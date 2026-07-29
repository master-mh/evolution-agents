"""Pricing table (SPEC.md §24.1 pricing-table version; pricing.py)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, strategies as st

from mitosis import money, pricing


def test_cost_is_tokens_times_price_per_mtok():
    # 2000 input @ $5/MTok = $0.010; 1000 output @ $25/MTok = $0.025.
    assert (
        pricing.cost_micro_usd(
            "anthropic", "claude-opus-5", input_tokens=2000, output_tokens=1000
        )
        == 2000 * 5 + 1000 * 25
    )


def test_zero_tokens_costs_nothing():
    assert (
        pricing.cost_micro_usd(
            "anthropic", "claude-opus-5", input_tokens=0, output_tokens=0
        )
        == 0
    )


def test_mock_provider_is_free_so_the_golden_run_never_spends():
    assert (
        pricing.cost_micro_usd("mock", "mock-1", input_tokens=10**6, output_tokens=10**6)
        == 0
    )


def test_unknown_model_fails_closed_rather_than_billing_at_zero():
    with pytest.raises(pricing.UnknownModelError):
        pricing.cost_micro_usd("anthropic", "gpt-4", input_tokens=1, output_tokens=1)
    with pytest.raises(pricing.UnknownModelError):
        pricing.cost_micro_usd("nobody", "mock-1", input_tokens=1, output_tokens=1)


def test_negative_token_counts_are_rejected():
    with pytest.raises(pricing.PricingError):
        pricing.cost_micro_usd(
            "anthropic", "claude-opus-5", input_tokens=-1, output_tokens=0
        )


@pytest.mark.parametrize(
    ("micro", "expected_cents"),
    [
        (0, 0),
        (1, 1),  # a sub-cent charge still costs a cent — rounds up, never down
        (9_999, 1),
        (10_000, 1),
        (10_001, 2),
        (35_000, 4),
    ],
)
def test_micro_usd_rounds_up_to_the_cent(micro, expected_cents):
    assert pricing.micro_usd_to_minor_units(micro) == expected_cents


@given(st.integers(min_value=0, max_value=10**12))
def test_cent_conversion_never_understates_the_real_charge(micro):
    """The fail-closed direction (pricing.py module docstring): the ledger may
    believe slightly more was spent than actually was, never less."""
    cents = pricing.micro_usd_to_minor_units(micro)
    assert cents * 10_000 >= micro
    assert (cents - 1) * 10_000 < micro or micro == 0


def test_prices_are_decimal_not_float():
    """§30.1's money rule: anything that becomes money is Decimal, never
    binary float — a float price would make the cost of a large call
    non-reproducible in the last digit, and the golden run pins costs."""
    price = pricing.get_price("anthropic", "claude-opus-5")
    assert isinstance(price.input_usd_per_mtok, Decimal)
    assert isinstance(price.output_usd_per_mtok, Decimal)


def test_usd_real_minor_unit_is_still_the_cent():
    """Guards the assumption micro_usd_to_minor_units is built on. If USD_REAL
    ever moves off a 2-decimal minor unit, the /10_000 divisor is wrong."""
    assert money.MINOR_UNITS_EXPONENT["USD_REAL"] == 2


def test_pricing_table_version_is_recorded_and_non_empty():
    assert pricing.PRICING_TABLE_VERSION
    assert pricing.known_models("anthropic")
    assert pricing.known_models("nonexistent-provider") == ()
