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
measurement, §15.1 anchoring, the twins that
chose the fix, and the fix itself, 2026-07-21 through 2026-08-26):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-27 — An approved summary anchors exactly as hard

A measurement (ADR-053). **No code changed** — the remedy is the third design iteration on this
section and needs its own twins run first.

ADR-052 shipped `_was_decided` on a branch it had never measured: every arm behind it left every
proposal `pending`, because an unattended colony queues and nobody reviews. Both the ADR and
`_was_decided`'s docstring said so and named this as the result that would move the line. It does.

Approving does more than reveal a summary — it sets a standing strategy, issues grants, changes what
§15 assembles. So three arms, `llama3.2` t=0.8, 4 runs × 8 wakes:

| arm | approvals | section | parsed | **ideas/run** |
|---|---|---|---|---|
| `decided_shown` | every proposal | 64 tok, summaries **present** | 13/32 | **1.122** |
| `decided_hidden` | every proposal | 35 tok, summaries withheld | 14/32 | **1.764** |
| `pending` (shipped default) | none | 21 tok, summaries withheld | 18/32 | **2.195** |

`decided_shown` vs `decided_hidden` holds every approval side-effect constant and varies only whether
the summary renders. **`decided_hidden` is higher in 100% of 16 pairwise comparisons.**

### Approval makes no difference to anchoring

`decided_shown` scores **1.122** — the original pre-ADR-052 control was **1.089**. The anchoring
returns in full the moment the summary is visible, approved or not. **A Cell copies text it can see;
the annotation beside that text is not what it is reading.** So ADR-046 and diversity are in genuine
conflict on the branch that shipped, and the current rule is safe only in a colony nobody reviews.

### ADR-052's reason for showing it was wrong, and that is the way out

The reasoning was "APPROVED is meaningless if the Cell cannot tell *what* was approved." An approved
strategy in fact reaches the Cell through **two** sections — the proposal log and `Your standing
strategy (your words, approved by a person — this is how you operate)`, a dedicated independent
channel. **ADR-046's delivery for `STRATEGY` never ran through the proposal log**, so the summary
there is redundant for the one kind ADR-046 is about. Likely the same for the others — an approved
experiment reaches the Cell through the current-experiment section, a tool through its grant — but
that is inferred, not measured.

### Verification

- **Instrument checked before the numbers counted**: 13 and 14 approvals against 0, run-0 statuses
  all `approved` against all `pending`, section medians **64 / 35 / 21 tokens** confirming summaries
  present, withheld, withheld. (35 > 21 because an approved entry's decision note is longer.)
- **The confounded comparison is reported and not used.** `pending` vs `decided_shown` shows the
  right direction and attributes it wrongly; `decided_hidden` is the arm that isolates the summary.
- **A second finding, separate:** `decided_hidden` (1.764) scores below `pending` (2.195), so
  approval itself costs diversity through its other effects — a standing strategy is a strong
  instruction and the Cell follows it. Not obviously a fault.
- **1009 tests and the golden run green** — untouched, which is the point: this is a live-only
  property and no replay can see it.
- Next: verify each kind's approval still reaches the Cell with the proposal-log summary gone
  (`STRATEGY` is confirmed; experiment, tool and external-action are inferred), then a twins run on
  hiding it unconditionally. **Not shipped on this measurement alone** — §14.2 caught ADR-052
  reasoning instead of measuring once already.
