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

## 2026-07-25 — Golden-run replay slice: seeded ids for reproducible event ordering — RESOLVED 2026-07-26
- Built: `src/mitosis/ids.py`, wired into every `uuid.uuid4()` call site and into `golden.run_scenario`. See BUILD_RECORD.md / PRIORITIES.md.
- Still open, not this entry's scope: kernel timestamps are still real wall-clock (clock.py is built but unwired), which remains the reason a *real* colony can't be byte-identically replayed — tracked directly in PRIORITIES.md, not here.

## 2026-07-26 — Lineage slice: minimum-population floor before the lineage cap engages
- Source: reproduction/lineage tracking slice (see ADR-019).
- `max_lineage_population_fraction` is enforced literally, so in a *small* colony reproduction is impossible: at the colony.yaml default of 0.20, any second-generation Cell in a 4-Cell colony is already 40% of the living population. Seeded founders are exempt (a founder has no ancestor), so the bootstrap path is "seed more founders", and the cap is harmless at Phase 2's target scale of hundreds–thousands of Cells — a lineage may hold 200 of 1000. It only bites in small test/bootstrap colonies.
- Common EA practice is a **minimum-population floor**: the share cap only engages once the living population is large enough for a fraction to be statistically meaningful (e.g. `living >= 1/cap`). Deliberately *not* implemented, because SPEC.md §9 specifies no such threshold and inventing one would be inventing colony policy rather than implementing the spec. Worth revisiting when Phase 2 sets up real seeded populations — if the flight simulator ends up needing a floor to bootstrap, that's evidence the spec should gain one explicitly.
- Related, and also deferred: §9.4 lists diversity bonuses, diminishing birth priority, independent-replication requirements, and niche-specific carrying capacity as founder-effect measures. Only the hard cap is implemented; the rest are selection-policy concerns that belong with Phase 2's MAP-Elites/allocator work, not the kernel.
