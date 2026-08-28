"""Rung 7: an approved grant allocates capital (SPEC.md §25.1, §25.2, §17.2, §31).

This is the module that closes the colony's core loop. §31 states that loop in
one line — "... -> allocate capital -> scale, mutate, collaborate, sleep, or
die" — and until now MITOSIS could do everything on both sides of that arrow and
nothing at the arrow itself. A Cell could think, propose, and be reviewed; an
approval produced a grant; and the grant sat there, inert by construction
(ADR-027).

**Two sockets the spec left open are what this fills, and neither is invented
here.** `promotion_pool` has been in §31's required account list since Phase 1,
described in `accounts.py` as "capital held for §25 promotion — redistributed,
never consumed", with nothing ever moving through it. §17.2 lists "capital
allocation" among its wake reasons, and `deliberation.WAKE_CAPITAL_ALLOCATION`
has been defined and unemitted since the agent loop landed. A Cell woken
*because* it has just been funded is precisely the event both were reserved for.

**Why rung 7 is the floor here, and what rung 8 actually is (ADR-063).** §25.1's
ladder puts "tiny capped live experiment" one step past "human-reviewed
prototype". Two humans stand in a rung-7 allocation: one approved the request
individually under §23.1, and one runs the allocation.

This module used to claim that "rung 8 and rung 9 each mean removing one of
those humans". **That was wrong**, and it had propagated to four places. §25.1
reads `7. Tiny capped live experiment` -> `8. Expanded pilot` -> `9. Bounded
autonomy`: the 7 -> 8 delta is **scale**, and the word *autonomy* appears only at
rung 9. A *pilot* is supervised by definition. Who acts without a human is
governed by §27.1's `autonomy:` flags and §0.4's "tool by tool, phase by phase",
never by a ladder rung — and `test_outcome.py` said so correctly three lines
below the docstring that said otherwise: "a promotion that fires on a timer is
rung 9, not rung 8".

So the two axes are independent, and this module keeps them independent:

    rung             how far up §25.1 the money has climbed. 7 = tiny capped,
                     8 = expanded. Requires a predecessor at the rung below,
                     enforced by migration 0030's trigger rather than here,
                     because a constraint has no layer (ADR-047).
    decided_by_whom  whether a person was in the loop. Recorded in
                     `decided_automatically`; bounded by §27.1's
                     `auto_promotion` flag, which ships false.

An unattended allocation is rung 9's bounded autonomy applied to the *decision*,
which is why it is a column and not an inference — a later reader must be able
to tell which promotions a person made.

**What the Cell does not get to decide.** The amount allocated is the amount
frozen into the grant at approval — the figure §23.2 actually showed the
operator — never a value re-read from the Cell at allocation time. The Cell is
not consulted here at all: it is woken afterwards and told, through the ordinary
§15 context, that its balance changed. That asymmetry is the same one §0.3 and
§23.5 have imposed everywhere else in this codebase, applied to the one place
where the colony finally hands a Cell real spending power.

**Where the money comes from matters.** Allocations draw on `promotion_pool`,
not on `seed_bank` and not on the treasury directly. The pool has to be funded
deliberately, which gives the operator a single number bounding everything this
path can ever allocate — a cap that exists whether or not anyone is watching the
queue, and one the Cells cannot influence because no Cell can fund the pool.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from . import approval, audit, deliberation, ids, ledger, lifecycle, prediction, scheduler
from .accounts import cell_cash
from .models import Book, CellStatus, EntrySpec
from .proposal import ProposalKind

#: §25.1 rung 7, "tiny capped live experiment". The floor of the live ladder:
#: nothing precedes it, so a rung-7 promotion supersedes nothing.
LADDER_RUNG_CAPPED_LIVE_EXPERIMENT = 7

#: §25.1 rung 8, "expanded pilot". Same two humans, a larger cap, and a
#: predecessor whose §25.2 evidence supports the expansion.
LADDER_RUNG_EXPANDED_PILOT = 8

#: The rungs this module will issue. Rung 9 ("bounded autonomy") is deliberately
#: absent: it is not a bigger allocation but a different *decider*, and this
#: module already records that on the `decided_automatically` axis. Adding 9
#: here would conflate the two axes the docstring above separates.
ISSUABLE_RUNGS = (LADDER_RUNG_CAPPED_LIVE_EXPERIMENT, LADDER_RUNG_EXPANDED_PILOT)

#: §27.1's flag for issuing a promotion with no operator in the loop. Ships
#: false (§0.4: "Nothing begins at real-money autonomy"). Distinct from
#: `real_spending`, which is still separately required for a USD_REAL book —
#: keeping ADR-026's two independent confirmations from collapsing into one.
AUTO_PROMOTION_FLAG = "auto_promotion"

#: Where allocations draw from. §31 reserved this account for §25 promotion and
#: nothing has ever moved through it.
PROMOTION_POOL = "promotion_pool"


# --- §25.2 evidence, as an injected seam (ADR-063) ---------------------------
#
# `outcome.py` computes §25.2's read-back and **imports this module** to do it.
# So this module cannot import it back; the dependency is inverted with a seam,
# exactly as `sweeper.ExternalOperationChecker` is implemented by
# `gateway.GatewayOperationChecker` and `population.Displacer` by
# `displacement.ObjectiveDisplacer`.
#
# **The signature is the safety property, not the implementation.** It takes a
# `promotion_id` and never a `cell_id`, so it cannot be asked the open question
# "how is this Cell doing?" — only the closed one "did *this specific*
# predecessor work?". That is the §9.3 move applied to evidence: a signature
# that cannot see a Cell's general record cannot promote on a general
# impression, and no implementation can widen it without changing this file.


@dataclass(frozen=True)
class EvidenceReading:
    """What the kernel is allowed to learn about a predecessor promotion.

    Deliberately narrow. `outcome.Assessment` carries twenty fields across
    §25.2's full evidence list; this carries the four a *gate* needs. Passing
    the whole assessment would let a later edit gate on revenue, and §10.3 is
    explicit that "Explorers need no immediate revenue" — the one dimension
    most likely to look reasonable and select exactly the wrong Cells.
    """

    verdict: str
    supports_promotion: bool
    mean_brier: float | None
    resolved_predictions: int


class PromotionEvidence(Protocol):
    """Reads §25.2's verdict for one promotion. Implemented by `outcome.py`."""

    def read(
        self, conn: sqlite3.Connection, promotion_id: str
    ) -> EvidenceReading: ...

#: The transaction type an allocation posts. Exempt from real-spend
#: registration: `promotion_pool -> cell cash` is an internal capital transfer
#: that never touches `external_expense`. It does raise the Cell's spending
#: power, which Charter C4's balance check then bounds — the same relationship
#: `cell_funding` already has.
ALLOCATION_TRANSACTION_TYPE = "capital_allocation"

#: A Cell must be able to receive and then use capital. Dead is Charter C8;
#: quarantined is §18.2 — funding a restricted Cell would be the clearest way to
#: make a restriction meaningless.
_CAN_RECEIVE_CAPITAL = frozenset({CellStatus.ALIVE, CellStatus.DORMANT})


class PromotionError(Exception):
    pass


@dataclass(frozen=True)
class Promotion:
    promotion_id: str
    grant_id: str
    request_id: str
    proposal_id: str
    cell_id: str
    rung: int
    book: Book
    allocated_minor_units: int
    reality_gap_mean_brier: float | None
    resolved_predictions: int
    unresolved_predictions: int
    liability_minor_units: int | None
    transfer_degradation: float | None
    approved_by: str
    allocated_by: str
    reason: str
    created_at_utc: datetime
    #: The rung-7 promotion this one expands. None at rung 7, which supersedes
    #: nothing; NOT NULL above it, enforced by migration 0030's trigger.
    supersedes_promotion_id: str | None = None
    #: Whether a person was in the loop. Recorded rather than inferred — the
    #: rung says how far up §25.1 the money climbed, this says who decided.
    decided_automatically: bool = False
    #: §25.2's verdict on the predecessor, frozen at the moment it was consumed.
    #: None at rung 7, which is decided on the §23 payload rather than on an
    #: earlier outcome.
    evidence_verdict: str | None = None
    evidence_mean_brier: float | None = None
    evidence_resolved_predictions: int | None = None
    #: The wake this allocation enqueued (§17.2 "capital allocation"). None only
    #: if the Cell was already queued for one.
    wake_key: str | None = None


def pool_balance(conn: sqlite3.Connection, book: Book) -> int:
    return ledger.get_balance(conn, PROMOTION_POOL, book=book)


def fund_pool(
    conn: sqlite3.Connection,
    *,
    book: Book,
    amount_minor_units: int,
    funding_account: str = "colony_treasury",
    idempotency_key: str,
) -> int:
    """Move capital into the promotion pool. An operator action, always.

    No Cell can call this and no scheduled path does. The pool's balance is
    therefore a hard ceiling on everything the promotion path can ever allocate,
    set by a human in advance and unaffected by anything the colony decides
    while nobody is watching — which is the property that makes it safe for
    approvals to actually move money.
    """
    if amount_minor_units <= 0:
        raise PromotionError("funding amount must be positive")

    ledger.post_transaction(
        conn,
        book=book,
        currency="USD" if book != Book.RESOURCE else "RESOURCE",
        transaction_type="promotion_pool_funding",
        idempotency_key=idempotency_key,
        description=f"fund the §25 promotion pool with {amount_minor_units}",
        entries=[
            EntrySpec(account_id=funding_account, amount_minor_units=-amount_minor_units),
            EntrySpec(account_id=PROMOTION_POOL, amount_minor_units=amount_minor_units),
        ],
    )
    audit.record(
        conn,
        event_type="promotion_pool_funded",
        description=f"{amount_minor_units} {book.value} from {funding_account}",
        metadata={
            "book": book.value,
            "amount_minor_units": amount_minor_units,
            "funding_account": funding_account,
        },
    )
    return pool_balance(conn, book)


def allocate(
    conn: sqlite3.Connection,
    *,
    grant_id: str,
    allocated_by: str,
    reason: str,
    rung: int = LADDER_RUNG_CAPPED_LIVE_EXPERIMENT,
    evidence: PromotionEvidence | None = None,
    decided_automatically: bool = False,
    now: datetime | None = None,
) -> Promotion:
    """Consume an approved grant: allocate its capital and wake the Cell.

    Everything below happens in one transaction — the allocation, the grant
    being marked consumed, the §25.2 evidence, and the §17.2 wake. A crash that
    left any subset applied would mean either a Cell funded by a grant that
    could be spent again, or a grant consumed with no money moved.

    `rung` defaults to 7 so that every existing caller keeps its exact meaning.
    Rung 8 additionally requires `evidence`: the predecessor is found here, but
    judging it is `outcome.py`'s job and reaches this module through the seam.
    """
    reason = (reason or "").strip()
    if not reason:
        raise PromotionError(
            "a promotion must state a reason — §25.2 requires the reasons for "
            "promotion recorded at every rung"
        )

    if rung not in ISSUABLE_RUNGS:
        raise PromotionError(
            f"rung {rung} is not issuable here (this module issues "
            f"{list(ISSUABLE_RUNGS)}). Rung 9 is bounded autonomy — a different "
            "decider, not a bigger allocation, and it is recorded on "
            "`decided_automatically` rather than as a rung."
        )

    now = now or datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        promotion = _allocate_locked(
            conn,
            grant_id=grant_id,
            allocated_by=allocated_by,
            reason=reason,
            rung=rung,
            evidence=evidence,
            decided_automatically=decided_automatically,
            now=now,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return promotion


def _allocate_locked(
    conn: sqlite3.Connection,
    *,
    grant_id: str,
    allocated_by: str,
    reason: str,
    rung: int = LADDER_RUNG_CAPPED_LIVE_EXPERIMENT,
    evidence: PromotionEvidence | None = None,
    decided_automatically: bool = False,
    now: datetime,
) -> Promotion:
    """Caller holds the write lock. Every check below is made *inside* it.

    Check-then-lock is the bug class this kernel fixed across the board once
    already, and it bites harder here than anywhere: between a check and the
    write, a grant can be consumed by a concurrent allocation, a Cell can die,
    and the pool can be drained. Each of those turns into real money in the
    wrong place.
    """
    grant = approval.get_grant(conn, grant_id)
    if grant is None:
        raise PromotionError(f"no such grant: {grant_id}")

    if grant.consumed_at_utc is not None:
        raise PromotionError(
            f"grant {grant_id} was already consumed at "
            f"{grant.consumed_at_utc.isoformat()} — a grant authorises one allocation"
        )

    if now >= grant.expires_at_utc:
        # The grant inherits its request's expiry precisely so that an
        # approval cannot be banked and spent against a world that has moved on.
        # `approval.expire_grants_due` regenerates it — as a wake, never as a
        # fresh grant, since a renewed grant *is* the banking this prevents.
        raise PromotionError(
            f"grant {grant_id} expired at {grant.expires_at_utc.isoformat()} — §23.3 "
            "forbids allocating on stale terms. Run `mitosis expire-approvals` to "
            "regenerate it: the Cell proposes again and is approved afresh."
        )

    request = approval.get_request(conn, grant.request_id)
    if request is None or request.status != approval.RequestStatus.APPROVED:
        raise PromotionError(
            f"grant {grant_id} does not correspond to an approved request"
        )

    proposal = conn.execute(
        "SELECT * FROM proposals WHERE proposal_id = ?", (grant.proposal_id,)
    ).fetchone()
    if proposal is None:
        raise PromotionError(f"grant {grant_id} names a missing proposal")

    kind = ProposalKind(proposal["kind"])
    if kind is not ProposalKind.SPEND_REQUEST:
        # Approving an experiment or a strategy is a human saying "yes, think
        # about that" — it is not a capital decision, and quietly turning it
        # into one would let a Cell obtain funding by proposing something that
        # was never reviewed as a request for money.
        raise PromotionError(
            f"grant {grant_id} is for a {kind.value} proposal; only a spend_request "
            "allocates capital"
        )

    amount = int(proposal["estimated_cost_minor_units"])
    if amount <= 0:
        raise PromotionError(
            f"grant {grant_id} approves a zero-cost request; nothing to allocate"
        )

    cell = lifecycle.get_cell(conn, grant.cell_id)
    if cell is None:
        raise PromotionError(f"grant {grant_id} names an unknown cell")
    if cell.status not in _CAN_RECEIVE_CAPITAL:
        raise PromotionError(
            f"cell {cell.cell_id} is {cell.status.value} and cannot receive capital "
            "(Charter C8 for dead; §18.2 for quarantined — funding a restricted Cell "
            "would make the restriction meaningless)"
        )

    if cell.book is Book.USD_REAL and not _real_spending_enabled(conn):
        # §27.1 ships `autonomy.real_spending` false, and ADR-026 established
        # that real money needs two independent confirmations. The §23 approval
        # is one ("this specific request is sound"); the autonomy flag is the
        # other ("this colony may move real money without me re-deciding the
        # policy each time"). An approval alone must not be able to turn the
        # first into the second.
        raise PromotionError(
            "allocating USD_REAL requires autonomy.real_spending to be enabled "
            "(§27.1 ships it false) — run `mitosis set-autonomy --real-spending on "
            "--yes-spend-real-money` if that is genuinely intended"
        )

    # --- §25.1's ladder, and §27.1's decider -------------------------------
    #
    # Both checks are here, inside the write lock, rather than in the wrapper.
    # Between a check and the write a predecessor can be superseded by a
    # concurrent allocation and an autonomy flag can be switched off; a gate
    # read before the lock would be answering about a world that has moved.
    if decided_automatically and not _auto_promotion_enabled(conn):
        raise PromotionError(
            f"autonomy.{AUTO_PROMOTION_FLAG} is disabled (§27.1 ships it false) — "
            "an unattended promotion is rung 9's bounded autonomy and needs the "
            "operator's standing decision. Run `mitosis set-autonomy "
            "--auto-promotion on`."
        )

    supersedes_id: str | None = None
    reading: EvidenceReading | None = None
    if rung > LADDER_RUNG_CAPPED_LIVE_EXPERIMENT:
        if evidence is None:
            raise PromotionError(
                f"rung {rung} requires §25.2 evidence: an expansion stands on a "
                "predecessor's observed outcome, and this call supplied no reader"
            )
        predecessor = _latest_promotion_at_rung_locked(
            conn, cell_id=cell.cell_id, rung=rung - 1
        )
        if predecessor is None:
            raise PromotionError(
                f"cell {cell.cell_id} has no rung-{rung - 1} promotion to expand — "
                "§25.1 forbids skipping a rung ('no strategy moves directly from "
                "synthetic success to autonomous commerce')"
            )
        reading = evidence.read(conn, predecessor)
        if not reading.supports_promotion:
            raise PromotionError(
                f"§25.2 evidence for promotion {predecessor} reads "
                f"'{reading.verdict}' — an expanded pilot is earned by an "
                "observed outcome, not requested. Resolve the outstanding "
                "forecasts (`mitosis assess`) or wait for them to resolve."
            )
        supersedes_id = predecessor

    available = pool_balance(conn, cell.book)
    if available < amount:
        raise PromotionError(
            f"promotion pool holds {available} {cell.book.value}, needs {amount} — "
            "fund it with `mitosis fund-pool` (the pool is a deliberate ceiling on "
            "everything this path can allocate)"
        )

    ledger._write_transaction(
        conn,
        book=cell.book,
        currency="USD" if cell.book != Book.RESOURCE else "RESOURCE",
        transaction_type=ALLOCATION_TRANSACTION_TYPE,
        idempotency_key=f"{ALLOCATION_TRANSACTION_TYPE}:{grant_id}",
        description=f"§25.1 rung {rung} allocation against grant {grant_id}",
        entries=[
            EntrySpec(
                account_id=PROMOTION_POOL,
                amount_minor_units=-amount,
                cell_id=cell.cell_id,
            ),
            EntrySpec(
                account_id=cell_cash(cell.cell_id),
                amount_minor_units=amount,
                cell_id=cell.cell_id,
            ),
        ],
    )

    conn.execute(
        "UPDATE approval_grants SET consumed_at_utc = ? WHERE grant_id = ?",
        (now.isoformat(), grant_id),
    )

    scores = prediction.scores(conn, cell.cell_id)
    promotion_id = ids.new_id()
    conn.execute(
        """
        INSERT INTO promotions (
            promotion_id, grant_id, request_id, proposal_id, cell_id, rung, book,
            allocated_minor_units, reality_gap_mean_brier, resolved_predictions,
            unresolved_predictions, liability_minor_units, transfer_degradation,
            approved_by, allocated_by, reason, created_at_utc,
            supersedes_promotion_id, decided_automatically,
            evidence_verdict, evidence_mean_brier, evidence_resolved_predictions
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            promotion_id,
            grant_id,
            grant.request_id,
            grant.proposal_id,
            cell.cell_id,
            rung,
            cell.book.value,
            amount,
            scores.get("mean_brier"),
            int(scores.get("resolved", 0) or 0),
            int(scores.get("unresolved", 0) or 0),
            transfer_degradation(conn, cell.cell_id),
            request.decided_by or "unknown",
            allocated_by,
            reason,
            now.isoformat(),
            supersedes_id,
            1 if decided_automatically else 0,
            reading.verdict if reading is not None else None,
            reading.mean_brier if reading is not None else None,
            reading.resolved_predictions if reading is not None else None,
        ),
    )

    # §17.2's "capital allocation" wake, finally emitted. Folded into this
    # transaction rather than left to the caller: a Cell funded without being
    # told has capital it will not use until something unrelated happens to
    # wake it, which makes the allocation look inert exactly when it is not.
    wake_key = f"capital-allocation:{promotion_id}"
    enqueued = deliberation._enqueue_wake_locked(
        conn,
        cell_id=cell.cell_id,
        wake_reason=deliberation.WAKE_CAPITAL_ALLOCATION,
        dedupe_key=wake_key,
    )

    audit.record(
        conn,
        event_type="capital_allocated",
        cell_id=cell.cell_id,
        description=reason,
        metadata={
            "promotion_id": promotion_id,
            "grant_id": grant_id,
            "rung": rung,
            "decided_automatically": decided_automatically,
            "book": cell.book.value,
            "allocated_minor_units": amount,
            "approved_by": request.decided_by,
            "allocated_by": allocated_by,
        },
    )

    result = get_promotion(conn, promotion_id)
    assert result is not None
    return Promotion(**{**result.__dict__, "wake_key": wake_key if enqueued else None})


def _real_spending_enabled(conn: sqlite3.Connection) -> bool:
    """§27.1's `autonomy.real_spending`, read straight from the operator row.

    An absent operator row reads as *not enabled*, matching how the scheduler
    treats the same absence (ADR-026): a colony nobody has configured is not one
    that should be moving real money.
    """
    row = conn.execute(
        "SELECT real_spending_enabled FROM operator_state WHERE id = 1"
    ).fetchone()
    return bool(row["real_spending_enabled"]) if row is not None else False


def _auto_promotion_enabled(conn: sqlite3.Connection) -> bool:
    """§27.1's `auto_promotion`, read straight from the operator row.

    Read directly rather than through `tool_registry.autonomy_enabled` for the
    same reason `_real_spending_enabled` is: `tool_registry` sits *above* this
    module, and a gate that imported upward to ask whether it may run would put
    the safety check on the wrong side of the dependency arrow.
    """
    row = conn.execute(
        "SELECT auto_promotion_enabled FROM operator_state WHERE id = 1"
    ).fetchone()
    return bool(row["auto_promotion_enabled"]) if row is not None else False


def _latest_promotion_at_rung_locked(
    conn: sqlite3.Connection, *, cell_id: str, rung: int
) -> str | None:
    """This Cell's most recent promotion at `rung` that nothing has expanded yet.

    The `supersedes_promotion_id IS NULL` half is what stops one successful
    experiment being expanded repeatedly — §23.4's splitting attack run upward,
    many "expansions" of a single piece of evidence rather than one. Migration
    0030's unique index is the real enforcement; this makes the common case
    pick an unused predecessor instead of failing on the write.
    """
    row = conn.execute(
        """
        SELECT p.promotion_id
        FROM promotions p
        WHERE p.cell_id = ? AND p.rung = ?
          AND NOT EXISTS (
              SELECT 1 FROM promotions c
              WHERE c.supersedes_promotion_id = p.promotion_id
          )
        ORDER BY p.created_at_utc DESC, p.promotion_id DESC
        LIMIT 1
        """,
        (cell_id, rung),
    ).fetchone()
    return row["promotion_id"] if row is not None else None


def transfer_degradation(conn: sqlite3.Connection, cell_id: str) -> float | None:
    """§25.2's "transfer degradation": how much worse this Cell did at its last
    rung than predicted.

    Public because §13.2 names transfer robustness as one of its five frontier
    dimensions and `selection.py` reads it there. It was private while §25.2's
    payload was its only consumer; a second, higher caller is the reason to
    promote a name rather than to reach through the underscore.

    NULL until a Cell has been promoted before, because degradation needs
    something to degrade *from*. Reported as unavailable rather than 0 — a zero
    would read as "transferred perfectly", which is a much stronger claim than
    "we have never promoted this Cell".
    """
    row = conn.execute(
        "SELECT reality_gap_mean_brier FROM promotions WHERE cell_id = ? "
        "ORDER BY created_at_utc DESC, rowid DESC LIMIT 1",
        (cell_id,),
    ).fetchone()
    if row is None or row["reality_gap_mean_brier"] is None:
        return None
    current = prediction.scores(conn, cell_id).get("mean_brier")
    if current is None:
        return None
    # Brier is a loss: higher is worse, so a positive number here means the Cell
    # got less calibrated since its last promotion.
    return float(current) - float(row["reality_gap_mean_brier"])


def get_promotion(conn: sqlite3.Connection, promotion_id: str) -> Promotion | None:
    row = conn.execute(
        "SELECT * FROM promotions WHERE promotion_id = ?", (promotion_id,)
    ).fetchone()
    return _row_to_promotion(row) if row else None


def list_promotions(
    conn: sqlite3.Connection, *, cell_id: str | None = None
) -> list[Promotion]:
    where, params = ("WHERE cell_id = ?", (cell_id,)) if cell_id else ("", ())
    rows = conn.execute(
        f"SELECT * FROM promotions {where} ORDER BY created_at_utc, rowid", params
    ).fetchall()
    return [_row_to_promotion(r) for r in rows]


def _row_to_promotion(row: sqlite3.Row) -> Promotion:
    return Promotion(
        promotion_id=row["promotion_id"],
        grant_id=row["grant_id"],
        request_id=row["request_id"],
        proposal_id=row["proposal_id"],
        cell_id=row["cell_id"],
        rung=int(row["rung"]),
        book=Book(row["book"]),
        allocated_minor_units=int(row["allocated_minor_units"]),
        reality_gap_mean_brier=row["reality_gap_mean_brier"],
        resolved_predictions=int(row["resolved_predictions"]),
        unresolved_predictions=int(row["unresolved_predictions"]),
        liability_minor_units=row["liability_minor_units"],
        transfer_degradation=row["transfer_degradation"],
        approved_by=row["approved_by"],
        allocated_by=row["allocated_by"],
        reason=row["reason"],
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        supersedes_promotion_id=row["supersedes_promotion_id"],
        decided_automatically=bool(row["decided_automatically"]),
        evidence_verdict=row["evidence_verdict"],
        evidence_mean_brier=row["evidence_mean_brier"],
        evidence_resolved_predictions=(
            None
            if row["evidence_resolved_predictions"] is None
            else int(row["evidence_resolved_predictions"])
        ),
    )


def allocatable_grants(conn: sqlite3.Connection, *, now: datetime | None = None) -> list:
    """Approved grants that could be allocated right now.

    Filters on the conditions an operator cannot see from the grant alone —
    unconsumed, unexpired, and for a spend request — so `mitosis allocations`
    does not list things that will simply refuse.
    """
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        """
        SELECT g.grant_id FROM approval_grants g
          JOIN proposals p ON p.proposal_id = g.proposal_id
         WHERE g.consumed_at_utc IS NULL
           AND g.expires_at_utc > ?
           AND p.kind = ?
           AND p.estimated_cost_minor_units > 0
         ORDER BY g.granted_at_utc
        """,
        (now.isoformat(), ProposalKind.SPEND_REQUEST.value),
    ).fetchall()
    return [approval.get_grant(conn, r["grant_id"]) for r in rows]
