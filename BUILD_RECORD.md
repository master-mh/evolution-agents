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
risk_tier becoming optional for abstain, and the bounded single parse-repair
retry,
2026-07-21 through 2026-09-03):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-04 — Parse-repair is *not* extended to the Auditors or `call-model`

`auditor.py` docstring correction + ADR-070; no other code change. **The ADR-069 parse-repair
mechanism stays in `deliberation.py` only — the follow-up BUILD_RECORD left "unargued, not a gap"
is now argued, and the conclusion is: don't port.** Recording the refusal *is* the deliverable.

### The three sites split two ways, and neither wants the retry

- **`cli.py`'s `call-model` is inapplicable, not scoped-out.** `cmd_call_model` takes a freeform
  `--prompt`, optional freeform `--system`, and prints `call.response_text` *raw* — no `parse()`, no
  schema, no `ProposalError`. A repair re-prompt names "the specific validation error"; there is
  none to name. This verb belongs on no follow-up list; struck.
- **`auditor.py` + `content_audit.py` look identical to deliberation, and the resemblance is the
  trap.** Same shape (paid `call_model` -> strict `_parse` -> recorded rejection on failure), so the
  mechanism would drop in. But their `_parse` error fires on two causes, not one: malformed JSON /
  schema violation *and* an **incoherent verdict** (`concern` above the coherence midpoint,
  `no_concern` below). Re-prompting a Cell to reformat its own proposal is reformatting;
  re-prompting an Auditor to fix a contradiction in its own verdict is coaching the judge, and
  §23.2/§10.4 make the Auditor's value its independence, produced once. Add lower salvage value (a
  rejected audit is already gracefully absorbed; a lost proposal is the loop's core output) and
  ADR-067's precedent putting the burden on the extension — and the port argues against itself.

### The stale claim it surfaced (the one code change)

`auditor._parse`'s docstring asserted its strictness was "the same policy `deliberation` applies:
never repair a half-understood judgement." False as of ADR-069 — `deliberation` now repairs once.
The recurring claim-drift shape: a comment naming another module's behaviour a later slice changed,
with no test defending it. Inverted into the deliberate divergence ADR-070 records rather than
deleted. `content_audit._parse` carried no such claim.

### Verification

- **Nothing to verify behaviourally — the decision is to build nothing.** 1175 tests and the golden
  run stay green (docstring edit touches no code path); golden hash unchanged. The teeth are in the
  record, not a test.

- Next: Phase 2 proper — synthetic customers, marketplace, MAP-Elites, regime shifts, chaos drills.
  Phases 2 and 3 remain deliberately skipped, so the selection machinery is still unvalidated. The
  parse-repair arc (ADR-069/070) is now fully closed, follow-ups and all.
