-- Event delivery kernel: transactional inbox/outbox (SPEC.md §17, §3.5;
-- docs/EVENT_SEMANTICS.md). At-least-once delivery, idempotent processing
-- (Charter C6), deterministic total ordering via Amendment A5's
-- (effective_time, priority, event_id) tie-break.
--
-- `priority` is not in §17.2's illustrative schema block but is required by
-- ADR-011 / §17.1's ordering key ("every event producer must supply a
-- stable priority") — added here as a required column.

CREATE TABLE event_inbox (
    event_id         TEXT PRIMARY KEY,
    dedupe_key       TEXT NOT NULL UNIQUE,
    attempt_number   INTEGER NOT NULL DEFAULT 0,
    event_type       TEXT NOT NULL,
    source           TEXT NOT NULL,
    target           TEXT,
    priority         INTEGER NOT NULL,
    created_at_utc   TEXT NOT NULL,
    available_at     TEXT NOT NULL,
    simulated_at     TEXT,
    payload_json     TEXT NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL CHECK (status IN ('pending', 'processed', 'dead_letter')) DEFAULT 'pending',
    last_error       TEXT,
    causation_id     TEXT,
    correlation_id   TEXT
);

CREATE INDEX idx_event_inbox_ready ON event_inbox (status, available_at);

CREATE TABLE event_outbox (
    event_id          TEXT PRIMARY KEY,
    dedupe_key        TEXT NOT NULL UNIQUE,
    event_type        TEXT NOT NULL,
    source            TEXT NOT NULL,
    target            TEXT,
    priority          INTEGER NOT NULL,
    created_at_utc    TEXT NOT NULL,
    available_at      TEXT NOT NULL,
    simulated_at      TEXT,
    payload_json      TEXT NOT NULL DEFAULT '{}',
    causation_id      TEXT,
    correlation_id    TEXT,
    published_at_utc  TEXT
);

CREATE INDEX idx_event_outbox_unpublished ON event_outbox (published_at_utc);
