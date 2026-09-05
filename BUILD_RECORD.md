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
decision loop's own first sub-slice (a run record that never named its own
selection policy, founder concentration as a real time series),
2026-07-21 through 2026-09-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-05 — Closing the evolutionary decision loop, part 1: simulator-native fitness dimensions, the full decision-record schema, Thompson sampling (Slice G, part 1)

Continuing the plan from ADR-077 without a fresh plan-mode round-trip. ADR-078 is the full as-built
record.

### What shipped

New `src/mitosis/simulation/candidate.py`: simulator-native gates (`not_quarantined`;
`reproducibility` — a genuine canonical measurement via cross-Cell replication of a revenue-producing
result, not a port of the kernel's permanently-unmeasurable version) and axes (`structural_novelty`,
reused from `novelty.descriptors()` by direct call since it's genome-content-only;
`realized_net_revenue`; `experiment_success_rate`; `economic_potential`, permanently unmeasurable
even here — §0.3's refusal is structural, and the simulator has no self-reported-upside field to even
decline). `dominates()`/`pareto_frontier()` reimplement `selection.py`'s exact rule over the new
candidate shape; `niche_elite()` gives `novelty.py`'s archive the elite-per-niche rule its own
docstring says it deliberately lacks. `posteriors.sample()` adds one Thompson-sampling draw without
disturbing the module's stated boundary — comparing niches' draws stays absent, reserved for G5.

`SelectionDecision` gains nine new fields, all defaulted, so no existing policy or test needed to
change shape: gate results, measured/unmeasured dimensions, Pareto-front membership,
`niches: tuple[NicheStanding, ...]`, per-parent operator/budget overrides (ADR-074 logged deferring
exactly this generalization), and `intended_experiment`. `RandomEligibleSelection` now reports every
known dimension as `unmeasured_dimensions` — an explicit "nothing consulted," not a silent empty
tuple. `runner.py`'s reproduction loop consults the per-parent overrides with a fallback that keeps
every prior run's behaviour byte-identical.

### A wrong first verification, caught before it shipped

The first draft of the budget-override test checked the child's *current* USD_SIM cash balance —
wrong, since a child born early in a 20-epoch run has since earned its own revenue. Fixed to query
the `cell_reproduction_funding` transaction itself (fixed at birth, and — found while fixing this —
a genuinely different transaction type from founding's `cell_birth_funding`).

### Verification

30 new tests across three files (80 total in the simulation area): every gate/axis function on
constructed fixtures; `dominates()`'s strict-improvement and disjoint-measured-axes cases;
`pareto_frontier()`'s gate filtering; `niche_elite()`'s evaluated-vs-exploratory split;
`posteriors.sample()`'s statistical convergence, determinism, and seed-sensitivity; the
decision-record honesty field; the per-parent override mechanism through a live run. Seven
teeth-checks, each confirmed to fail for the stated reason and restored verbatim. Full suite green;
golden run unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both
clean.

- Next: G2 — `SingleLeaderboardSelection`, the smallest new policy (no gates, no niches), proving the
  CLI/factory wiring pattern before G3 (`ParetoSelection`), G4 (`MapElitesSelection`), and G5
  (`StagedFundingSelection` + the `EnvironmentSuite.validation` consumer) build on it — then Slice
  H's pre-registered Phase 3 comparisons. The >= 500 Cell/>= 10,000 epoch Phase 2 acceptance
  benchmark itself remains documented but not yet run to completion (ADR-076).
