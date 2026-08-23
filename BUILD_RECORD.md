# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, and the tool surface,
2026-07-21 through 2026-08-23):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-23 — The artifact store: what a Cell made, and what it may do with it

`artifacts.py` + migration 0020 (ADR-035). A Cell could decide, be funded, and read the world. The
thing it *produced* had nowhere to live — so `revenue.record_revenue` attributed money to a
free-text string, and `ledger_entries.artifact_id`, an **Amendment A3 required field present since
migration 0001**, had never been populated by anything.

### §11.3 forbids the obvious identity, and this is the third time

> Auditors inspect ... **duplicated artifacts with new names**

A uuid plus a title makes that trivial to do and turns detection into a permanent chore. **Content
addressing makes it unrepresentable** — two identical artifacts are one row, and a Cell resubmitting
its own work gets its own artifact back. Same move as ADR-018 for genomes and ADR-033 for the closed
genome schema, and at three instances the principle is worth naming outright: *prefer making the bad
state impossible over detecting it*. The title is part of the address, so a rename is an honest new
artifact rather than a way to hide that two things are the same.

### §1 names the fitness dimension a work-product store invites

> The colony is *not* successful because it ... **produces many artifacts**

So nothing counts them. §10.3 makes an Explorer's value depend on *useful* artifacts, and §11.2 puts
usefulness strictly downstream — another Cell adopts it, verification passes, the adopter
progresses, it is not reciprocal farming, causal contribution recorded. None of those five are
things the producer controls, which is the whole point. A structural test guards `death` and
`outcome` against ever mentioning artifacts.

### Rights propagate; they never reset

An artifact derived from a fetched page inherits that page's §20.1 position most-restrictive-wins,
and taints union. Without it, "summarise it into an artifact" is a one-step launder: since every
tool result is `commercial_use: unknown` by construction (ADR-034), anything built on one is
`unknown` too, and therefore unsellable until a person establishes the rights. Colony-authored work
also starts `unknown` rather than `permitted` — whether the colony may sell its own output is a
question for a person, not a default.

### Production is free, export is gated — the opposite of the tool surface

§28's Phase 8 gates *external use*, not production, and §19.3 names an "artifact-export gateway".
Writing to the colony's own store is not an external action. Gating production instead would put a
human in the loop for a Cell drafting into its own store, and spend the §23 queue — a finite
resource §23.5 warns is optimised against — on the cheapest thing a Cell does.

### Charter C13's router is built; C13 is not satisfied, and that distinction is the point

C13 is the last Charter clause with no test, and artifacts are literally its subject. The gateway
refuses on `SIM_ADVERSARIAL`, so **the router that clause describes now exists and is tested** —
while C13 itself stays unsatisfied, because §18.2 is about lineages evolved under adversarial
synthetic incentives and nothing can produce that label until the Phase 6 shadow economy. The test
sets the label directly and says why. Calling this "C13 done" was the tempting, wrong move.

`UNTRUSTED_EXTERNAL` deliberately does **not** block export — that would forbid exporting anything
informed by research, i.e. every real deliverable. Its effect flows through `commercial_use`
instead, which blocks *commercial* export specifically. The control test matters as much as the
block: a gateway refusing everything passes every refusal test and is useless.

### Verification

- **781 tests passing** (23 new, 0 removed; up from 758).
- **Golden expectation 14 → 15**, and the scenario **records revenue for the first time in its
  history** — `USD_SIM::cell_revenue: 1`, deliberately not USD_REAL. The diff is small on purpose:
  the artifact rides on the deliberation that already existed, so `deliberations`, `proposals`,
  `model_calls`, `resource_usage` and `reservations` are unchanged in count. **No USD_REAL moves and
  `external_expense` is unchanged in both books.** The scenario **requires a commercial export to be
  refused** before exporting non-commercially — a run that only exported successfully would pass
  identically against a gateway that refused nothing.
- **Teeth-checked sixteen ways**, each failing its named test: content addressing abandoned, title
  excluded from the address, least-restrictive source winning, a derived artifact resetting rights,
  the personal-data flag dropped, colony-authored defaulting to sellable, the C13 block removed,
  researched work blocked from export, the §20.2 commercial gate removed, export repeatable, export
  needing no reason, a phantom source accepted, revenue attributed to a nonexistent artifact, A3
  attribution never written, abstention carrying work, and the index inlining content.
- **A structural test was checking the wrong thing and was rewritten.**
  `test_the_fetcher_is_not_imported_by_the_kernel` substring-matched "fetchers" in source, so it
  failed the moment `artifacts.py` *mentioned* the file in a docstring. Now scoped by AST — a
  structural test that fires on prose is one people learn to work around by not writing the prose.
- **Hand-verified on a live colony against a genuinely fetched page** (the `example.com` response
  from the previous slice). The artifact inherited `commercial_use: unknown` and
  `UNTRUSTED_EXTERNAL` from real data rather than a fixture; commercial export was refused citing
  §20.2; non-commercial export recorded; resubmitting identical content returned the same row and
  left the colony at one artifact; A3 attribution written to `ledger_entries`; conservation green in
  all three books, chain valid, `external_expense` 0.
- Next: §11.2's five-condition downstream credit and §11.4's decay both need experiment tracking,
  which still does not exist. Nothing delivers an exported artifact anywhere — export records that a
  human took it, and there is no channel.
