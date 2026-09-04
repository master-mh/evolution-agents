#!/usr/bin/env python
"""Build a clean source archive from git-tracked files only.

    .venv/bin/python scripts/build_source_archive.py [--ref HEAD] [--output dist/mitosis-source.zip]

Uses `git archive`, so only content committed at the given ref is included --
`.env`, the working database, `.venv`, caches and macOS metadata are absent
because they were never tracked, not because this script guesses a pattern to
strip out of a directory walk. (A manually zipped working directory has
shipped a live credential before precisely because zipping a directory
bypasses `.gitignore`; `git archive` cannot make that mistake.)

That is still only the first guard. Before the archive is left on disk, its
member list is checked against FORBIDDEN_PATTERNS below -- an independent
check of the actual output, so that a future `git add -f` of something that
should never have been tracked fails this build instead of shipping.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Directory-component names that must never appear in an archive member's path.
FORBIDDEN_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "virtualenv",
        "__pycache__",
        ".pytest_cache",
        ".hypothesis",
        "__MACOSX",
    }
)


def _forbidden_reason(member: str) -> str | None:
    """Return the forbidden pattern `member` matches, or None if it's clean."""
    parts = member.split("/")
    basename = parts[-1] or (parts[-2] if len(parts) > 1 else "")
    for part in parts[:-1]:
        if part in FORBIDDEN_DIR_NAMES:
            return f"{part}/"
    if basename == ".env" or basename.startswith(".env."):
        return ".env"
    if basename.endswith((".db", ".sqlite", ".sqlite3")):
        return "*.db/*.sqlite/*.sqlite3"
    if basename == ".DS_Store":
        return ".DS_Store"
    if basename == ".coverage" or basename.startswith(".coverage."):
        return ".coverage"
    return None


def find_forbidden_members(archive_path: Path) -> list[tuple[str, str]]:
    """Return (member, matched pattern) pairs for every disallowed entry."""
    with zipfile.ZipFile(archive_path) as zf:
        names = zf.namelist()
    found = []
    for name in names:
        reason = _forbidden_reason(name)
        if reason is not None:
            found.append((name, reason))
    return found


def build_archive(output: Path, *, ref: str = "HEAD", repo_root: Path = REPO_ROOT) -> Path:
    """Run `git archive` for `ref` inside `repo_root`, writing a zip to `output`."""
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "archive", "--format=zip", f"--output={output}", ref],
        cwd=repo_root,
        check=True,
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default="HEAD", help="git ref to archive (default: HEAD)")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="repository to archive")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output zip path (default: <repo-root>/dist/mitosis-source.zip)",
    )
    args = parser.parse_args(argv)
    output = args.output or (args.repo_root / "dist" / "mitosis-source.zip")

    build_archive(output, ref=args.ref, repo_root=args.repo_root)

    forbidden = find_forbidden_members(output)
    if forbidden:
        output.unlink(missing_ok=True)
        print(f"refusing to ship {output}: forbidden content in archive:", file=sys.stderr)
        for name, reason in forbidden:
            print(f"  {name}  (matched: {reason})", file=sys.stderr)
        return 1

    size_kib = output.stat().st_size / 1024
    print(f"wrote {output} ({size_kib:.0f} KiB, ref={args.ref})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
