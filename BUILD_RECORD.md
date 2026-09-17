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
call becoming its own deliberation outcome, 2026-07-21 through 2026-09-16):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-17 — A repair turn that names only the error specifies the whole reply (ADR-102)

One paid wake on 2026-09-16 (`claude-haiku-4-5`) spent two calls and recorded nothing, and the
second reply was **worse** than the first. Reply 1 was `{"kind": "abstain", "summary": "No proposal
at this scheduled cycle."}`, rejected for a missing `rationale` and `estimated_cost_minor_units`.
The repair turn named those two fields. Reply 2 carried exactly those two fields and had dropped
the `summary` it had already produced correctly. Between them the two replies contain a complete
proposal; neither one is.

ADR-069's docstring named the choice that caused it: point at the specific error rather than repeat
the schema, because "the schema is already the first turn's own content, still in context, and
restating it would waste tokens on the part that was never the problem." The premise is true. The
inference is not — **on a small model the part that was never the problem is what gets dropped**,
because a turn naming two field names does not read as a patch to an object. It reads as a
specification of the reply.

### What shipped

- **The repair turn asks for an edit.** "Correct the JSON object you just sent. Do not write a new
  one: keep every key you already sent, with its value unchanged, and change only what the error
  above names." The failed reply was already the middle message of the repair request (ADR-069 built
  that); what was missing was an instruction pointing at it. No new message, no new context.
- **It names every required key**, from a new `proposal.always_required_keys()` — the reply skeleton
  minus the conditional payloads, derived so it cannot drift from what the parser demands. This
  covers what an edit instruction structurally cannot: a first reply that was not JSON has no object
  to edit *from*, and that is the commonest unparseable shape this repo has measured.
- **No merge.** Carrying a field forward from reply 1 into reply 2 was the third candidate and the
  tempting one. Refused: it manufactures an utterance no Cell made, it is the salvage
  `proposal.parse` explicitly refuses one layer up, and it destroys the premise ADR-070 used to keep
  parse-repair away from the Auditors — repair reformats and never re-judges; a merge is the kernel
  *authoring*.
- **`rationale` and `estimated_cost_minor_units` stay required for `abstain`.** For that kind the
  rationale is the entire content, and §23.5 says the queue will be optimised against — a
  zero-content abstain is an outcome a Cell can always emit for free.

### Found

- **The under-filling invitation is real and is not where it looked.** "Most wakes produce nothing"
  is the trailing sentence of the **`artifact`** key's description, one clause after `never with
  kind "abstain"` — which is what makes it read as being about abstain wakes. The likelier cause is
  the general rule below it, "Leave out any key you are not using": an abstaining model applying
  that to `rationale` produces the observed reply 1 exactly. A wording hypothesis, not a finding —
  this repo does not tune prompt wording without a live run.
- **Second ADR premise to be its own defect.** ADR-101 found ADR-069's "the first call is known to
  have succeeded and been billed" disproved four paragraphs below itself; this is ADR-069's other
  stated premise. Both were invisible to the suite for the same reason: `MockProvider`'s reply is an
  input, not a response to the wording (ADR-049).

### Verification

1582 tests pass (5 new), golden run exact at version 42 — `_repair_instruction` is never rendered in
a replay with no malformed reply, so unlike ADR-068 no prompt length moves. Ruff and docs-facts
clean. 5 guards teeth-checked, 5 CAUGHT: ADR-069's instruction restored verbatim fails both new
guards (the structural one names the missing keys, the end-to-end one reproduces the observed wake
as UNPARSEABLE), the assistant turn dropped from the repair request fails the test that the object
being edited is present, and `always_required_keys` narrowed by hand fails the skeleton-agreement
test and — narrowed past a parser-required field — the test binding it to `Proposal`.

### Confirmed live

One operator-approved paid call (`claude-haiku-4-5`), replaying the observed conversation through
the production path — `_attempt_parse_repair`, the real gateway, the real provider, reply 1 and its
validation error verbatim. **The model kept the `summary` byte-for-byte** and added the two fields
it was missing, correctly omitting `risk_tier` for `abstain`. 1,716 in / 196 out, 2,696 micro-USD
recorded as 1 minor unit, conservation and the hash chain green in all three books. One call, not
two: the first reply's outcome was already known.

n=1 and one model — it shows the observed failure no longer reproduces, not a repair *rate*. The
rationale it produced answered the other question in passing: generation 0, no revenue, every
channel and tool OFF, "proposing work I cannot execute serves no purpose." That is the content
§10.3/§10.5 need to tell "nothing worth doing because X" from "produced nothing", and relaxing the
requirement would have thrown it away.

- Next: §28 Phase 9's remaining kernel items — the liability reserve, a merchant channel behind
  `real_commerce`, and §1.1's operating-cost terms.
