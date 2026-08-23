"""Structured proposals: what a Cell is allowed to say (SPEC.md §0.3, §19.4, §23.1).

A Cell's deliberation returns *this*, or it returns nothing. Prose is not an
acceptable output, and the reason is not tidiness.

**§0.3 is the constraint that shapes the schema: "A Cell may explain a result;
it may never define the canonical result."** So the fields below are
deliberately all intentions and explanations — what the Cell wants to do, why,
what it thinks it would cost, and what it predicts. There is no field for what
it earned, achieved, or how well it did, and adding one would be a
constitutional change rather than a feature: `death.contribution` reads revenue
from the ledger and calibration from the hash-chained prediction register
precisely so that a Cell under selection pressure cannot grade itself.
`FORBIDDEN_FIELD_SENSE` and its test exist to make that boundary trip an alarm
rather than pass review.

**Unknown fields are rejected, not ignored** (`extra="forbid"`). A model that
invents `"authorised": true` must fail validation loudly rather than have the
field silently dropped — under §19.4 model output is untrusted content, never a
trusted command, and the safest reading of an unrecognised instruction is that
something has gone wrong.

**Nothing here is executed.** A proposal is data recorded in a table; §25.1's
ladder puts a first agent loop at rung 5, "shadow prediction with no action".
The `risk_tier` field is the clearest case: it records what the Cell thinks it
is asking for, and grants nothing — a Cell that could set its own risk tier
*and be believed* would set it to LOW forever.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

#: Upper bounds on free text. A proposal is a summary the operator will read,
#: not a place to park an essay — and §15's context budget means today's
#: proposal is tomorrow's context, so unbounded text here inflates every later
#: wake's cost.
MAX_SUMMARY_CHARS = 500
MAX_RATIONALE_CHARS = 2_000
MAX_CLAIM_CHARS = 300
MAX_PREDICTIONS = 5

#: Prediction horizons the loop will register, in days. Bounded below because a
#: claim resolvable in minutes is not a forecast, and above because a claim
#: resolvable after the Cell is dead cannot score it (§8.5's anti-gaming
#: surface: unresolved predictions are the ones a Cell hides its losses in).
MIN_PREDICTION_HORIZON_DAYS = 1
MAX_PREDICTION_HORIZON_DAYS = 365


class ProposalError(Exception):
    pass


class ProposalKind(StrEnum):
    EXPERIMENT = "experiment"
    STRATEGY = "strategy"
    SPEND_REQUEST = "spend_request"
    #: Ask to run a registered tool (§0.4, §19). Like SPEND_REQUEST this is a
    #: request, not an action: it produces a §23 review item, and only an
    #: approved grant runs anything. The tool id is deliberately *not*
    #: validated here — `tools` sits above this module in the dependency order,
    #: and importing it would invert the layering the kernel keeps everywhere.
    #: `tools.validate_request` checks it at proposal-record and execute time.
    TOOL_REQUEST = "tool_request"
    #: A first-class outcome, not a failure. A Cell with nothing worth doing
    #: should say so; the alternative is a Cell that invents work because the
    #: schema gave it no way to decline. (Abstaining is still not free — §10.5
    #: domination does not reward an idle Cell, so this does not become a
    #: strategy for surviving without contributing.)
    ABSTAIN = "abstain"


class RiskTier(StrEnum):
    """§23.1's tiers. Recorded, never honoured as a permission."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ProposedPrediction(BaseModel):
    """A binary claim the Cell commits to *before* the outcome (§8.5, A14).

    Binary and threshold-shaped for the reason prediction.py already
    documents: Brier and log scores are defined over binary outcomes, so
    "revenue >= 50 minor units by epoch 4" is scoreable and "revenue will be
    about 50" is not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str = Field(min_length=1, max_length=MAX_CLAIM_CHARS)
    probability: float = Field(gt=0.0, lt=1.0)
    horizon_days: int = Field(
        ge=MIN_PREDICTION_HORIZON_DAYS, le=MAX_PREDICTION_HORIZON_DAYS
    )

    @field_validator("claim")
    @classmethod
    def _claim_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim must not be blank")
        return value.strip()


class ToolRequestSpec(BaseModel):
    """Which tool, with which arguments (§19, §0.4).

    An *intention*, which is what this whole schema is for — the Cell says what
    it wants done and nothing here does it. The pair is frozen at approval and
    read back from `payload_json` at execution, so what runs is what the
    operator was shown at §23.2 rather than anything re-read from the Cell
    afterwards.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("arguments")
    @classmethod
    def _arguments_are_flat_scalars(cls, value: dict) -> dict:
        """Arguments are scalars, not nested structures.

        A nested payload is somewhere to hide a second instruction, and §19.4
        is explicit that nothing arriving through this path may read as a
        command. Keeping arguments flat means an operator reviewing a request
        sees the whole of it on one line.
        """
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("argument names must be strings")
            if not isinstance(item, (str, int, float, bool)):
                raise ValueError(f"argument {key!r} must be a string, number or boolean")
        return value


class Proposal(BaseModel):
    """The only shape a deliberation may return.

    Every field is an intention or an explanation. See the module docstring on
    why there is nothing here describing an outcome.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProposalKind
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY_CHARS)
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE_CHARS)
    risk_tier: RiskTier
    estimated_cost_minor_units: int = Field(ge=0)
    predictions: tuple[ProposedPrediction, ...] = Field(
        default=(), max_length=MAX_PREDICTIONS
    )
    #: Present exactly when `kind` is TOOL_REQUEST — see `_tool_request_matches_kind`.
    tool_request: ToolRequestSpec | None = None

    @model_validator(mode="after")
    def _tool_request_matches_kind(self) -> "Proposal":
        """A tool_request proposal carries a tool_request, and nothing else does.

        Both directions matter. Without the first, a `tool_request` reaches the
        queue with nothing to execute and the failure surfaces at execution
        time, after a human has already approved it. Without the second, a Cell
        could attach a tool request to an `experiment` — a kind reviewers read
        as "yes, go think about that" — and `tools.execute_grant` refuses that
        pairing precisely because approving one is not approving the other.
        """
        if self.kind is ProposalKind.TOOL_REQUEST and self.tool_request is None:
            raise ValueError("a tool_request proposal must carry a tool_request")
        if self.kind is not ProposalKind.TOOL_REQUEST and self.tool_request is not None:
            raise ValueError(
                f"only a tool_request proposal may carry a tool_request, not {self.kind.value}"
            )
        return self

    @field_validator("summary", "rationale")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("predictions")
    @classmethod
    def _claims_are_distinct(
        cls, value: tuple[ProposedPrediction, ...]
    ) -> tuple[ProposedPrediction, ...]:
        """Reject a proposal that states the same claim twice.

        Two probabilities for one claim is not a forecast, it is a hedge that
        scores whichever way the outcome falls — and a repeated claim would
        also be registered twice, inflating a Cell's resolved count on one
        piece of evidence. Rejected at parse time so the model is told, rather
        than deduplicated silently.
        """
        claims = [p.claim.strip().casefold() for p in value]
        if len(set(claims)) != len(claims):
            raise ValueError("predictions must state distinct claims")
        return value


#: Field names a proposal must never carry, and why. This is not a blocklist
#: the parser consults — `extra="forbid"` already rejects anything unknown, so
#: none of these could be accepted today. It is a **tripwire for the schema
#: itself**: `test_no_self_reported_outcome_field` fails if any of these ever
#: becomes a real field, so widening the schema toward self-reporting has to be
#: a deliberate, argued change to §0.3 rather than a plausible-looking commit.
FORBIDDEN_FIELD_SENSE: dict[str, str] = {
    "revenue_earned": "revenue is canonical only from the ledger (revenue.record_revenue)",
    "profit": "derived from the ledger, never asserted",
    "spend": "canonical only from ledger entries (ledger.spend_by_book)",
    "success": "an outcome; §0.3 forbids a Cell defining its own result",
    "outcome": "an outcome, by name",
    "score": "fitness is computed by the colony, never submitted by the Cell",
    "fitness": "as above; §10.2 also forbids collapsing it to one scalar",
    "calibration": "comes from resolved predictions in the hash-chained register",
    "authorised": "authorisation is the kernel's, never the Cell's to assert",
    "approved": "§23 approval is the operator's; a Cell cannot approve itself",
}


def parse(raw_text: str) -> Proposal:
    """Parse a model's reply into a validated Proposal, or raise.

    Raising is the point. An unparseable reply is recorded as a failed
    deliberation with the validation error — it is never salvaged into a
    "best effort" record, because a half-understood intention stored next to
    fully-understood ones is worse than an honest gap.
    """
    text = _strip_code_fence(raw_text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProposalError(f"reply is not JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProposalError(
            f"reply must be a JSON object, got {type(payload).__name__}"
        )

    try:
        return Proposal.model_validate(payload)
    except ValidationError as exc:
        raise ProposalError(_summarise_validation_error(exc)) from exc


def _strip_code_fence(text: str) -> str:
    """Tolerate ```json fences, which most models emit whatever the prompt says.

    This is the *only* leniency in the parser, and it is lexical: it removes a
    wrapper, it never repairs, infers, or fills in a field. Everything past
    this point is strict.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


def _summarise_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def response_schema_hint() -> str:
    """The schema, rendered for the prompt.

    Generated from the model rather than hand-written, so the prompt cannot
    drift out of step with what the parser will actually accept — a
    hand-maintained copy would eventually describe a field that no longer
    validates, and every Cell would fail on it at once.
    """
    return json.dumps(_prompt_schema(), indent=2, sort_keys=True)


def _prompt_schema() -> dict[str, Any]:
    """The schema as the prompt shows it.

    **Enum choices are rendered as a string, never as a JSON array**, and that
    is not cosmetic. Rendering `"risk_tier": ["LOW", "MEDIUM", ...]` reads to a
    model as "this field holds a list of these values", and the first real
    model run returned exactly that — `"risk_tier": ["MEDIUM"]` — failing
    validation on a field it had actually chosen correctly. The ambiguity was
    the prompt's, not the model's. A mock provider could never surface this,
    because its reply is an input rather than a response to these words.

    Only `predictions` stays an array, because it genuinely is one.
    """
    return {
        "kind": _one_of(ProposalKind),
        "summary": f"REQUIRED string, 1-{MAX_SUMMARY_CHARS} chars",
        "rationale": f"REQUIRED string, 1-{MAX_RATIONALE_CHARS} chars",
        "risk_tier": _one_of(RiskTier),
        "estimated_cost_minor_units": "REQUIRED integer >= 0 (use 0 if nothing would be spent)",
        "tool_request": (
            "REQUIRED only when kind is tool_request, and forbidden otherwise: "
            '{"tool": "<one of the tools listed in your context>", '
            '"arguments": {"<name>": "<scalar value>"}}. Nothing runs until a '
            "human approves the request."
        ),
        "predictions": [
            {
                "claim": (
                    "string, a claim that is unambiguously true or false once "
                    "resolved (state a threshold, e.g. 'revenue >= 50 minor units'); "
                    "each claim must be distinct"
                ),
                "probability": "number strictly between 0 and 1 (never 0 or 1)",
                "horizon_days": (
                    f"integer {MIN_PREDICTION_HORIZON_DAYS}-{MAX_PREDICTION_HORIZON_DAYS}"
                ),
            }
        ],
    }


def _one_of(enum_type) -> str:
    """A single-choice field, rendered so it cannot be mistaken for a list."""
    return "REQUIRED, exactly one of: " + " | ".join(m.value for m in enum_type)
