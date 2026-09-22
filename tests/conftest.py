import sqlite3

import pytest

from mitosis import db, tracing


@pytest.fixture(autouse=True)
def _no_tracing_from_the_developer_shell(monkeypatch):
    """A developer who opted in to LangSmith for their own wakes must not ship
    the suite's fixtures there (ADR-104). Tracing tests opt back in explicitly."""
    monkeypatch.delenv(tracing.TRACING_ENV, raising=False)
    monkeypatch.delenv(tracing.API_KEY_ENV, raising=False)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = db.connect_and_migrate()
    yield connection
    connection.close()
