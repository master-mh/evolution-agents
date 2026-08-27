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
the +15% that did not survive honesty, §13.4's concreteness measure, and
§13.2's selector, 2026-07-21 through 2026-08-27):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-27 — §31 lists two tables for the novelty archive, and §12.2 refuses both

`novelty.py` + 17 tests + `mitosis archive` + golden expectations **29 -> 30** (ADR-060).
**No migration.** `structural_novelty` wired into §13.2's frontier.

ADR-059 shipped the selector with `structural_novelty` abstaining and ADR-058 scored one of §13.4's
four flags, both for the same reason: **there was nothing to be novel against.**

### The clause that removed the tables

> **§12.2** Store full raw behavioural descriptors **separately**; the archive is a **derived
> view**, allowing later rebuilding with different dimensions and bins.

Read as an instruction it says "make a table". Read for what it protects, it says the archive must
not *be* the record — and in this kernel the raw material already lives separately and in better
custody: `cell_genomes` is content-addressed (§16.1) and append-only. A `behavioural_descriptors`
table would be the second version §2.5 refuses, and §31 offers "suggested entities" rather than a
build order. **Third and fourth §31 entity that §2.5 has removed** (after ADR-043, ADR-044).

### One of §12.1's three dimensions is live, and the block on the other two is specific

`novelty_distance` is structural. `buyer_type` and `revenue_recurrence` both need to know *who
paid*, and `revenue.record_revenue` records that as free text — so two payments from one buyer are
indistinguishable from one each from two. **The colony already solved this outbound**: §21.2's
`external_action_registry` stores a salted hash of a counterparty, equality without identity, exactly
as §16.3 requires. Naming the asymmetry beats guessing: counting payments per *Cell* would report a
Cell with three one-off customers as `repeat`.

### The bins are §13.4's language, not a threshold anyone chose

**adjacent** = the nearest earlier genome differs in exactly one business field, which is §13.4's
first flag as a distance. **moderate** = more than one, but some earlier genome shares its `market`.
**radical** = no earlier genome shares its `market` (§16.3 makes the market hypothesis what keeps a
lineage that lineage).

**Radical is checked first**, and that ordering is load-bearing — a genome whose only changed field
*is* the market would otherwise be filed as a relabel, inverting §13.4 rather than applying it.
**Zero distance is a real case**: a genome differing only in `risk_class` or `allowed_tools` gets a
new content hash and the same hypothesis, so it bins `adjacent` with its own reason. Otherwise a Cell
could reach a further niche by asking for permissions instead of by having an idea.

**It is a distance, not a merit.** A small one is evidence of §13.4's first flag; a large one proves
nothing, since a genome changed to nonsense scores `radical`. Being a Pareto axis rather than a score
is what makes it safe to ship: nothing is funded for being radical.

### Verification

- **Teeth-checked eight ways**, and **two came back MISSED** — the §13.4 flag keyed on a field count
  rather than on the market, and niche occupancy counting genomes instead of Cells. Both fixtures
  could not distinguish the two behaviours; rewritten, both now CAUGHT. The second one the golden
  replay also cannot catch, because its two niches happen to hold as many Cells as genomes.
- **1058 tests and the golden run green.** Only the `selection` section changed
  (`structural_novelty` null -> 0.0) plus the new `novelty_archive` section; **`balances` identical
  in every account in every book**, because the archive is derived and writes nothing.
- Next: an **inbound counterparty key** is what unblocks two more §12.1 dimensions and with them a
  two- or three-dimensional archive. Then §12.3's Thompson posteriors — which need stage
  *conversions*, and `promotion.allocate` only ever issues rung 7, so the ladder's next rung comes
  first.
