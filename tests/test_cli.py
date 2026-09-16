import socket
from pathlib import Path

import pytest

from mitosis import cli


def test_init_creates_db(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    exit_code = cli.main(["--db", str(db_path), "init"])
    assert exit_code == 0
    assert db_path.exists()
    out = capsys.readouterr().out
    assert "Initialized MITOSIS database" in out
    assert "0001_init.sql" in out
    assert "0002_cells.sql" in out
    assert "0003_population.sql" in out
    assert "Population limits: max_living_cells=1000, max_active_cells=100" in out


def test_init_is_idempotent(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()
    exit_code = cli.main(["--db", str(db_path), "init"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "already existed" in out
    assert "already up to date" in out


def test_status_before_init_errors(tmp_path, capsys):
    db_path = tmp_path / "nope.db"
    exit_code = cli.main(["--db", str(db_path), "status"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "run `mitosis init` first" in err
    assert not db_path.exists()


def test_create_cell_before_init_errors(tmp_path, capsys):
    db_path = tmp_path / "nope.db"
    exit_code = cli.main(
        ["--db", str(db_path), "create-cell", "--type", "explorer", "--budget", "5.00"]
    )
    assert exit_code == 1
    assert "run `mitosis init` first" in capsys.readouterr().err


def test_create_cell_end_to_end(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    exit_code = cli.main(
        ["--db", str(db_path), "create-cell", "--type", "explorer", "--budget", "5.00"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Created cell" in out
    assert "type:   explorer" in out
    assert "status: alive" in out

    exit_code = cli.main(["--db", str(db_path), "status"])
    assert exit_code == 0
    status_out = capsys.readouterr().out
    assert "'explorer': 1" in status_out
    assert "'alive': 1" in status_out


def test_seed_capital_seeds_ledger(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    exit_code = cli.main(
        ["--db", str(db_path), "init", "--seed-capital", "1000.00", "--book", "USD_SIM"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Seeded 1000.00 USD_SIM into seed_bank" in out

    capsys.readouterr()
    cli.main(["--db", str(db_path), "status"])
    status_out = capsys.readouterr().out
    assert "USD_SIM: 1 transactions, conservation=OK" in status_out


def test_invalid_budget_string_fails_cleanly(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    exit_code = cli.main(
        ["--db", str(db_path), "create-cell", "--type", "explorer", "--budget", "not-a-number"]
    )
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def test_create_cell_seeds_genome_content_from_json(tmp_path, capsys):
    """§14: the operator seeds founders; this is the verb that does it."""
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    exit_code = cli.main([
        "--db", str(db_path), "create-cell", "--type", "commercial", "--budget", "5.00",
        "--genome", '{"market": "small accounting firms", "revenue_model": "per-close fee"}',
    ])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "genome content (§16.2)" in out
    assert "small accounting firms" in out


def test_create_cell_seeds_genome_content_from_a_file(tmp_path, capsys):
    """A seed genome is prose about a market; a file is the expected form.

    Shell-quoting a paragraph is how a seed genome arrives truncated, so
    `--genome` accepts a path as readily as inline JSON.
    """
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    seed = tmp_path / "founder.json"
    seed.write_text('{"market": "independent bookshops", "problem": "stock goes stale"}')

    exit_code = cli.main([
        "--db", str(db_path), "create-cell", "--type", "commercial", "--budget", "5.00",
        "--genome", str(seed),
    ])
    assert exit_code == 0
    assert "independent bookshops" in capsys.readouterr().out


def test_create_cell_rejects_an_unknown_genome_field(tmp_path, capsys):
    """§16.4: the closed schema must fail loudly at the operator, not silently.

    A seed genome typo that were quietly dropped would leave a founder reasoning
    from content the operator believed it had.
    """
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    exit_code = cli.main([
        "--db", str(db_path), "create-cell", "--type", "commercial", "--budget", "5.00",
        "--genome", '{"stratergy": "typo"}',
    ])
    assert exit_code == 1
    assert "unknown genome field" in capsys.readouterr().err


def test_create_cell_is_idempotent_across_cli_invocations(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    cli.main(
        [
            "--db", str(db_path), "create-cell", "--type", "explorer",
            "--budget", "5.00", "--idempotency-key", "fixed-key",
        ]
    )
    first_out = capsys.readouterr().out

    cli.main(
        [
            "--db", str(db_path), "create-cell", "--type", "builder",
            "--budget", "999.00", "--idempotency-key", "fixed-key",
        ]
    )
    second_out = capsys.readouterr().out

    assert "type:   explorer" in first_out
    assert "type:   explorer" in second_out  # replay returned the original cell


def test_init_configures_custom_population_limits(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    exit_code = cli.main(
        ["--db", str(db_path), "init", "--max-living-cells", "2", "--max-active-cells", "2"]
    )
    assert exit_code == 0
    assert "Population limits: max_living_cells=2, max_active_cells=2" in capsys.readouterr().out

    capsys.readouterr()
    cli.main(["--db", str(db_path), "status"])
    assert "living: 0/2   active: 0/2" in capsys.readouterr().out


def test_reinit_does_not_change_existing_population_limits(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init", "--max-living-cells", "2", "--max-active-cells", "2"])
    capsys.readouterr()

    cli.main(["--db", str(db_path), "init", "--max-living-cells", "500", "--max-active-cells", "500"])
    out = capsys.readouterr().out
    assert "already configured (living=2, active=2) — not changed" in out


def test_create_cell_denied_at_capacity_via_cli(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init", "--max-living-cells", "1", "--max-active-cells", "1"])
    capsys.readouterr()

    exit_code = cli.main(
        ["--db", str(db_path), "create-cell", "--type", "explorer", "--budget", "5.00"]
    )
    assert exit_code == 0

    exit_code = cli.main(
        ["--db", str(db_path), "create-cell", "--type", "builder", "--budget", "5.00"]
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "birth denied" in err
    assert "capacity" in err


def test_init_shows_default_real_spend_limits(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    out = capsys.readouterr().out
    assert "Real-spend limits (USD_REAL cents): per_request=25, per_hour=100, per_day=500, per_month=5000, max_concurrent_reserved=200" in out


def test_init_can_set_real_spend_limits(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init", "--per-request-cents", "1000"])
    out = capsys.readouterr().out
    assert "Real-spend limits (USD_REAL cents) updated: per_request=1000" in out


def test_reinit_without_spend_flags_does_not_change_spend_limits(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init", "--per-request-cents", "1000"])
    capsys.readouterr()

    cli.main(["--db", str(db_path), "init"])
    out = capsys.readouterr().out
    assert "Real-spend limits (USD_REAL cents): per_request=1000" in out


def test_status_shows_real_spend_breaker_section(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    cli.main(["--db", str(db_path), "status"])
    out = capsys.readouterr().out
    assert "real-spend breaker (USD_REAL):" in out
    assert "concurrent reserved: 0/200" in out


def test_status_shows_events_section(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    cli.main(["--db", str(db_path), "status"])
    out = capsys.readouterr().out
    assert "events:" in out
    assert "inbox: none yet" in out
    assert "outbox unpublished: 0" in out


def test_init_shows_default_paused_clock(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    out = capsys.readouterr().out
    assert "Simulated clock: mode=paused, rate=86400.0 sim-sec/wall-sec" in out


def test_advance_time_moves_status_clock_forward(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    cli.main(["--db", str(db_path), "status"])
    before_out = capsys.readouterr().out
    before_line = [l for l in before_out.splitlines() if "current simulated time" in l][0]

    exit_code = cli.main(["--db", str(db_path), "advance-time", "--days", "1"])
    assert exit_code == 0
    advance_out = capsys.readouterr().out
    assert "Simulated time advanced by 1.0 day(s) to" in advance_out

    cli.main(["--db", str(db_path), "status"])
    after_out = capsys.readouterr().out
    after_line = [l for l in after_out.splitlines() if "current simulated time" in l][0]
    assert before_line != after_line


def test_advance_time_before_init_errors(tmp_path, capsys):
    db_path = tmp_path / "nope.db"
    exit_code = cli.main(["--db", str(db_path), "advance-time", "--days", "1"])
    assert exit_code == 1
    assert "run `mitosis init` first" in capsys.readouterr().err


def test_reinit_does_not_change_existing_clock_mode(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init", "--clock-mode", "paused"])
    capsys.readouterr()

    cli.main(["--db", str(db_path), "init", "--clock-mode", "realtime"])
    out = capsys.readouterr().out
    assert "Simulated clock already configured (mode=paused" in out


def test_init_can_set_clock_mode_and_rate(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init", "--clock-mode", "accelerated", "--clock-rate", "3600"])
    out = capsys.readouterr().out
    assert "Simulated clock: mode=accelerated, rate=3600.0 sim-sec/wall-sec" in out


def test_advance_time_rejects_negative_days(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    capsys.readouterr()

    exit_code = cli.main(["--db", str(db_path), "advance-time", "--days", "-1"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "backwards" in err


def test_verify_golden_run_passes(capsys):
    """Runs against its own in-memory colony — no --db needed."""
    exit_code = cli.main(["verify-golden-run"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASS — the kernel reproduces the golden run exactly." in out
    assert "conservation_usd_sim: True" in out


def test_verify_golden_run_reports_drift_and_exits_nonzero(capsys, monkeypatch):
    from mitosis import golden

    real_verify = golden.verify

    def drifted():
        result = real_verify()
        return golden.GoldenRunResult(
            matched=False,
            expectation_version=result.expectation_version,
            expected_hash="deadbeef" * 8,
            actual_hash=result.actual_hash,
            invariant_failures=["living_cells: expected 3, got 2"],
            snapshot={**result.snapshot, "cells": []},
            invariants=result.invariants,
        )

    monkeypatch.setattr(cli.golden, "verify", drifted)
    exit_code = cli.main(["verify-golden-run"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "FAIL — semantic invariants diverged:" in captured.out
    assert "living_cells: expected 3, got 2" in captured.out
    assert "cells: differs" in captured.out
    assert "--update-expectations" in captured.err


def test_verify_golden_run_does_not_touch_the_colony_db(tmp_path):
    """A golden run must not depend on, or disturb, real colony state."""
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    before = db_path.read_bytes()

    assert cli.main(["--db", str(db_path), "verify-golden-run"]) == 0
    assert db_path.read_bytes() == before


# --- reproduce (SPEC.md §9.4; lineage.py) ------------------------------------


def _seeded_colony(db_path, capsys, founders=10):
    """A colony wide enough that the default 0.20 lineage cap permits a
    second-generation Cell."""
    cli.main(["--db", str(db_path), "init", "--seed-capital", "5000.00"])
    for i in range(founders):
        cli.main([
            "--db", str(db_path), "create-cell", "--type", "commercial",
            "--budget", "100.00", "--idempotency-key", f"f{i}",
        ])
    capsys.readouterr()
    import sqlite3

    conn = sqlite3.connect(db_path)
    parent = conn.execute("SELECT cell_id FROM cells LIMIT 1").fetchone()[0]
    conn.close()
    return parent


def test_reproduce_creates_a_child_from_parent_cash(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    parent = _seeded_colony(db_path, capsys)

    exit_code = cli.main([
        "--db", str(db_path), "reproduce", "--parent", parent, "--budget", "30.00",
    ])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "reproduced ->" in out
    assert "generation: 1" in out
    assert f"founder:    {parent}" in out
    assert "shares the parent's genome" in out


def test_reproduce_with_mutation_reports_a_distinct_genome(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    parent = _seeded_colony(db_path, capsys)

    exit_code = cli.main([
        "--db", str(db_path), "reproduce", "--parent", parent, "--budget", "30.00",
        "--mutation", '{"acquisition_channel": "v2"}', "--mutation-operator", "cli_test",
    ])
    assert exit_code == 0
    assert "mutated genome" in capsys.readouterr().out


def test_reproduce_unknown_parent_errors_cleanly(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    _seeded_colony(db_path, capsys)
    exit_code = cli.main([
        "--db", str(db_path), "reproduce", "--parent", "nope", "--budget", "1.00",
    ])
    assert exit_code == 1
    assert "unknown parent cell" in capsys.readouterr().err


def test_reproduce_invalid_mutation_json_errors_cleanly(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    parent = _seeded_colony(db_path, capsys)
    exit_code = cli.main([
        "--db", str(db_path), "reproduce", "--parent", parent, "--budget", "1.00",
        "--mutation", "not-json",
    ])
    assert exit_code == 1
    assert "must be valid JSON" in capsys.readouterr().err


def test_reproduce_over_parent_balance_errors_cleanly(tmp_path, capsys):
    """Charter C4 surfaced through the CLI without a traceback."""
    db_path = tmp_path / "mitosis.db"
    parent = _seeded_colony(db_path, capsys)
    exit_code = cli.main([
        "--db", str(db_path), "reproduce", "--parent", parent, "--budget", "9999.00",
    ])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "Traceback" not in err


def test_status_reports_lineage(tmp_path, capsys):
    db_path = tmp_path / "mitosis.db"
    parent = _seeded_colony(db_path, capsys)
    cli.main(["--db", str(db_path), "reproduce", "--parent", parent, "--budget", "30.00"])
    capsys.readouterr()

    cli.main(["--db", str(db_path), "status"])
    out = capsys.readouterr().out
    assert "lineage (SPEC.md §9.4" in out
    assert "lineages: 10" in out
    assert "integrity: True" in out
    assert "depth 1" in out


# --- fund-cell + call-model (model gateway, SPEC.md §24) ---------------------


def _init_and_cell(tmp_path, capsys, book="USD_REAL", budget="10.00"):
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])
    cli.main(
        [
            "--db", str(db_path), "create-cell",
            "--type", "explorer", "--budget", budget, "--book", book,
        ]
    )
    out = capsys.readouterr().out
    cell_id = out.split("Created cell ")[1].split("\n")[0].strip()
    return str(db_path), cell_id


def _fund_for_calls(db_path, cell_id):
    cli.main(["--db", db_path, "fund-cell", "--cell", cell_id,
              "--amount", "1000000", "--book", "RESOURCE"])
    cli.main(["--db", db_path, "fund-cell", "--cell", cell_id,
              "--amount", "10.00", "--book", "USD_SIM"])


def test_fund_cell_credits_a_second_book(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    exit_code = cli.main(["--db", db_path, "fund-cell", "--cell", cell_id,
                          "--amount", "2.50", "--book", "USD_SIM"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Funded cell" in out
    assert "book:    USD_SIM" in out
    assert "balance: 2.50" in out


def test_fund_cell_rejects_unknown_cell(tmp_path, capsys):
    db_path, _ = _init_and_cell(tmp_path, capsys)
    assert cli.main(["--db", db_path, "fund-cell", "--cell", "nope",
                     "--amount", "1.00", "--book", "USD_SIM"]) == 1
    assert "unknown cell" in capsys.readouterr().err


def test_call_model_with_mock_provider(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    capsys.readouterr()
    exit_code = cli.main(["--db", db_path, "call-model", "--cell", cell_id,
                          "--prompt", "hello there"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Model call" in out
    assert "status:    succeeded" in out
    assert "provider:  mock" in out
    assert "mock reply" in out


def test_call_model_refuses_a_paid_provider_without_confirmation(tmp_path, capsys):
    """The one CLI verb that can spend real money requires saying so."""
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    capsys.readouterr()
    exit_code = cli.main(["--db", db_path, "call-model", "--cell", cell_id,
                          "--prompt", "hi", "--provider", "anthropic",
                          "--model", "claude-opus-5"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "--yes-spend-real-money" in err
    assert "spends real money" in err


def test_call_model_rejects_unknown_provider(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    capsys.readouterr()
    assert cli.main(["--db", db_path, "call-model", "--cell", cell_id,
                     "--prompt", "hi", "--provider", "openai"]) == 1
    assert "unknown provider" in capsys.readouterr().err


def test_call_model_rejects_unpriced_model_cleanly(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    capsys.readouterr()
    assert cli.main(["--db", db_path, "call-model", "--cell", cell_id,
                     "--prompt", "hi", "--model", "no-such-model"]) == 1
    err = capsys.readouterr().err
    assert "no price for model" in err
    assert "Traceback" not in err


def test_call_model_rejects_unknown_cell(tmp_path, capsys):
    db_path, _ = _init_and_cell(tmp_path, capsys)
    capsys.readouterr()
    assert cli.main(["--db", db_path, "call-model", "--cell", "nope",
                     "--prompt", "hi"]) == 1
    assert "unknown cell" in capsys.readouterr().err


def test_status_shows_the_model_gateway_section(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    cli.main(["--db", db_path, "call-model", "--cell", cell_id, "--prompt", "hi"])
    capsys.readouterr()
    cli.main(["--db", db_path, "status"])
    out = capsys.readouterr().out
    assert "model gateway (pricing table" in out
    assert "calls by status: {'succeeded': 1}" in out
    assert "mock: 1 calls" in out


def test_status_gateway_section_empty_before_any_call(tmp_path, capsys):
    db_path, _ = _init_and_cell(tmp_path, capsys)
    capsys.readouterr()
    cli.main(["--db", db_path, "status"])
    assert "no calls yet" in capsys.readouterr().out


def test_sweep_before_init_errors(tmp_path, capsys):
    assert cli.main(["--db", str(tmp_path / "nope.db"), "sweep"]) == 1
    assert "run `mitosis init` first" in capsys.readouterr().err


def test_sweep_is_a_no_op_on_a_healthy_colony(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    cli.main(["--db", db_path, "call-model", "--cell", cell_id, "--prompt", "hi"])
    capsys.readouterr()
    assert cli.main(["--db", db_path, "sweep"]) == 0
    out = capsys.readouterr().out
    assert "Reservations swept: 0" in out
    assert "Stranded model calls resolved: 0" in out
    assert "execution_unknown" not in out


def test_sweep_resolves_a_stranded_call_and_says_money_is_still_committed(
    tmp_path, capsys, monkeypatch
):
    """The operator-facing half of crash recovery: after a real crash the
    sweep must both fix the record and be loud that real money is still
    committed against an outcome nobody knows (Charter C7).

    The stranded state is produced by actually crashing a call rather than by
    rewriting rows — a hand-built one would replay ledger postings the real
    crash never made, and collide on their idempotency keys.
    """
    from datetime import datetime, timedelta, timezone

    import pytest

    from mitosis import db as _db
    from mitosis import gateway, providers

    class _Crash(BaseException):
        pass

    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    capsys.readouterr()

    def boom(*args, **kwargs):
        raise _Crash("mid-settle")

    monkeypatch.setattr(gateway, "_mirror_to_sim_locked", boom)
    conn = _db.connect_and_migrate(db_path)
    with pytest.raises(_Crash):
        gateway.call_model(
            conn,
            cell_id=cell_id,
            provider=providers.MockProvider(),
            request=providers.ModelRequest(
                model="mock-1",
                messages=({"role": "user", "content": "hi"},),
                max_tokens=64,
            ),
            idempotency_key="cli-crash",
        )
    conn.close()  # process death: the transaction is never committed
    monkeypatch.undo()

    # Age the reservations past their TTL so the sweeper is willing to look;
    # the alternative is sleeping out a 15-minute default.
    conn = _db.connect_and_migrate(db_path)
    conn.execute(
        "UPDATE reservations SET expires_at = ?",
        ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),),
    )
    conn.close()

    assert cli.main(["--db", db_path, "sweep"]) == 0
    out = capsys.readouterr().out
    assert "Reservations swept: 2" in out
    assert "-> execution_unknown" in out
    assert "-> released" in out
    assert "Stranded model calls resolved: 1" in out
    assert "reconciled, never auto-released" in out


def test_reconcile_before_init_errors(tmp_path, capsys):
    assert cli.main([
        "--db", str(tmp_path / "nope.db"), "reconcile",
        "--call", "x", "--invoiced", "1.00", "--source", "s",
    ]) == 1
    assert "run `mitosis init` first" in capsys.readouterr().err


def test_outstanding_lists_then_clears(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    cli.main(["--db", db_path, "call-model", "--cell", cell_id, "--prompt", "hi"])
    out = capsys.readouterr().out
    call_id = out.split("Model call ")[1].split("\n")[0].strip()

    # The CLI's default provider is the zero-priced mock, and no invoice will
    # ever list a call that cost nothing — so it is not outstanding work.
    cli.main(["--db", db_path, "outstanding"])
    out = capsys.readouterr().out
    assert "0 billable, 0 reconciled, 0 outstanding" in out
    assert "Nothing outstanding." in out

    # But `outstanding` is a worklist, not a gate: reconcile still accepts the
    # call by id, so a surprise charge on a nominally free call can be applied.
    assert cli.main([
        "--db", db_path, "reconcile", "--call", call_id,
        "--invoiced", "0", "--source", "inv-2026-07",
    ]) == 0
    out = capsys.readouterr().out
    assert "Reconciled model call" in out
    assert "source:    inv-2026-07" in out

    cli.main(["--db", db_path, "outstanding"])
    assert "Nothing outstanding." in capsys.readouterr().out


def test_reconcile_refuses_to_run_twice(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    cli.main(["--db", db_path, "call-model", "--cell", cell_id, "--prompt", "hi"])
    call_id = capsys.readouterr().out.split("Model call ")[1].split("\n")[0].strip()
    cli.main([
        "--db", db_path, "reconcile", "--call", call_id,
        "--invoiced", "0", "--source", "inv",
    ])
    capsys.readouterr()
    assert cli.main([
        "--db", db_path, "reconcile", "--call", call_id,
        "--invoiced", "0", "--source", "inv",
    ]) == 1
    assert "already reconciled" in capsys.readouterr().err


def test_reconcile_rejects_precision_finer_than_micro_usd(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    cli.main(["--db", db_path, "call-model", "--cell", cell_id, "--prompt", "hi"])
    call_id = capsys.readouterr().out.split("Model call ")[1].split("\n")[0].strip()
    assert cli.main([
        "--db", db_path, "reconcile", "--call", call_id,
        "--invoiced", "0.00000001", "--source", "inv",
    ]) == 1
    assert "more precision than micro-USD supports" in capsys.readouterr().err


def test_dispute_then_reconcile_resolves_a_crashed_call(tmp_path, capsys, monkeypatch):
    """The whole operator loop after a crash: sweep -> outstanding -> dispute
    -> reconcile, ending with no frozen money and nothing outstanding."""
    from datetime import datetime, timedelta, timezone

    import pytest

    from mitosis import db as _db
    from mitosis import gateway, providers

    class _Crash(BaseException):
        pass

    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    capsys.readouterr()

    monkeypatch.setattr(
        gateway, "_mirror_to_sim_locked", lambda *a, **k: (_ for _ in ()).throw(_Crash())
    )
    conn = _db.connect_and_migrate(db_path)
    with pytest.raises(_Crash):
        gateway.call_model(
            conn,
            cell_id=cell_id,
            provider=providers.MockProvider(),
            request=providers.ModelRequest(
                model="mock-1",
                messages=({"role": "user", "content": "hi"},),
                max_tokens=64,
            ),
            idempotency_key="cli-recon-crash",
        )
    conn.close()
    monkeypatch.undo()

    conn = _db.connect_and_migrate(db_path)
    conn.execute(
        "UPDATE reservations SET expires_at = ?",
        ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),),
    )
    conn.close()

    cli.main(["--db", db_path, "sweep"])
    capsys.readouterr()

    cli.main(["--db", db_path, "outstanding"])
    out = capsys.readouterr().out
    assert "execution_unknown" in out
    assert "estimated=unknown" in out, "a call that never returned has no cost to show"
    call_id = out.strip().split("\n")[-1].split()[0]

    assert cli.main([
        "--db", db_path, "dispute", "--call", call_id, "--reason", "no response",
    ]) == 0
    assert "Disputed model call" in capsys.readouterr().out

    assert cli.main([
        "--db", db_path, "reconcile", "--call", call_id,
        "--invoiced", "0.0150", "--source", "anthropic-inv",
    ]) == 0
    out = capsys.readouterr().out
    assert "unknown (the call never returned a usage report)" in out
    assert "invoiced:  15000 micro-USD" in out

    cli.main(["--db", db_path, "outstanding"])
    out = capsys.readouterr().out
    assert "Nothing outstanding." in out
    assert "frozen in unreconciled open reservations: 0" in out


def test_record_revenue_credits_the_cell_and_prints_running_total(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)

    assert cli.main([
        "--db", db_path, "record-revenue", "--cell", cell_id,
        "--amount", "12.50", "--source", "acme-inv-7", "--note", "first sale",
    ]) == 0
    out = capsys.readouterr().out
    assert "Recorded revenue" in out
    assert "1250 minor units" in out
    assert "acme-inv-7" in out
    assert "first sale" in out
    assert "cell earned to date: 1250" in out

    cli.main([
        "--db", db_path, "record-revenue", "--cell", cell_id,
        "--amount", "0.50", "--source", "acme-inv-8",
    ])
    assert "cell earned to date: 1300" in capsys.readouterr().out


def test_record_revenue_requires_a_source_and_refuses_nonpositive(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    capsys.readouterr()

    with pytest.raises(SystemExit):
        cli.main(["--db", db_path, "record-revenue", "--cell", cell_id, "--amount", "1.00"])

    assert cli.main([
        "--db", db_path, "record-revenue", "--cell", cell_id,
        "--amount", "0.00", "--source", "x",
    ]) == 1
    assert "must be positive" in capsys.readouterr().err


def test_record_revenue_to_unknown_cell_exits_nonzero(tmp_path, capsys):
    db_path, _ = _init_and_cell(tmp_path, capsys)
    capsys.readouterr()
    assert cli.main([
        "--db", db_path, "record-revenue", "--cell", "nope",
        "--amount", "1.00", "--source", "x",
    ]) == 1
    assert "no such cell" in capsys.readouterr().err


def test_record_refund_names_the_payment_and_reports_what_is_left(tmp_path, capsys):
    """§1.1's refunds and chargebacks, from the operator's side (ADR-097). The
    verb takes the payment `record-revenue` printed, never a Cell, and shares one
    bound across both kinds."""
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    cli.main([
        "--db", db_path, "record-revenue", "--cell", cell_id,
        "--amount", "12.50", "--source", "acme-inv-7",
    ])
    payment = next(
        line.split()[-1]
        for line in capsys.readouterr().out.splitlines()
        if line.strip().startswith("txn:")
    )

    assert cli.main([
        "--db", db_path, "record-refund", "--payment", payment,
        "--amount", "2.50", "--source", "processor-re-1",
    ]) == 0
    out = capsys.readouterr().out
    assert f"Recorded refund of payment {payment}" in out
    assert "still reversible on that payment: 1000 minor units" in out
    assert "cell earned to date (net): 1000" in out

    assert cli.main([
        "--db", db_path, "record-refund", "--payment", payment,
        "--amount", "10.01", "--source", "dispute-1", "--chargeback",
    ]) == 1
    assert "1000 of its 1250 is left" in capsys.readouterr().err

    assert cli.main([
        "--db", db_path, "record-refund", "--payment", payment,
        "--amount", "10.00", "--source", "dispute-1", "--chargeback",
    ]) == 0
    assert "Recorded chargeback" in capsys.readouterr().out

    assert cli.main(["--db", db_path, "cell-fitness", "--cell", cell_id]) == 0
    out = capsys.readouterr().out
    assert "revenue:           0 minor units" in out
    assert "received 1250, refunded or charged back 1250" in out


def test_record_fee_names_the_charge_and_reports_the_cells_spend(tmp_path, capsys):
    """§1.1's payment fees, from the operator's side (ADR-098): the gross sale is
    recorded as revenue and the fee beside it, taken on the payment by id."""
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    cli.main([
        "--db", db_path, "record-revenue", "--cell", cell_id,
        "--amount", "12.50", "--source", "acme-inv-7",
    ])
    payment = next(
        line.split()[-1]
        for line in capsys.readouterr().out.splitlines()
        if line.strip().startswith("txn:")
    )

    assert cli.main([
        "--db", db_path, "record-fee", "--on", payment,
        "--amount", "0.66", "--source", "processor-fee-1",
    ]) == 0
    out = capsys.readouterr().out
    assert f"Recorded payment fee on {payment}" in out
    assert "cell spend to date: 66 minor units USD_REAL" in out

    refund = cli.main([
        "--db", db_path, "record-refund", "--payment", payment,
        "--amount", "1.00", "--source", "processor-re-1",
    ])
    assert refund == 0
    refund_txn = next(
        line.split()[-1]
        for line in capsys.readouterr().out.splitlines()
        if line.strip().startswith("txn:")
    )
    assert cli.main([
        "--db", db_path, "record-fee", "--on", refund_txn,
        "--amount", "0.10", "--source", "refund-fee",
    ]) == 1
    assert "revenue payment or a chargeback" in capsys.readouterr().err


def test_profit_reports_both_figures_and_abstains_until_a_rate_is_declared(tmp_path, capsys):
    """§1.1 asks for both figures always. The second one abstains rather than
    guessing a RESOURCE→USD rate (§2.4), and says so (ADR-099)."""
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    cli.main([
        "--db", db_path, "record-revenue", "--cell", cell_id,
        "--amount", "12.50", "--source", "acme-inv-7",
    ])
    payment = next(
        line.split()[-1]
        for line in capsys.readouterr().out.splitlines()
        if line.strip().startswith("txn:")
    )
    cli.main([
        "--db", db_path, "record-fee", "--on", payment,
        "--amount", "0.66", "--source", "processor-fee-1",
    ])
    capsys.readouterr()

    assert cli.main(["--db", db_path, "profit"]) == 0
    out = capsys.readouterr().out
    assert "settled revenue:        1250" in out
    assert "- payment fees:         66" in out
    assert "REAL_SETTLED_NET_PROFIT: 1184" in out
    assert "AUTONOMY_ADJUSTED_PROFIT: not available" in out
    assert "other external operating costs" in out

    assert cli.main([
        "--db", db_path, "set-shadow-rate", "--micro-usd-per-unit", "100", "--by", "operator",
    ]) == 0
    assert "no transaction is posted" in capsys.readouterr().out

    assert cli.main(["--db", db_path, "profit"]) == 0
    out = capsys.readouterr().out
    assert "AUTONOMY_ADJUSTED_PROFIT: 1184" in out, "no metered labour yet, so the two agree"


def test_record_refund_of_an_unknown_payment_exits_nonzero(tmp_path, capsys):
    db_path, _ = _init_and_cell(tmp_path, capsys)
    capsys.readouterr()
    assert cli.main([
        "--db", db_path, "record-refund", "--payment", "nope",
        "--amount", "1.00", "--source", "x",
    ]) == 1
    assert "no such transaction" in capsys.readouterr().err


def test_ollama_provider_needs_no_spend_confirmation(tmp_path, capsys, monkeypatch):
    """Local inference costs nothing, so gating it behind
    --yes-spend-real-money would train the operator to pass that flag by
    habit — which is the flag protecting real money."""
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    capsys.readouterr()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{closed_port}")

    # Reaches the provider rather than being refused for want of a confirmation
    # flag, and exits 0 either way — a provider that is down is an outcome the
    # gateway records, not a CLI usage error (the shape the live 401 took).
    assert cli.main([
        "--db", db_path, "call-model", "--cell", cell_id,
        "--provider", "ollama", "--model", "llama3.2", "--prompt", "hi",
    ]) == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "yes-spend-real-money" not in combined

    # Hermetic: OLLAMA_HOST points at a loopback port nothing listens on, so
    # the outcome is always a refused connection. This test used to read
    # whatever daemon the machine had, and so reported on the machine rather
    # than the property — red once a daemon was installed, then red again when
    # one was up but too busy to answer (a timeout), and again when its GPU
    # backend failed (a Metal library error). Tolerating each outcome as it
    # appeared was patching symptoms of reading the environment at all.
    assert "status:    failed" in captured.out
    assert "ollama serve" in captured.out, "a down provider names the fix"
    assert "settled 0.00 USD_REAL" in captured.out, "local inference is free in money"


def test_unknown_provider_lists_all_three(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    _fund_for_calls(db_path, cell_id)
    capsys.readouterr()
    assert cli.main([
        "--db", db_path, "call-model", "--cell", cell_id,
        "--provider", "openai", "--prompt", "hi",
    ]) == 1
    err = capsys.readouterr().err
    assert "mock" in err and "anthropic" in err and "ollama" in err


def test_predict_resolve_and_calibration_end_to_end(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    capsys.readouterr()

    assert cli.main([
        "--db", db_path, "predict", "--cell", cell_id,
        "--claim", "revenue >= 50", "--probability", "0.8",
    ]) == 0
    out = capsys.readouterr().out
    assert "Registered prediction" in out
    assert "revenue >= 50" in out
    prediction_id = out.split("Registered prediction ")[1].split("\n")[0].strip()

    assert cli.main([
        "--db", db_path, "resolve-prediction", "--prediction", prediction_id,
        "--occurred", "--source", "ledger",
    ]) == 0
    out = capsys.readouterr().out
    assert "brier score: 0.0400" in out

    assert cli.main(["--db", db_path, "calibration"]) == 0
    out = capsys.readouterr().out
    assert "registered: 1   resolved: 1" in out
    assert "predicted 0.80, observed 1.00" in out
    assert "register hash chain valid: True" in out


def test_calibration_warns_when_predictions_are_overdue(tmp_path, capsys):
    """A curve built only from resolved predictions is self-selected, and an
    operator reading the mean has no way to know unless told."""
    import sqlite3

    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    cli.main([
        "--db", db_path, "predict", "--cell", cell_id,
        "--claim", "overdue claim", "--probability", "0.9",
    ])
    capsys.readouterr()

    # Move the deadline into the past rather than racing the wall clock: a
    # sub-second deadline is not reliably elapsed by the time the next command
    # runs, and sleeping to make it so would be slower and no more truthful.
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE prediction_register SET resolves_by_utc = '2020-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()

    cli.main(["--db", db_path, "calibration"])
    out = capsys.readouterr().out
    assert "overdue: 1" in out
    assert "WARNING" in out
    assert "self-selected" in out


def test_an_unknown_experiment_id_is_refused_rather_than_stored(tmp_path, capsys):
    """Migration 0026 complained that `--experiment` "has always accepted any
    string and validated nothing", and creating the table did not fix that —
    nothing joined the two (ADR-044).

    A typo does not fail loudly here. It silently detaches the prediction from
    every report that would have counted it, and §2.6 then shows a smaller
    number with nothing anywhere saying why. A dangling foreign key that only
    ever *subtracts* from a report is the quietest possible way to be wrong.
    """
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    capsys.readouterr()
    assert cli.main([
        "--db", db_path, "predict", "--cell", cell_id,
        "--claim", "revenue >= 50", "--probability", "0.6",
        "--experiment", "exp-that-never-existed",
    ]) == 1
    err = capsys.readouterr().err
    assert "no such experiment" in err
    # Refused, not recorded: a prediction written with a dangling id would
    # already be in the hash chain and could not be edited out (§3.6).
    assert cli.main(["--db", db_path, "calibration"]) == 0
    assert "exp-that-never-existed" not in capsys.readouterr().out


def test_revenue_refuses_an_unknown_experiment_id(tmp_path, capsys):
    """The same hole on the money side, where it is worse: revenue attached to
    a dangling experiment is revenue §2.6 will never report as earned."""
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    capsys.readouterr()
    assert cli.main([
        "--db", db_path, "record-revenue", "--cell", cell_id,
        "--amount", "5.00", "--source", "manual", "--book", "USD_SIM",
        "--experiment", "exp-that-never-existed",
    ]) == 1
    assert "no such experiment" in capsys.readouterr().err


def test_predict_refuses_certainty_through_the_cli(tmp_path, capsys):
    db_path, cell_id = _init_and_cell(tmp_path, capsys)
    capsys.readouterr()
    assert cli.main([
        "--db", db_path, "predict", "--cell", cell_id,
        "--claim", "certain", "--probability", "1.0",
    ]) == 1
    assert "strictly between 0 and 1" in capsys.readouterr().err
