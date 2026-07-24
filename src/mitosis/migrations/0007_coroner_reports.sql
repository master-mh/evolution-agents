-- Coroner reports: the artifact filed on every Cell death.
-- SPEC.md §10.5 (Amendment A15), docs/STATE_MACHINES.md §1.4.
-- Migrations are append-only per §30.1 — never edit a shipped migration.

CREATE TABLE coroner_reports (
    report_id              TEXT PRIMARY KEY,
    cell_id                TEXT NOT NULL UNIQUE REFERENCES cells(cell_id),
    genome_hash            TEXT NOT NULL,
    spend_by_book_json     TEXT NOT NULL,
    stage_reached          TEXT,
    cause_of_death         TEXT NOT NULL,
    final_hypotheses_json  TEXT NOT NULL DEFAULT '[]',
    experiment_ids_json    TEXT NOT NULL DEFAULT '[]',
    created_at_utc         TEXT NOT NULL
);
