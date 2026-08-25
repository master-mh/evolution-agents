# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, the experiment, experiment attribution,
proposed experiments, and the strategy kind decided, 2026-07-21 through 2026-08-26):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-25 — The seam four files scheduled, and the constraint that made it unnecessary

Migration 0027 + `db.raise_for_unknown_experiment` + two `except` clauses (ADR-047).
`PRIORITIES.md`, `FUTURE_BUILD_HOOKS.md` and ADR-044 all scheduled the same next slice — an
injected `ExperimentChecker` seam, `sweeper.ExternalOperationChecker`-shaped, because
`reservations`, `prediction`, `ledger` and `gateway` sit *below* `experiments` in the layering.
**The premise is true and the conclusion was wrong: the layering objection is an objection to a
*Python* check, and a foreign key has no layer.**

### What was actually missing was a declaration, not a mechanism

All four `experiment_id` columns are bare `TEXT` for one reason each — every one predates the table
it names (`ledger_entries`/`reservations` 0001, `model_calls` 0010, `prediction_register` 0012;
`experiments` 0026). Migration 0026's own header had already said it: "**the foreign key was exposed
to the operator before the table existed**." Meanwhile `db.connect` has set
`PRAGMA foreign_keys = ON` since the beginning, so enforcement was switched on and waiting. SQLite
cannot `ALTER TABLE ADD CONSTRAINT`, so 0027 rebuilds the four tables; every copy is `ORDER BY
rowid`, because both hash chains read their rows in rowid order and the ledger folds each
transaction's entries into that transaction's hash — a reordered copy would read exactly like
tamper-evidence firing.

### The bug the design nearly shipped, found by a test that did the real thing

An **open** reservation carrying a dangling id would have had its funds committed *forever*.
`settle` and `release` write **new** ledger entries carrying the reservation's `experiment_id`, so
once the entry constraint existed every exit from that reservation wrote a row the key must refuse.
**A `PRAGMA`-level probe said the row was healthy** — a bare `UPDATE` of a non-key column on a
violating row is allowed, and that is what I checked first. Only a test that actually *released* one
found the hole. The migration now repairs that single case to NULL — the true value, since ADR-044
settled that unattributed is a result — and writes an `audit_events` row naming the id it cleared.
Terminal reservations and every ledger entry keep their dangling ids untouched: nothing will write
another entry for them, so the id is harmless evidence that a report had been undercounting, and
§3.6 keeps it. **Repair what is still live; preserve what is already history.**

### Verification

- **980 tests passing** (18 new, 0 removed; up from 962). **Golden expectation unchanged at 23** —
  hash byte-identical. A rebuild that preserves order changes no data, and the repair matches zero
  rows on a colony whose only internal source for the value is `experiments.attribution_for`.
- **The blast radius was zero, and that is the finding.** All 962 pre-existing tests passed against
  the new constraint without a single edit, because every internal caller already derives the id
  from `attribution_for`. The hole was never in what the kernel does today — it was in what the next
  programmatic caller would have been free to do, which is exactly what ADR-044 meant by "worth doing
  before anything else starts passing the id programmatically".
- **Teeth-checked twelve ways**, each failing its named test: the foreign key dropped from each of
  the four tables separately, the repair removed (the stranded-funds bug), the repair left
  unrecorded, the repair over-reaching to terminal rows, the rebuild copy losing rowid order (both
  chains break), the translator swallowing non-experiment `IntegrityError`s, and three more.
  **Two mutations initially MISSED and exposed a real gap**: the translator was never tested against
  a *different* foreign key failing on the same row — `prediction_register` and `model_calls` both
  reference `cells` too, and all of them fail with the identical eight words. Two tests added; both
  mutations then caught.
- **Hand-verified end to end on a live on-disk colony** (every test until then used `:memory:`):
  0027 applies under WAL, all four keys land, `foreign_key_check` is clean, an experiment starts, and
  revenue and a prediction attach to it while a ghost id is refused.
- Next: unchanged from the last entry — §13.1's `normalised_cost` still has no stage tranche to
  divide by. Note its numerator was measured at 0 on every proposal from both models on 2026-08-06,
  so the first step there is a re-measurement, not a migration.
