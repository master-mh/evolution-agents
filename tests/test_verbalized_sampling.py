"""Verbalized sampling as a genome-declared sampling policy (SPEC.md §14.1,
§23.5, §26; ADR-089).

A genome's `model_policy.verbalized_candidates` asks one wake for several
genuinely different proposals, each with a stated probability (arXiv
2510.01171). The properties defended here are the ones that keep that from
becoming a new surface: the kernel chooses uniformly and ignores every
probability; the choice is seeded by the wake, so it replays; nothing a Cell
writes beside a candidate reaches the record; and a genome that declares
nothing gets exactly the wake it always had.
"""

from __future__ import annotations

import json

import pytest

from mitosis import deliberation, genome, ledger, lifecycle, proposal, providers
from mitosis.models import Book, CellType, EntrySpec

GENOME = {
    "market": "small accounting firms",
    "problem": "month-end close is manual",
    "workflow": "probe cheaply, measure, iterate",
}


def _proposal(summary: str, **overrides) -> dict:
    payload = {
        "kind": "experiment",
        "summary": summary,
        "rationale": "a cheap probe is the fastest way to a realised record",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 50,
        "predictions": [],
        "experiment": {"hypothesis": f"{summary} finds demand"},
    }
    payload.update(overrides)
    return payload


CANDIDATES = [
    ("probe firms with a close-checklist export", 0.90),
    ("offer a reconciliation report to two firms", 0.08),
    ("price a month-end audit add-on", 0.02),
]


def _candidates_reply(entries=CANDIDATES) -> str:
    return json.dumps({
        "candidates": [
            {**_proposal(summary), "probability": probability}
            for summary, probability in entries
        ]
    })


def _make_cell(conn, *, candidates: int | None, key: str = "vs"):
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100, book=Book.USD_SIM,
        idempotency_key=key,
    )
    content = dict(GENOME)
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


class _Sequenced:
    name = providers.MOCK_PROVIDER

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def complete(self, request):
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return providers.MockProvider(reply=reply).complete(request)


def _deliberate(conn, cell, provider, *, wake_key="w1"):
    return deliberation.deliberate(
        conn, cell_id=cell.cell_id, provider=provider, wake_key=wake_key, model="mock-1",
    )


def _deliberated_metadata(conn) -> list[dict]:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(audit_events)")]
    column = next(name for name in columns if "metadata" in name)
    return [
        json.loads(row[0])
        for row in conn.execute(
            f"SELECT {column} FROM audit_events WHERE event_type = 'cell_deliberated' ORDER BY rowid"
        )
    ]


# --- the genome field ---------------------------------------------------------


def test_a_genome_declaring_nothing_asks_for_one_reply():
    assert genome.verbalized_candidates_of(None) == 1
    assert genome.verbalized_candidates_of({}) == 1
    assert genome.verbalized_candidates_of({"model_policy": {"temperature": 0.5}}) == 1
    assert genome.verbalized_candidates_of({"model_policy": {"verbalized_candidates": 4}}) == 4


@pytest.mark.parametrize("value", [0, 6, 2.0, True, "3"])
def test_verbalized_candidates_is_a_bounded_whole_number(value):
    with pytest.raises(genome.GenomeError, match="verbalized_candidates"):
        genome.canonical_genome_json(CellType.EXPLORER, {"model_policy": {"verbalized_candidates": value}})


@pytest.mark.parametrize("value", [1, 5])
def test_the_bounds_themselves_are_valid(value):
    genome.canonical_genome_json(CellType.EXPLORER, {"model_policy": {"verbalized_candidates": value}})


def test_only_the_candidate_prompt_mentions_candidates():
    """The single-reply prompt was checked byte-identical to its pre-ADR-089
    text when this landed (and the golden run's token counts pin it since);
    this pins that the candidate branch is the only one that changed."""
    assert deliberation._system_prompt() == deliberation._system_prompt(1)
    assert "candidates" not in deliberation._system_prompt()
    many = deliberation._system_prompt(3)
    assert proposal.candidates_instruction(3) in many
    assert proposal.response_schema_hint() in many


# --- the parser -----------------------------------------------------------------


def test_every_valid_candidate_parses_in_reply_order():
    valid, rejected = proposal.parse_candidates(_candidates_reply())
    assert [p.summary for p in valid] == [summary for summary, _ in CANDIDATES]
    assert rejected == []


def test_an_invalid_candidate_is_dropped_whole_not_repaired():
    reply = json.loads(_candidates_reply())
    reply["candidates"][1]["risk_tier"] = "ENORMOUS"
    valid, rejected = proposal.parse_candidates(json.dumps(reply))
    assert [p.summary for p in valid] == [CANDIDATES[0][0], CANDIDATES[2][0]]
    assert len(rejected) == 1 and rejected[0].startswith("candidates.1:")


def test_a_candidate_with_no_probability_key_is_refused_by_name():
    reply = json.loads(_candidates_reply())
    del reply["candidates"][2]["probability"]
    valid, rejected = proposal.parse_candidates(json.dumps(reply))
    assert len(valid) == 2
    assert "'probability' key" in rejected[0]


def test_the_nested_shape_the_first_design_asked_for_is_not_accepted():
    """ADR-089's first format, which no live model followed. Kept refused so
    the parser cannot quietly accept two shapes and the prompt drift from both."""
    nested = {"candidates": [{"probability": 0.5, "proposal": _proposal("nested idea")}]}
    with pytest.raises(proposal.ProposalError, match="no candidate validated"):
        proposal.parse_candidates(json.dumps(nested))


@pytest.mark.parametrize("probability", [0, 1, 1.5, None, True, "0.4"])
def test_a_candidate_without_a_real_probability_is_not_verbalized_sampling(probability):
    reply = json.loads(_candidates_reply())
    reply["candidates"][0]["probability"] = probability
    valid, rejected = proposal.parse_candidates(json.dumps(reply))
    assert len(valid) == 2
    assert rejected[0].startswith("candidates.0.probability")


@pytest.mark.parametrize(
    "payload",
    [
        {"candidates": [], },
        {"candidates": "three ideas"},
        {"candidates": [{**_proposal("x"), "probability": 0.5}], "note": "extra"},
        _proposal("a single proposal where candidates were asked for"),
    ],
)
def test_a_wrong_wrapper_is_refused(payload):
    with pytest.raises(proposal.ProposalError):
        proposal.parse_candidates(json.dumps(payload))


def test_nothing_valid_raises_with_every_reason():
    reply = json.loads(_candidates_reply())
    for item in reply["candidates"]:
        item["probability"] = 0
    with pytest.raises(proposal.ProposalError, match="no candidate validated"):
        proposal.parse_candidates(json.dumps(reply))


# --- the choice -------------------------------------------------------------------


def test_the_choice_replays_for_the_same_wake():
    first = deliberation._parse_reply(_candidates_reply(), candidates=3, wake_key="replay")
    second = deliberation._parse_reply(_candidates_reply(), candidates=3, wake_key="replay")
    assert first == second


def test_the_choice_ignores_every_probability():
    """§23.5: a probability that moved the choice would be a number a Cell
    could learn to write. Across many wakes the 0.02 candidate must be chosen
    about as often as the 0.90 one — and reversing the probabilities must not
    change a single choice."""
    forward, reversed_ = [], []
    flipped = [(summary, probability) for (summary, _), (_, probability)
               in zip(CANDIDATES, reversed(CANDIDATES))]
    for i in range(300):
        forward.append(deliberation._parse_reply(_candidates_reply(), candidates=3, wake_key=f"w{i}")[1]["chosen_index"])
        reversed_.append(deliberation._parse_reply(_candidates_reply(flipped), candidates=3, wake_key=f"w{i}")[1]["chosen_index"])
    assert forward == reversed_
    counts = [forward.count(index) for index in range(3)]
    assert min(counts) > 60, counts  # uniform would be 100 each


# --- the wake -----------------------------------------------------------------------


def test_a_candidate_wake_records_one_candidate_and_no_probability(conn):
    cell = _make_cell(conn, candidates=3)
    result = _deliberate(conn, cell, _Sequenced([_candidates_reply()]))
    assert result.status == deliberation.DeliberationStatus.PROPOSED

    recorded = deliberation.get_proposal(conn, result.proposal_id)
    assert recorded["summary"] in {summary for summary, _ in CANDIDATES}
    assert "probability" not in json.dumps(recorded["payload"])

    [metadata] = _deliberated_metadata(conn)
    assert metadata["sampling"]["verbalized_candidates"] == 3
    assert metadata["sampling"]["candidates_valid"] == 3
    assert metadata["sampling"]["candidates_rejected"] == 0
    assert recorded["summary"] == CANDIDATES[metadata["sampling"]["chosen_index"]][0]


def test_a_cell_asking_for_candidates_pays_for_their_tokens(conn):
    cell = _make_cell(conn, candidates=3)
    _deliberate(conn, cell, _Sequenced([_candidates_reply()]))
    [row] = conn.execute("SELECT parameters_json FROM model_calls").fetchall()
    assert json.loads(row[0])["max_tokens"] == deliberation.DEFAULT_MAX_TOKENS * 3


def test_an_ordinary_wake_carries_no_sampling_record(conn):
    cell = _make_cell(conn, candidates=None, key="plain")
    result = _deliberate(conn, cell, _Sequenced([json.dumps(_proposal("probe the market"))]))
    assert result.status == deliberation.DeliberationStatus.PROPOSED
    [metadata] = _deliberated_metadata(conn)
    assert "sampling" not in metadata
    [row] = conn.execute("SELECT parameters_json FROM model_calls").fetchall()
    assert json.loads(row[0])["max_tokens"] == deliberation.DEFAULT_MAX_TOKENS


def test_a_repaired_candidate_reply_records_its_sampling(conn):
    cell = _make_cell(conn, candidates=3)
    provider = _Sequenced(["not json", _candidates_reply()])
    result = _deliberate(conn, cell, provider)
    assert result.status == deliberation.DeliberationStatus.PROPOSED
    assert result.repair_model_call_id is not None
    [metadata] = _deliberated_metadata(conn)
    assert metadata["sampling"]["candidates_valid"] == 3


def test_a_single_proposal_sent_where_candidates_were_asked_for_is_unparseable(conn):
    """A model that ignores the candidate format gets the one repair every
    wake gets, and is not silently accepted as if it had followed it."""
    cell = _make_cell(conn, candidates=3)
    provider = _Sequenced([json.dumps(_proposal("one idea only"))])
    result = _deliberate(conn, cell, provider)
    assert result.status == deliberation.DeliberationStatus.UNPARSEABLE
    assert provider.calls == 2
