from datetime import datetime, timedelta, timezone

import pytest

from mitosis import ledger, reservations, sweeper
from mitosis.accounts import cell_cash, cell_committed
from mitosis.models import Book, EntrySpec, ReservationStatus
from mitosis.sweeper import CheckResult, ExternalOutcome

FUTURE = datetime.now(timezone.utc) + timedelta(days=1)
PAST = datetime.now(timezone.utc) - timedelta(seconds=1)


def fund(conn, cell_id="cell-1", amount=1000):
    ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="seed_fund",
        idempotency_key=f"seed:{cell_id}",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
            EntrySpec(account_id=cell_cash(cell_id), amount_minor_units=amount),
        ],
    )


class AlwaysNotHappened:
    def check(self, reservation):
        return CheckResult(ExternalOutcome.NOT_HAPPENED)


class AlwaysHappened:
    def __init__(self, amount, destination="external_expense"):
        self.amount = amount
        self.destination = destination

    def check(self, reservation):
        return CheckResult(
            ExternalOutcome.HAPPENED,
            actual_amount=self.amount,
            destination_account_id=self.destination,
        )


def test_sweep_ignores_unexpired_reservations(conn):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=100, expires_at=FUTURE, idempotency_key="req:1",
    )
    swept = sweeper.sweep(conn)
    assert swept == []
    assert reservations.get_reservation(conn, r.reservation_id).status == ReservationStatus.RESERVED


def test_sweep_releases_expired_reservation_with_no_external_op(conn):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=100, expires_at=PAST, idempotency_key="req:1",
    )
    swept = sweeper.sweep(conn)
    assert len(swept) == 1
    assert swept[0].status == ReservationStatus.RELEASED
    assert ledger.get_balance(conn, cell_cash("cell-1"), Book.USD_SIM) == 1000


def test_sweep_defaults_to_execution_unknown_for_unresolvable_external_op(conn):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=100, expires_at=PAST, idempotency_key="req:1",
        external_operation_id="ext-1",
    )
    swept = sweeper.sweep(conn)
    assert len(swept) == 1
    assert swept[0].status == ReservationStatus.EXECUTION_UNKNOWN
    # funds must NOT be released while unconfirmed (Charter C7)
    assert ledger.get_balance(conn, cell_committed("cell-1"), Book.USD_SIM) == 100


def test_sweep_releases_when_checker_confirms_not_happened(conn):
    fund(conn)
    reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=100, expires_at=PAST, idempotency_key="req:1",
        external_operation_id="ext-1",
    )
    swept = sweeper.sweep(conn, checker=AlwaysNotHappened())
    assert swept[0].status == ReservationStatus.RELEASED


def test_sweep_settles_when_checker_confirms_happened(conn):
    fund(conn)
    reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=100, expires_at=PAST, idempotency_key="req:1",
        external_operation_id="ext-1",
    )
    swept = sweeper.sweep(conn, checker=AlwaysHappened(amount=80))
    assert swept[0].status == ReservationStatus.PARTIALLY_SETTLED
    assert swept[0].settled_amount == 80
    assert ledger.get_balance(conn, "external_expense", Book.USD_SIM) == 80


def test_sweep_leaves_conservation_intact(conn):
    fund(conn, amount=10_000)
    for i in range(5):
        reservations.request(
            conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
            maximum_amount=100, expires_at=PAST, idempotency_key=f"req:{i}",
            external_operation_id=f"ext-{i}" if i % 2 == 0 else None,
        )
    sweeper.sweep(conn)
    assert ledger.verify_conservation(conn, Book.USD_SIM) is True
