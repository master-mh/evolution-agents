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

## 2026-08-27 — Showing a rejected proposal's wording causes the §23.4 repeat it was meant to prevent

A measurement (ADR-054). **No code changed — the rule shipped hours earlier is confirmed by the
experiment queued to challenge it.**

ADR-053 hid the proposal-log summary for every status and left one known cost: a rejected proposal
loses its subject. Every other kind keeps a channel (approval's substance arrives on grant
consumption); a rejection has none. Restoring the wording for rejections only was the obvious remedy,
pinned by a test rather than shipped. Two predictions genuinely diverged — anchoring (the Cell copies
what it sees) versus learning (`REJECTED` steers it away) — so it needed an arm.

### The instrument was already in the kernel

§23.4's `repeat_after_rejection` compares normalised summaries and persists to `approval_signals`. It
answers the question directly, with no metric of mine standing between it and the answer.

| arm | parsed | ideas@3 | **§23.4 repeats fired** |
|---|---|---|---|
| `reject_shown` (wording restored) | 20/32 | **1.210** | **12** |
| `reject_hidden` (shipped rule) | 13/32 | **1.922** | **0** |

`reject_hidden` wins on diversity in **100% of 12 pairwise comparisons**.

### The remedy causes the failure it was meant to prevent

Twelve `repeat_after_rejection` signals against zero. **A Cell shown the wording of a proposal a
person just rejected proposes it again** — the feature intended to teach it what not to repeat is
what makes it repeat. `REJECTED` is not read as a negative instruction any more than `APPROVED` was
read as a positive one (ADR-053): **the label is not a modifier on the text beside it**, now measured
twice from opposite signs.

So the lost subject is the *price* of the rule, not a debt to repay.
`test_a_rejected_proposal_loses_its_subject_and_that_is_recorded` stays as the written-down cost, and
this entry is why it is not a TODO.

### Verification

- **Instrument checked before the numbers counted:** 20 and 13 rejections made, run-0 statuses all
  `rejected` in both, section medians **76 vs 36 tokens** confirming wording present and withheld.
- **Parse rate rose while the colony got worse** — 20/32 against 13/32. A Cell re-proposing a
  known-good shape parses more easily. **The clearest instance yet of ADR-050's theme:** anything
  tuning on parse rate alone would have chosen the arm that breaks §23.4.
- **1010 tests and the golden run green** — untouched, which is the point: this is a live-only
  property that no replay can see.
- Next: §15.1's remaining candidate causes for self-repetition — the genome pinning
  market/problem/product, and the identical wake reason on every wake. Anchoring is now fixed and the
  colony sits at ~2.1 effective ideas per run of 8; those two are what stands between that and 3.
