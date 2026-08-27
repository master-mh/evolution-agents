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
