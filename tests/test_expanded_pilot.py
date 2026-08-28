"""§25.1 rung 8 ("expanded pilot") and the bounded engine that issues it.

Every test is named for the property it defends. The theme is that rung 8 is a
*scale* step, not an autonomy step — the two axes are independent, and most of
the ways this could go wrong are ways of quietly conflating them.
"""

import inspect
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    approval,
    autopromotion,
    deliberation,
    ledger,
    lifecycle,
    models,
    outcome,
    population,
    prediction,
    promotion,
    providers,
    tools,
)
from mitosis.models import Book, CellType, EntrySpec


# --- fixtures ----------------------------------------------------------------


def _seed(conn, *, pool=10_000):
    population.set_limits_if_absent(conn, models.DEFAULT_POPULATION_LIMITS)
    for book, currency, amount in (
        (Book.USD_SIM, "USD", 100_000),
        (Book.USD_REAL, "USD", 10_000),
        (Book.RESOURCE, "RESOURCE", 500_000),
    ):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="external_capital_in",
            idempotency_key=f"seed:{book.value}",
            description="test seed",
            entries=[
                EntrySpec(account_id="external_capital", amount_minor_units=-amount),
                EntrySpec(account_id="seed_bank", amount_minor_units=amount),
            ],
        )
    promotion.fund_pool(
        conn,
        book=Book.USD_SIM,
        amount_minor_units=pool,
        funding_account="seed_bank",
        idempotency_key="pool",
    )


def _cell(conn, tag, *, book=Book.USD_SIM):
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=200,
        book=book,
        idempotency_key=f"cell:{tag}",
    )
    # §15.4: a Cell pays for its own thinking, so it needs a balance in the
    # books deliberation bills before it can produce a proposal at all.
    for fund_book, currency, amount in (
        (Book.USD_REAL, "USD", 50),
        (Book.RESOURCE, "RESOURCE", 5_000),
    ):
        ledger.post_transaction(
            conn,
            book=fund_book,
            currency=currency,
            transaction_type="cell_funding",
            idempotency_key=f"fund:{tag}:{fund_book.value}",
            description="§15.4: a Cell pays for its own thinking",
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
    return cell


def _forecast(conn, cell, claim, probability, *, days=30, key=None):
    return prediction.register(
        conn,
        cell_id=cell.cell_id,
        claim=claim,
        probability=probability,
        resolves_by=datetime.now(timezone.utc) + timedelta(days=days),
        idempotency_key=key,
    )


def _grant(conn, cell, tag, *, cost=30, tier="MEDIUM"):
    deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(
            reply=json.dumps(
                {
                    "kind": "spend_request",
                    "summary": f"test request {tag}",
                    "rationale": "exists to produce a promotion",
                    "risk_tier": tier,
                    "estimated_cost_minor_units": cost,
                    "predictions": [],
                },
                sort_keys=True,
            )
        ),
        wake_key=f"wake:{tag}",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    request = next(
        r for r in approval.queue(conn)
        if r.cell_id == cell.cell_id and r.request_id not in _seen_requests
    )
    _seen_requests.add(request.request_id)
    return approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="test approval"
    )


_seen_requests: set = set()


@pytest.fixture(autouse=True)
def _reset_seen():
    _seen_requests.clear()
    yield
    _seen_requests.clear()


def _earned_rung_7(conn, cell, tag):
    """A rung-7 promotion whose §25.2 evidence supports an expansion."""
    sloppy = [_forecast(conn, cell, f"{tag} sloppy {i}", 0.6, key=f"{tag}s{i}") for i in range(3)]
    for item in sloppy:
        prediction.resolve(conn, item.prediction_id, occurred=True, source="test")
    funding_set = [
        _forecast(conn, cell, f"{tag} funded {i}", 0.95, key=f"{tag}f{i}") for i in range(3)
    ]
    grant = _grant(conn, cell, f"{tag}-7")
    record = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="rung 7"
    )
    for item in funding_set:
        prediction.resolve(conn, item.prediction_id, occurred=True, source="test")
    return record


# --- §25.1: the ladder forbids skipping --------------------------------------


def test_an_expansion_without_a_predecessor_is_refused(conn):
    """§25.1: "No strategy moves directly from synthetic success to autonomous
    commerce." Rung 8 expands something; a Cell with no rung-7 promotion has
    nothing to expand, and funding one anyway would be the ladder's whole
    purpose defeated on its first use."""
    _seed(conn)
    cell = _cell(conn, "a")
    grant = _grant(conn, cell, "a")

    with pytest.raises(promotion.PromotionError, match="no rung-7 promotion"):
        promotion.allocate(
            conn,
            grant_id=grant.grant_id,
            allocated_by="operator",
            reason="skip the ladder",
            rung=8,
            evidence=outcome.AssessmentEvidence(),
        )


def test_the_schema_refuses_a_skipped_rung_by_direct_insert(conn):
    """ADR-047: a constraint has no layer.

    `promotion.py`'s check binds callers that go through `promotion.py`. This
    repo has escape hatches that do not — `mitosis start-experiment --rung 7` is
    one, and a future importer is another. Migration 0030's trigger is what
    makes the skipped rung *unrepresentable* rather than merely refused, which
    is the difference between a guard and a guarantee.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    record = _earned_rung_7(conn, cell, "a")

    with pytest.raises(sqlite3.IntegrityError, match="ladder forbids skipping"):
        conn.execute(
            """
            INSERT INTO promotions (
                promotion_id, grant_id, request_id, proposal_id, cell_id, rung,
                book, allocated_minor_units, resolved_predictions,
                unresolved_predictions, approved_by, allocated_by, reason,
                created_at_utc, supersedes_promotion_id
            ) VALUES ('p-x', 'g-x', ?, ?, ?, 8, 'USD_SIM', 10, 0, 0,
                      'op', 'op', 'smuggled', ?, NULL)
            """,
            (record.request_id, record.proposal_id, cell.cell_id,
             datetime.now(timezone.utc).isoformat()),
        )


def test_a_promotion_cannot_expand_another_cells_evidence(conn):
    """§29's reciprocal evidence farming, expressed as a foreign key that
    happens to point somewhere plausible.

    Cell A does the work and earns the verdict; Cell B names A's promotion as
    its predecessor. Without the same-Cell check the FK is satisfied, the rung
    is legal, and B is funded on evidence it never produced.
    """
    _seed(conn)
    worker = _cell(conn, "worker")
    freeloader = _cell(conn, "freeloader")
    earned = _earned_rung_7(conn, worker, "w")

    with pytest.raises(sqlite3.IntegrityError, match="own evidence"):
        conn.execute(
            """
            INSERT INTO promotions (
                promotion_id, grant_id, request_id, proposal_id, cell_id, rung,
                book, allocated_minor_units, resolved_predictions,
                unresolved_predictions, approved_by, allocated_by, reason,
                created_at_utc, supersedes_promotion_id
            ) VALUES ('p-y', 'g-y', ?, ?, ?, 8, 'USD_SIM', 10, 0, 0,
                      'op', 'op', 'borrowed', ?, ?)
            """,
            (earned.request_id, earned.proposal_id, freeloader.cell_id,
             datetime.now(timezone.utc).isoformat(), earned.promotion_id),
        )


def test_one_success_supports_only_one_expansion(conn):
    """§23.4's action-splitting attack, run upward.

    §23.4 detects "splitting one risky action into many small ones". The
    inverse is expanding one piece of evidence many times: three rung-8 grants
    all naming the same successful rung-7 experiment. The unique index makes
    the second one impossible rather than merely unlikely.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    earned = _earned_rung_7(conn, cell, "a")

    first = _grant(conn, cell, "a-8a")
    promotion.allocate(
        conn, grant_id=first.grant_id, allocated_by="operator", reason="expand once",
        rung=8, evidence=outcome.AssessmentEvidence(),
    )

    second = _grant(conn, cell, "a-8b")
    with pytest.raises(promotion.PromotionError, match="no rung-7 promotion"):
        promotion.allocate(
            conn, grant_id=second.grant_id, allocated_by="operator",
            reason="expand twice", rung=8, evidence=outcome.AssessmentEvidence(),
        )


def test_the_schema_refuses_a_second_expansion_of_one_success(conn):
    """The same property as above, one layer down — and it needs its own test.

    `test_one_success_supports_only_one_expansion` passes even with the unique
    index dropped, because `_latest_promotion_at_rung_locked` declines to *find*
    an already-expanded predecessor. That is a good guard and it is not a
    guarantee: it binds callers that go through `promotion.py`, and ADR-047's
    whole lesson is that a constraint has no layer. A direct insert is what a
    future importer, a repair script, or `start-experiment`'s escape hatch
    looks like to the database.

    Found by teeth-checking: dropping the index left every other test green.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    earned = _earned_rung_7(conn, cell, "a")
    grant = _grant(conn, cell, "a-8")
    first = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator",
        reason="the one legitimate expansion", rung=8,
        evidence=outcome.AssessmentEvidence(),
    )
    assert first.supersedes_promotion_id == earned.promotion_id

    # A *fully valid* second row but for the one thing under test: its own real
    # grant, request and proposal, the right cell, the right rung. If the index
    # were dropped this insert would simply succeed, which is what makes the
    # failure signal unambiguous — no foreign key stands in as an accidental
    # second line of defence.
    spare = _grant(conn, cell, "a-spare")
    with pytest.raises(
        sqlite3.IntegrityError,
        match="UNIQUE constraint failed: promotions.supersedes_promotion_id",
    ):
        conn.execute(
            """
            INSERT INTO promotions (
                promotion_id, grant_id, request_id, proposal_id, cell_id, rung,
                book, allocated_minor_units, resolved_predictions,
                unresolved_predictions, approved_by, allocated_by, reason,
                created_at_utc, supersedes_promotion_id
            ) VALUES ('p-dup', ?, ?, ?, ?, 8, 'USD_SIM', 10, 0, 0,
                      'op', 'op', 'second bite', ?, ?)
            """,
            (spare.grant_id, spare.request_id, spare.proposal_id, cell.cell_id,
             datetime.now(timezone.utc).isoformat(), earned.promotion_id),
        )


# --- §25.2: an expansion is earned, not requested ----------------------------


def test_an_expansion_needs_a_supporting_verdict(conn):
    """§25.2: promotion evidence is "predicted vs observed outcome".

    A rung-7 promotion whose forecasts have not resolved yields
    `INSUFFICIENT_EVIDENCE`, and that is not a licence to expand. The failure
    this pins is the tempting one: treating "no evidence against" as support.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    _forecast(conn, cell, "unresolved", 0.9, key="u1")
    grant7 = _grant(conn, cell, "a-7")
    promotion.allocate(
        conn, grant_id=grant7.grant_id, allocated_by="operator", reason="rung 7"
    )

    grant8 = _grant(conn, cell, "a-8")
    with pytest.raises(promotion.PromotionError, match="insufficient_evidence"):
        promotion.allocate(
            conn, grant_id=grant8.grant_id, allocated_by="operator",
            reason="expand on nothing", rung=8, evidence=outcome.AssessmentEvidence(),
        )


def test_an_earned_expansion_records_the_evidence_it_consumed(conn):
    """§25.2 requires the reasons recorded at every rung — and `outcome.py`
    predicted this column set: "A table becomes worth adding when a *decision*
    consumes an assessment, because then what was known at decision time is
    itself a fact."

    The verdict is frozen onto the promotion rather than recomputed later,
    because the assessment moves as forecasts resolve and the decision does not.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    earned = _earned_rung_7(conn, cell, "a")
    grant = _grant(conn, cell, "a-8")

    record = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator",
        reason="earned expansion", rung=8, evidence=outcome.AssessmentEvidence(),
    )

    assert record.rung == 8
    assert record.supersedes_promotion_id == earned.promotion_id
    assert record.evidence_verdict == "supports_promotion"
    assert record.evidence_resolved_predictions == 3
    assert record.decided_automatically is False


def test_the_evidence_seam_cannot_be_asked_about_a_cell():
    """§9.3's move, applied to evidence: a signature that cannot see a Cell's
    general record cannot promote on a general impression.

    `PromotionEvidence.read` takes a `promotion_id` — a closed question about a
    named predecessor. A `cell_id` parameter would let an implementation answer
    "how is this Cell doing?", which is the scalar §10.2 forbids wearing a
    different name. Structural, because the behavioural version can only
    observe that today's implementation happens not to do it.
    """
    signature = inspect.signature(promotion.PromotionEvidence.read)
    assert "promotion_id" in signature.parameters
    assert "cell_id" not in signature.parameters

    fields = promotion.EvidenceReading.__dataclass_fields__
    assert "revenue_since_minor_units" not in fields, (
        "§10.3: Explorers need no immediate revenue — a gate that could see "
        "revenue is one a later edit will point at it"
    )


# --- §27.1: the decider is a separate axis from the rung ---------------------


def test_an_unattended_promotion_is_refused_while_the_flag_is_off(conn):
    """§0.4: "Nothing begins at real-money autonomy." §27.1 ships
    `auto_promotion` false, and an allocation that fires with no operator is
    §25.1 rung 9 whatever rung the money is at."""
    _seed(conn)
    cell = _cell(conn, "a")
    grant = _grant(conn, cell, "a")

    with pytest.raises(promotion.PromotionError, match="auto_promotion is disabled"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by=autopromotion.DECIDER,
            reason="unattended", decided_automatically=True,
        )


def test_auto_promotion_does_not_open_real_spending(conn):
    """ADR-026: real money needs two independent confirmations, and this slice
    must not collapse them into one.

    `auto_promotion` says "the colony may decide without me". `real_spending`
    says "the colony may move real money without me re-deciding the policy".
    A USD_REAL allocation needs both, so turning on the new flag alone changes
    nothing about real money.
    """
    _seed(conn)
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    cell = _cell(conn, "real-cell", book=Book.USD_REAL)
    promotion.fund_pool(
        conn, book=Book.USD_REAL, amount_minor_units=500,
        funding_account="seed_bank", idempotency_key="real-pool",
    )
    grant = _grant(conn, cell, "real")

    with pytest.raises(promotion.PromotionError, match="real_spending"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by=autopromotion.DECIDER,
            reason="unattended real", decided_automatically=True,
        )


def test_an_automatic_promotion_is_distinguishable_in_the_record(conn):
    """§2.6's autonomy-adjusted profit exists "to expose hidden human labour".

    The inverse matters just as much: an unattended allocation that recorded an
    operator's name would hide *machine* decisions inside a human's record, and
    nothing downstream could ever separate them again.
    """
    _seed(conn)
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    cell = _cell(conn, "a")
    grant = _grant(conn, cell, "a")

    record = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by=autopromotion.DECIDER,
        reason="unattended", decided_automatically=True,
    )

    assert record.decided_automatically is True
    assert record.allocated_by == autopromotion.DECIDER
    assert record.rung == 7, "the decider axis moved; the rung axis did not"


def test_rung_9_is_not_issuable_as_a_rung(conn):
    """§25.1 rung 9 is "bounded autonomy" — a different *decider*, not a bigger
    allocation. Issuing it as a rung would conflate the two axes this slice
    exists to separate, and would let a single number stand for both."""
    _seed(conn)
    cell = _cell(conn, "a")
    grant = _grant(conn, cell, "a")

    with pytest.raises(promotion.PromotionError, match="not issuable"):
        promotion.allocate(
            conn, grant_id=grant.grant_id, allocated_by="operator",
            reason="straight to autonomy", rung=9,
            evidence=outcome.AssessmentEvidence(),
        )


# --- the unattended engine ---------------------------------------------------


def test_the_sweep_does_nothing_while_the_flag_is_off(conn):
    """The engine's own gate, checked before it approves anything. A sweep that
    batch-approved and only then discovered it could not allocate would have
    already spent the operator's authority."""
    _seed(conn)
    cell = _cell(conn, "a")
    _grant(conn, cell, "a")

    result = autopromotion.sweep(conn)

    assert result.ran is False
    assert result.promotions == ()
    assert result.approved == ()


def test_the_sweep_records_what_it_refused(conn):
    """An unattended system that logged only its successes would look identical
    whether it was working or promoting everything. `skipped` is the record of
    the engine declining, and it is what makes an unattended run auditable."""
    _seed(conn, pool=10)  # too small for the 30-unit request
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    cell = _cell(conn, "a")
    _grant(conn, cell, "a")

    result = autopromotion.sweep(conn)

    assert result.ran is True
    assert result.promotions == ()
    assert len(result.skipped) == 1
    assert "promotion pool holds 10" in result.skipped[0][1]


def test_the_sweep_never_widens_batchable(conn):
    """§23.1 batches "low-risk reversible actions" and requires individual
    review otherwise; §23.4 makes batching the payload of a splitting attack.

    The engine approves by exactly one predicate — the kernel's own
    `batchable` — and a HIGH-tier request must survive a sweep untouched. An
    engine that cleared the backlog by relaxing its own eligibility is the
    failure §23.1's convenience turns into §23.4's vulnerability.
    """
    _seed(conn)
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    cell = _cell(conn, "a")
    deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(
            reply=json.dumps(
                {
                    "kind": "spend_request",
                    "summary": "a large risky request",
                    "rationale": "should never be swept",
                    "risk_tier": "CRITICAL",
                    "estimated_cost_minor_units": 5_000,
                    "predictions": [],
                },
                sort_keys=True,
            )
        ),
        wake_key="wake:risky",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )

    result = autopromotion.sweep(conn)

    assert result.approved == ()
    assert result.promotions == ()
    still_queued = [r.cell_id for r in approval.queue(conn)]
    assert cell.cell_id in still_queued, "a CRITICAL request must survive a sweep"


def test_the_sweep_climbs_to_rung_8_on_earned_evidence(conn):
    """The end-to-end property: a Cell that earned an expansion gets one with
    nobody in the loop, and the record says so on both axes."""
    _seed(conn)
    cell = _cell(conn, "a")
    earned = _earned_rung_7(conn, cell, "a")
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    _grant(conn, cell, "a-8")

    result = autopromotion.sweep(conn)

    assert result.ran is True
    assert result.rung_8_count == 1
    expansion = result.promotions[0]
    assert expansion.rung == 8
    assert expansion.decided_automatically is True
    assert expansion.supersedes_promotion_id == earned.promotion_id


def test_the_sweep_stays_at_rung_7_without_evidence(conn):
    """The same sweep, one fact changed: unresolved forecasts. An engine that
    climbed anyway would make the §25.2 gate decorative, and it would do so
    precisely when nobody was watching."""
    _seed(conn)
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    cell = _cell(conn, "a")
    _forecast(conn, cell, "unresolved", 0.9, key="u1")
    grant7 = _grant(conn, cell, "a-7")
    promotion.allocate(
        conn, grant_id=grant7.grant_id, allocated_by="operator", reason="rung 7"
    )
    _grant(conn, cell, "a-8")

    result = autopromotion.sweep(conn)

    assert result.rung_8_count == 0
    assert [p.rung for p in result.promotions] == [7]
