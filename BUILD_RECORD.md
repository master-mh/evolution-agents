# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, and the experiment,
2026-07-21 through 2026-08-24):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-25 — Attribution: the column everything asked for, and never needed

No migration. `experiments.attribution_for` + threading through `tools`, `external_actions` and
`deliberation` (ADR-044). The slice was scheduled as "add `resource_usage.experiment_id`" —
BUILD_RECORD said it, PRIORITIES said it, `golden.py`'s version-20 note said it, and
`experiments.py`'s own docstring said it. All four were wrong about the mechanism.

### The join was always there; the stamp was not

`resource_usage.reservation_id` is `NOT NULL REFERENCES reservations(reservation_id)` — Amendment
A6 requires precisely that — and `reservations.experiment_id` has existed since **migration 0001**.
Every metered row was one join from its experiment the whole time. What was missing was the stamp:
`gateway` threaded `experiment_id` into its reservations and `tools`, `external_actions` and
`deliberation` did not. Adding the column would have worked, and would have created a second answer
to a question the reservation already owns — a usage row stamped with one experiment hanging off a
reservation stamped with another, with nothing in the schema preferring either. That is §2.5's
cached-derivation trap reached from the metering side, so
`test_resource_usage_has_no_experiment_id_column` now refuses it the way
`test_there_is_no_experiment_results_table` refuses the other one.

### The visible bug was the abstention; the real one was the undercount

`human_minutes` reported `None` with a stated reason, which announces itself. **`resource_spend_
minor_units` — §2.6's shadow-cost line — reads the same reservations through the ledger and was
reporting a definite figure with every tool call and every human minute missing from it.** And
`deliberation` never named its experiment to the gateway at all, so §2.6's *real cash consumed* was
0 for any experiment whose Cell simply ran — the headline number on a paid provider, and the least
visible failure, because 0 is plausible for work that has not spent yet. An abstaining dimension is
loud. An undercounting one sits next to it looking identical.

### Derived, never supplied

§15.1 gives a Cell one current experiment, so which experiment bears a cost is already determined.
A parameter would be a place to put a *different* one — §0.3 reached from the expense side, since a
Cell that could name the experiment could make its own look cheap by naming another. So
`attribution_for` is the single seam, an `inspect.signature` test asserts no metering entry point
grows the parameter, and `None` stays a result rather than a gap. Two timing rules fell out:
external-action labour is stamped **at claim, not at completion** (a person may answer days later,
by which time the Cell may be on another experiment or dead), and a deliberation **resolves it once
and carries it** to both the gateway call and the predictions it registers, because ADR-022 puts
those on opposite sides of a transaction boundary.

### §1.1 wanted the number the obvious sum would have hidden

`external_actions` bills a Cell up to its channel ceiling and records the overflow as subsidy, so
`resource_usage.quantity` is the *billed* minutes. Summing it alone would report the colony's human
cost as **smaller the more of it a person absorbed unpaid** — the exact quantity §1.1 subtracts to
"expose hidden founder labour", hidden by the report built to expose it. The report carries
billed + subsidised, with the subsidy printed beside it.

### Verification

- **931 tests passing** (15 new, 0 removed; up from 916). **Golden expectation 20 → 21**, with
  **`balances` identical in every account in every book** and USD_REAL untouched — attribution
  decides which experiment a cost is *reported* under; it posts no entry. `human_minutes` moves
  `null → 0` on one experiment and `null → 58` on the other; the `0` is now a *measurement* rather
  than a decline. `resource_spend` `0 → 550`. Four deliberations gain 1–3 input tokens, all from
  one cause: §15's experiment section renders the RESOURCE figure to the Cell, which had always
  read `0`.
- **Teeth-checked twelve ways**, each failing its named test: both metering paths unstamped (the
  state before this slice), the wake unstamped, a Cell's forecasts back to `experiment_id=None`,
  human labour summing only billed minutes, the report abstaining again, attribution ignoring
  whether the experiment still runs, attribution read at completion instead of claim, the CLI
  accepting any string for `--experiment`, a metering entry point growing the parameter, the column
  being added, and the attribution re-derived instead of carried.
- **One test could not have failed and was rewritten.** "The call and its forecasts share one
  experiment" passes trivially on a quiet run — a re-derivation agrees too. It now uses a provider
  that concludes the experiment *while the call is in flight*, the only moment the two designs
  differ, and the mutation is caught.
- **Hand-verified end to end on a live colony**: experiment started, a wake deliberating under it,
  an approved external action claimed and completed at 47 human minutes against email's 30-minute
  ceiling — the report showing 2 model calls, 47 minutes with 17 subsidised, 304 RESOURCE, and the
  Cell's *own* auto-registered forecast in the reality gap. A bogus `--experiment` is refused.
- **The live run is what found the deliberation half.** The first report read "Model calls: 0" for
  a Cell that had just deliberated under the experiment, which no test was asking about.
- Next: `revenue.record_revenue` refuses a re-record that only adds an experiment (correct per
  idempotency), so an operator attributing revenue late needs §3.6's adjustment path — logged, not
  built. Kernel-internal validation of a dangling `experiment_id` needs a seam and is in
  FUTURE_BUILD_HOOKS.
