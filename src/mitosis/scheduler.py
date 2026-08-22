"""The scheduler: epochs, and the guards that make unattended running safe
(SPEC.md §6.3, §17.2, §23.3, §27.1; Amendment A19).

Until now every Cell had to be woken by hand. This is what wakes them — and
most of what follows is refusals, because that is what the spec spends its
words on. §23.3 exists because the failure mode of automation is not a bad
decision, it is **four hundred quiet ones overnight**.

**A tick is one epoch's worth of work.** Cadence is not a parameter the caller
tunes: each living, funded, alive Cell gets **exactly one wake per epoch**, and
that is enforced structurally rather than by arithmetic — the wake's dedupe key
is `epoch:{n}:cell:{id}`, and `events.enqueue` is idempotent on dedupe keys. So
ticking twice inside one epoch is a no-op, a crashed tick resumes cleanly, and
running the scheduler from cron every minute costs nothing until the epoch
turns over. The cadence *is* the idempotency key.

**Three guards, each from a normative clause, checked before any Cell is
woken:**

- **`real_spending` (§27.1 `autonomy:`)** — the spec ships this **false**. An
  unattended scheduler is therefore free-provider-only until an operator
  deliberately enables paid spend. This is the one guard that is a plain
  configuration default rather than a judgement, and it is also the one that
  makes the other two survivable: with a free provider the worst case is wasted
  local compute.
- **Vacation mode (§23.3)** — "when the operator is unresponsive past a
  threshold, external-facing phases auto-pause (fail-safe), while sim-only work
  may continue." That maps exactly onto the provider split: a paid provider is
  external-facing, mock and Ollama are not. So an absent operator does not stop
  the colony thinking; it stops the colony *spending*.
- **The metabolic alarm (§23.3)** — "track real cents spent per sim-epoch (and
  per wall-hour); an acceleration in the burn rate raises an alarm **even if
  every individual cap is satisfied**." The emphasis is the whole design: this
  is not another cap, because caps already exist and did not catch the case
  §23.3 is worried about. It watches the derivative. See `metabolic_status`.

**What "raises an alarm" is taken to mean here.** §23.3 says alarm, not halt.
But an alarm nothing acts on is a log line, and this is the module that runs
while nobody is watching — so a fired alarm halts the scheduler and **stays
fired until an operator acknowledges it**. Self-clearing on the next tick would
reduce the guard to a comment. It halts *scheduling* only: no Cell is killed,
no reservation is touched, the breaker is untouched, and a human can still run
`mitosis wake` by hand.

Deliberately out of scope, and logged: §23's approval queue and its SLAs (there
is no queue yet, so `approval_sla_seconds` has nothing to time);
`max_births_per_epoch`, which this module's epoch primitive finally makes
checkable but which belongs with the birth paths; and a long-running daemon —
`tick` is a command, composable with cron, per §30.1's "avoid unnecessary
frameworks".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import (
    approval,
    audit,
    clock,
    deliberation,
    ids,
    ledger,
    lifecycle,
    providers,
    real_spend_breaker,
)
from .accounts import cell_cash
from .models import Book, Cell, CellStatus

#: One simulated day. Matches colony.yaml's accelerated rate of 86400 simulated
#: seconds per wall second, so at that rate an epoch is roughly a wall second —
#: fast enough for a flight simulator, and the unit §9.2's
#: `max_births_per_epoch` reads naturally against.
DEFAULT_EPOCH_DURATION_SECONDS = 86_400

#: How many prior epochs form the baseline the alarm compares against. Short on
#: purpose: a long window lets a slow, sustained ramp become the new normal,
#: which is the acceleration §23.3 is asking us to notice.
METABOLIC_BASELINE_EPOCHS = 5

#: Providers that reach outside the colony and can bill. Vacation mode and the
#: `real_spending` flag gate exactly these.
PAID_PROVIDERS = frozenset({providers.ANTHROPIC_PROVIDER})


class SchedulerError(Exception):
    pass


class TickOutcome:
    RAN = "ran"
    IDLE = "idle"
    HALTED_METABOLIC = "halted_metabolic"
    HALTED_VACATION = "halted_vacation"
    HALTED_AUTONOMY = "halted_autonomy"


@dataclass(frozen=True)
class OperatorState:
    last_heartbeat_utc: datetime
    vacation_pause_after_seconds: int
    metabolic_alarm_cents_per_epoch: int
    metabolic_acceleration_factor: float
    real_spending_enabled: bool
    metabolic_alarm_at_utc: datetime | None
    metabolic_alarm_reason: str | None

    @property
    def alarm_active(self) -> bool:
        return self.metabolic_alarm_at_utc is not None


@dataclass(frozen=True)
class TickResult:
    tick_id: str
    epoch_number: int
    outcome: str
    detail: str | None
    cells_woken: int
    deliberations: tuple = field(default=())

    @property
    def halted(self) -> bool:
        return self.outcome.startswith("halted_")


# --- epochs ------------------------------------------------------------------


def configure_epochs_if_absent(
    conn: sqlite3.Connection,
    *,
    genesis: datetime | None = None,
    duration_seconds: int = DEFAULT_EPOCH_DURATION_SECONDS,
) -> None:
    """Anchor epoch zero. Write-once, like every other colony config here — a
    genesis that moved would renumber history."""
    start = genesis or clock.now(conn)
    if start.tzinfo is None:
        raise SchedulerError("genesis must be timezone-aware UTC (Charter C11)")
    conn.execute(
        "INSERT OR IGNORE INTO epoch_config (id, genesis_simulated_at_utc, epoch_duration_seconds) "
        "VALUES (1, ?, ?)",
        (start.astimezone(timezone.utc).isoformat(), duration_seconds),
    )


def epoch_settings(conn: sqlite3.Connection) -> tuple[datetime, int]:
    row = conn.execute("SELECT * FROM epoch_config WHERE id = 1").fetchone()
    if row is None:
        return clock.now(conn), DEFAULT_EPOCH_DURATION_SECONDS
    return (
        datetime.fromisoformat(row["genesis_simulated_at_utc"]),
        row["epoch_duration_seconds"],
    )


def current_epoch(conn: sqlite3.Connection) -> int:
    """Derived from the simulated clock, never stored (Charter C3's rule for
    balances, applied for the same reason)."""
    genesis, duration = epoch_settings(conn)
    elapsed = (clock.now(conn) - genesis).total_seconds()
    return max(0, int(elapsed // duration))


def _record_epoch_start_locked(conn: sqlite3.Connection, epoch_number: int) -> datetime:
    """Record when this epoch was first *observed*, in both clocks.

    This is §6.3's "explicit conversion metadata" in its most literal form, and
    it is load-bearing rather than decorative: ledger rows are stamped in wall
    time while epochs are simulated, so without a recorded wall anchor per
    epoch there is no way to ask "what did we spend this epoch" at all.
    """
    row = conn.execute(
        "SELECT started_at_wall_utc FROM epoch_log WHERE epoch_number = ?", (epoch_number,)
    ).fetchone()
    if row is not None:
        return datetime.fromisoformat(row["started_at_wall_utc"])

    wall_now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO epoch_log (epoch_number, started_at_wall_utc, started_at_simulated_utc) "
        "VALUES (?, ?, ?)",
        (epoch_number, wall_now.isoformat(), clock.now(conn).isoformat()),
    )
    return wall_now


def epoch_started_at_wall(conn: sqlite3.Connection, epoch_number: int) -> datetime | None:
    row = conn.execute(
        "SELECT started_at_wall_utc FROM epoch_log WHERE epoch_number = ?", (epoch_number,)
    ).fetchone()
    return datetime.fromisoformat(row["started_at_wall_utc"]) if row else None


# --- operator state (§23.3, A19) ---------------------------------------------


def _row_to_operator(row: sqlite3.Row) -> OperatorState:
    return OperatorState(
        last_heartbeat_utc=datetime.fromisoformat(row["last_heartbeat_utc"]),
        vacation_pause_after_seconds=row["vacation_pause_after_seconds"],
        metabolic_alarm_cents_per_epoch=row["metabolic_alarm_cents_per_epoch"],
        metabolic_acceleration_factor=row["metabolic_acceleration_factor"],
        real_spending_enabled=bool(row["real_spending_enabled"]),
        metabolic_alarm_at_utc=(
            datetime.fromisoformat(row["metabolic_alarm_at_utc"])
            if row["metabolic_alarm_at_utc"]
            else None
        ),
        metabolic_alarm_reason=row["metabolic_alarm_reason"],
    )


def operator_state(conn: sqlite3.Connection) -> OperatorState:
    row = conn.execute("SELECT * FROM operator_state WHERE id = 1").fetchone()
    if row is not None:
        return _row_to_operator(row)
    # Unconfigured reads as "operator absent since the epoch", i.e. vacation
    # mode active and real spending off. Failing safe on an absent config is
    # the whole point of a fail-safe (§23.3).
    return OperatorState(
        last_heartbeat_utc=datetime(1970, 1, 1, tzinfo=timezone.utc),
        vacation_pause_after_seconds=172_800,
        metabolic_alarm_cents_per_epoch=50,
        metabolic_acceleration_factor=3.0,
        real_spending_enabled=False,
        metabolic_alarm_at_utc=None,
        metabolic_alarm_reason=None,
    )


def initialize_operator_if_absent(conn: sqlite3.Connection) -> OperatorState:
    conn.execute(
        "INSERT OR IGNORE INTO operator_state (id, last_heartbeat_utc) VALUES (1, ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    return operator_state(conn)


def heartbeat(conn: sqlite3.Connection) -> OperatorState:
    """The operator is present. Clears vacation mode; deliberately does **not**
    clear a metabolic alarm — being back at the keyboard is not the same as
    having looked at why the colony was burning money."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        initialize_operator_if_absent(conn)
        conn.execute(
            "UPDATE operator_state SET last_heartbeat_utc = ? WHERE id = 1",
            (datetime.now(timezone.utc).isoformat(),),
        )
        audit.record(conn, event_type="operator_heartbeat", description="operator present")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return operator_state(conn)


def set_real_spending(conn: sqlite3.Connection, enabled: bool) -> OperatorState:
    """§27.1 `autonomy.real_spending`. Always audited, in both directions:
    enabling unattended real spend is the single most consequential switch in
    this kernel, and disabling it matters just as much for reconstructing why
    a colony went quiet."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        initialize_operator_if_absent(conn)
        conn.execute(
            "UPDATE operator_state SET real_spending_enabled = ? WHERE id = 1",
            (1 if enabled else 0,),
        )
        audit.record(
            conn,
            event_type="autonomy_real_spending_changed",
            description=f"real_spending_enabled -> {enabled}",
            metadata={"enabled": enabled},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return operator_state(conn)


def acknowledge_metabolic_alarm(conn: sqlite3.Connection, *, note: str) -> OperatorState:
    """Clear a fired alarm. Requires a note for the same reason
    `death.kill_for_negative_ev` requires evidence: an acknowledgement with no
    stated reason is a click, and the next one will be too."""
    if not note.strip():
        raise SchedulerError(
            "a note is required — acknowledging an alarm without saying why it "
            "was safe to clear is how the alarm stops meaning anything"
        )
    conn.execute("BEGIN IMMEDIATE")
    try:
        state = operator_state(conn)
        if not state.alarm_active:
            raise SchedulerError("no metabolic alarm is active")
        initialize_operator_if_absent(conn)
        conn.execute(
            "UPDATE operator_state SET metabolic_alarm_at_utc = NULL, "
            "metabolic_alarm_reason = NULL WHERE id = 1"
        )
        audit.record(
            conn,
            event_type="metabolic_alarm_acknowledged",
            description=note.strip(),
            metadata={"cleared_reason": state.metabolic_alarm_reason},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return operator_state(conn)


def _raise_metabolic_alarm_locked(conn: sqlite3.Connection, reason: str) -> None:
    initialize_operator_if_absent(conn)
    conn.execute(
        "UPDATE operator_state SET metabolic_alarm_at_utc = ?, metabolic_alarm_reason = ? "
        "WHERE id = 1",
        (datetime.now(timezone.utc).isoformat(), reason),
    )
    audit.record(conn, event_type="metabolic_alarm_raised", description=reason)


# --- the metabolic alarm (§23.3) ---------------------------------------------


def epoch_spend_minor_units(conn: sqlite3.Connection, epoch_number: int) -> int:
    """Real cents settled during `epoch_number`, via its recorded wall anchor.

    Returns 0 for an epoch never observed by a tick — correctly: if no tick ran
    in it, the scheduler caused no spend in it, and spend a human caused by
    hand is not what §23.3's automation guard is measuring.
    """
    start = epoch_started_at_wall(conn, epoch_number)
    if start is None:
        return 0
    end = epoch_started_at_wall(conn, epoch_number + 1)
    total = real_spend_breaker._settled_spend_since(conn, start)
    if end is not None:
        total -= real_spend_breaker._settled_spend_since(conn, end)
    return total


def metabolic_status(conn: sqlite3.Connection, epoch_number: int | None = None) -> dict:
    """§23.3's two readings: spend per sim-epoch and per wall-hour, plus the
    acceleration against a recent baseline.

    The baseline deliberately excludes the current epoch (it is what is being
    judged) and any epoch with no spend at all (a colony that was idle then
    burning is not accelerating, it is starting — and a zero baseline would
    make every first spend an infinite acceleration).
    """
    epoch_number = current_epoch(conn) if epoch_number is None else epoch_number
    state = operator_state(conn)

    this_epoch = epoch_spend_minor_units(conn, epoch_number)
    prior = [
        epoch_spend_minor_units(conn, n)
        for n in range(max(0, epoch_number - METABOLIC_BASELINE_EPOCHS), epoch_number)
    ]
    spending_prior = [p for p in prior if p > 0]
    baseline = (sum(spending_prior) / len(spending_prior)) if spending_prior else None
    acceleration = (this_epoch / baseline) if baseline else None

    last_hour = real_spend_breaker._settled_spend_since(
        conn, datetime.now(timezone.utc) - timedelta(hours=1)
    )

    breached = []
    if this_epoch > state.metabolic_alarm_cents_per_epoch:
        breached.append(
            f"epoch {epoch_number} spent {this_epoch} minor units, above "
            f"metabolic_alarm_cents_per_epoch={state.metabolic_alarm_cents_per_epoch}"
        )
    if acceleration is not None and acceleration > state.metabolic_acceleration_factor:
        breached.append(
            f"epoch {epoch_number} burn rate is {acceleration:.1f}x the recent "
            f"baseline of {baseline:.1f}, above "
            f"metabolic_acceleration_factor={state.metabolic_acceleration_factor} "
            "(every individual cap may still be satisfied — §23.3)"
        )

    return {
        "epoch": epoch_number,
        "spend_this_epoch_minor_units": this_epoch,
        "spend_last_wall_hour_minor_units": last_hour,
        "baseline_minor_units": baseline,
        "acceleration": acceleration,
        "breached": breached,
        "alarm_active": state.alarm_active,
        "alarm_reason": state.metabolic_alarm_reason,
    }


def is_on_vacation(conn: sqlite3.Connection, *, now: datetime | None = None) -> bool:
    state = operator_state(conn)
    now = now or datetime.now(timezone.utc)
    elapsed = (now - state.last_heartbeat_utc).total_seconds()
    return elapsed > state.vacation_pause_after_seconds


# --- the tick ----------------------------------------------------------------


def eligible_cells(conn: sqlite3.Connection, epoch_number: int) -> list[Cell]:
    """Cells that should be woken this epoch.

    `alive` only — a dormant Cell is woken by a *delivered event* (§17.2), not
    by the passage of time, and quarantined/dead are excluded by §18.2 and
    Charter C8. Unfunded Cells are skipped rather than woken-and-refused: a
    refusal is worth recording when someone asked for it, but an automated
    scheduler generating one per epoch per broke Cell is noise that would bury
    the refusals that matter.
    """
    rows = conn.execute(
        "SELECT cell_id FROM cells WHERE status = ? ORDER BY rowid", (CellStatus.ALIVE.value,)
    ).fetchall()
    eligible = []
    for row in rows:
        cell = lifecycle.get_cell(conn, row["cell_id"])
        if cell is None:
            continue
        if any(
            ledger.get_balance(conn, cell_cash(cell.cell_id), book) < 1
            for book in (Book.USD_REAL, Book.RESOURCE)
        ):
            continue
        eligible.append(cell)
    return eligible


def _guard(conn: sqlite3.Connection, *, provider_name: str) -> tuple[str, str] | None:
    """The three §23.3/§27.1 checks, in increasing order of how bad it would be
    to get them wrong. Returns (outcome, detail) if the tick must not run."""
    is_paid = provider_name in PAID_PROVIDERS
    state = operator_state(conn)

    if state.alarm_active:
        return (
            TickOutcome.HALTED_METABOLIC,
            f"metabolic alarm active since {state.metabolic_alarm_at_utc}: "
            f"{state.metabolic_alarm_reason}. Acknowledge it to resume.",
        )

    if is_paid and not state.real_spending_enabled:
        return (
            TickOutcome.HALTED_AUTONOMY,
            f"provider {provider_name!r} spends real money and "
            "autonomy.real_spending is disabled (SPEC.md §27.1 ships it false)",
        )

    if is_paid and is_on_vacation(conn):
        return (
            TickOutcome.HALTED_VACATION,
            f"operator last seen {state.last_heartbeat_utc.isoformat()}, beyond "
            f"vacation_pause_after_seconds={state.vacation_pause_after_seconds} — "
            "external-facing work auto-paused (§23.3). Free providers still run.",
        )

    return None


def tick(
    conn: sqlite3.Connection,
    *,
    provider: providers.ModelProvider,
    model: str,
    max_cells: int | None = None,
) -> TickResult:
    """Run one epoch's scheduled wakes, if the guards allow it.

    Idempotent per epoch by construction: wake dedupe keys are
    `epoch:{n}:cell:{id}`, so a second tick in the same epoch enqueues nothing
    new and drains an already-empty queue. Safe to run from cron as often as
    you like.
    """
    epoch_number = current_epoch(conn)
    tick_id = ids.new_id()
    started = datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        _record_epoch_start_locked(conn, epoch_number)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    spend_before = real_spend_breaker._settled_spend_since(conn, datetime(1970, 1, 1, tzinfo=timezone.utc))

    halt = _guard(conn, provider_name=provider.name)
    if halt is not None:
        outcome, detail = halt
        _record_tick(
            conn, tick_id=tick_id, epoch_number=epoch_number, started=started,
            provider=provider.name, outcome=outcome, detail=detail,
            cells_woken=0, spend_before=spend_before, spend_after=spend_before,
        )
        return TickResult(tick_id, epoch_number, outcome, detail, 0)

    cells = eligible_cells(conn, epoch_number)
    if max_cells is not None:
        cells = cells[:max_cells]

    if not cells:
        _record_tick(
            conn, tick_id=tick_id, epoch_number=epoch_number, started=started,
            provider=provider.name, outcome=TickOutcome.IDLE,
            detail="no alive, funded Cell was eligible",
            cells_woken=0, spend_before=spend_before, spend_after=spend_before,
        )
        return TickResult(tick_id, epoch_number, TickOutcome.IDLE,
                          "no alive, funded Cell was eligible", 0)

    for cell in cells:
        deliberation.enqueue_wake(
            conn,
            cell_id=cell.cell_id,
            wake_reason=deliberation.WAKE_SCHEDULED_RESEARCH,
            # The cadence policy *is* this key: one wake per Cell per epoch,
            # enforced by enqueue's dedupe rather than by counting.
            dedupe_key=f"epoch:{epoch_number}:cell:{cell.cell_id}",
        )

    # §23. An unattended tick is precisely the case the queue exists for: nobody
    # is watching the proposals appear, so each one is routed to review as it is
    # recorded rather than waiting for someone to think to look.
    results = deliberation.run_ready_wakes(
        conn, provider=provider, model=model, proposal_sink=approval.QueueSink()
    )

    spend_after = real_spend_breaker._settled_spend_since(conn, datetime(1970, 1, 1, tzinfo=timezone.utc))

    # Checked *after* the wakes, not before: the alarm's job is to stop the
    # *next* tick, and it cannot know what this one cost until it has run. The
    # per-request/hour/day caps are what bound damage inside a single tick, and
    # §23.3 is explicit that this fires even when those are all satisfied.
    status = metabolic_status(conn, epoch_number)
    if status["breached"]:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _raise_metabolic_alarm_locked(conn, "; ".join(status["breached"]))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    _record_tick(
        conn, tick_id=tick_id, epoch_number=epoch_number, started=started,
        provider=provider.name, outcome=TickOutcome.RAN,
        detail=f"{len(results)} deliberation(s)",
        cells_woken=len(results), spend_before=spend_before, spend_after=spend_after,
    )
    return TickResult(
        tick_id, epoch_number, TickOutcome.RAN, f"{len(results)} deliberation(s)",
        len(results), tuple(results),
    )


def _record_tick(
    conn: sqlite3.Connection,
    *,
    tick_id: str,
    epoch_number: int,
    started: datetime,
    provider: str,
    outcome: str,
    detail: str | None,
    cells_woken: int,
    spend_before: int,
    spend_after: int,
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO scheduler_ticks (
                tick_id, epoch_number, started_at_utc, provider, is_paid,
                outcome, detail, cells_woken, spend_before_minor, spend_after_minor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tick_id, epoch_number, started.isoformat(), provider,
                1 if provider in PAID_PROVIDERS else 0,
                outcome, detail, cells_woken, spend_before, spend_after,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def recent_ticks(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM scheduler_ticks ORDER BY rowid DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]
