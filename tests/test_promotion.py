"""Rung 7: an approved grant allocates capital (SPEC.md §25.1, §25.2, §17.2, §31).

The colony's core loop (§31) reads "... -> allocate capital -> scale, mutate,
collaborate, sleep, or die". These defend the arrow: that it moves only under a
human's hand, only the amount a human saw, only from a pot a human filled, and
only once.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    approval,
    deliberation,
    events,
    ledger,
    lifecycle,
    promotion,
    providers,
    scheduler,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellStatus, CellType, EntrySpec

GENOME = {"objective": "find a paying niche", "strategy": "probe cheaply"}


def _reply(**overrides) -> str:
    payload = {
        "kind": "spend_request",
        "summary": "buy the sample dataset",
        "rationale": "cheapest way to test the demand hypothesis",
        "risk_tier": "MEDIUM",
        "estimated_cost_minor_units": 40,
        "predictions": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _fund(conn, cell, amount: int = 50_000) -> None:
    for book, currency in (
        (Book.USD_REAL, "USD"),
        (Book.RESOURCE, "RESOURCE"),
        (Book.USD_SIM, "USD"),
    ):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="cell_birth_funding",
            idempotency_key=f"fund:{cell.cell_id}:{book.value}",
            description="fund",
            entries=[
                EntrySpec(
                    account_id="seed_bank", amount_minor_units=-amount, cell_id=cell.cell_id
                ),
                EntrySpec(
                    account_id=cell_cash(cell.cell_id),
                    amount_minor_units=amount,
                    cell_id=cell.cell_id,
                ),
            ],
        )


def _seed_pool(conn, amount: int = 10_000, book: Book = Book.USD_SIM) -> None:
    """The treasury needs capital before the pool can hold any."""
    ledger.post_transaction(
        conn,
        book=book,
        currency="USD" if book != Book.RESOURCE else "RESOURCE",
        transaction_type="colony_seed_capital",
        idempotency_key=f"seed-treasury:{book.value}",
        description="seed the treasury",
        entries=[
            EntrySpec(account_id="external_capital", amount_minor_units=-amount),
            EntrySpec(account_id="colony_treasury", amount_minor_units=amount),
        ],
    )
    promotion.fund_pool(
        conn, book=book, amount_minor_units=amount, idempotency_key=f"pool:{book.value}"
    )


def _make_cell(conn, *, key: str = "a", book: Book = Book.USD_SIM):
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=100,
        book=book,
        idempotency_key=key,
    )
    genome_hash = lifecycle._get_or_create_genome(conn, CellType.EXPLORER, mutation=GENOME)
    conn.execute(
        "UPDATE cells SET genome_hash = ? WHERE cell_id = ?", (genome_hash, cell.cell_id)
    )
    conn.commit()
    _fund(conn, cell)
    return lifecycle.get_cell(conn, cell.cell_id)


def _approved_grant(conn, cell, *, wake_key: str = "w1", **overrides):
    """Drive the real path: deliberate, queue, approve."""
    result = deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=_reply(**overrides)),
        wake_key=wake_key,
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    row = conn.execute(
        "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
        (result.proposal_id,),
    ).fetchone()
    return approval.approve(
        conn, request_id=row["request_id"], decided_by="operator", reason="worth testing"
    )


# --- the loop actually closes -------------------------------------------------


def test_allocating_a_grant_funds_the_cell(conn):
    """§31's core loop: "... -> allocate capital -> ...". Until this, the colony
    could do everything on both sides of that arrow and nothing at the arrow.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    before = ledger.get_balance(conn, cell_cash(cell.cell_id), book=Book.USD_SIM)

    result = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="tiny capped test"
    )

    assert result.allocated_minor_units == 40
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), book=Book.USD_SIM) == before + 40
    assert promotion.pool_balance(conn, Book.USD_SIM) == 10_000 - 40
    assert ledger.verify_conservation(conn, Book.USD_SIM)


def test_the_allocation_wakes_the_cell_for_capital_allocation(conn):
    """§17.2 lists "capital allocation" among its wake reasons, and the constant
    has been defined and unemitted since the agent loop landed. A Cell funded
    without being told has capital it will not use until something unrelated
    wakes it, which makes the allocation look inert exactly when it is not.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    result = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
    )

    assert result.wake_key is not None
    ready = events.next_ready(conn, now=datetime.now(timezone.utc) + timedelta(minutes=1))
    reasons = [
        e.payload.get("wake_reason")
        for e in ready
        if e.event_type == deliberation.WAKE_EVENT_TYPE
    ]
    assert deliberation.WAKE_CAPITAL_ALLOCATION in reasons


def test_the_promotion_is_recorded_at_the_right_rung(conn):
    """§25.1 has nine rungs. A later slice issuing rung-8 promotions must not be
    indistinguishable in the record from this one.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    result = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
    )

    assert result.rung == promotion.LADDER_RUNG_CAPPED_LIVE_EXPERIMENT == 7


def test_promotion_evidence_records_what_25_2_asks_for(conn):
    """§25.2: "At each rung record predicted vs observed outcome, cost,
    liability, reality gap ..., human intervention, transfer degradation, and
    the reasons for promotion or rejection."

    Two of those cannot be known at allocation time and must report as
    unavailable rather than as a fabricated zero — a 0 liability reads as "no
    liability" and a 0 transfer degradation reads as "transferred perfectly".
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    result = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="mohammad", reason="tiny capped test"
    )

    assert result.allocated_minor_units == 40            # cost
    assert result.liability_minor_units is None          # liability (unmodelled)
    assert result.reality_gap_mean_brier is None         # reality gap (nothing resolved)
    assert result.unresolved_predictions == 0
    assert result.approved_by == "operator"              # human intervention, both of them
    assert result.allocated_by == "mohammad"
    assert result.transfer_degradation is None           # no earlier rung to degrade from
    assert result.reason == "tiny capped test"


# --- what an allocation must refuse ------------------------------------------


def test_a_grant_can_only_be_allocated_once(conn):
    """A grant authorises one allocation. If this fails, an approved request is
    a standing instruction to hand over money repeatedly.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
    )
    with pytest.raises(promotion.PromotionError, match="already consumed"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by="operator", reason="again"
        )

    assert promotion.pool_balance(conn, Book.USD_SIM) == 10_000 - 40


def test_an_expired_grant_cannot_be_allocated(conn):
    """§23.3: an expired approval is regenerated and re-evaluated, never executed
    late. The grant inherits its request's expiry precisely so an approval
    cannot be banked and spent against a world that has moved on.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    with pytest.raises(promotion.PromotionError, match="expired"):
        promotion.allocate(
            conn,
            grant_id=grant.grant_id,
            allocated_by="operator",
            reason="clearing the backlog",
            now=grant.expires_at_utc + timedelta(seconds=1),
        )
    assert promotion.pool_balance(conn, Book.USD_SIM) == 10_000


def test_only_a_spend_request_allocates_capital(conn):
    """Approving an experiment is a human saying "yes, think about that" — not a
    capital decision. Quietly treating it as one would let a Cell obtain funding
    through a proposal that was never reviewed as a request for money.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell, kind="experiment", risk_tier="LOW")

    with pytest.raises(promotion.PromotionError, match="only a spend_request"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
        )


def test_the_pool_is_a_hard_ceiling(conn):
    """The pool is the one number bounding everything this path can allocate,
    set by a human in advance. No Cell can fund it and nothing scheduled draws
    on it.

    If this fails, an approval can overdraw the colony.
    """
    _seed_pool(conn, amount=30)          # less than the 40 the Cell asked for
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    with pytest.raises(promotion.PromotionError, match="promotion pool holds 30"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
        )
    assert promotion.pool_balance(conn, Book.USD_SIM) == 30


def test_a_dead_cell_cannot_receive_capital(conn):
    """Charter C8. Funding a Cell that cannot act is capital thrown away — and
    ADR-028's estate would immediately reclaim it, so the money would make a
    pointless round trip through a corpse.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    with pytest.raises(promotion.PromotionError, match="dead"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
        )


def test_a_quarantined_cell_cannot_receive_capital(conn):
    """§18.2. A Cell under restriction that can still be handed money is only
    restricted in name.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    lifecycle.quarantine(conn, cell.cell_id, reason="policy review")

    with pytest.raises(promotion.PromotionError, match="quarantined"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
        )


def test_allocating_real_money_needs_the_autonomy_flag_too(conn):
    """ADR-026's two-independent-confirmations rule, applied to capital. The §23
    approval says "this request is sound"; §27.1's `autonomy.real_spending` says
    "this colony may move real money". An approval alone must not be able to
    turn the first into the second.
    """
    _seed_pool(conn, book=Book.USD_REAL)
    scheduler.initialize_operator_if_absent(conn)
    cell = _make_cell(conn, book=Book.USD_REAL)
    grant = _approved_grant(conn, cell)

    with pytest.raises(promotion.PromotionError, match="real_spending"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
        )

    scheduler.set_real_spending(conn, enabled=True)
    result = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
    )
    assert result.book is Book.USD_REAL


def test_an_allocation_must_state_a_reason(conn):
    """§25.2 requires "the reasons for promotion" recorded at every rung."""
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    with pytest.raises(promotion.PromotionError, match="reason"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by="operator", reason="  "
        )


def test_the_cell_cannot_change_the_amount_after_approval(conn):
    """§23.2 showed the operator a number; that number is what moves. The Cell is
    not consulted at allocation time at all — it is told afterwards, through the
    ordinary §15 context, that its balance changed.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    # A Cell rewriting its own proposal is impossible through the kernel; this
    # asserts the allocation reads the approved figure rather than anything
    # re-derived, by checking it against the grant the operator actually saw.
    result = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
    )
    approved_cost = conn.execute(
        "SELECT estimated_cost_minor_units AS c FROM proposals WHERE proposal_id = ?",
        (grant.proposal_id,),
    ).fetchone()["c"]
    assert result.allocated_minor_units == approved_cost


# --- the failure path leaves nothing behind ----------------------------------


def test_a_refused_allocation_moves_no_money_and_consumes_nothing(conn):
    """Everything in an allocation is one transaction: the ledger movement, the
    grant being consumed, the §25.2 record, and the wake. A refusal partway
    through must leave all four untouched.
    """
    _seed_pool(conn, amount=30)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    with pytest.raises(promotion.PromotionError):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by="operator", reason="go"
        )

    assert promotion.pool_balance(conn, Book.USD_SIM) == 30
    assert approval.get_grant(conn, grant.grant_id).consumed_at_utc is None
    assert promotion.list_promotions(conn) == []
    assert ledger.verify_conservation(conn, Book.USD_SIM)


def test_allocatable_grants_hides_what_would_refuse(conn):
    """The operator's worklist should not list things that will simply error."""
    _seed_pool(conn)
    cell = _make_cell(conn)
    spendable = _approved_grant(conn, cell, wake_key="w1")
    _approved_grant(conn, cell, wake_key="w2", kind="experiment", risk_tier="LOW")

    ready = promotion.allocatable_grants(conn)
    assert [g.grant_id for g in ready] == [spendable.grant_id]

    promotion.allocate(
        conn, grant_id=spendable.grant_id, allocated_by="operator", reason="go"
    )
    assert promotion.allocatable_grants(conn) == []
