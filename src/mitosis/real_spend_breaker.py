"""Global real-spend circuit breaker (SPEC.md §5; Charter C5).

USD_REAL only — this has nothing to do with USD_SIM or RESOURCE. Gates
`reservations.request`, not arbitrary ledger transactions: per the
two-phase-spend model (§4), all real spend is meant to flow through the
reserve step, so that's the one gate that needs to check these caps. An
internal treasury transfer like funding a Cell's cash account is capital
allocation, not spend, and isn't gated here.

Per §5.2: "A Cell cannot override or mutate these limits." There is no
Cell-facing code path that reaches set_limits at all in this kernel (Cells
have no code-execution capability yet — that's Phase 5), so this is
enforced by the absence of such a path rather than a runtime permission
check. "An administrator may lower limits immediately; raising limits
requires explicit human action and an audit event" — set_limits always
requires an explicit call (there's no automatic raise path) and always
emits an audit event, distinguishing a raise from a lower/initial-configure
in the event type so the trail is legible.

"max real spend per provider" (§5.1) is stored (`provider_limits`) but not
enforced — there's no model gateway or provider identification in this
kernel yet (Phase 4).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from . import audit
from .models import DEFAULT_REAL_SPEND_LIMITS, RealSpendLimits, RealSpendSnapshot

_RAISABLE_FIELDS = (
    "per_request_minor_units",
    "per_hour_minor_units",
    "per_day_minor_units",
    "per_month_minor_units",
    "max_concurrent_reserved_minor_units",
)

_MONTH = timedelta(days=30)  # approximation, not a calendar month — documented simplification
_DAY = timedelta(days=1)
_HOUR = timedelta(hours=1)


class RealSpendBreakerError(Exception):
    pass


class RealSpendCapExceededError(RealSpendBreakerError):
    pass


def get_limits(conn: sqlite3.Connection) -> RealSpendLimits:
    row = conn.execute("SELECT * FROM real_spend_limits WHERE id = 1").fetchone()
    if row is None:
        return DEFAULT_REAL_SPEND_LIMITS
    return RealSpendLimits(
        per_request_minor_units=row["per_request_minor_units"],
        per_hour_minor_units=row["per_hour_minor_units"],
        per_day_minor_units=row["per_day_minor_units"],
        per_month_minor_units=row["per_month_minor_units"],
        max_concurrent_reserved_minor_units=row["max_concurrent_reserved_minor_units"],
        provider_limits=json.loads(row["provider_limits_json"]),
    )


def configure_if_absent(conn: sqlite3.Connection) -> RealSpendLimits:
    """Baseline initialization only (e.g. from `mitosis init`) — not an
    audited administrator action. If limits are already configured, they
    are left untouched."""
    conn.execute(
        """
        INSERT OR IGNORE INTO real_spend_limits (
            id, per_request_minor_units, per_hour_minor_units, per_day_minor_units,
            per_month_minor_units, max_concurrent_reserved_minor_units, provider_limits_json
        ) VALUES (1, ?, ?, ?, ?, ?, ?)
        """,
        (
            DEFAULT_REAL_SPEND_LIMITS.per_request_minor_units,
            DEFAULT_REAL_SPEND_LIMITS.per_hour_minor_units,
            DEFAULT_REAL_SPEND_LIMITS.per_day_minor_units,
            DEFAULT_REAL_SPEND_LIMITS.per_month_minor_units,
            DEFAULT_REAL_SPEND_LIMITS.max_concurrent_reserved_minor_units,
            json.dumps(DEFAULT_REAL_SPEND_LIMITS.provider_limits),
        ),
    )
    return get_limits(conn)


def set_limits(conn: sqlite3.Connection, new_limits: RealSpendLimits) -> RealSpendLimits:
    """Explicit administrator adjustment. Always applies; always audited.
    A raise on any field is called out by name in the audit event."""
    current = get_limits(conn)
    raised_fields = [
        name for name in _RAISABLE_FIELDS if getattr(new_limits, name) > getattr(current, name)
    ]
    event_type = "real_spend_limit_raised" if raised_fields else "real_spend_limit_configured"

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO real_spend_limits (
                id, per_request_minor_units, per_hour_minor_units, per_day_minor_units,
                per_month_minor_units, max_concurrent_reserved_minor_units, provider_limits_json
            ) VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                per_request_minor_units = excluded.per_request_minor_units,
                per_hour_minor_units = excluded.per_hour_minor_units,
                per_day_minor_units = excluded.per_day_minor_units,
                per_month_minor_units = excluded.per_month_minor_units,
                max_concurrent_reserved_minor_units = excluded.max_concurrent_reserved_minor_units,
                provider_limits_json = excluded.provider_limits_json
            """,
            (
                new_limits.per_request_minor_units,
                new_limits.per_hour_minor_units,
                new_limits.per_day_minor_units,
                new_limits.per_month_minor_units,
                new_limits.max_concurrent_reserved_minor_units,
                json.dumps(new_limits.provider_limits),
            ),
        )
        audit.record(
            conn,
            event_type=event_type,
            description=f"real-spend limits {event_type.split('_')[-1]}: {new_limits.model_dump(exclude={'provider_limits'})}",
            metadata={
                "before": current.model_dump(),
                "after": new_limits.model_dump(),
                "raised_fields": raised_fields,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return new_limits


def _concurrent_reserved(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(maximum_amount - settled_amount), 0) AS total
        FROM reservations
        WHERE book = 'USD_REAL' AND status NOT IN ('settled', 'released')
        """
    ).fetchone()
    return row["total"]


def _settled_spend_since(conn: sqlite3.Connection, since: datetime) -> int:
    """Sum of the destination-side (positive) entries of USD_REAL
    reservation_settle transactions effective since `since`."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.book = 'USD_REAL'
          AND t.transaction_type = 'reservation_settle'
          AND e.amount_minor_units > 0
          AND t.effective_at_utc >= ?
        """,
        (since.astimezone(timezone.utc).isoformat(),),
    ).fetchone()
    return row["total"]


def snapshot(
    conn: sqlite3.Connection, *, now: datetime | None = None, limits: RealSpendLimits | None = None
) -> RealSpendSnapshot:
    now = now or datetime.now(timezone.utc)
    limits = limits or get_limits(conn)
    return RealSpendSnapshot(
        limits=limits,
        concurrent_reserved_minor_units=_concurrent_reserved(conn),
        spend_last_hour_minor_units=_settled_spend_since(conn, now - _HOUR),
        spend_last_day_minor_units=_settled_spend_since(conn, now - _DAY),
        spend_last_month_minor_units=_settled_spend_since(conn, now - _MONTH),
    )


def check(
    conn: sqlite3.Connection,
    *,
    requested_amount: int,
    now: datetime | None = None,
    limits: RealSpendLimits | None = None,
) -> None:
    """Raise RealSpendCapExceededError if reserving requested_amount now
    would push any cap over its limit. Must be called after the caller has
    already acquired a write lock (BEGIN IMMEDIATE) — see
    reservations.request — so this check is atomic with the reservation
    insert under concurrency (Charter C5).
    """
    now = now or datetime.now(timezone.utc)
    snap = snapshot(conn, now=now, limits=limits)
    limits = snap.limits

    if requested_amount > limits.per_request_minor_units:
        raise RealSpendCapExceededError(
            f"real-spend per-request cap exceeded: {requested_amount} > "
            f"{limits.per_request_minor_units}"
        )

    projected_concurrent = snap.concurrent_reserved_minor_units + requested_amount
    if projected_concurrent > limits.max_concurrent_reserved_minor_units:
        raise RealSpendCapExceededError(
            f"real-spend concurrent-reserved cap exceeded: {projected_concurrent} > "
            f"{limits.max_concurrent_reserved_minor_units}"
        )

    # Per §5.3: caps consider settled spend + currently reserved spend, not
    # only completed charges — an open reservation could settle at any
    # moment, so it counts as immediate exposure against every window.
    windows = (
        ("hour", snap.spend_last_hour_minor_units, limits.per_hour_minor_units),
        ("day", snap.spend_last_day_minor_units, limits.per_day_minor_units),
        ("month", snap.spend_last_month_minor_units, limits.per_month_minor_units),
    )
    for name, settled_in_window, cap in windows:
        projected = settled_in_window + projected_concurrent
        if projected > cap:
            raise RealSpendCapExceededError(
                f"real-spend {name} cap exceeded: {projected} > {cap}"
            )
