"""README.md's stated facts vs. the repository (implementation brief, Slice C).

Runs `scripts/check_docs_facts.py` against synthetic README text so a test
can assert on a specific kind of drift without waiting for the real README
to actually go stale.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_docs_facts as facts  # noqa: E402


def test_the_real_readme_has_no_drift():
    readme_text = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert facts.check(readme_text) == []


def test_a_stale_migration_count_is_caught():
    real = facts.migration_count()
    text = f"| Schema | {real + 1} numbered migrations |\nexpectation version {facts.golden_expectation_version()}\n"
    failures = facts.check(text)
    assert any("numbered migrations" in f for f in failures)


def test_a_stale_golden_version_is_caught():
    real = facts.golden_expectation_version()
    text = f"| Schema | {facts.migration_count()} numbered migrations |\nexpectation version {real + 1}\n"
    failures = facts.check(text)
    assert any("expectation version" in f for f in failures)


def test_a_missing_fact_statement_is_caught():
    """A number in the wrong format is drift too, not silently "nothing to check"."""
    failures = facts.check("This README no longer mentions either fact at all.")
    assert any("migration count" in f for f in failures)
    assert any("expectation version" in f for f in failures)


def test_a_renamed_or_removed_cli_verb_is_caught():
    text = (
        f"| Schema | {facts.migration_count()} numbered migrations |\n"
        f"expectation version {facts.golden_expectation_version()}\n"
        "```bash\n.venv/bin/mitosis --db colony.db this-verb-does-not-exist\n```\n"
    )
    failures = facts.check(text)
    assert any("this-verb-does-not-exist" in f for f in failures)


def test_referenced_cli_verbs_handles_the_db_flag_and_inline_code():
    text = (
        ".venv/bin/mitosis --db colony.db init\n"
        ".venv/bin/mitosis verify-golden-run\n"
        "Running `mitosis tick` from cron is idempotent.\n"
    )
    assert facts.referenced_cli_verbs(text) == {"init", "verify-golden-run", "tick"}


def test_cli_verbs_finds_real_verbs_structurally():
    verbs = facts.cli_verbs()
    assert {"init", "status", "tick", "health", "verify-golden-run"} <= verbs
