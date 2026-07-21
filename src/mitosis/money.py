"""Decimal-safe money parsing. Charter C11: all money is integer minor units.

SPEC.md §30 dollar-string parsing rule: decimal strings such as "5.00" must be
parsed with Decimal and converted exactly to integer minor units. Never parse
money through binary float.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

MINOR_UNITS_EXPONENT: dict[str, int] = {
    "USD_REAL": 2,
    "USD_SIM": 2,
    "RESOURCE": 0,
}


def parse_minor_units(amount: str, book: str) -> int:
    """Parse a decimal string into an exact integer count of minor units.

    Raises ValueError if the string isn't a valid decimal or has more
    fractional precision than the book's minor-unit exponent supports.
    """
    if book not in MINOR_UNITS_EXPONENT:
        raise ValueError(f"unknown book: {book!r}")
    exponent = MINOR_UNITS_EXPONENT[book]
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError(f"not a valid decimal string: {amount!r}") from exc

    scale = Decimal(1).scaleb(-exponent)
    scaled = value / scale
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"{amount!r} has more precision than {book} supports "
            f"({exponent} decimal places)"
        )
    return int(scaled)


def format_minor_units(amount_minor_units: int, book: str) -> str:
    """Inverse of parse_minor_units, for display/CLI purposes."""
    if book not in MINOR_UNITS_EXPONENT:
        raise ValueError(f"unknown book: {book!r}")
    exponent = MINOR_UNITS_EXPONENT[book]
    scale = Decimal(1).scaleb(-exponent)
    value = Decimal(amount_minor_units) * scale
    return str(value)
