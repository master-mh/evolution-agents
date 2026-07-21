"""SQLite connection + migration runner.

§30.1 coding rule: "write migrations rather than hand-altering DB state."
Migrations are plain numbered .sql files in mitosis/migrations/, applied in
order, tracked in a schema_migrations table, and never edited after they
ship — a schema change is a new migration file.
"""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


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
