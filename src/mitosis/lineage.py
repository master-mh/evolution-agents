"""Reproduction and lineage tracking (SPEC.md §9.2/§9.4, Amendment A10;
§16 genome parentage; docs/DECISIONS.md ADR-019).

`reproduce()` is the second birth path. Where `lifecycle.create_cell` seeds
a founder funded from a colony account, `reproduce()` births a child of an
existing Cell, **funded from the parent's own cash** — a parent cannot mint
capital, so lineage growth is bounded by the lineage's own earnings. That
funding rule is what makes Charter C4's balance guard apply to reproduction
for free: a parent with 500 minor units simply cannot fund a 600-unit child.

**What "lineage" means here (Amendment A10).** §9.4 defines lineage
"strictly by genome parentage", in explicit contrast to *module* ancestry
(horizontal transfer, §16), which must not count toward lineage caps. This
kernel therefore tracks vertical descent only — `cells.parent_cell_id` — and
never lets a shared module or a shared genome create a lineage edge.

Vertical descent is tracked on the **Cell**, not the genome, and that split
is forced by content addressing rather than chosen for convenience. Phase 1
genomes are placeholders carrying only `cell_type` (see genome.py), so every
Cell of a given type currently hashes to *one* genome row. Deriving lineage
from genome parentage today would put every commercial Cell in the colony
into a single lineage and make `max_lineage_population_fraction` fire on
unrelated Cells — the precise opposite of the founder-effect control §9.4
asks for. Cell parentage is the faithful record of "who descended from
whom"; genome parentage (`cell_genomes.parent_genome_hashes`) is recorded
too, but only where a mutation actually produced different content, since
identical content is by definition the same genome (ADR-018). Once Phase 5
gives genomes real mutable content, the two trees converge and the genome
edges become the richer record; nothing here has to change for that.

**Founder-effect enforcement.** `max_lineage_population_fraction` (§9.2,
previously stored but unenforced) is now checked on every reproduction: a
birth is denied if it would push the parent's founder lineage above the
configured share of the living population. Note the bootstrapping
consequence, which is a real constraint and not an oversight: with the
default 0.20 cap, a colony of 4 seeded founders cannot reproduce at all,
because any lineage of 2 in a population of 5 is already 40%. Growing a
colony past its seed therefore requires either enough founders that a
second-generation Cell stays under the cap, or a deliberately raised cap.
SPEC.md §9.3 says a birth that cannot be licensed "waits"; a synchronous
kernel call cannot wait, so it raises — the same conservative stance
population.py takes for carrying capacity.

Deliberately out of scope for this slice: **displacement** (§9.3, Amendment
A2 / ADR-009) still has no implementation — a denied birth is denied, never
converted into evicting an objectively-failing Cell, because the §10.5 death
criteria that identify one (stage budgets, validation gates, reproducibility)
still don't exist in this kernel. Sexual recombination / multi-parent genomes
(§16.5) are out too: `parent_genome_hashes` is a list and the schema takes
several, but `reproduce()` takes exactly one parent. Inheritance classes
(§16.3 — inheritable vs. liability-linked vs. non-inheritable assets) are not
modeled: a child inherits its parent's genome content and nothing else, since
this kernel has no assets, obligations, customers, or credentials for a child
to inherit or be blocked from inheriting.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import audit, ids, ledger, lifecycle, population
from .accounts import cell_cash
from .models import Book, Cell, CellStatus, CellType, EntrySpec, PopulationLimits


class LineageError(Exception):
    pass


class LineageCapExceededError(LineageError):
    """max_lineage_population_fraction would be exceeded (§9.2/§9.4)."""


# Only a Cell that is actually running should be able to reproduce: a
# dormant Cell is idle, a quarantined Cell is under restriction, and a dead
# Cell is inert (Charter C8). Mirrors the per-operation valid-source-states
# guard lifecycle.py uses for its own transitions.
_CAN_REPRODUCE = frozenset({CellStatus.ALIVE})


def reproduce(
    conn: sqlite3.Connection,
    *,
    parent_cell_id: str,
    budget_minor_units: int,
    idempotency_key: str,
    cell_type: CellType | None = None,
    mutation: dict | None = None,
    mutation_operator: str | None = None,
) -> Cell:
    """Birth a child of `parent_cell_id`, funded from the parent's cash.

    The child inherits the parent's book (funding cannot cross books — §2.4
    forbids an implicit exchange-rate bridge) and, unless `cell_type` says
    otherwise, its type. Supplying a `mutation` gives the child genuinely
    different genome content, and therefore a distinct genome with a
    parent_genome_hashes edge; omitting it means the child shares its
    parent's genome exactly, which under content addressing is the same
    genome row (ADR-018).
    """
    existing = lifecycle.get_cell_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing

    if budget_minor_units <= 0:
        raise LineageError("budget_minor_units must be positive")

    child_id = ids.new_id()
    now = datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Everything below is re-read and re-validated inside the write lock,
        # not before it: two concurrent reproductions against the same parent
        # must not both pass the capacity, lineage-cap, and balance checks
        # before either commits (the check-before-lock bug class fixed across
        # the kernel in slice 10).
        parent = lifecycle.get_cell(conn, parent_cell_id)
        if parent is None:
            raise LineageError(f"unknown parent cell: {parent_cell_id!r}")
        if parent.status not in _CAN_REPRODUCE:
            raise LineageError(
                f"cell {parent_cell_id} cannot reproduce from status "
                f"{parent.status.value} (must be {'/'.join(sorted(s.value for s in _CAN_REPRODUCE))})"
            )

        limits = population.get_limits(conn)
        population.check_birth_licence(conn, limits)
        check_lineage_licence(conn, founder_cell_id=parent.founder_cell_id, limits=limits)

        child_type = cell_type or parent.cell_type
        parent_genome = _genome_hash_of(conn, parent_cell_id)
        genome_hash = lifecycle._get_or_create_genome(
            conn,
            child_type,
            mutation=mutation,
            parent_genome_hashes=(parent_genome,),
            mutation_operator=mutation_operator,
            version=_child_genome_version(conn, parent_genome),
        )

        # Funded from the parent's own cash, so C4's guard (a Cell may never
        # move more than it holds) is what bounds reproduction. ledger's
        # balance check runs inside this same lock.
        _debit_parent_for_child(
            conn,
            parent=parent,
            child_id=child_id,
            budget_minor_units=budget_minor_units,
        )

        conn.execute(
            """
            INSERT INTO cells (
                cell_id, cell_type, genome_hash, book, status,
                created_at_utc, idempotency_key,
                parent_cell_id, founder_cell_id, generation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                child_id,
                child_type.value,
                genome_hash,
                parent.book.value,
                CellStatus.ALIVE.value,
                now.isoformat(),
                idempotency_key,
                parent.cell_id,
                parent.founder_cell_id,
                parent.generation + 1,
            ),
        )

        audit.record(
            conn,
            event_type="cell_lifecycle_transition",
            cell_id=child_id,
            description=(
                f"created -> alive by reproduction from {parent.cell_id} "
                f"({child_type.value}, budget={budget_minor_units} minor units, "
                f"{parent.book.value})"
            ),
            metadata={
                "from": "created",
                "to": "alive",
                "cell_type": child_type.value,
                "parent_cell_id": parent.cell_id,
                "founder_cell_id": parent.founder_cell_id,
                "generation": parent.generation + 1,
                "genome_hash": genome_hash,
                "mutated": bool(mutation),
            },
        )

        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        if "idempotency_key" in str(exc):
            existing = lifecycle.get_cell_by_idempotency_key(conn, idempotency_key)
            if existing is not None:
                return existing
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    child = lifecycle.get_cell(conn, child_id)
    assert child is not None
    return child


def _debit_parent_for_child(
    conn: sqlite3.Connection,
    *,
    parent: Cell,
    child_id: str,
    budget_minor_units: int,
) -> None:
    currency = "USD" if parent.book != Book.RESOURCE else "RESOURCE"
    available = ledger.get_balance(conn, cell_cash(parent.cell_id), parent.book)
    if available < budget_minor_units:
        raise LineageError(
            f"cell {parent.cell_id} cannot fund a {budget_minor_units}-unit child: "
            f"only {available} available in {parent.book.value} (Charter C4)"
        )

    ledger._write_transaction(
        conn,
        book=parent.book,
        currency=currency,
        transaction_type="cell_reproduction_funding",
        idempotency_key=f"cell_reproduction_funding:{child_id}",
        description=f"fund child {child_id} from parent {parent.cell_id}",
        entries=[
            EntrySpec(
                account_id=cell_cash(parent.cell_id),
                amount_minor_units=-budget_minor_units,
                cell_id=parent.cell_id,
            ),
            EntrySpec(
                account_id=cell_cash(child_id),
                amount_minor_units=budget_minor_units,
                cell_id=child_id,
            ),
        ],
    )


def _genome_hash_of(conn: sqlite3.Connection, cell_id: str) -> str:
    row = conn.execute(
        "SELECT genome_hash FROM cells WHERE cell_id = ?", (cell_id,)
    ).fetchone()
    if row is None:
        raise LineageError(f"unknown cell: {cell_id!r}")
    return row["genome_hash"]


def _child_genome_version(conn: sqlite3.Connection, parent_genome_hash: str) -> int:
    row = conn.execute(
        "SELECT version FROM cell_genomes WHERE genome_hash = ?", (parent_genome_hash,)
    ).fetchone()
    return (row["version"] + 1) if row is not None else 1


# --- lineage queries ---------------------------------------------------------


def check_lineage_licence(
    conn: sqlite3.Connection,
    *,
    founder_cell_id: str,
    limits: PopulationLimits | None = None,
) -> None:
    """Raise if one more living Cell in this lineage would exceed
    `max_lineage_population_fraction` (§9.2, §9.4).

    Must be called with a write lock already held, for the same reason
    `population.check_birth_licence` must be: otherwise two concurrent
    births into the same lineage could both pass before either commits.
    """
    limits = limits or population.get_limits(conn)
    cap = limits.max_lineage_population_fraction

    living_total = population.living_count(conn)
    lineage_living = living_lineage_count(conn, founder_cell_id)

    # The child counts toward both its own lineage and the population.
    projected = (lineage_living + 1) / (living_total + 1)
    if projected > cap:
        raise LineageCapExceededError(
            f"birth denied: lineage {founder_cell_id} would hold "
            f"{lineage_living + 1}/{living_total + 1} = {projected:.3f} of the living "
            f"population, above max_lineage_population_fraction={cap} (SPEC.md §9.4). "
            "Seed more founders or raise the cap."
        )


def living_lineage_count(conn: sqlite3.Connection, founder_cell_id: str) -> int:
    """Living Cells (any status but dead) descended from `founder_cell_id`,
    including the founder itself."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cells WHERE founder_cell_id = ? AND status != ?",
        (founder_cell_id, CellStatus.DEAD.value),
    ).fetchone()
    return row["n"]


def lineage_fraction(conn: sqlite3.Connection, founder_cell_id: str) -> float:
    """This lineage's current share of the living population. 0.0 when the
    colony has no living Cells at all."""
    living_total = population.living_count(conn)
    if living_total == 0:
        return 0.0
    return living_lineage_count(conn, founder_cell_id) / living_total


def lineage_members(conn: sqlite3.Connection, founder_cell_id: str) -> list[Cell]:
    """Every Cell in the lineage, living or dead, oldest first."""
    rows = conn.execute(
        "SELECT * FROM cells WHERE founder_cell_id = ? ORDER BY generation, rowid",
        (founder_cell_id,),
    ).fetchall()
    return [lifecycle._row_to_cell(r) for r in rows]


def children(conn: sqlite3.Connection, cell_id: str) -> list[Cell]:
    rows = conn.execute(
        "SELECT * FROM cells WHERE parent_cell_id = ? ORDER BY rowid", (cell_id,)
    ).fetchall()
    return [lifecycle._row_to_cell(r) for r in rows]


def descendants(conn: sqlite3.Connection, cell_id: str) -> list[Cell]:
    """Every Cell below `cell_id` in the parent tree, excluding itself."""
    rows = conn.execute(
        """
        WITH RECURSIVE subtree(cell_id) AS (
            SELECT cell_id FROM cells WHERE parent_cell_id = ?
            UNION ALL
            SELECT c.cell_id FROM cells c JOIN subtree s ON c.parent_cell_id = s.cell_id
        )
        SELECT c.* FROM cells c JOIN subtree s ON c.cell_id = s.cell_id
        ORDER BY c.generation, c.rowid
        """,
        (cell_id,),
    ).fetchall()
    return [lifecycle._row_to_cell(r) for r in rows]


def ancestors(conn: sqlite3.Connection, cell_id: str) -> list[Cell]:
    """Parent chain from immediate parent up to the founder."""
    rows = conn.execute(
        """
        WITH RECURSIVE chain(cell_id, parent_cell_id) AS (
            SELECT cell_id, parent_cell_id FROM cells WHERE cell_id = ?
            UNION ALL
            SELECT c.cell_id, c.parent_cell_id
            FROM cells c JOIN chain ch ON c.cell_id = ch.parent_cell_id
        )
        SELECT c.* FROM cells c JOIN chain ON c.cell_id = chain.cell_id
        WHERE c.cell_id != ?
        ORDER BY c.generation DESC
        """,
        (cell_id, cell_id),
    ).fetchall()
    return [lifecycle._row_to_cell(r) for r in rows]


def founders(conn: sqlite3.Connection) -> list[Cell]:
    rows = conn.execute(
        "SELECT * FROM cells WHERE parent_cell_id IS NULL ORDER BY rowid"
    ).fetchall()
    return [lifecycle._row_to_cell(r) for r in rows]


def lineage_summary(conn: sqlite3.Connection) -> list[dict]:
    """Per-founder lineage sizes and shares, largest living lineage first —
    the founder-effect view §9.4 asks the colony to watch."""
    rows = conn.execute(
        """
        SELECT founder_cell_id,
               COUNT(*) AS total,
               SUM(CASE WHEN status != ? THEN 1 ELSE 0 END) AS living,
               MAX(generation) AS max_generation
        FROM cells
        GROUP BY founder_cell_id
        """,
        (CellStatus.DEAD.value,),
    ).fetchall()

    living_total = population.living_count(conn)
    summary = [
        {
            "founder_cell_id": r["founder_cell_id"],
            "total": r["total"],
            "living": r["living"],
            "max_generation": r["max_generation"],
            "fraction": (r["living"] / living_total) if living_total else 0.0,
        }
        for r in rows
    ]
    summary.sort(key=lambda s: (-s["living"], s["founder_cell_id"]))
    return summary


def verify_lineage_integrity(conn: sqlite3.Connection) -> bool:
    """Re-derive `founder_cell_id` and `generation` from the parent chain and
    confirm the stored values match (see 0009_lineage.sql on why they're
    stored at all). Also catches orphaned parents and parent cycles."""
    rows = conn.execute(
        "SELECT cell_id, parent_cell_id, founder_cell_id, generation FROM cells"
    ).fetchall()
    parents = {r["cell_id"]: r["parent_cell_id"] for r in rows}

    for row in rows:
        cell_id = row["cell_id"]
        depth = 0
        current = cell_id
        seen = {current}
        while parents[current] is not None:
            current = parents[current]
            if current not in parents:
                return False  # parent row missing entirely
            if current in seen:
                return False  # cycle
            seen.add(current)
            depth += 1

        if current != row["founder_cell_id"] or depth != row["generation"]:
            return False

    return True
