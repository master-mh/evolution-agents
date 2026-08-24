# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, and scheduler liveness,
2026-07-21 through 2026-08-24):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-24 — The experiment: seven sections reference it, none defines it

`experiments.py` + migration 0026 + four CLI verbs (ADR-043). The largest socket cluster in the
repo, and unusually most of it was **live plumbing rather than dead columns**: `experiment_id` has
been threaded through `gateway`, `prediction` and `ledger` for months, `reservations.settle` has
been propagating it onto ledger entries all along, and `mitosis predict --experiment <id>` accepted
any string and validated nothing. The foreign key was exposed to the operator before the table
existed.

### §2.6 defines the report, and the clause above it decides the design

There is no §Experiments. What §2.6 does define is *"synthetic revenue/profit, real cash consumed,
resource consumption, shadow cost, human labour, and a reality-gap estimate"* — six dimensions, so
§10.2 and §13.2's "do not rely on a single weighted scalar" are satisfied by the definition rather
than by a preference.

**§2.5, immediately above it, is "Balances are derived."** Read as neighbours, an experiment report
is a derived view and not a stored row. So there is **no `experiment_results` table**, despite §31
listing one — §31 offers "suggested entities" and does not mark that one Phase 1, and a stored
outcome is exactly where §0.3 leaks back in. The surest way to keep "a Cell may explain a result and
never define one" true is to give it no column to write, which is how `proposal.py` earns its shape.
`test_there_is_no_experiment_results_table` defends the refusal.

### The stage question had three witnesses and they agreed

§10.5's coroner lists `stage_reached` (singular) beside `experiment_ids` (plural); §27.2's dashboard
pairs them as one Cell field, "current experiment/stage"; and §13.1's `normalised_cost = expected
experiment cost / current stage tranche` would be circular if the stage belonged to the experiment.
**So §25.1's nine rungs are the only ladder** and Phase 2's "stage gates" are the gates between
them — no second ladder, no stages table. `stage_reached` derives from the highest rung a Cell was
funded at *or* ran at, because a Cell that did rung-1 simulator work and was never promoted has
still reached rung 1.

### Found while building: a slot that leaks on every death

§9.2 caps *simultaneous* experiments colony-wide, and death is routine. A Cell that died mid-
experiment left it `running` forever, so a colony killing Cells faster than it concludes experiments
would ratchet to its cap and refuse every new one with nothing anywhere explaining the refusals —
the "a claim held before acting is a lock and nothing sweeps it" shape ADR-036 logged for channel
claims. The seam now **settles before it reports**, and the experiment is **abandoned, never
concluded**: it reached no answer, and a coroner report listing a running experiment on a dead Cell
would be a false statement rather than a thin one.

The seam itself is `lifecycle.CoronerEnricher` — `lifecycle` sits below `experiments`, so §10.5's
two fields arrive by injection rather than a back-edge, the shape `population.Displacer` established.

**§9.2's cap is a third refusal shape.** ADR-031 separated durable carrying capacity (which
justifies displacement) from a temporary birth rate (which a clock clears); this slot frees when an
experiment *concludes*. `ExperimentCapacityError` sits deliberately outside `PopulationError` so it
cannot be caught as either, because both would suggest the wrong remedy.

### Verification

- **916 tests passing** (29 new, 0 removed; up from 887). **Golden expectation 19 → 20**, with
  **`balances` identical in every account in every book** — an experiment is a record and a
  derivation, and the revenue it now names was already being posted. The snapshot pins each
  experiment's §2.6 figures *derived on the spot*, so a kernel that started caching an outcome would
  have to keep them identical. `coroner_reports.stage_reached` moves from `null` — which it has been
  since migration 0007 — to `"rung 7: tiny capped live experiment"`.
- **Teeth-checked sixteen ways**, each failing its named test: the report ignoring the ledger,
  revenue read off the cash leg, an unmeasurable dimension reported as 0, the §9.2 cap unchecked
  (the state before this slice), that error folded into the population hierarchy, concluded
  experiments still counting, §15.1's singular ignored, `stage_reached` from promotions alone, the
  coroner seam never consulted, the seam made mandatory, the seam overwriting an explicit stage,
  death not releasing the slot, death concluding rather than abandoning, `death.py` no longer
  enriching, a rung off the ladder accepted, and unresolved forecasts folded into the reality-gap
  mean.
- **Hand-verified end to end on a live colony**: experiment started at rung 1, §15.1's one-at-a-time
  refused, rung 12 refused, 12.50 USD_SIM of revenue derived into the report, concluded and the slot
  freed, then a second experiment at rung 7 abandoned by its Cell's death with the coroner carrying
  `rung 7: tiny capped live experiment` and both experiment ids.
- Two gaps the live run surfaced: `record-revenue` had no `--experiment` flag despite the function
  taking one (fixed), and re-recording revenue to attach an experiment is **correctly refused by
  idempotency** — which means an operator who attributes revenue late cannot fix it, and §3.6 says
  the remedy is an adjustment rather than an edit. Logged, not built.
- **A snapshot-hygiene fix rode along**: a prediction's free-text claim embeds its approval request
  id, so a section about *calibration* was pinning an identifier into the hash. Seeded ids are
  reproducible only for a fixed sequence of allocations, so this slice minting one id earlier
  produced a spurious diff. ADR-017 excludes volatile ids; this was one wearing a sentence as a
  disguise, and it is now scrubbed.
- Next: `resource_usage.experiment_id` is the obvious next socket — it is the one column standing
  between §2.6's report and its last two dimensions.
