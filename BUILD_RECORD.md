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
gate reading a resolved content audit, and model_policy's temperature socket,
2026-07-21 through 2026-09-03):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-03 — `risk_tier` is optional for exactly one kind: `abstain`

`proposal.py` + migration 0032 + `deliberation.py` + 8 new tests across three files + golden
35 -> 36 (ADR-068). **Two models independently produced the same failure shape on `abstain`
replies** — `qwen2.5` dropped `risk_tier` outright at t=0, `llama3.2` sent `"risk_tier": null` —
and PRIORITIES read it correctly: a stronger model reaching the same objection is evidence the
schema asked for something indefensible. §23.1 classifies *actions*; a Cell that proposes none has
nothing to classify.

### Two layers, each teeth-checked independently

`Proposal._risk_tier_matches_kind` (a `model_validator`, mirroring `_experiment_matches_kind`'s
shape) rejects a null `risk_tier` on every kind but `abstain` at parse time. Migration 0032 rebuilds
`proposals` with `CHECK (risk_tier IS NOT NULL OR kind = 'abstain')` — ADR-047's "unrepresentable,
not merely refused" applied again: a constraint with no layer belongs in the schema when the schema
can express it, binding every future caller regardless of whether it imports `proposal.py`.
Disabling either layer alone produces its own clean `DID NOT RAISE`/assertion failure, confirming
neither is redundant with the other.

### Scoped to exactly the defensible field

`qwen2.5`'s collapse dropped three fields, not one — `summary` and `estimated_cost_minor_units`
stay required. An abstaining Cell still has something to say, and its cost is trivially 0 (the
prompt already says so). Widening either would fix a different, unargued failure under cover of
this one.

### The "§23.1 implications" PRIORITIES flagged never materialised

`approval._enqueue_locked` already returns `None` for `kind == 'abstain'` before it ever reads
`risk_tier` — abstaining proposals have never reached the approval queue. The one place §23.1's
tier is read as a classification (`approval._assessed_tier`) is structurally unreachable for a row
that could carry NULL. `deliberation.py`'s two `.value` accesses were the only real call sites
needing a change.

### Verification

- **8 new tests across `test_prompt_shape.py` and `test_deliberation.py`; teeth-checked twice, once
  per layer.** Neutralising the Pydantic validator failed the parametrized "every other kind still
  requires a risk tier" test with a clean `DID NOT RAISE`. Dropping migration 0032's CHECK failed
  the schema-level `sqlite3.IntegrityError` test the same clean way.
- **1168 tests and the golden run green.** Golden expectations moved 35 -> 36: no scenario Cell
  ever proposes `abstain`, so the only diff is `input_tokens` shifting by a constant +30 on every
  deliberation-loop call — the rendered prompt hint describing the new exception is longer text,
  and `MockProvider`'s token estimate is a pure function of prompt length. `output_tokens`, cost,
  and every ledger balance are byte-identical.
- Next: a parse-repair retry (re-prompting with the validation error on an `UNPARSEABLE` reply) is
  the standard remedy still deliberately unbuilt — PRIORITIES flags it as worth arguing once the
  model question is settled, since a better model may make it unnecessary.
