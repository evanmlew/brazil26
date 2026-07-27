"""Create public card and thumbnail derivatives from the private export folder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageOps


def derivative(image: Image.Image, longest_edge: int, output: Path) -> None:
    normalized = ImageOps.exif_transpose(image).convert("RGB")
    normalized.thumbnail((longest_edge, longest_edge), Image.Resampling.LANCZOS)
    normalized.save(output, "JPEG", quality=88, optimize=True, progressive=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Private folder containing exported JPEGs")
    parser.add_argument("catalog", type=Path, help="Photo catalog JSON")
    parser.add_argument("output", type=Path, help="Public assets folder")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    files = {path.name: path for path in args.input.iterdir() if path.is_file()}
    args.output.mkdir(parents=True, exist_ok=True)
    for photo in catalog["photos"]:
        source = files.get(photo["filename"])
        if source is None:
            raise FileNotFoundError(f"Catalog photo is missing from export folder: {photo['filename']}")
        card_name = f"{photo['id']}-card.jpg"
        thumb_name = f"{photo['id']}-thumb.jpg"
        with Image.open(source) as image:
            derivative(image, 1200, args.output / card_name)
            derivative(image, 360, args.output / thumb_name)
        photo["assets"] = {
            "original": "",
            "card": f"assets/photos/{card_name}",
            "thumb": f"assets/photos/{thumb_name}",
        }
    args.catalog.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote derivatives for {len(catalog['photos'])} photos to {args.output}")


if __name__ == "__main__":
    main()
