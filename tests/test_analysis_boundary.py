"""The analysis scripts must stay outside the kernel (SPEC.md §23.5).

`scripts/diversity.py` and `scripts/concreteness.py` score how *varied* and how
*concrete* a Cell's proposals are. Both say in their own docstrings that nothing
in the kernel may import them, and until this file that was prose:

    A Cell that learns it is scored on novelty learns to perform novelty.

§23.5 states the general form -- "any approval queue will be optimised against"
-- and a score computed inside `deliberate()` is worse than an approval queue,
because it would sit in the same transaction as the proposal it grades. The
scores are also a model call per proposal, so the cost argument and the safety
argument point the same way.

The forbidden set is **derived from the scripts directory**, not listed here, so
a measurement added tomorrow is covered without anyone remembering to add it.

What this cannot see: a dynamic `importlib.import_module("diversity")` built
from a string. That is a deliberate limit rather than an oversight -- the guard
is structural, and a structural guard that started pattern-matching string
literals would be a behavioural approximation wearing an AST's clothes.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KERNEL = REPO / "src" / "mitosis"
SCRIPTS = REPO / "scripts"


def _analysis_module_names() -> set[str]:
    return {path.stem for path in SCRIPTS.glob("*.py")}


def _imported_names(tree: ast.AST) -> set[str]:
    """Every module named by any import anywhere in the file, function-local ones included."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_the_analysis_scripts_exist_to_be_guarded() -> None:
    """If this fails the guard below is vacuous -- it would forbid an empty set.

    The recurring failure in this repo is a test that passes because it is
    checking nothing, so the set being non-empty is asserted rather than assumed.
    """
    names = _analysis_module_names()
    assert names, f"no analysis scripts found under {SCRIPTS}"
    assert {"diversity", "concreteness"} <= names, names


def test_no_kernel_module_imports_an_analysis_script() -> None:
    """§23.5: a Cell scored on novelty from inside its own loop learns to perform it.

    If this fails, some kernel module can compute a diversity or concreteness
    score during deliberation, and the Cell's own output is being graded by
    something the Cell's prompt can be tuned against.
    """
    forbidden = _analysis_module_names()
    offenders = []
    for path in sorted(KERNEL.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for name in sorted(_imported_names(tree) & forbidden):
            offenders.append(f"{path.relative_to(REPO)} imports {name!r}")
    assert not offenders, "the kernel reaches into the analysis scripts:\n  " + "\n  ".join(offenders)


#: Scripts allowed to import `mitosis`. **An allowlist, not a blocklist**, so a
#: measurement added tomorrow is a scorer by default and joining this list is a
#: deliberate edit. `measure_parse_compliance` is here because it *drives* the
#: loop in-process to produce an arm; it is a harness, not a scorer.
KERNEL_DRIVING_SCRIPTS = {"measure_parse_compliance"}


def test_a_scorer_does_not_import_the_kernel() -> None:
    """A score must be readable from a database, not from this checkout's code.

    Scorers read the colony databases directly with `sqlite3`. Importing
    `mitosis` would pin a measurement to the schema version of the checkout it
    runs from, and the arms worth comparing are routinely written by different
    ones -- ADR-056's arms cannot be rescored by an instrument that only loads
    against today's migrations.
    """
    offenders = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.stem in KERNEL_DRIVING_SCRIPTS:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        if "mitosis" in _imported_names(tree):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, f"scorers importing the kernel: {offenders}"
