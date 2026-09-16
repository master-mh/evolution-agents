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
person declares, and the trial's legal identity, 2026-07-21 through
2026-09-16):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-16 — A failed call is its own outcome, not the Cell's unparseable reply (ADR-101)

Ollama's Metal backend died mid-session on 2026-09-15 and `mitosis wake` reported the Cell had failed to
produce a valid proposal — then bought a second call to re-prompt the provider that was down.
`gateway.call_model` does not raise on a provider failure: it classifies the outcome, records it, and
returns the call. `deliberation.py` read `response_text or ""` straight past that, and an empty string
parses exactly like a model ignoring the schema.

### What shipped

- `gateway.call_failure(call)` — `None` when the call succeeded, otherwise the status, the provider and
  the gateway's already-redacted error. One place a caller reads the classification the gateway made,
  living in the layer that wrote it.
- A fourth deliberation status, `call_failed`, and migration 0041 rebuilding the CHECK (SQLite cannot
  ALTER one). §24.2 is the reason it is a status and not a better sentence: provider drift must stay
  distinguishable from Cell evolution, and `status` is what every reader groups by. Two row-shape CHECKs
  ride along, since the rebuild is the chance to take them: a `call_failed` row names the call that
  failed — one naming none is a refusal wearing the wrong status — and names no repair.
- **No repair.** A wake lost to an outage costs one call, not two. The repair call and every workflow step
  ask the same question: a repair that fails still ends the wake `unparseable` (the first reply really was
  the Cell's), but the note says the second call returned nothing; a workflow step that fails keeps the
  draft and the wake is still `proposed`.
- `scripts/measure_parse_compliance.py` reports call failures beside the parse rate, which had been
  counting outages as compliance failures — the hazard its own docstring named.

### Found

- **ADR-069 wrote the false premise down**, four paragraphs above its own counter-example: "the first call
  is known to have **succeeded and been billed** (it returned response text)" — and then, below, that a
  `failed` row "needs no special handling ... flows through the same path". A `failed` row is exactly the
  case where nothing was returned.
- **The Auditors have the identical defect and it costs more there.** `auditor.py` and `content_audit.py`
  parse `response_text or ""` too, and §10.4 makes a rejected audit a fitness fact about the *Auditor*.
  Not fixed here — what an `audits` row says with no verdict is its own schema decision, and ADR-070's
  rule is that an extension to the Auditors earns itself. Logged, with the stale ADR-022 comment
  ("the call is bought and committed by now") it leaves behind.
- **A teeth check caught a test passing for the wrong reason.** The rebuilt table's `wake_key` UNIQUE
  check was satisfied by the fixture's dangling genome reference, because the migration re-enables foreign
  keys on its last line. Now disabled again and matched by error name.

### Verification

1577 tests pass (12 new), golden run exact at version 42 — no snapshot field moved, which is the
honest outcome for an outcome the fixed scenario never produces — ruff and docs-facts clean. 15 guards
teeth-checked, 15 CAUGHT. Reproduced end to end with `OLLAMA_HOST` pointed at a dead port: one `failed`
call, both reservations released, nothing settled, `Deliberation … (call_failed)` naming the provider.

- Next: §28 Phase 9's remaining kernel items — the liability reserve (refunds and chargebacks now give it
  a trigger; the share and window are policy), a merchant channel behind `real_commerce`, and §1.1's
  operating-cost terms. Still the operator's: the real-money budget, and whether to open any channel.
