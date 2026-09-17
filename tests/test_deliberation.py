"""The agent loop (SPEC.md §17.2, §15, §0.3, §25.1; Charter C6, C8, C15).

Organised around what the loop must *not* be able to do, because that is where
the spec is prescriptive and where the obvious implementation goes wrong.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path

import pytest

from mitosis import (
    approval,
    context,
    db,
    death,
    deliberation,
    events,
    experiments,
    gateway,
    ledger,
    lifecycle,
    prediction,
    proposal,
    providers,
    real_spend_breaker,
)
from mitosis.models import Book, CellStatus, CellType, EntrySpec, ModelCallStatus

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
    make a Cell that returns garbage cheaper to run than one that complies.

    A fixed `MockProvider` returns the same broken text on the repair attempt
    too (ADR-069), so both calls are billed and both are traceable — the
    Cell's tokens were burned twice, and the record says so.
    """
    cell = _make_cell(conn)
    result = _deliberate(conn, cell, "not json")
    assert result.model_call_id is not None
    assert result.repair_model_call_id is not None
    assert result.status == deliberation.DeliberationStatus.UNPARSEABLE
    assert _model_call_count(conn) == 2


# --- ADR-069: one bounded parse-repair retry -----------------------------------


class _SequencedProvider:
    """Returns a different canned reply on each successive call, so a test can
    exercise "the first reply was bad, the second (repair) reply was good" —
    something one fixed `MockProvider` cannot represent, since its reply never
    varies by call. Calling past the end of `replies` repeats the last one."""

    name = providers.MOCK_PROVIDER

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def complete(self, request):
        index = min(self.calls, len(self._replies) - 1)
        reply = self._replies[index]
        self.calls += 1
        return providers.MockProvider(reply=reply).complete(request)


class _FailsOnSecondCall:
    """The first call succeeds with a bad reply; the second (the repair) fails
    at the provider level — the shape `gateway.call_model` already handles
    internally (records a `failed` `model_calls` row, does not raise)."""

    name = providers.MOCK_PROVIDER

    def __init__(self, first_reply):
        self._first_reply = first_reply
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return providers.MockProvider(reply=self._first_reply).complete(request)
        raise providers.ProviderCallError("simulated repair-call failure", execution_unknown=False)


class _DeadProvider:
    """A provider that is down, the way Ollama's Metal backend was down on
    2026-09-15: every call raises, `gateway.call_model` records the row as
    `failed` (or `execution_unknown`) and returns it rather than raising, and
    the caller is handed a `ModelCall` with no reply in it.

    `message` stands in for the real one — `HTTPError 500 from ollama:
    llama-server process has terminated: MTLLibraryErrorDomain` — which is
    what the deliberation record must end up naming."""

    name = providers.MOCK_PROVIDER

    def __init__(self, message="the backend is down", *, execution_unknown=False):
        self._message = message
        self._execution_unknown = execution_unknown
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        raise providers.ProviderCallError(
            self._message, execution_unknown=self._execution_unknown
        )


def test_a_repaired_reply_is_recorded_as_proposed(conn):
    """The headline case: a bad first reply followed by a valid repair reply
    ends up PROPOSED, not UNPARSEABLE, and both calls are on the record."""
    cell = _make_cell(conn)
    provider = _SequencedProvider(["not json", _valid_reply()])

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )

    assert result.status == deliberation.DeliberationStatus.PROPOSED
    assert result.model_call_id is not None
    assert result.repair_model_call_id is not None
    assert result.model_call_id != result.repair_model_call_id
    assert result.proposal_id is not None
    assert provider.calls == 2


def test_a_second_failed_reply_is_still_unparseable_and_bounded_to_one_retry(conn):
    """Two bad replies in a row end the wake — never a third attempt.
    `MAX_PARSE_REPAIR_ATTEMPTS` is 1, and this is the behavioural proof of it:
    a provider that always fails is called exactly twice, not repeatedly."""
    cell = _make_cell(conn)
    provider = _SequencedProvider(["not json", "still not json"])

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )

    assert result.status == deliberation.DeliberationStatus.UNPARSEABLE
    assert result.repair_model_call_id is not None
    assert "repair reply also failed to validate" in result.failure_reason
    assert provider.calls == 2
    assert _model_call_count(conn) == 2


def test_repair_is_idempotent_on_wake_key(conn):
    """Charter C6: a redelivered wake must not pay for a third call. The outer
    `wake_key` guard in `deliberate()` already returns the existing
    deliberation before any of this runs — proven here across a repair
    specifically, since that is the path with two calls to not repeat."""
    cell = _make_cell(conn)
    provider = _SequencedProvider(["not json", _valid_reply()])

    first = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )
    second = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )

    assert second.deliberation_id == first.deliberation_id
    assert provider.calls == 2, "the redelivered wake must not call the provider again"
    assert _model_call_count(conn) == 2


def test_a_provider_failure_on_the_repair_names_the_provider_not_the_reply(conn):
    """The wake is still UNPARSEABLE — the *first* reply genuinely did not
    validate, and that outcome is the Cell's — but the record must not go on
    to say the repair produced a reply that also failed to validate when the
    repair produced no reply at all (§24.2; ADR-101, correcting ADR-069's
    "needs no special handling ... flows through the same path")."""
    cell = _make_cell(conn)
    provider = _FailsOnSecondCall("not json")

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )

    assert result.status == deliberation.DeliberationStatus.UNPARSEABLE
    assert result.repair_model_call_id is not None, (
        "the repair call was made and §24.1 wants it traceable, even though it "
        "returned nothing and — being `failed` rather than `execution_unknown` — "
        "cost nothing"
    )
    assert "repair call failed at the provider" in result.failure_reason
    assert "simulated repair-call failure" in result.failure_reason
    assert "repair reply also failed to validate" not in result.failure_reason


def test_a_repair_that_cannot_even_be_attempted_falls_back_gracefully(conn, monkeypatch):
    """The pre-repair behaviour is the floor: if the repair attempt itself
    cannot even be made — a real-spend cap, an exhausted balance, an unpriced
    model, anything `gateway.call_model` can raise before a reservation
    exists — `deliberate()` must still return an UNPARSEABLE deliberation
    rather than raising mid-wake, exactly what would have happened before
    this mechanism existed. `gateway.call_model` is monkeypatched to let the
    first (real) call through and raise a real-spend cap on the second,
    standing in for whichever economic refusal fires in production — the ones
    `_attempt_parse_repair` catches on purpose (`_REPAIR_UNATTEMPTABLE_ERRORS`)."""
    cell = _make_cell(conn)
    real_call_model = deliberation.gateway.call_model
    calls = {"n": 0}

    def flaky_call_model(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_call_model(*args, **kwargs)
        raise real_spend_breaker.RealSpendCapExceededError(
            "simulated cap: the repair attempt could not be reserved"
        )

    monkeypatch.setattr(deliberation.gateway, "call_model", flaky_call_model)

    result = _deliberate(conn, cell, "not json")

    assert result.status == deliberation.DeliberationStatus.UNPARSEABLE
    assert result.repair_model_call_id is None, "no call was ever made, so nothing to point at"
    assert "repair not attempted" in result.failure_reason
    assert _model_call_count(conn) == 1


def test_a_bug_in_the_repair_path_propagates_rather_than_masquerading(conn, monkeypatch):
    """A genuine fault on the repair call — a programming error, a locked or
    corrupt database, anything outside `_REPAIR_UNATTEMPTABLE_ERRORS` — must
    NOT be swallowed and recorded as "the model could not format its reply."
    It propagates, exactly as it already would from the first, unwrapped
    `gateway.call_model` in `deliberate()`. This is the teeth of narrowing the
    catch from a blanket `except Exception` (the finding ADR-069's first pass
    left open): a blanket catch would have turned this bug into a silent
    UNPARSEABLE row with the traceback buried in `failure_reason`."""
    cell = _make_cell(conn)
    real_call_model = deliberation.gateway.call_model
    calls = {"n": 0}

    def buggy_call_model(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_call_model(*args, **kwargs)
        raise RuntimeError("a bug in the repair path, not an economic refusal")

    monkeypatch.setattr(deliberation.gateway, "call_model", buggy_call_model)

    with pytest.raises(RuntimeError, match="a bug in the repair path"):
        _deliberate(conn, cell, "not json")


def test_ledger_conservation_holds_across_a_repaired_wake(conn):
    """Two billed calls in one wake must not desynchronise the books — the
    same guarantee every other gateway path already carries, exercised here
    specifically because this is the first caller that can make two calls
    from one `deliberate()` invocation."""
    cell = _make_cell(conn)
    provider = _SequencedProvider(["not json", _valid_reply()])
    deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_conservation(conn, Book.RESOURCE)
    assert ledger.verify_chain(conn)


# --- a call that failed at the provider (ADR-101) -----------------------------


def test_a_call_that_failed_at_the_provider_is_not_the_cells_unparseable_reply(conn):
    """§24.2: provider change is an *environment* regime change and must not
    be mistaken for Cell behaviour. `gateway.call_model` does not raise on a
    provider failure — it classifies it, records it, and returns the call —
    so an outage reaches this module as a `ModelCall` carrying no reply, and
    reading `response_text or ""` past that classification records the
    provider's weather as this genome's inability to answer in the required
    shape."""
    cell = _make_cell(conn)
    provider = _DeadProvider("llama-server process has terminated: MTLLibraryErrorDomain")

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )

    assert result.status == deliberation.DeliberationStatus.CALL_FAILED
    assert result.status != deliberation.DeliberationStatus.UNPARSEABLE
    assert "MTLLibraryErrorDomain" in result.failure_reason, (
        "the record must name the failure the gateway observed, not a story "
        "composed here about a reply that never arrived"
    )
    assert "is not JSON" not in result.failure_reason


def test_a_failed_call_buys_no_parse_repair(conn):
    """ADR-069's one re-prompt exists to fix a *reply*. There is no reply to
    re-prompt about, and the only provider a repair could call is the one that
    just failed — so a wake lost to an outage must cost exactly one call, not
    two. This is the behaviour that was observed failing on 2026-09-15: two
    `model_calls` rows, both `failed`, one wake."""
    cell = _make_cell(conn)
    provider = _DeadProvider()

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )

    assert provider.calls == 1
    assert _model_call_count(conn) == 1
    assert result.repair_model_call_id is None


def test_the_failed_call_itself_stays_on_the_record(conn):
    """§24.1 wants every call traceable. A `call_failed` deliberation names
    the call that failed, and that row carries the gateway's own classification
    — which is the independent record the deliberation's `failure_reason` is
    only repeating (§0.3's discipline, applied between two kernel layers)."""
    cell = _make_cell(conn)

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=_DeadProvider(), wake_key="w1", model="mock-1",
    )

    assert result.model_call_id is not None
    call = gateway.get_model_call(conn, result.model_call_id)
    assert call.status is ModelCallStatus.FAILED
    assert call.response_text is None


def test_an_execution_unknown_call_is_a_call_failure_too(conn):
    """The other half of §4.4's failure split: a timeout may already have been
    billed, so the funds stay committed and reconciliation resolves it. Either
    way this Cell got no reply, so the deliberation outcome is the same one —
    and `failure_reason` names which of the two it was, because the money
    consequence differs."""
    cell = _make_cell(conn)
    provider = _DeadProvider("read timed out", execution_unknown=True)

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )

    assert result.status == deliberation.DeliberationStatus.CALL_FAILED
    assert "execution_unknown" in result.failure_reason
    call = gateway.get_model_call(conn, result.model_call_id)
    assert call.status is ModelCallStatus.EXECUTION_UNKNOWN


def test_an_empty_reply_from_a_call_that_succeeded_is_still_the_cells_failure(conn):
    """The discriminating case, and the reason the guard reads `status` rather
    than the text. A model that answers with nothing *did* answer: the call
    succeeded, was billed, and the empty reply is the Cell's own output — so
    it stays UNPARSEABLE and still buys its one repair. A fix that keyed on
    `not reply` instead would silently reclassify this as a provider outage
    and stop re-prompting a model that can be re-prompted."""
    cell = _make_cell(conn)
    provider = _SequencedProvider(["", _valid_reply()])

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )

    assert result.status == deliberation.DeliberationStatus.PROPOSED
    assert result.repair_model_call_id is not None
    assert provider.calls == 2


def test_a_wake_lost_to_an_outage_conserves_money_and_is_audited(conn):
    """A failed call releases its reservations (`gateway._handle_failure`), so
    the books must be exactly where they were — and Charter C10 wants the
    event itself visible, since a colony whose provider is down looks, in the
    deliberation table alone, like a colony whose Cells stopped proposing."""
    cell = _make_cell(conn)
    before = ledger.get_balance(conn, f"cell:{cell.cell_id}:cash", Book.USD_REAL)

    deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=_DeadProvider(), wake_key="w1", model="mock-1",
    )

    assert ledger.get_balance(conn, f"cell:{cell.cell_id}:cash", Book.USD_REAL) == before
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_conservation(conn, Book.RESOURCE)
    assert ledger.verify_chain(conn)
    events_recorded = [
        r["event_type"]
        for r in conn.execute("SELECT event_type FROM audit_events WHERE cell_id = ?", (cell.cell_id,))
    ]
    assert "cell_deliberation_call_failed" in events_recorded
    assert "cell_deliberation_unparseable" not in events_recorded


def test_the_schema_refuses_a_deliberation_status_it_does_not_know(conn):
    """ADR-047's discipline: the four outcomes are a closed set in the schema,
    not only in `DeliberationStatus`. Migration 0041 widened the CHECK to
    admit `call_failed` — it must not have widened it to admit anything."""
    cell = _make_cell(conn)
    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=_DeadProvider(), wake_key="w1", model="mock-1",
    )
    assert result.status == deliberation.DeliberationStatus.CALL_FAILED

    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        conn.execute(
            "UPDATE deliberations SET status = 'provider_down' WHERE deliberation_id = ?",
            (result.deliberation_id,),
        )


def test_the_schema_refuses_a_call_failure_that_names_no_call_or_a_repair(conn):
    """The two things `call_failed` means, made unrepresentable rather than
    only implemented (ADR-047's discipline): a row naming no call is a
    *refusal* wearing the wrong status, and a row naming a repair contradicts
    the decision that an outage buys none. `deliberation.py` writes neither —
    these CHECKs are what stops a future caller in another module doing so."""
    cell = _make_cell(conn)
    failed = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=_DeadProvider(), wake_key="w1", model="mock-1",
    )
    parsed = _deliberate(conn, cell, wake_key="w2")

    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        conn.execute(
            "UPDATE deliberations SET model_call_id = NULL WHERE deliberation_id = ?",
            (failed.deliberation_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        conn.execute(
            "UPDATE deliberations SET repair_model_call_id = ? WHERE deliberation_id = ?",
            (parsed.model_call_id, failed.deliberation_id),
        )


def test_every_declared_deliberation_status_is_one_the_schema_admits(conn):
    """`DeliberationStatus` and migration 0041's CHECK are two lists of the
    same closed set, and a slice that adds to one and forgets the other fails
    at runtime on a path that only fires when something has *already* gone
    wrong — a provider outage, a dead Cell. Pinned together structurally, the
    way `test_every_declared_structure_has_a_runner` pins the genome's workflow
    structures to their runners: each declared value is written to the column
    and rolled back, so the schema itself answers. The probe row is an ordinary
    proposed deliberation — one call, no repair — so it satisfies the row-shape
    CHECKs above and the *status* is the only thing under test."""
    cell = _make_cell(conn)
    result = _deliberate(conn, cell)
    declared = {
        value
        for name, value in vars(deliberation.DeliberationStatus).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    assert deliberation.DeliberationStatus.CALL_FAILED in declared

    for status in sorted(declared):
        conn.execute("SAVEPOINT probe")
        try:
            conn.execute(
                "UPDATE deliberations SET status = ? WHERE deliberation_id = ?",
                (status, result.deliberation_id),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - the failure is the point
            raise AssertionError(f"the schema does not admit {status!r}: {exc}") from exc
        finally:
            conn.execute("ROLLBACK TO probe")
            conn.execute("RELEASE probe")


def _connect_pre_migration_41() -> sqlite3.Connection:
    """Migrated through 0040, one short of the widened CHECK, so a test can
    write rows in the old shape and watch 0041 carry them across the rebuild."""
    conn = db.connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  filename TEXT PRIMARY KEY,"
        "  applied_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ")"
    )
    for migration_path in db._migration_files():
        if migration_path.name >= "0041_":
            break
        conn.executescript(migration_path.read_text())
        conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES (?)", (migration_path.name,)
        )
    return conn


def test_the_rebuild_keeps_every_row_and_every_child_reference():
    """SQLite cannot ALTER a CHECK, so 0041 rebuilds `deliberations` — and
    three tables point at it (`proposals`, `deliberation_predictions`,
    `artifacts`). A rebuild that dropped a row, or left a child pointing at a
    table that no longer exists, would lose the Cell history the whole record
    is for. One child of each kind is present across the migration."""
    conn = _connect_pre_migration_41()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        INSERT INTO cells (cell_id, cell_type, genome_hash, book, status,
                           created_at_utc, idempotency_key, generation)
        VALUES ('c1', 'explorer', 'g1', 'USD_SIM', 'alive', 't', 'k1', 0);
        INSERT INTO deliberations (
            deliberation_id, cell_id, wake_key, wake_reason, genome_hash,
            model_call_id, context_json, context_tokens, context_dropped_json,
            status, failure_reason, created_at_utc, repair_model_call_id
        ) VALUES
            ('d1', 'c1', 'w1', 'scheduled research cycle', 'g1', NULL,
             '{}', 10, '[]', 'proposed', NULL, 't', NULL),
            ('d2', 'c1', 'w2', 'scheduled research cycle', 'g1', 'mc-first',
             '{}', 10, '[]', 'unparseable', 'reply is not JSON', 't', 'mc-repair'),
            ('d3', 'c1', 'w3', 'scheduled research cycle', 'g1', NULL,
             '{}', 0, '[]', 'refused', 'cell is dead', 't', NULL);
        INSERT INTO proposals (
            proposal_id, deliberation_id, cell_id, kind, summary, rationale,
            risk_tier, estimated_cost_minor_units, payload_json, created_at_utc
        ) VALUES ('p1', 'd1', 'c1', 'experiment', 's', 'r', 'LOW', 0, '{}', 't');
        INSERT INTO prediction_register (
            prediction_id, cell_id, claim, probability, resolves_by_utc,
            created_at_utc, previous_hash, prediction_hash, idempotency_key
        ) VALUES ('pr1', 'c1', 'revenue >= 50', 0.4, 't', 't', NULL, 'h', 'k2');
        INSERT INTO deliberation_predictions (deliberation_id, prediction_id)
        VALUES ('d1', 'pr1');
        INSERT INTO artifacts (
            artifact_id, artifact_hash, kind, title, content, content_bytes,
            created_by_cell_id, created_by_deliberation_id, created_at_utc,
            licence, permitted_uses, commercial_use, contains_personal_data,
            retention_rule, source_summary
        ) VALUES ('a1', 'h1', 'report', 't', 'c', 1, 'c1', 'd1', 't',
                  'unknown', 'review', 'unknown', 'unknown', 'retain', 'none');
        """
    )

    def dangling():
        return {tuple(r) for r in conn.execute("PRAGMA foreign_key_check")}

    # The fixture references a genome and a model call it does not create —
    # writing valid ones means a reservation chain three tables deep that says
    # nothing more about this rebuild — so the claim is that the migration
    # adds no dangling reference, not that the fixture had none.
    before = dangling()

    (path,) = [p for p in db._migration_files() if p.name.startswith("0041_")]
    conn.executescript(path.read_text())

    rows = {
        r["deliberation_id"]: r["status"]
        for r in conn.execute("SELECT deliberation_id, status FROM deliberations")
    }
    assert sorted(rows) == ["d1", "d2", "d3"]
    assert rows == {"d1": "proposed", "d2": "unparseable", "d3": "refused"}
    assert conn.execute(
        "SELECT repair_model_call_id FROM deliberations WHERE deliberation_id = 'd2'"
    ).fetchone()[0] == "mc-repair"
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert dangling() == before
    indexes = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND tbl_name = 'deliberations' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    assert "idx_deliberations_cell" in indexes, "a rebuild is where an index goes missing"
    # Each child still resolves to the deliberation it was written against —
    # the join, not just the row count, because a rebuild that renamed or
    # reordered the key would leave both tables populated and unjoinable.
    for child, key in (
        ("proposals", "deliberation_id"),
        ("deliberation_predictions", "deliberation_id"),
        ("artifacts", "created_by_deliberation_id"),
    ):
        joined = conn.execute(
            f"SELECT COUNT(*) FROM {child} c "
            f"JOIN deliberations d ON d.deliberation_id = c.{key}"
        ).fetchone()[0]
        assert joined == 1, f"{child} lost its reference to the rebuilt table"
    # The rebuilt table admits the new status and still refuses an unknown one.
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        conn.execute(
            "UPDATE deliberations SET status = 'provider_down' WHERE deliberation_id = 'd2'"
        )
    # …and refuses the two rows `call_failed` cannot mean: one naming no call
    # (that is a refusal) and one naming a repair (a wake with no reply buys
    # none). d2 carries both columns, so each CHECK is reached in turn.
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        conn.execute(
            "UPDATE deliberations SET status = 'call_failed' WHERE deliberation_id = 'd2'"
        )
    conn.execute(
        "UPDATE deliberations SET repair_model_call_id = NULL WHERE deliberation_id = 'd2'"
    )
    conn.execute(
        "UPDATE deliberations SET status = 'call_failed' WHERE deliberation_id = 'd2'"
    )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        conn.execute(
            "UPDATE deliberations SET status = 'call_failed' WHERE deliberation_id = 'd3'"
        )
    # The UNIQUE on wake_key is the outer idempotency guard (Charter C6) and a
    # rebuild is exactly where a constraint gets quietly left behind. The
    # migration script re-enables foreign keys on its last line, so they go back
    # off here and the error is matched by name — otherwise this passes on the
    # fixture's dangling genome reference whether or not the UNIQUE survived
    # (which is how a teeth check found it passing for the wrong reason).
    conn.execute("PRAGMA foreign_keys = OFF")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed: deliberations.wake_key"):
        conn.execute(
            "INSERT INTO deliberations (deliberation_id, cell_id, wake_key, wake_reason,"
            " genome_hash, context_json, context_tokens, context_dropped_json, status,"
            " created_at_utc) VALUES ('d4', 'c1', 'w1', 'r', 'g1', '{}', 0, '[]',"
            " 'proposed', 't')"
        )


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


def test_abstaining_with_no_risk_tier_is_recorded_not_rejected(conn):
    """ADR-068, end to end: the two failure shapes that motivated it
    (`qwen2.5` dropping the key, `llama3.2` sending `null`) must reach a
    recorded proposal rather than an `UNPARSEABLE` deliberation."""
    cell = _make_cell(conn)
    payload = json.loads(_valid_reply(
        kind="abstain",
        summary="nothing worth doing this cycle",
        rationale="no signal has changed since the last wake",
        predictions=[],
    ))
    del payload["risk_tier"]

    result = _deliberate(conn, cell, json.dumps(payload))

    assert result.status == deliberation.DeliberationStatus.PROPOSED
    stored = deliberation.get_proposal(conn, result.proposal_id)
    assert stored["kind"] == "abstain"
    assert stored["risk_tier"] is None


def test_the_schema_itself_refuses_a_null_risk_tier_on_a_non_abstain_kind(conn):
    """ADR-047's discipline applied here: `_risk_tier_matches_kind` is not the
    only thing standing between a non-abstain proposal and a missing risk
    tier — migration 0032's CHECK constraint makes the row unrepresentable
    regardless of which future caller writes to `proposals` directly."""
    cell = _make_cell(conn)
    result = _deliberate(conn, cell)
    assert result.status == deliberation.DeliberationStatus.PROPOSED

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO proposals (
                proposal_id, deliberation_id, cell_id, kind, summary, rationale,
                risk_tier, estimated_cost_minor_units, derived_from_untrusted,
                payload_json, created_at_utc
            ) VALUES ('bad-proposal', ?, ?, 'spend_request', 'x', 'x',
                      NULL, 0, 0, '{}', '2026-01-01T00:00:00Z')
            """,
            (result.deliberation_id, cell.cell_id),
        )


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


# --- ADR-102: the repair turn must not narrow the reply ------------------------


#: The abstain reply `claude-haiku-4-5` actually sent on 2026-09-16, before any
#: repair: a correct `summary`, and neither of the two other keys every reply
#: owes. Reproduced verbatim so the regression is anchored to the observed
#: failure rather than to a convenient stand-in.
_OBSERVED_FIRST_REPLY = json.dumps(
    {"kind": "abstain", "summary": "No proposal at this scheduled cycle."}
)


class _SuppliesExactlyTheKeysNamed:
    """A model that answers a repair turn with an object carrying exactly the
    proposal keys that turn *mentions*, and nothing else.

    **This encodes one measured behaviour, not a claim about models in
    general.** On 2026-09-16 `claude-haiku-4-5` was told
    `rationale: Field required; estimated_cost_minor_units: Field required`
    and replied with an object holding those two keys — having silently dropped
    the `summary` it had produced correctly one turn earlier. The repair turn
    named two keys, so the reply had two keys. That is the behaviour this double
    reproduces, and it is the reason a repair turn that names only the error can
    hand back a reply strictly worse than the one it was repairing.

    A canned reply cannot respond to prompt wording at all (`MockProvider`'s
    reply is an input — ADR-049), so this is the nearest a test can get to the
    live failure without spending money. What it genuinely proves is
    conditional and worth stating plainly: *if* the model supplies the keys it
    is told to supply, the repair turn has to tell it all of them.
    """

    name = providers.MOCK_PROVIDER

    def __init__(self, first_reply=_OBSERVED_FIRST_REPLY):
        self._first_reply = first_reply
        self.calls = 0
        self.repair_turn = None

    def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return providers.MockProvider(reply=self._first_reply).complete(request)

        self.repair_turn = request.messages[-1]["content"]
        named = [
            key
            for key in proposal.Proposal.model_fields
            if key in self.repair_turn
        ]
        values = {
            "kind": "abstain",
            "summary": "No proposal at this scheduled cycle.",
            "rationale": "nothing in the context is worth a call this wake",
            "estimated_cost_minor_units": 0,
        }
        reply = {key: values[key] for key in named if key in values}
        return providers.MockProvider(reply=json.dumps(reply)).complete(request)


def test_the_repair_turn_names_every_key_a_reply_must_carry(conn):
    """The guard, stated where it is enforced.

    A repair turn that names a *subset* of the required keys reads to a small
    model as a specification of the whole reply, not as a patch to one. Naming
    all of them costs a handful of tokens and removes the failure mode; the
    list is derived from the schema, so it cannot drift from what the parser
    demands.
    """
    instruction = deliberation._repair_instruction("summary: Field required")

    missing = [
        key for key in proposal.always_required_keys() if key not in instruction
    ]
    assert missing == [], (
        f"the repair turn does not name {missing}, so a model that supplies "
        "exactly what it is asked for will omit them"
    )


def test_a_repair_does_not_drop_a_field_the_first_reply_got_right(conn):
    """The observed 2026-09-16 failure, end to end: an abstain reply missing
    two required keys, repaired by a model that supplies the keys it is told
    to supply.

    Before ADR-102 this wake ended UNPARSEABLE after two billed calls, and the
    second reply was *worse* than the first — it had traded a correct `summary`
    for the two fields the error named. The repair now has to leave the model
    able to produce a complete object.
    """
    cell = _make_cell(conn)
    provider = _SuppliesExactlyTheKeysNamed()

    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key="w1", model="mock-1",
    )

    assert result.status == deliberation.DeliberationStatus.PROPOSED, (
        f"the repair reply still did not validate: {result.failure_reason}"
    )
    assert provider.calls == 2
    assert result.repair_model_call_id is not None

    row = conn.execute(
        "SELECT kind, summary FROM proposals WHERE proposal_id = ?", (result.proposal_id,)
    ).fetchone()
    assert row["kind"] == "abstain"
    assert row["summary"] == "No proposal at this scheduled cycle.", (
        "the summary the first reply got right did not survive the repair"
    )


def test_the_repair_request_still_shows_the_model_its_own_failed_reply(conn):
    """The precondition for asking a model to *edit* rather than regenerate.

    The repair turn says "correct the JSON object you just sent"; that
    instruction is empty unless the object is actually in the request. It is
    the middle of three messages — original prompt, the failed reply as the
    assistant turn, the correction request — and a refactor that dropped it
    would leave the wording pointing at nothing.
    """
    cell = _make_cell(conn)
    captured = []

    class _Capturing:
        name = providers.MOCK_PROVIDER

        def __init__(self):
            self.calls = 0

        def complete(self, request):
            self.calls += 1
            captured.append(request.messages)
            return providers.MockProvider(reply="not json").complete(request)

    deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=_Capturing(), wake_key="w1", model="mock-1",
    )

    repair_messages = captured[1]
    assert [m["role"] for m in repair_messages] == ["user", "assistant", "user"]
    assert repair_messages[1]["content"] == "not json", (
        "the reply being repaired is not in the repair request"
    )
