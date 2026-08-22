"""The approval queue (SPEC.md §23; Amendments A11, A19).

Organised around the clause that makes this module adversarial rather than
administrative — §23.5, "the approval queue is itself part of the environment
and will be optimised against by Cells." Most of what follows defends a property
a Cell would benefit from breaking.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mitosis import (
    approval,
    deliberation,
    events,
    ledger,
    lifecycle,
    prediction,
    scheduler,
)
from mitosis.models import Book, CellStatus, CellType, EntrySpec
from mitosis.proposal import RiskTier

GENOME = {"market": "small accounting firms", "workflow": "probe cheaply"}


def _reply(**overrides) -> str:
    payload = {
        "kind": "experiment",
        "summary": "probe the synthetic market for demand",
        "rationale": "no realised record yet; a cheap probe is the fastest way to get one",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 5,
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
            description="fund for deliberation",
            entries=[
                EntrySpec(
                    account_id="seed_bank", amount_minor_units=-amount, cell_id=cell.cell_id
                ),
                EntrySpec(
                    account_id=f"cell:{cell.cell_id}:cash",
                    amount_minor_units=amount,
                    cell_id=cell.cell_id,
                ),
            ],
        )


def _make_cell(conn, *, key: str = "a", book: Book = Book.USD_SIM, fund: bool = True):
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
    if fund:
        _fund(conn, cell)
    return lifecycle.get_cell(conn, cell.cell_id)


def _propose(conn, cell, *, wake_key: str = "w1", now=None, **overrides):
    """Deliberate once with the queue wired, and return the resulting request.

    `now` routes around the sink so the queue can be assessed from a chosen
    point in time; the sink itself deliberately has no such parameter.
    """
    from mitosis import providers

    result = deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=_reply(**overrides)),
        wake_key=wake_key,
        model="mock-1",
        proposal_sink=None if now else approval.QueueSink(),
    )
    if now:
        approval.enqueue(conn, proposal_id=result.proposal_id, now=now)
    assert result.status == deliberation.DeliberationStatus.PROPOSED, result.failure_reason
    row = conn.execute(
        "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
        (result.proposal_id,),
    ).fetchone()
    return approval.get_request(conn, row["request_id"]) if row else None


# --- §23.5: the Cell does not set the tier it is reviewed at -----------------


def test_a_cell_cannot_lower_its_own_risk_tier(conn):
    """§23.5 + §0.3. The queue "will be optimised against by Cells", and
    proposal.py already names the exploit: a Cell that could set its own tier
    and be believed "would set it to LOW forever".

    If this fails, every risky request arrives labelled LOW, batch approval
    waves it through, and §23.1's individual-review requirement is dead.
    """
    cell = _make_cell(conn)
    request = _propose(
        conn, cell, kind="spend_request", risk_tier="LOW", estimated_cost_minor_units=40
    )

    assert request.claimed_tier is RiskTier.LOW
    assert request.assessed_tier is not RiskTier.LOW
    # The claim is preserved rather than overwritten — the attempt must stay visible.
    assert request.claimed_tier is RiskTier.LOW


def test_a_cell_may_raise_its_own_risk_tier(conn):
    """The other direction, and it must stay open. Claiming *more* danger than
    the kernel found is a Cell flagging itself; disbelieving that would be
    perverse and would discard genuine information.

    If this fails, `assessed = max(claimed, kernel)` has become
    `assessed = kernel` and the Cell's judgement is ignored entirely.
    """
    cell = _make_cell(conn)
    request = _propose(
        conn, cell, kind="experiment", risk_tier="CRITICAL", estimated_cost_minor_units=1
    )

    assert request.assessed_tier is RiskTier.CRITICAL


def test_assessed_tier_is_never_below_claimed_tier(conn):
    """The invariant behind both directions, stated once over every tier pair.

    If this fails, some combination of kind, book and exposure produces an
    assessment *below* what the Cell itself asked for — the one direction §23.5
    forbids.
    """
    for index, tier in enumerate(("LOW", "MEDIUM", "HIGH", "CRITICAL")):
        cell = _make_cell(conn, key=f"cell-{tier}")
        request = _propose(
            conn,
            cell,
            wake_key=f"w-{tier}",
            risk_tier=tier,
            estimated_cost_minor_units=index,
        )
        assert approval._TIER_ORDER[request.assessed_tier] >= approval._TIER_ORDER[
            RiskTier(tier)
        ]


def test_the_queue_seam_cannot_be_handed_a_precomputed_assessment(conn):
    """A structural test on the §23 seam, in the repo's `Displacer` tradition.

    `ProposalSink.enqueue_locked` takes a proposal id and nothing else. A
    parameter for a tier, a cost, or an exposure would be a channel through
    which a caller — and therefore, one layer up, a Cell's own output — could
    supply the classification the kernel is supposed to derive.

    If this fails, §23.5's guarantee is no longer enforced by the type of the
    seam, only by the discipline of its callers.
    """
    signature = inspect.signature(approval.QueueSink.enqueue_locked)
    parameters = set(signature.parameters) - {"self", "conn"}
    assert parameters == {"proposal_id"}, (
        f"the queue seam must derive its own classification; got {sorted(parameters)}"
    )

    protocol_signature = inspect.signature(deliberation.ProposalSink.enqueue_locked)
    assert set(protocol_signature.parameters) - {"self", "conn"} == {"proposal_id"}


# --- §23.1: tiers, reversibility, and batching -------------------------------


def test_real_money_spend_requests_are_irreversible(conn):
    """§23.1 requires individual review for irreversible actions, and §3.6 is
    why a real spend is one: history is never edited, only adjusted, and an
    adjustment does not bring the money back.

    If this fails, real spending becomes batch-approvable.
    """
    real_cell = _make_cell(conn, key="real", book=Book.USD_REAL)
    request = _propose(conn, real_cell, kind="spend_request", estimated_cost_minor_units=1)

    assert request.reversible is False
    assert request.batchable is False
    assert request.assessed_tier in {RiskTier.HIGH, RiskTier.CRITICAL}


def test_simulated_work_stays_reversible(conn):
    """The contrast case. USD_SIM experiments are exactly what §23.1's batching
    clause exists to keep cheap — if everything were irreversible, the queue
    would demand individual review for every synthetic probe and the operator
    would stop reading it."""
    cell = _make_cell(conn)
    request = _propose(conn, cell, kind="experiment", estimated_cost_minor_units=1)

    assert request.reversible is True
    assert request.batchable is True


def test_batch_approval_takes_only_low_risk_reversible_items(conn):
    """§23.1: "Batch low-risk reversible actions; require individual review for
    high-risk or irreversible actions."

    If this fails, a batch sweep clears items that were never individually
    reviewed, which is the exact authority §23.1 withholds.
    """
    cheap = _make_cell(conn, key="cheap")
    risky = _make_cell(conn, key="risky", book=Book.USD_REAL)

    cheap_request = _propose(conn, cheap, wake_key="w-cheap", estimated_cost_minor_units=1)
    risky_request = _propose(
        conn, risky, wake_key="w-risky", kind="spend_request", estimated_cost_minor_units=10
    )

    _, grants = approval.approve_batch(
        conn, decided_by="operator", reason="routine synthetic probes"
    )

    granted = {g.request_id for g in grants}
    assert cheap_request.request_id in granted
    assert risky_request.request_id not in granted
    assert approval.get_request(conn, risky_request.request_id).status == "pending"


def test_batch_approval_refuses_a_non_batchable_request_directly(conn):
    """The batch path must not be usable as a back door on a single item.

    If this fails, `approve_batch` becomes a way to approve anything without
    the individual review §23.1 requires.
    """
    risky = _make_cell(conn, key="risky", book=Book.USD_REAL)
    request = _propose(conn, risky, kind="spend_request", estimated_cost_minor_units=10)

    with pytest.raises(approval.ApprovalError, match="not batchable"):
        approval._decide_approve(
            conn,
            request_id=request.request_id,
            decided_by="operator",
            reason="sneaking it through",
            batch_id="batch-1",
            now=None,
        )


def test_a_gaming_signal_forces_individual_review(conn):
    """§23.1 and §23.4 meet here. An item carrying any anti-gaming signal is
    never batchable, however low its tier — batching is the *payload* of an
    action-splitting attack, so the two clauses have to interlock.

    **Two independent mechanisms carry this, and the test checks both
    separately on purpose.** Escalation is what carries it today: four of the
    five signals raise the tier, so a signalled item never arrives at
    `batchable` still LOW. The explicit `not self.signals` clause is therefore
    currently unreachable through the real path — which is exactly why it is
    asserted directly below rather than left to be exercised incidentally. If
    the escalation rules are ever loosened, that clause becomes the only thing
    standing between a gamed request and automatic approval, and a test that
    only ever saw the escalation would not notice it had rotted.
    """
    cell = _make_cell(conn)
    # Registered with a real (future) horizon, then assessed from a point past
    # it. The register refuses a deadline already gone — "a prediction
    # registered after its own deadline is not a prediction" — and the row
    # cannot be back-dated because the register is hash-chained. So the clock
    # moves, not the record.
    soon = datetime.now(timezone.utc) + timedelta(days=1)
    for index in range(approval.SELECTIVE_EVIDENCE_OVERDUE_LIMIT):
        prediction.register(
            conn,
            cell_id=cell.cell_id,
            claim=f"claim {index}",
            probability=0.5,
            resolves_by=soon,
            idempotency_key=f"p{index}",
        )

    request = _propose(
        conn, cell, estimated_cost_minor_units=1, now=soon + timedelta(days=1)
    )

    assert any(s.signal == approval.SIGNAL_SELECTIVE_EVIDENCE for s in request.signals)

    # Mechanism 1: the signal escalated the tier out of LOW.
    assert request.assessed_tier is not RiskTier.LOW

    # Mechanism 2: the explicit clause, isolated. Force the tier back to LOW so
    # escalation cannot be what produces the answer.
    forced_low = dataclasses.replace(request, assessed_tier=RiskTier.LOW)
    assert forced_low.signals
    assert forced_low.batchable is False

    # And the combination, which is what the operator actually relies on.
    assert request.batchable is False


# --- §23.4: anti-gaming (Amendment A11) --------------------------------------


def test_action_splitting_across_a_lineage_is_detected(conn):
    """§23.4 + A11: "detect splitting one risky action into many small ones ...
    via cumulative-exposure aggregation ... over a rolling window".

    Keyed on the lineage founder rather than the Cell, because §9 reproduction
    is the cheapest splitting mechanism this colony offers: a parent can birth
    children and have each ask for a fraction.

    If this fails, a lineage gets an unbounded budget in small change.
    """
    parent = _make_cell(conn, key="parent")
    per_request = 12  # individually below the MEDIUM threshold of 25.

    requests = []
    for index in range(4):
        requests.append(
            _propose(
                conn,
                parent,
                wake_key=f"split-{index}",
                kind="spend_request",
                estimated_cost_minor_units=per_request,
            )
        )

    last = requests[-1]
    assert last.exposure_minor_units == per_request * 4
    assert any(s.signal == approval.SIGNAL_ACTION_SPLITTING for s in last.signals)


def test_a_child_cells_request_counts_against_its_founders_exposure(conn):
    """The reason the aggregation key is the lineage. A Cell that split a risky
    ask across its children would otherwise show four clean first offences.

    If this fails, reproduction becomes a laundering mechanism for exposure.
    """
    from mitosis import lineage

    parent = _make_cell(conn, key="parent")
    # §9.4 caps a lineage at 20% of the living population, so a two-member
    # lineage needs eight unrelated Cells alongside it before the birth is
    # allowed. Seeding them is cheaper than raising the cap, which would make
    # the test pass for a reason unrelated to what it defends.
    for index in range(8):
        _make_cell(conn, key=f"bystander-{index}", fund=False)
    child = lineage.reproduce(
        conn,
        parent_cell_id=parent.cell_id,
        budget_minor_units=50,
        idempotency_key="child-1",
    )
    _fund(conn, child)

    parent_request = _propose(
        conn, parent, wake_key="p1", kind="spend_request", estimated_cost_minor_units=20
    )
    child_request = _propose(
        conn, child, wake_key="c1", kind="spend_request", estimated_cost_minor_units=20
    )

    assert child_request.aggregation_key == parent_request.aggregation_key
    assert child_request.exposure_minor_units == 40


def test_queue_flooding_is_detected(conn):
    """§23.4 "queue flooding", and the shape of §23.3's "400 approvals quietly
    queuing overnight".

    If this fails, a Cell can bury a real request in noise it generated itself.
    """
    cell = _make_cell(conn)
    last = None
    for index in range(approval.QUEUE_FLOOD_PENDING_LIMIT + 1):
        last = _propose(
            conn, cell, wake_key=f"flood-{index}", estimated_cost_minor_units=0
        )

    assert any(s.signal == approval.SIGNAL_QUEUE_FLOODING for s in last.signals)


def test_a_zero_cost_spend_request_is_flagged(conn):
    """§23.4's "misleading summaries". A spend request that claims to cost
    nothing is either wrong or an attempt to keep exposure off the aggregate.

    If this fails, a Cell zeroes its estimate and its requests never accumulate
    toward the splitting detector.
    """
    cell = _make_cell(conn)
    request = _propose(
        conn, cell, kind="spend_request", risk_tier="MEDIUM", estimated_cost_minor_units=0
    )

    assert any(s.signal == approval.SIGNAL_UNDERSTATED_RISK for s in request.signals)


def test_repeating_a_rejected_request_is_detected(conn):
    """§23.4's "repeated requests after rejection", compared on a normalised
    summary so re-punctuating does not launder it.

    If this fails, rejection costs a Cell one wake and nothing else.
    """
    cell = _make_cell(conn)
    first = _propose(conn, cell, wake_key="r1", summary="Buy the premium dataset")
    approval.reject(
        conn, request_id=first.request_id, decided_by="operator", reason="too expensive"
    )

    second = _propose(conn, cell, wake_key="r2", summary="buy the premium dataset!!!")

    assert any(
        s.signal == approval.SIGNAL_REPEAT_AFTER_REJECTION for s in second.signals
    )


def test_signals_annotate_and_never_auto_reject(conn):
    """§23.5 again, applied to the detectors themselves. An automatic rejector
    is simply the next thing to optimise against, and it kills honest work
    silently on a false positive. A signal escalates and forces individual
    review; the human still decides.

    If this fails, the queue starts making decisions nobody can appeal.
    """
    cell = _make_cell(conn)
    for index in range(approval.QUEUE_FLOOD_PENDING_LIMIT + 1):
        request = _propose(
            conn, cell, wake_key=f"annotate-{index}", estimated_cost_minor_units=0
        )

    assert request.signals
    assert request.status == approval.RequestStatus.PENDING
    # And it is still approvable by a human.
    grant = approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="checked, fine"
    )
    assert grant.request_id == request.request_id


def test_a_rejected_request_stops_counting_toward_exposure(conn):
    """A rejected ask costs nothing and never will, so counting it would inflate
    a lineage's exposure permanently on the strength of something the operator
    already refused. Repetition is caught by `repeat_after_rejection` instead.

    If this fails, one rejection quietly raises the tier of every later request
    that lineage makes.
    """
    cell = _make_cell(conn)
    first = _propose(conn, cell, wake_key="e1", kind="spend_request",
                     estimated_cost_minor_units=20)
    approval.reject(
        conn, request_id=first.request_id, decided_by="operator", reason="no"
    )

    second = _propose(conn, cell, wake_key="e2", kind="spend_request",
                      summary="a different ask entirely", estimated_cost_minor_units=20)

    assert second.exposure_minor_units == 20


# --- §23.3: SLA, expiry, and regeneration (Amendment A19) --------------------


def test_overdue_is_derived_not_stored(conn):
    """§23.3: "overdue items surface distinctly". Overdue is a *reporting*
    state — the item is still pending and still approvable on the same terms.

    If this became a stored lifecycle state it could disagree with the clock,
    and an item could be "overdue" in the table while its SLA had been extended.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell)

    assert request.is_overdue() is False
    later = request.sla_due_at_utc + timedelta(seconds=1)
    assert request.is_overdue(now=later) is True
    assert request.status == approval.RequestStatus.PENDING

    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(approval_requests)").fetchall()
    }
    assert "overdue" not in columns


def test_higher_risk_gets_a_shorter_sla(conn):
    """§27.1's `approval_sla_seconds` ordering: low 86400 ... critical 900. It
    reads backwards until you see that an SLA is not how long the operator may
    take, it is how fast the item needs eyes.

    If this inverts, critical items sit longest.
    """
    low = _make_cell(conn, key="low")
    critical = _make_cell(conn, key="crit")

    low_request = _propose(conn, low, wake_key="s1", risk_tier="LOW",
                           estimated_cost_minor_units=0)
    critical_request = _propose(conn, critical, wake_key="s2", risk_tier="CRITICAL",
                                estimated_cost_minor_units=0)

    assert critical_request.sla_seconds < low_request.sla_seconds


def test_an_expired_request_is_regenerated_not_dropped(conn):
    """§23.3: "expired actions are **regenerated and re-evaluated** before
    execution." Both halves. Expiry is not rejection — the operator never
    judged it — so the action is asked for again rather than discarded.

    If this fails, unreviewed work vanishes silently, which is exactly how a
    solo operator loses track of what the colony wanted to do.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell)

    after = request.expires_at_utc + timedelta(seconds=1)
    expired = approval.expire_due(conn, now=after)

    assert len(expired) == 1
    assert expired[0].status == approval.RequestStatus.EXPIRED
    assert expired[0].regenerated_wake_key is not None

    pending_wakes = [
        event
        for event in events.next_ready(conn, now=after)
        if event.event_type == deliberation.WAKE_EVENT_TYPE
    ]
    assert any(
        e.payload.get("wake_reason") == approval.WAKE_APPROVAL_EXPIRED
        for e in pending_wakes
    )


def test_an_expired_request_cannot_be_approved(conn):
    """The other half of §23.3. An approval granted against expired reasoning is
    precisely what "re-evaluated before execution" forbids.

    If this fails, an operator clearing a backlog approves week-old assessments
    of a world that has moved.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell)
    after = request.expires_at_utc + timedelta(seconds=1)

    with pytest.raises(approval.ApprovalError, match="expired"):
        approval.approve(
            conn,
            request_id=request.request_id,
            decided_by="operator",
            reason="clearing the backlog",
            now=after,
        )


def test_expiry_of_an_unwakeable_cells_request_records_the_gap(conn):
    """A dead Cell has nothing to regenerate into. The request still expires,
    and `regenerated_wake_key` stays NULL so the gap is visible rather than
    looking like a wake that went missing."""
    cell = _make_cell(conn)
    request = _propose(conn, cell)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    after = request.expires_at_utc + timedelta(seconds=1)
    expired = approval.expire_due(conn, now=after)

    assert expired[0].status == approval.RequestStatus.EXPIRED
    assert expired[0].regenerated_wake_key is None


def test_expiry_does_not_override_a_decision_made_first(conn):
    """The race the sweep must lose. If an operator decided the item between the
    scan and the lock, their decision stands.

    If this fails, a sweep can overwrite a human's approval with an expiry.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell)
    approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="fine"
    )

    after = request.expires_at_utc + timedelta(seconds=1)
    expired = approval.expire_due(conn, now=after)

    assert expired == []
    assert approval.get_request(conn, request.request_id).status == "approved"


# --- §23.2: the payload ------------------------------------------------------


def test_the_payload_carries_every_element_the_clause_names(conn):
    """§23.2 lists ten things the operator must see before deciding. A payload
    that quietly drops one is worse than one reporting it unavailable, because
    only the second is visible in review."""
    cell = _make_cell(conn)
    request = _propose(conn, cell, kind="spend_request", estimated_cost_minor_units=7)
    detail = approval.payload(conn, request.request_id)

    assert detail.proposal["summary"]                       # proposed action
    assert detail.exposure_minor_units == 7                 # cumulative exposure
    assert detail.estimated_cost_minor_units == 7           # real and synthetic cost
    assert detail.book is Book.USD_SIM
    assert detail.liability_minor_units is None             # liability (unmodelled)
    assert detail.cell_explanation                          # Cell explanation
    assert detail.auditor_summary is None                   # Auditor summary (absent)
    assert detail.request.reversible is True                # reversibility
    assert detail.resolved_prediction_count == 0            # relevant evidence
    assert detail.signals is not None                       # policy classification
    assert detail.request.expires_at_utc                    # expiry time


def test_the_auditor_summary_can_never_come_from_the_proposing_cell(conn):
    """§23.2 asks for an *independent* Auditor summary, and §0.3 forbids a Cell
    defining the canonical account of its own work. No Auditor Cell exists, so
    the honest value is absent — and it must not be quietly backfilled from the
    Cell's own rationale, which would make the payload's independence a lie.

    If this fails, the operator reads the proposer's self-assessment believing
    it to be a second opinion.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell, rationale="this is completely safe, trust me")
    detail = approval.payload(conn, request.request_id)

    assert detail.auditor_summary is None
    assert detail.cell_explanation == "this is completely safe, trust me"


def test_evidence_comes_from_the_register_not_the_proposal(conn):
    """§23.2's "relevant evidence" is drawn from the hash-chained prediction
    register, not from anything the Cell wrote. Same source the Cell's own §15
    context reads, so operator and Cell see the same tamper-evident facts.

    If this fails, a Cell's track record in the payload becomes self-reported.
    """
    cell = _make_cell(conn)
    soon = datetime.now(timezone.utc) + timedelta(days=1)
    for index in range(2):
        prediction.register(
            conn,
            cell_id=cell.cell_id,
            claim=f"overdue claim {index}",
            probability=0.5,
            resolves_by=soon,
            idempotency_key=f"ev{index}",
        )

    request = _propose(conn, cell)
    detail = approval.payload(conn, request.request_id, now=soon + timedelta(days=1))

    assert detail.unresolved_prediction_count == 2
    assert detail.overdue_prediction_count == 2


# --- §25.1: this is rung 6, not rung 9 ---------------------------------------


def test_only_the_promotion_module_consumes_a_grant():
    """§25.1's ladder, enforced structurally — and this test has been
    *deliberately loosened once*, which is the point of it existing.

    ADR-027 shipped it as "no module consumes a grant", pinning the loop at rung
    6 ("human-reviewed prototype"). ADR-028's successor, `promotion.py`, is the
    argued step to rung 7 ("tiny capped live experiment"), and it had to change
    this test to land — exactly the friction intended: climbing the ladder must
    cost an explicit edit to a named guarantee, not slip in as a plausible
    commit.

    What it still forbids is the *next* unargued step. Only `promotion.py` may
    write a grant's `consumed_at_utc`, and nothing scheduled may reach it — the
    scheduler must not import promotion, or rung 7's "a human runs each
    allocation" quietly becomes rung 9's bounded autonomy.
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    allowed = {"promotion.py"}

    consumers = []
    for path in sorted(source_dir.glob("*.py")):
        if path.name in allowed:
            continue
        text = path.read_text().lower()
        if "consumed_at_utc = ?" in text or "insert into promotions" in text:
            consumers.append(path.name)

    assert not consumers, (
        f"{consumers} consumes an approval grant — only promotion.py may, and moving "
        "that authority is a step up §25.1's ladder"
    )

    # The scheduler is the specific module that must never gain it: it is the
    # one that runs while nobody is watching.
    scheduler_source = (source_dir / "scheduler.py").read_text()
    assert "promotion" not in scheduler_source, (
        "scheduler.py must not reach the promotion path — an allocation that fires "
        "on a timer is rung 9 (bounded autonomy), not rung 7"
    )


def test_a_grant_is_never_consumed_on_creation(conn):
    """The runtime half. Approval records authority; it does not spend it.

    If this fails, something began executing grants.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell)
    grant = approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="fine"
    )

    assert grant.consumed_at_utc is None
    assert grant.expires_at_utc == request.expires_at_utc


# --- decisions and their record ----------------------------------------------


def test_a_decision_must_state_a_reason(conn):
    """§25.2 requires "the reasons for promotion or rejection" recorded at each
    rung. This is the rung-6 gate, so an unexplained decision is unauditable —
    and `repeat_after_rejection` is only meaningful if rejections say why.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell)

    with pytest.raises(approval.ApprovalError, match="reason"):
        approval.approve(
            conn, request_id=request.request_id, decided_by="operator", reason="  "
        )
    with pytest.raises(approval.ApprovalError, match="reason"):
        approval.reject(
            conn, request_id=request.request_id, decided_by="operator", reason=""
        )


def test_a_request_cannot_be_decided_twice(conn):
    """Validation happens inside the write lock, not before it. Check-then-lock
    is a bug class this kernel already fixed once across the board; here it
    would mean two decisions on one item, or a grant against a rejected request.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell)
    approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="fine"
    )

    with pytest.raises(approval.ApprovalError, match="already"):
        approval.reject(
            conn, request_id=request.request_id, decided_by="operator", reason="changed my mind"
        )


def test_every_decision_is_audited(conn):
    """An unattended colony's review path has to leave a trail — §23.3's whole
    premise is that nobody was watching at the time."""
    cell = _make_cell(conn)
    first = _propose(conn, cell, wake_key="a1")
    second = _propose(conn, cell, wake_key="a2")

    approval.approve(
        conn, request_id=first.request_id, decided_by="operator", reason="yes"
    )
    approval.reject(
        conn, request_id=second.request_id, decided_by="operator", reason="no"
    )

    types = {
        row["event_type"]
        for row in conn.execute("SELECT event_type FROM audit_events").fetchall()
    }
    assert {"approval_requested", "approval_granted", "approval_rejected"} <= types


# --- queueing behaviour ------------------------------------------------------


def test_an_abstention_is_not_queued(conn):
    """There is nothing to approve in "I have nothing to propose" — and a queue
    padded with abstentions is *useful* to a Cell trying to make a flood look
    ordinary, which makes this an anti-gaming concern rather than a tidiness one.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell, kind="abstain", summary="nothing worth doing yet")

    assert request is None
    assert approval.queue(conn) == []


def test_queueing_is_atomic_with_recording_the_proposal(conn):
    """A proposal recorded without a queue entry is one no operator sees. The
    sink runs inside `_record_proposal`'s transaction for the same reason
    prediction registration does.

    If this fails, a crash between the two produces invisible proposals.
    """
    cell = _make_cell(conn)
    request = _propose(conn, cell)

    proposals = conn.execute("SELECT COUNT(*) AS n FROM proposals").fetchone()["n"]
    requests = conn.execute("SELECT COUNT(*) AS n FROM approval_requests").fetchone()["n"]
    assert proposals == requests == 1
    assert request is not None


def test_enqueue_missing_backfills_and_is_idempotent(conn):
    """Self-healing for proposals recorded before the queue existed, or by a
    caller that did not wire the sink. A review surface that can silently miss
    items is not one.
    """
    from mitosis import providers

    cell = _make_cell(conn)
    deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=_reply()),
        wake_key="unqueued",
        model="mock-1",
    )  # no sink
    assert approval.queue(conn) == []

    queued = approval.enqueue_missing(conn)
    assert len(queued) == 1
    assert approval.enqueue_missing(conn) == []


def test_one_proposal_cannot_produce_two_queue_entries(conn):
    """Two review paths for one intention would let an operator approve one
    while rejecting the other."""
    cell = _make_cell(conn)
    request = _propose(conn, cell)

    again = approval.enqueue(conn, proposal_id=request.proposal_id)
    assert again.request_id == request.request_id
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM approval_requests"
    ).fetchone()["n"] == 1


def test_the_queue_surfaces_the_most_urgent_first(conn):
    """§23.3's "overdue items surface distinctly" holds without the caller
    sorting: highest tier first, then longest-waiting."""
    low = _make_cell(conn, key="low")
    high = _make_cell(conn, key="high", book=Book.USD_REAL)

    _propose(conn, low, wake_key="q1", estimated_cost_minor_units=0)
    _propose(conn, high, wake_key="q2", kind="spend_request", estimated_cost_minor_units=5)

    ordered = approval.queue(conn)
    assert ordered[0].assessed_tier is not RiskTier.LOW


# --- §27.1 wiring ------------------------------------------------------------


def test_exposure_thresholds_track_the_operators_metabolic_alarm(conn):
    """The queue's risk thresholds are multiples of
    `operator.metabolic_alarm_cents_per_epoch` rather than three fresh
    constants — the colony should not hold two different silent opinions about
    what a worrying amount of money is.

    If this fails, tuning burn tolerance no longer moves the review thresholds
    and the two drift apart.
    """
    scheduler.initialize_operator_if_absent(conn)
    conn.execute("UPDATE operator_state SET metabolic_alarm_cents_per_epoch = 1000")
    conn.commit()

    cell = _make_cell(conn)
    request = _propose(conn, cell, kind="experiment", estimated_cost_minor_units=40)

    # 40 would be HIGH against the default alarm of 50; against 1000 it is LOW.
    assert request.assessed_tier is RiskTier.LOW


def test_slas_come_from_the_operator_row(conn):
    """§27.1's `approval_sla_seconds` is stored and, until now, timed nothing."""
    scheduler.initialize_operator_if_absent(conn)
    conn.execute("UPDATE operator_state SET approval_sla_low_seconds = 42")
    conn.commit()

    cell = _make_cell(conn)
    request = _propose(conn, cell, risk_tier="LOW", estimated_cost_minor_units=0)

    assert request.sla_seconds == 42
    assert request.expires_at_utc == request.created_at_utc + timedelta(
        seconds=42 * approval.EXPIRY_SLA_MULTIPLE
    )
