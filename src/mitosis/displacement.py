"""Birth-by-displacement (SPEC.md §9.3, Amendment A2; docs/DECISIONS.md ADR-009).

§9.3: a birth needs capital, a valid child genome, "**an available population
slot or a successful displacement**", and a birth licence. Until now this
kernel only had the first half — a birth denied at carrying capacity stayed
denied, because the objective criteria that identify a displaceable Cell did
not exist. `death.is_objectively_failing` is the predicate §9.3 was waiting on,
and this module is the other side of that seam.

**The constraint that shapes everything here is what displacement must *not*
be able to do.** §9.3 and ADR-009 both say a proposed child's *forecast* can
never trigger a kill — forecasts are unfalsifiable at decision time, so a Cell
family that could displace on one would simply manufacture optimistic
forecasts to evict competitors. The guarantee is structural rather than
checked: `population.Displacer.displace` takes no information about the child
whatsoever, so there is no forecast in scope to be gamed, and no code shape in
this module can reach one. Everything it *does* see — the candidate's balances
and its resolved record — is realised fact, via `death.findings`.

So a displacement is never "this child looks better than that Cell". It is
"that Cell is already objectively failing, and something needs its slot". The
second clause is why displacement is a separate path from `death.reap` rather
than the same one: an objectively-failing Cell is not thereby scheduled for
death, it is merely no longer protected from eviction.

Three restrictions beyond "meets a criterion", each load-bearing:

- **Never the parent.** In `lineage.reproduce` the child is funded from the
  parent's own cash, so displacing the parent would kill a Cell and then move
  money out of it — a dead Cell is inert (Charter C8), and the ordering that
  makes it "work" would be an accident. A lineage buying itself room by
  killing its own root is also exactly the incentive §9.4 exists to suppress.
- **Never a Cell mid-operation.** Committed funds mean a reservation is open;
  killing then strands it, since `kill()` sweeps nothing. `death` already
  reasons this way for `budget_exhausted` (a Cell at zero cash with funds
  committed is *not* exhausted), but domination has no such guard — so this
  is applied here, over every criterion. The same gap in `reap` is real and
  logged in FUTURE_BUILD_HOOKS; it is not this slice's to close.
- **Never on estimated EV.** See `DISPLACEABLE_CRITERIA`.

§9.3's other class of target — "bottom quantile of realised stage
progression" — is not implemented, and cannot be: stages belong to §25's
promotion ladder and no experiment tracking exists (the same Phase 2
prerequisite that blocks `failed_validation_gates` and
`evidence_not_reproducible` in `death`). Displacement therefore selects on the
§10.5 half of §9.3's disjunction only. That makes it strictly more
conservative than the spec permits, which is the correct direction to be
wrong in when the operation is irreversible.
"""

from __future__ import annotations

import sqlite3

from . import death, ledger, lifecycle, population
from .accounts import cell_committed
from .models import Cell, CellStatus

#: Criteria that make a Cell displaceable.
#:
#: §9.3 permits displacing a Cell "already meeting a death criterion in
#: §10.5" — but estimated negative EV is not such a criterion on its own.
#: §10.5 admits it only when evidence is strong *and* an independent Auditor
#: concurs, which is `death.kill_for_negative_ev`'s guarded, twice-signed
#: path. Displacement must never become the back door around that signature,
#: so NEGATIVE_EV is excluded explicitly rather than merely being absent from
#: what `death.findings` happens to return today. DISPLACEMENT itself is
#: excluded because "already failing because it was displaced" is circular.
DISPLACEABLE_CRITERIA = frozenset(death.DeathCriterion) - {
    death.DeathCriterion.NEGATIVE_EV,
    death.DeathCriterion.DISPLACEMENT,
}


def _has_funds_committed(conn: sqlite3.Connection, cell: Cell) -> bool:
    return ledger.get_balance(conn, cell_committed(cell.cell_id), cell.book) != 0


def candidates(
    conn: sqlite3.Connection,
    *,
    require_active: bool = False,
    exclude: frozenset[str] = frozenset(),
) -> list[tuple[Cell, death.Finding]]:
    """Every Cell that may currently be displaced, with the objective finding
    that makes it eligible, in a deterministic order.

    Ordering is by birth order (`death.living_cells` orders by rowid) and is
    **not** a ranking. Ranking candidates by how badly they are doing would
    reintroduce exactly the scalar collapse §10.2 forbids, through the back
    door of "pick the worst one". Every candidate here independently meets an
    objective §10.5 criterion, so any of them is an equally valid target; the
    order exists so that replay is deterministic (§26), not so that it selects.
    """
    found: list[tuple[Cell, death.Finding]] = []
    for cell in death.living_cells(conn):
        if cell.cell_id in exclude:
            continue
        if require_active and cell.status is not CellStatus.ALIVE:
            continue
        if _has_funds_committed(conn, cell):
            continue
        for finding in death.findings(conn, cell.cell_id):
            if finding.criterion in DISPLACEABLE_CRITERIA:
                found.append((cell, finding))
                break  # one ground for eviction is enough; the first is recorded
    return found


class ObjectiveDisplacer:
    """§9.3's `population.Displacer`, evicting only objectively-failing Cells.

    Supplied by a caller that has explicitly chosen eviction over waiting.
    Instantiating one is not itself a decision to kill anything: it evicts
    only when a birth is actually blocked by a cap, and only ever one Cell.
    """

    def displace(
        self,
        conn: sqlite3.Connection,
        *,
        require_active: bool,
        exclude: frozenset[str],
    ) -> population.Displacement | None:
        """Evict one objectively-failing Cell, or return None if there is none.

        The caller holds the write lock, and the kill is folded into it via
        `lifecycle._kill_locked` — the eviction and the birth it makes room
        for commit together or roll back together. A crash between them would
        otherwise leave a Cell dead and its slot unfilled: a death that bought
        nothing, and one no invariant would report, since conservation and the
        hash chain stay green through it.
        """
        eligible = candidates(conn, require_active=require_active, exclude=exclude)
        if not eligible:
            return None

        cell, finding = eligible[0]
        displacement = population.Displacement(
            cell_id=cell.cell_id,
            criterion=finding.criterion.value,
            evidence=dict(finding.evidence),
        )

        lifecycle._kill_locked(
            conn,
            cell,
            cause_of_death=(
                f"{death.DeathCriterion.DISPLACEMENT.value}: displaced at carrying "
                f"capacity while already meeting {finding.describe()}"
            ),
            metadata={
                "displaced": True,
                "underlying_criterion": finding.criterion.value,
                "underlying_evidence": finding.evidence,
            },
        )
        return displacement
