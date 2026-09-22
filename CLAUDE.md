# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# MITOSIS (Evolution Agents)

An evolutionary "operating system" for autonomous economic agents ("Cells") running under an
immutable colony kernel. Cells are born, spend, earn, predict, deliberate, and die; the kernel
enforces the money and safety guarantees they cannot violate.

`docs/SPEC.md` (~1,300 lines, v0.2) is the **normative** specification. The code implements it;
where they disagree, the spec wins and the code is wrong.

---

## The most important thing to know

**SPEC.md repeatedly forbids the obvious design, and reading the normative section *first* has
changed the implementation every time it mattered.** This is not a style preference — it is the
single highest-value habit in this repo. Some precedents:

- **§10.5** forbids compute-fitness-and-cull-the-bottom ("estimated negative EV *alone* must not
  kill a Cell" without strong evidence *and* an independent Auditor concurring). So `death.py`
  kills only on realised facts, and negative-EV death is a separately guarded entry point.
- **§10.2** forbids collapsing fitness into one scalar. So domination is **Pareto** across
  dimensions — and this reaches further than it looks: it also forbids ranking displacement
  candidates by "the worst one" (`displacement.py`).
- **§8.5** names Brier and log score, both defined only over binary outcomes. So the prediction
  register takes threshold claims ("revenue >= 50"), never point estimates.
- **§0.3** — "a Cell may *explain* a result; it may never *define* the canonical result" — is why
  the proposal schema has no field for what a Cell earned or achieved (`proposal.py`).
- **§25.1**'s promotion ladder is why the agent loop proposes but cannot act — and why a Cell's
  proposed experiment gets its rung from `promotions` rather than from the proposal: a field a Cell
  can fill is a field it will optimise (§23.5), so the schema gives the answer nowhere to live
  (`experiment_grants.py`).
- **§0.2**'s two-column table is load-bearing, not scene-setting. "Experiments" sits in the
  *mutable Cell* column, which is why the kernel gates an experiment's slot and rung and has no
  opinion whatever on its hypothesis.
- **§23.3 regenerates expired *actions*** — so `ProposalKind.STRATEGY` gets no consumer and no
  regeneration wake: approving a statement *is* the act (`proposal.STATEMENT_KINDS`). A dead-looking
  socket is not always a missing feature; sometimes the feature is a written-down refusal plus the
  consequence nobody had supplied (ADR-046).
- **§16.3** makes "customer identity" non-inheritable, so the external-action registry stores a
  salted *hash* of a counterparty and never the counterparty — a `customers` table is the obvious
  design and the one the clause warns about (`channel_registry.py`). Dedupe needs equality, not
  identity, so everything §21.2 asks still works.
- **§2.5** ("Balances are derived") has now refused two tables and one column: no
  `experiment_results` despite §31 listing it, and no `resource_usage.experiment_id` despite four
  places in this repo scheduling it as the next slice. Before adding a column that *identifies*
  something, check whether an existing NOT NULL foreign key already reaches it — a second answer to
  a question another table already owns is the same trap as a cached balance (ADR-043, ADR-044).
- **The layering rule is about Python; a constraint has no layer.** Four places scheduled an injected
  seam to validate `experiment_id`, each reasoning correctly that `ledger`/`reservations`/`prediction`
  sit *below* `experiments` — and a foreign key sits below all of them, binds callers that never heard
  of the seam, and has no default that skips the check. Before building a seam to enforce something,
  ask whether the schema can make it unrepresentable instead. Then check the migration against the
  *operation*, not the statement: a violating row that `UPDATE`s fine can still be unsettleable,
  because the real exit path writes a child row (ADR-047).

Before designing a slice, `grep -n` SPEC.md for the section and read that range. **Never read
SPEC.md wholesale** — it is large, and the relevant slice is usually 20 lines.

---

## Commands

The venv is Python 3.11. The system `python3` is 3.9 and will fail — always use `.venv/bin/`.

```bash
.venv/bin/python -m pytest -q
```

```bash
.venv/bin/python -m pytest tests/test_deliberation.py -k test_a_dead_cell_cannot_deliberate -q
```

Golden-run replay (also run in CI; see "Golden run" below):

```bash
.venv/bin/mitosis verify-golden-run
```

The CLI is a console script (`mitosis`), argparse-based, and takes `--db` before the verb:

```bash
.venv/bin/mitosis --db /tmp/colony.db init
```

There is no formatter configured. A narrow Ruff gate checks runtime-defect classes only —
undefined names, syntax-shaped errors — not general style; a broad run reports ~339 findings,
mostly import ordering and modernisation suggestions, deliberately not chased in one commit:

```bash
.venv/bin/ruff check .
```

```bash
.venv/bin/python scripts/check_docs_facts.py
```

CI (`.github/workflows/ci.yml`) runs the suite, the golden run, the docs-facts check, and the lint
gate on every push/PR to `main`.

**`anthropic` is an optional dependency on purpose** — the kernel, the full suite, and the golden
run all work without it. CI installs `.[dev]` only, so CI reports one extra skip versus a local
install that has it.

**`langgraph` and `langsmith` are optional too** (extras `langgraph`, `tracing`; ADR-103, ADR-104), but
`dev` includes `langgraph`, so CI runs the `self_critique_loop` and tracing tests. LangGraph owns that
structure's control flow only — every call still goes through `_workflow_call` and the gateway, and
`workflow_graph.py` must import nothing from `mitosis`. **Tracing is off unless both
`LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` are set**; `tests/conftest.py` strips them for every
test, and the golden run and sealed simulator runs are never traced.

**`dashboard.py` must stay read-only** (ADR-105): it opens `mode=ro`, never migrates, escapes every
value and ships no JavaScript. A new panel reads through an existing kernel reader, or a plain `SELECT`
where none exists — never a write, and never `connect_and_migrate`.

---

## Architecture

### Layering and the dependency direction

Roughly: `money`/`db`/`models`/`ids` → `ledger`/`accounts` → `reservations`/`resource_metering` →
`lifecycle`/`population` → `lineage`/`death`/`displacement` → `gateway`/`pricing`/`providers` →
`deliberation`/`context`/`proposal`.

When a lower layer needs behaviour from a higher one, **the dependency is inverted with an
injected seam rather than an import**. Established examples: `sweeper.ExternalOperationChecker`
(implemented by `gateway.GatewayOperationChecker`) and `population.Displacer` (implemented by
`displacement.ObjectiveDisplacer`). Follow this pattern rather than adding a back-edge or a
function-local import.

The other established move is a **registry/executor split**: `tool_registry` / `tools` and
`channel_registry` / `external_actions`. Everything that *reads or refuses* sits low enough for
`context` to import; the part that *consumes a grant* sits above `approval`. In both cases the
layering cut and a safety boundary want the same line — `context` can list capabilities and read
results, and has no path to running one.

Some seams are shaped by a *constraint*, not just by layering: `population.Displacer` takes no
information about the child being born, because §9.3 forbids a child's forecast triggering a kill
and a signature that cannot see a forecast cannot consult one.

### Money: three books, never bridged

`USD_REAL`, `USD_SIM`, `RESOURCE`. Conservation holds **per book**; no transaction crosses books
(§2.4 forbids an implicit exchange-rate bridge — model cost is *mirrored* into USD_SIM, not
converted). All money is integer minor units; balances are always derived from ledger entries and
never cached.

`accounts.py` draws the distinction §31's account list does not: **consumption vs capital
movement** (`SPEND_DESTINATIONS` vs `CAPITAL_ACCOUNTS`), *not* internal vs external. Adding a
fixed account forces that classification — `unclassified_accounts()` and its test fail otherwise.

Any new `transaction_type` that touches `external_expense` in USD_REAL must be registered in
`_REAL_SPEND_TRANSACTION_TYPES`, or the circuit breaker goes blind to it.
`tests/test_real_spend_registration.py` attacks this from three angles and will tell you.

### Transactions: the `_*_locked` core-plus-wrapper split

Most write operations pair a `_foo_locked(conn, ...)` core (no `BEGIN`, no `COMMIT`) with a thin
`foo(conn, ...)` wrapper that opens `BEGIN IMMEDIATE` and commits. This lets one module fold
another's operation into a single atomic step — `gateway` composes `reservations`,
`resource_metering` and `ledger` cores; `displacement` folds `lifecycle._kill_locked` into a
birth; `deliberation` folds `prediction._register_locked` into a proposal.

**This is a live footgun:** calling a `_*_locked` core outside a transaction silently autocommits
and quietly undoes the atomicity guarantee, with no test failure.

Validation belongs **inside** the write lock, not before it. Check-then-lock is a bug class that
was fixed across the kernel once already; re-read the Cell/reservation state inside the
transaction rather than trusting a value read before it.

### Idempotency and crash safety

Every externally-visible operation is idempotent on a caller-supplied key. That is what carries
Charter C6 under at-least-once event redelivery — and in one place it carries it *instead of*
transactional atomicity: a wake cannot run inside `events.process_event`'s handler transaction,
because that contract forbids the handler committing while ADR-022 requires the gateway's
reservation to commit *before* the external call. Expect that collision anywhere an external call
meets the event system.

### Tamper-evidence

`ledger_transactions` and `prediction_register` are both **hash-chained**: editing any row
invalidates every row after it. `verify_chain()` on each. Never edit history to correct
something — post a new, signed adjustment (§3.6).

### Schema

Plain numbered `.sql` migrations in `src/mitosis/migrations/`, applied in order and tracked in
`schema_migrations`. **Never edit a shipped migration** — a schema change is a new file.

---

## Repo conventions

### The tracking files

- `PRIORITIES.md` — `Now` / `Next` / `Later`. The top unchecked item is the front.
- `BUILD_RECORD.md` — **only the current entry**; older entries move to
  `docs/BUILD_RECORD_ARCHIVE.md` when superseded, so the live file stays readable in full.
- `docs/DECISIONS.md` — ADRs. A slice with a real decision between alternatives adds one, and
  records *what it displaced*, not just what was chosen.
- `FUTURE_BUILD_HOOKS.md` — append-only parking lot for suggestions, deferred calls, and "out of
  scope" notes that come up mid-session, so they don't die in a throwaway plan file. **Not a
  roadmap.** Append in real time; `/wrap` sweeps for anything missed.

`/prime` (in `.claude/commands/`) is the warm-start after a context clear and reads these itself —
this project has no SessionStart hook.

### The Charter

`docs/SPEC.md` §0.1 is a traceability matrix: every clause C1–C15 maps to a named property test
that must be individually collectible by `pytest -k <id>`. They live in
`tests/test_charter_properties.py` (Hypothesis-backed, including a stateful crash-recovery
machine). Breaking one is by definition a change to the kernel's guarantees.

### Golden run

`golden.py` drives a fixed scenario and reduces it to a **semantic snapshot** (volatile ids,
timestamps and hash digests excluded) which is then hashed. Comparison is semantic invariants
*plus* the hash — ADR-017 explains why both matter.

Changing the expectations is a deliberate, reviewed act (Amendment A12):
`mitosis verify-golden-run --update-expectations`, bump `EXPECTATION_VERSION`, and **write the
migration note explaining every section of the diff**. An unexplained diff means behaviour drifted.
A golden run must never move USD_REAL — the mock provider is priced at zero, and a replay that
started billing someone would be the worst regression this file could miss.

### Testing style

Tests are named for the *property* they defend, and their docstrings cite the spec clause and say
what breaks if the property fails. Structural guarantees get structural tests (an AST walk, an
`inspect.signature` assertion) rather than a behavioural approximation.

**Teeth-check a new guard by reintroducing the bug and confirming a named test fails.** This has
repeatedly found tests that passed for the wrong reason — the recurring shape is a test asserting
against the very constant it is meant to bound (`<= RECENT_PROPOSALS` is satisfied by raising
`RECENT_PROPOSALS`). Two caveats:

- Never restore with `git checkout` — the working tree usually has uncommitted work. Hold the
  original in memory and write it back.
- Run with `PYTHONDONTWRITEBYTECODE=1` (or clear `__pycache__`). Size-preserving edits inside one
  second defeat Python's `(mtime, size)` pyc check, and stale bytecode from the *broken* source
  will produce a false result and a restored-but-failing tree.

`scripts/teeth_check.py` removes both caveats rather than working around them (ADR-091): each
mutation runs in its own copy of the working tree, in parallel, so nothing is ever restored, and its
verdict is `CAUGHT` only when the test fails *and* a stated `expect` string appears — an incomplete
mutation that crashes instead reports `WRONG-FAILURE`. The `teeth-checker` agent
(`.claude/agents/`) drives it.

### Working with paid providers

`call-model` is the only verb that can spend real money and is gated behind
`--yes-spend-real-money` for any paid provider. Prefer the free paths: `MockProvider`
(deterministic, no network) and `OllamaProvider` (local, priced at zero — but RESOURCE metering
still bounds it, which is the only bound left when USD_REAL is free).
