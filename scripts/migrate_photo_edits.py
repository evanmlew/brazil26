"""Re-key data/photo-edits.json after a re-export changes every photo id.

Photo ids are `slug(filename) + sha1(file bytes)[:10]`, so re-exporting the same
photo at a new size mints a new id and orphans its editorial entry — captions,
titles, species, legId, ordering, exclusions. Filenames survive a re-export, so
they are the stable join key.

Usage:

    python scripts\\migrate_photo_edits.py <old-catalog> <new-catalog> <photo-edits.json>

The old catalog is the pre-re-export copy (git has it, or use a snapshot). Safe
to re-run: entries already carrying a current id are left alone.

**Worktree staleness check:** a `git worktree` freezes `data/photo-edits.json` at
whatever `rev` was current when the worktree branched. If review edits were made
and pushed to `main` afterward, migrating from that stale copy re-keys old
captions/order/exclusions onto the new ids and silently discards the newer ones —
even though nothing was actually lost from `main`. Before running this script,
this checks the `edits` file's `rev` against `origin/<default-branch>`'s copy and
refuses to proceed if the remote is ahead. Pass `--skip-git-check` only when you
are certain `edits` already reflects the latest published edits (e.g. running in
the main checkout itself, or offline).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def id_by_filename(catalog_path: Path) -> dict[str, str]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    return {photo["filename"]: photo["id"] for photo in catalog["photos"]}


def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def check_not_stale(edits_path: Path, local_rev: int) -> None:
    """Warn-and-abort if origin's default branch has a newer photo-edits.json.

    Best-effort: any git failure (not a repo, no network, no origin) is treated
    as "can't tell" and just prints a caution rather than blocking the run.
    """
    repo_root = _run_git(["rev-parse", "--show-toplevel"], edits_path.parent)
    if repo_root is None:
        print("(not a git repo — skipping worktree-staleness check)")
        return

    rel_path = edits_path.resolve().relative_to(Path(repo_root).resolve()).as_posix()

    _run_git(["fetch", "origin", "--quiet"], Path(repo_root))
    default_ref = _run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], Path(repo_root))
    default_branch = default_ref.rsplit("/", 1)[-1] if default_ref else "main"

    remote_json = _run_git(
        ["show", f"origin/{default_branch}:{rel_path}"], Path(repo_root)
    )
    if remote_json is None:
        print(f"(couldn't read origin/{default_branch}:{rel_path} — skipping staleness check)")
        return

    try:
        remote_rev = json.loads(remote_json)["rev"]
    except (json.JSONDecodeError, KeyError):
        print("(couldn't parse remote photo-edits.json rev — skipping staleness check)")
        return

    if remote_rev > local_rev:
        raise SystemExit(
            f"\nSTOP: origin/{default_branch}'s {rel_path} is at rev {remote_rev}, "
            f"but the copy you're about to migrate is only rev {local_rev}.\n"
            "Someone edited captions/order/exclusions in the review tool and pushed "
            "since this worktree branched — migrating now would re-key the STALE "
            "edits onto the new photo ids and bury the newer ones.\n\n"
            f"Fix: pull the current edits first, e.g.\n"
            f"  git show origin/{default_branch}:{rel_path} > {edits_path}\n"
            "then re-run this script. Pass --skip-git-check if you are certain "
            f"{edits_path} already reflects the latest published edits."
        )
    print(f"OK: local rev {local_rev} >= origin/{default_branch} rev {remote_rev}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_catalog", type=Path, help="Catalog JSON from before the re-export")
    parser.add_argument("new_catalog", type=Path, help="Catalog JSON rebuilt from the new export")
    parser.add_argument("edits", type=Path, help="data/photo-edits.json to re-key in place")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    parser.add_argument(
        "--skip-git-check",
        action="store_true",
        help="Skip the origin/<default-branch> staleness check (see module docstring)",
    )
    args = parser.parse_args()

    document_preview = json.loads(args.edits.read_text(encoding="utf-8"))
    if not args.skip_git_check:
        check_not_stale(args.edits, document_preview.get("rev", 0))

    old_ids = id_by_filename(args.old_catalog)
    new_ids = id_by_filename(args.new_catalog)

    # old id -> new id, joined on the filename both catalogs agree on
    remap = {
        old_id: new_ids[filename]
        for filename, old_id in old_ids.items()
        if filename in new_ids
    }
    current = set(new_ids.values())

    document = document_preview
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
