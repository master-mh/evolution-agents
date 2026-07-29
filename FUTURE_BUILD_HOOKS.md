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
