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
and auto-promotion reaching the scheduled `tick`,
2026-07-21 through 2026-09-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-05 — Phase 2 flight simulator, first slice: mock Cells decide through the real deliberation pipeline (Slice F, part 1)

The brief calls this "the highest-value substantive build" and the last gate before real
evolutionary evidence — SPEC.md's own Amendment A1 already concedes this repo built Phase 4 (the
LLM loop) before Phase 2, so nothing has ever exercised the kernel's governance/accounting machinery
at population scale. Given the size, a plan was written first — three parallel research passes over
the actual current code (genome/lineage/death; selection/novelty/promotion; providers/deliberation/
revenue), not memory — and approved before any code. `docs/DECISIONS.md`'s ADR-072 is the full
as-built record, including three places building it refined the plan; this entry is the summary.

### What shipped

New `src/mitosis/simulation/` package (migration 0035 for its own `simulation_runs` audit row,
`pricing.py` gains a zero-cost `("simulation", "policy-v1")` entry, `cli.py` gains `mitosis
simulate`). Every birth, death, transaction, experiment, and capital movement goes through the
*existing* kernel entry points — `lifecycle.create_cell`/`lineage.reproduce`, `ledger
.post_transaction`, `experiment_grants.start_from_grant`/`experiments.conclude`, `revenue
.record_revenue`, `scheduler.tick`. The simulator supplies only the decisions nothing in the kernel
makes today:

- **`policy.py`** — `SimulationPolicyProvider` implements the existing `providers.ModelProvider`
  Protocol, so a mock Cell's proposal plugs into `scheduler.tick()` unchanged and still passes
  through the real proposal schema, risk assessment, and approval queue. Deterministic per call from
  `(genome content shown this call, a monotonic call counter)`, not per-Cell identity — the Protocol
  carries none, and two Cells can share a genome hash right after birth.
- **The plan proposed a new manual approval decider for `spend_request` grants; building it found a
  cleaner path.** `approval._kernel_tier` has no branch at all for `ProposalKind.EXPERIMENT` — a
  LOW-claimed, reversible, signal-free one is genuinely `batchable` and auto-approved by the
  *existing* `autopromotion.sweep()` step ADR-071 already wired into `tick()`. This also explains two
  reserved sockets already sitting unfilled in the repo: `experiment_grants.FLIGHT_SIMULATOR_RUNG =
  1` and `experiments.LADDER`'s rung-1 label, verbatim, `"flight simulator"`.
- **`environment.py`** — `MarketEnvironment` Protocol plus one concrete family
  (`UtilityMaximizingMarket`): customers buy when a seeded willingness-to-pay meets the genome's
  declared price. Brief requires >= 2 families; only one ships here.
- **`mutation.py` / `selection_policy.py`** — the required no-op/control mutation, and
  `RandomEligibleSelection` (brief Slice G's own policy #1, built here since it is also Slice F's
  own minimum — some reproduction across niches, not quality-diversity selection). The
  `SelectionPolicy` Protocol is designed to Slice G's full decision-record shape now, so the other
  four named policies are additive later rather than a rework.

### Three bugs found by running it, not by reading it

`random.Random()` does not accept a tuple as a seed (every draw was keyed on one; fixed to a stable
f-string, which — unlike `hash()` — does not depend on `PYTHONHASHSEED`). `experiment_grants
.start_from_grant` raises two sibling exceptions and only one was caught: `ExperimentConflictError`
(expected — an approval's own `WAKE_HUMAN_DECISION` follow-up becomes ready only on the *next*
tick, so a cell often carries two pending grants into one epoch) was handled, but at population >=
`max_parallel_experiments` (default 20, §9.2's colony-wide slot cap) the sibling
`ExperimentCapacityError` fired just as often and, uncaught, aborted the whole epoch before anything
could conclude — stranding every running experiment permanently. A smoke-scale test (population <=
10) never exercised this; only a manual population=20 run did. And the first invariant check counted
`Book.USD_REAL` transaction rows, which fails on every run: `gateway.call_model` reserves and
releases against USD_REAL for *every* call regardless of provider (a same-Cell cash<->committed pair
netting to zero) — pre-existing bookkeeping, not spend. Fixed to sum `external_expense` activity,
which is what "zero USD_REAL movement" actually means.

### A gap fixed while building

`lineage.reproduce()` funds a child only in the parent's own book — a child born this way had no
USD_REAL/RESOURCE balance and would be permanently unschedulable. Every reproduction now also funds
the child's scheduler-eligibility sliver from `seed_bank`, same as founding. Confirmed live:
population 20 -> 70 over 50 epochs, children actually woken and participating in later epochs, not
just present as inert rows.

### Verification

- 12 new tests (`tests/test_simulation.py`): same-seed determinism (byte-identical manifests except
  `run_id`); the `external_expense` invariant; population growth through the real reproduction path
  (population raised to 10 so a lineage's first child clears `max_lineage_population_fraction`'s
  0.20 cap — the same founder-effect tension FUTURE_BUILD_HOOKS.md already documents, which bites
  immediately at population=3); a reproduced child's own USD_REAL/RESOURCE funding; a population=20
  run against §9.2's cap; a CLI end-to-end run; the policy's prompt-extraction seam; environment
  purity; a structural test that no kernel module imports `simulation`.
- Every bug above teeth-checked in the literal sense: fix reverted, the specific new test confirmed
  to fail for the stated reason, fix restored — including a temporary fake USD_REAL spend inserted
  into the epoch loop to prove the invariant actually catches one.
- Full suite green (1249, up from 1239 — the file's own 12 plus 2 that already existed as a wash);
  golden run unaffected (hash unchanged at 38 — new package, a migration nothing existing reads, a
  new CLI verb, no existing scenario touched); `ruff check .` and `scripts/check_docs_facts.py` both
  clean (README's migration count and phase-status table updated — Phase 2 split from Phase 3 to
  say precisely what is and is not built rather than one blanket "not built" claim).
- Manually run at population=20/epochs=50 (~5.6 epochs/sec on this hardware) specifically because
  the automated suite's smoke scale would not have surfaced the capacity-cap bug.

- Next: the plan's own sub-slice sequence continues — a second, independently-shaped environment
  family and environment separation (§8.1) next, then regime shifts (§8.4), the remaining mutation
  operators (§14.1), chaos drills, and the two acceptance-scale configurations, before Slice G's
  remaining `SelectionPolicy` implementations and Slice H's pre-registered Phase 3 comparisons.
