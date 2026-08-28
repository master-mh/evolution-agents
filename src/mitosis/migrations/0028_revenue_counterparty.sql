-- Who paid, in the only form §16.3 permits
-- (SPEC.md §12.1, §12.2, §16.3, §21.2, §2.5, §3.4; ADR-060, ADR-061).
--
-- §12.1's first two dimensions — buyer type and revenue recurrence — both turn
-- on knowing whether one buyer paid twice. `revenue.record_revenue` has always
-- recorded who paid as free-text `source` ("an invoice id, a customer
-- reference, 'manual'"), so two payments from one buyer are indistinguishable
-- from one payment each from two, and ADR-060 had to ship a one-dimensional
-- archive because of it.
--
-- **The column goes on the transaction, not in a side table**, because who paid
-- is a fact about the payment and the payment is a ledger row. A side table
-- could be dropped, edited or fall out of step with the transaction it
-- describes; a column on `ledger_transactions` is covered by §3.4's hash chain,
-- so altering it after the fact invalidates every transaction that followed.
-- That matters here more than it looks: this field decides whether a Cell
-- occupies §12.1's `repeat` niche, which is a fitness-bearing claim.
--
-- `metadata_json` was the tempting home and is the wrong one. It is **not** in
-- the hash preimage (`ledger._compute_hash` covers the transaction's identifying
-- fields and its canonicalised entries, and no metadata on either), so a
-- counterparty stored there would be silently editable — the one property this
-- field must not have.
--
-- **The CHECK is the §16.3 guarantee, not a validation nicety.** The column can
-- physically hold nothing but 64 lowercase hex characters, so a raw email
-- address, account handle or legal name cannot be written to it by any caller,
-- present or future, whether or not that caller remembered to hash. ADR-047's
-- lesson applied a second time: before building a seam to enforce something,
-- ask whether the schema can make it unrepresentable instead. `counterparty.is_hash`
-- is the same rule in Python and `test_counterparty.py` pins the two together.
--
-- No NOT NULL, and no backfill. Revenue that predates the key genuinely has no
-- counterparty recorded, and inventing one from `source` would be the fabricated
-- attribution the whole module exists to prevent. `novelty._revenue_recurrence`
-- treats a NULL as an unmeasured payment and abstains rather than guessing —
-- see the monotone rule there, which can still report `repeat` from a partial
-- record but never `one_off`.
--
-- ADD COLUMN rather than a table rebuild: the chain hash covers values, not
-- storage, so a rebuild would have been safe, but `ledger_transactions` is the
-- one table in this colony worth not rewriting for a nullable field.

ALTER TABLE ledger_transactions ADD COLUMN counterparty_hash TEXT
    CHECK (
        counterparty_hash IS NULL
        OR (length(counterparty_hash) = 64 AND counterparty_hash NOT GLOB '*[^0-9a-f]*')
    );

CREATE INDEX idx_ledger_transactions_counterparty
    ON ledger_transactions(counterparty_hash)
    WHERE counterparty_hash IS NOT NULL;
