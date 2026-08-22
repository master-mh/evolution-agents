"""A dead Cell's estate (Charter C1, C3, C8; SPEC.md §3.6, §10.5; ADR-028).

The spec has no "estate" concept, so what these defend is the intersection of
clauses that do exist: an open reservation is standing authorisation to spend,
which C8 forbids a dead Cell holding; capital left on a dead account is capital
the colony lost; and §3.6 says the remedy is always a new transaction, never an
edited row.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mitosis import gateway, ledger, lifecycle, reservations, sweeper
from mitosis.accounts import cell_cash, cell_committed
from mitosis.models import Book, CellStatus, CellType, EntrySpec, ReservationStatus

#: Far enough out that the sweeper never expires a reservation mid-test.
_LATER = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _make_cell(conn, *, key: str = "a", budget: int = 1_000, book: Book = Book.USD_SIM):
    return lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=budget,
        book=book,
        idempotency_key=key,
    )


def _treasury(conn, book: Book = Book.USD_SIM) -> int:
    return ledger.get_balance(conn, lifecycle.ESTATE_ACCOUNT, book=book)


# --- the capital actually comes back ----------------------------------------


def test_death_returns_residual_capital_to_the_colony(conn):
    """Capital on a dead Cell's account is capital the colony has lost: nothing
    can ever spend it again, and no report counts it as still held.

    Before this, every death stranded its Cell's whole remaining balance —
    the golden run had been quietly losing 3450 USD_SIM per replay since
    version 1.
    """
    cell = _make_cell(conn, budget=1_000)
    before = _treasury(conn)

    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    assert ledger.get_balance(conn, cell_cash(cell.cell_id), book=Book.USD_SIM) == 0
    assert _treasury(conn) == before + 1_000


def test_the_estate_is_a_transfer_so_conservation_holds(conn):
    """Charter C1. The estate moves money, it does not create or destroy it —
    §3.6's "post a new transaction, never edit history" applied to a balance
    that has to end up somewhere.
    """
    cell = _make_cell(conn, budget=1_000)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    assert ledger.verify_conservation(conn, Book.USD_SIM)
    assert ledger.verify_chain(conn)


def test_death_releases_open_reservations(conn):
    """Charter C8: "dead Cells cannot act". An open reservation *is*
    authorisation to spend, whatever the Cell's status column says — so a dead
    Cell holding one is the clearest form of the thing C8 forbids.
    """
    cell = _make_cell(conn, budget=1_000)
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=400,
        idempotency_key="r1",
        expires_at=_LATER,
    )
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), book=Book.USD_SIM) == 400

    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    assert (
        reservations.get_reservation(conn, reservation.reservation_id).status
        is ReservationStatus.RELEASED
    )
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), book=Book.USD_SIM) == 0
    # And the released funds went home with the rest of the estate.
    assert _treasury(conn) == 1_000


def test_the_estate_covers_every_book(conn):
    """Conservation is per book, so reclamation has to be too — a Cell funded
    in RESOURCE and USD_SIM must not have one of them quietly left behind.
    """
    cell = _make_cell(conn, budget=1_000)
    ledger.post_transaction(
        conn,
        book=Book.RESOURCE,
        currency="RESOURCE",
        transaction_type="cell_funding",
        idempotency_key="fund-resource",
        description="resource budget",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-500, cell_id=cell.cell_id),
            EntrySpec(
                account_id=cell_cash(cell.cell_id), amount_minor_units=500, cell_id=cell.cell_id
            ),
        ],
    )

    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    assert ledger.get_balance(conn, cell_cash(cell.cell_id), book=Book.RESOURCE) == 0
    assert _treasury(conn, Book.RESOURCE) == 500
    assert ledger.verify_conservation(conn, Book.RESOURCE)


# --- what the estate must NOT do --------------------------------------------


def test_an_in_flight_external_operation_is_never_released(conn):
    """ADR-022's argument, applied at death. A reservation carrying an
    `external_operation_id` may already have caused a real, billable effect
    outside the colony — it is resolved by finding out what the provider did,
    never by assuming.

    If this fails, death hands the money back and the invoice then arrives
    against a Cell with no committed funds and no way to pay.
    """
    cell = _make_cell(conn, budget=1_000)
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=400,
        idempotency_key="r1",
        expires_at=_LATER,
        external_operation_id="provider-call-1",
    )

    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    assert (
        reservations.get_reservation(conn, reservation.reservation_id).status
        is ReservationStatus.RESERVED
    )
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), book=Book.USD_SIM) == 400
    # The free cash still came home; only the committed part waits.
    assert _treasury(conn) == 600


def test_death_is_never_blocked_by_an_unresolvable_estate(conn):
    """A kill that could be refused would break §9.3 displacement — and worse,
    would hand a Cell a survival strategy: keep one external call in flight and
    never die.

    So an in-flight operation makes the estate *incomplete*, not the death
    impossible.
    """
    cell = _make_cell(conn, budget=1_000)
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=400,
        idempotency_key="r1",
        expires_at=_LATER,
        external_operation_id="provider-call-1",
    )

    dead = lifecycle.kill(conn, cell.cell_id, cause_of_death="displaced")

    assert dead.status is CellStatus.DEAD
    assert lifecycle.outstanding_estates(conn)[0]["cell_id"] == cell.cell_id


def test_a_negative_balance_is_left_alone(conn):
    """ADR-021 lets a cost overrun drive a Cell's cash below zero. "Reclaiming"
    a debt would be inventing money, so the shortfall stays visible on the dead
    Cell's account rather than being absorbed by the treasury.
    """
    cell = _make_cell(conn, budget=100)
    ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="model_call_cost_overrun",
        idempotency_key="overrun:1",
        description="overrun",
        entries=[
            EntrySpec(
                account_id=cell_cash(cell.cell_id), amount_minor_units=-250, cell_id=cell.cell_id
            ),
            EntrySpec(
                account_id="external_expense", amount_minor_units=250, cell_id=cell.cell_id
            ),
        ],
    )
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), book=Book.USD_SIM) == -150
    before = _treasury(conn)

    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    assert ledger.get_balance(conn, cell_cash(cell.cell_id), book=Book.USD_SIM) == -150
    assert _treasury(conn) == before


def test_the_coroner_report_is_unpolluted_by_the_estate(conn):
    """§10.5 wants spend by book *as it stood at death* — a dead Cell must not
    appear to have spent its entire remaining balance in its final moment.

    What actually guarantees this is the **classification**, not the ordering
    inside `_kill_locked`: `cell_estate_reclaim` and `reservation_release` are
    capital movements, so `spend_by_book` ignores them wherever they run. An
    earlier version of this test asserted the ordering instead and passed with
    the estate deliberately moved before the report — it was checking something
    the ordering does not control.
    """
    cell = _make_cell(conn, budget=1_000)
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=400,
        idempotency_key="r1",
        expires_at=_LATER,
    )

    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    report = lifecycle.get_coroner_report(conn, cell.cell_id)
    assert report.spend_by_book.get(Book.USD_SIM.value, 0) == 0
    assert lifecycle.ESTATE_TRANSACTION_TYPE not in str(report.spend_by_book)
    # And the estate did happen — otherwise this passes vacuously.
    assert _treasury(conn) == 1_000


def test_the_estate_is_not_counted_as_spend(conn):
    """`accounts.py` already settled this: returning surplus to the treasury is
    "capital going back, not cost incurred". Counting it as spend would make
    every death look like a final burst of spending in the fitness numbers —
    and §10's fitness reads exactly that figure.
    """
    cell = _make_cell(conn, budget=1_000)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    spend = ledger.spend_by_book(conn, cell.cell_id)
    assert spend.get(Book.USD_SIM.value, 0) == 0


# --- the follow-up pass ------------------------------------------------------


def test_an_estate_is_finished_once_its_external_operation_resolves(conn):
    """The second half of the story. A Cell that died mid-call left committed
    funds behind on purpose; once the sweeper resolves that reservation, the
    residual is free and belongs to the colony.
    """
    cell = _make_cell(conn, budget=1_000)
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=400,
        idempotency_key="r1",
        expires_at=_LATER,
        external_operation_id="provider-call-1",
    )
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")
    assert _treasury(conn) == 600

    # The operation resolves: nothing was spent.
    reservations.release(conn, reservation.reservation_id)
    finished = lifecycle.reclaim_settled_estates(conn)

    assert len(finished) == 1
    assert _treasury(conn) == 1_000
    assert lifecycle.outstanding_estates(conn) == []


def test_the_follow_up_pass_is_idempotent(conn):
    """Run by `mitosis sweep`, which an operator may run on a timer. A second
    pass over an already-emptied account must be a no-op, not a double credit —
    the estate's idempotency key is per cell and book for exactly this.
    """
    cell = _make_cell(conn, budget=1_000)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    assert lifecycle.reclaim_settled_estates(conn) == []
    assert lifecycle.reclaim_settled_estates(conn) == []
    assert _treasury(conn) == 1_000
    assert ledger.verify_conservation(conn, Book.USD_SIM)


def test_a_living_cells_capital_is_never_touched(conn):
    """The obvious way to get this wrong. `reclaim_settled_estates` scans for
    dead Cells; a bug that scanned all Cells would silently confiscate every
    living Cell's balance and read as a conservation-preserving transfer.
    """
    alive = _make_cell(conn, key="alive", budget=1_000)
    doomed = _make_cell(conn, key="doomed", budget=500)
    lifecycle.kill(conn, doomed.cell_id, cause_of_death="test")

    lifecycle.reclaim_settled_estates(conn)

    assert ledger.get_balance(conn, cell_cash(alive.cell_id), book=Book.USD_SIM) == 1_000
    assert _treasury(conn) == 500


def test_displacement_reclaims_the_evicted_cells_capital(conn):
    """§9.3 evicts a Cell to free a population slot. Before this, it freed the
    slot and stranded the capital — precisely when the colony is at capacity
    and least able to afford losing it.
    """
    from mitosis import displacement, population

    doomed = _make_cell(conn, key="doomed", budget=800)
    before = _treasury(conn)

    conn.execute("BEGIN IMMEDIATE")
    try:
        cell = lifecycle.get_cell(conn, doomed.cell_id)
        lifecycle._kill_locked(conn, cell, cause_of_death="displaced by a superior candidate")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    assert _treasury(conn) == before + 800
    assert ledger.verify_conservation(conn, Book.USD_SIM)
