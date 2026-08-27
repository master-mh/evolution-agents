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
the +15% that did not survive honesty, and §13.4's concreteness measure,
2026-07-21 through 2026-08-27):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-27 — §13.2's selector: four of its nine dimensions have no data

`selection.py` + 21 tests + `mitosis frontier` + golden expectations **28 -> 29** (ADR-059).
**No migration.** `promotion.transfer_degradation` made public; `UNINFORMATIVE_BRIER` moved to
`prediction.py`.

PRIORITIES asked for the selector that consumes ADR-058's concreteness measure. §13.2 says what one
is: *"Reject candidates below minimum thresholds on evidence quality, reproducibility, policy
compliance, and software-native advantage; then select from a Pareto frontier over structural
novelty, information gain, economic potential, experiment cost, and transfer robustness. Do not rely
on a single weighted scalar."*

### Five of the nine are measurable here; four abstain

| live | unmeasurable, and why |
|---|---|
| evidence quality (§8.5, bar = `UNINFORMATIVE_BRIER`) | reproducibility — §11.2's adoption record |
| policy compliance (§18 quarantine, §23.4 signals) | software-native advantage — §13.3 judges *content* |
| information gain (entropy of the filed forecasts) | structural novelty — §31's `novelty_archive` |
| experiment cost (§13.1's first consumer) | economic potential — no proper scoring rule over it |
| transfer robustness (§25.2's degradation) | |

**An unmeasurable dimension abstains and never scores zero** — `structural_novelty = 0.0` is a claim
about the idea; `None` is the truth. `UNEVALUABLE` (a new Cell) and `UNMEASURABLE` (no data anywhere)
stay separate for the reason §25.2 splits `INSUFFICIENT_EVIDENCE` from `EVIDENCE_WITHHELD`.

### Why one self-reported number is safe and another is not

`information_gain` comes from the Cell's own forecasts, and §8.5 is what makes that admissible:
**Brier is a proper scoring rule**, so overstating uncertainty loses points at resolution and the
register is hash-chained before the outcome is knowable. `economic_potential` has no such rule, so
§0.3 stands and the module declines. **That contrast is what "no single weighted scalar" protects** —
the axes hold each other honest only while they are separate.

The exception is named rather than hidden: `experiment_cost`'s numerator is the Cell's own estimate,
and nothing yet compares it with what the experiment consumed.

### ADR-058's concreteness measure is not wired in, and that is the finding

Concreteness judges an idea's *content*, which is §13.3's category — and §13.2 puts that behind a
human or an independent Auditor. The kernel is excluded by §23.5 and by the AST boundary this repo
added one slice ago. **So concreteness enters §13.2 as `software_native_advantage`'s missing judge,
not as an axis.** The shape of the gap is now written down instead of assumed.

### Verification

- **Teeth-checked nine ways** — sign flip, gates not removing, frontier over rejected candidates,
  unmeasured rejected instead of unevaluable, three abstain-becomes-zero mutations,
  `understated_risk` escalating, and domination reading an unmeasured axis as zero. Each failed the
  test written for it.
- **An existing guard caught a real mistake.** `test_no_kernel_path_acts_on_an_assessment` failed the
  moment `selection` imported `outcome` for two constants, and it was right to — a selector that can
  see a §25.2 verdict is one edit from acting on it. `UNINFORMATIVE_BRIER` moved to the scoring rule
  that defines it; the count threshold became this module's own number.
- **The golden section would have been born dead** — every grant the scenario made was consumed by
  the step that made it, the shape ADR-045 found here once already. Step 19f leaves one approved,
  unallocated candidate, from the Cell with a rung-7 promotion so `experiment_cost` resolves to 0.4
  rather than abstaining. **`assessments.forecasts_made_while_funded` moves 0 -> 2 with the verdict
  unchanged** — §23.5's exclusion demonstrated for the first time.
- **1040 tests green; USD_REAL and USD_SIM identical in every account.** Only RESOURCE moved, by 2
  minor units of metering for a mock call priced at zero.
- Next: three axes is a frontier, not quality-diversity. §31's `novelty_archive` and
  `behavioural_descriptors`, §11.2's adoption record, and an Auditor path for content judgments —
  in that order, since the archive also unblocks §13.4's other three flags.
