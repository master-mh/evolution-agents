-- Reproduction and lineage tracking.
-- SPEC.md §9.2 (max population share descended from one ancestor), §9.4
-- (founder-effect control, Amendment A10), §16 (genome parentage);
-- docs/DECISIONS.md ADR-019.
--
-- `parent_cell_id` is the vertical-descent edge: NULL for a seeded founder
-- (lifecycle.create_cell), set for a Cell born via lineage.reproduce.
--
-- `founder_cell_id` and `generation` are denormalized but *immutable* — a
-- Cell's parent never changes after birth, so neither can drift. They exist
-- because the §9.2 lineage cap is checked on every birth, and a stored
-- founder turns that into a GROUP BY instead of a recursive walk. Both are
-- re-derived from the parent chain and checked by
-- lineage.verify_lineage_integrity(), the same way ledger balances are
-- always re-derivable from entries (Charter C3's spirit).

ALTER TABLE cells ADD COLUMN parent_cell_id TEXT REFERENCES cells(cell_id);
ALTER TABLE cells ADD COLUMN founder_cell_id TEXT;
ALTER TABLE cells ADD COLUMN generation INTEGER NOT NULL DEFAULT 0;

-- Cells that existed before this migration are all seeded founders by
-- definition: there was no reproduction path that could have given them a
-- parent.
UPDATE cells SET founder_cell_id = cell_id WHERE founder_cell_id IS NULL;

CREATE INDEX idx_cells_parent ON cells(parent_cell_id);
CREATE INDEX idx_cells_founder ON cells(founder_cell_id);
