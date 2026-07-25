# Future Build Hooks

Append-only parking lot for suggestions, ideas, and deferred calls that surface mid-session —
a plan's "out of scope" or "assumptions to confirm" section, a tangent worth remembering, a
"novel idea" that isn't worth interrupting the current task for. **Not the roadmap** — if/when
this project grows a curated priorities or roadmap file, that's where actual planned work lives.
This file is the raw catch-net so nothing dies in a throwaway plan file under `~/.claude/plans/`
or scrolls out of a conversation.

Newest entries at the bottom. Each entry: date, source (which session/plan), the suggestion,
why it's not in scope now. Promote an entry into the roadmap (and delete it here) once it's
actually queued for building — this file is memory, not a backlog to work through in order.

---

## 2026-07-21 — MITOSIS v0.2 spec review
- Source: spec-review session (plan `users-mohammadmaster-downloads-mitosis-cheeky-stardust`).
- Deferred creative additions now normative in the *spec* but not yet built: executable Colony Charter, prediction register, coroner reports, North Star metric table, governance-overhead ratio, chaos drills, solo-operator vacation mode. Build lands in Phase 1+ once the kernel exists.
- §31 directive "must not be lost" long-horizon ideas (M2M commerce, one-customer software factories, CVT-MAP-Elites, approximate-Shapley credit, decaying royalties, internal compute auctions, etc.) live in the spec's per-section Future Build Hooks — pull from there when those subsystems come up.

## 2026-07-25 — Golden-run replay slice: seeded ids for reproducible event ordering
- Source: Phase 1 kernel slice 9 (golden-run replay), surfaced while making the scenario deterministic.
- **Amendment A5's ordering key `(effective_time, priority, event_id)` is a *total* order but not a *reproducible* one.** When two events share an effective_time and a priority, the tie-break falls to `event_id` — a `uuid4` today — so two runs of the same scenario can order those events differently. `golden.py`'s scenario sidesteps this by giving every event a distinct priority, but a Phase 2 producer emitting same-instant same-priority events would be flaky, and §26's "deterministic golden scenarios" would not hold for it.
- Fix is seeded/monotonic id generation (the same work as seeded ids generally, which also blocks byte-level golden comparison — currently worked around by hashing a normalized *semantic* snapshot per ADR-017). Not in scope for the golden-run slice itself: making ids injectable touches every module that calls `uuid.uuid4()`.
- Related: kernel timestamps are still real wall-clock (clock.py is built but unwired), which is the other half of why byte-identical replay is impossible today.
