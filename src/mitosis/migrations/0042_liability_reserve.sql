-- A real sale is held against its refunds until the window for them closes
-- (SPEC.md §2.3, §10.2, §16.3, §28 Phase 9; ADR-106).
--
-- §28 Phase 9 asks for "full liability reserves" and nothing posted to
-- `liability_reserve`, a §31 Phase-1 account since migration 0001. Two pieces:
--
-- **The policy is a person's, append-only, latest wins by rowid.** How much of
-- a sale to hold and for how long depends on the merchant's refund terms and the
-- card networks' chargeback window — facts about the world the kernel cannot
-- know and must not invent (ADR-042). A new row supersedes; nothing is updated,
-- so a hold can always be traced to the policy in force when it was taken. There
-- is no "no reserve" row: Phase 9 has no reserve-free mode to withdraw into.
--
-- **The hold and its releases name the payment they provision for**, in a
-- column beside 0037's and 0038's rather than a reuse of either: a hold neither
-- takes a payment back nor charges a fee on it. In the hash preimage when set
-- and absent otherwise (`ledger._compute_hash`), so no existing hash moves. The
-- CHECK ties the link to exactly the two types, both ways (ADR-047); what SQL
-- cannot say — that the target is a USD_REAL revenue payment — is checked in
-- `liability.py` inside the write lock.
--
-- No `held_until` column anywhere. When a hold ends is derived from its own
-- hash-chained `created_at_utc` and the policy in force at that instant, so it
-- is not a second answer that could disagree with the ledger (§2.5), and a later
-- policy can never shorten a hold already taken.

CREATE TABLE liability_reserve_policies (
    policy_id           TEXT PRIMARY KEY,
    -- Share of each sale held, in basis points: 10000 is the whole sale.
    hold_basis_points   INTEGER NOT NULL
        CHECK (hold_basis_points BETWEEN 1 AND 10000),
    -- Days from the sale until nothing can be refunded or charged back.
    window_days         INTEGER NOT NULL CHECK (window_days BETWEEN 1 AND 730),
    declared_by         TEXT NOT NULL CHECK (length(trim(declared_by)) > 0),
    declared_at_utc     TEXT NOT NULL,
    note                TEXT NOT NULL DEFAULT ''
);

ALTER TABLE ledger_transactions ADD COLUMN provisions_for_transaction_id TEXT
    REFERENCES ledger_transactions(transaction_id)
    CHECK (
        (provisions_for_transaction_id IS NOT NULL)
        = (transaction_type IN ('liability_hold', 'liability_release'))
    );

CREATE INDEX idx_ledger_transactions_provisions_for
    ON ledger_transactions(provisions_for_transaction_id)
    WHERE provisions_for_transaction_id IS NOT NULL;
