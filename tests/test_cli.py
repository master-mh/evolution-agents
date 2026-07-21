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
