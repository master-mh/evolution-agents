-- Resource metering: non-cash consumption linked to a RESOURCE-book
-- reservation (SPEC.md §2.2/§2.3, Amendment A6).
-- Migrations are append-only per §30.1 — never edit a shipped migration.

CREATE TABLE resource_usage (
    usage_id        TEXT PRIMARY KEY,
    cell_id         TEXT NOT NULL REFERENCES cells(cell_id),
    reservation_id  TEXT NOT NULL REFERENCES reservations(reservation_id),
    resource_type   TEXT NOT NULL CHECK (resource_type IN (
                        'input_tokens', 'output_tokens', 'model_calls',
                        'cpu_seconds', 'memory_seconds', 'browser_minutes',
                        'network_requests', 'storage_byte_days',
                        'human_minutes', 'approval_actions'
                    )),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    minor_units     INTEGER NOT NULL CHECK (minor_units > 0),
    recorded_at_utc TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_resource_usage_cell ON resource_usage(cell_id);
CREATE INDEX idx_resource_usage_reservation ON resource_usage(reservation_id);
