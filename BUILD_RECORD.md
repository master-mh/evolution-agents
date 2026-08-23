# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, and grant regeneration,
2026-07-21 through 2026-08-23):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-23 — The sweep runs before the guards

`scheduler.tick` (ADR-040). ADR-039 gave an unconsumed grant a regeneration path and ADR-027 gave a
pending request one. Both had exactly one caller — `mitosis expire-approvals` — so **the machinery
built for an absent operator only ran when the operator was present to type a command.** A cron
tick is the thing that is actually there when nobody is.

### Wiring it in is one line. The placement is the decision.

The sweep runs **before `_guard`**, which is the opposite of everything else in `tick`.

Every guard below it decides whether the colony may **do** something: the metabolic alarm, the
`real_spending` gate, vacation mode. They stop spending, deliberating, acting. The sweep only ever
**removes** permission — it expires a request nobody decided and an approval nobody consumed, and
it cannot authorise anything. Gating it behind the guards would invert their purpose, because **a
halt that also stopped expiry would preserve exactly the authorisations the halt exists to stop
being used.**

Vacation mode is what makes that bite rather than being a nicety. §23.3 pauses external-facing work
when the operator is unresponsive — precisely the condition under which approvals lapse unconsumed.
Sweeping after the guard would disable the mechanism built for an absent operator *whenever the
operator is absent*. That is the same inversion this repo hit twice in one week: a disproof pointer
that named the bug as its own resolution, and now a guard that would have switched off the thing it
exists to make safe.

The alternative it displaced is the one a reader would naturally write — put the sweep beside the
wakes, since "expire, then run what expiry produced" reads as a single step. It is two steps, and
they belong on opposite sides of the halt.

### The cost stays guarded, and that falls out rather than needing a rule

Expiring is free. The wakes it enqueues are only *processed* by `run_ready_wakes`, which a halted
tick returns before reaching. So a halted colony withdraws stale authority immediately and leaves
the re-deliberation pending until a tick is allowed to run: **authority goes at once, spending
waits.** No extra condition expresses this — it is what the placement already means.

On a tick that does run, the regenerated wake is processed in the same tick, and that is correct
rather than merely convenient: §23.3's staleness sits between the original approval and now, and
"now" is already later than the window that lapsed.

### Verification

- **839 tests passing** (4 new, 0 removed; up from 835). **Golden run unchanged** — the scenario's
  grants are not stale at wall-clock tick time, so the sweep runs and correctly finds nothing.
- **Teeth-checked four ways**, each failing its named test: `tick` not sweeping at all (the state
  before this slice), the sweep gated behind the guards (the inversion), a halted tick processing
  the wakes it regenerated, and the sweep losing idempotence across ticks.
- **Hand-verified on a live colony.** A tick logged
  `ran | 2 deliberation(s); expired 0 request(s), 1 grant(s)` — the scheduled wake plus the
  regenerated one — with the grant showing `expired_at_utc` set, `regenerated_wake_key` set,
  `consumed_at_utc` NULL, the grant total still 1 (no renewal), the request still `approved`, and
  the regenerated wake `processed`. The halted-tick path is covered by tests rather than by hand,
  since reaching it live needs either a paid provider or a tripped alarm.
- `TickResult` gains `requests_expired` / `grants_expired`, and the counts reach the tick log's
  `detail` on every outcome including a halt — a halted tick that said only "nothing was woken"
  would hide the one thing that did happen.
- **Noted, not special-cased:** regenerated wakes are not bounded by `max_cells`, which caps only
  scheduled research wakes, so a burst of expiries becomes a burst of deliberations in one tick.
  That is bounded by the per-request/hour/day real-spend caps inside a tick and the metabolic alarm
  across ticks — the same guards that bound everything else, on ADR-039's principle that a local
  cap would be a second, weaker copy of both.
- Next: with this, §23.3 is fully built — SLAs, expiry, regeneration on both clocks, vacation mode
  and the metabolic alarm. The nearest open work is `set-rights`, now flagged by four consecutive
  slices: an artifact built on a fetched page is `commercial_use: unknown` forever, so
  `real_commerce` could be opened and still sell nothing.
