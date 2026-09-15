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
dated, workflow structure as a gene the kernel runs, and Slice H's arm
settings and the simulator stall they uncovered, 2026-07-21 through
2026-09-15):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-15 — Slice H, part 2: Phase 3's pre-registered run — no selection effect (ADR-096)

The pre-registration (9bb866c) was committed before the run; the confirmatory batch ran once from it; the
result is recorded as it came out.

### What shipped

- `docs/PHASE3_RESULTS.md`: integrity, verdicts through each declared interval, the gate table, two post hoc
  checks marked as such, per-arm descriptives, every `simulate-compare` invocation verbatim, and the design
  pilot's effects beside the confirmatory ones.
- `docs/benchmarks/phase3-confirmatory/`: `batch.json` and 224 manifests (6.2 MB), all at code version
  9bb866c and policy version 2, so every comparison reruns from the artifact alone.

### Found

- **H1, the gate's selection effect: not supported** (−2.86, CI [−6.59, +0.83]). H3 not supported. H4
  supported: the lineage cap bounds founder share. H2 and H5 supported as registered, and post hoc checks
  show H2's diversity gain is headcount and H5's price response is as large without revenue-ranked
  selection.
- **`random_eligible` is weak selection on sales, not random reproduction**: a child is eligible only once
  it has sold.
- **A run's `code_version` names HEAD, not the tree** — the design pilot's manifests name a commit older
  than the code they ran. Logged.
- The runtime estimate from the pilot was low: 3,090 s, not ~1,800.

### Verification

Code unchanged since 3256737; full suite, golden run, ruff and docs-facts re-run before this commit. Every
verdict in the results document is the analysis script's output; every interval reruns from the artifact.

- Next: Phase 3's parallel track needs a new pre-registration, not a reread of this one (candidates in
  FUTURE_BUILD_HOOKS.md); Phase 4 is not blocked. Still open: ADR-089's verbalized-sampling twin, and the
  claim-drift routine once GitHub access is granted.
