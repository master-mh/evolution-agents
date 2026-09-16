-- A wake whose model call failed at the provider is its own outcome
-- (SPEC.md §24.2, §24.1; ADR-101) — not the Cell's unparseable reply.
--
-- `gateway.call_model` does not raise when a provider fails: it classifies
-- the outcome (`failed` when the request is known to be unbilled,
-- `execution_unknown` when it may have been billed), records it on the
-- `model_calls` row, and returns the call. `deliberation.py` read
-- `response_text or ""` straight past that classification, handed the empty
-- string to `proposal.parse`, and recorded the resulting `ProposalError` as
-- `unparseable` — then spent ADR-069's one parse-repair call re-prompting the
-- provider that had just gone down. Observed 2026-09-15 against a local
-- Ollama whose Metal backend had died: two `model_calls` rows, both `failed`,
-- and a deliberation saying the model had not returned a valid proposal.
--
-- **Why a fourth status rather than a clearer `failure_reason`.** §24.2
-- requires material provider change to be treated as an *environment* regime
-- change "so provider drift is not mistaken for Cell evolution", and an
-- outage is the loudest provider change there is. A reason string is prose;
-- `status` is what every reader groups by. `scripts/measure_parse_compliance.py`
-- reports a rate over exactly this column — its own docstring already named
-- the hazard ("a slow local model is recorded as an unparseable empty reply
-- -- a timeout wearing a compliance failure's clothes") — and the golden
-- snapshot pins it per deliberation. Left inside `unparseable`, every one of
-- those readers counts the provider's weather as the Cell's work.
--
-- `refused` was the other candidate and is worse: it means the loop declined
-- *before* spending, and carries no assembled context because none was
-- assembled. A failed call happened after a wake ran in full — context
-- assembled, reservation taken, provider reached.
--
-- **Two row-shape CHECKs ride along**, because the rebuild is the one chance
-- to add them (ADR-047's discipline: a decision the schema can express does
-- not belong only in the Python that happens to run first). A `call_failed`
-- row names the call that failed — one naming none is a refusal wearing the
-- wrong status — and names no repair, since a wake with no reply to repair
-- buys none.
--
-- Same rebuild as migrations 0019/0021/0027/0032: SQLite cannot ALTER a CHECK
-- constraint, and `db.migrate` runs each file through `executescript`, which
-- commits before it starts and is therefore outside any transaction. The
-- three tables that reference `deliberations` (`proposals`,
-- `deliberation_predictions`, `artifacts`) name it by the name this restores,
-- so their foreign keys land back on the rebuilt table. `PRAGMA
-- foreign_key_check` and `PRAGMA integrity_check` are clean afterwards, with
-- a child row of each of the three present across the rebuild --
-- `test_the_rebuild_keeps_every_row_and_every_child_reference` in
-- `tests/test_deliberation.py` inserts them and re-asserts it.

PRAGMA foreign_keys = OFF;

CREATE TABLE deliberations_rebuilt (
    deliberation_id      TEXT PRIMARY KEY,
    cell_id              TEXT NOT NULL REFERENCES cells(cell_id),

    -- Idempotency for the whole wake (Charter C6). Wake events are delivered
    -- at least once, and a redelivered wake must not buy a second model call.
    wake_key             TEXT NOT NULL UNIQUE,

    -- One of §17.2's wake events. Free text rather than a CHECK because
    -- §17.2 gives an open list and new wake sources are expected.
    wake_reason          TEXT NOT NULL,

    -- The genome whose content was interpreted.
    genome_hash          TEXT NOT NULL REFERENCES cell_genomes(genome_hash),

    -- The gateway call that did the thinking. NULL when the loop refused
    -- before spending anything (a dead Cell, an unfunded one), and required on
    -- a `call_failed` row by the CHECK at the foot of this table: a call was
    -- made, §24.1 wants it traceable, and a `call_failed` row naming no call
    -- would be describing a refusal.
    model_call_id        TEXT REFERENCES model_calls(model_call_id),

    -- What §15 context assembly actually selected, and what it dropped.
    context_json         TEXT NOT NULL,
    context_tokens       INTEGER NOT NULL,
    context_dropped_json TEXT NOT NULL,

    status               TEXT NOT NULL CHECK (status IN (
                             'proposed',      -- a valid structured proposal
                             'unparseable',   -- the model did not return one
                             'refused',       -- the loop declined to run
                             'call_failed'    -- the provider returned no reply
                         )),
    -- Why a deliberation ended without a proposal. On `call_failed` this is
    -- the gateway's own redacted `error_text` (Charter C14), repeated rather
    -- than re-described: the layer that observed the failure defines it. The
    -- raw model text is still deliberately NOT stored on the unparseable
    -- path — it is untrusted content (§19.4), and a prose blob invites a
    -- later reader to treat it as a result.
    failure_reason       TEXT,

    created_at_utc       TEXT NOT NULL,

    -- ADR-069's second, separately-billed call. NULL for every deliberation
    -- that never needed one.
    repair_model_call_id TEXT REFERENCES model_calls(model_call_id),

    -- ADR-047's discipline, applied to the two things `call_failed` means.
    -- A wake whose call failed *made* a call (or it would be a refusal), and
    -- it bought no repair — there was no reply to repair, and the only
    -- provider a repair could reach is the one that just failed. Both are
    -- decisions `deliberation.py` implements; a CHECK is what stops a future
    -- caller writing the row that contradicts them, whichever module it
    -- lives in.
    CHECK (status != 'call_failed' OR model_call_id IS NOT NULL),
    CHECK (status != 'call_failed' OR repair_model_call_id IS NULL)
);

INSERT INTO deliberations_rebuilt (
    deliberation_id, cell_id, wake_key, wake_reason, genome_hash,
    model_call_id, context_json, context_tokens, context_dropped_json,
    status, failure_reason, created_at_utc, repair_model_call_id
)
SELECT
    deliberation_id, cell_id, wake_key, wake_reason, genome_hash,
    model_call_id, context_json, context_tokens, context_dropped_json,
    status, failure_reason, created_at_utc, repair_model_call_id
FROM deliberations ORDER BY rowid;

DROP TABLE deliberations;
ALTER TABLE deliberations_rebuilt RENAME TO deliberations;

CREATE INDEX idx_deliberations_cell ON deliberations (cell_id);

PRAGMA foreign_keys = ON;
