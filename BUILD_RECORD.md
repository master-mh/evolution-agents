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
normalised cost, and the reply format a model can follow, 2026-07-21 through 2026-08-25):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-26 — Parse rate is maximised by the setting that destroys the colony

A measurement, and two refusals (ADR-050). **No code changed, no migration, no test added.**

ADR-049 left one item: at ~36% compliance the remaining gap was "a **model** decision, not a prompt
edit," and PRIORITIES carried it as *pull a bigger local model and re-measure*. Pulled `qwen2.5` (7B)
and measured three arms, n=16 each, fresh colony per run.

| arm | parsed | **distinct/wake** | median latency |
|---|---|---|---|
| `llama3.2` t=0.8 (control) | 7/16, replicated 7/16 | 0.25, replicated 0.19 | 11.3 / 12.4 s |
| `qwen2.5` t=0.8 | 14/16, replicated 13/16 | 0.12, replicated **0.56** | 162.5 / **38.1** s |
| `llama3.2` t=0.0 | **16/16** | **0.06** (1 reply × 16) | 6.3 s |
| `qwen2.5` t=0.0 | **0/16** | **0.00** (1 reply × 16) | 14.6 s |

Each t=0.8 arm measured twice. **Parse rates replicate; diversity figures do not** — see the
correction in ADR-050.

### The hypothesis was refuted, and so was its obvious replacement

- **`qwen2.5` wins on parse rate, and that replicates** — 14/16 then 13/16 against 7/16 twice,
  precisely ADR-049's failure class vanishing (flattened **0/16 vs 3/16**). **The case against it in
  the first draft of this entry did not survive re-measurement**: "14× slower" was 3× once the box
  was not thrashing, and "fewer distinct proposals" reversed outright. Both withdrawn; see ADR-050's
  correction. It is a live option, deferred behind the temperature question, not a rejected one.
- **Nobody had ever set the sampling temperature.** `providers.py` sends `num_predict` and nothing
  else, and neither model pins one, so every deliberation in this project's history — ADR-049's
  measurements included — ran at Ollama's default 0.8. At `temperature: 0` **both** models collapse to
  a single byte-identical reply per run (1 distinct `response_hash` per 8 calls), while §15.1's
  context of its own recent proposals grows (1522 → 1628 tokens) and changes nothing. **Which reply
  they collapse onto is arbitrary and decides the whole score:** `llama3.2` lands on a valid
  experiment (**16/16**), `qwen2.5` on an `abstain` the schema rejects (**0/16**). At t=0 a parse rate
  is one sample reported sixteen times.
- **So the finding is the metric, not the model.** Parse rate is maximised by a setting that deletes
  the colony's variation *and* does not reliably buy compliance — the same setting scores 16/16 on one
  model and 0/16 on another. Anything tuning compliance from here must report distinct proposals per
  wake beside the rate, and **must replicate the arm before concluding from it**: two of this slice's
  three conclusions came from single arms and both were wrong.
- **§14.1 forbids the one-line fix.** "temperature/sampling mutation" is listed as a prompt-mutation
  operator — sampling sits in the *mutable Cell* column, so pinning it in the kernel would delete a
  mutation dimension the spec enumerates. The socket is already reserved and already empty:
  `model_policy` is a §16.2 genome field, hashed to `cells.model_policy_hash`, **written at birth and
  read by nothing** — the fourteenth such socket.

### Verification

- **The control validates the scenario:** re-measured at 7/16 against ADR-049's recorded 20/56,
  Fisher one-sided p = 0.38 — not significantly different, so the arms read against that baseline.
- **The temperature override was teeth-checked** rather than trusted: asserted `temperature: 0.0`
  reaching the request payload, not just inferred from the changed result.
- **Sampling defaults ruled out as a confound** — `ollama show --parameters` sets no temperature on
  either model, so both t=0.8 arms sampled identically and the qwen2.5 gap is the model.
- **`qwen2.5`'s only two failures are a known schema objection**, reached independently by a stronger
  model: both `abstain` replies carrying `kind` + `rationale` alone. FUTURE_BUILD_HOOKS already logs
  `risk_tier`-on-abstain from `llama3.2` doing the same. Two models now decline to state a risk tier
  for declining to act — evidence the schema is wrong, not the models.
- **Zero USD_REAL moved in any arm.** `qwen2.5` was newly exercised through the priced path and its
  bare tag settled at zero; conservation OK per book, hash chains valid, breaker 0/100, A6 linkage
  complete. **1004 tests and the golden run still green** — nothing changed to break them.
- **The harness was lost to a wiped scratchpad for the second time**, and rebuilding it is what
  surfaced both errors — the rebuild ran fast enough to expose that the original latency was
  environmental. FUTURE_BUILD_HOOKS has logged "nothing measures parse compliance in CI" since
  ADR-049; that gap has now cost the harness twice and a published figure once.
- Next: **`temperature` as a genome field** (§14.1), carrying §14.2's counterfactual-twin obligation
  — the first real decision is whether sampling is inherited, mutated, or both. The `risk_tier`-on-
  abstain schema question is now well-evidenced and cheap — it is what `qwen2.5` deterministically
  converges to, 16/16 of its greedy output. The 2×2 is complete.
