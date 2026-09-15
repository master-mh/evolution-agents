#!/usr/bin/env python
"""Which open PRIORITIES entries name a *Disproved by:* pointer that now resolves?

    .venv/bin/python scripts/check_disproved_by.py [--json out.json]
    .venv/bin/python scripts/check_disproved_by.py --selftest

Why this exists (ADR-092). PRIORITIES.md's convention, added 2026-08-22 after
three wrong blocker claims in one audit: "an entry that asserts a blocker must
name what would disprove it" — a symbol, table or command, so settling it is
"one grep instead of a full pass". But nothing ever ran the grep. An entry is
written when a gap is noticed, and no later slice re-reads it when it happens to
fill the gap; this repo's claim drift has been found by hand every time.

This runs every grep. For each **unchecked** entry it extracts the backticked
tokens from the pointer and resolves each one against the repository:

- `mitosis <verb>` / `mitosis --help` — a verb the CLI parser defines (AST).
- `something.py` — a file of that name under `src/`, `scripts/` or `tests/`.
- `module.name` — `name` defined at top level (or as a method) in
  `src/mitosis/**/module.py`, found by AST.
- a bare identifier — a table some migration creates, or else a name that
  appears in kernel source.

**Resolving is not enough, and the first version proved it.** It flagged all 9
open entries, because most pointers name a symbol that already existed when the
entry was written — the entry was *narrowed* or *split* around it, on purpose.
Drift is the other case: the symbol appeared **after** the pointer was last
written, so nobody who wrote the entry could have seen it. So each resolving
token is dated with git — the first commit whose diff introduces it (`git log
-S`) against the commit that last touched the pointer's line (`git blame`) —
and only a token newer than its pointer marks the entry `RE-READ`. The rest
print as `resolves (predates pointer)`.

**It reports; it never decides.** A pointer that resolves is a worklist item —
"re-read this entry, its blocker may already be disproved" — not a verdict:
several pointers name a *behaviour* of a symbol ("`death._budget_exhausted`
reading `promotions`"), and a symbol existing is not the behaviour existing.
That judgment is a reader's; the value here is that the reader gets a list
instead of 991 lines. Exit code is always 0 unless `--fail-on-resolved`.

Imports nothing from `mitosis`.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs_facts  # noqa: E402

_ITEM_RE = re.compile(r"^- \[( |x)\] ", re.M)
_POINTER_RE = re.compile(r"\*Disproved by:\*(.*?)(?=\n\s*\n|\n- \[|\n## |\Z)", re.S)
_TOKEN_RE = re.compile(r"`([^`]+)`")
_CREATE_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)", re.I)


def entries(text: str) -> list[dict]:
    """Every checklist entry after the first `## ` heading (the convention
    note above it quotes the pointer syntax and is not an entry)."""
    start = text.find("\n## ")
    body = text[start:] if start >= 0 else text
    matches = list(_ITEM_RE.finditer(body))
    found = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[match.start():end]
        pointer = _POINTER_RE.search(chunk)
        title = re.search(r"\*\*(.+?)\*\*", chunk)
        pointer_offset = pointer.start() if pointer else 0
        found.append({
            "line": text[:start if start >= 0 else 0].count("\n")
            + body[:match.start() + pointer_offset].count("\n") + 1,
            "checked": match.group(1) == "x",
            "title": (title.group(1) if title else chunk[6:90]).strip(),
            "pointer": " ".join(pointer.group(1).split()) if pointer else None,
        })
    return found


class Repository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._defs: dict[str, set[str]] | None = None
        self._tables: set[str] | None = None
        self._source: str | None = None

    def definitions(self) -> dict[str, set[str]]:
        """module stem -> names defined in it (top-level and methods)."""
        if self._defs is None:
            self._defs = {}
            for path in (self.root / "src" / "mitosis").rglob("*.py"):
                names: set[str] = set()
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        names.add(node.name)
                    elif isinstance(node, ast.Assign):
                        names.update(t.id for t in node.targets if isinstance(t, ast.Name))
                    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                        names.add(node.target.id)
                self._defs.setdefault(path.stem, set()).update(names)
        return self._defs

    def tables(self) -> set[str]:
        if self._tables is None:
            self._tables = set()
            for path in (self.root / "src" / "mitosis" / "migrations").glob("*.sql"):
                self._tables.update(m.lower() for m in _CREATE_TABLE_RE.findall(path.read_text()))
        return self._tables

    def kernel_source(self) -> str:
        if self._source is None:
            self._source = "\n".join(
                p.read_text() for p in (self.root / "src" / "mitosis").rglob("*.py")
            )
        return self._source

    def resolve(self, token: str) -> tuple[bool, str]:
        token = token.strip()
        if token.startswith("mitosis "):
            verb = token.split()[1]
            if verb in ("--help", "-h"):
                return True, "the CLI's own help"
            ok = verb in check_docs_facts.cli_verbs(self.root)
            return ok, f"CLI verb {verb!r} {'defined' if ok else 'not defined'}"
        if token.endswith(".py"):
            hits = [p for d in ("src", "scripts", "tests") for p in (self.root / d).rglob(token)]
            return bool(hits), (f"file {hits[0].relative_to(self.root)}" if hits else f"no file {token}")
        dotted = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", token)
        if dotted:
            module, name = dotted.groups()
            defs = self.definitions()
            if module not in defs:
                return False, f"no module {module}.py"
            ok = name in defs[module]
            return ok, f"{module}.{name} {'defined' if ok else 'not defined'}"
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            if token.lower() in self.tables():
                return True, f"table {token}"
            ok = re.search(rf"\b{re.escape(token)}\b", self.kernel_source()) is not None
            return ok, f"name {token!r} {'appears' if ok else 'does not appear'} in kernel source"
        return False, "not a symbol, file, table or command this script can resolve"


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def pointer_written_at(root: Path, line: int) -> datetime | None:
    """When the commit that last touched PRIORITIES.md's `line` was made;
    `None` for an uncommitted line."""
    out = _git(root, "blame", "-L", f"{line},{line}", "--porcelain", "PRIORITIES.md")
    match = re.search(r"^committer-time (\d+)$", out, re.M)
    if not match or out.startswith("0" * 40):
        return None
    return datetime.fromtimestamp(int(match.group(1)))


def token_introduced_at(root: Path, token: str) -> datetime | None:
    """When the thing a pointer names came into existence: the commit adding
    a named file, or the first commit whose diff introduces the name itself.

    A dotted token is searched by its last component — `death._budget_exhausted`
    never appears as that literal string in source, `_budget_exhausted` does —
    and a CLI invocation is not dated at all (a verb's name is too common a
    word to date by diff)."""
    token = token.strip()
    if token.startswith("mitosis "):
        return None
    if token.endswith(".py"):
        hits = [p for d in ("src", "scripts", "tests") for p in (root / d).rglob(token)]
        if not hits:
            return None
        out = _git(root, "log", "--diff-filter=A", "--reverse", "--format=%ct", "--",
                   str(hits[0].relative_to(root)))
    else:
        needle = token.rsplit(".", 1)[-1]
        out = _git(root, "log", "-S", needle, "--reverse", "--format=%ct", "--",
                   "src", "scripts", "tests")
    first = out.split()
    return datetime.fromtimestamp(int(first[0])) if first else None


def report(root: Path = REPO) -> list[dict]:
    repo = Repository(root)
    rows = []
    for entry in entries((root / "PRIORITIES.md").read_text()):
        if entry["checked"] or not entry["pointer"]:
            continue
        tokens = _TOKEN_RE.findall(entry["pointer"])
        resolutions = [
            {"token": token, "resolves": ok, "detail": detail}
            for token in tokens
            for ok, detail in [repo.resolve(token)]
        ]
        written = pointer_written_at(root, entry["line"])
        for resolution in resolutions:
            resolution["newer_than_pointer"] = False
            if resolution["resolves"] and written is not None:
                introduced = token_introduced_at(root, resolution["token"])
                resolution["introduced"] = introduced.isoformat() if introduced else None
                resolution["newer_than_pointer"] = bool(introduced and introduced > written)
        rows.append({**entry, "tokens": resolutions,
                     "pointer_written": written.isoformat() if written else None,
                     "any_resolves": any(r["resolves"] for r in resolutions),
                     "re_read": any(r["newer_than_pointer"] for r in resolutions)})
    return rows


def selftest() -> int:
    repo = Repository(REPO)
    cases = [
        ("proposal.parse", True), ("proposal.no_such_function", False),
        ("no_such_module.parse", False), ("sandbox.py", False), ("check_docs_facts.py", True),
        ("model_calls", True), ("mitosis --help", True), ("mitosis simulate-batch", True),
        ("mitosis no-such-verb", False),
    ]
    failures = 0
    for token, expected in cases:
        ok, detail = repo.resolve(token)
        good = ok == expected
        failures += not good
        print(f"  [{'ok' if good else 'FAIL'}] {token!r}: {ok} ({detail})")
    sample = "## Now\n- [ ] **Open thing.** *Disproved by:* `proposal.parse`.\n\n- [x] **Done.** *Disproved by:* `x.y`.\n"
    parsed = entries(sample)
    shape_ok = [e["checked"] for e in parsed] == [False, True] and parsed[0]["pointer"] == "`proposal.parse`."
    failures += not shape_ok
    print(f"  [{'ok' if shape_ok else 'FAIL'}] entry parsing")
    print("selftest:", "PASS" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="write the full report here")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fail-on-resolved", action="store_true",
                    help="exit 1 when any open entry's pointer resolves")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    rows = report()
    flagged = [r for r in rows if r["re_read"]]
    print(f"{len(rows)} open entr{'y' if len(rows) == 1 else 'ies'} carry a *Disproved by:* pointer; "
          f"{sum(r['any_resolves'] for r in rows)} name something that exists; "
          f"{len(flagged)} name something that appeared after the pointer was written.\n")
    for row in rows:
        mark = "RE-READ" if row["re_read"] else "open   "
        print(f"[{mark}] PRIORITIES.md:{row['line']}  {row['title'][:90]}")
        print(f"          pointer ({(row['pointer_written'] or 'uncommitted')[:10]}): {row['pointer'][:150]}")
        for token in row["tokens"]:
            age = ""
            if token["resolves"] and token.get("introduced"):
                age = (" — NEWER than the pointer" if token["newer_than_pointer"]
                       else " — predates pointer")
            print(f"          {'+' if token['resolves'] else '-'} {token['detail']}{age}")
        if not row["tokens"]:
            print("          (no backticked token — settle by hand)")
    if flagged:
        print("\nRE-READ means a pointer names something newer than the pointer itself, not that "
              "the blocker is disproved: several pointers name a behaviour of a symbol, which only "
              "a reader can confirm.")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
    return 1 if (args.fail_on_resolved and flagged) else 0


if __name__ == "__main__":
    raise SystemExit(main())
