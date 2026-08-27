"""The strategy kind: approving it *is* the act (SPEC.md §0.2, §15.1, §23.3,
§23.4, §23.5; ADR-046).

`ProposalKind.STRATEGY` had no consumer, and unlike the other four kinds that is
the right answer rather than an unfinished corner — a strategy names nothing to
do. What was missing was the consequence: an approved strategy reached the Cell
nowhere, and the inert grant beside it lapsed and woke the Cell to re-propose
something a person had already agreed to.

These defend the decision and both halves of the feedback it turns on.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mitosis import (
    approval,
    context,
    db,
    deliberation,
    ledger,
    lifecycle,
    proposal as proposal_module,
    providers,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType, EntrySpec

GENOME = {"market": "independent bookshops", "workflow": "read, then decide"}
STRATEGY = "focus on independent bookshops and sell a weekly stock digest"


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


def _reply(**overrides) -> str:
    payload = {
        "kind": "strategy",
        "summary": STRATEGY,
        "rationale": "the market is small enough to reach by hand and nobody serves it",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 0,
        "predictions": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _make_cell(conn, *, key: str = "a"):
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key=key, genome_content=GENOME,
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


def _propose(conn, cell, *, wake_key: str = "w1", queued: bool = True, **overrides):
    return deliberation.deliberate(
        conn, cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=_reply(**overrides)),
        wake_key=wake_key, model="mock-1",
        proposal_sink=approval.QueueSink() if queued else None,
    )


def _request_for(conn, proposal_id: str):
    return conn.execute(
        "SELECT request_id FROM approval_requests WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()["request_id"]


def _sections(conn, cell) -> dict[str, str]:
    assembled = context.assemble(
        conn, cell=lifecycle.get_cell(conn, cell.cell_id), canonical_genome=GENOME,
        wake_reason="scheduled research cycle", budget_tokens=8_000,
    )
    return {s.name: s.body for s in assembled.sections}


def _standing(conn, cell) -> str | None:
    for name, body in _sections(conn, cell).items():
        if name.startswith("Your standing strategy"):
            return body
    return None


def _proposal_log(conn, cell) -> str | None:
    for name, body in _sections(conn, cell).items():
        if name.startswith("Your recent proposals"):
            return body
    return None


# --- the decision: no consumer, on purpose ------------------------------------


def test_a_strategy_has_no_consumer_and_the_kernel_says_so(conn):
    """ADR-046's decision, made structural.

    Every other queued kind has a module that consumes its grant —
    `promotion`, `tools`, `external_actions`, `experiment_grants`. A strategy
    names nothing to do, so approving one *is* the act, and
    `proposal.STATEMENT_KINDS` is where that is written down rather than left as
    the absence that made this kind look unfinished for four months.

    If a consumer is ever added, delete this test deliberately and argue it —
    the same friction `test_only_the_promotion_module_consumes_a_grant` creates.
    """
    assert proposal_module.ProposalKind.STRATEGY in proposal_module.STATEMENT_KINDS
    # ABSTAIN is a statement too but is never queued, so a rule about it would
    # govern a state that cannot occur.
    assert proposal_module.ProposalKind.ABSTAIN not in proposal_module.STATEMENT_KINDS
    for kind in proposal_module.ProposalKind:
        if kind in {
            proposal_module.ProposalKind.STRATEGY,
            proposal_module.ProposalKind.ABSTAIN,
        }:
            continue
        assert kind not in proposal_module.STATEMENT_KINDS, (
            f"{kind.value} has a consumer; a statement is a kind that asks for nothing"
        )


def test_the_standing_strategy_is_derived_and_stored_nowhere(conn):
    """§2.5's habit, applied outside the ledger.

    A `cell_strategies` table is the obvious design and would give a Cell a
    column to write its approach into — a second answer that can drift from what
    the queue actually approved. The derivation reads the queue, so the two
    cannot disagree.
    """
    tables = {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert not {t for t in tables if "strateg" in t.lower()}
    cell_columns = {r["name"] for r in conn.execute("PRAGMA table_info(cells)")}
    assert not {c for c in cell_columns if "strateg" in c.lower()}


# --- an approved strategy becomes standing context ----------------------------


def test_an_approved_strategy_becomes_the_cells_standing_strategy(conn):
    """§15.1's "relevant epigenetic state" — the one context source that clause
    names which nothing implemented. Before this, a Cell proposed a strategy, a
    person agreed, and the Cell was never told."""
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    assert _standing(conn, cell) is None

    approval.approve(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="agreed — that market fits your genome",
    )

    body = _standing(conn, cell)
    assert body is not None
    assert STRATEGY in body


def test_the_operators_reason_reaches_the_cell(conn):
    """The only human-authored text a Cell ever receives, and the most direct
    steering the design offers. It is trusted in the sense §19.4 cares about:
    it did not come from outside the colony."""
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    approval.approve(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="yes, but stay off paid advertising",
    )

    assert "stay off paid advertising" in _standing(conn, cell)


def test_a_later_approved_strategy_supersedes_an_earlier_one(conn):
    """Singular, the way §15.1's "current experiment" is. A Cell shown two
    standing strategies has been told two different things about how it
    operates, and nothing says which is live."""
    cell = _make_cell(conn)
    first = _propose(conn, cell, wake_key="w1")
    approval.approve(
        conn, request_id=_request_for(conn, first.proposal_id),
        decided_by="operator", reason="fine for now",
    )
    second = _propose(conn, cell, wake_key="w2", summary="switch to library suppliers")
    approval.approve(
        conn, request_id=_request_for(conn, second.proposal_id),
        decided_by="operator", reason="better", now=datetime.now(timezone.utc) + timedelta(minutes=1),
    )

    body = _standing(conn, cell)
    assert "library suppliers" in body
    assert STRATEGY not in body


def test_a_strategy_nobody_approved_does_not_stand(conn):
    """Pending is not agreement. A Cell that read its own unreviewed proposal
    back as standing policy would be approving itself."""
    cell = _make_cell(conn)
    _propose(conn, cell)

    assert _standing(conn, cell) is None


def test_a_rejected_strategy_does_not_stand(conn):
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    approval.reject(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="that market is too small to matter",
    )

    assert _standing(conn, cell) is None


def test_only_a_strategy_becomes_a_standing_strategy(conn):
    """An approved spend request is permission to spend, not a statement of how
    the Cell operates. Folding every approval into standing context would turn
    each individual "yes" into a standing instruction the Cell reads back on
    every wake — §23's decisions are per-request by design."""
    cell = _make_cell(conn)
    result = _propose(
        conn, cell, kind="spend_request", summary="buy the sample dataset",
        estimated_cost_minor_units=40,
    )
    approval.approve(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="worth it",
    )

    assert _standing(conn, cell) is None


def test_a_lapsed_grant_does_not_un_adopt_a_standing_strategy(conn):
    """The grant beside a strategy approval is inert by construction, so its
    expiry says nothing about whether the strategy still stands.

    A derivation keyed on the *grant* rather than the decision would quietly
    revoke every strategy the colony ever agreed to, on a clock, with nothing
    anywhere saying it had happened.
    """
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    approval.approve(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="agreed",
    )
    approval.expire_grants_due(conn, now=datetime.now(timezone.utc) + timedelta(days=365))

    assert STRATEGY in _standing(conn, cell)


# --- §23.3: a statement is not regenerated ------------------------------------


def test_a_lapsed_strategy_grant_does_not_wake_the_cell(conn):
    """§23.3 regenerates expired **actions**, and a strategy names no action.

    The bug this replaced: a Cell proposed a strategy, a person approved it, the
    inert grant lapsed, and the Cell was woken to propose it again — told to
    redo the one thing that had actually succeeded.
    """
    cell = _make_cell(conn)
    result = _propose(conn, cell)
    grant = approval.approve(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="agreed",
    )

    expired = approval.expire_grants_due(
        conn, now=datetime.now(timezone.utc) + timedelta(days=365)
    )

    assert [g.grant_id for g in expired] == [grant.grant_id]
    assert approval.get_grant(conn, grant.grant_id).expired_at_utc is not None
    assert conn.execute("SELECT COUNT(*) AS n FROM event_inbox").fetchone()["n"] == 0


def test_a_lapsed_action_grant_still_wakes_the_cell(conn):
    """The contrast, without which the test above passes against a kernel that
    regenerates nothing at all — and §23.3's actual requirement would be gone.
    """
    cell = _make_cell(conn)
    result = _propose(conn, cell, kind="spend_request", estimated_cost_minor_units=40)
    grant = approval.approve(
        conn, request_id=_request_for(conn, result.proposal_id),
        decided_by="operator", reason="agreed",
    )

    approval.expire_grants_due(conn, now=datetime.now(timezone.utc) + timedelta(days=365))

    assert approval.get_grant(conn, grant.grant_id).regenerated_wake_key is not None
    assert conn.execute("SELECT COUNT(*) AS n FROM event_inbox").fetchone()["n"] == 1


# --- what a person decided reaches the Cell -----------------------------------


def test_the_cell_learns_what_a_person_decided(conn):
    """Before this, approved, rejected, expired and never-reviewed all rendered
    identically in the Cell's own proposal log — so the one signal the colony
    most wants a Cell to learn from was the one it could not see.

    Safe to give only because §23.4's `repeat_after_rejection` detector already
    exists: §23.5 says the queue will be optimised against, and re-asking for a
    rejected thing is the specific optimisation this feedback invites.
    """
    cell = _make_cell(conn)
    approved = _propose(conn, cell, wake_key="w1", summary="approved plan")
    approval.approve(
        conn, request_id=_request_for(conn, approved.proposal_id),
        decided_by="operator", reason="go ahead",
    )
    rejected = _propose(conn, cell, wake_key="w2", summary="rejected plan")
    approval.reject(
        conn, request_id=_request_for(conn, rejected.proposal_id),
        decided_by="operator", reason="too expensive",
    )
    _propose(conn, cell, wake_key="w3", summary="pending plan")

    log = _proposal_log(conn, cell)
    # Since ADR-053 the log carries no wording for any status — an approved
    # summary was measured to anchor exactly as hard as a pending one. What this
    # test defends is the *decision*, and all three still reach the Cell.
    assert "-> APPROVED, saying: go ahead" in log
    assert "-> REJECTED, saying: too expensive" in log
    assert "-> waiting on a person" in log
    for wording in ("approved plan", "rejected plan", "pending plan"):
        assert wording not in log, f"{wording!r} leaked back into the proposal log"
    # The approved one still reaches the Cell in full, through the section that
    # was always ADR-046's actual channel.
    assert "approved plan" in _standing(conn, cell)


def test_an_unreviewed_proposal_is_distinguishable_from_an_expired_one(conn):
    """"Nobody looked" and "the window closed before anyone looked" are
    different facts about the operator, and `approval_requests.status` already
    keeps them apart. Collapsing them here would tell a Cell it was judged when
    nobody judged it."""
    cell = _make_cell(conn)
    unqueued = _propose(conn, cell, wake_key="w1", summary="never queued", queued=False)
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM approval_requests WHERE proposal_id = ?",
        (unqueued.proposal_id,),
    ).fetchone()["n"] == 0
    _propose(conn, cell, wake_key="w2", summary="queued then lapsed")
    approval.expire_due(conn, now=datetime.now(timezone.utc) + timedelta(days=365))

    log = _proposal_log(conn, cell)
    # Neither is decided, so neither shows its wording (ADR-052) — the two facts
    # are carried entirely by the notes. Order is asserted rather than the
    # summary prefix, because that is what still ties each note to the proposal
    # it belongs to once the wording is gone.
    unreviewed = "-> not reviewed (nothing was asked of anyone)"
    lapsed = "-> the review window closed before anyone looked"
    assert unreviewed in log and lapsed in log
    assert log.index(unreviewed) < log.index(lapsed), "oldest first, so the note mapping holds"
    assert "never queued" not in log and "queued then lapsed" not in log
