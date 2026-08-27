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
and the +15% that did not survive honesty, 2026-07-21 through 2026-08-27):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-27 — The concreteness measure is §13.4, and the instrument had never been measured

`scripts/concreteness.py` + a labelled fixture + `scripts/genomes/loose.json` + `--genome` on the
arm harness + `tests/test_analysis_boundary.py` (3 tests). **No kernel change, no migration**
(ADR-058).

PRIORITIES asked for ADR-056's concreteness measure as the Phase 2 counterweight to selecting on
variety alone, noting it "is not yet anywhere in the repo". It never had been: it lived in a scratch
script and was gone by the next session — *the day after* `scripts/` was created to stop exactly
that.

### The spec had named it, and this repo never had

> **§13.4** Flag ideas where only the industry label changed, ordinary freelancing is described
> exotically, the same mechanism is renamed, or **no new capability/transaction structure exists**.
> **§13.5** LLMs are skilled at producing rhetorically novel but structurally ordinary ideas.

§13.5 is ADR-056's finding written down before any of it was measured. **§13.4 appears nowhere in
PRIORITIES, FUTURE_BUILD_HOOKS or DECISIONS before this slice** — the sixteenth reserved socket, and
the first found by reading a *justification* clause rather than a mechanism clause. It also settles
the Phase 2 warning in the spec's vocabulary: §12.1 makes `novelty distance` a MAP-Elites
*descriptor*, and §13.4 is what stops a Cell cheating it.

### The instrument was measured before its numbers were read

The judge is asked to **quote** the words naming a specific thing, and the verdict is then decided
deterministically — every content word of the quote must really be in the summary (§24.3:
"verification → deterministic tools first, model second"). It may not be the generator's family
(§24.3), which the script enforces by reading `model_calls.requested_model` and refusing.

| rubric | agreement (24 labelled) | missed a real deliverable | invented one |
|---|---|---|---|
| first draft | 18/24 | 6/9 | 0 |
| shipped | **19/24** | **5/9** | **0** |

**Every error is one-directional**, and safely so: an arm with no objects has none to miss, so the
bias understates a gap and never manufactures one. `--selftest` therefore gates on **false
positives, not agreement** — gating on agreement would gate on a number in the same file, this
repo's recurring way of writing a test that passes for the wrong reason.

### The replication

| arm | parsed | **names a deliverable** | ideas@2 |
|---|---|---|---|
| `genome_tight` | 36/64 | **13/36 = 36%** | 1.524 ± 0.056 |
| `genome_loose` | 14/64 | **0/14 = 0%** | 1.467 ± 0.065 |

**Fisher exact one-sided p = 0.0065.** Not one of the loose arm's fourteen proposals named a single
object of its own business in eight independent runs. **ADR-056's diversity null replicates** (1.524
vs 1.467 at matched n, against its 1.513 vs 1.612) — diversity and concreteness still move
independently.

**ADR-056's 100% vs 5% does not replicate and cannot**: the rubric that produced it was lost with
its script, so the two are not measurements of one quantity. The direction, the completeness of the
separation and the independence from diversity are what was load-bearing, and all three hold. An
absolute rate from a lost instrument is not a result.

### Verification

- **Teeth-checked six ways.** Three mutations of the deterministic verifier (`all`→`any`, stopwords
  unstripped, empty quote counted as present) each failed the case written for it; three of the
  boundary tests (a scorer importing the kernel, `deliberation` importing the scorer
  function-locally, the scripts directory vanishing so the guard forbids an empty set) each failed
  the named test. One vacuity case was rewritten after the first teeth-check MISSED — the original
  gave the same answer with and without the bug.
- **1019 tests and the golden run green**, hash unchanged: nothing under `src/` was touched.
- Next: the counterweight exists; the **selector that consumes it** does not. §13.2 says hard gates
  then a Pareto frontier, never a single weighted scalar. Otherwise open: ADR-050's model question
  and §14's mutation operators.
