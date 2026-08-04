"""Death criteria (SPEC.md §10.5, Amendment A15; §9.3 displacement hook).

The last piece of the evolutionary loop. Reproduction has worked since the
lineage slice; what was missing was any principled reason for a Cell to stop.

**§10.5 is more restrictive than "kill the unprofitable", and deliberately so.**
Its primary criteria are *objective*: stage budget exhausted, N consecutive
failed validation gates, evidence that cannot be reproduced, policy violation,
carrying-capacity displacement (§9.3), and domination by a superior
near-duplicate. Then the constitutional guard that shapes this whole module:

    Estimated negative EV **alone must not kill a Cell** unless evidence is
    sufficiently strong *and* an independent Auditor or evaluator concurs.

So the obvious design — compute fitness, kill the bottom — is exactly what the
spec forbids. An estimate is not evidence, and a colony that culls on estimates
selects for Cells that look good to the estimator. `reap` therefore kills only
on *realised* facts, and killing on EV is a separate, guarded entry point that
structurally cannot be reached without a concurring Auditor
(`kill_for_negative_ev`).

**§10.2 forbids collapsing fitness into one scalar** ("use constraints and
portfolio selection"), which is why domination here is **Pareto** domination
across dimensions rather than a ranking on a weighted sum. A Cell is dominated
only if a near-duplicate is at least as good on *every* measured dimension and
strictly better on at least one. Ties, and Cells that are better on one axis and
worse on another, are not dominated — that is the point.

**§10.3 protects Explorers**, which "need no immediate revenue", so comparing
them on net contribution would kill exactly the Cells whose value is
exploratory. Domination handles this without a special case: comparisons are
restricted to near-duplicates, and in this kernel a near-duplicate is a Cell
sharing a genome hash (genomes are content-addressed placeholders per ADR-019,
so this is effectively same-type). An Explorer is therefore only ever compared
against another Explorer.

What is implemented, and what is not:

    budget_exhausted              yes — realised balances
    dominated_by_near_duplicate   yes — realised outcomes, Pareto
    negative_ev                   guarded entry point only, never in `reap`
    failed_validation_gates       no — needs experiment tracking (Phase 2)
    evidence_not_reproducible     no — needs experiment tracking (Phase 2)
    policy_violation              no — §31's `policy_violations` table does not
                                  exist, and inferring it from a quarantine
                                  reason would be guessing: `quarantine` takes
                                  free text and is also used for poison events.
                                  §23 governance is where this belongs.
    displacement                  no — §9.3 is its own slice, but it was blocked
                                  on this module and is now unblocked: see
                                  `is_objectively_failing`.

Nothing here kills automatically on a schedule. `reap` must be called, and
`--dry-run` is the default posture in the CLI, because the first time a colony
can end its own Cells is not the moment to discover a criterion was too eager.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from . import audit, ledger, lifecycle, prediction, revenue
from .accounts import cell_cash, cell_committed
from .models import Book, Cell, CellStatus


class DeathCriterion(StrEnum):
    """§10.5's primary criteria. Members exist for the unimplemented ones so a
    coroner report's `cause_of_death` uses one vocabulary from the start, and so
    the gap is visible in the type rather than only in prose."""

    BUDGET_EXHAUSTED = "budget_exhausted"
    DOMINATED_BY_NEAR_DUPLICATE = "dominated_by_near_duplicate"
    POLICY_VIOLATION = "policy_violation"
    FAILED_VALIDATION_GATES = "failed_validation_gates"
    EVIDENCE_NOT_REPRODUCIBLE = "evidence_not_reproducible"
    DISPLACEMENT = "displacement"
    NEGATIVE_EV = "negative_ev"


#: Criteria `reap` will act on. Everything else is either unimplementable
#: today or, in negative EV's case, constitutionally not automatic.
AUTOMATIC_CRITERIA = frozenset(
    {DeathCriterion.BUDGET_EXHAUSTED, DeathCriterion.DOMINATED_BY_NEAR_DUPLICATE}
)


class DeathError(Exception):
    pass


@dataclass(frozen=True)
class Finding:
    """One objective criterion a Cell currently meets, with the realised
    evidence that shows it. `evidence` reaches the coroner report, so a death is
    always accompanied by the numbers that caused it."""

    cell_id: str
    criterion: DeathCriterion
    evidence: dict[str, object]

    def describe(self) -> str:
        return f"{self.criterion.value}: {self.evidence}"


@dataclass(frozen=True)
class Contribution:
    """A Cell's *realised* record on the dimensions this kernel can measure.

    Deliberately not reduced to a score (§10.2). `net_contribution` is a
    subtraction of two recorded quantities rather than a fitness function; it
    stays a separate field alongside calibration precisely so domination has to
    consider both.
    """

    cell_id: str
    revenue_minor_units: int
    spend_minor_units: int
    mean_brier: float | None
    resolved_predictions: int
    unresolved_predictions: int

    @property
    def net_contribution(self) -> int:
        return self.revenue_minor_units - self.spend_minor_units


def contribution(conn: sqlite3.Connection, cell: Cell) -> Contribution:
    """What a Cell has actually done, from the ledger and the register — never
    a forecast (§9.3: "a proposed child's forecast can never trigger a kill")."""
    scores = prediction.scores(conn, cell.cell_id)
    return Contribution(
        cell_id=cell.cell_id,
        revenue_minor_units=revenue.total_revenue(conn, cell.cell_id, cell.book),
        spend_minor_units=ledger.spend_by_book(conn, cell.cell_id).get(cell.book.value, 0),
        mean_brier=scores["mean_brier"],  # type: ignore[arg-type]
        resolved_predictions=scores["resolved"],  # type: ignore[arg-type]
        unresolved_predictions=scores["unresolved"],  # type: ignore[arg-type]
    )


def _budget_exhausted(conn: sqlite3.Connection, cell: Cell) -> Finding | None:
    """§10.5 "stage budget exhausted". Stages belong to §25's promotion ladder
    and do not exist, so this is the kernel-level form: the Cell holds nothing
    and has nothing pending.

    `committed > 0` means an operation is still in flight, and killing then
    would strand its reservation — so a Cell mid-call is never exhausted, even
    at zero cash.
    """
    cash = ledger.get_balance(conn, cell_cash(cell.cell_id), cell.book)
    committed = ledger.get_balance(conn, cell_committed(cell.cell_id), cell.book)
    if cash > 0 or committed != 0:
        return None
    return Finding(
        cell_id=cell.cell_id,
        criterion=DeathCriterion.BUDGET_EXHAUSTED,
        evidence={"book": cell.book.value, "cash": cash, "committed": committed},
    )


def _has_realised_record(record: Contribution) -> bool:
    """Whether a Cell has done anything a comparison can be based on.

    This gate is load-bearing and its absence is a trap worth naming: net
    contribution alone makes an *idle* Cell (spent nothing, earned nothing, net
    zero) dominate one that invested and has not yet returned. That selects for
    doing nothing, which in an evolutionary colony is the failure mode that
    quietly ends the experiment. A Cell with no realised record is not superior;
    it is unmeasured.
    """
    return (
        record.spend_minor_units != 0
        or record.revenue_minor_units != 0
        or record.resolved_predictions > 0
    )


def _dominates(better: Contribution, worse: Contribution) -> bool:
    """Pareto domination across measured dimensions (§10.2: no scalar collapse).

    At least as good everywhere, strictly better somewhere. Both Cells must have
    a realised record; a dimension only one of them has evidence on is skipped,
    because domination on no evidence is just an opinion with a body count.
    """
    if not (_has_realised_record(better) and _has_realised_record(worse)):
        return False

    strictly_better_somewhere = False

    if better.net_contribution < worse.net_contribution:
        return False
    if better.net_contribution > worse.net_contribution:
        strictly_better_somewhere = True

    # Calibration counts only when both have resolved predictions. A Cell with
    # none is not thereby worse, it is unmeasured — and unresolved predictions
    # are excluded from the mean, so a Cell cannot improve its standing here by
    # leaving its losers open (see prediction.overdue).
    if better.mean_brier is not None and worse.mean_brier is not None:
        if better.mean_brier > worse.mean_brier:  # lower Brier is better
            return False
        if better.mean_brier < worse.mean_brier:
            strictly_better_somewhere = True

    return strictly_better_somewhere


def _dominated_by_near_duplicate(
    conn: sqlite3.Connection, cell: Cell, peers: list[Cell]
) -> Finding | None:
    """§10.5 "dominated by a superior near-duplicate".

    A near-duplicate is a living Cell sharing this one's genome hash. In this
    kernel that is effectively same-type (ADR-018/019: Phase 1 genome content is
    a placeholder), and it is what keeps §10.3 honest — an Explorer is only ever
    compared with another Explorer, never with a revenue-earning Commercial.
    """
    mine = contribution(conn, cell)
    for peer in peers:
        if peer.cell_id == cell.cell_id or peer.genome_hash != cell.genome_hash:
            continue
        theirs = contribution(conn, peer)
        if _dominates(theirs, mine):
            return Finding(
                cell_id=cell.cell_id,
                criterion=DeathCriterion.DOMINATED_BY_NEAR_DUPLICATE,
                evidence={
                    "dominated_by": peer.cell_id,
                    "genome_hash": cell.genome_hash,
                    "net_contribution": mine.net_contribution,
                    "peer_net_contribution": theirs.net_contribution,
                    "mean_brier": mine.mean_brier,
                    "peer_mean_brier": theirs.mean_brier,
                },
            )
    return None


def living_cells(conn: sqlite3.Connection) -> list[Cell]:
    rows = conn.execute(
        "SELECT cell_id FROM cells WHERE status IN (?, ?, ?) ORDER BY rowid",
        (CellStatus.ALIVE.value, CellStatus.DORMANT.value, CellStatus.QUARANTINED.value),
    ).fetchall()
    cells = []
    for row in rows:
        cell = lifecycle.get_cell(conn, row["cell_id"])
        if cell is not None:
            cells.append(cell)
    return cells


def findings(conn: sqlite3.Connection, cell_id: str) -> list[Finding]:
    """Every objective §10.5 criterion this Cell currently meets.

    Empty for a Cell that is merely doing badly — that is the guard working, not
    a gap. Losing money is not a death criterion; having none left is.
    """
    cell = lifecycle.get_cell(conn, cell_id)
    if cell is None:
        raise DeathError(f"no such cell: {cell_id}")
    if cell.status is CellStatus.DEAD:
        return []

    peers = living_cells(conn)
    found = []
    for check in (
        _budget_exhausted(conn, cell),
        _dominated_by_near_duplicate(conn, cell, peers),
    ):
        if check is not None:
            found.append(check)
    return found


def is_objectively_failing(conn: sqlite3.Connection, cell_id: str) -> bool:
    """§9.3's displacement hook: "a child may displace only a Cell already
    failing objective criteria ... or already meeting a death criterion in
    §10.5". Displacement was blocked on this module existing; this is the seam
    it was blocked on."""
    return bool(findings(conn, cell_id))


def reap(
    conn: sqlite3.Connection, *, dry_run: bool = True, final_hypotheses: list[str] | None = None
) -> list[Finding]:
    """Kill every living Cell meeting an objective criterion, returning what was
    found (or would be found, under `dry_run`).

    Defaults to `dry_run=True`. The first time a colony can end its own Cells is
    not the moment to discover that a criterion was too eager, and a death is
    not reversible — a coroner report is filed and Charter C8 makes the Cell
    permanently inert.
    """
    results: list[Finding] = []
    for cell in living_cells(conn):
        for finding in findings(conn, cell.cell_id):
            if finding.criterion not in AUTOMATIC_CRITERIA:
                continue
            results.append(finding)
            if not dry_run:
                lifecycle.kill(
                    conn,
                    cell.cell_id,
                    cause_of_death=finding.describe(),
                    final_hypotheses=final_hypotheses,
                )
            break  # one cause of death per Cell; the first found is recorded
    return results


def kill_for_negative_ev(
    conn: sqlite3.Connection,
    cell_id: str,
    *,
    evidence: str,
    concurring_auditor_cell_id: str,
    final_hypotheses: list[str] | None = None,
) -> Cell:
    """§10.5's guarded path: kill on estimated negative EV.

    Never reachable from `reap`, and refused unless both of §10.5's conditions
    hold — the evidence is stated, and an *independent* Auditor concurs. The
    independence checks are the whole substance of this function:

    - the auditor is not the Cell itself (a Cell cannot sign its own death
      warrant);
    - the auditor is a living Cell of a type whose job this is (auditor or
      immune, §10.4);
    - the concurrence is recorded in the audit trail, so a death on an estimate
      can always be traced to who agreed to it.

    Everything else in this module kills on realised facts. This one is an
    estimate, which is why it is the only one that needs a second signature.
    """
    if not evidence.strip():
        raise DeathError(
            "evidence is required — §10.5 permits a negative-EV death only when "
            "evidence is sufficiently strong, and an unstated case is not strong"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        subject = lifecycle.get_cell(conn, cell_id)
        if subject is None:
            raise DeathError(f"no such cell: {cell_id}")

        if concurring_auditor_cell_id == cell_id:
            raise DeathError(
                "a Cell cannot concur in its own death — §10.5 requires an "
                "*independent* Auditor or evaluator"
            )
        auditor = lifecycle.get_cell(conn, concurring_auditor_cell_id)
        if auditor is None:
            raise DeathError(f"no such concurring auditor: {concurring_auditor_cell_id}")
        if auditor.status is not CellStatus.ALIVE:
            raise DeathError(
                f"concurring auditor {concurring_auditor_cell_id} is "
                f"{auditor.status.value}, not alive — a dead or quarantined Cell "
                "cannot concur (Charter C8)"
            )
        if auditor.cell_type.value not in ("auditor", "immune"):
            raise DeathError(
                f"concurring cell {concurring_auditor_cell_id} is a "
                f"{auditor.cell_type.value}, not an auditor or immune Cell — "
                "§10.5 names an independent Auditor or evaluator"
            )

        audit.record(
            conn,
            event_type="negative_ev_death_concurred",
            cell_id=cell_id,
            description=evidence.strip(),
            metadata={
                "concurring_auditor_cell_id": concurring_auditor_cell_id,
                "auditor_type": auditor.cell_type.value,
            },
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()

    return lifecycle.kill(
        conn,
        cell_id,
        cause_of_death=(
            f"{DeathCriterion.NEGATIVE_EV.value}: {evidence.strip()} "
            f"(concurred by {concurring_auditor_cell_id})"
        ),
        final_hypotheses=final_hypotheses,
    )
