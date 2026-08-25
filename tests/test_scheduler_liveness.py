"""Can anything outside the colony tell it is still running?
(SPEC.md §23.3, §30.1, §17.2; Charter C14; ADR-022, ADR-040, ADR-042.)

`tick` is composable with cron, and cron already restarts it — it runs again
next minute whether or not the last run succeeded. What cron does not do is tell
anyone. These defend the two failures that used to look identical from outside:
nothing is running the scheduler, and something is running it and every run
dies.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import approval, clock, db, ledger, providers, scheduler
from mitosis.models import Book, EntrySpec

REPLY = json.dumps({
    "kind": "experiment", "summary": "probe", "rationale": "none",
    "risk_tier": "LOW", "estimated_cost_minor_units": 0, "predictions": [],
    "experiment": {"hypothesis": "the probe finds a signal"},
})


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    clock.initialize_if_absent(connection)
    scheduler.configure_epochs_if_absent(connection)
    scheduler.initialize_operator_if_absent(connection)
    connection.commit()
    yield connection
    connection.close()


def _tick(conn):
    return scheduler.tick(conn, provider=providers.MockProvider(reply=REPLY), model="mock-1")


def _backdate_last_tick(conn, **delta):
    when = (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()
    conn.execute(
        "UPDATE scheduler_ticks SET started_at_utc = ?, finished_at_utc = ? "
        "WHERE tick_id = (SELECT tick_id FROM scheduler_ticks ORDER BY rowid DESC LIMIT 1)",
        (when, when),
    )
    conn.commit()


# --- a crash leaves a diagnosable row ------------------------------------------


def test_a_tick_is_recorded_before_it_does_any_work(conn):
    """ADR-042, borrowed from `tool_calls.status = 'requested'` (migration 0019).

    `scheduler_ticks` used to be written only at the end, so a tick that raised
    left no row at all — and a colony failing every minute for a week was
    indistinguishable from one nothing had ever scheduled. Those need different
    people to fix them, so they must be distinguishable in the record.
    """
    original = approval.expire_due
    approval.expire_due = lambda c: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        with pytest.raises(RuntimeError):
            _tick(conn)
    finally:
        approval.expire_due = original

    row = conn.execute("SELECT * FROM scheduler_ticks ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row is not None, "a crashed tick must still leave a row"
    assert row["outcome"] == scheduler.TickOutcome.CRASHED
    assert "boom" in row["detail"]


def test_a_crash_detail_is_redacted_before_it_is_stored(conn):
    """Charter C14. A provider error quotes the key it was rejected with, and
    this string is persisted — so the crash path has to redact exactly like
    `providers` does on the paths that already carry secrets.
    """
    secret = "sk-ant-api03-" + "Z" * 20
    original = approval.expire_due

    def boom(c):
        raise RuntimeError(f"auth failed for {secret}")

    approval.expire_due = boom
    try:
        with pytest.raises(RuntimeError):
            _tick(conn)
    finally:
        approval.expire_due = original

    detail = conn.execute(
        "SELECT detail FROM scheduler_ticks ORDER BY rowid DESC LIMIT 1"
    ).fetchone()["detail"]
    assert secret not in detail
    assert "[redacted]" in detail


def test_a_crash_handler_that_fails_does_not_mask_the_original_error(conn):
    """The database being broken is one of the reasons a tick crashes, so the
    handler that records the crash is exactly the code most likely to fail too.
    It must never replace the caller's exception with its own — the original is
    the more informative one, and the `started` row left behind carries the same
    signal a killed process would leave.
    """
    original_expire, original_finish = approval.expire_due, scheduler._finish_tick
    approval.expire_due = lambda c: (_ for _ in ()).throw(RuntimeError("the real problem"))
    scheduler._finish_tick = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("and the recorder is broken too")
    )
    try:
        with pytest.raises(RuntimeError, match="the real problem"):
            _tick(conn)
    finally:
        approval.expire_due, scheduler._finish_tick = original_expire, original_finish

    row = conn.execute("SELECT * FROM scheduler_ticks ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row["outcome"] == scheduler.TickOutcome.STARTED
    assert row["finished_at_utc"] is None


def test_a_completed_tick_records_when_it_finished(conn):
    """NULL `finished_at_utc` is the signal for "began and never reported back",
    so a normal tick must clear it or every healthy colony reads as failing."""
    _tick(conn)
    row = conn.execute("SELECT * FROM scheduler_ticks ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row["finished_at_utc"] is not None
    assert row["outcome"] in (scheduler.TickOutcome.RAN, scheduler.TickOutcome.IDLE)


def test_a_crashed_tick_does_not_claim_it_spent_nothing(conn):
    """A crash row reading `spend 0 → 0` would be a false statement rather than
    a missing one, and the tick log is what an operator reads at 3am to work out
    what the colony did while nobody was watching.

    `spend_before` is captured when the row is opened — equivalent to capturing
    it after the sweeps, since ADR-040 established that expiry has no ledger
    consequence — so the figure survives a crash that happens before the body
    ever computes one.
    """
    # Give the colony a settled real spend so 0 is distinguishable from "we
    # simply have not spent anything", which is the state that would let this
    # test pass against a kernel that hard-codes zero.
    ledger.post_transaction(
        conn,
        book=Book.USD_REAL,
        currency="USD",
        # A registered real-spend type (`_REAL_SPEND_TRANSACTION_TYPES`), or the
        # breaker's spend window does not see it and this test would pass
        # against a kernel that recorded nothing.
        transaction_type="model_call_cost_overrun",
        idempotency_key="model_call_cost_overrun:liveness-probe",
        description="prior spend",
        entries=[
            EntrySpec(account_id="colony_treasury", amount_minor_units=-7),
            EntrySpec(account_id="external_expense", amount_minor_units=7),
        ],
    )
    conn.commit()

    original = approval.expire_due
    approval.expire_due = lambda c: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        with pytest.raises(RuntimeError):
            _tick(conn)
    finally:
        approval.expire_due = original

    row = conn.execute("SELECT * FROM scheduler_ticks ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row["outcome"] == scheduler.TickOutcome.CRASHED
    assert row["spend_before_minor"] == 7
    assert row["spend_after_minor"] == 7


# --- the verdicts ---------------------------------------------------------------


def test_a_colony_that_never_ticked_says_so(conn):
    """The commonest real failure: the colony was set up and no crontab was ever
    installed. Nothing inside a scheduler that never ran can notice, so this is
    the read that has to work from outside."""
    state = scheduler.liveness(conn)
    assert state.verdict == scheduler.Verdict.NEVER_RAN
    assert state.exit_code == scheduler.EXIT_INFRASTRUCTURE


def test_a_recent_tick_is_healthy(conn):
    _tick(conn)
    state = scheduler.liveness(conn)
    assert state.verdict == scheduler.Verdict.HEALTHY
    assert state.exit_code == 0


def test_silence_past_the_deadline_reads_as_not_running(conn):
    """The wall-clock rule, which applies when an operator has said how often
    cron runs `tick`."""
    _tick(conn)
    scheduler.set_tick_expectation(conn, 60)
    _backdate_last_tick(conn, minutes=10)

    state = scheduler.liveness(conn)
    assert state.verdict == scheduler.Verdict.NOT_RUNNING
    assert state.exit_code == scheduler.EXIT_INFRASTRUCTURE


def test_the_default_deadline_is_measured_in_epochs_not_wall_time(conn):
    """**The default is the policy, not a placeholder.**

    What an outage costs the colony is *work*, and wakes are keyed
    `epoch:{n}:cell:{id}` — so any tick inside an epoch does that epoch's work
    and a second does nothing. A colony silent for ten minutes inside a
    day-long epoch has lost nothing, and alarming on it would train the operator
    to ignore the alarm. Two epochs behind means an epoch's wakes were skipped.
    """
    _tick(conn)
    _backdate_last_tick(conn, minutes=10)
    assert scheduler.liveness(conn).verdict == scheduler.Verdict.HEALTHY

    # Epochs move because the *simulated* clock moves, which is what
    # `current_epoch` reads — passing a later wall `now` would move the silence
    # measurement and leave the epoch where it was.
    _, epoch_seconds = scheduler.epoch_settings(conn)
    clock.advance(conn, timedelta(seconds=epoch_seconds * 2 + 60))
    assert scheduler.liveness(conn).verdict == scheduler.Verdict.NOT_RUNNING


def test_a_running_but_crashing_scheduler_is_not_the_same_as_a_stopped_one(conn):
    """The distinction ADR-042 exists to draw. Both used to look like "no recent
    rows"; they need different fixes, so they get different verdicts and
    different reasons — while sharing an exit code, because both are the same
    person's problem.
    """
    original = approval.expire_due
    approval.expire_due = lambda c: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        with pytest.raises(RuntimeError):
            _tick(conn)
    finally:
        approval.expire_due = original

    state = scheduler.liveness(conn)
    assert state.verdict == scheduler.Verdict.FAILING
    assert state.consecutive_failures == 1
    assert "crashed" in state.reasons[0]


def test_a_tick_still_in_flight_is_not_counted_as_a_failure(conn):
    """`health` can be invoked while a tick is running — by the operator, or by
    a monitor on its own schedule. An in-flight tick is `started` with no
    `finished_at_utc`, which is exactly what a killed one looks like; they are
    told apart by age, not by shape. Counting a busy tick as a failure would
    make the check flap on every healthy colony.
    """
    conn.execute(
        "INSERT INTO scheduler_ticks (tick_id, epoch_number, started_at_utc, "
        "finished_at_utc, provider, is_paid, outcome, detail, cells_woken, "
        "spend_before_minor, spend_after_minor) "
        "VALUES ('inflight', 0, ?, NULL, 'mock', 0, 'started', NULL, 0, 0, 0)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    assert scheduler.liveness(conn).verdict == scheduler.Verdict.HEALTHY


def test_a_tick_that_began_and_never_reported_back_is_a_failure(conn):
    """The killed-process case: SIGKILL, OOM, power. Nothing can be caught and
    nothing can be written, so the absence of `finished_at_utc` on an aged row
    is the only signal there is — and it has to be enough.
    """
    conn.execute(
        "INSERT INTO scheduler_ticks (tick_id, epoch_number, started_at_utc, "
        "finished_at_utc, provider, is_paid, outcome, detail, cells_woken, "
        "spend_before_minor, spend_after_minor) "
        "VALUES ('killed', 0, ?, NULL, 'mock', 0, 'started', NULL, 0, 0, 0)",
        ((datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),),
    )
    conn.commit()
    state = scheduler.liveness(conn)
    assert state.verdict == scheduler.Verdict.FAILING
    assert "never reported back" in state.reasons[0]


# --- a deliberate halt is not an outage -----------------------------------------


def test_vacation_mode_is_not_an_outage(conn):
    """§23.3's fail-safe engaging is the colony working, and it clears when the
    operator returns. Paging someone on holiday because the pause they
    configured engaged is how a fail-safe gets switched off.
    """
    _tick(conn)
    conn.execute(
        "UPDATE operator_state SET last_heartbeat_utc = ? WHERE id = 1",
        ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),),
    )
    conn.commit()
    assert scheduler.is_on_vacation(conn)
    state = scheduler.liveness(conn)
    assert state.verdict == scheduler.Verdict.HEALTHY
    assert state.exit_code == 0


def test_real_spending_disabled_is_not_an_outage(conn):
    """§27.1 ships `real_spending` false. A colony in its shipped configuration
    must not read as broken."""
    _tick(conn)
    scheduler.set_real_spending(conn, False)
    assert scheduler.liveness(conn).verdict == scheduler.Verdict.HEALTHY


def test_a_metabolic_alarm_needs_an_operator_and_says_so_distinctly(conn):
    """The one halt that does *not* clear on its own: §23.3 holds it until
    acknowledged. It gets its own exit code because it is a different person's
    job from a broken crontab — the colony is running fine and is waiting for a
    decision.
    """
    _tick(conn)
    conn.execute("BEGIN IMMEDIATE")
    scheduler._raise_metabolic_alarm_locked(conn, "burn rate 7x baseline")
    conn.execute("COMMIT")

    state = scheduler.liveness(conn)
    assert state.verdict == scheduler.Verdict.NEEDS_OPERATOR
    assert state.exit_code == scheduler.EXIT_NEEDS_OPERATOR
    assert state.exit_code != scheduler.EXIT_INFRASTRUCTURE


def test_a_stopped_scheduler_outranks_an_alarm_but_still_reports_it(conn):
    """Precedence, and the reason for it: an alarm nobody can act on is not the
    urgent fact when nothing is running at all. It is still reported, because
    the operator who fixes the crontab needs to know what they are restarting
    into.
    """
    _tick(conn)
    conn.execute("BEGIN IMMEDIATE")
    scheduler._raise_metabolic_alarm_locked(conn, "burn rate 7x baseline")
    conn.execute("COMMIT")
    scheduler.set_tick_expectation(conn, 60)
    _backdate_last_tick(conn, minutes=10)

    state = scheduler.liveness(conn)
    assert state.verdict == scheduler.Verdict.NOT_RUNNING
    assert any("metabolic alarm" in reason for reason in state.reasons)


# --- ordering -------------------------------------------------------------------


def test_the_latest_tick_is_the_latest_inserted_not_the_latest_timestamped(conn):
    """Rows are only ever inserted in tick order, so `rowid` is the true order —
    while wall time can move backwards under an NTP correction, a VM restore or
    a DST-naive host, and would then report an older tick as the newest. Same
    reasoning as `rights.current` (ADR-041).
    """
    _tick(conn)
    recent_tick_at = datetime.fromisoformat(
        conn.execute(
            "SELECT started_at_utc FROM scheduler_ticks ORDER BY rowid DESC LIMIT 1"
        ).fetchone()["started_at_utc"]
    )
    backdated_at = datetime.now(timezone.utc) - timedelta(days=9)
    conn.execute(
        "INSERT INTO scheduler_ticks (tick_id, epoch_number, started_at_utc, "
        "finished_at_utc, provider, is_paid, outcome, detail, cells_woken, "
        "spend_before_minor, spend_after_minor) "
        "VALUES ('newest-but-backdated', 0, ?, ?, 'mock', 0, 'idle', NULL, 0, 0, 0)",
        (backdated_at.isoformat(), backdated_at.isoformat()),
    )
    conn.commit()

    # The two orderings disagree here and the assertion has to be able to tell
    # them apart: insertion order picks the backdated row, wall-clock order
    # picks the tick that really ran a moment ago.
    seen = scheduler.liveness(conn).last_tick_at_utc
    assert seen == backdated_at
    assert seen != recent_tick_at


def test_a_cadence_must_be_positive(conn):
    with pytest.raises(scheduler.SchedulerError, match="positive"):
        scheduler.set_tick_expectation(conn, 0)
