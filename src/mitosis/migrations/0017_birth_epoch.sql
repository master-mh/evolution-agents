-- §9.2's `max_births_per_epoch`, finally enforceable (SPEC.md §9.1, §9.2, §9.3).
--
-- The limit has been stored in `colony_config` since the Phase 1 population
-- slice and unchecked ever since, for one missing prerequisite: there was no
-- epoch. ADR-026's scheduler built that primitive; this migration supplies the
-- other half, which is knowing *which* epoch a Cell was born in.
--
-- **Why it is stored rather than derived.** Every other count in population.py
-- is derived from live rows (Charter C3's rule), and this one cannot be. Cells
-- are stamped `created_at_utc` in **wall** time while epochs are spans of
-- **simulated** time, and §6.3 forbids mixing the two "without explicit
-- conversion metadata". The scheduler's `epoch_log` is that metadata for spend
-- — but it only holds anchors for epochs a *tick* has observed, so a colony
-- driven by hand would have births attributable to no epoch at all, and a cap
-- that silently never binds is worse than one that does not exist. Recording
-- the epoch at the moment of birth is the only reading that cannot go missing.
--
-- **NULL for Cells born before this migration**, deliberately not backfilled
-- to 0. Those births really did happen outside any epoch this colony can now
-- reconstruct, and stamping them into epoch 0 would consume a live colony's
-- current birth budget with history. NULL reads as "before the cap existed",
-- and `births_in_epoch` counts an exact match, so historical rows are excluded
-- from every epoch rather than dumped into one.
ALTER TABLE cells ADD COLUMN born_in_epoch INTEGER;

CREATE INDEX idx_cells_born_in_epoch ON cells (born_in_epoch);
