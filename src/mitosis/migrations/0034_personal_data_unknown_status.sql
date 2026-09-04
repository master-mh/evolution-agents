-- contains_personal_data becomes tri-state -- 'yes' / 'no' / 'unknown' --
-- instead of a boolean (SPEC.md §20.1, §20.2; implementation brief Slice B).
--
-- `fetchers.py` wrote `contains_personal_data=False` for every page it ever
-- fetched, unconditionally -- it never classified anything, so every False a
-- fetch produced was a fabricated negative, not a determination. §20.2 makes
-- exactly this argument for `commercial_use` already ("a default here would
-- be a fabricated licence claim"), which is why that column is already
-- `TEXT ... IN ('permitted', 'prohibited', 'unknown')` in both tables below.
-- `contains_personal_data` gets the same shape, for the same reason, sitting
-- right next to it in the same §20.1 metadata tuple.
--
-- **`tool_calls` stays nullable, unchanged in kind.** NULL still means "this
-- call has nothing to describe" (a failed call); a *succeeded* fetch now
-- records 'unknown' there instead of 0, matching how it already records
-- `commercial_use = 'unknown'` rather than NULL.
--
-- **`artifacts` needs a real data decision, not just a type change.** Every
-- existing row has `contains_personal_data = 0`, because nothing has ever
-- written 1 -- `artifacts.inherit_provenance`'s most-restrictive-wins
-- aggregation could only ever produce True if some contribution already had
-- it, and nothing did. But not every 0 means the same thing: an artifact
-- built from a fetched page inherited a fabricated False and should become
-- 'unknown'; an artifact with **no external sources at all**
-- (`artifacts.COLONY_AUTHORED`, `source_summary = 'no external sources'`) has
-- a real, defensible "no" -- there is no source it could have inherited
-- personal data from. The migration below preserves that distinction rather
-- than erasing it in either direction: correcting a real "no" to "unknown"
-- would be its own fabrication, and leaving an inherited fabricated "no" as
-- "no" would be the bug this migration exists to fix.
--
-- Same rebuild as migrations 0019/0021/0027/0032: SQLite cannot ALTER a
-- column's type or CHECK constraint, and `db.migrate` runs each file through
-- `executescript`, which commits before it starts and is therefore outside
-- any transaction.

PRAGMA foreign_keys = OFF;

-- --- tool_calls -----------------------------------------------------------

CREATE TABLE tool_calls_rebuilt (
    tool_call_id      TEXT PRIMARY KEY,
    grant_id          TEXT NOT NULL REFERENCES approval_grants(grant_id),
    proposal_id       TEXT NOT NULL REFERENCES proposals(proposal_id),
    cell_id           TEXT NOT NULL REFERENCES cells(cell_id),
    tool              TEXT NOT NULL,
    arguments_json    TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN (
                          'requested', 'succeeded', 'failed', 'execution_unknown'
                      )),
    idempotency_key   TEXT NOT NULL UNIQUE,
    started_at_utc    TEXT NOT NULL,
    finished_at_utc   TEXT,
    taint_label       TEXT NOT NULL DEFAULT 'UNTRUSTED_EXTERNAL',
    source            TEXT,
    retrieved_at_utc  TEXT,
    licence           TEXT,
    permitted_uses    TEXT,
    commercial_use    TEXT CHECK (commercial_use IN (
                          'permitted', 'prohibited', 'unknown'
                      )),
    -- NULL: nothing to describe (a failed call). Otherwise tri-state, same
    -- as commercial_use — see the file header.
    contains_personal_data TEXT CHECK (contains_personal_data IN (
                          'yes', 'no', 'unknown'
                      )),
    result_text       TEXT,
    result_bytes      INTEGER CHECK (result_bytes IS NULL OR result_bytes >= 0),
    result_sha256     TEXT,
    http_status       INTEGER,
    error             TEXT,
    resource_reservation_id TEXT REFERENCES reservations(reservation_id)
);

INSERT INTO tool_calls_rebuilt (
    tool_call_id, grant_id, proposal_id, cell_id, tool, arguments_json,
    status, idempotency_key, started_at_utc, finished_at_utc, taint_label,
    source, retrieved_at_utc, licence, permitted_uses, commercial_use,
    contains_personal_data, result_text, result_bytes, result_sha256,
    http_status, error, resource_reservation_id
)
SELECT
    tool_call_id, grant_id, proposal_id, cell_id, tool, arguments_json,
    status, idempotency_key, started_at_utc, finished_at_utc, taint_label,
    source, retrieved_at_utc, licence, permitted_uses, commercial_use,
    CASE contains_personal_data
        WHEN 1 THEN 'yes'
        WHEN 0 THEN 'unknown'  -- the only writer ever set 0, and never classified anything
        ELSE NULL
    END,
    result_text, result_bytes, result_sha256, http_status, error,
    resource_reservation_id
FROM tool_calls ORDER BY rowid;

DROP TABLE tool_calls;
ALTER TABLE tool_calls_rebuilt RENAME TO tool_calls;

CREATE INDEX idx_tool_calls_cell ON tool_calls (cell_id);
CREATE INDEX idx_tool_calls_grant ON tool_calls (grant_id);
CREATE INDEX idx_tool_calls_tool ON tool_calls (tool);

-- --- artifacts --------------------------------------------------------------

CREATE TABLE artifacts_rebuilt (
    artifact_id       TEXT PRIMARY KEY,
    artifact_hash     TEXT NOT NULL UNIQUE,
    kind              TEXT NOT NULL,
    title             TEXT NOT NULL,
    content           TEXT NOT NULL,
    content_bytes     INTEGER NOT NULL CHECK (content_bytes >= 0),
    created_by_cell_id      TEXT NOT NULL REFERENCES cells(cell_id),
    created_by_deliberation_id TEXT REFERENCES deliberations(deliberation_id),
    created_at_utc    TEXT NOT NULL,
    taint_labels_json TEXT NOT NULL DEFAULT '[]',
    licence           TEXT NOT NULL,
    permitted_uses    TEXT NOT NULL,
    commercial_use    TEXT NOT NULL CHECK (commercial_use IN (
                          'permitted', 'prohibited', 'unknown'
                      )),
    -- Tri-state, NOT NULL like commercial_use — every artifact has *some*
    -- position, even if the honest one is 'unknown'. See the file header for
    -- why the data migration below is not a blanket 0 -> 'unknown'.
    contains_personal_data TEXT NOT NULL DEFAULT 'unknown' CHECK (contains_personal_data IN (
                          'yes', 'no', 'unknown'
                      )),
    retention_rule    TEXT NOT NULL,
    source_summary    TEXT NOT NULL,
    exported_at_utc   TEXT,
    exported_by       TEXT,
    export_reason     TEXT,
    export_is_commercial INTEGER CHECK (export_is_commercial IN (0, 1)),
    own_provenance_json TEXT
);

INSERT INTO artifacts_rebuilt (
    artifact_id, artifact_hash, kind, title, content, content_bytes,
    created_by_cell_id, created_by_deliberation_id, created_at_utc,
    taint_labels_json, licence, permitted_uses, commercial_use,
    contains_personal_data, retention_rule, source_summary,
    exported_at_utc, exported_by, export_reason, export_is_commercial,
    own_provenance_json
)
SELECT
    artifact_id, artifact_hash, kind, title, content, content_bytes,
    created_by_cell_id, created_by_deliberation_id, created_at_utc,
    taint_labels_json, licence, permitted_uses, commercial_use,
    CASE
        WHEN contains_personal_data = 1 THEN 'yes'
        WHEN source_summary = 'no external sources' THEN 'no'  -- COLONY_AUTHORED: nothing to have inherited it from
        ELSE 'unknown'  -- inherited from a source that was never actually classified
    END,
    retention_rule, source_summary,
    exported_at_utc, exported_by, export_reason, export_is_commercial,
    own_provenance_json
FROM artifacts ORDER BY rowid;

DROP TABLE artifacts;
ALTER TABLE artifacts_rebuilt RENAME TO artifacts;

CREATE INDEX idx_artifacts_cell ON artifacts (created_by_cell_id);
CREATE INDEX idx_artifacts_kind ON artifacts (kind);

PRAGMA foreign_keys = ON;
