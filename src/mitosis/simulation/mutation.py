"""Seeded mutation operators over the genome schema (SPEC.md §14.1, §16.3;
implementation brief Slice F's "mutation and reproduction").

`lineage.reproduce()` has accepted `mutation: dict | None` and
`mutation_operator: str | None` since migration 0002 and already threads the
operator name through to a real, tested column
(`cell_genomes.mutation_operator`) -- every existing caller just passes
`None` or a fixed one-off string. This module is what finally exercises that
socket with real seeded content: one function per brief-required operator,
each returning `(mutation, operator_name)` for `reproduce()` to consume
unchanged.

Every operator shares one signature -- `(parent_content: dict, *, seed: str)
-> tuple[dict, str]` -- so `runner.py` can dispatch on `OPERATORS[name]`
without a special case per operator. `seed` is a pre-formatted label, not a
bare int: every other seeded draw in this package builds `random.Random`
directly from an f-string (stable across processes, unlike `hash()`), and a
label lets the caller bind the seed to *this* reproduction event (run, epoch,
parent) rather than reusing one value for every mutation in a run.

`genome.inherit()` merges a mutation dict into the parent's content key by
key (`content.update(mutation)`, not a deep merge) -- so an operator that
wants to change one nested field must read the parent's current value for
that top-level key, copy it, and return the *whole* modified copy, or every
other nested field under that key would be silently dropped from the child.

Discrete-choice operators (market segment, delivery mode, acquisition
channel, workflow) exclude the parent's current value from candidates, so
invoking one always changes that field -- the operator's whole identity is
"this field changed," and a fixed candidate set makes guaranteeing that
change free. The two continuous operators (price, temperature) do not retry
for a guaranteed change: any nonzero perturbation already differs in a
continuous space, and the one case where clamping produces no change
(temperature already at a bound, pushed further the same way) is a real,
honestly-recorded outcome rather than a bug to engineer away -- brief:
"whether it created genuinely distinct canonical content" is something to
*record*, not something every call must force to true.

Only the control operator shipped in F1. This is F3's addition: the
remaining five (market/customer, product/delivery, acquisition-channel,
pricing/revenue-model, workflow, model-policy temperature).
"""

from __future__ import annotations

import random
from typing import Any, Callable

from .. import genome as genome_module

#: The one required control/no-op mutation. An empty overlay collapses to the
#: parent's own genome hash by construction (ADR-018) -- the baseline every
#: real variation operator is compared against.
NO_OP_OPERATOR = "control_noop"
MARKET_CUSTOMER_OPERATOR = "market_customer_variation"
PRODUCT_DELIVERY_OPERATOR = "product_delivery_variation"
ACQUISITION_CHANNEL_OPERATOR = "acquisition_channel_variation"
PRICING_REVENUE_MODEL_OPERATOR = "pricing_revenue_model_variation"
WORKFLOW_OPERATOR = "workflow_variation"
MODEL_POLICY_TEMPERATURE_OPERATOR = "model_policy_temperature_variation"

_CUSTOMER_SEGMENTS = ("smb", "enterprise", "consumer", "prosumer", "developer")
_DELIVERY_MODES = ("self_serve", "managed", "api", "white_glove")
_ACQUISITION_CHANNELS = (
    "content_marketing", "paid_search", "partnerships", "direct_sales", "community",
)
#: The kernel's own closed set (ADR-093), in declaration order. It was four
#: names no code read ("sequential" among them); now every value it draws is
#: one `deliberation.deliberate` runs, and a value outside the set would fail
#: genome validation at birth rather than breed a structure nothing honours.
#:
#: **One kernel structure is deliberately not bred (ADR-103).**
#: `self_critique_loop` branches on a keep/revise verdict, and
#: `SimulationPolicyProvider` only ever replies with a proposal — so in the
#: simulator the critique never validates and the structure is a single pass
#: plus one billed call, every time. Breeding it would let selection punish a
#: surcharge the simulator invented, and would make seeded runs depend on
#: whether the optional `langgraph` extra is installed. A founder genome may
#: still declare it; evolution just cannot drift into it here.
_NOT_BRED_STRUCTURES = frozenset({"self_critique_loop"})
_WORKFLOW_STRUCTURES = tuple(
    s for s in genome_module.WORKFLOW_STRUCTURES if s not in _NOT_BRED_STRUCTURES
)

_MIN_PRICE_MINOR_UNITS = 50
_PRICE_MULTIPLIER_RANGE = (0.7, 1.3)
_DEFAULT_PRICE_MINOR_UNITS = 500
_DEFAULT_TEMPERATURE = 0.7
_TEMPERATURE_DELTA_RANGE = (-0.3, 0.3)


def no_op(parent_content: dict[str, Any], *, seed: str) -> tuple[dict[str, Any], str]:
    del parent_content, seed  # unused: a no-op reads nothing and changes nothing
    return {}, NO_OP_OPERATOR


def _choose_different(rng: random.Random, candidates: tuple[str, ...], current: Any) -> str:
    options = [c for c in candidates if c != current] or list(candidates)
    return rng.choice(options)


def market_customer_variation(
    parent_content: dict[str, Any], *, seed: str
) -> tuple[dict[str, Any], str]:
    rng = random.Random(seed)
    market = dict(parent_content.get("market") or {})
    market["segment"] = _choose_different(rng, _CUSTOMER_SEGMENTS, market.get("segment"))
    return {"market": market}, MARKET_CUSTOMER_OPERATOR


def product_delivery_variation(
    parent_content: dict[str, Any], *, seed: str
) -> tuple[dict[str, Any], str]:
    rng = random.Random(seed)
    product = dict(parent_content.get("product") or {})
    product["delivery_mode"] = _choose_different(rng, _DELIVERY_MODES, product.get("delivery_mode"))
    return {"product": product}, PRODUCT_DELIVERY_OPERATOR


def acquisition_channel_variation(
    parent_content: dict[str, Any], *, seed: str
) -> tuple[dict[str, Any], str]:
    rng = random.Random(seed)
    channel = dict(parent_content.get("acquisition_channel") or {})
    channel["channel"] = _choose_different(rng, _ACQUISITION_CHANNELS, channel.get("channel"))
    return {"acquisition_channel": channel}, ACQUISITION_CHANNEL_OPERATOR


def pricing_revenue_model_variation(
    parent_content: dict[str, Any], *, seed: str
) -> tuple[dict[str, Any], str]:
    rng = random.Random(seed)
    revenue_model = dict(parent_content.get("revenue_model") or {})
    current_price = revenue_model.get("price_minor_units")
    if not isinstance(current_price, int) or isinstance(current_price, bool) or current_price <= 0:
        current_price = _DEFAULT_PRICE_MINOR_UNITS
    multiplier = rng.uniform(*_PRICE_MULTIPLIER_RANGE)
    revenue_model["price_minor_units"] = max(
        _MIN_PRICE_MINOR_UNITS, int(current_price * multiplier)
    )
    return {"revenue_model": revenue_model}, PRICING_REVENUE_MODEL_OPERATOR


def workflow_variation(parent_content: dict[str, Any], *, seed: str) -> tuple[dict[str, Any], str]:
    rng = random.Random(seed)
    workflow = dict(parent_content.get("workflow") or {})
    workflow["structure"] = _choose_different(rng, _WORKFLOW_STRUCTURES, workflow.get("structure"))
    return {"workflow": workflow}, WORKFLOW_OPERATOR


def model_policy_temperature_variation(
    parent_content: dict[str, Any], *, seed: str
) -> tuple[dict[str, Any], str]:
    rng = random.Random(seed)
    policy = dict(parent_content.get("model_policy") or {})
    current = policy.get("temperature")
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        current = _DEFAULT_TEMPERATURE
    delta = rng.uniform(*_TEMPERATURE_DELTA_RANGE)
    policy["temperature"] = min(1.0, max(0.0, round(float(current) + delta, 3)))
    return {"model_policy": policy}, MODEL_POLICY_TEMPERATURE_OPERATOR


#: Name -> function, so a caller holding only the name a `SelectionDecision`
#: recorded (a string, deliberately -- see `selection_policy.py`) can dispatch
#: without a per-operator special case.
OPERATORS: dict[str, Callable[..., tuple[dict[str, Any], str]]] = {
    NO_OP_OPERATOR: no_op,
    MARKET_CUSTOMER_OPERATOR: market_customer_variation,
    PRODUCT_DELIVERY_OPERATOR: product_delivery_variation,
    ACQUISITION_CHANNEL_OPERATOR: acquisition_channel_variation,
    PRICING_REVENUE_MODEL_OPERATOR: pricing_revenue_model_variation,
    WORKFLOW_OPERATOR: workflow_variation,
    MODEL_POLICY_TEMPERATURE_OPERATOR: model_policy_temperature_variation,
}
