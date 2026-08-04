-- Prediction register (SPEC.md §8.5, Amendment A14; §31 `prediction_register`).
--
-- Predictions are appended *before* outcomes are known, each hashed and
-- timestamped, and scored with a proper scoring rule when the outcome arrives.
-- The point is commitment: a prediction that can be edited after the fact
-- measures nothing.
--
-- Hash-chained the same way ledger_transactions is, and for the same reason. A
-- per-row content hash alone proves nothing against an editor who recomputes
-- it; chaining means altering any prediction invalidates every prediction after
-- it. This is what makes "register-before-outcome" an enforceable claim rather
-- than a convention.
--
-- The hash covers the *prediction* only, never the outcome. Resolution writes
-- the outcome columns once (refused if already set, exactly as
-- reconciliation.reconciled_at_utc is), so the commitment stays intact while the
-- row still answers "what actually happened" in one place.

CREATE TABLE prediction_register (
    prediction_id        TEXT PRIMARY KEY,
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),
    experiment_id        TEXT,

    -- What is being predicted, as a claim that is unambiguously true or false
    -- once resolved. Brier and log scores are defined over binary outcomes
    -- (§8.5 names exactly those two rules), so a continuous quantity is
    -- predicted by stating a threshold claim: "revenue >= 50 minor units".
    claim                TEXT NOT NULL,

    -- P(claim is true), strictly between 0 and 1. The bounds are exclusive on
    -- purpose: the log score of a confident-and-wrong prediction is infinite,
    -- and one such prediction would make a Cell's mean score -inf forever,
    -- destroying the ordering that selection needs.
    probability          REAL NOT NULL CHECK (probability > 0 AND probability < 1),

    -- When the outcome should be known. A prediction resolved at the Cell's own
    -- discretion produces a self-selected calibration curve, so overdue and
    -- unresolved predictions are reportable (see prediction.overdue).
    resolves_by_utc      TEXT NOT NULL,

    created_at_utc       TEXT NOT NULL,
    previous_hash        TEXT,
    prediction_hash      TEXT NOT NULL,

    -- Outcome. All NULL until resolved; written exactly once.
    outcome              INTEGER CHECK (outcome IN (0, 1)),
    resolved_at_utc      TEXT,
    resolution_source    TEXT,
    brier_score          REAL,
    log_score            REAL,

    idempotency_key      TEXT NOT NULL UNIQUE
);

CREATE INDEX idx_prediction_register_cell ON prediction_register(cell_id);
CREATE INDEX idx_prediction_register_unresolved
    ON prediction_register(resolved_at_utc, resolves_by_utc);
