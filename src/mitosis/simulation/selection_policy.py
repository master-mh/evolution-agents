"""A replaceable, recorded selection policy (implementation brief Slice G;
`docs/DECISIONS.md`'s Slice G ADRs and the approved plan file have the full
architecture).

`SelectionPolicy` decides which Cell(s) reproduce each epoch and records a
full decision, not just a list of winners (brief Slice G's own requirement).
`RandomEligibleSelection` (policy #1, shipped in F1) and `SingleLeaderboardSelection`
(policy #2, an intentionally-forbidden single-scalar shape kept only as a
Phase 3 comparator) both ship here. `ParetoSelection`, `MapElitesSelection`,
and `StagedFundingSelection` land in their own later sub-slices behind this
same interface, once `candidate.py`'s gates/axes/niches have real consumers
worth building around.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from .. import ledger, lifecycle
from ..accounts import cell_cash
from ..models import Book, CellStatus
from . import candidate, mutation

#: Generous for a toy F1 economy: a parent needs this much left over *after*
#: funding a child so it can still pay for its own next wake (§15.4).
_CHILD_BUDGET_MINOR_UNITS = 100
_MIN_RETAINED_CASH_MINOR_UNITS = 50

#: Every simulator-native dimension name (`candidate.py`), for a policy that
#: consults none of them to report honestly -- `unmeasured_dimensions` names
#: what *could* be measured and wasn't, never an unexplained empty tuple.
_ALL_SIM_DIMENSIONS: tuple[str, ...] = tuple(
    sorted(set(candidate.SIM_GATE_DIMENSIONS) | set(candidate.SIM_FRONTIER_DIMENSIONS))
)


@dataclass(frozen=True)
class NicheStanding:
    """One niche's standing at decision time -- brief Slice G's "niche
    assignment and current niche occupant" plus "posterior values or samples
    actually used", bundled per niche rather than as parallel tuples that
    could disagree on length or order."""

    coordinate: tuple[tuple[str, str], ...]
    living_cell_ids: tuple[str, ...]
    elite_cell_id: str | None
    posterior_trials: int
    posterior_conversions: int
    posterior_alpha: float
    posterior_beta: float
    posterior_mean: float
    thompson_sample: float | None
    funded_this_epoch: bool


@dataclass(frozen=True)
class SelectionDecision:
    """Brief Slice G's required decision-record fields. New fields are all
    defaulted, so a policy with nothing to report for one (like
    `RandomEligibleSelection`, which runs no gates and consults no niches)
    states that explicitly in `reason`/`intended_experiment` rather than
    leaving a silently-empty field with no explanation -- the same posture
    this dataclass's own F1 docstring already established for its first,
    smaller field set."""

    policy_name: str
    policy_version: str
    epoch: int
    rng_seed_label: str
    eligible_cell_ids: tuple[str, ...]
    chosen_parent_cell_ids: tuple[str, ...]
    mutation_operator: str
    child_budget_minor_units: int
    reason: str
    gate_results: tuple[candidate.GateResult, ...] = ()
    measured_dimensions: tuple[str, ...] = ()
    unmeasured_dimensions: tuple[str, ...] = ()
    pareto_front_cell_ids: tuple[str, ...] = ()
    niches: tuple[NicheStanding, ...] = ()
    #: (parent_cell_id, operator) overrides for a policy reproducing from
    #: multiple parents in one epoch, each wanting its own operator -- a
    #: policy that reproduces from at most one parent (like
    #: `RandomEligibleSelection`) never populates this; `runner.py` falls
    #: back to `mutation_operator` above when a parent has no entry here.
    parent_mutation_operators: tuple[tuple[str, str], ...] = ()
    #: Same pattern as `parent_mutation_operators`, for a per-niche budget
    #: that scales with that niche's own posterior confidence.
    parent_child_budgets: tuple[tuple[str, int], ...] = ()
    intended_experiment: str = ""


class SelectionPolicy(Protocol):
    name: str
    version: str

    def decide(
        self, conn, *, epoch: int, rng: random.Random, seed_label: str
    ) -> SelectionDecision: ...


def _eligible_parents(conn, *, book: Book) -> list[lifecycle.Cell]:
    eligible = []
    for cell in lifecycle.list_cells(conn):
        if cell.status is not CellStatus.ALIVE or cell.book is not book:
            continue
        cash = ledger.get_balance(conn, cell_cash(cell.cell_id), book)
        if cash >= _CHILD_BUDGET_MINOR_UNITS + _MIN_RETAINED_CASH_MINOR_UNITS:
            eligible.append(cell)
    return eligible


class RandomEligibleSelection:
    name = "random_eligible"
    version = "1"

    def __init__(self, *, book: Book = Book.USD_SIM) -> None:
        self._book = book

    def decide(
        self, conn, *, epoch: int, rng: random.Random, seed_label: str
    ) -> SelectionDecision:
        eligible = _eligible_parents(conn, book=self._book)
        chosen = tuple(cell.cell_id for cell in rng.sample(eligible, k=min(1, len(eligible))))
        # Reuses this same call's `rng` rather than drawing a second one --
        # the choice is still deterministic given `seed_label`, just a later
        # value in the one stream this decision already consumes from.
        operator = rng.choice(sorted(mutation.OPERATORS)) if chosen else mutation.NO_OP_OPERATOR
        return SelectionDecision(
            policy_name=self.name,
            policy_version=self.version,
            epoch=epoch,
            rng_seed_label=seed_label,
            eligible_cell_ids=tuple(c.cell_id for c in eligible),
            chosen_parent_cell_ids=chosen,
            mutation_operator=operator,
            child_budget_minor_units=_CHILD_BUDGET_MINOR_UNITS,
            reason=(
                f"{len(eligible)} cell(s) eligible ({self._book.value} cash >= "
                f"{_CHILD_BUDGET_MINOR_UNITS + _MIN_RETAINED_CASH_MINOR_UNITS}); "
                f"chose {len(chosen)} uniformly at random -- brief Slice G policy #1, "
                "no quality-diversity signal consulted; mutation operator chosen "
                "uniformly at random among all registered operators"
            ),
            unmeasured_dimensions=_ALL_SIM_DIMENSIONS,
            intended_experiment=(
                "none -- this policy does not read a candidate's proposed "
                "hypothesis before choosing it, by design (brief Slice G policy #1)"
            ),
        )


#: Brief Slice G policy #2's own named scalar -- a class attribute, not a
#: buried literal, so the decision record can state exactly what it
#: collapsed fitness into.
_SCALAR_METRIC = "realized_net_revenue_minor_units"


class SingleLeaderboardSelection:
    """Brief Slice G policy #2: "a single-leaderboard baseline with an
    explicitly declared scalar metric, used only as an experimental
    control." SPEC.md §10.2/§13.2 both forbid exactly this shape for the
    production kernel — built here on purpose, clearly labelled, so Slice H
    has a real comparator for "intended selection vs random mutation" and
    "Pareto vs a single scalar," never as a candidate default."""

    name = "single_leaderboard"
    version = "1"
    scalar_metric = _SCALAR_METRIC

    def __init__(self, *, book: Book = Book.USD_SIM) -> None:
        self._book = book

    def decide(
        self, conn, *, epoch: int, rng: random.Random, seed_label: str
    ) -> SelectionDecision:
        eligible = _eligible_parents(conn, book=self._book)

        def _rank_key(cell: lifecycle.Cell) -> tuple:
            revenue_axis = candidate._realized_net_revenue(conn, cell.cell_id)
            # Unmeasured (no concluded experiment yet) ranks last: a
            # leaderboard needs one total order over every eligible cell,
            # and "has proven nothing yet" cannot outrank a proven, even
            # small, positive result -- stated here rather than silently
            # decided, since `Axis.value is None` is never "zero" elsewhere
            # in this codebase.
            has_evidence = revenue_axis.value is not None
            return (
                not has_evidence, -(revenue_axis.value or 0.0),
                cell.generation, cell.created_at_utc, cell.cell_id,
            )

        ranked = sorted(eligible, key=_rank_key)
        chosen = (ranked[0].cell_id,) if ranked else ()
        operator = rng.choice(sorted(mutation.OPERATORS)) if chosen else mutation.NO_OP_OPERATOR
        return SelectionDecision(
            policy_name=self.name,
            policy_version=self.version,
            epoch=epoch,
            rng_seed_label=seed_label,
            eligible_cell_ids=tuple(c.cell_id for c in eligible),
            chosen_parent_cell_ids=chosen,
            mutation_operator=operator,
            child_budget_minor_units=_CHILD_BUDGET_MINOR_UNITS,
            reason=(
                f"{len(eligible)} cell(s) eligible; ranked by {_SCALAR_METRIC} descending "
                "(a cell with no concluded experiment yet ranks last, never tied with a "
                "proven zero), chose the single top-ranked cell -- brief Slice G policy #2, "
                "an intentionally-forbidden single-scalar shape (SPEC.md §10.2/§13.2) built "
                "only as a Phase 3 experimental control, never a default. No gates run."
            ),
            measured_dimensions=("realized_net_revenue",),
            unmeasured_dimensions=tuple(d for d in _ALL_SIM_DIMENSIONS if d != "realized_net_revenue"),
            intended_experiment=(
                "none -- this policy ranks by realized revenue alone and does not read a "
                "candidate's proposed hypothesis before choosing it"
            ),
        )


class UnknownSelectionPolicyError(Exception):
    pass


def build_selection_policy(name: str) -> SelectionPolicy:
    """A name -> instance factory, mirroring `environment.build_environment`,
    so a CLI flag or scenario config can select a policy without importing
    every concrete class itself."""
    if name == RandomEligibleSelection.name:
        return RandomEligibleSelection()
    if name == SingleLeaderboardSelection.name:
        return SingleLeaderboardSelection()
    raise UnknownSelectionPolicyError(
        f"no selection policy named {name!r}; available: "
        f"{RandomEligibleSelection.name}, {SingleLeaderboardSelection.name}"
    )
