"""Structured data for the ledger and reservation kernel (SPEC.md §3, §4).

Pydantic models per §30.1 coding rule ("Pydantic for structured data").
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class Book(StrEnum):
    USD_REAL = "USD_REAL"
    USD_SIM = "USD_SIM"
    RESOURCE = "RESOURCE"


class ReservationStatus(StrEnum):
    """Canonical reservation FSM (SPEC.md §4.4, Amendment A4;
    docs/STATE_MACHINES.md §2)."""

    REQUESTED = "requested"
    RESERVED = "reserved"
    EXECUTION_UNKNOWN = "execution_unknown"
    PARTIALLY_SETTLED = "partially_settled"
    SETTLED = "settled"
    RELEASED = "released"
    DISPUTED = "disputed"


TERMINAL_RESERVATION_STATUSES = frozenset(
    {ReservationStatus.SETTLED, ReservationStatus.RELEASED}
)


class CellType(StrEnum):
    """The Explorer/Builder/Commercial/Auditor/Immune/Skeptic taxonomy."""

    EXPLORER = "explorer"
    BUILDER = "builder"
    COMMERCIAL = "commercial"
    AUDITOR = "auditor"
    IMMUNE = "immune"
    SKEPTIC = "skeptic"


class CellStatus(StrEnum):
    """Cell lifecycle FSM (docs/STATE_MACHINES.md §1)."""

    CREATED = "created"
    ALIVE = "alive"
    DORMANT = "dormant"
    QUARANTINED = "quarantined"
    DEAD = "dead"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class EntrySpec(BaseModel):
    """Caller-supplied entry, before entry_id/transaction_id are assigned."""

    account_id: str
    amount_minor_units: int
    cell_id: str | None = None
    team_id: str | None = None
    experiment_id: str | None = None
    artifact_id: str | None = None
    metadata: dict[str, Any] = {}


class Entry(_Frozen):
    """One leg of a ledger transaction (SPEC.md §3.3, Amendment A3).

    Carries a single signed amount — there is no independent `direction`
    field (docs/DECISIONS.md ADR-003).
    """

    entry_id: str
    transaction_id: str
    account_id: str
    amount_minor_units: int
    cell_id: str | None = None
    team_id: str | None = None
    experiment_id: str | None = None
    artifact_id: str | None = None
    metadata: dict[str, Any] = {}


class Transaction(_Frozen):
    """SPEC.md §3.2. One balanced, single-book unit of the ledger."""

    transaction_id: str
    book: Book
    currency: str
    created_at_utc: datetime
    effective_at_utc: datetime
    idempotency_key: str
    event_id: str | None = None
    transaction_type: str
    description: str = ""
    previous_transaction_hash: str | None
    transaction_hash: str
    metadata: dict[str, Any] = {}
    entries: tuple[Entry, ...]

    @field_validator("created_at_utc", "effective_at_utc")
    @classmethod
    def _require_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware UTC (Charter C11)")
        return v.astimezone(timezone.utc)


class Reservation(_Frozen):
    """SPEC.md §4.2, §4.4."""

    reservation_id: str
    cell_id: str
    experiment_id: str | None = None
    book: Book
    currency: str
    maximum_amount: int
    settled_amount: int = 0
    reserved_at: datetime
    expires_at: datetime
    external_operation_type: str | None = None
    external_operation_id: str | None = None
    status: ReservationStatus
    idempotency_key: str


class CellGenome(_Frozen):
    """SPEC.md §16.2. Content-addressed: identical canonical_genome_json
    always yields the same genome_hash and the same row (dedup)."""

    genome_id: str
    genome_hash: str
    version: int
    parent_genome_hashes: tuple[str, ...] = ()
    created_at: datetime
    mutation_operator: str | None = None
    canonical_genome_json: dict[str, Any]
    prompt_hashes: tuple[str, ...] = ()
    module_hashes: tuple[str, ...] = ()
    model_policy_hash: str | None = None
    risk_label: str = "unclassified"
    taint_labels: tuple[str, ...] = ()


class Cell(_Frozen):
    """SPEC.md §31; lifecycle per docs/STATE_MACHINES.md §1."""

    cell_id: str
    cell_type: CellType
    genome_hash: str
    book: Book
    status: CellStatus
    created_at_utc: datetime
    idempotency_key: str


class AuditEvent(_Frozen):
    event_id: str
    event_type: str
    cell_id: str | None = None
    description: str = ""
    created_at_utc: datetime
    metadata: dict[str, Any] = {}


class PopulationLimits(_Frozen):
    """SPEC.md §9.2, §27.1 `colony.yaml` `population:` block.

    Only max_living_cells and max_active_cells are enforced in this kernel
    (see population.py). The rest are stored so the config shape matches
    colony.yaml exactly, but are not yet checked: max_parallel_experiments
    needs experiment tracking, max_births_per_epoch needs the simulated
    clock, and max_lineage_population_fraction needs reproduction/lineage
    tracking — none of which exist in the kernel yet.
    """

    max_living_cells: int
    max_active_cells: int
    max_parallel_experiments: int
    max_births_per_epoch: int
    max_lineage_population_fraction: float


DEFAULT_POPULATION_LIMITS = PopulationLimits(
    max_living_cells=1000,
    max_active_cells=100,
    max_parallel_experiments=20,
    max_births_per_epoch=25,
    max_lineage_population_fraction=0.20,
)


class RealSpendLimits(_Frozen):
    """SPEC.md §5.1, §27.1 `colony.yaml` `real_spend_limits:` block. USD_REAL
    only. provider_limits is stored so the config shape matches colony.yaml
    but is not enforced (see real_spend_breaker.py — no model gateway or
    provider identification exists in this kernel yet)."""

    per_request_minor_units: int
    per_hour_minor_units: int
    per_day_minor_units: int
    per_month_minor_units: int
    max_concurrent_reserved_minor_units: int
    provider_limits: dict[str, int] = {}


DEFAULT_REAL_SPEND_LIMITS = RealSpendLimits(
    per_request_minor_units=25,
    per_hour_minor_units=100,
    per_day_minor_units=500,
    per_month_minor_units=5000,
    max_concurrent_reserved_minor_units=200,
    provider_limits={},
)


class RealSpendSnapshot(_Frozen):
    """Current USD_REAL exposure at a point in time, for breaker checks and
    `mitosis status` display."""

    limits: RealSpendLimits
    concurrent_reserved_minor_units: int
    spend_last_hour_minor_units: int
    spend_last_day_minor_units: int
    spend_last_month_minor_units: int


class ClockMode(StrEnum):
    """SPEC.md §6.2."""

    PAUSED = "paused"
    STEP = "step"
    ACCELERATED = "accelerated"
    REALTIME = "realtime"


class SimulationClockState(_Frozen):
    """SPEC.md §6; §27.1 `colony.yaml` `simulation_clock:` block.

    checkpoint_simulated_at_utc / checkpoint_wall_at_utc together anchor a
    lazy time computation: current simulated time = checkpoint_simulated +
    (elapsed wall time since checkpoint_wall) * rate(mode). See clock.py.
    """

    mode: ClockMode
    simulated_seconds_per_wall_second: float
    checkpoint_simulated_at_utc: datetime
    checkpoint_wall_at_utc: datetime
