"""Payment fees (SPEC.md §1.1, §2.2, §3.6, §5.1, §16.3; ADR-098).

§1.1 subtracts payment fees from real settled net profit and nothing could
record one, so every live sale would have overstated profit by its fee. These
tests defend what a fee is: a real charge nobody chose — recorded past a cap and
counted by it afterwards — that lands on the Cell whose charge incurred it and is
read by every reader of spend with none of them changed.
"""

from __future__ import annotations

import hashlib
import inspect
import pathlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    death,
    experiments,
    ledger,
    lifecycle,
    payment_fees,
    real_spend_breaker,
    reservations,
    revenue,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType, EntrySpec, RealSpendLimits

SRC = pathlib.Path(payment_fees.__file__).parent
MIGRATION = SRC / "migrations" / "0038_payment_fee.sql"


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
        idempotency_key=f"fee-cell:{key}",
    )


def _sale(conn, cell, amount=500, *, source="inv-1", **kwargs):
    return revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=amount, source=source, book=cell.book,
        **kwargs,
    )


def _fee(conn, charge, amount, *, source="fee-1", **kwargs):
    return payment_fees.record_payment_fee(
        conn,
        charged_on_transaction_id=charge.transaction_id,
        amount_minor_units=amount,
        source=source,
        **kwargs,
    )


def _cash(conn, cell):
    return ledger.get_balance(conn, cell_cash(cell.cell_id), cell.book)


# --- the posting -------------------------------------------------------------


def test_a_fee_moves_the_cells_cash_to_external_expense(conn, cell):
    sale = _sale(conn, cell, 500)
    cash = _cash(conn, cell)

    fee = _fee(conn, sale, 45)

    assert fee.transaction_type == payment_fees.PAYMENT_FEE_TRANSACTION_TYPE
    assert fee.charged_on_transaction_id == sale.transaction_id
    assert _cash(conn, cell) == cash - 45
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 45
    assert revenue.net_revenue(conn, cell.cell_id) == 500, "a fee is a cost, not a reversal"
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_chain(conn)


def test_a_fee_is_audited_with_the_charge_it_was_taken_on(conn, cell):
    sale = _sale(conn, cell, 500)
    _fee(conn, sale, 45, note="2.9% + 30")

    row = conn.execute(
        "SELECT cell_id, metadata_json FROM audit_events WHERE event_type = 'payment_fee_recorded'"
    ).fetchone()
    assert row["cell_id"] == cell.cell_id
    assert sale.transaction_id in row["metadata_json"]
    assert '"charged_on_type":"cell_revenue"' in row["metadata_json"]


# --- attribution comes from the charge (§16.3) --------------------------------


def test_record_payment_fee_offers_no_way_to_name_a_cell():
    """For `record_reversal`'s reason: a fee that could name its Cell could land a
    sale's cost on a sibling that never made the sale."""
    parameters = set(inspect.signature(payment_fees.record_payment_fee).parameters)
    forbidden = {"cell_id", "book", "experiment_id", "artifact_id", "account_id", "provider"}
    assert not parameters & forbidden, f"record_payment_fee can be pointed at {parameters & forbidden}"


def test_a_fee_inherits_its_cell_and_experiment_but_not_the_buyer(conn, cell):
    """The processor, not the buyer, is who a fee is paid to — copying the buyer's
    §16.3 digest onto it would make the processor look like a repeat customer."""
    experiment = experiments.start(conn, cell_id=cell.cell_id, hypothesis="fees are costs")
    sale = _sale(
        conn, cell, 500, experiment_id=experiment.experiment_id, counterparty="buyer@example.test"
    )

    fee = _fee(conn, sale, 45)

    assert fee.book is Book.USD_REAL
    assert fee.counterparty_hash is None and sale.counterparty_hash is not None
    by_account = {e.account_id: e for e in fee.entries}
    for leg in (by_account[cell_cash(cell.cell_id)], by_account["external_expense"]):
        assert leg.cell_id == cell.cell_id
        assert leg.experiment_id == experiment.experiment_id


def test_a_fee_may_be_taken_on_a_chargeback_but_not_on_a_refund(conn, cell):
    """A chargeback fee arrives with the chargeback. A refund carries no fee of its
    own: the fee on the sale was charged on the sale, and a fee on the refund would
    count it twice."""
    sale = _sale(conn, cell, 500)
    chargeback = revenue.record_reversal(
        conn, revenue_transaction_id=sale.transaction_id, amount_minor_units=200,
        source="dispute-1", kind=revenue.ReversalKind.CHARGEBACK,
    )
    refund = revenue.record_reversal(
        conn, revenue_transaction_id=sale.transaction_id, amount_minor_units=100, source="re-1",
    )

    assert _fee(conn, chargeback, 1_500, source="dispute-fee").charged_on_transaction_id == (
        chargeback.transaction_id
    )
    with pytest.raises(payment_fees.PaymentFeeError, match="revenue payment or a chargeback"):
        _fee(conn, refund, 10, source="refund-fee")


def test_only_a_charge_can_carry_a_fee(conn, cell):
    funding = conn.execute(
        "SELECT transaction_id FROM ledger_transactions WHERE transaction_type != 'cell_revenue' "
        "LIMIT 1"
    ).fetchone()["transaction_id"]
    with pytest.raises(payment_fees.PaymentFeeError, match="no such transaction"):
        payment_fees.record_payment_fee(
            conn, charged_on_transaction_id="nope", amount_minor_units=1, source="x"
        )
    with pytest.raises(payment_fees.PaymentFeeError, match="revenue payment or a chargeback"):
        payment_fees.record_payment_fee(
            conn, charged_on_transaction_id=funding, amount_minor_units=1, source="x"
        )


def test_a_fee_is_not_bounded_by_the_charge(conn, cell):
    """A fixed per-charge fee on a small sale can exceed it. A bound here would
    refuse a charge the processor has already taken."""
    sale = _sale(conn, cell, 20)
    _fee(conn, sale, 30)
    assert _cash(conn, cell) == 1_000 + 20 - 30


@pytest.mark.parametrize("amount", [0, -5])
def test_a_fee_must_be_positive(conn, cell, amount):
    sale = _sale(conn, cell)
    with pytest.raises(payment_fees.PaymentFeeError, match="must be positive"):
        _fee(conn, sale, amount)


def test_a_fee_requires_a_reference(conn, cell):
    sale = _sale(conn, cell)
    with pytest.raises(payment_fees.PaymentFeeError, match="source is required"):
        _fee(conn, sale, 10, source="  ")


def test_the_same_fee_recorded_twice_posts_once(conn, cell):
    sale = _sale(conn, cell)
    assert _fee(conn, sale, 45).transaction_id == _fee(conn, sale, 45).transaction_id
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 45


def test_a_key_already_used_for_another_fee_is_refused(conn, cell):
    first = _sale(conn, cell, source="inv-1")
    other = _sale(conn, cell, source="inv-2")
    _fee(conn, first, 45, idempotency_key="shared")
    with pytest.raises(payment_fees.PaymentFeeError, match="already belongs"):
        _fee(conn, other, 45, idempotency_key="shared")


def test_a_dead_cell_pays_its_fees_and_the_debt_stays_visible(conn, cell):
    sale = _sale(conn, cell, 500)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")
    treasury = ledger.get_balance(conn, "colony_treasury", Book.USD_REAL)

    _fee(conn, sale, 30)

    assert _cash(conn, cell) == -30
    assert ledger.get_balance(conn, "colony_treasury", Book.USD_REAL) == treasury


# --- imposed, and counted (§5) ------------------------------------------------


def test_a_fee_is_recorded_past_a_reached_cap_and_the_cap_then_refuses_chosen_spend(conn):
    """Refusing to record money a processor has already taken would misstate the
    books without un-taking it. Counting it is what makes the fee matter: the next
    reservation — spend the colony chooses — meets a window the fee filled."""
    real_spend_breaker.configure_if_absent(conn)
    real_spend_breaker.set_limits(
        conn,
        RealSpendLimits(
            per_request_minor_units=5_000,
            per_hour_minor_units=1_000,
            per_day_minor_units=100_000,
            per_month_minor_units=100_000,
            max_concurrent_reserved_minor_units=5_000,
            provider_limits={},
        ),
    )
    seller = _cell(conn, "capped", budget=5_000)
    sale = _sale(conn, seller, 500)

    _fee(conn, sale, 1_200)

    now = datetime.now(timezone.utc)
    assert real_spend_breaker.snapshot(conn, now=now).spend_last_hour_minor_units == 1_200
    with pytest.raises(real_spend_breaker.RealSpendCapExceededError, match="hour cap"):
        reservations.request(
            conn, cell_id=seller.cell_id, book=Book.USD_REAL, currency="USD", maximum_amount=1,
            expires_at=now + timedelta(hours=1), idempotency_key="after-the-fee",
        )


def test_a_usd_sim_fee_never_reaches_the_breaker(conn):
    seller = _cell(conn, "sim", book=Book.USD_SIM)
    _fee(conn, _sale(conn, seller, 500), 45)
    assert real_spend_breaker.snapshot(conn).spend_last_month_minor_units == 0


# --- every reader of spend sees it, and none was changed ----------------------


def test_a_fee_is_consumption_to_domination_and_to_spend_by_book(conn, cell):
    sale = _sale(conn, cell, 500)
    _fee(conn, sale, 45)

    assert ledger.spend_by_book(conn, cell.cell_id)[Book.USD_REAL.value] == 45
    record = death.contribution(conn, cell)
    assert record.spend_minor_units == 45
    assert record.net_contribution == 455


def test_an_experiment_report_counts_a_fee_as_real_spend(conn, cell):
    experiment = experiments.start(conn, cell_id=cell.cell_id, hypothesis="fees are costs")
    sale = _sale(conn, cell, 500, experiment_id=experiment.experiment_id)
    _fee(conn, sale, 45)

    assert experiments.report(conn, experiment.experiment_id).real_spend_minor_units == 45


# --- the schema (migration 0038) ----------------------------------------------


def _post(conn, cell, *, transaction_type, key, charged_on=None):
    return ledger.post_transaction(
        conn,
        book=Book.USD_REAL,
        currency="USD",
        transaction_type=transaction_type,
        idempotency_key=key,
        charged_on_transaction_id=charged_on,
        entries=[
            EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=-1, cell_id=cell.cell_id),
            EntrySpec(account_id="external_expense", amount_minor_units=1, cell_id=cell.cell_id),
        ],
    )


def test_the_schema_refuses_a_fee_that_names_no_charge(conn, cell):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _post(conn, cell, transaction_type=payment_fees.PAYMENT_FEE_TRANSACTION_TYPE, key="bare")


def test_the_schema_refuses_a_charge_link_on_any_other_type(conn, cell):
    sale = _sale(conn, cell)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _post(conn, cell, transaction_type="test_adjustment", key="linked", charged_on=sale.transaction_id)


def test_the_schema_refuses_a_fee_on_a_transaction_that_does_not_exist(conn, cell):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        _post(
            conn, cell, transaction_type=payment_fees.PAYMENT_FEE_TRANSACTION_TYPE, key="dangling",
            charged_on="no-such-transaction",
        )


def test_the_fee_type_is_the_one_the_schema_names():
    named = re.search(r"transaction_type = '([^']+)'", MIGRATION.read_text()).group(1)
    assert named == payment_fees.PAYMENT_FEE_TRANSACTION_TYPE


def test_the_charge_a_fee_names_is_covered_by_the_hash_chain(conn, cell):
    first = _sale(conn, cell, source="inv-1")
    other = _sale(conn, cell, source="inv-2")
    fee = _fee(conn, first, 45)
    assert ledger.verify_chain(conn)

    conn.execute(
        "UPDATE ledger_transactions SET charged_on_transaction_id = ? WHERE transaction_id = ?",
        (other.transaction_id, fee.transaction_id),
    )
    assert not ledger.verify_chain(conn)


def test_a_transaction_without_a_charge_link_hashes_as_it_always_did(conn, cell):
    """The pre-0038 formula, recomputed by hand (§3.4), on a transaction that
    carries neither link nor counterparty."""
    sale = _sale(conn, cell)
    row = conn.execute(
        "SELECT * FROM ledger_transactions WHERE transaction_id = ?", (sale.transaction_id,)
    ).fetchone()
    entries = conn.execute(
        "SELECT * FROM ledger_entries WHERE transaction_id = ? ORDER BY rowid", (sale.transaction_id,)
    ).fetchall()
    canonical = {
        key: row[key]
        for key in (
            "transaction_id", "book", "currency", "created_at_utc", "effective_at_utc",
            "idempotency_key", "event_id", "transaction_type", "description",
            "previous_transaction_hash",
        )
    }
    canonical["entries"] = [
        {
            key: e[key]
            for key in (
                "entry_id", "account_id", "amount_minor_units", "cell_id", "team_id",
                "experiment_id", "artifact_id",
            )
        }
        for e in entries
    ]
    assert row["charged_on_transaction_id"] is None
    assert hashlib.sha256(ledger._canonical_json(canonical).encode()).hexdigest() == row["transaction_hash"]
