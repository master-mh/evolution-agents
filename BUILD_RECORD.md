# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, the experiment, experiment attribution,
proposed experiments, the strategy kind decided, the experiment_id foreign keys, §13.1's
normalised cost, the reply format a model can follow, the temperature/diversity
measurement, §15.1 anchoring and the twins that chose the fix, the proposal log that
shows no wording, the §23.4 repeat, the wake reason, the genome, the human-decision wake,
the +15% that did not survive honesty, §13.4's concreteness measure,
§13.2's selector, §12's novelty archive, the inbound counterparty key,
§12.1's declared third dimension, rung 8, §12.3's `P(next stage)`, the
Auditor path for §13.3/§13.4's content judgments, the software_native_advantage
gate reading a resolved content audit, model_policy's temperature socket,
risk_tier becoming optional for abstain, the bounded single parse-repair
retry, the argued refusal to extend it to the Auditors or `call-model`,
an external audit's clean source-distribution archive, its egress-boundary
repair (robots.txt transport, SSRF, honest personal-data status),
documentation/safety-claim reconciliation, a narrow runtime-defect lint gate,
auto-promotion reaching the scheduled `tick`, the flight simulator's five
slices (mock Cells deciding through the real deliberation pipeline; a second
market family with environment separation and regime shifts; the remaining
mutation operators wired through a real choice; chaos drills as repeatable
scenarios; manifest richness, a CI-scale acceptance test, a founding cap bug
fix, and a retained benchmark artifact), and closing the evolutionary
decision loop's six sub-slices (a run record that never named its
own selection policy and founder concentration as a real time series;
simulator-native fitness dimensions, the full decision-record schema, and
Thompson sampling; the single-leaderboard control policy; Pareto selection
reproducing the whole front, and a gate found structurally unreachable
through this pipeline; MAP-Elites, one elite per occupied niche; staged
funding composing everything, and the cross-family validation deadlock it
surfaced; the cross-policy acceptance harness), seed-paired batch
comparisons, a sealed simulated run, tools naming what observes their
effect, two measurement instruments (judge entanglement and evaluator
epochs), verbalized sampling as a genome sampling policy, Amendment A20
naming collusion and counterparty deception, a teeth-check runner that
cannot touch the real tree, every *Disproved by:* pointer run and
dated, workflow structure as a gene the kernel runs, Slice H's arm
settings and the simulator stall they uncovered, and Phase 3's
pre-registered run that found no selection effect, and refunds and
chargebacks naming the payment they reverse, and payment fees as a
charge nobody chose, and §1.1's profit report with the shadow rate a
person declares, and the trial's legal identity, and a failed model
call becoming its own deliberation outcome, and a repair turn that names
every required key, and a self-critique loop on LangGraph with opt-in
tracing, and a read-only colony dashboard, 2026-07-21 through 2026-09-22):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-24 — A real sale is held against its refunds until the window closes (ADR-106)

Asked to get the colony to real money as fast as possible. The kernel could already record, attribute and
report a sale; what §28 Phase 9 still demanded before a live trial was **full liability reserves**, and
nothing had ever posted to `liability_reserve`. The operator chose 100% held until the refund window closes.

- **`liability.py` + migration 0042.** An operator policy (append-only; share in basis points, window in
  days). With one in force, `record_revenue` holds a USD_REAL sale in the sale's own transaction;
  `record_reversal` pays a refund or chargeback from the hold first; `release_due` returns what a closed
  window leaves. Hold and release name their payment through `provisions_for_transaction_id`, hash-chained.
- **Reading the spec first changed the accounting.** `accounts.py` had classified the reserve as *spend*.
  §2.3 lists reserves beside cash, and §10.2 names unsettled liability exposure as its own dimension — so a
  hold is restricted cash, and the account moved to `CAPITAL_ACCOUNTS` before its first posting. Counted as
  spend, a full hold would have told the Cell (via `context`) it had consumed its own sale.
- **The window is derived, never stored** — the sale's `created_at_utc` plus the window of the policy in
  force at the hold. Transaction metadata is outside the hash preimage, so a stored date would have been
  editable without trace.
- **A replayed sale is never held retroactively**: `record_revenue` asks whether the payment already
  existed before posting, because the ledger answers a replay with the original.
- CLI: `set-reserve-policy`, `reserves`, `release-reserves`; `profit` prints what is still held and names
  the abstention when no policy is declared.
- **Hand-verification found the one bug no test had asked about:** §10.5's `budget_exhausted` read a Cell
  at zero cash with its sale held as "no money, nothing in flight" — `reap` would have killed the first
  successful seller (at −40 once a fee came out of cash while the gross was held). Held money now counts as
  in flight, like `committed`.
- 26 new tests; 14 guards teeth-checked, 14 CAUGHT. Golden run unmoved (USD_REAL only).

**Still between the colony and its first real sale:** the operator's merchant account and trial identity
(`set-trial-identity`), the reserve policy's window in days, and — for Phase 9 proper — the channel gate
(PRIORITIES). Selling by hand, recording with `record-revenue`/`record-fee`, is already fully supported.

### Same day — step 5 run end to end: a Cell writes a product, an operator clears it for sale

Dry run on the mock provider (Ollama's Metal backend failing again): create a Cell → wake → proposal
plus `fulfilment_artifact` → `export-artifact --commercial` refused while rights are `unknown` →
`set-rights --colony` → export passes → trial identity + reserve policy → `record-revenue --artifact`
→ `record-fee` → `profit`/`reserves`. Conservation green in all three books, hash chain valid. Three
defects found, two fixed here:

- **A new Cell was never told which artifact kinds exist.** The schema said "an artifact kind from your
  context", and nothing in a new Cell's context names one — a real model had to guess. **And the guess
  was stored**: the wake path records through `artifacts._create_locked`, which never ran `_validate`, so
  `proposal.py`'s "validated at record time" was a stale claim. `ARTIFACT_KINDS` moved to `models`, the
  hint lists all seven, and `ArtifactSpec` refuses any other at parse time — an ordinary invalid reply
  that ADR-069's repair turn can correct. Golden 42 → 43 (+45 input tokens on each of 12 calls, nothing
  else).
- **`export-artifact` printed `commercial_use: unknown` on a commercial export that had just passed as
  `permitted`** — the stored field, not the position in force (ADR-041). It now prints what the gate read,
  and says how to get the content out (`artifact <id> --content`). The verb had no CLI test at all.
- **Not fixed — the operator's call:** processor fees count against the real-spend caps (ADR-098, by
  design), so at a $10/month cap the fees on ~4 sales of $19 would lock the colony out of model calls
  for the month; and a Cell whose sale is fully held and whose fee took its cash negative cannot pay
  for its own next wake until the hold releases. Both in PRIORITIES.
- Review time was recorded as 0 minutes: Phase 9's "complete human-time accounting" is not met by the
  manual path yet.

3 more guards teeth-checked, 3 CAUGHT.
