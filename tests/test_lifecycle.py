from datetime import datetime, timedelta, timezone

import pytest

from mitosis import ledger, lifecycle, population, reservations
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellStatus, CellType, PopulationLimits


def test_create_cell_funds_cash_and_is_alive(conn):
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=500,
        book=Book.USD_SIM,
        idempotency_key="create:1",
    )
    assert cell.status == CellStatus.ALIVE
    assert cell.cell_type == CellType.EXPLORER
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_SIM) == 500
    assert ledger.get_balance(conn, "seed_bank", Book.USD_SIM) == -500


def test_create_cell_is_idempotent(conn):
    first = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=500,
        book=Book.USD_SIM, idempotency_key="create:1",
    )
    second = lifecycle.create_cell(
        conn, cell_type=CellType.BUILDER, budget_minor_units=999,
        book=Book.USD_SIM, idempotency_key="create:1",
    )
    assert first.cell_id == second.cell_id
    assert second.cell_type == CellType.EXPLORER  # replay ignored the differing args
    assert ledger.get_balance(conn, "seed_bank", Book.USD_SIM) == -500


def test_create_cell_rejects_non_positive_budget(conn):
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.create_cell(
            conn, cell_type=CellType.EXPLORER, budget_minor_units=0,
            book=Book.USD_SIM, idempotency_key="create:zero",
        )


def test_identical_cell_type_genomes_are_deduped(conn):
    a = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key="create:a",
    )
    b = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=200,
        book=Book.USD_SIM, idempotency_key="create:b",
    )
    assert a.genome_hash == b.genome_hash
    row_count = conn.execute(
        "SELECT COUNT(*) AS n FROM cell_genomes WHERE genome_hash = ?", (a.genome_hash,)
    ).fetchone()["n"]
    assert row_count == 1


def test_create_cell_emits_audit_event(conn):
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.AUDITOR, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key="create:1",
    )
    row = conn.execute(
        "SELECT * FROM audit_events WHERE cell_id = ?", (cell.cell_id,)
    ).fetchone()
    assert row is not None
    assert row["event_type"] == "cell_lifecycle_transition"


def test_count_by_status_and_type(conn):
    lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key="c1",
    )
    lifecycle.create_cell(
        conn, cell_type=CellType.BUILDER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key="c2",
    )
    assert lifecycle.count_by_status(conn) == {"alive": 2}
    assert lifecycle.count_by_type(conn) == {"explorer": 1, "builder": 1}


def test_create_cell_denied_at_carrying_capacity(conn):
    population.set_limits_if_absent(
        conn,
        PopulationLimits(
            max_living_cells=1, max_active_cells=99, max_parallel_experiments=1,
            max_births_per_epoch=1, max_lineage_population_fraction=1.0,
        ),
    )
    lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key="c1",
    )
    with pytest.raises(population.CarryingCapacityError):
        lifecycle.create_cell(
            conn, cell_type=CellType.BUILDER, budget_minor_units=100,
            book=Book.USD_SIM, idempotency_key="c2",
        )
    # the denied birth must not have partially applied anything
    assert lifecycle.count_by_status(conn) == {"alive": 1}
    assert ledger.get_balance(conn, "seed_bank", Book.USD_SIM) == -100
    assert ledger.verify_conservation(conn, Book.USD_SIM) is True


def test_denied_birth_does_not_consume_idempotency_key(conn):
    population.set_limits_if_absent(
        conn,
        PopulationLimits(
            max_living_cells=0, max_active_cells=99, max_parallel_experiments=1,
            max_births_per_epoch=1, max_lineage_population_fraction=1.0,
        ),
    )
    with pytest.raises(population.CarryingCapacityError):
        lifecycle.create_cell(
            conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
            book=Book.USD_SIM, idempotency_key="c1",
        )
    assert lifecycle.get_cell_by_idempotency_key(conn, "c1") is None


def test_conservation_holds_after_births(conn):
    for i in range(5):
        lifecycle.create_cell(
            conn, cell_type=CellType.EXPLORER, budget_minor_units=100 + i,
            book=Book.USD_SIM, idempotency_key=f"c{i}",
        )
    assert ledger.verify_conservation(conn, Book.USD_SIM) is True
    assert ledger.verify_chain(conn) is True


def _born(conn, idempotency_key="c1", budget=100):
    return lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=budget,
        book=Book.USD_SIM, idempotency_key=idempotency_key,
    )


# --- sleep / wake (docs/STATE_MACHINES.md §1.2) -----------------------------


def test_sleep_then_wake_round_trip(conn):
    cell = _born(conn)
    dormant = lifecycle.sleep(conn, cell.cell_id)
    assert dormant.status == CellStatus.DORMANT
    alive = lifecycle.wake(conn, cell.cell_id)
    assert alive.status == CellStatus.ALIVE


def test_sleep_rejected_from_dormant(conn):
    cell = _born(conn)
    lifecycle.sleep(conn, cell.cell_id)
    with pytest.raises(lifecycle.InvalidTransitionError):
        lifecycle.sleep(conn, cell.cell_id)


def test_wake_rejected_from_alive(conn):
    cell = _born(conn)
    with pytest.raises(lifecycle.InvalidTransitionError):
        lifecycle.wake(conn, cell.cell_id)


def test_wake_rejected_from_quarantined(conn):
    """Quarantined -> alive is a valid FSM edge, but only via
    clear_quarantine's explicit review — wake() must not be a backdoor."""
    cell = _born(conn)
    lifecycle.quarantine(conn, cell.cell_id, reason="policy violation")
    with pytest.raises(lifecycle.InvalidTransitionError):
        lifecycle.wake(conn, cell.cell_id)


def test_sleep_rejected_from_quarantined(conn):
    cell = _born(conn)
    lifecycle.quarantine(conn, cell.cell_id, reason="policy violation")
    with pytest.raises(lifecycle.InvalidTransitionError):
        lifecycle.sleep(conn, cell.cell_id)


# --- quarantine / clear_quarantine (§1.2, §1.4, §18.2) ----------------------


def test_quarantine_from_alive_and_dormant(conn):
    alive_cell = _born(conn, idempotency_key="c-alive")
    q1 = lifecycle.quarantine(conn, alive_cell.cell_id, reason="policy violation")
    assert q1.status == CellStatus.QUARANTINED

    dormant_cell = _born(conn, idempotency_key="c-dormant")
    lifecycle.sleep(conn, dormant_cell.cell_id)
    q2 = lifecycle.quarantine(conn, dormant_cell.cell_id, reason="taint detected")
    assert q2.status == CellStatus.QUARANTINED


def test_quarantine_links_finding_in_audit_event(conn):
    cell = _born(conn)
    lifecycle.quarantine(
        conn, cell.cell_id, reason="poison event dead-lettered",
        linked_finding={"event_id": "evt-1", "event_type": "poison"},
    )
    row = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE cell_id = ? AND description LIKE '%quarantined%'",
        (cell.cell_id,),
    ).fetchone()
    assert '"event_id":"evt-1"' in row["metadata_json"]


def test_clear_quarantine_to_alive_or_dormant(conn):
    cell = _born(conn, idempotency_key="c-alive")
    lifecycle.quarantine(conn, cell.cell_id, reason="policy violation")
    cleared = lifecycle.clear_quarantine(conn, cell.cell_id, to_status=CellStatus.ALIVE)
    assert cleared.status == CellStatus.ALIVE

    cell2 = _born(conn, idempotency_key="c-dormant")
    lifecycle.quarantine(conn, cell2.cell_id, reason="policy violation")
    cleared2 = lifecycle.clear_quarantine(conn, cell2.cell_id, to_status=CellStatus.DORMANT)
    assert cleared2.status == CellStatus.DORMANT


def test_clear_quarantine_rejects_non_quarantined_source(conn):
    cell = _born(conn)
    with pytest.raises(lifecycle.InvalidTransitionError):
        lifecycle.clear_quarantine(conn, cell.cell_id, to_status=CellStatus.ALIVE)


def test_clear_quarantine_rejects_invalid_target(conn):
    cell = _born(conn)
    lifecycle.quarantine(conn, cell.cell_id, reason="policy violation")
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.clear_quarantine(conn, cell.cell_id, to_status=CellStatus.DEAD)


# --- kill / coroner reports (§10.5, Amendment A15) --------------------------


def test_kill_from_alive_dormant_and_quarantined(conn):
    for idempotency_key, prep in (
        ("c-alive", lambda c: None),
        ("c-dormant", lambda c: lifecycle.sleep(conn, c.cell_id)),
        ("c-quarantined", lambda c: lifecycle.quarantine(conn, c.cell_id, reason="x")),
    ):
        cell = _born(conn, idempotency_key=idempotency_key)
        prep(cell)
        dead = lifecycle.kill(conn, cell.cell_id, cause_of_death="stage budget exhausted")
        assert dead.status == CellStatus.DEAD


def test_kill_is_terminal(conn):
    cell = _born(conn)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="stage budget exhausted")
    with pytest.raises(lifecycle.InvalidTransitionError):
        lifecycle.wake(conn, cell.cell_id)
    with pytest.raises(lifecycle.InvalidTransitionError):
        lifecycle.kill(conn, cell.cell_id, cause_of_death="double kill")


def test_kill_files_coroner_report_with_genome_and_spend(conn):
    cell = _born(conn, budget=1000)
    r = reservations.request(
        conn, cell_id=cell.cell_id, book=Book.USD_SIM, currency="USD", maximum_amount=300,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), idempotency_key="r1",
    )
    reservations.settle(conn, r.reservation_id, settled_amount=300, destination_account_id="external_expense")

    lifecycle.kill(
        conn, cell.cell_id, cause_of_death="stage budget exhausted",
        final_hypotheses=["h1", "h2"], experiment_ids=["exp-1"],
    )
    report = lifecycle.get_coroner_report(conn, cell.cell_id)
    assert report.genome_hash == cell.genome_hash
    assert report.spend_by_book == {"USD_SIM": 300}
    assert report.cause_of_death == "stage budget exhausted"
    assert report.final_hypotheses == ("h1", "h2")
    assert report.experiment_ids == ("exp-1",)
    assert lifecycle.count_coroner_reports(conn) == 1


def test_kill_no_report_for_unknown_cell(conn):
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.kill(conn, "no-such-cell", cause_of_death="x")
    assert lifecycle.count_coroner_reports(conn) == 0


def test_kill_emits_audit_event(conn):
    cell = _born(conn)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="policy violation")
    row = conn.execute(
        "SELECT * FROM audit_events WHERE cell_id = ? AND description LIKE '%-> dead%'",
        (cell.cell_id,),
    ).fetchone()
    assert row is not None
