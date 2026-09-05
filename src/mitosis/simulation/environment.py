"""Synthetic markets (SPEC.md §8; implementation brief Slice F).

`MarketEnvironment` is the seam the brief specifies almost verbatim: Cells
propose (`policy.py`), and only the environment produces a canonical outcome
(brief requirement F.8, "no hidden outcome authority") -- a Cell's own
`estimated_cost_minor_units`/rationale is a guess, never the truth `evaluate`
returns. Every draw below is a pure function of `(master_seed, name, version,
purpose, epoch, cell_id)` rather than of an environment instance's own mutable
state, so replaying the same seed reproduces the same outcomes regardless of
call order or how many times a method was invoked before.

Only one environment family ships in this slice (F1). Brief requirement F.2
("at least two independently shaped customer/market models so success cannot
depend on one authored rule set") is F2's addition behind this same Protocol.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Protocol

#: A price genuinely absent from a founder's genome still needs somewhere to
#: land -- an environment cannot refuse to evaluate a Cell that hasn't
#: mutated its revenue model yet.
_DEFAULT_PRICE_MINOR_UNITS = 500
_NOISE_MINOR_UNITS = 50


@dataclass(frozen=True)
class Observation:
    """What a Cell's environment currently looks like. Not yet consumed by
    `policy.py` in this slice -- F1's policy decides from genome content alone
    (see `policy.py`'s docstring on why) -- but implemented for real so a
    richer F2 policy has something true to read rather than a stub."""

    epoch: int
    market_price_signal_minor_units: int
    demand_index: float


@dataclass(frozen=True)
class ExperimentAction:
    """What a Cell asked the environment to evaluate. `hypothesis` is the
    Cell's own words (§0.2: the kernel never rewrites what is tested); the
    environment's `evaluate` below decides what happens regardless of what
    the hypothesis claims."""

    cell_id: str
    genome_content: dict[str, Any]
    hypothesis: str


@dataclass(frozen=True)
class Outcome:
    """The canonical result of one evaluated experiment. Nothing here is the
    Cell's to set."""

    purchased: bool
    revenue_minor_units: int
    note: str


@dataclass(frozen=True)
class EnvironmentEvent:
    """A colony-wide happening the environment produced on its own clock
    (regime shifts, F2+) rather than in response to one Cell's action."""

    kind: str
    detail: str


class MarketEnvironment(Protocol):
    name: str
    version: str

    def reset(self, *, seed: int) -> None: ...
    def observe(self, *, cell_id: str, epoch: int) -> Observation: ...
    def evaluate(self, *, experiment: ExperimentAction, epoch: int) -> Outcome: ...
    def advance(self, *, epoch: int) -> tuple[EnvironmentEvent, ...]: ...


def _declared_price(genome_content: dict[str, Any]) -> int:
    revenue_model = genome_content.get("revenue_model")
    if isinstance(revenue_model, dict):
        price = revenue_model.get("price_minor_units")
        if isinstance(price, int) and price > 0:
            return price
    return _DEFAULT_PRICE_MINOR_UNITS


class UtilityMaximizingMarket:
    """Customers buy when their (randomly drawn, bounded) willingness to pay
    meets or exceeds the Cell's declared price (SPEC.md §8's "customer
    preferences and willingness to pay" and "product/market compatibility
    derived from genome fields") -- the brief's own minimum mechanism, kept
    to exactly that for this slice. Delayed settlement, churn, competition,
    and regime shifts are F2's job."""

    name = "utility_maximizing_market"
    version = "1"

    def __init__(self) -> None:
        self._seed: int | None = None

    def reset(self, *, seed: int) -> None:
        self._seed = seed

    def _rng(self, *, purpose: str, epoch: int, cell_id: str) -> random.Random:
        if self._seed is None:
            raise RuntimeError("UtilityMaximizingMarket.reset() must be called before use")
        # A tuple is not an accepted `random.Random` seed type -- a stable
        # string is, and (unlike `hash()`) its seeding does not depend on
        # `PYTHONHASHSEED`, so this reproduces across separate processes.
        return random.Random(f"{self._seed}:{self.name}:{self.version}:{purpose}:{epoch}:{cell_id}")

    def observe(self, *, cell_id: str, epoch: int) -> Observation:
        rng = self._rng(purpose="observe", epoch=epoch, cell_id=cell_id)
        return Observation(
            epoch=epoch,
            market_price_signal_minor_units=_DEFAULT_PRICE_MINOR_UNITS,
            demand_index=rng.uniform(0.3, 0.9),
        )

    def evaluate(self, *, experiment: ExperimentAction, epoch: int) -> Outcome:
        rng = self._rng(purpose="evaluate", epoch=epoch, cell_id=experiment.cell_id)
        price = _declared_price(experiment.genome_content)
        willingness_to_pay = rng.uniform(0.5, 1.5) * _DEFAULT_PRICE_MINOR_UNITS
        purchased = willingness_to_pay >= price
        revenue = 0
        if purchased:
            noise = rng.uniform(-_NOISE_MINOR_UNITS, _NOISE_MINOR_UNITS)
            revenue = max(0, price + int(noise))
        return Outcome(
            purchased=purchased,
            revenue_minor_units=revenue,
            note=(
                f"willingness_to_pay={willingness_to_pay:.0f} vs declared_price={price} "
                f"-> {'purchase' if purchased else 'no sale'}"
            ),
        )

    def advance(self, *, epoch: int) -> tuple[EnvironmentEvent, ...]:
        return ()
