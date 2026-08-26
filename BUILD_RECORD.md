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
measurement, §15.1 anchoring, and the twins that
chose the fix, 2026-07-21 through 2026-08-26):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-26 — A recent proposal shows its wording only once a person judged it

`context._was_decided` + 5 tests + golden expectation **25 -> 26** (ADR-052, implementing what its
twins chose). No migration.

§15.1's proposal log now renders `- [kind]\n    -> note` for an undecided proposal and keeps the
summary once a person judged it. This is the pending-only variant ADR-052 recommended — narrower
than the `nosummary` arm that won, because that one hides the summary even on the decided proposals
ADR-046 exists to deliver.

### The line is drawn where `_decision_note` already drew it

**`expired` is not decided**, and that is the one judgement ADR-052 did not settle — its arms had no
expired proposals. The docstring of `_decision_note` refuses to collapse "nobody looked" into "was
judged", so a closed review window withholds the summary like any other undecided state. It is the
status that looks decided and is not, which is why it gets its own test.

### Verification

- **Confirmed live, because no replay can see a prompt edit.** The shipped kernel scores **1.833
  effective ideas per run** against ADR-052's arm at 1.852 and control at 1.089 — every parsed
  proposal distinct in all four runs. `MockProvider` cannot show this, which is the whole reason
  ADR-052 existed.
- **Teeth-checked three ways**, each caught by a named test: always-decided (the old behaviour),
  never-decided (the `nosummary` arm, which deletes ADR-046), and expired-counted-as-decided.
- **Two existing tests failed for the right reason and were repaired, not weakened.**
  `test_context_never_loads_the_entire_history` detected history-loading *through* the summaries, so
  hiding them made it **silently vacuous** (`got []`) rather than red — it now approves its probes,
  which restores the detection and tests the leaky case: the slice must stay bounded even when every
  entry is fully shown. `test_an_unreviewed_proposal_is_distinguishable_from_an_expired_one` lost its
  summary prefix, so it asserts **order** instead, which is what still ties each note to its proposal.
- **Golden diff is two rows of eleven**, and only `context_tokens` — the only two wakes in the
  scenario that assemble a non-empty proposal log. `model_calls` and `resource_usage` follow in the
  matching rows; `resource_usage.minor_units` is unchanged at 1, so **`balances` is identical in
  every account in every book** and `proposals` is byte-identical.
- **1009 tests passing** (5 new, 0 removed; up from 1004).
- Next: an arm that **approves proposals mid-run**. Nothing measured yet exercises the decided
  branch, so nothing shows whether a Cell anchors to an *approved* summary too — the one result that
  would put ADR-046 and diversity back in genuine conflict and move this line.
