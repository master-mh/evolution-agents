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
decision loop's first three sub-slices (a run record that never named its
own selection policy and founder concentration as a real time series;
simulator-native fitness dimensions, the full decision-record schema, and
Thompson sampling; the single-leaderboard control policy),
2026-07-21 through 2026-09-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-05 — Closing the evolutionary decision loop, part 3: Pareto selection, reproducing the whole front (Slice G, part 3)

Continuing the plan from ADR-077 through ADR-079 without a fresh plan-mode round-trip. ADR-080 is
the full as-built record.

### What shipped

`ParetoSelection` (brief Slice G policy #3): gates every eligible Cell on
`not_quarantined`/`reproducibility`, takes the Pareto front over
`structural_novelty`/`realized_net_revenue`/`experiment_success_rate`, and reproduces from **every**
Cell on the front — not one winner. That last point is the whole content of the comparison this
policy sets up against `SingleLeaderboardSelection`: SPEC.md §10.2's "portfolio, not a scalar" only
means something if the portfolio is actually funded. Each front member draws its own mutation
operator via the per-parent override fields ADR-078 built but nothing had used yet.

### A gate found to be structurally unreachable through this pipeline

`candidate._not_quarantined` is correctly implemented and independently proven (ADR-078) — but every
policy builds its candidates only from `_eligible_parents()`'s own output, which already filters to
`CellStatus.ALIVE` before a gate ever runs. A quarantined Cell is excluded at the *eligibility*
stage, not the *gate* stage, so this gate's `REJECTED` branch cannot fire through any policy's
`decide()` regardless of colony state. Kept anyway — correct, cheap, and a module built for reuse by
`MapElitesSelection`/`StagedFundingSelection` next shouldn't assume every future caller pre-filters
the same way — but the first version of this slice's own test asserted a rejection that can never
happen here and failed; rewritten to assert the accurate, narrower fact instead.

### Verification

4 new tests (88 total in the simulation area): a genuine three-Cell trade-off fixture (higher revenue
but a lower success rate vs. lower revenue but a perfect one, with `structural_novelty` held tied via
identical genome content so only the two controlled axes discriminate) proving mutual
non-domination puts both on the front while a dominated third is excluded; the corrected quarantine
test; every chosen parent receiving its own operator; a CLI end-to-end run. Three teeth-checks, each
confirmed to fail for the stated reason and restored verbatim. Full suite green; golden run
unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: G4 — `MapElitesSelection`, giving `novelty.py`'s archive the elite-per-niche rule
  `candidate.niche_elite()` already built in G1 its first real caller — then G5
  (`StagedFundingSelection` + Thompson sampling + the `EnvironmentSuite.validation` consumer), G6
  (the cross-policy acceptance harness), and Slice H's pre-registered Phase 3 comparisons. The
  >= 500 Cell/>= 10,000 epoch Phase 2 acceptance benchmark itself remains documented but not yet run
  to completion (ADR-076).
