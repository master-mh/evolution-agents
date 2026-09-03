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
§12.1's declared third dimension, rung 8, §12.3's `P(next stage)`, and the
Auditor path for §13.3/§13.4's content judgments,
2026-07-21 through 2026-08-31):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-03 — §13.2's `software_native_advantage` gate reads a resolved content audit

`selection._software_native_advantage` + 3 new tests + golden run unchanged (ADR-066). **The gate
ADR-065 deliberately left `UNMEASURABLE` is now conditionally measurable**, the same way ADR-060
gave `structural_novelty` a live prior: `content_audit.py`'s Auditor path is this gate's one
consumer, and `test_only_selection_consumes_a_content_audit` (renamed from `test_nothing_yet_
consumes_a_content_audit`) keeps it that way.

### Only a resolved prediction may gate — an unresolved one is exactly §10.5's forbidden shape

An audit's `probability` is registered before the outcome is known; reading it into an automatic
gate would be gating a candidate on an *estimate*. The gate instead reads `prediction.get(conn,
audit.prediction_id).outcome` — set only once the register has resolved the claim against what was
actually observed. No audit at all is `UNMEASURABLE`, unchanged; an audit that exists but has not
resolved is `UNEVALUABLE`, not a rejection — the same distinction `_evidence_quality` already draws
for a Cell with no resolved forecasts.

### Any single resolved, vindicated concern rejects — no quorum across Auditors

§10.5's "an independent Auditor must concur" bar is written for *killing* a Cell. This gate does
not kill — a rejected candidate can be re-proposed once the concern is addressed, and more than one
Auditor may record an opinion about the same genome (migration 0031's partial unique index only
stops the *same* Auditor opining twice). Requiring unanimity would let a vindicated "ordinary
freelancing" flag be outvoted by Auditors who never looked closely, so the rule mirrors
`_policy_compliance`'s existing posture: any one resolved, vindicated concern rejects; the register
scoring the Auditor who raised it is the check on carelessness, not a second gate reading their
track record.

### A stale PRIORITIES claim, corrected rather than left to drift

PRIORITIES said `test_no_kernel_path_acts_on_a_frontier`'s allowed-importers list would also need
an edit. It did not — that test scans who imports `selection`, not what `selection` imports, and
this slice only added the latter. Logged and corrected in ADR-066 rather than left stale for the
next reader.

### Verification

- **3 new tests, teeth-checked.** Reverting the gate's wiring in `evaluate()` back to
  `_unmeasurable_gate("software_native_advantage")` failed the new PASSED test with the expected
  assertion (`UNMEASURABLE` where `PASSED` was expected) — a real MISS, not a false CAUGHT.
- **1143 tests and the golden run green, hash unchanged.** No fixture Cell has ever had a content
  audit (ADR-065's own golden note), so this slice's diff is nowhere in the replay — additive over
  a gate nothing in the scenario reaches yet.
- Next: `selection.py`'s frontier still carries two dimensions with no data at all
  (`economic_potential`, `reproducibility`) — see PRIORITIES `Next` for what each is blocked on.
