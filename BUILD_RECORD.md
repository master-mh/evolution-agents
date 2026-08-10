# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, and death criteria, 2026-07-21 through 2026-08-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-06 — §9.3 displacement: a birth at capacity can evict instead of wait

§9.3 says a birth needs "an available population slot **or a successful displacement**". Only the
first half existed: a birth denied at carrying capacity stayed denied, because the objective
criteria that identify a displaceable Cell had not been built. Last slice's
`death.is_objectively_failing` was the predicate §9.3 was waiting on, and this is the other side
of that seam.

**Almost every decision here is about what displacement must not be able to do** (ADR-024).

- **§9.3 / ADR-009: a proposed child's forecast can never trigger a kill.** So
  `population.Displacer.displace` takes the connection, which cap binds, and an exclusion set —
  and nothing whatsoever about the child. There is no forecast in scope to game. ADR-009 claims
  this surface is closed "by construction"; a construction argument that relies on a reviewer
  noticing a misuse is not one, so the guarantee is in the signature and pinned by a test that
  reads the signature. The *link* is not lost: the birth's audit event records which Cell it
  displaced, so traceability runs both ways while selection depends on none of it.
- **§10.2 forbids scalar collapse**, which reaches further than it first appears. Choosing among
  several eligible candidates is where a fitness ranking would sneak back in as "take the worst
  one". Every candidate already independently meets an objective criterion, so any is a valid
  target; order is birth order, for deterministic replay (§26), and the CLI says so on screen.
- **Displacement is opt-in per birth.** Without a `displacer` the behaviour is unchanged: denial.
  The alternative — displacing whenever a birth hits a cap — silently converts every capacity
  refusal in the kernel into a death. Same posture `reap` takes by defaulting to a dry run.
- **At most one Cell, with the caps re-checked afterwards.** A displacer that frees the wrong kind
  of slot produces a denied birth, never a second kill chasing the slot it missed.

### What landed

- **`displacement.py`** — `ObjectiveDisplacer` plus a read-only `candidates()`. Three exclusions
  beyond "meets a criterion", each load-bearing: **never the parent** (it funds the child, so
  killing it first moves money out of a dead Cell, and a lineage buying room by killing its own
  root is the incentive §9.4 exists to suppress); **never a Cell with committed funds** (a
  reservation is open and `kill()` sweeps nothing); **never on negative EV** (§10.5 admits that
  only with a concurring independent Auditor — `DISPLACEABLE_CRITERIA` excludes it explicitly
  rather than relying on `death.findings` happening not to return it today).
- **`lifecycle._kill_locked`** — the kill split into ADR-022's core-plus-wrapper shape, so eviction
  and birth are one `BEGIN IMMEDIATE`. A crash between them would otherwise leave a Cell dead and
  its slot unfilled: a death that bought nothing, and one no invariant would report, since
  conservation and the hash chain stay green through it.
- **Which cap binds decides what a target must be.** Only killing an `alive` Cell frees an *active*
  slot; any living Cell frees a *living* one. Evicting a dormant Cell to relieve an active-cap
  breach is a death that buys nothing, so `require_active` is derived from the actual breach.
- **CLI** — `--displace` on `create-cell` and `reproduce`, and `displacement-candidates`, which is
  read-only and is the look-before-you-evict command.
- The coroner report's cause of death carries **both** the displacement and the objective criterion
  the Cell already met, with its evidence — a death is never traceable only to "something needed
  the slot".

### The trap caught while building it

**The lineage cap has to be checked *after* displacement.** Eviction shrinks the living population,
which *raises* every surviving lineage's share — so checking first licences the birth against a
population that no longer exists by the time the child is inserted, and the colony ends up
violating §9.4 having killed a Cell to get there. The ordering is load-bearing at ordinary numbers,
not just in principle: with cap 0.5 and three living Cells, the projection is 2/4 = 0.50 before and
2/3 = 0.67 after. Pinned by
`test_the_lineage_cap_is_checked_against_the_population_displacement_leaves`, which also asserts
the eviction rolls back with the failed birth.

### Verification

- **520 tests passing** (19 new, 0 removed; up from 501). Golden-run hash unchanged.
- **Teeth-checked seven ways**, one per guarantee: removing the parent exclusion, the
  committed-funds guard, the `require_active` derivation, the negative-EV exclusion, or the
  post-displacement cap re-check each fails its named test; adding a `child_forecast` parameter to
  the seam fails the structural test; swapping the lineage-cap ordering fails the test above.
- **One test was passing for the wrong reason and the teeth check caught it.** The mid-operation
  test originally used a Cell at zero cash with funds committed — but `_budget_exhausted` already
  refuses to fire while funds are committed, so `death` was doing the work and the new guard could
  be deleted with everything still green. Rebuilt around a Cell that is genuinely failing
  (dominated by a near-duplicate) *and* mid-call, which is the only shape where the guard is load-
  bearing.
- **A methodology note worth keeping:** the first teeth run reported a false result and then left a
  restored-but-failing tree. Cause was Python bytecode caching, not the code — the lineage
  reordering is size-preserving, and the mutate/restore cycle completed inside one second, so the
  `(mtime, size)` pyc check accepted bytecode compiled from the *broken* source. Teeth checks that
  edit source in place must run with `PYTHONDONTWRITEBYTECODE=1` or clear `__pycache__`.
- **Hand-verified end to end** on a file-backed colony: `displacement-candidates` named the drained
  Cell with its evidence, a birth without `--displace` was refused (`2/2 living, 2/2 active`), the
  same birth with `--displace` succeeded and printed what it displaced, and the coroner report
  recorded `displacement: ... while already meeting budget_exhausted: {'cash': 0, 'committed': 0}`
  with `spend_by_book {'USD_SIM': 500}`. Hash chain and conservation green throughout; the dead
  Cell reports no findings (Charter C8 inert).
- Not committed — reporting for review first.
- Next: the agent loop is still the missing subsystem. Worth being plain that **displacement
  selects nothing on its own either** — it fires only when a caller passes `--displace`, and no
  Cell yet acts, earns, or reproduces without a human driving it.
