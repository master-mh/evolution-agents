"""Source-distribution hygiene (implementation brief, Slice A).

A manually zipped working directory shipped a live Anthropic credential once
-- zipping a directory bypasses `.gitignore`, `git archive` does not. These
tests run the actual documented command (`scripts/build_source_archive.py`)
as a subprocess and open its real output, per the brief's own definition of
done: "Test the produced archive, not merely `.gitignore` patterns."

The per-pattern cases build a throwaway git repo and force-track one
forbidden file each (`git add -f`), rather than asserting "this repository's
archive has no .db in it" -- this repository never tracks a .db, so that
assertion would pass whether or not the detector works. Forcing the content
to exist and confirming the build still refuses it is the actual teeth
check (CLAUDE.md, "Testing style").
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "build_source_archive.py"

# (relative path to force-track, forbidden reason a correct build must cite)
FORBIDDEN_FIXTURES = [
    (".env", ".env"),
    ("nested/.env.local", ".env"),
    ("data.db", "*.db/*.sqlite/*.sqlite3"),
    ("data.sqlite3", "*.db/*.sqlite/*.sqlite3"),
    (".venv/pyvenv.cfg", ".venv/"),
    ("venv/pyvenv.cfg", "venv/"),
    ("__pycache__/mod.cpython-311.pyc", "__pycache__/"),
    (".pytest_cache/README.md", ".pytest_cache/"),
    (".hypothesis/unicode_data/marker", ".hypothesis/"),
    ("__MACOSX/._foo", "__MACOSX/"),
    (".DS_Store", ".DS_Store"),
    (".coverage", ".coverage"),
    (".coverage.host.12345", ".coverage"),
]
# `.git/` is in FORBIDDEN_DIR_NAMES too, but git refuses to track any path
# through a literal `.git` directory, so there is no fixture that can put it
# in an archive to begin with -- the guard is defense in depth, untestable
# by this method, and that is fine.


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _build(tmp_path: Path, *, ref: str = "HEAD", repo_root: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    output = tmp_path / "mitosis-source.zip"
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--ref", ref, "--repo-root", str(repo_root), "--output", str(output)],
        capture_output=True,
        text=True,
    )


def _member_names(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        return zf.namelist()


def test_the_archive_is_produced_by_one_documented_command(tmp_path):
    result = _build(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "mitosis-source.zip").exists()


def test_the_archive_is_derived_from_tracked_content_not_a_directory_walk(tmp_path):
    """`git archive`'s member list must equal `git ls-files`, not `os.walk`."""
    result = _build(tmp_path)
    assert result.returncode == 0, result.stderr
    names = set(_member_names(tmp_path / "mitosis-source.zip"))

    tracked = _git("ls-files", cwd=REPO_ROOT).stdout.splitlines()
    assert set(tracked) <= names
    assert "src/mitosis/__init__.py" in names


def test_no_secret_value_is_printed_by_the_build(tmp_path):
    """The script must never read or echo `.env`'s contents -- only check
    whether a path named `.env` is present in the archive's member list."""
    result = _build(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ANTHROPIC_API_KEY" not in result.stdout
    assert "ANTHROPIC_API_KEY" not in result.stderr


@pytest.fixture
def throwaway_repo(tmp_path):
    repo = tmp_path / "throwaway_repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@test.invalid", cwd=repo)
    _git("config", "user.name", "test", cwd=repo)
    (repo / "README.md").write_text("throwaway fixture repo\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo


@pytest.mark.parametrize("relative_path,expected_reason", FORBIDDEN_FIXTURES)
def test_a_tracked_forbidden_file_fails_the_build_closed(tmp_path, throwaway_repo, relative_path, expected_reason):
    """Teeth-check: if a forbidden path were ever force-tracked, the build's
    own member-list guard must refuse it -- not rely solely on git archive's
    tracked-only default to keep it out."""
    target = throwaway_repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("forbidden fixture content\n")
    _git("add", "-f", relative_path, cwd=throwaway_repo)
    _git("commit", "-q", "-m", "add forbidden fixture", cwd=throwaway_repo)

    result = _build(tmp_path, repo_root=throwaway_repo)

    assert result.returncode != 0
    assert not (tmp_path / "mitosis-source.zip").exists()
    assert relative_path in result.stderr
    assert expected_reason in result.stderr


def test_a_clean_throwaway_repo_builds_successfully(tmp_path, throwaway_repo):
    """Negative control for the parametrized case above: the guard must not
    be so broad that an ordinary repo fails to build at all."""
    result = _build(tmp_path, repo_root=throwaway_repo)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "mitosis-source.zip").exists()
