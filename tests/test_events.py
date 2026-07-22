from datetime import datetime, timedelta, timezone

import pytest

from mitosis import events, ledger
from mitosis.models import Book, EntrySpec, EventStatus, OutboxEventSpec

FUTURE = datetime.now(timezone.utc) + timedelta(days=365)


def _credit_handler(account_id: str):
    def handler(conn, event):
        ledger._write_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="event_side_effect",
            idempotency_key=f"event_side_effect:{event.event_id}",
            entries=[
                EntrySpec(account_id="source", amount_minor_units=-5),
                EntrySpec(account_id=account_id, amount_minor_units=5),
            ],
        )
        return []

    return handler


def _failing_handler(conn, event):
    raise RuntimeError("handler failed")


# --- enqueue -----------------------------------------------------------------


def test_enqueue_is_idempotent_on_dedupe_key(conn):
    first = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    second = events.enqueue(conn, event_type="different", source="s", priority=9, dedupe_key="dk-1")
    assert second.event_id == first.event_id
    assert second.event_type == "t"
    assert second.priority == 0


def test_enqueue_rejects_naive_available_at(conn):
    with pytest.raises(events.EventError):
        events.enqueue(
            conn, event_type="t", source="s", priority=0, dedupe_key="dk-1",
            available_at=datetime(2026, 1, 1),
        )


def test_enqueue_rejects_naive_simulated_at(conn):
    with pytest.raises(events.EventError):
        events.enqueue(
            conn, event_type="t", source="s", priority=0, dedupe_key="dk-1",
            simulated_at=datetime(2026, 1, 1),
        )


def test_enqueue_defaults_to_pending_status(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    assert event.status == EventStatus.PENDING
    assert event.attempt_number == 0


# --- next_ready / ordering (Amendment A5) ------------------------------------


def test_next_ready_excludes_not_yet_available_events(conn):
    now = datetime.now(timezone.utc)
    events.enqueue(
        conn, event_type="future", source="s", priority=0, dedupe_key="dk-future",
        available_at=now + timedelta(hours=1),
    )
    ready = events.next_ready(conn, now=now)
    assert ready == []


def test_next_ready_orders_by_effective_time_then_priority_then_event_id(conn):
    now = datetime.now(timezone.utc)
    late = events.enqueue(
        conn, event_type="late", source="s", priority=0, dedupe_key="dk-late",
        available_at=now - timedelta(seconds=5),
    )
    early_low_priority = events.enqueue(
        conn, event_type="early-low", source="s", priority=5, dedupe_key="dk-early-low",
        available_at=now - timedelta(seconds=10),
    )
    early_high_priority = events.enqueue(
        conn, event_type="early-high", source="s", priority=0, dedupe_key="dk-early-high",
        available_at=now - timedelta(seconds=10),
    )
    ready = events.next_ready(conn, now=now)
    assert [e.event_id for e in ready] == [
        early_high_priority.event_id,
        early_low_priority.event_id,
        late.event_id,
    ]


def test_next_ready_uses_simulated_at_over_available_at(conn):
    now = datetime.now(timezone.utc)
    # available_at is far in the future (not real-time ready) but simulated_at
    # has already arrived — simulated_at is the effective_time for this event.
    synthetic = events.enqueue(
        conn, event_type="synthetic", source="s", priority=0, dedupe_key="dk-synth",
        available_at=now + timedelta(days=1),
        simulated_at=now - timedelta(seconds=1),
    )
    ready = events.next_ready(conn, now=now)
    assert [e.event_id for e in ready] == [synthetic.event_id]


def test_next_ready_only_returns_pending(conn):
    now = datetime.now(timezone.utc)
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    events.process_event(conn, event.event_id, lambda conn, e: [])
    assert events.next_ready(conn, now=now) == []


def test_next_ready_respects_limit(conn):
    now = datetime.now(timezone.utc)
    for i in range(3):
        events.enqueue(
            conn, event_type="t", source="s", priority=0, dedupe_key=f"dk-{i}",
            available_at=now - timedelta(seconds=1),
        )
    assert len(events.next_ready(conn, now=now, limit=2)) == 2


# --- process_event: idempotent processing (Charter C6) ----------------------


def test_process_event_runs_handler_exactly_once_under_redelivery(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    call_count = 0

    def handler(conn, ev):
        nonlocal call_count
        call_count += 1
        return []

    for _ in range(5):
        result = events.process_event(conn, event.event_id, handler)

    assert call_count == 1
    assert result.status == EventStatus.PROCESSED


def test_process_event_applies_handler_state_change_exactly_once(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    handler = _credit_handler("dest")

    for _ in range(3):
        events.process_event(conn, event.event_id, handler)

    assert ledger.get_balance(conn, "dest", Book.USD_SIM) == 5


def test_process_event_unknown_event_id_raises(conn):
    with pytest.raises(events.UnknownEventError):
        events.process_event(conn, "no-such-event", lambda conn, e: [])


def test_process_event_stages_outbox_events_from_handler(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")

    def handler(conn, ev):
        return [
            OutboxEventSpec(
                event_type="produced", source="handler", priority=0, dedupe_key="out-1"
            )
        ]

    events.process_event(conn, event.event_id, handler)
    assert events.outbox_unpublished_count(conn) == 1


def test_process_event_rolls_back_outbox_staging_on_handler_failure(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")

    def handler(conn, ev):
        events._stage_outbox(
            conn,
            spec=OutboxEventSpec(event_type="x", source="h", priority=0, dedupe_key="out-1"),
            causation_id=ev.event_id,
        )
        raise RuntimeError("boom after staging")

    with pytest.raises(RuntimeError):
        events.process_event(conn, event.event_id, handler)

    assert events.outbox_unpublished_count(conn) == 0


# --- poison-event / dead-letter handling (§17.3) -----------------------------


def test_process_event_failure_increments_attempt_and_records_error(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    with pytest.raises(RuntimeError):
        events.process_event(conn, event.event_id, _failing_handler, max_attempts=5)

    updated = events.get_event(conn, event.event_id)
    assert updated.attempt_number == 1
    assert updated.status == EventStatus.PENDING
    assert "handler failed" in updated.last_error


def test_process_event_dead_letters_after_max_attempts(conn):
    event = events.enqueue(conn, event_type="poison", source="s", priority=0, dedupe_key="dk-1")
    for _ in range(3):
        with pytest.raises(RuntimeError):
            events.process_event(conn, event.event_id, _failing_handler, max_attempts=3)

    final = events.get_event(conn, event.event_id)
    assert final.status == EventStatus.DEAD_LETTER
    assert final.attempt_number == 3


def test_dead_letter_records_audit_event(conn):
    event = events.enqueue(conn, event_type="poison", source="s", priority=0, dedupe_key="dk-1")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            events.process_event(conn, event.event_id, _failing_handler, max_attempts=2)

    row = conn.execute(
        "SELECT * FROM audit_events WHERE event_type = 'event_dead_lettered'"
    ).fetchone()
    assert row is not None
    assert event.event_id in row["description"]


def test_dead_lettered_event_no_longer_returned_by_next_ready(conn):
    now = datetime.now(timezone.utc)
    event = events.enqueue(conn, event_type="poison", source="s", priority=0, dedupe_key="dk-1")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            events.process_event(conn, event.event_id, _failing_handler, max_attempts=2)

    assert events.next_ready(conn, now=now) == []


def test_redelivering_a_dead_lettered_event_is_a_no_op(conn):
    event = events.enqueue(conn, event_type="poison", source="s", priority=0, dedupe_key="dk-1")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            events.process_event(conn, event.event_id, _failing_handler, max_attempts=2)

    # redelivery after dead-lettering must not call the handler again or raise
    result = events.process_event(conn, event.event_id, _failing_handler, max_attempts=2)
    assert result.status == EventStatus.DEAD_LETTER
    assert result.attempt_number == 2


# --- replay_dead_letter -------------------------------------------------------


def test_replay_dead_letter_resets_to_pending(conn):
    event = events.enqueue(conn, event_type="poison", source="s", priority=0, dedupe_key="dk-1")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            events.process_event(conn, event.event_id, _failing_handler, max_attempts=2)

    replayed = events.replay_dead_letter(conn, event.event_id)
    assert replayed.status == EventStatus.PENDING
    assert replayed.attempt_number == 0
    assert replayed.last_error is None


def test_replay_dead_letter_records_audit_event(conn):
    event = events.enqueue(conn, event_type="poison", source="s", priority=0, dedupe_key="dk-1")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            events.process_event(conn, event.event_id, _failing_handler, max_attempts=2)
    events.replay_dead_letter(conn, event.event_id)

    row = conn.execute(
        "SELECT * FROM audit_events WHERE event_type = 'event_dead_letter_replayed'"
    ).fetchone()
    assert row is not None


def test_replay_dead_letter_rejects_non_dead_lettered_event(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    with pytest.raises(events.EventError):
        events.replay_dead_letter(conn, event.event_id)


def test_replay_dead_letter_unknown_event_id_raises(conn):
    with pytest.raises(events.UnknownEventError):
        events.replay_dead_letter(conn, "no-such-event")


def test_replayed_event_can_be_processed_successfully(conn):
    event = events.enqueue(conn, event_type="poison", source="s", priority=0, dedupe_key="dk-1")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            events.process_event(conn, event.event_id, _failing_handler, max_attempts=2)
    events.replay_dead_letter(conn, event.event_id)

    result = events.process_event(conn, event.event_id, lambda conn, e: [])
    assert result.status == EventStatus.PROCESSED


# --- outbox dispatch -----------------------------------------------------------


def test_dispatch_outbox_publishes_and_marks_published(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    events.process_event(
        conn,
        event.event_id,
        lambda conn, e: [
            OutboxEventSpec(event_type="produced", source="h", priority=0, dedupe_key="out-1")
        ],
    )

    published_types = []
    result = events.dispatch_outbox(conn, lambda oe: published_types.append(oe.event_type))
    assert published_types == ["produced"]
    assert len(result) == 1
    assert events.outbox_unpublished_count(conn) == 0


def test_dispatch_outbox_does_not_republish(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    events.process_event(
        conn,
        event.event_id,
        lambda conn, e: [
            OutboxEventSpec(event_type="produced", source="h", priority=0, dedupe_key="out-1")
        ],
    )
    events.dispatch_outbox(conn, lambda oe: None)

    published_types = []
    events.dispatch_outbox(conn, lambda oe: published_types.append(oe.event_type))
    assert published_types == []


def test_dispatch_outbox_carries_causation_id_from_producing_event(conn):
    event = events.enqueue(conn, event_type="t", source="s", priority=0, dedupe_key="dk-1")
    events.process_event(
        conn,
        event.event_id,
        lambda conn, e: [
            OutboxEventSpec(event_type="produced", source="h", priority=0, dedupe_key="out-1")
        ],
    )

    row = conn.execute("SELECT * FROM event_outbox").fetchone()
    assert row["causation_id"] == event.event_id


# --- counts / status helpers --------------------------------------------------


def test_count_by_status_reflects_current_state(conn):
    events.enqueue(conn, event_type="a", source="s", priority=0, dedupe_key="dk-a")
    b = events.enqueue(conn, event_type="b", source="s", priority=0, dedupe_key="dk-b")
    events.process_event(conn, b.event_id, lambda conn, e: [])

    assert events.count_by_status(conn) == {"pending": 1, "processed": 1}
