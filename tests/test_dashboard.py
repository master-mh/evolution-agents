"""The read-only dashboard (`mitosis dashboard`).

The properties defended: it cannot write to the colony — enforced by SQLite,
not by care — and serving every page leaves the database byte-identical; it
never migrates a database behind the code; model-written text is escaped and
the page is forbidden to run scripts (§19.4: a proposal can carry
UNTRUSTED_EXTERNAL content); it listens on loopback only; and its numbers are
the kernel's own readers' numbers.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from mitosis import accounts, dashboard, db, death, ledger, lifecycle
from mitosis.models import Book
from tests.test_workflow_structure import _deliberate, _make_cell, _proposal, _Recording


def _verdict(verdict: str, *issues: str) -> str:
    return json.dumps({"verdict": verdict, **({"issues": list(issues)} if issues else {})})


@pytest.fixture()
def colony(tmp_path):
    path = str(tmp_path / "colony.db")
    conn = db.connect_and_migrate(path)
    loop = _make_cell(conn, structure="self_critique_loop", key="loop")
    _deliberate(conn, loop, _Recording([
        _proposal("draft idea"), _verdict("revise", "vague"), _proposal("revised idea"), _verdict("keep"),
    ]), wake_key="w-loop")
    hostile = _make_cell(conn, structure=None, key="hostile")
    _deliberate(conn, hostile, _Recording([_proposal('<script>alert("x")</script><img src=x onerror=y>')]),
                wake_key="w-hostile")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return {"path": path, "loop": loop.cell_id, "hostile": hostile.cell_id}


@pytest.fixture()
def server(colony):
    srv = dashboard.make_server(colony["path"], port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url: str) -> tuple[int, dict, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode()


def _digest(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# --- it cannot change the colony ----------------------------------------------------


def test_the_dashboard_connection_refuses_every_write(colony):
    conn = dashboard.connect_readonly(colony["path"])
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("UPDATE cells SET status = 'dead'")
    finally:
        conn.close()


def test_serving_every_page_leaves_the_database_byte_identical(colony, server):
    before = _digest(colony["path"])
    for path in ("/", "/api/overview", f"/cell/{colony['loop']}", f"/cell/{colony['hostile']}", "/cell/nope"):
        _get(server + path)
    assert _digest(colony["path"]) == before


def test_a_database_behind_the_code_is_refused_not_migrated(colony):
    rw = db.connect(colony["path"])
    (last,) = rw.execute("SELECT filename FROM schema_migrations ORDER BY filename DESC LIMIT 1").fetchone()
    rw.execute("DELETE FROM schema_migrations WHERE filename = ?", (last,))
    rw.close()

    with pytest.raises(dashboard.DashboardError, match="never migrates"):
        dashboard.connect_readonly(colony["path"])
    rw = db.connect(colony["path"])
    assert rw.execute("SELECT COUNT(*) FROM schema_migrations WHERE filename = ?", (last,)).fetchone()[0] == 0
    rw.close()


def test_a_missing_database_is_refused_rather_than_created(tmp_path):
    missing = tmp_path / "nothing-here.db"
    with pytest.raises(dashboard.DashboardError, match="init"):
        dashboard.connect_readonly(str(missing))
    assert not missing.exists()


# --- untrusted text, and who can reach it --------------------------------------------------


def test_model_written_text_is_escaped_and_the_page_may_not_run_scripts(colony, server):
    for path in ("/", f"/cell/{colony['hostile']}"):
        status, headers, body = _get(server + path)
        assert status == 200
        assert "<script" not in body.lower() and "<img" not in body.lower()
        assert "&lt;script&gt;" in body
        csp = headers["Content-Security-Policy"]
        assert "default-src 'none'" in csp and "script-src" not in csp
        assert headers["X-Content-Type-Options"] == "nosniff"


def test_the_dashboard_listens_on_loopback_and_offers_no_way_not_to(colony):
    srv = dashboard.make_server(colony["path"], port=0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()
    for fn in (dashboard.make_server, dashboard.serve):
        assert "host" not in inspect.signature(fn).parameters


# --- what it shows -----------------------------------------------------------------


def test_its_numbers_are_the_kernels_own(colony):
    conn = dashboard.connect_readonly(colony["path"])
    try:
        data = dashboard.overview(conn)
        for row in data["cells"]:
            cell = lifecycle.get_cell(conn, row["cell_id"])
            record = death.contribution(conn, cell)
            assert (row["revenue"], row["spend"], row["net"]) == (
                record.revenue_minor_units, record.spend_minor_units, record.net_contribution,
            )
            assert row["cash"] == {
                b.value: ledger.get_balance(conn, accounts.cell_cash(cell.cell_id), b) for b in Book
            }
        assert data["integrity"]["hash_chain"] is True
    finally:
        conn.close()


def test_a_self_critique_wake_shows_every_step_it_paid_for(colony, server):
    _, _, body = _get(f"{server}/cell/{colony['loop']}")
    for step in ("critique:0", "revise:0", "critique:1"):
        assert step in body
    assert "revised idea" in body


def test_an_unknown_cell_is_a_404_and_the_json_view_parses(colony, server):
    assert _get(f"{server}/cell/not-a-cell")[0] == 404
    status, headers, body = _get(f"{server}/api/overview")
    assert status == 200 and headers["Content-Type"] == "application/json"
    assert {c["cell_id"] for c in json.loads(body)["cells"]} == {colony["loop"], colony["hostile"]}
