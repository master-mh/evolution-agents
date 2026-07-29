-- Model gateway: every model call and its required metadata (SPEC.md §24.1),
-- plus the per-reservation provider tag that makes §5.1's "max real spend per
-- provider" cap enforceable.
-- Migrations are append-only per §30.1 — never edit a shipped migration.

-- Set only by gateway.call_model; NULL on every other reservation. The
-- real-spend breaker sums per-provider exposure off this column inside the
-- same write lock as the reservation insert, which is what makes the
-- per-provider cap atomic under concurrency (Charter C5).
ALTER TABLE reservations ADD COLUMN provider TEXT;

CREATE INDEX idx_reservations_provider ON reservations(provider);

CREATE TABLE model_calls (
    model_call_id        TEXT PRIMARY KEY,
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),
    experiment_id        TEXT,
    status               TEXT NOT NULL CHECK (status IN (
                             'reserved', 'succeeded', 'failed', 'execution_unknown'
                         )),

    -- §24.1: provider | requested model | resolved model version | API version
    provider             TEXT NOT NULL,
    requested_model      TEXT NOT NULL,
    resolved_model       TEXT,
    api_version          TEXT,

    -- §24.1: pricing-table version | prompt hashes | tool schema hashes
    pricing_table_version TEXT NOT NULL,
    system_prompt_hash   TEXT,
    user_prompt_hash     TEXT NOT NULL,
    tool_schema_hashes_json TEXT NOT NULL DEFAULT '[]',

    -- §24.1: parameters | input/output usage | latency | response hash
    parameters_json      TEXT NOT NULL DEFAULT '{}',
    input_tokens         INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens        INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    latency_ms           INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    response_hash        TEXT,
    stop_reason          TEXT,

    -- §24.1: full response or secure pointer. Stored inline in this kernel;
    -- a secure pointer is the Phase 5 sandbox concern.
    response_text        TEXT,

    -- §24.1: cost estimate | reconciled cost. Both in micro-USD (1e-6 USD) —
    -- see pricing.py for why per-call cost cannot be held in USD_REAL's
    -- minor unit. `settled_minor_units` is what actually hit the ledger,
    -- rounded up to the cent.
    cost_estimate_micro_usd  INTEGER NOT NULL DEFAULT 0,
    cost_actual_micro_usd    INTEGER,
    reconciled_micro_usd     INTEGER,
    settled_minor_units      INTEGER NOT NULL DEFAULT 0,

    -- The two reservations this call is bound to. Amendment A6 requires every
    -- metered operation to link to exactly one reservation; USD_REAL and
    -- RESOURCE are metered separately because they are separate books (§2.2).
    real_reservation_id     TEXT NOT NULL REFERENCES reservations(reservation_id),
    resource_reservation_id TEXT NOT NULL REFERENCES reservations(reservation_id),

    -- §2.4 mirror: an independent synthetic expense, never a cross-book
    -- transfer. 0 when mirroring was disabled or could not be funded.
    mirror_minor_units   INTEGER NOT NULL DEFAULT 0 CHECK (mirror_minor_units >= 0),
    mirror_skipped_reason TEXT,

    error_text           TEXT,
    created_at_utc       TEXT NOT NULL,
    idempotency_key      TEXT NOT NULL UNIQUE
);

CREATE INDEX idx_model_calls_cell ON model_calls(cell_id);
CREATE INDEX idx_model_calls_provider ON model_calls(provider);
CREATE INDEX idx_model_calls_status ON model_calls(status);
