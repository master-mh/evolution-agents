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
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from mitosis import cli, db, ledger
from mitosis.models import Book
from mitosis.simulation import chaos, environment, mutation, runner, selection_policy
from mitosis.simulation.environment import (
    EnvironmentSuite,
    ExperimentAction,
    Outcome,
    RuleBasedMarket,
    UtilityMaximizingMarket,
)
from mitosis.simulation.policy import SimulationPolicyProvider, _extract_genome
from mitosis.simulation.selection_policy import (
    ParetoSelection,
    RandomEligibleSelection,
    SelectionDecision,
    SingleLeaderboardSelection,
)


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


class _NamedWrapperSelection:
    """A minimal `SelectionPolicy`-conforming wrapper reporting a distinct
    name/version, used only to prove the run record reads `.name`/`.version`
    from the actual policy object rather than a hardcoded constant -- no
    second real policy exists yet at this sub-slice (Slice G's G0)."""

    def __init__(self, wrapped, *, name: str, version: str) -> None:
        self._wrapped = wrapped
        self.name = name
        self.version = version

    def decide(self, conn, *, epoch, rng, seed_label):
        return self._wrapped.decide(conn, epoch=epoch, rng=rng, seed_label=seed_label)


def test_the_run_record_and_manifest_name_the_actual_selection_policy_used(conn):
    """`runner._record_run_start` took a `selection: SelectionPolicy`
    parameter but never read `.name`/`.version` from it -- both
    `simulation_runs` and the manifest recorded the *Cell* policy's identity
    (`SIMULATION_PROVIDER`/`POLICY_VERSION`) in the selection-policy fields
    too, so nothing at the run level could say which `SelectionPolicy` a run
    actually used, only a per-epoch `simulation_selection_decision` audit
    event could (Slice G's G0 fix)."""
    fake = _NamedWrapperSelection(RandomEligibleSelection(), name="fake_policy", version="7")
    manifest = runner.run(
        conn, runner.RunConfig(scenario_name="test", master_seed=1, epochs=3, population=3),
        selection=fake,
    )

    assert manifest.selection_policy_name == "fake_policy"
    assert manifest.selection_policy_version == "7"

    row = conn.execute(
        "SELECT selection_policy_name, selection_policy_version FROM simulation_runs "
        "WHERE run_id = ?", (manifest.run_id,),
    ).fetchone()
    assert row["selection_policy_name"] == "fake_policy"
    assert row["selection_policy_version"] == "7"


def test_founder_concentration_identifies_the_larger_living_lineage(conn):
    """Ten founders, not two: `max_lineage_population_fraction` (default
    0.20) refuses a second Cell in any lineage while the colony is this
    small -- a single child already exceeds the cap at population=2
    (`2/3 = 0.667`), the same founder-effect tension
    `test_population_grows_through_the_real_reproduction_path` already
    documents. At population=10 a lineage's first child clears it
    (`2/11 ~= 0.18`)."""
    from mitosis import lifecycle, lineage
    from mitosis.models import CellType

    founders = [
        lifecycle.create_cell(
            conn, cell_type=CellType.COMMERCIAL, budget_minor_units=1000,
            book=Book.USD_SIM, idempotency_key=f"founder-{i}",
        )
        for i in range(10)
    ]
    lineage.reproduce(
        conn, parent_cell_id=founders[0].cell_id, budget_minor_units=100,
        idempotency_key="child-of-founder-0",
    )

    dominant_id, share = lineage.founder_concentration(conn)
    assert dominant_id == founders[0].cell_id
    assert share == pytest.approx(2 / 11)


def test_epoch_records_track_founder_concentration_as_a_time_series(conn):
    """Brief: "founder concentration [measured] over time" -- surfaced as a
    real per-epoch field (`lineage.founder_concentration`), comparable
    across policies, not buried in one policy's own free-text reason."""
    manifest = _run(conn, seed=7, epochs=20, population=10)

    for record in manifest.epochs:
        assert 0.0 <= record.founder_concentration <= 1.0
        if record.living_cells > 0:
            assert record.dominant_founder_cell_id is not None
        else:
            assert record.dominant_founder_cell_id is None


def test_founding_a_population_above_the_birth_rate_cap_does_not_raise(conn):
    """§9.2's `max_births_per_epoch` (default 25) does not distinguish a
    founder from a reproduced child (`population._check_birth_rate` reads
    `cells.born_in_epoch` unconditionally) -- founding more than that many
    Cells in what looks like one instant used to raise `BirthRateExceededError`
    uncaught, well under the >= 500 Cells the brief's own acceptance scale
    needs. Fixed by batching founding across kernel epochs, advancing the
    clock between batches -- found empirically via a moderate-scale
    (population=50) benchmark run, not by reading the code.

    Goes through `run()`, not `_found_population` directly: the clock must
    be anchored first (`clock.initialize_if_absent`/`scheduler.
    configure_epochs_if_absent`, both part of `run()`'s own setup) or
    `clock.current_epoch` never advances regardless of how many times
    `clock.advance` is called, and every birth would still land in the same
    "epoch 0" the cap is checked against."""
    manifest = _run(conn, epochs=1, population=30)
    assert manifest.failures == ()
    assert manifest.final_living_cells >= 30


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


def test_random_eligible_selection_reports_every_dimension_as_unmeasured(conn):
    """Brief Slice G's honesty rule: a policy that consults no gates/niches
    says so explicitly via `unmeasured_dimensions` naming every known
    simulator-native dimension, rather than an unexplained empty tuple."""
    import random

    from mitosis.simulation import candidate

    policy = RandomEligibleSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    all_dimensions = set(candidate.SIM_GATE_DIMENSIONS) | set(candidate.SIM_FRONTIER_DIMENSIONS)
    assert set(decision.unmeasured_dimensions) == all_dimensions
    assert decision.measured_dimensions == ()


class _OverrideWrapperSelection:
    """Wraps `RandomEligibleSelection`, overriding only the per-parent
    operator/budget fields on top of its real decision -- proves
    `runner.py`'s reproduction loop actually reads and uses the override
    fields. No real policy populates them yet at this sub-slice (G1); Slice
    G's later policies (MAP-Elites, staged funding) will be the first."""

    name = "override_wrapper"
    version = "1"

    def __init__(self, *, operator: str, budget: int) -> None:
        self._wrapped = RandomEligibleSelection()
        self._operator = operator
        self._budget = budget

    def decide(self, conn, *, epoch, rng, seed_label):
        base = self._wrapped.decide(conn, epoch=epoch, rng=rng, seed_label=seed_label)
        return replace(
            base, policy_name=self.name, policy_version=self.version,
            parent_mutation_operators=tuple(
                (cid, self._operator) for cid in base.chosen_parent_cell_ids
            ),
            parent_child_budgets=tuple(
                (cid, self._budget) for cid in base.chosen_parent_cell_ids
            ),
        )


def test_per_parent_mutation_operator_and_budget_overrides_take_precedence(conn):
    """The per-parent mapping fields exist so a future policy reproducing
    from multiple niches in one epoch can give each its own operator/budget
    (ADR-074 logged deferring exactly this as "scope built for a Slice G
    policy that doesn't exist yet"); this proves `runner.py`'s lookup
    actually prefers them over the shared `mutation_operator`/
    `child_budget_minor_units` fields, not just that the schema accepts them."""
    policy = _OverrideWrapperSelection(operator=mutation.MARKET_CUSTOMER_OPERATOR, budget=250)
    manifest = runner.run(
        conn, runner.RunConfig(scenario_name="test", master_seed=7, epochs=20, population=10),
        selection=policy,
    )
    if manifest.final_living_cells <= 10:
        pytest.skip("no reproduction happened at this seed/epoch count -- not this test's claim")

    rows = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'simulation_mutation'"
    ).fetchall()
    assert rows
    for row in rows:
        metadata = json.loads(row["metadata_json"])
        assert metadata["operator"] == mutation.MARKET_CUSTOMER_OPERATOR

    children = conn.execute("SELECT cell_id FROM cells WHERE parent_cell_id IS NOT NULL").fetchall()
    assert children
    for child in children:
        # The funding *transaction* at birth, not the current cash balance --
        # a child born early has had further epochs to earn its own revenue
        # since, which would make a live-balance check pass or fail for the
        # wrong reason.
        row = conn.execute(
            "SELECT e.amount_minor_units AS amount FROM ledger_entries e "
            "JOIN ledger_transactions t ON t.transaction_id = e.transaction_id "
            "WHERE t.transaction_type = 'cell_reproduction_funding' "
            "AND e.account_id = ? AND e.amount_minor_units > 0",
            (f"cell:{child['cell_id']}:cash",),
        ).fetchone()
        assert row is not None
        assert row["amount"] == 250


def test_single_leaderboard_selection_chooses_the_highest_revenue_eligible_cell(conn):
    """Brief Slice G policy #2: an explicit single-scalar leaderboard, built
    only as a Phase 3 comparator -- SPEC.md §10.2/§13.2 forbid this shape
    for the production kernel."""
    import random

    from mitosis import experiments as experiments_module
    from mitosis import lifecycle
    from mitosis import revenue as revenue_module
    from mitosis.models import CellType

    low = lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=1000,
        book=Book.USD_SIM, idempotency_key="low",
    )
    high = lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=1000,
        book=Book.USD_SIM, idempotency_key="high",
    )
    for cell, amount in ((low, 50), (high, 900)):
        experiment = experiments_module.start(conn, cell_id=cell.cell_id, hypothesis="h")
        revenue_module.record_revenue(
            conn, cell_id=cell.cell_id, amount_minor_units=amount, source="test sale",
            book=Book.USD_SIM, experiment_id=experiment.experiment_id,
            idempotency_key=f"sale:{cell.cell_id}",
        )
        experiments_module.conclude(
            conn, experiment_id=experiment.experiment_id, concluded_by="test", note="concluded",
        )

    policy = SingleLeaderboardSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert decision.chosen_parent_cell_ids == (high.cell_id,)
    assert decision.gate_results == ()
    assert decision.measured_dimensions == ("realized_net_revenue",)


def test_single_leaderboard_selection_ranks_an_unmeasured_cell_last(conn):
    """A cell with a concluded, zero-revenue experiment (a *measured* zero)
    must still outrank a cell with no concluded experiment at all
    (unmeasured) -- unmeasured is never treated as a worse number, it is
    excluded from the comparison entirely and sorted to the bottom."""
    import random

    from mitosis import experiments as experiments_module
    from mitosis import lifecycle
    from mitosis.models import CellType

    # `unmeasured` is created *first* deliberately: its earlier
    # `created_at_utc` would win a same-value tie-break if "unmeasured
    # ranks last" were ever silently dropped, making that specific bug
    # unambiguous rather than depending on which cell happened to sort
    # first by generated id.
    unmeasured = lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=1000,
        book=Book.USD_SIM, idempotency_key="unmeasured",
    )
    proven_zero = lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=1000,
        book=Book.USD_SIM, idempotency_key="proven-zero",
    )
    experiment = experiments_module.start(conn, cell_id=proven_zero.cell_id, hypothesis="h")
    experiments_module.conclude(
        conn, experiment_id=experiment.experiment_id, concluded_by="test", note="no sale",
    )

    policy = SingleLeaderboardSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert decision.chosen_parent_cell_ids == (proven_zero.cell_id,)
    assert unmeasured.cell_id in decision.eligible_cell_ids


def _cell_with_experiments(conn, *, key, genome_content, outcomes):
    """`outcomes` is a list of revenue amounts (or `None` for no sale), one
    concluded experiment per entry, all sharing `genome_content` -- so
    `structural_novelty` ties or abstains identically across every cell
    built with the same content, leaving `realized_net_revenue`/
    `experiment_success_rate` as the only axes that can discriminate."""
    from mitosis import experiments as experiments_module
    from mitosis import lifecycle
    from mitosis import revenue as revenue_module
    from mitosis.models import CellType

    cell = lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=1000,
        book=Book.USD_SIM, idempotency_key=key, genome_content=genome_content,
    )
    for i, amount in enumerate(outcomes):
        experiment = experiments_module.start(conn, cell_id=cell.cell_id, hypothesis="h")
        if amount is not None:
            revenue_module.record_revenue(
                conn, cell_id=cell.cell_id, amount_minor_units=amount, source="test sale",
                book=Book.USD_SIM, experiment_id=experiment.experiment_id,
                idempotency_key=f"sale:{key}:{i}",
            )
        experiments_module.conclude(
            conn, experiment_id=experiment.experiment_id, concluded_by="test", note="concluded",
        )
    return cell


def test_pareto_selection_reproduces_the_whole_front_not_one_winner(conn):
    """A genuine trade-off (higher revenue but a lower success rate) puts
    two cells on the front together -- neither dominates the other -- while
    a third, strictly worse than one of them on every measured axis, is
    excluded. Reproducing *both* front members is what distinguishes this
    from `SingleLeaderboardSelection`."""
    import random

    shared_genome = {"market": {"segment": "shared"}}
    high_revenue_low_rate = _cell_with_experiments(
        conn, key="a", genome_content=shared_genome, outcomes=[1000, None],
    )
    low_revenue_high_rate = _cell_with_experiments(
        conn, key="b", genome_content=shared_genome, outcomes=[200],
    )
    dominated = _cell_with_experiments(
        conn, key="c", genome_content=shared_genome, outcomes=[50],
    )

    policy = ParetoSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert set(decision.pareto_front_cell_ids) == {
        high_revenue_low_rate.cell_id, low_revenue_high_rate.cell_id,
    }
    assert dominated.cell_id not in decision.pareto_front_cell_ids
    assert set(decision.chosen_parent_cell_ids) == set(decision.pareto_front_cell_ids)


def test_pareto_selection_never_builds_a_candidate_for_a_quarantined_cell(conn):
    """A quarantined Cell is excluded at the *eligibility* stage
    (`_eligible_parents` filters to `CellStatus.ALIVE`, shared by every
    policy) before `candidate.cell_candidate` -- and its `not_quarantined`
    gate -- ever sees it; `test_simulation_candidate.py`'s own
    `test_not_quarantined_gate_passes_alive_and_rejects_quarantined` proves
    the gate function itself rejects one when actually given one. This test
    states the accurate, narrower fact for this policy's own pipeline:
    a quarantined Cell is not even eligible, so it appears in neither the
    front nor `gate_results` at all."""
    import random

    from mitosis import lifecycle

    winner = _cell_with_experiments(
        conn, key="winner", genome_content={"market": {"segment": "a"}}, outcomes=[900],
    )
    quarantined = _cell_with_experiments(
        conn, key="quarantined", genome_content={"market": {"segment": "b"}}, outcomes=[900],
    )
    lifecycle.quarantine(conn, quarantined.cell_id, reason="test")

    policy = ParetoSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert quarantined.cell_id not in decision.eligible_cell_ids
    assert quarantined.cell_id not in decision.pareto_front_cell_ids
    assert not any(g.cell_id == quarantined.cell_id for g in decision.gate_results)
    assert winner.cell_id in decision.pareto_front_cell_ids


def test_pareto_selection_gives_each_chosen_parent_its_own_operator(conn):
    import random

    shared_genome = {"market": {"segment": "shared"}}
    high_revenue_low_rate = _cell_with_experiments(
        conn, key="a", genome_content=shared_genome, outcomes=[1000, None],
    )
    low_revenue_high_rate = _cell_with_experiments(
        conn, key="b", genome_content=shared_genome, outcomes=[200],
    )

    policy = ParetoSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    overrides = dict(decision.parent_mutation_operators)
    assert high_revenue_low_rate.cell_id in overrides
    assert low_revenue_high_rate.cell_id in overrides
    assert overrides[high_revenue_low_rate.cell_id] in mutation.OPERATORS
    assert overrides[low_revenue_high_rate.cell_id] in mutation.OPERATORS


def test_cli_simulate_accepts_the_pareto_selection_policy(tmp_path):
    db_path = tmp_path / "sim.db"
    output_path = tmp_path / "manifest.json"
    cli.main(["--db", str(db_path), "init"])

    exit_code = cli.main([
        "--db", str(db_path), "simulate",
        "--seed", "3", "--epochs", "5", "--population", "3",
        "--selection-policy", "pareto", "--output", str(output_path),
    ])

    assert exit_code in (0, None)
    written = json.loads(output_path.read_text())
    assert written["selection_policy_name"] == "pareto"
    assert all(written["conservation_ok"].values())


def test_map_elites_selection_funds_one_elite_per_occupied_niche(conn):
    """`novelty.archive()`'s own niche computation drives this policy
    directly -- two genomes forced into different niches (one shares an
    earlier market and lands "adjacent", one names a fresh market and lands
    "radical") each fund their own elite; a founder genome with nothing
    earlier to compare against is unbinned (§12.1) and funds nothing.
    `niche_elite()`'s own tie-break logic is unit-tested in
    `test_simulation_candidate.py`; this proves the *policy* correctly uses
    the archive and assembles the decision record from it."""
    import random

    from mitosis.simulation.selection_policy import MapElitesSelection

    # `founder` and `adjacent` cannot share identical genome_content -- under
    # ADR-018's content addressing that would be the *same* genome_hash (one
    # archive record, not two). `adjacent` shares `founder`'s market but adds
    # one more novelty field (`product`), which is exactly one field
    # difference from its nearest earlier genome -- "adjacent" by
    # `novelty._novelty_distance`'s own "nearest == 1" branch.
    founder = _cell_with_experiments(
        conn, key="founder", genome_content={"market": {"segment": "shared"}}, outcomes=[500],
    )
    adjacent = _cell_with_experiments(
        conn, key="adjacent",
        genome_content={"market": {"segment": "shared"}, "product": {"name": "variant"}},
        outcomes=[500],
    )
    radical = _cell_with_experiments(
        conn, key="radical", genome_content={"market": {"segment": "different"}}, outcomes=[500],
    )

    policy = MapElitesSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert len(decision.niches) == 2
    elites = {n.elite_cell_id for n in decision.niches}
    assert elites == {adjacent.cell_id, radical.cell_id}
    assert set(decision.chosen_parent_cell_ids) == elites
    assert founder.cell_id not in decision.chosen_parent_cell_ids
    assert all(n.funded_this_epoch for n in decision.niches)
    assert all(n.thompson_sample is None for n in decision.niches)


def test_map_elites_selection_records_the_real_posterior_even_though_unused(conn, monkeypatch):
    """`decide()` must carry through whatever `posteriors.posteriors()` reports
    for a niche's own coordinate, keyed correctly, rather than silently
    falling back to the uninformative prior. A *zero-trial* real posterior is
    numerically identical to the hardcoded fallback (alpha=beta=1.0 either
    way, per `_posterior`'s own formula) -- so asserting only that shape
    cannot tell a real lookup from a broken one that always misses. This
    injects a posterior with real, non-prior trials/conversions and asserts
    those exact values survive into the decision record."""
    import random

    from mitosis import novelty
    from mitosis import posteriors as posteriors_module
    from mitosis.simulation.selection_policy import MapElitesSelection

    _cell_with_experiments(
        conn, key="founder", genome_content={"market": {"segment": "shared"}}, outcomes=[500],
    )
    _cell_with_experiments(
        conn, key="adjacent",
        genome_content={"market": {"segment": "shared"}, "product": {"name": "variant"}},
        outcomes=[500],
    )

    real_niche = novelty.archive(conn).niches[0]
    fake_posterior = posteriors_module.StageConversionPosterior(
        coordinate=real_niche.coordinate, trials=5, conversions=2,
        alpha=3.0, beta=4.0, posterior_mean=3.0 / 7.0, reason="fake posterior for this test",
    )
    monkeypatch.setattr(
        posteriors_module, "posteriors",
        lambda conn: posteriors_module.Posteriors(
            niches=(fake_posterior,), unbinned_trials=0, unbinned_conversions=0,
        ),
    )

    policy = MapElitesSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert len(decision.niches) == 1
    niche = decision.niches[0]
    assert niche.posterior_trials == 5
    assert niche.posterior_conversions == 2
    assert niche.posterior_alpha == pytest.approx(3.0)
    assert niche.posterior_beta == pytest.approx(4.0)
    assert niche.posterior_mean == pytest.approx(3.0 / 7.0)


def test_map_elites_selection_runs_cleanly_across_a_live_multi_epoch_run(conn):
    from mitosis.simulation.selection_policy import MapElitesSelection

    manifest = runner.run(
        conn, runner.RunConfig(scenario_name="test", master_seed=7, epochs=20, population=10),
        selection=MapElitesSelection(),
    )
    assert manifest.failures == ()
    assert all(manifest.conservation_ok.values())


def test_cli_simulate_accepts_the_map_elites_selection_policy(tmp_path):
    db_path = tmp_path / "sim.db"
    output_path = tmp_path / "manifest.json"
    cli.main(["--db", str(db_path), "init"])

    exit_code = cli.main([
        "--db", str(db_path), "simulate",
        "--seed", "3", "--epochs", "5", "--population", "3",
        "--selection-policy", "map_elites", "--output", str(output_path),
    ])

    assert exit_code in (0, None)
    written = json.loads(output_path.read_text())
    assert written["selection_policy_name"] == "map_elites"
    assert all(written["conservation_ok"].values())


class _AlwaysRejectsValidation:
    """A minimal `MarketEnvironment` stub that never clears a probe --
    deterministic, unlike the real market families, so a test can assert
    exclusion without fighting either family's own random/tiered mechanics."""

    name = "always_rejects_validation"
    version = "1"

    def reset(self, *, seed: int) -> None:
        pass

    def observe(self, *, cell_id: str, epoch: int):
        raise NotImplementedError("not used by validation_probe")

    def evaluate(self, *, experiment: ExperimentAction, epoch: int) -> Outcome:
        return Outcome(purchased=False, revenue_minor_units=0, note="stub always rejects")

    def advance(self, *, epoch: int) -> tuple:
        return ()


def test_staged_funding_selection_never_elects_an_elite_whose_genome_failed_reproducibility(conn):
    """Three independent Cells try the same genome and none ever convert to
    revenue -- `candidate._reproducibility` REJECTs that genome
    (`_MIN_INDEPENDENT_TRIES = 3`). `StagedFundingSelection` composes this
    gate (`ParetoSelection`'s own) before `niche_elite` ever runs, so this
    niche's only occupants are all excluded from the candidate pool and the
    niche funds nothing -- proving gate composition actually restricts who
    can become an elite, not merely that gates run and get recorded."""
    import random

    _cell_with_experiments(
        conn, key="founder", genome_content={"market": {"segment": "shared"}}, outcomes=[1],
    )
    never_converts_genome = {"market": {"segment": "shared"}, "product": {"name": "tried"}}
    for i in range(3):
        _cell_with_experiments(
            conn, key=f"tried-{i}", genome_content=never_converts_genome, outcomes=[None],
        )

    policy = selection_policy.StagedFundingSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert len(decision.niches) == 1
    niche = decision.niches[0]
    assert niche.elite_cell_id is None
    assert not niche.funded_this_epoch
    assert decision.chosen_parent_cell_ids == ()
    assert any(
        g.dimension == "reproducibility" and g.outcome.value == "rejected"
        for g in decision.gate_results
    )


def test_staged_funding_selection_excludes_an_elite_that_fails_the_validation_probe(conn):
    """The headline new mechanism: an elite that would otherwise be funded
    (alive, ungated, the sole occupant of its niche) is excluded once a
    validation environment rejects it -- SPEC.md §8.1's validation role,
    'influences capital allocation,' given real teeth. `elite_cell_id` is
    still recorded on the `NicheStanding` (this niche's real elite *is* this
    Cell) but `funded_this_epoch` is `False` and it never reaches
    `chosen_parent_cell_ids`."""
    import random

    _cell_with_experiments(
        conn, key="founder", genome_content={"market": {"segment": "shared"}}, outcomes=[1],
    )
    elite = _cell_with_experiments(
        conn, key="elite",
        genome_content={"market": {"segment": "shared"}, "product": {"name": "variant"}},
        outcomes=[500],
    )

    policy = selection_policy.StagedFundingSelection(validation=_AlwaysRejectsValidation())
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert len(decision.niches) == 1
    niche = decision.niches[0]
    assert niche.elite_cell_id == elite.cell_id
    assert not niche.funded_this_epoch
    assert elite.cell_id not in decision.chosen_parent_cell_ids
    assert any(
        g.cell_id == elite.cell_id and g.dimension == "validation_probe"
        and g.outcome.value == "rejected"
        for g in decision.gate_results
    )


def test_staged_funding_selection_reports_validation_probe_as_unevaluable_without_an_environment(conn):
    """`validation=None` (the default) is an honestly weaker policy, not a
    crash: every elite's `validation_probe` gate is `UNEVALUABLE` -- 'nothing
    to judge' -- and `UNEVALUABLE` never excludes, matching
    `_reproducibility`'s own posture below its evidence threshold."""
    import random

    _cell_with_experiments(
        conn, key="founder", genome_content={"market": {"segment": "shared"}}, outcomes=[1],
    )
    elite = _cell_with_experiments(
        conn, key="elite",
        genome_content={"market": {"segment": "shared"}, "product": {"name": "variant"}},
        outcomes=[500],
    )

    policy = selection_policy.StagedFundingSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert elite.cell_id in decision.chosen_parent_cell_ids
    assert any(
        g.cell_id == elite.cell_id and g.dimension == "validation_probe"
        and g.outcome.value == "unevaluable"
        for g in decision.gate_results
    )


def test_staged_funding_selection_funds_at_most_the_top_k_niches(conn, monkeypatch):
    """The archive has at most 3 niches today (only `structural_novelty`
    ever measures for a simulated genome -- see `candidate.py`'s own module
    docstring), so `_STAGED_FUNDING_TOP_K = 3` cannot yet exclude anything
    by itself. This monkeypatches the cap down to 1 so the ranking-and-cap
    logic itself is still verified: exactly one of two fundable niches gets
    funded, and it is the one with the higher Thompson sample -- proving the
    cap and the ranking it orders by, not just that funding happens at all."""
    import random

    monkeypatch.setattr(selection_policy, "_STAGED_FUNDING_TOP_K", 1)

    _cell_with_experiments(
        conn, key="founder", genome_content={"market": {"segment": "shared"}}, outcomes=[1],
    )
    _cell_with_experiments(
        conn, key="adjacent",
        genome_content={"market": {"segment": "shared"}, "product": {"name": "variant"}},
        outcomes=[500],
    )
    _cell_with_experiments(
        conn, key="radical", genome_content={"market": {"segment": "different"}}, outcomes=[500],
    )

    policy = selection_policy.StagedFundingSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert len(decision.niches) == 2
    funded = [n for n in decision.niches if n.funded_this_epoch]
    assert len(funded) == 1
    assert len(decision.chosen_parent_cell_ids) == 1
    unfunded = [n for n in decision.niches if not n.funded_this_epoch]
    assert len(unfunded) == 1
    assert funded[0].thompson_sample >= unfunded[0].thompson_sample


def test_staged_funding_selection_scales_child_budget_with_posterior_mean(conn):
    """A niche with zero rung-7 trials gets the uninformative prior
    (mean=0.5); `_staged_child_budget`'s own formula
    (`base + round(base * scale * mean)`) at `scale=1.0` says that niche's
    funded elite should get exactly 1.5x the base child budget -- checked
    against the real formula's output, not a re-derived number, so this
    fails if either the formula or the wiring from posterior to budget
    drifts."""
    import random

    from mitosis.simulation.selection_policy import _CHILD_BUDGET_MINOR_UNITS, _staged_child_budget

    _cell_with_experiments(
        conn, key="founder", genome_content={"market": {"segment": "shared"}}, outcomes=[1],
    )
    elite = _cell_with_experiments(
        conn, key="elite",
        genome_content={"market": {"segment": "shared"}, "product": {"name": "variant"}},
        outcomes=[500],
    )

    policy = selection_policy.StagedFundingSelection()
    decision = policy.decide(conn, epoch=0, rng=random.Random(0), seed_label="seed=0")

    assert elite.cell_id in decision.chosen_parent_cell_ids
    budgets = dict(decision.parent_child_budgets)
    assert budgets[elite.cell_id] == _staged_child_budget(0.5)
    assert budgets[elite.cell_id] > _CHILD_BUDGET_MINOR_UNITS


def test_staged_funding_selection_runs_cleanly_across_a_live_multi_epoch_run(conn):
    manifest = runner.run(
        conn, runner.RunConfig(scenario_name="test", master_seed=11, epochs=20, population=10),
        selection=selection_policy.StagedFundingSelection(validation=RuleBasedMarket()),
    )
    assert manifest.failures == ()
    assert all(manifest.conservation_ok.values())


def test_cli_simulate_accepts_the_staged_funding_selection_policy_and_defaults_validation(tmp_path):
    """No `--validation-environment` given: `cmd_simulate` defaults it to the
    *other* family from `--environment` (SPEC.md §8.3's two independently
    shaped families) rather than leaving `validation=None`."""
    db_path = tmp_path / "sim.db"
    output_path = tmp_path / "manifest.json"
    cli.main(["--db", str(db_path), "init"])

    exit_code = cli.main([
        "--db", str(db_path), "simulate",
        "--seed", "3", "--epochs", "5", "--population", "3",
        "--environment", "utility_maximizing_market",
        "--selection-policy", "staged_funding", "--output", str(output_path),
    ])

    assert exit_code in (0, None)
    written = json.loads(output_path.read_text())
    assert written["selection_policy_name"] == "staged_funding"
    assert all(written["conservation_ok"].values())


def test_build_selection_policy_selects_the_named_policy_and_rejects_unknown_names():
    assert isinstance(
        selection_policy.build_selection_policy("random_eligible"), RandomEligibleSelection,
    )
    assert isinstance(
        selection_policy.build_selection_policy("single_leaderboard"), SingleLeaderboardSelection,
    )
    assert isinstance(
        selection_policy.build_selection_policy("pareto"), selection_policy.ParetoSelection,
    )
    assert isinstance(
        selection_policy.build_selection_policy("map_elites"), selection_policy.MapElitesSelection,
    )
    staged = selection_policy.build_selection_policy("staged_funding", validation=RuleBasedMarket())
    assert isinstance(staged, selection_policy.StagedFundingSelection)
    assert isinstance(staged._validation, RuleBasedMarket)
    with pytest.raises(selection_policy.UnknownSelectionPolicyError):
        selection_policy.build_selection_policy("not_a_real_policy")


def test_cli_simulate_accepts_the_single_leaderboard_selection_policy(tmp_path):
    db_path = tmp_path / "sim.db"
    output_path = tmp_path / "manifest.json"
    cli.main(["--db", str(db_path), "init"])

    exit_code = cli.main([
        "--db", str(db_path), "simulate",
        "--seed", "3", "--epochs", "5", "--population", "3",
        "--selection-policy", "single_leaderboard", "--output", str(output_path),
    ])

    assert exit_code in (0, None)
    written = json.loads(output_path.read_text())
    assert written["selection_policy_name"] == "single_leaderboard"
    assert all(written["conservation_ok"].values())


def test_kill_fraction_drill_kills_the_expected_share_and_conservation_holds(conn):
    drill = chaos.KillFractionDrill(fraction=0.3, at_epoch=5)
    manifest = runner.run(
        conn, runner.RunConfig(scenario_name="t", master_seed=1, epochs=15, population=10),
        epoch_hook=drill,
    )

    assert len(drill.reports) == 1
    assert drill.reports[0].epoch == 5
    killed_count = int(drill.reports[0].detail.split("killed ")[1].split("/")[0])
    assert killed_count > 0
    coroner_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM coroner_reports WHERE cause_of_death = 'chaos_drill_kill'"
    ).fetchone()
    assert coroner_rows["n"] == killed_count
    assert manifest.failures == ()
    invariants = chaos.verify_post_drill_invariants(conn)
    assert all(invariants.values())
    # Population recovery or explicit extinction (brief) -- either is a valid
    # post-drill state; a negative or nonsensical count is not.
    assert manifest.final_living_cells >= 0


def test_kill_fraction_drill_replays_deterministically_from_the_same_seed(conn):
    conn_b = db.connect_and_migrate()
    try:
        first = runner.run(
            conn, runner.RunConfig(scenario_name="t", master_seed=3, epochs=12, population=8),
            epoch_hook=chaos.KillFractionDrill(fraction=0.3, at_epoch=4),
        )
        second = runner.run(
            conn_b, runner.RunConfig(scenario_name="t", master_seed=3, epochs=12, population=8),
            epoch_hook=chaos.KillFractionDrill(fraction=0.3, at_epoch=4),
        )
        first_dict = asdict(first)
        second_dict = asdict(second)
        del first_dict["run_id"]
        del second_dict["run_id"]
        assert first_dict == second_dict
    finally:
        conn_b.close()


def test_withdraw_capability_drill_disables_the_flag_and_the_run_survives(conn):
    drill = chaos.WithdrawCapabilityDrill(at_epoch=5)
    manifest = runner.run(
        conn, runner.RunConfig(scenario_name="t", master_seed=1, epochs=10, population=5),
        epoch_hook=drill,
    )

    from mitosis import tools

    assert len(drill.reports) == 1
    assert tools.autonomy_enabled(conn, "auto_promotion") is False
    assert manifest.failures == ()
    assert all(chaos.verify_post_drill_invariants(conn).values())


def test_crashing_environment_records_one_failure_and_the_experiment_recovers_later(conn):
    """"Crash at ... boundaries" reframed to the experiment lifecycle's
    execute phase (see `chaos.py`'s module docstring). Recovery means the
    interrupted experiment is retried and actually concludes on a later
    epoch -- not merely that the run as a whole didn't crash."""
    crashing_env = chaos.CrashingEnvironment(environment.UtilityMaximizingMarket(), at_epoch=5)
    manifest = runner.run(
        conn, runner.RunConfig(scenario_name="t", master_seed=1, epochs=10, population=5),
        suite=environment.EnvironmentSuite.training_only(crashing_env),
    )

    assert len(manifest.failures) == 1
    assert "epoch 5" in manifest.failures[0]
    assert len(crashing_env.reports) == 1
    victim_cell_id = crashing_env.reports[0].detail.rsplit(" ", 1)[-1]

    from mitosis import experiments
    assert experiments.current_for(conn, victim_cell_id) is None
    rows = conn.execute(
        "SELECT status FROM experiments WHERE cell_id = ?", (victim_cell_id,)
    ).fetchall()
    assert rows
    assert all(row["status"] == "concluded" for row in rows)
    assert all(chaos.verify_post_drill_invariants(conn).values())


def test_crashing_environment_replays_deterministically_from_the_same_seed(conn):
    conn_b = db.connect_and_migrate()
    try:
        config = runner.RunConfig(scenario_name="t", master_seed=5, epochs=10, population=5)
        first = runner.run(
            conn, config,
            suite=environment.EnvironmentSuite.training_only(
                chaos.CrashingEnvironment(environment.UtilityMaximizingMarket(), at_epoch=4)
            ),
        )
        second = runner.run(
            conn_b, config,
            suite=environment.EnvironmentSuite.training_only(
                chaos.CrashingEnvironment(environment.UtilityMaximizingMarket(), at_epoch=4)
            ),
        )
        first_dict = asdict(first)
        second_dict = asdict(second)
        del first_dict["run_id"]
        del second_dict["run_id"]
        assert first_dict == second_dict
    finally:
        conn_b.close()


def test_a_regime_shift_measurably_invalidates_a_previously_viable_price(conn):
    """Brief drill: "a regime shift that invalidates the currently dominant
    strategy." Uses F2's own scheduled shift (ADR-073) at full-economy scale
    rather than the isolated environment-level check that ADR-073's own
    tests already cover -- founders span prices 400/450/500 (`runner.
    _founder_genome`); every one of those prices sells routinely pre-shift
    and is severely restricted or impossible post-shift (max post-shift
    willingness-to-pay is 450)."""
    manifest = runner.run(
        conn, runner.RunConfig(scenario_name="t", master_seed=1, epochs=20, population=5),
    )
    assert manifest.failures == ()

    pre_shift_sales = sum(record.sales for record in manifest.epochs[:10])
    post_shift_sales = sum(record.sales for record in manifest.epochs[10:])
    assert pre_shift_sales > 0
    assert post_shift_sales < pre_shift_sales / 2
    assert all(chaos.verify_post_drill_invariants(conn).values())


def test_duplicate_funding_call_is_a_safe_noop(conn):
    """"Duplicate event delivery" at the simulator's own layer: the raw
    kernel event queue's idempotency is already Charter C6's job (a
    provider-agnostic stateful machine); this proves the simulator's own
    idempotency-keyed operation (`_fund_scheduler_eligibility`) is safe under
    redelivery."""
    from mitosis import lifecycle
    from mitosis.models import CellType

    cell = lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=10,
        book=Book.USD_SIM, idempotency_key="dup-cell",
    )
    runner._fund_scheduler_eligibility(
        conn, cell_id=cell.cell_id, key="dup-key", amount_minor_units=500,
    )
    once = ledger.get_balance(conn, f"cell:{cell.cell_id}:cash", Book.USD_REAL)
    runner._fund_scheduler_eligibility(
        conn, cell_id=cell.cell_id, key="dup-key", amount_minor_units=500,
    )
    twice = ledger.get_balance(conn, f"cell:{cell.cell_id}:cash", Book.USD_REAL)

    assert once == 500
    assert twice == once


def test_out_of_order_funding_for_a_not_yet_born_cell_is_inert_and_unreachable(conn):
    """"Out-of-order event delivery": a funding operation for a child can,
    in principle, be attempted before that child's own birth is visible.
    `ledger` accounts are plain strings, not a foreign key into `cells` --
    so this neither corrupts anything nor gets rejected; it parks a balance
    `scheduler.eligible_cells` (which only ever iterates real `cells` rows)
    can never reach until a Cell with that same id actually exists, at which
    point the very same already-posted entries become that Cell's real
    balance by construction -- no special-case recovery code needed."""
    from mitosis import scheduler

    orphan_id = "not-born-yet"
    runner._fund_scheduler_eligibility(
        conn, cell_id=orphan_id, key="early-fund", amount_minor_units=500,
    )

    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert all(cell.cell_id != orphan_id for cell in scheduler.eligible_cells(conn, epoch_number=0))


def test_verify_post_drill_invariants_reports_true_on_a_healthy_run(conn):
    manifest = _run(conn)
    assert manifest.failures == ()
    assert chaos.verify_post_drill_invariants(conn) == {
        "USD_REAL": True, "USD_SIM": True, "RESOURCE": True, "ledger_chain_valid": True,
    }


def test_manifest_carries_a_diversity_time_series_bounded_by_living_cells(conn):
    """Brief: "population/diversity time series." Diversity is counted as
    distinct `genome_hash` values among living Cells -- a genome hash *is* a
    Cell's full strategy (ADR-018's content addressing), so this is a
    structural bound true regardless of which operators fired: you cannot
    have more distinct strategies than living Cells, and at least one living
    Cell means at least one distinct genome."""
    manifest = _run(conn, seed=7, epochs=20, population=10)
    assert manifest.epochs
    for record in manifest.epochs:
        assert 1 <= record.distinct_genomes <= record.living_cells
    # Not merely "distinct_genomes == living_cells always" (which a
    # non-deduplicating count would also satisfy): at this seed/scale some
    # epochs genuinely have fewer distinct genomes than living Cells (a
    # no-op mutation or a clamped continuous operator collapsing to the
    # parent's own hash, ADR-018) -- confirmed empirically, not assumed.
    assert any(record.distinct_genomes < record.living_cells for record in manifest.epochs)


def test_manifest_carries_regime_shift_events_only_at_the_scheduled_epoch(conn):
    """Brief: "regime-shift recovery." Made visible directly on the
    retained manifest (not only via the `simulation_environment_event`
    audit trail, ADR-073/074) -- a reader can see which epoch carried a
    shift and read the following epochs' own `living_cells`/`sales`/
    `distinct_genomes` to see recovery, rather than the manifest declaring a
    computed verdict on the colony's behalf."""
    manifest = _run(conn, seed=1, epochs=15, population=3)
    shift_epochs = [record.epoch for record in manifest.epochs if record.environment_events]
    assert shift_epochs == [10]
    assert "price_compression" in manifest.epochs[10].environment_events[0]


def test_config_hash_is_stable_for_the_same_configuration_and_differs_for_a_different_one():
    same_a = runner._config_hash(
        runner.RunConfig(scenario_name="x", master_seed=1, epochs=6, population=3)
    )
    same_b = runner._config_hash(
        runner.RunConfig(scenario_name="x", master_seed=1, epochs=6, population=3)
    )
    different_seed = runner._config_hash(
        runner.RunConfig(scenario_name="x", master_seed=2, epochs=6, population=3)
    )
    different_population = runner._config_hash(
        runner.RunConfig(scenario_name="x", master_seed=1, epochs=6, population=4)
    )
    different_output_path_only = runner._config_hash(
        runner.RunConfig(
            scenario_name="x", master_seed=1, epochs=6, population=3, output_path="/tmp/m.json",
        )
    )

    assert same_a == same_b
    assert same_a != different_seed
    assert same_a != different_population
    # output_path is a write destination, not configuration -- it must not
    # change the hash, or two runs of the identical scenario writing to
    # different paths would wrongly look like different configurations.
    assert same_a == different_output_path_only


def test_phase_2_ci_scale_acceptance_scenario(conn):
    """The brief's own Phase 2 acceptance checklist, in one place, at a
    scale CI can run in seconds rather than the >=500 Cell/>=10,000 epoch
    scale the same checklist also asks for (brief: "if runtime makes
    500x10,000 unsuitable for ordinary CI, keep a small deterministic CI
    scenario, and a separately documented benchmark command whose result
    artifact is retained" -- `docs/DECISIONS.md`'s Slice F ADR-076 documents
    that larger, separately-run benchmark; this is the small scenario).

    Every bullet below is the brief's own acceptance-test wording, each with
    the specific assertion that stands in for it -- not a paraphrase with no
    checkable claim behind it."""
    drill = chaos.KillFractionDrill(fraction=0.3, at_epoch=8)
    manifest = runner.run(
        conn,
        runner.RunConfig(scenario_name="acceptance", master_seed=1, epochs=30, population=15),
        epoch_hook=drill,
    )

    # "zero real API spend and zero USD_REAL movement"
    assert manifest.usd_real_spend_unchanged

    # "deterministic reruns from the same version and seed"
    conn_b = db.connect_and_migrate()
    try:
        replay = runner.run(
            conn_b,
            runner.RunConfig(scenario_name="acceptance", master_seed=1, epochs=30, population=15),
            epoch_hook=chaos.KillFractionDrill(fraction=0.3, at_epoch=8),
        )
        first_dict = asdict(manifest)
        second_dict = asdict(replay)
        del first_dict["run_id"]
        del second_dict["run_id"]
        assert first_dict == second_dict
    finally:
        conn_b.close()

    # "stable carrying capacity" -- never exceeded the configured colony limit
    from mitosis import population as population_module

    limits = population_module.get_limits(conn)
    assert all(record.living_cells <= limits.max_living_cells for record in manifest.epochs)

    # "no book-level conservation failure"
    assert all(chaos.verify_post_drill_invariants(conn).values())

    # "no duplicate economic effects under event redelivery" -- the
    # simulator's own idempotency-keyed operations are covered directly by
    # `test_duplicate_funding_call_is_a_safe_noop`; referenced, not re-proven
    # here, to keep this scenario about the acceptance checklist as a whole.

    # "recovery from the defined chaos drills"
    assert len(drill.reports) == 1
    assert manifest.failures == ()
    assert manifest.final_living_cells > 0

    # "more than one occupied behavioural niche" -- distinct genome_hash
    # values among living Cells are distinct strategies (ADR-018's content
    # addressing; see `manifest.py`'s own diversity-time-series docstring)
    assert manifest.epochs[-1].distinct_genomes > 1

    # brief: "regime-shift recovery" as part of the same acceptance run
    assert any(record.environment_events for record in manifest.epochs)


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
