"""A human decision wakes the Cell it was about (SPEC.md §17.2, §25.2; ADR-057).

§17.2 lists "human decision" among its wake events, and `WAKE_HUMAN_DECISION`
has been defined since the agent loop shipped — emitted by nothing. Every other
reason §17.2 names is earned by a real event; approving or rejecting a proposal
produced an audit record and no wake, so a Cell learned what a person decided
only whenever it next happened to tick.

The reason is **earned, not rotated**. ADR-055 measured what a fabricated wake
reason does: told `tool result available` with no tool result, a Cell proposed
emailing customers about it. So these tests pin both directions — the wake fires
on a real decision, and expiry (where nobody decided) keeps its own reason.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import approval, db, deliberation, ledger, lifecycle, providers
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellStatus, CellType, EntrySpec

GENOME = {"market": "independent bookshops", "workflow": "read, then decide"}


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
            conn, book=book, currency=currency, transaction_type="cell_birth_funding",
            idempotency_key=f"fund:{book.value}", description="fund",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-50_000),
                EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=50_000,
                          cell_id=cell.cell_id),
            ],
        )
    return lifecycle.get_cell(conn, cell.cell_id)


def _propose(conn, cell, *, wake_key="w1", summary="sell a weekly digest"):
    reply = json.dumps({
        "kind": "strategy", "summary": summary, "rationale": "small market",
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


def _wakes(conn):
    return [
        (row["dedupe_key"], json.loads(row["payload_json"])["wake_reason"])
        for row in conn.execute(
            "SELECT dedupe_key, payload_json FROM event_inbox "
            "WHERE event_type = ? ORDER BY rowid", (deliberation.WAKE_EVENT_TYPE,))
    ]


@pytest.mark.parametrize("decide", [approval.approve, approval.reject])
def test_a_decision_wakes_the_cell_it_was_about(conn, decide):
    """Both directions. A rejection is as much a human decision as an approval —
    §25.2 wants the reasons for *promotion or rejection* to reach the Cell, and
    for a rejection this wake is the only thing that makes it timely."""
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    assert _wakes(conn) == [], "nothing should be woken before a person decides"

    decide(conn, request_id=_request_for(conn, result.proposal_id),
           decided_by="operator", reason="a stated reason")

    wakes = _wakes(conn)
    assert len(wakes) == 1
    key, reason = wakes[0]
    assert reason == deliberation.WAKE_HUMAN_DECISION
    assert key.startswith("human-decision:")


def test_the_decision_wake_is_idempotent_on_the_request(conn):
    """Charter C6. Events are delivered at least once and a decision may be
    replayed; the dedupe key is the request, so a redelivery cannot buy the Cell
    a second deliberation."""
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    request_id = _request_for(conn, result.proposal_id)
    approval.approve(conn, request_id=request_id, decided_by="operator", reason="yes")

    request = approval.get_request(conn, request_id)
    approval._wake_on_human_decision_locked(conn, request=request)
    conn.commit()

    assert len(_wakes(conn)) == 1, "the same decision must not wake the Cell twice"


def test_an_expiry_is_not_a_human_decision(conn):
    """The line `_decision_note` refuses to blur, held here too: the review
    window closing is not a judgement. Collapsing the two would tell a Cell a
    person decided when nobody looked — the §0.3 mirror ADR-055 named, where the
    kernel asserts to a Cell something that is not so."""
    cell = _make_cell(conn)
    _propose(conn, cell)
    approval.expire_due(conn, now=datetime.now(timezone.utc) + timedelta(days=365))

    reasons = {reason for _, reason in _wakes(conn)}
    assert deliberation.WAKE_HUMAN_DECISION not in reasons
    assert approval.WAKE_APPROVAL_EXPIRED in reasons


def test_a_dead_cell_is_not_woken_by_a_decision_about_it(conn):
    """A dead Cell may not deliberate (Charter C8), and `deliberate` records a
    refusal rather than raising — so waking one would turn every decision about
    a dead Cell into a deliberation row saying it could not think."""
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    request_id = _request_for(conn, result.proposal_id)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    approval.approve(conn, request_id=request_id, decided_by="operator", reason="yes")

    assert deliberation.WAKE_HUMAN_DECISION not in {r for _, r in _wakes(conn)}


def test_every_wake_reason_the_spec_names_now_has_a_producer(conn):
    """§17.2's list is a contract, and `WAKE_HUMAN_DECISION` was the one entry
    nothing produced. Structural rather than behavioural: a reason defined and
    never emitted is a socket, and this is the check that says which are filled.

    If a new reason is added to `deliberation`, either wire it to the event that
    justifies it or add it here deliberately with a note saying why it is inert.
    """
    import inspect

    from mitosis import auditor, external_actions, promotion, tools

    producers = "\n".join(
        inspect.getsource(module)
        for module in (approval, auditor, external_actions, promotion, tools)
    )
    named = [
        name for name in dir(deliberation)
        if name.startswith("WAKE_") and name != "WAKE_EVENT_TYPE"
    ]
    unproduced = [
        name for name in named
        if name not in producers and getattr(deliberation, name) not in producers
    ]
    # `WAKE_SCHEDULED_RESEARCH` is produced by the scheduler's tick, which is
    # honest: a scheduled tick *is* a scheduled research cycle.
    assert unproduced == ["WAKE_SCHEDULED_RESEARCH"], (
        f"wake reasons defined but emitted by no real event: {unproduced}"
    )
