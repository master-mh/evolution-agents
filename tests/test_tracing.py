"""Opt-in LangSmith tracing (SPEC.md §19.3 "network disabled by default", §2.5;
ADR-104).

The properties defended: tracing is off unless the operator set both
variables, and *off* is enforced over LangSmith's and LangChain's own
environment switches; a sealed run and the golden run are never traced; an
opted-in wake is one trace with every call nested under it; and nothing about
tracing — on, off or broken — changes what the kernel records or bills.

The end-to-end tests point LangSmith at a collector on 127.0.0.1, so no byte
leaves the machine.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

langsmith = pytest.importorskip("langsmith")
import langsmith.run_trees  # noqa: E402
import langsmith.utils  # noqa: E402

from mitosis import db, golden, network_seal, tracing  # noqa: E402
from tests.test_workflow_structure import (  # noqa: E402
    _deliberate,
    _make_cell,
    _proposal,
    _recorded_summary,
    _Recording,
)


def _verdict(verdict: str, *issues: str) -> str:
    return json.dumps({"verdict": verdict, **({"issues": list(issues)} if issues else {})})


class _Collector:
    def __init__(self) -> None:
        self.bodies: list[bytes] = []
        collector = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, body: bytes) -> None:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._reply(b'{"batch_ingest_config": {}}')

            def do_POST(self):
                collector.bodies.append(self.rfile.read(int(self.headers.get("content-length") or 0)))
                self._reply(b"{}")

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def runs(self) -> list[dict]:
        """Every run posted, reassembled from LangSmith's multipart ingest, which
        sends a run's `inputs`, `outputs` and `extra` as parts of their own."""
        found: dict[str, dict] = {}
        for body in self.bodies:
            for part in re.split(rb"\r?\n--[^\r\n]+\r?\n", body):
                name = re.search(rb'name="post\.([0-9a-f-]+)(?:\.(\w+))?"', part)
                if not name:
                    continue
                payload = part[part.find(b"\r\n\r\n") + 4:].strip().rstrip(b"-").strip()
                try:
                    value = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                run = found.setdefault(name.group(1).decode(), {})
                if name.group(2):
                    run[name.group(2).decode()] = value
                else:
                    run.update(value)
        return list(found.values())


@pytest.fixture()
def opted_in(monkeypatch):
    collector = _Collector()
    monkeypatch.setenv("LANGSMITH_ENDPOINT", collector.url)
    monkeypatch.setenv(tracing.TRACING_ENV, "true")
    monkeypatch.setenv(tracing.API_KEY_ENV, "test-key-never-sent-anywhere-real")
    monkeypatch.delenv(tracing.PROJECT_ENV, raising=False)
    monkeypatch.setattr(langsmith.run_trees, "_CLIENT", None)
    yield collector
    client = langsmith.run_trees._CLIENT
    if client is not None:
        client.flush()
        client.close()
    collector.server.shutdown()


def _flush() -> None:
    langsmith.run_trees.get_cached_client().flush()


# --- the decision ---------------------------------------------------------------


@pytest.mark.parametrize("flag, key, expected", [
    (None, None, False),
    ("true", None, False),
    (None, "k", False),
    ("false", "k", False),
    ("1", "k", False),
    ("true", "  ", False),
    ("true", "k", True),
    ("TRUE", "k", True),
])
def test_tracing_is_off_unless_the_operator_set_both_variables(monkeypatch, flag, key, expected):
    for name, value in ((tracing.TRACING_ENV, flag), (tracing.API_KEY_ENV, key)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert tracing.enabled() is expected


def test_the_project_defaults_to_my_first_agent(monkeypatch):
    monkeypatch.delenv(tracing.PROJECT_ENV, raising=False)
    assert tracing.project() == "my-first-agent"
    monkeypatch.setenv(tracing.PROJECT_ENV, "another")
    assert tracing.project() == "another"


def test_a_sealed_run_is_never_traced(opted_in):
    """A sealed run has promised it cannot reach outside the interpreter
    (ADR-085); LangSmith's uploader is outside."""
    assert tracing.enabled()
    with network_seal.sealed(reason="test"):
        assert not tracing.enabled()


def test_off_overrides_langchains_own_environment_switches(monkeypatch):
    """A variable exported for some other project must not switch tracing on
    here. Inside a span, both LangSmith and LangChain must see it off."""
    from langchain_core.tracers.context import _tracing_v2_is_enabled

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "k")
    assert langsmith.utils.tracing_is_enabled(), "precondition: the library alone would trace"
    with tracing.span("probe") as span:
        assert not span.recording
        assert not langsmith.utils.tracing_is_enabled()
        assert not _tracing_v2_is_enabled()


# --- an opted-in wake ------------------------------------------------------------------


def test_an_opted_in_wake_is_one_trace_with_every_call_nested(conn, opted_in):
    cell = _make_cell(conn, structure="self_critique_loop")
    provider = _Recording([
        _proposal("draft idea"), _verdict("revise", "vague"), _proposal("revised idea"), _verdict("keep"),
    ])
    _deliberate(conn, cell, provider)
    _flush()

    runs = opted_in.runs()
    by_name: dict[str, list[dict]] = {}
    for run in runs:
        by_name.setdefault(run["name"], []).append(run)
    (root,) = by_name["cell_wake"]
    assert root.get("parent_run_id") is None
    assert root["session_name"] == "my-first-agent"
    assert {run["trace_id"] for run in runs} == {root["id"]}, "one wake, one trace"

    model_calls = by_name["model_call"]
    assert len(model_calls) == provider.calls == 4
    assert all(run["run_type"] == "llm" for run in model_calls)
    ids = sorted(run["extra"]["metadata"]["idempotency_key"] for run in model_calls)
    assert ids == sorted(
        row[0] for row in conn.execute("SELECT idempotency_key FROM model_calls")
    ), "each span names the model_calls row it mirrors"
    assert len(by_name["critique"]) == 2 and len(by_name["revise"]) == 1, (
        "LangGraph's node runs nest in the same trace"
    )


def test_tracing_changes_nothing_the_kernel_records(conn, opted_in):
    cell = _make_cell(conn, structure="self_critique_loop")
    _deliberate(conn, cell, _Recording([_proposal("draft idea"), _verdict("keep")]))
    _flush()
    assert opted_in.runs(), "precondition: this wake was traced"

    untraced = db.connect_and_migrate()
    try:
        tracing_off = pytest.MonkeyPatch()
        tracing_off.delenv(tracing.TRACING_ENV)
        try:
            other = _make_cell(untraced, structure="self_critique_loop")
            _deliberate(untraced, other, _Recording([_proposal("draft idea"), _verdict("keep")]))
        finally:
            tracing_off.undo()

        def shape(c):
            return (
                c.execute("SELECT status, input_tokens, output_tokens FROM model_calls ORDER BY rowid").fetchall(),
                c.execute("SELECT status FROM deliberations").fetchall(),
            )

        assert [tuple(r) for r in shape(conn)[0]] == [tuple(r) for r in shape(untraced)[0]]
        assert [tuple(r) for r in shape(conn)[1]] == [tuple(r) for r in shape(untraced)[1]]
        assert _recorded_summary(conn, cell) == _recorded_summary(untraced, other)
    finally:
        untraced.close()


def test_a_tracing_fault_never_costs_a_model_call(conn, opted_in, monkeypatch):
    """The gateway opens its span after committing a reservation. A tracing
    library that raises there must not strand it (ADR-104)."""

    def broken(*args, **kwargs):
        raise RuntimeError("the tracing library is broken")

    monkeypatch.setattr(langsmith, "trace", broken)
    cell = _make_cell(conn, structure=None)
    provider = _Recording([_proposal("probe firms")])
    _deliberate(conn, cell, provider)

    assert provider.calls == 1
    assert _recorded_summary(conn, cell) == "probe firms"
    assert conn.execute("SELECT status FROM model_calls").fetchone()[0] == "succeeded"


def test_the_golden_run_is_never_traced(opted_in):
    """A replay must not ship its wakes to a third party any more than it may
    fetch a page (golden.py's own rule)."""
    replay = db.connect_and_migrate()
    try:
        golden.run_scenario(replay)
    finally:
        replay.close()
    assert langsmith.run_trees._CLIENT is None, "nothing even constructed an uploader"
    assert opted_in.bodies == []
