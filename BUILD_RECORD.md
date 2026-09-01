# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, the experiment, experiment attribution,
proposed experiments, the strategy kind decided, the experiment_id foreign keys, §13.1's
normalised cost, the reply format a model can follow, the temperature/diversity
measurement, §15.1 anchoring and the twins that chose the fix, the proposal log that
shows no wording, the §23.4 repeat, the wake reason, the genome, the human-decision wake,
the +15% that did not survive honesty, §13.4's concreteness measure,
§13.2's selector, §12's novelty archive, the inbound counterparty key,
§12.1's declared third dimension, rung 8, and §12.3's `P(next stage)`,
2026-07-21 through 2026-08-31):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-31 — §13.3/§13.4's Auditor path judges a genome directly

`content_audit.py` + migration 0031 + 21 tests + `audit-genome`/`audit-genome-pair`/
`content-audit-record` + golden expectations **34 -> 35** (ADR-065). **`auditor.py`'s machinery
gets its second subject: a genome (§13.3, and §13.4's "ordinary freelancing described
exotically") and a genome pair (§13.4's "the same mechanism is renamed") — scored the same way an
approval request already is.**

### One table, a `kind` column — the `promotions.rung` shape, not the attestation shape

Two precedents pointed opposite ways. `rights_attestations`/`buyer_attestations` copied one
shape into two separate tables for two genuinely different acts by different declarers.
`promotions.rung` keeps two variants of *one* mechanism together. This is the second case:
`software_native_advantage` and `renamed_mechanism` are the same act — an Auditor scoring a
probability about a Cell's own prose — with a different subject shape, so one table with a `kind`
discriminator and a nullable `compared_genome_hash` won. The CHECK constraint makes the pairing
itself unrepresentable: `software_native_advantage` forbids a second genome, `renamed_mechanism`
requires one distinct from the first.

### Independence, generalised from one Cell to a set of them

A genome has no single subject Cell — content-addressed, it may be carried by zero, one, or many,
dead or alive. The check: the auditor's own current genome must not be either hash under review,
and the auditor must share no lineage founder with *any* Cell that has ever carried either genome.
**Teeth-checking found the dedicated self-check is strictly subsumed by the lineage check** — a
Cell whose own genome matches always appears in the lineage query's own result, trivially sharing
a founder with itself. Both ship anyway: the first for a sharper error message, the second as the
actual guarantee.

### `concern`/`no_concern` transfers unchanged

Both kinds are framed as "genuinely holds up" (genuinely program-native, genuinely a distinct
mechanism), so migration 0018's verdict vocabulary and coherence rule apply with zero
modification — no new direction to get backwards.

### Verification

- **21 new tests; teeth-checked two ways.** Removing the dedicated self-audit check still raised
  (via the lineage check, confirming no coverage gap) but with the wrong, more generic message —
  a legitimate finding about diagnostic clarity, not a defect. Dropping the partial unique index
  (`idx_genome_content_audits_one_opinion`) produced a clean `DID NOT RAISE`, the exact shape
  `test_the_schema_refuses_a_second_opinion_from_the_same_auditor` exists to catch.
- **1140 tests and the golden run green.** The golden diff is **one added section**,
  `genome_content_audits: []` — empty, and stated as deliberate rather than hidden: the fixture's
  only two Auditor-eligible Cells share one lineage, and this module's own independence check
  refuses exactly that pairing. Manufacturing a valid pair means a sixth Cell, which moves
  population counts and every book's balance — logged for its own reviewed diff rather than
  folded into this one.
- Next: nothing yet consumes a content audit (`test_nothing_yet_consumes_a_content_audit` keeps
  it that way). `selection.py`'s `software_native_advantage` gate is the natural first consumer —
  reading a *resolved* audit only, never an unresolved one, which would be exactly the "estimated
  negative EV" shape §10.5 forbids acting on automatically.
