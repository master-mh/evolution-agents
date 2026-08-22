-- Rung 7: an approved grant allocates capital (SPEC.md §25.1, §25.2, §17.2, §31).
--
-- This is the migration that makes the colony's core loop close. §31's line for
-- it is one clause long — "allocate capital -> scale, mutate, collaborate,
-- sleep, or die" — and until now the colony could do everything on either side
-- of that arrow and nothing at the arrow itself.
--
-- **Two sockets the spec left open are what this fills, and neither is new
-- here.** `promotion_pool` has been in §31's required account list since Phase
-- 1 with nothing ever moving through it ("capital held for §25 promotion —
-- redistributed, never consumed"), and §17.2 lists "capital allocation" among
-- its wake reasons, a constant defined in `deliberation.py` that nothing has
-- ever emitted. A Cell being woken *because* it was funded is the behaviour
-- both were reserved for.
--
-- **What makes this rung 7 and not rung 9.** §25.1's ladder puts "tiny capped
-- live experiment" one step past "human-reviewed prototype". Every allocation
-- here still requires a human to have approved the request individually
-- (§23.1) and a human to run the allocation — nothing allocates on a schedule.
-- What changes is that an approval now *does* something, where before ADR-027's
-- grant was inert by construction. Rung 8 ("expanded pilot") and rung 9
-- ("bounded autonomy") would mean removing one of those two humans, and that is
-- a separate, argued step.


-- §25.2's promotion evidence: "At each rung record predicted vs observed
-- outcome, cost, liability, reality gap (from the prediction register, §8.5),
-- human intervention, transfer degradation, and the reasons for promotion or
-- rejection."
--
-- Two of those cannot be known at allocation time and are recorded as such
-- rather than fabricated. *Observed* outcome resolves later, through the
-- hash-chained prediction register — which is why this table stores the
-- calibration snapshot as it stood at promotion instead of a copy of the
-- predictions themselves: the register is the canonical record and duplicating
-- it here would create a second version that could disagree. *Transfer
-- degradation* needs a previous rung to degrade from, and no Cell has one yet.
CREATE TABLE promotions (
    promotion_id            TEXT PRIMARY KEY,

    -- One promotion per grant, enforced. This is what makes a grant
    -- single-use: `approval_grants.consumed_at_utc` records the fact, and this
    -- UNIQUE makes a concurrent second attempt fail on the write rather than
    -- on a check that could race.
    grant_id                TEXT NOT NULL UNIQUE REFERENCES approval_grants(grant_id),
    request_id              TEXT NOT NULL REFERENCES approval_requests(request_id),
    proposal_id             TEXT NOT NULL REFERENCES proposals(proposal_id),
    cell_id                 TEXT NOT NULL REFERENCES cells(cell_id),

    -- Which rung of §25.1's ladder this promotion represents. Stored rather
    -- than assumed: the ladder has nine rungs and a later slice that starts
    -- issuing rung-8 promotions must not be indistinguishable in the record
    -- from this one.
    rung                    INTEGER NOT NULL CHECK (rung BETWEEN 1 AND 9),

    book                    TEXT NOT NULL CHECK (book IN ('USD_REAL', 'USD_SIM', 'RESOURCE')),

    -- The amount actually moved, which is the amount the operator approved and
    -- not a figure re-read from the Cell at allocation time. §23.2 showed the
    -- human a number; that number is what gets allocated.
    allocated_minor_units   INTEGER NOT NULL CHECK (allocated_minor_units > 0),

    -- §25.2 "reality gap (from the prediction register, §8.5)", snapshotted.
    -- NULL mean_brier means nothing has resolved yet, which is itself the
    -- honest reading for a Cell being promoted on its first request.
    reality_gap_mean_brier  REAL,
    resolved_predictions    INTEGER NOT NULL,
    unresolved_predictions  INTEGER NOT NULL,

    -- §25.2 "liability". No liability reserve exists (§13 is Phase 6+), so this
    -- is NULL and reported as unmodelled. A fabricated 0 would read as "no
    -- liability" rather than "not yet modelled".
    liability_minor_units   INTEGER,

    -- §25.2 "transfer degradation": how much worse the strategy performed at
    -- this rung than the last. NULL until a Cell has been promoted twice.
    transfer_degradation    REAL,

    -- §25.2 "human intervention" and "the reasons for promotion". Two distinct
    -- humans in principle: the one who approved the request under §23, and the
    -- one who ran the allocation. Usually the same person on a solo-operated
    -- colony (A19), and recorded separately anyway so that stops being true
    -- silently.
    approved_by             TEXT NOT NULL,
    allocated_by            TEXT NOT NULL,
    reason                  TEXT NOT NULL,

    created_at_utc          TEXT NOT NULL
);

CREATE INDEX idx_promotions_cell ON promotions (cell_id);
CREATE INDEX idx_promotions_rung ON promotions (rung);
