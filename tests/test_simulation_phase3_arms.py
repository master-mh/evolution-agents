"""The settings §28 Phase 3 compares that are not a selection policy, and the
metrics a comparison of them can honestly read (Slice H; ADR-094).

Three things are defended. A *static market* is the shifting market with the
shift removed and nothing else — same draws, same seed — so a static arm and
a shifting arm pair by seed. A *lineage cap* named by an arm reaches the
kernel's birth licence, and a run cannot record a cap it was never held to.
And the *trait and rate metrics* are what they say: headcount cannot move
them, and a window with nothing in it is refused rather than read as zero.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from mitosis import db, models, population
from mitosis.simulation import batch, mutation, paired, runner
from mitosis.simulation.environment import (
    STATIC,
    EnvironmentSuite,
    ExperimentAction,
    RuleBasedMarket,
    UtilityMaximizingMarket,
    build_environment,
)
from mitosis.simulation.selection_policy import SelectionDecision, SingleLeaderboardSelection


class _NoReproduction:
    """Chooses no parent, so a run keeps exactly its founders."""

    name = "quiet"
    version = "1"

    def decide(self, conn, *, epoch, rng, seed_label):
        return SelectionDecision(
            policy_name=self.name, policy_version=self.version, epoch=epoch,
            rng_seed_label=seed_label, eligible_cell_ids=(), chosen_parent_cell_ids=(),
            mutation_operator=mutation.NO_OP_OPERATOR, child_budget_minor_units=0,
            reason="test policy: never reproduces",
        )


def _run(*, environment=None, selection=None, lineage_cap=None, seed=7, epochs=12, population_size=4,
         conn=None):
    own = conn is None
    conn = conn or db.connect_and_migrate()
    try:
        return runner.run(
            conn,
            runner.RunConfig(
                scenario_name="phase3", master_seed=seed, epochs=epochs,
                population=population_size, lineage_cap=lineage_cap,
            ),
            suite=EnvironmentSuite.training_only(environment or UtilityMaximizingMarket()),
            selection=selection or SingleLeaderboardSelection(),
        )
    finally:
        if own:
            conn.close()


# --- the static market -------------------------------------------------------


@pytest.mark.parametrize("family", [UtilityMaximizingMarket, RuleBasedMarket])
def test_a_static_market_is_the_pre_shift_market_forever_and_announces_nothing(family):
    """§28's "static vs shifting markets". A static market must be the shifting
    market *minus the shift*: identical outcomes before the shift epoch (so the
    two arms pair by seed — every draw is keyed by `name:version`, which the
    setting must not change), the pre-shift rule after it, and no regime-shift
    event at all. A static arm that quietly used different draws would turn a
    paired comparison into an unpaired one under the same name."""
    shifting, static = family(), family(regime_shift_epoch=STATIC)
    # The pre-shift rule at every epoch below, with the same draws.
    never_reached = family(regime_shift_epoch=10_000)
    for market in (shifting, static, never_reached):
        market.reset(seed=11)
    assert static.version == shifting.version
    genome = {"revenue_model": {"price_minor_units": 250}}
    for epoch in range(25):
        for cell in ("a", "b", "c", "d"):
            action = ExperimentAction(cell_id=cell, genome_content=genome, hypothesis="h")
            expected = (shifting if epoch < 10 else never_reached).evaluate(experiment=action, epoch=epoch)
            assert static.evaluate(experiment=action, epoch=epoch) == expected
        assert static.advance(epoch=epoch) == ()
    assert any(shifting.advance(epoch=epoch) for epoch in range(25))


@pytest.mark.parametrize(
    "family,price",
    [
        # Pre-shift willingness to pay is uniform(0.5, 1.5) * 500 >= 250, so
        # 250 always sells; post-shift it is uniform(0.3, 0.9) * 500, often < 250.
        (UtilityMaximizingMarket, 250),
        # Pre-shift the budget band is <= 300, so 280 always sells; post-shift
        # it is <= 150, and 280 without a `durable` flag never does.
        (RuleBasedMarket, 280),
    ],
)
def test_after_the_shift_a_static_market_still_sells_what_the_shifted_market_refuses(family, price):
    """Checked against each family's pre-shift *rule*, not against another
    instance of the same class — an instance shares any bug in the code that
    decides which regime applies, and would agree with a static market that
    shifted anyway."""
    shifting, static = family(), family(regime_shift_epoch=STATIC)
    shifting.reset(seed=3)
    static.reset(seed=3)
    actions = [
        ExperimentAction(
            cell_id=f"cell-{i}", genome_content={"revenue_model": {"price_minor_units": price}},
            hypothesis="h",
        )
        for i in range(20)
    ]
    for epoch in range(10, 25):
        assert all(static.evaluate(experiment=a, epoch=epoch).purchased for a in actions)
    assert not all(
        shifting.evaluate(experiment=a, epoch=epoch).purchased for a in actions for epoch in range(10, 25)
    )


def test_a_static_and_a_shifting_run_are_the_same_economy_until_the_shift():
    """The pairing claim at run level: the same seed, the same policy, and
    every epoch record identical before epoch 10 — the shift epoch is the first
    thing allowed to differ."""
    shifting = _run(environment=build_environment(UtilityMaximizingMarket.name))
    static = _run(environment=build_environment(UtilityMaximizingMarket.name, static=True))
    assert shifting.epochs[:10] == static.epochs[:10]
    assert shifting.epochs[10].environment_events
    assert not any(record.environment_events for record in static.epochs)


@pytest.mark.parametrize("bad", [-1, True, 2.5, "10"])
def test_a_regime_shift_epoch_that_is_not_an_epoch_is_refused(bad):
    with pytest.raises(ValueError, match="regime_shift_epoch"):
        UtilityMaximizingMarket(regime_shift_epoch=bad)


# --- the lineage cap ---------------------------------------------------------


def test_a_lineage_cap_reaches_the_kernels_birth_licence():
    """§9.4's cap, set per run, has to bind where births are licensed — not
    only appear in a manifest. With four founders every lineage already holds
    1/4 of the colony, so one more birth projects 2/5 = 0.4: above the 0.2
    kernel default, below 1.0. The capped run therefore reproduces nothing and
    the uncapped one reproduces; if the setting never reached
    `lineage.check_lineage_licence` the two runs would be identical."""
    capped = _run(lineage_cap=0.2, epochs=6)
    uncapped = _run(lineage_cap=1.0, epochs=6)
    assert sum(record.reproductions for record in capped.epochs) == 0
    assert sum(record.reproductions for record in uncapped.epochs) > 0
    assert (capped.max_lineage_population_fraction, uncapped.max_lineage_population_fraction) == (0.2, 1.0)


def test_a_manifest_names_the_cap_the_colony_held_not_the_one_requested():
    """With no cap requested, the manifest reports the kernel default the colony
    actually applied — the field is read back from `colony_config`, never
    copied from `RunConfig`."""
    manifest = _run(epochs=2)
    assert manifest.max_lineage_population_fraction == models.DEFAULT_POPULATION_LIMITS.max_lineage_population_fraction


def test_a_run_refuses_a_cap_its_colony_was_already_configured_against():
    """`set_limits_if_absent` never changes a configured colony, so a run asking
    for a different cap would run under the old one while its manifest named
    the new one. Refused before the run is recorded."""
    conn = db.connect_and_migrate()
    try:
        population.set_limits_if_absent(conn, models.DEFAULT_POPULATION_LIMITS)
        with pytest.raises(runner.SimulationError, match="already configured"):
            _run(lineage_cap=0.5, epochs=2, conn=conn)
        assert conn.execute("SELECT COUNT(*) FROM simulation_runs").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("bad", [0, -0.1, 1.5, True])
def test_a_lineage_cap_outside_zero_to_one_is_refused(bad):
    with pytest.raises(runner.SimulationError, match="lineage_cap"):
        _run(lineage_cap=bad, epochs=1)


def test_an_unset_cap_hashes_exactly_as_a_run_configured_before_the_cap_existed():
    """Adding the field must not silently re-identify every earlier
    configuration; setting it must change the hash."""
    before = hashlib.sha256(json.dumps(
        {"scenario_name": "x", "master_seed": 1, "epochs": 6, "population": 3},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    unset = runner._config_hash(runner.RunConfig(scenario_name="x", master_seed=1, epochs=6, population=3))
    capped = runner._config_hash(
        runner.RunConfig(scenario_name="x", master_seed=1, epochs=6, population=3, lineage_cap=1.0)
    )
    assert unset == before
    assert capped != unset


# --- the arm grammar ----------------------------------------------------------


def test_a_bare_policy_name_is_that_policy_with_every_default():
    assert batch.parse_arm("map_elites") == batch.ArmSpec(label="map_elites", selection="map_elites")


def test_a_labelled_arm_carries_its_settings():
    assert batch.parse_arm("uncapped_static=map_elites+static_market+lineage_cap=1.0") == batch.ArmSpec(
        label="uncapped_static", selection="map_elites", static_market=True, lineage_cap=1.0,
    )


@pytest.mark.parametrize(
    "text,match",
    [
        ("map_elites+static_market", "needs a label"),
        ("s=map_elites+static_marker", "unknown option"),
        ("s=map_elites+static_market+static_market", "twice"),
        ("s=map_elites+lineage_cap=abc", "not a number"),
        ("s=map_elites+lineage_cap=0", r"\(0, 1\]"),
        ("s=map_elites+lineage_cap=nan", r"\(0, 1\]"),
        ("s=map_elites+lineage_cap", "unknown option"),
        ("a/b=map_elites", "letters, digits"),
        ("=map_elites", "names no policy"),
    ],
)
def test_an_arm_that_would_not_say_what_it_ran_is_refused(text, match):
    with pytest.raises(batch.BatchError, match=match):
        batch.parse_arm(text)


def test_a_static_arm_validates_against_a_static_market_too():
    """`staged_funding` probes elites against a validation market. In a static
    arm that market must not shift either, or the arm would be training in one
    regime and validating in two while its label says "static"."""
    static_policy = batch.build_selection(
        "staged_funding", environment_name=UtilityMaximizingMarket.name,
        validation_environment=UtilityMaximizingMarket.name, static_market=True,
    )
    shifting_policy = batch.build_selection(
        "staged_funding", environment_name=UtilityMaximizingMarket.name,
        validation_environment=UtilityMaximizingMarket.name,
    )
    assert static_policy._validation.regime_shift_epoch is STATIC
    assert shifting_policy._validation.regime_shift_epoch == 10


def test_two_labels_for_identical_settings_are_refused(tmp_path):
    """A batch comparing `a` with `b` when both are plain `map_elites` would
    report an arm against itself — the same refusal as naming an arm twice."""
    with pytest.raises(batch.BatchError, match="identical settings"):
        batch.plan(
            arms=["map_elites", "copy=map_elites+lineage_cap=0.2", "again=map_elites+lineage_cap=0.2"],
            seeds=[1], epochs=1, population=2, scenario="s",
            environment=UtilityMaximizingMarket.name, validation_environment=None, out_dir=tmp_path,
        )


def test_a_batch_runs_each_arm_with_its_own_settings_and_indexes_them(tmp_path):
    """End to end through the batch: the static arm's manifest has no shift
    event, the uncapped arm's names cap 1.0, and `batch.json` says what every
    label ran."""
    out = tmp_path / "arms"
    jobs = batch.plan(
        arms=["single_leaderboard", "static=single_leaderboard+static_market",
              "uncapped=single_leaderboard+lineage_cap=1.0"],
        seeds=[3], epochs=11, population=4, scenario="arms",
        environment=UtilityMaximizingMarket.name, validation_environment=None, out_dir=out,
    )
    batch.run_batch(jobs, out_dir=out, workers=1)
    manifests = {
        job.arm: json.loads((out / batch.manifest_filename(job.arm, 3)).read_text()) for job in jobs
    }
    assert any(e["environment_events"] for e in manifests["single_leaderboard"]["epochs"])
    assert not any(e["environment_events"] for e in manifests["static"]["epochs"])
    assert manifests["uncapped"]["max_lineage_population_fraction"] == 1.0
    assert manifests["single_leaderboard"]["max_lineage_population_fraction"] == 0.2
    index = json.loads((out / batch.INDEX_FILENAME).read_text())
    assert index["arm_settings"]["static"] == {
        "selection": "single_leaderboard", "static_market": True, "lineage_cap": None,
    }
    assert index["arm_settings"]["uncapped"]["lineage_cap"] == 1.0


# --- the metrics ---------------------------------------------------------------


def _manifest_with(epochs: list[dict]) -> dict:
    return {"epochs": epochs, "failures": [], "final_living_cells": 1}


def _epoch(*, concluded, revenue, price=400.0):
    return {
        "experiments_concluded": concluded, "revenue_minor_units": revenue,
        "mean_price_minor_units": price,
    }


def test_revenue_per_concluded_experiment_is_a_rate_that_headcount_cannot_move():
    """Twice the Cells concluding twice the experiments for twice the revenue is
    the same rate — the property `total_revenue_minor_units` lacks, and the
    reason Slice H's selection metric is this one."""
    small = _manifest_with([_epoch(concluded=4, revenue=1000), _epoch(concluded=6, revenue=500)])
    large = _manifest_with([_epoch(concluded=8, revenue=2000), _epoch(concluded=12, revenue=1000)])
    metric = paired.METRICS["revenue_per_concluded_experiment"]
    assert metric(small) == metric(large) == pytest.approx(150.0)
    assert paired.METRICS["total_revenue_minor_units"](large) == 2 * paired.METRICS[
        "total_revenue_minor_units"
    ](small)


def test_the_second_half_window_is_positional_and_reads_only_the_later_epochs():
    epochs = [_epoch(concluded=1, revenue=1000)] * 3 + [_epoch(concluded=2, revenue=100)] * 3
    assert paired.METRICS["second_half_revenue_per_concluded_experiment"](
        _manifest_with(epochs)
    ) == pytest.approx(50.0)
    # Five epochs: the window is the last three (5 // 2 = 2), so the middle
    # epoch counts — rounding the split up instead would read 10.0.
    odd = [_epoch(concluded=1, revenue=1000)] * 2 + [
        _epoch(concluded=1, revenue=100), _epoch(concluded=1, revenue=10), _epoch(concluded=1, revenue=10),
    ]
    assert paired.METRICS["second_half_revenue_per_concluded_experiment"](
        _manifest_with(odd)
    ) == pytest.approx(40.0)


def test_a_window_where_nothing_concluded_is_refused_not_reported_as_zero():
    with pytest.raises(paired.PairedComparisonError, match="no experiment concluded"):
        paired.METRICS["revenue_per_concluded_experiment"](
            _manifest_with([_epoch(concluded=0, revenue=0)])
        )


def test_final_mean_price_reads_the_last_epoch():
    manifest = _manifest_with([_epoch(concluded=1, revenue=1, price=500.0), _epoch(concluded=1, revenue=1, price=312.5)])
    assert paired.METRICS["final_mean_price_minor_units"](manifest) == 312.5


def test_mean_price_is_the_mean_over_living_cells():
    """Four founders price 400, 450, 500, 400 (`runner._founder_genome`), and a
    policy that never reproduces keeps exactly them."""
    manifest = _run(selection=_NoReproduction(), epochs=2)
    assert [record.mean_price_minor_units for record in manifest.epochs] == [437.5, 437.5]


def test_a_comparison_over_a_manifest_that_predates_a_metric_is_refused_by_name(tmp_path):
    out = tmp_path / "old"
    jobs = batch.plan(
        arms=["random_eligible", "single_leaderboard"], seeds=[1], epochs=2, population=2,
        scenario="old", environment=UtilityMaximizingMarket.name, validation_environment=None,
        out_dir=out,
    )
    batch.run_batch(jobs, out_dir=out, workers=1)
    path = out / batch.manifest_filename("random_eligible", 1)
    manifest = json.loads(path.read_text())
    for record in manifest["epochs"]:
        del record["mean_price_minor_units"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(paired.PairedComparisonError, match="predates this metric"):
        paired.compare_batch(
            out, baseline="random_eligible", treatment="single_leaderboard",
            metric="final_mean_price_minor_units",
        )
