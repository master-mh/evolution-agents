-- Population control and carrying capacity (SPEC.md §9; §27.1 colony.yaml
-- `population:` block — field names match exactly). Single-row config table.

CREATE TABLE colony_config (
    id                              INTEGER PRIMARY KEY CHECK (id = 1),
    max_living_cells                INTEGER NOT NULL,
    max_active_cells                INTEGER NOT NULL,
    max_parallel_experiments        INTEGER NOT NULL,
    max_births_per_epoch            INTEGER NOT NULL,
    max_lineage_population_fraction REAL NOT NULL
);
