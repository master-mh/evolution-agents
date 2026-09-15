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
epochs), verbalized sampling as a genome sampling policy, and
Amendment A20 naming collusion and counterparty deception,
2026-07-21 through 2026-09-15):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-15 — A teeth-check runner that cannot touch the real tree (ADR-091)

Seventh of the research-driven slices; tooling, no kernel change.

### What shipped

- `scripts/teeth_check.py` takes a JSON list of mutations (`file`, `old` occurring exactly once,
  `new`, `test`, `expect`) and runs each in its own copy of the working tree — uncommitted work
  included; `.git`, `.venv`, caches and colony databases excluded — with `PYTHONDONTWRITEBYTECODE=1`
  and `PYTHONPATH` at the copy, in parallel. Verdicts: `CAUGHT`, `WRONG-FAILURE`, `MISS`, `INVALID`.
  It fails loudly if the real tree's digest changed.
- `.claude/agents/teeth-checker.md`: an agent that writes the mutation spec, runs the script and
  reports each verdict with its assertion line, carrying this repo's rules about complete mutations
  and secondary rules rescuing a mutation.
- CLAUDE.md's teeth-check section points at both.

### Found

- **`PYTHONPATH` beats the editable install** — probed with a stub package before relying on it, so
  a copy's `src/` really is what its test imports.
- **`expect` narrows a false CAUGHT; it does not remove one.** Of 17 guards checked through it this
  session, one `expect` (`AttributeError`) matched the test crashing on a missing `cache_clear` rather
  than failing on the property. Reading the assertion line caught it; the test was rewritten not to
  depend on the cache's API and re-checked.

### Verification

`tests/test_teeth_check.py` (3 tests) pins all four verdicts against a throwaway project — including
an incomplete mutation that must report `WRONG-FAILURE` — and that the real tree is never touched.
Used in anger for 17 mutations across the verbalized-sampling fix and the workflow gene.

- Next: the claim-drift checker and its weekly routine; the workflow gene; then Slice H.
