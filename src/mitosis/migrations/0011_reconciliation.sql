-- Provider-invoice reconciliation (SPEC.md §24.1 "reconciled cost", §3.6).
-- Migrations are append-only per §30.1 — never edit a shipped migration.

-- `reconciled_micro_usd` already exists (migration 0010) and is §24.1's
-- required field. These two record where the figure came from and when, so a
-- reconciled row can be audited without joining back to audit_events. The
-- adjustment *amount* is deliberately NOT stored: it is derivable from the
-- ledger, and Charter C3 says balances are derived, never authoritative.
ALTER TABLE model_calls ADD COLUMN reconciled_at_utc TEXT;
ALTER TABLE model_calls ADD COLUMN reconciliation_source TEXT;

CREATE INDEX idx_model_calls_reconciled ON model_calls(reconciled_at_utc);
