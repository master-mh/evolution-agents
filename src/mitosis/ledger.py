"""Ledger: transactions + entries, hash chain, balance/conservation queries.

SPEC.md §3. Charter C1 (balanced per transaction; no transaction crosses
books — structurally guaranteed here since `book` lives on the transaction,
not the entry), C2 (conservation per book), C3 (balances derived, never
authoritative), C11 (canonical forms: UTC timestamps, integer minor units).

`_write_transaction` is the non-transactional core: it assumes the caller
already holds a write transaction (BEGIN IMMEDIATE) and does not itself
check idempotency-key replay. It exists so other modules (reservations.py)
can post a ledger transaction as part of a larger atomic operation without
nesting SQLite transactions. `post_transaction` is the public, standalone
entry point: it checks for idempotency-key replay and manages its own
transaction boundary. `_post_transaction_locked` sits between the two — the
replay check without the transaction boundary — for callers (gateway.py)
composing several money movements into one atomic step.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from . import db, ids
from .accounts import SPEND_DESTINATIONS, cell_cash, cell_committed
from .models import Book, Entry, EntrySpec, Transaction


class LedgerError(Exception):
    pass


class UnbalancedTransactionError(LedgerError):
    pass


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _last_transaction_hash(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT transaction_hash FROM ledger_transactions ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return row["transaction_hash"] if row else None


def _compute_hash(
    *,
    transaction_id: str,
    book: str,
    currency: str,
    created_at_utc: str,
    effective_at_utc: str,
    idempotency_key: str,
    event_id: str | None,
    transaction_type: str,
    description: str,
    previous_transaction_hash: str | None,
    entries: list[dict],
) -> str:
    canonical = {
        "transaction_id": transaction_id,
        "book": book,
        "currency": currency,
        "created_at_utc": created_at_utc,
        "effective_at_utc": effective_at_utc,
        "idempotency_key": idempotency_key,
        "event_id": event_id,
        "transaction_type": transaction_type,
        "description": description,
        "previous_transaction_hash": previous_transaction_hash,
        "entries": entries,
    }
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


def _write_transaction(
    conn: sqlite3.Connection,
    *,
    book: Book,
    currency: str,
    entries: list[EntrySpec],
    transaction_type: str,
    idempotency_key: str,
    description: str = "",
    event_id: str | None = None,
    effective_at_utc: datetime | None = None,
    metadata: dict | None = None,
) -> Transaction:
    """Insert a balanced transaction. Caller must already hold a write
    transaction (BEGIN IMMEDIATE) and be responsible for COMMIT/ROLLBACK."""
    if not entries:
        raise UnbalancedTransactionError("a transaction must have at least one entry")
    total = sum(e.amount_minor_units for e in entries)
    if total != 0:
        raise UnbalancedTransactionError(
            f"entries sum to {total}, must sum to 0 (Charter C1)"
        )

    now = datetime.now(timezone.utc)
    effective = effective_at_utc or now
    if effective.tzinfo is None:
        raise LedgerError("effective_at_utc must be timezone-aware UTC (Charter C11)")

    transaction_id = ids.new_id()
    created_at_iso = now.isoformat()
    effective_at_iso = effective.astimezone(timezone.utc).isoformat()

    entry_rows = []
    canonical_entries = []
    for spec in entries:
        entry_id = ids.new_id()
        entry_rows.append(
            (
                entry_id,
                transaction_id,
                spec.account_id,
                spec.amount_minor_units,
                spec.cell_id,
                spec.team_id,
                spec.experiment_id,
                spec.artifact_id,
                _canonical_json(spec.metadata),
            )
        )
        canonical_entries.append(
            {
                "entry_id": entry_id,
                "account_id": spec.account_id,
                "amount_minor_units": spec.amount_minor_units,
                "cell_id": spec.cell_id,
                "team_id": spec.team_id,
                "experiment_id": spec.experiment_id,
                "artifact_id": spec.artifact_id,
            }
        )

    previous_hash = _last_transaction_hash(conn)
    transaction_hash = _compute_hash(
        transaction_id=transaction_id,
        book=book.value,
        currency=currency,
        created_at_utc=created_at_iso,
        effective_at_utc=effective_at_iso,
        idempotency_key=idempotency_key,
        event_id=event_id,
        transaction_type=transaction_type,
        description=description,
        previous_transaction_hash=previous_hash,
        entries=canonical_entries,
    )

    conn.execute(
        """
        INSERT INTO ledger_transactions (
            transaction_id, book, currency, created_at_utc, effective_at_utc,
            idempotency_key, event_id, transaction_type, description,
            previous_transaction_hash, transaction_hash, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            transaction_id,
            book.value,
            currency,
            created_at_iso,
            effective_at_iso,
            idempotency_key,
            event_id,
            transaction_type,
            description,
            previous_hash,
            transaction_hash,
            _canonical_json(metadata or {}),
        ),
    )
    try:
        conn.executemany(
            """
            INSERT INTO ledger_entries (
                entry_id, transaction_id, account_id, amount_minor_units,
                cell_id, team_id, experiment_id, artifact_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            entry_rows,
        )
    except sqlite3.IntegrityError as exc:
        # Migration 0027's experiment foreign key, named rather than left as
        # "FOREIGN KEY constraint failed". This is the only entry insert in the
        # kernel, so it is also where a *reservation's* experiment_id is first
        # refused: `reservations._request_locked` stamps its id onto these
        # entries before inserting the reservation row, so the ledger always
        # fails first. `test_reservations.py` pins that coupling.
        db.raise_for_unknown_experiment(
            conn, exc, experiment_ids=(row[6] for row in entry_rows)
        )
        raise

    txn = get_transaction(conn, transaction_id)
    assert txn is not None
    return txn


def _post_transaction_locked(
    conn: sqlite3.Connection,
    *,
    book: Book,
    currency: str,
    entries: list[EntrySpec],
    transaction_type: str,
    idempotency_key: str,
    description: str = "",
    event_id: str | None = None,
    effective_at_utc: datetime | None = None,
    metadata: dict | None = None,
) -> Transaction:
    """`post_transaction` minus the transaction boundary: the caller must
    already hold a write transaction (BEGIN IMMEDIATE) and is responsible for
    COMMIT/ROLLBACK. Still idempotent on idempotency_key.

    Exists for the same reason `_write_transaction` does, one level up: a
    caller composing several money movements into a single atomic step
    (gateway.py's success path) needs the replay check without nesting a
    SQLite transaction inside its own.
    """
    existing = get_transaction_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing
    return _write_transaction(
        conn,
        book=book,
        currency=currency,
        entries=entries,
        transaction_type=transaction_type,
        idempotency_key=idempotency_key,
        description=description,
        event_id=event_id,
        effective_at_utc=effective_at_utc,
        metadata=metadata,
    )


def post_transaction(
    conn: sqlite3.Connection,
    *,
    book: Book,
    currency: str,
    entries: list[EntrySpec],
    transaction_type: str,
    idempotency_key: str,
    description: str = "",
    event_id: str | None = None,
    effective_at_utc: datetime | None = None,
    metadata: dict | None = None,
) -> Transaction:
    """Post a balanced, single-book transaction as a standalone operation.

    Idempotent on idempotency_key: replaying the same key returns the
    already-posted transaction instead of erroring or double-posting.
    """
    existing = get_transaction_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing

    conn.execute("BEGIN IMMEDIATE")
    try:
        txn = _post_transaction_locked(
            conn,
            book=book,
            currency=currency,
            entries=entries,
            transaction_type=transaction_type,
            idempotency_key=idempotency_key,
            description=description,
            event_id=event_id,
            effective_at_utc=effective_at_utc,
            metadata=metadata,
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK")
        if "idempotency_key" in str(exc):
            existing = get_transaction_by_idempotency_key(conn, idempotency_key)
            if existing is not None:
                return existing
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return txn


def _row_to_transaction(row: sqlite3.Row, entry_rows: list[sqlite3.Row]) -> Transaction:
    entries = tuple(
        Entry(
            entry_id=r["entry_id"],
            transaction_id=r["transaction_id"],
            account_id=r["account_id"],
            amount_minor_units=r["amount_minor_units"],
            cell_id=r["cell_id"],
            team_id=r["team_id"],
            experiment_id=r["experiment_id"],
            artifact_id=r["artifact_id"],
            metadata=json.loads(r["metadata_json"]),
        )
        for r in entry_rows
    )
    return Transaction(
        transaction_id=row["transaction_id"],
        book=Book(row["book"]),
        currency=row["currency"],
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        effective_at_utc=datetime.fromisoformat(row["effective_at_utc"]),
        idempotency_key=row["idempotency_key"],
        event_id=row["event_id"],
        transaction_type=row["transaction_type"],
        description=row["description"],
        previous_transaction_hash=row["previous_transaction_hash"],
        transaction_hash=row["transaction_hash"],
        metadata=json.loads(row["metadata_json"]),
        entries=entries,
    )


def get_transaction(conn: sqlite3.Connection, transaction_id: str) -> Transaction | None:
    row = conn.execute(
        "SELECT * FROM ledger_transactions WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()
    if row is None:
        return None
    entry_rows = conn.execute(
        "SELECT * FROM ledger_entries WHERE transaction_id = ? ORDER BY rowid",
        (transaction_id,),
    ).fetchall()
    return _row_to_transaction(row, entry_rows)


def get_transaction_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> Transaction | None:
    row = conn.execute(
        "SELECT transaction_id FROM ledger_transactions WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    return get_transaction(conn, row["transaction_id"])


def get_balance(conn: sqlite3.Connection, account_id: str, book: Book) -> int:
    """Charter C3: balance is always derived from ledger entries, never cached."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS balance
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE e.account_id = ? AND t.book = ?
        """,
        (account_id, book.value),
    ).fetchone()
    return row["balance"]


def spend_by_book(
    conn: sqlite3.Connection, cell_id: str, *, since: datetime | None = None
) -> dict[str, int]:
    """Net minor units a Cell has spent — value it *consumed* — by book.

    `since` narrows to transactions posted after an instant, which is what
    §25.2's "cost at this rung" needs: consumption *since the capital arrived*,
    not a lifetime total that a Cell's whole history before the promotion would
    swamp. It filters `created_at_utc`, deliberately **not** `effective_at_utc`
    — a caller may back- or forward-date the effective stamp to a simulated
    instant (§6.3), while every consumer of this window compares against a
    wall-clock record, and mixing the two clocks silently drops or admits rows.

    Measured as the **signed** sum of this Cell's entries landing on a
    `accounts.SPEND_DESTINATIONS` account. Signed, so a reconciliation credit
    reduces the figure; scoped by destination, so capital movements do not
    inflate it.

    The earlier version filtered `amount_minor_units > 0` over every account
    outside the Cell's own pair, and that was wrong in a way worth recording
    because the two errors hid each other. A reconciliation credit debits
    `external_expense` with a negative amount, so the sign filter dropped it and
    a refunded Cell kept its full recorded spend. But simply removing the filter
    would have made a freshly-funded Cell read as having spent a *negative*
    amount, because birth funding's negative leg carries the same cell_id.
    Neither half is fixable alone: the sign matters only once the account is
    known, which is what `accounts.SPEND_DESTINATIONS` now supplies.

    The distinction being drawn is consumption versus capital movement, not
    internal versus external — settling metered compute into
    `infrastructure_reserve` never leaves the colony but is unambiguously cost
    to the Cell. See `accounts.py` for the per-account reasoning.

    Feeds coroner reports (SPEC.md §10.5) today. **It is about to feed fitness**,
    which is why this was worth fixing before selection reads it: a Cell that
    was refunded would otherwise look more expensive than it was, and selection
    would kill the wrong Cells with the error compounding down every generation.
    """
    destinations = tuple(sorted(SPEND_DESTINATIONS))
    placeholders = ", ".join("?" for _ in destinations)
    window, window_params = (
        ("AND t.created_at_utc > ?", (since.astimezone(timezone.utc).isoformat(),))
        if since is not None
        else ("", ())
    )
    rows = conn.execute(
        f"""
        SELECT t.book AS book, COALESCE(SUM(e.amount_minor_units), 0) AS spent
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE e.cell_id = ?
          AND e.account_id IN ({placeholders})
          {window}
        GROUP BY t.book
        """,
        (cell_id, *destinations, *window_params),
    ).fetchall()
    return {r["book"]: r["spent"] for r in rows}


def verify_conservation(conn: sqlite3.Connection, book: Book) -> bool:
    """Charter C2: capital is conserved per book across any event sequence.

    Every posted transaction already sums to zero at post time (enforced in
    _write_transaction), so conservation across the whole book reduces to
    summing every entry ever posted to it and checking it's still zero.
    """
    row = conn.execute(
        """
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE t.book = ?
        """,
        (book.value,),
    ).fetchone()
    return row["total"] == 0


def verify_chain(conn: sqlite3.Connection) -> bool:
    """Recompute each transaction's hash and check linkage (§3.4)."""
    rows = conn.execute("SELECT * FROM ledger_transactions ORDER BY rowid").fetchall()
    previous_hash: str | None = None
    for row in rows:
        if row["previous_transaction_hash"] != previous_hash:
            return False
        entry_rows = conn.execute(
            "SELECT * FROM ledger_entries WHERE transaction_id = ? ORDER BY rowid",
            (row["transaction_id"],),
        ).fetchall()
        canonical_entries = [
            {
                "entry_id": r["entry_id"],
                "account_id": r["account_id"],
                "amount_minor_units": r["amount_minor_units"],
                "cell_id": r["cell_id"],
                "team_id": r["team_id"],
                "experiment_id": r["experiment_id"],
                "artifact_id": r["artifact_id"],
            }
            for r in entry_rows
        ]
        expected = _compute_hash(
            transaction_id=row["transaction_id"],
            book=row["book"],
            currency=row["currency"],
            created_at_utc=row["created_at_utc"],
            effective_at_utc=row["effective_at_utc"],
            idempotency_key=row["idempotency_key"],
            event_id=row["event_id"],
            transaction_type=row["transaction_type"],
            description=row["description"],
            previous_transaction_hash=row["previous_transaction_hash"],
            entries=canonical_entries,
        )
        if expected != row["transaction_hash"]:
            return False
        previous_hash = row["transaction_hash"]
    return True
