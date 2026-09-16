"""Workflow structure as a genome gene (SPEC.md §14.1 "critic addition/removal",
§16.3 "workflow structure", Charter C4, C6, C15; ADR-093).

A genome's `workflow.structure` chooses how many calls one wake makes and how
they relate — a single pass, a draft revised by self-critique, or two
independent drafts and a review. The properties defended here are the ones
that keep a multi-call wake inside the kernel's guarantees: the genome chooses
from a closed set and supplies nothing; every further call is its own gateway
reservation on its own idempotency key; the draft already in hand is the
floor, never lost to a failing step; an unaffordable step degrades while a
genuine fault propagates; and a genome declaring nothing wakes exactly as before.
"""

from __future__ import annotations

import json

import pytest

from mitosis import deliberation, gateway, genome, ledger, lifecycle, providers
from mitosis.models import Book, CellType, EntrySpec
from mitosis.simulation import mutation

GENOME = {
    "market": "small accounting firms",
    "problem": "month-end close is manual",
}


def _proposal(summary: str) -> str:
    return json.dumps({
        "kind": "experiment",
        "summary": summary,
        "rationale": "a cheap probe is the fastest way to a realised record",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 50,
        "predictions": [],
        "experiment": {"hypothesis": f"{summary} finds demand"},
    })


def _candidates(*summaries: str) -> str:
    return json.dumps({
        "candidates": [
            {**json.loads(_proposal(summary)), "probability": 0.3} for summary in summaries
        ]
    })


class _Recording:
    name = providers.MOCK_PROVIDER

    def __init__(self, replies):
        self._replies = list(replies)
        self.requests: list[providers.ModelRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def complete(self, request):
        """A reply that is a `ProviderError` is raised instead of returned —
        the provider being down for that step, which `gateway.call_model`
        records and returns rather than raising (ADR-101). The request is
        recorded first either way, so `calls` counts the attempt."""
        reply = self._replies[min(len(self.requests), len(self._replies) - 1)]
        self.requests.append(request)
        if isinstance(reply, providers.ProviderError):
            raise reply
        return providers.MockProvider(reply=reply).complete(request)


def _text(request) -> str:
    return "\n".join(str(m["content"]) for m in request.messages)


def _make_cell(conn, *, structure: str | None, candidates: int | None = None, key: str = "wf"):
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100, book=Book.USD_SIM,
        idempotency_key=key,
    )
    content = dict(GENOME)
    if structure is not None:
        content["workflow"] = {"structure": structure}
    if candidates is not None:
        content["model_policy"] = {"verbalized_candidates": candidates}
    genome_hash = lifecycle._get_or_create_genome(conn, CellType.EXPLORER, mutation=content)
    conn.execute("UPDATE cells SET genome_hash = ? WHERE cell_id = ?", (genome_hash, cell.cell_id))
    conn.commit()
    for book, currency in ((Book.USD_REAL, "USD"), (Book.RESOURCE, "RESOURCE"), (Book.USD_SIM, "USD")):
        ledger.post_transaction(
            conn, book=book, currency=currency, transaction_type="cell_birth_funding",
            idempotency_key=f"fund:{cell.cell_id}:{book.value}", description="fund",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-100_000, cell_id=cell.cell_id),
                EntrySpec(account_id=f"cell:{cell.cell_id}:cash", amount_minor_units=100_000,
                          cell_id=cell.cell_id),
            ],
        )
    return lifecycle.get_cell(conn, cell.cell_id)


def _deliberate(conn, cell, provider, *, wake_key="w1"):
    return deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key=wake_key, model="mock-1",
    )


def _recorded_summary(conn, cell) -> str:
    (proposal,) = deliberation.list_proposals(conn, cell_id=cell.cell_id)
    return proposal["summary"]


def _metadata(conn) -> dict:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(audit_events)")]
    column = next(name for name in columns if "metadata" in name)
    (row,) = conn.execute(
        f"SELECT {column} FROM audit_events WHERE event_type = 'cell_deliberated'"
    ).fetchall()
    return json.loads(row[0])


# --- the gene -----------------------------------------------------------------


def test_a_genome_declaring_no_structure_runs_a_single_pass():
    for content in (None, {}, {"workflow": "probe cheaply, measure, iterate"}, {"workflow": {}}):
        assert genome.workflow_structure_of(content) == genome.WORKFLOW_SINGLE_PASS


@pytest.mark.parametrize("structure", ["sequential", "swarm", 3, None])
def test_a_structure_the_kernel_does_not_run_is_refused_by_name(structure):
    """A structure nothing runs would wake as a single pass while the genome
    claimed otherwise — the silently-ignored field `MODEL_POLICY_FIELDS` is
    closed to prevent."""
    with pytest.raises(genome.GenomeError, match="workflow.structure"):
        genome.canonical_genome_json(CellType.EXPLORER, {"workflow": {"structure": structure}})


def test_a_prose_workflow_stays_valid_and_selects_nothing():
    content = genome.canonical_genome_json(CellType.EXPLORER, {"workflow": "probe, measure, iterate"})
    assert genome.workflow_structure_of(content) == genome.WORKFLOW_SINGLE_PASS


def test_every_declared_structure_has_a_runner():
    assert set(deliberation._WORKFLOW_RUNNERS) | {genome.WORKFLOW_SINGLE_PASS} == set(
        genome.WORKFLOW_STRUCTURES
    )


def test_the_simulator_can_only_breed_structures_the_kernel_runs():
    """Its operator once drew from four names no code read; one of them is now
    refused at birth. A mutated genome must always validate."""
    assert set(mutation._WORKFLOW_STRUCTURES) == set(genome.WORKFLOW_STRUCTURES)
    parent = {"workflow": {"structure": genome.WORKFLOW_SINGLE_PASS}}
    for seed in ("a", "b", "c", "d", "e", "f"):
        overlay, _ = mutation.workflow_variation(parent, seed=seed)
        genome.inherit(parent, overlay, cell_type=CellType.EXPLORER)


# --- a single pass is unchanged ---------------------------------------------------


def test_a_single_pass_wake_makes_one_call_and_records_no_workflow(conn):
    cell = _make_cell(conn, structure=None)
    provider = _Recording([_proposal("probe firms")])
    _deliberate(conn, cell, provider)
    assert provider.calls == 1
    assert "workflow" not in _metadata(conn)


# --- iterative refinement ---------------------------------------------------------


def test_refinement_shows_the_model_its_draft_and_records_the_revision(conn):
    cell = _make_cell(conn, structure="iterative_refinement")
    provider = _Recording([_proposal("draft idea"), _proposal("revised idea")])
    _deliberate(conn, cell, provider)

    assert provider.calls == 2
    revise = provider.requests[1]
    assert revise.messages[1]["role"] == "assistant"
    assert "draft idea" in revise.messages[1]["content"]
    assert deliberation._refinement_instruction() == revise.messages[2]["content"]
    assert _recorded_summary(conn, cell) == "revised idea"
    workflow = _metadata(conn)["workflow"]
    assert workflow["structure"] == "iterative_refinement"
    assert [s["step"] for s in workflow["steps"]] == ["revise"]
    assert workflow["recorded"] == "final"


def test_a_revision_that_does_not_validate_keeps_the_draft(conn):
    cell = _make_cell(conn, structure="iterative_refinement")
    provider = _Recording([_proposal("draft idea"), "I would rather not"])
    _deliberate(conn, cell, provider)

    assert _recorded_summary(conn, cell) == "draft idea"
    workflow = _metadata(conn)["workflow"]
    assert workflow["recorded"] == "first_draft"
    (step,) = workflow["steps"]
    assert step["note"].startswith("did not validate")
    assert step["model_call_id"] is not None, "a call that was made and billed must stay traceable"


def test_a_repaired_draft_is_still_refined(conn):
    cell = _make_cell(conn, structure="iterative_refinement")
    provider = _Recording(["not json", _proposal("repaired idea"), _proposal("revised idea")])
    _deliberate(conn, cell, provider)
    assert provider.calls == 3
    assert "repaired idea" in provider.requests[2].messages[1]["content"]
    assert _recorded_summary(conn, cell) == "revised idea"


def test_a_step_that_fails_at_the_provider_keeps_the_draft_and_says_so(conn):
    """A workflow step whose call never reached a model leaves the wake exactly
    where a single pass would have left it — the draft is the floor — but the
    step's note must not report a reply that did not validate when no reply
    arrived (§24.2; ADR-101). The draft already validated, so the wake is still
    PROPOSED: the outage costs the refinement, not the proposal."""
    cell = _make_cell(conn, structure="iterative_refinement")
    provider = _Recording([
        _proposal("draft idea"),
        providers.ProviderCallError("the backend is down", execution_unknown=False),
    ])
    result = _deliberate(conn, cell, provider)

    assert result.status == deliberation.DeliberationStatus.PROPOSED
    assert _recorded_summary(conn, cell) == "draft idea"
    workflow = _metadata(conn)["workflow"]
    assert workflow["recorded"] == "first_draft"
    (step,) = workflow["steps"]
    assert "the backend is down" in step["note"]
    assert step["note"].startswith("call failed at the provider")
    assert "did not validate" not in step["note"]
    assert step["model_call_id"] is not None, "the call was made and stays traceable (§24.1)"


def test_a_first_call_that_fails_at_the_provider_never_reaches_the_workflow(conn):
    """The draft is the floor and there is no draft: a wake whose very first
    call failed is recorded as a call failure and buys nothing further — not a
    repair, not a refinement."""
    cell = _make_cell(conn, structure="iterative_refinement")
    provider = _Recording([providers.ProviderCallError("down", execution_unknown=False)])
    result = _deliberate(conn, cell, provider)

    assert result.status == deliberation.DeliberationStatus.CALL_FAILED
    assert provider.calls == 1


def test_an_unparseable_wake_buys_no_further_calls(conn):
    cell = _make_cell(conn, structure="parallel_review")
    provider = _Recording(["not json", "still not json"])
    result = _deliberate(conn, cell, provider)
    assert result.status == deliberation.DeliberationStatus.UNPARSEABLE
    assert provider.calls == 2  # the draft and its one repair, nothing more


# --- parallel review ----------------------------------------------------------------


def test_parallel_review_drafts_independently_then_reviews_both(conn):
    cell = _make_cell(conn, structure="parallel_review")
    provider = _Recording([_proposal("idea A"), _proposal("idea B"), _proposal("reviewed idea")])
    _deliberate(conn, cell, provider)

    assert provider.calls == 3
    first, second, review = provider.requests
    assert _text(second) == _text(first), "a second draft that saw the first is a revision, not a draft"
    assert "idea A" in _text(review) and "idea B" in _text(review)
    assert _recorded_summary(conn, cell) == "reviewed idea"
    workflow = _metadata(conn)["workflow"]
    assert [s["step"] for s in workflow["steps"]] == ["draft:1", "review"]
    assert workflow["recorded"] == "final"


def test_a_second_draft_that_does_not_validate_skips_the_review(conn):
    cell = _make_cell(conn, structure="parallel_review")
    provider = _Recording([_proposal("idea A"), "garbage"])
    _deliberate(conn, cell, provider)
    assert provider.calls == 2
    assert _recorded_summary(conn, cell) == "idea A"
    assert [s["step"] for s in _metadata(conn)["workflow"]["steps"]] == ["draft:1"]


def test_drafts_get_the_draft_budget_and_the_review_gets_one_proposals(conn):
    cell = _make_cell(conn, structure="parallel_review", candidates=3)
    provider = _Recording([
        _candidates("a1", "a2", "a3"), _candidates("b1", "b2", "b3"), _proposal("reviewed"),
    ])
    _deliberate(conn, cell, provider)
    budgets = [r.max_tokens for r in provider.requests]
    assert budgets == [deliberation.DEFAULT_MAX_TOKENS * 3] * 2 + [deliberation.DEFAULT_MAX_TOKENS]
    review = _text(provider.requests[2])
    assert deliberation._system_prompt(3) not in review
    assert deliberation._system_prompt() in review


# --- the gateway, idempotency, and failure ------------------------------------------------


def test_every_call_of_a_structure_is_its_own_gateway_call(conn):
    """Charter C4: no call escapes a reservation. A step that reached the
    provider without passing through `gateway.call_model` would appear here as
    a provider call with no `model_calls` row."""
    cell = _make_cell(conn, structure="parallel_review")
    provider = _Recording([_proposal("A"), _proposal("B"), _proposal("R")])
    _deliberate(conn, cell, provider)
    keys = sorted(
        row[0] for row in conn.execute(
            "SELECT idempotency_key FROM model_calls WHERE cell_id = ?", (cell.cell_id,)
        )
    )
    assert keys == ["deliberation:w1", "deliberation:w1:workflow:draft:1", "deliberation:w1:workflow:review"]
    assert len(keys) == provider.calls


def test_a_redelivered_multi_call_wake_buys_nothing(conn):
    cell = _make_cell(conn, structure="parallel_review")
    provider = _Recording([_proposal("A"), _proposal("B"), _proposal("R")])
    _deliberate(conn, cell, provider)
    _deliberate(conn, cell, provider)
    assert provider.calls == 3


def test_a_wake_that_crashed_after_its_steps_replays_them_without_paying_again(conn, monkeypatch):
    """Charter C6 across steps: the steps were billed before the crash, and
    the redelivery must find them rather than buy them twice."""
    cell = _make_cell(conn, structure="parallel_review")
    provider = _Recording([_proposal("A"), _proposal("B"), _proposal("R")])
    real_record = deliberation._record_proposal

    def crash(*args, **kwargs):
        raise RuntimeError("crash before the proposal was recorded")

    monkeypatch.setattr(deliberation, "_record_proposal", crash)
    with pytest.raises(RuntimeError):
        _deliberate(conn, cell, provider)
    monkeypatch.setattr(deliberation, "_record_proposal", real_record)

    _deliberate(conn, cell, provider)
    assert provider.calls == 3
    assert _recorded_summary(conn, cell) == "R"


def _refuse_workflow_steps(monkeypatch, error: Exception):
    real = gateway.call_model

    def call_model(conn, **kwargs):
        if ":workflow:" in kwargs["idempotency_key"]:
            raise error
        return real(conn, **kwargs)

    monkeypatch.setattr(gateway, "call_model", call_model)


def test_an_unaffordable_step_keeps_the_draft_rather_than_raising(conn, monkeypatch):
    cell = _make_cell(conn, structure="iterative_refinement")
    _refuse_workflow_steps(monkeypatch, gateway.GatewayError("cap reached"))
    _deliberate(conn, cell, _Recording([_proposal("draft idea"), _proposal("revised idea")]))
    assert _recorded_summary(conn, cell) == "draft idea"
    (step,) = _metadata(conn)["workflow"]["steps"]
    assert step["note"].startswith("not attempted") and step["model_call_id"] is None


def test_a_genuine_fault_in_a_step_propagates(conn, monkeypatch):
    """The ADR-069 narrowing, applied to steps: a bug must not masquerade as a
    step the Cell could not afford."""
    cell = _make_cell(conn, structure="iterative_refinement")
    _refuse_workflow_steps(monkeypatch, RuntimeError("a real bug"))
    with pytest.raises(RuntimeError, match="a real bug"):
        _deliberate(conn, cell, _Recording([_proposal("draft idea"), _proposal("revised idea")]))
    assert deliberation.get_deliberation_by_wake_key(conn, "w1") is None
