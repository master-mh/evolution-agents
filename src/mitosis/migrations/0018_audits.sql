-- §23.2's independent Auditor summary (SPEC.md §23.2, §10.4, §0.3, §29.10).
--
-- `approval_requests` has carried an `auditor_summary` of NULL since ADR-027,
-- correctly reporting as unavailable: §23.2 requires the summary be
-- *independent*, and §0.3 forbids the proposing Cell writing it. The Auditor
-- type in the taxonomy has existed since Phase 1 and `death.kill_for_negative_ev`
-- already validates a concurring one — what has never existed is any way for an
-- Auditor to actually produce an audit. This table is that.
--
-- **§10.4 forbids the obvious design, and this schema is shaped by the ban.**
-- The obvious Auditor wakes, reads the proposal, and writes prose flagging
-- whatever looks risky. §10.4 says Auditor reward is precision-weighted:
-- "reward valid detected errors, prevented loss, reproducible findings;
-- penalise wrongful flags, excessive false positives, unnecessary blocking,
-- unverified accusations" — and §29's acceptance criterion 10 is literally
-- "Wrongful Auditor flags are penalised". Prose cannot be penalised. An
-- Auditor whose flags cost it nothing will flag everything, which is
-- maximally cautious, maximally useless, and looks responsible while being so.
--
-- So every audit carries a **probability and a registered prediction**, not
-- only a verdict. The flag resolves later through §8.5's hash-chained register
-- and is scored with the same proper scoring rule every other Cell is judged
-- by, which makes precision-weighting computable from machinery that already
-- exists rather than from a new reputation system.
--
-- **The Auditor does not write the claim it is scored on.** `prediction_id`
-- points at a claim the *kernel* composed from the request. §0.3 — "a Cell may
-- explain a result; it may never define the canonical result" — applies to the
-- independent evaluator too: an Auditor that phrased its own claim could phrase
-- an unfalsifiable one and never be wrong.
CREATE TABLE audits (
    audit_id            TEXT PRIMARY KEY,

    request_id          TEXT NOT NULL REFERENCES approval_requests(request_id),
    proposal_id         TEXT NOT NULL REFERENCES proposals(proposal_id),

    -- Independence, recorded on both sides so it is checkable after the fact
    -- and not only at write time.
    auditor_cell_id     TEXT NOT NULL REFERENCES cells(cell_id),
    subject_cell_id     TEXT NOT NULL REFERENCES cells(cell_id),

    -- `rejected` covers a reply that produced no usable audit: malformed JSON,
    -- a schema violation, or a verdict incoherent with its own probability.
    --
    -- **A rejected audit is recorded rather than raised, and the reason is the
    -- money.** The gateway call commits before the reply is parsed (ADR-022),
    -- so by the time a reply turns out to be unusable the Auditor has already
    -- paid for it. Raising would leave real spend with nothing explaining it,
    -- and would hide an Auditor that reliably produces garbage — which is
    -- itself a §10.4 fitness fact. `deliberations` records unparseable replies
    -- for exactly this reason.
    status              TEXT NOT NULL CHECK (status IN ('recorded', 'rejected')),
    failure_reason      TEXT,

    -- §23.2's field: what the operator actually reads. NULL only when the
    -- audit was rejected, and the CHECK below is what stops a rejected row
    -- ever being mistaken for an opinion.
    verdict             TEXT CHECK (verdict IN ('concern', 'no_concern')),
    summary             TEXT,

    -- What the verdict costs if it is wrong. Strictly between 0 and 1 for the
    -- reason prediction_register gives: the log score of a confident-and-wrong
    -- claim is infinite, and one such flag would pin an Auditor's mean at -inf
    -- permanently, making the population unorderable.
    probability         REAL CHECK (probability IS NULL
                                    OR (probability > 0 AND probability < 1)),
    prediction_id       TEXT REFERENCES prediction_register(prediction_id),

    -- The audit costs a model call, which is §10.4's governance overhead made
    -- real. Recorded per audit so that ratio is computable when it is built.
    model_call_id       TEXT REFERENCES model_calls(model_call_id),
    wake_reason         TEXT NOT NULL,

    created_at_utc      TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,

    -- A recorded audit always carries all of verdict, summary, probability and
    -- prediction. This is the invariant that keeps §10.4's precision-weighting
    -- honest: an opinion the operator can read is always an opinion the
    -- Auditor is scored on, with no shape in between. Stated as a table
    -- constraint because it spans columns, and it must follow every column
    -- definition — SQLite rejects a table constraint that appears mid-list.
    CHECK (
        (status = 'rejected' AND verdict IS NULL AND probability IS NULL
                             AND prediction_id IS NULL AND failure_reason IS NOT NULL)
        OR
        (status = 'recorded' AND verdict IS NOT NULL AND summary IS NOT NULL
                             AND probability IS NOT NULL AND prediction_id IS NOT NULL)
    )
);

CREATE INDEX idx_audits_request ON audits (request_id);
CREATE INDEX idx_audits_auditor ON audits (auditor_cell_id);

-- One *opinion* per Auditor per request. An Auditor revising its own audit
-- after the fact is the same defect re-resolving a prediction would be: a
-- record that can be improved once the outcome is visible is not evidence. A
-- *second* Auditor is allowed and is a different row.
--
-- **Partial, on `status = 'recorded'`, and the partiality is the point.** A
-- rejected reply is an attempt, not an opinion — it carries no verdict and
-- stakes nothing. A plain UNIQUE would let one malformed reply permanently
-- disqualify that Auditor from that request, so a model's bad JSON would
-- silently decide who is allowed to review what. Every attempt is still kept,
-- each under its own idempotency key, which is what keeps a Cell that burns
-- money producing garbage visible in `auditor.precision`.
CREATE UNIQUE INDEX idx_audits_one_opinion_per_auditor
    ON audits (request_id, auditor_cell_id)
    WHERE status = 'recorded';
