"""The teeth-check runner itself (ADR-091).

Run against a tiny throwaway project rather than this repository, so each
verdict is decided by a mutation whose outcome is known in advance — and so
the test is fast. The property that matters most is the last one: the real
tree is never touched, which is the failure (`git checkout` restoring over
uncommitted work, stale bytecode after a restore) the runner exists to remove.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "teeth_check.py"


@pytest.fixture(scope="module")
def teeth():
    spec = importlib.util.spec_from_file_location("teeth_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "src" / "arith").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "arith" / "__init__.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef table():\n    return {'one': 1}\n"
    )
    (root / "tests" / "test_arith.py").write_text(
        "from arith import add, table\n\n\n"
        "def test_add_sums():\n    assert add(2, 3) == 5\n\n\n"
        "def test_table_has_one():\n    assert table()['one'] == 1\n"
    )
    return root


def _mutation(**overrides):
    base = {
        "label": "subtracts", "file": "src/arith/__init__.py",
        "old": "    return a + b\n", "new": "    return a - b\n",
        "test": "tests/test_arith.py::test_add_sums", "expect": "assert -1 == 5",
    }
    return {**base, **overrides}


def test_verdicts_separate_caught_from_miss_wrong_failure_and_invalid(teeth, project):
    results = teeth.run(
        [
            _mutation(),
            _mutation(label="commutes", new="    return b + a\n", expect="assert"),
            # Crashes with a KeyError instead of reintroducing a wrong value:
            # the incomplete-mutation shape that a bare exit code reads as CAUGHT.
            _mutation(label="incomplete", file="src/arith/__init__.py",
                      old="    return {'one': 1}\n", new="    return {}\n",
                      test="tests/test_arith.py::test_table_has_one", expect="assert 0 == 1"),
            _mutation(label="not there", old="    return a * b\n"),
        ],
        root=project, python=sys.executable, workers=4,
    )
    verdicts = {r["label"]: r["verdict"] for r in results}
    assert verdicts == {
        "subtracts": "CAUGHT",
        "commutes": "MISS",
        "incomplete": "WRONG-FAILURE",
        "not there": "INVALID",
    }
    incomplete = next(r for r in results if r["label"] == "incomplete")
    assert "KeyError" in incomplete["detail"]


def test_the_real_tree_is_never_touched(teeth, project):
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    teeth.run([_mutation(), _mutation(label="again")], root=project, python=sys.executable, workers=2)
    after = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert after == before
    assert not list(project.rglob("__pycache__"))


def test_a_mutation_missing_a_field_is_refused_before_anything_runs(teeth, project):
    broken = _mutation()
    del broken["expect"]
    with pytest.raises(ValueError, match="expect"):
        teeth.run([broken], root=project, python=sys.executable)
