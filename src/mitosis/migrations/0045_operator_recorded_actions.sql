-- An external action a person took outside any grant, recorded after the fact,
-- and the offer it made (SPEC.md §21.2, §28 Phase 9; ADR-036, ADR-111).
--
-- Live, 2026-09-26: the colony's first product was listed on Gumroad by the
-- operator's own hand, at their request, outside `claim-external-action` — and
-- migration 0021 made that unrecordable: `grant_id` is NOT NULL so that "there
-- is no column arrangement that records an ungranted action". That guarantee was
-- written about *Cells*. It stays exactly as strong for them: a row that did
-- not come from a grant must say so in `origin`, and the CHECK below admits no
-- other way to leave `grant_id` empty.
--
-- What an `operator_record` row is, enforced here rather than in Python:
--   * completed — it records a fact, never a claim, so nothing can hold a
--     counterparty or a channel against a sibling on its strength;
--   * `recorded_at_utc` set — the moment it was written, beside
--     `claimed_at_utc`, which holds when the action happened in the world. The
--     collision windows measure exposure in the world, so they read the latter;
--     the former is why the row can never pass for a claim written first;
--   * an artifact — the Cell is derived from what was delivered, never named by
--     the caller (ADR-097's rule), so a row with no artifact would have no Cell.
--
-- §21.2 also tracks "offer made", and nothing held one. Found the same day: a
-- Cell revising its own marketing wrote "$19" because the price it planned is
-- in its proposal log and the price the operator listed is nowhere. The offer
-- is a fact about the action, so it lives on the action's row.
--
-- Rebuilt as it stands otherwise; `channel_state` and `counterparty_blocks`
-- reference it by name, which the rename preserves.

PRAGMA foreign_keys = OFF;

CREATE TABLE external_action_registry_rebuilt (
    action_id         TEXT PRIMARY KEY,

    -- NULL only for an operator record (the CHECK at the foot of the table).
    grant_id          TEXT REFERENCES approval_grants(grant_id),
    proposal_id       TEXT REFERENCES proposals(proposal_id),
    cell_id           TEXT NOT NULL REFERENCES cells(cell_id),
    founder_cell_id   TEXT NOT NULL,

    channel           TEXT NOT NULL,
    counterparty_hash TEXT,
    domain            TEXT,
    platform_account  TEXT,
    intent            TEXT NOT NULL,
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

    outcome           TEXT CHECK (outcome IN (
                          'delivered', 'no_response', 'positive_reply',
                          'negative_reply', 'bounced', 'complaint', 'blocked'
                      )),
    reference         TEXT,
    human_minutes     INTEGER CHECK (human_minutes IS NULL OR human_minutes > 0),
    resource_reservation_id TEXT REFERENCES reservations(reservation_id),

    origin            TEXT NOT NULL DEFAULT 'grant'
                      CHECK (origin IN ('grant', 'operator_record')),
    recorded_at_utc   TEXT,

    -- §21.2's "offer made": the price the action put in front of the world.
    offer_minor_units INTEGER CHECK (offer_minor_units IS NULL OR offer_minor_units > 0),
    offer_book        TEXT CHECK (offer_book IS NULL OR offer_book IN ('USD_REAL', 'USD_SIM')),
    CHECK ((offer_minor_units IS NULL) = (offer_book IS NULL)),

    CHECK (
        (origin = 'grant'
            AND grant_id IS NOT NULL AND proposal_id IS NOT NULL
            AND recorded_at_utc IS NULL)
        OR
        (origin = 'operator_record'
            AND grant_id IS NULL AND proposal_id IS NULL
            AND status = 'completed' AND recorded_at_utc IS NOT NULL
            AND artifact_id IS NOT NULL AND resource_reservation_id IS NULL)
    )
);

INSERT INTO external_action_registry_rebuilt (
    action_id, grant_id, proposal_id, cell_id, founder_cell_id, channel,
    counterparty_hash, domain, platform_account, intent, artifact_id, status,
    idempotency_key, claimed_at_utc, claimed_by, completed_at_utc, completed_by,
    abandoned_at_utc, abandon_reason, outcome, reference, human_minutes,
    resource_reservation_id
)
SELECT
    action_id, grant_id, proposal_id, cell_id, founder_cell_id, channel,
    counterparty_hash, domain, platform_account, intent, artifact_id, status,
    idempotency_key, claimed_at_utc, claimed_by, completed_at_utc, completed_by,
    abandoned_at_utc, abandon_reason, outcome, reference, human_minutes,
    resource_reservation_id
FROM external_action_registry;

DROP TABLE external_action_registry;
ALTER TABLE external_action_registry_rebuilt RENAME TO external_action_registry;

CREATE INDEX idx_external_actions_channel ON external_action_registry (channel);
CREATE INDEX idx_external_actions_counterparty
    ON external_action_registry (counterparty_hash);
CREATE INDEX idx_external_actions_cell ON external_action_registry (cell_id);
CREATE INDEX idx_external_actions_founder ON external_action_registry (founder_cell_id);
CREATE INDEX idx_external_actions_domain
    ON external_action_registry (domain) WHERE domain IS NOT NULL;
CREATE INDEX idx_external_actions_platform_account
    ON external_action_registry (platform_account) WHERE platform_account IS NOT NULL;
CREATE INDEX idx_external_actions_artifact
    ON external_action_registry (artifact_id) WHERE artifact_id IS NOT NULL;

PRAGMA foreign_keys = ON;
