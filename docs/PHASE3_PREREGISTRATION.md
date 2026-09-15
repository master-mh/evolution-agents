# Phase 3 pre-registration — the flight simulator's selection machinery

**Declared 2026-09-15, before any confirmatory run.** SPEC.md §28 Phase 3 (Amendment A1): "Before
running, declare hypothesis, metric, and seed count." Everything below is fixed by the commit that adds
this file; the confirmatory batch is run from that commit, once, and analysed exactly as written.

## Scope (§7.4, stated first because every result inherits it)

The mock Cells' trait→performance mapping is authored by us. A result here says whether the **selection
machinery** turns a signal the simulator plants into a measurable effect. It says nothing about whether
LLM-driven Cells will evolve useful businesses. Every number reported from this design carries that
sentence.

## What was known before this was written

- **Exploratory runs, excluded from confirmation.** Seeds 1–2 (40 epochs, 7 arms) and a design pilot on
  seeds 1–8 (60 epochs, 7 arms) — both policy version 2. The design pilot was used for exactly three
  things: runtime, whether any arm saturates `max_active_cells`, and each metric's variance ratio (which
  decides paired vs unpaired intervals below). Its effect sizes are recorded in the results document for
  transparency and are not evidence. What it established for the design: no run of any arm reached
  `max_active_cells` or recorded a failure in 60 epochs; `staged_funding`'s founder share peaked at
  exactly 0.200 under the default cap; the H5-reference below is not zero at every seed (as the
  eligibility argument predicts); and 56 runs took 449 s on 8 workers, so the 224 confirmatory runs
  should take about half an hour.
- **The mechanism the simulator plants.** In `utility_maximizing_market` price is the only trait that
  matters: willingness to pay is `uniform(0.5, 1.5) × 500` before epoch 10 and `uniform(0.3, 0.9) × 500`
  from epoch 10, so expected revenue per attempt peaks near price 375 before the shift and near 225 after.
  Founders price 400/450/500. The pricing operator multiplies price by `uniform(0.7, 1.3)` and is drawn
  with probability 1/7 per birth.
- **Known structural limits** (FUTURE_BUILD_HOOKS.md): nothing dies, so founders stay in every
  population-trait mean; the default lineage cap (0.2) refuses most births under concentrating policies;
  selection policies rank on cumulative revenue.

## Fixed design

| | |
|---|---|
| Code | the commit adding this file (`simulation_runs.code_version`, every manifest's `code_version`) |
| Policy version | `simulation` policy `"2"` (ADR-095) |
| Training market | `utility_maximizing_market` |
| Validation market | `utility_maximizing_market` for `staged_funding` (ADR-083: cross-family validation deadlocks) |
| Founders | 20 |
| Epochs | 60 |
| Seeds | **1001–1032** (32) |
| Interval | two-sided 95% percentile bootstrap, 5,000 resamples, bootstrap seed 0 (`simulate-compare` defaults) |

### Arms (one batch)

```
random_eligible
random_static=random_eligible+static_market
single_leaderboard
map_elites
staged_funding
static=staged_funding+static_market
uncapped=staged_funding+lineage_cap=1.0
```

### The command, verbatim

```bash
mitosis simulate-batch --arms "random_eligible,random_static=random_eligible+static_market,single_leaderboard,map_elites,staged_funding,static=staged_funding+static_market,uncapped=staged_funding+lineage_cap=1.0" --seeds 1001-1032 --epochs 60 --population 20 --validation-environment utility_maximizing_market --out-dir docs/benchmarks/phase3-confirmatory
```

## Hypotheses

Each comparison names one metric; `treatment − baseline` per seed. "Supported" means the declared
interval excludes zero **in the stated direction**. An interval excluding zero in the other direction is
reported as an effect opposite to the hypothesis, never as support.

**H1 — selection vs random (primary; the only comparison the gate's "selection effect" reads).**
`staged_funding − random_eligible` on `second_half_revenue_per_concluded_experiment`. Direction: > 0.

**H2 — MAP-Elites vs single leaderboard.** `map_elites − single_leaderboard` on
`final_distinct_genomes`. Direction: > 0.

**H3 — staged vs flat funding.** `staged_funding − map_elites` on
`second_half_revenue_per_concluded_experiment`. Direction: > 0.

**H4 — lineage caps vs none.** `uncapped − staged_funding` on `peak_founder_concentration`.
Direction: > 0 (the cap bounds founder share).

**H5 — static vs shifting markets (regime adaptation).** `staged_funding − static` on
`final_mean_price_minor_units`. Direction: < 0 (a shifting market selects lower prices).
**H5-reference (descriptive, not a hypothesis):** `random_eligible − random_static` on the same metric,
reported beside H5. It is *not* a zero-difference control: a child is born with 100 USD_SIM and becomes
eligible to reproduce only at 150, so even `random_eligible` reads revenue through eligibility, and the
market's shift reaches its genomes that way. What the reference shows is how far the shift moves price
without selection on revenue; H5 is read against it, not instead of it. That the static setting changes
nothing but the market is defended structurally, not here:
`test_a_static_and_a_shifting_run_are_the_same_economy_until_the_shift` requires identical epoch records
before epoch 10.

H2–H5 are secondary. All five are reported; no multiplicity correction is applied, and none of H2–H5 is
read as satisfying the gate.

## Paired or unpaired, per metric (from the design pilot's variance ratios)

ADR-084 found pairing narrows some intervals and widens others, and ADR-095 found its ratios had been
measured on a stalled economy; so they were re-measured on the design pilot (seeds 1–8, this design,
policy version 2). **Rule:** a pilot variance ratio below 1 declares the paired interval; 1 or above
declares the unpaired one. `simulate-compare` prints both; only the declared one is read.

| | Metric | Pilot seed correlation | Pilot variance ratio | Declared interval |
|---|---|---|---|---|
| H1 | `second_half_revenue_per_concluded_experiment` | −0.32 | 1.32 | **unpaired** |
| H2 | `final_distinct_genomes` | +0.67 | 0.35 | **paired** |
| H3 | `second_half_revenue_per_concluded_experiment` | −0.03 | 1.03 | **unpaired** |
| H4 | `peak_founder_concentration` | −0.20 | 1.03 | **unpaired** |
| H5 | `final_mean_price_minor_units` | +0.62 | 0.40 | **paired** |

H3's and H4's ratios sit close to 1, where the two intervals nearly coincide; the rule is applied as
written rather than argued case by case.

## The soft gate, mapped

| §28 Phase 3 gate item | How it is read here |
|---|---|
| A selection effect in ≥1 pre-registered scenario suite, CI excluding zero | H1 supported |
| Diversity persists | `final_distinct_genomes` > 1 in every run of every arm, and H2 reported |
| Regime adaptation occurs | H5 supported, reported beside the H5-reference |
| Reciprocal-credit attacks fail | **Untested.** The simulator has no evidence-credit system (§11). Not approximated |
| Founder luck is bounded | `peak_founder_concentration` ≤ 0.20 in every `staged_funding` run (cap 0.2), and H4 supported |
| *(§28's comparison list)* shared knowledge vs isolated cohorts | **Untested.** A mock Cell decides from its genome alone; nothing in `simulation/policy.py` reads anything shared (§22.1). Not approximated |

## Rules fixed in advance

- **One run.** The batch is run once. No seed is added, removed or rerun after any result is seen.
- **Failures are results.** A run that records a failure makes every comparison reading its arm refuse
  (`paired.load_arm`); that comparison is reported as not evaluable, and its seed is not replaced.
- **An empty window is not a zero.** A metric that refuses (nothing concluded in the second half) makes
  its comparison not evaluable, reported as such.
- **Saturation is reported, not fixed.** If any run reaches `max_active_cells`, the epoch it did so is
  reported beside every comparison reading that arm.
- **Retained artifact:** the batch directory above, checked in whole — `batch.json` and all 224
  manifests (~26 KB each, ~6 MB), because `simulate-compare` reads manifests through the index and a
  reader must be able to rerun every comparison from the artifact alone — with a results document
  naming each `simulate-compare` invocation and its full printed output.
- **Timebox:** one session's confirmatory run and analysis. Deeper validation is Phase 3's parallel track.
