# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, and the prediction register, 2026-07-21 through 2026-08-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-05 — Death criteria: the evolutionary loop closes

Reproduction has worked since the lineage slice. What was missing was any principled reason for a
Cell to stop — so a colony could grow but never select. This is the other half, and with it the
loop is closed: birth, spend, earn, predict, die.

**Reading §10.5 first changed the design substantially, and the spec forbids what "selection on
fitness" would naturally mean.**

- **§10.5: "Estimated negative EV *alone* must not kill a Cell"** unless evidence is sufficiently
  strong *and* an independent Auditor or evaluator concurs. So compute-fitness-and-cull-the-bottom
  — the obvious implementation, and the one the previous three slices might look like they were
  building toward — is exactly what the spec prohibits. An estimate is not evidence, and a colony
  that culls on estimates selects for Cells that look good to the estimator. `reap` therefore kills
  only on realised facts, and negative EV is a separate entry point that structurally cannot be
  reached without a concurring Auditor.
- **§10.2: "Do not collapse all dimensions into one scalar."** So domination is **Pareto**
  domination — at least as good on every measured dimension, strictly better on one — rather than a
  ranking on a weighted sum. A Cell that earns more but predicts worse is *not* dominated. That is
  the constraint doing real work rather than being cited.
- **§10.3: Explorers "need no immediate revenue."** Handled without a special case: comparisons are
  restricted to near-duplicates (same genome hash, which in this kernel is effectively same-type per
  ADR-018/019), so an Explorer is only ever compared with another Explorer.
- **§9.3: "A proposed child's forecast can never trigger a kill."** Every input to `findings` comes
  from the ledger or the resolved prediction register. Nothing forecasts.

### What landed

- **`death.py`.** `DeathCriterion` covers all of §10.5's criteria — including the unimplementable
  ones, so a coroner report's `cause_of_death` uses one vocabulary from the start and the gap is
  visible in the type rather than only in prose. `findings()` returns the criteria a Cell currently
  meets *with the realised evidence*, which reaches the coroner report, so a death always carries
  the numbers that caused it. `reap()` is **dry-run by default**: a death is irreversible, files a
  coroner report, and Charter C8 makes the Cell permanently inert, so the first time a colony can
  end its own Cells is not the moment to discover a criterion was too eager.
- **Two criteria implemented, and the honest list of what is not.** `budget_exhausted` (holds
  nothing, nothing pending) and `dominated_by_near_duplicate` (Pareto, realised). Not implemented:
  `failed_validation_gates` and `evidence_not_reproducible` need experiment tracking (Phase 2);
  `policy_violation` needs §31's `policy_violations` table, and inferring it from a quarantine
  reason would be guessing, since `quarantine` takes free text and is also used for poison events;
  `displacement` is §9.3's own slice — **which this unblocks**, via `is_objectively_failing`, the
  predicate §9.3 was waiting on.
- **`kill_for_negative_ev` is the guarded path**, and its independence checks are its substance: the
  auditor cannot be the subject, must be alive, and must be an auditor or immune Cell (§10.4). The
  concurrence is written to the audit trail and the auditor's id into the coroner report, so a death
  on an estimate can always be traced to who agreed to it.
- **A Cell mid-operation is never exhausted.** Zero cash with funds committed means a call is in
  flight; killing then would strand its reservation.
- **CLI:** `reap` (dry-run unless `--execute`) and `cell-fitness`, which prints revenue, spend, net
  contribution and calibration side by side — deliberately not a score, per §10.2.

### A trap caught while writing it

Domination on net contribution alone makes an **idle** Cell — spent nothing, earned nothing, net
zero — dominate one that invested and has not yet returned. That selects for doing nothing, which in
an evolutionary colony is the failure mode that quietly ends the experiment while every invariant
stays green. Fixed with `_has_realised_record`: a Cell with no realised record is not superior, it
is unmeasured. Pinned by `test_an_idle_cell_does_not_dominate_one_that_invested`, and the teeth
check confirms removing the gate fails it.

### Verification

- **501 tests passing** (20 new, 0 removed; up from 481). Golden-run hash unchanged — correct, since
  the golden scenario contains no Cell meeting an objective criterion and `reap` is never called;
  a changed hash would have meant death criteria firing somewhere they should not.
- **Teeth-checked four ways**, one per constitutional constraint: making negative EV automatic fails
  `test_negative_ev_is_never_reachable_from_reap`; removing the idle gate fails the idle-domination
  test; collapsing calibration out of the comparison (a scalar collapse, §10.2) fails
  `test_domination_requires_being_better_on_every_dimension`; allowing self-concurrence fails the
  own-death test.
- **The most important test is `test_losing_money_is_not_a_death_criterion`.** A Cell that spent 600
  and earned 100 survives, because §10.5 does not make that fatal. Breaking it would cull on
  estimates and nothing would report it — the colony would simply stop exploring.
- **Hand-verified end to end** on a scratch colony: drained a Cell, `reap` reported it without
  killing, `reap --execute` killed it, and the coroner report recorded both the criterion and its
  evidence (`budget_exhausted: {'book': 'USD_SIM', 'cash': 0, 'committed': 0}`) with
  `spend_by_book` reading `{"USD_SIM": 500}` — the function fixed two slices ago now feeding a real
  death. On the live colony, `cell-fitness` reads 75 revenue / 0 spend / mean Brier 0.0563 and
  `reap` correctly finds nothing.
- Not yet committed — reporting for review first.
- Next: §9.3 displacement is now unblocked and is the natural follow-on — a birth denied at capacity
  can evict an objectively-failing Cell rather than simply waiting. Beyond that the agent loop is
  still the missing subsystem, and it is worth being plain that **nothing here selects on its own**:
  `reap` must be called, and no Cell yet acts, predicts, or earns without a human driving it.
