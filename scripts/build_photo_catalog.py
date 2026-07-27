"""Build a reviewable photo catalog from the private Lightroom export folder."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image


IMAGE_EXTENSIONS = {".jpg", ".jpeg"}
EXIF_TAGS = {value: key for key, value in ExifTags.TAGS.items()}


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


def extract_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        exif = image.getexif()
        gps = exif.get_ifd(EXIF_TAGS["GPSInfo"]) if EXIF_TAGS["GPSInfo"] in exif else {}
        gps = {ExifTags.GPSTAGS.get(key, key): value for key, value in gps.items()}
        capture_value = (
            exif.get(EXIF_TAGS.get("DateTimeOriginal"))
            or exif.get(EXIF_TAGS.get("DateTimeDigitized"))
            or exif.get(EXIF_TAGS.get("DateTime"))
        )
        exported_value = exif.get(EXIF_TAGS.get("DateTime"))
        latitude = coordinate(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef", ""))
        longitude = coordinate(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef", ""))
        sha1 = hashlib.sha1(path.read_bytes()).hexdigest()
        flags = []
        if latitude is None or longitude is None:
            flags.append("no-gps")

        return {
            "id": f"{slugify(path.stem)}-{sha1[:10]}",
            "filename": path.name,
            "width": image.width,
            "height": image.height,
            "bytes": path.stat().st_size,
            "sha1": sha1,
            "date": parse_exif_datetime(capture_value),
            "exportedAt": parse_exif_datetime(exported_value),
            "latitude": latitude,
            "longitude": longitude,
            "camera": {
                "make": exif.get(EXIF_TAGS.get("Make")),
                "model": exif.get(EXIF_TAGS.get("Model")),
            },
            "title": "",
            "body": "",
            "kicker": "",
            "chips": [],
            "star": False,
            "subjectId": "",
            "locationName": "",
            "legId": "",
            "order": None,
            "tags": [],
            "species": "",
            "confidence": "",
            "featured": False,
            "flags": flags,
            "assets": {
                "original": "",
                "card": "",
                "thumb": "",
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Private folder containing exported JPEGs")
    parser.add_argument("output", type=Path, help="Catalog JSON output path")
    args = parser.parse_args()

    photos = [
        extract_metadata(path)
        for path in sorted(args.input.iterdir(), key=lambda candidate: candidate.name.lower())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    catalog = {
        "schemaVersion": 1,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "imageCount": len(photos),
        },
        "photos": photos,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(photos)} photos to {args.output}")


if __name__ == "__main__":
    main()
