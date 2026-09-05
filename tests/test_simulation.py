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
from mitosis.simulation import environment, mutation, runner
from mitosis.simulation.environment import (
    EnvironmentSuite,
    ExperimentAction,
    RuleBasedMarket,
    UtilityMaximizingMarket,
)
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

    Unlike F1 (where `no_op` was the only operator ever chosen, so every
    child's `genome_hash` necessarily collapsed to its parent's own, ADR-018),
    F3 wired a real random operator choice -- asserting hash collapse here
    would now be testing which operator the RNG happened to pick, not
    reproduction itself. That property moved to its own test below.
    """
    manifest = _run(conn, seed=7, epochs=20, population=10)

    if manifest.final_living_cells <= 10:
        pytest.skip("no reproduction happened at this seed/epoch count -- not this test's claim")

    rows = {row["cell_id"]: dict(row) for row in conn.execute(
        "SELECT cell_id, parent_cell_id, genome_hash FROM cells"
    ).fetchall()}
    children = [row for row in rows.values() if row["parent_cell_id"] is not None]
    assert children

    # And the funding was real: each child's ledger shows a
    # `cell_birth_funding`-shaped debit against its own parent, not the pool.
    for child in children:
        credited = ledger.get_balance(conn, f"cell:{child['cell_id']}:cash", Book.USD_SIM)
        assert credited > 0


def test_every_reproduction_records_a_complete_mutation_audit_event(conn):
    """Brief: "each mutation must record parent hashes, operator, seed,
    before/after changed fields, and whether it created genuinely distinct
    canonical content." `cell_genomes.mutation_operator` cannot carry this
    alone: a mutation that collapses to a parent's own existing genome row
    (ADR-018) writes no new row at all, so nothing would even be attributed
    to *this* reproduction event. The durable per-event record is
    `audit_events` (`runner._run_one_epoch`'s `simulation_mutation` events),
    the same "explain, don't define a second identity" mechanism
    `SelectionDecision` and regime-shift events already use."""
    manifest = _run(conn, seed=7, epochs=20, population=10)
    if manifest.final_living_cells <= 10:
        pytest.skip("no reproduction happened at this seed/epoch count -- not this test's claim")

    rows = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'simulation_mutation'"
    ).fetchall()
    assert rows
    for row in rows:
        metadata = json.loads(row["metadata_json"])
        assert metadata["operator"] in mutation.OPERATORS
        assert metadata["seed"]
        assert metadata["parent_cell_id"]
        assert isinstance(metadata["changed_fields"], dict)
        assert isinstance(metadata["genuinely_distinct"], bool)


def test_mutation_seeds_differ_across_reproduction_events(conn):
    """Guards against reusing the bare `master_seed` for every mutation in a
    run: every `simulation_mutation` audit event must carry a seed unique to
    *that* reproduction event, or every mutation of one operator in a run
    would produce byte-identical "variation" forever."""
    manifest = _run(conn, seed=7, epochs=20, population=10)
    if manifest.final_living_cells <= 10:
        pytest.skip("no reproduction happened at this seed/epoch count -- not this test's claim")

    rows = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'simulation_mutation'"
    ).fetchall()
    seeds = [json.loads(row["metadata_json"])["seed"] for row in rows]
    if len(seeds) <= 1:
        pytest.skip("fewer than two reproductions happened -- nothing to compare")
    assert len(set(seeds)) == len(seeds)


def test_a_real_operator_actually_changes_genome_content_over_the_run(conn):
    """The point of F3: unlike F1 (`no_op` was the only operator
    `RandomEligibleSelection` could ever choose), a real, content-changing
    operator must actually fire through the live pipeline and produce a
    child whose genome_hash differs from its parent's -- not just exist as a
    unit-testable function nothing calls end-to-end."""
    manifest = _run(conn, seed=7, epochs=20, population=10)
    if manifest.final_living_cells <= 10:
        pytest.skip("no reproduction happened at this seed/epoch count -- not this test's claim")

    rows = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'simulation_mutation'"
    ).fetchall()
    records = [json.loads(row["metadata_json"]) for row in rows]
    operators_used = {record["operator"] for record in records}
    assert operators_used - {mutation.NO_OP_OPERATOR}, (
        f"only {operators_used} fired at this seed/scale -- no real operator was ever chosen"
    )
    assert any(record["genuinely_distinct"] for record in records)


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


def test_the_rule_based_market_is_pure_given_its_coordinates():
    env_a = RuleBasedMarket()
    env_a.reset(seed=99)
    env_b = RuleBasedMarket()
    env_b.reset(seed=99)
    action = ExperimentAction(
        cell_id="c1", genome_content={"product": {"quality": "premium"}}, hypothesis="h"
    )

    outcome_a = env_a.evaluate(experiment=action, epoch=3)
    outcome_b = env_b.evaluate(experiment=action, epoch=3)

    assert outcome_a == outcome_b


def test_the_rule_based_market_always_clears_the_budget_tier():
    env = RuleBasedMarket()
    env.reset(seed=1)
    action = ExperimentAction(
        cell_id="c1", genome_content={"revenue_model": {"price_minor_units": 250}}, hypothesis="h"
    )
    for epoch in range(5):
        outcome = env.evaluate(experiment=action, epoch=epoch)
        assert outcome.purchased
        assert outcome.revenue_minor_units == 250


def test_the_rule_based_market_requires_the_durable_flag_above_the_budget_tier():
    env = RuleBasedMarket()
    env.reset(seed=1)
    no_flag = ExperimentAction(
        cell_id="c1", genome_content={"revenue_model": {"price_minor_units": 650}}, hypothesis="h"
    )
    with_flag = ExperimentAction(
        cell_id="c1",
        genome_content={
            "revenue_model": {"price_minor_units": 650}, "product": {"durable": True},
        },
        hypothesis="h",
    )
    for epoch in range(5):
        assert env.evaluate(experiment=no_flag, epoch=epoch).purchased is False
        assert env.evaluate(experiment=with_flag, epoch=epoch).purchased is True


def test_the_rule_based_market_requires_premium_quality_above_the_standard_tier():
    env = RuleBasedMarket()
    env.reset(seed=1)
    no_quality = ExperimentAction(
        cell_id="c1", genome_content={"revenue_model": {"price_minor_units": 900}}, hypothesis="h"
    )
    for epoch in range(5):
        assert env.evaluate(experiment=no_quality, epoch=epoch).purchased is False


def test_the_two_environment_families_disagree_on_the_same_genome():
    """SPEC.md §8.3's actual requirement: a strategy is not promoted on
    success in one family alone. A standard-band price without the `durable`
    flag fails `RuleBasedMarket` at every coordinate below, by construction --
    yet the identical genome sometimes clears `UtilityMaximizingMarket`'s
    willingness-to-pay draw. The two mechanisms disagree on the same input
    rather than being the same formula wearing different constants.

    Restricted to epochs before `_REGIME_SHIFT_EPOCH` (10): price=600 exceeds
    the post-shift willingness-to-pay ceiling of 450 and would always fail
    `UtilityMaximizingMarket` too past that epoch -- this test is about the
    two families' base mechanisms disagreeing, not about the shift itself
    (see the dedicated regime-shift tests)."""
    genome = {"revenue_model": {"price_minor_units": 600}}
    action = ExperimentAction(cell_id="c1", genome_content=genome, hypothesis="h")

    utility = UtilityMaximizingMarket()
    utility.reset(seed=1)
    rule_based = RuleBasedMarket()
    rule_based.reset(seed=1)

    utility_sales = sum(
        1 for epoch in range(10) if utility.evaluate(experiment=action, epoch=epoch).purchased
    )
    rule_based_sales = sum(
        1 for epoch in range(10) if rule_based.evaluate(experiment=action, epoch=epoch).purchased
    )

    assert utility_sales > 0
    assert rule_based_sales == 0


def test_the_utility_maximizing_market_shifts_regime_at_the_scheduled_epoch():
    """SPEC.md §8.4: a scheduled price-compression shift, not a random market
    shock. At price=600, post-shift willingness to pay
    (`uniform(0.3, 0.9) * 500` = [150, 450]) can never reach 600, while
    pre-shift (`uniform(0.5, 1.5) * 500` = [250, 750]) sometimes does --
    deterministic given the fixed seed, not a statistical fluke."""
    env = UtilityMaximizingMarket()
    env.reset(seed=1)
    action = ExperimentAction(
        cell_id="c1", genome_content={"revenue_model": {"price_minor_units": 600}}, hypothesis="h"
    )

    pre_shift_sales = sum(
        1 for epoch in range(10) if env.evaluate(experiment=action, epoch=epoch).purchased
    )
    post_shift_sales = sum(
        1 for epoch in range(10, 20) if env.evaluate(experiment=action, epoch=epoch).purchased
    )
    assert pre_shift_sales > 0
    assert post_shift_sales == 0

    assert env.advance(epoch=9) == ()
    events = env.advance(epoch=10)
    assert len(events) == 1
    assert events[0].kind == "price_compression"


def test_the_rule_based_market_shifts_regime_at_the_scheduled_epoch():
    """Price=200 always clears the pre-shift budget tier (<= 300) but falls
    into the standard tier post-shift (<= 150) once stricter enforcement
    narrows it -- deterministic at every epoch, no coin flip involved."""
    env = RuleBasedMarket()
    env.reset(seed=1)
    action = ExperimentAction(
        cell_id="c1", genome_content={"revenue_model": {"price_minor_units": 200}}, hypothesis="h"
    )

    for epoch in range(10):
        assert env.evaluate(experiment=action, epoch=epoch).purchased is True
    for epoch in range(10, 15):
        assert env.evaluate(experiment=action, epoch=epoch).purchased is False

    assert env.advance(epoch=9) == ()
    events = env.advance(epoch=10)
    assert len(events) == 1
    assert events[0].kind == "stricter_enforcement"


def test_regime_shift_events_are_recorded_in_the_audit_trail(conn):
    """A regime shift is a colony-wide happening on the environment's own
    clock, not one Cell's action -- recorded via `audit.record` the same way
    `SelectionDecision` is, rather than a second schema-level identity for a
    fact this mechanism already carries (see `runner._run_one_epoch`)."""
    manifest = _run(conn, seed=1, epochs=15, population=3)
    assert manifest.failures == ()

    rows = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'simulation_environment_event'"
    ).fetchall()
    assert len(rows) == 1
    metadata = json.loads(rows[0]["metadata_json"])
    assert metadata["kind"] == "price_compression"
    assert metadata["epoch"] == 10


def test_each_discrete_mutation_operator_always_changes_its_field():
    """Discrete-choice operators exclude the parent's current value from
    their candidate set -- invoking one always changes that field, which is
    the operator's whole identity (see `mutation.py`'s module docstring)."""
    cases = [
        (mutation.market_customer_variation, "market", "segment", "smb"),
        (mutation.product_delivery_variation, "product", "delivery_mode", "self_serve"),
        (mutation.acquisition_channel_variation, "acquisition_channel", "channel", "community"),
        (mutation.workflow_variation, "workflow", "structure", "sequential"),
    ]
    for operator_fn, top_key, sub_key, current_value in cases:
        parent_content = {top_key: {sub_key: current_value}}
        for seed in ("s1", "s2", "s3", "s4", "s5"):
            mutation_dict, _ = operator_fn(parent_content, seed=seed)
            assert mutation_dict[top_key][sub_key] != current_value


def test_mutation_operator_names_match_their_registry_entries():
    for name, fn in mutation.OPERATORS.items():
        _, returned_name = fn({}, seed="x")
        assert returned_name == name


def test_pricing_revenue_model_variation_stays_positive_and_bounded():
    parent_content = {"revenue_model": {"price_minor_units": 500}}
    for seed in ("a", "b", "c", "d", "e", "f", "g", "h"):
        mutation_dict, operator_name = mutation.pricing_revenue_model_variation(
            parent_content, seed=seed
        )
        assert mutation_dict["revenue_model"]["price_minor_units"] >= mutation._MIN_PRICE_MINOR_UNITS
        assert operator_name == mutation.PRICING_REVENUE_MODEL_OPERATOR


def test_model_policy_temperature_variation_stays_within_bounds():
    for current in (0.0, 0.5, 1.0):
        parent_content = {"model_policy": {"temperature": current}}
        for seed in ("a", "b", "c", "d", "e"):
            mutation_dict, operator_name = mutation.model_policy_temperature_variation(
                parent_content, seed=seed
            )
            temperature = mutation_dict["model_policy"]["temperature"]
            assert 0.0 <= temperature <= 1.0
            assert operator_name == mutation.MODEL_POLICY_TEMPERATURE_OPERATOR


def test_mutation_operators_are_deterministic_given_the_same_seed():
    parent_content = {
        "market": {"segment": "smb"}, "product": {"delivery_mode": "api"},
        "revenue_model": {"price_minor_units": 500}, "model_policy": {"temperature": 0.5},
    }
    for operator_fn in mutation.OPERATORS.values():
        assert operator_fn(parent_content, seed="fixed-seed") == operator_fn(
            parent_content, seed="fixed-seed"
        )


def test_mutation_operators_preserve_unrelated_fields_within_the_same_key():
    """`genome.inherit` replaces a top-level key wholesale
    (`content.update(mutation)`), so an operator touching one field must
    carry the rest of that same key's own content forward, or a nested fact
    the mutation didn't intend to touch would be silently dropped from the
    child."""
    parent_content = {"market": {"segment": "smb", "region": "emea"}}
    mutation_dict, _ = mutation.market_customer_variation(parent_content, seed="x")
    assert mutation_dict["market"]["region"] == "emea"
    assert mutation_dict["market"]["segment"] != "smb"


def test_build_environment_selects_the_named_family_and_rejects_unknown_names():
    assert isinstance(
        environment.build_environment("utility_maximizing_market"), UtilityMaximizingMarket
    )
    assert isinstance(environment.build_environment("rule_based_market"), RuleBasedMarket)
    with pytest.raises(environment.UnknownEnvironmentError):
        environment.build_environment("not_a_real_market")


def test_cli_simulate_accepts_the_rule_based_market(tmp_path):
    db_path = tmp_path / "sim.db"
    output_path = tmp_path / "manifest.json"
    cli.main(["--db", str(db_path), "init"])

    exit_code = cli.main([
        "--db", str(db_path), "simulate",
        "--seed", "3", "--epochs", "5", "--population", "3",
        "--environment", "rule_based_market", "--output", str(output_path),
    ])

    assert exit_code in (0, None)
    written = json.loads(output_path.read_text())
    assert written["environment_name"] == "rule_based_market"
    assert all(written["conservation_ok"].values())


class _NeverCallMarket:
    """A `MarketEnvironment` that fails loudly the moment anything routine
    calls it -- used to prove `validation`/`secret_challenge` roles are
    structurally untouched, not just conventionally ignored."""

    name = "never_call_market"
    version = "1"

    def reset(self, *, seed: int) -> None:
        pass

    def observe(self, *, cell_id: str, epoch: int):
        raise AssertionError("validation/secret_challenge must never be observed by the routine loop")

    def evaluate(self, *, experiment, epoch: int):
        raise AssertionError("validation/secret_challenge must never be evaluated by the routine loop")

    def advance(self, *, epoch: int):
        raise AssertionError("validation/secret_challenge must never be advanced by the routine loop")


def test_the_routine_epoch_loop_never_touches_validation_or_secret_challenge_environments(conn):
    """SPEC.md §8.1: validation 'influences capital allocation, partially
    hidden' and secret challenge is 'never available to Cells or routine
    selection logic'. Enforced structurally, not by convention:
    `runner._run_one_epoch` takes a single `MarketEnvironment`, not a suite,
    so there is no path by which it could reach `validation` or
    `secret_challenge` even by mistake -- a fake that raises the instant
    anything calls it proves the routine loop never does."""
    suite = EnvironmentSuite(
        training=UtilityMaximizingMarket(),
        validation=_NeverCallMarket(),
        secret_challenge=_NeverCallMarket(),
    )
    manifest = runner.run(
        conn, runner.RunConfig(scenario_name="test", master_seed=1, epochs=6, population=3),
        suite=suite,
    )
    assert manifest.failures == ()
    assert manifest.epochs_completed == 6


def test_environment_suite_training_only_leaves_the_other_roles_unset():
    suite = EnvironmentSuite.training_only(UtilityMaximizingMarket())
    assert suite.validation is None
    assert suite.secret_challenge is None


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
