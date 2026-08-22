"""Event delivery kernel: transactional inbox/outbox (SPEC.md §17, §3.5;
docs/EVENT_SEMANTICS.md). Implements the atomic processing algorithm in
docs/EVENT_SEMANTICS.md §3 (Charter C6: handlers are idempotent under
at-least-once redelivery), the `(effective_time, priority, event_id)` total
order from Amendment A5, and poison-event dead-lettering (§17.3).

Two separate idempotency guards, matching the rest of the kernel's
idempotency_key convention:
  - `dedupe_key` (event_inbox, UNIQUE): guards the *producer* side —
    `enqueue()` called twice with the same dedupe_key returns the
    already-enqueued event instead of creating a duplicate.
  - `event_inbox.status` (checked inside process_event's own transaction,
    re-checked after the write lock is acquired): guards the *consumer*
    side — redelivering an already-processed event_id is a no-op. This is
    the mechanism docs/EVENT_SEMANTICS.md §3 describes and what
    `charter_idempotent_handlers` (C6) tests.

Deliberately out of scope for this slice (see PRIORITIES.md): nothing in the
kernel yet produces real events through this path — Phase 2's flight
simulator and later Phase 1 work (reproduction, resource metering) are the
first real callers. Poison-event dead-lettering *does* quarantine the
implicated Cell when the caller identifies one (`process_event`/
`record_failure`'s optional `cell_id`) — see `record_failure`'s docstring;
callers that can't attribute an event to a single Cell simply omit it, and
dead-lettering proceeds without a quarantine side effect. `next_ready`'s
ordering compares `simulated_at`/`available_at` timestamp strings directly
(same approach as real_spend_breaker's window queries) — reconciling
simulated vs. real effective_time against a *live* simulated clock (clock.py,
not yet wired into any producer) is deferred to whichever slice first wires
clock.py into a real event producer.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Callable

from . import audit, ids, lifecycle
from .models import CellStatus, Event, EventStatus, OutboxEvent, OutboxEventSpec

DEFAULT_MAX_ATTEMPTS = 5


class EventError(Exception):
    pass


class UnknownEventError(EventError):
    pass


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        event_id=row["event_id"],
        dedupe_key=row["dedupe_key"],
        attempt_number=row["attempt_number"],
        event_type=row["event_type"],
        source=row["source"],
        target=row["target"],
        priority=row["priority"],
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        available_at=datetime.fromisoformat(row["available_at"]),
        simulated_at=datetime.fromisoformat(row["simulated_at"]) if row["simulated_at"] else None,
        payload=json.loads(row["payload_json"]),
        status=EventStatus(row["status"]),
        last_error=row["last_error"],
        causation_id=row["causation_id"],
        correlation_id=row["correlation_id"],
    )


def _row_to_outbox_event(row: sqlite3.Row) -> OutboxEvent:
    return OutboxEvent(
        event_id=row["event_id"],
        dedupe_key=row["dedupe_key"],
        event_type=row["event_type"],
        source=row["source"],
        target=row["target"],
        priority=row["priority"],
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        available_at=datetime.fromisoformat(row["available_at"]),
        simulated_at=datetime.fromisoformat(row["simulated_at"]) if row["simulated_at"] else None,
        payload=json.loads(row["payload_json"]),
        causation_id=row["causation_id"],
        correlation_id=row["correlation_id"],
        published_at_utc=datetime.fromisoformat(row["published_at_utc"]) if row["published_at_utc"] else None,
    )


def get_event(conn: sqlite3.Connection, event_id: str) -> Event | None:
    row = conn.execute("SELECT * FROM event_inbox WHERE event_id = ?", (event_id,)).fetchone()
    return _row_to_event(row) if row else None


def get_by_dedupe_key(conn: sqlite3.Connection, dedupe_key: str) -> Event | None:
    row = conn.execute(
        "SELECT * FROM event_inbox WHERE dedupe_key = ?", (dedupe_key,)
    ).fetchone()
    return _row_to_event(row) if row else None


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM event_inbox GROUP BY status"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def outbox_unpublished_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM event_outbox WHERE published_at_utc IS NULL"
    ).fetchone()
    return row["n"]


def enqueue(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    source: str,
    priority: int,
    dedupe_key: str,
    target: str | None = None,
    payload: dict | None = None,
    available_at: datetime | None = None,
    simulated_at: datetime | None = None,
    causation_id: str | None = None,
    correlation_id: str | None = None,
) -> Event:
    """Insert a new inbox event. Idempotent on dedupe_key: re-enqueuing the
    same logical event returns the existing row rather than duplicating it.
    """
    existing = get_by_dedupe_key(conn, dedupe_key)
    if existing is not None:
        return existing

    conn.execute("BEGIN IMMEDIATE")
    try:
        event_id = _enqueue_locked(
            conn,
            event_type=event_type,
            source=source,
            priority=priority,
            dedupe_key=dedupe_key,
            target=target,
            payload=payload,
            available_at=available_at,
            simulated_at=simulated_at,
            causation_id=causation_id,
            correlation_id=correlation_id,
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        if "dedupe_key" in str(exc):
            existing = get_by_dedupe_key(conn, dedupe_key)
            if existing is not None:
                return existing
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_event(conn, event_id)
    assert result is not None
    return result


def _enqueue_locked(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    source: str,
    priority: int,
    dedupe_key: str,
    target: str | None = None,
    payload: dict | None = None,
    available_at: datetime | None = None,
    simulated_at: datetime | None = None,
    causation_id: str | None = None,
    correlation_id: str | None = None,
) -> str:
    """Insert one inbox event. Caller holds the transaction; returns the event id.

    Exists so another module can fold an enqueue into its own atomic step —
    §23.3's approval expiry is the first caller, and it needs the expiry and the
    wake that regenerates the action to commit together. An expiry that
    committed without its regeneration would be an action silently dropped,
    which is the half of that clause easiest to lose.

    Unlike the wrapper, this does **not** pre-check the dedupe key or translate
    an IntegrityError: inside someone else's transaction a ROLLBACK here would
    discard their work, so the caller owns that decision.
    """
    now = datetime.now(timezone.utc)
    available = available_at or now
    if available.tzinfo is None:
        raise EventError("available_at must be timezone-aware UTC (Charter C11)")
    if simulated_at is not None and simulated_at.tzinfo is None:
        raise EventError("simulated_at must be timezone-aware UTC (Charter C11)")

    event_id = ids.new_id()

    conn.execute(
        """
        INSERT INTO event_inbox (
            event_id, dedupe_key, attempt_number, event_type, source, target,
            priority, created_at_utc, available_at, simulated_at, payload_json,
            status, causation_id, correlation_id
        ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            event_id,
            dedupe_key,
            event_type,
            source,
            target,
            priority,
            now.isoformat(),
            available.astimezone(timezone.utc).isoformat(),
            simulated_at.astimezone(timezone.utc).isoformat() if simulated_at else None,
            _canonical_json(payload or {}),
            causation_id,
            correlation_id,
        ),
    )
    return event_id


def next_ready(
    conn: sqlite3.Connection, *, now: datetime, limit: int | None = None
) -> list[Event]:
    """Pending events whose effective_time (simulated_at if set, else
    available_at) has arrived, in Amendment A5's total order:
    (effective_time, priority, event_id)."""
    query = """
        SELECT * FROM event_inbox
        WHERE status = 'pending'
          AND COALESCE(simulated_at, available_at) <= ?
        ORDER BY COALESCE(simulated_at, available_at), priority, event_id
    """
    params: list = [now.astimezone(timezone.utc).isoformat()]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [_row_to_event(r) for r in rows]


def _stage_outbox(
    conn: sqlite3.Connection, *, spec: OutboxEventSpec, causation_id: str
) -> None:
    now = datetime.now(timezone.utc)
    available = spec.available_at or now
    conn.execute(
        """
        INSERT INTO event_outbox (
            event_id, dedupe_key, event_type, source, target, priority,
            created_at_utc, available_at, simulated_at, payload_json,
            causation_id, correlation_id, published_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            ids.new_id(),
            spec.dedupe_key,
            spec.event_type,
            spec.source,
            spec.target,
            spec.priority,
            now.isoformat(),
            available.astimezone(timezone.utc).isoformat(),
            spec.simulated_at.astimezone(timezone.utc).isoformat() if spec.simulated_at else None,
            _canonical_json(spec.payload),
            causation_id,
            spec.correlation_id,
        ),
    )


def process_event(
    conn: sqlite3.Connection,
    event_id: str,
    handler: Callable[[sqlite3.Connection, Event], list[OutboxEventSpec]],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    cell_id: str | None = None,
) -> Event:
    """Atomically process one inbox event (docs/EVENT_SEMANTICS.md §3):

    1. If already processed or dead-lettered, no-op — this is what makes
       at-least-once redelivery safe (Charter C6).
    2. Otherwise call `handler(conn, event)` inside the same write
       transaction as the state changes it makes; the handler returns any
       events it produces (not yet published).
    3. Stage produced events into event_outbox (same transaction).
    4. Mark this event processed. COMMIT.

    A crash at any point before COMMIT leaves the event 'pending' — safe to
    retry from step 1. `handler` must not itself commit/rollback, the same
    shared-transaction convention as ledger._write_transaction/audit.record.
    On handler failure, records the failure (§17.3) and re-raises.

    `cell_id`, if given, identifies the Cell this event is attributed to —
    passed through to record_failure so dead-lettering after max_attempts
    can quarantine it (§17.3). Omit when an event isn't attributable to a
    single Cell.
    """
    event = get_event(conn, event_id)
    if event is None:
        raise UnknownEventError(f"no such event: {event_id}")
    if event.status != EventStatus.PENDING:
        return event

    conn.execute("BEGIN IMMEDIATE")
    try:
        current = get_event(conn, event_id)
        assert current is not None
        if current.status != EventStatus.PENDING:
            conn.execute("COMMIT")
            return current

        produced = handler(conn, current)
        for spec in produced or []:
            _stage_outbox(conn, spec=spec, causation_id=event_id)

        conn.execute(
            "UPDATE event_inbox SET status = 'processed' WHERE event_id = ?",
            (event_id,),
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        try:
            record_failure(conn, event_id, error=str(exc), max_attempts=max_attempts, cell_id=cell_id)
        except Exception as bookkeeping_exc:
            # The handler's own failure is the one the caller needs to see —
            # a failure while recording *that* failure must not mask it, so
            # the original is always what propagates, with the bookkeeping
            # failure chained on for visibility rather than swallowed.
            raise exc from bookkeeping_exc
        raise

    result = get_event(conn, event_id)
    assert result is not None
    return result


def record_failure(
    conn: sqlite3.Connection,
    event_id: str,
    *,
    error: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    cell_id: str | None = None,
) -> Event:
    """After a failed processing attempt: increment attempt_number, record
    last_error, and — once max_attempts is reached — move the event to
    dead_letter and emit an audit event (§17.3).

    If `cell_id` is given and the event reaches dead_letter, the implicated
    Cell is quarantined in the same transaction (docs/STATE_MACHINES.md §1.2
    `*  -> quarantined`) — but only if it's currently alive/dormant; a Cell
    that's already quarantined or dead from some other cause is left alone
    rather than raising (a second poison event shouldn't crash dead-lettering
    of the first)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        event = get_event(conn, event_id)
        if event is None:
            raise UnknownEventError(f"no such event: {event_id}")
        new_attempt = event.attempt_number + 1
        dead_letter = new_attempt >= max_attempts
        new_status = EventStatus.DEAD_LETTER if dead_letter else EventStatus.PENDING
        conn.execute(
            """
            UPDATE event_inbox
            SET attempt_number = ?, last_error = ?, status = ?
            WHERE event_id = ?
            """,
            (new_attempt, error, new_status.value, event_id),
        )
        if dead_letter:
            audit.record(
                conn,
                event_type="event_dead_lettered",
                description=(
                    f"event {event_id} ({event.event_type}) moved to dead-letter "
                    f"after {new_attempt} failed attempt(s): {error}"
                ),
                metadata={
                    "event_id": event_id,
                    "event_type": event.event_type,
                    "attempt_number": new_attempt,
                    "last_error": error,
                },
            )
            if cell_id is not None:
                cell = lifecycle.get_cell(conn, cell_id)
                if cell is not None and cell.status in (CellStatus.ALIVE, CellStatus.DORMANT):
                    lifecycle._transition_core(
                        conn,
                        cell,
                        CellStatus.QUARANTINED,
                        reason=f"poison event {event_id} ({event.event_type}) dead-lettered",
                        metadata={"linked_finding": {"event_id": event_id, "event_type": event.event_type}},
                    )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_event(conn, event_id)
    assert result is not None
    return result


def replay_dead_letter(conn: sqlite3.Connection, event_id: str) -> Event:
    """Controlled (human-triggered) re-admission of a dead-lettered event
    back to 'pending' with a fresh attempt budget (§17.3: "allow controlled
    replay from the dead-letter queue")."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        event = get_event(conn, event_id)
        if event is None:
            raise UnknownEventError(f"no such event: {event_id}")
        if event.status != EventStatus.DEAD_LETTER:
            raise EventError(
                f"event {event_id} is not dead-lettered (status={event.status.value})"
            )
        conn.execute(
            """
            UPDATE event_inbox
            SET status = 'pending', attempt_number = 0, last_error = NULL
            WHERE event_id = ?
            """,
            (event_id,),
        )
        audit.record(
            conn,
            event_type="event_dead_letter_replayed",
            description=f"event {event_id} ({event.event_type}) replayed from dead-letter queue",
            metadata={"event_id": event_id, "event_type": event.event_type},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_event(conn, event_id)
    assert result is not None
    return result


def dispatch_outbox(
    conn: sqlite3.Connection, publisher: Callable[[OutboxEvent], None]
) -> list[OutboxEvent]:
    """Publish all not-yet-published outbox events, in insertion order, via
    `publisher` (docs/EVENT_SEMANTICS.md §3 step 7 — runs after the
    producing transaction has committed). Marking an event published is its
    own transaction per event: a crash partway through only re-publishes the
    remaining unpublished events on retry, so `publisher` is expected to be
    idempotent downstream (the same at-least-once contract as inbox
    delivery)."""
    rows = conn.execute(
        "SELECT * FROM event_outbox WHERE published_at_utc IS NULL ORDER BY rowid"
    ).fetchall()
    published: list[OutboxEvent] = []
    for row in rows:
        outbox_event = _row_to_outbox_event(row)
        publisher(outbox_event)
        conn.execute(
            "UPDATE event_outbox SET published_at_utc = ? WHERE event_id = ?",
            (datetime.now(timezone.utc).isoformat(), outbox_event.event_id),
        )
        published.append(outbox_event)
    return published
