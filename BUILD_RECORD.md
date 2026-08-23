# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, and the §27.1 autonomy decisions, 2026-07-21 through
2026-08-23):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-23 — §23.3's other clock: an approval nobody consumed

`approval.expire_grants_due` + migration 0023 (ADR-039). §23.3 says "pending approvals expire;
expired actions are **regenerated and re-evaluated** before execution", and ADR-027 built exactly
that — for a PENDING request. A grant is the other side of the same clock and had no path at all.

### The bug was a comment that told the truth about a mechanism that did not exist

All three grant consumers — `tools`, `external_actions`, `promotion` — refused a stale grant with
some version of "§23.3: an expired approval is regenerated, never executed late". The regeneration
is real and covers pending requests only: `expire_due` sweeps `WHERE status = PENDING`, and an
approved grant's request is APPROVED, so the sweep never saw it.

**Verified before building rather than reasoned about.** Driving a real grant past its expiry left
`expire_due` sweeping 0 requests, `regenerated_wake_key` NULL, the grant sitting unconsumed in the
table, and 0 wakes enqueued. A human approved something, went away, and the action vanished with
the Cell still waiting on it — which is the solo-operator failure Amendment A19 exists to name.

### The constraint: regeneration is a wake, never a new authorisation

This shaped everything else, and both obvious designs are wrong in the same way. Renewing the grant
with a fresh window, or reopening the request as PENDING for a second decision, would each **turn
one human decision into an indefinite licence, refreshed by the very mechanism meant to end it** —
which is precisely the banking a grant's inherited expiry exists to prevent. §23.3's word is
"re-evaluated", and re-evaluation is a person's. So the Cell is woken, proposes again, and a human
approves again.

`test_an_expired_grant_never_becomes_a_new_authorisation` asserts the grant total is unchanged by a
sweep, that no grant survives its own expiry, and that no request reopens itself.

### The request stays APPROVED, and that is not tidiness

Marking it EXPIRED is the neater-looking option and destroys information twice. §3.6's habit is the
first reason: a human *did* approve it, and that is history. The second is a collision —
`RequestStatus.EXPIRED` already means **expired unreviewed**, so reusing it would fold "nobody ever
looked" into "someone approved it and the window lapsed". Those are different facts about the
operator and about the proposal's merit, and the queue's own statistics would stop distinguishing
them.

### A distinct wake reason, because §15 shows it to the Cell

`grant_expired` rather than reusing `approval_expired`. "Expired unreviewed" says nothing about
merit; "approved, then the window lapsed" says a human judged it worth doing — exactly what a Cell
deciding whether to re-propose should know. Neither reason is in §17.2's list, which is
illustrative rather than closed.

### Nothing is released, because a grant holds nothing

`approve` inserts a row and reserves no money and no RESOURCE; ADR-029 allocates capital when a
grant is *consumed*. So expiry is a bookkeeping transition plus a wake, with no ledger consequence
at all — and the golden diff proves it rather than asserting it. `test_a_grant_expiry_moves_no_money`
pins it so a later slice that makes granting reserve something shows up as a missing release rather
than a slow leak.

Regeneration can loop — propose, approve, lapse, propose — and it is bounded where everything else
is: each cycle costs a deliberation against the Cell's budget (Charter C4/C5), and §23.3's own
metabolic alarm watches the burn rate. A cap here would be a second, weaker copy of both.

### Verification

- **835 tests passing** (7 new, 0 removed; up from 828).
- **Golden expectation 17 → 18, and a tight diff — three sections, with the absence being half the
  point.** `approval_grants` stops being a bare count and becomes a disposition: `9` →
  `{total: 9, live: 0, consumed: 5, expired: 4, regenerated: 4}`. Four grants in the scenario were
  approved and never consumed (the refused email sibling claim and the three refused publish
  claims). **`total` is unchanged by the sweep, and that is the assertion** — a kernel that renewed
  instead of waking would still show `expired: 4` and would move `total` to 13. `audit_event_types`
  gains `grant_expired: 4`; `event_inbox` gains four pending `cell_wake` rows. **Nothing else moves
  at all** — no balance, transaction, reservation or `resource_usage` row, which is what "a grant
  holds nothing" looks like in a snapshot.
- **Teeth-checked six ways**, each failing its named test: the sweep removed entirely (the original
  bug), regeneration renewing the grant instead of waking, the expiry written onto the request as
  EXPIRED, a consumed grant swept too, `expired_at_utc` never recorded (breaking idempotency), and
  an unwakeable Cell's grant skipped rather than expired.
- **Hand-verified end to end on a live colony**: the sweep expires and regenerates, a second run is
  a no-op, the grant total stays 1, the request stays `approved`, the wake carries
  `wake_reason: grant_expired` and sits pending, one `grant_expired` audit row is written, the
  executor refuses with the message that now names the sweep, and conservation is green in all
  three books with the hash chain valid.
- Next: **both sweeps still have exactly one caller**, `mitosis expire-approvals`. The machinery
  built for an absent operator only runs when the operator is present, which is the other half of
  PRIORITIES' "nothing handles the operator being away" and now the sharper half. Wiring it to the
  scheduler is a §23.3 *vacation-mode* question — what the colony does with nobody watching — and
  wants its own argument rather than a quiet addition to `tick`.
