"""A held seller's working-capital advance (SPEC.md §2.3, §2.5, §28 Phase 9;
ADR-106, ADR-112).

Under a full liability hold, a real sale reaches its seller's cash only when the
refund window closes, while the processor's fee comes out of cash at once
(ADR-106, decision 6). Live, with the operator's 100% / 120-day policy, the
colony's first $9 sale would leave its seller at -80 cents: the one Cell that
had shown its product sells would be the one unable to wake for four months.

**The advance comes from the colony, not from the hold.** `seed_bank` pays the
seller a declared share of what was just held; `liability_reserve` is never
touched, so every refund is still met in full from money set aside for it. The
risk moves from the buyer — who never bore it — to the colony's own capital: a
refunded sale leaves its advance unrepaid, which costs the colony exactly what a
`fund-cell` of the same amount would have. That is the whole downside, and the
policy's per-Cell cap bounds it.

**Three rules, each the answer to a way an advance goes wrong:**

- *Posted in the sale's own transaction*, like the hold, and only for a sale
  posted now — a replay never advances twice, and a policy never reaches back to
  a sale recorded before it.
- *Repaid first when the hold releases* (`liability.release_due`), up to what
  was released — so the colony is paid back from the very money it lent against,
  and the Cell receives only the rest. A release to meet a refund repays nothing:
  that money goes to the buyer.
- *Owed per Cell, not per sale.* What a Cell owes is its advances less its
  repayments, derived from the ledger (§2.5) — so the cap binds across every
  held sale, and a later sale's release repays an earlier refunded sale's advance.

**Capital movement, not revenue or spend.** Both legs sit in accounts
`accounts.py` already classifies — `seed_bank` is capital and a Cell's cash is
its own — so `net_revenue`, `spend_by_book` and §10.5's net contribution never
see an advance. It is not real spend: nothing leaves the colony.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import audit, ids, ledger
from .accounts import cell_cash
from .models import Book, Entry, EntrySpec, Transaction

ADVANCE_TRANSACTION_TYPE = "held_sale_advance"
REPAYMENT_TRANSACTION_TYPE = "held_sale_advance_repayment"
ADVANCE_TRANSACTION_TYPES = (ADVANCE_TRANSACTION_TYPE, REPAYMENT_TRANSACTION_TYPE)

#: "capital staged for allocation to Cells" (`accounts.CAPITAL_ACCOUNTS`) — the
#: account a Cell's birth funding already comes from.
FUNDING_ACCOUNT = "seed_bank"

FULL_BASIS_POINTS = 10_000


class AdvanceError(Exception):
    pass


@dataclass(frozen=True)
class AdvancePolicy:
    policy_id: str
    advance_basis_points: int
    max_outstanding_minor_units: int
    declared_by: str
    declared_at_utc: datetime
    note: str


def declare_policy(
    conn: sqlite3.Connection,
    *,
    advance_basis_points: int,
    max_outstanding_minor_units: int,
    declared_by: str,
    note: str = "",
) -> AdvancePolicy:
    """Declare how much of each held real sale to advance to its seller, and the
    most one Cell may owe. Operator-only; append-only, latest wins; 0 basis
    points withdraws advances. Applies to sales recorded from now on."""
    for name, value in (
        ("advance_basis_points", advance_basis_points),
        ("max_outstanding_minor_units", max_outstanding_minor_units),
    ):
        if not isinstance(value, int) or isinstance(value, bool):
            raise AdvanceError(f"{name} must be an integer, got {value!r}")
    if not 0 <= advance_basis_points <= FULL_BASIS_POINTS:
        raise AdvanceError(
            f"advance_basis_points must be between 0 (no advances) and "
            f"{FULL_BASIS_POINTS} (the whole hold), got {advance_basis_points}"
        )
    if max_outstanding_minor_units < 0:
        raise AdvanceError("max_outstanding_minor_units cannot be negative")
    if not declared_by.strip():
        raise AdvanceError(
            "declared_by is required — an advance policy lends the colony's capital, "
            "and the record must say who chose to"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        previous = current_policy(conn)
        policy_id = ids.new_id()
        conn.execute(
            """
            INSERT INTO held_seller_advance_policies (
                policy_id, advance_basis_points, max_outstanding_minor_units,
                declared_by, declared_at_utc, note
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (policy_id, advance_basis_points, max_outstanding_minor_units,
             declared_by.strip(), datetime.now(timezone.utc).isoformat(), note),
        )
        audit.record(
            conn,
            event_type="advance_policy_declared",
            description=(
                f"held-seller advance: {advance_basis_points / 100:g}% of each held sale, "
                f"at most {max_outstanding_minor_units} owed per Cell "
                f"(declared by {declared_by.strip()})"
            ),
            metadata={
                "policy_id": policy_id,
                "advance_basis_points": advance_basis_points,
                "max_outstanding_minor_units": max_outstanding_minor_units,
                "declared_by": declared_by.strip(),
                "previous_policy_id": previous.policy_id if previous else None,
                "note": note,
            },
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()
    policy = current_policy(conn)
    assert policy is not None
    return policy


def current_policy(conn: sqlite3.Connection) -> AdvancePolicy | None:
    row = conn.execute(
        "SELECT * FROM held_seller_advance_policies ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return AdvancePolicy(
        policy_id=row["policy_id"],
        advance_basis_points=row["advance_basis_points"],
        max_outstanding_minor_units=row["max_outstanding_minor_units"],
        declared_by=row["declared_by"],
        declared_at_utc=datetime.fromisoformat(row["declared_at_utc"]),
        note=row["note"],
    )


def outstanding(conn: sqlite3.Connection, cell_id: str) -> int:
    """What one Cell owes the colony in advances, derived from the ledger (§2.5):
    its advances less its repayments. USD_REAL only — only a real sale is held."""
    return conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.book = ? AND t.transaction_type IN (?, ?) AND e.account_id = ?
        """,
        (Book.USD_REAL.value, *ADVANCE_TRANSACTION_TYPES, cell_cash(cell_id)),
    ).fetchone()["total"]


def _advance_locked(
    conn: sqlite3.Connection, *, payment: Transaction, hold: Transaction
) -> Transaction | None:
    """Advance the declared share of a hold just taken. Caller holds the write
    lock and has posted `hold` for `payment` in the same transaction.

    `None` when nothing is advanced: no policy, a 0% policy, or a Cell already
    owing its cap. The amount rounds *down* — the opposite of the hold, and for
    the same reason: each rounds in the direction that protects someone else's
    money.
    """
    policy = current_policy(conn)
    if policy is None or policy.advance_basis_points == 0:
        return None
    cash_leg = _cash_leg(hold)
    held = -cash_leg.amount_minor_units
    room = policy.max_outstanding_minor_units - outstanding(conn, cash_leg.cell_id)
    amount = min(math.floor(held * policy.advance_basis_points / FULL_BASIS_POINTS), room)
    if amount <= 0:
        return None
    return ledger._post_transaction_locked(
        conn,
        book=payment.book,
        currency=payment.currency,
        transaction_type=ADVANCE_TRANSACTION_TYPE,
        idempotency_key=f"{ADVANCE_TRANSACTION_TYPE}:{payment.transaction_id}",
        description=(
            f"advance {amount} to cell {cash_leg.cell_id} against the hold on "
            f"{payment.transaction_id} (policy {policy.policy_id}); repaid when it releases"
        ),
        entries=[
            EntrySpec(account_id=FUNDING_ACCOUNT, amount_minor_units=-amount,
                      cell_id=cash_leg.cell_id),
            EntrySpec(account_id=cash_leg.account_id, amount_minor_units=amount,
                      cell_id=cash_leg.cell_id),
        ],
    )


def _repay_locked(conn: sqlite3.Connection, *, release: Transaction) -> Transaction | None:
    """Repay what the Cell owes, up to what a window-closed release just paid it.
    Caller holds the write lock. `None` when the Cell owes nothing."""
    cash_leg = _cash_leg(release)
    released = cash_leg.amount_minor_units
    amount = min(outstanding(conn, cash_leg.cell_id), released)
    if amount <= 0:
        return None
    transaction = ledger._post_transaction_locked(
        conn,
        book=release.book,
        currency=release.currency,
        transaction_type=REPAYMENT_TRANSACTION_TYPE,
        idempotency_key=f"{REPAYMENT_TRANSACTION_TYPE}:{release.transaction_id}",
        description=(
            f"repay {amount} of cell {cash_leg.cell_id}'s advances from release "
            f"{release.transaction_id}"
        ),
        entries=[
            EntrySpec(account_id=cash_leg.account_id, amount_minor_units=-amount,
                      cell_id=cash_leg.cell_id),
            EntrySpec(account_id=FUNDING_ACCOUNT, amount_minor_units=amount,
                      cell_id=cash_leg.cell_id),
        ],
    )
    audit.record(
        conn,
        event_type="held_sale_advance_repaid",
        cell_id=cash_leg.cell_id,
        metadata={
            "release_transaction_id": release.transaction_id,
            "amount_minor_units": amount,
            "transaction_id": transaction.transaction_id,
        },
    )
    return transaction


def _cash_leg(transaction: Transaction) -> Entry:
    legs = [
        e for e in transaction.entries
        if e.cell_id is not None and e.account_id == cell_cash(e.cell_id)
    ]
    if len(legs) != 1:  # pragma: no cover - a hold's and a release's shape
        raise AdvanceError(f"{transaction.transaction_id} has no single Cell cash leg")
    return legs[0]
