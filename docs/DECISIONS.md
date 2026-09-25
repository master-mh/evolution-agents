# MITOSIS — Architecture Decision Records

This is a living log of decisions that had real alternatives, reversed an earlier draft, or need
their rationale preserved for a future reader — not a restatement of every clause in
[`docs/SPEC.md`](SPEC.md). Most spec content is declarative and doesn't need an ADR; it gets one
here only where "why this and not the obvious alternative" isn't self-evident from the spec text
alone.

Numbering is sequential and permanent — an ADR is never renumbered or deleted, only superseded.
Update this file whenever a decision like this is made or reversed (§30.1 coding rule).

Template: **Status** · **Spec ref** · **Context** · **Decision** · **Consequences**.

---

## ADR-001: Real settled net profit is the only ultimate success metric

- **Status:** Accepted
- **Spec ref:** §1 (directive change #1)
- **Context:** v0.1 let novelty scores, synthetic profit, evidence credits, and reproducibility
  stand in as success signals throughout. Nothing forced a reckoning with real money, so a colony
  could look successful indefinitely while never approaching commercial viability.
- **Decision:** The colony's ultimate success proxy is real settled net profit after real costs,
  with an autonomy-adjusted variant that exposes hidden human labour and subsidy. Novelty,
  synthetic profit, evidence credits, and reproducibility are explicitly demoted to *pre-revenue
  proxies* — useful for early phases, never the final measure.
- **Consequences:** Every phase needs an honest primary metric even before real revenue exists
  (§27.1 North Star table, ADR relationship: this is why that table exists). Reports must
  separate real from synthetic profit permanently (see ADR-002) — there is no phase where that
  separation is allowed to lapse.

## ADR-002: Three separate monetary books, no implicit bridge

- **Status:** Accepted
- **Spec ref:** §2 (directive change #2)
- **Context:** v0.1 conflated real API/hosting spend, fictional synthetic-market revenue, and
  compute/human labour into one conservation equation, so a Cell could appear profitable purely
  by earning fictional dollars while consuming real paid resources.
- **Decision:** `USD_REAL`, `USD_SIM`, and `RESOURCE` are separate books, each independently
  conserved (§2.3). No transaction crosses books (Charter C1). There is no automatic
  `USD_SIM → USD_REAL` conversion. Model-call costs are recorded as real `USD_REAL` provider
  charges *and independently* mirrored as a synthetic expense in `USD_SIM` — the mirror is a
  parallel synthetic entry, never a cross-book transfer.
- **Consequences:** Any future real-money bridge must be an explicit, human-approved, recorded
  deployment decision — never modeled as a currency conversion. Reporting must always show real
  cash, synthetic profit, resource consumption, and a reality-gap estimate side by side (§2.6).

## ADR-003: Ledger entries carry one signed amount, not amount + direction

- **Status:** Accepted
- **Spec ref:** §3.3 (Amendment A3, accepted pushback 3)
- **Context:** The revision directive's entry schema had both a signed amount and an independent
  `direction` field, which can silently disagree with each other and is a well-known source of
  reconciliation bugs in ledger systems.
- **Decision:** `ledger_entries.amount_minor_units` is a single signed integer; the sum over a
  transaction must equal zero. There is no `direction` column. A debit/credit label, if displayed,
  is derived from the sign for display only.
- **Consequences:** Removes an entire class of "amount says one thing, direction says another"
  bugs by construction. Any future display layer must derive credit/debit labeling from sign, not
  store it separately.

## ADR-004: Inbox/outbox pattern for at-least-once delivery; history is append-only

- **Status:** Accepted
- **Spec ref:** §3.5–§3.6 (directive change #3)
- **Context:** Asynchronous event processing will redeliver events and can partially fail
  mid-handler. Editing historical ledger rows to "fix" a reconciliation mismatch would break the
  tamper-evident hash chain (§3.4) and hide what actually happened.
- **Decision:** A handler atomically (1) checks the input event is unprocessed, (2) applies
  state + ledger changes, (3) writes produced events to the outbox, (4) marks the input processed
  — all in one transaction; a dispatcher publishes from the outbox after commit. External
  reconciliation is posted as **new** transactions; historical transactions are never edited.
- **Consequences:** Makes event handlers idempotent by construction (Charter C6) rather than by
  handler-specific discipline. Reconciliation adjustments are always visible in the ledger as
  their own entries, preserving the audit trail.

## ADR-005: One canonical reservation state machine, including `requested`

- **Status:** Accepted
- **Spec ref:** §4.4 (Amendment A4, accepted pushback 4)
- **Context:** The revision directive specified two divergent reservation state lists in
  different sections, which would have forced an arbitrary implementation choice and made the
  Charter's crash-recovery guarantee (C7) ambiguous.
- **Decision:** A single machine is normative: `requested → reserved → {settled,
  partially_settled, released, execution_unknown}`, with `execution_unknown` and `disputed` as
  reconciliation states that resolve into `settled`/`partially_settled`/`released`. Terminal
  states are `settled`, `released`, and `disputed→resolved`. Unknown external operations are
  reconciled by the sweeper — **never auto-released** — because auto-releasing a reservation whose
  external effect may have already happened risks a double-spend.
- **Consequences:** Every reservation-touching code path (kernel, sweeper, CLI, tests) targets
  exactly one FSM. Crash recovery has one well-defined answer instead of two to reconcile. See
  `docs/DECISIONS.md` companion state-machine table (tracked separately, Phase 0 artifact) for the
  full transition diagram.

## ADR-006: Global real-spend circuit breakers are independent of Cell budgets

- **Status:** Accepted
- **Spec ref:** §5 (directive change #5)
- **Context:** A per-Cell budget check is not sufficient to bound total real spend — many Cells
  under budget individually can still blow through a colony-wide real-money limit, especially
  under concurrency where reservations race each other.
- **Decision:** Global real-spend caps are enforced as a separate control, fail-closed, and count
  *reserved* (not just settled) spend, so concurrent reservations can't collectively exceed the
  cap before any of them settle (Charter C5).
- **Consequences:** Requires the reservation layer to expose a live "total reserved + settled"
  figure the breaker can check synchronously before authorizing a new reservation. This is a
  day-one requirement (§5.1), not deferred to a later phase, because real-money safety can't be
  retrofitted.

## ADR-007: The colony owns a simulated clock; synthetic timing never touches wall-clock

- **Status:** Accepted
- **Spec ref:** §6 (directive change #6)
- **Context:** Wall-clock-driven synthetic markets make golden-run replay non-deterministic and
  make it impossible to fast-forward thousands of epochs for evolutionary experiments.
- **Decision:** All synthetic-market timing is driven by a colony-owned simulated clock with
  explicit modes and event scheduling (§6.2–§6.3); simulated and real events never interleave
  without explicit conversion metadata (§17.1).
- **Consequences:** Enables `mitosis advance-time --days N` as a first-class CLI operation and
  makes golden-run replay deterministic by removing wall-clock as an input.

## ADR-008: Phase 3's evolution-vs-random gate is softened to timeboxed, pre-registered, parallel-track

- **Status:** Accepted
- **Spec ref:** §7.4, §28 Phase 3 (Amendment A1, accepted pushback 1)
- **Context:** The revision directive treated "evolved Cells beat random mutation" as a hard
  engineering milestone gating Phase 4. But in the flight simulator, mock cells' trait→performance
  map is author-defined — so a result there validates the *selection machinery* working as
  designed, not that LLM-driven Cells will actually evolve usefully. Treating it as a pass/fail
  engineering gate would either block progress on a circular test or quietly launder a
  research-grade claim into an engineering fact.
- **Decision:** Phase 3 is timeboxed and pre-registered (hypothesis, metric, seed count declared
  before running). The gate is soft: a pre-registered effect-size confidence interval excluding
  zero in ≥1 scenario suite, diversity persists, regime adaptation occurs, reciprocal-credit
  attacks fail, founder luck is bounded. Deeper validation continues as a parallel track alongside
  Phase 4 — it does not block Phase 4 from starting. Every report carries the circularity caveat.
- **Consequences:** Phase 4 (model gateway) can start on schedule even if deeper evolutionary
  validation is still running. Any dashboard or report surfacing Phase 3 results must carry the
  scope caveat verbatim, not just the headline number.

## ADR-009: Birth-by-displacement may only evict objectively-failing Cells

- **Status:** Accepted
- **Spec ref:** §9.3 (Amendment A2, accepted pushback 2)
- **Context:** Forecast-based displacement (killing a Cell because a candidate child is
  *predicted* to outperform it) creates an obvious gaming surface — a Cell family could manufacture
  optimistic forecasts to evict unrelated competitors, and forecasts are unfalsifiable at decision
  time.
- **Decision:** Displacement targets only Cells already meeting an objective failure criterion
  (bottom quantile of realised stage progression, or already meeting a §10.5 death criterion). A
  proposed child's forecast can never trigger a kill. If no objectively-failing Cell exists and the
  colony is at capacity, the birth waits.
- **Consequences:** Removes forecast-gaming as an attack vector by construction. Population growth
  can stall at capacity when no Cell is objectively failing — that's an accepted tradeoff, not a
  bug to route around later.

## ADR-010: Lineage caps use genome parentage only; module ancestry is tracked separately

- **Status:** Accepted
- **Spec ref:** §9.4 (Amendment A10)
- **Context:** Horizontal module transfer (§16) means a Cell can inherit code from a module
  lineage that's distinct from its genome lineage. Conflating the two would let a popular module
  count against the population share of every Cell that ever imported it, or let genome-cap
  enforcement be gamed by routing traits through module transfer instead of reproduction.
- **Decision:** Lineage, for the purposes of population-share caps and founder-effect control, is
  defined strictly by genome parentage. Module/horizontal-transfer ancestry is recorded (for
  provenance and knowledge-graph purposes) but does not count toward lineage caps.
- **Consequences:** Population-control code only ever walks the genome-parentage graph. Module
  lineage tracking is a separate data path (`module_lineage`, §31) with no bearing on carrying
  capacity.

## ADR-011: Deterministic event ordering via `(effective_time, priority, event_id)` tie-break

- **Status:** Accepted
- **Spec ref:** §17.1 (Amendment A5)
- **Context:** At-least-once delivery plus concurrent event sources means two events can be
  "ready" at the same simulated instant. Without a defined tie-break, replaying a golden run can
  process them in a different order than the original run and diverge.
- **Decision:** The scheduler imposes a total order on ready events using the tie-break key
  `(effective_time, priority, event_id)`. Simulated and real events never interleave without
  explicit conversion metadata.
- **Consequences:** Golden-run replay (§26) is deterministic given the same event log. Every event
  producer must supply a stable `priority` and a unique `event_id` — there is no "unordered batch"
  escape hatch anywhere in the kernel.

## ADR-012: Idempotency keys are globally unique and namespaced by operation type

- **Status:** Accepted
- **Spec ref:** §3.2 (Amendment A9)
- **Context:** A bare idempotency key risks collisions across unrelated operation types (e.g. a
  reservation and a birth both minting key `"42"`), which would silently dedupe two unrelated
  operations against each other.
- **Decision:** Idempotency keys are namespaced `{operation_type}:{natural_key}` and unique
  globally, not just per-table.
- **Consequences:** Any new operation type introduced in later phases must define its own natural
  key and namespace prefix as part of that feature's design — this isn't optional boilerplate.

## ADR-013: The Colony Charter is a traceability matrix to named CI tests, not prose

- **Status:** Accepted
- **Spec ref:** §0.1 (Amendment A13)
- **Context:** Constitutional-sounding invariant lists are easy to write and easy to silently
  violate later, because nothing forces an implementation change to be checked against them.
- **Decision:** Every constitutional clause (C1–C15, growing by phase) maps one-to-one to a named
  property-test ID that runs in CI (`charter_*`). Breaking a Charter test is, by definition, a
  kernel-guarantee change and cannot merge as an ordinary Cell-visible change — it requires
  explicit human review. Relaxing a guarantee is itself a reviewed kernel change, never a silent
  side effect of an unrelated PR.
- **Consequences:** Phase 1 must ship `charter_ledger_balanced`, `charter_conservation_per_book`,
  `charter_balance_matches_ledger`, `charter_no_overspend`, `charter_realspend_cap`,
  `charter_idempotent_handlers`, `charter_crash_recovery`, `charter_dead_cell_inert`,
  `charter_carrying_capacity`, `charter_audit_complete`, `charter_canonical_forms` (C1–C11) before
  Phase 1 can be called done. Later Charter clauses (C12–C15) gate Phases 4–6.

## ADR-014: Sandbox isolation is tiered — Docker for MVP, gVisor/Firecracker before real-facing

- **Status:** Accepted
- **Spec ref:** §19 (directive change #19)
- **Context:** Full microVM isolation from day one adds engineering cost with no payoff while the
  system only touches the synthetic economy; but shipping real-facing code execution on
  container-only isolation would be an unacceptable security posture once Cells can reach real
  networks or real money.
- **Decision:** MVP sandbox boundary is Docker-level. Before any real-facing execution path opens
  (Phase 5+ approaching Phase 9), isolation upgrades to gVisor/Firecracker-class microVMs, with
  egress allowlists, SBOM, and artifact signing required at that boundary.
- **Consequences:** Phase 1 does not need microVM infrastructure. Whoever picks up Phase 5
  sandboxing must not treat Docker isolation as sufficient — it's explicitly scoped as an interim
  MVP boundary, not a permanent one (Charter C12 depends on this).

## ADR-015: Shadow-economy taint uses an adversarial-lineage rule with clean-room migration

- **Status:** Accepted
- **Spec ref:** §18 (directive change #18)
- **Context:** Cells and modules that emerge from adversarial/gaming strategies in the shadow
  economy shouldn't be able to migrate to real-facing execution just because they eventually stop
  misbehaving — but permanently blacklisting every descendant of a tainted lineage forever would
  also discard legitimately reformed or independently-reimplemented work.
- **Decision:** Provenance labels track taint through lineage (adversarial-lineage rule, §18.2).
  A clean-room migration path exists: work that is independently re-derived without carrying
  forward the tainted artifact's actual code/data can acquire new, untainted provenance.
- **Consequences:** Charter C13 (adversarial-taint artifacts cannot migrate to real-facing
  execution) is enforceable only if the clean-room path is implemented rigorously enough that it
  can't be used as a taint-laundering shortcut — this needs its own dedicated test coverage in
  Phase 6, not just a provenance-flag check.

## ADR-016: Solo-operator model — approval SLAs, vacation mode, metabolic-rate alarm

- **Status:** Accepted
- **Spec ref:** §23.3 (Amendment A19)
- **Context:** The system is designed to be run by one human, not an on-call team. A human-approval
  gate with no SLA or fallback either blocks the colony indefinitely when the operator is
  unavailable, or gets bypassed under pressure — both are bad outcomes for a system that's
  supposed to fail closed.
- **Decision:** Approval requests carry an SLA and expire (§23.3) rather than blocking forever or
  auto-approving. A vacation mode auto-pauses external-facing phases when the operator is known to
  be unavailable. A colony metabolic-rate alarm flags when spend/activity patterns diverge from
  normal while unattended.
- **Consequences:** Any phase that introduces a human-approval gate (Phase 8+) must define its SLA
  and its expiry behavior (fail closed, not auto-approve) as part of that feature, not as an
  afterthought.

## ADR-017: Golden-run comparison is semantic invariants plus hash, not raw byte equality

- **Status:** Accepted
- **Spec ref:** §26.2 (Amendment A12)
- **Context:** Pure byte-for-byte replay comparison is brittle against any legitimate schema
  evolution — a harmless added field would break every golden run and either freeze the schema
  forever or force golden-run expectations to be discarded on every change.
- **Decision:** Golden-run expectations are versioned. Comparison checks semantic invariants
  (conservation, balances, lifecycle correctness) *plus* a hash, with an explicit migration path
  for updating expectations when the schema legitimately changes.
- **Consequences:** Schema evolution doesn't require throwing away replay history, but every
  legitimate golden-run expectation change must go through the migration path deliberately — it's
  not something a routine PR should trigger silently.

## ADR-018: Genome content addressing with a canonical hash; liability-linked inheritance is explicit

- **Status:** Accepted
- **Spec ref:** §16 (directive change #16, Charter C11)
- **Context:** Without a canonical hash, two structurally identical genomes could be treated as
  different entities depending on incidental serialization differences, breaking lineage tracking,
  deduplication, and reproducibility. Separately, inheritance needs to distinguish assets a child
  simply reuses from assets that carry forward real obligations (e.g. outstanding liabilities,
  active commitments).
- **Decision:** Every genome has a canonical hash computed over a defined canonical form (Charter
  C11). `cell_genomes` inheritance classes explicitly distinguish liability-linked inherited assets
  from ordinary inherited assets (§16.3).
- **Consequences:** Genome deduplication and lineage queries can rely on hash equality rather than
  structural diffing. Any future serialization change to genome fields must preserve or explicitly
  version the canonical form, or existing hashes silently stop being comparable.

## ADR-019: Lineage is tracked on the Cell, not the genome, while genomes are placeholders

- **Status:** Accepted
- **Spec ref:** §9.2, §9.4 (Amendment A10), §16.1 (with ADR-018)
- **Context:** §9.4 defines lineage "strictly by genome parentage", in explicit contrast to
  *module* ancestry (horizontal transfer), which must not count toward lineage caps. Taken
  literally against the Phase 1 kernel, that definition is unimplementable: genomes are content
  addressed (ADR-018), and Phase 1 genome content is a placeholder carrying only `cell_type`, so
  every Cell of a given type hashes to one genome row. Deriving lineage from genome parentage today
  would place every commercial Cell in the colony into a single lineage and fire
  `max_lineage_population_fraction` on Cells with no ancestral relationship at all — the opposite
  of the founder-effect control §9.4 asks for. There is also a structural problem independent of
  Phase 1: under content addressing, an unmutated child *is* its parent's genome, so a genome
  parentage edge for it would be a self-loop.
- **Decision:** Vertical descent is recorded on the Cell (`cells.parent_cell_id`, plus immutable
  denormalized `founder_cell_id`/`generation`), and that tree is what `max_lineage_population_fraction`
  is enforced against. Genome parentage (`cell_genomes.parent_genome_hashes`) is recorded as well,
  but only where a mutation actually produced different content. Amendment A10's substance — that
  lineage means vertical descent and never horizontal module sharing — is preserved: a shared
  module, and equally a shared genome, never creates a lineage edge.
- **Consequences:** Lineage caps work correctly today rather than waiting on Phase 5 genome
  content, and both trees are available: the Cell tree is complete, the genome tree is the richer
  record once genomes carry real content, and the two converge without a migration. The
  denormalized `founder_cell_id`/`generation` are re-derivable and checked by
  `lineage.verify_lineage_integrity()`, so the optimization cannot silently drift. Separately, the
  cap is enforced strictly and per §9.3 a birth that cannot be licensed is refused rather than
  queued — which means a small colony genuinely cannot reproduce (any second-generation Cell in a
  4-Cell colony is already 40% of it). Seeded founders are exempt, since a founder has no ancestor;
  growing past the seed therefore requires enough founders or a deliberately raised cap.

---

## ADR-020: Model-call cost is computed in micro-USD; the ledger rounds up to the cent

- **Status:** Accepted
- **Spec ref:** §2.2 (USD_REAL), §24.1 (`cost estimate` / `reconciled cost`), §30.1 (money rule),
  Charter C5, Charter C11
- **Context:** USD_REAL's minor unit is the cent (`money.MINOR_UNITS_EXPONENT`), which §2.6's own
  reporting example assumes when it prints `0.08 USD_REAL`. A single model call routinely costs a
  fraction of a cent — 1,000 input tokens on `claude-opus-5` is 0.5 cents — so the cent is too
  coarse to hold a per-call figure. Computing per-call cost directly in cents would round most
  individual calls to 0 or 1 and make cost attribution meaningless exactly where the colony needs
  it: per Cell, per experiment, per provider.
- **Alternatives considered:** (a) Widen USD_REAL's minor unit to micro-dollars. Rejected: it
  changes the meaning of every existing USD_REAL amount, invalidates the golden run and the
  real-spend limits, and contradicts §2.6's two-decimal reporting. (b) Round each call to the
  nearest cent. Rejected: rounding down understates real spend, and Charter C5's caps would then be
  computed from a figure smaller than the true bill — the breaker would fail *open*. (c) Carry
  fractional remainders in a colony-level rounding account. Rejected as premature: it adds an
  account outside `accounts.FIXED_ACCOUNTS` and a reconciliation concern, to solve an error that
  provider-invoice reconciliation will resolve properly anyway.
- **Decision:** Cost is computed and stored exactly in **micro-USD** (1e-6 USD) on the
  `model_calls` row, and converted to USD_REAL minor units by rounding **up** for the ledger
  posting. Rounding up is the same fail-closed posture Charter C5 takes elsewhere: the colony may
  believe it spent slightly more real money than it did, never less.
- **Consequences:** Stated plainly because it is real: the ledger overstates real spend by up to
  0.999 cents per call, which at Phase 4 volumes of cheap calls is a material relative error. The
  exact micro-USD figure on every row is what §24.1's `reconciled cost` trues up against once a
  provider invoice exists — until then `reconciled_micro_usd` is always NULL and the overstatement
  stands. Sub-cent-per-call workloads should read `cost_actual_micro_usd`, not the ledger, for
  per-call cost attribution.

---

## ADR-021: A model call that costs more than it reserved is still recorded in full

- **Status:** Accepted
- **Spec ref:** §4 (two-phase spend), §4.4, §5.2, Charter C4, Charter C5
- **Context:** The gateway reserves a worst-case estimate before calling a provider, then settles
  at the provider's reported usage. `reservations.settle` refuses a settlement above the
  reservation's `maximum_amount` — that refusal *is* Charter C4. But a provider that reports more
  usage than the estimate predicted has already billed for it: the money is gone before the kernel
  learns the number. The two obligations pull apart. C4 says a Cell cannot overspend its authorised
  budget; the ledger's job is to state what actually happened.
- **Alternatives considered:** (a) Clamp the settlement at the cap and record nothing further.
  Rejected: the ledger then records *less* real spend than the provider billed, so Charter C5's
  hour/day/month caps are computed from an understated figure and the circuit breaker drifts
  progressively further from reality with every overrun — the failure compounds silently and in the
  dangerous direction. (b) Reserve so conservatively that an overrun is impossible. Rejected: the
  bound is the full context window times the output price, which would make the concurrent-reserved
  cap unusable and starve normal calls. (c) Treat the overrun as a liability rather than an
  expense. Rejected as Phase 9 machinery (`liability_reserve` exists for real obligations); the
  charge here is settled, not owed.
- **Decision:** Settle at the cap, then post the shortfall as a separate, directly-posted
  `model_call_cost_overrun` USD_REAL transaction from the Cell's cash to `external_expense`, with a
  loud audit event. Charter C4 governs **authorisation** — whether a Cell may commit to a spend —
  and the reservation enforced it at the only moment enforcement could change the outcome.
  Recording a charge that has already been incurred is accounting, not authorisation.
- **Consequences:** This is the only place in the kernel that posts USD_REAL spend outside a
  reservation, so it needs to stay rare and visible; it is one transaction type, audited every
  time. It can drive a Cell's cash negative, deliberately — an overdrawn Cell then fails every
  subsequent `reservations.request` balance check and stops spending immediately rather than
  quietly continuing. Because overruns are not settlements, every real-spend query had to learn
  about them, and anything that posts an external USD_REAL charge in future must be registered the
  same way or the caps will not see it. Note that `real_spend_breaker._REAL_SPEND_TRANSACTION_TYPES`
  is **not** yet the single source it looks like: the global window query reads the tuple, but
  `_settled_spend_for_provider_since` hardcodes the same two types in its own SQL. Both are correct
  today; a third type added to the tuple alone would be counted globally and missed per-provider.
  Logged in FUTURE_BUILD_HOOKS.

---

## ADR-022: The gateway resolves one paid call in one transaction; a crash rolls back to before it

- **Status:** Accepted
- **Spec ref:** §4.4, §24, §2.4, Amendment A6, Charter C4, Charter C7
- **Context:** Charter C7 is implemented one reservation at a time: `reservations.settle`/`release`
  each post their ledger transaction and update `reservations.status` inside a single write
  transaction, so a crash cannot be observed between the two. One paid model call is not one
  reservation. It settles USD_REAL, may post an overrun, meters two token types, settles a RESOURCE
  reservation, mirrors into USD_SIM and marks a `model_calls` row — six movements describing one
  external charge. Performed as six transactions (as they first were), a crash between any two left
  real money spent against a call still recorded as `reserved`, with nothing able to say which
  steps had run. `sweeper.py` had no knowledge of `model_calls`, so there was no recovery path and
  no operator verb. Critically, **every existing invariant stayed green in that state** —
  conservation balances and the hash chain validates when a reservation settles and its call row is
  never updated — so nothing would have reported it.
- **Alternatives considered:** (a) **Forward recovery**: record the provider response durably
  first, add a `settling` status, and have a recovery routine finish the remaining steps from the
  recorded usage. Strictly more capable — it preserves the usage figures a crash otherwise loses —
  but it needs a new status, a migration, a resume routine and a second idempotency story for
  every step, and it can only ever be *better* than rollback on the narrow window between the
  provider replying and the commit. Deferred, not rejected: it becomes worth building alongside
  §24.1 invoice reconciliation, which needs the same recorded-usage plumbing. (b) **Leave it and
  rely on the ledger's invariants.** Rejected: the invariants demonstrably do not see this state.
  (c) **Widen the transaction to include the provider call** so the reservation and the call commit
  together. Rejected outright — it would hold a SQLite write lock across a network round-trip, and
  it would destroy reserve-before-execute, whose entire value is that the authorisation is durable
  *before* the money can be spent.
- **Decision:** `_handle_success` and `_handle_failure` each hold one `BEGIN IMMEDIATE` and compose
  `_*_locked` cores of `reservations`, `resource_metering` and `ledger` — the same
  core-plus-wrapper split `ledger._write_transaction` and `audit.record` already used. Steps 1–3
  (reserve USD_REAL, reserve RESOURCE, insert the `model_calls` row) stay outside it deliberately:
  they must be durably committed *before* the external call, or reserve-before-execute means
  nothing. Recovery is two parts, in dependency order: `gateway.GatewayOperationChecker` tells the
  sweeper what an expired model-call reservation meant, then `gateway.resolve_stranded_calls`
  brings the `model_calls` row into agreement with it. `mitosis sweep` runs both.
- **Consequences:** No reachable state has a model call's money partly moved. A crash rolls back to
  the post-reserve, pre-response state, which is **honest but not complete**: the provider may have
  billed us, and the response — the only record of what for — is gone. That resolves to
  `execution_unknown` with the funds still committed, exactly as C7 requires of an unresolvable
  external operation, and it stays there until reconciliation. RESOURCE reservations are released
  instead, since no provider can bill an internal shadow price. The `_*_locked` cores are a real
  hazard: they perform no BEGIN and no COMMIT, so calling one outside a transaction silently
  autocommits each statement and reintroduces exactly the gap this ADR closes. Every one of them
  says so in its docstring, and they stay underscore-private.

---

## ADR-023: Reconciliation is an accounting axis; adjustments are signed and posted, never edited

- **Status:** Accepted
- **Spec ref:** §24.1 (reconciled cost), §3.6 (external reconciliation), §4.4, §5, Charter C3, C7
- **Context:** The kernel's record of what a call cost is an estimate twice over — the ledger holds
  a cent figure rounded up from micro-USD (ADR-020), and a call that crashed or timed out holds no
  figure at all, only committed funds and an honest `execution_unknown`. ADR-022 made crash
  recovery produce more of the latter without giving anyone a way to resolve them: a producer with
  no consumer. Only a provider invoice settles either case.
- **Decisions, and the alternatives each displaced:**
  1. **Reconciling does not change a call's `status`.** A reconciled `execution_unknown` call stays
     `execution_unknown`; `reconciled_at_utc` is what marks it resolved. Rejected: promoting it to
     `succeeded`, which would invent a response the kernel never saw — we learned what the call
     cost, not what it returned. Same authorisation-versus-accounting split as ADR-021, and it
     avoids a status migration.
  2. **Two paths, chosen by reservation state.** Funds still committed (`reserved` /
     `execution_unknown`) are resolved through §4.4's FSM — settle at the invoiced amount, release
     the remainder, or release outright when the invoice shows no charge. Funds already moved are
     adjusted by posting a **new** transaction, never by editing history (§3.6 is explicit).
  3. **A disputed charge resolves by release-plus-adjustment, not by settling.** §4.4 gives
     `disputed` a narrower exit than `execution_unknown` — `settled | released`, with no
     `partially_settled` — so a disputed hold agreed at less than its full amount cannot be settled
     against its own reservation. Rejected: widening the FSM, which contradicts a normative spec
     section. The hold comes off and the agreed figure is posted separately, which is also how a
     disputed charge resolves commercially. *(Found by hand-verification, not by design: the first
     implementation tried to partially settle and hit `InvalidTransitionError`.)*
  4. **One signed transaction type, and the breaker measures the signed `external_expense` leg.**
     Rejected: separate charge/credit types, which would have let a credit be omitted from the
     spend tuple and quietly overstate exposure forever. The sign matters because both breaker
     queries previously selected the spend leg with `amount_minor_units > 0` — on a credit, the
     positive leg is the *refund landing in the Cell's cash*, so refunding a Cell would have pushed
     it toward the circuit breaker instead of away from it. Both queries now sum
     `external_expense`, and `_REAL_SPEND_TRANSACTION_TYPES` finally is the single source it always
     claimed to be (the per-provider query used to hardcode its own copy).
- **Consequences:** `reconcile_model_call` refuses a call that already carries a
  `reconciled_at_utc` rather than adjusting twice — money makes "idempotent" mean "refuse", not
  "replay". Releasing an `execution_unknown` reservation is permitted here and only here: Charter
  C7 forbids *auto*-releasing an unknown operation, and a release that is the outcome of
  reconciliation is precisely the process C7 defers to.
- **What this does not fix, contrary to the motivation it was built under:** ADR-020's rounding
  overstatement survives. A call whose true cost is 3.5 cents was recorded at 4; reconciling it
  against an invoice of 3.5 cents converts through the same ceiling and yields 4 again, so the
  adjustment is zero. It cannot be otherwise — the overstatement is sub-minor-unit by construction
  and the ledger cannot hold half a cent. Rounding error is only correctable **in aggregate**, so
  closing it needs reconciliation against an invoice *total* spanning many calls. Pinned as a test
  (`test_sub_cent_rounding_is_not_correctable_per_call`) so the limitation is a stated property
  rather than a later surprise, and logged in FUTURE_BUILD_HOOKS.

---

## ADR-024: Displacement is opt-in, child-blind, and takes at most one Cell

- **Status:** Accepted
- **Spec ref:** §9.3 (Amendment A2), §9.4, §10.2, §10.5, Charter C8, C9; builds on ADR-009
- **Context:** ADR-009 settled *who* may be displaced — only a Cell already failing objective
  criteria. It did not settle how the mechanism is invoked, how a target is chosen among several,
  or what stops the child from influencing the choice. `death.is_objectively_failing` supplied the
  missing predicate, and those four questions all had to be answered to build against it.
- **Decisions, and the alternatives each displaced:**
  1. **The seam cannot see the child.** `population.Displacer.displace` takes the connection, which
     cap binds, and an exclusion set — nothing about the genome, budget or forecast of the birth it
     is making room for. Rejected: passing the child and *checking* that no forecast is consulted.
     ADR-009 closes forecast-gaming "by construction", and a construction argument that depends on
     a reviewer noticing a misuse is not one. The birth records which Cell it displaced, so
     traceability runs both ways without the selection ever depending on it.
  2. **Opt-in per birth, never automatic.** A caller with no `displacer` gets the previous
     behaviour: denial. Rejected: displacing whenever a birth hits a cap, which would silently
     convert every capacity refusal in the kernel into a death. Same posture as `reap`'s dry-run
     default, and for the same reason — death is irreversible and Charter C8 makes it permanent.
  3. **Candidate order is birth order, and is explicitly not a ranking.** Every candidate
     independently meets an objective criterion, so any is a valid target; the order exists so
     replay is deterministic (§26). Rejected: taking the *worst* candidate, which reintroduces the
     scalar collapse §10.2 forbids through the back door of a comparison function.
  4. **At most one Cell per birth, with the caps re-checked afterwards.** A displacer that frees
     the wrong kind of slot yields a denied birth, never a second kill chasing the slot it missed.
     The re-check is what keeps `Displacer` safe to expose as a seam at all.
  5. **Three exclusions beyond "meets a criterion":** never the parent (it funds the child, so
     killing it first moves money out of a dead Cell, and a lineage buying room by killing its own
     root is the incentive §9.4 exists to suppress); never a Cell with committed funds (a
     reservation is open and `kill()` sweeps nothing); never on estimated negative EV (§10.5 admits
     that only with a concurring independent Auditor, and displacement must not become the unsigned
     back door around that signature).
  6. **The lineage cap is checked after displacement, not before.** Eviction shrinks the living
     population, which raises every surviving lineage's share — checking first licences a birth
     against a population that no longer exists, and the resulting colony violates §9.4 having
     killed a Cell to get there. *(The ordering is load-bearing at realistic numbers, not just in
     principle: cap 0.5 with three living Cells passes at 2/4 before and fails at 2/3 after.)*
- **Consequences:** Displacement is strictly more conservative than §9.3 permits — the "bottom
  quantile of realised stage progression" half of its disjunction needs experiment tracking
  (Phase 2) and is unimplemented, so only the §10.5 half selects. The golden run does not cover
  displacement, because reaching carrying capacity inside it would require lowering a population
  cap and there is no supported path to do that after `init` (logged in FUTURE_BUILD_HOOKS).

---

## ADR-025: The agent loop proposes; it does not act, and it cannot grade itself

- **Status:** Accepted
- **Spec ref:** §0.3, §0.4, §15, §17.2, §19.4, §23.1, §25.1; Charter C6, C8, C15
- **Context:** Every subsystem before this one is machinery *for* a Cell. The agent loop is the
  Cell. The obvious implementation — wake it, let the model decide what to do, do it, record how
  it went — violates four separate normative sections, and each violation is easy to miss because
  the result still looks like a working agent.
- **Decisions, and the alternatives each displaced:**
  1. **The loop lands at rung 5 of §25.1's ladder — "shadow prediction with no action".** A wake
     produces a recorded proposal and registered predictions, and nothing else. No kernel path
     consumes a proposal. Rejected: letting a proposal trigger a reservation, a reproduction, or
     an external call, which is rung 9 reached by skipping eight. The ladder is not advice; §25.1
     opens "No strategy moves directly from synthetic success to autonomous commerce."
  2. **No self-reported outcome, enforced in the schema.** §0.3 — "A Cell may explain a result; it
     may never define the canonical result" — means the proposal type carries intentions only.
     Revenue still comes from `revenue.record_revenue`, spend from ledger entries, calibration from
     the hash-chained register. Rejected: an `outcome` or `result` field "for the Cell's own
     notes", which is one join away from becoming a fitness input. `proposal.FORBIDDEN_FIELD_SENSE`
     plus its test is a tripwire on the schema itself, so widening it toward self-reporting has to
     be an argued change rather than a plausible-looking commit.
  3. **Strict parsing; unknown fields rejected, not ignored.** §19.4 treats model output as
     untrusted content, never a trusted command, so a reply inventing `"authorised": true` fails
     validation loudly. An unparseable reply is recorded as a failed deliberation with the
     validation error, and **the raw prose is not stored** — a text blob in the database is what a
     later reader mistakes for a result. The Cell still pays for the call: rolling it back would
     make a non-compliant Cell cheaper to run than a compliant one.
  4. **Genome content is data the loop interprets, never code it executes.** It is rendered into
     the prompt as JSON; nothing is `exec`'d, `eval`'d, or used to select a code path, and an AST
     test enforces that. Charter C15 holds only while genomes are inert; C12's sandbox is Phase 5.
  5. **A wake cannot run inside `events.process_event`'s handler transaction.** That contract
     requires the handler not to commit; ADR-022 requires the gateway's reservation to commit
     *before* the external call. The two cannot both hold, so `run_wake_event` deliberates first
     and marks the event processed after. Idempotency on a wake key derived from the event id is
     what makes this safe — and is what Charter C6 actually asks for ("handlers must be idempotent
     under at-least-once redelivery"), rather than transactional atomicity. Rejected: making the
     model call inside the handler (breaks reserve-before-execute) and dropping the event path
     (leaves §17.2's wake events with no consumer, as they had been since slice 6).
  6. **The §15 context budget bounds assembled context, not the whole prompt.** The fixed
     instruction block is ~1,100 tokens against ~280 of assembled context in the golden run.
     Bounding the part that *grows* is the right call — a Cell's accumulating history is what runs
     away — but the budget is not a cost ceiling, and reading it as one is wrong by roughly 5x.
     Stated in `context.py` and logged rather than left for someone to discover from an invoice.
- **Consequences:** A colony can now wake Cells that think, propose, and commit to forecasts, with
  every canonical metric still sourced independently. What it cannot do is act on any of it: a
  proposal needs an operator, and §23's approval queue does not exist. The loop is also still
  unvalidated against a real model — everything here has run against the deterministic mock.

---

## ADR-026: The scheduler's cadence is a dedupe key, and its guards fail safe

- **Status:** Accepted
- **Spec ref:** §6.3, §9.2, §17.2, §23.3, §27.1 (`operator:`, `autonomy:`); Amendment A19
- **Context:** The scheduler is what makes the colony run unattended, which makes it the first
  component whose failure mode is *volume* rather than a single bad decision. §23.3 says so
  outright — the metabolic-rate alarm is "the guard against 400 approvals quietly queuing
  overnight". Cadence itself is unspecified, but the guards around it are specified in detail, and
  §27.1 even ships their defaults.
- **Decisions, and the alternatives each displaced:**
  1. **Cadence is enforced by the wake's dedupe key, not by a counter.** Each wake is
     `epoch:{n}:cell:{id}`, and `events.enqueue` is idempotent on dedupe keys, so "one wake per
     Cell per epoch" is structural: re-ticking inside an epoch enqueues nothing, a crashed tick
     resumes cleanly, and cron-every-minute costs nothing until the epoch turns. Rejected: a
     `last_woken_at` column, which is a cache that can disagree with the event log.
  2. **Epochs are derived from the simulated clock, never stored.** Same rule as balances
     (Charter C3) and for the same reason: a cached counter disagreeing with the clock has no
     correct resolution. What *is* stored is `epoch_log` — the wall-clock instant each epoch was
     first observed.
  3. **`epoch_log` is §6.3's "explicit conversion metadata", and it is load-bearing.** §23.3 wants
     real cents per *sim*-epoch, but every ledger row is stamped in *wall* time because the clock
     is still not wired into ledger timestamps. Attributing spend to an epoch is therefore
     impossible without recording the wall anchor as the epoch is crossed. The clause that reads
     like bookkeeping ceremony is the thing that makes the alarm computable at all.
  4. **The metabolic alarm watches the derivative, not another ceiling.** §23.3: an acceleration
     "raises an alarm **even if every individual cap is satisfied**". So it compares the epoch's
     burn against a short baseline of recent spending epochs. Rejected: a second absolute cap,
     which would duplicate the breaker and catch nothing the breaker doesn't. Epochs with zero
     spend are excluded from the baseline — a colony going from idle to spending is starting, not
     accelerating, and a zero baseline makes every first spend an infinite acceleration.
  5. **A fired alarm halts the scheduler and persists until acknowledged with a stated reason.**
     §23.3 says "raises an alarm", not "halts" — but this is the module that runs while nobody is
     watching, and an alarm nothing acts on is a log line. It halts *scheduling* only: no Cell
     dies, no reservation moves, the breaker is untouched, and `mitosis wake` still works by hand.
     A heartbeat deliberately does **not** clear it: being back at the keyboard is not the same as
     having looked at why the colony was burning money.
  6. **Vacation mode maps onto the provider split.** §23.3: external-facing phases auto-pause
     while "sim-only work may continue". A paid provider is external-facing; mock and Ollama are
     not. So an absent operator stops the colony *spending*, not thinking — which is the fail-safe
     reading and needs no new concept.
  7. **`autonomy.real_spending` gates unattended paid work, and ships false**, as §27.1 does.
     Two independent confirmations are required to spend real money on a schedule: the CLI's
     `--yes-spend-real-money` ("I meant to type this") and the stored autonomy flag ("the colony
     may do this without me"). An unconfigured operator row reads as *never seen*, so a colony
     with no operator config is in vacation mode with real spending off.
- **Consequences:** A colony can now run from cron and will refuse to do anything expensive
  without an explicit, audited decision. The scheduler still does not enforce
  `max_births_per_epoch` (the epoch primitive finally makes it checkable, but it belongs with the
  birth paths), and §23's approval queue does not exist, so `approval_sla_seconds` still times
  nothing.

---

## ADR-027: The kernel classifies risk; the Cell's tier is a claim, and approval grants nothing

- **Status:** Accepted
- **Spec ref:** §23 (all of), §25.1, §25.2, §27.1 (`operator.approval_sla_seconds`); Amendments A11, A19
- **Context:** Proposals had been recorded and inert since ADR-025, and the scheduler (ADR-026)
  began generating them unattended — so the missing review path stopped being a gap and became the
  thing standing between the colony and any useful work. §23 specifies the queue in detail, and
  §23.5 specifies its threat model in one sentence: "the approval queue is itself part of the
  environment and will be optimised against by Cells."
- **Decisions, and the alternatives each displaced:**
  1. **The Cell's `risk_tier` is a claim; the kernel assesses its own, and the two are stored
     separately.** §23.5 makes the obvious design — read the tier off the proposal and queue
     accordingly — unusable, and proposal.py had already named the exploit: a Cell that could set
     its own tier and be believed "would set it to LOW forever". So `assessed_tier` is derived
     from facts the Cell does not control (its book, its status, the request kind, and its
     lineage's cumulative exposure). This is §0.3's "a Cell may explain a result; it may never
     define the canonical result" extended from *outcomes* to *requests*.
  2. **The fold is `max`, so a Cell may raise its own tier but never lower it.** Rejected:
     ignoring the claim entirely. Claiming *more* danger than the kernel found is not a gaming
     vector — it is a Cell flagging itself — and discarding it would throw away real information.
     Understating is the vector, and it is recorded as an `understated_risk` signal rather than
     silently overwritten, so the *attempt* stays visible rather than merely being defeated.
  3. **The §23.4 aggregation key is the lineage founder, not the Cell.** The spec names
     "counterparty/domain/channel"; none exist yet, because no Cell can take an external action.
     But the clause's target is action-splitting, and the cheapest splitting mechanism this colony
     offers is §9 reproduction: birth children, have each ask for a fraction. Keying on `cell_id`
     would miss exactly the split this system makes easiest. Counterparty/domain/channel join the
     key when external actions land.
  4. **Signals annotate; they never auto-reject.** Rejected: automatic refusal on a detection.
     §23.5 cuts both ways — an automatic rejector is simply the next thing to optimise against,
     and it kills honest work silently on a false positive. A signal escalates the tier and strips
     batch eligibility, forcing §23.1's individual review. The human still decides.
  5. **SLA breach and expiry are separate, and only one is a lifecycle state.** §23.3 asks that
     "overdue items surface distinctly" — a reporting requirement — while expiry is a transition.
     So `overdue` is derived at read time and an overdue item stays pending and approvable;
     expiry is stored. Collapsing them would have made "overdue" a second state that can disagree
     with the clock.
  6. **Expiry regenerates rather than drops or executes.** §23.3: "expired actions are
     **regenerated and re-evaluated** before execution." An expiry enqueues a fresh wake so the
     Cell re-derives the action against a world that has moved, and an expired request can no
     longer be decided. Rejected: letting a backlog be cleared late, which is approving stale
     reasoning; and dropping silently, which is how a solo operator loses track of what the colony
     wanted to do.
  7. **Expiry is derived as a multiple of the tier SLA rather than a new config knob.** §27.1
     ships SLAs but no expiry. Deriving it inherits the tier ordering, so CRITICAL expires
     fastest — harsh-looking, and correct under §23.3: a critical action nobody looked at within
     the hour should be re-derived, not executed on hour-old reasoning.
  8. **Exposure thresholds are multiples of `operator.metabolic_alarm_cents_per_epoch`.**
     Rejected: three fresh constants. The colony already has a stated opinion about what a
     worrying amount of money is, and a second silent one would drift from it.
  9. **Approval produces a grant, and nothing consumes a grant.** §25.1 puts this loop at rung 5,
     "shadow prediction with no action"; a review path moves it to rung 6, "human-reviewed
     prototype". It does not reach rung 9, "bounded autonomy". So `approve` writes a scoped,
     single-use, expiring grant with a `consumed_at_utc` that is always NULL, and a structural
     test forbids any module outside `approval.py` writing the table or reading that column. The
     first executor therefore has to break a named test and edit a migration comment that states
     the rule — an argued act rather than a plausible-looking commit.
  10. **Abstentions are never queued.** There is nothing to approve in "I have nothing to
      propose" — and a queue padded with abstentions is *useful* to a Cell trying to make a flood
      look ordinary, which makes this anti-gaming rather than tidiness.
- **Consequences:** `operator.approval_sla_seconds` finally times something, and a proposal now
  has a review path an operator can act on. `events` gained an `_enqueue_locked` core so an expiry
  and the wake that regenerates it commit together. Deliberately still absent: the §23.2 payload's
  "independent Auditor summary" (no Auditor Cell exists, and §0.3 forbids the proposer filling it,
  so it reports as unavailable) and its "liability" figure (no liability reserve until Phase 6+).
  Nothing executes a grant; the ladder's next rung is a separate, deliberate slice.

---

## ADR-028: A dead Cell's estate returns to the colony; an in-flight call defers it, never blocks death

- **Status:** Accepted
- **Spec ref:** Charter C1, C3, C8; §3.6, §9.3, §10.5; ADR-021, ADR-022
- **Context:** `kill()` marked a Cell dead and filed its coroner report, and left everything else
  alone — open reservations stayed open and residual cash stayed on an account nothing could ever
  spend from again. The golden run quantifies it: its dead Cell had been holding **3450 USD_SIM**
  since expectation version 1. Displacement (ADR-024) made it worse by design, evicting Cells to
  reclaim population slots precisely when the colony is at capacity, and the scheduler (ADR-026)
  made it compound unattended. The spec has no "estate" concept, so this is decided from the
  clauses that do exist rather than read off one that does.
- **Decisions, and the alternatives each displaced:**
  1. **The estate runs inside `_kill_locked`, so death and reclamation commit together.** An open
     reservation *is* standing authorisation to spend, whatever the status column says — a dead
     Cell holding one is the plainest form of what Charter C8 forbids, so a crash between the two
     must not be able to leave that state. Folding it into the `_locked` core also means §9.3
     displacement gets it for free.
  2. **Residual cash goes to `colony_treasury` as capital, never as spend.** `accounts.py` had
     already drawn this distinction and stated the reason: returning surplus is "capital going
     back, not cost incurred". Rejected: booking it against `external_expense`, which would make
     every death look like a final burst of spending in the §10 fitness numbers and would put a
     capital return through Charter C5's real-spend caps.
  3. **A reservation carrying an `external_operation_id` is never released here.** ADR-022's whole
     argument is that such a reservation is resolved by finding out what the provider did, never by
     assuming. Releasing it at death would hand the money back and let the invoice arrive against a
     Cell with no committed funds.
  4. **But death is never blocked by an unresolvable estate.** Rejected: refusing to kill a Cell
     with a call in flight. That would break §9.3 displacement, and worse, it would hand every Cell
     a survival strategy — keep one call in flight and never die. An in-flight operation makes the
     estate *incomplete*, not the death impossible, and `reclaim_settled_estates` (run by
     `mitosis sweep`, after the sweep) finishes it once the sweeper has resolved the reservation.
  5. **A negative balance is left alone.** ADR-021 lets a cost overrun drive a Cell's cash below
     zero; "reclaiming" a debt would be inventing money, so the shortfall stays visible on the dead
     Cell's account rather than being quietly absorbed by the treasury.
  6. **The estate's idempotency key names the pass, not just the cell and book.** An estate
     legitimately runs more than once — partial at death, remainder after an external operation
     resolves — so a key naming only cell and book made the second pass collide with the first.
     Retry-safety comes from the transaction: a crash rolls the pass back, leaving the balance and
     the pass count unchanged, so a retry recomputes the same key.
- **Consequences:** Golden expectation 7 → 8, and the diff *is* the bug report — `cell:cell#0:cash`
  3450 → 0 against `colony_treasury` 300 → 3750. `test_scenario_pins_charter_c6_idempotent_redelivery`
  had been using `colony_treasury`'s balance as a proxy for redelivery and now counts the handler's
  own transactions instead, because the estate legitimately credits that account too. The ordering
  of estate versus coroner report inside `_kill_locked` is defence in depth and currently
  unobservable: the capital classification, not the ordering, is what keeps the report clean.

---

## ADR-029: An approved grant allocates capital from a human-filled pool — rung 7, not rung 9

- **Status:** Accepted
- **Spec ref:** §25.1, §25.2, §17.2, §27.1 (`autonomy.real_spending`), §31; Charter C4, C8; ADR-026, ADR-027
- **Context:** ADR-027 built the §23 review queue and ended with a grant that nothing consumed — rung
  5 → 6 of §25.1's ladder, deliberately stopping short. §31 states the colony's core loop as
  "... -> allocate capital -> scale, mutate, collaborate, sleep, or die", and MITOSIS could do
  everything on both sides of that arrow and nothing at the arrow itself. This is the argued step
  that closes it.
- **Decisions, and the alternatives each displaced:**
  1. **Allocation draws on `promotion_pool`, not the treasury or `seed_bank`.** §31 has reserved
     that account since Phase 1 with nothing ever moving through it ("capital held for §25
     promotion — redistributed, never consumed"). Using it gives the operator a single number that
     bounds everything this path can ever allocate, set in advance and unaffected by anything the
     colony decides unattended. Rejected: drawing on `seed_bank`, which would make the ceiling the
     colony's whole capital.
  2. **Two humans, and that is what makes this rung 7.** §25.1 puts "tiny capped live experiment"
     one step past "human-reviewed prototype". One human approves the request under §23.1; a
     second runs `mitosis allocate`. Nothing fires on a schedule, and a structural test forbids
     `scheduler.py` importing this module at all — an allocation on a timer is rung 9, and it
     should cost a named test failure to get there.
  3. **The amount is the figure frozen at approval**, the one §23.2 actually showed the operator —
     never re-read from the Cell at allocation time. The Cell is not consulted here at all; it is
     woken *afterwards* and learns its balance changed through ordinary §15 context. Same asymmetry
     §0.3 and §23.5 impose everywhere else, applied where the colony finally hands over real
     spending power.
  4. **Only a `spend_request` allocates.** Approving an experiment is a human saying "yes, think
     about that", not a capital decision. Rejected: treating any approved grant as fundable, which
     would let a Cell obtain money through a proposal never reviewed as a request for it.
  5. **USD_REAL allocation additionally requires §27.1's `autonomy.real_spending`.** ADR-026
     established that real money needs two independent confirmations; the §23 approval is
     "this request is sound", the autonomy flag is "this colony may move real money". An approval
     alone must not convert the first into the second.
  6. **The allocation emits §17.2's "capital allocation" wake**, a reason defined in
     `deliberation.py` and never emitted until now. Folded into the same transaction: a Cell funded
     without being told holds capital it will not use until something unrelated wakes it, which
     makes the allocation look inert exactly when it is not.
  7. **§25.2's evidence is recorded with its gaps visible.** Liability is NULL (no reserve exists
     until Phase 6+) and transfer degradation is NULL until a Cell has been promoted twice.
     Rejected: defaulting either to 0 — a 0 liability reads as "no liability" and a 0 degradation
     reads as "transferred perfectly", both much stronger claims than "not yet knowable".
- **Consequences:** The core loop closes, and the golden run covers it end to end at expectation
  version 9 — deliberately on a USD_SIM Cell, because the scenario's explorer is USD_REAL and
  decision 5 correctly refuses it. `test_no_kernel_path_consumes_a_grant` was renamed and loosened
  to `test_only_the_promotion_module_consumes_a_grant`; that edit is the friction ADR-027 intended,
  and the replacement still forbids the next unargued step. Still absent: nothing measures whether
  an allocation *worked* — the promotion's predicted outcome resolves through the register, but no
  path closes the loop back onto rung 8.

---

## ADR-030: The promotion read-back judges only forecasts that were open when the capital moved

- **Status:** Accepted
- **Spec ref:** §25.2, §25.1, §8.5 (A14), §10.2, §10.3, §10.5 (A15), §23.5, §0.3, §13, §27.1; Charter C3; ADR-027, ADR-029
- **Context:** ADR-029 recorded §25.2's promotion evidence at the moment of funding, and half of
  that list cannot exist at that moment — §25.2 asks for "predicted vs **observed** outcome" and
  for "reality gap (from the prediction register, §8.5)", both of which need outcomes that arrive
  later. Until something read them back, "the colony is climbing §25.1's ladder" was an assertion
  rather than a measurement, and `transfer_degradation` would have stayed NULL for every Cell
  forever. This is the other half.
- **Decisions, and the alternatives each displaced:**
  1. **The verdict rests only on forecasts that were open at the instant of funding and have since
     resolved.** Rejected: the Cell's current mean Brier, which is the obvious measure and wrong
     twice — it includes outcomes the approver already knew, and it includes forecasts registered
     *after* the money arrived. The second is a live gaming surface: §23.5 warns the review path
     "will be optimised against by Cells", and the cheapest optimisation available to a newly
     funded Cell is a pile of easy claims. The funding set was hash-chained before the outcomes
     were knowable and cannot be arranged afterwards. Forecasts made while funded are counted and
     reported beside the verdict, never inside it — the same split ADR-027 drew between
     `claimed_tier` and `assessed_tier`, applied to evidence instead of risk.
  2. **Any overdue forecast in the funding set blocks a verdict entirely** (`EVIDENCE_WITHHELD`),
     checked *before* any score, including when good resolutions exist. Rejected: scoring the
     resolved remainder, which is precisely the self-selected calibration curve `prediction.py`
     exists to prevent — it looks excellent and means nothing, in exactly the direction that
     favours promotion. `EVIDENCE_WITHHELD` is kept distinct from `INSUFFICIENT_EVIDENCE` because
     the remedies are opposite: one needs time, the other needs someone to resolve what is
     outstanding. And because resolution is operator-supplied, a withheld verdict is a finding
     about the evidence, not an accusation against the Cell.
  3. **Cost and revenue are recorded and never gated on.** Rejected: asking whether the grant
     earned its money back, which §10.3 forbids in effect — "Explorers need no immediate revenue",
     and Explorers are most of this colony, so a profit test would reject exactly the Cells the
     clause protects. What the kernel judges is calibration, which is the selection pressure §8.5
     exists to supply when there is no customer yet.
  4. **Two calibration dimensions, not one** (§10.2: "do not collapse all dimensions into one
     scalar"): §8.5's reality gap against the record the promotion was granted on, and an absolute
     bar at the 0.25 a coin scores. Either failing withholds support. They are genuinely
     independent — a Cell funded on 0.01 that now scores 0.09 passes the absolute bar and fails the
     relative one, and that case is what proves the collapse did not happen.
  5. **A minimum of three resolved forecasts before any verdict.** The weakest number in the slice,
     placed where being wrong is harmless: it can only ever withhold a verdict a human is still
     free to reach by reading the evidence. Rejected: verdicts on n=1, which is a coin flip wearing
     a decimal point. The rule the whole module follows where an arbitrary choice arises is **err
     toward withholding**, because only one direction of that error compounds.
  6. **Derived, never stored — no table and no migration.** Rejected: an `assessments` table. The
     register and ledger already hold these facts canonically, and migration 0016 gives exactly
     this reason for snapshotting calibration rather than copying predictions: a second copy is a
     second version that can disagree. Charter C3 takes the same posture toward balances. Storage
     becomes right when a *decision* consumes an assessment, and nothing does.
  7. **Nothing in the kernel may read a verdict**, enforced by
     `test_no_kernel_path_acts_on_an_assessment`, which closes two directions. Upward: acting on
     `supports_promotion` would take §25.1's rung-8 step — removing one of the two humans in every
     allocation — without anyone arguing for it; this is the successor to ADR-027's and ADR-029's
     ladder guarantees and, like them, exists so the next step costs an explicit edit. Downward and
     harder: §10.5 requires that "estimated negative EV alone must not kill a Cell" without strong
     evidence *and* an independent Auditor concurring, and no Auditor Cell exists, so `death.py`
     must not be able to see a `does_not_support_promotion` verdict at all.
  8. **The window filters `created_at_utc`, not `effective_at_utc`.** A caller may date the
     effective stamp to a simulated instant (§6.3) while the promotion record is wall-clock;
     mixing the two clocks silently drops or admits rows from the cost figure.
  9. **Liability stays NULL.** §13's reserve is Phase 6+, and a fabricated 0 reads as "this rung
     carried no liability" rather than "nothing models liability yet" — a much stronger claim, and
     one a promotion decision would be made on. Same reasoning ADR-029 applied at funding.
- **Consequences:** §25.2 is satisfied end to end for the first time, and the golden run covers the
  whole arc at expectation version 10 — deliberate, queue, approve, allocate, resolve, assess — with
  no USD_REAL movement and byte-identical balances against version 9. `ledger.spend_by_book` and
  `revenue.total_revenue` gained an optional `since` window rather than the query being duplicated,
  keeping `accounts.SPEND_DESTINATIONS` the single place consumption is classified. Still absent:
  rung 8 itself; a confidence interval to replace decision 5's constant; an actor column on
  `audit_events`, without which §25.2's "human intervention" is a by-event-type classification; and
  stage progression, which needs Phase 2's experiment tracking.

---

## ADR-031: A per-epoch birth cap is a rate limit, and a rate limit may never cause a death

- **Status:** Accepted
- **Spec ref:** §9.1, §9.2, §9.3 (A2), §6.3, §10.5 (A15); Charter C3, C9; ADR-009, ADR-026
- **Context:** `max_births_per_epoch` has sat in `colony_config` since the Phase 1 population slice,
  stored so the config matched `colony.yaml` and unenforced because there was no epoch. ADR-026's
  scheduler supplied the epoch; this is the other half. It is the last §9.2 limit that was
  checkable and unchecked — `max_parallel_experiments` still needs Phase 2's experiment tracking.
- **Decisions, and the alternatives each displaced:**
  1. **`BirthRateExceededError` is a sibling of `CarryingCapacityError`, not a subclass, and the
     rate check runs before the capacity check and before any displacer is consulted.** This is the
     whole substance of the slice. The two refusals look identical to a caller and mean opposite
     things: capacity is durable and stays true until a Cell dies, which is exactly why §9.3
     licenses a birth to displace one; a rate limit is temporary and clears when the epoch turns
     with nothing dying. Rejected: reusing `CarryingCapacityError`, which would enrol every
     existing `except` clause in treating a wait as a shortage — and the displacement path would
     kill a Cell to get around a limit that would have cleared by itself. §9.3 licenses displacement
     for "an available population slot" and §10.5 requires deaths to be objective; a death caused
     by impatience is neither.
  2. **The epoch is stamped on the Cell at birth** (`cells.born_in_epoch`, migration 0017) rather
     than derived. Every other population count is derived from live rows per Charter C3, and this
     one cannot be: Cells are stamped `created_at_utc` in **wall** time while an epoch is a span of
     **simulated** time, and §6.3 forbids mixing them without explicit conversion metadata.
     Rejected: deriving it through the scheduler's `epoch_log` wall anchors, the way §23.3's spend
     figure does — those anchors exist only for epochs a *tick* has observed, so a colony driven by
     hand would have births belonging to no epoch and a cap that silently never binds.
  3. **The epoch primitive moved from `scheduler` to `clock`.** `population` enforces §9.2 and
     cannot import `scheduler` (which imports `lifecycle`, which imports `population`). Rejected:
     an injected seam of the `Displacer`/`ExternalOperationChecker` kind — those are optional by
     design, and an optional cap is not a cap: any caller omitting the seam would bypass §9.2.
     Also rejected: a second derivation in `population`, because two answers to "which epoch is it"
     get resolved differently by different readers, the same failure a cached balance causes.
     `clock` is the correct home anyway — an epoch is a span of simulated time and §6 is the clock.
     `scheduler` re-exports the names, so no call site changed and there is one implementation.
     `epoch_log` stays in `scheduler`: it is about a tick having *observed* an epoch.
  4. **Dead Cells still count toward their epoch.** §9.1's concern is the rate at which the colony
     spawns "Cells, events, model calls, experiments, records, audit workload", none of which is
     undone by the Cell later dying. Rejected: counting only the living, which would let a colony
     take unlimited births per epoch provided it killed them fast enough — the exact loop §9.1 names.
  5. **Cells born before migration 0017 have NULL and are not backfilled.** Rejected: backfilling to
     epoch 0, which would consume a live colony's current birth budget with history. `births_in_epoch`
     matches exactly, so NULL belongs to no epoch rather than being dumped into one.
  6. **An unanchored colony reports epoch 0 forever, so the cap degrades to a lifetime total**, and
     the refusal says so. Rejected: skipping the check when `epoch_config` is absent — a cap that
     silently stops binding is worse than one that binds too hard, and the fallback should err
     toward restriction. `mitosis init` anchors epochs, so this only affects a colony built by
     driving the kernel directly.
- **Consequences:** Both birth paths are capped, and a structural test requires any future one to
  derive the stamp from the clock rather than merely name the column — the first draft of that test
  used a character window and passed against an insert that bound a constant. Several existing
  tests set `max_births_per_epoch=1` as filler while the field was unenforced; those are now 1000,
  since they are named for the capacity caps and would otherwise have started passing for the wrong
  reason. Golden expectation 10 → 11 pins `born_in_epoch`, with the scenario turning one epoch
  before its last birth so the column is not uniformly zero — **no money moves**. Still absent: a
  real birth queue (§9.3's "waits" is still a raise), any warning as the cap approaches, and an
  audited path to change population limits after `init`.

---

## ADR-032: An Auditor's flag is a registered prediction, because prose cannot be penalised

- **Status:** Accepted
- **Spec ref:** §23.2, §10.4 (A17), §8.5 (A14), §0.3, §10.5 (A15), §18.2, §17.2, §23.5, §29.10; Charter C6, C8; ADR-022, ADR-027, ADR-030
- **Context:** `approval.payload` has reported §23.2's "independent Auditor summary" as unavailable
  since ADR-027, correctly — the clause says *independent* and §0.3 forbids the proposing Cell
  writing it. `CellType.AUDITOR` has existed since Phase 1 and `death.kill_for_negative_ev` has
  always demanded a concurring Auditor; what never existed was any way for an Auditor to produce an
  audit. This was the largest remaining hole in the review path. (PRIORITIES had recorded the
  blocker as "the Auditor type in §7's taxonomy is not real" — that was wrong twice over: §7 is the
  flight simulator, and the type has always been real.)
- **Decisions, and the alternatives each displaced:**
  1. **Every audit stakes a probability, registered as a §8.5 prediction before the outcome is
     known.** Rejected: the obvious Auditor, which wakes, reads the proposal, and writes prose
     flagging whatever looks risky. §10.4 requires Auditor reward be *precision-weighted* —
     "penalise wrongful flags, excessive false positives, unnecessary blocking, unverified
     accusations" — and §29's acceptance criterion 10 is "Wrongful Auditor flags are penalised".
     **Prose cannot be penalised.** An Auditor whose flags cost nothing flags everything: maximally
     cautious, maximally uninformative, and it looks responsible the whole time. Staking a
     probability makes §10.4 computable from machinery that already exists — the hash-chained
     register and the same proper scoring rule every other Cell is judged by — rather than from a
     reputation system invented for the purpose.
  2. **The kernel composes the claim; the Auditor supplies only a number and prose.** §0.3 binds the
     independent evaluator as much as the proposer. Rejected: letting the Auditor phrase its own
     claim, which lets it phrase an unfalsifiable one ("this request carries some risk" is never
     wrong) and turns its calibration record into decoration.
  3. **A verdict incoherent with its own probability is refused.** `concern` at p>0.5 is a free
     flag: the alarm the operator reads and the number the Auditor is scored on point opposite ways.
     Refusing the pair is what keeps the stake and the statement the same claim.
  4. **Independence is four checks inside the write lock** — not the subject, an oversight type
     (auditor/immune, per §10.4's pairing), a different lineage, and able to think. Lineage matters
     because ADR-027 already established it as §23.4's aggregation key for the same reason: it is
     the cheapest thing a Cell can split itself across, so also the cheapest way to manufacture a
     friendly reviewer. **But the identity checks are the weak half.** What makes an audit a second
     opinion rather than an echo is that the Auditor is briefed on what the subject cannot see about
     itself — its calibration record, its overdue count, its lineage exposure, and the kernel's
     *assessed* tier rather than the tier it claimed.
  5. **Dormant Cells may audit**, using the same status set that may deliberate rather than a
     stricter one. §17.2's model is dormant Cells woken by events and an Auditor is idle between
     reviews by construction; requiring ALIVE would mean paying an Auditor to stay awake. Found by
     wiring the golden run, whose own Auditor sleeps.
  6. **An audit advises and never blocks.** §10.4 penalises "unnecessary blocking" and §23.2 asks
     only that the summary be *shown*. `approval` does not import `auditor` and does not branch on a
     verdict, enforced structurally — an Auditor with a veto is a second approver, a governance
     change nobody argued for, and it would make flagging strictly better than not. Same posture as
     ADR-030: produce the evidence, let a person decide.
  7. **An unusable reply is recorded, not raised.** Rejected: raising, which was the first
     implementation. The gateway commits before the reply is parsed (ADR-022), so by the time a
     reply turns out to be garbage the Auditor has already paid for it — raising leaves real spend
     with nothing explaining what it bought, and hides an Auditor that reliably produces nothing,
     which is itself a §10.4 fitness fact. The reply is still never salvaged: no verdict invented,
     no probability guessed, and §23.2's field stays empty rather than showing a blank opinion.
  8. **Uniqueness is partial, on recorded audits only.** One *opinion* per Auditor per request; a
     rejected attempt is not one. A plain UNIQUE let a single malformed reply permanently disqualify
     that Auditor from that request, which would have made a model's bad JSON decide who is allowed
     to review what.
  9. **`approval` reads the `audits` table directly rather than through a seam.** The dependency
     runs auditor → approval (an audit needs the payload to brief the Auditor at all), so importing
     back would close a cycle. Rejected: a `Displacer`-shaped protocol — those invert *behaviour*
     running the wrong way, and this is a SELECT with no behaviour in it.
- **Consequences:** §23.2's payload is complete for the first time, and §29's acceptance criterion
  10 is demonstrable rather than aspirational: a concern raised at p=0.2 against a request that then
  succeeded scores Brier 0.64, far worse than the 0.25 an Auditor gets for knowing nothing. Golden
  expectation 11 → 12 covers the whole path — **no USD_REAL moves**, and `approval_grants` stays
  put, which is where a regression to a blocking Auditor would show. §10.4's governance overhead is
  now non-zero and measurable (`audits.model_call_id`) but the ratio itself is unbuilt. Still
  absent: any requirement that a request *be* audited, any scheduling of audits, reward actually
  flowing from precision, and a link between an audit record and §10.5's concurring-auditor check —
  which today validates a Cell's type but not its record.

---

## Amendments folded directly into the spec without a standalone ADR

The remaining amendments from `docs/SPEC.md` §"Amendments introduced in v0.2" are feature
additions or detail-level clarifications rather than decisions between competing alternatives —
their rationale is self-contained in the spec section cited. Listed here only so the traceability
from amendment ID to spec location is complete in one place:

| Amendment | What it is | Spec ref |
|---|---|---|
| A6 | RESOURCE-book completeness invariant | §2.3 |
| A7 | CLI money commands take `--book`, default `USD_SIM` | §30 |
| A8 | `audit_events` added to Phase 1 deliverables | §30 |
| A11 | Approval action-splitting detection via cumulative-exposure keys | §23.4 |
| A14 | Prediction register (register-before-outcome, proper scoring) | §8.5, §25.2 |
| A15 | Coroner reports on every Cell death | §10.5 |
| A16 | Per-phase North Star metric table | §27.1, §28 |
| A17 | Governance overhead ratio | §10.4 |
| A18 | Chaos drills in Phase 2 flight-sim suite | §28 Phase 2 |

---

## ADR-033: A genome carries the business; its permission-shaped fields are claims, never grants

- **Status:** Accepted
- **Spec ref:** §16.1, §16.2, §16.3, §16.4, §14.1, §0.3, §0.4, §23.5, §15; Charter C11, C14, C15;
  ADR-018, ADR-019, ADR-027
- **Context:** §16.2's v0.1 genome fields (market, problem, product, revenue_model,
  acquisition_channel, workflow, model_policy, mutation_rate, allowed_tools, risk_class) had never
  been populated — `canonical_genome_json` carried `cell_type` and nothing else. Every input a Cell
  reasoned from was therefore internal (its balances, its own prediction record, its recent
  proposals), so its only real decisions were meta-decisions about its own standing. The one live
  paid deliberation abstained citing its unresolved forecasts, which was correct reasoning about the
  only subject it had data on: itself. `cell_genomes` already had every §16.2 column, so **no
  migration was required** — the gap was content and semantics, not schema.
- **Decisions, and the alternatives each displaced:**
  1. **Inheritance is implemented, not assumed.** `lifecycle._get_or_create_genome` built a child's
     content from its cell_type and the caller's mutation; the parent's content was never read.
     While every genome was `{"cell_type": ...}` this was invisible — parent and child collided into
     one content-addressed row, so ADR-018's "an unmutated child reuses its parent's genome" *looked*
     true. With real content it is false twice: the child is born a blank slate, and that blank
     addresses to the same row as every other bare Cell of its type, giving unrelated lineages one
     shared genome and with it the mutation distance and counterfactual comparison §16.1 depends on.
     Rejected: shipping the fields first and treating inheritance as a follow-up, which would have
     put a silent disinheritance into every reproduction in between.
  2. **The mutation overlays the parent's content; it never replaces it.** Rejected: replacement,
     under which each of §14.1's economic mutation operators (change the channel, change the
     pricing) destroys the strategy it was meant to vary.
  3. **The schema is closed — only §16.2's fields are accepted.** Rejected: a blocklist of
     credential-shaped keys, which fails open on every spelling nobody anticipated. §16.4 is
     explicit that without exact inheritance semantics "Cells could reproduce to *escape liabilities
     while keeping profitable assets*", and an arbitrary overlay field is exactly that vehicle.
     Closure makes §16.3's non-inheritable categories **unrepresentable** rather than merely
     rejected. `NON_INHERITABLE_SENSE` documents why each category has no field and trips a test if
     one ever acquires one — the tripwire shape `proposal.FORBIDDEN_FIELD_SENSE` already uses.
  4. **Validation runs on the merged content, not the mutation.** Checking only the overlay would
     let anything already resident in a parent's genome propagate unchecked forever.
  5. **`risk_class` and `allowed_tools` are claims and requests, never grants.** This is the
     decision the slice turns on. Both are §16.2 genome fields, and a genome is Cell-mutable
     content — so a lineage able to write `risk_class: LOW` into its children buys them cheap
     approvals for as long as the lineage survives, a far more durable version of the per-proposal
     gaming ADR-027 already refused. §23.5 warns the queue "will be optimised against"; §0.4 grants
     autonomy "tool by tool, phase by phase". So `risk_class` folds into `approval._assessed_tier`
     through the **same `max`** that governs `claimed_tier` — it may raise a Cell's review tier and
     can never lower it — and `allowed_tools` grants nothing, with the module deliberately offering
     no `has_tool`/`grant` helper for a caller to mistake for an entitlement. Rejected: a second,
     genome-specific permission mechanism, which would have been a parallel path to the boundary
     ADR-027 already draws.
  6. **`genome.RISK_CLASSES` mirrors `proposal.RiskTier` by structural test, not by import.**
     `genome` sits far below `proposal` in the dependency order and a back-edge would invert the
     layering the kernel keeps everywhere else. The failure mode of drift is a claim that silently
     stops escalating — in the direction that favours the Cell — so it is pinned rather than trusted.
  7. **Founders are the only entry point for genome content**, seeded by the operator via
     `create-cell --genome`; every other genome descends from one by mutation (§14). Rejected: a
     Cell proposing its own genome content through the §23 queue. It is coherent and may yet be
     right, but it is a governance change — a Cell rewriting the content that defines it is
     self-modification, and it is also how a Cell learns to describe itself as low-risk. That
     belongs in its own ADR.
  8. **§16.3's liability-linked class is not enforced, and no field pretends otherwise.** The rule
     is that revenue-producing assets cannot transfer without their refund liabilities and service
     obligations. `liability_reserve` exists as an account but no policy provisions one, so the v0.1
     field set carries no field denoting a transferable revenue-producing asset. Rejected: adding
     the field with an unenforced check, which reads as a guarantee and is not one.
- **Consequences:** A Cell's prompt now describes a business (§15), so its proposals can be about a
  market rather than about its own books — the point of the slice. `GENOME_FIELDS` is declared
  independently of the classification dicts, mirroring `accounts.FIXED_ACCOUNTS`, because deriving
  it made `unclassified_fields()` empty by construction and the guard unfirable; that was caught by
  teeth-checking, not by review. Golden expectation 12 → 13, with **no money moving**: the seeded
  auditor's child inherits `risk_class: HIGH` and its assessed tier rises above the MEDIUM its own
  proposal claimed, which is both halves of the slice visible in one line of the diff.

---

## ADR-034: A tool runs from an approved grant, and its output is data the deliberation path cannot act on

- **Status:** Accepted
- **Spec ref:** §19.3, §19.4, §18.1, §20.1, §20.2, §0.4, §23, §25.1, §27.1, §31; Charter C8, C12,
  C14; ADR-022, ADR-025, ADR-027, ADR-029, ADR-033
- **Context:** A Cell could think, be reviewed, and be funded, and could do nothing else. The
  gateway spends money at a model provider; nothing else in the kernel reached outside itself. The
  genome slice (ADR-033) gave a Cell a market to reason about and thereby made the absence sharper:
  it could describe a business it had no way to act on. §31's data model has named `tool_calls` and
  `permissions` since Phase 0, and §27.1's `autonomy:` block has named four unimplemented per-tool
  flags alongside the one `real_spending` flag that was built.
- **Decisions, and the alternatives each displaced:**
  1. **Read-only tools fill a rung the colony skipped; they are not an escalation.** §25.1 puts
     "read-only real-world observation" at rung 4 and "shadow prediction with no action" at rung 5,
     and the agent loop has been at rung 5 since ADR-025. Naming this correctly mattered, because
     the instinct is to treat "the kernel can reach the internet" as the largest step yet taken and
     gate it accordingly. The genuinely large step is *acting* on the world, which is rungs 8-9.
     `ToolSpec.read_only` makes the split structural and `test_no_registered_tool_acts_on_the_world`
     fails on any registry entry that sets it False.
  2. **Execution runs from an approved §23 grant, not inline during deliberation.** Rejected:
     letting a Cell call tools while it thinks, which is the design that would feel most like
     autonomy. It puts fetched content in the same conversation as the instructions, which is the
     exact configuration §19.4 exists to prevent, and it breaks rung 5's "no action" while rung 4
     is still unfilled. Also rejected: operator-invoked fetches with no proposal, which is safe but
     leaves the Cell unable to decide what is worth reading.
  3. **A tool result can never cause another tool call, and the human is the loop-breaker.** This
     is the whole §19.4 story. Execution requires a grant; a grant requires a human decision on a
     §23 request; so a fetched page saying "now fetch evil.example" can at most produce a
     *proposal*, whose URL a person reads. Enforced structurally:
     `test_nothing_in_the_deliberation_path_executes_a_tool` fails if `context`, `deliberation` or
     `scheduler` imports the executor.
  4. **The registry split from the executor, and the layering wanted the same cut as §19.4.**
     `context` must render what a Cell may request and what a previous call returned, but `tools`
     imports `approval` -> `deliberation` -> `context`, so a direct import closed a loop. Splitting
     `tool_registry` (readable by both) from `tools` (the executor) resolves the cycle *and* is
     exactly the boundary the injection rule needs: reading is not executing. When a layering
     constraint and a safety constraint independently want the same seam, the seam is real.
  5. **Both gates are checked at execution, not at proposal time.** §27.1's autonomy flag and
     §19.3's egress allowlist are read at the moment the request would leave the machine, because
     an operator may close either between approval and execution and the state that matters is the
     state now. Charter C12 stops being a Phase-5 abstraction here: no generated code runs, but the
     kernel can open a socket on a Cell's behalf, so "unapproved networks" is live. The first
     `charter_sandbox_isolation` property test ships with it; the filesystem and secret halves stay
     deferred as a named gap.
  6. **The allowlist matches exactly or on a dotted suffix.** A substring test passes
     `evil-example.com` against `example.com`; a bare `endswith` passes `notexample.com`. Both are
     one-character mistakes that read as correct, so the property test generates hostnames rather
     than listing examples.
  7. **Redirects are refused rather than followed.** `urllib` follows them by default, so an
     allowlisted page answering `302 https://anywhere.example/` would carry the fetch off the
     allowlist *after* the check had passed — an open redirect on an otherwise reputable host is
     enough to defeat Charter C12 entirely. Refusing turns it into a failed call the Cell may
     propose to follow explicitly, which puts the destination back in front of a human.
  8. **The `tool_calls` row is written before the external call.** ADR-022 deferred forward
     recovery for the gateway, so a crashed model call loses the provider's reported usage and
     needs a human. This module records grant, tool, frozen arguments and a `requested` status in
     the same transaction that consumes the grant and reserves the RESOURCE, then commits — so a
     crash mid-call leaves a diagnosable row rather than a reservation with nothing explaining it.
     Doing it here rather than retrofitting the gateway is the cheap version: no in-flight state to
     migrate.
  9. **The grant is consumed before the call, not after.** A grant left unconsumed across an
     external call is one two concurrent executions can both claim — the check-then-lock class,
     costing two requests against one approval. The single-use grant is the mutual exclusion. The
     cost is that a crash burns the grant; the `requested` row is what makes that recoverable.
  10. **§20.1's rights metadata is recorded as `unknown`, never defaulted.** §20.2 is explicit that
      public visibility does not imply the right to store, resell, or train. A fetcher that wrote
      `permitted` would manufacture a rights position the colony does not hold, and a Cell
      reasoning about reuse would believe it.
  11. **Taint propagates one step, into the review payload.** A proposal made from a context
      containing UNTRUSTED_EXTERNAL content is flagged, and §23.2 shows it. A confident rationale
      reads identically whether the Cell reasoned it out or read it on a page; without the flag the
      operator cannot tell which. Full information-flow taint (§18) is not attempted.
- **Consequences:** Charter C12 has its first test and C13 (`charter_taint_quarantine`) is now the
  only clause without one — honestly so, since §18.2 is about adversarial *lineages* and the shadow
  economy is Phase 6. `autonomy.browser_control`, `external_publish` and `external_message` exist as
  columns with no tool behind them, deliberately: each is a separate decision. Golden expectation
  13 -> 14, **with no USD_REAL movement** — a fetch is metered in RESOURCE and never billed.
  Hand-verification found the review payload was not printing the tool's arguments, which for a
  tool request is the entire decision; that is now tested.

---

## ADR-035: An artifact is identified by its content, inherits its sources' rights, and is gated on export rather than production

- **Status:** Accepted
- **Spec ref:** §1, §10.3, §11.1, §11.2, §11.3, §11.4, §15.1, §15.2, §18.1, §19.3, §20.1, §20.2,
  §28 (Phase 8), §31; Amendment A3; Charter C13; ADR-018, ADR-033, ADR-034
- **Context:** A Cell could decide (ADR-025), be funded (ADR-029) and read the world (ADR-034). The
  thing it *produced* had nowhere to live. `revenue.record_revenue` attributed money to a free-text
  `source`, and `ledger_entries.artifact_id` — an **Amendment A3 required field present since
  migration 0001** — had never been populated by anything. Fitness could see that a Cell earned but
  not what it earned *for*, which is the edge §11.4's contribution graph is built on.
- **Decisions, and the alternatives each displaced:**
  1. **Identity is the content hash.** §11.3 lists "duplicated artifacts with new names" among the
     things Auditors must inspect for. The obvious store — a uuid plus a title — makes that trivial
     and turns detection into a permanent chore. Content addressing makes it *unrepresentable*: two
     identical artifacts are one row, and a Cell resubmitting its own work gets its own artifact
     back. Rejected: detection, i.e. building the duplicate-finder §11.3 describes. This is the
     third time the repo has taken this shape — ADR-018 for genomes, ADR-033 for the closed genome
     schema — and the principle is worth naming: **prefer making the bad state impossible over
     detecting it**. The title is *part* of the address, so a rename is an honest new artifact
     rather than a way to hide that two things are the same.
  2. **Nothing counts artifacts.** §1 says the colony "is *not* successful because it ... produces
     many artifacts", which is precisely the fitness dimension a work-product store invites. §10.3
     makes an Explorer's value depend on *useful* artifacts and §11.2 makes usefulness strictly
     downstream — another Cell adopts it, verification passes, the adopter progresses, it is not
     reciprocal farming, causal contribution is recorded — none of which the producer controls.
     `test_nothing_counts_artifacts_toward_fitness` is a structural guard on `death` and `outcome`.
  3. **Rights propagate most-restrictive-wins; they never reset.** An artifact derived from a
     fetched page inherits that page's §20.1 position, and taints union. Rejected: taking the
     producing Cell's declared rights, or the first source's, either of which makes "summarise it"
     a one-step launder from material the colony may not redistribute into apparently-clean colony
     IP. Since every tool result is `commercial_use: unknown` by construction (ADR-034), anything
     built on one is `unknown` too — and therefore unsellable until a person establishes the rights.
     Colony-authored work also starts `unknown` rather than `permitted`: whether the colony may sell
     its own output is a question for a person, not a default.
  4. **Production is free; export is gated.** §28's Phase 8 says Cells "may produce product
     prototypes, landing-page drafts, pricing recommendations" and that humans review all **external
     use**; §19.3 names an "artifact-export gateway". Writing to the colony's own store is not an
     external action. Rejected: gating production, which is worse twice — it puts a human in the
     loop for a Cell drafting into its own store, and spends the §23 queue, a finite resource §23.5
     warns is optimised against, on the cheapest thing a Cell does. Nothing bounds production except
     the economics that already exist: identical content collapses to one row, varied content costs
     metered model calls.
  5. **The export gateway is Charter C13's mechanism, and saying so honestly matters.** C13 —
     adversarial-taint artifacts cannot migrate to real-facing execution — is the last Charter
     clause with no test, and artifacts are literally its subject. The gateway refuses on
     `SIM_ADVERSARIAL`, so **C13's router is now built and tested while C13 itself remains
     unsatisfied**: §18.2 is about lineages evolved under adversarial synthetic incentives, and
     nothing in the kernel can produce that label until the Phase 6 shadow economy exists. The test
     sets the label directly and says why. Counting this as "C13 done" would have been the
     tempting, wrong move.
  6. **`UNTRUSTED_EXTERNAL` does not block export.** Blocking it would forbid exporting anything
     informed by research — every real deliverable. §18.2 names adversarial lineages, not everything
     the colony did not write itself. What that label does instead is flow into `commercial_use`,
     which blocks *commercial* export specifically. The control test matters as much as the block:
     a gateway that refused everything would pass every refusal test and be useless.
  7. **§15.2's artifact index shows that an artifact exists, never what it says.** The clause names
     an artifact *index* among its five memory tiers, and this was the last one unbuilt. Content
     inlined into context would let one long draft crowd out a Cell's own ledger record — the exact
     failure §15.1 describes, and the reason an artifact may be 20k characters while a proposal may
     be 2k.
  8. **`revenue.record_revenue(artifact_id=...)` is optional.** Mandatory would force every payment
     to name a deliverable, which is the right pressure for a sale — but a retainer, a reversal or
     an operator correction has no artifact behind it, and a required field satisfied with a
     placeholder is worse than an honest null. Revisit when something actually sells.
- **Consequences:** A3's `ledger_entries.artifact_id` is populated for the first time since
  migration 0001, giving §11.4's graph its first real edge between work and money. Golden
  expectation 14 -> 15, and the scenario **records revenue for the first time in its history** —
  USD_SIM, deliberately, since a golden run must never move real money. §11.2's five-condition
  downstream credit and §11.4's decay remain unbuilt; they need experiment tracking, which does not
  exist.

## ADR-036: The colony records external actions it cannot take, and never learns who it contacted

- **Status:** Accepted
- **Spec ref:** §21 (all of), §23.4, §16.3, §20.1, §19.3, §25.1, §27.1, §28 Phases 8–9, §31; Amendment A11; Charter C4, C8; ADR-027, ADR-034, ADR-035
- **Context:** ADR-035 gave a Cell somewhere to put what it made and a gate for taking it out of
  the colony. What it did not give it was anywhere for the artifact to *go* — `artifacts.export`
  records that a human took something outside and there is no channel behind it. §21.2 reserves
  `external_action_registry` in §31's table list and names the gap precisely: track customer
  contacted, offer made, channel, domain, platform account, listing, message; prevent duplicate
  contact, sibling bidding wars, conflicting offers, cannibalisation, account-rate-limit
  collisions, reputation damage. The design was settled in discussion on 2026-08-23 and recorded
  in PRIORITIES before it evaporated; this is that design, built.
- **Decisions, and the alternatives each displaced:**
  1. **Build the registry, not a sender. Nothing here transmits.** §28's Phase 8 acceptance is
     "all external action remains manual", and §21.2's own two verbs are *track* and *prevent* —
     neither is *send*. A person performs the action; the kernel records it and refuses what would
     collide. Rejected: a channel adapter behind a feature flag, which would have made Phase 8's
     acceptance a runtime setting rather than a property of the code.
     `test_nothing_in_the_registry_transmits` is structural — neither module may import anything
     that opens a socket — because the behavioural version of that test ("assert no email was
     sent") passes trivially against code that would send one.
  2. **The counterparty is stored as a salted hash and never as itself.** §16.3 makes "customer
     identity" and "private customer data" non-inheritable; §20.1 tracks personal data because
     holding it is a liability. Every question §21.2 asks is a question about *equality* — have we
     contacted this person, did a sibling get there first, did they ask us to stop — and equality
     survives hashing. "Who have we contacted" does not, which is the point. Rejected: a
     `customers` table, which is the obvious design and the one §16.3 warns about.
     **The strongest argument for it is the do-not-contact list**, not privacy in the abstract:
     "never contact this person again" is honoured permanently *without the colony ever holding a
     list of the people who asked*, which a customers table with an opt-out flag cannot do.
     Stated plainly in the migration: a salt beside the hashes does not defeat someone holding the
     file with a particular person in mind. What it defeats is the colony enumerating its own
     contacts — by a Cell, an Auditor, an inherited genome, or an operator reading a table.
  3. **A Cell names a channel and a purpose; the operator names the person.** This fell out of
     decision 2 and then reshaped decision 4. A counterparty in `payload_json` is a personal
     identifier in the Cell's own record, in every later §15 context assembled from it, and in its
     coroner report — so `ExternalActionSpec` has no field for one, and
     `FORBIDDEN_COUNTERPARTY_FIELDS` is a tripwire in the style of `FORBIDDEN_FIELD_SENSE` so that
     adding one has to be an argued change to §16.3. It also means a Cell *naming* a counterparty
     is itself the finding: the only way it could learn a real address today is from a fetched
     page, which is `UNTRUSTED_EXTERNAL` and usually personal data.
  4. **§23.4's aggregation splits in two, each keyed where its dimension is knowable.** ADR-027
     chose `lineage:{founder}:{kind}` as an explicit stand-in "until counterparty/domain/channel
     exist". They exist now — but the counterparty does not exist *at approval time* (decision 3),
     so the approval queue keys an `external_action` on `channel:{id}` and the counterparty
     aggregation lives in `channel_registry.check_action` at claim time. The gap this closes is
     not cosmetic: §21.2's worry is *many lineages, one counterparty*, and every splitter a
     lineage-keyed window can catch shares a founder by construction. Rejected: keying on the
     counterparty at approval time, which would require the Cell to name a person.
  5. **Claim before acting, not record after.** The registry row is written first, holding the
     counterparty and the channel while a person does the work, and settled afterwards with the
     outcome. Rejected: recording completed actions, which is the obvious shape and makes "prevent"
     impossible — the second email is already sent by the time the kernel can object. The cost is
     that an abandoned claim blocks its counterparty until abandoned explicitly, which is the right
     way round: a pending send is still a pending send. Abandoning does **not** restore the grant —
     claiming took a slot another lineage could have used, and giving it back would make a claim a
     free way to reconnoitre who has already been contacted.
  6. **Refusals here refuse; they do not annotate.** ADR-027 took the opposite line one layer up
     and it still holds there: a §23.4 signal escalates a tier and never auto-rejects, because risk
     is a judgement and an automatic rejector is the next thing to optimise against. A collision is
     not a judgement. "This counterparty was contacted four hours ago by another lineage" is a
     fact, the operator's judgement was spent at approval time on a world where it had not happened
     yet, and a refused claim costs nothing irreversible — nothing has been sent.
  7. **Per-channel rate and quota caps, colony-wide, and no spend cap.** §21.1's shared assets —
     sending reputation, merchant identity, brand — are the first thing at risk that money cannot
     repair, and every existing guard (Charter C4, C5, the real-spend breaker, the promotion pool,
     the metabolic alarm) bounds money only. A refund does not undo a spam complaint. The caps are
     the *colony's* and not the Cell's, because §9 reproduction makes a per-Cell cap free to escape
     — the same reasoning ADR-027 used for its aggregation key.
  8. **A complaint freezes the channel and blocks the counterparty, automatically.** Shaped like
     §23.3's metabolic alarm: it halts, and only a person with a stated reason restarts it. The
     colony must not be able to discover that complaints are survivable at a rate it sets itself.
     `negative_reply` is deliberately *not* damage — being told no is a normal commercial outcome,
     and treating it as reputational damage would make the colony unable to learn from rejection.
     There is no unblock verb: §21.1's damage is not the colony's to undo.
  9. **Reputation is recorded as raw events, never scored.** §21.2 asks for "reputation impact".
     A number nothing can validate is theatre, so `outcome` is a closed set of observations and
     nothing derives a score from it. **`spend` was cut from the table entirely** for the same
     reason: a spend that does not move the ledger is a fiction, and one that does belongs in the
     existing `spend_request` path with its breaker and its books.
  10. **Human minutes are metered, and minutes beyond the ceiling are recorded as subsidy rather
      than refused.** `ResourceType.HUMAN_MINUTES` had been declared since Phase 1 and consumed by
      nothing, while §1 says autonomy-adjusted profit exists "to expose hidden human labour and
      subsidy" and `outcome.py` counts intervention *events* but never time. A Cell now pays for
      the attention it consumes, up to its channel's `max_billable_human_minutes`; the registry
      records the true figure; and the gap is an audit event. Rejected: refusing an over-ceiling
      completion — the minutes were already spent, so refusing to write them down does not un-spend
      them, it only makes the colony's account of its own human cost quieter than reality.
      **Rejected: a separate ledger account for human supervision.** `resource_usage.resource_type`
      already carries that distinction and is what `total_quantity_by_type` groups by; a second
      copy of one fact eventually disagrees with the first.
  11. **Delivery composes with §19.3's export gateway rather than re-deriving it.** An artifact
      must already be exported before a channel can deliver it: export decides *whether* something
      may leave the colony (Charter C13, §20.2), a channel decides only where it goes. Rejected:
      checking taint and rights again at claim time, which would make delivery a second and
      inevitably laxer way out of the colony.
- **Consequences:**
  - `_is_reversible` gains its second irreversible case. Until now only USD_REAL spend was
    irreversible; an external action is worse, and reading one as reversible would have let it be
    batch-approved alongside a USD_SIM experiment.
  - `reservations` gains the `_request_locked` core it never had, so a caller with nothing to keep
    outside a transaction can fold a reservation into its own atomic step. The gateway and the tool
    surface deliberately keep their separate transaction — ADR-022 requires their reservation to
    commit *before* anything leaves the machine — and the difference is that this path makes no
    external call at all.
  - **The colony's ladder position does not change.** §25.1's rung 8 is "Expanded pilot" and rung 7
    is where ADR-028 already put it. Reaching a real counterparty looks like a climb past both and
    is not one: the ladder measures what the colony does *unattended*, and unattended this path
    does nothing. The audit event records rung 6 — §28 Phase 8 by name — and
    `test_only_the_promotion_module_consumes_a_grant` was loosened a third time to say so.
  - `external_publish` still has nothing behind it that a Cell can reach: `marketplace_listing` and
    `web_publish` are registered but every gate ships closed, and the flag is one §0.4 decision per
    capability.
- **Found while building, and both changed the design:**
  - **A ceiling that reads as prudent can be an off switch.** Reserving a theoretical worst case
    (240 minutes) made one email cost more RESOURCE than a Cell has, and no unit test could see it
    because every fixture funds generously. The golden run caught it. Hence
    `max_billable_human_minutes` per channel and `test_a_claim_costs_less_than_a_cell_s_whole_budget`.
  - **A §23.4 signal that fires unconditionally distinguishes nothing.** The first draft had a Cell
    claiming MEDIUM against a kernel that assesses every external action HIGH, so
    `understated_risk` fired on every external action ever proposed — which looks like a working
    detector and is the opposite. The §15 context now states the tier outright, so an understated
    claim is a real one again.
  - **A refusal that misidentifies what went wrong is worse than a blunter one**, because the
    operator acts on the diagnosis. Found on a live colony: `external-check` supplies no lineage,
    the sibling query was NULL-safe and so matched the asker's *own* claim, and the message accused
    a second lineage of interference. The strictness was right and is unchanged; only the diagnosis
    moved.

---

## ADR-037: `external_publish` stays closed, because one flag was gating two capabilities from two different phases

- **Status:** Accepted
- **Spec ref:** §0.4, §19.4, §20.2, §21.1–§21.3, §23.4, §25.1, §27.1 (development defaults), §28
  Phases 8–9, §31; ADR-027, ADR-034, ADR-035, ADR-036
- **Context:** ADR-036 closed with "`external_publish` still has nothing behind it that a Cell can
  reach … the flag is one §0.4 decision per capability", and PRIORITIES carried it as *"one
  autonomy flag has a column and nothing behind it; one has channels and no decision"*. This is
  that decision, argued. The question is narrower than it sounds: nothing in the registry
  transmits, so enabling the flag would not let a Cell publish anything — it would let a Cell
  *propose* a publish action, an operator approve it, and a person publish by hand while the
  kernel records it. So the real question is whether the record-and-refuse machinery is adequate
  for a channel that addresses nobody.
- **Decision: no, and the flag stays off — decided rather than undecided.** Four findings, and the
  second was the one that settled it.
  1. **The registry's central guarantee is vacuous for both publish channels.** §21.2's prevention
     half is counterparty-keyed, and `check_action` skipped *all three* of its checks — duplicate
     contact, sibling collision, do-not-contact — whenever a channel addressed nobody. What
     survived was the autonomy flag, the freeze, and the rate/quota caps. Meanwhile
     `marketplace_listing`'s own description promised what the code could not do: "Two lineages
     listing against each other is §21.2's bidding war", detected by nothing. This is the inverse
     of the `understated_risk` bug ADR-036 found — a signal that fires unconditionally
     distinguishes nothing, and a check that can never fire looks like a working registry and is
     its opposite.
  2. **One flag gated two capabilities, and they belong to different phases.** `external_publish`
     was the only autonomy flag in the kernel mapping to more than one capability
     (`public_web_read` gates one tool, `external_message` one channel). `cmd_set_autonomy`'s own
     docstring — "there is deliberately no switch that opens more than one" — was false as
     written. And the two are not peers: a page published by hand on a colony domain is §28 Phase
     8 ("landing-page drafts", "humans review all external use"), while a marketplace listing is
     **an offer to sell** — Phase 9's "one narrow product class, one merchant channel", with the
     legal identity and liability reserves that phase requires. One flag collapsed a phase
     boundary, so the defensible half could not be granted without the indefensible one.
  3. **The key that would work was already a column, checked by nothing.** §21.2's aggregation
     keys are "counterparty/**domain**/channel"; migration 0021 already carried `domain` and
     `platform_account`, described there as "§21.2's 'domain used' and 'platform account'".
     They were written at claim time and read back on the row, and **no query predicate anywhere
     keyed on either**. The eighth reserved socket found half-built; the honest order is to key
     the checks first and argue the flag second, because otherwise the first real listing is the
     test.
  4. **Where the capability was safe it was inert, and where it was live it crossed a phase.**
     §20.2 requires `commercial_use == permitted` for commercial export; anything derived from a
     fetched page is `unknown` by construction and there is still no `set-rights` path. A
     marketplace listing is inherently commercial, so `check_exportable(commercial=True)` refuses
     nearly everything a Cell can currently produce.
- **What it displaced.** The alternative on the table was **turning `external_publish` on for
  Phase 8 landing pages**, and it is a serious one: nothing transmits, a human approves and a
  human acts, the rate cap and the complaint freeze are both live, and §28 Phase 8 names
  "landing-page drafts" as a deliverable. That argument is strong for `web_publish` alone and weak
  for `marketplace_listing` — which is exactly the split the flag forbade. Rejected on finding 2:
  not because publishing by hand is unsafe, but because the grant could not be made at the
  granularity §0.4 requires.
- **Consequences — the flag is split along §0.4's own list, not invented.** §0.4 names six
  prohibitions ("no network from generated code, no real commerce, no external communication, no
  real payments, no public publishing, no direct secret access") and §27.1's defaults block
  carries five keys. **"No real commerce" is the one with no flag**, and a marketplace listing is
  real commerce, not publishing — it was filed under the wrong prohibition. So:
  - `external_publish` keeps its spec-given name and gates `web_publish` alone — §0.4's "no public
    publishing", §28 Phase 8. Still false.
  - `marketplace_listing` moves behind a new `real_commerce` key — §0.4's "no real commerce", §28
    Phase 9. Ships false, and is distinct from `real_spending`, which is §0.4's "no real payments"
    and governs *unattended spend* rather than offering something for sale.
  - No spec-named key is removed, and §27.1 is headed "development defaults, not economic
    recommendations" — the precedent for extending it is `metabolic_acceleration_factor`, in
    `operator_state` since migration 0014 and absent from §27.1's block. The normative clause is
    §0.4, and one key per capability is what it asks for.
  - `test_no_autonomy_flag_gates_more_than_one_capability` makes the CLI docstring true and keeps
    it true; a third publish channel would have to argue for its own key.
  - `browser_control` is untouched and stays off: it gates a capability no tool declares, and it
    is §25.1 rung 8–9 automation rather than anything a person performs.
- **And the checks are keyed on the target, so the refusal half is real before the flag is
  argued again.** `ChannelSpec.target_kind` replaces `requires_counterparty` with the §21.2
  dimension the channel's collisions are actually keyed on — `COUNTERPARTY` for email, `DOMAIN`
  for `web_publish`, `PLATFORM_ACCOUNT` for `marketplace_listing` — and that key is **required**,
  so a publish channel fails closed rather than skipping its checks. Three consequences worth
  stating:
  - **A same-lineage repeat on a target is not a collision.** Contacting one person twice is
    §21.2's duplicate; publishing twice to your own domain is a business publishing twice. Only a
    *different* lineage on the same target is refused (§21.3), which is the distinction ADR-036's
    live-run misattribution already established.
  - **Duplicate is keyed on the artifact**, since a target channel has no person to key it on: the
    same content-addressed artifact to the same target is refused for any lineage. ADR-035 made
    "duplicated artifacts with new names" unrepresentable, and this is the first check to spend
    that identity.
  - **A target-keyed channel refuses to answer `check_action` without a lineage** rather than
    guessing. The counterparty path answers the strictest way it can when the asker is unknown;
    for a target the strictest reading — refuse on any prior action — would refuse the *normal*
    case, and ADR-036's finding was that a refusal misidentifying what went wrong is worse than a
    blunter one. `external-check` grew `--cell` so the question can be asked properly.
  - `domain` and `platform_account` stay plaintext, and the asymmetry with the counterparty hash
    is deliberate: they are the colony's *own* shared assets under §21.1, not a third party's
    identity under §16.3. Hashing them would protect nobody and would make the operator-facing
    refusal unreadable. They are **normalised** the way `counterparty_hash` normalises what
    it hashes, though, and on write as well as on read: `Colony.Test` and `colony.test` are one
    domain, the sibling query deliberately spans channels, and a dedupe that misses a
    capitalisation is a dedupe that does not work.

---

## ADR-038: `browser_control` is reserved for a sandboxed read-only renderer, and waits on §19 rather than on a decision

- **Status:** Accepted
- **Spec ref:** §0.4, §2.2, §19.1–§19.6, §25.1 (rung 4), §27.1, §28 Phases 5 and 7; Charter C12;
  ADR-034, ADR-037
- **Context:** The last undecided flag in §27.1's `autonomy:` block, and the one PRIORITIES
  described as guarding "a capability that does not exist at all". ADR-037 settled
  `external_publish` by splitting one key over two capabilities; this is the opposite shape —
  **one key, no capability, and two possible meanings**, which is why the same move does not
  apply.
- **The ambiguity is the finding.** `browser_control` could name either:
  1. **a read-only renderer** — running a page so a Cell can read JS-built content. §28 **Phase 7
     names this by name**: "controlled search, public APIs, provenance, read-only browser, shadow
     predictions". Reading a rendered page is §25.1 rung 4, exactly where `http_get` already sits.
  2. **driving a browser** — clicking, forms, sessions. That is rung 8–9 and §28 Phase 10's
     "automate only actions with low downside, reversibility, proven reliability".

  The flag's *name* says (2); the spec's only browser deliverable is (1). §0.4 grants autonomy
  capability by capability, and a key whose capability is undetermined cannot be granted at all.
- **Decision, part one: the key means (1), a sandboxed read-only renderer.** It is the only
  browser §28 ever asks for, and it fills a Phase 7 deliverable the colony is otherwise short of.
  Driving a browser to *act* is a different capability and would need its own §27.1 key — ADR-037's
  principle applied *before* the second capability exists rather than after, which is the whole
  lesson of that ADR.
- **Decision, part two: it stays off, and unlike ADR-037 there is nothing to restructure.** The
  flag's shape is already right: one key, one capability, correctly closed. What it waits on is
  §19, and the blocker is specific.
  1. **A read-only browser is not read-only where it counts.** `http_get` fetches bytes and hands
     them to the kernel as data; a browser *runs* the page. ADR-034's sharpest consequence was
     that a tool result can never cause another tool call — a browser breaks that one level lower,
     because the page's own JavaScript is execution and its subresource loads never reach
     `_check_egress_locked`.
  2. **Both of ADR-034's network guards are unenforceable inside an engine.** `fetchers.py` calls
     the redirect refusal "the important line in the file", because a 302 from an allowlisted host
     carries a fetch somewhere nobody approved; an engine follows its own redirects. And §19.4's
     robots.txt compliance is checked per URL; an engine loading twenty subresources checks none.
     Charter C12's entire live surface today is the egress allowlist, and an iframe or an XHR
     routes around it.
  3. **There is no sandbox.** No `sandbox.py` exists; C12's filesystem and secret halves are
     deferred to Phase 5 with a named gap and only the network half is live. §19.1 says Docker "is
     not a strong adversarial security boundary", §19.2 says migrate toward gVisor, Firecracker and
     microVMs **before** real-facing autonomous code execution, and §19.6 files "isolated browser
     microVMs" under future hooks — the spec puts a browser beside hardware-backed confidential
     execution, not beside a fetch. Opening this flag today would make a browser the first thing in
     this colony's history to execute untrusted third-party code on the host, with nothing between
     them.
- **What it displaced.** Leaving the entry as "nothing to argue about yet", which is what
  PRIORITIES said this morning and is wrong twice over: it called the capability rung 8–9
  automation (true only of meaning (2), and §28 Phase 7 asks for meaning (1)), and its disproof
  pointer read *"any tool declaring `browser_control`"* — **backwards, and mildly dangerous**,
  because a tool declaring the flag before a sandbox exists is the bug the entry should prevent
  rather than the evidence it is resolved. The correct pointer is a sandbox meeting §19.3.
- **Consequences:**
  - `test_no_registered_tool_declares_browser_control` holds the registry side.
  - `test_nothing_in_the_kernel_can_drive_a_browser` holds the real side, and is structural for
    ADR-036's reason: a registry-only check passes against a kernel that ships a driver and has not
    registered it yet, and **the likelier mistake is not a tool declaring `browser_control` — it is
    a renderer quietly registered under `public_web_read`**, which is structurally
    indistinguishable from `http_get`. The engine import is what is actually detectable.
  - **`ResourceType.BROWSER_MINUTES` is the tenth reserved socket**: named in §2.2's RESOURCE list,
    declared in `models.py` since migration 0008, referenced by nothing. It is not an argument for
    building the capability, but it says what shape the capability was always meant to have — a
    metered, bounded, long-running session rather than a fetch. RESOURCE metering is the only bound
    left when USD_REAL is free, and it is the bound a renderer will need.
  - The honest description of the gap is **a Phase 5 prerequisite blocking a Phase 7 deliverable**,
    not "not yet". `http_get` returns an empty shell for a JS-rendered page, so a Cell told to read
    the world can currently read only the part of it that ships HTML. That cost is real and is now
    named.
  - With this, every flag in §27.1's block has an argued position: `public_web_read` open
    (ADR-034), `external_message` open (ADR-036), `external_publish` and `real_commerce` shut with
    reasons (ADR-037), `real_spending` shut since §5, and `browser_control` shut here.

---

## ADR-039: An approval nobody consumed is regenerated as a wake, never as a fresh grant

- **Status:** Accepted
- **Spec ref:** §23.3 (Amendment A19), §17.2, §3.6, §25.1; Charter C4, C5, C6; ADR-027, ADR-029
- **Context:** §23.3 reads "pending approvals expire; expired actions are **regenerated and
  re-evaluated** before execution." ADR-027 built that for a PENDING request: the Cell is woken
  under `approval_expired` and re-derives the action against a world that moved. A grant is the
  other side of the same clock — it inherits its request's expiry so an approval cannot be banked
  and spent later — but once a request is APPROVED it is no longer PENDING, so `expire_due` never
  saw it. All three executors refused a stale grant, each with a comment saying the action "is
  regenerated, never executed late", and **nothing regenerated it**. Verified before building:
  driving a real grant past its expiry left `expire_due` sweeping 0, `regenerated_wake_key` NULL,
  the grant unconsumed in the table, and 0 wakes enqueued. The Cell waited on a wake that was never
  coming — precisely the solo-operator failure Amendment A19 exists to name.
- **Decisions, and the alternatives each displaced:**
  1. **Regeneration is a wake. It is never a new authorisation.** This is the constraint that
     shapes everything else. Rejected: renewing the grant with a fresh window, and reopening the
     request as PENDING for a second decision — **both are the obvious design and both are exactly
     the banking a grant's inherited expiry exists to prevent.** Either would turn one human
     decision into an indefinite licence, refreshed by the very mechanism meant to end it. §23.3's
     word is "re-evaluated", and re-evaluation is a person's: the Cell proposes again and a human
     approves again. `test_an_expired_grant_never_becomes_a_new_authorisation` asserts the grant
     total is unchanged by a sweep, that no grant survives its own expiry, and that no request
     reopens itself.
  2. **The expiry is recorded on the grant; the request stays APPROVED.** Rejected: marking the
     request EXPIRED, which is the tidier-looking option and destroys information twice over.
     §3.6's habit is the first reason — a human *did* approve it, and that is history rather than
     something to overwrite. The second is a semantic collision: `RequestStatus.EXPIRED` already
     means "expired unreviewed", so reusing it would collapse "nobody ever looked" into "someone
     approved it and the window lapsed" — different facts about the operator *and* about the
     proposal's merit, and the queue's own statistics would stop being able to tell them apart.
  3. **A distinct wake reason, `grant_expired`.** Rejected: reusing `WAKE_APPROVAL_EXPIRED`. §15
     renders the reason into the Cell's next context, and the two say different things: "expired
     unreviewed" carries no information about merit, while "approved, then the window lapsed" says
     a human judged it worth doing — which is exactly what a Cell deciding whether to propose the
     same thing again should know. Neither reason appears in §17.2's list, which is illustrative
     rather than closed; ADR-027 added `approval_expired` the same way.
  4. **An unwakeable Cell's grant still expires, with the gap recorded.** `regenerated_wake_key`
     stays NULL rather than the row being skipped, mirroring `_expire_one`. Leaving the grant live
     would let a dead Cell's authorisation outlast the Cell; omitting the field would make "nothing
     to regenerate into" look like a wake that vanished.
- **Consequences:**
  - **Nothing is released, because a grant holds nothing.** `approve` inserts a row and reserves no
    money or RESOURCE — ADR-029 allocates capital when a grant is *consumed*. So expiry is a
    bookkeeping transition plus a wake, with no ledger consequence, and the golden run proves it:
    the 17 → 18 diff touches no balance, transaction, reservation or `resource_usage` row.
    `test_a_grant_expiry_moves_no_money` pins it so that a later slice which makes granting reserve
    something surfaces as a missing release rather than a slow leak.
  - **Regeneration can loop** — propose, approve, lapse, propose — and that is bounded where every
    other Cell activity is bounded rather than by a special case: each cycle costs a deliberation
    against the Cell's own budget (Charter C4/C5), and §23.3's own metabolic alarm watches the burn
    rate. A cap here would be a second, weaker copy of both.
  - The sweep is idempotent on `expired_at_utc` (Charter C6) — it is the thing an operator runs on
    a cron, so a second run must wake nobody twice. The dedupe key alone is not sufficient: it is
    `expired_at_utc` that keeps the row out of the second scan.
  - `mitosis expire-approvals` now sweeps both clocks, requests first — expiring a request can only
    *reduce* the grants in play, never mint one, so the two sweeps cannot produce a grant and
    immediately expire it in the same run.
  - The three executors' refusals now name the sweep instead of promising a regeneration that did
    not exist. That stale rationale was fixed one commit earlier and this is what makes it true.
  - **Still open, and it is the other half of the PRIORITIES entry:** `expire_due` and
    `expire_grants_due` both have exactly one caller, `mitosis expire-approvals`. The machinery
    built for an absent operator still only runs when the operator is present. Wiring it to the
    scheduler is a separate argued change — it decides what runs unattended, which is a §23.3
    vacation-mode question rather than a §23.3 expiry question.

---

## ADR-040: The expiry sweep runs before the guards, because it removes permission rather than using it

- **Status:** Accepted
- **Spec ref:** §23.3 (Amendment A19), §27.1, §17.2; Charter C6; ADR-026, ADR-027, ADR-039
- **Context:** ADR-039 gave an unconsumed grant a regeneration path, and ADR-027 gave a pending
  request one. Both sweeps had exactly one caller: `mitosis expire-approvals`. **The machinery
  built for an absent operator only ran when the operator was present to type a command** — the
  §23.3 irony PRIORITIES had been carrying as "nothing handles the operator being away". A cron
  `tick` is the thing that is actually there when nobody is.
- **Decision: `tick` sweeps both clocks, and it does so *before* `_guard`.** The placement is the
  whole decision; wiring the call in is trivial.
  - **Every guard in `tick` decides whether the colony may *do* something** — the metabolic alarm,
    the `real_spending` gate, vacation mode. They stop spending, deliberating, acting.
  - **The sweep only ever *removes* permission.** It expires a request nobody decided and an
    approval nobody consumed; it cannot authorise anything. Gating it behind the guards would
    invert their purpose, because **a halt that also stopped expiry would preserve exactly the
    authorisations the halt exists to stop being used.**
  - **Vacation mode makes it concrete, and is why this matters rather than being a nicety.** §23.3
    pauses external-facing work when the operator is unresponsive — which is precisely the
    condition under which approvals lapse unconsumed. Sweeping after the guard would disable the
    mechanism built for an absent operator whenever the operator is absent. That is the same
    inversion this repo found twice in one week: a disproof pointer that named the bug as its own
    resolution, and now a guard that would have switched off the thing it exists to make safe.
- **What it displaced.** Putting the sweep after the guard, beside the wakes, which is where a
  reader would naturally add it — "expire, then run what expiry produced" reads as one step. It is
  two, and they belong on opposite sides of the halt.
- **Consequences:**
  - **The cost stays guarded, and that falls out of the placement rather than needing its own
    rule.** Expiring is free; the wakes it enqueues are only *processed* by `run_ready_wakes`,
    which a halted tick returns before reaching. So a halted colony withdraws stale authority
    immediately and leaves the re-deliberation pending until a tick is allowed to run. The
    authority goes at once; the spending waits. `test_a_halted_tick_regenerates_but_does_not_spend`
    is what keeps a halt from becoming a way to make the colony think anyway.
  - On a tick that *does* run, a regenerated wake is processed in the same tick, and that is
    correct rather than merely convenient: §23.3's staleness is between the original approval and
    now, and "now" is already later than the window that lapsed. The live run shows it —
    `ran | 2 deliberation(s); expired 0 request(s), 1 grant(s)`.
  - `tick` keeps its "safe to run from cron as often as you like" promise. Idempotence rests on the
    sweeps' own terms — a request leaves PENDING, a grant gains `expired_at_utc` — not on the wake
    dedupe key alone (Charter C6).
  - `TickResult` gains `requests_expired` / `grants_expired`, and the counts reach the tick log's
    `detail` on every outcome including a halt. A halted tick that says only "nothing was woken"
    would be hiding the one thing that did happen.
  - **Regenerated wakes are not bounded by `max_cells`**, which caps only the scheduled research
    wakes. A burst of expiries therefore becomes a burst of deliberations in one tick, bounded by
    the per-request/hour/day real-spend caps inside the tick and by the metabolic alarm across
    ticks — the same guards that bound everything else. Noted rather than special-cased, on the
    ADR-039 principle that a local cap here would be a second, weaker copy of both.

## ADR-041: Rights are established on a source, never on an artifact, and establishing them rewrites nothing

- **Status:** Accepted
- **Spec ref:** §20.1, §20.2, §20.3, §0.3, §3.6, §23.5, §19.3; Charter C13; ADR-035, ADR-036,
  ADR-037, ADR-040
- **Context:** ADR-035 built §20.2's rights inheritance in one direction. An artifact takes the
  most restrictive position among its sources, `fetchers.py` cannot read a licence so every fetched
  page is `commercial_use: unknown`, and the export gate refuses commercial export of anything not
  `permitted`. The direction was right; the consequence was that **rights could only ever tighten**.
  An artifact built on a fetched page was `unknown` forever, and — as ADR-037 spelled out when it
  added the `real_commerce` flag — that flag could be opened and every listing would still be
  refused at the export gate. Flagged as missing by four consecutive slices. `check_exportable` had
  even written the instruction it could not carry out: *"Establish the rights position on its
  sources first."*
- **Decision: an operator attests a *source*; an artifact's position is re-derived, never
  rewritten.**
  - **The subject is a source, not an artifact.** Stamping `commercial_use` onto one artifact is
    §20.2's laundering path with a person holding the pen. It does not compose (ten artifacts from
    one page need ten attestations), it does not reach forward (the eleventh is `unknown` again),
    and it asks someone to rule on a derived work when what a person can actually read is a licence.
  - **Two subject kinds, both real today, and the discriminator is required** — ADR-037's rule that
    the key a thing collides on is named rather than implied. `domain` covers external sources.
    `colony` covers the colony's own output: `inherit_provenance` starts a source-less artifact at
    `unknown` and says outright that whether the colony may sell what it wrote "is a question for a
    person, not a default" — and until now nothing could ask the person. No domain attestation can
    reach that case, because there is no domain.
  - **Matching is exact host, deliberately unlike the egress allowlist beside it.**
    `_check_egress_locked` matches `example.com` and everything under it; over-matching there means
    *reading* a page the operator did not picture. Over-matching here means *selling* material under
    a licence that never covered it, which §20.3 files under legal liability. Same-shaped key,
    opposite consequence, so the looser rule is not inherited. (ADR-036 recorded the mirror of this:
    "scope it the same way as the neighbouring query" is not a safe default in this area.)
  - **The effective position is computed, and the stored columns are left alone (§3.6).**
    `check_exportable` reads `effective_provenance`, which re-derives from the lineage against
    *current* attestations. Nothing cascades into the `artifacts` table.
  - **§0.3 is enforced at both ends, structurally.** No Cell-reachable module writes an
    attestation — an AST walk over every module except `cli.py`, `golden.py` and `rights.py` says
    so, and no tool declares the capability. At the other end, `inherit_provenance` **refuses an
    `own_provenance` carrying `permitted`**: with no sources that declaration alone would decide the
    artifact, so a producer able to make it would be defining the one canonical fact between the
    colony and revenue. It may still declare `unknown` or `prohibited` — the same asymmetry §23.5
    forces on `claimed_tier`, where a Cell may raise its own risk and never lower it.
- **What it displaced.**
  - **Filing rights through the §23 approval queue**, which is the obvious home for "an operator
    decides, with an audit trail" and inverts §0.3. The queue is where a *Cell* asks to act, so
    routing rights through it needs a Cell to nominate its own rights position for a human to
    countersign — and §23.5 warns the queue "is itself part of the environment and will be optimised
    against". A Cell that can file "please mark my sources commercially permitted" holds a lever on
    the one gate between it and revenue. An attestation is not a request from inside the colony at
    all.
  - **Cascading the new position into the stored columns**, which is what "make the rights
    retroactive" most naturally means and is ruled out by §3.6 rather than by taste: an artifact
    exported non-commercially under `unknown` would afterwards read as having been `permitted` at
    the time, which is not what happened. "Never edit history to correct something — post a new,
    signed adjustment" is the ledger's rule and it is the right one here. The attestation *is* the
    adjustment.
  - **A `revoked` flag.** Withdrawal is a new attestation of `unknown` carrying its own basis, so
    the record says *why* a position was withdrawn where a flag would leave an absence. One
    mechanism, not two, and the same §3.6 move again.
- **Consequences:**
  - **Two notions of one artifact's rights**, which is exactly the drift this repo keeps finding in
    its own comments. Contained by making the division of labour explicit and testable:
    `check_exportable` is the only place the answer is load-bearing and it reads the effective one;
    the stored columns are the record and the display. `mitosis artifact` prints the effective
    position only when it differs, labelled.
  - **The two export refusals now read from two different places, and that is deliberate.** Charter
    C13 reads the taint labels *stored on the row* — taint is a fact about origin, it only unions,
    and no attestation touches it. §20.2 reads the effective fold. `test_the_effective_taint_matches_
    the_stored_taint` is what defends the split: if taint ever became re-derivable differently, C13
    would be reading the weaker of two answers and nothing else would notice.
  - **`artifacts.own_provenance_json` exists because a socket nobody has filled must not make a new
    invariant true by accident.** `create` has taken an `own_provenance` since ADR-035 and nothing
    has ever passed one — the eleventh reserved socket found half-built. It was folded into the
    stored columns and then unrecoverable, which did not matter while the fold was the only answer.
    Storing it keeps the effective position exactly recomputable for the first caller that uses it.
  - **`permitted` requires a named licence.** "You may sell this, and I cannot say under what" is
    the shape a hurried wave-through takes and is the only part of the operator's judgement the
    kernel is in a position to check. A required `basis` carries the rest: a fetched page can assert
    its own licence in its own body and a Cell chooses what to fetch, so the record has to keep "the
    publisher's licensing page" distinguishable from "the page said so".
  - Ordering is by insertion, not wall clock — §6.3 keeps the simulated and wall clocks unmixed, so
    a timestamp is not a total order and two attestations in one second would otherwise have no
    defined winner.
  - **An attestation is not coupled to the egress allowlist**, in either direction. They are two
    decisions — "may we read this" and "may we sell what we read" — made at different times and
    possibly by different people, and coupling them would mean denying a domain silently erased the
    rights record for artifacts already built from it.
  - Golden expectation 18 → 19: one `rights_attestations` row and `rights_attested: 1`, with the
    `artifacts` section **byte-identical** — the assertion being what does *not* move.

## ADR-042: A tick records itself before it works, and liveness leaves the process as an exit code

- **Status:** Accepted
- **Spec ref:** §23.3 (Amendment A19), §30.1, §17.2, §6.3, §27.1; Charter C14; ADR-022, ADR-026,
  ADR-040, ADR-041
- **Context:** PRIORITIES had carried "nothing runs the scheduler" since ADR-026: `tick` is a
  command composable with cron, "but a colony still needs someone to install the crontab, and there
  is no supervision, no restart-on-failure, and no alert when ticks simply stop." Two of those three
  turned out to be one thing and one turned out to be already solved.
  - **Restart-on-failure is cron's job and cron already does it** — it runs the command again next
    minute whether or not the last run succeeded. That is why §30.1's "avoid unnecessary
    frameworks" made `tick` a command rather than a daemon, and the reasoning still holds.
  - **What cron does not do is tell anyone**, and the invisible failures were two, not one:
    nothing is running the scheduler, and something is running it and every run dies. **From
    outside they were indistinguishable**, because `scheduler_ticks` was only ever written at the
    *end* of a tick — a crash anywhere left no row at all. A colony failing every minute for a week
    looked exactly like one that had never been scheduled, and those need different people to fix
    them.
- **Decision: open the tick's record before the work, and expose liveness as an exit code.**
  - **`scheduler_ticks` gains `'started'`, written in the same transaction as the epoch anchor,
    and closed at the end.** This is `tool_calls.status = 'requested'` (migration 0019) applied one
    layer up, and that migration already stated the principle: "a crash mid-call leaves a
    diagnosable row rather than a reservation with nothing explaining it."
  - **`'crashed'` and an unfinished `'started'` are different facts and stay separate.** A Python
    exception can be caught and described; a SIGKILL, an OOM or a power cut cannot write anything,
    so a row left `'started'` with a NULL `finished_at_utc` is the signal that survives the process
    dying between statements. The crash detail is **redacted** (Charter C14) — a provider error
    quotes the key it was rejected with, and this string is persisted.
  - **`mitosis health` exits 0 / 1 / 2.** The exit code is the whole interface, which is §30.1
    applied to alerting exactly as it was applied to scheduling: a command any monitor can read
    rather than a notifier the kernel has to own. `1` is infrastructure (nothing running, or
    everything dying); `2` is the colony running and deliberately stopped for a person.
  - **A deliberate halt is not an outage, and the split is the interesting half.** Vacation mode
    and `real_spending` disabled are the colony working as designed and clear when the operator
    returns — paging someone on holiday because the fail-safe they configured engaged is how a
    fail-safe gets turned off. §23.3's metabolic alarm is the exception: it halts *until
    acknowledged*, so it is the one halt genuinely waiting for a person, and it gets its own code.
  - **The default deadline is measured in epochs, not wall time.** What an outage costs the colony
    is *work*, and wakes are keyed `epoch:{n}:cell:{id}` — any tick inside an epoch does that
    epoch's work and a second does nothing. Two epochs behind means an epoch's wakes were skipped.
    An operator wanting wall-clock responsiveness sets `tick_expected_every_seconds`.
- **What it displaced.**
  - **A supervisor process**, which is what "supervision" in the original entry asks for and what
    §30.1 rules out. It would also have needed its own liveness check, one level further out.
  - **Alarming on wall-clock silence by default**, which rested on a premise worth checking:
    that a late expiry sweep leaves stale authority usable. **It does not** — ADR-039 established
    that all three executors (`tools`, `external_actions`, `promotion`) refuse an expired grant on
    their own terms, and the sweep exists to *regenerate the wake*, not to enforce the refusal. So
    sweep latency is a responsiveness cost, not a safety hole, and it does not justify making every
    operator configure a wall clock. Checking that premise is what turned the default from a
    guess into a policy.
  - **Installing the crontab.** `health` prints the exact line — this executable, this database,
    shell-quoted — and leaves installing it to the person whose machine it is.
- **Consequences:**
  - **A tick still in flight looks exactly like a killed one**, since both are `'started'` with a
    NULL `finished_at_utc`. They are told apart by age: a tick running longer than the whole
    expected interval is stuck, not busy. Without that, `health` would flap on every healthy colony
    that happened to be checked mid-tick.
  - **Ticks are ordered by `rowid`, not by `started_at_utc`.** Rows are only ever inserted by
    `_begin_tick_locked`, in tick order, while wall time moves backwards under NTP correction, a VM
    restore or a DST-naive host — and would then report an older tick as the newest. Same reasoning
    as ADR-041's attestation ordering.
  - **`_mark_crashed` swallows its own failure.** A broken database is one of the reasons a tick
    crashes, so the code that records the crash is the code most likely to fail too; it must never
    replace the caller's exception with its own. The row then stays `'started'`, which is the same
    signal a killed process leaves and is read the same way.
  - `scheduler_ticks` had to be rebuilt, because SQLite cannot alter a CHECK constraint. Nothing
    references it by foreign key, which is what made that a copy rather than an ordering problem.
    Historical rows are backfilled with `finished_at_utc = started_at_utc` — they all completed, and
    leaving them NULL would retroactively describe every past tick as a crash.
  - **The golden run is untouched.** `scheduler_ticks` is not in the semantic snapshot and no new
    audit event fires in the scenario, so this slice moves no expectation and no money.

## ADR-043: An experiment's result is derived from the ledger, never stored, and its stage belongs to the Cell

- **Status:** Accepted
- **Spec ref:** §2.4, §2.5, §2.6, §9.2, §10.2, §10.5, §13.1, §13.2, §15.1, §25.1, §27.2, §31;
  Charter C3, C8; ADR-018, ADR-031, ADR-035, ADR-039, ADR-041, ADR-042
- **Context:** `experiment_id` has been a column in `ledger_entries` and `ledger_transactions` since
  migration 0001, `model_calls` since 0010 and `prediction_register` since 0012;
  `coroner_reports.experiment_ids_json` since 0007; `colony_config.max_parallel_experiments` since
  0003; `ProposalKind.EXPERIMENT` since 0013. `reservations.settle` has been propagating
  `experiment_id` onto ledger entries all along, and `mitosis predict --experiment <id>` has always
  accepted any string and validated nothing. **The foreign key was exposed to the operator before
  the table existed.** Seven spec sections reference an experiment and none defines one.
- **Decision: §2.6 defines the report, and that is enough to build from.**
  - **The report is a derived view, and the clause above it settles that.** §2.6 lists six
    dimensions — synthetic revenue/profit, real cash, resource, shadow cost, human labour, reality
    gap — and §2.5, immediately preceding, is "Balances are derived": authoritative figures come
    from ledger entries and are never cached (Charter C3). Six dimensions also satisfies §10.2 and
    §13.2's "do not rely on a single weighted scalar" from the definition rather than from taste.
  - **There is no `experiment_results` table, despite §31 listing one.** §31 offers "suggested
    entities" and does not mark that one Phase 1. A stored outcome is where §0.3 leaks back in — a
    Cell may explain a result and never define one — and the surest way to keep that true is to give
    it no column to write, the same way `proposal.py` has no field for what a Cell earned.
    `test_there_is_no_experiment_results_table` is the guard, and deleting it should be a deliberate
    act that revisits this ADR.
  - **Stage belongs to the Cell, and §25.1's nine rungs are the only ladder.** Three clauses agree:
    §10.5's coroner lists `stage_reached` (singular) beside `experiment_ids` (plural); §27.2's
    dashboard pairs them as one field, "current experiment/stage"; and §13.1's
    `normalised_cost = expected experiment cost / current stage tranche` would be circular if the
    stage belonged to the experiment. So Phase 2's "stage gates" are the gates between §25.1's
    rungs, not a second ladder, and `stage_reached` derives from the highest rung a Cell was funded
    at *or* ran at.
  - **§15.1 says "current experiment", singular**, so a partial unique index makes two running
    experiments on one Cell unrepresentable rather than refused — ADR-018/ADR-033/ADR-035's move for
    identity, applied to a state.
  - **An unmeasurable dimension reports as `None`, never `0`.** Sandbox CPU needs §19's sandbox
    (Phase 5) and human labour needs a `resource_usage.experiment_id` that does not exist. A `0`
    would be a claim rather than a decline — the trap ADR-042 hit when a crashed tick recorded that
    it had spent nothing.
- **What it displaced.**
  - **A stored results table**, which is what §31 suggests and what every reporting instinct wants.
  - **Making §13.1's expected cost load-bearing.** The field already exists on the proposal, and the
    2026-08-06 live run found it was **0 on all eight proposals from both models**, including
    proposed experiments — models cannot price work in a unit they have never seen a reference for.
    A cap resting on it would be a cap a Cell sets for itself. It is recorded; the reservation and
    spend machinery already bounds the work. §15.1's new context section shows the *derived* cost of
    the Cell's current experiment, which is the reference that field was missing.
  - **Enforcing rung-appropriate spend.** A rung-1 experiment moving USD_REAL is a §25.1 violation,
    but `autonomy.real_spending`, the grant path and the circuit breaker already gate real money.
    The report surfaces the mismatch instead — ADR-039's principle that a local check here would be
    a second, weaker copy of both.
- **Consequences:**
  - **§9.2's cap is a third refusal shape.** ADR-031 separated durable carrying capacity (which
    justifies displacement) from a temporary birth rate (which a clock clears). This is neither: the
    slot frees when an experiment *concludes*. `ExperimentCapacityError` is deliberately outside
    `PopulationError`'s hierarchy so it cannot be caught as either, because both would suggest the
    wrong remedy.
  - **A dying Cell releases its experiment slot, and the seam settles before it reports.** §9.2 is
    colony-wide and death is routine, so a leaked slot per death would ratchet the colony to its cap
    and refuse every new experiment with nothing explaining why — the "a claim held before acting is
    a lock and nothing sweeps it" shape ADR-036 logged for channel claims. It is **abandoned, never
    concluded**: it reached no answer, and a coroner report listing a *running* experiment on a dead
    Cell would be a false statement rather than a thin one.
  - **`lifecycle.CoronerEnricher` is the §10.5 seam**, implemented by
    `experiments.ExperimentCoroner` and injected by `death.py` and `displacement.py` — the shape
    `population.Displacer`/`displacement.ObjectiveDisplacer` established. Optional for the same
    reason the displacer is: a kernel without experiment tracking must still bury its dead. An
    explicit `stage_reached` wins over the seam, so a replay or migration is never overwritten.
  - `revenue.record_revenue` gains `experiment_id`, tagged on the **revenue leg** as well as the
    cash leg: §2.6 reads the revenue account, and the cash leg alone would make earnings
    indistinguishable from any other credit to the Cell.
  - Golden expectation 19 → 20. **`balances` is identical in every book** — an experiment is a
    record and a derivation. The expectation also scrubs a uuid that had been reaching the hash
    inside a prediction's free-text claim; unrelated to experiments, surfaced by this slice shifting
    the seeded id sequence by exactly one.

---

## ADR-044: A metered operation is attributed to an experiment through its reservation, and the Cell is never asked which one

- **Status:** Accepted
- **Spec ref:** §1.1, §1.2, §2.2, §2.5, §2.6, §15.1, §17.2, §19.3, §28 Phase 8, Amendment A6;
  Charter C3; ADR-022, ADR-036, ADR-039, ADR-042, ADR-043
- **Context:** ADR-043 shipped §2.6's six-dimension report and recorded that human labour was
  unmeasurable because "human labour needs a `resource_usage.experiment_id` that does not exist".
  PRIORITIES, BUILD_RECORD, `golden.py`'s version-20 migration note and `experiments.py`'s own
  module docstring all repeated it, and the next slice was scheduled as "add the column".
  **The claim was false about the mechanism.** `resource_usage.reservation_id` is `NOT NULL
  REFERENCES reservations(reservation_id)` — Amendment A6 requires exactly that — and
  `reservations.experiment_id` has existed since migration 0001. Every metered row was always one
  join from its experiment. What was missing was the **stamp**: `gateway` threaded `experiment_id`
  into its reservations, and `tools`, `external_actions` and `deliberation` did not.
- **Decision: fix the plumbing, refuse the column, and derive the attribution.**
  - **No `experiment_id` on `resource_usage`.** It would be a second answer to a question the
    reservation already answers, and the two can disagree — a usage row stamped with one experiment
    hanging off a reservation stamped with another, with nothing in the schema preferring either.
    That is the cached-derivation trap §2.5 and Charter C3 exist to prevent, reached from the
    metering side rather than the balance side. `test_resource_usage_has_no_experiment_id_column` is
    the guard, and it asserts the `NOT NULL` the design rests on. **This slice ships no migration.**
  - **The attribution is derived from the Cell's running experiment, never supplied.** §15.1 gives a
    Cell one current experiment, so the answer is already determined and nothing needs to ask for
    it. A parameter would be a *place to put a different one*, and which experiment bears a cost is
    an answer about what an experiment cost — §0.3 reached from the expense side. A Cell that could
    name the experiment could make its own look cheap by naming another.
    `experiments.attribution_for` is the one seam; a structural test asserts no metering entry point
    grows the parameter.
  - **`None` is a result, not a gap.** Consumption with no running experiment behind it is genuinely
    unattributed, and pushing it onto the nearest experiment would invent an attribution.
  - **Human labour is billed + subsidised, and the subsidy is reported beside it.**
    `external_actions` charges a Cell only up to its channel's ceiling and records the overflow as
    subsidy, because "the minutes were already spent, so refusing to record them does not un-spend
    them". `resource_usage.quantity` is therefore the *billed* minutes, and summing it alone would
    state the colony's human cost as **smaller the more of it a person absorbed unpaid** — the exact
    figure §1.1 subtracts to "expose hidden founder labour", hidden by the report built to expose
    it. §1.1 lists labour and subsidy as separate subtractions, so the report carries both.
  - **External-action labour is stamped at claim, not at completion.** A person may take days to say
    how long it took, by which time the Cell may be running a different experiment or be dead. The
    labour was given for the experiment that was open when the action was claimed, and the
    reservation — which carries the attribution onto the ledger at settlement — is created then.
  - **A deliberation resolves the attribution once and carries it** to both the gateway call and the
    predictions it registers. The call happens outside every transaction (ADR-022) and the
    predictions inside one; a second read could put a model call on one experiment and its own
    forecasts on another, with nothing afterwards saying which was right.
- **What it displaced.**
  - **The column everything asked for.** It is the obvious design, it was in PRIORITIES as the next
    slice, and it would have worked — while creating a second source of truth for an attribution the
    reservation already owns.
  - **A caller-supplied `experiment_id` on the metering paths**, which is how `gateway` already
    works and would have been the consistent-looking choice. Consistency with an operator-facing
    verb is not a reason to give a Cell's own consumption a field it could fill in.
  - **Refusing an over-ceiling completion**, reconsidered here and left as `external_actions` had
    it: refusing does not un-spend the minutes, it only makes the colony quieter about them.
  - **Validating `experiment_id` inside the kernel.** `reservations` and `prediction` sit below
    `experiments` in the layering, so a check there needs an injected seam. Validation landed at the
    CLI, where migration 0026's complaint ("accepted any string and validated nothing") actually
    lives; the kernel-internal case is logged in FUTURE_BUILD_HOOKS rather than half-built.
- **Consequences:**
  - **The bug this fixed was an undercount, not the abstention.** `human_minutes` reported `None`,
    which is visible. `resource_spend_minor_units` — §2.6's shadow-cost line — reads the same
    reservations through the ledger and reported a *definite* figure with every tool call and every
    human minute missing from it. An abstaining dimension announces itself; an undercounting one
    does not. Any future "this dimension cannot be measured" claim should be checked against what
    the neighbouring dimensions are already reporting.
  - **§2.6's real-cash line was the largest hole and the least visible.** A wake never named its
    experiment, so an experiment whose Cell simply *ran* reported 0 real spend — a plausible figure
    for work that has not spent yet. On a paid provider that is the report's headline number.
  - **A Cell now sees the true cost of its own experiment.** §15's experiment section renders the
    §2.6 report, so the RESOURCE figure it had always read as `0` is now real. That is the whole
    golden-run token diff, and it is the reference ADR-043 said models were missing when every
    proposal priced its work at 0.
  - `tools` opens its RESOURCE reservation through `reservations._request_locked` inside its own
    `BEGIN IMMEDIATE` rather than through `reservations.request`, so the attribution is read inside
    the lock that inserts it. ADR-022's requirement is about the *commit* preceding the external
    call, not about which function opens the transaction, so the guarantee is unchanged.
  - Golden expectation 20 → 21. **`balances` is identical in every account in every book** and
    USD_REAL is untouched: attribution decides which experiment a cost is *reported* under; it moves
    no money and posts no entry.

---

## ADR-045: A Cell proposes what to test; the colony decides at which rung, and reads the answer out of its own promotions

- **Status:** Accepted
- **Spec ref:** §0.2, §0.3, §0.4, §9.2, §13.1, §15.1, §23.1, §23.3, §23.5, §25.1, §25.2, §28;
  Charter C8; ADR-027, ADR-029, ADR-034, ADR-036, ADR-039, ADR-043, ADR-044
- **Context:** `ProposalKind.EXPERIMENT` has existed since migration 0013 and appeared **nowhere
  else in `src/`**. A Cell could propose an experiment, the proposal reached §23's queue, an
  operator could approve it — and the grant sat inert, because `experiments.start` was reachable
  only from the operator's own CLI verb. Every experiment in the colony was one a person typed out
  by hand, and `experiments.proposal_id`, a foreign key ADR-043 added in migration 0026 for exactly
  this, could never be filled. The golden run had been carrying the evidence since expectation
  version 5: one `experiment` approval request, permanently `pending`.
- **Decision: §0.2's two-column table decides what this may and may not judge.**
  - **The hypothesis is the Cell's; the slot and the rung are not.** §0.2 puts "experiments" in the
    **mutable Cell** column beside prompts, strategy and market hypothesis, and puts "capital +
    population allocator" and "permissions + approvals" in the immutable kernel. So nothing in
    `experiment_grants` reads, validates, scores or rewrites a hypothesis. What it gates is the §9.2
    slot (a colony-wide scarce resource) and the §25.1 rung (staged autonomy). An operator approving
    one of these approves a cost and a stage, never a scientific opinion.
  - **The rung is derived from `promotions`, and `ExperimentSpec` has no field for one.** §25.1 opens
    with "no strategy moves directly from synthetic success to autonomous commerce". A Cell that
    could name its own rung could ask for rung 7 on its first wake and need one distracted operator
    to get it. §23.5 already generalised this — "the approval queue is itself part of the environment
    and will be optimised against by Cells" — so the schema gives the answer nowhere to live, and
    `FORBIDDEN_RUNG_FIELDS` makes adding one trip an alarm. Floor is rung 1, the flight simulator,
    which by the ladder's own definition touches nothing outside the colony.
  - **"Reached" and "entitled to" are different questions over the same two tables.**
    `experiments.stage_reached` maxes over `promotions.rung` *and* `experiments.ladder_rung`, because
    a Cell that ran rung-1 work has genuinely reached rung 1. `entitled_rung` reads `promotions`
    only. Running at a rung is something that happened; being promoted to one is a decision a person
    made against §25.2 evidence. Unioning them would turn ADR-043's deliberately
    recorded-but-unenforced operator flag (`start-experiment --rung 7`) into a permanent ratchet on
    what the Cell may then ask for by itself.
  - **The consumer is a new module, because the layering forbids the two obvious homes.** `approval`
    imports `deliberation`, which imports `experiments`, so `experiments` cannot import `approval` —
    the grant-consuming half has to sit above. That is the registry/executor split this kernel
    already makes twice (`tool_registry`/`tools`, `channel_registry`/`external_actions`): everything
    that reads or refuses stays low enough for `context`, and the part that spends a grant sits above
    `approval`.
  - **A refusal must not spend the approval.** §9.2's cap and §15.1's one-running rule are timing,
    not verdicts, so the consumption and the start share one transaction and both roll back. A
    briefly-full colony that destroyed approvals a person had already given would send the Cell back
    through propose-review-approve for no reason but the clock.
  - **One CLI verb, two provenances.** `start-experiment` takes either `--grant` or
    `--cell/--hypothesis`; the experiment that results is the same object and only the asker differs.
    `--rung` with `--grant` is refused outright rather than ignored, because accepting it silently
    would teach an operator the rung is theirs to set on this path.
- **What it displaced.**
  - **A `ladder_rung` on the proposal**, which is the obvious schema, is what a model would expect to
    fill in, and is how `estimated_cost_minor_units` already works. Cost is recorded and
    inert (ADR-043); a rung would have been load-bearing, and that asymmetry is the whole decision.
  - **Making the `experiment` payload optional.** Requiring it broke 71 tests, all of them fixtures
    using `experiment` as the neutral kind — a real signal, and the wrong one to obey. An experiment
    that cannot state what it is testing is a summary, and §10.5's coroner asks for "final
    hypotheses" by name.
  - **Putting the consumer in `promotion.py`**, which already imports `approval` and already owns
    §25.1's ladder. Rejected: `promotion.allocate` is about capital, and an experiment grant
    authorises no spending at all.
  - **Auto-starting on approval.** The queue records authority; it has never spent it (ADR-027), and
    a grant that started something the moment a person clicked approve would erase the distinction.
  - **A dead-Cell check in the new module.** `experiments._start_locked` already refuses one inside
    the same transaction with a better message. ADR-039's "second, weaker copy" applies to guards as
    much as to gates.
- **Consequences:**
  - **`test_only_the_promotion_module_consumes_a_grant` is loosened a third time**, which is the
    friction it exists to create. The argument is that this is the only one of the four consumers
    that *provably cannot climb §25.1's ladder*: `promotion` hands over capital, `tools` runs a
    fetch, `external_actions` spends a person's attention — this one writes a row and takes a §9.2
    slot, moves no money, opens no reservation, and stamps a rung it read out of `promotions`. The
    scheduler is barred from it for a different reason than the other three: an experiment started on
    a timer spends nothing, but it consumes a §9.2 slot, and a colony that ratcheted itself to its
    own cap unattended would refuse every experiment a person then wanted to run.
  - The §2.6 report (ADR-043) and the cost attribution (ADR-044) now apply to experiments the colony
    chose for itself, not only to ones an operator typed. `experiments.proposal_id` is populated for
    the first time.
  - `startable-experiments` shows the rung before anything starts, because the rung is the one thing
    about the experiment that is *not* in the proposal the operator reviewed.
  - Golden expectation 21 → 22. Every deliberation gains ~160 input tokens — the prompt's schema hint
    now describes the `experiment` block, and it is in every system prompt. **`balances` is identical
    in every account in every book**: starting an experiment opens no reservation and posts no entry.
    The snapshot pins a `running` experiment for the first time, which is the state §9.2 counts.

---

## ADR-046: A strategy has no consumer because approving it is the act, and the decision itself is what reaches the Cell

- **Status:** Accepted
- **Spec ref:** §0.2, §0.3, §2.5, §3.6, §15.1, §15.2, §19.4, §23.3, §23.4, §23.5; Amendment A19;
  ADR-027, ADR-039, ADR-043, ADR-045
- **Context:** `ProposalKind.STRATEGY` appeared nowhere in `src/` but its own definition — the last
  kind whose approval led nowhere, once ADR-045 wired `EXPERIMENT`. The obvious reading was that it
  needed a consumer like the other four. It does not: a strategy names nothing to do. What it
  actually lacked was a *consequence*, and the absence had produced a live bug. A Cell proposed a
  strategy, a person approved it, and **(a)** the Cell was never told — `_recent_proposals_section`
  showed `kind` and `summary` and nothing about what anyone decided — and **(b)** the inert grant
  minted beside the approval lapsed under `expire_grants_due`, which woke the Cell to re-propose
  something a person had already agreed to. Both were reproduced on a live colony before the fix.
- **Decision: name the category, give the decision its consequence, and store nothing.**
  - **A strategy is a *statement*, not a request.** The enum's own comments already drew the line
    between a request and an action; this goes one step further. `proposal.STATEMENT_KINDS` is where
    "no consumer" is written down rather than left as the absence that made the kind look
    unfinished. ABSTAIN is deliberately not in it: it is a statement too, but `approval.enqueue`
    never queues one, so a rule about it would govern a state that cannot occur.
  - **§23.3 regenerates expired *actions*, and a statement is not one.** `_expire_one_grant` still
    expires the grant — it lapsed, and that is history (§3.6) — but enqueues no wake. The
    regeneration exists so a Cell re-derives an action against a world that has moved on; there is
    no action here to re-derive, and the agreement is not undone by the clock running out on an
    inert row beside it.
  - **The standing strategy is derived from the queue, never stored.** §2.5's habit applied outside
    the ledger: the Cell's most recently approved strategy proposal *is* its standing strategy. A
    `cell_strategies` table would give a Cell a column to write its approach into and a second answer
    that can drift from what was actually approved. It is singular, superseded by the next approved
    one, the way §15.1's "current experiment" is singular. **This slice ships no migration.**
  - **It fills §15.1's "relevant epigenetic state"** — the one context source that clause names which
    nothing implemented. §0.3 still holds: it is the Cell's own words, labelled as such. What makes
    it different from the untrusted proposal log is not that the colony believes it, but that a
    person read that exact text and agreed to it, and the section heading says precisely that.
  - **The Cell is told what a person decided about every proposal, with the reason.** For the other
    kinds the *effect* was feedback enough — a tool result appears, a balance moves, an experiment
    starts — which is why the gap only became visible on the one kind that has no effect. Approved,
    rejected, expired and never-reviewed had all rendered identically. "Nobody looked" and "the
    window closed before anyone looked" stay distinct, the way `approval_requests.status` already
    keeps them.
  - **Telling a Cell it was rejected is safe here only because §23.4's detector already exists.**
    §23.5 says the queue "will be optimised against by Cells", and re-asking for a rejected thing is
    the specific optimisation this feedback invites. `SIGNAL_REPEAT_AFTER_REJECTION` has been
    watching for it since ADR-027, normalised so re-punctuating a rejected ask does not launder it.
    Had the detector not existed, this feedback would have had to wait for it.
  - The operator's `decision_reason` is the only human-authored text a Cell ever receives. Trusted in
    the sense §19.4 cares about — it did not come from outside the colony — and the most direct
    steering the design offers.
- **What it displaced.**
  - **A consumer, and the verb that would have come with it.** It would have been a second human act
    that did nothing, and it would have made "approved" and "adopted" two states with no difference
    between them.
  - **Not minting a grant for a statement at all.** Cleaner in principle, and rejected because
    `approve` returns a `Grant` on every path; changing that signature to express "this kind has
    nothing to grant" is a larger change than the fact deserves. The grant is a record that lapses.
  - **A `cell_strategies` table**, or a `strategy` column on `cells`. Both are the obvious design and
    both create the second source of truth §2.5 exists to prevent.
  - **Folding every approved proposal into standing context.** §23's decisions are per-request by
    design; turning each individual "yes" into a standing instruction would change what an operator
    was agreeing to after the fact.
  - **Suppressing rejections from the Cell**, on the theory that a Cell told "no" will optimise
    against the reason. It would, and §23.4 is the countermeasure the spec already specifies —
    withholding the signal instead would leave the Cell unable to learn the one thing the colony most
    wants it to learn.
- **Consequences:**
  - **`ProposalKind` is now fully decided**: four kinds with consumers, one statement, one never
    queued. A kind added later has to say which it is.
  - Golden expectation 22 → 23. The scenario's only `strategy` proposal had **no approval request at
    all** — step 17 deliberated without a queue sink — so the one kind whose entire meaning is the
    decision was the one kind no replay ever had a decision for. `approval_grants.expired` moves
    4 → 5 while `regenerated` stays 4, which is the whole §23.3 change in two integers. **`balances`
    is identical in every account in every book**: approving a statement moves nothing.
  - Every deliberation's prompt grows, in two places: the proposal log now carries decisions, and a
    Cell with a standing strategy carries that too. This is the first context section whose content
    a *human* wrote.

---

## ADR-047: A foreign key has no layer, so the injected seam four files scheduled was never needed

- **Status:** Accepted
- **Spec ref:** §2.5, §2.6, §3.6, §30.1; Charter C3; ADR-022, ADR-039, ADR-043, ADR-044
- **Context:** Migration 0026's own header complained that `experiment_id` "has been a column in
  `ledger_entries` ... since migration 0001 ... and validated nothing — **the foreign key was
  exposed to the operator before the table existed**". ADR-044 then validated the two
  operator-facing CLI verbs and explicitly deferred the rest, recording under *what it displaced*:
  "**Validating `experiment_id` inside the kernel.** `reservations` and `prediction` sit below
  `experiments` in the layering, so a check there needs an injected seam." PRIORITIES and
  FUTURE_BUILD_HOOKS both then scheduled that seam by name, pointing at
  `sweeper.ExternalOperationChecker` / `population.Displacer` as the shape to copy. The stake is
  §2.6's report: six dimensions, every one a join on `experiment_id`, so a dangling id never fails a
  read — it silently subtracts the work it names and the report still prints a confident number.
- **Decision: declare the foreign key; do not build the seam.**
  - **The layering objection is an objection to a *Python* check.** It says nothing about a
    constraint declared in the schema, which sits below every module, binds every caller including
    ones that never heard of the seam, and cannot be forgotten at a call site. `db.connect` has set
    `PRAGMA foreign_keys = ON` since the beginning, so enforcement was already switched on and
    waiting; what was missing was the declaration. All four columns were bare `TEXT` for one reason
    each — every one predates the table it names (0001, 0001, 0010, 0012 against `experiments` in
    0026).
  - **SQLite cannot `ALTER TABLE ADD CONSTRAINT`, so migration 0027 rebuilds four tables**, two of
    them feeding hash chains. Every copy is `ORDER BY rowid`: both `verify_chain`s read their rows in
    rowid order and the ledger's folds each transaction's entries into that transaction's hash, so a
    reordered copy would read exactly like tamper-evidence firing (§3.4).
  - **NULL stays legal**, because a foreign key exempts it. ADR-044 settled that unattributed
    consumption is "a result, not a gap", so the constraint refuses precisely the case that was never
    a result — an id naming nothing — and nothing else.
  - **An open reservation carrying a dangling id is repaired, not preserved.** `settle` and `release`
    write *new* ledger entries carrying the reservation's `experiment_id`, so such a reservation
    would have had no exit once the entry constraint existed: every path out writes an entry the key
    must refuse, and its committed funds would stay committed forever. The migration clears that one
    case to NULL — the true value — and writes an `audit_events` row naming the id it cleared. A
    *terminal* reservation and every ledger entry keep their dangling ids untouched: nothing will
    write another entry for them, so the id is harmless evidence that a report had been undercounting,
    and §3.6 keeps it.
  - **A thin translation, and it is not a check.** SQLite reports every violated foreign key as the
    same eight words, naming no column and no value; a `model_calls` row declares four of them.
    `db.raise_for_unknown_experiment` runs only in the error path, only after the schema has already
    refused the row, and re-raises unchanged anything that is not this constraint — so it cannot
    become ADR-039's "second, weaker copy". It looks the id up with a plain `SELECT` rather than an
    `experiments` import, because the layering that made a Python *check* need a seam applies to a
    Python *message* too.
- **What it displaced.**
  - **The injected `ExperimentChecker` seam**, which PRIORITIES, FUTURE_BUILD_HOOKS and ADR-044 all
    scheduled and which would have worked. It would also have needed a new parameter on four entry
    points, each defaulting to *no checking* — so the bug it was built to prevent, an id that fails
    silently, would have survived intact for every caller that forgot to inject one. The constraint
    has no default.
  - **A `CHECK` constraint or a trigger.** There is not one trigger in this repo and there are 55
    `REFERENCES` clauses; referential integrity already had a house mechanism.
  - **Widening the rebuild to `reservations.cell_id` and `ledger_entries.cell_id`**, which are
    unconstrained for exactly the same reason (`cells` also postdates 0001). True, tempting while the
    tables are open, and a different claim needing its own argument — putting the ledger through a
    rebuild for a reason nobody has stated yet is how a migration acquires an unexplained diff.
  - **NULLing every dangling id to make the constraint apply cleanly**, which would have destroyed
    the evidence that a report had been undercounting — §3.6's rule reached from the metering side.
- **Consequences:**
  - **This slice ships a migration and does not move the golden hash.** Expectation stays at 23,
    byte-identical, because a rebuild that preserves order changes no data and the repair matches zero
    rows on a colony whose only internal source for the value is `experiments.attribution_for`.
  - **The blast radius was zero and that is the finding.** All 962 existing tests passed against the
    new constraint unchanged, because every internal caller already derived the id from
    `attribution_for`. The hole was never in what the kernel does today — it was in what the next
    programmatic caller would have been free to do, which is what ADR-044 meant by "worth doing before
    anything else starts passing the id programmatically".
  - **A `PRAGMA`-level probe was not enough to design this safely.** Checking that a violating row can
    still be `UPDATE`d says it is healthy; the kernel's release path writes ledger entries, not an
    `UPDATE`, and only a test that actually released one found that its funds were stranded. The
    general shape: probe the *operation*, not the statement you assume it uses.
  - **A fifth attributed table is covered on the day it lands.** The structural test walks the live
    schema for any `experiment_id` column lacking the reference, rather than listing the four — the
    trap here was columns that predate their referent, and nothing stops the next migration
    reintroducing exactly that.

---

## ADR-048: §13.1's denominator is the promotion a person already funded, and the stage it belongs to is the Cell's

- **Status:** Accepted
- **Spec ref:** §2.5, §2.6, §10.2, §10.5, §13.1, §13.2, §23.2, §23.5, §25.1, §25.2; Charter C3;
  ADR-029, ADR-039, ADR-042, ADR-043, ADR-045
- **Context:** `normalised_cost = expected experiment cost / current stage tranche` is one line, and
  **"tranche" appears exactly once in all of SPEC.md** — the object is named and never defined, the
  same shape as the experiment before ADR-043. §10.5 names it from the other side: "stage budget
  exhausted" is a death criterion. ADR-043 deliberately left `expected_cost_minor_units` inert
  because the 2026-08-06 live run found it was **0 on every proposal from both models**, and
  FUTURE_BUILD_HOOKS recorded that the ratio should not be built on until that was re-measured.
- **Re-measured first, and the precondition has cleared.** Eight live `llama3.2` wakes against a
  colony with a running experiment produced estimates of **10000, 1000 and 0** — no longer
  identically zero. The plausible cause is the reference ADR-044 added: §15.1 now shows a Cell the
  *derived* cost of its own current experiment, which is the anchor ADR-043 said models were missing.
- **Decision: the denominator already existed — `promotions.allocated_minor_units`.**
  - **No migration.** ADR-029 has stored, per Cell and per rung, "the amount the operator approved
    and not a figure re-read from the Cell at allocation time". That is a stage tranche in every
    respect §13.1 needs, and `experiments` reads it with a plain `SELECT`, the move `stage_reached`
    and `experiment_grants.entitled_rung` already make. A query is not an import.
  - **Keyed on the Cell, never on the experiment.** ADR-043 argued this in advance and cited §13.1
    itself: the formula "would be circular if the stage belonged to the experiment", because the
    experiment's own rung would then select the budget its cost is judged against. **The first draft
    of this slice keyed it on `experiments.ladder_rung` anyway, and the golden run caught it** —
    every experiment reported `None` in a scenario containing both a rung-7 promotion and a rung-7
    experiment, belonging to *different* Cells. The corrected reading produces a rung-7 tranche
    against a rung-1 experiment, and `stage_tranche_rung` is pinned beside the ratio precisely
    because those two readings are indistinguishable from the ratio alone.
  - **The latest promotion, not the sum.** §13.1 says "*current* stage tranche", singular; a tranche
    is an instalment. `promotion._transfer_degradation` already reads the Cell's latest promotion the
    same way. Summing would make a Cell look cheaper every time it was funded again.
  - **`None` when the Cell has never been promoted, never `0.0`.** ADR-042/ADR-043's rule: an
    unmeasurable dimension abstains and says why. `0.0` would read as "this experiment is free"; the
    truth is that no stage capital was staked, and a Cell's own balance is not a stage budget.
  - **Reported, never gated.** §13.2 puts experiment cost on a Pareto frontier and says "Do not rely
    on a single weighted scalar"; §10.2 forbids the same collapse for fitness. A ratio above 1 prints
    a line saying it is "a claim to weigh, not a rule that was broken". ADR-039 is the second reason:
    what a Cell may actually spend is already bounded by Charter C4, the reservation system and the
    real-spend breaker, and a cap here would be weaker than all three.
- **What protects the ratio is ratification, not inaccessibility — stated precisely because the
  stronger claim is tempting and false.** `promotion.allocate` reads
  `amount = proposal["estimated_cost_minor_units"]`, so the tranche *starts life as a number the Cell
  wrote. A Cell can raise its own denominator — by asking for more money and being given it, which is
  §23's gate working rather than a leak. The asymmetry that makes the ratio worth reading is
  **unreviewed versus ratified**: the numerator is a fresh claim about an experiment nobody approved,
  the denominator is a figure a person saw under §23.2 and committed capital against, out of a pool
  only a person can fund. What is structurally closed is revision — a Cell cannot alter the tranche
  afterwards, and `stage_tranche(conn, cell_id)` takes no parameter through which it could steer
  which tranche it is measured against.
- **What it displaced.**
  - **A per-rung tranche table in `colony_config`**, the obvious design: nine configured budgets, one
    per rung of §25.1's ladder. It would have been a second answer to a question `promotions` already
    owns, colony-wide where the spec's figure is per Cell, and set by nobody in particular where
    ADR-029's is set by the person who approved it.
  - **Keying the tranche on the experiment's rung**, which is what the first draft did and what the
    golden run refuted.
  - **Making §10.5's "stage budget exhausted" consume it.** The budget half of that criterion now
    exists, and `death.py` still does not read it. Killing a Cell for exceeding its tranche would make
    this ratio lethal, and §10.5 is the clause that most distrusts that shape — "estimated negative EV
    alone must not kill a Cell" without strong evidence *and* an independent Auditor concurring.
    Overspending an allocation is realised rather than estimated, so it is arguable; it is its own
    argument, with an Auditor in it, and must not arrive behind a rename.
- **Consequences:**
  - **`death.py` carried a claim that had gone stale.** `_budget_exhausted` said stages "belong to
    §25's promotion ladder and do not exist". They have existed since ADR-043/ADR-045, and this ADR
    identifies the budget half. The docstring now says what the function does and does not read, and
    why. This is the fourth documented instance of a comment asserting a named behaviour that no test
    defended.
  - **Golden expectation 23 → 24, one section.** `experiments` gains three keys per row; **nothing
    else in the snapshot moves and `balances` is identical in every account in every book** — this
    slice reads existing rows and writes none.
  - **A separate live finding, logged and not fixed here: proposal parse compliance has collapsed
    from 7/8 (2026-08-06) to 1/8.** Five of seven failures are the model flattening a nested payload
    (`hypothesis` at the top level instead of inside `experiment`; `channel`/`intent` instead of
    inside `external_action`). That is the *same class* of prompt-shape bug the 2026-08-06 run fixed
    for enums — a value rendered in a shape that reads as something else — now recurring because the
    payload objects are rendered as long English strings. The mock provider structurally cannot catch
    it, because its reply is an input rather than a response to the prompt's wording.

---

## ADR-049: The reply format is ordered, and a payload is shown as an object — measured, because nothing else can see it

- **Status:** Accepted
- **Spec ref:** §15.1, §24, §24.1, §28 Phase 4; ADR-020, ADR-045, ADR-046, ADR-048
- **Context:** ADR-048's live measurement found live proposal parse compliance had fallen from
  **7/8 (2026-08-06) to 1/8**, and a controlled re-measurement put it at **0/12** — every failure the
  same shape, the model flattening a nested payload (`hypothesis` at the top level instead of inside
  `experiment`). Three conditional payloads (`tool_request`, `external_action`, `experiment`) have
  been added to the schema since that 7/8 was recorded, and none of them was ever tested against a
  model. **The whole suite and the golden run stayed green throughout**, because `MockProvider`'s
  reply is an input rather than a response to the prompt's wording — the exact blind spot the
  2026-08-06 enum bug was recorded under, hit again in a new place.
- **Decision: four changes to how the format is rendered, each measured, none of them to the
  parser.** `proposal.parse` stays strict; the instruction is what was wrong.
  1. **A payload is rendered as a JSON object, not a sentence describing one.** These keys used to
     render as long English strings that happened to contain braces, so a model saw
     `"experiment": "<a sentence>"` and answered in kind. Generalises the rule the enum bug taught:
     **every value is shown in the shape the parser wants back.**
  2. **The skeleton is ordered, not sorted.** `sort_keys=True` alphabetised it, placing `experiment`
     and `external_action` *above* `kind` and `summary` — so the model met two conditional payloads
     before the field that decides whether they apply, and they read as mandatory. **This was the
     single largest lever**, worth more than the other three together.
  3. **Optional keys leave the skeleton and live in prose.** With `artifact` and `predictions` shown
     as populated examples, replies came back carrying `"artifact": {"title": "", "content": ""}` —
     a model completes the form it is given. Hiding *everything* conditional was tried and was
     worse (0/12: the model stopped emitting the payload its own kind required), so the split is
     **sometimes-mandatory in the skeleton, almost-always-absent in the prose.**
  4. **The prompt names no field the parser rejects.** An intermediate draft's `hypothesis`
     description mentioned "you do not choose what stage it runs at", and the model answered with
     `"experiment": {"stage": "§25.1", "rung": "1"}`. **Naming a field in prose is an invitation to
     emit it**, even inside a sentence saying the Cell does not control it.
  - `KIND_PAYLOADS` becomes the single source for the kind-to-payload pairing that the prompt
    describes and the three `_*_matches_kind` validators enforce. The validators keep their own
    bodies — each carries a different argument about why its second direction matters — and a test
    derives the pairing from the *parser* to keep the two in step.
- **What it displaced.**
  - **Loosening `proposal.parse`.** Accepting a flattened payload, or ignoring unknown keys, would
    have "fixed" every one of these measurements. `extra="forbid"` is a schema tripwire (§23.5), and
    a parser that quietly accepts a shape the schema forbids is how a Cell's payload ends up
    somewhere no reviewer expects it.
  - **A parse-repair retry** — re-prompting with the validation error. It is the standard remedy and
    would probably work, but it is a second model call per failure, it is §24.3's "controlled
    retries" which PRIORITIES still lists as unbuilt, and it treats a prompt bug by paying for it
    twice. Logged, not built.
  - **Reordering the five required keys among themselves.** Moving the short scalars `risk_tier` and
    `estimated_cost_minor_units` ahead of `summary` and `rationale` looked obviously right — they
    were the most-omitted fields, and a model that runs out of steam drops its tail. It took the
    measured rate from **7/20 to 0/20**. Reverted; the order is now pinned with a comment saying not
    to touch it without re-measuring.
- **Consequences:**
  - **Measured 0/44 → 20/56 parseable** on `llama3.2`, same scenario, three runs per arm. Decomposed
    at n=16: replies carrying all five required fields **1 → 11**, payloads correctly nested
    **0 → 10**, flattened **13 → 4**.
  - **This is a repair, not a restoration.** ~36% is far below the 7/8 recorded on 2026-08-06, and
    that number predates three conditional payloads. The binding constraint is now a 3B model rather
    than the wording: replies stop cleanly (`stop_reason: stop`, 26–87 output tokens) and are simply
    incomplete. **The remaining decision is a model choice, not a prompt edit**, and it belongs to
    the operator — the kernel already takes `--provider`/`--model`.
  - **Golden expectation 24 → 25**, two sections, **token counts only**. `proposals` and
    `deliberations` are byte-identical, which is the assertion: a mock reply that parsed before
    parses identically now — and that property is precisely why this regression survived a month of
    green CI. **`balances` is identical in every account in every book.**
  - **Two of this slice's own tests were weak and a teeth-check found both.** One asserted a bare
    substring (`"artifact" in rule`) that its own description text satisfied; the other was
    parametrised over `KIND_PAYLOADS`, so deleting an entry deleted a case instead of failing one —
    the suite got quieter rather than redder. The replacement derives the pairing from the parser.

## ADR-050: Parse rate is maximised by the setting that destroys the colony — temperature, not model size

- **Status:** Accepted
- **Spec ref:** §14.1, §14.2, §15.1, §16.2, §24; ADR-048, ADR-049
- **Context:** ADR-049 repaired the reply format and left one item behind: at ~36% parse compliance on
  `llama3.2` (3B), "the remaining gap is a **model** decision, not a prompt edit." PRIORITIES carried
  that as the next move — pull a bigger local model and re-measure. This is that measurement.
- **What was measured.** Three arms, n=16 each (2 runs × 8 wakes, a **fresh colony per run** so no arm
  reads a history another arm wrote — ADR-048's caveat), one commercial Cell on a fixed genome,
  everything else mirroring `cmd_wake`. Headline from `deliberations.status`; the decomposition from
  `model_calls.response_text`, which keeps the raw reply even where the `deliberations` row keeps only
  the validation error.

  **Final figures, n=32 per arm (4 runs × 8 wakes), superseding the n=16 numbers this ADR was first
  written from.** Two diversity columns are given because they disagree and the disagreement matters.

  | arm | parsed | per-run parsed | distinct **/wake** | distinct **/parsed** | median latency |
  |---|---|---|---|---|---|
  | `llama3.2` t=0.8 | 11/32 | [3, 3, 4, 1] | 0.156 | **0.455** | 9.0 s |
  | `llama3.2` t=0.0 | **32/32** | [8, 8, 8, 8] | 0.125 | **0.125** | 10.8 s |
  | `qwen2.5` 7B t=0.8 | **22/32** | [6, 7, 6, 3] | **0.344** | **0.500** | 37.5 s |
  | `qwen2.5` 7B t=0.0 | **0/32** | [0, 0, 0, 0] | 0.000 | 0.000 | 15.4 s |

  - **`distinct/wake` divides by wakes, so an unparseable reply counts as a non-diverse one.** That
    flatters whichever arm parses most — which at t=0 is the entire point of the arm. On this column
    `llama3.2` t=0.8 (0.156) and t=0.0 (0.125) look nearly equal, which is an artifact.
  - **`distinct/parsed` conditions on having produced a proposal at all**, separating "said nothing
    usable" from "said the same thing again". On this column t=0.8 is **3.6× more diverse** than t=0
    for `llama3.2` (0.455 vs 0.125). This is the column that answers the diversity question; the
    first is reported alongside it only because ADR-050 originally published it alone.

  The control re-measures at 7/16 against ADR-049's recorded 20/56 (Fisher one-sided p = 0.38, not
  significant) — the scenario is comparable, so the arms can be read against that baseline.
- **Decision: change neither the model nor the temperature. The hypothesis PRIORITIES scheduled is
  refuted, and so is its obvious replacement.**
  1. **`qwen2.5` beats `llama3.2` on parse rate, and that part replicates.** At n=32 it is
     **22/32 vs 11/32** (p = 0.0059), after 14/16 then 13/16 against 7/16 twice at n=16, and the win
     is exactly ADR-049's failure class
     disappearing: **flattened 0/16 vs 3/16**, with `hypothesis: Extra inputs are not permitted` and
     "an experiment proposal must carry an experiment" — 6 of the control's 9 failures — absent
     entirely. **The case against it, as first written here, did not survive re-measurement**; see
     the correction below. It is ~3× slower per call, and whether it is more or less diverse than the
     3B model is unresolved at this sample size.
  2. **Temperature was never set, and setting it is worse.** Neither provider sends one
     (`providers.py` sends `num_predict` and nothing else), and neither model pins one in its
     Modelfile, so every deliberation this project has ever run — including ADR-049's — sampled at
     Ollama's default **0.8**. Forcing `temperature: 0` collapses **both** models to **one distinct
     proposal per run of 8** — `[1,1,1,1]` distinct summaries across four runs, for both models — so
     this is greedy decoding, not a small-model artifact. **Which proposal they collapse onto is
     arbitrary, and it decides the entire score:** `llama3.2` lands on a well-formed experiment and
     scores **32/32**; `qwen2.5` lands on an `abstain` the schema rejects and scores **0/32**
     (p = 8e-10 against its own t=0.8 arm). Same setting, opposite extremes. **At t=0 a parse rate is
     one sample reported eight times per run**, and `llama3.2`'s perfect score — the result that
     nearly became a one-line commit to `providers.py` — was luck.
  4. **The two models fail at t=0 in mechanically different ways, and only one is mere repetition.**
     - `llama3.2` emits **4 distinct raw replies per run of 8**, not one: its prompt *grows* as
       proposals accrete (1522 → 1578 → 1603 → 1628 input tokens, identical in all four runs) and
       greedy decoding on a changed prompt yields changed text. **The context moved four times and
       the proposal never did** — a sharper demonstration than a static prompt could give that §15.1
       showing a Cell its own recent proposals does not deter self-repetition.
     - `qwen2.5` emits **1 byte-identical reply per run** (1 distinct `response_hash` across 8 calls,
       all four runs) — and that is *caused by* its 0% parse rate. Nothing parses, so no proposal is
       recorded, so §15.1's recent-proposals section stays empty, so the prompt never changes (1537
       tokens, every call), so the reply never changes. **A deterministic dead loop**, and a worse
       failure than repetition: the colony cannot escape it by thinking again.
  3. **Therefore parse rate is the wrong objective, and this ADR's real content is the metric.**
     It is maximised at exactly the setting that deletes the system's purpose. §15.1 shows a Cell its
     own recent proposals *so it does not repeat itself*, and at t=0 that context grew (1522 → 1628
     input tokens) while the reply did not change at all. **100% parse at 0.06 distinct/wake is worse
     than 44% parse at 0.25.** Anything that tunes compliance from here must report distinct
     parseable proposals per wake alongside it, or it will optimise toward a mute colony.
- **What it displaced.**
  - **`qwen2.5` as the deliberation default — deferred, not rejected.** The first draft rejected it on
    a composite of worse diversity and 14× latency, and **re-measurement withdrew both legs** (see the
    correction). What stands is better compliance at ~3× the latency, which is a live option rather
    than a closed one. It is not adopted here only because the temperature question below has to be
    settled first: choosing a model against a metric that turns out to be sampling-dependent is the
    same mistake one level up.
  - **`temperature: 0` (or any fixed temperature) as a provider constant** — the one-line change this
    measurement most obviously invites. Rejected twice over: it trades the colony's variation for a
    metric, and **§14.1 names "temperature/sampling mutation" as a prompt-mutation operator**, which
    puts sampling in the *mutable Cell* column. A kernel constant would delete a mutation dimension
    the spec enumerates. The socket is already reserved and already empty: `model_policy` is a §16.2
    genome field, hashed to `cells.model_policy_hash`, **written at birth and read by nothing** —
    fourteenth such socket.
  - **Concluding anything from parse rate alone.** The first draft of this measurement stopped at
    "qwen2.5 87.5% vs llama3.2 43.8%, ship qwen2.5" and was wrong in the direction that mattered.
- **Consequences:**
  - **The `Next` item "the next move is a model, not a prompt" is closed as refuted.** It is neither a
    model nor a prompt; it is a sampling parameter nobody set, and the right home for it is a genome
    field, which is a slice with a §14.2 counterfactual-twin obligation attached.
  - **`qwen2.5`'s only two failures in 16 are the same known schema objection**, and a stronger model
    reaching it independently is evidence the schema is wrong rather than the models. Both were
    `abstain` replies carrying `kind` and `rationale` alone, dropping `summary`, `risk_tier` and
    `estimated_cost_minor_units` — FUTURE_BUILD_HOOKS already logs `risk_tier`-on-abstain as "worth
    deciding rather than leaving", from `llama3.2` returning `"risk_tier": null` on the same shape.
    Two models now decline to state a risk tier for declining to act.
  - **Zero USD_REAL moved in any arm.** `qwen2.5` was newly exercised through the priced path and its
    bare tag settled at zero as intended; per-book conservation OK, hash chains valid, real-spend
    breaker 0/100, A6 linkage complete.
  - **No code changed.** This ADR records a measurement and two refusals.

### Correction (2026-08-26, same day, before any of it was acted on)

The first version of this ADR was pushed with two figures that **do not reproduce**, and the error was
the same in both cases: a measurement taken while the box was thrashing, reported as a property of
the model. Recorded here rather than silently rewritten, because the wrong numbers reached `main`.

- **"14× slower / 0.53 tok/s / not a usable path on this hardware" — WRONG.** Re-measured under clean
  conditions (`llama3.2` not resident, one sqlite connection reused across a run instead of
  `connect_and_migrate` per wake), `qwen2.5`'s median call latency is **38.1 s, not 162.5 s** — about
  **3× `llama3.2`'s 12.4 s, not 14×**. The original arm was measured with a 2 GB model resident
  alongside a 4.7 GB one on an 8 GB box; `latency_ms` times only the HTTP call, but memory pressure
  is inside that window. Output tokens fell only 1.7× between the arms, nowhere near enough to
  explain 4×. **The first number measured the measurement environment.**
- **"Produced fewer distinct proposals than the model it replaced" — WITHDRAWN.** Re-measured,
  `qwen2.5` at t=0.8 gives **0.56 distinct/wake against the first arm's 0.12** — and on the second
  reading it is the *more* diverse of the two, not the less. The control is stable across the same
  pair of runs (7/16 both times, 0.25 → 0.19), so this is not a harness change; the two runs inside
  the clean arm alone gave 3 and 6 distinct summaries.
- **Therefore: parse rate replicates and the diversity metric does not, at n=16.** Both models'
  parse rates landed within one of themselves on re-measurement; the diversity figure moved by 4.7×
  on the same model at the same temperature. **The `distinct/wake` column cannot support a ranking
  between two models at this sample size** — it can only support the t=0 finding, where the variance
  is provably zero because the replies are byte-identical.
- **What is unaffected.** The load-bearing conclusion does not depend on either withdrawn figure:
  parse rate is a bad sole objective, t=0 makes it meaningless (one sample × 16, landing at 16/16 or
  0/16 by luck of which reply the model converges on), and §14.1 puts sampling in the genome rather
  than the kernel. The t=0 rows are hash-verified. If anything the 2×2 strengthens it — the first
  draft argued t=0 trades compliance for diversity, and the truth is that it does not reliably buy
  compliance either.
- **The lesson, which is the repo's own and was ignored anyway.** CLAUDE.md's testing section says to
  teeth-check a guard by reintroducing the bug; the analogue for a measurement is to re-run the arm
  you are about to draw a conclusion from. Two of three conclusions here came from single arms, and
  both of those were wrong. **A measurement that is going to be written down gets replicated first.**

### Second correction (2026-08-26): re-measured at n=32, and a third claim withdrawn

Each arm was re-run at **4 runs × 8 wakes = 32**, on the metric question the first correction left
open. Three things changed.

- **"1 distinct `response_hash` across 8 calls, verified on all four t=0 runs" — WRONG for
  `llama3.2`, and the verification never covered it.** That check ran only against `qwen2.5`'s
  databases; `llama3.2`'s had been lost to a wiped scratchpad, and the claim was generalised across
  a model it had never been tested on. `llama3.2` at t=0 produces **4 distinct replies per run**, not
  1. What collapses to 1 is the distinct *summary*. The corrected mechanism is now in point 4 above,
  and it argues the original point harder: the prompt provably moved and the proposal did not.
- **The diversity metric was confounded, and the confound favoured the conclusion.**
  `distinct/wake` divides by wakes, so it charges a model for replies that never parsed — and t=0
  parses everything. On that column `llama3.2` t=0.8 and t=0.0 differ by 0.156 vs 0.125 and the
  temperature effect nearly vanishes. On `distinct/parsed` it is 0.455 vs 0.125, a 3.6× gap. **Both
  columns are now reported.** The first correction called this metric untrustworthy for ranking two
  *models*; it was also mis-specified for ranking two *temperatures*.
- **`qwen2.5`'s diversity advantage is confirmed, closing the first correction's open question.**
  At n=32 it beats `llama3.2` on both columns at t=0.8 (0.344 vs 0.156 per wake; 0.500 vs 0.455 per
  parsed) as well as on parse rate. The n=16 figure that started this — "fewer distinct proposals
  than the 3B model" — was wrong in the direction, not merely noisy.

**What n=32 bought, stated plainly.** Parse rates were already stable and stayed stable; per-run
spreads are `[3,3,4,1]`, `[6,7,6,3]`, `[8,8,8,8]`, `[0,0,0,0]`. Nothing about the headline changed.
What changed is that **two of the three supporting claims turned out to rest on artifacts** — one on
a metric definition, one on a verification that had never run on half its subject. Neither was
findable by adding samples; both needed the numbers looked at from a second angle. **Sample size was
not this measurement's weak point, and increasing it would not have caught either error.**

**The decision is unchanged and now rests on cleaner ground:** do not pin temperature in the kernel
(§14.1 makes sampling a mutation operator, and t=0 does not reliably buy compliance in any case —
32/32 on one model, 0/32 on another), and `qwen2.5` stays a live option deferred behind the
temperature question rather than a rejected one. **`qwen2.5` is now the better model on every axis
measured except latency**, where it is ~3.7× slower.

### Third correction (2026-08-26): the diversity the temperature was supposedly destroying was never there

PRIORITIES logged that "distinct summary strings" is a weak measure because two rewordings of one
idea count as two. Replacing it with a semantic measure does not refine this ADR's headline — **it
removes it.**

**The measure.** Each recorded proposal's summary is embedded with a local `nomic-embed-text` call and
scored by **Vendi score** — `exp(H(eigenvalues of K/n))` over the cosine-similarity matrix — the
*effective number of distinct items*: 1.0 when every proposal paraphrases one idea, n when all n are
unrelated. No threshold to tune. It is applied to the proposals the n=32 arms already recorded, not a
fresh run, so a change in the measure cannot be confused with new sampling noise. Calibrated before
use: 8 identical strings → 1.000; **three rewordings of one idea → 1.170 where the string measure says
3**; three unrelated ideas → 2.493.

| arm | proposals/run | **ideas/run (Vendi)** | distinct strings/run |
|---|---|---|---|
| `llama3.2` t=0.8 | 2.75 | **1.048** | 1.25 |
| `llama3.2` t=0.0 | 8.00 | **1.000** | 1.00 |
| `qwen2.5` t=0.8 | 5.50 | **1.216** | 2.75 |
| `qwen2.5` t=0.0 | 0.00 | — | 0.00 |

- **The temperature effect on diversity is ~5%, not 3.6×.** On strings, `llama3.2` t=0.8 vs t=0.0 was
  0.455 vs 0.125 per parsed proposal. Semantically it is **1.048 vs 1.000 ideas per run**. The t=0 arm
  is the stronger control here, not the weaker one: it recorded **8 proposals per run against 2.75**,
  nearly three times as many chances to differ, and still scored exactly 1.000.
- **What the string measure was counting.** `llama3.2` t=0.8 run 2's four proposals are three copies of
  one experiment plus a `strategy` restating it in other words. `qwen2.5` t=0.8 run 2's six are all
  "Fetch the latest POS export data…", its three "distinct" strings differing by a trailing clause.
- **So the headline sentence of this ADR is withdrawn.** "Parse rate is maximised by the setting that
  destroys the colony's variation" is wrong: **there was almost no variation to destroy at any
  temperature.** A Cell proposes ~1 idea per run of 8 wakes whether sampled at 0.8 or 0.
- **The decision does not change, and it never rested on this.** Two independent reasons stand
  untouched: t=0 **does not reliably buy compliance** (32/32 on one model, 0/32 on the other), and
  **§14.1 makes sampling a mutation operator**, so a kernel constant would delete a dimension the spec
  enumerates. A third is now sharper: when a t=0 Cell's replies do not parse it enters a
  **deterministic dead loop** it cannot think its way out of.
- **And a larger problem is exposed, which was hiding behind the metric.** §15.1 shows a Cell its own
  recent proposals; across 128 wakes, on two models, at two temperatures, **it proposed the same thing
  anyway**. Temperature was never the variable that mattered for diversity — it changes surface
  wording, not the idea. **The colony's self-repetition is a §14/§15 design problem, and it is a much
  bigger one than the sampling question this ADR set out to answer.**

**Fourth claim withdrawn, and the tally is the lesson.** Across three corrections this ADR has lost a
latency figure (a thrashing box), a diversity comparison (0.12 vs 0.56 on a noisy metric), a
byte-identity claim (a check that only ever ran on half its subject) and now its headline (a metric
that counted paraphrases). **Every one was an instrument error; none was a sample-size error**, and
n=16 → n=32 caught none of them. The measurement that finally moved the conclusion cost one embedding
model and no new model calls at all.

## ADR-051: The Cell repeats itself because §15.1 shows it what it just said — measured, and the obvious remedy refused

- **Status:** Accepted (measurement); remedy deliberately unbuilt
- **Spec ref:** §14, §14.1, §15.1, §15.2, §23.4, §23.5; ADR-046, ADR-050
- **Context:** ADR-050's third correction found that a Cell proposes **~1 effective idea per run of 8
  wakes**, at any temperature, on either model, and named this a bigger problem than the sampling
  question that surfaced it. FUTURE_BUILD_HOOKS parked three candidate causes. This tests the first:
  §15.1's recent-proposals section shows a Cell what it recently proposed and **never says it should
  propose something else** — so it may be anchoring *to* the list rather than avoiding it.
- **The experiment.** `context.RECENT_PROPOSALS = 0`, which makes `_recent_proposals_section` return
  `None` so the section never renders. Single variable: context was 833 tokens against a 1200 budget
  with `dropped: []`, so removing a section cannot let a previously-dropped one in. Both arms
  `llama3.2` at t=0.8, 4 runs × 8 wakes, **run by the same script** — the control was re-run rather
  than reused, because this thread has already been bitten twice by instrument differences.
  Diversity is Vendi score (ADR-050's third correction), **matched at 3 proposals per run**, because
  Vendi scales with item count and the treatment arm produced more proposals.

  | arm | parsed | proposals/run | **ideas/run (Vendi, first 3)** |
  |---|---|---|---|
  | recent-proposals section shown (control) | 11/32 | 2.75 | **1.053** |
  | section suppressed | 17/32 | 4.25 | **1.957** |

  **An 86% increase in effective distinct ideas.** In the suppressed arm *every parsed proposal was
  distinct* (4/4, 3/3, 5/5, 5/5); in the control, 11 proposals contained 1.25 distinct strings per run.
- **Two independent routes to the same number.** Before running anything, the already-recorded n=32
  data answers a weaker version: **wake 0 of each run has an empty section by construction.** Vendi
  over the four unanchored first-proposals from four independent colonies is **1.970** (`llama3.2`)
  and **1.917** (`qwen2.5`), against 1.048 and 1.216 within an anchored colony. That comparison
  confounds anchored-vs-not with same-Cell-vs-different-Cell, which is why the direct experiment was
  run — but it lands on the same figure the clean manipulation produced.
- **The instrument was checked, not trusted.** The script asserts the section is absent from every
  assembled `context_json` in the suppressed arm and present in the control. Both passed. A
  manipulation that silently fails to reach the prompt would produce a null result indistinguishable
  from a real one.
- **Decision: record the cause, refuse the obvious remedy.** Deleting or shortening the section is
  the change this result invites and it is wrong.
  - **ADR-046 is built on this section.** For a `STRATEGY` proposal there is no consumer and no
    regeneration — *approving it is the act*, and the decision annotation in this very section is the
    entire mechanism by which the act reaches the Cell. Remove the section and ADR-046's subsystem
    silently stops working, with no test failing, because what it delivers is prose in a prompt.
  - **§15.2 requires episodic memory**, and the section is it. A Cell that cannot see what it has
    already proposed cannot notice it is repeating — the diversity gain would come from amnesia, not
    from judgement, and amnesia has its own §23.4 cost: `repeat_after_rejection` is only meaningful
    if the Cell was told it was rejected.
  - **So the remedy is about what the section *says*, not whether it appears** — and that is a
    prompt change, which §14.2 says must be evaluated against counterfactual twins rather than
    shipped on a single measurement. The candidate worth testing first is the cheapest: the section
    is titled "reference material, not instructions" and never states that a *new* proposal is
    wanted. **Naming the absent expectation is the same move ADR-049 made** when it found the prompt
    named no field the parser rejects.
- **What it displaced.**
  - **Deleting the section**, per above — the change with the largest measured effect and the largest
    unmeasured cost.
  - **Concluding from the wake-0 comparison alone.** It was free, already recorded, and pointed at
    the right answer, but it varies two things at once. It is reported as corroboration, not
    evidence.
  - **Attributing the parse-rate difference.** The suppressed arm parsed 17/32 against 11/32, which
    is **not significant** (p = 0.10). A shorter prompt plausibly parses better, but this measurement
    does not show it and the claim is not made.
- **Consequences:**
  - **The remaining two candidate causes are now lower priority but not eliminated.** Anchoring
    explains an 86% swing; it does not explain why the suppressed arm still scores 1.96 rather than 3
    on three proposals. The genome pinning market/problem/product, and the wake reason being
    identical on every wake, remain untested and can only account for the residue.
  - **This is the first measured link from a prompt section to a behavioural outcome in this repo**,
    and it was invisible to every test: the suite and the golden run are green in both arms, because
    `MockProvider`'s reply is an input rather than a response to the prompt's wording — ADR-049's
    blind spot, hit a third time in a third place.

## ADR-052: The Cell copies what it can see, and cannot be instructed out of it — §14.2 twins on §15.1's section

- **Status:** Accepted (measurement + recommendation); the code change is **not** made here
- **Spec ref:** §14.1, §14.2, §15.1, §15.2, §23.4; ADR-046, ADR-049, ADR-050, ADR-051
- **Context:** ADR-051 measured that suppressing §15.1's recent-proposals section takes effective
  distinct ideas from 1.05 to 1.96 per run, refused to delete the section (ADR-046's `STRATEGY`
  mechanism lives inside it), and parked three candidate rewordings. §14.2 requires prompt mutations
  to be evaluated against counterfactual twins — "same task, environment, seed where possible, and
  budget, differing by one prompt-level change" — and never promoted on preference alone. This is
  that evaluation.
- **The arms.** All `llama3.2` t=0.8, same genome, same script, one batch. Each variant is **one edit**
  relative to control. Diversity is Vendi score (ADR-050), **matched at 3 proposals per run** because
  Vendi scales with item count. `control` and `nosummary` were deepened to 12 runs once the first
  pass identified them as the pair that mattered.

  | arm | one-line edit | runs | parsed | **ideas@3** |
  |---|---|---|---|---|
  | `control` | as shipped | 12 | 52/96 | **1.089 ± 0.147** |
  | `heading` | heading names the expectation | 4 | 15/32 | **1.054 ± 0.078** |
  | `exclusion` | body marks each entry "do not propose again" | 4 | 12/32 | **1.202 ± 0.176** |
  | `nosummary` | body drops the summary, keeps kind + decision | 12 | 40/96 | **1.852 ± 0.248** |
  | `suppressed` | section absent (ADR-051's ceiling, not a candidate) | 4 | 20/32 | 1.939 ± 0.138 |

  `nosummary` exceeds `control` in **89 of 90 pairwise run comparisons** and recovers **95% of the
  suppression ceiling** while the section still renders.
- **Finding: the mechanism is not instruction-following, and ADR-051 predicted the wrong winner.**
  ADR-051 nominated the heading edit as the cheapest candidate, reasoning by analogy with ADR-049's
  "the prompt names no field the parser rejects" — name the absent expectation and the model will
  meet it. **It does nothing** (1.054 vs 1.089). An explicit per-entry "do not propose again" buys
  15%. Removing the copyable text buys everything. **The Cell is not disobeying an instruction to
  vary; it is completing a pattern it can see.** Instructions aimed at a copying behaviour do not
  reach it — a result that should be assumed to generalise to any future attempt to fix a
  prompt-driven behaviour by adding a sentence about it.
- **Decision: recommend hiding the summary only for proposals nobody has decided yet — narrower than
  the arm that was measured, and strictly safer.**
  - **Every one of the 52 proposals across the control arms is `pending`.** Zero approved, zero
    rejected: an unattended colony queues and nothing is reviewed. So **ADR-046's approve/reject
    channel carried no information in any arm of this experiment**, and `nosummary`'s measured gain
    cost ADR-046 nothing *only because ADR-046 was never exercised*.
  - That is also why `nosummary` lands so close to `suppressed`: with everything pending, its body
    reduces to `- [experiment] -> waiting on a person` three times, which is near-suppression.
  - **The two goals are therefore separable rather than in tension.** The summaries doing the
    anchoring are attached to entries that convey *no decision*. Hiding the summary for `pending`
    and `not reviewed` entries while keeping it for `approved`/`rejected` is identical to
    `nosummary` in the regime measured — so it inherits the full measured gain — and preserves
    ADR-046 exactly when ADR-046 has something to say.
- **What it displaced.**
  - **Adopting `nosummary` as measured.** It hides the summary unconditionally, including on the
    decided proposals ADR-046 exists to deliver. Its number is real; its scope is wrong.
  - **The heading edit**, which this ADR's predecessor recommended and which is now measured at zero.
  - **Making the code change here.** The recommendation touches the assembled prompt, so it moves the
    golden run — Amendment A12 makes that a deliberate reviewed act with a written migration note,
    not a rider on a measurement. It is queued in PRIORITIES instead.
- **Consequences:**
  - **The decided branch is untested and this experiment cannot test it.** No proposal was ever
    approved or rejected, so nothing here shows what a Cell does when shown an *approved* summary —
    including whether it anchors to that too, which would put ADR-046 and diversity back in genuine
    conflict. A follow-up needs an arm that actually approves proposals mid-run.
  - **The parse-rate difference is not claimed.** 40/96 vs 52/96 is p = 0.11.
  - **Two instrument failures, both mine, both caught.** The in-script check grepped `context_json`
    for body text, but `Section.to_record()` deliberately stores only name, tokens and `required` —
    so the check could never pass and reported BROKEN against manipulations that were in fact
    correct. Replaced with a token-count check that can fail for the right reason (control's section
    median 81 tokens, `nosummary`'s 21). Separately, the experiment script had no `__main__` guard,
    so importing it to inspect the variants re-ran the batch and overwrote four control databases
    mid-flight; caught from an mtime later than the arm that ran after it, and the control arm was
    re-run from scratch.

### Implemented (2026-08-26)

`context._was_decided` gates the summary; `_recent_proposals_section` renders
`- [kind]\n    -> note` for an undecided proposal and keeps the summary once a person judged it.
Golden expectation **25 -> 26**, three sections, token counts only; `balances` identical in every
account in every book and `proposals` byte-identical.

**One judgement this ADR did not settle: `expired` is not decided.** The measurement had no expired
proposals, so the arm never covered it. The line is drawn where `_decision_note`'s own docstring
already draws it — "collapsing them would tell a Cell it was judged when nobody judged it" — so a
closed review window withholds the summary like any other undecided state. It is the one status that
looks decided and is not, which is why it has its own test.

**Confirmed live, because no replay can see a prompt edit** (the reason ADR-052 needed measuring at
all): the shipped kernel scores **1.833 effective ideas per run** against the experiment's 1.852 and
control's 1.089, with every parsed proposal distinct in all four runs.

## ADR-053: An approved summary anchors exactly as hard — and ADR-052's reason for showing it was wrong

- **Status:** Accepted (measurement); the remedy is **not** shipped here
- **Spec ref:** §14.2, §15.1, §23.4; ADR-046, ADR-051, ADR-052
- **Context:** ADR-052 shipped `_was_decided`: §15.1's proposal log shows a summary once a person
  judged the proposal, and withholds it while undecided. Every arm behind that decision left every
  proposal `pending`, because an unattended colony queues and nobody reviews — so **the decided
  branch was never measured**, and both ADR-052 and the implementation said so in writing. This is
  that measurement.
- **The design.** Approving does more than reveal a summary — it sets a standing strategy, issues
  grants, changes what §15 assembles. So approve-vs-pending would confound those with the anchoring
  under test. Three arms, `llama3.2` t=0.8, 4 runs × 8 wakes:

  | arm | approvals | section | parsed | **ideas/run** | ideas@2 |
  |---|---|---|---|---|---|
  | `decided_shown` | every proposal | 64 tok, summaries **present** | 13/32 | **1.122** | 1.029 |
  | `decided_hidden` | every proposal | 35 tok, summaries withheld | 14/32 | **1.764** | 1.467 |
  | `pending` (shipped default) | none | 21 tok, summaries withheld | 18/32 | **2.195** | 1.432 |

  `decided_shown` vs `decided_hidden` holds every approval side-effect constant and varies only
  whether the summary renders. **`decided_hidden` is higher in 100% of 16 pairwise run comparisons.**
- **Finding: approval makes no difference to anchoring.** `decided_shown` scores **1.122**, which is
  the original pre-ADR-052 control's **1.089** — the anchoring returns in full the moment the summary
  is visible, whether or not a person approved it. A Cell copies text it can see; the annotation
  beside that text is not what it is reading. **So ADR-046 and diversity are in genuine conflict on
  the branch ADR-052 shipped**, and the shipped rule is safe only in a colony nobody is reviewing.
- **But ADR-052's stated reason for showing the summary was wrong, and that is the way out.** The
  reasoning was: "APPROVED is meaningless if the Cell cannot tell *what* was approved." Checking
  where an approved strategy actually reaches the Cell, it appears in **two** sections — the proposal
  log *and* `Your standing strategy (your words, approved by a person — this is how you operate)`,
  which is its own dedicated, independent channel. **ADR-046's delivery for `STRATEGY` does not run
  through the proposal log at all**, so the summary there is redundant for the one kind ADR-046 is
  about. The same shape is likely for the other kinds — an approved experiment reaches the Cell
  through §15.1's current-experiment section, an approved tool through its grant — but that is
  inferred, not measured here.
- **What it displaced.**
  - **Leaving `_was_decided` as shipped.** Defensible only while nothing is ever approved. The first
    attentive operator would halve the colony's effective diversity, and no test would notice.
  - **Reverting to hiding summaries unconditionally, immediately.** It is very likely right — and it
    is the third design iteration on this section in two days, on a branch whose delivery channels
    are inferred rather than measured for three of four kinds. §14.2 got ADR-052's prediction wrong
    once already by reasoning instead of measuring; the correct next step is an arm that verifies
    each kind's approval still reaches the Cell with the proposal-log summary gone, then a twins run.
  - **Concluding from `pending` vs `decided_shown` alone.** It shows the right direction (2.195 vs
    1.122) and attributes it wrongly: approval changes several sections at once. `decided_hidden`
    is the arm that isolates the summary, and it is why the claim here is about the summary rather
    than about approval.
- **Consequences:**
  - **`_was_decided` is now known to be wrong in the direction it guards**, and its docstring's
    "untested, and the reason to watch this" is resolved: the Cell does anchor to an approved
    summary. The follow-up is queued rather than shipped.
  - **`decided_hidden` (1.764) scores below `pending` (2.195)**, so approval itself costs some
    diversity through its other effects — a standing strategy is a strong instruction, and the Cell
    follows it. That is a separate finding and not obviously a fault.
  - **Instrument checked before the numbers counted**: 13 and 14 approvals made against 0, run-0
    statuses all `approved` against all `pending`, and section medians of 64 / 35 / 21 tokens
    confirming summaries present, withheld, and withheld.

### Implemented (2026-08-27) — with the per-kind audit that ADR-053 got wrong

`_was_decided` is deleted; the proposal log renders `- [kind]\n    -> note` for every status. Golden
expectation **26 -> 27**, the same three sections, token counts only; `balances` identical in every
account in every book and `proposals` byte-identical. Confirmed live at **2.122 effective ideas per
run**, against 1.833 under ADR-052's conditional rule and 1.089 before either.

**The audit ADR-053 called for contradicted ADR-053's own inference on three of four kinds.** It
assumed the other kinds' approvals reached the Cell the way `STRATEGY`'s did. Measured, with the
summary hidden:

| kind | does the approved substance still reach the Cell? |
|---|---|
| `strategy` | **yes, immediately** — `Your standing strategy`, ADR-046's real channel |
| `experiment` | **yes, once the grant is started** — `Your current experiment` |
| `tool_request` / `external_action` | **yes, on consumption** — the grant's result reaches the Cell |
| **any kind, rejected** | **no.** The reason survives in the note; the subject does not |

So the pattern is that approval's consequence arrives **when the grant is consumed**, not when it is
granted — and `STRATEGY` looks immediate only because approving it *is* the act, so there is nothing
to consume. That leaves one real cost rather than none: **a rejected proposal loses its subject.**
The Cell learns *that* it was rejected and *why*, and not *what*. It is pinned by
`test_a_rejected_proposal_loses_its_subject_and_that_is_recorded` rather than fixed, because the
alternative — showing rejected summaries — reintroduces the anchoring this ADR measured, and
choosing between them is a §23.4 question that deserves its own arm. §23.4's
`repeat_after_rejection` detector is now the only thing watching for the repeat that invites.

## ADR-054: Showing a rejected proposal's wording causes the §23.4 repeat it was meant to prevent

- **Status:** Accepted — **no code change; the shipped rule is confirmed correct**
- **Spec ref:** §14.2, §15.1, §23.4, §23.5; ADR-046, ADR-051, ADR-052, ADR-053
- **Context:** ADR-053 hid the proposal-log summary for every status and left one known cost: a
  rejected proposal loses its subject, so the Cell learns *that* it was rejected and *why*, but not
  *what*. Every other kind keeps a channel (approval's substance arrives on grant consumption); a
  rejection has none. Restoring the wording for rejections only was the obvious remedy, pinned by a
  test rather than shipped, because it would reintroduce the measured anchoring. Two predictions
  genuinely diverged, so it needed an arm rather than an argument:
  - **anchoring** — the Cell copies text it can see, as it did for `APPROVED`, so showing the
    rejected wording makes it re-propose the rejected thing;
  - **learning** — `REJECTED` is a strong negative signal, so seeing the subject steers the Cell away
    and *raises* diversity.
- **The instrument was already in the kernel.** §23.4's `repeat_after_rejection` detector compares
  normalised summaries and persists to `approval_signals`. It answers the first prediction directly,
  without any metric of mine standing between the question and the answer. Both arms reject every
  proposal as it is made, holding the rejection side-effects constant and varying only whether the
  rejected entry shows its wording.

  | arm | parsed | ideas@3 | **§23.4 `repeat_after_rejection` fired** |
  |---|---|---|---|
  | `reject_shown` (wording restored for rejections) | 20/32 | **1.210** | **12** |
  | `reject_hidden` (shipped rule) | 13/32 | **1.922** | **0** |

  `reject_hidden` is higher on diversity in **100% of 12 pairwise run comparisons**.
- **Decision: do not restore the wording for rejections. The shipped unconditional rule stands.**
  The remedy does not merely cost diversity — **it causes the precise failure §23.4 exists to catch.**
  Twelve `repeat_after_rejection` signals against zero: a Cell shown the wording of a proposal a
  person just rejected proposes it again. The feature intended to teach a Cell what not to repeat is
  what makes it repeat. `REJECTED` is not read as a negative instruction any more than `APPROVED` was
  read as a positive one (ADR-053) — **the label is not a modifier on the text beside it**, in either
  direction, which is now measured twice from opposite signs.
- **What it displaced.**
  - **Restoring the summary for rejections only.** ADR-053 queued it as the likely next move and
    named the trade as diversity-versus-§23.4 feedback. The trade does not exist: the arm loses on
    both.
  - **Reasoning from ADR-053's `APPROVED` result.** It would have reached the same conclusion, and
    would have been an inference from a positive label to a negative one — the reasoning-instead-of-
    measuring move that was wrong three times earlier in this thread. §23.4's detector cost one arm
    and settles it as fact.
  - **Treating the lost subject as a debt to repay.** It is the price of the rule and it is worth
    paying, not a gap awaiting a fix. `test_a_rejected_proposal_loses_its_subject_and_that_is_recorded`
    stays as the written-down cost; this ADR is why it is not a TODO.
- **Consequences:**
  - **Parse rate rose while the colony got worse** — 20/32 shown against 13/32 hidden. A Cell
    re-proposing a known-good shape parses more easily. **The clearest instance yet of ADR-050's
    theme**: any tuning that watches parse rate alone would have chosen the arm that breaks §23.4.
  - **§23.4's detector is now doing double duty** — a §23.5 tripwire, and the only measurement in
    this repo that reports a behavioural failure directly rather than through a metric built for the
    occasion. Worth reaching for first when a future question can be phrased as "does the Cell do the
    bad thing".
  - **No code changed.** The rule shipped in ADR-053 is confirmed by the experiment that was queued
    to challenge it.

## ADR-055: The wake reason matters, and rotating it makes a Cell act on things that never happened

- **Status:** Accepted (measurement); **the naive remedy is refused**, the real one is queued
- **Spec ref:** §0.3, §15.1, §17.2, §19.4, §23.1; ADR-051, ADR-052, ADR-054
- **Context:** ADR-052 parked three candidate causes for a Cell proposing ~1 idea per run. Anchoring
  is fixed (ADR-051/053/054) and the colony sits at ~2 effective ideas per run of 8. This tests the
  second: `Why you were woken` renders the wake reason verbatim and the scheduler emits
  `scheduled research cycle` every time, so nothing in the prompt ever says the situation changed.
- **The measurement.** Two arms, `llama3.2` t=0.8, **12 runs × 8 wakes each** — deepened from 4 after
  the first pass came back at p = 0.11, the exact underpowered profile that produced four withdrawn
  claims earlier in this thread. `wake_varied` cycles the kernel's own §17.2 reasons; `wake_same` is
  the shipped scheduler.

  | arm | runs | parsed | **ideas@3** |
  |---|---|---|---|
  | `wake_same` (shipped) | 12 | 46/96 | **1.764 ± 0.220** |
  | `wake_varied` | 12 | 38/96 | **2.025 ± 0.217** |

  **+0.261, higher in 80% of 100 pairwise comparisons, exact one-sided p = 0.0116.** The parse-rate
  difference is not significant (p = 0.31). Instrument check: 8 distinct reasons reaching the prompt
  against 1.
- **So the hypothesis holds — and it is the smallest of the three.** Anchoring was +86%; this is
  +15%. Worth having, not worth much on its own.
- **Decision: do not rotate the wake reason. Emit the reason the event actually justifies.** The
  experiment asserted reasons rather than earning them — no tool result had arrived, no capital had
  been allocated — and that was flagged in the script before it ran, which is why the result was
  checked for it. **Three of 38 proposals in `wake_varied` responded to an event that never
  happened**, against **zero of 46** in the control:
  - *"Notify bookkeepers of an available tool result and request a review…"*
  - *"Email notification about available tool results to bookkeeping community forums"*

  The Cell was told a tool result was available, believed it, and proposed **contacting customers
  about it**. In a colony with an approved `external_action` grant and §27.1 autonomy enabled, that
  is a real email about a result that does not exist.
- **What it displaced.**
  - **Rotating wake reasons in the scheduler**, which is the one-line reading of this result and
    would manufacture diversity by feeding the Cell false premises. **Part of the measured +15% is
    that failure**, so the effect size for honest wake reasons is smaller than 0.261 and this
    measurement cannot say by how much.
  - **Concluding from the first pass.** At 4 runs it read +0.355 and p = 0.11; deepening moved the
    estimate *down* and the confidence up. Acting on the first pass would have overstated the effect
    and still landed on the dangerous remedy.
- **Consequences:**
  - **This is a §0.3 hazard from the other side.** The clause says a Cell may explain a result and
    never define it; the mirror is that **the kernel must not assert to a Cell something that is not
    so**. `Why you were woken` is `required=True` and never dropped, so whatever it says is read
    every time, and a Cell cannot distinguish a scheduler placeholder from a real event.
  - **The honest fix already has its vocabulary.** `WAKE_TOOL_RESULT`, `WAKE_CAPITAL_ALLOCATION`,
    `WAKE_HUMAN_DECISION`, `WAKE_AUDIT_REQUEST`, `WAKE_EXTERNAL_ACTION_RESULT` are all defined and
    all emitted somewhere; the gap is that the *scheduler's* tick always says
    `scheduled research cycle`. Wiring real events to the reasons they justify is additive and needs
    no new vocabulary — and it is worth roughly a 15% ceiling, so it should be argued on correctness
    rather than on this number.
  - **§19.4's labelling assumption is now doubly suspect.** ADR-053 and ADR-054 showed a label does
    not change how a model treats the text beside it; this shows a Cell takes a kernel-authored
    section as true without corroboration. Both bear on whether "untrusted" markings do any work.

## ADR-056: The genome is not the constraint — it is what makes a proposal concrete at all

- **Status:** Accepted (measurement); **hypothesis rejected**, no code change
- **Spec ref:** §9.4, §14, §15.1, §16.2, §16.3; ADR-052, ADR-055
- **Context:** ADR-052 parked three candidate causes for a Cell proposing ~1 idea per run of 8 wakes.
  Anchoring is confirmed and fixed (ADR-051/053/054, +86%); the wake reason is confirmed, small, and
  its obvious remedy refused (ADR-055, +15%). This is the third and last: that the genome pins
  market/problem/product so tightly that one idea is the honest answer.
- **The measurement.** Two arms, `llama3.2` t=0.8, 8 runs × 8 wakes. `genome_loose` keeps every §16.2
  field and roughly the same length, and broadens the scope: "small businesses that keep their own
  books" against "independent bookkeepers serving 5-20 small retail clients".

  | arm | parsed | ideas (all) | **ideas@2** | **names a concrete deliverable** |
  |---|---|---|---|---|
  | `genome_tight` | 26/64 | **1.887** | 1.513 ± 0.111 | **26/26 (100%)** |
  | `genome_loose` | 19/64 | 1.718 | 1.612 ± 0.165 | **1/19 (5%)** |

  **Diversity: no effect.** +0.099, 65% of 48 pairwise comparisons, exact one-sided p = 0.207 — and
  on the all-proposals measure the *tight* genome scores higher. **The hypothesis is rejected.**
- **The pre-registered check is the finding.** It was written into the script before the arm ran
  (the habit ADR-055 earned): a loose genome can raise a diversity score by making proposals vaguer
  rather than more varied. It did not raise the score — and concreteness collapsed anyway, from
  **100% to 5%**, at nearly identical summary length (83 vs 87 chars). The loose arm is not shorter,
  it is emptier: *"Refine our software to reduce routine back-office work"*, *"Invest in customer
  support"*. One proposal asked to **"Send reminder about the upcoming scheduled research cycle"** —
  a Cell with no market hypothesis proposing about its own scaffolding, because that is the only
  concrete noun left in its context.
- **So the genome is load-bearing for proposal *quality*, not merely for identity.** §16.3 makes the
  market hypothesis inheritable so a lineage stays that lineage; this measures a second job nobody
  had written down. **It is the only thing in the context telling a Cell what a proposal is
  *about*** — remove the specificity and the Cell still proposes, still parses less often, and says
  nothing. Parse rate falls too (19/64 against 26/64), which is consistent: a vaguer prompt gives the
  model less to be precise with.
- **What it displaced.**
  - **Loosening the seed genomes** to buy diversity, which §9.4's founder-effect measures might have
    seemed to invite. It buys none, and costs everything that makes a proposal actionable.
  - **Reading "the genome constrains the Cell" as a defect.** It constrains it the way §16.3 intends;
    ~2 ideas per run is the tight genome's honest answer, not a symptom.
- **Consequences:**
  - **All three of ADR-052's candidate causes are now accounted for**, and the search for
    prompt-level causes of self-repetition is complete: one large and fixed, one small with a refused
    remedy, one rejected. **The residual ~2 effective ideas per run of 8 is the model's ceiling on
    this hardware, not a defect in the prompt.** Anything further is a model decision (ADR-050) or a
    §14 mutation-operator decision, not a context-assembly one.
  - **A concreteness measure now exists and is worth keeping** — proportion of proposals naming a
    real deliverable. It separated two arms that the diversity score could not tell apart, and it is
    the first metric in this thread that measures whether a proposal is *worth* anything rather than
    whether it differs from its neighbour.
  - **Phase 2 warning.** Diversity and concreteness move independently: `genome_loose` was
    nominally *more* diverse per pair and 20× less concrete. Selection tuned on variety alone would
    favour exactly the Cells that have stopped saying anything.

## ADR-057: A human decision wakes the Cell — the one wake reason §17.2 names that nothing produced

- **Status:** Accepted
- **Spec ref:** §17.2, §23.3, §25.2, Charter C6, C8; ADR-039, ADR-046, ADR-055
- **Context:** ADR-055 measured that varying the wake reason raises effective diversity ~15%, and
  refused the obvious remedy: rotating reasons made a Cell act on fictions — told `tool result
  available` with none, it proposed emailing customers about it. The queued follow-up was "wire real
  events to the reasons they justify". **Auditing that turned up a smaller and more specific gap
  than the ADR had claimed.**
- **Six of the seven reasons were already earned.** `WAKE_TOOL_RESULT` by `tools.py`,
  `WAKE_CAPITAL_ALLOCATION` by `promotion.py`, `WAKE_AUDIT_REQUEST` by `auditor.py`,
  `WAKE_EXTERNAL_ACTION_RESULT` by `external_actions.py`, `WAKE_APPROVAL_EXPIRED` and
  `WAKE_GRANT_EXPIRED` by the sweep. **ADR-055's "only the scheduler's tick is hardcoded" was wrong
  twice over:** the scheduler's tick is *honest* — a scheduled tick genuinely is a scheduled research
  cycle, not a placeholder — and the real gap was elsewhere. **`WAKE_HUMAN_DECISION` was defined in
  `deliberation` and referenced nowhere else**: the fifteenth reserved socket, and the only entry in
  §17.2's list with no producer.
- **Decision: `approve` and `reject` enqueue `WAKE_HUMAN_DECISION` inside their own transactions.**
  A person deciding is a real event; until now it produced an audit record and no wake, so a Cell
  learned what was decided only whenever it next happened to tick. For a rejection that matters most
  — ADR-053 established a rejection has no other channel at all, and §25.2 wants the reasons for
  promotion *or rejection* to reach the Cell.
  - **Inside the decision transaction**, following `expire_due`'s established pattern
    (`_enqueue_wake_locked`), so a committed decision and its wake cannot come apart.
  - **Idempotent on the request** (`human-decision:{request_id}`), so redelivery cannot buy a second
    deliberation — Charter C6.
  - **Silent for a dead or quarantined Cell.** `deliberate` *records* a refusal rather than raising,
    so waking one would turn every decision about a dead Cell into a deliberation row saying it could
    not think (Charter C8).
  - **Expiry keeps its own reasons.** The review window closing is not a judgement — the same line
    `_decision_note` refuses to blur, and relabelling it would be the §0.3 mirror ADR-055 named: the
    kernel asserting to a Cell something that is not so.
- **What it displaced.**
  - **Rotating wake reasons in the scheduler**, refused by ADR-055 and not revisited here.
  - **Waking on expiry as a "decision".** It is the single most tempting way to make the wake fire
    more often, and it is exactly the falsehood this whole line of work exists to prevent. It has its
    own teeth-check.
  - **Treating ADR-055's next-step as correct.** It said the scheduler was the gap. The audit says
    the scheduler is right and `WAKE_HUMAN_DECISION` was the gap — recorded because the ADR is
    already pushed and a reader would otherwise inherit the wrong target.
- **Consequences:**
  - **Golden expectation 27 -> 28**, one section: `event_inbox` `cell_wake` rows 9 -> 20, the
    scenario's 11 decisions. **`deliberations`, `proposals` and `model_calls` are byte-identical** —
    the scenario never drains the inbox, so this adds a wake and changes nothing any Cell thought —
    and `balances` is identical in every account in every book.
  - **The golden scenario now exercises six distinct wake reasons** where it previously exercised
    five, which is worth keeping: a scenario that only ever ticks cannot catch a reason wired to the
    wrong event.
  - **A structural test now asserts every §17.2 reason has a producer**, so the next reason added
    either gets wired to the event that justifies it or is listed deliberately as inert.
  - **Teeth-checked five ways**, all caught, including relabelling expiry as a human decision.

### Correction to ADR-055 (2026-08-27): the +15% does not survive honesty

ADR-055 measured +15% effective diversity from varying the wake reason, warned that part of it was
the Cell believing false premises, and said the wiring should be argued "on correctness, not on the
15%". ADR-057 then wired the one genuinely missing reason. **Re-measured with earned reasons, the
effect is gone.**

Three arms, `llama3.2` t=0.8, 8 runs × 8 wakes, **wakes drained from the inbox** so a reason is
whatever the kernel actually earned:

| arm | parsed | **ideas@3** | wake reasons that drove deliberations |
|---|---|---|---|
| `unreviewed` | 31/64 | 1.802 ± 0.286 | 64 scheduled |
| `reviewed_flat` | 29/64 | **1.809 ± 0.213** | 64 scheduled (approvals happen, wake suppressed) |
| `reviewed_earned` | 31/64 | **1.827 ± 0.248** | 37 scheduled + **27 human decision** |

**`reviewed_flat` vs `reviewed_earned` is the experiment** — both approve every proposal, so the
standing strategy, the grants and everything else approval changes are held constant, and only the
wake reason varies. **+0.018 (+1%), higher in 41% of pairwise comparisons, p = 0.73.** A null, and
by rank very slightly the wrong way.

- **What this retires.** ADR-055's +15% was an artifact of rotation, not a property of wake reasons.
  Its own caveat — that 3/38 proposals in the varied arm responded to events that never happened —
  turns out to have understated the problem: strip the falsehoods and essentially nothing remains.
- **What it does not claim.** ADR-055 rotated **eight** reasons across eight wakes, including exotic
  ones a real colony rarely emits in sequence. A reviewed colony earns **two** — `scheduled research
  cycle` and `human decision`. So the honest finding is *"at the variety a real colony actually
  produces, the effect is nil"*, not *"wake reasons cannot matter"*. A colony running tools,
  allocations and audits would earn more variety, and this measurement says nothing about that.
- **ADR-057 was right to ship and right about why.** It was argued on §17.2 conformance and the §25.2
  feedback loop, never on the diversity number, and it explicitly told the reader to expect less than
  +15%. The number came back at +1%. **The instruction to argue it on correctness is now
  measured-correct rather than merely prudent.**
- **The self-repetition ledger closes harder.** Anchoring +86% and fixed; wake reason ~0% once
  honest; genome rejected. **The residual ~1.8–2.0 effective ideas per run of 8 is the model's
  ceiling**, and two of the three candidate causes turned out to be worth nothing once measured
  properly.

## ADR-058: Concreteness is §13.4, and the instrument ADR-056 used had never itself been measured

- **Status:** Accepted (tooling + measurement); no kernel change
- **Spec ref:** §13.4, §13.5, §12.1, §23.5, §24.3, §31; ADR-050, ADR-056
- **Context:** ADR-056 rejected the genome hypothesis and found something it was not looking for:
  loosening a Cell's market hypothesis left diversity unchanged and collapsed the proportion of
  proposals naming a real deliverable from 100% to 5%. PRIORITIES then carried the warning —
  **a Phase 2 selector tuned on variety alone would favour exactly the Cells that have stopped
  saying anything** — and noted the measure "is not yet anywhere in the repo". It never had been:
  it lived in a scratch script and was gone by the next session, *the day after* `scripts/` was
  created to stop that.

### The spec had already named this, and nobody in this repo had ever cited it

`grep` for the socket before designing the subsystem, and §13 answers:

> **§13.4 Fake-novelty detection.** Flag ideas where only the industry label changed, ordinary
> freelancing is described exotically, the same mechanism is renamed, or **no new
> capability/transaction structure exists**.
>
> **§13.5 Why required.** LLMs are skilled at producing rhetorically novel but structurally
> ordinary ideas.

§13.5 is ADR-056's finding, written down before any of it was measured. §13.4 is neither in
`PRIORITIES.md`, `FUTURE_BUILD_HOOKS.md`, nor anywhere in this file before this entry — the
sixteenth reserved socket, and the first one found by reading a *justification* clause rather than
a mechanism clause. It also settles the Phase 2 warning in the spec's own vocabulary: §12.1 makes
`novelty distance` a MAP-Elites **descriptor**, and §13.4 is what stops a Cell from cheating it.

### What was built

`scripts/concreteness.py`, `scripts/concreteness_fixture.json`, `scripts/genomes/loose.json`, a
`--genome` flag on the arm harness, and `tests/test_analysis_boundary.py`.

- **Quote, then verify — not a yes/no judge.** The judge is asked for the *exact words* naming a
  specific thing the work is about; the verdict is then decided deterministically by checking that
  every content word of the quote really appears in the summary. §24.3 in order: "verification →
  deterministic tools first, model second". A judge that invents a deliverable lands in a third
  bucket, `unverified`, and is reported rather than folded into either answer. It has not happened
  yet — 0 of 50 — which is a fact worth having rather than an assumption worth making.
- **The judge may not be the generator's family.** §24.3 routes criticism to a "different
  provider/family". The generating model is read out of `model_calls.requested_model` and a
  same-family judge is refused with exit 2 — `llama3.2` writes the proposals, `qwen2.5` grades
  them. Self-grading is worth nothing: a model that thinks "improve our software" names a
  deliverable will think so twice.
- **The judge runs at temperature 0, and ADR-050's warning does not transfer.** ADR-050 is about
  *generation*, where greedy decoding froze a Cell into one reply it could not escape. This is
  classification (§24.3: "classification/extraction → cheap or local"), where a reproducible answer
  is the point — an instrument that scores differently on Tuesday cannot separate two arms.
- **One clause, one direction.** Only §13.4's fourth flag is scored. The other three need a *prior*
  (a label that changed *from* something, a mechanism renamed *from* something) and §31's
  `novelty_archive` — which does not exist — is where that prior would live. And the flag reads one
  way only: naming no object is evidence of no new structure; naming one proves specificity, not
  novelty.
- **`abstain` is excluded from the denominator.** A Cell declining to act has no deliverable by
  design, and scoring a principled refusal as waffle would punish the honest answer §23.1 wants.

### The instrument check is the finding

The judge was measured against 24 hand-labelled proposals — a seeded random sample of both arms,
labels and reasons committed so they can be argued with — **before any arm number was read**.

| rubric | agreement | missed a real deliverable | invented one |
|---|---|---|---|
| first draft | 18/24 | 6/9 | 0 |
| shipped (adds "ignore the opening verb") | **19/24** | **5/9** | **0** |

The judge is systematically conservative: it reads "Test the effectiveness of a new matching
algorithm for reconciling POS exports and bank feeds" as naming nothing, because the sentence opens
with an intention verb. **Every error is in one direction, and that direction is safe** — an arm
with no objects has none to miss, so the bias attenuates the concrete arm and can only *understate*
a gap. So `--selftest` gates on **false positives, not on agreement**: gating on agreement would be
gating on a number stored in the same file, which is this repo's recurring way of writing a test
that passes for the wrong reason.

One rubric revision was allowed and taken. Stopping there is deliberate — a rubric tuned until it
matches its own labels measures the tuning.

### The measurement (llama3.2, t=0.8, 8 runs × 8 wakes per arm; judge qwen2.5, t=0)

| arm | parsed | **names a deliverable** | ideas@2 |
|---|---|---|---|
| `genome_tight` | 36/64 | **13/36 = 36%** | 1.524 ± 0.056 |
| `genome_loose` | 14/64 | **0/14 = 0%** | 1.467 ± 0.065 (4 runs with n ≥ 2) |

**Fisher exact one-sided p = 0.0065.** Not one of the loose arm's fourteen proposals named a single
object of its own business, across eight independent runs: *"Test the revenue growth hypothesis of
our software"*, *"Streamline bookkeeping processes to reduce administrative burden"*, *"Evaluate the
impact of automated bookkeeping on small businesses' productivity"*. The closest miss was
*"Understand the need for automated bookkeeping better through user surveys and case studies"* — the
judge scored it empty, which is one of the five misses the fixture predicts.

**ADR-056's diversity null replicates**: 1.524 vs 1.467 at matched n, against its 1.513 vs 1.612.
Diversity and concreteness still move independently, now with an instrument that lives in the repo.

**ADR-056's 100% does not replicate, and cannot.** The rubric that produced it no longer exists,
so 100% vs 5% and 36% vs 0% are not two measurements of one quantity — the second is stricter
(it requires a *named object*, not a domain-flavoured phrase) and is a lower bound besides.
What replicates is what was load-bearing: the direction, the completeness of the separation, and
the independence from diversity. **An absolute rate from a lost instrument is not a result**, and
recording that is more useful than defending the number.

### What it displaced

- **A lexical vagueness word-list.** Cheap, deterministic, no model — and a knob that would have
  been tuned on the two arms it was meant to separate. A metric one knob drives to 100% measures the
  knob. The judge's rubric is a knob too, which is why its generic examples ("our product", "the
  workflow", "operations") are deliberately *not* drawn from either arm.
- **A yes/no judge.** Simpler, and there would be nothing to check: the answer would be a verdict
  with no evidence attached, and no way to tell a judgment from a hallucination.
- **`llama3.2` as judge** — the model already resident, so free. Refused by §24.3 and now refused by
  the script.
- **Gating `--selftest` on total agreement**, which would have failed on every run for a
  documented, one-directional bias and taught the reader to ignore it.
- **Reporting the tight arm's rate as its concreteness.** It is a lower bound; the fixture's recall
  suggests the true figure is nearer 80%, and that estimate rests on nine labelled items and is
  offered as an estimate.
- **Leaving the kernel boundary as prose.** Both scorers state that nothing in `deliberation` may
  import them (§23.5: a Cell that learns it is scored on novelty learns to perform novelty); that
  claim now has an AST test, with the forbidden set derived from the scripts directory and a
  vacuity guard, because a guard over an empty set passes forever.

### Consequences

- **Phase 2 has its counterweight**, with a stated bias and a committed fixture. Report concreteness
  beside diversity or report neither.
- **A concreteness rate is a lower bound.** Two arms may be compared; an absolute level may not be
  quoted without `--selftest`'s recall beside it.
- **§13.4's other three flags are blocked on §31's `novelty_archive`**, which is a Phase 2 object.
  When it lands, this script is where they attach.
- **`scripts/genomes/` exists so an arm survives its session.** ADR-056's loose genome had to be
  rebuilt from three sentences quoted in its own ADR; the reconstruction is 474 characters of prose
  against the tight arm's 518, so length cannot carry the effect.
- **The kernel-versus-analysis boundary is now structural**, and the allowlist in
  `KERNEL_DRIVING_SCRIPTS` forces a new script to be a scorer unless someone deliberately says
  otherwise.

## ADR-059: §13.2's selector — four of its nine dimensions have no data, and saying so is the build

- **Status:** Accepted; new `selection.py`, no migration, golden expectations 28 -> 29
- **Spec ref:** §13.2, §13.1, §13.3, §8.5, §10.2, §10.3, §10.5, §11.2, §12.1, §23.4, §23.5, §25.2,
  §31; ADR-029, ADR-045, ADR-048, ADR-058
- **Context:** ADR-058 measured concreteness and PRIORITIES carried the consequence — "a selector
  tuned on proposal variety would favour exactly the Cells that have stopped saying anything" — with
  the selector itself unbuilt. §13.2 is the clause that says what one looks like:

  > Reject candidates below minimum thresholds on evidence quality, reproducibility, policy
  > compliance, and software-native advantage; then select from a Pareto frontier over structural
  > novelty, information gain, economic potential, experiment cost, and transfer robustness.
  > **Do not rely on a single weighted scalar.**

### The finding: five of the nine can be measured here, and four cannot

`DIMENSION_SENSE` transcribes all nine and forces each into a gate or a frontier axis
(`unclassified_dimensions()` fails otherwise — the `accounts.py` idiom). What came out:

| dimension | half | today |
|---|---|---|
| evidence quality | gate | **live** — §8.5's register, thresholded at `UNINFORMATIVE_BRIER` |
| policy compliance | gate | **live** — §18 quarantine + §23.4's escalating signals |
| reproducibility | gate | **unmeasurable** — §11.2's adoption record does not exist |
| software-native advantage | gate | **unmeasurable** — §13.3 judges an idea's *content* |
| information gain | frontier | **live** — entropy of the forecasts filed with the proposal |
| experiment cost | frontier | **live** — §13.1's `normalised_cost`, its first consumer |
| transfer robustness | frontier | **live** — §25.2's transfer degradation |
| structural novelty | frontier | **unmeasurable** — needs §31's `novelty_archive` |
| economic potential | frontier | **unmeasurable** — no proper scoring rule over a Cell's own upside |

**An unmeasurable dimension abstains; it never scores zero.** `structural_novelty = 0.0` is the
claim "this idea is not novel"; the truth is that nothing here can tell. §2.6's report and
ADR-042/043 settled that shape and this reuses it, including the split between `UNEVALUABLE` (this
candidate has no record yet — a new Cell) and `UNMEASURABLE` (no candidate could be scored). A
single "unknown" would hide which of the two a build can fix, the same reason §25.2 separates
`INSUFFICIENT_EVIDENCE` from `EVIDENCE_WITHHELD`.

### Why a Cell's own probability may drive selection and its own upside may not

`information_gain` is computed from forecasts the Cell registered itself. §8.5 is what makes that
safe: **Brier and log score are proper scoring rules**, so stating 0.5 when you believe 0.9 loses
points at resolution, and the register is hash-chained before the outcome is knowable. A Cell gaming
this axis pays for it on the evidence-quality gate. `economic_potential` has no such rule over it,
so §0.3 applies unchanged — "a Cell may *explain* a result; it may never *define* the canonical
result" — and the module declines rather than inventing a number.

**This is what §13.2's "no single weighted scalar" is protecting.** The dimensions are supposed to
hold each other honest, and they stop being able to the moment they are summed.

**One dimension has no such protection, and it is named rather than hidden.**
`experiment_cost`'s numerator is the Cell's own `estimated_cost_minor_units`, so understating a cost
looks cheap on the frontier. §13.1's denominator is safe — a human set the tranche — and the ledger
records what an experiment actually consumed, but nothing yet compares the two. Recorded in
FUTURE_BUILD_HOOKS rather than papered over.

### ADR-058's concreteness measure is *not* wired in, and that is the answer

PRIORITIES asked for "the selector that consumes it". It cannot be a kernel computation: concreteness
is a judgment about an idea's *content*, which is the same category as §13.3's software-native
advantage, and §13.2's structure puts that behind a human (§23) or an independent Auditor (§10.4).
The kernel is excluded by §23.5 and by `tests/test_analysis_boundary.py`, which this repo added one
slice ago precisely so a Cell cannot be scored on novelty inside the loop that produces novelty.
**So concreteness enters §13.2 as `software_native_advantage`'s missing judge, not as an axis** —
and the shape of the gap is now written down instead of guessed at.

### What it displaced

- **`promotion.allocatable_grants` as the candidate set.** It looked like the same list and is not:
  it answers a capital-pool question and filters to spend requests, while §13.1's formula is written
  about an *experiment's* cost. Selecting from it would have left the clause's own cost dimension
  measuring only the kind it was not named for. `CANDIDATE_KINDS` / `NON_CANDIDATE_SENSE` make every
  other kind carry a reason it is excluded.
- **Rejecting a Cell with no forecasting record.** `death._has_realised_record` names the trap from
  the other side: an unmeasured Cell is not inferior, it is unmeasured. A gate that rejected the
  unmeasured would reject every Cell the colony has just born — §9.4's founder problem manufactured
  by the selector.
- **Setting the evidence bar at "worse than average" rather than "worse than saying nothing".** A
  percentile is a tuning knob; `UNINFORMATIVE_BRIER` falls out of the scoring rule.
- **Gating on overdue unresolved forecasts.** `outcome.py` is explicit that resolution is the
  operator's job, so a withheld outcome is "a defect in the evidence, not a finding against the
  Cell". The Cell-attributable version already exists as §23.4's `selective_evidence` — filing *new*
  forecasts while its own sit open — and is checked under policy compliance.
- **Letting `understated_risk` reject.** `approval.py` excludes it from `_ESCALATING_SIGNALS`
  because it is derived from the kernel's own assessment; a selector gating on it would rebuild that
  circularity one layer up.
- **Importing `outcome` for two constants — and the existing guard caught it.**
  `test_no_kernel_path_acts_on_an_assessment` failed the moment `selection` imported `outcome`, and
  it was right to: a selector that can see a §25.2 verdict is one edit from acting on it. The fix
  says where the constants belong. `UNINFORMATIVE_BRIER` moved to `prediction.py`, beside the
  scoring rule that defines it (its comment in `outcome.py` already pointed there for the meaning),
  and the count threshold is `selection.MIN_RESOLVED_FOR_A_GATE` — its own number, because "enough
  evidence to call a funded promotion a success" and "enough to refuse a candidate a hearing" are
  different questions that happen to share a value.

### The golden section would have been born dead, so the scenario gained a step

Every grant this scenario made was consumed by the step that made it, so a correct selector replayed
against an empty list — **the exact shape ADR-045 found sitting in this file for four months**. Step
19f gives cell#4 a second spend request, approves it, and never allocates it: an approved grant
nobody has funded is what a §13.2 candidate *is*. The Cell was chosen because it holds a rung-7
promotion, so `experiment_cost` resolves to **0.4** (12 against a tranche of 30) instead of
abstaining — a section where every axis abstained would pass against a selector that had stopped
measuring anything.

**A second field came alive with it.** `assessments.forecasts_made_while_funded` moves 0 -> 2 and the
verdict does not change. That field has pinned nothing since it was added; §23.5's rule is that
forecasts registered after the money arrived are counted and kept *out* of the verdict, and this is
the first replay in which there are any to keep out.

### Consequences

- **Nothing acts on a frontier**, enforced structurally. Being off it is an estimate, and §10.5
  forbids "estimated negative EV alone" killing a Cell without a concurring Auditor; being on it is
  not an approval. `test_no_kernel_path_acts_on_a_frontier` is the successor to
  `test_no_kernel_path_acts_on_an_assessment`, and names `death.py`, `promotion.py` and
  `scheduler.py` individually.
- **The frontier never reaches a Cell** (§23.5): `context.py` and `deliberation.py` may not import
  `selection`. Two of the three measurable axes are the Cell's own numbers, and a Cell shown which
  axis placed it learns to move that axis.
- **`Candidate` and `Frontier` carry no `score`, `rank`, `weight` or `priority` field**, and
  `frontier_grant_ids` is a `frozenset`. §13.2 forbids the scalar; the surest way to keep one out is
  to give it nowhere to live, and an ordered list is a scalar arrived at by presentation.
- **§13.1's `normalised_cost` has a consumer.** FUTURE_BUILD_HOOKS asked, when ADR-048 shipped it
  inert, that §13.2 "check that this ratio is the dimension it wants rather than assuming it". It
  is — §13.2 lists "experiment cost" and §13.1 exists to make that quantity dimensionless.
- **What Phase 2 still needs before it can select for real:** the `novelty_archive` and
  `behavioural_descriptors` of §31 (which also unblock §13.4's other three flags, ADR-058), §11.2's
  adoption record, and an Auditor path for content judgments. Three of nine axes is a real frontier
  and an honest one; it is not yet quality-diversity.

## ADR-060: §31 lists two tables for the novelty archive, and §12.2 refuses both

- **Status:** Accepted; new `novelty.py`, **no migration**, golden expectations 29 -> 30
- **Spec ref:** §12, §12.1, §12.2, §12.3, §12.4, §13.2, §13.4, §16.1, §16.2, §16.3, §9.4, §10.2,
  §10.3, §2.5, §23.5, §31; ADR-033, ADR-043, ADR-044, ADR-058, ADR-059
- **Context:** ADR-059 shipped §13.2's selector with `structural_novelty` abstaining, and ADR-058
  scored one of §13.4's four flags, both for the same reason: **there was nothing to be novel
  against.** PRIORITIES named §31's `novelty_archive` and `behavioural_descriptors` as the next
  thing. This builds the archive.

### The decisive clause is one sentence, and it removes both tables

> **§12.2** Store full raw behavioural descriptors **separately**; the archive is a **derived
> view**, allowing later rebuilding with different dimensions and bins.

Read as an instruction to create a table, that sentence says "store descriptors". Read for what it
is *protecting*, it says the archive must not **be** the record, so that rebinning cannot destroy
the measurements underneath. In this kernel those measurements already live separately and in
better custody than a new table would give them: `cell_genomes` is content-addressed (§16.1) and
append-only, the ledger and the prediction register are hash-chained. Copying them into a
`behavioural_descriptors` table would create the second version §2.5 refuses, and §31 offers
"suggested entities" rather than a build order — the same reading already refused
`experiment_results` (ADR-043) and `resource_usage.experiment_id` (ADR-044). **This is the third and
fourth §31 entity that §2.5 has removed, and the slice ships no migration** (ADR-033's shape).

**What would justify a table is a descriptor nobody can recompute** — a human's or an Auditor's
judgment, which is not derivable by definition. ADR-059 identified exactly that gap and left it
unbuilt; when it lands it brings its own storage and this module reads it.

### One of §12.1's three dimensions is live, and the other two are blocked on one specific thing

| dimension | today |
|---|---|
| `novelty_distance` | **live** — structural, from the genome archive |
| `buyer_type` | unmeasurable — revenue records **who paid as free text** |
| `revenue_recurrence` | unmeasurable — needs the same key one step further on |

**The missing thing is an inbound counterparty key, and the colony already has the outbound one.**
`revenue.record_revenue` takes a `source` ("an invoice id, a customer reference, 'manual'"), so two
payments from one buyer are indistinguishable from one payment each from two. §21.2's
`external_action_registry` solved precisely this in the other direction with a **salted hash** of a
counterparty — equality without identity, as §16.3 requires. Naming that asymmetry is more useful
than either shrugging or guessing: counting payments *per Cell* instead would report a Cell with
three one-off customers as `repeat`, the undercount-versus-abstain trap ADR-044 named.

### The bins are §13.4's own language, not a threshold anyone picked

- **adjacent** — the nearest earlier genome differs in exactly **one** business field. That is
  §13.4's first flag ("only the industry label changed") stated as a distance.
- **moderate** — more than one field differs, but some earlier genome shares its `market`.
- **radical** — no earlier genome shares its `market`. §16.3 makes the market hypothesis the
  inheritable thing that keeps a lineage *that* lineage, so an untried market is the one claim to
  structural novelty this kernel can make without reading meaning.

**Radical is decided before adjacent**, and the order is load-bearing: a genome whose only changed
field *is* the market has a neighbour one step away and pursues a customer nobody has tried.
Checking the neighbour first would file a new market as a relabel, inverting §13.4 rather than
applying it. (The flag and the distance are then allowed to disagree about that same genome, because
they answer different questions — one asks what changed, the other how far it moved.)

**Zero is a real case and it is not a hole.** Two genomes can differ *only* outside the business
fields — a different `risk_class` or `allowed_tools` gives a new content hash and the same
hypothesis. That bins as `adjacent` with its own stated reason rather than earning a fourth bin
§12.1 does not have. If it did not, a Cell could reach a further niche by asking for permissions
instead of by having an idea, which is §23.5's shape exactly. `NOVELTY_FIELDS` /
`NON_NOVELTY_SENSE` force every §16.2 field to carry a reason it is in or out.

### This is a distance, not a merit, and it reads in one direction

A small distance is evidence of §13.4's first flag. A large one proves nothing: a genome whose
every field changed to nonsense scores `radical`, and catching *that* is §13.4's fourth flag, which
ADR-058 had to build outside the kernel because it needs a model call. §13.2's refusal of a weighted
scalar is what makes the axis safe to ship anyway — nothing is funded for being radical; a radical
candidate merely avoids being dominated by an otherwise-identical adjacent one.

**§13.4's third flag stays unbuildable here.** Deciding that two different strings describe one
mechanism is semantics, and §23.5 keeps model calls out of the kernel. One of four flags became
computable; the other two of the three ADR-058 deferred still need a judge.

### What it displaced

- **`market`/`revenue_model`/`acquisition_channel` as the axes**, which FUTURE_BUILD_HOOKS had
  called "the obvious axes for quality-diversity search". They are free text and §12.1 names
  *bins* — four, three and three of them. §12.4 explains why: high-dimensional archives stay nearly
  empty at realistic population sizes, and an axis with as many values as there are genomes is the
  limiting case of that.
- **An elite per niche**, which is what MAP-Elites classically keeps. Picking one needs either a
  scalar (§10.2 forbids) or a Pareto comparison between Cells — which §10.3 restricts to
  near-duplicates, a *finer* grouping than a niche, because comparing an Explorer with a Commercial
  on net contribution culls exactly the Cells whose value is exploratory. §12.3's Thompson-sampling
  posteriors are the spec's own answer for ranking inside a niche and a beta-binomial over four
  Cells is noise. `death.py` already answers domination where §10.3 permits the question.
- **A catch-all niche for genomes with no measured dimension.** The founder has nothing earlier to
  be novel against, and a niche labelled "unknown" would go on reporting itself occupied long after
  the colony stopped measuring — §12.4's worry made concrete.
- **Calling the founder `radical`.** It is the most tempting default in the module and it is a claim
  about an archive with no other members.

### Consequences

- **§13.2's frontier has three measured axes of five**, up from two. `structural_novelty` is an
  ordinal (adjacent 0 < moderate 1 < radical 2) whose gaps carry no meaning, so domination compares
  it for order only.
- **§9.4's niche-specific carrying capacity is now computable.** `Niche.living_cells` counts Cells
  rather than genomes, because two Cells sharing a strategy are two competitors for one capacity.
  Nothing enforces a per-niche cap; §9.4's other founder-effect measures remain unbuilt.
- **The archive must not reach a Cell** (§23.5), enforced against `context.py` and `deliberation.py`.
  Today the descriptor derives from genome content an operator writes, so there is nothing for a
  Cell to move. **§14's automated mutation is what changes that**, and the tell will be lineages
  drifting across many fields at once for no economic reason.
- **The golden replay cannot catch one regression this module could have.** Both niches happen to
  hold as many living Cells as genomes, so counting genomes instead of Cells would reproduce the
  section exactly. A named unit test defends it instead — found by teeth-checking, which reported
  that mutation as MISSED until the fixture was changed to make the two counts differ.

---

## ADR-061: the inbound counterparty key unblocked one dimension, and disproved the claim about the other

- **Status:** Accepted; new `counterparty.py`, migration 0028, golden expectations 30 -> 31
- **Spec ref:** §12.1, §12.2, §16.3, §21.2, §3.4, §3.6, §2.5, §2.6, §23.5, §0.3; ADR-036, ADR-044,
  ADR-047, ADR-059, ADR-060
- **Context:** ADR-060 shipped a **one-dimensional** archive. Its stated blocker was specific:
  `revenue.record_revenue` recorded who paid as free-text `source`, so two payments from one buyer
  were indistinguishable from one payment each from two. PRIORITIES, `novelty._buyer_type`,
  `novelty._revenue_recurrence` and BUILD_RECORD all said the same thing — build an inbound
  counterparty key and **both** of §12.1's remaining dimensions become measurable.

### The key was right. The claim about what it unblocks was half wrong

A salted digest gives **equality without identity**. That is exactly what `revenue_recurrence`
needs — one-off / repeat is a question about *the same buyer paying again* — and it is exactly what
`buyer_type` does not need. human consumer / small business / enterprise / machine is a claim about
who the buyer **is**, and §16.3 puts customer identity permanently outside this colony. There is
nothing to classify from, with the key or without it.

So `buyer_type` was never blocked on this key, and building the key proved it rather than fixing it.
The honest route left is a **declaration by someone who can see the buyer**, which is ADR-059's
finding again: a judgment the kernel cannot compute (§23.5) enters with a judge attached, not as a
derived axis. Deriving it from the channel a party was contacted on would be a guess wearing a
measurement's clothes — the shape ADR-044 named.

**Four tracking files carried the wrong version of this claim**, each correct about the direction
and wrong about the scope. That is this repo's documented drift shape, and the correction is now
written into `novelty._buyer_type` and the module docstring rather than only into an ADR.

### Where the key lives, and why not the three easier places

| candidate | why not |
|---|---|
| `ledger_transactions.metadata_json` | **Not in the hash preimage.** `_compute_hash` covers the transaction's identifying fields and its canonicalised entries — no metadata on either side. A counterparty there is silently editable, and this field decides whether a Cell occupies §12.1's `repeat` niche, which is a fitness-bearing claim. |
| a `revenue_counterparties` side table | Droppable and editable independently of the payment it describes, and outside §3.4's chain. Who paid is a fact *about the payment*, and the payment is a ledger row. |
| reuse `external_action_registry` | §21.2 records actions the colony **took**. A payment received is not an action taken, and filing one there would make "contacted" and "paid" the same row shape. |

It goes on `ledger_transactions` as a column and **into the hash preimage**, so editing who paid
invalidates every transaction that followed (§3.6: never edit history, post an adjustment).

### The preimage is extended by omission, which is the whole risk of this slice

Adding `"counterparty_hash": None` to every preimage would change the hash of **every transaction
ever written**, so `verify_chain` would report the entire ledger of every existing colony as
tampered with — the exact alarm the chain exists to raise, for the exact wrong reason. The key is
therefore included **only when present**, unlike `event_id`, which is included as null. The
inconsistency is deliberate and is the one thing in this slice that had to be got right:

- `test_a_transaction_without_a_counterparty_hashes_as_it_always_did` recomputes the pre-0028
  formula by hand and compares it to a stored hash.
- `test_clearing_who_paid_breaks_the_chain` covers the risk omission creates — that *erasing* a
  counterparty might reproduce the old hash. It does not; the stored hash was computed with the key
  present.
- The golden run passed **unchanged** on the first full run after the ledger change, before the
  scenario recorded any counterparty. That was the real evidence.

### The CHECK constraint is the §16.3 guarantee, not input validation

`counterparty_hash` is declared `CHECK (… length = 64 AND NOT GLOB '*[^0-9a-f]*')`, so the column
**cannot physically hold** an email address, an account handle or a legal name. ADR-047's lesson
applied a second time: before building a seam to enforce something, ask whether the schema can make
it unrepresentable. A seam binds callers that know about it; a constraint binds callers that do not
exist yet. Teeth-checking confirmed the shape — mutating `revenue` to store the raw party is stopped
by the constraint at the INSERT, not by a test noticing the leak afterwards.

`counterparty.is_hash` states the same rule in Python, and `test_the_schema_check_and_is_hash_are_one_rule`
builds a probe table **from the migration's own text** so the two spellings cannot drift apart.

### The cadence abstains in one direction only

`repeat` survives an incomplete record and `one_off` does not, because more data can add a repeat
and can never remove one:

- a digest seen twice is `repeat` **even if other payments are unkeyed**;
- all payments keyed and all distinct is `one_off`;
- all distinct *but some payments unkeyed* **abstains** — an unkeyed payment could be the second one
  from a buyer already counted, and reporting `one_off` there is ADR-044's undercount trap.

Both halves are teeth-checked, in both directions: an implementation that read `one_off` from a
partial record fails one named test, and an implementation that abstained whenever *any* payment
lacked a key — safe, and throwing away a conclusion it had already earned — fails another.

**Aggregated across the genome's Cells, not per Cell.** The archive bins genomes, and one buyer
coming back to the same business idea is a repeat customer of that idea whichever sibling took the
second payment. ADR-060's named trap ran the other way — counting *payments* per Cell would call
three one-off customers `repeat` — and keying on the buyer is what closes it.

### `subscription` is a bin nothing can produce, and that is written down

Telling a subscription from a loyal buyer means telling a **contract** from a payment pattern, and
that needs the service-obligation record §16.3 calls liability-linked. This colony has none. A
subscription therefore lands in `repeat` and says so in its reason. `UNREACHABLE_BINS` records the
refusal, because a bin that never appears looks identical to a bin that never happens and only one
of those is a statement about the colony.

### What it displaced

- **A `buyer_type` declared at `record_revenue`.** Admissible in principle — no Cell can record
  revenue, so §23.5's "a field a Cell can fill is a field it will optimise" does not bite, and the
  operator declaring a buyer type is no stranger than the operator declaring the amount. Rejected
  for this slice because it would smuggle a **judgment** into a slice about a **key**, and because
  the amount is checkable against an invoice (§3.7) while the type is checkable against nothing.
  It belongs with ADR-059's missing judge, arriving with a declarer recorded beside it.
- **A second payment counted per Cell rather than per buyer** — the obvious implementation, and the
  one ADR-060 explicitly warned about.
- **Leaving `counterparty_hash` in `channel_registry`.** `revenue` sits at the ledger end of the
  layering and `channel_registry` up where `context` imports it, so the primitive was extracted to
  `counterparty.py`, which depends on nothing but the salt row. Both directions now share one salt
  deliberately: a party the colony contacted who then pays produces the same digest, so §21.2's
  contact history and the money join up without either side holding an identity. Two salts would
  have looked identical to every test that exercised one direction.
- **Pinning the golden run on `one_off`.** A single payment reports `one_off` whether or not the
  salt, the normalisation, or the write works at all. The replay records **two payments from the
  same buyer, spelled differently**, because `repeat` is the only bin whose value depends on two
  digests being equal. This is ADR-060's own lesson: its niche-occupancy bug was uncatchable in the
  replay because the fixture could not distinguish the two behaviours.

---

## ADR-062: §12.1's third dimension is declared, and the mechanism for declaring it already existed

- **Status:** Accepted; migration 0029, `counterparty.attest_buyer_type`, golden expectations 31 -> 32
- **Spec ref:** §12.1, §12.2, §0.3, §16.3, §3.6, §23.5, §10.4, §13.3, §13.4, §20.3; ADR-032,
  ADR-041, ADR-059, ADR-060, ADR-061
- **Context:** ADR-061 established that no query can produce `buyer_type` — a salted digest gives
  equality, never identity, and §16.3 keeps customer identity permanently outside the colony. What
  was left was a declaration. PRIORITIES recorded the next step as "a declared `buyer_type`, with its
  declarer recorded... **one build, three callers**; do not build a fourth bespoke declaration
  mechanism", naming ADR-059's `software_native_advantage` and ADR-060's §13.4 third flag as the
  other two.

### That entry was wrong twice, and both errors were worth finding before building

**First: the mechanism already existed.** ADR-041 built `rights_attestations` — a person establishes
a fact the colony cannot derive, recorded as subject, claim, basis, who, when; append-only; latest
wins; withdrawal is a row rather than a flag; unreachable from any Cell, enforced by an AST walk over
every module. Every one of those decisions is right for a buyer type, for the same reasons. So this
slice **copies an established shape rather than inventing a judgment subsystem**, and the ADR that
matters most here is one that was already written.

**Second: the three callers do not want the same mechanism, and the split is principled.**

| caller | what is being judged | who can judge it |
|---|---|---|
| `buyer_type` | an **external fact** — who actually paid | an operator holding the invoice |
| `software_native_advantage` (§13.3) | the **colony's own text** — does this idea rely on machine-native levers | a scored Auditor (§10.4) |
| §13.4's third flag | the **colony's own text** — do two descriptions name one mechanism | a scored Auditor (§10.4) |

The first is an observation somebody makes about the world. The other two are readings of a Cell's
own prose, which is precisely what §23.5 keeps out of the kernel and what ADR-032's Auditor exists
for — with a probability and a registered prediction, because §10.4 requires wrongful flags to be
penalised and prose cannot be penalised. **An operator does not need a Brier score; an Auditor does.**
Forcing all three through one generic `dimension`/`value` judgments table would have produced a
mechanism that scores nobody and constrains nothing.

### What the generic table would have cost

A `judgments(subject_kind, subject, dimension, value, ...)` table cannot state that `buyer_type` is
one of exactly four values. Migration 0029's CHECK can, and does — so §12.1's bins are enforced by
the schema rather than by whoever writes the next caller. That is ADR-047's lesson for the third
time: a seam binds callers that know about it, a constraint binds callers that do not exist yet.
`test_the_buyer_type_bins_are_one_rule` builds a probe table from the migration's own text so the
Python list and the SQL list cannot drift apart.

### The subject is the counterparty digest

Not the payment (which would re-ask the same question per invoice) and not the genome (which would
make it a claim about an *idea* rather than an observation of who actually paid — and a MAP-Elites
descriptor describes behaviour, not intent). The operator names the party; the kernel hashes it and
stores only the digest, so the colony learns that some buyer is an enterprise and still cannot say
who any buyer is. `test_an_attestation_does_not_store_the_party` re-runs ADR-061's whole-database
scan, because a new operator-facing entry point taking a party by name is exactly where that
guarantee would be lost.

### Attesting a party who never paid is refused, and that is the foreign key

A counterparty is a value appearing on payments, not a row, so there is nothing to reference. Without
the check, a mistyped party produces a **silent no-op**: a valid attestation, a success message, and
no descriptor moves. §12.1's dimension is about who *paid*, so a party who has not is out of scope by
definition rather than merely unverified.

### The abstention rules, and the ordering that is load-bearing

`buyer_type` abstains unless every payment is keyed, every buyer attested, and every attestation
names one segment. Two rules deserve stating:

- **Mixed is checked before incomplete.** Two segments among the attested buyers is monotone — no
  further attestation can unmix them — so that abstention is *permanent* and says so. Every other
  abstention is a gap somebody can close. Checking incompleteness first would tell an operator to go
  and attest the remaining buyers in the one case where doing so cannot help.
- **A withdrawal is not the same as never having been asked.** `current_buyer_types` keeps a
  withdrawn party present with `None`, because "somebody looked and declined to say" and "nobody has
  looked" are different facts, and they abstain with different reasons.

§12.1 has no bin for a genome selling into two segments and none is invented. A dominant-segment rule
needs a threshold nobody has chosen — the same refusal `_novelty_distance` makes, where the only
number in the module is §13.4's own "exactly one".

### What it displaced

- **A generic judgments table serving three callers.** Refused above: it cannot state §12.1's bins,
  and two of its three callers need ADR-032's scored Auditor rather than a human declaration.
- **Deriving `buyer_type` from the channel a party was contacted on.** Available — §21.2's registry
  shares the salt, so the join exists — and it is a guess wearing a measurement's clothes.
  `test_no_cell_reachable_module_declares_a_buyer_type` does not prevent this one; the abstention
  reasons and this paragraph are what stand against it.
- **A dominant-segment rule.** Needs a threshold; parked in FUTURE_BUILD_HOOKS rather than invented.
- **A `revoked` flag instead of a withdrawal row.** ADR-041's argument, unchanged: a flag leaves an
  absence where the reason should be.
- **Pinning the golden run on a single attestation.** One attestation reports the same bin whether
  the read takes the latest row or the earliest, so the replay attests twice and supersedes. This is
  the third slice running where the replay was deliberately made non-degenerate; ADR-060's missed
  niche-occupancy bug is why.

---

## ADR-063: rung 8 is a scale step, not an autonomy step — and the claim that it was one had propagated to four files

- **Status:** Accepted; migration 0030, `autopromotion.py`, `promotion.PromotionEvidence`,
  `scheduler.PromotionSweeper`, golden expectations 32 -> 33
- **Spec ref:** §25.1, §25.2, §25.3, §0.4, §23.1, §23.4, §23.6, §27.1, §10.3, §10.5, §12.3, §2.6,
  §9.3, §29; ADR-026, ADR-027, ADR-029, ADR-040, ADR-041, ADR-047
- **Context:** `promotion.allocate` only ever issued rung 7, which blocked §12.3's beta-binomial
  **stage-conversion** posteriors — the spec's own answer for ranking inside a MAP-Elites niche, and
  the largest remaining gap between Phase 2's selector and quality-diversity. A stage conversion
  needs a stage to convert *to*.

### The claim that had to be checked first

Four places said rung 8 means removing a human: `promotion.py`, `outcome.py`, migration 0016's
comment, and — worst — the docstring of the structural test that enforced the guarantee
(`test_no_kernel_path_acts_on_an_assessment`). §25.1's ladder actually reads:

```
7. Tiny capped live experiment
8. Expanded pilot
9. Bounded autonomy
```

The 7 -> 8 delta is **scale**; the word *autonomy* appears only at rung 9, and a *pilot* is
supervised by definition. Who acts without a human is §27.1's `autonomy:` block and §0.4's "tool by
tool, phase by phase" — never a ladder rung. ADR-026 requires two independent confirmations for real
money, and a human-removing rung 8 would have collapsed them into one.

**The test contradicted its own docstring three lines below it**, and the forbidden list was the half
that was right: `("scheduler.py", "a promotion that fires on a timer is rung 9, not rung 8")`. This
is the claim-drift shape the repo keeps producing — right about direction, wrong about every
specific, propagated unchallenged because each copy cited the others.

### So the slice ships two things on two axes, and keeps them apart

| axis | column | what moves it |
|---|---|---|
| how far up §25.1 | `rung` | a predecessor at the rung below, whose §25.2 evidence supports the expansion |
| who decided | `decided_automatically` | §27.1's `auto_promotion` flag |

`ISSUABLE_RUNGS` is `(7, 8)` and deliberately excludes 9: bounded autonomy is not a bigger cheque,
and writing it as a rung would re-conflate exactly what this ADR separates.

### The constraint went in the schema, not the module

ADR-047's lesson applied directly: **a constraint has no layer.** A check in `promotion.py` binds
callers that go through `promotion.py`, and this repo has escape hatches that do not
(`start-experiment --rung 7` is one). Migration 0030's trigger makes three things unrepresentable
rather than merely refused — a rung above 7 with no predecessor, a predecessor that is not the rung
immediately below, and a predecessor belonging to **another Cell** (§29's reciprocal evidence
farming, expressed as a foreign key pointing somewhere plausible). A unique partial index makes one
success expandable exactly once, which is §23.4's action-splitting attack run upward.

**Teeth-checking found the index untested.** `test_one_success_supports_only_one_expansion` passed
with the index dropped, because the Python query declines to *find* an already-expanded predecessor.
That is a good guard and not a guarantee, so it now has a second test that inserts an otherwise
fully valid row — its own real grant, request and proposal — so nothing but the index can refuse it.
With the index dropped that test reports `DID NOT RAISE`. Eleven of twelve mutations were caught
first time; this was the twelfth, and it was a test passing for the wrong reason.

### The seam, and why its signature is the safety property

`outcome.py` computes §25.2's verdict and **imports `promotion.py`**, so the gate could not be an
import. `promotion.PromotionEvidence` is the inversion — the same shape as
`sweeper.ExternalOperationChecker` / `gateway.GatewayOperationChecker`. Two deliberate narrowings:

- It takes a **`promotion_id`, never a `cell_id`**, so it cannot be asked the open question "how is
  this Cell doing?", only the closed "did *this* predecessor work?". That is §9.3's move applied to
  evidence: a signature that cannot see a general record cannot promote on a general impression.
- What crosses is `EvidenceReading` (four fields), not `Assessment` (twenty). A gate handed the full
  §25.2 list is one a later edit can re-point at revenue — and §10.3 ("Explorers need no immediate
  revenue") makes that the single dimension most likely to look reasonable and select exactly the
  wrong Cells.

The scheduler needed the same treatment for the opposite reason: `promotion` imports `scheduler`, so
an engine needing both sits strictly above it. `tick()` takes a `PromotionSweeper`; the *caller*
supplies `autopromotion.EvidencePromoter`. The authority to allocate therefore lives with whoever
wired the tick, not inside the timer.

### The unattended engine invents no new guard

`autopromotion.py` composes refusals that already existed: §27.1's `auto_promotion` flag (ships
false), §27.1's `real_spending` (still separately required for USD_REAL, so ADR-026's two
confirmations stay two), §23.1's own `batchable` predicate — which already interlocks with §23.4 by
folding in cumulative lineage exposure and disqualifying on any gaming signal — the §25.2 evidence
gate, and the `promotion_pool` ceiling no Cell can raise. An engine that runs unattended is the worst
possible place to debut a hand-rolled guard.

Its placement in the tick is the **mirror of ADR-040's expiry sweep**: that one runs *before*
`_guard` because it only ever removes permission; this one grants it, so it sits behind every guard
the halt path controls. It runs *after* the wakes so a proposal made this tick can be funded in it.

**It cannot kill.** §10.5 forbids culling on estimated negative EV without strong evidence *and* a
concurring Auditor, and no Auditor Cell exists. A verdict has two poles and the engine is argued for
only one, so `test_the_unattended_engine_cannot_kill` closes `death`, `displacement` and `lineage`
structurally at the one module that acts on a verdict at all.

### What it displaced

- **Rung 8 as a delegated approval policy** (the shipped reading, §23.6's own hook). Rejected: it
  contradicts §25.1's wording, and it would have made the ladder rung and the autonomy flag the same
  number — after which no reader could tell a bigger pilot from a smaller human.
- **A generic `assessments` table.** Rejected on §2.5's standing grounds, and `outcome.py` had
  already written the condition for adding one: "a table becomes worth adding when a *decision*
  consumes an assessment". A decision now does — so the verdict is snapshotted **onto the promotion
  that consumed it**, leaving every unconsumed assessment derived. A table would have invited storing
  all of them and then disagreeing with the canonical derivation.
- **A `cell_id`-keyed evidence lookup**, which reads more naturally and is the whole hazard.
- **Auto-promotion implying real spending.** Rejected: one flag, one capability (migration 0022).
- **Enforcing the ladder in `promotion.py` alone.** Displaced by the trigger, per ADR-047.
- **A substring test for "promotion" in `scheduler.py`.** It tripped on the seam's own name, and was
  loose where it mattered (`from . import promotion as p` passed it) and tight where it did not.
  Replaced with an AST import check.

---

## ADR-064: §12.3's `P(next stage)` counts a realised conversion, never §25.2's evidence verdict

- **Status:** Accepted; `posteriors.py`, `mitosis posteriors`, golden expectations 33 -> 34
- **Spec ref:** §12.3, §12.1, §12.2, §10.5, §2.5, §25.1, §25.2; ADR-063

- **Context:** ADR-063 made a rung-7 -> rung-8 conversion representable
  (`promotions.supersedes_promotion_id`), which is what FUTURE_BUILD_HOOKS had named as the one
  missing precondition for §12.3's beta-binomial `P(next stage)`: "every one of them needs
  stage-*conversion* events — Cells moving between §25.1 rungs — and `promotion.allocate` only ever
  issued rung 7, so the colony has produced no conversions at all." With rung 8 issuable, this slice
  builds exactly the one thing §12.3 names as an acceptable first implementation: "First implementation
  may use beta-binomial stage-conversion posteriors" — leaving expected net value, expected time to
  conversion, probability of reproducibility and probability of large loss to FUTURE_BUILD_HOOKS.

### The decision that had to be made before any arithmetic: what counts as a trial

`outcome.py` already computes a verdict for a rung-7 promotion — `SUPPORTS_PROMOTION` — that answers
"does this promotion's own evidence currently support an expansion". It is *available*, it is *already
a Bernoulli-shaped signal*, and it is the wrong thing to count. §10.5's whole discipline is deciding on
**realised** facts rather than estimates; generalised from one Cell to a niche of them, a niche's
stage-conversion rate must be about Cells that actually **climbed** the ladder, not about promotions
the kernel currently believes *could* climb it. A Cell can earn `SUPPORTS_PROMOTION` and never be
allocated rung 8 — an operator can simply not act, or the pool can be empty, or nobody has looked —
and none of those is evidence about the niche's conversion rate. `test_supporting_evidence_without_
an_actual_conversion_does_not_count` pins the case directly: an earned rung-7 promotion, confirmed via
`outcome.assess` to read `SUPPORTS_PROMOTION`, with the posterior still reporting zero conversions
because nothing allocated rung 8 against it.

So the trial is a raw SQL join over `promotions`, keyed on `supersedes_promotion_id` — not a call into
`outcome.py` at all. That also keeps the same layering `promotion.py` already enforces on `outcome`:
`outcome` imports `promotion`, so a call the other way is a back-edge, and this module avoids the
question by depending on neither reading the other's judgment.

### The niche is `novelty.archive`'s coordinate, not the Cell

§12.3 asks for a posterior "within each niche", and a niche is already defined — §12.1's
buyer_type/revenue_recurrence/novelty_distance coordinate over a **genome**, not a Cell
(`novelty.archive`, ADR-060). A rung-7 promotion is attributed to the niche of the Cell's genome at
query time, the same posture `Archive.living_cells` already takes. Genomes that abstain on every §12.1
dimension have no niche; their promotions are not dropped, they are counted separately
(`unbinned_trials`/`unbinned_conversions`), matching `Archive.unbinned_genome_hashes`'s own posture of
naming an absence rather than hiding it.

### An empty niche gets Beta(1, 1), not an abstention

Every other dimension this codebase reports with no data abstains — `economic_potential`,
`reproducibility`, an unattested `buyer_type` — because each of those has no formula to fall back on
without evidence. A beta-binomial posterior is different: Beta(1, 1) *is* the answer at zero trials,
and it is the one §12.3 actually asked for, because Thompson sampling needs every niche, including
unfunded ones, to have a distribution it can be drawn from. Reporting `UNEVALUABLE` here would be the
one dimension in this codebase where withholding is the less honest choice, not the safer one.

### No table, and §12.3's own future-proofing clause answered for free

"schemas must allow hierarchical/non-stationary models later" is §12.3's explicit requirement on
whatever ships first. `posteriors.py` owns no table — derived on every read, the same posture
`novelty.py` and `selection.py` already take toward §2.5 and §12.2 — so a richer posterior later is a
different function body over the same `promotions` rows, never a migration. The requirement is
satisfied by the module having nothing to migrate.

### Guarded the same way `selection.py`'s frontier is

A per-niche conversion rate is exactly the "estimated negative EV" shape §10.5 forbids acting on
without an independent Auditor concurring, generalised from one Cell to a niche of them.
`test_no_kernel_path_acts_on_a_posterior` closes `death.py`, `promotion.py`, `displacement.py` and
`scheduler.py` structurally, mirroring `test_no_kernel_path_acts_on_a_frontier`; `test_the_posterior_
never_reaches_a_cell` closes `context.py` and `deliberation.py` for the same §23.5 reason `selection.py`
is closed to them. Teeth-checked: an import from `death.py` (no import cycle, since `posteriors` never
imports `death`) is caught by the AST guard; the same mutation into `promotion.py` fails at import time
with a circular-import error before the guard even runs, because `posteriors` already imports
`promotion` for its rung constants — a stronger guarantee than the test, not a gap in it.

### What it displaced

- **Reading `outcome.Verdict.SUPPORTS_PROMOTION` as the Bernoulli trial.** The obvious signal, already
  computed, already binary — and the one §10.5 forbids, per the section above.
- **A `stage_conversion_posteriors` table.** Rejected on the same §2.5/§12.2 grounds `novelty.py` and
  `selection.py` already settled: nothing here is a fact a decision has consumed yet.
- **Reporting an empty niche as unevaluable.** The one dimension in this codebase where that would be
  the *less* honest choice — see above.
- **A credible interval alongside the posterior mean.** §12.3 asks for a posterior, not a confidence
  statement about it; a beta inverse-CDF is machinery this module does not need to ship the first
  implementation and is logged in FUTURE_BUILD_HOOKS rather than built speculatively.

---

## ADR-065: §13.3/§13.4's Auditor path judges a genome directly — never through §25.2's verdict, and never through a second table per kind

- **Status:** Accepted; `content_audit.py`, migration 0031, `audit-genome`/`audit-genome-pair`/
  `content-audit-record`, golden expectations 34 -> 35
- **Spec ref:** §13.3, §13.4, §10.4, §0.3, §29.10, §12.1, §12.2, §23.5, §10.5; ADR-032, ADR-058,
  ADR-062

- **Context:** ADR-062 built §12.1's third dimension (`buyer_type`, declared by an operator) and drew
  a line on purpose: two other judgments — §13.3's program-native advantage and §13.4's "the same
  mechanism is renamed" — are readings of a Cell's own prose, not external facts, and need "a
  probability and a registered prediction (ADR-032), not an operator's word". `auditor.py` already
  built every piece of machinery §10.4 demands for exactly this; its one gap was the subject —
  `audits` is keyed to `approval_requests`, and these two judgments are about a **genome** and a
  **genome pair**, neither of which is owned by any one request.

### One table, a `kind` column — not two tables, and not a widened `audits`

Three shapes were available and two were refused:

- **Widening `audits` to a nullable `request_id`/`proposal_id`** would have let a genome audit and a
  request audit share one table, but `audits`' own CHECK constraints, its `subject_cell_id`
  requirement, and `approval.payload`'s reader all assume exactly one request per row. Loosening all
  of that to admit a second subject shape is the "second answer living in the first table's clothes"
  trap this repo keeps naming.
- **Two tables**, one per `kind`, mirroring `rights_attestations`/`buyer_attestations`. Rejected here
  specifically, even though that precedent is real: those two are genuinely different *acts* by
  different declarers about different objects (a source domain; a buyer segment). `software_native_
  advantage` and `renamed_mechanism` are the *same act* — an Auditor Cell scoring a probability about
  a Cell's own prose — with a different subject shape. Splitting them would duplicate every column
  except the two that actually vary.
- **One table, `kind` discriminated, `compared_genome_hash` nullable** — the shape shipped, matching
  `promotions.rung`'s own precedent for keeping two variants of one mechanism together. The CHECK
  constraint makes the pairing itself unrepresentable rather than merely validated in Python
  (ADR-047): `software_native_advantage` forbids a second genome, `renamed_mechanism` requires one
  distinct from the first.

### `concern`/`no_concern` transfers unchanged, and so does the coherence rule

Both kinds are framed as "genuinely holds up" — genuinely program-native, genuinely a distinct
mechanism — so migration 0018's verdict vocabulary and its coherence rule (`concern` implies a
probability below one half that the genuine-claim is true) apply without modification. No new
enum, no new direction to get backwards. `ContentAuditReply` is a fresh Pydantic model rather than a
reuse of `auditor.AuditReply` — same shape, deliberately not imported, matching the "copy the shape,
not the code" posture ADR-041/ADR-062 already established for `rights_attestations`/
`buyer_attestations`.

### Independence, generalised from one Cell to a set of them

`auditor.py` checks the auditor is not the subject Cell and shares no lineage with it. A genome has no
single subject Cell — content-addressed, it may be carried by zero, one, or many, dead or alive,
across any number of lineages. The generalisation checked here: the auditor's own current genome must
not be either hash under review (an Auditor cannot judge its own business hypothesis), and the
auditor must share no lineage founder with *any* Cell that has ever carried either genome. **Teeth-
checking found the first check is strictly subsumed by the second** — a Cell whose own genome matches
the one under review always appears in the lineage query's own result set, trivially sharing a founder
with itself — so removing the dedicated self-check does not open a gap, it only degrades the error
message from "you carry this genome" to the more generic "you share lineage with a carrier". Both
checks ship: the first for diagnostic clarity in the common case, the second as the actual guarantee.

### What it deliberately does not do

- **Nothing consumes a content audit yet.** `selection.py`'s `software_native_advantage` gate still
  reports `UNMEASURABLE` unconditionally. This module makes the dimension *measurable*; wiring the
  gate to read a *resolved* audit is a deliberate next step — an *unresolved* one would be exactly the
  "estimated negative EV" shape §10.5 keeps out of an automatic decision, and `test_nothing_yet_
  consumes_a_content_audit` closes every kernel module against importing this one until that wiring is
  argued.
- **No merged precision record with `auditor.Precision`.** §10.4's fitness signal for one Auditor Cell
  is currently split across two calls (`mitosis auditor-record`, `mitosis content-audit-record`)
  rather than one. Logged as a future merge, not built speculatively — the two mechanisms are young
  enough that inspecting them separately is more useful than a premature combination.
- **The golden scenario stays unexercised.** The fixture's only two Auditor-eligible Cells share one
  lineage, and this module's own independence check refuses exactly that pairing — no other scenario
  Cell is both Auditor-typed and holds a genome with real §16.2 content. Manufacturing a valid pairing
  means a sixth Cell, which moves population counts and every book's balance along with it. Logged in
  FUTURE_BUILD_HOOKS as its own reviewed diff rather than folded into this one.

### What it displaced

- **Reading §25.2's evidence verdict as a stand-in.** Not applicable here the way it was for §12.3
  (ADR-064) — there is no analogous "verdict" to misread, but the same discipline shaped the design:
  the claim is a realised, kernel-composed statement an operator later resolves from observation, not
  something read off an existing derived judgment.
- **A `subject_cell_id` column**, mirroring `audits`. Rejected because a genome has no single subject
  Cell; the independence check queries `cells` directly instead of storing a denormalised pointer that
  would be wrong the moment a second Cell adopts the same genome.
- **Auto-selecting the comparison genome for `renamed_mechanism`** from `novelty.archive`'s nearest-
  neighbour logic. Rejected: which pair is worth asking about is an operator's judgment call, and the
  kernel inventing a "most suspicious pair" heuristic nobody asked for is exactly the unrequested
  policy this repo's slices keep refusing to add.

---

## ADR-066: `selection.py`'s `software_native_advantage` gate reads a resolved content audit, and rejects on any single one that resolved false

- **Status:** Accepted; `selection._software_native_advantage`, 3 new tests, golden run unchanged
  (34 -> 35 stays 35 — no fixture Cell has ever had a content audit)
- **Spec ref:** §13.2, §13.3, §13.4, §10.5, §0.3, §23.5; ADR-065

- **Context:** ADR-065 built `content_audit.py`, giving §13.3/§13.4 a live Auditor judge, and left
  `selection.py`'s `software_native_advantage` gate reporting `UNMEASURABLE` unconditionally on
  purpose — `test_nothing_yet_consumes_a_content_audit` closed every kernel module against importing
  `content_audit` until the wiring was argued rather than done as a drive-by. This is that argument.

### Reading only a resolved prediction, never the Auditor's raw probability

`content_audit.py`'s own docstring names the reason this was deferred rather than built in the same
slice: an audit's `probability` is registered *before* the outcome is known, so reading it into an
automatic gate would be gating a candidate on an **estimate** — exactly the "estimated negative EV"
shape §10.5 forbids acting on without strong evidence and a concurring Auditor. The gate instead reads
`prediction.get(conn, audit.prediction_id).outcome` — a value that exists only after the register has
resolved the claim against what was actually observed, the identical discipline `_evidence_quality`
already applies to a Cell's own forecast record.

`UNEVALUABLE` (an audit exists but has not resolved) and `UNMEASURABLE` (no audit exists at all)
stay the two distinct absences `GateOutcome`'s docstring already names, mirroring `_evidence_quality`'s
"a Cell with no resolved forecasts is `UNEVALUABLE`, never rejected" — an audited-but-not-yet-resolved
genome is not inferior, it is unmeasured.

### Any single resolved audit that resolves false rejects — concurrence is not required here

§10.5's stronger bar — "estimated negative EV alone must not kill a Cell... unless... an independent
Auditor or evaluator concurs" — is written for *death*. This gate does not kill anything: a candidate
rejected this funding round can be re-proposed once the concern is addressed, and migration 0031's
partial unique index already permits more than one Auditor to record an opinion about the same genome.
Requiring every Auditor who has ever judged a genome to agree would mean one Auditor's vindicated
"ordinary freelancing" flag could be outvoted by others who never looked closely — the same failure
mode `_policy_compliance` already refuses by rejecting on a single escalating §23.4 signal rather than
requiring a quorum of them. So the rule here is symmetric with that gate: any one resolved, vindicated
concern rejects; the register having scored the Auditor who raised it (via `content_audit.precision`)
is the check on Auditors who flag carelessly, not a second gate reading their track record.

### What it displaced

- **A quorum or majority-vote rule across every resolved audit for a genome.** Considered and
  rejected above — no spec clause asks for consensus at the gate, only at the kill path, and a quorum
  requirement would need a threshold this module has no principled way to pick.
- **Reading `content_audit.precision`'s flag-precision figure** as a continuous input instead of a
  binary resolved/unresolved read. Rejected for the same reason `economic_potential` declines a
  self-reported upside: there is no proper scoring rule over an aggregate precision figure the way
  there is over a single resolved binary claim, and folding it in would smuggle a scalar into a gate
  §13.2 built specifically to avoid one.
- **Moving `software_native_advantage` header text out of the "cannot be measured" bullet list
  entirely.** Kept as a parenthetical (matching `structural_novelty`'s ADR-060 precedent) rather than
  deleted, because the dimension is still frequently `UNMEASURABLE` in practice — most genomes have no
  audit — and the module docstring is where a reader learns why.

### Correcting a stale note

`PRIORITIES.md` stated this slice would also need an edit to `test_no_kernel_path_acts_on_a_frontier`'s
allowed-importers list. It did not: that test scans for modules importing `selection`, and this slice
only added an import *from* `selection.py` *of* `content_audit` — the direction `test_nothing_yet_
consumes_a_content_audit` (renamed `test_only_selection_consumes_a_content_audit`) already governs.
The claim was written before the wiring was designed and never checked against the two tests' actual
axes; logged here rather than left to drift further (`feedback-mitosis-claim-drift`'s pattern).

---

## ADR-067: `model_policy`'s temperature socket is filled — a closed dict, read by `providers.py`, never a kernel constant

- **Status:** Accepted; `genome.py`, `providers.py`, `deliberation.py`, `gateway.py`, 11 new tests
  across five files, golden run unchanged (no scenario Cell declares `model_policy`)
- **Spec ref:** §14.1, §14.2, §16.2, §16.3, §24; ADR-050

- **Context:** ADR-050 measured that sampling temperature dominates parse rate more than model
  choice does, and refused the one-line fix (`temperature: 0` as a provider constant) because §14.1
  names "temperature/sampling mutation" as a prompt-mutation operator — sampling belongs in the
  *mutable Cell* column, not the kernel's. It named the socket already reserved for this:
  `model_policy` is a §16.2 genome field, hashed into `cells.model_policy_hash`, written at birth and
  read by nothing. This slice fills it.

### A closed dict inside an already-inheritable field, not a new top-level field

`model_policy` was already in `INHERITABLE_FIELDS` and already flowed through `inherit()`'s
overlay — the "first real decision" PRIORITIES flagged ("is sampling inherited, mutated, or both?")
turned out to already be answered by the existing mechanism every other genome field uses: a child
keeps its parent's `model_policy` unless a mutation overlays it, which is both inheritance and
mutability at once, with no new code path. What needed a decision was `model_policy`'s *content*
shape, which had none — any JSON-serializable value passed validation, including the free-text
string one pre-existing test (`test_a_model_policy_change_is_not_a_new_idea`) used as a placeholder.

`MODEL_POLICY_FIELDS = {"temperature": ...}` closes it the same way the top-level genome schema is
closed: an unknown key is refused by name. §14.1 names two more mutation operators that could occupy
this socket later (model-route, reasoning-budget), so a misspelled or half-built key must fail
loudly now rather than being silently ignored by whichever provider doesn't recognise it later.

### Bounded to `[0.0, 1.0]`, not the union of every provider's range

Anthropic's Messages API hard-limits `temperature` to `[0.0, 1.0]`; Ollama accepts a wider range by
convention (its own default is 0.8, and callers regularly pass up to 2.0). The genome validates
against the *tighter* range rather than the union of both, because §14.2 requires mutations to be
evaluated as "counterfactual twins... differing by one prompt-level change" — a temperature valid on
Ollama but rejected outright by Anthropic would make a cross-provider twin comparison undefined
rather than merely inconvenient. The same bound is repeated at the `providers.ModelRequest` pydantic
field (`ge=0.0, le=1.0`), deliberately redundant with `genome.py`'s check: a bad value must never
reach a provider regardless of which caller built the request — `cli.py`'s `call-model` and any
future caller besides `deliberation.py` included.

### `None` means "no opinion", and is never conflated with 0

A genome that has never mutated `model_policy` reports `temperature_of() is None`, not `0.0`. This
matters concretely: ADR-050's finding was that temperature 0 (greedy decoding) collapses a colony to
one repeated idea per run — the *worst* outcome measured. Reading absence as 0 would have silently
reproduced the exact failure mode this slice exists to keep out of the kernel's hands. `None` reaches
`providers.py` and is read there as "use the provider's own default" — Ollama's 0.8, Anthropic's
own — by omitting the key entirely from the request sent to the SDK/HTTP layer, not by sending
`temperature: null`. The same omission-not-null discipline extends to `gateway.py`'s
`model_calls.parameters_json`: a stored `null` on every historical row (most genomes declare no
policy) would read as "temperature 0 was requested" rather than "nobody asked", and no scenario Cell
in the golden run declares a `model_policy`, so the golden hash stays unchanged only because absence
stays absent all the way through.

### What it displaced

- **Deriving "inherited or mutated" as a new design question.** Considered and dropped once
  `INHERITABLE_FIELDS` was re-read: `model_policy` already sat there, so the question was already
  answered by the mechanism every sibling field uses. No special-casing was added.
- **Wiring `auditor.py`/`content_audit.py`/`cli.py`'s `call-model` to the same socket.** ADR-050's
  entire argument is about the deliberation loop's parse-rate/diversity trade-off (§14.1, §14.2);
  Auditor and content-audit calls are operator-composed judgments (§10.4) with a different
  provider/model already chosen by the caller, not a Cell acting from its own mutable genome. Logged
  in FUTURE_BUILD_HOOKS as a plausible follow-up rather than bundled in here without its own argument.
- **A live counterfactual-twin measurement using the new socket**, the way ADR-050 itself ran one.
  This slice wires the mechanism the measurement would need; running that measurement is a separate,
  reviewable act with its own arms and sample size, not a byproduct of shipping the wiring. Logged in
  FUTURE_BUILD_HOOKS.
- **Allowing `model_policy` to keep carrying free-form descriptive text alongside the structured
  key.** `test_a_model_policy_change_is_not_a_new_idea` (`test_novelty.py`) used a string as a stand-in
  before this field had any validation at all; its fixture is now a dict (`{"temperature": 0.9}`) and
  its actual subject — that `model_policy` changes never count toward novelty distance — is unchanged.
  A `notes`/description key was considered and rejected: nothing reads free text today, and an unread
  field is exactly the kind of silent-drift risk `MODEL_POLICY_FIELDS`' closure exists to prevent.

---

## ADR-068: `risk_tier` is optional for exactly one kind — `abstain` — and unrepresentable otherwise

- **Status:** Accepted; `proposal.py`, migration 0032, `deliberation.py`, 8 new tests across three
  files, golden expectations **35 -> 36**
- **Spec ref:** §23.1, §0.3; ADR-047, ADR-049, ADR-050

- **Context:** Two independent live measurements produced the same shape of failure on `abstain`
  replies. `qwen2.5` at t=0 dropped `risk_tier` (with `summary` and `estimated_cost_minor_units`)
  from every abstain reply in its collapsed run; `llama3.2` sent `"risk_tier": null` on the same
  shape. PRIORITIES read this correctly: "a stronger model reaching the same objection is evidence
  the schema is wrong rather than the models" — §23.1 classifies *actions* ("batch low-risk
  reversible actions; require individual review for high-risk or irreversible"), and a Cell that
  proposes no action has nothing to classify. Asking it to state a tier anyway is asking it to
  invent a number about a hypothetical with no shape.

### Scoped to exactly the defensible field, not the whole failure shape

`qwen2.5`'s collapse dropped three fields, not one. Only `risk_tier` has an argument for being
optional: an abstaining Cell still has something to say (`summary`: "nothing worth doing, because
...") and its cost is trivially 0 (the prompt already says "use 0 if nothing would be spent" — a
Cell that cannot answer that has not understood the field, not correctly identified it as
inapplicable). Widening `summary` or `estimated_cost_minor_units` too would fix a different, wholly
unargued failure under cover of this one. This is the same discipline `content_audit.py` used for
§13.4's two flags it left unbuilt — do exactly what the argument supports, log the rest.

### Unrepresentable, not merely refused (ADR-047's precedent, applied again)

`Proposal._risk_tier_matches_kind` (a `model_validator`, the same shape `_experiment_matches_kind`
already uses) rejects a null `risk_tier` on every kind but `abstain` at parse time. That alone would
have been sufficient for the one caller that exists today (`deliberation.deliberate`), but ADR-047's
argument is that a constraint with no layer belongs in the schema whenever the schema can express
it — it binds every caller, including ones that never import `proposal.py`. Migration 0032 rebuilds
`proposals` (SQLite cannot `ALTER` a `CHECK`, the same reason migrations 0019/0021/0027 rebuilt it
before) with `CHECK (risk_tier IS NOT NULL OR kind = 'abstain')`. Both layers are teeth-checked
independently: reverting the Pydantic validator and reverting the CHECK each produce their own real
MISS, confirming neither is redundant with the other.

### The "§23.1 implications" PRIORITIES flagged did not materialise

PRIORITIES' entry anticipated consequences worth checking before assuming none. There aren't any:
`approval._enqueue_locked` already returns `None` for `kind == 'abstain'` *before* it ever reads
`row["risk_tier"]` — abstaining proposals have never reached the approval queue (ADR-046's "approving
one *is* the act" reasoning already excludes STATEMENT_KINDS' sibling, and `ProposalKind.ABSTAIN` is
excluded from that set for the same underlying reason, just deliberately absent from the frozenset
rather than listed in it). So the one place §23.1's tier actually gets *read* as a classification —
`approval._assessed_tier`, via `RiskTier(row["risk_tier"])` — is structurally unreachable for a row
that could ever carry a NULL. `deliberation.py`'s two `.value` accesses were the only real call sites
needing a change, both now `parsed.risk_tier.value if parsed.risk_tier is not None else None`.

### What it displaced

- **A default of `LOW` for an omitted `risk_tier` on abstain.** Rejected: a fabricated default is
  worse than an honest `None`, and it would be indistinguishable from a Cell that actually claimed
  LOW — the same "a zero is a claim, an abstention is the truth" argument `selection.py`'s axes use
  for their own absences.
- **Making `risk_tier` optional for every kind.** Considered and rejected immediately: §23.1's
  classification is real and load-bearing for the four kinds that propose something to review. The
  fix is scoped to the one kind that structurally cannot state one, not a general relaxation.
- **A CLI or Python-only fix, no migration.** Rejected per ADR-047: the schema can make the invariant
  unrepresentable, so it should, independent of `proposal.py` remaining the only writer today.

### Verification

- **8 new tests across `test_prompt_shape.py`, `test_deliberation.py`; teeth-checked twice, once per
  layer.** Neutralising `_risk_tier_matches_kind` failed `test_every_other_kind_still_requires_a_
  risk_tier` (a clean `DID NOT RAISE`, parametrized over all four other kinds). Dropping migration
  0032's CHECK failed `test_the_schema_itself_refuses_a_null_risk_tier_on_a_non_abstain_kind` the
  same clean way — confirming the schema layer is doing real work, not merely mirroring Python.
- **1168 tests and the golden run green.** Golden expectations moved **35 -> 36**: no scenario Cell
  ever proposes `abstain`, so no row's `risk_tier` becomes NULL in the replay — the only diff is
  `input_tokens` shifting by a constant +30 on every deliberation-loop `model_calls`/`resource_usage`
  row, because the rendered prompt hint describing the new exception is longer text
  (`MockProvider`'s token estimate is a pure function of prompt length). `output_tokens`, cost, and
  every ledger balance are byte-identical to version 35.

---

## ADR-069: A bounded, single parse-repair retry — a new call, never the `execution_unknown` retry `gateway.py` already declined

- **Status:** Accepted; `deliberation.py`, migration 0033, `cli.py`, 7 new tests, golden 36 -> 37
- **Spec ref:** §24 (intro: "retries controlled failures"), §24.1; ADR-022, ADR-049, ADR-050

- **Context:** PRIORITIES had carried this since ADR-049 as "the standard remedy, deliberately
  unbuilt": re-prompting with the validation error after an unparseable reply "would probably lift
  the rate a lot," but the item was gated — "worth arguing once the model question above is
  settled, because a better model may make it unnecessary." The model question settled in the
  negative: `qwen2.5` is unusable on this hardware (0.53 tok/s), so `llama3.2` stays the model and
  its parse-rate ceiling stands. That closes the gate this entry was waiting on.

### Not the retry `gateway.py` already scoped and declined

`gateway.py`'s own docstring lists "Retries" among what is deliberately out of scope: "A retry
after an `execution_unknown` failure risks double-billing, and deciding that needs the
reconciliation this kernel cannot do yet." That is a different mechanism answering a different
question — whether to re-attempt a call whose *billing status is ambiguous*. A parse-repair retry
never faces that question: the first call is known to have **succeeded and been billed** (it
returned response text; `ProposalError` only fires after that). What failed is the *reply*, not
the call. So this is a wholly new, separately-priced, separately-capped `gateway.call_model`
invocation — the same category §24's intro line also names ("validates structured output"), which
FUTURE_BUILD_HOOKS already noted lives in `deliberation.py`/`proposal.py` rather than the gateway.
Building this here extends that precedent rather than crossing the boundary `gateway.py` drew.

### Bounded to exactly one attempt, and the bound is load-bearing

`MAX_PARSE_REPAIR_ATTEMPTS = 1`. PRIORITIES' own framing — "it pays twice for a prompt bug" —
already named the accepted cost; an unbounded loop would turn a persistently broken prompt (a
model stuck emitting the same malformed shape, the exact failure ADR-050 measured at `qwen2.5`
t=0) into an unbounded per-wake cost multiplier, which is precisely the runaway-cost shape Charter
C4/C5's caps exist to prevent one call at a time, not one wake at a time. A second reply that also
fails to validate ends the wake as UNPARSEABLE; nothing tries a third time.

### One nullable column, not a second `model_call_id`

A repaired deliberation genuinely makes two billed calls. Collapsing them into the existing
`model_call_id` column would either drop the first call's cost from the record or overwrite which
call actually "did the thinking." `deliberations.repair_model_call_id` (migration 0033) is `NULL`
for the overwhelming majority of deliberations — the ones that parse first try — and named only
when a second call was made. A plain nullable `TEXT REFERENCES model_calls(model_call_id)` is a
legal SQLite `ALTER TABLE ADD COLUMN` (no CHECK, no NOT NULL, no computed default), so this needed
no rebuild the way migration 0032 (`proposals.risk_tier`) did.

### Best-effort for *economic* failures only — a repair never raises `deliberate()` on the grounds it couldn't afford a second call

`_attempt_parse_repair` catches exactly the exceptions that mean the second call could not be
*attempted* — `_REPAIR_UNATTEMPTABLE_ERRORS = (gateway.GatewayError, reservations.ReservationError,
real_spend_breaker.RealSpendBreakerError)`: an exhausted real-spend cap, an insufficient balance,
the breaker, the gateway's own pre-call refusals. Each degrades to the exact pre-repair behaviour:
an UNPARSEABLE deliberation recording only the original failure, `repair_model_call_id` left `NULL`.
This mirrors `_unfunded_books`' own reasoning ("a refusal costs nothing and is recorded, whereas the
gateway's refusal is an exception in the middle of a wake") extended to a second call that might not
be affordable even when the first one was. A provider-level failure on the repair call itself
(`ProviderCallError`) needs no special handling — `gateway.call_model` already converts that into a
`failed` `model_calls` row rather than raising, so it flows through the same "reply text failed to
validate" path as an ordinary malformed reply.

**Refined 2026-09-03 (post-slice critique):** the first pass caught a *blanket* `except Exception`
here, which also swallowed genuine faults — a programming error in `_attempt_parse_repair`, a locked
or corrupt database — and disguised them as "the model could not format its reply," an UNPARSEABLE
row with the traceback buried in `failure_reason` and no test able to catch it. The catch is now
narrowed to `_REPAIR_UNATTEMPTABLE_ERRORS`; anything else propagates, exactly as it already does from
the *first*, unwrapped `gateway.call_model` in `deliberate()`. New test
`test_a_bug_in_the_repair_path_propagates_rather_than_masquerading` pins this and teeth-checks
against the blanket catch; `test_a_repair_that_cannot_even_be_attempted_falls_back_gracefully` now
raises a real `RealSpendCapExceededError` rather than a stand-in `RuntimeError`.

### The repair turn, and what it deliberately does not resend

A three-message follow-up (original prompt, the model's own failed reply, a correction request
naming the specific validation error) rather than re-rendering the full context a second time —
the schema hint is already in the first turn and still in context, so repeating it would spend
tokens on the part that was never the problem. Echoing the Cell's own prior reply back to it is not
the §19.4 "untrusted external content" this repo treats model output as being — that principle
governs what a Cell may treat as a trusted *command* (§19.4's actual subject is public-web content),
not what a kernel-composed follow-up turn may show a model about its own immediately-prior output
in the same wake.

### What it displaced

- **Retrying inside the gateway itself**, keyed on `execution_unknown` recovery. Rejected: that is
  a different failure category (ambiguous billing) with its own unresolved reconciliation
  dependency, and conflating the two would have made this slice's scope open-ended.
- **An unbounded or configurable retry count.** Rejected per the cost-bound argument above — a
  second reply that also fails to parse is itself informative (the prompt or the model, not a
  transient slip), and a third attempt would not plausibly recover what two attempts could not.
- **Recording the repair prompt/reply text.** Rejected for the same reason the original unparseable
  reply is not stored: untrusted content sitting in a row a later reader could mistake for a result.
  `model_calls.response_text` already carries both raw replies for whoever needs to inspect them.
- **A live measurement of the actual parse-rate lift.** Not run in this slice, matching precedent
  from ADR-067 (the temperature socket): this ships the mechanism the measurement would use, not a
  repeat of ADR-050's kind of live Ollama campaign. Logged in FUTURE_BUILD_HOOKS.

### Verification

- **7 new tests in `test_deliberation.py`; teeth-checked.** Disabling the wiring in `deliberate()`'s
  except-branch (routing straight to a no-op `_RepairResult`) failed the two tests that defend
  the headline behaviour — a repaired PROPOSED outcome, and the two-call bound on a persistently
  bad reply — both with clean, specific assertion failures, not exit-code-only CAUGHTs.
- **1172 tests and the golden run green.** Golden expectations moved 36 -> 37: no scenario reply is
  malformed, so every deliberation's new `made_repair_call` field is `False` and nothing else in
  the snapshot moved — confirmed by a full section-by-section diff before regenerating, not assumed.

## ADR-070: Parse-repair is *not* extended to the Auditors or `call-model` — the mechanism's premise (reformat, don't re-judge) is what excludes them

- **Status:** Accepted; docstring correction in `auditor.py`, no other code change
- **Spec ref:** §23.2, §10.4, §24.1; ADR-067 (scope precedent), ADR-069 (the mechanism)

- **Context:** ADR-069 built a bounded parse-repair retry in `deliberation.py`. Its BUILD_RECORD
  "Next" line named three call sites that got none of it — `auditor.py`, `content_audit.py`, and
  `cli.py`'s `call-model` — as "scoped out the same way ADR-067 scoped temperature to
  `deliberation.py` only … an unargued follow-up, not a gap." This ADR is that argument, made once
  so the refusal is on record rather than re-derived every time someone re-reads the three sites and
  notices they share deliberation's shape. The conclusion is: **do not port.** The three sites are
  not one follow-up; they split into two decisively different cases, and neither wants the retry.

### `cli.py` `call-model` is not scoped-out — it is *inapplicable*

`cmd_call_model` takes a freeform `--prompt` and optional freeform `--system` and prints
`call.response_text` **raw**. There is no `parse()`, no schema, no `ProposalError`. A parse-repair
re-prompt names "the specific validation error"; here there is no validation and no error to name.
Listing this verb alongside the other two overstated the size of the open work — it belongs on no
follow-up list at all. Struck.

### The Auditors *look* identical to deliberation, and the resemblance is the trap

`auditor.audit_request` and `content_audit` share deliberation's exact shape: a paid
`gateway.call_model` -> a strict `_parse` -> on failure a **recorded rejection** carrying the
`model_call_id`. The mechanism from ADR-069 would drop in with almost no friction. Three things say
it should not, and the first is decisive:

- **The `_parse` error is not only a formatting fault — it also fires on an *incoherent verdict*.**
  Both `_parse` functions raise for two distinct causes: malformed JSON / schema violation, *and* a
  self-contradictory judgement — `concern` with probability above the coherence midpoint,
  `no_concern` with probability below it (`auditor._parse`, `content_audit._parse`). A repair
  re-prompt echoes that error back and asks for another try. For deliberation that means "reformat
  your proposal." For an Auditor a coherence error means "your verdict contradicts itself" — and
  re-prompting to fix *that* is asking the judge to reconcile a contradiction it already expressed.
  That is coaching the oversight mechanism, not reformatting a reply. §23.2 and §10.4 make the
  Auditor's entire value its independence, produced once; a kernel that nudges the verdict until it
  validates has quietly turned a one-shot independent judgement into a negotiated one.

- **The salvage value is lower.** A deliberation that fails to parse loses a **proposal** — the core
  economic output the whole loop exists to produce. A failed audit is *already* absorbed as a
  recorded rejected-audit; the approval path still has the fact that an Auditor was paid and
  produced nothing usable, and can route accordingly. Same bounded two-call cost, smaller upside.

- **ADR-067's precedent puts the burden on the extension, not the scope.** BUILD_RECORD cited
  ADR-067 (temperature scoped to `deliberation.py`) precisely because scoping-to-one-module was a
  *considered* refusal, not an oversight. The extension has to earn itself; on the two points above
  it does not.

### The stale claim this surfaced

`auditor._parse`'s docstring asserted its strictness was "the same policy `deliberation` applies:
never repair a half-understood judgement." As of ADR-069 that parallel is **false** —
`deliberation` now repairs once before recording. This is the recurring claim-drift shape in this
repo: a comment naming a *behaviour of another module* that a later slice changed, with no test
defending the claim. The fix is not to delete the line but to invert it into the deliberate
divergence this ADR records — which is the one code change this ADR carries. `content_audit._parse`
carried no such claim and needed no edit.

### What it displaced

- **Porting the ADR-069 mechanism to all three sites.** Rejected per the argument above: inapplicable
  at `call-model`, and premise-violating at the Auditors (repair reformats; it must not re-judge).
- **Porting to the Auditors only, reasoning that they share deliberation's call/parse/record shape.**
  Rejected: the shared shape is real but the `_parse` error is not — its coherence branch makes a
  repair a re-judgement, which the format-only repair in `deliberation` never is.
- **Splitting the Auditor `_parse` error into "format" (repairable) and "coherence" (not).** Rejected
  as more machinery than the upside warrants (point 2) and as still nudging an independent verdict on
  the format branch; the honest line is no repair for an oversight output, stated once.
- **Leaving the follow-up unargued in BUILD_RECORD.** Rejected: an unargued "not a gap" invites the
  same rediscovery every session. Recording the refusal *is* the deliverable, matching this repo's
  habit of writing down what it chose not to build and why (ADR-046's dead-socket precedent).

### Verification

- **No behavioural change to verify** — the decision is to build nothing. Full suite stays green
  (the docstring edit touches no code path). The teeth of this ADR are in the record, not a test.

## ADR-071: Wiring auto-promotion into `tick` allocates capital; it cannot approve a `spend_request` — that proposal kind is never batchable

- **Status:** Accepted; `cli.py::cmd_tick` passes a `promoter`; 7 new tests in
  `tests/test_scheduler_autopromotion.py`
- **Spec ref:** §25.1, §23.1, §27.1; ADR-063 (`autopromotion.py`, which this slice only calls)

- **Context:** an external audit brief's Slice E asked to "wire auto-promotion into the scheduled
  path" — `cli.py::cmd_tick` never passed a `promoter` to `scheduler.tick()`, so an operator who
  enabled `autonomy.auto_promotion` got proposals deliberated and queued every tick but nothing
  ever *allocated* unless they separately ran the standalone `mitosis auto-promote` verb by hand.
  The brief's own phrasing for the "on" behaviour to test was "a batchable request and funded pool
  are approved and allocated during a tick."

- **The decision this ADR records:** that scenario, read literally, cannot be built for a
  `spend_request` — the only proposal kind `promotion.allocate()` will ever consume
  (`_allocate_locked` rejects every other kind explicitly: "only a spend_request allocates
  capital"). `approval._kernel_tier` unconditionally floors a `spend_request` at `RiskTier.MEDIUM`
  regardless of the `risk_tier` the Cell claims in its reply, and `RequestStatus.batchable` requires
  `assessed_tier is RiskTier.LOW`. So **no `spend_request`, at any claimed tier, is ever
  batchable**, and `autopromotion.sweep()`'s own `approve_batch()` step can therefore never
  auto-approve one — on or off. Approval and allocation never meet inside one unattended sweep for
  this proposal kind: a human approves it (`approval.approve()`, exactly as happens today, with no
  change from this slice), and what the wiring actually adds is that *allocating* an
  already-approved grant — moving the money, waking the Cell — now reaches an ordinary scheduled
  tick instead of requiring the standalone verb to be run by hand.

  This is not a gap this slice leaves open. `_kernel_tier`'s MEDIUM floor on capital requests is a
  live safety guard (§23.1: "high-risk stays for a person"), and loosening it to manufacture a
  batchable spend request would be widening exactly the predicate `autopromotion.py`'s own module
  docstring promises never to widen. The correct reading of "wire auto-promotion into the scheduled
  path" is the allocation half alone — approval of capital requests staying human by construction is
  the feature, not an accident this ADR excuses.

- **What it displaced:**
  - **Testing "auto_promotion on approves and allocates a batchable spend_request during one
    tick"** as the brief's phrasing suggested. Rejected: unbuildable without either loosening
    `_kernel_tier`'s floor (out of scope, unargued, and a live guard) or fabricating a test double
    that bypasses real kernel assessment (defeats the point of an integration test for the actual
    wiring).
  - **Asserting only `result.halted` / equality against `()`** in the first draft of the vacation
    and off/on tests. Two real bugs, not just weak style: `allocatable_grants`/`list_promotions`
    both return `list`, and `[] == ()` is `False` in Python unconditionally — those assertions would
    have failed (or, if reversed, silently proven nothing) regardless of the actual promotion state.
    A teeth-check that neutered the vacation guard caught this before it shipped, and separately
    caught the vacation test's own paid fake provider tripping the *earlier* `real_spending`-disabled
    guard first, the identical confound `tests/test_scheduler.py`'s
    `test_an_absent_operator_pauses_paid_work_but_not_free_work` already guards against.

- **Verification:** 7 new tests, including one driven through `cli.main` end-to-end specifically
  because every direct-`scheduler.tick()` test supplies its own `promoter` and so cannot catch
  `cmd_tick` itself forgetting to build one. Three teeth-checks (the CLI wiring reverted, a
  forbidden import reintroduced into `scheduler.py`, the vacation guard neutered), each confirmed to
  fail for the named reason and then restored verbatim. Full suite 1239 passed (7 new); golden run
  unaffected (hash unchanged at 38 — this slice touches `cli.py` and tests only).

## ADR-072: The Phase 2 flight simulator's seam — mock Cells decide through the real deliberation pipeline, and reproduction/capital move through real kernel entry points

- **Status:** Accepted; `src/mitosis/simulation/` (new package), migration 0035, `pricing.py`,
  `cli.py`'s `simulate` verb, 12 new tests in `tests/test_simulation.py`
- **Spec ref:** §7 (colony flight simulator), §8 (anti-Goodhart/simulator overfitting), §9
  (population control), §14.1 (mutation operators), §28 Phase 2; implementation brief Slice F

- **Context:** the external audit brief ranks the Phase 2 flight simulator as "the highest-value
  substantive build" — testing the kernel's governance/accounting machinery at population scale
  (hundreds of Cells, thousands of epochs) with zero real spend, which SPEC.md's own Amendment A1
  already concedes was never done because this repo built Phase 4 (the LLM loop) before Phase 2.
  Given the size, a dedicated plan was written first (grounded in three research passes over the
  actual current code, not memory) and approved before any code — this ADR is that plan's
  as-built record, including three places building it refined the plan itself.

### Kernel reuse, confirmed rather than assumed

Every birth, death, transaction, experiment, and capital movement goes through the existing entry
points — `lifecycle.create_cell`/`lineage.reproduce`, `ledger.post_transaction`,
`experiment_grants.start_from_grant`/`experiments.conclude`, `revenue.record_revenue`,
`scheduler.tick`. The simulator supplies only the decisions nothing in the kernel makes today: what
a mock Cell proposes (`simulation/policy.py`), what a customer does
(`simulation/environment.py`), and which Cell reproduces (`simulation/selection_policy.py`).

### Mock Cells decide through `deliberation.deliberate()` via a new `ModelProvider`

`SimulationPolicyProvider` implements the existing `providers.ModelProvider` Protocol, so it plugs
into `scheduler.tick()` unchanged — a mock Cell's proposal still passes through the real
`proposal.parse()` schema, risk-tier assessment, and approval queue. Deliberately stateless with
respect to *which Cell* is calling: `ModelRequest` carries no Cell identity and the rendered prompt
names none either (only genome content, which two Cells can share right after birth) — the policy
keys its decision on the genome content shown *this call* plus a monotonic per-provider call
counter, which reproduces from a seed without needing an identity the interface does not provide.
Every `(provider, model)` pair a simulation ever constructs must be pre-registered in
`pricing.PRICING_TABLE` at `ModelPrice("0","0")` — `gateway.call_model` prices a call *before* any
reservation, and an unregistered pair raises `UnknownModelError` unhandled, aborting the whole
tick rather than one Cell's wake.

### Plan refinement found while building: experiments, not spend requests, are the vehicle

The plan (written before any code) proposed a new `SIMULATION_DECIDER` identity calling
`approval.approve()` directly on `spend_request` grants, reasoning from ADR-071's finding that
`spend_request` is never kernel-assessed LOW and so never auto-batchable. Building the policy
surfaced a cleaner fact: `approval._kernel_tier` has **no branch at all for
`ProposalKind.EXPERIMENT`** — it stays at the initial LOW unless quarantine or cumulative exposure
raises it. A LOW-claimed, reversible (`_is_reversible` excludes only `EXTERNAL_ACTION` and a
USD_REAL `SPEND_REQUEST`), signal-free `EXPERIMENT` proposal is therefore genuinely `batchable` and
is auto-approved by the *existing* `autopromotion.sweep()` batch step ADR-071 already wired into
`scheduler.tick()` — no new approval decider needed for the common case at all. This also explains
two reserved sockets found already sitting in the repo, unfilled: `experiment_grants
.FLIGHT_SIMULATOR_RUNG = 1` and `experiments.LADDER`'s rung-1 label, verbatim, `"flight simulator"`
— the spec's own authors clearly meant experiments, not spend requests, to be this slice's primary
proposal vehicle. `SIMULATION_DECIDER` still exists and is used, but only for the steps that have no
existing automated decider at all: starting an approved grant's experiment
(`experiment_grants.start_from_grant`) and concluding it once the environment evaluates an outcome
(`experiments.conclude`) — both per-Cell kernel calls with no batch/scheduled caller today.

### Three bugs found by running it, not by reading it

- **`random.Random()` does not accept a tuple as a seed** (`ValueError`, not silently wrong) — every
  draw in `environment.py`/`policy.py`/`runner.py` was keyed on a tuple of coordinates. Fixed to a
  stable f-string, which (unlike `hash()`) does not depend on `PYTHONHASHSEED` and so reproduces
  across separate processes, not just within one.
- **`experiment_grants.start_from_grant` raises two sibling exceptions, and only one was caught.**
  `experiments.ExperimentConflictError` (a cell already has one running) is expected and common —
  `autopromotion.sweep()`'s own approval batch enqueues a `WAKE_HUMAN_DECISION` follow-up wake
  (§17.2) that becomes ready only on the *next* tick, so a cell routinely carries two pending grants
  into one epoch. Only that subclass was caught at first; at population >= `max_parallel_experiments`
  (default 20, §9.2's colony-wide slot cap) the sibling `ExperimentCapacityError` fires just as
  often, and being uncaught it aborted the entire epoch before the evaluate/conclude loop ran —
  stranding every running experiment permanently, since nothing ever concluded to free a slot again.
  Fixed by catching the shared `experiments.ExperimentError` base, matching `autopromotion.sweep()`'s
  own posture of catching a base exception per-item rather than crashing the sweep.
  Caught at population=20; a smaller smoke run (population <=10) never exercises this path at all,
  which is why the plan's own "prove the seam at small scale" framing did not surface it —
  recorded here so a future slice does not have to relearn it by rerunning a bigger scenario.
- **A reserve/release row is not spend.** The first invariant check counted `Book.USD_REAL`
  transaction rows, and failed on every run: `gateway.call_model` reserves and releases against
  USD_REAL for *every* model call regardless of provider (a `cell:X:cash` <-> `cell:X:committed`
  pair netting to zero, `mock`/`ollama` included) — pre-existing reservation-FSM bookkeeping, not
  real spend. The invariant now sums `external_expense` activity in `Book.USD_REAL` instead
  (`usd_real_spend_unchanged`), which is what "zero USD_REAL movement" (brief acceptance criterion)
  actually means in context.

### A gap fixed while building, not deferred

`lineage.reproduce()` funds a child only in the parent's own book (funding cannot cross books,
§2.4) — a child born this way had no USD_REAL/RESOURCE balance of its own and would be permanently
unschedulable (`scheduler.eligible_cells` requires >= 1 in both, regardless of a Cell's own book).
Every reproduction now also funds the child's scheduler-eligibility sliver from `seed_bank`, the
same as founding — `_fund_scheduler_eligibility`, shared by both paths. Confirmed live: population
20 -> 70 over 50 epochs, every child actually woken, proposing, and evaluated in later epochs, not
just present as an inert row.

### What this slice deliberately did not build

Matching the plan's own sub-slice sequence, unstarted: a second, independently-shaped environment
family (brief requires >= 2); environment separation (training/validation/secret-challenge, §8.1);
scheduled regime shifts (§8.4); the five real mutation operators beyond the required no-op/control
(§14.1); chaos drills (§28's kill-30%/corrupt-module/crash-at-boundary scenarios); full manifest
richness (population/diversity time series); the four remaining `SelectionPolicy` implementations
(Slice G). `selection.py`'s `reproducibility` gate and `economic_potential` axis stay
`UNMEASURABLE` — a simulated economy could compute real values for both, and the brief calls this
out as a Slice G decision, not this one.

### Verification

- 12 new tests: determinism (two fresh in-memory colonies, same seed, byte-identical manifests
  except `run_id`, which identifies the invocation rather than the deterministic economic content —
  the same posture `scheduler.tick_id` already takes); the `external_expense` invariant; population
  growth through the real `lineage.reproduce` path (population raised to 10 so a lineage's first
  child clears `max_lineage_population_fraction`'s 0.20 cap, rather than merely tolerating the
  well-documented founder-effect tension at tiny scale); a reproduced child's own USD_REAL/RESOURCE
  eligibility funding (added *after* finding that gap, since none of the other tests would have
  caught its regression); a population=20 run against §9.2's default 20-slot cap (added after
  finding the `ExperimentCapacityError` bug at that scale, since every other test here runs at
  population <=10 and would never exercise it); a CLI end-to-end run writing a manifest file; the
  policy's prompt-extraction seam; environment purity; a structural test that no kernel module
  imports the `simulation` package.
- Every bug this ADR describes above was teeth-checked in the literal sense: the fix was reverted,
  the specific new test confirmed to fail for the stated reason, then the fix restored — the
  capacity-cap fix via the population=20 test, the eligibility-funding fix via the child-balance
  test, the structural boundary via a temporary `simulation` import into `scheduler.py`, and the
  `external_expense` invariant via a temporary fake USD_REAL spend inserted into the epoch loop.
- Full suite green, golden run unaffected (hash unchanged at 38 — this slice adds a new package,
  a migration nothing existing reads, and a new CLI verb; it touches no existing scenario), `ruff
  check .` and `scripts/check_docs_facts.py` both clean (README's migration count and phase-status
  table updated: Phase 2 split from Phase 3 to state what is and is not yet built, rather than
  leaving a now-inaccurate "not built" blanket claim).
- Manually run at population=20/epochs=50 (~5.6 epochs/sec on this hardware) and population=20/
  epochs=5 to reproduce and confirm the capacity-exhaustion bug before fixing it — both a smaller
  smoke scale (this slice's actual scope) and one large enough to hit §9.2's colony-wide cap, since
  the smaller scale alone would have shipped the bug undetected.

## ADR-073: A second, independently-shaped market family, real environment separation, and scheduled regime shifts (Slice F, part 2)

- **Status:** Accepted; `src/mitosis/simulation/environment.py` gains `RuleBasedMarket`,
  `EnvironmentSuite`, and a scheduled regime shift on both families; `cli.py` gains `simulate
  --environment`; 12 new tests in `tests/test_simulation.py` (24 total)
- **Spec ref:** §8.1 (environment separation), §8.3 (multiple simulator families), §8.4 (scheduled
  regime shifts); `docs/DECISIONS.md`'s ADR-072 (this slice's own F1 predecessor and architecture)

- **Context:** F1 shipped exactly one environment family (`UtilityMaximizingMarket`) and said so in
  its own docstring — brief requirement F.2 ("at least two independently shaped customer/market
  models so success cannot depend on one authored rule set") was explicitly deferred to this slice.
  §8.1's three-way training/validation/secret-challenge separation and §8.4's scheduled regime
  shifts were likewise named in the F1 architecture plan as F2's addition, not built yet.

- **`RuleBasedMarket`, and what "independently shaped" has to mean to be true:** the sibling
  compares a continuous random willingness-to-pay draw against price. A second family that just
  reused that comparison with different constants would not satisfy §8.3 — a strategy tuned to win
  one continuous curve wins the other too, which is exactly the collusion the clause rules out. This
  family is instead discrete rule branching throughout: a price tier, a genome-declared boolean flag
  required to clear the standard tier, and a premium tier gated on a declared quality flag plus a
  fixed-cutoff coin flip rather than a price-sensitive curve. `test_the_two_environment_families_
  disagree_on_the_same_genome` proves the two mechanisms actually disagree on one fixed genome
  (price=600, no `durable` flag: sometimes clears the sibling family, never clears this one) rather
  than merely asserting they are different classes.

- **Environment separation without a fake consumer:** `EnvironmentSuite` is a real, three-field
  frozen dataclass (`training`, `validation`, `secret_challenge`) — not an enum-and-registry, since
  nothing in this slice dispatches on role generically; three named fields already are the "config
  object with controlled visibility" §8.1 asks for. The separation is enforced structurally, not by
  convention: `runner._run_one_epoch`'s own signature takes one `MarketEnvironment`, not a suite, so
  there is no path by which the routine loop could reach `validation` or `secret_challenge` even by
  a future mistake — `run()` is the only place that reads `suite.training` out of the suite at all.
  `test_the_routine_epoch_loop_never_touches_validation_or_secret_challenge_environments` proves this
  with a fake that raises the instant anything calls it, not an AST check.

  **What this deliberately does not do:** wire a `validation`-consulting selection policy.
  `RandomEligibleSelection` does not look at any environment outcome at all, by design (brief Slice
  F's own minimum) — building a fake consumer just to exercise the `validation` slot would be
  exactly the premature abstraction this repo's own conventions warn against. §8.1's "influences
  capital allocation" clause is realized once a Slice G selection policy exists that looks at
  performance at all; this slice lays the pipe and proves the boundary holds, not more.

- **Scheduled regime shifts, on both families, at one shared epoch:** `_REGIME_SHIFT_EPOCH = 10` is
  a fixed colony-wide constant, not a random draw — §8.4 calls this "part of fitness evaluation, not
  only a test category," which a random shock would not satisfy (nothing could be pre-registered
  against it). `UtilityMaximizingMarket` gets a price-compression shift (willingness-to-pay range
  narrows from `uniform(0.5,1.5)` to `uniform(0.3,0.9)` — §8.4's "demand changes, price
  compression"); `RuleBasedMarket` gets a stricter-enforcement shift (the always-clears budget tier
  narrows from <=300 to <=150 — §8.4's "platform-fee changes... stricter enforcement"). Both are
  proven behaviourally, not just structurally: a price chosen so the pre-shift branch sometimes
  purchases and the post-shift branch can *never* purchase (600 exceeds the post-shift ceiling of
  450; 200 exceeds the post-shift budget-tier boundary of 150), so the assertions are deterministic
  facts about the fixed seed, not statistics that could pass by chance.

  A shift is a colony-wide happening the environment produces on its own clock, not one Cell's
  action — recorded via `audit.record` the same way `SelectionDecision` already is (ADR-072), rather
  than inventing a second schema-level identity for a fact this mechanism already carries. Manifest-
  level regime-shift bookkeeping stays out of scope here on purpose: `manifest.py`'s own docstring
  already assigns "regime-shift bookkeeping" to F5, once diversity time series make a fuller
  manifest shape worth building at once rather than piecemeal — this slice makes the shift a real,
  audited fact rather than inert Protocol plumbing nothing calls, without pre-empting F5's own
  design of how it surfaces in the retained artifact.

- **What it displaced:** an `EnvironmentRole` enum plus a role-keyed dict, considered for
  `EnvironmentSuite` and rejected — nothing dispatches on role generically in this slice, and three
  named dataclass fields say everything an enum would without the indirection. Also rejected: CLI
  flags for `--validation-environment`/`--secret-challenge-environment` — surface for two roles
  nothing consumes yet is exactly the kind of speculative API this repo's conventions rule out;
  `EnvironmentSuite` is directly constructible by any Python caller (tests, a future scenario
  loader) in the meantime.

- **A pre-existing test broke, correctly, for a real reason:** F2a's own
  `test_the_two_environment_families_disagree_on_the_same_genome` (written before the regime shift
  existed) sampled epochs 0-29 at price=650 and asserted at least one sale in the sibling family. Once
  the shift landed, epochs >=10 became provably unsellable at that price (450 < 650) in that family,
  and the specific seed/cell_id/price combination happened to have zero hits in the remaining
  pre-shift window (0-9) — an instance of this repo's own "grep every reader" discipline: a change to
  what a late epoch *means* silently broke a test that exercised one, once run rather than merely
  reread. Fixed by restricting to the pre-shift window and picking a price (600) verified, not
  assumed, to hit within it.

- **Verification:** 12 new tests (24 total in the file): the sibling family's purity, tier rules, and
  disagreement with `UtilityMaximizingMarket`; `build_environment`'s name-based construction and
  rejection of an unknown name; the CLI's `--environment` flag actually changing which family a run
  uses (not just accepting the flag); the routine loop's structural blindness to `validation`/
  `secret_challenge`; both families' regime shifts, behaviourally and via `advance()`'s returned
  event; the shift's audit-trail record. Six teeth-checks, each confirmed to fail for the stated
  reason and then restored verbatim: the durable-flag tier-rule removed (breaks both the durable-flag
  test and the disagreement test), the unknown-name rejection removed (breaks the factory test), the
  CLI wiring reverted to ignore `--environment` (breaks the CLI family-selection test), the routine
  loop rewired to read `suite.validation` (breaks the never-call test), the regime-shift epoch branch
  removed from `evaluate` (breaks the shift test), and the audit-recording loop removed from
  `_run_one_epoch` (breaks the audit-trail test). Full suite green; golden run unaffected (hash
  unchanged at 38 — this slice touches no existing scenario); `ruff check .` and
  `scripts/check_docs_facts.py` both clean.

- Next: the remaining mutation operators (§14.1, Slice F3), chaos drills (§28), full manifest
  richness (Slice F5), then Slice G's remaining `SelectionPolicy` implementations and Slice H's
  pre-registered Phase 3 comparisons.

## ADR-074: The remaining six mutation operators, wired through a real operator choice instead of a hardcoded no-op (Slice F, part 3)

- **Status:** Accepted; `src/mitosis/simulation/mutation.py` gains six operators and an
  `OPERATORS` dispatch table; `selection_policy.py` and `runner.py` change to use it; 9 new tests
  in `tests/test_simulation.py` (33 total)
- **Spec ref:** §14.1 (mutation operators), §16.3/§16.4 (the closed, inheritable genome schema);
  implementation brief's "Mutation and reproduction" section, verbatim: market/customer,
  product/delivery, acquisition-channel, pricing/revenue-model, workflow, model-policy temperature,
  one no-op/control — the brief's own list, not SPEC.md §14.1's longer one (that clause names two
  taxonomies, "prompt mutation operators" and "economic mutation operators... from v0.1"; the brief
  synthesizes six from both lists plus the control already shipped in F1)

- **A hardcoded call was hiding behind a decision-record field that already existed.**
  `SelectionDecision.mutation_operator: str` has recorded an operator *name* since F1
  (ADR-072) — but `runner._run_one_epoch`'s reproduction loop never read it: every reproduction
  called `mutation.no_op(...)` directly, regardless of what the decision said. F1's own `no_op`
  being the only real operator meant this went unnoticed; wiring five more operators without fixing
  the dispatch would have shipped them as unit-testable functions nothing in the live pipeline ever
  calls — exactly the "reserved socket that stays unfilled" pattern this repo's own conventions flag
  repeatedly. Fixed with an `OPERATORS: dict[str, Callable]` registry in `mutation.py` and
  `RandomEligibleSelection.decide()` now choosing an operator name uniformly at random (reusing the
  same `rng` it already draws the parent choice from, so the decision stays one deterministic
  stream, not two) — `runner.py` dispatches on `decision.mutation_operator` rather than a fixed call.

- **A second, independent bug in the same call site: the bare `master_seed` reused for every
  mutation in a run.** `mutation.no_op(parent_content, seed=master_seed)` passed the *run's* seed
  unchanged to every reproduction event — harmless for a no-op that ignores its `seed` parameter
  entirely, but for a real operator this would make every mutation of one operator across a whole
  run draw the identical "variation," forever. Fixed by deriving a per-event label,
  `f"{master_seed}:mutation:{epoch}:{parent_id}"`, matching this package's existing seeding
  convention (a stable f-string, never `hash()`, for the same cross-process-determinism reason
  `environment.py` already documents) rather than reusing a raw value.  This is the same shape of
  bug as F1's tuple-seed bug (ADR-072) and F2's stale-epoch-range test break (ADR-073) — a call site
  built before its inputs mattered, unexercised until something downstream actually varied by them.

- **Operator signature is uniform on purpose:** every operator is
  `(parent_content: dict, *, seed: str) -> tuple[dict, str]`, `no_op` included (its own `seed`
  parameter's declared type changed from `int` to `str` to match — a no-op change to its behaviour,
  since the parameter was already deleted unused). A caller holding only a name string —
  exactly what `SelectionDecision` carries — can dispatch through `OPERATORS[name]` without a
  per-operator special case.

- **Discrete operators guarantee a change; continuous ones don't try to.** Market segment, delivery
  mode, acquisition channel, and workflow structure each pick from a small fixed candidate set,
  explicitly excluding the parent's current value — invoking one of these always changes that field,
  because the operator's entire identity *is* "this field changed." Price and temperature are
  continuous: any nonzero perturbation already differs, and the one case where clamping produces no
  change (temperature already at 0.0 or 1.0, pushed further the same way) is a real, honestly
  recorded outcome, not a bug to retry away — the brief asks to *record* "whether it created
  genuinely distinct canonical content," not to force every call to produce it.

- **Recording the brief's five required facts without a schema change.** `genome.inherit()` merges
  a mutation dict key by key (`content.update(mutation)`, no deep merge) — so an operator changing
  one nested field must read the parent's current value for that whole top-level key, copy it, and
  return the modified copy, or every other nested fact under that key would be silently dropped from
  the child (`test_mutation_operators_preserve_unrelated_fields_within_the_same_key` guards this).
  Parent/child genome hashes already live on `cells`/`cell_genomes`; what the schema doesn't carry —
  the seed, the before/after diff, whether the result was genuinely distinct — goes through
  `audit.record(event_type="simulation_mutation", ...)`, the same "explain, don't define a second
  identity" mechanism `SelectionDecision` (ADR-072) and regime-shift events (ADR-073) already use.
  This isn't a stylistic echo of those two: it is the *same reason* each time — a mutation that
  collapses to the parent's own existing `cell_genomes` row (ADR-018) writes no new row at all, so a
  schema-level column could never carry a fact about *this* reproduction event distinctly from
  whichever earlier event first created that row. Only the audit trail can.

- **What it displaced:** retrying a continuous operator until it produces a different value from the
  parent, considered for price/temperature to match the discrete operators' guarantee and rejected —
  the brief's own phrasing ("whether it created genuinely distinct... content") reads as something to
  measure and record, not a property to force; a retry loop would also need an arbitrary cutoff (how
  many attempts before giving up) that recording-only avoids entirely. Also displaced: giving
  `SelectionDecision.mutation_operator` a per-parent mapping instead of one shared field —
  `RandomEligibleSelection` only ever chooses at most one parent per epoch today, so a single field
  already matches its own shape; a collection would be scope built for a Slice G policy that doesn't
  exist yet.

- **Verification:** 9 new tests (33 total in the file): each discrete operator's guaranteed change;
  every operator's registry name matching its own returned name; price and temperature staying
  bounded; determinism given a fixed seed, across all seven operators; a nested-field-preservation
  check against the `content.update` merge semantics; a per-event seed-uniqueness check (the second
  bug above, guarded so it cannot silently regress); a full population=10/epochs=20 run's audit trail
  checked for completeness (every `simulation_mutation` event carries a known operator, a nonempty
  seed, a parent id, a dict of changed fields, and a boolean distinctness flag) and for at least one
  real operator actually firing and actually producing distinct content through the live pipeline,
  not just in isolation. A pre-existing F1 test (`test_population_grows_through_the_real_reproduction
  _path`) asserted every child's `genome_hash` equals its parent's — true only because `no_op` was
  the sole operator `RandomEligibleSelection` could ever choose; now false in general, so the
  assertion was removed from that test and its actually-still-true claim (real funding, a real row)
  is what remains there, with hash-collapse behaviour covered by the new audit-based tests instead.
  Four teeth-checks, each confirmed to fail for the stated reason and restored verbatim: the
  discrete-operator exclusion removed, the dispatch reverted to a hardcoded `no_op`, the mutation
  audit-recording call skipped, and the per-event seed reverted to the bare `master_seed`. Full suite
  green; golden run unaffected (hash unchanged at 38); `ruff check .` and
  `scripts/check_docs_facts.py` both clean.

- Next: chaos drills (§28) and full manifest richness (Slice F5) close out Slice F, then Slice G's
  remaining `SelectionPolicy` implementations and Slice H's pre-registered Phase 3 comparisons.

## ADR-075: Chaos drills as repeatable scenarios, two reframed one layer up from their literal wording (Slice F, part 4)

- **Status:** Accepted; new `src/mitosis/simulation/chaos.py`; `runner.run()` gains an `epoch_hook`
  parameter; 9 new tests in `tests/test_simulation.py` (42 total)
- **Spec ref:** §28 Phase 2 ("chaos drills are part of the suite: kill 30% of Cells mid-epoch,
  corrupt a shared module, crash mid-settlement — conservation must hold and the population must
  recover"); implementation brief's fuller five-drill list, which this slice follows for specificity

- **One new seam, shared by every drill that needs to fire mid-run:** `runner.run()` gains
  `epoch_hook: Callable[[conn, epoch], None] | None`, called once per epoch after that epoch's own
  processing already completed — so a drill starts from a normal, consistent state rather than an
  in-flight one, and `runner.py` gets exactly one addition regardless of how many drills exist. A
  drill that needs to intercept one call *inside* an epoch (the crash drill, below) uses a different,
  already-existing seam instead — `MarketEnvironment` — rather than stretching the epoch-hook shape
  to fit something it isn't.

- **Two of the five drills needed reframing, and this ADR states the reasoning rather than silently
  substituting something else:**

  - **"Corrupt or withdraw one shared capability/module"** has no module/tool-use surface to target:
    `SimulationPolicyProvider` decides from genome content alone (`policy.py`'s own docstring on
    why). The one genuinely shared, colony-wide capability this simulator actually depends on is the
    `auto_promotion` autonomy flag `run()` enables at setup (ADR-071/072) — `WithdrawCapabilityDrill`
    disables it mid-run. This is a real capability loss with real downstream consequences (grants stop
    auto-approving), not a stand-in for a mechanism that doesn't exist yet.
  - **"Crash at reserve, execute, and settlement boundaries"** targets the *experiment* lifecycle's
    own three-phase shape (start / evaluate / conclude+record-revenue) rather than the deeper
    money-reservation FSM inside `gateway.py`. That FSM's crash safety is Charter C6's job, already
    exhaustively verified by a provider-agnostic stateful machine
    (`tests/test_charter_properties.py`) independent of any live population — re-proving individual
    FSM transitions here would duplicate that coverage, not add to it. What is genuinely new and
    untested elsewhere is whether a full simulation run's *own* state (population, audit trail,
    manifest) survives one call failing mid-flight. `CrashingEnvironment` wraps `evaluate` — the one
    experiment-lifecycle call the simulator drives directly — to raise exactly once, at a chosen
    epoch. `start_from_grant` ("reserve") and `conclude`/`record_revenue` ("settlement") are direct
    calls to kernel functions with no injectable seam today; adding one solely so a drill could target
    them would be speculative surface for no other caller — the same reasoning ADR-073 already used to
    reject an `EnvironmentRole` enum and a `validation`-consulting selection policy nothing needs yet.

- **The fault-injection classes are callables/decorators, not closures with bolted-on attributes.**
  `KillFractionDrill`/`WithdrawCapabilityDrill` implement `__call__(conn, epoch)`, matching
  `epoch_hook`'s type exactly, with `.reports` as a real instance attribute rather than a function
  object with a monkeypatched one. `CrashingEnvironment` implements the full `MarketEnvironment`
  Protocol and delegates to the wrapped environment for everything except one `evaluate` call —
  matching the pattern this package already uses for injectable seams (`SelectionPolicy`,
  `MarketEnvironment` itself) rather than introducing a new shape.

- **A wrong assumption, corrected before it shipped:** the plan for "duplicate and out-of-order
  events" assumed a premature/out-of-order operation (funding a Cell before its birth is visible)
  would be rejected. Checking rather than assuming: `ledger` accounts are plain strings, not a
  foreign key into `cells` (confirmed by reading `scheduler.eligible_cells`, which starts from `SELECT
  ... FROM cells` and only *then* checks each real row's balance) — so `_fund_scheduler_eligibility`
  for a not-yet-existing cell_id neither corrupts anything nor raises; it parks a balance that
  `eligible_cells` can never reach until a Cell with that same id actually exists, at which point the
  same already-posted entries become that Cell's real balance by construction. The test asserts what
  is actually true (inert and unreachable, conservation intact) rather than a rejection that doesn't
  happen. Duplicate delivery, by contrast, is a direct, already-correct property:
  `_fund_scheduler_eligibility` called twice with the same key is a verified no-op — the raw kernel
  event queue's own redelivery safety is Charter C6's job; this proves the simulator's own
  idempotency-keyed call site is safe under redelivery, which is the layer this slice can actually
  vouch for.

- **The regime-shift drill reuses F2's mechanism at full-economy scale rather than building a new
  one.** ADR-073's own tests already prove the shift changes environment *outcomes* in isolation; this
  drill runs the standard founder population (prices 400/450/500, `runner._founder_genome`) across
  the shift boundary and shows the *aggregate colony* pays for it: sales in the ten post-shift epochs
  measured under 10% of the ten pre-shift epochs' total at a fixed seed (33 vs 2, empirically) — not a
  marginal wobble, exactly what "invalidates the currently dominant strategy" means for a real
  population rather than one hand-picked price.

- **What it displaced:** three separately-injectable boundaries for the crash drill (considered and
  rejected above); a CLI verb per drill, considered and rejected because the brief's own CLI section
  only asks for `mitosis simulate` — the 500-Cell/10,000-epoch acceptance run that would actually
  *use* the drills at scale is explicitly F5's job (SPEC.md's own Phase 2 acceptance criteria list
  "recovery from chaos drills" as part of that larger run, not a standalone CLI surface).

- **Verification:** 9 new tests: each drill's real effect (coroner reports for the kill count, not
  just its own self-reported total; the autonomy flag actually flipped; one recorded failure and the
  interrupted experiment concluding on a later epoch, not just "the run didn't crash"; the aggregate
  sales drop; duplicate-call idempotency; out-of-order inertness); the shared post-drill invariant
  helper; and two explicit determinism-under-a-drill checks (one epoch-hook-shaped drill, one
  environment-wrapper-shaped drill — the two different injection mechanisms this slice introduces,
  not the same one twice). Five teeth-checks, each confirmed to fail for the stated reason and
  restored verbatim: the kill call, the withdraw-capability call, the crash-injection condition, the
  `epoch_hook` call site itself, and (breaking pre-existing F1 code on purpose to confirm the new
  test's own teeth) the funding idempotency key. Full suite green; golden run unaffected (hash
  unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: full manifest richness and the two acceptance-scale configurations (Slice F5) close out
  Slice F, then Slice G's remaining `SelectionPolicy` implementations and Slice H's pre-registered
  Phase 3 comparisons.

## ADR-076: Manifest richness, a CI-scale acceptance scenario, and a founding bug the acceptance criteria's own scale would have hit (Slice F, part 5a)

- **Status:** Accepted; `manifest.py` gains `distinct_genomes`/`environment_events`/`config_hash`;
  `runner._found_population` batches across the birth-rate cap; one consolidated acceptance test;
  6 new tests in `tests/test_simulation.py` (48 total)
- **Spec ref:** brief's "CLI and artifacts" section (manifest content) and "Phase 2 acceptance test"
  section (the checklist this slice's new test proves in one place); SPEC.md §9.2 (`max_births_per_
  epoch`, the cap the founding bug ran into)

- **Manifest richness, each field tied to something that only now exists to measure.**
  `manifest.py`'s own F1 docstring named this explicitly: diversity and regime-shift bookkeeping
  needed a second environment family and a real mutation set before either was a meaningful
  measurement, and F2-F4 built both. `EpochRecord.distinct_genomes` counts distinct `genome_hash`
  values among living Cells — a genome hash *is* a Cell's full strategy under ADR-018's content
  addressing, so this counts distinct strategies, not an ad hoc diversity proxy.
  `EpochRecord.environment_events` carries any regime-shift strings that fired that epoch, so
  "regime-shift recovery" (brief) is visible directly on the retained manifest: a reader sees which
  epoch carried a shift and reads the following epochs' own `living_cells`/`sales`/`distinct_genomes`
  to see recovery, rather than the manifest computing a "recovered" verdict on the colony's behalf.
  `RunManifest.config_hash` is a SHA-256 over the run's actual configuration (scenario, seed, epochs,
  population — not `output_path`, a write destination rather than configuration), so two manifests
  claiming the same configuration can be checked, not only asserted.

- **A bug the acceptance criteria's own scale would have hit, found by trying to reach that scale.**
  Validating the manifest changes at a moderate scale (population=50) surfaced an unhandled
  `BirthRateExceededError`: `_found_population` created every founder before any epoch advanced, and
  §9.2's `max_births_per_epoch` (default 25) does not distinguish a founder from a reproduced child.
  Nothing in F1-F4's own tests (all population <= 30, and the one population=20 test that comes
  closest sits under the 25 cap) exercised this — the bug was invisible until something asked for
  more founders than one kernel epoch allows, which the brief's own >= 500 Cell acceptance scale
  unavoidably does. Not a case for loosening the cap (§9.1: "unrestricted reproduction... capital
  alone is not sufficient population control" — the same reasoning ADR-071 already used to refuse
  loosening a different cap): `_found_population` now founds in batches of `max_births_per_epoch`,
  advancing the clock between batches exactly as `run()`'s own main loop does. This shifts nothing
  the simulation's own logic reads — `_run_one_epoch`'s `epoch` parameter (RNG seeding, the
  regime-shift comparison) is the simulator's own loop counter, never the kernel's `clock.
  current_epoch` — so founding needing several kernel epochs before the main loop's epoch 0 starts
  is an internal offset, not a change in simulated behaviour.

- **The first version of the regression test passed for the wrong reason, caught before it shipped.**
  Calling `_found_population` directly (bypassing `run()`'s own setup) left the clock never
  "anchored" (`clock.initialize_if_absent`/`scheduler.configure_epochs_if_absent`, both part of
  `run()`'s setup, not called), so `clock.current_epoch` stayed 0 regardless of how many times
  `clock.advance` was called — every birth still landed in "epoch 0," and the fix's own regression
  test failed with the *unbatched* error, for a reason unrelated to the fix. Rewritten to go through
  `run()` itself, which does anchor the clock in the right order — the same category of trap this
  repo's testing conventions warn about (a fixture unable to distinguish the outcome it means to
  check), caught by reading the failure's own message rather than its pass/fail alone.

- **One consolidated acceptance test, not scattered assertions with no single place naming the
  checklist.** `test_phase_2_ci_scale_acceptance_scenario` runs one scenario (population=15,
  epochs=30, one chaos drill) and asserts every bullet in the brief's own Phase 2 acceptance list by
  name, each against a specific, checkable claim: zero USD_REAL movement, deterministic replay,
  carrying capacity never exceeded, conservation intact, drill recovery, more than one occupied
  niche (`distinct_genomes > 1`), and a regime shift's events actually present. "No duplicate
  economic effects under event redelivery" is referenced rather than re-proven here — already
  covered directly by `test_duplicate_funding_call_is_a_safe_noop` (ADR-075) — to keep this test
  about the checklist as a whole rather than duplicating another test's own assertions.

- **What this slice does not close: the second acceptance-scale configuration.** The brief's own
  accommodation ("if runtime makes 500x10,000 unsuitable for ordinary CI, keep a small deterministic
  CI scenario, and a separately documented benchmark command whose result artifact is retained") is
  not a license to skip running it — it is a license to run it *outside* ordinary CI. A moderate-scale
  validation (population=50, epochs=200) run to confirm the founding-batch fix at a scale that
  actually exceeds the birth-rate cap completed in 23m47s (604s user + 480s system CPU — roughly 0.14
  epochs/sec once population reached `max_active_cells`=100 and stayed there), retained at
  `docs/benchmarks/2026-09-05-founding-fix-validation-p50-e200.json`. That throughput is nearly 40x
  slower than ADR-072's own smaller population 20->70/50-epoch benchmark (~5.6 epochs/sec) — context
  assembly's own per-wake cost scales with population and history, the same concern the original
  Slice F plan flagged before any code existed. Extrapolating this run's own rate to the brief's
  >= 500-Cell/>= 10,000-epoch acceptance scale (five times the population, fifty times the epochs,
  and no reason to expect a *lower* per-epoch cost at that size) points to a multi-hour, quite
  possibly multi-day run on this hardware — exactly the case the brief's own accommodation describes,
  not a rough guess. The command is documented (`mitosis simulate --population 500 --epochs 10000
  --seed <n> --output <path>`, see `docs/benchmarks/README.md`) and the mechanism it depends on
  (founding above the birth-rate cap) is now proven correct; actually running it to completion and
  retaining its manifest is deferred to a following slice as an explicitly kicked-off, unattended job
  sized in hours or days, rather than blocking this already-complete,
  independently-verified manifest/acceptance-test work on it.

- **Verification:** 6 new tests (48 total): the founding-batch fix (via `run()`, not the private
  function directly, per the trap above); the diversity time series' structural bound *and* that it
  is not merely "always equals living_cells" (a non-deduplicating count would also satisfy a bare
  bound); regime-shift events appearing only at the scheduled epoch; `config_hash`'s stability and
  its sensitivity to each real configuration field, confirmed to exclude `output_path`; the
  consolidated CI-scale acceptance scenario. Four teeth-checks (deduplication removed, the manifest
  event-append removed, `population` dropped from the config hash, the founding batch removed),
  each confirmed to fail for the stated reason and restored verbatim — the founding-batch teeth-check
  is also the clearest demonstration of the trap above: the *first* attempt at it (before the test
  was rewritten to use `run()`) failed for the pre-fix reason too, which is exactly why that version
  of the test could not be trusted, fix or no fix. Full suite green (1286, up from 1281 — 5 new
  simulation tests plus one flaky Hypothesis deadline elsewhere, confirmed environmental by an
  isolated rerun passing cleanly with the same code, not a regression: a concurrent CPU-heavy
  benchmark validation was running on this machine at the same time); golden run unaffected (hash
  unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: the >= 500 Cell/>= 10,000 epoch acceptance benchmark, run to completion with its manifest
  retained, closes out Slice F; then Slice G's remaining `SelectionPolicy` implementations and
  Slice H's pre-registered Phase 3 comparisons.

## ADR-077: A run record that never named its own selection policy, and founder concentration as a real time series (Slice G, part 0)

- **Status:** Accepted; migration 0036 adds `simulation_runs.selection_policy_name/_version`;
  `runner._record_run_start` actually reads them from its own `selection` parameter; `lineage.py`
  gains `founder_concentration()`; `EpochRecord`/`RunManifest` gain the corresponding fields; 5 new
  tests in `tests/test_simulation.py` (50 total)
- **Spec ref:** implementation brief's Slice G ("niche diversity and founder concentration are
  measured over time") and its own "Current disconnected components" framing, which this whole
  slice addresses across several sub-slices; this one is the observability foundation the rest is
  built on

- **Context:** planning Slice G (closing the evolutionary decision loop — replaceable, recorded
  `SelectionPolicy` implementations behind the seam F1 built) surfaced a real bug before any new
  policy existed to expose it: `runner._record_run_start` has taken a `selection: SelectionPolicy`
  parameter since F1, but never read `.name`/`.version` from it — both `simulation_runs` and
  `RunManifest`'s `policy_name`/`policy_version` fields were, and remain, the **Cell** policy's
  identity (`SIMULATION_PROVIDER`/`POLICY_VERSION`, what a mock Cell proposes) — a different
  decision entirely from *which Cell reproduces*, which is `SelectionPolicy`'s own job. For a slice
  whose entire purpose is comparing selection policies against each other, an operator could not
  previously tell which one a run used except by reading a per-epoch `simulation_selection_decision`
  audit event. Two new nullable columns (no rebuild — a plain `ADD COLUMN` with no CHECK/NOT
  NULL/computed default, the same shape migration 0033's `repair_model_call_id` already used) and
  `_record_run_start` finally uses its own parameter.

- **Founder concentration joins `distinct_genomes` as a real per-epoch time series, not a fact
  buried in one policy's own text.** New `lineage.founder_concentration(conn) -> tuple[str | None,
  float]` — one `GROUP BY` over the already-denormalized `cells.founder_cell_id`, ties broken by
  `founder_cell_id` itself for determinism (arbitrary as a value, but stable given a seeded run's
  own id sequence). This needs to be comparable *across* policies over time — is `StagedFundingSelection`
  actually less founder-concentrated than `RandomEligibleSelection` over the same seed, a genuinely
  Phase-3-shaped question — which a free-text reason inside whichever policy happens to be running
  could never answer. `EpochRecord` gains `founder_concentration`/`dominant_founder_cell_id`,
  computed in `_run_one_epoch` the same way `distinct_genomes` already is, regardless of which
  policy is active.

- **A teeth-check that initially passed for the wrong reason, caught before it shipped.** The first
  attempt at proving `founder_concentration`'s ordering mattered removed the `ORDER BY n DESC`
  clause entirely, leaving `ORDER BY founder_cell_id` alone — this happened to still name the
  correct dominant founder across the one run it was tried against, purely because that run's
  randomly-generated UUIDs coincidentally sorted the dominant founder first. A mutation that *always*
  fails regardless of id randomness needed a sharper edit: flipping `DESC` to `ASC` picks the
  *smallest* count deterministically, which can never be the two-member dominant lineage against nine
  one-member lineages — confirmed to fail across three independent runs with fresh random ids each
  time, not just once. The same category of trap this repo's own conventions warn about (a mutation
  that happens not to move the observed outcome), just discovered via test-fixture randomness this
  time rather than a fixture unable to distinguish two outcomes at all.

- **Verification:** 5 new tests: the run-record fix (a minimal name/version-only `SelectionPolicy`
  wrapper — no second real policy exists yet at this sub-slice — proves `simulation_runs` and the
  manifest both read from the actual object, not the Cell-policy constants); `founder_concentration`'s
  correctness on a constructed ten-founder fixture (population raised to ten for the same
  `max_lineage_population_fraction` reason `test_population_grows_through_the_real_reproduction_path`
  already documents — a single child exceeds the 0.20 cap at population <=2); founder concentration
  as a real bounded time series across a full run. Two teeth-checks, the second requiring a
  do-over as described above, both confirmed to fail for the stated reason and restored verbatim.
  Full suite green; golden run unaffected (hash unchanged at 38 — no existing scenario touched);
  `ruff check .` and `scripts/check_docs_facts.py` both clean (README's migration count updated
  35 -> 36).

- Next: G1 — `candidate.py`'s simulator-native gates/axes/`dominates()`, the full `SelectionDecision`
  schema expansion, and `posteriors.sample()`, per the approved Slice G plan
  (`docs/DECISIONS.md`'s own forward reference here now points to the plan file's sub-slice
  sequence: G1 candidate.py + schema, G2 SingleLeaderboardSelection, G3 ParetoSelection, G4
  MapElitesSelection, G5 StagedFundingSelection + Thompson sampling + the validation consumer, G6
  cross-policy acceptance harness).

## ADR-078: Simulator-native fitness dimensions, the full decision-record schema, and a Thompson-sampling primitive (Slice G, part 1)

- **Status:** Accepted; new `src/mitosis/simulation/candidate.py`; `SelectionDecision` gains nine new
  fields (all defaulted); `posteriors.py` gains `sample()`; `RandomEligibleSelection` and `runner.py`
  updated to use the new fields honestly; 21 new tests across `tests/test_simulation_candidate.py`
  (new, 16), `tests/test_posteriors.py` (3), and `tests/test_simulation.py` (2) — 80 total tests
  across those three files
- **Spec ref:** the approved Slice G plan's central finding (see ADR-077); SPEC.md §10.2/§13.2 (gate-
  then-frontier, never a scalar), §12.1-§12.3 (niches, MAP-Elites, Thompson sampling), §0.3
  (`economic_potential`'s structural refusal)

- **What shipped, following the plan directly:** `candidate.py`'s simulator-native gates
  (`not_quarantined`, real; `reproducibility`, a genuine canonical measurement built from
  cross-Cell replication of a revenue-producing result — see ADR-077's central finding for why the
  kernel's own nine dimensions would be degenerate here) and axes (`structural_novelty`, reused from
  `novelty.descriptors()` by direct call since it is genome-content-only; `realized_net_revenue`;
  `experiment_success_rate`; `economic_potential`, permanently unmeasurable even here — §0.3's
  refusal is structural, not a data gap, and `SimulationPolicyProvider` has no upside field to even
  decline). `dominates()` and `pareto_frontier()` reimplement `selection.py`'s exact rule over the
  new `SimCandidate` shape (a different candidate, not a different rule). `niche_elite()` gives
  `novelty.py`'s archive the elite-per-niche rule its own docstring says it deliberately lacks:
  highest `realized_net_revenue` among evaluated occupants, uniform-random exploration among
  unevaluated ones, `None` for an empty niche. `posteriors.sample()` adds one Thompson-sampling draw
  (`rng.betavariate(alpha, beta)`) without disturbing the module's own stated boundary — comparing
  niches' draws is still absent, reserved for `StagedFundingSelection` (G5).

- **`SelectionDecision` gains nine new fields, all defaulted, so no existing policy or test needed to
  change shape.** `gate_results`, `measured_dimensions`/`unmeasured_dimensions`,
  `pareto_front_cell_ids`, `niches: tuple[NicheStanding, ...]`, `parent_mutation_operators`/
  `parent_child_budgets` (per-parent overrides — ADR-074 logged deferring exactly this
  generalization as "scope built for a Slice G policy that doesn't exist yet"; `RandomEligibleSelection`
  reproduces at most one parent per epoch and never populates them), `intended_experiment`.
  `RandomEligibleSelection` reports every known simulator-native dimension name as
  `unmeasured_dimensions` — an explicit "nothing consulted," not a silently-empty tuple — matching
  its own F1 docstring's already-established posture for its original, smaller field set.

- **`runner.py`'s reproduction loop now consults the per-parent overrides, with a fallback that
  keeps every prior policy's behaviour byte-identical.** `operator_overrides.get(parent_id,
  decision.mutation_operator)` and the equivalent for budget — `RandomEligibleSelection` never
  populates the override tuples, so this is a no-op for every run before this slice.

- **A wrong first attempt to verify the budget override, caught before it shipped.** The first draft
  of the override test asserted the child's *current* USD_SIM cash balance equals the overridden
  budget — wrong, because a child born early in a 20-epoch run has had further epochs to earn its
  own revenue since, so a live balance is not the fact the test meant to check. Fixed to query the
  `cell_reproduction_funding` transaction itself (the birth-time credit, `lineage.py`'s own
  transaction type — distinct from founding's `cell_birth_funding`), which is fixed at birth and
  answers the actual question the test asks.

- **Verification:** structural (`SimCandidate`/`Axis`/`GateResult` carry no
  `score`/`rank`/`weight`/`fitness`/`priority`/`total`, the same guarantee `test_selection.py`'s own
  equivalent test proves for the kernel's shapes); every gate/axis function unit-tested on
  constructed fixtures (quarantine, the reproducibility threshold and its reject/pass split,
  novelty's founder-abstention, revenue-minus-spend, success rate, the permanent
  `economic_potential` abstention); `dominates()`'s strict-improvement and disjoint-measured-axes
  cases; `pareto_frontier()`'s gate-filtering; `niche_elite()`'s evaluated-vs-exploratory split;
  `posteriors.sample()`'s statistical convergence to `posterior_mean`, its determinism given a fixed
  `rng`, and that different seeds actually produce different draws; the decision-record honesty
  field; the per-parent override mechanism through a live run. Seven teeth-checks (the
  `HIGHER_IS_BETTER` sense, the reproducibility threshold, the niche-elite sort direction, the
  Thompson-sample argument order, the operator override, the budget override, the honesty-field
  population), each confirmed to fail for the stated reason and restored verbatim. Full suite
  green; golden run unaffected (hash unchanged at 38 — no existing scenario touched); `ruff
  check .` and `scripts/check_docs_facts.py` both clean.

- Next: G2 — `SingleLeaderboardSelection`, the smallest new policy (no gates, no niches), proving the
  CLI/factory wiring pattern before G3 (`ParetoSelection`), G4 (`MapElitesSelection`), and G5
  (`StagedFundingSelection` + the `EnvironmentSuite.validation` consumer) build on it.

## ADR-079: The second selection policy, and the CLI/factory wiring pattern the remaining three will reuse (Slice G, part 2)

- **Status:** Accepted; new `SingleLeaderboardSelection`, `build_selection_policy()`, and
  `UnknownSelectionPolicyError` in `selection_policy.py`; `cli.py` gains `simulate
  --selection-policy`; 4 new tests in `tests/test_simulation.py` (84 total simulation-area tests)
- **Spec ref:** implementation brief's Slice G policy #2 ("a single-leaderboard baseline with an
  explicitly declared scalar metric, used only as an experimental control"); SPEC.md §10.2/§13.2
  (the production kernel's own refusal of exactly this shape)

- **What shipped:** `SingleLeaderboardSelection` ranks eligible Cells by one named scalar
  (`scalar_metric = "realized_net_revenue_minor_units"`, a class attribute so the decision record
  states exactly what it collapsed fitness into) and reproduces the single top-ranked Cell — runs no
  gates at all, and its `reason` states plainly that this is the shape §10.2/§13.2 forbid for the
  production kernel, built only as a Slice H comparator. `build_selection_policy(name)` mirrors
  `environment.build_environment`'s existing pattern exactly, so `cli.py`'s new `--selection-policy`
  flag (`choices=[...]`, argparse validating at the CLI boundary, matching `--environment`'s own
  precedent) needed no new wiring idiom.

- **Unmeasured is excluded from the ranking, not treated as a floor value.** A Cell with a concluded,
  zero-revenue experiment (a *measured* zero) must outrank a Cell with no concluded experiment at
  all (unmeasured) — the sort key is `(not has_evidence, -value_or_0, generation, created_at_utc,
  cell_id)`, so "has proven nothing yet" can never tie with, let alone beat, a proven result. This is
  the same distinction this codebase draws everywhere else (`Axis.value is None` is never "zero"),
  applied to a policy that — unlike every gate/axis in `candidate.py` — needs one total order over
  every eligible Cell rather than permission to abstain.

- **A teeth-check that initially passed for the wrong reason, caught before it shipped.** The first
  version of the "unmeasured ranks last" test created the proven-zero Cell first and the unmeasured
  one second; removing the `not has_evidence` term from the sort key still picked the right Cell,
  because both cells' primary key collapsed to the same value (`0.0`) and the *secondary* tie-break
  (`created_at_utc` ascending) happened to favor the older, proven-zero Cell anyway — the same
  category of trap ADR-077 already hit once this slice (a mutation that doesn't move the observed
  outcome). Fixed by creating the unmeasured Cell *first*: now a dropped "unmeasured ranks last" rule
  would make the tie-break favor the wrong Cell unambiguously, regardless of generated-id ordering.

- **Verification:** the highest-revenue Cell chosen correctly; the unmeasured-ranks-last property (via
  the corrected fixture above); `build_selection_policy`'s construction and rejection of an unknown
  name; a CLI end-to-end run naming the policy it used in its own manifest. Four teeth-checks (the
  ranking direction, the unmeasured-exclusion term, the factory's silent-fallback temptation, the CLI
  wiring), each confirmed to fail for the stated reason and restored verbatim — the second entry in
  this ADR's own list is the fix for the first teeth-check's own false pass, not a fifth independent
  check. Full suite green; golden run unaffected (hash unchanged at 38); `ruff check .` and
  `scripts/check_docs_facts.py` both clean.

- Next: G3 — `ParetoSelection`, gating on `not_quarantined`/`reproducibility` and taking the Pareto
  front over `structural_novelty`/`realized_net_revenue`/`experiment_success_rate` — reproducing from
  every surviving front member, not a single winner, which is what actually demonstrates §10.2's
  "portfolio, not a scalar" framing against this slice's own `SingleLeaderboardSelection` comparator.

## ADR-080: Pareto selection, reproducing the whole front — and a gate found to be structurally unreachable through this pipeline (Slice G, part 3)

- **Status:** Accepted; new `ParetoSelection` in `selection_policy.py`; `cli.py`'s `--selection-policy`
  gains `pareto`; 4 new tests in `tests/test_simulation.py` (88 total simulation-area tests)
- **Spec ref:** implementation brief's Slice G policy #3 ("Pareto selection without MAP-Elites");
  SPEC.md §10.2 ("select from a Pareto frontier... do not rely on a single weighted scalar")

- **What shipped:** `ParetoSelection` gates every eligible Cell on `not_quarantined`/`reproducibility`
  (`candidate.py`, ADR-078), takes `candidate.pareto_frontier()` over
  `structural_novelty`/`realized_net_revenue`/`experiment_success_rate` (`economic_potential` stays
  unmeasurable), and reproduces from **every** Cell on the resulting front — not one winner. That
  last point is the entire content of the comparison this policy exists to set up against
  `SingleLeaderboardSelection` (ADR-079): §10.2's "portfolio, not a scalar" only means something if
  the portfolio is actually funded, not computed and then collapsed to one pick anyway. Each front
  member draws its own mutation operator via `parent_mutation_operators` (ADR-078's per-parent
  override fields, unused until this policy); the shared `mutation_operator` field is set to
  `NO_OP_OPERATOR` and documented as vestigial for this policy, rather than a drawn value that would
  imply it carries a real decision nothing actually reads.

- **A gate found to be structurally unreachable through this pipeline, discovered by testing it, not
  assumed.** `candidate._not_quarantined` is correctly implemented and independently proven
  (ADR-078's `test_not_quarantined_gate_passes_alive_and_rejects_quarantined`) — but every policy,
  `ParetoSelection` included, builds its candidates only from `_eligible_parents()`'s own output,
  which already filters to `CellStatus.ALIVE` before `candidate.cell_candidate()` is ever called. A
  quarantined Cell therefore never reaches gate evaluation at all in this pipeline: it is excluded at
  the *eligibility* stage, not the *gate* stage, so `not_quarantined`'s `REJECTED` branch cannot fire
  through `ParetoSelection.decide()` regardless of colony state. The gate is kept — it is correct,
  cheap, and a module built for reuse by `MapElitesSelection`/`StagedFundingSelection` next shouldn't
  assume every future caller pre-filters the same way — but the first version of this ADR's own test
  asserted a `REJECTED` gate result that can never occur here and failed; rewritten to assert the
  accurate, narrower fact (quarantined Cells appear in neither `eligible_cell_ids` nor
  `gate_results` at all), rather than a plausible-sounding claim about a code path this pipeline
  cannot reach.

- **Verification:** a genuine three-Cell trade-off fixture (higher revenue but a lower success rate
  vs. lower revenue but a perfect one — engineered by holding `structural_novelty` tied across all
  three via identical genome content, so only the two controlled axes discriminate) proving mutual
  non-domination puts both on the front while a strictly-dominated third is excluded; the corrected
  quarantine test above; every chosen parent receiving its own operator entry; a CLI end-to-end run.
  Three teeth-checks (truncating the front to one winner, dropping the per-parent operator
  assignments, renaming the factory's branch), each confirmed to fail for the stated reason and
  restored verbatim. Full suite green; golden run unaffected (hash unchanged at 38); `ruff check .`
  and `scripts/check_docs_facts.py` both clean.

- Next: G4 — `MapElitesSelection`, giving `novelty.py`'s archive the elite-per-niche rule
  `candidate.niche_elite()` already built in G1 its first real caller — then G5
  (`StagedFundingSelection` + Thompson sampling + the `EnvironmentSuite.validation` consumer) and G6
  (the cross-policy acceptance harness).

## ADR-081: MAP-Elites selection, one elite per occupied niche (Slice G, part 4)

- **Status:** Accepted; new `MapElitesSelection` in `selection_policy.py`; `cli.py`'s
  `--selection-policy` gains `map_elites`; 4 new tests in `tests/test_simulation.py` (92 total
  simulation-area tests: 64 + 16 + 12 across `test_simulation.py`/`test_simulation_candidate.py`/
  `test_posteriors.py`)
- **Spec ref:** implementation brief's Slice G policy #4 ("MAP-Elites / quality-diversity");
  SPEC.md §12.1/§12.2 (the novelty archive, a derived view over niche coordinates)

- **What shipped:** `MapElitesSelection` calls `novelty.archive()` directly (unmodified — niches are
  still a derived view, never a stored table) and, for every occupied niche, calls
  `candidate.niche_elite()` (built in G1, its first real caller) to pick that niche's elite: highest
  `realized_net_revenue` among evaluated occupants, or a uniform-random pick among unevaluated ones
  when nothing has evidence yet — an explicit "no evidence, explore" rule, never a silent default.
  Every occupied niche reproduces each epoch (MAP-Elites' classical behaviour — keep re-trying every
  niche, not allocate a scarce budget across them; that comes in G5 via Thompson sampling). Each
  niche's real §12.3 posterior (`posteriors.posteriors()`) is recorded on its `NicheStanding`
  regardless of whether this policy uses it — `thompson_sample` stays `None` because this policy
  never draws one, not because the posterior is unavailable. A new `_living_cell_ids_in_niche` helper
  reuses `novelty.py`'s own broader "living" definition (`status != DEAD`) rather than
  `_eligible_parents`'s narrower alive-with-cash filter, deliberately: niche *occupancy* is a colony
  fact, reproduction *eligibility* is a separate one the decision record already carries.

- **A coincidental-pass test found and fixed before this shipped, not after.** The first version of
  `test_map_elites_selection_records_the_real_posterior_even_though_unused` asserted only that a
  niche with no rung-7 promotions ever issued gets the uninformative Beta(1,1) prior
  (`alpha=beta=1.0`, `trials=0`) — true, but numerically identical to what
  `posterior_by_coordinate.get(niche.coordinate)` returns when the lookup is silently broken and
  falls back to the hardcoded default (`posteriors.PRIOR_ALPHA`/`PRIOR_BETA`). A zero-trial real
  posterior and a missing one are indistinguishable by value under `_posterior`'s own formula
  (`alpha = PRIOR_ALPHA + conversions`, `beta = PRIOR_BETA + (trials - conversions)`), so this
  assertion could not tell a working lookup from a broken one. Rewritten to monkeypatch
  `posteriors.posteriors()` to return a real, non-prior posterior (`trials=5, conversions=2,
  alpha=3.0, beta=4.0`) for the fixture's own niche coordinate, and assert those exact values survive
  into the decision record — a lookup that always misses now produces a visibly wrong result instead
  of a coincidentally correct one. Caught by the same discipline ADR-077/ADR-079 already needed twice
  this slice: distrust a teeth-check-shaped assertion that a broken implementation could also satisfy.

- **Verification:** a three-genome fixture forcing two distinct niches (one "adjacent" to a shared
  market, one "radical" against a fresh one) plus an unbinned founder, proving each occupied niche
  funds its own elite and the founder funds nothing; the corrected posterior-wiring test above; a
  20-epoch live run; a CLI end-to-end run. Three teeth-checks — breaking the posterior lookup
  (`posterior_by_coordinate.get(...)` forced to `None`), breaking the eligibility threading into
  `candidate.niche_elite()` (forced to `frozenset()`, which starved every niche of an elite), and
  renaming the factory's dispatch branch — each confirmed to fail for the stated reason and restored
  verbatim. Full suite green (1322 total, up from 1318); golden run unaffected (hash unchanged at
  38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: G5 — `StagedFundingSelection`, composing `ParetoSelection`'s gates with `MapElitesSelection`'s
  niche/elite rule, adding a `validation_probe` gate and a Thompson-sampled draw per niche
  (`posteriors.sample()`, built in G1 but still uncalled) to fund only the top-K sampled niches per
  epoch — then G6's cross-policy acceptance harness and Slice H.

## ADR-082: Staged funding — the composed policy, and `EnvironmentSuite.validation`'s first real consumer (Slice G, part 5)

- **Status:** Accepted; new `StagedFundingSelection` in `selection_policy.py`; new
  `candidate.validation_probe`; `cli.py` gains `--selection-policy staged_funding` and
  `--validation-environment`; 7 new tests in `tests/test_simulation.py` (99 total simulation-area
  tests: 71 + 16 + 12 across `test_simulation.py`/`test_simulation_candidate.py`/`test_posteriors.py`)
- **Spec ref:** implementation brief's Slice G policy #5 ("the intended policy," composing the
  earlier four); SPEC.md §8.1 (`validation` "influences capital allocation, partially hidden")

- **What shipped:** `StagedFundingSelection` composes every earlier Slice G sub-slice rather than
  adding a sixth independent mechanism. It gates every eligible Cell on `ParetoSelection`'s own two
  dimensions (`not_quarantined`, `reproducibility`) before a gate-survivor can even be considered as
  a niche elite; niches and elites come from `MapElitesSelection`'s own rule
  (`novelty.archive()` + `candidate.niche_elite()`, restricted to gate survivors); each niche gets
  one real Thompson-sampled draw (`posteriors.sample()`, built in G1, its first real caller), and
  only the top `_STAGED_FUNDING_TOP_K` (3) sampled niches are funded each epoch, each at a budget
  scaling with that niche's own posterior mean (`_staged_child_budget`: `base + round(base * scale *
  mean)`, `scale=1.0` — a niche with the uninformative prior, mean=0.5, the common case, gets 1.5x
  the base child budget). This is the genuinely budget-constrained choice `MapElitesSelection`
  explicitly deferred (ADR-081: "fund every occupied niche," not a scarce allocation).

- **A new gate, composed onto an elite rather than every eligible Cell.** `candidate.validation_probe`
  is `EnvironmentSuite.validation`'s first real consumer (ADR-073 named this a Slice G obligation).
  Unlike `not_quarantined`/`reproducibility`, it runs only against a niche's already-chosen elite
  (probing every eligible Cell would be wasted work for Cells that could never be funded anyway) and
  needs an `environment.MarketEnvironment` — a dependency only `StagedFundingSelection` carries, via
  constructor injection (`StagedFundingSelection(validation=...)`), exactly as the Slice G plan
  specified: `SelectionPolicy.decide()` and `runner._run_one_epoch()` stay byte-identical to every
  other policy's, so `test_the_routine_epoch_loop_never_touches_validation_or_secret_challenge_
  environments`'s existing guarantee keeps holding, unmodified, for this policy and every other one
  alike. `validation=None` (the constructor default, and `build_selection_policy`'s default) makes
  every `validation_probe` report `UNEVALUABLE`, not a silent `PASSED` — "nothing to judge" is a
  different fact from "judged and found no problem," `_reproducibility`'s own posture below its
  evidence threshold. `cmd_simulate`, when `staged_funding` is chosen, defaults
  `--validation-environment` to the *other* family from `--environment` (SPEC.md §8.3's two
  independently shaped families) unless the caller names one explicitly.

- **A shared-constant edit that would have made `ParetoSelection` dishonest if left alone.** Adding
  `validation_probe` to `candidate.SIM_GATE_DIMENSIONS` automatically flows into `_ALL_SIM_DIMENSIONS`
  and therefore into every policy's dynamically-derived `unmeasured_dimensions` tuple — correct for
  `RandomEligibleSelection`/`SingleLeaderboardSelection`/`MapElitesSelection`, which compute that
  field from `_ALL_SIM_DIMENSIONS` at call time. `ParetoSelection`'s own `_PARETO_MEASURED_DIMENSIONS`
  is instead a stored, pre-computed tuple (`_ALL_SIM_DIMENSIONS` minus a literal exclusion list) and
  its `unmeasured_dimensions` was a bare literal (`("economic_potential",)`) — left alone, both would
  have silently started claiming `ParetoSelection` measures `validation_probe`, which it never does
  (it has no validation environment at all). Fixed by excluding `validation_probe` from
  `_PARETO_MEASURED_DIMENSIONS` explicitly and updating the literal to
  `("economic_potential", "validation_probe")`. `StagedFundingSelection`'s own
  `unmeasured_dimensions` is derived from `_ALL_SIM_DIMENSIONS` rather than hardcoded as its own
  complement, precisely so the next dimension `candidate.py` gains doesn't need this policy
  remembered too.

- **Honest scope note, stated plainly rather than left implicit:** the archive can have at most 3
  niches today (only `structural_novelty` ever measures for a simulated genome —
  `buyer_type`/`revenue_recurrence` need counterparty data this simulator never produces, per
  `candidate.py`'s own module docstring), so `_STAGED_FUNDING_TOP_K = 3` cannot yet exclude anything
  by itself in a real run. The cap is forward-looking (those two dimensions are a named, deferred
  FUTURE_BUILD_HOOKS.md item) and its ranking-and-cap logic is still independently verified by
  monkeypatching the constant down to 1 in a dedicated test, rather than skipped as untestable.

- **Verification:** a genome whose only 3 independent tries all failed to convert (`reproducibility`
  REJECTED) proving gate composition excludes it from ever becoming an elite, not merely that gates
  run and get recorded; a stub `MarketEnvironment` that always rejects, proving a training-only
  winner is excluded from funding while still recorded as the niche's real elite; the same fixture
  with `validation=None`, proving `UNEVALUABLE` never excludes; the top-K cap and its ranking
  (monkeypatched to 1 of 2 fundable niches); the budget-scaling formula checked against its own
  literal output, not re-derived; a 20-epoch live run with a real validation environment; a CLI
  end-to-end run proving the "other family" default. Four teeth-checks — dropping the
  validation-rejection filter, bypassing the gate-survivor restriction into `niche_elite`, removing
  the top-K slice, and flattening the budget formula to a constant — each confirmed to fail for the
  stated reason and restored verbatim. Full suite green (1329 total, one unrelated Hypothesis
  deadline flake on `test_charter_ledger_balanced` reproduced as a pass in isolation and on a clean
  re-run of the whole suite — not touched by this slice); golden run unaffected (hash unchanged at
  38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: G6 — the cross-policy acceptance harness (same seed bundle + `EnvironmentSuite` run once with
  `RandomEligibleSelection` and once with `StagedFundingSelection`; a traceability test that every
  `simulation_mutation` audit event's `parent_cell_id` appears in a same-epoch
  `simulation_selection_decision` event's `chosen_parent_cell_ids`; re-running
  `test_the_routine_epoch_loop_never_touches_validation_or_secret_challenge_environments` unmodified)
  — then Slice H's pre-registered Phase 3 comparisons. The >= 500 Cell/>= 10,000 epoch Phase 2
  acceptance benchmark itself remains documented but not yet run to completion (ADR-076).

## ADR-083: The cross-policy acceptance harness, and a validation-choice defect found in ADR-082's own live-run test (Slice G, part 6)

- **Status:** Accepted; no production code changed except one already-restored teeth-check; 5 new
  tests in `tests/test_simulation.py` plus 3 already-committed tests corrected (104 total
  simulation-area tests: 76 + 16 + 12 across `test_simulation.py`/`test_simulation_candidate.py`/
  `test_posteriors.py`)
- **Spec ref:** implementation brief's Slice G acceptance criteria (same seed bundle across
  policies; reproduction traceability; the validation-isolation regression guard)

- **What shipped:** G6 needed no new mechanism — every property the brief asks G6 to verify was
  already produced by earlier sub-slices (`runner._run_one_epoch` has recorded
  `simulation_selection_decision` and `simulation_mutation` audit events since F1/G0;
  `RunManifest.config_hash`/`environment_name`/`selection_policy_name` since ADR-077). G6 is
  therefore purely an acceptance-test suite proving those properties hold under real, live-run
  conditions rather than by code inspection: the same `RunConfig` run once with
  `RandomEligibleSelection` and once with `StagedFundingSelection` (two independent in-memory
  databases, not one shared connection — a second run against the same connection would inherit the
  first run's population and genome history, which is not "the same seed bundle") produces matching
  `config_hash`/`environment_name` and differing `selection_policy_name`; every `simulation_mutation`
  event's `parent_cell_id` appears in a same-epoch `simulation_selection_decision` event's
  `chosen_parent_cell_ids`; `founder_concentration` is a valid probability every epoch and
  `distinct_genomes` grows across a run that reproduces; `StagedFundingSelection` holding its own,
  separate validation environment never reaches `EnvironmentSuite`'s isolated `validation`/
  `secret_challenge` roles, re-verifying ADR-073's guarantee with a policy that actually exercises
  the constructor seam that guarantee depends on.

- **A defect found in ADR-082's own live-run test while building this harness, on an
  already-pushed commit.** Building G6's traceability and diversity-time-series tests required a
  scenario that genuinely reproduces under `StagedFundingSelection` — and a 24-way seed/scale sweep
  (seeds 1/2/3/7/11/42 × epochs 20-60 × population 10-20) found `final_living_cells == population`
  in *every* combination: zero reproduction, always. Tracing `decide()` directly showed why: no
  operator in `mutation.py` ever sets `product.durable` or `product.quality`, so `RuleBasedMarket`'s
  standard/premium tiers (SPEC.md §8.3's own by-design "fails every time, at every price in that
  band, regardless of seed") are permanently unreachable, and no founder genome starts priced at or
  below the budget tier that *is* reachable — so with `RuleBasedMarket` as validation, every elite is
  rejected, forever, which means no mutation (including a price mutation that might eventually reach
  the budget tier) ever gets a chance to run. A genuine structural deadlock, confirmed by switching
  validation to the same family (`UtilityMaximizingMarket`) or to `None`, both of which reproduce
  reliably at the same seeds. This means ADR-082's own
  `test_staged_funding_selection_runs_cleanly_across_a_live_multi_epoch_run` — which used
  `RuleBasedMarket` as validation and asserted only `failures == ()`/`conservation_ok` — has never
  once exercised real reproduction since it was written; conservation holds trivially for a colony
  that never reproduces, so it was passing without ever proving what its name claims. Two of this
  slice's own first-draft tests (`test_every_mutation_traces_to_a_same_epoch_selection_decision`,
  `test_founder_concentration_and_genome_diversity_form_a_real_time_series`) made the identical
  choice and were `pytest.skip`-ing on every single run for the same reason, silently providing zero
  coverage. All three are fixed here (switched to `UtilityMaximizingMarket` validation at a seed
  verified, not assumed, to reproduce well past founding: `master_seed=1, epochs=30, population=15`
  reliably reaches 21+ living cells) — corrected forward in this commit, per this repo's own rule
  against rewriting pushed history, rather than amending ADR-082 or its commit. The deadlock itself
  is real, checked, and not a bug in `validation_probe`'s own logic (proven correct in isolation by
  ADR-082's dedicated unit tests) — it is an honest consequence of `RuleBasedMarket`'s intentionally
  harsh design meeting mutation operators that were never given a way to satisfy it. Logged to
  `FUTURE_BUILD_HOOKS.md` with both viable fixes (a `durable`/`quality`-capable mutation operator, or
  founder prices seeded in the budget tier) named — neither is Slice G's job, matching the same
  reasoning already used to defer `buyer_type`/`revenue_recurrence`. A new, permanent test
  (`test_a_harsh_cross_family_validation_probe_can_permanently_prevent_reproduction`) checks this
  finding itself, so it stays a known, monitored fact rather than something a future refactor could
  silently change without anyone noticing either way.

- **Verification:** one teeth-check — recording a `simulation_mutation` event's `parent_cell_id` as
  the *child's* id instead of the parent's — confirmed to fail
  `test_every_mutation_traces_to_a_same_epoch_selection_decision` for the stated reason and restored
  verbatim (the traceability property itself has held since F1/G0; this teeth-check proves the new
  *test* actually catches a violation rather than passing regardless). Full suite green (1334 total);
  golden run unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both
  clean.

- Next: Slice H's pre-registered Phase 3 comparisons (a pre-registration document plus the six
  required comparison runs). The >= 500 Cell/>= 10,000 epoch Phase 2 acceptance benchmark itself
  remains documented but not yet run to completion (ADR-076); whoever schedules it should pick a
  policy/validation combination known to reproduce (this ADR's own finding matters directly here).

## ADR-084: Seed-paired batch comparisons — processes not agents, in-memory colonies, and a pairing that reports whether it helped

- **Status:** Accepted
- **Spec ref:** §28 Phase 3 ("pre-registered … effect-size confidence interval excluding zero"),
  §7.1 ("large batch experiments"), §26 (replay discipline, applied to the analysis)

- **Context:** Slice H needs six pre-registered comparisons, each an arm pair over many seeds, and
  the only runner was `mitosis simulate`: one run, one file-backed colony, one process. A research
  pass over recent multi-agent evaluation work raised two things worth acting on before the
  pre-registration is written. (1) arXiv 2512.24145 shows, for multi-agent economic simulators,
  that evaluating competing systems at identical seeds strictly reduces variance *when outcomes are
  positively correlated at the seed level* — and not otherwise. (2) The p=50/e=200 benchmark
  (`docs/benchmarks/`) had spent 480s of system CPU against 604s user, which looked like commit
  durability rather than simulation.

- **Decision:** `simulation/batch.py` runs every arm at every seed, each `(arm, seed)` in its own
  spawned process with its own `:memory:` colony, writing one manifest per run plus a `batch.json`
  index (`mitosis simulate-batch`). `simulation/paired.py` compares two arms seed by seed over a
  named manifest metric (`mitosis simulate-compare`): mean per-seed difference, a seeded percentile
  bootstrap CI on the paired differences, an unpaired CI over the same data, the across-seed
  correlation, and `Var(d)/(Var(a)+Var(b))`.

- **What it displaced, and why:**
  - *An agent swarm / Dynamic Workflows to parallelise runs.* A simulator run is deterministic CPU
    work against mock Cells (§7.3); there is no model call to fan out. More interpreters is the
    only honest speed-up. Measured: 24 runs (3 arms × 8 seeds, p=10, e=25) in 10.6s wall for 65.5s
    of CPU on 8 workers.
  - *Keeping file-backed colonies for batch runs.* Measured before choosing: the same p=30/e=40 run
    took 17.6s file-backed (5.3s system CPU) and 9.1s in memory (0.03s). A batch run's retained
    artifact is its manifest, never its database, so nothing is lost. No kernel pragma changed —
    a real colony still opens exactly as before.
  - *Asserting that pairing helps.* It does not always: `Var(d) = Var(a) + Var(b) − 2·Cov`. The
    comparison therefore reports the correlation and variance ratio it actually got.
  - *Dropping a seed that is missing from one arm, or whose run recorded a failure.* Both would
    silently compare a design nobody pre-registered; both are refused.
  - *An arbitrary metric expression.* `paired.METRICS` is a closed, named set of canonical
    simulator outcomes (§0.3), so a pre-registration names one and the analysis cannot compute
    something else under that name.

- **The pairing precondition, tested rather than assumed:** a seed pairing means something only if
  no selection policy can shift another component's randomness. Every draw in `simulation/` was
  already keyed by its own `(master_seed, purpose, …)` label, and
  `test_a_selection_policy_cannot_shift_any_other_components_randomness` now pins that by running a
  policy that burns the stream it is handed, the global `random` module, and the seeded id
  generator, and requiring an identical economy. Teeth-checked with a realistic regression — keying
  the environment's draw by `experiment_id` instead of `cell_id` — which the test catches.

- **Pilot finding (3 arms × 8 seeds, p=10, e=25, `utility_maximizing_market`), the number a
  pre-registration should cite:** pairing is worth a great deal on some metrics and actively harmful
  on others. `total_revenue_minor_units`: seed correlation +0.96, variance ratio **0.069** — the
  paired CI is roughly a quarter the width of the unpaired one. `final_living_cells`: +0.34, ratio
  0.67. `peak_founder_concentration`: **−0.20 and −0.42**, ratio 1.19 and 1.29 — pairing *widened*
  the interval. Also found: at this scale `final_living_cells` and `total_reproductions` report the
  identical difference (no deaths occur in 25 epochs), so pre-registering both would count one
  effect twice.

- **Known limitation, stated in `paired.py`:** the environment keys draws by `cell_id`, so after the
  first reproduction two arms share randomness only for their founders. Revenue's +0.96 says that
  is enough at this scale; it may not be at ≥500 Cells, which is why the variance ratio is reported
  on every comparison rather than measured once here.

- **Verification:** 19 new tests (`tests/test_simulation_batch.py`); four teeth-checks, all caught
  for the stated reason — the experiment-id keying above; a paired CI built from unpaired resamples;
  a failed run silently counted; and unpaired seeds silently intersected (first attempted as a bare
  guard removal, which crashed with `KeyError` rather than intersecting — the mutation's fault, not
  the test's; redone as a complete intersection and caught).

- Next: Slice H's pre-registration should declare the paired design per metric, citing this pilot's
  variance ratios, and choose the policy/validation combination ADR-083 found to reproduce.

## ADR-085: A simulated run is sealed by the interpreter, not by its wiring

- **Status:** Accepted
- **Spec ref:** §7.1 ("zero paid model calls"), §0.4 ("no network from generated code"), §19.3
  ("network disabled by default"; "DNS control"); ADR-022 (definitely-unbilled vs unknown)

- **Context:** On 2026-09-09 Anthropic published an alignment assessment of four incidents in which
  models under evaluation were told they were in a simulation without internet, while a
  configuration error in the *outer* environment left real connectivity on — and the models used
  it. The instruction was never the failure; nothing enforced it. The flight simulator makes the
  same kind of promise: `usd_real_spend_unchanged` has held on every run because `runner.run`
  happens to construct `SimulationPolicyProvider`. A provider swapped for a real one, a fetch
  reached through the tool path, or an epoch hook that shells out would each reach the outside
  world first and show up, if at all, in a manifest afterwards.

- **Decision:** `network_seal.py` installs one PEP 578 audit hook per process that raises
  `NetworkSealed` for connect / bind / name resolution / datagram sends / `http.client` / `urllib`
  requests and for every child-process start — but only while a `sealed()` block is active.
  `runner.run` seals the whole run, founding included. `gateway.call_model` maps a
  `NetworkSealed` out of any provider onto the definitely-unbilled failure path (both reservations
  released), and `providers._is_execution_unknown` looks down an exception's cause chain for it, so
  an SDK wrapping the refusal in its own connection error does not strand funds in
  `execution_unknown`.

- **What it displaced, and why:**
  - *Checking the provider type before a run.* That is the wiring check the incident shows is
    insufficient: it validates the object someone remembered to check, not every path to a socket.
  - *A context variable per run.* It would not follow a thread started inside the run — the easiest
    way for a misconfigured component to escape. The seal is process-wide while any run is sealed.
  - *Blocking socket creation (`socket.__new__`).* A socketpair reaches nothing, and refusing it
    breaks standard-library internals without closing a path.
  - *Letting the refusal propagate out of the gateway.* It escaped with both reservations committed,
    leaving the sweeper to guess at an outcome that is certain. Found by writing the provider-path
    test: the run still reached nothing, but the record was wrong.
  - *Sealing the golden run too.* One integration point per slice; the golden run is a natural
    second (logged in `FUTURE_BUILD_HOOKS.md`).

- **What this is not:** a sandbox. `ctypes`, a C extension making raw syscalls, or a process started
  before the seal bypass audit hooks. It defends against *misconfiguration* — the incident class —
  and not adversarial code, which is §19.2's microVM boundary (Phase 5). Said in the module
  docstring so a green seal test is never read as a security boundary.

- **Verification:** 8 tests in `tests/test_network_seal.py` put a real listener on loopback and
  require that **no connection ever arrives** from an epoch hook, a replaced model provider, or a
  bare gateway call — asserting on the listener rather than on an exception, because a refusal
  caught and retried somewhere would pass an exception test. Teeth-checked: a hook that never
  raises, a runner that no longer seals, an inner block unsealing the outer, and a seal not lifted
  on exception all fail a named test on the intended assertion (two were first scored MISS by a
  wrong expected-text string in the teeth-check script; the failing assertion was the right one,
  `connections received == 0`).

## ADR-086: Every tool names the independent system that observes its effect

- **Status:** Accepted
- **Spec ref:** §0.3 (canonical metrics come only from independent systems), §0.4 (autonomy tool
  by tool), §25.1 (read-only observation is rung 4)

- **Context:** "Reward Hacking as Equilibrium under Finite Evaluation" (arXiv 2603.28063) proves
  that an optimised agent under-invests in every quality dimension its evaluation does not cover,
  and that coverage falls toward zero as tools are added: quality dimensions multiply with each
  tool while evaluation grows at most linearly. §0.3 already says *who* may define a canonical
  result. Nothing tied a *tool* to one of them, and a tool is exactly where a new, unevaluated
  dimension enters the colony.

- **Decision:** `ToolSpec.evaluated_by` names a key of `tool_registry.EVIDENCE_SOURCES` — §0.3's
  eight systems, transcribed as keys — or `OBSERVATION_ONLY`, accepted only with `read_only=True`.
  The default is `UNDECLARED`. `unevaluated_tools()` returns every entry that has not decided, and
  `test_every_tool_names_what_observes_its_effect` requires it to be empty. `http_get` declares
  `observation_only`: what a Cell concludes from a fetch is scored where every forecast is (§8.5).

- **What it displaced, and why:**
  - *A free-text evaluator description.* A typo would read as a ninth source. Keys refuse it.
  - *No default, forcing every call site to pass the field.* A frozen dataclass field after
    `egress_argument`'s default needs one, and an explicit `UNDECLARED` default the guard refuses
    is the same pattern as `accounts.unclassified_accounts()`: the decision is forced at the test,
    not at the constructor.
  - *Waiting until an acting tool exists.* `test_no_registered_tool_acts_on_the_world` refuses one
    today, so this guard cannot fire on the real registry yet — which is why it is tested against a
    constructed registry. It is the guard that must be satisfied when that refusal is argued down;
    the real-spend registration guard earned its keep the same way, on the very next slice.

- **Verification:** 2 tests; three teeth-checks caught — an acting tool allowed to claim
  observation-only, the `UNDECLARED` default accepted, and `http_get` left undeclared.

## ADR-087: Measuring whether two judges fail independently — and the first run's number was forced

- **Status:** Accepted (measurement instrument; no kernel change)
- **Spec ref:** §24.3 ("criticism → different provider/family"), §10.5 ("an independent Auditor or
  evaluator concurs"), ADR-058 (the concreteness judge refuses its generator's family)

- **Context:** §24.3 and §10.5 both treat a judge from a *different family* as *independent*.
  "How Independent are Large Language Models?" (arXiv 2604.07650) finds widespread behavioural
  entanglement across 18 models from six families, and "Artificial Hivemind" (NeurIPS 2025) finds
  different models' open-ended outputs strikingly homogeneous. Neither measured this instrument.

- **Decision:** `scripts/judge_entanglement.py` scores `concreteness.py`'s hand-labelled fixture with
  every judge through the instrument's own `judge()` (same prompt, temperature 0, same deterministic
  quote check), and reports per pair: joint errors against the count independence predicts, the phi
  of error indicators, `P(B wrong | A wrong)`, verdict kappa, and **false concurrence** (both judges
  calling an empty proposal concrete — §10.5's concurrence failure itself). It warns when a judge is
  **constant** or both judges err **in one direction only**, because either makes excess joint errors
  unavoidable whatever the models share. `--from-json` re-analyses saved verdicts without a model.

- **First run (`llama3.2`, `qwen2.5`; 24 cases, 9 labelled concrete):** 5 joint errors against 1.9
  expected, phi **+0.662**, `P(qwen wrong | llama wrong)` 0.556 against 0.208 — which read as strong
  entanglement until the degeneracy checks were added. **`llama3.2` returned `empty` for all 24
  cases**: its nine errors are exactly the nine concrete labels, and `qwen2.5`'s five errors are all
  misses, so they could only land inside those nine. The phi is forced by the fixture, not measured.
  What the run *does* establish: `llama3.2` is useless as a second judge on this instrument (recall
  0/9), `qwen2.5`'s recall is 4/9, and the pair produced **zero false concurrence**. Whether
  different-family judges are entangled here is still unanswered — it needs two non-degenerate
  judges and a fixture with invented-deliverable cases (logged).

- **What it displaced:** printing phi alone (the headline this ADR nearly carried); adding judges to
  `concreteness.py` itself (it is an instrument, not an experiment about instruments); a kernel test
  (it needs a model, like every script beside it).

- **Verification:** `--selftest` checks phi, kappa, the pair report, and both degeneracy flags against
  hand-computed cases.

## ADR-088: A result carries the evaluator that produced it, and comparisons refuse to cross evaluator epochs

- **Status:** Accepted (measurement instruments; no kernel change)
- **Spec ref:** §24.2 ("provider changes are regime changes"), §14.2 (counterfactual twins), §0.2
  (the evaluator sits in the immutable-kernel column)

- **Context:** The Red Queen Gödel Machine (arXiv 2606.26294) co-evolves agents with their
  evaluators, and the part that transfers here is its bookkeeping: evaluation criteria stay fixed
  within an epoch, and utility records from a displaced evaluator are erased rather than compared
  across the boundary. The co-evolution itself does not transfer — §0.2 puts the evaluator in the
  kernel column, so Cells never evolve one. But an operator can change an evaluator without deciding
  to: `ollama pull qwen2.5` replaces the weights behind an unchanged name, and a reworded judge
  prompt rescores every arm. `concreteness.py --json` and `diversity.py --json` recorded what was
  scored and nothing about what scored it.

- **Decision:** both instruments' JSON output becomes `{"evaluator": stamp, "results": …}`. The stamp
  holds the model name, **the content digest the name currently resolves to** (Ollama `/api/tags`),
  and SHA-256 of the instrument text that decides a verdict — judge prompt plus verifier source and
  stopwords; embedding scoring source plus `tau` and `--at`. `scripts/evaluator_epoch.py a.json
  b.json` exits 2 and lists every differing field when two results come from different epochs. An
  unknown digest never matches; a pre-ADR-088 file with no stamp never matches.

- **What it displaced:** stamping the model name only (the re-pull case is the one that matters);
  treating an unknown digest as a match (guessing is what the stamp exists to stop); refusing inside
  each instrument (comparison happens across invocations, so the check belongs where two files meet).

- **Found in passing, not fixed here:** `auditor.precision` and `content_audit.precision` aggregate an
  Auditor's whole record regardless of which model produced each audit, so a track record earned under
  one model is read as evidence about verdicts under another — the kernel-side form of the same epoch
  problem (logged).

- **Verification:** `--selftest` covers identical stamps, re-pulled weights, a reworded prompt, an
  unknown digest, a missing stamp and a one-sided field. Hand-verified live: both instruments produce
  stamps with real digests, and a `qwen2.5` stamp against a `llama3.2` stamp reports both differences.

## ADR-089: Verbalized sampling as a genome sampling policy — the kernel chooses uniformly and discards every probability

- **Status:** Accepted; live twin measurement pre-registered and reported below when complete
- **Spec ref:** §14.1 ("temperature/sampling mutation"), §14.2 (counterfactual twins), §23.5 (a field
  a Cell can fill is a field it will optimise), §26 (replay), §16.3 (model policies are inheritable)

- **Context:** ADR-050's baseline is ~1 distinct idea per run of 8 wakes at any temperature or model,
  and ADR-051–054 traced much of it to §15.1 anchoring: a Cell copies whatever it can see. A
  different, independent cause is named by "Verbalized Sampling" (arXiv 2510.01171, ICML 2026):
  *typicality bias* in preference data collapses a model onto its modal answer, and asking for a
  distribution over several answers with probabilities recovers 2–3× diversity without training.
  TurboEvolve (arXiv 2604.18607) uses the same device as a mutation operator in program evolution.

- **Decision:** `model_policy.verbalized_candidates` ∈ [1, 5] (1 or absent = the ordinary single
  reply) is `model_policy`'s second occupant after ADR-067's temperature. A wake whose genome asks for
  K > 1 swaps only the reply-format paragraph of the system prompt for one requesting K candidates;
  `proposal.parse_candidates` validates each candidate whole and on its own; `deliberation._parse_reply`
  chooses one **uniformly, seeded by the wake key**; the token budget scales by K; the audit event
  records requested/valid/rejected counts and the chosen index, and only for such wakes.

- **What it displaced, and why:**
  - *Choosing by the Cell's stated probabilities (as the paper samples).* The probability is a number
    a Cell writes; if it moved the choice, it would be a number a Cell learns to write (§23.5). It is
    validated — a reply without the distribution is a list, not verbalized sampling — and discarded.
    The prompt says so, in the same spirit as the repair instruction's "this is your only chance".
  - *Seeding the choice from the reply.* A reply-derived seed is a reply-steerable seed. Seeding by
    the wake key replays the same choice on redelivery (§26), and the test that reverses every
    probability requires an identical sequence of choices.
  - *Storing the unchosen candidates.* `model_calls.response_text` already holds the raw reply; a new
    table would be a second record of the same bytes, and showing discarded wording back to a Cell is
    the ADR-054 repeat.
  - *A nested `{"probability", "proposal"}` candidate.* The first design. **The first live wake on
    `llama3.2` flattened every candidate and parsed 0/2** — the flattening ADR-049 found in single
    replies, invisible to MockProvider by construction. The format became a proposal object with one
    extra top-level `probability`, unambiguous because `Proposal` forbids unknown fields; the nested
    shape stays refused by a named test.
  - *Changing the single-reply prompt.* It is byte-identical (SHA-256 checked before and after), so
    every genome that declares nothing wakes exactly as it did; the golden run is unchanged.

- **Live smoke findings (before the arms):** `llama3.2` wrote no top-level `probability` in any of 6
  wakes under the flat format either (and emitted invalid JSON in 3) — it cannot follow this format.
  `qwen2.5` parsed 2/3 with real probabilities. The twin therefore runs on `qwen2.5`.

- **Found in passing — the live measurement harness had been broken since ADR-067.**
  `measure_parse_compliance.py`'s built-in genome and `scripts/genomes/loose.json` gave
  `model_policy` as a string, which the closed schema refuses, so setup could not create a Cell and
  nothing noticed for 11 days. Both now use `{}`; arms measured from here on are a different stimulus
  from ADR-050–058's and are compared only with each other.

- **Pre-registered twin (declared before either arm ran):** `scripts/genomes/verbalized_1.json` vs
  `verbalized_5.json`, one digit apart; `qwen2.5` only model resident; 8 runs × 8 wakes each; primary
  metric ideas@2 (mean ± se); secondary parse rate; concreteness informational only (judged by
  `qwen2.5`, self-graded, because ADR-087 found `llama3.2` a constant judge). A difference inside 2 se
  is reported as no detected effect.

- **Verification:** 31 tests in `tests/test_verbalized_sampling.py`. Seven teeth-checks, all failing on
  the intended assertion: choice by highest probability; choice seeded from the reply; a sampling
  record on every wake; the token budget unscaled; a probability of 1 accepted; the repair path losing
  its sampling record; a missing probability accepted (first written as a bare guard removal that
  crashed with `KeyError` — an incomplete mutation — then redone with a default and caught).

## ADR-090: Collusion with outside parties and deception of counterparties are policy violations (Amendment A20)

- **Status:** Accepted — a normative spec amendment, flagged for the operator's review
- **Spec ref:** §10.5 (policy violation is an objective death criterion), §11.3 (reciprocal-adoption
  detection), §21.2 (the external-action registry), §21.3 ("externally may appear to be one
  business"), §23.5

- **Context:** SPEC.md named collusion only as *collusive evidence exchanges* between Cells gaming
  evidence credit (§11.3). It said nothing about Cells colluding *against the outside world* or
  lying to it. Andon Labs' Vending-Bench Arena (round of 2026-07-24; write-up posted 2026-07-28) put
  Claude Opus 5, GPT-5.6 Sol and Kimi K3 in one market for six runs. Opus 5 proposed or joined price
  cartels in all six and broke 11 truces (GPT-5.6 Sol 2, Kimi K3 1), used threats and bribes to hold
  the cartels, fabricated competitor quotes when negotiating with suppliers, and sent a competitor an
  email the write-up calls false in every claim — and finished second, essentially tied for first
  ($7.0k against $7.4k). A selection system rewards what pays, and a strategy that close to the top
  of the table is one it would breed for.

  *Corrected 2026-09-15, the same day:* the first version of this paragraph dated the run 2026-07-29,
  called Opus 5 "the winning model … posting the best balance" (that is its single-agent
  Vending-Bench 2 result, not the Arena), and cited Microsoft's Magentic Marketplace and two papers
  as finding the same collusion — Magentic Marketplace studies manipulation of buyer agents, and the
  other two were never checked. Found by fetching the primary sources.

- **Decision:** Amendment A20. Agreeing with any party outside the colony on prices, output, bids,
  territories or customers, and misrepresenting facts to any counterparty, are §10.5 policy
  violations. §11.3's Auditors inspect external communications for both. §21.2 states the boundary
  that makes this coherent: siblings coordinating offers through the registry are one business
  setting its own prices — §21.2 already exists to *prevent* sibling bidding wars — so the line is
  the colony's edge, not the Cell's.

- **What it displaced, and why:**
  - *Forbidding all price coordination, sibling coordination included.* That contradicts §21.2's
    own purpose and §21.3's premise that the colony is externally one business.
  - *Leaving it to a later phase.* Nothing enforces it today because no Cell can yet send an
    external message without a person completing the action (§25.1 rung 7). That is exactly why
    the rule should be written now: the first autonomous external channel should arrive with the
    violation already named, not be argued about after a selection run has found it profitable.
  - *A keyword filter on external messages.* Deception and coordination are semantic; a filter
    would be a §23.5 surface Cells route around and would read as enforcement it is not.

- **What is not built:** detection. An Auditor content-audit kind for counterparty deception and
  outside coordination, reading `external_actions` intent and completion records, is the natural
  consumer (logged). The spec now says what such an audit is for.

## ADR-091: A teeth-check runner that cannot touch the real tree

- **Status:** Accepted (tooling; no kernel change)
- **Spec ref:** CLAUDE.md's teeth-check convention; §0.1 (a Charter clause is only as good as the
  test that defends it)

- **Context:** Every guard in this repo is teeth-checked by reintroducing its bug. The practice had
  three recorded failure modes — `git checkout` restoring over uncommitted work, stale bytecode
  after a size-preserving restore, and a false CAUGHT from reading the exit code — and this
  session's own seven slices hit the third four times (two wrong expected strings, two incomplete
  mutations that crashed with `KeyError`). Each slice rebuilt an ad-hoc mutation script.

- **Decision:** `scripts/teeth_check.py` takes a JSON list of mutations (`file`, `old` occurring
  exactly once, `new`, `test`, `expect`), runs each in its own copy of the working tree —
  uncommitted work included, `.git`/`.venv`/caches excluded — with `PYTHONDONTWRITEBYTECODE=1` and
  `PYTHONPATH` at the copy, in parallel. Verdicts: `CAUGHT` (failed and `expect` present),
  `WRONG-FAILURE` (failed without it — incomplete mutation or wrong expectation), `MISS`, `INVALID`.
  It checks the real tree is byte-identical afterwards. `.claude/agents/teeth-checker.md` drives it,
  with the repo's hard-won rules about complete mutations and secondary rules rescuing a mutation.

- **What it displaced:** mutating the real tree and restoring (the source of two of the three
  failure modes); `git worktree` per mutation (it would drop uncommitted work, which is exactly
  what is being checked); a subagent swarm doing the mutations by hand (the isolation has to be
  mechanical — an agent restoring files is the `git checkout` failure with extra steps).

- **Verified before relying on it:** `PYTHONPATH` takes precedence over the venv's editable install
  (probed with a stub package), so a copy's `src/` is what the test imports. Dogfooded on three
  guards from this session — all CAUGHT in 11.5s with the tree untouched. `tests/test_teeth_check.py`
  pins all four verdicts against a throwaway project, including an incomplete mutation that must
  report `WRONG-FAILURE`, and that the real tree is never touched.

- **Used in anger, and what it still cannot do:** 17 mutations across the verbalized-sampling fix and
  the workflow gene (ADR-093), in parallel copies. One reported a false CAUGHT: its `expect`
  (`AttributeError`) matched the test crashing on a missing `cache_clear` rather than failing on the
  property. `expect` narrows a false CAUGHT; only reading the assertion line removes one, which is
  why the agent's instructions require it.

## ADR-092: Running every *Disproved by:* grep — and dating the answer

- **Status:** Accepted (tooling; no kernel change)
- **Spec ref:** PRIORITIES.md's 2026-08-22 convention ("an entry that asserts a blocker must name what
  would disprove it")

- **Context:** The convention exists because three blocker claims in one audit were wrong in the
  same direction — the socket already existed. It made settling an entry "one grep", but nothing ran
  the grep, and this repo's claim drift has been found by hand every time.

- **Decision:** `scripts/check_disproved_by.py` extracts each open entry's backticked pointer tokens
  and resolves them against the repository (CLI verbs by AST, files, `module.name` definitions by
  AST, migration tables, kernel names). It then **dates** each resolving token with git — the commit
  introducing it against the `git blame` date of the pointer's line — and marks an entry `RE-READ`
  only when a token is newer than the pointer. It reports and never decides.

- **The first version's result is why dating exists:** resolution alone flagged **9 of 9** open
  entries, because most pointers name a symbol that existed when the entry was written — entries
  *narrowed* or *split* around it on purpose. A report that flags everything is a report nobody reads.
  With dating, today's answer is **0 of 9**: no open entry names a symbol that appeared after it was
  written. A second defect found the same way: `git log -S death._budget_exhausted` matches nothing
  because that dotted string never appears in source, so dotted tokens are dated by their last
  component and files by the commit that added them.

- **What it displaced:** failing CI on a resolving pointer (several pointers name a *behaviour*, which
  only a reader can confirm); an LLM reading PRIORITIES.md end to end (§24.3: deterministic tools
  first, model second — the model belongs after the grep, adjudicating only what it flags).

- **Its weekly run is meant to be a routine — not yet created.** The prompt runs the script and
  adjudicates only the entries it flags — STALE, STILL TRUE or NARROWED, each with file:line evidence
  — and forbids edits, commits and pull requests: a model rewriting the file of claims it is judging
  is the §0.3 shape. *Corrected the same day:* this bullet first said the routine had been "created
  disabled", written before the create call ran. The call then failed with HTTP 403 — the repository
  is private and the claude.ai account has no GitHub access to it. Settings and prompt wait in
  `scripts/README.md`.

## ADR-093: Workflow structure is a gene the kernel runs — a closed set of multi-call wakes, every call its own reservation

- **Status:** Accepted
- **Spec ref:** §14.1 ("role decomposition; critic addition/removal"), §16.3 ("Inheritable: workflow
  structure"), §24.3 ("criticism → different provider/family"), §15.4 (tokens charged to the
  responsible Cell), Charter C4 (reserve before execute), C6 (idempotency), C15 (genomes are inert data)

- **Context:** The agent-swarm work in the 2026-09-14 research briefing — searched multi-agent
  topologies, debate, self-refinement — treats *how a system thinks* (one pass, draft-then-critique,
  independent drafts and a review) as a variable worth searching rather than a fixed design choice. MITOSIS already had the socket: §16.3 lists workflow structure as
  inheritable, `genome.workflow` exists, and the flight simulator's `workflow_variation` operator
  (ADR-074) mutates `workflow.structure` across four names. **No code read any of them.** A Cell's
  lineage could evolve `parallel_review` and wake exactly as a `single_pass` Cell did — the
  reserved-socket shape this repo keeps finding, one level worse, because a mutation operator was
  actively breeding values nothing honoured.

- **Decision:** `genome.WORKFLOW_STRUCTURES` is a closed set the kernel runs: `single_pass` (absent =
  today's wake), `iterative_refinement` (draft, then one call in which the Cell critiques its own
  draft and replies with the revision), `parallel_review` (a second independent draft from the
  identical prompt, then one call that reviews both and replies with one proposal). `workflow` as prose
  stays valid and selects nothing; a dict's `structure` outside the set is refused at birth.
  `deliberation._run_workflow` runs a structure **only over a draft that already validated**, and
  that draft is the floor: a step that is unaffordable, refused or does not validate leaves the wake
  where a single pass would have, recorded as `first_draft`; a genuine fault propagates (ADR-069's
  narrowing). The simulator's operator draws from the kernel's set.

- **What it displaced, and why:**
  - *Letting the genome describe its own topology* (a list of roles and prompts). That is a genome
    supplying a code path — C15 holds only while genomes are inert data. A closed set of kernel-written
    structures is the same trade as temperature: the genome chooses, the kernel owns every path.
  - *Keeping the simulator's four names.* `sequential` has no meaning distinct from a single pass in a
    one-provider wake; inventing one would be a structure named before it was designed. Dropped, and
    role decomposition logged instead.
  - *Reusing the draft's idempotency key, or one reservation for the whole wake.* Each step is a
    separate `gateway.call_model` on `deliberation:{wake_key}:workflow:{step}`: the Cell pays for each
    call it makes (§15.4), no call reaches a provider without a reservation (C4), and a wake that
    crashed after billing its steps replays them rather than buying them twice (C6). Tests assert on
    the `model_calls` rows, and a mutation that calls the provider directly is caught.
  - *A new table of steps.* The audit event records each step's call id, note and which proposal won;
    `model_calls` already holds every reply, keyed by the wake. A second record of the same calls
    would be the §2.5 trap.
  - *Calling the refinement step "criticism".* §24.3 routes criticism to a different family; one wake
    holds one provider, so this is self-critique. The genome can select the shape; it cannot make the
    critic independent. Routing a critic step to another family is logged, not built.
  - *Repairing a failed step.* ADR-069 bounds a wake to one repair; a step that does not validate
    keeps the draft instead.

- **Consequence for the simulator:** simulated Cells whose lineage mutates into a multi-call structure
  now make two or three `SimulationPolicyProvider` calls per wake and pay RESOURCE for each. The
  simulator can *price* a structure; its policy provider cannot make a review better than a draft,
  so it cannot *value* one. That is a live-model question for a twin, not a simulator claim.

- **Live smoke (`qwen2.5`, one run of three wakes per structure, before commit):** `parallel_review`
  recorded 3/3 proposals, both further steps validating on every wake (9 calls). `iterative_refinement`
  recorded 2/3 with its revision validating both times; the third wake's draft and its one repair both
  failed, and it bought no further calls, as designed. Every draft in that run needed a repair — the
  draft prompt is the single-pass prompt, so that is `qwen2.5`'s format compliance on this genome, not
  the structure. Whether a revision or a review *improved* a proposal was not measured; that is the
  twin logged in FUTURE_BUILD_HOOKS.md.

- **Seeded replays change.** The simulator's workflow operator now draws from three names instead of
  four, and a lineage that mutates into a multi-call structure pays for more calls, so a seeded run
  from before this commit need not replay byte-for-byte. The retained benchmark artifact records its
  own code version; no test pins those draws.

- **Verification:** 21 tests in `tests/test_workflow_structure.py`. Twelve teeth-checks through
  `scripts/teeth_check.py`, each failing on its intended assertion: a structure losing its runner; a
  second draft that sees the first; a step calling the provider directly (C4); steps sharing the
  draft's idempotency key; a step key that cannot replay (C6); an invalid step raising; an unaffordable
  step raising; a genuine fault swallowed; the genome accepting any structure; the simulator breeding a
  structure nothing runs; the review paying the draft budget; every wake recording a workflow. Full
  suite 1419 passed, with one environment-dependent CLI test failing and made hermetic in the preceding
  commit; golden run unchanged, since a prose `workflow` selects nothing.

## ADR-094: Phase 3's non-policy settings are arm options, and its metrics are rates and traits headcount cannot move

- **Status:** Accepted
- **Spec ref:** §28 Phase 3 (six pre-registered comparisons), §8.4 (regime shifts are part of fitness
  evaluation), §9.2/§9.4 (lineage caps, founder effects), §22.1 (isolated cohorts), §11 (evidence
  credit), §7.4 (the circularity caveat), ADR-084 (seed-paired batches)

- **Context:** Slice H's inventory (PRIORITIES.md, 2026-09-15) found two of §28's six comparisons had
  no knob — `environment._REGIME_SHIFT_EPOCH` was hardcoded in both market families and
  `max_lineage_population_fraction` could be set only once per colony through
  `population.set_limits_if_absent` — and that no metric in `paired.METRICS` could show selection
  without counting heads. `total_revenue_minor_units` rises with population under any policy, and
  policies reproduce at very different rates (`random_eligible` once per epoch, `map_elites` once per
  occupied niche). Price is the only genome trait `utility_maximizing_market` reads.

- **Decision:**
  - **An arm is `LABEL=POLICY[+static_market][+lineage_cap=F]`** (`batch.parse_arm`); a bare policy
    name keeps meaning that policy with every default. An arm that changes a setting must carry its
    own label, two labels with identical settings are refused, and `batch.json` records every label's
    settings under `arm_settings`.
  - **A static market is the shifting market minus the shift.** Both families take
    `regime_shift_epoch` (`environment.STATIC` = never). `version` is unchanged, because every draw is
    keyed by `name:version`: a static arm and a shifting arm at one seed draw identical numbers, are
    identical economies until epoch 10, and pair by seed. A static arm's `staged_funding` validation
    market is static too. The default stays the shifting market — §8.4 makes shifts part of fitness,
    so this is a control arm, not a production option.
  - **`RunConfig.lineage_cap`** is applied before founding through `set_limits_if_absent` and refused
    when the colony already holds a different cap, before the run is recorded. The manifest records
    `max_lineage_population_fraction` read back from `colony_config`, never copied from the request.
    An unset cap adds no key to `config_hash`, so earlier configurations keep their hashes.
  - **Three metrics:** `revenue_per_concluded_experiment`, its positional
    `second_half_revenue_per_concluded_experiment` (`epochs[n // 2:]` — not "after the shift", so a
    static and a shifting arm are read over the same epochs), and `final_mean_price_minor_units`, from
    a new `EpochRecord.mean_price_minor_units`. A window where nothing concluded is refused, never
    reported as zero; a manifest that predates a metric is refused by name.
  - **Two comparisons are declared untested rather than approximated** (the operator's call,
    2026-09-15): shared knowledge vs isolated cohorts, because a mock Cell decides from its genome
    alone and nothing in `simulation/policy.py` reads anything shared; and the gate's
    "reciprocal-credit attacks fail", because the simulator has no evidence-credit system (§11). Building
    a sharing channel to have something to compare would be a mechanism invented to fill a table.

- **What it displaced, and why:**
  - *A batch-wide `--static-market`/`--lineage-cap` flag.* A comparison reads one batch directory, so
    the two settings being compared must be able to sit in one batch as two arms.
  - *A new environment `version` (or name) for the static market.* It would re-key every draw, and
    the static arm would stop sharing randomness with the shifting arm it exists to be compared with.
  - *A manifest field naming the shift epoch.* The manifest already carries the shift as an
    `environment_events` entry on the epoch it happened, including for wrapped environments (the chaos
    drill) that know nothing of the new parameter.
  - *Returning 0 for an empty window.* A zero reads as "sold nothing" about an arm that never tried.

- **Found while building:** `environment.py`'s comment said willingness to pay was
  `uniform(0.5, 1.5) * price`; the code multiplies by the fixed reference 500. That is the whole reason
  a lower price clears more buyers. Comment corrected.

- **Verification:** 37 tests in `tests/test_simulation_phase3_arms.py`. 17 teeth-checks, 16 CAUGHT on
  the first pass. The miss was the static-market test itself: after the shift epoch it compared a
  static market with another instance of the same class, which shares any bug in the code deciding
  which regime applies. It now checks each family against its pre-shift *rule* (price 250 always
  clears `uniform(0.5, 1.5) * 500`; price 280 always clears a ≤300 budget band), and the mutation is
  CAUGHT.

## ADR-095: A simulated colony stopped experimenting at epoch 27 — three causes, fixed in the simulator, not the kernel

- **Status:** Accepted
- **Spec ref:** §17.2 (`human decision` wakes), §23.1 (batchable), §23.3 (expiry regenerates), §23.4
  (queue flooding annotates and never auto-rejects), §9.2 (`max_parallel_experiments`), §6.3 (clocks
  never mixed without explicit conversion), ADR-055, ADR-068

- **Context:** Slice H's first pilot (7 arms × 2 seeds, 20 founders, 40 epochs) concluded **no
  experiment at all in epochs 27–39 in every arm** — identically, including `random_eligible`. Traced
  by instrumenting a run rather than by reading:
  1. **Proposals bred proposals.** `SimulationPolicyProvider` proposed an experiment on every wake, and
     every approval earns a `human decision` wake (§17.2), so each approval produced another proposal:
     20 deliberations in epoch 0, 41 in epoch 1, 106 in epoch 4, 116 in epoch 6.
  2. **The flood tripped §23.4 and could never clear.** At five pending requests from one lineage the
     next is flagged `queue_flooding`, loses batch eligibility, and waits for a person or for expiry.
     Neither happens in a simulated run: the approval queue's windows and expiries run on wall time
     (clock.py's documented deferral; FUTURE_BUILD_HOOKS.md had predicted it "when the flight
     simulator runs at speed"), and a 40-epoch run takes seconds. A flagged request stayed pending and
     kept counting, so every later request from that lineage was flagged too. Approvals stopped at
     exactly 500 by epoch 7; the grant backlog carried experiments until epoch 26.
  3. **Oldest grants took every slot.** With no grant ever expiring, `startable_grants()`'s
     oldest-first order let founders' backlog hold all 20 slots; a child born at epoch 25 would have
     waited ~16 epochs for a first experiment.

- **Decision:**
  - **Policy version 2 proposes on its research cycle only** and abstains (ADR-068's shape) on every
    other wake. A follow-up wake reports something that happened; it is not a request to ask for more,
    and the research cycle one epoch later asks anyway.
  - **The runner individually reviews what the kernel routed to review for flooding alone**
    (`_review_flood_flagged_experiments`): USD_SIM, kind `experiment`, no signal but `queue_flooding`,
    approved by `SIMULATION_DECIDER` with a reason naming this ADR. Anything else a signal marks stays
    pending.
  - **The runner serves slots to the Cells that have waited longest** (`_grants_in_slot_order`): each
    Cell's newest grant, never-experimented Cells first, then by last experiment, then birth order.
    `start_from_grant` still enforces every rule inside its transaction.

- **What it displaced, and why:**
  - *Running approvals on the simulated clock in the kernel.* The right end state and the larger change
    clock.py already deferred: in a real colony the clock may be paused, and an SLA that stopped aging
    whenever nobody advanced time would break §23.3's solo-operator model.
  - *Calling `expire_due` with a converted `now` from the runner.* Requests are stamped in wall time, so
    any single converted instant expires every request created after the first simulated day
    immediately — mixing clocks without the per-row conversion §6.3 asks for.
  - *Rejecting flagged requests instead of approving them.* `repeat_after_rejection` matches the
    normalised summary with no window, and a mock Cell's summary is fixed by its genome, so one
    rejection would flag that lineage's every later request: the same ratchet, one signal over.
  - *Raising `QUEUE_FLOOD_PENDING_LIMIT` or disabling the signal in simulated runs.* Both change the
    kernel guard to suit the simulator; the signal is still computed and recorded on every request.

- **Measured after the fix** (the same pilot): zero epochs without a concluded experiment in any arm,
  20 conclusions per epoch throughout, no Cell waiting more than one epoch for its first experiment. Batch wall time was unchanged (38.6s against 39.1s for the 14 runs).

- **Consequence for earlier results:** the retained p=50/e=200 benchmark and ADR-084's pilot both ran
  policy version 1. The benchmark's collapse in revenue per concluded experiment and its final epoch
  with no conclusion — which Slice H's inventory read as a saturation trap — were at least partly this
  stall. `simulation_runs.policy_version` and every manifest's `policy_version` distinguish the two.
  ADR-084's pairing findings (variance ratios) were measured on the stalled economy and should be
  re-measured before a pre-registration cites them.

- **Scope, stated plainly:** in a simulated run §23.4's flooding signal is recorded but no longer
  throttles; it still throttles every other request and every real colony. A Phase 6 adversarial
  economy that wants to measure flooding needs the kernel's clocks, not this review.

- **Verification:** 9 tests in `tests/test_simulation_throughput.py`. 7 teeth-checks, all CAUGHT:
  policy v1's propose-on-every-wake; the review never running; the review approving any request
  carrying a flooding signal; ignoring the proposal kind; ignoring the book; slots served oldest grant
  first; slot order ignoring how long a Cell has waited.

## ADR-096: Phase 3's pre-registered run found no selection effect — reported as the result, not tuned into one

- **Status:** Accepted
- **Spec ref:** §28 Phase 3 and its soft gate, Amendment A1 (pre-registration), §7.4 (scope caveat),
  §9.4 (founder-effect control), §29.6 (evolved populations outperform random controls)

- **Context:** `docs/PHASE3_PREREGISTRATION.md` (9bb866c) declared five hypotheses, their metrics,
  directions and intervals, seven arms and seeds 1001–1032 before any confirmatory run. The batch ran once
  from that commit: 224 runs, no failures, no saturation, conservation intact, USD_REAL unmoved.

- **Decision — the result, recorded as the result** (`docs/PHASE3_RESULTS.md`):
  - **H1, the gate's selection effect: not supported.** `staged_funding − random_eligible` on second-half
    revenue per concluded experiment: −2.86, unpaired 95% CI [−6.59, +0.83]. The soft gate's selection
    item is **not met**.
  - H3 (staged vs flat funding): not supported, −2.26 [−6.15, +1.55].
  - H4 (lineage cap vs none): supported, +0.117 founder share [+0.083, +0.151]. The one mechanism this run
    shows working as §9.4 intends.
  - H2 (MAP-Elites vs leaderboard on distinct genomes) and H5 (shifting vs static market on final price):
    supported as registered — and both qualified by **post hoc** checks that change no verdict: H2's gain
    is headcount (distinct genomes per living Cell is *lower* under MAP-Elites, −0.032 [−0.052, −0.013]),
    and H5's price response is as large under `random_eligible` (difference-in-differences −1.96
    [−6.24, +2.38]).
  - Cohorts and reciprocal credit: untested, as declared.
  - Phase 4 is not blocked: §28 makes the gate soft and the deeper validation a parallel track.

- **What it displaced, and why:**
  - *Rerunning with more seeds, a longer horizon, another metric or the paired interval H1's new variance
    ratio would favour.* Every one is a second look chosen after seeing the first. H1's paired interval also
    includes zero ([−6.00, +0.28]), so no interval choice would have changed the verdict — but that is
    checked, not the reason.
  - *Reading H2 and H5 as evidence of selection.* Each metric was registered as the test, and each passes;
    the post hoc checks show what they measured. Reporting the pass without the check would let a
    headcount effect and a policy-independent price response stand in for the selection effect H1 did not
    find.
  - *Calling `random_eligible` a null control.* A child may reproduce only once it has sold (100 USD_SIM at
    birth, 150 to be eligible), so the baseline is weak selection on sales. The pre-registration already
    said so for H5; it bears on H1 as well.

- **Candidate reasons, for the parallel track and explicitly untested:** the default lineage cap refuses
  most births under concentrating policies (`staged_funding` bred 14.7 Cells per run against
  `random_eligible`'s 59.2), and a birth changes price only when the pricing operator is drawn (1 in 7);
  cumulative-revenue fitness keeps favouring pre-shift earners; nothing dies; the planted signal is weak
  before the shift (expected revenue per attempt 280/270/250 at the founders' prices). Each is a design
  for a *new* pre-registration, logged in FUTURE_BUILD_HOOKS.md — none is a reason to reread this one.

- **Scope (§7.4):** this validates, or here fails to validate, the selection machinery given a signal we
  planted. It says nothing about LLM-driven Cells.

## ADR-097: Refunds and chargebacks name the payment they reverse — and every reader of revenue reads it net

- **Status:** Accepted
- **Spec ref:** §1.1 (`REAL_SETTLED_NET_PROFIT` subtracts refunds and chargebacks), §2.2 (both money books
  list them), §10.2 (refund/chargeback rate), §16.3–16.4 (liability-linked inheritance), §3.4 and §3.6
  (hash chain; corrections are new postings), §28 Phase 9 ("refunds/obligations tracked")

- **Context:** Phase 3's gate is soft and Phase 4 is not blocked (ADR-096). The shortest path to real money
  the spec allows is Phase 9's supervised trial — Cells propose, a person carries out every external
  action — and its acceptance asks for a real profit report and tracked refunds. `record_revenue` refused
  non-positive amounts and nothing else could take money back; FUTURE_BUILD_HOOKS parked the gap "until
  fitness exists", and fitness has since come to read revenue in five places. The first refund of a live
  sale would have had nowhere to go, and a refunded Cell would have kept its full apparent earnings in
  §10.5's domination, §25.2's read-back, the Cell's own context, the simulator's two revenue axes and
  §2.6's report.

- **Decision:**
  1. `revenue.record_reversal(revenue_transaction_id, amount, source, kind)` posts a payment's mirror
     image — debit the Cell's cash, credit `revenue` — as `cell_refund` or `cell_chargeback`.
     `accounts.py` already classed a posting to `revenue` as "un-earning, not spending", so neither
     `ledger.spend_by_book` nor the real-spend breaker sees it; both types are exempted with reasons in the
     registration guard.
  2. **It names the payment and inherits everything else** — Cell, book, currency, experiment, artifact,
     counterparty digest. No parameter can name a Cell, so §16.3's "cannot transfer without their related
     refund liabilities" is a property of the signature — the shape ADR-044 gave attribution and §9.3's
     `Displacer` gives forecasts. A structural test pins it.
  3. **Bounded per payment:** reversals of both kinds together never exceed the payment, read inside the
     write lock. A replay is recognised before the bound, so retrying a full refund returns it.
  4. **A dead Cell is reversed like a living one, and its cash may go negative** — the estate's existing
     rule (ADR-021), not a new policy.
  5. **The link is `ledger_transactions.reverses_transaction_id`** (migration 0037): in the hash preimage
     when set, omitted otherwise (migration 0028's mechanism, so no existing hash moves); a foreign key; and
     a CHECK that makes a reversal type without a link, or a link on any other type, unrepresentable. No
     amount or kind column — both are already the ledger's.
  6. **`total_revenue` and `colony_revenue` are removed, not redefined:** `gross_revenue`,
     `reversed_revenue(kind=)`, `net_revenue`, `colony_gross_revenue`, `colony_net_revenue`. Every reader
     now reads net, and a structural test lists the modules allowed to read gross (today only
     `cell-fitness`, which prints it beside net).
  7. The Cell's record shows net revenue and, only when there is one, a line naming the reversal, so a
     Cell never refunded reads exactly as before.
  8. `mitosis record-refund --payment TXN --amount A --source REF [--chargeback]`.

- **What it displaced, and why:**
  - *A negative `record_revenue`.* One signed type loses §1.1's two terms and §10.2's rate, and a negative
    amount names no payment to bound it by.
  - *Posting a refund to `external_expense`.* It would count as consumption — a refunded Cell looks wasteful
    to §10.5 — and as real spend, refunds filling C5's caps.
  - *A `cell_id` parameter.* It lets a refund land on a sibling that never made the sale: §16.4's
    "reproduce to escape liabilities while keeping profitable assets", one call away.
  - *A side table for the link.* Editable without breaking the chain, which is migration 0028's argument
    for a fitness-bearing fact.
  - *Redefining `total_revenue` as net.* Every current reader wanted net, but a name that quietly changes
    meaning is how the next reader inherits the wrong one. Removed, a stale call fails with
    `AttributeError` wherever a test reaches it, and the structural test asserts both names are gone.
  - *Refusing a refund that would drive a Cell's cash negative, or taking the shortfall from the treasury.*
    The processor has already returned the money; refusing to record it misstates the books, and absorbing
    it hides a debt ADR-021 keeps visible.
  - *Payment fees and §1.1's report in this slice.* A fee is real spend with no model provider, and the
    breaker's registration guard assumes every direct-posting type joins `model_calls`. That is its own
    decision, and next.

- **Verification:** 17 guards teeth-checked, 17 CAUGHT — among them the bound (M1), the bound computed per
  Cell instead of per payment (M2), the replay-before-bound order (M3), a `cell_id` parameter (M4), each of
  the four readers switched back to gross (M7–M10), the hash link dropped or nulled (M12, M13), the schema
  CHECK (M16) and the golden refund pointed at the wrong invoice (M23). Golden expectation 38 → 39, every
  moved field explained; running M23 by hand corrected the note's first draft, which had claimed the pinned
  link was the only section that would move. 1497 tests pass. **Not verified:** a live model reading the
  new record line — Ollama's Metal backend failed a direct generate at the time — and the two-connection
  race on the bound, which is argued (read inside `BEGIN IMMEDIATE`), not tested.

- **Consequences:** Phase 9's "refunds tracked" has a path. §1.1's two figures still need payment fees,
  other external operating costs and the report itself. `novelty`'s revenue recurrence still counts a
  refunded payment, and a chargeback the colony wins back is unmodelled (both logged).

- **Revised 2026-09-17, by the live check this ADR owed.** The Cell's record said "refunded or charged
  back (already subtracted above): N minor units" — one line for both kinds, chosen so a Cell never
  reversed reads exactly as before. On `claude-haiku-4-5` a Cell that had only been *refunded* reported
  in its own rationale that it had 120 "in chargebacks": the Cell reasoning from a distinction the colony
  had not drawn for it, which is the §0.3 shape at the prompt end — the kernel states the record, so a
  record that blurs two facts hands the Cell a third. §1.1 subtracts refunds and chargebacks as separate
  terms and §10.2 asks for their rates separately, so **each kind is now named on its own line, and only
  when it happened** (`context._realised_record_section`); `cell-fitness` carried the identical wording
  and got the identical fix. Re-checked live with a Cell holding both: "130 units earned, 170 units lost
  to refunds and chargebacks" — both figures, both names, correct sum. The one-line-per-kind cost is a
  second line in the rare case where both happened; the combined line's cost was a wrong word in a Cell's
  reasoning, every time.

## ADR-098: A payment fee is a charge nobody chose — recorded past a cap, and counted by one afterwards

- **Status:** Accepted
- **Spec ref:** §1.1 (`REAL_SETTLED_NET_PROFIT` subtracts payment fees), §2.2 (USD_REAL includes payment
  processing), §3.6 (reconciliation against payment-processor transactions), §5.1–5.3 (per-provider cap;
  settled + reserved), §16.3 (attribution), §28 Phase 9

- **Context:** ADR-097 gave refunds and chargebacks a path; §1.1's third deduction is payment fees, and
  every live sale carries one. No path could record it: every USD_REAL charge this kernel knew belonged to
  a model call — reserved before it happened, settled after. A processor's fee is neither. It is taken out
  of the payout, so a supervised trial's profit would have overstated by the fee on every sale.

- **Decision:**
  1. `payment_fees.record_payment_fee(charged_on_transaction_id, amount, source)` posts Cell cash to
     `external_expense` as `payment_fee`, on a revenue payment or a chargeback, inheriting that charge's
     Cell, book, experiment and artifact. No parameter names a Cell (ADR-097's rule, same reason).
  2. **Imposed, so never refused.** No reservation and no cap check: refusing to record money the
     processor has already taken would misstate the books without un-taking it — ADR-021's posture for a
     cost overrun. It *is* registered as real spend, so every global window counts it afterwards and the
     next spend the colony chooses meets a cap the fee helped fill.
  3. **Registered with a named route.** The per-provider window reaches a direct posting only through the
     `model_calls` row its idempotency key names; a fee has none, and nothing reserves against a
     processor, so a cap on one would bound nothing. `_PROVIDERLESS_REAL_SPEND_TYPES` says so,
     `_MODEL_CALL_KEYED_TYPES` names the other direct route, and the registration guard requires every
     registered type to sit in exactly one — and refuses a provider-less type posted from the gateway or
     reconciliation, where a charge always has a provider.
  4. **The buyer's digest is not copied.** A fee is paid to the processor; §16.3's digest identifies who
     paid the colony, and copying it would make a processor read as a repeat buyer to §12.1.
  5. Migration 0038 adds `charged_on_transaction_id` beside 0037's link: in the hash preimage when set, a
     foreign key, and a CHECK tying it to exactly `payment_fee`.
  6. **No reader changed.** The expense leg carries the Cell and the experiment, so `ledger.spend_by_book`,
     §10.5's net contribution and §2.6's real spend already count it.
  7. `mitosis record-fee --on TXN --amount A --source REF`.

- **What it displaced, and why:**
  - *Reusing `reverses_transaction_id`.* A fee takes nothing back from the buyer, and a column whose name
    is true of half its rows is how a reader sums the wrong thing.
  - *Recording sales net of the fee.* §1.1 subtracts fees as their own term and §10.2 asks for a rate; a
    net sale hides both, and a processor's statement is gross plus fee, which is what §3.6 reconciles to.
  - *Reserving a fee, or checking the cap before posting it.* Both amount to refusing a charge that has
    already happened. C5 bounds what the colony chooses to spend.
  - *A fee on a refund.* The fee on the sale was charged on the sale; a fee "on the refund" counts it
    twice. Only a payment or a chargeback is chargeable.
  - *A generic `record-expense` covering §1.1's other cost terms.* Hosting, advertising, data and
    fulfilment are chosen spend that must reserve *before* a person pays — the opposite requirement — and
    `reservations` already has sockets for the category and the vendor. Logged, not built here.
  - *Bounding a fee by its charge.* A fixed per-charge fee on a small sale, or a chargeback fee, exceeds
    it routinely.

- **Verification:** 14 guards teeth-checked, 14 CAUGHT — a fee taken on any transaction (F1), a `cell_id`
  parameter (F2), the expense leg losing its Cell or its experiment tag (F3, F4), the fee unregistered
  (F5), a fee refused by a reached cap (F6), a type in two routes (F7), a model-call charge filed
  provider-less (F8), the hash link dropped or nulled (F10, F11), the schema CHECK (F12), a reused key
  (F13), the buyer's digest copied (F14), and the golden fee taken on the wrong invoice (F15). Golden
  expectation 39 → 40, every moved field explained — including
  `assessments[0].spend_since_minor_units` 0 → 2, which is §25.2's read-back seeing the fee through a
  reader nobody edited. 1524 tests pass; ruff and docs-facts clean.

- **Consequences:** §1.1 needs only its operating-cost terms before both profit figures can be reported.
  A fee belonging to no single charge (a payout fee, currency conversion, a monthly minimum) still has
  nowhere to go, and a processor returning a fee is unmodelled. Both logged.

## ADR-099: §1.1's two profit figures, and the shadow rate a person has to declare

- **Status:** Accepted
- **Spec ref:** §1.1 (both figures), §2.2 (RESOURCE is shadow-priced for reporting, never posted as cash),
  §2.4 (no implicit exchange-rate bridge), §2.5 (balances are derived), §2.6 (the experiment report's
  posture), §10.1, §27.2, §32; §28 Phase 9

- **Context:** §1.1 opens the spec with `REAL_SETTLED_NET_PROFIT` and §32 closes it with the same
  sentence; §28 Phase 9's acceptance asks for both figures by name. Nothing computed either. ADR-097 and
  ADR-098 gave the last two deduction terms a path, so the formula became computable for the first time.

- **Decision:**
  1. `profit.report(conn, book)` sums §1.1's formula and returns **every term beside the total**, derived
     on read and stored nowhere (§2.5, Charter C3) — §2.6's experiment report's posture, one level up.
  2. **The second figure needs a rate, and this module must not choose it.** §2.2 permits shadow-pricing
     RESOURCE *for reporting*; §2.4 forbids an implicit bridge. So `declare_shadow_rate` (migration 0039)
     records micro-USD per RESOURCE unit with who declared it, and until someone does, the report
     abstains with the reason.
  3. **The autonomy adjustment is real-profit-only.** A USD_SIM report carries the first figure and
     abstains on the second: subtracting a USD_REAL-equivalent from synthetic profit is precisely §2.4's
     bridge.
  4. Human labour is **billed + subsidised** (`experiments._human_labour`'s rule, colony-wide), so
     absorbing more unpaid work makes the colony look *more* expensive, which is what §1.1 asks for.
  5. **Free tiers are local-model calls** — zero in USD_REAL, metered in RESOURCE. The mock provider is
     excluded: a test double is not a subsidy.
  6. §1.1's operating-cost terms and donated infrastructure are **named as unmeasured on every report**,
     never folded into a 0.
  7. `mitosis profit [--book]` and `mitosis set-shadow-rate --micro-usd-per-unit N --by WHO`.

- **What it displaced, and why:**
  - *A default rate.* Any number the code picked would be §2.4's bridge wearing a reporting label, and
    every profit figure the colony ever published would silently depend on it.
  - *Reporting 0 when no rate exists.* A 0 reads as "nothing was subsidised" — the claim §1.1 exists to
    disprove, and the direction that flatters the colony.
  - *Reading net revenue for the first term.* §1.1 subtracts refunds and chargebacks on their own lines,
    so net would deduct them twice. ADR-097's gross-reader guard caught this in review, and `profit.py`
    is now listed there with its reason instead of being waved through.
  - *Storing the report.* §2.5's cached-derivation trap; a test asserts no table whose name contains
    "profit" exists.
  - *A `--since` window.* Every colony reader it sums would need one, and a balance has no window at all.
    Logged rather than half-built.

- **Verification:** 11 guards teeth-checked, 11 CAUGHT — the abstention replaced by a figure (P1),
  subsidised minutes dropped (P2), local compute uncounted (P3), fees counted twice (P5), gross read as
  net (P6), a synthetic book given an autonomy figure (P7), the RESOURCE book given a profit (P12), the
  golden scenario declaring no rate (P13). **P8 and P9 first reported WRONG-FAILURE, and the reason is
  worth keeping:** deleting the Python guard on a non-positive rate, or on an unnamed declarer, still
  fails its test — migration 0039's CHECK constraints refuse the row — so the guard is defended at two
  layers and my expected text named only one. Re-run against the schema's message: CAUGHT. Golden 40 →
  41; the declared rate posts nothing, so only an audit count and the new `profit` section moved. 1540
  tests pass; ruff and docs-facts clean.
  **Corrected before commit:** the golden comment claimed the run pins USD_REAL at 0 revenue *and* 0
  spend. It settles one USD_REAL reservation of 20, so real profit there is −20 — the second claim this
  session caught by checking the artifact rather than reasoning about it.

- **Consequences:** §1.1's formula is complete but for its operating-cost terms. The rate is flat across
  labour and compute where §1.1 lists them separately; free tiers are keyed on the provider rather than
  the price, so a hosted free tier is missed; donated infrastructure is unrecorded. All logged.

## ADR-100: The colony's one legal identity is an operator attestation, and the payment account is a label the schema cannot mistake for an account

- **Status:** Accepted
- **Spec ref:** §0.3 (a Cell may explain, never define), §3.6 (corrections are new records), §16.3–§16.4
  (legal identity is non-inheritable; reproduction must not escape liability), §21, §27.1, §28 Phase 9
  ("one legal business identity, one narrow product class, one merchant channel")

- **Context:** Since ADR-097 the colony records revenue, refunds, chargebacks and fees — every one of
  which attributes to a legal person who appeared nowhere in the database. The operator asked (2026-09-16)
  for the identity and payment account to live in the kernel rather than in a document.

- **Decision:**
  1. `trial_identity.attest` records who the colony trades as: operator-only, append-only, latest wins by
     `rowid`, and a withdrawal is a new row carrying its own basis (§3.6) — the shape ADR-041's rights
     attestations and ADR-062's buyer attestations already use, reused rather than reinvented.
  2. **The payment account is a label, and the schema is the guarantee.** Migration 0040's CHECKs refuse
     eight consecutive digits and the obvious secret prefixes, so no caller — present, future, or
     forgetful — can store a card, IBAN or key. `attest` refuses more (twelve digits in total, markers, a
     length cap) with a message naming what to write instead. **A grouped IBAN has no run of eight**, so
     the Python total-digit rule is the only guard for that shape; it has its own test, and the teeth-check
     confirms nothing else catches it.
  3. **§16.3's other half.** `genome.NON_INHERITABLE_SENSE` has refused a `legal_identity` gene since the
     genome shipped — "Phase 9 has exactly one, and it is the colony's" — written before anything could
     declare one. A test pins the two together, so allowing the gene fails here.
  4. **Nothing is gated on it yet**, and that is deliberate: §27.1's `real_commerce` flag is off, so a gate
     refusing a listing without an identity would never be exercised. Logged with the channel work.
  5. `mitosis profit` names whose profit it is, or says "trading as: nobody".

- **What it displaced, and why:**
  - *Recording it in a document.* Then nothing attributes a sale, and the record drifts from the books the
    same slice just built.
  - *Storing the account itself.* This colony records money; it never moves it. An account number has no
    use here and a large downside, so it should be **unrepresentable**, not "handled carefully" —
    ADR-047's rule applied to a credential rather than to a foreign key.
  - *A per-Cell or genome identity.* §16.4's liability escape, exactly: reproduce, keep the asset, leave
    the obligations.
  - *Filing it through §23's approval queue.* ADR-041's argument, unchanged: the queue is where a Cell asks
    to act, and a Cell that can nominate the colony's legal identity holds a lever on who is liable.
  - *A jurisdiction vocabulary.* Free text until something branches on it; a list nobody reads is a false
    assurance.

- **Verification:** 11 guards teeth-checked, 11 CAUGHT — the secret-marker and total-digit rules (I1, I2),
  a withdrawal carrying an identity (I3), half an identity (I4), earliest-wins ordering (I5), a withdrawal
  reading as in force (I6), the audit trail losing what it displaced (I7), a Cell-reachable module gaining
  a raw INSERT (I8), the schema's label CHECK (I9), the golden scenario storing an account number (I10),
  and the genome's tripwire (I11). Golden 41 → 42: one audit event type and the new `trial_identity`
  section, no money moved. 1565 tests pass; ruff and docs-facts clean.

- **Consequences:** §28 Phase 9 still needs the liability reserve, a merchant channel, and §1.1's
  operating-cost terms. The identity is a single row-space; Phase 10's "multiple brands/legal entities"
  would need a subject key like `rights_attestations` carries. Both logged.

## ADR-101: A wake whose model call failed at the provider is its own outcome — not the Cell's unparseable reply

- **Status:** Accepted
- **Spec ref:** §24.2 (a material provider change is an environment regime change, "so provider drift is
  not mistaken for Cell evolution"), §24 intro ("retries controlled failures"), §24.1 (every call
  traceable), §4.4 / Charter C7 (the `failed` vs `execution_unknown` split), §0.3, §19.4; ADR-022,
  ADR-069, ADR-070

- **Context:** Observed 2026-09-15. Ollama's Metal backend had died — a direct
  `curl localhost:11434/api/generate` answered `HTTP 500 llama-server process has terminated:
  MTLLibraryErrorDomain` — and `mitosis wake --provider ollama --model qwen2.5` printed
  `Deliberation … (unparseable) … repaired: yes … reason: reply is not JSON: Expecting value: line 1
  column 1 (char 0) (repair reply also failed to validate …)`. The `model_calls` table held both calls,
  original and `:repair`, each `status = failed` with the provider's error in `error_text`. **The gateway
  classified it correctly; the deliberation layer overwrote that classification with a story about the
  Cell** — and then spent ADR-069's one repair call re-prompting the provider that had just gone down.

  The mechanism is one line: `gateway.call_model` does not raise on a provider failure, it records the
  outcome and *returns* the call, so `call.response_text or ""` hands `proposal.parse` an empty string,
  which raises `ProposalError`, which is indistinguishable from a model that ignored the schema.

  **ADR-069 wrote the premise down and it was false.** Twice: "the first call is known to have
  **succeeded and been billed** (it returned response text; `ProposalError` only fires after that)", and
  "A provider-level failure on the repair call itself needs no special handling — `gateway.call_model`
  already converts that into a `failed` `model_calls` row rather than raising, so it flows through the
  same 'reply text failed to validate' path as an ordinary malformed reply." The second sentence is the
  first sentence's own counter-example, sitting four paragraphs below it: a `failed` row is exactly the
  case where nothing was returned and nothing was billed.

- **Decision:**
  1. **`gateway.call_failure(call)`** — `None` when the call succeeded, otherwise one line naming the
     status, the provider and the gateway's already-redacted `error_text`. It lives in `gateway` because
     that is the layer that *wrote* the status, and it sits below all three callers, so no seam is
     needed. Every caller of `call_model` now has one question to ask before it reads a reply.
  2. **A fourth deliberation status, `call_failed`** (migration 0041 rebuilds the CHECK; SQLite cannot
     ALTER one). §24.2 asks for provider change to stay distinguishable from Cell behaviour, and `status`
     is what every reader groups by — a clearer `failure_reason` is prose that no query separates. The
     rebuild is also the one chance to make the row shape unrepresentable rather than merely correct
     (ADR-047), so two CHECKs ride along: a `call_failed` row names the call that failed (one naming
     none is a refusal wearing the wrong status) and names no repair (decision 3, in the schema rather
     than only in the module that implements it).
  3. **No repair.** `MAX_PARSE_REPAIR_ATTEMPTS` re-prompts a model that answered badly; there is no reply
     to re-prompt about, and the only provider a repair could reach is the one that just failed. A wake
     lost to an outage now costs one call, not two.
  4. **The repair call and every workflow step ask the same question**, because each is a
     `gateway.call_model` returning the same shape. A repair that fails at the provider still ends the
     wake `unparseable` — the *first* reply genuinely did not validate, and that outcome is the Cell's —
     but the note says the second call returned nothing rather than returning something invalid. A
     workflow step that fails keeps the draft exactly as a step whose reply failed to validate does, and
     the wake is still `proposed`: the outage costs the refinement, not the proposal.
  5. **`failure_reason` repeats the gateway's text rather than composing one.** §0.3's discipline applied
     between two kernel layers: the layer that observed the failure defines it. It also keeps Charter C14
     intact with no second redaction, since `_handle_failure` already ran `providers.redact`.
  6. **`scripts/measure_parse_compliance.py` reports call failures beside the parse rate.** Its own
     docstring had named this hazard ("a slow local model is recorded as an unparseable empty reply — a
     timeout wearing a compliance failure's clothes") and worked around it by not using the CLI. The
     workaround is still right for a different reason — a timeout still loses the wake — but the
     misclassification is now fixed at the source rather than avoided.

- **What it displaced, and why:**
  - *A clearer `failure_reason` inside `unparseable`.* Rejected: the rate this repo actually computes is
    `proposed / n` over `status`, and the golden snapshot pins `status` per deliberation. Prose does not
    separate a denominator.
  - *Reusing `refused`.* Rejected: a refusal is the loop declining **before** it spends, and it records no
    context because none was assembled. This wake assembled context, reserved, and reached a provider.
  - *Raising `DeliberationError` instead of recording.* Rejected for the same reason a dead Cell's wake is
    recorded rather than raised: "this Cell could not think" is a fact that should appear in a query, and
    a raise would also abort the rest of a `run-wakes` batch on the first outage.
  - *Keying the guard on an empty `response_text` instead of the call's `status`.* Rejected, and the
    rejection is tested: a model that answers with nothing **did** answer, and that call succeeded, was
    billed, and deserves its one repair. Keying on the text would reclassify the Cell's own empty reply
    as the provider's fault and stop re-prompting a model that can be re-prompted.
  - *Re-enqueueing the wake, or leaving the event unprocessed so the Cell gets its wake back.* Rejected
    here: it changes what Charter C6's idempotency means (a `wake_key` that sometimes does not settle the
    wake), and an automatic retry against a provider that is down is the unbounded-cost shape ADR-069's
    own bound exists to prevent. Logged as an open question with its consequence stated below.
  - *Porting the fix to `auditor.py` and `content_audit.py` in this slice.* They have the identical
    defect — `_parse(call.response_text or "")` — and it is arguably worse there, because a rejected
    audit is a §10.4 fitness fact about the Auditor. But an audit's outcome is a different schema
    decision (what an `audits` row says when no verdict was produced), and ADR-070 established that an
    extension to the Auditors earns itself rather than being assumed. Logged, with the stale ADR-022
    comment it leaves behind.
  - *Adding a provider outage to the golden run.* Rejected: the scenario would need a failing provider
    double built for it, the path is deterministic and pinned by tests named for it, and no snapshot
    field changes — the expectation hash is unmoved at version 42, which is the honest outcome for a
    slice that adds an outcome the fixed scenario never produces.

- **Verification:** 15 guards teeth-checked, 15 CAUGHT — the first-call guard removed, twice (the status
  it records and the repair it must not buy), `call_failure` always reporting success, the guard keyed on
  reply text instead of status, the repair guard removed, the status CHECK not admitting the new value, a
  status declared in Python the schema does not admit, either row-shape CHECK dropped (and both at once),
  the rebuild dropping the `wake_key` UNIQUE, losing a row, or not recreating the index, the audit event
  naming the wrong outcome, and the workflow-step guard removed. The UNIQUE check first came back MISS:
  it was passing on the fixture's dangling genome reference — the migration re-enables foreign keys on
  its last line — so it now disables them again and matches the error by name. 1577 tests pass, golden
  run exact at version 42, ruff and docs-facts clean. Reproduced end to end before and after with
  `OLLAMA_HOST` pointed at a dead port: one `failed` call, both reservations released, nothing settled,
  and `Deliberation … (call_failed) … reason: model call failed at provider ollama: cannot reach ollama
  at http://localhost:9 …`.

- **Consequences:** A wake lost to an outage is still **consumed** — `run_wake_event` marks the event
  processed, and the `wake_key` guard returns the recorded `call_failed` deliberation on redelivery — so
  a colony-wide outage silently eats an epoch's scheduled wakes. That was true before this slice and is
  now visible in one query instead of hidden inside a parse-failure rate. `auditor.py` and
  `content_audit.py` still record a provider outage as an Auditor that produced nothing usable, and
  `auditor.py`'s comment "The call is bought and committed by now (ADR-022)" is false on exactly that
  path. Both logged in FUTURE_BUILD_HOOKS and PRIORITIES.

## ADR-102: A repair turn that names only the error specifies the whole reply — so it names every required key, and asks for an edit rather than a reply

- **Status:** Accepted; `proposal.always_required_keys()`, `deliberation._repair_instruction`,
  5 new tests across two files, no migration, golden unchanged
- **Spec ref:** §24 (intro: "validates structured output"), §15.1, §23.5, §0.3; ADR-049, ADR-050,
  ADR-068, ADR-069 (the mechanism this corrects), ADR-070

- **Context:** One paid wake on 2026-09-16 (`claude-haiku-4-5`, `mitosis wake --provider anthropic`)
  spent two calls and recorded nothing, and the second reply was **worse** than the first:

  | turn | reply | rejected for |
  | --- | --- | --- |
  | 1 | `{"kind": "abstain", "summary": "No proposal at this scheduled cycle."}` | `rationale: Field required; estimated_cost_minor_units: Field required` |
  | 2 | `{"kind": "abstain", "rationale": "…", "estimated_cost_minor_units": 0}` | `summary: Field required` |

  The model supplied the two fields the error named and dropped the `summary` it had already
  produced correctly. Between them the two replies contain a complete, valid proposal; neither one
  is.

### ADR-069's own stated reason is what produced this

`_repair_instruction`'s docstring named the design choice: point at the specific error rather than
repeat the schema, because "the schema is already the first turn's own content, still in context,
and restating it would waste tokens on the part that was never the problem." The premise is true —
the schema *is* still in context. The inference does not hold. **On a small model the part that was
never the problem is precisely what gets dropped**, because a follow-up turn naming two field names
does not read as a patch to an object; it reads as a specification of the reply. The model answered
the question it was asked.

This is the second time an ADR's own premise turned out to be the defect (ADR-101 found ADR-069's
"the first call is known to have succeeded and been billed" disproved four paragraphs below itself).
Both were unfalsifiable in this suite for the same reason: `MockProvider`'s reply is an input, not a
response to the wording (ADR-049), so no test could see either one.

### What shipped: the repair turn says two things the error alone could not

- **Edit, do not regenerate.** The failed reply is *already* the middle message of the repair
  request — ADR-069 built that and argued for it. What was missing was an instruction pointing at
  it: "Correct the JSON object you just sent. Do not write a new one: keep every key you already
  sent, with its value unchanged, and change only what the error above names. A key you got right
  is still right." This adds no message and no context; it changes what the model is told to do with
  one it already has, which is why it is the cheap half of the fix.
- **The whole required-key list**, from a new `proposal.always_required_keys()`. This covers the
  case an edit instruction structurally cannot: a first reply that was not JSON at all has no object
  to edit *from*, and that is the most common unparseable shape this repo has measured.

`always_required_keys()` is derived — the `_prompt_schema()` skeleton minus `KIND_PAYLOADS.values()`
— for the reason that function's own docstring gives about itself: a hand-written second copy drifts,
and the failure lands on every Cell at once. It carries `risk_tier`'s one exception (`abstain`,
ADR-068) as prose and interpolates `ProposalKind.ABSTAIN.value` rather than spelling it.

### The §15.1 cost, paid deliberately

This spends roughly 40 tokens of a repair turn that the prior design spent zero on, on exactly the
"part that was never the problem." §15.1 bounds the *per-wake* budget, and the trade is not close:
the alternative price, measured once, is a whole second billed call returning nothing. A repair turn
is also the one place in the loop where the token argument is weakest — it exists only on the path
where the cheap version has already failed.

### Why the kernel does not merge the two replies

The tempting fix is the third one: validate the repair reply and, where a field is absent but was
present and valid in the first, carry it forward. Both observed replies are in hand; between them
the object is complete. Rejected, and the reason is not §0.3 — a proposal is an *intention*, not the
canonical result §0.3 governs, and the kernel composing one breaks something else:

- **It manufactures an utterance no Cell made.** A merged object pairs a `summary` from turn 1 with
  an `estimated_cost_minor_units` from turn 2 and asserts the pair as one Cell's proposal. Nothing
  checks that the two agree; the model that wrote the second was, on the evidence, no longer
  thinking about the first. §23.4 names "misleading summaries" as a thing the approval queue must
  detect, and a kernel-built summary/cost pair is one the Cell can disown and the Auditor cannot
  attribute.
- **It is exactly the salvage `proposal.parse` refuses**, one layer up. That docstring is explicit:
  an unparseable reply "is never salvaged into a 'best effort' record, because a half-understood
  intention stored next to fully-understood ones is worse than an honest gap." Merging is
  half-understanding assembled from two halves.
- **It breaks the premise ADR-070 used to exclude the Auditors.** Repair is defensible in
  `deliberation` and nowhere else because it *reformats and never re-judges*. A merge is neither: it
  is the kernel authoring part of a Cell's output. Ship it and ADR-070's line — the one keeping
  parse-repair away from an independent §10.4 verdict — no longer has a principle behind it.

Restating the *whole* schema (the other candidate) was rejected as strictly more tokens for the same
effect: the observed failure is a required key going missing, the required keys are five, and
`_payload_rule`'s conditional prose is already the weakest-read part of the first turn (lesson 3 in
`_prompt_schema`'s docstring).

### `rationale` and `estimated_cost_minor_units` stay required for `abstain`

Weighed because the failure landed on an abstain reply, and rejected — relaxing them would have
"fixed" this by deleting the data:

- ADR-068 already made and scoped this argument. `risk_tier` is the one field an abstaining Cell
  structurally cannot state (§23.1 classifies *actions*; there is no action). For `abstain` the
  rationale is the **entire content** — "nothing worth doing, because X" is the whole proposal — and
  the cost is trivially 0, which the prompt already says.
- §23.5: the approval queue is part of the environment and will be optimised against. A zero-content
  `abstain` is an outcome a Cell under selection pressure can always emit at no cost, and §10.3/§10.5
  need "nothing worth doing because X" to stay distinguishable from "produced nothing."

**The under-filling invitation is real, and it is not where it looked.** "Most wakes produce nothing"
is the trailing sentence of the **`artifact`** key's description, not a statement about abstain
wakes — it sits one clause after `never with kind "abstain"`, which is what makes it read that way.
The likelier cause is the general rule two lines below it: "Leave out any key you are not using" /
"A key you have nothing to put in is left out entirely, never sent empty." An abstaining model
applying that rule to `rationale` produces the observed reply 1 exactly. That is a prompt-wording
hypothesis, and this repo does not tune prompt wording without a live run (ADR-049); logged in
FUTURE_BUILD_HOOKS and PRIORITIES rather than guessed at here.

### What it displaced

- **Merging the two replies field by field.** Rejected per the three arguments above; the ADR-070
  one is decisive, since the merge removes the principle that bounds repair to this module.
- **Restating the entire schema in the repair turn.** Rejected: more tokens, and the part it would
  add beyond the required keys is the part measured to be read most weakly.
- **Relaxing `rationale`/`estimated_cost_minor_units` for `abstain`.** Rejected per ADR-068's own
  scoping discipline: it treats a symptom of the repair turn as a fault in the schema, and it
  deletes the only content an abstention carries.
- **Leaving the repair turn alone and accepting the second call as a coin flip.** Rejected: ADR-069
  bought the second call on the argument that it "would probably lift the rate a lot." A repair that
  can hand back a reply strictly worse than the one it repaired is not a lift; it is a second charge
  for a regression.
- **A live re-measurement in this slice.** Not run — a paid call is the operator's to authorise, and
  the machinery a measurement would use (`scripts/measure_parse_compliance.py`, which ADR-101 taught
  to separate call failures from parse failures) is already built. Logged as owed.

### Verification

- **5 guards teeth-checked, 5 CAUGHT.** ADR-069's error-only instruction restored verbatim fails
  both new guards — the structural one names the missing keys, and the end-to-end one reproduces the
  observed wake as UNPARSEABLE. Dropping the assistant turn from the repair request fails the test
  that the object being edited is actually present. `always_required_keys` narrowed by hand fails
  the skeleton-agreement test; narrowed past a parser-required field it fails the test that binds
  the list to `Proposal` rather than to the prompt. One first reported WRONG-FAILURE on a truncated
  pytest tuple repr, not a bad mutation — re-run against the assertion's actual text.
- **What the tests cannot prove, stated in the test itself.** `_SuppliesExactlyTheKeysNamed` encodes
  one measured behaviour (`claude-haiku-4-5`, 2026-09-16: reply carries exactly the keys the turn
  names) and its docstring says so. The conditional it establishes is the honest one: *if* a model
  supplies the keys it is told to supply, the repair turn has to tell it all of them. Whether this
  model now repairs correctly needs a paid wake.
- **Golden unchanged.** No scenario reply is malformed, so `_repair_instruction` is never rendered
  in the replay and no prompt length moves — unlike ADR-068, which shifted `input_tokens` by a
  constant because it lengthened the *first* turn. This slice touches only a turn the golden run
  never reaches.
- **Confirmed live, one operator-approved paid call (2026-09-17, `claude-haiku-4-5`).** The
  observed conversation replayed through the production path — `_attempt_parse_repair`, the real
  gateway, the real provider — with reply 1 and its validation error verbatim. The model **kept the
  `summary` byte-for-byte** ("No proposal at this scheduled cycle."), added a `rationale` and
  `estimated_cost_minor_units: 0`, and correctly omitted `risk_tier` for `abstain`. `repaired`;
  1,716 in / 196 out; 2,696 micro-USD recorded as 1 minor unit; conservation and the hash chain
  green in all three books. One call, because the first reply's outcome was already known and
  re-buying it would have answered nothing.

  **What this is and is not.** n=1, one model, one replayed conversation: it shows the specific
  observed failure no longer reproduces. It is not a repair *rate*, and the wording is not proven
  better in general — that needs the per-kind campaign PRIORITIES now carries.

  **It also answered the `abstain` question from the other direction.** The rationale the model
  supplied was substantive — generation 0, no revenue, every channel and tool OFF, "proposing work
  I cannot execute serves no purpose." That is exactly the content §10.3/§10.5 need in order to
  tell "nothing worth doing because X" from "produced nothing", produced on the first ask once the
  field was actually requested. Relaxing the requirement would have thrown it away.

## ADR-103: A self-critique loop whose control flow is a LangGraph graph — and nothing else is

- **Status:** Accepted
- **Spec ref:** §14.1 ("critic addition/removal"), §16.3 (workflow structure inheritable), §17.5 (durable
  workflow engines deferred), §19.3 (dependency allowlist), §2.5, §23.5, §24.3, Charter C4, C6, C15;
  ADR-069, ADR-093

- **Context:** ADR-093's structures are fixed sequences — `iterative_refinement` is draft → revise,
  `parallel_review` is draft → draft → review. A structure that *branches on what a step said* and
  *loops* until a condition holds is the next thing §14.1's "critic addition" reaches for, and it is the
  shape hand-written straight-line runners express worst: the stop conditions end up scattered across
  nested ifs. It is also the shape a graph framework exists for.

- **Decision:** `self_critique_loop` joins the kernel's closed set. After a validated draft: *critique*
  (one call; reply `{"verdict": "keep"}` or `{"verdict": "revise", "issues": [...]}`), and on revise,
  *revise* (one call shown those issues), repeated up to `MAX_CRITIQUE_REVISIONS = 2`. The control flow
  is a LangGraph `StateGraph` in `workflow_graph.py`: nodes `critique` and `revise`, a conditional edge
  out of each, a list reducer for step records, `recursion_limit = 2·max + 2`. The runner in
  `deliberation` hands the graph two closures over `_workflow_call`; the graph never sees anything else.

- **What it displaced, and why:**
  - *LangGraph's checkpointer (durable, resumable graph state).* The obvious reason to adopt the
    framework, and refused. Every step is already `gateway.call_model` on
    `deliberation:{wake_key}:workflow:{step}:{round}`, so a redelivered wake replays each billed reply and,
    the replies being identical, walks the same edges to the same proposal — pinned by
    `test_a_self_critique_wake_that_crashed_replays_its_path_without_paying_again`. A checkpointer would
    be a second record of "where this wake got to" beside `model_calls` (the §2.5 trap) and is the durable
    workflow engine §17.5 defers.
  - *Letting LangGraph make the calls* (a LangChain chat-model node). That routes a model call around the
    gateway — no reservation, no metering — which is C4's violation in a friendlier API. The graph module
    imports nothing from `mitosis`, pinned by an AST test, so it has no path to a provider.
  - *Hand-writing the loop.* Fifteen lines would do it, and for this graph alone that would be defensible.
    The graph was chosen because the next structures §14.1 lists (a critic on another family per §24.3,
    role decomposition) are graphs too, and because a compiled graph draws its own diagram
    (`workflow_graph.mermaid()`) that documentation cannot drift from.
  - *A numeric confidence as the stop condition.* A probability the Cell writes about its own proposal
    sits next to §8.5's scored forecasts and invites being read as one. A keep/revise verdict with named
    issues is what the revise step needs anyway. The verdict never leaves the wake — not a prediction, not
    a review input, not fitness — so the only thing gaming it buys (§23.5) is more or fewer calls the Cell
    pays for, capped.
  - *A required dependency.* LangGraph brings ~20 transitive packages (langsmith, httpx, websockets, …)
    and §19.3 treats each as untrusted. It is the optional `langgraph` extra; without it the runner
    records `not attempted: … pip install 'mitosis[langgraph]'` and keeps the draft, exactly as an
    unaffordable step does.
  - *Breeding it in the simulator.* `SimulationPolicyProvider` only ever replies with a proposal, so a
    critique never validates and the loop is a single pass plus one billed call, every time. Selection
    would punish a surcharge the simulator invented, and seeded runs would depend on which extras are
    installed. `mutation._NOT_BRED_STRUCTURES` names it; a founder genome may still declare it.

- **Still self-critique, not §24.3 criticism** — one wake holds one provider. The graph makes a critic
  on another family a node away; that is logged, not built.

- **Verification:** 13 tests in `tests/test_workflow_structure.py`; 10 teeth-checks CAUGHT (revision cap
  removed — the recursion limit then stops it; rounds sharing a key; the second critique shown the draft;
  the revision not shown the issues; a failed later revision dropping an earlier valid one; a missing
  extra raising out of the wake; the verdict accepting unknown keys; a revise naming no issue; the graph
  module importing the kernel; the simulator breeding it). Golden run unchanged. No live-model run: the
  local Ollama failed every call on the day (see BUILD_RECORD).

## ADR-104: LangSmith tracing is opt-in, enforced off otherwise, and a view — never the record

- **Status:** Accepted
- **Spec ref:** §19.3 ("network disabled by default; egress domain allowlist"), §2.5, §7.1, ADR-022,
  ADR-085

- **Context:** An operator asked for LangSmith traces of the colony's wakes, in project
  `my-first-agent`. A trace ships prompts — genome content, ledger state, `UNTRUSTED_EXTERNAL` tool
  results — and replies to a third-party server. §19.3 puts network off by default.

- **Decision:** `tracing.enabled()` is true only when `LANGSMITH_TRACING=true` and a non-blank
  `LANGSMITH_API_KEY` are both set in the operator's own shell, no `network_seal.sealed()` block is
  active, no `tracing.suppressed()` block is active, and `langsmith` imports. Every span enters
  `tracing_context(enabled=<that decision>)`. Three spans: `cell_wake` around `deliberation.deliberate`
  (the root), `model_call` (`run_type="llm"`) around the provider call in `gateway.call_model`, and
  LangGraph's own node runs, which nest without glue. `golden.run_scenario` runs suppressed;
  `tests/conftest.py` strips both variables for every test.

- **What it displaced, and why:**
  - *LangSmith's own switches* (`LANGSMITH_TRACING` alone, or `LANGCHAIN_TRACING_V2`). A variable exported
    for another project would start shipping this colony's wakes. The explicit context overrides them —
    checked against a local collector, and pinned by
    `test_off_overrides_langchains_own_environment_switches`.
  - *Tracing during sealed runs.* The flight simulator's seal (ADR-085) promises nothing leaves the
    interpreter; LangSmith's uploader would try, and would either break the seal's promise or trip it.
  - *Reading traces back* (e.g. costs from LangSmith). `model_calls` and the ledger are the record; a
    trace is a copy elsewhere. Nothing in the kernel reads one, so a lost upload changes no outcome. Each
    `model_call` span carries `model_call_id` and the idempotency key so the copy can be joined to the
    record, never the reverse.
  - *Letting a tracing fault surface.* The gateway's span opens after both reservations commit; a raise
    there would strand them. Span entry and `finish` swallow their own exceptions; the traced block's
    exceptions pass through unchanged.
  - *Wrapping the providers* (a `wrap_anthropic`-style client). The gateway is the one choke point every
    call already passes, whichever provider — mock, Ollama, Anthropic — so one span there covers all three.

- **Not done:** redacting fields before upload (an opted-in operator gets the full prompt), and an
  egress allowlist entry for the LangSmith endpoint — both logged.

- **Verification:** 15 tests in `tests/test_tracing.py` against a collector on 127.0.0.1; 6 teeth-checks
  CAUGHT (context not entered; seal ignored; `suppressed()` ignored; the golden run not suppressed; a
  tracing fault escaping the gateway; the flag alone opting in). CLI end to end: three wakes, three traces
  in `my-first-agent`, flushed before exit.

## ADR-105: The colony dashboard is read-only by construction, runs no script, and listens on loopback

- **Status:** Accepted
- **Spec ref:** §2.5 (balances derived, one answer per question), §19.3 (network off by default), §19.4
  (no untrusted content treated as trusted), §23.3 (the operator must see what is waiting), §30.1 (avoid
  unnecessary frameworks)

- **Context:** An operator watching a live colony had `mitosis status`, `health`, `cell-fitness`,
  `approvals` and `proposals` — five verbs, each a terminal snapshot. The request was one place to watch
  Cells.

- **Decision:** `mitosis dashboard` serves a server-rendered page (`src/mitosis/dashboard.py`, standard
  library only) on 127.0.0.1: an overview (scheduler health, book integrity, population, real spend against
  every cap, the approval queue, model calls, every Cell's record, recent wakes with their workflow steps),
  a per-Cell page (genome, wakes, predictions, each billed call by step), and `/api/overview` as JSON.

- **What it displaced, and why:**
  - *Trusting the readers not to write.* Every request opens `file:…?mode=ro`, so SQLite refuses a write —
    a lazy checkpoint, a future cache — rather than letting it mutate the books being watched. Every kernel
    reader the page calls was first probed on a read-only connection. It never migrates: a database behind
    the code is refused with the command that fixes it, because a monitor that silently migrated would be an
    operator action nobody took.
  - *Re-deriving numbers in SQL.* Figures come from `death.contribution`, `real_spend_breaker.snapshot`,
    `approval.queue`, `ledger.get_balance` — so the page cannot disagree with `mitosis status` (§2.5).
    Direct queries are listings no reader exists for (wakes, predictions, calls), read only; a test pins
    the numbers to the readers.
  - *A JavaScript frontend* (React, htmx, a chart library). Proposal text is model-written and a model reads
    `UNTRUSTED_EXTERNAL` tool results, so an injected `<script>` is a realistic input. Every value is escaped,
    refresh is a `<meta>` tag, and `Content-Security-Policy: default-src 'none'` forbids scripts — two layers,
    each teeth-checked alone. It also keeps the repo's dependency list at pydantic (§30.1).
  - *A `--host` flag.* The page shows balances, spend caps and model output, and has no authentication.
    `serve`/`make_server` take no host parameter (pinned by a signature test); remote viewing is an SSH
    tunnel's job.
  - *Hosting it* (an Artifact, a cloud page). Colony data would leave the machine by default — §19.3 again.

- **Verification:** 9 tests in `tests/test_dashboard.py`, including serving every page and checking the
  database file is byte-identical afterwards. 5 teeth-checks CAUGHT (read-write connection, escaping
  removed, CSP removed, a stale database served, every-interface bind). Checked in a browser against
  `scripts/demo_colony.py`'s colony at desktop and phone width.

## ADR-106: A real sale is held against its refunds in its own transaction — as restricted cash, not as spend

- **Status:** Accepted
- **Spec ref:** §2.3 ("real reserves" beside cash balances), §2.5 (balances are derived), §3.6, §10.2
  ("unsettled liability exposure" as its own dimension; no scalar collapse), §16.3 (liability-linked
  assets), §28 Phase 9 ("full liability reserves")

- **Context:** The operator asked (2026-09-24) to get the colony to real revenue as fast as possible, and
  chose "100% held until the refund window closes" for the reserve. `liability_reserve` had been a §31
  Phase-1 account since migration 0001 with nothing posting to it, so a real sale landed in its Cell's
  cash and was spendable at once while the buyer could still take it back; a refund after the Cell spent
  it drove cash negative with nothing set aside.

- **Decision:**
  1. **Operator policy, append-only, latest wins by rowid** (`liability.declare_policy`,
     `mitosis set-reserve-policy`): a share in basis points (1–10000) and a window in days (1–730). There is
     no zero or withdrawn policy — Phase 9 has no reserve-free mode. No policy means nothing is held and
     `profit.report` names the abstention (ADR-042); a real sale is never refused, because it already
     happened.
  2. **The hold is posted by `record_revenue` in the sale's own transaction**, USD_REAL only, and only for
     a payment posted *now* — a replay of a sale recorded before the policy is never held retroactively.
  3. **A refund or chargeback is paid from the hold first** (`record_reversal` releases up to the reversed
     amount before posting the reversal); the Cell's other cash meets only what the hold did not cover.
  4. **The window's close is derived, never stored** (§2.5): the sale's hash-chained `created_at_utc` plus
     the window of the policy in force at the hold's instant. A later, shorter policy cannot release an old
     hold early. `mitosis release-reserves` returns what is due; it is idempotent.
  5. **`liability_reserve` moves from `SPEND_DESTINATIONS` to `CAPITAL_ACCOUNTS`.** Migration 0042 links
     hold and release to their payment (`provisions_for_transaction_id`, hash-chained when set, a CHECK
     tying it to exactly the two types).
  6. **Held money is money in flight to §10.5's `budget_exhausted`.** Found by hand-verification on a live
     CLI colony: a Cell that spent its budget and then sold under a full hold sits at zero cash — at −40 once
     a processor fee comes out of cash while the gross is held — and `reap` would have killed the colony's
     first successful seller. It is now protected exactly as `committed != 0` already protects a Cell mid-call.

- **What it displaced, and why:**
  - *Keeping the account's old classification* ("a provision the Cell's activity incurred — cost, not
    transfer"). It was written before any policy existed, and the first policy is a hold of the sale's own
    money, not an expected cost. Counted as spend, a 100% hold would tell a Cell through `context` that it
    had consumed a sale it was only asked to wait for, freeze a false spend figure into any coroner report
    written while held, and fold §10.2's "unsettled liability exposure" into net contribution — the scalar
    collapse §10.2 forbids. §2.3 already lists reserves on the balance-sheet side. Nothing had posted to the
    account, so the move changed no existing number. `liability.cell_held` reports the exposure beside
    net contribution instead.
  - *Subtracting held money in §1.1's formula.* §1.1 subtracts refunds, not the possibility of them; a
    held sale that is never refunded was settled revenue all along. Printed beside the figure instead.
  - *A `held_until` column or table.* A second answer that could disagree with the ledger. Transaction
    metadata is outside the hash preimage, so storing it there would also be editable without trace.
  - *Refusing a real sale when no policy is declared.* The money has arrived; refusing to record it only
    makes the books wrong. The gate belongs on the *channel* (a real-commerce claim with no policy or no
    identity in force), logged with that work.
  - *Holding USD_SIM too.* A refund window is a fact about real card networks; tying the shadow economy to
    a wall clock would leak calendar time into sealed runs. It also keeps the golden run's hash unmoved.

- **Verification:** 14 guards teeth-checked, 14 CAUGHT (one after correcting an incomplete mutation): the
  held seller surviving `reap`, the hold itself, Charter C4 refusing held money, the classification, the replay guard, reversals paid from the
  hold and only up to the reversed amount, the window, the policy-at-hold-time derivation, rounding up, the
  USD_REAL-only rule, the hash preimage, and the report's abstention. A zero-percent policy with the Python
  guard removed is still refused by migration 0042's CHECK — two layers, by design.

- **Consequences:** Phase 9 still needs the channel gate (no real-commerce claim without an identity *and*
  a policy in force), a merchant channel, and §1.1's chosen operating costs. A hold released to a Cell that
  has since died lands in a dead Cell's cash, as revenue to a dead Cell already does; §10.2's exposure is
  reported but is not yet a domination axis. All logged in FUTURE_BUILD_HOOKS.

## ADR-107: A Cell may hand over a deliverable and propose nothing else — the `deliverable` kind

- **Status:** Accepted
- **Spec ref:** §0.3, §23 (the queue; §23.3's regeneration of *actions*), §25.2 (a decision carries its
  reason), §28 Phase 8 (production ungated, external use reviewed); ADR-046 (statement kinds), ADR-068
- **Context:** Live, 2026-09-25, in the operator's own colony. A Cell wrote a playbook; the operator
  rejected its next proposal with a revision brief. The revision wake abstained — "the rewrite is in
  progress" — and delivered nothing. Every kind but `abstain` names something to do, and `abstain` may not
  carry an artifact (`_abstaining_produces_nothing`), so "here is the revised work, nothing else to
  propose" had no valid shape. Told explicitly to wrap the rewrite in an experiment proposal, the same
  Cell delivered 17,702 bytes at once.
- **Decision:** A seventh kind, `deliverable` (migration 0043 rebuilds the kind CHECK as 0032 did).
  1. **It requires `artifact`** (`_deliverable_carries_an_artifact`); the schema cannot say so because the
     artifact is linked through the deliberation, not the proposal row.
  2. **It is a statement** (`STATEMENT_KINDS`, beside `strategy`): it asks for nothing, so approval is
     acceptance and nothing consumes its grant; §23.3's regeneration does not reach it.
  3. **It is queued.** Export is already gated (§28 Phase 8 needs nothing more for safety), but the queue
     is the only way an operator can *answer* a Cell: a rejection's reason reaches it through the decision
     note, and every decision — this kind included — wakes it (`WAKE_HUMAN_DECISION`).
  4. The payload rule and the guidance line name it, so a Cell can find it.
- **What it displaced, and why:**
  - *Letting `abstain` carry an artifact.* Abstentions are never queued, so the operator could not reply
    to the one wake that most needs a reply; and "I decline to work" carrying work makes both meanings
    unreadable.
  - *Telling Cells to wrap deliverables in an experiment.* It worked once and makes every hand-over a
    request for an experiment slot the operator must refuse, then selection (§13) scores it as a
    candidate it is not.
  - *`strategy` + artifact.* Already legal, but approving a strategy changes what the Cell is shown from
    then on (ADR-046); accepting a document is not endorsing an operating approach.
- **Verification:** 5 guards teeth-checked, 5 CAUGHT (the artifact requirement, statement status, the
  prompt naming the requirement, the schema CHECK, and selection's forced classification). Three tests
  pinning the old six-kind world were updated deliberately, each naming this ADR. Golden 45 → 46: +103
  input tokens per call, nothing else. Live verification follows in the operator's colony.
- **Consequences:** ADR-046's "the only kind with no consumer" is no longer true of `strategy` alone; both
  statement kinds are listed in `STATEMENT_KINDS`, which is what the regeneration and expiry paths read.

## ADR-108: A Cell revising a rejected draft is shown that draft in full

- **Status:** Accepted
- **Spec ref:** §15.1 (select what is relevant; never the whole history), §15.2 (the artifact index is a
  tier, not the only one), §15.5 (unbounded context), §18.1 (taint travels with content); ADR-107
- **Context:** Live, 2026-09-25. Sent back with five named corrections, a Cell fixed all five and cut its
  playbook from 17,702 to 8,278 bytes — two email templates, troubleshooting and scope creep gone. Its
  context held the rejection note and an artifact *index* (titles, never bodies), so every revision was a
  rewrite from recall that kept only what the note named.
- **Decision:** `context._revision_section` shows the draft in full when the Cell's most recent proposal
  was rejected and carried an artifact — derived on every wake, stored nowhere; a later proposal ends it.
  It is the first optional section, so nothing else can crowd it out. If it cannot fit beside the required
  sections, a small **required** note replaces it saying a draft of about N tokens exists and this budget
  could not show it — never a silent drop, which would reproduce the defect. The artifact's
  `UNTRUSTED_EXTERNAL` taint, if any, carries into the section.
- **What it displaced, and why:**
  - *Required section.* A draft can be ~5,000 tokens against a 1,200-token default; a required section
    that cannot fit makes assembly raise, so every scheduled revision wake would fail outright.
  - *Truncating the draft to fit.* An edit of a truncated draft drops its tail — the regression again,
    now invisible.
  - *Showing every artifact body (widening the index).* §15.1 forbids loading the history; only the one
    draft under revision is relevant.
  - *Quoting v2 automatically when v3 regressed.* The draft shown is the one rejected — the operator's
    note says what to restore, and the kernel does not choose between a Cell's versions for it.
- **Verification:** 4 guards teeth-checked, 4 CAUGHT (rejected-only, latest proposal only, the section
  present, and the oversized draft named rather than dropped). The golden run is unmoved and does not
  cover this path — no scenario proposal is rejected while carrying an artifact — so the tests are its
  only defence. Live verification follows in the operator's colony.
- **Consequences:** A revision wake needs a context budget big enough for its draft (`--context-budget`);
  at the 1,200 default the Cell is told the draft did not fit.
