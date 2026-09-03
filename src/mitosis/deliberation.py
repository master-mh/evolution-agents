"""The agent loop: a Cell that acts (SPEC.md §17.2, §15, §0.3, §25.1; Charter C6, C8, C15).

Everything built before this is machinery *for* a Cell. This is the Cell.

One wake is: assemble bounded context (§15) → one gateway call → parse a
strict structured proposal → record it, with any predictions registered before
their outcomes (§8.5). Then the Cell sleeps.

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
  genome field selects a code path. Charter C15 holds only while genomes are
  inert data; the sandbox that would make executable genomes survivable (C12)
  is Phase 5.
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
import sqlite3
from dataclasses import dataclass
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


class DeliberationError(Exception):
    pass


class DeliberationStatus:
    PROPOSED = "proposed"
    UNPARSEABLE = "unparseable"
    REFUSED = "refused"


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
    status: str
    failure_reason: str | None
    context_tokens: int
    proposal_id: str | None
    prediction_ids: tuple[str, ...]
    created_at_utc: datetime


def _system_prompt() -> str:
    """The instruction half of the prompt. Fixed kernel text, never genome
    content — a genome that could rewrite these instructions would be a Cell
    editing the constitution it is judged against."""
    return (
        "You are a Cell in the MITOSIS colony: an autonomous economic agent under "
        "an immutable kernel you cannot modify.\n\n"
        "You are being woken to deliberate. You cannot take any action. Your only "
        "output is a single proposal, which is recorded and read by the operator. "
        "Nothing you propose is executed automatically.\n\n"
        "Reply with ONE JSON object and nothing else — no prose before or after. "
        "It must match this schema exactly. Every REQUIRED field must be present, "
        "and unknown fields are rejected:\n\n"
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
    """
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

    # The gateway call commits its own reservation before the external call
    # (ADR-022), so it happens outside every transaction this module opens.
    call = gateway.call_model(
        conn,
        cell_id=cell.cell_id,
        provider=provider,
        request=providers.ModelRequest(
            model=model,
            messages=(
                {"role": "user", "content": f"{_system_prompt()}\n\n{assembled.render()}"},
            ),
            max_tokens=max_tokens,
            # §14.1's sampling-temperature mutation operator, read from this
            # Cell's own genome rather than pinned as a kernel constant
            # (ADR-050, ADR-067). `None` when the genome declares no policy —
            # the provider's own default, not a kernel opinion.
            temperature=genome.temperature_of(canonical_genome),
        ),
        experiment_id=experiment_id,
        idempotency_key=f"deliberation:{wake_key}",
    )

    reply = call.response_text or ""
    try:
        parsed = proposal_module.parse(reply)
    except proposal_module.ProposalError as exc:
        return _record_unparseable(
            conn,
            cell=cell,
            wake_key=wake_key,
            wake_reason=wake_reason,
            assembled=assembled,
            model_call_id=call.model_call_id,
            reason=str(exc),
        )

    return _record_proposal(
        conn,
        cell=cell,
        wake_key=wake_key,
        wake_reason=wake_reason,
        assembled=assembled,
        model_call_id=call.model_call_id,
        parsed=parsed,
        # Carried rather than re-derived, so the call and the forecasts it
        # produced cannot land on two different experiments.
        experiment_id=experiment_id,
        proposal_sink=proposal_sink,
    )


def _insert_deliberation_locked(
    conn: sqlite3.Connection,
    *,
    cell: Cell,
    wake_key: str,
    wake_reason: str,
    assembled: context.AssembledContext | None,
    model_call_id: str | None,
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
            model_call_id, context_json, context_tokens, context_dropped_json,
            status, failure_reason, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            deliberation_id,
            cell.cell_id,
            wake_key,
            wake_reason,
            cell.genome_hash,
            model_call_id,
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
    reason: str,
) -> Deliberation:
    """A reply that did not validate.

    The Cell still paid for the call — the tokens were burned whatever came
    back — so this is recorded rather than rolled back. The raw reply is not
    stored: it is untrusted content (§19.4), and a prose blob sitting in the
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
            status=DeliberationStatus.UNPARSEABLE,
            failure_reason=reason,
        )
        audit.record(
            conn,
            event_type="cell_deliberation_unparseable",
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
    parsed: proposal_module.Proposal,
    experiment_id: str | None,
    proposal_sink: ProposalSink | None,
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
                parsed.risk_tier.value,
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
                "risk_tier": parsed.risk_tier.value,
                "predictions": len(parsed.predictions),
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
