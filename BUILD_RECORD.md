# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, 2026-07-21 through 2026-07-25): [docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-07-26 — CI workflow wired (first Phase 1 gating item closed)

SPEC.md §0.1 and §26 require Charter property tests and golden-run replay to run in CI, so a broken
Charter clause or a kernel-behaviour drift can't merge silently. Neither ran anywhere but locally
until now — no `.github/` directory existed in the repo.

- **`.github/workflows/ci.yml`:** new GitHub Actions workflow, triggers on push/PR to `main`.
  `actions/checkout` + `actions/setup-python@v5` (Python 3.11, matching `pyproject.toml`'s
  `requires-python = ">=3.11"`), `pip install -e ".[dev]"`, then `pytest` (full suite, which
  includes `tests/test_charter_properties.py` — no separate charter-only step needed) and
  `mitosis verify-golden-run` (uses its own fresh in-memory colony per its docstring, so it needs
  no `mitosis init` step first and never touches a `--db` path).
- Verified by hand before committing to the workflow file: built a scratch venv from
  `/opt/homebrew/bin/python3.11` (the same minor version `setup-python` will provision — the
  default macOS `python3` here is 3.9 and its bundled pip is too old for PEP 660 editable installs,
  which would have been a false negative if used to "test" this), ran `pip install -e ".[dev]"`,
  `pytest`, and `mitosis verify-golden-run` end to end: 221 passed, golden hash matched exactly.
  Scratch venv discarded after.
- Deliberately out of scope for this slice: no matrix (single Python version — nothing in the
  spec or codebase needs multi-version support yet), no coverage reporting, no lint/type-check step
  (none configured anywhere in the repo yet, so adding one here would be inventing new scope rather
  than wiring up an existing local check), no caching of the pip install (the install is a few
  seconds; not worth the added workflow complexity yet).
- Not yet committed or pushed — reporting for review first.
- Next: seeded ID generation (the remaining Phase 1 gating item — `uuid4` primary keys/timestamps
  block byte-level golden replay and Amendment A5's deterministic tie-break for same-instant
  same-priority events); otherwise the Phase 1 "Next" list in PRIORITIES.md is unchanged.
