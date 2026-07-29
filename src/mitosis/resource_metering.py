"""Resource metering (SPEC.md §2.2/§2.3, Amendment A6; Charter C4).

The RESOURCE book (input/output tokens, model calls, CPU/memory-seconds,
browser minutes, network requests, storage byte-days, human minutes,
approval actions) is "metered, not conserved as cash" (§2.3) — but Amendment
A6 requires every metered operation to link to exactly one reservation and
its eventual settlement. This module is that link: `record_usage` requires
an existing, open, RESOURCE-book reservation before it will record anything,
and never lets cumulative recorded usage exceed that reservation's
`maximum_amount` — this is Charter C4 ("Cells cannot overspend their
authorised budget") for the RESOURCE book specifically. The reservation FSM
itself already enforces C4 at settlement time (`reservations.settle` rejects
`settled_amount > maximum_amount`); this module enforces the same ceiling
earlier, at the point resources are actually consumed, so an overspend is
rejected before it happens rather than only caught when someone gets around
to settling.

`total_minor_units` is what a caller passes to `reservations.settle` once an
operation completes — this module deliberately does not call `settle`
itself, since deciding *when* an operation is finished (and which account
receives the consumed resource-credits, e.g. `infrastructure_reserve`) is a
caller decision, the same way `sweeper.py` calls `reservations.settle`
rather than resource_metering owning it.

Deliberately out of scope for this slice: shadow-pricing (converting a raw
physical quantity like token count into `minor_units` — §2.2 "resources may
be shadow-priced for reporting") is a caller responsibility; this module
records whatever `minor_units` figure the caller supplies rather than
computing one. Reconciling recorded usage against actual sandbox/model-
gateway logs (the other half of Amendment A6) isn't possible yet — no
sandbox or model gateway exists in this kernel (Phase 4/5). Issuing a Cell's
initial RESOURCE-book cash balance (so it has something to reserve against)
isn't a new concept either — `create_cell(..., book=Book.RESOURCE)` or a
manual `ledger.post_transaction` already does that generically, the same as
any other book.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import ids, reservations
from .models import Book, ReservationStatus, ResourceType, ResourceUsage


class ResourceMeteringError(Exception):
    pass


class ResourceOverspendError(ResourceMeteringError):
    pass


def _row_to_usage(row: sqlite3.Row) -> ResourceUsage:
    return ResourceUsage(
        usage_id=row["usage_id"],
        cell_id=row["cell_id"],
        reservation_id=row["reservation_id"],
        resource_type=ResourceType(row["resource_type"]),
        quantity=row["quantity"],
        minor_units=row["minor_units"],
        recorded_at_utc=datetime.fromisoformat(row["recorded_at_utc"]),
        idempotency_key=row["idempotency_key"],
        metadata=json.loads(row["metadata_json"]),
    )


def get_usage(conn: sqlite3.Connection, usage_id: str) -> ResourceUsage | None:
    row = conn.execute("SELECT * FROM resource_usage WHERE usage_id = ?", (usage_id,)).fetchone()
    return _row_to_usage(row) if row else None


def get_usage_by_idempotency_key(conn: sqlite3.Connection, idempotency_key: str) -> ResourceUsage | None:
    row = conn.execute(
        "SELECT * FROM resource_usage WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return _row_to_usage(row) if row else None


def total_minor_units(conn: sqlite3.Connection, reservation_id: str) -> int:
    """Sum of minor_units recorded so far against a reservation — pass this
    to reservations.settle(settled_amount=...) once an operation completes."""
    row = conn.execute(
        "SELECT COALESCE(SUM(minor_units), 0) AS total FROM resource_usage WHERE reservation_id = ?",
        (reservation_id,),
    ).fetchone()
    return row["total"]


def usage_by_type(conn: sqlite3.Connection, reservation_id: str) -> dict[str, int]:
    """Physical-unit quantity recorded so far against a reservation, grouped
    by resource_type — the §2.6 reporting breakdown."""
    rows = conn.execute(
        "SELECT resource_type, SUM(quantity) AS q FROM resource_usage "
        "WHERE reservation_id = ? GROUP BY resource_type",
        (reservation_id,),
    ).fetchall()
    return {r["resource_type"]: r["q"] for r in rows}


def total_quantity_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    """Colony-wide physical-unit quantity recorded, grouped by
    resource_type — used by `mitosis status`."""
    rows = conn.execute(
        "SELECT resource_type, SUM(quantity) AS q FROM resource_usage GROUP BY resource_type"
    ).fetchall()
    return {r["resource_type"]: r["q"] for r in rows}


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM resource_usage").fetchone()["n"]


def record_usage(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    reservation_id: str,
    resource_type: ResourceType,
    quantity: int,
    minor_units: int,
    idempotency_key: str,
    metadata: dict | None = None,
) -> ResourceUsage:
    """Record one metered consumption event against an open RESOURCE-book
    reservation. Idempotent on idempotency_key.

    Raises ResourceOverspendError (Charter C4) if this event would push the
    reservation's cumulative recorded minor_units past its maximum_amount —
    checked and inserted inside the same write-locked transaction so two
    concurrent recordings against the same reservation can't both pass the
    check before either commits (the same "check inside BEGIN IMMEDIATE"
    shape as the C5/C9 caps).
    """
    existing = get_usage_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing

    conn.execute("BEGIN IMMEDIATE")
    try:
        usage_id = _record_usage_locked(
            conn,
            cell_id=cell_id,
            reservation_id=reservation_id,
            resource_type=resource_type,
            quantity=quantity,
            minor_units=minor_units,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        if "idempotency_key" in str(exc):
            existing = get_usage_by_idempotency_key(conn, idempotency_key)
            if existing is not None:
                return existing
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_usage(conn, usage_id)
    assert result is not None
    return result


def _record_usage_locked(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    reservation_id: str,
    resource_type: ResourceType,
    quantity: int,
    minor_units: int,
    idempotency_key: str,
    metadata: dict | None = None,
) -> str:
    """Non-transactional core of `record_usage`; returns the usage_id. The
    caller must already hold a write transaction (BEGIN IMMEDIATE) — see
    reservations.py's module docstring for why the gateway needs to meter
    inside the same transaction that settles.

    Idempotency is checked here too rather than only in the wrapper, because
    the wrapper's pre-BEGIN check is an optimisation, not the guard.
    """
    existing = get_usage_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing.usage_id

    if quantity <= 0:
        raise ResourceMeteringError("quantity must be positive")
    if minor_units <= 0:
        raise ResourceMeteringError("minor_units must be positive")

    usage_id = ids.new_id()
    now = datetime.now(timezone.utc)

    # Reservation fetched and validated inside the write lock, not
    # before it: two concurrent recordings against the same reservation
    # must not both pass the status/book/ownership checks before either
    # commits (same "check inside BEGIN IMMEDIATE" shape as the
    # overspend check below, and as the C4/C5/C9 caps elsewhere).
    reservation = reservations.get_reservation(conn, reservation_id)
    if reservation is None:
        raise ResourceMeteringError(f"no such reservation: {reservation_id}")
    if reservation.cell_id != cell_id:
        raise ResourceMeteringError(
            f"reservation {reservation_id} belongs to cell {reservation.cell_id!r}, not {cell_id!r}"
        )
    if reservation.book != Book.RESOURCE:
        raise ResourceMeteringError(
            f"reservation {reservation_id} is book {reservation.book.value!r}, not RESOURCE (Amendment A6)"
        )
    if reservation.status != ReservationStatus.RESERVED:
        # Not just the two terminal statuses (settled/released): once a
        # reservation leaves `reserved` for *any* reason — including
        # partially_settled, whose FSM only permits -> released next
        # (reservations._ALLOWED_TRANSITIONS) — there is no remaining path
        # to settle any further recorded usage, so it would be permanently
        # unlinked from a settlement (Amendment A6). `reserved` is the only
        # state usage may accumulate against.
        raise ResourceMeteringError(
            f"reservation {reservation_id} is {reservation.status.value!r}, not 'reserved' — "
            "cannot record usage against it"
        )

    already_recorded = total_minor_units(conn, reservation_id)
    if already_recorded + minor_units > reservation.maximum_amount:
        raise ResourceOverspendError(
            f"reservation {reservation_id}: recording {minor_units} would bring cumulative "
            f"usage to {already_recorded + minor_units}, exceeding its cap of {reservation.maximum_amount} (Charter C4)"
        )
    conn.execute(
        """
        INSERT INTO resource_usage (
            usage_id, cell_id, reservation_id, resource_type, quantity,
            minor_units, recorded_at_utc, idempotency_key, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            usage_id,
            cell_id,
            reservation_id,
            resource_type.value,
            quantity,
            minor_units,
            now.isoformat(),
            idempotency_key,
            json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
        ),
    )
    return usage_id


def verify_linkage(conn: sqlite3.Connection) -> bool:
    """Amendment A6 completeness check: every resource_usage row must link
    to a RESOURCE-book reservation belonging to the same cell_id. Both are
    already enforced at write time by record_usage; this re-derives the
    invariant directly from the tables (same double-check shape as
    ledger.verify_conservation) so it also catches direct DB tampering."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM resource_usage u
        JOIN reservations r ON r.reservation_id = u.reservation_id
        WHERE r.book != 'RESOURCE' OR r.cell_id != u.cell_id
        """
    ).fetchone()
    return row["n"] == 0
