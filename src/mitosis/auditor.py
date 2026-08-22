"""Auditor Cells (SPEC.md §23.2, §10.4, §0.3, §10.5, §29.10; Charter C8).

`approval.payload` has reported §23.2's "independent Auditor summary" as
unavailable since ADR-027, and correctly: the clause says *independent*, and
§0.3 forbids the proposing Cell writing its own. The `AUDITOR` type has been in
the taxonomy since Phase 1, and `death.kill_for_negative_ev` has always required
a concurring Auditor. What never existed was any way for an Auditor to actually
produce an audit. This module is that, and it closes the largest remaining hole
in the review path.

**§10.4 forbids the obvious Auditor.** The obvious one wakes, reads the
proposal, and writes prose flagging whatever looks risky. §10.4:

    Auditor reward is **precision-weighted**: reward valid detected errors,
    prevented loss, reproducible findings; penalise wrongful flags, excessive
    false positives, unnecessary blocking, unverified accusations.

and §29's acceptance criterion 10 is, in full, "Wrongful Auditor flags are
penalised". **Prose cannot be penalised.** An Auditor whose flags cost it
nothing will flag everything — maximally cautious, maximally uninformative, and
it looks responsible the whole time it is destroying the signal.

So every audit states a **probability**, registered as a §8.5 prediction before
the outcome is known. A flag resolves later through the hash-chained register
and scores with the same proper scoring rule every other Cell is judged by. A
wrongful flag lands in the Auditor's own calibration record — the currency
§25.2's read-back already uses — which makes §10.4's precision-weighting
computable from machinery that exists rather than from a new reputation system
invented here.

**The Auditor does not write the claim it is scored against.** `_canonical_claim`
composes it from the request. §0.3 applies to the independent evaluator as much
as to the proposer: an Auditor allowed to phrase its own claim would phrase an
unfalsifiable one and never be wrong. It supplies a probability and prose; the
kernel supplies the thing being predicted.

**What independence is enforced to mean.** Checked inside the write lock, since
each is a fact that can change between a read and a write:

    not the subject         §0.3, and the obvious hole.
    an AUDITOR Cell         §7's taxonomy; the type is the job.
    a different lineage     a parent auditing its child is not independent.
                            ADR-027 already established lineage as §23.4's
                            aggregation key, for the same reason: it is the
                            cheapest thing a Cell can split itself across.
    able to think           the same statuses that may deliberate. Dead is
                            Charter C8 and quarantined is §18.2 — a restricted
                            Cell whose word still moves capital is restricted
                            in name only. **Dormant is allowed**, because
                            §17.2's whole model is dormant Cells woken by
                            events, and an Auditor is idle between reviews by
                            construction.

**What actually makes it a second opinion rather than an echo.** A Cell running
the same prompt over the same context is not independent in any useful sense,
whatever the row says. The Auditor is shown what the subject *cannot see about
itself*: the subject's calibration record, its overdue count, its lineage's
cumulative exposure, and the kernel's **assessed** risk tier rather than the
tier the subject claimed. That asymmetry is the independence; the identity check
only stops the crudest violation.

**An audit advises; it never blocks.** §10.4 penalises "unnecessary blocking",
so nothing here vetoes an approval — `approve` does not consult audits, and a
structural test keeps it that way. The audit fills a field a human reads, which
is exactly what §23.2 asks for and no more. This is the same posture as ADR-030's
read-back: produce the evidence, let a person decide.

Deliberately out of scope, and logged rather than dropped:

    governance overhead ratio   §10.4's second half — (audit + immune +
                                approval spend) / total spend against a target
                                band. Auditing now costs money, so the ratio is
                                finally non-zero and worth building; it needs a
                                spend classification of its own.
    audit wakes on a schedule   `WAKE_AUDIT_REQUEST` is stamped for provenance
                                but an audit is operator-invoked. Auto-enqueuing
                                one means audits that spend money unattended,
                                and picking *which* Auditor is a policy nobody
                                has stated.
    Auditor reward flowing      §10.4 says reward; precision is measured here
                                and nothing pays it. §11's negative-finding
                                credit path is where that belongs.
    the §25.2 verdict           an Auditor is the one legitimate consumer of
                                `outcome.assess`, but reading it would mean
                                loosening `test_no_kernel_path_acts_on_an_assessment`
                                — an argued step, not a convenience.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import (
    approval,
    audit as audit_log,
    deliberation,
    gateway,
    ids,
    lifecycle,
    prediction,
    proposal as proposal_module,
    providers,
)
from .models import Cell, CellStatus, CellType

MAX_SUMMARY_CHARS = 1_200

#: How long an audit's claim runs before it is due. Longer than a proposal's
#: default horizon on purpose: the Auditor is predicting whether the *approved
#: action* works out, which cannot be known before the action has had time to.
DEFAULT_HORIZON_DAYS = 30

#: A `concern` verdict asserting a >50% chance of success is incoherent, and
#: refusing it is what stops an Auditor hedging into a costless flag — raising
#: the alarm for the operator while quietly predicting the opposite for its own
#: score.
_COHERENCE_MIDPOINT = 0.5

#: Auditors may audit. §10.4 pairs Auditor and Immune fitness and both are
#: oversight roles, so an Immune Cell auditing is coherent; a Commercial Cell
#: auditing the competitor whose capital it wants is not.
AUDITING_TYPES = frozenset({CellType.AUDITOR, CellType.IMMUNE})

#: Statuses that may audit. Deliberately *the same set* that may deliberate
#: rather than a stricter one: an audit is a wake like any other, and §17.2's
#: model is dormant Cells woken by events. An Auditor that had to be kept awake
#: to be usable would be an Auditor the colony pays to idle, and requiring
#: ALIVE here would have made the golden run's own (sleeping) Auditor unable to
#: do the one job its type exists for.
_CAN_AUDIT = deliberation._CAN_DELIBERATE


class AuditError(Exception):
    pass


class Verdict(StrEnum):
    CONCERN = "concern"
    NO_CONCERN = "no_concern"


class AuditReply(BaseModel):
    """What an Auditor is allowed to say. Strict, like `proposal.Proposal`.

    Note what is absent: any field naming an outcome, a cost, or a score. §0.3
    binds the evaluator too — the Auditor judges a proposal, it does not get to
    record what happened.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Verdict
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY_CHARS)
    probability: float = Field(gt=0.0, lt=1.0)


#: An audit that produced no usable opinion. Recorded rather than raised
#: because the model call is already paid for by the time the reply is parsed
#: — see migration 0018.
STATUS_RECORDED = "recorded"
STATUS_REJECTED = "rejected"


@dataclass(frozen=True)
class Audit:
    audit_id: str
    request_id: str
    proposal_id: str
    auditor_cell_id: str
    subject_cell_id: str
    status: str
    verdict: Verdict | None
    summary: str | None
    probability: float | None
    prediction_id: str | None
    failure_reason: str | None
    model_call_id: str | None
    wake_reason: str
    created_at_utc: datetime

    @property
    def is_recorded(self) -> bool:
        return self.status == STATUS_RECORDED

    @property
    def raised_a_flag(self) -> bool:
        return self.verdict is Verdict.CONCERN


@dataclass(frozen=True)
class Precision:
    """§10.4's precision-weighted Auditor record, not collapsed to a score.

    §10.2 forbids one scalar, and here that matters more than usual: precision
    alone is trivially maximised by never flagging anything, so it is reported
    beside the flag counts and the calibration mean that would expose exactly
    that strategy.
    """

    auditor_cell_id: str
    audits: int
    #: Replies that produced no usable opinion. Counted because an Auditor that
    #: reliably emits garbage is spending the colony's money to say nothing,
    #: which is a §10.4 fitness fact and would otherwise be invisible.
    rejected: int
    flags_raised: int
    flags_resolved: int
    flags_vindicated: int
    wrongful_flags: int
    mean_brier: float | None
    resolved_audits: int

    @property
    def flag_precision(self) -> float | None:
        """Valid detections over all resolved flags. None when nothing has
        resolved — an Auditor with no resolved flags is unmeasured, not
        perfect, and reporting 1.0 would say the opposite."""
        decided = self.flags_vindicated + self.wrongful_flags
        return self.flags_vindicated / decided if decided else None


# --- the prompt --------------------------------------------------------------


def _response_schema_hint() -> str:
    return json.dumps(_prompt_schema(), indent=2, sort_keys=True)


def _prompt_schema() -> dict[str, Any]:
    """Enum choices rendered as a string, never a JSON array — reusing
    `proposal._one_of` rather than re-deriving it.

    That rendering was a real bug, found only on the first live model run:
    `"risk_tier": ["MEDIUM"]`, a correct choice in the wrong shape, because the
    prompt showed the field as a list. A second copy of the fix here would mean
    the next correction lands in one file and not the other.
    """
    return {
        "verdict": proposal_module._one_of(Verdict),
        "summary": (
            f"REQUIRED string, 1-{MAX_SUMMARY_CHARS} chars. What the operator "
            "needs to know that the proposing Cell would not tell them."
        ),
        "probability": (
            "REQUIRED number strictly between 0 and 1 (never 0 or 1): your "
            "probability that this request achieves what it claims. This is "
            "scored against what actually happens."
        ),
    }


def _system_prompt() -> str:
    """Fixed kernel text. The Auditor's genome never reaches these instructions,
    for the reason `deliberation._system_prompt` gives: a Cell that could
    rewrite the rules it is judged against is not being judged."""
    return (
        "You are an Auditor Cell in the MITOSIS colony. Another Cell has asked "
        "the human operator to approve an action. Your job is to give the "
        "operator an independent second opinion.\n\n"
        "You are not deciding anything. You cannot approve, block, or delay "
        "this request — the operator decides, and they will read what you "
        "write.\n\n"
        "**Your flag is scored.** The probability you state is registered "
        "before the outcome is known, hash-chained, and scored with a proper "
        "scoring rule. Raising a concern about something that then works out "
        "counts against you exactly as much as missing something that fails. "
        "Flagging everything is not caution, it is noise, and it is penalised.\n\n"
        "Reply with ONE JSON object and nothing else — no prose before or "
        "after. It must match this schema exactly. Every REQUIRED field must be "
        "present, and unknown fields are rejected:\n\n"
        f"{_response_schema_hint()}\n\n"
        "Guidance:\n"
        "- Use 'concern' only when you would genuinely expect this to go badly, "
        "and state a probability below 0.5 when you do.\n"
        "- 'no_concern' is the honest answer for a sound request, and it is not "
        "a failure to find something.\n"
        "- Point at the evidence below, not at generalities. The operator can "
        "already see the numbers; tell them what the numbers mean."
    )


def _brief(
    conn: sqlite3.Connection, detail: approval.ApprovalPayload, subject: Cell
) -> str:
    """What the Auditor is shown.

    Assembled from kernel facts, and deliberately including the things the
    subject Cell cannot see about itself — its own calibration record as the
    kernel computes it, and the tier the kernel *assessed* rather than the one
    the subject claimed. Showing the claimed tier alone would let a Cell frame
    its own audit (§23.5).
    """
    request = detail.request
    lines = [
        "# The request under review",
        f"kind: {detail.proposal['kind']}",
        f"summary: {detail.proposal['summary']}",
        f"the proposing Cell's own rationale: {detail.cell_explanation}",
        "",
        "# What the kernel says about it",
        f"claimed risk tier: {request.claimed_tier.value}",
        f"assessed risk tier: {request.assessed_tier.value}  "
        "(the kernel's own, which the proposing Cell cannot set)",
        f"estimated cost: {detail.estimated_cost_minor_units} {detail.book.value}",
        f"cumulative exposure for this lineage: {detail.exposure_minor_units}",
        f"related requests in the window: {detail.related_request_count}",
        f"reversible: {request.reversible}",
        "anti-gaming signals the kernel raised (§23.4): "
        + (
            "; ".join(f"{s.signal} — {s.detail}" for s in detail.signals)
            or "none"
        ),
        "",
        "# The proposing Cell's track record (from the hash-chained register)",
        f"cell type: {subject.cell_type.value}",
        f"resolved predictions: {detail.resolved_prediction_count}",
        f"unresolved: {detail.unresolved_prediction_count}",
        f"overdue and unresolved: {detail.overdue_prediction_count}",
        f"mean Brier score: "
        f"{'n/a' if detail.mean_brier_score is None else round(detail.mean_brier_score, 4)}"
        "  (0.25 is what always answering 0.5 scores)",
    ]
    return "\n".join(lines)


def _canonical_claim(detail: approval.ApprovalPayload) -> str:
    """The claim the Auditor's probability is scored against.

    Composed by the kernel, never by the Auditor. §0.3 binds the independent
    evaluator too: an Auditor phrasing its own claim would phrase one that
    cannot come out false.
    """
    return (
        f"approval request {detail.request.request_id} "
        f"({detail.proposal['kind']}, {detail.estimated_cost_minor_units} "
        f"{detail.book.value}) achieves what its proposal claims"
    )


# --- performing an audit -----------------------------------------------------


def audit_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    auditor_cell_id: str,
    provider: providers.ModelProvider,
    model: str,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    max_tokens: int = deliberation.DEFAULT_MAX_TOKENS,
    idempotency_key: str | None = None,
) -> Audit:
    """Have one Auditor Cell audit one pending approval request.

    Idempotent on the audit key (Charter C6): a redelivered call returns the
    existing audit rather than buying a second model call and writing a second
    opinion from the same Cell.

    Operator-invoked. Nothing schedules this — an audit costs a model call, and
    a colony that audits on a timer is spending money unattended.
    """
    key = idempotency_key or f"audit:{request_id}:{auditor_cell_id}"
    existing = get_audit_by_idempotency_key(conn, key)
    if existing is not None:
        return existing

    detail = approval.payload(conn, request_id)
    if detail.request.status != approval.RequestStatus.PENDING:
        raise AuditError(
            f"request {request_id} is {detail.request.status}; auditing a decided "
            "request would produce evidence for a decision already taken"
        )

    auditor = _validated_auditor(conn, auditor_cell_id=auditor_cell_id, detail=detail)
    subject = lifecycle.get_cell(conn, detail.request.cell_id)
    if subject is None:
        raise AuditError(f"request {request_id} names a missing cell")

    unfunded = deliberation._unfunded_books(conn, auditor)
    if unfunded:
        raise AuditError(
            f"auditor {auditor_cell_id} cannot pay for its own thinking (§15.4): "
            f"no balance in {', '.join(unfunded)}"
        )

    # Outside every transaction below: ADR-022 requires the gateway's
    # reservation to commit before the external call.
    call = gateway.call_model(
        conn,
        cell_id=auditor.cell_id,
        provider=provider,
        request=providers.ModelRequest(
            model=model,
            messages=(
                {
                    "role": "user",
                    "content": f"{_system_prompt()}\n\n{_brief(conn, detail, subject)}",
                },
            ),
            max_tokens=max_tokens,
        ),
        idempotency_key=f"audit:{key}",
    )

    try:
        reply = _parse(call.response_text or "")
    except AuditError as exc:
        # The call is bought and committed by now (ADR-022), so the failure is
        # recorded rather than raised: real spend with no record of what it
        # bought is the one outcome worse than a bad audit.
        return _record_rejected(
            conn,
            detail=detail,
            auditor=auditor,
            reason=str(exc),
            model_call_id=call.model_call_id,
            idempotency_key=key,
        )

    return _record(
        conn,
        detail=detail,
        auditor=auditor,
        reply=reply,
        model_call_id=call.model_call_id,
        horizon_days=horizon_days,
        idempotency_key=key,
    )


def _validated_auditor(
    conn: sqlite3.Connection, *, auditor_cell_id: str, detail: approval.ApprovalPayload
) -> Cell:
    """§23.2's "independent", made specific. See the module docstring."""
    auditor = lifecycle.get_cell(conn, auditor_cell_id)
    if auditor is None:
        raise AuditError(f"no such auditor cell: {auditor_cell_id}")

    if auditor.cell_id == detail.request.cell_id:
        raise AuditError(
            "a Cell cannot audit its own request — §23.2 requires an *independent* "
            "summary and §0.3 forbids a Cell defining the canonical account of its "
            "own work"
        )

    if auditor.cell_type not in AUDITING_TYPES:
        raise AuditError(
            f"cell {auditor_cell_id} is a {auditor.cell_type.value}; only "
            f"{'/'.join(sorted(t.value for t in AUDITING_TYPES))} Cells audit "
            "(§10.4 pairs Auditor and Immune as the oversight roles)"
        )

    if auditor.founder_cell_id == detail.request.founder_cell_id:
        raise AuditError(
            f"auditor {auditor_cell_id} shares lineage {auditor.founder_cell_id} with "
            "the Cell under review — a relative is not an independent evaluator, and "
            "lineage is already §23.4's aggregation key for the same reason"
        )

    if auditor.status not in _CAN_AUDIT:
        raise AuditError(
            f"auditor {auditor_cell_id} is {auditor.status.value} and cannot audit "
            "(Charter C8 for dead; §18.2 for quarantined — a restricted Cell whose "
            "word still moves capital is restricted in name only)"
        )
    return auditor


def _parse(raw_text: str) -> AuditReply:
    """Strict, and never salvaged into a best effort.

    Raises, and `audit_request` turns that into a *recorded* rejection rather
    than propagating it — the reply is refused, but the fact that an Auditor
    bought a model call and produced nothing usable is kept. Strictness here
    and recording there are the same policy `deliberation` applies: never
    repair a half-understood judgement, always remember that it happened.
    """
    text = proposal_module._strip_code_fence(raw_text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuditError(f"audit reply is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AuditError(f"audit reply must be a JSON object, got {type(payload).__name__}")

    try:
        reply = AuditReply.model_validate(payload)
    except ValidationError as exc:
        raise AuditError(proposal_module._summarise_validation_error(exc)) from exc

    if reply.verdict is Verdict.CONCERN and reply.probability > _COHERENCE_MIDPOINT:
        raise AuditError(
            f"incoherent audit: verdict 'concern' with probability {reply.probability} "
            "that the request succeeds. A flag that predicts success is a costless "
            "flag — it alarms the operator while scoring as if it had not (§10.4)"
        )
    if reply.verdict is Verdict.NO_CONCERN and reply.probability < _COHERENCE_MIDPOINT:
        raise AuditError(
            f"incoherent audit: verdict 'no_concern' with probability "
            f"{reply.probability} that the request succeeds. Say 'concern' if that "
            "is what you believe"
        )
    return reply


def _record_rejected(
    conn: sqlite3.Connection,
    *,
    detail: approval.ApprovalPayload,
    auditor: Cell,
    reason: str,
    model_call_id: str | None,
    idempotency_key: str,
) -> Audit:
    """An Auditor bought a model call and produced nothing usable.

    Recorded, never raised. By this point the gateway has committed (ADR-022),
    so the money is spent — and real spend with no record of what it bought is
    strictly worse than a bad audit. It also keeps an Auditor that reliably
    emits garbage visible, which `precision` counts and §10.4 would otherwise
    have no way to see.

    No prediction is registered, because there is no probability to register.
    That is why `precision` counts these separately rather than folding them
    into the flag counts: a rejected reply is neither a flag nor a clearance.
    """
    now = datetime.now(timezone.utc)
    audit_id = ids.new_id()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO audits (
                audit_id, request_id, proposal_id, auditor_cell_id, subject_cell_id,
                status, failure_reason, verdict, summary, probability, prediction_id,
                model_call_id, wake_reason, created_at_utc, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                audit_id,
                detail.request.request_id,
                detail.request.proposal_id,
                auditor.cell_id,
                detail.request.cell_id,
                STATUS_REJECTED,
                reason,
                model_call_id,
                deliberation.WAKE_AUDIT_REQUEST,
                now.isoformat(),
                idempotency_key,
            ),
        )
        audit_log.record(
            conn,
            event_type="audit_rejected",
            cell_id=auditor.cell_id,
            description=reason[:200],
            metadata={
                "audit_id": audit_id,
                "request_id": detail.request.request_id,
                "model_call_id": model_call_id,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_audit(conn, audit_id)
    assert result is not None
    return result


def _record(
    conn: sqlite3.Connection,
    *,
    detail: approval.ApprovalPayload,
    auditor: Cell,
    reply: AuditReply,
    model_call_id: str | None,
    horizon_days: int,
    idempotency_key: str,
) -> Audit:
    """Write the audit and register its prediction in one transaction.

    Folded together for the reason `deliberation._record_proposal` folds its
    own: an audit whose prediction failed to register would be a flag with no
    score attached, which is precisely the costless flag §10.4 forbids — and it
    would fail *open*, leaving the Auditor with the operator's attention and
    none of the risk.
    """
    now = datetime.now(timezone.utc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        registered = prediction._register_locked(
            conn,
            cell_id=auditor.cell_id,
            claim=_canonical_claim(detail),
            probability=reply.probability,
            resolves_by=now + timedelta(days=horizon_days),
            idempotency_key=f"audit-flag:{idempotency_key}",
        )

        audit_id = ids.new_id()
        conn.execute(
            """
            INSERT INTO audits (
                audit_id, request_id, proposal_id, auditor_cell_id, subject_cell_id,
                status, failure_reason, verdict, summary, probability, prediction_id,
                model_call_id, wake_reason, created_at_utc, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                detail.request.request_id,
                detail.request.proposal_id,
                auditor.cell_id,
                detail.request.cell_id,
                STATUS_RECORDED,
                reply.verdict.value,
                reply.summary.strip(),
                reply.probability,
                registered.prediction_id,
                model_call_id,
                deliberation.WAKE_AUDIT_REQUEST,
                now.isoformat(),
                idempotency_key,
            ),
        )
        audit_log.record(
            conn,
            event_type="request_audited",
            cell_id=auditor.cell_id,
            description=reply.summary.strip()[:200],
            metadata={
                "audit_id": audit_id,
                "request_id": detail.request.request_id,
                "subject_cell_id": detail.request.cell_id,
                "verdict": reply.verdict.value,
                "probability": reply.probability,
                "prediction_id": registered.prediction_id,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_audit(conn, audit_id)
    assert result is not None
    return result


# --- reading -----------------------------------------------------------------


def get_audit(conn: sqlite3.Connection, audit_id: str) -> Audit | None:
    row = conn.execute("SELECT * FROM audits WHERE audit_id = ?", (audit_id,)).fetchone()
    return _row_to_audit(row) if row else None


def get_audit_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> Audit | None:
    row = conn.execute(
        "SELECT * FROM audits WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return _row_to_audit(row) if row else None


def audits_for_request(conn: sqlite3.Connection, request_id: str) -> list[Audit]:
    rows = conn.execute(
        "SELECT * FROM audits WHERE request_id = ? ORDER BY rowid", (request_id,)
    ).fetchall()
    return [_row_to_audit(r) for r in rows]


def _row_to_audit(row: sqlite3.Row) -> Audit:
    return Audit(
        audit_id=row["audit_id"],
        request_id=row["request_id"],
        proposal_id=row["proposal_id"],
        auditor_cell_id=row["auditor_cell_id"],
        subject_cell_id=row["subject_cell_id"],
        status=row["status"],
        verdict=Verdict(row["verdict"]) if row["verdict"] else None,
        summary=row["summary"],
        probability=row["probability"],
        prediction_id=row["prediction_id"],
        failure_reason=row["failure_reason"],
        model_call_id=row["model_call_id"],
        wake_reason=row["wake_reason"],
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
    )


def precision(conn: sqlite3.Connection, auditor_cell_id: str) -> Precision:
    """§10.4's precision-weighted record for one Auditor.

    A flag is **vindicated** when the Auditor said `concern` and the request's
    claim resolved false — a valid detected error. It is **wrongful** when it
    said `concern` and the claim resolved true, which is §10.4's "wrongful
    flag" and §29's acceptance criterion 10 exactly.

    Reported alongside the counts and the calibration mean rather than as a
    single number, because precision on its own is maximised by never flagging
    anything and would rank a silent Auditor top.
    """
    # LEFT JOIN, so a rejected audit (which has no prediction) still appears.
    # An INNER JOIN here would make garbage replies invisible, which is the
    # opposite of what §10.4 wants from a fitness signal.
    rows = conn.execute(
        """
        SELECT a.status AS status, a.verdict AS verdict, p.outcome AS outcome,
               p.brier_score AS brier, p.resolved_at_utc AS resolved
          FROM audits a
          LEFT JOIN prediction_register p ON p.prediction_id = a.prediction_id
         WHERE a.auditor_cell_id = ?
        """,
        (auditor_cell_id,),
    ).fetchall()

    flags = [r for r in rows if r["verdict"] == Verdict.CONCERN.value]
    resolved_flags = [r for r in flags if r["resolved"] is not None]
    briers = [r["brier"] for r in rows if r["brier"] is not None]

    return Precision(
        auditor_cell_id=auditor_cell_id,
        audits=len(rows),
        rejected=len([r for r in rows if r["status"] == STATUS_REJECTED]),
        flags_raised=len(flags),
        flags_resolved=len(resolved_flags),
        # The claim is "the request achieves what it claims". A concern that
        # was right is therefore a claim that resolved *false*.
        flags_vindicated=len([r for r in resolved_flags if not r["outcome"]]),
        wrongful_flags=len([r for r in resolved_flags if r["outcome"]]),
        mean_brier=(sum(briers) / len(briers)) if briers else None,
        resolved_audits=len([r for r in rows if r["resolved"] is not None]),
    )
