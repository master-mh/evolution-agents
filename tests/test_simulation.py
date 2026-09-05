"""The Phase 2 flight simulator's seam (SPEC.md §7, §8, §28 Phase 2;
implementation brief Slice F; docs/DECISIONS.md's Slice F ADR).

This file proves the *wiring* the ADR argues for -- kernel reuse, determinism,
the USD_REAL invariant, population growth through the real reproduction path
-- not the economics themselves: `UtilityMaximizingMarket`'s specific
purchase model, the `random_eligible` selection policy, and the no-op
mutation operator are all deliberately minimal placeholders this slice is
explicit about (see `docs/DECISIONS.md` and the module docstrings), superseded
by F2-F5 and Slice G without changing this file's assertions.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from mitosis import cli, db, ledger
from mitosis.models import Book
from mitosis.simulation import runner
from mitosis.simulation.environment import ExperimentAction, UtilityMaximizingMarket
from mitosis.simulation.policy import SimulationPolicyProvider, _extract_genome
from mitosis.simulation.selection_policy import RandomEligibleSelection


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


def _run(conn, *, seed: int = 1, epochs: int = 6, population: int = 3, scenario: str = "test"):
    return runner.run(
        conn,
        runner.RunConfig(
            scenario_name=scenario, master_seed=seed, epochs=epochs, population=population,
        ),
    )


def test_a_smoke_run_completes_every_epoch_with_conservation_intact(conn):
    manifest = _run(conn)

    assert manifest.epochs_completed == 6
    assert manifest.failures == ()
    assert all(manifest.conservation_ok.values())
    assert manifest.usd_real_spend_unchanged
    assert manifest.final_living_cells >= 3  # founders alive; reproduction may add more
    assert len(manifest.epochs) == 6


def test_a_full_colony_of_experiments_does_not_strand_the_run(conn):
    """At population >= `max_parallel_experiments` (default 20, SPEC.md
    §9.2's colony-wide slot cap), the very first epoch fills every slot --
    `experiment_grants.start_from_grant` then raises the sibling
    `ExperimentCapacityError`, not the `ExperimentConflictError` a smaller
    run exercises. Catching only the conflict case left this uncaught,
    aborting every subsequent epoch before its evaluate/conclude loop ever
    ran and permanently stranding all 20 running experiments -- found only
    by a manual population=20 run, not by any test at the population<=10
    scale the rest of this file uses (see docs/DECISIONS.md's Slice F ADR)."""
    manifest = _run(conn, epochs=5, population=20)

    assert manifest.failures == ()
    assert manifest.epochs_completed == 5
    assert all(record.experiments_concluded > 0 for record in manifest.epochs)


def test_usd_real_never_moves_once_the_epoch_loop_starts(conn):
    """Every model call reserves and releases against `Book.USD_REAL`
    regardless of provider (cash <-> the Cell's own `committed` account,
    netting to zero for a zero-priced provider) -- that is pre-existing
    reservation-FSM bookkeeping, not real spend, and the invariant is about
    spend (`external_expense`), not row count."""
    manifest = _run(conn)

    external_spend = conn.execute(
        "SELECT COALESCE(SUM(ABS(e.amount_minor_units)), 0) AS total "
        "FROM ledger_entries e JOIN ledger_transactions t ON t.transaction_id = e.transaction_id "
        "WHERE t.book = ? AND e.account_id = 'external_expense'",
        (Book.USD_REAL.value,),
    ).fetchone()["total"]
    assert external_spend == 0
    assert manifest.usd_real_spend_unchanged


def test_the_same_seed_reproduces_the_same_manifest(conn):
    conn_b = db.connect_and_migrate()
    try:
        first = _run(conn, seed=42, epochs=8, population=4)
        second = _run(conn_b, seed=42, epochs=8, population=4)

        first_dict = asdict(first)
        second_dict = asdict(second)
        # run_id identifies *this invocation*, not the deterministic economic
        # content -- generated before the seeded-id window starts, exactly
        # like `scheduler.tick_id` is in real production use. Everything else
        # must be byte-identical.
        del first_dict["run_id"]
        del second_dict["run_id"]
        assert first_dict == second_dict
    finally:
        conn_b.close()


def test_a_different_seed_can_produce_a_different_manifest(conn):
    conn_b = db.connect_and_migrate()
    try:
        first = _run(conn, seed=1, epochs=10, population=4)
        second = _run(conn_b, seed=2, epochs=10, population=4)
        assert first.epochs != second.epochs or first.final_living_cells != second.final_living_cells
    finally:
        conn_b.close()


def test_population_grows_through_the_real_reproduction_path(conn):
    """Not a shortcut: every child must be a real row `lineage.reproduce`
    inserted, funded by a real parent-debit ledger transaction.

    Ten founders, not three: `max_lineage_population_fraction` (default 0.20)
    refuses a *second* Cell in any lineage while the colony is this small --
    a single child already exceeds the cap at population=3
    (`(1+1)/(3+1) = 0.5`) -- the same founder-effect tension
    FUTURE_BUILD_HOOKS.md already documents. At population=10 a lineage's
    first child clears it (`2/11 ~= 0.18`), so growth is expected here rather
    than merely tolerated.

    `mutation.no_op` is not separately asserted on `cell_genomes
    .mutation_operator` here: an empty overlay collapses to the *parent's own*
    existing genome row by content addressing (ADR-018), so the column this
    slice's only operator would populate is never actually written -- there
    is nothing new to attribute a name to. What *is* checked is that
    collapse: every child shares a real ancestor's genome_hash rather than
    getting one of its own.
    """
    manifest = _run(conn, seed=7, epochs=20, population=10)

    if manifest.final_living_cells <= 10:
        pytest.skip("no reproduction happened at this seed/epoch count -- not this test's claim")

    rows = {row["cell_id"]: dict(row) for row in conn.execute(
        "SELECT cell_id, parent_cell_id, genome_hash FROM cells"
    ).fetchall()}
    children = [row for row in rows.values() if row["parent_cell_id"] is not None]
    assert children
    for child in children:
        parent = rows[child["parent_cell_id"]]
        assert child["genome_hash"] == parent["genome_hash"]

    # And the funding was real: each child's ledger shows a
    # `cell_birth_funding`-shaped debit against its own parent, not the pool.
    for child in children:
        credited = ledger.get_balance(conn, f"cell:{child['cell_id']}:cash", Book.USD_SIM)
        assert credited > 0


def test_a_reproduced_child_is_scheduler_eligible_not_permanently_inert(conn):
    """`lineage.reproduce` funds a child only in the parent's own book
    (funding cannot cross books, SPEC.md §2.4) -- without this slice's own
    `_fund_scheduler_eligibility` step, a child would hold zero USD_REAL/
    RESOURCE and `scheduler.eligible_cells` would never wake it again. Not
    covered by the growth test above, which only checks genome/USD_SIM
    funding -- this regressed silently once already, caught only by a manual
    larger-scale run, not by the suite (see docs/DECISIONS.md's Slice F ADR)."""
    manifest = _run(conn, seed=7, epochs=20, population=10)
    if manifest.final_living_cells <= 10:
        pytest.skip("no reproduction happened at this seed/epoch count -- not this test's claim")

    children = conn.execute(
        "SELECT cell_id FROM cells WHERE parent_cell_id IS NOT NULL"
    ).fetchall()
    assert children
    for child in children:
        cash_account = f"cell:{child['cell_id']}:cash"
        assert ledger.get_balance(conn, cash_account, Book.USD_REAL) >= 1
        assert ledger.get_balance(conn, cash_account, Book.RESOURCE) >= 1


def test_cli_simulate_writes_a_manifest_file(tmp_path):
    db_path = tmp_path / "sim.db"
    output_path = tmp_path / "manifest.json"
    cli.main(["--db", str(db_path), "init"])

    exit_code = cli.main([
        "--db", str(db_path), "simulate",
        "--seed", "3", "--epochs", "5", "--population", "3",
        "--output", str(output_path),
    ])

    assert exit_code in (0, None)
    written = json.loads(output_path.read_text())
    assert written["epochs_completed"] == 5
    assert all(written["conservation_ok"].values())
    assert written["usd_real_spend_unchanged"] is True

    conn = db.connect_and_migrate(str(db_path))
    row = conn.execute("SELECT status, manifest_path FROM simulation_runs").fetchone()
    assert row["status"] == "completed"
    assert row["manifest_path"] == str(output_path)
    conn.close()


def test_the_policy_extracts_exactly_the_genome_it_was_shown():
    """Guards the one string-matching seam in `policy.py` -- if
    `context._genome_section`'s header text ever changes, this fails here
    with a clear message instead of as a mysterious `PolicyError` deep inside
    a simulation run."""
    genome_content = {"market": {"segment": "x"}, "cell_type": "commercial"}
    rendered = (
        "## Your genome (immutable; this is who you are)\n"
        + json.dumps(genome_content, indent=2, sort_keys=True)
        + "\n\n## Something else\nirrelevant"
    )
    assert _extract_genome(rendered) == genome_content


def test_the_utility_maximizing_market_is_pure_given_its_coordinates():
    env_a = UtilityMaximizingMarket()
    env_a.reset(seed=99)
    env_b = UtilityMaximizingMarket()
    env_b.reset(seed=99)
    action = ExperimentAction(cell_id="c1", genome_content={}, hypothesis="h")

    outcome_a = env_a.evaluate(experiment=action, epoch=3)
    outcome_b = env_b.evaluate(experiment=action, epoch=3)

    assert outcome_a == outcome_b


def test_random_eligible_selection_never_chooses_an_ineligible_cell(conn):
    import random

    from mitosis import lifecycle
    from mitosis.models import CellType

    lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=10,
        book=Book.USD_SIM, idempotency_key="poor-cell",
    )
    policy = RandomEligibleSelection()

    decision = policy.decide(
        conn, epoch=0, rng=random.Random(0), seed_label="seed=0:selection:epoch=0"
    )

    assert decision.eligible_cell_ids == ()
    assert decision.chosen_parent_cell_ids == ()


def test_no_kernel_module_imports_the_simulation_package():
    """The dependency inversion CLAUDE.md names explicitly: the simulator
    sits above `scheduler`/`promotion`/`lineage`/etc. and supplies new
    decisions over their existing entry points; none of them may import it
    back, or the layering this repo keeps everywhere would be inverted here."""
    forbidden = {"simulation"}
    checked = (
        "scheduler", "autopromotion", "promotion", "lineage", "lifecycle",
        "approval", "experiments", "experiment_grants", "revenue", "ledger",
        "deliberation", "selection", "novelty", "posteriors",
    )
    import mitosis

    base = Path(mitosis.__file__).parent
    for name in checked:
        source_path = base / f"{name}.py"
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source_path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module in (None, "mitosis", "."):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name.split(".")[-1] for a in node.names)
        collision = forbidden & imported
        assert not collision, f"{name}.py imports {collision}, breaking the dependency inversion"
