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

"max real spend per provider" (§5.1) **is** enforced, as of the model gateway
slice: `check(..., provider=...)` compares that provider's own exposure
(settled spend in the month window + currently reserved) against
`provider_limits[provider]`. A provider with no entry in `provider_limits` is
uncapped by that check — the global caps still apply — because inventing a
default cap for an unlisted provider would fail closed on a colony that has
simply not configured one. Reservations carry the provider tag
(`reservations.provider`, migration 0010); only the gateway sets it.

Not every real charge has a provider to cap. A payment fee (ADR-098) is taken by
a processor nothing ever reserves against, so it is counted by the global
windows and by no provider's: `_PROVIDERLESS_REAL_SPEND_TYPES`.
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


def _concurrent_reserved_for_provider(conn: sqlite3.Connection, provider: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(maximum_amount - settled_amount), 0) AS total
        FROM reservations
        WHERE book = 'USD_REAL' AND provider = ? AND status NOT IN ('settled', 'released')
        """,
        (provider,),
    ).fetchone()
    return row["total"]


def _settled_spend_for_provider_since(
    conn: sqlite3.Connection, provider: str, since: datetime
) -> int:
    """Per-provider analogue of _settled_spend_since.

    Two routes to the provider, both required, because a transaction does not
    carry a provider tag itself. Ordinary settlements are reached through the
    reservation's `provider` column. The directly-posted charges — a cost
    overrun (gateway) and a reconciliation adjustment (reconciliation.py) —
    are **not** settlements against a reservation, so a reservation join
    alone misses them, and it misses them precisely when a provider is
    running hotter than predicted or has just invoiced above estimate, which
    is when the cap matters most. Those are reached through the `model_calls`
    row named in the transaction's idempotency key.

    The direct route reads `_MODEL_CALL_KEYED_TYPES` and relies on the
    convention that such a transaction's idempotency key is
    `{type}:{model_call_id}`. Every registered type sits in exactly one route —
    a reservation, a model-call key, or none (`_PROVIDERLESS_REAL_SPEND_TYPES`)
    — and `test_real_spend_registration.py` refuses a type in no route or two,
    which is what keeps a new type from being skipped here in silence.
    """
    since_iso = since.astimezone(timezone.utc).isoformat()
    direct_types = tuple(t for t in _REAL_SPEND_TRANSACTION_TYPES if t in _MODEL_CALL_KEYED_TYPES)

    settled = 0
    if "reservation_settle" in _REAL_SPEND_TRANSACTION_TYPES:
        settled = conn.execute(
            """
            SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
            FROM ledger_entries e
            JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
            JOIN reservations r
              ON t.idempotency_key LIKE 'reservation_settle:' || r.reservation_id || ':%'
            WHERE t.book = 'USD_REAL'
              AND t.transaction_type = 'reservation_settle'
              AND e.account_id = ?
              AND r.provider = ?
              AND t.effective_at_utc >= ?
            """,
            (_SPEND_ACCOUNT, provider, since_iso),
        ).fetchone()["total"]

    direct = 0
    if direct_types:
        placeholders = ", ".join("?" for _ in direct_types)
        direct = conn.execute(
            f"""
            SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
            FROM ledger_entries e
            JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
            JOIN model_calls m
              ON t.idempotency_key = t.transaction_type || ':' || m.model_call_id
            WHERE t.book = 'USD_REAL'
              AND t.transaction_type IN ({placeholders})
              AND e.account_id = ?
              AND m.provider = ?
              AND t.effective_at_utc >= ?
            """,
            (*direct_types, _SPEND_ACCOUNT, provider, since_iso),
        ).fetchone()["total"]

    return settled + direct


def provider_exposure(
    conn: sqlite3.Connection, provider: str, *, now: datetime | None = None
) -> int:
    """Settled spend in the month window plus currently reserved, for one
    provider — the same "settled + reserved" basis §5.3 requires of the
    global caps, so many small calls to one provider cannot collectively
    exceed its cap while each stays under it."""
    now = now or datetime.now(timezone.utc)
    return _concurrent_reserved_for_provider(
        conn, provider
    ) + _settled_spend_for_provider_since(conn, provider, now - _MONTH)


# Every transaction type that represents real money leaving the colony. A type
# missing from this tuple is real spend the hour/day/month caps cannot see, so
# anything that posts an external USD_REAL charge must be added here — the
# model gateway's cost overrun is one such charge and is not a settlement, and
# a reconciliation adjustment is a third.
#
# This tuple is now genuinely the single source: `_settled_spend_since` and
# `_settled_spend_for_provider_since` both read it, rather than the latter
# hardcoding its own copy in SQL as it did through the gateway slice.
#
# Membership is no longer a convention a reviewer has to notice:
# `tests/test_real_spend_registration.py` walks the kernel's AST and fails on any
# transaction type that is neither registered here nor explicitly exempted there,
# and proves each registered type is summed by both spend windows. A type added
# here also needs its idempotency key shaped `{transaction_type}:{model_call_id}`
# or the per-provider join below will not find it.
_REAL_SPEND_TRANSACTION_TYPES = (
    "reservation_settle",
    "model_call_cost_overrun",
    "model_call_reconciliation_adjustment",
    "payment_fee",
)

#: Direct postings the per-provider window reaches through the `model_calls` row
#: their idempotency key names.
_MODEL_CALL_KEYED_TYPES = (
    "model_call_cost_overrun",
    "model_call_reconciliation_adjustment",
)

#: Real charges no provider's cap can bound, counted by the global windows only.
#: A processor's fee is taken by a party nothing reserves against, so a cap on
#: that party would bound nothing; counted globally, the fee still limits the
#: spend the colony does choose (ADR-098). A model-call charge filed here would
#: escape its provider's cap — the registration guard refuses one posted from the
#: gateway or reconciliation.
_PROVIDERLESS_REAL_SPEND_TYPES = ("payment_fee",)

# The leg that measures real money leaving the colony. Summing this account's
# *signed* entries — rather than filtering on `amount > 0` as the first two
# versions of these queries did — is what makes a negative adjustment work: a
# reconciliation credit debits external_expense, and on the old filter its
# positive counter-leg (the refund landing back in the Cell's cash) would have
# been counted as fresh spend, so paying a Cell back would have pushed it
# closer to the cap instead of further from it.
_SPEND_ACCOUNT = "external_expense"


def _settled_spend_since(conn: sqlite3.Connection, since: datetime) -> int:
    """Net USD_REAL flow into `external_expense` from external-spend
    transactions effective since `since`."""
    placeholders = ", ".join("?" for _ in _REAL_SPEND_TRANSACTION_TYPES)
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.book = 'USD_REAL'
          AND t.transaction_type IN ({placeholders})
          AND e.account_id = ?
          AND t.effective_at_utc >= ?
        """,
        (
            *_REAL_SPEND_TRANSACTION_TYPES,
            _SPEND_ACCOUNT,
            since.astimezone(timezone.utc).isoformat(),
        ),
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
    provider: str | None = None,
) -> None:
    """Raise RealSpendCapExceededError if reserving requested_amount now
    would push any cap over its limit. Must be called after the caller has
    already acquired a write lock (BEGIN IMMEDIATE) — see
    reservations.request — so this check is atomic with the reservation
    insert under concurrency (Charter C5).

    `provider` additionally enforces §5.1's per-provider cap. It is checked
    *first*: when a colony has deliberately capped one provider well below
    its global limits, the per-provider breach is the informative error.
    """
    now = now or datetime.now(timezone.utc)
    snap = snapshot(conn, now=now, limits=limits)
    limits = snap.limits

    if provider is not None and provider in limits.provider_limits:
        cap = limits.provider_limits[provider]
        projected = provider_exposure(conn, provider, now=now) + requested_amount
        if projected > cap:
            raise RealSpendCapExceededError(
                f"real-spend provider cap exceeded for {provider!r}: {projected} > {cap}"
            )

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
