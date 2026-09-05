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
