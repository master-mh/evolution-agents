"""Canonical ledger account identifiers (SPEC.md §31 closing paragraph)."""

from __future__ import annotations

FIXED_ACCOUNTS = frozenset(
    {
        "external_capital",
        "colony_treasury",
        "seed_bank",
        "promotion_pool",
        "infrastructure_reserve",
        "liability_reserve",
        "revenue",
        "external_expense",
    }
)


def cell_cash(cell_id: str) -> str:
    return f"cell:{cell_id}:cash"


def cell_committed(cell_id: str) -> str:
    return f"cell:{cell_id}:committed"
