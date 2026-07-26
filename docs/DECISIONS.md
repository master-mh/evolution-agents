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
