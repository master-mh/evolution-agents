-- `risk_tier` becomes optional for exactly one kind: `abstain` (SPEC.md
-- §23.1, §0.3; ADR-068).
--
-- Two models independently produced the same shape of failure: `qwen2.5` at
-- t=0 dropped `risk_tier` (with `summary` and `estimated_cost_minor_units`)
-- from every `abstain` reply in its collapsed run; `llama3.2` sent
-- `"risk_tier": null` on the same shape. A stronger model reaching the same
-- objection independently is evidence the schema asked for something
-- indefensible, not that the models are wrong: §23.1 classifies *actions* —
-- "batch low-risk reversible actions; require individual review for
-- high-risk or irreversible" — and an abstaining Cell has proposed no action
-- to classify. Being asked to state one anyway is being asked to invent a
-- number about a hypothetical that has no shape yet.
--
-- **Unrepresentable, not merely refused.** `proposal.py`'s Pydantic
-- validator can already reject a null `risk_tier` on every kind but
-- `abstain` at parse time — but ADR-047's precedent is that a constraint
-- with no layer belongs in the schema when the schema can express it, not
-- only in the Python that happens to run first. This CHECK makes a
-- non-abstain proposal with no risk tier impossible to store, full stop,
-- regardless of which future caller constructs a row.
--
-- **`estimated_cost_minor_units` and `summary` are deliberately untouched.**
-- `qwen2.5`'s failure dropped all three, but only `risk_tier` has a defensible
-- argument for being optional (a Cell has not classified an action it isn't
-- proposing). `summary` still has something to say ("nothing worth doing
-- right now, because...") and `estimated_cost_minor_units` is trivially 0 for
-- an abstention — the prompt already says "use 0 if nothing would be spent".
-- Widening either would be fixing a different, unargued failure under cover
-- of this one.
--
-- Same rebuild as migrations 0019/0021/0027: SQLite cannot ALTER a CHECK
-- constraint, and `db.migrate` runs each file through `executescript`, which
-- commits before it starts and is therefore outside any transaction.

PRAGMA foreign_keys = OFF;

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

    -- NULL only when `kind = 'abstain'` — every other kind still requires a
    -- tier, enforced below rather than left to whichever caller remembers to
    -- check.
    risk_tier            TEXT CHECK (risk_tier IS NULL OR risk_tier IN (
                             'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
                         )),

    estimated_cost_minor_units INTEGER NOT NULL CHECK (estimated_cost_minor_units >= 0),

    derived_from_untrusted INTEGER NOT NULL DEFAULT 0
                           CHECK (derived_from_untrusted IN (0, 1)),

    payload_json         TEXT NOT NULL,
    created_at_utc       TEXT NOT NULL,

    CHECK (risk_tier IS NOT NULL OR kind = 'abstain')
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
FROM proposals ORDER BY rowid;

DROP TABLE proposals;
ALTER TABLE proposals_rebuilt RENAME TO proposals;

CREATE INDEX idx_proposals_cell ON proposals (cell_id);
CREATE INDEX idx_proposals_deliberation ON proposals (deliberation_id);

PRAGMA foreign_keys = ON;
