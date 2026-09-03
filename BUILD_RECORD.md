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
Auditor path for §13.3/§13.4's content judgments, and the software_native_advantage
gate reading a resolved content audit,
2026-07-21 through 2026-09-03):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-03 — `model_policy`'s temperature socket is filled

`genome.py` + `providers.py` + `deliberation.py` + `gateway.py` + 11 new tests across five files +
golden run unchanged (ADR-067). **§16.2's reserved socket — `model_policy`, written at birth and
read by nothing since ADR-050 named it — now carries a validated `{"temperature": 0.0-1.0}`, read
into every deliberation wake from the Cell's own genome, never a kernel constant.**

### The "inherited, mutated, or both" question was already answered

`model_policy` already sat in `INHERITABLE_FIELDS`, flowing through `inherit()`'s overlay like every
other genome field — a child keeps its parent's policy unless a mutation overrides it, which is both
inheritance and mutability at once, with no new mechanism built. What actually needed a decision was
the field's *content* shape, which had none: any JSON-serializable value passed before this slice,
including the free-text string one pre-existing test used as a stand-in
(`test_a_model_policy_change_is_not_a_new_idea`, now a dict). `MODEL_POLICY_FIELDS` closes it the
same way the top-level genome schema is closed — an unknown key is refused by name, because §14.1
names two more mutation operators (model-route, reasoning-budget) that could occupy this socket
later.

### Bounded to `[0.0, 1.0]` — the tighter of two providers' ranges, not their union

Anthropic hard-limits `temperature` to `[0.0, 1.0]`; Ollama accepts wider. Validating against the
tighter range is what §14.2's "counterfactual twins... differing by one prompt-level change" needs —
a value valid on one provider and rejected outright by the other would make a cross-provider
comparison undefined. The bound is enforced twice: once in `genome.py`, again at the
`providers.ModelRequest` pydantic field, so a bad value can never reach a provider regardless of
which caller built the request.

### `None` means "no opinion" and is never conflated with 0, end to end

A silent genome reports `temperature_of() is None`; `providers.py` omits the key entirely rather
than sending `temperature: null`; `gateway.py`'s new `model_calls.parameters_json` entry does the
same. This is not cosmetic — ADR-050 measured that temperature 0 (greedy decoding) collapses a
colony to one repeated idea per run, the worst outcome the earlier measurement found. Reading
absence as 0 anywhere in this chain would have silently reproduced exactly that failure mode.

### Scope: `deliberation.py` only

`auditor.py`, `content_audit.py`, and `cli.py`'s `call-model` still send no temperature. ADR-050's
argument is specifically about the agent loop's parse-rate/diversity trade-off; Auditor and
content-audit calls are operator-composed §10.4 judgments with the model already chosen by the
caller. Whether an Auditor's own genome should set its own sampling temperature is a real,
unargued question — logged in FUTURE_BUILD_HOOKS rather than bundled in here.

### Verification

- **11 new tests across `test_genome.py`, `test_providers.py`, `test_ollama_provider.py`,
  `test_gateway.py`, `test_deliberation.py`; teeth-checked twice.** Reverting
  `deliberation.py`'s wiring to `temperature=None` failed the end-to-end wake test with the exact
  expected assertion (`None == 0.3` where `0.3` was expected). Reverting `gateway.py`'s conditional
  `parameters["temperature"]` line failed the parameters test the same clean way. Both are real
  MISSes, not false CAUGHTs.
- **1157 tests and the golden run green, hash unchanged.** No scenario Cell declares a
  `model_policy`, so `parameters_json` stays `{"max_tokens": ...}` everywhere in the replay —
  absence stayed absent through the whole chain, exactly as designed.
- Next: `risk_tier` on `abstain` — PRIORITIES' next `Next` item, cheap and well-evidenced by two
  models independently refusing to state a risk tier for declining to act.
