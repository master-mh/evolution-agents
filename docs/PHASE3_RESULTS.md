# Phase 3 results — the flight simulator's selection machinery

**Scope, first (§7.4).** The mock Cells' trait→performance mapping is authored by us. These results say
whether the **selection machinery** turns a signal the simulator plants into a measurable effect. They
say nothing about whether LLM-driven Cells will evolve useful businesses.

Pre-registration: [`docs/PHASE3_PREREGISTRATION.md`](PHASE3_PREREGISTRATION.md), committed in 9bb866c
before the run. Retained artifact: [`docs/benchmarks/phase3-confirmatory/`](benchmarks/phase3-confirmatory/)
(`batch.json` and 224 manifests, 6.2 MB). Analysis: exactly the declared metric, direction and interval
per hypothesis. Anything computed after the results were seen is marked **post hoc** and changes no
verdict.

## Headline

**The soft gate's selection item is not met.** In the one pre-registered suite, `staged_funding` did not
beat `random_eligible` on second-half revenue per concluded experiment (H1; point estimate −2.86, interval
includes zero). The lineage cap measurably bounds founder share (H4). H2 and H5 are supported as
registered, but two post hoc checks show neither is evidence that selection on revenue did anything: H2's
diversity gain is headcount, and H5's price response appears as strongly without revenue-ranked selection.
§28 lets Phase 4 proceed; deeper validation is Phase 3's parallel track.

## Integrity

- 224/224 runs completed, every one at code version `9bb866c` (the pre-registration commit, clean tree)
  and simulation policy version `"2"`; seeds 1001–1032; arm settings exactly as registered
  (`batch.json`'s `arm_settings`).
- No run recorded a failure; no run reached `max_active_cells`; conservation held in every book of every
  run; USD_REAL never moved.
- Every hypothesis was evaluable (no empty window).
- Wall time 3,090 s on 8 workers — the pre-registration's estimate of "about half an hour" was low.
- The batch was run once. No seed was added, removed or rerun.

## Verdicts

| | Comparison (treatment − baseline) | Metric | Declared interval | Mean | Declared 95% CI | Result |
|---|---|---|---|---|---|---|
| **H1** | `staged_funding − random_eligible` | second-half revenue / concluded experiment | unpaired | −2.86 | [−6.59, +0.83] | **not supported** |
| H2 | `map_elites − single_leaderboard` | final distinct genomes | paired | +7.84 | [+4.06, +11.56] | supported |
| H3 | `staged_funding − map_elites` | second-half revenue / concluded experiment | unpaired | −2.26 | [−6.15, +1.55] | not supported |
| H4 | `uncapped − staged_funding` | peak founder concentration | unpaired | +0.117 | [+0.083, +0.151] | supported |
| H5 | `staged_funding − static` | final mean price | paired | −8.36 | [−11.44, −5.26] | supported |
| H5-ref | `random_eligible − random_static` | final mean price | (descriptive) | −6.40 | paired [−9.36, −3.54] | — |

**No verdict depends on the paired/unpaired choice.** The confirmatory variance ratios differ from the
pilot's (H1's is now 0.73, H2's 1.02), but H1's and H3's paired intervals also include zero
([−6.00, +0.28], [−4.80, +0.40]), and H2's, H4's and H5's other intervals also exclude it.

## The soft gate

| §28 Phase 3 gate item | Result |
|---|---|
| A selection effect in ≥1 pre-registered scenario suite, CI excluding zero | **Not met** (H1) |
| Diversity persists | Met as registered: ≥25 distinct genomes at the end of every run of every arm; H2 supported — but see the post hoc check below |
| Regime adaptation occurs | Met as registered (H5), as a colony-level price response — not attributable to revenue-ranked selection (post hoc) |
| Reciprocal-credit attacks fail | **Untested** (declared) |
| Founder luck is bounded | Met: peak founder share ≤ 0.200 in every capped `staged_funding` run; H4 supported |
| *(§28's list)* shared knowledge vs isolated cohorts | **Untested** (declared) |

## Post hoc checks (not pre-registered; they change no verdict)

1. **H5 beyond the reference.** Per seed, `(staged_funding − static) − (random_eligible − random_static)`
   on final mean price: mean −1.96, paired 95% CI [−6.24, +2.38]. The shifting market lowers the
   population's price about as much under `random_eligible` as under `staged_funding`, so this design
   cannot attribute the response to revenue-ranked selection. `random_eligible` is not a null control:
   a child is born with 100 USD_SIM and may reproduce only at 150, so it too reproduces only Cells that
   have sold.
2. **H2 per living Cell.** Final distinct genomes divided by living Cells (20 founders + births):
   `map_elites` 0.878, `single_leaderboard` 0.910; difference −0.032, paired 95% CI [−0.052, −0.013].
   MAP-Elites ended with more distinct genomes because it bred more Cells (33.0 births against 22.5), and
   with slightly *less* diversity per Cell.

## What the machinery did — descriptive, per arm (means over 32 seeds)

| Arm | Births | Second-half revenue / concluded experiment | Final mean price |
|---|---|---|---|
| `random_eligible` | 59.2 | 31.79 | 439.09 |
| `random_static` | 59.0 | 266.67 | 445.48 |
| `single_leaderboard` | 22.5 | 31.09 | 438.72 |
| `map_elites` | 33.0 | 31.19 | 438.75 |
| `staged_funding` | 14.7 | 28.93 | 441.12 |
| `static` (`staged_funding`, no shift) | 27.3 | 267.64 | 449.48 |
| `uncapped` (`staged_funding`, cap 1.0) | 22.1 | 31.99 | 434.58 |

Post-shift, the price that maximises expected revenue per attempt is about 225. Every arm ended near 440,
between the founders' 400–500 and nowhere near it.

## Reading it

What this establishes, and what it only suggests:

- **Established:** in this simulator at this scale, none of the selection policies turned the planted
  price signal into a detectable revenue advantage over reproducing eligible Cells at random. The lineage
  cap does what §9.4 asks of it. A shifting market moves the population's price, whatever the policy.
- **Suggested, untested** — candidate reasons for the parallel track, not findings:
  - *Selection arms get few draws.* The default cap (0.2) refuses most concentrated births —
    `staged_funding` bred 14.7 Cells to `random_eligible`'s 59.2 — and a birth changes price only when the
    pricing operator is drawn (1 in 7). Fewer births means fewer chances to find a better price.
  - *Fitness is anchored on the old regime.* The policies rank on cumulative revenue, which keeps favouring
    Cells that sold at pre-shift prices.
  - *The control selects too.* Eligibility requires a child to have sold, so `random_eligible` is weak
    selection on sales, not random reproduction.
  - *Nothing dies.* Founders stay in every population mean, and in the slot rotation, for the whole run.
  - *The planted signal is weak before the shift.* Expected revenue per attempt at 400, 450 and 500 is
    280, 270 and 250.

## `simulate-compare`, verbatim

Run from the repository root against the retained artifact. The bootstrap is seeded, so rerunning any
command reproduces its output exactly.

```text
$ mitosis simulate-compare --dir docs/benchmarks/phase3-confirmatory --baseline random_eligible --treatment staged_funding --metric second_half_revenue_per_concluded_experiment
second_half_revenue_per_concluded_experiment: staged_funding - random_eligible over 32 paired seed(s)
  mean difference      -2.8582
  paired 95% CI       [-5.9988, +0.2804]
  unpaired 95% CI     [-6.5933, +0.8305]
  seed correlation     +0.274
  variance ratio       0.732  (<1: pairing narrowed the interval)

$ mitosis simulate-compare --dir docs/benchmarks/phase3-confirmatory --baseline single_leaderboard --treatment map_elites --metric final_distinct_genomes
final_distinct_genomes: map_elites - single_leaderboard over 32 paired seed(s)
  mean difference      +7.8438
  paired 95% CI       [+4.0625, +11.5625]  (excludes 0)
  unpaired 95% CI     [+4.0625, +11.5625]
  seed correlation     -0.020
  variance ratio       1.019  (<1: pairing narrowed the interval)

$ mitosis simulate-compare --dir docs/benchmarks/phase3-confirmatory --baseline map_elites --treatment staged_funding --metric second_half_revenue_per_concluded_experiment
second_half_revenue_per_concluded_experiment: staged_funding - map_elites over 32 paired seed(s)
  mean difference      -2.2595
  paired 95% CI       [-4.8015, +0.3978]
  unpaired 95% CI     [-6.1498, +1.5540]
  seed correlation     +0.541
  variance ratio       0.461  (<1: pairing narrowed the interval)

$ mitosis simulate-compare --dir docs/benchmarks/phase3-confirmatory --baseline staged_funding --treatment uncapped --metric peak_founder_concentration
peak_founder_concentration: uncapped - staged_funding over 32 paired seed(s)
  mean difference      +0.1168
  paired 95% CI       [+0.0862, +0.1480]  (excludes 0)
  unpaired 95% CI     [+0.0828, +0.1507]
  seed correlation     +0.552
  variance ratio       0.870  (<1: pairing narrowed the interval)

$ mitosis simulate-compare --dir docs/benchmarks/phase3-confirmatory --baseline static --treatment staged_funding --metric final_mean_price_minor_units
final_mean_price_minor_units: staged_funding - static over 32 paired seed(s)
  mean difference      -8.3588
  paired 95% CI       [-11.4418, -5.2561]  (excludes 0)
  unpaired 95% CI     [-13.9613, -2.6500]
  seed correlation     +0.688
  variance ratio       0.314  (<1: pairing narrowed the interval)

$ mitosis simulate-compare --dir docs/benchmarks/phase3-confirmatory --baseline random_static --treatment random_eligible --metric final_mean_price_minor_units
final_mean_price_minor_units: random_eligible - random_static over 32 paired seed(s)
  mean difference      -6.3962
  paired 95% CI       [-9.3563, -3.5408]  (excludes 0)
  unpaired 95% CI     [-10.4843, -2.4978]
  seed correlation     +0.477
  variance ratio       0.527  (<1: pairing narrowed the interval)
```

## For transparency: the design pilot (seeds 1–8; not evidence)

Used only for runtime, saturation and the paired/unpaired choice, and recorded here so its effects can
be compared with the confirmatory ones rather than remembered selectively. Its manifests name `ee79495` as
their code version although they ran the ADR-094/095 working tree later committed as 3256737 — a run
records HEAD, not a modified tree (logged in FUTURE_BUILD_HOOKS.md).

| | Pilot mean difference | Pilot declared 95% CI | Confirmatory |
|---|---|---|---|
| H1 | +0.75 | unpaired [−4.56, +6.12] | −2.86, includes zero |
| H2 | +10.63 | paired [+5.00, +16.50] | +7.84, excludes zero |
| H3 | +0.81 | unpaired [−5.30, +6.56] | −2.26, includes zero |
| H4 | +0.114 | unpaired [+0.060, +0.175] | +0.117, excludes zero |
| H5 | −6.95 | paired [−12.26, −1.13] | −8.36, excludes zero |

## Not tested (declared before the run)

- **Shared knowledge vs isolated cohorts (§22.1).** A mock Cell decides from its genome alone; nothing in
  `simulation/policy.py` reads anything another Cell wrote.
- **Reciprocal-credit attacks fail.** The simulator has no evidence-credit system (§11).
- **The rule-based market family.** Cross-family validation deadlocks `staged_funding` (ADR-083), and no
  mutation operator sets the flags its standard and premium bands require.
