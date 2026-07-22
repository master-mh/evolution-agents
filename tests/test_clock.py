from datetime import datetime, timedelta, timezone

import pytest

from mitosis import clock
from mitosis.models import ClockMode

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_unconfigured_clock_falls_back_to_wall_time(conn):
    before = datetime.now(timezone.utc)
    now = clock.now(conn)
    after = datetime.now(timezone.utc)
    assert before <= now <= after


def test_initialize_sets_baseline(conn):
    state = clock.initialize_if_absent(conn, mode=ClockMode.PAUSED, start_at=START)
    assert state.mode == ClockMode.PAUSED
    assert state.checkpoint_simulated_at_utc == START
    assert clock.now(conn) == START


def test_initialize_is_set_once(conn):
    clock.initialize_if_absent(conn, mode=ClockMode.PAUSED, start_at=START)
    second = clock.initialize_if_absent(
        conn, mode=ClockMode.REALTIME, start_at=START + timedelta(days=100)
    )
    assert second.mode == ClockMode.PAUSED
    assert clock.now(conn) == START


def test_initialize_rejects_naive_datetime(conn):
    with pytest.raises(clock.ClockError):
        clock.initialize_if_absent(conn, start_at=datetime(2026, 1, 1))


@pytest.mark.parametrize("mode", [ClockMode.PAUSED, ClockMode.STEP])
def test_paused_and_step_modes_do_not_advance_with_wall_time(conn, mode):
    clock.initialize_if_absent(conn, mode=mode, start_at=START)
    wall_now = datetime.now(timezone.utc) + timedelta(hours=5)
    assert clock.now(conn, wall_now=wall_now) == START


def test_realtime_mode_advances_one_to_one_with_wall_time(conn):
    clock.initialize_if_absent(conn, mode=ClockMode.REALTIME, start_at=START)
    state = clock.get_state(conn)
    wall_now = state.checkpoint_wall_at_utc + timedelta(seconds=30)
    assert clock.now(conn, wall_now=wall_now) == START + timedelta(seconds=30)


def test_accelerated_mode_scales_by_rate(conn):
    clock.initialize_if_absent(
        conn, mode=ClockMode.ACCELERATED, simulated_seconds_per_wall_second=86400.0, start_at=START
    )
    state = clock.get_state(conn)
    wall_now = state.checkpoint_wall_at_utc + timedelta(seconds=1)
    assert clock.now(conn, wall_now=wall_now) == START + timedelta(days=1)


def test_clock_never_runs_backwards_from_wall_clock_skew(conn):
    clock.initialize_if_absent(conn, mode=ClockMode.REALTIME, start_at=START)
    state = clock.get_state(conn)
    wall_before_checkpoint = state.checkpoint_wall_at_utc - timedelta(seconds=10)
    assert clock.now(conn, wall_now=wall_before_checkpoint) == START


def test_advance_moves_simulated_time_forward(conn):
    clock.initialize_if_absent(conn, mode=ClockMode.PAUSED, start_at=START)
    new_time = clock.advance(conn, timedelta(days=1))
    assert new_time == START + timedelta(days=1)
    assert clock.now(conn) == START + timedelta(days=1)


def test_advance_rejects_negative_delta(conn):
    clock.initialize_if_absent(conn, start_at=START)
    with pytest.raises(clock.ClockError):
        clock.advance(conn, timedelta(days=-1))
    assert clock.now(conn) == START  # rejected call must not have partially applied


def test_advance_is_cumulative(conn):
    clock.initialize_if_absent(conn, mode=ClockMode.PAUSED, start_at=START)
    clock.advance(conn, timedelta(days=1))
    clock.advance(conn, timedelta(hours=12))
    assert clock.now(conn) == START + timedelta(days=1, hours=12)


def test_advance_works_regardless_of_mode(conn):
    clock.initialize_if_absent(conn, mode=ClockMode.REALTIME, start_at=START)
    state = clock.get_state(conn)
    # advance() is called "at" the checkpoint instant, so no wall-drift is folded in
    new_time = clock.advance(conn, timedelta(days=2))
    assert new_time >= START + timedelta(days=2)


def test_set_mode_does_not_cause_a_jump(conn):
    clock.initialize_if_absent(conn, mode=ClockMode.PAUSED, start_at=START)
    before = clock.now(conn)
    clock.set_mode(conn, ClockMode.REALTIME)
    after = clock.now(conn)
    assert abs((after - before).total_seconds()) < 1  # re-anchored, not jumped


def test_set_mode_changes_subsequent_behavior(conn):
    clock.initialize_if_absent(conn, mode=ClockMode.PAUSED, start_at=START)
    clock.set_mode(conn, ClockMode.REALTIME)
    state = clock.get_state(conn)
    wall_now = state.checkpoint_wall_at_utc + timedelta(seconds=10)
    assert clock.now(conn, wall_now=wall_now) == state.checkpoint_simulated_at_utc + timedelta(seconds=10)


def test_set_mode_can_change_accelerated_rate(conn):
    clock.initialize_if_absent(conn, mode=ClockMode.PAUSED, start_at=START)
    clock.set_mode(conn, ClockMode.ACCELERATED, simulated_seconds_per_wall_second=10.0)
    state = clock.get_state(conn)
    assert state.mode == ClockMode.ACCELERATED
    assert state.simulated_seconds_per_wall_second == 10.0
    wall_now = state.checkpoint_wall_at_utc + timedelta(seconds=2)
    assert clock.now(conn, wall_now=wall_now) == state.checkpoint_simulated_at_utc + timedelta(seconds=20)
