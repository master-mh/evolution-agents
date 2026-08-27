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

## 2026-08-27 — A human decision wakes the Cell it was about

`approval._wake_on_human_decision_locked` + 6 tests + golden expectation **27 -> 28** (ADR-057).
No migration.

ADR-055 queued "wire real events to the wake reasons they justify". **Auditing that found a smaller
and more specific gap than the ADR had claimed, and corrected the ADR's own target.**

### Six of seven reasons were already earned

`WAKE_TOOL_RESULT` by `tools.py`, `WAKE_CAPITAL_ALLOCATION` by `promotion.py`, `WAKE_AUDIT_REQUEST`
by `auditor.py`, `WAKE_EXTERNAL_ACTION_RESULT` by `external_actions.py`, `WAKE_APPROVAL_EXPIRED` and
`WAKE_GRANT_EXPIRED` by the sweep. **ADR-055's "only the scheduler's tick is hardcoded" was wrong
twice:** the tick is *honest* — a scheduled tick genuinely is a scheduled research cycle — and the
real gap was elsewhere. **`WAKE_HUMAN_DECISION` was defined and referenced nowhere else** — the
fifteenth reserved socket, and the only entry in §17.2's list with no producer.

### What shipped

`approve` and `reject` now enqueue `WAKE_HUMAN_DECISION` **inside their own transactions**, following
`expire_due`'s pattern, so a committed decision and its wake cannot come apart. Idempotent on the
request (Charter C6). Silent for a dead or quarantined Cell, because `deliberate` *records* a refusal
rather than raising, and waking one would turn every decision about a dead Cell into a deliberation
row saying it could not think (C8). **Expiry keeps its own reasons** — the review window closing is
not a judgement, which is the line `_decision_note` already refuses to blur.

It matters most for rejection: ADR-053 established a rejection has no other channel at all, and §25.2
wants the reasons for promotion *or rejection* to reach the Cell.

### Verification

- **Teeth-checked five ways, all caught**: no wake on approve; no wake on reject; dead Cells woken;
  a dedupe key not derived from the request; and **expiry relabelled as a human decision** — the most
  tempting way to make this fire more often and exactly the falsehood ADR-055 exists to prevent.
- **Golden diff is one section.** `event_inbox` `cell_wake` rows **9 -> 20**, the scenario's 11
  decisions, counted directly. **`deliberations`, `proposals` and `model_calls` are byte-identical**
  — the scenario never drains the inbox, so this adds a wake and changes nothing any Cell thought —
  and **`balances` is identical in every account in every book**.
- **The golden scenario now exercises six distinct wake reasons**, up from five.
- **A structural test asserts every §17.2 reason has a producer**, so the next one added is either
  wired to the event that justifies it or listed deliberately as inert.
- **1016 tests passing** (6 new; up from 1010).
- Next: the honest re-measurement ADR-055 could not do — with reasons now earned rather than
  rotated, is any of its +15% real? A colony that ticks and is reviewed produces `human decision`
  wakes naturally, so the arm is a scheduled run with an operator deciding, against one without.
