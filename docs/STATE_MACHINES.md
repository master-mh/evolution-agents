# MITOSIS — State Machines

Phase 0 formal artifact (`docs/SPEC.md` §28 Phase 0, §30). This document makes explicit the two
state machines that `docs/SPEC.md` names but does not fully diagram: the Cell lifecycle (§30,
states only) and the reservation protocol (§4.4, states *and* transitions already normative there
— reproduced here as a single diagram for implementers). Every transition below is required to
emit an `audit_events` row (Charter C10) unless noted otherwise.

---

## 1. Cell lifecycle state machine

### 1.1 States

`created | alive | dormant | quarantined | dead` (§30, normative).

| State | Meaning | Can it act? | Charter |
|---|---|---|---|
| `created` | Genome assigned and hashed (C11); not yet funded/licensed | No | — |
| `alive` | Funded, licensed, actively processing a wake event | Yes | — |
| `dormant` | Normal idle state between wake events — this is the expected resting state, not a penalty | No (until woken) | — |
| `quarantined` | Cannot reach public-facing tools; under review | Restricted — internal-only | C8 |
| `dead` | Terminal; coroner report filed | No | C8 |

### 1.2 Transitions

```text
created
  -> alive          (birth licence granted: capital + valid genome + population slot
                      or objective-only displacement, §9.3. Two paths reach this
                      transition: a *seeded* birth funded from a colony account
                      (lifecycle.create_cell), and *reproduction* from a living parent
                      and funded out of that parent's own cash (lineage.reproduce),
                      which additionally requires the §9.4 lineage-share licence.
                      Only an `alive` Cell may be a parent — a dormant Cell is idle,
                      a quarantined Cell restricted, a dead Cell inert (C8).)
  -> dead            (birth licence denied and no capital reserved — no audit-visible
                      Cell ever existed; not a lifecycle transition, see note below)

alive
  -> dormant         (wake-event processing complete; Cell has no pending work, §17.2)
  -> quarantined     (policy violation; poison-event handling needs isolation, §17.3;
                      adversarial-taint detected, §18)
  -> dead            (objective death criterion met while alive, §10.5)

dormant
  -> alive           (wake event delivered: scheduled research cycle, synthetic customer
                      reply, payment settlement, test completion, sibling discovery,
                      capital allocation, market change, audit request, human decision — §17.2)
  -> quarantined     (policy violation or taint detected while dormant, e.g. from a
                      shared-module retroactive taint finding, §18)
  -> dead            (objective death criterion met while dormant — e.g. stage budget
                      exhausted by elapsed simulated time, carrying-capacity
                      displacement of an objectively-failing dormant Cell, §9.3/§10.5)

quarantined
  -> alive           (human/Auditor review clears the Cell; resolution mirrors the
                      reservation FSM's disputed -> resolved pattern, §4.4)
  -> dormant         (cleared but has no immediate pending work)
  -> dead            (review confirms an objective death criterion, §10.5)

dead
  (terminal — no outbound transitions; C8: dead Cells cannot act)
```

**Note on `created → dead` without passing through `alive`:** if a birth licence is denied, no
population slot is ever consumed and no lifecycle transition is emitted for a Cell that never
became `alive` — this is a failed birth *request*, not a Cell lifecycle event. Only Cells that
reached `alive` at least once get a coroner report on death (§10.5); a denied birth request is
logged as an ordinary event, not a coroner report.

### 1.3 Guards

| Transition | Guard |
|---|---|
| `created → alive` | Sufficient capital reserved; valid child genome; available population slot **or** a successful objective-only displacement (§9.3, ADR-009) |
| `* → quarantined` | Policy violation, poison-event threshold exceeded (§17.3), or adversarial-lineage taint detected (§18.2) |
| `quarantined → dead` | An objective §10.5 death criterion is independently confirmed during review — quarantine review may *not* invent a death criterion; it only confirms or clears one already met |
| `* → dead` | One of: stage budget exhausted; N consecutive failed validation gates; evidence cannot be reproduced; policy violation; carrying-capacity displacement (objective-only, §9.3); dominated by a superior near-duplicate. **Estimated negative EV alone must not kill a Cell** unless evidence is strong *and* an independent Auditor/evaluator concurs (§10.5) |
| `dead → *` | None — terminal |

### 1.4 Side effects required on every transition

- `audit_events` row (Charter C10) — no exceptions.
- `* → dead`: coroner report artifact (genome hash, spend by book, stage reached, cause of death,
  final hypotheses, links to experiments — §10.5, Amendment A15), feeding the negative-finding
  credit path (§11) and the knowledge graph.
- `* → quarantined`: the triggering policy violation or taint finding is linked in the audit event
  so the quarantine is auditable, not just a status flip.

---

## 2. Reservation state machine

Normative source: `docs/SPEC.md` §4.4 (Amendment A4). Reproduced here as a diagram for
implementers; §4.4 remains the authoritative text if the two ever disagree — update this file at
the same time as §4.4, never independently.

### 2.1 States

`requested | reserved | execution_unknown | partially_settled | settled | released | disputed`

| State | Meaning |
|---|---|
| `requested` | Spend requested; funds not yet committed |
| `reserved` | Funds committed to `cell:{id}:committed` |
| `execution_unknown` | Crash/timeout; external effect uncertain — **must be reconciled, never auto-released** (Charter C7) |
| `partially_settled` | Some cost settled; remainder pending release |
| `settled` | Actual cost known; committed → spent (terminal) |
| `released` | Execution never happened, or was cancelled (terminal) |
| `disputed` | Under human/Auditor resolution |

### 2.2 Transitions

```text
requested
  -> reserved             (funds committed to cell:{id}:committed)

reserved
  -> settled              (actual cost known; committed -> spent)
  -> partially_settled    (some cost settled; remainder released)
  -> released             (execution never happened / cancelled)
  -> execution_unknown    (crash/timeout; external effect uncertain)

execution_unknown
  -> settled / partially_settled / released / disputed   (after reconciliation)

partially_settled
  -> released             (remainder freed)

disputed
  -> settled / released   (after human/auditor resolution)
```

Terminal states: `settled`, `released`, `disputed→resolved` (resolves into `settled` or
`released`).

### 2.3 The sweeper

A reservation **sweeper** identifies expired or orphaned `reserved` reservations. Before
releasing, it determines whether the external operation may have completed:

- If the external operation is confirmed **not** to have happened → `released`.
- If confirmed to have happened → `settled` / `partially_settled`.
- If it cannot be determined → `execution_unknown`, routed to reconciliation — **never
  auto-released** (Charter C7: crash at reserve/execute/settle recovers with no double-spend).

### 2.4 Guards

| Transition | Guard |
|---|---|
| `requested → reserved` | Global real-spend cap check passes, counting already-reserved spend (Charter C5, ADR-006) |
| `reserved → execution_unknown` | Only on crash/timeout where external-effect confirmation is unavailable at recovery time |
| `execution_unknown → released` | Sweeper positively confirms the external operation did not occur |
| `execution_unknown → settled/partially_settled` | Sweeper positively confirms the external operation occurred, with actual cost known |
| `execution_unknown → disputed` | Confirmation is ambiguous or contested; routed to human/Auditor |
| `disputed → settled/released` | Human or Auditor resolution recorded |

### 2.5 Side effects required on every transition

- `audit_events` row is not separately required by §4.4, but every reservation transition is
  itself an entry in `reservations` with `status` updated; ledger-affecting transitions
  (`→ reserved`, `→ settled`, `→ partially_settled`, `→ released`) must post a balanced
  `ledger_transactions`/`ledger_entries` pair in the same book as the reservation (Charter C1).
