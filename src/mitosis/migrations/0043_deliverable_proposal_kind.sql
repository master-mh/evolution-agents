-- A Cell may hand over a deliverable and propose nothing else (§23, §28 Phase 8;
-- ADR-107).
--
-- Found live (2026-09-25): an operator rejected a Cell's proposal with a
-- revision request, and the Cell had no way to answer with only the revised
-- work. Every kind but `abstain` names something to do, and `abstain` may not
-- carry an artifact — so it abstained, saying the rewrite was "in progress",
-- and produced nothing. Told explicitly to wrap the rewrite in an experiment
-- proposal, it delivered at once.
--
-- `deliverable` is a *statement* kind (`proposal.STATEMENT_KINDS`), like
-- `strategy`: it asks for nothing, so approving it is acceptance, not
-- permission, and its grant is inert. It is queued like every other non-abstain
-- kind because the §23 queue is the only way an operator can answer a Cell — a
-- rejection's reason reaches it through the decision note and wakes it.
--
-- That a `deliverable` carries an artifact cannot be a CHECK here: the artifact
-- is linked to the deliberation in `artifacts`, not to the proposal row.
-- `proposal.Proposal` refuses one without it at parse time.
--
-- The table is rebuilt exactly as migration 0032 left it, with one value added
-- to the kind CHECK.

PRAGMA foreign_keys = OFF;

CREATE TABLE proposals_rebuilt (
    proposal_id          TEXT PRIMARY KEY,
    deliberation_id      TEXT NOT NULL REFERENCES deliberations(deliberation_id),
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),

    kind                 TEXT NOT NULL CHECK (kind IN (
                             'experiment', 'strategy', 'spend_request',
                             'tool_request', 'external_action', 'deliverable',
                             'abstain'
                         )),
    summary              TEXT NOT NULL,
    rationale            TEXT NOT NULL,

    -- NULL only when `kind = 'abstain'` (migration 0032, ADR-068).
    risk_tier            TEXT CHECK (risk_tier IS NULL OR risk_tier IN (
                             'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
                         )),

    estimated_cost_minor_units INTEGER NOT NULL CHECK (estimated_cost_minor_units >= 0),

    derived_from_untrusted INTEGER NOT NULL DEFAULT 0
                           CHECK (derived_from_untrusted IN (0, 1)),

    payload_json         TEXT NOT NULL,
    created_at_utc       TEXT NOT NULL,

    CHECK (risk_tier IS NOT NULL OR kind = 'abstain')
);

INSERT INTO proposals_rebuilt (
    proposal_id, deliberation_id, cell_id, kind, summary, rationale,
    risk_tier, estimated_cost_minor_units, derived_from_untrusted,
    payload_json, created_at_utc
)
SELECT
    proposal_id, deliberation_id, cell_id, kind, summary, rationale,
    risk_tier, estimated_cost_minor_units, derived_from_untrusted,
    payload_json, created_at_utc
FROM proposals ORDER BY rowid;

DROP TABLE proposals;
ALTER TABLE proposals_rebuilt RENAME TO proposals;

CREATE INDEX idx_proposals_cell ON proposals (cell_id);
CREATE INDEX idx_proposals_deliberation ON proposals (deliberation_id);

PRAGMA foreign_keys = ON;
