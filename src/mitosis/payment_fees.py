"""Payment fees: what a processor keeps from a charge (SPEC.md §1.1, §2.2, §3.6,
§5.1; ADR-098).

§1.1's `REAL_SETTLED_NET_PROFIT` subtracts "payment fees" from settled revenue,
§2.2 lists payment processing among USD_REAL's external money, and §3.6
reconciles against payment-processor transactions, which report a fee per charge.
Until this module no path could record one, so every live sale would have
overstated profit by its fee.

**Imposed, not chosen.** Nobody reserves a processor's fee before the sale; the
processor takes it. So it is posted directly, as `gateway`'s cost overrun is
(ADR-021), and never refused by a cap: refusing to record money already taken
would misstate the books without un-taking it. It is registered as real spend,
so every global window counts it afterwards and the next spend the colony *does*
choose meets a cap the fee helped fill.

**Registered, and counted by no provider's cap.** §5.1's per-provider cap bounds
exposure to a provider the colony reserves against. Nothing reserves against a
processor, so a processor cap would bound nothing, and the per-provider window
reaches a direct posting only through the model call its key names — which a fee
does not have. `real_spend_breaker._PROVIDERLESS_REAL_SPEND_TYPES` says so, and
the registration guard requires every registered type to sit in exactly one route.

**Names the charge and inherits its attribution** — a revenue payment or a
chargeback (a chargeback fee routinely arrives with the chargeback). The Cell,
book, experiment and artifact are the charge's own, read from its Cell leg; there
is no parameter to name them, for `revenue.record_reversal`'s reason (§16.3). The
buyer's digest is *not* copied: the fee's counterparty is the processor, and
§16.3's digest identifies the people who paid.

**Consumption, with no reader changed.** The fee posts Cell cash to
`external_expense`, a `SPEND_DESTINATION`, tagged with the Cell and experiment,
so `ledger.spend_by_book`, §10.5's net contribution and §2.6's real spend all
see it already.

**Not bounded by the charge.** A fixed per-charge fee on a small sale, or a
chargeback fee, can exceed the sale. A dead Cell pays its fees like a living one,
and its cash may go negative (ADR-021's rule, as for a refund).

Out of scope: a processor returning a fee (a signed adjustment, reconciliation's
shape); fees on payouts or currency conversion that belong to no charge; importing
a processor's statement.
"""

from __future__ import annotations

import sqlite3

from . import audit, ledger, lifecycle, revenue
from .models import EntrySpec, Transaction

PAYMENT_FEE_TRANSACTION_TYPE = "payment_fee"
_EXTERNAL_EXPENSE = "external_expense"

#: What a processor takes a fee on. A refund is not here: the fee on the sale it
#: refunds was charged on the sale, and a fee "on a refund" would count it twice.
CHARGEABLE_TRANSACTION_TYPES = (
    revenue.REVENUE_TRANSACTION_TYPE,
    revenue.CHARGEBACK_TRANSACTION_TYPE,
)


class PaymentFeeError(Exception):
    pass


def record_payment_fee(
    conn: sqlite3.Connection,
    *,
    charged_on_transaction_id: str,
    amount_minor_units: int,
    source: str,
    note: str = "",
    idempotency_key: str | None = None,
) -> Transaction:
    """Record what a processor kept from one charge.

    `source` is the processor's reference for the fee (a balance-transaction
    id), never the customer. `idempotency_key` defaults to one derived from the
    charge and the source, so the same fee recorded twice posts once.

    Refuses a charge that does not exist or is not a revenue payment or a
    chargeback, and a key already used for a different fee. Never refuses on a
    real-spend cap — see the module docstring.
    """
    if amount_minor_units <= 0:
        raise PaymentFeeError(
            f"a fee must be positive, got {amount_minor_units} — a processor returning "
            "a fee is an adjustment, not a negative fee"
        )
    if not source.strip():
        raise PaymentFeeError(
            "source is required — a fee with no reference cannot be matched to the "
            "processor record it came from (§3.6)"
        )
    key = idempotency_key or (
        f"{PAYMENT_FEE_TRANSACTION_TYPE}:{charged_on_transaction_id}:{source.strip()}"
    )

    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = ledger.get_transaction_by_idempotency_key(conn, key)
        if existing is not None:
            if (
                existing.transaction_type != PAYMENT_FEE_TRANSACTION_TYPE
                or existing.charged_on_transaction_id != charged_on_transaction_id
            ):
                raise PaymentFeeError(
                    f"idempotency key {key!r} already belongs to a different "
                    f"transaction ({existing.transaction_type})"
                )
            conn.execute("ROLLBACK")
            return existing

        charge = ledger.get_transaction(conn, charged_on_transaction_id)
        if charge is None:
            raise PaymentFeeError(f"no such transaction: {charged_on_transaction_id}")
        if charge.transaction_type not in CHARGEABLE_TRANSACTION_TYPES:
            raise PaymentFeeError(
                f"{charged_on_transaction_id} is a {charge.transaction_type!r} transaction — "
                "a fee is taken on a revenue payment or a chargeback"
            )
        leg = revenue.cell_leg(charge)

        transaction = ledger._post_transaction_locked(
            conn,
            book=charge.book,
            currency=charge.currency,
            transaction_type=PAYMENT_FEE_TRANSACTION_TYPE,
            idempotency_key=key,
            charged_on_transaction_id=charge.transaction_id,
            description=(
                f"payment fee on {charge.transaction_id} for cell {leg.cell_id} "
                f"({source.strip()})" + (f": {note}" if note else "")
            ),
            entries=[
                EntrySpec(
                    account_id=leg.account_id,
                    amount_minor_units=-amount_minor_units,
                    cell_id=leg.cell_id,
                    experiment_id=leg.experiment_id,
                    artifact_id=leg.artifact_id,
                ),
                EntrySpec(
                    account_id=_EXTERNAL_EXPENSE,
                    amount_minor_units=amount_minor_units,
                    # Both tags on the expense leg: `spend_by_book` selects by
                    # cell_id and §2.6's report by experiment_id, and each reads
                    # this leg, not the cash one.
                    cell_id=leg.cell_id,
                    experiment_id=leg.experiment_id,
                ),
            ],
        )

        cell = lifecycle.get_cell(conn, leg.cell_id)
        audit.record(
            conn,
            event_type="payment_fee_recorded",
            cell_id=leg.cell_id,
            metadata={
                "amount_minor_units": amount_minor_units,
                "book": charge.book.value,
                "source": source.strip(),
                "note": note,
                "charged_on_transaction_id": charge.transaction_id,
                "charged_on_type": charge.transaction_type,
                "cell_status": cell.status.value if cell is not None else None,
                "transaction_id": transaction.transaction_id,
            },
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()
    return transaction
