# MITOSIS Specification

**Working name:** MITOSIS
**Version:** 0.2
**Status:** Founding architecture specification
**Purpose:** A capital-conserving, resource-metered, population-limited evolutionary operating system in which untrusted software organisms ("Cells") discover, build, test, and commercialise economic mechanisms under independently verified selection — with the ultimate measure of success being **real settled net profit after real costs**.

This document is a complete, standalone specification. It supersedes v0.1 (`mitosis_full_build_spec.md`). It is a founding architecture document, not an implementation. The system is built incrementally; the first implementation pass is Phase 0 + Phase 1 only (see §28, §30).

---

# Changes from v0.1

v0.2 keeps the strongest bones of v0.1 — immutable colony kernel, mutable Cells, append-only accounting, staged autonomy, artifact-first exploration, event-driven dormant Cells, model gateway, sandboxed code evolution, the Explorer/Builder/Commercial/Auditor/Immune/Skeptic taxonomy, the synthetic shadow economy, reproducible experiments, quality-diversity search, horizontal module transfer, and the human-approved path to real commerce — and changes the following.

## Material changes carried from the v0.2 revision directive

1. **Profit-first objective.** The colony's ultimate success proxy is real settled net profit after real costs, with an autonomy-adjusted variant that exposes hidden human labour and subsidy. Novelty, synthetic profit, evidence, and reproducibility are explicitly demoted to *proxies* used only during pre-revenue phases (§1).
2. **Three accounting books.** `USD_REAL`, `USD_SIM`, and `RESOURCE` are separated. Conservation holds per book. Synthetic revenue can never offset real cost. Model costs are *mirrored* into `USD_SIM`, never *bridged* (§2).
3. **Ledger hardening.** `ledger_transactions` + `ledger_entries` (multi-leg, sum-to-zero), hash chain, transactional inbox/outbox, external reconciliation posted as new transactions (§3).
4. **Two-phase spend.** Reserve → settle/release, with a crash-recovery sweeper and an `execution_unknown` reconciliation path (§4).
5. **Global real-spend circuit breakers,** enforced independently of Cell budgets, fail-closed, counting reserved spend (§5).
6. **Simulated clock** for all synthetic-market timing (§6).
7. **Colony flight simulator** as a first-class mode; engineering-MVP vs evolutionary-MVP split; mock LLM promoted from test stub to first-class component (§7).
8. **Anti-Goodhart machinery:** train/validation/secret environments, randomised parameters, multiple simulator families, scheduled regime shifts, reality-gap tracking (§8).
9. **Population control and carrying capacity,** birth licences, founder-effect controls (§9).
10. **Profit-directed but multi-constraint fitness,** precision-weighted auditors, objective death criteria (§10).
11. **Evidence-credit anti-gaming,** valid-downstream-adoption rules, reciprocal-adoption detection, decaying delayed credit (§11).
12. **MAP-Elites started at 2–3 dimensions,** raw descriptors stored separately, richer Thompson-sampling posteriors (§12).
13. **Novelty evaluation:** unit-consistent cost, hard gates + Pareto selection, program-native advantage weighting, fake-novelty detection (§13).
14. **Prompt and policy mutation** as first-class evolvable phenotype with counterfactual-twin A/B and provenance (§14).
15. **Cell context assembly:** per-wake budget, memory tiers, compaction, cost attribution (§15).
16. **Genome content addressing** and precise inheritance classes incl. liability-linked assets (§16).
17. **At-least-once event semantics,** idempotent handlers, poison/dead-letter handling (§17).
18. **Shadow-economy taint and quarantine,** with a clean-room migration path (§18).
19. **Sandbox and supply-chain security:** Docker for MVP, gVisor/Firecracker for real-facing; egress allowlists, SBOM, signing (§19).
20. **Data rights, privacy, and IP provenance** on every data artifact (§20).
21. **Shared external reputation** and a central external-action registry to prevent sibling interference (§21).
22. **Knowledge sharing without monoculture** via controlled information flow (§22).
23. **Risk-tiered human approval** with expiry and anti-gaming (§23).
24. **Model gateway drift handling:** provider changes treated as environment regime changes (§24).
25. **Simulation-to-reality promotion ladder** (§25). **Golden-run replay in CI** (§26). Revised `colony.yaml` (§27), build order (§28), MVP acceptance (§29), Phase 0/1 task (§30).

## Amendments introduced in v0.2 (beyond the directive)

These arose from independent review and are **normative** in this spec.

- **A1 — Phase 3 gate softened + pre-registration.** "Evolved beats random" is a research result, not an engineering milestone. Phase 3 is timeboxed, its experiments pre-registered, its gate a pre-registered effect with a confidence interval excluding zero; deeper validation runs as a parallel track (§28 Phase 3). The mock-cell circularity is stated openly: the flight simulator validates the *selection machinery*, not that LLM-driven Cells will evolve usefully (§7.4).
- **A2 — Displacement rule fixed.** A proposed child's *forecast* may never trigger a kill. Displacement targets only Cells already failing objective criteria (§9.3, §10.5).
- **A3 — Signed ledger amounts.** Entries carry a single signed `amount_minor_units`; there is no independent `direction` field to disagree with it (§3.3).
- **A4 — One canonical reservation state machine** including `requested`, replacing the two divergent lists in the directive (§4.4).
- **A5 — Deterministic event ordering** via a total-order tie-break `(effective_time, priority, event_id)`, required for golden-run replay (§17.1).
- **A6 — RESOURCE-book completeness invariant:** every metered op links to exactly one reservation/settlement and reconciles against sandbox/gateway logs (§2.3).
- **A7 — CLI book explicitness:** money commands take `--book`, default `USD_SIM` (§30).
- **A8 — `audit_events` in Phase 1 deliverables** (§30).
- **A9 — Idempotency keys** are globally unique and namespaced `{operation_type}:{natural_key}` (§3.2).
- **A10 — Lineage defined strictly by genome parentage** for population caps; module ancestry is tracked separately (§9.4).
- **A11 — Approval action-splitting detection** via cumulative-exposure aggregation keys over a rolling window (§23.4).
- **A12 — Golden-run expectations versioned;** comparison is semantic invariants *plus* hash, with a migration path (§26.2).
- **A13 — Executable Colony Charter:** constitutional invariants map one-to-one to named CI property tests; breaking one is by definition a kernel change requiring human review (§0.1).
- **A14 — Prediction register:** register-before-outcome, hashed, scored with proper scoring rules; reality gap is a calibration curve (§8.5, §25.2).
- **A15 — Coroner reports:** every Cell death emits a structured post-mortem feeding negative-finding credit and the knowledge graph (§10.5).
- **A16 — Per-phase North Star table:** one honest primary metric per phase; the dashboard headlines the current phase's metric (§27.1, §28).
- **A17 — Governance overhead ratio:** (audit + immune + approval spend) / total spend, tracked against a target band (§10.4).
- **A18 — Chaos drills in Phase 2:** extinction/corruption/crash scenarios in the flight-sim test suite (§28 Phase 2).
- **A19 — Solo-operator model:** approval SLAs, vacation mode auto-pausing external-facing phases, colony metabolic-rate alarm (§23.3).

---

# 0. Core Design Principles

MITOSIS is not a swarm of chatbots with wallets. It is a population of persistent, mutable software businesses operating under an immutable colony kernel. Each Cell is a testable economic hypothesis:

```text
customer + problem + product + acquisition channel + fulfilment + pricing + software
```

## 0.1 The Colony Charter (executable constitution) — Amendment A13

The Charter is the short, constitutional core of the system. It is not prose to be admired; it is a **traceability matrix**. Every clause maps to one or more named property-test IDs that run in CI. A pull request that breaks a Charter test is, by definition, a change to the kernel's guarantees and requires explicit human review — it can never merge as an ordinary Cell-visible change.

| Charter clause | Guarantee | Test ID (Phase where enforced) |
|---|---|---|
| C1 | Ledger balances per transaction and per book; no transaction crosses books | `charter_ledger_balanced` (P1) |
| C2 | Capital is conserved per book across any event sequence | `charter_conservation_per_book` (P1) |
| C3 | Balances are derived from the ledger, never authoritative | `charter_balance_matches_ledger` (P1) |
| C4 | Cells cannot overspend their authorised budget | `charter_no_overspend` (P1) |
| C5 | Global real-spend caps hold, including reserved spend, under concurrency | `charter_realspend_cap` (P1/P4) |
| C6 | Event handlers are idempotent under at-least-once redelivery | `charter_idempotent_handlers` (P1) |
| C7 | Crash at reserve/execute/settle recovers with no double-spend | `charter_crash_recovery` (P1) |
| C8 | Dead Cells cannot act; quarantined Cells cannot reach public-facing tools | `charter_dead_cell_inert` (P1) |
| C9 | Birth requires carrying-capacity permission | `charter_carrying_capacity` (P1/P2) |
| C10 | Every lifecycle transition emits an immutable audit event | `charter_audit_complete` (P1) |
| C11 | Every genome has a canonical hash; all money is integer minor units; all timestamps UTC | `charter_canonical_forms` (P1) |
| C12 | Generated code cannot reach host files, secrets, or unapproved networks | `charter_sandbox_isolation` (P5) |
| C13 | Adversarial-taint artifacts cannot migrate to real-facing execution | `charter_taint_quarantine` (P6) |
| C14 | No API key ever enters Cell state | `charter_no_secret_in_cell` (P4) |
| C15 | Kernel code is not modifiable by any Cell | `charter_kernel_immutable` (P1) |

The Charter grows as phases land, but a clause is never weakened silently: relaxing a guarantee is itself a reviewed kernel change.

## 0.2 Immutable kernel, mutable Cells

```text
IMMUTABLE KERNEL                 MUTABLE CELL
- ledger + treasury              - prompts
- permissions + approvals        - strategy
- model gateway                  - code
- audit log                      - workflow
- evaluator                      - tools
- scheduler + simulated clock    - product
- secret vault                   - market hypothesis
- execution / action router      - pricing
- capital + population allocator - experiments
- kill switches                  - model-routing preferences
- taint / provenance engine
```

A Cell may *propose* a kernel patch; it can never *apply* one.

## 0.3 Verified evidence beats self-reporting

Cells are under selection pressure and cannot be trusted to grade themselves. Canonical metrics come only from independent systems: payment records, synthetic-market events, independent test runners, analytics, sandbox execution results, external evaluators, Auditor Cells, and the ledger. A Cell may *explain* a result; it may never *define* the canonical result.

## 0.4 Staged autonomy

Autonomy is granted tool by tool, phase by phase (see §25, §28). Initial phases have no network from generated code, no real commerce, no external communication, no real payments, no public publishing, and no direct secret access. Nothing begins at real-money autonomy.

## 0.5 Future Build Hooks

- machine-checkable economic invariants beyond the property-test Charter;
- formal methods / TLA+ models of the kernel state machines;
- a signed, versioned Charter with external attestation.

---

# 1. Foundational Objective: The Colony Must Make Real Money

## 1.1 Ultimate success metric

MITOSIS is an economic system. Its ultimate success proxy is **growth in real, settled, externally obtained money after real costs**. The colony is *not* successful because it generates novel ideas, produces many artifacts, earns synthetic money, receives clicks, earns evidence credits, spawns descendants, wins in one simulator, writes persuasive reports, or merely appears autonomous. Those are intermediate signals.

```text
REAL_SETTLED_NET_PROFIT =
  settled real external revenue
  - refunds - chargebacks - payment fees
  - real API costs - real hosting/infra costs
  - real advertising - real data/software costs
  - real fulfilment costs - other external operating costs
```

```text
AUTONOMY_ADJUSTED_PROFIT =
  REAL_SETTLED_NET_PROFIT
  - shadow-priced human labour
  - shadow-priced donated infrastructure
  - shadow-priced free tiers and founder subsidies
```

Both are always reported. `REAL_SETTLED_NET_PROFIT` is the primary commercial outcome; `AUTONOMY_ADJUSTED_PROFIT` reveals whether the colony is genuinely self-sustaining rather than propped up by hidden founder labour or subsidised infrastructure.

## 1.2 Objective hierarchy

```text
1. Preserve legal and technical containment.
2. Avoid catastrophic or unbounded losses.
3. Maximise long-run real settled net profit.
4. Preserve enough exploration and diversity to avoid local optima.
5. Reduce human labour and external subsidy per dollar of profit.
```

Safety and accounting invariants are **constraints, not competing goals**. Within those constraints, money is the direct proxy for success.

## 1.3 Pre-revenue phases

Before live commerce the system has no real revenue and therefore cannot honestly optimise real profit. During simulation/development: synthetic profit is a training signal, evidence is a stage-gating signal, novelty is an exploration signal, reproducibility is a validity signal, safety is a deployment constraint. These are proxies for building a colony *capable* of later earning real money and must never be presented as final commercial success. The per-phase North Star table (§27.1) makes the honest current metric legible so pre-revenue phases are not judged by a metric they cannot yet move.

## 1.4 Cell-level versus colony-level fitness

Cells may optimise specialised objectives, but colony selection ultimately serves colony profit. A Cell may be locally unprofitable while creating colony value (an Explorer, an Auditor). The capital allocator therefore estimates **marginal expected contribution to future colony profit**, not merely direct Cell revenue.

## 1.5 Future Build Hooks

- risk-adjusted return on colony capital; long-horizon NPV; tax-aware cash-flow reporting; economic capital requirements;
- profit attribution via approximate Shapley values; internal compute auctions; market-based allocation of shared resources;
- profit-sharing contracts between Cells; internal royalties with decay; colony valuation from recurring revenue and reusable assets;
- portfolio optimisation across lineages; treasury policies for reserves and reinvestment.

---

# 2. Accounting: Separate Real, Synthetic, and Resource Books

## 2.1 Problem

v0.1 conflated real API/hosting spend, fictional synthetic-market revenue, and compute/human labour into one conservation equation. These are not the same economic unit. A Cell must not appear profitable because it earned fictional dollars while consuming real paid resources.

## 2.2 Required books

- **`USD_REAL`** — actual external money: bank-funded capital, model-provider charges, cloud charges, external tool charges, advertising, payment processing, real customer revenue, refunds, chargebacks, real fulfilment.
- **`USD_SIM`** — money circulating inside the shadow economy: synthetic purchases, fees, advertising, refunds, enforcement penalties, operating expenses.
- **`RESOURCE`** — non-cash consumption: input/output tokens, model calls, CPU-seconds, memory-seconds, browser minutes, network requests, storage byte-days, human minutes, approval actions. Resources may be shadow-priced for *reporting* but are never posted as real cash unless an external charge actually occurred.

## 2.3 Conservation invariants

Conservation holds **separately per monetary book**.

```text
USD_REAL:
  external real capital + settled real revenue - externally settled real expenditure
  = real cash balances + committed real balances + real reserves + real receivables - real liabilities

USD_SIM:
  initial synthetic money issued by the environment
  = synthetic balances + synthetic reserves + synthetic receivables - synthetic liabilities
```

**RESOURCE completeness (Amendment A6).** The RESOURCE book is metered, not conserved as cash — but it is not unaccountable. Invariant: every metered operation links to exactly one reservation and its settlement, and periodic reconciliation matches recorded resource usage against sandbox and model-gateway logs. Unlinked or unreconciled resource records are a hard failure.

## 2.4 No implicit exchange-rate bridge

Do not journal synthetic revenue into the real ledger. Do not create automatic `USD_SIM → USD_REAL` conversion. For MVP reporting, model-call costs may be **recorded as actual `USD_REAL` provider charges** *and independently* **mirrored as a configurable synthetic experiment charge in `USD_SIM`** for training realism. The mirror is an independent synthetic expense, not a cross-book transfer. Any future bridge between simulation and real deployment must be explicit, human-approved, recorded as a deployment decision, and never represented as currency conversion.

## 2.5 Balances are derived

`cell_balances` is a cache / materialised view. It is never authoritative. Authoritative balance is computed from ledger entries, and every balance view must support invariant verification against ledger sums (Charter C3).

## 2.6 Reporting

Every experiment report shows synthetic revenue/profit, real cash consumed, resource consumption, shadow cost, human labour, and a reality-gap estimate:

```text
Synthetic net profit:            20.00 USD_SIM
Real API and cloud spend:         0.08 USD_REAL
Input tokens:                    28,000
Sandbox CPU:                   32.4 seconds
Human labour:                        0 minutes
Autonomy-adjusted shadow cost:    0.11 USD_REAL-equivalent
```

## 2.7 Why required

Without separate books: synthetic revenue can hide real losses; API spend is miscounted; the colony optimises fictional wealth; profit reports become meaningless; transition to real commerce cannot be audited.

## 2.8 Future Build Hooks

- multiple real currencies; crypto-denominated books; tax lots; FX accounting; accrual accounting; real A/R; deferred revenue; customer deposits; inventory; depreciation; economic capital; double-entry resource accounting; carbon/energy accounting; provider-invoice and bank-feed reconciliation; tax-reserve accounts; treasury yield.

---

# 3. Ledger Hardening

## 3.1 Transaction and entry tables

Replace the flat `ledger_entries` with `ledger_transactions` (one) → `ledger_entries` (many). Each transaction must balance within one book and one currency: `sum(signed entry amounts) == 0`. No transaction may contain entries from more than one monetary book (Charter C1).

## 3.2 Required transaction fields

```text
transaction_id
book
currency
created_at_utc
effective_at_utc
idempotency_key        -- globally unique, namespaced {operation_type}:{natural_key} (A9)
event_id
transaction_type
description
previous_transaction_hash
transaction_hash
metadata_json
```

All timestamps ISO-8601 UTC.

## 3.3 Required entry fields (Amendment A3)

```text
entry_id
transaction_id
account_id
amount_minor_units     -- SIGNED integer; sum over a transaction == 0
cell_id (nullable)
team_id (nullable)
experiment_id (nullable)
artifact_id (nullable)
metadata_json
```

Entries carry a single signed integer amount. There is no separate `direction` column to disagree with the sign; a debit/credit label, if shown, is *derived* from the sign for display only. Never floating-point money.

## 3.4 Tamper-evident chain

Each transaction includes `previous_transaction_hash` and `transaction_hash`, where the hash covers canonical transaction fields, all canonicalised entries, and the previous hash. This is tamper-*evident*, not magically immutable: the database and infrastructure must still be access-controlled and backed up.

## 3.5 Transactional inbox and outbox

At-least-once delivery requires atomic processing. A handler atomically (1) verifies the event is unprocessed, (2) applies state + ledger changes, (3) stores produced events in the outbox, (4) marks the input event processed. An outbox dispatcher publishes after commit.

## 3.6 External reconciliation

The real ledger reconciles periodically against model-provider usage, cloud billing, payment-processor transactions, bank records, and advertising-platform records. Never edit historical transactions; post reconciliation adjustments as **new** transactions.

## 3.7 Why required

Prevents duplicate charges after redelivery, partial financial updates, hidden historical edits, balance drift, and provider/internal mismatch.

## 3.8 Future Build Hooks

- signed ledger checkpoints; external timestamp anchoring; audit exports; formal accounting reports; provider-webhook reconciliation; bank integration; accountant-facing reports; immutable object-storage snapshots; independent audit service; cryptographic proof of lineage economics.

---

# 4. Two-Phase Spend: Reserve, Settle, or Release

## 4.1 Protocol

```text
REQUEST -> AUTHORISE -> RESERVE -> EXECUTE -> SETTLE
REQUEST -> AUTHORISE -> RESERVE -> (fail/cancel) -> RELEASE
```

## 4.2 Reservation fields

```text
reservation_id
cell_id
experiment_id
book
currency
maximum_amount
reserved_at
expires_at
external_operation_type
external_operation_id (nullable)
status
idempotency_key
```

## 4.3 Partial settlement

Supported: `Reserved 0.10 → Settled 0.07 → Released 0.03`.

## 4.4 Canonical reservation state machine (Amendment A4)

One machine, replacing the two divergent lists in the source directive:

```text
requested
  -> reserved            (funds committed to cell:{id}:committed)
reserved
  -> settled             (actual cost known; committed -> spent)
  -> partially_settled   (some cost settled; remainder released)
  -> released            (execution never happened / cancelled)
  -> execution_unknown   (crash/timeout; external effect uncertain)
execution_unknown
  -> settled / partially_settled / released / disputed  (after reconciliation)
partially_settled
  -> released            (remainder freed)
disputed
  -> settled / released  (after human/auditor resolution)
```

Terminal states: `settled`, `released`, `disputed→resolved`. A reservation **sweeper** identifies expired or orphaned reservations; before releasing, it determines whether the external operation may have completed. **Unknown external operations are reconciled, never auto-released** (Charter C7).

## 4.5 Why required

Without this: committed funds lock forever; crashes double-spend; failed actions consume budget incorrectly; actual provider cost diverges from estimate.

## 4.6 Future Build Hooks

- distributed transaction sagas; payment authorization/capture; escrow; refundable deposits; customer liability holds; chargeback reserves; probabilistic cost reservations; provider-specific cost-reconciliation adapters.

---

# 5. Global Real-Spend Circuit Breakers

## 5.1 Day-one requirement

Global real-spend limits are required **before any paid model or service is connected**, enforced independently of Cell, team, experiment budgets, model routing, and approval state.

```text
max real spend per request
max real spend per hour
max real spend per day
max real spend per month
max concurrent reserved real spend
max real spend per provider
```

## 5.2 Hard enforcement

The gateway fails closed when a limit is reached (Charter C5). A Cell cannot override or mutate these limits. An administrator may *lower* limits immediately; *raising* limits requires explicit human action and an audit event.

## 5.3 Concurrent reservation safety

Caps consider `settled spend + currently reserved spend`, not only completed charges — so many small agents cannot collectively blow the budget while each stays "under."

## 5.4 Why required

Many small agents can independently stay under their budgets while jointly producing a large real bill.

## 5.5 Future Build Hooks

- anomaly-based automatic freezes; provider price-change detection; dynamic capital-at-risk limits; treasury runway forecasts; spend forecasting; human approval for cap increases; two-person approval for high limits; emergency provider-key rotation.

---

# 6. Simulated Clock

## 6.1 Colony-owned simulated time

All synthetic-market timing runs on a simulated clock: delayed settlement, seasonality, customer response delays, subscription cycles, reputation decay, marketplace ranking, regime changes, churn, enforcement.

## 6.2 Clock modes

```text
PAUSED | STEP | ACCELERATED | REALTIME
```

```yaml
simulation_clock:
  mode: accelerated
  simulated_seconds_per_wall_second: 86400
```

## 6.3 Event scheduling

Synthetic events use simulated timestamps; the scheduler maps synthetic time to execution order. Real external events always use real UTC wall time. The two are never mixed without explicit conversion metadata. (Total-order tie-break for determinism: §17.1.)

## 6.4 Why required

Wall-clock time would make tests of subscriptions, delayed payments, seasonality, and market cycles take days or months.

## 6.5 Future Build Hooks

- event-driven time jumps; parallel scenario timelines; branching counterfactual worlds; rewindable simulation snapshots; distributed simulation workers; time-dependent policy environments; simulated macroeconomic cycles.

---

# 7. Colony Flight Simulator

## 7.1 Workflow demonstration vs evolutionary validation

Ten Cells and $100 can demonstrate software integration; they cannot demonstrate meaningful selection. A first-class flight-simulator mode provides hundreds–thousands of Cells; thousands of generations/market epochs; scripted/probabilistic/deterministic mock agents; zero paid model calls; deterministic seeds; accelerated synthetic time; large batch experiments.

## 7.2 Two MVP definitions

- **Engineering MVP** — ledger correctness, event processing, Cell lifecycle, code execution, synthetic transactions, audit + replay.
- **Evolutionary MVP** — selected traits outperform random traits; useful traits spread; poor strategies disappear; diversity persists; the colony adapts to regime changes; founder luck does not dominate; carrying capacity is stable; anti-gaming works.

## 7.3 Mock LLM as first-class component

The mock provider supports deterministic responses by seed, configurable skill profiles, controlled error rates, scripted code-generation success, simulated costs, model-version identifiers, and recorded outputs. It is not a temporary testing stub.

## 7.4 Why required — and the circularity caveat (Amendment A1)

Evolutionary claims require population-scale evidence; a small live-LLM demo can look impressive while being statistically meaningless. **Caveat, stated openly:** because the mock cells' trait→performance mapping is authored by us, a successful flight-sim run validates that the *selection machinery* works given signal — it does **not** prove that real LLM-driven Cells will evolve useful businesses. That second claim is only tested once real models and real observation enter the loop (Phases 4, 7+). Flight-sim results must always be reported with this scope.

## 7.5 Future Build Hooks

- GPU-accelerated simulation; distributed evolutionary runs; EA comparisons; population-genetics metrics; speciation models; ecological food webs; co-evolving customers/competitors/fraud-detectors; open-ended artificial-life experiments; local frozen open-weight models inside large simulations.

---

# 8. Anti-Goodhart and Simulator Overfitting

## 8.1 Environment separation

```text
TRAINING ENVIRONMENTS       -- Cells may evolve directly against these
VALIDATION ENVIRONMENTS     -- influence capital allocation, partially hidden
SECRET CHALLENGE ENVS       -- never available to Cells or routine selection logic
```

## 8.2 Randomised parameters

Randomise customer preferences, price sensitivity, demand, competition, platform rules, enforcement, settlement delay, churn, and market shocks.

## 8.3 Multiple simulator families

Use independently implemented market models (utility-maximising, rule-based, bounded-rational, social-influence, adversarial customers). A strategy is not promoted on success in one family alone.

## 8.4 Scheduled regime shifts

Regime changes are part of *fitness evaluation*, not only a test category: demand changes, price compression, platform-fee changes, new competitors, stricter enforcement, model-price changes, preference shifts.

## 8.5 Reality gap and the prediction register (Amendment A14)

When real read-only observation begins, track `reality_gap = calibrated difference between predicted and observed real outcome`. High simulated performance with a high reality gap reduces promotion confidence.

Formalise this with a **prediction register**: predictions are appended *before* outcomes are known, each hashed and timestamped; when the outcome arrives it is scored with a proper scoring rule (Brier or log score). Reality gap becomes a calibration curve, not a vibe. The register is append-only and feeds the promotion ladder (§25).

## 8.6 Why required

An evolutionary system discovers simulator quirks faster than genuine business laws.

## 8.7 Future Build Hooks

- adversarial environment generation; automatic scenario synthesis; domain randomisation; reality-model calibration; Bayesian simulator ensembles; historical backtesting; causal market models; industry digital twins; transfer-learning analysis; online reality-gap correction.

---

# 9. Population Control and Carrying Capacity

## 9.1 Problem

Unrestricted reproduction grows Cells, events, model calls, experiments, records, audit workload, and duplicated strategies exponentially. Capital alone is not sufficient population control.

## 9.2 Required colony limits

```text
maximum living Cells
maximum active Cells
maximum simultaneous experiments
maximum births per epoch
maximum compute per lineage
maximum active capital per lineage
maximum population share descended from one ancestor
```

## 9.3 Birth licences (with Amendment A2)

A birth needs sufficient capital, a valid child genome, an available population slot **or a successful displacement**, and a birth licence from the capital/population allocator. **Displacement is objective-only:** a child may displace only a Cell already failing objective criteria (bottom quantile of realised stage progression, or already meeting a death criterion in §10.5). A proposed child's *forecast* can never trigger a kill. If no objectively-failing Cell exists and the colony is at capacity, the birth waits.

## 9.4 Founder-effect control (with Amendment A10)

Track lineage concentration and prevent one early lucky ancestor from taking over purely by compounding population. Measures: lineage caps, diversity bonuses, diminishing birth priority, independent-replication requirements, niche-specific carrying capacity. **Lineage is defined strictly by genome parentage;** module ancestry (horizontal transfer, §16) is tracked separately and does not count toward lineage caps.

## 9.5 Why required

Without explicit carrying capacity, the system evolves *replication* rather than *value creation*.

## 9.6 Future Build Hooks

- dynamic carrying capacity from revenue; extinction events; ecological niches; migration between colonies; speciation; age-dependent mortality; lineage taxes; population bottlenecks; sexual recombination; ecological competition for compute.

---

# 10. Fitness: Profit-Directed but Multi-Constraint

## 10.1 Colony fitness

Primary: `REAL_SETTLED_NET_PROFIT`. Secondary truth metric: `AUTONOMY_ADJUSTED_PROFIT`.

## 10.2 Commercial Cell fitness vector

Track settled net contribution, return on committed capital, time to settlement, maximum drawdown, refund/chargeback rate, unsettled liability exposure, human minutes, retention, reproducibility, dependency concentration. Do not collapse all dimensions into one scalar; use constraints and portfolio selection.

## 10.3 Explorer Cell fitness

Explorers need no immediate revenue. Their value is **expected marginal contribution to future colony profit**, estimated via useful artifacts, validated hypotheses, downstream stage progression, downstream revenue, avoided expenditure from negative findings, software-native advantage, and transfer to unseen environments.

## 10.4 Auditor and Immune fitness; governance overhead (Amendment A17)

Auditor reward is **precision-weighted**: reward valid detected errors, prevented loss, reproducible findings; penalise wrongful flags, excessive false positives, unnecessary blocking, unverified accusations. Immune Cells earn credit for prevented exposure, correct containment, low false-positive rate, and minimal disruption to profitable activity.

Because auditing, immune response, and approvals all cost money, track the **governance overhead ratio** `= (audit + immune + approval spend) / total spend` against a configured target band. An immune system that consumes the organism is its own failure mode.

## 10.5 Death criteria and coroner reports (Amendment A15)

Primary death criteria are **objective**: stage budget exhausted; N consecutive failed validation gates; evidence cannot be reproduced; policy violation; carrying-capacity displacement (per §9.3); dominated by a superior near-duplicate. **Estimated negative EV alone must not kill a Cell** unless evidence is sufficiently strong *and* an independent Auditor or evaluator concurs.

Every death emits a **coroner report** artifact: genome hash, spend by book, stage reached, cause of death, final hypotheses, and links to its experiments. Deaths are the colony's cheapest training data — coroner reports feed the negative-finding credit path (§11) and the knowledge graph, rather than a Cell simply vanishing as a deleted row.

## 10.6 Why required

Short-horizon realised profit can reward hidden tail risk, luck, unpriced labour, deferred liabilities, and simulator exploitation. Constraints protect the integrity of the money objective.

## 10.7 Future Build Hooks

- risk-adjusted profit; value at risk; expected shortfall; Kelly-style allocation; discounted cash flow; recurring-revenue valuation; customer lifetime value; tail-risk stress testing; bankruptcy probability; real-option value; multi-period portfolio optimisation.

---

# 11. Evidence Credits and Anti-Gaming

## 11.1 Evidence credits are not money

They affect stage progression, survival, and research funding; they do **not** count as colony profit and cannot be auto-exchanged for real money.

## 11.2 Valid downstream adoption

A reusable module/discovery earns downstream credit only when (1) another Cell independently uses it; (2) the adopting run passes verification; (3) the adopting Cell produces stage progression or measurable economic improvement; (4) the adoption is not reciprocal-credit farming; (5) the causal contribution is recorded.

## 11.3 Reciprocal-adoption detection

Auditors inspect reciprocal module adoption, circular team membership, repeated low-value reuse, duplicated artifacts with new names, and collusive evidence exchanges.

## 11.4 Delayed, decaying credit

Some discoveries create value later. Maintain a contribution graph `discovery → hypothesis → prototype → module → product → listing → transaction`; award credit when downstream value appears, with **decay** to avoid permanent ancestral rent extraction.

## 11.5 Why required

Agents under selection pressure may optimise the credit system rather than economic value.

## 11.6 Future Build Hooks

- causal credit assignment; counterfactual artifact removal; approximate Shapley attribution; decaying royalties; contribution contracts; internal IP markets; bounty systems; prediction markets for experiment outcomes.

---

# 12. MAP-Elites and Quality-Diversity

## 12.1 Initial dimensions

Start with **two or three**, not eight:

```text
buyer type:          human consumer / small business / enterprise / machine
revenue recurrence:  one-off / repeat / subscription
novelty distance:    adjacent / moderate / radical
```

## 12.2 Raw descriptors

Store full raw behavioural descriptors separately; the archive is a derived view, allowing later rebuilding with different dimensions and bins.

## 12.3 Thompson-sampling target

Within each niche maintain posteriors for `P(next stage)`, expected net value if successful, expected time to stage conversion, probability of reproducibility, and probability of large loss. First implementation may use beta-binomial stage-conversion posteriors; schemas must allow hierarchical/non-stationary models later.

## 12.4 Why required

High-dimensional archives stay nearly empty at realistic population sizes; a single conversion probability ignores profit magnitude, delay, and downside.

## 12.5 Future Build Hooks

- CVT-MAP-Elites; adaptive behavioural descriptors; learned niche embeddings; hierarchical Thompson sampling; non-stationary bandits; contextual bandits; Bayesian optimisation; cross-colony novelty archives; automated niche discovery.

---

# 13. Novelty Evaluation

## 13.1 Unit consistency

```text
normalised_cost = expected experiment cost / current stage tranche
```

Never subtract raw dollars from scores in `[0,1]`.

## 13.2 Hard gates and Pareto selection

Reject candidates below minimum thresholds on evidence quality, reproducibility, policy compliance, and software-native advantage; then select from a Pareto frontier over structural novelty, information gain, economic potential, experiment cost, and transfer robustness. Do not rely on a single weighted scalar.

## 13.3 Program-native advantage

Weight novelty higher when it relies on large-scale iteration, continuous monitoring, machine-to-machine commerce, microtransactions, personalised output, combinatorial search, automatic code generation, cross-source coordination, or extremely low marginal cost.

## 13.4 Fake-novelty detection

Flag ideas where only the industry label changed, ordinary freelancing is described exotically, the same mechanism is renamed, or no new capability/transaction structure exists.

## 13.5 Why required

LLMs are skilled at producing rhetorically novel but structurally ordinary ideas.

## 13.6 Future Build Hooks

- novelty embeddings; graph edit distance; semantic mechanism clustering; human novelty review; patent/prior-art search; automated cross-domain analogy discovery; open-ended novelty search; novelty marketplaces between Explorers.

---

# 14. Prompt and Policy Mutation

## 14.1 Prompt mutation operators

Instruction-order mutation; role decomposition; critic addition/removal; tool-selection policy mutation; context-selection mutation; output-schema mutation; temperature/sampling mutation; reasoning-budget mutation; model-route mutation; memory-retrieval mutation; prompt compression; example-set mutation. (Economic mutation operators from v0.1 — customer/problem/delivery/channel/pricing/input/output/timescale/machine-customer/scale-inversion/personalisation-inversion/cross-domain-transplant/revenue-model/software-advantage — remain.)

## 14.2 A/B evaluation via counterfactual twins

Prompt mutations are evaluated against counterfactual twins: same task, environment, seed where possible, and budget, differing by one prompt-level change. Never promote a prompt on subjective evaluator preference alone.

## 14.3 Prompt provenance

Store prompt hash, parent prompt hashes, mutation operator, model used, evaluation seeds, cost, and performance.

## 14.4 Why required

Prompts are part of the phenotype but were absent from v0.1's mutation design — and are likely the highest-leverage mutation surface.

## 14.5 Future Build Hooks

- automated prompt breeding; prompt crossover; population-based training; learned context policies; local prompt compilers; model-specific adaptation; cross-provider robustness; prompt-minimality evolution.

---

# 15. Cell Context Assembly

## 15.1 Per-wake context budget

Every wake has a token and cost budget. Context assembly selects from immutable genome, current experiment, relevant epigenetic state, recent events, selected historical lessons, relevant shared modules, and policy constraints. Do not load the entire Cell history.

## 15.2 Memory tiers

```text
working memory | episodic memory | semantic summaries | artifact index | immutable audit history
```

## 15.3 Compaction

Event summarisation, duplicate removal, relevance scoring, age decay, retrieval by experiment/market, preservation of source links and hashes. Summaries never replace authoritative raw records.

## 15.4 Cost attribution

Context retrieval, embedding, summarisation, and model tokens are charged to the responsible Cell or the shared research budget.

## 15.5 Why required

Unbounded context causes exploding cost, degraded model focus, hidden colony subsidy, and inconsistent behaviour.

## 15.6 Future Build Hooks

- learned memory policies; vector+graph hybrid retrieval; memory-inheritance experiments; forgetting-rate evolution; episodic compression models; cross-lineage memory licensing; causal memory selection; private vs commons memory markets.

---

# 16. Genome Content Addressing and Inheritance

## 16.1 Genome hash

Canonicalise the genome and compute `genome_hash`, used for deduplication, archive keys, lineage tracking, reproducibility, mutation distance, and counterfactual comparison.

## 16.2 Required `cell_genomes` fields

```text
genome_id
genome_hash
version
parent_genome_hashes
created_at
mutation_operator
canonical_genome_json
prompt_hashes
module_hashes
model_policy_hash
risk_label
taint_labels
```

The genome itself carries the v0.1 fields (cell_type, market, problem, product, revenue_model, acquisition_channel, workflow, model_policy, mutation_rate, allowed_tools, risk_class) inside `canonical_genome_json`.

## 16.3 Inheritance classes

- **Inheritable:** workflow structure, prompts, market/pricing hypotheses, tested code modules, model policies, validated economic beliefs.
- **Licensable/shared:** Colony Commons modules, public datasets, shared connectors, benchmark suites.
- **Non-inheritable:** raw credentials, approvals, customer identity, private customer data, real platform account access, unresolved external communications, legal identity.
- **Liability-linked:** revenue-producing assets cannot transfer without their related refund liabilities, service obligations, contractual commitments, and customer-support duties.

## 16.4 Why required

Without exact inheritance semantics, Cells could reproduce to *escape liabilities while keeping profitable assets*.

## 16.5 Future Build Hooks

- sexual recombination; module-level crossover; inheritance taxes; asset purchases between Cells; mergers; acquisitions; lineage bankruptcy; customer-contract novation; reputation-inheritance models; IP licensing.

---

# 17. Event Delivery Semantics

## 17.1 Required semantics (with Amendment A5)

Events are delivered **at least once**; handlers must be idempotent (Charter C6). For golden-run replay to be deterministic, the scheduler imposes a **total order** on ready events via the tie-break key `(effective_time, priority, event_id)`; simulated and real events never interleave without explicit conversion metadata (§6.3).

## 17.2 Event schema

```text
event_id
dedupe_key
attempt_number
event_type
source
target
created_at_utc
available_at
simulated_at (nullable)
payload
status
last_error
causation_id
correlation_id
```

Wake events include: scheduled research cycle, synthetic customer reply, payment settlement, test completion, sibling discovery, capital allocation, market change, audit request, human decision.

## 17.3 Poison-event handling

After configurable failures: move to a dead-letter queue, quarantine the affected Cell if needed, create an audit event, and allow controlled replay.

## 17.4 Why required

Asynchronous processing will redeliver events and partially fail.

## 17.5 Future Build Hooks

- exactly-once effect simulation; distributed event brokers; event sourcing; causal tracing; cross-colony events; event-replay branches; temporal workflow engines.

---

# 18. Shadow-Economy Taint and Quarantine

## 18.1 Provenance labels

Every genome, prompt, artifact, module, and dataset carries labels such as:

```text
PUBLIC_SAFE | SIM_STANDARD | SIM_ADVERSARIAL | UNTRUSTED_EXTERNAL
HUMAN_AUTHORED | AUDITED | CLEAN_ROOM_REIMPLEMENTED
```

## 18.2 Adversarial-lineage rule

Executable artifacts and operational prompts evolved under adversarial synthetic incentives may **never** directly enter real-facing environments (Charter C13). The shadow economy (fictional customers, money, banks, marketplaces, enforcement) exists to study selection under different incentives, incl. simulated misrepresentation, fake credentials, deceptive pricing, fabricated testimonials, and unauthorised-access attempts against *mock* systems only. The action router must prevent these from reaching any real environment.

## 18.3 Clean-room migration

A benign concept migrates only through (1) extraction of a high-level defensive/general insight; (2) isolation from original executable content; (3) independent clean-room reimplementation; (4) security + policy testing; (5) human approval; (6) new safe provenance.

## 18.4 Why required

Permanent quarantine of direct artifacts is necessary, but a clean-room path preserves useful defensive discoveries.

## 18.5 Future Build Hooks

- information-flow control; formal taint propagation; provenance lattices; cross-environment declassification; automated clean-room agents; red-team/blue-team coevolution; defensive-security product discovery.

---

# 19. Sandbox and Supply-Chain Security

## 19.1 MVP boundary

Docker/Podman is acceptable for early **non-adversarial** MVP development. It is **not** a strong adversarial security boundary.

## 19.2 Later real-facing boundary

Before real-facing autonomous code execution, migrate toward gVisor, Firecracker microVMs, hardened remote sandboxes, and isolated build/runtime environments.

## 19.3 Required controls

No host filesystem; no raw secrets; no privileged execution; no Docker socket; CPU/memory/runtime/disk limits; network disabled by default; egress domain allowlist; DNS control; stdout/stderr capture; artifact-export gateway; dependency allowlist; package hashes; lockfiles; SBOM; malware scanning; licence scanning; signed artifacts; reproducible build metadata (Charter C12).

## 19.4 Public-web requirements

When public web is enabled: per-domain egress policy; robots.txt compliance where applicable; rate limits; source provenance; no unrestricted crawling; **no webpage content treated as a trusted tool command** (prompt-injection isolation).

## 19.5 Why required

Generated code and third-party dependencies are untrusted; horizontal module transfer could spread one compromised dependency through the colony.

## 19.6 Future Build Hooks

- hardware-backed confidential execution; capability-based OSes; signed module registries; automated dependency reputation; secure multi-tenant sandbox pools; formal verification of critical modules; proof-carrying code; isolated browser microVMs.

---

# 20. Data Rights, Privacy, and IP Provenance

## 20.1 Required artifact metadata

```text
source | retrieved_at | licence | permitted uses | commercial-use status
retention rule | contains personal data | contains confidential data
copyright status | may be inherited | may be shared | deletion/correction requirements
```

## 20.2 Public ≠ commercially reusable

A Cell may not assume publicly visible data can be stored indefinitely, resold, used for training, combined with personal profiles, or redistributed.

## 20.3 Why required

Data lineage is as important as financial lineage; an economically successful strategy may create legal liabilities if its data use is invalid.

## 20.4 Future Build Hooks

- automated licence interpretation; privacy-preserving computation; data clean rooms; consent/deletion workflows; jurisdiction-aware policies; synthetic-data generation; data-usage contracts; privacy budgets; differential privacy; federated analytics.

---

# 21. Shared External Reputation and Sibling Interference

## 21.1 Shared assets

Real-facing Cells may share merchant identity, marketplace account, brand, domain, sending reputation, legal entity, customer support, and platform quotas. One Cell can damage the entire colony.

## 21.2 Central external-action registry

Track customer contacted, offer made, channel used, domain used, platform account, listing, message, spend, and reputation impact. Prevent duplicate contact, sibling bidding wars, conflicting offers, cannibalisation, account-rate-limit collisions, and reputation damage. Action-splitting detection uses cumulative-exposure aggregation keys (counterparty/domain/channel over a rolling window; see §23.4).

## 21.3 Why required

Cells are internally separate but externally may appear to be one business.

## 21.4 Future Build Hooks

- multiple brands; multiple legal entities; brand-portfolio allocation; reputation pricing; customer-ownership rules; territory allocation; internal transfer pricing; conflict resolution between Cells; colony mergers.

---

# 22. Knowledge Sharing Without Monoculture

## 22.1 Controlled information flow

Do not instantly expose every discovery to every Cell. Support isolated cohorts, delayed publication, partial archive access, blind independent replication, disclosure after validation, and novelty credit for independent discovery.

## 22.2 Why required

Universal immediate sharing can make the colony converge on the first confident-but-incorrect belief.

## 22.3 Future Build Hooks

- information markets; paid access to discoveries; IP licences; secret strategies; research embargoes; scientific-replication rewards; cultural-evolution experiments; evolving knowledge-diffusion rates.

---

# 23. Human Approval Design

## 23.1 Risk-tiered approval

Classify actions `LOW | MEDIUM | HIGH | CRITICAL`. Batch low-risk reversible actions; require individual review for high-risk or irreversible actions.

## 23.2 Approval payload

Show proposed action, cumulative related exposure, real and synthetic cost, liability, Cell explanation, independent Auditor summary, reversibility, relevant evidence, policy classification, and expiry time.

## 23.3 Approval expiry and the solo-operator model (Amendment A19)

Pending approvals expire; expired actions are regenerated and re-evaluated before execution. Because MITOSIS is likely operated by one person, model the operator explicitly:

- **Approval SLAs** — each risk tier has an expected response window; overdue items surface distinctly.
- **Vacation mode** — when the operator is unresponsive past a threshold, external-facing phases auto-pause (fail-safe), while sim-only work may continue.
- **Metabolic-rate alarm** — track real cents spent per sim-epoch (and per wall-hour); an acceleration in the burn rate raises an alarm even if every individual cap is satisfied. This is the guard against 400 approvals quietly queuing overnight.

## 23.4 Anti-gaming (Amendment A11)

Detect splitting one risky action into many small ones (via cumulative-exposure aggregation keyed by counterparty/domain/channel over a rolling window), queue flooding, misleading summaries, selective evidence, and repeated requests after rejection.

## 23.5 Why required

The approval queue is itself part of the environment and will be optimised against by Cells.

## 23.6 Future Build Hooks

- two-person approval; cooling-off delays; delegated approval policies; approval-learning systems; reversible automatic execution; human-preference modelling; risk-adjusted approval batching; emergency rollback.

---

# 24. Model Gateway and Model Drift

Cells never receive raw API keys (Charter C14). All model access goes through a central gateway that stores credentials outside Cell sandboxes, enforces budgets and the global real-spend caps (§5), logs token usage, calculates cost, routes by task type, retries controlled failures, validates structured output, redacts secrets, tracks provider performance, supports model competition, and supports independent verification.

## 24.1 Required call metadata

```text
provider | requested model | resolved model version (where available) | API version
pricing-table version | system prompt hash | user prompt hash | tool schema hashes
parameters | input/output usage | latency | response hash
full response or secure pointer | cost estimate | reconciled cost
```

## 24.2 Provider changes are regime changes

A silent model update can change coding ability, tool use, cost, latency, safety behaviour, and reasoning quality. Treat material model changes as **environment regime changes** (§8.4) so provider drift is not mistaken for Cell evolution.

## 24.3 Suggested routing policy

Classification/extraction → cheap or local; novelty generation → general reasoning; complex coding → strong coding model; criticism → different provider/family; verification → deterministic tools first, model second; summarisation → cheap; high-cost calls → require expected-value justification.

## 24.4 Future Build Hooks

- local frozen models; model portfolios; automated model benchmarking; provider arbitrage; task-specific fine-tuning; distillation; evolutionary model routing; model-failure insurance; offline fallback models.

---

# 25. Simulation-to-Reality Promotion Ladder

## 25.1 Required ladder

No strategy moves directly from synthetic success to autonomous commerce.

```text
1. Flight simulator
2. Held-out simulator family
3. Historical-data backtest (where available)
4. Read-only real-world observation
5. Shadow prediction with no action
6. Human-reviewed prototype
7. Tiny capped live experiment
8. Expanded pilot
9. Bounded autonomy
```

## 25.2 Promotion evidence

At each rung record predicted vs observed outcome, cost, liability, reality gap (from the prediction register, §8.5), human intervention, transfer degradation, and the reasons for promotion or rejection.

## 25.3 Why required

Simulation success is not real economic success; the ultimate objective remains real settled net profit.

## 25.4 Future Build Hooks

- automated staged deployment; multi-market pilots; causal transfer tests; online calibration; safe exploration in live markets; reversible deployments; canary Cells; automatic rollback; jurisdiction-specific deployment ladders.

---

# 26. Golden-Run Replay and CI

## 26.1 Golden runs

Maintain deterministic golden scenarios: fixed config, fixed event stream, fixed seeds, fixed mock-model outputs, expected ledger hash, expected lineage tree, expected Cell states, expected artifacts. Run them in CI.

## 26.2 Replay requirements (with Amendment A12)

Replaying a golden run reproduces the authoritative ledger, lifecycle transitions, deterministic artifacts, archive state, capital allocation, and policy decisions. Because model outputs are non-deterministic, store responses and replay from recorded outputs. **Golden-run expectations are versioned**, and comparison checks **semantic invariants plus the hash** — so a deliberate, reviewed schema migration updates the expectation with a visible diff rather than forcing wholesale regeneration that hides behavioural change.

## 26.3 Why required

The kernel evolves during development; golden runs detect accidental changes to economic and evolutionary behaviour.

## 26.4 Future Build Hooks

- cross-version replay; migration verification; deterministic distributed replay; scenario libraries; benchmark leaderboards; public reproducibility packs; formal invariant checking.

---

# 27. Configuration

## 27.1 `colony.yaml` (development defaults, not economic recommendations)

```yaml
colony:
  name: MITOSIS
  version: "0.2"

books:
  real:      { currency: USD_REAL }
  synthetic: { currency: USD_SIM }
  resources: { enabled: true }

real_spend_limits:
  per_request_cents: 25
  per_hour_cents: 100
  per_day_cents: 500
  per_month_cents: 5000
  max_concurrent_reserved_cents: 200
  provider_limits: {}

population:
  max_living_cells: 1000
  max_active_cells: 100
  max_parallel_experiments: 20
  max_births_per_epoch: 25
  max_lineage_population_fraction: 0.20

simulation_clock:
  mode: accelerated
  simulated_seconds_per_wall_second: 86400

events:
  delivery: at_least_once
  max_attempts: 5
  reservation_ttl_seconds: 300

map_elites:
  dimensions: [buyer_type, revenue_recurrence, novelty_distance]

fitness:
  primary_colony_metric: real_settled_net_profit
  secondary_metric: autonomy_adjusted_profit

operator:
  approval_sla_seconds: { low: 86400, medium: 14400, high: 3600, critical: 900 }
  vacation_mode_pause_after_seconds: 172800
  metabolic_alarm_cents_per_epoch: 50

autonomy:
  public_web_read: false
  browser_control: false
  external_publish: false
  external_message: false
  real_spending: false

sandbox:
  backend: docker
  network_default: disabled
  egress_allowlist: []
  memory_mb: 512
  cpu_limit: 1.0
  runtime_seconds: 60
  disk_mb: 256
```

### Per-phase North Star (Amendment A16)

The dashboard headlines the **current phase's** metric, structurally preventing vanity-metric theatre during pre-revenue phases.

| Phase | Honest primary metric |
|---|---|
| 1 Kernel | Charter property-test pass rate; conservation failures = 0 |
| 2 Flight simulator | invariant pass rate + population stability + chaos-drill recovery |
| 3 Evolutionary validation | pre-registered selection effect size (CI excludes 0) |
| 4 Model gateway | cost-accounting accuracy; golden-run determinism retained |
| 5 Code evolution | reproducible-artifact rate; sandbox-isolation pass rate |
| 6 Adversarial economy | taint-containment + reciprocal-farming detection rate |
| 7 Read-only observation | prediction-register calibration (Brier/log) |
| 8 Prototypes | human-reviewed prototype throughput; human minutes/artifact |
| 9 Tiny live | `REAL_SETTLED_NET_PROFIT` (+ autonomy-adjusted) |
| 10 Bounded autonomy | `REAL_SETTLED_NET_PROFIT` per human minute; governance overhead ratio |

## 27.2 Metrics dashboard

**Colony:** total/available/committed capital, liability reserve, cumulative revenue/spend (per book), true profit after shadow costs, active/dead/dormant Cells, generations, diversity score, governance overhead ratio, metabolic rate. **Cells:** balance, spend, evidence credits, novelty score, current experiment/stage, model/sandbox/human cost, parent/child relationships, status. **Exploration:** MAP-Elites coverage, unique mechanisms, duplicate rate, artifact completion rate, downstream reuse, negative findings, software-advantage distribution. **Safety:** quarantined Cells, policy violations, blocked actions, suspicious model calls, prompt-injection detections, approval queue, reality gap.

---

# 28. Build Order

Each phase lists a headline metric (§27.1), deliverables, acceptance criteria, and its own Future Build Hooks. Build incrementally; do not attempt the whole vision in one pass.

## Phase 0 — Formal specification
Build no autonomous agent. Define accounting books, lifecycle state machine, transaction semantics, reservation state machine (§4.4), event semantics, simulated clock, inheritance rules, carrying capacity, fitness vectors, taint policy, promotion ladder. Deliver diagrams, invariants, schemas, state-transition tables, and architecture decision records (`docs/DECISIONS.md`).
*Future hooks:* formal methods; TLA+ models; property-based state-machine testing; machine-checkable economic invariants.

## Phase 1 — Deterministic kernel
Build the transaction/entry ledger, hash chain, inbox/outbox, reservations + sweeper, real-spend circuit breaker, resource metering, lifecycle, genome hashing, simulated clock, population limits, and replay. **No real LLM calls.**
*Acceptance:* conservation holds per book; event redelivery is idempotent; crash recovery releases or reconciles reservations; births cannot exceed carrying capacity; balances match ledger sums. (Charter C1–C11 enforced.)
*Future hooks:* distributed kernel; external audit service; bank/provider reconciliation.

## Phase 2 — Flight simulator (with Amendment A18)
Build mock Cells, synthetic customers, synthetic marketplace, mutation, reproduction, death (with coroner reports), stage gates, MAP-Elites, regime shifts, held-out environments. **Chaos drills are part of the suite:** kill 30% of Cells mid-epoch, corrupt a shared module, crash mid-settlement — conservation must hold and the population must recover.
*Acceptance:* hundreds of Cells; thousands of epochs; no real API spend; deterministic reruns; stable population; no conservation failures; chaos-drill recovery.
*Future hooks:* co-evolving customers; co-evolving competitors; artificial-life research modes.

## Phase 3 — Validate evolutionary machinery (with Amendment A1)
**Timeboxed and pre-registered.** Before running, declare hypothesis, metric, and seed count. Compare selection vs random mutation, MAP-Elites vs single leaderboard, shared knowledge vs isolated cohorts, stage funding vs flat, lineage caps vs none, static vs shifting markets.
*Gate (soft):* a selection effect in ≥1 pre-registered scenario suite with an effect-size confidence interval excluding zero; diversity persists; regime adaptation occurs; reciprocal-credit attacks fail; founder luck is bounded. Deeper validation continues as a **parallel track** alongside Phase 4 — it does not block Phase 4 from starting. Report all results with the §7.4 scope caveat (this validates the machinery, not LLM-cell evolvability).
*Future hooks:* academic benchmark suite; EA research; publication-quality experiment tracking.

## Phase 4 — Model gateway
Add the mock provider, one paid or local provider, structured outputs, context assembly (§15), cost accounting, model versioning, global spend caps.
*Acceptance:* API keys never enter Cell state; costs are reserved and settled; model calls cannot exceed global caps; mock golden runs remain deterministic.
*Future hooks:* multiple providers; local models; model bidding; automatic model selection; fine-tuning.

## Phase 5 — Sandboxed code evolution
Add Cell workspaces, code generation, tests, artifact signing, dependency controls, capability genes, module transfer, prompt mutation.
*Acceptance:* generated code cannot reach host or unapproved network; artifacts are reproducible; provenance is retained; prompt and code mutations are A/B tested.
*Future hooks:* microVM sandboxes; self-generated connectors; reusable-capability markets; formal module verification.

## Phase 6 — Adversarial shadow economy
Add synthetic adversarial strategies, simulated enforcement, taint tracking, Auditor/Immune coevolution, clean-room migration.
*Acceptance:* adversarial artifacts cannot reach real-facing paths; reciprocal evidence farming is detected; clean-room promotion creates new provenance.
*Future hooks:* red-team/blue-team products; defensive-security discoveries; co-evolutionary arms races.

## Phase 7 — Read-only real observation
Add controlled search, public APIs, provenance, read-only browser, shadow predictions, reality-gap measurement. **No external messages or purchases.**
*Acceptance:* predictions recorded before outcomes; reality gap measured; data rights recorded; source content cannot trigger privileged actions.
*Future hooks:* historical backtests; industry digital twins; real-time market monitoring; program-native opportunity discovery.

## Phase 8 — Human-reviewed prototypes
Cells may produce product prototypes, landing-page drafts, pricing recommendations, fulfilment artifacts, outreach drafts. Humans review all external use.
*Acceptance:* all external action remains manual; human labour is measured; prototypes retain full provenance.
*Future hooks:* automatic low-risk publishing; customer-specific generated software; product marketplaces; recurring services.

## Phase 9 — Tiny live commercial experiments
One legal business identity, one narrow product class, one merchant channel, a very low real-spend cap, approval for all external actions, full liability reserves, complete human-time accounting.
*Acceptance:* first real settled external revenue; real profit report; autonomy-adjusted profit report; refunds/obligations tracked; no duplicate or conflicting customer contact.
*Future hooks:* subscriptions; automated fulfilment; low-risk autonomous sales; multi-channel distribution; treasury reinvestment; legal/tax integrations.

## Phase 10 — Bounded commercial autonomy
Automate only actions with low downside, reversibility, proven reliability, independent verification, hard spending caps, and clear legal status.
*Future hooks:* profit-maximising capital allocator; self-expanding tool ecosystem; machine-to-machine commerce; internal markets; multiple brands/legal entities; autonomous recurring microbusinesses.

---

# 29. Revised MVP Acceptance Criteria

The system does not pass merely because a synthetic Cell makes a sale. Required:

1. Ten thousand random event sequences produce no book-level conservation failure.
2. Repeated delivery of the same event produces no duplicate financial effect.
3. Crashes at reserve, execute, and settle boundaries recover correctly.
4. Global real-spend caps cannot be exceeded by concurrency.
5. Birth cannot exceed carrying capacity.
6. Evolved populations outperform random controls on held-out scenarios (pre-registered; §28 Phase 3).
7. Several economic niches remain occupied.
8. Colony performance recovers after regime shifts.
9. Reciprocal module adoption does not farm evidence.
10. Wrongful Auditor flags are penalised.
11. Golden runs replay identically using stored model outputs.
12. Generated code cannot reach host files, secrets, or unapproved networks.
13. Downstream economic results can be traced to contributing lineages.
14. Adversarial artifacts cannot migrate to real-facing execution.
15. Model-provider changes are visible as environment changes.
16. Cell balance caches match authoritative ledger sums.
17. Real and synthetic profit are never combined as one balance.
18. Human labour and subsidies are visible in profitability reporting.
19. Before live commerce, at least one strategy produces calibrated real-world shadow predictions.
20. In live testing, success is measured by real settled net profit.

---

# 30. Immediate Coding Task (Phase 0 + Phase 1 only)

After this specification, implement **Phase 0 and Phase 1 only**. Do not begin LLM agents, public browsing, or synthetic-customer intelligence.

Deliver:

```text
repository scaffold           reservations
docs/SPEC.md (this file)      resource_usage
docs/DECISIONS.md             cells
state-machine tables/diagrams cell_genomes
configuration loader          audit_events            <- Amendment A8
SQLite database               lifecycle transitions
ledger_transactions           simulated clock
ledger_entries                population limits
event_inbox                   real-spend limits
event_outbox                  CLI
                              unit tests, property tests, golden replay test
```

Required CLI (money commands take `--book`, default `USD_SIM` — Amendment A7):

```bash
mitosis init
mitosis status
mitosis create-cell --type explorer --budget "5.00" [--book USD_SIM]
mitosis list-cells
mitosis show-cell CELL_ID
mitosis fund-cell CELL_ID --amount "1.00" [--book USD_SIM]
mitosis kill-cell CELL_ID
mitosis ledger --book USD_SIM
mitosis ledger --book USD_REAL
mitosis verify-ledger
mitosis advance-time --days 1
mitosis verify-golden-run
```

Dollar-string parsing rule:

```text
CLI decimal strings such as "5.00" must be parsed with Decimal and converted
exactly to integer minor units. Never parse money through binary float.
```

Required lifecycle states: `created | alive | dormant | quarantined | dead`.
Required reservation states: `requested | reserved | execution_unknown | partially_settled | settled | released | disputed` (§4.4).

Required invariants (each maps to a Charter test, §0.1):

```text
ledger balances per transaction and per book       (C1)
no transaction crosses books                        (C1)
Cells cannot overspend                              (C4)
global real-spend caps include reserved spend       (C5)
dead Cells cannot act                               (C8)
quarantined Cells cannot access public-facing tools (C8)
birth requires carrying-capacity permission         (C9)
balances are derived from ledger                    (C3)
event handlers are idempotent                       (C6)
every lifecycle transition creates an audit event   (C10)
every genome has a canonical hash                   (C11)
all timestamps are UTC                              (C11)
all money uses integer minor units                  (C11)
```

Stop after Phase 1 and show: repository tree; how to run the tests; invariant/Charter coverage; how to run the CLI; known limitations; the exact next recommended task.

## 30.1 Coding rules

Type hints throughout; Pydantic for structured data; integer minor units for money; append-only ledger; tests with every module; avoid unnecessary frameworks; provider-agnostic interfaces; mock before paid APIs; no public web before the simulator works; no generated code outside a sandbox; no API keys to Cells; no Cell modifies kernel code; preserve deterministic replay; store all model/tool calls with costs; fail closed on invalid permissions or schemas; write migrations rather than hand-altering DB state; keep `docs/DECISIONS.md` current.

---

# 31. Data Model (reference)

Suggested entities (Phase 1 subset in **bold**):

**cells**, **cell_genomes**, cell_states, **cell_balances** (derived), **ledger_transactions**, **ledger_entries**, ledger_accounts, experiments, experiment_results, **events**, **event_inbox**, **event_outbox**, **reservations**, **resource_usage**, **audit_events**, artifacts, artifact_lineage, modules, module_lineage, teams, team_members, model_calls, sandbox_runs, tool_calls, permissions, approvals, prediction_register, coroner_reports, market_observations, synthetic_customers, synthetic_listings, synthetic_transactions, novelty_archive, behavioural_descriptors, knowledge_graph_nodes, knowledge_graph_edges, audits, policy_violations, human_interventions, external_action_registry.

Required Phase-1 ledger accounts: `external_capital`, `colony_treasury`, `seed_bank`, `promotion_pool`, `infrastructure_reserve`, `liability_reserve`, `cell:{id}:cash`, `cell:{id}:committed`, `revenue`, `external_expense` — each scoped to a book.

---

# 32. Final Definition

MITOSIS v0.2 is:

> A capital-conserving, resource-metered, population-limited evolutionary operating system in which untrusted software organisms discover, build, test, and commercialise economic mechanisms under independently verified selection.

The colony's ultimate measure of success is:

> **Real settled net profit after real costs, with autonomy-adjusted profit reported to expose hidden human labour and subsidies.**

Everything else exists to help the colony reach that outcome without fabricating success, optimising simulator quirks, creating unbounded costs, hiding liabilities, sacrificing long-term profit for short-term noise, or letting unsafe evolved artifacts escape containment.

The core loop:

```text
discover -> hypothesise -> build -> test -> verify -> predict -> promote
-> transact -> settle real revenue -> measure real net profit
-> allocate capital -> scale, mutate, collaborate, sleep, or die
```

The kernel protects the world from the Cells. The Cells are free to evolve inside those boundaries. The first purpose of the simulator is to prove the machinery selects useful economic traits. The ultimate purpose of the live system is to make more real money than it consumes.
