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
- **`reap` selects nothing on its own.** It must be called, by a human or a scheduler that does not
  exist. That is deliberate for a first slice — death is irreversible — but a colony that only dies
  when someone runs a command is not evolving, and whatever eventually drives it needs a policy for
  cadence (per epoch? per birth attempt?) that §10.5 does not specify.
- **Domination compares only two dimensions.** §10.2's fitness vector names ten (return on committed
  capital, time to settlement, maximum drawdown, refund rate, unsettled liability, human minutes,
  retention, reproducibility, dependency concentration); this kernel can measure net contribution and
  calibration. Pareto domination over a *narrow* vector is more aggressive than over a wide one — a
  Cell dominated on 2 of 2 dimensions might survive on 4 of 10 — so the criterion will get *less*
  eager as more dimensions land, not more. Worth stating because the intuition runs the other way.
- **`budget_exhausted` cannot distinguish "spent it all" from "never funded".** A Cell created and
  never topped up looks identical to one that consumed a full budget. Today both are arguably
  exhausted; once stages exist (§25), "stage budget" is a per-stage allocation and the distinction
  becomes real.
- **Nothing reclaims a dead Cell's residual RESOURCE or USD_SIM balance.** `kill()` never swept
  reservations or reclaimed balances (already logged), and `reap` inherits that: a Cell killed for
  USD_REAL exhaustion may still hold RESOURCE. Harmless while books are separate, but it leaks
  capacity in a colony at carrying capacity.
- **A near-duplicate is currently "same genome hash", which is effectively "same type."** Phase 1
  genome content is a placeholder (ADR-018/019), so every Explorer shares one hash. Once genomes
  carry real strategy content, same-hash becomes *much* narrower and domination will fire far less
  often — the criterion silently changes strength as genomes gain content, which is worth knowing
  before tuning anything against its current behaviour.

## §9.3 displacement slice (2026-08-06)

- **There is no supported way to change a population limit after `init`.**
  `population.set_limits_if_absent` is deliberately write-once and, unlike the real-spend breaker,
  there is no audited raise/lower verb. This bit twice in one slice: the golden run cannot reach
  carrying capacity to exercise displacement, and the CLI test has to write `colony_config` with
  raw SQL. Adding one is not just a setter — lowering a cap below the current population needs a
  policy (refuse? allow and let attrition catch up? displace immediately?), which is exactly the
  question that shouldn't be answered in passing.
- **The golden run does not cover displacement**, for the reason above. It is the only birth path
  replay does not exercise, so a behaviour change there would not move the hash.
- **`reap` has no mid-operation guard.** `displacement.py` refuses to evict a Cell with committed
  funds, because killing it strands an open reservation. `death.reap` has no such check: a Cell
  meeting `dominated_by_near_duplicate` while a call is in flight can be killed and its reservation
  left behind. `_budget_exhausted` already reasons this way for itself, so the gap is only in the
  domination path. Not fixed here because it changes shipped `reap` semantics, which is its own
  slice.
- **A displaced Cell's residual cash is still stranded.** Already logged for `kill()` generally,
  but displacement raises the stakes: the colony now initiates deaths to reclaim *population*
  slots while leaving the capital where it was, at exactly the moment it is at capacity.
- **§9.3's other displacement target is unbuilt.** "Bottom quantile of realised stage progression"
  needs stages (§25) and experiment tracking (Phase 2). Until then displacement selects only on the
  §10.5 half of §9.3's disjunction — more conservative than the spec allows, which is the right
  direction for an irreversible operation.
- **Nothing calls displacement on its own.** Like `reap`, it needs a caller. A colony at capacity
  with a failing Cell and a queued birth will sit there until a human passes `--displace`.

## Agent loop slice (2026-08-06)

- **The loop has never been driven by a real model.** Every deliberation so far has run against
  `MockProvider`, whose reply is an input to the test. Nothing here shows that a real model
  returns schema-valid JSON at a useful rate, and the unparseable path exists precisely because it
  will not always. Ollama was not reachable on this machine when the slice landed; the first real
  run should be a local (free) model, not a paid one, and should measure the parse-failure rate
  before anything is concluded about the loop working.
- **The §15 context budget bounds assembled context, not the whole prompt.** The fixed instruction
  block (mostly the generated schema hint) is ~1,100 tokens against ~280 of assembled context.
  Bounding the growing part is right, but a caller reading `budget_tokens` as a cost ceiling is
  wrong by ~5x. Either fold the system prompt into the budget or rename the parameter.
- **Nothing consumes a proposal, by design — but nothing *reviews* one either.** §23's approval
  queue (risk tiers, SLAs, expiry, cumulative-exposure anti-gaming) does not exist. `risk_tier` is
  recorded and inert. Until there is a queue, "the operator reads it" means `mitosis proposals`.
- **Nothing wakes a Cell on its own.** `enqueue-wake` is manual, the same gap `reap` has. §17.2's
  "scheduled research cycle" implies a scheduler, and the simulated clock (§6) is the natural
  driver — but wiring it needs a cadence policy (per epoch? per Cell? funded how?) that §17 does
  not specify.
- **A proposal's `estimated_cost_minor_units` is never compared with what actually happened.**
  §25.2 wants predicted-vs-observed at each rung; the estimate is stored and nothing scores it.
  Prediction claims are scored (§8.5), the cost estimate is not — an obvious asymmetry to close
  once proposals lead to anything.
- **Context has no memory tiers or compaction (§15.2/§15.3).** Selection is recency-capped and
  budget-bounded, which satisfies "do not load the entire Cell history", but there is no episodic
  summarisation, relevance scoring, or age decay. A long-lived Cell's context does not get *better*
  as it ages, only truncated.
- **Deliberations are not linked to experiments.** `experiment_id` is None everywhere, as it is
  throughout the kernel — experiment tracking is still the Phase 2 prerequisite that also blocks
  two §10.5 death criteria and `max_parallel_experiments`.

## First real-model run (2026-08-06, Ollama/llama3.2)

- **Nothing checks that a prediction's claim is resolvable.** `llama3.2` registered "demand for
  small software automation jobs increases by 20% within 30 days" — a well-formed binary claim that
  no ledger query can settle. §8.5's scoring assumes claims resolve; the schema enforces bounded
  probability and distinct claims but has no notion of *decidability*. A Cell can therefore
  accumulate unresolvable predictions that inflate its `unresolved` count without ever being wrong.
  Related to the already-logged idea of auto-resolving ledger-decidable claims: both want a claim
  grammar rather than free text.
- **The models predict optimistically and nothing yet penalises it.** p=0.7 on "revenue >= 100
  minor units within 30 days" from a Cell with zero revenue and no customers, p=0.8 on a market
  claim. The register will record the miss once resolved, but nothing resolves predictions
  automatically, so the calibration signal only exists if an operator does the resolving.
- **A prompt change silently reprices every wake.** The schema-hint fix moved the golden run's
  deliberation from 1383 to 1450 input tokens. On a paid provider that is a real cost change
  applied colony-wide by editing a string, with no review gate distinguishing it from a typo fix.
  Worth considering whether prompt text belongs under the same versioned-migration discipline as
  the pricing table.
- **`providers._estimate_tokens` over-estimates ~2x on this prompt** (1781 estimated vs 909 actual
  by Anthropic's free `count_tokens`), which is the documented conservative direction but means
  every paid wake over-reserves ~2x. The already-logged `count_tokens` integration would fix it and
  now has a measured figure to justify it.

## First paid deliberation (2026-08-06, claude-haiku-4-5)

- **Thinking costs money and abstaining produces nothing to offset it.** Nine wakes on this Cell
  produced zero experiments, zero spend beyond the calls themselves, and one reasoned refusal to
  act. That is defensible behaviour, but the dynamic is worth naming: a Cell that abstains
  indefinitely drains its budget through deliberation alone and eventually meets §10.5's
  `budget_exhausted`. Whether that is correct selection (it did nothing, so it dies) or a trap (it
  was being epistemically responsible and starved for it) is a real question the colony will face
  as soon as anything wakes Cells on a schedule.
- **Context carries across providers on one Cell, which makes model comparison muddy.** The paid
  model abstained *because of* nine unresolved predictions the local model had registered on the
  same Cell. That is the loop working as designed — history is history regardless of who wrote it
  — but it means "compare model A against model B" needs separate Cells with separate histories,
  or the second model is really being tested on the first one's mess.
- **`estimated_cost_minor_units` was 0 on all eight proposals**, from both models, including for
  proposed experiments. Either the field is being treated as optional-in-spirit despite being
  REQUIRED, or the models genuinely cannot price work in a unit they have no reference for. The
  §15 context shows balances but never shows what anything has historically cost — worth adding
  before treating this field as signal.

## Scheduler slice (2026-08-06)

- **`max_births_per_epoch` is finally checkable and still unchecked.** The epoch primitive was the
  missing prerequisite (§9.2); enforcing it belongs with `lifecycle.create_cell` / `reproduce`
  rather than the scheduler, and needs a decision about what a denied birth does at the epoch
  boundary — wait for the next epoch, or fail like the other population caps?
- **§23's approval queue still does not exist**, so `operator.approval_sla_seconds` (§27.1) times
  nothing and proposals have no review path. The scheduler now generates proposals unattended,
  which makes the missing queue matter more than it did when a human ran every wake.
- **The metabolic alarm only sees spend the scheduler observed.** `epoch_spend_minor_units`
  returns 0 for any epoch no tick ran in, deliberately — but that means real spend a human causes
  by hand between ticks is invisible to the alarm, and could reset a baseline. Acceptable while
  the alarm guards automation specifically; revisit if it is ever presented as a colony-wide
  burn-rate monitor.
- **The baseline is naive.** Mean of up to five recent spending epochs, no seasonality, no
  variance, no minimum sample. Two epochs at 1 and 2 minor units give a baseline of 1.5, so 5
  units is a 3.3x "acceleration" — noisy at small numbers, which is exactly where a new colony
  lives. A median plus a minimum-absolute-delta floor would be a cheap improvement.
- **Nothing runs the scheduler.** `tick` is a command, composable with cron, per §30.1's
  "avoid unnecessary frameworks". A colony still needs someone to install the crontab, and there
  is no supervision, no restart-on-failure, and no alerting when ticks stop happening.
- **Vacation mode has no notification path.** §23.3's "overdue items surface distinctly" has
  nowhere to surface to. The colony pauses external work silently and waits.

## From the §23 approval-queue slice (2026-08-22, ADR-027)

- **`batchable`'s `not self.signals` clause is currently unreachable through the real path.** Four
  of the five §23.4 signals escalate the assessed tier, and the fifth (`understated_risk`) can only
  fire in situations where the kernel tier is already above LOW — so a signalled item never arrives
  at `batchable` still LOW. Kept as the lock that becomes load-bearing if the escalation rules are
  ever loosened, and `test_a_gaming_signal_forces_individual_review` now asserts both mechanisms
  separately so neither can quietly answer for the other. Revisit if the escalation set changes.
- **Exposure is summed from the Cell's own `estimated_cost_minor_units`**, which is a claim. The
  aggregate defeats *splitting* but not systematic under-estimation; only a zero on a spend request
  is currently caught. A cross-check against what similar approved requests actually cost would
  need realised spend attributable to a proposal, which nothing produces yet.
- **A Cell quarantined *after* enqueue does not re-escalate its pending requests.** The assessment
  is made at enqueue time. Mitigated by the payload showing the Cell's *current* status, so the
  operator sees it — but a sweep that re-assessed pending items on a status change would be
  stricter.
- **`repeat_after_rejection` matches on an exactly-normalised summary.** Casefold, strip
  punctuation, collapse whitespace — enough to defeat re-punctuation, and deliberately no more,
  because a fuzzy matcher would start flagging genuinely new requests and a false positive is a
  signal operators learn to ignore. Semantic similarity is a real improvement and a real risk.
- **The rolling exposure window is wall time, not simulated time.** Correct here — every clock in
  the queue measures a *human* (SLA, vacation, staleness) — but it means an accelerated colony
  generates proposals far faster than the window ages, so exposure could accumulate across what the
  colony experiences as a very long period. Worth revisiting when the flight simulator runs at
  speed.
- **Nothing expires approvals automatically.** `mitosis expire-approvals` is a command, like
  `sweep` and `reap`. The scheduler's tick is the obvious place to call it, and deliberately did
  not this slice — expiry regenerates wakes, and a tick that both expires and wakes needs a stated
  ordering policy.
- **`events._enqueue_locked` now exists** (extracted so an expiry and its regeneration wake commit
  together). Second caller welcome; the wrapper's dedupe pre-check and IntegrityError translation
  deliberately stay in `enqueue`, since a ROLLBACK inside a caller's transaction would discard
  their work.

## From the estate slice (2026-08-22, ADR-028)

- **An estate is only as complete as the sweeper is timely.** A dead Cell with an in-flight
  external operation holds committed funds until `mitosis sweep` runs, and nothing runs sweep on a
  schedule — same gap `tick` has. `lifecycle.outstanding_estates()` makes the backlog visible; an
  alert when it stops shrinking would make it actionable.
- **`_open_reservations` treats `requested` as open, but `request()` goes straight to `reserved`,**
  so that status is currently unreachable. If it ever becomes reachable, note that
  `reservations._release_locked` does not accept `requested -> released` and the estate would raise
  rather than skip. Worth a decision then, not now.
- **A dead Cell's negative cash balance is left permanently negative** (ADR-021 overruns). It is
  honest — the debt happened — but it means colony-wide cash totals carry the shortfall of every
  Cell that ever overran, with no write-off path. §13's liability reserve is the natural home.
- **The estate has no per-book policy.** Everything goes to `colony_treasury`, including RESOURCE.
  Returning RESOURCE to a treasury is defensible (it is the colony's compute allowance coming back)
  but it is not the same act as returning USD_SIM, and a future `infrastructure_reserve` return
  path may want to distinguish them.
- **Hypothesis deadlines and migration count are now coupled.** Every property test that calls
  `db.connect_and_migrate()` inside an example pays the full schema cost per example. `deadline=None`
  is applied across `test_charter_properties.py`, but the underlying cost keeps growing — a
  session-scoped migrated template database that tests copy would fix the cause rather than the
  symptom.

## From the rung-7 promotion slice (2026-08-22, ADR-029)

- **Nothing closes the loop back onto rung 8.** `promotions` records the reality gap and prediction
  counts *at* allocation; the outcome arrives later through the hash-chained register and nothing
  reads it. Until something does, "we are climbing §25.1's ladder" is an assertion rather than a
  measurement, and `transfer_degradation` will stay NULL for every Cell forever because it needs a
  second promotion that no criterion triggers.
- **The promotion pool has no refill policy and no low-balance warning.** It silently stops
  allocating when empty, which reads identically to "no grants were approved". `mitosis allocations`
  prints the balance; an alert when it cannot cover the pending approved grants would be better.
- **An allocation cannot be reversed.** If an operator allocates by mistake, the capital is on the
  Cell and the only paths back are the Cell spending it or dying (ADR-028's estate). A clawback
  would need §3.6-shaped handling — a new signed transaction, never an edit — and a policy on
  whether a Cell can be left with negative cash.
- **`promotion.allocate` reads `estimated_cost_minor_units` from the proposal, not from the grant
  row.** Equivalent today because a proposal is immutable, and the grant does freeze the exposure
  figure — but if proposals ever become editable the two diverge and the grant is the one the
  operator saw. Worth moving the amount onto the grant at that point.
- **Rung 7 is recorded but never checked as a precondition.** Nothing verifies a Cell passed rungs
  1–6 before being allocated at 7; the ladder is documented in the `rung` column rather than
  enforced by it. §25.1 describes a sequence, and a real gate would refuse a rung-7 promotion for a
  Cell with no rung-6 history.


## From the §25.2 read-back slice (2026-08-22, ADR-030)

- **`MIN_RESOLVED_FOR_A_VERDICT = 3` is a stand-in for a confidence interval.** The honest
  instrument for "is this score distinguishable from luck" is a CI on the mean Brier, which §8.5
  does not authorise and which would need a bootstrap or a beta-binomial the kernel has no other
  use for. §27.1's own phase-3 metric is "pre-registered selection effect size (CI excludes 0)", so
  the machinery is wanted eventually anyway. Until then the constant only ever *withholds* a
  verdict, which is the safe direction for an arbitrary number to be wrong in.
- **There is no `assessments` table, deliberately.** The read-back is recomputed from the register
  and the ledger every time, the posture Charter C3 takes toward balances. It becomes worth storing
  when a *decision* consumes one — at that point "what was known when we decided" is itself a fact,
  and a derived value recomputed later would answer a different question.
- **Should a Cell see its own verdict?** §15 context shows a Cell facts about itself; the
  assessment is the kernel's judgement *of* it, and §23.5 says a Cell will optimise against
  anything it can see. Kept out for now. The argument for letting it in is real though — a Cell
  told "your funded forecasts came in worse than the record that funded you" could correct, and
  nothing else in the colony gives it that signal.
- **`audit_events` has no actor column**, so §25.2's "human intervention" is a by-event-type
  classification (`outcome.HUMAN_INTERVENTION_EVENTS`) rather than a count of what people actually
  did. `cell_lifecycle_transition` had to be excluded entirely because the row does not say whether
  an operator or the kernel caused it. An actor column would make the figure exact and would feed
  §27.1's phase-8 "human minutes/artifact" metric properly.
- **Rung 8 itself.** A verdict of `supports_promotion` is read by nobody
  (`test_no_kernel_path_acts_on_an_assessment`). Rung 8 is "expanded pilot", which means removing
  one of the two humans standing in every allocation — its own argued step, and the test is there
  to make taking it cost an explicit edit.
- **The read-back cannot see stage progression.** §25.2 wants outcomes per rung and the coroner
  report's `stage_reached` is still always None; both need experiment tracking (Phase 2). Today the
  assessment judges calibration and reports cost, which is everything the kernel can currently
  observe about whether an allocation worked.
- **Nothing re-assesses on a schedule.** An `evidence_withheld` verdict stays withheld until
  someone runs `mitosis assess` again, and nothing tells an operator that a promotion's forecasts
  have just come due. The scheduler is the obvious home and is deliberately not wired to it.

## From the §9.2 birth-rate slice (2026-08-22, ADR-031)

- **A refused birth is lost, not deferred.** §9.3's word is "waits", and a synchronous kernel call
  cannot — so `BirthRateExceededError` is raised and the caller has to come back. A real birth queue
  would implement waiting properly, and would matter most for the reproduction path, where the
  parent has already decided to reproduce and simply gets told no. Note the queue itself would then
  be §23.5-shaped: a Cell that learns births are queued has an incentive to ask early and often.
- **The cap applies to operator-created founders too.** §9.2 says "births" without qualification and
  `max_living_cells` already binds an operator, so uniform is the reading taken. But §9.1's
  rationale is about *reproduction* growing exponentially, and an operator seeding a colony by hand
  is not that. If seeding a large colony ever becomes awkward, exempting the founder path is the
  defensible change — with the exemption stated, not silent.
- **`max_parallel_experiments` is now the only §9.2 limit still stored and unchecked.** Its
  prerequisite is experiment tracking (Phase 2), the same thing blocking the coroner report's
  `stage_reached` and the §25.2 read-back's stage progression.
- **Nothing warns as the cap approaches.** `mitosis scheduler-status` prints births-this-epoch, but
  an unattended colony hits the wall without notice and the refusal only appears in whatever tried
  to give birth. The metabolic alarm's shape — watch the derivative, warn before the cap — applies
  here too.
- **`epoch_config` unanchored means the cap acts as a lifetime total.** `mitosis init` anchors epoch
  zero, so this only bites a colony driven straight through the kernel. The fallback errs toward
  restriction deliberately, and the refusal says so, but a colony that cannot anchor epochs after
  the fact has no way out except raising the limit — `configure_epochs_if_absent` is write-once by
  design and lowering or re-anchoring a genesis would renumber history.
- **Population limits are still write-once** (`set_limits_if_absent`), which now bites harder: the
  birth cap is the limit most likely to need tuning as a colony grows, and there is no audited path
  to change it. This was already logged for the carrying-capacity caps and the birth cap joins it.

## From the §23.2 Auditor slice (2026-08-22, ADR-032)

- **§8.5's register has one namespace, and an Auditor now puts two kinds of claim in it.** A Cell's
  forecasts about its own work and the flags it raises about *other* Cells' requests are
  indistinguishable in `prediction_register`. Found in the golden run: a naive "resolve everything
  this Cell predicted" folded an audit of the explorer into the §25.2 read-back of the auditor's own
  funding. Scoped around for now by filtering on the claim text, which is not a real fix. A `kind`
  column, or scoping audit flags through `experiment_id`, would separate them — and §25.2's read-back
  should probably judge a Cell on its self-forecasts while §10.4 judges it on its flags.
- **Governance overhead ratio (§10.4's second half) is now computable and unbuilt.** "(audit +
  immune + approval spend) / total spend against a configured target band. An immune system that
  consumes the organism is its own failure mode." Auditing costs a model call as of this slice, so
  the numerator is finally non-zero — `audits.model_call_id` links every audit to its cost precisely
  so this can be built without re-deriving it.
- **Nothing requires an audit.** §23.2 lists the Auditor summary among the payload's fields, and an
  unaudited request still approves. Making one mandatory for HIGH/CRITICAL tiers is the obvious next
  step and is deliberately not taken here: it would make the Auditor a gate, and §10.4 penalises
  "unnecessary blocking". The honest version needs a policy on what happens when no eligible Auditor
  exists — which, on a small colony, is often.
- **Nothing schedules an audit.** `WAKE_AUDIT_REQUEST` is stamped for provenance but never emitted;
  audits are operator-invoked because an audit spends money. Auto-enqueuing needs a stated policy for
  *which* Auditor reviews *which* request — and that policy is itself §23.5-shaped, since a Cell that
  learns how reviewers are assigned has an incentive to shape its requests around it.
- **§10.4 says reward, and nothing pays.** `auditor.precision` measures precision-weighted
  performance; no capital or credit flows from it. §11's negative-finding credit path is where that
  belongs, and it would also give `flags_vindicated` an economic meaning rather than a reported one.
- **`death.kill_for_negative_ev` takes a concurring auditor that need never have audited anything.**
  The two paths both now exist and are unconnected: §10.5's concurrence check validates a Cell's
  type and identity, not its record. Requiring a concurring Auditor to have a calibration record —
  or refusing one whose flags are mostly wrongful — is the natural link.
- **`mitosis audit --provider mock` always rejects**, because `MockProvider`'s default reply is not
  audit-shaped and the CLI has no flag to set it. §7.3 wants the mock to be "a first-class component"
  with configurable responses; today the reply is a constructor argument no CLI verb exposes. The
  same is true of `mitosis wake --provider mock`, so this is a pre-existing gap the audit verb has
  now made visible twice.
- **An Auditor is briefed from `approval.payload`, which does not include §25.2's read-back.** The
  Auditor is the one legitimate consumer of `outcome.assess` — it is exactly the independent
  evaluator §10.5 wants — but reading it means loosening
  `test_no_kernel_path_acts_on_an_assessment`. That is an argued step, not a convenience, and it
  should be taken deliberately or not at all.
- **The README pins numbers that go stale every slice** — test count, migration count, expectation
  version. They were accurate when written and drifted twice within the same session (671 → 696).
  Either derive them at build time, or soften them to ranges. A README that is confidently wrong
  about its own test count undermines the more important claims next to it.

- **§16.3's liability-linked inheritance class is unenforced.** Revenue-producing assets may not
  transfer without their refund liabilities and service obligations, and the v0.1 field set
  deliberately carries no field denoting such an asset — so nothing can currently escape, but
  nothing is checked either. Lands with whatever first provisions `liability_reserve`.
- **`prompt_hashes`, `module_hashes` and `model_policy_hash` are still written as empty/NULL.**
  §16.2 names them and `cell_genomes` has the columns; §14.3's prompt provenance (prompt hash,
  parent prompt hashes, mutation operator, evaluation seeds, cost, performance) is the natural
  first consumer, and it needs prompts to be genome content rather than kernel constants.
- **Nothing mutates a genome automatically.** §14.1 lists the operators — instruction-order, role
  decomposition, critic add/remove, plus the economic ones (customer, problem, channel, pricing,
  revenue-model, cross-domain transplant) — and every mutation today is an operator typing
  `--mutation`. Automating them is where new business ideas actually come from, and it needs §14.2's
  counterfactual twins to evaluate one against its parent rather than promoting on preference.
- **MAP-Elites descriptors now have something to describe.** §12's behavioural descriptors were
  unbuildable while genomes were placeholders; `market`/`revenue_model`/`acquisition_channel` are
  the obvious axes for quality-diversity search, and `genome_hash` is already the archive key §16.1
  names.
- **`allowed_tools` is a request against an empty registry.** Nothing enumerates what tools exist,
  so a genome can request `send_email` and the kernel has no way to say the tool is unknown rather
  than merely ungranted. A tool registry would let the request be validated instead of only recorded.

- **Charter C13 (`charter_taint_quarantine`) is now the only clause with no test.** §18.2's rule is
  that adversarial-lineage artifacts may never reach real-facing environments, and the taint
  *labels* now exist (`tool_calls.taint_label`, `cell_genomes.taint_labels`) with a real-facing
  surface to protect. What is still missing is any notion of an adversarial lineage — the shadow
  economy is Phase 6 — so the clause stays untestable rather than untested. Worth revisiting the
  moment SIM_ADVERSARIAL is producible.
- **Taint propagates exactly one step.** A proposal made from a context containing
  UNTRUSTED_EXTERNAL content is flagged; a proposal made from *that* proposal is not. Full
  information-flow taint (§18.5's "formal taint propagation", "provenance lattices") is the real
  answer and is a large slice; the one-step flag is what §23.2's reviewer actually needs today.
- **Nothing schedules a tool call.** `WAKE_TOOL_RESULT` is emitted, but every execution is
  operator-invoked because a fetch reaches outside the colony. Auto-execution of approved grants is
  the obvious next step and is deliberately not taken: it removes the second human from rung 4 and
  would need a stated policy on what happens when a grant is approved and the operator is away
  (§23.3's vacation mode is the existing precedent).
- **`allowed_tools` is now checkable but still unchecked at proposal time.** `tools.validate_request`
  can say whether a tool exists, and a genome's `allowed_tools` list is still purely a request that
  nothing compares against the registry or against what was granted. Wiring it would let a Cell be
  told at deliberation time that it is asking for something it will never get.
- **The response cap is a blunt truncation.** `MAX_RESULT_BYTES` cuts mid-document, so a Cell may
  reason from half a price list without knowing it. Recording a `truncated` flag, or summarising
  server-side before the result enters context, would make the loss visible to the Cell rather than
  silent.
- **`run-tool --live` has never been pointed at a real host.** The redirect refusal, robots.txt
  handling and size cap are unit-tested against fakes; the actual socket path is not. One real
  fetch against a public page is the cheapest way to find out what the fetcher gets wrong.
- **§20.1's rights metadata is recorded and nothing consumes it.** Every result carries
  licence/permitted_uses/commercial_use, all `unknown` from a web fetch. Nothing refuses to reuse
  content whose commercial_use is not `permitted`, which is the check the columns exist for and
  which matters the first time a Cell's output is sold.
- **RESOLVED 2026-08-23 — "`run-tool --live` has never been pointed at a real host" (above).** It has
  now: `https://example.com/`, HTTP 200, 559 bytes, full provenance recorded, accounting green. The
  redirect refusal and the size cap were both exercised against real responses rather than fakes,
  and the redirect guard fired on a genuine 301. Left in place rather than deleted because this file
  is append-only and the original entry records why the gap mattered.

- **§11.2's five-condition downstream credit is unbuilt, and needs experiment tracking.** A reusable
  artifact earns credit only when another Cell independently uses it, the adopting run passes
  verification, the adopter shows stage progression or measurable improvement, the adoption is not
  reciprocal farming, and the causal contribution is recorded. Conditions 2 and 3 both need
  experiments, which still do not exist. `artifact_lineage` holds the edges the credit would flow
  along, so the graph is ready before the accounting is.
- **§11.4's decay is unbuilt.** "Award credit when downstream value appears, with **decay** to avoid
  permanent ancestral rent extraction." Without it, the first Cell to write anything reused would
  collect forever — which is the failure the clause names. Lands with the credit path.
- **Nothing delivers an exported artifact.** `artifacts.export` records that a human took one
  outside the colony; there is no channel, by design (§28 Phase 8: "all external action remains
  manual"). Delivery needs §21.2's external-action registry first — a Cell that can put something in
  front of a customer is spending the colony's one shared reputation (§21.1).
- **An artifact's rights can only get more restrictive, never less.** There is no path to
  *establish* rights — an operator who confirms a source is CC-BY cannot record that, so an artifact
  built on it stays `unknown` forever and can never be sold. A `set-rights` verb with an audit trail
  is the obvious complement to the export gate and was left out to keep this slice to one direction.
- **`retention_rule` and `permitted_uses` are recorded and nothing enforces them.** §20.1 asks for
  "retention rule" and "deletion/correction requirements"; the columns hold prose that no code
  reads. Enforcement needs a scheduler that can expire artifacts, and a stated policy on what
  happens to a lineage whose ancestor must be deleted.
- **The artifact index is capped at 5 with no relevance ordering.** §15.3 asks for "relevance
  scoring, age decay, retrieval by experiment/market" — the index is newest-first and nothing more,
  so a Cell with many artifacts loses sight of the ones that matter. Same shape as the
  `RECENT_PROPOSALS` cap and the same eventual fix.

- **The spec reserves sockets years before anything fills them, and four were found this session
  alone.** `liability_reserve` (a §31 Phase-1 account, classified in `accounts.py`, nothing posts
  to it), `ledger_entries.artifact_id` (Amendment A3, present since migration 0001, populated for
  the first time by ADR-035), `ResourceType.HUMAN_MINUTES` (declared in `models.py`, still unused),
  and §27.1's four autonomy flags (built as gates in ADR-034 with nothing behind three of them).
  Earlier ones: `promotion_pool` and §17.2's wake reasons. **Grep for the socket before designing
  the subsystem** — twice this session the "missing" thing was half-built already, and once
  (`liability_reserve`) a PRIORITIES entry had been wrong about it for weeks.

- **The salt lives beside the hashes, and that bound is worth restating rather than forgetting.**
  `counterparty_salt` is a row in the same database as `external_action_registry`, so hashing does
  not protect a counterparty from someone who holds the file and has a particular person in mind.
  What it buys is that the *colony* cannot enumerate its contacts — no Cell, Auditor, inherited
  genome, coroner report or idle table read produces a list of people. A colony that ever needs the
  stronger property wants the salt outside the database (an env var, a keyring), which trades a
  real guarantee for an operational failure mode: lose the salt and the do-not-contact list
  silently empties, with no error anywhere.
- **No `set-rights` complement, still.** ADR-035 noted an artifact's rights can only get more
  restrictive; delivery makes that bite harder, because an artifact built on a fetched page is
  `commercial_use: unknown` forever and can therefore never be exported commercially — so the
  channel can carry it to a person but never sell it. The gap is the same one; the cost is now
  visible at the end of the pipeline rather than in the middle.
- **A claim held before acting is a lock, and nothing sweeps it.** `abandon` is the only release,
  and it is manual. A claim whose operator walks away holds its counterparty and a channel quota
  slot until someone notices — the reservation expires after 8 hours and the sweeper reclaims *it*,
  but the registry row stays `claimed` forever. The obvious complement is expiring a claim the way
  §23.3 expires an approval (regenerate rather than drop), and it was left out because the policy
  question — does an expired claim free the counterparty, given that the person may in fact have
  sent something — deserves an argument rather than a default.
- **There is no unblock, deliberately, and no way to record a person asking to be contacted again.**
  §21.1's damage is not the colony's to undo, so `counterparty_blocks` has no delete path. That is
  right for a complaint and possibly wrong for a `blocked` outcome that later gets resolved out of
  band. Whatever fills it has to be a §3.6-shaped signed act, not a DELETE.
- **`external_publish` gates two registered channels and no decision.** `marketplace_listing` and
  `web_publish` exist in the registry with caps and refusals; §0.4 grants autonomy capability by
  capability and nobody has argued for either. Registering a channel is cheap and turning the flag
  on is not — keep those two facts separated.
- **§21.2's "spend" was cut rather than stubbed.** The clause lists spend among what a registry
  tracks; a `spend_minor_units` column that never moves the ledger is a fiction, and one that does
  belongs in the existing `spend_request` path with its breaker and its books. Phase 9's merchant
  channel is where external spend becomes real, and that is where the link belongs.
- **Reputation is recorded and never scored, and the counting is one-directional.** `outcome` is a
  closed set of observations, and nothing aggregates them into a per-channel or per-lineage health
  number. That was deliberate — a score nothing can validate is theatre — but it means a lineage
  with a poor record carries no cost until it produces an actual complaint. Real feedback (bounce
  rates, reply rates over a real volume) is what would make a score honest, and none exists yet.
- **`human_minutes` is now measured for external actions only.** Phase 8's North Star is "human
  minutes/artifact" and the denominator is complete, but the numerator counts only the minutes a
  person spent *acting outside the colony*. Approving a §23 request, resolving a prediction and
  disputing a charge are all real human minutes that `outcome.py` still counts as *events*. Wiring
  those to the same meter is the rest of the metric.
- **A ceiling that reads as prudent can be an off switch, and only the golden run could see it.**
  The first draft reserved a theoretical worst case of 240 human minutes per action, which cost
  more RESOURCE than a Cell actually holds — every unit fixture funds generously enough to hide it,
  and the fixed scenario funds like a real colony. Worth remembering the next time a cap is chosen
  from first principles rather than from a real balance.
- **`test_no_registered_tool_acts_on_the_world`'s message is now stale.** It says an acting tool
  "needs §21.2's external-action registry before it needs a registry entry" — the registry now
  exists (ADR-036), so the message reads as though the prerequisite is satisfied and an acting tool
  would be fine. It would not: a *tool* that acts is rung 8-9 automation, whereas an external action
  is performed by a person and the kernel only records it. The assertion is still correct; only its
  explanation misleads, which is the kind of stale rationale someone eventually acts on.

## From the `external_publish` decision (2026-08-23, ADR-037)

- **A flag can be wrong in a way that only shows up when someone tries to use it.** `external_publish`
  looked settled for two slices — it had a column, a CLI switch, two registered channels and a
  default of false. What it did not have was the *granularity* §0.4 requires, and nothing surfaced
  that until the decision to enable it was actually attempted. The tell was available the whole
  time: it was the only flag in `_AUTONOMY_COLUMNS` that more than one capability named.
  `test_no_autonomy_flag_gates_more_than_one_capability` now makes that structural, but the general
  shape — a gate nobody has tried to open is a gate nobody has checked — has no test.
- **§0.4's six prohibitions still map onto five and a half keys.** With `real_commerce` added, the
  list is: network-from-generated-code (`sandbox.network_default` plus `public_web_read`), real
  commerce (`real_commerce`), external communication (`external_message`), real payments
  (`real_spending`), public publishing (`external_publish`), direct secret access (**no flag** —
  carried by Charter C14 and the provider key handling, which is defensible, but it means the
  §27.1 block is not a complete index of §0.4 and should not be read as one).
- **`real_commerce` can be opened and still sell nothing.** §20.2 requires
  `commercial_use == permitted` for commercial export, anything derived from a fetched page is
  `unknown` by construction, and there is still no `set-rights` path — now flagged for the third
  slice running (ADR-035, ADR-036, ADR-037). The publish path is where it finally bites at the end
  of the pipeline rather than in the middle: the flag would be on, the channel open, and every
  listing refused at the export gate. Whatever fills it needs an audit trail and an operator
  attestation, not a column write.
- **The sibling check now spans channels and the duplicate check does not, and the asymmetry is
  load-bearing.** Two lineages on one domain contradict each other whichever channels they used;
  the same content going out two different ways is two normal actions. Both directions were wrong
  in a draft and each was caught by a different case — worth remembering that "scope it the same
  way as the neighbouring query" is not a safe default here.
- **A claim held before acting is still a lock, and nothing sweeps it — now on two more channels.**
  ADR-036 flagged this for `email`; `web_publish` and `marketplace_listing` inherit it, and a
  stranded publish claim holds a *domain* rather than one person, which is a broader lock. The open
  policy question is unchanged and now costs more: does an expired claim free its target, given the
  person may in fact have published?
- **Nothing distinguishes a colony domain from anyone else's.** `web_publish`'s description says "a
  colony domain", and the kernel accepts whatever string the operator types. There is no registry
  of domains the colony actually controls, so nothing stops a publish claim naming a domain the
  colony has no account on — the §21.2 collision checks would work perfectly against a fiction.
  `egress_allowlist` is the nearest existing thing and is about reading, not publishing.
- **`platform_account` is a bare string with no registry behind it either.** §21.1's shared assets
  include "marketplace account", and nothing says which accounts the colony actually holds — the
  same gap as the domain above. *(The narrower half of this — two operators typing
  `colony-merchant` and `Colony-Merchant` colliding on nothing — was found while writing this note
  and fixed rather than parked: `normalise_target` applies the same strip-and-casefold that
  `counterparty_hash` applies, on write as well as on read. The first draft normalised only for the
  query while the claim wrote the raw string, so every later check looked for a value the row did
  not contain. Worth remembering that a normalisation is two changes, not one.)*

## From the `browser_control` decision (2026-08-23, ADR-038)

- **A reserved flag can name two capabilities and the spec never disambiguate.** `external_publish`
  was one key over two *registered* capabilities; `browser_control` is one key over none, with two
  readings — §28 Phase 7's "read-only browser" and rung 8–9 actuation — and the flag's *name*
  points at the reading the spec never asks for. ADR-038 assigned it the renderer. The general
  lesson is that "the flag ships false" hides an unanswered question about what the flag is *for*,
  and the answer is cheapest to write down while nothing depends on it.
- **A disproof pointer can point the wrong way.** PRIORITIES' convention is that a blocker names
  what would settle it, and this entry's pointer — "any tool declaring `browser_control`" — named
  the *bug* rather than the resolution: a tool declaring the flag before a sandbox exists is
  precisely what the entry should prevent. **The sweep was done and found one more.** "Nothing
  schedules a tool call" points at *"the scheduler reaching `tools.execute_grant`"* — a state
  `test_nothing_in_the_deliberation_path_executes_a_tool` explicitly forbids, since §19.4's
  injection isolation is why `scheduler.py` may not import `tools` at all. So either that entry is
  asking for ADR-034's guard to be overturned (a large argued change, not a backlog item) or its
  real resolution is something else — most likely a vacation-mode policy for grants that expire
  while nobody is there, which needs no scheduler-side execution. **Resolved the same day:** the
  entry was retitled "nothing handles the operator being away" and repointed at
  `approval.expire_due`. Two concrete gaps turned up while doing it — an unconsumed grant expires
  and nothing regenerates it, though both executors carry a comment promising that it does, and
  `expire_due` has exactly one caller (`mitosis expire-approvals`), so the machinery built for an
  absent operator only runs when the operator is present. The other seven pointers name symbols or
  commands and are sound.
- **§19.3's controls are a list of thirteen and roughly one is implemented.** "No host filesystem;
  no raw secrets; no privileged execution; no Docker socket; CPU/memory/runtime/disk limits;
  network disabled by default; egress domain allowlist; DNS control; stdout/stderr capture;
  artifact-export gateway; dependency allowlist; package hashes; lockfiles; SBOM; malware scanning;
  licence scanning; signed artifacts; reproducible build metadata." The colony has the egress
  allowlist, the export gateway and network-disabled-by-default. Charter C12's filesystem and
  secret halves have been deferred as a named gap since ADR-034, and every later slice has been
  able to stay clear of them because nothing executes. **A renderer is the first thing that would
  not stay clear**, which is the honest reason a sandbox slice has to come before it.
- **`ResourceType.BROWSER_MINUTES` is the tenth reserved socket** — §2.2's RESOURCE list, declared
  in `models.py` since migration 0008, referenced by nothing. Same state `HUMAN_MINUTES` was in
  before ADR-036. It says the shape the capability was meant to have: a metered, bounded,
  long-running session rather than a fetch, which matters because RESOURCE metering is the only
  bound left when USD_REAL is free.
- **A renderer registered under `public_web_read` is the likelier mistake than one declaring
  `browser_control`**, and it is structurally indistinguishable from `http_get` at the registry
  level — same flag, same `read_only=True`, same `egress_argument`. `test_nothing_in_the_kernel_
  can_drive_a_browser` catches the engine import instead, which is the part that *is* detectable.
  Anything that renders without importing a known driver — a headless service reached over HTTP,
  say — defeats both guards, and that is a real hole rather than a hypothetical one: a
  render-as-a-service fetch would look exactly like an ordinary `http_get` to an allowlisted host.
- **Every §27.1 flag now has an argued position, so the next one is a new key rather than a
  backlog item.** `public_web_read` open (ADR-034), `external_message` open (ADR-036),
  `external_publish` / `real_commerce` shut with reasons (ADR-037), `real_spending` shut since §5,
  `browser_control` shut (ADR-038). §0.4's "no direct secret access" still has no key at all —
  carried by Charter C14 and the provider key handling — which is defensible but means §27.1's
  block is not a complete index of §0.4.

## From the grant-regeneration slice (2026-08-23, ADR-039)

- **Both expiry sweeps still have exactly one caller, and that is now the whole of the gap.**
  `expire_due` and `expire_grants_due` are only reached by `mitosis expire-approvals`. The
  machinery built for an absent operator runs only when the operator is present, which is the
  §23.3 irony the entry was originally about. Wiring it into `tick` is small, but it is a
  *vacation-mode* decision rather than an expiry one — it changes what the colony does with nobody
  watching, and the sweep enqueues wakes that a later tick may spend a Cell's budget on. It wants
  an argument, not a quiet addition.
- **A grant expiry can strand a claim, and the two clocks are not connected.** `external_actions`
  claims hold a RESOURCE reservation with an 8-hour TTL; a grant's window is SLA-derived and much
  longer. Nothing yet reasons about a Cell whose grant expired *while* a person was mid-claim —
  the claim consumed the grant, so the sweep will not touch it, which is correct, but there is no
  path that regenerates an action abandoned after the grant window closed. ADR-036's parked
  question about expiring stale claims is the same question from the other side.
- **The regeneration loop is bounded only by budget, and nothing counts it.** Propose → approve →
  lapse → propose is bounded by Charter C4/C5 and the metabolic alarm, which is the right answer
  and deliberately not a special-case cap. But nothing records *how many times* one action has
  been regenerated, so a Cell burning its budget re-proposing the same lapsed request looks
  identical to one doing fresh work. A `regeneration_count` on the proposal lineage would make it
  visible without capping it — and §10.5's coroner report is where it would matter, since "died
  re-proposing the same thing eleven times" is a cause of death worth naming.
- **`RequestStatus.EXPIRED` means "expired unreviewed", and that is now load-bearing.** ADR-039
  leaned on it to justify leaving a granted request APPROVED. Anything that later widens that
  status — an operator-cancelled request, say — has to keep the distinction or the queue statistics
  silently merge two different operator behaviours.
- **The golden run's grant assertion is a count invariant, and counts are weak against renaming.**
  `total` unchanged proves no grant was minted *into `approval_grants`*. A kernel that renewed by
  writing somewhere else entirely would pass. The unit test is the real guard; the golden run is
  the regression net.

## From wiring the sweeps into `tick` (2026-08-23, ADR-040)

- **"Runs before the guards" is a category a reader has to be told about.** Everything else in
  `tick` is gated because it *does* something; the sweep is ungated because it *undoes* something.
  Nothing in the code expresses that category — it is a comment and two tests. If a third
  ungated-by-design step ever appears, it wants a name (a `_withdrawals()` phase, say) rather than
  a third comment explaining the same distinction.
- **Regenerated wakes escape `max_cells`.** That flag caps the scheduled research wakes only;
  `run_ready_wakes` drains whatever is ready, so a tick following a large expiry burst deliberates
  more than the operator asked for. Bounded by the money guards and deliberately not capped
  locally, but an operator who passes `--max-cells 1` expecting one model call may get several.
  Worth either honouring the cap across the whole drain or renaming the flag.
- **The metabolic alarm is hard to reach on a scratch colony**, which made the halted-tick path
  awkward to verify by hand: a spend large enough to trip the per-epoch alarm (50c) also trips the
  hourly real-spend breaker (100c) once cumulative, and the breaker raises rather than halting, so
  the colony wedges instead of halting cleanly. The test suite reaches the halt through the paid
  provider gate instead. A `mitosis raise-alarm --reason` operator verb — the deliberate
  counterpart to `acknowledge-metabolic-alarm`, which already exists — would make the halted paths
  testable by hand and is the kind of thing a chaos drill (§28 Phase 2) will want anyway.
- **§23.3 is now fully built** — SLAs, expiry on both clocks, regeneration on both, vacation mode,
  metabolic alarm. Worth noting because it is the first clause in this spec to be finished
  end to end, and the shape of how it got there is instructive: ADR-027 built the visible half,
  ADR-039 found the invisible half by chasing a stale comment, and ADR-040 found that both halves
  only ran when a person asked. None of the three gaps were visible from the clause alone.

## From `set-rights` (2026-08-24, ADR-041)

- **The three "no `set-rights` complement" entries above are now closed** — one flagged at ADR-035,
  one at ADR-036, one at ADR-037, each stating the same gap from a point further down the pipeline.
  Worth recording that the *third* statement is the one that made it urgent, because it reached the
  end: "the flag would be on, the channel open, and every listing refused at the export gate." The
  entries stay above (this file is append-only); this line is the resolution.
- **The colony half was never in any of them.** All three described artifacts derived from fetched
  pages. A report the colony wrote unaided was equally unsellable — `inherit_provenance` starts it
  at `unknown` on purpose — and no domain attestation can reach it. Found by reading the fold
  rather than the entry, which is the argument for reading the code that the entry describes.
- **A rights position is site-wide, and some sites are not.** `github.com`, a marketplace, any
  user-content host: one licence per page, and a domain attestation is the wrong granularity for
  them. The kernel refuses `permitted` without a named licence and records a basis, and that is all
  it can check — the operator is trusted for the rest. **A URL-prefix subject** (`https://example.
  com/docs/`, longest-prefix-wins) is the additive refinement, and the `subject_kind` discriminator
  exists so it needs no schema break. It was left out because prefix normalisation (trailing slash,
  scheme, case, query) is its own rabbit hole and no case demanded it yet.
- **An attestation cannot say "this source contains personal data."** §20.1 lists it and
  `contains_personal_data` folds with `any()`, so an operator could only ever *add* the flag — a
  strictly-tightening and genuinely useful thing. Left out because the column gates nothing today:
  `check_exportable` reads taint and `commercial_use` and never touches it. Whatever enforces
  §20.1's retention rules will want both.
- **`retention_rule` and `permitted_uses` are still recorded and still unenforced**, and this slice
  makes `permitted_uses` slightly worse: an operator now writes real prose into it ("redistribution
  and resale with attribution") and nothing reads it. The gap named at ADR-035 is unchanged; the
  text in the column is now more likely to look load-bearing than it did.
- **The export record points at the audit event, not at the attestation.** `artifact_exported`
  metadata carries `commercial_use_effective` and `licence_effective`, which is enough to explain a
  commercial export after the position is withdrawn — but there is no foreign key to the
  attestation that authorised it, so "which statement did we rely on" is a join through timestamps.
  An `export_attestation_id` column would close it, and would want to come with whatever enforces
  §20.1's remaining fields rather than alone.
- **Nothing re-checks an artifact whose rights were withdrawn after it was exported.** Export is a
  one-time recorded act and the colony does not deliver anything (§28 Phase 8), so there is no
  recall path and nothing to recall through. Real once there is a channel: a withdrawal ought to
  produce a wake, or at minimum a report of what went out under the position now withdrawn.
- **The twelfth reserved socket, and a new failure mode for the habit.** `own_provenance` was
  declared by `artifacts.create` at ADR-035 and never passed — the eleventh — but the lesson is a
  variant of the usual one. The earlier ten were "the thing you were about to build already
  half-exists." This one was inert *and* would have made a new invariant true by accident:
  `effective_provenance` recomputes exactly only because nothing had ever filled the socket, and
  the first caller to fill it would have silently broken that. **Grep for the socket, and then ask
  whether an empty one is load-bearing in its emptiness.**
- **The observations block still shows the fetcher's licence, not the attested one.** `context.
  observations_for` renders `tool_calls.licence` / `commercial_use` straight from the row, so a Cell
  looking at a page it fetched reads `unknown` even where an operator has since attested the
  domain. Left alone: that block is explicitly framed as untrusted external content ("came from
  OUTSIDE the colony"), and overlaying an operator's statement inside it would put a trusted fact
  under an untrusted banner. The artifact index was fixed instead, because that is where the
  staleness had a consequence — a Cell deciding about its own product. Worth revisiting with
  whatever gives operator-sourced facts their own place in the prompt.
- **A self-review caught what the suite and the golden run did not, and the shape is worth
  keeping.** Both defects were *downstream* of a correct mechanism: the export gate read the
  effective position (right), and the Cell's own view of the same artifact did not (wrong), so
  every test of the gate passed while the feature could not actually be used. The general form —
  **fix the gate, forget the eye** — is what to look for whenever a kernel guarantee changes and
  something else renders the same fact.

## From scheduler liveness (2026-08-24, ADR-042)

- **Two of the three gaps the PRIORITIES entry named were not real, and the entry had been carried
  for six weeks.** "No restart-on-failure" was already cron's job; "someone must install the
  crontab" is a print statement. Only "no alert when ticks stop" was a real gap, and the actual bug
  underneath it — a crash leaving no row at all — was **not mentioned in the entry**. Worth adding
  to the `*Disproved by:*` habit: an entry can be *directionally* right and wrong about every
  specific it names, and reading the code it describes is what separates those.
- **`health` is a fifth thing that can halt, and nothing enumerates the halts.** `_guard` has three
  (metabolic, vacation, autonomy), ADR-040 added the sweep as an explicitly ungated step, and
  `liveness` now classifies all of them plus two failure modes. The classification lives in
  `liveness` as an if-chain and in `_guard` as another. A colony that grows a sixth guard has to
  remember to teach `liveness` whether it is an outage. **A single table of "halt → is this an
  outage" is the fix**, and it should come with the next guard rather than before it.
- **Nothing reconciles the tick record with a real cron installation.** `health` says "no tick in N
  epochs" and prints a crontab line, but it cannot tell "the crontab was removed" from "cron is
  running and the machine is asleep" from "the entry is there and mistyped". A `mitosis tick
  --dry-run` that records a tick without doing work would let an operator prove the line works
  before trusting it.
- **The stale-tick threshold reuses the liveness deadline, and those are two different questions.**
  "How long before I call a colony dead" and "how long before a running tick is stuck" happen to
  share a number today. A tick that legitimately takes longer than the whole cadence — many Cells,
  a slow provider — would be classified as stuck. Bounded in practice because `max_cells` and the
  spend caps bound a tick's work, but it is a coincidence rather than a design.
- **`liveness(now=...)` moves wall time and not the epoch**, because `current_epoch` reads the
  simulated clock and takes no `now`. Harmless in production (the clock tracks wall time in REAL
  mode) and a real trap in tests, where passing a later `now` silently exercises only half the
  rule. Threading a `now` through `clock.current_epoch` would close it.
- **Historical ticks were backfilled with `finished_at_utc = started_at_utc`**, which is honest
  about *whether* they finished and wrong about *when*. Any future "how long do ticks take"
  statistic has to exclude rows older than migration 0025, and nothing marks where that boundary
  is except the migration itself.

## From experiment tracking (2026-08-24, ADR-043)

- **`resource_usage.experiment_id` is the one column between §2.6 and a complete report.** Two of
  its six dimensions — sandbox CPU and human labour — report `None` today. Sandbox CPU is genuinely
  Phase 5, but **human labour is blocked only by a missing column**: `ResourceType.HUMAN_MINUTES`
  exists and ADR-036 already meters it, and nothing links a usage row to an experiment. Adding it is
  additive; threading it through `gateway` is nearly free because `experiment_id` already flows
  there, and through `external_actions`/`tools` needs an experiment context those paths do not yet
  carry.
- **Revenue attributed late cannot be corrected.** The default idempotency key is
  `cell_revenue:{cell}:{source}`, so re-recording the same revenue with `--experiment` is correctly
  deduped and the original stays untagged. Found on a live colony by doing exactly that. §3.6 says
  the remedy is an adjustment rather than an edit, so what is missing is a `reattribute` verb that
  posts a compensating pair — not a mutable column.
- **Nothing consumes `ProposalKind.EXPERIMENT` yet.** A Cell can propose an experiment and the
  kernel still treats it as an undifferentiated proposal; `experiments.start` is operator-driven or
  called directly. The `_start_locked` core exists precisely so `deliberation` can fold a start into
  the transaction that records an approved proposal, which is the obvious next half — and it is
  where the §25.1 rung gate belongs: a rung-1 simulator experiment should need no human, a rung-7
  live one already goes through §23 and `promotion.allocate`.
- **§13.1's `normalised_cost` is still structurally dead.** Its numerator is a Cell's own estimate,
  which the 2026-08-06 live run found was 0 on every proposal from both models. §15.1's new context
  section now shows the *derived* cost of the Cell's current experiment, which is the reference that
  field was missing — worth re-measuring on a live model run before anything is built on the ratio.
- **A rung-1 experiment moving USD_REAL is a §25.1 violation nothing refuses.** The report surfaces
  the mismatch and the existing real-spend gates bound the damage, which is why no local check was
  added (ADR-039's "second, weaker copy"). If a rung ever gets its own budget, this is the place the
  rule would become enforceable rather than merely visible.
- **`stage_reached` is a formatted string, not a rung.** `"rung 7: tiny capped live experiment"`
  reads well in a coroner report and parses badly. §9.3's unbuilt displacement target — "bottom
  quantile of realised stage progression" — needs to *compare* stages, so it will want the integer.
  The derivation exists; only the storage format is prose.
- **The snapshot was pinning a uuid inside free text.** A prediction's claim names its approval
  request, so seeded-but-sequence-dependent ids were reaching the golden hash through a section
  about calibration. Any slice that mints one id earlier produced a spurious diff there. Scrubbed
  now — but the general shape is worth watching: **ADR-017 excludes volatile ids, and free text is
  where they hide.**

<!-- 2026-08-25, ADR-044 (experiment attribution for metered ops) -->

- **A dangling `experiment_id` is still writable from inside the kernel.** ADR-044 validated the two
  operator-facing paths (`mitosis predict --experiment`, `mitosis record-revenue --experiment`), but
  `reservations.request`, `prediction._register_locked`, `ledger.post_transaction` and
  `gateway.call_model` all accept the id and check nothing. They sit *below* `experiments` in the
  layering, so a check needs an injected seam — the `sweeper.ExternalOperationChecker` /
  `population.Displacer` shape — rather than an import. Worth doing before anything else starts
  passing the id programmatically. **A dangling id fails silently and only ever *subtracts* from a
  report**, which is the quietest way this kernel can be wrong.
- **Revenue attributed late cannot be attached.** Re-recording revenue to add `--experiment` is
  correctly refused by idempotency, so an operator who realises afterwards which experiment earned
  the money has no path. §3.6 says the remedy is a signed adjustment, never an edit; there is no
  verb for one. (Logged under ADR-043 too; unchanged and now blocking a real workflow.)
- **`resource_usage.metadata_json` is load-bearing for one figure.** §2.6's subsidised-minutes line
  reads `subsidised_human_minutes` out of free-text metadata, because that is where
  `external_actions` durably records it and `resource_usage` is the row Amendment A6 makes
  authoritative. It works and it is the right *source*, but a typed column on the metering row (or a
  second `ResourceType`) would make the split structural. Note the trap next door: the golden
  snapshot has already been caught pinning an id hidden in free text.
- **`sandbox_cpu_seconds` is now the only `None` in §2.6's report**, and it is genuinely blocked on
  §19.3's sandbox (Phase 5). `ResourceType.CPU_SECONDS` has been declared since migration 0008 and
  nothing writes it. When the sandbox lands, attribution needs no work — it opens a RESOURCE
  reservation like everything else and the join already reaches.
- **The golden scenario never exercises prediction attribution.** Its five in-experiment
  deliberations propose no forecasts, so §2.6's reality-gap dimension pins as `0/0` and the
  prediction half of ADR-044 rests on `tests/test_deliberation.py` alone. The counts are now pinned
  so a scenario change surfaces it; a scenario that proposed one forecast under an experiment would
  make the golden run cover the whole report.

<!-- 2026-08-25, ADR-045 (wiring ProposalKind.EXPERIMENT) -->

- ~~**`ProposalKind.STRATEGY` is now the last kind whose approval leads nowhere.**~~ **Decided
  2026-08-26, ADR-046**: no consumer, because approving a strategy *is* the act
  (`proposal.STATEMENT_KINDS`). The guess in this entry — "that may be correct (a strategy is a
  statement, not an act)" — was right, and stopping there would still have missed both real bugs:
  the decision reached the Cell nowhere, and the inert grant lapsed and woke it to redo what had
  succeeded. **Deciding a socket is not the same as finishing it**; the question "what should
  happen instead" is where the bugs were.
- **§13.1's `normalised_cost = expected experiment cost / current stage tranche` still has no
  tranche.** ADR-045 makes the rung a real, derived property of every Cell-proposed experiment, so
  the numerator and the *stage* now both exist; a "tranche" would be a budget attached to a rung.
  This is the natural next thing an experiment's rung could be made to *mean* rather than merely
  record — and the first design where the rung would become load-bearing, which deserves its own
  argument (ADR-043 deliberately kept `expected_cost_minor_units` inert for exactly that reason).
- **An experiment concluded by its own Cell is still the Cell's word.** `experiments.conclude`
  accepts any `concluded_by`, and ADR-043 argued that ending an experiment is declaring it
  *finished*, not declaring that it *worked*. Now that a Cell can start one through a grant, the
  symmetric question is whether it should be able to end one without a person — currently it can,
  through the CLI, only because a human runs the verb. Worth stating before anything automates it.
- **The `experiment` payload requirement broke 71 test fixtures on landing**, all of them using
  `experiment` as the neutral kind for a test about something else. The fixtures now pair each kind
  with its payload in both directions. If a future kind gains a required payload, expect the same
  blast radius and the same shape of fix — and note that the size of it is not evidence the
  requirement is wrong.

<!-- 2026-08-26, ADR-046 (the strategy kind decided) -->

- **A standing strategy has no way to be retired.** It is superseded by the next approved one and
  otherwise stands forever — there is no "this no longer applies". An operator who wants to withdraw
  guidance has to wait for the Cell to propose something else, which inverts who is steering. The
  natural shape is an operator-initiated supersession, but §0.2 puts strategy in the *mutable Cell*
  column, so a kernel-written strategy would need its own argument.
- **`decision_reason` now reaches a model's prompt.** It is operator-authored and therefore trusted
  in the sense §19.4 cares about, but it is the first free text a *human* puts into a Cell's context,
  and nothing bounds its length or checks it for anything. A very long rejection reason competes with
  the genome for the §15.1 budget. Worth a cap before the first operator writes an essay.
- **Only the *latest* decision is shown per proposal, and only the last `RECENT_PROPOSALS` of them.**
  A Cell whose strategy was rejected three times running sees at most the window. That is §15.1's
  "do not load the entire Cell history" working as intended, but it means the feedback a Cell gets
  about a repeated refusal is weaker than the signal §23.4 records about it. If
  `repeat_after_rejection` ever escalates to something a Cell should visibly learn from, it will want
  its own section rather than more history.
- **`ProposalKind` is now fully decided** — four kinds with consumers, one statement, one never
  queued. A kind added later has to say which it is; there is no longer a precedent for leaving one
  ambiguous.
