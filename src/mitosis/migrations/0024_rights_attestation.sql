-- The other direction: rights a person can *establish* (SPEC.md §20.1, §20.2,
-- §20.3, §0.3, §3.6; Charter C13; ADR-041).
--
-- ADR-035 built rights inheritance in one direction only. An artifact takes the
-- most restrictive position among its sources, a fetched page is `unknown` by
-- construction (`fetchers.py` cannot read a licence), and §20.2's export gate
-- refuses commercial export of anything not `permitted`. So rights could only
-- ever tighten: **an artifact built on a fetched page was `unknown` forever**,
-- and `real_commerce` could be opened and still sell nothing. Flagged by four
-- consecutive slices (ADR-035, ADR-036, ADR-037, ADR-040) and built here.
--
-- **The subject is a source, not an artifact**, which is what `check_exportable`
-- already told the operator to do — "Establish the rights position on its
-- sources first." The alternative, stamping `commercial_use` onto one artifact,
-- is the §20.2 laundering path with a human holding the pen: it does not
-- compose (ten artifacts from one page need ten attestations), it does not
-- reach forward (the eleventh artifact is `unknown` again), and it asks a person
-- to judge a derived work when what they can actually read is a licence.
--
-- **Attesting is append-only and nothing is ever edited (§3.6).** The latest
-- row for a subject wins, ordered by insertion rather than by wall clock so a
-- replay is deterministic. Withdrawing an attestation is a *new* attestation of
-- `unknown` with its own basis — the same "post an adjustment, never rewrite"
-- move the ledger makes, and it leaves the reason legible where a `revoked`
-- flag would leave only an absence. One mechanism, not two.
--
-- **Two subject kinds, both real today, and the discriminator is required.**
-- ADR-037's lesson: name the key the thing collides on rather than leaving it
-- implicit.
--   * `domain` — an external source. Keyed on the normalised host, the object
--     the operator already manages through the Charter C12 egress allowlist.
--   * `colony` — the colony's own output. `inherit_provenance` gives an artifact
--     with no sources `commercial_use: unknown`, saying outright that "whether
--     the colony may *sell* its own output is a question for a person, not a
--     default". Nothing could ask the person. A domain attestation cannot reach
--     this case because there is no domain, so the colony is its own subject.
--
-- **Matching is exact host, never a dotted suffix, and that is deliberately
-- unlike the egress allowlist it sits beside.** `_check_egress_locked` matches
-- `example.com` or anything under it, because over-matching there means reading
-- a page the operator did not picture. Over-matching *here* means selling
-- material under a licence that never covered it — §20.3's "legal liabilities if
-- its data use is invalid". Same-shaped key, opposite consequence, so the
-- looser rule is not inherited. (ADR-036 hit the mirror of this: "scope it the
-- same way as the neighbouring query" is not a safe default in this area.)

CREATE TABLE rights_attestations (
    attestation_id   TEXT PRIMARY KEY,

    -- What is being attested about. Required, per ADR-037.
    subject_kind     TEXT NOT NULL CHECK (subject_kind IN ('domain', 'colony')),

    -- For 'domain', the normalised bare host. For 'colony', the literal
    -- 'colony' — a single row-space, since the colony is one thing.
    subject          TEXT NOT NULL,

    -- §20.1's three rights fields, and only those three. The remaining §20.1
    -- metadata (retention rule, personal data, source summary) stays with
    -- whatever observed it: an operator attests a *licence*, which is the part
    -- of §20.1 a person can actually read off a page.
    licence          TEXT NOT NULL,
    permitted_uses   TEXT NOT NULL,
    commercial_use   TEXT NOT NULL CHECK (commercial_use IN (
                         'permitted', 'prohibited', 'unknown'
                     )),

    -- Where the operator got this. Required and non-empty, like
    -- `artifacts.export_reason` and `egress_allowlist.reason`: §20.3 makes an
    -- invalid data-use position a liability rather than a mistake, so the record
    -- has to say who believed what and why.
    --
    -- It also does one thing the other two do not. A fetched page can *claim*
    -- its own licence in its own body, and a Cell chooses what to fetch; an
    -- operator reading that claim back is being told what to attest by the
    -- material under attestation. Making the basis a required sentence is what
    -- separates "the publisher's licensing page" from "the page said so".
    basis            TEXT NOT NULL,

    attested_by      TEXT NOT NULL,
    attested_at_utc  TEXT NOT NULL,

    -- 'colony' is one subject, not a namespace.
    CHECK (subject_kind <> 'colony' OR subject = 'colony'),

    -- **Commercially permitted requires a named licence.** The incoherent
    -- state — "you may sell this, and I cannot tell you under what" — is the
    -- one an operator waving a source through would produce, and it is the only
    -- part of the judgement the kernel can check. Refusing it here means the
    -- attestation that opens §20.2's gate always carries the thing a dispute
    -- would ask for.
    CHECK (commercial_use <> 'permitted' OR (licence <> '' AND licence <> 'unknown'))
);

-- Latest-wins reads are keyed on the subject; the ordering is `rowid`, which is
-- the index's implicit payload and cannot be named as a column here.
CREATE INDEX idx_rights_attestations_subject
    ON rights_attestations (subject_kind, subject);


-- What the *producing Cell* declared about content it wrote itself, held apart
-- from the inherited fold so the effective position stays exactly recomputable.
--
-- `artifacts.create` has taken an `own_provenance` since ADR-035 and **nothing
-- has ever passed one** — the eleventh reserved socket found half-built. It
-- was folded into the stored rights columns and then unrecoverable, which did
-- not matter while the fold was the only answer. It matters now: the effective
-- position is re-derived from current attestations plus this, and a socket
-- nobody has filled yet must not be the thing that makes a new invariant
-- true-by-accident. NULL means the producer declared nothing, which is every
-- row that exists today.
ALTER TABLE artifacts ADD COLUMN own_provenance_json TEXT;
