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
every required key, and a self-critique loop on LangGraph with opt-in
tracing, 2026-07-21 through 2026-09-22):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-22 — A read-only dashboard for watching the colony (ADR-105)

Watching a colony meant five terminal verbs, each a snapshot. `mitosis dashboard` is one page that
refreshes itself — and, because an operator is looking at money, one that is structurally unable to
change what it shows.

### What shipped

- **`src/mitosis/dashboard.py`**, standard library only, on 127.0.0.1:8765. Overview: scheduler health,
  book conservation and hash chain, population against limits, real spend against the hour/day/month and
  concurrent caps, the approval queue with overdue items flagged, model calls by provider and status, a
  row per Cell (status, generation, workflow structure, cash in all three books, net revenue, spend,
  Brier, wakes, any §10.5 death criterion met), and the last 25 wakes with each workflow's steps. A page
  per Cell adds genome, wakes, predictions and every billed call labelled by step (`draft`,
  `critique:0`, `revise:0`, …). `/api/overview` is the same data as JSON.
- **Read-only by construction:** a `mode=ro` connection per request, never a migration. **No script:**
  escaped values, `<meta>` refresh, a CSP of `default-src 'none'`. **Loopback only**, with no host flag.
- **`scripts/demo_colony.py`** — a fresh, offline, zero-cost colony built through the kernel's own
  operations (four founders across all four workflow structures, a provider outage, predictions, 11
  queued approvals), so the dashboard can be seen without a live model. Added to
  `KERNEL_DRIVING_SCRIPTS`: it is a harness, not a scorer.

### Found

- **Every reader the page needed already existed and ran on a read-only connection** — probed one by one
  before the design relied on it, so "cannot write" is SQLite's guarantee, not the module's promise.
- **A failed wake was rendered as "single pass"**, run into the error text: a wake that never produced a
  draft ran no workflow and now says only why it failed. Seen in the browser; no test would have shown it.
- **The analysis-boundary test refused the demo script** for importing the kernel — correctly, since
  scorers must not; the allowlist exists for harnesses.

### Verification

1627 tests pass (9 new), golden run exact at version 42, ruff and docs-facts clean. 5 guards
teeth-checked, 5 CAUGHT. Checked by eye against the demo colony at desktop and at 375px (no horizontal
scroll).

- Next: the money path — see PRIORITIES. The dashboard shows revenue as 0.00 on every Cell because no
  channel through which a customer can pay exists yet.
