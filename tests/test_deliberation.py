"""The agent loop (SPEC.md §17.2, §15, §0.3, §25.1; Charter C6, C8, C15).

Organised around what the loop must *not* be able to do, because that is where
the spec is prescriptive and where the obvious implementation goes wrong.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from mitosis import (
    approval,
    context,
    death,
    deliberation,
    events,
    experiments,
    ledger,
    lifecycle,
    prediction,
    proposal,
    providers,
)
from mitosis.models import Book, CellStatus, CellType, EntrySpec

GENOME = {
    "market": "small accounting firms",
    "problem": "month-end close is manual",
    "workflow": "probe cheaply, measure, iterate",
}


def _valid_reply(**overrides) -> str:
    payload = {
        "kind": "experiment",
        "summary": "probe the synthetic market for demand",
        "rationale": "no realised record yet; a cheap probe is the fastest way to get one",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 50,
        "predictions": [
            {"claim": "revenue >= 50 minor units", "probability": 0.4, "horizon_days": 7}
        ],
        "experiment": {"hypothesis": "small firms will pay for an automated month-end close"},
    }
    payload.update(overrides)
    # The schema pairs each kind with its own payload in both directions, so a
    # test that overrides `kind` does not inherit a block that kind may not
    # carry.
    if payload["kind"] != "experiment":
        payload.pop("experiment", None)
    return json.dumps(payload)


def _fund(conn, cell, amount: int = 5_000) -> None:
    """A calling Cell needs USD_REAL and RESOURCE — what the gateway reserves."""
    for book, currency in ((Book.USD_REAL, "USD"), (Book.RESOURCE, "RESOURCE"), (Book.USD_SIM, "USD")):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="cell_birth_funding",
            idempotency_key=f"fund:{cell.cell_id}:{book.value}",
            description="fund for deliberation",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-amount, cell_id=cell.cell_id),
                EntrySpec(
                    account_id=f"cell:{cell.cell_id}:cash",
                    amount_minor_units=amount,
                    cell_id=cell.cell_id,
                ),
            ],
        )


def _make_cell(
    conn, *, key: str = "a", cell_type: CellType = CellType.EXPLORER, fund: bool = True,
    extra_genome: dict | None = None,
):
    cell = lifecycle.create_cell(
        conn,
        cell_type=cell_type,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key=key,
    )
    content = {**GENOME, **(extra_genome or {})}
    # Give the genome real content, so the loop has something to interpret.
    genome_hash = lifecycle._get_or_create_genome(conn, cell_type, mutation=content)
    conn.execute(
        "UPDATE cells SET genome_hash = ? WHERE cell_id = ?", (genome_hash, cell.cell_id)
    )
    conn.commit()
    if fund:
        _fund(conn, cell)
    return lifecycle.get_cell(conn, cell.cell_id)


def _deliberate(conn, cell, reply: str | None = None, *, wake_key: str = "w1", **kwargs):
    return deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=reply if reply is not None else _valid_reply()),
        wake_key=wake_key,
        model="mock-1",
        **kwargs,
    )


def _model_call_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM model_calls").fetchone()["n"]


def _running_experiment(conn, cell, hypothesis="does the probe find demand"):
    return experiments.start(
        conn, cell_id=cell.cell_id, hypothesis=hypothesis, ladder_rung=1,
        expected_cost_minor_units=0,
    )


# --- §2.6: what a Cell's thinking cost, and which experiment it cost it for ---


def test_a_cells_thinking_is_attributed_to_the_experiment_it_is_thinking_about(conn):
    """§2.6's "real cash consumed" and "resource consumption" (ADR-044).

    A wake never named the experiment it was for, so the gateway recorded the
    call with no attribution and §2.6 reported **0 real spend** for every
    experiment whose Cell simply ran. Model calls are the colony's main real
    expense, so this was the largest hole in the report — and the least visible,
    because 0 is a plausible figure for an experiment that has not spent yet.
    """
    cell = _make_cell(conn)
    experiment = _running_experiment(conn, cell)

    _deliberate(conn, cell)

    call = conn.execute("SELECT * FROM model_calls").fetchone()
    assert call["experiment_id"] == experiment.experiment_id
    report = experiments.report(conn, experiment.experiment_id)
    assert report.model_calls == 1
    assert report.input_tokens > 0
    assert report.resource_spend_minor_units > 0


def test_a_cells_own_forecasts_reach_the_reality_gap_of_its_experiment(conn):
    """§2.6's sixth dimension, from §8.5's register.

    `deliberation` hardcoded `experiment_id=None` on every prediction a Cell
    registered, so the forecasts a Cell made *while running an experiment* —
    the ones the reality-gap estimate exists to score — were the only ones the
    report could never see. An operator passing `--experiment` by hand was the
    sole path in.
    """
    cell = _make_cell(conn)
    experiment = _running_experiment(conn, cell)

    _deliberate(conn, cell)

    report = experiments.report(conn, experiment.experiment_id)
    assert report.unresolved_predictions == 1
    assert report.resolved_predictions == 0
    registered = conn.execute("SELECT * FROM prediction_register").fetchone()
    assert registered["experiment_id"] == experiment.experiment_id


def test_a_call_and_the_forecasts_it_produced_share_one_experiment(conn):
    """Read once, used twice.

    The gateway call happens outside every transaction this module opens
    (ADR-022) and the predictions are registered inside one. Re-deriving the
    attribution in the second place would let an experiment concluding in
    between put a model call on one experiment and its own forecasts on
    another, with nothing afterwards saying which was right.

    **The experiment is concluded mid-call on purpose.** Asserting that the two
    agree on a quiet run proves nothing — a re-derivation agrees too, so the
    test would pass for the wrong reason and could never fail. The provider
    concludes it while the call is in flight, which is the only moment the two
    designs give different answers.
    """
    cell = _make_cell(conn)
    experiment = _running_experiment(conn, cell)

    class ConcludesMidCall:
        """Stands in for the world moving while a slow model call is out."""

        name = providers.MOCK_PROVIDER

        def complete(self, request):
            experiments.conclude(
                conn, experiment_id=experiment.experiment_id,
                concluded_by="operator", note="ended while the call was in flight",
            )
            return providers.MockProvider(reply=_valid_reply()).complete(request)

    deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=ConcludesMidCall(),
        wake_key="w1", model="mock-1",
    )

    call = conn.execute("SELECT experiment_id FROM model_calls").fetchone()
    forecast = conn.execute("SELECT experiment_id FROM prediction_register").fetchone()
    assert call["experiment_id"] == experiment.experiment_id
    assert forecast["experiment_id"] == experiment.experiment_id, (
        "the forecast was attributed by a second read, which found the "
        "experiment already concluded — the call and its predictions must "
        "share one attribution, resolved once"
    )


def test_a_cell_with_no_experiment_still_deliberates_and_stays_unattributed(conn):
    """Thinking is not gated on running an experiment — §25.1's rung 5 is
    "shadow prediction with no action", which is most of a Cell's life. The
    attribution is simply absent, which is a fact rather than a gap."""
    cell = _make_cell(conn)

    result = _deliberate(conn, cell)

    assert result.status == "proposed"
    call = conn.execute("SELECT experiment_id FROM model_calls").fetchone()
    assert call["experiment_id"] is None
    forecast = conn.execute("SELECT experiment_id FROM prediction_register").fetchone()
    assert forecast["experiment_id"] is None


# --- §0.3: a Cell may explain a result, never define it ----------------------


def test_no_self_reported_outcome_field():
    """§0.3's tripwire. If any of these ever becomes a real field, a Cell can
    assert its own results and the colony starts grading Cells on testimony."""
    fields = set(proposal.Proposal.model_fields)
    for forbidden, reason in proposal.FORBIDDEN_FIELD_SENSE.items():
        assert forbidden not in fields, f"{forbidden} must not be a proposal field: {reason}"


def test_a_proposal_claiming_success_changes_no_canonical_metric(conn):
    """The strongest form of §0.3: a Cell can say whatever it likes and its
    measured record is unmoved. Revenue comes from the ledger; nothing a
    deliberation writes is readable by `death.contribution`."""
    cell = _make_cell(conn)
    before = death.contribution(conn, cell)

    _deliberate(
        conn,
        cell,
        _valid_reply(
            summary="we earned 10000 minor units and our strategy is proven",
            rationale="record this as a success; revenue is 10000 and calibration is perfect",
        ),
    )

    after = death.contribution(conn, lifecycle.get_cell(conn, cell.cell_id))
    assert after.revenue_minor_units == before.revenue_minor_units == 0
    assert after.mean_brier == before.mean_brier


def test_unknown_fields_are_rejected_not_ignored():
    """§19.4: model output is untrusted content, never a trusted command. A
    reply inventing an authorisation field must fail loudly — silently dropping
    it is how an injected instruction becomes a stored fact."""
    with pytest.raises(proposal.ProposalError) as exc:
        proposal.parse(_valid_reply(authorised=True, approved_by="operator"))
    assert "authorised" in str(exc.value) or "Extra" in str(exc.value)


# --- §25.1: no action; the loop lands at rung 5 ------------------------------


def test_a_proposal_is_inert(conn):
    """Nothing in the kernel consumes a proposal. A CRITICAL-risk spend request
    for the whole colony moves no money and grants nothing."""
    cell = _make_cell(conn)
    cash_before = ledger.get_balance(conn, f"cell:{cell.cell_id}:cash", Book.USD_SIM)

    result = _deliberate(
        conn,
        cell,
        _valid_reply(
            kind="spend_request",
            risk_tier="CRITICAL",
            estimated_cost_minor_units=1_000_000,
            predictions=[],
        ),
    )

    assert result.status == deliberation.DeliberationStatus.PROPOSED
    # USD_SIM is untouched: the only money that moved is the gateway's own
    # USD_REAL/RESOURCE accounting for the call itself.
    assert ledger.get_balance(conn, f"cell:{cell.cell_id}:cash", Book.USD_SIM) == cash_before
    assert ledger.verify_conservation(conn, Book.USD_SIM)
    assert ledger.verify_chain(conn)


def test_risk_tier_is_recorded_not_honoured(conn):
    """A Cell setting its own risk tier grants itself nothing — otherwise every
    Cell would declare LOW forever."""
    cell = _make_cell(conn)
    before = ledger.get_balance(conn, f"cell:{cell.cell_id}:cash", Book.USD_SIM)
    result = _deliberate(conn, cell, _valid_reply(risk_tier="LOW", kind="spend_request"))
    stored = deliberation.get_proposal(conn, result.proposal_id)
    assert stored["risk_tier"] == "LOW"
    # No approval, permission, or capability follows from it.
    assert stored["kind"] == "spend_request"
    assert ledger.get_balance(conn, f"cell:{cell.cell_id}:cash", Book.USD_SIM) == before


# --- Charter C15: genome is data the loop interprets, never code -------------


def test_the_loop_never_executes_anything():
    """Charter C15 holds only while genomes are inert data. Genome content
    reaches a prompt as JSON; if it ever reached `exec`, a Cell would be able to
    run code inside the kernel process — and the sandbox that makes that
    survivable (C12) is Phase 5, not built."""
    dangerous = {"exec", "eval", "compile", "__import__"}
    for module in ("deliberation.py", "context.py", "proposal.py"):
        source = Path("src/mitosis") / module
        tree = ast.parse(source.read_text())
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not (called & dangerous), f"{module} calls {called & dangerous}"


def test_a_genomes_model_policy_temperature_reaches_the_gateway_request(conn):
    """§14.1's sampling-mutation operator, read from the Cell's own genome
    rather than a kernel constant (ADR-050, ADR-067) — the wiring this test
    defends end to end, not just `genome.temperature_of` in isolation."""
    cell = _make_cell(conn, extra_genome={"model_policy": {"temperature": 0.3}})

    seen: list = []

    class RecordingProvider:
        name = providers.MOCK_PROVIDER

        def complete(self, request):
            seen.append(request)
            return providers.MockProvider(reply=_valid_reply()).complete(request)

    deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=RecordingProvider(), wake_key="w1", model="mock-1",
    )
    assert seen[0].temperature == 0.3


def test_a_silent_genome_sends_no_temperature_opinion(conn):
    """A Cell that has never mutated `model_policy` must not be read as
    requesting temperature 0 — that is the exact kernel default ADR-050
    refused. `None` reaches the provider, which then applies its own
    default."""
    cell = _make_cell(conn)
    seen: list = []

    class RecordingProvider:
        name = providers.MOCK_PROVIDER

        def complete(self, request):
            seen.append(request)
            return providers.MockProvider(reply=_valid_reply()).complete(request)

    deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=RecordingProvider(), wake_key="w1", model="mock-1",
    )
    assert seen[0].temperature is None


def test_genome_content_reaches_the_prompt_as_data(conn):
    cell = _make_cell(conn)
    assembled = context.assemble(
        conn,
        cell=cell,
        canonical_genome={"cell_type": "explorer", **GENOME},
        wake_reason="scheduled research cycle",
    )
    rendered = assembled.render()
    assert "small accounting firms" in rendered
    assert json.dumps(GENOME["workflow"])[1:-1] in rendered


# --- Charter C8 / §18.2: who may be woken ------------------------------------


def test_a_dead_cell_cannot_deliberate(conn):
    cell = _make_cell(conn)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    result = _deliberate(conn, cell)

    assert result.status == deliberation.DeliberationStatus.REFUSED
    assert "dead" in result.failure_reason
    assert result.model_call_id is None
    assert _model_call_count(conn) == 0


def test_a_quarantined_cell_cannot_deliberate(conn):
    cell = _make_cell(conn)
    lifecycle.quarantine(conn, cell.cell_id, reason="poison event")

    result = _deliberate(conn, cell)

    assert result.status == deliberation.DeliberationStatus.REFUSED
    assert _model_call_count(conn) == 0


def test_a_dormant_cell_may_be_woken(conn):
    """§17.2's whole point: a wake event brings a dormant Cell back."""
    cell = _make_cell(conn)
    lifecycle.sleep(conn, cell.cell_id)

    result = _deliberate(conn, cell)

    assert result.status == deliberation.DeliberationStatus.PROPOSED


def test_an_unfunded_cell_is_refused_without_spending(conn):
    cell = _make_cell(conn, fund=False)

    result = _deliberate(conn, cell)

    assert result.status == deliberation.DeliberationStatus.REFUSED
    assert "USD_REAL" in result.failure_reason
    assert _model_call_count(conn) == 0


def test_a_refusal_is_recorded_not_raised(conn):
    """A refusal is a fact about the colony, not just an error. One that
    only ever appeared in a traceback would be invisible to any query."""
    cell = _make_cell(conn, fund=False)
    result = _deliberate(conn, cell)
    assert deliberation.get_deliberation_by_wake_key(conn, "w1").deliberation_id == (
        result.deliberation_id
    )


# --- Charter C6: idempotent under at-least-once redelivery -------------------


def test_a_redelivered_wake_does_not_buy_a_second_model_call(conn):
    cell = _make_cell(conn)
    first = _deliberate(conn, cell)
    second = _deliberate(conn, cell)

    assert first.deliberation_id == second.deliberation_id
    assert _model_call_count(conn) == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM prediction_register").fetchone()["n"] == 1


def test_distinct_wakes_are_distinct_deliberations(conn):
    cell = _make_cell(conn)
    first = _deliberate(conn, cell, wake_key="w1")
    second = _deliberate(conn, cell, wake_key="w2")
    assert first.deliberation_id != second.deliberation_id
    assert _model_call_count(conn) == 2


# --- parsing and recording ---------------------------------------------------


def test_an_unparseable_reply_is_recorded_without_storing_the_prose(conn):
    cell = _make_cell(conn)

    result = _deliberate(conn, cell, "I think we should probably try selling something!")

    assert result.status == deliberation.DeliberationStatus.UNPARSEABLE
    assert result.proposal_id is None
    assert "not JSON" in result.failure_reason
    row = conn.execute(
        "SELECT * FROM deliberations WHERE deliberation_id = ?", (result.deliberation_id,)
    ).fetchone()
    assert "selling something" not in json.dumps(dict(row))


def test_the_cell_still_paid_for_an_unparseable_reply(conn):
    """The tokens were burned whatever came back. Rolling the call back would
    make a Cell that returns garbage cheaper to run than one that complies."""
    cell = _make_cell(conn)
    result = _deliberate(conn, cell, "not json")
    assert result.model_call_id is not None
    assert _model_call_count(conn) == 1


def test_a_fenced_json_reply_is_accepted(conn):
    cell = _make_cell(conn)
    result = _deliberate(conn, cell, f"```json\n{_valid_reply()}\n```")
    assert result.status == deliberation.DeliberationStatus.PROPOSED


def test_predictions_are_registered_before_their_outcomes(conn):
    cell = _make_cell(conn)
    result = _deliberate(conn, cell)

    assert len(result.prediction_ids) == 1
    registered = prediction.get(conn, result.prediction_ids[0])
    assert registered.claim == "revenue >= 50 minor units"
    assert registered.outcome is None  # unresolved: the outcome is not known yet
    assert prediction.verify_chain(conn)


def test_a_duplicate_claim_is_rejected(conn):
    """Two probabilities for one claim is a hedge that scores either way, and
    would inflate the Cell's resolved count on one piece of evidence."""
    cell = _make_cell(conn)
    result = _deliberate(
        conn,
        cell,
        _valid_reply(
            predictions=[
                {"claim": "revenue >= 50", "probability": 0.4, "horizon_days": 7},
                {"claim": "revenue >= 50", "probability": 0.9, "horizon_days": 7},
            ]
        ),
    )
    assert result.status == deliberation.DeliberationStatus.UNPARSEABLE
    assert "distinct" in result.failure_reason


def test_a_certain_prediction_is_rejected(conn):
    """prediction.py refuses certainty because an infinite log score makes a
    population unorderable; the proposal schema refuses it earlier."""
    cell = _make_cell(conn)
    result = _deliberate(
        conn,
        cell,
        _valid_reply(
            predictions=[{"claim": "we will succeed", "probability": 1.0, "horizon_days": 7}]
        ),
    )
    assert result.status == deliberation.DeliberationStatus.UNPARSEABLE


def test_abstaining_is_a_valid_proposal(conn):
    cell = _make_cell(conn)
    result = _deliberate(
        conn,
        cell,
        _valid_reply(
            kind="abstain",
            summary="nothing worth doing this cycle",
            rationale="no signal has changed since the last wake; probing again would spend for nothing",
            predictions=[],
        ),
    )
    assert result.status == deliberation.DeliberationStatus.PROPOSED
    assert deliberation.get_proposal(conn, result.proposal_id)["kind"] == "abstain"


# --- §15: bounded context ----------------------------------------------------


def test_context_never_loads_the_entire_history(conn):
    """§15.1, literally: do not load the entire Cell history."""
    cell = _make_cell(conn)
    for index in range(8):
        result = _deliberate(
            conn, cell, _valid_reply(summary=f"probe number {index}", predictions=[]),
            wake_key=f"w{index}", proposal_sink=approval.QueueSink(),
        )
        # Approved so the summaries actually render: since ADR-052 an *undecided*
        # proposal shows no wording, which would make this probe invisible and the
        # test vacuously green. Deciding them tests the leaky case on purpose —
        # the slice must stay bounded even when every entry is fully shown.
        approval.approve(
            conn, request_id=conn.execute(
                "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
                (result.proposal_id,),
            ).fetchone()["request_id"],
            decided_by="operator", reason="probe",
        )

    assembled = context.assemble(
        conn,
        cell=lifecycle.get_cell(conn, cell.cell_id),
        canonical_genome=GENOME,
        wake_reason="scheduled research cycle",
    )
    rendered = assembled.render()

    # Counted, not matched on summaries: since ADR-053 the log shows no wording,
    # so a probe-text search finds nothing and would pass vacuously — which it
    # did, silently, when that rule shipped. The entry count is what the §15.1
    # bound actually governs.
    log = next(
        s.body for s in assembled.sections if s.name.startswith("Your recent proposals")
    )
    entries = log.count("- [")

    # Bounds are absolute, not `<= context.RECENT_PROPOSALS`. Asserting against
    # the constant makes the test a tautology — raising the constant to 1000
    # would satisfy it while loading exactly the history §15.1 forbids. (Found
    # by the teeth check, which is the only reason this reads oddly.)
    assert 1 <= entries <= 3, f"expected a bounded slice, got {entries} entries"
    # And nothing else may dump the history either: no probe wording anywhere.
    assert not [i for i in range(8) if f"probe number {i}" in rendered], (
        "a section is leaking proposal wording back into the context"
    )


def test_context_stays_within_its_token_budget(conn):
    cell = _make_cell(conn)
    for index in range(6):
        _deliberate(
            conn, cell, _valid_reply(summary=f"a fairly wordy probe {index} " * 10, predictions=[]),
            wake_key=f"w{index}",
        )

    assembled = context.assemble(
        conn,
        cell=lifecycle.get_cell(conn, cell.cell_id),
        canonical_genome=GENOME,
        wake_reason="scheduled research cycle",
        budget_tokens=260,
    )
    assert assembled.tokens <= 260
    assert assembled.dropped  # and it says what it left out


def test_required_context_is_never_dropped(conn):
    cell = _make_cell(conn)
    assembled = context.assemble(
        conn, cell=cell, canonical_genome=GENOME,
        wake_reason="scheduled research cycle", budget_tokens=250,
    )
    names = [s.name for s in assembled.sections]
    assert any("Policy constraints" in n for n in names)
    assert any("genome" in n for n in names)


def test_a_budget_too_small_for_the_constitution_fails_loudly(conn):
    """A Cell shown half its constraints is guessing. Better to refuse."""
    cell = _make_cell(conn)
    with pytest.raises(context.ContextError) as exc:
        context.assemble(
            conn, cell=cell, canonical_genome=GENOME,
            wake_reason="scheduled research cycle", budget_tokens=5,
        )
    assert "policy or genome" in str(exc.value)


def test_the_deliberation_records_what_context_was_dropped(conn):
    cell = _make_cell(conn)
    result = _deliberate(conn, cell, context_budget_tokens=260)
    row = conn.execute(
        "SELECT context_json, context_tokens, context_dropped_json FROM deliberations "
        "WHERE deliberation_id = ?",
        (result.deliberation_id,),
    ).fetchone()
    record = json.loads(row["context_json"])
    assert record["budget_tokens"] == 260
    assert record["used_tokens"] == row["context_tokens"]
    assert isinstance(json.loads(row["context_dropped_json"]), list)


# --- §17.2: the wake-event path ---------------------------------------------


def test_a_wake_event_drives_a_deliberation(conn):
    """The first real producer *and* consumer on the event path — until now
    nothing in the kernel emitted or consumed a domain event."""
    cell = _make_cell(conn)
    deliberation.enqueue_wake(conn, cell_id=cell.cell_id, dedupe_key="wake:1")

    results = deliberation.run_ready_wakes(
        conn, provider=providers.MockProvider(reply=_valid_reply()), model="mock-1"
    )

    assert len(results) == 1
    assert results[0].status == deliberation.DeliberationStatus.PROPOSED
    assert events.count_by_status(conn).get("processed") == 1


def test_a_redelivered_wake_event_does_not_pay_twice(conn):
    """Charter C6 for the event path. The deliberation commits before the event
    is marked processed, so a crash in between means redelivery — which must
    find the existing deliberation rather than buy a second call."""
    cell = _make_cell(conn)
    event = deliberation.enqueue_wake(conn, cell_id=cell.cell_id, dedupe_key="wake:1")

    deliberation.run_wake_event(
        conn, event, provider=providers.MockProvider(reply=_valid_reply()), model="mock-1"
    )
    # Simulate the crash window: the deliberation landed, the event did not get
    # marked. Redelivery must be a no-op that costs nothing.
    conn.execute(
        "UPDATE event_inbox SET status = 'pending' WHERE event_id = ?", (event.event_id,)
    )
    conn.commit()
    deliberation.run_wake_event(
        conn, event, provider=providers.MockProvider(reply=_valid_reply()), model="mock-1"
    )

    assert _model_call_count(conn) == 1
    assert events.count_by_status(conn).get("processed") == 1


def test_run_ready_wakes_ignores_other_event_types(conn):
    _make_cell(conn)
    events.enqueue(
        conn, event_type="something_else", source="test", priority=100, dedupe_key="other:1"
    )
    results = deliberation.run_ready_wakes(
        conn, provider=providers.MockProvider(reply=_valid_reply()), model="mock-1"
    )
    assert results == []
    assert events.count_by_status(conn).get("pending") == 1
