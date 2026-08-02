"""Small previews of the export, for reading a batch of photos quickly.

Writing captions means actually looking at every frame, and the published cards are
2048-3840px — far too heavy to page through in bulk (and pointlessly so: judging
subject, place and sequence needs maybe 900px). This writes throwaway previews into
a gitignored scratch folder.

    python scripts\\make_previews.py photos previews
    python scripts\\make_previews.py photos previews --catalog data\\photo-catalog.json
    python scripts\\make_previews.py photos previews --catalog data\\photo-catalog.json --uncaptioned data\\photo-edits.json
    python scripts\\make_previews.py photos previews --filter "Por Maycon*"

With `--catalog`, previews are named `<photo-id>.jpg` so they map straight back to
catalog / photo-edits entries. Without it they keep the source filename.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path

from PIL import Image, ImageOps

MAX_EDGE = 900
QUALITY = 78
IMAGE_EXTENSIONS = {".jpg", ".jpeg"}


def load_catalog(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    return {photo["filename"]: photo for photo in json.loads(path.read_text(encoding="utf-8"))["photos"]}


def captioned_ids(path: Path | None) -> set[str] | None:
    """Ids that already have a caption — everything else is what needs looking at."""
    if path is None:
        return None
    edits = json.loads(path.read_text(encoding="utf-8"))["photos"]
    return {
        photo_id
        for photo_id, entry in edits.items()
        if (entry.get("body") or entry.get("caption") or "").strip()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Private folder containing exported JPEGs")
    parser.add_argument("output", type=Path, help="Scratch folder for previews (gitignored)")
    parser.add_argument("--catalog", type=Path, help="Photo catalog JSON; names previews by photo id")
    parser.add_argument("--uncaptioned", type=Path, help="photo-edits.json; only preview photos with no body yet")
    parser.add_argument("--filter", dest="pattern", help="Only files matching this glob, e.g. \"Por Maycon*\"")
    parser.add_argument("--max", type=int, default=MAX_EDGE, help=f"Long edge in px (default {MAX_EDGE})")
    parser.add_argument("--quality", type=int, default=QUALITY, help=f"JPEG quality (default {QUALITY})")
    args = parser.parse_args()

    if args.uncaptioned and not args.catalog:
        raise SystemExit("--uncaptioned needs --catalog too (it matches on photo id).")

    catalog = load_catalog(args.catalog)
    captioned = captioned_ids(args.uncaptioned)

    sources = sorted(
        path
        for path in args.input.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and path.stat().st_size > 0
    )
    if args.pattern:
        sources = [path for path in sources if fnmatch.fnmatch(path.name, args.pattern)]

    args.output.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in sources:
        photo = catalog.get(path.name)
        if catalog and photo is None:
            continue  # not a real export as far as the catalog is concerned
        if captioned is not None and photo["id"] in captioned:
            continue
        name = f"{photo['id']}.jpg" if photo else f"{path.stem}.jpg"
        with Image.open(path) as image:
            preview = ImageOps.exif_transpose(image).convert("RGB")
            preview.thumbnail((args.max, args.max), Image.Resampling.LANCZOS)
            preview.save(args.output / name, "JPEG", quality=args.quality, optimize=True)
        written += 1
        print(f"  {name}  ({preview.width}x{preview.height})", flush=True)

    print(f"\nWrote {written} preview(s) to {args.output}")
    if not written:
        print("Nothing matched — check --filter/--uncaptioned.")


if __name__ == "__main__":
    main()
