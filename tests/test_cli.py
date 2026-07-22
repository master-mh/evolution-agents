from pathlib import Path

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
