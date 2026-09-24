"""Liability reserves: a real sale's money held against its refunds until the
window for them closes (SPEC.md §2.3, §10.2, §16.3, §28 Phase 9; ADR-106).

§28 Phase 9 trades with "full liability reserves", and `liability_reserve` — a
§31 Phase-1 account since migration 0001 — had nothing posting to it. So every
real sale landed in its Cell's cash at once and was spendable the same minute,
while the buyer could still take it back for weeks: a refund that arrived after
the Cell had spent the money drove its cash negative with nothing set aside to
meet it.

**A hold is restricted cash, not cost.** The account was classified as a spend
destination before any policy existed ("a provision ... cost, not transfer"),
and ADR-106 moved it to `accounts.CAPITAL_ACCOUNTS` before the first posting.
§2.3 lists "real reserves" beside cash balances on the balance-sheet side, and
§10.2 names "unsettled liability exposure" as a fitness dimension of its own —
counting a hold as spend would fold it into net contribution, the scalar
collapse §10.2 forbids, and would tell a Cell (through `context`) that it had
spent a sale it had only been asked to wait for. So a hold lowers the Cell's
*cash* — Charter C4 then stops it spending held money, which is the whole point
— and leaves `spend_by_book` and `net_revenue` exactly where they were.
`cell_held` reports the exposure beside them.

**Three transactions, each naming the payment** (`provisions_for_transaction_id`,
migration 0042, hash-chained):

- `liability_hold` — posted by `revenue.record_revenue` in the same transaction
  as a USD_REAL sale, when a policy is in force. Cell cash -> `liability_reserve`.
- `liability_release` on a refund or chargeback — `revenue.record_reversal`
  releases up to the reversed amount from the hold before taking it back, so the
  refund is paid from the money set aside for it rather than from the Cell's
  other cash. That is what the reserve is *for*.
- `liability_release` when the window closes — `release_due`, run by an operator
  (`mitosis release-reserves`). Whatever the hold still has goes back to the Cell.

**The policy is a person's.** How much to hold and for how long depend on the
merchant's refund terms and the card networks' chargeback window — facts about
the world the kernel cannot know, and ADR-042's rule is that a figure which
should abstain must not be invented. With no policy declared, nothing is held
and `profit.report` says so; a real sale is never refused, because it has
already happened.

**When a hold ends is derived, never stored** (§2.5): the sale's hash-chained
`created_at_utc` plus the window of the policy in force at the hold's own
instant. A later policy therefore never shortens a hold already taken, and there
is no `held_until` column to disagree with the ledger.

**USD_REAL only.** A refund window is a fact about real card networks. USD_SIM
refunds are the simulator's to model, and holding synthetic money against a
real-world clock would tie the shadow economy to wall time.

Deliberately out of scope, logged in FUTURE_BUILD_HOOKS: a hold released to a
Cell that has since died lands in a dead Cell's cash, as revenue to a dead Cell
already does; and §10.2's exposure is reported, not yet a domination axis.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import audit, ids, ledger
from .accounts import cell_cash
from .models import Book, Entry, EntrySpec, Transaction

LIABILITY_RESERVE_ACCOUNT = "liability_reserve"
HOLD_TRANSACTION_TYPE = "liability_hold"
RELEASE_TRANSACTION_TYPE = "liability_release"

#: Migration 0042's CHECK names the same two; `test_liability.py` pins the pair.
PROVISION_TRANSACTION_TYPES = (HOLD_TRANSACTION_TYPE, RELEASE_TRANSACTION_TYPE)

#: Basis points in a whole sale.
FULL_HOLD_BASIS_POINTS = 10_000

#: The migration's bounds, restated so `declare_policy` refuses with a sentence
#: rather than an IntegrityError. 730 days is two years — longer than any card
#: network's chargeback window, so a larger figure is a typo, not a policy.
MAX_WINDOW_DAYS = 730


class LiabilityError(Exception):
    pass


@dataclass(frozen=True)
class ReservePolicy:
    """What a person said to hold, and for how long."""

    policy_id: str
    hold_basis_points: int
    window_days: int
    declared_by: str
    declared_at_utc: datetime
    note: str


@dataclass(frozen=True)
class Hold:
    """One sale's hold, derived from the ledger on read."""

    payment_transaction_id: str
    hold_transaction_id: str
    cell_id: str
    held_minor_units: int
    #: What the hold still has: `held_minor_units` less every release so far.
    remaining_minor_units: int
    held_until_utc: datetime


# --- the policy ----------------------------------------------------------------


def declare_policy(
    conn: sqlite3.Connection,
    *,
    hold_basis_points: int,
    window_days: int,
    declared_by: str,
    note: str = "",
) -> ReservePolicy:
    """Declare how much of each real sale to hold, and for how many days.

    Operator-only: nothing a Cell can reach calls this. Append-only, latest wins
    by rowid, so every hold stays traceable to the policy it was taken under and
    a change is a new row rather than an edit (§3.6). Applies to sales recorded
    from now on — a policy never reaches back to a sale already posted.
    """
    for name, value in (("hold_basis_points", hold_basis_points), ("window_days", window_days)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise LiabilityError(f"{name} must be an integer, got {value!r}")
    if not 1 <= hold_basis_points <= FULL_HOLD_BASIS_POINTS:
        raise LiabilityError(
            f"hold_basis_points must be between 1 and {FULL_HOLD_BASIS_POINTS} (the whole "
            f"sale), got {hold_basis_points}. There is no reserve-free policy: §28 Phase 9 "
            "trades with full liability reserves"
        )
    if not 1 <= window_days <= MAX_WINDOW_DAYS:
        raise LiabilityError(
            f"window_days must be between 1 and {MAX_WINDOW_DAYS}, got {window_days} — the "
            "days from a sale until it can no longer be refunded or charged back"
        )
    if not declared_by.strip():
        raise LiabilityError(
            "declared_by is required — the record of who chose the policy is what "
            "distinguishes it from one the code invented"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        previous = current_policy(conn)
        policy_id = ids.new_id()
        now = datetime.now(timezone.utc)
        conn.execute(
            """
            INSERT INTO liability_reserve_policies (
                policy_id, hold_basis_points, window_days, declared_by,
                declared_at_utc, note
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (policy_id, hold_basis_points, window_days, declared_by.strip(),
             now.isoformat(), note),
        )
        audit.record(
            conn,
            event_type="liability_policy_declared",
            description=(
                f"liability reserve: hold {hold_basis_points / 100:g}% of each real sale "
                f"for {window_days} days (declared by {declared_by.strip()})"
            ),
            metadata={
                "policy_id": policy_id,
                "hold_basis_points": hold_basis_points,
                "window_days": window_days,
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


def current_policy(conn: sqlite3.Connection) -> ReservePolicy | None:
    """The policy in force, or `None` when nobody has declared one."""
    row = conn.execute(
        "SELECT * FROM liability_reserve_policies ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return _policy(row) if row is not None else None


def policy_history(conn: sqlite3.Connection) -> list[ReservePolicy]:
    """Every policy ever declared, newest first."""
    rows = conn.execute(
        "SELECT * FROM liability_reserve_policies ORDER BY rowid DESC"
    ).fetchall()
    return [_policy(row) for row in rows]


def _policy_at(conn: sqlite3.Connection, instant: datetime) -> ReservePolicy | None:
    """The policy in force at `instant`: the latest declared at or before it.
    ISO-8601 UTC strings order as the instants they name."""
    row = conn.execute(
        """
        SELECT * FROM liability_reserve_policies
        WHERE declared_at_utc <= ?
        ORDER BY rowid DESC LIMIT 1
        """,
        (instant.astimezone(timezone.utc).isoformat(),),
    ).fetchone()
    return _policy(row) if row is not None else None


def _policy(row: sqlite3.Row) -> ReservePolicy:
    return ReservePolicy(
        policy_id=row["policy_id"],
        hold_basis_points=row["hold_basis_points"],
        window_days=row["window_days"],
        declared_by=row["declared_by"],
        declared_at_utc=datetime.fromisoformat(row["declared_at_utc"]),
        note=row["note"],
    )


# --- the postings ----------------------------------------------------------------


def _hold_locked(
    conn: sqlite3.Connection, *, payment: Transaction, cash_leg: Entry
) -> Transaction | None:
    """Hold part of a sale that was just posted, under the policy in force.

    Called by `revenue.record_revenue` inside its own write lock, and only for a
    payment it has just posted — never for a replay, so declaring a policy can
    never reach back and hold a sale recorded before it. Returns `None` when no
    hold applies: a synthetic book, or no policy declared.
    """
    if payment.book is not Book.USD_REAL:
        return None
    policy = current_policy(conn)
    if policy is None:
        return None
    # Rounded up: "full" reserves, so a share never holds a unit less than it says.
    amount = math.ceil(cash_leg.amount_minor_units * policy.hold_basis_points / FULL_HOLD_BASIS_POINTS)
    until = payment.created_at_utc + timedelta(days=policy.window_days)
    return ledger._post_transaction_locked(
        conn,
        book=payment.book,
        currency=payment.currency,
        transaction_type=HOLD_TRANSACTION_TYPE,
        idempotency_key=f"{HOLD_TRANSACTION_TYPE}:{payment.transaction_id}",
        provisions_for_transaction_id=payment.transaction_id,
        # The release date is in the hashed description as a witness a person
        # can read; the code derives it (`held_until`) rather than parsing this.
        description=(
            f"hold {amount} of {payment.transaction_id} for cell {cash_leg.cell_id} "
            f"until {until.date().isoformat()} (policy {policy.policy_id})"
        ),
        entries=_legs(cash_leg, amount, to_reserve=True),
    )


def _release_locked(
    conn: sqlite3.Connection,
    *,
    payment: Transaction,
    cash_leg: Entry,
    amount_minor_units: int,
    idempotency_key: str,
    reason: str,
) -> Transaction:
    return ledger._post_transaction_locked(
        conn,
        book=payment.book,
        currency=payment.currency,
        transaction_type=RELEASE_TRANSACTION_TYPE,
        idempotency_key=idempotency_key,
        provisions_for_transaction_id=payment.transaction_id,
        description=(
            f"release {amount_minor_units} held on {payment.transaction_id} to cell "
            f"{cash_leg.cell_id}: {reason}"
        ),
        entries=_legs(cash_leg, amount_minor_units, to_reserve=False),
    )


def _legs(cash_leg: Entry, amount: int, *, to_reserve: bool) -> list[EntrySpec]:
    """The Cell's cash leg and the reserve leg, both tagged like the sale — so
    `cell_held` can attribute the reserve to a Cell, and §2.6's report can see
    which experiment's sale is held."""
    sign = 1 if to_reserve else -1
    return [
        EntrySpec(
            account_id=cash_leg.account_id,
            amount_minor_units=-sign * amount,
            cell_id=cash_leg.cell_id,
            experiment_id=cash_leg.experiment_id,
            artifact_id=cash_leg.artifact_id,
        ),
        EntrySpec(
            account_id=LIABILITY_RESERVE_ACCOUNT,
            amount_minor_units=sign * amount,
            cell_id=cash_leg.cell_id,
            experiment_id=cash_leg.experiment_id,
            artifact_id=cash_leg.artifact_id,
        ),
    ]


def _held_remaining_locked(conn: sqlite3.Connection, payment_transaction_id: str) -> int:
    """What one sale's hold still has. Read inside the caller's write lock, so a
    refund and the window's release racing for the same hold cannot both see it."""
    return conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.provisions_for_transaction_id = ? AND e.account_id = ?
        """,
        (payment_transaction_id, LIABILITY_RESERVE_ACCOUNT),
    ).fetchone()["total"]


def _release_for_reversal_locked(
    conn: sqlite3.Connection,
    *,
    payment: Transaction,
    cash_leg: Entry,
    amount_minor_units: int,
    reversal_key: str,
) -> Transaction | None:
    """Before a refund or chargeback takes money back, free up to that much of
    the sale's hold, so the reversal is paid from the money set aside for it.
    `None` when the sale holds nothing (no policy then, or already released)."""
    held = _held_remaining_locked(conn, payment.transaction_id)
    if held <= 0:
        return None
    return _release_locked(
        conn,
        payment=payment,
        cash_leg=cash_leg,
        amount_minor_units=min(held, amount_minor_units),
        idempotency_key=f"{RELEASE_TRANSACTION_TYPE}:{payment.transaction_id}:{reversal_key}",
        reason="to meet a reversal of the sale",
    )


def release_due(conn: sqlite3.Connection, *, now: datetime | None = None) -> list[Transaction]:
    """Release every hold whose window has closed. Idempotent: a hold already
    released posts nothing, so running this twice, or after a crash, is safe.

    `now` is wall-clock by default because a refund window is: it closes on a
    calendar date whatever the colony's simulated clock says.
    """
    now = now or datetime.now(timezone.utc)
    released: list[Transaction] = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        for hold in _holds_locked(conn):
            if hold.remaining_minor_units <= 0 or hold.held_until_utc > now:
                continue
            payment = ledger.get_transaction(conn, hold.payment_transaction_id)
            assert payment is not None  # foreign key
            transaction = _release_locked(
                conn,
                payment=payment,
                cash_leg=_cash_leg(payment),
                amount_minor_units=hold.remaining_minor_units,
                idempotency_key=f"{RELEASE_TRANSACTION_TYPE}:{payment.transaction_id}:window_closed",
                reason=f"refund window closed {hold.held_until_utc.date().isoformat()}",
            )
            audit.record(
                conn,
                event_type="liability_released",
                cell_id=hold.cell_id,
                metadata={
                    "payment_transaction_id": hold.payment_transaction_id,
                    "amount_minor_units": hold.remaining_minor_units,
                    "held_until_utc": hold.held_until_utc.isoformat(),
                    "transaction_id": transaction.transaction_id,
                },
            )
            released.append(transaction)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()
    return released


# --- reading -----------------------------------------------------------------------


def holds(conn: sqlite3.Connection) -> list[Hold]:
    """Every sale ever held, oldest first, with what each still has."""
    return _holds_locked(conn)


def held_until(conn: sqlite3.Connection, hold: Transaction) -> datetime:
    """When a hold's window closes: its sale's instant plus the window of the
    policy in force when the hold was taken (§2.5 — derived, never stored)."""
    policy = _policy_at(conn, hold.created_at_utc)
    if policy is None:  # pragma: no cover - a hold is only posted under a policy
        raise LiabilityError(f"no policy was in force for hold {hold.transaction_id}")
    payment = ledger.get_transaction(conn, hold.provisions_for_transaction_id)
    assert payment is not None  # foreign key
    return payment.created_at_utc + timedelta(days=policy.window_days)


def cell_held(conn: sqlite3.Connection, cell_id: str, book: Book = Book.USD_REAL) -> int:
    """§10.2's "unsettled liability exposure" for one Cell: what its sales still
    hold. Reported beside net contribution, never subtracted from it."""
    return conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.book = ? AND e.account_id = ? AND e.cell_id = ?
        """,
        (book.value, LIABILITY_RESERVE_ACCOUNT, cell_id),
    ).fetchone()["total"]


def colony_held(conn: sqlite3.Connection, book: Book = Book.USD_REAL) -> int:
    """What the whole colony holds against refunds, in one book."""
    return ledger.get_balance(conn, LIABILITY_RESERVE_ACCOUNT, book)


def _holds_locked(conn: sqlite3.Connection) -> list[Hold]:
    rows = conn.execute(
        """
        SELECT t.transaction_id FROM ledger_transactions t
        WHERE t.transaction_type = ?
        ORDER BY t.rowid
        """,
        (HOLD_TRANSACTION_TYPE,),
    ).fetchall()
    result = []
    for row in rows:
        hold = ledger.get_transaction(conn, row["transaction_id"])
        assert hold is not None and hold.provisions_for_transaction_id is not None
        reserve_leg = next(e for e in hold.entries if e.account_id == LIABILITY_RESERVE_ACCOUNT)
        result.append(
            Hold(
                payment_transaction_id=hold.provisions_for_transaction_id,
                hold_transaction_id=hold.transaction_id,
                cell_id=reserve_leg.cell_id,
                held_minor_units=reserve_leg.amount_minor_units,
                remaining_minor_units=_held_remaining_locked(
                    conn, hold.provisions_for_transaction_id
                ),
                held_until_utc=held_until(conn, hold),
            )
        )
    return result


def _cash_leg(payment: Transaction) -> Entry:
    legs = [
        e for e in payment.entries
        if e.cell_id is not None and e.account_id == cell_cash(e.cell_id)
    ]
    if len(legs) != 1:  # pragma: no cover - a revenue payment's shape
        raise LiabilityError(f"{payment.transaction_id} has no single Cell cash leg")
    return legs[0]
