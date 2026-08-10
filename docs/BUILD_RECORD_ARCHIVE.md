# MITOSIS / Evolution Agents — Build Record Archive

Entries through slice 9 (2026-07-25, golden-run replay), moved out of the top-level
`BUILD_RECORD.md` so that file stays small enough to read in full every session (it had grown to
~42 KB / 9 slices). `BUILD_RECORD.md` keeps only the current/most-recent entry plus a pointer
here; append new slices there, and move an entry here once a newer one supersedes it as "last
landed."

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
- Committed `2ba65e2`, pushed.
- Next: seeded ID generation (the remaining Phase 1 gating item — `uuid4` primary keys/timestamps
  block byte-level golden replay and Amendment A5's deterministic tie-break for same-instant
  same-priority events); otherwise the Phase 1 "Next" list in PRIORITIES.md is unchanged.

## 2026-07-25 — Slice 10: close the C4 reservation-vs-cash gap, concurrency-safety pass, Charter test-ID coverage

A `/critique` of the prior session found a live overdraft hole: `reservations.request()` never
checked a Cell's cash balance, so a Cell funded with 1,000 minor units could reserve and settle
1,000,000 — conservation and the hash chain both stayed green throughout, which is exactly why
nine slices hadn't surfaced it. SPEC.md §4.1's protocol names a distinct `AUTHORISE` stage between
`REQUEST` and `RESERVE`; it existed nowhere in `src/`, and Charter C4 ("cannot overspend authorised
budget") was that missing stage's guarantee.

- **`src/mitosis/reservations.py`:** `request()` now checks `ledger.get_balance(cell_cash)` against
  `maximum_amount` inside the same `BEGIN IMMEDIATE` as the existing C5 real-spend check, across all
  three books (not just USD_REAL) — a Cell can never reserve more than it currently holds in cash.
  New `InsufficientBalanceError`.
- **Concurrency-safety pass, same bug class found while implementing the above:** `settle()`,
  `release()`, `_bare_status_transition()` (reservations.py) and `_transition()`/`kill()`
  (lifecycle.py) all fetched their entity and validated its current status *before* acquiring the
  write lock, then applied the pre-validated decision after — the same race `create_cell`/`request`
  already guard against correctly. Two concurrent calls against the same reservation/Cell could both
  pass validation before either committed. All five now re-fetch and re-validate inside
  `BEGIN IMMEDIATE`. `resource_metering.record_usage()` had the identical pattern for its
  reservation-ownership/status checks (only the overspend check itself was already inside the
  lock) — fixed the same way.
- **`src/mitosis/accounts.py`:** `FIXED_ACCOUNTS` existed but was never referenced anywhere except
  its own definition — no account-id typo (e.g. `externl_expense`) was ever caught. Added
  `is_known_account()`; wired into `reservations.settle()`'s `destination_account_id` and
  `lifecycle.create_cell()`'s `funding_account_id`, the two call sites where a caller supplies a
  fixed-account name directly. Left the generic ledger core (`_write_transaction`) unvalidated —
  several existing tests deliberately use synthetic placeholder account names (`"x"`/`"y"`/`"a"`/
  `"b"`) to test raw balancing logic decoupled from the real account taxonomy, and validating there
  would have required rewriting them for no correctness gain.
- **`src/mitosis/money.py`:** `parse_minor_units` crashed with a raw `OverflowError` (not the
  documented `ValueError`) on `"Infinity"`, and on `"1e400"` the crash surfaced later, inside
  `ledger._write_transaction`, from SQLite's 64-bit `INTEGER` column rejecting the value. Also,
  `Decimal`'s native underscore-digit-separator support meant `"5_0"` silently parsed as $50.00 with
  no error. Now: non-finite values (`Infinity`/`NaN`) and underscores are rejected with a clean
  `ValueError` at parse time, and any value that wouldn't fit a signed 64-bit integer is rejected
  the same way instead of surfacing as a traceback three layers down.
- **`src/mitosis/events.py`:** `process_event`'s failure path called `record_failure` and then
  `raise`d the original exception — but if `record_failure` itself raised, that replaced the
  original with no trace of the real handler failure. Now the original is always what propagates;
  a `record_failure` exception is chained onto it (`raise exc from bookkeeping_exc`) rather than
  replacing it.
- **`tests/test_charter_properties.py`:** SPEC.md §0.1 claims every Charter clause maps to a named,
  CI-collectible property-test ID (`pytest -k <id>`); 7 of 15 collected zero tests under their own
  name (5 existed only as differently-named functions/classes; C11 and C15 had no test at all).
  Renamed the C2/C3 function and the C7/C8+C10 stateful-machine `TestCase` aliases so each ID is a
  literal substring of its node id; added `charter_canonical_forms` (C11 — money round-trips through
  integer minor units, genome hashing is deterministic and content-addressed, naive/non-UTC
  timestamps are rejected everywhere) and `charter_kernel_immutable` (C15, Phase-1 slice only — no
  Cell executes any code in this kernel at all, so full sandbox isolation is Phase 5/C12; what's
  checkable now is that genome content is inert data, never `eval`/`exec`/imported, and no kernel
  module writes into its own source tree). Added a dedicated `charter_no_overspend` property test
  for the new reservation-vs-cash guard (the existing test under that ID only covered RESOURCE
  metering vs. its reservation cap) and a `cell_cash_never_negative` invariant on the existing
  crash-recovery state machine.
- Added targeted unit tests: `test_reservations.py` (overdraft rejected exactly at the boundary,
  rejected via a second reservation eating remaining cash, allowed at exactly the available amount,
  unrecognized destination account rejected), `test_money.py` (non-finite values, `1e400`,
  underscore separators), `test_lifecycle.py` (unrecognized funding account rejected).
- Verified by hand before/alongside the tests: reproduced the original 1000×-budget overdraft
  end-to-end and confirmed it's now rejected with cash unchanged; confirmed `mitosis
  verify-golden-run` still reproduces its pinned hash unchanged (the golden scenario's reservation
  amounts were already within each Cell's funded budget, so the new guard changes nothing there);
  confirmed the CLI's existing exception handling already catches the new error types cleanly (no
  traceback) since `InsufficientBalanceError`/the account errors subclass the already-caught
  `ReservationError`/`LifecycleError`.
- **221 tests passing** (19 new, 0 removed; up from 202).
- Also split this file: 9 slices had grown it to ~42 KB, well past what a prime should read in
  full every session. Earlier entries moved to `docs/BUILD_RECORD_ARCHIVE.md`;
  `.claude/commands/prime.md` updated to use `git status -sb` (plain `--short` hides the
  ahead/behind line, which is how a 4-commits-unpushed branch was previously reported as "clean").
- Deliberately out of scope for this slice (see PRIORITIES.md): seeded id generation, clock-driven
  timestamps, reproduction/lineage/experiment tracking, model gateway/provider identification,
  wiring event_inbox/outbox into a real producer, `kill()` not sweeping open reservations/residual
  balances, resource-usage reconciliation against real logs, and the remaining CLI commands are all
  unchanged from the prior "Next" list. No CI is wired up yet (no `.github/` workflow) — the Charter
  tests and golden-run replay are collectible and passing locally but nothing runs them
  automatically on push.
- Next: either the CLI remainder (`list-cells/show-cell/fund-cell/kill-cell/ledger/verify-ledger`,
  purely additive) or wiring a CI workflow to actually run pytest + `verify-golden-run` on push —
  both are cheap and neither has a Phase 2+ prerequisite. Seeded id generation remains the largest
  single remaining Phase 1 item.

## 2026-07-21 — Spec review & v0.2 direction locked
- Reviewed MITOSIS v0.1 build spec (`~/Downloads/mitosis_full_build_spec.md`); delivered ~10 findings (real/synthetic money conflation, ledger hardening, reserve-without-release, no global spend breaker, no sim clock, 10-cell population can't show selection, farmable evidence credits, EV-based death, MAP-Elites too sparse, missing prompt mutation).
- User returned a v0.2 revision directive (`~/Downloads/MITOSIS_v0.2_revision_directive.md`) folding in the review + adding profit-first objective, 3-book accounting, population/carrying-capacity control, shared-reputation registry, sim-to-reality promotion ladder.
- Analysed directive: concur ~90%. Logged 4 pushbacks + 12 gap fixes + 7 creative additions (executable Colony Charter, prediction register, coroner reports, per-phase North Star table, governance-overhead ratio, chaos drills, solo-operator/vacation mode).
- Decisions: spec-only first pass; adopt all 19 amendments as normative. Plan saved at `~/.claude/plans/users-mohammadmaster-downloads-mitosis-cheeky-stardust.md`.
- **Wrote `docs/SPEC.md` v0.2** (1309 lines): all 32 directive sections + a Colony Charter (§0.1) mapping 15 constitutional invariants to named CI property-test IDs, all 19 amendments folded in normatively, per-phase North Star metric table (§27.1), Phase 0/1 coding task (§30). Downloads originals left untouched.
- Next: Phase 0 formal artifacts + `docs/DECISIONS.md`, then Phase 1 kernel.
- Committed `512fb2e` — `docs/SPEC.md` + project docs (PRIORITIES.md, BUILD_RECORD.md, CLAUDE.md, FUTURE_BUILD_HOOKS.md). First commit to the repo.

## 2026-07-22 — Phase 0 formal artifacts

- **Wrote `docs/DECISIONS.md`:** 18 ADRs covering the decisions-with-real-alternatives locked into SPEC.md v0.2 (three-book accounting, signed ledger amounts, canonical reservation FSM, real-spend breakers, Phase 3 gate softening, objective-only displacement, deterministic event ordering, executable Colony Charter, sandbox tiering, taint/clean-room migration, solo-operator model, golden-run semantic comparison, genome content addressing, and more), each with context/decision/consequences and a spec-section reference. Remaining amendments that are feature detail rather than alternatives-decisions are cross-referenced in a closing table instead of getting a standalone ADR.
- **Wrote `docs/STATE_MACHINES.md`:** formalized the Cell lifecycle FSM (`created|alive|dormant|quarantined|dead`) — states, transitions, guards, and required side effects — which SPEC.md §30 names but never diagrams; reproduced the already-normative reservation FSM (§4.4) as a companion diagram for implementers.
- **Wrote `docs/EVENT_SEMANTICS.md`:** the inbox/outbox atomic-processing algorithm, the `(effective_time, priority, event_id)` deterministic ordering tie-break (Amendment A5), simulated-vs-real event separation, and poison-event/dead-letter handling (§17.3), spelling out the mechanics behind §17's stated guarantees.
- Considered out of scope for this pass: SQLite DDL/schemas (naturally a Phase 1 kernel deliverable per §30's combined Phase 0+1 task list) and standalone diagrams for fitness vectors / promotion ladder (already adequately tabulated in SPEC.md §10, §25 — no separate artifact needed).
- Next: Phase 1 deterministic kernel per PRIORITIES.md.

## 2026-07-22 — Phase 1 kernel slice 1: ledger + reservations + sweeper

First code in the repo. Python 3.11 (`.venv`, `pyproject.toml`), Pydantic v2, raw `sqlite3` (no ORM, per §30.1 "avoid unnecessary frameworks"), pytest + Hypothesis.

- **`src/mitosis/money.py`:** Decimal-string -> integer-minor-units parsing/formatting (§30 dollar-string rule, Charter C11). Rejects binary-float paths and excess precision by construction.
- **`src/mitosis/migrations/0001_init.sql` + `db.py`:** numbered-migration runner (`schema_migrations` tracking table) per the "write migrations rather than hand-altering DB state" coding rule. Schema for `ledger_transactions`, `ledger_entries`, `reservations` per SPEC.md §3.2/§3.3/§4.2.
- **`src/mitosis/models.py`:** frozen Pydantic models (`Transaction`, `Entry`, `Reservation`) plus `Book`/`ReservationStatus` enums; UTC-aware-datetime validation built in.
- **`src/mitosis/ledger.py`:** `post_transaction` (idempotent, hash-chained, rejects unbalanced/cross-book by construction since `book` lives on the transaction not the entry), `get_balance` (always derived, never cached — C3), `verify_conservation` (C2), `verify_chain` (tamper-evidence, §3.4). Factored a non-transactional `_write_transaction` core so `reservations.py` can post ledger effects inside its own atomic block without nesting SQLite transactions — this was the one real design snag (SQLite `executescript`/nested `BEGIN` don't compose) and cost a couple of iterations to get right.
- **`src/mitosis/reservations.py`:** the canonical FSM from `docs/STATE_MACHINES.md` §2, implemented as an adjacency-table guard (`_ALLOWED_TRANSITIONS`) that doubles as the replay guard — once a reservation leaves a non-terminal state, retrying the same call is rejected rather than double-applied. `request`/`settle`/`release`/`mark_execution_unknown`/`mark_disputed`, each posting its ledger effect and updating status in one SQLite transaction (crash-atomic by construction, Charter C7).
- **`src/mitosis/sweeper.py`:** sweeps expired `reserved` reservations only (resolving stuck `execution_unknown` ones is a separate human/Auditor reconciliation flow, not automatic). Pluggable `ExternalOperationChecker` protocol; the Phase-1 default (`UnknownOperationChecker`) always returns `UNKNOWN` since there's no real external system yet to ask — lands in `execution_unknown`, never guesses `released`.
- **41 tests, all passing:** unit tests per module + `tests/test_charter_properties.py` with Hypothesis — `charter_ledger_balanced` (C1), `charter_conservation_and_balance_match` (C2/C3), and a `RuleBasedStateMachine` (`charter_crash_recovery`, C7) that runs random request/settle/release/crash/reconcile sequences and asserts conservation + hash-chain validity + committed-balance-matches-open-reservations after every step.
- Added `.gitignore` (none existed yet — needed before committing `.venv`/`__pycache__` could leak in).
- Deliberately out of scope for this slice (left for the next Phase 1 pass): `event_inbox`/`event_outbox`, the real-spend circuit breaker, resource metering, Cell lifecycle implementation, genome hashing, simulated clock, population limits, the CLI, and the golden-replay test.
- Next: pick up the Phase 1 remainder per `PRIORITIES.md`, most likely starting with the CLI + `mitosis init` since it gives the fastest path to an end-to-end demo of what already exists.

## 2026-07-22 — Phase 1 kernel slice 2: Cell lifecycle birth + CLI (init/status/create-cell)

`create-cell` can't exist without a Cell to create, so this slice pulled in the minimum lifecycle/genome/audit machinery it depends on rather than stubbing it out:

- **`src/mitosis/migrations/0002_cells.sql`:** `cell_genomes` (all 12 fields from SPEC.md §16.2), `cells`, `audit_events` (Amendment A8).
- **`src/mitosis/genome.py`:** minimal Phase-1 genome (`{"cell_type": ...}` only — real strategy content is Phase 5) canonicalized + SHA-256 hashed (Charter C11). Content-addressed: two Explorers get the same `genome_hash` and share one `cell_genomes` row by design.
- **`src/mitosis/audit.py`:** `record()` — plain insert, no transaction control of its own, same pattern as `ledger._write_transaction`.
- **`src/mitosis/lifecycle.py`:** `create_cell()` — the `created -> alive` birth transition, mirroring `reservations.request`'s shape: funds `cell:{id}:cash` from a funding account (default `seed_bank`), upserts the (deduped) genome, inserts the `cells` row as `alive` directly, and emits the audit event, all in one SQLite transaction. Idempotent on `idempotency_key`, same replay-guard pattern as the rest of the kernel.
- **`src/mitosis/cli.py`:** argparse-based (stdlib, no click/typer), `mitosis --db PATH {init,status,create-cell}`, registered as a `mitosis` console-script entry point in `pyproject.toml`. `init` supports an optional `--seed-capital` for a nicer demo path (funds `external_capital -> seed_bank`). `status` reports migrations applied, per-book transaction counts + conservation + chain validity, cell counts by status/type, reservation counts by status. `create-cell --type --budget [--book] [--funding-account] [--idempotency-key]` — `--book` defaults to `USD_SIM` per Amendment A7, budget parsed via `money.parse_minor_units` (Decimal, never float). Commands against a missing DB fail cleanly with "run `mitosis init` first" rather than silently creating one.
- **Explicit, documented known gap:** `create_cell` does **not** enforce Charter C9 (birth requires carrying-capacity permission) — population limits aren't built yet. Every birth currently succeeds if funding/genome bookkeeping succeed. Called out in the `lifecycle.py` module docstring and in `PRIORITIES.md` so it isn't mistaken for an oversight later.
- Verified end-to-end by hand via the installed console script (`init --seed-capital` → `create-cell` ×2 → `status` shows correct per-type/per-status counts and conservation=OK → re-running `init` is a clean no-op → `status`/`create-cell` against a non-existent DB path fail with exit code 1) before writing the test suite.
- **59 tests passing** (18 new: genome dedup/hashing, lifecycle birth + idempotency + audit-event emission + conservation, and CLI tests via `cli.main()` + `capsys` covering the same end-to-end flow plus error paths).
- Next: Phase 1 remainder per `PRIORITIES.md` — population limits are the natural next piece since `create_cell`'s C9 gap is now the most visible hole, but event_inbox/outbox and the real-spend breaker are also still open.

## 2026-07-22 — Phase 1 kernel slice 3: population limits and carrying capacity (Charter C9)

Closes the known gap flagged at the end of the previous slice.

- **`src/mitosis/migrations/0003_population.sql`:** single-row `colony_config` table. Field names (`max_living_cells`, `max_active_cells`, `max_parallel_experiments`, `max_births_per_epoch`, `max_lineage_population_fraction`) match SPEC.md §27.1's `colony.yaml` `population:` block exactly, including its documented dev defaults (1000/100/20/25/0.20) — added as `DEFAULT_POPULATION_LIMITS` in `models.py`.
- **`src/mitosis/population.py`:** `get_limits`/`set_limits_if_absent` (first `init` wins — re-running `init` with different flags never silently changes a running colony's carrying capacity), `living_count` (any status except `dead`), `active_count` (`alive` only — dormant is idle, quarantined is restricted, neither counts as active), and `check_birth_licence` which raises `CarryingCapacityError` when either cap would be exceeded.
- **Scope decision, stated up front in the module docstring:** only `max_living_cells`/`max_active_cells` are enforced. The other three fields are stored (so the config shape matches `colony.yaml`) but deliberately not checked yet, because their prerequisites don't exist in this kernel: `max_parallel_experiments` needs experiment tracking, `max_births_per_epoch` needs the simulated clock, `max_lineage_population_fraction` needs reproduction/lineage tracking. Same reasoning for skipping Amendment A2's displacement path (docs/DECISIONS.md ADR-009) — displacing an objectively-failing Cell requires the §10.5 death criteria, which nothing in this kernel evaluates yet. A birth beyond capacity is simply denied (`CarryingCapacityError`), matching §9.3's "the birth waits" for the case where no displacement target exists — a synchronous kernel call can't wait, so it raises instead.
- **`src/mitosis/lifecycle.py`:** `check_birth_licence` is called *inside* `create_cell`'s `BEGIN IMMEDIATE` block, after the write lock is acquired but before any genome/ledger/insert work — so two concurrent births can't both pass the check before either commits, same concurrency-safety shape as the Charter C5 real-spend cap check. A denied birth touches nothing: no genome row, no ledger transaction, no idempotency key consumed (verified explicitly in tests).
- **`src/mitosis/cli.py`:** `init` gained `--max-living-cells`/`--max-active-cells` (defaults from `DEFAULT_POPULATION_LIMITS`); `status` now prints `living: X/limit  active: Y/limit` alongside the existing by-status/by-type breakdown; `main()` catches `population.PopulationError` for a clean error message and exit code 1 instead of a traceback.
- Added `test_charter_carrying_capacity` to `tests/test_charter_properties.py` (Hypothesis, C9) — for randomized limits and randomized attempted-birth counts, asserts the living-cell count never exceeds the configured cap after *any* individual attempt, and that exactly `min(attempts, max_living)` births are ever granted.
- Verified end-to-end by hand first (init with `--max-living-cells 2` → 2 successful creates → 3rd denied with a clear message → `status` shows `2/2` → re-init with different limits leaves the colony's limits untouched) before writing the test suite.
- **74 tests passing** (15 new: `test_population.py` unit tests, two `test_lifecycle.py` integration tests for the denial path, three `test_cli.py` tests, one Charter property test).
- Next: Phase 1 remainder per `PRIORITIES.md`. The simulated clock is now a dependency of two open items (`max_births_per_epoch` enforcement and the general Phase 1 remainder), so it's a reasonable next pick — but event_inbox/outbox and the real-spend breaker remain equally open.

## 2026-07-22 — Phase 1 kernel slice 4: global real-spend circuit breaker (Charter C5)

- **`src/mitosis/migrations/0004_real_spend_limits.sql`:** single-row `real_spend_limits` table. Field names/shape match SPEC.md §27.1's `colony.yaml` `real_spend_limits:` block exactly, including its documented dev defaults (25/100/500/5000/200 cents) — added as `DEFAULT_REAL_SPEND_LIMITS` in `models.py`, alongside a new `RealSpendSnapshot` model for status/breaker-check display.
- **`src/mitosis/real_spend_breaker.py`:** `configure_if_absent` (unaudited baseline, same shape as population's set-once) vs `set_limits` (explicit administrator adjustment — always applies, always audited, and the audit `event_type` distinguishes `real_spend_limit_raised` from `_configured` per §5.2's "lowering is immediate, raising needs an audit event"). `snapshot()` computes concurrent-reserved (open USD_REAL reservations) plus settled spend in trailing 1-hour/1-day/~30-day windows (a documented approximation, not a calendar month) by querying `reservation_settle`-type ledger transactions directly — no new timestamp column needed. `check()` enforces per-request, concurrent-reserved, and all three time-windowed caps, treating currently-open reservations as immediate exposure against every window per §5.3 ("settled spend + currently reserved spend, not only completed charges").
- **Scope decision:** `provider_limits` is stored (shape parity with `colony.yaml`) but not enforced — no model gateway or provider identification exists in this kernel yet (Phase 4). Documented in the module docstring, same pattern as population.py's deferred fields.
- **`src/mitosis/reservations.py`:** `check()` is called inside `request()`'s `BEGIN IMMEDIATE` block, gated on `book == Book.USD_REAL` only — USD_SIM/RESOURCE reservations are untouched, and the breaker deliberately does not gate `ledger.post_transaction` generally: real spend flows through the reservation gate per the two-phase-spend model (§4), so an internal treasury transfer like Cell birth-funding isn't "spend" in the sense §5 targets.
- **`src/mitosis/cli.py`:** `init` gains `--per-request-cents/--per-hour-cents/--per-day-cents/--per-month-cents/--max-concurrent-reserved-cents`, all defaulting to `None` so a flag-less re-init never resets a previously-adjusted limit (same footgun-avoidance reasoning as population limits, but the mechanism differs: real-spend limits *are* meant to be live-adjustable by re-running `init` with explicit flags, whereas population limits are set-once — because §5.2 explicitly describes admin raise/lower as an expected workflow and §9 does not). `status` gained a "real-spend breaker (USD_REAL)" section showing concurrent-reserved and hour/day/~30d spend against configured caps.
- Verified end-to-end by hand first (fund a USD_REAL cell → request within caps succeeds → a second request that would push the trailing-hour projection over its cap is denied with the exact numbers in the message → a request over the flat per-request cap is denied → settling the first reservation and re-checking the snapshot shows the settled amount move from "concurrent reserved" into "spend last hour/day/~30d" correctly) before writing the test suite.
- **92 tests passing** (18 new: `test_real_spend_breaker.py` unit tests covering limits config/audit-trail/each cap path/window-boundary math, `reservations.request` USD_REAL-vs-USD_SIM integration tests, four CLI tests, one Charter property test `charter_realspend_cap`).
- Next: Phase 1 remainder per `PRIORITIES.md` — event_inbox/outbox and the simulated clock are the two largest remaining pieces; the simulated clock also unblocks `max_births_per_epoch` enforcement and would let the real-spend breaker's hour/day/month windows use simulated rather than wall-clock time if that ever matters for replay determinism.

## 2026-07-22 — Phase 1 kernel slice 5: simulated clock (SPEC.md §6)

- **`src/mitosis/migrations/0005_simulation_clock.sql`:** single-row `simulation_clock` table — mode, `simulated_seconds_per_wall_second`, plus a `(checkpoint_simulated_at_utc, checkpoint_wall_at_utc)` pair.
- **`src/mitosis/clock.py`:** a *lazy* clock — no background thread ticks time forward; `now()` projects the last checkpoint forward by `elapsed_wall_time * rate(mode)` on read (rate is 0 for paused/step, 1 for realtime, configurable for accelerated — matching colony.yaml's `simulated_seconds_per_wall_second`). This fits the kernel as it exists today: a synchronous CLI tool with no event loop, so there's nothing to tick continuously until Phase 2's flight simulator has a real scheduler. `advance(delta)` re-anchors the checkpoint — the mechanism behind `mitosis advance-time` — and works the same regardless of configured mode, matching §30's CLI requirement. `set_mode()` re-anchors to the current simulated instant before switching, so a mode change is never itself a jump. `get_state`/`now` fall back to an implicit default (paused, anchored at current wall time) when unconfigured, matching the population/real-spend-breaker fallback pattern rather than raising.
- **Explicit, deliberate scope boundary (documented in the module docstring):** existing kernel timestamps — ledger `effective_at_utc`, reservation `reserved_at`/`expires_at`, the real-spend breaker's hour/day/month window math, `audit_events.created_at_utc` — all still run on real wall-clock time; none of them were touched. SPEC.md §6.3's synthetic-vs-real-event timestamp split ("never mixed without explicit conversion metadata") is a separate, larger integration with real correctness risk — e.g. the real-spend breaker's windows would need a careful redesign if USD_SIM and USD_REAL transactions started living on different clocks. This slice ships the clock primitive and `advance-time` only.
- **CLI:** `mitosis advance-time --days N` (exact §30 signature, `--days` accepts fractional values); `init` gains `--clock-mode`/`--clock-rate` (set-once baseline like population limits — re-running `init` never silently resets the clock); `status` gained a "simulated clock" section showing mode, rate, and current simulated time.
- Verified end-to-end by hand first (init paused at a fixed instant → advance by 1 day then 0.5 days → status reflects the cumulative advance → re-init with `--clock-mode realtime` correctly leaves the colony paused → switching an existing colony's clock to accelerated and checking status shows time visibly progressing between commands) before writing the test suite.
- **113 tests passing** (21 new: `test_clock.py` covering all four modes' rate math, advance/set_mode re-anchoring semantics, clock-skew protection, negative-delta rejection, UTC validation, and set-once init behavior; six CLI tests).
- Next: Phase 1 remainder per `PRIORITIES.md`. event_inbox/outbox is now the largest unbuilt piece; wiring the clock into `max_births_per_epoch` and into USD_SIM timestamps are both natural follow-ups but deliberately weren't bundled into this slice.

## 2026-07-22 — Self-review: closed a CLI test-coverage gap

`/critique` on the simulated-clock summary found no factual errors, misalignment, or overclaims — every number and claim checked out against the actual repo (test counts, file scope, ADR references). One genuine minor gap: `clock.advance()` rejecting a negative delta was unit-tested in `test_clock.py` but never confirmed to surface as a clean CLI error (exit 1, stderr message, not a traceback) through `mitosis advance-time --days -1`. Added `test_advance_time_rejects_negative_days` to `test_cli.py`.
- **114 tests passing** (1 new).
- Commit `4b50f48`.

## 2026-07-22 — Phase 1 kernel slice 6: event_inbox/outbox (SPEC.md §17, §3.5; Charter C6)

- **`src/mitosis/migrations/0006_events.sql`:** `event_inbox` and `event_outbox` tables. Field names/shape match §17.2/§3.5's schema list, plus a required `priority` column — the illustrative schema block in SPEC.md/EVENT_SEMANTICS.md omits it, but ADR-011/§17.1's `(effective_time, priority, event_id)` ordering key and "every event producer must supply a stable priority" make it a required field in practice.
- **`src/mitosis/models.py`:** `EventStatus` (`pending|processed|dead_letter`), `Event`, `OutboxEventSpec` (caller-supplied, pre-event_id — mirrors `EntrySpec`/`Entry`), `OutboxEvent`.
- **`src/mitosis/events.py`:** implements docs/EVENT_SEMANTICS.md §3's atomic algorithm exactly. `enqueue` (idempotent on `dedupe_key` — the producer-side guard, same shape as `idempotency_key` elsewhere in the kernel) and `process_event` (the consumer-side guard: checks `event_inbox.status` inside a `BEGIN IMMEDIATE`, re-checked after the write lock in case of a concurrent redelivery race, mirroring the population/real-spend concurrency-check pattern). `next_ready` returns pending events whose effective_time — `simulated_at` if set, else `available_at` — has arrived, ordered `(effective_time, priority, event_id)` per Amendment A5. Poison-event handling (`record_failure`) increments `attempt_number` and, past a configurable threshold, moves the event to `dead_letter` and emits an audit event (§17.3); `replay_dead_letter` is the controlled human-triggered re-admission path. `dispatch_outbox` publishes staged outbox events and marks them published one at a time, so a publisher crash only re-publishes the remainder on retry.
- **Two distinct idempotency guards, deliberately not merged:** `dedupe_key` (producer calling `enqueue` twice for the same logical event) vs. inbox `status` (a single event redelivered and reprocessed) — documented in the module docstring since it's not obvious from the schema alone why both exist.
- **Scope decisions, stated up front in the module docstring (mirrors the pattern from population.py/real_spend_breaker.py):** nothing in the kernel yet produces real events through this path — Phase 2's flight simulator and later Phase 1 work are the first real callers, so this slice ships the primitive only. Poison-event dead-lettering does **not** quarantine the implicated Cell — the `alive`/`dormant -> quarantined` lifecycle transition doesn't exist in this kernel yet (only `created -> alive` birth is built) — that's tracked as its own item in `PRIORITIES.md`. `next_ready`'s ordering compares `simulated_at`/`available_at` ISO-8601 strings directly via SQL, the same approach `real_spend_breaker`'s window queries already use — reconciling that against a *live* simulated clock is deferred until some future slice actually wires `clock.py` into an event producer.
- **`src/mitosis/cli.py`:** `status` gained an "events:" section (inbox counts by status, outbox unpublished count) — the same "extend `status`" integration point used by every prior slice, since no real event producer exists yet to give this a more meaningful CLI hook.
- Verified end-to-end by hand first (enqueue with a duplicate `dedupe_key` short-circuits; `next_ready` orders correctly across mixed priority/effective_time; `process_event` redelivered 4× only invokes the handler once and posts the ledger side effect exactly once; staged outbox events dispatch and don't redispatch; a handler raising 5× against `max_attempts=3` dead-letters on the 3rd attempt and stops calling the handler; `replay_dead_letter` resets it to pending) via a scratch script, then via the installed `mitosis` console script's `status` output, before writing the test suite.
- Added `test_charter_idempotent_handlers` (Hypothesis, C6) to `tests/test_charter_properties.py` — for any redelivery count, a handler's ledger-affecting side effect is applied exactly once and the event ends up `processed`.
- **144 tests passing** (30 new: 28 in `tests/test_events.py` covering enqueue/ordering/idempotent processing/dead-letter/replay/outbox dispatch, 1 Charter property test, 1 CLI status test).
- Next: Phase 1 remainder per `PRIORITIES.md` — resource metering and the remaining Cell lifecycle transitions (which would also close the poison-event quarantine gap) are the two most visible open pieces; wiring the simulated clock and event_inbox/outbox into a real producer are both natural follow-ups but deliberately weren't bundled into this slice.

## 2026-07-24 — Phase 1 kernel slice 7: remaining Cell lifecycle transitions (docs/STATE_MACHINES.md §1, SPEC.md §10.5 Amendment A15, Charter C8/C10)

- **`src/mitosis/lifecycle.py`:** the rest of the Cell lifecycle FSM — `wake` (dormant->alive), `sleep` (alive->dormant), `quarantine` (alive|dormant->quarantined, links the triggering finding in its audit event per §1.4), `clear_quarantine` (quarantined->alive|dormant, mirrors the reservation FSM's disputed->resolved pattern), `kill` (alive|dormant|quarantined->dead, terminal). `_ALLOWED_TRANSITIONS` is the FSM adjacency table from docs/STATE_MACHINES.md §1.2 (`created`/`dead` are deliberately not keys: `created` is transient and handled only by `create_cell`, `dead` is terminal per Charter C8).
- **Real bug caught by hand-verification before the test suite existed:** a single shared adjacency table isn't enough — `wake` and `clear_quarantine` both target `alive`, but `quarantined -> alive` is only a valid FSM edge when it's `clear_quarantine`'s explicit review decision, not `wake`'s implicit wake-event trigger. Running the hand-verification script (see below) surfaced `wake()` silently succeeding from `quarantined`. Fixed by adding a per-operation `valid_sources` set on top of the shared table, so each function also restricts which source status it may fire from — mirroring how `_check_transition` alone wasn't sufficient. This shows up as `test_wake_rejected_from_quarantined`/`test_sleep_rejected_from_quarantined` in the test suite.
- **Coroner reports (Amendment A15):** new `coroner_reports` table (migration `0007_coroner_reports.sql`), filed atomically inside `kill()`. Fields match §10.5's list: genome hash, spend by book, stage reached, cause of death, final hypotheses, links to experiments. **`ledger.spend_by_book`** (new query helper) computes genuine spend per Cell per book — entries tagged with the Cell's `cell_id` that are positive *and* land on an account outside the Cell's own `cell:{id}:cash`/`cell:{id}:committed` pair. This deliberately excludes internal reserve/release moves (cash<->committed, both the Cell's own accounts) and inbound birth funding (negative on the funding side), counting only money that actually left the Cell's control — e.g. a reservation's settlement destination entry. `stage_reached`/`experiment_ids` are always `None`/`[]` in this kernel (stage progression and experiment tracking don't exist yet) — same deferred-field-for-shape-parity pattern as `colony_config`/`real_spend_limits`.
- **Closed the slice-6 gap:** `events.py`'s `process_event`/`record_failure` gained an optional `cell_id`. When given and a poison event reaches dead-letter, the implicated Cell is quarantined in the same transaction via `lifecycle._transition_core` (the non-transactional-core shape `ledger._write_transaction` established, reused here across modules) — but only if the Cell is currently alive/dormant, so a second poison event against an already-quarantined (or dead, for an unrelated reason) Cell doesn't crash dead-lettering.
- **`src/mitosis/cli.py`:** `status` gained a "coroner reports filed: N" line under the cells section.
- Verified end-to-end by hand first: a scratch script exercising birth -> sleep -> wake -> quarantine -> (wake/sleep correctly rejected) -> clear_quarantine -> reserve+settle -> kill -> coroner report, then a second scratch script confirming a failing event handler's dead-letter quarantines the implicated Cell and that a second poison event against the now-quarantined Cell doesn't crash — before writing the automated test suite. Also re-ran the installed `mitosis` console script's `status` output to confirm the new line renders.
- Added `test_charter_dead_cell_inert` (Hypothesis stateful, C8) and `test_charter_audit_complete` (Hypothesis stateful, C10) to `tests/test_charter_properties.py` as one `CellLifecycleMachine`: for any interleaving of birth/sleep/wake/quarantine/clear_quarantine/kill, a dead Cell rejects every further transition attempt, and the audit-event count for a Cell always equals the number of transitions that actually succeeded for it.
- **167 tests passing** (23 new: unit tests in `test_lifecycle.py` for each transition + coroner-report contents, `test_ledger.py` for `spend_by_book`, `test_events.py` for the quarantine wiring, one Charter stateful-machine test class covering C8+C10).
- Deliberately out of scope for this slice (see PRIORITIES.md): `kill()` doesn't sweep the dead Cell's open reservations or reclaim its residual balances; quarantine/taint doesn't use §18's structured provenance-label schema (a free-text reason + linked-finding dict instead); resource metering and the remaining wiring items are unchanged.
- Next: Phase 1 remainder per `PRIORITIES.md` — resource metering is now the most visible unbuilt piece with no remaining lifecycle blocker; wiring the simulated clock into real timestamps and event_inbox/outbox into a real producer remain open follow-ups.

## 2026-07-24 — Phase 1 kernel slice 8: resource metering (SPEC.md §2.2/§2.3 Amendment A6, Charter C4)

- **`src/mitosis/migrations/0008_resource_usage.sql`:** new `resource_usage` table — the Phase-1 `resource_usage` entity §31's data model names explicitly. Fields: `cell_id`/`reservation_id` (both FK'd, NOT NULL — Amendment A6's "every metered operation links to exactly one reservation"), a CHECK-constrained `resource_type` matching §2.2's list (input/output tokens, model calls, CPU/memory-seconds, browser minutes, network requests, storage byte-days, human minutes, approval actions), `quantity` (physical unit count) and `minor_units` (cost against the reservation's budget) as separate columns, `idempotency_key` UNIQUE.
- **`src/mitosis/resource_metering.py`:** `record_usage` — the core of this slice. Requires the reservation to already exist, belong to the given `cell_id`, be `book=RESOURCE`, and be in the exact `reserved` status (not just "not yet terminal" — see the bug below); rejects with `ResourceOverspendError` if the new event would push cumulative recorded `minor_units` past the reservation's `maximum_amount`, checked inside the same `BEGIN IMMEDIATE` the insert runs in (the established C5/C9-style "check under the write lock" shape). This overspend guard **is** Charter C4 ("Cells cannot overspend their authorised budget") for the RESOURCE book — a Charter clause marked P1 in SPEC.md §0.1 that had no implementation or named test until this slice. `total_minor_units`/`usage_by_type` are read helpers a caller uses to feed `reservations.settle`/`sweeper.py` — this slice deliberately reuses the existing settlement machinery rather than inventing a parallel one. `verify_linkage` re-derives Amendment A6's completeness invariant (every usage row's reservation is RESOURCE-book and belongs to the same cell) directly from the tables, the same "double-check against tampering" shape as `ledger.verify_conservation`.
- **Two real bugs caught by hand-verification before the test suite existed** (a scratch script exercising record/idempotent-replay/overspend/wrong-book/settle/reconcile before any pytest was written):
  1. Recording usage against a reservation already in `partially_settled` silently succeeded. `partially_settled` isn't one of the two terminal reservation statuses, but `reservations._ALLOWED_TRANSITIONS` only permits `partially_settled -> released` next — there is no way to settle any *further* recorded usage against it, so it would sit permanently unlinked from a settlement (a direct Amendment A6 violation). Fixed by checking for the exact `reserved` status rather than excluding only `{settled, released}` — the same lesson as slice 7's `wake`/`clear_quarantine` bug: checking "not terminal" is weaker than checking "is the one specific valid state."
  2. (Caught while writing the fix for #1) `execution_unknown`/`disputed` reservations have the identical problem and needed the same fix, folded into the same `!= RESERVED` check rather than an enumerated exclusion list.
- **`src/mitosis/cli.py`:** `status` gained a "resource usage (RESOURCE book, Amendment A6):" section — colony-wide quantity by `resource_type` plus `verify_linkage`'s result.
- Verified end-to-end by hand first: birth a RESOURCE-book Cell, reserve a budget, record usage against it (idempotent replay confirmed, overspend rejected, wrong-book/wrong-cell reservations rejected), settle for the recorded total, confirm usage-after-settlement and usage-after-partial-settlement are both rejected, confirm `verify_linkage`/RESOURCE-book conservation hold — then the installed `mitosis` console script's `status` output with real usage rows — before writing the automated test suite.
- Added `test_charter_no_overspend` (Hypothesis, C4) to `tests/test_charter_properties.py` — for any reservation cap and any sequence of attempted usage recordings, cumulative recorded `minor_units` never exceeds the cap after any single attempt.
- **183 tests passing** (16 new: 15 in `tests/test_resource_metering.py` covering recording/idempotency/validation/overspend/state-guard/linkage, 1 Charter property test).
- Deliberately out of scope for this slice (see PRIORITIES.md): shadow-pricing (converting a raw physical quantity into `minor_units`) is left to the caller — no cost-accounting subsystem exists until Phase 4's model gateway; reconciling recorded usage against actual sandbox/model-gateway logs (Amendment A6's other half) isn't possible yet since no such logs exist; issuing a Cell's initial RESOURCE-book cash balance uses the existing generic `create_cell`/`ledger.post_transaction` path, no new funding flow was added.
- Next: Phase 1 remainder per `PRIORITIES.md` — with lifecycle transitions and resource metering both landed, the simulated-clock/event-producer wiring items and reproduction/experiment tracking (which unblock the remaining deferred population/coroner-report fields) are the largest open pieces.

## 2026-07-25 — Phase 1 kernel slice 9: golden-run replay (SPEC.md §26, Amendment A12, ADR-017; §29 criterion 11)

The last named Phase 1 deliverable with no Phase 2+ prerequisite. §30's deliverable list ends with "golden replay test" and its required-CLI list ends with `mitosis verify-golden-run`; this slice is both.

- **`src/mitosis/golden.py` — the scenario.** One fixed, fully-specified sequence with no randomness and no wall-clock reads: explicit config (population/real-spend/clock set rather than inherited from `DEFAULT_*`, so a later default change can't silently alter the run's meaning), seed capital in all three books, four births (one per Cell type/book combination, whose order *defines* the `cell#N` aliases), the reservation FSM in every shape it supports (full settle, partial-settle-then-release, plain release, and one left in `execution_unknown`), a USD_REAL path inside the C5 caps, resource metering settled for exactly what was metered, every remaining lifecycle transition ending in a coroner report, events including a double-processed batch, a poison event that dead-letters and quarantines its Cell, and an outbox produce-then-dispatch, then a clock advance.
- **The comparison model (ADR-017 / Amendment A12).** `semantic_snapshot` reduces the resulting colony to what its economics *mean* — normalized balances per (book, account), transaction-type counts, Cell status/type/genome-hash, reservation shapes, metered usage, coroner contents, audit-event-type counts, inbox/outbox state, clock position — with every volatile field excluded: uuid4 primary keys, wall-clock timestamps, hash-chain digests. Cell ids become birth-order aliases (`cell#0`…), so `cell:{uuid}:cash` normalizes to `cell:cell#0:cash`. `semantic_hash` is SHA-256 over that canonicalized structure; `semantic_invariants` carries the Charter-level facts (per-book conservation, chain validity, resource linkage, living/active counts, coroner count) alongside it.
- **Why normalization isn't a cop-out, stated in the module docstring:** the kernel has no seeded id generation and its timestamps are still real wall-clock, so a byte-identical rerun is *impossible by construction* today. ADR-017 anticipated exactly this ("semantic invariants plus hash, not raw byte equality"). Both underlying gaps are tracked in PRIORITIES.md.
- **Verified the comparison actually earns its two halves** (hand-verification, before the test suite): monkeypatching `kill()` to stop filing coroner reports trips the *invariants* (`coroner_reports: expected 1, got 0`); monkeypatching births to overfund by 1 keeps conservation perfectly intact — all invariants pass — and is caught *only* by the hash. That second case is the concrete argument for ADR-017's "plus a hash" and is now `test_hash_catches_drift_that_invariants_miss`.
- **Determinism gap found and logged** (`FUTURE_BUILD_HOOKS.md`): Amendment A5's `(effective_time, priority, event_id)` key is a *total* order but not a *reproducible* one — same-instant same-priority events tie-break on a `uuid4`. The scenario sidesteps it by giving every event a distinct priority, but a Phase 2 producer would be flaky. Real finding, out of scope here (seeded ids touch every `uuid.uuid4()` call site).
- **Also found:** the first regression simulation (breaking C6 idempotency directly) never reached the snapshot — the handler's own ledger `idempotency_key` rejected the double-post first. Defence in depth working as intended, and worth knowing the golden run's C6 assertion is a second line rather than the only one.
- **CLI:** `mitosis verify-golden-run` prints the invariants, both hashes, and on failure names the diverged invariants plus the snapshot sections that differ (§26.2's "visible diff"), exiting 1. `--update-expectations` is A12's migration path — it regenerates `golden_expectations.json` and prints a warning that an unreviewed change means behaviour drifted. Runs against its own fresh in-memory colony, never the `--db` path, so a golden run can't depend on or disturb real colony state (asserted in `test_verify_golden_run_does_not_touch_the_colony_db`).
- Verified by hand first: generated the expectations through the CLI itself, confirmed a clean PASS with exit 0, confirmed the hash is byte-identical across 5 consecutive runs, hand-checked the resulting economics rather than just their stability (USD_SIM conservation sums to 0; `colony_treasury` is 300 not 600, proving the double-processed events landed once — Charter C6; the `execution_unknown` reservation still holds its 250 committed — Charter C7; the coroner's 1,550 spend correctly excludes the 550 that was released), then confirmed the CLI drift path prints diagnostics and exits 1.
- **202 tests passing** (19 new: `tests/test_golden.py` covering the scenario's coverage of every lifecycle status and reservation shape, the C6/C7 pins, hash reproducibility across runs, absence of volatile identifiers from the snapshot, alias stability, the shipped-expectations CI guard, and both drift-detection paths; plus three CLI tests).
- Deliberately out of scope: seeded ids and clock-driven timestamps (both tracked); replaying from *stored model outputs* (§26.2) — no model calls exist until Phase 4, so there's nothing to record yet; multiple golden scenarios (§26.1's "scenarios" plural) — one thorough scenario is the right size until Phase 2 produces behaviour worth pinning separately.
- Next: Phase 1 remainder per `PRIORITIES.md`. Seeded id generation is now the most load-bearing open item (it unblocks reproducible event ordering *and* byte-level replay); the remaining CLI commands (`list-cells/show-cell/fund-cell/kill-cell/ledger/verify-ledger`) are the last purely-additive Phase 1 surface.

---

## 2026-07-26 — Reproduction and lineage tracking (the Phase 2 prerequisite)

The first Phase 1 item that isn't merely additive: Phase 2's flight simulator needs Cells that
reproduce, and `max_lineage_population_fraction` (§9.2) had been stored-but-unenforced since slice 3
precisely because there was no lineage to measure.

- **New `src/mitosis/lineage.py` + migration `0009_lineage.sql`.** `reproduce()` is the second
  birth path: a child of a living Cell, **funded from the parent's own cash** rather than a colony
  account. That funding rule is the point — a parent cannot mint capital, so lineage growth is
  bounded by the lineage's own money, and Charter C4's guard applies to reproduction for free.
  `cells` gained `parent_cell_id` (NULL for a seeded founder), plus immutable denormalized
  `founder_cell_id`/`generation`.
- **The design decision, written up as `docs/DECISIONS.md` ADR-019.** §9.4 defines lineage
  "strictly by genome parentage", which is unimplementable as stated against this kernel: genomes
  are content-addressed (ADR-018) and Phase 1 genome content is a placeholder carrying only
  `cell_type`, so *every* commercial Cell hashes to one genome row — deriving lineage from it would
  put unrelated Cells in one lineage and fire the cap on them. There's also a structural problem
  independent of Phase 1: under content addressing an unmutated child *is* its parent's genome, so
  a genome-parentage edge for it would be a self-loop. Resolution: vertical descent is recorded on
  the Cell and is what the cap is enforced against; genome parentage is recorded too, but only
  where a mutation actually changed the content. Amendment A10's substance is preserved — lineage
  means vertical descent, and a shared module (or a shared genome) never creates a lineage edge.
- **`max_lineage_population_fraction` now enforced** (`check_lineage_licence`, inside the write
  lock like every other birth check). Two consequences worth stating plainly, both documented in
  lineage.py, ADR-019, and the error message itself: seeded founders are exempt (a founder has no
  ancestor, and a lone founder is trivially 100% of a one-Cell colony), and **a small colony
  genuinely cannot reproduce** — with the colony.yaml default of 0.20, any second-generation Cell
  in a 4-Cell colony is already 40% of it. Growing past the seed needs enough founders or a
  raised cap. That's §9.3 applied literally ("the birth waits" → a synchronous kernel raises),
  matching the conservative stance population.py already takes for displacement.
- **`genome.py` gained mutation support:** `canonical_genome_json(cell_type, mutation)` overlays
  caller-supplied fields, with JSON-serializability validated up front (new `GenomeError`).
  `lifecycle._get_or_create_genome` now carries `parent_genome_hashes`/`mutation_operator`/`version`
  on creation, and drops a self-referential parent edge if a "mutation" didn't actually change
  anything. Provenance is recorded only when the row is *created* — rediscovering existing content
  from a different parent must not rewrite how that genome first came to exist.
- **Golden run extended** (SPEC.md §26 names the "expected lineage tree" as golden-run content, so
  reproduction drift had to become visible in CI): the scenario now reproduces the auditor with a
  mutated genome, and `semantic_snapshot` carries parent/founder/generation as *aliases*, keeping
  the snapshot uuid-free. This is a real expectation migration via the A12 path
  (`--update-expectations`); the diff was reviewed line by line and every change is attributable to
  the new step — parent debited exactly 500, child credited 500, one new `cell_reproduction_funding`
  transaction, one more lifecycle audit event, living 3→4, active 2→3. No conservation, chain, or
  linkage invariant moved. The scenario's lineage cap was raised to 0.50 with a comment, since a
  4-Cell colony can't reproduce at 0.20.
- **CLI:** new `mitosis reproduce --parent --budget [--type --mutation --mutation-operator]`, and
  `status` gained a lineage section (per-founder living/total/depth/share, largest first, plus the
  integrity check).
- Verified by hand before the tests, which is again where the design got pinned down: built a
  4-generation lineage at realistic scale and confirmed generation/founder propagation, that an
  unmutated child reuses its parent's genome row while a mutated one gets a distinct genome with a
  correct parent edge and incremented version, that the parent is debited exactly the child's
  budget with conservation and the hash chain intact, and that a death shrinks the *living* lineage
  count without erasing lineage history. Then drove every rejection path (unknown/dormant/
  quarantined/dead parent, over-balance, zero budget) confirming cash was unchanged after each, and
  the CLI's error paths end to end (clean `error:` lines, exit 1, no tracebacks).
- Also verified the **migration upgrade path**, which no test covers because every test builds a
  fresh DB: built a colony on the pre-0009 schema, confirmed the new columns were genuinely absent,
  then upgraded it and confirmed `founder_cell_id` backfills to each Cell's own id with
  `generation` 0 and integrity green. That detour surfaced one real robustness gap — a NULL founder
  (unreachable through the kernel, but reachable in a corrupted or hand-edited DB) made `status`
  traceback instead of reporting, right next to the integrity line that exists to flag it. Fixed
  and covered.
- **274 tests passing** (43 new, 0 removed; up from 230). New `tests/test_lineage.py` (36);
  `tests/test_cli.py` gained 6 for the new verb and the status section; `test_golden.py` gained
  `test_snapshot_pins_the_lineage_tree`. Charter coverage: C9 gained
  `test_charter_carrying_capacity_lineage_share`, a Hypothesis property that no lineage ever
  exceeds its configured share across arbitrary reproduction sequences — it immediately earned its
  keep by falsifying an over-strong first draft of the invariant and forcing the seeded-founder
  exemption to be stated explicitly (now pinned by its own test rather than assumed away).
- Deliberately out of scope, unchanged from the prior list: **displacement** (§9.3/ADR-009) still
  isn't implemented — a denied birth stays denied, because the §10.5 death criteria that identify an
  objectively-failing Cell to evict still don't exist. Sexual recombination / multi-parent genomes
  (§16.5) are out (schema takes a list; `reproduce` takes one parent). §16.3's inheritance classes
  are not modeled: a child inherits genome content and nothing else, since this kernel has no
  assets, obligations, customers, or credentials to inherit or withhold. `max_births_per_epoch` is
  still unenforced (needs the clock wired to a real epoch counter) and `max_parallel_experiments`
  still needs experiment tracking.
- Committed as `0224866` and pushed.
- Next: Phase 2's other prerequisites are experiment tracking (also unblocks
  `max_parallel_experiments` and the coroner report's always-empty `experiment_ids`/`stage_reached`)
  and wiring the simulated clock into real timestamps/epochs. The remaining CLI commands and
  `kill()`'s reservation/balance sweep stay additive.

---

## 2026-07-27 — Phase 4 model gateway: the kernel can spend real money

A deliberate jump over Phases 2 and 3. The stated goal was to get Cells spending real money as
quickly as possible, so the flight simulator (Phase 2) and the evolutionary-machinery validation
(Phase 3) were skipped rather than deferred-by-accident. **That tradeoff is real and worth
restating: the selection machinery those phases exist to validate is still unvalidated, so this
colony can now spend real money on an evolution loop nobody has shown works.** Defensible for a
bounded, hard-capped experiment; not defensible at scale.

Everything below is the first code in MITOSIS whose *successful execution costs money*.

- **`pricing.py`** — versioned pricing table (`PRICING_TABLE_VERSION`, recorded on every call so a
  price change reads as an accounting change rather than as Cell behaviour, per §24.2). Cost is
  computed in **micro-USD**, not USD_REAL minor units, and rounded **up** to the cent for the
  ledger. Written up as **ADR-020**: USD_REAL's minor unit is the cent, a single call routinely
  costs a fraction of one, and rounding down would have Charter C5's caps computed off an
  understated bill — the breaker would fail *open*. The overstatement this creates (up to 0.999
  cents per call) is stated plainly rather than hidden; the exact micro-USD figure is preserved per
  row for the invoice reconciliation that will true it up.
- **`providers.py`** — `ModelProvider` protocol (§30.1's provider-agnostic interfaces), a
  deterministic zero-priced `MockProvider`, and the paid `AnthropicProvider`. **Charter C14 is
  enforced structurally, not by a runtime check**: no credential is an argument to, a field of, or
  a return value from anything in the module; the key is read from the environment into a local
  that dies with the frame. Plus `redact()`, because an SDK exception message is the realistic way
  a credential reaches a database. `_is_execution_unknown` classifies failures conservatively —
  only a definitely-unbilled rejection (400/401/403/404) releases funds.
- **`gateway.py`** — reserve (USD_REAL, provider-tagged) → reserve (RESOURCE, the A6 metering link)
  → call → settle at *reported* usage → meter input/output tokens → mirror into USD_SIM (§2.4, an
  independent synthetic expense, never a cross-book transfer). Reserve-before-execute is the whole
  point: caps are checked inside the reservation's write lock, so concurrent calls cannot
  collectively exceed a limit each individually respects.
- **`max real spend per provider` (§5.1) is now enforced** — stored-but-unchecked since slice 4,
  the second such "stored but inert" limit to be closed (after `max_lineage_population_fraction`;
  `max_parallel_experiments` and `max_births_per_epoch` are still stored and unchecked).
  Reservations gained a `provider` column so the check is atomic with the reservation insert.
- **Five bugs, none of which broke a kernel invariant — conservation and the hash chain stayed
  green through all of them. Three were found by hand-verification before any test ran, one by a
  test written afterwards, one by `/critique` after the slice was first reported done:**
  1. *(hand)* **Over-reservations were stranded in `committed` forever.** The gateway reserves a
     worst case and settles for less; nothing released the difference. Every call quietly drained
     the Cell's spendable cash *and* ratcheted the C5 concurrent-reserved cap tighter, until the
     colony could no longer call at all.
  2. *(hand)* **Output-token metering was silently dropped** by subtracting the running total
     twice, so A6's completeness invariant had a hole exactly where the cheapest models are.
  3. *(hand)* A zero-priced model produced a misleading "mirror rounds to zero" reason.
  4. *(test)* **Cost overruns were invisible to both the global and per-provider spend windows** —
     the serious one, and the one hand-verification missed. `test_per_provider_cap_counts_settled_
     spend_too` asserted an exposure of 8 and got 6. An overrun is real money leaving the colony
     but is *not* a reservation settlement, and every breaker query filtered on
     `reservation_settle`, so the breaker went blind precisely when a provider billed above
     estimate.
  5. *(critique)* **Cost and metering priced off different models.** The USD_REAL charge used the
     provider's `resolved_model` while the RESOURCE shadow price used the requested one, so a
     substituted model (§24.2) made the two books disagree about the same call. Both now use one
     resolved `billed_model`.
- **ADR-021** covers the overrun decision itself: `settle` refuses to exceed its reservation (that
  refusal *is* C4), but the provider has already billed. Clamping and recording nothing further
  would make the ledger understate real spend and compound silently in the dangerous direction, so
  the shortfall is posted directly with a loud audit event. C4 governs *authorisation*, which the
  reservation enforced at the only moment it could change the outcome; recording an incurred charge
  is accounting. This can drive a Cell's cash negative — deliberately, since an overdrawn Cell then
  fails every subsequent balance check and stops.
- **Charter C14 gained its first test** (`charter_no_secret_in_cell`, previously P4-and-untested):
  the Cell-facing request type cannot carry a credential, a canary key planted in the environment
  and leaked through a provider exception never appears in *any* column of *any* table, and no
  kernel module outside `providers.py` mentions a credential at all.
- **CLI:** new `fund-cell` (pulled into scope, not gold-plating — a calling Cell needs balances in
  three books and there was no way to fund the second and third) and `call-model`, which requires
  `--yes-spend-real-money` for any paid provider. A required flag rather than a prompt, so it
  survives being scripted.
- **Golden run extended** through a reviewed A12 migration (expectation version 1 → 2), with a new
  `model_calls` snapshot section. Diff reviewed line by line: every change attributable to the new
  step, no USD_REAL movement at all (the mock provider is priced at zero — a replay that could bill
  someone is not a replay), funding transactions netting exactly, and the 1-cent floor reservation
  settling 0 then releasing. Latency and response hash are excluded from the snapshot for the same
  reason timestamps are.
- **356 tests passing** (82 new, 0 removed; up from 274). New `tests/test_pricing.py` (15),
  `tests/test_providers.py` (23), `tests/test_gateway.py` (30); `test_cli.py` +9, `test_golden.py`
  +2, `test_charter_properties.py` +3 (C14). Note CI reports **355 passed + 1 skipped**: it
  installs `.[dev]` only, so the one test that needs the `anthropic` package is skipped there.
- `anthropic` is an **optional** dependency (`pip install 'mitosis[anthropic]'`). The kernel, the
  full suite, and the golden run all run without it — §30.1's "mock before paid APIs".
- **No real money has actually been spent yet.** The paid path is wired, unit-tested against a
  stub, and gated, but no live call has been made: that needs an `ANTHROPIC_API_KEY` and a
  deliberate run. That is the top item in PRIORITIES `Next`.
- **Known gap, not deferred by choice — found in self-review after the slice was reported done:
  the success path is not crash-atomic.** `_handle_success` performs roughly six independent
  write transactions (settle real, optional overrun, up to two `record_usage` rows, settle
  resource, mirror, final `UPDATE model_calls`). Each is individually atomic, but a crash
  *between* them leaves the `model_calls` row in `'reserved'` with money already partly moved,
  and `sweeper.py` has no knowledge of `model_calls` at all — so there is no recovery path and
  no operator verb to resolve one. Charter C7 covers exactly this boundary for a single
  reservation and is tested (`charter_crash_recovery`); the gateway's *composition* of several
  reservations is not covered by that test or any other. This is the largest correctness gap in
  the slice and should be closed before sustained real spend, not after.
- Also inaccurate as first written, now corrected: `_REAL_SPEND_TRANSACTION_TYPES` is **not** a
  single source of truth. `_settled_spend_for_provider_since` still hardcodes both transaction
  types in its own two SQL queries, so a third real-spend type added to the tuple would be counted
  by the global caps and silently missed by the per-provider cap. Logged in FUTURE_BUILD_HOOKS.
- Deliberately out of scope, and recorded in `gateway.py`'s docstring as well as PRIORITIES:
  routing by task type (§24.3), controlled retries (a retry after `execution_unknown` risks
  double-billing and needs reconciliation to decide safely), structured-output validation, model
  competition, and reacting to provider drift as a §8.4 regime change — drift is *recorded*
  (`resolved_model`/`api_version`) but nothing consumes it. `reconciled_micro_usd` (§24.1) is
  always NULL: there is no provider invoice to reconcile against.
- Committed as `ef6cb06` and pushed — as one arc together with the two entries it belongs
  with (Phase 4 gateway, crash atomicity, provider-invoice reconciliation), since the three
  interleave across the same files and no intermediate state was separately verifiable.
- Next: close the crash-atomicity gap above (the largest known correctness hole), then either make
  the first real paid call (small cap, one prompt) or close the reconciliation gap that both the
  ADR-020 rounding overstatement and `execution_unknown` resolution depend on.

---

## 2026-07-28 — Gateway crash atomicity: one paid call, one transaction

Closes the "known gap, not deferred by choice" the entry below ends on — the largest correctness
hole in the Phase 4 slice, and the thing that entry says to fix *before* sustained real spend
rather than after.

- **The gap, precisely.** `_handle_success` was ~6 independent write transactions (settle real,
  optional overrun, up to two `record_usage` rows, settle resource, mirror, final `UPDATE
  model_calls`). Each was individually crash-atomic — that is Charter C7, and it is tested. But one
  paid call is not one reservation, and a crash *between* two of those six left real money spent
  against a call still recorded as `'reserved'`, with nothing able to say which steps had run.
  `sweeper.py` had no knowledge of `model_calls`, so there was no recovery path and no operator
  verb. `_handle_failure` had the same shape in miniature (3 transactions).
- **What makes it the dangerous kind of bug: every existing invariant stays green in that state.**
  A settled reservation whose call row was never updated balances perfectly — conservation holds,
  the hash chain validates, A6 linkage is intact. Nothing in the kernel would ever have reported
  it. This is the third distinct instance of the same lesson (after the C4 reservation-vs-cash gap
  and the cost-overrun blindness): the invariants catch violations of rules someone wrote down,
  never the absence of a rule.
- **Fix (ADR-022).** `_handle_success` and `_handle_failure` each hold one `BEGIN IMMEDIATE` and
  compose new `_*_locked` cores — `reservations._settle_locked`/`_release_locked`/
  `_bare_status_transition_locked`, `resource_metering._record_usage_locked`,
  `ledger._post_transaction_locked`. This is not a new pattern: `ledger._write_transaction` and
  `audit.record` were already exactly this split, which is what made the change small. Steps 1–3
  (reserve USD_REAL, reserve RESOURCE, insert the row) stay *outside* the transaction deliberately
  — they must be durably committed before the external call, or reserve-before-execute means
  nothing.
- **Recovery, without inverting the dependency.** `sweeper.py` still does not import `gateway` and
  still does not know what a model call is; its `ExternalOperationChecker` protocol was built for
  exactly this and had only ever had the Phase 1 "answer UNKNOWN to everything" implementation. The
  gateway now supplies `GatewayOperationChecker` (USD_REAL -> UNKNOWN, because the request may have
  been billed and nothing local can tell; RESOURCE -> released, because no provider can bill an
  internal shadow price — but HAPPENED, settled at what was metered, if usage rows exist, so A6 is
  never violated by discarding them) and `resolve_stranded_calls` for its own rows. New `mitosis
  sweep` verb runs both in dependency order and prints a standing warning while any reservation
  sits in `execution_unknown`.
- **What the fix deliberately does not do, and why it's the right call anyway.** A rollback also
  discards the provider's response — the one thing a crash cannot reconstruct. So a crashed call
  resolves to `execution_unknown` with its money still committed: **honest, but not complete**, and
  it needs a human. The alternative (record the response first under a `settling` status, then let
  recovery finish the settlement from real usage figures) is strictly more capable and was
  deferred, not rejected — it needs a new status, a migration and a second idempotency story, and
  it shares all its plumbing with §24.1 invoice reconciliation. Logged in ADR-022's alternatives,
  the gateway docstring, PRIORITIES `Next`, and FUTURE_BUILD_HOOKS.
- **Hand-verification did its job again, and this time also proved the tests aren't vacuous.**
  A file-backed colony, a priced call, and a genuine crash at three points inside the transaction
  — the injected failure derives from `BaseException` so the module's own `except Exception:
  ROLLBACK` never runs, then the connection closes with the transaction open and SQLite rolls it
  back on reopen exactly as it would after process death. All three came back to the pre-call
  state. Then the counterfactual: re-emulating the old separate-transaction shape reproduced the
  original bug exactly (3 cents in `external_expense`, reservation `settled`, call still
  `'reserved'`) **with conservation and the hash chain green throughout**, confirming both the
  diagnosis and that the new assertions have teeth. Repeated against the test suite: 4 of the 5
  new crash tests fail against the pre-fix shape, and the 5th fails against a pre-fix
  `_handle_failure`.
- **368 tests passing** (12 new, 0 removed; up from 356). `test_gateway.py` +9 (3 parametrized
  crash points, the sweep-to-`execution_unknown` path, the stranded-status mapping, the
  don't-touch-an-in-flight-call guard, both checker behaviours, and failure-path atomicity),
  `test_cli.py` +3. Both new C7 tests are `pytest -k charter_crash_recovery`-collectible alongside
  the existing reservation machine, per SPEC.md §0.1.
- **Golden-run hash unchanged** (expectation version still 2, no A12 migration). Correct and worth
  stating: a pure atomicity change alters no economic outcome on a path that never crashes, so a
  changed hash here would have meant an accidental behaviour change.
- Also corrected while adjacent: ADR-021's closing claim that
  `_REAL_SPEND_TRANSACTION_TYPES` "is now the single list" — it isn't, as
  FUTURE_BUILD_HOOKS already recorded and the gateway entry below already flagged. The ADR now says
  so instead of contradicting them.
- **New hazard introduced, stated plainly:** the `_*_locked` cores perform no BEGIN and no COMMIT.
  Called outside a transaction, SQLite autocommits each statement and the atomicity this slice
  bought is silently gone — with no test failure, because every invariant still holds. They are
  underscore-private and each says so in its docstring, but that is a convention, not an
  enforcement; a `conn.in_transaction` assertion or a lint rule is logged in FUTURE_BUILD_HOOKS.
- Committed as `ef6cb06` and pushed — as one arc together with the two entries it belongs
  with (Phase 4 gateway, crash atomicity, provider-invoice reconciliation), since the three
  interleave across the same files and no intermediate state was separately verifiable.
- Next: the first real paid call (small cap, one prompt), or §24.1 reconciliation — which now
  carries the deferred forward-recovery work as well.

---

## 2026-07-28 — Provider-invoice reconciliation: the number the kernel cannot compute

ADR-022 taught crash recovery to park a call in `execution_unknown` with its money committed, and
then nothing in the kernel could resolve one. This closes that loop, and with it §24.1's
`reconciled cost` — the last always-NULL field in the gateway schema.

- **`reconciliation.py` + migration 0011.** Two paths, chosen by the state of the call's USD_REAL
  reservation. Funds still committed (`reserved`/`execution_unknown`/`disputed`) are resolved
  through §4.4's FSM — settle at the invoiced amount, release the remainder, or release outright
  when the invoice shows no charge. Funds already moved are corrected by posting a **new**
  transaction, because §3.6 is explicit that reconciliation never edits history. Both paths end the
  same way: `reconciled_micro_usd`, `reconciled_at_utc`, `reconciliation_source`, an audit event,
  all in one transaction using ADR-022's `_*_locked` cores — which earned their keep one slice
  after being introduced.
- **Releasing an `execution_unknown` reservation happens here and only here.** Charter C7 forbids
  *auto*-releasing an unknown external operation; a release that is the *outcome of
  reconciliation* is the process C7 defers to, not an exception to it.
- **Reconciling does not change a call's `status`** — a reconciled `execution_unknown` call stays
  `execution_unknown`, and `reconciled_at_utc` marks it resolved. Promoting it to `succeeded` would
  invent a response the kernel never saw: we learned what the call cost, not what it returned.
  Same authorisation-versus-accounting split as ADR-021, and it avoids a status migration.
- **The `_REAL_SPEND_TRANSACTION_TYPES` footgun had to be fixed to land this, and the reason is
  worse than the one logged.** The logged risk was that a third real-spend type would be counted
  globally and missed per-provider, because `_settled_spend_for_provider_since` hardcoded its own
  copy in SQL. True, and now fixed — both queries read the tuple. But the adjustment is also the
  first real-spend type that can be **negative**, and *both* breaker queries selected the spend leg
  with `e.amount_minor_units > 0`. On a credit the positive leg is the refund landing in the Cell's
  own cash — so a refund would have been counted as fresh spend, and **paying a Cell back would
  have pushed it toward the circuit breaker instead of away from it.** Both queries now sum the
  signed `external_expense` leg. Hand-verified with the counterfactual: the old filter reports 6
  where the true net is 2.
- **Two bugs found by hand-verification, before any test existed. Neither was a coding slip:**
  1. **A §4.4 violation.** The FSM gives `disputed` a deliberately narrower exit than
     `execution_unknown` — `settled | released`, with no `partially_settled`. Reconciling a
     disputed call at less than its full hold tried to settle partially and hit
     `InvalidTransitionError`. The fix is release-plus-adjustment, which is both what §3.6
     prescribes and how a disputed charge resolves commercially. Widening the FSM was rejected: it
     contradicts a normative spec section.
  2. **My own docstring overclaiming.** The slice was motivated partly by ADR-020's rounding
     overstatement, and I wrote that reconciliation hands it back. It does not, and cannot: 3.5
     cents of true cost converts through the same `micro_usd_to_minor_units` ceiling to the 4 cents
     already recorded, so the adjustment is zero. The overstatement is sub-minor-unit by
     construction and only becomes correctable in aggregate. Corrected in three docstrings, pinned
     as `test_sub_cent_rounding_is_not_correctable_per_call`, and logged as the aggregate-invoice
     work that would actually close it. **What this slice fixes is estimate error and unknown
     outcomes, not rounding.**
- **A third finding, deliberately not fixed:** `ledger.spend_by_book` has the same sign trap — a
  credit's negative `external_expense` leg is dropped by its `amount > 0` filter, so a refund never
  reduces a Cell's recorded spend. Removing the filter is *not* the fix, because birth funding's
  negative leg carries the same cell_id and a freshly-funded Cell would read as having spent a
  negative amount. Separating them needs an account-level distinction between funding sources and
  spend destinations that §31's account list does not draw — a modelling decision, not a patch, and
  not one to make inside a reconciliation slice. Documented in the function, FUTURE_BUILD_HOOKS and
  PRIORITIES. Bounded: coroner reports only, never an enforcement check.
- **CLI:** `reconcile` (dollar string parsed at micro-USD precision via new
  `pricing.parse_micro_usd` — cents are too coarse for an invoice line, and rounding the operator's
  own evidence before it reaches the ledger would defeat the point), `dispute`, and `outstanding`,
  which orders frozen money first. Hand-verification also caught two display bugs an operator would
  have hit immediately: `outstanding` reported a *released* reservation's returned funds as still
  frozen, and a crashed call printed `estimated: None micro-USD`.
- **405 tests passing** (37 new, 0 removed; up from 368). New `tests/test_reconciliation.py` (32),
  `test_cli.py` +5. Teeth-checked by reverting each fix in turn: the disputed-path test and the
  credit-does-not-inflate-spend test both fail against the pre-fix code.
- **Golden run extended** through a reviewed A12 migration (expectation version 2 → 3). The
  scenario reconciles its mock call against a zero invoice, which is the honest figure for a
  zero-priced provider. Diff reviewed section by section: only `audit_event_types` (+1) and
  `model_calls` (+3 fields) changed — `balances`, `transaction_types` and `reservations` are all
  identical, which is the evidence that no money moved. The adjustment paths, where the sign
  matters, are covered by unit tests rather than the golden run *on purpose*: pinning them would
  mean giving up the property that a golden replay never moves USD_REAL.
- **Migration upgrade path hand-verified** against a genuine pre-0011 colony left over from the
  previous slice (the test suite cannot see this — every test builds a fresh DB): columns land
  NULL rather than garbage, and the pre-existing call correctly reads as outstanding.
- Committed as `ef6cb06` and pushed — as one arc together with the two entries it belongs
  with (Phase 4 gateway, crash atomicity, provider-invoice reconciliation), since the three
  interleave across the same files and no intermediate state was separately verifiable.
- Next: the first real paid call, or aggregate-invoice reconciliation.

---

## 2026-07-30 — Real-spend type registration: replacing the reviewer

`_REAL_SPEND_TRANSACTION_TYPES` is the list both the hour/day/month caps and the per-provider cap
read. A USD_REAL type that posts to `external_expense` but is missing from it is real money the
breaker cannot see, so the caps fail **open** — the one direction that matters. Membership was a
convention enforced by a reviewer noticing, and it was missed twice inside a single arc:
`model_call_cost_overrun` shipped unregistered, and `model_call_reconciliation_adjustment` arrived as
the first type whose amount can be negative, which both queries mishandled. This replaces the
reviewer.

- **Three angles, because no one of them is sufficient.** (1) An **AST walk** over `src/mitosis`
  requiring every `transaction_type=` to be either registered or exempted *with a stated reason* —
  the only angle that fires on a genuinely new type, whatever that type does. (2) A **precise static
  check** that any call site naming `external_expense` uses a registered type — this is the one that
  would have caught the cost overrun, and it fails pointing at `gateway.py:569`. (3) A **behavioural
  check**, parametrized over the registry itself, that each registered type is actually summed by
  *both* spend windows.
- **The behavioural angle exists because the static one structurally cannot cover the main path.**
  `reservation_settle` takes its destination account from the reservation record at runtime, so
  `external_expense` never appears at its call site. The kernel's single largest real-spend path is
  invisible to a source-level check, and only a test that moves money can confirm the breaker sees
  it.
- **A subtlety I had assumed away, caught by the test failing on first run.**
  `model_call_sim_mirror` also posts to `external_expense` — `external_expense` is an account name,
  not a book, and the §2.4 mirror debits the same account in `Book.USD_SIM`. So the static check has
  to resolve the **book** as well as the account, treating a dynamic `book=book` as possibly-real and
  only excluding a statically-provable `Book.USD_SIM`. The exclusion is then asserted explicitly
  (`test_sim_book_postings_to_external_expense_are_excluded_deliberately`) rather than left implicit,
  because misfiling a real-spend type as USD_SIM is precisely how one would hide from the check.
- **Pinned an undocumented coupling that would have bitten the next person to register a type.** The
  per-provider query finds a direct posting by joining `model_calls` on
  `transaction_type || ':' || model_call_id`. A newly-registered type with any other idempotency-key
  shape is counted globally and silently missed per-provider — the *exact* asymmetry the gateway
  slice logged and the reconciliation slice fixed, reintroducible for free. Registration in the
  tuple is necessary but not sufficient, and the test now says so in its failure message.
- **Exemption reasons were verified against each call site's book and entry accounts, not inferred
  from the name.** `colony_seed_capital` is the one that would have caught me out: it is
  USD_REAL-capable and touches an account called `external_capital`, which is a different account
  from `external_expense` and flows the opposite way (capital entering the colony).
- **Teeth-checked by reintroducing each bug in turn**, per the practice that has now caught something
  in every slice: unregistering `model_call_cost_overrun` fails 2 tests and names its call site;
  introducing a novel unclassified type fails classification (and *also* trips the stale-exemption
  check, which is the cross-check working); breaking the idempotency-key convention fails the
  per-provider assertion for both direct types. Each mutation was reverted and the tree confirmed
  clean.
- **Guard against the tests going vacuous**, since a static walk that finds nothing passes forever: a
  floor on discovered call sites, an assertion that at least one site names `external_expense`, and
  stale-entry checks in both directions (an exemption for a type no longer in the kernel, a
  registered type no call site posts — the latter catches a typo in the tuple).
- **412 tests passing** (7 new, 0 removed; up from 405). Golden-run hash unchanged, which is correct
  for a test-only change — a changed hash would have meant an accidental behaviour change. All five
  new C5-relevant tests are `pytest -k charter_realspend_cap`-collectible alongside the existing
  property test (6 collected), per SPEC.md §0.1; `test_charter_properties.py`'s ID map now
  cross-references them.
- **The registry comment in `real_spend_breaker.py` now points at its own enforcement**, so the next
  person to add a type reads both the requirement and the idempotency-key constraint at the point of
  change rather than discovering them from a breaker query.
- **What this deliberately is not: a runtime guard.** The airtight version is a check where the
  transaction is written — if `book` is USD_REAL and any entry hits `external_expense`, require a
  registered type — which no novel code shape can bypass. Not built here because the registry lives
  in `real_spend_breaker` while the check belongs in `ledger` (the tuple needs moving to a neutral
  module first), and because raising there fails a legitimate-but-unregistered transaction closed in
  production. For real money that is arguably the *right* direction, so it is logged in
  FUTURE_BUILD_HOOKS as worth revisiting before sustained real spend rather than dismissed.
- Committed as `1518677` and pushed.
- Next: the first real paid call, which now needs only an `ANTHROPIC_API_KEY` and a deliberate
  `--yes-spend-real-money` run against a tiny cap.

---

## 2026-08-05 — The first real paid call: one cent, and what it measured

MITOSIS has spent real money. `claude-haiku-4-5` (resolved
`claude-haiku-4-5-20251001`), 12 input tokens, 4 output tokens, 32 micro-USD of true cost, **1 cent
recorded in USD_REAL**. The model replied `ok`. Every number below was verified against the ledger
rather than read off the CLI's own summary.

- **The call was set up to be boring on purpose.** A dedicated `first-real-call.db` capped at 5¢ per
  request and $1.00 per month, one explorer Cell funded in all three books, and a free `MockProvider`
  dry run on the same colony first — so the only untested variable when real money moved was the live
  API itself.
- **Cost math reconciles exactly.** 12 input × $1/Mtok = 12 μ$, 4 output × $5/Mtok = 20 μ$, total 32
  μ$ — matching `cost_actual_micro_usd` and both `resource_usage` rows independently. One
  `reservation_settle` entry of 1 minor unit on `external_expense`, and it is the *only* USD_REAL
  entry on that account in the whole colony. Cell cash 20¢ → 19¢. Conservation OK in all three books,
  hash chain valid, A6 linkage complete, `committed` zero everywhere.
- **ADR-020's overstatement, measured rather than argued: 312×.** True cost 0.0032¢, recorded 1¢. The
  ceiling is correct — rounding down would have Charter C5's caps computing off an understated bill —
  but at this size the ledger is recording the *floor of a cent*, not the cost. This is the sharpest
  possible argument for aggregate-invoice reconciliation, which is the only thing that can recover
  it, and it is now a number instead of a prediction.
- **The estimate over-reserved by 10.8×** (347 μ$ held against 32 μ$ actual), because it reserves the
  full `max_tokens` output. Harmless to the ledger — the remainder released cleanly — but with a 5¢
  per-request cap it is the *estimate*, not the real cost, that decides whether a call is permitted.
- **And it under-counts input, which is the opposite of what was assumed.** `_estimate_tokens` uses 2
  chars/token and predicted 11 where the API's own `count_tokens` returned 12. It is documented as a
  deliberate over-estimate; for short prompts it is not, because the heuristic ignores per-message
  structural overhead. The backlog item to tighten it should be rewritten: input needs a *floor*,
  output needs a tighter ceiling.
- **Two failure paths ran for real before the successful one, and both behaved.** A RESOURCE
  under-funding tripped Charter C4 (`cannot reserve 347`, C4 refusing before any money moved), and an
  invalid key produced a 401 that `_is_execution_unknown` classified as definitely-unbilled — so
  funds were *released* rather than frozen in `execution_unknown`. Verified afterwards: across five
  failed attempts, every USD_REAL reservation reached `released`, `committed` was 0, and no
  transaction touched `external_expense`. The release-on-failure path that the gateway slice's bug #1
  was about had never run outside a test until now.
- **Model drift was recorded and nothing consumed it**, exactly as documented: requested
  `claude-haiku-4-5`, resolved `claude-haiku-4-5-20251001`. §24.2 captured it; reacting to it as a
  §8.4 regime change remains unimplemented.
- **Also fixed, spotted while verifying: `outstanding` counted zero-cost calls as billable work.**
  The mock provider is priced at 0, so it produces calls no invoice will ever list, and both
  `outstanding` and `summary` counted them — noise that grows without bound as mock calls accumulate.
  Both now share one `_BILLABLE_PREDICATE` (already moved real money, recorded a real cost, or still
  holding funds), deliberately kept as a single string so the two queries cannot drift apart — the
  same two-copies-of-one-rule shape that let a third real-spend type be missed by one of two breaker
  queries. It remains a **worklist, not a gate**: `reconcile` still accepts any `model_call_id`, so a
  surprise charge on a nominally free call can still be applied, and that is pinned by its own test.
- **414 tests passing** (2 new, 0 removed; up from 412). `test_outstanding_lists_then_clears` was
  rewritten rather than deleted — it had encoded the old behaviour, and now asserts the new semantics
  plus the worklist-not-a-gate property. Teeth-checked by reverting the predicate: both new tests
  fail against the old shape. Golden-run hash unchanged (expectation version still 3), correct for a
  change that alters no economic outcome.
- **`.gitignore` gained `.env` / `.env.*`.** It had neither, and the credential file needed for a
  paid call sits in the repo root — with `git add -A` in the commit flow, an API key was one command
  away from being pushed to GitHub.
- Committed as `a28b86b` and pushed.
- Next: see PRIORITIES. The honest summary is that the *kernel* is proven and the *colony* does not
  exist yet — nothing in MITOSIS can currently earn a cent, and Phases 2 and 3 remain skipped.

---

## 2026-08-05 — Revenue, and a second provider: the two halves of a fitness signal

Both prerequisites for open-ended, self-directing Cells, built together because neither is useful
alone. **Money can now enter the colony**, so profitability is a number rather than an aspiration;
and **inference can now be free**, so a Cell can think without every thought hitting Charter C5's
caps. Nothing here makes a Cell autonomous — that is still the missing subsystem — but it is what
autonomy would need underneath it.

### Revenue (`revenue.py`, SPEC.md §31, §2.2)

- **The `revenue` account existed in §31's fixed-account list and nothing ever posted to it.** A
  Cell's profitability was therefore not merely unmeasured but *unmeasurable* — the number had
  nowhere to live. `record_revenue` gives it one, mirroring spend exactly: a spend debits the Cell
  and credits `external_expense`; revenue debits `revenue` and credits the Cell's cash. The
  `revenue` account accumulates gross earnings negated, the same convention `external_capital`
  already uses, so conservation per book (Charter C2) is unchanged.
- **Revenue is not spend, and the separation is the load-bearing decision.** It never touches
  `external_expense`, so the real-spend breaker cannot see it — deliberately. Charter C5 bounds how
  much the colony may *spend*, not its net position, and a Cell that earns must not thereby earn
  permission to spend past a cap. The one intended coupling is Charter C4: earnings are cash, and a
  Cell may reserve up to its cash. Both halves are pinned by their own tests.
- **The teeth check on that separation produced the clearest possible argument for it.** Mutating
  revenue to post to `external_expense` *and* registering `cell_revenue` as a real-spend type makes
  the hour window read **−10,000 instead of 0** — a Cell would literally earn its way *backwards*
  through the circuit breaker. Each half of that mutation is independently caught by last slice's
  registration guard (the disjointness check for one, the precise static check naming
  `revenue.py:106` for the other), and the breaker test catches the combination. Stated plainly
  because it matters: `test_revenue_does_not_move_the_spend_breaker` **cannot fail on either half
  alone** — it is a backstop, and the registration guard is what actually holds each side.
- **Attribution is mandatory.** `source` is required and refused when blank, the same rule
  reconciliation applies to invoice figures, for the same reason: an unattributable credit to a Cell
  is precisely how a fitness signal gets fabricated, and fitness is what this exists to feed. The
  default idempotency key is derived from the source, so posting the same attributed payment twice
  is refused by the ledger rather than silently doubling a Cell's apparent fitness.
- **A dead Cell can still receive revenue** — payment arrives after the work, sometimes after the
  worker, and a coroner report omitting final earnings would misstate the thing it exists to record.
  Status is not checked; existence is, so revenue cannot be posted to a typo.
- **RESOURCE is refused.** Nobody pays a colony in compute units, and allowing it would let a Cell
  top up its own metering budget by declaring revenue.

### Ollama provider (`providers.OllamaProvider`, SPEC.md §30.1)

- **The second provider, and the one that makes exploration affordable.** A Cell that proposes
  strategies constantly cannot do that against a metered API without the proposal stage dominating
  its budget. Local inference has no per-call marginal cost, so the creative loop can run flat out
  and never touch a cap. Registered in the pricing table at zero.
- **Zero dependencies.** Uses stdlib `urllib` against Ollama's HTTP API rather than an SDK — unlike
  `anthropic`, which is optional precisely because it is heavy. A local model should not cost the
  kernel an install.
- **Charter C14 in its cleanest form: there is no key to leak.** Ollama is unauthenticated on
  localhost, so no credential exists anywhere in the provider's surface — asserted by a test rather
  than assumed. `OLLAMA_HOST` is a URL, not a secret, and is still passed through `redact()` on the
  error path in case it points at an authenticated proxy.
- **Never reports `execution_unknown`, which is a deliberate departure from
  `_is_execution_unknown`'s conservatism.** That default exists because wrongly releasing a
  reservation for a call that *was* billed loses real money silently. A local provider cannot bill:
  its USD_REAL exposure is structurally zero, so freezing funds would park money against an invoice
  that can never exist, and `mitosis outstanding` would ask a human to resolve something no evidence
  could ever resolve. What a timeout does cost is RESOURCE metering accuracy — a shadow-price
  imprecision, not a money risk. Documented on the class and pinned across 400/500/503/timeout.
- **Models are registered explicitly rather than priced zero by wildcard**, and that friction is on
  purpose: an Ollama-compatible endpoint can front a *paid* hosted model, and a wildcard would
  silently price it at zero and blind Charter C5 to real spend. An unknown model fails loudly.
- **A zero price is not a free call.** Local compute is still metered and shadow-priced in the
  RESOURCE book, so a runaway local Cell is still bounded — proven end to end by an integration test
  driving the gateway with a stubbed Ollama: USD_REAL settles at 0 and the breaker stays at 0, while
  the provider's *reported* token counts (17 in / 5 out) are metered, not estimates.
- **Ollama names everything differently** (`num_predict`, `prompt_eval_count`, `eval_count`), and
  getting that mapping wrong corrupts A6 metering silently rather than failing. Each is pinned;
  dropping `num_predict` would let a local call generate past its metered budget.
- Missing usage counters (Ollama omits `prompt_eval_count` on a fully cached prompt) meter as zero
  rather than crashing — zero recorded tokens is true, and a crash would strand the reservation.

### Verification

- **448 tests passing** (34 new, 0 removed; up from 414). New `tests/test_revenue.py` (13),
  `tests/test_ollama_provider.py` (16), `test_cli.py` +5. Golden-run hash unchanged.
- **Last slice's registration guard fired on the very next slice, as designed.** `cell_revenue` was
  refused as unclassified until it was explicitly exempted with a stated reason — the convention it
  replaced would have let a new money-moving type through on a reviewer's attention.
- **Hand-verified on the live colony** that made the real paid call: recorded 75¢ of revenue against
  the Cell that had spent 1¢. Cash 19 → 94, `revenue` account −75, conservation and hash chain green,
  breaker unmoved at 1/25, and re-posting the same `source` returned the *same* transaction id with
  no double-count. **Net position: +74 minor units — the first profit figure MITOSIS has ever been
  able to compute.**
- One verification bug worth recording because it nearly became a false alarm: a shell-interpolated
  account id in my own check string was mangled (`…986ash`), so `get_balance` was asked about a
  nonexistent account and returned 0, making it look as though the balance had not moved. The code
  was correct; the check was not. Identifiers in hand-verification scripts should come from the
  database, not from shell interpolation.
- Committed as `945ef04` and pushed.
- Next: fitness (revenue − spend) is now computable, but `ledger.spend_by_book`'s sign bug becomes
  load-bearing the moment selection reads it — a credited Cell currently reads as having spent more
  than it did. That fix needs §31's account-level split between funding sources and spend
  destinations, and it should land *before* anything selects on profit. See PRIORITIES.

---

## 2026-08-05 — `spend_by_book`: the account-level distinction §31 never drew

Logged since the gateway slice as "coroner reports only, never enforcement" — which stopped being
true the moment revenue landed, because fitness is `revenue − spend` and selection would read it.
Fixed before anything selects on profit, which was the whole point of doing it now: a wrong spend
figure does not fail loudly, it kills the wrong Cells and compounds down every generation.

- **The known bug.** A reconciliation credit debits `external_expense` with a *negative* amount, and
  the old query filtered `amount_minor_units > 0`, so a refunded Cell kept its full recorded spend
  forever. The reason it could not be fixed by deleting the filter is the other half: birth
  funding's negative leg carries the same `cell_id`, so an unscoped signed sum makes a
  freshly-funded Cell read as having spent a *negative* amount. **Neither half is fixable alone** —
  the sign only becomes meaningful once the account is known.
- **The fix: classify the account, then trust the sign.** `accounts.py` now carries
  `SPEND_DESTINATIONS` and `CAPITAL_ACCOUNTS`, each entry with its reason, and `spend_by_book` is
  the **signed** sum of a Cell's entries landing on a spend destination. A credit reduces it; a
  capital movement never enters it.
- **The distinction is consumption versus capital movement — not internal versus external, which
  is where I started and would have been badly wrong.** Settling metered compute into
  `infrastructure_reserve` never leaves the colony but is unambiguous cost to the Cell. I only
  caught this because the golden run settles there and hand-verification then showed **the gateway
  settles every RESOURCE metering there too** (`gateway.py:372`, `:730`). Under the
  internal/external framing, *every Cell's entire compute consumption would have silently vanished
  from `spend_by_book`* — and with Ollama making USD_REAL free, the RESOURCE book is now the only
  thing bounding a local Cell, so the hole would have opened exactly where the next work is headed.
- **A second overstatement, found by the teeth check and not previously named.** Faithfully
  restoring the original query makes the consumption test read **1600 instead of 700**: the old
  code counted a `colony_treasury` capital return as spend. So it overstated on two independent
  paths — credits never subtracted, and capital returns wrongly added. Only the first was logged.
- **A completeness guard, in the shape that has now paid off twice.** `unclassified_accounts()`
  plus a test means adding an account to §31's list forces a spend-or-capital decision instead of
  silently defaulting to "not spend". Same lesson as the real-spend type registry: the invariants
  catch violations of rules someone wrote down, never the absence of a rule.
- **The golden run does not protect this, and the teeth check proved it.** Misclassifying
  `infrastructure_reserve` makes spend read `{}` instead of `700` while `verify-golden-run` still
  passes — the golden scenario's coroner'd Cell only ever spends to `external_expense`. The unit
  tests are the only cover, which is worth knowing before trusting the golden run as a backstop for
  accounting-shape changes.
- **453 tests passing** (5 new, 0 removed; up from 448). Golden-run hash unchanged — correct and
  meaningful here: the fix is identical to the old code everywhere the old code was right, and
  differs only in the cases that were broken. A changed hash would have meant an accidental
  behaviour change.
- **Teeth-checked three ways:** the faithful original query fails the credit test (300 vs 200) and
  the consumption test (1600 vs 700); the naive fix (drop the sign filter, keep the old scoping)
  makes a funded Cell read **−1000**; and misclassifying an account fails the consumption test.
- **Hand-verified on the live colony** that made the real paid call: `spend_by_book` reads
  `{RESOURCE: 34, USD_REAL: 1, USD_SIM: 1}` against 75 earned — fitness **+74**. Posting a 1¢
  reconciliation credit moves USD_REAL spend `1 → 0`, where the old code would have held it at 1.
  Conservation and hash chain green throughout. (That credit is left in `first-real-call.db`, which
  is a gitignored scratch colony.)
- Committed as `dd4d215` and pushed.
- Next: fitness is now a trustworthy number, so the prediction register (a Cell states expected
  earnings *before* spending) is the cheapest real selection pressure available and needs no
  customer. Then §10.5 death criteria, which closes the evolutionary loop since reproduction
  already works. The agent loop remains the missing subsystem.

---

## 2026-08-05 — Prediction register: selection pressure without a customer

Amendment A14 / §8.5, normative since the v0.2 spec and unbuilt until now. **The reason to build it
before an agent loop exists:** selection needs a fitness signal, revenue needs a customer, and there
isn't one — but calibration needs neither. A Cell that predicts its own outcomes badly is
demonstrably worse than one that predicts them well, whatever it is doing and whether or not anyone
pays for it. This is the cheapest real selection pressure available, and it can start
discriminating between Cells on day one.

- **`prediction.py` + migration 0012 (`prediction_register`, §31).** Register before the outcome is
  known, resolve once, score with both rules §8.5 names — Brier `(p−o)²` and log `−ln(p_actual)`.
  `calibration()` returns §8.5's curve; `scores()` the means.
- **Binary claims, because the spec named the rules.** Brier and log are defined over binary
  outcomes, so a continuous quantity is predicted by stating a threshold — "revenue >= 50 minor
  units" — not a point estimate. This is the spec's constraint, not an implementation shortcut, and
  worth being explicit about: **a point revenue estimate cannot be scored by either named rule.**
  Doing that properly needs CRPS or an interval rule, which §8.5 does not authorise, so it is logged
  rather than invented.
- **Certainty is refused.** `probability` must be strictly inside (0, 1), enforced in Python *and*
  by a schema CHECK. The reason is not fastidiousness: the log score of a confident-and-wrong
  prediction is infinite, one such prediction would pin a Cell's mean at −inf permanently, and **a
  population containing several infinitely-bad Cells cannot be ordered — so it cannot be selected
  on.** `log_score` also clamps, so a row that somehow escaped the CHECK scores very badly rather
  than uncomparably.
- **Hash-chained, like the ledger, for the same reason.** A per-row hash proves nothing against an
  editor who recomputes it; chaining means altering any prediction invalidates every prediction
  after it. That is what turns "register-before-outcome" from a convention into something
  `verify_chain` can check. **The hash covers the prediction and never the outcome** — including the
  outcome would defeat its only purpose, and would also make recording what happened look like
  tampering (pinned by `test_resolving_does_not_break_the_chain`).
- **The anti-gaming surface, which is the part that decides whether any of this means anything.** A
  Cell that resolves only its winners has a beautiful calibration curve and a pile of unresolved
  losers behind it. `overdue()` lists predictions past their own deadline, `scores()` reports
  `unresolved` and `overdue` *beside* the means rather than quietly omitting them, and the CLI
  prints an explicit warning that the scores are self-selected and unreliable while any are
  outstanding. Nothing here *forces* resolution — that is a policy question for whatever drives
  selection — but the omission is now impossible to miss.
- **Calibration is returned as buckets, not one number, because the shape is the diagnosis.**
  Systematic overconfidence and systematic underconfidence can produce the *same* mean Brier score
  and call for opposite corrections. `test_calibration_curve_separates_confidence_from_accuracy`
  pins exactly that case: ten claims at p=0.9 that come true half the time.
- **CLI:** `predict`, `resolve-prediction` (mutually exclusive `--occurred` / `--did-not-occur`, so
  an outcome cannot be omitted by accident), and `calibration`, which prints the curve, the scores,
  the overdue warning, and the chain-validity check.
- **481 tests passing** (28 new, 0 removed; up from 453). New `tests/test_prediction.py` (25),
  `test_cli.py` +3.
- **Golden run extended through a reviewed A12 migration** (expectation version 3 → 4): three
  predictions — one resolved true, one resolved false, one left deliberately open so `unresolved`
  appears in the snapshot and a future change cannot silently drop the anti-gaming surface. Diff
  reviewed section by section: only `predictions` and two new `audit_event_types` changed, while
  `balances`, `transaction_types`, `reservations`, `cells`, `resource_usage`, `model_calls` and
  `coroner_reports` are **absent from the diff entirely** — the evidence that predictions move no
  money. Scores were re-derived by hand against the snapshot: `(0.8−1)² = 0.04`, `−ln(0.8) =
  0.223144`, `(0.6−0)² = 0.36`, `−ln(0.4) = 0.916291`. Float scores are rounded to six places in the
  snapshot so a last-place difference across platforms cannot break replay for a reason unrelated
  to behaviour.
- **Teeth-checked three ways:** making the hash cover the outcome fails three chain tests including
  the resolve-is-not-tampering one; removing the chaining check fails the tamper test; allowing
  certainty fails at the schema CHECK — which incidentally proved the two guards are independent,
  since the test then fails on the wrong exception type.
- **Hand-verified on the live colony** that made the real paid call. Migration 0012 applied cleanly
  to a genuine pre-0012 database. Two predictions registered and resolved (0.85→occurred, Brier
  0.0225; 0.3→did not occur, Brier 0.09; mean 0.0563 ✓). Then the property that matters: editing a
  resolved prediction's probability directly in SQL made `verify_chain` return **False**, and
  reverting it returned **True**. Tamper-evidence demonstrated on real data, not only in a test.
- One test bug of my own, worth recording: the overdue CLI test originally set a sub-second deadline
  and raced the wall clock, which had not elapsed by the next command. Rewritten to move the
  deadline into the past — deterministic, faster, and a more honest depiction of what an overdue
  prediction actually is.
- Committed as `312e1d9` and pushed.
- Next: §10.5 death criteria. With calibration and `spend_by_book` both trustworthy and `kill()`
  already built, death is what closes the evolutionary loop — reproduction already works, so a
  colony that can select is a colony that can evolve. The agent loop remains the missing subsystem,
  and nothing here changes that: a Cell still cannot make its own predictions.

## 2026-08-05 — Death criteria: the evolutionary loop closes

Reproduction has worked since the lineage slice. What was missing was any principled reason for a
Cell to stop — so a colony could grow but never select. This is the other half, and with it the
loop is closed: birth, spend, earn, predict, die.

**Reading §10.5 first changed the design substantially, and the spec forbids what "selection on
fitness" would naturally mean.**

- **§10.5: "Estimated negative EV *alone* must not kill a Cell"** unless evidence is sufficiently
  strong *and* an independent Auditor or evaluator concurs. So compute-fitness-and-cull-the-bottom
  — the obvious implementation, and the one the previous three slices might look like they were
  building toward — is exactly what the spec prohibits. An estimate is not evidence, and a colony
  that culls on estimates selects for Cells that look good to the estimator. `reap` therefore kills
  only on realised facts, and negative EV is a separate entry point that structurally cannot be
  reached without a concurring Auditor.
- **§10.2: "Do not collapse all dimensions into one scalar."** So domination is **Pareto**
  domination — at least as good on every measured dimension, strictly better on one — rather than a
  ranking on a weighted sum. A Cell that earns more but predicts worse is *not* dominated. That is
  the constraint doing real work rather than being cited.
- **§10.3: Explorers "need no immediate revenue."** Handled without a special case: comparisons are
  restricted to near-duplicates (same genome hash, which in this kernel is effectively same-type per
  ADR-018/019), so an Explorer is only ever compared with another Explorer.
- **§9.3: "A proposed child's forecast can never trigger a kill."** Every input to `findings` comes
  from the ledger or the resolved prediction register. Nothing forecasts.

### What landed

- **`death.py`.** `DeathCriterion` covers all of §10.5's criteria — including the unimplementable
  ones, so a coroner report's `cause_of_death` uses one vocabulary from the start and the gap is
  visible in the type rather than only in prose. `findings()` returns the criteria a Cell currently
  meets *with the realised evidence*, which reaches the coroner report, so a death always carries
  the numbers that caused it. `reap()` is **dry-run by default**: a death is irreversible, files a
  coroner report, and Charter C8 makes the Cell permanently inert, so the first time a colony can
  end its own Cells is not the moment to discover a criterion was too eager.
- **Two criteria implemented, and the honest list of what is not.** `budget_exhausted` (holds
  nothing, nothing pending) and `dominated_by_near_duplicate` (Pareto, realised). Not implemented:
  `failed_validation_gates` and `evidence_not_reproducible` need experiment tracking (Phase 2);
  `policy_violation` needs §31's `policy_violations` table, and inferring it from a quarantine
  reason would be guessing, since `quarantine` takes free text and is also used for poison events;
  `displacement` is §9.3's own slice — **which this unblocks**, via `is_objectively_failing`, the
  predicate §9.3 was waiting on.
- **`kill_for_negative_ev` is the guarded path**, and its independence checks are its substance: the
  auditor cannot be the subject, must be alive, and must be an auditor or immune Cell (§10.4). The
  concurrence is written to the audit trail and the auditor's id into the coroner report, so a death
  on an estimate can always be traced to who agreed to it.
- **A Cell mid-operation is never exhausted.** Zero cash with funds committed means a call is in
  flight; killing then would strand its reservation.
- **CLI:** `reap` (dry-run unless `--execute`) and `cell-fitness`, which prints revenue, spend, net
  contribution and calibration side by side — deliberately not a score, per §10.2.

### A trap caught while writing it

Domination on net contribution alone makes an **idle** Cell — spent nothing, earned nothing, net
zero — dominate one that invested and has not yet returned. That selects for doing nothing, which in
an evolutionary colony is the failure mode that quietly ends the experiment while every invariant
stays green. Fixed with `_has_realised_record`: a Cell with no realised record is not superior, it
is unmeasured. Pinned by `test_an_idle_cell_does_not_dominate_one_that_invested`, and the teeth
check confirms removing the gate fails it.

### Verification

- **501 tests passing** (20 new, 0 removed; up from 481). Golden-run hash unchanged — correct, since
  the golden scenario contains no Cell meeting an objective criterion and `reap` is never called;
  a changed hash would have meant death criteria firing somewhere they should not.
- **Teeth-checked four ways**, one per constitutional constraint: making negative EV automatic fails
  `test_negative_ev_is_never_reachable_from_reap`; removing the idle gate fails the idle-domination
  test; collapsing calibration out of the comparison (a scalar collapse, §10.2) fails
  `test_domination_requires_being_better_on_every_dimension`; allowing self-concurrence fails the
  own-death test.
- **The most important test is `test_losing_money_is_not_a_death_criterion`.** A Cell that spent 600
  and earned 100 survives, because §10.5 does not make that fatal. Breaking it would cull on
  estimates and nothing would report it — the colony would simply stop exploring.
- **Hand-verified end to end** on a scratch colony: drained a Cell, `reap` reported it without
  killing, `reap --execute` killed it, and the coroner report recorded both the criterion and its
  evidence (`budget_exhausted: {'book': 'USD_SIM', 'cash': 0, 'committed': 0}`) with
  `spend_by_book` reading `{"USD_SIM": 500}` — the function fixed two slices ago now feeding a real
  death. On the live colony, `cell-fitness` reads 75 revenue / 0 spend / mean Brier 0.0563 and
  `reap` correctly finds nothing.
- Committed as `2c876dd` and pushed; CI green.
- Next: §9.3 displacement is now unblocked and is the natural follow-on — a birth denied at capacity
  can evict an objectively-failing Cell rather than simply waiting. Beyond that the agent loop is
  still the missing subsystem, and it is worth being plain that **nothing here selects on its own**:
  `reap` must be called, and no Cell yet acts, predicts, or earns without a human driving it.
