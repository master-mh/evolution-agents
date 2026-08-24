# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, and establishable rights, 2026-07-21 through 2026-08-24):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-24 — A tick that dies leaves a record

`scheduler.liveness` + migration 0025 + `mitosis health` (ADR-042). PRIORITIES had carried
"nothing runs the scheduler" since ADR-026 — no crontab, no supervision, no restart-on-failure, no
alert. **Two of the three dissolved on inspection and the third was a different bug than the entry
described.**

### Cron already restarts it; what it cannot do is tell anyone

Restart-on-failure is cron's job and cron does it — it runs the command again next minute whether
or not the last run succeeded. That is exactly why §30.1's "avoid unnecessary frameworks" made
`tick` a command rather than a daemon, and a supervisor would only have needed its own liveness
check one level further out.

The real gap was **two invisible failures that looked identical**: nothing is running the
scheduler, and something is running it and every run dies. `scheduler_ticks` was only ever written
at the *end* of a tick, so a crash anywhere — the expiry sweeps, a guard, `run_ready_wakes`, a
provider call — left **no row at all**. A colony failing every minute for a week was
indistinguishable from one that had never been scheduled, and those need different people to fix
them.

**The fix already existed one layer down.** `tool_calls` writes `status = 'requested'` before the
external call, and migration 0019 had said why: "a crash mid-call leaves a diagnosable row rather
than a reservation with nothing explaining it." The scheduler was in the state the gateway is in.

`'crashed'` and an unfinished `'started'` stay separate facts: an exception can be caught and
described (redacted — Charter C14, since a provider error quotes the key it was rejected with),
while a SIGKILL, an OOM or a power cut writes nothing, and a row left `'started'` with a NULL
`finished_at_utc` is the signal that survives the process dying between statements.

### The alert leaves the process as an exit code

`mitosis health` exits **0 / 1 / 2** — §30.1 applied to alerting exactly as it was applied to
scheduling. Any monitor that exists can read an exit code; none of them need to know what MITOSIS
is. `1` is infrastructure, `2` is the colony running and deliberately stopped for a person.

**A deliberate halt is not an outage, and that split is the half worth arguing.** Vacation mode and
`real_spending` disabled are fail-safes working, and they clear when the operator returns — paging
someone on holiday because the pause they configured engaged is how a fail-safe gets switched off.
§23.3's metabolic alarm is the exception: it holds *until acknowledged*, so it is the one halt
genuinely waiting for a person.

### The default deadline is in epochs, and checking why turned a guess into a policy

The tempting default is wall-clock silence, and it rests on a premise: that a late expiry sweep
leaves stale authority usable. **It does not.** ADR-039 established that all three executors
(`tools`, `external_actions`, `promotion`) refuse an expired grant on their own terms — the sweep
regenerates the wake, it does not enforce the refusal. So sweep latency is a responsiveness cost,
not a safety hole. What an outage actually costs is *work*, and wakes are keyed
`epoch:{n}:cell:{id}`, so any tick inside an epoch does that epoch's work. Two epochs behind means
an epoch's wakes were skipped. An operator who wants wall-clock responsiveness sets
`tick_expected_every_seconds`.

### Verification

- **887 tests passing** (18 new, 0 removed; up from 869). **Golden run untouched** — `scheduler_
  ticks` is not in the semantic snapshot and no new audit event fires in the scenario, so this
  slice moves no expectation and no money.
- **Teeth-checked thirteen ways**, each failing its named test: the row written only at the end (the
  state before this slice), an unredacted crash detail, a crash-recorder masking the original
  exception, `finished_at_utc` never set, vacation reported as an outage, the alarm sharing the
  infrastructure exit code, the alarm outranking a stopped scheduler, an in-flight tick counted as
  a failure, wall-clock ordering, a wall-clock default deadline, `never_ran` reading healthy, and a
  crashed tick not recognised at all, and a crash row claiming zero spend. **One MISSed and the
  test was at fault** — it asserted on `.year`, which cannot tell nine days ago from now. The exact
  shape the workflow note warns about: an assertion that cannot distinguish the two outcomes. A
  second test failed for the same family of reason — it posted an unregistered `transaction_type`,
  so the breaker's spend window never saw it and the fixture could not have proved anything.
- **Hand-verified on live colonies**, all five verdicts and all three exit codes: never-ran (1),
  healthy (0), a crash with an API key in the message redacted to `[redacted]` (1), a killed
  process left as an unfinished `started` row (1), silence past a configured cadence (1), and a
  metabolic alarm with the scheduler alive (2).
- **A self-review caught one more:** a crashed tick recorded `spend 0 → 0` regardless of what it
  had spent — a *false* statement in the log an operator reads at 3am, not merely a missing one.
  `spend_before` is now captured when the row is opened, which is equivalent to capturing it after
  the sweeps (ADR-040: expiry "has no ledger consequence at all") and survives a crash before the
  body computes anything.
- Two bugs surfaced only by running it. The generated crontab line was **unquoted**, and this repo
  lives at a path with a space in it — it would have failed in a way cron reports to nobody, which
  is precisely the failure `health` exists to make visible. And ticks were ordered by
  `started_at_utc`, which moves backwards under NTP correction or a VM restore; now `rowid`, the
  same reasoning as ADR-041.
- Next: the nearest open work is Charter C13, still the one clause with no `charter_*` test and
  still blocked on Phase 6's shadow economy — so the front is really Phase 2's experiment tracking,
  which also unblocks `max_parallel_experiments` and the coroner report's empty `experiment_ids`.
