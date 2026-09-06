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
decision loop's first four sub-slices (a run record that never named its
own selection policy and founder concentration as a real time series;
simulator-native fitness dimensions, the full decision-record schema, and
Thompson sampling; the single-leaderboard control policy; Pareto selection
reproducing the whole front, and a gate found structurally unreachable
through this pipeline),
2026-07-21 through 2026-09-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-06 — Closing the evolutionary decision loop, part 4: MAP-Elites, one elite per occupied niche (Slice G, part 4)

Continuing the plan from ADR-077 through ADR-080 without a fresh plan-mode round-trip. ADR-081 is
the full as-built record.

### What shipped

`MapElitesSelection` (brief Slice G policy #4): calls `novelty.archive()` directly and, for every
occupied niche, calls `candidate.niche_elite()` (built in G1, its first real caller) — highest
`realized_net_revenue` among evaluated occupants, or a uniform-random pick among unevaluated ones.
Every occupied niche reproduces each epoch (classical MAP-Elites; budget-constrained prioritization
across niches is G5's job via Thompson sampling). Each niche's real §12.3 posterior is recorded on
its `NicheStanding` regardless of whether this policy reads it.

### A coincidental-pass test found and fixed before it shipped

The first version of the posterior-recording test asserted only that a niche with zero rung-7
promotions gets the uninformative Beta(1,1) prior — true, but numerically identical to what a
silently-broken posterior lookup falls back to (`_posterior`'s formula gives `alpha=beta=1.0` at
`trials=0` either way). Rewritten to inject a real, non-prior posterior via monkeypatch and assert
those exact values survive into the decision record, so a broken lookup now produces a visibly wrong
result. Same root cause as ADR-077/ADR-079's own coincidental-pass teeth-checks this slice: a
too-easy CAUGHT deserves a second look before being trusted.

### Verification

4 new tests (92 total in the simulation area). Three teeth-checks — the posterior lookup, the
eligibility threading into `candidate.niche_elite()`, the factory's dispatch branch — each confirmed
to fail for the stated reason and restored verbatim. Full suite green (1322 total); golden run
unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: G5 — `StagedFundingSelection`, composing `ParetoSelection`'s gates with this policy's
  niche/elite rule, a new `validation_probe` gate, and a Thompson-sampled draw per niche
  (`posteriors.sample()`, built in G1 but still uncalled) funding only the top-K sampled niches — then
  G6's cross-policy acceptance harness and Slice H's pre-registered Phase 3 comparisons. The
  >= 500 Cell/>= 10,000 epoch Phase 2 acceptance benchmark itself remains documented but not yet run
  to completion (ADR-076).
