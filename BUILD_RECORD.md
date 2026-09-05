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
auto-promotion reaching the scheduled `tick`, the flight simulator's first
slice (mock Cells deciding through the real deliberation pipeline), its
second (a second market family, environment separation, regime shifts), its
third (the remaining mutation operators, wired through a real choice), its
fourth (chaos drills as repeatable scenarios), and its fifth (manifest
richness, a CI-scale acceptance test, a founding cap bug fix, and a retained
benchmark artifact),
2026-07-21 through 2026-09-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-05 — Closing the evolutionary decision loop, part 0: a run record that never named its own selection policy, and founder concentration as a real time series (Slice G, part 0)

A plan was written first, given the genuine architectural forks Slice G surfaces (a full Explore
pass over `selection.py`/`novelty.py`/`posteriors.py`/`autopromotion.py`, then a Plan pass to
resolve them) — `docs/DECISIONS.md`'s ADR-077 is the as-built record for this first sub-slice; the
plan file itself sequences the remaining six.

### The central finding the whole plan turns on

The kernel's own fitness dimensions would be uniformly degenerate if reused verbatim on simulated
Cells: `SimulationPolicyProvider._propose()` hardcodes `estimated_cost_minor_units: 0` and
`predictions: []` on every call, killing `evidence_quality`/`information_gain`/`experiment_cost`
permanently; no content audit or counterparty-keyed revenue is ever produced either, killing
`software_native_advantage` and two of `novelty.py`'s three dimensions. Only genome-content-based
`novelty_distance` survives contact with the simulator unchanged. The plan therefore builds a
simulator-native dimension set from data the simulator actually produces — reusing the kernel's
*shapes* (the `dominates()` rule, the niche-coordinate pattern) by direct call where the underlying
function is genuinely genome-content-only, and building new, honestly-named logic everywhere else.

### What shipped in this first, smallest sub-slice

- **The bug**: `runner._record_run_start` has taken a `selection: SelectionPolicy` parameter since
  F1 but never read `.name`/`.version` from it — both `simulation_runs` and the manifest recorded
  the *Cell* policy's identity in the selection-policy fields too. For a slice whose entire purpose
  is comparing selection policies, nothing at the run level could say which one a run used except a
  per-epoch audit event. Fixed with two new nullable columns (migration 0036, no rebuild needed) and
  `_record_run_start` finally using its own parameter.
- **Founder concentration**, joining `distinct_genomes` as a real per-epoch time series: new
  `lineage.founder_concentration()`, one `GROUP BY` over the already-denormalized
  `cells.founder_cell_id`. Comparable across policies over time, which a free-text reason inside one
  policy could never give.

### A teeth-check that initially passed for the wrong reason

The first attempt at proving `founder_concentration`'s ordering mattered removed `ORDER BY n DESC`
entirely — this happened to still name the right founder, purely because that run's random ids
coincidentally sorted it first. Flipping `DESC` to `ASC` instead picks the *smallest* count
deterministically, which can never be the dominant lineage — confirmed to fail across three
independent runs with fresh random ids each time, not just once, before trusting it.

### Verification

5 new tests (50 total): the run-record fix (a minimal name/version-only policy wrapper, since no
second real policy exists yet); `founder_concentration`'s correctness on a ten-founder fixture (the
same `max_lineage_population_fraction` reason population is raised to ten elsewhere in this file);
founder concentration as a real bounded time series. Two teeth-checks (the second needing the
do-over above), both confirmed to fail for the stated reason and restored verbatim. Full suite
green; golden run unaffected (hash unchanged at 38); `ruff check .` and
`scripts/check_docs_facts.py` both clean (README's migration count updated 35 -> 36).

- Next: G1 — `candidate.py`'s simulator-native gates/axes/`dominates()`, the full
  `SelectionDecision` schema expansion, and `posteriors.sample()`, per the approved Slice G plan
  (G2 `SingleLeaderboardSelection`, G3 `ParetoSelection`, G4 `MapElitesSelection`, G5
  `StagedFundingSelection` + Thompson sampling + the `EnvironmentSuite.validation` consumer, G6 the
  cross-policy acceptance harness) — then Slice H's pre-registered Phase 3 comparisons. The >= 500
  Cell/>= 10,000 epoch Phase 2 acceptance benchmark itself remains documented but not yet run to
  completion (ADR-076).
