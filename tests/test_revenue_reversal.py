"""Refunds and chargebacks (SPEC.md §1.1, §2.2, §10.2, §16.3, §3.4; §28 Phase 9;
ADR-097).

§1.1 subtracts refunds and chargebacks from real settled net profit, and until
migration 0037 nothing could record either: a refunded Cell kept its full
apparent earnings, and every reader of revenue — §10.5's domination, §25.2's
read-back, the Cell's own record, the simulator's fitness — overstated it. These
tests defend the three rules a reversal lives by (it lands on the Cell that made
the sale, it never takes back more than the sale, and every reader of revenue
sees it) and the ledger properties the new column must not disturb.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import pathlib
import re
import sqlite3
from datetime import datetime, timezone

import pytest

from mitosis import (
    context,
    death,
    experiments,
    ledger,
    lifecycle,
    real_spend_breaker,
    revenue,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType, EntrySpec
from mitosis.simulation import candidate

SRC = pathlib.Path(revenue.__file__).parent
MIGRATION = SRC / "migrations" / "0037_revenue_reversal.sql"


@pytest.fixture()
def cell(conn):
    real_spend_breaker.configure_if_absent(conn)
    return _cell(conn, "seller")


def _cell(conn, key, *, book=Book.USD_REAL):
    return lifecycle.create_cell(
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=1_000,
        book=book,
        idempotency_key=f"reversal-cell:{key}",
    )


def _sale(conn, cell, amount=500, *, source="inv-1", **kwargs):
    return revenue.record_revenue(
        conn,
        cell_id=cell.cell_id,
        amount_minor_units=amount,
        source=source,
        book=cell.book,
        **kwargs,
    )


def _refund(conn, sale, amount, *, source="refund-1", **kwargs):
    return revenue.record_reversal(
        conn,
        revenue_transaction_id=sale.transaction_id,
        amount_minor_units=amount,
        source=source,
        **kwargs,
    )


def _cash(conn, cell):
    return ledger.get_balance(conn, cell_cash(cell.cell_id), cell.book)


def _transaction_count(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM ledger_transactions").fetchone()["n"]


# --- the posting -------------------------------------------------------------


def test_a_refund_takes_money_back_from_the_cell_and_returns_it_to_revenue(conn, cell):
    sale = _sale(conn, cell, 500)
    cash = _cash(conn, cell)

    refund = _refund(conn, sale, 200)

    assert refund.transaction_type == revenue.REFUND_TRANSACTION_TYPE
    assert refund.reverses_transaction_id == sale.transaction_id
    assert _cash(conn, cell) == cash - 200
    assert ledger.get_balance(conn, revenue.REVENUE_ACCOUNT, Book.USD_REAL) == -300
    assert revenue.gross_revenue(conn, cell.cell_id) == 500
    assert revenue.reversed_revenue(conn, cell.cell_id) == 200
    assert revenue.net_revenue(conn, cell.cell_id) == 300
    assert revenue.colony_gross_revenue(conn) == 500
    assert revenue.colony_net_revenue(conn) == 300
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_chain(conn)


def test_refunds_and_chargebacks_are_separate_terms(conn, cell):
    """§1.1 subtracts "refunds - chargebacks" as two terms and §10.2 asks for
    their rate, so a report must be able to tell them apart. Both reduce net
    revenue; each is counted under its own kind."""
    sale = _sale(conn, cell, 500)
    _refund(conn, sale, 100, source="refund-1")
    chargeback = _refund(
        conn, sale, 150, source="dispute-1", kind=revenue.ReversalKind.CHARGEBACK
    )

    assert chargeback.transaction_type == revenue.CHARGEBACK_TRANSACTION_TYPE
    assert revenue.reversed_revenue(conn, cell.cell_id, kind=revenue.ReversalKind.REFUND) == 100
    assert (
        revenue.reversed_revenue(conn, cell.cell_id, kind=revenue.ReversalKind.CHARGEBACK) == 150
    )
    assert revenue.net_revenue(conn, cell.cell_id) == 250


def test_a_reversal_is_audited_with_the_payment_it_names(conn, cell):
    sale = _sale(conn, cell, 500)
    _refund(conn, sale, 120, note="customer changed their mind")

    row = conn.execute(
        "SELECT cell_id, metadata_json FROM audit_events "
        "WHERE event_type = 'cell_revenue_reversed'"
    ).fetchone()
    assert row["cell_id"] == cell.cell_id
    assert sale.transaction_id in row["metadata_json"]
    assert '"remaining_after_minor_units":380' in row["metadata_json"]
    assert '"kind":"refund"' in row["metadata_json"]


# --- rule 1: it lands on the Cell that made the sale (§16.3) ------------------


def test_record_reversal_offers_no_way_to_name_a_cell(conn):
    """§16.3: revenue-producing assets "cannot transfer without their related
    refund liabilities", and §16.4 names the failure — reproducing "to escape
    liabilities while keeping profitable assets". A reversal that took a
    `cell_id` could land a sale's refund on a sibling that never made it. The
    guarantee is that no such parameter exists, so it is asserted on the
    signature rather than on any one call."""
    parameters = set(inspect.signature(revenue.record_reversal).parameters)
    forbidden = {
        "cell_id",
        "book",
        "experiment_id",
        "artifact_id",
        "counterparty",
        "counterparty_hash",
        "account_id",
    }
    assert not parameters & forbidden, f"record_reversal can be pointed at {parameters & forbidden}"


def test_a_reversal_inherits_its_cell_book_experiment_and_buyer_from_the_payment(conn):
    seller = _cell(conn, "sim-seller", book=Book.USD_SIM)
    experiment = experiments.start(conn, cell_id=seller.cell_id, hypothesis="refunds net out")
    sale = _sale(
        conn,
        seller,
        400,
        experiment_id=experiment.experiment_id,
        counterparty="buyer@example.test",
    )

    refund = _refund(conn, sale, 100)

    assert refund.book is Book.USD_SIM
    assert refund.counterparty_hash == sale.counterparty_hash is not None
    by_account = {e.account_id: e for e in refund.entries}
    cash_leg = by_account[cell_cash(seller.cell_id)]
    assert cash_leg.cell_id == seller.cell_id
    assert cash_leg.amount_minor_units == -100
    assert cash_leg.experiment_id == experiment.experiment_id
    assert by_account[revenue.REVENUE_ACCOUNT].experiment_id == experiment.experiment_id


def test_a_sibling_is_untouched_by_a_refund_of_a_sale_it_did_not_make(conn, cell):
    sibling = _cell(conn, "sibling")
    sibling_cash = _cash(conn, sibling)
    sale = _sale(conn, cell, 500)

    _refund(conn, sale, 500)

    assert _cash(conn, sibling) == sibling_cash
    assert revenue.net_revenue(conn, sibling.cell_id) == 0
    assert revenue.net_revenue(conn, cell.cell_id) == 0


# --- rule 2: never more than the sale ----------------------------------------


def test_reversals_of_one_payment_never_exceed_it(conn, cell):
    """Money handed back beyond a sale is not a refund of it. Refunds and
    chargebacks share one bound — a sale refunded in full and then charged back
    would otherwise take the money back twice."""
    sale = _sale(conn, cell, 500)
    _refund(conn, sale, 300, source="refund-1")

    before = _transaction_count(conn)
    with pytest.raises(revenue.RevenueError, match="200 of its 500 is left"):
        _refund(conn, sale, 201, source="refund-2")
    assert _transaction_count(conn) == before

    _refund(conn, sale, 200, source="dispute-1", kind=revenue.ReversalKind.CHARGEBACK)
    with pytest.raises(revenue.RevenueError, match="0 of its 500 is left"):
        _refund(conn, sale, 1, source="refund-3")

    assert revenue.reversible_amount(conn, sale.transaction_id) == 0
    assert revenue.net_revenue(conn, cell.cell_id) == 0


def test_the_bound_is_the_payment_not_the_cells_total(conn, cell):
    """A Cell with two sales has 1000 of gross revenue, and a reversal of the
    first may still take back only 500. A bound computed per Cell passes the
    single-sale test above and fails here."""
    first = _sale(conn, cell, 500, source="inv-1")
    _sale(conn, cell, 500, source="inv-2")

    _refund(conn, first, 500, source="refund-1")
    with pytest.raises(revenue.RevenueError, match="0 of its 500 is left"):
        _refund(conn, first, 1, source="refund-2")
    assert revenue.net_revenue(conn, cell.cell_id) == 500


@pytest.mark.parametrize("amount", [0, -1])
def test_a_reversal_must_be_positive(conn, cell, amount):
    sale = _sale(conn, cell, 500)
    with pytest.raises(revenue.RevenueError, match="must be positive"):
        _refund(conn, sale, amount)


def test_a_reversal_requires_a_reference(conn, cell):
    sale = _sale(conn, cell, 500)
    for blank in ("", "   "):
        with pytest.raises(revenue.RevenueError, match="source is required"):
            _refund(conn, sale, 10, source=blank)


def test_only_a_revenue_payment_can_be_reversed(conn, cell):
    sale = _sale(conn, cell, 500)
    refund = _refund(conn, sale, 100)
    funding = conn.execute(
        "SELECT transaction_id FROM ledger_transactions WHERE transaction_type NOT IN (?, ?) "
        "LIMIT 1",
        (revenue.REVENUE_TRANSACTION_TYPE, revenue.REFUND_TRANSACTION_TYPE),
    ).fetchone()["transaction_id"]

    with pytest.raises(revenue.RevenueError, match="no such transaction"):
        revenue.record_reversal(
            conn, revenue_transaction_id="nope", amount_minor_units=1, source="x"
        )
    for not_revenue in (funding, refund.transaction_id):
        with pytest.raises(revenue.RevenueError, match="only a revenue payment can be reversed"):
            revenue.record_reversal(
                conn, revenue_transaction_id=not_revenue, amount_minor_units=1, source="x"
            )


# --- idempotency -------------------------------------------------------------


def test_the_same_reversal_recorded_twice_posts_once(conn, cell):
    sale = _sale(conn, cell, 500)
    first = _refund(conn, sale, 200, source="refund-1")
    second = _refund(conn, sale, 200, source="refund-1")

    assert first.transaction_id == second.transaction_id
    assert revenue.net_revenue(conn, cell.cell_id) == 300


def test_retrying_a_full_refund_returns_it_instead_of_refusing(conn, cell):
    """The replay is recognised before the bound is checked. The other order
    makes a retried full refund fail as "exceeding" the sale it already
    reversed, which turns an at-least-once retry into an operator error."""
    sale = _sale(conn, cell, 500)
    first = _refund(conn, sale, 500, source="refund-1")
    assert _refund(conn, sale, 500, source="refund-1").transaction_id == first.transaction_id


def test_a_key_already_used_for_a_different_reversal_is_refused(conn, cell):
    first = _sale(conn, cell, 500, source="inv-1")
    other = _sale(conn, cell, 500, source="inv-2")
    _refund(conn, first, 100, idempotency_key="shared-key")

    with pytest.raises(revenue.RevenueError, match="already belongs"):
        _refund(conn, other, 100, idempotency_key="shared-key")
    with pytest.raises(revenue.RevenueError, match="already belongs"):
        _refund(conn, first, 100, idempotency_key="shared-key", kind=revenue.ReversalKind.CHARGEBACK)


# --- rule 3: a dead Cell carries its refunds ----------------------------------


def test_a_dead_cell_is_refunded_and_the_debt_stays_on_its_account(conn, cell):
    """Payment outlives the worker, and so does a refund. The estate has already
    returned the Cell's cash to the treasury; the refund is not quietly taken
    from the treasury instead. The shortfall stays visible on the dead Cell,
    `lifecycle._reclaim_locked`'s rule for a negative balance (ADR-021)."""
    sale = _sale(conn, cell, 500)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")
    assert _cash(conn, cell) == 0
    treasury = ledger.get_balance(conn, "colony_treasury", Book.USD_REAL)

    _refund(conn, sale, 200)

    assert _cash(conn, cell) == -200
    assert ledger.get_balance(conn, "colony_treasury", Book.USD_REAL) == treasury
    event = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'cell_revenue_reversed'"
    ).fetchone()
    assert '"cell_status":"dead"' in event["metadata_json"]


# --- not spend ---------------------------------------------------------------


def test_a_reversal_is_neither_consumption_nor_real_spend(conn, cell):
    """`accounts.py` calls a posting to `revenue` "un-earning, not spending".
    Counted as consumption, a refunded Cell would look wasteful to §10.5; counted
    by the breaker, refunds would fill caps that exist for spending."""
    sale = _sale(conn, cell, 500)
    now = datetime.now(timezone.utc)
    spend_before = ledger.spend_by_book(conn, cell.cell_id)

    _refund(conn, sale, 400)

    assert ledger.spend_by_book(conn, cell.cell_id) == spend_before
    snapshot = real_spend_breaker.snapshot(conn, now=now)
    assert snapshot.spend_last_hour_minor_units == 0
    assert snapshot.spend_last_month_minor_units == 0


# --- every reader of revenue sees it ----------------------------------------


def test_domination_reads_revenue_net_of_reversals(conn, cell):
    """§10.5's near-duplicate domination compares net contribution. On gross, a
    Cell whose every sale was refunded would dominate a peer on money it no
    longer has."""
    sale = _sale(conn, cell, 500)
    _refund(conn, sale, 500)

    record = death.contribution(conn, cell)
    assert record.revenue_minor_units == 0
    assert record.net_contribution == -record.spend_minor_units


def test_the_cells_own_record_names_each_reversal_kind(conn, cell):
    """A Cell shown only a smaller number cannot tell a refund from a sale that
    never happened, so the reversal is named — and **each kind is named on its
    own line**. §1.1 subtracts refunds and chargebacks as separate terms and
    §10.2 asks for their rates separately; the earlier combined wording
    ("refunded or charged back") led a live model to report this Cell's refund as
    a chargeback in its own rationale. A Cell with neither reads exactly as it did
    before ADR-097: the lines are absent, not zero."""
    untouched = _cell(conn, "untouched")
    _sale(conn, untouched, 100, source="inv-u")
    sale = _sale(conn, cell, 500)
    _refund(conn, sale, 200)

    body = context._realised_record_section(conn, cell).body
    assert "revenue earned to date: 300 minor units" in body
    assert "refunded to customers (already subtracted above): 200 minor units" in body
    assert "charged back" not in body, (
        "nothing was charged back — naming a kind that did not happen is the "
        "conflation this wording exists to prevent"
    )

    _refund(conn, sale, 50, source="dispute-1", kind=revenue.ReversalKind.CHARGEBACK)
    both = context._realised_record_section(conn, cell).body
    assert "revenue earned to date: 250 minor units" in both
    assert "refunded to customers (already subtracted above): 200 minor units" in both
    assert "charged back by a payer's bank (already subtracted above): 50 minor units" in both

    plain = context._realised_record_section(conn, untouched).body
    assert "revenue earned to date: 100 minor units" in plain
    assert "refunded" not in plain and "charged back" not in plain


def test_an_experiment_report_nets_a_refund_out_of_the_experiment_that_sold(conn):
    """§2.6's report reads the `revenue` account by experiment tag, so the
    reversal must carry the payment's tag on that leg — an untagged credit
    would leave the experiment's revenue gross while the colony's went net."""
    seller = _cell(conn, "report-seller", book=Book.USD_SIM)
    experiment = experiments.start(conn, cell_id=seller.cell_id, hypothesis="refunds net out")
    sale = _sale(conn, seller, 40, experiment_id=experiment.experiment_id)

    _refund(conn, sale, 15)

    report = experiments.report(conn, experiment.experiment_id)
    assert report.synthetic_revenue_minor_units == 25
    assert report.synthetic_net_profit_minor_units == 25


def test_the_simulators_revenue_axis_reads_net(conn):
    seller = _cell(conn, "sim-axis", book=Book.USD_SIM)
    experiment = experiments.start(conn, cell_id=seller.cell_id, hypothesis="axis")
    sale = _sale(conn, seller, 700, experiment_id=experiment.experiment_id)
    experiments.conclude(
        conn, experiment_id=experiment.experiment_id, concluded_by="test", note="done"
    )

    _refund(conn, sale, 300)

    axis = candidate._realized_net_revenue(conn, seller.cell_id)
    assert axis.value == pytest.approx(400.0)


_GROSS_READERS = {
    "cli.py": (
        "cell-fitness prints what was received beside what was taken back, and only "
        "beside the net figure domination reads — never instead of it"
    ),
    "profit.py": (
        "§1.1's first term *is* settled revenue before deductions: the formula subtracts "
        "refunds and chargebacks itself, on their own lines, so a reader can check the "
        "subtraction. Using net here would deduct them twice (ADR-099)"
    ),
}


def test_nothing_reads_gross_revenue_where_net_is_meant():
    """`total_revenue` meant gross, and every reader wanted net — which is how a
    refund would have been invisible to all of them. The name is gone, and a
    module that reaches for gross must be listed here with its reason, so the
    next reader of revenue chooses rather than inherits."""
    assert not hasattr(revenue, "total_revenue")
    assert not hasattr(revenue, "colony_revenue")
    gross = {"gross_revenue", "colony_gross_revenue"}
    readers: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "revenue.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            name = (
                node.attr
                if isinstance(node, ast.Attribute)
                else node.id
                if isinstance(node, ast.Name)
                else None
            )
            if name in gross:
                readers.setdefault(path.relative_to(SRC).as_posix(), set()).add(name)
    unlisted = set(readers) - set(_GROSS_READERS)
    assert not unlisted, f"reads gross revenue without a stated reason: {sorted(unlisted)}"
    assert not set(_GROSS_READERS) - set(readers), "stale entry in _GROSS_READERS"


# --- the schema makes both mistakes unrepresentable (migration 0037) ---------


def _post(conn, *, transaction_type, key, reverses=None, cell):
    return ledger.post_transaction(
        conn,
        book=Book.USD_REAL,
        currency="USD",
        transaction_type=transaction_type,
        idempotency_key=key,
        reverses_transaction_id=reverses,
        entries=[
            EntrySpec(account_id=revenue.REVENUE_ACCOUNT, amount_minor_units=1),
            EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=-1, cell_id=cell.cell_id),
        ],
    )


def test_the_schema_refuses_a_reversal_that_names_no_payment(conn, cell):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _post(conn, transaction_type=revenue.REFUND_TRANSACTION_TYPE, key="bare", cell=cell)


def test_the_schema_refuses_a_link_on_any_other_type(conn, cell):
    sale = _sale(conn, cell, 500)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _post(
            conn, transaction_type="test_adjustment", key="linked", reverses=sale.transaction_id,
            cell=cell,
        )


def test_the_schema_refuses_a_link_to_a_transaction_that_does_not_exist(conn, cell):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        _post(
            conn, transaction_type=revenue.CHARGEBACK_TRANSACTION_TYPE, key="dangling",
            reverses="no-such-transaction", cell=cell,
        )


def test_the_reversal_types_are_the_ones_the_schema_names():
    named = re.search(r"transaction_type IN \(([^)]*)\)", MIGRATION.read_text()).group(1)
    assert {t.strip().strip("'") for t in named.split(",")} == set(revenue.REVERSAL_TRANSACTION_TYPES)


# --- §3.4: the link is chained, and no existing hash moved -------------------


def test_the_payment_a_reversal_names_is_covered_by_the_hash_chain(conn, cell):
    """Which sale a refund undoes decides how much revenue survives, so the link
    must not be editable unseen — migration 0028's reason for putting a
    fitness-bearing fact on the transaction rather than beside it."""
    first = _sale(conn, cell, 500, source="inv-1")
    other = _sale(conn, cell, 500, source="inv-2")
    refund = _refund(conn, first, 100)
    assert ledger.verify_chain(conn)

    conn.execute(
        "UPDATE ledger_transactions SET reverses_transaction_id = ? WHERE transaction_id = ?",
        (other.transaction_id, refund.transaction_id),
    )
    assert not ledger.verify_chain(conn)


def test_a_transaction_that_reverses_nothing_hashes_as_it_always_did(conn, cell):
    """The pre-0037 formula, recomputed by hand (§3.4). A `null` key in every
    preimage would change the hash of every transaction ever written and make
    `verify_chain` report every existing colony as tampered with."""
    sale = _sale(conn, cell, 500)
    row = conn.execute(
        "SELECT * FROM ledger_transactions WHERE transaction_id = ?", (sale.transaction_id,)
    ).fetchone()
    entries = conn.execute(
        "SELECT * FROM ledger_entries WHERE transaction_id = ? ORDER BY rowid",
        (row["transaction_id"],),
    ).fetchall()
    canonical = {
        key: row[key]
        for key in (
            "transaction_id", "book", "currency", "created_at_utc", "effective_at_utc",
            "idempotency_key", "event_id", "transaction_type", "description",
            "previous_transaction_hash",
        )
    }
    canonical["entries"] = [
        {
            key: e[key]
            for key in (
                "entry_id", "account_id", "amount_minor_units", "cell_id", "team_id",
                "experiment_id", "artifact_id",
            )
        }
        for e in entries
    ]
    pre_0037 = hashlib.sha256(ledger._canonical_json(canonical).encode("utf-8")).hexdigest()
    assert row["reverses_transaction_id"] is None and row["counterparty_hash"] is None
    assert pre_0037 == row["transaction_hash"]
