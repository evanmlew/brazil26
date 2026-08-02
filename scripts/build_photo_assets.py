"""Create public card and thumbnail derivatives from the private export folder.

Quality rules of the road:

* The Lightroom export is the master: 3840px on the long edge, 4:4:4, sRGB,
  quality ~100. Never re-encode it at the same pixel size for the same format —
  that is pure generation loss (the old pipeline halved every file at identical
  dimensions, dropped chroma to 4:2:0, and threw away the ICC profile).
* The primary card is AVIF at full 3840px. On a 27" 4K the photo pane is ~2880
  device px wide, and up to 3840 when the map is collapsed, so the full export
  size is genuinely needed — anything smaller gets upsampled by the browser.
* A smaller JPEG card is written alongside as a fallback for browsers without
  AVIF. It is deliberately not full size: it exists for correctness, not for
  4K displays, and a full-size JPEG set would triple the repository.
* Downscaled output gets a light unsharp mask, because Lightroom applies
  "Sharpen for Screen" on export and a bare LANCZOS resample does not.
* Nothing published carries EXIF. The JPEG passthrough path strips metadata at
  the marker level (lossless, keeps ICC); re-encodes simply never write it.
* Derivatives that already exist are kept, never rebuilt. A photo id is a hash of
  the decoded pixels, so an existing `<id>-card.avif` is by definition the right
  picture — but the AVIF encoder is *not* byte-reproducible, so re-encoding it
  produces a different file with identical content. Committing that churn cost
  ~92 MB of duplicate binaries in git history on one re-export. The encode
  settings are recorded in `build-settings.json` beside the derivatives; if they
  change, everything is rebuilt (because then the output really is different).
  `--force` overrides.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

SETTINGS_NAME = "build-settings.json"

THUMB = 360
CARD = 3840          # AVIF, full export size
FALLBACK = 2048      # JPEG, non-AVIF browsers only

AVIF_QUALITY = 68
FALLBACK_QUALITY = 85
THUMB_QUALITY = 88
AVIF_SPEED = 6       # libaom speed/effort tradeoff, 0 slowest .. 10 fastest

SHARPEN_RADIUS = 0.7
SHARPEN_PERCENT = 60
SHARPEN_THRESHOLD = 2

# JPEG APPn segments worth keeping: APP0 (JFIF), APP2 (ICC colour profile),
# APP14 (Adobe colour-transform marker). Everything else — APP1 (EXIF/GPS/XMP),
# APP13 (IPTC) — is metadata we do not publish.
_KEEP_APP_MARKERS = {0xE0, 0xE2, 0xEE}
_EXIF_ORIENTATION_TAG = 0x0112


def strip_jpeg_metadata(data: bytes) -> bytes:
    """Drop EXIF/XMP/IPTC without touching the compressed image data.

    Walks the JPEG marker segments and copies everything except the metadata
    APPn blocks. The entropy-coded scan is copied byte for byte, so this is
    lossless. Returns the input unchanged if the file does not parse cleanly.
    """
    if data[:2] != b"\xff\xd8":
        return data

    out = bytearray(b"\xff\xd8")
    i, n = 2, len(data)
    while i < n - 1:
        if data[i] != 0xFF:
            return data  # not on a marker boundary; leave the file alone
        marker = data[i + 1]
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # standalone, no payload
            out += data[i : i + 2]
            i += 2
            continue
        if marker == 0xDA:  # start of scan — the rest is image data
            out += data[i:]
            return bytes(out)
        if i + 4 > n:
            return data
        segment_end = i + 2 + int.from_bytes(data[i + 2 : i + 4], "big")
        if segment_end <= i + 2 or segment_end > n:
            return data
        is_metadata = marker == 0xFE or (0xE0 <= marker <= 0xEF and marker not in _KEEP_APP_MARKERS)
        if not is_metadata:
            out += data[i:segment_end]
        i = segment_end
    return data  # ran off the end without finding a scan; don't risk it


def exif_orientation(image: Image.Image) -> int:
    """Return the EXIF orientation, or 1 when absent/unreadable."""
    try:
        return image.getexif().get(_EXIF_ORIENTATION_TAG, 1) or 1
    except Exception:
        return 1


def prepare(image: Image.Image, longest_edge: int, sharpen: int) -> tuple[Image.Image, bytes | None]:
    """Orient, downscale (never up), and re-sharpen. Returns the image and its ICC profile."""
    oriented = ImageOps.exif_transpose(image)
    icc = oriented.info.get("icc_profile")
    rgb = oriented.convert("RGB")
    before = max(rgb.size)
    rgb.thumbnail((longest_edge, longest_edge), Image.Resampling.LANCZOS)
    if sharpen and max(rgb.size) < before:
        rgb = rgb.filter(ImageFilter.UnsharpMask(SHARPEN_RADIUS, sharpen, SHARPEN_THRESHOLD))
    return rgb, icc


def write_avif(image: Image.Image, longest_edge: int, output: Path, quality: int, sharpen: int) -> int:
    rgb, icc = prepare(image, longest_edge, sharpen)
    rgb.save(output, "AVIF", quality=quality, speed=AVIF_SPEED, **({"icc_profile": icc} if icc else {}))
    return max(rgb.size)


def write_jpeg(image: Image.Image, longest_edge: int, output: Path, quality: int, sharpen: int) -> int:
    rgb, icc = prepare(image, longest_edge, sharpen)
    rgb.save(
        output,
        "JPEG",
        quality=quality,
        # 4:4:4 — the default (4:2:0) halves colour resolution in both axes and
        # visibly softens saturated edges.
        subsampling=0,
        optimize=True,
        progressive=True,
        **({"icc_profile": icc} if icc else {}),
    )
    return max(rgb.size)


def write_jpeg_card(source: Path, output: Path, longest_edge: int, quality: int, sharpen: int) -> tuple[int, bool]:
    """JPEG fallback card. Copies the source verbatim when no resize is needed."""
    with Image.open(source) as image:
        edge = max(ImageOps.exif_transpose(image).size)
        if not (image.format == "JPEG" and edge <= longest_edge and exif_orientation(image) == 1):
            return write_jpeg(image, longest_edge, output, quality, sharpen), False
    output.write_bytes(strip_jpeg_metadata(source.read_bytes()))
    return edge, True


def encode_settings(args: argparse.Namespace) -> dict[str, int | float]:
    """Every knob that changes the produced bytes.

    Photo ids cover the *source* pixels, not the encode, so they cannot tell us
    that `--card 3000` now means something different from the 3840px files already
    on disk. This does.
    """
    return {
        "card": args.card,
        "fallback": args.fallback,
        "avifQuality": args.quality,
        "avifSpeed": AVIF_SPEED,
        "fallbackQuality": FALLBACK_QUALITY,
        "thumb": THUMB,
        "thumbQuality": THUMB_QUALITY,
        "sharpen": args.sharpen,
        "sharpenRadius": SHARPEN_RADIUS,
        "sharpenThreshold": SHARPEN_THRESHOLD,
    }


def read_settings(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def source_long_edge(source: Path) -> int:
    """Long edge of the source, without decoding it (header read only)."""
    with Image.open(source) as image:
        return max(image.size)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Private folder containing exported JPEGs")
    parser.add_argument("catalog", type=Path, help="Photo catalog JSON")
    parser.add_argument("output", type=Path, help="Public assets folder")
    parser.add_argument("--card", type=int, default=CARD, help=f"AVIF card long edge (default {CARD})")
    parser.add_argument("--fallback", type=int, default=FALLBACK, help=f"JPEG fallback long edge (default {FALLBACK})")
    parser.add_argument("--quality", type=int, default=AVIF_QUALITY, help=f"AVIF quality (default {AVIF_QUALITY})")
    parser.add_argument(
        "--sharpen",
        type=int,
        default=SHARPEN_PERCENT,
        help=f"Unsharp-mask percent applied after downscaling, 0 to disable (default {SHARPEN_PERCENT})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-encode derivatives that already exist (normally they are kept, to avoid pointless git churn)",
    )
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    files = {path.name: path for path in args.input.iterdir() if path.is_file()}
    args.output.mkdir(parents=True, exist_ok=True)

    settings = encode_settings(args)
    settings_path = args.output / SETTINGS_NAME
    previous = read_settings(settings_path)
    reuse = not args.force and previous == settings
    if args.force:
        print("--force: re-encoding every derivative.\n")
    elif previous is None:
        print(f"No {SETTINGS_NAME} yet — building everything, then recording the encode settings.\n")
    elif previous != settings:
        changed = sorted(k for k in settings if previous.get(k) != settings[k])
        print(f"Encode settings changed ({', '.join(changed)}) — rebuilding every derivative.\n")

    undersized: list[tuple[str, int]] = []
    avif_bytes = jpeg_bytes = thumb_bytes = 0
    built = kept = 0
    total = len(catalog["photos"])
    for index, photo in enumerate(catalog["photos"], 1):
        source = files.get(photo["filename"])
        if source is None:
            raise FileNotFoundError(f"Catalog photo is missing from export folder: {photo['filename']}")
        avif_name = f"{photo['id']}-card.avif"
        card_name = f"{photo['id']}-card.jpg"
        thumb_name = f"{photo['id']}-thumb.jpg"
        outputs = [args.output / avif_name, args.output / card_name, args.output / thumb_name]

        if reuse and all(path.is_file() and path.stat().st_size > 0 for path in outputs):
            # thumbnail() only ever shrinks, so this is what an encode would have produced.
            got = min(source_long_edge(source), args.card)
            kept += 1
            action = "kept"
        else:
            with Image.open(source) as image:
                got = write_avif(image, args.card, args.output / avif_name, args.quality, args.sharpen)
            write_jpeg_card(source, args.output / card_name, args.fallback, FALLBACK_QUALITY, args.sharpen)
            with Image.open(source) as image:
                write_jpeg(image, THUMB, args.output / thumb_name, THUMB_QUALITY, args.sharpen)
            built += 1
            action = "built"

        avif_bytes += (args.output / avif_name).stat().st_size
        jpeg_bytes += (args.output / card_name).stat().st_size
        thumb_bytes += (args.output / thumb_name).stat().st_size

        if got < args.card:
            undersized.append((photo["filename"], got))
        photo["assets"] = {
            "original": "",
            "card": f"assets/photos/{card_name}",
            "cardAvif": f"assets/photos/{avif_name}",
            "thumb": f"assets/photos/{thumb_name}",
        }
        print(f"  [{index}/{total}] {photo['filename']} -> {got}px ({action})", flush=True)

    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    args.catalog.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mb = 1024 * 1024
    print(f"\nWrote derivatives for {total} photos to {args.output}  ({built} built, {kept} kept unchanged)")
    print(f"  AVIF cards  @{args.card}px q{args.quality}: {avif_bytes/mb:6.1f} MB  ({avif_bytes/total/1024:.0f} KB avg)")
    print(f"  JPEG cards  @{args.fallback}px q{FALLBACK_QUALITY}: {jpeg_bytes/mb:6.1f} MB  ({jpeg_bytes/total/1024:.0f} KB avg)")
    print(f"  JPEG thumbs @{THUMB}px:          {thumb_bytes/mb:6.1f} MB")
    print(f"  total published:              {(avif_bytes+jpeg_bytes+thumb_bytes)/mb:6.1f} MB")

    referenced = {name for photo in catalog["photos"] for name in (
        f"{photo['id']}-card.avif", f"{photo['id']}-card.jpg", f"{photo['id']}-thumb.jpg")}
    orphans = sorted(
        path.name
        for path in args.output.iterdir()
        if path.is_file()
        and path.name not in referenced
        and path.name != SETTINGS_NAME
        and ("-card." in path.name or "-thumb." in path.name)
    )
    if orphans:
        print(
            f"\n{len(orphans)} derivative(s) in {args.output} are no longer referenced by the catalog. "
            "Delete them before committing — anything committed stays in git history forever:"
        )
        for name in orphans[:12]:
            print(f"  {name}")
        if len(orphans) > 12:
            print(f"  ... and {len(orphans) - 12} more")

    if undersized:
        print(
            f"\n{len(undersized)} source file(s) are smaller than --card ({args.card}px); "
            f"re-export these from Lightroom at {args.card}px on the long edge:"
        )
        for name, edge in sorted(undersized, key=lambda item: item[1])[:12]:
            print(f"  {name}  ({edge}px)")
        if len(undersized) > 12:
            print(f"  ... and {len(undersized) - 12} more")


if __name__ == "__main__":
    main()
