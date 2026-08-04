# Future Build Hooks

Append-only parking lot for suggestions, ideas, and deferred calls that surface mid-session —
a plan's "out of scope" or "assumptions to confirm" section, a tangent worth remembering, a
"novel idea" that isn't worth interrupting the current task for. **Not the roadmap** — if/when
this project grows a curated priorities or roadmap file, that's where actual planned work lives.
This file is the raw catch-net so nothing dies in a throwaway plan file under `~/.claude/plans/`
or scrolls out of a conversation.

Newest entries at the bottom. Each entry: date, source (which session/plan), the suggestion,
why it's not in scope now. Promote an entry into the roadmap (and delete it here) once it's
actually queued for building — this file is memory, not a backlog to work through in order.

---

## 2026-07-21 — MITOSIS v0.2 spec review
- Source: spec-review session (plan `users-mohammadmaster-downloads-mitosis-cheeky-stardust`).
- Deferred creative additions now normative in the *spec* but not yet built: executable Colony Charter, prediction register, coroner reports, North Star metric table, governance-overhead ratio, chaos drills, solo-operator vacation mode. Build lands in Phase 1+ once the kernel exists.
- §31 directive "must not be lost" long-horizon ideas (M2M commerce, one-customer software factories, CVT-MAP-Elites, approximate-Shapley credit, decaying royalties, internal compute auctions, etc.) live in the spec's per-section Future Build Hooks — pull from there when those subsystems come up.

## 2026-07-25 — Golden-run replay slice: seeded ids for reproducible event ordering — RESOLVED 2026-07-26
- Built: `src/mitosis/ids.py`, wired into every `uuid.uuid4()` call site and into `golden.run_scenario`. See BUILD_RECORD.md / PRIORITIES.md.
- Still open, not this entry's scope: kernel timestamps are still real wall-clock (clock.py is built but unwired), which remains the reason a *real* colony can't be byte-identically replayed — tracked directly in PRIORITIES.md, not here.

## 2026-07-26 — Lineage slice: minimum-population floor before the lineage cap engages
- Source: reproduction/lineage tracking slice (see ADR-019).
- `max_lineage_population_fraction` is enforced literally, so in a *small* colony reproduction is impossible: at the colony.yaml default of 0.20, any second-generation Cell in a 4-Cell colony is already 40% of the living population. Seeded founders are exempt (a founder has no ancestor), so the bootstrap path is "seed more founders", and the cap is harmless at Phase 2's target scale of hundreds–thousands of Cells — a lineage may hold 200 of 1000. It only bites in small test/bootstrap colonies.
- Common EA practice is a **minimum-population floor**: the share cap only engages once the living population is large enough for a fraction to be statistically meaningful (e.g. `living >= 1/cap`). Deliberately *not* implemented, because SPEC.md §9 specifies no such threshold and inventing one would be inventing colony policy rather than implementing the spec. Worth revisiting when Phase 2 sets up real seeded populations — if the flight simulator ends up needing a floor to bootstrap, that's evidence the spec should gain one explicitly.
- Related, and also deferred: §9.4 lists diversity bonuses, diminishing birth priority, independent-replication requirements, and niche-specific carrying capacity as founder-effect measures. Only the hard cap is implemented; the rest are selection-policy concerns that belong with Phase 2's MAP-Elites/allocator work, not the kernel.

## Phase 4 model gateway (2026-07-27)

- **Provider-invoice reconciliation** is now load-bearing in two places, not one: it trues up
  ADR-020's up-to-0.999-cents-per-call rounding overstatement, *and* it is the only thing that can
  resolve a reservation left in `execution_unknown` by a timed-out call. Until it exists, an
  `execution_unknown` model call holds its funds committed indefinitely with no operator path to
  resolve it. A `mitosis reconcile-model-call --resolve settled|unbilled` verb would be a cheap
  interim.
- **Tighter pre-call token estimation.** `providers._estimate_tokens` assumes 2 chars/token (a
  deliberate over-estimate) because the real `count_tokens` endpoint is a second round trip. The
  cost is chronic over-reservation, which eats into the C5 concurrent-reserved cap.
- **A rounding-remainder account** was rejected in ADR-020 as premature. If sub-cent calls become
  the dominant workload, revisit: a `rounding_remainder` fixed account would let the ledger carry
  exact micro-USD without widening USD_REAL's minor unit.
- ~~**`_REAL_SPEND_TRANSACTION_TYPES` is a footgun, and is not yet the single source it looks
  like.**~~ — CLOSED 2026-07-28 by ADR-023, which added the predicted third type
  (`model_call_reconciliation_adjustment`) and so had to fix it: both the global and per-provider
  queries now read the tuple. The remaining half of the original suggestion is still open: **a test
  asserting that every USD_REAL transaction type reaching `external_expense` is either in the tuple
  or explicitly exempted.** Today the registration is a convention enforced by a code reviewer
  noticing, which is exactly how the overrun type was missed the first time.
- **Aggregate-invoice reconciliation is what actually closes ADR-020's rounding drift.** Per-call
  reconciliation (ADR-023) provably cannot: 3.5 cents of true cost reconciles back through the same
  ceiling to the 4 already recorded. Ten such calls are 35 cents of true cost carried as 40, and
  only a reconciliation against an invoice *total* covering many calls can post the 5-cent
  correction. Needs an invoice-level record (`invoices` table, calls linked to it) and one
  adjustment posted against the aggregate — the per-call machinery, sign handling and breaker
  registration are already in place, so this is additive.
- **`ledger.spend_by_book` overstates spend for a Cell that received a reconciliation credit.** The
  refund's positive leg is on the Cell's own cash (correctly excluded) but the negative
  `external_expense` leg is dropped by the function's `amount_minor_units > 0` filter, so the
  refund never reduces the figure. Removing the filter is *not* the fix: birth funding's negative
  leg carries the same cell_id, so a freshly-funded Cell would read as having spent a negative
  amount. Telling them apart needs an account-level distinction between funding sources and spend
  destinations that §31's account list does not draw — a real modelling decision, not a patch.
  Bounded impact: this figure feeds coroner reports only, never an enforcement check.
- **Reconciliation is per-call and operator-driven.** Nothing fetches an invoice, parses a
  statement, or reconciles in bulk; `mitosis reconcile` takes one call id and one figure. A CSV or
  provider-API import needs no new kernel concepts and is the obvious next step once there is a
  real invoice to work from.
- **Resolving a `disputed` reservation is only half-built.** `mitosis dispute` moves a reservation
  into `disputed` (§4.4) and `reconcile` carries it out again, but the human/Auditor process around
  a dispute is §23 governance, which does not exist. Today a dispute is a label plus a held
  balance.
- ~~**Gateway success path is not crash-atomic**~~ — CLOSED 2026-07-28 by ADR-022, taking option
  (c) plus (b): `_handle_success`/`_handle_failure` are each one transaction composed from new
  `_*_locked` cores, and `mitosis sweep` pairs `gateway.GatewayOperationChecker` with
  `gateway.resolve_stranded_calls`. What that choice deliberately leaves on the table is below.
- **Forward recovery for the gateway: record the provider response before applying the
  accounting.** ADR-022 alternative (a), deferred rather than rejected. Rollback loses the one
  thing a crash cannot reconstruct — what the provider actually billed for — so the call resolves
  to `execution_unknown` and waits for a human. Recording the response durably (a `settling`
  status, set in its own transaction the moment `complete()` returns) would let a recovery routine
  finish the settlement automatically from real usage figures. Worth building *with* §24.1 invoice
  reconciliation, which needs the same plumbing; not worth a new status and migration on its own.
- **The `_*_locked` cores are a live footgun.** `reservations._settle_locked`/`_release_locked`/
  `_bare_status_transition_locked`, `resource_metering._record_usage_locked` and
  `ledger._post_transaction_locked` perform no BEGIN and no COMMIT. Called outside a transaction,
  SQLite autocommits each statement and the atomicity ADR-022 bought is silently gone — with no
  test failure, since every invariant still holds. Underscore-private and documented, but a lint
  rule or a runtime `conn.in_transaction` assertion would make it enforceable rather than
  conventional.
- **`sweeper.sweep` is colony-wide and unbatched.** It loads every expired reservation and resolves
  them one transaction at a time. Fine at Phase 4 volumes; revisit before a colony large enough
  that a sweep is a long-running job, since nothing currently bounds or resumes it.
- **Streaming responses** are unsupported; `AnthropicProvider` uses non-streaming `messages.create`.
  Streaming changes the failure model (a partial response is billed), which interacts directly with
  the `execution_unknown` classification.
- **Per-Cell / per-experiment spend caps.** Only global and per-provider caps exist. A Cell's own
  budget is enforced only as "cash on hand", which is coarser than §5's shape suggests.
- **Prompt caching** is not used at all. At Phase 4 volumes with a shared system prompt it is the
  single largest available cost reduction, and it changes the cost model (cache writes cost more,
  reads cost far less) in a way the pricing table cannot currently express.
- **Real-spend type registration is guarded by a test, not by the ledger.**
  `tests/test_real_spend_registration.py` walks the kernel's AST, so it models the shapes the kernel
  uses today: a `transaction_type=` keyword whose value is a literal or a module-level constant, and
  a `book=` that is either `Book.MEMBER` or dynamic. A future call site that computes its type some
  other way is caught only by the "unrecognised expression" guard, which forces a human look rather
  than deciding for itself. The airtight alternative is a runtime check where the transaction is
  written — if `book` is USD_REAL and any entry hits `external_expense`, require a registered type —
  which cannot be bypassed by a novel code shape. It was not built here because the registry lives in
  `real_spend_breaker` and the check belongs in `ledger`, so it needs the tuple moved to a neutral
  module first, and because raising there means a legitimate-but-unregistered transaction fails
  closed in production. That is arguably the *right* failure direction for real money and is worth
  revisiting before sustained real spend.
- **`reservation_settle`'s destination account is dynamic**, taken from the reservation record, so the
  precise static check ("any call site naming `external_expense` must use a registered type") cannot
  see the kernel's single largest real-spend path. It is covered behaviourally instead. A future type
  that also resolves its destination at runtime would likewise be invisible to that check and would
  rest entirely on the classification test forcing a human decision.
- **`test_revenue_does_not_move_the_spend_breaker` is a backstop, not a guard.** It can only fail if
  revenue *both* posts to `external_expense` *and* is registered as a real-spend type; each half
  alone is caught by `tests/test_real_spend_registration.py` instead. That layering is fine, but it
  means the breaker test would go quietly vacuous if the registration guard were ever weakened, and
  nothing currently connects the two.
- **Revenue has no negative counterpart.** A refund, chargeback or clawback is a real commercial
  event and `record_revenue` refuses non-positive amounts outright. The signed-adjustment machinery
  already exists in `reconciliation.py` and is the obvious model, but a Cell whose revenue can be
  clawed back also needs its fitness recomputed, so this waits for fitness to exist.
- **Ollama's `resolved_model` drift is recorded and unused, same as Anthropic's.** A local tag like
  `llama3.2:latest` silently changes what it points at when a user re-pulls, which is §8.4 regime
  change with no watcher — and unlike a hosted API there is no announcement to notice.
- **The pricing table's Ollama entries will drift from what is actually pulled.** Registration is
  deliberate (a wildcard would blind C5 to a paid model behind an Ollama-compatible endpoint), but
  nothing reconciles the registered list against `ollama list`, so a model a Cell wants may simply
  fail. A `mitosis providers --check` that diffs the two would make the friction diagnosable.
- **A local provider's RESOURCE shadow price is caller-supplied, and now it matters more.** With
  Ollama free in USD_REAL, the RESOURCE book is the *only* thing bounding a local Cell — so the
  quality of that shadow price is now load-bearing in a way it never was when USD_REAL caps were the
  real constraint. Reconciling it against real sandbox/GPU logs (Amendment A6's other half) moves up
  in priority the moment Cells run local inference in a loop.
- **`spend_by_book`'s account classification is unenforced at write time.** `unclassified_accounts()`
  fails a test if a *fixed* account is unclassified, but a reservation can settle to any account
  `accounts.is_known_account` accepts — including another Cell's cash. Such a settlement is silently
  non-spend, which is right for a transfer and wrong if it was payment for work. A settle-time
  assertion, or a `spend|transfer` argument on `reservations.settle`, would make the intent explicit
  instead of inferred from the destination.
- **Cell-to-Cell payment has no representation.** Once Cells trade with each other (§31's M2M
  commerce), one Cell's spend is another's revenue, and today the ledger records only a cash
  movement that reads as spend for neither. Fitness across a trading colony needs this before
  internal markets mean anything.
- **The golden run does not cover the spend/capital classification.** Its coroner'd Cell only spends
  to `external_expense`, so misclassifying `infrastructure_reserve` leaves `verify-golden-run`
  passing while `spend_by_book` returns `{}`. Extending the scenario so the *killed* Cell also
  consumes metered resources would close it, at the cost of an A12 expectation migration.
- **Point-estimate predictions cannot be scored by Brier or log.** §8.5 names exactly those two
  rules and both are defined over binary outcomes, so `prediction.py` takes threshold claims
  ("revenue >= 50") rather than "I expect 50". Scoring a *distribution* or point estimate properly
  needs CRPS or an interval score, which the spec does not authorise — a real expressiveness limit
  (a Cell cannot say "about 50, give or take 10"), and it should be a spec amendment rather than an
  implementation choice made quietly.
- **Nothing forces a prediction to be resolved.** `overdue()` and the CLI warning make omission
  visible, but a Cell that never resolves anything simply has no scores. Once selection reads
  calibration, unresolved-past-deadline should probably count as a *failed* prediction rather than
  as no evidence — otherwise the optimal strategy is to predict constantly and resolve nothing.
  That is a policy decision for the selection mechanism, and it belongs with §10.5 death criteria.
- **Predictions are not linked to the spend they are about.** A Cell can register a prediction
  without acting on it, and the register has no notion of "this prediction preceded that model
  call". Two-stage spend (predict cheaply, then act) needs that link to be enforceable rather than
  conventional — an `experiment_id` column exists and is the obvious hook once experiment tracking
  lands.
- **Automatic resolution from ledger state.** Outcomes are supplied by the caller, exactly like an
  invoice figure. Many claims ("revenue >= 50 by epoch 4") are decidable directly from the ledger,
  and resolving those automatically would remove both the manual step and the temptation not to
  take it. Needs a claim grammar rather than free text, which is a bigger commitment than this
  slice should make.
- **§25's promotion ladder does not consume calibration yet.** §25.2 requires reality gap per rung
  and §8.5 says the register feeds the ladder; the ladder does not exist. When it does, the
  consumer wants per-rung scoping, which the current `scores(cell_id)` shape does not offer.
