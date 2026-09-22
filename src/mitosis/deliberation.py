"""The agent loop: a Cell that acts (SPEC.md §17.2, §15, §0.3, §25.1; Charter C6, C8, C15).

Everything built before this is machinery *for* a Cell. This is the Cell.

One wake is: assemble bounded context (§15) → one gateway call (or the few its
genome's workflow structure names, each reserved separately; ADR-093) → parse
a strict structured proposal → record it, with any predictions registered
before their outcomes (§8.5). Then the Cell sleeps.

**What the loop deliberately cannot do, and why each is a spec requirement
rather than caution:**

- **It cannot act.** §25.1's ladder — "no strategy moves directly from
  synthetic success to autonomous commerce" — puts a first agent loop at rung
  5, *shadow prediction with no action*. A proposal is a row in a table; no
  kernel path consumes it. The obvious loop ("let the model decide, then do
  it") skips eight rungs.
- **It cannot report its own results.** §0.3: "A Cell may explain a result; it
  may never define the canonical result." So the proposal schema has no
  outcome field (see proposal.FORBIDDEN_FIELD_SENSE), and the only writes this
  module makes are a deliberation, a proposal, and predictions — never
  revenue, never a balance, never a score.
- **It cannot execute its genome.** Genome content is rendered into the prompt
  as data and interpreted by a model. Nothing is `exec`'d or `eval`'d, and no
  genome field *supplies* a code path: a genome may choose among the kernel's
  own closed set of wake structures (`genome.WORKFLOW_STRUCTURES`, ADR-093) the
  way it chooses a temperature, and every one of them is kernel code. Charter
  C15 holds only while genomes are inert data; the sandbox that would make
  executable genomes survivable (C12) is Phase 5.
- **It cannot be woken when dead.** Charter C8. Quarantined Cells are refused
  too — a Cell under restriction that can still think and propose is only
  quarantined in name.

**The one architectural surprise, worth stating because it looks like a
shortcut and is not:** a wake cannot run inside `events.process_event`'s
handler transaction. That contract requires the handler not to commit, but
ADR-022 requires the gateway's reservation to *commit before* the external
call — otherwise reserve-before-execute means nothing, and a crash mid-call
loses the record that money was authorised. The two are irreconcilable, so
`run_wake_event` does the deliberation first and marks the event processed
after. Idempotency is what makes that safe, and it is what Charter C6
actually asks for: `wake_key` is derived from the event id, so a redelivered
wake returns the existing deliberation rather than buying a second model call.
A crash between the two leaves the event pending and the deliberation done —
the redelivery finds it and simply marks the event processed.
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol

from . import (
    artifacts,
    audit,
    context,
    events,
    experiments,
    gateway,
    genome,
    ids,
    ledger,
    lifecycle,
    prediction,
    proposal as proposal_module,
    providers,
    real_spend_breaker,
    reservations,
    tracing,
    workflow_graph,
)
from .accounts import cell_cash
from .models import Book, Cell, CellStatus

#: Wake reasons drawn from §17.2's list. Not a closed enum — §17.2 gives an
#: open list and new sources are expected — but named here so the common ones
#: are spelled consistently across the CLI, the event payloads and the record.
WAKE_SCHEDULED_RESEARCH = "scheduled research cycle"
WAKE_CAPITAL_ALLOCATION = "capital allocation"
WAKE_AUDIT_REQUEST = "audit request"
WAKE_HUMAN_DECISION = "human decision"
#: §17.2. A tool call finished and its (UNTRUSTED_EXTERNAL) result is now in
#: the Cell's context. Emitted by `tools.execute_grant`, never by a tool result
#: itself — see tools.py on why nothing a tool returns may cause another call.
WAKE_TOOL_RESULT = "tool result available"
#: §17.2. A person finished an external action this Cell proposed, and the
#: registry now records what came of it. Emitted by
#: `external_actions.complete` — the outcome is an observation a person made,
#: never something the Cell reported about itself (§0.3).
WAKE_EXTERNAL_ACTION_RESULT = "external action result"

#: The event type the loop consumes.
WAKE_EVENT_TYPE = "cell_wake"

#: A Cell must be able to pay for its own thinking (§15.4: context and model
#: tokens are charged to the responsible Cell). Below this it is woken only to
#: be refused — recorded, so "this Cell could not afford to think" is a visible
#: fact rather than a silent absence.
MIN_CASH_TO_DELIBERATE = 1

DEFAULT_MAX_TOKENS = 700

#: A parse-repair retry is bounded to exactly one attempt (ADR-069): "it pays
#: twice for a prompt bug" is the accepted, bounded cost; an unbounded loop
#: would turn a persistently broken prompt into an unbounded multiplier on a
#: single wake's cost, which is exactly the failure mode a bound exists to
#: prevent. Named rather than hardcoded so the cap is visible at the call
#: site and in tests that pin it.
MAX_PARSE_REPAIR_ATTEMPTS = 1

#: The exceptions a repair attempt may raise that mean "the second call could
#: not even be *attempted*" — the Cell cannot afford it, a cap or the real-spend
#: breaker refused it, or the gateway declined it outright. These, and only
#: these, degrade a repair to the pre-repair UNPARSEABLE outcome (ADR-069):
#: losing the *first* failure's record because a *second* call was unaffordable
#: would be strictly worse than not repairing at all. Anything else a repair
#: raises — a programming error in `_attempt_parse_repair`, a locked or corrupt
#: database — is a genuine fault and must propagate, exactly as it already does
#: from the first (unwrapped) `gateway.call_model` in `deliberate()`: a bug
#: masquerading as "the model cannot format its reply" is the failure mode a
#: blanket `except Exception` here would have hidden.
_REPAIR_UNATTEMPTABLE_ERRORS = (
    gateway.GatewayError,
    reservations.ReservationError,
    real_spend_breaker.RealSpendBreakerError,
)


class DeliberationError(Exception):
    pass


class DeliberationStatus:
    PROPOSED = "proposed"
    UNPARSEABLE = "unparseable"
    REFUSED = "refused"
    #: The gateway call failed at the provider, so this Cell never had a reply
    #: to be judged on (ADR-101). Distinct from UNPARSEABLE because §24.2
    #: requires provider change to stay distinguishable from Cell behaviour,
    #: and an outage is the loudest provider change there is: recorded as
    #: "the model did not return a valid proposal", it is a row asserting the
    #: genome produced nothing usable when in fact nothing was ever asked of
    #: it. Distinct from REFUSED because the loop did not decline — it ran,
    #: assembled context, and reached a provider that could not answer.
    CALL_FAILED = "call_failed"


#: Statuses a Cell may be woken from. Dead is Charter C8; quarantined is §18.2
#: — a Cell under restriction that can still deliberate is not restricted.
#: Dormant is allowed on purpose: §17.2's whole point is that a wake event
#: brings a dormant Cell back, and `lifecycle.wake` is how it becomes alive.
_CAN_DELIBERATE = frozenset({CellStatus.ALIVE, CellStatus.DORMANT})


class ProposalSink(Protocol):
    """The §23 seam: where a recorded proposal goes for review.

    `approval` reads proposals and regenerates wakes, so it sits *above* this
    module and cannot be imported from it. This inverts that edge in the shape
    `population.Displacer` and `sweeper.ExternalOperationChecker` already
    established, rather than adding a back-edge or a function-local import.

    **Note what the signature cannot accept.** It takes a `proposal_id` and
    nothing else — no tier, no cost, no exposure. Like `Displacer`'s inability
    to see the child being born, that is a constraint expressed as a signature:
    §23.5 warns the approval queue "will be optimised against by Cells", so
    every input to a review decision must be one the queue reads for itself.
    A parameter here through which a caller could pass a pre-computed risk tier
    would be the hole that clause describes.

    Called *inside* the caller's transaction: a proposal recorded without its
    queue entry is a proposal no operator sees.
    """

    def enqueue_locked(self, conn: sqlite3.Connection, *, proposal_id: str) -> None: ...


@dataclass(frozen=True)
class Deliberation:
    deliberation_id: str
    cell_id: str
    wake_key: str
    wake_reason: str
    genome_hash: str
    model_call_id: str | None
    #: The second, separately-billed call made when the first reply failed to
    #: validate — NULL for every deliberation that never needed one (ADR-069).
    repair_model_call_id: str | None
    status: str
    failure_reason: str | None
    context_tokens: int
    proposal_id: str | None
    prediction_ids: tuple[str, ...]
    created_at_utc: datetime


def _system_prompt(candidates: int = 1) -> str:
    """The instruction half of the prompt. Fixed kernel text, never genome
    content — a genome that could rewrite these instructions would be a Cell
    editing the constitution it is judged against.

    `candidates` above 1 swaps only the reply-format paragraph for verbalized
    sampling's (ADR-089). The count is a genome value, but it selects between
    two fixed kernel texts and is never itself text the model is told to obey,
    so this is still not a genome rewriting its instructions. A genome that
    declares nothing gets the exact bytes every wake got before the field
    existed (pinned by a test, and by the golden run's token counts).
    """
    if candidates == 1:
        reply_format = (
            "You are being woken to deliberate. You cannot take any action. Your only "
            "output is a single proposal, which is recorded and read by the operator. "
            "Nothing you propose is executed automatically.\n\n"
            "Reply with ONE JSON object and nothing else — no prose before or after. "
            "It must match this schema exactly. Every REQUIRED field must be present, "
            "and unknown fields are rejected:\n\n"
        )
    else:
        reply_format = (
            "You are being woken to deliberate. You cannot take any action. Your "
            "output is a set of candidate proposals; one of them is recorded and read "
            "by the operator. Nothing you propose is executed automatically.\n\n"
            f"{proposal_module.candidates_instruction(candidates)}\n\n"
            "Each proposal object must match this schema exactly. Every REQUIRED field "
            "must be present, and unknown fields are rejected:\n\n"
        )
    return (
        "You are a Cell in the MITOSIS colony: an autonomous economic agent under "
        "an immutable kernel you cannot modify.\n\n"
        f"{reply_format}"
        f"{proposal_module.response_schema_hint()}\n\n"
        "Guidance:\n"
        "- Propose something your genome and your record actually support.\n"
        "- If nothing is worth doing, use kind 'abstain' and say why. That is a "
        "legitimate answer; inventing work is not.\n"
        "- Predictions are scored with a proper scoring rule and cannot be edited "
        "afterwards. State claims that will be unambiguously true or false by "
        "their horizon.\n"
        "- Never state a probability of 0 or 1.\n"
        "- Send only the keys your chosen kind needs. A key you have nothing to "
        "put in is left out entirely, never sent empty."
    )


def _repair_instruction(error: str) -> str:
    """The follow-up turn sent after an unparseable reply (ADR-069, corrected
    by ADR-102).

    **Naming only the error made the second reply worse than the first.**
    ADR-069 argued that restating the schema "would waste tokens on the part
    that was never the problem", because the schema is the first turn's own
    content and still in context. Measured on `claude-haiku-4-5` (2026-09-16),
    the part that was never the problem is precisely what a small model drops:
    told `rationale: Field required; estimated_cost_minor_units: Field
    required`, it returned an object carrying exactly those two keys and no
    `summary` — a key it had already produced correctly one turn earlier. Two
    billed calls, nothing recorded. A repair turn that names a subset of the
    required keys reads as a *specification* of the reply, not as a patch to
    one.

    So this turn now says two things the error alone could not:

    - **Edit, do not regenerate.** The model's own prior reply is already the
      middle message of the repair request; the instruction now points at it
      and asks for that object back with the named fault fixed, so the keys it
      got right have somewhere to survive. This changes no message the request
      carries — only what the model is told to do with one it already has.
    - **The whole required-key list**, from `proposal.always_required_keys()`
      so it cannot drift from the schema the first turn rendered. This is what
      covers the case an edit instruction cannot: a first reply that was not
      JSON at all has no object to edit from.

    "This is your only chance" is true and stated rather than implied:
    `MAX_PARSE_REPAIR_ATTEMPTS` really is 1, and a model told it has one shot
    is closer to the truth than one that thinks it can iterate.
    """
    required = ", ".join(proposal_module.always_required_keys())
    return (
        "That reply did not validate:\n"
        f"    {error}\n\n"
        "Correct the JSON object you just sent. Do not write a new one: keep "
        "every key you already sent, with its value unchanged, and change only "
        "what the error above names. A key you got right is still right.\n\n"
        f"Whatever you change, the corrected object must still carry: {required} "
        f'(risk_tier only if your kind is not "{proposal_module.ProposalKind.ABSTAIN.value}"), '
        "plus the payload key your kind requires.\n\n"
        "Reply with ONE corrected JSON object and nothing else — no prose "
        "before or after. This is your only chance to fix it: if this reply "
        "does not validate either, nothing from this wake is recorded."
    )


def _genome_content(conn: sqlite3.Connection, cell: Cell) -> dict:
    """The Cell's genome content, as data.

    Read from the stored canonical JSON rather than recomputed, so what the
    Cell is shown is exactly what its hash commits to (§16.1).
    """
    row = conn.execute(
        "SELECT canonical_genome_json FROM cell_genomes WHERE genome_hash = ?",
        (cell.genome_hash,),
    ).fetchone()
    if row is None:
        raise DeliberationError(f"cell {cell.cell_id} has no genome row")
    content = json.loads(row["canonical_genome_json"])
    if not isinstance(content, dict):
        raise DeliberationError("genome content must be a JSON object")
    return content


def _unfunded_books(conn: sqlite3.Connection, cell: Cell) -> list[str]:
    """Books the Cell would need for a gateway call and has no balance in.

    **USD_REAL and RESOURCE regardless of the Cell's own book**, because that
    is what `gateway.call_model` reserves — a USD_SIM Cell with a healthy
    synthetic balance still cannot make a model call without those two. Getting
    this wrong the obvious way (checking `cell.book`) produces a Cell that
    passes the pre-check and then fails inside the gateway with its reservation
    half-made.

    This is a courtesy check, not the enforcement: Charter C4 in the gateway is
    what actually stops an overspend. The value of doing it here is that a
    refusal costs nothing and is recorded, whereas the gateway's refusal is an
    exception in the middle of a wake.
    """
    unfunded = []
    for book in (Book.USD_REAL, Book.RESOURCE):
        if ledger.get_balance(conn, cell_cash(cell.cell_id), book) < MIN_CASH_TO_DELIBERATE:
            unfunded.append(book.value)
    return unfunded


def get_deliberation_by_wake_key(
    conn: sqlite3.Connection, wake_key: str
) -> Deliberation | None:
    row = conn.execute(
        "SELECT * FROM deliberations WHERE wake_key = ?", (wake_key,)
    ).fetchone()
    return _row_to_deliberation(conn, row) if row else None


def get_deliberation(conn: sqlite3.Connection, deliberation_id: str) -> Deliberation | None:
    row = conn.execute(
        "SELECT * FROM deliberations WHERE deliberation_id = ?", (deliberation_id,)
    ).fetchone()
    return _row_to_deliberation(conn, row) if row else None


def _row_to_deliberation(conn: sqlite3.Connection, row: sqlite3.Row) -> Deliberation:
    proposal_row = conn.execute(
        "SELECT proposal_id FROM proposals WHERE deliberation_id = ?",
        (row["deliberation_id"],),
    ).fetchone()
    prediction_rows = conn.execute(
        "SELECT prediction_id FROM deliberation_predictions WHERE deliberation_id = ? "
        "ORDER BY prediction_id",
        (row["deliberation_id"],),
    ).fetchall()
    return Deliberation(
        deliberation_id=row["deliberation_id"],
        cell_id=row["cell_id"],
        wake_key=row["wake_key"],
        wake_reason=row["wake_reason"],
        genome_hash=row["genome_hash"],
        model_call_id=row["model_call_id"],
        repair_model_call_id=row["repair_model_call_id"],
        status=row["status"],
        failure_reason=row["failure_reason"],
        context_tokens=row["context_tokens"],
        proposal_id=proposal_row["proposal_id"] if proposal_row else None,
        prediction_ids=tuple(r["prediction_id"] for r in prediction_rows),
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
    )


def get_proposal(conn: sqlite3.Connection, proposal_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()
    if row is None:
        return None
    return {
        "proposal_id": row["proposal_id"],
        "deliberation_id": row["deliberation_id"],
        "cell_id": row["cell_id"],
        "kind": row["kind"],
        "summary": row["summary"],
        "rationale": row["rationale"],
        "risk_tier": row["risk_tier"],
        "estimated_cost_minor_units": row["estimated_cost_minor_units"],
        "payload": json.loads(row["payload_json"]),
        "created_at_utc": row["created_at_utc"],
    }


def list_proposals(conn: sqlite3.Connection, *, cell_id: str | None = None) -> list[dict]:
    if cell_id is None:
        rows = conn.execute("SELECT proposal_id FROM proposals ORDER BY rowid").fetchall()
    else:
        rows = conn.execute(
            "SELECT proposal_id FROM proposals WHERE cell_id = ? ORDER BY rowid",
            (cell_id,),
        ).fetchall()
    return [get_proposal(conn, r["proposal_id"]) for r in rows]  # type: ignore[misc]


@dataclass(frozen=True)
class _RepairResult:
    """What one parse-repair attempt produced (ADR-069).

    `model_call_id` is `None` only when the attempt could not be made at all
    — an exhausted cap, an unpriced model, anything `gateway.call_model`
    raises before a call exists to bill. Whenever a repair call *was* made,
    its id is carried regardless of what came back, because §24.1 requires
    every call to be traceable — including one that failed at the provider,
    where the id is the only thing naming *which* outage, and the only way to
    tell a clean `failed` (released, nothing billed) from an
    `execution_unknown` whose funds are still committed.
    """

    model_call_id: str | None
    parsed: proposal_module.Proposal | None
    note: str
    #: What verbalized sampling did on the repaired reply (ADR-089); `None`
    #: for an ordinary single-reply wake.
    sampling: dict[str, int] | None = None


def _parse_reply(
    reply: str, *, candidates: int, wake_key: str
) -> tuple[proposal_module.Proposal, dict[str, int] | None]:
    """One reply into one proposal — directly, or by choosing among a
    verbalized-sampling reply's valid candidates (ADR-089).

    **The choice is uniform and seeded by the wake, never by the reply.** The
    probabilities a Cell writes beside its candidates are validated and then
    discarded: a probability that moved the choice would be a number a Cell
    could learn to write (§23.5), and a seed taken from anything in the reply
    would let the reply steer it the same way. Seeding by `wake_key` makes a
    redelivered or replayed wake choose the same candidate (§26).
    """
    if candidates == 1:
        return proposal_module.parse(reply), None
    valid, rejected = proposal_module.parse_candidates(reply)
    chosen = random.Random(f"verbalized:{wake_key}").randrange(len(valid))
    return valid[chosen], {
        "verbalized_candidates": candidates,
        "candidates_valid": len(valid),
        "candidates_rejected": len(rejected),
        "chosen_index": chosen,
    }


def _attempt_parse_repair(
    conn: sqlite3.Connection,
    *,
    cell: Cell,
    provider: providers.ModelProvider,
    model: str,
    assembled: context.AssembledContext,
    reply: str,
    error: str,
    max_tokens: int,
    temperature: float | None,
    experiment_id: str | None,
    wake_key: str,
    candidates: int = 1,
) -> _RepairResult:
    """One bounded re-prompt after an unparseable reply
    (`MAX_PARSE_REPAIR_ATTEMPTS`; ADR-069).

    A wholly new, separately-priced, separately-capped `gateway.call_model`
    — never a retry of the first reservation, and not the `execution_unknown`
    retry `gateway.py`'s own docstring declines: the first call is known to
    have succeeded and been billed, so what needs fixing is the *reply text*,
    not an ambiguous call outcome.

    **Best-effort for economic failures only.** An *unaffordable* or *refused*
    second call — a real-spend cap, an insufficient balance, the breaker, any
    `_REPAIR_UNATTEMPTABLE_ERRORS` the gateway raises before a call is made —
    is caught here and reported in `note` rather than raised, so it degrades to
    exactly the pre-repair behaviour (`_unfunded_books`' own reasoning: "a
    refusal costs nothing and is recorded, whereas the gateway's refusal is
    an exception in the middle of a wake"). A repair therefore never turns an
    UNPARSEABLE reply into a *raise* on economic grounds. But a genuine fault —
    a bug in this function, a locked database — is deliberately *not* caught: it
    propagates exactly as it already would from the first, unwrapped
    `gateway.call_model` in `deliberate()`, rather than being disguised as "the
    model could not format its reply."
    """
    try:
        repair_call = gateway.call_model(
            conn,
            cell_id=cell.cell_id,
            provider=provider,
            request=providers.ModelRequest(
                model=model,
                messages=(
                    {"role": "user", "content": f"{_system_prompt(candidates)}\n\n{assembled.render()}"},
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": _repair_instruction(error)},
                ),
                max_tokens=max_tokens,
                temperature=temperature,
            ),
            experiment_id=experiment_id,
            idempotency_key=f"deliberation:{wake_key}:repair",
        )
    except _REPAIR_UNATTEMPTABLE_ERRORS as exc:
        # An unaffordable/refused second call is a fact about the colony, not a
        # crash: degrade to the pre-repair outcome (see _REPAIR_UNATTEMPTABLE_ERRORS).
        # Any *other* exception is a real fault and propagates, matching the
        # first, unwrapped gateway call in deliberate().
        return _RepairResult(model_call_id=None, parsed=None, note=f"repair not attempted: {exc}")

    # The repair reached a provider that could not answer (ADR-101). The first
    # reply is still the Cell's own unparseable one — that outcome stands — but
    # the note must say the second call never produced a reply rather than that
    # it produced one that failed to validate.
    repair_failure = gateway.call_failure(repair_call)
    if repair_failure is not None:
        return _RepairResult(
            model_call_id=repair_call.model_call_id,
            parsed=None,
            note=f"repair call failed at the provider: {repair_failure}",
        )

    try:
        parsed, sampling = _parse_reply(
            repair_call.response_text or "", candidates=candidates, wake_key=wake_key
        )
    except proposal_module.ProposalError as exc:
        return _RepairResult(
            model_call_id=repair_call.model_call_id,
            parsed=None,
            note=f"repair reply also failed to validate: {exc}",
        )
    return _RepairResult(
        model_call_id=repair_call.model_call_id, parsed=parsed, note="repaired", sampling=sampling
    )


# --- workflow structures (ADR-093) ---------------------------------------------


def _refinement_instruction() -> str:
    return (
        "Above is the proposal you drafted for this wake. Critique it before it is "
        "recorded: is every claim in it specific enough to check, is its cost estimate "
        "honest, and does anything in the context contradict it? Then reply with the "
        "improved proposal in exactly the JSON format described above — or the same "
        "proposal unchanged if the critique finds nothing to fix. Reply with the JSON "
        "object only. If this reply is valid it replaces the draft."
    )


def _review_instruction(first_draft: str, second_draft: str) -> str:
    return (
        "You drafted two proposals for this wake independently, from the same context. "
        "Review both against the context above: which is more specific, more honest "
        "about cost and risk, and better supported? Reply with one proposal in exactly "
        "the JSON format described above — one of the drafts, or a combination of "
        "their best parts. Reply with the JSON object only.\n\n"
        f"Draft A:\n{first_draft}\n\nDraft B:\n{second_draft}"
    )


#: `self_critique_loop`'s designed bound (ADR-103): at most this many revisions,
#: so at most twice this many calls after the draft. Bounded for ADR-069's
#: reason — a critic that always says "revise" must cost a known amount.
MAX_CRITIQUE_REVISIONS = 2
MAX_CRITIQUE_ISSUES = 5
MAX_CRITIQUE_ISSUE_CHARS = 300


def _critique_instruction() -> str:
    return (
        "Above is the proposal you currently hold for this wake. Judge it before it is "
        "recorded: is every claim specific enough to check, is its cost estimate honest, "
        "and does anything in the context contradict it? Do not rewrite it here. Reply "
        'with ONE JSON object and nothing else: {"verdict": "keep"} if it is ready, or '
        '{"verdict": "revise", "issues": ["...", ...]} naming at most '
        f"{MAX_CRITIQUE_ISSUES} specific problems."
    )


def _address_instruction(issues: tuple[str, ...]) -> str:
    listed = "\n".join(f"- {issue}" for issue in issues)
    return (
        "A critique of the proposal above found these problems:\n"
        f"{listed}\n\n"
        "Reply with the revised proposal in exactly the JSON format described above, "
        "addressing each of them. Reply with the JSON object only. If this reply is "
        "valid it replaces the proposal you hold."
    )


def _parse_verdict(raw_text: str) -> workflow_graph.Verdict:
    """A critique reply, validated as strictly as a proposal is (ADR-103).

    Raises `ProposalError` so `_workflow_call` classifies an invalid verdict
    exactly as it classifies an invalid proposal: the step is recorded and the
    proposal in hand is kept. The verdict lives only inside the wake — it is
    never a prediction, never a review input, never fitness — so the one thing a
    Cell can buy by gaming it is more or fewer calls it pays for itself.
    """
    try:
        payload = json.loads(proposal_module._strip_code_fence(raw_text))
    except json.JSONDecodeError as exc:
        raise proposal_module.ProposalError(f"verdict is not JSON: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) - {"verdict", "issues"}:
        raise proposal_module.ProposalError("verdict must be an object with only 'verdict' and 'issues'")
    verdict = payload.get("verdict")
    issues = payload.get("issues", [])
    if verdict not in ("keep", "revise"):
        raise proposal_module.ProposalError(f"verdict must be 'keep' or 'revise', got {verdict!r}")
    if not isinstance(issues, list) or not all(isinstance(i, str) and i.strip() for i in issues):
        raise proposal_module.ProposalError("issues must be a list of non-empty strings")
    if verdict == "revise" and not issues:
        raise proposal_module.ProposalError("a 'revise' verdict must name at least one issue")
    if len(issues) > MAX_CRITIQUE_ISSUES or any(len(i) > MAX_CRITIQUE_ISSUE_CHARS for i in issues):
        raise proposal_module.ProposalError(
            f"at most {MAX_CRITIQUE_ISSUES} issues of at most {MAX_CRITIQUE_ISSUE_CHARS} characters"
        )
    return workflow_graph.Verdict(verdict, tuple(i.strip() for i in issues) if verdict == "revise" else ())


@dataclass(frozen=True)
class _WorkflowStep:
    name: str
    #: `None` only when the call could not be attempted at all; a call that was
    #: made is carried whether or not its reply validated (§24.1).
    model_call_id: str | None
    parsed: proposal_module.Proposal | None
    note: str


def _workflow_call(
    conn: sqlite3.Connection,
    *,
    name: str,
    cell: Cell,
    provider: providers.ModelProvider,
    model: str,
    messages: tuple[dict, ...],
    max_tokens: int,
    temperature: float | None,
    experiment_id: str | None,
    wake_key: str,
    parse,
) -> _WorkflowStep:
    """One further call of a multi-call wake.

    **Its own gateway reservation, its own idempotency key** (Charter C4, C6):
    every step is a separate `gateway.call_model`, so the Cell pays for each and
    a redelivered wake that crashed between steps replays the steps already
    billed instead of buying them twice. Failure is classified exactly as a
    parse repair's is: an unaffordable or refused call, a call that failed at
    the provider, or a reply that does not validate, each keeps the draft
    already in hand; a genuine fault propagates.
    """
    try:
        call = gateway.call_model(
            conn,
            cell_id=cell.cell_id,
            provider=provider,
            request=providers.ModelRequest(
                model=model, messages=messages, max_tokens=max_tokens, temperature=temperature,
            ),
            experiment_id=experiment_id,
            idempotency_key=f"deliberation:{wake_key}:workflow:{name}",
        )
    except _REPAIR_UNATTEMPTABLE_ERRORS as exc:
        return _WorkflowStep(name=name, model_call_id=None, parsed=None, note=f"not attempted: {exc}")
    # A step whose call failed at the provider keeps the draft exactly as a
    # step whose reply failed to validate does — but the record must not say
    # the model answered badly when it never answered (§24.2; ADR-101).
    failure = gateway.call_failure(call)
    if failure is not None:
        return _WorkflowStep(
            name=name,
            model_call_id=call.model_call_id,
            parsed=None,
            note=f"call failed at the provider: {failure}",
        )
    try:
        parsed = parse(call.response_text or "")
    except proposal_module.ProposalError as exc:
        return _WorkflowStep(
            name=name, model_call_id=call.model_call_id, parsed=None, note=f"did not validate: {exc}"
        )
    return _WorkflowStep(name=name, model_call_id=call.model_call_id, parsed=parsed, note="ok")


def _iterative_refinement(conn, *, draft, prompt, **step) -> tuple[proposal_module.Proposal | None, list[_WorkflowStep]]:
    """Draft → one self-critique that replies with the revision.

    Self-critique, not criticism in §24.3's sense: one wake holds one provider,
    and §24.3 routes criticism to a different family. The genome can select
    this shape; it cannot make the critic independent."""
    revise = _workflow_call(
        conn,
        name="revise",
        messages=(
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": draft.model_dump_json()},
            {"role": "user", "content": _refinement_instruction()},
        ),
        parse=proposal_module.parse,
        **step,
    )
    return revise.parsed, [revise]


def _parallel_review(
    conn, *, draft, prompt, draft_prompt, draft_max_tokens, candidates, wake_key, **step
) -> tuple[proposal_module.Proposal | None, list[_WorkflowStep]]:
    """Two independent drafts → one review that replies with a single proposal.

    The second draft sees exactly the first call's prompt and nothing of the
    first draft — otherwise it is a revision, not an independent draft, and
    the review compares a proposal with its own echo."""
    second = _workflow_call(
        conn,
        name="draft:1",
        messages=({"role": "user", "content": draft_prompt},),
        parse=lambda text: _parse_reply(text, candidates=candidates, wake_key=f"{wake_key}:draft:1")[0],
        wake_key=wake_key,
        **{**step, "max_tokens": draft_max_tokens},
    )
    if second.parsed is None:
        return None, [second]
    review = _workflow_call(
        conn,
        name="review",
        messages=({
            "role": "user",
            "content": f"{prompt}\n\n"
            f"{_review_instruction(draft.model_dump_json(), second.parsed.model_dump_json())}",
        },),
        parse=proposal_module.parse,
        wake_key=wake_key,
        **step,
    )
    return review.parsed, [second, review]


def _self_critique_loop(conn, *, draft, prompt, **step) -> tuple[proposal_module.Proposal | None, list[_WorkflowStep]]:
    """Critique → revise, repeated until kept or `MAX_CRITIQUE_REVISIONS`.

    The graph decides which step runs next; every step is still one
    `_workflow_call` on its own key (`critique:0`, `revise:0`, `critique:1`, …),
    so billing, replay and the draft-is-the-floor rule are exactly the other
    structures'. Self-critique again, not §24.3 criticism: one provider."""

    def critique(current, round_):
        s = _workflow_call(
            conn,
            name=f"critique:{round_}",
            messages=(
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": current.model_dump_json()},
                {"role": "user", "content": _critique_instruction()},
            ),
            parse=_parse_verdict,
            **step,
        )
        return s.parsed, (replace(s, note=f"ok: {s.parsed.verdict}") if s.parsed else s)

    def revise(current, issues, round_):
        s = _workflow_call(
            conn,
            name=f"revise:{round_}",
            messages=(
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": current.model_dump_json()},
                {"role": "user", "content": _address_instruction(issues)},
            ),
            parse=proposal_module.parse,
            **step,
        )
        return s.parsed, s

    try:
        result = workflow_graph.run_critique_loop(
            draft=draft, critique=critique, revise=revise, max_revisions=MAX_CRITIQUE_REVISIONS,
        )
    except workflow_graph.GraphUnavailable as exc:
        # Degrades like an unaffordable step: nothing was attempted, the draft
        # is kept, and the record says why on every wake it happens.
        return None, [_WorkflowStep(name="critique:0", model_call_id=None, parsed=None,
                                    note=f"not attempted: {exc}")]
    return result.final, result.steps


#: Every structure but a single pass has a runner here, and only here —
#: `test_every_declared_structure_has_a_runner` pins the two sets together, so
#: a structure added to the genome cannot quietly run as a single pass.
_WORKFLOW_RUNNERS = {
    "iterative_refinement": _iterative_refinement,
    "parallel_review": _parallel_review,
    "self_critique_loop": _self_critique_loop,
}


def _run_workflow(
    conn: sqlite3.Connection,
    *,
    structure: str,
    cell: Cell,
    provider: providers.ModelProvider,
    model: str,
    assembled: context.AssembledContext,
    draft: proposal_module.Proposal,
    max_tokens: int,
    draft_max_tokens: int,
    candidates: int,
    temperature: float | None,
    experiment_id: str | None,
    wake_key: str,
) -> tuple[proposal_module.Proposal, dict]:
    """Run a genome's multi-call structure over a draft that already validated.

    The draft is the floor: a step that fails leaves the wake exactly where a
    single pass would have left it, never worse, and the record says which
    proposal was kept and why."""
    rendered = assembled.render()
    step = dict(
        cell=cell, provider=provider, model=model, max_tokens=max_tokens,
        temperature=temperature, experiment_id=experiment_id,
    )
    runner = _WORKFLOW_RUNNERS[structure]
    if runner is _parallel_review:
        final, steps = runner(
            conn, draft=draft, prompt=f"{_system_prompt()}\n\n{rendered}",
            draft_prompt=f"{_system_prompt(candidates)}\n\n{rendered}",
            draft_max_tokens=draft_max_tokens, candidates=candidates, wake_key=wake_key, **step,
        )
    else:
        final, steps = runner(
            conn, draft=draft, prompt=f"{_system_prompt()}\n\n{rendered}", wake_key=wake_key, **step,
        )
    record = {
        "structure": structure,
        "steps": [
            {"step": s.name, "model_call_id": s.model_call_id, "note": s.note} for s in steps
        ],
        "recorded": "final" if final is not None else "first_draft",
    }
    return (final if final is not None else draft), record


def deliberate(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    provider: providers.ModelProvider,
    wake_key: str,
    wake_reason: str = WAKE_SCHEDULED_RESEARCH,
    model: str,
    context_budget_tokens: int = context.DEFAULT_CONTEXT_TOKEN_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    proposal_sink: ProposalSink | None = None,
) -> Deliberation:
    """Wake one Cell, think once, record what it proposed.

    Idempotent on `wake_key` (Charter C6): a redelivered wake returns the
    existing deliberation without re-assembling context or paying for a second
    model call.

    One wake is one trace when tracing is opted in (ADR-104): this span is the
    root, each gateway call and each graph step nests under it.
    """
    with tracing.span(
        "cell_wake",
        inputs={"cell_id": cell_id, "wake_reason": wake_reason, "wake_key": wake_key},
        metadata={"cell_id": cell_id, "wake_key": wake_key, "model": model},
    ) as span:
        result = _deliberate(
            conn, cell_id=cell_id, provider=provider, wake_key=wake_key, wake_reason=wake_reason,
            model=model, context_budget_tokens=context_budget_tokens, max_tokens=max_tokens,
            proposal_sink=proposal_sink,
        )
        span.finish({
            "status": result.status,
            "deliberation_id": result.deliberation_id,
            "proposal_id": result.proposal_id,
            "failure_reason": result.failure_reason,
        })
        return result


def _deliberate(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    provider: providers.ModelProvider,
    wake_key: str,
    wake_reason: str,
    model: str,
    context_budget_tokens: int,
    max_tokens: int,
    proposal_sink: ProposalSink | None,
) -> Deliberation:
    existing = get_deliberation_by_wake_key(conn, wake_key)
    if existing is not None:
        return existing

    cell = lifecycle.get_cell(conn, cell_id)
    if cell is None:
        raise DeliberationError(f"no such cell: {cell_id}")

    if cell.status not in _CAN_DELIBERATE:
        # Recorded, not raised: a refusal is a fact about the colony, and a
        # dead Cell being woken repeatedly is exactly the kind of thing that
        # should show up in a query rather than only in a traceback.
        return _record_refusal(
            conn,
            cell=cell,
            wake_key=wake_key,
            wake_reason=wake_reason,
            reason=(
                f"cell is {cell.status.value}; only "
                f"{'/'.join(sorted(s.value for s in _CAN_DELIBERATE))} may deliberate "
                "(Charter C8 for dead, §18.2 for quarantined)"
            ),
        )

    unfunded = _unfunded_books(conn, cell)
    if unfunded:
        return _record_refusal(
            conn,
            cell=cell,
            wake_key=wake_key,
            wake_reason=wake_reason,
            reason=(
                f"cell cannot pay for its own thinking (§15.4): no balance in "
                f"{', '.join(unfunded)}"
            ),
        )

    canonical_genome = _genome_content(conn, cell)
    assembled = context.assemble(
        conn,
        cell=cell,
        canonical_genome=canonical_genome,
        wake_reason=wake_reason,
        budget_tokens=context_budget_tokens,
    )

    # **Read once, used twice** (§2.6; ADR-044). A Cell's thinking and the
    # forecasts it makes in the same breath must land on the same experiment,
    # and reading the attribution again inside the write lock below could give
    # two different answers if the experiment concluded in between — a model
    # call on one experiment and its own predictions on another, with no way to
    # tell afterwards which was right. So it is resolved here and carried.
    #
    # This is also the dimension it matters most for: §2.6's "real cash
    # consumed" was reported as 0 for every experiment whose Cell simply *ran*,
    # because a wake never named the experiment it was thinking about.
    experiment_id = experiments.attribution_for(conn, cell.cell_id)

    # §14.1's sampling-temperature mutation operator, read from this Cell's
    # own genome rather than pinned as a kernel constant (ADR-050, ADR-067).
    # `None` when the genome declares no policy — the provider's own default,
    # not a kernel opinion. Resolved once and reused for a repair attempt
    # below: a repair reasons about the same genome, so it samples the same way.
    temperature = genome.temperature_of(canonical_genome)
    # ADR-089: verbalized sampling, read from the same genome policy. The token
    # budget scales with it — a Cell asked for five ideas pays for five ideas'
    # worth of output, which is the honest price of asking, rather than a
    # truncated reply that fails to parse and buys a repair call instead.
    candidates = genome.verbalized_candidates_of(canonical_genome)
    request_max_tokens = max_tokens * candidates

    # The gateway call commits its own reservation before the external call
    # (ADR-022), so it happens outside every transaction this module opens.
    call = gateway.call_model(
        conn,
        cell_id=cell.cell_id,
        provider=provider,
        request=providers.ModelRequest(
            model=model,
            messages=(
                {"role": "user", "content": f"{_system_prompt(candidates)}\n\n{assembled.render()}"},
            ),
            max_tokens=request_max_tokens,
            temperature=temperature,
        ),
        experiment_id=experiment_id,
        idempotency_key=f"deliberation:{wake_key}",
    )

    # **Asked before `response_text` is read, and that order is the whole
    # fix.** `gateway.call_model` does not raise when the provider fails; it
    # classifies the outcome, records it, and returns the call — so an outage
    # arrives here as a `ModelCall` carrying no reply, and the empty string
    # parses exactly like a model that ignored the schema. ADR-069 assumed this
    # could not happen ("the first call is known to have succeeded and been
    # billed; it returned response text"), and on that assumption an outage was
    # recorded as this Cell's unparseable reply and bought a second call to the
    # very provider that had just failed (ADR-101).
    provider_failure = gateway.call_failure(call)
    if provider_failure is not None:
        return _record_call_failure(
            conn,
            cell=cell,
            wake_key=wake_key,
            wake_reason=wake_reason,
            assembled=assembled,
            model_call_id=call.model_call_id,
            reason=provider_failure,
        )

    reply = call.response_text or ""
    repair_model_call_id = None
    try:
        parsed, sampling = _parse_reply(reply, candidates=candidates, wake_key=wake_key)
    except proposal_module.ProposalError as exc:
        # §24's "retries controlled failures" (ADR-069): one bounded re-prompt
        # before giving up. The first call already succeeded and was billed,
        # so this is not the `execution_unknown` retry `gateway.py` declines —
        # see `_attempt_parse_repair`.
        repair = _attempt_parse_repair(
            conn,
            cell=cell,
            provider=provider,
            model=model,
            assembled=assembled,
            reply=reply,
            error=str(exc),
            max_tokens=request_max_tokens,
            temperature=temperature,
            experiment_id=experiment_id,
            wake_key=wake_key,
            candidates=candidates,
        )
        if repair.parsed is None:
            return _record_unparseable(
                conn,
                cell=cell,
                wake_key=wake_key,
                wake_reason=wake_reason,
                assembled=assembled,
                model_call_id=call.model_call_id,
                repair_model_call_id=repair.model_call_id,
                reason=f"{exc} ({repair.note})",
            )
        parsed, sampling, repair_model_call_id = repair.parsed, repair.sampling, repair.model_call_id

    # ADR-093: §16.3's inheritable workflow structure. Runs only over a draft
    # that already validated — a wake with nothing to refine or review is
    # recorded unparseable above, and buys no further calls.
    workflow = None
    structure = genome.workflow_structure_of(canonical_genome)
    if structure != genome.WORKFLOW_SINGLE_PASS:
        parsed, workflow = _run_workflow(
            conn,
            structure=structure,
            cell=cell,
            provider=provider,
            model=model,
            assembled=assembled,
            draft=parsed,
            max_tokens=max_tokens,
            draft_max_tokens=request_max_tokens,
            candidates=candidates,
            temperature=temperature,
            experiment_id=experiment_id,
            wake_key=wake_key,
        )

    return _record_proposal(
        conn,
        cell=cell,
        wake_key=wake_key,
        wake_reason=wake_reason,
        assembled=assembled,
        model_call_id=call.model_call_id,
        repair_model_call_id=repair_model_call_id,
        parsed=parsed,
        # Carried rather than re-derived, so the call and the forecasts it
        # produced cannot land on two different experiments.
        experiment_id=experiment_id,
        proposal_sink=proposal_sink,
        sampling=sampling,
        workflow=workflow,
    )


def _insert_deliberation_locked(
    conn: sqlite3.Connection,
    *,
    cell: Cell,
    wake_key: str,
    wake_reason: str,
    assembled: context.AssembledContext | None,
    model_call_id: str | None,
    repair_model_call_id: str | None = None,
    status: str,
    failure_reason: str | None,
) -> str:
    deliberation_id = ids.new_id()
    record = assembled.to_record() if assembled else {"budget_tokens": 0, "sections": []}
    dropped = list(assembled.dropped) if assembled else []
    conn.execute(
        """
        INSERT INTO deliberations (
            deliberation_id, cell_id, wake_key, wake_reason, genome_hash,
            model_call_id, repair_model_call_id, context_json, context_tokens,
            context_dropped_json, status, failure_reason, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            deliberation_id,
            cell.cell_id,
            wake_key,
            wake_reason,
            cell.genome_hash,
            model_call_id,
            repair_model_call_id,
            json.dumps(record, sort_keys=True, separators=(",", ":")),
            assembled.tokens if assembled else 0,
            json.dumps(dropped, separators=(",", ":")),
            status,
            failure_reason,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return deliberation_id


def _record_refusal(
    conn: sqlite3.Connection, *, cell: Cell, wake_key: str, wake_reason: str, reason: str
) -> Deliberation:
    conn.execute("BEGIN IMMEDIATE")
    try:
        deliberation_id = _insert_deliberation_locked(
            conn,
            cell=cell,
            wake_key=wake_key,
            wake_reason=wake_reason,
            assembled=None,
            model_call_id=None,
            status=DeliberationStatus.REFUSED,
            failure_reason=reason,
        )
        audit.record(
            conn,
            event_type="cell_wake_refused",
            cell_id=cell.cell_id,
            description=reason,
            metadata={"wake_key": wake_key, "wake_reason": wake_reason},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    result = get_deliberation(conn, deliberation_id)
    assert result is not None
    return result


def _record_unparseable(
    conn: sqlite3.Connection,
    *,
    cell: Cell,
    wake_key: str,
    wake_reason: str,
    assembled: context.AssembledContext,
    model_call_id: str,
    repair_model_call_id: str | None = None,
    reason: str,
) -> Deliberation:
    """A reply that did not validate — the first one, and the repair's if one
    was attempted (ADR-069).

    The Cell still paid for every call made — the tokens were burned whatever
    came back — so this is recorded rather than rolled back. Neither raw reply
    is stored: it is untrusted content (§19.4), and a prose blob sitting in the
    database is exactly what a later reader would mistake for a result.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        deliberation_id = _insert_deliberation_locked(
            conn,
            cell=cell,
            wake_key=wake_key,
            wake_reason=wake_reason,
            assembled=assembled,
            model_call_id=model_call_id,
            repair_model_call_id=repair_model_call_id,
            status=DeliberationStatus.UNPARSEABLE,
            failure_reason=reason,
        )
        audit.record(
            conn,
            event_type="cell_deliberation_unparseable",
            cell_id=cell.cell_id,
            description=reason,
            metadata={
                "wake_key": wake_key,
                "model_call_id": model_call_id,
                "repair_model_call_id": repair_model_call_id,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    result = get_deliberation(conn, deliberation_id)
    assert result is not None
    return result


def _record_call_failure(
    conn: sqlite3.Connection,
    *,
    cell: Cell,
    wake_key: str,
    wake_reason: str,
    assembled: context.AssembledContext,
    model_call_id: str,
    reason: str,
) -> Deliberation:
    """The provider could not answer, so this Cell never had a reply to be
    judged on (ADR-101).

    **Why this is not UNPARSEABLE.** §24.2 requires a material provider
    change to be treated as an *environment* regime change "so provider drift
    is not mistaken for Cell evolution", and an outage is the loudest provider
    change there is. Recorded as unparseable, it is a row asserting that this
    genome, on this context, produced nothing usable — a claim about the Cell,
    written from an observation about the network. Everything that counts
    these rows would count the provider's weather as the Cell's work, starting
    with `scripts/measure_parse_compliance.py`, whose whole output is a rate
    over exactly this status.

    **Why this is not REFUSED.** A refusal is the loop declining before it
    spends anything, and records no context because none was assembled. This
    wake ran: it assembled context, reserved, and reached a provider. The
    context is recorded for the same reason every other completed wake's is —
    §15's budget is only checkable if the selection is kept — and the
    `model_call_id` because §24.1 wants every call traceable, including the
    one that failed.

    **`failure_reason` is the gateway's own text, not a description composed
    here.** The layer that observed the failure defines it; this one repeats
    it. That is also what keeps Charter C14 intact without a second
    redaction — `gateway._handle_failure` has already run `providers.redact`
    over the provider's error.

    **No repair is bought.** `MAX_PARSE_REPAIR_ATTEMPTS` re-prompts a model
    that answered badly. There is no reply to re-prompt about, and the only
    provider a repair could call is the one that just failed.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        deliberation_id = _insert_deliberation_locked(
            conn,
            cell=cell,
            wake_key=wake_key,
            wake_reason=wake_reason,
            assembled=assembled,
            model_call_id=model_call_id,
            status=DeliberationStatus.CALL_FAILED,
            failure_reason=reason,
        )
        audit.record(
            conn,
            event_type="cell_deliberation_call_failed",
            cell_id=cell.cell_id,
            description=reason,
            metadata={"wake_key": wake_key, "model_call_id": model_call_id},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    result = get_deliberation(conn, deliberation_id)
    assert result is not None
    return result


def _record_proposal(
    conn: sqlite3.Connection,
    *,
    cell: Cell,
    wake_key: str,
    wake_reason: str,
    assembled: context.AssembledContext,
    model_call_id: str,
    repair_model_call_id: str | None = None,
    parsed: proposal_module.Proposal,
    experiment_id: str | None,
    proposal_sink: ProposalSink | None,
    sampling: dict[str, int] | None = None,
    workflow: dict | None = None,
) -> Deliberation:
    """Record the proposal, register its predictions, and queue it for review
    — one transaction.

    Atomic on purpose: a proposal whose predictions failed to register would
    be a Cell that stated a forecast the register has no record of, which is
    precisely the gap §8.5's register-before-outcome rule exists to close. The
    §23 queue entry joins the same transaction for the analogous reason — a
    proposal that exists but reached no review path is one the operator has no
    way to know about.
    """
    now = datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        deliberation_id = _insert_deliberation_locked(
            conn,
            cell=cell,
            wake_key=wake_key,
            wake_reason=wake_reason,
            assembled=assembled,
            model_call_id=model_call_id,
            repair_model_call_id=repair_model_call_id,
            status=DeliberationStatus.PROPOSED,
            failure_reason=None,
        )

        # §28's Phase 8: production is not gated, so this needs no approval —
        # what is gated is *external use* (`artifacts.export`). Folded into the
        # proposal's own transaction because a Cell that produced a deliverable
        # and a proposal in one wake did one thing, and a crash that recorded
        # half of it would lose the half that has no other record.
        artifact_id = None
        if parsed.artifact is not None:
            artifact_id = artifacts._create_locked(
                conn,
                cell_id=cell.cell_id,
                kind=parsed.artifact.kind,
                title=parsed.artifact.title,
                content=parsed.artifact.content,
                source_tool_call_ids=tuple(parsed.artifact.source_tool_call_ids),
                deliberation_id=deliberation_id,
                now=now,
            ).artifact_id

        proposal_id = ids.new_id()
        conn.execute(
            """
            INSERT INTO proposals (
                proposal_id, deliberation_id, cell_id, kind, summary, rationale,
                risk_tier, estimated_cost_minor_units, derived_from_untrusted,
                payload_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                deliberation_id,
                cell.cell_id,
                parsed.kind.value,
                parsed.summary,
                parsed.rationale,
                # ADR-068: None exactly when kind is abstain — the schema's
                # own CHECK (migration 0032) enforces the pairing.
                parsed.risk_tier.value if parsed.risk_tier is not None else None,
                parsed.estimated_cost_minor_units,
                # §18/§19.4: recorded from the *context that produced it*, not
                # from anything the Cell said. A Cell repeating a web page has
                # no incentive to mention that it is, and §0.3 would not let it
                # define the answer anyway.
                1 if assembled.contains_untrusted_external else 0,
                parsed.model_dump_json(),
                now.isoformat(),
            ),
        )

        for index, proposed in enumerate(parsed.predictions):
            registered = prediction._register_locked(
                conn,
                cell_id=cell.cell_id,
                claim=proposed.claim,
                probability=proposed.probability,
                resolves_by=now + timedelta(days=proposed.horizon_days),
                # §2.6's reality-gap dimension is *about* this: a forecast made
                # while an experiment runs is a forecast about that experiment.
                # Hardcoding None kept every Cell's own predictions out of the
                # one report built to score them (ADR-044).
                experiment_id=experiment_id,
                idempotency_key=f"deliberation:{wake_key}:{index}",
            )
            conn.execute(
                "INSERT INTO deliberation_predictions (deliberation_id, prediction_id) "
                "VALUES (?, ?)",
                (deliberation_id, registered.prediction_id),
            )

        if proposal_sink is not None:
            proposal_sink.enqueue_locked(conn, proposal_id=proposal_id)

        audit.record(
            conn,
            event_type="cell_deliberated",
            cell_id=cell.cell_id,
            description=f"{parsed.kind.value}: {parsed.summary}",
            metadata={
                "wake_key": wake_key,
                "wake_reason": wake_reason,
                "model_call_id": model_call_id,
                "repair_model_call_id": repair_model_call_id,
                "risk_tier": parsed.risk_tier.value if parsed.risk_tier is not None else None,
                "predictions": len(parsed.predictions),
                # Only when a genome asked for candidates (ADR-089): the audit
                # trail of every ordinary wake stays exactly as it was.
                **({"sampling": sampling} if sampling is not None else {}),
                # Only for a multi-call structure (ADR-093): which further
                # calls were made, what each produced, and which proposal won.
                **({"workflow": workflow} if workflow is not None else {}),
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_deliberation(conn, deliberation_id)
    assert result is not None
    return result


# --- wake events (§17.2) -----------------------------------------------------


def enqueue_wake(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    wake_reason: str = WAKE_SCHEDULED_RESEARCH,
    dedupe_key: str,
    priority: int = 100,
    available_at: datetime | None = None,
) -> object:
    """Schedule a wake. The first real producer on the event path — until now
    nothing in the kernel emitted a domain event through event_inbox."""
    return events.enqueue(
        conn,
        event_type=WAKE_EVENT_TYPE,
        source="colony",
        priority=priority,
        dedupe_key=dedupe_key,
        target=cell_id,
        payload={"cell_id": cell_id, "wake_reason": wake_reason},
        available_at=available_at,
    )


def _enqueue_wake_locked(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    wake_reason: str,
    dedupe_key: str,
    priority: int = 100,
) -> str | None:
    """Schedule a wake inside the caller's transaction; returns the event id.

    §23.3's approval expiry needs the expiry and the wake that regenerates the
    action to commit together — an expiry that committed alone would be an
    action silently dropped. Returns None if this wake is already queued, since
    the dedupe pre-check cannot be delegated to the wrapper's IntegrityError
    handling here: a ROLLBACK inside someone else's transaction would discard
    their work.
    """
    if events.get_by_dedupe_key(conn, dedupe_key) is not None:
        return None
    return events._enqueue_locked(
        conn,
        event_type=WAKE_EVENT_TYPE,
        source="colony",
        priority=priority,
        dedupe_key=dedupe_key,
        target=cell_id,
        payload={"cell_id": cell_id, "wake_reason": wake_reason},
    )


def run_wake_event(
    conn: sqlite3.Connection,
    event,
    *,
    provider: providers.ModelProvider,
    model: str,
    context_budget_tokens: int = context.DEFAULT_CONTEXT_TOKEN_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    proposal_sink: ProposalSink | None = None,
) -> Deliberation:
    """Consume one wake event: deliberate, then mark the event processed.

    Deliberately *not* run inside `events.process_event`'s handler transaction
    — see the module docstring. The deliberation happens first and is
    idempotent on a wake key derived from the event id, so a crash before the
    event is marked processed results in a redelivery that finds the existing
    deliberation and simply completes the bookkeeping.
    """
    if event.event_type != WAKE_EVENT_TYPE:
        raise DeliberationError(
            f"not a wake event: {event.event_type!r} (expected {WAKE_EVENT_TYPE!r})"
        )
    payload = event.payload or {}
    cell_id = payload.get("cell_id") or event.target
    if not cell_id:
        raise DeliberationError(f"wake event {event.event_id} names no cell")

    result = deliberate(
        conn,
        cell_id=cell_id,
        provider=provider,
        wake_key=f"event:{event.event_id}",
        wake_reason=payload.get("wake_reason", WAKE_SCHEDULED_RESEARCH),
        model=model,
        context_budget_tokens=context_budget_tokens,
        max_tokens=max_tokens,
        proposal_sink=proposal_sink,
    )

    events.process_event(conn, event.event_id, lambda _conn, _event: [], cell_id=cell_id)
    return result


def run_ready_wakes(
    conn: sqlite3.Connection,
    *,
    provider: providers.ModelProvider,
    model: str,
    now: datetime | None = None,
    limit: int | None = None,
    context_budget_tokens: int = context.DEFAULT_CONTEXT_TOKEN_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    proposal_sink: ProposalSink | None = None,
) -> list[Deliberation]:
    """Drain ready wake events in Amendment A5's deterministic order.

    Non-wake events are left alone: this drains the wake queue, it is not a
    general event pump, and silently processing someone else's event type
    would make the two indistinguishable in the record.
    """
    ready = events.next_ready(conn, now=now or datetime.now(timezone.utc), limit=limit)
    results = []
    for event in ready:
        if event.event_type != WAKE_EVENT_TYPE:
            continue
        results.append(
            run_wake_event(
                conn,
                event,
                provider=provider,
                model=model,
                context_budget_tokens=context_budget_tokens,
                max_tokens=max_tokens,
                proposal_sink=proposal_sink,
            )
        )
    return results
