# MITOSIS — Event Delivery Semantics

Phase 0 formal artifact (`docs/SPEC.md` §28 Phase 0, §30). Normative source: §17 (Event Delivery
Semantics), with supporting detail from §3.5 (inbox/outbox), §6.3 (clock interaction), and §17.1's
Amendment A5. This document exists to make the *processing algorithm* explicit — §17 states the
guarantees; this spells out the mechanics an implementer needs to satisfy them.

---

## 1. Delivery guarantee

Events are delivered **at least once**. There is no exactly-once delivery in Phase 1 — handlers
must be idempotent by construction (Charter C6), not by hoping redelivery doesn't happen.

## 2. Event schema

```text
event_id           -- unique identifier for this event
dedupe_key         -- used by the handler to detect "already processed"
attempt_number      -- incremented on each redelivery attempt
event_type
source
target
created_at_utc
available_at        -- earliest time this event may be processed
simulated_at (nullable)  -- simulated-clock timestamp, if this is a synthetic-market event
payload
status
last_error
causation_id         -- the event that caused this one to be produced
correlation_id        -- groups events belonging to one logical workflow
```

Wake events (the set of `event_type`s that move a Cell `dormant → alive`, §1.2 of
`docs/STATE_MACHINES.md`): scheduled research cycle, synthetic customer reply, payment settlement,
test completion, sibling discovery, capital allocation, market change, audit request, human
decision.

## 3. Idempotent processing algorithm (inbox/outbox, §3.5)

A handler processes one event as a single atomic unit:

```text
1. BEGIN transaction
2. Check event_inbox: has this event_id already been marked processed?
   -> if yes: COMMIT (no-op), acknowledge delivery, done.
3. Apply state changes (Cell lifecycle, ledger, reservations, etc.)
4. Write any events this handler produces into event_outbox
   (not published yet — just persisted in the same transaction)
5. Mark this event_id processed in event_inbox
6. COMMIT transaction
7. (after commit) An outbox dispatcher publishes newly-written outbox events
```

Because steps 2–6 are one transaction, a crash between them leaves either "not processed, will be
retried" or "fully processed, including produced events durably staged" — never a half-applied
state. Redelivery after a crash re-enters at step 2 and is a no-op if step 6 already committed.

**Failure mode this prevents:** applying a ledger-affecting state change, crashing before marking
the event processed, then re-applying the same change on redelivery — a double-spend. The inbox
check makes this structurally impossible rather than relying on handler-specific dedup logic.

## 4. Deterministic ordering (Amendment A5)

For golden-run replay (§26) to be deterministic, the scheduler imposes a **total order** on ready
events via the tie-break key:

```text
(effective_time, priority, event_id)
```

- `effective_time` is the primary sort key — `simulated_at` for synthetic events, real UTC
  `available_at` for real events.
- `priority` breaks ties at the same `effective_time`.
- `event_id` breaks remaining ties, guaranteeing a strict total order (no two events may ever
  compare equal).

Every event producer must supply a stable `priority`; there is no "unordered batch" path anywhere
in the kernel that bypasses this ordering.

## 5. Simulated vs. real events never interleave implicitly

Synthetic events carry `simulated_at`; real external events use real UTC `available_at`/
`created_at_utc`. The scheduler never compares a `simulated_at` timestamp against a real UTC
timestamp to interleave them — mixing the two requires explicit conversion metadata (§6.3). This
keeps the simulated clock (`docs/SPEC.md` §6) as the sole authority for synthetic-event ordering,
independent of wall-clock drift.

## 6. Poison-event handling (§17.3)

```text
attempt fails
  -> attempt_number += 1
  -> retry (subject to backoff, not specified further in Phase 0/1)
  -> after a configurable failure threshold:
       - move the event to a dead-letter queue
       - quarantine the affected Cell if the failure implicates Cell-controlled logic
         (see docs/STATE_MACHINES.md §1.2, alive/dormant -> quarantined)
       - create an audit_events row documenting the poison event and the quarantine decision
       - allow controlled (human-triggered) replay from the dead-letter queue
```

A poison event is never silently dropped — it always lands in the dead-letter queue with an audit
trail, and quarantining the Cell (rather than just discarding the event) is a deliberate choice:
an event that reliably crashes its handler is itself evidence about the Cell, not just a
transient fault.

## 7. Why this matters beyond §17's stated rationale

Every invariant above exists because "asynchronous processing will redeliver events and partially
fail" (§17.4) is not a hypothetical for this system — the reservation sweeper (§4.4), the
inbox/outbox pattern (§3.5), and golden-run replay (§26) all depend on event processing being
idempotent *and* deterministically ordered at the same time. Getting one right without the other
still breaks replay: idempotent-but-unordered processing can apply the same correct set of state
changes in a different sequence and diverge; ordered-but-non-idempotent processing double-applies
on redelivery even in the "correct" order.
