"""Population control and carrying capacity (SPEC.md §9; Charter C9: birth
requires carrying-capacity permission).

This module enforces the two population-size limits, `max_living_cells` and
`max_active_cells`, which apply to every birth by either path.
`max_lineage_population_fraction` is enforced too, but it lives in
lineage.py (`check_lineage_licence`) since it only has meaning for a birth
with a parent — see that module on how lineage is defined. §9.2's remaining
limits — max_parallel_experiments and max_births_per_epoch — are stored (so
colony_config matches colony.yaml's shape) but not yet checked, because
their prerequisites don't exist in this kernel yet: experiment tracking and
a clock wired into a real epoch counter respectively.

Amendment A2 (displacement is objective-only, docs/DECISIONS.md ADR-009) is
also not implemented here: displacing an already-failing Cell to make room
requires the §10.5 death criteria (stage budgets, validation gates,
reproducibility checks), none of which this kernel evaluates yet. So the
only two outcomes right now are "granted" or "denied" — there is no
displacement path. A denied birth is the conservative, spec-compliant
behaviour when displacement can't be evaluated: SPEC.md §9.3 says a birth
"waits" when at capacity with no valid displacement target; a synchronous
kernel call can't wait, so it raises instead.
"""

from __future__ import annotations

import sqlite3

from .models import DEFAULT_POPULATION_LIMITS, CellStatus, PopulationLimits


class PopulationError(Exception):
    pass


class CarryingCapacityError(PopulationError):
    pass


def set_limits_if_absent(conn: sqlite3.Connection, limits: PopulationLimits) -> PopulationLimits:
    """Configure colony_config on first init only. If a colony is already
    configured, later calls (e.g. re-running `mitosis init`) never change
    live carrying-capacity limits out from under a running colony — the
    existing configuration is returned unchanged."""
    conn.execute(
        """
        INSERT OR IGNORE INTO colony_config (
            id, max_living_cells, max_active_cells, max_parallel_experiments,
            max_births_per_epoch, max_lineage_population_fraction
        ) VALUES (1, ?, ?, ?, ?, ?)
        """,
        (
            limits.max_living_cells,
            limits.max_active_cells,
            limits.max_parallel_experiments,
            limits.max_births_per_epoch,
            limits.max_lineage_population_fraction,
        ),
    )
    return get_limits(conn)


def get_limits(conn: sqlite3.Connection) -> PopulationLimits:
    row = conn.execute("SELECT * FROM colony_config WHERE id = 1").fetchone()
    if row is None:
        return DEFAULT_POPULATION_LIMITS
    return PopulationLimits(
        max_living_cells=row["max_living_cells"],
        max_active_cells=row["max_active_cells"],
        max_parallel_experiments=row["max_parallel_experiments"],
        max_births_per_epoch=row["max_births_per_epoch"],
        max_lineage_population_fraction=row["max_lineage_population_fraction"],
    )


def living_count(conn: sqlite3.Connection) -> int:
    """Living = any lifecycle status except dead (alive, dormant, quarantined)."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cells WHERE status != ?", (CellStatus.DEAD.value,)
    ).fetchone()
    return row["n"]


def active_count(conn: sqlite3.Connection) -> int:
    """Active = alive only. Dormant is idle, quarantined is restricted —
    neither counts as active."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cells WHERE status = ?", (CellStatus.ALIVE.value,)
    ).fetchone()
    return row["n"]


def check_birth_licence(
    conn: sqlite3.Connection, limits: PopulationLimits | None = None
) -> None:
    """Raise CarryingCapacityError if birth would exceed configured limits.

    Must be called after the caller has already acquired a write lock
    (BEGIN IMMEDIATE) so the count-then-insert is atomic under concurrency
    (Charter C9's "under concurrency" spirit, same pattern as the C5
    real-spend cap check) — otherwise two concurrent births could both pass
    this check before either commits.
    """
    limits = limits or get_limits(conn)

    living = living_count(conn)
    if living >= limits.max_living_cells:
        raise CarryingCapacityError(
            f"birth denied: colony at capacity ({living}/{limits.max_living_cells} living cells)"
        )

    active = active_count(conn)
    if active >= limits.max_active_cells:
        raise CarryingCapacityError(
            f"birth denied: colony at capacity ({active}/{limits.max_active_cells} active cells)"
        )
