"""A read-only web dashboard for watching a colony (`mitosis dashboard`).

**It cannot change the colony, and that is enforced, not intended.** Every
request opens its own SQLite connection with `mode=ro`, so a reader that
quietly wrote — a lazy checkpoint, a cache — would fail loudly here instead of
mutating the books an operator is trying to watch. It never migrates: a
database behind the code is refused with the command that fixes it.

**Model-written text is untrusted.** Proposal summaries, rationales and failure
reasons come from a model reading context that can include
`UNTRUSTED_EXTERNAL` tool results (§19.4). Every value is HTML-escaped, the
page runs no JavaScript at all (refresh is a `<meta>` tag), and the
Content-Security-Policy forbids scripts, so an injected `<script>` is inert
twice over.

**Loopback only.** `serve` binds 127.0.0.1 and takes no host argument; the
page shows balances, prompts' outputs and spend caps, and has no auth. Seeing
it from elsewhere is an SSH tunnel's job, not a flag's.

Numbers come from the kernel's own readers (`death.contribution`,
`real_spend_breaker.snapshot`, `approval.queue`, …) rather than re-derived SQL,
so the dashboard cannot disagree with `mitosis status` (§2.5). The few direct
queries are listings no reader exists for, and read only.
"""

from __future__ import annotations

import html
import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from . import (
    accounts,
    approval,
    clock,
    db,
    death,
    deliberation,
    gateway,
    genome,
    ledger,
    lifecycle,
    money,
    population,
    real_spend_breaker,
    scheduler,
)
from .models import Book, Cell

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_REFRESH_SECONDS = 15
RECENT_DELIBERATIONS = 25

CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; form-action 'none'; frame-ancestors 'none'"


class DashboardError(Exception):
    pass


def connect_readonly(path: str) -> sqlite3.Connection:
    if not Path(path).is_file():
        raise DashboardError(f"no colony database at {path} — run `mitosis --db {path} init` first")
    conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    applied = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
    missing = [p.name for p in db._migration_files() if p.name not in applied]
    if missing:
        conn.close()
        raise DashboardError(
            f"the database is {len(missing)} migration(s) behind this code (first: {missing[0]}); "
            f"the dashboard never migrates — run `mitosis --db {path} status` once"
        )
    return conn


# --- data -----------------------------------------------------------------------


def _money(amount: int, book: Book | str) -> str:
    return money.format_minor_units(amount, book.value if isinstance(book, Book) else book)


def _workflow_by_wake(conn: sqlite3.Connection, wake_keys: list[str]) -> dict[str, dict]:
    if not wake_keys:
        return {}
    marks = ",".join("?" * len(wake_keys))
    rows = conn.execute(
        f"SELECT json_extract(metadata_json, '$.wake_key') AS wake_key, "
        f"json_extract(metadata_json, '$.workflow') AS workflow FROM audit_events "
        f"WHERE event_type = 'cell_deliberated' AND json_extract(metadata_json, '$.wake_key') IN ({marks})",
        wake_keys,
    ).fetchall()
    return {r["wake_key"]: json.loads(r["workflow"]) for r in rows if r["workflow"]}


def _deliberations(conn: sqlite3.Connection, *, cell_id: str | None, limit: int) -> list[dict]:
    where, params = ("WHERE d.cell_id = ?", [cell_id]) if cell_id else ("", [])
    rows = conn.execute(
        f"SELECT d.deliberation_id, d.cell_id, d.wake_key, d.wake_reason, d.status, d.failure_reason, "
        f"d.created_at_utc, d.repair_model_call_id IS NOT NULL AS repaired, p.kind, p.summary, "
        f"p.risk_tier, p.estimated_cost_minor_units "
        f"FROM deliberations d LEFT JOIN proposals p ON p.deliberation_id = d.deliberation_id "
        f"{where} ORDER BY d.created_at_utc DESC, d.rowid DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    found = [dict(r) for r in rows]
    workflows = _workflow_by_wake(conn, [d["wake_key"] for d in found])
    for d in found:
        d["workflow"] = workflows.get(d["wake_key"])
    return found


def _cell_row(conn: sqlite3.Connection, cell: Cell) -> dict:
    record = death.contribution(conn, cell)
    content = deliberation._genome_content(conn, cell)
    last = conn.execute(
        "SELECT status, created_at_utc FROM deliberations WHERE cell_id = ? "
        "ORDER BY created_at_utc DESC, rowid DESC LIMIT 1", (cell.cell_id,),
    ).fetchone()
    wakes = conn.execute("SELECT COUNT(*) FROM deliberations WHERE cell_id = ?", (cell.cell_id,)).fetchone()[0]
    return {
        "cell_id": cell.cell_id,
        "type": cell.cell_type.value,
        "status": cell.status.value,
        "book": cell.book.value,
        "generation": cell.generation,
        "founder_cell_id": cell.founder_cell_id,
        "workflow": genome.workflow_structure_of(content),
        "cash": {b.value: ledger.get_balance(conn, accounts.cell_cash(cell.cell_id), b) for b in Book},
        "revenue": record.revenue_minor_units,
        "spend": record.spend_minor_units,
        "net": record.net_contribution,
        "mean_brier": record.mean_brier,
        "resolved_predictions": record.resolved_predictions,
        "unresolved_predictions": record.unresolved_predictions,
        "death_findings": [f.describe() for f in death.findings(conn, cell.cell_id)],
        "wakes": wakes,
        "last_wake_status": last["status"] if last else None,
        "last_wake_at": last["created_at_utc"] if last else None,
    }


def overview(conn: sqlite3.Connection) -> dict:
    limits = population.get_limits(conn)
    snap = real_spend_breaker.snapshot(conn)
    live = scheduler.liveness(conn)
    pending = approval.queue(conn, status="pending")
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "simulated_time": clock.now(conn).isoformat(timespec="seconds"),
        "health": {
            "verdict": str(live.verdict),
            "healthy": live.healthy,
            "reasons": list(live.reasons),
            "last_tick_at": live.last_tick_at_utc.isoformat() if live.last_tick_at_utc else None,
            "vacation": scheduler.is_on_vacation(conn),
        },
        "integrity": {
            "conservation": {b.value: ledger.verify_conservation(conn, b) for b in Book},
            "hash_chain": ledger.verify_chain(conn),
        },
        "population": {
            "living": population.living_count(conn),
            "max_living": limits.max_living_cells,
            "active": population.active_count(conn),
            "max_active": limits.max_active_cells,
            "by_status": lifecycle.count_by_status(conn),
            "by_type": lifecycle.count_by_type(conn),
        },
        "real_spend": {
            "concurrent_reserved": [snap.concurrent_reserved_minor_units, snap.limits.max_concurrent_reserved_minor_units],
            "last_hour": [snap.spend_last_hour_minor_units, snap.limits.per_hour_minor_units],
            "last_day": [snap.spend_last_day_minor_units, snap.limits.per_day_minor_units],
            "last_month": [snap.spend_last_month_minor_units, snap.limits.per_month_minor_units],
        },
        "providers": gateway.spend_by_provider(conn),
        "model_calls_by_status": gateway.count_by_status(conn),
        "approvals": {
            "pending": len(pending),
            "overdue": sum(1 for r in pending if r.is_overdue()),
            "items": [
                {
                    "request_id": r.request_id,
                    "cell_id": r.cell_id,
                    "tier": r.assessed_tier.value,
                    "exposure": r.exposure_minor_units,
                    "reversible": r.reversible,
                    "overdue": r.is_overdue(),
                }
                for r in pending[:15]
            ],
        },
        "cells": [_cell_row(conn, c) for c in lifecycle.list_cells(conn)],
        "recent_deliberations": _deliberations(conn, cell_id=None, limit=RECENT_DELIBERATIONS),
    }


def cell_detail(conn: sqlite3.Connection, cell_id: str) -> dict | None:
    cell = lifecycle.get_cell(conn, cell_id)
    if cell is None:
        return None
    predictions = [
        dict(r) for r in conn.execute(
            "SELECT claim, probability, resolves_by_utc, outcome, brier_score FROM prediction_register "
            "WHERE cell_id = ? ORDER BY created_at_utc DESC LIMIT 50", (cell_id,),
        )
    ]
    calls = [
        dict(r) for r in conn.execute(
            "SELECT idempotency_key, status, provider, requested_model, input_tokens, output_tokens, "
            "cost_actual_micro_usd, settled_minor_units, latency_ms, error_text, created_at_utc "
            "FROM model_calls WHERE cell_id = ? ORDER BY created_at_utc DESC, rowid DESC LIMIT 50", (cell_id,),
        )
    ]
    return {
        **_cell_row(conn, cell),
        "genome": deliberation._genome_content(conn, cell),
        "parent_cell_id": cell.parent_cell_id,
        "deliberations": _deliberations(conn, cell_id=cell_id, limit=50),
        "predictions": predictions,
        "model_calls": calls,
    }


# --- rendering --------------------------------------------------------------------


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


_STATUS_TONE = {
    "alive": "ok", "proposed": "ok", "succeeded": "ok", "healthy": "ok",
    "dormant": "muted", "refused": "warn", "unparseable": "warn", "quarantined": "warn",
    "dead": "bad", "call_failed": "bad", "failed": "bad", "execution_unknown": "bad",
    "never_ran": "warn", "needs_operator": "warn", "not_running": "bad", "failing": "bad",
    "LOW": "muted", "MEDIUM": "muted", "HIGH": "warn", "CRITICAL": "bad",
}


def _pill(text: Any) -> str:
    return f'<span class="pill {_STATUS_TONE.get(str(text), "muted")}">{_e(text)}</span>'


def _meter(used: int, cap: int, book: str = "USD_REAL") -> str:
    pct = 0 if not cap else min(100, round(100 * used / cap))
    tone = "bad" if pct >= 90 else "warn" if pct >= 70 else "ok"
    return (f'<div class="meter"><div class="fill {tone}" style="width:{pct}%"></div></div>'
            f'<div class="small">{_e(_money(used, book))} of {_e(_money(cap, book))} ({pct}%)</div>')


def _table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f'<p class="muted">{_e(empty)}</p>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _short(cell_id: str | None) -> str:
    if not cell_id:
        return "—"
    return f'<a href="/cell/{_e(cell_id)}"><code>{_e(cell_id[:8])}</code></a>'


def _steps(workflow: dict | None) -> str:
    if not workflow:
        return '<div class="small muted">single pass</div>'
    steps = " → ".join(f'{_e(s["step"])} <span class="muted">({_e(s["note"])})</span>' for s in workflow["steps"])
    return f'<div class="small"><b>{_e(workflow["structure"])}</b>: {steps} · kept <b>{_e(workflow["recorded"])}</b></div>'


def _deliberation_rows(items: list[dict], *, with_cell: bool) -> list[list[str]]:
    rows = []
    for d in items:
        what = (f'<span class="pill muted">{_e(d["kind"])}</span> {_e(d["summary"])}' + _steps(d["workflow"])
                if d["summary"] else f'<span class="muted">{_e(d["failure_reason"])}</span>')
        row = [f'<span class="small">{_e(d["created_at_utc"])[:19]}</span>']
        if with_cell:
            row.append(_short(d["cell_id"]))
        row += [
            _pill(d["status"]) + (' <span class="small muted">repaired</span>' if d["repaired"] else ""),
            _e(d["wake_reason"]),
            what,
        ]
        rows.append(row)
    return rows


_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1c1c1a;--muted:#6b6b66;--line:#e4e3de;--ok:#1f7a4d;--warn:#a86a00;--bad:#b3261e;--accent:#3b5bdb}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#ecebe6;--muted:#9a9993;--line:#2e2d2a;--ok:#5fcf97;--warn:#f0b54a;--bad:#ff8a80;--accent:#8ea4ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between}
h1{font-size:18px;margin:0}h2{font-size:14px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
main{padding:16px 20px;display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;min-width:0}.wide{grid-column:1/-1}
.big{font-size:26px;font-weight:600}.small{font-size:12px}.muted{color:var(--muted)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid currentColor}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.meter{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin:4px 0}.fill{height:100%}
.fill.ok{background:var(--ok)}.fill.warn{background:var(--warn)}.fill.bad{background:var(--bad)}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:500;white-space:nowrap}a{color:var(--accent)}code{font-size:12px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;margin:0}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;margin:0}
"""


def _page(title: str, body: str, *, refresh: int, subtitle: str) -> str:
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f'<meta http-equiv=refresh content="{int(refresh)}">'
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
        f'<header><h1><a href="/" style="color:inherit;text-decoration:none">MITOSIS</a> · {_e(title)}</h1>'
        f'<span class="small muted">{subtitle} · read-only · refreshes every {int(refresh)}s</span></header>'
        f"<main>{body}</main></body></html>"
    )


def render_overview(data: dict, *, refresh: int, db_label: str) -> str:
    h, integ, pop, spend = data["health"], data["integrity"], data["population"], data["real_spend"]
    healthy_books = all(integ["conservation"].values()) and integ["hash_chain"]
    cards = [
        '<section class="card"><h2>Scheduler</h2>'
        f'<div class="big">{_pill(h["verdict"])}</div>'
        f'<div class="small muted">last tick: {_e(h["last_tick_at"] or "never")}'
        f'{" · VACATION (external work paused)" if h["vacation"] else ""}</div>'
        + "".join(f'<div class="small">{_e(r)}</div>' for r in h["reasons"]) + "</section>",

        '<section class="card"><h2>Books</h2>'
        f'<div class="big {"ok" if healthy_books else "bad"}">{"Intact" if healthy_books else "INTEGRITY FAILURE"}</div>'
        + "".join(f'<div class="small">{_e(b)} conservation: {"OK" if ok else "<b class=bad>FAILED</b>"}</div>'
                  for b, ok in integ["conservation"].items())
        + f'<div class="small">hash chain: {"valid" if integ["hash_chain"] else "<b class=bad>BROKEN</b>"}</div></section>',

        '<section class="card"><h2>Population</h2>'
        f'<div class="big">{pop["living"]} <span class="small muted">living of {pop["max_living"]}</span></div>'
        f'<div class="small">active {pop["active"]}/{pop["max_active"]}</div>'
        f'<div class="small muted">{_e(", ".join(f"{k} {v}" for k, v in pop["by_status"].items()) or "no cells yet")}</div></section>',

        '<section class="card"><h2>Real money spent</h2>'
        f'<div class="small">last hour</div>{_meter(*spend["last_hour"])}'
        f'<div class="small">last day</div>{_meter(*spend["last_day"])}'
        f'<div class="small">last ~30 days</div>{_meter(*spend["last_month"])}'
        f'<div class="small">reserved right now</div>{_meter(*spend["concurrent_reserved"])}</section>',

        '<section class="card"><h2>Waiting for you</h2>'
        f'<div class="big {"warn" if data["approvals"]["pending"] else ""}">{data["approvals"]["pending"]}'
        f' <span class="small muted">approval request(s)</span></div>'
        + (f'<div class="small bad">{data["approvals"]["overdue"]} overdue</div>' if data["approvals"]["overdue"] else "")
        + "".join(
            f'<div class="small" title="mitosis approval {_e(a["request_id"])}">'
            f'{"<b class=bad>overdue</b> · " if a["overdue"] else ""}{_pill(a["tier"])} '
            f'{_short(a["cell_id"])} · exposure {_e(_money(a["exposure"], "USD_REAL"))}'
            f'{"" if a["reversible"] else " · irreversible"}</div>'
            for a in data["approvals"]["items"])
        + (f'<div class="small muted">review with <code>mitosis approvals</code></div>' if data["approvals"]["pending"] else "")
        + "</section>",

        '<section class="card"><h2>Model calls</h2>'
        + _table(
            ["provider", "calls", "tokens in/out", "settled"],
            [[_e(n), _e(s["calls"]), f'{_e(s["input_tokens"])} / {_e(s["output_tokens"])}',
              _e(_money(s["settled_minor_units"], "USD_REAL"))] for n, s in data["providers"].items()],
            "no model calls yet",
        )
        + f'<div class="small muted">{_e(", ".join(f"{k} {v}" for k, v in data["model_calls_by_status"].items()))}</div></section>',
    ]
    cell_rows = [[
        _short(c["cell_id"]), _e(c["type"]), _pill(c["status"]), _e(c["generation"]),
        f'<span class="small">{_e(c["workflow"])}</span>',
        f'<span class="small">{_e(_money(c["cash"]["USD_REAL"], "USD_REAL"))} real<br>'
        f'{_e(_money(c["cash"]["USD_SIM"], "USD_SIM"))} sim<br>{_e(c["cash"]["RESOURCE"])} resource</span>',
        _e(_money(c["revenue"], c["book"])), _e(_money(c["spend"], c["book"])),
        f'<b class="{"ok" if c["net"] > 0 else "bad" if c["net"] < 0 else ""}">{_e(_money(c["net"], c["book"]))}</b>',
        _e(f'{c["mean_brier"]:.3f}' if c["mean_brier"] is not None else "—")
        + f'<div class="small muted">{c["resolved_predictions"]} resolved / {c["unresolved_predictions"]} open</div>',
        f'{_e(c["wakes"])}<div class="small">{_pill(c["last_wake_status"]) if c["last_wake_status"] else ""}</div>',
        '<span class="small bad">' + "<br>".join(_e(f) for f in c["death_findings"]) + "</span>" if c["death_findings"] else "—",
    ] for c in data["cells"]]
    cards.append(
        '<section class="card wide"><h2>Cells</h2>'
        + _table(["cell", "type", "status", "gen", "workflow", "cash", "revenue", "spend", "net",
                  "Brier", "wakes", "death criteria"], cell_rows, "no cells yet — `mitosis create-cell`")
        + "</section>"
    )
    cards.append(
        '<section class="card wide"><h2>Recent wakes</h2>'
        + _table(["when", "cell", "outcome", "why woken", "proposal"],
                 _deliberation_rows(data["recent_deliberations"], with_cell=True), "no wakes yet")
        + "</section>"
    )
    subtitle = f'{_e(db_label)} · generated {_e(data["generated_at"])} · simulated time {_e(data["simulated_time"])}'
    return _page("Colony", "".join(cards), refresh=refresh, subtitle=subtitle)


def render_cell(data: dict, *, refresh: int, db_label: str) -> str:
    facts = {
        "status": _pill(data["status"]), "type": _e(data["type"]), "book": _e(data["book"]),
        "generation": _e(data["generation"]), "founder": _short(data["founder_cell_id"]),
        "parent": _short(data["parent_cell_id"]), "workflow": _e(data["workflow"]),
        "revenue (net)": _e(_money(data["revenue"], data["book"])),
        "spend": _e(_money(data["spend"], data["book"])), "net": _e(_money(data["net"], data["book"])),
        "cash": " · ".join(f"{_e(b)} {_e(_money(v, b))}" for b, v in data["cash"].items()),
        "death criteria": "<br>".join(_e(f) for f in data["death_findings"]) or "none met",
    }
    cards = [
        '<section class="card"><h2>Record</h2><dl>'
        + "".join(f"<dt>{_e(k)}</dt><dd>{v}</dd>" for k, v in facts.items()) + "</dl></section>",
        '<section class="card"><h2>Genome</h2>'
        + (f'<pre>{_e(json.dumps(data["genome"], indent=2, ensure_ascii=False))}</pre>'
           if data["genome"] else '<p class="muted">no genome content</p>') + "</section>",
        '<section class="card wide"><h2>Wakes</h2>'
        + _table(["when", "outcome", "why woken", "proposal"],
                 _deliberation_rows(data["deliberations"], with_cell=False), "never woken") + "</section>",
        '<section class="card wide"><h2>Predictions</h2>'
        + _table(["claim", "p", "resolves by", "outcome", "Brier"],
                 [[_e(p["claim"]), _e(p["probability"]), f'<span class="small">{_e(p["resolves_by_utc"])[:10]}</span>',
                   _e("open" if p["outcome"] is None else bool(p["outcome"])), _e(p["brier_score"])]
                  for p in data["predictions"]], "no predictions registered") + "</section>",
        '<section class="card wide"><h2>Model calls</h2>'
        + _table(["when", "step", "status", "model", "tokens", "settled", "error"],
                 [[f'<span class="small">{_e(m["created_at_utc"])[:19]}</span>',
                   f'<code>{_e(m["idempotency_key"].rsplit(":workflow:", 1)[-1] if ":workflow:" in m["idempotency_key"] else "draft")}</code>',
                   _pill(m["status"]), f'{_e(m["provider"])}/{_e(m["requested_model"])}',
                   f'{_e(m["input_tokens"])} / {_e(m["output_tokens"])}',
                   _e(_money(m["settled_minor_units"] or 0, "USD_REAL")),
                   f'<span class="small muted">{_e((m["error_text"] or "")[:160])}</span>']
                  for m in data["model_calls"]], "no model calls") + "</section>",
    ]
    return _page(f"Cell {data['cell_id'][:8]}", "".join(cards), refresh=refresh,
                 subtitle=f"<code>{_e(data['cell_id'])}</code> · {_e(db_label)}")


# --- server -----------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _handler(db_path: str, refresh: int):
    label = Path(db_path).name

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: str, content_type: str) -> None:
            payload = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            try:
                conn = connect_readonly(db_path)
            except DashboardError as exc:
                self._send(503, _page("Unavailable", f'<section class="card wide">{_e(exc)}</section>',
                                      refresh=refresh, subtitle=_e(label)), "text/html; charset=utf-8")
                return
            try:
                if path == "/":
                    self._send(200, render_overview(overview(conn), refresh=refresh, db_label=label),
                               "text/html; charset=utf-8")
                elif path == "/api/overview":
                    self._send(200, json.dumps(overview(conn), default=_jsonable), "application/json")
                elif path.startswith("/cell/"):
                    detail = cell_detail(conn, unquote(path[len("/cell/"):]))
                    if detail is None:
                        self._send(404, _page("Not found", '<section class="card wide">no such cell</section>',
                                              refresh=refresh, subtitle=_e(label)), "text/html; charset=utf-8")
                    else:
                        self._send(200, render_cell(detail, refresh=refresh, db_label=label),
                                   "text/html; charset=utf-8")
                else:
                    self._send(404, "not found", "text/plain; charset=utf-8")
            finally:
                conn.close()

        def log_message(self, *args) -> None:
            pass

    return Handler


def make_server(db_path: str, *, port: int = DEFAULT_PORT, refresh: int = DEFAULT_REFRESH_SECONDS) -> ThreadingHTTPServer:
    connect_readonly(db_path).close()
    return ThreadingHTTPServer((HOST, port), _handler(db_path, refresh))


def serve(db_path: str, *, port: int = DEFAULT_PORT, refresh: int = DEFAULT_REFRESH_SECONDS) -> None:
    server = make_server(db_path, port=port, refresh=refresh)
    print(f"MITOSIS dashboard (read-only) on http://{HOST}:{server.server_address[1]}/ — Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
