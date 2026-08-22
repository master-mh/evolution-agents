# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, and the dead-Cell estate, 2026-07-21 through 2026-08-22):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-22 — Rung 7: the core loop closes, and an approval finally does something

`promotion.py` + migration 0016 (ADR-029). §31 states the colony's core loop in one line —
"... -> allocate capital -> scale, mutate, collaborate, sleep, or die" — and until now MITOSIS
could do everything on both sides of that arrow and nothing at the arrow itself.

### Two sockets the spec left open, neither invented here

`promotion_pool` has been in §31's required account list since Phase 1, described in `accounts.py`
as "capital held for §25 promotion — redistributed, never consumed", with nothing ever moving
through it. §17.2 lists "capital allocation" among its wake reasons and
`deliberation.WAKE_CAPITAL_ALLOCATION` has been defined and unemitted since the agent loop landed.
A Cell woken *because* it has just been funded is exactly the event both were reserved for. The
slice is mostly a matter of connecting things the spec had already named.

### What makes this rung 7 and not rung 9

§25.1 puts "tiny capped live experiment" one step past "human-reviewed prototype". **Two humans
still stand in every allocation** — one approves the request under §23.1, one runs
`mitosis allocate` — and a structural test forbids `scheduler.py` importing this module at all, so
an allocation that fires on a timer costs a named test failure. What changed is only that an
approval now *does* something.

The pool is the other half of that. It has to be filled deliberately by an operator, which gives a
single number bounding everything this path can ever allocate — a ceiling that holds whether or not
anyone is watching the queue, and one no Cell can raise.

### The rung-6 guarantee was deliberately loosened, which is the point of it

ADR-027 shipped `test_no_kernel_path_consumes_a_grant` so that climbing the ladder would cost an
explicit edit to a named guarantee rather than slipping in as a plausible commit. Landing this
slice required that edit. The replacement, `test_only_the_promotion_module_consumes_a_grant`, still
forbids the *next* unargued step and names the scheduler specifically.

### Verification

- **636 tests passing** (15 new, 0 removed; up from 621).
- **Golden expectation 8 → 9**: the scenario now runs the whole loop — deliberate a spend request,
  queue it under §23, approve it, allocate at rung 7, wake the Cell. Every line of the diff traces
  to that one block and the note explains each. **The allocation deliberately runs on a USD_SIM
  Cell**: the scenario's explorer is USD_REAL and `promotion.allocate` refuses it without §27.1's
  `autonomy.real_spending`, which the scenario must never enable. `external_expense` is unchanged
  in every book, and the new USD_REAL movement is a `seed_bank -> cell cash` transfer whose model
  call *released* rather than settled — the tell that no real money moved.
- **Teeth-checked nine ways**, each failing its named test: allocating a grant twice, allocating an
  expired grant, allocating for a non-spend proposal, ignoring the pool ceiling, funding a dead or
  quarantined Cell, moving USD_REAL without the autonomy flag, allocating with no stated reason,
  not waking the Cell, and letting the scheduler import the promotion path.
- **Hand-verified end to end on a live colony**: pool funded 500, Cell proposed a 60-unit spend
  request claiming MEDIUM (kernel assessed **HIGH** with an `understated_risk` signal), approved,
  allocated — pool 500 → 440, Cell +60, promotion recorded at rung 7 with liability and transfer
  degradation both reported unavailable. The Cell then woke under "capital allocation". A second
  allocation of the same grant was refused. Conservation in both books and the hash chain green,
  `external_expense` still 0.
- Next: nothing measures whether an allocation *worked* — the promotion's predictions resolve
  through the register, but no path closes back onto rung 8. Nothing still runs the scheduler, and
  `max_births_per_epoch` is checkable and unchecked.
