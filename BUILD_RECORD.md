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
cannot touch the real tree, and every *Disproved by:* pointer run and
dated, 2026-07-21 through 2026-09-15):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-15 — Workflow structure is a gene the kernel runs (ADR-093)

Ninth of the research-driven slices: the agent-swarm item. How a Cell thinks — one pass, a draft
revised by self-critique, or independent drafts and a review — is now inheritable and mutable, and the
kernel runs it.

### What shipped

- `genome.WORKFLOW_STRUCTURES`, a closed set; `genome.workflow_structure_of`; a dict `workflow`'s
  `structure` outside the set is refused at birth, while prose `workflow` stays valid and selects nothing.
- `deliberation._run_workflow` over a draft that already validated: `_workflow_call` makes each further
  step its own `gateway.call_model` on `deliberation:{wake_key}:workflow:{step}`, and
  `_WORKFLOW_RUNNERS` holds one runner per multi-call structure. The `cell_deliberated` audit event
  records each step's call id and note, and which proposal won — for such wakes only.
- `simulation.mutation`'s workflow operator draws from the kernel's set.
- `deliberation.py`'s docstring no longer says "no genome field selects a code path": a genome chooses
  among kernel-owned paths, as with temperature, and supplies none (Charter C15).

### Found

- **The simulator had been breeding four workflow structures that no code read.** §16.3 reserved the
  socket, `workflow_variation` mutated it, and every Cell woke as a single pass regardless. `sequential`
  was dropped rather than given an invented meaning; role decomposition is logged.
- **Live smoke (`qwen2.5`):** `parallel_review` 3/3; `iterative_refinement` 2/3, the third wake
  unparseable before any step and buying none. Every draft in the refinement run needed a repair — a
  format-compliance fact about the draft prompt, not the structure.
- **A CLI test that read the machine's Ollama** failed three different ways this session (a busy daemon
  timed out, then its GPU backend failed). It now points at a closed loopback port.

### Verification

21 tests; twelve teeth-checks in isolated copies, all on the intended assertion; full suite 1419 passed
before the hermetic test fix; golden run unchanged.

- Next: Slice H (Phase 3's pre-registered selection test); the claim-drift routine; the
  verbalized-sampling twin rerun on an idle machine.
