# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, and §9.2's birth cap, 2026-07-21 through 2026-08-22):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-22 — Auditor Cells: a flag that costs something

`auditor.py` + migration 0018 (ADR-032). §23.2's "independent Auditor summary" has read as
unavailable since ADR-027, correctly — the clause says *independent* and §0.3 forbids the proposing
Cell writing it. This fills it, and closes what PRIORITIES called the largest remaining gap in the
review path.

### The blocker on record was wrong on both counts

PRIORITIES said the hole would stand "until the Auditor type in §7's taxonomy is real". §7 is the
flight simulator, not the taxonomy; and `CellType.AUDITOR` has existed since Phase 1, with
`death.kill_for_negative_ev` validating a concurring Auditor since the death slice. Nothing was
missing from the type system. What was missing was any way for an Auditor to *produce* an audit —
a much smaller slice than the entry implied, and worth checking before scheduling rather than after.

### §10.4 forbids the obvious Auditor

The obvious one wakes, reads the proposal, and writes prose flagging whatever looks risky. §10.4:

    Auditor reward is **precision-weighted**: reward valid detected errors, prevented loss,
    reproducible findings; penalise wrongful flags, excessive false positives, unnecessary
    blocking, unverified accusations.

and §29's acceptance criterion 10 is, in full, "Wrongful Auditor flags are penalised". **Prose
cannot be penalised.** An Auditor whose flags cost it nothing will flag everything — maximally
cautious, maximally uninformative, and it looks responsible the entire time it is destroying the
signal the operator needs.

So every audit stakes a **probability, registered as a §8.5 prediction** before the outcome is
known, scored by the same proper scoring rule every other Cell faces. A wrongful flag lands in the
Auditor's own calibration record — the currency ADR-030's read-back already uses. Verified on a live
colony: a concern raised at p=0.2 against a request that then succeeded scores Brier 0.64, against
the 0.25 an Auditor gets for knowing nothing.

**The kernel composes the claim, not the Auditor.** §0.3 binds the independent evaluator as much as
the proposer: one allowed to phrase its own claim would phrase an unfalsifiable one and never be
wrong. And a verdict incoherent with its own probability — `concern` at p>0.5 — is refused, because
that pair is a free flag: the alarm the operator reads and the number the Auditor is scored on point
opposite ways.

### Independence is four checks, and the identity ones are the weak half

Not the subject, an oversight type (§10.4 pairs Auditor and Immune), a different lineage, able to
think. Lineage because ADR-027 already made it §23.4's aggregation key for the same reason — it is
the cheapest thing a Cell can split itself across, so also the cheapest way to manufacture a
friendly reviewer.

But a Cell running the same prompt over the same context is not independent whatever the row says.
What makes it a second opinion is that the Auditor is briefed on what the subject **cannot see about
itself**: its calibration record, its overdue count, its lineage exposure, and the kernel's
*assessed* risk tier rather than the tier it claimed.

### An audit advises; it never blocks

§10.4 penalises "unnecessary blocking" and §23.2 asks only that the summary be *shown*. `approval`
does not import `auditor` and does not branch on a verdict, enforced structurally. An Auditor with a
veto is a second approver — a governance change nobody argued for — and it would make flagging
strictly better than not, inverting the incentive the rest of the module builds.

### Three things the build found that the design did not

- **An unusable reply must be recorded, not raised.** The first implementation raised. But the
  gateway commits before the reply is parsed (ADR-022), so by then the Auditor has already paid for
  the call — raising leaves real spend with nothing explaining what it bought, and hides an Auditor
  that reliably produces nothing, which is itself a §10.4 fitness fact. Found by a CLI test.
- **Uniqueness had to become partial.** `UNIQUE (request_id, auditor_cell_id)` let one malformed
  reply permanently disqualify that Auditor from that request — a model's bad JSON deciding who is
  allowed to review what. It is now a partial unique index on `status = 'recorded'`: one *opinion*
  per Auditor, unlimited attempts.
- **Dormant Cells must be able to audit.** Requiring ALIVE was inconsistent with the deliberation
  path, where §17.2's whole model is dormant Cells woken by events — and an Auditor is idle between
  reviews by construction. Found by wiring the golden run, whose own Auditor sleeps.

### Verification

- **696 tests passing** (25 new, 0 removed; up from 671).
- **Golden expectation 11 → 12**: the auditor's child audits the explorer's queued request — a
  different lineage, and both sides pinned as aliases so a regression letting a Cell audit itself
  shows up as the same alias twice. **No USD_REAL moves**; the only balance change is 2 RESOURCE of
  metered compute, which is §10.4's governance overhead becoming non-zero for the first time. The
  USD_REAL leg *releases* rather than settles, the tell that the mock is priced at zero.
  `approval_grants` is byte-identical, which is where a regression to a blocking Auditor would show.
  **Two `resource_usage` rows appear to change and do not** — the audit now runs before the child's
  deliberation and takes those indices; checked rather than assumed, because a reordering and a
  regression look identical in a positional diff.
- **Teeth-checked sixteen ways**, each failing its named test: self-audit, any cell type auditing, a
  relative vouching, a quarantined Cell auditing, the flag staked on the wrong Cell, a wrongful flag
  going unpenalised, precision reading as perfect before any resolution, a hedged flag accepted, the
  Auditor writing its own claim, a rejected audit rendering as an opinion, an unusable reply raising
  and losing the paid call, an audit revised after the fact, `approval` importing the auditing path,
  a decided request being audited, the prompt rendering enums as a JSON list again, and the Auditor
  briefed on the claimed tier only. Two mutations were bad on the first pass — one still called the
  function it was meant to disable, one left the searched-for string in place — and were redone.
- **Hand-verified end to end on a live colony**: every independence check refused, the coherence
  guard refused a hedged flag, §23.2's field filled with attribution, idempotency held at one model
  call, and a wrongful flag moved precision to 0.0 with Brier 0.5625. Conservation in all three
  books, both hash chains green, `external_expense` 0 throughout.
- **Found while wiring the golden run:** §8.5's register has one namespace, and an Auditor now puts
  two kinds of claim in it — forecasts about its own work and flags about other Cells' requests. A
  naive "resolve everything this Cell predicted" folded an audit of the explorer into the §25.2
  read-back of the auditor's own funding. Scoped around in the scenario and logged; the real fix is
  a `kind` on the register.
- Next: nothing requires an audit and nothing schedules one; §10.4's governance overhead ratio is
  now computable and unbuilt; and §10.5's concurring-auditor check still validates a Cell's type but
  not its record.
