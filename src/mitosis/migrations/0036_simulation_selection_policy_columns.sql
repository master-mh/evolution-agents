-- Records which SelectionPolicy a simulation run actually used (implementation
-- brief Slice G; docs/DECISIONS.md's Slice G ADR).
--
-- `simulation_runs.policy_name`/`policy_version` (migration 0035) already
-- name the *Cell* policy (`SimulationPolicyProvider`, what a mock Cell
-- proposes) -- a wholly different decision from *which Cell reproduces*,
-- which is `SelectionPolicy`'s job. `runner._record_run_start` takes a
-- `selection: SelectionPolicy` parameter and has never read
-- `selection.name`/`.version` from it, so for a slice whose entire purpose is
-- comparing different selection policies, nothing at the run level could
-- say which one a given run used -- only a per-epoch
-- `simulation_selection_decision` audit event could. Two nullable columns,
-- no rebuild needed (a plain `ADD COLUMN` with no CHECK/NOT NULL/computed
-- default is a legal SQLite ALTER, the same shape migration 0033's
-- `repair_model_call_id` already used) -- nullable because a row from before
-- this migration genuinely never recorded a selection policy, and a
-- fabricated backfill would be a fabricated claim about a fact the row never
-- captured.
ALTER TABLE simulation_runs ADD COLUMN selection_policy_name TEXT;
ALTER TABLE simulation_runs ADD COLUMN selection_policy_version TEXT;
