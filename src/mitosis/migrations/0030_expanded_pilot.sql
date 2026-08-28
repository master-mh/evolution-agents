-- 0030: §25.1 rung 8 ("expanded pilot"), and the bounded engine that issues it.
--
-- **What this migration corrects before it adds anything.** Migration 0016, and
-- the two modules built on it, state that rung 8 "means removing one of the two
-- humans standing in every allocation". That reading is wrong, and it had
-- propagated to four places unchallenged. §25.1's ladder reads:
--
--     7. Tiny capped live experiment
--     8. Expanded pilot
--     9. Bounded autonomy
--
-- The 7 -> 8 delta is **scale** ("tiny capped" -> "expanded"). The word
-- *autonomy* appears only at rung 9, and a *pilot* is supervised by definition.
-- Who acts without a human is governed by §27.1's `autonomy:` flags and §0.4's
-- "tool by tool, phase by phase" — not by a ladder rung. `test_outcome.py`
-- contradicted its own docstring three lines below it, in the right direction:
-- "a promotion that fires on a timer is rung 9, not rung 8".
--
-- **So this migration ships two distinct things, and keeps them distinguishable
-- in the record.** Rung 8 is the *expanded* allocation, earned by rung-7
-- evidence. Issuing one *on a timer with no operator* is rung 9's bounded
-- autonomy applied to the promotion decision, which is why
-- `decided_automatically` is a column and not an inference: a later reader must
-- be able to tell which promotions a person made.
--
-- **The ladder forbids skipping.** §25.1 opens "no strategy moves directly from
-- synthetic success to autonomous commerce", so an automatic engine cannot jump
-- a Cell to rung 8 without a rung-7 record to stand on. That is enforced below
-- by a trigger rather than by the caller, because ADR-047's lesson is that a
-- constraint has no layer: a check in `promotion.py` binds only callers that go
-- through `promotion.py`, and the escape hatches in this repo do not.

-- --------------------------------------------------------------------------
-- The rung-7 record an expansion stands on.
-- --------------------------------------------------------------------------
-- NULL at rung 7 (nothing precedes the first live experiment), NOT NULL above
-- it. A self-reference rather than a `cell_id` lookup, because "this Cell was
-- once at rung 7" is a weaker fact than "*this* expansion expands *that*
-- experiment" — and §25.2's transfer degradation is only meaningful against a
-- specific predecessor.
ALTER TABLE promotions ADD COLUMN supersedes_promotion_id TEXT
    REFERENCES promotions(promotion_id);

-- --------------------------------------------------------------------------
-- Was a person in the loop?
-- --------------------------------------------------------------------------
-- Defaults 0 and every existing row is a human decision, so this is backfilled
-- explicitly below rather than left to the default — the default is for *new*
-- rows, and reading "automatic" off a pre-existing rung-7 allocation would
-- misreport the one fact this column exists to keep.
ALTER TABLE promotions ADD COLUMN decided_automatically INTEGER NOT NULL DEFAULT 0
    CHECK (decided_automatically IN (0, 1));

-- --------------------------------------------------------------------------
-- §25.2's evidence, snapshotted at the moment of decision.
-- --------------------------------------------------------------------------
-- `outcome.py` predicted this exact column set and the condition for adding it:
-- "A table becomes worth adding when a *decision* consumes an assessment,
-- because then what was known at decision time is itself a fact. Nothing
-- consumes one yet." Something does now. These are columns on `promotions`
-- rather than a new `assessments` table for the reason §2.5 keeps refusing one:
-- the assessment stays *derived* for every promotion that no decision consumed,
-- and only the consumed one is frozen. A table would invite storing all of them
-- and then disagreeing with the canonical derivation.
--
-- NULL means "no assessment was consumed" — true of every rung-7 allocation,
-- which is decided on the §23 payload rather than on a predecessor's outcome.
ALTER TABLE promotions ADD COLUMN evidence_verdict TEXT
    CHECK (evidence_verdict IS NULL OR evidence_verdict IN (
        'insufficient_evidence',
        'evidence_withheld',
        'supports_promotion',
        'does_not_support_promotion'
    ));
ALTER TABLE promotions ADD COLUMN evidence_mean_brier REAL;
ALTER TABLE promotions ADD COLUMN evidence_resolved_predictions INTEGER;

-- Every row that exists today is a human-decided rung 7 with no predecessor and
-- no consumed assessment. Stated, not assumed.
UPDATE promotions SET decided_automatically = 0 WHERE decided_automatically IS NULL;

-- --------------------------------------------------------------------------
-- The ladder, enforced where no caller can route around it.
-- --------------------------------------------------------------------------
-- Three rules, all §25.1:
--   (a) rung 7 has no predecessor — it is where live money starts.
--   (b) rung 8+ must name one, or the ladder has been skipped.
--   (c) a predecessor must be the *immediately* preceding rung, and must belong
--       to the same Cell. Promoting Cell A on Cell B's evidence is the
--       reciprocal-evidence farming §29 names, expressed as a foreign key that
--       happened to point somewhere plausible.
CREATE TRIGGER promotions_ladder_insert
BEFORE INSERT ON promotions
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.rung = 7 AND NEW.supersedes_promotion_id IS NOT NULL
            THEN RAISE(ABORT, '§25.1: rung 7 is where the live ladder starts and supersedes nothing')
        WHEN NEW.rung > 7 AND NEW.supersedes_promotion_id IS NULL
            THEN RAISE(ABORT, '§25.1: a rung above 7 must name the promotion it expands — the ladder forbids skipping')
        WHEN NEW.supersedes_promotion_id IS NOT NULL AND (
            SELECT rung FROM promotions WHERE promotion_id = NEW.supersedes_promotion_id
        ) IS NOT NEW.rung - 1
            THEN RAISE(ABORT, '§25.1: a promotion may only expand the rung immediately below it')
        WHEN NEW.supersedes_promotion_id IS NOT NULL AND (
            SELECT cell_id FROM promotions WHERE promotion_id = NEW.supersedes_promotion_id
        ) IS NOT NEW.cell_id
            THEN RAISE(ABORT, '§25.1: a promotion may only expand this Cell''s own evidence')
    END;
END;

-- One expansion per predecessor. Without this a single successful rung-7
-- experiment could be expanded repeatedly, which is the §23.4 splitting attack
-- run upward: many "expansions" of one piece of evidence rather than one.
CREATE UNIQUE INDEX idx_promotions_supersedes
    ON promotions (supersedes_promotion_id)
    WHERE supersedes_promotion_id IS NOT NULL;

-- --------------------------------------------------------------------------
-- §27.1: the flag that lets the engine act unattended.
-- --------------------------------------------------------------------------
-- Ships 0 like every other autonomy flag (§0.4: "Nothing begins at real-money
-- autonomy"). §0.4 grants autonomy "tool by tool", and migration 0022 made one
-- key per capability structural, so this gates exactly one thing: issuing a
-- promotion with no operator. It does **not** imply real spending —
-- `real_spending` remains separately required for a USD_REAL book, which keeps
-- ADR-026's two independent confirmations intact rather than collapsing them.
ALTER TABLE operator_state ADD COLUMN auto_promotion_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (auto_promotion_enabled IN (0, 1));
