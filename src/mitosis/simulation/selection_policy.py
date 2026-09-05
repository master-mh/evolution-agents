"""A replaceable, recorded selection policy (implementation brief Slice G;
`docs/DECISIONS.md`'s Slice G ADRs and the approved plan file have the full
architecture).

`SelectionPolicy` decides which Cell(s) reproduce each epoch and records a
full decision, not just a list of winners (brief Slice G's own requirement).
`RandomEligibleSelection` -- brief Slice G's policy #1, shipped in F1 as the
correct minimum before quality-diversity selection existed to build on -- is
joined here by the full decision-record shape the other four named policies
(a single-leaderboard baseline, Pareto without MAP-Elites, MAP-Elites/
quality-diversity, the intended staged-funding policy) need; those policies
themselves land in their own sub-slices behind this same interface.
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
