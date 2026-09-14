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
surfaced; the cross-policy acceptance harness),
2026-07-21 through 2026-09-06):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-14 — Seed-paired batch comparisons (ADR-084)

The first of a set of slices acting on a research pass over recent agent-swarm, evolutionary-agent
and evaluation work. This one is the Slice H prerequisite that pass pointed at most directly.

### What shipped

`simulation/batch.py` runs every arm at every seed, each `(arm, seed)` in its own spawned process
against its own `:memory:` colony, and writes one manifest per run plus a `batch.json` index
(`mitosis simulate-batch`). `simulation/paired.py` compares two arms seed by seed over a closed set
of named manifest metrics (`mitosis simulate-compare`): the mean per-seed difference, a seeded
percentile-bootstrap CI on it, an unpaired CI over the same numbers, the across-seed correlation,
and `Var(d)/(Var(a)+Var(b))`. `cmd_simulate`'s staged-funding validation default moved into
`batch.build_selection` so a single run and a batch arm cannot disagree about it.

### Measured before choosing

- **Processes, not agents.** A run is deterministic CPU work against mock Cells; there is no model
  call to fan out. 24 runs took 10.6s wall for 65.5s CPU on 8 workers.
- **In memory, not file-backed.** The same p=30/e=40 run: 17.6s file-backed (5.3s system CPU) vs
  9.1s in memory (0.03s). That is the p=50/e=200 benchmark's 480s of system CPU explained.

### Found

- **Pairing is metric-dependent, in both directions.** A 3-arm × 8-seed pilot: total revenue
  correlates +0.96 across seeds and pairing cuts its variance to 7%; peak founder concentration
  correlates −0.20/−0.42 and pairing *widens* its interval (ratio 1.19/1.29). Slice H's
  pre-registration has to declare the paired design per metric.
- **Two candidate metrics are one effect at this scale.** `final_living_cells` and
  `total_reproductions` report the identical difference over 25 epochs (nobody dies), so
  pre-registering both would count one effect twice.
- **The pairing precondition held already and is now pinned.** Every simulator draw was keyed by its
  own seed label; a new test runs a selection policy that burns its stream, the global `random`
  module and the seeded id generator, and requires an identical economy.

### Verification

19 new tests. Four teeth-checks, all caught for the stated reason (environment keyed by
`experiment_id`; paired CI from unpaired resamples; a failed run silently counted; unpaired seeds
silently intersected — the last first written as a bare guard removal that crashed with `KeyError`
instead of intersecting, i.e. an incomplete mutation, then redone completely and caught). Full suite
1353 passed; golden run unchanged; `ruff check .` and `scripts/check_docs_facts.py` clean.

- Next: the rest of the research-driven set — a network/process seal on simulated runs, Auditor
  judge entanglement, verbalized sampling as a twin experiment, a real consumer for the workflow
  gene, a tool-evaluator registration guard, evaluator-epoch bookkeeping, the §11.3 collusion
  amendment, a teeth-check runner and a claim-drift checker — then Slice H.
