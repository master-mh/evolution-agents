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
decision loop's first six sub-slices (a run record that never named its
own selection policy and founder concentration as a real time series;
simulator-native fitness dimensions, the full decision-record schema, and
Thompson sampling; the single-leaderboard control policy; Pareto selection
reproducing the whole front, and a gate found structurally unreachable
through this pipeline; MAP-Elites, one elite per occupied niche; staged
funding composing everything, and the cross-family validation deadlock it
surfaced),
2026-07-21 through 2026-09-06):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-06 — Closing the evolutionary decision loop, part 6: the cross-policy acceptance harness (Slice G, part 6 — Slice G complete)

Continuing the plan from ADR-077 through ADR-082 without a fresh plan-mode round-trip. ADR-083 is
the full as-built record.

### What shipped

G6 needed no new mechanism — every property the brief asks it to verify was already produced by
earlier sub-slices (`simulation_selection_decision`/`simulation_mutation` audit events since F1/G0;
`config_hash`/`environment_name`/`selection_policy_name` since ADR-077). This is purely an
acceptance-test suite proving those properties hold under real, live-run conditions: the same
`RunConfig` run once with `RandomEligibleSelection` and once with `StagedFundingSelection` (two
independent in-memory databases, not one shared connection) produces matching
`config_hash`/`environment_name` and differing `selection_policy_name`; every `simulation_mutation`
event's `parent_cell_id` appears in a same-epoch `simulation_selection_decision` event's
`chosen_parent_cell_ids`; `founder_concentration`/`distinct_genomes` form a real, growing time
series across a run; `StagedFundingSelection` holding its own validation environment never reaches
`EnvironmentSuite`'s isolated `validation`/`secret_challenge` roles, re-verifying ADR-073's guarantee
with a policy that actually exercises the seam it depends on.

### A defect found in ADR-082's own live-run test, on an already-pushed commit

Building a scenario that genuinely reproduces under `StagedFundingSelection` required a 24-way
seed/scale sweep — every combination showed zero reproduction, ever. Tracing `decide()` directly
found why: no mutation operator ever sets `product.durable`/`product.quality`, so `RuleBasedMarket`'s
standard/premium tiers are permanently unreachable, and no founder starts priced in the one tier that
*is* reachable — with `RuleBasedMarket` as validation, every elite is rejected forever, so no
mutation (including a price mutation that might reach the reachable tier) ever gets a chance to run.
A genuine structural deadlock, confirmed by switching validation to the same family or to `None`,
both of which reproduce reliably. ADR-082's own live-run test used `RuleBasedMarket` and asserted
only `failures == ()`/conservation — which holds trivially for a colony that never reproduces — so it
had never once exercised real reproduction since it was written. Two of this slice's own first-draft
tests made the identical choice and were silently `pytest.skip`-ing every run for the same reason.
All three fixed here (same-family validation at a verified-reproducing seed), corrected forward per
this repo's rule against rewriting pushed history rather than amending ADR-082. The deadlock itself
is real and not a `validation_probe` bug (proven correct in isolation by ADR-082's own unit tests) —
an honest consequence of `RuleBasedMarket`'s intentionally harsh design meeting mutation operators
never given a way to satisfy it. A new, permanent test checks this finding itself; both viable fixes
are named in `FUTURE_BUILD_HOOKS.md`, neither of them Slice G's job.

### Verification

5 new tests plus 3 corrected (104 total in the simulation area). One teeth-check — recording a
mutation event's `parent_cell_id` as the child's id instead of the parent's — confirmed to fail the
traceability test for the stated reason and restored verbatim. Full suite green (1334 total); golden
run unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: Slice H's pre-registered Phase 3 comparisons (a pre-registration document plus the six
  required comparison runs — pick a policy/validation combination known to reproduce, per this
  slice's own finding). The >= 500 Cell/>= 10,000 epoch Phase 2 acceptance benchmark itself remains
  documented but not yet run to completion (ADR-076).
