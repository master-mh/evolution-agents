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
surfaced; the cross-policy acceptance harness), and seed-paired batch
comparisons,
2026-07-21 through 2026-09-14):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-14 — A sealed simulated run (ADR-085)

Second of the research-driven slices. Prompted by Anthropic's 2026-09-09 alignment assessment:
four incidents in which models were told they were in a simulation without internet while an
outer configuration error left real connectivity on.

### What shipped

`network_seal.py` installs one PEP 578 audit hook per process that refuses connect, bind, name
resolution, datagram sends, `http.client`/`urllib` requests and every child-process start while a
`sealed()` block is active; outside a block the hook returns on one integer test. `runner.run`
seals the whole run, founding included, and reads `git rev-parse` once before sealing (it is a child
process, and the run record and manifest previously read it twice).

### Found while building

- **A refusal escaping a provider stranded both reservations.** The provider-path test passed on
  its real assertion — nothing reached the listener — but `gateway.call_model` only caught
  `ProviderError`, so a `NetworkSealed` left the call's USD_REAL and RESOURCE reservations committed
  for the sweeper to guess about. The gateway now maps it onto the definitely-unbilled path, and
  `providers._is_execution_unknown` finds it down an exception's cause chain so an SDK wrapping it in
  a connection error cannot strand funds in `execution_unknown` either. Every other failure keeps
  the conservative default.

### Verification

8 tests put a real listener on loopback and require that no connection arrives from an epoch hook,
a replaced provider, or a bare gateway call; one requires a child process be refused; three pin
nesting, lifting on exception, and inertness outside a seal. Six teeth-checks, all failing on the
intended assertion (two first scored MISS by a wrong expected-text string in the checker, not by the
tests). Full suite 1361 passed; golden unchanged; lint and docs-facts clean. Not a sandbox — logged in
`FUTURE_BUILD_HOOKS.md` along with sealing the golden run.

- Next: judge entanglement, verbalized sampling, the workflow gene, the tool-evaluator guard,
  evaluator epochs, the §11.3 amendment, the teeth-check runner, the claim-drift checker; then Slice H.
