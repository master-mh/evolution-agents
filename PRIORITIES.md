# MITOSIS — Priorities

## Now
- [x] Write `docs/SPEC.md` v0.2 — DONE (1309 lines; 32 sections + Colony Charter + 19 amendments normative)
- [x] Phase 0 formal artifacts — DONE: `docs/DECISIONS.md` (18 ADRs), `docs/STATE_MACHINES.md` (Cell lifecycle FSM + reservation FSM), `docs/EVENT_SEMANTICS.md` (delivery/ordering/poison-event handling)
- [x] Phase 1 kernel slice 1 — DONE: `src/mitosis/{money,db,models,accounts,ledger,reservations,sweeper}.py` + 41 tests (unit + Hypothesis property tests incl. a stateful `charter_crash_recovery` FSM machine). Charter C1/C2/C3/C7/C11 covered for the ledger+reservation surface.
- [x] Phase 1 kernel slice 2 — DONE: Cell lifecycle birth transition (`created->alive`), minimal genome hashing, audit_events, CLI (`mitosis init/status/create-cell`) with a console-script entry point. 59 tests passing.

## Next
- [ ] Phase 1 kernel remainder: event_inbox/outbox, real-spend circuit breaker, resource metering, remaining lifecycle transitions (alive<->dormant<->quarantined->dead, coroner reports), **population limits (Charter C9 — create_cell currently does NOT enforce carrying capacity, known gap)**, simulated clock, remaining CLI (`list-cells/show-cell/fund-cell/kill-cell/ledger/verify-ledger/advance-time`), golden-replay test

## Later
- [ ] Phase 2 flight simulator → Phase 3 evolutionary validation (pre-registered) → Phases 4–10 per directive §28
