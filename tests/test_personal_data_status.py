"""contains_personal_data becomes tri-state (implementation brief, Slice B,
3/3): 'yes' / 'no' / 'unknown' instead of a boolean.

`fetchers.py` wrote `contains_personal_data=False` for every page it ever
fetched, unconditionally -- it never classified anything, so every False a
fetch produced was a fabricated negative. This file covers the migration's
data translation (0034_personal_data_unknown_status.sql) and the Python-level
plumbing: fetchers -> tool_calls -> artifacts -> context rendering -> CLI.
"""

from __future__ import annotations

import sqlite3

from mitosis import db


def _connect_pre_migration_34() -> sqlite3.Connection:
    """Migrated through 0033, one short of the tri-state change, so a test
    can insert data in the *old* (INTEGER 0/1) shape and watch 0034
    translate it."""
    conn = db.connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  filename TEXT PRIMARY KEY,"
        "  applied_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ")"
    )
    for migration_path in db._migration_files():
        if migration_path.name >= "0034_":
            break
        conn.executescript(migration_path.read_text())
        conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES (?)", (migration_path.name,)
        )
    return conn


def _apply_migration_34(conn: sqlite3.Connection) -> None:
    (path,) = [p for p in db._migration_files() if p.name.startswith("0034_")]
    conn.executescript(path.read_text())


def test_migration_translates_tool_calls_contains_personal_data():
    conn = _connect_pre_migration_34()
    conn.execute("PRAGMA foreign_keys = OFF")
    columns = (
        "tool_call_id, grant_id, proposal_id, cell_id, tool, arguments_json, "
        "status, idempotency_key, started_at_utc, contains_personal_data"
    )
    rows = [
        ("tc-yes", "g1", "p1", "c1", "fetch_url", "{}", "succeeded", "idem-1", "t", 1),
        ("tc-zero", "g1", "p1", "c1", "fetch_url", "{}", "succeeded", "idem-2", "t", 0),
        ("tc-null", "g1", "p1", "c1", "fetch_url", "{}", "failed", "idem-3", "t", None),
    ]
    for row in rows:
        conn.execute(f"INSERT INTO tool_calls ({columns}) VALUES (?,?,?,?,?,?,?,?,?,?)", row)

    _apply_migration_34(conn)

    result = {
        r["tool_call_id"]: r["contains_personal_data"]
        for r in conn.execute("SELECT tool_call_id, contains_personal_data FROM tool_calls")
    }
    assert result["tc-yes"] == "yes"
    # The only writer ever set 0, and never classified anything -- 0 was
    # always a fabricated negative, so the honest translation is 'unknown',
    # not 'no'.
    assert result["tc-zero"] == "unknown"
    # NULL means "nothing to describe" (a failed call) both before and after.
    assert result["tc-null"] is None


def test_migration_translates_artifacts_contains_personal_data():
    conn = _connect_pre_migration_34()
    conn.execute("PRAGMA foreign_keys = OFF")
    columns = (
        "artifact_id, artifact_hash, kind, title, content, content_bytes, "
        "created_by_cell_id, created_at_utc, licence, permitted_uses, "
        "commercial_use, contains_personal_data, retention_rule, source_summary"
    )
    rows = [
        # A real True (nothing has ever produced one, but the migration must
        # still get it right if something someday does).
        ("a-yes", "h1", "report", "t", "c", 1, "cell1", "t", "unknown", "review",
         "unknown", 1, "retain", "https://example.test/"),
        # COLONY_AUTHORED's exact shape: no external sources at all, so False
        # is a real "no", not a fabricated one -- the migration must not
        # "correct" this into 'unknown'.
        ("a-colony", "h2", "report", "t", "c", 1, "cell1", "t", "colony-authored",
         "internal use", "unknown", 0, "retain", "no external sources"),
        # Built from a fetched (or inherited-from-fetched) source: False here
        # was always fabricated.
        ("a-fetched", "h3", "report", "t", "c", 1, "cell1", "t", "unknown",
         "review", "unknown", 0, "retain", "https://example.test/"),
    ]
    for row in rows:
        conn.execute(f"INSERT INTO artifacts ({columns}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)

    _apply_migration_34(conn)

    result = {
        r["artifact_id"]: r["contains_personal_data"]
        for r in conn.execute("SELECT artifact_id, contains_personal_data FROM artifacts")
    }
    assert result["a-yes"] == "yes"
    assert result["a-colony"] == "no"
    assert result["a-fetched"] == "unknown"


def test_migration_leaves_integrity_and_foreign_keys_intact():
    conn = _connect_pre_migration_34()
    _apply_migration_34(conn)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
