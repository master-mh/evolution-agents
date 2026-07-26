# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring and seeded ids, 2026-07-21 through 2026-07-26):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-07-26 — Reproduction and lineage tracking (the Phase 2 prerequisite)

The first Phase 1 item that isn't merely additive: Phase 2's flight simulator needs Cells that
reproduce, and `max_lineage_population_fraction` (§9.2) had been stored-but-unenforced since slice 3
precisely because there was no lineage to measure.

- **New `src/mitosis/lineage.py` + migration `0009_lineage.sql`.** `reproduce()` is the second
  birth path: a child of a living Cell, **funded from the parent's own cash** rather than a colony
  account. That funding rule is the point — a parent cannot mint capital, so lineage growth is
  bounded by the lineage's own money, and Charter C4's guard applies to reproduction for free.
  `cells` gained `parent_cell_id` (NULL for a seeded founder), plus immutable denormalized
  `founder_cell_id`/`generation`.
- **The design decision, written up as `docs/DECISIONS.md` ADR-019.** §9.4 defines lineage
  "strictly by genome parentage", which is unimplementable as stated against this kernel: genomes
  are content-addressed (ADR-018) and Phase 1 genome content is a placeholder carrying only
  `cell_type`, so *every* commercial Cell hashes to one genome row — deriving lineage from it would
  put unrelated Cells in one lineage and fire the cap on them. There's also a structural problem
  independent of Phase 1: under content addressing an unmutated child *is* its parent's genome, so
  a genome-parentage edge for it would be a self-loop. Resolution: vertical descent is recorded on
  the Cell and is what the cap is enforced against; genome parentage is recorded too, but only
  where a mutation actually changed the content. Amendment A10's substance is preserved — lineage
  means vertical descent, and a shared module (or a shared genome) never creates a lineage edge.
- **`max_lineage_population_fraction` now enforced** (`check_lineage_licence`, inside the write
  lock like every other birth check). Two consequences worth stating plainly, both documented in
  lineage.py, ADR-019, and the error message itself: seeded founders are exempt (a founder has no
  ancestor, and a lone founder is trivially 100% of a one-Cell colony), and **a small colony
  genuinely cannot reproduce** — with the colony.yaml default of 0.20, any second-generation Cell
  in a 4-Cell colony is already 40% of it. Growing past the seed needs enough founders or a
  raised cap. That's §9.3 applied literally ("the birth waits" → a synchronous kernel raises),
  matching the conservative stance population.py already takes for displacement.
- **`genome.py` gained mutation support:** `canonical_genome_json(cell_type, mutation)` overlays
  caller-supplied fields, with JSON-serializability validated up front (new `GenomeError`).
  `lifecycle._get_or_create_genome` now carries `parent_genome_hashes`/`mutation_operator`/`version`
  on creation, and drops a self-referential parent edge if a "mutation" didn't actually change
  anything. Provenance is recorded only when the row is *created* — rediscovering existing content
  from a different parent must not rewrite how that genome first came to exist.
- **Golden run extended** (SPEC.md §26 names the "expected lineage tree" as golden-run content, so
  reproduction drift had to become visible in CI): the scenario now reproduces the auditor with a
  mutated genome, and `semantic_snapshot` carries parent/founder/generation as *aliases*, keeping
  the snapshot uuid-free. This is a real expectation migration via the A12 path
  (`--update-expectations`); the diff was reviewed line by line and every change is attributable to
  the new step — parent debited exactly 500, child credited 500, one new `cell_reproduction_funding`
  transaction, one more lifecycle audit event, living 3→4, active 2→3. No conservation, chain, or
  linkage invariant moved. The scenario's lineage cap was raised to 0.50 with a comment, since a
  4-Cell colony can't reproduce at 0.20.
- **CLI:** new `mitosis reproduce --parent --budget [--type --mutation --mutation-operator]`, and
  `status` gained a lineage section (per-founder living/total/depth/share, largest first, plus the
  integrity check).
- Verified by hand before the tests, which is again where the design got pinned down: built a
  4-generation lineage at realistic scale and confirmed generation/founder propagation, that an
  unmutated child reuses its parent's genome row while a mutated one gets a distinct genome with a
  correct parent edge and incremented version, that the parent is debited exactly the child's
  budget with conservation and the hash chain intact, and that a death shrinks the *living* lineage
  count without erasing lineage history. Then drove every rejection path (unknown/dormant/
  quarantined/dead parent, over-balance, zero budget) confirming cash was unchanged after each, and
  the CLI's error paths end to end (clean `error:` lines, exit 1, no tracebacks).
- Also verified the **migration upgrade path**, which no test covers because every test builds a
  fresh DB: built a colony on the pre-0009 schema, confirmed the new columns were genuinely absent,
  then upgraded it and confirmed `founder_cell_id` backfills to each Cell's own id with
  `generation` 0 and integrity green. That detour surfaced one real robustness gap — a NULL founder
  (unreachable through the kernel, but reachable in a corrupted or hand-edited DB) made `status`
  traceback instead of reporting, right next to the integrity line that exists to flag it. Fixed
  and covered.
- **274 tests passing** (43 new, 0 removed; up from 230). New `tests/test_lineage.py` (36);
  `tests/test_cli.py` gained 6 for the new verb and the status section; `test_golden.py` gained
  `test_snapshot_pins_the_lineage_tree`. Charter coverage: C9 gained
  `test_charter_carrying_capacity_lineage_share`, a Hypothesis property that no lineage ever
  exceeds its configured share across arbitrary reproduction sequences — it immediately earned its
  keep by falsifying an over-strong first draft of the invariant and forcing the seeded-founder
  exemption to be stated explicitly (now pinned by its own test rather than assumed away).
- Deliberately out of scope, unchanged from the prior list: **displacement** (§9.3/ADR-009) still
  isn't implemented — a denied birth stays denied, because the §10.5 death criteria that identify an
  objectively-failing Cell to evict still don't exist. Sexual recombination / multi-parent genomes
  (§16.5) are out (schema takes a list; `reproduce` takes one parent). §16.3's inheritance classes
  are not modeled: a child inherits genome content and nothing else, since this kernel has no
  assets, obligations, customers, or credentials to inherit or withhold. `max_births_per_epoch` is
  still unenforced (needs the clock wired to a real epoch counter) and `max_parallel_experiments`
  still needs experiment tracking.
- Not yet committed or pushed — reporting for review first.
- Next: Phase 2's other prerequisites are experiment tracking (also unblocks
  `max_parallel_experiments` and the coroner report's always-empty `experiment_ids`/`stage_reached`)
  and wiring the simulated clock into real timestamps/epochs. The remaining CLI commands and
  `kill()`'s reservation/balance sweep stay additive.
