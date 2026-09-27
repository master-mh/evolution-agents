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
tracing, and a read-only colony dashboard, and full liability reserves with the step-5 dry run that found the artifact-kind and export-message bugs, and the live run from a Cell that abstained to a product on sale, 2026-07-21 through 2026-09-26):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-27 — Getting the first sale's path ready: posts that tell the truth, and a seller that can still wake (ADR-110, ADR-111, ADR-112)

The operator asked for "next steps to make money". The product had been on Gumroad a day with no sale and
nobody aware of it, so the session did the sale-readiness work (option A of the prime). The work was
live wakes in the operator's `colony.db`, and each one exposed a kernel gap that the next wake confirmed closed.

- **Caps (operator decision):** hour $1 → $3, day $5 → $10. One $9 sale's ~$1.40 fee had been larger than
  the whole hour. The month stays at $50.
- **ADR-110: a Cell is shown the product it is selling.** Asked for community posts, the Cell wrote from the
  playbook's *title*. It invented a day schedule, a "90% of errors" figure and a "days to hours" claim, and
  used first-person experience. The most recent commercial export now sits in context in full, after the
  decision notes; when it doesn't fit, a note names it instead. 6/6 teeth-checked. The placement test first
  MISSed twice: its budget was read off the very ordering it defends.
- **ADR-111: an action taken outside a grant is recorded after the fact, with its offer.** The revised posts
  said "$19". That was the price the Cell had planned; the $9 listing existed nowhere in the kernel. Migration
  0045 rebuilds the registry so an `operator_record` row is completed, dated and grant-less, and 0021's
  guarantee still holds for Cells. Collisions are reported, not refused. The Cell sees the offer, labelled
  "what a buyer is charged" once it was clear its genome's `$19` outranked an unlabelled line. A reference is
  shown only on channels that address nobody (§16.3). The Gumroad listing is back-filled. 12/12 CAUGHT.
  Golden 47 → 48.
- **ADR-112: a held seller is advanced working capital.** Under the 100% hold, a sale left the seller at
  −80¢ for 120 days. A share of each hold is now advanced from `seed_bank` in the sale's own transaction,
  capped per Cell, and repaid first on release. The hold is untouched, so a refund is still met in full.
  Live policy: 25%, $5 cap. 8/8 CAUGHT after two mutations were corrected. `test_real_spend_registration`
  caught both new types unclassified, as it is meant to.
- **Outcome:** four community posts (artifact `cc0a9788…`) approved and exported. Every tip comes from the
  playbook, the price is $9, and the disclosure is next to each link. The operator posts them by hand. There
  is no channel to record them yet (PRIORITIES).
- Live spend today: 7 calls across 4 wakes, 102,299 micro-USD true (14¢ recorded); one wake was lost to a
  RESOURCE shortfall on its repair, and RESOURCE was topped up by 100,000 (shadow units, free).
- Two full-suite runs stalled at 99% CPU (about 12% in) and were killed. Three later runs passed in about
  190s and the stall never reproduced; logged, cause unknown.
- 1705 tests; golden 48.

**Next:** the operator posts the four drafts. On the first sale: `record-revenue` then `record-fee`, and
the hold and advance post themselves. After that, a `community_post` channel so the posts are in §21's
registry, or Phase 7 scouting (read-only `http_get`) for a second product in the same class.
