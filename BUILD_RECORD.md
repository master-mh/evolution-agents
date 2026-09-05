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
auto-promotion reaching the scheduled `tick`, the flight simulator's first
slice (mock Cells deciding through the real deliberation pipeline), and its
second (a second market family, environment separation, regime shifts),
2026-07-21 through 2026-09-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-05 — Phase 2 flight simulator, third slice: the remaining mutation operators, wired through a real operator choice (Slice F, part 3)

Continuing the same sub-slice sequence (ADR-072, ADR-073) without a fresh plan-mode round-trip.
ADR-074 is the full as-built record.

### What shipped

Six new operators in `src/mitosis/simulation/mutation.py` — market/customer, product/delivery,
acquisition-channel, pricing/revenue-model, workflow, model-policy temperature — the brief's exact
list, alongside the no-op/control that shipped in F1. Discrete-choice operators (segment, delivery
mode, channel, workflow structure) exclude the parent's current value from their candidates, so
invoking one always changes that field; the two continuous operators (price, temperature) don't
force a guaranteed change — any nonzero perturbation already differs, and the rare clamped-identical
case (temperature already at a bound) is recorded honestly rather than retried away.

### A hardcoded call was hiding behind a decision-record field that already existed

`SelectionDecision.mutation_operator` has recorded an operator *name* since F1, but
`runner._run_one_epoch` never read it — every reproduction called `mutation.no_op(...)` directly.
Unnoticed while `no_op` was the only real operator; wiring five more without fixing this would have
shipped them as functions nothing in the live pipeline ever calls. Fixed with an `OPERATORS`
dispatch table and `RandomEligibleSelection` now choosing an operator name at random from the same
`rng` it already draws the parent choice from.

### A second bug in the same call site

The reproduction loop passed the bare `master_seed` to every mutation, unchanged across the whole
run — harmless for a no-op that ignores its seed, but every real operator would have drawn the
identical "variation" forever. Fixed with a per-event label,
`f"{master_seed}:mutation:{epoch}:{parent_id}"`, matching this package's existing seeding
convention. Same shape as F1's tuple-seed bug and F2's stale-epoch-range test break: a call site
built before its inputs mattered, unexercised until something downstream actually varied by them.

### Recording the brief's five required facts without a schema change

`genome.inherit()` merges a mutation key by key, not a deep merge — an operator changing one nested
field must carry the rest of that key's own content forward, or a fact the mutation didn't intend
to touch would be silently dropped from the child. Parent/child hashes already live on
`cells`/`cell_genomes`; the seed, before/after diff, and distinctness flag go through
`audit.record(event_type="simulation_mutation", ...)` — the same "explain, don't define a second
identity" reason `SelectionDecision` and regime-shift events already use, for the same underlying
cause each time: a mutation that collapses to the parent's own existing genome row (ADR-018) writes
no new row, so only the audit trail can attribute a fact to *this* reproduction event.

### Verification

9 new tests (33 total in `tests/test_simulation.py`): each discrete operator's guaranteed change;
registry names matching returned names; price/temperature bounds; determinism given a fixed seed
across all seven operators; nested-field preservation against the merge semantics; per-event seed
uniqueness; a full run's audit trail checked for completeness and for a real operator actually
firing and producing distinct content through the live pipeline. A pre-existing F1 test asserted
every child's genome_hash equals its parent's — true only because `no_op` was the sole operator
ever chosen; the assertion was removed (now false in general) and its still-true claim (real
funding, a real row) is what remains, with hash-collapse behaviour covered by the new audit-based
tests. Four teeth-checks, each confirmed to fail for the stated reason and restored verbatim: the
discrete-operator exclusion, the dispatch, the mutation audit-recording call, and the per-event
seed, each removed in turn. Full suite green; golden run unaffected (hash unchanged at 38); `ruff
check .` and `scripts/check_docs_facts.py` both clean.

- Next: chaos drills (§28) and full manifest richness (Slice F5) close out Slice F, then Slice G's
  remaining `SelectionPolicy` implementations and Slice H's pre-registered Phase 3 comparisons.
