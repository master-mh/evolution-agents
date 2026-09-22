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
person declares, and the trial's legal identity, and a failed model
call becoming its own deliberation outcome, and a repair turn that names
every required key, 2026-07-21 through 2026-09-17):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-22 — A self-critique loop on LangGraph, and tracing that is off until an operator says so (ADR-103, ADR-104)

ADR-093 made workflow structure a gene the kernel runs, and both multi-call structures it shipped are
straight lines: two or three calls in a fixed order. Neither can *branch* on what a step said, or *loop*.
`self_critique_loop` is the first that does, and it is the first place a graph framework earns its keep —
so its control flow is a LangGraph `StateGraph`, and nothing else is.

### What shipped

- **`self_critique_loop`**, a fourth structure in `genome.WORKFLOW_STRUCTURES`: after a validated draft,
  up to `MAX_CRITIQUE_REVISIONS` (2) rounds of *critique* (one call replying `{"verdict": "keep"}` or
  `{"verdict": "revise", "issues": [...]}`) and, on revise, *revise* (one call shown the named issues).
  At most five calls per wake. The last proposal that validated is recorded; a critique or revision that
  fails keeps it.
- **`workflow_graph.py`** — the graph: two nodes, two conditional edges, a reducer that appends each
  step's record, and a `recursion_limit` set just above the designed bound as a backstop. It imports
  nothing from the kernel (pinned by an AST test): it is handed two step functions and never sees a
  connection, a provider or a reservation. Every step is still `deliberation._workflow_call` on its own
  key (`…:workflow:critique:0`, `…:revise:0`, …), so C4, C6 and the draft-is-the-floor rule hold
  exactly as ADR-093 wrote them. **No checkpointer**: the gateway's idempotency keys already replay a
  crashed wake down the same path without paying twice, and a durable workflow engine is §17.5's
  deferred hook.
- **`_parse_verdict`** — strict like `proposal.parse`: only `verdict`/`issues`, a revise names at least
  one issue, at most 5 of at most 300 characters. The verdict never leaves the wake.
- **`tracing.py`** — opt-in LangSmith tracing. Off unless `LANGSMITH_TRACING=true` *and*
  `LANGSMITH_API_KEY` are set; project `LANGSMITH_PROJECT`, default `my-first-agent`. Every span opens an
  explicit `tracing_context(enabled=…)`, which overrides LangSmith's and LangChain's own environment
  switches. Forced off inside `network_seal.sealed()` and inside `tracing.suppressed()` (the golden run).
  One wake is one trace: `cell_wake` (in `deliberation.deliberate`) → `model_call` (an `llm` run in
  `gateway.call_model`, carrying `model_call_id` and the idempotency key) and LangGraph's node runs.
- Optional extras `langgraph` and `tracing`; `dev` includes `langgraph` so CI runs all of it. The
  simulator does not breed `self_critique_loop` (`mutation._NOT_BRED_STRUCTURES`) — its policy provider
  only ever replies with a proposal, so the loop would be a single pass plus one billed call every time.

### Found

- **LangGraph's node runs nest under a hand-opened LangSmith span without any glue**, and an explicit
  `tracing_context(enabled=False)` overrides `LANGCHAIN_TRACING_V2=true` for both libraries — each
  checked against a collector on 127.0.0.1 before the design relied on it.
- **The gateway opens its span after committing a reservation**, so a tracing library that raised there
  would strand both reservations — the exact shape ADR-085's `NetworkSealed` comment warns about. Span
  entry and exit swallow their own faults; the traced code's exceptions propagate unchanged.
- **A test's flush constructed the uploader it was checking for.** The golden-run test called
  `get_cached_client().flush()`, which creates a client when none exists; it now asserts that nothing
  constructed one.
- **Two teeth checks reported WRONG-FAILURE for a harmless reason**: pytest names string parameters by
  their text, so `[reply8]` selected nothing (exit 4). The verdict cases now carry explicit ids.

### Verification

1618 tests pass (28 new: 13 for the loop, 15 for tracing), golden run exact at version 42 — no snapshot
field moved, since no golden genome declares the new structure — ruff and docs-facts clean. 16 guards
teeth-checked, 16 CAUGHT. End to end through the CLI with tracing pointed at a local collector: three
wakes arrived as three traces in `my-first-agent`, uploaded before the process exited. **The live-model
smoke did not run**: the local Ollama's Metal backend failed every call (`XPC_ERROR_CONNECTION_INVALID`,
the 2026-09-15 failure again), which ADR-101 recorded correctly as `call_failed` with no loop steps bought.

- Next: rerun the three-wake `qwen2.5` smoke once Ollama is restarted, then the twin FUTURE_BUILD_HOOKS
  names — whether a revision *improves* a proposal, which neither this slice nor ADR-093 measured.
