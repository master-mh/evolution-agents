-- Global real-spend circuit breaker (SPEC.md §5; Charter C5). Single-row
-- config table, USD_REAL only ("real spend" — never USD_SIM/RESOURCE).
-- Field names/shape match §27.1 colony.yaml's `real_spend_limits:` block.

CREATE TABLE real_spend_limits (
    id                                   INTEGER PRIMARY KEY CHECK (id = 1),
    per_request_minor_units               INTEGER NOT NULL,
    per_hour_minor_units                  INTEGER NOT NULL,
    per_day_minor_units                   INTEGER NOT NULL,
    per_month_minor_units                 INTEGER NOT NULL,
    max_concurrent_reserved_minor_units    INTEGER NOT NULL,
    provider_limits_json                  TEXT NOT NULL DEFAULT '{}'
);
