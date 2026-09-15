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
epochs), and verbalized sampling as a genome sampling policy,
2026-07-21 through 2026-09-15):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-15 — Collusion and counterparty deception are policy violations (ADR-090, Amendment A20)

Sixth of the research-driven slices: a normative spec amendment, no code. **Flagged for the
operator's review** — it adds to what §10.5 treats as a policy violation.

### What shipped

- **Amendment A20** in SPEC.md's amendment list. Agreeing with any party outside the colony on
  prices, output, bids, territories or customers, and misrepresenting facts to any counterparty, are
  §10.5 policy violations, never strategies selection may reward.
- **§11.3**: Auditors also inspect external communications for coordination with outside parties
  and misrepresentation to counterparties.
- **§21.2**: the boundary. Coordinating sibling Cells' offers through the registry is the colony
  acting as one business — the clause exists to *prevent* sibling bidding wars — so the line is the
  colony's edge, not the Cell's.

### Why now

Selection rewards what pays. Vending-Bench Arena found price agreements formed and broken by all
three frontier models placed in one market, and deception (false supplier quotes, feigned
cooperation) from the one that earned most. Nothing enforces A20 today because no Cell has an
autonomous external channel; that is exactly when to write it, so the first such channel arrives
with the violation already named rather than argued about after a run has found it profitable.

### Not built

Detection. A keyword filter was rejected: coordination and deception are semantic, and a filter
would be a §23.5 surface that reads as enforcement it is not. The natural consumer — an Auditor
content-audit kind over `external_actions` intent and completion records — is logged in
FUTURE_BUILD_HOOKS.md.

### Verification

No code changed. `check_docs_facts.py` and the golden run are unaffected; the full suite was run on
this tree as part of the verbalized-sampling commit's verification.

- Next: the teeth-check runner, the claim-drift checker, the workflow gene; then Slice H.
