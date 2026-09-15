"""Seed-paired batch comparisons (SPEC.md §28 Phase 3, §7.1; ADR-084).

Two things are defended here. The *pairing precondition* — that no selection
policy can shift the randomness another component draws, which is the only
thing that makes comparing two arms at the same seed mean more than comparing
them at different seeds. And the *analysis* — that a paired interval is
computed over genuinely paired data and reports whether pairing helped,
rather than asserting that it did.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict
from pathlib import Path

import pytest

from mitosis import cli, db, ids
from mitosis.simulation import batch, mutation, paired, runner
from mitosis.simulation.environment import EnvironmentSuite, UtilityMaximizingMarket
from mitosis.simulation.selection_policy import SelectionDecision, SingleLeaderboardSelection


class _NoReproduction:
    """Chooses no parent, so both arms keep exactly the founding population —
    and, when `burn` is set, consumes the stream it was handed, the global
    `random` module, and the seeded id generator as hard as it can first."""

    version = "1"

    def __init__(self, *, burn: bool) -> None:
        self.name = "burning" if burn else "quiet"
        self._burn = burn

    def decide(self, conn, *, epoch, rng, seed_label):
        if self._burn:
            for _ in range(250):
                rng.random()
                random.random()
                ids.new_id()
        return SelectionDecision(
            policy_name=self.name, policy_version=self.version, epoch=epoch,
            rng_seed_label=seed_label, eligible_cell_ids=(), chosen_parent_cell_ids=(),
            mutation_operator=mutation.NO_OP_OPERATOR, child_budget_minor_units=0,
            reason="test policy: never reproduces",
        )


def _run_with(selection, *, seed=5, epochs=8, population=4):
    conn = db.connect_and_migrate()
    try:
        return runner.run(
            conn,
            runner.RunConfig(scenario_name="pairing", master_seed=seed, epochs=epochs, population=population),
            suite=EnvironmentSuite.training_only(UtilityMaximizingMarket()),
            selection=selection,
        )
    finally:
        conn.close()


def test_a_selection_policy_cannot_shift_any_other_components_randomness():
    """The pairing precondition (arXiv 2512.24145's "structural randomness"
    shared across arms). Two arms that differ *only* in how much randomness —
    and how many seeded ids — their selection policy consumes must produce
    identical economies. If a component keyed its draws off a shared stream,
    off the global `random` module, or off any id the seeded generator hands
    out after selection runs (an experiment id, a deliberation id), the burning
    arm's sales would diverge and a seed-paired comparison would be comparing
    two different markets under one seed."""
    quiet = _run_with(_NoReproduction(burn=False))
    burning = _run_with(_NoReproduction(burn=True))
    assert quiet.epochs == burning.epochs
    assert quiet.final_living_cells == burning.final_living_cells
    # Not vacuous: the markets actually traded, so there was randomness to shift.
    assert sum(epoch.sales for epoch in quiet.epochs) > 0


def test_two_real_policies_share_everything_before_their_first_selection():
    """Every arm at one seed starts from the same founders facing the same
    first market; selection is the first thing allowed to differ."""
    leaderboard = _run_with(SingleLeaderboardSelection(), epochs=3)
    burning = _run_with(_NoReproduction(burn=True), epochs=3)
    first_a, first_b = leaderboard.epochs[0], burning.epochs[0]
    for field in ("experiments_started", "experiments_concluded", "sales", "revenue_minor_units"):
        assert getattr(first_a, field) == getattr(first_b, field), field


# --- the analysis ------------------------------------------------------------


def test_perfectly_correlated_arms_pair_to_a_zero_width_interval():
    baseline = {1: 10.0, 2: 20.0, 3: 30.0, 4: 40.0}
    treatment = {s: v + 5.0 for s, v in baseline.items()}
    result = paired.compare_values(baseline, treatment, resamples=500)
    assert result.mean_difference == pytest.approx(5.0)
    assert result.paired_ci == (pytest.approx(5.0), pytest.approx(5.0))
    assert result.variance_ratio == pytest.approx(0.0)
    assert result.seed_correlation == pytest.approx(1.0)
    # The unpaired interval over the same numbers is wide and straddles zero:
    # this is the whole reason for the design.
    assert result.unpaired_ci[0] < 0 < result.unpaired_ci[1]
    assert result.paired_ci_excludes_zero


def test_anticorrelated_arms_report_that_pairing_widened_the_interval():
    """Pairing is not free: `Var(d) = Var(a) + Var(b) - 2 Cov`, so negatively
    correlated arms make the paired interval *wider*. Reported, not hidden."""
    baseline = {1: 10.0, 2: 20.0, 3: 30.0, 4: 40.0}
    treatment = {1: 40.0, 2: 30.0, 3: 20.0, 4: 10.0}
    result = paired.compare_values(baseline, treatment, resamples=500)
    assert result.seed_correlation == pytest.approx(-1.0)
    assert result.variance_ratio == pytest.approx(2.0)


def test_unpaired_seeds_are_refused_not_dropped():
    with pytest.raises(paired.PairedComparisonError, match="not paired"):
        paired.compare_values({1: 1.0, 2: 2.0}, {1: 1.0, 3: 3.0})


def test_constant_arms_have_undefined_correlation_rather_than_a_made_up_one():
    result = paired.compare_values({1: 3.0, 2: 3.0}, {1: 4.0, 2: 4.0}, resamples=50)
    assert result.seed_correlation is None
    assert result.variance_ratio is None
    assert result.mean_difference == pytest.approx(1.0)


def test_the_same_data_reports_the_same_interval_every_time():
    baseline = {s: float(s * s % 7) for s in range(1, 9)}
    treatment = {s: float((s * 3) % 11) for s in range(1, 9)}
    first = paired.compare_values(baseline, treatment, resamples=300)
    second = paired.compare_values(baseline, treatment, resamples=300)
    assert first == second


def test_every_named_metric_reads_a_real_manifest():
    manifest = json.loads(_run_with(SingleLeaderboardSelection(), epochs=4).to_json())
    for name, fn in paired.METRICS.items():
        assert isinstance(fn(manifest), float), name


# --- the batch ---------------------------------------------------------------


def test_plan_runs_every_arm_at_every_seed(tmp_path):
    jobs = batch.plan(
        arms=["random_eligible", "single_leaderboard"], seeds=[3, 4, 5], epochs=2, population=2,
        scenario="s", environment=UtilityMaximizingMarket.name, validation_environment=None,
        out_dir=tmp_path,
    )
    assert {(j.arm, j.seed) for j in jobs} == {
        (arm, seed) for arm in ("random_eligible", "single_leaderboard") for seed in (3, 4, 5)
    }


@pytest.mark.parametrize(
    "arms,seeds,match",
    [
        (["random_eligible", "random_eligible"], [1], "arm named twice"),
        (["random_eligible"], [1, 1], "seed named twice"),
        (["no_such_policy"], [1], "no selection policy"),
    ],
)
def test_plan_refuses_a_batch_that_would_not_be_the_comparison_it_names(tmp_path, arms, seeds, match):
    from mitosis.simulation.selection_policy import UnknownSelectionPolicyError

    with pytest.raises((batch.BatchError, UnknownSelectionPolicyError), match=match):
        batch.plan(
            arms=arms, seeds=seeds, epochs=2, population=2, scenario="s",
            environment=UtilityMaximizingMarket.name, validation_environment=None, out_dir=tmp_path,
        )


def test_a_worker_process_reproduces_the_in_process_manifest(tmp_path):
    """Spawned workers must not change what a run produces — otherwise a
    batch result is a property of the process pool rather than of the seed."""
    jobs = batch.plan(
        arms=["random_eligible", "single_leaderboard"], seeds=[2], epochs=5, population=3,
        scenario="xproc", environment=UtilityMaximizingMarket.name, validation_environment=None,
        out_dir=tmp_path / "pool",
    )
    batch.run_batch(jobs, out_dir=tmp_path / "pool", workers=2)
    for job in jobs:
        pooled = json.loads(Path(job.output_path).read_text())
        inline_path = tmp_path / f"inline-{job.arm}.json"
        batch.run_job(batch.BatchJob(**{**asdict(job), "output_path": str(inline_path)}))
        inline = json.loads(inline_path.read_text())
        del pooled["run_id"], inline["run_id"]
        assert pooled == inline, job.arm

    index = json.loads((tmp_path / "pool" / batch.INDEX_FILENAME).read_text())
    assert index["arms"] == ["random_eligible", "single_leaderboard"]
    assert len(index["runs"]) == 2


def test_every_run_in_a_batch_names_the_code_version_read_once_by_the_plan(tmp_path, monkeypatch):
    """A run that reads `git` itself can time out under load and record
    "unknown" — the cause of this suite's one flaky failure, where a pooled
    manifest and its inline twin disagreed about nothing but `code_version`.
    `plan` reads it once, in the parent, and every run carries that answer;
    nothing a worker does afterwards can change what a manifest names."""
    monkeypatch.setattr(runner, "_code_version", lambda: "plan-read")
    jobs = batch.plan(
        arms=["random_eligible", "single_leaderboard"], seeds=[1, 2], epochs=2, population=2,
        scenario="cv", environment=UtilityMaximizingMarket.name, validation_environment=None,
        out_dir=tmp_path,
    )
    monkeypatch.setattr(runner, "_code_version", lambda: "unknown")
    batch.run_batch(jobs, out_dir=tmp_path, workers=1)
    recorded = {json.loads(Path(job.output_path).read_text())["code_version"] for job in jobs}
    assert recorded == {"plan-read"}


def test_one_process_names_one_code_version_even_when_git_slows_down(monkeypatch):
    """The in-process half of the same flake: two runs of one seed in one
    process named different code after the second `git rev-parse` timed out,
    and `test_the_same_seed_reproduces_the_same_manifest` failed on it."""
    answers = iter(["abc1234\n"])

    def slow_git(*args, **kwargs):
        try:
            stdout = next(answers)
        except StopIteration:
            raise runner.subprocess.TimeoutExpired(cmd="git", timeout=5) from None
        return runner.subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    # Through getattr, so a regression that drops the cache fails on the
    # disagreement below rather than on a missing `cache_clear`.
    clear = getattr(runner._code_version, "cache_clear", lambda: None)
    clear()
    monkeypatch.setattr(runner.subprocess, "run", slow_git)
    try:
        first = runner._code_version()
        second = runner._code_version()
        assert (first, second) == ("abc1234", "abc1234")
    finally:
        clear()


def test_a_comparison_refuses_an_arm_whose_run_recorded_a_failure(tmp_path):
    out = tmp_path / "b"
    jobs = batch.plan(
        arms=["random_eligible", "single_leaderboard"], seeds=[1, 2], epochs=2, population=2,
        scenario="f", environment=UtilityMaximizingMarket.name, validation_environment=None, out_dir=out,
    )
    batch.run_batch(jobs, out_dir=out, workers=1)
    broken = out / batch.manifest_filename("single_leaderboard", 2)
    manifest = json.loads(broken.read_text())
    manifest["failures"] = ["epoch 1: injected"]
    broken.write_text(json.dumps(manifest))
    with pytest.raises(paired.PairedComparisonError, match="failure"):
        paired.compare_batch(out, baseline="random_eligible", treatment="single_leaderboard",
                             metric="final_living_cells")


def test_cli_batch_then_compare_end_to_end(tmp_path, capsys):
    out = tmp_path / "cli"
    assert cli.main([
        "simulate-batch", "--arms", "random_eligible,single_leaderboard", "--seeds", "1-3",
        "--epochs", "3", "--population", "3", "--workers", "1", "--out-dir", str(out),
    ]) in (0, None)
    assert cli.main([
        "simulate-compare", "--dir", str(out), "--baseline", "random_eligible",
        "--treatment", "single_leaderboard", "--metric", "total_revenue_minor_units",
        "--resamples", "200",
    ]) in (0, None)
    printed = capsys.readouterr().out
    assert "over 3 paired seed(s)" in printed
    assert "seed correlation" in printed


@pytest.mark.parametrize(
    "text,expected",
    [("1-3", [1, 2, 3]), ("5,2", [5, 2]), ("1-2,9", [1, 2, 9])],
)
def test_seed_lists_parse_ranges_and_lists(text, expected):
    assert cli._parse_seed_list(text) == expected


def test_a_backwards_seed_range_is_refused():
    with pytest.raises(cli.CliError, match="backwards"):
        cli._parse_seed_list("5-2")
