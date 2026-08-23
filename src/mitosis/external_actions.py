"""The external-action registry: what the colony did outside itself, and what it
therefore may not do next (SPEC.md §21, §23.4, §16.3, §19.3, §28 Phase 8/9, §31;
Amendment A11; ADR-036).

A Cell could think, be funded, read the world, and produce a deliverable. What
it could not do was put that deliverable in front of anyone — `artifacts.export`
records that a human took something outside the colony and there is no channel
behind it. This is that channel's registry, and the emphasis matters:

**This module builds the registry, not a sender. Nothing here transmits.** §28's
Phase 8 acceptance is "all external action remains manual", and §21.2's own two
verbs are *track* and *prevent*. A person performs the action; the kernel
records what was done, meters what it cost in human time, and refuses what would
collide with what a sibling is already doing. That refusal is Phase 9's
acceptance criterion — "no duplicate or conflicting customer contact" — built a
phase early, because a guarantee that arrives with the first real customer has
never been tested against anything.

The shape of one external action, in order:

    1. CLAIM       validate the grant, gate on §27.1, run §21.2's collision
                   checks, reserve the human minutes, write 'claimed'  — one
                   transaction, committed before anyone touches the world
    2. (a person does the thing)
    3. COMPLETE    record the outcome and the minutes actually spent, meter
                   HUMAN_MINUTES, settle, freeze the channel if it went badly,
                   wake the Cell — one transaction
       or ABANDON  release the reservation, say why

**Claim-before-act is what makes "prevent" mean anything.** Recording an action
after the fact turns every collision into a post-mortem: the second email is
already sent by the time the kernel can object. So the registry row is written
first, and it holds the counterparty and the channel against every other Cell
while a person does the work. The cost is that an abandoned claim blocks its
counterparty until it is abandoned explicitly — which is the right way round,
since a pending send is still a pending send.

**The counterparty is supplied by the operator, never by the Cell.** A Cell
proposes a channel and an intent; a person decides who. Three reasons, and the
third is the one that surprised me:

1. §16.3 makes customer identity non-inheritable, and a proposal is inherited
   context — a counterparty named in `payload_json` is a personal identifier
   sitting in the Cell's own history, in every later §15 context, and in the
   coroner report when it dies.
2. The only way a Cell could *learn* a real address today is from a fetched
   page, which is `UNTRUSTED_EXTERNAL` and very often personal data. A Cell
   naming a counterparty is therefore itself the finding, not the feature.
3. It relocates §23.4's aggregation. ADR-027 keyed the approval window on the
   lineage as an explicit stand-in "until counterparty/domain/channel exist".
   They exist now — but the counterparty does not exist *at approval time*, so
   the approval queue keys on the **channel** and the counterparty aggregation
   lives here, at claim time, which is the first moment the dimension is real.
   Two keys at the two points where each is knowable, rather than one key
   pretending to know both.

**Human minutes are metered against the Cell's RESOURCE budget** (§2.2's
`human_minutes`, declared since Phase 1 and consumed by nothing until now). §1
says autonomy-adjusted profit exists "to expose hidden human labour and
subsidy", and `outcome.py` counts intervention *events* but has never counted
time. A Cell that can only act by consuming a person's attention now runs out of
budget for doing so, and Phase 8's North Star — "human minutes/artifact" —
becomes computable rather than aspirational.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import (
    approval,
    artifacts,
    audit,
    channel_registry,
    deliberation,
    ids,
    lifecycle,
    reservations,
    resource_metering,
)
from .channel_registry import (
    DAMAGE_OUTCOMES,
    HUMAN_MINUTE_RESOURCE_COST,
    INFRASTRUCTURE_RESERVE,
    LADDER_RUNG_HUMAN_REVIEWED_PROTOTYPE,
    MAX_HUMAN_MINUTES_PER_ACTION,
    OUTCOMES,
    RESERVATION_TTL,
    ChannelError,
    ChannelSpec,
    ExternalActionRefused,
    check_action,
    get_spec,
)
from .models import Book, CellStatus, ResourceType
from .proposal import ProposalKind

#: Charter C8 / §18.2. Mirrors `tool_registry._CAN_RECEIVE_TOOL_RESULT` — a Cell
#: waiting on a person is the ordinary case for a dormant one.
_CAN_ACT_EXTERNALLY = frozenset({CellStatus.ALIVE, CellStatus.DORMANT})

__all__ = [
    "ExternalAction",
    "ExternalActionError",
    "ExternalActionRefused",
    "abandon",
    "claim",
    "complete",
    "get",
]


class ExternalActionError(ChannelError):
    pass


@dataclass(frozen=True)
class ExternalAction:
    action_id: str
    grant_id: str
    proposal_id: str
    cell_id: str
    founder_cell_id: str
    channel: str
    intent: str
    artifact_id: str | None
    domain: str | None
    platform_account: str | None
    status: str
    claimed_at_utc: datetime
    claimed_by: str
    completed_at_utc: datetime | None
    outcome: str | None
    reference: str | None
    human_minutes: int | None
    resource_reservation_id: str | None


def external_action_of(proposal_row: sqlite3.Row) -> dict:
    """The frozen (channel, intent, artifact) an approved proposal asked for.

    Read from `payload_json` — the proposal exactly as parsed and recorded —
    never from anything the Cell can touch afterwards. Same asymmetry
    `tools.tool_request_of` and `promotion.py` apply: what happens is what the
    operator was shown at §23.2.
    """
    payload = json.loads(proposal_row["payload_json"])
    request = payload.get("external_action")
    if not isinstance(request, dict):
        raise ExternalActionError(
            f"proposal {proposal_row['proposal_id']} is an external_action but carries "
            "no external_action payload"
        )
    channel = request.get("channel")
    intent = request.get("intent")
    if not isinstance(channel, str) or not isinstance(intent, str):
        raise ExternalActionError(
            f"proposal {proposal_row['proposal_id']} has a malformed external_action"
        )
    return request


# --- 1. claim -----------------------------------------------------------------


def claim(
    conn: sqlite3.Connection,
    *,
    grant_id: str,
    claimed_by: str,
    counterparty: str | None = None,
    domain: str | None = None,
    platform_account: str | None = None,
    now: datetime | None = None,
) -> ExternalAction:
    """Reserve the right to take one external action, before taking it.

    One transaction, unlike `tools.execute_grant`'s three. There is no external
    call to keep outside a lock here — that is the whole design — so the grant,
    the collision checks, the RESOURCE reservation and the registry row all
    commit together or not at all. A partially-applied claim would either hold a
    counterparty with no reservation behind it or bill for a claim nobody holds.

    Returns the row a person then acts on by hand. **Nothing has been sent.**
    """
    now = now or datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        action = _claim_locked(
            conn,
            grant_id=grant_id,
            claimed_by=claimed_by,
            counterparty=counterparty,
            domain=domain,
            platform_account=platform_account,
            now=now,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return action


def _claim_locked(
    conn: sqlite3.Connection,
    *,
    grant_id: str,
    claimed_by: str,
    counterparty: str | None,
    domain: str | None,
    platform_account: str | None,
    now: datetime,
) -> ExternalAction:
    """Caller holds the write lock. Every check runs inside it.

    Check-then-lock would mean two lineages each seeing an empty table and each
    concluding they were first — which is precisely the duplicate contact §21.2
    exists to prevent, arrived at by way of the check meant to prevent it.
    """
    grant = approval.get_grant(conn, grant_id)
    if grant is None:
        raise ExternalActionError(f"no such grant: {grant_id}")
    if grant.consumed_at_utc is not None:
        raise ExternalActionError(
            f"grant {grant_id} was already consumed at "
            f"{grant.consumed_at_utc.isoformat()} — a grant authorises one action"
        )
    if now >= grant.expires_at_utc:
        # §23.3 forbids acting on stale terms: an offer authorised against
        # last week's market is a different offer. `approval.expire_grants_due`
        # regenerates it — as a wake, never as a fresh grant — so the Cell asks
        # again and a person decides again.
        raise ExternalActionError(
            f"grant {grant_id} expired at {grant.expires_at_utc.isoformat()} — §23.3 "
            "forbids acting on stale terms. Run `mitosis expire-approvals` to "
            "regenerate it: the Cell proposes again and is approved afresh."
        )

    request = approval.get_request(conn, grant.request_id)
    if request is None or request.status != approval.RequestStatus.APPROVED:
        raise ExternalActionError(f"grant {grant_id} does not correspond to an approved request")

    proposal = conn.execute(
        "SELECT * FROM proposals WHERE proposal_id = ?", (grant.proposal_id,)
    ).fetchone()
    if proposal is None:
        raise ExternalActionError(f"grant {grant_id} names a missing proposal")

    kind = ProposalKind(proposal["kind"])
    if kind is not ProposalKind.EXTERNAL_ACTION:
        # Approving an experiment is a human saying "yes, go think about that".
        # Reading it as permission to contact a customer would let a Cell obtain
        # the colony's scarcest capability by proposing something else.
        raise ExternalActionError(
            f"grant {grant_id} is for a {kind.value} proposal; only an external_action "
            "claims a channel"
        )

    payload = external_action_of(proposal)
    channel = payload["channel"]
    intent = payload["intent"]
    artifact_id = payload.get("artifact_id") or None
    spec = get_spec(channel)

    cell = lifecycle.get_cell(conn, grant.cell_id)
    if cell is None:
        raise ExternalActionError(f"grant {grant_id} names an unknown cell")
    if cell.status not in _CAN_ACT_EXTERNALLY:
        # Charter C8: a dead Cell does not act, and a quarantined one is under
        # §18.2 restriction. Acting on behalf of either would spend the colony's
        # shared reputation for a Cell that cannot answer for it.
        raise ExternalActionError(
            f"cell {cell.cell_id} is {cell.status.value} and cannot take an external action"
        )

    # §21.2 and §27.1, inside the lock. Identical to what `check_action` offers
    # an operator beforehand — the same function, not a second copy of it.
    check_action(
        conn,
        channel=channel,
        counterparty=counterparty,
        domain=domain,
        platform_account=platform_account,
        artifact_id=artifact_id,
        founder_cell_id=cell.founder_cell_id,
        now=now,
    )

    # §19.3's export gateway decides *whether* an artifact may leave the colony;
    # this decides to whom. Requiring the export first rather than re-deriving
    # the decision keeps Charter C13 and §20.2 in one place, and means delivery
    # cannot become a second, laxer way out of the colony.
    if artifact_id is not None:
        artifact = artifacts.get(conn, artifact_id)
        if artifact is None:
            raise ExternalActionError(f"external action names a missing artifact: {artifact_id}")
        if artifact.created_by_cell_id != cell.cell_id:
            raise ExternalActionError(
                f"artifact {artifact_id} was made by {artifact.created_by_cell_id}, not "
                f"{cell.cell_id} — §11.2 puts usefulness downstream, and delivering "
                "another Cell's work is not this path's decision to make"
            )
        if not artifact.is_exported:
            raise ExternalActionError(
                f"artifact {artifact_id} has not been exported. §19.3's export gateway "
                "is what decides an artifact may leave the colony at all; a channel "
                "decides only where it goes."
            )

    digest = (
        channel_registry.counterparty_hash(conn, counterparty)
        if counterparty is not None
        else None
    )

    # Stored in the form §21.2 aggregates on, never as typed. `check_action`
    # above compared the normalised value; writing the raw one would leave every
    # later query looking for a string this row does not contain.
    domain = channel_registry.normalise_target(domain)
    platform_account = channel_registry.normalise_target(platform_account)

    conn.execute(
        "UPDATE approval_grants SET consumed_at_utc = ? WHERE grant_id = ?",
        (now.isoformat(), grant_id),
    )

    action_id = ids.new_id()
    reservation = reservations._request_locked(
        conn,
        cell_id=cell.cell_id,
        book=Book.RESOURCE,
        currency="RESOURCE",
        maximum_amount=spec.max_billable_human_minutes * HUMAN_MINUTE_RESOURCE_COST,
        expires_at=now + RESERVATION_TTL,
        idempotency_key=f"external_action_resource:{action_id}",
        external_operation_type="external_action",
        external_operation_id=action_id,
    )

    conn.execute(
        """
        INSERT INTO external_action_registry (
            action_id, grant_id, proposal_id, cell_id, founder_cell_id, channel,
            counterparty_hash, domain, platform_account, intent, artifact_id,
            status, idempotency_key, claimed_at_utc, claimed_by,
            resource_reservation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'claimed', ?, ?, ?, ?)
        """,
        (
            action_id,
            grant_id,
            grant.proposal_id,
            cell.cell_id,
            cell.founder_cell_id,
            channel,
            digest,
            domain,
            platform_account,
            intent,
            artifact_id,
            f"external_action:{grant_id}",
            now.isoformat(),
            claimed_by,
            reservation.reservation_id,
        ),
    )

    # **No counterparty, hashed or otherwise, in the audit trail.** The registry
    # holds the hash because equality is what the collision checks need; the
    # audit log needs none of it, and a stable per-person token scattered through
    # a log that everything reads is how a carefully un-stored identity gets
    # reconstructed by correlation.
    audit.record(
        conn,
        event_type="external_action_claimed",
        cell_id=cell.cell_id,
        description=f"{channel}: {intent}",
        metadata={
            "action_id": action_id,
            "grant_id": grant_id,
            "channel": channel,
            "claimed_by": claimed_by,
            "addressed": digest is not None,
            "artifact_id": artifact_id,
            "ladder_rung": LADDER_RUNG_HUMAN_REVIEWED_PROTOTYPE,
        },
    )

    return _row_to_action(_read_row(conn, action_id))


# --- 2. complete / abandon ----------------------------------------------------


def complete(
    conn: sqlite3.Connection,
    *,
    action_id: str,
    completed_by: str,
    outcome: str,
    human_minutes: int,
    reference: str | None = None,
    now: datetime | None = None,
) -> ExternalAction:
    """Record what a person actually did, and what it cost in their time.

    One transaction: a crash leaving any subset applied would mean either
    metered minutes against an action that still reads as unfinished, or a
    completed action whose reservation is never settled.

    `human_minutes` must be at least 1. §28 Phase 8's acceptance is that "human
    labour is measured", and a completion claiming zero minutes is either untrue
    or a report that something was automated — which is the one thing this phase
    says does not happen. Refusing is how the claim stays worth reading.
    """
    now = now or datetime.now(timezone.utc)

    if outcome not in OUTCOMES:
        raise ExternalActionError(
            f"unknown outcome {outcome!r}. One of: {', '.join(sorted(OUTCOMES))}"
        )
    if human_minutes < 1:
        raise ExternalActionError(
            "an external action costs at least one human minute — §28's Phase 8 "
            "measures human labour, and nothing on this path is automated"
        )
    if human_minutes > MAX_HUMAN_MINUTES_PER_ACTION:
        # A sanity bound on the reported figure, not an economic one — the
        # economic bound is the channel's `max_billable_human_minutes`, and
        # exceeding *that* is recorded as subsidy rather than refused. This
        # catches a mistyped 9999 before it becomes a fact about the colony.
        raise ExternalActionError(
            f"{human_minutes} minutes is beyond the {MAX_HUMAN_MINUTES_PER_ACTION}-minute "
            "sanity bound on a single action. Something that took longer than a working "
            "day is two actions."
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _read_row(conn, action_id)
        if row["status"] != "claimed":
            raise ExternalActionError(
                f"action {action_id} is {row['status']}, not claimed — there is nothing "
                "left to complete"
            )

        # **The Cell pays up to the channel's ceiling; the record holds the
        # truth; the difference is subsidy.** Refusing an over-ceiling
        # completion was the obvious alternative and is worse: the minutes were
        # already spent, so refusing to record them does not un-spend them, it
        # only makes the colony's account of its own human cost quieter than the
        # reality. §1 wants "hidden human labour and subsidy" *exposed*, and a
        # gap between what a person gave and what a Cell could pay for is
        # exactly that quantity — so it is recorded rather than prevented.
        spec = get_spec(row["channel"])
        billable = min(human_minutes, spec.max_billable_human_minutes)
        subsidised = human_minutes - billable

        resource_metering._record_usage_locked(
            conn,
            cell_id=row["cell_id"],
            reservation_id=row["resource_reservation_id"],
            resource_type=ResourceType.HUMAN_MINUTES,
            quantity=billable,
            minor_units=billable * HUMAN_MINUTE_RESOURCE_COST,
            idempotency_key=f"external_action_usage:{action_id}",
            metadata={
                "channel": row["channel"],
                "action_id": action_id,
                "reported_human_minutes": human_minutes,
                "subsidised_human_minutes": subsidised,
            },
        )

        # Settle what was billed, then release the rest. The claim-time ceiling
        # is an upper bound a claim cannot know the outcome of, so unlike a tool
        # call this is almost always a *partial* settlement — and
        # `partially_settled` leaves the remainder committed until something
        # releases it. The gateway does the same two steps for the same reason;
        # skipping the second would strand most of a Cell's RESOURCE budget on
        # every action it ever takes.
        reservation = reservations.get_reservation(conn, row["resource_reservation_id"])
        settled = resource_metering.total_minor_units(conn, row["resource_reservation_id"])
        reservations._settle_locked(
            conn,
            row["resource_reservation_id"],
            settled_amount=settled,
            destination_account_id=INFRASTRUCTURE_RESERVE,
        )
        if settled < reservation.maximum_amount:
            reservations._release_locked(conn, row["resource_reservation_id"])

        conn.execute(
            """
            UPDATE external_action_registry SET
                status = 'completed', completed_at_utc = ?, completed_by = ?,
                outcome = ?, reference = ?, human_minutes = ?
            WHERE action_id = ?
            """,
            (now.isoformat(), completed_by, outcome, reference, human_minutes, action_id),
        )

        if subsidised > 0:
            # A distinct event rather than a field on the completion, because
            # this is a fact about the *colony* — it absorbed labour a Cell's
            # budget could not carry — and `outcome.py` reads audit events when
            # it assembles §25.2's human-intervention picture.
            audit.record(
                conn,
                event_type="human_minutes_subsidised",
                cell_id=row["cell_id"],
                description=(
                    f"{subsidised} of {human_minutes} human minutes on "
                    f"{row['channel']} were beyond what the Cell pays for"
                ),
                metadata={
                    "action_id": action_id,
                    "channel": row["channel"],
                    "reported_human_minutes": human_minutes,
                    "billed_human_minutes": billable,
                    "subsidised_human_minutes": subsidised,
                },
            )

        if outcome in DAMAGE_OUTCOMES:
            _record_damage_locked(conn, row=row, outcome=outcome, now=now)

        # §17.2. The Cell is told what came of the action it proposed. This is
        # the feedback the whole path exists for — without it a Cell proposes
        # outreach forever and never learns that nobody replied.
        deliberation._enqueue_wake_locked(
            conn,
            cell_id=row["cell_id"],
            wake_reason=deliberation.WAKE_EXTERNAL_ACTION_RESULT,
            dedupe_key=f"external_action_result:{action_id}",
        )

        audit.record(
            conn,
            event_type="external_action_completed",
            cell_id=row["cell_id"],
            description=f"{row['channel']} {outcome} ({human_minutes} human minutes)",
            metadata={
                "action_id": action_id,
                "channel": row["channel"],
                "outcome": outcome,
                "human_minutes": human_minutes,
                "billed_human_minutes": billable,
                "completed_by": completed_by,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return _row_to_action(_read_row(conn, action_id))


def _record_damage_locked(
    conn: sqlite3.Connection, *, row: sqlite3.Row, outcome: str, now: datetime
) -> None:
    """§21.1: the shared asset took a hit. Two consequences, both automatic.

    Freezing the channel is the §23.3 metabolic-alarm shape applied to
    reputation rather than to spend: it halts, and only a person with a stated
    reason restarts it. The colony must not be able to discover that complaints
    are survivable at a rate it chooses for itself.

    Blocking the counterparty is the design's own justification. "Never contact
    this person again" is answerable from a table of hashes, so the colony
    honours the request permanently **without ever holding a list of the people
    who made one** — which a `customers` table with an opt-out flag could not do.
    """
    channel_registry._freeze_channel_locked(
        conn,
        channel=row["channel"],
        reason=f"{outcome} recorded on action {row['action_id']}",
        action_id=row["action_id"],
        now=now,
    )
    if row["counterparty_hash"] is not None:
        conn.execute(
            "INSERT OR IGNORE INTO counterparty_blocks "
            "(counterparty_hash, blocked_at_utc, reason, source_action_id) "
            "VALUES (?, ?, ?, ?)",
            (row["counterparty_hash"], now.isoformat(), outcome, row["action_id"]),
        )
    audit.record(
        conn,
        event_type="channel_frozen",
        cell_id=row["cell_id"],
        description=f"{row['channel']} frozen after {outcome}",
        metadata={
            "channel": row["channel"],
            "outcome": outcome,
            "action_id": row["action_id"],
            "counterparty_blocked": row["counterparty_hash"] is not None,
        },
    )


def abandon(
    conn: sqlite3.Connection,
    *,
    action_id: str,
    abandoned_by: str,
    reason: str,
    now: datetime | None = None,
) -> ExternalAction:
    """Give up a claim without having acted on it.

    Releases the reservation and frees the counterparty and the channel slot.
    **The grant is not restored** — claiming was a real act that took a slot
    another lineage could have used, and handing it back would make a claim a
    free way to reconnoitre who has already been contacted.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ExternalActionError("abandoning a claim must state why")
    now = now or datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _read_row(conn, action_id)
        if row["status"] != "claimed":
            raise ExternalActionError(f"action {action_id} is {row['status']}, not claimed")
        if row["resource_reservation_id"] is not None:
            reservations._release_locked(conn, row["resource_reservation_id"])
        conn.execute(
            "UPDATE external_action_registry SET status = 'abandoned', "
            "abandoned_at_utc = ?, abandon_reason = ? WHERE action_id = ?",
            (now.isoformat(), reason, action_id),
        )
        audit.record(
            conn,
            event_type="external_action_abandoned",
            cell_id=row["cell_id"],
            description=f"{row['channel']} abandoned: {reason}",
            metadata={
                "action_id": action_id,
                "channel": row["channel"],
                "abandoned_by": abandoned_by,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return _row_to_action(_read_row(conn, action_id))


# --- reads --------------------------------------------------------------------


def get(conn: sqlite3.Connection, action_id: str) -> ExternalAction | None:
    row = conn.execute(
        "SELECT * FROM external_action_registry WHERE action_id = ?", (action_id,)
    ).fetchone()
    return _row_to_action(row) if row is not None else None


def _read_row(conn: sqlite3.Connection, action_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM external_action_registry WHERE action_id = ?", (action_id,)
    ).fetchone()
    if row is None:
        raise ExternalActionError(f"no such external action: {action_id}")
    return row


def _row_to_action(row: sqlite3.Row) -> ExternalAction:
    return ExternalAction(
        action_id=row["action_id"],
        grant_id=row["grant_id"],
        proposal_id=row["proposal_id"],
        cell_id=row["cell_id"],
        founder_cell_id=row["founder_cell_id"],
        channel=row["channel"],
        intent=row["intent"],
        artifact_id=row["artifact_id"],
        domain=row["domain"],
        platform_account=row["platform_account"],
        status=row["status"],
        claimed_at_utc=datetime.fromisoformat(row["claimed_at_utc"]),
        claimed_by=row["claimed_by"],
        completed_at_utc=(
            datetime.fromisoformat(row["completed_at_utc"])
            if row["completed_at_utc"]
            else None
        ),
        outcome=row["outcome"],
        reference=row["reference"],
        human_minutes=row["human_minutes"],
        resource_reservation_id=row["resource_reservation_id"],
    )
