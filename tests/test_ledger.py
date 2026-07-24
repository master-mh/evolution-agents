from datetime import datetime, timedelta, timezone

import pytest

from mitosis import ledger, reservations
from mitosis.accounts import cell_cash
from mitosis.models import Book, EntrySpec


def _post(conn, *, idempotency_key="txn:1", amounts=(-100, 100), book=Book.USD_SIM):
    return ledger.post_transaction(
        conn,
        book=book,
        currency="USD",
        transaction_type="test",
        idempotency_key=idempotency_key,
        entries=[
            EntrySpec(account_id="a", amount_minor_units=amounts[0]),
            EntrySpec(account_id="b", amount_minor_units=amounts[1]),
        ],
    )


def test_post_balanced_transaction(conn):
    txn = _post(conn)
    assert txn.book == Book.USD_SIM
    assert sum(e.amount_minor_units for e in txn.entries) == 0
    assert txn.previous_transaction_hash is None
    assert txn.transaction_hash


def test_unbalanced_transaction_rejected(conn):
    with pytest.raises(ledger.UnbalancedTransactionError):
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="test",
            idempotency_key="txn:bad",
            entries=[EntrySpec(account_id="a", amount_minor_units=-100)],
        )


def test_empty_entries_rejected(conn):
    with pytest.raises(ledger.UnbalancedTransactionError):
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="test",
            idempotency_key="txn:empty",
            entries=[],
        )


def test_idempotent_replay_returns_same_transaction(conn):
    first = _post(conn, idempotency_key="txn:dup")
    second = _post(conn, idempotency_key="txn:dup", amounts=(-999, 999))
    assert first.transaction_id == second.transaction_id
    # the replay's differing amounts were never applied
    assert ledger.get_balance(conn, "a", Book.USD_SIM) == -100


def test_naive_datetime_rejected(conn):
    with pytest.raises(ledger.LedgerError):
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="test",
            idempotency_key="txn:naive",
            effective_at_utc=datetime(2026, 1, 1),  # no tzinfo
            entries=[
                EntrySpec(account_id="a", amount_minor_units=-1),
                EntrySpec(account_id="b", amount_minor_units=1),
            ],
        )


def test_balance_is_derived_from_entries(conn):
    _post(conn, idempotency_key="txn:1", amounts=(-100, 100))
    _post(conn, idempotency_key="txn:2", amounts=(-50, 50))
    assert ledger.get_balance(conn, "a", Book.USD_SIM) == -150
    assert ledger.get_balance(conn, "b", Book.USD_SIM) == 150
    assert ledger.get_balance(conn, "nonexistent", Book.USD_SIM) == 0


def test_balance_is_scoped_per_book(conn):
    _post(conn, idempotency_key="txn:sim", amounts=(-100, 100), book=Book.USD_SIM)
    _post(conn, idempotency_key="txn:real", amounts=(-7, 7), book=Book.USD_REAL)
    assert ledger.get_balance(conn, "a", Book.USD_SIM) == -100
    assert ledger.get_balance(conn, "a", Book.USD_REAL) == -7


def test_hash_chain_links_transactions(conn):
    first = _post(conn, idempotency_key="txn:1")
    second = _post(conn, idempotency_key="txn:2")
    assert second.previous_transaction_hash == first.transaction_hash
    assert ledger.verify_chain(conn) is True


def test_hash_chain_detects_tampering(conn):
    _post(conn, idempotency_key="txn:1")
    _post(conn, idempotency_key="txn:2")
    conn.execute(
        "UPDATE ledger_entries SET amount_minor_units = amount_minor_units + 1 "
        "WHERE account_id = 'a'"
    )
    assert ledger.verify_chain(conn) is False


def test_conservation_holds_after_balanced_postings(conn):
    _post(conn, idempotency_key="txn:1", amounts=(-100, 100))
    _post(conn, idempotency_key="txn:2", amounts=(-50, 50))
    assert ledger.verify_conservation(conn, Book.USD_SIM) is True


def test_conservation_detects_direct_db_corruption(conn):
    _post(conn, idempotency_key="txn:1")
    # simulate corruption bypassing the API (post_transaction can't produce this)
    conn.execute("UPDATE ledger_entries SET amount_minor_units = 12345 WHERE account_id = 'a'")
    assert ledger.verify_conservation(conn, Book.USD_SIM) is False


# --- spend_by_book (SPEC.md §10.5 coroner reports) --------------------------


def test_spend_by_book_excludes_internal_reserve_and_release(conn):
    ledger.post_transaction(
        conn, book=Book.USD_SIM, currency="USD", transaction_type="fund",
        idempotency_key="fund", entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-1000, cell_id="cell-1"),
            EntrySpec(account_id=cell_cash("cell-1"), amount_minor_units=1000, cell_id="cell-1"),
        ],
    )
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD", maximum_amount=400,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        idempotency_key="r1",
    )
    reservations.release(conn, r.reservation_id)
    # birth funding, reserve, and release never leave the cell's own accounts
    assert ledger.spend_by_book(conn, "cell-1") == {}


def test_spend_by_book_counts_settled_amount_only(conn):
    ledger.post_transaction(
        conn, book=Book.USD_SIM, currency="USD", transaction_type="fund",
        idempotency_key="fund", entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-1000, cell_id="cell-1"),
            EntrySpec(account_id=cell_cash("cell-1"), amount_minor_units=1000, cell_id="cell-1"),
        ],
    )
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD", maximum_amount=400,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        idempotency_key="r1",
    )
    reservations.settle(conn, r.reservation_id, settled_amount=250, destination_account_id="external_expense")
    reservations.release(conn, r.reservation_id)  # release the remaining 150
    assert ledger.spend_by_book(conn, "cell-1") == {"USD_SIM": 250}


def test_spend_by_book_scoped_to_cell_and_empty_when_untouched(conn):
    assert ledger.spend_by_book(conn, "no-such-cell") == {}
