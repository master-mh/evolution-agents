"""Provider-invoice reconciliation (SPEC.md §24.1, §3.6, §4.4; Charter C7).

The money-correctness edges here are about *direction*: an invoice can be
above or below what the ledger recorded, and a credit that gets counted as
spend is worse than no reconciliation at all — it would push a Cell toward
the circuit breaker for being refunded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    db,
    gateway,
    ledger,
    lifecycle,
    pricing,
    providers,
    real_spend_breaker,
    reconciliation,
    reservations,
)
from mitosis.accounts import cell_cash, cell_committed
from mitosis.models import (
    Book,
    CellType,
    EntrySpec,
    ModelCallStatus,
    RealSpendLimits,
    ReservationStatus,
)

PRICED_MODEL = "claude-opus-5"
# StubProvider reports 2000 in / 1000 out; opus is $5/$25 per MTok, so
# 2000*5 + 1000*25 = 35_000 micro-USD = 3.5 cents, recorded as 4 (ADR-020).
TRUE_COST_MICRO = 35_000
RECORDED_MINOR = 4


class StubProvider:
    name = "anthropic"

    def __init__(self, *, fail=None, unknown=False):
        self.fail = fail
        self.unknown = unknown

    def complete(self, request):
        if self.fail is not None:
            raise providers.ProviderCallError(self.fail, execution_unknown=self.unknown)
        return providers.ModelResponse(
            text="stub reply",
            resolved_model=request.model,
            api_version="2023-06-01",
            input_tokens=2000,
            output_tokens=1000,
            stop_reason="end_turn",
            latency_ms=7,
        )


def _fund(conn, cell_id, book, amount):
    ledger.post_transaction(
        conn,
        book=book,
        currency=book.value,
        transaction_type="test_funding",
        idempotency_key=f"fund:{cell_id}:{book.value}",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
            EntrySpec(account_id=cell_cash(cell_id), amount_minor_units=amount),
        ],
    )


@pytest.fixture()
def cell(conn):
    real_spend_breaker.configure_if_absent(conn)
    real_spend_breaker.set_limits(
        conn,
        RealSpendLimits(
            per_request_minor_units=500,
            per_hour_minor_units=5_000,
            per_day_minor_units=50_000,
            per_month_minor_units=500_000,
            max_concurrent_reserved_minor_units=5_000,
            provider_limits={},
        ),
    )
    created = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=1_000,
        book=Book.USD_REAL,
        idempotency_key="recon-cell",
    )
    _fund(conn, created.cell_id, Book.RESOURCE, 10_000_000)
    _fund(conn, created.cell_id, Book.USD_SIM, 1_000)
    return created


class _ZeroPricedProvider(StubProvider):
    """A successful call that costs nothing, which is what a zero-priced entry in
    the pricing table produces — the mock provider is the live example."""

    name = "mock"
    model = "mock-1"


def _call(conn, cell, *, key="k", fail=None, unknown=False, provider=None):
    provider = provider or StubProvider(fail=fail, unknown=unknown)
    return gateway.call_model(
        conn,
        cell_id=cell.cell_id,
        provider=provider,
        request=providers.ModelRequest(
            model=getattr(provider, "model", PRICED_MODEL),
            messages=({"role": "user", "content": "hello there"},),
            max_tokens=1000,
        ),
        idempotency_key=key,
    )


def _unknown_call(conn, cell, *, key="k"):
    """A call whose provider timed out: `execution_unknown`, funds committed."""
    return _call(conn, cell, key=key, fail="TimeoutError: gone", unknown=True)


def _invariants_hold(conn):
    return all(ledger.verify_conservation(conn, b) for b in Book) and ledger.verify_chain(conn)


# --------------------------------------------------------------------------
# Already-settled calls: §3.6 adjustments, never an edit
# --------------------------------------------------------------------------


def test_invoice_above_the_ledger_posts_a_further_charge(conn, cell):
    call = _call(conn, cell)
    assert call.settled_minor_units == RECORDED_MINOR
    cash_before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)

    reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=120_000, source="inv-B"
    )

    assert reconciliation.net_adjustment_minor_units(conn) == 12 - RECORDED_MINOR
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) == cash_before - 8
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 12
    assert _invariants_hold(conn)


def test_invoice_below_the_ledger_credits_the_cell_back(conn, cell):
    call = _call(conn, cell)
    cash_before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)

    reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=20_000, source="inv-F"
    )

    assert reconciliation.net_adjustment_minor_units(conn) == 2 - RECORDED_MINOR
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) == cash_before + 2
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 2
    assert _invariants_hold(conn)


def test_a_credit_reduces_measured_spend_rather_than_inflating_it(conn, cell):
    """The one that would be silently, expensively wrong.

    Both breaker queries used to select the spend leg with
    `e.amount_minor_units > 0`. A credit's positive leg is the refund landing
    in the Cell's *cash*, so on that filter a refund read as fresh spend and
    paying a Cell back pushed it toward the circuit breaker. They now sum the
    signed `external_expense` leg instead.
    """
    call = _call(conn, cell)
    before_global = real_spend_breaker.snapshot(conn).spend_last_day_minor_units
    before_provider = real_spend_breaker.provider_exposure(conn, "anthropic")
    assert before_global == RECORDED_MINOR

    reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=20_000, source="inv-F"
    )

    after_global = real_spend_breaker.snapshot(conn).spend_last_day_minor_units
    after_provider = real_spend_breaker.provider_exposure(conn, "anthropic")
    assert after_global == 2 < before_global
    assert after_provider == 2 < before_provider

    # The pre-fix filter, spelled out so the regression is unmistakable: it
    # would report 6 (4 settled + the 2-cent refund leg counted as spend).
    old_filter = conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.book = 'USD_REAL'
          AND t.transaction_type IN
              ('reservation_settle', 'model_call_cost_overrun',
               'model_call_reconciliation_adjustment')
          AND e.amount_minor_units > 0
        """
    ).fetchone()["total"]
    assert old_filter == 6
    assert after_global != old_filter


def test_a_further_charge_counts_against_the_caps(conn, cell):
    """The cross-cutting half: a new real-spend transaction type that the
    breaker does not know about is spend the caps cannot see."""
    call = _call(conn, cell)
    reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=120_000, source="inv-B"
    )
    assert real_spend_breaker.snapshot(conn).spend_last_day_minor_units == 12
    assert real_spend_breaker.provider_exposure(conn, "anthropic") == 12
    assert (
        reconciliation.RECONCILIATION_TRANSACTION_TYPE
        in real_spend_breaker._REAL_SPEND_TRANSACTION_TYPES
    )


def test_an_invoice_matching_the_ledger_moves_no_money(conn, cell):
    call = _call(conn, cell)
    before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)
    result = reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=TRUE_COST_MICRO, source="inv-A"
    )
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) == before
    assert reconciliation.net_adjustment_minor_units(conn) == 0
    assert result.reconciled_micro_usd == TRUE_COST_MICRO


def test_sub_cent_rounding_is_not_correctable_per_call(conn, cell):
    """ADR-020's overstatement survives per-call reconciliation, deliberately
    and unavoidably: 3.5 cents of true cost converts back through the same
    ceiling to the 4 already recorded. Pinned as a test so the limitation is
    a stated property rather than a surprise — closing it needs
    reconciliation against an invoice *total* across many calls."""
    call = _call(conn, cell)
    reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=TRUE_COST_MICRO, source="inv-A"
    )
    assert pricing.micro_usd_to_minor_units(TRUE_COST_MICRO) == RECORDED_MINOR
    assert reconciliation.net_adjustment_minor_units(conn) == 0
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == RECORDED_MINOR


# --------------------------------------------------------------------------
# Open reservations: §4.4 resolution, Charter C7
# --------------------------------------------------------------------------


def test_reconciling_an_unknown_call_that_was_billed_settles_from_committed(conn, cell):
    call = _unknown_call(conn, cell)
    assert call.status is ModelCallStatus.EXECUTION_UNKNOWN
    reservation = reservations.get_reservation(conn, call.real_reservation_id)
    assert reservation.status is ReservationStatus.EXECUTION_UNKNOWN
    committed = ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL)
    assert committed > 0

    result = reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=20_000, source="inv-C"
    )

    assert ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL) == 0
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 2
    # Reconciliation is an accounting axis, not an execution outcome: we
    # learned what the call cost, never what it returned.
    assert result.status is ModelCallStatus.EXECUTION_UNKNOWN
    assert result.reconciled_at_utc is not None
    assert result.settled_minor_units == 2
    assert _invariants_hold(conn)


def test_reconciling_an_unknown_call_that_was_not_billed_releases_the_funds(conn, cell):
    """Charter C7 forbids *auto*-releasing an unknown operation. A release
    that is the outcome of reconciliation is the process C7 defers to, not a
    violation of it."""
    cash_before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)
    call = _unknown_call(conn, cell)
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) < cash_before

    reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=0, source="inv-D"
    )

    reservation = reservations.get_reservation(conn, call.real_reservation_id)
    assert reservation.status is ReservationStatus.RELEASED
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) == cash_before
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL) == 0
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 0
    assert _invariants_hold(conn)


def test_an_invoice_above_the_reservation_cap_is_still_recorded_in_full(conn, cell):
    """ADR-021 reached by a different road: `settle` refuses to exceed its
    authorisation, so the excess is posted directly rather than lost."""
    call = _unknown_call(conn, cell)
    cap = reservations.get_reservation(conn, call.real_reservation_id).maximum_amount

    reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=(cap + 5) * 10_000, source="inv-G"
    )

    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == cap + 5
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL) == 0
    assert _invariants_hold(conn)


# --------------------------------------------------------------------------
# Disputes (§4.4)
# --------------------------------------------------------------------------


def test_dispute_moves_the_reservation_without_moving_money(conn, cell):
    call = _unknown_call(conn, cell)
    before = (
        ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL),
        ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL),
    )

    reconciliation.dispute_model_call(conn, call.model_call_id, reason="no response ever arrived")

    reservation = reservations.get_reservation(conn, call.real_reservation_id)
    assert reservation.status is ReservationStatus.DISPUTED
    assert (
        ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL),
        ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL),
    ) == before


def test_a_disputed_call_reconciles_by_release_plus_adjustment(conn, cell):
    """§4.4 gives `disputed` a narrower exit than `execution_unknown` —
    `settled | released`, with no `partially_settled`. Settling a disputed
    hold at less than its full amount is therefore not expressible, so the
    hold is released and the agreed figure posted as its own transaction
    (§3.6). Found by hand-verification: the first implementation tried to
    partially settle and hit InvalidTransitionError.
    """
    call = _unknown_call(conn, cell)
    cap = reservations.get_reservation(conn, call.real_reservation_id).maximum_amount
    reconciliation.dispute_model_call(conn, call.model_call_id, reason="contested")

    reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=10_000, source="inv-E"
    )

    reservation = reservations.get_reservation(conn, call.real_reservation_id)
    assert reservation.status is ReservationStatus.RELEASED
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 1
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL) == 0
    assert cap > 1  # the hold really was larger than the agreed charge
    assert _invariants_hold(conn)


def test_dispute_needs_a_reason(conn, cell):
    call = _unknown_call(conn, cell)
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.dispute_model_call(conn, call.model_call_id, reason="  ")


def test_cannot_dispute_a_settled_call(conn, cell):
    """The FSM already forbids it; this pins that the gateway path inherits
    the guard rather than working around it."""
    call = _call(conn, cell)
    with pytest.raises(reservations.InvalidTransitionError):
        reconciliation.dispute_model_call(conn, call.model_call_id, reason="too late")


# --------------------------------------------------------------------------
# Guards and reporting
# --------------------------------------------------------------------------


def test_reconciling_twice_is_refused_rather_than_double_posted(conn, cell):
    call = _call(conn, cell)
    reconciliation.reconcile_model_call(
        conn, call.model_call_id, invoiced_micro_usd=120_000, source="inv-B"
    )
    with pytest.raises(reconciliation.ReconciliationError, match="already reconciled"):
        reconciliation.reconcile_model_call(
            conn, call.model_call_id, invoiced_micro_usd=120_000, source="inv-B"
        )
    assert reconciliation.net_adjustment_minor_units(conn) == 8


def test_rejects_an_unattributable_or_negative_figure(conn, cell):
    call = _call(conn, cell)
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.reconcile_model_call(
            conn, call.model_call_id, invoiced_micro_usd=1, source="   "
        )
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.reconcile_model_call(
            conn, call.model_call_id, invoiced_micro_usd=-1, source="inv"
        )
    assert reconciliation.net_adjustment_minor_units(conn) == 0


def test_rejects_an_unknown_model_call(conn, cell):
    with pytest.raises(reconciliation.ReconciliationError, match="no such model call"):
        reconciliation.reconcile_model_call(
            conn, "nope", invoiced_micro_usd=1, source="inv"
        )


def test_outstanding_puts_frozen_money_first(conn, cell):
    settled = _call(conn, cell, key="settled")
    unknown = _unknown_call(conn, cell, key="unknown")

    ids = [c.model_call_id for c in reconciliation.outstanding(conn)]
    assert ids[0] == unknown.model_call_id, "an open reservation holds real money and leads"
    assert settled.model_call_id in ids

    reconciliation.reconcile_model_call(
        conn, unknown.model_call_id, invoiced_micro_usd=0, source="inv-D"
    )
    assert [c.model_call_id for c in reconciliation.outstanding(conn)] == [
        settled.model_call_id
    ]


def test_zero_cost_calls_are_not_outstanding_work(conn, cell):
    """A resolved call that cost nothing appears on no invoice, so listing it as
    outstanding is noise that grows without bound as mock calls accumulate. A
    call that cost real money still leads, and one still holding funds is
    outstanding whatever it cost."""
    billable = _call(conn, cell, key="billable")
    free = _call(conn, cell, key="free", provider=_ZeroPricedProvider())

    ids = [c.model_call_id for c in reconciliation.outstanding(conn)]
    assert billable.model_call_id in ids
    assert free.model_call_id not in ids
    assert reconciliation.summary(conn)["calls"] == 1

    # Frozen money outranks costing nothing: an unresolved call stays listed
    # even with no settled amount, because its outcome is unknown.
    unknown = _unknown_call(conn, cell, key="frozen")
    assert unknown.model_call_id in [c.model_call_id for c in reconciliation.outstanding(conn)]


def test_zero_cost_call_can_still_be_reconciled_explicitly(conn, cell):
    """`outstanding` is a worklist, not a gate — excluding a call from it must
    not stop a surprise charge being applied to it."""
    free = _call(conn, cell, key="free", provider=_ZeroPricedProvider())
    reconciled = reconciliation.reconcile_model_call(
        conn, free.model_call_id, invoiced_micro_usd=500, source="surprise-invoice"
    )
    assert reconciled.reconciled_micro_usd == 500


def test_summary_counts_and_frozen_money(conn, cell):
    _call(conn, cell, key="a")
    _unknown_call(conn, cell, key="b")
    stats = reconciliation.summary(conn)
    assert stats["calls"] == 2
    assert stats["reconciled"] == 0
    assert stats["outstanding"] == 2
    assert stats["frozen_minor_units"] > 0


def test_failed_calls_are_not_awaiting_reconciliation(conn, cell):
    """A definitely-unbilled failure released its funds and produced no
    charge, so there is nothing for an invoice to confirm."""
    _call(conn, cell, key="dead", fail="BadRequestError: bad", unknown=False)
    assert reconciliation.outstanding(conn) == []
    assert reconciliation.summary(conn)["calls"] == 0


# --------------------------------------------------------------------------
# Atomicity (Charter C7), same shape as the gateway's
# --------------------------------------------------------------------------


class _Crash(BaseException):
    pass


def test_a_crashed_reconciliation_moves_no_money(tmp_path, monkeypatch):
    """Reconciliation settles a reservation, posts an adjustment, marks the
    row and audits — one transaction, for the same reason the gateway's
    success path is."""
    path = str(tmp_path / "recon.db")
    conn = db.connect_and_migrate(path)
    real_spend_breaker.configure_if_absent(conn)
    created = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=1_000,
        book=Book.USD_REAL,
        idempotency_key="crash-recon-cell",
    )
    _fund(conn, created.cell_id, Book.RESOURCE, 10_000_000)
    _fund(conn, created.cell_id, Book.USD_SIM, 1_000)
    call = _unknown_call(conn, created)
    committed_before = ledger.get_balance(conn, cell_committed(created.cell_id), Book.USD_REAL)
    conn.close()

    conn = db.connect_and_migrate(path)

    def boom(*args, **kwargs):
        raise _Crash("mid-reconciliation")

    monkeypatch.setattr(reconciliation.audit, "record", boom)
    with pytest.raises(_Crash):
        reconciliation.reconcile_model_call(
            conn, call.model_call_id, invoiced_micro_usd=20_000, source="inv-C"
        )
    conn.close()  # process death: never committed
    monkeypatch.undo()

    conn = db.connect_and_migrate(path)
    after = gateway.get_model_call(conn, call.model_call_id)
    assert after.reconciled_at_utc is None
    assert (
        ledger.get_balance(conn, cell_committed(created.cell_id), Book.USD_REAL)
        == committed_before
    )
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 0
    assert (
        reservations.get_reservation(conn, call.real_reservation_id).status
        is ReservationStatus.EXECUTION_UNKNOWN
    )
    assert _invariants_hold(conn)
    conn.close()


# --------------------------------------------------------------------------
# Micro-USD parsing (§30 dollar-string rule at a finer scale)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0", 0), ("1", 1_000_000), ("0.000001", 1), ("0.0035", 3_500), ("12.50", 12_500_000)],
)
def test_parse_micro_usd_is_exact(text, expected):
    assert pricing.parse_micro_usd(text) == expected


@pytest.mark.parametrize("text", ["0.0000001", "1_0", "Infinity", "NaN", "abc", "-1.00"])
def test_parse_micro_usd_rejects_bad_input(text):
    """The same guards money.parse_minor_units grew in slice 10: underscores
    silently change magnitude, and non-finite values crash deeper down."""
    with pytest.raises(pricing.PricingError):
        pricing.parse_micro_usd(text)


def test_format_micro_usd_round_trips():
    for text in ("0.0035", "12.50", "0.000001"):
        assert pricing.parse_micro_usd(pricing.format_micro_usd(pricing.parse_micro_usd(text))) == (
            pricing.parse_micro_usd(text)
        )
