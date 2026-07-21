# MITOSIS / Evolution Agents — Build Record

## 2026-07-21 — Spec review & v0.2 direction locked
- Reviewed MITOSIS v0.1 build spec (`~/Downloads/mitosis_full_build_spec.md`); delivered ~10 findings (real/synthetic money conflation, ledger hardening, reserve-without-release, no global spend breaker, no sim clock, 10-cell population can't show selection, farmable evidence credits, EV-based death, MAP-Elites too sparse, missing prompt mutation).
- User returned a v0.2 revision directive (`~/Downloads/MITOSIS_v0.2_revision_directive.md`) folding in the review + adding profit-first objective, 3-book accounting, population/carrying-capacity control, shared-reputation registry, sim-to-reality promotion ladder.
- Analysed directive: concur ~90%. Logged 4 pushbacks + 12 gap fixes + 7 creative additions (executable Colony Charter, prediction register, coroner reports, per-phase North Star table, governance-overhead ratio, chaos drills, solo-operator/vacation mode).
- Decisions: spec-only first pass; adopt all 19 amendments as normative. Plan saved at `~/.claude/plans/users-mohammadmaster-downloads-mitosis-cheeky-stardust.md`.
- **Wrote `docs/SPEC.md` v0.2** (1309 lines): all 32 directive sections + a Colony Charter (§0.1) mapping 15 constitutional invariants to named CI property-test IDs, all 19 amendments folded in normatively, per-phase North Star metric table (§27.1), Phase 0/1 coding task (§30). Downloads originals left untouched.
- Next: Phase 0 formal artifacts + `docs/DECISIONS.md`, then Phase 1 kernel.
- Committed `512fb2e` — `docs/SPEC.md` + project docs (PRIORITIES.md, BUILD_RECORD.md, CLAUDE.md, FUTURE_BUILD_HOOKS.md). First commit to the repo.

## 2026-07-22 — Phase 0 formal artifacts

- **Wrote `docs/DECISIONS.md`:** 18 ADRs covering the decisions-with-real-alternatives locked into SPEC.md v0.2 (three-book accounting, signed ledger amounts, canonical reservation FSM, real-spend breakers, Phase 3 gate softening, objective-only displacement, deterministic event ordering, executable Colony Charter, sandbox tiering, taint/clean-room migration, solo-operator model, golden-run semantic comparison, genome content addressing, and more), each with context/decision/consequences and a spec-section reference. Remaining amendments that are feature detail rather than alternatives-decisions are cross-referenced in a closing table instead of getting a standalone ADR.
- **Wrote `docs/STATE_MACHINES.md`:** formalized the Cell lifecycle FSM (`created|alive|dormant|quarantined|dead`) — states, transitions, guards, and required side effects — which SPEC.md §30 names but never diagrams; reproduced the already-normative reservation FSM (§4.4) as a companion diagram for implementers.
- **Wrote `docs/EVENT_SEMANTICS.md`:** the inbox/outbox atomic-processing algorithm, the `(effective_time, priority, event_id)` deterministic ordering tie-break (Amendment A5), simulated-vs-real event separation, and poison-event/dead-letter handling (§17.3), spelling out the mechanics behind §17's stated guarantees.
- Considered out of scope for this pass: SQLite DDL/schemas (naturally a Phase 1 kernel deliverable per §30's combined Phase 0+1 task list) and standalone diagrams for fitness vectors / promotion ladder (already adequately tabulated in SPEC.md §10, §25 — no separate artifact needed).
- Next: Phase 1 deterministic kernel per PRIORITIES.md.
