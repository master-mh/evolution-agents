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

#: What an external action is for, as the operator will read it in the §23.2
#: payload before deciding whether a person should do it. Short on purpose: an
#: intent that needs a page to state is a plan, and the plan belongs in the
#: rationale where a reviewer already reads it.
MAX_INTENT_CHARS = 300
#: Kept equal to `experiments.MAX_HYPOTHESIS_CHARS`, which is the limit that
#: actually bites when the experiment is started. Defined here rather than
#: imported because `experiments` sits above this module; a structural test
#: asserts the two agree, so they cannot drift into a proposal that parses and
#: then fails at the one moment a human has already approved it.
MAX_HYPOTHESIS_CHARS = 2_000

#: An artifact's body, carried on the proposal that produced it. Far larger than
#: `MAX_RATIONALE_CHARS` and that asymmetry is deliberate: §15's caps exist
#: because today's proposal is tomorrow's context, and an artifact's content
#: **never enters context** — §15.2 asks for an artifact *index*, which is what
#: `context.py` renders. The store holds the deliverable; the Cell sees that it
#: has one. Kept in step with `artifacts.MAX_CONTENT_CHARS` by a structural test
#: rather than an import, since `artifacts` sits above this module.
MAX_ARTIFACT_CONTENT_CHARS = 20_000
MAX_ARTIFACT_TITLE_CHARS = 200

#: Prediction horizons the loop will register, in days. Bounded below because a
#: claim resolvable in minutes is not a forecast, and above because a claim
#: resolvable after the Cell is dead cannot score it (§8.5's anti-gaming
#: surface: unresolved predictions are the ones a Cell hides its losses in).
MIN_PREDICTION_HORIZON_DAYS = 1
MAX_PREDICTION_HORIZON_DAYS = 365


class ProposalError(Exception):
    pass


class ProposalKind(StrEnum):
    #: Ask to run an experiment (§0.2, §9.2, §25.1). §0.2 puts "experiments" in
    #: the **mutable Cell** column, so what is tested is entirely the Cell's —
    #: the kernel has no opinion on the hypothesis and never rewrites it. What
    #: it gates is the *slot* (§9.2 caps simultaneous experiments colony-wide)
    #: and the *rung* (§25.1), neither of which the Cell owns. Like the
    #: requests below, an approved grant is what starts one.
    EXPERIMENT = "experiment"
    #: How the Cell intends to operate (§0.2, §15.1). **The only kind with no
    #: consumer, and that is the decision rather than an unfinished corner
    #: (ADR-046).** Every other kind names something to do and an approved grant
    #: is permission to do it; a strategy names nothing, so approving one *is*
    #: the act. What changes is what the Cell is shown from then on — §15.1's
    #: "relevant epigenetic state", which `context` derives from the most
    #: recently approved one rather than storing anywhere.
    STRATEGY = "strategy"
    SPEND_REQUEST = "spend_request"
    #: Ask to run a registered tool (§0.4, §19). Like SPEND_REQUEST this is a
    #: request, not an action: it produces a §23 review item, and only an
    #: approved grant runs anything. The tool id is deliberately *not*
    #: validated here — `tools` sits above this module in the dependency order,
    #: and importing it would invert the layering the kernel keeps everywhere.
    #: `tools.validate_request` checks it at proposal-record and execute time.
    TOOL_REQUEST = "tool_request"
    #: Ask that a *person* take one action outside the colony on the Cell's
    #: behalf (§21, §28 Phase 8). Like the two above it is a request and not an
    #: action — and unlike them, nothing in the kernel can ever execute it: §28
    #: Phase 8's acceptance is "all external action remains manual", so an
    #: approved grant authorises a human to act and to record what they did.
    #: The channel id is validated by `channel_registry.validate_request` at
    #: record time for the same layering reason `tool_request.tool` is.
    EXTERNAL_ACTION = "external_action"
    #: A first-class outcome, not a failure. A Cell with nothing worth doing
    #: should say so; the alternative is a Cell that invents work because the
    #: schema gave it no way to decline. (Abstaining is still not free — §10.5
    #: domination does not reward an idle Cell, so this does not become a
    #: strategy for surviving without contributing.)
    ABSTAIN = "abstain"


#: Kinds that ask for nothing, so approving one is agreement rather than
#: permission. The distinction the enum's own comments already draw between a
#: *request* and an *action*, taken one step further: these are **statements**,
#: and §23.3's "expired actions are regenerated and re-evaluated" does not reach
#: them, because there is no action to redo (ADR-046).
#:
#: ABSTAIN is deliberately absent. It is a statement too, but `approval.enqueue`
#: never queues one, so it can never reach a grant — listing it here would be a
#: rule about a state that cannot occur.
STATEMENT_KINDS: frozenset["ProposalKind"] = frozenset({ProposalKind.STRATEGY})

#: The payload object each kind must carry, and which no other kind may.
#:
#: One source of truth for a pairing that is stated in two places and has to
#: agree in both: the three `_*_matches_kind` validators enforce it, and the
#: prompt has to *describe* it. `_payload_rule` generates the wording from this
#: dict for the same reason `_prompt_schema` is generated from the model —
#: a hand-written copy drifts, and the failure lands on every Cell at once with
#: nothing pointing at the prompt as the cause.
#:
#: The validators keep their own bodies rather than looping over this, because
#: each carries a different argument about *why* its second direction matters
#: (`experiment` is the permissive kind; `external_action` spends §21.1's shared
#: reputation). `test_proposal_payload_pairing_matches_the_validators` is what
#: keeps the two in step.
#:
#: `artifact` is deliberately absent: it pairs with no kind and is allowed
#: alongside all of them but ABSTAIN.
KIND_PAYLOADS: dict["ProposalKind", str] = {
    ProposalKind.TOOL_REQUEST: "tool_request",
    ProposalKind.EXTERNAL_ACTION: "external_action",
    ProposalKind.EXPERIMENT: "experiment",
}


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


class ExternalActionSpec(BaseModel):
    """One action a person is being asked to take outside the colony (§21, §28).

    **There is no field for who.** A Cell names a channel and a purpose; the
    operator names the counterparty at claim time and the kernel stores only a
    salted hash of it. Three reasons, in `external_actions.py` — the shortest is
    that §16.3 makes customer identity non-inheritable, and a proposal is
    inherited context: an address written here would sit in the Cell's own
    record, in every later §15 context assembled from it, and in its coroner
    report. `FORBIDDEN_COUNTERPARTY_FIELDS` makes adding one trip an alarm.

    **`artifact_id` cites the Cell's own work, and citing it is not permission
    to send it.** §19.3's export gateway still has to have let the artifact out
    of the colony first; a channel decides only where an already-exported thing
    goes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: str = Field(min_length=1, max_length=64)
    intent: str = Field(min_length=1, max_length=MAX_INTENT_CHARS)
    #: An artifact this Cell produced, if the action delivers one.
    artifact_id: str | None = None

    @field_validator("intent")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class ExperimentSpec(BaseModel):
    """What the Cell wants to test (§0.2, §9.2, §15.1, §25.1).

    **There is no field for which rung it runs at, and that is the whole
    design.** §25.1 opens with "no strategy moves directly from synthetic
    success to autonomous commerce", and its rungs run from a flight simulator
    to bounded autonomy over real money. A Cell that could name its own rung
    could ask for rung 7 on its first wake and need only one tired operator to
    get it. §23.5 already settled the general form of this — "no input to a
    queueing decision may be a value the Cell supplies about itself" — so the
    rung is *derived* from what the colony has actually promoted this Cell to,
    and there is nowhere here to put a different answer.
    `FORBIDDEN_RUNG_FIELDS` makes adding one trip an alarm.

    **A hypothesis, not a summary.** `summary` already says what the Cell wants
    to do. This is the claim being tested, which §10.5's coroner asks for by
    name ("final hypotheses") and which is the thing an experiment can turn out
    to be wrong about.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hypothesis: str = Field(min_length=1, max_length=MAX_HYPOTHESIS_CHARS)

    @field_validator("hypothesis")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("hypothesis must not be blank")
        return value.strip()


class ArtifactSpec(BaseModel):
    """A deliverable the Cell produced during this wake (§28 Phase 8, §20).

    Not an outcome claim, and the distinction is what keeps it inside §0.3: an
    artifact is the *work*, not a statement about how the work did. Nothing
    derives fitness from its content, nothing counts artifacts, and §11.2 makes
    usefulness strictly downstream — another Cell has to adopt it.

    `kind` is validated against `artifacts.ARTIFACT_KINDS` at record time rather
    than here, for the same layering reason `tool_request.tool` is: `artifacts`
    sits above this module and a back-edge would invert the dependency order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=MAX_ARTIFACT_TITLE_CHARS)
    content: str = Field(min_length=1, max_length=MAX_ARTIFACT_CONTENT_CHARS)
    #: Tool calls this drew on. §20.2's laundering guard depends on these being
    #: declared: rights propagate from cited sources, so an artifact that cites
    #: nothing claims to be original work — which is a statement a human can
    #: check against the Cell's tool history.
    source_tool_call_ids: tuple[str, ...] = ()

    @field_validator("title", "content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class Proposal(BaseModel):
    """The only shape a deliberation may return.

    Every field is an intention or an explanation. See the module docstring on
    why there is nothing here describing an outcome.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProposalKind
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY_CHARS)
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE_CHARS)
    #: Required for every kind except ABSTAIN (ADR-068). §23.1 classifies
    #: *actions*; an abstaining Cell has proposed no action to classify, and
    #: two models independently dropped or nulled this field on exactly that
    #: kind. See `_risk_tier_matches_kind` for the enforcement, which mirrors
    #: `_experiment_matches_kind`'s shape rather than inventing a new one.
    risk_tier: RiskTier | None = None
    estimated_cost_minor_units: int = Field(ge=0)
    predictions: tuple[ProposedPrediction, ...] = Field(
        default=(), max_length=MAX_PREDICTIONS
    )
    #: Present exactly when `kind` is TOOL_REQUEST — see `_tool_request_matches_kind`.
    tool_request: ToolRequestSpec | None = None
    #: Present exactly when `kind` is EXTERNAL_ACTION — same rule, same reason.
    external_action: ExternalActionSpec | None = None
    #: Present exactly when `kind` is EXPERIMENT — same rule, same reason.
    experiment: ExperimentSpec | None = None
    #: What the Cell made this wake, if anything. Allowed alongside any kind
    #: except ABSTAIN: production is not gated (§28 Phase 8 gates *external
    #: use*), so a Cell may hand over a draft while proposing what to do next.
    artifact: ArtifactSpec | None = None

    @model_validator(mode="after")
    def _abstaining_produces_nothing(self) -> "Proposal":
        """A Cell that declines to work does not also hand in a deliverable.

        ABSTAIN is a first-class outcome precisely so a Cell with nothing worth
        doing can say so; attaching work to it would make abstention the
        cheapest way to produce without proposing anything reviewable.
        """
        if self.kind is ProposalKind.ABSTAIN and self.artifact is not None:
            raise ValueError("an abstaining proposal cannot carry an artifact")
        return self

    @model_validator(mode="after")
    def _risk_tier_matches_kind(self) -> "Proposal":
        """§23.1 classifies *actions*, LOW through CRITICAL. ABSTAIN proposes
        none, so it is the one kind where omitting `risk_tier` (or sending it
        as `null`) is a defensible answer rather than a dropped field —
        ADR-068, after two models independently produced exactly this shape.
        Every other kind still requires a stated tier.
        """
        if self.kind is ProposalKind.ABSTAIN:
            return self
        if self.risk_tier is None:
            raise ValueError(
                f"risk_tier is required for kind {self.kind.value!r} "
                "(only 'abstain' may omit it)"
            )
        return self

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

    @model_validator(mode="after")
    def _external_action_matches_kind(self) -> "Proposal":
        """An external_action proposal carries one, and nothing else does.

        The second half is the load-bearing one here, more so than for
        `tool_request`. An `experiment` is the kind a reviewer reads as "yes, go
        think about that"; letting one carry an external action would mean the
        colony's single shared reputation (§21.1) could be spent under an
        approval nobody read as being about that. `external_actions.claim`
        refuses the pairing again at claim time.
        """
        if self.kind is ProposalKind.EXTERNAL_ACTION and self.external_action is None:
            raise ValueError("an external_action proposal must carry an external_action")
        if self.kind is not ProposalKind.EXTERNAL_ACTION and self.external_action is not None:
            raise ValueError(
                "only an external_action proposal may carry an external_action, not "
                f"{self.kind.value}"
            )
        return self

    @model_validator(mode="after")
    def _experiment_matches_kind(self) -> "Proposal":
        """An experiment proposal carries a hypothesis, and nothing else does.

        Both directions again, and the second is not symmetric with the two
        above. `experiment` is the *permissive* kind — the one a reviewer reads
        as "yes, go think about that" — so the risk runs the other way: a
        hypothesis attached to a `tool_request` or an `external_action` would
        let a Cell take a §9.2 slot on the back of an approval that was read as
        being about a fetch or an email. `experiment_grants.start_from_grant`
        refuses the pairing again at start time.
        """
        if self.kind is ProposalKind.EXPERIMENT and self.experiment is None:
            raise ValueError("an experiment proposal must carry an experiment")
        if self.kind is not ProposalKind.EXPERIMENT and self.experiment is not None:
            raise ValueError(
                f"only an experiment proposal may carry an experiment, not {self.kind.value}"
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


#: Field names an `ExternalActionSpec` must never carry. A second tripwire in
#: the same style as `FORBIDDEN_FIELD_SENSE` above, guarding a different
#: boundary: §0.3 keeps a Cell from defining its own *result*, and this keeps it
#: from naming a *person*.
#:
#: `extra="forbid"` already rejects every one of these today, so this is not a
#: blocklist the parser consults. It exists so that `test_a_cell_cannot_name_a
#: _counterparty` fails the moment one becomes a real field — widening the
#: schema toward a Cell-supplied identity has to be an argued change to §16.3
#: rather than a plausible-looking commit that makes outreach "easier".
FORBIDDEN_COUNTERPARTY_FIELDS: dict[str, str] = {
    "counterparty": "the operator names who; §16.3 makes customer identity non-inheritable",
    "recipient": "as above, by another name",
    "customer": "as above; a `customers` table is the design §16.3 warns about",
    "to": "as above",
    "email": "a personal identifier in a record every later context inherits",
    "address": "as above",
    "phone": "as above",
    "contact": "as above",
    "name": "as above — and the artifact's title is where a deliverable is named",
}


#: Field names an `ExperimentSpec` must never carry. A third tripwire in the
#: style of the two above, guarding the third boundary: §0.3 keeps a Cell from
#: defining its own *result*, §16.3 keeps it from naming a *person*, and this
#: keeps it from choosing its own *rung*.
#:
#: §25.1's ladder is the colony's staged-autonomy mechanism, and a rung is a
#: statement about how much of the real world a Cell may touch. `extra="forbid"`
#: rejects all of these today; the dict exists so that
#: `test_a_cell_cannot_choose_its_own_rung` fails the moment one becomes a real
#: field. The rung is derived from `promotions` — see
#: `experiment_grants.entitled_rung`.
FORBIDDEN_RUNG_FIELDS: dict[str, str] = {
    "ladder_rung": "§25.1's rung is derived from what the colony promoted, never asked for",
    "rung": "as above, by the short name",
    "stage": "as above; §13.1's 'current stage' is the same ladder",
    "tranche": "§13.1's stage tranche is a budget the allocator sets, not the Cell",
    "budget": "capital comes from an approved allocation (§25.2), never self-declared",
    "capital": "as above",
    "real_money": "§27.1's autonomy flags are the operator's, and default to off",
    "autonomy": "as above — autonomy is granted tool by tool (§0.4), never claimed",
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
    """The reply format, rendered for the prompt.

    Two parts, and the split is the whole design: a JSON skeleton of the keys
    that are **always** present, then prose for the keys that are conditional or
    optional. Generated from the model and from `KIND_PAYLOADS` rather than
    hand-written, so the prompt cannot drift out of step with what the parser
    accepts.
    """
    # **Not sorted, and not ASCII-escaped.** `sort_keys=True` alphabetised the
    # skeleton, which put `experiment` and `external_action` *above* `kind` and
    # `summary` — so a model reading top-to-bottom met two conditional payloads
    # before it met the field that decides whether they apply, and they looked
    # exactly as mandatory as everything else. Insertion order puts the five
    # always-required keys first and the conditional ones last, which is the
    # order the reply should be built in. `ensure_ascii=False` keeps em-dashes
    # as em-dashes instead of `\u2014`, which was pure noise in a prompt whose
    # whole job is to be unambiguous.
    return (
        json.dumps(_prompt_schema(), indent=2, ensure_ascii=False)
        + "\n\n"
        + _payload_rule()
    )


def _prompt_schema() -> dict[str, Any]:
    """The keys every reply carries, and only those.

    **A model fills in every key it is shown.** That is the single lesson three
    live measurements produced, and it is stronger than "describe the fields
    accurately":

    1. **Enum choices are a string, never a JSON array** (2026-08-06). Rendering
       `"risk_tier": ["LOW", "MEDIUM", ...]` reads as "this field holds a list",
       and the first real run returned `"risk_tier": ["MEDIUM"]` — failing
       validation on a field it had chosen correctly.
    2. **A payload object is an object, never a sentence describing one**
       (2026-08-25). These keys used to render as English strings containing
       braces, so `llama3.2` hoisted `hypothesis` to the top level. Measured at
       **0/12 parseable**, every failure that same flattening.
    3. **An optional key shown in the skeleton comes back filled with nothing**
       (2026-08-25). With `artifact` and `predictions` displayed as populated
       examples, replies arrived carrying `"artifact": {"title": "", "content":
       ""}` and `"summary": ""` — the model completing a form rather than
       answering. So optional and conditional keys are described in
       `_payload_rule` instead — where being skimmed is the desired outcome.
    4. **The skeleton must be ordered, not sorted** (2026-08-25). `sort_keys=True`
       alphabetised it, so `experiment` and `external_action` appeared *above*
       `kind` and `summary`: the model met two conditional payloads before it
       met the field that decides whether they apply, and they looked exactly as
       mandatory as the rest. This was the single largest lever of the four.

    Measured end to end on `llama3.2`, same scenario, 20 wakes per arm:
    **0/44 parseable before, 20/56 after.** That is a real repair and not a
    restoration — the 7/8 recorded on 2026-08-06 predates three conditional
    payloads, and a 3B model is now the binding constraint rather than the
    wording (ADR-049).

    A mock provider can surface none of these: its reply is an input rather than
    a response to these words (ADR-049).
    """
    # **This exact order is measured, and reordering within it is not safe.**
    # The five required keys come before the conditional payloads (docstring,
    # lesson 4). Moving the short scalars `risk_tier` and
    # `estimated_cost_minor_units` *ahead* of `summary` and `rationale` looked
    # obviously right — they were the most-omitted fields, and a model that runs
    # out of steam drops its tail — and it collapsed the parse rate from 7/20
    # back to **0/20**, with flattening returning at 15/20. Whatever the model
    # is doing with this list, `summary` and `rationale` immediately after
    # `kind` is holding it together. Re-measure before touching the order.
    schema: dict[str, Any] = {
        "kind": _one_of(ProposalKind),
        "summary": f"REQUIRED string, 1-{MAX_SUMMARY_CHARS} chars",
        "rationale": f"REQUIRED string, 1-{MAX_RATIONALE_CHARS} chars",
        "risk_tier": (
            _one_of(RiskTier)
            + ' — required for every kind except "abstain", which classifies no '
            "action and may omit this key entirely"
        ),
        "estimated_cost_minor_units": "REQUIRED integer >= 0 (use 0 if nothing would be spent)",
    }
    # The conditional payloads stay in the skeleton; `artifact` and
    # `predictions` do not. That asymmetry is measured, not aesthetic — see
    # lesson 3 above. Hiding *everything* optional and describing it in prose
    # was tried and was worse (0/12): the model stopped emitting the payload its
    # own `kind` required, failing with "an experiment proposal must carry an
    # experiment" seven times out of twelve. **The skeleton is the instruction
    # that lands; prose beneath it is read much more weakly.** So a key that is
    # sometimes mandatory belongs in the skeleton, and a key that is almost
    # always absent belongs in prose, where being ignored is the desired
    # outcome.
    schema.update(
        {field: json.loads(_PAYLOAD_EXAMPLES[field]) for field in KIND_PAYLOADS.values()}
    )
    return schema


#: Compact JSON examples for the keys `_prompt_schema` deliberately omits.
#: Written as literal JSON so the prompt shows the exact shape it wants back —
#: the rule that lesson 2 above cost a measurement to learn.
_PAYLOAD_EXAMPLES: dict[str, str] = {
    "tool_request": (
        '{"tool": "REQUIRED, one of the tools listed in your context", '
        '"arguments": {"<argument name>": "<scalar value>"}}'
    ),
    "external_action": (
        '{"channel": "REQUIRED, one of the channels listed in your context", '
        '"intent": "REQUIRED, what this action is for"}'
    ),
    "experiment": (
        '{"hypothesis": "REQUIRED, the claim this experiment would test — state '
        'what could turn out to be false, not what you intend to do"}'
    ),
}


def _payload_rule() -> str:
    """Everything the skeleton leaves out, in words, generated from
    `KIND_PAYLOADS`.

    A JSON skeleton has nowhere to say "include this key only for this kind" —
    there is no way to annotate a key, and a fake `_when` member gets copied
    into the reply. So the conditional lives here, and the skeleton stays an
    honest picture of the minimum reply.
    """
    lines = [
        "Which of the payload keys above you send is decided by your \"kind\", "
        "and you send AT MOST ONE of them:",
    ]
    for kind, field in KIND_PAYLOADS.items():
        lines.append(f'  kind "{kind.value}"  ->  keep "{field}", drop the other two')
    other = ", ".join(f'"{k.value}"' for k in ProposalKind if k not in KIND_PAYLOADS)
    lines.append(f"  kind {other}  ->  drop all three")
    lines.append("")
    lines.append("Two more keys exist and are NOT shown above, because most replies "
                 "leave them out. Add one only if it genuinely applies:")
    lines.append(
        '  "predictions": [{"claim": "<true or false once resolved, e.g. \'revenue '
        f'>= 50 minor units\'>", "probability": <between 0 and 1, never 0 or 1>, '
        f'"horizon_days": <{MIN_PREDICTION_HORIZON_DAYS}-{MAX_PREDICTION_HORIZON_DAYS}>}}]'
        " — only if you are actually forecasting something; each claim distinct"
    )
    lines.append(
        '  "artifact": {"kind": "<an artifact kind from your context>", "title": '
        '"<title>", "content": "<the deliverable itself>", "source_tool_call_ids": '
        '["<ids of tool results you drew on>"]}'
        ' — only if you actually produced a deliverable this wake, and never with '
        'kind "abstain". Most wakes produce nothing.'
    )
    lines.append("")
    lines.append(
        "Leave out any key you are not using. Do NOT send it as an empty string, "
        "an empty object, an empty list or null — a key with nothing in it is "
        "rejected exactly like a wrong one."
    )
    return "\n".join(lines)


def _one_of(enum_type) -> str:
    """A single-choice field, rendered so it cannot be mistaken for a list."""
    return "REQUIRED, exactly one of: " + " | ".join(m.value for m in enum_type)
