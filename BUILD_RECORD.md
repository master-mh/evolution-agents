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
auto-promotion reaching the scheduled `tick`, and the flight simulator's first
slice (mock Cells deciding through the real deliberation pipeline),
2026-07-21 through 2026-09-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-05 — Phase 2 flight simulator, second slice: a second market family, real environment separation, and scheduled regime shifts (Slice F, part 2)

Continuing F1's own sub-slice sequence (`docs/DECISIONS.md`'s ADR-072) without a fresh plan-mode
round-trip — the architecture was already settled there. ADR-073 is the full as-built record.

### What shipped

- **`RuleBasedMarket`** — the second family brief requirement F.2 (§8.3) requires. Where
  `UtilityMaximizingMarket` compares a continuous random willingness-to-pay draw against price, this
  one branches on discrete rules throughout: a price tier, a genome-declared boolean flag required
  to clear the standard tier, a premium tier gated on a declared quality flag plus a fixed-cutoff
  coin flip. Proven independently shaped, not just differently named: one fixed genome (price=600,
  no `durable` flag) sometimes sells in the sibling family and never sells in this one.
- **`EnvironmentSuite`** (§8.1) — a real three-field config object (`training`/`validation`/
  `secret_challenge`), enforced structurally rather than by convention: `runner._run_one_epoch`'s
  own signature takes one environment, not a suite, so the routine loop has no path to
  `validation`/`secret_challenge` even by mistake. Proven with a fake that raises the instant
  anything calls it, not an AST check. Wiring a `validation`-consulting selection policy is
  deliberately left to Slice G — `RandomEligibleSelection` doesn't consult any environment outcome
  at all, by design, so there is no real consumer yet to wire it to.
- **Scheduled regime shifts** (§8.4) on both families, at one shared fixed epoch: price compression
  for the utility-maximizing market, stricter enforcement (a narrower always-clears budget tier) for
  the rule-based one. A fixed epoch, not a random shock, because §8.4 calls this "part of fitness
  evaluation" — something a Phase 3 comparison could pre-register against. Recorded via
  `audit.record` the same way a selection decision already is (ADR-072), rather than a second
  schema-level identity for the same fact; surfacing it in the manifest itself stays out of scope,
  per `manifest.py`'s own docstring assigning that to F5.
- `cli.py`'s `simulate` verb gains `--environment {utility_maximizing_market,rule_based_market}`.

### A pre-existing test broke, correctly

`test_the_two_environment_families_disagree_on_the_same_genome` (written before the regime shift
existed) sampled 30 epochs at a price that the shift made provably unsellable past epoch 10 in the
sibling family — the specific seed/price combination had zero hits in the remaining pre-shift
window. Fixed by restricting to the pre-shift window and picking a price verified, not assumed, to
hit within it. The `grep every reader of it, not just the enforcer` habit applies to a change in
what an epoch *means*, not only to a changed field.

### Verification

12 new tests (24 total in `tests/test_simulation.py`): the second family's purity, tier rules, and
proven disagreement with the first; the environment factory's name-based construction and rejection
of an unknown name; the CLI flag actually changing which family runs, not just being accepted; the
routine loop's structural blindness to `validation`/`secret_challenge`; both regime shifts,
behaviourally (a price chosen so the post-shift outcome is deterministically impossible, not just
statistically unlikely) and via `advance()`'s returned event; the shift's audit-trail record. Six
teeth-checks, each confirmed to fail for the stated reason and restored verbatim: the durable-flag
tier rule, the unknown-name rejection, the CLI wiring, the routine loop's environment source, the
regime-shift epoch branch, and the audit-recording loop, each removed in turn. Full suite green
(1263, up from 1251); golden run unaffected (hash unchanged at 38 — no existing scenario touched);
`ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: the remaining mutation operators (§14.1, Slice F3), chaos drills (§28), full manifest
  richness including regime-shift bookkeeping (Slice F5), then Slice G's remaining
  `SelectionPolicy` implementations and Slice H's pre-registered Phase 3 comparisons.
