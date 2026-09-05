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

## 2026-09-05 — Closing the evolutionary decision loop, part 2: the second selection policy, and the CLI/factory wiring the rest will reuse (Slice G, part 2)

Continuing the plan from ADR-077/078 without a fresh plan-mode round-trip. ADR-079 is the full
as-built record.

### What shipped

`SingleLeaderboardSelection` (brief Slice G policy #2): ranks eligible Cells by one named scalar
(`scalar_metric = "realized_net_revenue_minor_units"`), reproduces the single top-ranked Cell, runs
no gates — its `reason` states plainly this is the shape SPEC.md §10.2/§13.2 forbid for the
production kernel, built only as a Slice H comparator. `build_selection_policy(name)` mirrors
`environment.build_environment`'s existing pattern; `cli.py` gains `simulate --selection-policy`.
Unmeasured is excluded from the ranking, not treated as a floor value: a Cell with a concluded,
zero-revenue experiment must outrank one with no concluded experiment at all — the same
never-zero posture this codebase takes everywhere else, applied here to a policy that (unlike every
gate/axis in `candidate.py`) needs one total order rather than permission to abstain.

### Another teeth-check that initially passed for the wrong reason

The first version of the "unmeasured ranks last" test created the proven-zero Cell before the
unmeasured one; removing the exclusion term from the sort key still picked the right Cell, because
both collapsed to the same primary key and the *secondary* tie-break (creation order) happened to
favor the older, proven-zero Cell anyway. The same category of trap ADR-077 already hit once this
slice. Fixed by creating the unmeasured Cell first, so a dropped rule now produces an unambiguously
wrong answer regardless of generated-id ordering.

### Verification

4 new tests (84 total in the simulation area): the highest-revenue Cell chosen correctly; the
corrected unmeasured-ranks-last property; the factory's construction and rejection of an unknown
name; a CLI end-to-end run naming the policy it used in its own manifest. Four teeth-checks, each
confirmed to fail for the stated reason and restored verbatim. Full suite green; golden run
unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: G3 — `ParetoSelection`, gating on `not_quarantined`/`reproducibility` and taking the Pareto
  front over `structural_novelty`/`realized_net_revenue`/`experiment_success_rate` — reproducing from
  every surviving front member, not a single winner, against this slice's own
  `SingleLeaderboardSelection` comparator — then G4 (`MapElitesSelection`), G5
  (`StagedFundingSelection` + the `EnvironmentSuite.validation` consumer), G6 (the cross-policy
  acceptance harness), and Slice H's pre-registered Phase 3 comparisons. The >= 500 Cell/>= 10,000
  epoch Phase 2 acceptance benchmark itself remains documented but not yet run to completion
  (ADR-076).
