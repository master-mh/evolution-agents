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

## 2026-08-27 — The wake reason matters, and rotating it makes a Cell act on things that never happened

A measurement and a refusal (ADR-055). **No code changed.**

ADR-052's second candidate cause: `Why you were woken` renders the wake reason verbatim, the
scheduler emits `scheduled research cycle` every time, so nothing in the prompt ever says the
situation changed. Two arms, **12 runs × 8 wakes each** — deepened from 4 after the first pass came
back at p = 0.11, the underpowered profile that produced four withdrawn claims earlier in this thread.

| arm | runs | parsed | **ideas@3** |
|---|---|---|---|
| `wake_same` (shipped) | 12 | 46/96 | **1.764 ± 0.220** |
| `wake_varied` | 12 | 38/96 | **2.025 ± 0.217** |

**+0.261, 80% of 100 pairwise comparisons, exact one-sided p = 0.0116.** Parse-rate difference not
significant (p = 0.31). **The hypothesis holds and is the smallest of the three** — anchoring was
+86%, this is +15%.

### The remedy this invites is dangerous, and the arm proved it

The experiment asserted reasons rather than earning them — no tool result had arrived, no capital had
been allocated. That was flagged in the script *before* it ran, which is why the output was checked
for it. **Three of 38 proposals in `wake_varied` responded to an event that never happened**, against
**zero of 46** in the control:

- *"Notify bookkeepers of an available tool result and request a review…"*
- *"Email notification about available tool results to bookkeeping community forums"*

The Cell was told a tool result was available, believed it, and proposed **contacting customers about
it**. With an approved `external_action` grant and §27.1 autonomy on, that is a real email about a
result that does not exist. **Part of the measured +15% is that failure**, so the effect size for
*honest* wake reasons is smaller than 0.261 and this measurement cannot say by how much.

### §0.3 from the other side

The clause says a Cell may explain a result and never define it. The mirror is that **the kernel must
not assert to a Cell something that is not so.** `Why you were woken` is `required=True` and never
dropped, so whatever it says is read every wake, and a Cell cannot tell a scheduler placeholder from
a real event.

### Verification

- **Deepened rather than reported.** The first pass read +0.355 at p = 0.11; deepening moved the
  estimate *down* and the confidence up. Acting on it would have overstated the effect and still
  landed on the dangerous remedy.
- **Instrument checked:** 8 distinct reasons reaching the prompt against 1.
- **The false-premise check was pre-registered in the script docstring**, not invented after seeing a
  number worth defending.
- **1010 tests and the golden run green** — untouched.
- Next: wire real events to the reasons they justify (`WAKE_TOOL_RESULT`, `WAKE_CAPITAL_ALLOCATION`
  and the rest are all defined; only the scheduler's tick is hardcoded). Argue it on correctness, not
  on the 15%. Then the last candidate cause: the genome pinning market/problem/product.
