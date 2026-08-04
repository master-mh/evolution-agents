"""Provider-invoice reconciliation (SPEC.md §24.1, §3.6, §4.4; Charter C7).

The kernel's picture of what a model call cost is an estimate twice over: the
ledger holds a *rounded-up* cent figure (ADR-020), and a call that crashed or
timed out holds no figure at all — just committed funds and an honest
`execution_unknown`. Only the provider's invoice settles it. This module is
where that number arrives.

Two paths, chosen by the state of the call's USD_REAL reservation:

    reservation still open        the money was never spent, so resolve it
    (`reserved`/`execution_unknown`)   through the FSM: settle at the invoiced
                                  amount, release any remainder, or release
                                  outright if the invoice shows no charge

    reservation terminal          the money already moved, and §3.6 forbids
    (`settled`/`released`/...)    editing history — so the difference is
                                  posted as a **new** adjustment transaction

Both paths end the same way: `reconciled_micro_usd` is written (§24.1's
"reconciled cost"), provenance is recorded, and an audit event is filed.
Everything happens in one transaction, using the `_*_locked` cores — a
reconciliation that half-applied would be worse than one that never ran.

**Never edits a historical transaction** (§3.6). An adjustment is always a
new, signed posting: positive when the provider billed more than the ledger
recorded, negative when it billed less.

**What this does *not* fix: ADR-020's rounding overstatement.** That was the
stated motivation, and per-call reconciliation turns out not to address it.
A call whose true cost is 3.5 cents was recorded at 4; reconciling it against
an invoice of 3.5 cents converts that figure through the same
`micro_usd_to_minor_units` ceiling and gets 4 again, so the adjustment is
zero. It cannot be otherwise: the overstatement is sub-minor-unit by
construction, and the ledger has no way to hold half a cent. Rounding error
only becomes correctable in aggregate — ten such calls are 35 cents of true
cost recorded as 40 — so closing it needs reconciliation against an *invoice
total* covering many calls, posting one adjustment for the difference. That
is a real gap and is logged rather than papered over; what this module does
fix is **estimate error**, where the provider billed a materially different
amount than the pricing table predicted, and **unknown outcomes**, where the
kernel had recorded nothing at all.

**Reconciliation is an accounting axis, not an execution outcome.** A call
that crashed stays `execution_unknown` after reconciliation: we learned what
it cost, not what it returned, and relabelling it `succeeded` would invent a
response the kernel never saw. `reconciled_at_utc` is what distinguishes a
resolved unknown from an outstanding one. This is the same
authorisation-versus-accounting split ADR-021 draws.

Deliberately out of scope for this slice:

- **Fetching the invoice.** The operator supplies the figure; nothing calls a
  billing API or parses a statement. Bulk import is the obvious next step and
  needs no new kernel concepts.
- **Resolving a `disputed` reservation.** `dispute` moves it there (§4.4's
  `execution_unknown -> disputed`); carrying it to `settled`/`released` is the
  same two functions here, but the human process around it is §23 governance,
  which does not exist.
- **Reconciling `resource_usage` against gateway logs** — Amendment A6's other
  half. Needs a log to reconcile against; §24.1's cost side is what has an
  invoice.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import audit, gateway, ledger, pricing, reservations
from .accounts import cell_cash
from .models import Book, EntrySpec, ModelCall, ReservationStatus

_EXTERNAL_EXPENSE = "external_expense"

# Real money moving because an invoice disagreed with the estimate. Signed:
# positive is a further charge, negative is a credit back to the Cell. Both
# are the same transaction type on purpose — the sign carries the direction,
# and real_spend_breaker sums the signed `external_expense` leg, so a credit
# correctly *reduces* measured exposure instead of inflating it.
RECONCILIATION_TRANSACTION_TYPE = "model_call_reconciliation_adjustment"

# A reservation whose funds are still committed — reconciliation resolves it
# through the FSM rather than by posting an adjustment beside it. Public
# because "is this reservation still holding money?" is a question callers
# ask too: a released reservation also has a non-zero
# `maximum_amount - settled_amount`, but that is the amount it gave back, not
# money still frozen.
OPEN_RESERVATION_STATUSES = frozenset(
    {ReservationStatus.RESERVED, ReservationStatus.EXECUTION_UNKNOWN, ReservationStatus.DISPUTED}
)


class ReconciliationError(Exception):
    pass


def reconcile_model_call(
    conn: sqlite3.Connection,
    model_call_id: str,
    *,
    invoiced_micro_usd: int,
    source: str,
    note: str = "",
) -> ModelCall:
    """Reconcile one model call against what the provider actually invoiced.

    `invoiced_micro_usd` is the authoritative figure in micro-USD; 0 means the
    provider did not bill for this call at all. `source` records where it came
    from (an invoice id, a console export, "manual") and is stored on the row.

    Idempotent in the only sense that matters for money: a call that already
    carries a `reconciled_at_utc` is refused rather than adjusted twice.
    """
    if invoiced_micro_usd < 0:
        raise ReconciliationError("invoiced_micro_usd cannot be negative")
    if not source.strip():
        raise ReconciliationError("source is required — an unattributable figure is not evidence")

    now = datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Re-read inside the write lock: two operators reconciling the same
        # call must not both pass the already-reconciled check.
        call = gateway.get_model_call(conn, model_call_id)
        if call is None:
            raise ReconciliationError(f"no such model call: {model_call_id}")
        if call.reconciled_at_utc is not None:
            raise ReconciliationError(
                f"model call {model_call_id} was already reconciled at "
                f"{call.reconciled_at_utc.isoformat()} against "
                f"{call.reconciliation_source!r} — reconciling twice would "
                "double-post the adjustment"
            )

        reservation = reservations.get_reservation(conn, call.real_reservation_id)
        if reservation is None:
            raise ReconciliationError(
                f"model call {model_call_id} names a reservation that does not exist"
            )

        invoiced_minor = pricing.micro_usd_to_minor_units(invoiced_micro_usd)
        recorded_minor = call.settled_minor_units

        if reservation.status in OPEN_RESERVATION_STATUSES:
            adjustment = _resolve_open_reservation(
                conn,
                call=call,
                reservation_status=reservation.status,
                reservation_id=reservation.reservation_id,
                reservation_maximum=reservation.maximum_amount,
                invoiced_minor=invoiced_minor,
            )
        else:
            adjustment = invoiced_minor - recorded_minor
            if adjustment != 0:
                _post_adjustment_locked(
                    conn,
                    call=call,
                    amount=adjustment,
                    recorded_minor=recorded_minor,
                    invoiced_minor=invoiced_minor,
                )

        conn.execute(
            """
            UPDATE model_calls SET
                reconciled_micro_usd = ?, reconciled_at_utc = ?,
                reconciliation_source = ?
            WHERE model_call_id = ?
            """,
            (invoiced_micro_usd, now.isoformat(), source, model_call_id),
        )
        audit.record(
            conn,
            event_type="model_call_reconciled",
            cell_id=call.cell_id,
            description=(
                f"model call {model_call_id} reconciled against {source!r}: "
                f"invoiced {invoiced_micro_usd} micro-USD "
                f"({invoiced_minor} minor), ledger had {recorded_minor} minor, "
                f"adjustment {adjustment:+d}"
                + (f" — {note}" if note else "")
            ),
            metadata={
                "model_call_id": model_call_id,
                "provider": call.provider,
                "invoiced_micro_usd": invoiced_micro_usd,
                "cost_actual_micro_usd": call.cost_actual_micro_usd,
                "recorded_minor_units": recorded_minor,
                "adjustment_minor_units": adjustment,
                "reservation_status_before": reservation.status.value,
                "source": source,
                "note": note,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = gateway.get_model_call(conn, model_call_id)
    assert result is not None
    return result


def _resolve_open_reservation(
    conn: sqlite3.Connection,
    *,
    call: ModelCall,
    reservation_status: ReservationStatus,
    reservation_id: str,
    reservation_maximum: int,
    invoiced_minor: int,
) -> int:
    """§4.4's `execution_unknown -> settled | partially_settled | released`.

    Nothing was spent yet — the funds are sitting in `cell:{id}:committed` —
    so the invoice is applied by settling, not by adjusting. Returns the
    amount that ended up charged, which is also the adjustment relative to
    the zero the ledger had recorded.

    An invoice above the reservation cap is the ADR-021 situation reached by a
    different road: `settle` refuses to exceed its authorisation, so the
    settlement is clamped and the excess posted directly. The charge is
    already incurred; C4 governed the authorisation, which happened when the
    reservation was taken.
    """
    if invoiced_minor <= 0:
        # The provider did not bill. This is the one case where releasing an
        # `execution_unknown` reservation is correct rather than a Charter C7
        # violation: C7 forbids *auto*-releasing an unknown operation, and
        # this release is the outcome of reconciliation, which is exactly the
        # process C7 defers to.
        reservations._release_locked(conn, reservation_id)
        return 0

    if reservation_status is ReservationStatus.DISPUTED:
        # §4.4 gives `disputed` a deliberately narrower exit than
        # `execution_unknown`: `settled | released`, with no
        # `partially_settled`. So a disputed charge finally agreed at less
        # than the full hold cannot be settled against its own reservation.
        # Release the hold and post the agreed amount as its own transaction
        # — which is both what §3.6 prescribes for reconciliation adjustments
        # and how a disputed charge actually resolves commercially: the hold
        # comes off, the agreed figure is billed separately. Done for every
        # disputed amount, not just partial ones, so the path is one shape
        # rather than branching on an accident of arithmetic.
        reservations._release_locked(conn, reservation_id)
        _post_adjustment_locked(
            conn,
            call=call,
            amount=invoiced_minor,
            recorded_minor=0,
            invoiced_minor=invoiced_minor,
        )
        conn.execute(
            "UPDATE model_calls SET settled_minor_units = ? WHERE model_call_id = ?",
            (invoiced_minor, call.model_call_id),
        )
        return invoiced_minor

    settle_minor = min(invoiced_minor, reservation_maximum)
    reservations._settle_locked(
        conn,
        reservation_id,
        settled_amount=settle_minor,
        destination_account_id=_EXTERNAL_EXPENSE,
    )
    if settle_minor < reservation_maximum:
        reservations._release_locked(conn, reservation_id)

    if invoiced_minor > settle_minor:
        _post_adjustment_locked(
            conn,
            call=call,
            amount=invoiced_minor - settle_minor,
            recorded_minor=settle_minor,
            invoiced_minor=invoiced_minor,
        )

    conn.execute(
        "UPDATE model_calls SET settled_minor_units = ? WHERE model_call_id = ?",
        (invoiced_minor, call.model_call_id),
    )
    return invoiced_minor


def _post_adjustment_locked(
    conn: sqlite3.Connection,
    *,
    call: ModelCall,
    amount: int,
    recorded_minor: int,
    invoiced_minor: int,
) -> None:
    """§3.6: "post reconciliation adjustments as **new** transactions."

    Signed. A positive `amount` is further real money leaving the colony
    (cell cash -> external_expense); a negative one is a credit coming back
    (external_expense -> cell cash), which is the routine case because
    ADR-020 rounds every call up to the whole cent.

    Caller holds the write transaction.
    """
    if amount == 0:
        return
    ledger._post_transaction_locked(
        conn,
        book=Book.USD_REAL,
        currency="USD",
        transaction_type=RECONCILIATION_TRANSACTION_TYPE,
        idempotency_key=f"{RECONCILIATION_TRANSACTION_TYPE}:{call.model_call_id}",
        description=(
            f"reconciliation of model call {call.model_call_id}: "
            f"invoiced {invoiced_minor}, ledger had {recorded_minor}"
        ),
        entries=[
            EntrySpec(
                account_id=cell_cash(call.cell_id),
                amount_minor_units=-amount,
                cell_id=call.cell_id,
                experiment_id=call.experiment_id,
            ),
            EntrySpec(
                account_id=_EXTERNAL_EXPENSE,
                amount_minor_units=amount,
                cell_id=call.cell_id,
                experiment_id=call.experiment_id,
            ),
        ],
    )


def dispute_model_call(
    conn: sqlite3.Connection, model_call_id: str, *, reason: str
) -> ModelCall:
    """§4.4's `execution_unknown -> disputed`: the operator contests the
    charge rather than accepting it.

    No money moves — the funds stay committed exactly as they were. This
    records that the uncertainty is now being actively challenged instead of
    merely outstanding, which is the distinction §4.4 draws between the two
    states.
    """
    if not reason.strip():
        raise ReconciliationError("a dispute needs a reason")

    conn.execute("BEGIN IMMEDIATE")
    try:
        call = gateway.get_model_call(conn, model_call_id)
        if call is None:
            raise ReconciliationError(f"no such model call: {model_call_id}")
        reservations._bare_status_transition_locked(
            conn, call.real_reservation_id, ReservationStatus.DISPUTED
        )
        audit.record(
            conn,
            event_type="model_call_disputed",
            cell_id=call.cell_id,
            description=f"model call {model_call_id} disputed: {reason}",
            metadata={
                "model_call_id": model_call_id,
                "provider": call.provider,
                "reason": reason,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = gateway.get_model_call(conn, model_call_id)
    assert result is not None
    return result


# A call worth checking against a provider invoice: one that has already moved
# real money, one that recorded a real cost, or one still holding funds whose
# outcome is unknown. A resolved zero-cost call is none of these. Kept as one
# string so `outstanding` and `summary` cannot drift apart — the same split that
# let a third real-spend type be missed by one of two breaker queries.
_BILLABLE_PREDICATE = """(
            m.settled_minor_units > 0
            OR COALESCE(m.cost_actual_micro_usd, 0) > 0
            OR r.status IN ('reserved', 'execution_unknown', 'disputed')
        )"""


def outstanding(conn: sqlite3.Connection) -> list[ModelCall]:
    """Every call still awaiting reconciliation, worst first.

    Two kinds, and the ordering says which matters more: a call whose
    reservation is still open has real money frozen in `committed` and cannot
    resolve itself, so it leads. Behind it sit already-settled calls, where
    reconciliation only confirms or corrects a figure that has already moved.

    A call that neither cost anything nor holds anything is excluded: a
    zero-priced provider (the mock) produces calls no invoice will ever list, so
    counting them as outstanding is noise that grows without bound as mock calls
    accumulate. This is a worklist, not a gate — `reconcile` still accepts any
    model_call_id, so a surprise charge on a nominally free call can still be
    applied.
    """
    rows = conn.execute(
        f"""
        SELECT m.model_call_id AS model_call_id
        FROM model_calls m
        JOIN reservations r ON r.reservation_id = m.real_reservation_id
        WHERE m.reconciled_at_utc IS NULL
          AND m.status != 'failed'
          AND {_BILLABLE_PREDICATE}
        ORDER BY
          CASE WHEN r.status IN ('reserved', 'execution_unknown', 'disputed')
               THEN 0 ELSE 1 END,
          m.created_at_utc
        """
    ).fetchall()
    calls = []
    for row in rows:
        call = gateway.get_model_call(conn, row["model_call_id"])
        assert call is not None
        calls.append(call)
    return calls


def summary(conn: sqlite3.Connection) -> dict[str, int]:
    """Counts for `mitosis status`: how much of the colony's real spend has
    been checked against an invoice, and how much has not."""
    row = conn.execute(
        f"""
        SELECT
          COUNT(*) AS total,
          COALESCE(SUM(CASE WHEN m.reconciled_at_utc IS NOT NULL THEN 1 ELSE 0 END), 0)
            AS reconciled
        FROM model_calls m
        JOIN reservations r ON r.reservation_id = m.real_reservation_id
        WHERE m.status != 'failed'
          AND {_BILLABLE_PREDICATE}
        """
    ).fetchone()
    frozen = conn.execute(
        """
        SELECT COALESCE(SUM(r.maximum_amount - r.settled_amount), 0) AS frozen
        FROM model_calls m
        JOIN reservations r ON r.reservation_id = m.real_reservation_id
        WHERE m.reconciled_at_utc IS NULL
          AND r.status IN ('reserved', 'execution_unknown', 'disputed')
        """
    ).fetchone()
    return {
        "calls": row["total"],
        "reconciled": row["reconciled"],
        "outstanding": row["total"] - row["reconciled"],
        "frozen_minor_units": frozen["frozen"],
    }


def net_adjustment_minor_units(conn: sqlite3.Connection) -> int:
    """Signed total the ledger has moved because invoices disagreed with
    estimates. Derived from the ledger rather than stored (Charter C3).

    Expected to sit near zero: the pricing table is usually right to the cent,
    and per-call reconciliation cannot express the sub-cent rounding drift
    (see the module docstring). A figure that keeps growing in either
    direction means the pricing table is wrong, not that rounding is being
    corrected."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.transaction_type = ? AND e.account_id = ?
        """,
        (RECONCILIATION_TRANSACTION_TYPE, _EXTERNAL_EXPENSE),
    ).fetchone()
    return row["total"]
