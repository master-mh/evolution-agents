"""A replaceable, recorded selection policy (implementation brief Slice G,
designed here so Slice G is additive rather than a rework of this slice's
seam -- see the Slice F architecture ADR).

`SelectionPolicy` decides which Cell(s) reproduce each epoch and records a
full decision, not just a list of winners (brief Slice G's own requirement).
Only `RandomEligibleSelection` -- brief Slice G's policy #1 -- ships in this
slice: brief Slice F's own acceptance criteria need *some* reproduction to
happen across niches, not quality-diversity selection, so this is the correct
minimum rather than a placeholder. The other four named policies (a
single-leaderboard baseline, Pareto without MAP-Elites, MAP-Elites/quality-
diversity, the intended staged-funding policy) are Slice G's addition behind
this same interface.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from .. import ledger, lifecycle
from ..accounts import cell_cash
from ..models import Book, CellStatus
from . import mutation

#: Generous for a toy F1 economy: a parent needs this much left over *after*
#: funding a child so it can still pay for its own next wake (§15.4).
_CHILD_BUDGET_MINOR_UNITS = 100
_MIN_RETAINED_CASH_MINOR_UNITS = 50


@dataclass(frozen=True)
class SelectionDecision:
    """Brief Slice G's required decision-record fields, minus the ones this
    minimal policy has nothing to report for (no gates run, no frontier
    consulted, no posterior sampled) -- `reason` says so explicitly rather
    than a field silently reading zero."""

    policy_name: str
    policy_version: str
    epoch: int
    rng_seed_label: str
    eligible_cell_ids: tuple[str, ...]
    chosen_parent_cell_ids: tuple[str, ...]
    mutation_operator: str
    child_budget_minor_units: int
    reason: str


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
        )
