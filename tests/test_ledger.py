from datetime import datetime, timedelta, timezone

import pytest

from mitosis import accounts, ledger, lifecycle, reservations
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType, EntrySpec


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


def _fund_cell(conn, cell_id="cell-1", amount=1000, book=Book.USD_SIM):
    ledger.post_transaction(
        conn, book=book, currency="USD", transaction_type="fund",
        idempotency_key=f"fund:{cell_id}:{book.value}", entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-amount, cell_id=cell_id),
            EntrySpec(account_id=cell_cash(cell_id), amount_minor_units=amount, cell_id=cell_id),
        ],
    )


def test_spend_by_book_is_reduced_by_a_reconciliation_credit(conn):
    """The bug this fix exists for. An invoice below what the ledger recorded
    posts a negative adjustment debiting external_expense; the old sign filter
    dropped it, so a refunded Cell kept its full recorded spend forever."""
    _fund_cell(conn)
    r = reservations.request(
        conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD", maximum_amount=400,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), idempotency_key="r1",
    )
    reservations.settle(
        conn, r.reservation_id, settled_amount=300, destination_account_id="external_expense"
    )
    assert ledger.spend_by_book(conn, "cell-1") == {"USD_SIM": 300}

    # The provider invoiced 100 less than estimated: cash back to the Cell,
    # external_expense debited. Same shape reconciliation._post_adjustment posts.
    ledger.post_transaction(
        conn, book=Book.USD_SIM, currency="USD",
        transaction_type="model_call_reconciliation_adjustment",
        idempotency_key="credit-1", entries=[
            EntrySpec(account_id=cell_cash("cell-1"), amount_minor_units=100, cell_id="cell-1"),
            EntrySpec(account_id="external_expense", amount_minor_units=-100, cell_id="cell-1"),
        ],
    )
    assert ledger.spend_by_book(conn, "cell-1") == {"USD_SIM": 200}


def test_spend_by_book_never_reads_negative_from_inbound_funding(conn):
    """The other half, and why the sign filter could not simply be removed:
    birth funding's negative leg carries the same cell_id, so an unscoped signed
    sum would make a freshly-funded Cell read as having spent a negative
    amount."""
    _fund_cell(conn, amount=5_000)
    assert ledger.spend_by_book(conn, "cell-1") == {}


def test_spend_by_book_counts_consumption_not_capital_movement(conn):
    """`infrastructure_reserve` never leaves the colony but is unambiguously
    cost to the Cell — metered compute it consumed. `colony_treasury` is the
    opposite: capital going back."""
    _fund_cell(conn, amount=5_000)
    for key, destination, amount in (
        ("infra", "infrastructure_reserve", 700),
        ("treasury", "colony_treasury", 900),
    ):
        r = reservations.request(
            conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD", maximum_amount=amount,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1), idempotency_key=key,
        )
        reservations.settle(
            conn, r.reservation_id, settled_amount=amount, destination_account_id=destination
        )
    assert ledger.spend_by_book(conn, "cell-1") == {"USD_SIM": 700}


def test_spend_by_book_ignores_revenue(conn):
    """Revenue raises a Cell's cash; it must not register as negative spend."""
    from mitosis import revenue

    _fund_cell(conn, amount=1_000)
    lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=10,
        book=Book.USD_SIM, idempotency_key="rev-cell",
    )
    cell_id = conn.execute(
        "SELECT cell_id FROM cells WHERE idempotency_key = 'rev-cell'"
    ).fetchone()["cell_id"]
    revenue.record_revenue(
        conn, cell_id=cell_id, amount_minor_units=800, source="inv-1", book=Book.USD_SIM
    )
    assert ledger.spend_by_book(conn, cell_id) == {}


def test_every_fixed_account_is_classified_as_spend_or_capital():
    """Adding an account to §31's list must force a decision. Defaulting to
    "not spend" is how a fitness signal goes quietly wrong — and unlike a
    crash, nothing would ever report it."""
    assert accounts.unclassified_accounts() == frozenset(), (
        f"unclassified fixed account(s): {sorted(accounts.unclassified_accounts())}. "
        "Decide whether a Cell's value arriving there is consumption (add to "
        "SPEND_DESTINATIONS) or capital movement (add to CAPITAL_ACCOUNTS)."
    )
    overlap = set(accounts.SPEND_DESTINATIONS) & set(accounts.CAPITAL_ACCOUNTS)
    assert not overlap, f"account(s) classified as both: {sorted(overlap)}"
    assert all(accounts.SPEND_DESTINATIONS.values()), "every spend destination states its reason"
    assert all(accounts.CAPITAL_ACCOUNTS.values()), "every capital account states its reason"
    # Both sets name only real accounts — a typo would silently never match.
    assert set(accounts.SPEND_DESTINATIONS) <= accounts.FIXED_ACCOUNTS
    assert set(accounts.CAPITAL_ACCOUNTS) <= accounts.FIXED_ACCOUNTS
