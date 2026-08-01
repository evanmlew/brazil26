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
# "DSC00036-LAPTOP-73TG5O6M.jpg". They are stale duplicates at the wrong size,
# and ingesting them mints phantom catalog entries.
CONFLICT_RE = re.compile(r"-(?:LAPTOP|DESKTOP|PC|MACBOOK)-[A-Z0-9]{5,}$", re.IGNORECASE)
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


def extract_metadata(path: Path) -> dict[str, Any]:
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
            "id": f"{slugify(path.stem)}-{pixels[:10]}",
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

    candidates = [
        path
        for path in sorted(args.input.iterdir(), key=lambda candidate: candidate.name.lower())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    skipped = [path for path in candidates if CONFLICT_RE.search(path.stem)]
    photos = [extract_metadata(path) for path in candidates if path not in skipped]
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
    if skipped:
        print(f"\nSkipped {len(skipped)} sync conflict copy/copies (not real exports):")
        for path in skipped[:12]:
            print(f"  {path.name}")
        if len(skipped) > 12:
            print(f"  ... and {len(skipped) - 12} more")
        print("Delete them from the export folder to keep it tidy.")


if __name__ == "__main__":
    main()
