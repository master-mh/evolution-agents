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

## 2026-08-27 — The +15% does not survive honesty

A measurement (correction to ADR-055). **No code changed.**

ADR-055 measured +15% diversity from varying the wake reason, flagged that part of it was the Cell
believing false premises, and said to argue the wiring "on correctness, not on the 15%". ADR-057
wired the one genuinely missing reason. This re-measures with reasons **earned**, wakes drained from
the inbox rather than set by hand.

| arm | parsed | **ideas@3** | reasons that drove deliberations |
|---|---|---|---|
| `unreviewed` | 31/64 | 1.802 ± 0.286 | 64 scheduled |
| `reviewed_flat` | 29/64 | **1.809 ± 0.213** | 64 scheduled (approvals happen, wake suppressed) |
| `reviewed_earned` | 31/64 | **1.827 ± 0.248** | 37 scheduled + **27 human decision** |

**`reviewed_flat` vs `reviewed_earned` is the experiment** — both approve everything, so the standing
strategy, grants and every other approval side-effect are constant and only the reason varies.
**+0.018 (+1%), higher in 41% of pairs, p = 0.73.** A null.

### What it retires, and what it does not claim

ADR-055's +15% was an artifact of rotation. Its own caveat — 3/38 proposals responding to events that
never happened — understated it: strip the falsehoods and essentially nothing remains.

**It does not show wake reasons cannot matter.** ADR-055 rotated *eight* reasons across eight wakes,
including ones a real colony rarely emits in sequence; a reviewed colony earns *two*. The honest
claim is **"at the variety a real colony actually produces, the effect is nil"** — a colony running
tools, allocations and audits would earn more, and this says nothing about that.

**ADR-057 was right to ship and right about why.** It was argued on §17.2 conformance and §25.2's
feedback loop, never on the number, and told the reader to expect less than +15%. It came back at
+1%. The instruction to argue it on correctness is now measured-correct rather than merely prudent.

### The self-repetition ledger closes harder

| candidate (ADR-052) | verdict | effect |
|---|---|---|
| §15.1 anchoring | confirmed, **fixed** | **+86%** |
| identical wake reason | confirmed by rotation, **~0% once honest** | +1% (p = 0.73) |
| genome pinning | rejected | none (p = 0.21) |

**Two of the three candidate causes were worth nothing once measured properly**, and the residual
~1.8–2.0 effective ideas per run of 8 is the model's ceiling.

### Verification

- **Instrument checked before the numbers counted:** 27 genuinely earned `human decision` wakes drove
  42% of `reviewed_earned`'s deliberations, while both controls stayed at 64 scheduled and zero.
- **The confound ADR-053 taught was designed out.** Comparing reviewed against unreviewed would have
  measured "does having an operator help" and reported it as "does the wake reason help";
  `reviewed_flat` exists to hold that constant.
- **1016 tests and the golden run green** — untouched.
- Next: nothing further on self-repetition from context assembly; the ground is measured. Open work
  is ADR-050's model question, §14's mutation operators, and Phase 2.
