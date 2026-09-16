"""Revenue: the path by which money enters the colony, and the one by which it
goes back (SPEC.md §31, §2.2, §1.1).

Until now every USD_REAL movement in MITOSIS was capital being seeded, moved
between internal accounts, or spent. The `revenue` account existed in §31's
fixed-account list and nothing ever posted to it, which meant a Cell's
profitability was not merely unmeasured but *unmeasurable* — the number had no
place to live. This module gives it one.

**Direction and sign.** Revenue mirrors spend exactly. A spend debits the Cell
and credits `external_expense`; revenue debits `revenue` and credits the Cell's
cash. `revenue` therefore accumulates a *negative* balance whose magnitude is
earnings net of reversals, the same convention `external_capital` already uses
for seed capital — an external source is a place value comes from, so it goes
negative. Conservation per book (Charter C2) holds unchanged.

**Revenue is not a spend, and must never be counted as one.** It does not touch
`external_expense`, so it is invisible to the real-spend breaker, and that is
correct: Charter C5's caps bound how much the colony may *spend*, not its net
position. A Cell that earns does not thereby earn permission to exceed the
hour/day/month caps. Earnings do raise its cash balance, so Charter C4 lets it
reserve more — that is the intended and only coupling. Pinned by
`test_revenue_does_not_move_the_spend_breaker`.

**Attribution is required.** Like reconciliation, revenue takes a `source` and
refuses to post without one. An unattributable credit to a Cell is precisely
how a fitness signal gets fabricated, and fitness is what this exists to feed.

**A dead Cell can still receive revenue.** Payment arrives after work, sometimes
after the worker is gone, and a coroner report that omits a Cell's final earnings
would misstate the thing it exists to record. Status is therefore not checked —
but the Cell must exist, so revenue cannot be posted to a typo.

**Reversals (ADR-097).** §2.2 lists refunds and chargebacks in both money books,
§1.1 subtracts both from `REAL_SETTLED_NET_PROFIT`, and §28 Phase 9's acceptance
requires them tracked. `record_reversal` posts a payment's mirror image — debit
the Cell's cash, credit `revenue` — which `accounts.py` already classifies as
"un-earning, not spending": it never touches `external_expense`, so it is
neither consumption (`ledger.spend_by_book`) nor spend the breaker bounds. Three
rules, each closing a way a refunded Cell could keep revenue it no longer has:

- **It names the payment and inherits everything else from it** — Cell, book,
  experiment, artifact, counterparty. §16.3: "revenue-producing assets cannot
  transfer without their related refund liabilities", so a refund lands on the
  Cell that made the sale, and there is no parameter through which a caller could
  land it anywhere else (ADR-044: attribution is derived, never supplied).
- **Reversals of one payment never exceed it.** Money handed back beyond a sale
  is not a refund of that sale; it is an expense.
- **A dead Cell is reversed like a living one, and its cash may go negative.**
  Its estate has already gone to the treasury, and `lifecycle._reclaim_locked`
  leaves a negative balance visible rather than absorbing it (ADR-021's rule). A
  refund that arrives after death is exactly that debt.

**Gross, reversed, net.** There is no `total_revenue`. It meant gross, and every
reader of it — §10.5's domination, §25.2's read-back, the Cell's own record, the
simulator's fitness axes — wanted net, so a reversal would have been invisible to
all of them. Removing the name made each reader choose.

Deliberately out of scope: recurring or accrued revenue; a chargeback the
colony later wins back; anything that fetches money from a real payment
processor. The operator supplies the figure, exactly as with an invoice.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from enum import Enum

from . import audit, ledger, lifecycle
from .accounts import cell_cash
from .counterparty import CounterpartyError
from .counterparty import hash_of as counterparty_digest
from .models import Book, Entry, EntrySpec, Transaction

REVENUE_ACCOUNT = "revenue"
REVENUE_TRANSACTION_TYPE = "cell_revenue"
REFUND_TRANSACTION_TYPE = "cell_refund"
CHARGEBACK_TRANSACTION_TYPE = "cell_chargeback"

#: Every type that takes a payment back. Migration 0037's CHECK names the same
#: two, and `test_revenue_reversal.py` pins the tuple to the schema.
REVERSAL_TRANSACTION_TYPES = (REFUND_TRANSACTION_TYPE, CHARGEBACK_TRANSACTION_TYPE)

# RESOURCE is a shadow-price book for metering internal consumption (§2.2).
# Nobody pays a colony in compute units, and allowing it would let a Cell's
# RESOURCE budget be topped up by declaring revenue, which is not a thing that
# can happen.
_REVENUE_BOOKS = frozenset({Book.USD_REAL, Book.USD_SIM})


class RevenueError(Exception):
    pass


class ReversalKind(str, Enum):
    """§1.1 names refunds and chargebacks as separate terms and §10.2 asks for
    their *rate*, so the kind is kept — on the hash-chained transaction type,
    not in a field beside it."""

    REFUND = "refund"
    CHARGEBACK = "chargeback"


_REVERSAL_TYPE = {
    ReversalKind.REFUND: REFUND_TRANSACTION_TYPE,
    ReversalKind.CHARGEBACK: CHARGEBACK_TRANSACTION_TYPE,
}


def record_revenue(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    amount_minor_units: int,
    source: str,
    book: Book = Book.USD_REAL,
    note: str = "",
    artifact_id: str | None = None,
    #: Which experiment earned it (§2.6). Amendment A3 gave `artifact_id` the
    #: same job for *what* produced the money; this says under which test.
    experiment_id: str | None = None,
    #: Who paid, hashed on the way in and never stored as themselves (§16.3).
    #: This is §12.1's missing inbound key — see the docstring.
    counterparty: str | None = None,
    idempotency_key: str | None = None,
) -> Transaction:
    """Credit a Cell with money it earned.

    `source` records who paid and for what — an invoice id, a customer
    reference, "manual". Stored on the transaction and on the audit event.

    `artifact_id` names **what was sold**, populating Amendment A3's
    `ledger_entries.artifact_id` — a required field that has existed since
    migration 0001 and that nothing populated until the artifact store. It is
    the edge §11.4's contribution graph needs between a Cell's work and the
    money that followed it: without it, attribution is a free-text string and
    fitness cannot see which deliverable earned.

    **Optional, deliberately.** Making it mandatory would force every payment to
    name a deliverable, which is the right pressure for a sale — but not every
    receipt has an artifact behind it (a retainer, a reversal, an operator
    correction), and a required field that people satisfy with a placeholder is
    worse than an honest null. Revisit when something actually sells.

    `idempotency_key` defaults to one derived from the source, so posting the
    same attributed payment twice is refused by the ledger's own idempotency
    rather than silently doubling a Cell's apparent fitness. **A repeat customer
    therefore needs a distinct `source` or an explicit key**, which is correct —
    two invoices from one buyer are two payments, and one invoice recorded twice
    is not.

    `counterparty` is **who paid**, and it is hashed before it is stored
    (`counterparty.hash_of`, §16.3's per-colony salt) — the colony keeps the
    ability to ask "is this the same buyer as that one?" and no ability
    whatever to say who they are. It is the same digest §21.2 uses outbound, so
    a party the colony contacted and who then pays produces the same key on both
    sides without either side holding an identity.

    **`source` is not a place to put the counterparty.** It is free text and it
    is interpolated into the transaction description, which *is* covered by the
    hash chain — an email address typed there is in the ledger permanently and
    §3.6 forbids editing it out. Put the invoice reference in `source` and the
    party in `counterparty`.

    Optional for the same reason `artifact_id` is: revenue recorded before this
    key existed genuinely has no counterparty, and backfilling one from `source`
    would fabricate the attribution this module exists to prevent.
    `novelty._revenue_recurrence` abstains on a partial record rather than
    reading `one_off` out of it.
    """
    if amount_minor_units <= 0:
        raise RevenueError(
            f"revenue must be positive, got {amount_minor_units} — a refund or "
            "chargeback is `record_reversal`, which names the payment it takes back"
        )
    if book not in _REVENUE_BOOKS:
        raise RevenueError(
            f"cannot record revenue in {book.value}: revenue is money, and "
            f"{Book.RESOURCE.value} is a shadow-price book for metering"
        )
    if not source.strip():
        raise RevenueError(
            "source is required — unattributed revenue is how a fitness signal "
            "gets fabricated"
        )
    if counterparty is not None and not counterparty.strip():
        raise RevenueError(
            "counterparty was supplied but is blank — a payment from nobody in "
            "particular is what `counterparty=None` already says, and saying it "
            "twice in different ways would put an empty digest in the ledger"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Inside the write lock so a Cell cannot be killed and reaped between
        # the existence check and the posting.
        cell = lifecycle.get_cell(conn, cell_id)
        if cell is None:
            raise RevenueError(f"no such cell: {cell_id}")

        if artifact_id is not None:
            # Checked inside the lock like everything else here. An attribution
            # to a nonexistent artifact is worse than none: it looks like
            # provenance and points nowhere.
            exists = conn.execute(
                "SELECT 1 FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
            if exists is None:
                raise RevenueError(
                    f"no such artifact: {artifact_id} — revenue cannot be attributed "
                    "to something the colony never made"
                )

        # Hashed inside the lock, because the salt row is created lazily on
        # first use: doing it before BEGIN IMMEDIATE would autocommit that write
        # separately from the payment it belongs to.
        try:
            digest = (
                counterparty_digest(conn, counterparty)
                if counterparty is not None
                else None
            )
        except CounterpartyError as exc:  # pragma: no cover - guarded above
            raise RevenueError(str(exc)) from exc

        key = idempotency_key or f"{REVENUE_TRANSACTION_TYPE}:{cell_id}:{source.strip()}"
        transaction = ledger._post_transaction_locked(
            conn,
            book=book,
            currency="USD" if book is Book.USD_REAL else book.value,
            transaction_type=REVENUE_TRANSACTION_TYPE,
            idempotency_key=key,
            counterparty_hash=digest,
            description=f"revenue for cell {cell_id} from {source.strip()}"
            + (f": {note}" if note else ""),
            entries=[
                EntrySpec(
                    account_id=REVENUE_ACCOUNT,
                    amount_minor_units=-amount_minor_units,
                    # Tagged on the revenue leg as well as the cash leg, because
                    # §2.6's report reads the *revenue account* for what an
                    # experiment earned — the cash leg alone would make revenue
                    # indistinguishable from any other credit to the Cell.
                    experiment_id=experiment_id,
                ),
                EntrySpec(
                    account_id=cell_cash(cell_id),
                    amount_minor_units=amount_minor_units,
                    cell_id=cell_id,
                    experiment_id=experiment_id,
                    artifact_id=artifact_id,
                ),
            ],
        )
        audit.record(
            conn,
            event_type="cell_revenue_recorded",
            cell_id=cell_id,
            metadata={
                "amount_minor_units": amount_minor_units,
                "artifact_id": artifact_id,
                "book": book.value,
                "source": source.strip(),
                # Whether, never who — the same rule §21.2's registry follows.
                # The digest is not an identity, but it is a *linkable key*, and
                # audit events are read by paths a Cell can reach.
                "counterparty_recorded": digest is not None,
                "note": note,
                "cell_status": cell.status.value,
                "transaction_id": transaction.transaction_id,
            },
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()
    return transaction


def record_reversal(
    conn: sqlite3.Connection,
    *,
    revenue_transaction_id: str,
    amount_minor_units: int,
    source: str,
    kind: ReversalKind = ReversalKind.REFUND,
    note: str = "",
    idempotency_key: str | None = None,
) -> Transaction:
    """Take back some or all of one revenue payment: a refund or a chargeback.

    **There is no `cell_id`, `book`, `experiment_id`, `artifact_id` or
    `counterparty` parameter, and that is the guarantee.** All five are read off
    the payment. A caller who could name the Cell could refund a sale against a
    sibling that never made it — §16.3's escape, where one lineage keeps the
    asset and another carries the liability — and a structural test asserts the
    signature stays this narrow.

    `source` is the processor's reference for the refund — never the customer,
    for the reason `record_revenue` gives. `idempotency_key` defaults to one
    derived from the payment and the source, so the same refund recorded twice
    posts once, and two partial refunds of one sale need two references.

    Refuses: a payment that does not exist or is not revenue (including a
    reversal, which is not itself revenue), and an amount larger than what
    earlier reversals of the same payment left. A replay of an already-posted
    reversal returns it *before* that bound is checked — otherwise retrying a
    full refund would be refused as exceeding the sale it had already reversed.
    """
    kind = ReversalKind(kind)
    if amount_minor_units <= 0:
        raise RevenueError(
            f"a reversal must be positive, got {amount_minor_units} — it is the "
            "amount taken back, and the direction is already the reversal's"
        )
    if not source.strip():
        raise RevenueError(
            "source is required — a reversal with no reference cannot be matched "
            "to the processor record that issued it"
        )
    transaction_type = _REVERSAL_TYPE[kind]
    key = idempotency_key or f"{transaction_type}:{revenue_transaction_id}:{source.strip()}"

    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = ledger.get_transaction_by_idempotency_key(conn, key)
        if existing is not None:
            if (
                existing.transaction_type != transaction_type
                or existing.reverses_transaction_id != revenue_transaction_id
            ):
                raise RevenueError(
                    f"idempotency key {key!r} already belongs to a different "
                    f"transaction ({existing.transaction_type})"
                )
            conn.execute("ROLLBACK")
            return existing

        payment = ledger.get_transaction(conn, revenue_transaction_id)
        if payment is None:
            raise RevenueError(f"no such transaction: {revenue_transaction_id}")
        if payment.transaction_type != REVENUE_TRANSACTION_TYPE:
            raise RevenueError(
                f"{revenue_transaction_id} is a {payment.transaction_type!r} transaction — "
                "only a revenue payment can be reversed, and a reversal is not revenue"
            )
        cash_leg, revenue_leg = _legs(payment)
        remaining = _reversible_locked(conn, payment, cash_leg)
        if amount_minor_units > remaining:
            raise RevenueError(
                f"cannot reverse {amount_minor_units} of payment {revenue_transaction_id}: "
                f"{remaining} of its {cash_leg.amount_minor_units} is left after earlier "
                "reversals. Money handed back beyond a sale is not a refund of it"
            )

        posting = dict(
            payment=payment,
            cash_leg=cash_leg,
            revenue_leg=revenue_leg,
            amount_minor_units=amount_minor_units,
            idempotency_key=key,
            description=(
                f"{kind.value} of {revenue_transaction_id} for cell {cash_leg.cell_id} "
                f"({source.strip()})" + (f": {note}" if note else "")
            ),
        )
        # One call per type, each naming its constant, so the AST walk in
        # `test_real_spend_registration.py` classifies both — a type relayed
        # through a variable would reach the ledger unclassified.
        if kind is ReversalKind.REFUND:
            transaction = _post_reversal_locked(
                conn, transaction_type=REFUND_TRANSACTION_TYPE, **posting
            )
        else:
            transaction = _post_reversal_locked(
                conn, transaction_type=CHARGEBACK_TRANSACTION_TYPE, **posting
            )

        cell = lifecycle.get_cell(conn, cash_leg.cell_id)
        audit.record(
            conn,
            event_type="cell_revenue_reversed",
            cell_id=cash_leg.cell_id,
            metadata={
                "kind": kind.value,
                "amount_minor_units": amount_minor_units,
                "book": payment.book.value,
                "source": source.strip(),
                "note": note,
                "reverses_transaction_id": revenue_transaction_id,
                "remaining_after_minor_units": remaining - amount_minor_units,
                "cell_status": cell.status.value if cell is not None else None,
                "transaction_id": transaction.transaction_id,
            },
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()
    return transaction


def reversible_amount(conn: sqlite3.Connection, revenue_transaction_id: str) -> int:
    """How much of one payment is still there to take back."""
    payment = ledger.get_transaction(conn, revenue_transaction_id)
    if payment is None or payment.transaction_type != REVENUE_TRANSACTION_TYPE:
        raise RevenueError(f"not a revenue payment: {revenue_transaction_id}")
    cash_leg, _ = _legs(payment)
    return _reversible_locked(conn, payment, cash_leg)


def cell_leg(transaction: Transaction) -> Entry:
    """The entry on a Cell's own cash account — where a revenue payment or a
    reversal carries its attribution: the Cell, the experiment, the artifact.
    `payment_fees` reads a charge's attribution from here rather than taking one
    from its caller (ADR-098)."""
    legs = [
        e for e in transaction.entries
        if e.cell_id is not None and e.account_id == cell_cash(e.cell_id)
    ]
    if len(legs) != 1:
        raise RevenueError(f"{transaction.transaction_id} has no single Cell cash leg")
    return legs[0]


def _legs(payment: Transaction) -> tuple[Entry, Entry]:
    """A revenue payment's two entries: the credit to the Cell, and the debit to
    `revenue`. `record_revenue` writes exactly these."""
    cash = [e for e in payment.entries if e.cell_id is not None and e.account_id == cell_cash(e.cell_id)]
    earned = [e for e in payment.entries if e.account_id == REVENUE_ACCOUNT]
    if len(cash) != 1 or len(earned) != 1:  # pragma: no cover - record_revenue's shape
        raise RevenueError(f"{payment.transaction_id} is not shaped like a revenue payment")
    return cash[0], earned[0]


def _reversible_locked(conn: sqlite3.Connection, payment: Transaction, cash_leg: Entry) -> int:
    """The payment less every reversal already posted against it, of either kind.
    Read inside the caller's write lock, so two refunds racing for the last of a
    sale cannot both see it."""
    reversed_so_far = -conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.reverses_transaction_id = ?
          AND e.account_id = ?
        """,
        (payment.transaction_id, cash_leg.account_id),
    ).fetchone()["total"]
    return cash_leg.amount_minor_units - reversed_so_far


def _post_reversal_locked(
    conn: sqlite3.Connection,
    *,
    transaction_type: str,
    payment: Transaction,
    cash_leg: Entry,
    revenue_leg: Entry,
    amount_minor_units: int,
    idempotency_key: str,
    description: str,
) -> Transaction:
    """The payment's entries, mirrored, with every tag copied from them. The
    `revenue` leg keeps its experiment tag so §2.6's report, which reads that
    account, nets the reversal out of the experiment that earned the sale."""
    return ledger._post_transaction_locked(
        conn,
        book=payment.book,
        currency=payment.currency,
        transaction_type=transaction_type,
        idempotency_key=idempotency_key,
        counterparty_hash=payment.counterparty_hash,
        reverses_transaction_id=payment.transaction_id,
        description=description,
        entries=[
            EntrySpec(
                account_id=REVENUE_ACCOUNT,
                amount_minor_units=amount_minor_units,
                experiment_id=revenue_leg.experiment_id,
            ),
            EntrySpec(
                account_id=cash_leg.account_id,
                amount_minor_units=-amount_minor_units,
                cell_id=cash_leg.cell_id,
                experiment_id=cash_leg.experiment_id,
                artifact_id=cash_leg.artifact_id,
            ),
        ],
    )


def _cash_leg_sum(
    conn: sqlite3.Connection,
    cell_id: str,
    book: Book,
    transaction_types: tuple[str, ...],
    since: datetime | None,
) -> int:
    """Signed sum of one Cell's cash legs across the given types. Reads the
    Cell's own entry rather than the `revenue` account, because that account is
    colony-wide — the per-Cell attribution lives on the cell-scoped entry.

    `since` filters `created_at_utc` for the reason `ledger.spend_by_book`
    gives: the effective stamp may be simulated, the window boundary is
    wall-clock. A reversal counts in the window it was *posted* in, not the one
    its payment was — §3.6 records a correction when it happens."""
    window, window_params = (
        ("AND t.created_at_utc > ?", (since.astimezone(timezone.utc).isoformat(),))
        if since is not None
        else ("", ())
    )
    placeholders = ", ".join("?" for _ in transaction_types)
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.book = ?
          AND t.transaction_type IN ({placeholders})
          AND e.account_id = ?
          {window}
        """,
        (book.value, *transaction_types, cell_cash(cell_id), *window_params),
    ).fetchone()
    return row["total"]


def gross_revenue(
    conn: sqlite3.Connection,
    cell_id: str,
    book: Book = Book.USD_REAL,
    *,
    since: datetime | None = None,
) -> int:
    """Every payment a Cell received, before anything was taken back. The
    denominator of §10.2's refund rate — and the wrong figure for anything that
    asks what a Cell earned, which is `net_revenue`."""
    return _cash_leg_sum(conn, cell_id, book, (REVENUE_TRANSACTION_TYPE,), since)


def reversed_revenue(
    conn: sqlite3.Connection,
    cell_id: str,
    book: Book = Book.USD_REAL,
    *,
    since: datetime | None = None,
    kind: ReversalKind | None = None,
) -> int:
    """What refunds and chargebacks took back from a Cell, as a positive number;
    one kind only when `kind` is given (§1.1 subtracts them as separate terms)."""
    types = REVERSAL_TRANSACTION_TYPES if kind is None else (_REVERSAL_TYPE[ReversalKind(kind)],)
    return -_cash_leg_sum(conn, cell_id, book, types, since)


def net_revenue(
    conn: sqlite3.Connection,
    cell_id: str,
    book: Book = Book.USD_REAL,
    *,
    since: datetime | None = None,
) -> int:
    """What a Cell earned and kept: payments less refunds and chargebacks. The
    figure fitness, domination, §25.2's read-back and the Cell's own record read."""
    return gross_revenue(conn, cell_id, book, since=since) - reversed_revenue(
        conn, cell_id, book, since=since
    )


def colony_gross_revenue(conn: sqlite3.Connection, book: Book = Book.USD_REAL) -> int:
    """Every payment the colony received, before reversals, as a positive number."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.book = ? AND t.transaction_type = ? AND e.account_id = ?
        """,
        (book.value, REVENUE_TRANSACTION_TYPE, REVENUE_ACCOUNT),
    ).fetchone()
    return -row["total"]


def colony_net_revenue(conn: sqlite3.Connection, book: Book = Book.USD_REAL) -> int:
    """Colony-wide earnings net of reversals, as a positive number. The `revenue`
    account holds exactly this negated, per the sign convention above — a
    reversal credits it back."""
    return -ledger.get_balance(conn, REVENUE_ACCOUNT, book)
