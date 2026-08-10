-- The agent loop: wake, deliberate, propose (SPEC.md §15, §17.2, §0.3, §25.1).
--
-- Everything before this migration is machinery *for* a Cell. This is the
-- first table a Cell writes to by thinking.
--
-- Two constitutional constraints shape these tables more than anything else:
--
-- §0.3 "A Cell may *explain* a result; it may never *define* the canonical
-- result." So there is no column here that any fitness, selection, or death
-- criterion reads. A proposal is an explanation and an intention. Revenue
-- still arrives only through `revenue.record_revenue`, spend only through the
-- ledger, calibration only through the hash-chained prediction register. If a
-- Cell could write a number here that `death.contribution` later read, the
-- colony would be grading Cells on their own testimony.
--
-- §25.1 "No strategy moves directly from synthetic success to autonomous
-- commerce." A proposal is inert: `status` exists to record that it was
-- recorded, and nothing in the kernel consumes it. That is rung 5 of the
-- promotion ladder ("shadow prediction with no action"), which is where a
-- first agent loop honestly belongs — not rung 9.

CREATE TABLE deliberations (
    deliberation_id      TEXT PRIMARY KEY,
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),

    -- Idempotency for the whole wake (Charter C6). Wake events are delivered
    -- at least once, and a redelivered wake must not buy a second model call.
    -- The gateway is idempotent on its own key, but this is the outer guard:
    -- a replayed wake returns the existing deliberation without re-assembling
    -- context or re-parsing anything.
    wake_key             TEXT NOT NULL UNIQUE,

    -- One of §17.2's wake events (scheduled research cycle, payment
    -- settlement, audit request, ...). Free text rather than a CHECK because
    -- §17.2 gives an open list and new wake sources are expected.
    wake_reason          TEXT NOT NULL,

    -- The genome whose content was interpreted. Recorded so a proposal can
    -- always be traced to the strategy that produced it, and so a genome
    -- change is visible as a change in behaviour.
    genome_hash          TEXT NOT NULL REFERENCES cell_genomes(genome_hash),

    -- The gateway call that did the thinking. NULL when the loop refused
    -- before spending anything (a dead Cell, an unfunded one) — a refusal is
    -- still a recorded deliberation, because "this Cell could not think" is
    -- exactly the kind of fact that should not be silently absent.
    model_call_id        TEXT REFERENCES model_calls(model_call_id),

    -- What §15 context assembly actually selected, and what it dropped to stay
    -- inside the budget. Stored because "do not load the entire Cell history"
    -- is only checkable if the selection is recorded.
    context_json         TEXT NOT NULL,
    context_tokens       INTEGER NOT NULL,
    context_dropped_json TEXT NOT NULL,

    status               TEXT NOT NULL CHECK (status IN (
                             'proposed',      -- a valid structured proposal
                             'unparseable',   -- the model did not return one
                             'refused'        -- the loop declined to run
                         )),
    -- Why an 'unparseable' or 'refused' deliberation ended that way. The raw
    -- model text is deliberately NOT stored on the unparseable path: it is
    -- untrusted content (§19.4), and keeping a prose blob invites a later
    -- reader to treat it as a result. The validation error is the record.
    failure_reason       TEXT,

    created_at_utc       TEXT NOT NULL
);

CREATE INDEX idx_deliberations_cell ON deliberations (cell_id);


CREATE TABLE proposals (
    proposal_id          TEXT PRIMARY KEY,
    deliberation_id      TEXT NOT NULL REFERENCES deliberations(deliberation_id),
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),

    kind                 TEXT NOT NULL CHECK (kind IN (
                             'experiment', 'strategy', 'spend_request', 'abstain'
                         )),
    summary              TEXT NOT NULL,
    rationale            TEXT NOT NULL,

    -- §23.1's risk tiers. Recorded, and nothing consumes it: §23's approval
    -- queue does not exist. A proposal is inert either way, so the tier is
    -- currently documentation of what the Cell *thinks* it is asking for --
    -- and specifically not a permission, since a Cell that could set its own
    -- risk tier and have it honoured would simply always say LOW.
    risk_tier            TEXT NOT NULL CHECK (risk_tier IN (
                             'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
                         )),

    -- What the Cell estimates it would cost. An estimate, never a charge:
    -- nothing debits a ledger account from this column.
    estimated_cost_minor_units INTEGER NOT NULL CHECK (estimated_cost_minor_units >= 0),

    payload_json         TEXT NOT NULL,
    created_at_utc       TEXT NOT NULL
);

CREATE INDEX idx_proposals_cell ON proposals (cell_id);
CREATE INDEX idx_proposals_deliberation ON proposals (deliberation_id);


-- A deliberation's registered predictions (§8.5). A link table rather than a
-- column on prediction_register, because that table is hash-chained: adding a
-- field to it would either change what the chain covers or add an unchained
-- column to a table whose whole point is that its contents are committed.
CREATE TABLE deliberation_predictions (
    deliberation_id      TEXT NOT NULL REFERENCES deliberations(deliberation_id),
    prediction_id        TEXT NOT NULL REFERENCES prediction_register(prediction_id),
    PRIMARY KEY (deliberation_id, prediction_id)
);
