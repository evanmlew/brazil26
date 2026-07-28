"""Create public card and thumbnail derivatives from the private export folder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageOps

# Long-edge sizes. The journal shows photos full-bleed with a Ken Burns zoom
# that scales up to ~1.14x, so on a retina display the pane needs ~2900-3300
# device px — a single 3000px card covers that without a separate 2x variant.
THUMB = 360
CARD = 3000


def derivative(image: Image.Image, longest_edge: int, output: Path, quality: int = 80) -> int:
    """Write a downscaled JPEG. Never upscales. Returns the long edge actually written."""
    normalized = ImageOps.exif_transpose(image).convert("RGB")
    # thumbnail() is a no-op when the source is already smaller, so the file
    # written may be shorter than longest_edge — report what we really produced.
    normalized.thumbnail((longest_edge, longest_edge), Image.Resampling.LANCZOS)
    normalized.save(output, "JPEG", quality=quality, optimize=True, progressive=True)
    return max(normalized.size)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Private folder containing exported JPEGs")
    parser.add_argument("catalog", type=Path, help="Photo catalog JSON")
    parser.add_argument("output", type=Path, help="Public assets folder")
    parser.add_argument("--card", type=int, default=CARD, help=f"Card long edge (default {CARD})")
    parser.add_argument("--quality", type=int, default=80, help="JPEG quality (default 80)")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    files = {path.name: path for path in args.input.iterdir() if path.is_file()}
    args.output.mkdir(parents=True, exist_ok=True)

    undersized = []
    for photo in catalog["photos"]:
        source = files.get(photo["filename"])
        if source is None:
            raise FileNotFoundError(f"Catalog photo is missing from export folder: {photo['filename']}")
        card_name = f"{photo['id']}-card.jpg"
        thumb_name = f"{photo['id']}-thumb.jpg"
        with Image.open(source) as image:
            source_edge = max(ImageOps.exif_transpose(image).size)
            got = derivative(image, args.card, args.output / card_name, args.quality)
            derivative(image, THUMB, args.output / thumb_name, args.quality)
        if got < args.card:
            undersized.append((photo["filename"], source_edge))
        photo["assets"] = {
            "original": "",
            "card": f"assets/photos/{card_name}",
            "thumb": f"assets/photos/{thumb_name}",
        }

    args.catalog.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote derivatives for {len(catalog['photos'])} photos to {args.output}")
    if undersized:
        print(
            f"\n{len(undersized)} source file(s) are smaller than --card ({args.card}px); "
            "the card is just a copy at source size and will look soft full-bleed. "
            f"Re-export these from Lightroom at {args.card}px+ on the long edge:"
        )
        for name, edge in sorted(undersized, key=lambda item: item[1])[:12]:
            print(f"  {name}  ({edge}px)")
        if len(undersized) > 12:
            print(f"  ... and {len(undersized) - 12} more")


if __name__ == "__main__":
    main()
