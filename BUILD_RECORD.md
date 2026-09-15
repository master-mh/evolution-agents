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
naming collusion and counterparty deception, and a teeth-check runner
that cannot touch the real tree, 2026-07-21 through 2026-09-15):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-15 — Every *Disproved by:* pointer, run and dated (ADR-092)

Eighth of the research-driven slices; tooling, no kernel change.

### What shipped

- `scripts/check_disproved_by.py` extracts each open PRIORITIES.md entry's backticked pointer tokens
  and resolves them: CLI verbs through `check_docs_facts.cli_verbs`, files, `module.name` definitions
  by AST, tables from migrations, kernel names. It dates each resolving token with git — the commit
  introducing it against the `git blame` date of the pointer's line — and marks an entry `RE-READ`
  only when a token is newer than the pointer. `--selftest`; `--fail-on-resolved` for a stricter
  caller; it never edits the file.
- A weekly Claude Code routine (created disabled) runs it and adjudicates only the entries it flags.

### Found

- **Resolution alone flagged every open entry.** Most pointers name a symbol that existed when the
  entry was written — entries narrowed or split around it on purpose. A report that flags everything
  is a report nobody reads; with dating, the answer at commit time is **0 of 9** open entries (all 9 pointers resolve).
- **Dotted tokens never date.** `git log -S death._budget_exhausted` matches nothing, because that
  dotted string never appears in source. Dotted tokens are dated by their last component and files by
  the commit that added them.
- **One stale claim, found by reading rather than by the script.** The §23.2 liability entry said its
  wrong claim was "still copied into `approval.py`'s `liability_minor_units` comment"; that comment
  had already been corrected. The sentence is gone. (The script could not have caught it: the pointer
  was right, and the stale sentence was prose around it.)

### Verification

`--selftest` passes; the live run's result is above. The routine's first run is left to the operator,
who enables it.
