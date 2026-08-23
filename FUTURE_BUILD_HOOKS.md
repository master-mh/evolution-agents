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
