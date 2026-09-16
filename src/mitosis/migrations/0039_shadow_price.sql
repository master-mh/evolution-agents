-- The reporting-only shadow rate §1.1's second figure needs
-- (SPEC.md §1.1, §2.2, §2.4, §2.6, §10.1; ADR-099).
--
-- §1.1 reports AUTONOMY_ADJUSTED_PROFIT = real settled net profit less
-- shadow-priced human labour, donated infrastructure and free tiers. Human
-- minutes and local compute are metered in the RESOURCE book, and §2.2 is exact
-- about what that book is: "Resources may be shadow-priced for *reporting* but
-- are never posted as real cash." §2.6's own sample report prints an
-- "Autonomy-adjusted shadow cost ... USD_REAL-equivalent", so a rate has to
-- exist somewhere — and §2.4 forbids the colony inventing one, because a rate
-- the code chose is an implicit USD_SIM/RESOURCE → USD_REAL bridge wearing a
-- reporting label.
--
-- So the rate is **declared by a person, recorded with who declared it, and read
-- by exactly one module**. Until someone declares one, `profit.report` reports
-- the second figure as unavailable rather than as 0 — a 0 would read as "nothing
-- was subsidised", which is the claim §1.1 exists to disprove.
--
-- **Single row, like `colony_config` and `real_spend_limits`.** Redeclaring
-- replaces it and is audited with the previous value, because a rate that
-- changed silently would move every historical profit figure derived from it
-- with no record of why (§3.6's posture, applied to a report rather than to the
-- ledger).
--
-- No ledger account and no transaction type: nothing here ever posts. The rate
-- multiplies RESOURCE units into a USD_REAL-equivalent inside one derived
-- report object and nowhere else.

CREATE TABLE shadow_price_config (
    id                              INTEGER PRIMARY KEY CHECK (id = 1),
    resource_micro_usd_per_unit     INTEGER NOT NULL CHECK (resource_micro_usd_per_unit > 0),
    declared_by                     TEXT NOT NULL CHECK (length(trim(declared_by)) > 0),
    declared_at_utc                 TEXT NOT NULL,
    note                            TEXT NOT NULL DEFAULT ''
);
