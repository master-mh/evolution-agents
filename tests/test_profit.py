"""§1.1's two profit figures (SPEC.md §1.1, §2.2, §2.4, §2.5, §2.6; §28 Phase 9;
ADR-099).

§1.1 is the colony's stated measure of success and §32 repeats it as the final
definition. These tests defend the arithmetic, and — more importantly — the two
places where a convenient number would be a lie: a second figure computed from a
rate nobody declared (§2.4's forbidden bridge), and a cost reported as 0 because
nothing records it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    ids,
    ledger,
    lifecycle,
    payment_fees,
    profit,
    real_spend_breaker,
    reservations,
    resource_metering,
    revenue,
)
from mitosis.channel_registry import HUMAN_MINUTE_RESOURCE_COST
from mitosis.models import Book, CellType, EntrySpec, ResourceType


@pytest.fixture()
def cell(conn):
    real_spend_breaker.configure_if_absent(conn)
    created = lifecycle.create_cell(
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=10_000,
        book=Book.USD_REAL,
        idempotency_key="profit-cell",
    )
    _fund(conn, created.cell_id, Book.RESOURCE, "RESOURCE", 100_000)
    return created


def _fund(conn, cell_id, book, currency, amount):
    ledger.post_transaction(
        conn,
        book=book,
        currency=currency,
        transaction_type="test_funding",
        idempotency_key=f"fund:{book.value}:{cell_id}",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
            EntrySpec(account_id=f"cell:{cell_id}:cash", amount_minor_units=amount, cell_id=cell_id),
        ],
    )


def _spend(conn, cell, amount, *, key="spend"):
    """Real spend the way production makes it: reserve, then settle to
    external_expense."""
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=cell.book,
        currency="USD",
        maximum_amount=amount,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key=key,
    )
    reservations.settle(
        conn, reservation.reservation_id, settled_amount=amount,
        destination_account_id="external_expense",
    )


def _human_minutes(conn, cell, *, billed, subsidised, key="hm"):
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.RESOURCE,
        currency="RESOURCE",
        maximum_amount=billed * HUMAN_MINUTE_RESOURCE_COST,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key=f"res:{key}",
    )
    resource_metering.record_usage(
        conn,
        cell_id=cell.cell_id,
        reservation_id=reservation.reservation_id,
        resource_type=ResourceType.HUMAN_MINUTES,
        quantity=billed,
        minor_units=billed * HUMAN_MINUTE_RESOURCE_COST,
        idempotency_key=f"usage:{key}",
        metadata={"subsidised_human_minutes": subsidised},
    )


def _local_call(conn, cell, *, units, key="local"):
    """A model_calls row for a locally-hosted model, with its RESOURCE metering —
    §1.1's "free tier": zero in USD_REAL, real compute on someone's machine."""
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.RESOURCE,
        currency="RESOURCE",
        maximum_amount=units,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key=f"res:{key}",
    )
    resource_metering.record_usage(
        conn,
        cell_id=cell.cell_id,
        reservation_id=reservation.reservation_id,
        resource_type=ResourceType.MODEL_CALLS,
        quantity=1,
        minor_units=units,
        idempotency_key=f"usage:{key}",
    )
    # `model_calls.real_reservation_id` is NOT NULL: even a local model's call
    # reserves in USD_REAL, at a price of zero. That is the point of the free
    # tier — the accounting path is identical and the money is someone else's.
    real = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_REAL,
        currency="USD",
        maximum_amount=1,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key=f"res-real:{key}",
    )
    model_call_id = ids.new_id()
    conn.execute(
        """
        INSERT INTO model_calls (
            model_call_id, cell_id, status, provider, requested_model,
            pricing_table_version, user_prompt_hash, real_reservation_id,
            resource_reservation_id, created_at_utc, idempotency_key
        ) VALUES (?, ?, 'succeeded', 'ollama', 'qwen2.5', 'test', 'hash', ?, ?, ?, ?)
        """,
        (
            model_call_id,
            cell.cell_id,
            real.reservation_id,
            reservation.reservation_id,
            datetime.now(timezone.utc).isoformat(),
            f"call:{model_call_id}",
        ),
    )
    conn.commit()
    return model_call_id


# --- REAL_SETTLED_NET_PROFIT --------------------------------------------------


def test_an_empty_colony_reports_zero_profit_and_names_what_it_cannot_measure(conn):
    report = profit.report(conn)
    assert report.real_settled_net_profit_minor_units == 0
    assert profit.UNMEASURED_OPERATING_COSTS in report.unmeasured
    assert profit.UNMEASURED_DONATED_INFRASTRUCTURE in report.unmeasured


def test_the_first_figure_is_exactly_ones_formula(conn, cell):
    """`settled revenue - refunds - chargebacks - payment fees - real spend`,
    §1.1's own order, each term reported beside the total so a reader can check
    the subtraction rather than trust it."""
    sale = revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=1_000, source="inv-1"
    )
    revenue.record_reversal(
        conn, revenue_transaction_id=sale.transaction_id, amount_minor_units=100, source="re-1"
    )
    revenue.record_reversal(
        conn, revenue_transaction_id=sale.transaction_id, amount_minor_units=50,
        source="dispute-1", kind=revenue.ReversalKind.CHARGEBACK,
    )
    payment_fees.record_payment_fee(
        conn, charged_on_transaction_id=sale.transaction_id, amount_minor_units=30,
        source="fee-1",
    )
    _spend(conn, cell, 20)

    report = profit.report(conn)

    assert report.gross_revenue_minor_units == 1_000
    assert report.refunds_minor_units == 100
    assert report.chargebacks_minor_units == 50
    assert report.payment_fees_minor_units == 30
    assert report.model_and_cloud_spend_minor_units == 20
    assert report.real_settled_net_profit_minor_units == 800


def test_a_fee_lowers_profit_by_exactly_the_fee(conn, cell):
    sale = revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=1_000, source="inv-1"
    )
    before = profit.report(conn).real_settled_net_profit_minor_units

    payment_fees.record_payment_fee(
        conn, charged_on_transaction_id=sale.transaction_id, amount_minor_units=29, source="f"
    )

    assert profit.report(conn).real_settled_net_profit_minor_units == before - 29


def test_the_report_is_derived_and_stored_nowhere(conn, cell):
    """§2.5 and Charter C3: a stored profit figure is a second answer that can
    disagree with the ledger it came from."""
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert not {t for t in tables if "profit" in t}
    revenue.record_revenue(conn, cell_id=cell.cell_id, amount_minor_units=500, source="inv-1")
    assert profit.report(conn).real_settled_net_profit_minor_units == 500


def test_the_books_never_mix(conn, cell):
    """Amendment A7 and §2.4: synthetic earnings must never read as real ones."""
    sim = lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=1_000, book=Book.USD_SIM,
        idempotency_key="sim-cell",
    )
    revenue.record_revenue(
        conn, cell_id=sim.cell_id, amount_minor_units=900, source="sim-sale", book=Book.USD_SIM
    )
    revenue.record_revenue(conn, cell_id=cell.cell_id, amount_minor_units=100, source="real-sale")

    assert profit.report(conn, Book.USD_REAL).gross_revenue_minor_units == 100
    assert profit.report(conn, Book.USD_SIM).gross_revenue_minor_units == 900


def test_the_resource_book_has_no_profit(conn):
    with pytest.raises(profit.ProfitError, match="shadow-price book"):
        profit.report(conn, Book.RESOURCE)


# --- AUTONOMY_ADJUSTED_PROFIT -------------------------------------------------


def test_without_a_declared_rate_the_second_figure_abstains(conn, cell):
    """§2.4 forbids this module inventing a RESOURCE→USD rate, and 0 would read
    as "nothing was subsidised" — the claim §1.1 exists to disprove. The labour
    is still reported; only the money-equivalent is withheld."""
    _human_minutes(conn, cell, billed=30, subsidised=8)

    report = profit.report(conn)

    assert report.autonomy_adjusted_profit_minor_units is None
    assert report.shadow_cost_minor_units is None
    assert profit.UNMEASURED_NO_SHADOW_RATE in report.unmeasured
    assert report.human_minutes == 38
    assert report.human_minutes_subsidised == 8
    assert report.human_shadow_resource_units == 38 * HUMAN_MINUTE_RESOURCE_COST


def test_a_declared_rate_prices_human_labour_and_local_compute(conn, cell):
    revenue.record_revenue(conn, cell_id=cell.cell_id, amount_minor_units=1_000, source="inv-1")
    _human_minutes(conn, cell, billed=10, subsidised=5)
    _local_call(conn, cell, units=400)
    profit.declare_shadow_rate(
        conn, micro_usd_per_resource_unit=100, declared_by="operator", note="test"
    )

    report = profit.report(conn)

    units = 15 * HUMAN_MINUTE_RESOURCE_COST + 400
    assert report.local_model_calls == 1
    assert report.local_model_resource_units == 400
    assert report.shadow_cost_minor_units == (units * 100 + 9_999) // 10_000
    assert report.autonomy_adjusted_profit_minor_units == (
        report.real_settled_net_profit_minor_units - report.shadow_cost_minor_units
    )
    assert profit.UNMEASURED_NO_SHADOW_RATE not in report.unmeasured


def test_unpaid_minutes_make_the_colony_look_more_expensive_not_less(conn, cell):
    """§1.1's point: a subsidy is a cost someone absorbed, so absorbing more of it
    must not improve the figure meant to expose it."""
    profit.declare_shadow_rate(
        conn, micro_usd_per_resource_unit=1_000, declared_by="operator"
    )
    _human_minutes(conn, cell, billed=10, subsidised=0, key="a")
    paid_only = profit.report(conn).autonomy_adjusted_profit_minor_units

    _human_minutes(conn, cell, billed=1, subsidised=20, key="b")
    with_subsidy = profit.report(conn).autonomy_adjusted_profit_minor_units

    assert with_subsidy < paid_only


def test_a_synthetic_book_abstains_on_the_second_figure(conn, cell):
    """Human minutes and compute are colony-wide RESOURCE consumption; a
    USD_REAL-equivalent subtracted from synthetic profit is §2.4's bridge."""
    profit.declare_shadow_rate(conn, micro_usd_per_resource_unit=100, declared_by="operator")
    report = profit.report(conn, Book.USD_SIM)
    assert report.autonomy_adjusted_profit_minor_units is None
    assert profit.UNMEASURED_SIM_AUTONOMY in report.unmeasured


# --- the rate is declared, never inferred -------------------------------------


def test_declaring_a_rate_is_audited_with_the_one_it_replaced(conn):
    profit.declare_shadow_rate(conn, micro_usd_per_resource_unit=100, declared_by="operator")
    profit.declare_shadow_rate(
        conn, micro_usd_per_resource_unit=250, declared_by="operator", note="revised"
    )

    rate = profit.get_shadow_rate(conn)
    assert rate.micro_usd_per_resource_unit == 250 and rate.declared_by == "operator"
    rows = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'shadow_price_declared' "
        "ORDER BY rowid"
    ).fetchall()
    assert len(rows) == 2
    assert '"before_micro_usd_per_unit":null' in rows[0]["metadata_json"]
    assert '"before_micro_usd_per_unit":100' in rows[1]["metadata_json"]
    assert '"after_micro_usd_per_unit":250' in rows[1]["metadata_json"]


@pytest.mark.parametrize("rate", [0, -1])
def test_a_rate_must_be_positive(conn, rate):
    with pytest.raises(profit.ProfitError, match="must be positive"):
        profit.declare_shadow_rate(
            conn, micro_usd_per_resource_unit=rate, declared_by="operator"
        )


def test_a_rate_must_say_who_declared_it(conn):
    with pytest.raises(profit.ProfitError, match="declared_by is required"):
        profit.declare_shadow_rate(
            conn, micro_usd_per_resource_unit=100, declared_by="   "
        )


def test_no_rate_is_the_starting_state(conn):
    assert profit.get_shadow_rate(conn) is None
