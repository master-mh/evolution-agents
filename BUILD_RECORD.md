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

Final figures, **n=32 per arm** (4 runs × 8):

| arm | parsed | per-run parsed | distinct **/wake** | distinct **/parsed** | median latency |
|---|---|---|---|---|---|
| `llama3.2` t=0.8 | 11/32 | [3, 3, 4, 1] | 0.156 | **0.455** | 9.0 s |
| `llama3.2` t=0.0 | **32/32** | [8, 8, 8, 8] | 0.125 | **0.125** | 10.8 s |
| `qwen2.5` t=0.8 | **22/32** | [6, 7, 6, 3] | **0.344** | **0.500** | 37.5 s |
| `qwen2.5` t=0.0 | **0/32** | [0, 0, 0, 0] | 0.000 | 0.000 | 15.4 s |

**Two diversity columns, because they disagree.** `distinct/wake` divides by wakes, charging a model
for replies that never parsed — and t=0 parses everything, so the temperature effect nearly vanishes
on it (0.156 vs 0.125). `distinct/parsed` conditions on producing a proposal: **3.6× (0.455 vs
0.125)**. ADR-050 originally published the confounded column alone.

### The hypothesis was refuted, and so was its obvious replacement

- **`qwen2.5` wins on parse rate and it replicates** — **22/32 vs 11/32** at n=32 (p = 0.0059),
  precisely ADR-049's failure class vanishing (flattened 0/16 vs 3/16). **The case against it in the
  first draft of this entry did not survive re-measurement**: "14× slower" was ~3.7× once the box was
  not thrashing, and "fewer distinct proposals" reversed outright — at n=32 `qwen2.5` is *more*
  diverse on both columns. It is now the better model on every axis measured except latency; a live
  option deferred behind the temperature question, not a rejected one.
- **Nobody had ever set the sampling temperature.** `providers.py` sends `num_predict` and nothing
  else, and neither model pins one, so every deliberation in this project's history — ADR-049's
  measurements included — ran at Ollama's default 0.8. At `temperature: 0` **both** models collapse to
  **one distinct proposal per run of 8** (`[1,1,1,1]` across four runs, both models). **Which proposal
  they collapse onto is arbitrary and decides the whole score:** `llama3.2` lands on a valid
  experiment (**32/32**), `qwen2.5` on an `abstain` the schema rejects (**0/32**).
- **The two t=0 failures are mechanically different, and only one is repetition.** `llama3.2` emits
  **4 distinct replies per run** — its prompt grows as proposals accrete (1522 → 1628, identically in
  all four runs) and greedy decoding on a changed prompt changes the text, yet the proposal never
  moves. **The context moved four times and the Cell did not.** `qwen2.5` emits **1 byte-identical
  reply per run**, and that is *caused by* its 0% parse rate: nothing parses → no proposal recorded →
  §15.1's recent-proposals section stays empty → prompt frozen at 1537 tokens → same reply forever.
  **A deterministic dead loop**, which the colony cannot think its way out of.
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
- **Three published claims withdrawn across two corrections, and sample size caught none of them.**
  "14× slower" was a thrashing box; "fewer distinct proposals" was a metric that charges a model for
  replies that never parsed; "byte-identical on all four t=0 runs" was a check that had only ever run
  against one of the two models, the other's data having been wiped. Re-running at n=32 confirmed the
  headline and changed nothing about it — **every real error needed a second angle, not more
  samples.** FUTURE_BUILD_HOOKS has logged "nothing measures parse compliance in CI" since ADR-049;
  that gap has now cost the harness twice and three published figures once each.
- Next: **`temperature` as a genome field** (§14.1), carrying §14.2's counterfactual-twin obligation
  — the first real decision is whether sampling is inherited, mutated, or both. The `risk_tier`-on-
  abstain schema question is now well-evidenced and cheap — it is what `qwen2.5` deterministically
  converges to, 16/16 of its greedy output. The 2×2 is complete.
