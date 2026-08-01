"""Re-key data/photo-edits.json after a re-export changes every photo id.

Photo ids are `slug(filename) + sha1(file bytes)[:10]`, so re-exporting the same
photo at a new size mints a new id and orphans its editorial entry — captions,
titles, species, legId, ordering, exclusions. Filenames survive a re-export, so
they are the stable join key.

Usage:

    python scripts\\migrate_photo_edits.py <old-catalog> <new-catalog> <photo-edits.json>

The old catalog is the pre-re-export copy (git has it, or use a snapshot). Safe
to re-run: entries already carrying a current id are left alone.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def id_by_filename(catalog_path: Path) -> dict[str, str]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    return {photo["filename"]: photo["id"] for photo in catalog["photos"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_catalog", type=Path, help="Catalog JSON from before the re-export")
    parser.add_argument("new_catalog", type=Path, help="Catalog JSON rebuilt from the new export")
    parser.add_argument("edits", type=Path, help="data/photo-edits.json to re-key in place")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    args = parser.parse_args()

    old_ids = id_by_filename(args.old_catalog)
    new_ids = id_by_filename(args.new_catalog)

    # old id -> new id, joined on the filename both catalogs agree on
    remap = {
        old_id: new_ids[filename]
        for filename, old_id in old_ids.items()
        if filename in new_ids
    }
    current = set(new_ids.values())

    document = json.loads(args.edits.read_text(encoding="utf-8"))
    entries = document["photos"]

    migrated: dict[str, dict] = {}
    moved = kept = orphaned = 0
    orphans = []
    for key, value in entries.items():
        if key in current:  # already current — re-run, or an untouched photo
            migrated[key] = value
            kept += 1
        elif key in remap:
            migrated[remap[key]] = value
            moved += 1
        else:
            # No matching filename in the new export. Keep the entry rather than
            # silently dropping someone's caption; report it for a human call.
            migrated[key] = value
            orphaned += 1
            orphans.append((key, value.get("title") or "(no title)"))

    print(f"old catalog: {len(old_ids)} photos    new catalog: {len(new_ids)} photos")
    print(f"edits entries: {len(entries)}")
    print(f"  re-keyed to a new id : {moved}")
    print(f"  already current      : {kept}")
    print(f"  orphaned (kept as-is): {orphaned}")
    if orphans:
        print("\nThese entries have no matching filename in the new export:")
        for key, title in orphans[:12]:
            print(f"  {key}  {title}")
        if len(orphans) > 12:
            print(f"  ... and {len(orphans) - 12} more")

    unedited = sorted(set(new_ids.values()) - set(migrated))
    if unedited:
        print(f"\n{len(unedited)} photo(s) in the new export have no edits entry (expected for new photos).")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    backup = args.edits.with_suffix(args.edits.suffix + ".bak")
    shutil.copy2(args.edits, backup)
    document["photos"] = migrated
    args.edits.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote {args.edits}  (previous version backed up to {backup.name})")


if __name__ == "__main__":
    main()
