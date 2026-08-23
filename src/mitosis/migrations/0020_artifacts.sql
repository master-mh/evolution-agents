-- The artifact store (SPEC.md §20.1, §18.1, §11.3, §11.4, §15.2, §19.3, §31;
-- Amendment A3; Charter C13; ADR-035).
--
-- What a Cell makes. Until now a Cell could decide and could read; the thing it
-- produced had nowhere to live, so `revenue.record_revenue` attributed money to
-- a free-text string and `ledger_entries.artifact_id` — an **Amendment A3
-- required field, present since migration 0001** — was never populated by
-- anything.
--
-- **Identity is the content hash, not a name.** §11.3 lists "duplicated
-- artifacts with new names" among the things Auditors must inspect for. Giving
-- each artifact a uuid and a title makes that trivial to do and turns detection
-- into a permanent chore; content addressing makes it *unrepresentable*, since
-- two identical artifacts are one row. Same move §16.1 makes for genomes
-- (ADR-018) and ADR-033 makes for the closed genome schema.

CREATE TABLE artifacts (
    -- The A3 name, and what `ledger_entries.artifact_id` finally points at.
    artifact_id       TEXT PRIMARY KEY,

    -- The content address (§16.1's trick, applied to work products). UNIQUE is
    -- the whole of §11.3's anti-duplication defence: re-submitting identical
    -- content returns the existing row rather than minting a second identity.
    artifact_hash     TEXT NOT NULL UNIQUE,

    kind              TEXT NOT NULL,
    title             TEXT NOT NULL,
    content           TEXT NOT NULL,
    content_bytes     INTEGER NOT NULL CHECK (content_bytes >= 0),

    created_by_cell_id      TEXT NOT NULL REFERENCES cells(cell_id),
    -- The wake that produced it, when a Cell did. NULL for operator-authored
    -- artifacts, which is also how HUMAN_AUTHORED provenance gets its meaning.
    created_by_deliberation_id TEXT REFERENCES deliberations(deliberation_id),
    created_at_utc    TEXT NOT NULL,

    -- §18.1 provenance labels, as a JSON array. A *union* of its sources' —
    -- see artifacts.py. Charter C13 reads this at the export gate.
    taint_labels_json TEXT NOT NULL DEFAULT '[]',

    -- §20.1's required metadata. Every field is NOT NULL: §20.2 is explicit
    -- that public visibility does not imply commercial reusability, so an
    -- absent rights position must never read as an unrestricted one. Inherited
    -- from sources on a most-restrictive-wins basis, which is what stops
    -- "summarise the page into an artifact" laundering a licence the colony
    -- never had.
    licence           TEXT NOT NULL,
    permitted_uses    TEXT NOT NULL,
    commercial_use    TEXT NOT NULL CHECK (commercial_use IN (
                          'permitted', 'prohibited', 'unknown'
                      )),
    contains_personal_data INTEGER NOT NULL DEFAULT 0
                           CHECK (contains_personal_data IN (0, 1)),
    retention_rule    TEXT NOT NULL,
    source_summary    TEXT NOT NULL,

    -- §19.3's "artifact-export gateway". Export is the recorded act of a human
    -- taking an artifact outside the colony — §28's Phase 8 gates *external
    -- use*, not production, so nothing here gates creation.
    exported_at_utc   TEXT,
    exported_by       TEXT,
    export_reason     TEXT,
    export_is_commercial INTEGER CHECK (export_is_commercial IN (0, 1))
);

CREATE INDEX idx_artifacts_cell ON artifacts (created_by_cell_id);
CREATE INDEX idx_artifacts_kind ON artifacts (kind);


-- §11.4's contribution graph, first edges:
--     discovery -> hypothesis -> prototype -> module -> product -> listing
-- A source is either another artifact or a tool call (what the colony read).
-- Exactly one, enforced — an edge naming both would be two edges pretending to
-- be one, and an edge naming neither is not provenance.
CREATE TABLE artifact_lineage (
    artifact_id         TEXT NOT NULL REFERENCES artifacts(artifact_id),
    source_artifact_id  TEXT REFERENCES artifacts(artifact_id),
    source_tool_call_id TEXT REFERENCES tool_calls(tool_call_id),

    CHECK (
        (source_artifact_id IS NOT NULL AND source_tool_call_id IS NULL)
        OR (source_artifact_id IS NULL AND source_tool_call_id IS NOT NULL)
    ),
    -- A self-referential edge is meaningless and would loop any lineage walk.
    CHECK (source_artifact_id IS NULL OR source_artifact_id <> artifact_id),

    UNIQUE (artifact_id, source_artifact_id, source_tool_call_id)
);

CREATE INDEX idx_artifact_lineage_artifact ON artifact_lineage (artifact_id);
CREATE INDEX idx_artifact_lineage_source ON artifact_lineage (source_artifact_id);
