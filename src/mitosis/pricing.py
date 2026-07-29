"""Model pricing table (SPEC.md §24.1 `pricing-table version`).

Cost is computed in **micro-USD** (1e-6 USD), not in the USD_REAL book's
minor units. That is deliberate: USD_REAL's minor unit is the cent
(money.MINOR_UNITS_EXPONENT), and a single model call routinely costs a
fraction of a cent — 1,000 input tokens on `claude-opus-5` is 0.5 cents.
Computing in cents would round most individual calls to 0 or 1 and make the
per-call cost meaningless.

So the split is:

- `cost_micro_usd` is the **exact** figure, kept at full precision. It is
  what gets stored on the `model_calls` row (§24.1 `cost estimate` /
  `reconciled cost`) and what the RESOURCE book is shadow-priced in.
- `micro_usd_to_minor_units` rounds **up** to the cent for the USD_REAL
  ledger posting. Rounding up, never down, is the same fail-closed posture
  Charter C5 takes everywhere else: the colony may believe it has spent
  slightly more real money than it has, never less.

The consequence is stated plainly because it is real: at Phase 4 volumes a
sub-cent call is billed as a whole cent, so the ledger overstates real spend
by up to 0.999 cents per call. The exact micro-USD figure on every
`model_calls` row is what a later provider-invoice reconciliation (§24.1's
`reconciled cost`, listed as a Phase 1 future hook) trues up against. Do not
"fix" this by widening USD_REAL's minor unit — §2.6's own reporting example
prints real spend to two decimal places.

Prices are per million tokens, as published. `PRICING_TABLE_VERSION` is
recorded on every model call so a price change is legible as a change in the
accounting rather than as a change in Cell behaviour (§24.2 treats provider
changes as regime changes).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

PRICING_TABLE_VERSION = "2026-07-27"

_MICRO_USD_PER_CENT = 10_000


class PricingError(Exception):
    pass


class UnknownModelError(PricingError):
    pass


class ModelPrice:
    """USD per million tokens, held as Decimal — never float (§30.1 money rule
    applies to anything that becomes money)."""

    __slots__ = ("input_usd_per_mtok", "output_usd_per_mtok")

    def __init__(self, input_usd_per_mtok: str, output_usd_per_mtok: str) -> None:
        self.input_usd_per_mtok = Decimal(input_usd_per_mtok)
        self.output_usd_per_mtok = Decimal(output_usd_per_mtok)


# provider -> model -> price. The mock provider is priced at zero: it makes no
# external call, so it incurs no real charge, and pricing it at zero is what
# keeps `mitosis verify-golden-run` free of USD_REAL movement (§26 replay must
# not depend on a paid API).
PRICING_TABLE: dict[str, dict[str, ModelPrice]] = {
    "mock": {
        "mock-1": ModelPrice("0", "0"),
    },
    "anthropic": {
        "claude-opus-5": ModelPrice("5", "25"),
        "claude-sonnet-5": ModelPrice("3", "15"),
        "claude-haiku-4-5": ModelPrice("1", "5"),
    },
}


def known_models(provider: str) -> tuple[str, ...]:
    return tuple(sorted(PRICING_TABLE.get(provider, {})))


def get_price(provider: str, model: str) -> ModelPrice:
    try:
        return PRICING_TABLE[provider][model]
    except KeyError:
        raise UnknownModelError(
            f"no price for model {model!r} on provider {provider!r} "
            f"(pricing table {PRICING_TABLE_VERSION}); known: "
            f"{known_models(provider) or 'none — unknown provider'}"
        ) from None


def cost_micro_usd(
    provider: str, model: str, *, input_tokens: int, output_tokens: int
) -> int:
    """Exact cost of one model call in micro-USD, rounded up to the whole
    micro-USD. Raises UnknownModelError rather than guessing a price — an
    un-priced model must fail closed, not be silently billed at zero."""
    if input_tokens < 0 or output_tokens < 0:
        raise PricingError(
            f"token counts must be non-negative (got input={input_tokens}, "
            f"output={output_tokens})"
        )
    price = get_price(provider, model)
    # (tokens / 1e6) * usd_per_mtok * 1e6 micro-USD-per-USD — the two factors
    # of a million cancel exactly, so micro-USD is just tokens * price.
    exact = (
        Decimal(input_tokens) * price.input_usd_per_mtok
        + Decimal(output_tokens) * price.output_usd_per_mtok
    )
    return _ceil_decimal(exact)


def parse_micro_usd(amount: str) -> int:
    """Parse a decimal dollar string into exact micro-USD.

    The §30 dollar-string rule with a finer scale: `money.parse_minor_units`
    stops at the cent, which is too coarse for an invoice line — a single
    call routinely costs a fraction of one, and rounding the operator's input
    before it reaches the ledger would defeat the point of reconciling.
    Rejects underscores and non-finite values for the same reasons
    money.py does, and refuses precision finer than a micro-USD rather than
    silently truncating it.
    """
    if "_" in amount:
        raise PricingError(
            f"not a valid decimal string: {amount!r} (underscores not allowed)"
        )
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise PricingError(f"not a valid decimal string: {amount!r}") from exc
    if not value.is_finite():
        raise PricingError(f"not a finite decimal value: {amount!r}")
    scaled = value * 1_000_000
    if scaled != scaled.to_integral_value():
        raise PricingError(
            f"{amount!r} has more precision than micro-USD supports (6 decimal places)"
        )
    result = int(scaled)
    if result < 0:
        raise PricingError(f"{amount!r} is negative; an invoiced cost cannot be")
    return result


def format_micro_usd(micro_usd: int) -> str:
    """Inverse of parse_micro_usd, for display."""
    return str(Decimal(micro_usd) / 1_000_000)


def micro_usd_to_minor_units(micro_usd: int) -> int:
    """Round micro-USD up to whole USD_REAL minor units (cents). See the module
    docstring for why this rounds up rather than to nearest."""
    if micro_usd < 0:
        raise PricingError(f"micro_usd must be non-negative (got {micro_usd})")
    return -(-micro_usd // _MICRO_USD_PER_CENT)


def _ceil_decimal(value: Decimal) -> int:
    integral = int(value)
    return integral if Decimal(integral) == value else integral + 1
