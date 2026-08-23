-- §23.3's second half, for the side of the clock it never reached
-- (SPEC.md §23.3, §17.2, §3.6; Amendment A19; ADR-039).
--
-- "Pending approvals expire; expired actions are **regenerated and
-- re-evaluated** before execution." `approval.expire_due` has done that for a
-- PENDING request since ADR-027: the Cell is woken under `approval_expired` and
-- re-derives the action against a world that moved.
--
-- A grant is the other side of the same clock and had no such path. It inherits
-- its request's expiry so an approval cannot be banked and spent later — but
-- once the request is APPROVED it is no longer PENDING, so the sweep never saw
-- it. An approved grant nobody consumed expired in silence: all three executors
-- (`tools`, `external_actions`, `promotion`) refused it, and nothing told the
-- Cell. Verified before it was built — expire_due swept 0, the grant sat
-- unconsumed, 0 wakes were enqueued.
--
-- **The expiry is recorded on the grant, and the request stays APPROVED.**
-- Two reasons, and the second is the one that would have been easy to get
-- wrong:
--   1. §3.6's habit — a human *did* approve it, and that is history rather than
--      something to overwrite.
--   2. `RequestStatus.EXPIRED` already means "expired unreviewed". Reusing it
--      here would collapse "nobody ever looked" into "someone approved it and
--      the window lapsed", which are different facts about the operator and
--      about the proposal's merit. The queue's own statistics would stop being
--      able to tell them apart.
--
-- **Nothing is released, because a grant holds nothing.** `approve()` inserts a
-- row and reserves no money or RESOURCE; ADR-029's capital allocation happens
-- when a grant is *consumed*, not when it is issued. So expiry here is a
-- bookkeeping transition plus a wake, with no ledger consequence at all — which
-- is why this migration touches no accounting table.

-- When the sweep expired it. NULL for a grant that is live, or was consumed
-- before its window closed.
ALTER TABLE approval_grants ADD COLUMN expired_at_utc TEXT;

-- The wake that regenerates the action, mirroring `approval_requests.
-- regenerated_wake_key`. **Stays NULL when the Cell can no longer deliberate**
-- (dead, quarantined) rather than being omitted, so "nothing to regenerate
-- into" is visible in the row instead of looking like a wake that vanished.
--
-- What it must never be is a new *grant*. §23.3 says regenerated **and
-- re-evaluated**: the Cell proposes again and a human approves again. Renewing
-- the grant is the obvious design and is precisely the banking that the shared
-- expiry exists to prevent.
ALTER TABLE approval_grants ADD COLUMN regenerated_wake_key TEXT;

-- The sweep's predicate: live, unconsumed, past its window.
CREATE INDEX idx_approval_grants_expiry
    ON approval_grants (expires_at_utc)
    WHERE consumed_at_utc IS NULL AND expired_at_utc IS NULL;
