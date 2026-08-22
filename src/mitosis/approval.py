"""The approval queue: risk tiers, SLAs, expiry, and anti-gaming
(SPEC.md §23; Amendments A11, A19).

Migration 0013 recorded proposals and said plainly that nothing consumed them.
This is what consumes them — into a **review path**, not an execution path.

**§23.5 is the clause that shapes everything here:** "The approval queue is
itself part of the environment and will be optimised against by Cells." That is
not a caution, it is a specification. It means no input to a queueing decision
may be a value the Cell supplies about itself. §0.3 already established this for
outcomes ("a Cell may *explain* a result; it may never *define* the canonical
result"); §23.5 extends it to *requests*.

The concrete consequence is the `claimed_tier` / `assessed_tier` split. A
proposal carries a `risk_tier`, and proposal.py already anticipated the problem:
"a Cell that could set its own risk tier *and be believed* would set it to LOW
forever." So the Cell's tier is recorded as a **claim** and the kernel assesses
its own from facts the Cell does not control — its book, its status, the kind of
thing it is asking for, and the aggregate exposure of its whole lineage over a
rolling window. The relation is one-directional:

    assessed_tier >= claimed_tier, always.

A Cell may raise its own tier and be believed; it may never lower it. Claiming
*more* danger is not a gaming vector — it is a Cell flagging itself, and
disbelieving that would be perverse. Claiming less is the vector, and it is
recorded as an `understated_risk` signal rather than quietly overwritten, so the
attempt is visible rather than merely defeated.

**Why the aggregation key is the lineage, not the Cell.** §23.4 asks for
cumulative exposure "keyed by counterparty/domain/channel". None of those exist
yet — no Cell can take an external action. But the spec's target is
action-splitting, and the cheapest splitting mechanism *this* colony offers is
not one Cell making many requests: it is §9 reproduction. A Cell can birth
children and have each child request a fraction of one risky thing. Keying on
`cell_id` would miss exactly the split this system makes easiest, so the key is
`{founder_cell_id}:{kind}`. Counterparty/domain/channel join it when external
actions land.

**Two clocks, deliberately not merged (§23.3).** An SLA breach makes an item
*overdue* — "overdue items surface distinctly" is a reporting requirement, so
overdue is derived at read time and changes nothing about the item's lifecycle.
Expiry is a lifecycle transition, and §23.3 is specific about what follows it:
"expired actions are **regenerated and re-evaluated** before execution". So
expiry does not reject and does not silently drop — it enqueues a fresh wake, and
the Cell derives the action again against a world that has moved on. An approval
granted against stale facts is the thing that clause is protecting against.

**Wall time throughout, and that is not an oversight.** The scheduler had to
bridge simulated epochs to wall time for §23.3's metabolic alarm (see
`epoch_log`). Nothing here does, because every clock in this module measures a
*human*: an SLA is how long a person has, vacation mode is how long a person has
been gone, expiry is how stale a person's information is. Those are wall-time
facts by nature, and converting them to simulated time would make the queue run
fast in an accelerated colony — which is the opposite of what §23.3 wants.

**What an approval produces, and what it does not.** §25.1's ladder puts the
agent loop at rung 5, "shadow prediction with no action". This module moves it to
rung 6, "human-reviewed prototype" — no further. `approve` records a decision and
writes a **grant**: scoped to one proposal, single-use, expiring. *Nothing in the
kernel consumes a grant.* That is the same posture ADR-025 took toward proposals,
held for the same reason, and `test_no_kernel_path_consumes_a_grant` is a
structural test rather than a promise in a docstring.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import audit, deliberation, genome, ids, lifecycle, prediction
from .models import Book, CellStatus
from .proposal import ProposalKind, RiskTier

#: The rolling window §23.4's cumulative exposure is summed over, in wall
#: seconds. Set to match the LOW tier's SLA (§27.1: 86400) on purpose: the
#: window must be at least as long as an item can plausibly sit unreviewed, or a
#: patient splitter simply spaces requests out past its edge and every batch
#: looks like a first offence.
EXPOSURE_WINDOW_SECONDS = 86_400

#: How much longer than its SLA an item lives before it expires (§23.3). The
#: spec gives SLAs per tier but no expiry, and deriving expiry from the SLA
#: avoids inventing a fourth unspecified knob — it also inherits the tier
#: ordering, so a CRITICAL item expires in an hour. That reads harsh until you
#: read it as §23.3 does: a critical action nobody looked at within the hour
#: should be re-derived, not executed on hour-old reasoning.
EXPIRY_SLA_MULTIPLE = 4

#: Exposure thresholds, expressed as multiples of the operator's own
#: `metabolic_alarm_cents_per_epoch` (§27.1, default 50) rather than as three
#: fresh constants. The colony already has a stated opinion about what a
#: worrying rate of spend looks like; the queue should not hold a second,
#: silently different one. An operator who tunes their burn tolerance tunes the
#: review thresholds with it.
EXPOSURE_MEDIUM_ALARM_MULTIPLE = 0.5
EXPOSURE_HIGH_ALARM_MULTIPLE = 1.0
EXPOSURE_CRITICAL_ALARM_MULTIPLE = 4.0

#: Minimum number of requests on one aggregation key before splitting is even
#: considered. Two requests are a colony working; the pattern §23.4 describes
#: needs a run.
SPLIT_MIN_REQUESTS = 3

#: Pending requests from one lineage in the window before `queue_flooding`
#: fires. §23.3's "400 approvals quietly queuing overnight" is the failure being
#: guarded; this catches the shape of it long before the number.
QUEUE_FLOOD_PENDING_LIMIT = 5

#: Overdue unresolved predictions a Cell may carry before new forecasts read as
#: `selective_evidence`. A Cell that resolves only its winners has a beautiful
#: calibration curve and a pile of these behind it (see `prediction.overdue`) —
#: offering fresh predictions as evidence while that pile grows is the §23.4
#: "selective evidence" pattern precisely.
SELECTIVE_EVIDENCE_OVERDUE_LIMIT = 3

_TIER_ORDER: dict[RiskTier, int] = {
    RiskTier.LOW: 0,
    RiskTier.MEDIUM: 1,
    RiskTier.HIGH: 2,
    RiskTier.CRITICAL: 3,
}

_TIER_BY_ORDER = {order: tier for tier, order in _TIER_ORDER.items()}

#: §23.4's detections. Named as constants because they are written to a CHECKed
#: column and read by the CLI; a typo should fail at import, not at 3am.
SIGNAL_ACTION_SPLITTING = "action_splitting"
SIGNAL_QUEUE_FLOODING = "queue_flooding"
SIGNAL_UNDERSTATED_RISK = "understated_risk"
SIGNAL_SELECTIVE_EVIDENCE = "selective_evidence"
SIGNAL_REPEAT_AFTER_REJECTION = "repeat_after_rejection"

#: Signals that escalate the assessed tier. `understated_risk` is excluded
#: because it is *derived from* the assessment — letting it escalate would make
#: the kernel's own finding raise the bar it was measured against, which is
#: circular and would push every honest MEDIUM to HIGH the moment a Cell
#: guessed LOW.
_ESCALATING_SIGNALS = frozenset(
    {
        SIGNAL_ACTION_SPLITTING,
        SIGNAL_QUEUE_FLOODING,
        SIGNAL_SELECTIVE_EVIDENCE,
        SIGNAL_REPEAT_AFTER_REJECTION,
    }
)

#: The wake reason an expiry regenerates under (§23.3). Distinct from §17.2's
#: scheduled research so the record shows *why* the Cell was asked again.
WAKE_APPROVAL_EXPIRED = "approval_expired"


class ApprovalError(Exception):
    pass


class RequestStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Signal:
    signal: str
    detail: str


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    proposal_id: str
    cell_id: str
    founder_cell_id: str
    aggregation_key: str
    claimed_tier: RiskTier
    assessed_tier: RiskTier
    exposure_minor_units: int
    reversible: bool
    status: str
    sla_seconds: int
    sla_due_at_utc: datetime
    expires_at_utc: datetime
    created_at_utc: datetime
    decided_at_utc: datetime | None
    decided_by: str | None
    decision_reason: str | None
    batch_id: str | None
    regenerated_wake_key: str | None
    signals: tuple[Signal, ...] = ()

    def is_overdue(self, *, now: datetime | None = None) -> bool:
        """§23.3's "overdue items surface distinctly".

        Derived, never stored. An overdue item is still pending and still
        approvable on exactly the same terms — the only thing that changes is
        how loudly it appears. Storing it would create a second lifecycle state
        that means nothing and could disagree with the clock.
        """
        if self.status != RequestStatus.PENDING:
            return False
        return (now or _now()) >= self.sla_due_at_utc

    @property
    def batchable(self) -> bool:
        """Whether §23.1 permits approving this without individual review.

        "Batch low-risk reversible actions; require individual review for
        high-risk or irreversible actions."

        **Batching is the payload of an action-splitting attack**, so §23.1 and
        §23.4 have to interlock rather than sit side by side. Two mechanisms do
        that here. The tier test is not only about this item: `assessed_tier`
        already folds in the lineage's cumulative exposure, so a run of
        individually-trivial requests stops being batchable once the *aggregate*
        crosses a threshold, even though no single one ever would. And any
        gaming signal disqualifies an item outright — that is §23.1's
        "individual review for high-risk" doing real work rather than
        decorating a log line.
        """
        return (
            self.assessed_tier is RiskTier.LOW
            and self.reversible
            and not self.signals
        )


@dataclass(frozen=True)
class Grant:
    """What an approval produces. Nothing consumes it — see the module docstring."""

    grant_id: str
    request_id: str
    proposal_id: str
    cell_id: str
    tier: RiskTier
    exposure_at_grant_minor_units: int
    granted_at_utc: datetime
    expires_at_utc: datetime
    consumed_at_utc: datetime | None


@dataclass(frozen=True)
class ApprovalPayload:
    """§23.2's payload, assembled.

    The clause names ten things the operator must see. Two of them cannot be
    honestly produced today, and this dataclass says so in its own fields rather
    than omitting them — a payload that quietly drops a required element is
    worse than one that reports the element as unavailable, because only the
    second is visible in review.
    """

    request: ApprovalRequest
    proposal: dict
    #: §23.2 "real and synthetic cost". The Cell's estimate is a claim; the
    #: model-call cost of the deliberation that produced it is a ledger fact.
    estimated_cost_minor_units: int
    book: Book
    deliberation_cost_micro_usd: int | None
    #: §23.2 "cumulative related exposure".
    exposure_minor_units: int
    related_request_count: int
    #: §23.2 "liability". `liability_reserve` is one of §31's **required
    #: Phase-1 accounts** and exists (`accounts.FIXED_ACCOUNTS`, classified as a
    #: SPEND_DESTINATION); what is missing is any policy that *provisions* one,
    #: so no Cell has a reserve to report. This stays None and the CLI prints it
    #: as unavailable — fabricating a zero would read as "no liability" rather
    #: than "not yet modelled". An earlier version of this comment said no
    #: liability-reserve concept was implemented and cited §13, which is Novelty
    #: Evaluation; both halves were wrong, and the account had been in the
    #: Phase-1 list the whole time.
    liability_minor_units: int | None
    #: §23.2 "Cell explanation".
    cell_explanation: str
    #: §23.2 "independent Auditor summary", filled from `audits` when an
    #: Auditor Cell has reviewed this request (ADR-032). Still None when none
    #: has — an unaudited request must read as unaudited rather than as clean.
    #: **This field can never be filled by the proposing Cell** — the clause
    #: says *independent*, and §0.3 forbids a Cell defining the canonical
    #: account of its own work.
    auditor_summary: str | None
    #: §23.2 "relevant evidence" — the Cell's own track record, taken from the
    #: hash-chained register rather than from anything it said about itself.
    resolved_prediction_count: int
    unresolved_prediction_count: int
    overdue_prediction_count: int
    mean_brier_score: float | None
    #: §23.2 "policy classification".
    signals: tuple[Signal, ...]
    current_cell_status: CellStatus
    overdue: bool
    #: Every audit on this request, oldest first. Plural because a second
    #: Auditor is allowed and is worth seeing separately: two independent
    #: opinions that agree are evidence, and the same opinion twice is not.
    #: Raw rows rather than `auditor.Audit` — see `_audit_rows` on why this
    #: module reads the table instead of importing the module that owns it.
    audits: tuple = ()


# --- the seam ----------------------------------------------------------------


class QueueSink:
    """`deliberation.ProposalSink`, implemented.

    The dependency runs approval → deliberation (this module regenerates wakes
    on expiry), so deliberation must not import approval. This is the injected
    seam that inverts it, in the established shape of `population.Displacer` and
    `sweeper.ExternalOperationChecker`.

    **Note what the signature cannot accept**, the same way `Displacer` cannot
    accept a child: `enqueue_locked` takes a `proposal_id` and nothing else. The
    tier, the cost, the book, the exposure — every input to the classification —
    is read from the database by the queue itself, inside the caller's
    transaction. There is deliberately no parameter through which a caller could
    hand the queue a pre-computed assessment, because a Cell's own tier reaching
    the queue as an authority is the failure §23.5 predicts.
    """

    def enqueue_locked(self, conn: sqlite3.Connection, *, proposal_id: str) -> None:
        _enqueue_locked(conn, proposal_id=proposal_id)


# --- enqueueing --------------------------------------------------------------


def _enqueue_locked(
    conn: sqlite3.Connection, *, proposal_id: str, now: datetime | None = None
) -> ApprovalRequest | None:
    """Queue one proposal for review. Caller holds the transaction.

    Returns None when the proposal is not reviewable — an `abstain`, or one
    already queued. Abstentions are deliberately not queued: there is nothing to
    approve, and a queue full of "I have nothing to propose" is not merely noise.
    It would be *useful* noise to a Cell trying to make a flood look ordinary,
    which makes it an anti-gaming concern rather than a tidiness one.
    """
    row = conn.execute(
        "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()
    if row is None:
        raise ApprovalError(f"no such proposal: {proposal_id}")

    if row["kind"] == ProposalKind.ABSTAIN.value:
        return None

    existing = conn.execute(
        "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if existing is not None:
        return get_request(conn, existing["request_id"])

    cell = lifecycle.get_cell(conn, row["cell_id"])
    if cell is None:
        raise ApprovalError(f"proposal {proposal_id} names an unknown cell")

    kind = ProposalKind(row["kind"])
    claimed = RiskTier(row["risk_tier"])
    estimated = int(row["estimated_cost_minor_units"])
    now = now or _now()

    aggregation_key = _aggregation_key(founder_cell_id=cell.founder_cell_id, kind=kind)
    prior = _window_requests(conn, aggregation_key=aggregation_key, now=now)
    exposure = sum(int(r["exposure_delta"]) for r in prior) + estimated

    reversible = _is_reversible(kind=kind, book=cell.book)
    kernel_tier = _kernel_tier(
        kind=kind,
        book=cell.book,
        status=cell.status,
        exposure_minor_units=exposure,
        alarm_cents_per_epoch=_metabolic_alarm_cents(conn),
    )

    signals = _detect_signals(
        conn,
        cell_id=cell.cell_id,
        founder_cell_id=cell.founder_cell_id,
        aggregation_key=aggregation_key,
        claimed_tier=claimed,
        kernel_tier=kernel_tier,
        kind=kind,
        estimated_cost_minor_units=estimated,
        exposure_minor_units=exposure,
        prior_request_count=len(prior),
        summary=row["summary"],
        now=now,
    )

    assessed = _assessed_tier(
        claimed=claimed,
        kernel_tier=kernel_tier,
        signals=signals,
        genome_claim=_genome_risk_claim(conn, cell.genome_hash),
    )

    sla_seconds = _sla_seconds(conn, assessed)
    request_id = ids.new_id()
    conn.execute(
        """
        INSERT INTO approval_requests (
            request_id, proposal_id, cell_id, aggregation_key, founder_cell_id,
            claimed_tier, assessed_tier, exposure_minor_units, reversible, status,
            sla_seconds, sla_due_at_utc, expires_at_utc, created_at_utc,
            decided_at_utc, decided_by, decision_reason, batch_id, regenerated_wake_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
        """,
        (
            request_id,
            proposal_id,
            cell.cell_id,
            aggregation_key,
            cell.founder_cell_id,
            claimed.value,
            assessed.value,
            exposure,
            1 if reversible else 0,
            RequestStatus.PENDING,
            sla_seconds,
            (now + timedelta(seconds=sla_seconds)).isoformat(),
            (now + timedelta(seconds=sla_seconds * EXPIRY_SLA_MULTIPLE)).isoformat(),
            now.isoformat(),
        ),
    )

    for signal in signals:
        conn.execute(
            "INSERT INTO approval_signals (signal_id, request_id, signal, detail, created_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            (ids.new_id(), request_id, signal.signal, signal.detail, now.isoformat()),
        )

    audit.record(
        conn,
        event_type="approval_requested",
        cell_id=cell.cell_id,
        description=f"{assessed.value}: {row['summary']}",
        metadata={
            "request_id": request_id,
            "proposal_id": proposal_id,
            "claimed_tier": claimed.value,
            "assessed_tier": assessed.value,
            "exposure_minor_units": exposure,
            "reversible": reversible,
            "signals": sorted(s.signal for s in signals),
        },
    )

    result = get_request(conn, request_id)
    assert result is not None
    return result


def enqueue(
    conn: sqlite3.Connection, *, proposal_id: str, now: datetime | None = None
) -> ApprovalRequest | None:
    """Queue one proposal for review, in its own transaction."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _enqueue_locked(conn, proposal_id=proposal_id, now=now)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


def enqueue_missing(conn: sqlite3.Connection) -> list[ApprovalRequest]:
    """Queue any reviewable proposal that has no queue entry, oldest first.

    Self-healing, and it exists for two honest reasons. Proposals recorded
    before this module existed have no request; and while the normal path
    queues atomically with the proposal (see `QueueSink`), a caller that
    deliberates without wiring the sink would otherwise create proposals no
    operator ever sees. A review surface that can silently miss items is not one.

    Idempotent: `approval_requests.proposal_id` is UNIQUE, and abstentions are
    skipped on every pass rather than retried.
    """
    rows = conn.execute(
        """
        SELECT p.proposal_id FROM proposals p
         LEFT JOIN approval_requests r ON r.proposal_id = p.proposal_id
         WHERE r.request_id IS NULL AND p.kind != ?
         ORDER BY p.created_at_utc, p.rowid
        """,
        (ProposalKind.ABSTAIN.value,),
    ).fetchall()

    queued = []
    for row in rows:
        request = enqueue(conn, proposal_id=row["proposal_id"])
        if request is not None:
            queued.append(request)
    return queued


# --- classification ----------------------------------------------------------


def _aggregation_key(*, founder_cell_id: str, kind: ProposalKind) -> str:
    """§23.4's key. Lineage plus kind — see the module docstring on why the
    lineage founder rather than the Cell."""
    return f"lineage:{founder_cell_id}:{kind.value}"


def _is_reversible(*, kind: ProposalKind, book: Book) -> bool:
    """Kernel-derived, never asserted by the Cell (§23.1).

    Real money leaving the colony is the only thing here that cannot be undone.
    §3.6 forbids editing history to correct something — the remedy is a signed
    adjustment, and an adjustment does not bring the money back. Everything else
    a proposal can ask for is simulated or internal, and therefore reversible.
    """
    return not (kind is ProposalKind.SPEND_REQUEST and book is Book.USD_REAL)


def _kernel_tier(
    *,
    kind: ProposalKind,
    book: Book,
    status: CellStatus,
    exposure_minor_units: int,
    alarm_cents_per_epoch: int,
) -> RiskTier:
    """The tier the kernel assesses, from facts the Cell does not control.

    Every input here is either schema-validated structure (`kind`) or colony
    state the Cell cannot write (`book`, `status`, and the aggregate exposure of
    its lineage). Notably absent: the Cell's own `risk_tier`, which is folded in
    afterwards by `_assessed_tier` and only ever upward.
    """
    tier = RiskTier.LOW

    if kind is ProposalKind.SPEND_REQUEST:
        # It asks for money. Even in simulation that is the category of request
        # §23.1 wants looked at, because the strategies it trains transfer.
        tier = _max_tier(tier, RiskTier.MEDIUM)
        if book is Book.USD_REAL:
            # Real, and irreversible. Nothing a Cell can say lowers this.
            tier = _max_tier(tier, RiskTier.HIGH)

    if status is CellStatus.QUARANTINED:
        # §18.2. A Cell under restriction cannot deliberate, so it cannot reach
        # here at enqueue time — but it can be quarantined *after* proposing and
        # before review, and a restricted Cell's pending request should not be
        # batch-approved on the strength of an assessment made when it was
        # healthy. The payload also shows the Cell's current status for exactly
        # this reason.
        tier = _max_tier(tier, RiskTier.HIGH)

    tier = _max_tier(
        tier,
        _exposure_tier(
            exposure_minor_units=exposure_minor_units,
            alarm_cents_per_epoch=alarm_cents_per_epoch,
        ),
    )
    return tier


def _exposure_tier(*, exposure_minor_units: int, alarm_cents_per_epoch: int) -> RiskTier:
    """Tier implied by cumulative exposure alone (§23.2, §23.4).

    Thresholds are multiples of the operator's metabolic alarm rather than fresh
    constants — the colony should not hold two different silent opinions about
    what a worrying amount of money is.
    """
    if exposure_minor_units >= alarm_cents_per_epoch * EXPOSURE_CRITICAL_ALARM_MULTIPLE:
        return RiskTier.CRITICAL
    if exposure_minor_units >= alarm_cents_per_epoch * EXPOSURE_HIGH_ALARM_MULTIPLE:
        return RiskTier.HIGH
    if exposure_minor_units >= alarm_cents_per_epoch * EXPOSURE_MEDIUM_ALARM_MULTIPLE:
        return RiskTier.MEDIUM
    return RiskTier.LOW


def _assessed_tier(
    *,
    claimed: RiskTier,
    kernel_tier: RiskTier,
    signals: tuple[Signal, ...],
    genome_claim: RiskTier | None = None,
) -> RiskTier:
    """Fold the Cell's claims into the kernel's assessment — upward only.

    `max` is the entire policy, and it is the §23.5 boundary in one line: a Cell
    may raise its own tier and be believed, and may never lower it.

    **There are two claims, not one.** `claimed` is the tier this proposal
    stated; `genome_claim` is §16.2's `risk_class`, inherited and mutable. They
    fold identically and for the same reason: a genome is Cell-mutable content,
    so a lineage that could write `risk_class: LOW` into its children would have
    bought them cheap approvals for as long as the lineage survived — a far more
    durable version of the per-proposal gaming ADR-027 already refused. Reusing
    `max` rather than adding a second mechanism is the point; a genome may raise
    a Cell's review tier and can never lower it.
    """
    tier = _max_tier(kernel_tier, claimed)
    if genome_claim is not None:
        tier = _max_tier(tier, genome_claim)
    if any(s.signal in _ESCALATING_SIGNALS for s in signals):
        tier = _escalate(tier)
    return tier


def _genome_risk_claim(conn: sqlite3.Connection, genome_hash: str) -> RiskTier | None:
    """§16.2's `risk_class`, read as a claim (see `_assessed_tier`).

    An unparseable or absent value is None rather than an error: a genome that
    states no risk class is the ordinary case, and one that states nonsense
    must not be able to block its own Cell's review by making the request
    unbuildable.
    """
    row = conn.execute(
        "SELECT canonical_genome_json FROM cell_genomes WHERE genome_hash = ?",
        (genome_hash,),
    ).fetchone()
    if row is None:
        return None
    try:
        claim = genome.risk_class_of(json.loads(row["canonical_genome_json"]))
        return RiskTier(claim) if claim is not None else None
    except (json.JSONDecodeError, ValueError):
        return None


def _max_tier(left: RiskTier, right: RiskTier) -> RiskTier:
    return left if _TIER_ORDER[left] >= _TIER_ORDER[right] else right


def _escalate(tier: RiskTier) -> RiskTier:
    return _TIER_BY_ORDER[min(_TIER_ORDER[tier] + 1, _TIER_ORDER[RiskTier.CRITICAL])]


# --- §23.4 anti-gaming -------------------------------------------------------


def _detect_signals(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    founder_cell_id: str,
    aggregation_key: str,
    claimed_tier: RiskTier,
    kernel_tier: RiskTier,
    kind: ProposalKind,
    estimated_cost_minor_units: int,
    exposure_minor_units: int,
    prior_request_count: int,
    summary: str,
    now: datetime,
) -> tuple[Signal, ...]:
    """§23.4's detections.

    **These annotate; they never auto-reject.** The restraint is deliberate and
    it follows from §23.5: an automatic rejector is simply the next thing to
    optimise against, and it fails closed on honest work without anyone
    noticing. A signal does two things instead — it escalates the tier, and it
    strips batch eligibility so a human must look at the item individually. The
    human still decides.
    """
    signals: list[Signal] = []
    alarm = _metabolic_alarm_cents(conn)

    # 1. Action splitting (A11). A run of individually-modest requests on one
    #    aggregation key whose *total* has crossed a tier the individual items
    #    never would. The second half of that sentence is the test — a lineage
    #    making many genuinely trivial requests is not splitting anything.
    if prior_request_count + 1 >= SPLIT_MIN_REQUESTS:
        individual_tier = _exposure_tier(
            exposure_minor_units=estimated_cost_minor_units,
            alarm_cents_per_epoch=alarm,
        )
        aggregate_tier = _exposure_tier(
            exposure_minor_units=exposure_minor_units, alarm_cents_per_epoch=alarm
        )
        if _TIER_ORDER[aggregate_tier] > _TIER_ORDER[individual_tier]:
            signals.append(
                Signal(
                    SIGNAL_ACTION_SPLITTING,
                    f"{prior_request_count + 1} requests on {aggregation_key} total "
                    f"{exposure_minor_units} minor units ({aggregate_tier.value}) while "
                    f"this one alone is {estimated_cost_minor_units} ({individual_tier.value})",
                )
            )

    # 2. Queue flooding (§23.4). Pending items from one lineage, regardless of
    #    kind — a flood built from three kinds of request is still a flood.
    pending_from_lineage = conn.execute(
        """
        SELECT COUNT(*) AS n FROM approval_requests
         WHERE founder_cell_id = ? AND status = ? AND created_at_utc >= ?
        """,
        (
            founder_cell_id,
            RequestStatus.PENDING,
            _window_start(now).isoformat(),
        ),
    ).fetchone()["n"]
    if pending_from_lineage >= QUEUE_FLOOD_PENDING_LIMIT:
        signals.append(
            Signal(
                SIGNAL_QUEUE_FLOODING,
                f"lineage {founder_cell_id} already has {pending_from_lineage} pending "
                f"requests in the last {EXPOSURE_WINDOW_SECONDS}s",
            )
        )

    # 3. Understated risk (§23.4 "misleading summaries"). Two shapes: a tier
    #    below the kernel's, and a spend request that claims to cost nothing.
    if _TIER_ORDER[claimed_tier] < _TIER_ORDER[kernel_tier]:
        signals.append(
            Signal(
                SIGNAL_UNDERSTATED_RISK,
                f"cell claimed {claimed_tier.value}; kernel assessed {kernel_tier.value}",
            )
        )
    elif kind is ProposalKind.SPEND_REQUEST and estimated_cost_minor_units == 0:
        signals.append(
            Signal(
                SIGNAL_UNDERSTATED_RISK,
                "spend request estimates zero cost",
            )
        )

    # 4. Selective evidence (§23.4). New forecasts offered while earlier ones
    #    sit unresolved past their own horizon. `prediction.overdue` exists for
    #    exactly this anti-gaming surface; this is its first consumer.
    overdue_here = [p for p in prediction.overdue(conn, now=now) if p.cell_id == cell_id]
    if len(overdue_here) >= SELECTIVE_EVIDENCE_OVERDUE_LIMIT:
        signals.append(
            Signal(
                SIGNAL_SELECTIVE_EVIDENCE,
                f"{len(overdue_here)} of this cell's predictions are unresolved past "
                "their horizon",
            )
        )

    # 5. Repeated request after rejection (§23.4). Compared on a normalised
    #    summary, so re-punctuating a rejected ask does not launder it.
    normalised = _normalise(summary)
    if normalised:
        for row in conn.execute(
            """
            SELECT r.request_id, p.summary FROM approval_requests r
              JOIN proposals p ON p.proposal_id = r.proposal_id
             WHERE r.founder_cell_id = ? AND r.status = ?
            """,
            (founder_cell_id, RequestStatus.REJECTED),
        ).fetchall():
            if _normalise(row["summary"]) == normalised:
                signals.append(
                    Signal(
                        SIGNAL_REPEAT_AFTER_REJECTION,
                        f"substantially this request was rejected as {row['request_id']}",
                    )
                )
                break

    return tuple(signals)


def _normalise(text: str) -> str:
    """Casefold, strip punctuation, collapse whitespace.

    Enough to defeat re-punctuation and capitalisation, and deliberately no
    more: a fuzzy matcher here would start refusing genuinely new requests that
    happen to read alike, and a false `repeat_after_rejection` is a signal an
    operator learns to ignore.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text).casefold()).strip()


# --- decisions ---------------------------------------------------------------


def approve(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    decided_by: str,
    reason: str,
    now: datetime | None = None,
) -> Grant:
    """Approve one request individually, producing a grant.

    A reason is mandatory. §25.2 requires "the reasons for promotion or
    rejection" recorded at each rung of the ladder, and this is the rung-6 gate
    — an approval with no stated reason is an unauditable one.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ApprovalError("an approval must state a reason (§25.2)")
    return _decide_approve(
        conn,
        request_id=request_id,
        decided_by=decided_by,
        reason=reason,
        batch_id=None,
        now=now,
    )


def reject(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    decided_by: str,
    reason: str,
    now: datetime | None = None,
) -> ApprovalRequest:
    """Reject one request. A reason is mandatory, for the §25.2 reason above —
    and because `repeat_after_rejection` is only meaningful if the record says
    what was rejected and why."""
    reason = (reason or "").strip()
    if not reason:
        raise ApprovalError("a rejection must state a reason (§25.2)")

    now = now or _now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        request = _pending_or_raise_locked(conn, request_id=request_id, now=now)
        conn.execute(
            """
            UPDATE approval_requests
               SET status = ?, decided_at_utc = ?, decided_by = ?, decision_reason = ?
             WHERE request_id = ?
            """,
            (RequestStatus.REJECTED, now.isoformat(), decided_by, reason, request_id),
        )
        audit.record(
            conn,
            event_type="approval_rejected",
            cell_id=request.cell_id,
            description=reason,
            metadata={
                "request_id": request_id,
                "proposal_id": request.proposal_id,
                "assessed_tier": request.assessed_tier.value,
                "decided_by": decided_by,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_request(conn, request_id)
    assert result is not None
    return result


def approve_batch(
    conn: sqlite3.Connection,
    *,
    decided_by: str,
    reason: str,
    now: datetime | None = None,
    limit: int | None = None,
) -> tuple[str, list[Grant]]:
    """§23.1's "batch low-risk reversible actions".

    Approves every currently batchable pending request under one batch id.
    Items that are not batchable are simply left in the queue for individual
    review — this never widens its own eligibility to clear the backlog, which
    is the failure mode that would turn §23.1's convenience into §23.4's
    vulnerability.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ApprovalError("a batch approval must state a reason (§25.2)")

    now = now or _now()
    batch_id = ids.new_id()
    eligible = [r for r in queue(conn, now=now) if r.batchable]
    if limit is not None:
        eligible = eligible[:limit]

    grants = []
    for request in eligible:
        grants.append(
            _decide_approve(
                conn,
                request_id=request.request_id,
                decided_by=decided_by,
                reason=reason,
                batch_id=batch_id,
                now=now,
            )
        )
    return batch_id, grants


def _decide_approve(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    decided_by: str,
    reason: str,
    batch_id: str | None,
    now: datetime | None,
) -> Grant:
    now = now or _now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        request = _pending_or_raise_locked(conn, request_id=request_id, now=now)

        if batch_id is not None and not request.batchable:
            raise ApprovalError(
                f"{request_id} is not batchable "
                f"({request.assessed_tier.value}, "
                f"{'reversible' if request.reversible else 'irreversible'}, "
                f"{len(request.signals)} signals) — §23.1 requires individual review"
            )

        conn.execute(
            """
            UPDATE approval_requests
               SET status = ?, decided_at_utc = ?, decided_by = ?, decision_reason = ?,
                   batch_id = ?
             WHERE request_id = ?
            """,
            (
                RequestStatus.APPROVED,
                now.isoformat(),
                decided_by,
                reason,
                batch_id,
                request_id,
            ),
        )

        grant_id = ids.new_id()
        grant_expires = request.expires_at_utc
        conn.execute(
            """
            INSERT INTO approval_grants (
                grant_id, request_id, proposal_id, cell_id, tier,
                exposure_at_grant_minor_units, granted_at_utc, expires_at_utc,
                consumed_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                grant_id,
                request_id,
                request.proposal_id,
                request.cell_id,
                request.assessed_tier.value,
                request.exposure_minor_units,
                now.isoformat(),
                grant_expires.isoformat(),
            ),
        )

        audit.record(
            conn,
            event_type="approval_granted",
            cell_id=request.cell_id,
            description=reason,
            metadata={
                "request_id": request_id,
                "proposal_id": request.proposal_id,
                "grant_id": grant_id,
                "assessed_tier": request.assessed_tier.value,
                "batch_id": batch_id,
                "decided_by": decided_by,
                "exposure_minor_units": request.exposure_minor_units,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    grant = get_grant(conn, grant_id)
    assert grant is not None
    return grant


def _pending_or_raise_locked(
    conn: sqlite3.Connection, *, request_id: str, now: datetime
) -> ApprovalRequest:
    """Re-read the request inside the write lock and check it is still actionable.

    Read inside the lock on purpose. Check-then-lock is the bug class this
    kernel already fixed once across the board: a request validated before
    `BEGIN IMMEDIATE` can be decided, or expire, between the check and the
    write. Here that would mean two decisions on one item, or a grant issued
    against a request that had already expired.
    """
    request = get_request(conn, request_id)
    if request is None:
        raise ApprovalError(f"no such approval request: {request_id}")
    if request.status != RequestStatus.PENDING:
        raise ApprovalError(
            f"{request_id} is already {request.status}; only pending requests can be decided"
        )
    if now >= request.expires_at_utc:
        raise ApprovalError(
            f"{request_id} expired at {request.expires_at_utc.isoformat()} — §23.3 requires "
            "the action be regenerated and re-evaluated, not decided on stale terms "
            "(run `mitosis expire-approvals`)"
        )
    return request


# --- §23.3 expiry and regeneration -------------------------------------------


def expire_due(
    conn: sqlite3.Connection, *, now: datetime | None = None
) -> list[ApprovalRequest]:
    """Expire pending requests past their expiry, and regenerate each action.

    §23.3: "Pending approvals expire; expired actions are **regenerated and
    re-evaluated** before execution." Both halves matter and the second is the
    one that is easy to drop. Expiry is not rejection — the operator never
    judged the item — so the action is not discarded; it is asked for again by
    waking the Cell, which re-derives it against a world that has moved. That is
    what stops a stale approval being acted on later.

    A Cell that can no longer deliberate (dead, quarantined) has nothing to
    regenerate into. Its request still expires, and `regenerated_wake_key` stays
    NULL so the gap is visible rather than looking like a wake that vanished.
    """
    now = now or _now()
    due = conn.execute(
        "SELECT request_id FROM approval_requests WHERE status = ? AND expires_at_utc <= ?"
        " ORDER BY expires_at_utc, rowid",
        (RequestStatus.PENDING, now.isoformat()),
    ).fetchall()

    expired = []
    for row in due:
        expired.append(_expire_one(conn, request_id=row["request_id"], now=now))
    return expired


def _expire_one(
    conn: sqlite3.Connection, *, request_id: str, now: datetime
) -> ApprovalRequest:
    conn.execute("BEGIN IMMEDIATE")
    try:
        request = get_request(conn, request_id)
        if request is None:
            raise ApprovalError(f"no such approval request: {request_id}")
        if request.status != RequestStatus.PENDING:
            # Decided between the scan and the lock. Not an error — the
            # operator won the race, and their decision stands.
            conn.execute("ROLLBACK")
            return request

        cell = lifecycle.get_cell(conn, request.cell_id)
        wake_key: str | None = None
        if cell is not None and cell.status in {CellStatus.ALIVE, CellStatus.DORMANT}:
            wake_key = f"approval-expiry:{request_id}"
            deliberation._enqueue_wake_locked(
                conn,
                cell_id=request.cell_id,
                wake_reason=WAKE_APPROVAL_EXPIRED,
                dedupe_key=wake_key,
            )

        conn.execute(
            """
            UPDATE approval_requests
               SET status = ?, decided_at_utc = ?, decided_by = 'colony',
                   decision_reason = ?, regenerated_wake_key = ?
             WHERE request_id = ?
            """,
            (
                RequestStatus.EXPIRED,
                now.isoformat(),
                f"expired unreviewed after {request.sla_seconds * EXPIRY_SLA_MULTIPLE}s",
                wake_key,
                request_id,
            ),
        )

        audit.record(
            conn,
            event_type="approval_expired",
            cell_id=request.cell_id,
            description=f"{request.assessed_tier.value} request expired unreviewed",
            metadata={
                "request_id": request_id,
                "proposal_id": request.proposal_id,
                "regenerated_wake_key": wake_key,
                "assessed_tier": request.assessed_tier.value,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_request(conn, request_id)
    assert result is not None
    return result


# --- reading -----------------------------------------------------------------


def queue(
    conn: sqlite3.Connection,
    *,
    status: str = RequestStatus.PENDING,
    now: datetime | None = None,
) -> list[ApprovalRequest]:
    """The queue, most urgent first.

    Ordered by assessed tier descending, then by SLA due time ascending, so
    §23.3's "overdue items surface distinctly" holds without the caller sorting:
    the most dangerous thing that has been waiting longest is at the top.
    """
    now = now or _now()
    rows = conn.execute(
        "SELECT request_id FROM approval_requests WHERE status = ?", (status,)
    ).fetchall()
    requests = [get_request(conn, r["request_id"]) for r in rows]
    return sorted(
        (r for r in requests if r is not None),
        key=lambda r: (-_TIER_ORDER[r.assessed_tier], r.sla_due_at_utc),
    )


def get_request(conn: sqlite3.Connection, request_id: str) -> ApprovalRequest | None:
    row = conn.execute(
        "SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)
    ).fetchone()
    if row is None:
        return None
    signals = tuple(
        Signal(s["signal"], s["detail"])
        for s in conn.execute(
            "SELECT signal, detail FROM approval_signals WHERE request_id = ? "
            "ORDER BY rowid",
            (request_id,),
        ).fetchall()
    )
    return ApprovalRequest(
        request_id=row["request_id"],
        proposal_id=row["proposal_id"],
        cell_id=row["cell_id"],
        founder_cell_id=row["founder_cell_id"],
        aggregation_key=row["aggregation_key"],
        claimed_tier=RiskTier(row["claimed_tier"]),
        assessed_tier=RiskTier(row["assessed_tier"]),
        exposure_minor_units=int(row["exposure_minor_units"]),
        reversible=bool(row["reversible"]),
        status=row["status"],
        sla_seconds=int(row["sla_seconds"]),
        sla_due_at_utc=_parse(row["sla_due_at_utc"]),
        expires_at_utc=_parse(row["expires_at_utc"]),
        created_at_utc=_parse(row["created_at_utc"]),
        decided_at_utc=_parse(row["decided_at_utc"]) if row["decided_at_utc"] else None,
        decided_by=row["decided_by"],
        decision_reason=row["decision_reason"],
        batch_id=row["batch_id"],
        regenerated_wake_key=row["regenerated_wake_key"],
        signals=signals,
    )


def get_grant(conn: sqlite3.Connection, grant_id: str) -> Grant | None:
    row = conn.execute(
        "SELECT * FROM approval_grants WHERE grant_id = ?", (grant_id,)
    ).fetchone()
    if row is None:
        return None
    return Grant(
        grant_id=row["grant_id"],
        request_id=row["request_id"],
        proposal_id=row["proposal_id"],
        cell_id=row["cell_id"],
        tier=RiskTier(row["tier"]),
        exposure_at_grant_minor_units=int(row["exposure_at_grant_minor_units"]),
        granted_at_utc=_parse(row["granted_at_utc"]),
        expires_at_utc=_parse(row["expires_at_utc"]),
        consumed_at_utc=(
            _parse(row["consumed_at_utc"]) if row["consumed_at_utc"] else None
        ),
    )


def _audit_rows(conn: sqlite3.Connection, request_id: str) -> list[sqlite3.Row]:
    """§23.2's Auditor summaries, read as rows rather than through `auditor`.

    The dependency runs auditor -> approval (an audit is *of* a request, and
    needs this payload to brief the Auditor at all), so importing back would
    close a cycle. A direct read is the honest alternative here: `audits` is
    part of the same migrated schema, and the shape being read — a verdict and
    a summary — is the §23.2 field itself, not the auditing machinery.

    Deliberately not a seam. `population.Displacer` and
    `sweeper.ExternalOperationChecker` invert *behaviour* that would otherwise
    run the wrong way; this is a read with no behaviour in it, and a protocol
    around a SELECT would be ceremony that hides where the coupling is.
    """
    return conn.execute(
        "SELECT * FROM audits WHERE request_id = ? ORDER BY rowid", (request_id,)
    ).fetchall()


def _auditor_summary(conn: sqlite3.Connection, request_id: str) -> str | None:
    """The §23.2 field, rendered for a human.

    None when nobody has audited — an unaudited request must read as unaudited,
    never as clean. Attribution is included even for a single audit, because a
    summary whose author is invisible reads as the kernel's own view, and the
    whole point of the clause is that it is somebody else's.
    """
    # Rejected audits are excluded, not rendered as an opinion with blanks in
    # it: a reply that produced no verdict is not a judgement, and §23.2's
    # field showing one would tell an operator that somebody looked when
    # nobody usefully did. They stay visible in `audits` and in
    # `auditor.precision`, which is where a Cell burning money to say nothing
    # belongs.
    rows = [r for r in _audit_rows(conn, request_id) if r["verdict"] is not None]
    if not rows:
        return None
    return "\n\n".join(
        f"[{row['verdict']}, p={row['probability']:.2f}] "
        f"{row['auditor_cell_id']}: {row['summary']}"
        for row in rows
    )


def payload(
    conn: sqlite3.Connection, request_id: str, *, now: datetime | None = None
) -> ApprovalPayload:
    """§23.2's approval payload, assembled from kernel facts.

    The evidence half deliberately comes from the hash-chained prediction
    register rather than from anything the Cell wrote in its proposal. That is
    not belt-and-braces: the first live paid deliberation abstained *because*
    §15 context showed the Cell its own unresolved record, which is the same
    evidence shown here — so the operator and the Cell are reading the same
    facts from the same tamper-evident source.
    """
    now = now or _now()
    request = get_request(conn, request_id)
    if request is None:
        raise ApprovalError(f"no such approval request: {request_id}")

    proposal_row = conn.execute(
        "SELECT * FROM proposals WHERE proposal_id = ?", (request.proposal_id,)
    ).fetchone()
    if proposal_row is None:
        raise ApprovalError(f"request {request_id} names a missing proposal")

    cell = lifecycle.get_cell(conn, request.cell_id)
    if cell is None:
        raise ApprovalError(f"request {request_id} names a missing cell")

    cost_row = conn.execute(
        """
        SELECT mc.cost_actual_micro_usd AS cost
          FROM deliberations d
          JOIN model_calls mc ON mc.model_call_id = d.model_call_id
         WHERE d.deliberation_id = ?
        """,
        (proposal_row["deliberation_id"],),
    ).fetchone()

    related = conn.execute(
        "SELECT COUNT(*) AS n FROM approval_requests WHERE aggregation_key = ? "
        "AND created_at_utc >= ?",
        (request.aggregation_key, _window_start(request.created_at_utc).isoformat()),
    ).fetchone()["n"]

    scores = prediction.scores(conn, request.cell_id)
    overdue_count = len(
        [p for p in prediction.overdue(conn, now=now) if p.cell_id == request.cell_id]
    )

    return ApprovalPayload(
        request=request,
        proposal=dict(proposal_row),
        estimated_cost_minor_units=int(proposal_row["estimated_cost_minor_units"]),
        book=cell.book,
        deliberation_cost_micro_usd=(
            int(cost_row["cost"]) if cost_row and cost_row["cost"] is not None else None
        ),
        exposure_minor_units=request.exposure_minor_units,
        related_request_count=related,
        liability_minor_units=None,
        cell_explanation=proposal_row["rationale"],
        auditor_summary=_auditor_summary(conn, request_id),
        audits=tuple(_audit_rows(conn, request_id)),
        resolved_prediction_count=int(scores.get("resolved", 0) or 0),
        unresolved_prediction_count=int(scores.get("unresolved", 0) or 0),
        overdue_prediction_count=overdue_count,
        mean_brier_score=scores.get("mean_brier"),
        signals=request.signals,
        current_cell_status=cell.status,
        overdue=request.is_overdue(now=now),
    )


# --- helpers -----------------------------------------------------------------


def _window_start(now: datetime) -> datetime:
    return now - timedelta(seconds=EXPOSURE_WINDOW_SECONDS)


def _window_requests(
    conn: sqlite3.Connection, *, aggregation_key: str, now: datetime
) -> list[sqlite3.Row]:
    """Requests on this key inside the rolling window that still count as exposure.

    Rejected requests are excluded: a rejected ask costs nothing and never
    will, so counting it would inflate a lineage's exposure forever on the
    strength of something the operator already refused. Repeating a rejected
    request is caught by `repeat_after_rejection` instead, which is the honest
    place for it.

    Expired ones are excluded for the same reason — nothing happened — while
    pending and approved both count, because both may still become real.
    """
    return conn.execute(
        """
        SELECT r.exposure_delta AS exposure_delta FROM (
            SELECT ar.request_id,
                   p.estimated_cost_minor_units AS exposure_delta
              FROM approval_requests ar
              JOIN proposals p ON p.proposal_id = ar.proposal_id
             WHERE ar.aggregation_key = ?
               AND ar.created_at_utc >= ?
               AND ar.status IN (?, ?)
        ) r
        """,
        (
            aggregation_key,
            _window_start(now).isoformat(),
            RequestStatus.PENDING,
            RequestStatus.APPROVED,
        ),
    ).fetchall()


def _sla_seconds(conn: sqlite3.Connection, tier: RiskTier) -> int:
    """§27.1's per-tier SLA, from the operator row."""
    column = {
        RiskTier.LOW: "approval_sla_low_seconds",
        RiskTier.MEDIUM: "approval_sla_medium_seconds",
        RiskTier.HIGH: "approval_sla_high_seconds",
        RiskTier.CRITICAL: "approval_sla_critical_seconds",
    }[tier]
    row = conn.execute(
        f"SELECT {column} AS sla FROM operator_state WHERE id = 1"
    ).fetchone()
    if row is None:
        # No operator configured. §23.3's vacation model reads an absent
        # operator as *never seen*, and the scheduler already treats that as
        # fail-safe; the strictest SLA is the consistent reading here.
        return _DEFAULT_SLA_SECONDS[tier]
    return int(row["sla"])


#: §27.1's literals, used only when no operator row exists.
_DEFAULT_SLA_SECONDS = {
    RiskTier.LOW: 86_400,
    RiskTier.MEDIUM: 14_400,
    RiskTier.HIGH: 3_600,
    RiskTier.CRITICAL: 900,
}


def _metabolic_alarm_cents(conn: sqlite3.Connection) -> int:
    """The operator's burn tolerance, which the exposure thresholds are scaled to.

    Read with a direct query rather than through `scheduler`: approval sits
    *above* deliberation, scheduler will later want to drive this queue, and
    importing scheduler from here would close that loop into a cycle.
    """
    row = conn.execute(
        "SELECT metabolic_alarm_cents_per_epoch AS cents FROM operator_state WHERE id = 1"
    ).fetchone()
    if row is None:
        return 50  # §27.1's default.
    return int(row["cents"])


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)
