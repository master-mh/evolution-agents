# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, 2026-07-21 through 2026-07-25) and CI wiring (2026-07-26):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-07-26 — Seeded id generation (second and final Phase 1 gating item closed)

`golden.py`'s docstring named the gap: the kernel had no seeded id generation, so a golden run's
raw uuids differed every time even though its *semantic* snapshot didn't — and Amendment A5's
`(effective_time, priority, event_id)` ordering tie-break fell to a fresh `uuid4` every run,
making it a total order but not a reproducible one. Both are the same underlying fix.

- **New `src/mitosis/ids.py`:** an injectable id generator. `RandomIdGenerator` (the default) is
  byte-for-byte what every call site already did — `str(uuid.uuid4())` — so a real colony run is
  unchanged. `SeededIdGenerator(seed)` uses a `random.Random(seed)` to emit uuid4-*shaped* strings
  deterministically (`uuid.UUID(int=rng.getrandbits(128), version=4)`) — same TEXT-primary-key
  format everywhere, no schema/format migration. `ids.seeded(seed)` is a context manager that
  scopes determinism to a block and restores whatever generator was active before (not always
  `reset()`'s default — nesting stays correct); `seed()`/`reset()` are the lower-level equivalents
  for a caller that wants an open-ended window instead. No thread-safety needed: nothing in this
  kernel runs Python threads (concurrency here is SQLite `BEGIN IMMEDIATE` write-lock contention
  between connections, not in-process threading — see slice 10's concurrency-safety pass).
- **Every `uuid.uuid4()` call site converted to `ids.new_id()`:** `ledger.py` (transaction_id,
  entry_id), `reservations.py` (reservation_id), `lifecycle.py` (genome_id, cell_id, coroner
  report_id), `events.py` (inbox event_id, outbox event_id), `resource_metering.py` (usage_id),
  `audit.py` (audit event_id), and `cli.py`'s idempotency-key default suffix (not a primary key,
  but converted too for one consistent source of id-ish randomness in the kernel).
- **`golden.py` wired to use it:** `run_scenario` now runs its whole body inside
  `ids.seeded(GOLDEN_RUN_ID_SEED)` (renamed the body to `_run_scenario_body` so the public
  function's signature/callers didn't need to change). Updated the module docstring — the "known
  determinism gap" paragraph is now "determinism gap this closes"; ADR-017's semantic-snapshot-plus-
  hash comparison is unchanged and stays the permanent design (its real rationale is schema-
  evolution robustness, not id determinism) but the raw run underneath it is no longer
  non-reproducible.
- Verified by hand before writing tests: ran `golden.run_scenario` against two independent fresh
  in-memory connections and diffed the raw `cell_id`/`transaction_id`/`event_id` lists — identical,
  not just their semantic snapshot. Confirmed default (unseeded) `ids.new_id()` still produces
  distinct random uuids, confirmed a real `mitosis init && create-cell` session end to end still
  produces normal random-looking ids, confirmed `ids.seeded(...)` correctly restores the *previous*
  generator (not unconditionally "random") when nested. Confirmed `mitosis verify-golden-run`'s
  shipped hash is unchanged — expected, since the semantic snapshot already stripped ids before this
  slice, so nothing about what the hash covers changed.
- New tests: `tests/test_ids.py` (7 tests — default randomness/shape, seed determinism, distinct
  seeds diverge, seeded output is still uuid4-shaped, `reset()` behaviour, context-manager scoping
  and restore-to-prior-generator including nesting). `tests/test_golden.py` gained
  `test_raw_ids_are_reproducible_across_runs` (byte-identical raw ids across two runs, the property
  this slice exists to establish) and `test_run_scenario_does_not_leak_seeded_ids_afterward` (calling
  `run_scenario` must not leave the global generator seeded for unrelated code afterward).
- **230 tests passing** (9 new, 0 removed; up from 221).
- Deliberately out of scope for this slice: no CLI `--seed` flag (nothing yet needs an end user to
  run a *real* colony deterministically — the two documented consumers, golden-run replay and
  Amendment A5's tie-break, are both served by `golden.py`'s internal seeding; a public seeding knob
  is Phase 2 flight-simulator territory per SPEC.md §7's "deterministic seeds" requirement, not a
  Phase 1 concern); no change to ADR-017's semantic-snapshot-plus-hash comparison strategy or to
  `golden_expectations.json` (hash unaffected, so no `--update-expectations` migration was needed);
  clock.py's wall-clock timestamps are still not seeded/wired — see PRIORITIES.md — so a *real*
  colony still can't be byte-identically replayed, only a scenario like `golden.py`'s that already
  avoids reading the wall clock.
- Closed the `FUTURE_BUILD_HOOKS.md` entry this slice resolves (2026-07-25, "seeded ids for
  reproducible event ordering").
- Committed and pushed to `main`.
- Next: with both Phase 1 gating items closed, the remaining Phase 1 "Next" list in PRIORITIES.md
  is all additive/Phase-2-adjacent — remaining CLI commands, `kill()` reservation/balance sweep,
  wiring the simulated clock into real producers, reproduction/lineage tracking, experiment
  tracking, model gateway. None has a hard ordering constraint over the others.
