import pytest

from mitosis import ledger, lifecycle, population
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
