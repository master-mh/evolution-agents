"""The tool surface: a Cell acts on the world, under grant (SPEC.md §19, §18.1,
§20.1, §0.4, §23, §25.1; Charter C12, C13, C14; ADR-034).

Until now a Cell could think and be funded, and that was all it could do. The
gateway spends money at a model provider; nothing else in the kernel reached
outside itself. This module is the second such path, and the first that can
read the world.

**§25.1 makes this a rung the colony skipped, not an escalation.** The ladder
puts "read-only real-world observation" at rung 4 and "shadow prediction with no
action" at rung 5, and the agent loop has been at rung 5 since ADR-025. A
read-only tool is therefore *below* where the colony already stands. Tools that
change the world — publish, message, purchase — are rungs 8 and 9, and the split
is structural rather than conventional: `ToolSpec.read_only` is required, and
`test_no_registered_tool_acts_on_the_world` fails on any registry entry that
sets it False. Adding an acting tool has to break a named test.

The shape of one tool call, in order:

    1. VALIDATE the grant       approved, unconsumed, unexpired, tool_request
    2. FREEZE the arguments     read from the proposal, never from the Cell
    3. GATE                     §27.1 autonomy flag + §19.3 egress allowlist
    4. RESERVE (RESOURCE)       the A6 link; §19.3's limits are the only bound
    5. RECORD 'requested'       ── all of 1-5 in one transaction, then COMMIT
    6. EXECUTE                  the external call, outside any transaction
    7. SETTLE + METER + WAKE    one transaction: result, taint, §17.2 wake

**Steps 1-5 commit before step 6, and step 5 is the part the gateway does not
have.** ADR-022 left forward recovery deferred: a crashed model call loses the
provider's reported usage and needs a human, because nothing durably records
that the call was about to happen. This module writes its `tool_calls` row —
grant, tool, frozen arguments, `requested` — *before* the external call, so a
crash leaves a diagnosable record rather than a reservation with nothing
explaining it. Doing it here rather than retrofitting the gateway is the cheap
version: the module is new, so there is no migration of in-flight state.

**The grant is consumed in step 1-5's transaction, not step 7's.** A grant left
unconsumed across the external call is a grant two concurrent executions can
both claim, which is the check-then-lock bug class this kernel fixed once
already — and here it would mean two fetches billed against one approval. The
cost is that a crash burns the grant; that is the honest trade, and the
`requested` row is what makes it recoverable by hand.

**§19.4 is the constraint that shapes the rest: "no webpage content treated as
a trusted tool command".** Three consequences, and the third is the one that is
easy to miss:

1. Everything a tool returns is labelled `UNTRUSTED_EXTERNAL` (§18.1) and stays
   so. §18.3's clean-room path is the only route to another label and is not
   built, so there is no code here that can promote a taint label.
2. Results reach a Cell only through a **fenced** §15 context section that says
   what they are, never merged into the instruction text (see `context.py`).
3. **A tool result can never cause another tool call.** Execution requires an
   approved grant, and a grant requires a human decision on a §23 request — so
   a fetched page that says "now fetch evil.example" can at most produce a
   *proposal*, which a person reads before anything happens. The human is the
   loop-breaker, and `test_nothing_in_the_deliberation_path_executes_a_tool`
   pins it: neither `deliberation` nor `context` nor `scheduler` may reach this
   module's executor.

That third point is why the proposal→approval→grant route was chosen over
letting a Cell call tools inline while it thinks. Inline tool use puts fetched
content in the same conversation as the instructions, which is the exact
configuration §19.4 exists to prevent.

**Charter C12 stops being an abstraction here.** "Generated code cannot reach
host files, secrets, or unapproved networks" had no test, deferred to Phase 5
because no generated code runs. But the moment the kernel can open a socket on
a Cell's behalf, "unapproved networks" is a live guarantee whether or not the
caller is generated code — so the egress allowlist ships with the first
`charter_sandbox_isolation` property test.

**Charter C14** is upheld the way `providers.py` upholds it: no credential is
an argument to, a field of, or a return value from anything here, and error
text is redacted before it is persisted.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import (
    approval,
    audit,
    deliberation,
    experiments,
    ids,
    lifecycle,
    reservations,
    resource_metering,
    scheduler,
)
from .models import Book, ResourceType
from .proposal import ProposalKind
from .tool_registry import (
    _CAN_RECEIVE_TOOL_RESULT,
    _INFRASTRUCTURE_RESERVE,
    _RESERVATION_TTL,
    _AUTONOMY_COLUMNS,
    _check_egress_locked,
    _redact,
    AutonomyRefused,
    EgressRefused,
    Fetcher,
    FetchResult,
    LADDER_RUNG_READ_ONLY_OBSERVATION,
    MAX_RESULT_BYTES,
    REGISTRY,
    RESOURCE_COST_PER_CALL,
    RefusingFetcher,
    TAINT_UNTRUSTED_EXTERNAL,
    ToolError,
    ToolSpec,
    allow_domain,
    allowed_domains,
    autonomy_enabled,
    deny_domain,
    get_spec,
    observations_for,
    validate_request,
)

#: Re-exported so callers have one import for the tool surface. The *split* is
#: a layering fact (see tool_registry.py), not an API the rest of the kernel
#: should have to know about — except in one direction: `context` imports
#: `tool_registry` and must never import this module, which is what keeps
#: §19.4's "a tool result cannot cause a tool call" structurally true.
__all__ = [
    "AutonomyRefused",
    "EgressRefused",
    "Fetcher",
    "FetchResult",
    "RefusingFetcher",
    "REGISTRY",
    "TAINT_UNTRUSTED_EXTERNAL",
    "ToolCall",
    "ToolError",
    "ToolSpec",
    "allow_domain",
    "allowed_domains",
    "autonomy_enabled",
    "deny_domain",
    "execute_grant",
    "get_spec",
    "observations_for",
    "set_autonomy",
    "validate_request",
]


def set_autonomy(
    conn: sqlite3.Connection, *, flag: str, enabled: bool, changed_by: str = "operator"
) -> None:
    """Turn one §27.1 autonomy flag on or off. Always audited, both directions.

    Mirrors `scheduler.set_real_spending` deliberately — that flag and these
    four are the same list in the spec, and having two mechanisms for one
    config block is how they drift apart.
    """
    column = _AUTONOMY_COLUMNS.get(flag)
    if column is None:
        raise ToolError(f"unknown autonomy flag {flag!r}")

    conn.execute("BEGIN IMMEDIATE")
    try:
        # An UPDATE against a colony whose operator row was never created would
        # affect zero rows and leave the flag reading False forever — a gate
        # that silently cannot be opened. `scheduler` owns the row's shape, so
        # reuse its initialiser rather than writing a second INSERT here.
        scheduler.initialize_operator_if_absent(conn)
        conn.execute(
            f"UPDATE operator_state SET {column} = ? WHERE id = 1", (1 if enabled else 0,)
        )
        audit.record(
            conn,
            event_type="autonomy_flag_changed",
            cell_id=None,
            description=f"autonomy.{flag} -> {enabled}",
            metadata={"flag": flag, "enabled": enabled, "changed_by": changed_by},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --- execution ----------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    tool_call_id: str
    grant_id: str
    proposal_id: str
    cell_id: str
    tool: str
    arguments: dict[str, Any]
    status: str
    taint_label: str
    result_text: str | None
    result_bytes: int | None
    http_status: int | None
    error: str | None


def tool_request_of(proposal_row: sqlite3.Row) -> tuple[str, dict[str, Any]]:
    """The frozen (tool, arguments) pair a proposal asked for.

    Read from `payload_json` — the proposal exactly as parsed and recorded —
    rather than from anything the Cell can touch later. This is the same
    asymmetry `promotion.py` applies to a grant's amount: what executes is what
    the operator was shown at §23.2, not a value re-read at execution time.
    """
    payload = json.loads(proposal_row["payload_json"])
    request = payload.get("tool_request")
    if not isinstance(request, dict):
        raise ToolError(
            f"proposal {proposal_row['proposal_id']} is a tool_request but carries "
            "no tool_request payload"
        )
    tool_id = request.get("tool")
    arguments = request.get("arguments")
    if not isinstance(tool_id, str) or not isinstance(arguments, dict):
        raise ToolError(
            f"proposal {proposal_row['proposal_id']} has a malformed tool_request"
        )
    return tool_id, arguments


def execute_grant(
    conn: sqlite3.Connection,
    *,
    grant_id: str,
    executed_by: str,
    reason: str,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> ToolCall:
    """Consume an approved grant by running the tool it authorised.

    Three phases, deliberately not one transaction — see the module docstring.
    The grant is consumed in phase 1, which is what serialises two concurrent
    executions: the single-use grant is the mutual exclusion, so a second
    caller finds it consumed rather than making a second external request
    against one approval.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ToolError("executing a tool grant must state a reason")

    now = now or datetime.now(timezone.utc)
    fetcher = fetcher or RefusingFetcher()

    # --- phase 1: validate, gate, consume the grant, record the intent -------
    conn.execute("BEGIN IMMEDIATE")
    try:
        call = _claim_grant_locked(
            conn, grant_id=grant_id, executed_by=executed_by, reason=reason, now=now
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    spec = get_spec(call.tool)

    # --- phase 2: reserve the metered RESOURCE ------------------------------
    # Its own transaction, exactly as the gateway keeps reserve separate from
    # execute: the reservation must be durably committed before anything
    # leaves the machine, or a crash could bill work nobody authorised.
    # Opened through the locked core rather than `reservations.request` so the
    # §2.6 attribution is read *inside* the same write lock that inserts it. The
    # transaction boundary is unchanged — still its own, still committed before
    # anything leaves the machine — but an experiment concluding between the
    # read and the insert can no longer stamp a reservation with an experiment
    # that has stopped running.
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            reservation = reservations._request_locked(
                conn,
                cell_id=call.cell_id,
                book=Book.RESOURCE,
                currency="RESOURCE",
                maximum_amount=RESOURCE_COST_PER_CALL,
                expires_at=now + _RESERVATION_TTL,
                idempotency_key=f"tool_call_resource:{call.tool_call_id}",
                experiment_id=experiments.attribution_for(conn, call.cell_id),
                external_operation_type="tool_call",
                external_operation_id=call.tool_call_id,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    except Exception as exc:
        _finish(conn, call, status="failed", error=f"reservation refused: {exc}", now=now)
        raise

    conn.execute(
        "UPDATE tool_calls SET resource_reservation_id = ? WHERE tool_call_id = ?",
        (reservation.reservation_id, call.tool_call_id),
    )
    conn.commit()

    # --- phase 3: the external call, outside any transaction ----------------
    try:
        result = fetcher.fetch(call.arguments["url"], max_bytes=MAX_RESULT_BYTES)
    except ToolError as exc:
        # A refusal that definitely never left the machine. Release, don't strand.
        _finish(
            conn,
            call,
            status="failed",
            error=_redact(str(exc)),
            now=now,
            reservation_id=reservation.reservation_id,
            release=True,
        )
        raise
    except Exception as exc:
        # It may or may not have reached the network. §4.4/Charter C7: say so
        # rather than guess, and leave the RESOURCE committed until something
        # resolves it — the same posture the gateway takes with real money.
        _finish(
            conn,
            call,
            status="execution_unknown",
            error=_redact(str(exc)),
            now=now,
            reservation_id=reservation.reservation_id,
        )
        raise ToolError(f"tool call {call.tool_call_id} outcome unknown: {_redact(str(exc))}")

    return _finish_success(
        conn,
        call,
        result=result,
        reservation_id=reservation.reservation_id,
        spec=spec,
        now=now,
    )


def _claim_grant_locked(
    conn: sqlite3.Connection,
    *,
    grant_id: str,
    executed_by: str,
    reason: str,
    now: datetime,
) -> ToolCall:
    """Caller holds the write lock. Every check runs inside it.

    Check-then-lock is the bug class this kernel fixed across the board once
    already; here it would mean two external requests against one approval.
    """
    grant = approval.get_grant(conn, grant_id)
    if grant is None:
        raise ToolError(f"no such grant: {grant_id}")
    if grant.consumed_at_utc is not None:
        raise ToolError(
            f"grant {grant_id} was already consumed at "
            f"{grant.consumed_at_utc.isoformat()} — a grant authorises one tool call"
        )
    if now >= grant.expires_at_utc:
        # §23.3 forbids executing on stale terms: a fetch authorised against
        # last week's world is a different request. `approval.expire_grants_due`
        # regenerates it — as a wake, never as a fresh grant — so the Cell asks
        # again and a person decides again.
        raise ToolError(
            f"grant {grant_id} expired at {grant.expires_at_utc.isoformat()} — §23.3 "
            "forbids executing on stale terms. Run `mitosis expire-approvals` to "
            "regenerate it: the Cell proposes again and is approved afresh."
        )

    request = approval.get_request(conn, grant.request_id)
    if request is None or request.status != approval.RequestStatus.APPROVED:
        raise ToolError(f"grant {grant_id} does not correspond to an approved request")

    proposal = conn.execute(
        "SELECT * FROM proposals WHERE proposal_id = ?", (grant.proposal_id,)
    ).fetchone()
    if proposal is None:
        raise ToolError(f"grant {grant_id} names a missing proposal")

    kind = ProposalKind(proposal["kind"])
    if kind is not ProposalKind.TOOL_REQUEST:
        # Approving an experiment is a human saying "yes, think about that".
        # Turning that into permission to reach the network would let a Cell
        # obtain a capability by proposing something never reviewed as one.
        raise ToolError(
            f"grant {grant_id} is for a {kind.value} proposal; only a tool_request "
            "runs a tool"
        )

    tool_id, arguments = tool_request_of(proposal)
    spec = validate_request(tool_id, arguments)

    # §27.1: the per-tool autonomy gate. Checked here rather than at proposal
    # time because the operator may turn a flag off between approval and
    # execution, and the state that matters is the state at the moment the
    # request would leave the machine.
    if not autonomy_enabled(conn, spec.autonomy_flag):
        raise AutonomyRefused(
            f"autonomy.{spec.autonomy_flag} is disabled (§27.1 ships it false), "
            f"so {spec.tool_id} cannot run"
        )

    # Charter C12 / §19.3.
    if spec.egress_argument is not None:
        _check_egress_locked(conn, arguments[spec.egress_argument])

    cell = lifecycle.get_cell(conn, grant.cell_id)
    if cell is None:
        raise ToolError(f"grant {grant_id} names an unknown cell")
    if cell.status not in _CAN_RECEIVE_TOOL_RESULT:
        # Charter C8: a dead Cell cannot act, and a quarantined one is under
        # §18.2 restriction. Either way, nothing should be fetched on its
        # behalf and then delivered into a context it will never read.
        raise ToolError(
            f"cell {cell.cell_id} is {cell.status.value} and cannot run a tool"
        )

    conn.execute(
        "UPDATE approval_grants SET consumed_at_utc = ? WHERE grant_id = ?",
        (now.isoformat(), grant_id),
    )

    tool_call_id = ids.new_id()
    conn.execute(
        """
        INSERT INTO tool_calls (
            tool_call_id, grant_id, proposal_id, cell_id, tool, arguments_json,
            status, idempotency_key, started_at_utc, taint_label
        ) VALUES (?, ?, ?, ?, ?, ?, 'requested', ?, ?, ?)
        """,
        (
            tool_call_id,
            grant_id,
            grant.proposal_id,
            grant.cell_id,
            tool_id,
            json.dumps(arguments, sort_keys=True, separators=(",", ":")),
            f"tool_call:{grant_id}",
            now.isoformat(),
            TAINT_UNTRUSTED_EXTERNAL,
        ),
    )

    audit.record(
        conn,
        event_type="tool_call_requested",
        cell_id=grant.cell_id,
        description=f"{tool_id}: {reason}",
        metadata={
            "tool_call_id": tool_call_id,
            "grant_id": grant_id,
            "tool": tool_id,
            "executed_by": executed_by,
            "ladder_rung": LADDER_RUNG_READ_ONLY_OBSERVATION,
        },
    )

    return ToolCall(
        tool_call_id=tool_call_id,
        grant_id=grant_id,
        proposal_id=grant.proposal_id,
        cell_id=grant.cell_id,
        tool=tool_id,
        arguments=arguments,
        status="requested",
        taint_label=TAINT_UNTRUSTED_EXTERNAL,
        result_text=None,
        result_bytes=None,
        http_status=None,
        error=None,
    )


def _finish(
    conn: sqlite3.Connection,
    call: ToolCall,
    *,
    status: str,
    error: str,
    now: datetime,
    reservation_id: str | None = None,
    release: bool = False,
) -> None:
    """Close out a call that produced no usable result."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if release and reservation_id is not None:
            reservations._release_locked(conn, reservation_id)
        conn.execute(
            "UPDATE tool_calls SET status = ?, error = ?, finished_at_utc = ? "
            "WHERE tool_call_id = ?",
            (status, error, now.isoformat(), call.tool_call_id),
        )
        audit.record(
            conn,
            event_type="tool_call_finished",
            cell_id=call.cell_id,
            description=f"{call.tool} {status}",
            metadata={"tool_call_id": call.tool_call_id, "status": status},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _finish_success(
    conn: sqlite3.Connection,
    call: ToolCall,
    *,
    result: FetchResult,
    reservation_id: str,
    spec: ToolSpec,
    now: datetime,
) -> ToolCall:
    """Settle, meter, record the result with its provenance, and wake the Cell.

    One transaction: a crash that left any subset applied would mean either a
    metered call with no result, or a result the Cell is never told about.
    """
    text = result.text[:MAX_RESULT_BYTES]
    result_bytes = len(text.encode("utf-8"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    conn.execute("BEGIN IMMEDIATE")
    try:
        resource_metering._record_usage_locked(
            conn,
            cell_id=call.cell_id,
            reservation_id=reservation_id,
            resource_type=ResourceType.NETWORK_REQUESTS,
            quantity=1,
            minor_units=RESOURCE_COST_PER_CALL,
            idempotency_key=f"tool_call_usage:{call.tool_call_id}",
            metadata={"tool": call.tool, "tool_call_id": call.tool_call_id},
        )
        reservations._settle_locked(
            conn,
            reservation_id,
            settled_amount=resource_metering.total_minor_units(conn, reservation_id),
            destination_account_id=_INFRASTRUCTURE_RESERVE,
        )

        conn.execute(
            """
            UPDATE tool_calls SET
                status = 'succeeded', finished_at_utc = ?,
                source = ?, retrieved_at_utc = ?, licence = ?, permitted_uses = ?,
                commercial_use = ?, contains_personal_data = ?,
                result_text = ?, result_bytes = ?, result_sha256 = ?, http_status = ?
            WHERE tool_call_id = ?
            """,
            (
                now.isoformat(),
                result.source,
                now.isoformat(),
                result.licence,
                result.permitted_uses,
                result.commercial_use,
                1 if result.contains_personal_data else 0,
                text,
                result_bytes,
                digest,
                result.http_status,
                call.tool_call_id,
            ),
        )

        # §17.2. The Cell is told its context changed; it is not consulted here
        # and cannot act on the result except by proposing again.
        deliberation._enqueue_wake_locked(
            conn,
            cell_id=call.cell_id,
            wake_reason=deliberation.WAKE_TOOL_RESULT,
            dedupe_key=f"tool_result:{call.tool_call_id}",
        )

        audit.record(
            conn,
            event_type="tool_call_finished",
            cell_id=call.cell_id,
            description=f"{call.tool} succeeded ({result_bytes} bytes, {result.http_status})",
            metadata={
                "tool_call_id": call.tool_call_id,
                "status": "succeeded",
                "taint_label": TAINT_UNTRUSTED_EXTERNAL,
                "result_sha256": digest,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return ToolCall(
        tool_call_id=call.tool_call_id,
        grant_id=call.grant_id,
        proposal_id=call.proposal_id,
        cell_id=call.cell_id,
        tool=call.tool,
        arguments=call.arguments,
        status="succeeded",
        taint_label=TAINT_UNTRUSTED_EXTERNAL,
        result_text=text,
        result_bytes=result_bytes,
        http_status=result.http_status,
        error=None,
    )


