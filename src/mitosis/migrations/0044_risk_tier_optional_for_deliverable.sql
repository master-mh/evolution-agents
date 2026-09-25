-- `risk_tier` is optional for `deliverable` as it is for `abstain`
-- (§23.1, §23.5; ADR-068, ADR-109).
--
-- Live, 2026-09-25: every first-attempt `deliverable` reply from
-- claude-haiku-4-5 omitted `risk_tier` (3 of 3), and a repair turn naming every
-- required key still dropped it once — two revised playbooks lost to a missing
-- field. ADR-068 made the same call for `abstain` on the same ground: §23.1
-- classifies *actions*, and a deliverable, like an abstention, proposes none —
-- approving one grants nothing (ADR-107). Unlike an abstention it is queued, so
-- the queue's record of the Cell's claim must be able to say "no claim".
--
-- Nothing is weakened: the queue's assessed tier folds the claim in with `max`,
-- upward only, so an absent claim leaves the kernel's own assessment standing.
--
-- Both tables are rebuilt as they stand, one CHECK relaxed in each.

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

    -- NULL only for the kinds that propose no action (ADR-068, ADR-109).
    risk_tier            TEXT CHECK (risk_tier IS NULL OR risk_tier IN (
                             'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
                         )),

    estimated_cost_minor_units INTEGER NOT NULL CHECK (estimated_cost_minor_units >= 0),

    derived_from_untrusted INTEGER NOT NULL DEFAULT 0
                           CHECK (derived_from_untrusted IN (0, 1)),

    payload_json         TEXT NOT NULL,
    created_at_utc       TEXT NOT NULL,

    CHECK (risk_tier IS NOT NULL OR kind IN ('abstain', 'deliverable'))
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

CREATE TABLE approval_requests_rebuilt (
    request_id           TEXT PRIMARY KEY,

    -- One queue entry per proposal, enforced. A second entry for the same
    -- proposal would be two review paths for one intention, and an operator
    -- could approve one while rejecting the other.
    proposal_id          TEXT NOT NULL UNIQUE REFERENCES proposals(proposal_id),
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),

    -- §23.4's aggregation key, resolved at enqueue time. The spec names
    -- "counterparty/domain/channel"; none of those exist yet, because no Cell
    -- can take an external action. What *does* exist — and is the cheapest
    -- action-splitting mechanism this colony offers — is reproduction: a Cell
    -- can birth children and have each request a fraction of one risky thing.
    -- So the key is the lineage founder plus the kind of request. Keying on
    -- the Cell alone would miss exactly the split this system makes easiest.
    -- Counterparty/domain/channel join this key when external actions land.
    aggregation_key      TEXT NOT NULL,
    founder_cell_id      TEXT NOT NULL,

    -- NULL when the proposal claimed no tier: `abstain` and `deliverable` propose no
    -- action for §23.1 to classify (ADR-068, ADR-109). Only a deliverable is ever
    -- queued without one; the queue's own assessed tier is always present.
    claimed_tier         TEXT CHECK (claimed_tier IS NULL OR claimed_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    assessed_tier        TEXT NOT NULL CHECK (assessed_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')),

    -- §23.2 "cumulative related exposure": the sum over the rolling window on
    -- this aggregation key, including this request. Snapshotted at enqueue
    -- because it is what the tier was assessed against — recomputing it at
    -- read time would show the operator a number that never justified anything.
    exposure_minor_units INTEGER NOT NULL CHECK (exposure_minor_units >= 0),

    -- §23.1 "batch low-risk reversible actions; require individual review for
    -- high-risk or irreversible actions". Irreversibility is kernel-derived
    -- from the Cell's book and the request kind, never asserted by the Cell.
    reversible           INTEGER NOT NULL CHECK (reversible IN (0, 1)),

    status               TEXT NOT NULL CHECK (status IN (
                             'pending',
                             'approved',
                             'rejected',
                             -- §23.3. Distinct from rejected: an expired item
                             -- was never judged, and the spec requires it be
                             -- "regenerated and re-evaluated before execution"
                             -- rather than dropped or executed on stale terms.
                             'expired'
                         )),

    -- Two clocks, and conflating them would lose the guarantee §23.3 asks for.
    --
    -- `sla_due_at_utc` is when the item becomes *overdue* — a reporting state
    -- ("overdue items surface distinctly"), computed at read time from this
    -- column. An overdue item is still pending and still approvable; nothing
    -- about it changes except how loudly it appears.
    --
    -- `expires_at_utc` is a lifecycle transition: past it, the item is dead and
    -- the action must be re-derived from scratch.
    sla_seconds          INTEGER NOT NULL CHECK (sla_seconds > 0),
    sla_due_at_utc       TEXT NOT NULL,
    expires_at_utc       TEXT NOT NULL,

    created_at_utc       TEXT NOT NULL,

    -- Set on approve/reject/expire. `decided_by` is free text naming the human
    -- (or 'colony' for an expiry, which no human decided). A decision reason is
    -- mandatory for approve and reject at the API boundary, not here, because
    -- an expiry has no reason to give beyond the clock.
    decided_at_utc       TEXT,
    decided_by           TEXT,
    decision_reason      TEXT,

    -- Non-NULL when this item was approved as part of a §23.1 batch rather
    -- than individually reviewed. Recorded so "how was this actually looked
    -- at?" is answerable months later — a batch approval is a weaker claim
    -- about operator attention than an individual one, and the audit trail
    -- should not blur the two.
    batch_id             TEXT,

    -- When an expiry regenerates the action (§23.3), the fresh wake it
    -- enqueued. NULL if the Cell was no longer wakeable — a dead Cell's
    -- expired request has nothing to regenerate into, and that is a fact worth
    -- being able to see rather than an error.
    regenerated_wake_key TEXT
);

INSERT INTO approval_requests_rebuilt (request_id, proposal_id, cell_id, aggregation_key, founder_cell_id, claimed_tier, assessed_tier, exposure_minor_units, reversible, status, sla_seconds, sla_due_at_utc, expires_at_utc, created_at_utc, decided_at_utc, decided_by, decision_reason, batch_id, regenerated_wake_key)
SELECT request_id, proposal_id, cell_id, aggregation_key, founder_cell_id, claimed_tier, assessed_tier, exposure_minor_units, reversible, status, sla_seconds, sla_due_at_utc, expires_at_utc, created_at_utc, decided_at_utc, decided_by, decision_reason, batch_id, regenerated_wake_key FROM approval_requests ORDER BY rowid;

DROP TABLE approval_requests;
ALTER TABLE approval_requests_rebuilt RENAME TO approval_requests;

CREATE INDEX idx_approval_requests_status    ON approval_requests (status);
CREATE INDEX idx_approval_requests_cell      ON approval_requests (cell_id);
CREATE INDEX idx_approval_requests_aggregate ON approval_requests (aggregation_key, created_at_utc);

PRAGMA foreign_keys = ON;
