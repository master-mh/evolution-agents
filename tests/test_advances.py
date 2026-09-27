"""A held seller's working-capital advance (SPEC.md §2.3, §2.5, §28 Phase 9;
ADR-106, ADR-112).

Under the operator's 100% / 120-day reserve, the colony's first $9 sale would
leave its seller at -80 cents, unable to wake for four months. These tests
defend what the advance is: the colony's own capital, never the buyer's hold;
posted with the sale; capped per Cell across every held sale; repaid first from
the release it was lent against; and left unrepaid — the colony's loss, not the
buyer's — when the sale is refunded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    advances,
    ledger,
    liability,
    lifecycle,
    payment_fees,
    real_spend_breaker,
    reservations,
    revenue,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType


@pytest.fixture()
def cell(conn):
    real_spend_breaker.configure_if_absent(conn)
    return _cell(conn, "seller")


def _cell(conn, key, *, book=Book.USD_REAL, budget=1_000):
    return lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=budget, book=book,
        idempotency_key=f"advance-cell:{key}",
    )


def _policies(conn, *, hold=100, advance=25, cap=500):
    liability.declare_policy(
        conn, hold_basis_points=round(hold * 100), window_days=120, declared_by="operator"
    )
    if advance is not None:
        advances.declare_policy(
            conn, advance_basis_points=round(advance * 100),
            max_outstanding_minor_units=cap, declared_by="operator",
        )


def _sale(conn, cell, amount=900, *, source="gumroad-1"):
    return revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=amount, source=source, book=cell.book,
    )


def _cash(conn, cell):
    return ledger.get_balance(conn, cell_cash(cell.cell_id), cell.book)


def _after_window():
    return datetime.now(timezone.utc) + timedelta(days=121)


# --- the advance -------------------------------------------------------------------


def test_a_held_seller_is_advanced_the_declared_share(conn, cell):
    _policies(conn, advance=25)
    cash = _cash(conn, cell)

    _sale(conn, cell, 900)

    assert _cash(conn, cell) == cash + 225
    assert advances.outstanding(conn, cell.cell_id) == 225
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_chain(conn)


def test_the_buyers_hold_is_never_touched_by_an_advance(conn, cell):
    """The whole design: the colony lends its own capital. A refund is still met
    in full from money set aside for it."""
    _policies(conn, advance=100, cap=10_000)

    _sale(conn, cell, 900)

    assert liability.cell_held(conn, cell.cell_id) == 900
    assert liability.colony_held(conn, Book.USD_REAL) == 900


def test_the_first_live_sale_leaves_its_seller_able_to_wake(conn):
    """The live case (2026-09-27): 60 cents of cash, a $9 sale fully held, a
    $1.40 fee from cash — -80 cents without an advance, and Charter C4 refuses
    every wake. With a 25% advance the seller can still reserve a call."""
    # The live colony's caps (raised 2026-09-27 so one sale's fee fits the hour).
    real_spend_breaker.configure_if_absent(conn)
    real_spend_breaker.set_limits(conn, real_spend_breaker.get_limits(conn).model_copy(
        update={"per_hour_minor_units": 300, "per_day_minor_units": 1_000},
    ))
    seller = _cell(conn, "live", budget=60)
    _policies(conn, advance=25)
    sale = _sale(conn, seller, 900)
    payment_fees.record_payment_fee(
        conn, charged_on_transaction_id=sale.transaction_id, amount_minor_units=140,
        source="gumroad-fee-1",
    )

    assert _cash(conn, seller) == 60 + 225 - 140
    reservations.request(
        conn, cell_id=seller.cell_id, book=Book.USD_REAL, currency="USD",
        maximum_amount=20, expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key="next-wake",
    )


def test_the_sale_and_its_advance_commit_together(conn, cell, monkeypatch):
    """A crash between them must not record a held sale whose seller was
    promised working capital it never received — or the reverse."""
    _policies(conn)

    def boom(*args, **kwargs):
        raise RuntimeError("crash between hold and advance")

    monkeypatch.setattr(advances, "_advance_locked", boom)
    with pytest.raises(RuntimeError):
        _sale(conn, cell)

    assert revenue.gross_revenue(conn, cell.cell_id) == 0
    assert liability.colony_held(conn, Book.USD_REAL) == 0


def test_without_a_policy_or_at_zero_percent_nothing_is_advanced(conn, cell):
    _policies(conn, advance=None)
    cash = _cash(conn, cell)
    _sale(conn, cell, 900, source="a")
    assert _cash(conn, cell) == cash

    advances.declare_policy(
        conn, advance_basis_points=0, max_outstanding_minor_units=500, declared_by="operator"
    )
    _sale(conn, cell, 900, source="b")
    assert _cash(conn, cell) == cash
    assert advances.outstanding(conn, cell.cell_id) == 0


def test_what_a_cell_owes_is_capped_across_all_its_held_sales(conn, cell):
    """A per-sale cap would let a Cell owe without limit by selling often; the
    bound on the colony's exposure is per Cell."""
    _policies(conn, advance=25, cap=300)

    _sale(conn, cell, 900, source="a")
    _sale(conn, cell, 900, source="b")
    _sale(conn, cell, 900, source="c")

    assert advances.outstanding(conn, cell.cell_id) == 300


def test_an_advance_rounds_down(conn, cell):
    """The hold rounds up and the advance down: each in the direction that
    protects someone else's money."""
    _policies(conn, advance=25)

    _sale(conn, cell, 901)

    assert advances.outstanding(conn, cell.cell_id) == 225


def test_a_replayed_sale_is_not_advanced_twice(conn, cell):
    _policies(conn)
    _sale(conn, cell, 900)
    cash = _cash(conn, cell)

    _sale(conn, cell, 900)

    assert _cash(conn, cell) == cash
    assert advances.outstanding(conn, cell.cell_id) == 225


def test_a_synthetic_sale_is_never_advanced(conn):
    """Only a real sale is held, and only a hold is advanced against."""
    real_spend_breaker.configure_if_absent(conn)
    sim = _cell(conn, "sim", book=Book.USD_SIM)
    _policies(conn)
    cash = _cash(conn, sim)

    _sale(conn, sim, 900)

    assert _cash(conn, sim) == cash + 900
    assert advances.outstanding(conn, sim.cell_id) == 0


def test_a_dead_cell_is_not_advanced(conn, cell):
    """Working capital for a Cell that can never wake funds nothing."""
    _policies(conn)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    _sale(conn, cell, 900)

    assert advances.outstanding(conn, cell.cell_id) == 0


def test_an_advance_is_neither_revenue_nor_spend(conn, cell):
    """Capital movement: §10.5's net contribution and §1.1's revenue must not
    see the colony lending a Cell its own future money."""
    _policies(conn)

    _sale(conn, cell, 900)

    assert revenue.gross_revenue(conn, cell.cell_id) == 900
    assert ledger.spend_by_book(conn, cell.cell_id).get("USD_REAL", 0) == 0


# --- repayment ---------------------------------------------------------------------


def test_the_colony_is_repaid_first_when_the_hold_releases(conn, cell):
    _policies(conn)
    cash = _cash(conn, cell)
    _sale(conn, cell, 900)
    seed = ledger.get_balance(conn, advances.FUNDING_ACCOUNT, Book.USD_REAL)

    liability.release_due(conn, now=_after_window())

    assert advances.outstanding(conn, cell.cell_id) == 0
    assert _cash(conn, cell) == cash + 900
    assert ledger.get_balance(conn, advances.FUNDING_ACCOUNT, Book.USD_REAL) == seed + 225
    assert ledger.verify_conservation(conn, Book.USD_REAL)


def test_a_refunded_sale_is_paid_in_full_and_its_advance_stays_owed(conn, cell):
    """The buyer bears none of the advance's risk: the refund comes from the
    hold, and the colony's loss is the advance left unrepaid."""
    _policies(conn)
    sale = _sale(conn, cell, 900)
    cash = _cash(conn, cell)

    revenue.record_reversal(
        conn, revenue_transaction_id=sale.transaction_id, amount_minor_units=900,
        source="refund-1",
    )
    liability.release_due(conn, now=_after_window())

    assert _cash(conn, cell) == cash
    assert advances.outstanding(conn, cell.cell_id) == 225


def test_a_later_release_repays_an_earlier_refunded_sales_advance(conn, cell):
    """Owed per Cell, not per sale: a refunded sale's advance is repaid from the
    next release the Cell receives."""
    _policies(conn, cap=1_000)
    refunded = _sale(conn, cell, 900, source="a")
    revenue.record_reversal(
        conn, revenue_transaction_id=refunded.transaction_id, amount_minor_units=900,
        source="refund-a",
    )
    _sale(conn, cell, 900, source="b")
    assert advances.outstanding(conn, cell.cell_id) == 450

    liability.release_due(conn, now=_after_window())

    assert advances.outstanding(conn, cell.cell_id) == 0


# --- the policy --------------------------------------------------------------------


@pytest.mark.parametrize("bps, cap, by", [(-1, 500, "op"), (10_001, 500, "op"),
                                           (2_500, -1, "op"), (2_500, 500, " ")])
def test_a_policy_outside_its_bounds_is_refused(conn, bps, cap, by):
    with pytest.raises(advances.AdvanceError):
        advances.declare_policy(
            conn, advance_basis_points=bps, max_outstanding_minor_units=cap, declared_by=by
        )
