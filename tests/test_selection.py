"""§13.2's selector: hard gates, then a Pareto frontier (SPEC.md §13.2, §13.1,
§10.2, §10.5, §11.2, §23.4, §23.5, §25.2).

Every test is named for the property it defends. Two themes recur. The first is
that a dimension nobody can measure must *abstain* rather than score zero — a
zero is a claim about the candidate, and four of §13.2's nine dimensions have no
data in this kernel. The second is that a selector is the most tempting place in
an evolutionary system to smuggle in a scalar, and §13.2 and §10.2 both forbid
one.
"""

import ast
import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mitosis import (
    approval,
    content_audit,
    deliberation,
    ledger,
    lifecycle,
    models,
    population,
    prediction,
    promotion,
    providers,
    selection,
)
from mitosis.models import Book, CellType, EntrySpec
from mitosis.proposal import ProposalKind


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


def _cell(conn, tag, genome_content=None, cell_type=CellType.EXPLORER):
    cell = lifecycle.create_cell(
        conn,
        cell_type=cell_type,
        budget_minor_units=200,
        book=Book.USD_SIM,
        idempotency_key=f"cell:{tag}",
        genome_content=genome_content,
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
            description="a Cell pays for its own thinking",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-amount,
                          cell_id=cell.cell_id),
                EntrySpec(account_id=f"cell:{cell.cell_id}:cash", amount_minor_units=amount,
                          cell_id=cell.cell_id),
            ],
        )
    return cell


def _candidate(conn, cell, tag, *, cost=30, forecasts=()):
    """Propose -> approve, and stop. An approved, unallocated grant is exactly
    what `promotion.allocatable_grants` offers and what §13.2 selects among."""
    deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(
            reply=json.dumps(
                {
                    "kind": "spend_request",
                    "summary": f"test request {tag}",
                    "rationale": "exists to be selected among",
                    "risk_tier": "MEDIUM",
                    "estimated_cost_minor_units": cost,
                    "predictions": [
                        {"claim": f"{tag} claim {i}", "probability": p, "horizon_days": 30}
                        for i, p in enumerate(forecasts)
                    ],
                },
                sort_keys=True,
            )
        ),
        wake_key=f"wake:{tag}",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    request = next(r for r in approval.queue(conn)
                   if r.cell_id == cell.cell_id and not _decided(conn, r.request_id))
    return approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="test approval"
    )


def _experiment_candidate(conn, cell, tag, *, cost=40):
    """An approved, unconsumed experiment grant — §13's other candidate kind."""
    deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(
            reply=json.dumps(
                {
                    "kind": "experiment",
                    "summary": f"test experiment {tag}",
                    "rationale": "exists to be selected among",
                    "risk_tier": "MEDIUM",
                    "estimated_cost_minor_units": cost,
                    "experiment": {"hypothesis": f"{tag} hypothesis under test"},
                    "predictions": [],
                },
                sort_keys=True,
            )
        ),
        wake_key=f"wake:{tag}",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    request = next(r for r in approval.queue(conn)
                   if r.cell_id == cell.cell_id and not _decided(conn, r.request_id))
    return approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="test approval"
    )


def _decided(conn, request_id):
    row = conn.execute("SELECT status FROM approval_requests WHERE request_id = ?",
                       (request_id,)).fetchone()
    return row is not None and row["status"] != "pending"


def _resolved_forecasts(conn, cell, probability, occurred, count=3):
    for i in range(count):
        item = prediction.register(
            conn,
            cell_id=cell.cell_id,
            claim=f"standing claim {i}",
            probability=probability,
            resolves_by=datetime.now(timezone.utc) + timedelta(days=30),
            idempotency_key=f"standing:{cell.cell_id}:{i}",
        )
        prediction.resolve(conn, item.prediction_id, occurred=occurred, source="test")


def _for(frontier, grant):
    return next(c for c in frontier.candidates if c.grant_id == grant.grant_id)


NO_CONCERN_REPLY = json.dumps(
    {"verdict": "no_concern", "summary": "genuinely combinatorial", "probability": 0.8},
    sort_keys=True,
)
CONCERN_REPLY = json.dumps(
    {"verdict": "concern", "summary": "reads as ordinary freelancing", "probability": 0.2},
    sort_keys=True,
)


def _audited_cell(conn, tag, *, reply, occurred, resolve=True):
    """A candidate Cell whose genome has one resolved (or pending, if
    `resolve=False`) `content_audit.py` judgment — an independent Auditor Cell
    (its own lineage, `_cell` never reproduces) judges the subject's genome,
    and the caller decides whether that prediction gets resolved and to what
    outcome, matching `_resolved_forecasts`' shape for the evidence-quality
    gate."""
    subject = _cell(conn, tag, genome_content={
        "market": f"{tag} bookshops", "problem": "stock decisions are guesswork",
        "product": "a weekly stock digest", "revenue_model": "monthly subscription per shop",
        "acquisition_channel": "trade newsletters", "workflow": "ingest, rank, publish",
    })
    reviewer = _cell(conn, f"{tag}-auditor", cell_type=CellType.AUDITOR)
    audit = content_audit.audit_genome(
        conn,
        genome_hash=subject.genome_hash,
        auditor_cell_id=reviewer.cell_id,
        provider=providers.MockProvider(reply=reply),
        model="mock-1",
    )
    if resolve:
        prediction.resolve(conn, audit.prediction_id, occurred=occurred, source="test")
    return subject


# --- the clause's own list (§13.2) -------------------------------------------


def test_every_dimension_the_clause_names_is_classified():
    """§13.2 names nine things; each must be a gate or a frontier axis.

    If this fails, a dimension is sitting in the module with nobody having
    decided whether it can remove a candidate — the difference between "reject
    below a minimum threshold" and "select from a Pareto frontier", which is the
    whole structure of the clause. Same forcing shape as
    `accounts.unclassified_accounts()`.
    """
    assert selection.unclassified_dimensions() == set()
    overlap = set(selection.GATE_DIMENSIONS) & set(selection.FRONTIER_DIMENSIONS)
    assert not overlap, f"{overlap} is both a gate and a frontier axis"
    assert len(selection.GATE_DIMENSIONS) == 4
    assert len(selection.FRONTIER_DIMENSIONS) == 5


def test_every_proposal_kind_is_a_candidate_or_carries_a_reason_it_is_not():
    """A seventh kind must not become a candidate by falling through a filter.

    `NON_CANDIDATE_SENSE` holds a reason per excluded kind rather than letting
    the exclusion be the silent complement of a set — the same forcing shape as
    `accounts.unclassified_accounts()` and `genome.unclassified_fields()`.
    """
    assert selection.unclassified_kinds() == set()
    assert not selection.CANDIDATE_KINDS & set(selection.NON_CANDIDATE_SENSE)
    assert ProposalKind.EXPERIMENT in selection.CANDIDATE_KINDS


def test_an_approved_experiment_is_a_candidate_and_a_tool_request_is_not(conn):
    """§13.1's formula is written about an *experiment's* cost.

    `promotion.allocatable_grants` filters to spend requests, because it answers
    a capital-pool question. Selecting from that list would have left §13.2's own
    cost dimension measuring only the kind §13.1 was not named for. A tool
    request asks for a capability instead, which is §0.4's question and not §13's.
    """
    _seed(conn)
    cell = _cell(conn, "experimenter")
    grant = _experiment_candidate(conn, cell, "exp", cost=40)

    assert promotion.allocatable_grants(conn) == []
    frontier = selection.evaluate(conn)
    assert [c.grant_id for c in frontier.candidates] == [grant.grant_id]
    assert selection.NON_CANDIDATE_SENSE[ProposalKind.TOOL_REQUEST]


def test_a_dimension_with_no_data_abstains_rather_than_scoring_zero(conn):
    """Four of the nine cannot be measured here, and a zero would be a lie.

    `structural_novelty = 0.0` reads as "this idea is not novel"; the truth is
    that §31's novelty archive does not exist. §2.6's report and ADR-042/043
    settled this shape — an unmeasurable dimension reports unmeasurable.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    _candidate(conn, cell, "a")
    frontier = selection.evaluate(conn)
    candidate = frontier.candidates[0]

    axis = candidate.axis("economic_potential")
    assert axis.value is None, f"economic_potential scored {axis.value} with no rule over it"
    assert axis.reason

    # `structural_novelty` is measurable in general (ADR-060) and abstains here
    # for a *different* reason — this Cell carries the colony's first genome.
    # Asserting only "is None" would have kept passing if the axis were deleted.
    founder_axis = candidate.axis("structural_novelty")
    assert founder_axis.value is None
    assert "nothing earlier" in founder_axis.reason

    for name in ("reproducibility", "software_native_advantage"):
        gate = next(g for g in candidate.gates if g.dimension == name)
        assert gate.outcome is selection.GateOutcome.UNMEASURABLE
        assert gate.reason

    assert set(frontier.unmeasured_dimensions) >= {"structural_novelty", "economic_potential"}


def test_unmeasurable_and_unevaluable_are_not_the_same_answer(conn):
    """A new Cell and a missing subsystem are different problems.

    `UNEVALUABLE` means this candidate has no record yet and a later run could
    fix it; `UNMEASURABLE` means no candidate could be scored because the data
    exists nowhere. A single "unknown" would hide which of the two a build can
    resolve — the same reason §25.2 splits `INSUFFICIENT_EVIDENCE` from
    `EVIDENCE_WITHHELD`.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    _candidate(conn, cell, "a")
    gates = {g.dimension: g.outcome for g in selection.evaluate(conn).candidates[0].gates}
    assert gates["evidence_quality"] is selection.GateOutcome.UNEVALUABLE
    assert gates["reproducibility"] is selection.GateOutcome.UNMEASURABLE


# --- gates (§13.2 "reject candidates below minimum thresholds") --------------


def test_a_cell_with_no_record_is_unevaluable_and_never_rejected(conn):
    """§9.4's founder problem, manufactured by the selector if this breaks.

    A gate that rejected an unmeasured Cell would reject every Cell the colony
    has just born, leaving only incumbents fundable. `death._has_realised_record`
    names the same trap from the other side: an unmeasured Cell is not inferior,
    it is unmeasured.
    """
    _seed(conn)
    cell = _cell(conn, "newborn")
    grant = _candidate(conn, cell, "newborn")
    candidate = _for(selection.evaluate(conn), grant)
    assert candidate.passes_gates
    assert candidate.grant_id in selection.evaluate(conn).frontier_grant_ids


def test_a_forecaster_worse_than_a_coin_flip_fails_the_evidence_gate(conn):
    """§13.2's "minimum threshold on evidence quality", set by the scoring rule.

    The bar is `prediction.UNINFORMATIVE_BRIER` — what a forecaster who knows
    nothing scores. Below it the Cell is not merely uncertain, it is
    anti-correlated with reality. Setting the bar anywhere else (a percentile, a
    mean over peers) would make it a tuning knob rather than a property of Brier.
    """
    _seed(conn)
    cell = _cell(conn, "confident-and-wrong")
    _resolved_forecasts(conn, cell, probability=0.95, occurred=False)
    grant = _candidate(conn, cell, "confident-and-wrong")

    candidate = _for(selection.evaluate(conn), grant)
    assert candidate.rejected_by == ("evidence_quality",)
    assert candidate.grant_id not in selection.evaluate(conn).frontier_grant_ids


def test_a_well_calibrated_forecaster_passes_the_same_gate(conn):
    """The other half of the previous test: the gate must be able to pass.

    Without this, a gate that rejected everything would look identical to one
    that worked — the vacuity failure this repo keeps finding in its own guards.
    """
    _seed(conn)
    cell = _cell(conn, "calibrated")
    _resolved_forecasts(conn, cell, probability=0.95, occurred=True)
    grant = _candidate(conn, cell, "calibrated")
    candidate = _for(selection.evaluate(conn), grant)
    gate = next(g for g in candidate.gates if g.dimension == "evidence_quality")
    assert gate.outcome is selection.GateOutcome.PASSED
    assert candidate.passes_gates


def test_a_quarantined_cell_is_rejected_on_policy_compliance(conn):
    """§18's taint, read as §13.2's policy-compliance threshold.

    A quarantine is a recorded finding about something that already happened,
    not the "estimated negative EV" §10.5 forbids acting on — so rejecting a
    candidate for it is a fact, not a forecast.
    """
    _seed(conn)
    cell = _cell(conn, "tainted")
    grant = _candidate(conn, cell, "tainted")
    lifecycle.quarantine(conn, cell.cell_id, reason="policy violation under test")

    candidate = _for(selection.evaluate(conn), grant)
    assert "policy_compliance" in candidate.rejected_by


def test_understated_risk_does_not_reject_but_an_escalating_signal_does(conn):
    """§23.4's asymmetry, reused rather than re-derived.

    `approval.py` excludes `understated_risk` from `_ESCALATING_SIGNALS` because
    it is derived from the kernel's own assessment — letting it escalate would
    make a finding raise the bar it was measured against. A selector that gated
    on it would reintroduce exactly that circularity one layer up.
    """
    _seed(conn)
    cell = _cell(conn, "signalled")
    grant = _candidate(conn, cell, "signalled")

    conn.execute(
        "INSERT INTO approval_signals (signal_id, request_id, signal, detail, created_at_utc) "
        "VALUES (?, ?, ?, ?, ?)",
        ("sig-understated", grant.request_id, approval.SIGNAL_UNDERSTATED_RISK,
         "claimed LOW", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    assert "policy_compliance" not in _for(selection.evaluate(conn), grant).rejected_by

    conn.execute(
        "INSERT INTO approval_signals (signal_id, request_id, signal, detail, created_at_utc) "
        "VALUES (?, ?, ?, ?, ?)",
        ("sig-repeat", grant.request_id, approval.SIGNAL_REPEAT_AFTER_REJECTION,
         "asked again after a rejection", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    assert "policy_compliance" in _for(selection.evaluate(conn), grant).rejected_by


def test_a_content_audit_that_holds_up_passes_the_software_native_advantage_gate(conn):
    """§13.3, read from a *resolved* `content_audit.py` judgment.

    The claim an Auditor scores is "genuinely §13.3"; resolving it `True` is a
    realised fact that the idea holds up, the same standing `_evidence_quality`
    gives a resolved forecast rather than an opinion about one.
    """
    _seed(conn)
    cell = _audited_cell(conn, "holds-up", reply=NO_CONCERN_REPLY, occurred=True)
    grant = _candidate(conn, cell, "holds-up")

    candidate = _for(selection.evaluate(conn), grant)
    gate = next(g for g in candidate.gates if g.dimension == "software_native_advantage")
    assert gate.outcome is selection.GateOutcome.PASSED
    assert candidate.passes_gates


def test_a_content_audit_that_does_not_hold_up_rejects_the_gate(conn):
    """The reverse resolution: a claim that resolves `False` is a vindicated
    concern (§13.4's "ordinary freelancing described exotically"), a realised
    finding rather than the estimated negative EV §10.5 forbids acting on."""
    _seed(conn)
    cell = _audited_cell(conn, "ordinary", reply=CONCERN_REPLY, occurred=False)
    grant = _candidate(conn, cell, "ordinary")

    candidate = _for(selection.evaluate(conn), grant)
    assert "software_native_advantage" in candidate.rejected_by


def test_an_unresolved_content_audit_is_unevaluable_not_a_rejection(conn):
    """Reading an unresolved prediction into the gate would be scoring a
    candidate on an Auditor's opinion before the register has judged the
    Auditor — exactly the shape §10.5 forbids. §13.2's own gate for a Cell
    with no resolved forecasts draws the identical distinction: unmeasured is
    not inferior."""
    _seed(conn)
    cell = _audited_cell(conn, "pending", reply=NO_CONCERN_REPLY, occurred=True, resolve=False)
    grant = _candidate(conn, cell, "pending")

    candidate = _for(selection.evaluate(conn), grant)
    gate = next(g for g in candidate.gates if g.dimension == "software_native_advantage")
    assert gate.outcome is selection.GateOutcome.UNEVALUABLE
    assert candidate.passes_gates


def test_gates_run_before_the_frontier(conn):
    """§13.2's order, and it is not cosmetic.

    A rejected candidate is not compared at all. If it were, the cheapest
    proposal in the colony could be a quarantined Cell's, and it would dominate
    every compliant candidate on cost — a gate that only lowered a rank would
    not be a gate.
    """
    _seed(conn)
    bad, good = _cell(conn, "bad"), _cell(conn, "good")
    bad_grant = _candidate(conn, bad, "bad", cost=1, forecasts=(0.5,))
    good_grant = _candidate(conn, good, "good", cost=90, forecasts=(0.99,))
    lifecycle.quarantine(conn, bad.cell_id, reason="under test")

    frontier = selection.evaluate(conn)
    assert bad_grant.grant_id in frontier.rejected_grant_ids
    assert bad_grant.grant_id not in frontier.frontier_grant_ids
    assert good_grant.grant_id in frontier.frontier_grant_ids


# --- the frontier (§13.2 "do not rely on a single weighted scalar") ----------


def test_information_gain_prefers_the_forecast_that_could_still_go_either_way(conn):
    """§8.5's register read as §13.2's information gain.

    A claim at p = 0.5 resolves to a full bit; one at p = 0.99 tells the colony
    almost nothing it did not already believe. The reason this is safe to select
    on despite being the Cell's own number is that Brier is a **proper** scoring
    rule: overstating uncertainty loses points at resolution.
    """
    _seed(conn)
    uncertain, confident = _cell(conn, "uncertain"), _cell(conn, "confident")
    a = _candidate(conn, uncertain, "uncertain", forecasts=(0.5,))
    b = _candidate(conn, confident, "confident", forecasts=(0.99,))

    frontier = selection.evaluate(conn)
    hi = _for(frontier, a).axis("information_gain").value
    lo = _for(frontier, b).axis("information_gain").value
    assert hi == pytest.approx(1.0, abs=1e-9)
    assert lo < 0.1
    assert selection.dominates(_for(frontier, a), _for(frontier, b))
    assert not selection.dominates(_for(frontier, b), _for(frontier, a))


def test_structural_novelty_is_an_ordinal_and_radical_dominates_adjacent(conn):
    """ADR-060 turned §13.2's novelty axis from an abstention into a measurement.

    §12.1's bins are ordinal — adjacent < moderate < radical — and the gaps carry
    no meaning, so domination may compare them for order and nothing else. The
    reverse direction is asserted too: a sign error here would select for the
    Cells doing what the colony already does, and nothing would crash.
    """
    _seed(conn)
    base = {"market": "independent bookshops", "problem": "stock is guesswork",
            "product": "a weekly digest", "revenue_model": "monthly subscription",
            "acquisition_channel": "trade newsletters", "workflow": "ingest, rank, publish"}
    _cell(conn, "founder", base)
    near = _cell(conn, "near", {**base, "product": "a daily digest"})
    far = _cell(conn, "far", {**base, "market": "hospital procurement teams"})

    a = _candidate(conn, far, "far", cost=30, forecasts=(0.5,))
    b = _candidate(conn, near, "near", cost=30, forecasts=(0.5,))

    frontier = selection.evaluate(conn)
    assert _for(frontier, a).axis("structural_novelty").value == 2.0
    assert _for(frontier, b).axis("structural_novelty").value == 0.0
    assert selection.dominates(_for(frontier, a), _for(frontier, b))
    assert not selection.dominates(_for(frontier, b), _for(frontier, a))
    assert "structural_novelty" in frontier.measured_dimensions


def test_a_proposal_with_no_forecast_abstains_on_information_gain(conn):
    """No claim registered is not "zero information", it is no measurement.

    Scoring it 0.0 would rank a Cell that promised nothing below one that made a
    near-certain claim, when in fact neither has told the colony anything it can
    check.
    """
    _seed(conn)
    cell = _cell(conn, "silent")
    grant = _candidate(conn, cell, "silent", forecasts=())
    axis = _for(selection.evaluate(conn), grant).axis("information_gain")
    assert axis.value is None
    assert "no forecasts" in axis.reason


def test_experiment_cost_is_normalised_by_the_stage_tranche(conn):
    """§13.1's ratio, and its first consumer.

    `normalised_cost = expected experiment cost / current stage tranche`. ADR-048
    built it with nothing computing on it and FUTURE_BUILD_HOOKS asked §13.2 to
    check that this ratio is the dimension it wants rather than assume it: §13.2
    lists "experiment cost", and §13.1 exists to make that quantity
    dimensionless. The denominator is a figure a human approved, so §23.5 never
    reaches it.
    """
    _seed(conn)
    cell = _cell(conn, "funded")
    first = _candidate(conn, cell, "first", cost=30)
    assert _for(selection.evaluate(conn), first).axis("experiment_cost").value is None

    promotion.allocate(conn, grant_id=first.grant_id, allocated_by="operator", reason="test")
    second = _candidate(conn, cell, "second", cost=30)
    axis = _for(selection.evaluate(conn), second).axis("experiment_cost")
    tranche = promotion.get_promotion(
        conn, promotion.list_promotions(conn, cell_id=cell.cell_id)[0].promotion_id
    )
    assert axis.value == pytest.approx(30 / tranche.allocated_minor_units)


def test_a_cheaper_candidate_dominates_a_dearer_one_and_not_the_reverse(conn):
    """The sign, which no crash would ever reveal.

    A flipped comparison in a domination test still returns a frontier, still
    passes every structural test, and selects the opposite population. Both
    directions are asserted for exactly that reason — and `HIGHER_IS_BETTER`
    exists so the direction is written down rather than implied by an operator.
    """
    _seed(conn)
    cheap, dear = _cell(conn, "cheap"), _cell(conn, "dear")
    for cell, tag in ((cheap, "cheap"), (dear, "dear")):
        seed_grant = _candidate(conn, cell, f"{tag}-seed", cost=10)
        promotion.allocate(conn, grant_id=seed_grant.grant_id,
                           allocated_by="operator", reason="test")
    a = _candidate(conn, cheap, "cheap", cost=5, forecasts=(0.5,))
    b = _candidate(conn, dear, "dear", cost=95, forecasts=(0.5,))

    frontier = selection.evaluate(conn)
    assert selection.dominates(_for(frontier, a), _for(frontier, b))
    assert not selection.dominates(_for(frontier, b), _for(frontier, a))
    assert b.grant_id not in frontier.frontier_grant_ids


def test_domination_needs_an_axis_both_candidates_measured(conn):
    """`death._dominates`'s rule, applied to candidates.

    "A dimension only one of them has evidence on is skipped, because domination
    on no evidence is just an opinion with a body count." Two candidates sharing
    no measured axis therefore both stay on the frontier — the honest result for
    a colony that cannot yet measure four of §13.2's nine dimensions, and the
    reason this is written to abstain rather than fall back on whatever axis
    happens to exist.
    """
    _seed(conn)
    quiet_a, quiet_b = _cell(conn, "quiet-a"), _cell(conn, "quiet-b")
    a = _candidate(conn, quiet_a, "quiet-a", cost=5, forecasts=())
    b = _candidate(conn, quiet_b, "quiet-b", cost=95, forecasts=())

    frontier = selection.evaluate(conn)
    assert not any(axis.measured for axis in _for(frontier, a).axes)
    assert not selection.dominates(_for(frontier, a), _for(frontier, b))
    assert not selection.dominates(_for(frontier, b), _for(frontier, a))
    assert {a.grant_id, b.grant_id} <= frontier.frontier_grant_ids


def test_a_candidate_better_on_one_axis_and_worse_on_another_survives(conn):
    """The property that makes this a frontier rather than a ranking.

    §10.2: "Do not collapse all dimensions into one scalar; use constraints and
    portfolio selection." A cheap uninformative candidate and an expensive
    informative one are both answers, and any rule that picked between them
    would be the weighted sum the clause forbids.
    """
    _seed(conn)
    cheap, rich = _cell(conn, "cheap"), _cell(conn, "rich")
    for cell, tag in ((cheap, "cheap"), (rich, "rich")):
        seed_grant = _candidate(conn, cell, f"{tag}-seed", cost=10)
        promotion.allocate(conn, grant_id=seed_grant.grant_id,
                           allocated_by="operator", reason="test")
    a = _candidate(conn, cheap, "cheap", cost=5, forecasts=(0.99,))
    b = _candidate(conn, rich, "rich", cost=95, forecasts=(0.5,))

    frontier = selection.evaluate(conn)
    assert not selection.dominates(_for(frontier, a), _for(frontier, b))
    assert not selection.dominates(_for(frontier, b), _for(frontier, a))
    assert {a.grant_id, b.grant_id} <= frontier.frontier_grant_ids


# --- structural guarantees ---------------------------------------------------


def test_selection_carries_no_score_rank_or_weight():
    """§13.2 and §10.2 both forbid the scalar, so nothing may hold one.

    The surest way to keep a scalar out of a selector is to give it nowhere to
    live — the move `proposal.FORBIDDEN_FIELD_SENSE` makes for a Cell's
    self-report. A field named `score` would be filled by the first person who
    wanted the frontier sorted.
    """
    forbidden = {"score", "rank", "weight", "fitness", "priority", "total"}
    for cls in (selection.Candidate, selection.Frontier, selection.Axis, selection.Gate):
        names = {f.name for f in dataclasses.fields(cls)}
        assert not names & forbidden, f"{cls.__name__} carries {names & forbidden}"


def test_no_kernel_path_acts_on_a_frontier():
    """Being off the frontier is an estimate, and §10.5 forbids acting on one.

    "Estimated negative EV alone must not kill a Cell" without strong evidence
    *and* an independent Auditor concurring — and a Pareto rank over three
    measurable axes is precisely such an estimate. Upward is closed for the same
    reason `outcome.py` is: an allocation that read its own selector would be
    promoting without the human §25.1 puts in the loop.

    This is the successor to `test_no_kernel_path_acts_on_an_assessment`, and
    like it, the next step costs an explicit edit to a named test.
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    allowed = {"selection.py", "cli.py", "golden.py"}
    consumers = sorted(
        path.name for path in source_dir.glob("*.py")
        if path.name not in allowed and "selection" in _imported_modules(path)
    )
    assert not consumers, (
        f"{consumers} imports §13.2's selector. Acting on a frontier is a promotion "
        "nobody approved (upward) or a §10.5 violation (downward)"
    )
    for forbidden, why in (
        ("death.py", "§10.5 forbids culling on an estimate without a concurring Auditor"),
        ("promotion.py", "an allocation that reads its own selector funds itself"),
        ("scheduler.py", "a selector that fires on a timer is selection without a human"),
    ):
        assert "selection" not in _imported_modules(source_dir / forbidden), (
            f"{forbidden} must never reach the frontier: {why}"
        )


def test_the_frontier_never_reaches_a_cell():
    """§23.5: the review path is part of the environment and will be optimised against.

    A Cell shown which axes put it on the frontier learns to move those axes,
    and two of the three measurable ones are its own numbers. `context.py` is
    the only module that decides what a Cell sees, so it is the one that must
    not be able to see this — the same boundary `tests/test_analysis_boundary.py`
    draws around the diversity and concreteness scorers.
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    for module in ("context.py", "deliberation.py"):
        assert "selection" not in _imported_modules(source_dir / module), (
            f"{module} can reach §13.2's frontier; a Cell that learns how it is "
            "selected learns to perform it (§23.5)"
        )


def test_selecting_writes_nothing(conn):
    """Derived on every read, stored nowhere (§2.5, Charter C3).

    A `selections` table would be a second version of a question the ledger, the
    register and the approval queue already answer, and it becomes worth adding
    only when a *decision* consumes one — which the test above keeps shut.
    """
    _seed(conn)
    cell = _cell(conn, "a")
    _candidate(conn, cell, "a", forecasts=(0.5,))
    before = _fingerprint(conn)
    selection.evaluate(conn)
    assert _fingerprint(conn) == before

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {t for t in tables if "selection" in t or "frontier" in t}


def _fingerprint(conn):
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def _imported_modules(path: Path) -> set[str]:
    """Module names `path` imports, function-local ones included."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.update(node.module.split("."))
            if node.level:
                imported.update(alias.name for alias in node.names)
    return imported
