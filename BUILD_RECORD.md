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
measurement, §15.1 anchoring and the twins that chose the fix, the proposal log that
shows no wording, the §23.4 repeat, the wake reason, the genome, the human-decision wake,
the +15% that did not survive honesty, §13.4's concreteness measure,
§13.2's selector, §12's novelty archive, the inbound counterparty key,
§12.1's declared third dimension, rung 8, §12.3's `P(next stage)`, the
Auditor path for §13.3/§13.4's content judgments, the software_native_advantage
gate reading a resolved content audit, model_policy's temperature socket,
risk_tier becoming optional for abstain, the bounded single parse-repair
retry, the argued refusal to extend it to the Auditors or `call-model`,
an external audit's clean source-distribution archive, and its egress-boundary
repair (robots.txt transport, SSRF, honest personal-data status),
2026-07-21 through 2026-09-04):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-05 — External audit brief, Slices C–E: docs reconciliation, a lint gate, and auto-promotion reaching `tick`

Continuing the brief's priority order after Slices A–B (distribution hygiene, egress boundary;
archived above): documentation repair, a minimal static-analysis gate, then the scheduled-path
wiring the brief calls out as the last step before the Phase 2 flight simulator becomes the
gating priority.

### Slice C — documentation/safety-claim reconciliation

README's Status table carried stale counts (a fixed test/migration/golden-version trio that had
already drifted once) and a "two separate humans" approval claim the code has never enforced —
`approval.approve` takes any `decided_by` string, so a single operator approving their own request
is not code-refused, only discouraged by convention. Rewrote the Status section as a phase-capability
table plus a **Tests** row that names the mechanism (`pytest`, Hypothesis property tests) instead of
a number that goes stale on the next commit, and corrected "two separate humans" to "two explicit
steps" with an audit-trail caveat rather than a code-enforced guarantee. Backed by
`scripts/check_docs_facts.py` (stdlib-only: migration count from the migrations directory, golden
expectation version from `golden_expectations.json`, CLI verbs via an AST walk of `cli.py`'s
`add_parser` calls, README's own referenced verbs via regex) wired into CI so a claim that *can*
drift automatically fails the build the next time it does, instead of waiting for the next external
audit to notice.

### Slice D — a narrow runtime-defect lint gate

The brief's claim reproduced exactly: `tools.py`'s `ToolCall.arguments: dict[str, Any]` referenced
`Any` with no import, a live `NameError` on any code path that called
`typing.get_type_hints` against that class (confirmed by reverting the one-line fix and getting the
exact `NameError: name 'Any' is not defined`, before re-fixing). Added `ruff` as a dev dependency
scoped to `E9,F63,F7,F82` — undefined names and syntax-shaped errors only, **not** the ~339-finding
broad style sweep a default `ruff check` reports, which stays deliberately unchased in one commit
per CLAUDE.md. `test_public_type_hints_resolve` pins the guarantee structurally
(`typing.get_type_hints` on every public class); CI gained both the docs-fact-check and the lint
gate as separate steps.

### Slice E — wiring `autopromotion.EvidencePromoter` into the scheduled `tick`

`cli.py::cmd_tick` never passed a `promoter` to `scheduler.tick()`, so an operator who enabled
`auto_promotion` (§27.1) got proposals deliberated and queued every tick but **nothing ever
allocated** unless they separately remembered to run the standalone `mitosis auto-promote` verb by
hand — the flag looked live and silently wasn't, on the one path (`cron` + `tick`) an unattended
colony actually runs. One line (`promoter=autopromotion.EvidencePromoter()`), leaning entirely on
`autopromotion.sweep()`'s own pre-existing flag gate and guard coverage (ADR-063) — nothing new to
build, only a missing call site.

**Reading the guards changed what "on" needed to test.** `approval._kernel_tier` unconditionally
floors a `spend_request` at `RiskTier.MEDIUM` regardless of what the Cell claims, and
`RequestStatus.batchable` requires `assessed_tier is RiskTier.LOW` — so **no `spend_request` can
ever be batchable**, and `sweep()`'s own `approve_batch()` step can therefore never auto-approve
one, flag on or off. Since `promotion.allocate()` also requires the grant's proposal be exactly
`spend_request` (the only kind that moves capital), approval and allocation never meet inside one
unattended sweep for this proposal kind: a human approves (`approval.approve()`, exactly as today),
and what this slice adds is that *allocating* that already-approved grant — moving the money, waking
the Cell — now reaches an ordinary scheduled tick instead of requiring the standalone verb. Written
up as ADR-071, since the brief's own phrasing ("approves and allocates") described a scenario that
turns out to be unbuildable in good faith without loosening a live safety floor nobody asked to
revisit.

#### Verification

- **7 new tests** (`tests/test_scheduler_autopromotion.py`): flag off leaves an approved grant
  un-allocated; flag on allocates it; the same property proven **end-to-end through `cli.main`**,
  not just `scheduler.tick()` directly — every other test passes its own `promoter` by hand, so only
  the CLI-level test actually pins `cmd_tick`'s call site; a HIGH-tier request stays queued for a
  person even with auto-promotion on; vacation mode blocks the promoter before deliberation even
  runs (a paid, unreachable `_Boom.complete` proves it); ticking twice does not double-allocate;
  a structural AST test pins that `scheduler.py` still imports none of
  `autopromotion`/`promotion`/`outcome` (the dependency inversion CLAUDE.md names explicitly).
- **Three teeth-checks, each mutate → confirm the specific test fails for the stated reason → restore
  verbatim (never `git checkout`, working tree held in memory).** Removing `cmd_tick`'s `promoter=`
  line failed only the CLI-level test — every direct-`scheduler.tick()` test kept passing, which is
  exactly the gap that test exists to close. Reintroducing a `promotion` import into `scheduler.py`
  failed the structural test by name. Neutering the vacation guard (`if False and is_paid and
  is_on_vacation(...)`) **surfaced two real bugs in the test itself before it could confirm
  anything**: `list == ()` is unconditionally `False` in Python regardless of contents (every
  `allocatable_grants`/`list_promotions` call returns a `list`, so four assertions across the file
  were comparing against the wrong empty-container literal and would have failed even in the
  passing case, or — worse — silently proven nothing when written the other direction), and the
  vacation test's own paid `_Boom` provider tripped the *earlier* `real_spending`-disabled guard
  first, never reaching vacation at all, mirroring the exact confound
  `test_an_absent_operator_pauses_paid_work_but_not_free_work` in `tests/test_scheduler.py` already
  guards against with `scheduler.set_real_spending(conn, True)`. Both fixed, then the same mutation
  re-run to confirm the *fixed* test fails for the right reason before restoring the guard.
- Full suite **1239 passed** (up from 1232 at the end of Slice D — 7 new); golden run unaffected
  (hash unchanged at 38, as expected — this slice touches `cli.py` and tests only, no scenario or
  kernel-semantics change); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: the Phase 2 flight simulator (Slice F) — deterministic seeded environments, at least two
  independent market-family models, a `mitosis simulate` verb, population scale, an assertion
  `USD_REAL` never moves — is now the brief's and PRIORITIES.md's shared gating step for real
  evolutionary evidence (Phases 2–3 remain deliberately unbuilt). Its own design/scoping pass comes
  first, given its scale, rather than freehand implementation.
