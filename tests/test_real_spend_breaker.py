from datetime import datetime, timedelta, timezone

import pytest

from mitosis import ledger, real_spend_breaker, reservations
from mitosis.models import Book, DEFAULT_REAL_SPEND_LIMITS, RealSpendLimits

FUTURE = datetime.now(timezone.utc) + timedelta(days=1)


def fund(conn, cell_id="cell-1", amount=100_000, book=Book.USD_REAL):
    ledger.post_transaction(
        conn,
        book=book,
        currency="USD",
        transaction_type="seed_fund",
        idempotency_key=f"seed:{cell_id}:{book.value}",
        entries=[
            ledger.EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
            ledger.EntrySpec(account_id=f"cell:{cell_id}:cash", amount_minor_units=amount),
        ],
    )


def test_get_limits_returns_defaults_when_unconfigured(conn):
    assert real_spend_breaker.get_limits(conn) == DEFAULT_REAL_SPEND_LIMITS


def test_configure_if_absent_sets_once_without_audit(conn):
    first = real_spend_breaker.configure_if_absent(conn)
    assert first == DEFAULT_REAL_SPEND_LIMITS
    count = conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()["n"]
    assert count == 0

    second = real_spend_breaker.configure_if_absent(conn)
    assert second == first


def test_set_limits_always_applies_and_audits(conn):
    new_limits = RealSpendLimits(
        per_request_minor_units=10, per_hour_minor_units=20, per_day_minor_units=30,
        per_month_minor_units=40, max_concurrent_reserved_minor_units=50, provider_limits={},
    )
    result = real_spend_breaker.set_limits(conn, new_limits)
    assert result == new_limits
    assert real_spend_breaker.get_limits(conn) == new_limits

    events = conn.execute("SELECT event_type FROM audit_events").fetchall()
    assert len(events) == 1


def test_lowering_limits_is_not_flagged_as_raised(conn):
    real_spend_breaker.set_limits(conn, DEFAULT_REAL_SPEND_LIMITS)
    lower = DEFAULT_REAL_SPEND_LIMITS.model_copy(update={"per_request_minor_units": 1})
    real_spend_breaker.set_limits(conn, lower)
    event_types = [r["event_type"] for r in conn.execute("SELECT event_type FROM audit_events")]
    assert event_types[-1] == "real_spend_limit_configured"


def test_raising_a_limit_is_flagged_and_field_named(conn):
    real_spend_breaker.set_limits(conn, DEFAULT_REAL_SPEND_LIMITS)
    raised = DEFAULT_REAL_SPEND_LIMITS.model_copy(
        update={"per_day_minor_units": DEFAULT_REAL_SPEND_LIMITS.per_day_minor_units + 1}
    )
    real_spend_breaker.set_limits(conn, raised)
    row = conn.execute(
        "SELECT event_type, metadata_json FROM audit_events ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    assert row["event_type"] == "real_spend_limit_raised"
    assert "per_day_minor_units" in row["metadata_json"]


def test_check_allows_within_all_caps(conn):
    fund(conn)
    real_spend_breaker.set_limits(conn, DEFAULT_REAL_SPEND_LIMITS)
    real_spend_breaker.check(conn, requested_amount=5)  # well under every default cap


def test_check_denies_over_per_request_cap(conn):
    limits = DEFAULT_REAL_SPEND_LIMITS.model_copy(update={"per_request_minor_units": 10})
    real_spend_breaker.set_limits(conn, limits)
    with pytest.raises(real_spend_breaker.RealSpendCapExceededError, match="per-request"):
        real_spend_breaker.check(conn, requested_amount=11)


def test_check_denies_over_concurrent_reserved_cap(conn):
    fund(conn)
    limits = DEFAULT_REAL_SPEND_LIMITS.model_copy(
        update={"per_request_minor_units": 1000, "max_concurrent_reserved_minor_units": 100}
    )
    real_spend_breaker.set_limits(conn, limits)
    reservations.request(
        conn, cell_id="cell-1", book=Book.USD_REAL, currency="USD",
        maximum_amount=90, expires_at=FUTURE, idempotency_key="r1",
    )
    with pytest.raises(real_spend_breaker.RealSpendCapExceededError, match="concurrent-reserved"):
        real_spend_breaker.check(conn, requested_amount=20)


def test_check_denies_over_hour_cap_from_settled_plus_reserved(conn):
    fund(conn)
    limits = DEFAULT_REAL_SPEND_LIMITS.model_copy(
        update={
            "per_request_minor_units": 1000,
            "max_concurrent_reserved_minor_units": 1000,
            "per_hour_minor_units": 100,
        }
    )
    real_spend_breaker.set_limits(conn, limits)
    r1 = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_REAL, currency="USD",
        maximum_amount=60, expires_at=FUTURE, idempotency_key="r1",
    )
    reservations.settle(conn, r1.reservation_id, settled_amount=60, destination_account_id="external_expense")
    # 60 already settled within the hour; requesting 50 more projects to 110 > 100
    with pytest.raises(real_spend_breaker.RealSpendCapExceededError, match="hour"):
        real_spend_breaker.check(conn, requested_amount=50)
    # but 40 more (settled 60 + reserved 40 = 100) fits exactly
    real_spend_breaker.check(conn, requested_amount=40)


def test_reservations_request_enforces_breaker_for_usd_real(conn):
    fund(conn)
    limits = DEFAULT_REAL_SPEND_LIMITS.model_copy(update={"per_request_minor_units": 10})
    real_spend_breaker.set_limits(conn, limits)
    with pytest.raises(real_spend_breaker.RealSpendCapExceededError):
        reservations.request(
            conn, cell_id="cell-1", book=Book.USD_REAL, currency="USD",
            maximum_amount=11, expires_at=FUTURE, idempotency_key="r1",
        )
    # denied request must not have consumed the idempotency key or touched the ledger
    assert reservations.get_reservation_by_idempotency_key(conn, "r1") is None
    assert ledger.get_balance(conn, "cell:cell-1:cash", Book.USD_REAL) == 100_000


def test_reservations_request_ignores_breaker_for_usd_sim(conn):
    fund(conn, book=Book.USD_SIM)
    limits = DEFAULT_REAL_SPEND_LIMITS.model_copy(update={"per_request_minor_units": 10})
    real_spend_breaker.set_limits(conn, limits)  # USD_REAL-only limits
    # a USD_SIM reservation far exceeding the USD_REAL per-request cap must succeed
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=99_999, expires_at=FUTURE, idempotency_key="r1",
    )
    assert r.status.value == "reserved"


def test_snapshot_reflects_current_exposure(conn):
    fund(conn)
    real_spend_breaker.set_limits(conn, DEFAULT_REAL_SPEND_LIMITS)
    r1 = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_REAL, currency="USD",
        maximum_amount=10, expires_at=FUTURE, idempotency_key="r1",
    )
    snap = real_spend_breaker.snapshot(conn)
    assert snap.concurrent_reserved_minor_units == 10
    assert snap.spend_last_hour_minor_units == 0

    reservations.settle(conn, r1.reservation_id, settled_amount=10, destination_account_id="external_expense")
    snap = real_spend_breaker.snapshot(conn)
    assert snap.concurrent_reserved_minor_units == 0
    assert snap.spend_last_hour_minor_units == 10
    assert snap.spend_last_day_minor_units == 10
    assert snap.spend_last_month_minor_units == 10


def test_spend_outside_window_does_not_count(conn):
    fund(conn)
    real_spend_breaker.set_limits(conn, DEFAULT_REAL_SPEND_LIMITS)
    r1 = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_REAL, currency="USD",
        maximum_amount=10, expires_at=FUTURE, idempotency_key="r1",
    )
    reservations.settle(conn, r1.reservation_id, settled_amount=10, destination_account_id="external_expense")
    far_future = datetime.now(timezone.utc) + timedelta(days=40)
    snap = real_spend_breaker.snapshot(conn, now=far_future)
    assert snap.spend_last_hour_minor_units == 0
    assert snap.spend_last_day_minor_units == 0
    assert snap.spend_last_month_minor_units == 0
