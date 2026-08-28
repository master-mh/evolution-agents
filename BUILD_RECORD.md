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
§13.2's selector, §12's novelty archive, the inbound counterparty key, and
§12.1's declared third dimension,
2026-07-21 through 2026-08-28):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-28 — Rung 8 is a scale step, and the claim that it removed a human had spread to four files

Migration 0030 + `autopromotion.py` + two injected seams + 18 tests + `auto-promote` +
golden expectations **32 -> 33** (ADR-063). **§25.1's ladder issues rung 8, and §12.3's stage
conversions are unblocked.**

### The build began by disproving its own brief

`promotion.py`, `outcome.py`, migration 0016's comment and — worst — the docstring of the
structural test enforcing the guarantee all said rung 8 "means removing one of the two humans".
§25.1 reads `7. Tiny capped live experiment` -> `8. Expanded pilot` -> `9. Bounded autonomy`: the
7 -> 8 delta is **scale**, and *autonomy* appears only at rung 9. `test_outcome.py` contradicted
its own docstring three lines below it, and the forbidden list was the half that was right ("a
promotion that fires on a timer is rung 9, not rung 8").

Left uncorrected, rung 8 and the autonomy flag would have become the same number.

### Two axes, kept apart by construction

`rung` says how far up §25.1 the money climbed; `decided_automatically` says whether a person was
in the loop. `ISSUABLE_RUNGS` is `(7, 8)` — rung 9 is excluded on purpose, because bounded autonomy
is a different decider, not a bigger cheque.

### The constraint went in the schema (ADR-047)

Migration 0030's trigger makes three things unrepresentable rather than refused: a rung above 7
with no predecessor, a predecessor that is not the rung immediately below, and a predecessor
belonging to **another Cell** — §29's reciprocal evidence farming as a foreign key pointing
somewhere plausible. A unique partial index makes one success expandable exactly once (§23.4's
splitting attack, run upward).

### Two seams, because both directions were blocked

`outcome` imports `promotion`, so the §25.2 gate is `promotion.PromotionEvidence` — and its
signature takes a **`promotion_id`, never a `cell_id`**, so it cannot be asked "how is this Cell
doing?" (§9.3's move applied to evidence). `promotion` imports `scheduler`, so the unattended
engine reaches the tick as `scheduler.PromotionSweeper`, supplied by the *caller*.

### The engine invents no new guard

`autopromotion.py` composes §27.1's `auto_promotion` flag (ships false), §27.1's `real_spending`
(still separately required for USD_REAL, so ADR-026's two confirmations stay two), §23.1's own
`batchable` predicate, the §25.2 evidence gate and the `promotion_pool` ceiling. It **cannot kill**:
§10.5 forbids culling on an estimate with no concurring Auditor, so `death`/`displacement`/`lineage`
are closed structurally at the one module that acts on a verdict.

### Verification

- **Teeth-checked twelve ways; eleven caught first time.** The twelfth was a test passing for the
  wrong reason — dropping the unique index left every test green, because the Python query declines
  to *find* an expanded predecessor. It now has a constraint-level test that reports `DID NOT RAISE`
  when the index goes.
- **1110 tests and the golden run green.** The golden diff is **one added key** —
  `autonomy.auto_promotion: false` — with balances identical in every account in every book. The
  scenario never turns it on; the mechanism ships complete and switched off.
- Next: §12.3's beta-binomial stage-conversion posteriors are now buildable — rung-7 promotions that
  converted to rung 8 are the binary they need. The Auditor path for §13.3/§13.4's content judgments
  remains the clearly-scoped other half.
