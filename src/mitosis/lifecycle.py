"""Cell lifecycle (docs/STATE_MACHINES.md §1; SPEC.md §30).

`create_cell` is the `created -> alive` birth transition. It mirrors
reservations.request: the transient `created` state is never persisted on
its own (nothing observable happens in it alone) — a successful birth
inserts the cell directly as `alive`, atomically with funding it and
recording the genome, in one SQLite write transaction.

Charter C9 ("birth requires carrying-capacity permission") is enforced via
population.check_birth_licence — see that module for what is and isn't
covered (only max_living_cells/max_active_cells; no displacement path yet).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from . import audit, genome, ledger, population
from .accounts import cell_cash
from .models import Book, Cell, CellGenome, CellStatus, CellType, EntrySpec


class LifecycleError(Exception):
    pass


def _row_to_cell(row: sqlite3.Row) -> Cell:
    return Cell(
        cell_id=row["cell_id"],
        cell_type=CellType(row["cell_type"]),
        genome_hash=row["genome_hash"],
        book=Book(row["book"]),
        status=CellStatus(row["status"]),
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        idempotency_key=row["idempotency_key"],
    )


def get_cell(conn: sqlite3.Connection, cell_id: str) -> Cell | None:
    row = conn.execute("SELECT * FROM cells WHERE cell_id = ?", (cell_id,)).fetchone()
    return _row_to_cell(row) if row else None


def get_cell_by_idempotency_key(conn: sqlite3.Connection, idempotency_key: str) -> Cell | None:
    row = conn.execute(
        "SELECT * FROM cells WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return _row_to_cell(row) if row else None


def list_cells(conn: sqlite3.Connection) -> list[Cell]:
    rows = conn.execute("SELECT * FROM cells ORDER BY created_at_utc").fetchall()
    return [_row_to_cell(r) for r in rows]


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM cells GROUP BY status"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def count_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT cell_type, COUNT(*) AS n FROM cells GROUP BY cell_type"
    ).fetchall()
    return {r["cell_type"]: r["n"] for r in rows}


def _get_or_create_genome(conn: sqlite3.Connection, cell_type: CellType) -> str:
    canonical = genome.canonical_genome_json(cell_type)
    genome_hash = genome.compute_genome_hash(canonical)
    existing = conn.execute(
        "SELECT genome_hash FROM cell_genomes WHERE genome_hash = ?", (genome_hash,)
    ).fetchone()
    if existing is not None:
        return genome_hash

    conn.execute(
        """
        INSERT INTO cell_genomes (
            genome_id, genome_hash, version, parent_genome_hashes, created_at,
            mutation_operator, canonical_genome_json, prompt_hashes,
            module_hashes, model_policy_hash, risk_label, taint_labels
        ) VALUES (?, ?, 1, '[]', ?, NULL, ?, '[]', '[]', NULL, 'unclassified', '[]')
        """,
        (
            str(uuid.uuid4()),
            genome_hash,
            datetime.now(timezone.utc).isoformat(),
            json.dumps(canonical, sort_keys=True, separators=(",", ":")),
        ),
    )
    return genome_hash


def create_cell(
    conn: sqlite3.Connection,
    *,
    cell_type: CellType,
    budget_minor_units: int,
    book: Book,
    idempotency_key: str,
    funding_account_id: str = "seed_bank",
) -> Cell:
    existing = get_cell_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing

    if budget_minor_units <= 0:
        raise LifecycleError("budget_minor_units must be positive")

    cell_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Checked inside the write-locked transaction, not before it: two
        # concurrent births must not both pass this check before either
        # commits (Charter C9 under concurrency).
        population.check_birth_licence(conn)

        genome_hash = _get_or_create_genome(conn, cell_type)

        ledger._write_transaction(
            conn,
            book=book,
            currency="USD" if book != Book.RESOURCE else "RESOURCE",
            transaction_type="cell_birth_funding",
            idempotency_key=f"cell_birth_funding:{cell_id}",
            description=f"fund new {cell_type.value} cell {cell_id}",
            entries=[
                EntrySpec(account_id=funding_account_id, amount_minor_units=-budget_minor_units, cell_id=cell_id),
                EntrySpec(account_id=cell_cash(cell_id), amount_minor_units=budget_minor_units, cell_id=cell_id),
            ],
        )

        conn.execute(
            """
            INSERT INTO cells (
                cell_id, cell_type, genome_hash, book, status,
                created_at_utc, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cell_id,
                cell_type.value,
                genome_hash,
                book.value,
                CellStatus.ALIVE.value,
                now.isoformat(),
                idempotency_key,
            ),
        )

        audit.record(
            conn,
            event_type="cell_lifecycle_transition",
            cell_id=cell_id,
            description=f"created -> alive ({cell_type.value}, budget={budget_minor_units} minor units, {book.value})",
            metadata={"from": "created", "to": "alive", "cell_type": cell_type.value},
        )

        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        if "idempotency_key" in str(exc):
            existing = get_cell_by_idempotency_key(conn, idempotency_key)
            if existing is not None:
                return existing
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_cell(conn, cell_id)
    assert result is not None
    return result
