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
