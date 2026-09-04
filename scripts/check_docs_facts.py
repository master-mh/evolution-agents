#!/usr/bin/env python
"""Fail if README.md's stated facts have drifted from the repository.

    .venv/bin/python scripts/check_docs_facts.py

Checks:
  - the migration count README states matches migrations/*.sql on disk;
  - the golden expectation version README states matches the shipped
    golden_expectations.json;
  - every `mitosis <verb>` reference in README names a verb the CLI parser
    actually defines today.

Deliberately does not check a test count. README states no specific number
for exactly that reason: the count moves on nearly every commit in this
repo, so pinning one here would make this script the next thing to go
stale instead of the README (implementation brief, Slice C).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"


def migration_count(repo_root: Path = REPO_ROOT) -> int:
    return len(list((repo_root / "src" / "mitosis" / "migrations").glob("*.sql")))


def golden_expectation_version(repo_root: Path = REPO_ROOT) -> int:
    data = json.loads((repo_root / "src" / "mitosis" / "golden_expectations.json").read_text())
    return data["expectation_version"]


def cli_verbs(repo_root: Path = REPO_ROOT) -> set[str]:
    """Every subparser name cli.py's argument parser defines, found
    structurally (AST) so this works without the package installed."""
    tree = ast.parse((repo_root / "src" / "mitosis" / "cli.py").read_text())
    verbs = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_parser"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            verbs.add(node.args[0].value)
    return verbs


#: `mitosis`, an optional `--db <path>`, then the verb -- matches this
#: README's actual invocation shape (`mitosis [--db DB] <verb> ...`) whether
#: inside a fenced code block or inline as `` `mitosis tick` ``.
_MITOSIS_VERB_RE = re.compile(r"\bmitosis\b(?:\s+--db\s+\S+)?\s+([a-z][a-z-]*)")


def referenced_cli_verbs(text: str) -> set[str]:
    return set(_MITOSIS_VERB_RE.findall(text))


def check(readme_text: str, *, repo_root: Path = REPO_ROOT) -> list[str]:
    failures: list[str] = []

    actual_migrations = migration_count(repo_root)
    match = re.search(r"(\d+) numbered migrations", readme_text)
    if match is None:
        failures.append("README no longer states a migration count in the expected format")
    elif int(match.group(1)) != actual_migrations:
        failures.append(
            f"README says {match.group(1)} numbered migrations; "
            f"src/mitosis/migrations/ actually has {actual_migrations}"
        )

    actual_version = golden_expectation_version(repo_root)
    match = re.search(r"expectation version (\d+)", readme_text)
    if match is None:
        failures.append("README no longer states a golden expectation version in the expected format")
    elif int(match.group(1)) != actual_version:
        failures.append(
            f"README says expectation version {match.group(1)}; "
            f"golden_expectations.json actually ships version {actual_version}"
        )

    actual_verbs = cli_verbs(repo_root)
    referenced = referenced_cli_verbs(readme_text)
    stale = sorted(v for v in referenced if v not in actual_verbs)
    if stale:
        failures.append(f"README references CLI verb(s) not in the current parser: {', '.join(stale)}")

    return failures


def main() -> int:
    readme_text = README.read_text()
    failures = check(readme_text)

    if failures:
        print("Documentation facts have drifted from the repository:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        f"README facts check out: {migration_count()} migrations, "
        f"golden expectation version {golden_expectation_version()}, "
        f"{len(referenced_cli_verbs(readme_text))} CLI verb reference(s) all valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
