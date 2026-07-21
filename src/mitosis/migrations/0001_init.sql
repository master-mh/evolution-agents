-- MITOSIS Phase 1 kernel — initial schema.
-- Ledger: SPEC.md §3.2 (transactions), §3.3 (entries, Amendment A3).
-- Reservations: SPEC.md §4.2, §4.4 (Amendment A4).
-- Migrations are append-only per §30.1 ("write migrations rather than
-- hand-altering DB state") — never edit this file after it has shipped;
-- add a new numbered migration instead.

PRAGMA foreign_keys = ON;

CREATE TABLE ledger_transactions (
    transaction_id              TEXT PRIMARY KEY,
    book                        TEXT NOT NULL CHECK (book IN ('USD_REAL', 'USD_SIM', 'RESOURCE')),
    currency                    TEXT NOT NULL,
    created_at_utc               TEXT NOT NULL,
    effective_at_utc             TEXT NOT NULL,
    idempotency_key              TEXT NOT NULL UNIQUE,
    event_id                    TEXT,
    transaction_type             TEXT NOT NULL,
    description                 TEXT NOT NULL DEFAULT '',
    previous_transaction_hash    TEXT,
    transaction_hash             TEXT NOT NULL,
    metadata_json                TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_ledger_transactions_book ON ledger_transactions(book);

CREATE TABLE ledger_entries (
    entry_id            TEXT PRIMARY KEY,
    transaction_id       TEXT NOT NULL REFERENCES ledger_transactions(transaction_id),
    account_id           TEXT NOT NULL,
    amount_minor_units    INTEGER NOT NULL,
    cell_id              TEXT,
    team_id              TEXT,
    experiment_id        TEXT,
    artifact_id          TEXT,
    metadata_json         TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_ledger_entries_transaction ON ledger_entries(transaction_id);
CREATE INDEX idx_ledger_entries_account ON ledger_entries(account_id);

CREATE TABLE reservations (
    reservation_id           TEXT PRIMARY KEY,
    cell_id                  TEXT NOT NULL,
    experiment_id             TEXT,
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
    idempotency_key           TEXT NOT NULL UNIQUE
);

CREATE INDEX idx_reservations_status_expires ON reservations(status, expires_at);
CREATE INDEX idx_reservations_cell ON reservations(cell_id);
