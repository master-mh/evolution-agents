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
measurement, and §15.1 anchoring, 2026-07-21 through 2026-08-26):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-26 — The Cell copies what it can see, and cannot be instructed out of it

§14.2 counterfactual twins on §15.1's recent-proposals section (ADR-052). **No code changed** — the
recommendation moves the golden run, which Amendment A12 makes a separate reviewed act.

ADR-051 confirmed the section anchors the Cell and parked three candidate rewordings. Each is one
edit relative to control; all `llama3.2` t=0.8, same genome, one batch, Vendi matched at 3 proposals
per run. `control` and `nosummary` deepened to 12 runs once the first pass named them the pair that
mattered.

| arm | one-line edit | runs | parsed | **ideas@3** |
|---|---|---|---|---|
| `control` | as shipped | 12 | 52/96 | **1.089 ± 0.147** |
| `heading` | heading names the expectation | 4 | 15/32 | **1.054 ± 0.078** |
| `exclusion` | each entry marked "do not propose again" | 4 | 12/32 | **1.202 ± 0.176** |
| `nosummary` | body drops the summary, keeps kind + decision | 12 | 40/96 | **1.852 ± 0.248** |
| `suppressed` | section absent (ADR-051's ceiling) | 4 | 20/32 | 1.939 ± 0.138 |

`nosummary` beats `control` in **89 of 90 pairwise run comparisons** and recovers **95% of the
suppression ceiling** with the section still rendering.

### ADR-051 predicted the wrong winner, and the reason generalises

ADR-051 nominated the heading edit, reasoning from ADR-049 that naming an absent expectation makes a
model meet it. **It measured at zero** (1.054 vs 1.089). An explicit per-entry "do not propose again"
bought 15%. Removing the copyable text bought everything. **The Cell is not disobeying an instruction
to vary — it is completing a pattern it can see**, and an instruction aimed at a copying behaviour
does not reach it. Assume that for the next prompt-driven behaviour someone tries to fix with a
sentence.

### The recommendation is narrower than the arm that won

**All 52 control proposals are `pending`** — zero approved, zero rejected, because an unattended
colony queues and nobody reviews. So ADR-046's channel carried nothing in any arm, and `nosummary`
cost it nothing *only because it was never exercised*. That is also why `nosummary` sits so close to
`suppressed`: with everything pending its body reduces to `- [experiment] -> waiting on a person`.

So the two goals are **separable, not in tension**: the summaries doing the anchoring are on entries
that convey no decision. Hide the summary for `pending`/`not reviewed` and keep it for
`approved`/`rejected` — identical to `nosummary` in the measured regime, so it inherits the full
gain, while ADR-046 keeps exactly what it needs.

### Verification

- **Instrument checked with something that can fail.** The first check grepped `context_json` for
  body text, but `Section.to_record()` stores only name, tokens and `required` — it could never pass,
  and reported BROKEN against manipulations that were correct. Replaced with token counts: control's
  section median **81 tokens**, `nosummary`'s **21**, both present. Variants also verified by
  rendering them directly.
- **A missing `__main__` guard cost the control arm.** Importing the experiment script to inspect its
  variants re-ran the batch and overwrote four databases mid-flight — caught from an mtime later than
  the arm that ran after it. Guard added, control re-run from scratch, and the other four arms
  verified intact at 32/32 before use.
- **The parse-rate difference is not claimed**: 40/96 vs 52/96 is p = 0.11.
- **1004 tests and the golden run green.** Zero USD_REAL in any arm.
- Next: implement the pending-only variant (a golden-run expectation bump under A12), and an arm that
  **actually approves proposals mid-run** — nothing here shows whether a Cell anchors to an *approved*
  summary too, which is the one result that would put ADR-046 and diversity back in real conflict.
