# MITOSIS — Priorities

## Now
- [x] Write `docs/SPEC.md` v0.2 — DONE (1309 lines; 32 sections + Colony Charter + 19 amendments normative)
- [x] Phase 0 formal artifacts — DONE: `docs/DECISIONS.md` (18 ADRs), `docs/STATE_MACHINES.md` (Cell lifecycle FSM + reservation FSM), `docs/EVENT_SEMANTICS.md` (delivery/ordering/poison-event handling)
- [x] Phase 1 kernel slice 1 — DONE: `src/mitosis/{money,db,models,accounts,ledger,reservations,sweeper}.py` + 41 tests (unit + Hypothesis property tests incl. a stateful `charter_crash_recovery` FSM machine). Charter C1/C2/C3/C7/C11 covered for the ledger+reservation surface.
- [x] Phase 1 kernel slice 2 — DONE: Cell lifecycle birth transition (`created->alive`), minimal genome hashing, audit_events, CLI (`mitosis init/status/create-cell`) with a console-script entry point. 59 tests passing.
- [x] Phase 1 kernel slice 3 — DONE: population limits + carrying capacity (Charter C9). `max_living_cells`/`max_active_cells` enforced in `create_cell` under concurrency; `colony_config` table matches `colony.yaml`'s `population:` block shape. 74 tests passing.
- [x] Phase 1 kernel slice 4 — DONE: global real-spend circuit breaker (Charter C5). `real_spend_limits` table matches `colony.yaml`'s `real_spend_limits:` block; per-request/concurrent-reserved/hour/day/~30d caps enforced in `reservations.request` for USD_REAL only, under concurrency. Admin raise/lower is always audited. 92 tests passing.

## Next
- [ ] Phase 1 kernel remainder: event_inbox/outbox, resource metering, remaining lifecycle transitions (alive<->dormant<->quarantined->dead, coroner reports), simulated clock (needed before `max_births_per_epoch` can be enforced), reproduction/lineage tracking (needed before `max_lineage_population_fraction` and displacement can be enforced), experiment tracking (needed before `max_parallel_experiments` can be enforced), model gateway/provider identification (needed before per-provider real-spend caps can be enforced), remaining CLI (`list-cells/show-cell/fund-cell/kill-cell/ledger/verify-ledger/advance-time`), golden-replay test

## Later
- [ ] Phase 2 flight simulator → Phase 3 evolutionary validation (pre-registered) → Phases 4–10 per directive §28
