"""§15.1's recent-proposals log shows a summary only once a person judged it
(SPEC.md §14.2, §15.1, §15.2, §23.4; ADR-046, ADR-051, ADR-052).

The section was measured as the cause of the colony's self-repetition: a Cell
shown its own recent wording proposes it again, scoring ~1.05 effective distinct
ideas per run of 8 wakes against ~1.94 with the section removed. Under §14.2
counterfactual twins the only edit that recovered the gain was **removing the
summary** — naming the expectation in the heading measured at zero.

The summary cannot be removed unconditionally, because ADR-046's `STRATEGY`
mechanism is delivered entirely as prose in this section: approving a strategy
*is* the act, and "APPROVED" tells a Cell nothing if it cannot see what was
approved. So the line is drawn at whether a person actually decided.

These defend both halves. Break either and the failure is silent in production —
what this section delivers is text in a prompt, so nothing else notices.
"""

from __future__ import annotations

import json

import pytest

from mitosis import (
    approval,
    context,
    db,
    deliberation,
    ledger,
    lifecycle,
    providers,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType, EntrySpec

GENOME = {"market": "independent bookshops", "workflow": "read, then decide"}
SUMMARY = "sell a weekly stock digest to independent bookshops"


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


def _make_cell(conn):
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key="a", genome_content=GENOME,
    )
    conn.commit()
    for book, currency in (
        (Book.USD_REAL, "USD"), (Book.RESOURCE, "RESOURCE"), (Book.USD_SIM, "USD"),
    ):
        ledger.post_transaction(
            conn, book=book, currency=currency,
            transaction_type="cell_birth_funding",
            idempotency_key=f"fund:{cell.cell_id}:{book.value}", description="fund",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-50_000),
                EntrySpec(
                    account_id=cell_cash(cell.cell_id), amount_minor_units=50_000,
                    cell_id=cell.cell_id,
                ),
            ],
        )
    return lifecycle.get_cell(conn, cell.cell_id)


def _propose(conn, cell, *, wake_key="w1", summary=SUMMARY):
    reply = json.dumps({
        "kind": "strategy", "summary": summary,
        "rationale": "the market is small enough to reach by hand",
        "risk_tier": "LOW", "estimated_cost_minor_units": 0, "predictions": [],
    })
    return deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=providers.MockProvider(reply=reply),
        wake_key=wake_key, model="mock-1", proposal_sink=approval.QueueSink(),
    )


def _request_for(conn, proposal_id):
    return conn.execute(
        "SELECT request_id FROM approval_requests WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()["request_id"]


def _proposal_log(conn, cell) -> str | None:
    assembled = context.assemble(
        conn, cell=lifecycle.get_cell(conn, cell.cell_id), canonical_genome=GENOME,
        wake_reason="scheduled research cycle", budget_tokens=8_000,
    )
    for section in assembled.sections:
        if section.name.startswith("Your recent proposals"):
            return section.body
    return None


def test_an_undecided_proposal_shows_no_summary_to_copy(conn):
    """The anchoring fix (ADR-051, ADR-052). A pending proposal is the case that
    dominates a real colony — across the 12 control runs that measured this, all
    52 proposals were `pending`, because an unattended colony queues and nobody
    reviews. That is precisely the text a Cell was copying, and it carries no
    decision, so withholding it costs nothing.

    If this fails, the colony's effective distinct ideas per run of 8 wakes drops
    from ~1.85 back to ~1.09 and no other test notices.
    """
    cell = _make_cell(conn)
    _propose(conn, cell)

    body = _proposal_log(conn, cell)
    assert body is not None, "the section must still render — ADR-046 needs it"
    assert SUMMARY not in body, "an undecided proposal must not show its wording"
    assert "[strategy]" in body, "the kind is still shown"
    assert "waiting on a person" in body, "the decision note is still shown"


@pytest.mark.parametrize(
    "decide, expected",
    [(approval.approve, "APPROVED"), (approval.reject, "REJECTED")],
)
def test_a_decided_proposal_shows_no_summary_either(conn, decide, expected):
    """ADR-053. ADR-052 kept the summary once a person had judged the proposal,
    reasoning that "APPROVED" is meaningless if the Cell cannot tell what was
    approved. Measured, that branch anchors exactly as hard as the pending one
    (1.122 shown vs 1.764 hidden, approvals held constant) — **a decision
    annotation is not a modifier on the text beside it.**

    The decision itself still reaches the Cell, and for an approved proposal so
    does the substance, through the channel that kind actually uses.
    """
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    decide(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="a stated reason",
    )

    body = _proposal_log(conn, cell)
    assert SUMMARY not in body, "a judged proposal must not show its wording either"
    assert expected in body, "the decision still reaches the Cell"
    assert "a stated reason" in body, "and so does the operator's reason"


def test_an_approved_strategy_still_reaches_the_cell_in_full(conn):
    """The half ADR-052 was right to protect, delivered by the section that was
    always doing it. ADR-046's `STRATEGY` mechanism does **not** run through the
    proposal log — `Your standing strategy` is its own channel — which is why
    hiding the summary here costs it nothing.

    This is the test that would fail if someone removed the standing-strategy
    section believing the proposal log covered it.
    """
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    approval.approve(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="agreed",
    )

    assembled = context.assemble(
        conn, cell=lifecycle.get_cell(conn, cell.cell_id), canonical_genome=GENOME,
        wake_reason="scheduled research cycle", budget_tokens=8_000,
    )
    carriers = [s.name for s in assembled.sections if SUMMARY in s.body]
    assert carriers, "an approved strategy must still reach the Cell somewhere"
    assert any(n.startswith("Your standing strategy") for n in carriers)
    assert not any(n.startswith("Your recent proposals") for n in carriers)


def test_a_rejected_proposal_loses_its_subject_and_that_is_recorded(conn):
    """**The known cost of ADR-053, pinned so it cannot become a surprise.**

    A rejection has no grant to consume and no standing-strategy delivery, so
    with the summary hidden the Cell learns *that* something was rejected and
    *why*, but not *what*. Every other kind keeps a channel; this one does not.

    Asserted rather than fixed because the alternative — showing rejected
    summaries — reintroduces the anchoring ADR-053 measured, and choosing
    between them is a §23.4 question that deserves its own measurement. If that
    argument is ever had, this test is where the current answer is written down.
    """
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    approval.reject(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="too expensive for now",
    )

    assembled = context.assemble(
        conn, cell=lifecycle.get_cell(conn, cell.cell_id), canonical_genome=GENOME,
        wake_reason="scheduled research cycle", budget_tokens=8_000,
    )
    assert not any(SUMMARY in s.body for s in assembled.sections), (
        "if a channel for rejected content ever appears, this cost is gone and "
        "this test should be deleted deliberately"
    )
    log = _proposal_log(conn, cell)
    assert "REJECTED" in log and "too expensive for now" in log


def test_no_status_shows_a_summary(conn):
    """Structural: the rule is unconditional, so no status may reintroduce the
    wording. Guards the shape ADR-052 shipped and ADR-053 removed — a
    status-conditional branch — from being reintroduced by a later edit.
    """
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    request_id = _request_for(conn, result.proposal_id)
    for status in ("pending", "expired", "approved", "rejected"):
        conn.execute(
            "UPDATE approval_requests SET status = ? WHERE request_id = ?",
            (status, request_id),
        )
        conn.commit()
        body = _proposal_log(conn, cell)
        assert SUMMARY not in body, f"status {status!r} leaked the summary back"
        assert "[strategy]" in body
