"""Liability reserves (SPEC.md §2.3, §10.2, §16.3, §28 Phase 9; ADR-106).

§28 Phase 9 trades with "full liability reserves" and nothing posted to
`liability_reserve`, so a real sale was spendable the minute it arrived while the
buyer could still take it back. These tests defend what a hold is: the sale's own
money set aside in the sale's own transaction, restricted rather than spent, paid
out to meet a refund, returned when the window closes — and never reaching back
to a sale recorded before the policy that would have held it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    accounts,
    death,
    ledger,
    liability,
    lifecycle,
    payment_fees,
    profit,
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
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=budget,
        book=book,
        idempotency_key=f"liability-cell:{key}",
    )


def _policy(conn, *, percent=100, days=120, by="operator"):
    return liability.declare_policy(
        conn, hold_basis_points=round(percent * 100), window_days=days, declared_by=by
    )


def _sale(conn, cell, amount=500, *, source="inv-1", **kwargs):
    return revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=amount, source=source, book=cell.book,
        **kwargs,
    )


def _cash(conn, cell):
    return ledger.get_balance(conn, cell_cash(cell.cell_id), cell.book)


def _held(conn):
    return liability.colony_held(conn, Book.USD_REAL)


def _after_window(days=120):
    return datetime.now(timezone.utc) + timedelta(days=days, hours=1)


# --- the hold --------------------------------------------------------------------


def test_with_no_policy_a_real_sale_is_not_held(conn, cell):
    """ADR-042: no policy is an abstention, not a zero-percent hold — the sale
    lands in cash as it always did, and the profit report says nothing held it."""
    cash = _cash(conn, cell)
    _sale(conn, cell, 500)

    assert _cash(conn, cell) == cash + 500
    assert _held(conn) == 0
    assert liability.holds(conn) == []
    assert profit.UNMEASURED_NO_RESERVE_POLICY in profit.report(conn).unmeasured


def test_a_full_hold_sets_the_whole_sale_aside_in_its_own_transaction(conn, cell):
    """§28 Phase 9: with a 100% policy the sale reaches the reserve, not the
    Cell's spendable cash, and the hold names the payment it provisions for."""
    _policy(conn, percent=100)
    cash = _cash(conn, cell)

    sale = _sale(conn, cell, 500)

    assert _cash(conn, cell) == cash, "a fully held sale must not be spendable"
    assert _held(conn) == 500
    assert liability.cell_held(conn, cell.cell_id) == 500
    [hold] = liability.holds(conn)
    assert hold.payment_transaction_id == sale.transaction_id
    assert hold.remaining_minor_units == 500
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_chain(conn)


def test_a_hold_is_restricted_cash_not_spend(conn, cell):
    """§2.3 puts reserves beside cash; §10.2 keeps "unsettled liability exposure"
    its own dimension. A hold that counted as spend would tell the Cell it had
    consumed a sale it had only been asked to wait for, and fold exposure into
    net contribution — the scalar collapse §10.2 forbids."""
    _policy(conn, percent=100)
    spent = ledger.spend_by_book(conn, cell.cell_id).get(Book.USD_REAL.value, 0)

    _sale(conn, cell, 500)

    assert ledger.spend_by_book(conn, cell.cell_id).get(Book.USD_REAL.value, 0) == spent
    assert revenue.net_revenue(conn, cell.cell_id) == 500
    assert "liability_reserve" in accounts.CAPITAL_ACCOUNTS
    assert "liability_reserve" not in accounts.SPEND_DESTINATIONS
    assert not accounts.unclassified_accounts()


def test_a_held_cell_cannot_reserve_against_the_held_money(conn):
    """Charter C4 reads cash, so the hold is what stops a Cell spending a sale
    that may yet be refunded — the reason the reserve exists."""
    real_spend_breaker.configure_if_absent(conn)
    poor = _cell(conn, "poor", budget=10)
    _policy(conn, percent=100)
    _sale(conn, poor, 500)

    with pytest.raises(reservations.InsufficientBalanceError):
        reservations.request(
            conn,
            cell_id=poor.cell_id,
            book=Book.USD_REAL,
            currency="USD",
            maximum_amount=20,  # under the breaker's per-request cap, over the cash
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            idempotency_key="spend-held",
        )


def test_a_seller_whose_sale_is_held_is_not_budget_exhausted(conn):
    """Found by hand-verification: a Cell that spent its budget and then sold
    under a full reserve sits at zero cash — below it once the processor's fee
    comes out of cash while the gross is held — with the sale coming back when
    the window closes. §10.5's `budget_exhausted` read that as "no money, nothing
    in flight" and `reap` would have killed the colony's first successful seller."""
    real_spend_breaker.configure_if_absent(conn)
    seller = _cell(conn, "held-seller", budget=10)
    _policy(conn, percent=100)
    sale = _sale(conn, seller, 500)
    payment_fees.record_payment_fee(
        conn, charged_on_transaction_id=sale.transaction_id, amount_minor_units=50,
        source="fee-1",
    )
    assert _cash(conn, seller) == -40

    assert death.findings(conn, seller.cell_id) == []
    assert death.reap(conn) == []


def test_a_partial_hold_rounds_up(conn, cell):
    """'Full' reserves: a share never holds a unit less than it says."""
    _policy(conn, percent=33.33)
    _sale(conn, cell, 100)
    assert _held(conn) == 34


def test_a_synthetic_sale_is_never_held(conn):
    """A refund window is a fact about real card networks; holding USD_SIM
    against a wall clock would tie the shadow economy to calendar time."""
    sim = _cell(conn, "sim", book=Book.USD_SIM)
    _policy(conn, percent=100)
    cash = _cash(conn, sim)

    _sale(conn, sim, 500)

    assert _cash(conn, sim) == cash + 500
    assert liability.colony_held(conn, Book.USD_SIM) == 0


def test_a_policy_never_reaches_back_to_a_sale_recorded_before_it(conn, cell):
    """Replaying a sale posted before any policy returns the original payment;
    it must not post a fresh hold on it, or declaring a policy would retroactively
    freeze money a Cell was already told it had."""
    first = _sale(conn, cell, 500)
    _policy(conn, percent=100)
    cash = _cash(conn, cell)

    replay = _sale(conn, cell, 500)

    assert replay.transaction_id == first.transaction_id
    assert _cash(conn, cell) == cash
    assert liability.holds(conn) == []


def test_the_sale_and_its_hold_commit_together(conn, cell, monkeypatch):
    """A crash between the two must not leave a real sale spendable that the
    policy said to hold: if the hold fails, the sale is not recorded either."""
    _policy(conn, percent=100)

    def boom(*args, **kwargs):
        raise RuntimeError("crash between sale and hold")

    monkeypatch.setattr(liability, "_hold_locked", boom)
    with pytest.raises(RuntimeError):
        _sale(conn, cell, 500)

    assert revenue.gross_revenue(conn, cell.cell_id) == 0
    assert _held(conn) == 0


# --- reversals are paid from the hold ------------------------------------------------


@pytest.mark.parametrize("kind", list(revenue.ReversalKind))
def test_a_reversal_inside_the_window_is_paid_from_the_hold(conn, cell, kind):
    """That is what the reserve is for: the refund leaves the Cell's other cash
    untouched instead of driving it negative."""
    _policy(conn, percent=100)
    cash = _cash(conn, cell)
    sale = _sale(conn, cell, 500)

    revenue.record_reversal(
        conn, revenue_transaction_id=sale.transaction_id, amount_minor_units=200,
        source="rf-1", kind=kind,
    )

    assert _cash(conn, cell) == cash, "the reversal must come out of the hold"
    [hold] = liability.holds(conn)
    assert hold.remaining_minor_units == 300
    assert revenue.net_revenue(conn, cell.cell_id) == 300
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_chain(conn)


def test_a_reversal_larger_than_a_partial_hold_takes_the_rest_from_cash(conn, cell):
    _policy(conn, percent=20)
    cash = _cash(conn, cell)
    sale = _sale(conn, cell, 500)
    assert _cash(conn, cell) == cash + 400

    revenue.record_reversal(
        conn, revenue_transaction_id=sale.transaction_id, amount_minor_units=500, source="rf-1"
    )

    assert _cash(conn, cell) == cash
    assert _held(conn) == 0


def test_a_replayed_reversal_does_not_release_twice(conn, cell):
    _policy(conn, percent=100)
    sale = _sale(conn, cell, 500)
    for _ in range(2):
        revenue.record_reversal(
            conn, revenue_transaction_id=sale.transaction_id, amount_minor_units=200,
            source="rf-1",
        )
    assert _held(conn) == 300


# --- the window --------------------------------------------------------------------


def test_nothing_is_released_before_the_window_closes(conn, cell):
    _policy(conn, percent=100, days=120)
    _sale(conn, cell, 500)

    assert liability.release_due(conn, now=datetime.now(timezone.utc) + timedelta(days=119)) == []
    assert _held(conn) == 500


def test_a_closed_window_returns_what_the_hold_still_has(conn, cell):
    _policy(conn, percent=100, days=120)
    cash = _cash(conn, cell)
    sale = _sale(conn, cell, 500)
    revenue.record_reversal(
        conn, revenue_transaction_id=sale.transaction_id, amount_minor_units=100, source="rf-1"
    )

    released = liability.release_due(conn, now=_after_window(120))

    assert len(released) == 1
    assert _cash(conn, cell) == cash + 400
    assert _held(conn) == 0
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_chain(conn)


def test_releasing_twice_releases_once(conn, cell):
    _policy(conn, percent=100, days=120)
    _sale(conn, cell, 500)
    liability.release_due(conn, now=_after_window(120))
    cash = _cash(conn, cell)

    assert liability.release_due(conn, now=_after_window(120)) == []
    assert _cash(conn, cell) == cash


def test_a_later_policy_never_shortens_a_hold_already_taken(conn, cell):
    """The window is derived from the policy in force *when the hold was taken*,
    so an operator cannot release old holds early by declaring a shorter one."""
    _policy(conn, percent=100, days=120)
    _sale(conn, cell, 500)
    _policy(conn, percent=100, days=1)

    assert liability.release_due(conn, now=_after_window(2)) == []
    [hold] = liability.holds(conn)
    assert hold.held_until_utc > datetime.now(timezone.utc) + timedelta(days=119)


# --- the policy ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bps, days, by",
    [(0, 120, "op"), (10_001, 120, "op"), (10_000, 0, "op"), (10_000, 731, "op"), (10_000, 120, " ")],
)
def test_a_policy_outside_its_bounds_is_refused(conn, bps, days, by):
    """There is no reserve-free policy (Phase 9 has no such mode), and a window
    beyond any chargeback period is a typo."""
    with pytest.raises(liability.LiabilityError):
        liability.declare_policy(conn, hold_basis_points=bps, window_days=days, declared_by=by)
    assert liability.current_policy(conn) is None


def test_policies_are_append_only_and_the_latest_wins(conn):
    _policy(conn, percent=100, days=120)
    _policy(conn, percent=50, days=30)
    assert liability.current_policy(conn).hold_basis_points == 5_000
    assert [p.window_days for p in liability.policy_history(conn)] == [30, 120]


def test_a_declared_policy_removes_the_reports_abstention(conn, cell):
    _policy(conn)
    _sale(conn, cell, 500)
    report = profit.report(conn)
    assert profit.UNMEASURED_NO_RESERVE_POLICY not in report.unmeasured
    assert report.liability_reserve_held_minor_units == 500
    assert report.real_settled_net_profit_minor_units == 500, "a hold is not a §1.1 deduction"


# --- the schema ----------------------------------------------------------------------


def test_the_provision_types_match_the_schema_check(conn, cell):
    """Migration 0042's CHECK and `PROVISION_TRANSACTION_TYPES` name the same
    pair: a link on any other type, or a hold with none, is unrepresentable."""
    _policy(conn)
    sale = _sale(conn, cell, 500)
    for transaction_type in ("cell_revenue", "payment_fee"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE ledger_transactions SET provisions_for_transaction_id = ? "
                "WHERE transaction_id = ? AND transaction_type = ?",
                (sale.transaction_id, sale.transaction_id, transaction_type),
            ) if transaction_type == "cell_revenue" else conn.execute(
                "INSERT INTO ledger_transactions (transaction_id, book, currency, "
                "created_at_utc, effective_at_utc, idempotency_key, transaction_type, "
                "description, transaction_hash, provisions_for_transaction_id) "
                "VALUES ('x', 'USD_REAL', 'USD', '', '', 'k', 'payment_fee', '', 'h', ?)",
                (sale.transaction_id,),
            )
    for transaction_type in liability.PROVISION_TRANSACTION_TYPES:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ledger_transactions (transaction_id, book, currency, "
                "created_at_utc, effective_at_utc, idempotency_key, transaction_type, "
                "description, transaction_hash) "
                "VALUES ('y', 'USD_REAL', 'USD', '', '', 'k2', ?, '', 'h')",
                (transaction_type,),
            )


def test_editing_a_holds_payment_breaks_the_chain(conn, cell):
    """The link is in the hash preimage, so a hold cannot be quietly re-pointed
    at a different sale (§3.6)."""
    _policy(conn)
    _sale(conn, cell, 500, source="inv-1")
    other = _sale(conn, cell, 700, source="inv-2")
    [first, _second] = liability.holds(conn)
    assert ledger.verify_chain(conn)

    conn.execute(
        "UPDATE ledger_transactions SET provisions_for_transaction_id = ? WHERE transaction_id = ?",
        (other.transaction_id, first.hold_transaction_id),
    )
    assert not ledger.verify_chain(conn)
