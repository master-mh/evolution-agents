from datetime import datetime, timedelta, timezone

import pytest

from mitosis import ledger, reservations
from mitosis.accounts import cell_cash, cell_committed
from mitosis.models import Book, EntrySpec, ReservationStatus

FUTURE = datetime.now(timezone.utc) + timedelta(days=1)
PAST = datetime.now(timezone.utc) - timedelta(days=1)


def fund(conn, cell_id="cell-1", amount=1000, book=Book.USD_SIM, key=None):
    ledger.post_transaction(
        conn,
        book=book,
        currency="USD",
        transaction_type="seed_fund",
        idempotency_key=key or f"seed:{cell_id}",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
            EntrySpec(account_id=cell_cash(cell_id), amount_minor_units=amount),
        ],
    )


def test_request_moves_funds_to_committed(conn):
    fund(conn)
    r = reservations.request(
        conn,
        cell_id="cell-1",
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=300,
        expires_at=FUTURE,
        idempotency_key="req:1",
    )
    assert r.status == ReservationStatus.RESERVED
    assert ledger.get_balance(conn, cell_cash("cell-1"), Book.USD_SIM) == 700
    assert ledger.get_balance(conn, cell_committed("cell-1"), Book.USD_SIM) == 300


def test_request_is_idempotent(conn):
    fund(conn)
    first = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=300, expires_at=FUTURE, idempotency_key="req:1",
    )
    second = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=999, expires_at=FUTURE, idempotency_key="req:1",
    )
    assert first.reservation_id == second.reservation_id
    assert ledger.get_balance(conn, cell_committed("cell-1"), Book.USD_SIM) == 300


def test_request_rejects_non_positive_amount(conn):
    fund(conn)
    with pytest.raises(reservations.ReservationError):
        reservations.request(
            conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
            maximum_amount=0, expires_at=FUTURE, idempotency_key="req:zero",
        )


def test_full_settle_is_terminal(conn):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=300, expires_at=FUTURE, idempotency_key="req:1",
    )
    settled = reservations.settle(
        conn, r.reservation_id, settled_amount=300, destination_account_id="external_expense"
    )
    assert settled.status == ReservationStatus.SETTLED
    assert ledger.get_balance(conn, cell_committed("cell-1"), Book.USD_SIM) == 0
    assert ledger.get_balance(conn, "external_expense", Book.USD_SIM) == 300

    with pytest.raises(reservations.InvalidTransitionError):
        reservations.release(conn, r.reservation_id)


def test_partial_settle_then_release_remainder(conn):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=300, expires_at=FUTURE, idempotency_key="req:1",
    )
    partial = reservations.settle(
        conn, r.reservation_id, settled_amount=200, destination_account_id="external_expense"
    )
    assert partial.status == ReservationStatus.PARTIALLY_SETTLED
    assert ledger.get_balance(conn, cell_committed("cell-1"), Book.USD_SIM) == 100

    released = reservations.release(conn, r.reservation_id)
    assert released.status == ReservationStatus.RELEASED
    assert ledger.get_balance(conn, cell_committed("cell-1"), Book.USD_SIM) == 0
    assert ledger.get_balance(conn, cell_cash("cell-1"), Book.USD_SIM) == 800  # 1000-300+100


def test_release_directly_from_reserved(conn):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=300, expires_at=FUTURE, idempotency_key="req:1",
    )
    released = reservations.release(conn, r.reservation_id)
    assert released.status == ReservationStatus.RELEASED
    assert ledger.get_balance(conn, cell_cash("cell-1"), Book.USD_SIM) == 1000
    assert ledger.get_balance(conn, cell_committed("cell-1"), Book.USD_SIM) == 0


def test_execution_unknown_never_auto_releases_and_can_resolve_either_way(conn):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=300, expires_at=FUTURE, idempotency_key="req:1",
        external_operation_type="model_call", external_operation_id="ext-1",
    )
    unknown = reservations.mark_execution_unknown(conn, r.reservation_id)
    assert unknown.status == ReservationStatus.EXECUTION_UNKNOWN
    # funds remain committed while unresolved
    assert ledger.get_balance(conn, cell_committed("cell-1"), Book.USD_SIM) == 300

    resolved = reservations.settle(
        conn, r.reservation_id, settled_amount=300, destination_account_id="external_expense"
    )
    assert resolved.status == ReservationStatus.SETTLED


def test_execution_unknown_can_go_to_disputed_then_resolve(conn):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=300, expires_at=FUTURE, idempotency_key="req:1",
        external_operation_id="ext-1",
    )
    reservations.mark_execution_unknown(conn, r.reservation_id)
    disputed = reservations.mark_disputed(conn, r.reservation_id)
    assert disputed.status == ReservationStatus.DISPUTED

    resolved = reservations.release(conn, r.reservation_id)
    assert resolved.status == ReservationStatus.RELEASED
    assert ledger.get_balance(conn, cell_cash("cell-1"), Book.USD_SIM) == 1000


@pytest.mark.parametrize(
    "setup_terminal_status",
    [ReservationStatus.SETTLED, ReservationStatus.RELEASED],
)
def test_terminal_states_reject_further_transitions(conn, setup_terminal_status):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=300, expires_at=FUTURE, idempotency_key="req:1",
    )
    if setup_terminal_status == ReservationStatus.SETTLED:
        reservations.settle(
            conn, r.reservation_id, settled_amount=300, destination_account_id="external_expense"
        )
    else:
        reservations.release(conn, r.reservation_id)

    with pytest.raises(reservations.InvalidTransitionError):
        reservations.mark_execution_unknown(conn, r.reservation_id)


def test_settle_amount_cannot_exceed_maximum(conn):
    fund(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=300, expires_at=FUTURE, idempotency_key="req:1",
    )
    with pytest.raises(reservations.ReservationError):
        reservations.settle(
            conn, r.reservation_id, settled_amount=301, destination_account_id="external_expense"
        )


def test_conservation_holds_across_full_reservation_lifecycle(conn):
    fund(conn, amount=10_000)
    r1 = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=300, expires_at=FUTURE, idempotency_key="req:1",
    )
    reservations.settle(
        conn, r1.reservation_id, settled_amount=250, destination_account_id="external_expense"
    )
    reservations.release(conn, r1.reservation_id)

    r2 = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
        maximum_amount=500, expires_at=FUTURE, idempotency_key="req:2",
    )
    reservations.release(conn, r2.reservation_id)

    assert ledger.verify_conservation(conn, Book.USD_SIM) is True
    assert ledger.verify_chain(conn) is True
