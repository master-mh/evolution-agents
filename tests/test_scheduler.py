"""The scheduler and its §23.3 guards (SPEC.md §6.3, §17.2, §23.3, §27.1, A19).

Weighted toward the refusals. A scheduler that wakes Cells is easy; a scheduler
that is safe to leave running overnight is the part the spec actually specifies.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    clock,
    deliberation,
    ledger,
    lifecycle,
    providers,
    scheduler,
)
from mitosis.models import Book, CellStatus, CellType, EntrySpec

REPLY = json.dumps({
    "kind": "experiment", "summary": "probe the market",
    "rationale": "no realised record yet", "risk_tier": "LOW",
    "estimated_cost_minor_units": 0, "predictions": [],
})


def _setup(conn):
    clock.initialize_if_absent(conn)
    scheduler.configure_epochs_if_absent(conn)
    scheduler.initialize_operator_if_absent(conn)
    conn.commit()


def _make_cell(conn, key: str, *, funded: bool = True, status=CellStatus.ALIVE):
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key=key,
    )
    if funded:
        for book, currency in ((Book.USD_REAL, "USD"), (Book.RESOURCE, "RESOURCE")):
            ledger.post_transaction(
                conn, book=book, currency=currency, transaction_type="cell_birth_funding",
                idempotency_key=f"fund:{key}:{book.value}", description="fund",
                entries=[
                    EntrySpec(account_id="seed_bank", amount_minor_units=-5000, cell_id=cell.cell_id),
                    EntrySpec(account_id=f"cell:{cell.cell_id}:cash",
                              amount_minor_units=5000, cell_id=cell.cell_id),
                ],
            )
    if status is not CellStatus.ALIVE:
        conn.execute("UPDATE cells SET status = ? WHERE cell_id = ?",
                     (status.value, cell.cell_id))
        conn.commit()
    return lifecycle.get_cell(conn, cell.cell_id)


def _tick(conn, provider_name: str = "mock", **kwargs):
    provider = (
        providers.MockProvider(reply=REPLY) if provider_name == "mock"
        else _FakePaidProvider()
    )
    return scheduler.tick(conn, provider=provider, model="mock-1", **kwargs)


class _FakePaidProvider:
    """Names itself `anthropic` so the guards treat it as paid, without ever
    being reached — every test using it expects a halt *before* the call."""
    name = providers.ANTHROPIC_PROVIDER

    def complete(self, request):  # pragma: no cover - must never be called
        raise AssertionError("a guard should have halted the tick before this")


def _post_real_spend(conn, minor_units: int, key: str):
    """Simulate settled real spend, using a registered real-spend type so the
    breaker's own query sees it (the same query the alarm reads through)."""
    ledger.post_transaction(
        conn, book=Book.USD_REAL, currency="USD",
        transaction_type="model_call_cost_overrun",
        idempotency_key=f"spend:{key}", description="simulated spend",
        entries=[
            EntrySpec(account_id="external_expense", amount_minor_units=minor_units),
            EntrySpec(account_id="colony_treasury", amount_minor_units=-minor_units),
        ],
    )


# --- cadence: one wake per Cell per epoch ------------------------------------


def test_a_tick_wakes_every_eligible_cell_once(conn):
    _setup(conn)
    _make_cell(conn, "a")
    _make_cell(conn, "b")

    result = _tick(conn)

    assert result.outcome == scheduler.TickOutcome.RAN
    assert result.cells_woken == 2


def test_re_ticking_inside_one_epoch_wakes_nobody(conn):
    """The cadence policy *is* the dedupe key `epoch:{n}:cell:{id}`, so this is
    structural rather than a counter that could drift. It is what makes running
    the scheduler from cron every minute cost nothing."""
    _setup(conn)
    _make_cell(conn, "a")

    first = _tick(conn)
    second = _tick(conn)
    third = _tick(conn)

    assert first.cells_woken == 1
    assert second.cells_woken == 0 and third.cells_woken == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM model_calls").fetchone()["n"] == 1


def test_a_new_epoch_wakes_them_again(conn):
    _setup(conn)
    _make_cell(conn, "a")
    assert _tick(conn).cells_woken == 1

    clock.advance(conn, timedelta(seconds=scheduler.DEFAULT_EPOCH_DURATION_SECONDS))

    assert scheduler.current_epoch(conn) == 1
    assert _tick(conn).cells_woken == 1


def test_the_epoch_is_derived_from_the_clock_never_stored(conn):
    """Charter C3's rule for balances, applied to epochs for the same reason: a
    cached counter and the clock disagreeing has no correct resolution."""
    _setup(conn)
    assert scheduler.current_epoch(conn) == 0
    clock.advance(conn, timedelta(seconds=scheduler.DEFAULT_EPOCH_DURATION_SECONDS * 3))
    assert scheduler.current_epoch(conn) == 3


# --- eligibility -------------------------------------------------------------


def test_only_alive_funded_cells_are_woken(conn):
    """Dormant is excluded on purpose: §17.2 wakes a dormant Cell by *delivering
    an event*, not by the passage of time."""
    _setup(conn)
    _make_cell(conn, "alive")
    _make_cell(conn, "dormant", status=CellStatus.DORMANT)
    _make_cell(conn, "quarantined", status=CellStatus.QUARANTINED)
    _make_cell(conn, "dead", status=CellStatus.DEAD)
    _make_cell(conn, "broke", funded=False)

    assert len(scheduler.eligible_cells(conn, 0)) == 1
    assert _tick(conn).cells_woken == 1


def test_a_colony_with_nothing_to_do_records_an_idle_tick(conn):
    """Recorded, not silent: a scheduler whose quiet nights leave no trace is
    one you cannot debug."""
    _setup(conn)
    result = _tick(conn)
    assert result.outcome == scheduler.TickOutcome.IDLE
    assert scheduler.recent_ticks(conn)[-1]["outcome"] == "idle"


# --- §27.1 autonomy.real_spending -------------------------------------------


def test_a_paid_provider_is_refused_while_real_spending_is_disabled(conn):
    """§27.1 ships `autonomy.real_spending: false`. An unattended scheduler is
    free-provider-only until someone deliberately says otherwise."""
    _setup(conn)
    _make_cell(conn, "a")

    result = _tick(conn, "paid")

    assert result.outcome == scheduler.TickOutcome.HALTED_AUTONOMY
    assert result.cells_woken == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM model_calls").fetchone()["n"] == 0


def test_enabling_real_spending_is_audited_in_both_directions(conn):
    _setup(conn)
    scheduler.set_real_spending(conn, True)
    scheduler.set_real_spending(conn, False)
    types = [r["description"] for r in conn.execute(
        "SELECT description FROM audit_events WHERE event_type='autonomy_real_spending_changed' "
        "ORDER BY rowid")]
    assert types == ["real_spending_enabled -> True", "real_spending_enabled -> False"]


# --- §23.3 vacation mode -----------------------------------------------------


def test_an_absent_operator_pauses_paid_work_but_not_free_work(conn):
    """§23.3: "external-facing phases auto-pause (fail-safe), while sim-only
    work may continue." The provider split is exactly that distinction — an
    absent operator stops the colony *spending*, not thinking."""
    _setup(conn)
    _make_cell(conn, "a")
    scheduler.set_real_spending(conn, True)
    conn.execute("UPDATE operator_state SET last_heartbeat_utc = ? WHERE id = 1",
                 ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),))
    conn.commit()

    assert scheduler.is_on_vacation(conn)
    assert _tick(conn, "paid").outcome == scheduler.TickOutcome.HALTED_VACATION
    # ... and free work continues.
    assert _tick(conn).outcome == scheduler.TickOutcome.RAN


def test_a_heartbeat_ends_vacation_mode(conn):
    _setup(conn)
    conn.execute("UPDATE operator_state SET last_heartbeat_utc = ? WHERE id = 1",
                 ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),))
    conn.commit()
    assert scheduler.is_on_vacation(conn)
    scheduler.heartbeat(conn)
    assert not scheduler.is_on_vacation(conn)


def test_an_unconfigured_operator_fails_safe(conn):
    """No operator row means "never seen", so vacation mode is on and real
    spending is off. Failing open on missing config is how an unattended system
    does something nobody chose."""
    clock.initialize_if_absent(conn)
    scheduler.configure_epochs_if_absent(conn)
    conn.commit()
    state = scheduler.operator_state(conn)
    assert not state.real_spending_enabled
    assert scheduler.is_on_vacation(conn)


# --- §23.3 the metabolic alarm ----------------------------------------------


def test_the_alarm_fires_on_absolute_epoch_spend(conn):
    _setup(conn)
    _make_cell(conn, "a")
    _tick(conn)  # anchors epoch 0 in wall time
    _post_real_spend(conn, 500, "big")

    status = scheduler.metabolic_status(conn)

    assert status["spend_this_epoch_minor_units"] == 500
    assert any("above metabolic_alarm_cents_per_epoch" in b for b in status["breached"])


def test_the_alarm_fires_on_acceleration_even_under_every_cap(conn):
    """**The §23.3 property.** "An acceleration in the burn rate raises an alarm
    even if every individual cap is satisfied." This is not another ceiling —
    the ceilings already exist and did not catch this. Spend stays under the
    per-epoch cap throughout; what fires the alarm is the *derivative*.
    """
    _setup(conn)
    _make_cell(conn, "a")
    cap = scheduler.operator_state(conn).metabolic_alarm_cents_per_epoch
    assert cap == 50

    # Four quiet epochs at 2 minor units each, then one at 30. Every epoch is
    # comfortably under the 50 cap, so no absolute breach is possible.
    for epoch in range(4):
        _tick(conn)
        _post_real_spend(conn, 2, f"baseline-{epoch}")
        clock.advance(conn, timedelta(seconds=scheduler.DEFAULT_EPOCH_DURATION_SECONDS))
    _tick(conn)
    _post_real_spend(conn, 30, "spike")

    status = scheduler.metabolic_status(conn)

    assert status["spend_this_epoch_minor_units"] == 30 < cap, "under the cap"
    assert status["baseline_minor_units"] == 2
    assert status["acceleration"] == 15.0
    assert any("burn rate" in b for b in status["breached"])
    assert not any("above metabolic_alarm_cents_per_epoch" in b for b in status["breached"])


def test_a_first_spend_is_not_an_infinite_acceleration(conn):
    """A colony that was idle and is now spending is starting, not
    accelerating. A zero baseline would make every first spend fire."""
    _setup(conn)
    _make_cell(conn, "a")
    _tick(conn)
    clock.advance(conn, timedelta(seconds=scheduler.DEFAULT_EPOCH_DURATION_SECONDS))
    _tick(conn)
    _post_real_spend(conn, 10, "first")

    status = scheduler.metabolic_status(conn)
    assert status["baseline_minor_units"] is None
    assert status["acceleration"] is None
    assert status["breached"] == []


def test_a_fired_alarm_halts_the_next_tick(conn):
    _setup(conn)
    _make_cell(conn, "a")
    _tick(conn)
    _post_real_spend(conn, 500, "big")
    _tick(conn)  # observes the breach and raises

    assert scheduler.operator_state(conn).alarm_active
    clock.advance(conn, timedelta(seconds=scheduler.DEFAULT_EPOCH_DURATION_SECONDS))
    result = _tick(conn)

    assert result.outcome == scheduler.TickOutcome.HALTED_METABOLIC
    assert result.cells_woken == 0


def test_the_alarm_halts_free_work_too(conn):
    """Unlike vacation mode. Vacation says "the operator is away, so don't
    spend"; the alarm says "something is wrong with how this colony is
    behaving", and that is not a statement about money alone."""
    _setup(conn)
    _make_cell(conn, "a")
    _tick(conn)
    _post_real_spend(conn, 500, "big")
    _tick(conn)

    assert _tick(conn).outcome == scheduler.TickOutcome.HALTED_METABOLIC


def test_a_heartbeat_does_not_clear_a_metabolic_alarm(conn):
    """Being back at the keyboard is not the same as having looked at why the
    colony was burning money."""
    _setup(conn)
    _make_cell(conn, "a")
    _tick(conn)
    _post_real_spend(conn, 500, "big")
    _tick(conn)

    scheduler.heartbeat(conn)

    assert scheduler.operator_state(conn).alarm_active


def test_acknowledging_requires_a_stated_reason(conn):
    _setup(conn)
    _make_cell(conn, "a")
    _tick(conn)
    _post_real_spend(conn, 500, "big")
    _tick(conn)

    with pytest.raises(scheduler.SchedulerError) as exc:
        scheduler.acknowledge_metabolic_alarm(conn, note="   ")
    assert "stated" in str(exc.value) or "why" in str(exc.value)

    scheduler.acknowledge_metabolic_alarm(conn, note="investigated: one-off backfill")
    assert not scheduler.operator_state(conn).alarm_active


def test_acknowledging_records_what_it_cleared(conn):
    _setup(conn)
    _make_cell(conn, "a")
    _tick(conn)
    _post_real_spend(conn, 500, "big")
    _tick(conn)
    scheduler.acknowledge_metabolic_alarm(conn, note="one-off backfill, reviewed")

    row = conn.execute(
        "SELECT description, metadata_json FROM audit_events "
        "WHERE event_type='metabolic_alarm_acknowledged'"
    ).fetchone()
    assert "reviewed" in row["description"]
    assert "metabolic_alarm_cents_per_epoch" in row["metadata_json"]


# --- the record --------------------------------------------------------------


def test_every_tick_is_recorded_including_the_refusals(conn):
    _setup(conn)
    _make_cell(conn, "a")
    _tick(conn)
    _tick(conn, "paid")

    outcomes = [t["outcome"] for t in scheduler.recent_ticks(conn)]
    assert outcomes == ["ran", "halted_autonomy"]
    assert [t["is_paid"] for t in scheduler.recent_ticks(conn)] == [0, 1]


def test_the_epoch_log_anchors_simulated_time_to_wall_time(conn):
    """§6.3's "explicit conversion metadata", and the only reason spend (stamped
    in wall time) can be attributed to an epoch (measured in simulated time)."""
    _setup(conn)
    _make_cell(conn, "a")
    _tick(conn)
    assert scheduler.epoch_started_at_wall(conn, 0) is not None
    assert scheduler.epoch_started_at_wall(conn, 99) is None


def test_spend_in_an_epoch_no_tick_observed_is_zero(conn):
    """Spend a human caused by hand is not what §23.3's automation guard
    measures, and an unobserved epoch has no wall anchor to measure against."""
    _setup(conn)
    _post_real_spend(conn, 999, "by-hand")
    assert scheduler.epoch_spend_minor_units(conn, 0) == 0


# --- ADR-040: §23.3's expiry runs before the guards --------------------------


def _stale_grant(conn, cell):
    """An approval a person made and nobody consumed, already past its window."""
    from mitosis import approval, deliberation, providers as _providers

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=_providers.MockProvider(reply=REPLY),
        wake_key=f"seed:{cell.cell_id}", model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    row = conn.execute(
        "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
        (result.proposal_id,),
    ).fetchone()
    grant = approval.approve(
        conn, request_id=row["request_id"], decided_by="operator", reason="worth doing"
    )
    conn.execute(
        "UPDATE approval_grants SET expires_at_utc = '2020-01-01T00:00:00+00:00' "
        "WHERE grant_id = ?",
        (grant.grant_id,),
    )
    conn.commit()
    return grant


def test_a_tick_sweeps_both_expiry_clocks(conn):
    """§23.3's sweeps had exactly one caller — `mitosis expire-approvals` — so
    the machinery built for an absent operator only ran when the operator was
    present to type a command. A cron tick is the thing that is actually there
    when nobody is."""
    from mitosis import approval

    _setup(conn)
    cell = _make_cell(conn, "a")
    grant = _stale_grant(conn, cell)

    result = _tick(conn)

    assert result.grants_expired == 1
    assert approval.get_grant(conn, grant.grant_id).expired_at_utc is not None


def test_expiry_runs_even_on_a_halted_tick(conn):
    """**The placement decision, and the reason this slice exists** (ADR-040).

    Every guard in `tick` decides whether the colony may *do* something. The
    sweep only ever *removes* permission — it cannot authorise anything — so
    gating it behind the guards inverts their purpose: a halt that also stopped
    expiry would preserve exactly the authorisations the halt exists to stop
    being used.

    Vacation mode makes it concrete. §23.3 pauses work when the operator is
    unresponsive, which is precisely when approvals lapse unconsumed. Sweeping
    after the guard would disable the mechanism built for an absent operator
    whenever the operator is absent.
    """
    from mitosis import approval

    _setup(conn)
    cell = _make_cell(conn, "a")
    grant = _stale_grant(conn, cell)

    # A paid provider with real_spending off: halted before anything runs.
    result = _tick(conn, provider_name="paid")

    assert result.halted
    assert result.outcome == scheduler.TickOutcome.HALTED_AUTONOMY
    assert result.cells_woken == 0
    assert result.grants_expired == 1, "a halt must not preserve a stale approval"
    assert approval.get_grant(conn, grant.grant_id).expired_at_utc is not None


def test_a_halted_tick_regenerates_but_does_not_spend(conn):
    """The other half of the placement, and it falls out rather than being a
    separate rule.

    Expiring is free; the wake it enqueues is only *processed* by
    `run_ready_wakes`, which a halted tick returns before reaching. So a halted
    colony withdraws the stale authority immediately and leaves the
    re-deliberation pending until a tick is allowed to run. If this fails, a
    halt has become a way to make the colony think — and pay — anyway.
    """
    from mitosis import approval

    _setup(conn)
    cell = _make_cell(conn, "a")
    grant = _stale_grant(conn, cell)

    result = _tick(conn, provider_name="paid")

    assert result.halted
    assert result.deliberations == ()
    pending = conn.execute(
        "SELECT status FROM event_inbox WHERE dedupe_key = ?",
        (f"grant-expiry:{grant.grant_id}",),
    ).fetchone()
    assert pending is not None, "the action must still be regenerated"
    assert pending["status"] == "pending", "but not deliberated on a halted tick"


def test_sweeping_twice_in_one_epoch_regenerates_once(conn):
    """`tick` advertises itself as safe to run from cron as often as you like,
    and adding a sweep to it must not cost that. Idempotence here rests on
    `expired_at_utc` keeping the row out of the second scan, not on the wake's
    dedupe key alone."""
    _setup(conn)
    cell = _make_cell(conn, "a")
    grant = _stale_grant(conn, cell)

    first = _tick(conn)
    second = _tick(conn)

    assert first.grants_expired == 1
    assert second.grants_expired == 0
    wakes = conn.execute(
        "SELECT COUNT(*) AS n FROM event_inbox WHERE dedupe_key = ?",
        (f"grant-expiry:{grant.grant_id}",),
    ).fetchone()["n"]
    assert wakes == 1
