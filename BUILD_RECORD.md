# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–9, 2026-07-21 through 2026-07-25): [docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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
  full every session. Earlier entries moved to
  [docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md); `.claude/commands/prime.md`
  updated to use `git status -sb` (plain `--short` hides the ahead/behind line, which is how a
  4-commits-unpushed branch was previously reported as "clean").
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
