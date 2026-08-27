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
measurement, §15.1 anchoring, the twins that
chose the fix, and the fix itself, 2026-07-21 through 2026-08-26):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-27 — The genome is not the constraint; it is what makes a proposal concrete at all

A measurement (ADR-056). **Hypothesis rejected. No code changed.** This closes ADR-052's third and
last candidate cause.

| arm | parsed | ideas (all) | **ideas@2** | **names a concrete deliverable** |
|---|---|---|---|---|
| `genome_tight` | 26/64 | **1.887** | 1.513 ± 0.111 | **26/26 (100%)** |
| `genome_loose` | 19/64 | 1.718 | 1.612 ± 0.165 | **1/19 (5%)** |

**Diversity: no effect** — +0.099, 65% of 48 pairwise comparisons, p = 0.207, and on the
all-proposals measure the *tight* genome scores higher.

### The pre-registered check is the finding

It was written into the script before the arm ran (the habit ADR-055 earned): a loose genome could
raise a diversity score by making proposals vaguer rather than more varied. It raised no score — and
concreteness collapsed anyway, **100% → 5%**, at nearly identical summary length (83 vs 87 chars).
The loose arm is not shorter, it is emptier: *"Refine our software to reduce routine back-office
work"*, *"Invest in customer support"*. One proposal asked to **"Send reminder about the upcoming
scheduled research cycle"** — a Cell with no market hypothesis proposing about its own scaffolding,
because that was the only concrete noun left in its context.

### So the genome has a second job nobody had written down

§16.3 makes the market hypothesis inheritable so a lineage stays that lineage. This measures the
other thing it does: **it is the only part of the context that tells a Cell what a proposal is
*about*.** Remove the specificity and the Cell still proposes, parses less often, and says nothing.

### The search for prompt-level causes is complete

| candidate (ADR-052) | verdict | effect |
|---|---|---|
| §15.1 anchoring | confirmed, **fixed** | **+86%** |
| identical wake reason | confirmed, remedy refused | +15% |
| genome pinning | **rejected** | none (p = 0.21) |

**The residual ~2 effective ideas per run of 8 is the model's ceiling on this hardware, not a defect
in the prompt.** Anything further is a model decision (ADR-050) or a §14 mutation-operator decision,
not a context-assembly one.

### Verification

- **Instrument checked**: the genome section is present in the prompt in both arms; the concreteness
  and length comparisons are computed over all proposals, not a sample.
- **1010 tests and the golden run green** — untouched.
- **A concreteness measure now exists and is worth keeping.** It separated two arms the diversity
  score could not tell apart, and it is the first metric here that asks whether a proposal is *worth*
  anything rather than whether it differs from its neighbour.
- Next: **Phase 2 warning recorded** — diversity and concreteness move independently, so selection
  tuned on variety alone would favour exactly the Cells that have stopped saying anything.
