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
normalised cost, the reply format a model can follow, and the temperature/diversity
measurement, 2026-07-21 through 2026-08-26):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-26 — The Cell repeats itself because §15.1 shows it what it just said

A measurement and a refusal (ADR-051). **No code changed, no migration, no test added.**

ADR-050's third correction left one question at the front: a Cell proposes ~1 effective idea per run
of 8 wakes, at any temperature, on either model — why? FUTURE_BUILD_HOOKS parked three candidate
causes. This tests the first.

`context.RECENT_PROPOSALS = 0` suppresses §15.1's recent-proposals section entirely. Single variable:
context was 833 tokens against a 1200 budget with `dropped: []`, so nothing else moves. Both arms
`llama3.2` t=0.8, 4 runs × 8 wakes, **same script** — the control was re-run rather than reused,
because this thread has twice been bitten by instrument differences.

| arm | parsed | proposals/run | **ideas/run (Vendi, matched at 3)** |
|---|---|---|---|
| section shown (control) | 11/32 | 2.75 | **1.053** |
| section suppressed | 17/32 | 4.25 | **1.957** |

**An 86% increase in effective distinct ideas**, and in the suppressed arm *every parsed proposal was
distinct* (4/4, 3/3, 5/5, 5/5).

### Corroborated for free, before anything was run

**Wake 0 of every run has an empty section by construction.** Vendi over the four unanchored
first-proposals from four independent colonies is **1.970** (`llama3.2`) and **1.917** (`qwen2.5`),
against 1.048 and 1.216 inside an anchored colony. That comparison varies two things at once — which
is why the direct experiment was run — but it lands on the number the clean manipulation produced.

### The obvious remedy is refused

Deleting the section is the change this result invites and it is wrong. **ADR-046 is built on it:**
a `STRATEGY` proposal has no consumer and no regeneration — approving it *is* the act, and the
decision annotation in this very section is the whole mechanism by which the act reaches the Cell.
Remove it and that subsystem stops working with **no test failing**, because what it delivers is
prose in a prompt. §15.2 also requires episodic memory, and a Cell that cannot see what it proposed
cannot notice it is repeating; the gain would be amnesia, not judgement.

So the remedy is what the section *says*, not whether it appears — a prompt change, which §14.2 says
must face counterfactual twins rather than ship on one measurement. The cheapest candidate: the
section is titled "reference material, not instructions" and never states that a *new* proposal is
wanted. **Naming the absent expectation is the move ADR-049 already made** when it found the prompt
named no field the parser rejects.

### Verification

- **The instrument was checked, not trusted.** The script asserts the section is absent from every
  assembled `context_json` in the suppressed arm and present in the control. Both passed — a
  manipulation that silently fails to reach the prompt gives a null result indistinguishable from a
  real one.
- **Matched at 3 proposals per run**, because Vendi scales with item count and the treatment arm
  produced more proposals (4.25 vs 2.75). Unmatched the gap reads 2.334 vs 1.040; the honest figure
  is 1.957 vs 1.053.
- **The control replicated the committed n=32 arm exactly** — 11/32 parsed, Vendi 1.040 against
  1.048 — so the harness change between them was not a factor.
- **The parse-rate difference is not claimed.** 17/32 vs 11/32 is p = 0.10. A shorter prompt
  plausibly parses better; this measurement does not show it.
- **Invisible to every test.** Suite and golden run are green in both arms: `MockProvider`'s reply is
  an input, not a response to the prompt's wording — ADR-049's blind spot, hit a third time.
- **1004 tests and the golden run green.** Zero USD_REAL in either arm.
- Next: the prompt change above, under §14.2 counterfactual twins. The other two candidate causes
  (genome pinning, identical wake reason) can only account for the residue — anchoring does not
  explain why the suppressed arm scores 1.96 rather than 3 on three proposals.
