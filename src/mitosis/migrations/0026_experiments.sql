-- The object seven sections reference and none defines (SPEC.md §2.6, §9.2,
-- §10.5, §13.1, §15.1, §25.1, §27.2, §31; Charter C3; ADR-031, ADR-041; ADR-043).
--
-- `experiment_id` has been a column in `ledger_entries` and `ledger_transactions`
-- since migration 0001, in `model_calls` since 0010 and `predictions` since 0012;
-- `coroner_reports.experiment_ids_json` since 0007; `colony_config.
-- max_parallel_experiments` since 0003; `ProposalKind.EXPERIMENT` since 0013.
-- It is plumbed as a live parameter through `gateway`, `prediction` and
-- `ledger`, and `mitosis predict --experiment <id>` has always accepted any
-- string and validated nothing. **The foreign key was exposed to the operator
-- before the table existed.** This is the table.
--
-- **There is deliberately no `experiment_results`**, despite §31 listing one.
-- §31 says "suggested entities" and does not mark it Phase 1 — and §2.5, the
-- section immediately above the one that defines an experiment report, is
-- "Balances are derived": authoritative figures are computed from ledger
-- entries and never cached (Charter C3). §2.6's report is six dimensions of
-- money, resource and reality gap, every one of which is already derivable once
-- `experiment_id` is populated. A stored results table would be the place §0.3
-- leaks back in — a Cell may explain a result and may never define one, and the
-- surest way to keep that true is to give it no column to write. Same reasoning
-- that keeps `proposal.py` free of any field for what a Cell earned.

CREATE TABLE experiments (
    experiment_id      TEXT PRIMARY KEY,
    cell_id            TEXT NOT NULL REFERENCES cells(cell_id),

    -- The §23 request that asked for it, when a Cell proposed it. **There is no
    -- 'proposed' status** because the approval queue already holds that state:
    -- a row here means the experiment is real. Duplicating the queue would give
    -- the colony two answers to "is this waiting on a person".
    proposal_id        TEXT REFERENCES proposals(proposal_id),

    -- What the Cell is testing. §10.5's coroner wants "final hypotheses"; this
    -- is where a hypothesis lives while it is still live.
    hypothesis         TEXT NOT NULL,

    -- §13.1's "expected experiment cost", the numerator of `normalised_cost`.
    -- **Recorded and deliberately not load-bearing.** The 2026-08-06 live run
    -- found `estimated_cost_minor_units` was 0 on all eight proposals from both
    -- models, including proposed experiments — models cannot price work in a
    -- unit they have never seen a reference for. A cap resting on this number
    -- would be a cap a Cell sets for itself. What actually bounds an experiment
    -- is the reservation and spend machinery that already exists.
    expected_cost_minor_units INTEGER NOT NULL DEFAULT 0
                              CHECK (expected_cost_minor_units >= 0),

    -- §25.1's rung this experiment runs at. Rung 1 is "flight simulator", rung 7
    -- is "tiny capped live experiment" — so the rung says whether real money can
    -- be involved at all. **Recorded, not enforced here**: `autonomy.
    -- real_spending`, the grant path and the circuit breaker already gate real
    -- spend, and a second check would be the weaker copy ADR-039 warns about.
    -- The §2.6 report shows spend per book against the rung, which is what makes
    -- a mismatch visible without inventing a rule.
    ladder_rung        INTEGER NOT NULL DEFAULT 1
                       CHECK (ladder_rung BETWEEN 1 AND 9),

    status             TEXT NOT NULL CHECK (status IN (
                           'running',    -- counts against §9.2's simultaneous cap
                           'concluded',  -- ran to an answer, whatever the answer
                           'abandoned'   -- stopped without one
                       )),

    created_at_utc     TEXT NOT NULL,
    concluded_at_utc   TEXT,

    -- Who ended it and what they said. A Cell may end its own experiment: that
    -- is declaring it *finished*, not declaring that it *worked*, and the
    -- difference is §0.3's whole line. Nothing here is an outcome — the outcome
    -- is derived from the ledger, `model_calls` and the prediction register.
    concluded_by       TEXT,
    conclusion_note    TEXT,

    CHECK (status = 'running' OR concluded_at_utc IS NOT NULL),
    CHECK (status = 'running' OR concluded_by IS NOT NULL),
    CHECK (status <> 'running' OR concluded_at_utc IS NULL)
);

-- §15.1: context assembly selects from "immutable genome, **current
-- experiment**, ..." — singular. §27.2's dashboard says "current
-- experiment/stage" for the same reason. One running experiment per Cell is
-- therefore the spec's shape, and a partial unique index makes it
-- *unrepresentable* rather than checked — the move ADR-018, ADR-033 and ADR-035
-- all make, applied to a state instead of an identity.
CREATE UNIQUE INDEX idx_experiments_one_running_per_cell
    ON experiments (cell_id) WHERE status = 'running';

-- §9.2's "maximum simultaneous experiments" counts this.
CREATE INDEX idx_experiments_status ON experiments (status);
