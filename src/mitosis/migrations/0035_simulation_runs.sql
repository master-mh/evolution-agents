-- The Phase 2 flight simulator's own audit trail (SPEC.md §7, §8, §28 Phase 2;
-- implementation brief Slice F).
--
-- Genuinely new information, not a second answer to a question another table
-- already owns: nothing existing records that a `mitosis simulate` invocation
-- happened at all. Shaped like `scheduler_ticks` (migration 0014) -- one row
-- per run, config and outcome, nothing derived that a query could recompute.
-- The rich per-epoch detail (population/diversity time series, per-epoch
-- outcomes) lives in the manifest file `--output` writes, not here; this row
-- is what lets a later query find and verify that a run occurred without
-- opening the manifest.

CREATE TABLE simulation_runs (
    run_id                TEXT PRIMARY KEY,
    scenario_name         TEXT NOT NULL,
    master_seed           INTEGER NOT NULL,
    code_version          TEXT NOT NULL,
    environment_name      TEXT NOT NULL,
    environment_version   TEXT NOT NULL,
    policy_name           TEXT NOT NULL,
    policy_version        TEXT NOT NULL,
    population_target     INTEGER NOT NULL,
    epochs_target         INTEGER NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at_utc        TEXT NOT NULL,
    finished_at_utc       TEXT,
    manifest_path         TEXT
);

CREATE INDEX idx_simulation_runs_started ON simulation_runs (started_at_utc);
