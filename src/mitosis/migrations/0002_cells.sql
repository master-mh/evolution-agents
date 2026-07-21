-- Cells, content-addressed genomes, and the audit trail.
-- SPEC.md §16.2 (cell_genomes fields), §30 (lifecycle states, Amendment A8),
-- Charter C10 (every lifecycle transition emits an audit event),
-- Charter C11 (every genome has a canonical hash).

CREATE TABLE cell_genomes (
    genome_id               TEXT PRIMARY KEY,
    genome_hash              TEXT NOT NULL UNIQUE,
    version                  INTEGER NOT NULL,
    parent_genome_hashes      TEXT NOT NULL DEFAULT '[]',
    created_at                TEXT NOT NULL,
    mutation_operator         TEXT,
    canonical_genome_json      TEXT NOT NULL,
    prompt_hashes             TEXT NOT NULL DEFAULT '[]',
    module_hashes             TEXT NOT NULL DEFAULT '[]',
    model_policy_hash         TEXT,
    risk_label                TEXT NOT NULL DEFAULT 'unclassified',
    taint_labels              TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE cells (
    cell_id       TEXT PRIMARY KEY,
    cell_type     TEXT NOT NULL CHECK (cell_type IN (
                      'explorer', 'builder', 'commercial', 'auditor', 'immune', 'skeptic'
                  )),
    genome_hash   TEXT NOT NULL REFERENCES cell_genomes(genome_hash),
    book          TEXT NOT NULL CHECK (book IN ('USD_REAL', 'USD_SIM', 'RESOURCE')),
    status        TEXT NOT NULL CHECK (status IN (
                      'created', 'alive', 'dormant', 'quarantined', 'dead'
                  )),
    created_at_utc TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE INDEX idx_cells_status ON cells(status);
CREATE INDEX idx_cells_type ON cells(cell_type);

CREATE TABLE audit_events (
    event_id       TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    cell_id        TEXT,
    description    TEXT NOT NULL DEFAULT '',
    created_at_utc  TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_audit_events_cell ON audit_events(cell_id);
