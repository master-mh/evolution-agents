"""Golden-run replay tests (SPEC.md §26, §29 criterion 11; ADR-017/A12)."""

import json

import pytest

from mitosis import db, golden, ids, ledger, lifecycle
from mitosis.models import Book, CellStatus


def _fresh_run():
    conn = db.connect_and_migrate()
    golden.run_scenario(conn)
    return conn


# --- the scenario itself ------------------------------------------------------


def test_scenario_conserves_capital_in_every_book():
    conn = _fresh_run()
    try:
        for book in Book:
            assert ledger.verify_conservation(conn, book) is True
        assert ledger.verify_chain(conn) is True
    finally:
        conn.close()


def test_scenario_exercises_every_lifecycle_status():
    """A golden run that never reaches a status can't detect drift in it."""
    conn = _fresh_run()
    try:
        statuses = {row["status"] for row in conn.execute("SELECT status FROM cells")}
        assert statuses == {
            CellStatus.ALIVE.value,
            CellStatus.QUARANTINED.value,
            CellStatus.DEAD.value,
        }
        assert lifecycle.count_coroner_reports(conn) == 1
    finally:
        conn.close()


def test_scenario_exercises_every_reservation_terminal_shape():
    conn = _fresh_run()
    try:
        statuses = {row["status"] for row in conn.execute("SELECT status FROM reservations")}
        assert statuses == {
            "settled", "released", "partially_settled", "execution_unknown", "reserved",
        }
    finally:
        conn.close()


def test_scenario_pins_charter_c6_idempotent_redelivery():
    """Every event is processed twice; the side effect must land once.
    colony_treasury == 300 (3 events x 100), not 600."""
    conn = _fresh_run()
    try:
        assert ledger.get_balance(conn, "colony_treasury", Book.USD_SIM) == 300
    finally:
        conn.close()


def test_scenario_pins_charter_c7_execution_unknown_stays_committed():
    """An unknown external operation is reconciled, never auto-released —
    so its funds are still committed at the end of the run."""
    conn = _fresh_run()
    try:
        row = conn.execute(
            "SELECT cell_id, maximum_amount FROM reservations WHERE status = 'execution_unknown'"
        ).fetchone()
        assert row is not None
        committed = ledger.get_balance(conn, f"cell:{row['cell_id']}:committed", Book.USD_SIM)
        assert committed == row["maximum_amount"]
    finally:
        conn.close()


def test_scenario_dead_letters_poison_event_and_quarantines_its_cell():
    conn = _fresh_run()
    try:
        poison = conn.execute(
            "SELECT * FROM event_inbox WHERE event_type = 'golden_poison'"
        ).fetchone()
        assert poison["status"] == "dead_letter"
        quarantined = conn.execute(
            "SELECT COUNT(*) AS n FROM cells WHERE status = 'quarantined'"
        ).fetchone()["n"]
        assert quarantined == 1
    finally:
        conn.close()


# --- determinism (the property the whole slice rests on) ----------------------


def test_semantic_hash_is_reproducible_across_runs():
    hashes = set()
    for _ in range(3):
        conn = _fresh_run()
        try:
            hashes.add(golden.semantic_hash(golden.semantic_snapshot(conn)))
        finally:
            conn.close()
    assert len(hashes) == 1


def _raw_ids(conn):
    return (
        [r["cell_id"] for r in conn.execute("SELECT cell_id FROM cells ORDER BY rowid")],
        [
            r["transaction_id"]
            for r in conn.execute("SELECT transaction_id FROM ledger_transactions ORDER BY rowid")
        ],
        [r["event_id"] for r in conn.execute("SELECT event_id FROM event_inbox ORDER BY rowid")],
    )


def test_raw_ids_are_reproducible_across_runs():
    """The determinism gap ids.py closes (see golden.py's module docstring):
    not just the semantic snapshot, but the actual uuids the scenario
    generates, are identical run to run given GOLDEN_RUN_ID_SEED."""
    conn1 = _fresh_run()
    try:
        first = _raw_ids(conn1)
    finally:
        conn1.close()

    conn2 = _fresh_run()
    try:
        second = _raw_ids(conn2)
    finally:
        conn2.close()

    assert first == second
    assert all(first)  # sanity: none of the three id lists is empty


def test_run_scenario_does_not_leak_seeded_ids_afterward():
    """`run_scenario` scopes its determinism to its own duration (`ids.seeded`,
    not a bare `ids.seed`) — id generation elsewhere must stay random."""
    conn = _fresh_run()
    conn.close()
    assert ids.new_id() != ids.new_id()


def test_snapshot_contains_no_volatile_identifiers():
    """uuid4 primary keys and wall-clock timestamps must never reach the
    snapshot — they're exactly what makes byte comparison impossible today
    (ADR-017)."""
    conn = _fresh_run()
    try:
        snapshot = golden.semantic_snapshot(conn)
        raw_cell_ids = [r["cell_id"] for r in conn.execute("SELECT cell_id FROM cells")]
    finally:
        conn.close()

    serialized = json.dumps(snapshot)
    for cell_id in raw_cell_ids:
        assert cell_id not in serialized
    # cell accounts survive, but under stable birth-order aliases
    assert any("cell#0" in key for key in snapshot["balances"])


def test_cell_aliases_follow_birth_order():
    conn = _fresh_run()
    try:
        snapshot = golden.semantic_snapshot(conn)
    finally:
        conn.close()
    aliases = [cell["alias"] for cell in snapshot["cells"]]
    assert aliases == ["cell#0", "cell#1", "cell#2", "cell#3"]
    # birth order is the scenario's declared order
    assert [c["cell_type"] for c in snapshot["cells"]] == [
        "commercial", "explorer", "builder", "auditor",
    ]


# --- verification against the shipped expectations ----------------------------


def test_shipped_expectations_match_current_kernel():
    """The CI guard itself: if this fails, kernel economic behaviour changed
    (§26.3). Regenerate deliberately via --update-expectations."""
    result = golden.verify()
    assert result.invariant_failures == []
    assert result.hash_matched, (
        f"golden-run hash drift: expected {result.expected_hash}, got {result.actual_hash}"
    )
    assert result.matched is True


def test_shipped_expectations_are_versioned():
    expectations = golden.load_expectations()
    assert expectations["expectation_version"] == golden.EXPECTATION_VERSION
    assert set(expectations) == {
        "expectation_version", "semantic_hash", "invariants", "snapshot",
    }


def test_build_expectations_round_trips_to_verify():
    built = golden.build_expectations()
    assert built["semantic_hash"] == golden.verify().actual_hash


# --- drift detection ----------------------------------------------------------


def test_invariant_regression_is_caught(monkeypatch):
    """A kill() that stops filing coroner reports must fail loudly."""
    def kill_without_report(conn, cell_id, *, cause_of_death, **_):
        return lifecycle._transition(
            conn, cell_id, CellStatus.DEAD, reason=cause_of_death,
            valid_sources=frozenset(
                {CellStatus.ALIVE, CellStatus.DORMANT, CellStatus.QUARANTINED}
            ),
        )

    monkeypatch.setattr(golden.lifecycle, "kill", kill_without_report)
    result = golden.verify()
    assert result.matched is False
    assert "coroner_reports: expected 1, got 0" in result.invariant_failures


def test_hash_catches_drift_that_invariants_miss(monkeypatch):
    """The reason ADR-017 requires invariants *plus* a hash: overfunding
    every birth keeps conservation intact, so only the hash notices."""
    original_create = golden.lifecycle.create_cell

    def overfunded(conn, *, cell_type, budget_minor_units, book, idempotency_key, **kw):
        return original_create(
            conn, cell_type=cell_type, budget_minor_units=budget_minor_units + 1,
            book=book, idempotency_key=idempotency_key, **kw,
        )

    monkeypatch.setattr(golden.lifecycle, "create_cell", overfunded)
    result = golden.verify()
    assert result.invariant_failures == []  # conservation still holds
    assert result.hash_matched is False
    assert result.matched is False
    assert "balances: differs" in golden.diff_snapshots(
        golden.load_expectations()["snapshot"], result.snapshot
    )


def test_missing_expectations_file_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(golden, "_expectations_path", lambda: tmp_path / "absent.json")
    with pytest.raises(golden.GoldenRunError):
        golden.load_expectations()


def test_diff_snapshots_reports_added_removed_and_changed():
    expected = {"same": 1, "changed": 2, "only_expected": 3}
    actual = {"same": 1, "changed": 99, "only_actual": 4}
    differences = golden.diff_snapshots(expected, actual)
    assert "changed: differs" in differences
    assert "only_expected: present in expectations, absent now" in differences
    assert "only_actual: absent from expectations, present now" in differences
    assert not any(line.startswith("same:") for line in differences)
