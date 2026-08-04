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


# --- Spend vs capital (SPEC.md §31; the distinction §31's list does not draw) --
#
# "What did this Cell spend?" cannot be answered from the account list alone,
# because value leaving a Cell's control means two different things depending on
# where it lands. Settling a reservation into `infrastructure_reserve` is the
# Cell *consuming* metered compute — real spend from its own point of view, even
# though the money never left the colony. Returning surplus to `colony_treasury`
# is the opposite: capital going back, not cost incurred.
#
# The distinction is therefore **consumption versus capital movement**, not
# internal versus external. Drawing it wrong in either direction corrupts
# fitness: count capital returns as spend and a frugal Cell looks wasteful;
# miss a consumption account and a wasteful one looks frugal.
#
# Each account carries its reason, and `unclassified_accounts()` fails loudly on
# any that is neither — so adding an account to §31's list forces this decision
# instead of silently defaulting to "not spend".

SPEND_DESTINATIONS: dict[str, str] = {
    "external_expense": "value consumed outside the colony — a provider charge",
    "infrastructure_reserve": (
        "metered compute/infrastructure the Cell consumed and paid the colony "
        "for; internal to the colony but genuine cost to the Cell"
    ),
    "liability_reserve": "a provision the Cell's activity incurred — cost, not transfer",
}

CAPITAL_ACCOUNTS: dict[str, str] = {
    "external_capital": "capital entering or leaving the colony's balance sheet",
    "colony_treasury": "the colony's own pot — funding out, surplus back",
    "seed_bank": "capital staged for allocation to Cells",
    "promotion_pool": "capital held for §25 promotion — redistributed, never consumed",
    "revenue": "money earned; a Cell posting here would be un-earning, not spending",
}


def unclassified_accounts() -> frozenset[str]:
    """Fixed accounts that are neither a spend destination nor a capital
    account. Non-empty means `ledger.spend_by_book` would silently treat a new
    account as non-spend, which is how a fitness signal goes quietly wrong."""
    return FIXED_ACCOUNTS - set(SPEND_DESTINATIONS) - set(CAPITAL_ACCOUNTS)


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
