-- A held seller's working-capital advance (SPEC.md §2.3, §2.5, §28 Phase 9;
-- ADR-106, ADR-112).
--
-- Live, 2026-09-27: under the operator's 100% hold, the colony's first sale
-- would leave its seller at -80 cents — the whole $9 held for 120 days, the
-- processor's fee taken from cash (ADR-106, decision 6) — and a Cell with no
-- cash cannot wake. The seller that proved the product sells would be the one
-- Cell unable to work for four months.
--
-- **The buyer's hold is untouched.** The advance comes from the colony's own
-- capital (`seed_bank`, "capital staged for allocation to Cells"), never from
-- `liability_reserve`, so every refund is still met in full from money set
-- aside for it. What moves is the colony's risk: a refunded sale leaves its
-- advance unrepaid, which costs the colony exactly what a `fund-cell` of the
-- same amount would have.
--
-- **The policy is a person's**, append-only, latest wins by rowid — the reserve
-- policy's shape (0042). Unlike a reserve, an advance is optional: 0 basis
-- points is "no advances", and is how a policy is withdrawn.
--
-- No table of advances and no `outstanding` column. What a Cell owes is derived
-- from the ledger on read (§2.5): its advances less its repayments.

CREATE TABLE held_seller_advance_policies (
    policy_id                   TEXT PRIMARY KEY,
    -- Share of each held sale advanced to its seller: 10000 is the whole hold.
    advance_basis_points        INTEGER NOT NULL
        CHECK (advance_basis_points BETWEEN 0 AND 10000),
    -- The most one Cell may owe at once, across all its held sales.
    max_outstanding_minor_units INTEGER NOT NULL
        CHECK (max_outstanding_minor_units >= 0),
    declared_by                 TEXT NOT NULL CHECK (length(trim(declared_by)) > 0),
    declared_at_utc             TEXT NOT NULL,
    note                        TEXT NOT NULL DEFAULT ''
);
