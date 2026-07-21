"""Audit trail (Amendment A8; Charter C10: every lifecycle transition emits
an immutable audit event).

`record` performs a plain INSERT and manages no transaction of its own —
same pattern as `ledger._write_transaction`: callers emit an audit event as
part of a larger atomic operation (e.g. a lifecycle transition) and are
responsible for the surrounding BEGIN/COMMIT.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone


def record(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    cell_id: str | None = None,
    description: str = "",
    metadata: dict | None = None,
) -> str:
    event_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO audit_events (event_id, event_type, cell_id, description,
                                   created_at_utc, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            event_type,
            cell_id,
            description,
            datetime.now(timezone.utc).isoformat(),
            json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
        ),
    )
    return event_id
