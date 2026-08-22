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
    provider: str | None = None
    """Set only on reservations created by the model gateway. The real-spend
    breaker sums per-provider exposure off this field to enforce §5.1's
    "max real spend per provider" cap."""


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
    """SPEC.md §31; lifecycle per docs/STATE_MACHINES.md §1.

    Lineage (SPEC.md §9.4, Amendment A10; ADR-019): `parent_cell_id` is NULL
    for a seeded founder and set for a Cell born via `lineage.reproduce`.
    `founder_cell_id` is the root of that parent chain (a founder is its own
    founder) and `generation` its depth — both immutable after birth and
    re-derivable via `lineage.verify_lineage_integrity`.
    """

    cell_id: str
    cell_type: CellType
    genome_hash: str
    book: Book
    status: CellStatus
    created_at_utc: datetime
    idempotency_key: str
    parent_cell_id: str | None = None
    founder_cell_id: str
    generation: int = 0


class AuditEvent(_Frozen):
    event_id: str
    event_type: str
    cell_id: str | None = None
    description: str = ""
    created_at_utc: datetime
    metadata: dict[str, Any] = {}


class CoronerReport(_Frozen):
    """The artifact filed on every Cell death (SPEC.md §10.5, Amendment A15;
    docs/STATE_MACHINES.md §1.4).

    `stage_reached` and `experiment_ids` are stored for shape parity with
    §10.5's field list but always None/empty in this kernel: stage
    progression and experiment tracking don't exist yet (same deferred-field
    pattern as PopulationLimits/RealSpendLimits).
    """

    report_id: str
    cell_id: str
    genome_hash: str
    spend_by_book: dict[str, int]
    stage_reached: str | None = None
    cause_of_death: str
    final_hypotheses: tuple[str, ...] = ()
    experiment_ids: tuple[str, ...] = ()
    created_at_utc: datetime


class ResourceType(StrEnum):
    """RESOURCE-book consumption categories (SPEC.md §2.2)."""

    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    MODEL_CALLS = "model_calls"
    CPU_SECONDS = "cpu_seconds"
    MEMORY_SECONDS = "memory_seconds"
    BROWSER_MINUTES = "browser_minutes"
    NETWORK_REQUESTS = "network_requests"
    STORAGE_BYTE_DAYS = "storage_byte_days"
    HUMAN_MINUTES = "human_minutes"
    APPROVAL_ACTIONS = "approval_actions"


class ResourceUsage(_Frozen):
    """One metered RESOURCE-book consumption event (SPEC.md §2.2/§2.3,
    Amendment A6). `quantity` is the physical unit count (e.g. 500 tokens);
    `minor_units` is what that consumption costs against the linked
    reservation's RESOURCE-book budget — resource_metering.py enforces the
    two never diverge from Charter C4 (a Cell cannot overspend its
    authorised budget)."""

    usage_id: str
    cell_id: str
    reservation_id: str
    resource_type: ResourceType
    quantity: int
    minor_units: int
    recorded_at_utc: datetime
    idempotency_key: str
    metadata: dict[str, Any] = {}


class ModelCallStatus(StrEnum):
    """Lifecycle of one gateway call. Mirrors the reservation FSM's shape
    where it matters: `execution_unknown` means the provider may or may not
    have billed us, so the funds stay committed until reconciliation (§4.4)."""

    RESERVED = "reserved"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXECUTION_UNKNOWN = "execution_unknown"


class ModelCall(_Frozen):
    """One model call and the metadata SPEC.md §24.1 requires.

    Costs are in micro-USD (1e-6 USD) rather than USD_REAL minor units —
    see pricing.py: a single call routinely costs a fraction of a cent, so
    the cent is too coarse to hold a per-call figure. `settled_minor_units`
    is the cent-rounded amount that actually moved on the ledger.

    `reconciled_micro_usd` is §24.1's `reconciled cost`: what the provider
    actually invoiced, as opposed to what the pricing table predicted. It
    stays None until an operator reconciles the call (reconciliation.py) —
    nothing fetches an invoice automatically. `reconciled_at_utc` is what
    distinguishes a reconciled call from an outstanding one; reconciliation
    is an accounting axis, not an execution outcome, so `status` is unchanged
    by it.
    """

    model_call_id: str
    cell_id: str
    experiment_id: str | None = None
    status: ModelCallStatus

    provider: str
    requested_model: str
    resolved_model: str | None = None
    api_version: str | None = None

    pricing_table_version: str
    system_prompt_hash: str | None = None
    user_prompt_hash: str
    tool_schema_hashes: tuple[str, ...] = ()

    parameters: dict[str, Any] = {}
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    response_hash: str | None = None
    stop_reason: str | None = None
    response_text: str | None = None

    cost_estimate_micro_usd: int = 0
    cost_actual_micro_usd: int | None = None
    reconciled_micro_usd: int | None = None
    reconciled_at_utc: datetime | None = None
    reconciliation_source: str | None = None
    settled_minor_units: int = 0

    real_reservation_id: str
    resource_reservation_id: str

    mirror_minor_units: int = 0
    mirror_skipped_reason: str | None = None

    error_text: str | None = None
    created_at_utc: datetime
    idempotency_key: str


class PopulationLimits(_Frozen):
    """SPEC.md §9.2, §27.1 `colony.yaml` `population:` block.

    max_living_cells, max_active_cells and max_births_per_epoch are enforced
    on every birth (population.py); max_lineage_population_fraction is
    enforced on every reproduction (lineage.py). max_parallel_experiments is
    stored so the config shape matches colony.yaml exactly, but is not yet
    checked: experiment tracking does not exist in the kernel.

    max_births_per_epoch is a **rate** limit and the only one here that
    clears by itself — see population.BirthRateExceededError on why it must
    never be confused with a carrying-capacity refusal.
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


class EventStatus(StrEnum):
    """Inbox event lifecycle (SPEC.md §17.3): pending -> processed, or
    pending -> dead_letter after too many failed attempts."""

    PENDING = "pending"
    PROCESSED = "processed"
    DEAD_LETTER = "dead_letter"


class Event(_Frozen):
    """One event_inbox row (SPEC.md §17.2, §3.5). Identity is event_id,
    stable across redelivery attempts — only attempt_number changes.
    `dedupe_key` is the producer-side idempotency guard (see events.py);
    `priority` is required per ADR-011 even though the illustrative §17.2
    schema block omits it."""

    event_id: str
    dedupe_key: str
    attempt_number: int = 0
    event_type: str
    source: str
    target: str | None = None
    priority: int
    created_at_utc: datetime
    available_at: datetime
    simulated_at: datetime | None = None
    payload: dict[str, Any] = {}
    status: EventStatus = EventStatus.PENDING
    last_error: str | None = None
    causation_id: str | None = None
    correlation_id: str | None = None


class OutboxEventSpec(BaseModel):
    """Caller-supplied event produced by a handler, staged into
    event_outbox before event_id is assigned — mirrors EntrySpec's
    relationship to Entry."""

    event_type: str
    source: str
    priority: int
    dedupe_key: str
    target: str | None = None
    payload: dict[str, Any] = {}
    available_at: datetime | None = None
    simulated_at: datetime | None = None
    correlation_id: str | None = None


class OutboxEvent(_Frozen):
    """One event_outbox row. `published_at_utc` is set once the outbox
    dispatcher has published it (docs/EVENT_SEMANTICS.md §3 step 7)."""

    event_id: str
    dedupe_key: str
    event_type: str
    source: str
    target: str | None = None
    priority: int
    created_at_utc: datetime
    available_at: datetime
    simulated_at: datetime | None = None
    payload: dict[str, Any] = {}
    causation_id: str | None = None
    correlation_id: str | None = None
    published_at_utc: datetime | None = None


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
