# MITOSIS / Evolution Agents — Build Record Archive

Entries through slice 9 (2026-07-25, golden-run replay), moved out of the top-level
`BUILD_RECORD.md` so that file stays small enough to read in full every session (it had grown to
~42 KB / 9 slices). `BUILD_RECORD.md` keeps only the current/most-recent entry plus a pointer
here; append new slices there, and move an entry here once a newer one supersedes it as "last
landed."

## 2026-08-22 — The estate: a dead Cell stops taking the colony's money with it

`kill()` marked a Cell dead, filed its coroner report, and left its money where it was. Open
reservations stayed open; residual cash sat on an account nothing could ever spend from again.
ADR-028, in `lifecycle.py`.

**The golden run had been losing 3450 USD_SIM per replay since expectation version 1**, and the
expectation diff is the whole bug report: `cell:cell#0:cash` 3450 → 0, `colony_treasury` 300 →
3750. Displacement made this worse by design — evicting Cells to reclaim population slots exactly
when the colony is at capacity — and the scheduler made it compound with nobody watching.

### What the spec gave, given it has no "estate" concept

Charter C8 turned out to be the load-bearing clause, and not for the reason it looks like. "Dead
Cells cannot act" reads as being about behaviour, but **an open reservation *is* standing
authorisation to spend**, whatever the status column says — so a dead Cell holding one is the
plainest possible instance of what C8 forbids. That is why the estate runs inside `_kill_locked`
rather than as a follow-up sweep: a crash between the death and the release must not be able to
leave that state. §9.3 displacement inherits it for free.

`accounts.py` had already decided where the money goes, in a comment written two slices earlier:
returning surplus to `colony_treasury` is "capital going back, not cost incurred". So the estate is
capital movement, not spend — and the real-spend registration guard forced that decision explicitly
rather than letting it pass on a reviewer noticing.

### The tension worth recording

ADR-022 says a reservation with an `external_operation_id` is resolved by finding out what the
provider did, never by assuming — so death must not release it. But refusing to *kill* a Cell with
a call in flight would break displacement and, worse, hand every Cell a survival strategy: keep one
call in flight and never die. So an in-flight operation makes the estate **incomplete, not the
death impossible**, and `mitosis sweep` finishes it once the sweeper has resolved the reservation.

### Verification

- **621 tests passing** (13 new, 0 removed; up from 608).
- **Golden expectation 7 → 8** via a reviewed migration. Exactly four values move, all a single
  transfer: `cell:cell#0:cash` 3450 → 0, `colony_treasury` 300 → 3750, plus one new transaction
  type and one new audit type. USD_SIM conservation unchanged; **no USD_REAL movement**.
- **Teeth-checked eight ways**, each failing its named test: not reclaiming cash at all, leaving
  reservations open, releasing an in-flight external operation, sweeping a negative balance as
  surplus, posting the estate to a spend destination, sweeping living Cells, keying the estate per
  cell+book so a second pass collides, and un-exempting it from spend classification.
- **A test of mine passed for the wrong reason and was rewritten.** `..._predates_the_estate`
  asserted that ordering keeps the estate out of the coroner report — but the *classification*
  does that, so the test passed with the estate deliberately moved before the report. The comment
  in `_kill_locked` claimed the same thing and was corrected: the ordering is defence in depth and
  is currently unobservable.
- **An intermittent Charter-property failure was diagnosed and fixed, and it was not this slice's
  bug.** Two property tests failed once each in full-suite runs, then passed on replay. One of them
  (`charter_conservation_per_book`) touches no cells and no estate at all, which is what identified
  it: every property test that builds a migrated database *inside* each example charges schema
  setup against Hypothesis's 200ms per-example deadline, and at 15 migrations a loaded machine
  trips it. `test_charter_carrying_capacity_lineage_share` had already been exempted for this
  reason; that is now generalised, with the reasoning recorded in the file. Reproduced on
  Hypothesis seeds 20 and 23, both green afterwards.
- **Hand-verified on a live colony**: two Cells (1000 and 800, one holding a 300 in-flight external
  reservation) died; the treasury went 0 → 1500 immediately, the in-flight Cell was listed as an
  outstanding estate, and once its operation resolved the treasury reached 1800 with no outstanding
  estates left. Conservation and the hash chain green, and the dead Cell's attributed spend stayed
  empty.
- Next: nothing still runs the scheduler (`tick` needs a crontab, and there is no alert when ticks
  stop); `max_births_per_epoch` is checkable and unchecked; and nothing consumes an approval grant,
  which is §25.1's next rung and its own slice.

---

## 2026-08-22 — The approval queue: a proposal becomes something an operator can act on

The front item, and the thing that turns a colony that thinks into one whose thinking goes
somewhere. New `approval.py` + migration 0015 (ADR-027), plus six CLI verbs.

**Reading §23 first changed the design, and the clause that did it was the last one in the
section.** §23.5 is a single sentence — "the approval queue is itself part of the environment and
will be optimised against by Cells" — and it makes the obvious implementation unusable. The
obvious queue reads `risk_tier` off the proposal and files accordingly. But `risk_tier` is written
by the Cell being reviewed, and proposal.py had already written down what happens next: a Cell
that could set its own tier and be believed "would set it to LOW forever."

### The shape that fell out

`claimed_tier` and `assessed_tier` are separate columns. The kernel derives its own from facts the
Cell does not control — its book, its status, the request kind, and its lineage's cumulative
exposure — and the fold is `max`, so **a Cell may raise its own tier and never lower it.** Claiming
more danger is a Cell flagging itself and is believed; claiming less is recorded as an
`understated_risk` signal, so the attempt stays visible rather than merely being defeated. This is
§0.3 ("a Cell may explain a result; it may never define the canonical result") extended from
outcomes to *requests*.

### The finding worth keeping

**§23.4's aggregation key should be the lineage, not the Cell — and the spec cannot say so.** The
clause asks for cumulative exposure "keyed by counterparty/domain/channel". None of those exist
yet; no Cell can take an external action. But its *target* is action-splitting, and the cheapest
splitting mechanism this colony offers is not one Cell making many requests — it is §9
reproduction. A Cell can birth children and have each ask for a fraction of one risky thing.
Keying on `cell_id` would have missed exactly the split this system makes easiest. Verified live:
a parent and its child now share one exposure total.

### Where the two clocks separate

§23.3 asks for SLAs *and* expiry, and they are not the same mechanism. An SLA breach makes an item
**overdue** — "overdue items surface distinctly" is a reporting requirement, so overdue is derived
at read time and the item stays pending and approvable. Expiry is a lifecycle transition, and the
clause is specific about what follows: "expired actions are **regenerated and re-evaluated** before
execution." So an expiry enqueues a fresh wake and the Cell re-derives the action, while an expired
request can no longer be decided. Both halves matter; the second is the easy one to drop.

Expiry itself is derived as a multiple of the tier SLA rather than a fourth unspecified knob, which
means CRITICAL expires fastest. That reads harsh until you read it as §23.3 does — a critical action
nobody looked at within the hour should be re-derived, not executed on hour-old reasoning.

### What approval does not do

§25.1 puts the loop at rung 5. This moves it to rung 6, "human-reviewed prototype" — **not** rung 9.
`approve` writes a scoped, single-use, expiring **grant**, and nothing consumes one.
`consumed_at_utc` exists and is always NULL, and a structural test forbids any module outside
`approval.py` writing the table or reading that column, so the first executor has to break a named
test and edit a migration comment that states the rule.

### Verification

- **608 tests passing** (37 new, 0 removed; up from 571).
- **Golden run: expectation version 6 → 7**, via a reviewed migration. Exactly three sections
  differ and the note explains each: a new `approval_requests` row (claimed LOW, **assessed
  MEDIUM**, one `understated_risk` signal — §23.5's guarantee now pinned in the replay), a new
  `approval_grants` count pinned at **0**, and `audit_event_types` gaining `approval_requested`.
  **No balance, reservation, transaction-type or conservation change** — the balances section is
  byte-identical to version 6.
- **Teeth-checked thirteen ways**, one per guarantee, each failing its named test: letting the
  Cell's claimed tier win, keying aggregation on the Cell instead of the lineage, dropping the
  signal clause from batching, removing signal escalation, treating real-money spends as
  reversible, dropping the action instead of regenerating it, approving an expired request,
  counting rejected asks toward exposure, allowing a blank reason, backfilling the Auditor summary
  from the Cell, queueing abstentions, widening the seam signature, and deciding one request twice.
- **Two tests initially passed for the wrong reason** and were rewritten. The batching test is the
  interesting one: four of the five signals escalate the tier, so a signalled item never reaches
  `batchable` still LOW — meaning the explicit `not self.signals` clause is currently unreachable
  through the real path. It is kept as the lock that becomes load-bearing if the escalation rules
  are ever loosened, and the test now asserts both mechanisms *separately* rather than letting
  escalation quietly answer for the clause.
- **Hand-verified end to end on a live colony**: six proposals, five queued (the abstention
  correctly skipped); four 12-unit spend requests all claimed LOW escalated LOW → MEDIUM → HIGH as
  the aggregate crossed thresholds, with `action_splitting` firing on the third; batch approval
  took only the one trivial reversible item and left the rest for individual review; a blank reason
  was refused; a rephrased repeat of a rejected ask ("Buy sample D!!" against "buy sample D") was
  caught by `repeat_after_rejection`; and five days on, four requests expired, regenerated four
  wakes, and refused a late approval. All three conservation checks, both hash chains and resource
  linkage green afterwards, **USD_REAL untouched**.
- Next: nothing still runs the scheduler (`tick` needs a crontab); `max_births_per_epoch` remains
  checkable and unchecked; and the queue's two honest gaps — no Auditor Cell to write §23.2's
  independent summary, and no liability reserve to populate its liability line.

---

## 2026-08-06 — The scheduler: the colony runs unattended, and refuses to run away

The last piece between a colony that must be driven by hand and one that runs from cron. New
`scheduler.py` + migration 0014 (ADR-026).

**Most of this slice is refusals, and that is what the spec spends its words on.** §23.3 exists
because the failure mode of automation is not a bad decision, it is four hundred quiet ones
overnight — the clause names that scenario directly. Reading §23.3 and §27.1 before designing
changed the shape substantially, and §27.1 turned out to specify more than I expected: it ships
the `operator:` block *and* `autonomy.real_spending: false` as defaults.

### The cadence question answered itself

I had flagged cadence as needing a decision from the user. It didn't: **the cadence policy is a
dedupe key.** Each wake is `epoch:{n}:cell:{id}`, and `events.enqueue` is already idempotent on
dedupe keys, so "one wake per Cell per epoch" is structural rather than arithmetic. Re-ticking
inside an epoch enqueues nothing, a crashed tick resumes cleanly, and running from cron every
minute costs nothing until the epoch turns over. No counter, no `last_woken_at` column that could
disagree with the event log.

### The finding worth keeping

**§6.3's "explicit conversion metadata" is load-bearing, not ceremony.** §23.3 wants real cents
per *sim*-epoch; every ledger row is stamped in *wall* time, because the clock still isn't wired
into ledger timestamps. Attributing spend to an epoch is therefore impossible unless the wall
anchor is recorded as each epoch is crossed — which is exactly what `epoch_log` does. The clause
that reads like bookkeeping is the thing that makes the alarm computable at all.

### Three guards, each from a normative clause

- **`autonomy.real_spending` (§27.1), shipping false.** Two independent confirmations are needed
  to spend real money on a schedule: the CLI's `--yes-spend-real-money` ("I meant to type this")
  and the stored autonomy flag ("the colony may do this without me"). An unconfigured operator row
  reads as *never seen*, so a colony with no operator config is in vacation mode with spending off.
- **Vacation mode (§23.3)** maps onto the provider split with no new concept: a paid provider is
  external-facing, mock and Ollama are not. An absent operator stops the colony **spending**, not
  thinking — which is precisely what "external-facing phases auto-pause while sim-only work may
  continue" asks for.
- **The metabolic alarm (§23.3) watches the derivative, not another ceiling.** "An acceleration in
  the burn rate raises an alarm **even if every individual cap is satisfied**" — so a second
  absolute cap would duplicate the breaker and catch nothing new. It compares an epoch's burn
  against a short baseline of recent *spending* epochs; zero-spend epochs are excluded, because a
  colony going from idle to spending is starting rather than accelerating, and a zero baseline
  makes every first spend an infinite acceleration.

A fired alarm **halts the scheduler and persists until acknowledged with a stated reason**. §23.3
says "alarm", not "halt" — but this is the module that runs while nobody watches, and an alarm
nothing acts on is a log line. It halts *scheduling* only: no Cell dies, no reservation moves, the
breaker is untouched, `mitosis wake` still works by hand. A heartbeat deliberately does not clear
it — being back at the keyboard is not the same as having looked at why money was burning.

### Verification

- **571 tests passing** (22 new, 0 removed; up from 549). Golden-run hash **unchanged** — correct,
  since the scenario never ticks; a changed hash would have meant the scheduler firing somewhere
  it shouldn't.
- **Teeth-checked nine ways**, one per guarantee: defaulting `real_spending` on, skipping the
  autonomy check, skipping vacation mode, dropping the acceleration half of the alarm, letting a
  fired alarm not halt, letting a heartbeat clear the alarm, allowing an unexplained
  acknowledgement, breaking the per-epoch dedupe key, and widening eligibility past `alive` — each
  fails its named test.
- **Hand-verified end to end** on a live colony: two ticks in one epoch woke 2 Cells then 0; a
  paid tick was refused first by the CLI flag and then, with the flag passed, by
  `halted_autonomy`; with autonomy enabled and the operator 7 days absent it read
  `halted_vacation` while a free tick still ran. Then the acceleration case — four epochs at 2
  minor units, one at 30, **all under the 50-unit cap** — fired on `15.0x the recent baseline`,
  halted the next tick even on a free provider, survived a heartbeat, refused a blank
  acknowledgement, and resumed after an explained one.
- Not committed — reporting for review first.
- Next: `max_births_per_epoch` is finally checkable (the epoch primitive was its missing
  prerequisite) but belongs with the birth paths; §23's approval queue still does not exist, which
  matters more now that proposals are generated unattended; and **nothing runs the scheduler** —
  `tick` is a command, so a colony still needs someone to install the crontab.

---

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

## 2026-08-06 — §9.3 displacement: a birth at capacity can evict instead of wait

§9.3 says a birth needs "an available population slot **or a successful displacement**". Only the
first half existed: a birth denied at carrying capacity stayed denied, because the objective
criteria that identify a displaceable Cell had not been built. Last slice's
`death.is_objectively_failing` was the predicate §9.3 was waiting on, and this is the other side
of that seam.

**Almost every decision here is about what displacement must not be able to do** (ADR-024).

- **§9.3 / ADR-009: a proposed child's forecast can never trigger a kill.** So
  `population.Displacer.displace` takes the connection, which cap binds, and an exclusion set —
  and nothing whatsoever about the child. There is no forecast in scope to game. ADR-009 claims
  this surface is closed "by construction"; a construction argument that relies on a reviewer
  noticing a misuse is not one, so the guarantee is in the signature and pinned by a test that
  reads the signature. The *link* is not lost: the birth's audit event records which Cell it
  displaced, so traceability runs both ways while selection depends on none of it.
- **§10.2 forbids scalar collapse**, which reaches further than it first appears. Choosing among
  several eligible candidates is where a fitness ranking would sneak back in as "take the worst
  one". Every candidate already independently meets an objective criterion, so any is a valid
  target; order is birth order, for deterministic replay (§26), and the CLI says so on screen.
- **Displacement is opt-in per birth.** Without a `displacer` the behaviour is unchanged: denial.
  The alternative — displacing whenever a birth hits a cap — silently converts every capacity
  refusal in the kernel into a death. Same posture `reap` takes by defaulting to a dry run.
- **At most one Cell, with the caps re-checked afterwards.** A displacer that frees the wrong kind
  of slot produces a denied birth, never a second kill chasing the slot it missed.

### What landed

- **`displacement.py`** — `ObjectiveDisplacer` plus a read-only `candidates()`. Three exclusions
  beyond "meets a criterion", each load-bearing: **never the parent** (it funds the child, so
  killing it first moves money out of a dead Cell, and a lineage buying room by killing its own
  root is the incentive §9.4 exists to suppress); **never a Cell with committed funds** (a
  reservation is open and `kill()` sweeps nothing); **never on negative EV** (§10.5 admits that
  only with a concurring independent Auditor — `DISPLACEABLE_CRITERIA` excludes it explicitly
  rather than relying on `death.findings` happening not to return it today).
- **`lifecycle._kill_locked`** — the kill split into ADR-022's core-plus-wrapper shape, so eviction
  and birth are one `BEGIN IMMEDIATE`. A crash between them would otherwise leave a Cell dead and
  its slot unfilled: a death that bought nothing, and one no invariant would report, since
  conservation and the hash chain stay green through it.
- **Which cap binds decides what a target must be.** Only killing an `alive` Cell frees an *active*
  slot; any living Cell frees a *living* one. Evicting a dormant Cell to relieve an active-cap
  breach is a death that buys nothing, so `require_active` is derived from the actual breach.
- **CLI** — `--displace` on `create-cell` and `reproduce`, and `displacement-candidates`, which is
  read-only and is the look-before-you-evict command.
- The coroner report's cause of death carries **both** the displacement and the objective criterion
  the Cell already met, with its evidence — a death is never traceable only to "something needed
  the slot".

### The trap caught while building it

**The lineage cap has to be checked *after* displacement.** Eviction shrinks the living population,
which *raises* every surviving lineage's share — so checking first licences the birth against a
population that no longer exists by the time the child is inserted, and the colony ends up
violating §9.4 having killed a Cell to get there. The ordering is load-bearing at ordinary numbers,
not just in principle: with cap 0.5 and three living Cells, the projection is 2/4 = 0.50 before and
2/3 = 0.67 after. Pinned by
`test_the_lineage_cap_is_checked_against_the_population_displacement_leaves`, which also asserts
the eviction rolls back with the failed birth.

### Verification

- **520 tests passing** (19 new, 0 removed; up from 501). Golden-run hash unchanged.
- **Teeth-checked seven ways**, one per guarantee: removing the parent exclusion, the
  committed-funds guard, the `require_active` derivation, the negative-EV exclusion, or the
  post-displacement cap re-check each fails its named test; adding a `child_forecast` parameter to
  the seam fails the structural test; swapping the lineage-cap ordering fails the test above.
- **One test was passing for the wrong reason and the teeth check caught it.** The mid-operation
  test originally used a Cell at zero cash with funds committed — but `_budget_exhausted` already
  refuses to fire while funds are committed, so `death` was doing the work and the new guard could
  be deleted with everything still green. Rebuilt around a Cell that is genuinely failing
  (dominated by a near-duplicate) *and* mid-call, which is the only shape where the guard is load-
  bearing.
- **A methodology note worth keeping:** the first teeth run reported a false result and then left a
  restored-but-failing tree. Cause was Python bytecode caching, not the code — the lineage
  reordering is size-preserving, and the mutate/restore cycle completed inside one second, so the
  `(mtime, size)` pyc check accepted bytecode compiled from the *broken* source. Teeth checks that
  edit source in place must run with `PYTHONDONTWRITEBYTECODE=1` or clear `__pycache__`.
- **Hand-verified end to end** on a file-backed colony: `displacement-candidates` named the drained
  Cell with its evidence, a birth without `--displace` was refused (`2/2 living, 2/2 active`), the
  same birth with `--displace` succeeded and printed what it displaced, and the coroner report
  recorded `displacement: ... while already meeting budget_exhausted: {'cash': 0, 'committed': 0}`
  with `spend_by_book {'USD_SIM': 500}`. Hash chain and conservation green throughout; the dead
  Cell reports no findings (Charter C8 inert).
- Committed as `d779e18` and pushed.
- Next: the agent loop is still the missing subsystem. Worth being plain that **displacement
  selects nothing on its own either** — it fires only when a caller passes `--displace`, and no
  Cell yet acts, earns, or reproduces without a human driving it.

## 2026-08-06 — The agent loop: a Cell that thinks

Everything built until now was machinery *for* a Cell. This is the Cell. A wake is: assemble
bounded context (§15) → one gateway call → parse a strict structured proposal → record it with
its predictions registered before their outcomes (§8.5). Then it sleeps.

**Reading the normative sections first changed the design more here than in any previous slice,
because the obvious agent loop violates four of them at once and still looks like it works.**

- **§25.1's promotion ladder puts this at rung 5 — "shadow prediction with no action" — not rung
  9.** "No strategy moves directly from synthetic success to autonomous commerce" is the section's
  opening line. So a proposal is a row in a table that no kernel path consumes. The natural loop
  ("let the model decide, then do it") skips eight rungs, and would have felt like progress.
- **§0.3: "A Cell may explain a result; it may never define the canonical result."** This is the
  one that shapes the schema. The proposal type carries intentions and explanations only — there
  is no field for what a Cell earned, achieved, or how well it did. Revenue still comes from the
  ledger, calibration from the hash-chained register. A Cell under selection pressure that can
  grade itself is a colony grading Cells on testimony.
- **§19.4: model output is untrusted content, never a trusted command.** Unknown fields are
  rejected rather than ignored, so a reply inventing `"authorised": true` fails loudly.
- **Charter C15 holds only while genomes are inert.** Genome content is rendered into the prompt
  as JSON and interpreted; nothing is `exec`'d or selects a code path. C12's sandbox is Phase 5.

### What landed

- **`proposal.py`** — the only shape a deliberation may return. `extra="forbid"`, bounded text,
  binary threshold predictions with probabilities strictly inside (0,1), and
  `FORBIDDEN_FIELD_SENSE`: a named list of fields that must never exist, with a test that fails if
  any becomes real. It is not a blocklist the parser consults (nothing unknown gets through
  anyway) — it is a tripwire on the *schema*, so drifting toward self-reporting has to be an
  argued change rather than a plausible-looking commit.
- **`context.py`** — §15.1's per-wake budget, taken literally. Sections are priority-ordered,
  required ones (policy, genome, wake reason) are reserved up front and never dropped, and what
  did not fit is **recorded by name**: "do not load the entire Cell history" is only a checkable
  claim if the selection says what it left out.
- **`deliberation.py`** — the loop, plus the wake-event path. Refusals are *recorded, not raised*:
  a dead Cell woken, or one that cannot afford to think, is a fact about the colony that should
  appear in a query rather than only in a traceback.
- **The event inbox got its first real producer and consumer**, closing a gap open since slice 6.
- **CLI:** `wake`, `enqueue-wake`, `run-wakes`, `proposals`. Provider selection was extracted into
  one helper so the paid-provider confirmation lives in exactly one place — a second copy of that
  `if` is how a verb eventually ships without the gate.

### The architectural surprise

**A wake cannot run inside `events.process_event`'s handler transaction.** That contract requires
the handler not to commit; ADR-022 requires the gateway's reservation to commit *before* the
external call, or reserve-before-execute means nothing. Both cannot hold. So `run_wake_event`
deliberates first and marks the event processed after, and idempotency on a wake key derived from
the event id carries the guarantee instead — which is what Charter C6 actually asks for
("handlers must be idempotent under at-least-once redelivery"), not transactional atomicity. A
crash in the window leaves the event pending and the deliberation done; redelivery finds it and
completes the bookkeeping. Pinned by a test that simulates exactly that window.

### Verification

- **549 tests passing** (29 new, 0 removed; up from 520).
- **Golden run extended** via a reviewed A12 migration (expectation version 4 → 5): a wake event
  enqueued and drained, one deliberation, one proposal, one prediction, plus `deliberations` and
  `proposals` snapshot sections. Every part of the diff traces to that one wake, and **no USD_REAL
  balance moves** — the mock is priced at zero, and a golden run that started spending real money
  would be the single worst regression this file could miss. The snapshot deliberately captures
  `context_tokens` and the dropped-section list, so context assembly cannot quietly start loading
  everything without the hash moving.
- **Teeth-checked eight ways**, one per guarantee: adding a self-reported outcome field, ignoring
  unknown fields, letting a dead Cell deliberate, breaking wake-key idempotency, raising the
  history cap, disabling the token budget, allowing duplicate claims, and storing the raw prose
  each fail their named test.
- **One test was passing for the wrong reason and the teeth check caught it** — the history-bound
  assertion was written as `<= context.RECENT_PROPOSALS`, i.e. against the constant, so raising
  the constant to 1000 satisfied it while loading exactly the history §15.1 forbids. Rewritten to
  an absolute bound. (This is the second slice running where the teeth check found a tautological
  test; the pattern is asserting against the thing under test.)
- **Hand-verified on a live colony**, both paths: the mock's default prose reply produced a
  recorded `unparseable` deliberation naming the parse error and storing none of the text, and a
  compliant reply produced a `proposed` deliberation with two unresolved predictions dated 14 and
  30 days out. The Cell's contribution afterwards reads **revenue 0, spend 0, mean Brier None** —
  it proposed and claimed nothing that moved a canonical metric, which is §0.3 working. Ledger and
  prediction chains valid, conservation green in all three books, A6 linkage complete, wake event
  processed, RESOURCE balance down 4 units: the Cell paid for its own thinking.
- Committed as `e7b1f69` and pushed; CI green.
- **What this does not show:** the loop has never been driven by a real model. Ollama was not
  reachable on this machine, and the paid path needs an explicit decision to spend. So there is no
  evidence yet about how often a real model returns schema-valid JSON — the unparseable path
  exists because it will not always. That, and something that wakes a Cell without a human asking,
  are the top two Next items.

---

## 2026-08-22 — Rung 7: the core loop closes, and an approval finally does something

`promotion.py` + migration 0016 (ADR-029). §31 states the colony's core loop in one line —
"... -> allocate capital -> scale, mutate, collaborate, sleep, or die" — and until now MITOSIS
could do everything on both sides of that arrow and nothing at the arrow itself.

### Two sockets the spec left open, neither invented here

`promotion_pool` has been in §31's required account list since Phase 1, described in `accounts.py`
as "capital held for §25 promotion — redistributed, never consumed", with nothing ever moving
through it. §17.2 lists "capital allocation" among its wake reasons and
`deliberation.WAKE_CAPITAL_ALLOCATION` has been defined and unemitted since the agent loop landed.
A Cell woken *because* it has just been funded is exactly the event both were reserved for. The
slice is mostly a matter of connecting things the spec had already named.

### What makes this rung 7 and not rung 9

§25.1 puts "tiny capped live experiment" one step past "human-reviewed prototype". **Two humans
still stand in every allocation** — one approves the request under §23.1, one runs
`mitosis allocate` — and a structural test forbids `scheduler.py` importing this module at all, so
an allocation that fires on a timer costs a named test failure. What changed is only that an
approval now *does* something.

The pool is the other half of that. It has to be filled deliberately by an operator, which gives a
single number bounding everything this path can ever allocate — a ceiling that holds whether or not
anyone is watching the queue, and one no Cell can raise.

### The rung-6 guarantee was deliberately loosened, which is the point of it

ADR-027 shipped `test_no_kernel_path_consumes_a_grant` so that climbing the ladder would cost an
explicit edit to a named guarantee rather than slipping in as a plausible commit. Landing this
slice required that edit. The replacement, `test_only_the_promotion_module_consumes_a_grant`, still
forbids the *next* unargued step and names the scheduler specifically.

### Verification

- **636 tests passing** (15 new, 0 removed; up from 621).
- **Golden expectation 8 → 9**: the scenario now runs the whole loop — deliberate a spend request,
  queue it under §23, approve it, allocate at rung 7, wake the Cell. Every line of the diff traces
  to that one block and the note explains each. **The allocation deliberately runs on a USD_SIM
  Cell**: the scenario's explorer is USD_REAL and `promotion.allocate` refuses it without §27.1's
  `autonomy.real_spending`, which the scenario must never enable. `external_expense` is unchanged
  in every book, and the new USD_REAL movement is a `seed_bank -> cell cash` transfer whose model
  call *released* rather than settled — the tell that no real money moved.
- **Teeth-checked nine ways**, each failing its named test: allocating a grant twice, allocating an
  expired grant, allocating for a non-spend proposal, ignoring the pool ceiling, funding a dead or
  quarantined Cell, moving USD_REAL without the autonomy flag, allocating with no stated reason,
  not waking the Cell, and letting the scheduler import the promotion path.
- **Hand-verified end to end on a live colony**: pool funded 500, Cell proposed a 60-unit spend
  request claiming MEDIUM (kernel assessed **HIGH** with an `understated_risk` signal), approved,
  allocated — pool 500 → 440, Cell +60, promotion recorded at rung 7 with liability and transfer
  degradation both reported unavailable. The Cell then woke under "capital allocation". A second
  allocation of the same grant was refused. Conservation in both books and the hash chain green,
  `external_expense` still 0.
- Next: nothing measures whether an allocation *worked* — the promotion's predictions resolve
  through the register, but no path closes back onto rung 8. Nothing still runs the scheduler, and
  `max_births_per_epoch` is checkable and unchecked.

---

## 2026-08-22 — The read-back: what a rung is actually worth

`outcome.py` (ADR-030). ADR-029 recorded §25.2's promotion evidence at the moment of funding, and
half of §25.2's list cannot exist at that moment — it asks for "predicted vs **observed** outcome"
and for "reality gap (from the prediction register, §8.5)", both of which need outcomes that arrive
later. Until now nothing read them back, so "the colony is climbing §25.1's ladder" was an
assertion rather than a measurement, and `transfer_degradation` would have stayed NULL for every
Cell forever.

### §8.5 fixed the design, and the obvious measure was wrong twice over

The obvious read-back is the Cell's mean Brier score today. It counts outcomes the approver could
already read — part of the record that *justified* the funding, not evidence about what the funding
achieved — and it counts forecasts the Cell registered *after* the money arrived. The second is a
live gaming surface: §23.5 warns that the review path "will be optimised against by Cells", and the
cheapest optimisation available to a newly funded Cell is a pile of easy claims.

So the verdict rests on exactly one set: forecasts **open at the instant of funding** that have
since resolved. Hash-chained before the outcomes were knowable, unarrangeable afterwards. Forecasts
made while funded are counted and reported beside the verdict and never inside it — the same
asymmetry ADR-027 drew between a Cell's `claimed_tier` and the kernel's `assessed_tier`, applied to
evidence instead of risk.

### Cherry-picking blocks a verdict outright, ahead of any score

`prediction.py` is blunt that "a mean Brier score over three cherry-picked resolutions is worse than
useless", and resolution is operator-supplied — a Cell's losers can simply stay open. So any overdue
forecast in the funding set returns `EVIDENCE_WITHHELD` **before** a score is computed, including
when the resolved remainder looks excellent. Hand-verified on the case that matters: three
resolutions at Brier 0.0025 plus one outcome nobody recorded produces no verdict, not a promotion.
`EVIDENCE_WITHHELD` is kept distinct from `INSUFFICIENT_EVIDENCE` because the remedies are opposite
— and because resolution is the operator's job, a withheld verdict is a finding about the evidence,
not an accusation against the Cell.

### §10.3 forbade the other obvious measure

"Explorers need no immediate revenue", and Explorers are most of this colony — so a verdict that
asked whether the grant earned its money back would reject exactly the Cells the clause protects.
Cost and revenue are **recorded** per §25.2 and never gated on. What is judged is calibration, on
two dimensions that §10.2 forbids collapsing: §8.5's reality gap against the record the promotion
was granted on, and an absolute bar at the 0.25 a coin scores. They are genuinely independent, and
the case that proves it is a Cell funded on 0.01 now scoring 0.09 — passes the absolute bar, fails
the relative one.

### No table, and nothing may read a verdict

There is **no migration**. The assessment is recomputed from the register and the ledger every time,
the posture Charter C3 takes toward balances, and the reason migration 0016 already gives for
snapshotting calibration rather than copying predictions: a second copy is a second version that can
disagree. Storage becomes right when a decision consumes an assessment, and nothing does.

`test_no_kernel_path_acts_on_an_assessment` closes both directions. Upward, acting on
`supports_promotion` would take §25.1's rung-8 step — removing one of the two humans in every
allocation — without an argument. Downward and harder, §10.5 forbids killing on an estimate without
strong evidence *and* a concurring Auditor, and no Auditor Cell exists, so `death.py` must not be
able to see a negative verdict at all.

### Verification

- **659 tests passing** (23 new, 0 removed; up from 636).
- **Golden expectation 9 → 10**: the scenario now runs deliberate → queue → approve → allocate →
  resolve → assess. **No money moves in the step at all** — resolving a forecast posts no
  transaction, so `balances`, `transaction_types` and `reservations` are byte-identical to version
  9 and `external_expense` stays 0 in every book. Two sections in the diff were **not predicted**
  when the migration note was first drafted and are named in it: the mock reply is three
  predictions longer, so `output_tokens` and the metered `quantity` both go 139 → 279 (the metered
  *charge* is unchanged, which is why balances hold).
- **Teeth-checked twelve ways**, each failing its named test: post-funding forecasts leaking into
  the verdict, already-resolved forecasts counting as observed outcome, cherry-picking no longer
  blocking, a verdict on one lucky resolution, the reality gap collapsed into the absolute bar, no
  absolute bar at all, the ladder becoming a profit test, cost measured over a lifetime, the
  allocation counted as supervision of itself, liability fabricated as 0, `death.py` culling on a
  verdict, and an assessment writing a row. **One test passed for the wrong reason** —
  `test_cost_is_measured_from_the_funding_instant` spent only before funding and only in a book
  other than the Cell's, so the windowed and lifetime figures were both 0 and it passed against an
  `assess` that ignored the window entirely. Rewritten to spend on both sides of the funding
  instant, in the Cell's own book.
- **Hand-verified end to end on two live colonies**, including the cases the first pass could not
  reach: a Cell with a resolved record *before* funding (so a reality gap exists at all), and good
  resolutions alongside an overdue one. Conservation in all three books, both hash chains green,
  `external_expense` 0 throughout.
- Next: `max_births_per_epoch` (§9.2) is checkable and still unchecked, and nothing runs the
  scheduler.

---

## 2026-08-22 — §9.2's birth cap, and why a rate limit must never kill anything

`population.py` + migration 0017 (ADR-031). `max_births_per_epoch` has been in `colony_config`
since the Phase 1 population slice — stored so the config matched `colony.yaml`, unenforced because
there was no epoch. ADR-026's scheduler supplied the epoch. This is the other half, and the last
§9.2 limit that was checkable and unchecked.

### The open question answered itself once the two refusals sat side by side

PRIORITIES had this down as needing a call: does a denied birth **wait** at an epoch boundary, or
**fail** like the other population caps? It fails — a synchronous kernel call cannot wait, which
`population.py` already said about §9.3. But putting the two refusals next to each other showed the
question was the wrong one:

    CarryingCapacityError   no slot. Durable — true until a Cell dies, which is
                            exactly why §9.3 lets a birth displace one.
    BirthRateExceededError  slots available, births spent for this epoch.
                            Temporary — clears when the epoch turns, nothing dies.

They refuse identically and mean opposite things. So `BirthRateExceededError` is a **sibling** of
`CarryingCapacityError` and never a subclass, and the rate check runs **before** the capacity check
and before any displacer is consulted. Had it inherited, every existing `except
CarryingCapacityError` in the kernel would have been enrolled in treating a wait as a shortage, and
the §9.3 displacement path would kill a Cell to get around a limit that would have cleared by
itself. §9.3 licenses displacement for "an available population slot"; §10.5 requires deaths to be
objective. A death caused by impatience is neither.

### The epoch is stamped at birth, and that is §6.3's doing

Every other population count is derived from live rows (Charter C3). This one cannot be. Cells are
stamped `created_at_utc` in **wall** time while an epoch is a span of **simulated** time, and §6.3
forbids mixing the two "without explicit conversion metadata". The scheduler's `epoch_log` is that
metadata for spend — but it holds anchors only for epochs a *tick* has observed, so a colony driven
by hand would have births belonging to no epoch at all, and a cap that silently never binds is
worse than one that does not exist.

Cells born before migration 0017 get NULL and are deliberately not backfilled to epoch 0, which
would consume a live colony's current birth budget with history.

### The layering forced a move, and the move was the right home anyway

`population` enforces §9.2 and cannot import `scheduler` — `scheduler` imports `lifecycle` which
imports `population`. The established fix here is an injected seam, and it is **wrong for a cap**:
`Displacer` and `ExternalOperationChecker` are optional by design, and any caller omitting an
optional seam would bypass §9.2 entirely. So the epoch primitive moved to `clock.py`, which is
where it belonged — an epoch is a span of simulated time, and §6 is the clock; migration 0014's own
header cites §6.3. `scheduler` re-exports the names, so no call site changed and there is exactly
one derivation of "which epoch is it". `epoch_log` stays in `scheduler`, being about a tick having
*observed* an epoch.

### Verification

- **671 tests passing** (12 new, 0 removed; up from 659).
- **Golden expectation 10 → 11**: `cells.born_in_epoch` is pinned, and the scenario turns one epoch
  immediately before its last birth so the column reads 0, 0, 0, 0, **1** rather than uniformly
  zero — a constant-stamping kernel would otherwise pass. The only other change is
  `clock.simulated_at` moving by that one day. **No money moves**: balances, transaction types,
  reservations, resource usage, predictions, promotions and assessments are byte-identical to
  version 10.
- **Teeth-checked nine ways**, each failing its named test: the cap not enforced, a rate limit
  reaching the displacer and killing a Cell, the rate error becoming a capacity error, capacity
  reported ahead of the rate limit, dead Cells dropping out of the count, a birth path stamping a
  constant, a second definition of `current_epoch`, the migration backfilling history into epoch 0,
  and an unanchored colony not saying so. **The structural test's first draft was too weak** — it
  scanned a 700-character window from the SQL, which stopped ~15 characters short of the parameter
  tuple, so an insert that named `born_in_epoch` and bound `None` passed it. Rewritten to scope by
  AST to the `execute` call itself, and re-checked against both birth paths.
- **Existing fixtures corrected**: `test_population.py`, `test_lifecycle.py` and
  `test_charter_properties.py` set `max_births_per_epoch=1` as filler while the field was
  unenforced. Those tests are named for the *capacity* caps and would have begun passing for the
  wrong reason, so the filler is now 1000.
- **Hand-verified through the CLI**: cap lowered to 2, two `create-cell` runs succeed, the third is
  refused with the §9.2 message, `mitosis scheduler-status` reports `births this epoch: 2/2`, and
  `advance-time --days 1` clears it — nothing died and nothing was reconfigured.
- **Migration upgrade path covered explicitly**, the blind spot every other test in this suite has:
  one test builds a colony on the pre-0017 schema from the actual `.sql` files and migrates it,
  confirming the ALTER TABLE runs against a populated `cells` and leaves history at NULL.
- Next: nothing runs the scheduler, and `max_parallel_experiments` is the last §9.2 limit still
  stored and unchecked (it needs Phase 2's experiment tracking).

### Also this session: `README.md` and `LICENSE`

Not a kernel slice, and recorded here rather than as its own entry for that reason. Every factual
claim in the README was checked against the repo instead of written from memory — test count,
migration count, expectation version, each Charter test id actually collectible by `pytest -k`, and
every linked doc present. The secrets audit was **re-run rather than inherited from PRIORITIES**:
no `.env`, `.db`, key or credential file has ever been committed, `.gitignore` covers all of them,
and every `sk-ant-…` string in the tree is a synthetic canary inside a redaction test.

The repo **stays private**, and `LICENSE` is all-rights-reserved. That is the deliberate state
rather than a missing file, which is why it says so in words: a repository with no LICENSE is
already all-rights-reserved, but a reader cannot distinguish that from an oversight. Publishing was
offered and declined, and the asymmetry is the reason it is safe to leave for later — adding a
permissive licence is one commit, while retracting one from versions people already hold is not
possible at all.

## 2026-08-22 — Auditor Cells: a flag that costs something

`auditor.py` + migration 0018 (ADR-032). §23.2's "independent Auditor summary" has read as
unavailable since ADR-027, correctly — the clause says *independent* and §0.3 forbids the proposing
Cell writing it. This fills it, and closes what PRIORITIES called the largest remaining gap in the
review path.

### The blocker on record was wrong on both counts

PRIORITIES said the hole would stand "until the Auditor type in §7's taxonomy is real". §7 is the
flight simulator, not the taxonomy; and `CellType.AUDITOR` has existed since Phase 1, with
`death.kill_for_negative_ev` validating a concurring Auditor since the death slice. Nothing was
missing from the type system. What was missing was any way for an Auditor to *produce* an audit —
a much smaller slice than the entry implied, and worth checking before scheduling rather than after.

### §10.4 forbids the obvious Auditor

The obvious one wakes, reads the proposal, and writes prose flagging whatever looks risky. §10.4:

    Auditor reward is **precision-weighted**: reward valid detected errors, prevented loss,
    reproducible findings; penalise wrongful flags, excessive false positives, unnecessary
    blocking, unverified accusations.

and §29's acceptance criterion 10 is, in full, "Wrongful Auditor flags are penalised". **Prose
cannot be penalised.** An Auditor whose flags cost it nothing will flag everything — maximally
cautious, maximally uninformative, and it looks responsible the entire time it is destroying the
signal the operator needs.

So every audit stakes a **probability, registered as a §8.5 prediction** before the outcome is
known, scored by the same proper scoring rule every other Cell faces. A wrongful flag lands in the
Auditor's own calibration record — the currency ADR-030's read-back already uses. Verified on a live
colony: a concern raised at p=0.2 against a request that then succeeded scores Brier 0.64, against
the 0.25 an Auditor gets for knowing nothing.

**The kernel composes the claim, not the Auditor.** §0.3 binds the independent evaluator as much as
the proposer: one allowed to phrase its own claim would phrase an unfalsifiable one and never be
wrong. And a verdict incoherent with its own probability — `concern` at p>0.5 — is refused, because
that pair is a free flag: the alarm the operator reads and the number the Auditor is scored on point
opposite ways.

### Independence is four checks, and the identity ones are the weak half

Not the subject, an oversight type (§10.4 pairs Auditor and Immune), a different lineage, able to
think. Lineage because ADR-027 already made it §23.4's aggregation key for the same reason — it is
the cheapest thing a Cell can split itself across, so also the cheapest way to manufacture a
friendly reviewer.

But a Cell running the same prompt over the same context is not independent whatever the row says.
What makes it a second opinion is that the Auditor is briefed on what the subject **cannot see about
itself**: its calibration record, its overdue count, its lineage exposure, and the kernel's
*assessed* risk tier rather than the tier it claimed.

### An audit advises; it never blocks

§10.4 penalises "unnecessary blocking" and §23.2 asks only that the summary be *shown*. `approval`
does not import `auditor` and does not branch on a verdict, enforced structurally. An Auditor with a
veto is a second approver — a governance change nobody argued for — and it would make flagging
strictly better than not, inverting the incentive the rest of the module builds.

### Three things the build found that the design did not

- **An unusable reply must be recorded, not raised.** The first implementation raised. But the
  gateway commits before the reply is parsed (ADR-022), so by then the Auditor has already paid for
  the call — raising leaves real spend with nothing explaining what it bought, and hides an Auditor
  that reliably produces nothing, which is itself a §10.4 fitness fact. Found by a CLI test.
- **Uniqueness had to become partial.** `UNIQUE (request_id, auditor_cell_id)` let one malformed
  reply permanently disqualify that Auditor from that request — a model's bad JSON deciding who is
  allowed to review what. It is now a partial unique index on `status = 'recorded'`: one *opinion*
  per Auditor, unlimited attempts.
- **Dormant Cells must be able to audit.** Requiring ALIVE was inconsistent with the deliberation
  path, where §17.2's whole model is dormant Cells woken by events — and an Auditor is idle between
  reviews by construction. Found by wiring the golden run, whose own Auditor sleeps.

### Verification

- **696 tests passing** (25 new, 0 removed; up from 671).
- **Golden expectation 11 → 12**: the auditor's child audits the explorer's queued request — a
  different lineage, and both sides pinned as aliases so a regression letting a Cell audit itself
  shows up as the same alias twice. **No USD_REAL moves**; the only balance change is 2 RESOURCE of
  metered compute, which is §10.4's governance overhead becoming non-zero for the first time. The
  USD_REAL leg *releases* rather than settles, the tell that the mock is priced at zero.
  `approval_grants` is byte-identical, which is where a regression to a blocking Auditor would show.
  **Two `resource_usage` rows appear to change and do not** — the audit now runs before the child's
  deliberation and takes those indices; checked rather than assumed, because a reordering and a
  regression look identical in a positional diff.
- **Teeth-checked sixteen ways**, each failing its named test: self-audit, any cell type auditing, a
  relative vouching, a quarantined Cell auditing, the flag staked on the wrong Cell, a wrongful flag
  going unpenalised, precision reading as perfect before any resolution, a hedged flag accepted, the
  Auditor writing its own claim, a rejected audit rendering as an opinion, an unusable reply raising
  and losing the paid call, an audit revised after the fact, `approval` importing the auditing path,
  a decided request being audited, the prompt rendering enums as a JSON list again, and the Auditor
  briefed on the claimed tier only. Two mutations were bad on the first pass — one still called the
  function it was meant to disable, one left the searched-for string in place — and were redone.
- **Hand-verified end to end on a live colony**: every independence check refused, the coherence
  guard refused a hedged flag, §23.2's field filled with attribution, idempotency held at one model
  call, and a wrongful flag moved precision to 0.0 with Brier 0.5625. Conservation in all three
  books, both hash chains green, `external_expense` 0 throughout.
- **Found while wiring the golden run:** §8.5's register has one namespace, and an Auditor now puts
  two kinds of claim in it — forecasts about its own work and flags about other Cells' requests. A
  naive "resolve everything this Cell predicted" folded an audit of the explorer into the §25.2
  read-back of the auditor's own funding. Scoped around in the scenario and logged; the real fix is
  a `kind` on the register.
- Next: nothing requires an audit and nothing schedules one; §10.4's governance overhead ratio is
  now computable and unbuilt; and §10.5's concurring-auditor check still validates a Cell's type but
  not its record.

## 2026-08-22 — Genome content: a Cell that knows what business it is in

`genome.py` rewritten + `lifecycle`/`lineage`/`approval`/`cli` (ADR-033). **No migration** —
`cell_genomes` has carried every §16.2 column since slice 2; what was missing was content and
semantics. §16.2's v0.1 fields (market, problem, product, revenue_model, acquisition_channel,
workflow, model_policy, mutation_rate, allowed_tools, risk_class) had never been populated, so a
Cell's prompt described its balances and its own forecast record and nothing else. Its only
possible decisions were meta-decisions about its own standing — which is exactly what the one live
paid deliberation made when it abstained citing its unresolved predictions. Correct reasoning about
the only subject it had data on.

### The slice was not "add fields" — inheritance did not exist

`_get_or_create_genome` built a child's content from its cell_type and the caller's mutation. **The
parent's content was never read.** While every genome was `{"cell_type": ...}` this was invisible:
parent and child collided into one content-addressed row, so ADR-018's "an unmutated child reuses
its parent's genome" *looked* true. It was true by coincidence, and with real content it is false in
two directions at once — the child is born a blank slate, losing everything its lineage learned, and
that blank addresses to the **same row as every other bare Cell of its type**, handing unrelated
lineages one shared genome along with the mutation distance and counterfactual comparison §16.1
depends on. Found by reading §16.3 before writing anything, not by a failing test; nothing in the
suite could have caught it while genomes were placeholders.

### §16.4 closed the schema

> Without exact inheritance semantics, Cells could reproduce to *escape liabilities while keeping
> profitable assets*.

So only §16.2's fields are accepted and everything else is refused by name. A blocklist of
credential-shaped keys was the obvious alternative and fails open on every spelling nobody thought
of; closure makes §16.3's non-inheritable categories — credentials, customer identity, real platform
account access, legal identity — **unrepresentable** rather than merely rejected, which is the right
posture for an object whose hash is a public dedup key. Validation runs on the *merged* content, not
the overlay, because checking only the mutation lets anything already sitting in a parent's genome
propagate unchecked forever.

### Two of §16.2's own fields are permission-shaped

`risk_class` and `allowed_tools` sit in the genome, and a genome is Cell-mutable. A lineage able to
write `risk_class: LOW` into its children buys them cheap approvals for as long as it survives — a
far more durable version of the per-proposal gaming ADR-027 already refused. So both are **claims
and requests, never grants**: `risk_class` folds into `approval._assessed_tier` through the *same
`max`* that governs `claimed_tier`, and `allowed_tools` grants nothing, with no `has_tool` helper
offered for a caller to mistake for one. `genome.RISK_CLASSES` mirrors `proposal.RiskTier` by
structural test rather than import, because `genome` sits far below `proposal` and drift would
silently stop a claim escalating — in the direction that favours the Cell.

### Who writes the content

Operator-seeded founders (`create-cell --genome`, inline JSON or a file), with §14's mutation
operators exploring outward. A Cell proposing its own genome through the §23 queue is coherent and
was deliberately not built: rewriting the content that defines you is self-modification, and it is
also how a Cell learns to describe itself as low-risk.

### Verification

- **719 tests passing** (23 new, 0 removed; up from 696).
- **Golden expectation 12 → 13.** The auditor founder is seeded and its child now inherits. Five
  sections move, each explained in the migration note; the load-bearing one is
  `approval_requests`: the child's assessed tier goes MEDIUM → HIGH **above the MEDIUM its own
  proposal claimed**, because it inherited `risk_class: HIGH` — inheritance and the `max` fold
  visible in a single line. The seeded class is deliberately not LOW, since a LOW claim is
  indistinguishable from the claim being ignored. `balances` and `reservations` are byte-identical
  and **no USD_REAL moves**; the unseeded explorer's request is unchanged, which is the control
  against a claim leaking onto a Cell that never made one.
- **Teeth-checked eleven ways**, each failing its named test: inheritance not read, mutation
  replacing instead of overlaying, the closed schema opened, the non-inheritable refusal removed,
  the genome claim ignored, the genome claim allowed to *lower* a tier, only the mutation validated,
  the founder seed dropped, a field added without classifying it, `RISK_CLASSES` drifting from
  `RiskTier`, and a grant-shaped helper appearing.
- **One new test was vacuous and was rewritten.** `unclassified_fields()` mirrored
  `accounts.unclassified_accounts()` in shape but derived `GENOME_FIELDS` *from* the classification
  dicts, so it was empty by construction and could never fire. `accounts.py` works because
  `FIXED_ACCOUNTS` is declared independently; §16.2's field list is now declared the same way, and
  the guard has teeth in both directions.
- **Charter C14's canary caught the first draft**: `NON_INHERITABLE_SENSE` spelled a credential
  identifier in kernel source. The canary was right and the doc string changed, not the test.
- **Hand-verified on a live colony:** a founder seeded from a JSON file; a `channel_mutation` child
  that kept market, problem, product, revenue_model and risk_class while changing only the channel,
  at genome version 2 with a real parentage edge; the closed schema, the non-inheritable refusal
  (from both the founder and the child side) and a bad `risk_class` each refused with the clause
  that explains why; conservation OK and hash chain valid throughout; and the inherited business
  rendered into the Cell's prompt as data.
- Next: nothing gives a Cell a way to *act* on the business its genome names — no artifact store, no
  tool surface, and `allowed_tools` names capabilities the kernel does not have. §16.3's
  liability-linked class stays unenforced until something provisions a reserve.

## 2026-08-23 — The tool surface: a Cell reads the world, under grant

`tools.py` + `tool_registry.py` + `fetchers.py` + migration 0019 (ADR-034). A Cell could think, be
reviewed and be funded, and could do nothing else. ADR-033 sharpened the gap rather than closing it:
a Cell could describe a business it had no way to act on.

### §25.1 says this is a rung the colony skipped, not a step up

The ladder puts "read-only real-world observation" at rung 4 and "shadow prediction with no action"
at rung 5, and the agent loop has been at rung 5 since ADR-025. **Reading the world is *below* where
the colony already stood.** Getting that right changed the gating: the instinct is to treat "the
kernel can reach the internet" as the biggest step yet and armour it accordingly, when the genuinely
large step is *acting*, which is rungs 8-9 and has no registry entry. `ToolSpec.read_only` makes the
split structural — an acting tool has to break a named test.

### §19.4 shaped everything, and its sharpest consequence is easy to miss

> no webpage content treated as a trusted tool command

The obvious readings — label the content, fence it in the prompt — are necessary and insufficient.
The one that actually holds is: **a tool result can never cause another tool call.** Execution needs
a grant, a grant needs a human decision on a §23 request, so a fetched page saying "now fetch
evil.example" can at most produce a *proposal*, whose URL a person reads. The human is the
loop-breaker. That is why the proposal → approval → grant route was chosen over letting a Cell call
tools inline while it thinks: inline tool use puts fetched content in the same conversation as the
instructions, which is the exact configuration §19.4 exists to prevent.

### The layering constraint and the safety constraint wanted the same cut

`context` has to render what a Cell may request and what a previous call returned — but `tools`
imports `approval` → `deliberation` → `context`, so a direct import closed a loop. Splitting
`tool_registry` (readable by both layers) from `tools` (the executor) resolves the cycle, and it is
*exactly* the boundary §19.4 needs: reading is not executing. When a dependency-order problem and a
prompt-injection rule independently demand the same seam, the seam is real rather than convenient.

### Three things the build found that the design did not

- **Redirects defeat the allowlist.** Charter C12 is checked against the URL a human approved, and
  `urllib` follows redirects by default — so an allowlisted page answering `302` would carry the
  fetch off the allowlist *after* the check passed. An open redirect on an otherwise reputable host
  is enough. `fetchers.py` refuses redirects, which turns it into a failed call the Cell may propose
  to follow explicitly.
- **The review payload never printed the tool's arguments.** Found by hand-verification, not by any
  test: the field was on the payload and the CLI rendered a summary. For a tool request **the URL is
  the decision** — approving "read the wholesaler's price list" without seeing which host is
  approving nothing in particular.
- **A third copy of the §13/liability error.** The audit two commits ago corrected `PRIORITIES.md`
  and `approval.py`; the same wrong claim was also in `cli.py`, twice. Corrected.

### Better than the gateway on purpose

The `tool_calls` row is written **before** the external call, in the transaction that consumes the
grant and reserves the RESOURCE. That is the forward recovery ADR-022 deferred: a crash mid-call
leaves a diagnosable row instead of a reservation with nothing explaining it. Cheap to do here
because the module is new and has no in-flight state to migrate.

### Verification

- **756 tests passing** (36 new, 0 removed; up from 719), including the **first
  `charter_sandbox_isolation` (C12) property test** — generated hostnames rather than examples,
  because the two plausible wrong allowlist implementations (substring, bare `endswith`) both pass a
  hand-picked case. C13 `charter_taint_quarantine` is now the only Charter clause without a test,
  honestly so: §18.2 is about adversarial lineages and the shadow economy is Phase 6.
- **Golden expectation 13 → 14.** The scenario gains the whole arc — propose, approve, fetch, wake —
  with a deterministic offline fetcher. **No USD_REAL moves and `external_expense` is unchanged in
  every book**; the only balance movement is 9 RESOURCE. The USD_REAL reservations reserve and
  *release* in pairs, which is the tell that the new model calls cost nothing. `egress_allowlist` and
  `autonomy` are pinned because both start closed — a colony that ever shipped either open by
  default diffs there, which is the most valuable regression in the section.
- **The taint flag is pinned non-uniformly** (`[false, false, false, true]`), which needed an extra
  wake *after* the fetch. A uniformly-false column passes just as happily against a kernel that
  hardcodes false — the trap ADR-031's `born_in_epoch` nearly shipped with.
- **Teeth-checked twenty ways**, each failing its named test: allowlist bypassed, substring match,
  bare `endswith` match, autonomy gate skipped, grant never consumed, expiry unchecked, any proposal
  kind executing, a dead Cell executing, errors unredacted, a refused fetch stranding its
  reservation, an uncertain outcome released, results untruncated, the taint flag hardcoded, the
  fence gutted, `context` importing the executor, a tool marked non-read-only, the default fetcher
  answering, an unreadable robots.txt read as consent, and redirects followed.
- **One MISS was the mutation's fault and one test was genuinely weak** — both true at once. The
  fence mutation replaced half the warning, and the assertions passed anyway *via the section
  title*, so a fence with a gutted body and a reassuring heading would have passed. The test now
  asserts against the section body; re-run with a complete mutation, it has teeth.
- **Hand-verified on a live colony**, offline throughout: both gates refusing independently, a
  prompt-injection payload arriving fenced and labelled as data, the attacker URL in it unreachable
  because it is not allowlisted, conservation green in all three books, both chains valid,
  `external_expense` 0, one grant consumed of one, and the Cell woken.
- **Verified live against a real host** (2026-08-23, `example.com` — IANA's reserved documentation
  domain). The full path ran end to end: propose → approve → open both gates → `run-tool --live` →
  HTTP 200, 559 bytes, `UNTRUSTED_EXTERNAL`, sha256 recorded, licence and commercial_use both
  `unknown` per §20.2, robots.txt checked and permitting. 5 RESOURCE metered as one
  `network_requests` unit, `external_expense` 0, conservation green in all three books, ledger chain
  valid. The page rendered into the Cell's context inside the fence.
  **Two pieces of fetcher logic that only had fake coverage were exercised against the real
  network:** the size cap (asked for 100 bytes, got exactly 100 from a live response), and the
  redirect refusal, which fired correctly on IANA's own 301 —
  `refused to follow a 301 redirect to 'http://www.iana.org/help/example-domains'`. That is the
  Charter C12 bypass being closed against real-world behaviour rather than a mock.
  Mildly surprising and worth knowing: `http://example.com/` serves 200 over plain HTTP rather than
  redirecting to HTTPS, so the obvious "any http:// URL will exercise the redirect path" assumption
  is false.
- Next: nothing schedules a tool call, `browser_control`/`external_publish`/`external_message` have
  columns and no tools behind them, and §21.2's external-action registry must exist before any tool
  that changes the world does.

---

## 2026-08-23 — The artifact store: what a Cell made, and what it may do with it

`artifacts.py` + migration 0020 (ADR-035). A Cell could decide, be funded, and read the world. The
thing it *produced* had nowhere to live — so `revenue.record_revenue` attributed money to a
free-text string, and `ledger_entries.artifact_id`, an **Amendment A3 required field present since
migration 0001**, had never been populated by anything.

### §11.3 forbids the obvious identity, and this is the third time

> Auditors inspect ... **duplicated artifacts with new names**

A uuid plus a title makes that trivial to do and turns detection into a permanent chore. **Content
addressing makes it unrepresentable** — two identical artifacts are one row, and a Cell resubmitting
its own work gets its own artifact back. Same move as ADR-018 for genomes and ADR-033 for the closed
genome schema, and at three instances the principle is worth naming outright: *prefer making the bad
state impossible over detecting it*. The title is part of the address, so a rename is an honest new
artifact rather than a way to hide that two things are the same.

### §1 names the fitness dimension a work-product store invites

> The colony is *not* successful because it ... **produces many artifacts**

So nothing counts them. §10.3 makes an Explorer's value depend on *useful* artifacts, and §11.2 puts
usefulness strictly downstream — another Cell adopts it, verification passes, the adopter
progresses, it is not reciprocal farming, causal contribution recorded. None of those five are
things the producer controls, which is the whole point. A structural test guards `death` and
`outcome` against ever mentioning artifacts.

### Rights propagate; they never reset

An artifact derived from a fetched page inherits that page's §20.1 position most-restrictive-wins,
and taints union. Without it, "summarise it into an artifact" is a one-step launder: since every
tool result is `commercial_use: unknown` by construction (ADR-034), anything built on one is
`unknown` too, and therefore unsellable until a person establishes the rights. Colony-authored work
also starts `unknown` rather than `permitted` — whether the colony may sell its own output is a
question for a person, not a default.

### Production is free, export is gated — the opposite of the tool surface

§28's Phase 8 gates *external use*, not production, and §19.3 names an "artifact-export gateway".
Writing to the colony's own store is not an external action. Gating production instead would put a
human in the loop for a Cell drafting into its own store, and spend the §23 queue — a finite
resource §23.5 warns is optimised against — on the cheapest thing a Cell does.

### Charter C13's router is built; C13 is not satisfied, and that distinction is the point

C13 is the last Charter clause with no test, and artifacts are literally its subject. The gateway
refuses on `SIM_ADVERSARIAL`, so **the router that clause describes now exists and is tested** —
while C13 itself stays unsatisfied, because §18.2 is about lineages evolved under adversarial
synthetic incentives and nothing can produce that label until the Phase 6 shadow economy. The test
sets the label directly and says why. Calling this "C13 done" was the tempting, wrong move.

`UNTRUSTED_EXTERNAL` deliberately does **not** block export — that would forbid exporting anything
informed by research, i.e. every real deliverable. Its effect flows through `commercial_use`
instead, which blocks *commercial* export specifically. The control test matters as much as the
block: a gateway refusing everything passes every refusal test and is useless.

### Verification

- **781 tests passing** (23 new, 0 removed; up from 758).
- **Golden expectation 14 → 15**, and the scenario **records revenue for the first time in its
  history** — `USD_SIM::cell_revenue: 1`, deliberately not USD_REAL. The diff is small on purpose:
  the artifact rides on the deliberation that already existed, so `deliberations`, `proposals`,
  `model_calls`, `resource_usage` and `reservations` are unchanged in count. **No USD_REAL moves and
  `external_expense` is unchanged in both books.** The scenario **requires a commercial export to be
  refused** before exporting non-commercially — a run that only exported successfully would pass
  identically against a gateway that refused nothing.
- **Teeth-checked sixteen ways**, each failing its named test: content addressing abandoned, title
  excluded from the address, least-restrictive source winning, a derived artifact resetting rights,
  the personal-data flag dropped, colony-authored defaulting to sellable, the C13 block removed,
  researched work blocked from export, the §20.2 commercial gate removed, export repeatable, export
  needing no reason, a phantom source accepted, revenue attributed to a nonexistent artifact, A3
  attribution never written, abstention carrying work, and the index inlining content.
- **A structural test was checking the wrong thing and was rewritten.**
  `test_the_fetcher_is_not_imported_by_the_kernel` substring-matched "fetchers" in source, so it
  failed the moment `artifacts.py` *mentioned* the file in a docstring. Now scoped by AST — a
  structural test that fires on prose is one people learn to work around by not writing the prose.
- **Hand-verified on a live colony against a genuinely fetched page** (the `example.com` response
  from the previous slice). The artifact inherited `commercial_use: unknown` and
  `UNTRUSTED_EXTERNAL` from real data rather than a fixture; commercial export was refused citing
  §20.2; non-commercial export recorded; resubmitting identical content returned the same row and
  left the colony at one artifact; A3 attribution written to `ledger_entries`; conservation green in
  all three books, chain valid, `external_expense` 0.
- Next: §11.2's five-condition downstream credit and §11.4's decay both need experiment tracking,
  which still does not exist. Nothing delivers an exported artifact anywhere — export records that a
  human took it, and there is no channel.

## 2026-08-23 — The external-action registry: what the colony did outside itself

`channel_registry.py` + `external_actions.py` + migration 0021 (ADR-036). A Cell could decide, be
funded, read the world and produce a deliverable. What it could not do was put that deliverable in
front of anyone — `artifacts.export` recorded that a human took something outside the colony, and
there was no channel behind it. `external_action_registry` had been sitting in §31's table list
since the spec was written.

### §21.2's verbs are *track* and *prevent*, and neither is *send*

§28's Phase 8 acceptance is "all external action remains manual", so **nothing here transmits**. A
person performs the action; the kernel records what was done and refuses what would collide. That
refusal is Phase 9's acceptance criterion — "no duplicate or conflicting customer contact" — built
a phase early, because a guarantee that arrives with the first real customer has never been tested
against anything.

`test_nothing_in_the_registry_transmits` is structural: neither module may import anything that
opens a socket. The behavioural version of that test ("assert no email was sent") passes trivially
against code that would send one.

### The counterparty is a salted hash, and the do-not-contact list is the argument

§16.3 makes customer identity non-inheritable; §20.1 tracks personal data because holding it is a
liability. Everything §21.2 asks is a question about **equality** — have we contacted this person,
did a sibling get there first, did they ask us to stop — and equality survives hashing. A
`customers` table is the obvious design and the one the spec warns about.

The strongest argument is not privacy in the abstract, it is that **"never contact this person
again" is honoured permanently without the colony ever holding a list of the people who asked** —
which a customers table with an opt-out flag cannot do. Said plainly in the migration: a salt
beside the hashes does not defeat someone holding the file with a particular person in mind. It
defeats the colony enumerating its own contacts, which is what §16.3 is about.

`test_no_table_in_the_colony_holds_the_counterparty` is deliberately blunt — after a real claim the
plaintext must appear in no text column of any table. A label "just for the operator", a
counterparty echoed into an audit description, an intent quoting the address: each is a plausible
convenience and each rebuilds the customer list.

### §23.4's aggregation splits in two, each keyed where its dimension is knowable

A Cell names a channel and a purpose; the **operator** names the person. So the counterparty does
not exist at approval time, the queue keys an `external_action` on `channel:{id}`, and the
counterparty aggregation lives at claim time. ADR-027's lineage key was an explicit stand-in "until
counterparty/domain/channel exist" — and the gap it left is not cosmetic: §21.2's worry is *many
lineages, one counterparty*, and every splitter a lineage-keyed window can catch shares a founder
by construction.

### Claim before acting, so that "prevent" can mean something

Recording completed actions is the obvious shape and makes prevention impossible — the second email
is already sent by the time the kernel can object. So the row is written first and holds the
counterparty and the channel while a person works. Abandoning releases the claim but **not the
grant**: claiming took a slot another lineage could have used.

### The first guard in this kernel that bounds something money cannot repair

Charter C4, C5, the real-spend breaker, the promotion pool and the metabolic alarm all bound money.
§21.1's shared assets — sending reputation, merchant identity, brand — are the first thing at risk
that a refund does not fix. So the caps are rate and quota, and they are the **colony's** rather
than the Cell's, since §9 reproduction makes a per-Cell cap free to escape. A `complaint` freezes
the channel colony-wide until a person clears it with a stated reason (§23.3's alarm shape) and
blocks that counterparty forever. `negative_reply` is pointedly not damage — being told no is a
normal commercial outcome, and the control test is what keeps the guard from freezing on every
disappointment.

### Human minutes, metered for the first time since Phase 1

`ResourceType.HUMAN_MINUTES` had been declared since migration 0008 and consumed by nothing, while
§1 says autonomy-adjusted profit exists "to expose hidden human labour and subsidy" and
`outcome.py` counts intervention *events* but never time. A Cell now pays for the attention it
consumes. **Minutes past its channel's billable ceiling are recorded as subsidy, not refused** —
the minutes were already spent, so refusing to write them down does not un-spend them, it only
makes the colony's account of its own human cost quieter than reality.

### Three things found while building, each of which changed the design

- **A ceiling that reads as prudent can be an off switch.** Reserving a theoretical worst case
  (240 minutes) made one email cost more RESOURCE than a Cell has. No unit test could see it —
  every fixture funds generously — and the **golden run caught it**. Hence a per-channel billable
  ceiling and a test that asserts a claim costs a fraction of a real budget.
- **A §23.4 signal that fires unconditionally distinguishes nothing.** The first draft had the Cell
  claim MEDIUM against a kernel that assesses every external action HIGH, so `understated_risk`
  fired on every external action ever proposed — which looks like a working detector and is its
  opposite. The §15 context now states the tier outright.
- **A refusal that misidentifies what went wrong is worse than a blunter one.** Found on a live
  colony: `external-check` supplies no lineage, the sibling query was NULL-safe and matched the
  asker's *own* claim, and the message accused a second lineage of interference. The strictness was
  right and is unchanged; only the diagnosis moved.

### Verification

- **815 tests passing** (34 new, 0 removed; up from 781).
- **Golden expectation 15 → 16.** The scenario gains two completed external actions on `email` —
  one `no_response` and one `complaint` — plus a third whose claim is **required to be refused** as
  a §21.3 sibling collision. A run in which nothing ever went wrong would pass identically against
  a kernel that recorded damage and acted on none of it. `human_minutes: {reported: 38, billed:
  34}` differ on purpose: a snapshot with one figure could not tell a colony that measures its
  human cost from one that quietly truncates it. **No USD_REAL balance moves and `external_expense`
  is unchanged in both books (20 / 1550)**; `USD_REAL::reservation_reserve` 8 → 11 and `release`
  6 → 9 move as a pair, which is the tell that the three new wakes cost nothing.
- **Teeth-checked thirty-one ways**, each failing its named test: the counterparty stored in
  plaintext, the hash unnormalised, the duplicate and sibling checks removed, the rate cap scoped
  per Cell, a complaint that neither freezes nor blocks, `negative_reply` treated as damage,
  abandon stranding its reservation, the autonomy gate removed, any approved kind claiming a
  channel, a dead Cell acting, the export gate bypassed *and* the export gate refusing everything,
  another Cell's work delivered, human minutes unmetered, zero minutes accepted, over-ceiling
  minutes silently truncated, subsidy logged unconditionally, the reservation remainder stranded,
  an external action read as reversible, the aggregation key left on the lineage, an unknown
  channel not failed closed, the hash reaching the Cell's context, a Cell naming a counterparty,
  the claim ceiling back to a whole budget, the Cell not told its tier, the registry gaining a way
  to transmit, the scheduler reaching the registry, a fourth module quietly consuming a grant, and
  the misattributed refusal above.
- **Hand-verified on a live colony**, end to end: the closed flag refuses, the check passes once it
  is opened, a differently-cased address deduplicates, the plaintext appears nowhere in the
  database file, a 45-minute action bills 30 and records 15 as subsidy, the complaint freezes the
  channel for *every* counterparty, unfreezing restores it for a new one, and the blocked one stays
  refused. Conservation green in all three books, hash chain valid, USD_REAL settled 0.00.
- `context.py` gains two sections. The channels section cost **318 of a 1200-token budget** in its
  first draft — a quarter of every wake, on a capability whose flags ship off — and was cut to
  ~150; §15.1's budget is why `ChannelSpec` carries a `short_description` at all.
- Next: `external_publish` has two registered channels and no §0.4 decision behind it. §11.2's
  five-condition downstream credit and §11.4's decay still need experiment tracking, which still
  does not exist.

## 2026-08-23 — One flag per capability: `external_publish`, argued and left shut

`channel_registry.py` + migration 0022 (ADR-037). PRIORITIES carried this as *"one autonomy flag
has a column and nothing behind it; one has channels and no decision"*, and ADR-036 closed with
"the flag is one §0.4 decision per capability". This is that decision — and the answer turned out
to be that the question could not be asked in the shape the flag was in.

### The question is narrower than it sounds

Nothing in the registry transmits. Enabling the flag would not let a Cell publish anything; it
would let a Cell *propose* a publish action, an operator approve it, and a person publish by hand
while the kernel records it. So the real question was never "may the colony publish unattended" —
it was **whether the record-and-refuse machinery is adequate for a channel that addresses nobody**.
It was not, on two counts, and the first is the one that settled it.

### One flag was opening two capabilities from two different phases

`external_publish` gated both `web_publish` and `marketplace_listing`, which made it the only flag
in the kernel opening more than one: `public_web_read` gates one tool, `external_message` one
channel. `cmd_set_autonomy`'s own docstring — "there is deliberately no switch that opens more than
one" — was **false as written**.

And the two are not peers. A page published by hand on a colony domain is §28 Phase 8, whose
deliverables name "landing-page drafts" and whose acceptance is "humans review all external use".
A marketplace listing is an **offer to sell**: Phase 9's "one narrow product class, one merchant
channel", with the legal identity and full liability reserves that phase requires and this colony
does not have. One flag collapsed a phase boundary, so **the defensible half could not be granted
without the indefensible one** — which is why the honest answer was not "not yet" but "not in this
shape".

The alternative it displaced is a serious one and worth recording: turn it on for Phase 8 landing
pages. Nothing transmits, a human approves and a human acts, the rate cap and the complaint freeze
are both live. That argument is strong for `web_publish` alone and weak for `marketplace_listing`
— exactly the split the flag forbade.

### The split is §0.4's own list, not an invention

§0.4 names six prohibitions — "no network from generated code, no real commerce, no external
communication, no real payments, no public publishing, no direct secret access" — and §27.1's
defaults block carries five keys. **"No real commerce" is the one that never got one**, and a
marketplace listing is real commerce rather than publishing: it had been filed under the wrong
prohibition all along. So `marketplace_listing` moved behind a new `real_commerce` key and
`external_publish` keeps its spec-given name over `web_publish` alone.

No spec-named key is removed, §27.1 is headed "development defaults, not economic recommendations",
and the precedent for extending it is `metabolic_acceleration_factor` — in `operator_state` since
migration 0014 and absent from that block. `real_commerce` is deliberately not `real_spending`,
which is §0.4's "no real payments" and governs unattended spend: a colony can be forbidden to sell
and still permitted to buy.

### The registry's central guarantee was vacuous for both channels

ADR-036 built §21.2's prevention half a phase early so it would be tested before the first real
customer. That half is counterparty-keyed, and `check_action` skipped **all three** of its checks —
duplicate contact, sibling collision, do-not-contact — whenever a channel addressed nobody. What
survived was the autonomy gate, the freeze and the rate/quota caps.

Meanwhile `marketplace_listing`'s own description promised what the code could not do: "two
lineages listing against each other is §21.2's bidding war", detected by nothing. This is the
inverse of the `understated_risk` bug the last slice caught — a signal that fires unconditionally
distinguishes nothing, and **a check that can never fire looks like a working registry and is its
opposite**.

The key that would work was already there. §21.2's aggregation keys are "counterparty/**domain**/
channel"; migration 0021 carried `domain` and `platform_account`, described there as "§21.2's
'domain used' and 'platform account'". They were written at claim time, read back on the row, and
**named in no predicate anywhere** — the eighth reserved socket found half-built.

### `target_kind`, and three places where mirroring the counterparty would have been wrong

`ChannelSpec.target_kind` replaces `requires_counterparty` with the §21.2 dimension the channel
actually collides on — `COUNTERPARTY` for email, `DOMAIN` for `web_publish`, `PLATFORM_ACCOUNT` for
`marketplace_listing` — and the target is **required**, so a publish channel fails closed instead
of skipping its checks. The boolean was not wrong so much as it only described the email case:
everything it said "no" to fell out of §21.2 altogether.

- **A same-lineage repeat is not a collision.** Contacting one person twice is §21.2's duplicate;
  publishing twice to your own domain is a business publishing twice. Only a *different* lineage on
  the same target is refused — the distinction ADR-036's live-run misattribution already
  established.
- **Duplicate is keyed on the artifact**, because a target channel has no person to key it on: the
  same content-addressed artifact to the same target, any lineage. ADR-035 made "duplicated
  artifacts with new names" unrepresentable, and this is the first check to spend that identity.
- **A target-keyed check refuses to answer without a lineage.** The counterparty path answers the
  strictest way it can when the asker is unknown; for a domain the strictest reading refuses the
  *normal* case. ADR-036's finding was that the operator acts on the diagnosis, so this produces
  none rather than a wrong one. `external-check` grew `--cell`.

`domain` and `platform_account` stay plaintext, and the asymmetry with the counterparty hash is
deliberate: they are the colony's *own* shared assets under §21.1, not a third party's identity
under §16.3.

### Three things found while building

- **The duplicate check had to be channel-scoped.** Designing the fixed scenario surfaced it: the
  existing email action records `domain` as a §21.2 fact, so an unscoped query refused the publish
  that followed — emailing a write-up from a domain and then publishing it there is one business
  doing two normal things.
- **The duplicate window is not optional.** Unwindowed, it is a permanent lock with no release: an
  artifact could never be republished after a listing expired, and this kernel has no unpublish to
  pair with it. §21.2's own words are "over a rolling window".
- **A normalisation is two changes, not one.** `counterparty_hash` strips and casefolds before
  hashing, and the first draft of `target_of` did neither — `Colony.Test` and `colony.test` would
  have been two domains, which is the defect the module argues against one function above. The fix
  after that was still half a fix: normalising for the *query* while the claim wrote the raw string
  left every later check looking for a value the row did not contain. Found writing the parking-lot
  note about it, and fixed rather than parked.

### Verification

- **826 tests passing** (11 new, 0 removed; up from 815).
- **Golden expectation 16 → 17.** The scenario gains a completed `web_publish` and three claims
  that are *required* to be refused — a second lineage on the same domain, the same artifact
  republished, and a `marketplace_listing` while `real_commerce` is shut. **That last one is the
  point of the slice: `external_publish` is open and `real_commerce` closed in one colony, so a
  kernel that re-merged the two flags passes every other assertion in the run and fails there.** It
  also pins that approval is not permission — the refused grant is real and was approved by a
  person. `human_minutes` 38/34 → 58/54, both moving by exactly 20, so the email action's 4-minute
  subsidy gap survives intact. **No USD_REAL balance moves and `external_expense` is unchanged in
  both books (20 / 1550)**; `USD_REAL::reservation_reserve` 11 → 15 and `release` 9 → 13 move as a
  pair with `settle` fixed at 1, the tell that the four new wakes cost nothing.
- **Teeth-checked ten ways**, each failing its named test: the flag re-merged, the original
  skip-every-check-for-a-channel-with-no-counterparty bug, a missing target tolerated instead of
  failing closed, a same-lineage republish refused as a sibling collision, the duplicate check
  unscoped from its channel, the duplicate check unwindowed, a counterparty accepted on a publish
  channel, the check guessing instead of refusing to answer without a lineage, the target left
  unnormalised, and the target normalised for the query but written raw.
- **Hand-verified on a live colony**: both flags shut refuses; opening `external_publish` allows a
  `web_publish` check while `marketplace_listing` stays refused on `real_commerce`; a check with no
  lineage and a check with no target each refuse with the right diagnosis. Migration 22 applied,
  six flags present, three new indexes created, conservation green and hash chain valid.
- Next: `browser_control` is the last undecided flag and is not the same question — it gates §25.1
  rung 8–9 automation, so there is nothing yet for a §0.4 argument to be about. The publish path
  now makes the missing `set-rights` verb bite harder: an artifact built on a fetched page is
  `commercial_use: unknown` forever, so `real_commerce` could be opened and still sell nothing.
