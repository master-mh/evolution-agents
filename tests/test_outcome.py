"""§25.2's read-back — did an allocation work? (SPEC.md §25.2, §8.5, §10.2, §10.3, §23.5)

Every test here is named for the property it defends. The recurring theme is
that the *obvious* measure of "did the money work" is wrong in a specific,
spec-identified way, and each test pins one of those.
"""

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mitosis import (
    approval,
    cli,
    db,
    deliberation,
    ledger,
    lifecycle,
    models,
    outcome,
    population,
    prediction,
    promotion,
    providers,
    revenue,
)
from mitosis.models import Book, CellType, EntrySpec


# --- fixtures ----------------------------------------------------------------


def _seed(conn):
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
        amount_minor_units=10_000,
        funding_account="seed_bank",
        idempotency_key="pool",
    )


def _cell(conn, tag):
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=200,
        book=Book.USD_SIM,
        idempotency_key=f"cell:{tag}",
    )
    for book, currency, amount in (
        (Book.USD_REAL, "USD", 50),
        (Book.RESOURCE, "RESOURCE", 5_000),
    ):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="cell_funding",
            idempotency_key=f"fund:{tag}:{book.value}",
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


def _allocate(conn, cell, tag, *, cost=30):
    """Propose -> approve -> allocate. The only route capital reaches a Cell."""
    deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(
            reply=json.dumps(
                {
                    "kind": "spend_request",
                    "summary": f"test request {tag}",
                    "rationale": "exists to produce a promotion to assess",
                    "risk_tier": "MEDIUM",
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
    request = next(r for r in approval.queue(conn) if r.cell_id == cell.cell_id)
    grant = approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="test approval"
    )
    return promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="test allocation"
    )


def _resolve_all(conn, forecasts, *, occurred=True, source="test"):
    for item in forecasts:
        prediction.resolve(conn, item.prediction_id, occurred=occurred, source=source)


# --- which forecasts count (§25.2 "predicted vs observed", §23.5) ------------


def test_forecasts_registered_after_funding_never_reach_the_verdict(conn):
    """§23.5: the review path "will be optimised against by Cells".

    The cheapest optimisation available to a Cell that has just been handed
    money is a pile of easy claims registered immediately afterwards. If those
    counted, a Cell could manufacture a promotion-supporting record on demand
    and the ladder would measure nothing.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    open_at_funding = _forecast(conn, cell, "the real claim", 0.7, key="p0")
    record = _allocate(conn, cell, "a")

    easy = [
        _forecast(conn, cell, f"trivially true {i}", 0.99, key=f"easy{i}") for i in range(5)
    ]
    _resolve_all(conn, easy, occurred=True)

    result = outcome.assess(conn, record.promotion_id)

    assert result.forecasts_open_at_funding == 1
    assert result.forecasts_made_while_funded == 5
    assert result.forecasts_made_while_funded_resolved == 5
    # The five perfect scores are visible and excluded.
    assert result.mean_brier_made_while_funded == pytest.approx(0.0001)
    assert result.observed_mean_brier is None
    assert result.verdict is outcome.Verdict.INSUFFICIENT_EVIDENCE

    # And resolving the one that actually counts still cannot reach a verdict
    # on its own — the funding set is what it is.
    prediction.resolve(conn, open_at_funding.prediction_id, occurred=True, source="test")
    assert (
        outcome.assess(conn, record.promotion_id).verdict
        is outcome.Verdict.INSUFFICIENT_EVIDENCE
    )


def test_a_forecast_already_resolved_at_funding_is_not_observed_outcome(conn):
    """§25.2 asks for predicted vs **observed** outcome at the rung.

    An outcome the approver could already read is part of the record that
    *justified* the funding, not evidence about what the funding achieved.
    Counting it twice would let a Cell coast into rung 8 on the same three
    resolutions that won it rung 7.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    already = [_forecast(conn, cell, f"old {i}", 0.9, key=f"old{i}") for i in range(3)]
    _resolve_all(conn, already, occurred=True)
    record = _allocate(conn, cell, "a")

    result = outcome.assess(conn, record.promotion_id)

    assert result.forecasts_open_at_funding == 0
    assert result.forecasts_resolved_since == 0
    # It is still the baseline the promotion was granted on, which is the
    # separate job the promotion snapshot does.
    assert result.funded_mean_brier == pytest.approx(0.01)
    assert result.verdict is outcome.Verdict.INSUFFICIENT_EVIDENCE


# --- the cherry-picking guard (§8.5) -----------------------------------------


def test_an_overdue_funding_forecast_blocks_a_verdict_despite_perfect_scores(conn):
    """§8.5's register is worthless if a Cell's losers can simply stay open.

    `prediction.py`: "a mean Brier score over three cherry-picked resolutions is
    worse than useless". This is the test that makes that true here — three
    excellent resolutions plus one outcome nobody recorded past its deadline
    must not produce support, because the missing one is exactly where a bad
    outcome would hide.

    If this fails, the read-back can be passed by resolving winners and
    forgetting losers, which is the single cheapest way to game the ladder.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    winners = [_forecast(conn, cell, f"winner {i}", 0.95, key=f"w{i}") for i in range(3)]
    _forecast(conn, cell, "the one nobody resolves", 0.95, days=1, key="loser")
    record = _allocate(conn, cell, "a")
    _resolve_all(conn, winners, occurred=True)

    # Before the loser is due, the three resolutions stand on their own.
    before = outcome.assess(conn, record.promotion_id)
    assert before.verdict is outcome.Verdict.SUPPORTS_PROMOTION
    assert before.forecasts_overdue == 0

    after = outcome.assess(
        conn, record.promotion_id, now=datetime.now(timezone.utc) + timedelta(days=3)
    )
    assert after.verdict is outcome.Verdict.EVIDENCE_WITHHELD
    assert after.forecasts_overdue == 1
    # The excellent mean is still computed and still reported — it is the
    # *verdict* that refuses to rest on it.
    assert after.observed_mean_brier == pytest.approx(0.0025)


def test_evidence_withheld_is_distinct_from_insufficient_evidence(conn):
    """Both mean "no verdict"; the remedies are opposite.

    Insufficient needs time. Withheld needs someone to go and resolve what is
    outstanding — and since resolution is operator-supplied (`prediction.py`),
    a withheld verdict is a finding about the evidence, not an accusation
    against the Cell. Collapsing them into one "unknown" hides which.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    _forecast(conn, cell, "not due for a while", 0.7, days=30, key="slow")
    record = _allocate(conn, cell, "a")

    assert (
        outcome.assess(conn, record.promotion_id).verdict
        is outcome.Verdict.INSUFFICIENT_EVIDENCE
    )
    assert (
        outcome.assess(
            conn, record.promotion_id, now=datetime.now(timezone.utc) + timedelta(days=40)
        ).verdict
        is outcome.Verdict.EVIDENCE_WITHHELD
    )


# --- sample size -------------------------------------------------------------


def test_two_resolutions_cannot_earn_a_rung_and_three_can(conn):
    """§25.1 exists to stop a rung being won by luck.

    Asserted against literal counts rather than `MIN_RESOLVED_FOR_A_VERDICT`,
    because a test written as `>= MIN_RESOLVED` is satisfied by editing the
    constant — it would pass with the threshold set to 1, which is the bug it is
    supposed to catch.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    forecasts = [_forecast(conn, cell, f"claim {i}", 0.95, key=f"p{i}") for i in range(3)]
    record = _allocate(conn, cell, "a")

    _resolve_all(conn, forecasts[:2], occurred=True)
    two = outcome.assess(conn, record.promotion_id)
    assert two.forecasts_resolved_since == 2
    assert two.verdict is outcome.Verdict.INSUFFICIENT_EVIDENCE
    assert not two.is_decided

    _resolve_all(conn, forecasts[2:], occurred=True)
    three = outcome.assess(conn, record.promotion_id)
    assert three.forecasts_resolved_since == 3
    assert three.verdict is outcome.Verdict.SUPPORTS_PROMOTION


# --- calibration, as two dimensions that must not collapse (§10.2, §8.5) -----


def test_degraded_calibration_withholds_support_even_while_beating_chance(conn):
    """§8.5: "High simulated performance with a high reality gap reduces
    promotion confidence."

    This is the case that proves the two calibration dimensions are genuinely
    independent (§10.2: "do not collapse all dimensions into one scalar"). The
    Cell's observed Brier of 0.09 comfortably beats the 0.25 uninformative bar,
    so an absolute-only verdict would support promotion — but it was funded on a
    record of 0.01 and has got four times worse. If this fails, the reality gap
    has been folded into the absolute bar and §8.5 is no longer enforced.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    sharp = [_forecast(conn, cell, f"sharp {i}", 0.9, key=f"s{i}") for i in range(3)]
    _resolve_all(conn, sharp, occurred=True)  # Brier 0.01
    funding_set = [_forecast(conn, cell, f"funded {i}", 0.7, key=f"f{i}") for i in range(3)]
    record = _allocate(conn, cell, "a")
    _resolve_all(conn, funding_set, occurred=True)  # Brier 0.09

    result = outcome.assess(conn, record.promotion_id)

    assert result.observed_mean_brier == pytest.approx(0.09)
    assert result.observed_mean_brier < 0.25  # would pass an absolute-only test
    assert result.funded_mean_brier == pytest.approx(0.01)
    assert result.reality_gap == pytest.approx(0.08)
    assert result.verdict is outcome.Verdict.DOES_NOT_SUPPORT_PROMOTION
    assert any("reality gap" in reason for reason in result.reasons)


def test_improved_calibration_supports_promotion(conn):
    """The mirror image: a Cell that got sharper after funding."""
    _seed(conn)
    cell = _cell(conn, "a")
    sloppy = [_forecast(conn, cell, f"sloppy {i}", 0.6, key=f"s{i}") for i in range(3)]
    _resolve_all(conn, sloppy, occurred=True)  # Brier 0.16
    funding_set = [_forecast(conn, cell, f"funded {i}", 0.95, key=f"f{i}") for i in range(3)]
    record = _allocate(conn, cell, "a")
    _resolve_all(conn, funding_set, occurred=True)  # Brier 0.0025

    result = outcome.assess(conn, record.promotion_id)

    assert result.reality_gap == pytest.approx(-0.1575)
    assert result.verdict is outcome.Verdict.SUPPORTS_PROMOTION
    assert result.next_rung == 8


def test_calibration_no_better_than_chance_withholds_support(conn):
    """The absolute dimension, for a Cell with no prior record to degrade from.

    A confident-and-wrong forecaster scores 0.81 against the 0.25 a coin scores.
    With `funded_mean_brier` NULL there is no reality gap to catch this, so the
    absolute bar is the only thing standing between it and a rung.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    forecasts = [_forecast(conn, cell, f"wrong {i}", 0.9, key=f"p{i}") for i in range(3)]
    record = _allocate(conn, cell, "a")
    _resolve_all(conn, forecasts, occurred=False)

    result = outcome.assess(conn, record.promotion_id)

    assert result.funded_mean_brier is None
    assert result.reality_gap is None
    assert result.observed_mean_brier == pytest.approx(0.81)
    assert result.verdict is outcome.Verdict.DOES_NOT_SUPPORT_PROMOTION


# --- §10.3: revenue is recorded, never judged --------------------------------


def test_revenue_is_recorded_but_never_changes_the_verdict(conn):
    """§10.3: "Explorers need no immediate revenue."

    A verdict that asked whether the grant earned its money back would reject
    every Explorer in the colony — which is most of it, and precisely the Cells
    §10.3 protects. §25.2 asks for cost to be *recorded*, not gated on. If this
    fails, the ladder has quietly become a profit test and Explorers can no
    longer climb it.
    """
    _seed(conn)
    earner, pauper = _cell(conn, "earner"), _cell(conn, "pauper")
    records = {}
    for cell, tag in ((earner, "earner"), (pauper, "pauper")):
        forecasts = [
            _forecast(conn, cell, f"{tag} claim {i}", 0.95, key=f"{tag}{i}") for i in range(3)
        ]
        records[tag] = _allocate(conn, cell, tag)
        _resolve_all(conn, forecasts, occurred=True)

    revenue.record_revenue(
        conn,
        cell_id=earner.cell_id,
        amount_minor_units=500,
        book=Book.USD_SIM,
        source="a paying customer",
        idempotency_key="rev",
    )

    rich = outcome.assess(conn, records["earner"].promotion_id)
    poor = outcome.assess(conn, records["pauper"].promotion_id)

    assert rich.revenue_since_minor_units == 500
    assert poor.revenue_since_minor_units == 0
    assert rich.net_contribution_minor_units == 500
    assert poor.net_contribution_minor_units == 0
    assert rich.verdict is poor.verdict is outcome.Verdict.SUPPORTS_PROMOTION


# --- §25.2 "cost", measured over the right window ----------------------------


def _consume(conn, cell, amount, key):
    """A Cell paying the colony for metered compute — `infrastructure_reserve`
    is a spend destination, so this is consumption in the Cell's own book."""
    ledger.post_transaction(
        conn,
        book=cell.book,
        currency="USD",
        transaction_type="resource_settlement",
        idempotency_key=key,
        description="metered compute the Cell consumed",
        entries=[
            EntrySpec(
                account_id=f"cell:{cell.cell_id}:cash",
                amount_minor_units=-amount,
                cell_id=cell.cell_id,
            ),
            EntrySpec(
                account_id="infrastructure_reserve",
                amount_minor_units=amount,
                cell_id=cell.cell_id,
            ),
        ],
    )


def test_cost_is_measured_from_the_funding_instant(conn):
    """§25.2 asks what this *rung* cost, not what the Cell has ever cost.

    A Cell's whole pre-promotion history would swamp the figure, and a Cell that
    was expensive before funding and frugal after would read as wasteful — which
    is the reading that decides whether it climbs.

    Both sides are asserted on purpose. An earlier version of this test spent
    only *before* funding and only in a different book from the Cell's, so the
    windowed and lifetime figures were both 0 and it passed against a
    deliberately broken `assess` that ignored the window entirely.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    _consume(conn, cell, 40, "before")
    record = _allocate(conn, cell, "a")
    _consume(conn, cell, 10, "after")

    lifetime = ledger.spend_by_book(conn, cell.cell_id)
    since = ledger.spend_by_book(conn, cell.cell_id, since=record.created_at_utc)
    assert lifetime[cell.book.value] == 50
    assert since[cell.book.value] == 10

    result = outcome.assess(conn, record.promotion_id)
    assert result.spend_since_minor_units == 10, "the 40 spent before funding is not this rung's"
    assert result.allocated_minor_units == 30
    assert result.unspent_minor_units == 20


def test_liability_reports_unmodelled_rather_than_zero(conn):
    """§25.2 lists liability; §13's reserve is Phase 6+.

    A fabricated 0 reads as "this rung carried no liability", which is a much
    stronger claim than "nothing here models liability yet" — and it is the kind
    of claim a promotion decision would be made on.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    record = _allocate(conn, cell, "a")

    assert outcome.assess(conn, record.promotion_id).liability_minor_units is None


# --- §25.2 "human intervention" ----------------------------------------------


def test_the_allocation_itself_is_not_counted_as_supervision(conn):
    """The act of funding is not supervision *of* the funded period.

    `capital_allocated` is stamped microseconds after the promotion row, so a
    naive "audit events since funding" filter counts it — inflating every
    assessment by exactly one and making a Cell that needed no attention at all
    look like it needed some. §25.2's human-intervention figure feeding §27.1's
    "human minutes/artifact" is why an off-by-one here matters.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    record = _allocate(conn, cell, "a")

    result = outcome.assess(conn, record.promotion_id)

    assert result.human_interventions == 0
    assert "capital_allocated" not in result.intervention_kinds
    # The allocation event does exist; it is being excluded, not missing.
    allocated = conn.execute(
        "SELECT COUNT(*) AS n FROM audit_events WHERE event_type = 'capital_allocated'"
    ).fetchone()["n"]
    assert allocated == 1


def test_operator_resolutions_count_as_human_intervention(conn):
    """§25.2's "human intervention", and §8.5's register does not resolve itself.

    Every outcome in the register was typed in by someone. That is real human
    minutes spent supervising this Cell, and it is the figure §27.1's phase-8
    metric ("human minutes/artifact") is built from.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    forecasts = [_forecast(conn, cell, f"claim {i}", 0.9, key=f"p{i}") for i in range(3)]
    record = _allocate(conn, cell, "a")
    _resolve_all(conn, forecasts, occurred=True)

    result = outcome.assess(conn, record.promotion_id)

    assert result.intervention_kinds == {"prediction_resolved": 3}
    assert result.human_interventions == 3


def test_colony_wide_operator_actions_are_not_charged_to_one_cell(conn):
    """Funding the pool is human minutes belonging to no Cell.

    Charging it to whichever Cell happened to be funded next would make that
    Cell look expensive to supervise for work done on the colony's behalf.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    record = _allocate(conn, cell, "a")
    promotion.fund_pool(
        conn,
        book=Book.USD_SIM,
        amount_minor_units=100,
        funding_account="seed_bank",
        idempotency_key="pool-again",
    )

    assert outcome.assess(conn, record.promotion_id).human_interventions == 0


# --- transfer degradation ----------------------------------------------------


def test_transfer_degradation_is_the_realised_reality_gap(conn):
    """§25.2's transfer degradation, measured instead of estimated.

    `promotions.transfer_degradation` is computed at funding from whatever the
    Cell's lifetime record happened to be. The read-back replaces the estimate
    with the thing itself: how much worse the strategy did at this rung than the
    record it was promoted on.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    sharp = [_forecast(conn, cell, f"sharp {i}", 0.9, key=f"s{i}") for i in range(3)]
    _resolve_all(conn, sharp, occurred=True)
    funding_set = [_forecast(conn, cell, f"funded {i}", 0.7, key=f"f{i}") for i in range(3)]
    record = _allocate(conn, cell, "a")
    _resolve_all(conn, funding_set, occurred=True)

    result = outcome.assess(conn, record.promotion_id)
    assert result.transfer_degradation == result.reality_gap == pytest.approx(0.08)


# --- the ladder stays where it is (§25.1, §10.5) -----------------------------


def test_no_kernel_path_acts_on_an_assessment():
    """§25.1 rung 8 and §10.5's death bar, both enforced structurally.

    Two directions have to stay closed, and neither is closed by anything in
    `outcome.py` itself — only by nothing else reaching it.

    **Upward:** rung 8 ("expanded pilot") means removing one of the two humans
    standing in every allocation. A verdict of `supports_promotion` that some
    module read and acted on would take that step without anyone arguing for
    it. This is the successor to ADR-027's rung-6 guarantee and ADR-029's rung-7
    one, and like them it is meant to make the next step cost an explicit edit
    to a named test rather than slip in as a plausible commit.

    **Downward, and harder:** §10.5 requires that "estimated negative EV alone
    must not kill a Cell" without strong evidence *and* an independent Auditor
    concurring. No Auditor Cell exists (§23.2's standing hole), so
    `death.py` must not be able to see a `does_not_support_promotion` verdict at
    all — a kernel that culls on this would be culling on exactly the estimate
    §10.5 names.
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    # The CLI reports assessments to a human, and the golden run replays one.
    # Neither acts on a verdict.
    allowed = {"outcome.py", "cli.py", "golden.py"}

    consumers = sorted(
        path.name
        for path in source_dir.glob("*.py")
        if path.name not in allowed and "outcome" in _imported_modules(path)
    )
    assert not consumers, (
        f"{consumers} imports the §25.2 read-back. Acting on a verdict is a step up "
        "§25.1's ladder (upward) or a §10.5 violation (downward); either way it "
        "needs an argument, not an import"
    )

    # Named individually, because these three are the ones where the step would
    # look most reasonable at the moment someone took it.
    for forbidden, why in (
        ("death.py", "§10.5 forbids killing on an estimate without a concurring Auditor"),
        ("scheduler.py", "a promotion that fires on a timer is rung 9, not rung 8"),
        ("promotion.py", "an allocation that reads its own verdict is a self-promoting loop"),
    ):
        assert "outcome" not in _imported_modules(source_dir / forbidden), (
            f"{forbidden} must never reach the assessment: {why}"
        )


def _imported_modules(path: Path) -> set[str]:
    """Module names `path` imports, including inside functions.

    An AST walk rather than a text search, because "outcome" is ordinary prose
    all over this codebase (§8.5 is about outcomes) and a column name in the
    prediction register — a substring test would flag a dozen modules that never
    touch this one, and a test that cries wolf gets deleted.
    """
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.update(node.module.split("."))
            if node.level:  # `from . import outcome`
                imported.update(alias.name for alias in node.names)
    return imported


def test_assessing_writes_nothing(conn):
    """Derived, never stored — the posture Charter C3 takes toward balances.

    An assessment that wrote a row would create a second version of a fact the
    prediction register already holds canonically, and the two could disagree.
    Migration 0016 gives exactly this reason for snapshotting calibration rather
    than copying predictions.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    forecasts = [_forecast(conn, cell, f"claim {i}", 0.9, key=f"p{i}") for i in range(3)]
    record = _allocate(conn, cell, "a")
    _resolve_all(conn, forecasts, occurred=True)

    before = "\n".join(conn.iterdump())
    outcome.assess(conn, record.promotion_id)
    outcome.assess_all(conn)
    after = "\n".join(conn.iterdump())

    assert before == after
    assert "assessments" not in {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


# --- surface -----------------------------------------------------------------


def test_an_unknown_promotion_is_refused(conn):
    _seed(conn)
    with pytest.raises(outcome.OutcomeError, match="no such promotion"):
        outcome.assess(conn, "not-a-promotion")


def test_assess_all_covers_every_promotion_and_filters_by_cell(conn):
    _seed(conn)
    first, second = _cell(conn, "one"), _cell(conn, "two")
    records = [_allocate(conn, first, "one"), _allocate(conn, second, "two")]

    assert [r.promotion_id for r in outcome.assess_all(conn)] == [
        r.promotion_id for r in records
    ]
    scoped = outcome.assess_all(conn, cell_id=second.cell_id)
    assert [r.promotion_id for r in scoped] == [records[1].promotion_id]


def test_every_human_intervention_event_type_is_cell_scoped(conn):
    """`HUMAN_INTERVENTION_EVENTS` classifies by event type because
    `audit_events` has no actor column. An entry whose emitter never sets
    `cell_id` would be silently uncountable — present in the table, attributable
    to nobody, and quietly worth zero forever.
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    sources = "\n".join(path.read_text() for path in source_dir.glob("*.py"))
    for event_type in outcome.HUMAN_INTERVENTION_EVENTS:
        assert f'event_type="{event_type}"' in sources, (
            f"{event_type} is classified as human intervention but nothing emits it"
        )


# --- CLI ---------------------------------------------------------------------


def test_assess_cli_reports_every_field_the_spec_lists(tmp_path, capsys):
    """§25.2 enumerates seven things to record at each rung. The operator-facing
    verb is where they actually have to appear."""
    db_path = tmp_path / "colony.db"
    cli.main(["--db", str(db_path), "init"])
    conn = db.connect_and_migrate(db_path)
    _seed(conn)
    cell = _cell(conn, "a")
    forecasts = [_forecast(conn, cell, f"claim {i}", 0.9, key=f"p{i}") for i in range(3)]
    record = _allocate(conn, cell, "a")
    _resolve_all(conn, forecasts, occurred=True)
    conn.close()
    capsys.readouterr()

    assert cli.main(["--db", str(db_path), "assess", record.promotion_id]) == 0
    out = capsys.readouterr().out

    assert "SUPPORTS_PROMOTION" in out
    for fragment in (
        "predicted vs observed",
        "reality gap",
        "transfer degradation",
        "cost since funding",
        "liability:",
        "human intervention:",
        "not modelled",
    ):
        assert fragment in out, f"§25.2's {fragment!r} is missing from the report"
    # It reports; it does not promote.
    assert "supports considering rung 8" in out


def test_assessments_cli_lists_and_handles_an_empty_colony(tmp_path, capsys):
    db_path = tmp_path / "colony.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    assert cli.main(["--db", str(db_path), "assessments"]) == 0
    assert "No promotions to assess." in capsys.readouterr().out

    conn = db.connect_and_migrate(db_path)
    _seed(conn)
    record = _allocate(conn, _cell(conn, "a"), "a")
    conn.close()
    capsys.readouterr()

    assert cli.main(["--db", str(db_path), "assessments", "--verbose"]) == 0
    out = capsys.readouterr().out
    assert record.promotion_id in out
    assert "insufficient_evidence" in out


def test_assess_cli_refuses_an_unknown_promotion(tmp_path, capsys):
    db_path = tmp_path / "colony.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    assert cli.main(["--db", str(db_path), "assess", "nope"]) == 1
    assert "no such promotion" in capsys.readouterr().err
