"""Reservations: canonical FSM (SPEC.md §4.4, Amendment A4;
docs/STATE_MACHINES.md §2).

Every ledger-affecting transition posts its ledger transaction and updates
`reservations.status` inside a single SQLite write transaction, so a crash
between the two is impossible to observe: either both happened or neither
did (Charter C7). The FSM adjacency table below both enforces valid
transitions *and* doubles as the idempotency guard for these operations —
once a reservation leaves `reserved`/`execution_unknown`/`disputed`, the
same operation retried against the new (terminal-ish) status is rejected
rather than replayed.

`settle`/`release`/`mark_*` each pair a `_*_locked` core with a thin wrapper
that owns the BEGIN/COMMIT, the same split `ledger._write_transaction` uses.
The cores exist because that C7 guarantee only covers *one* reservation: a
caller resolving several at once (gateway.py settles a USD_REAL and a
RESOURCE reservation, meters, mirrors and records a model call for a single
paid call) needs all of it inside one transaction, or a crash mid-sequence
leaves money half-moved with no way to tell which half.

`request()` enforces Charter C4 ("Cells cannot overspend their authorised
budget") at the point of reservation, across all three books: a Cell may
never reserve more than currently sits in its own cell:{id}:cash. This is
the AUTHORISE step SPEC.md §4.1's protocol names (REQUEST -> AUTHORISE ->
RESERVE -> EXECUTE -> SETTLE) — §4.4 licenses collapsing requested->reserved
into one atomic step, but that collapse must not also mean skipping the
budget check AUTHORISE stands for. Checked inside the same BEGIN IMMEDIATE
as the real-spend-breaker check, for the same reason: two concurrent
requests against the same cell must not both pass before either commits.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import accounts, ids, ledger, real_spend_breaker
from .accounts import cell_cash, cell_committed
from .models import Book, EntrySpec, Reservation, ReservationStatus

_ALLOWED_TRANSITIONS: dict[ReservationStatus, frozenset[ReservationStatus]] = {
    ReservationStatus.RESERVED: frozenset(
        {
            ReservationStatus.SETTLED,
            ReservationStatus.PARTIALLY_SETTLED,
            ReservationStatus.RELEASED,
            ReservationStatus.EXECUTION_UNKNOWN,
        }
    ),
    ReservationStatus.EXECUTION_UNKNOWN: frozenset(
        {
            ReservationStatus.SETTLED,
            ReservationStatus.PARTIALLY_SETTLED,
            ReservationStatus.RELEASED,
            ReservationStatus.DISPUTED,
        }
    ),
    ReservationStatus.PARTIALLY_SETTLED: frozenset({ReservationStatus.RELEASED}),
    ReservationStatus.DISPUTED: frozenset(
        {ReservationStatus.SETTLED, ReservationStatus.RELEASED}
    ),
}


class ReservationError(Exception):
    pass


class InvalidTransitionError(ReservationError):
    pass


class InsufficientBalanceError(ReservationError):
    pass


def _check_transition(current: ReservationStatus, target: ReservationStatus) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidTransitionError(
            f"cannot transition reservation from {current.value!r} to {target.value!r}"
        )


def _row_to_reservation(row: sqlite3.Row) -> Reservation:
    return Reservation(
        reservation_id=row["reservation_id"],
        cell_id=row["cell_id"],
        experiment_id=row["experiment_id"],
        book=Book(row["book"]),
        currency=row["currency"],
        maximum_amount=row["maximum_amount"],
        settled_amount=row["settled_amount"],
        reserved_at=datetime.fromisoformat(row["reserved_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        external_operation_type=row["external_operation_type"],
        external_operation_id=row["external_operation_id"],
        status=ReservationStatus(row["status"]),
        idempotency_key=row["idempotency_key"],
        provider=row["provider"],
    )


def get_reservation(conn: sqlite3.Connection, reservation_id: str) -> Reservation | None:
    row = conn.execute(
        "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
    ).fetchone()
    return _row_to_reservation(row) if row else None


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM reservations GROUP BY status"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def get_reservation_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> Reservation | None:
    row = conn.execute(
        "SELECT * FROM reservations WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return _row_to_reservation(row) if row else None


def request(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    book: Book,
    currency: str,
    maximum_amount: int,
    expires_at: datetime,
    idempotency_key: str,
    experiment_id: str | None = None,
    external_operation_type: str | None = None,
    external_operation_id: str | None = None,
    provider: str | None = None,
) -> Reservation:
    """requested -> reserved in one atomic step (§4.4): funds move
    cell:{id}:cash -> cell:{id}:committed. Idempotent on idempotency_key.

    `provider` tags the reservation for §5.1's per-provider real-spend cap
    and is set only by the model gateway.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        reservation = _request_locked(
            conn,
            cell_id=cell_id,
            book=book,
            currency=currency,
            maximum_amount=maximum_amount,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            experiment_id=experiment_id,
            external_operation_type=external_operation_type,
            external_operation_id=external_operation_id,
            provider=provider,
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        if "idempotency_key" in str(exc):
            existing = get_reservation_by_idempotency_key(conn, idempotency_key)
            if existing is not None:
                return existing
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return reservation


def _request_locked(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    book: Book,
    currency: str,
    maximum_amount: int,
    expires_at: datetime,
    idempotency_key: str,
    experiment_id: str | None = None,
    external_operation_type: str | None = None,
    external_operation_id: str | None = None,
    provider: str | None = None,
) -> Reservation:
    """Non-transactional core of `request`. Caller holds the write lock.

    Extracted so a caller with nothing to keep *outside* a transaction can fold
    the reservation into its own atomic step — `external_actions.claim` consumes
    a grant, claims a counterparty and reserves the human minutes together, and
    a partially-applied version of that is either a held counterparty with
    nothing metered behind it or a charge against a claim nobody holds.

    The gateway and the tool surface deliberately do **not** use this: ADR-022
    requires their reservation to be committed *before* anything leaves the
    machine, so for them a separate transaction is the guarantee rather than a
    limitation. The difference is that this path makes no external call at all.
    """
    existing = get_reservation_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing

    if maximum_amount <= 0:
        raise ReservationError("maximum_amount must be positive")
    if expires_at.tzinfo is None:
        raise ReservationError("expires_at must be timezone-aware UTC (Charter C11)")

    reservation_id = ids.new_id()
    now = datetime.now(timezone.utc)

    # Checked inside the write-locked transaction, not before it: two
    # concurrent USD_REAL requests must not both pass this check before
    # either commits (Charter C5 under concurrency). USD_SIM/RESOURCE
    # reservations are untouched — the breaker is real-spend only.
    if book == Book.USD_REAL:
        real_spend_breaker.check(
            conn, requested_amount=maximum_amount, now=now, provider=provider
        )

    # Charter C4, all books: a Cell cannot reserve more than it
    # currently holds in cash. Checked under the same write lock as the
    # C5 breaker above, for the same concurrency reason.
    available = ledger.get_balance(conn, cell_cash(cell_id), book)
    if maximum_amount > available:
        raise InsufficientBalanceError(
            f"cell {cell_id} has {available} available in {book.value}, "
            f"cannot reserve {maximum_amount} (Charter C4)"
        )

    ledger._write_transaction(
        conn,
        book=book,
        currency=currency,
        transaction_type="reservation_reserve",
        idempotency_key=f"reservation_reserve:{reservation_id}",
        description=f"reserve {maximum_amount} for cell {cell_id}",
        entries=[
            EntrySpec(
                account_id=cell_cash(cell_id),
                amount_minor_units=-maximum_amount,
                cell_id=cell_id,
                experiment_id=experiment_id,
            ),
            EntrySpec(
                account_id=cell_committed(cell_id),
                amount_minor_units=maximum_amount,
                cell_id=cell_id,
                experiment_id=experiment_id,
            ),
        ],
    )
    conn.execute(
        """
        INSERT INTO reservations (
            reservation_id, cell_id, experiment_id, book, currency,
            maximum_amount, settled_amount, reserved_at, expires_at,
            external_operation_type, external_operation_id, status,
            idempotency_key, provider
        ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reservation_id,
            cell_id,
            experiment_id,
            book.value,
            currency,
            maximum_amount,
            now.isoformat(),
            expires_at.astimezone(timezone.utc).isoformat(),
            external_operation_type,
            external_operation_id,
            ReservationStatus.RESERVED.value,
            idempotency_key,
            provider,
        ),
    )

    result = get_reservation(conn, reservation_id)
    assert result is not None
    return result


def settle(
    conn: sqlite3.Connection,
    reservation_id: str,
    *,
    settled_amount: int,
    destination_account_id: str,
) -> Reservation:
    """reserved|execution_unknown|disputed -> settled (settled_amount ==
    maximum_amount) or partially_settled (settled_amount < maximum_amount).
    committed -> destination_account_id.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        _settle_locked(
            conn,
            reservation_id,
            settled_amount=settled_amount,
            destination_account_id=destination_account_id,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_reservation(conn, reservation_id)
    assert result is not None
    return result


def _settle_locked(
    conn: sqlite3.Connection,
    reservation_id: str,
    *,
    settled_amount: int,
    destination_account_id: str,
) -> None:
    """Non-transactional core of `settle`. Caller holds the write lock."""
    if not accounts.is_known_account(destination_account_id):
        raise ReservationError(
            f"unrecognized destination_account_id: {destination_account_id!r} "
            "(not a fixed account or cell:{id}:cash|committed)"
        )

    # Fetched and re-validated inside the write lock (not before it): two
    # concurrent settle() calls against the same reservation must not
    # both decide against the pre-lock status.
    reservation = get_reservation(conn, reservation_id)
    if reservation is None:
        raise ReservationError(f"no such reservation: {reservation_id}")
    if settled_amount < 0 or settled_amount > reservation.maximum_amount:
        raise ReservationError(
            f"settled_amount {settled_amount} out of range "
            f"[0, {reservation.maximum_amount}]"
        )
    is_full = settled_amount == reservation.maximum_amount
    target = ReservationStatus.SETTLED if is_full else ReservationStatus.PARTIALLY_SETTLED
    _check_transition(reservation.status, target)

    if settled_amount > 0:
        ledger._write_transaction(
            conn,
            book=reservation.book,
            currency=reservation.currency,
            transaction_type="reservation_settle",
            idempotency_key=f"reservation_settle:{reservation_id}:{settled_amount}",
            description=f"settle {settled_amount} of reservation {reservation_id}",
            entries=[
                EntrySpec(
                    account_id=cell_committed(reservation.cell_id),
                    amount_minor_units=-settled_amount,
                    cell_id=reservation.cell_id,
                    experiment_id=reservation.experiment_id,
                ),
                EntrySpec(
                    account_id=destination_account_id,
                    amount_minor_units=settled_amount,
                    cell_id=reservation.cell_id,
                    experiment_id=reservation.experiment_id,
                ),
            ],
        )
    conn.execute(
        "UPDATE reservations SET status = ?, settled_amount = ? WHERE reservation_id = ?",
        (target.value, settled_amount, reservation_id),
    )


def release(conn: sqlite3.Connection, reservation_id: str) -> Reservation:
    """reserved|execution_unknown|partially_settled|disputed -> released.
    Remaining committed funds (maximum_amount - settled_amount) return to
    cell:{id}:cash.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        _release_locked(conn, reservation_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_reservation(conn, reservation_id)
    assert result is not None
    return result


def _release_locked(conn: sqlite3.Connection, reservation_id: str) -> None:
    """Non-transactional core of `release`. Caller holds the write lock."""
    # Fetched and re-validated inside the write lock — same reasoning
    # as settle() above.
    reservation = get_reservation(conn, reservation_id)
    if reservation is None:
        raise ReservationError(f"no such reservation: {reservation_id}")
    _check_transition(reservation.status, ReservationStatus.RELEASED)

    remaining = reservation.maximum_amount - reservation.settled_amount

    if remaining > 0:
        ledger._write_transaction(
            conn,
            book=reservation.book,
            currency=reservation.currency,
            transaction_type="reservation_release",
            idempotency_key=f"reservation_release:{reservation_id}",
            description=f"release {remaining} from reservation {reservation_id}",
            entries=[
                EntrySpec(
                    account_id=cell_committed(reservation.cell_id),
                    amount_minor_units=-remaining,
                    cell_id=reservation.cell_id,
                    experiment_id=reservation.experiment_id,
                ),
                EntrySpec(
                    account_id=cell_cash(reservation.cell_id),
                    amount_minor_units=remaining,
                    cell_id=reservation.cell_id,
                    experiment_id=reservation.experiment_id,
                ),
            ],
        )
    conn.execute(
        "UPDATE reservations SET status = ? WHERE reservation_id = ?",
        (ReservationStatus.RELEASED.value, reservation_id),
    )


def mark_execution_unknown(conn: sqlite3.Connection, reservation_id: str) -> Reservation:
    """reserved -> execution_unknown. No ledger movement: funds stay
    committed until reconciliation resolves the uncertainty (Charter C7).
    """
    return _bare_status_transition(conn, reservation_id, ReservationStatus.EXECUTION_UNKNOWN)


def mark_disputed(conn: sqlite3.Connection, reservation_id: str) -> Reservation:
    """execution_unknown -> disputed. No ledger movement."""
    return _bare_status_transition(conn, reservation_id, ReservationStatus.DISPUTED)


def _bare_status_transition(
    conn: sqlite3.Connection, reservation_id: str, target: ReservationStatus
) -> Reservation:
    conn.execute("BEGIN IMMEDIATE")
    try:
        _bare_status_transition_locked(conn, reservation_id, target)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_reservation(conn, reservation_id)
    assert result is not None
    return result


def _bare_status_transition_locked(
    conn: sqlite3.Connection, reservation_id: str, target: ReservationStatus
) -> None:
    """Non-transactional core of `_bare_status_transition`. Caller holds the
    write lock."""
    # Fetched and re-validated inside the write lock — same reasoning
    # as settle()/release() above.
    reservation = get_reservation(conn, reservation_id)
    if reservation is None:
        raise ReservationError(f"no such reservation: {reservation_id}")
    _check_transition(reservation.status, target)

    conn.execute(
        "UPDATE reservations SET status = ? WHERE reservation_id = ?",
        (target.value, reservation_id),
    )
