-- The one legal identity §28 Phase 9 requires, declared by a person
-- (SPEC.md §0.3, §3.6, §16.3, §28 Phase 9; ADR-100).
--
-- Phase 9 is "one legal business identity, one narrow product class, one
-- merchant channel". The colony had no record of whose identity it trades under,
-- so every sale, refund and fee recorded since ADR-097 attributes to an entity
-- nobody named. This is that record.
--
-- **§16.3 lists legal identity as non-inheritable, and `genome.py` already
-- refuses a `legal_identity` gene** ("Phase 9 has exactly one, and it is the
-- colony's"). That tripwire was written before anything could declare one; this
-- is the other half of the same rule. The identity is the colony's, an operator
-- states it, and no Cell can carry, propose or inherit it.
--
-- **An operator attestation, exactly like `rights_attestations` (ADR-041) and
-- `buyer_attestations` (ADR-062):** append-only, latest wins by `rowid` rather
-- than by wall clock, withdrawal is a new row asserting no identity, and the
-- basis is required — §3.6's habit applied to a record that decides who is
-- liable for a trade.
--
-- **The account is a label and the schema will not hold anything else.** A real
-- account number, card or IBAN must never enter this database: the CHECKs below
-- refuse a run of eight or more digits and the obvious secret prefixes, so
-- "Stripe account: personal" is storable and "4111111111111111" is not, whatever
-- a caller intends. `trial_identity.attest` refuses more (any twelve digits in
-- total, more markers, a length cap) with a message naming what to write
-- instead — but the guarantee that a number cannot be stored is the schema's,
-- not the caller's.
--
-- A withdrawal is `legal_entity IS NULL`, and then the other three identity
-- fields must be NULL too: half an identity in force is not a state.

CREATE TABLE trial_identity_attestations (
    attestation_id        TEXT PRIMARY KEY,

    -- NULL means "no identity in force" — a withdrawal, superseding whatever
    -- stood before it. Never an unknown.
    legal_entity          TEXT,
    jurisdiction          TEXT,
    payment_account_label TEXT,

    basis                 TEXT NOT NULL CHECK (length(trim(basis)) > 0),
    attested_by           TEXT NOT NULL CHECK (length(trim(attested_by)) > 0),
    attested_at_utc       TEXT NOT NULL,

    -- All three together, or none of them.
    CHECK (
        (legal_entity IS NULL AND jurisdiction IS NULL AND payment_account_label IS NULL)
        OR (legal_entity IS NOT NULL AND jurisdiction IS NOT NULL
            AND payment_account_label IS NOT NULL)
    ),

    CHECK (legal_entity IS NULL OR length(trim(legal_entity)) > 0),
    CHECK (jurisdiction IS NULL OR length(trim(jurisdiction)) > 0),

    -- A label, never an account. Eight consecutive digits is already a sort
    -- code plus a stub; a card, an IBAN or a full account number cannot pass.
    CHECK (
        payment_account_label IS NULL
        OR (
            length(trim(payment_account_label)) > 0
            AND length(payment_account_label) <= 200
            AND payment_account_label NOT GLOB
                '*[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*'
            AND lower(payment_account_label) NOT LIKE '%sk_live%'
            AND lower(payment_account_label) NOT LIKE '%sk-%'
            AND lower(payment_account_label) NOT LIKE '%pk_live%'
            AND lower(payment_account_label) NOT LIKE '%whsec%'
            AND lower(payment_account_label) NOT LIKE '%-----begin%'
            AND lower(payment_account_label) NOT LIKE '%password%'
        )
    )
);
