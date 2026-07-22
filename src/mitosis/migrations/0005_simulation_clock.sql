-- Colony-owned simulated clock (SPEC.md §6). Single-row config + checkpoint.
-- Field shape matches §27.1 colony.yaml's `simulation_clock:` block, plus a
-- (simulated, wall) checkpoint pair the kernel uses to compute the current
-- simulated time lazily on read (no background ticking process).

CREATE TABLE simulation_clock (
    id                                 INTEGER PRIMARY KEY CHECK (id = 1),
    mode                               TEXT NOT NULL CHECK (mode IN ('paused', 'step', 'accelerated', 'realtime')),
    simulated_seconds_per_wall_second   REAL NOT NULL,
    checkpoint_simulated_at_utc         TEXT NOT NULL,
    checkpoint_wall_at_utc              TEXT NOT NULL
);
