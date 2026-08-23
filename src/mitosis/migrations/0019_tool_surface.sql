-- Tool surface (SPEC.md §19, §18.1, §20.1, §0.4, §25.1 rung 4, §31; ADR-034).
--
-- The first path by which the kernel touches something outside itself that is
-- not a model provider. Everything here is gated: a tool runs only from an
-- approved §23 grant, only when its §27.1 autonomy flag is on, and (for
-- egress) only against an allowlisted domain.
--
-- §25.1 puts "read-only real-world observation" at rung 4 and "shadow
-- prediction with no action" at rung 5 — so a read-only tool is *below* where
-- the agent loop already sits. Tools that change the world are rungs 8-9 and
-- have no registry entry; `tools.ToolSpec.read_only` is the structural split.

PRAGMA foreign_keys = OFF;

-- --------------------------------------------------------------------------
-- 1. `proposals.kind` gains 'tool_request'.
--
-- SQLite cannot ALTER a CHECK constraint, so the table is rebuilt. The
-- rebuild is safe here because `db.migrate` runs each file through
-- `executescript`, which commits before it starts and is therefore outside
-- any transaction — the one place in this kernel where a PRAGMA that is a
-- no-op inside a transaction actually takes effect.
-- --------------------------------------------------------------------------
CREATE TABLE proposals_rebuilt (
    proposal_id          TEXT PRIMARY KEY,
    deliberation_id      TEXT NOT NULL REFERENCES deliberations(deliberation_id),
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),

    kind                 TEXT NOT NULL CHECK (kind IN (
                             'experiment', 'strategy', 'spend_request',
                             'tool_request', 'abstain'
                         )),
    summary              TEXT NOT NULL,
    rationale            TEXT NOT NULL,

    risk_tier            TEXT NOT NULL CHECK (risk_tier IN (
                             'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
                         )),

    estimated_cost_minor_units INTEGER NOT NULL CHECK (estimated_cost_minor_units >= 0),

    -- §18/§19.4 taint propagation, in its cheapest useful form. Set when the
    -- context this proposal was produced from contained UNTRUSTED_EXTERNAL
    -- observations, so §23.2's payload can tell a reviewer that the Cell may
    -- be repeating what a web page told it. Without this the reviewer sees a
    -- confident rationale and cannot tell whose idea it was.
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
    risk_tier, estimated_cost_minor_units, 0,
    payload_json, created_at_utc
FROM proposals;

DROP TABLE proposals;
ALTER TABLE proposals_rebuilt RENAME TO proposals;

CREATE INDEX idx_proposals_cell ON proposals (cell_id);
CREATE INDEX idx_proposals_deliberation ON proposals (deliberation_id);


-- --------------------------------------------------------------------------
-- 2. §31's `tool_calls`: one row per invocation, carrying §20.1 provenance
--    and the §18.1 taint label of whatever came back.
-- --------------------------------------------------------------------------
CREATE TABLE tool_calls (
    tool_call_id      TEXT PRIMARY KEY,

    -- Every tool call descends from an approved grant. NOT NULL is the whole
    -- §0.4 gate expressed in the schema: there is no column arrangement that
    -- records an ungranted invocation, so a bug that skipped the grant check
    -- could not write its result down.
    grant_id          TEXT NOT NULL REFERENCES approval_grants(grant_id),
    proposal_id       TEXT NOT NULL REFERENCES proposals(proposal_id),
    cell_id           TEXT NOT NULL REFERENCES cells(cell_id),

    tool              TEXT NOT NULL,

    -- The arguments as *frozen at approval*, never re-read from the Cell at
    -- execution time. Same asymmetry promotion.py applies to a grant's amount:
    -- what executes is what the operator was shown.
    arguments_json    TEXT NOT NULL,

    -- 'requested' is written *before* the external call, in the same
    -- transaction that consumes the grant and reserves the RESOURCE. This is
    -- the forward recovery ADR-022 deferred for the gateway, done properly
    -- here because the module is new: a crash mid-call leaves a diagnosable
    -- row rather than a reservation with nothing explaining it. The gateway
    -- cannot say which steps ran; this table can.
    status            TEXT NOT NULL CHECK (status IN (
                          'requested', 'succeeded', 'failed', 'execution_unknown'
                      )),

    -- §4.4/Charter C7's posture, borrowed from the gateway: a call that may or
    -- may not have reached the outside world is neither a success nor a
    -- failure, and saying so is more honest than guessing.
    idempotency_key   TEXT NOT NULL UNIQUE,

    started_at_utc    TEXT NOT NULL,
    finished_at_utc   TEXT,

    -- §18.1 provenance label. Anything a tool returns from outside the colony
    -- is UNTRUSTED_EXTERNAL and stays so; §18.3's clean-room path is the only
    -- route to any other label and is not built.
    taint_label       TEXT NOT NULL DEFAULT 'UNTRUSTED_EXTERNAL',

    -- §20.1's required artifact metadata. Nullable because a failed call has
    -- nothing to describe, and deliberately *not* defaulted for a successful
    -- one — §20.2 is explicit that public does not imply commercially
    -- reusable, so a default would be a fabricated licence claim.
    source            TEXT,
    retrieved_at_utc  TEXT,
    licence           TEXT,
    permitted_uses    TEXT,
    commercial_use    TEXT CHECK (commercial_use IN (
                          'permitted', 'prohibited', 'unknown'
                      )),
    contains_personal_data INTEGER CHECK (contains_personal_data IN (0, 1)),

    result_text       TEXT,
    result_bytes      INTEGER CHECK (result_bytes IS NULL OR result_bytes >= 0),
    result_sha256     TEXT,
    http_status       INTEGER,

    -- Redacted before persistence, exactly as gateway does with provider
    -- errors (Charter C14).
    error             TEXT,

    -- The A6 link: metered RESOURCE for the call.
    resource_reservation_id TEXT REFERENCES reservations(reservation_id)
);

CREATE INDEX idx_tool_calls_cell ON tool_calls (cell_id);
CREATE INDEX idx_tool_calls_grant ON tool_calls (grant_id);
CREATE INDEX idx_tool_calls_tool ON tool_calls (tool);


-- --------------------------------------------------------------------------
-- 3. §19.3's egress allowlist ("network disabled by default; egress domain
--    allowlist"). Shaped like §27.1's `sandbox:` block, and stored in the DB
--    for the same reason `real_spend_limits` is: a limit that lives only in a
--    config file cannot be audited when it changes.
-- --------------------------------------------------------------------------
CREATE TABLE egress_allowlist (
    domain        TEXT PRIMARY KEY,
    added_at_utc  TEXT NOT NULL,
    added_by      TEXT NOT NULL,
    reason        TEXT NOT NULL
);


-- --------------------------------------------------------------------------
-- 4. The rest of §27.1's `autonomy:` block. Only `real_spending` existed;
--    these four are the per-tool gates §0.4 calls for ("autonomy is granted
--    tool by tool, phase by phase"). All ship false, like their sibling.
-- --------------------------------------------------------------------------
ALTER TABLE operator_state ADD COLUMN public_web_read_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (public_web_read_enabled IN (0, 1));
ALTER TABLE operator_state ADD COLUMN browser_control_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (browser_control_enabled IN (0, 1));
ALTER TABLE operator_state ADD COLUMN external_publish_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (external_publish_enabled IN (0, 1));
ALTER TABLE operator_state ADD COLUMN external_message_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (external_message_enabled IN (0, 1));

PRAGMA foreign_keys = ON;
