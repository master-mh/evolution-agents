"""Simulator-native fitness dimensions (SPEC.md §10.2/§13.2's gate-then-
frontier shape, never a scalar; implementation brief Slice G).

**Why this is not `selection.py` reused, and not a stylistic choice.**
`selection.py`'s nine dimensions are built for *grants* awaiting a kernel
funding decision, measured against real predictions/content-audits/escalating
signals -- and `SimulationPolicyProvider._propose()` hardcodes
`estimated_cost_minor_units: 0` and `predictions: []` on every call
(`policy.py:96-97`), unconditionally. That alone makes `evidence_quality`,
`information_gain`, and `experiment_cost` permanently trivial for every
simulated Cell; no content-audit or counterparty-keyed revenue is ever
produced either, so `software_native_advantage` and two of `novelty.py`'s
three descriptors (`buyer_type`, `revenue_recurrence`) are equally dead.
Reusing `selection.evaluate()`/`novelty.archive()` verbatim on simulated Cells
would produce a "frontier" that is constant on seven of nine kernel
dimensions and real on exactly one (`novelty_distance`, pure genome-content
diffing). Timing kills grant-shaped reuse outright too: by the time a
`SelectionPolicy.decide()` call happens in the epoch loop, the current
epoch's own experiment grant has already been consumed
(`experiment_grants.start_from_grant`, called before `decide()`), so
`selection.waiting_candidates()` structurally cannot see it as "waiting" --
the kernel's unit of analysis (a pending grant) answers a different question
than "which Cell reproduces this epoch."

So this module builds a **simulator-native** dimension set from data the
simulator actually produces (revenue, experiment outcomes, genome novelty),
reusing the kernel's *shapes* -- the gate/axis/UNMEASURABLE posture,
`dominates()`'s exact rule, the niche-coordinate pattern -- and reusing
`novelty.descriptors()` by **direct call** for `structural_novelty`, since
that one function is genuinely genome-content-only and works on simulated
genomes unchanged. Everything else here is new, honestly-named logic, not a
port of a kernel dimension under a different name.

Deliberately **not** named `fitness.py`: `death.py`'s own docstring already
argues SPEC.md forbids collapsing evaluation into a scalar a colony culls the
bottom of, and a module name suggesting a scalar this design never produces
would undercut the one point this whole file exists to make.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum

from .. import experiments, ledger, lifecycle, novelty, revenue
from ..models import Book, CellStatus
from . import environment

#: Mirrors `selection.GATE_DIMENSIONS`'s shape (name -> description) with a
#: deliberately disjoint set of names -- see the module docstring for why
#: porting the kernel's own nine names here would be dishonest, not merely
#: redundant.
SIM_GATE_DIMENSIONS: dict[str, str] = {
    "not_quarantined": "the Cell is not currently quarantined (§18) -- a realised fact, not a judgment",
    "reproducibility": (
        "a simulator-native analogue of §11.2's independent-adoption record: "
        "has this exact genome been tried by several independent Cells, and "
        "did any of them ever convert it to revenue? A different "
        "operationalization from the kernel's own human-adoption sense, "
        "stated explicitly rather than reused by accident (see `_reproducibility`)"
    ),
    "validation_probe": (
        "does this genome also clear a *different* market mechanism than the one "
        "it trained against (SPEC.md §8.1's validation role: 'influences capital "
        "allocation, partially hidden')? UNEVALUABLE, not a silent pass, when no "
        "validation environment is configured -- only StagedFundingSelection ever "
        "supplies one (see `validation_probe`)"
    ),
}

#: Mirrors `selection.FRONTIER_DIMENSIONS`'s shape. `economic_potential` is
#: named here, alongside the others, and is always unmeasurable -- see
#: `_economic_potential` for why that is a structural fact, not a gap this
#: slice left open.
SIM_FRONTIER_DIMENSIONS: dict[str, str] = {
    "structural_novelty": (
        "§12.1's novelty distance, read via a direct call to "
        "`novelty.descriptors()` -- pure genome-content diffing, unchanged "
        "from the kernel, since it needs no prediction/audit/counterparty data"
    ),
    "realized_net_revenue": (
        "revenue.total_revenue(USD_SIM) minus ledger.spend_by_book(...)"
        "['USD_SIM'] -- the spend term is an honest, computed zero for every "
        "simulated Cell today (no simulated Cell ever posts to a "
        "SPEND_DESTINATIONS account in USD_SIM), not a fabricated one"
    ),
    "experiment_success_rate": "fraction of this Cell's concluded experiments that produced USD_SIM revenue",
    "economic_potential": "always unmeasurable in the simulator too -- see `_economic_potential`",
}

#: Direction of preference for every measurable frontier dimension.
#: `economic_potential` is omitted, matching `selection.HIGHER_IS_BETTER`'s
#: own omission of the same permanently-unmeasurable dimension.
SIM_HIGHER_IS_BETTER: dict[str, bool] = {
    "structural_novelty": True,
    "realized_net_revenue": True,
    "experiment_success_rate": True,
}

#: How many independent Cells must have tried a genome before the
#: `reproducibility` gate will judge it, rather than abstain.
_MIN_INDEPENDENT_TRIES = 3

_NOVELTY_ORDINAL: dict[str, float] = {"adjacent": 0.0, "moderate": 1.0, "radical": 2.0}


class GateOutcome(StrEnum):
    """Three outcomes -- no `UNMEASURABLE` here, unlike `selection.GateOutcome`:
    every simulator-native gate below has real data to judge *something* on
    (a Cell's own status is always known; independent-try data either exists
    or doesn't, which is `UNEVALUABLE`, not a structural absence)."""

    PASSED = "passed"
    REJECTED = "rejected"
    UNEVALUABLE = "unevaluable"


@dataclass(frozen=True)
class GateResult:
    cell_id: str
    dimension: str
    outcome: GateOutcome
    reason: str


@dataclass(frozen=True)
class Axis:
    """One frontier dimension for one candidate. `value is None` is never
    "zero on this axis" -- `reason` says why, and a `None` axis is skipped by
    `dominates()` entirely, the same posture `selection.Axis` takes."""

    dimension: str
    value: float | None
    reason: str

    @property
    def measured(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class SimCandidate:
    """One living, eligible Cell, gated and placed -- the simulator's own
    unit of analysis for a reproduction decision, not a kernel grant.
    Carries no score, rank, or weight: `selection.Candidate`'s own reason
    (§13.2/§10.2 forbid the scalar; the surest way to keep one out is to give
    it nowhere to live) applies here unchanged."""

    cell_id: str
    gates: tuple[GateResult, ...]
    axes: tuple[Axis, ...]

    @property
    def rejected_by(self) -> tuple[str, ...]:
        return tuple(g.dimension for g in self.gates if g.outcome is GateOutcome.REJECTED)

    @property
    def passes_gates(self) -> bool:
        return not self.rejected_by

    def axis(self, dimension: str) -> Axis | None:
        return next((a for a in self.axes if a.dimension == dimension), None)


def _not_quarantined(cell: lifecycle.Cell) -> GateResult:
    if cell.status is CellStatus.QUARANTINED:
        return GateResult(
            cell.cell_id, "not_quarantined", GateOutcome.REJECTED, "Cell is quarantined",
        )
    return GateResult(
        cell.cell_id, "not_quarantined", GateOutcome.PASSED, f"status={cell.status.value}",
    )


def _independent_tries(conn, genome_hash: str) -> list[str]:
    """Other Cells sharing this genome_hash that have concluded >= 1
    experiment -- an independent "try" of this exact genome."""
    return [
        cell.cell_id for cell in lifecycle.list_cells(conn)
        if cell.genome_hash == genome_hash
        and any(e.status == experiments.STATUS_CONCLUDED for e in experiments.list_for(conn, cell.cell_id))
    ]


def _reproducibility(conn, cell: lifecycle.Cell) -> GateResult:
    tried = _independent_tries(conn, cell.genome_hash)
    if len(tried) < _MIN_INDEPENDENT_TRIES:
        return GateResult(
            cell.cell_id, "reproducibility", GateOutcome.UNEVALUABLE,
            f"only {len(tried)} independent Cell(s) have tried this genome and concluded an "
            f"experiment; {_MIN_INDEPENDENT_TRIES} needed before this gate can judge it",
        )
    if any(revenue.total_revenue(conn, cid, book=Book.USD_SIM) > 0 for cid in tried):
        return GateResult(
            cell.cell_id, "reproducibility", GateOutcome.PASSED,
            f"{len(tried)} independent Cell(s) tried this genome; at least one produced revenue",
        )
    return GateResult(
        cell.cell_id, "reproducibility", GateOutcome.REJECTED,
        f"{len(tried)} independent Cell(s) tried this genome and concluded an experiment; "
        "none ever produced revenue",
    )


def validation_probe(
    validation: environment.MarketEnvironment | None, *,
    cell_id: str, genome_content: dict, epoch: int,
) -> GateResult:
    """Whether a niche's chosen elite also clears a *different* market
    mechanism than the one it trained against -- `EnvironmentSuite.
    validation`'s first real consumer (`StagedFundingSelection` only).

    `UNEVALUABLE`, not a silent `PASSED`, when no validation environment is
    configured (every policy but `StagedFundingSelection`, and even that one
    when its own caller supplied none): "nothing to judge" is a different
    fact from "judged and found no problem," the same posture
    `_reproducibility` already takes below the independent-tries threshold.

    Side-effect-free by construction, not by convention: `evaluate()` is a
    pure function of its inputs (`environment.py`'s own docstring), so this
    probe posts no grant, no experiment row, no revenue -- it is a second
    read of a market's rule, not a second experiment.
    """
    if validation is None:
        return GateResult(
            cell_id, "validation_probe", GateOutcome.UNEVALUABLE,
            "no validation environment configured for this run",
        )
    outcome = validation.evaluate(
        experiment=environment.ExperimentAction(
            cell_id=cell_id, genome_content=genome_content, hypothesis="validation probe",
        ),
        epoch=epoch,
    )
    if outcome.purchased:
        return GateResult(
            cell_id, "validation_probe", GateOutcome.PASSED,
            f"cleared {validation.name}: {outcome.note}",
        )
    return GateResult(
        cell_id, "validation_probe", GateOutcome.REJECTED,
        f"failed {validation.name}: {outcome.note}",
    )


def _structural_novelty(conn, genome_hash: str) -> Axis:
    found = next(
        d for d in novelty.descriptors(conn, genome_hash) if d.dimension == "novelty_distance"
    )
    if found.measurement is not novelty.Measurement.MEASURED or found.bin is None:
        return Axis("structural_novelty", None, found.reason)
    return Axis("structural_novelty", _NOVELTY_ORDINAL[found.bin], f"{found.bin}: {found.reason}")


def _concluded_experiments(conn, cell_id: str) -> list[experiments.Experiment]:
    return [e for e in experiments.list_for(conn, cell_id) if e.status == experiments.STATUS_CONCLUDED]


def _realized_net_revenue(conn, cell_id: str, *, concluded: list[experiments.Experiment] | None = None) -> Axis:
    concluded = _concluded_experiments(conn, cell_id) if concluded is None else concluded
    if not concluded:
        return Axis("realized_net_revenue", None, "no concluded experiments yet")
    net = revenue.total_revenue(conn, cell_id, book=Book.USD_SIM) - ledger.spend_by_book(
        conn, cell_id
    ).get(Book.USD_SIM.value, 0)
    return Axis(
        "realized_net_revenue", float(net),
        f"revenue minus USD_SIM spend across {len(concluded)} concluded experiment(s)",
    )


def _experiment_success_rate(conn, cell_id: str, *, concluded: list[experiments.Experiment] | None = None) -> Axis:
    concluded = _concluded_experiments(conn, cell_id) if concluded is None else concluded
    if not concluded:
        return Axis("experiment_success_rate", None, "no concluded experiments yet")
    successes = 0
    for experiment in concluded:
        row = conn.execute(
            "SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total FROM ledger_entries e "
            "JOIN ledger_transactions t ON t.transaction_id = e.transaction_id "
            "WHERE e.experiment_id = ? AND t.book = ? AND e.amount_minor_units > 0",
            (experiment.experiment_id, Book.USD_SIM.value),
        ).fetchone()
        if row["total"] > 0:
            successes += 1
    return Axis(
        "experiment_success_rate", successes / len(concluded),
        f"{successes}/{len(concluded)} concluded experiments produced revenue",
    )


def _economic_potential() -> Axis:
    """Stays UNMEASURABLE even in the simulator, unlike `reproducibility`.

    The kernel's blocker is structural, not a data gap: §0.3 forbids a
    Cell's self-reported upside from ever being canonical, and there is no
    proper scoring rule over it. `SimulationPolicyProvider._propose()` has no
    upside/potential field at all -- there is nothing here to even refuse.
    Retroactively defining "economic potential" as realized revenue would
    answer a different question (backward-looking, not a forecast) under a
    name that means something else; `realized_net_revenue` carries that
    honest signal under its own name instead.
    """
    return Axis(
        "economic_potential", None,
        "no self-reported-upside field exists in the simulator to even refuse "
        "-- unlike the kernel's gap (structural: §0.3), there is nothing here "
        "that could be measured under this name without answering a "
        "different question (realized, not forecast) than what it means",
    )


def cell_candidate(conn, cell: lifecycle.Cell) -> SimCandidate:
    """Build one `SimCandidate` for a living, eligible Cell."""
    concluded = _concluded_experiments(conn, cell.cell_id)
    gates = (_not_quarantined(cell), _reproducibility(conn, cell))
    axes = (
        _structural_novelty(conn, cell.genome_hash),
        _realized_net_revenue(conn, cell.cell_id, concluded=concluded),
        _experiment_success_rate(conn, cell.cell_id, concluded=concluded),
        _economic_potential(),
    )
    return SimCandidate(cell_id=cell.cell_id, gates=gates, axes=axes)


def dominates(better: SimCandidate, worse: SimCandidate) -> bool:
    """Same rule as `selection.dominates`, reimplemented over `SimCandidate`
    (a different shape, not a different rule): at least as good everywhere
    measured, strictly better somewhere, skip axes either side hasn't
    measured, never dominate across disjoint measured sets."""
    strictly_better_somewhere = False
    for dimension, higher_is_better in SIM_HIGHER_IS_BETTER.items():
        mine, theirs = better.axis(dimension), worse.axis(dimension)
        if mine is None or theirs is None or not (mine.measured and theirs.measured):
            continue
        a, b = mine.value, theirs.value
        if a == b:
            continue
        if (a > b) is higher_is_better:
            strictly_better_somewhere = True
        else:
            return False
    return strictly_better_somewhere


def pareto_frontier(candidates: list[SimCandidate]) -> tuple[str, ...]:
    """`cell_id`s on the frontier among gate-survivors."""
    survivors = [c for c in candidates if c.passes_gates]
    return tuple(
        c.cell_id for c in survivors
        if not any(dominates(other, c) for other in survivors if other.cell_id != c.cell_id)
    )


def niche_elite(
    conn, niche: novelty.Niche, eligible_cell_ids: frozenset[str], *, rng: random.Random,
) -> str | None:
    """MAP-Elites' elite rule for one niche.

    The eligible living Cell in this niche with the highest
    `realized_net_revenue` among those that have concluded >= 1 experiment;
    if none have, chosen **uniformly at random** among the eligible ones --
    an explicit "no evidence yet, explore" rule, never a silent default to
    `None`. `None` only when no eligible Cell occupies this niche at all.
    """
    occupants = [
        cell for cell in lifecycle.list_cells(conn)
        if cell.genome_hash in niche.genome_hashes and cell.cell_id in eligible_cell_ids
    ]
    if not occupants:
        return None
    evaluated = [
        (cell.cell_id, _realized_net_revenue(conn, cell.cell_id))
        for cell in occupants
        if _concluded_experiments(conn, cell.cell_id)
    ]
    if evaluated:
        evaluated.sort(key=lambda pair: (-pair[1].value, pair[0]))
        return evaluated[0][0]
    return rng.choice(sorted(cell.cell_id for cell in occupants))
