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
an external audit's clean source-distribution archive, its egress-boundary
repair (robots.txt transport, SSRF, honest personal-data status),
documentation/safety-claim reconciliation, a narrow runtime-defect lint gate,
auto-promotion reaching the scheduled `tick`, the flight simulator's first
slice (mock Cells deciding through the real deliberation pipeline), its
second (a second market family, environment separation, regime shifts), and
its third (the remaining mutation operators, wired through a real choice),
2026-07-21 through 2026-09-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-05 — Phase 2 flight simulator, fourth slice: chaos drills as repeatable scenarios (Slice F, part 4)

Continuing the same sub-slice sequence (ADR-072–074) without a fresh plan-mode round-trip.
ADR-075 is the full as-built record.

### What shipped

New `src/mitosis/simulation/chaos.py`, all five brief-required drills, plus one new seam:
`runner.run()` gains `epoch_hook`, called once per epoch after that epoch's own processing already
completed, so every hook-shaped drill shares one addition to `runner.py` rather than one each.
`KillFractionDrill` kills a seeded fraction of living Cells; `WithdrawCapabilityDrill` disables the
`auto_promotion` autonomy flag mid-run; `CrashingEnvironment` (a `MarketEnvironment` decorator, no
runner change needed) raises once from `evaluate()` at a chosen epoch; a regime-shift drill and a
duplicate/out-of-order drill reuse existing mechanisms rather than adding new ones (below).

### Two of five drills needed reframing, stated rather than silently substituted

"Corrupt or withdraw one shared capability/module" has no module/tool-use surface in this simulator
yet (`SimulationPolicyProvider` decides from genome content alone) — `auto_promotion` is the one
capability that actually is shared and colony-wide, so withdrawing it is a real loss, not a
stand-in. "Crash at reserve, execute, and settlement boundaries" targets the *experiment*
lifecycle's own three-phase shape (start/evaluate/conclude), not the deeper money-reservation FSM in
`gateway.py` — that FSM's crash safety is Charter C6's job, already exhaustively verified
independent of any live population; what's genuinely new is whether a full run's own state
(population, audit trail, manifest) survives one call failing mid-flight. The other two boundaries
(`start_from_grant`, `conclude`/`record_revenue`) have no injectable seam today, and building one
solely for a drill to target would be speculative surface for no other caller.

### A wrong assumption, corrected before it shipped

The plan assumed an out-of-order funding call (a child funded before its birth is visible) would be
rejected. Checking rather than assuming: `ledger` accounts are plain strings, not a foreign key into
`cells` (confirmed by reading `scheduler.eligible_cells`, which starts from the `cells` table and
only then checks balances) — so the call neither corrupts anything nor raises; it parks an inert,
unreachable balance instead. The test asserts what's actually true, not the rejection that doesn't
happen.

### Verification

9 new tests (42 total): each drill's real effect verified independently of its own self-report (a
coroner-report count matching the claimed kill count, not just trusting it; the autonomy flag
actually flipped; one recorded failure and the interrupted experiment concluding on a later epoch,
not just "didn't crash"; a >5x aggregate sales drop across the regime-shift boundary at full-economy
scale; duplicate-call idempotency; out-of-order inertness); the shared post-drill invariant helper;
two determinism-under-a-drill checks covering both injection mechanisms (epoch-hook and
environment-wrapper). Five teeth-checks, each confirmed to fail for the stated reason and restored
verbatim. Full suite green; golden run unaffected (hash unchanged at 38); `ruff check .` and
`scripts/check_docs_facts.py` both clean.

- Next: full manifest richness and the two acceptance-scale configurations (Slice F5) close out
  Slice F, then Slice G's remaining `SelectionPolicy` implementations and Slice H's pre-registered
  Phase 3 comparisons.
