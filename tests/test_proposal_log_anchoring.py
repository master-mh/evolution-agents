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
def test_a_decided_proposal_keeps_its_summary(conn, decide, expected):
    """ADR-046, preserved. A `STRATEGY` has no consumer and no regeneration —
    approving it *is* the act, and this section is the only channel by which the
    act reaches the Cell. "APPROVED" against an unnamed proposal tells it nothing.

    Rejection matters for the same reason from the other side: §23.4's
    `repeat_after_rejection` detector is only meaningful if the Cell was told
    what was rejected.
    """
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    decide(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="a stated reason",
    )

    body = _proposal_log(conn, cell)
    assert SUMMARY in body, f"a {expected.lower()} proposal must name what was decided"
    assert expected in body


def test_an_expired_proposal_is_not_treated_as_decided(conn):
    """`_decision_note` keeps "not yet reviewed" and "expired unreviewed"
    distinct because "collapsing them would tell a Cell it was judged when
    nobody judged it". The summary gate is drawn on the same line: the review
    window closing is not a judgement, so an expired proposal shows no summary.

    Getting this wrong would leak the anchoring text back in through the one
    status that looks decided and is not.
    """
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    conn.execute(
        "UPDATE approval_requests SET status = 'expired' WHERE request_id = ?",
        (_request_for(conn, result.proposal_id),),
    )
    conn.commit()

    body = _proposal_log(conn, cell)
    assert SUMMARY not in body
    assert "review window closed" in body


def test_the_gate_is_derived_from_the_decision_note_not_a_second_list(conn):
    """A structural guarantee, not a behavioural one. `_was_decided` and
    `_decision_note` must agree about which statuses are a judgement; two
    separate lists would drift, and the drift would be invisible because both
    render into prose.

    Checked by exercising every status the note handles and asserting the gate
    agrees with whether the note reports a verdict.
    """
    for status, note_has_verdict in (
        (None, False), ("pending", False), ("expired", False),
        ("approved", True), ("rejected", True),
    ):
        row = {"status": status, "decision_reason": None}
        note = context._decision_note(row)
        says_verdict = "APPROVED" in note or "REJECTED" in note
        assert says_verdict == note_has_verdict, f"note changed for {status}"
        assert context._was_decided(row) == says_verdict, (
            f"_was_decided disagrees with _decision_note for status {status!r}"
        )
