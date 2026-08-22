-- The approval queue (SPEC.md §23; Amendments A11, A19).
--
-- Migration 0013 recorded proposals and said plainly that nothing consumed
-- them. This is the thing that consumes them — and it consumes them into a
-- *review path*, not an execution path.
--
-- One clause shapes every table below more than the rest:
--
-- §23.5 "The approval queue is itself part of the environment and will be
-- optimised against by Cells."
--
-- That is not a warning in a footnote, it is a design constraint with teeth.
-- It means every input to a queueing decision must be a fact the kernel can
-- establish, never a value the Cell supplies about itself. §0.3 already said
-- this about outcomes ("a Cell may explain a result; it may never define the
-- canonical result"); §23.5 extends it to *requests*. A Cell that could set
-- the tier it is reviewed at would set it to LOW forever, and a Cell that
-- could choose its own anti-gaming aggregation key would choose a fresh one
-- per request, which is precisely the action-splitting §23.4 exists to catch.
--
-- §25.1's ladder is the other constraint. An approval here moves the loop from
-- rung 5 ("shadow prediction with no action") to rung 6 ("human-reviewed
-- prototype"). It does not reach rung 9 ("bounded autonomy"). So approval
-- produces a *grant* — a recorded, scoped, expiring authorisation — and no
-- kernel path consumes a grant. Wiring an executor to one is a later,
-- deliberate rung, not a follow-on commit.


-- §27.1's `operator.approval_sla_seconds`. Stored in 0014's operator row
-- because it is operator policy, not queue state — and because 0014 shipped
-- the rest of that block already. Defaults are §27.1's literal values.
--
-- Note the ordering: the *higher* the risk, the *shorter* the window. That
-- reads backwards until you see what an SLA is for here — it is not how long
-- the operator is allowed to take, it is how quickly the item needs eyes.
ALTER TABLE operator_state ADD COLUMN approval_sla_low_seconds      INTEGER NOT NULL DEFAULT 86400;
ALTER TABLE operator_state ADD COLUMN approval_sla_medium_seconds   INTEGER NOT NULL DEFAULT 14400;
ALTER TABLE operator_state ADD COLUMN approval_sla_high_seconds     INTEGER NOT NULL DEFAULT 3600;
ALTER TABLE operator_state ADD COLUMN approval_sla_critical_seconds INTEGER NOT NULL DEFAULT 900;


-- One row per proposal that entered the queue.
--
-- `claimed_tier` vs `assessed_tier` is the heart of this table. The Cell's
-- proposal carries a `risk_tier`; that column is copied here as *claimed*, and
-- the kernel independently computes `assessed_tier` from facts the Cell does
-- not control (its book, its status, the kind of thing it is asking for, and
-- the aggregate exposure of its lineage over a rolling window). The queue acts
-- on `assessed_tier` only.
--
-- The relation between them is one-directional and deliberate: a Cell may
-- raise its own tier, never lower it (`assessed >= claimed` always). Claiming
-- *more* danger than the kernel found is not a gaming vector — it is a Cell
-- flagging its own risk, and disbelieving that would be perverse. Claiming
-- less is the vector, and it is recorded as an `understated_risk` signal
-- rather than silently overwritten.
CREATE TABLE approval_requests (
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

    claimed_tier         TEXT NOT NULL CHECK (claimed_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')),
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

CREATE INDEX idx_approval_requests_status    ON approval_requests (status);
CREATE INDEX idx_approval_requests_cell      ON approval_requests (cell_id);
CREATE INDEX idx_approval_requests_aggregate ON approval_requests (aggregation_key, created_at_utc);


-- §23.4's detections, one row per signal fired on a request.
--
-- These **annotate; they do not auto-reject.** That restraint is the point.
-- §23.5 says the queue will be optimised against — and an automatic rejector
-- is simply the next thing to optimise against, with the added cost that a
-- false positive kills honest work silently. So a signal does two things: it
-- escalates the assessed tier, and it disqualifies the request from §23.1
-- batching, forcing a human to look at it individually. The human still
-- decides.
CREATE TABLE approval_signals (
    signal_id   TEXT PRIMARY KEY,
    request_id  TEXT NOT NULL REFERENCES approval_requests(request_id),
    signal      TEXT NOT NULL CHECK (signal IN (
                    -- Many small requests on one aggregation key summing to
                    -- something that would not have been approved at once.
                    'action_splitting',
                    -- Too many pending requests from one lineage in the window.
                    'queue_flooding',
                    -- The Cell's own tier is below the kernel's assessment, or
                    -- a spend request claims to cost nothing.
                    'understated_risk',
                    -- New forecasts offered as evidence while the Cell's
                    -- earlier ones sit unresolved past their horizon.
                    'selective_evidence',
                    -- Substantially this request, already rejected once.
                    'repeat_after_rejection'
                )),
    detail      TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX idx_approval_signals_request ON approval_signals (request_id);


-- What an approval produces (§25.1 rung 6).
--
-- A grant is scoped to one proposal, single-use, and expiring. **Nothing in
-- the kernel consumes a grant**, exactly as nothing consumed a proposal in
-- 0013, and for the same reason: approval moves this loop to "human-reviewed
-- prototype", not to "bounded autonomy". `consumed_at_utc` therefore exists
-- and is always NULL today. It is here rather than added later so that the
-- first executor has to *fill in a column that already documents the rule*,
-- rather than inventing its own notion of what spending a grant means.
--
-- `exposure_at_grant_minor_units` freezes what the operator was actually shown
-- (§23.2). If a later executor ever reads a grant, it must be able to tell
-- that the world has moved since a human looked at it.
CREATE TABLE approval_grants (
    grant_id                      TEXT PRIMARY KEY,
    request_id                    TEXT NOT NULL UNIQUE REFERENCES approval_requests(request_id),
    proposal_id                   TEXT NOT NULL REFERENCES proposals(proposal_id),
    cell_id                       TEXT NOT NULL REFERENCES cells(cell_id),
    tier                          TEXT NOT NULL CHECK (tier IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    exposure_at_grant_minor_units INTEGER NOT NULL CHECK (exposure_at_grant_minor_units >= 0),
    granted_at_utc                TEXT NOT NULL,
    expires_at_utc                TEXT NOT NULL,
    consumed_at_utc               TEXT
);

CREATE INDEX idx_approval_grants_cell ON approval_grants (cell_id);
