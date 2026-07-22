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
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from . import ledger, real_spend_breaker
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
) -> Reservation:
    """requested -> reserved in one atomic step (§4.4): funds move
    cell:{id}:cash -> cell:{id}:committed. Idempotent on idempotency_key.
    """
    existing = get_reservation_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing

    if maximum_amount <= 0:
        raise ReservationError("maximum_amount must be positive")
    if expires_at.tzinfo is None:
        raise ReservationError("expires_at must be timezone-aware UTC (Charter C11)")

    reservation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Checked inside the write-locked transaction, not before it: two
        # concurrent USD_REAL requests must not both pass this check before
        # either commits (Charter C5 under concurrency). USD_SIM/RESOURCE
        # reservations are untouched — the breaker is real-spend only.
        if book == Book.USD_REAL:
            real_spend_breaker.check(conn, requested_amount=maximum_amount, now=now)

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
                idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
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
            ),
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

    conn.execute("BEGIN IMMEDIATE")
    try:
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
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_reservation(conn, reservation_id)
    assert result is not None
    return result


def release(conn: sqlite3.Connection, reservation_id: str) -> Reservation:
    """reserved|execution_unknown|partially_settled|disputed -> released.
    Remaining committed funds (maximum_amount - settled_amount) return to
    cell:{id}:cash.
    """
    reservation = get_reservation(conn, reservation_id)
    if reservation is None:
        raise ReservationError(f"no such reservation: {reservation_id}")
    _check_transition(reservation.status, ReservationStatus.RELEASED)

    remaining = reservation.maximum_amount - reservation.settled_amount

    conn.execute("BEGIN IMMEDIATE")
    try:
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
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_reservation(conn, reservation_id)
    assert result is not None
    return result


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
    reservation = get_reservation(conn, reservation_id)
    if reservation is None:
        raise ReservationError(f"no such reservation: {reservation_id}")
    _check_transition(reservation.status, target)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE reservations SET status = ? WHERE reservation_id = ?",
            (target.value, reservation_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_reservation(conn, reservation_id)
    assert result is not None
    return result
