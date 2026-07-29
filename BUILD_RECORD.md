# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, and reproduction/lineage, 2026-07-21 through
2026-07-26): [docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

**Three entries are current right now, all uncommitted and all part of one arc:** the Phase 4
gateway made the kernel able to spend real money, crash-atomicity closed the largest hole that
slice left, and reconciliation closes the producer-with-no-consumer that crash-atomicity created.
They want reviewing together; the older two get archived once committed.

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
- Not yet committed — reporting for review first.
- Next: the first real paid call, or aggregate-invoice reconciliation.

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
- Not yet committed — reporting for review first.
- Next: the first real paid call (small cap, one prompt), or §24.1 reconciliation — which now
  carries the deferred forward-recovery work as well.

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
- Not yet committed — reporting for review first.
- Next: close the crash-atomicity gap above (the largest known correctness hole), then either make
  the first real paid call (small cap, one prompt) or close the reconciliation gap that both the
  ADR-020 rounding overstatement and `execution_unknown` resolution depend on.
