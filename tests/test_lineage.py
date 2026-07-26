"""Reproduction and lineage tracking (SPEC.md §9.2/§9.4, §16; ADR-019)."""

import json
import sqlite3

import pytest

from mitosis import db, genome, ledger, lifecycle, lineage, population
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellStatus, CellType, EntrySpec, PopulationLimits

SEED = 1_000_000


def _colony(conn, *, cap=1.0, founders=1, budget=100_000):
    population.set_limits_if_absent(
        conn,
        PopulationLimits(
            max_living_cells=100,
            max_active_cells=100,
            max_parallel_experiments=10,
            max_births_per_epoch=10,
            max_lineage_population_fraction=cap,
        ),
    )
    ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="seed",
        idempotency_key="seed",
        description="seed",
        entries=[
            EntrySpec(account_id="external_capital", amount_minor_units=-SEED),
            EntrySpec(account_id="seed_bank", amount_minor_units=SEED),
        ],
    )
    return [
        lifecycle.create_cell(
            conn,
            cell_type=CellType.COMMERCIAL,
            budget_minor_units=budget,
            book=Book.USD_SIM,
            idempotency_key=f"founder:{i}",
        )
        for i in range(founders)
    ]


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


# --- birth by reproduction ----------------------------------------------------


def test_seeded_cell_founds_its_own_lineage(conn):
    (founder,) = _colony(conn)
    assert founder.parent_cell_id is None
    assert founder.founder_cell_id == founder.cell_id
    assert founder.generation == 0


def test_child_records_parent_founder_and_generation(conn):
    (parent,) = _colony(conn)
    child = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=1_000, idempotency_key="c1"
    )
    assert child.parent_cell_id == parent.cell_id
    assert child.founder_cell_id == parent.cell_id
    assert child.generation == 1


def test_generation_and_founder_propagate_down_a_chain(conn):
    (founder,) = _colony(conn)
    current = founder
    for depth in range(1, 5):
        current = lineage.reproduce(
            conn,
            parent_cell_id=current.cell_id,
            budget_minor_units=100,
            idempotency_key=f"gen{depth}",
        )
        assert current.generation == depth
        # every descendant keeps pointing at the original founder, not its parent
        assert current.founder_cell_id == founder.cell_id


def test_child_is_funded_from_parent_cash_not_the_colony(conn):
    (parent,) = _colony(conn, budget=5_000)
    seed_before = ledger.get_balance(conn, "seed_bank", Book.USD_SIM)

    child = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=1_200, idempotency_key="c1"
    )

    assert ledger.get_balance(conn, cell_cash(parent.cell_id), Book.USD_SIM) == 3_800
    assert ledger.get_balance(conn, cell_cash(child.cell_id), Book.USD_SIM) == 1_200
    assert ledger.get_balance(conn, "seed_bank", Book.USD_SIM) == seed_before
    assert ledger.verify_conservation(conn, Book.USD_SIM) is True
    assert ledger.verify_chain(conn) is True


def test_child_inherits_book_and_type_by_default(conn):
    (parent,) = _colony(conn)
    child = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    assert child.book == parent.book
    assert child.cell_type == parent.cell_type


def test_child_type_can_be_overridden(conn):
    (parent,) = _colony(conn)
    child = lineage.reproduce(
        conn,
        parent_cell_id=parent.cell_id,
        budget_minor_units=100,
        idempotency_key="c1",
        cell_type=CellType.AUDITOR,
    )
    assert child.cell_type == CellType.AUDITOR
    assert child.book == parent.book


def test_reproduction_emits_an_audit_event(conn):
    """Charter C10 — birth by reproduction is a lifecycle transition too."""
    (parent,) = _colony(conn)
    child = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    row = conn.execute(
        "SELECT * FROM audit_events WHERE cell_id = ? AND event_type = 'cell_lifecycle_transition'",
        (child.cell_id,),
    ).fetchone()
    assert row is not None
    metadata = json.loads(row["metadata_json"])
    assert metadata["parent_cell_id"] == parent.cell_id
    assert metadata["generation"] == 1
    assert metadata["to"] == "alive"


# --- genome parentage under content addressing (ADR-018) ----------------------


def test_unmutated_child_shares_the_parent_genome_row(conn):
    (parent,) = _colony(conn)
    child = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    assert child.genome_hash == parent.genome_hash
    rows = conn.execute("SELECT COUNT(*) AS n FROM cell_genomes").fetchone()
    assert rows["n"] == 1  # identical content is the same genome, not a copy


def test_mutated_child_gets_a_distinct_genome_with_a_parent_edge(conn):
    (parent,) = _colony(conn)
    child = lineage.reproduce(
        conn,
        parent_cell_id=parent.cell_id,
        budget_minor_units=100,
        idempotency_key="c1",
        mutation={"strategy": "v2"},
        mutation_operator="test_op",
    )
    assert child.genome_hash != parent.genome_hash

    row = conn.execute(
        "SELECT * FROM cell_genomes WHERE genome_hash = ?", (child.genome_hash,)
    ).fetchone()
    assert json.loads(row["parent_genome_hashes"]) == [parent.genome_hash]
    assert row["mutation_operator"] == "test_op"
    assert row["version"] == 2
    assert json.loads(row["canonical_genome_json"])["strategy"] == "v2"


def test_mutation_that_changes_nothing_creates_no_self_referential_edge(conn):
    """Content addressing makes an ineffective mutation land back on the
    parent's own genome; that must not record a genome as its own parent."""
    (parent,) = _colony(conn)
    child = lineage.reproduce(
        conn,
        parent_cell_id=parent.cell_id,
        budget_minor_units=100,
        idempotency_key="c1",
        mutation={"cell_type": parent.cell_type.value},  # identical content
    )
    assert child.genome_hash == parent.genome_hash
    row = conn.execute(
        "SELECT parent_genome_hashes FROM cell_genomes WHERE genome_hash = ?",
        (child.genome_hash,),
    ).fetchone()
    assert json.loads(row["parent_genome_hashes"]) == []


def test_non_serializable_mutation_is_rejected(conn):
    (parent,) = _colony(conn)
    with pytest.raises(genome.GenomeError):
        lineage.reproduce(
            conn,
            parent_cell_id=parent.cell_id,
            budget_minor_units=100,
            idempotency_key="c1",
            mutation={"bad": object()},
        )


# --- guards -------------------------------------------------------------------


def test_unknown_parent_is_rejected(conn):
    _colony(conn)
    with pytest.raises(lineage.LineageError):
        lineage.reproduce(
            conn, parent_cell_id="nope", budget_minor_units=100, idempotency_key="c1"
        )


def test_non_positive_budget_is_rejected(conn):
    (parent,) = _colony(conn)
    for bad in (0, -1):
        with pytest.raises(lineage.LineageError):
            lineage.reproduce(
                conn,
                parent_cell_id=parent.cell_id,
                budget_minor_units=bad,
                idempotency_key=f"c{bad}",
            )


def test_parent_cannot_fund_more_than_it_holds(conn):
    """Charter C4 on the reproduction path."""
    (parent,) = _colony(conn, budget=1_000)
    with pytest.raises(lineage.LineageError):
        lineage.reproduce(
            conn, parent_cell_id=parent.cell_id, budget_minor_units=1_001, idempotency_key="c1"
        )
    assert ledger.get_balance(conn, cell_cash(parent.cell_id), Book.USD_SIM) == 1_000
    assert ledger.verify_conservation(conn, Book.USD_SIM) is True


def test_parent_may_fund_exactly_what_it_holds(conn):
    (parent,) = _colony(conn, budget=1_000)
    child = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=1_000, idempotency_key="c1"
    )
    assert ledger.get_balance(conn, cell_cash(parent.cell_id), Book.USD_SIM) == 0
    assert ledger.get_balance(conn, cell_cash(child.cell_id), Book.USD_SIM) == 1_000


@pytest.mark.parametrize("transition", ["sleep", "quarantine", "kill"])
def test_only_an_alive_cell_may_reproduce(conn, transition):
    """A dormant Cell is idle, a quarantined Cell restricted, a dead Cell
    inert (Charter C8) — none may become a parent."""
    (parent,) = _colony(conn)
    if transition == "sleep":
        lifecycle.sleep(conn, parent.cell_id)
    elif transition == "quarantine":
        lifecycle.quarantine(conn, parent.cell_id, reason="test")
    else:
        lifecycle.kill(conn, parent.cell_id, cause_of_death="test")

    with pytest.raises(lineage.LineageError):
        lineage.reproduce(
            conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
        )


def test_reproduction_respects_carrying_capacity(conn):
    (parent,) = _colony(conn)
    conn.execute("UPDATE colony_config SET max_living_cells = 1 WHERE id = 1")
    with pytest.raises(population.CarryingCapacityError):
        lineage.reproduce(
            conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
        )


def test_reproduction_is_idempotent(conn):
    (parent,) = _colony(conn, budget=5_000)
    first = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=1_000, idempotency_key="same"
    )
    second = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=1_000, idempotency_key="same"
    )
    assert first.cell_id == second.cell_id
    # the parent must be charged exactly once
    assert ledger.get_balance(conn, cell_cash(parent.cell_id), Book.USD_SIM) == 4_000


# --- the lineage cap (§9.2, §9.4) ---------------------------------------------


def test_lineage_cap_denies_a_birth_that_would_exceed_the_share(conn):
    (parent,) = _colony(conn, cap=0.20, founders=1)
    with pytest.raises(lineage.LineageCapExceededError):
        lineage.reproduce(
            conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
        )


def test_lineage_cap_allows_a_birth_exactly_at_the_boundary(conn):
    """4 founders, cap 0.40: the child makes the lineage 2/5 = 0.40, which is
    at the cap and therefore permitted."""
    founders = _colony(conn, cap=0.40, founders=4)
    child = lineage.reproduce(
        conn, parent_cell_id=founders[0].cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    assert child.generation == 1
    assert lineage.lineage_fraction(conn, founders[0].cell_id) == pytest.approx(0.40)


def test_a_death_frees_lineage_room(conn):
    """The cap counts living Cells, so killing one lets the lineage grow
    again — the population-share limit is not a lifetime birth quota."""
    founders = _colony(conn, cap=0.40, founders=4)
    parent = founders[0]
    child = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
    )

    with pytest.raises(lineage.LineageCapExceededError):
        lineage.reproduce(
            conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c2"
        )

    lifecycle.kill(conn, child.cell_id, cause_of_death="test")
    again = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c3"
    )
    assert again.generation == 1


def test_seeded_founders_are_not_subject_to_the_lineage_cap(conn):
    """§9.4 caps population share *descended from one ancestor*. A seeded
    founder has no ancestor, so the cap cannot govern its own birth — a
    single founder is trivially 100% of a one-Cell colony, and seeding more
    founders is the intended way to make room, never something the cap
    should block."""
    founders = _colony(conn, cap=0.20, founders=6)
    assert len(founders) == 6
    assert population.living_count(conn) == 6
    # each founder is its own lineage, at 1/6 — above no cap, blocked by none
    assert all(f.founder_cell_id == f.cell_id for f in founders)
    assert lineage.lineage_fraction(conn, founders[0].cell_id) == pytest.approx(1 / 6)


def test_cap_of_one_disables_the_limit(conn):
    (parent,) = _colony(conn, cap=1.0)
    for i in range(3):
        lineage.reproduce(
            conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key=f"c{i}"
        )
    assert lineage.living_lineage_count(conn, parent.cell_id) == 4


# --- queries ------------------------------------------------------------------


def test_tree_queries(conn):
    founders = _colony(conn, cap=1.0, founders=2)
    root, other = founders
    child_a = lineage.reproduce(
        conn, parent_cell_id=root.cell_id, budget_minor_units=1_000, idempotency_key="a"
    )
    child_b = lineage.reproduce(
        conn, parent_cell_id=root.cell_id, budget_minor_units=1_000, idempotency_key="b"
    )
    grandchild = lineage.reproduce(
        conn, parent_cell_id=child_a.cell_id, budget_minor_units=100, idempotency_key="g"
    )

    assert {c.cell_id for c in lineage.children(conn, root.cell_id)} == {
        child_a.cell_id,
        child_b.cell_id,
    }
    assert {c.cell_id for c in lineage.descendants(conn, root.cell_id)} == {
        child_a.cell_id,
        child_b.cell_id,
        grandchild.cell_id,
    }
    # nearest ancestor first, up to the founder
    assert [c.cell_id for c in lineage.ancestors(conn, grandchild.cell_id)] == [
        child_a.cell_id,
        root.cell_id,
    ]
    assert {c.cell_id for c in lineage.founders(conn)} == {root.cell_id, other.cell_id}
    assert lineage.living_lineage_count(conn, root.cell_id) == 4
    assert lineage.living_lineage_count(conn, other.cell_id) == 1
    # the other founder's lineage is untouched by root's growth
    assert lineage.descendants(conn, other.cell_id) == []


def test_lineage_members_includes_the_dead_but_the_living_count_does_not(conn):
    (root,) = _colony(conn, cap=1.0)
    child = lineage.reproduce(
        conn, parent_cell_id=root.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    lifecycle.kill(conn, child.cell_id, cause_of_death="test")

    assert len(lineage.lineage_members(conn, root.cell_id)) == 2
    assert lineage.living_lineage_count(conn, root.cell_id) == 1
    # a dead Cell keeps its lineage bookkeeping — coroner reports need it
    assert lifecycle.get_cell(conn, child.cell_id).founder_cell_id == root.cell_id


def test_lineage_summary_ranks_by_living_size(conn):
    founders = _colony(conn, cap=1.0, founders=3)
    for i in range(2):
        lineage.reproduce(
            conn,
            parent_cell_id=founders[1].cell_id,
            budget_minor_units=100,
            idempotency_key=f"c{i}",
        )

    summary = lineage.lineage_summary(conn)
    assert len(summary) == 3
    assert summary[0]["founder_cell_id"] == founders[1].cell_id
    assert summary[0]["living"] == 3
    assert summary[0]["max_generation"] == 1
    assert summary[0]["fraction"] == pytest.approx(3 / 5)


def test_lineage_fraction_is_zero_for_an_empty_colony(conn):
    population.set_limits_if_absent(conn, population.DEFAULT_POPULATION_LIMITS)
    assert lineage.lineage_fraction(conn, "nobody") == 0.0


# --- integrity ----------------------------------------------------------------


def test_integrity_holds_across_a_realistic_colony(conn):
    founders = _colony(conn, cap=1.0, founders=3)
    a = lineage.reproduce(
        conn, parent_cell_id=founders[0].cell_id, budget_minor_units=1_000, idempotency_key="a"
    )
    lineage.reproduce(
        conn, parent_cell_id=a.cell_id, budget_minor_units=100, idempotency_key="b"
    )
    lifecycle.kill(conn, founders[2].cell_id, cause_of_death="test")
    assert lineage.verify_lineage_integrity(conn) is True


@pytest.mark.parametrize("column,value", [("generation", 99), ("founder_cell_id", "wrong")])
def test_integrity_detects_a_corrupted_denormalized_field(conn, column, value):
    (root,) = _colony(conn, cap=1.0)
    child = lineage.reproduce(
        conn, parent_cell_id=root.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    conn.execute(f"UPDATE cells SET {column} = ? WHERE cell_id = ?", (value, child.cell_id))
    assert lineage.verify_lineage_integrity(conn) is False


def test_integrity_detects_a_parent_cycle(conn):
    (root,) = _colony(conn, cap=1.0)
    child = lineage.reproduce(
        conn, parent_cell_id=root.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    conn.execute(
        "UPDATE cells SET parent_cell_id = ? WHERE cell_id = ?", (child.cell_id, root.cell_id)
    )
    assert lineage.verify_lineage_integrity(conn) is False


def test_a_parent_with_children_cannot_be_deleted(conn):
    """The FK on parent_cell_id makes orphaning a child impossible through
    normal SQL — the schema backs the integrity check rather than relying
    on it."""
    (root,) = _colony(conn, cap=1.0)
    lineage.reproduce(
        conn, parent_cell_id=root.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM cells WHERE cell_id = ?", (root.cell_id,))


def test_integrity_detects_a_missing_parent_row(conn):
    """Only reachable with FK enforcement off (a partial restore, a bulk
    load) — but that is exactly when a structural check has to earn its
    keep, so the defensive branch is covered."""
    (root,) = _colony(conn, cap=1.0)
    lineage.reproduce(
        conn, parent_cell_id=root.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM cells WHERE cell_id = ?", (root.cell_id,))
    conn.execute("PRAGMA foreign_keys = ON")
    assert lineage.verify_lineage_integrity(conn) is False


def test_status_survives_a_corrupted_founder_and_flags_it(conn, tmp_path, capsys):
    """A NULL founder is unreachable through the kernel, but a corrupted DB
    must report cleanly rather than traceback — and integrity must say so."""
    from mitosis import cli

    db_path = tmp_path / "corrupt.db"
    cli.main(["--db", str(db_path), "init"])
    cli.main([
        "--db", str(db_path), "create-cell", "--type", "commercial",
        "--budget", "10.00", "--idempotency-key", "c1",
    ])
    capsys.readouterr()

    raw = sqlite3.connect(db_path)
    raw.execute("UPDATE cells SET founder_cell_id = NULL")
    raw.commit()
    raw.close()

    assert cli.main(["--db", str(db_path), "status"]) == 0
    out = capsys.readouterr().out
    assert "<none>" in out
    assert "integrity: False" in out
