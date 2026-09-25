"""The reply format, as the model actually receives it (SPEC.md §24; ADR-049).

`proposal.parse` is strict — `extra="forbid"`, every required field checked —
and a strict parser is only as good as the instruction that precedes it. Two
live measurements have now shown the same failure shape: the prompt was accurate
and still described the reply in a form the model answered differently, and
**nothing in the suite could see it**, because `MockProvider`'s reply is an input
rather than a response to the prompt's wording.

These are the guards that can be written without a model: the rendered format
must be a shape the parser accepts, must not name a field the parser rejects,
and must keep the ordering and the object-vs-string rendering that were measured
to matter. What none of them can check is whether a model *follows* it — that
needs `mitosis wake --provider ollama` and counting, which is why the numbers in
`_prompt_schema`'s docstring are measurements rather than assertions.
"""

from __future__ import annotations

import json

import pytest

from mitosis import proposal
from mitosis.proposal import KIND_PAYLOADS, ProposalKind


def _skeleton() -> dict:
    """The JSON half of the hint, as a dict."""
    return json.loads(proposal.response_schema_hint().split("\n\n", 1)[0])


def _rule() -> str:
    """The prose half."""
    return proposal.response_schema_hint().split("\n\n", 1)[1]


#: Keys the skeleton always shows, regardless of `kind`. Not the same claim as
#: "always mandatory" — `risk_tier` (ADR-068) is shown here unconditionally
#: but its own hint text carries the one exception, `abstain`.
ALWAYS_REQUIRED = (
    "kind", "summary", "rationale", "risk_tier", "estimated_cost_minor_units",
)


# --- the format has to be one the parser accepts ------------------------------


def test_every_key_shown_is_a_real_proposal_field():
    """The prompt may not name a field the parser would reject.

    This is not hypothetical. An earlier draft's `hypothesis` description
    mentioned "you do not choose what stage it runs at", and `llama3.2` answered
    with `"experiment": {"stage": "§25.1", "rung": "1"}` — **naming a field in
    prose is an invitation to emit it**, even in a sentence saying the Cell does
    not control it. A key shown in the skeleton that `Proposal` does not have
    would be the same mistake, made louder.
    """
    unknown = set(_skeleton()) - set(proposal.Proposal.model_fields)
    assert unknown == set(), f"the prompt shows fields the parser forbids: {unknown}"


def test_every_payload_key_shown_is_a_real_field_of_that_payload():
    """Same rule, one level down. `extra="forbid"` applies to the nested specs
    too, so a made-up member inside `experiment` fails exactly as hard as one at
    the top level."""
    specs = {
        "tool_request": proposal.ToolRequestSpec,
        "external_action": proposal.ExternalActionSpec,
        "experiment": proposal.ExperimentSpec,
    }
    skeleton = _skeleton()
    for field, spec in specs.items():
        shown = set(skeleton[field])
        unknown = shown - set(spec.model_fields)
        assert unknown == set(), f"{field} shows members {spec.__name__} forbids: {unknown}"


@pytest.mark.parametrize("kind", sorted(KIND_PAYLOADS, key=lambda k: k.value))
def test_a_reply_built_from_the_shown_shape_parses(kind):
    """End to end: fill the rendered skeleton in and the parser must accept it.

    The strongest guard here, because it fails if the prompt and the parser ever
    disagree about *shape* — which is the whole bug class — rather than only
    about names.
    """
    reply = {
        "kind": kind.value,
        "summary": "a summary",
        "rationale": "a rationale",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 0,
    }
    filled = {
        "tool_request": {"tool": "http_get", "arguments": {"url": "https://example.com"}},
        "external_action": {"channel": "email", "intent": "ask for feedback"},
        "experiment": {"hypothesis": "widgets sell at 4"},
    }
    reply[KIND_PAYLOADS[kind]] = filled[KIND_PAYLOADS[kind]]

    parsed = proposal.parse(json.dumps(reply))
    assert parsed.kind is kind
    assert getattr(parsed, KIND_PAYLOADS[kind]) is not None


def test_a_reply_with_only_the_required_keys_parses():
    """The skeleton alone, with no payload, must be a legal reply — otherwise
    the five keys it presents as sufficient are not."""
    parsed = proposal.parse(json.dumps({
        "kind": "strategy",
        "summary": "stay off paid advertising",
        "rationale": "no evidence it converts at our price",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 0,
    }))
    assert parsed.kind is ProposalKind.STRATEGY


# --- risk_tier is optional for exactly one kind (ADR-068) ---------------------


def test_an_abstain_reply_may_omit_risk_tier_entirely():
    """§23.1 classifies actions; an abstaining Cell proposes none. `qwen2.5`
    dropped the key outright on every abstain reply in its collapsed t=0 run —
    this is that shape, made legal."""
    parsed = proposal.parse(json.dumps({
        "kind": "abstain",
        "summary": "nothing worth doing this wake",
        "rationale": "no evidence supports a new claim right now",
        "estimated_cost_minor_units": 0,
    }))
    assert parsed.kind is ProposalKind.ABSTAIN
    assert parsed.risk_tier is None


def test_an_abstain_reply_may_send_risk_tier_as_null():
    """`llama3.2`'s shape for the same objection: not omitted, but `null`.
    Pydantic parses `null` into `None` for an `Optional` field, so both of the
    two independently observed failure shapes are covered by one change."""
    parsed = proposal.parse(json.dumps({
        "kind": "abstain",
        "summary": "nothing worth doing this wake",
        "rationale": "no evidence supports a new claim right now",
        "risk_tier": None,
        "estimated_cost_minor_units": 0,
    }))
    assert parsed.risk_tier is None


def test_an_abstain_reply_may_still_state_a_risk_tier():
    """Optional, not forbidden — a Cell that has an opinion may still state
    one; the schema only stops treating its absence as a parse failure."""
    parsed = proposal.parse(json.dumps({
        "kind": "abstain",
        "summary": "nothing worth doing this wake",
        "rationale": "no evidence supports a new claim right now",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 0,
    }))
    assert parsed.risk_tier is proposal.RiskTier.LOW


@pytest.mark.parametrize(
    "kind", sorted(set(ProposalKind) - {ProposalKind.ABSTAIN}, key=lambda k: k.value)
)
def test_every_other_kind_still_requires_a_risk_tier(kind):
    """The exception is exactly one kind wide. Widening it silently — a
    stronger model reaching the same objection on a *different* kind, say —
    must still fail loudly rather than being read as evidence to relax
    further."""
    reply = {
        "kind": kind.value,
        "summary": "a summary",
        "rationale": "a rationale",
        "estimated_cost_minor_units": 0,
    }
    filled = {
        "tool_request": {"tool": "http_get", "arguments": {}},
        "external_action": {"channel": "email", "intent": "ask for feedback"},
        "experiment": {"hypothesis": "widgets sell at 4"},
    }
    if kind in KIND_PAYLOADS:
        reply[KIND_PAYLOADS[kind]] = filled[KIND_PAYLOADS[kind]]
    if kind is ProposalKind.DELIVERABLE:
        # Its own requirement (ADR-107), met so the only missing field is the tier.
        reply["artifact"] = {"kind": "report", "title": "t", "content": "c"}

    with pytest.raises(proposal.ProposalError, match="risk_tier is required"):
        proposal.parse(json.dumps(reply))


def test_the_prompt_names_the_one_exception():
    """The rendered hint must actually say which kind may omit the field, not
    just that the schema now permits it — a model reading the old wording
    ("required for every kind, abstain included") would still supply one it
    no longer needs to."""
    hint = _skeleton()["risk_tier"]
    assert "abstain" in hint
    assert "except" in hint


# --- the renderings that were measured to matter ------------------------------


def test_payloads_render_as_objects_not_as_sentences():
    """The regression this file exists for.

    These keys used to render as long English strings that happened to contain
    braces — `"experiment": "REQUIRED only when kind is experiment ... {...}"` —
    and `llama3.2` answered by hoisting `hypothesis` to the top level in **every
    one of 12 replies**. A value has to be shown in the shape the parser wants
    back; that rule was learned once for enums (2026-08-06) and again here.
    """
    skeleton = _skeleton()
    for field in KIND_PAYLOADS.values():
        assert isinstance(skeleton[field], dict), (
            f"{field} is rendered as {type(skeleton[field]).__name__}; a model reads a "
            "string-valued key as a key that takes a string, and flattens the object"
        )


def test_the_required_keys_come_before_the_conditional_payloads():
    """The single largest lever of the four, and the one an alphabetical sort
    silently undid.

    `json.dumps(..., sort_keys=True)` put `experiment` and `external_action`
    *above* `kind` and `summary`, so the model met two conditional payloads
    before the field that decides whether they apply — and they looked exactly
    as mandatory as everything else. Restoring insertion order moved the
    measured parse rate from 0/16 to 7/16 with nothing else changed.
    """
    keys = list(_skeleton())
    assert keys[: len(ALWAYS_REQUIRED)] == list(ALWAYS_REQUIRED)
    first_payload = min(keys.index(f) for f in KIND_PAYLOADS.values())
    assert first_payload >= len(ALWAYS_REQUIRED), (
        "a conditional payload is shown above a required field — the exact "
        "ordering an alphabetical sort produces"
    )


def test_kind_is_shown_before_any_key_that_depends_on_it():
    """`kind` decides which payload belongs, so a model that reads it last has
    already had to guess."""
    keys = list(_skeleton())
    assert keys.index("kind") < min(keys.index(f) for f in KIND_PAYLOADS.values())


def test_the_optional_keys_are_described_but_not_shown_in_the_skeleton():
    """`artifact` and `predictions` stay out of the skeleton, and that asymmetry
    is measured rather than tidy.

    Shown, they came back filled with nothing — `"artifact": {"title": "",
    "content": ""}` — because a model completes the form it is given. Hidden
    *entirely*, the model also stopped emitting the payload its own kind
    required (0/12, "an experiment proposal must carry an experiment"). So a key
    that is sometimes mandatory belongs in the skeleton and a key that is almost
    always absent belongs in the prose, where being skimmed is the point.
    """
    skeleton = _skeleton()
    for optional in ("artifact", "predictions"):
        assert optional not in skeleton, (
            f"{optional} is back in the skeleton; it returns filled with empty strings"
        )
        assert f'"{optional}"' in _rule(), (
            f"{optional} is in neither the skeleton nor the prose, so a model is "
            "never told it exists. Note the bare word appears inside its own "
            "description text, which is why this asserts the quoted key."
        )


def test_the_rendered_format_is_not_ascii_escaped():
    """`ensure_ascii=True` renders every em-dash as `\\u2014`. Harmless to a
    parser and pure noise in a prompt whose entire job is to be unambiguous."""
    assert "\\u" not in proposal.response_schema_hint()


# --- the two places the pairing is stated must agree --------------------------


@pytest.mark.parametrize("kind,field", sorted(KIND_PAYLOADS.items(), key=lambda kv: kv[0].value))
def test_kind_payloads_matches_what_the_validators_enforce(kind, field):
    """`KIND_PAYLOADS` generates the prompt's rule; the three
    `_*_matches_kind` validators enforce it. They are separate on purpose — each
    validator carries its own argument about why its second direction matters —
    so this is what keeps them from drifting into disagreement, which would put
    a rule in the prompt that the parser does not apply, or the reverse.
    """
    base = {
        "summary": "s", "rationale": "r", "risk_tier": "LOW",
        "estimated_cost_minor_units": 0,
    }
    filled = {
        "tool_request": {"tool": "http_get", "arguments": {}},
        "external_action": {"channel": "email", "intent": "ask"},
        "experiment": {"hypothesis": "h"},
    }[field]

    # This kind must carry its payload...
    with pytest.raises(proposal.ProposalError):
        proposal.parse(json.dumps({"kind": kind.value, **base}))

    # ...and no other kind may.
    for other in ProposalKind:
        if other is kind:
            continue
        with pytest.raises(proposal.ProposalError):
            proposal.parse(json.dumps({"kind": other.value, **base, field: filled}))


def test_the_payload_rule_names_every_kind():
    """A kind missing from the rule is a kind a model gets no instruction
    about — and `ProposalKind` has grown four times."""
    rule = _rule()
    for kind in ProposalKind:
        assert f'"{kind.value}"' in rule, f"the payload rule never mentions {kind.value}"


def test_kind_payloads_covers_exactly_the_kinds_the_parser_demands_one_for():
    """Derived from the parser, not from `KIND_PAYLOADS`, on purpose.

    `test_kind_payloads_matches_what_the_validators_enforce` is parametrised
    over `KIND_PAYLOADS` — so removing an entry deletes a test case instead of
    failing one, and the suite goes quieter rather than redder. A teeth-check
    caught exactly that. This asks the parser which kinds refuse a payload-less
    proposal and compares that set, so a kind dropped from the constant shows up
    as a mismatch here however few cases the parametrised test generates.
    """
    base = {
        "summary": "s", "rationale": "r", "risk_tier": "LOW",
        "estimated_cost_minor_units": 0,
    }
    demanded = set()
    for kind in ProposalKind:
        try:
            proposal.parse(json.dumps({"kind": kind.value, **base}))
        except proposal.ProposalError as exc:
            # A deliverable's artifact is not one of the three payload keys —
            # `artifact` pairs with no kind and rides alongside most of them
            # (ADR-107) — so it is checked on its own below, not counted here.
            if "must carry" in str(exc) and '"artifact"' not in str(exc):
                demanded.add(kind)
    with pytest.raises(proposal.ProposalError, match='must carry an "artifact"'):
        proposal.parse(json.dumps({"kind": ProposalKind.DELIVERABLE.value, **base}))
    assert 'REQUIRES "artifact"' in proposal.response_schema_hint()
    assert demanded == set(KIND_PAYLOADS), (
        f"the parser demands a payload for {sorted(k.value for k in demanded)} but "
        f"KIND_PAYLOADS lists {sorted(k.value for k in KIND_PAYLOADS)} — the prompt "
        "and the parser now disagree about which kinds need one"
    )


# --- the repair turn has to name the same keys the skeleton does (ADR-102) ----


def test_the_always_required_list_matches_the_skeleton_it_is_derived_from():
    """`proposal.always_required_keys()` exists so a second caller — the
    parse-repair follow-up turn — can name the required keys without writing
    them out again.

    `ALWAYS_REQUIRED` above is the independent, hand-written statement of the
    same thing; this test is the two-source agreement. If the skeleton gains or
    loses an unconditional key and this file is not updated, one of them is
    wrong and the repair turn is about to describe a reply the parser will
    reject.
    """
    assert proposal.always_required_keys() == ALWAYS_REQUIRED


def test_the_always_required_list_covers_every_field_the_parser_demands():
    """Binds the list to the *parser*, not just to the prompt.

    A new field added to `Proposal` with no default is required of every reply
    from that moment on. If it never reaches `always_required_keys`, the repair
    turn keeps reciting the old list and a model that follows it exactly still
    fails to validate — the exact shape ADR-102 was written about, one layer up.
    """
    demanded = {
        name
        for name, field in proposal.Proposal.model_fields.items()
        if field.is_required()
    }
    missing = demanded - set(proposal.always_required_keys())
    assert missing == set(), (
        f"the parser requires {missing} of every reply, and neither the reply "
        "skeleton nor the repair turn names it"
    )
