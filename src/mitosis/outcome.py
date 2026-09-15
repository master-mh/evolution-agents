"""§25.2's read-back: did an allocation actually work? (SPEC.md §25.2, §8.5, §10.3, §23.5)

`promotion.py` records §25.2's evidence at the moment of funding. Half of that
evidence cannot exist yet at that moment — §25.2 asks for "predicted vs
**observed** outcome" and for "reality gap (from the prediction register,
§8.5)", and both need outcomes that arrive later. This module supplies the
second half, and it is what any honest claim that the colony is *climbing*
§25.1's ladder rather than walking up it has to rest on.

**Which forecasts count is the whole design, and §8.5 fixes it.** The obvious
measure — the Cell's mean Brier score today — is wrong twice over. It includes
predictions the funding decision already knew the answers to, and it includes
predictions the Cell registered *after* the money arrived. The second is a live
gaming surface: §23.5 warns that the review path "is itself part of the
environment and will be optimised against by Cells", and the cheapest optimisation
available to a funded Cell is a pile of easy claims registered the moment it is
richer. So the verdict rests on exactly one set:

    forecasts that were **open at the instant of funding** and have **since
    resolved** — registered before the money moved, hash-chained before the
    outcome was knowable, and therefore impossible to arrange afterwards.

Forecasts made *while* funded are counted and reported, and deliberately kept
out of the verdict. That asymmetry is the same one ADR-027 drew between a Cell's
`claimed_tier` and the kernel's `assessed_tier`, applied to evidence instead of
risk.

**§10.3 forbids the other obvious measure.** "Explorers need no immediate
revenue", so a verdict that asked whether the grant earned its money back would
reject precisely the Cells whose value is exploratory — and Explorers are most
of this colony. Cost, revenue and net contribution are therefore *recorded*, per
§25.2's list, and are not gates. What the kernel judges is calibration, which is
the selection pressure §8.5 exists to provide when there is no customer yet.

**Cherry-picked resolutions block a verdict entirely.** `prediction.py` is blunt
that "a mean Brier score over three cherry-picked resolutions is worse than
useless", and resolution is not automatic — an operator supplies outcomes. So a
promotion with any *overdue* unresolved forecast from its funding set returns
`EVIDENCE_WITHHELD` rather than a score computed over whatever happens to have
been resolved. Note what this verdict does and does not accuse: resolution is
the operator's job, so a withheld outcome is a defect in the *evidence*, not a
finding against the Cell.

**This module judges; it never acts (ADR-063).** The two directions are no
longer symmetric, and the asymmetry is the point.

**Upward, this is now consumed.** `promotion.py` gates a rung-8 "expanded pilot"
on a `SUPPORTS_PROMOTION` verdict for the predecessor. It reaches that verdict
through `PromotionEvidence` — a seam this module implements, because `outcome`
imports `promotion` and the dependency cannot run both ways. What crosses the
seam is `EvidenceReading`, four fields wide, and not `Assessment`'s twenty: a
gate handed the full evidence list is a gate a later edit can quietly re-point
at revenue, and §10.3 ("Explorers need no immediate revenue") makes that the one
dimension most likely to look reasonable and select exactly the wrong Cells.

This module still cannot *start* anything. It answers a closed question about a
named promotion; it never scans for candidates, and it does not know whether the
caller is a person or a timer.

**Downward, nothing has changed and nothing may.** §10.5 requires that
"estimated negative EV alone must not kill a Cell" without strong evidence *and*
an independent Auditor concurring, and no Auditor Cell exists (§23.2's standing
hole), so a `DOES_NOT_SUPPORT_PROMOTION` verdict must stay structurally
unreachable from `death.py`. `test_no_kernel_path_acts_on_an_assessment` still
enforces exactly that, and opening the upward direction did not loosen it —
`death.py` is named in it individually.

**The correction this slice carried.** The paragraph replaced here claimed rung 8
"means removing one of the two humans standing in every allocation". §25.1 reads
`7. Tiny capped live experiment` -> `8. Expanded pilot` -> `9. Bounded autonomy`:
the 7 -> 8 delta is *scale*, and *autonomy* appears only at rung 9. Whether a
person is in the loop is §27.1's `auto_promotion` flag, on its own axis.

**Derived, never stored.** There is no `assessments` table and no migration.
Every number below is recomputed from the hash-chained prediction register, the
ledger and the audit trail — the same posture Charter C3 takes toward balances
("always derived from ledger entries, never cached"), and the same reason
migration 0016 gives for snapshotting calibration instead of copying predictions:
a second copy is a second version that can disagree with the canonical one. A
table becomes worth adding when a *decision* consumes an assessment, because
then what was known at decision time is itself a fact. Nothing consumes one yet.

Deliberately out of scope, and logged rather than dropped:

    scanning for candidates   this answers about one named promotion. Finding
                              which Cells are due is `autopromotion.py`'s job,
                              which sits above this module.
    liability                 §13's reserve is Phase 6+, so §25.2's liability
                              figure reports unmodelled, exactly as the
                              promotion record does. A fabricated 0 would read
                              as "no liability" rather than "not yet modelled".
    the Cell seeing this      §15 context shows a Cell facts about itself; this
                              is the kernel's *judgement* of it, and §23.5 says
                              anything a Cell can see it will optimise against.
                              Kept out until there is an argument for letting a
                              Cell answer back.
    experiment outcomes       §25.2's stage progression needs experiment
                              tracking (Phase 2), which does not exist.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from . import ledger, prediction, promotion, revenue
from .models import Book

#: The only calibration bar available to a Cell being judged on its first
#: promotion, where there is no earlier record to have degraded from. **Defined
#: by the scoring rule, so it lives with the scoring rule** — this module used to
#: hold the literal while its own comment pointed at `prediction.py` for the
#: meaning. §13.2's evidence-quality gate needed the same bar, and a second
#: copy of a threshold is a second version of it (ADR-059).
UNINFORMATIVE_BRIER = prediction.UNINFORMATIVE_BRIER

#: How many resolved forecasts before the kernel will state a verdict at all.
#:
#: **This is the weakest number in the module and is deliberately placed where
#: being wrong is harmless.** A mean Brier over one resolution is a coin flip
#: wearing a decimal point, and §27.1's own phase-3 metric — "pre-registered
#: selection effect size (CI excludes 0)" — is the spec being explicit that it
#: cares whether a result is distinguishable from luck. The honest instrument is
#: a confidence interval on the score; that needs machinery §8.5 does not
#: authorise here, and it is logged rather than invented.
#:
#: Until then, the rule this module follows everywhere an arbitrary choice
#: arises: **err toward withholding.** Too high a threshold delays a promotion a
#: human can still make by reading the evidence themselves. Too low a one hands
#: a rung to a Cell that got lucky once, and §25.1 exists precisely to stop
#: that. Only one of those errors compounds.
MIN_RESOLVED_FOR_A_VERDICT = 3

#: §25.1 has nine rungs; there is nothing above the top.
TOP_RUNG = 9

#: §25.2's "human intervention", classified by audit event type because
#: `audit_events` has **no actor column** — nothing in the schema distinguishes
#: an operator's action from the kernel's. So this is a by-type judgement, and
#: each entry carries the reason it is one, in the style `accounts.py` uses for
#: spend destinations.
#:
#: Only cell-scoped events can be attributed to a promotion at all. Colony-wide
#: operator actions (funding the pool, acknowledging a metabolic alarm, changing
#: the autonomy flag) are real human minutes but belong to no single Cell, and
#: charging them to one would make whichever Cell happened to be funded look
#: expensive to supervise.
#:
#: `cell_lifecycle_transition` is deliberately absent: some transitions are an
#: operator's decision and some are the kernel's, and the row does not say which.
#: Counting it would inflate the figure with automation.
HUMAN_INTERVENTION_EVENTS: dict[str, str] = {
    "approval_granted": "an operator approved a request under §23.1",
    "approval_rejected": "an operator refused a request under §23.1",
    "capital_allocated": "an operator ran an allocation",
    "prediction_resolved": (
        "an operator supplied an outcome — §8.5's register does not resolve "
        "itself, so every resolution is human minutes"
    ),
    "model_call_disputed": "an operator disputed a provider charge",
    "negative_ev_death_concurred": "an independent evaluator concurred in a §10.5 kill",
}


class Verdict(StrEnum):
    """§25.2's "reasons for promotion or rejection", reduced to four outcomes.

    `INSUFFICIENT_EVIDENCE` and `EVIDENCE_WITHHELD` are both "no verdict", and
    they are separate because the remedies are opposite: the first needs time,
    the second needs someone to go and resolve the outstanding forecasts. A
    single "unknown" would hide which.
    """

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EVIDENCE_WITHHELD = "evidence_withheld"
    SUPPORTS_PROMOTION = "supports_promotion"
    DOES_NOT_SUPPORT_PROMOTION = "does_not_support_promotion"


class OutcomeError(Exception):
    pass


@dataclass(frozen=True)
class Assessment:
    """§25.2's evidence list, read back after the fact.

    Not collapsed to a score (§10.2: "do not collapse all dimensions into one
    scalar"). The fields below are the spec's own enumeration — predicted vs
    observed outcome, cost, liability, reality gap, human intervention, transfer
    degradation, and the reasons — and `verdict` summarises only the calibration
    dimensions it is entitled to judge.
    """

    promotion_id: str
    cell_id: str
    rung: int
    next_rung: int
    book: Book
    funded_at_utc: datetime
    assessed_at_utc: datetime

    # --- §25.2 "predicted vs observed outcome" -------------------------------
    # The funding set: open at the instant of funding, so unknowable to the
    # approver and unarrangeable by the Cell afterwards.
    forecasts_open_at_funding: int
    forecasts_resolved_since: int
    forecasts_still_open: int
    forecasts_overdue: int
    observed_mean_brier: float | None
    observed_mean_log: float | None

    # --- §25.2 "reality gap (from the prediction register, §8.5)" ------------
    funded_mean_brier: float | None
    reality_gap: float | None

    # --- §25.2 "cost" --------------------------------------------------------
    allocated_minor_units: int
    spend_since_minor_units: int
    revenue_since_minor_units: int

    # --- §25.2 "liability" ---------------------------------------------------
    liability_minor_units: int | None

    # --- §25.2 "human intervention" ------------------------------------------
    human_interventions: int
    intervention_kinds: dict[str, int]

    # --- §25.2 "transfer degradation" ----------------------------------------
    transfer_degradation: float | None

    # --- §25.2 "the reasons for promotion or rejection" ----------------------
    verdict: Verdict
    reasons: tuple[str, ...]

    # --- reported, and excluded from the verdict on purpose (§23.5) ----------
    forecasts_made_while_funded: int
    forecasts_made_while_funded_resolved: int
    mean_brier_made_while_funded: float | None

    @property
    def net_contribution_minor_units(self) -> int:
        """Realised revenue minus realised consumption since funding.

        Recorded because §25.2 asks for cost, and **not** judged: §10.3 says
        Explorers "need no immediate revenue", so a negative figure here is the
        expected shape of a working Explorer, not a failure.
        """
        return self.revenue_since_minor_units - self.spend_since_minor_units

    @property
    def unspent_minor_units(self) -> int:
        """Grant not yet consumed. A grant untouched means the experiment the
        money was approved for has not run, which reads very differently from a
        grant spent to no effect — so the two are never summed together."""
        return self.allocated_minor_units - self.spend_since_minor_units

    @property
    def is_decided(self) -> bool:
        return self.verdict in (
            Verdict.SUPPORTS_PROMOTION,
            Verdict.DOES_NOT_SUPPORT_PROMOTION,
        )


def assess(
    conn: sqlite3.Connection, promotion_id: str, *, now: datetime | None = None
) -> Assessment:
    """Read back what happened after a promotion. Pure derivation — no writes.

    Every figure comes from a record the Cell does not control: the hash-chained
    prediction register, the ledger, and the audit trail. §0.3 — "a Cell may
    *explain* a result; it may never *define* the canonical result" — is the
    reason nothing here reads a Cell's own account of how it did.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    record = promotion.get_promotion(conn, promotion_id)
    if record is None:
        raise OutcomeError(f"no such promotion: {promotion_id}")

    funded_at = record.created_at_utc.astimezone(timezone.utc)
    funded_iso = funded_at.isoformat()

    funding_set = _forecasts_open_at(conn, record.cell_id, funded_iso)
    resolved = [row for row in funding_set if row["resolved_at_utc"] is not None]
    still_open = [row for row in funding_set if row["resolved_at_utc"] is None]
    overdue = [row for row in still_open if row["resolves_by_utc"] < now.isoformat()]

    observed_brier = _mean(row["brier_score"] for row in resolved)
    observed_log = _mean(row["log_score"] for row in resolved)

    # §8.5: "reality_gap = calibrated difference between predicted and observed
    # real outcome". The predicted side is the snapshot the promotion froze at
    # funding; the observed side is what the funding set actually did. Brier is
    # a loss, so a positive gap means the Cell performed worse than the record
    # it was funded on. None when the Cell had nothing resolved at funding —
    # there is no baseline to have moved away from, and reporting 0 would claim
    # a perfect transfer nobody measured.
    reality_gap = (
        None
        if observed_brier is None or record.reality_gap_mean_brier is None
        else observed_brier - float(record.reality_gap_mean_brier)
    )

    while_funded = _forecasts_registered_after(conn, record.cell_id, funded_iso)
    while_funded_resolved = [r for r in while_funded if r["resolved_at_utc"] is not None]

    interventions = _human_interventions(
        conn, cell_id=record.cell_id, since_iso=funded_iso, promotion_id=promotion_id
    )

    verdict, reasons = _verdict(
        resolved_count=len(resolved),
        overdue_count=len(overdue),
        still_open_count=len(still_open),
        observed_brier=observed_brier,
        reality_gap=reality_gap,
    )

    return Assessment(
        promotion_id=record.promotion_id,
        cell_id=record.cell_id,
        rung=record.rung,
        next_rung=min(record.rung + 1, TOP_RUNG),
        book=record.book,
        funded_at_utc=funded_at,
        assessed_at_utc=now,
        forecasts_open_at_funding=len(funding_set),
        forecasts_resolved_since=len(resolved),
        forecasts_still_open=len(still_open),
        forecasts_overdue=len(overdue),
        observed_mean_brier=observed_brier,
        observed_mean_log=observed_log,
        funded_mean_brier=record.reality_gap_mean_brier,
        reality_gap=reality_gap,
        allocated_minor_units=record.allocated_minor_units,
        spend_since_minor_units=ledger.spend_by_book(
            conn, record.cell_id, since=funded_at
        ).get(record.book.value, 0),
        # Net (ADR-097): a sale refunded after funding did not earn this rung
        # anything, whenever the sale itself was made.
        revenue_since_minor_units=revenue.net_revenue(
            conn, record.cell_id, record.book, since=funded_at
        ),
        # §13's liability reserve is Phase 6+. Reported unmodelled rather than
        # 0, matching the promotion record it is read back against.
        liability_minor_units=None,
        human_interventions=sum(interventions.values()),
        intervention_kinds=interventions,
        # The realised figure, where `promotions.transfer_degradation` holds the
        # estimate made at funding. Degradation *is* the reality gap once the
        # outcomes are in: how much worse the strategy did at this rung than the
        # record it was promoted on.
        transfer_degradation=reality_gap,
        verdict=verdict,
        reasons=reasons,
        forecasts_made_while_funded=len(while_funded),
        forecasts_made_while_funded_resolved=len(while_funded_resolved),
        mean_brier_made_while_funded=_mean(
            row["brier_score"] for row in while_funded_resolved
        ),
    )


def assess_all(
    conn: sqlite3.Connection, *, cell_id: str | None = None, now: datetime | None = None
) -> list[Assessment]:
    """Every promotion's read-back, oldest first."""
    return [
        assess(conn, item.promotion_id, now=now)
        for item in promotion.list_promotions(conn, cell_id=cell_id)
    ]


# --- the verdict -------------------------------------------------------------


def _verdict(
    *,
    resolved_count: int,
    overdue_count: int,
    still_open_count: int,
    observed_brier: float | None,
    reality_gap: float | None,
) -> tuple[Verdict, tuple[str, ...]]:
    """Judge only what the kernel is entitled to judge.

    Order matters. `EVIDENCE_WITHHELD` is checked **before** any score is
    considered, including when resolved outcomes exist: a mean over the subset
    someone chose to resolve, with the rest still outstanding past their
    deadlines, is the self-selected calibration curve `prediction.py` exists to
    prevent. It looks excellent and means nothing, and it would mean nothing in
    exactly the direction that favours promotion.

    Then the sample-size gate, then two calibration dimensions — one relative
    (§8.5's reality gap, against the record the promotion was granted on) and
    one absolute (better than knowing nothing). Either one failing withholds
    support; both are reported either way, because §10.2 forbids collapsing them
    and they call for opposite corrections. The relative test triggers on any
    degradation rather than a "material" one, because there is no principled
    threshold for material and the direction of that error is the safe one: it
    can only ever delay a promotion a human is still free to make.
    """
    if overdue_count:
        return (
            Verdict.EVIDENCE_WITHHELD,
            (
                f"{overdue_count} forecast(s) open at funding are past their own "
                "deadline and unresolved; a mean over the resolved remainder would "
                "be self-selected (§8.5). Resolve them and reassess.",
            ),
        )

    if resolved_count < MIN_RESOLVED_FOR_A_VERDICT:
        pending = (
            f"{still_open_count} still open, none past deadline"
            if still_open_count
            else "none still open"
        )
        return (
            Verdict.INSUFFICIENT_EVIDENCE,
            (
                f"{resolved_count} of the forecasts open at funding have resolved; "
                f"{MIN_RESOLVED_FOR_A_VERDICT} is the minimum this kernel will call a "
                f"verdict on ({pending}). A mean over fewer is not distinguishable "
                "from luck, and §25.1 exists to stop a rung being won by one.",
            ),
        )

    assert observed_brier is not None  # resolved_count > 0 implies a mean exists

    reasons: list[str] = []
    if reality_gap is not None and reality_gap > 0:
        # §8.5: "High simulated performance with a high reality gap reduces
        # promotion confidence."
        reasons.append(
            f"reality gap {reality_gap:+.4f}: the Cell is less calibrated on the "
            "forecasts it was funded on than on the record that funded it (§8.5)."
        )
    if observed_brier >= UNINFORMATIVE_BRIER:
        reasons.append(
            f"mean Brier {observed_brier:.4f} over {resolved_count} resolved "
            f"forecast(s) is no better than always answering 0.5 ({UNINFORMATIVE_BRIER})."
        )

    if reasons:
        return Verdict.DOES_NOT_SUPPORT_PROMOTION, tuple(reasons)

    supporting = [
        f"mean Brier {observed_brier:.4f} over {resolved_count} forecast(s) that "
        f"were open when the capital moved, beating {UNINFORMATIVE_BRIER}."
    ]
    if reality_gap is not None:
        supporting.append(
            f"reality gap {reality_gap:+.4f}: calibration held or improved against "
            "the record the promotion was granted on (§8.5)."
        )
    return Verdict.SUPPORTS_PROMOTION, tuple(supporting)


# --- the register, sliced at the funding instant -----------------------------


def _forecasts_open_at(
    conn: sqlite3.Connection, cell_id: str, at_iso: str
) -> list[sqlite3.Row]:
    """Forecasts that were live at `at_iso`: registered before it, and not yet
    resolved as of it.

    This is the set §25.2's "predicted vs observed" is about, and the only one
    that cannot be arranged after the money arrives. Timestamps compare as ISO
    strings because every writer in this kernel stamps
    `datetime.now(timezone.utc).isoformat()`, which is lexicographically ordered.
    """
    return conn.execute(
        """
        SELECT * FROM prediction_register
         WHERE cell_id = ?
           AND created_at_utc <= ?
           AND (resolved_at_utc IS NULL OR resolved_at_utc > ?)
         ORDER BY rowid
        """,
        (cell_id, at_iso, at_iso),
    ).fetchall()


def _forecasts_registered_after(
    conn: sqlite3.Connection, cell_id: str, at_iso: str
) -> list[sqlite3.Row]:
    """Forecasts the Cell registered while funded. Counted, never judged — see
    the module docstring on §23.5."""
    return conn.execute(
        """
        SELECT * FROM prediction_register
         WHERE cell_id = ? AND created_at_utc > ?
         ORDER BY rowid
        """,
        (cell_id, at_iso),
    ).fetchall()


def _human_interventions(
    conn: sqlite3.Connection, *, cell_id: str, since_iso: str, promotion_id: str
) -> dict[str, int]:
    """§25.2's "human intervention", counted per event type since funding.

    The promotion's *own* `capital_allocated` event is excluded. It is stamped a
    few microseconds after the promotion row, so a naive `> funded_at` filter
    counts the act of funding as supervision of the funded period — inflating
    every assessment by exactly one and making a Cell that needed no attention
    at all look like it needed some.
    """
    counts: dict[str, int] = {}
    placeholders = ", ".join("?" for _ in HUMAN_INTERVENTION_EVENTS)
    rows = conn.execute(
        f"""
        SELECT event_type, metadata_json FROM audit_events
         WHERE cell_id = ?
           AND created_at_utc > ?
           AND event_type IN ({placeholders})
         ORDER BY rowid
        """,
        (cell_id, since_iso, *sorted(HUMAN_INTERVENTION_EVENTS)),
    ).fetchall()
    for row in rows:
        if row["event_type"] == "capital_allocated" and _names_promotion(
            row["metadata_json"], promotion_id
        ):
            continue
        counts[row["event_type"]] = counts.get(row["event_type"], 0) + 1
    return counts


def _names_promotion(metadata_json: str, promotion_id: str) -> bool:
    try:
        return json.loads(metadata_json).get("promotion_id") == promotion_id
    except (ValueError, AttributeError):
        return False


def _mean(values) -> float | None:
    present = [float(v) for v in values if v is not None]
    return sum(present) / len(present) if present else None


# --- the §25.2 gate, as `promotion.PromotionEvidence` (ADR-063) --------------


class AssessmentEvidence:
    """`promotion.PromotionEvidence`, implemented over `assess`.

    The inversion `sweeper.ExternalOperationChecker` /
    `gateway.GatewayOperationChecker` established, applied to evidence: the
    lower module (`promotion`) declares the shape it needs, the higher one
    (`outcome`, which imports it) supplies the behaviour, and no back-edge is
    created.

    Stateless and cheap to construct. It holds no connection, because the one
    it must read is the connection *inside the caller's write lock* — an
    implementation that captured its own would assess a promotion against a
    snapshot taken before the transaction that is about to consume it.
    """

    def read(
        self, conn: sqlite3.Connection, promotion_id: str
    ) -> "promotion.EvidenceReading":
        assessment = assess(conn, promotion_id)
        return promotion.EvidenceReading(
            verdict=str(assessment.verdict),
            supports_promotion=assessment.verdict is Verdict.SUPPORTS_PROMOTION,
            mean_brier=assessment.observed_mean_brier,
            resolved_predictions=assessment.forecasts_resolved_since,
        )
