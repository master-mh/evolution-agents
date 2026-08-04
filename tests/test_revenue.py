"""Revenue: money entering the colony (SPEC.md §31, §2.2).

The first path by which a Cell's balance can rise for a reason other than
capital allocation, and therefore the first half of a fitness signal. These
tests lean on the two things that would quietly corrupt that signal: revenue
counted as spend (or vice versa), and revenue posted without attribution.
"""

from __future__ import annotations

import pytest

from mitosis import ledger, lifecycle, real_spend_breaker, reservations, revenue
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType, EntrySpec, RealSpendLimits

from datetime import datetime, timedelta, timezone


@pytest.fixture()
def cell(conn):
    real_spend_breaker.configure_if_absent(conn)
    return lifecycle.create_cell(
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=1_000,
        book=Book.USD_REAL,
        idempotency_key="revenue-cell",
    )


def test_revenue_credits_the_cell_and_debits_the_revenue_account(conn, cell):
    before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)

    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=500, source="inv-001"
    )

    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) == before + 500
    # The revenue account holds gross earnings negated — an external source of
    # value, same convention as external_capital.
    assert ledger.get_balance(conn, revenue.REVENUE_ACCOUNT, Book.USD_REAL) == -500
    assert revenue.colony_revenue(conn) == 500
    assert revenue.total_revenue(conn, cell.cell_id) == 500
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_chain(conn)


def test_revenue_does_not_move_the_spend_breaker(conn, cell):
    """Charter C5 bounds gross spend, not a net position. A Cell that earns must
    not thereby earn permission to spend past a cap — the single most tempting
    wrong turn available here."""
    now = datetime.now(timezone.utc)
    before = real_spend_breaker.snapshot(conn, now=now)

    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=10_000, source="big-customer"
    )

    after = real_spend_breaker.snapshot(conn, now=now)
    assert after.spend_last_hour_minor_units == before.spend_last_hour_minor_units == 0
    assert after.spend_last_day_minor_units == before.spend_last_day_minor_units == 0
    assert after.spend_last_month_minor_units == before.spend_last_month_minor_units == 0


def test_revenue_raises_spending_power_through_the_c4_balance_check(conn, cell):
    """The one intended coupling: earnings are cash, and Charter C4 lets a Cell
    reserve up to its cash. Distinct from the breaker, which is unmoved."""
    # Lift the C5 caps clear of the amounts under test, so the failure below is
    # unambiguously C4's balance check and not the per-request cap firing first.
    real_spend_breaker.set_limits(
        conn,
        RealSpendLimits(
            per_request_minor_units=100_000,
            per_hour_minor_units=100_000,
            per_day_minor_units=100_000,
            per_month_minor_units=100_000,
            max_concurrent_reserved_minor_units=100_000,
            provider_limits={},
        ),
    )
    cash = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)
    with pytest.raises(reservations.InsufficientBalanceError):
        reservations.request(
            conn,
            cell_id=cell.cell_id,
            book=Book.USD_REAL,
            currency="USD",
            maximum_amount=cash + 100,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            idempotency_key="too-big",
        )

    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=100, source="inv-002"
    )
    reserved = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_REAL,
        currency="USD",
        maximum_amount=cash + 100,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key="now-affordable",
    )
    assert reserved.maximum_amount == cash + 100


def test_revenue_requires_attribution(conn, cell):
    for bad_source in ("", "   "):
        with pytest.raises(revenue.RevenueError, match="source is required"):
            revenue.record_revenue(
                conn, cell_id=cell.cell_id, amount_minor_units=100, source=bad_source
            )


@pytest.mark.parametrize("amount", [0, -1, -500])
def test_revenue_must_be_positive(conn, cell, amount):
    with pytest.raises(revenue.RevenueError, match="must be positive"):
        revenue.record_revenue(
            conn, cell_id=cell.cell_id, amount_minor_units=amount, source="inv"
        )


def test_revenue_cannot_be_recorded_in_the_resource_book(conn, cell):
    """Nobody pays a colony in compute units, and allowing it would let a Cell
    top up its metering budget by declaring revenue."""
    with pytest.raises(revenue.RevenueError, match="shadow-price book"):
        revenue.record_revenue(
            conn,
            cell_id=cell.cell_id,
            amount_minor_units=100,
            source="inv",
            book=Book.RESOURCE,
        )


def test_revenue_to_unknown_cell_is_refused(conn):
    with pytest.raises(revenue.RevenueError, match="no such cell"):
        revenue.record_revenue(
            conn, cell_id="not-a-cell", amount_minor_units=100, source="inv"
        )
    assert ledger.get_balance(conn, revenue.REVENUE_ACCOUNT, Book.USD_REAL) == 0


def test_the_same_attributed_payment_cannot_be_posted_twice(conn, cell):
    """Double-posting one payment would double a Cell's apparent fitness, which
    is the failure mode that matters once selection reads these numbers."""
    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=500, source="inv-003"
    )
    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=500, source="inv-003"
    )
    assert revenue.total_revenue(conn, cell.cell_id) == 500


def test_a_dead_cell_can_still_receive_revenue(conn, cell):
    """Payment arrives after the work, sometimes after the worker. A coroner
    report that omitted final earnings would misstate what it exists to record."""
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")
    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=250, source="late-payment"
    )
    assert revenue.total_revenue(conn, cell.cell_id) == 250

    event = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'cell_revenue_recorded'"
    ).fetchone()
    assert '"cell_status":"dead"' in event["metadata_json"]


def test_revenue_is_audited_with_its_source(conn, cell):
    revenue.record_revenue(
        conn,
        cell_id=cell.cell_id,
        amount_minor_units=750,
        source="acme-invoice-42",
        note="first sale",
    )
    row = conn.execute(
        "SELECT cell_id, metadata_json FROM audit_events WHERE event_type = 'cell_revenue_recorded'"
    ).fetchone()
    assert row["cell_id"] == cell.cell_id
    assert "acme-invoice-42" in row["metadata_json"]
    assert "first sale" in row["metadata_json"]


def test_usd_sim_revenue_is_tracked_separately_from_usd_real(conn, cell):
    """Amendment A7's separation: simulated earnings must never read as real
    ones, or the promotion ladder is measuring the wrong colony."""
    ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency=Book.USD_SIM.value,
        transaction_type="test_funding",
        idempotency_key="sim-seed",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-100),
            EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=100),
        ],
    )
    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=400, source="sim", book=Book.USD_SIM
    )
    assert revenue.total_revenue(conn, cell.cell_id, Book.USD_SIM) == 400
    assert revenue.total_revenue(conn, cell.cell_id, Book.USD_REAL) == 0
    assert ledger.verify_conservation(conn, Book.USD_SIM)
