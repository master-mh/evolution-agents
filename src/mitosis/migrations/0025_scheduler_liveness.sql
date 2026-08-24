-- A tick that dies leaves a record, and something outside can ask whether the
-- colony is still running (SPEC.md §23.3, §30.1, §17.2; ADR-022, ADR-040;
-- Charter C14; ADR-042).
--
-- `tick` is a command composable with cron, which §30.1's "avoid unnecessary
-- frameworks" makes the right shape: cron already restarts it, because it runs
-- again next minute whether or not the last run succeeded. What cron does not
-- do is *tell anyone*. Two failures were invisible and they are not the same
-- failure:
--
--   1. **Nothing is running the scheduler.** No crontab installed, the host
--      rebooted, the entry was removed.
--   2. **Something is running it and every run dies.** A bad migration, an
--      unreadable database, a provider misconfiguration.
--
-- From outside they looked identical, because **`scheduler_ticks` was only ever
-- written at the *end* of a tick**. A crash anywhere — the expiry sweeps, a
-- guard, `run_ready_wakes`, a provider call — left no row at all, so a colony
-- failing every minute for a week was indistinguishable from one that had never
-- been scheduled. The two need different people to fix them.
--
-- **The fix already exists in this repo, one layer down.** `tool_calls` writes
-- `status = 'requested'` *before* the external call, and migration 0019 said
-- why: "a crash mid-call leaves a diagnosable row rather than a reservation
-- with nothing explaining it. The gateway cannot say which steps ran; this
-- table can." The scheduler was in the state the gateway is in. Same move.

-- SQLite cannot alter a CHECK constraint, so the table is rebuilt. Nothing
-- references it by foreign key, which is what makes this a copy rather than a
-- migration with an ordering problem.
CREATE TABLE scheduler_ticks_new (
    tick_id             TEXT PRIMARY KEY,
    epoch_number        INTEGER NOT NULL,
    started_at_utc      TEXT NOT NULL,

    -- NULL means this tick began and never reported back. That is not the same
    -- as 'crashed': a Python exception can be caught and described, but a
    -- SIGKILL, an OOM or a power cut cannot write anything at all. The absence
    -- *is* the signal, and it is the one that survives the process dying
    -- between statements.
    finished_at_utc     TEXT,

    provider            TEXT NOT NULL,
    is_paid             INTEGER NOT NULL CHECK (is_paid IN (0, 1)),
    outcome             TEXT NOT NULL CHECK (outcome IN (
                            'started',            -- written before the work
                            'ran',                -- woke Cells
                            'idle',               -- nothing eligible
                            'crashed',            -- raised; detail is redacted
                            'halted_metabolic',   -- §23.3 alarm active
                            'halted_vacation',    -- §23.3 operator absent
                            'halted_autonomy'     -- §27.1 real_spending disabled
                        )),
    detail              TEXT,
    cells_woken         INTEGER NOT NULL DEFAULT 0,
    spend_before_minor  INTEGER NOT NULL DEFAULT 0,
    spend_after_minor   INTEGER NOT NULL DEFAULT 0
);

-- Existing rows all completed — the old code could not write one otherwise.
-- `finished_at_utc` is backfilled from `started_at_utc` rather than left NULL,
-- because NULL now means "never reported back" and backfilling NULL would
-- retroactively describe every historical tick as a crash.
INSERT INTO scheduler_ticks_new (
    tick_id, epoch_number, started_at_utc, finished_at_utc, provider, is_paid,
    outcome, detail, cells_woken, spend_before_minor, spend_after_minor
)
SELECT
    tick_id, epoch_number, started_at_utc, started_at_utc, provider, is_paid,
    outcome, detail, cells_woken, spend_before_minor, spend_after_minor
FROM scheduler_ticks;

DROP TABLE scheduler_ticks;
ALTER TABLE scheduler_ticks_new RENAME TO scheduler_ticks;

CREATE INDEX idx_scheduler_ticks_epoch ON scheduler_ticks (epoch_number);

-- `health` reads the tail of this table, newest first, on every invocation.
CREATE INDEX idx_scheduler_ticks_started ON scheduler_ticks (started_at_utc);


-- How often the operator's crontab actually runs `tick`, when they want a
-- tighter liveness rule than the default.
--
-- **NULL means "one epoch", and that default is the policy rather than a
-- placeholder.** What an outage costs the colony is *work*, and work is
-- measured in epochs: wakes are `epoch:{n}:cell:{id}`, so any tick inside an
-- epoch does that epoch's work and a second one does nothing. A colony that has
-- not ticked for two epochs has skipped an epoch's wakes; one that ticked
-- thirty seconds ago in a one-hour epoch has skipped nothing, however many cron
-- runs it missed.
--
-- The tempting alternative — alarm on wall-clock silence by default — would
-- have rested on a premise worth checking, which is that a late expiry sweep
-- leaves stale authority usable. **It does not.** ADR-039 established that all
-- three executors (`tools`, `external_actions`, `promotion`) refuse an expired
-- grant on their own terms; the sweep exists to *regenerate the wake*, not to
-- enforce the refusal. So sweep latency is a responsiveness cost, not a safety
-- hole, and it does not justify making every operator configure a wall clock.
-- An operator who cares about that responsiveness sets this column.
ALTER TABLE operator_state ADD COLUMN tick_expected_every_seconds INTEGER
    CHECK (tick_expected_every_seconds IS NULL OR tick_expected_every_seconds > 0);
