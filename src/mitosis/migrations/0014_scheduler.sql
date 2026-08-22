-- The scheduler: epochs, the metabolic alarm, and vacation mode
-- (SPEC.md §6.3, §17.2, §23.3, §27.1 `operator:`; Amendment A19).
--
-- This is the last piece between a colony that must be driven by hand and one
-- that runs unattended. That is exactly why most of what follows is guards
-- rather than scheduling: §23.3 exists because "400 approvals quietly queuing
-- overnight" is the failure mode of automation, not of agents.

-- Epoch definition. An epoch is a fixed span of *simulated* time (§6), and the
-- unit §9.2 (`max_births_per_epoch`) and §23.3 (`metabolic_alarm_cents_per_epoch`)
-- both already assume exists. The current epoch number is always *derived* from
-- the clock, never stored — the same rule balances follow (Charter C3), and for
-- the same reason: a cached epoch counter and a clock that disagree would be
-- resolved in favour of whichever the reader happened to consult.
CREATE TABLE epoch_config (
    id                       INTEGER PRIMARY KEY CHECK (id = 1),
    genesis_simulated_at_utc TEXT NOT NULL,
    epoch_duration_seconds   INTEGER NOT NULL CHECK (epoch_duration_seconds > 0)
);

-- Where simulated time is converted to wall time, and the record of that
-- conversion. §6.3: simulated and real events "are never mixed without explicit
-- conversion metadata" — this table *is* that metadata, and it is what makes
-- §23.3's alarm computable at all.
--
-- The problem it solves: the alarm wants "real cents spent per sim-epoch", but
-- every ledger row is stamped in wall time (the clock is still not wired into
-- ledger timestamps — see clock.py). Attributing spend to an epoch therefore
-- needs to know when that epoch began *in wall time*, which is only knowable by
-- recording it as it is crossed. Hence one row per observed epoch, written the
-- first time a tick sees it.
CREATE TABLE epoch_log (
    epoch_number             INTEGER PRIMARY KEY,
    started_at_wall_utc      TEXT NOT NULL,
    started_at_simulated_utc TEXT NOT NULL
);

-- One row per scheduler tick, so an unattended colony leaves a record of what
-- it did while nobody was watching — including the ticks that did nothing, and
-- why. A scheduler whose refusals are invisible is one you cannot debug at 3am.
CREATE TABLE scheduler_ticks (
    tick_id             TEXT PRIMARY KEY,
    epoch_number        INTEGER NOT NULL,
    started_at_utc      TEXT NOT NULL,
    provider            TEXT NOT NULL,
    is_paid             INTEGER NOT NULL CHECK (is_paid IN (0, 1)),
    outcome             TEXT NOT NULL CHECK (outcome IN (
                            'ran',                -- woke Cells
                            'idle',               -- nothing eligible
                            'halted_metabolic',   -- §23.3 alarm active
                            'halted_vacation',    -- §23.3 operator absent
                            'halted_autonomy'     -- §27.1 real_spending disabled
                        )),
    detail              TEXT,
    cells_woken         INTEGER NOT NULL DEFAULT 0,
    spend_before_minor  INTEGER NOT NULL DEFAULT 0,
    spend_after_minor   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_scheduler_ticks_epoch ON scheduler_ticks (epoch_number);

-- §23.3's operator model (A19). Defaults come from §27.1's `operator:` block,
-- with `real_spending` from its `autonomy:` block — the spec ships that as
-- **false**, so an unattended scheduler is free-provider-only until somebody
-- deliberately says otherwise.
CREATE TABLE operator_state (
    id                              INTEGER PRIMARY KEY CHECK (id = 1),
    last_heartbeat_utc              TEXT NOT NULL,
    vacation_pause_after_seconds    INTEGER NOT NULL DEFAULT 172800,
    metabolic_alarm_cents_per_epoch INTEGER NOT NULL DEFAULT 50,

    -- The acceleration half of §23.3. The alarm is not another cap — the caps
    -- already exist and §23.3 says it fires "even if every individual cap is
    -- satisfied". It watches the *derivative*: an epoch burning this multiple
    -- of the recent baseline is anomalous regardless of whether it is under
    -- the ceiling, which is what catches a colony quietly accelerating.
    metabolic_acceleration_factor   REAL NOT NULL DEFAULT 3.0,

    -- §27.1 `autonomy.real_spending`. Ships false.
    real_spending_enabled           INTEGER NOT NULL DEFAULT 0 CHECK (real_spending_enabled IN (0, 1)),

    -- Set when the alarm fires. Non-NULL halts the scheduler until an operator
    -- explicitly acknowledges — an alarm that self-clears on the next tick is
    -- not a guard, it is a log line.
    metabolic_alarm_at_utc          TEXT,
    metabolic_alarm_reason          TEXT
);
