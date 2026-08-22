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
