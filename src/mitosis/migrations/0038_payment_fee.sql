-- A payment fee names the charge it was taken on
-- (SPEC.md §1.1, §2.2, §3.4, §3.6, §5.1; ADR-098).
--
-- §1.1's REAL_SETTLED_NET_PROFIT subtracts "payment fees", §2.2 lists payment
-- processing among USD_REAL's external money, and §3.6 reconciles the ledger
-- against payment-processor transactions — which report a fee per charge. No
-- path could record one: every USD_REAL charge the kernel knew belonged to a
-- model call.
--
-- **A column beside migration 0037's, not a reuse of it.** `reverses_transaction_id`
-- means "takes this payment back"; a fee takes nothing back from the buyer, and a
-- column whose name lies about half its rows is how a reader sums the wrong thing.
-- In the hash preimage when set and absent otherwise (`ledger._compute_hash`), so
-- no existing hash moves.
--
-- **The CHECK ties the link to exactly one type, both ways** (ADR-047): a
-- `payment_fee` that names no charge, and a charge link on any other type, are
-- unrepresentable. What SQL cannot say — that the target is a revenue payment or
-- a chargeback — is checked in `payment_fees.record_payment_fee`, inside the
-- write lock.
--
-- No amount, processor or category column: the amount is the fee's own entries,
-- and a processor is not a counterparty §16.3's digest was built for.

ALTER TABLE ledger_transactions ADD COLUMN charged_on_transaction_id TEXT
    REFERENCES ledger_transactions(transaction_id)
    CHECK (
        (charged_on_transaction_id IS NOT NULL) = (transaction_type = 'payment_fee')
    );

CREATE INDEX idx_ledger_transactions_charged_on
    ON ledger_transactions(charged_on_transaction_id)
    WHERE charged_on_transaction_id IS NOT NULL;
