"""Build a reviewable photo catalog from the private Lightroom export folder."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image


IMAGE_EXTENSIONS = {".jpg", ".jpeg"}
# OneDrive/Dropbox conflict copies land beside the real export as
# "DSC00036-LAPTOP-73TG5O6M.jpg". Normally they are stale duplicates at the wrong
# size and ingesting them mints phantom catalog entries — so they are skipped.
#
# But the failure can arrive inverted: OneDrive has been seen leaving the *base*
# name as a 0-byte placeholder and putting the real bytes in the conflict copy. A
# blind skip then drops the photo entirely (or crashes on the empty file), so a
# conflict copy is only skipped when a non-empty base file actually exists.
CONFLICT_RE = re.compile(r"^(?P<base>.+?)-(?:LAPTOP|DESKTOP|PC|MACBOOK)-[A-Z0-9]{5,}$", re.IGNORECASE)
EXIF_TAGS = {value: key for key, value in ExifTags.TAGS.items()}
OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "photo"


def rational_to_float(value: Any) -> float:
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return float(value.numerator) / float(value.denominator)
    return float(value)


def coordinate(value: Any, reference: str) -> float | None:
    if not value or len(value) != 3:
        return None
    degrees, minutes, seconds = (rational_to_float(part) for part in value)
    result = degrees + minutes / 60 + seconds / 3600
    return -result if reference in {"S", "W"} else result


def parse_exif_datetime(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S").isoformat()
    except ValueError:
        return None


def parse_offset(value: Any) -> timezone | None:
    """Parse an EXIF OffsetTime* string like '-03:00' into a timezone."""
    if not isinstance(value, str):
        return None
    match = OFFSET_RE.match(value.strip())
    if not match:
        return None
    sign, hours, minutes = match.groups()
    delta = timedelta(hours=int(hours), minutes=int(minutes))
    if sign == "-":
        delta = -delta
    return timezone(delta)


def parse_capture_datetime(value: Any, offset_value: Any) -> tuple[str | None, str | None]:
    """Combine an EXIF DateTimeOriginal string with its OffsetTime* string.

    Returns (isoformat-with-offset-when-known, raw-offset-string-or-None).
    """
    if not isinstance(value, str):
        return None, None
    try:
        naive = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, None
    tz = parse_offset(offset_value)
    if tz is None:
        return naive.isoformat(), None
    return naive.replace(tzinfo=tz).isoformat(), offset_value.strip()


def pixel_digest(image: Image.Image) -> str:
    """Hash what the photo *looks like*, not the bytes it happens to be stored in.

    Photo ids feed the published filenames, so they need two properties that pull
    against each other: stable across a re-export that changed nothing, and different
    the moment the image itself changes (otherwise browser and CDN caches keep serving
    the old picture).

    Hashing the exported file's bytes gets the second property but not the first.
    Lightroom stamps a fresh export timestamp into every file it writes, so re-exporting
    an untouched photo at identical settings still produced a different sha1 -> a
    different id -> a different filename -> git stored a full second copy of all 168
    derivatives (~125 MB) and kept the originals forever.

    The decoded pixel buffer has both properties. Lightroom's render is deterministic,
    so identical develop settings and export size decode to identical pixels no matter
    how many times you export; any real edit (exposure, crop, size, quality) changes
    them. Mode and size are folded in so two images can't collide through a raw buffer
    that happens to match under a different interpretation.
    """
    digest = hashlib.sha1()
    digest.update(f"{image.mode}:{image.width}x{image.height}:".encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


def extract_metadata(path: Path, stem: str | None = None) -> dict[str, Any]:
    """Read one export. `stem` overrides the id source when `path` is a recovered
    conflict copy, so `X-LAPTOP-1234.jpg` still mints the id `X` would have."""
    with Image.open(path) as image:
        exif = image.getexif()
        # DateTimeOriginal/DateTimeDigitized and the OffsetTime* tags that
        # carry the camera's UTC offset live in the Exif sub-IFD, not IFD0 —
        # exif.get(...) alone always returns None for them.
        exif_ifd = exif.get_ifd(ExifTags.IFD.Exif) if ExifTags.IFD.Exif in exif else {}
        gps = exif.get_ifd(EXIF_TAGS["GPSInfo"]) if EXIF_TAGS["GPSInfo"] in exif else {}
        gps = {ExifTags.GPSTAGS.get(key, key): value for key, value in gps.items()}
        capture_value = (
            exif_ifd.get(EXIF_TAGS.get("DateTimeOriginal"))
            or exif_ifd.get(EXIF_TAGS.get("DateTimeDigitized"))
            or exif.get(EXIF_TAGS.get("DateTime"))
        )
        offset_value = (
            exif_ifd.get(EXIF_TAGS.get("OffsetTimeOriginal"))
            or exif_ifd.get(EXIF_TAGS.get("OffsetTimeDigitized"))
            or exif_ifd.get(EXIF_TAGS.get("OffsetTime"))
        )
        # IFD0 DateTime is the file's modify/export timestamp (e.g. when
        # Lightroom wrote the export), which is unrelated to when the photo
        # was actually taken.
        exported_value = exif.get(EXIF_TAGS.get("DateTime"))
        capture_iso, capture_offset = parse_capture_datetime(capture_value, offset_value)
        latitude = coordinate(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef", ""))
        longitude = coordinate(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef", ""))
        sha1 = hashlib.sha1(path.read_bytes()).hexdigest()
        pixels = pixel_digest(image)
        flags = []
        if latitude is None or longitude is None:
            flags.append("no-gps")

        return {
            "id": f"{slugify(stem or path.stem)}-{pixels[:10]}",
            "filename": path.name,
            "width": image.width,
            "height": image.height,
            "bytes": path.stat().st_size,
            "sha1": sha1,
            "pixelSha1": pixels,
            "date": capture_iso,
            "utcOffset": capture_offset,
            "exportedAt": parse_exif_datetime(exported_value),
            "latitude": latitude,
            "longitude": longitude,
            "camera": {
                "make": exif.get(EXIF_TAGS.get("Make")),
                "model": exif.get(EXIF_TAGS.get("Model")),
            },
            "title": "",
            "body": "",
            "chips": [],
            "star": False,
            "subjectId": "",
            "locationName": "",
            "legId": "",
            "order": None,
            "species": "",
            "featured": False,
            # Build-time data-quality markers only ("no-gps"). The site never
            # renders these; the review tool shows them as a warning badge.
            "flags": flags,
            "assets": {
                "original": "",
                "card": "",
                "thumb": "",
            },
        }


def resolve_sources(folder: Path) -> tuple[list[tuple[Path, str]], dict[str, list]]:
    """Decide which files on disk are real exports, and what stem each one owns.

    Returns `[(path, canonical_stem), ...]` plus a report of everything that was
    skipped, recovered, or is broken.
    """
    candidates = [
        path
        for path in sorted(folder.iterdir(), key=lambda candidate: candidate.name.lower())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    empty = [path for path in candidates if path.stat().st_size == 0]
    usable = [path for path in candidates if path.stat().st_size > 0]
    usable_stems = {path.stem for path in usable}

    report: dict[str, list] = {"skipped": [], "recovered": [], "empty": [], "lost": [], "ambiguous": []}
    claimed: dict[str, Path] = {}
    sources: list[tuple[Path, str]] = []
    # Provisional: a conflict copy can still lose the stem to a larger one below,
    # and reporting a loser as "recovered" would tell you to rename the wrong file
    # over the base. Only the survivors make it into the report.
    recovered: dict[Path, str] = {}

    for path in usable:
        match = CONFLICT_RE.match(path.stem)
        if match is None:
            stem = path.stem
        elif match.group("base") in usable_stems:
            report["skipped"].append(path.name)  # the real export is right there
            continue
        else:
            stem = match.group("base")
            recovered[path] = f"{stem}{path.suffix}"

        if stem in claimed:
            # Two files both claim one stem (e.g. several conflict copies, no base).
            # Keep the largest and say so, rather than silently picking one.
            winner, loser = sorted((claimed[stem], path), key=lambda p: p.stat().st_size, reverse=True)
            report["ambiguous"].append((stem, winner.name, loser.name))
            claimed[stem] = winner
            sources = [(p, s) for p, s in sources if s != stem]
            sources.append((winner, stem))
            continue

        claimed[stem] = path
        sources.append((path, stem))

    for path in empty:
        # An empty file is never a real photo. It only matters whether some
        # non-empty file covers the same shot — and the only relationship that
        # means that is the conflict-copy one. Matching on a bare name prefix
        # instead would let an unrelated export "rescue" a genuinely lost photo
        # (`IMG_1.jpg` empty, `IMG_1-2.jpg` real) and skip the hard-fail below,
        # which is the silent loss this whole function exists to prevent.
        match = CONFLICT_RE.match(path.stem)
        base = match.group("base") if match else path.stem
        rescued = path.stem in claimed or base in claimed
        (report["empty"] if rescued else report["lost"]).append(path.name)

    sources.sort(key=lambda item: item[1].lower())
    report["recovered"] = [(path.name, recovered[path]) for path, _ in sources if path in recovered]
    return sources, report


def diff_catalogs(previous: Path, photos: list[dict[str, Any]]) -> list[str]:
    """Report what changed against the catalog already sitting at the output path."""
    try:
        old = json.loads(previous.read_text(encoding="utf-8"))["photos"]
    except (OSError, KeyError, json.JSONDecodeError):
        return []

    old_by_id = {photo["id"]: photo for photo in old}
    old_by_file = {photo["filename"]: photo for photo in old}
    new_by_id = {photo["id"]: photo for photo in photos}

    lines: list[str] = []
    moved = [
        (photo["filename"], old_by_file[photo["filename"]]["id"], photo["id"])
        for photo in photos
        if photo["filename"] in old_by_file and old_by_file[photo["filename"]]["id"] != photo["id"]
    ]
    added = [photo for photo in photos if photo["id"] not in old_by_id and photo["filename"] not in old_by_file]
    removed = [photo for photo in old if photo["id"] not in new_by_id and photo["filename"] not in
               {p["filename"] for p in photos}]

    if added:
        lines.append(f"Added {len(added)}:")
        lines += [f"  + {photo['id']}  ({photo['filename']})" for photo in added]
    if removed:
        lines.append(f"Removed {len(removed)}:")
        lines += [f"  - {photo['id']}  ({photo['filename']})" for photo in removed]
    if moved:
        lines.append(f"Re-keyed {len(moved)} — the image itself changed, so run migrate_photo_edits.py:")
        lines += [f"  ~ {name}: {before} -> {after}" for name, before, after in moved]
    if not lines:
        lines.append("No photos added, removed, or re-keyed.")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Private folder containing exported JPEGs")
    parser.add_argument("output", type=Path, help="Catalog JSON output path")
    args = parser.parse_args()

    sources, report = resolve_sources(args.input)

    if report["lost"]:
        raise SystemExit(
            f"\n{len(report['lost'])} file(s) in {args.input} are 0 bytes with no usable copy beside them.\n"
            "These are almost always OneDrive placeholders that never finished syncing. Open the folder\n"
            "in Explorer, right-click > 'Always keep on this device', let it download, and re-run:\n"
            + "\n".join(f"  {name}" for name in report["lost"])
        )

    previous = args.output if args.output.exists() else None
    photos = [extract_metadata(path, stem) for path, stem in sources]
    catalog = {
        "schemaVersion": 1,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "imageCount": len(photos),
        },
        "photos": photos,
    }
    diff = diff_catalogs(previous, photos) if previous else []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(photos)} photos to {args.output}")

    if diff:
        print()
        for line in diff:
            print(line)

    if report["recovered"]:
        print(
            f"\nRecovered {len(report['recovered'])} sync conflict copy/copies whose base file was "
            "missing or empty — the id is keyed to the base name, so nothing downstream moves:"
        )
        for name, base in report["recovered"]:
            print(f"  {name}  (used as {base})")
        print("Rename these over their empty base files in the export folder to keep it tidy.")

    if report["ambiguous"]:
        print(f"\n{len(report['ambiguous'])} stem(s) claimed by more than one file; kept the largest:")
        for stem, winner, loser in report["ambiguous"]:
            print(f"  {stem}: kept {winner}, ignored {loser}")

    if report["empty"]:
        print(f"\nIgnored {len(report['empty'])} empty (0-byte) file(s); a real copy exists for each:")
        for name in report["empty"][:12]:
            print(f"  {name}")
        if len(report["empty"]) > 12:
            print(f"  ... and {len(report['empty']) - 12} more")

    if report["skipped"]:
        print(f"\nSkipped {len(report['skipped'])} sync conflict copy/copies (not real exports):")
        for name in report["skipped"][:12]:
            print(f"  {name}")
        if len(report["skipped"]) > 12:
            print(f"  ... and {len(report['skipped']) - 12} more")
        print("Delete them from the export folder to keep it tidy.")


if __name__ == "__main__":
    main()
