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
dated, and workflow structure as a gene the kernel runs, 2026-07-21
through 2026-09-15):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-15 — Slice H, part 1: Phase 3's arm settings, and the stall that hid every comparison (ADR-094, ADR-095)

Phase 3's pre-registered comparisons need two settings that are not selection policies and metrics that
headcount cannot move. Building them, the first pilot showed every arm had stopped experimenting at
epoch 27. The stall is fixed before any comparison is run or pre-registered.

### What shipped

- **Arm grammar** (`batch.parse_arm`): `LABEL=POLICY[+static_market][+lineage_cap=F]`; `batch.json`
  records every label's settings. A static market (`environment.STATIC`) is the shifting market minus the
  shift, drawing identical numbers. `RunConfig.lineage_cap` is applied before founding, refused against
  a colony configured otherwise, and read back into the manifest.
- **Metrics:** `revenue_per_concluded_experiment`, `second_half_revenue_per_concluded_experiment`,
  `final_mean_price_minor_units` (from a new `EpochRecord.mean_price_minor_units`).
- **Policy version 2** proposes on its research cycle only. The runner individually approves synthetic
  experiment requests flagged for flooding alone, and serves slots to the Cells that have waited longest.
- **Declared untested, per the operator:** shared knowledge vs isolated cohorts, and reciprocal-credit
  attacks — the simulator represents neither.

### Found

- **The stall (ADR-095):** a proposal on every wake × a wake on every approval → a flood → §23.4's
  `queue_flooding` → a request that never ages out of a simulated run (the queue runs on wall time) →
  every later request from that lineage flagged. Approvals stopped at 500 by epoch 7; the backlog ran
  out at epoch 26. The retained benchmark and ADR-084's pilot ran this policy; the earlier "saturation
  trap" reading of the benchmark was partly this.
- **A teeth-check miss on the first pass:** a static-market test compared against another instance of
  the same class, which shares the bug under test. Now checked against each family's pre-shift rule.
- `environment.py`'s comment said willingness to pay scales with the Cell's price; the code uses a fixed
  500.

### Verification

46 new tests (37 + 9); 24 teeth-checks in isolated copies, all CAUGHT on the intended assertion after the
one test fix; golden run unchanged (the simulator is not in it); ruff and the docs-facts check clean.

- Next: the Phase 3 pre-registration (committed before any confirmatory batch), then the runs.
