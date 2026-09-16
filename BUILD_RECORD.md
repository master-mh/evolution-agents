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
chargebacks naming the payment they reverse, 2026-07-21 through
2026-09-15):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-16 — Payment fees: a charge nobody chose (ADR-098)

§1.1's third deduction after refunds and chargebacks, and the one every live sale carries. No path could
record a USD_REAL charge that was not a model call — reserved before it happened and settled after. A
processor's fee is neither: it is taken out of the payout.

### What shipped

- `payment_fees.record_payment_fee` and `mitosis record-fee --on TXN --amount A --source REF`: a fee taken
  on a revenue payment or a chargeback, inheriting that charge's Cell, book, experiment and artifact. A
  refund is not chargeable — the fee on the sale was charged on the sale, and a fee on the refund would
  count it twice.
- Migration 0038: `ledger_transactions.charged_on_transaction_id`, beside 0037's link — in the hash
  preimage when set, a foreign key, and a CHECK tying it to exactly `payment_fee`.
- **Imposed, not chosen:** posted directly and never refused by a cap, then counted by every global
  window, so the next spend the colony *does* choose meets a cap the fee helped fill.
- The breaker's registry now names a route per registered type — a reservation, a model-call key, or
  provider-less — and a guard refuses a type in no route or two, or a model-call charge filed
  provider-less.
- Golden 39 → 40: one USD_SIM fee, on the invoice that carries the artifact.

### Found

- **§25.2's read-back sees a fee with no reader changed.** `assessments[0].spend_since_minor_units` moved
  0 → 2 in the replay — the expense leg's Cell tag doing its job through `spend_by_book`.
- **A fee is the first real charge with no provider.** The per-provider window reaches a direct posting
  only through the model call its key names, so the registry had quietly assumed every direct charge had
  one.

### Verification

1524 tests pass (27 new), golden run exact at version 40, ruff and docs-facts clean. 14 guards
teeth-checked, 14 CAUGHT.

- Next: §1.1's operating-cost terms (hosting, advertising, data/software, fulfilment) — chosen spend,
  which reserves before a person pays rather than posting after — then the report of both profit figures.
  Still the operator's to decide: legal identity, payment account, real-money budget.
