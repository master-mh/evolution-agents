-- A refund or chargeback names the payment it reverses
-- (SPEC.md §1.1, §2.2, §10.2, §16.3, §3.4, §3.6; §28 Phase 9; ADR-097).
--
-- §1.1's REAL_SETTLED_NET_PROFIT subtracts "refunds - chargebacks" from settled
-- revenue, §10.2 lists "refund/chargeback rate" as a commercial fitness
-- dimension, and §28 Phase 9's acceptance requires "refunds/obligations
-- tracked". `revenue.record_revenue` refused non-positive amounts and nothing
-- else could take money back, so a refunded Cell kept its full apparent
-- earnings and every reader of revenue — §10.5's domination, §25.2's read-back,
-- the Cell's own record — overstated it.
--
-- **The link goes on the transaction, not in a side table**, for migration
-- 0028's reason: which payment a reversal undoes decides how much of a Cell's
-- revenue survives, which is a fitness-bearing claim, and a column on
-- `ledger_transactions` is covered by §3.4's hash chain (`ledger._compute_hash`
-- adds the key to the preimage only when it is set, so no existing hash moves).
-- A side table could be edited to point a refund at a different sale without
-- the chain noticing.
--
-- **No amount and no kind column.** The amount is the reversal's own entries and
-- the kind is its `transaction_type`; storing either again would be §2.5's
-- cached derivation, a second answer that can disagree with the ledger.
--
-- **The CHECK makes both mistakes unrepresentable** (ADR-047): a reversal type
-- that names no payment, and a link on any other type. The foreign key refuses
-- a link to a transaction that does not exist. What SQL cannot say — that the
-- target is a `cell_revenue` payment with enough left to reverse — is checked in
-- `revenue.record_reversal`, inside the write lock.
--
-- Adding a reversal kind therefore needs a migration, deliberately: a new way to
-- take money back is a change to what a Cell's revenue means.

ALTER TABLE ledger_transactions ADD COLUMN reverses_transaction_id TEXT
    REFERENCES ledger_transactions(transaction_id)
    CHECK (
        (reverses_transaction_id IS NOT NULL)
        = (transaction_type IN ('cell_refund', 'cell_chargeback'))
    );

CREATE INDEX idx_ledger_transactions_reverses
    ON ledger_transactions(reverses_transaction_id)
    WHERE reverses_transaction_id IS NOT NULL;
