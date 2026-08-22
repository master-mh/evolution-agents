"""Colony-owned simulated clock (SPEC.md §6; docs/DECISIONS.md ADR-007).

Lazy / pull-based: there is no background thread ticking simulated time
forward. `now()` computes the current simulated time on read, projecting a
(simulated, wall) checkpoint forward by however much wall-clock time has
elapsed at the configured mode's rate. This fits a synchronous, CLI-driven
kernel with no event loop yet — there's nothing to tick continuously until
Phase 2's flight simulator has a real scheduler.

`get_state`/`now` fall back to an implicit default (paused, anchored at the
current wall time) when the clock hasn't been configured, rather than
raising — same pattern as population.get_limits and
real_spend_breaker.get_limits.

Deliberately NOT done in this slice (see PRIORITIES.md): existing kernel
timestamps — ledger effective_at_utc, reservation reserved_at/expires_at,
the real-spend breaker's hour/day/month window math, audit_events
created_at_utc — all still run on real wall-clock time. SPEC.md §6.3 draws
a line between synthetic events (simulated time) and real external events
(real UTC) that "are never mixed without explicit conversion metadata".
Wiring that distinction through every existing money-path module is a
separate, larger change: e.g. the real-spend breaker's windows would need
a careful redesign if USD_SIM and USD_REAL transactions started living on
different clocks. This slice only builds the clock primitive itself and
`mitosis advance-time`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .models import ClockMode, SimulationClockState

_MODE_RATES: dict[ClockMode, float] = {
    ClockMode.PAUSED: 0.0,
    ClockMode.STEP: 0.0,
    ClockMode.REALTIME: 1.0,
}

DEFAULT_ACCELERATED_RATE = 86400.0  # 1 simulated day per wall second, matches colony.yaml


class ClockError(Exception):
    pass


def _rate_for(mode: ClockMode, simulated_seconds_per_wall_second: float) -> float:
    if mode == ClockMode.ACCELERATED:
        return simulated_seconds_per_wall_second
    return _MODE_RATES[mode]


def _row_to_state(row: sqlite3.Row) -> SimulationClockState:
    return SimulationClockState(
        mode=ClockMode(row["mode"]),
        simulated_seconds_per_wall_second=row["simulated_seconds_per_wall_second"],
        checkpoint_simulated_at_utc=datetime.fromisoformat(row["checkpoint_simulated_at_utc"]),
        checkpoint_wall_at_utc=datetime.fromisoformat(row["checkpoint_wall_at_utc"]),
    )


def get_state(conn: sqlite3.Connection) -> SimulationClockState:
    row = conn.execute("SELECT * FROM simulation_clock WHERE id = 1").fetchone()
    if row is not None:
        return _row_to_state(row)
    wall_now = datetime.now(timezone.utc)
    return SimulationClockState(
        mode=ClockMode.PAUSED,
        simulated_seconds_per_wall_second=DEFAULT_ACCELERATED_RATE,
        checkpoint_simulated_at_utc=wall_now,
        checkpoint_wall_at_utc=wall_now,
    )


def initialize_if_absent(
    conn: sqlite3.Connection,
    *,
    mode: ClockMode = ClockMode.PAUSED,
    simulated_seconds_per_wall_second: float = DEFAULT_ACCELERATED_RATE,
    start_at: datetime | None = None,
) -> SimulationClockState:
    """Baseline initialization only (e.g. from `mitosis init`) — leaves an
    already-initialized clock untouched, same pattern as
    population.set_limits_if_absent."""
    start = start_at or datetime.now(timezone.utc)
    if start.tzinfo is None:
        raise ClockError("start_at must be timezone-aware UTC (Charter C11)")
    conn.execute(
        """
        INSERT OR IGNORE INTO simulation_clock (
            id, mode, simulated_seconds_per_wall_second,
            checkpoint_simulated_at_utc, checkpoint_wall_at_utc
        ) VALUES (1, ?, ?, ?, ?)
        """,
        (
            mode.value,
            simulated_seconds_per_wall_second,
            start.astimezone(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return get_state(conn)


def now(conn: sqlite3.Connection, *, wall_now: datetime | None = None) -> datetime:
    """Current simulated time: the last checkpoint projected forward by
    elapsed wall time at the configured mode's rate."""
    state = get_state(conn)
    wall_now = wall_now or datetime.now(timezone.utc)
    rate = _rate_for(state.mode, state.simulated_seconds_per_wall_second)
    elapsed_wall_seconds = (wall_now - state.checkpoint_wall_at_utc).total_seconds()
    elapsed_wall_seconds = max(elapsed_wall_seconds, 0.0)  # clock skew never runs sim time backwards
    return state.checkpoint_simulated_at_utc + timedelta(seconds=elapsed_wall_seconds * rate)


def advance(conn: sqlite3.Connection, delta: timedelta) -> datetime:
    """Explicitly jump simulated time forward by `delta`, regardless of
    mode, and re-anchor the checkpoint to this instant. Used by
    `mitosis advance-time`."""
    if delta < timedelta(0):
        raise ClockError("cannot advance time backwards")

    conn.execute("BEGIN IMMEDIATE")
    try:
        wall_now = datetime.now(timezone.utc)
        state = get_state(conn)
        new_simulated = now(conn, wall_now=wall_now) + delta
        conn.execute(
            """
            INSERT INTO simulation_clock (
                id, mode, simulated_seconds_per_wall_second,
                checkpoint_simulated_at_utc, checkpoint_wall_at_utc
            ) VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                checkpoint_simulated_at_utc = excluded.checkpoint_simulated_at_utc,
                checkpoint_wall_at_utc = excluded.checkpoint_wall_at_utc
            """,
            (
                state.mode.value,
                state.simulated_seconds_per_wall_second,
                new_simulated.isoformat(),
                wall_now.isoformat(),
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return new_simulated


def set_mode(
    conn: sqlite3.Connection,
    mode: ClockMode,
    *,
    simulated_seconds_per_wall_second: float | None = None,
) -> SimulationClockState:
    """Change the clock mode, re-anchoring the checkpoint to the current
    simulated time first so switching modes never causes a jump."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        wall_now = datetime.now(timezone.utc)
        state = get_state(conn)
        current_simulated = now(conn, wall_now=wall_now)
        rate_param = (
            simulated_seconds_per_wall_second
            if simulated_seconds_per_wall_second is not None
            else state.simulated_seconds_per_wall_second
        )
        conn.execute(
            """
            INSERT INTO simulation_clock (
                id, mode, simulated_seconds_per_wall_second,
                checkpoint_simulated_at_utc, checkpoint_wall_at_utc
            ) VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                mode = excluded.mode,
                simulated_seconds_per_wall_second = excluded.simulated_seconds_per_wall_second,
                checkpoint_simulated_at_utc = excluded.checkpoint_simulated_at_utc,
                checkpoint_wall_at_utc = excluded.checkpoint_wall_at_utc
            """,
            (
                mode.value,
                rate_param,
                current_simulated.isoformat(),
                wall_now.isoformat(),
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get_state(conn)


# --- epochs (SPEC.md §6.3; §9.2, §23.3 both count in them) -------------------
#
# An epoch is a fixed span of *simulated* time, which is why it lives here and
# not in scheduler.py where it was first written: §9.2's `max_births_per_epoch`
# is enforced on the birth paths and §23.3's metabolic alarm in the scheduler,
# and neither may import the other. `scheduler` re-exports these names, so
# there is one derivation rather than two that could disagree — the same reason
# balances are never cached (Charter C3).
#
# What stays in scheduler is `epoch_log`, the per-epoch *wall* anchor. That is
# about a tick having observed an epoch, not about what an epoch is.

#: One simulated day. Matches colony.yaml's accelerated rate of 86400 simulated
#: seconds per wall second, so at that rate an epoch is roughly a wall second —
#: fast enough for a flight simulator, and the unit §9.2's
#: `max_births_per_epoch` reads naturally against.
DEFAULT_EPOCH_DURATION_SECONDS = 86_400


def configure_epochs_if_absent(
    conn: sqlite3.Connection,
    *,
    genesis: datetime | None = None,
    duration_seconds: int = DEFAULT_EPOCH_DURATION_SECONDS,
) -> None:
    """Anchor epoch zero. Write-once, like every other colony config here — a
    genesis that moved would renumber history."""
    start = genesis or now(conn)
    if start.tzinfo is None:
        raise ClockError("genesis must be timezone-aware UTC (Charter C11)")
    conn.execute(
        "INSERT OR IGNORE INTO epoch_config (id, genesis_simulated_at_utc, epoch_duration_seconds) "
        "VALUES (1, ?, ?)",
        (start.astimezone(timezone.utc).isoformat(), duration_seconds),
    )


def epochs_configured(conn: sqlite3.Connection) -> bool:
    """Whether epoch zero has been anchored.

    Worth asking separately, because the fallback below is silently
    *conservative* rather than absent: an unanchored colony reports epoch 0
    forever, so a per-epoch cap degrades into a lifetime total instead of
    quietly not applying. Erring toward restriction is the right direction, but
    a caller refusing something should be able to say which of the two it is.
    `mitosis init` anchors epochs, so this is only ever false for a colony
    built by driving the kernel directly.
    """
    return conn.execute("SELECT 1 FROM epoch_config WHERE id = 1").fetchone() is not None


def epoch_settings(conn: sqlite3.Connection) -> tuple[datetime, int]:
    row = conn.execute("SELECT * FROM epoch_config WHERE id = 1").fetchone()
    if row is None:
        return now(conn), DEFAULT_EPOCH_DURATION_SECONDS
    return (
        datetime.fromisoformat(row["genesis_simulated_at_utc"]),
        row["epoch_duration_seconds"],
    )


def current_epoch(conn: sqlite3.Connection) -> int:
    """Derived from the simulated clock, never stored (Charter C3's rule for
    balances, applied for the same reason: a cached counter and a clock that
    disagree get resolved in favour of whichever the reader consulted)."""
    genesis, duration = epoch_settings(conn)
    elapsed = (now(conn) - genesis).total_seconds()
    return max(0, int(elapsed // duration))
