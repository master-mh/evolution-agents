# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, the experiment, experiment attribution,
proposed experiments, the strategy kind decided, and the experiment_id foreign keys,
2026-07-21 through 2026-08-25):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-25 — The denominator that had been sitting in `promotions` since ADR-029

`experiments.stage_tranche` + three fields on §2.6's report + one CLI line (ADR-048).
**No migration.** `normalised_cost = expected experiment cost / current stage tranche` is one line of
SPEC.md, and **"tranche" appears exactly once in the whole document** — named, never defined, the
same shape the experiment itself was in before ADR-043. §10.5 names the object from the other side:
"stage budget exhausted" is a death criterion.

### The measurement came first, and it cleared the gate

FUTURE_BUILD_HOOKS had set a precondition: the numerator was `0` on every proposal from both models
on 2026-08-06, so nothing should be built on the ratio until it was re-measured. Eight live
`llama3.2` wakes against a colony with a running experiment returned **10000, 1000 and 0** — no
longer identically zero. The likely cause is ADR-044's own consequence: §15.1 now shows a Cell the
*derived* cost of its current experiment, which is the reference ADR-043 said models were missing.

### The denominator needed no building

`promotions.allocated_minor_units` has been, since ADR-029 and in its own column comment, "the amount
the operator approved and **not** a figure re-read from the Cell at allocation time" — per Cell, per
rung, human-ratified. That is a stage tranche in every respect §13.1 needs. **Thirteenth socket that
turned out to already exist.**

### The golden run caught the design error, and ADR-043 had predicted it

The first draft keyed the tranche on `experiments.ladder_rung`. ADR-043 had argued against exactly
that a slice earlier, citing §13.1 itself — the formula "would be circular if the stage belonged to
the experiment". The scenario is unusually good at exposing it: its rung-7 promotion and its rung-7
experiment belong to **different Cells**, so the circular reading returns `None` for all three rows
and looks merely conservative. The correct Cell-keyed reading reports a rung-7 tranche against a
rung-1 experiment, so `stage_tranche_rung` is pinned beside the ratio — from the ratio alone the two
readings are indistinguishable.

### Reported, never gated

§13.2 puts experiment cost on a Pareto frontier and says "Do not rely on a single weighted scalar";
§10.2 forbids the same collapse for fitness. A ratio above 1 prints "a claim to weigh, not a rule
that was broken". §10.5's "stage budget exhausted" *could* now consume this and deliberately does
not — that would make the ratio lethal, and it needs its own argument with an Auditor in it.
`death.py`'s docstring claimed stages "do not exist"; it has been corrected.

**One claim stated carefully because the stronger version is false:** `promotion.allocate` reads
`amount = proposal["estimated_cost_minor_units"]`, so the tranche starts as a number the *Cell* wrote.
A Cell can raise its own denominator — by asking for more and being given it, which is §23's gate
working. The asymmetry worth reading is **unreviewed versus ratified**, not Cell versus colony.

### Verification

- **988 tests passing** (8 new, 0 removed; up from 980). **Golden expectation 23 → 24**, one section
  (`experiments`, three keys per row), **`balances` identical in every account in every book** — this
  slice reads existing rows and writes none.
- **Teeth-checked seven ways, no misses**: the tranche keyed on the experiment's rung (the real bug —
  and it fails the golden run too, which is what the migration note claims), `0.0` instead of `None`,
  summing every promotion, the earliest instead of the latest, the ratio inverted, the abstention
  losing its stated reason, and `stage_tranche` regrowing a rung parameter.
- **One existing test was quietly brittle and is fixed**: `test_an_unmeasurable_dimension_...`
  asserted `len(report.unmeasured) == 1`, which made "a second dimension honestly abstained"
  indistinguishable from "the sandbox note was lost". It now asserts the sandbox note.
- **Hand-verified live** on both branches: an unpromoted Cell prints the abstention in words, and a
  promoted one prints `0.00x (0 estimated / 30 allotted at the Cell's current stage, rung 7)` and
  `8.33x` with the over-tranche line.
- **Found and NOT fixed — logged as the new top `Next` item.** Live proposal parse compliance has
  **collapsed from 7/8 (2026-08-06) to 1/8**. Five of seven failures are the model *flattening a
  nested payload* — `hypothesis` at the top level instead of inside `experiment`. Same class as the
  enum bug fixed on 2026-08-06: a value rendered in a shape that reads as a different type, since
  `_prompt_schema` renders each payload as a long English string. The mock provider structurally
  cannot catch it, so the suite and the golden run stay green while a live Cell's proposals are
  discarded.
- Next: that parse regression. It gates every future measurement of anything a Cell proposes,
  including the numerator this slice just measured.
