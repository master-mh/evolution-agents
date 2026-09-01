-- §13.3/§13.4's content judgments, scored by an Auditor Cell rather than
-- taken on an operator's word (SPEC.md §13.3, §13.4, §10.4, §0.3, §29.10;
-- ADR-032, ADR-058, ADR-062, ADR-064).
--
-- ADR-062 built the third §12.1 dimension and drew a line it did not cross:
-- `buyer_type` is an *external fact* an operator can observe, so a human
-- attestation fits. §13.3's "software-native advantage" and §13.4's "the same
-- mechanism is renamed" are not external facts — they are *readings of a
-- Cell's own prose*, and §10.4 requires exactly the machinery migration 0018
-- already built for approval requests: a scored probability, not an opinion
-- that costs nothing to state. That machinery's one gap was its subject —
-- `audits` is keyed to `approval_requests`/`proposals`, and a content
-- judgment is about a **genome**, which is not owned by any one request and
-- may be carried by zero, one, or several Cells at once (a genome is
-- content-addressed; a request belongs to exactly one Cell).
--
-- **Two subjects, one table, a `kind` discriminator** — the same shape
-- `promotions.rung` already uses to keep two variants of one mechanism in one
-- table rather than inventing a second. `software_native_advantage` judges
-- one genome (§13.3, and by the same probability's failure mode, §13.4's
-- "ordinary freelancing described exotically"); `renamed_mechanism` judges a
-- **pair** (§13.4's "the same mechanism is renamed" needs the *prior* ADR-058
-- named as the blocker for this exact flag, and §31's `novelty_archive` — now
-- built, ADR-060 — is where a comparison genome comes from).
--
-- **The claim, and why `concern`/`no_concern` transfers unchanged from
-- migration 0018.** Both kinds are framed as "genuinely holds up" — genuinely
-- program-native, genuinely a distinct mechanism — so `concern` means the same
-- thing it always has ("I flag this"), and flagging still implies a
-- probability below one half that the genuine-claim is true. No new verdict
-- vocabulary, no new coherence rule.
CREATE TABLE genome_content_audits (
    audit_id                TEXT PRIMARY KEY,

    -- Which §13 judgment this is. `renamed_mechanism` requires the second
    -- genome the CHECK below demands; `software_native_advantage` forbids it
    -- — a pairless "renamed" judgment or a paired "program-native" one would
    -- both be a claim this table cannot state coherently.
    kind                     TEXT NOT NULL
                             CHECK (kind IN ('software_native_advantage', 'renamed_mechanism')),

    genome_hash              TEXT NOT NULL REFERENCES cell_genomes(genome_hash),
    compared_genome_hash     TEXT REFERENCES cell_genomes(genome_hash),

    -- Independence is checked against genome authorship, not a single Cell:
    -- a genome has none, several, or many Cells carrying it, so there is no
    -- `subject_cell_id` to mirror migration 0018's. `content_audit.py`
    -- checks the auditor's *own* current genome against both hashes here,
    -- and every Cell that has ever carried either, at write time.
    auditor_cell_id          TEXT NOT NULL REFERENCES cells(cell_id),

    -- `rejected` covers a reply that produced no usable audit: malformed
    -- JSON, a schema violation, or a verdict incoherent with its own
    -- probability — the same three ways migration 0018's replies fail.
    status                   TEXT NOT NULL CHECK (status IN ('recorded', 'rejected')),
    failure_reason           TEXT,

    verdict                  TEXT CHECK (verdict IN ('concern', 'no_concern')),
    summary                  TEXT,
    probability              REAL CHECK (probability IS NULL
                                         OR (probability > 0 AND probability < 1)),
    prediction_id            TEXT REFERENCES prediction_register(prediction_id),

    model_call_id             TEXT REFERENCES model_calls(model_call_id),
    wake_reason               TEXT NOT NULL,

    created_at_utc            TEXT NOT NULL,
    idempotency_key           TEXT NOT NULL UNIQUE,

    -- The pairing constraint: exactly one genome for a program-native
    -- judgment, exactly two distinct ones for a renamed-mechanism judgment.
    CHECK (
        (kind = 'software_native_advantage' AND compared_genome_hash IS NULL)
        OR
        (kind = 'renamed_mechanism' AND compared_genome_hash IS NOT NULL
                                     AND compared_genome_hash != genome_hash)
    ),

    -- The same all-or-nothing invariant migration 0018 states: a recorded
    -- audit always carries a verdict, a summary, a probability and a
    -- prediction together, never some of them.
    CHECK (
        (status = 'rejected' AND verdict IS NULL AND probability IS NULL
                             AND prediction_id IS NULL AND failure_reason IS NOT NULL)
        OR
        (status = 'recorded' AND verdict IS NOT NULL AND summary IS NOT NULL
                             AND probability IS NOT NULL AND prediction_id IS NOT NULL)
    )
);

CREATE INDEX idx_genome_content_audits_genome ON genome_content_audits (genome_hash);
CREATE INDEX idx_genome_content_audits_compared ON genome_content_audits (compared_genome_hash);
CREATE INDEX idx_genome_content_audits_auditor ON genome_content_audits (auditor_cell_id);

-- One *opinion* per Auditor per subject, mirroring migration 0018's reasoning
-- exactly: revising a judgment once its consequences are visible is not
-- evidence, and a rejected attempt is not an opinion, so the index is partial
-- on `status = 'recorded'`.
--
-- **`COALESCE(compared_genome_hash, '')` is load-bearing, not decoration.**
-- SQLite's default UNIQUE semantics treat every NULL as distinct from every
-- other NULL, so a plain `(kind, genome_hash, compared_genome_hash,
-- auditor_cell_id)` index would never fire for `software_native_advantage`
-- rows — they all carry `compared_genome_hash IS NULL`, and the exact
-- duplicate this index exists to stop (the same Auditor asked to judge the
-- same genome twice) is precisely the case where the two NULLs would compare
-- unequal. The substitution folds every NULL to the same non-NULL sentinel,
-- which `renamed_mechanism` rows can never collide with because the CHECK
-- above requires their `compared_genome_hash` to be a real, distinct hash —
-- a 64-character hex digest is never the empty string.
CREATE UNIQUE INDEX idx_genome_content_audits_one_opinion
    ON genome_content_audits (kind, genome_hash, COALESCE(compared_genome_hash, ''), auditor_cell_id)
    WHERE status = 'recorded';
