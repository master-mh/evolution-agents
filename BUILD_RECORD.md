# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, the experiment, experiment attribution,
proposed experiments, the strategy kind decided, the experiment_id foreign keys, and §13.1's
normalised cost, 2026-07-21 through 2026-08-25):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-25 — The reply format a model can actually follow

`proposal.KIND_PAYLOADS` + a rewritten `_prompt_schema` / `_payload_rule` + one guidance line
(ADR-049). No migration, and **no change to the parser** — `proposal.parse` stays strict.

ADR-048's live run found parse compliance had fallen from **7/8 (2026-08-06) to 1/8**; a controlled
re-measurement put it at **0/12**, every failure the same shape. Three conditional payloads have been
added to the schema since that 7/8, and **none of them had ever been shown to a model.** The suite
and the golden run stayed green the whole time, because `MockProvider`'s reply is an input rather
than a response to the prompt's wording — the same blind spot the 2026-08-06 enum bug was recorded
under, hit again somewhere new.

### Four renderings, each measured

1. **A payload is an object, not a sentence describing one.** `"experiment"` used to render as a
   long English string containing braces, so the model hoisted `hypothesis` to the top level.
2. **The skeleton is ordered, not sorted.** `sort_keys=True` put `experiment` and `external_action`
   *above* `kind` and `summary` — the model met two conditional payloads before the field that
   decides whether they apply. **This was the largest lever, worth more than the other three
   together.**
3. **Optional keys left the skeleton for the prose.** Shown as populated examples, `artifact` and
   `predictions` came back filled with empty strings. Hiding *everything* conditional was worse
   (0/12 — the model stopped emitting the payload its own kind required), so the split is
   sometimes-mandatory in the skeleton, almost-always-absent in prose.
4. **The prompt names no field the parser rejects.** A draft that said "you do not choose what stage
   it runs at" got back `"experiment": {"stage": "§25.1", "rung": "1"}`. **Naming a field is an
   invitation to emit it**, even while denying the Cell controls it.

### Verification

- **Measured 0/44 → 20/56 parseable** on `llama3.2`, same scenario, three runs per arm. Decomposed
  at n=16: all five required fields present **1 → 11**, payload correctly nested **0 → 10**,
  flattened **13 → 4**.
- **1004 tests passing** (16 new, 0 removed; up from 988). **Golden expectation 24 → 25**, two
  sections, **token counts only** — `proposals` and `deliberations` byte-identical, `balances`
  identical in every account in every book.
- **Teeth-checked nine ways.** Two of my own tests were weak and the teeth-check found both: one
  asserted a bare substring (`"artifact" in rule`) that the key's own description text satisfied,
  and one was parametrised over `KIND_PAYLOADS`, so deleting an entry deleted a case instead of
  failing one — **the suite went quieter rather than redder**. Replaced with a test that derives the
  pairing from the parser.
- **One plausible hypothesis measured and refuted.** `risk_tier` and `estimated_cost_minor_units`
  were the most-omitted fields, so moving them ahead of `summary`/`rationale` looked obviously right
  — a model that runs out of steam drops its tail. It took the rate from **7/20 to 0/20**. Reverted,
  and the order now carries a comment saying not to touch it without re-measuring.
- **This is a repair, not a restoration, and the honest reason matters.** ~36% is far below 7/8, and
  that baseline predates three conditional payloads. Replies now stop cleanly (`stop_reason: stop`,
  26–87 output tokens) and are simply incomplete — a 3B capability ceiling, not an ambiguity. Not
  truncation: checked.
- Next: the remaining gap is a **model** decision, not a prompt edit — a larger local model, or a
  paid one where compliance matters. A parse-repair retry is the standard third option and is
  deliberately unbuilt (§24.3, and it pays twice for a prompt bug). All three are in PRIORITIES.
