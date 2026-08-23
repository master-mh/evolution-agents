"""Revenue: the first path by which money enters the colony (SPEC.md §31, §2.2).

Until now every USD_REAL movement in MITOSIS was capital being seeded, moved
between internal accounts, or spent. The `revenue` account existed in §31's
fixed-account list and nothing ever posted to it, which meant a Cell's
profitability was not merely unmeasured but *unmeasurable* — the number had no
place to live. This module gives it one.

**Direction and sign.** Revenue mirrors spend exactly. A spend debits the Cell
and credits `external_expense`; revenue debits `revenue` and credits the Cell's
cash. `revenue` therefore accumulates a *negative* balance whose magnitude is
gross earnings, the same convention `external_capital` already uses for seed
capital — an external source is a place value comes from, so it goes negative.
Conservation per book (Charter C2) holds unchanged.

**Revenue is not a spend, and must never be counted as one.** It does not touch
`external_expense`, so it is invisible to the real-spend breaker, and that is
correct: Charter C5's caps bound how much the colony may *spend*, not its net
position. A Cell that earns does not thereby earn permission to exceed the
hour/day/month caps. Earnings do raise its cash balance, so Charter C4 lets it
reserve more — that is the intended and only coupling. Pinned by
`test_revenue_does_not_move_the_spend_breaker`.

**Attribution is required.** Like reconciliation, revenue takes a `source` and
refuses to post without one. An unattributable credit to a Cell is precisely
how a fitness signal gets fabricated, and fitness is what this exists to feed.

**A dead Cell can still receive revenue.** Payment arrives after work, sometimes
after the worker is gone, and a coroner report that omits a Cell's final earnings
would misstate the thing it exists to record. Status is therefore not checked —
but the Cell must exist, so revenue cannot be posted to a typo.

Deliberately out of scope: fitness itself (revenue minus spend is the next
slice, and it needs `ledger.spend_by_book`'s sign bug fixed first — a credited
Cell currently reads as having spent more than it did); recurring or accrued
revenue; anything that fetches money from a real payment processor. The operator
supplies the figure, exactly as with an invoice.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import audit, ledger, lifecycle
from .accounts import cell_cash
from .models import Book, EntrySpec, Transaction

REVENUE_ACCOUNT = "revenue"
REVENUE_TRANSACTION_TYPE = "cell_revenue"

# RESOURCE is a shadow-price book for metering internal consumption (§2.2).
# Nobody pays a colony in compute units, and allowing it would let a Cell's
# RESOURCE budget be topped up by declaring revenue, which is not a thing that
# can happen.
_REVENUE_BOOKS = frozenset({Book.USD_REAL, Book.USD_SIM})


class RevenueError(Exception):
    pass


def record_revenue(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    amount_minor_units: int,
    source: str,
    book: Book = Book.USD_REAL,
    note: str = "",
    artifact_id: str | None = None,
    idempotency_key: str | None = None,
) -> Transaction:
    """Credit a Cell with money it earned.

    `source` records who paid and for what — an invoice id, a customer
    reference, "manual". Stored on the transaction and on the audit event.

    `artifact_id` names **what was sold**, populating Amendment A3's
    `ledger_entries.artifact_id` — a required field that has existed since
    migration 0001 and that nothing populated until the artifact store. It is
    the edge §11.4's contribution graph needs between a Cell's work and the
    money that followed it: without it, attribution is a free-text string and
    fitness cannot see which deliverable earned.

    **Optional, deliberately.** Making it mandatory would force every payment to
    name a deliverable, which is the right pressure for a sale — but not every
    receipt has an artifact behind it (a retainer, a reversal, an operator
    correction), and a required field that people satisfy with a placeholder is
    worse than an honest null. Revisit when something actually sells.

    `idempotency_key` defaults to one derived from the source, so posting the
    same attributed payment twice is refused by the ledger's own idempotency
    rather than silently doubling a Cell's apparent fitness.
    """
    if amount_minor_units <= 0:
        raise RevenueError(
            f"revenue must be positive, got {amount_minor_units} — a refund or "
            "clawback is a separate, signed concept and does not exist yet"
        )
    if book not in _REVENUE_BOOKS:
        raise RevenueError(
            f"cannot record revenue in {book.value}: revenue is money, and "
            f"{Book.RESOURCE.value} is a shadow-price book for metering"
        )
    if not source.strip():
        raise RevenueError(
            "source is required — unattributed revenue is how a fitness signal "
            "gets fabricated"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Inside the write lock so a Cell cannot be killed and reaped between
        # the existence check and the posting.
        cell = lifecycle.get_cell(conn, cell_id)
        if cell is None:
            raise RevenueError(f"no such cell: {cell_id}")

        if artifact_id is not None:
            # Checked inside the lock like everything else here. An attribution
            # to a nonexistent artifact is worse than none: it looks like
            # provenance and points nowhere.
            exists = conn.execute(
                "SELECT 1 FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
            if exists is None:
                raise RevenueError(
                    f"no such artifact: {artifact_id} — revenue cannot be attributed "
                    "to something the colony never made"
                )

        key = idempotency_key or f"{REVENUE_TRANSACTION_TYPE}:{cell_id}:{source.strip()}"
        transaction = ledger._post_transaction_locked(
            conn,
            book=book,
            currency="USD" if book is Book.USD_REAL else book.value,
            transaction_type=REVENUE_TRANSACTION_TYPE,
            idempotency_key=key,
            description=f"revenue for cell {cell_id} from {source.strip()}"
            + (f": {note}" if note else ""),
            entries=[
                EntrySpec(account_id=REVENUE_ACCOUNT, amount_minor_units=-amount_minor_units),
                EntrySpec(
                    account_id=cell_cash(cell_id),
                    amount_minor_units=amount_minor_units,
                    cell_id=cell_id,
                    artifact_id=artifact_id,
                ),
            ],
        )
        audit.record(
            conn,
            event_type="cell_revenue_recorded",
            cell_id=cell_id,
            metadata={
                "amount_minor_units": amount_minor_units,
                "artifact_id": artifact_id,
                "book": book.value,
                "source": source.strip(),
                "note": note,
                "cell_status": cell.status.value,
                "transaction_id": transaction.transaction_id,
            },
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()
    return transaction


def total_revenue(
    conn: sqlite3.Connection,
    cell_id: str,
    book: Book = Book.USD_REAL,
    *,
    since: datetime | None = None,
) -> int:
    """Gross earnings for one Cell, as a positive number.

    Reads the Cell's own positive leg rather than the `revenue` account, because
    the `revenue` account is colony-wide — the per-Cell attribution lives on the
    cell-scoped entry.

    `since` narrows to a window, for §25.2's "what did this rung earn" — and
    filters `created_at_utc` for the same reason `ledger.spend_by_book` does:
    the effective stamp may be simulated, the window boundary is wall-clock.
    """
    window, window_params = (
        ("AND t.created_at_utc > ?", (since.astimezone(timezone.utc).isoformat(),))
        if since is not None
        else ("", ())
    )
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.book = ?
          AND t.transaction_type = ?
          AND e.account_id = ?
          {window}
        """,
        (book.value, REVENUE_TRANSACTION_TYPE, cell_cash(cell_id), *window_params),
    ).fetchone()
    return row["total"]


def colony_revenue(conn: sqlite3.Connection, book: Book = Book.USD_REAL) -> int:
    """Gross colony-wide earnings, as a positive number. The `revenue` account
    holds this negated, per the sign convention in the module docstring."""
    return -ledger.get_balance(conn, REVENUE_ACCOUNT, book)
