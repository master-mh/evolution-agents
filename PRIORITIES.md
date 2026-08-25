# MITOSIS — Priorities

> **Convention: an entry that asserts a blocker must name what would disprove it.**
> Added 2026-08-22 after an audit of the unchecked items found three that were wrong and one that
> overstated the work — every one in the same direction, claiming something was missing when the
> socket already existed (`liability_reserve` had been in §31's Phase-1 account list the whole
> time). The cause is structural, not careless: an entry is written the moment a gap is noticed and
> nothing ever re-reads it when a later slice happens to fill it. So a blocker claim now carries a
> `*Disproved by:*` pointer to the symbol, table or command that would settle it — one grep instead
> of a full pass. **Check the pointer before scheduling the item.**

## Now
- [x] Write `docs/SPEC.md` v0.2 — DONE (1309 lines; 32 sections + Colony Charter + 19 amendments normative)
- [x] Phase 0 formal artifacts — DONE: `docs/DECISIONS.md` (18 ADRs), `docs/STATE_MACHINES.md` (Cell lifecycle FSM + reservation FSM), `docs/EVENT_SEMANTICS.md` (delivery/ordering/poison-event handling)
- [x] Phase 1 kernel slice 1 — DONE: `src/mitosis/{money,db,models,accounts,ledger,reservations,sweeper}.py` + 41 tests (unit + Hypothesis property tests incl. a stateful `charter_crash_recovery` FSM machine). Charter C1/C2/C3/C7/C11 covered for the ledger+reservation surface.
- [x] Phase 1 kernel slice 2 — DONE: Cell lifecycle birth transition (`created->alive`), minimal genome hashing, audit_events, CLI (`mitosis init/status/create-cell`) with a console-script entry point. 59 tests passing.
- [x] Phase 1 kernel slice 3 — DONE: population limits + carrying capacity (Charter C9). `max_living_cells`/`max_active_cells` enforced in `create_cell` under concurrency; `colony_config` table matches `colony.yaml`'s `population:` block shape. 74 tests passing.
- [x] Phase 1 kernel slice 4 — DONE: global real-spend circuit breaker (Charter C5). `real_spend_limits` table matches `colony.yaml`'s `real_spend_limits:` block; per-request/concurrent-reserved/hour/day/~30d caps enforced in `reservations.request` for USD_REAL only, under concurrency. Admin raise/lower is always audited. 92 tests passing.
- [x] Phase 1 kernel slice 5 — DONE: simulated clock (SPEC.md §6). Lazy checkpoint-based `clock.now/advance/set_mode`, all 4 modes (paused/step/accelerated/realtime); `mitosis advance-time --days N` + `status` clock section. Deliberately NOT wired into existing ledger/reservation/audit timestamps yet (still real wall-clock) — see clock.py docstring. 114 tests passing (includes a follow-up CLI test closing a gap found in self-review).
- [x] Phase 1 kernel slice 6 — DONE: event_inbox/outbox (SPEC.md §17, §3.5; docs/EVENT_SEMANTICS.md; Charter C6). `events.py`: idempotent atomic processing algorithm (`enqueue`/`process_event`), `(effective_time, priority, event_id)` deterministic ordering (`next_ready`, Amendment A5), poison-event dead-lettering + controlled replay (`record_failure`/`replay_dead_letter`, §17.3), outbox staging + dispatch. `status` gained an events section. Deliberately NOT wired into any real producer yet (nothing in the kernel emits domain events through this path) and poison handling does NOT quarantine the implicated Cell (the alive/dormant->quarantined lifecycle transition doesn't exist yet) — see events.py module docstring. 144 tests passing.
- [x] Phase 1 kernel slice 7 — DONE: remaining Cell lifecycle transitions (docs/STATE_MACHINES.md §1.2; SPEC.md §10.5 Amendment A15; Charter C8/C10). `lifecycle.py` gained `wake`/`sleep`/`quarantine`/`clear_quarantine`/`kill`, each guarded by both the FSM adjacency table (`_ALLOWED_TRANSITIONS`) *and* a per-operation `valid_sources` set (needed because e.g. `wake` and `clear_quarantine` both target `alive` but must not be interchangeable). `kill` files a coroner report artifact (`coroner_reports` table, migration 0007): genome hash, spend-by-book (new `ledger.spend_by_book`, derived from ledger entries — excludes internal cash<->committed reserve/release moves), cause of death, final hypotheses, experiment links. Wired into `events.py`: dead-lettering a poison event now quarantines its implicated Cell (`process_event`/`record_failure` gained an optional `cell_id`), closing the gap left by slice 6. `status` gained a coroner-reports count. 167 tests passing (23 new, incl. two Charter property tests: `charter_dead_cell_inert` C8, `charter_audit_complete` C10).
- [x] Phase 1 kernel slice 8 — DONE: resource metering (SPEC.md §2.2/§2.3 Amendment A6; Charter C4). New `resource_metering.py` + `resource_usage` table (migration 0008): `record_usage` links every metered RESOURCE-book consumption event to exactly one open (`reserved`-status) reservation and never lets cumulative recorded `minor_units` exceed that reservation's cap — this *is* Charter C4 (`charter_no_overspend`, newly added) for the RESOURCE book. `total_minor_units`/`usage_by_type` feed into the existing `reservations.settle`/`sweeper` machinery rather than inventing new settlement logic. `verify_linkage` re-derives the Amendment A6 completeness invariant from the tables. `status` gained a resource-usage-by-type + linkage section. 183 tests passing (16 new).

- [x] Phase 1 kernel slice 9 — DONE: golden-run replay (SPEC.md §26; Amendment A12; docs/DECISIONS.md ADR-017; §29 acceptance criterion 11). `golden.py`: a fixed scenario exercising every Phase 1 subsystem, reduced to a **semantic snapshot** (uuid4 keys, wall-clock timestamps and hash-chain digests excluded; cell ids replaced by birth-order aliases) and hashed. Comparison is semantic invariants *plus* hash per ADR-017 — verified both matter: a coroner-report regression trips the invariants, while an overfunded-birth regression keeps conservation intact and is caught only by the hash. Expectations are versioned in `golden_expectations.json`; `mitosis verify-golden-run [--update-expectations]` is A12's deliberate migration path. 202 tests passing (19 new).
- [x] Phase 1 kernel slice 10 — DONE: closed a live Charter C4 gap a `/critique` found — `reservations.request()` never checked a Cell's cash balance, so a Cell could reserve/settle far beyond its funded budget while conservation and the hash chain stayed green throughout. Added the balance check (all books, inside the existing write lock); fixed the same check-before-lock race in `settle`/`release`/`_bare_status_transition`/lifecycle `_transition`/`kill`/`resource_metering.record_usage`; wired the previously-unused `accounts.FIXED_ACCOUNTS` into destination/funding-account validation; fixed three `money.py` parsing bugs (Infinity/NaN crashed instead of raising ValueError, `1e400` crashed inside the ledger instead of at parse time, underscore separators silently changed amounts 10x); fixed an events.py exception-swallowing bug; brought 7 of 15 Charter clauses' test IDs (C2/C3/C7/C8/C10/C11/C15) up to being individually `pytest -k`-collectible per SPEC.md §0.1's own requirement — C11 and C15 previously had no test at all. 221 tests passing (19 new). See BUILD_RECORD.md for the full writeup.
- [x] **CI workflow** — DONE: `.github/workflows/ci.yml` runs the full pytest suite (incl. Charter property tests, SPEC.md §0.1) + `mitosis verify-golden-run` (§26) on every push/PR to `main`. Python 3.11 via `actions/setup-python`. Hand-verified in a scratch venv on the matching Python minor version before committing. Committed `2ba65e2`, pushed.
- [x] **Seeded id generation** — DONE: new `src/mitosis/ids.py` — every `uuid.uuid4()` call site in the kernel (`ledger`/`reservations`/`lifecycle`/`events`/`resource_metering`/`audit`/`cli`) now goes through `ids.new_id()`. Default behaviour is unchanged (real, non-deterministic uuid4 strings); `ids.seeded(seed)` swaps in a `random.Random`-backed generator that still emits uuid4-*shaped* strings but deterministically. `golden.run_scenario` seeds itself (`GOLDEN_RUN_ID_SEED`) for its whole duration, closing both gaps `golden.py`'s docstring named: Amendment A5's `(effective_time, priority, event_id)` tie-break is now reproducible, and the scenario's raw uuids (not just its semantic snapshot) are now byte-identical run to run — verified by hand and pinned by `test_raw_ids_are_reproducible_across_runs`. Shipped golden-run hash unchanged (semantic snapshot already stripped ids; no expectation regeneration needed). 230 tests passing (9 new).

- [x] **Reproduction/lineage tracking** — DONE (the Phase 2 prerequisite): new `src/mitosis/lineage.py` + migration `0009_lineage.sql`. `reproduce()` births a child of a living Cell funded from the *parent's own cash* (so Charter C4 bounds lineage growth); `cells` gained `parent_cell_id` + immutable `founder_cell_id`/`generation`. **`max_lineage_population_fraction` is now enforced** — the §9.2 limit that had been stored-but-unchecked since slice 3. Lineage is tracked on the Cell rather than the genome because Phase 1 genomes are content-addressed placeholders (all Cells of a type share one hash) — written up as `docs/DECISIONS.md` ADR-019, which also records the two live consequences: seeded founders are exempt from the cap, and a small colony genuinely cannot reproduce under a tight cap (any 2nd-generation Cell in a 4-Cell colony is 40% of it). Genome parentage is recorded when a `mutation` actually changes content. Golden run extended to cover the lineage tree (§26) via a reviewed A12 expectation migration; new `mitosis reproduce` verb + `status` lineage section. 274 tests passing (43 new).

- [x] **Phase 4 model gateway** — DONE (skipping Phase 2/3 per an explicit call to get real spend working first; see BUILD_RECORD). `pricing.py` (versioned table, micro-USD costing, ADR-020), `providers.py` (`ModelProvider` protocol, deterministic free `MockProvider`, paid `AnthropicProvider`; Charter C14 enforced structurally + credential redaction), `gateway.py` (reserve → call → settle → meter → mirror), migration `0010_model_gateway.sql` (`model_calls` + `reservations.provider`). **§5.1's per-provider real-spend cap is now enforced** — stored-but-unchecked since slice 4. Five bugs found: three by hand-verification (over-reservations stranded in `committed` forever, draining Cell cash and ratcheting the C5 concurrent cap shut; output-token metering silently dropped by a double-subtraction; a misleading mirror-skip reason), one by a test (**the serious one** — cost overruns invisible to *both* the global and per-provider spend windows, so the breaker went blind exactly when a provider billed above estimate; ADR-021), and one by `/critique` post-"done" (cost and metering priced off different models). New CLI `fund-cell` (required: a calling Cell needs balances in three books) and `call-model` (gated behind `--yes-spend-real-money` for any paid provider). Golden run extended via a reviewed A12 migration (expectation version 1 → 2). Charter C14 gained its first test (`charter_no_secret_in_cell`). 356 tests passing (82 new; CI reports 355 + 1 skip, since it installs `.[dev]` without the optional `anthropic` package).

- [x] **Crash-atomicity of the gateway success path** — DONE (ADR-022), closing the largest known correctness gap in the Phase 4 slice. `_handle_success` and `_handle_failure` are now one `BEGIN IMMEDIATE` each, composed from new `_*_locked` cores in `reservations.py`/`resource_metering.py`/`ledger.py` — the same core-plus-wrapper split `ledger._write_transaction` and `audit.record` already used. Steps 1–3 stay outside on purpose: the reservation must commit *before* the external call or reserve-before-execute means nothing. `sweeper.py` still doesn't import `gateway` (the dependency runs the other way): the gateway supplies `GatewayOperationChecker` for the `ExternalOperationChecker` seam that was built for exactly this, plus `resolve_stranded_calls` for its own rows, and the new `mitosis sweep` verb runs both in order. Hand-verified against a file-backed colony at three crash points, including a counterfactual that reproduced the old bug — **conservation and the hash chain stayed green throughout it**, which is why no existing invariant would ever have caught this. 368 tests passing (12 new); golden-run hash unchanged (a pure atomicity change is invisible to the semantic snapshot, as it should be).

- [x] **Provider-invoice reconciliation** — DONE (ADR-023), closing the producer-with-no-consumer ADR-022 had just created: crash recovery parks calls in `execution_unknown` and nothing could resolve them. New `reconciliation.py` + migration `0011`: two paths (funds still committed → resolve through §4.4's FSM; funds already moved → post a **new** adjustment transaction, never edit history per §3.6), `reconciled_micro_usd`/`reconciled_at_utc`/`reconciliation_source` (§24.1), and CLI `reconcile`/`dispute`/`outstanding`. **The `_REAL_SPEND_TRANSACTION_TYPES` footgun had to be fixed to land this** — the adjustment is the predicted third real-spend type, and it can be *negative*, which both breaker queries would have counted as fresh spend (their `amount > 0` filter selects a refund's cell-cash leg), so refunding a Cell would have pushed it toward the circuit breaker. Both queries now sum the signed `external_expense` leg and read one list. Two bugs found by hand-verification: a §4.4 violation (`disputed` has no `partially_settled` exit) and my own docstring overclaiming that this fixes ADR-020's rounding. 405 tests passing (37 new); golden run extended via a reviewed A12 migration (expectation version 2 → 3, no money movement).

- [x] **Real-spend type registration guard** — DONE, replacing the convention that let the
  cost-overrun type ship unregistered. New `tests/test_real_spend_registration.py` (7 tests) attacks
  it from three angles, because no one of them is sufficient: an **AST walk** over the kernel
  requiring every `transaction_type=` to be either registered in `_REAL_SPEND_TRANSACTION_TYPES` or
  exempted *with a stated reason* (the angle that fires on a genuinely new type, whatever it does); a
  **precise static check** that any call site naming `external_expense` uses a registered type (the
  one that would have caught the overrun); and a **behavioural check**, parametrized over the
  registry itself, that each registered type is summed by *both* the global and per-provider windows.
  Writing it surfaced a subtlety I had assumed away: `model_call_sim_mirror` posts to
  `external_expense` too, in `Book.USD_SIM` — so the static check must resolve the **book**, not just
  the account, and the USD_SIM exclusion is now asserted explicitly rather than left implicit, since
  that is the one way a real-spend type could hide from it. Also pins the previously-undocumented
  coupling that a registered direct-posting type must shape its idempotency key
  `{type}:{model_call_id}` or the per-provider join silently misses it — registration in the tuple is
  necessary but not sufficient. Teeth-checked by reintroducing each bug in turn: unregistering the
  overrun type fails 2 tests and names `gateway.py:569`, adding a novel type fails classification,
  breaking the key convention fails the per-provider assertion. 412 tests passing (7 new); golden-run
  hash unchanged, as a test-only change should leave it. The airtight alternative — a runtime check
  in `ledger` that no code shape can bypass — is logged in FUTURE_BUILD_HOOKS with why it wasn't
  built here.

- [x] **Make a real paid call** — DONE (2026-08-05). `claude-haiku-4-5`, 12 in / 4 out, 32 micro-USD
  true cost, **1 cent recorded**, model replied `ok`. Verified against the ledger: cost math
  reconciles exactly, one `reservation_settle` entry on `external_expense`, conservation and hash
  chain green, A6 linkage complete, nothing stranded. Measured rather than predicted: ADR-020's
  rounding overstates by **312×** at this size, and the pre-call estimate over-reserved **10.8×**
  while *under*-counting input tokens (11 predicted vs 12 actual) — the opposite of the documented
  "deliberate over-estimate", because the 2-chars/token heuristic ignores per-message overhead. Two
  real failure paths ran first and both behaved: Charter C4 refused an under-funded RESOURCE
  reservation, and a 401 was classified definitely-unbilled so funds released rather than freezing in
  `execution_unknown`. Also fixed `outstanding`/`summary` counting zero-cost mock calls as billable
  work (shared `_BILLABLE_PREDICATE`; still a worklist, not a gate), and added `.env`/`.env.*` to
  `.gitignore`, which had neither. 414 tests passing; golden-run hash unchanged.

- [x] **Revenue path + Ollama provider** — DONE (2026-08-05), the two prerequisites for
  self-directing Cells. **Revenue**: new `revenue.py` — the `revenue` account existed in §31's list
  and nothing ever posted to it, so profitability was unmeasurable, not merely unmeasured.
  `record_revenue` mirrors spend (debit `revenue`, credit Cell cash), requires attribution, is
  idempotent per source, and works for a dead Cell (payment outlives the worker). Deliberately
  invisible to Charter C5: earning must not buy permission to spend past a cap — the teeth check
  showed the combined mis-wiring makes the hour window read **−10,000**, i.e. a Cell earning
  *backwards* through the breaker. **Ollama**: local inference at zero price via stdlib `urllib`
  (no new dependency), no credential to leak at all, models registered explicitly rather than
  zero-by-wildcard (an Ollama-compatible endpoint can front a paid model), and never
  `execution_unknown` since a local provider cannot bill. Free in money is not free in compute —
  RESOURCE metering still bounds it, proven end to end. Last slice's registration guard fired on
  `cell_revenue` immediately, as designed. 448 tests passing (34 new); golden-run hash unchanged.
  Hand-verified on the live colony: **net position +74 minor units, the first profit figure MITOSIS
  could compute.**

- [x] **`ledger.spend_by_book` account-level fix** — DONE (2026-08-05), landed before anything
  selects on profit. `accounts.py` gained `SPEND_DESTINATIONS`/`CAPITAL_ACCOUNTS` (each with its
  reason) plus `unclassified_accounts()`, and `spend_by_book` is now the **signed** sum over spend
  destinations — so a reconciliation credit reduces it and a capital movement never enters it.
  Neither half was fixable alone: dropping the sign filter without scoping by account makes a
  freshly-funded Cell read **−1000**. **The framing mattered more than the query:** the distinction
  is consumption vs capital movement, *not* internal vs external — the gateway settles every
  RESOURCE metering into `infrastructure_reserve`, so the internal/external framing I started with
  would have erased every Cell's entire compute consumption, exactly where Ollama makes RESOURCE the
  only remaining bound. Teeth-checking also surfaced a second, previously unnamed overstatement: the
  old query counted `colony_treasury` capital returns as spend (1600 vs 700). Golden-run hash
  unchanged, and notably the golden run does *not* cover this — misclassifying an account leaves it
  passing. 453 tests passing (5 new). Hand-verified live: a 1¢ credit moves USD_REAL spend 1 → 0.

- [x] **Prediction register** — DONE (2026-08-05), Amendment A14 / §8.5, normative since v0.2 and
  unbuilt until now. `prediction.py` + migration 0012: register-before-outcome, hash-chained like the
  ledger, scored with both rules §8.5 names (Brier and log), with §8.5's calibration curve returned
  as buckets because the *shape* is the diagnosis — systematic over- and under-confidence produce the
  same mean Brier and need opposite corrections. **Binary claims only**, because Brier and log are
  defined over binary outcomes: a continuous quantity is predicted by threshold, and scoring a point
  estimate properly needs CRPS, which §8.5 does not authorise (logged). **Certainty refused** in
  Python and by schema CHECK — an infinite log score would make a population unorderable and
  therefore unselectable. **The anti-gaming surface is the load-bearing part**: `overdue()` plus
  `unresolved`/`overdue` reported beside the means, since a Cell resolving only its winners has a
  perfect curve and a pile of losers behind it. Golden run extended via a reviewed A12 migration
  (version 3 → 4; only `predictions` and two audit types changed — no money moved). 481 tests
  passing (28 new). Hand-verified live: editing a resolved prediction breaks the chain, reverting
  restores it.

- [x] **Death criteria (§10.5, A15)** — DONE (2026-08-05); the evolutionary loop is closed
  (reproduction already worked). **Reading §10.5 changed the design: the spec forbids
  compute-fitness-and-cull-the-bottom.** "Estimated negative EV *alone* must not kill a Cell"
  without strong evidence *and* an independent Auditor concurring, so `reap` kills only on realised
  facts and `kill_for_negative_ev` is a separate path that structurally cannot be reached without a
  living, non-self, auditor/immune concurrer (recorded in the audit trail and the coroner report).
  §10.2 forbids scalar collapse, so domination is **Pareto** across net contribution and calibration
  — earning more but predicting worse is *not* domination. §10.3's Explorers are protected for free
  by restricting comparison to same-genome near-duplicates. Implemented: `budget_exhausted`,
  `dominated_by_near_duplicate`. Not implemented, with reasons recorded: validation gates and
  evidence reproduction (need Phase 2 experiments), policy violation (needs §31's `policy_violations`
  table; inferring it from a free-text quarantine reason would be guessing). **Caught while
  building: domination on net contribution alone lets an *idle* Cell dominate one that invested —
  selecting for doing nothing.** Fixed and pinned. `reap` is dry-run by default; death is
  irreversible. 501 tests passing (20 new); golden hash unchanged. Hand-verified end to end.

- [x] **§9.3 displacement** — DONE (2026-08-06), ADR-024. A birth denied at carrying capacity can
  now evict one objectively-failing Cell instead of waiting, opt-in per birth. **The design is
  mostly what displacement must not be able to do:** `population.Displacer` takes nothing about the
  child — not its genome, budget, or forecast — so ADR-009's "no forecast-triggered kill" is a
  property of the signature rather than a rule a reviewer has to notice, and the birth records
  which Cell it displaced so traceability still runs both ways. Order among candidates is birth
  order, explicitly *not* a ranking, since "take the worst" is §10.2's forbidden scalar collapse
  wearing a comparison function. `lifecycle.kill` gained the `_kill_locked` core (ADR-022's shape)
  so eviction and birth are one transaction. Three exclusions, each load-bearing: never the parent
  (it funds the child), never a Cell with committed funds (an open reservation would be stranded),
  never on negative EV (§10.5's twice-signed path must not have a back door). **Caught while
  building: the lineage cap has to be checked *after* displacement** — eviction shrinks the living
  population and so *raises* every surviving lineage's share; checking first births into a §9.4
  violation having killed a Cell to get there. 520 tests passing (19 new); golden hash unchanged,
  and honestly so — displacement is the one birth path replay cannot reach, since there is no
  supported way to lower a population cap after `init` (logged).

- [x] **A Cell that acts** — DONE (2026-08-06), ADR-025. `deliberation.py` + `context.py` +
  `proposal.py` + migration 0013. One wake is: assemble bounded context (§15) → one gateway call →
  parse a strict structured proposal → record it with its predictions registered before their
  outcomes (§8.5). **Structured proposals landed with it** (the separate Next item below), because
  prose output and §0.3 are incompatible: `extra="forbid"`, no field for a self-reported outcome,
  and `FORBIDDEN_FIELD_SENSE` as a tripwire on the schema itself. **The loop lands at rung 5 of
  §25.1's ladder — "shadow prediction with no action" — not rung 9:** a proposal is inert, no
  kernel path consumes it, and `risk_tier` grants nothing. Genome content is data rendered into a
  prompt, never executed (Charter C15, enforced by an AST test). **Found while building: a wake
  cannot run inside `events.process_event`'s transaction** — that contract forbids the handler
  committing, ADR-022 requires the reservation to commit before the external call — so idempotency
  on a wake key carries Charter C6 instead, which is what C6 actually asks for. Closes the
  long-standing "no producer or consumer on the event path" gap. 549 tests passing (29 new);
  golden expectation version 4 → 5 via a reviewed migration (**no USD_REAL moves**).

## Next
- [x] **Drive the loop with a real model — local half DONE** (2026-08-06). Ollama installed,
  `llama3.2` (3B), nine live wakes. **The first one failed to parse, and the bug was the prompt's,
  not the model's:** the schema hint rendered enum choices as JSON arrays, so the model returned
  `"risk_tier": ["MEDIUM"]` — a correct choice in the wrong shape. A mock provider structurally
  cannot find this, because its reply is an input rather than a response to the prompt's wording.
  Fixed to `exactly one of: A | B | C`; compliance went **0/1 → 7/8**, the remaining failure being
  malformed JSON from the model itself (170 output tokens against a 700 budget, and `max_tokens` is
  correctly wired to Ollama's `num_predict`, so not a cap). Confirmed live: USD_REAL never moved,
  RESOURCE was the only bound (20000 → 19982), and context grew 336 → 414 tokens across nine wakes
  then plateaued under the `RECENT_PROPOSALS` cap — §15.1 holding on real data. Golden expectation
  5 → 6 (prompt text only; no balances moved).
- [x] **The paid half — DONE** (2026-08-06). One `claude-haiku-4-5` deliberation: 909 in / 199 out,
  3.8s, true cost **0.19¢ recorded as 1¢** (ADR-020 ceiling, 5× overstatement at this size; the
  pre-call estimate over-reserved 2.8×). USD_REAL 5 → 4, `external_expense` 1, nothing committed,
  no stranded reservations, breaker at 1¢ against a 5¢/request cap, all chains and conservation
  green, A6 linkage complete. **It abstained** — citing its 9 unresolved predictions and absent
  resolved track record, which it knew only because §15 context assembly shows a Cell its own
  record. First live evidence that the context design feeds a real decision, and that `ABSTAIN`
  earns its place as a first-class outcome rather than a Cell inventing work. Caveat: n=1, and it
  read a history `llama3.2` created on the same Cell, so this is not a clean head-to-head.
- [x] **Something that wakes a Cell — DONE** (2026-08-06), ADR-026. `scheduler.py` + migration
  0014: epochs derived from §6's simulated clock, `mitosis tick` running one epoch's wakes, and
  the §23.3 guards that make unattended running survivable. **The cadence policy I had flagged as
  needing a decision answered itself: it is a dedupe key.** Wakes are `epoch:{n}:cell:{id}` and
  `events.enqueue` is already idempotent on dedupe keys, so one-wake-per-Cell-per-epoch is
  structural — cron every minute costs nothing until the epoch turns. **Three guards, each
  normative:** `autonomy.real_spending` (§27.1 ships it false, and needs two independent
  confirmations to enable), vacation mode (§23.3 — maps onto the paid/free provider split, so an
  absent operator stops the colony *spending*, not thinking), and the metabolic alarm (§23.3 —
  watches the **derivative**, firing "even if every individual cap is satisfied", and halting
  until acknowledged with a stated reason). **Found while building: §6.3's "explicit conversion
  metadata" is load-bearing** — ledger rows are wall-stamped while epochs are simulated, so
  `epoch_log`'s per-epoch wall anchor is the only thing that makes per-epoch spend computable at
  all. 571 tests (22 new); golden hash unchanged. Teeth-checked nine ways.
- [x] **Nothing runs the scheduler — DONE** (2026-08-24), ADR-042. `scheduler.liveness` +
  migration 0025 + `mitosis health`. **Two of the three gaps this entry named dissolved and the
  third was a different bug than the entry described.** Restart-on-failure is cron's job and cron
  already does it — it runs the command again next minute either way, which is why §30.1 made
  `tick` a command rather than a daemon. The real gap was **two invisible failures that looked
  identical**: nothing running the scheduler, and something running it and dying every time.
  `scheduler_ticks` was written only at the *end* of a tick, so a crash left **no row at all** and
  a colony failing every minute for a week looked exactly like one never scheduled. The row is now
  opened before the work (`tool_calls.status='requested'` one layer up), with `'crashed'` and an
  unfinished `'started'` kept as separate facts — an exception can be caught and redacted (C14), a
  SIGKILL cannot write anything. `mitosis health` **exits 0/1/2**, which is §30.1 applied to
  alerting: any monitor reads an exit code, none need to know what MITOSIS is. **A deliberate halt
  is not an outage** — vacation and `real_spending` off are fail-safes working and clear when the
  operator returns; only §23.3's metabolic alarm, which holds until acknowledged, gets code 2. The
  default deadline is measured **in epochs**, and checking why turned a guess into a policy: the
  wall-clock alternative assumed a late sweep leaves stale authority usable, and ADR-039 had
  already established that all three executors refuse an expired grant on their own terms. 887
  tests (18 new); golden run untouched (**no expectation moved, no money**). Teeth-checked thirteen
  ways; hand-verified across five verdicts and three exit codes, which surfaced an unquoted
  crontab line on a path with a space in it, and a self-review caught a crash row claiming it had
  spent nothing.
- [x] **`max_births_per_epoch` (§9.2) — DONE** (2026-08-22), ADR-031. `population.py` + migration
  0017. **The open question answered itself once the two refusals were put side by side:** it fails
  like the other caps, but it must not be *confused* with them. Capacity is durable and is why §9.3
  lets a birth displace a Cell; a rate limit is temporary and clears when the epoch turns. So
  `BirthRateExceededError` is a **sibling** of `CarryingCapacityError`, never a subclass, and the
  rate check runs before the displacer is consulted — otherwise a birth kills something to get
  around a wait, and §10.5 does not permit a death caused by impatience. **The epoch is stamped on
  the Cell at birth** rather than derived: cells are wall-stamped while epochs are simulated (§6.3),
  and the scheduler's `epoch_log` anchors only exist for epochs a tick observed, so a
  hand-driven colony would have births belonging to no epoch and a cap that silently never binds.
  **The epoch primitive moved `scheduler` → `clock`**, because `population` cannot import
  `scheduler` and an *optional* injected seam is not a cap. Dead Cells still count (§9.1 is about
  the rate work is spawned, which dying does not undo). 671 tests (12 new); golden expectation
  10 → 11 pins `born_in_epoch`, with an epoch turned mid-scenario so the column is not uniformly
  zero (**no money moves**). Teeth-checked nine ways; the structural test's first draft used a
  character window and passed against an insert binding a constant.
- [x] **§23 approval queue — DONE** (2026-08-22), ADR-027. `approval.py` + migration 0015 + six
  CLI verbs. **§23.5 — "the approval queue is itself part of the environment and will be optimised
  against by Cells" — made the obvious design unusable**, because the obvious queue files by the
  `risk_tier` the reviewed Cell wrote itself. So `claimed_tier` and `assessed_tier` are separate:
  the kernel derives its own from book, status, kind and lineage exposure, and the fold is `max`,
  so **a Cell may raise its own tier and never lower it** — §0.3 extended from outcomes to
  requests. **Found while building: §23.4's aggregation key should be the lineage, not the Cell,
  and the spec cannot say so** — it names counterparty/domain/channel, none of which exist yet,
  but its target is action-splitting and the cheapest splitter here is §9 reproduction. **SLA and
  expiry are two clocks**: overdue is derived and stays approvable, expiry is a transition that
  *regenerates* the action (§23.3's easy-to-drop second half) and locks out a late decision.
  Approval writes a scoped, expiring **grant that nothing consumes** — rung 6 of §25.1, not rung 9,
  enforced structurally. 608 tests (37 new); golden expectation 6 → 7 via a reviewed migration
  (**no USD_REAL moves**). Teeth-checked thirteen ways; two tests initially passed for the wrong
  reason and were rewritten.

- [x] **§23.2's independent Auditor summary — DONE** (2026-08-22), ADR-032. `auditor.py` +
  migration 0018. **The blocker recorded here was wrong on both counts:** §7 is the flight
  simulator, not the taxonomy, and `CellType.AUDITOR` has existed since Phase 1 — `death.kill_for_
  negative_ev` has always validated a concurring Auditor. What was missing was any way for one to
  *produce* an audit. **§10.4 forbade the obvious design:** Auditor reward is precision-weighted and
  §29.10 is "wrongful Auditor flags are penalised", and prose cannot be penalised — an Auditor whose
  flags cost nothing flags everything, which looks responsible while destroying the signal. So every
  audit stakes a **probability registered as a §8.5 prediction**, scored by the same rule every
  other Cell faces; the *kernel* composes the claim, because §0.3 binds the evaluator too. A verdict
  incoherent with its own probability is refused. Independence is four checks — not the subject, an
  oversight type, a different lineage, able to think — but the identity checks are the weak half:
  what makes it a second opinion is that the Auditor is briefed on what the subject cannot see about
  itself, including the kernel's **assessed** tier. **An audit advises and never blocks** (§10.4
  penalises "unnecessary blocking"), enforced structurally. An unusable reply is *recorded* rather
  than raised, because the model call is already paid for. 696 tests (25 new); golden expectation
  11 → 12 (**no USD_REAL movement**). Teeth-checked sixteen ways.
- [x] **Genome content (§16.2's v0.1 fields) — DONE** (2026-08-22), ADR-033. `genome.py` rewritten
  + `lifecycle`/`lineage`/`approval`/`cli`; **no migration** — `cell_genomes` has had every §16.2
  column since slice 2. **The slice was not "add fields": inheritance did not exist.**
  `_get_or_create_genome` rebuilt a child's content from cell_type alone and never read the
  parent's — invisible while every genome was `{"cell_type": ...}` (parent and child collided into
  one content-addressed row, so ADR-018's promise *looked* true) and false in two directions the
  moment content was real: a child born blank, addressing to the same row as every other bare Cell
  of its type. **§16.4 closed the schema** — "Cells could reproduce to escape liabilities while
  keeping profitable assets" — so only §16.2's fields are accepted and §16.3's non-inheritable
  categories are *unrepresentable* rather than merely rejected; validation runs on the merged
  content, not the overlay. **`risk_class` and `allowed_tools` are claims, never grants**, folding
  through the same ADR-027 `max` that governs `claimed_tier`, because a lineage that could write
  `risk_class: LOW` into its children would buy them cheap approvals for as long as it survived.
  Founders are the only entry point (`create-cell --genome`); §14's operators explore from there —
  a Cell proposing its own genome is self-modification and was deliberately not built. 719 tests
  (23 new); golden expectation 12 → 13, where the child's assessed tier rises *above its own
  claim* on inherited `risk_class` (**no money moves**). Teeth-checked eleven ways; one new test
  was vacuous (`GENOME_FIELDS` derived from its own classification) and was rewritten.
- [x] **The tool surface — DONE** (2026-08-23), ADR-034. `tools.py` + `tool_registry.py` +
  `fetchers.py` + migration 0019. **§25.1 reframed the risk: read-only observation is rung 4 and
  the agent loop has been at rung 5 since ADR-025**, so reading the world is *below* where the
  colony stood — the large step is acting, which is rungs 8-9 and has no registry entry
  (`ToolSpec.read_only`, enforced by a named test). **§19.4's sharpest consequence is that a tool
  result can never cause another tool call**: execution needs a grant, a grant needs a human on a
  §23 request, so an injected page can at most produce a *proposal* whose URL a person reads —
  which is why the proposal→approval→grant route beat inline tool use. **The layering constraint
  and the injection rule wanted the same seam**, splitting `tool_registry` (readable by `context`)
  from `tools` (the executor `context` must not reach). Both §27.1 gates are checked at execution;
  the allowlist matches exactly or on a dotted suffix; **redirects are refused**, because following
  one carries the fetch off the allowlist after the check passed. First
  `charter_sandbox_isolation` (C12) test ships with it. 756 tests (36 new); golden expectation
  13 → 14 (**no USD_REAL movement**). Teeth-checked twenty ways; one test was genuinely weak and
  was rewritten.
- [x] **The artifact store — DONE** (2026-08-23), ADR-035. `artifacts.py` + migration 0020.
  **Identity is the content hash**, because §11.3 names "duplicated artifacts with new names" as a
  gaming vector and content addressing makes it *unrepresentable* rather than detectable — the
  third instance of that move after ADR-018 and ADR-033, and worth naming as a principle. **§1
  forbids the fitness dimension a work-product store invites** ("the colony is not successful
  because it produces many artifacts"), so nothing counts them and a structural test guards `death`
  and `outcome`. **Rights propagate most-restrictive-wins and never reset**, closing §20.2's
  one-step launder: everything derived from a fetched page is `commercial_use: unknown` and
  unsellable until a person establishes the rights — which ADR-041 is now the way to do. **Production is free, export is gated** (§28
  Phase 8 gates *external use*; §19.3's export gateway), the opposite of the tool surface and for a
  stated reason. Amendment A3's `ledger_entries.artifact_id` is populated for the first time since
  migration 0001, and §15.2's "artifact index" — its last unbuilt memory tier — now exists. 781
  tests (23 new); golden expectation 14 → 15, and the scenario **records revenue for the first time
  in its history** (USD_SIM; **no USD_REAL movement**). Teeth-checked sixteen ways; one structural
  test was checking the wrong thing and was rewritten.
- [x] **The delivery channel — DONE** (2026-08-23), ADR-036. `channel_registry.py` +
  `external_actions.py` + migration 0021. All four design decisions survived contact; a fifth
  emerged from building. **The registry, not a sender** — `test_nothing_in_the_registry_transmits`
  is structural, since the behavioural version ("assert no email was sent") passes against code
  that would send one. **Counterparty as a salted hash**, and the argument turned out to be the
  do-not-contact list rather than privacy in the abstract: "never contact this person again" is
  honoured permanently *without the colony ever holding a list of the people who asked*.
  **Aggregation split in two** — the queue keys `channel:{id}` and the counterparty aggregation
  lives at claim time, because a Cell never names a person, so the counterparty does not exist at
  approval time. **Per-channel rate and quota caps, colony-wide**, plus a complaint that freezes
  the channel (§23.3's alarm shape) — the first guard in this kernel bounding something money
  cannot repair. **`HUMAN_MINUTES` metered at last**, with minutes past the billable ceiling
  recorded as *subsidy* rather than refused: the minutes were already spent, and refusing to write
  them down only makes the colony's account of its own human cost quieter than reality. The fifth
  decision: **claim before acting**, because recording completed actions makes "prevent"
  impossible — the second email is already sent by the time the kernel can object. 815 tests
  (34 new); golden expectation 15 → 16, **no USD_REAL movement**. Teeth-checked 31 ways;
  hand-verified end to end on a live colony, where the pre-send check was found misattributing a
  same-lineage duplicate as a §21.3 sibling collision.
- [x] **Nothing handles the operator being away — DONE** (2026-08-23), ADR-039 + ADR-040.
  **Retitled and repointed first** (was
  "nothing schedules a tool call"); the old title invited the one reading §19.4 rules out, and its
  disproof pointer named that reading as the resolution. **Execution staying manual is the design,
  not the gap:** §19.4's injection isolation is why `scheduler.py` may not import `tools` at all,
  and `test_nothing_in_the_deliberation_path_executes_a_tool` enforces it. The delivery half is
  likewise done and manual on purpose (§28 Phase 8's acceptance is "all external action remains
  manual"). The real gap is §23.3's solo-operator model, and it is in two halves:
  - [x] **An unconsumed grant expires and nothing regenerates it — DONE** (2026-08-23), ADR-039.
    `approval.expire_grants_due` + migration 0023. **The constraint that shaped it: regeneration is
    a wake and never a new authorisation.** Renewing the grant, or reopening the request as
    PENDING, is the obvious design and is exactly the banking a grant's inherited expiry exists to
    prevent — one human decision refreshed indefinitely by the mechanism meant to end it. §23.3's
    word is "re-evaluated", and that is a person's. **The expiry is recorded on the grant and the
    request stays APPROVED**: §3.6's habit, plus `RequestStatus.EXPIRED` already means "expired
    unreviewed", so reusing it would collapse "nobody looked" into "someone approved and the window
    lapsed". A distinct `grant_expired` wake reason, because §15 renders it into the Cell's context
    and "a human judged this worth doing" is exactly what a Cell re-proposing should know. Nothing
    is released because a grant holds nothing — `approve` reserves neither money nor RESOURCE, and
    the golden diff touches no book. 835 tests (7 new); golden expectation 17 → 18, where
    `approval_grants` becomes a disposition and **`total` is unchanged by the sweep**, which is the
    assertion a renewing kernel would fail. Teeth-checked six ways; hand-verified end to end.
  - **The regeneration that does exist only runs when the operator is present.** `approval.
    expire_due` has exactly one caller, `mitosis expire-approvals` in `cli.py:1562` — the scheduler
    never calls it. So the machinery built for an absent operator is itself operator-invoked, which
    is the failure §23.3's vacation mode exists to describe.

  **Both halves landed 2026-08-23.** ADR-039 built grant regeneration; ADR-040 wired both sweeps
  into `tick`, **before `_guard`** — which is the whole of that slice. Every guard in `tick`
  decides whether the colony may *do* something; the sweep only ever *removes* permission, so
  gating it behind them would invert their purpose: a halt that also stopped expiry would preserve
  exactly the authorisations the halt exists to stop being used. Vacation mode is the case that
  makes it bite — §23.3 pauses work when the operator is unresponsive, which is precisely when
  approvals lapse unconsumed, so sweeping after the guard would switch off the mechanism built for
  an absent operator whenever the operator is absent. **The cost stays guarded and that falls out
  of the placement**: expiring is free, and the wakes it enqueues are only *processed* by
  `run_ready_wakes`, which a halted tick returns before reaching — authority withdrawn at once,
  spending deferred. Neither half ever required anything to execute a tool, which is why this was
  never blocked on overturning ADR-034. 839 tests (11 new across the two slices); golden expectation
  17 → 18 (ADR-039), unchanged by ADR-040. Teeth-checked ten ways across the two; hand-verified on a
  live colony, where a tick logged `ran | 2 deliberation(s); expired 0 request(s), 1 grant(s)`.
- [x] **Rights a person can establish — DONE** (2026-08-24), ADR-041. `rights.py` + migration
  0024 + `set-rights`/`rights`. The gap four consecutive slices flagged (ADR-035, 036, 037, 040):
  §20.2's inheritance ran one way only, so an artifact built on a fetched page was `unknown`
  forever and `real_commerce` could be opened and still sell nothing. **The subject is a source,
  never an artifact** — per-artifact stamping is the laundering path with a person holding the pen,
  and it reopens on the next artifact from the same page. **Two subject kinds**: `domain`, and
  `colony` for the colony's own output, which was half the gap and nearly missed — a report written
  unaided was equally unsellable and no domain attestation can reach it. **Matching is exact host,
  deliberately unlike the egress allowlist beside it**, because over-matching there means reading a
  page and here means *selling* under a licence that never covered it (§20.3). **Retroactive
  without rewriting anything**: §3.6 rules out cascading into the stored columns, so
  `check_exportable` re-derives and withdrawal is an attestation of `unknown` rather than a
  `revoked` flag. §0.3 is enforced at both ends — an AST walk over every module bars a Cell-reachable
  writer, and `inherit_provenance` refuses an `own_provenance` carrying `permitted`. `artifacts.
  create`'s `own_provenance` was **the eleventh reserved socket found half-built** (declared since
  ADR-035, never passed) and is now stored so the recomputation is exact by construction. 869 tests
  (30 new); golden expectation 18 → 19, where the `artifacts` section is **byte-identical** and that
  is the assertion (**balances identical in every book**). Teeth-checked fourteen ways;
  hand-verified end to end on a live colony, which surfaced two message bugs nothing else would
  have. A self-review then found that **§15.2's artifact index was still feeding the Cell the
  creation-time position** — the gap moved upstream rather than closed, since a Cell reading
  `unknown` never proposes the sale the open gate would now allow.
- [ ] **Charter C13's router exists; C13 is still unsatisfied.** `artifacts.check_exportable`
  refuses `SIM_ADVERSARIAL` and is tested, but nothing in the kernel can *produce* that label —
  §18.2 is about lineages evolved under adversarial synthetic incentives, and the shadow economy is
  Phase 6. C13 remains the one Charter clause with no `charter_*` test, now for a precise reason
  rather than a vague one. *Disproved by:* anything **in `src/`** that writes `SIM_ADVERSARIAL`
  from a lineage's history — **narrowed 2026-08-24**, because ADR-041's
  `test_charter_c13_refuses_regardless_of_any_attestation` hand-constructs the label through
  `own_provenance` to prove the router still refuses, and a pointer reading "anything that writes
  `SIM_ADVERSARIAL`" would have been satisfied by a test fixture exercising the gate rather than by
  the evolutionary machinery §18.2 actually asks for.
- [x] **The `external_publish` decision — DONE** (2026-08-23), ADR-037. `channel_registry.py` +
  migration 0022. **The flag stays off, and the reason it could not simply be turned on is that it
  was gating two capabilities from two different phases.** `external_publish` was the only flag in
  the kernel opening more than one — `public_web_read` gates one tool, `external_message` one
  channel — which made `cmd_set_autonomy`'s own "there is deliberately no switch that opens more
  than one" false as written. And the two are not peers: a page published by hand is §28 Phase 8's
  landing-page draft, while a marketplace listing is an offer to sell — Phase 9's merchant channel,
  with the legal identity and liability reserves that phase requires. **The split is §0.4's own
  list, not an invention:** §0.4 names six prohibitions and §27.1's block carries five keys, and
  "no real commerce" is the one that never got one. So `marketplace_listing` moved to a new
  `real_commerce` key and `external_publish` keeps its spec-given name over `web_publish` alone —
  no spec-named key removed, and §27.1 is headed "development defaults". **The second finding was
  that the registry's guarantee was vacuous for both:** every §21.2 check was counterparty-keyed,
  so a channel addressing nobody ran the autonomy gate, the freeze and the rate cap and then
  skipped duplicate, sibling and do-not-contact entirely — while `marketplace_listing`'s own
  description promised "two lineages listing against each other is §21.2's bidding war", detected
  by nothing. `domain` and `platform_account` had been columns since migration 0021 and were named
  in no predicate anywhere: the eighth reserved socket found half-built. `ChannelSpec.target_kind`
  now names the §21.2 key each channel collides on and **requires** it, so a publish channel fails
  closed. A same-lineage repeat on a domain is deliberately *not* a collision (publishing twice to
  your own site is a business publishing twice), duplicates are keyed on the content-addressed
  artifact instead, and a target-keyed check **refuses to answer without a lineage** rather than
  guessing which way to be wrong. 826 tests (11 new); golden expectation 16 → 17, where
  `external_publish` is open and `real_commerce` shut in one colony — a kernel that re-merged them
  passes every other assertion in the run and fails there (**no USD_REAL movement**). Teeth-checked
  ten ways; hand-verified end to end on a live colony.
- [x] **The `browser_control` decision — DONE** (2026-08-23), ADR-038. No migration, no code — a
  decision and two structural guards. **The entry this replaces was wrong twice, and both errors
  were written the same morning it was resolved.** It called the capability §25.1 rung 8–9
  automation "with nothing for a §0.4 argument to be about": false, because §28 **Phase 7 names a
  "read-only browser" as a deliverable**, and rendering a page a Cell may read is rung 4 exactly
  where `http_get` already sits. And its disproof pointer read *"any tool declaring
  `browser_control`"* — **backwards, and mildly dangerous**: a tool declaring the flag before a
  sandbox exists is the bug the entry should prevent, not the evidence it is resolved. **The real
  finding is that the flag names two capabilities and the spec never says which** — a renderer
  (Phase 7) or driving a browser to act (rung 8–9, Phase 10). ADR-038 assigns it the renderer,
  because that is the only browser §28 ever asks for, and rules that actuation would need its own
  §27.1 key — ADR-037's principle applied *before* the second capability exists. **It stays shut,
  and what it waits on is §19 rather than a decision:** a browser *runs* the page, so both of
  ADR-034's network guards stop working (an engine follows its own redirects, and checks robots.txt
  for none of its subresources), Charter C12's whole live surface is the egress allowlist, and
  there is no `sandbox.py` at all — §19.1 calls Docker "not a strong adversarial security
  boundary", §19.2 wants gVisor/Firecracker *before* real-facing code execution, and §19.6 files
  "isolated browser microVMs" under future hooks. 828 tests (2 new), golden run untouched
  (no behaviour changed). *Disproved by:* a sandbox meeting §19.3 — **not** by a registered tool.
- [ ] **A JS-rendered page is unreadable, and that is a Phase 5 prerequisite blocking a Phase 7
  deliverable.** Named by ADR-038 rather than left as "not yet": `http_get` returns an empty shell
  for anything built client-side, so a Cell told to read the world can read only the part of it
  that ships HTML. The unblock is §19.3's sandbox, which is Phase 5 and does not exist.
  `ResourceType.BROWSER_MINUTES` (§2.2, declared since migration 0008, referenced by nothing) is
  the tenth reserved socket and says what shape the capability was meant to have — a metered,
  bounded session rather than a fetch. *Disproved by:* `sandbox.py`, or anything writing
  `browser_minutes`.
- [ ] **§23.2's liability figure is unmodelled — but the account is not missing.** Corrected
  2026-08-22: the previous wording ("no liability reserve exists (§13 is Phase 6+)") was wrong on
  both counts. §13 is Novelty Evaluation; liability is not a §13 concept. And `liability_reserve`
  is one of §31's **required Phase-1 accounts** — it exists in `accounts.py` and is already
  classified as a `SPEND_DESTINATION` ("a provision the Cell's activity incurred — cost, not
  transfer"). **What is missing is a policy that posts to it**, not the account. Until one exists
  the payload prints "not modelled" rather than a fabricated zero, which stays correct.
  *Disproved by:* `accounts.FIXED_ACCOUNTS`. The same wrong claim is still copied into
  `approval.py`'s `liability_minor_units` comment.
- [x] **The grant consumer — DONE** (2026-08-22), ADR-029. `promotion.py` + migration 0016. §31's
  core loop ("... -> allocate capital -> ...") finally closes: an approved `spend_request` grant
  allocates from `promotion_pool` and wakes the Cell under §17.2's "capital allocation" reason —
  **two sockets the spec reserved in Phase 1 and nothing had ever used**. Rung 7, not rung 9: two
  humans stand in every allocation and a structural test forbids the scheduler importing the
  module. The pool is a human-filled ceiling no Cell can raise; USD_REAL additionally needs §27.1's
  autonomy flag. ADR-027's rung-6 test was deliberately loosened to land this — that friction was
  its purpose. 636 tests (15 new); golden expectation 8 → 9 now covers the whole loop (**no
  USD_REAL movement**). Teeth-checked nine ways.
- [x] **README + LICENSE — DONE** (2026-08-22). `README.md` and `LICENSE` written; every factual
  claim in the README was verified against the repo rather than written from memory (test count,
  migration count, expectation version, each charter test id individually collectible, every linked
  doc present). **Secrets audit re-run rather than trusted:** no `.env`, `.db`, key or credential
  file has ever been committed, `.gitignore` covers all of them, and every `sk-ant-…` string in the
  tree is a synthetic canary inside a redaction test (`AAAA…`, `ZZZZ…`, `CHARTERC14CANARY`).
- **The repo stays private, deliberately** — not a gap, and not a task (checkbox removed: this is
  a standing decision that will never be "done"). `LICENSE` is all-rights-reserved and
  says so explicitly rather than leaving it inferred, because "the author forgot" and "the author
  decided" call for different behaviour from a reader. While private this is free to change; once
  published it is not, since terms cannot be retracted from versions people already hold. Swapping
  in a permissive licence is a one-commit change whenever publishing is actually intended.
- [x] **The §25.2 read-back — DONE** (2026-08-22), ADR-030. `outcome.py`, **no migration**: the
  assessment is derived from the hash-chained register and the ledger every time, the posture
  Charter C3 takes toward balances, because a stored copy is a second version that can disagree.
  **§8.5 fixed the design and the obvious measure was wrong twice.** A Cell's current mean Brier
  counts outcomes the approver already knew *and* forecasts registered after the money arrived — so
  the verdict rests only on the set that was **open at the instant of funding**, hash-chained
  before the outcomes were knowable and unarrangeable afterwards. Forecasts made while funded are
  reported beside the verdict, never inside it (§23.5, the same split ADR-027 drew between claimed
  and assessed tier). **Any overdue forecast blocks a verdict outright**, checked before any score,
  because a mean over the subset someone chose to resolve is the self-selected curve `prediction.py`
  exists to prevent — it looks excellent and means nothing, in the direction that favours
  promotion. **§10.3 forbade the other obvious measure:** "Explorers need no immediate revenue", so
  cost and revenue are recorded and never gated on; what is judged is calibration, on two
  non-collapsing dimensions (§10.2) — §8.5's reality gap and an absolute bar at the 0.25 a coin
  scores. Nothing acts on a verdict: upward that would be rung 8 without an argument, downward it
  would be §10.5's forbidden cull on an estimate with no Auditor to concur. 659 tests (23 new);
  golden expectation 9 → 10 now covers deliberate → queue → approve → allocate → resolve → assess
  (**no USD_REAL movement, balances byte-identical**). Teeth-checked twelve ways; one test passed
  for the wrong reason and was rewritten.
- [ ] **Aggregate-invoice reconciliation** — the half ADR-023 provably cannot do. Per-call reconciliation leaves ADR-020's sub-cent rounding overstatement exactly where it was (3.5¢ reconciles back through the same ceiling to the 4¢ already recorded); only an invoice *total* spanning many calls can post the correction. Additive: needs an invoice-level record, reusing all the per-call sign handling and breaker registration.
- [ ] **Forward recovery for the gateway** — ADR-022's deferred alternative, which belongs with the reconciliation plumbing. Rollback is atomic but loses the provider's reported usage, so a crashed call still needs a human. Recording the response durably before applying the accounting (a `settling` status) would let recovery finish the settlement automatically.
- [ ] Tighten the pre-call token estimate — `providers._estimate_tokens` is a deliberate over-estimate (2 chars/token). The provider's `count_tokens` endpoint would cut over-reservation sharply and make cost overruns (ADR-021) rarer.
- [x] **Experiment tracking — DONE** (2026-08-24), ADR-043. `experiments.py` + migration 0026 +
  four CLI verbs. **The largest socket cluster in the repo, and most of it was live plumbing rather
  than dead columns** — `experiment_id` threaded through `gateway`/`prediction`/`ledger`,
  propagated onto ledger entries by `reservations.settle`, and `mitosis predict --experiment <id>`
  validating nothing. Seven sections reference an experiment and none defines one; **§2.6 defines
  the *report*, and §2.5 immediately above it ("Balances are derived") makes that report a derived
  view rather than a stored row.** So there is **no `experiment_results` table despite §31 listing
  one** — a stored outcome is where §0.3 leaks back in, and a guard test defends the refusal.
  **Stage belongs to the Cell**: §10.5's singular `stage_reached` beside plural `experiment_ids`,
  §27.2's "current experiment/stage", and §13.1's ratio all agree, so §25.1's nine rungs are the
  only ladder and Phase 2's "stage gates" are the gates between them. §15.1's singular "current
  experiment" is a partial unique index. **Found while building: a dead Cell's running experiment
  leaked its §9.2 slot forever**, so the coroner seam now settles before it reports, abandoning
  rather than concluding. `max_parallel_experiments` is enforced as a **third refusal shape**
  (ADR-031's two plus one that frees when an experiment concludes), deliberately outside
  `PopulationError`. 916 tests (29 new); golden expectation 19 → 20 with **balances identical in
  every book**, and `coroner_reports.stage_reached` finally non-null after being empty since
  migration 0007. Teeth-checked sixteen ways; hand-verified end to end on a live colony.
- [x] **Experiment attribution for metered ops — DONE** (2026-08-25), ADR-044. **No migration.**
  This entry was scheduled as "add `resource_usage.experiment_id`" and the claim was wrong about
  the mechanism — BUILD_RECORD, `golden.py`'s version-20 note and `experiments.py`'s own docstring
  all repeated it. `resource_usage.reservation_id` is **NOT NULL** (Amendment A6 requires it) and
  `reservations.experiment_id` has existed since **migration 0001**, so every metered row was
  always one join from its experiment. The gap was the **stamp**: `gateway` threaded it and
  `tools`, `external_actions` and `deliberation` did not. The column is now *refused* by a guard
  test — it would be a second answer to a question the reservation already owns, §2.5's
  cached-derivation trap reached from the metering side. **The visible bug was the abstention; the
  real one was the undercount.** `human_minutes` reported `None` with a reason, which announces
  itself, while `resource_spend_minor_units` reported a *definite* shadow cost with every tool call
  and every human minute missing from it — and §2.6's real-cash line read 0 for any experiment
  whose Cell simply ran, because a wake never named its experiment to the gateway. **Attribution is
  derived from §15.1's one current experiment and never supplied**, because a parameter is a place
  to put a different one (§0.3 from the expense side); a structural test asserts no metering entry
  point grows it. Human labour reports **billed + subsidised** — summing `quantity` alone would
  make the colony's human cost *smaller* the more of it a person absorbed unpaid, hiding the exact
  figure §1.1 subtracts. 931 tests (15 new); golden expectation 20 → 21 with **balances identical
  in every account in every book**. Teeth-checked twelve ways; one test could not have failed and
  was rewritten to conclude the experiment mid-call. **The live run found the deliberation half** —
  a report reading "Model calls: 0" for a Cell that had just deliberated under the experiment.
- [x] **`ProposalKind.EXPERIMENT` wired — DONE** (2026-08-25), ADR-045. **No migration.**
  `experiment_grants.py` + an `ExperimentSpec` payload. The kind existed since migration 0013 and
  appeared **nowhere else in `src/`**: a Cell could propose an experiment, it reached §23's queue,
  an operator could approve it, and the grant sat inert — every experiment in the colony was one a
  person typed by hand, and `experiments.proposal_id` could never be filled. The golden run had
  been carrying a permanently `pending` experiment request since expectation version 5.
  **§0.2's table decides what the kernel may judge**: it puts "experiments" in the *mutable Cell*
  column, so the hypothesis is the Cell's and nothing reads or rewrites it; what the kernel gates
  is the §9.2 slot and the §25.1 rung. **The rung has nowhere to be named** — `ExperimentSpec` has
  no field for one (`FORBIDDEN_RUNG_FIELDS`, the third tripwire in `proposal.py`) and
  `entitled_rung` reads `promotions`, so §25.1's "no strategy moves directly from synthetic success
  to autonomous commerce" is a property of the schema. **"Reached" and "entitled to" are different
  questions over the same two tables**: `stage_reached` unions promotions with experiments and
  `entitled_rung` deliberately does not, or ADR-043's recorded-but-unenforced operator `--rung`
  would become a permanent ratchet. The consumer is a new module because `approval` imports
  `deliberation` imports `experiments` — the registry/executor split, made a third time. 949 tests
  (18 new); golden expectation 21 → 22 with **balances identical in every book**, pinning a
  `running` experiment for the first time. Teeth-checked twelve ways; hand-verified end to end.
- [x] **`ProposalKind.STRATEGY` decided — DONE** (2026-08-26), ADR-046. **No migration.** The last
  kind whose approval led nowhere, and the obvious reading — that it needed a consumer like the
  other four — is wrong: **a strategy names nothing to do, so approving one *is* the act.**
  `proposal.STATEMENT_KINDS` now says so. What it lacked was a *consequence*, and the absence had
  produced a live bug reproduced before the fix: an approved strategy reached the Cell nowhere
  (approved, rejected, expired and never-reviewed all rendered identically in its own proposal
  log), **and its inert grant lapsed and woke the Cell to re-propose something a person had already
  agreed to** — §23.3 regenerates expired *actions*, and a statement is not one. The Cell now sees
  a **standing strategy** (§15.1's "relevant epigenetic state", the last context source that clause
  named which nothing implemented) derived from the queue and stored nowhere, plus what a person
  decided about every proposal **and their reason** — the only human-authored text a Cell ever
  receives. Safe to give only because §23.4's `repeat_after_rejection` detector already existed.
  962 tests (13 new); golden expectation 22 → 23 with **balances identical in every book**, and
  `expired` 4 → 5 while `regenerated` stays 4. Teeth-checked ten ways; hand-verified end to end.
- [ ] §24 gateway features left out of the slice: routing by task type (§24.3), controlled retries (a retry after `execution_unknown` risks double-billing), model competition, and reacting to provider drift as a §8.4 regime change (drift is *recorded* — `resolved_model`/`api_version` — but nothing consumes it). **Structured-output validation was struck from this list** (2026-08-22): it exists, at the deliberation layer rather than the gateway — `proposal.parse` is strict, `extra="forbid"`, with `FORBIDDEN_FIELD_SENSE` as a schema tripwire. Anything added at the gateway must not duplicate it. *Disproved by:* `proposal.parse`.
- [ ] Remaining CLI — **narrowed 2026-08-22** from `list-cells/show-cell/kill-cell/ledger/verify-ledger`, most of which had already landed among the CLI's 42 verbs. Still genuinely absent: **`list-cells`** (`status` prints counts and per-status/per-type tallies, but no roster) and **`ledger`** (no transaction browser). Struck: `verify-ledger` (`status` prints per-book conservation and `ledger.verify_chain`; `calibration` prints `prediction.verify_chain`), `show-cell` (substantially covered by `cell-fitness`), and `kill-cell` (`reap` kills on objective criteria — a *forced* operator kill is a §10.5 question, not an additive CLI verb, and should be argued before it is built). Purely additive, no blockers. *Disproved by:* `mitosis --help`.
- [x] **A dead Cell's estate — DONE** (2026-08-22), ADR-028. `kill()` now releases the dead Cell's
  open reservations and returns its residual cash to `colony_treasury`, inside the same transaction
  as the death. **Charter C8 is the load-bearing clause and not for the obvious reason: an open
  reservation *is* standing authorisation to spend**, so a dead Cell holding one is the plainest
  instance of "dead Cells cannot act". The money is capital movement, never spend (`accounts.py`
  had already decided this). A reservation with an `external_operation_id` is deferred to the
  sweeper per ADR-022 — but **death is never blocked by it**, or a Cell could survive by keeping a
  call in flight. Golden expectation 7 → 8, and the diff is the bug report: the scenario had been
  stranding **3450 USD_SIM per replay since version 1**. 621 tests (13 new); teeth-checked eight
  ways. Also fixed an intermittent Charter-property failure this surfaced but did not cause —
  property tests that build a database per example were charging migration time against
  Hypothesis's 200ms deadline.
- [ ] An audited path to change population limits after `init` (`set_limits_if_absent` is write-once, and lowering a cap below the current population needs a stated policy). Blocks golden-run coverage of displacement. See FUTURE_BUILD_HOOKS.
- [ ] Wiring the simulated clock into USD_SIM/synthetic timestamps (still the *only* remaining reason a real colony can't do true byte-identical replay, since ids are seeded but timestamps still aren't). `max_births_per_epoch` no longer belongs on this line — it is enforced as of ADR-031, against `clock.current_epoch` with the epoch stamped on the Cell at birth precisely *because* the two clocks are still unmixed.
- [ ] Giving the event *outbox* a real destination. **Reworded 2026-08-22** — the previous entry
  ("wiring the outbox into a real dispatcher") overstated the work: `events.dispatch_outbox(conn,
  publisher)` already exists, insertion-ordered, one commit per event, with the same at-least-once
  contract as inbox delivery. The seam is built and takes an injected publisher. What is missing is
  a publisher implementation and something that calls it. The inbox got its first producer and
  consumer with the agent loop (`enqueue_wake` / `run_ready_wakes`). *Disproved by:*
  `events.dispatch_outbox`.
- [ ] Shadow-pricing `resource_usage.minor_units` from a raw quantity instead of a caller-supplied
  figure. **Split 2026-08-22:** this entry used to lead with "model gateway/provider
  identification (needed before per-provider real-spend caps can be enforced)", and that half
  landed with the gateway slice. `reservations.provider` and `model_calls.provider` exist
  (migration 0010), and `real_spend_breaker` states plainly that §5.1's "max real spend per
  provider" **is** enforced, via `_concurrent_reserved_for_provider` and
  `_settled_spend_for_provider_since`. Only the shadow-pricing half remains. *Disproved by:*
  `real_spend_breaker._concurrent_reserved_for_provider`.
- [ ] **A dangling `experiment_id` is unvalidated inside the kernel.** ADR-044 validated the two
  operator-facing paths; `reservations.request`, `prediction._register_locked`,
  `ledger.post_transaction` and `gateway.call_model` all accept the id and check nothing. They sit
  *below* `experiments` in the layering, so this needs an injected seam rather than an import — the
  `sweeper.ExternalOperationChecker` shape. A dangling id fails silently and only ever *subtracts*
  from a §2.6 report. *Disproved by:* anything in `src/` raising on an unknown `experiment_id`
  below the CLI layer.
- [ ] Reconciling resource_usage against actual sandbox/model-gateway logs (Amendment A6's other half). **Half-unblocked 2026-08-22:** the entry said "no such logs exist until Phase 4/5", but the model-gateway half now does — `model_calls` records provider, resolved model, API version and reported usage per call. The *sandbox* half is still genuinely blocked until Phase 5. *Disproved by:* the `model_calls` table.

## Later
- [ ] Phase 2 flight simulator → Phase 3 evolutionary validation (pre-registered) → Phases 4–10 per directive §28
