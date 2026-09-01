"""The Auditor path for §13.3/§13.4's content judgments (SPEC.md §13.3, §13.4,
§10.4, §0.3, §29.10, §12.1, §12.2; ADR-032, ADR-058, ADR-062, ADR-064).

ADR-062 built §12.1's third archive dimension and drew a line on purpose:
`buyer_type` is an *external fact* an operator can observe, so a human
attestation (`counterparty.attest_buyer_type`) fits. Two other judgments were
left on the other side of that line, both readings of a Cell's own prose
rather than facts about the world:

    §13.3 Program-native advantage.  Weight novelty higher when it relies on
    large-scale iteration, continuous monitoring, machine-to-machine commerce,
    microtransactions, personalised output, combinatorial search, automatic
    code generation, cross-source coordination, or extremely low marginal cost.

    §13.4 Fake-novelty detection.  Flag ideas where only the industry label
    changed, ordinary freelancing is described exotically, the same mechanism
    is renamed, or no new capability/transaction structure exists.

`auditor.py` already built exactly the machinery §10.4 demands for a content
judgment — independence checks, a kernel-composed claim, a probability
registered before the outcome is known and scored with a proper rule — but
its one subject is an `approval_request`. Two of §13.4's four flags and all of
§13.3 are not about a request; they are about a **genome**, and §13.4's third
flag needs a **pair** of genomes. This module is that second subject, built
the same way `buyer_attestations` copied `rights_attestations`' shape rather
than generalising `audits` into something that has to serve both — see
`docs/DECISIONS.md`'s ADR-041/ADR-062 precedent.

## What is judged here, and what already is not

§13.4 names four flags. Two are already answered without an Auditor:

    only the industry label changed   structural (`novelty.only_the_label_
                                       changed`) — the nearest earlier genome
                                       differing in `market` alone.
    no new capability/transaction     `scripts/concreteness.py` (ADR-058), an
    structure exists                  *offline* measurement tool, deliberately
                                       outside the kernel and unscored — built
                                       before this module existed to give a
                                       researcher a lower bound across arms,
                                       not to give one genome a probability.

The other two — "ordinary freelancing described exotically" and "the same
mechanism is renamed" — plus the whole of §13.3, have no structural test:
telling program-native substance from a well-written description of ordinary
work, or telling a new mechanism from an old one in new words, is exactly the
judgment call §0.3 reserves for "a human (§23) or an independent Auditor
(§10.4)" and forbids both the Cell and the kernel from making unaided.

## One genome, one pair, one table

`software_native_advantage` judges a single genome: does it genuinely exhibit
§13.3's characteristics, as opposed to being §13.4's "ordinary freelancing
described exotically"? The two readings are the same underlying question
looked at from either side, so one scored claim covers both — an Auditor who
believes the business is ordinary work in fancy language states a low
probability that it "genuinely relies on a §13.3 characteristic", exactly the
`concern` verdict this shares with `auditor.py`.

`renamed_mechanism` judges a **pair**: is `genome_hash` genuinely a distinct
mechanism from `compared_genome_hash`, or the same one renamed? ADR-058 could
not build this flag because it "needs a *prior*... and §31's `novelty_archive`
... is where that prior would live" — the archive now exists (ADR-060), so an
operator can name the pair worth comparing.

Both live in `genome_content_audits`, split by a `kind` column rather than two
tables — the same shape `promotions.rung` already uses to keep two variants of
one mechanism together (migration 0031's own comment has the full reasoning).

## Independence, generalised from a Cell to a genome

`auditor.py` checks the auditor is not the subject Cell, and shares no lineage
with it. A genome has no single subject Cell — it is content-addressed and may
be carried by zero, one, or many Cells, dead or alive, across any number of
lineages. So the check here is over the genome directly (an Auditor whose own
current genome *is* the one under review cannot judge it — the same §0.3
argument, generalised) and over every Cell that has ever carried either genome
under review (an Auditor sharing a lineage founder with any of them is not
independent, mirroring `auditor._validated_auditor`'s reasoning applied to a
set rather than one row).

**This independence check is close to unreachable today, on purpose, and
temporarily.** `novelty.py`'s own docstring is explicit: "today the descriptor
is derived from genome content, and genome content is written by an operator
passing `--mutation`; no Cell writes its own." So in this kernel an Auditor's
current genome coinciding with the genome under review, or an Auditor sharing
lineage with a genome's carriers, are both edge cases rather than the routine
hazard `auditor.py` guards against — until §14's automated mutation changes
who writes genomes, the same tell `novelty.py` names for its own safety
argument.

## What this deliberately does not do

**Nothing consumes a content audit yet.** `selection.py`'s `software_native_
advantage` gate reports `UNMEASURABLE` unconditionally — this module makes it
*measurable*, and wiring the gate to read a resolved audit is a deliberate
next step, not this one (logged in FUTURE_BUILD_HOOKS). Reading an
*unresolved* prediction into a gate would be scoring a candidate on an
Auditor's opinion before the register has judged the Auditor, which is
precisely the "estimated negative EV" shape §10.5 exists to keep out of an
automatic decision.

**No combined precision record across both audit kinds.** `precision()` here
reports only `genome_content_audits`; `auditor.precision()` reports only
`audits`. §10.4's fitness signal for one Auditor Cell is therefore currently
split across two calls rather than one merged view — correct today (the two
mechanisms are young and independently useful to inspect), logged as a future
merge rather than built speculatively.

**Never reaches a Cell.** §23.5: a Cell that could see it is scored on
"genuine program-native advantage" or "not a renamed mechanism" learns to
perform novelty rather than have it. `test_a_content_audit_never_reaches_a_
cell` closes `context.py` and `deliberation.py` the same way `auditor.py`'s
brief is built only from kernel-observed facts.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import audit as audit_log, deliberation, gateway, ids, lifecycle, novelty, prediction
from . import proposal as proposal_module
from . import providers
from .models import Cell, CellType

MAX_SUMMARY_CHARS = 1_200

#: Longer than a proposal's default horizon, matching `auditor.py`'s reasoning:
#: whether a genome "genuinely" has program-native advantage, or whether two
#: genomes are genuinely distinct mechanisms, is not knowable the instant the
#: claim is made — it needs the Cells carrying it to have operated for a while.
DEFAULT_HORIZON_DAYS = 30

#: A `concern` verdict paired with a probability above one half that the
#: genuine-claim holds is incoherent, for the identical reason
#: `auditor._COHERENCE_MIDPOINT` exists: it would let an Auditor raise a flag
#: for the operator while quietly predicting the opposite for its own score.
_COHERENCE_MIDPOINT = 0.5

#: §10.4 pairs Auditor and Immune as the oversight roles; both may judge
#: content the same way both may judge a request in `auditor.py`.
AUDITING_TYPES = frozenset({CellType.AUDITOR, CellType.IMMUNE})

#: The same statuses `auditor._CAN_AUDIT` uses — an audit is a wake like any
#: other, and a dormant Auditor is idle between reviews by construction.
_CAN_AUDIT = deliberation._CAN_DELIBERATE


class ContentAuditError(Exception):
    pass


class Kind(StrEnum):
    """Which §13 judgment a row is. See the module docstring for the split."""

    SOFTWARE_NATIVE_ADVANTAGE = "software_native_advantage"
    RENAMED_MECHANISM = "renamed_mechanism"


class Verdict(StrEnum):
    CONCERN = "concern"
    NO_CONCERN = "no_concern"


class ContentAuditReply(BaseModel):
    """What an Auditor may say about a genome or a genome pair. Strict, like
    `auditor.AuditReply` — the same shape, because the judgment being scored
    (a probability that a genuine-claim holds, plus what the operator should
    know) is identical; only the claim it is scored against differs by kind.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Verdict
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY_CHARS)
    probability: float = Field(gt=0.0, lt=1.0)


STATUS_RECORDED = "recorded"
STATUS_REJECTED = "rejected"


@dataclass(frozen=True)
class GenomeContentAudit:
    audit_id: str
    kind: Kind
    genome_hash: str
    compared_genome_hash: str | None
    auditor_cell_id: str
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
    """§10.4's precision-weighted record, over `genome_content_audits` alone.
    See the module docstring on why this is not merged with `auditor.Precision`.
    """

    auditor_cell_id: str
    audits: int
    rejected: int
    flags_raised: int
    flags_resolved: int
    flags_vindicated: int
    wrongful_flags: int
    mean_brier: float | None
    resolved_audits: int

    @property
    def flag_precision(self) -> float | None:
        decided = self.flags_vindicated + self.wrongful_flags
        return self.flags_vindicated / decided if decided else None


# --- genome content, read for the brief ---------------------------------------


def _genome_record(conn: sqlite3.Connection, genome_hash: str) -> novelty.GenomeRecord:
    row = conn.execute(
        "SELECT genome_hash, created_at, canonical_genome_json FROM cell_genomes "
        "WHERE genome_hash = ?",
        (genome_hash,),
    ).fetchone()
    if row is None:
        raise ContentAuditError(f"no such genome: {genome_hash}")
    return novelty.GenomeRecord(
        genome_hash=row["genome_hash"],
        created_at=row["created_at"],
        content=json.loads(row["canonical_genome_json"]),
    )


def _genome_lines(record: novelty.GenomeRecord, *, label: str) -> list[str]:
    lines = [f"# {label} (genome {record.genome_hash[:12]}…)"]
    for field in sorted(novelty.NOVELTY_FIELDS):
        lines.append(f"{field}: {record.content.get(field, '(absent)')}")
    return lines


# --- the prompt ----------------------------------------------------------------


def _response_schema_hint() -> str:
    return json.dumps(_prompt_schema(), indent=2, sort_keys=True)


def _prompt_schema() -> dict[str, Any]:
    return {
        "verdict": proposal_module._one_of(Verdict),
        "summary": (
            f"REQUIRED string, 1-{MAX_SUMMARY_CHARS} chars. What the operator "
            "needs to know that the raw content below would not tell them."
        ),
        "probability": (
            "REQUIRED number strictly between 0 and 1 (never 0 or 1): your "
            "probability that the claim below is true. This is scored against "
            "what is actually observed."
        ),
    }


def _claim_and_system_prompt(
    kind: Kind, *, genome_hash: str, compared_genome_hash: str | None
) -> tuple[str, str]:
    """The canonical claim and the fixed system prompt, together — both are a
    function of `kind` alone, and keeping them beside each other stops the
    claim drifting out of sync with what the prompt actually asks."""
    if kind is Kind.SOFTWARE_NATIVE_ADVANTAGE:
        claim = (
            f"genome {genome_hash} genuinely relies on at least one of §13.3's "
            "program-native characteristics (large-scale iteration, continuous "
            "monitoring, machine-to-machine commerce, microtransactions, "
            "personalised output, combinatorial search, automatic code "
            "generation, cross-source coordination, or extremely low marginal "
            "cost) — rather than being ordinary freelancing described "
            "exotically (§13.4)"
        )
        task = (
            "Judge ONE genome below against SPEC.md §13.3 and §13.4:\n\n"
            "§13.3 Program-native advantage. Weight novelty higher when it "
            "relies on large-scale iteration, continuous monitoring, "
            "machine-to-machine commerce, microtransactions, personalised "
            "output, combinatorial search, automatic code generation, "
            "cross-source coordination, or extremely low marginal cost.\n\n"
            "§13.4 Fake-novelty detection (the flag this judgment covers): "
            "ordinary freelancing is described exotically."
        )
    else:
        claim = (
            f"genome {genome_hash} is genuinely a distinct business mechanism "
            f"from genome {compared_genome_hash} — not the same mechanism "
            "renamed under different language (§13.4)"
        )
        task = (
            "Judge a PAIR of genomes below against SPEC.md §13.4:\n\n"
            "§13.4 Fake-novelty detection (the flag this judgment covers): "
            "the same mechanism is renamed."
        )
    prompt = (
        "You are an Auditor Cell in the MITOSIS colony. An operator has asked "
        "you to give an independent second opinion on a business idea's "
        "content — never on whether to fund it, only on whether the idea is "
        "what it claims to be.\n\n"
        "You are not deciding anything. You cannot approve, block, or change "
        "anything about the genome — the operator reads what you write.\n\n"
        "**Your probability is scored.** It is registered before the outcome "
        "is known, hash-chained, and scored with a proper scoring rule. "
        "Flagging something that then holds up counts against you exactly as "
        "much as clearing something that does not. Flagging everything is not "
        "caution, it is noise, and it is penalised (§10.4).\n\n"
        f"{task}\n\n"
        "The claim you are stating a probability for:\n"
        f"    {claim}\n\n"
        "Reply with ONE JSON object and nothing else — no prose before or "
        "after. It must match this schema exactly. Every REQUIRED field must "
        "be present, and unknown fields are rejected:\n\n"
        f"{_response_schema_hint()}\n\n"
        "Guidance:\n"
        "- Use 'concern' when you would flag this to the operator, and state a "
        "probability below 0.5 when you do.\n"
        "- 'no_concern' is the honest answer when the content holds up, and it "
        "is not a failure to find nothing.\n"
        "- Point at the specific words that support your view, not at "
        "generalities. A model can describe anything in program-native "
        "language; look for whether the mechanism itself is one."
    )
    return claim, prompt


def _brief(
    conn: sqlite3.Connection, *, kind: Kind, genome_hash: str, compared_genome_hash: str | None
) -> str:
    record = _genome_record(conn, genome_hash)
    if kind is Kind.SOFTWARE_NATIVE_ADVANTAGE:
        lines = _genome_lines(record, label="The genome under review")
        label = novelty.only_the_label_changed(conn, genome_hash)
        lines.append("")
        lines.append(
            "§13.4's structural flag (kernel-computed, not an opinion): "
            + (
                f"this genome differs from an earlier one ({label[:12]}…) in "
                "`market` alone — the industry label may be all that changed"
                if label
                else "no earlier genome differs from this one in `market` alone"
            )
        )
        return "\n".join(lines)

    assert compared_genome_hash is not None
    compared = _genome_record(conn, compared_genome_hash)
    diff = novelty.field_differences(record.content, compared.content)
    lines = [
        *_genome_lines(record, label="Genome A"),
        "",
        *_genome_lines(compared, label="Genome B"),
        "",
        "# What differs structurally (kernel-computed, not an opinion)",
        f"fields that differ: {', '.join(sorted(diff)) or '(none — identical business hypothesis)'}",
    ]
    return "\n".join(lines)


# --- performing an audit --------------------------------------------------------


def audit_genome(
    conn: sqlite3.Connection,
    *,
    genome_hash: str,
    auditor_cell_id: str,
    provider: providers.ModelProvider,
    model: str,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    max_tokens: int = deliberation.DEFAULT_MAX_TOKENS,
    idempotency_key: str | None = None,
) -> GenomeContentAudit:
    """§13.3 (and §13.4's "ordinary freelancing described exotically"): does
    this genome genuinely have program-native advantage?

    Operator-invoked, like `auditor.audit_request` — nothing schedules this,
    because an audit costs a model call and a colony that audits on a timer is
    spending money unattended.
    """
    key = idempotency_key or f"content-audit:{Kind.SOFTWARE_NATIVE_ADVANTAGE.value}:{genome_hash}:{auditor_cell_id}"
    return _audit(
        conn,
        kind=Kind.SOFTWARE_NATIVE_ADVANTAGE,
        genome_hash=genome_hash,
        compared_genome_hash=None,
        auditor_cell_id=auditor_cell_id,
        provider=provider,
        model=model,
        horizon_days=horizon_days,
        max_tokens=max_tokens,
        idempotency_key=key,
    )


def audit_genome_pair(
    conn: sqlite3.Connection,
    *,
    genome_hash: str,
    compared_genome_hash: str,
    auditor_cell_id: str,
    provider: providers.ModelProvider,
    model: str,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    max_tokens: int = deliberation.DEFAULT_MAX_TOKENS,
    idempotency_key: str | None = None,
) -> GenomeContentAudit:
    """§13.4: is this genome a genuinely distinct mechanism from the compared
    one, or the same mechanism renamed?

    `compared_genome_hash` is always operator-named — the kernel does not
    guess which pair is suspicious. §31's `novelty_archive` (`mitosis
    archive`) is where an operator finds a candidate pair worth asking about.
    """
    if genome_hash == compared_genome_hash:
        raise ContentAuditError("a genome cannot be compared against itself")
    key = (
        idempotency_key
        or f"content-audit:{Kind.RENAMED_MECHANISM.value}:{genome_hash}:{compared_genome_hash}:{auditor_cell_id}"
    )
    return _audit(
        conn,
        kind=Kind.RENAMED_MECHANISM,
        genome_hash=genome_hash,
        compared_genome_hash=compared_genome_hash,
        auditor_cell_id=auditor_cell_id,
        provider=provider,
        model=model,
        horizon_days=horizon_days,
        max_tokens=max_tokens,
        idempotency_key=key,
    )


def _audit(
    conn: sqlite3.Connection,
    *,
    kind: Kind,
    genome_hash: str,
    compared_genome_hash: str | None,
    auditor_cell_id: str,
    provider: providers.ModelProvider,
    model: str,
    horizon_days: int,
    max_tokens: int,
    idempotency_key: str,
) -> GenomeContentAudit:
    existing = get_audit_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing

    # Genomes exist independently of any request, so validate both hashes
    # (and that the pairing matches `kind`) before spending anything.
    _genome_record(conn, genome_hash)
    if compared_genome_hash is not None:
        _genome_record(conn, compared_genome_hash)

    auditor = _validated_auditor(
        conn,
        auditor_cell_id=auditor_cell_id,
        genome_hash=genome_hash,
        compared_genome_hash=compared_genome_hash,
    )

    unfunded = deliberation._unfunded_books(conn, auditor)
    if unfunded:
        raise ContentAuditError(
            f"auditor {auditor_cell_id} cannot pay for its own thinking (§15.4): "
            f"no balance in {', '.join(unfunded)}"
        )

    claim, system_prompt = _claim_and_system_prompt(
        kind, genome_hash=genome_hash, compared_genome_hash=compared_genome_hash
    )
    brief = _brief(conn, kind=kind, genome_hash=genome_hash, compared_genome_hash=compared_genome_hash)

    # Outside every transaction below: ADR-022 requires the gateway's
    # reservation to commit before the external call.
    call = gateway.call_model(
        conn,
        cell_id=auditor.cell_id,
        provider=provider,
        request=providers.ModelRequest(
            model=model,
            messages=({"role": "user", "content": f"{system_prompt}\n\n{brief}"},),
            max_tokens=max_tokens,
        ),
        idempotency_key=f"content-audit:{idempotency_key}",
    )

    try:
        reply = _parse(call.response_text or "")
    except ContentAuditError as exc:
        # The call is bought and committed by now (ADR-022); record rather
        # than raise, matching `auditor._record_rejected`'s reasoning exactly.
        return _record_rejected(
            conn,
            kind=kind,
            genome_hash=genome_hash,
            compared_genome_hash=compared_genome_hash,
            auditor=auditor,
            reason=str(exc),
            model_call_id=call.model_call_id,
            idempotency_key=idempotency_key,
        )

    return _record(
        conn,
        kind=kind,
        genome_hash=genome_hash,
        compared_genome_hash=compared_genome_hash,
        auditor=auditor,
        claim=claim,
        reply=reply,
        model_call_id=call.model_call_id,
        horizon_days=horizon_days,
        idempotency_key=idempotency_key,
    )


def _validated_auditor(
    conn: sqlite3.Connection,
    *,
    auditor_cell_id: str,
    genome_hash: str,
    compared_genome_hash: str | None,
) -> Cell:
    """§0.3, generalised from a Cell to a genome. See the module docstring."""
    auditor = lifecycle.get_cell(conn, auditor_cell_id)
    if auditor is None:
        raise ContentAuditError(f"no such auditor cell: {auditor_cell_id}")

    if auditor.cell_type not in AUDITING_TYPES:
        raise ContentAuditError(
            f"cell {auditor_cell_id} is a {auditor.cell_type.value}; only "
            f"{'/'.join(sorted(t.value for t in AUDITING_TYPES))} Cells audit "
            "(§10.4 pairs Auditor and Immune as the oversight roles)"
        )

    if auditor.status not in _CAN_AUDIT:
        raise ContentAuditError(
            f"auditor {auditor_cell_id} is {auditor.status.value} and cannot "
            "audit (Charter C8 for dead; §18.2 for quarantined)"
        )

    under_review = {genome_hash} | ({compared_genome_hash} if compared_genome_hash else set())
    if auditor.genome_hash in under_review:
        raise ContentAuditError(
            f"auditor {auditor_cell_id} carries genome {auditor.genome_hash} — "
            "an Auditor cannot judge its own business hypothesis (§0.3)"
        )

    placeholders = ",".join("?" for _ in under_review)
    rows = conn.execute(
        f"SELECT founder_cell_id FROM cells WHERE genome_hash IN ({placeholders})",
        tuple(under_review),
    ).fetchall()
    related_founders = {row["founder_cell_id"] for row in rows}
    if auditor.founder_cell_id in related_founders:
        raise ContentAuditError(
            f"auditor {auditor_cell_id} shares lineage {auditor.founder_cell_id} "
            "with a Cell that carries a genome under review — a relative is not "
            "an independent evaluator (§23.4's aggregation key, for the same "
            "reason)"
        )
    return auditor


def _parse(raw_text: str) -> ContentAuditReply:
    text = proposal_module._strip_code_fence(raw_text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContentAuditError(f"audit reply is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContentAuditError(
            f"audit reply must be a JSON object, got {type(payload).__name__}"
        )

    try:
        reply = ContentAuditReply.model_validate(payload)
    except ValidationError as exc:
        raise ContentAuditError(proposal_module._summarise_validation_error(exc)) from exc

    if reply.verdict is Verdict.CONCERN and reply.probability > _COHERENCE_MIDPOINT:
        raise ContentAuditError(
            f"incoherent audit: verdict 'concern' with probability "
            f"{reply.probability} that the genuine-claim holds. A flag that "
            "predicts the claim is true is a costless flag (§10.4)"
        )
    if reply.verdict is Verdict.NO_CONCERN and reply.probability < _COHERENCE_MIDPOINT:
        raise ContentAuditError(
            f"incoherent audit: verdict 'no_concern' with probability "
            f"{reply.probability} that the genuine-claim holds. Say 'concern' "
            "if that is what you believe"
        )
    return reply


def _record_rejected(
    conn: sqlite3.Connection,
    *,
    kind: Kind,
    genome_hash: str,
    compared_genome_hash: str | None,
    auditor: Cell,
    reason: str,
    model_call_id: str | None,
    idempotency_key: str,
) -> GenomeContentAudit:
    now = datetime.now(timezone.utc)
    audit_id = ids.new_id()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO genome_content_audits (
                audit_id, kind, genome_hash, compared_genome_hash, auditor_cell_id,
                status, failure_reason, verdict, summary, probability, prediction_id,
                model_call_id, wake_reason, created_at_utc, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                audit_id,
                kind.value,
                genome_hash,
                compared_genome_hash,
                auditor.cell_id,
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
            event_type="content_audit_rejected",
            cell_id=auditor.cell_id,
            description=reason[:200],
            metadata={
                "audit_id": audit_id,
                "kind": kind.value,
                "genome_hash": genome_hash,
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
    kind: Kind,
    genome_hash: str,
    compared_genome_hash: str | None,
    auditor: Cell,
    claim: str,
    reply: ContentAuditReply,
    model_call_id: str | None,
    horizon_days: int,
    idempotency_key: str,
) -> GenomeContentAudit:
    now = datetime.now(timezone.utc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        registered = prediction._register_locked(
            conn,
            cell_id=auditor.cell_id,
            claim=claim,
            probability=reply.probability,
            resolves_by=now + timedelta(days=horizon_days),
            idempotency_key=f"content-audit-flag:{idempotency_key}",
        )

        audit_id = ids.new_id()
        conn.execute(
            """
            INSERT INTO genome_content_audits (
                audit_id, kind, genome_hash, compared_genome_hash, auditor_cell_id,
                status, failure_reason, verdict, summary, probability, prediction_id,
                model_call_id, wake_reason, created_at_utc, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                kind.value,
                genome_hash,
                compared_genome_hash,
                auditor.cell_id,
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
            event_type="content_audit_recorded",
            cell_id=auditor.cell_id,
            description=reply.summary.strip()[:200],
            metadata={
                "audit_id": audit_id,
                "kind": kind.value,
                "genome_hash": genome_hash,
                "compared_genome_hash": compared_genome_hash,
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


# --- reading ---------------------------------------------------------------------


def get_audit(conn: sqlite3.Connection, audit_id: str) -> GenomeContentAudit | None:
    row = conn.execute(
        "SELECT * FROM genome_content_audits WHERE audit_id = ?", (audit_id,)
    ).fetchone()
    return _row_to_audit(row) if row else None


def get_audit_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> GenomeContentAudit | None:
    row = conn.execute(
        "SELECT * FROM genome_content_audits WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return _row_to_audit(row) if row else None


def audits_for_genome(conn: sqlite3.Connection, genome_hash: str) -> list[GenomeContentAudit]:
    rows = conn.execute(
        "SELECT * FROM genome_content_audits "
        "WHERE genome_hash = ? OR compared_genome_hash = ? ORDER BY rowid",
        (genome_hash, genome_hash),
    ).fetchall()
    return [_row_to_audit(r) for r in rows]


def _row_to_audit(row: sqlite3.Row) -> GenomeContentAudit:
    return GenomeContentAudit(
        audit_id=row["audit_id"],
        kind=Kind(row["kind"]),
        genome_hash=row["genome_hash"],
        compared_genome_hash=row["compared_genome_hash"],
        auditor_cell_id=row["auditor_cell_id"],
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
    """§10.4's precision-weighted record for one Auditor's content judgments.
    See `auditor.precision` for the request-audit half, and the module
    docstring for why the two are not merged."""
    rows = conn.execute(
        """
        SELECT a.status AS status, a.verdict AS verdict, p.outcome AS outcome,
               p.brier_score AS brier, p.resolved_at_utc AS resolved
          FROM genome_content_audits a
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
        # The claim is always "genuinely X"; a concern that was right is a
        # claim that resolved false, the same sign `auditor.precision` uses.
        flags_vindicated=len([r for r in resolved_flags if not r["outcome"]]),
        wrongful_flags=len([r for r in resolved_flags if r["outcome"]]),
        mean_brier=(sum(briers) / len(briers)) if briers else None,
        resolved_audits=len([r for r in rows if r["resolved"] is not None]),
    )
