-- The seam four files scheduled, and the constraint that made it unnecessary
-- (SPEC.md §2.5, §2.6, §3.6; Charter C3; ADR-043, ADR-044, ADR-047).
--
-- Migration 0026 created `experiments` and its own header complained that
-- `experiment_id` "has been a column in ... since migration 0001 ... and
-- validated nothing. **The foreign key was exposed to the operator before the
-- table existed.**" ADR-044 then validated the two operator-facing CLI paths
-- and explicitly deferred the rest, because `reservations`, `prediction` and
-- `ledger` sit *below* `experiments` in the layering, so a Python check there
-- would need an injected seam (`sweeper.ExternalOperationChecker` shape).
-- PRIORITIES and FUTURE_BUILD_HOOKS both scheduled that seam.
--
-- **A foreign key has no layer.** The layering objection is an objection to a
-- Python check; it says nothing about a constraint declared in the schema,
-- which sits below every module, binds every caller including ones that never
-- heard of the seam, and cannot be forgotten at a call site. `db.connect` has
-- set `PRAGMA foreign_keys = ON` since migration 0001, so the enforcement was
-- already switched on and waiting — what was missing was the declaration.
--
-- These four columns are bare TEXT for one reason each: every one of them
-- predates the table it names. `ledger_entries` and `reservations` are from
-- 0001, `model_calls` from 0010, `prediction_register` from 0012; `experiments`
-- arrived in 0026. SQLite cannot ALTER TABLE ADD CONSTRAINT, so each is
-- rebuilt. (`reservations.cell_id` and `ledger_entries.cell_id` are unconstrained
-- for exactly the same reason — `cells` also postdates 0001 — and are
-- deliberately **not** touched here: that is a different claim needing its own
-- argument, and widening this migration would put the ledger through a rebuild
-- for a reason nobody has stated yet.)
--
-- **NULL stays legal, and that is the point.** ADR-044 settled that consumption
-- with no running experiment behind it is genuinely unattributed and that
-- "`None` is a result, not a gap". A foreign key exempts NULL, so the constraint
-- refuses exactly the case that was never a result — an id naming nothing.
--
-- **Pre-existing rows are copied verbatim, violations included.** §3.6 forbids
-- editing history to correct it, and a migration that silently NULLed a dangling
-- id would be doing precisely that — destroying the evidence that a report had
-- been undercounting. SQLite does not retro-check on rebuild, so such rows
-- survive and `PRAGMA foreign_key_check` names them. Verified: a row already
-- dangling can still be UPDATEd on its other columns, so a live colony's
-- in-flight reservations keep transitioning normally rather than freezing.
--
-- **Order is preserved deliberately.** `ledger_transactions` and
-- `prediction_register` are hash-chained and both `verify_chain`s read their
-- rows `ORDER BY rowid`; `golden.py` reads four of these tables the same way.
-- A rebuild renumbers rowids, so each copy below is `ORDER BY rowid` to make
-- relative order a stated guarantee rather than a property of how SQLite
-- happens to scan. Nothing persists a rowid value, so renumbering is otherwise
-- invisible.

-- --------------------------------------------- repair before constraining
-- **One case had to be repaired rather than preserved, and it is not a history
-- edit.** `reservations.settle` and `.release` write *new* ledger entries
-- carrying the reservation's `experiment_id`. So an open reservation that
-- already holds a dangling id becomes unsettleable the moment the entry
-- constraint exists: every path out of it writes an entry the foreign key must
-- refuse, and the funds it committed stay committed forever. A `PRAGMA`-level
-- probe does not reveal this — a bare UPDATE of a non-key column on a violating
-- row is allowed, so the row looks healthy right up until the kernel tries to
-- release it. The test that releases one is what found it.
--
-- A *terminal* reservation is left exactly as it is: nothing will ever write
-- another entry for it, so its dangling id is harmless evidence and §3.6 keeps
-- it. An *open* one is not history — it is a live claim, and the id on it is an
-- attribution that was already false. Clearing it to NULL makes the row say the
-- true thing (ADR-044: unattributed is a result, not a gap), and the audit row
-- records the id that was cleared, so nothing is dropped silently.
--
-- Neither statement touches a ledger row, so both hash chains are untouched.
-- On a colony with no dangling ids — every colony this repo has ever run,
-- because `experiments.attribution_for` is the only internal source of the
-- value — both statements match zero rows and the migration is a pure schema
-- change.

INSERT INTO audit_events (
    event_id, event_type, cell_id, description, created_at_utc, metadata_json
)
SELECT
    lower(hex(randomblob(16))),
    'reservation_attribution_cleared',
    cell_id,
    'migration 0027 cleared a dangling experiment_id from an open reservation',
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    json_object(
        'reservation_id', reservation_id,
        'cleared_experiment_id', experiment_id,
        'status', status
    )
FROM reservations
WHERE experiment_id IS NOT NULL
  AND status NOT IN ('settled', 'released')
  AND experiment_id NOT IN (SELECT experiment_id FROM experiments);

UPDATE reservations
SET experiment_id = NULL
WHERE experiment_id IS NOT NULL
  AND status NOT IN ('settled', 'released')
  AND experiment_id NOT IN (SELECT experiment_id FROM experiments);


PRAGMA foreign_keys = OFF;

-- ---------------------------------------------------------------- 0001 tables

CREATE TABLE ledger_entries_new (
    entry_id            TEXT PRIMARY KEY,
    transaction_id       TEXT NOT NULL REFERENCES ledger_transactions(transaction_id),
    account_id           TEXT NOT NULL,
    amount_minor_units    INTEGER NOT NULL,
    cell_id              TEXT,
    team_id              TEXT,
    experiment_id        TEXT REFERENCES experiments(experiment_id),
    artifact_id          TEXT,
    metadata_json         TEXT NOT NULL DEFAULT '{}'
);

INSERT INTO ledger_entries_new (
    entry_id, transaction_id, account_id, amount_minor_units,
    cell_id, team_id, experiment_id, artifact_id, metadata_json
)
SELECT entry_id, transaction_id, account_id, amount_minor_units,
       cell_id, team_id, experiment_id, artifact_id, metadata_json
FROM ledger_entries ORDER BY rowid;

DROP TABLE ledger_entries;
ALTER TABLE ledger_entries_new RENAME TO ledger_entries;

CREATE INDEX idx_ledger_entries_transaction ON ledger_entries(transaction_id);
CREATE INDEX idx_ledger_entries_account ON ledger_entries(account_id);


CREATE TABLE reservations_new (
    reservation_id           TEXT PRIMARY KEY,
    cell_id                  TEXT NOT NULL,
    experiment_id             TEXT REFERENCES experiments(experiment_id),
    book                     TEXT NOT NULL CHECK (book IN ('USD_REAL', 'USD_SIM', 'RESOURCE')),
    currency                 TEXT NOT NULL,
    maximum_amount            INTEGER NOT NULL CHECK (maximum_amount >= 0),
    settled_amount            INTEGER NOT NULL DEFAULT 0 CHECK (settled_amount >= 0),
    reserved_at               TEXT NOT NULL,
    expires_at                TEXT NOT NULL,
    external_operation_type   TEXT,
    external_operation_id     TEXT,
    status                   TEXT NOT NULL CHECK (status IN (
                                 'requested', 'reserved', 'execution_unknown',
                                 'partially_settled', 'settled', 'released', 'disputed'
                             )),
    idempotency_key           TEXT NOT NULL UNIQUE,
    provider                 TEXT
);

INSERT INTO reservations_new (
    reservation_id, cell_id, experiment_id, book, currency,
    maximum_amount, settled_amount, reserved_at, expires_at,
    external_operation_type, external_operation_id, status,
    idempotency_key, provider
)
SELECT reservation_id, cell_id, experiment_id, book, currency,
       maximum_amount, settled_amount, reserved_at, expires_at,
       external_operation_type, external_operation_id, status,
       idempotency_key, provider
FROM reservations ORDER BY rowid;

DROP TABLE reservations;
ALTER TABLE reservations_new RENAME TO reservations;

CREATE INDEX idx_reservations_status_expires ON reservations(status, expires_at);
CREATE INDEX idx_reservations_cell ON reservations(cell_id);
CREATE INDEX idx_reservations_provider ON reservations(provider);


-- ------------------------------------------------------------- 0010 model_calls
-- The column comments are carried across verbatim: they live in `sqlite_master`,
-- so recreating the table without them would delete documentation from every
-- deployed schema.

CREATE TABLE model_calls_new (
    model_call_id        TEXT PRIMARY KEY,
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),
    experiment_id        TEXT REFERENCES experiments(experiment_id),
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

    -- §24.1: cost estimate | reconciled cost. Both in micro-USD (1e-6 USD) --
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
    idempotency_key      TEXT NOT NULL UNIQUE,

    -- Added by migration 0018 (per-call reconciliation, ADR-023).
    reconciled_at_utc    TEXT,
    reconciliation_source TEXT
);

INSERT INTO model_calls_new (
    model_call_id, cell_id, experiment_id, status,
    provider, requested_model, resolved_model, api_version,
    pricing_table_version, system_prompt_hash, user_prompt_hash,
    tool_schema_hashes_json, parameters_json, input_tokens, output_tokens,
    latency_ms, response_hash, stop_reason, response_text,
    cost_estimate_micro_usd, cost_actual_micro_usd, reconciled_micro_usd,
    settled_minor_units, real_reservation_id, resource_reservation_id,
    mirror_minor_units, mirror_skipped_reason, error_text, created_at_utc,
    idempotency_key, reconciled_at_utc, reconciliation_source
)
SELECT model_call_id, cell_id, experiment_id, status,
       provider, requested_model, resolved_model, api_version,
       pricing_table_version, system_prompt_hash, user_prompt_hash,
       tool_schema_hashes_json, parameters_json, input_tokens, output_tokens,
       latency_ms, response_hash, stop_reason, response_text,
       cost_estimate_micro_usd, cost_actual_micro_usd, reconciled_micro_usd,
       settled_minor_units, real_reservation_id, resource_reservation_id,
       mirror_minor_units, mirror_skipped_reason, error_text, created_at_utc,
       idempotency_key, reconciled_at_utc, reconciliation_source
FROM model_calls ORDER BY rowid;

DROP TABLE model_calls;
ALTER TABLE model_calls_new RENAME TO model_calls;

CREATE INDEX idx_model_calls_cell ON model_calls(cell_id);
CREATE INDEX idx_model_calls_provider ON model_calls(provider);
CREATE INDEX idx_model_calls_status ON model_calls(status);
CREATE INDEX idx_model_calls_reconciled ON model_calls(reconciled_at_utc);


-- ------------------------------------------------- 0012 prediction_register
-- Hash-chained (§8.5, ADR-025). The copy below is ORDER BY rowid because
-- `prediction.verify_chain` walks the register in rowid order and
-- `_last_prediction_hash` reads `ORDER BY rowid DESC LIMIT 1`.

CREATE TABLE prediction_register_new (
    prediction_id        TEXT PRIMARY KEY,
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),
    experiment_id        TEXT REFERENCES experiments(experiment_id),

    -- What is being predicted, as a claim that is unambiguously true or false
    -- once resolved. Brier and log scores are defined over binary outcomes
    -- (§8.5 names exactly those two rules), so a continuous quantity is
    -- predicted by stating a threshold claim: "revenue >= 50 minor units".
    claim                TEXT NOT NULL,

    -- P(claim is true), strictly between 0 and 1. The bounds are exclusive on
    -- purpose: the log score of a confident-and-wrong prediction is infinite,
    -- and one such prediction would make a Cell's mean score -inf forever,
    -- destroying the ordering that selection needs.
    probability          REAL NOT NULL CHECK (probability > 0 AND probability < 1),

    -- When the outcome should be known. A prediction resolved at the Cell's own
    -- discretion produces a self-selected calibration curve, so overdue and
    -- unresolved predictions are reportable (see prediction.overdue).
    resolves_by_utc      TEXT NOT NULL,

    created_at_utc       TEXT NOT NULL,
    previous_hash        TEXT,
    prediction_hash      TEXT NOT NULL,

    -- Outcome. All NULL until resolved; written exactly once.
    outcome              INTEGER CHECK (outcome IN (0, 1)),
    resolved_at_utc      TEXT,
    resolution_source    TEXT,
    brier_score          REAL,
    log_score            REAL,

    idempotency_key      TEXT NOT NULL UNIQUE
);

INSERT INTO prediction_register_new (
    prediction_id, cell_id, experiment_id, claim, probability,
    resolves_by_utc, created_at_utc, previous_hash, prediction_hash,
    outcome, resolved_at_utc, resolution_source, brier_score, log_score,
    idempotency_key
)
SELECT prediction_id, cell_id, experiment_id, claim, probability,
       resolves_by_utc, created_at_utc, previous_hash, prediction_hash,
       outcome, resolved_at_utc, resolution_source, brier_score, log_score,
       idempotency_key
FROM prediction_register ORDER BY rowid;

DROP TABLE prediction_register;
ALTER TABLE prediction_register_new RENAME TO prediction_register;

CREATE INDEX idx_prediction_register_cell ON prediction_register(cell_id);
CREATE INDEX idx_prediction_register_unresolved
    ON prediction_register(resolved_at_utc, resolves_by_utc);

PRAGMA foreign_keys = ON;
