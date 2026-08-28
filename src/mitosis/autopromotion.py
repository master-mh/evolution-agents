"""Climbing §25.1's ladder with no operator in the loop (SPEC.md §25.1, §23.1,
§23.6, §27.1, §0.4; ADR-063).

**What this module is, named honestly.** §25.1 rung 8 is an "expanded pilot" — a
*larger* allocation, still supervised. Issuing one **on a timer, with nobody
watching** is a different axis entirely, and it is rung 9's "bounded autonomy".
This module is that second thing, and the two are kept apart everywhere: the
rung is a column, the decider is a column, and `promotion.ISSUABLE_RUNGS` stops
9 ever being written as a rung because bounded autonomy is not a bigger cheque.

**Every bound here is a refusal that already existed.** This module invents no
new safety mechanism, and that is deliberate — an engine that runs unattended is
the worst possible place to debut a hand-rolled guard. What it does is *compose*
gates the kernel already enforces:

    §27.1 `auto_promotion`  ships false (§0.4: "Nothing begins at real-money
                            autonomy"). Nothing below runs without it.
    §27.1 `real_spending`   still separately required for a USD_REAL book, so
                            ADR-026's two independent confirmations stay two.
    §23.1 `batchable`       the *only* predicate by which this approves
                            anything. It is the kernel's own, already
                            interlocked with §23.4: it folds in cumulative
                            lineage exposure and disqualifies on any gaming
                            signal. This module never widens it.
    §25.2 evidence          a rung-8 expansion needs its predecessor's observed
                            outcome to support it — enforced in `promotion.py`
                            behind the `PromotionEvidence` seam, not here.
    `promotion_pool`        the operator's standing ceiling. Nothing this module
                            does can raise it, and no Cell can fund it. It is
                            the one number that bounds an unattended run whether
                            or not anyone is watching.

**What it deliberately does not do.** It never kills. §10.5 requires that
"estimated negative EV alone must not kill a Cell" without strong evidence *and*
an independent Auditor concurring, and no Auditor Cell exists (§23.2's standing
hole). An engine that promoted on a verdict and culled on its negation would be
culling on exactly the estimate §10.5 names, so `death.py` stays unreachable
from every path below — enforced structurally by
`test_no_kernel_path_acts_on_an_assessment`.

It also never approves anything §23.1 calls individual-review. The batchable
predicate is low-tier *and* reversible *and* signal-free; a spend request large
enough to matter fails it on exposure alone, and stays in the queue for a
person. Automation here clears the routine tail; it does not empty the queue.

**Where it sits.** Above `outcome`, which is above `promotion`, which is above
`scheduler`. That ordering is why the scheduler cannot call this directly and
takes an injected `PromotionSweeper` instead — the same inversion as
`sweeper.ExternalOperationChecker` and `population.Displacer`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import approval, audit, lifecycle, outcome, promotion
from .models import CellStatus

#: What `allocated_by` records when nobody typed anything. A literal rather than
#: a caller-supplied string: §2.6's autonomy-adjusted profit exists "to expose
#: hidden human labour", and an unattended allocation that recorded an
#: operator's name would hide the opposite — machine labour wearing a person's.
DECIDER = "autopromotion"

#: The reason written onto every batch approval this module makes. §23.1 permits
#: batching; §25.2 still requires a stated reason, and "a human said so" would
#: be false.
BATCH_REASON = (
    "§23.1 batch: low-tier, reversible, no gaming signal — approved unattended "
    "under §27.1 autonomy.auto_promotion"
)


class AutoPromotionError(Exception):
    pass


@dataclass(frozen=True)
class SweepResult:
    """What one unattended pass did, and what it refused.

    `skipped` is not an error list — it is the record of the engine declining,
    which is the behaviour most worth being able to read back. An unattended
    system that only logged its successes would look identical whether it was
    working or silently promoting everything.
    """

    ran: bool
    detail: str
    batch_id: str | None = None
    approved: tuple[str, ...] = ()
    promotions: tuple[promotion.Promotion, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()

    @property
    def rung_8_count(self) -> int:
        return sum(
            1
            for p in self.promotions
            if p.rung == promotion.LADDER_RUNG_EXPANDED_PILOT
        )


def enabled(conn: sqlite3.Connection) -> bool:
    """§27.1's `auto_promotion`. Absent operator row reads as *off*."""
    row = conn.execute(
        "SELECT auto_promotion_enabled FROM operator_state WHERE id = 1"
    ).fetchone()
    return bool(row["auto_promotion_enabled"]) if row is not None else False


def entitled_rung_for(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    evidence: promotion.PromotionEvidence,
) -> tuple[int, str]:
    """The rung this Cell's next allocation may be issued at, and why.

    Returns rung 8 only when an unexpanded rung-7 promotion exists *and* its
    §25.2 verdict supports the expansion. Everything else is rung 7 — including
    "the evidence is not in yet", which is a wait rather than a refusal.

    The reason string is returned rather than logged because it is the thing an
    operator reads afterwards to understand an unattended decision, and a
    decision whose rationale is only in a log line is one nobody will reconcile.
    """
    predecessor = promotion._latest_promotion_at_rung_locked(
        conn, cell_id=cell_id, rung=promotion.LADDER_RUNG_CAPPED_LIVE_EXPERIMENT
    )
    if predecessor is None:
        return (
            promotion.LADDER_RUNG_CAPPED_LIVE_EXPERIMENT,
            "no prior live experiment — §25.1 starts at rung 7",
        )

    reading = evidence.read(conn, predecessor)
    if reading.supports_promotion:
        return (
            promotion.LADDER_RUNG_EXPANDED_PILOT,
            f"§25.2 evidence for {predecessor} supports promotion "
            f"({reading.resolved_predictions} forecast(s) resolved)",
        )
    return (
        promotion.LADDER_RUNG_CAPPED_LIVE_EXPERIMENT,
        f"§25.2 evidence for {predecessor} reads '{reading.verdict}' — "
        "staying at rung 7",
    )


def sweep(
    conn: sqlite3.Connection,
    *,
    evidence: promotion.PromotionEvidence | None = None,
    approve_batchable: bool = True,
    limit: int | None = None,
    now: datetime | None = None,
) -> SweepResult:
    """One unattended pass: approve what §23.1 permits, then allocate it.

    Not a `_locked` core and deliberately not one. Each allocation is its own
    transaction, because a sweep that folded twenty allocations into one would
    roll back nineteen good ones on the twentieth's insufficient pool — and an
    unattended engine that fails all-or-nothing on a routine shortfall is one
    that stops silently at 3am.
    """
    now = now or datetime.now(timezone.utc)
    evidence = evidence or outcome.AssessmentEvidence()

    if not enabled(conn):
        return SweepResult(
            ran=False,
            detail=(
                f"autonomy.{promotion.AUTO_PROMOTION_FLAG} is disabled (§27.1 ships "
                "it false) — no unattended promotion attempted"
            ),
        )

    batch_id: str | None = None
    approved: list[str] = []
    if approve_batchable:
        batch_id, grants = approval.approve_batch(
            conn, decided_by=DECIDER, reason=BATCH_REASON, now=now, limit=limit
        )
        approved = [g.grant_id for g in grants]
        if not grants:
            batch_id = None

    promotions: list[promotion.Promotion] = []
    skipped: list[tuple[str, str]] = []

    for grant in promotion.allocatable_grants(conn, now=now):
        if limit is not None and len(promotions) >= limit:
            break

        cell = lifecycle.get_cell(conn, grant.cell_id)
        if cell is None or cell.status is not CellStatus.ALIVE:
            skipped.append((grant.grant_id, "cell is not alive"))
            continue

        rung, why = entitled_rung_for(
            conn, cell_id=cell.cell_id, evidence=evidence
        )
        try:
            promotions.append(
                promotion.allocate(
                    conn,
                    grant_id=grant.grant_id,
                    allocated_by=DECIDER,
                    reason=f"unattended §25.1 rung {rung} allocation: {why}",
                    rung=rung,
                    evidence=evidence,
                    decided_automatically=True,
                    now=now,
                )
            )
        except promotion.PromotionError as exc:
            # Every refusal below is a kernel gate doing its job — an empty
            # pool, a disabled real-spending flag, a quarantined Cell. Recorded
            # and stepped over, never retried: a loop that retried a refusal
            # would turn one guard into a hot loop against it.
            skipped.append((grant.grant_id, str(exc)))

    detail = (
        f"approved {len(approved)}, allocated {len(promotions)} "
        f"({sum(1 for p in promotions if p.rung == promotion.LADDER_RUNG_EXPANDED_PILOT)} "
        f"at rung 8), skipped {len(skipped)}"
    )

    if promotions or approved:
        audit.record(
            conn,
            event_type="autopromotion_swept",
            cell_id=None,
            description=detail,
            metadata={
                "batch_id": batch_id,
                "approved": approved,
                "promotions": [p.promotion_id for p in promotions],
                "rung_8": [
                    p.promotion_id
                    for p in promotions
                    if p.rung == promotion.LADDER_RUNG_EXPANDED_PILOT
                ],
                "skipped": [g for g, _ in skipped],
            },
        )

    return SweepResult(
        ran=True,
        detail=detail,
        batch_id=batch_id,
        approved=tuple(approved),
        promotions=tuple(promotions),
        skipped=tuple(skipped),
    )


class EvidencePromoter:
    """`scheduler.PromotionSweeper`, implemented over `sweep`.

    The scheduler sits *below* this module (`promotion` imports it), so it
    cannot import this one. Same inversion as everywhere else in the kernel:
    the lower module declares the shape, the higher one supplies it, and the
    tick's caller does the wiring.
    """

    def __init__(self, *, limit: int | None = None) -> None:
        self._limit = limit

    def sweep(
        self, conn: sqlite3.Connection, *, now: datetime | None = None
    ) -> str | None:
        result = sweep(conn, limit=self._limit, now=now)
        if not result.ran or not (result.promotions or result.approved):
            return None
        return result.detail
