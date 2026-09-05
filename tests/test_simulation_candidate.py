"""`src/mitosis/simulation/candidate.py` -- simulator-native fitness
dimensions (SPEC.md §10.2/§13.2; implementation brief Slice G, ADR-077+).

Unit-level, on constructed fixtures -- `tests/test_simulation.py` proves the
policies that consume this module through a live epoch loop; this file
proves the dimensions themselves in isolation."""

from __future__ import annotations

import random

import pytest

from mitosis import db, experiments, lifecycle
from mitosis.models import Book, CellStatus, CellType
from mitosis.simulation import candidate
from mitosis.simulation.candidate import Axis, GateOutcome, GateResult, SimCandidate


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


def _cell(conn, *, key: str, genome_content=None):
    return lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=1000,
        book=Book.USD_SIM, idempotency_key=key, genome_content=genome_content,
    )


def _concluded_experiment(conn, cell_id: str, *, key: str, revenue_minor_units: int | None = None):
    experiment = experiments.start(conn, cell_id=cell_id, hypothesis=f"hypothesis {key}")
    if revenue_minor_units is not None:
        from mitosis import revenue as revenue_module

        revenue_module.record_revenue(
            conn, cell_id=cell_id, amount_minor_units=revenue_minor_units,
            source=f"test sale {key}", book=Book.USD_SIM,
            experiment_id=experiment.experiment_id, idempotency_key=f"sale:{key}",
        )
    experiments.conclude(
        conn, experiment_id=experiment.experiment_id, concluded_by="test",
        note=f"test conclusion for {key}",
    )
    return experiment


def test_the_new_dataclasses_carry_no_score_rank_or_weight():
    """The same guarantee `test_selection.py`'s own
    `test_selection_carries_no_score_rank_or_weight` proves for the kernel's
    shapes, re-proven here for the simulator-native ones -- §13.2/§10.2 both
    forbid the scalar, and the surest way to keep one out is to give it
    nowhere to live."""
    forbidden = {"score", "rank", "weight", "fitness", "priority", "total"}
    for cls in (SimCandidate, Axis, GateResult):
        fields = set(cls.__dataclass_fields__)
        assert not (fields & forbidden), f"{cls.__name__} carries {fields & forbidden}"


def test_not_quarantined_gate_passes_alive_and_rejects_quarantined(conn):
    cell = _cell(conn, key="c1")
    result = candidate._not_quarantined(cell)
    assert result.outcome is GateOutcome.PASSED

    lifecycle.quarantine(conn, cell.cell_id, reason="test")
    quarantined = lifecycle.get_cell(conn, cell.cell_id)
    result = candidate._not_quarantined(quarantined)
    assert result.outcome is GateOutcome.REJECTED


def test_reproducibility_gate_is_unevaluable_below_the_minimum_tries(conn):
    cell = _cell(conn, key="c1")
    _concluded_experiment(conn, cell.cell_id, key="e1", revenue_minor_units=None)

    result = candidate._reproducibility(conn, cell)
    assert result.outcome is GateOutcome.UNEVALUABLE


def test_reproducibility_gate_rejects_a_genome_that_never_converts(conn):
    """3 independent Cells share a genome (founded with identical content),
    each concludes an experiment, none ever earns revenue -- REJECTED."""
    genome = {"market": {"segment": "shared"}}
    cells = [_cell(conn, key=f"c{i}", genome_content=genome) for i in range(3)]
    for i, cell in enumerate(cells):
        _concluded_experiment(conn, cell.cell_id, key=f"e{i}", revenue_minor_units=None)

    result = candidate._reproducibility(conn, cells[0])
    assert result.outcome is GateOutcome.REJECTED


def test_reproducibility_gate_passes_a_genome_that_converted_at_least_once(conn):
    genome = {"market": {"segment": "shared"}}
    cells = [_cell(conn, key=f"c{i}", genome_content=genome) for i in range(3)]
    for i, cell in enumerate(cells):
        revenue_minor_units = 500 if i == 1 else None
        _concluded_experiment(conn, cell.cell_id, key=f"e{i}", revenue_minor_units=revenue_minor_units)

    result = candidate._reproducibility(conn, cells[0])
    assert result.outcome is GateOutcome.PASSED


def test_structural_novelty_abstains_for_the_first_genome_in_the_archive(conn):
    cell = _cell(conn, key="c1")
    axis = candidate._structural_novelty(conn, cell.genome_hash)
    assert axis.value is None
    assert not axis.measured


def test_realized_net_revenue_is_unmeasured_with_no_concluded_experiments(conn):
    cell = _cell(conn, key="c1")
    axis = candidate._realized_net_revenue(conn, cell.cell_id)
    assert axis.value is None


def test_realized_net_revenue_reflects_earned_revenue_minus_spend(conn):
    cell = _cell(conn, key="c1")
    _concluded_experiment(conn, cell.cell_id, key="e1", revenue_minor_units=700)

    axis = candidate._realized_net_revenue(conn, cell.cell_id)
    # No simulated Cell posts to a SPEND_DESTINATIONS account in USD_SIM, so
    # the spend term is a real, computed zero -- net equals gross revenue.
    assert axis.value == pytest.approx(700.0)


def test_experiment_success_rate_reflects_the_fraction_that_earned_revenue(conn):
    cell = _cell(conn, key="c1")
    _concluded_experiment(conn, cell.cell_id, key="e1", revenue_minor_units=500)
    _concluded_experiment(conn, cell.cell_id, key="e2", revenue_minor_units=None)

    axis = candidate._experiment_success_rate(conn, cell.cell_id)
    assert axis.value == pytest.approx(0.5)


def test_economic_potential_is_always_unmeasured():
    axis = candidate._economic_potential()
    assert axis.value is None


def test_dominates_requires_strictly_better_on_at_least_one_shared_axis():
    better = SimCandidate(
        cell_id="a", gates=(),
        axes=(Axis("realized_net_revenue", 100.0, ""), Axis("structural_novelty", 1.0, "")),
    )
    worse = SimCandidate(
        cell_id="b", gates=(),
        axes=(Axis("realized_net_revenue", 50.0, ""), Axis("structural_novelty", 1.0, "")),
    )
    assert candidate.dominates(better, worse)
    assert not candidate.dominates(worse, better)
    assert not candidate.dominates(better, better)  # tied everywhere -- no strict improvement


def test_dominates_abstains_across_disjoint_measured_axes():
    """A high-revenue, unmeasured-novelty candidate and a high-novelty,
    unmeasured-revenue candidate share no measured axis -- neither
    dominates, and both must stay on the frontier."""
    revenue_only = SimCandidate(
        cell_id="a", gates=(),
        axes=(Axis("realized_net_revenue", 100.0, ""), Axis("structural_novelty", None, "")),
    )
    novelty_only = SimCandidate(
        cell_id="b", gates=(),
        axes=(Axis("realized_net_revenue", None, ""), Axis("structural_novelty", 2.0, "")),
    )
    assert not candidate.dominates(revenue_only, novelty_only)
    assert not candidate.dominates(novelty_only, revenue_only)


def test_pareto_frontier_excludes_gate_failures_and_dominated_candidates():
    rejected = SimCandidate(
        cell_id="rejected", gates=(GateResult("rejected", "not_quarantined", GateOutcome.REJECTED, ""),),
        axes=(Axis("realized_net_revenue", 1000.0, ""),),
    )
    dominated = SimCandidate(
        cell_id="dominated", gates=(),
        axes=(Axis("realized_net_revenue", 10.0, ""),),
    )
    dominant = SimCandidate(
        cell_id="dominant", gates=(),
        axes=(Axis("realized_net_revenue", 20.0, ""),),
    )
    frontier = candidate.pareto_frontier([rejected, dominated, dominant])
    assert frontier == ("dominant",)


def test_niche_elite_picks_the_highest_revenue_evaluated_occupant(conn):
    genome = {"market": {"segment": "shared"}}
    cells = [_cell(conn, key=f"c{i}", genome_content=genome) for i in range(3)]
    _concluded_experiment(conn, cells[0].cell_id, key="e0", revenue_minor_units=100)
    _concluded_experiment(conn, cells[1].cell_id, key="e1", revenue_minor_units=900)
    # cells[2] has no concluded experiment -- unevaluated, must lose to any
    # evaluated occupant regardless of the random draw.

    from mitosis import novelty

    niche = novelty.Niche(coordinate=(), genome_hashes=(cells[0].genome_hash,), living_cells=3)
    eligible = frozenset(c.cell_id for c in cells)
    elite = candidate.niche_elite(conn, niche, eligible, rng=random.Random(0))
    assert elite == cells[1].cell_id


def test_niche_elite_explores_uniformly_at_random_when_nothing_is_evaluated(conn):
    genome = {"market": {"segment": "shared"}}
    cells = [_cell(conn, key=f"c{i}", genome_content=genome) for i in range(5)]

    from mitosis import novelty

    niche = novelty.Niche(coordinate=(), genome_hashes=(cells[0].genome_hash,), living_cells=5)
    eligible = frozenset(c.cell_id for c in cells)
    picks = {
        candidate.niche_elite(conn, niche, eligible, rng=random.Random(seed))
        for seed in range(20)
    }
    # Deterministic per seed, but varies across seeds -- proves the random
    # exploration path actually runs rather than degenerating to one Cell.
    assert len(picks) > 1
    assert picks <= {c.cell_id for c in cells}


def test_niche_elite_returns_none_when_the_niche_has_no_eligible_occupant(conn):
    cell = _cell(conn, key="c1")

    from mitosis import novelty

    niche = novelty.Niche(coordinate=(), genome_hashes=(cell.genome_hash,), living_cells=1)
    elite = candidate.niche_elite(conn, niche, frozenset(), rng=random.Random(0))
    assert elite is None
