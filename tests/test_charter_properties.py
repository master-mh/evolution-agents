"""Charter property tests (docs/DECISIONS.md ADR-013; SPEC.md §0.1).

Maps to named Charter test IDs:
  charter_ledger_balanced            -> C1
  charter_conservation_per_book      -> C2
  charter_balance_matches_ledger     -> C3
  charter_crash_recovery             -> C7 (reservation FSM stateful machine)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, precondition, rule

from mitosis import db, ledger, reservations
from mitosis.accounts import cell_cash, cell_committed
from mitosis.models import Book, EntrySpec, ReservationStatus

FUTURE = datetime.now(timezone.utc) + timedelta(days=365)


# --- charter_ledger_balanced (C1) -------------------------------------------


@given(a=st.integers(min_value=-10_000, max_value=10_000).filter(lambda x: x != 0))
def test_charter_ledger_balanced(a):
    conn = db.connect_and_migrate()
    txn = ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="t",
        idempotency_key=f"k:{a}",
        entries=[
            EntrySpec(account_id="x", amount_minor_units=-a),
            EntrySpec(account_id="y", amount_minor_units=a),
        ],
    )
    assert sum(e.amount_minor_units for e in txn.entries) == 0


@given(
    a=st.integers(min_value=1, max_value=10_000),
    b=st.integers(min_value=1, max_value=10_000),
)
def test_charter_ledger_rejects_unbalanced(a, b):
    if a == b:
        return
    conn = db.connect_and_migrate()
    try:
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="t",
            idempotency_key=f"k:{a}:{b}",
            entries=[
                EntrySpec(account_id="x", amount_minor_units=-a),
                EntrySpec(account_id="y", amount_minor_units=b),
            ],
        )
        raise AssertionError("unbalanced transaction should have been rejected")
    except ledger.UnbalancedTransactionError:
        pass


# --- charter_conservation_per_book (C2) & charter_balance_matches_ledger (C3) --


@given(amounts=st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=20))
@settings(max_examples=50)
def test_charter_conservation_and_balance_match(amounts):
    conn = db.connect_and_migrate()
    for i, amount in enumerate(amounts):
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="t",
            idempotency_key=f"k:{i}",
            entries=[
                EntrySpec(account_id="source", amount_minor_units=-amount),
                EntrySpec(account_id="dest", amount_minor_units=amount),
            ],
        )
    assert ledger.verify_conservation(conn, Book.USD_SIM) is True
    assert ledger.get_balance(conn, "source", Book.USD_SIM) == -sum(amounts)
    assert ledger.get_balance(conn, "dest", Book.USD_SIM) == sum(amounts)


# --- charter_crash_recovery (C7) --------------------------------------------
# A reservation stuck in execution_unknown after a simulated crash must never
# be silently released, and conservation must hold under any interleaving of
# request / settle / release / crash / reconcile.


@settings(max_examples=30, stateful_step_count=25)
class ReservationKernelMachine(RuleBasedStateMachine):
    reservation_ids = Bundle("reservation_ids")

    def __init__(self):
        super().__init__()
        self.conn = db.connect_and_migrate()
        self.status: dict[str, ReservationStatus] = {}
        self._next_id = 0
        ledger.post_transaction(
            self.conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="seed",
            idempotency_key="seed",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-1_000_000),
                EntrySpec(account_id=cell_cash("cell-1"), amount_minor_units=1_000_000),
            ],
        )

    def _fresh_key(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}:{self._next_id}"

    @rule(target=reservation_ids, amount=st.integers(min_value=1, max_value=1000))
    def request(self, amount):
        r = reservations.request(
            self.conn,
            cell_id="cell-1",
            book=Book.USD_SIM,
            currency="USD",
            maximum_amount=amount,
            expires_at=FUTURE,
            idempotency_key=self._fresh_key("req"),
        )
        self.status[r.reservation_id] = r.status
        return r.reservation_id

    @precondition(lambda self: ReservationStatus.RESERVED in self.status.values())
    @rule(reservation_id=reservation_ids, fraction=st.integers(min_value=0, max_value=100))
    def settle_or_release(self, reservation_id, fraction):
        if self.status.get(reservation_id) != ReservationStatus.RESERVED:
            return
        r = reservations.get_reservation(self.conn, reservation_id)
        settle_amount = (r.maximum_amount * fraction) // 100
        if settle_amount == 0:
            result = reservations.release(self.conn, reservation_id)
        else:
            result = reservations.settle(
                self.conn,
                reservation_id,
                settled_amount=settle_amount,
                destination_account_id="external_expense",
            )
            if result.status == ReservationStatus.PARTIALLY_SETTLED:
                result = reservations.release(self.conn, reservation_id)
        self.status[reservation_id] = result.status

    @precondition(lambda self: ReservationStatus.RESERVED in self.status.values())
    @rule(reservation_id=reservation_ids)
    def crash_before_resolution(self, reservation_id):
        """Simulates a crash/timeout: the reservation can neither be
        confirmed executed nor confirmed unexecuted at this point."""
        if self.status.get(reservation_id) != ReservationStatus.RESERVED:
            return
        result = reservations.mark_execution_unknown(self.conn, reservation_id)
        self.status[reservation_id] = result.status

    @precondition(lambda self: ReservationStatus.EXECUTION_UNKNOWN in self.status.values())
    @rule(reservation_id=reservation_ids)
    def reconcile_unknown(self, reservation_id):
        if self.status.get(reservation_id) != ReservationStatus.EXECUTION_UNKNOWN:
            return
        result = reservations.release(self.conn, reservation_id)
        self.status[reservation_id] = result.status

    @invariant()
    def conservation_and_chain_hold(self):
        assert ledger.verify_conservation(self.conn, Book.USD_SIM) is True
        assert ledger.verify_chain(self.conn) is True

    @invariant()
    def committed_balance_matches_open_reservations(self):
        open_committed = 0
        for reservation_id, status in self.status.items():
            if status in (ReservationStatus.RELEASED, ReservationStatus.SETTLED):
                continue
            r = reservations.get_reservation(self.conn, reservation_id)
            open_committed += r.maximum_amount - r.settled_amount
        actual = ledger.get_balance(self.conn, cell_committed("cell-1"), Book.USD_SIM)
        assert actual == open_committed

    def teardown(self):
        self.conn.close()


TestReservationKernelMachine = ReservationKernelMachine.TestCase
