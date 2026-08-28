-- §12.1's third dimension is a declaration, not a query
-- (SPEC.md §12.1, §0.3, §16.3, §3.6, §23.5, §20.3; ADR-041, ADR-059, ADR-061).
--
-- ADR-061 built the inbound counterparty key and proved it does **not** unblock
-- `buyer_type`: a salted digest gives equality, never identity, and human
-- consumer / small business / enterprise / machine is a claim about who the
-- buyer *is*. §16.3 keeps customer identity out of this colony permanently, so
-- there is nothing here to classify from and no query will ever produce one.
--
-- What is left is somebody who can see the buyer saying so. That is §0.3's own
-- answer — canonical metrics come from "independent systems: payment records
-- ... external evaluators, Auditor Cells, and the ledger", and an operator
-- reading an invoice is an external evaluator.
--
-- **This is ADR-041's shape, deliberately, and not a new mechanism.**
-- `rights_attestations` already records a person establishing a fact the colony
-- cannot derive: subject, claim, basis, who, when; append-only; latest wins;
-- withdrawal is a new row rather than a flag. Every one of those decisions is
-- right here for the same reasons, so this table copies them rather than
-- re-deciding them.
--
-- **The subject is a counterparty digest, which is what makes it §16.3-safe.**
-- The operator attests using the party's name; the kernel hashes it and stores
-- only the digest, exactly as `record_revenue` does. So the colony learns that
-- *some* buyer is an enterprise and still cannot say who any buyer is. Attaching
-- the type to the *payment* instead would have re-asked the same question for
-- every invoice; attaching it to the *genome* would have made it a claim about
-- an idea rather than an observation of who actually paid, which is not what a
-- behavioural descriptor is.
--
-- **NULL `buyer_type` is a withdrawal, and it carries its own basis.** Straight
-- from ADR-041: withdrawing by attesting "no position" leaves *why* in the
-- record, where a `revoked` flag would leave an absence. It is why the column is
-- nullable while `basis` and `attested_by` are not — a withdrawal is an
-- attestation, so it is held to the same standard as a claim. Latest-wins
-- supersession handles a correction; this handles a retraction, and without it
-- an operator who mis-typed could only replace one wrong assertion with another.
--
-- No idempotency key, matching `rights_attestations`: attesting twice is two
-- rows and the later one wins. An attestation is a statement someone made, and
-- two statements are two facts even when they agree.

CREATE TABLE buyer_attestations (
    attestation_id     TEXT PRIMARY KEY,

    -- The same digest and the same rule as `ledger_transactions.counterparty_hash`
    -- (migration 0028), repeated rather than referenced: there is nothing to
    -- point a foreign key at, because a counterparty is not a row anywhere —
    -- it is a value appearing on payments. `counterparty.attest_buyer_type`
    -- refuses a party with no recorded payment, which is the check a foreign
    -- key would have been.
    counterparty_hash  TEXT NOT NULL
        CHECK (length(counterparty_hash) = 64
               AND counterparty_hash NOT GLOB '*[^0-9a-f]*'),

    -- §12.1's four bins, enforced by the schema rather than by the writer. The
    -- alternative was a generic `dimension`/`value` judgments table serving
    -- several callers; it cannot state this constraint, and the constraint is
    -- most of the value (ADR-062 records why the generic table was refused).
    -- NULL is a withdrawal, not an unknown bin.
    buyer_type         TEXT CHECK (buyer_type IS NULL OR buyer_type IN (
                           'human_consumer', 'small_business', 'enterprise', 'machine'
                       )),

    -- Where the operator got this, required and non-empty for §20.3's reason in
    -- ADR-041's words: the record has to say who believed what and why. A buyer
    -- type is not a liability the way a rights position is, but it *is* a
    -- selection input — it decides which §12.1 niche a genome occupies — and an
    -- unexplained selection input is how a fitness signal gets fabricated.
    basis              TEXT NOT NULL CHECK (basis <> ''),
    attested_by        TEXT NOT NULL CHECK (attested_by <> ''),
    attested_at_utc    TEXT NOT NULL
);

CREATE INDEX idx_buyer_attestations_counterparty
    ON buyer_attestations (counterparty_hash);
