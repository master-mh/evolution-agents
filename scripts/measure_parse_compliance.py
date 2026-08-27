#!/usr/bin/env python
"""Live proposal parse-compliance measurement against a local model.

    .venv/bin/python scripts/measure_parse_compliance.py \
        --model llama3.2 --runs 4 --wakes 8 --out /tmp/arms [--temperature 0.8]

Writes one colony database per run (`arm_<tag>_run<i>.db`) plus a JSON summary,
and prints parse rate with per-run spread. Feed the same directory to
`scripts/diversity.py` for the semantic diversity half -- **parse rate alone is
not a sufficient report** (ADR-050: it is maximised at temperature 0, which does
not reliably buy compliance and freezes the Cell).

Why this is a script and not a test. It costs real model time and needs a
running Ollama, so it cannot sit in the suite -- and `MockProvider` structurally
cannot replace it, because its reply is an input rather than a response to the
prompt's wording. That blind spot has now hidden two live regressions
(ADR-049's enum bug, then its conditional payloads). Every new `ProposalKind` or
payload spec should be measured with this before it ships.

Design notes, each of which cost something to learn:

  - **Fresh colony per run.** ADR-048 measured a paid model against a history a
    local model had written on the same Cell, which is not a comparison.
  - **One connection reused across a run's wakes.** `connect_and_migrate` per
    wake re-checks every migration; on a memory-bound box that overhead dwarfed
    the model call and made a 25-minute arm take four hours.
  - **Only one model resident at a time** when comparing arms. `latency_ms`
    times the HTTP call, but memory pressure lives inside that window -- a
    latency taken with a second model loaded measures the box, not the model.
    `ollama stop <other-model>` between arms.
  - **In-process rather than via the CLI**, for exactly one reason: `mitosis
    wake` has no `--timeout` and `OllamaProvider` defaults to 120s, so a slow
    local model is recorded as an unparseable empty reply -- a timeout wearing a
    compliance failure's clothes. Every other argument mirrors `cmd_wake`.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
MITOSIS = REPO / ".venv" / "bin" / "mitosis"

GENOME = {
    "cell_type": "commercial",
    "market": "independent bookkeepers serving 5-20 small retail clients",
    "problem": "month-end reconciliation between POS exports and bank feeds is manual and error-prone",
    "product": "a hosted reconciliation report that flags unmatched transactions with a suggested match",
    "revenue_model": "flat monthly subscription per bookkeeper seat, billed in advance",
    "acquisition_channel": "bookkeeping community forums and accountant referral",
    "workflow": "ingest exports, match on amount+date window, rank residual candidates, publish report",
    "model_policy": "prefer local models for drafting; escalate only for customer-facing text",
    "mutation_rate": 0.1,
    "allowed_tools": ["http_fetch"],
    "risk_class": "MEDIUM",
}

REQUIRED = ("kind", "summary", "rationale", "risk_tier", "estimated_cost_minor_units")
NESTED = ("experiment", "tool_request", "external_action", "artifact", "predictions")
FLATTEN_MARKERS = ("hypothesis", "success_criteria", "tool_name", "channel", "counterparty")


def _cli(db: pathlib.Path, *args: str) -> str:
    result = subprocess.run([str(MITOSIS), "--db", str(db), *args],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"mitosis {' '.join(args[:1])} failed: {result.stderr.strip()}")
    return result.stdout


def setup(db: pathlib.Path, out_dir: pathlib.Path, genome: dict) -> str:
    if db.exists():
        db.unlink()
    genome_path = out_dir / "genome.json"
    genome_path.write_text(json.dumps(genome, indent=2))
    _cli(db, "init")
    stdout = _cli(db, "create-cell", "--type", "commercial", "--budget", "5.00",
                  "--book", "USD_SIM", "--genome", str(genome_path))
    cell_id = next(
        (tok for line in stdout.splitlines()
         for tok in line.replace(":", " ").replace(",", " ").split()
         if len(tok) >= 30 and tok.count("-") == 4), None)
    if cell_id is None:
        raise SystemExit(f"could not find a cell id in:\n{stdout}")
    # The gateway reserves USD_REAL and RESOURCE regardless of the Cell's own book.
    for book, amount in (("USD_REAL", "1.00"), ("RESOURCE", "20000")):
        _cli(db, "fund-cell", "--cell", cell_id, "--amount", amount, "--book", book)
    return cell_id


def make_provider(providers, timeout: float, temperature: float | None):
    provider = providers.OllamaProvider(timeout_seconds=timeout)
    if temperature is None:
        return provider
    inner = provider._post

    def _post(path, payload):
        if path == "/api/chat":
            payload.setdefault("options", {})["temperature"] = temperature
        return inner(path, payload)

    provider._post = _post
    return provider


def run_wakes(db, cell_id, model, prefix, count, timeout, temperature) -> None:
    from mitosis import approval, deliberation, lifecycle, providers
    from mitosis import db as db_mod

    conn = db_mod.connect_and_migrate(str(db))
    try:
        cell = lifecycle.get_cell(conn, cell_id)
        assert cell is not None
        for i in range(count):
            started = time.time()
            try:
                deliberation.deliberate(
                    conn,
                    cell_id=cell.cell_id,
                    provider=make_provider(providers, timeout, temperature),
                    wake_key=f"{prefix}:w{i}",
                    wake_reason=deliberation.WAKE_SCHEDULED_RESEARCH,
                    model=model,
                    proposal_sink=approval.QueueSink(),
                )
                note = "ok"
            except Exception as exc:  # recorded, not swallowed
                note = f"!! {type(exc).__name__}: {exc}"
            print(f"  wake {i:2d}  {time.time() - started:6.1f}s  {note}", flush=True)
    finally:
        conn.close()


def first_json_object(text: str):
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                except ValueError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def analyse(db: pathlib.Path) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT d.status, d.failure_reason, m.response_text, m.output_tokens, "
        "m.input_tokens, m.stop_reason, m.latency_ms, m.response_hash "
        "FROM deliberations d LEFT JOIN model_calls m "
        "ON d.model_call_id = m.model_call_id ORDER BY d.created_at_utc").fetchall()
    summaries = [r[0] for r in conn.execute("SELECT summary FROM proposals")]
    conn.close()

    res = {"n": len(rows), "proposed": 0, "unparseable": 0, "refused": 0,
           "all_required_present": 0, "correctly_nested": 0, "flattened": 0,
           "not_json": 0, "latency_ms": [], "output_tokens": [],
           "distinct_response_hashes": len({r["response_hash"] for r in rows
                                            if r["response_hash"]}),
           "distinct_summaries": len({s.strip().lower() for s in summaries}),
           "failures": []}
    for row in rows:
        res[row["status"]] = res.get(row["status"], 0) + 1
        if row["latency_ms"] is not None:
            res["latency_ms"].append(row["latency_ms"])
        if row["output_tokens"] is not None:
            res["output_tokens"].append(row["output_tokens"])
        obj = first_json_object(row["response_text"] or "")
        if obj is None:
            res["not_json"] += 1
        else:
            res["all_required_present"] += all(k in obj for k in REQUIRED)
            res["correctly_nested"] += any(isinstance(obj.get(k), (dict, list)) for k in NESTED)
            res["flattened"] += any(k in obj for k in FLATTEN_MARKERS)
        if row["status"] != "proposed" and row["failure_reason"]:
            res["failures"].append(row["failure_reason"][:300])
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--wakes", type=int, default=8)
    ap.add_argument("--out", required=True, help="directory for the colony databases")
    ap.add_argument("--temperature", type=float, default=None,
                    help="override sampling temperature; omit to use the endpoint default "
                         "(0.8 for Ollama -- see ADR-050 before pinning this)")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--genome", help="JSON genome file; omit for the tight baseline above "
                                     "(ADR-056's arms live in scripts/genomes/)")
    args = ap.parse_args()

    out_dir = pathlib.Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO / "src"))

    genome = GENOME
    tag = args.model.replace(":", "_").replace(".", "_")
    if args.genome:
        genome = json.loads(pathlib.Path(args.genome).expanduser().read_text())
        tag += "_" + pathlib.Path(args.genome).stem
    if args.temperature is not None:
        tag += "_t" + str(args.temperature).replace(".", "")

    agg = {"model": args.model, "temperature": args.temperature,
           "genome": args.genome or "(module default)",
           "n": 0, "proposed": 0, "per_run": []}
    for run_index in range(args.runs):
        db = out_dir / f"arm_{tag}_run{run_index}.db"
        cell_id = setup(db, out_dir, genome)
        print(f"[{args.model} t={args.temperature}] run {run_index}: cell {cell_id}", flush=True)
        run_wakes(db, cell_id, args.model, f"{tag}:r{run_index}", args.wakes,
                  args.timeout, args.temperature)
        res = analyse(db)
        agg["n"] += res["n"]
        agg["proposed"] += res["proposed"]
        agg["per_run"].append({
            "parsed": res["proposed"], "n": res["n"],
            "distinct_summaries": res["distinct_summaries"],
            "distinct_response_hashes": res["distinct_response_hashes"],
            "flattened": res["flattened"], "not_json": res["not_json"],
            "median_latency_s": round(
                sorted(res["latency_ms"])[len(res["latency_ms"]) // 2] / 1000, 1)
            if res["latency_ms"] else None,
            "failures": res["failures"],
        })
        print(f"  -> parsed {res['proposed']}/{res['n']}  "
              f"distinct summaries {res['distinct_summaries']}  "
              f"distinct replies {res['distinct_response_hashes']}", flush=True)

    print(f"\n=== {args.model} t={args.temperature}: "
          f"parsed {agg['proposed']}/{agg['n']} ===")
    print("per-run parsed:  ", [r["parsed"] for r in agg["per_run"]])
    print("per-run distinct:", [r["distinct_summaries"] for r in agg["per_run"]])
    print("\nParse rate is only half the report. Now run:")
    print(f"  .venv/bin/python scripts/diversity.py {out_dir} --pattern 'arm_{tag}_run*.db'")
    (out_dir / f"result_{tag}.json").write_text(json.dumps(agg, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
