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

# Re-exported, not redefined: an epoch is a span of simulated time, so it lives
# in clock.py (§6). `population` enforces §9.2's per-epoch birth cap and cannot
# import this module, and two derivations of "which epoch is it" could disagree.
from .clock import (  # noqa: E402  (kept beside the other imports it belongs with)
    DEFAULT_EPOCH_DURATION_SECONDS,
    configure_epochs_if_absent,
    current_epoch,
    epoch_settings,
)

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
    #: Written *before* the work, so a tick that dies leaves a row (ADR-042).
    #: Borrowed from `tool_calls.status = 'requested'` (migration 0019), which
    #: solved the same problem one layer down.
    STARTED = "started"
    #: Raised and was caught. `detail` carries the redacted exception — a
    #: Charter C14 requirement, since a provider error can quote a key.
    CRASHED = "crashed"
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
    #: How often the operator's crontab actually runs `tick`. None means "one
    #: epoch" — see `liveness`, where the default is the policy.
    tick_expected_every_seconds: int | None = None

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
    #: §23.3's two expiry clocks, swept before the guards (ADR-040). Reported
    #: even on a halted tick, because the sweep runs on one.
    requests_expired: int = 0
    grants_expired: int = 0

    @property
    def halted(self) -> bool:
        return self.outcome.startswith("halted_")


# --- epochs ------------------------------------------------------------------


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
        tick_expected_every_seconds=row["tick_expected_every_seconds"],
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
    new and drains an already-empty queue. The expiry sweeps below are
    idempotent on their own terms (a request leaves PENDING, a grant gains
    `expired_at_utc`), so this stays true. Safe to run from cron as often as
    you like.
    """
    epoch_number = current_epoch(conn)
    tick_id = ids.new_id()
    started = datetime.now(timezone.utc)

    # **The row is written before any work happens** (ADR-042), in the same
    # transaction as the epoch anchor. Until this, `scheduler_ticks` was only
    # written at the *end* of a tick, so a crash anywhere below left no row at
    # all — and a colony failing every minute for a week looked exactly like one
    # nothing had ever scheduled. Those need different people to fix them.
    # `tool_calls` made this move first (migration 0019, `status='requested'`).
    conn.execute("BEGIN IMMEDIATE")
    try:
        _record_epoch_start_locked(conn, epoch_number)
        _begin_tick_locked(
            conn, tick_id=tick_id, epoch_number=epoch_number,
            started=started, provider=provider.name,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    try:
        return _run_tick(
            conn, tick_id=tick_id, epoch_number=epoch_number, started=started,
            provider=provider, model=model, max_cells=max_cells,
        )
    except Exception as exc:
        _mark_crashed(conn, tick_id=tick_id, exc=exc)
        raise


def _run_tick(
    conn: sqlite3.Connection,
    *,
    tick_id: str,
    epoch_number: int,
    started: datetime,
    provider: providers.ModelProvider,
    model: str,
    max_cells: int | None,
) -> TickResult:
    """The body of a tick, with its record already open."""
    # §23.3's two expiry clocks, and **the placement is the decision** (ADR-040).
    #
    # This runs *before* `_guard`, which is the opposite of everything else in
    # this function. Every guard below decides whether the colony may **do**
    # something — spend, deliberate, act. The sweep only ever **removes**
    # permission: it expires a request nobody decided and an approval nobody
    # consumed, and it cannot authorise anything. Gating it behind the guards
    # would invert their purpose, because a halt that also stopped expiry would
    # preserve exactly the authorisations the halt exists to stop being used.
    #
    # Vacation mode makes that concrete and is the reason this slice exists at
    # all. §23.3's vacation clause fires when the operator is unresponsive —
    # which is precisely when approvals lapse unconsumed. Sweeping *after* the
    # guard would disable the mechanism built for an absent operator whenever
    # the operator is absent, which is the same inversion twice over.
    #
    # **The cost stays guarded, though, and that falls out of the placement
    # rather than needing its own rule.** Expiring is free; the regenerated
    # wakes it enqueues are only *processed* by `run_ready_wakes` below, which a
    # halt returns before reaching. So a halted colony expires stale grants and
    # leaves the re-deliberation pending until a tick is allowed to run — the
    # authority is withdrawn immediately, the spending waits.
    requests_expired = len(approval.expire_due(conn))
    grants_expired = len(approval.expire_grants_due(conn))
    swept = (
        f"; expired {requests_expired} request(s), {grants_expired} grant(s)"
        if requests_expired or grants_expired
        else ""
    )

    spend_before = real_spend_breaker._settled_spend_since(conn, datetime(1970, 1, 1, tzinfo=timezone.utc))

    halt = _guard(conn, provider_name=provider.name)
    if halt is not None:
        outcome, detail = halt
        detail = f"{detail}{swept}"
        _finish_tick(
            conn, tick_id=tick_id, outcome=outcome, detail=detail,
            cells_woken=0, spend_before=spend_before, spend_after=spend_before,
        )
        return TickResult(
            tick_id, epoch_number, outcome, detail, 0,
            requests_expired=requests_expired, grants_expired=grants_expired,
        )

    cells = eligible_cells(conn, epoch_number)
    if max_cells is not None:
        cells = cells[:max_cells]

    if not cells:
        idle_detail = f"no alive, funded Cell was eligible{swept}"
        _finish_tick(
            conn, tick_id=tick_id, outcome=TickOutcome.IDLE, detail=idle_detail,
            cells_woken=0, spend_before=spend_before, spend_after=spend_before,
        )
        return TickResult(
            tick_id, epoch_number, TickOutcome.IDLE, idle_detail, 0,
            requests_expired=requests_expired, grants_expired=grants_expired,
        )

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

    ran_detail = f"{len(results)} deliberation(s){swept}"
    _finish_tick(
        conn, tick_id=tick_id, outcome=TickOutcome.RAN, detail=ran_detail,
        cells_woken=len(results), spend_before=spend_before, spend_after=spend_after,
    )
    return TickResult(
        tick_id, epoch_number, TickOutcome.RAN, ran_detail,
        len(results), tuple(results),
        requests_expired=requests_expired, grants_expired=grants_expired,
    )


def _begin_tick_locked(
    conn: sqlite3.Connection,
    *,
    tick_id: str,
    epoch_number: int,
    started: datetime,
    provider: str,
) -> None:
    """Open the tick's record. Caller holds the write lock, so this commits
    together with the epoch anchor — a tick that exists and an epoch that was
    never observed would be a state nothing could explain."""
    # `spend_before` is captured here rather than after the expiry sweeps,
    # which is equivalent — ADR-040: expiring "has no ledger consequence at
    # all" — and is what lets a *crashed* tick still report the spend it
    # started from. A crash row claiming 0 → 0 would be a false statement
    # rather than a missing one.
    spend_before = real_spend_breaker._settled_spend_since(
        conn, datetime(1970, 1, 1, tzinfo=timezone.utc)
    )
    conn.execute(
        """
        INSERT INTO scheduler_ticks (
            tick_id, epoch_number, started_at_utc, finished_at_utc, provider,
            is_paid, outcome, detail, cells_woken, spend_before_minor,
            spend_after_minor
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, NULL, 0, ?, ?)
        """,
        (
            tick_id, epoch_number, started.isoformat(), provider,
            1 if provider in PAID_PROVIDERS else 0,
            TickOutcome.STARTED, spend_before, spend_before,
        ),
    )


def _finish_tick(
    conn: sqlite3.Connection,
    *,
    tick_id: str,
    outcome: str,
    detail: str | None,
    cells_woken: int,
    spend_before: int | None,
    spend_after: int,
) -> None:
    """`spend_before=None` keeps what `_begin_tick_locked` recorded, which is
    what the crash path wants: it knows what the colony has spent *now* and has
    no way to recover the figure the tick body was working from."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            UPDATE scheduler_ticks
               SET finished_at_utc = ?, outcome = ?, detail = ?, cells_woken = ?,
                   spend_before_minor = COALESCE(?, spend_before_minor),
                   spend_after_minor = ?
             WHERE tick_id = ?
            """,
            (
                datetime.now(timezone.utc).isoformat(), outcome, detail,
                cells_woken, spend_before, spend_after, tick_id,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _mark_crashed(conn: sqlite3.Connection, *, tick_id: str, exc: BaseException) -> None:
    """Close the record on the way out of a failure, and **never mask the
    original exception**.

    The detail is redacted (Charter C14): a provider error can quote the key it
    was rejected with, and this string is persisted. If the write itself fails —
    which is likely, since a broken database is one of the things that makes a
    tick crash — the row simply stays `started` with a NULL `finished_at_utc`,
    which is the same signal a killed process leaves and is read the same way.
    Swallowing that secondary failure is deliberate: the caller is already
    raising something more informative.
    """
    try:
        _finish_tick(
            conn,
            tick_id=tick_id,
            outcome=TickOutcome.CRASHED,
            detail=providers.redact(f"{type(exc).__name__}: {exc}")[:500],
            cells_woken=0,
            # Keep the figure the tick opened with, and record what the colony
            # has actually settled by now: a tick that spent money and then died
            # must not leave a row saying it spent nothing.
            spend_before=None,
            spend_after=real_spend_breaker._settled_spend_since(
                conn, datetime(1970, 1, 1, tzinfo=timezone.utc)
            ),
        )
    except Exception:
        pass


def recent_ticks(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM scheduler_ticks ORDER BY rowid DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


# --- liveness: is anything still running this? (§23.3, §30.1; ADR-042) --------

#: How many recent ticks `liveness` reads to describe a failure run. A window
#: rather than the whole table: the verdict only ever depends on the newest
#: tick, and this exists to say "and the previous eleven died too".
FAILURE_WINDOW = 20

#: Slack on the liveness deadline, in missed runs. One is standard for a
#: liveness check and is what keeps a slow tick or a late cron wake-up from
#: reading as an outage.
OVERDUE_SLACK = 2


class Verdict:
    HEALTHY = "healthy"
    NEVER_RAN = "never_ran"
    NOT_RUNNING = "not_running"
    FAILING = "failing"
    NEEDS_OPERATOR = "needs_operator"


#: What `mitosis health` exits with. **0/non-zero is the whole interface**, and
#: that is §30.1's "avoid unnecessary frameworks" applied to alerting exactly as
#: it was applied to scheduling: a command composable with cron rather than a
#: daemon, and an exit code readable by every monitor that exists rather than a
#: notifier the kernel has to own. The two non-zero codes separate the two
#: fixes, because they are not the same person's job.
EXIT_HEALTHY = 0
EXIT_INFRASTRUCTURE = 1  # nothing is running the scheduler, or every run dies
EXIT_NEEDS_OPERATOR = 2  # it is running and has deliberately stopped

_EXIT_BY_VERDICT = {
    Verdict.HEALTHY: EXIT_HEALTHY,
    Verdict.NEVER_RAN: EXIT_INFRASTRUCTURE,
    Verdict.NOT_RUNNING: EXIT_INFRASTRUCTURE,
    Verdict.FAILING: EXIT_INFRASTRUCTURE,
    Verdict.NEEDS_OPERATOR: EXIT_NEEDS_OPERATOR,
}


@dataclass(frozen=True)
class Liveness:
    verdict: str
    reasons: tuple[str, ...]
    current_epoch: int
    last_tick_at_utc: datetime | None
    last_tick_epoch: int | None
    last_outcome: str | None
    epochs_since_last_tick: int | None
    seconds_since_last_tick: float | None
    #: Which rule was applied, in words, so the report never leaves the operator
    #: guessing why a silent colony reads healthy.
    deadline_rule: str
    consecutive_failures: int

    @property
    def exit_code(self) -> int:
        return _EXIT_BY_VERDICT[self.verdict]

    @property
    def healthy(self) -> bool:
        return self.verdict == Verdict.HEALTHY


def liveness(conn: sqlite3.Connection, *, now: datetime | None = None) -> Liveness:
    """Can anything outside the colony tell that the colony is still running?

    Nothing *inside* a stopped scheduler can notice it stopped, so this is a
    read an operator, a cron `MAILTO`, or a monitor invokes from outside. It
    answers three questions that used to be one:

    * **Has it ever run?** No crontab was ever installed.
    * **Has it run recently enough?** Installed once, gone now.
    * **Is it running and dying?** Installed, firing, failing every time —
      which before ADR-042 wrote no row and so looked identical to the second.

    **A deliberate halt is not an outage**, and the split matters more than it
    looks. Vacation mode and `real_spending` disabled are the colony working as
    designed and resolve themselves when the operator returns — paging someone
    on holiday because the fail-safe they configured engaged is how a fail-safe
    gets turned off. A metabolic alarm is different: §23.3 halts *until
    acknowledged*, so it will not clear on its own and it is the one halt that
    is genuinely waiting for a person.
    """
    # `now` moves the wall-clock measurements only. The epoch comes from the
    # simulated clock, as `current_epoch` always has — §6.3 keeps the two
    # unmixed, and in a live colony the simulated clock tracks wall time so
    # they agree. A caller that wants to move the epoch advances the clock.
    now = now or datetime.now(timezone.utc)
    epoch = current_epoch(conn)
    state = operator_state(conn)
    _, epoch_seconds = epoch_settings(conn)

    # **Ordered by `rowid`, not by `started_at_utc`.** Rows are only ever
    # inserted by `_begin_tick_locked`, in tick order, so insertion order *is*
    # tick order — while wall time can move backwards under NTP correction, a
    # VM restore or a DST-naive host, and would then report an older tick as the
    # newest. Same reasoning as `rights.current` (ADR-041); the timestamps are
    # still what the wall-clock deadline is measured against, because there is
    # nothing else to measure it against.
    row = conn.execute(
        "SELECT * FROM scheduler_ticks ORDER BY rowid DESC LIMIT 1"
    ).fetchone()

    if row is None:
        return Liveness(
            verdict=Verdict.NEVER_RAN,
            reasons=("no tick has ever run — nothing is scheduled to run `mitosis tick`",),
            current_epoch=epoch,
            last_tick_at_utc=None,
            last_tick_epoch=None,
            last_outcome=None,
            epochs_since_last_tick=None,
            seconds_since_last_tick=None,
            deadline_rule="not applicable until a first tick exists",
            consecutive_failures=0,
        )

    last_at = datetime.fromisoformat(row["started_at_utc"])
    silence = (now - last_at).total_seconds()
    epochs_since = epoch - row["epoch_number"]

    # **The default deadline is expressed in epochs, and that is the policy.**
    # What an outage costs the colony is *work*: wakes are keyed
    # `epoch:{n}:cell:{id}`, so any tick within an epoch does that epoch's work
    # and a second does nothing. A colony that has skipped two epochs has lost
    # an epoch's wakes; one silent for an hour inside a six-hour epoch has lost
    # nothing, however many cron runs it missed. An operator who wants
    # wall-clock responsiveness sets `tick_expected_every_seconds` and gets a
    # wall-clock rule instead.
    if state.tick_expected_every_seconds:
        deadline = state.tick_expected_every_seconds * OVERDUE_SLACK
        overdue = silence > deadline
        rule = (
            f"silent for more than {deadline}s "
            f"({OVERDUE_SLACK} × the configured {state.tick_expected_every_seconds}s cadence)"
        )
    else:
        overdue = epochs_since >= OVERDUE_SLACK
        rule = (
            f"{OVERDUE_SLACK} or more epochs behind (epoch is {epoch_seconds}s; "
            "set tick_expected_every_seconds for a wall-clock rule instead)"
        )

    # A tick still in flight is `started` with no `finished_at_utc`, and so is
    # one whose process was killed. They are told apart by age: a tick running
    # longer than the whole expected interval is stuck, not busy.
    stale_after = state.tick_expected_every_seconds or epoch_seconds
    recent = conn.execute(
        "SELECT * FROM scheduler_ticks ORDER BY rowid DESC LIMIT ?", (FAILURE_WINDOW,)
    ).fetchall()

    def failed(tick_row) -> bool:
        if tick_row["outcome"] == TickOutcome.CRASHED:
            return True
        if tick_row["outcome"] != TickOutcome.STARTED:
            return False
        began = datetime.fromisoformat(tick_row["started_at_utc"])
        return (now - began).total_seconds() > stale_after

    consecutive = 0
    for tick_row in recent:
        if not failed(tick_row):
            break
        consecutive += 1

    reasons: list[str] = []
    verdict = Verdict.HEALTHY

    if consecutive:
        verdict = Verdict.FAILING
        if row["outcome"] == TickOutcome.CRASHED:
            reasons.append(
                f"the last {consecutive} tick(s) crashed — most recently: {row['detail']}"
            )
        else:
            reasons.append(
                f"the last {consecutive} tick(s) began and never reported back, which is "
                "what a killed process leaves (SIGKILL, OOM, power) — no detail is "
                "recoverable for those"
            )
    elif overdue:
        verdict = Verdict.NOT_RUNNING
        reasons.append(
            f"last tick was {_ago(silence)} ago in epoch {row['epoch_number']}; "
            f"now epoch {epoch}. Overdue: {rule}"
        )
    elif state.alarm_active:
        # Only reached when the scheduler is demonstrably alive, which is the
        # right order: an alarm nobody can act on is not the urgent fact when
        # nothing is running at all.
        verdict = Verdict.NEEDS_OPERATOR
        reasons.append(
            f"§23.3 metabolic alarm is raised and halts every tick until "
            f"acknowledged — {state.metabolic_alarm_reason}"
        )

    if verdict != Verdict.NEEDS_OPERATOR and state.alarm_active:
        reasons.append(f"(also: metabolic alarm raised — {state.metabolic_alarm_reason})")

    return Liveness(
        verdict=verdict,
        reasons=tuple(reasons),
        current_epoch=epoch,
        last_tick_at_utc=last_at,
        last_tick_epoch=row["epoch_number"],
        last_outcome=row["outcome"],
        epochs_since_last_tick=epochs_since,
        seconds_since_last_tick=silence,
        deadline_rule=rule,
        consecutive_failures=consecutive,
    )


def _ago(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86_400:.1f}d"


def set_tick_expectation(conn: sqlite3.Connection, seconds: int | None) -> OperatorState:
    """How often the operator's crontab runs `tick`. None restores the
    epoch-based default. Audited, like every other operator-set guard."""
    if seconds is not None and seconds <= 0:
        raise SchedulerError("a tick cadence must be a positive number of seconds")
    conn.execute("BEGIN IMMEDIATE")
    try:
        initialize_operator_if_absent(conn)
        conn.execute(
            "UPDATE operator_state SET tick_expected_every_seconds = ? WHERE id = 1",
            (seconds,),
        )
        audit.record(
            conn,
            event_type="tick_expectation_set",
            description=(
                f"liveness deadline: every {seconds}s"
                if seconds
                else "liveness deadline: back to the epoch-based default"
            ),
            metadata={"tick_expected_every_seconds": seconds},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return operator_state(conn)
