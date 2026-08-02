"""Make the private `photos\\` export folder reachable from a git worktree.

`photos/` is gitignored, so it exists only in the checkout it was copied into —
usually the OneDrive one. Every build script needs it, so working on this repo from
a `git worktree` (or a fresh clone) otherwise fails with an empty/missing folder.

This creates a directory junction from the current checkout to the real folder.
A junction costs no disk and needs no administrator rights on Windows; `--copy`
falls back to a real copy for filesystems that can't do it.

    python scripts\\link_photos.py                     # auto-detect the main worktree
    python scripts\\link_photos.py --source D:\\export  # point somewhere explicit
    python scripts\\link_photos.py --copy              # copy instead of linking
    python scripts\\link_photos.py --force             # replace what's already there
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

FOLDER = "photos"


def git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], capture_output=True, text=True, check=False,
        cwd=Path(__file__).resolve().parents[1],
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def main_worktree() -> Path | None:
    """The first entry of `git worktree list` is always the main working tree."""
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):])
    return None


def is_link(path: Path) -> bool:
    """True for a symlink or an NT directory junction (both are reparse points)."""
    if path.is_symlink():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def make_junction(source: Path, target: Path) -> bool:
    if os.name != "nt":
        try:
            target.symlink_to(source, target_is_directory=True)
            return True
        except OSError:
            return False
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(target), str(source)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(result.stdout or result.stderr, end="")
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, help=f"The real {FOLDER} folder (default: the main worktree's)")
    parser.add_argument("--copy", action="store_true", help="Copy the files instead of creating a junction")
    parser.add_argument("--force", action="store_true", help="Replace an existing photos folder/link")
    args = parser.parse_args()

    here = Path(__file__).resolve().parents[1]
    target = here / FOLDER

    source = args.source
    if source is None:
        main_tree = main_worktree()
        if main_tree is None:
            return fail("Not in a git checkout, and no --source given.")
        source = main_tree / FOLDER
        if source.resolve() == target.resolve():
            print(f"Already in the main worktree — {target} is the real folder. Nothing to do.")
            return 0
    source = source.resolve()

    if not source.is_dir():
        return fail(f"Source folder does not exist: {source}")
    count = len([p for p in source.iterdir() if p.is_file()])
    if count == 0:
        return fail(f"Source folder is empty: {source}")

    if target.exists() or target.is_symlink():
        if not args.force:
            kind = "link" if is_link(target) else "folder"
            print(f"{target} already exists ({kind}). Use --force to replace it.")
            return 0
        if is_link(target):
            target.unlink() if target.is_symlink() else os.rmdir(target)
        else:
            shutil.rmtree(target)

    if args.copy:
        shutil.copytree(source, target)
        print(f"Copied {count} file(s)\n  from {source}\n  to   {target}")
        return 0

    if make_junction(source, target):
        print(f"Linked {target}\n    -> {source}  ({count} files)")
        return 0

    print("Junction failed; falling back to a copy.")
    shutil.copytree(source, target)
    print(f"Copied {count} file(s)\n  from {source}\n  to   {target}")
    return 0


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
