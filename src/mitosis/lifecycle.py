"""Cell lifecycle (docs/STATE_MACHINES.md §1; SPEC.md §30).

`create_cell` is the `created -> alive` birth transition. It mirrors
reservations.request: the transient `created` state is never persisted on
its own (nothing observable happens in it alone) — a successful birth
inserts the cell directly as `alive`, atomically with funding it and
recording the genome, in one SQLite write transaction.

Charter C9 ("birth requires carrying-capacity permission") is enforced via
population.check_birth_licence — see that module for what is and isn't
covered (only max_living_cells/max_active_cells). A birth blocked by those
caps may optionally displace an objectively-failing Cell instead of being
denied (§9.3); pass a `displacer`, and see displacement.py.

The remaining transitions (`wake`/`sleep`/`quarantine`/`clear_quarantine`/
`kill`) implement the rest of docs/STATE_MACHINES.md §1.2's adjacency table
via `_ALLOWED_TRANSITIONS`, the same guard-table-as-idempotency-guard shape
`reservations.py` uses: once a Cell leaves a state, retrying the same bare
transition against its new status raises `InvalidTransitionError` rather
than silently reapplying (there's no idempotency_key for these — unlike
`create_cell`/`reservations.request`, they have no ledger effect to
dedupe... except `kill`, whose coroner report is protected the same way:
`coroner_reports.cell_id` is UNIQUE, and DEAD has no outbound transitions in
`_ALLOWED_TRANSITIONS`, so a second `kill()` call always raises before it
could double-insert).

Charter C10 ("every lifecycle transition emits an audit event") applies to
every transition below, not just birth.

Deliberately out of scope for this slice: `kill()` does not sweep the dead
Cell's open reservations or return its committed/cash balances anywhere —
that's a reconciliation concern (arguably the sweeper's, or a future
"colony treasury reclaims a dead Cell's residual balance" step), not part of
the lifecycle transition itself. `quarantine()`/`clear_quarantine()` take a
free-text reason/linked-finding payload rather than a structured taint-label
schema — §18's provenance labels aren't modeled in this kernel yet.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import accounts, audit, genome, ids, ledger, population
from .accounts import cell_cash
from .models import Book, Cell, CellGenome, CellStatus, CellType, CoronerReport, EntrySpec


class LifecycleError(Exception):
    pass


class InvalidTransitionError(LifecycleError):
    pass


_ALLOWED_TRANSITIONS: dict[CellStatus, frozenset[CellStatus]] = {
    CellStatus.ALIVE: frozenset({CellStatus.DORMANT, CellStatus.QUARANTINED, CellStatus.DEAD}),
    CellStatus.DORMANT: frozenset({CellStatus.ALIVE, CellStatus.QUARANTINED, CellStatus.DEAD}),
    CellStatus.QUARANTINED: frozenset({CellStatus.ALIVE, CellStatus.DORMANT, CellStatus.DEAD}),
    # CREATED is transient (handled solely by create_cell) and DEAD is
    # terminal (Charter C8) — neither is a key, so both default to the empty
    # frozenset() below and reject every target.
}


def _check_transition(current: CellStatus, target: CellStatus) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidTransitionError(
            f"cannot transition cell from {current.value!r} to {target.value!r}"
        )


def _displacement_metadata(displaced: population.Displacement | None) -> dict:
    """Audit metadata linking a birth to the Cell it displaced (§9.3). Empty
    for the ordinary case, so a birth into a free slot is not annotated with
    a displacement that never happened."""
    if displaced is None:
        return {}
    return {
        "displaced_cell_id": displaced.cell_id,
        "displaced_criterion": displaced.criterion,
        "displaced_evidence": displaced.evidence,
    }


def _row_to_cell(row: sqlite3.Row) -> Cell:
    return Cell(
        cell_id=row["cell_id"],
        cell_type=CellType(row["cell_type"]),
        genome_hash=row["genome_hash"],
        book=Book(row["book"]),
        status=CellStatus(row["status"]),
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        idempotency_key=row["idempotency_key"],
        parent_cell_id=row["parent_cell_id"],
        founder_cell_id=row["founder_cell_id"],
        generation=row["generation"],
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


def _get_or_create_genome(
    conn: sqlite3.Connection,
    cell_type: CellType,
    *,
    mutation: dict | None = None,
    parent_genome_hashes: tuple[str, ...] = (),
    mutation_operator: str | None = None,
    version: int = 1,
) -> str:
    """Content-addressed upsert (ADR-018): identical canonical content is
    always the same row, so an unmutated child simply reuses its parent's
    genome rather than duplicating it.

    `parent_genome_hashes`/`mutation_operator`/`version` are recorded only
    when this call actually creates the row. A genome that already exists is
    returned untouched — its provenance describes how it *first* came to
    exist, and a later independent rediscovery of the same content must not
    rewrite that history (nor could it meaningfully, since the same content
    can be reached from many parents).
    """
    canonical = genome.canonical_genome_json(cell_type, mutation)
    genome_hash = genome.compute_genome_hash(canonical)
    existing = conn.execute(
        "SELECT genome_hash FROM cell_genomes WHERE genome_hash = ?", (genome_hash,)
    ).fetchone()
    if existing is not None:
        return genome_hash

    # A self-referential parentage edge is meaningless and would corrupt
    # lineage walks; content addressing makes it reachable only if a caller
    # passes a mutation that doesn't actually change anything.
    parents = tuple(h for h in parent_genome_hashes if h != genome_hash)

    conn.execute(
        """
        INSERT INTO cell_genomes (
            genome_id, genome_hash, version, parent_genome_hashes, created_at,
            mutation_operator, canonical_genome_json, prompt_hashes,
            module_hashes, model_policy_hash, risk_label, taint_labels
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', '[]', NULL, 'unclassified', '[]')
        """,
        (
            ids.new_id(),
            genome_hash,
            version,
            json.dumps(list(parents), separators=(",", ":")),
            datetime.now(timezone.utc).isoformat(),
            mutation_operator,
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
    displacer: population.Displacer | None = None,
) -> Cell:
    """Seed a founder Cell, funded from a colony account.

    `displacer` opts this birth into §9.3 displacement: if the colony is at
    carrying capacity, one objectively-failing Cell may be evicted to make
    room rather than the birth being denied. Omitted, the behaviour is
    unchanged — denial. See displacement.py for why the displacer cannot see
    the child it is making room for.
    """
    existing = get_cell_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing

    if budget_minor_units <= 0:
        raise LifecycleError("budget_minor_units must be positive")
    if not accounts.is_known_account(funding_account_id):
        raise LifecycleError(
            f"unrecognized funding_account_id: {funding_account_id!r} "
            "(not a fixed account or cell:{id}:cash|committed)"
        )

    cell_id = ids.new_id()
    now = datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Checked inside the write-locked transaction, not before it: two
        # concurrent births must not both pass this check before either
        # commits (Charter C9 under concurrency). Any displacement happens
        # under this same lock, so eviction and birth are one atomic step.
        displaced = population.check_birth_licence(conn, displacer=displacer)

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

        # A seeded Cell has no parent and founds its own lineage (ADR-019).
        conn.execute(
            """
            INSERT INTO cells (
                cell_id, cell_type, genome_hash, book, status,
                created_at_utc, idempotency_key,
                parent_cell_id, founder_cell_id, generation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 0)
            """,
            (
                cell_id,
                cell_type.value,
                genome_hash,
                book.value,
                CellStatus.ALIVE.value,
                now.isoformat(),
                idempotency_key,
                cell_id,
            ),
        )

        # The displaced Cell is recorded on the *birth* side, never passed to
        # the displacer: §9.3 forbids the child influencing the selection, but
        # once a target has been chosen on its own merits, which birth took
        # its slot is exactly what the audit trail should be able to answer.
        audit.record(
            conn,
            event_type="cell_lifecycle_transition",
            cell_id=cell_id,
            description=f"created -> alive ({cell_type.value}, budget={budget_minor_units} minor units, {book.value})",
            metadata={
                "from": "created",
                "to": "alive",
                "cell_type": cell_type.value,
                **_displacement_metadata(displaced),
            },
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


def _transition_core(
    conn: sqlite3.Connection,
    cell: Cell,
    target: CellStatus,
    *,
    reason: str,
    metadata: dict | None = None,
) -> None:
    """Apply an already-validated status change + its audit event. Caller
    must already hold a write transaction (BEGIN IMMEDIATE) and must have
    called _check_transition first — the non-transactional-core shape
    ledger._write_transaction established, so other modules (events.py's
    poison-event quarantine) can fold a transition into their own atomic
    operation without nesting BEGIN."""
    conn.execute(
        "UPDATE cells SET status = ? WHERE cell_id = ?",
        (target.value, cell.cell_id),
    )
    audit.record(
        conn,
        event_type="cell_lifecycle_transition",
        cell_id=cell.cell_id,
        description=f"{cell.status.value} -> {target.value} ({reason})",
        metadata={"from": cell.status.value, "to": target.value, **(metadata or {})},
    )


def _transition(
    conn: sqlite3.Connection,
    cell_id: str,
    target: CellStatus,
    *,
    reason: str,
    valid_sources: frozenset[CellStatus],
    metadata: dict | None = None,
) -> Cell:
    """`valid_sources` narrows _ALLOWED_TRANSITIONS's per-status adjacency
    down to the specific source(s) a given *semantic* operation may start
    from. This matters because two different operations can share a target:
    both `wake` (dormant -> alive) and `clear_quarantine` (quarantined ->
    alive) end at `alive`, but `wake` must not be usable to spring a
    quarantined Cell loose — only clear_quarantine's explicit review
    decision may do that, even though quarantined -> alive is itself a valid
    FSM edge."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Fetched and re-validated inside the write lock, not before it: two
        # concurrent transitions against the same Cell must not both decide
        # against a pre-lock status (same reasoning as reservations.py).
        cell = get_cell(conn, cell_id)
        if cell is None:
            raise LifecycleError(f"no such cell: {cell_id}")
        if cell.status not in valid_sources:
            raise InvalidTransitionError(
                f"cannot {reason}: cell {cell_id} is {cell.status.value!r}, "
                f"expected one of {sorted(s.value for s in valid_sources)}"
            )
        _check_transition(cell.status, target)

        _transition_core(conn, cell, target, reason=reason, metadata=metadata)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_cell(conn, cell_id)
    assert result is not None
    return result


def sleep(conn: sqlite3.Connection, cell_id: str) -> Cell:
    """alive -> dormant: wake-event processing complete, Cell has no
    pending work (§17.2)."""
    return _transition(
        conn, cell_id, CellStatus.DORMANT,
        reason="wake-event processing complete", valid_sources=frozenset({CellStatus.ALIVE}),
    )


def wake(conn: sqlite3.Connection, cell_id: str) -> Cell:
    """dormant -> alive: a wake event was delivered — scheduled research
    cycle, synthetic customer reply, payment settlement, test completion,
    sibling discovery, capital allocation, market change, audit request, or
    human decision (§17.2). Only from dormant — waking a quarantined Cell
    requires clear_quarantine's explicit review decision instead."""
    return _transition(
        conn, cell_id, CellStatus.ALIVE,
        reason="wake event delivered", valid_sources=frozenset({CellStatus.DORMANT}),
    )


def quarantine(
    conn: sqlite3.Connection,
    cell_id: str,
    *,
    reason: str,
    linked_finding: dict | None = None,
) -> Cell:
    """alive|dormant -> quarantined: policy violation, poison-event threshold
    exceeded (§17.3), or adversarial-lineage taint detected (§18.2). The
    triggering finding is linked in the audit event so the quarantine is
    auditable, not just a status flip (§1.4)."""
    return _transition(
        conn,
        cell_id,
        CellStatus.QUARANTINED,
        reason=reason,
        valid_sources=frozenset({CellStatus.ALIVE, CellStatus.DORMANT}),
        metadata={"linked_finding": linked_finding or {}},
    )


def clear_quarantine(conn: sqlite3.Connection, cell_id: str, *, to_status: CellStatus) -> Cell:
    """quarantined -> alive|dormant: human/Auditor review clears the Cell
    (mirrors the reservation FSM's disputed -> resolved pattern, §4.4).
    Review may only confirm or clear a Cell, never invent a death criterion
    (§1.3) — call kill() separately if review instead confirms death. Only
    from quarantined — this is the sole path back to alive/dormant from
    quarantine; wake()/sleep() are reserved for the dormant<->alive cycle."""
    if to_status not in (CellStatus.ALIVE, CellStatus.DORMANT):
        raise LifecycleError("clear_quarantine target must be alive or dormant")
    return _transition(
        conn, cell_id, to_status,
        reason="quarantine review cleared", valid_sources=frozenset({CellStatus.QUARANTINED}),
    )


def _kill_locked(
    conn: sqlite3.Connection,
    cell: Cell,
    *,
    cause_of_death: str,
    final_hypotheses: list[str] | None = None,
    experiment_ids: list[str] | None = None,
    stage_reached: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Apply the kill + its coroner report. Caller must already hold a write
    transaction (BEGIN IMMEDIATE) and must have re-read `cell` inside it —
    the `_*_locked` core-plus-wrapper split ADR-022 established, so another
    module can fold a death into its own atomic operation without nesting
    BEGIN. §9.3 displacement is the reason this exists: evicting a Cell and
    birthing the child that displaced it must be one transaction, or a crash
    between them kills a Cell to free a slot no birth ever fills.

    Validates the transition itself, so no caller can compose a kill that
    skips Charter C8's terminality check.
    """
    _check_transition(cell.status, CellStatus.DEAD)

    # Computed under the caller's lock so the coroner report reflects a
    # consistent snapshot.
    spend = ledger.spend_by_book(conn, cell.cell_id)

    _transition_core(
        conn, cell, CellStatus.DEAD,
        reason=cause_of_death,
        metadata={"cause_of_death": cause_of_death, **(metadata or {})},
    )
    conn.execute(
        """
        INSERT INTO coroner_reports (
            report_id, cell_id, genome_hash, spend_by_book_json,
            stage_reached, cause_of_death, final_hypotheses_json,
            experiment_ids_json, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ids.new_id(),
            cell.cell_id,
            cell.genome_hash,
            json.dumps(spend, sort_keys=True, separators=(",", ":")),
            stage_reached,
            cause_of_death,
            json.dumps(list(final_hypotheses or []), separators=(",", ":")),
            json.dumps(list(experiment_ids or []), separators=(",", ":")),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def kill(
    conn: sqlite3.Connection,
    cell_id: str,
    *,
    cause_of_death: str,
    final_hypotheses: list[str] | None = None,
    experiment_ids: list[str] | None = None,
    stage_reached: str | None = None,
) -> Cell:
    """alive|dormant|quarantined -> dead (terminal, Charter C8). Files a
    coroner report artifact in the same transaction as the status change
    (SPEC.md §10.5, Amendment A15): genome hash, spend by book (derived from
    the ledger — see ledger.spend_by_book), cause of death, final
    hypotheses, and links to experiments. `stage_reached`/`experiment_ids`
    are always None/empty in this kernel — see module docstring."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Fetched and re-validated inside the write lock — same reasoning as
        # _transition() above.
        cell = get_cell(conn, cell_id)
        if cell is None:
            raise LifecycleError(f"no such cell: {cell_id}")

        _kill_locked(
            conn,
            cell,
            cause_of_death=cause_of_death,
            final_hypotheses=final_hypotheses,
            experiment_ids=experiment_ids,
            stage_reached=stage_reached,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = get_cell(conn, cell_id)
    assert result is not None
    return result


def _row_to_coroner_report(row: sqlite3.Row) -> CoronerReport:
    return CoronerReport(
        report_id=row["report_id"],
        cell_id=row["cell_id"],
        genome_hash=row["genome_hash"],
        spend_by_book=json.loads(row["spend_by_book_json"]),
        stage_reached=row["stage_reached"],
        cause_of_death=row["cause_of_death"],
        final_hypotheses=tuple(json.loads(row["final_hypotheses_json"])),
        experiment_ids=tuple(json.loads(row["experiment_ids_json"])),
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
    )


def get_coroner_report(conn: sqlite3.Connection, cell_id: str) -> CoronerReport | None:
    row = conn.execute(
        "SELECT * FROM coroner_reports WHERE cell_id = ?", (cell_id,)
    ).fetchone()
    return _row_to_coroner_report(row) if row else None


def count_coroner_reports(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM coroner_reports").fetchone()["n"]
