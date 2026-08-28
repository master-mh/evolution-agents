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
§13.2's selector, §12's novelty archive, and the inbound counterparty key,
2026-07-21 through 2026-08-28):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-28 — §12.1's third dimension is declared, and the mechanism already existed

Migration 0029 + `counterparty.attest_buyer_type` + 15 tests + `set-buyer-type`/`buyers` + golden
expectations **31 -> 32** (ADR-062). **§12.1's archive is three-dimensional; nothing abstains.**

PRIORITIES said the next step was "a declared `buyer_type`, with its declarer recorded — **one
build, three callers**". That entry was wrong twice, and both errors were worth finding before
building anything.

### The mechanism already existed

ADR-041 built `rights_attestations`: a person establishes a fact the colony cannot derive — subject,
claim, basis, who, when; append-only; latest wins; withdrawal is a row and not a flag; unreachable
from any Cell, enforced by an AST walk. Every one of those decisions is right here for the same
reasons, so this slice **copies an established shape** instead of inventing a judgment subsystem.

### The three callers split two ways, and the split is principled

`buyer_type` is an **external fact** — who actually paid — which an operator holding the invoice can
observe. §13.3's `software_native_advantage` and §13.4's third flag are **readings of the colony's
own prose**, which is what §23.5 keeps out of the kernel and what ADR-032's scored Auditor exists
for: §10.4 requires wrongful flags to be penalised, and prose cannot be penalised. An operator does
not need a Brier score; an Auditor does. One generic judgments table would have scored nobody and
constrained nothing — and could not have stated §12.1's four bins, which migration 0029's CHECK does.

### Three dimensions, three routes

`novelty_distance` is **structural** (the kernel computes it), `revenue_recurrence` is **observed**
(derived from the ledger), `buyer_type` is **declared** (no query can produce it). A Cell writes none
of them, and for the declared one that is structural rather than promised.

### The refusals that carry the most

- **Attesting a party who never paid is refused** — the check a foreign key would have been, since a
  counterparty is a value on payments rather than a row. Without it a typo is a *silent no-op*: a
  valid attestation, a success message, and no descriptor moves.
- **Mixed is checked before incomplete.** Two segments among the attested buyers is monotone — no
  further attestation can unmix them — so that abstention is permanent. Checking incompleteness first
  would tell an operator to attest more buyers in the one case where it cannot help.
- **A withdrawal is not "never asked."** A withdrawn party stays present with no position, because
  somebody looking and declining to say is a different fact from nobody looking.

### Verification

- **Teeth-checked twelve ways, all CAUGHT**, including a Cell-reachable module reaching the
  attestation (§0.3) and a faithful mixed-collapse that returns a bin rather than only changing a
  reason string.
- **1092 tests and the golden run green.** `balances` identical in every account in every book — a
  declaration is not a transaction. The replay **attests twice and supersedes**, because a single
  attestation reports the same bin whether the read takes the latest row or the earliest.
- Next: §12.3's Thompson posteriors are what turn this archive into quality-diversity, and they need
  stage *conversions* — `promotion.allocate` only ever issues rung 7, so **the ladder's next rung is
  the gating build**. The Auditor path for §13.3/§13.4's content judgments is now the clearly-scoped
  other half, and ADR-032's machinery is already most of it.
