# Retained simulation benchmark artifacts

The implementation brief's Phase 2 acceptance section: "if runtime makes 500x10,000 unsuitable for
ordinary CI, keep a small deterministic CI scenario, and a separately documented benchmark command
whose result artifact is retained." `tests/test_simulation.py::test_phase_2_ci_scale_acceptance_scenario`
is the CI scenario; this directory is where a benchmark's retained manifest lives, checked in rather
than left in a temp directory a later session cannot see.

## 2026-09-05-founding-fix-validation-p50-e200.json

Not the full acceptance run — a moderate-scale validation, run once `docs/DECISIONS.md`'s ADR-076
fixed a bug that blocked founding populations above SPEC.md §9.2's `max_births_per_epoch` (default
25, well under the brief's own >= 500 Cell acceptance target). Produced by:

```bash
mitosis --db /tmp/bench-small.db init
mitosis --db /tmp/bench-small.db simulate --seed 1 --epochs 200 --population 50 \
  --output docs/benchmarks/2026-09-05-founding-fix-validation-p50-e200.json
```

Result: 200/200 epochs completed, population 50 -> 100 (`max_active_cells`, stable carrying
capacity thereafter), conservation intact across all three books, zero real spend, zero failures,
diversity (`distinct_genomes`) tracked throughout, the scheduled regime shift fired exactly once at
epoch 10. Wall time: 23m47s (604s user + 480s system CPU) — roughly **0.14 epochs/sec** at this
scale, well below the first slice's own smaller population 20->70/50-epoch benchmark (~5.6
epochs/sec) once population reached the `max_active_cells` ceiling and stayed there. Extrapolating
this run's own rate to the brief's >= 10,000-epoch, >= 500-Cell acceptance scale — a run five times
larger, whose per-epoch cost is not expected to be lower — points to a **multi-hour, quite possibly
multi-day** run on this hardware, not a "leave it running over lunch" job.

This is the real evidence behind that estimate, not a guess: the fix itself is proven correct
(founding now clears a target above the birth-rate cap, `test_founding_a_population_above_the_
birth_rate_cap_does_not_raise`), and this artifact is the throughput data point the estimate is
built from. The brief's own literal >= 500 Cell/>= 10,000 epoch run is intentionally not attempted
in an interactive session on this basis — it belongs as an explicitly kicked-off, unattended,
long-running job, documented here so whoever runs it next knows what to expect and where its result
belongs.

## Running many runs at once: `simulate-batch` (ADR-084)

The acceptance benchmark above is one long run. Phase 3's comparisons are many short ones — every
arm at every seed — and they are embarrassingly parallel, so they run as separate processes, each
against its own in-memory colony:

```bash
mitosis simulate-batch --arms random_eligible,staged_funding --seeds 1-16 --epochs 200 --population 50 --out-dir docs/benchmarks/<date>-<name>
```

```bash
mitosis simulate-compare --dir docs/benchmarks/<date>-<name> --baseline random_eligible --treatment staged_funding --metric total_revenue_minor_units
```

**Why in memory.** Measured on this machine: a p=30/e=40 run took 17.6s against a file-backed WAL
colony (5.3s of it system CPU) and 9.1s in memory (0.03s). The 480s of system CPU in the p=50/e=200
run above is the same effect at larger scale. A batch run keeps its manifests and `batch.json`, never
a database.

**Read the variance ratio, not just the interval.** `simulate-compare` reports the across-seed
correlation of the two arms and `Var(d)/(Var(a)+Var(b))`. Below 1, seed pairing narrowed the
interval; above 1, it widened it. A 3-arm × 8-seed pilot found 0.07 for total revenue and 1.29 for
peak founder concentration — the same batch, opposite answers — so a pre-registration should declare
the paired design per metric, not globally.
