# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, and the §25.2
read-back, 2026-07-21 through 2026-08-22):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-22 — §9.2's birth cap, and why a rate limit must never kill anything

`population.py` + migration 0017 (ADR-031). `max_births_per_epoch` has been in `colony_config`
since the Phase 1 population slice — stored so the config matched `colony.yaml`, unenforced because
there was no epoch. ADR-026's scheduler supplied the epoch. This is the other half, and the last
§9.2 limit that was checkable and unchecked.

### The open question answered itself once the two refusals sat side by side

PRIORITIES had this down as needing a call: does a denied birth **wait** at an epoch boundary, or
**fail** like the other population caps? It fails — a synchronous kernel call cannot wait, which
`population.py` already said about §9.3. But putting the two refusals next to each other showed the
question was the wrong one:

    CarryingCapacityError   no slot. Durable — true until a Cell dies, which is
                            exactly why §9.3 lets a birth displace one.
    BirthRateExceededError  slots available, births spent for this epoch.
                            Temporary — clears when the epoch turns, nothing dies.

They refuse identically and mean opposite things. So `BirthRateExceededError` is a **sibling** of
`CarryingCapacityError` and never a subclass, and the rate check runs **before** the capacity check
and before any displacer is consulted. Had it inherited, every existing `except
CarryingCapacityError` in the kernel would have been enrolled in treating a wait as a shortage, and
the §9.3 displacement path would kill a Cell to get around a limit that would have cleared by
itself. §9.3 licenses displacement for "an available population slot"; §10.5 requires deaths to be
objective. A death caused by impatience is neither.

### The epoch is stamped at birth, and that is §6.3's doing

Every other population count is derived from live rows (Charter C3). This one cannot be. Cells are
stamped `created_at_utc` in **wall** time while an epoch is a span of **simulated** time, and §6.3
forbids mixing the two "without explicit conversion metadata". The scheduler's `epoch_log` is that
metadata for spend — but it holds anchors only for epochs a *tick* has observed, so a colony driven
by hand would have births belonging to no epoch at all, and a cap that silently never binds is
worse than one that does not exist.

Cells born before migration 0017 get NULL and are deliberately not backfilled to epoch 0, which
would consume a live colony's current birth budget with history.

### The layering forced a move, and the move was the right home anyway

`population` enforces §9.2 and cannot import `scheduler` — `scheduler` imports `lifecycle` which
imports `population`. The established fix here is an injected seam, and it is **wrong for a cap**:
`Displacer` and `ExternalOperationChecker` are optional by design, and any caller omitting an
optional seam would bypass §9.2 entirely. So the epoch primitive moved to `clock.py`, which is
where it belonged — an epoch is a span of simulated time, and §6 is the clock; migration 0014's own
header cites §6.3. `scheduler` re-exports the names, so no call site changed and there is exactly
one derivation of "which epoch is it". `epoch_log` stays in `scheduler`, being about a tick having
*observed* an epoch.

### Verification

- **671 tests passing** (12 new, 0 removed; up from 659).
- **Golden expectation 10 → 11**: `cells.born_in_epoch` is pinned, and the scenario turns one epoch
  immediately before its last birth so the column reads 0, 0, 0, 0, **1** rather than uniformly
  zero — a constant-stamping kernel would otherwise pass. The only other change is
  `clock.simulated_at` moving by that one day. **No money moves**: balances, transaction types,
  reservations, resource usage, predictions, promotions and assessments are byte-identical to
  version 10.
- **Teeth-checked nine ways**, each failing its named test: the cap not enforced, a rate limit
  reaching the displacer and killing a Cell, the rate error becoming a capacity error, capacity
  reported ahead of the rate limit, dead Cells dropping out of the count, a birth path stamping a
  constant, a second definition of `current_epoch`, the migration backfilling history into epoch 0,
  and an unanchored colony not saying so. **The structural test's first draft was too weak** — it
  scanned a 700-character window from the SQL, which stopped ~15 characters short of the parameter
  tuple, so an insert that named `born_in_epoch` and bound `None` passed it. Rewritten to scope by
  AST to the `execute` call itself, and re-checked against both birth paths.
- **Existing fixtures corrected**: `test_population.py`, `test_lifecycle.py` and
  `test_charter_properties.py` set `max_births_per_epoch=1` as filler while the field was
  unenforced. Those tests are named for the *capacity* caps and would have begun passing for the
  wrong reason, so the filler is now 1000.
- **Hand-verified through the CLI**: cap lowered to 2, two `create-cell` runs succeed, the third is
  refused with the §9.2 message, `mitosis scheduler-status` reports `births this epoch: 2/2`, and
  `advance-time --days 1` clears it — nothing died and nothing was reconfigured.
- **Migration upgrade path covered explicitly**, the blind spot every other test in this suite has:
  one test builds a colony on the pre-0017 schema from the actual `.sql` files and migrates it,
  confirming the ALTER TABLE runs against a populated `cells` and leaves history at NULL.
- Next: nothing runs the scheduler, and `max_parallel_experiments` is the last §9.2 limit still
  stored and unchecked (it needs Phase 2's experiment tracking).

### Also this session: `README.md` and `LICENSE`

Not a kernel slice, and recorded here rather than as its own entry for that reason. Every factual
claim in the README was checked against the repo instead of written from memory — test count,
migration count, expectation version, each Charter test id actually collectible by `pytest -k`, and
every linked doc present. The secrets audit was **re-run rather than inherited from PRIORITIES**:
no `.env`, `.db`, key or credential file has ever been committed, `.gitignore` covers all of them,
and every `sk-ant-…` string in the tree is a synthetic canary inside a redaction test.

The repo **stays private**, and `LICENSE` is all-rights-reserved. That is the deliberate state
rather than a missing file, which is why it says so in words: a repository with no LICENSE is
already all-rights-reserved, but a reader cannot distinguish that from an oversight. Publishing was
offered and declined, and the asymmetry is the reason it is safe to leave for later — adding a
permissive licence is one commit, while retracting one from versions people already hold is not
possible at all.
