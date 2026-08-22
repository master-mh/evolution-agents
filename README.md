# MITOSIS

An evolutionary operating system for autonomous economic agents.

Cells are born, spend, earn, predict, deliberate and die inside an immutable colony kernel. The
kernel enforces the money and safety guarantees the Cells cannot violate — conservation, spend caps,
carrying capacity, tamper-evident history — and everything else is left to evolution.

The colony can spend real money. Most of this repository exists to make sure it does so only when a
human said it could.

---

## Status

Phase 1 of ten. The kernel is real and the core loop closes: a Cell thinks, proposes, is reviewed
by a human, is allocated capital, and is measured on what it forecast. Nothing runs unattended
without a human having enabled it, and the ladder that would remove those humans is deliberately
not climbed.

| | |
|---|---|
| Tests | 671, including Hypothesis property tests for the Colony Charter |
| Golden-run replay | expectation version 11, verified in CI |
| Schema | 17 numbered migrations |
| Python | 3.11+ |
| Real money spent to date | 0.19¢, once, deliberately |

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

```bash
.venv/bin/mitosis --db colony.db init
```

Nothing above touches the network or costs anything. The default provider is a deterministic mock;
a local Ollama model is priced at zero; the paid provider is an optional dependency and the one CLI
verb that can bill you requires `--yes-spend-real-money`.

---

## The specification is the source of truth

[`docs/SPEC.md`](docs/SPEC.md) is ~1,300 normative lines written and reviewed before any code
existed. Where the code and the spec disagree, the spec wins and the code is wrong.

This matters more than it usually does, because **the spec repeatedly forbids the obvious design**:

- **§10.5** forbids compute-fitness-and-cull-the-bottom — "estimated negative EV *alone* must not
  kill a Cell" without strong evidence *and* an independent Auditor concurring. So death happens on
  realised facts, and killing on an estimate is a separately guarded entry point.
- **§10.2** forbids collapsing fitness into one scalar. Domination is therefore **Pareto** across
  dimensions, which reaches further than it looks — it also forbids ranking eviction candidates by
  "the worst one".
- **§8.5** names Brier and log score, both defined only over binary outcomes. So the prediction
  register takes threshold claims ("revenue >= 50"), never point estimates.
- **§0.3** — "a Cell may *explain* a result; it may never *define* the canonical result" — is why
  a Cell's proposal has no field for what it earned or achieved, enforced by a test on the schema.
- **§23.5** — the approval queue "will be optimised against by Cells" — is why a Cell's claimed risk
  tier and the kernel's assessed tier are separate values, folded with `max`. A Cell may raise its
  own risk tier and never lower it.

Every one of those changed the implementation. `CLAUDE.md` records the habit that produced them:
read the normative section *before* designing, never afterwards.

---

## The Colony Charter

[`docs/SPEC.md`](docs/SPEC.md) §0.1 is a traceability matrix, not a manifesto. Fifteen clauses,
each mapped to a named property test that must be individually collectible:

```bash
.venv/bin/python -m pytest -k charter_conservation_per_book -q
```

C1 ledger balances per book · C2 capital is conserved · C3 balances are derived, never cached ·
C4 no Cell overspends · C5 real-spend caps hold under concurrency · C6 handlers are idempotent
under at-least-once redelivery · C7 a crash at reserve/execute/settle recovers with no double-spend ·
C8 dead Cells cannot act · C9 birth requires carrying-capacity permission · C10 every lifecycle
transition is audited · C11 canonical forms — integer minor units, UTC, hashed genomes ·
C15 no Cell can modify the kernel. (C12–C14 land with the phases that make them reachable.)

Breaking one of these tests is by definition a change to the kernel's guarantees.

---

## How it is built

**Three books, never bridged.** `USD_REAL`, `USD_SIM`, `RESOURCE`. Conservation holds per book and
no transaction crosses one, because §2.4 forbids an implicit exchange-rate bridge — a model call's
cost is *mirrored* into the simulated book, never converted. All money is integer minor units.
Balances are always derived from ledger entries and never cached.

**Tamper-evident history.** The ledger and the prediction register are both hash-chained: editing
any row invalidates every row after it. History is never corrected by editing it — a correction is
a new, signed adjustment.

**A ladder that is climbed deliberately.** §25.1 defines nine rungs from flight simulator to bounded
autonomy. The colony currently sits at rung 7, "tiny capped live experiment": two separate humans
stand in every allocation of capital, and structural tests forbid the scheduler from reaching the
allocation path at all. Each step up has cost an explicit, argued edit to a named test — which is
what those tests are for.

**Deterministic replay.** A fixed scenario is driven through the kernel and reduced to a semantic
snapshot, then hashed. Changing what the colony does economically requires regenerating the
expectations, bumping a version, and writing a migration note that explains every section of the
diff. An unexplained diff means behaviour drifted.

```bash
.venv/bin/mitosis verify-golden-run
```

---

## Repository map

| Path | What it holds |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | The normative specification (v0.2) |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Architecture decision records — each one names what it *displaced*, not just what was chosen |
| [`docs/STATE_MACHINES.md`](docs/STATE_MACHINES.md) | Cell lifecycle and reservation FSMs |
| [`docs/EVENT_SEMANTICS.md`](docs/EVENT_SEMANTICS.md) | Delivery, ordering, poison-event handling |
| [`src/mitosis/`](src/mitosis/) | The kernel |
| [`tests/`](tests/) | Tests named for the property they defend, citing the clause that requires it |
| [`PRIORITIES.md`](PRIORITIES.md) | What is done, what is next, and what is knowingly missing |
| [`BUILD_RECORD.md`](BUILD_RECORD.md) | The current slice, in detail — earlier ones are archived |
| [`FUTURE_BUILD_HOOKS.md`](FUTURE_BUILD_HOOKS.md) | Append-only parking lot for deferred calls |

`PRIORITIES.md` and `FUTURE_BUILD_HOOKS.md` are worth reading before the code. Both are candid
about what does not work yet, which is more of the system than what does.

---

## Spending real money

One CLI verb can bill you, and it takes a flag saying so:

```bash
.venv/bin/mitosis --db colony.db call-model --cell <id> --prompt "..." --provider anthropic --yes-spend-real-money
```

Before that is reachable, a global circuit breaker enforces per-request, concurrent-reserved,
hourly, daily and ~30-day caps on `USD_REAL` — and any new transaction type that could touch
external spend must be registered, or a test fails rather than the breaker going quietly blind.
Separately, §27.1's `autonomy.real_spending` ships disabled, an absent operator stops the colony
spending (but not thinking), and a metabolic alarm watches the *derivative* of the burn rate and
halts scheduling "even if every individual cap is satisfied".

The free paths — the mock provider and a local Ollama model — are the default, and the entire test
suite and golden run pass without the paid dependency installed at all.

---

## Licence

All rights reserved — see [`LICENSE`](LICENSE). MITOSIS is a personal research project and is not
published under an open-source licence. That is the deliberate state rather than an oversight,
which is why the file says so explicitly: a repository with no LICENSE is already
all-rights-reserved, but a reader cannot tell that from someone having forgotten.

Adding a permissive licence later is a one-commit change. Removing one is not, since terms cannot
be retracted from versions people already hold — so it waits until it is meant.
