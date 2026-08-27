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

## 2026-08-27 — The proposal log shows no wording at all

`context._was_decided` deleted, the section heading corrected, 6 tests, golden expectation
**26 -> 27** (ADR-053). No migration.

§15.1's proposal log now renders `- [kind]\n    -> note` for every status. ADR-053 measured that an
approved summary anchors exactly as hard as a pending one (1.122 shown vs 1.764 hidden, approvals
held constant), so the status-conditional gate ADR-052 shipped was guarding the wrong thing.

**Confirmed live at 2.122 effective ideas per run** — against 1.833 under the conditional rule and
1.089 before either — with every parsed proposal distinct in all four runs. Parse rate 17/32.

### The per-kind audit contradicted ADR-053's own inference

ADR-053 assumed the other kinds' approvals reached the Cell the way `STRATEGY`'s did. Three of four
were wrong. With the summary hidden:

| kind | does the approved substance still reach the Cell? |
|---|---|
| `strategy` | **yes, immediately** — `Your standing strategy` |
| `experiment` | **yes, once the grant is started** — `Your current experiment` |
| `tool_request` / `external_action` | **yes, on consumption** |
| **any kind, rejected** | **no** — the reason survives, the subject does not |

Approval's consequence arrives **when the grant is consumed**, not when it is granted; `STRATEGY`
looked immediate only because approving it *is* the act, so there is nothing to consume.

### One real cost, pinned rather than fixed

**A rejected proposal loses its subject.** The Cell learns that it was rejected and why, not what.
`test_a_rejected_proposal_loses_its_subject_and_that_is_recorded` asserts it so it cannot become a
surprise; fixing it means showing rejected summaries, which reintroduces the anchoring, and that
trade is a §23.4 question deserving its own arm. §23.4's `repeat_after_rejection` detector is now the
only thing watching for the repeat this invites.

### Verification

- **Teeth-checked three ways**, all caught, including a regression back to **ADR-052's own gate** —
  so the refuted design cannot quietly return.
- **The history-bound test had gone silently vacuous a second time.** It matched on probe wording,
  which no longer renders, so it passed while measuring nothing. It now **counts entries** in the
  log — the thing §15.1's bound actually governs — and separately asserts no wording leaks anywhere
  in the render, which catches a different section dumping history.
- **Golden diff is eight deliberation rows of eleven**, `context_tokens` only; the three that do not
  move are the wakes with no proposal log. `model_calls` and `resource_usage` follow;
  `resource_usage.minor_units` moves on no row, so **`balances` is identical in every account in
  every book** and `proposals` is byte-identical.
- **The heading was corrected too** — it claimed to show "your own prior words", which stopped being
  true. ADR-052 measured heading edits at zero behavioural effect, so it is carried as pure accuracy.
- **1010 tests passing** (1 net new; up from 1009).
- Next: whether to restore the summary **for rejections only**, measured rather than argued — the
  one case with no other channel, against the anchoring it would reintroduce.
