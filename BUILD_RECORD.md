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
comparisons, a sealed simulated run, and tools naming what observes their
effect,
2026-07-21 through 2026-09-14):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-14 — Two measurement instruments: judge entanglement and evaluator epochs (ADR-087, ADR-088)

Fourth of the research-driven slices; scripts only, no kernel change.

### What shipped

- `scripts/judge_entanglement.py` asks whether two judges from different families fail
  independently, which §24.3 and §10.5 both assume. It scores the concreteness fixture through the
  instrument's own judge and reports joint errors against independence, error phi, the conditional
  error rate, and false concurrence — with warnings for the two shapes that make phi meaningless.
- `concreteness.py --json` and `diversity.py --json` now carry an evaluator stamp (model, weights
  digest, instrument-text hashes), and `scripts/evaluator_epoch.py` refuses to compare two results
  from different evaluator epochs — the Red Queen Gödel Machine's fixed-criteria-per-epoch rule, and
  §24.2's regime-change rule applied to the instruments.

### Found

- **The first entanglement number was forced, and nearly became the headline.** phi +0.66 and 5 joint
  errors against 1.9 expected — until the script checked for degeneracy: `llama3.2` returned `empty`
  for all 24 proposals, so its errors are the nine concrete labels and `qwen2.5`'s five misses could
  only land among them. Established instead: `llama3.2` cannot serve as a second concreteness judge;
  the pair produced no false concurrence.
- **The live measurement harness has been broken since ADR-067.** `measure_parse_compliance.py`'s
  built-in genome and `scripts/genomes/loose.json` give `model_policy` as a string, which the closed
  `model_policy` schema refuses — so setup cannot create a Cell. Fixed in the verbalized-sampling
  slice, which needs the harness.
- **Kernel precision crosses model changes** (`auditor.precision`, `content_audit.precision`) — logged.

### Verification

Both scripts' `--selftest`s pass (maths and stamp comparison, no model); `concreteness.py
--check-verifier` and `diversity.py --selftest` still pass; stamps hand-verified live with real
digests; `ruff check .` clean.

- Next: verbalized sampling (with the harness fix), the workflow gene, the §11.3 amendment, the
  teeth-check runner, the claim-drift checker; then Slice H.
