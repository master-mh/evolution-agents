"""The Phase 2 flight simulator (SPEC.md §7, §8, §9, §14, §28 Phase 2;
implementation brief Slice F).

Sits above `scheduler`/`autopromotion`/`promotion`/`lineage`/`experiments`/
`providers` in this repo's dependency direction (CLAUDE.md's layering table):
nothing below this package imports it, the same shape as every other injected
seam (`scheduler.PromotionSweeper`, `population.Displacer`). It supplies new
*decisions* -- what a mock Cell proposes, what a customer does, which Cell
reproduces -- over existing kernel entry points; it never maintains a second
ledger, a second Cell table, or a second proposal/approval concept.

See `simulation.runner.run` for the orchestration loop and
`docs/DECISIONS.md`'s Slice F ADR for the architecture this package follows.
"""
