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

| arm | parsed | distinct summaries | **distinct/wake** | median latency |
|---|---|---|---|---|
| `llama3.2` t=0.8 (control) | 7/16 | 4 | **0.25** | 11.3 s |
| `qwen2.5` t=0.8 | 14/16 | 2 | **0.12** | 162.5 s |
| `llama3.2` t=0.0 | **16/16** | **1** | **0.06** | 6.3 s |

### The hypothesis was refuted, and so was its obvious replacement

- **`qwen2.5` wins on parse rate and loses the thing that matters.** 14/16 vs 7/16 is real
  (Fisher p = 0.012) and it is precisely ADR-049's failure class vanishing — flattened **0/16 vs
  3/16**. But it is **14× slower** here (0.53 tok/s at 7% free memory; an 8 GB box pages per token)
  and produced **fewer distinct proposals than the 3B model it would replace**.
- **Nobody had ever set the sampling temperature.** `providers.py` sends `num_predict` and nothing
  else, and neither model pins one, so every deliberation in this project's history — ADR-049's
  measurements included — ran at Ollama's default 0.8. Forcing `temperature: 0` gave a **perfect
  16/16** and collapsed the Cell to **one proposal repeated eight times per run**, while §15.1's
  context of its own recent proposals grew (1522 → 1628 tokens) and changed nothing.
- **So the finding is the metric, not the model.** Parse rate is maximised by the setting that
  deletes the colony's variation. **100% parse at 0.06 distinct/wake is worse than 44% at 0.25.**
  Anything tuning compliance from here must report both numbers.
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
- **The harness was lost to a wiped scratchpad for the second time.** FUTURE_BUILD_HOOKS has logged
  "nothing measures parse compliance in CI" since ADR-049; that gap has now cost the harness twice.
- Next: **`temperature` as a genome field** (§14.1), carrying §14.2's counterfactual-twin obligation
  — the first real decision is whether sampling is inherited, mutated, or both. The `risk_tier`-on-
  abstain schema question is now well-evidenced and cheap. `qwen2.5` at t=0 is the one unmeasured
  cell of the 2×2.
