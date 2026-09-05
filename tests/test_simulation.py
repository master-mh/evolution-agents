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
from mitosis.simulation import chaos, environment, mutation, runner
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
