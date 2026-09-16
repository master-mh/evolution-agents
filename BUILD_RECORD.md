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
charge nobody chose, 2026-07-21 through 2026-09-16):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-16 — §1.1's profit report: the colony can state its own result (ADR-099)

§1.1 opens the spec with `REAL_SETTLED_NET_PROFIT` and §32 closes with the same sentence; nothing
computed it. With refunds, chargebacks and payment fees recorded, the formula became computable.

### What shipped

- `profit.report` and `mitosis profit`: §1.1's formula with every term printed beside the total, derived
  on read and stored nowhere (§2.5) — so the subtraction can be checked rather than trusted.
- `mitosis set-shadow-rate` and migration 0039: the reporting-only rate the second figure needs, declared
  by a person and recorded with their name. §2.4 forbids the kernel choosing what a RESOURCE unit is
  worth, so without a declared rate the report abstains with its reason instead of printing 0.
- Human labour counted as billed **plus** subsidised, so unpaid work makes the colony look more expensive;
  free tiers counted as local-model calls; operating costs and donated infrastructure named as unmeasured
  on every report rather than zeroed.
- The autonomy adjustment is real-profit-only: a synthetic book carries the first figure and abstains on
  the second.
- Golden 40 → 41, pinning both books.

### Found

- **The rate guards are defended twice.** Deleting either Python check still fails its test, because
  migration 0039's CHECK constraints refuse the row. Two teeth-checks read WRONG-FAILURE until the
  expected text named the schema's message — the exit code alone would have called them holes.
- **A comment claimed more than the run does.** The first draft said the golden run pins USD_REAL at zero
  revenue *and* zero spend; it settles one USD_REAL reservation of 20, so real profit there is −20.
  Corrected before commit — the second such claim caught this session by checking rather than reasoning.

### Verification

1540 tests pass (16 new), golden run exact at version 41, ruff and docs-facts clean. 11 guards
teeth-checked, 11 CAUGHT.

- Next: the operator's trial identity and payment-account attestation, then §1.1's operating-cost terms —
  chosen spend, which reserves before a person pays rather than posting after.
