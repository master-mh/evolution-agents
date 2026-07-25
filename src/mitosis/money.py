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

# SQLite's INTEGER column is a signed 64-bit int (§30's ledger_entries /
# reservations columns store amount_minor_units as INTEGER) — reject
# anything that wouldn't fit at parse time with a clean ValueError, rather
# than letting it surface as an OverflowError deep in ledger._write_transaction.
_SQLITE_INTEGER_BOUND = 2**63 - 1


def parse_minor_units(amount: str, book: str) -> int:
    """Parse a decimal string into an exact integer count of minor units.

    Raises ValueError if the string isn't a valid, finite decimal; has more
    fractional precision than the book's minor-unit exponent supports; or
    doesn't fit in a signed 64-bit integer. Underscore digit separators
    (e.g. "5_0", valid Python/Decimal literal syntax) are rejected outright
    — a typo'd separator silently changing a dollar amount by 10x is worse
    than requiring a plain decimal string.
    """
    if book not in MINOR_UNITS_EXPONENT:
        raise ValueError(f"unknown book: {book!r}")
    if "_" in amount:
        raise ValueError(f"not a valid decimal string: {amount!r} (underscores not allowed)")
    exponent = MINOR_UNITS_EXPONENT[book]
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError(f"not a valid decimal string: {amount!r}") from exc
    if not value.is_finite():
        raise ValueError(f"not a finite decimal value: {amount!r}")

    scale = Decimal(1).scaleb(-exponent)
    scaled = value / scale
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"{amount!r} has more precision than {book} supports "
            f"({exponent} decimal places)"
        )
    result = int(scaled)
    if abs(result) > _SQLITE_INTEGER_BOUND:
        raise ValueError(f"{amount!r} is too large to represent as minor units")
    return result


def format_minor_units(amount_minor_units: int, book: str) -> str:
    """Inverse of parse_minor_units, for display/CLI purposes."""
    if book not in MINOR_UNITS_EXPONENT:
        raise ValueError(f"unknown book: {book!r}")
    exponent = MINOR_UNITS_EXPONENT[book]
    scale = Decimal(1).scaleb(-exponent)
    value = Decimal(amount_minor_units) * scale
    return str(value)
