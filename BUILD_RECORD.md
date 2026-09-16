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
§12.1's declared third dimension, rung 8, §12.3's `P(next stage)`, the
Auditor path for §13.3/§13.4's content judgments, the software_native_advantage
gate reading a resolved content audit, model_policy's temperature socket,
risk_tier becoming optional for abstain, the bounded single parse-repair
retry, the argued refusal to extend it to the Auditors or `call-model`,
an external audit's clean source-distribution archive, its egress-boundary
repair (robots.txt transport, SSRF, honest personal-data status),
documentation/safety-claim reconciliation, a narrow runtime-defect lint gate,
auto-promotion reaching the scheduled `tick`, the flight simulator's five
slices (mock Cells deciding through the real deliberation pipeline; a second
market family with environment separation and regime shifts; the remaining
mutation operators wired through a real choice; chaos drills as repeatable
scenarios; manifest richness, a CI-scale acceptance test, a founding cap bug
fix, and a retained benchmark artifact), and closing the evolutionary
decision loop's six sub-slices (a run record that never named its
own selection policy and founder concentration as a real time series;
simulator-native fitness dimensions, the full decision-record schema, and
Thompson sampling; the single-leaderboard control policy; Pareto selection
reproducing the whole front, and a gate found structurally unreachable
through this pipeline; MAP-Elites, one elite per occupied niche; staged
funding composing everything, and the cross-family validation deadlock it
surfaced; the cross-policy acceptance harness), seed-paired batch
comparisons, a sealed simulated run, tools naming what observes their
effect, two measurement instruments (judge entanglement and evaluator
epochs), verbalized sampling as a genome sampling policy, Amendment A20
naming collusion and counterparty deception, a teeth-check runner that
cannot touch the real tree, every *Disproved by:* pointer run and
dated, workflow structure as a gene the kernel runs, Slice H's arm
settings and the simulator stall they uncovered, and Phase 3's
pre-registered run that found no selection effect, and refunds and
chargebacks naming the payment they reverse, and payment fees as a
charge nobody chose, and §1.1's profit report with the shadow rate a
person declares, 2026-07-21 through 2026-09-16):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-16 — The trial's legal identity, and an account the schema cannot hold (ADR-100)

§28 Phase 9 trades under "one legal business identity". Since ADR-097 the colony has recorded revenue,
refunds, chargebacks and fees — every one attributing to a legal person who appeared nowhere in the
database. The operator asked for the identity and payment account to live in the kernel.

### What shipped

- `trial_identity.attest`, `mitosis set-trial-identity`, `mitosis trial-identity`: operator-only,
  append-only, latest wins, and a withdrawal is a new row that keeps *why* in the record (§3.6) — the
  shape ADR-041 and ADR-062 already established, reused rather than reinvented.
- Migration 0040, whose CHECKs refuse eight consecutive digits and the obvious secret prefixes: **an
  account number, card or key cannot be stored by any caller.** `attest` refuses more, with a message
  naming what to write instead ("Stripe account: personal").
- §16.3's other half: the genome has refused a `legal_identity` gene since it shipped, and a test now pins
  that tripwire to the record it was waiting for.
- `mitosis profit` names whose profit it is, or says "trading as: nobody". Golden 41 → 42.

### Found

- **A grouped account number slips past the schema.** "GB29 NWBK 6016 1331 9268 19" has no run of eight
  digits, so migration 0040's GLOB cannot see it; only the Python total-digit rule catches it. The two
  rules are not redundant, and the one with no backstop has its own test and its own teeth-check.
- **Nothing is gated on the identity**, deliberately: `real_commerce` is off, so a gate refusing a listing
  without an identity would never be exercised. It belongs with the channel work.

### Verification

1565 tests pass (25 new), golden run exact at version 42, ruff and docs-facts clean. 11 guards
teeth-checked, 11 CAUGHT — including the golden scenario refusing to store an account number.

- Next: §28 Phase 9's remaining kernel items — the liability reserve (refunds and chargebacks now give it
  a trigger; the share and window are policy), a merchant channel behind `real_commerce`, and §1.1's
  operating-cost terms. Still the operator's: the real-money budget, and whether to open any channel.
