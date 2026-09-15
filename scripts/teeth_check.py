#!/usr/bin/env python
"""Teeth-check a batch of guards: reintroduce each bug in a throwaway copy of
the repository, run the named test, and require it to fail *for the stated
reason*.

    .venv/bin/python scripts/teeth_check.py mutations.json [--workers N] [--json out.json]

`mutations.json`:

    {"mutations": [
        {"label": "hook never raises",
         "file": "src/mitosis/network_seal.py",
         "old": "    if _depth and event in SEALED_EVENTS:",
         "new": "    if False:",
         "test": "tests/test_network_seal.py::test_an_epoch_hook_cannot_open_a_connection_from_inside_a_run",
         "expect": "_connections_received(listener) == 0"}
    ]}

Why this exists (ADR-091). CLAUDE.md asks every new guard to be teeth-checked,
and names three ways the practice has gone wrong here, each found the hard way:

1. **Restoring with `git checkout`** reverts to HEAD, not to the pre-mutation
   state, and has deleted an uncommitted fix mid-slice.
2. **Stale bytecode**: a size-preserving edit restored inside one second leaves
   a `.pyc` compiled from the *broken* source looking valid, producing both a
   false result and a restored-but-failing tree.
3. **Reading the exit code instead of the assertion**: a mutation that changes
   only a reason string, or an incomplete mutation that crashes with `KeyError`
   instead of reintroducing the bug, both report a false CAUGHT.

This script makes the first two impossible and the third visible. Every
mutation runs in its **own copy** of the working tree (uncommitted work
included; `.git`, `.venv` and caches excluded), with `PYTHONDONTWRITEBYTECODE=1`
and `PYTHONPATH` pointing at the copy — so the real tree is never edited, nothing
is ever restored, and mutations can run in parallel. The verdict is **CAUGHT**
only when the test failed *and* the `expect` text appears in its output;
a failure without it is **WRONG-FAILURE**, printed with its assertion lines,
because that is the shape of an incomplete mutation or a test failing for the
wrong reason. A passing test is **MISS**; an `old` string that does not occur
exactly once is **INVALID**. Checked at the end: the real tree's files are
byte-identical to before the run.

Session-time sanity on this repo (2026-09-14): 20 teeth-checks across seven
slices, two first misread as MISS by a wrong expected string and two
incomplete mutations that crashed instead — all four surfaced by exactly the
distinction between CAUGHT and WRONG-FAILURE this script draws.

Imports nothing from `mitosis`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Never copied: history, environments, caches, and colony databases — none of
#: them is source a test reads, and `.git`/`.venv` dwarf everything else.
_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "venv", "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache",
    ".hypothesis", "node_modules", "*.db", "*.db-wal", "*.db-shm", "dist", "build",
)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for directory in ("src", "tests", "scripts"):
        base = root / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def _interpreter(root: Path, override: str | None) -> str:
    if override:
        return override
    venv = root / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def run_one(mutation: dict, *, root: Path, python: str, timeout: float) -> dict:
    result = {"label": mutation["label"], "test": mutation["test"]}
    source = root / mutation["file"]
    if not source.exists():
        return {**result, "verdict": "INVALID", "detail": f"no file {mutation['file']}"}
    occurrences = source.read_text().count(mutation["old"])
    if occurrences != 1:
        return {**result, "verdict": "INVALID",
                "detail": f"`old` occurs {occurrences} times in {mutation['file']}, not once"}

    workdir = Path(tempfile.mkdtemp(prefix="teeth-"))
    try:
        copy = workdir / "repo"
        shutil.copytree(root, copy, ignore=_IGNORE, symlinks=True)
        target = copy / mutation["file"]
        target.write_text(target.read_text().replace(mutation["old"], mutation["new"]))
        env = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join([str(copy / "src"), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep),
        }
        try:
            completed = subprocess.run(
                [python, "-m", "pytest", mutation["test"], "-q", "-p", "no:cacheprovider"],
                cwd=copy, env=env, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {**result, "verdict": "WRONG-FAILURE", "detail": f"timed out after {timeout}s"}
        output = completed.stdout + completed.stderr
        assertion_lines = [
            line for line in output.splitlines() if line.startswith("E ") or line.startswith(">")
        ][:6]
        if completed.returncode == 0:
            verdict = "MISS"
        elif mutation["expect"] in output:
            verdict = "CAUGHT"
        else:
            verdict = "WRONG-FAILURE"
        return {**result, "verdict": verdict, "detail": " | ".join(assertion_lines)[:600],
                "returncode": completed.returncode}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run(mutations: list[dict], *, root: Path = REPO, workers: int | None = None,
        python: str | None = None, timeout: float = 600.0) -> list[dict]:
    for mutation in mutations:
        missing = {"label", "file", "old", "new", "test", "expect"} - set(mutation)
        if missing:
            raise ValueError(f"mutation {mutation.get('label', '?')!r} is missing {sorted(missing)}")
    interpreter = _interpreter(root, python)
    before = _tree_digest(root)
    with ThreadPoolExecutor(max_workers=workers or min(len(mutations), os.cpu_count() or 1) or 1) as pool:
        results = list(pool.map(
            lambda m: run_one(m, root=root, python=interpreter, timeout=timeout), mutations
        ))
    if _tree_digest(root) != before:
        raise RuntimeError("the real tree changed during a teeth check — this must never happen")
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="JSON file with a 'mutations' list")
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--python", default=None, help="interpreter for pytest (default: the root's .venv)")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--json", help="write every result here")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    results = run(spec["mutations"], root=Path(args.root), workers=args.workers,
                  python=args.python, timeout=args.timeout)
    for r in results:
        print(f"{r['verdict']:13s} {r['label']}")
        if r["verdict"] != "CAUGHT" and r.get("detail"):
            print(f"              {r['detail']}")
    counts = {v: sum(1 for r in results if r["verdict"] == v)
              for v in ("CAUGHT", "WRONG-FAILURE", "MISS", "INVALID")}
    print("\n" + ", ".join(f"{n} {v}" for v, n in counts.items()))
    if counts["WRONG-FAILURE"]:
        print("WRONG-FAILURE is not CAUGHT: read the assertion lines. Usually the mutation is "
              "incomplete (it crashed instead of reintroducing the bug) or `expect` is wrong.")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
    return 0 if counts["CAUGHT"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
