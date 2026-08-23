-- The external-action registry (SPEC.md §21, §23.4, §16.3, §20.1, §28 Phase 8/9,
-- §31; Amendment A11; ADR-036).
--
-- §21.2's two verbs are **track** and **prevent**. Neither is *send*. §28's
-- Phase 8 acceptance is "all external action remains manual", so nothing behind
-- this schema transmits anything: a human performs the action, and the kernel
-- records what was done and refuses what would collide with what a sibling is
-- already doing. That refusal is Phase 9's acceptance criterion — "no duplicate
-- or conflicting customer contact" — built a phase early, because the guarantee
-- is worthless if it arrives at the same time as the first real customer.
--
-- **The counterparty is stored as a salted hash and never as itself.** §16.3
-- makes "customer identity" and "private customer data" non-inheritable and
-- §20.1 tracks personal data because holding it is a liability. Everything
-- §21.2 asks for needs *equality*, not identity: "have we contacted this person
-- before", "did this person complain". Both stay answerable. "Who have we
-- contacted" does not, from these tables, by anyone — including the colony. A
-- `customers` table is the obvious design and is the one §16.3 warns about.

PRAGMA foreign_keys = OFF;

-- --------------------------------------------------------------------------
-- 1. `proposals.kind` gains 'external_action'.
--
-- Same rebuild as migration 0019, for the same reason: SQLite cannot ALTER a
-- CHECK constraint, and `db.migrate` runs each file through `executescript`,
-- which commits before it starts and is therefore outside any transaction.
-- --------------------------------------------------------------------------
CREATE TABLE proposals_rebuilt (
    proposal_id          TEXT PRIMARY KEY,
    deliberation_id      TEXT NOT NULL REFERENCES deliberations(deliberation_id),
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),

    kind                 TEXT NOT NULL CHECK (kind IN (
                             'experiment', 'strategy', 'spend_request',
                             'tool_request', 'external_action', 'abstain'
                         )),
    summary              TEXT NOT NULL,
    rationale            TEXT NOT NULL,

    risk_tier            TEXT NOT NULL CHECK (risk_tier IN (
                             'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
                         )),

    estimated_cost_minor_units INTEGER NOT NULL CHECK (estimated_cost_minor_units >= 0),

    derived_from_untrusted INTEGER NOT NULL DEFAULT 0
                           CHECK (derived_from_untrusted IN (0, 1)),

    payload_json         TEXT NOT NULL,
    created_at_utc       TEXT NOT NULL
);

INSERT INTO proposals_rebuilt (
    proposal_id, deliberation_id, cell_id, kind, summary, rationale,
    risk_tier, estimated_cost_minor_units, derived_from_untrusted,
    payload_json, created_at_utc
)
SELECT
    proposal_id, deliberation_id, cell_id, kind, summary, rationale,
    risk_tier, estimated_cost_minor_units, derived_from_untrusted,
    payload_json, created_at_utc
FROM proposals;

DROP TABLE proposals;
ALTER TABLE proposals_rebuilt RENAME TO proposals;

CREATE INDEX idx_proposals_cell ON proposals (cell_id);
CREATE INDEX idx_proposals_deliberation ON proposals (deliberation_id);


-- --------------------------------------------------------------------------
-- 2. The salt.
--
-- One row, created once, never rotated: rotating it would silently empty the
-- do-not-contact list and the duplicate-contact history, which is the failure
-- mode this whole table exists to prevent. It lives in the database rather than
-- in a config file so a colony that is copied stays internally consistent.
--
-- **Stated plainly:** a salt stored beside the hashes stops an off-the-shelf
-- dictionary of common addresses, not an attacker who already has the file and
-- a specific person in mind. The guarantee being bought is narrower and is the
-- one §16.3 asks for — the colony cannot enumerate the people it has contacted,
-- and neither can a Cell, an Auditor, or an inherited genome.
-- --------------------------------------------------------------------------
CREATE TABLE counterparty_salt (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    salt_hex       TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);


-- --------------------------------------------------------------------------
-- 3. §31's `external_action_registry`.
--
-- One row per external action, written *before* the human performs it
-- ('claimed') and settled after ('completed' / 'abandoned'). The order is what
-- makes §21.2's "prevent" mean anything: a claim reserves the counterparty and
-- the channel, so a colliding sibling is refused while there is still time for
-- the refusal to matter. Recording only after the fact would make every
-- collision a post-mortem.
-- --------------------------------------------------------------------------
CREATE TABLE external_action_registry (
    action_id         TEXT PRIMARY KEY,

    -- Every external action descends from an approved grant. NOT NULL is the
    -- §0.4 gate expressed in the schema, exactly as `tool_calls.grant_id` is:
    -- there is no column arrangement that records an ungranted action.
    grant_id          TEXT NOT NULL REFERENCES approval_grants(grant_id),
    proposal_id       TEXT NOT NULL REFERENCES proposals(proposal_id),
    cell_id           TEXT NOT NULL REFERENCES cells(cell_id),

    -- §21.2's sibling detection is about *lineages*, not Cells: "Cells are
    -- internally separate but externally may appear to be one business" (§21.3).
    -- Denormalised from `cells` so the collision query is one table scan and
    -- stays correct after the Cell dies.
    founder_cell_id   TEXT NOT NULL,

    channel           TEXT NOT NULL,

    -- The salted hash, or NULL for a channel that addresses nobody in
    -- particular (a listing, a page). **There is deliberately no column holding
    -- a name, a label, or a hint** — a "just for the operator" label is the
    -- identity column wearing a different hat, and `test_no_table_in_the_colony
    -- _holds_the_counterparty` fails if the plaintext reaches any column of any
    -- table, this one included.
    counterparty_hash TEXT,

    -- §21.2's "domain used" and "platform account". Operator facts, supplied at
    -- claim time: a Cell has no way to know which account will be used, and
    -- asking it to name one would be asking it to invent one.
    domain            TEXT,
    platform_account  TEXT,

    -- What the action is for, frozen from the proposal the operator approved.
    intent            TEXT NOT NULL,

    -- What is being delivered, when the action delivers something. §19.3's
    -- export gateway decides *whether* an artifact may leave the colony; this
    -- decides to whom and on what channel. An artifact must already be exported
    -- before it can be delivered — see external_actions.py.
    artifact_id       TEXT REFERENCES artifacts(artifact_id),

    status            TEXT NOT NULL CHECK (status IN (
                          'claimed', 'completed', 'abandoned'
                      )),

    idempotency_key   TEXT NOT NULL UNIQUE,

    claimed_at_utc    TEXT NOT NULL,
    claimed_by        TEXT NOT NULL,
    completed_at_utc  TEXT,
    completed_by      TEXT,
    abandoned_at_utc  TEXT,
    abandon_reason    TEXT,

    -- §21.2's "reputation impact", as **raw observed events and no score**. A
    -- reputation number nothing can validate is theatre; a recorded complaint
    -- is a fact, and it is the one that freezes the channel.
    outcome           TEXT CHECK (outcome IN (
                          'delivered', 'no_response', 'positive_reply',
                          'negative_reply', 'bounced', 'complaint', 'blocked'
                      )),

    -- The human's external reference (message id, listing URL). Free text on
    -- purpose: it is the operator's own audit trail back to the real system,
    -- and the kernel never parses it.
    reference         TEXT,

    -- §28 Phase 8: "human labour is measured", and Phase 8's North Star is
    -- "human minutes/artifact". `ResourceType.HUMAN_MINUTES` has been declared
    -- since Phase 1 and metered by nothing; this is what fills it.
    human_minutes     INTEGER CHECK (human_minutes IS NULL OR human_minutes > 0),

    -- The A6 link: RESOURCE reserved at claim, settled at completion against
    -- the minutes actually spent.
    resource_reservation_id TEXT REFERENCES reservations(reservation_id)
);

CREATE INDEX idx_external_actions_channel ON external_action_registry (channel);
CREATE INDEX idx_external_actions_counterparty
    ON external_action_registry (counterparty_hash);
CREATE INDEX idx_external_actions_cell ON external_action_registry (cell_id);
CREATE INDEX idx_external_actions_founder ON external_action_registry (founder_cell_id);


-- --------------------------------------------------------------------------
-- 4. Per-channel state (§21.1).
--
-- Shaped like §23.3's metabolic alarm, and for a closely related reason: an
-- alarm halts the colony's *spending* when the derivative looks wrong, and this
-- halts a *channel* when the colony's shared reputation takes a hit. Both clear
-- only on a human acknowledgement carrying a stated reason, because both are
-- about a person deciding it is safe to continue.
--
-- §21.1's shared assets — sending reputation, merchant identity, brand — are
-- the first thing at risk that money cannot repair. Every existing guard
-- (Charter C4, C5, the real-spend breaker, the promotion pool) bounds money.
-- A refund does not undo a spam complaint.
-- --------------------------------------------------------------------------
CREATE TABLE channel_state (
    channel               TEXT PRIMARY KEY,
    frozen_at_utc         TEXT,
    frozen_reason         TEXT,
    frozen_by_action_id   TEXT REFERENCES external_action_registry(action_id),
    acknowledged_at_utc   TEXT,
    acknowledged_by       TEXT,
    acknowledgement_note  TEXT
);


-- --------------------------------------------------------------------------
-- 5. The do-not-contact list, and the argument for the hash in one table.
--
-- "Never contact this person again" is answerable here without the colony
-- holding a list of people. That is not a consolation prize for having hashed
-- the counterparty — it is the strongest thing the design buys, and it is why
-- the hash is a better answer than a `customers` table with an opt-out flag.
--
-- Nothing removes a row. §21.1's damage is not undoable by the party that
-- caused it, and an unblock verb would be a way to relitigate someone else's
-- decision to be left alone.
-- --------------------------------------------------------------------------
CREATE TABLE counterparty_blocks (
    counterparty_hash TEXT PRIMARY KEY,
    blocked_at_utc    TEXT NOT NULL,
    reason            TEXT NOT NULL,
    source_action_id  TEXT REFERENCES external_action_registry(action_id)
);

PRAGMA foreign_keys = ON;
