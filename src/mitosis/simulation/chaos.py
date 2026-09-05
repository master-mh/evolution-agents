"""Chaos drills (SPEC.md §28 Phase 2: "kill 30% of Cells mid-epoch, corrupt a
shared module, crash mid-settlement -- conservation must hold and the
population must recover"; implementation brief's fuller five-drill list).

Two of the five drills operate one layer up from where their brief wording
might suggest, and that reframing is deliberate, not a shortcut -- explained
at each one below and in `docs/DECISIONS.md`'s ADR-075:

- "Corrupt or withdraw one shared capability/module" has no module/tool-use
  surface to target yet: `SimulationPolicyProvider` decides from genome
  content alone (see `policy.py`'s own docstring on why). The one genuinely
  shared, colony-wide capability this simulator actually depends on is the
  `auto_promotion` autonomy flag `runner.run()` enables at setup
  (ADR-071/072) -- withdrawing *that* mid-run is a real capability loss with
  real downstream consequences, not a stand-in for a mechanism that isn't
  built.
- "Crash at reserve, execute, and settlement boundaries" targets the
  *experiment* lifecycle's own three-phase shape (start / evaluate /
  conclude+record-revenue) rather than the deeper money-reservation FSM
  inside `gateway.py`. That FSM's own crash safety is Charter C6's job,
  already exhaustively verified by a provider-agnostic stateful machine
  (`tests/test_charter_properties.py`) independent of any live population.
  What that machine does not exercise -- and what is actually new here -- is
  whether a full simulation run's *own* state (population, audit trail,
  manifest) survives one call failing mid-flight. `CrashingEnvironment`
  wraps the one experiment-lifecycle call the simulator already drives
  directly (`environment.evaluate`, the "execute" phase) to fail exactly
  once; `start_from_grant` ("reserve") and `conclude`/`record_revenue`
  ("settlement") are direct calls to kernel functions with no injectable
  seam today, and adding one solely so a drill could target them would be
  building speculative surface for no other caller -- exactly what this
  repo's own conventions rule out.

Each drill is either an epoch-hook (`__call__(conn, epoch) -> None`, fired
once per epoch by `runner.run`'s `epoch_hook` parameter after that epoch's
own processing already completed) or a `MarketEnvironment` decorator. Neither
shape needs `runner.py` to grow a per-drill special case.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from .. import ledger, lifecycle, tools
from ..models import Book, CellStatus
from .environment import EnvironmentEvent, ExperimentAction, MarketEnvironment, Observation, Outcome


@dataclass(frozen=True)
class DrillReport:
    drill_name: str
    epoch: int
    detail: str


class KillFractionDrill:
    """Brief: "kill 30% of Cells mid-epoch." Fires once, at `at_epoch`,
    after that epoch's own processing has already run -- population,
    experiments, and reproduction for that epoch already settled, so
    recovery is measured from a normal, consistent state rather than an
    in-flight one."""

    name = "kill_fraction"

    def __init__(self, *, fraction: float, at_epoch: int, cause: str = "chaos_drill_kill") -> None:
        self._fraction = fraction
        self._at_epoch = at_epoch
        self._cause = cause
        self.reports: list[DrillReport] = []

    def __call__(self, conn: Any, epoch: int) -> None:
        if epoch != self._at_epoch:
            return
        living = [c for c in lifecycle.list_cells(conn) if c.status is CellStatus.ALIVE]
        rng = random.Random(f"chaos:{self.name}:{self._at_epoch}")
        victim_count = min(len(living), round(len(living) * self._fraction))
        victims = rng.sample(living, k=victim_count)
        for cell in victims:
            lifecycle.kill(conn, cell.cell_id, cause_of_death=self._cause)
        self.reports.append(DrillReport(
            drill_name=self.name, epoch=epoch,
            detail=f"killed {len(victims)}/{len(living)} living Cell(s)",
        ))


class WithdrawCapabilityDrill:
    """Brief: "corrupt or withdraw one shared capability/module." See the
    module docstring for why `auto_promotion` is the honest target here."""

    name = "withdraw_capability"

    def __init__(self, *, at_epoch: int, flag: str = "auto_promotion") -> None:
        self._at_epoch = at_epoch
        self._flag = flag
        self.reports: list[DrillReport] = []

    def __call__(self, conn: Any, epoch: int) -> None:
        if epoch != self._at_epoch:
            return
        tools.set_autonomy(conn, flag=self._flag, enabled=False)
        self.reports.append(DrillReport(
            drill_name=self.name, epoch=epoch,
            detail=f"withdrew autonomy flag {self._flag!r}",
        ))


class CrashingEnvironment:
    """Brief: "crash at reserve, execute, and settlement boundaries" --
    reframed to the experiment lifecycle's "execute" phase; see the module
    docstring for why. Delegates to `wrapped` for everything except one
    `evaluate` call at `at_epoch`, which raises exactly once."""

    def __init__(self, wrapped: MarketEnvironment, *, at_epoch: int) -> None:
        self._wrapped = wrapped
        self._at_epoch = at_epoch
        self._raised = False
        self.name = wrapped.name
        self.version = wrapped.version
        self.reports: list[DrillReport] = []

    def reset(self, *, seed: int) -> None:
        self._wrapped.reset(seed=seed)

    def observe(self, *, cell_id: str, epoch: int) -> Observation:
        return self._wrapped.observe(cell_id=cell_id, epoch=epoch)

    def evaluate(self, *, experiment: ExperimentAction, epoch: int) -> Outcome:
        if epoch == self._at_epoch and not self._raised:
            self._raised = True
            self.reports.append(DrillReport(
                drill_name="crash_at_execute", epoch=epoch,
                detail=f"raised during evaluate() for cell {experiment.cell_id}",
            ))
            raise RuntimeError(f"chaos drill: simulated crash in evaluate() at epoch {epoch}")
        return self._wrapped.evaluate(experiment=experiment, epoch=epoch)

    def advance(self, *, epoch: int) -> tuple[EnvironmentEvent, ...]:
        return self._wrapped.advance(epoch=epoch)


def verify_post_drill_invariants(conn: Any) -> dict[str, bool]:
    """The brief's shared post-drill checklist, minus "deterministic replay
    from the same seed" (a property of *two runs*, not one connection) and
    "population recovery or explicit extinction" (a judgment call about the
    specific drill's own expectation, made by that drill's own test) --
    what's left is checkable generically from any `conn`, drill-agnostic:
    conservation per book, and the hash chain's own tamper-evidence."""
    conservation = {
        book.value: ledger.verify_conservation(conn, book)
        for book in (Book.USD_REAL, Book.USD_SIM, Book.RESOURCE)
    }
    return {**conservation, "ledger_chain_valid": ledger.verify_chain(conn)}
