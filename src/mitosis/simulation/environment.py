"""Synthetic markets (SPEC.md §8; implementation brief Slice F).

`MarketEnvironment` is the seam the brief specifies almost verbatim: Cells
propose (`policy.py`), and only the environment produces a canonical outcome
(brief requirement F.8, "no hidden outcome authority") -- a Cell's own
`estimated_cost_minor_units`/rationale is a guess, never the truth `evaluate`
returns. Every draw below is a pure function of `(master_seed, name, version,
purpose, epoch, cell_id)` rather than of an environment instance's own mutable
state, so replaying the same seed reproduces the same outcomes regardless of
call order or how many times a method was invoked before.

Two independently shaped families ship: `UtilityMaximizingMarket` (F1) compares
a continuous random willingness-to-pay against price; `RuleBasedMarket` (F2)
applies discrete tier rules -- a price band, a genome-declared eligibility
flag per band, and (premium only) a seeded coin flip against a fixed cutoff,
never a smooth distribution. Brief requirement F.2 ("at least two
independently shaped customer/market models so success cannot depend on one
authored rule set") is satisfied by construction: the two mechanisms disagree
on the same genome (see `build_environment`'s tests) rather than being the
same formula with different constants.
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

#: A scheduled regime shift (SPEC.md §8.4: "part of fitness evaluation, not
#: only a test category"), not a random market shock -- every family's shift
#: takes effect on this same colony-wide epoch, deterministically, so a run's
#: own manifest can be reasoned about without re-deriving when a shift lands.
_REGIME_SHIFT_EPOCH = 10


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


#: Pre-shift: willingness to pay is `uniform(0.5, 1.5) * price`. At
#: `_REGIME_SHIFT_EPOCH` a price-compression regime shift narrows this to
#: `uniform(0.3, 0.9) * price` -- buyers who used to sometimes pay well above
#: list price no longer do (SPEC.md §8.4's "demand changes, price
#: compression").
_PRE_SHIFT_WILLINGNESS_RANGE = (0.5, 1.5)
_POST_SHIFT_WILLINGNESS_RANGE = (0.3, 0.9)


class UtilityMaximizingMarket:
    """Customers buy when their (randomly drawn, bounded) willingness to pay
    meets or exceeds the Cell's declared price (SPEC.md §8's "customer
    preferences and willingness to pay" and "product/market compatibility
    derived from genome fields") -- the brief's own minimum mechanism, kept
    to exactly that for this slice. Delayed settlement and competition remain
    unmodelled; a scheduled price-compression regime shift (§8.4) is F2's
    addition."""

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
        willingness_range = (
            _POST_SHIFT_WILLINGNESS_RANGE if epoch >= _REGIME_SHIFT_EPOCH
            else _PRE_SHIFT_WILLINGNESS_RANGE
        )
        willingness_to_pay = rng.uniform(*willingness_range) * _DEFAULT_PRICE_MINOR_UNITS
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
        if epoch == _REGIME_SHIFT_EPOCH:
            return (
                EnvironmentEvent(
                    kind="price_compression",
                    detail=(
                        f"willingness-to-pay range narrows from {_PRE_SHIFT_WILLINGNESS_RANGE} "
                        f"to {_POST_SHIFT_WILLINGNESS_RANGE} starting this epoch"
                    ),
                ),
            )
        return ()


#: Pre-shift the budget tier (always clears) runs up to 300; at
#: `_REGIME_SHIFT_EPOCH` a stricter-enforcement regime shift (SPEC.md §8.4's
#: "platform-fee changes... stricter enforcement") narrows it to 150 --
#: prices that used to clear automatically now fall into the standard band
#: and need the `durable` flag.
_PRE_SHIFT_BUDGET_TIER_MAX_MINOR_UNITS = 300
_POST_SHIFT_BUDGET_TIER_MAX_MINOR_UNITS = 150
_STANDARD_TIER_MAX_MINOR_UNITS = 700
_PREMIUM_DEMAND_THRESHOLD = 0.5


class RuleBasedMarket:
    """The second family (SPEC.md §8.3). Where `UtilityMaximizingMarket`
    compares a continuous random draw against price, every branch here is a
    discrete rule: a price band, a genome-declared boolean flag required to
    clear the standard band, and a premium band gated on a declared quality
    flag plus a fixed-cutoff coin flip rather than a price-sensitive curve.
    Pricing low enough to clear most willingness-to-pay draws (the lever that
    wins in the sibling family) has no equivalent here -- a standard-band
    price without the `durable` flag fails every time, at every price in that
    band, regardless of seed. A scheduled stricter-enforcement regime shift
    (§8.4) narrows the budget band starting at `_REGIME_SHIFT_EPOCH`."""

    name = "rule_based_market"
    version = "1"

    def __init__(self) -> None:
        self._seed: int | None = None

    def reset(self, *, seed: int) -> None:
        self._seed = seed

    def _rng(self, *, purpose: str, epoch: int, cell_id: str) -> random.Random:
        if self._seed is None:
            raise RuntimeError("RuleBasedMarket.reset() must be called before use")
        return random.Random(f"{self._seed}:{self.name}:{self.version}:{purpose}:{epoch}:{cell_id}")

    def observe(self, *, cell_id: str, epoch: int) -> Observation:
        rng = self._rng(purpose="observe", epoch=epoch, cell_id=cell_id)
        return Observation(
            epoch=epoch,
            market_price_signal_minor_units=_STANDARD_TIER_MAX_MINOR_UNITS,
            demand_index=rng.uniform(0.3, 0.9),
        )

    def evaluate(self, *, experiment: ExperimentAction, epoch: int) -> Outcome:
        price = _declared_price(experiment.genome_content)
        product = experiment.genome_content.get("product")
        product = product if isinstance(product, dict) else {}

        budget_tier_max = (
            _POST_SHIFT_BUDGET_TIER_MAX_MINOR_UNITS if epoch >= _REGIME_SHIFT_EPOCH
            else _PRE_SHIFT_BUDGET_TIER_MAX_MINOR_UNITS
        )
        if price <= budget_tier_max:
            return Outcome(
                purchased=True, revenue_minor_units=price,
                note=f"budget tier (price={price}) -- always clears",
            )

        if price <= _STANDARD_TIER_MAX_MINOR_UNITS:
            if product.get("durable") is True:
                return Outcome(
                    purchased=True, revenue_minor_units=price,
                    note=f"standard tier (price={price}) -- durable flag present",
                )
            return Outcome(
                purchased=False, revenue_minor_units=0,
                note=f"standard tier (price={price}) -- no durable flag declared",
            )

        if product.get("quality") != "premium":
            return Outcome(
                purchased=False, revenue_minor_units=0,
                note=f"premium tier (price={price}) -- no premium quality declared",
            )
        rng = self._rng(purpose="premium_demand", epoch=epoch, cell_id=experiment.cell_id)
        purchased = rng.random() < _PREMIUM_DEMAND_THRESHOLD
        return Outcome(
            purchased=purchased, revenue_minor_units=price if purchased else 0,
            note=(
                f"premium tier (price={price}) -- demand roll "
                f"{'cleared' if purchased else 'missed'}"
            ),
        )

    def advance(self, *, epoch: int) -> tuple[EnvironmentEvent, ...]:
        if epoch == _REGIME_SHIFT_EPOCH:
            return (
                EnvironmentEvent(
                    kind="stricter_enforcement",
                    detail=(
                        f"budget tier narrows from <= {_PRE_SHIFT_BUDGET_TIER_MAX_MINOR_UNITS} "
                        f"to <= {_POST_SHIFT_BUDGET_TIER_MAX_MINOR_UNITS} starting this epoch"
                    ),
                ),
            )
        return ()


@dataclass(frozen=True)
class EnvironmentSuite:
    """SPEC.md §8.1's three-way separation as a real config object rather
    than a convention. `training` is the only role the routine epoch loop
    (`runner._run_one_epoch`) ever receives -- its own signature carries one
    `MarketEnvironment`, not a suite, so there is no path by which it could
    call `validation` or `secret_challenge` even by mistake. `validation`
    ("influences capital allocation, partially hidden") has no consumer yet:
    `RandomEligibleSelection` does not look at any environment outcome at all
    by design (see `selection_policy.py`), so wiring a performance-sensitive
    policy to actually consult it is Slice G's job, not this slice's to fake.
    `secret_challenge` ("never available to Cells or routine selection
    logic") is deliberately unused anywhere in this package -- reserved for
    Slice H's held-out evaluation."""

    training: MarketEnvironment
    validation: MarketEnvironment | None = None
    secret_challenge: MarketEnvironment | None = None

    @classmethod
    def training_only(cls, environment: MarketEnvironment) -> "EnvironmentSuite":
        return cls(training=environment)


class UnknownEnvironmentError(Exception):
    pass


def build_environment(name: str) -> MarketEnvironment:
    """A name -> instance factory so a CLI flag or scenario config can select
    a family without importing both concrete classes itself (brief F.2)."""
    if name == UtilityMaximizingMarket.name:
        return UtilityMaximizingMarket()
    if name == RuleBasedMarket.name:
        return RuleBasedMarket()
    raise UnknownEnvironmentError(
        f"no environment family named {name!r}; available: "
        f"{UtilityMaximizingMarket.name}, {RuleBasedMarket.name}"
    )
