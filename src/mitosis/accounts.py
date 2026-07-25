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


def is_known_account(account_id: str) -> bool:
    """True if account_id is one of the fixed colony-level accounts or a
    cell-scoped cash/committed account. Used at the few call sites where a
    caller supplies an account id directly (reservation settlement
    destinations, Cell funding sources) so a typo'd fixed-account name is
    rejected instead of silently opening a new, permanently-unreconciled
    ledger account."""
    if account_id in FIXED_ACCOUNTS:
        return True
    return account_id.startswith("cell:") and (
        account_id.endswith(":cash") or account_id.endswith(":committed")
    )
