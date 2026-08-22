"""Population control and carrying capacity (SPEC.md §9; Charter C9: birth
requires carrying-capacity permission).

This module enforces the two population-size limits, `max_living_cells` and
`max_active_cells`, which apply to every birth by either path.
`max_lineage_population_fraction` is enforced too, but it lives in
lineage.py (`check_lineage_licence`) since it only has meaning for a birth
with a parent — see that module on how lineage is defined.
`max_births_per_epoch` is enforced here as of the §9.2 slice, against the
epoch primitive in clock.py. §9.2's one remaining limit —
max_parallel_experiments — is stored (so colony_config matches colony.yaml's
shape) but not yet checked: experiment tracking does not exist in this kernel.

**The per-epoch cap is checked before the capacity check and can never reach
the displacer**, because the two refusals mean opposite things — see
`BirthRateExceededError`. This is the one ordering constraint in this module
that a reader would not guess, and getting it wrong turns a wait into a
death.

Amendment A2 (displacement is objective-only, docs/DECISIONS.md ADR-009) is
implemented as of the §9.3 slice, but *not* here: `Displacer` below is the
seam, and `displacement.ObjectiveDisplacer` is the implementation, so
nothing in this module imports `death` or knows what an objective criterion
is. The dependency has to run that way round — `lifecycle` imports
`population`, and `death` imports `lifecycle` — and it is also the right
shape: carrying capacity is a counting problem, and which Cell is failing
is not.

**`Displacer` deliberately cannot see the proposed child.** §9.3 and
ADR-009 both say a child's *forecast* may never trigger a kill, and the
cheapest way to guarantee that is a signature carrying no information about
the child at all — not its genome, not its budget, not its forecast. The
birth records which Cell it displaced (see `lifecycle.create_cell`), so the
link is auditable in both directions without the selection ever depending
on it.

Displacement is **opt-in**: a caller with no `displacer` gets the old
behaviour, denial. §9.3 says a birth that cannot be licensed "waits"; a
synchronous kernel call can't wait, so it raises — and a caller must say
explicitly that it would rather evict than wait, because eviction is a
death and a death is irreversible.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Protocol

from . import clock
from .models import DEFAULT_POPULATION_LIMITS, CellStatus, PopulationLimits


class PopulationError(Exception):
    pass


class CarryingCapacityError(PopulationError):
    pass


class BirthRateExceededError(PopulationError):
    """§9.2's `max_births_per_epoch`, breached.

    **Deliberately not a subclass of `CarryingCapacityError`**, and that is the
    whole point of it existing. The two refusals look identical to a caller and
    mean opposite things:

        CarryingCapacityError   the colony has no slot. Durable — it stays true
                                until a Cell dies, which is why §9.3 lets a
                                birth displace one to make room.
        BirthRateExceededError  the colony has slots and has used its births
                                for this epoch. Temporary — it clears by itself
                                when the epoch turns, with nothing dying.

    If this inherited from the other, every existing `except
    CarryingCapacityError` would treat a rate limit as a structural shortage,
    and the displacement path would kill a Cell to get around a wait. §9.3
    licenses displacement for "an available population slot", and §10.5 requires
    deaths to be objective — a death caused by impatience is neither.
    """


@dataclass(frozen=True)
class Displacement:
    """One Cell evicted to make room for a birth (§9.3).

    `criterion`/`evidence` are the *objective* grounds that made the Cell
    eligible, carried back so the birth can record them — a displacement is
    only ever a consequence of the target's own realised record.
    """

    cell_id: str
    criterion: str
    evidence: dict[str, object] = field(default_factory=dict)

    def describe(self) -> str:
        return f"displacement: {self.criterion}: {self.evidence}"


class Displacer(Protocol):
    """The §9.3 seam. Note what is absent: every parameter describes the
    *colony*, none describes the child. See the module docstring."""

    def displace(
        self,
        conn: sqlite3.Connection,
        *,
        require_active: bool,
        exclude: frozenset[str],
    ) -> Displacement | None: ...


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


def births_in_epoch(conn: sqlite3.Connection, epoch_number: int) -> int:
    """How many Cells were born in `epoch_number`, by either birth path.

    Exact match on `born_in_epoch`, so Cells born before that column existed
    (NULL) count toward no epoch — see migration 0017 on why they are not
    backfilled into epoch 0.

    Dead Cells still count. A birth that happened, happened: §9.1's concern is
    the *rate* at which the colony spawns work — "Cells, events, model calls,
    experiments, records, audit workload" — and none of that is undone by the
    Cell later dying. Counting only the living would let a colony churn through
    unlimited births per epoch as long as it killed them fast enough.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cells WHERE born_in_epoch = ?", (epoch_number,)
    ).fetchone()
    return row["n"]


def _check_birth_rate(conn: sqlite3.Connection, limits: PopulationLimits) -> int:
    """§9.2's per-epoch birth cap. Returns the epoch the birth belongs to.

    Called **before** the carrying-capacity check and before any displacer is
    consulted, which is a deliberate ordering: a rate limit must never be able
    to reach the code that kills a Cell. See `BirthRateExceededError`.
    """
    epoch = clock.current_epoch(conn)
    born = births_in_epoch(conn, epoch)
    if born >= limits.max_births_per_epoch:
        unanchored = (
            ""
            if clock.epochs_configured(conn)
            else " This colony has never anchored epoch zero, so every birth lands "
            "in epoch 0 and the cap is behaving as a lifetime total — "
            "`mitosis init` anchors it."
        )
        raise BirthRateExceededError(
            f"birth denied: {born}/{limits.max_births_per_epoch} births already in "
            f"epoch {epoch} (SPEC.md §9.2). The colony is not out of room — this "
            f"clears when the epoch turns, and nothing needs to die for it to."
            f"{unanchored}"
        )
    return epoch


def _binding_caps(conn: sqlite3.Connection, limits: PopulationLimits) -> tuple[str, ...]:
    """Which population caps a birth would breach right now.

    A birth inserts an `alive` Cell, so it consumes one living slot *and*
    one active slot; both are checked. Which cap binds decides what a
    displacement has to free: only killing an `alive` Cell frees an active
    slot, whereas any living Cell (alive/dormant/quarantined) frees a living
    one. Evicting a dormant Cell to relieve an active-cap breach would be a
    death that bought nothing.
    """
    breached = []
    if living_count(conn) >= limits.max_living_cells:
        breached.append("living")
    if active_count(conn) >= limits.max_active_cells:
        breached.append("active")
    return tuple(breached)


def _capacity_error(conn: sqlite3.Connection, limits: PopulationLimits, suffix: str = "") -> str:
    return (
        f"birth denied: colony at capacity "
        f"({living_count(conn)}/{limits.max_living_cells} living, "
        f"{active_count(conn)}/{limits.max_active_cells} active){suffix}"
    )


def check_birth_licence(
    conn: sqlite3.Connection,
    limits: PopulationLimits | None = None,
    *,
    displacer: Displacer | None = None,
    exclude: frozenset[str] = frozenset(),
) -> Displacement | None:
    """Raise CarryingCapacityError if birth would exceed configured limits,
    unless a `displacer` can free a slot per §9.3.

    Must be called after the caller has already acquired a write lock
    (BEGIN IMMEDIATE) so the count-then-insert is atomic under concurrency
    (Charter C9's "under concurrency" spirit, same pattern as the C5
    real-spend cap check) — otherwise two concurrent births could both pass
    this check before either commits. Displacement inherits that lock: the
    eviction and the birth commit together or not at all.

    Returns the Displacement if one was performed, else None. **At most one
    Cell is ever evicted per birth**, and the caps are re-checked afterwards
    rather than assumed relieved — so a displacer that frees the wrong kind
    of slot (or none) degrades to a denied birth, never to a second kill.
    """
    limits = limits or get_limits(conn)

    # §9.2's per-epoch rate, first and never displaceable. A birth refused here
    # is waiting, not competing for a slot — reaching the displacer below would
    # turn "come back next epoch" into a death.
    _check_birth_rate(conn, limits)

    breached = _binding_caps(conn, limits)
    if not breached:
        return None

    if displacer is None:
        raise CarryingCapacityError(_capacity_error(conn, limits))

    displaced = displacer.displace(
        conn, require_active="active" in breached, exclude=exclude
    )
    if displaced is None:
        # §9.3: "If no objectively-failing Cell exists and the colony is at
        # capacity, the birth waits." A synchronous call cannot wait.
        raise CarryingCapacityError(
            _capacity_error(
                conn,
                limits,
                " and no Cell is objectively failing, so none may be displaced "
                "(SPEC.md §9.3 / ADR-009) — the birth waits",
            )
        )

    still_breached = _binding_caps(conn, limits)
    if still_breached:
        raise CarryingCapacityError(
            _capacity_error(
                conn,
                limits,
                f" — displacing {displaced.cell_id} did not free a slot for "
                f"{'/'.join(still_breached)}",
            )
        )
    return displaced
