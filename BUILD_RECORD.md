# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, the experiment, and experiment attribution,
2026-07-21 through 2026-08-24):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-25 — The proposal kind that led nowhere, and the rung a Cell may not name

`experiment_grants.py` + an `ExperimentSpec` payload (ADR-045). No migration.
`ProposalKind.EXPERIMENT` has existed since migration 0013 and appeared **nowhere else in `src/`**.
A Cell could propose an experiment, it reached §23's queue, an operator could approve it — and the
grant sat inert, because `experiments.start` was reachable only from the operator's own CLI verb.
Every experiment in the colony was one a person typed by hand, and `experiments.proposal_id`, the
foreign key ADR-043 added for exactly this, could never be filled.

**The golden run had been carrying the evidence since expectation version 5**: one `experiment`
approval request, permanently `pending`, in every replay for four months.

### §0.2's table decides what the kernel may judge

Its two columns put **"experiments" in the mutable Cell side**, beside prompts, strategy and market
hypothesis — and "capital + population allocator" and "permissions + approvals" on the immutable
kernel side. So nothing in the new module reads, validates or rewrites a hypothesis: what is tested
is the Cell's business. What the kernel gates is the **§9.2 slot** (a colony-wide scarce resource)
and the **§25.1 rung**. An operator approving one of these approves a cost and a stage, never a
scientific opinion.

### The rung has nowhere to be named

§25.1 opens with "no strategy moves directly from synthetic success to autonomous commerce", and a
Cell that could name its own rung could ask for rung 7 on its first wake and need one distracted
operator to get it. §23.5 already generalised the problem — the queue "will be optimised against by
Cells" — so `ExperimentSpec` has **no rung field at all** (`FORBIDDEN_RUNG_FIELDS` is the third
tripwire in `proposal.py`, after §0.3's and §16.3's) and `entitled_rung` reads the answer out of
`promotions`. §25.1 becomes a property of the schema rather than a rule someone remembered to check.

**"Reached" and "entitled to" turn out to be different questions over the same two tables.**
`experiments.stage_reached` maxes over `promotions.rung` *and* `experiments.ladder_rung`, because a
Cell that ran rung-1 work has genuinely reached rung 1. `entitled_rung` deliberately does not:
unioning them would turn ADR-043's recorded-but-unenforced `start-experiment --rung 7` into a
permanent ratchet on what the Cell may then ask for by itself.

### Where it had to live

`approval` imports `deliberation`, which imports `experiments` — so `experiments` **cannot** import
`approval`, and the consumer cannot live there. That is the registry/executor split this kernel
already makes twice: everything that reads or refuses stays low enough for `context`, and the part
that spends a grant sits above `approval`.

### Verification

- **949 tests passing** (18 new, 0 removed; up from 931). **Golden expectation 21 → 22**, with
  **`balances` identical in every account in every book** — starting an experiment opens no
  reservation and posts no entry. Every deliberation gains ~160 input tokens, one cause: the
  prompt's schema hint now describes the `experiment` block and it is in every system prompt. The
  snapshot pins a **`running`** experiment for the first time — the state §9.2's cap actually
  counts, and the one every prior version missed because all its experiments ended terminal.
- **`test_only_the_promotion_module_consumes_a_grant` loosened a third time**, which is the friction
  it exists to create. The argument: this is the only one of the four consumers that *provably
  cannot climb the ladder* — `promotion` hands over capital, `tools` runs a fetch,
  `external_actions` spends a person's attention; this one writes a row and stamps a rung it read
  from `promotions`. The scheduler is barred for a different reason than the other three: an
  experiment on a timer spends nothing but consumes a §9.2 slot, and a colony that ratcheted itself
  to its own cap unattended would refuse every experiment a person then wanted to run.
- **Teeth-checked twelve ways**, each failing its named test: `entitled_rung` returning a constant,
  `entitled_rung` unioning experiments the way `stage_reached` does, the grant consumed outside the
  rollback, no kind check, a consumed grant reusable, an expired grant still acting,
  `startable_grants` listing what would refuse, `ExperimentSpec` growing a `ladder_rung`, both
  directions of the payload/kind rule, the hypothesis taken from `summary` instead of the frozen
  payload, and `proposal_id` left null.
- **Requiring the payload broke 71 tests**, all fixtures using `experiment` as the neutral kind. A
  real signal and the wrong one to obey: an experiment that cannot state what it is testing is a
  summary, and §10.5's coroner asks for "final hypotheses" by name. The fixtures now pair each kind
  with its own payload.
- **Hand-verified end to end on a live colony**: a Cell proposed an experiment, the kernel assessed
  MEDIUM against its claimed LOW (§23.5), an operator approved it, `startable-experiments` showed
  the rung *before* anything started, and the grant started it at rung 1. A second start on the same
  grant is refused; `--rung` with `--grant` is refused outright rather than ignored.
- **A guard was removed, not added**: the new module's dead-Cell check shadowed a better message from
  `experiments._start_locked` inside the same transaction. ADR-039's "second, weaker copy" applies to
  guards as much as to gates.
- Next: `ProposalKind.STRATEGY` and `SPEND_REQUEST`-adjacent kinds are now the only ones whose
  approval leads nowhere in particular; and §13.1's `normalised_cost` still has no stage tranche to
  divide by, which is the next thing an experiment's rung could be made to mean.
