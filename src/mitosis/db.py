"""SQLite connection + migration runner, and the one constraint that needs
translating (SPEC.md §2.6, §30.1; ADR-047).

§30.1 coding rule: "write migrations rather than hand-altering DB state."
Migrations are plain numbered .sql files in mitosis/migrations/, applied in
order, tracked in a schema_migrations table, and never edited after they
ship — a schema change is a new migration file.

This module also owns `PRAGMA foreign_keys = ON`, which is why migration 0027's
experiment foreign key is *read back* here. `UnknownExperimentError` is not a
check — the schema has already refused the write by the time it is raised — it
only says which foreign key failed and what was passed, because SQLite will not.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from importlib import resources
from pathlib import Path


class UnknownExperimentError(Exception):
    """A write named an `experiment_id` that no `experiments` row matches.

    Raised *after* migration 0027's foreign key has already refused the write.
    The constraint is the guarantee; this is the sentence explaining it.
    """


def raise_for_unknown_experiment(
    conn: sqlite3.Connection,
    exc: sqlite3.IntegrityError,
    *,
    experiment_ids: Iterable[str | None],
) -> None:
    """Re-raise `exc` as `UnknownExperimentError` when it is the experiment FK.

    SQLite reports every violated foreign key as the same eight words —
    "FOREIGN KEY constraint failed" — naming no column and no value. A
    `model_calls` row declares four foreign keys, so on the table where a
    dangling experiment is most likely, the message is least able to say which
    one broke. ADR-044 recorded that a dangling id "fails silently and only ever
    *subtracts* from a report"; migration 0027 ended the silence, and this ends
    the ambiguity.

    **This adds no enforcement and must not.** It runs only in the error path,
    only after the schema has already refused the row, and it re-raises
    unchanged anything that is not this constraint — so it can never become
    ADR-039's "second, weaker copy" of a rule the schema owns. The lookup is a
    plain SELECT rather than an `experiments` import on purpose: the layering
    that made a Python check need an injected seam applies to this module too.
    """
    if "FOREIGN KEY constraint failed" not in str(exc):
        return
    named = {e for e in experiment_ids if e is not None}
    if not named:
        return
    unknown = sorted(
        e
        for e in named
        if conn.execute(
            "SELECT 1 FROM experiments WHERE experiment_id = ?", (e,)
        ).fetchone()
        is None
    )
    if not unknown:
        return
    listed = ", ".join(repr(e) for e in unknown)
    raise UnknownExperimentError(
        f"no such experiment: {listed}. §2.6's report is derived by joining on "
        "experiment_id, so an id naming nothing does not fail loudly at read "
        "time — it silently subtracts this work from every dimension that would "
        "have counted it. Pass None for work no experiment is accountable for; "
        "`experiments.attribution_for(conn, cell_id)` gives a Cell's current one."
    ) from exc


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)  # manual transaction control
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL" if path != ":memory:" else "PRAGMA journal_mode = MEMORY")
    return conn


def _migration_files() -> list[Path]:
    migrations_dir = resources.files("mitosis") / "migrations"
    return sorted(
        (Path(str(p)) for p in migrations_dir.iterdir() if p.name.endswith(".sql")),
        key=lambda p: p.name,
    )


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply any not-yet-applied migrations in order. Returns applied filenames."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  filename TEXT PRIMARY KEY,"
        "  applied_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ")"
    )
    applied = {row["filename"] for row in conn.execute("SELECT filename FROM schema_migrations")}
    newly_applied: list[str] = []
    for migration_path in _migration_files():
        if migration_path.name in applied:
            continue
        sql = migration_path.read_text()
        # executescript implicitly commits any pending transaction before
        # running and is not itself atomic with the statement below, so this
        # can't be wrapped in a manual BEGIN/COMMIT the way the rest of the
        # kernel is. Acceptable for a local dev-stage migration runner: a
        # crash between the two statements just means the next run needs the
        # schema_migrations row inserted by hand before retrying.
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES (?)",
            (migration_path.name,),
        )
        newly_applied.append(migration_path.name)
    return newly_applied


def connect_and_migrate(path: str = ":memory:") -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn)
    return conn
