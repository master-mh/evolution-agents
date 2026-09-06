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
decision loop's first five sub-slices (a run record that never named its
own selection policy and founder concentration as a real time series;
simulator-native fitness dimensions, the full decision-record schema, and
Thompson sampling; the single-leaderboard control policy; Pareto selection
reproducing the whole front, and a gate found structurally unreachable
through this pipeline; MAP-Elites, one elite per occupied niche),
2026-07-21 through 2026-09-06):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-06 — Closing the evolutionary decision loop, part 5: staged funding, the composed policy (Slice G, part 5)

Continuing the plan from ADR-077 through ADR-081 without a fresh plan-mode round-trip. ADR-082 is
the full as-built record.

### What shipped

`StagedFundingSelection` (brief Slice G policy #5, "the intended policy"): composes every earlier
sub-slice rather than adding a sixth mechanism. Gates every eligible Cell on `ParetoSelection`'s two
dimensions before a gate-survivor can be considered a niche elite; niches/elites come from
`MapElitesSelection`'s own rule, restricted to gate survivors; each niche gets one real
Thompson-sampled draw (`posteriors.sample()`, its first real caller), funding only the top 3 sampled
niches at a budget scaling with that niche's posterior mean. A new `candidate.validation_probe` gate
— `EnvironmentSuite.validation`'s first real consumer (ADR-073's own named obligation) — runs against
a niche's chosen elite only, injected via this policy's own constructor rather than a new `decide()`
parameter, so the routine epoch loop's existing "no path to `validation`" guarantee stays unmodified
for every policy. `cmd_simulate` defaults `--validation-environment` to the other market family from
`--environment` when `staged_funding` is chosen.

### A shared-constant edit that would have made `ParetoSelection` dishonest if left alone

Adding `validation_probe` to `candidate.SIM_GATE_DIMENSIONS` automatically flows into every
dynamically-derived `unmeasured_dimensions` tuple — correct everywhere except `ParetoSelection`,
whose measured-dimensions constant and `unmeasured_dimensions` were both hardcoded literals that
would have silently started claiming it measures a gate it never runs. Fixed by excluding
`validation_probe` explicitly in both places; `StagedFundingSelection`'s own `unmeasured_dimensions`
is derived rather than hardcoded, precisely so this doesn't recur for the next dimension added.

### Verification

7 new tests (99 total in the simulation area). Four teeth-checks — the validation-rejection filter,
the gate-survivor restriction into `niche_elite`, the top-K slice, the budget-scaling formula — each
confirmed to fail for the stated reason and restored verbatim. Full suite green (1329 total; one
unrelated Hypothesis deadline flake on `test_charter_ledger_balanced` reproduced as a clean pass in
isolation and on a full re-run); golden run unaffected (hash unchanged at 38); `ruff check .` and
`scripts/check_docs_facts.py` both clean. Documented honestly: the archive can have at most 3 niches
today (only `structural_novelty` ever measures for a simulated genome), so the top-K=3 cap cannot yet
exclude anything in a real run — its ranking-and-cap logic is still verified by monkeypatching the
constant down to 1 in a dedicated test.

- Next: G6 — the cross-policy acceptance harness (same seed bundle run once with
  `RandomEligibleSelection` and once with `StagedFundingSelection`; a reproduction-traceability test;
  the validation-isolation regression guard re-run unmodified) — then Slice H's pre-registered
  Phase 3 comparisons. The >= 500 Cell/>= 10,000 epoch Phase 2 acceptance benchmark itself remains
  documented but not yet run to completion (ADR-076).
