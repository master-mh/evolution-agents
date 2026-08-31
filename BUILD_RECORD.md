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
§12.1's declared third dimension, and rung 8,
2026-07-21 through 2026-08-28):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-31 — §12.3's `P(next stage)` counts a realised conversion, never a verdict

`posteriors.py` + `mitosis posteriors` + 9 tests + golden expectations **33 -> 34** (ADR-064).
**§12.3's beta-binomial Thompson-sampling target ships: one posterior per §12 niche, built from
rung-7 -> rung-8 conversions.**

### The decision was which signal counts as a trial, not the arithmetic

`outcome.py` already computes a verdict — `SUPPORTS_PROMOTION` — for whether a rung-7 promotion's
own evidence would earn an expansion. It is available, binary, and the wrong thing to count. §10.5's
discipline (decide on realised facts, not estimates) generalises from one Cell to a niche of them: a
niche's conversion rate is about Cells that actually climbed the ladder, not about promotions the
kernel currently believes could. A Cell can earn `SUPPORTS_PROMOTION` and never be allocated rung 8 —
an operator can simply not act — and that is not evidence about the niche. The trial is a raw join on
`promotions.supersedes_promotion_id`, the realised fact ADR-063 made representable, computed without
ever calling into `outcome.py`.

### The niche is `novelty.archive`'s coordinate, and an empty one still gets a posterior

A rung-7 promotion is attributed to the §12.1 niche of the Cell's genome; genomes that abstain on
every dimension are counted separately (`unbinned_trials`/`unbinned_conversions`) rather than
dropped, matching `Archive.unbinned_genome_hashes`. **A niche with zero rung-7 promotions still
reports Beta(1, 1)**, not an abstention — the one dimension in this codebase where withholding would
be the less honest choice, because Thompson sampling needs every niche, funded or not, to have a
distribution it can be drawn from.

### No table

Derived on every read, same posture as `novelty.py` and `selection.py` toward §2.5/§12.2. This also
answers §12.3's own future-proofing clause for free: "schemas must allow hierarchical/non-stationary
models later" is automatic when the module owns no schema — a richer model is a different function
body over the same rows, never a migration.

### Guarded the same way `selection.py`'s frontier is

`test_no_kernel_path_acts_on_a_posterior` closes `death.py`, `promotion.py`, `displacement.py` and
`scheduler.py`; `test_the_posterior_never_reaches_a_cell` closes `context.py` and `deliberation.py`
(§23.5). §10.5's "estimated negative EV" shape, generalised from a Cell to a niche of them.

### Verification

- **9 new tests; teeth-checked two ways.** Conflating "converted" with "always true" (the tempting
  `outcome.assess` shortcut) failed four tests, including the one written to catch exactly it. A
  forbidden import into `death.py` was caught by the AST guard; the same mutation into `promotion.py`
  failed even earlier, at import time, with a circular-import error — `posteriors` already imports
  `promotion` for its rung constants, which makes that back-edge structurally impossible rather than
  merely refused.
- **1119 tests and the golden run green.** The golden diff is **one added section**,
  `stage_conversion_posteriors` — three niches, the scenario's one rung-7 promotion sitting at
  `trials: 1, conversions: 0`, the other two niches reporting the bare Beta(1, 1) prior. No balance,
  transaction, or existing row moved.
- Next: the Auditor path for §13.3/§13.4's content judgments is the other half ADR-062 scoped and
  clearly left open. §12.3's remaining four posteriors (expected net value, expected time to
  conversion, probability of reproducibility, probability of large loss) stay logged in
  FUTURE_BUILD_HOOKS — each needs machinery this colony does not have yet (§11.2's adoption record,
  a liability model, a survival-style time-to-event model).
