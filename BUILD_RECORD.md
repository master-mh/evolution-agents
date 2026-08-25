# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, the experiment, experiment attribution, and proposed experiments,
2026-07-21 through 2026-08-24):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-26 — The kind that needed no consumer, and the wake that told a Cell to redo what worked

`proposal.STATEMENT_KINDS` + two context sections + one refusal in `expire_grants_due` (ADR-046).
No migration. `ProposalKind.STRATEGY` was the last kind whose approval led nowhere, and the obvious
reading — that it needed a consumer like the other four — is wrong. **A strategy names nothing to
do, so approving one *is* the act.** What it lacked was a consequence, and the absence had produced
a live bug.

### Two failures, both reproduced on a live colony before the fix

1. **An approved strategy reached the Cell nowhere.** `_recent_proposals_section` showed `kind` and
   `summary` and nothing about what any person decided, so approved, rejected, expired and
   never-reviewed all rendered identically. For every other kind the *effect* was feedback enough —
   a tool result appears, a balance moves, an experiment starts — which is exactly why the gap only
   became visible on the one kind that has no effect.
2. **Its inert grant lapsed and woke the Cell to re-propose it.** `expire_grants_due` regenerates
   every unconsumed grant, and nothing can ever consume a strategy's. So the colony's response to
   "a person agreed with you" was, eventually, "redo that" — the exact opposite of the feedback the
   Cell needed, and the loudest evidence the kind was never finished.

### §23.3 says *actions*

"Expired actions are regenerated and re-evaluated." A strategy names no action, so
`proposal.STATEMENT_KINDS` is where "this kind has no consumer" is now written down rather than
left as the absence that made it look unfinished for four months. The grant still expires — it
lapsed, and §3.6's habit is that history is not rewritten — but nothing is woken.

### §15.1's last unimplemented source

The standing strategy is the Cell's most recently **approved** strategy proposal, derived from the
queue and stored nowhere (§2.5's habit outside the ledger). That fills "relevant epigenetic state",
the one context source §15.1 names which nothing implemented. §0.3 still holds — it is the Cell's
own words, labelled as such — and what distinguishes it from the untrusted proposal log is not that
the colony believes it but that **a person read that exact text and agreed to it**. The operator's
`decision_reason` rides along: the only human-authored text a Cell ever receives, and the most
direct steering the design offers.

**Telling a Cell it was rejected is safe only because §23.4's detector already exists.** §23.5 says
the queue "will be optimised against", and re-asking for a rejected thing is the specific
optimisation this feedback invites — `SIGNAL_REPEAT_AFTER_REJECTION` has been watching for it since
ADR-027, normalised so re-punctuating a rejected ask does not launder it. Had it not existed, this
half would have had to wait.

### Verification

- **962 tests passing** (13 new, 0 removed; up from 949). **Golden expectation 22 → 23** with
  **`balances` identical in every account in every book** — approving a statement moves nothing.
  The scenario's only `strategy` proposal had **no approval request at all** (step 17 deliberated
  without a queue sink), so the one kind whose entire meaning is the decision was the one kind no
  replay ever had a decision for. `approval_grants.expired` moves 4 → 5 **while `regenerated` stays
  4** — the whole §23.3 change in two integers.
- **Teeth-checked ten ways**, each failing its named test: the statement's grant regenerating again
  (the original bug), *no* grant regenerating (the over-fix, which the first test alone would have
  passed against), the standing strategy keyed on the grant so a lapse revokes it, a pending
  strategy standing, the earliest standing instead of the latest, any approved kind becoming the
  standing strategy, the operator's reason dropped, `expired` collapsed into "not reviewed", the
  verdict shown without its reason, and a kind with a consumer called a statement.
- **Hand-verified end to end on a live colony**: a Cell proposed a strategy and it was approved with
  "stay off paid advertising"; a spend request was rejected with a reason; a third sat pending. All
  three render distinctly in the Cell's next context, the standing strategy carries the operator's
  words, and the lapsing grant enqueued **zero** wakes while leaving the strategy standing.
- **One near-miss worth recording**: the golden run showed a strategy request assessed HIGH against
  a claimed LOW with *no* `understated_risk` signal, which looked like a broken detector. It is
  correct — `_assessed_tier` folds §16.2's genome `risk_class`, and that Cell's genome declares
  HIGH. The Cell understated nothing relative to the kernel's tier; its inheritance raised it.
- Next: `ProposalKind` is now fully decided — four consumers, one statement, one never queued. The
  open ground is §13.1's `normalised_cost`, which still has no stage tranche to divide by.
