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
pre-registered run that found no selection effect, 2026-07-21 through
2026-09-15):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-15 — Refunds and chargebacks: the first of Phase 9's books (ADR-097)

Phase 3's gate is soft and Phase 4 is not blocked. The shortest path to real money the spec allows is §28
Phase 9's supervised trial — Cells propose, a person carries out every external action — and its
acceptance asks for tracked refunds and a real profit report. Nothing could take money back.

### What shipped

- `revenue.record_reversal` (a refund or a chargeback) and `mitosis record-refund --payment TXN --amount A
  --source REF [--chargeback]`. It names the payment and inherits its Cell, book, experiment, artifact and
  buyer digest; reversals of one payment never exceed it; a replay returns before the bound; a dead Cell
  is reversed too and its cash may go negative (ADR-021's rule).
- Migration 0037: `ledger_transactions.reverses_transaction_id` — in the hash preimage when set, a foreign
  key, and a CHECK tying it to exactly the two reversal types.
- `total_revenue` and `colony_revenue` removed in favour of gross, reversed and net readers. Domination,
  §25.2's read-back, the Cell's record (plus a line naming the reversal, only when there is one),
  `cell-fitness`, the simulator's two revenue axes and §2.6's report all read net.
- Golden 38 → 39: one USD_SIM refund, pinned to the invoice it reverses.

### Found

- **Every reader of revenue wanted net and read gross** — five modules a refund could not have reached.
- **The golden note's first draft overclaimed.** It said the pinned link was the only section that tells
  the two invoices apart; running the mutation showed `artifact_attributed_ledger_entries` moves too.
  Corrected before commit.
- **A provider failure is recorded as an unparseable reply and buys a repair call** — found by the live
  check against a failing Ollama. Logged, and offered as its own task.

### Verification

1497 tests pass (31 new), golden run exact, ruff and docs-facts clean. 17 guards teeth-checked, 17 CAUGHT.
**Not verified:** a live model reading the new record line (Ollama's Metal backend failed a direct
generate); the two-connection race on the bound is argued, not tested.

- Next: payment fees and other external operating costs, then §1.1's report of both profit figures. Before
  any live trial the operator decides the legal identity, payment account and real-money budget.
