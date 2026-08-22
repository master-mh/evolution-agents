"""§9.2's `max_births_per_epoch` (SPEC.md §9.1, §9.2, §9.3, §6.3, §10.5).

The limit has been in `colony_config` since Phase 1 and unenforced ever since.
What these tests defend is mostly the *distinction* the cap introduces: a rate
limit and a capacity limit refuse identically and mean opposite things, and only
one of them may ever cause a death.
"""

import ast
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from mitosis import clock, db, displacement, ledger, lifecycle, lineage, population
from mitosis.models import Book, CellStatus, CellType, EntrySpec, PopulationLimits

ROOMY = PopulationLimits(
    max_living_cells=1000,
    max_active_cells=1000,
    max_parallel_experiments=20,
    max_births_per_epoch=3,
    max_lineage_population_fraction=1.0,
)


def _seed(conn, limits=ROOMY, *, anchor_epochs=True):
    population.set_limits_if_absent(conn, limits)
    if anchor_epochs:
        clock.configure_epochs_if_absent(conn)
    for book, currency, amount in (
        (Book.USD_SIM, "USD", 1_000_000),
        (Book.RESOURCE, "RESOURCE", 1_000_000),
    ):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="external_capital_in",
            idempotency_key=f"seed:{book.value}",
            description="test seed",
            entries=[
                EntrySpec(account_id="external_capital", amount_minor_units=-amount),
                EntrySpec(account_id="seed_bank", amount_minor_units=amount),
            ],
        )


def _born(conn, tag, **kwargs):
    return lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=10,
        book=Book.USD_SIM,
        idempotency_key=f"cell:{tag}",
        **kwargs,
    )


# --- the cap binds, on both birth paths --------------------------------------


def test_the_epoch_birth_cap_is_enforced(conn):
    """§9.2 lists "maximum births per epoch" among the required colony limits.

    Stored since Phase 1 and unchecked until the epoch primitive existed. If
    this fails, §9.1's whole concern — reproduction growing "Cells, events,
    model calls, experiments, records, audit workload" exponentially — has no
    rate control at all.
    """
    _seed(conn)
    for index in range(3):
        _born(conn, index)

    with pytest.raises(population.BirthRateExceededError, match="3/3 births already"):
        _born(conn, "one-too-many")

    assert population.births_in_epoch(conn, clock.current_epoch(conn)) == 3


def test_reproduction_counts_against_the_same_cap(conn):
    """A birth is a birth. §9.1's concern is reproduction specifically, so a
    cap the reproduction path did not respect would miss its actual target."""
    _seed(conn)
    parent = _born(conn, "parent")
    lineage.reproduce(conn, parent_cell_id=parent.cell_id, budget_minor_units=5,
                      idempotency_key="child-1")
    lineage.reproduce(conn, parent_cell_id=parent.cell_id, budget_minor_units=5,
                      idempotency_key="child-2")

    assert population.births_in_epoch(conn, clock.current_epoch(conn)) == 3
    with pytest.raises(population.BirthRateExceededError):
        lineage.reproduce(conn, parent_cell_id=parent.cell_id, budget_minor_units=5,
                          idempotency_key="child-3")


def test_the_cap_clears_when_the_epoch_turns(conn):
    """The property that makes this a *rate* limit rather than a total.

    Nothing has to die and nothing has to be reconfigured — simulated time
    passing is sufficient, which is exactly what distinguishes it from carrying
    capacity.
    """
    _seed(conn)
    for index in range(3):
        _born(conn, index)
    with pytest.raises(population.BirthRateExceededError):
        _born(conn, "blocked")

    clock.advance(conn, timedelta(seconds=clock.DEFAULT_EPOCH_DURATION_SECONDS))

    later = _born(conn, "next-epoch")
    assert later.status is CellStatus.ALIVE
    assert population.births_in_epoch(conn, 0) == 3
    assert population.births_in_epoch(conn, 1) == 1


# --- the distinction that matters (§9.3, §10.5) ------------------------------


def test_a_rate_limited_birth_never_displaces_a_cell(conn):
    """§9.3 licenses displacement for "an available population slot"; §10.5
    requires deaths to be objective.

    A rate limit is neither a shortage of slots nor a fact about the Cell that
    would be evicted. If the rate check ran after the capacity check, or if
    `BirthRateExceededError` subclassed `CarryingCapacityError`, a birth would
    reach the displacer and kill something to get around a wait that would have
    cleared by itself — a death caused by impatience, which §10.5 does not
    permit anyone to cause.

    The colony is deliberately at capacity *as well*, so the displacer would
    genuinely fire if it were reached. Without that, a broken ordering would
    simply let the birth through and this test would pass for the wrong reason
    — it would never have exercised the death it is named for.

    This is the single most important test in this file.
    """
    _seed(
        conn,
        PopulationLimits(
            max_living_cells=3,
            max_active_cells=3,
            max_parallel_experiments=20,
            max_births_per_epoch=3,
            max_lineage_population_fraction=1.0,
        ),
    )
    survivors = [_born(conn, index) for index in range(3)]
    # Every one of them is objectively failing and therefore displaceable, so
    # a displacer *would* find a victim if it were ever consulted.
    for cell in survivors:
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="cell_defunding",
            idempotency_key=f"drain:{cell.cell_id}",
            description="drain the cell so it is objectively failing",
            entries=[
                EntrySpec(
                    account_id=f"cell:{cell.cell_id}:cash",
                    amount_minor_units=-10,
                    cell_id=cell.cell_id,
                ),
                EntrySpec(account_id="colony_treasury", amount_minor_units=10,
                          cell_id=cell.cell_id),
            ],
        )

    displacer = displacement.ObjectiveDisplacer()
    with pytest.raises(population.BirthRateExceededError):
        _born(conn, "blocked", displacer=displacer)

    living = conn.execute(
        "SELECT COUNT(*) AS n FROM cells WHERE status != ?", (CellStatus.DEAD.value,)
    ).fetchone()["n"]
    assert living == 3, "the rate limit must not have cost a Cell its life"
    assert conn.execute("SELECT COUNT(*) AS n FROM coroner_reports").fetchone()["n"] == 0


def test_the_rate_error_is_not_a_carrying_capacity_error():
    """Structural, because the runtime consequence is a death.

    Every existing `except population.CarryingCapacityError` in this kernel
    treats the exception as "the colony has no room", which licenses
    displacement. Making the rate error a subclass would silently enrol all of
    them in killing Cells to beat a rate limit.
    """
    assert not issubclass(
        population.BirthRateExceededError, population.CarryingCapacityError
    )
    assert issubclass(population.BirthRateExceededError, population.PopulationError)


def test_the_rate_check_runs_before_the_capacity_check(conn):
    """Order is load-bearing, not incidental.

    A colony that is both at capacity and out of births reports the rate limit,
    because that is the refusal that resolves itself. Reporting capacity first
    would send an operator looking for a Cell to kill.
    """
    _seed(
        conn,
        PopulationLimits(
            max_living_cells=2,
            max_active_cells=2,
            max_parallel_experiments=20,
            max_births_per_epoch=2,
            max_lineage_population_fraction=1.0,
        ),
    )
    _born(conn, "a")
    _born(conn, "b")

    with pytest.raises(population.BirthRateExceededError):
        _born(conn, "c")


# --- counting ----------------------------------------------------------------


def test_dead_cells_still_count_against_the_epoch(conn):
    """§9.1's concern is the *rate* at which work is spawned — "Cells, events,
    model calls, experiments, records, audit workload" — and none of that is
    undone when the Cell dies.

    Counting only the living would let a colony take unlimited births per epoch
    provided it killed them fast enough, which is the exact loop §9.1 names.
    """
    _seed(conn)
    first = _born(conn, "a")
    _born(conn, "b")
    lifecycle.kill(conn, first.cell_id, cause_of_death="budget_exhausted")

    assert population.births_in_epoch(conn, clock.current_epoch(conn)) == 2
    _born(conn, "c")
    with pytest.raises(population.BirthRateExceededError):
        _born(conn, "d")


def test_every_birth_path_stamps_the_epoch():
    """Structural: a third birth path that forgot `born_in_epoch` would be
    invisible to the cap forever, and the cap would silently stop binding.

    Checked against the SQL rather than behaviourally, because the failure mode
    is a path that does not exist yet.
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    inserters = []
    for path in sorted(source_dir.glob("*.py")):
        text = path.read_text()
        if "INSERT INTO cells" not in text:
            continue
        inserters.append(path.name)
        segment = _cell_insert_call(text)
        assert "born_in_epoch" in segment, (
            f"{path.name} inserts a Cell without naming born_in_epoch — §9.2's "
            "cap counts on that column and would silently stop binding"
        )
        # Naming the column is not enough: an insert that names it and binds a
        # constant satisfies the check above while leaving the cap blind. The
        # epoch has to actually be read from the clock.
        assert "clock.current_epoch(conn)" in segment, (
            f"{path.name} names born_in_epoch but does not derive it from the "
            "clock — a constant there is the same bug with the column present"
        )
    assert set(inserters) == {"lifecycle.py", "lineage.py"}, (
        f"birth paths changed: {inserters}. A new one must stamp born_in_epoch."
    )


def _cell_insert_call(source: str) -> str:
    """Source of the `execute` call that inserts a Cell, statement and
    parameters together.

    Scoped by the AST rather than by a character window, because the parameter
    tuple sits several hundred characters past the SQL and any fixed window is
    one added column away from silently checking the wrong text — which it did,
    on the first draft of this test.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if "INSERT INTO cells" in first.value:
                return ast.get_source_segment(source, node) or ""
    raise AssertionError("no Cell insert found in a module that contains the SQL")


def test_the_epoch_primitive_has_exactly_one_definition():
    """`population` enforces §9.2 and `scheduler` enforces §23.3, and neither
    may import the other — so the epoch derivation lives in `clock`.

    Two definitions of "which epoch is it" would be resolved differently by
    different readers, which is the same failure a cached balance would cause
    (Charter C3).
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    definers = [
        path.name
        for path in sorted(source_dir.glob("*.py"))
        if any(
            isinstance(node, ast.FunctionDef) and node.name == "current_epoch"
            for node in ast.walk(ast.parse(path.read_text()))
        )
    ]
    assert definers == ["clock.py"]


# --- unanchored epochs -------------------------------------------------------


def test_an_unanchored_colony_errs_toward_restriction(conn):
    """`mitosis init` anchors epoch zero; a colony driven straight through the
    kernel may not have.

    Without an anchor every birth reports epoch 0, so the cap behaves as a
    lifetime total. That is the conservative direction for the fallback to be
    wrong in — a cap that silently stopped binding would leave §9.2
    unenforced, which is the failure this slice exists to fix — but the refusal
    has to say so, or an operator sees an impossible number.
    """
    _seed(conn, anchor_epochs=False)
    assert not clock.epochs_configured(conn)

    for index in range(3):
        _born(conn, index)
    clock.advance(conn, timedelta(days=30))

    with pytest.raises(population.BirthRateExceededError) as error:
        _born(conn, "still-blocked")
    assert "never anchored epoch zero" in str(error.value)


# --- migration upgrade path (invisible to every other test in this suite) ----


def test_cells_born_before_the_column_existed_belong_to_no_epoch(tmp_path):
    """Migration 0017 adds `born_in_epoch` NULL and does not backfill.

    Every other test builds a fresh database, so a migration's behaviour against
    a *pre-existing* colony is never exercised — this repo has been bitten by
    that before. The property: historical Cells count toward no epoch, rather
    than being stamped into epoch 0 where they would consume a live colony's
    current birth budget with history.
    """
    db_path = tmp_path / "old.db"
    connection = db.connect_and_migrate(db_path)
    _seed(connection)
    for index in range(3):
        _born(connection, index)
    # Simulate rows written before the column existed.
    connection.execute("UPDATE cells SET born_in_epoch = NULL")
    connection.commit()
    connection.close()

    upgraded = db.connect_and_migrate(db_path)
    try:
        assert population.births_in_epoch(upgraded, 0) == 0
        assert population.births_in_epoch(upgraded, clock.current_epoch(upgraded)) == 0
        # And the colony can still give birth — the cap is not consumed by history.
        fresh = _born(upgraded, "after-upgrade")
        assert fresh.status is CellStatus.ALIVE
        assert population.births_in_epoch(upgraded, clock.current_epoch(upgraded)) == 1
    finally:
        upgraded.close()


def test_the_migration_applies_to_a_populated_colony(tmp_path):
    """The real upgrade, run as a migration rather than simulated.

    Builds a colony on the pre-0017 schema, then migrates it — the path a live
    colony actually takes, and the one `connect_and_migrate` on a fresh database
    never covers.
    """
    db_path = tmp_path / "colony.db"
    migrations = sorted(
        (Path(__file__).resolve().parents[1] / "src" / "mitosis" / "migrations").glob("*.sql")
    )
    pre, post = [m for m in migrations if m.name < "0017"], [
        m for m in migrations if m.name >= "0017"
    ]

    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    for migration in pre:
        raw.executescript(migration.read_text())
    # FKs off for the fixture row only: this test is about an ALTER TABLE
    # running against a populated `cells`, not about genome referential
    # integrity. Set after the scripts, because executescript commits and a
    # foreign_keys pragma inside a transaction is a no-op.
    raw.execute("PRAGMA foreign_keys = OFF")
    raw.execute(
        "INSERT INTO cells (cell_id, cell_type, genome_hash, book, status, "
        "created_at_utc, idempotency_key, founder_cell_id, generation) "
        "VALUES ('old', 'explorer', 'h', 'USD_SIM', 'alive', '2026-01-01T00:00:00+00:00', "
        "'k', 'old', 0)"
    )
    raw.commit()

    columns = {r["name"] for r in raw.execute("PRAGMA table_info(cells)")}
    assert "born_in_epoch" not in columns

    for migration in post:
        raw.executescript(migration.read_text())

    columns = {r["name"] for r in raw.execute("PRAGMA table_info(cells)")}
    assert "born_in_epoch" in columns
    assert raw.execute("SELECT born_in_epoch FROM cells").fetchone()["born_in_epoch"] is None
    assert population.births_in_epoch(raw, 0) == 0
    raw.close()
