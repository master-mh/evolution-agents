# MITOSIS / Evolution Agents — Build Record Archive

Entries through slice 9 (2026-07-25, golden-run replay), moved out of the top-level
`BUILD_RECORD.md` so that file stays small enough to read in full every session (it had grown to
~42 KB / 9 slices). `BUILD_RECORD.md` keeps only the current/most-recent entry plus a pointer
here; append new slices there, and move an entry here once a newer one supersedes it as "last
landed."

## 2026-09-15 — Every *Disproved by:* pointer, run and dated (ADR-092)

Eighth of the research-driven slices; tooling, no kernel change.

### What shipped

- `scripts/check_disproved_by.py` extracts each open PRIORITIES.md entry's backticked pointer tokens
  and resolves them: CLI verbs through `check_docs_facts.cli_verbs`, files, `module.name` definitions
  by AST, tables from migrations, kernel names. It dates each resolving token with git — the commit
  introducing it against the `git blame` date of the pointer's line — and marks an entry `RE-READ`
  only when a token is newer than the pointer. `--selftest`; `--fail-on-resolved` for a stricter
  caller; it never edits the file.
- A weekly Claude Code routine to run it and adjudicate only what it flags — specified in
  `scripts/README.md`, **not created**: the create call returned HTTP 403, since claude.ai has no
  GitHub access to this private repository. (Corrected the same day; the entry first said "created
  disabled", written before the call ran.)

### Found

- **Resolution alone flagged every open entry.** Most pointers name a symbol that existed when the
  entry was written — entries narrowed or split around it on purpose. A report that flags everything
  is a report nobody reads; with dating, the answer at commit time is **0 of 9** open entries (all 9 pointers resolve).
- **Dotted tokens never date.** `git log -S death._budget_exhausted` matches nothing, because that
  dotted string never appears in source. Dotted tokens are dated by their last component and files by
  the commit that added them.
- **One stale claim, found by reading rather than by the script.** The §23.2 liability entry said its
  wrong claim was "still copied into `approval.py`'s `liability_minor_units` comment"; that comment
  had already been corrected. The sentence is gone. (The script could not have caught it: the pointer
  was right, and the stale sentence was prose around it.)

### Verification

`--selftest` passes; the live run's result is above. The routine waits on GitHub access.

## 2026-09-15 — A teeth-check runner that cannot touch the real tree (ADR-091)

Seventh of the research-driven slices; tooling, no kernel change.

### What shipped

- `scripts/teeth_check.py` takes a JSON list of mutations (`file`, `old` occurring exactly once,
  `new`, `test`, `expect`) and runs each in its own copy of the working tree — uncommitted work
  included; `.git`, `.venv`, caches and colony databases excluded — with `PYTHONDONTWRITEBYTECODE=1`
  and `PYTHONPATH` at the copy, in parallel. Verdicts: `CAUGHT`, `WRONG-FAILURE`, `MISS`, `INVALID`.
  It fails loudly if the real tree's digest changed.
- `.claude/agents/teeth-checker.md`: an agent that writes the mutation spec, runs the script and
  reports each verdict with its assertion line, carrying this repo's rules about complete mutations
  and secondary rules rescuing a mutation.
- CLAUDE.md's teeth-check section points at both.

### Found

- **`PYTHONPATH` beats the editable install** — probed with a stub package before relying on it, so
  a copy's `src/` really is what its test imports.
- **`expect` narrows a false CAUGHT; it does not remove one.** Of 17 guards checked through it this
  session, one `expect` (`AttributeError`) matched the test crashing on a missing `cache_clear` rather
  than failing on the property. Reading the assertion line caught it; the test was rewritten not to
  depend on the cache's API and re-checked.

### Verification

`tests/test_teeth_check.py` (3 tests) pins all four verdicts against a throwaway project — including
an incomplete mutation that must report `WRONG-FAILURE` — and that the real tree is never touched.
Used in anger for 17 mutations across the verbalized-sampling fix and the workflow gene.

- Next: the claim-drift checker and its weekly routine; the workflow gene; then Slice H.

## 2026-09-15 — Collusion and counterparty deception are policy violations (ADR-090, Amendment A20)

Sixth of the research-driven slices: a normative spec amendment, no code. **Flagged for the
operator's review** — it adds to what §10.5 treats as a policy violation.

### What shipped

- **Amendment A20** in SPEC.md's amendment list. Agreeing with any party outside the colony on
  prices, output, bids, territories or customers, and misrepresenting facts to any counterparty, are
  §10.5 policy violations, never strategies selection may reward.
- **§11.3**: Auditors also inspect external communications for coordination with outside parties
  and misrepresentation to counterparties.
- **§21.2**: the boundary. Coordinating sibling Cells' offers through the registry is the colony
  acting as one business — the clause exists to *prevent* sibling bidding wars — so the line is the
  colony's edge, not the Cell's.

### Why now

Selection rewards what pays. In Vending-Bench Arena (Andon Labs, write-up 2026-07-28) all three
models in one market broke price truces, and Opus 5 — cartelising in all six runs, fabricating
competitor quotes to suppliers, lying to a competitor — finished essentially tied for first. (An
earlier wording said it earned most; corrected the same day against the primary source.) Nothing enforces A20 today because no Cell has an
autonomous external channel; that is exactly when to write it, so the first such channel arrives
with the violation already named rather than argued about after a run has found it profitable.

### Not built

Detection. A keyword filter was rejected: coordination and deception are semantic, and a filter
would be a §23.5 surface that reads as enforcement it is not. The natural consumer — an Auditor
content-audit kind over `external_actions` intent and completion records — is logged in
FUTURE_BUILD_HOOKS.md.

### Verification

No code changed. `check_docs_facts.py` and the golden run are unaffected; the full suite was run on
this tree as part of the verbalized-sampling commit's verification.

- Next: the teeth-check runner, the claim-drift checker, the workflow gene; then Slice H.

## 2026-09-15 — Verbalized sampling as a genome sampling policy (ADR-089)

Fifth of the research-driven slices. "Verbalized Sampling" (arXiv 2510.01171) names a cause of mode
collapse independent of §15.1 anchoring — typicality bias in preference data — and recovers diversity
by asking for several answers with probabilities. ADR-050's baseline of ~1 idea per run of 8 wakes is
the target.

### What shipped

- `model_policy.verbalized_candidates` (1–5; absent means 1) is `model_policy`'s second occupant
  after ADR-067's temperature.
- For K > 1, `deliberation._system_prompt` swaps only the reply-format paragraph for
  `proposal.candidates_instruction(K)`. The single-reply prompt is byte-identical (SHA-256 checked),
  so every genome that declares nothing wakes as before and the golden run is unchanged.
- `proposal.parse_candidates` validates each candidate whole. `_parse_reply` picks one uniformly with
  `random.Random(f"verbalized:{wake_key}")`, so redelivery replays the same choice and no number a
  Cell writes can move it (§23.5). The token budget scales by K; the audit event records
  requested/valid/rejected counts and the chosen index, for such wakes only.
- `scripts/genomes/verbalized_1.json` and `verbalized_5.json`, twin genomes one digit apart.

### Found

- **The nested candidate format parsed 0/2 on its first live wake** — `llama3.2` flattened every
  candidate, as ADR-049 found for single replies. MockProvider cannot see this by construction. The
  flat format replaced it; the nested shape stays refused by a named test.
- **`llama3.2` cannot follow the flat format either** (no `probability` in 6 wakes, invalid JSON in
  3); `qwen2.5` parsed 2/3. The twin runs on `qwen2.5`.
- **The live measurement harness could not create a Cell for 11 days.**
  `measure_parse_compliance.py`'s genome and `scripts/genomes/loose.json` gave `model_policy` as a
  string, refused since ADR-067. Both now use `{}`.
- **The suite's flaky failures were a `git` timeout.**
  `test_a_worker_process_reproduces_the_in_process_manifest` failed once under load and passed
  alone; the next full run under the same load failed `test_the_same_seed_reproduces_the_same_manifest`
  instead, with the diff naming it exactly — `'unknown' != 'a178f18'`. `runner._code_version()` runs
  `git rev-parse` with a 5-second timeout and records `"unknown"` on timeout (confirmed with a `git`
  that sleeps 6s), so two runs of one seed could disagree about nothing but the code. It is now read
  once per process (`functools.cache`), and `batch.plan` reads it once in the parent and carries it
  to spawned workers, which have their own processes; `runner.run` takes it as an optional argument.
- **The first twin attempt was lost** to a scratchpad wipe after two control runs (no ideas@2 had
  been computed, no treatment run started). The pre-registration was re-declared unchanged and both
  arms restarted from scratch.

### Verification

31 tests in `tests/test_verbalized_sampling.py`, plus
`test_every_run_in_a_batch_names_the_code_version_read_once_by_the_plan`. Eleven teeth-checks, each
failing on its intended assertion: seven for sampling (listed in ADR-089) and three for the
code-version fix, each in an isolated copy of the tree (a worker reading `git` itself, `plan` never
reading it, the runner ignoring a passed version), plus a fourth for the per-process cache — first a
false CAUGHT, failing on a missing `cache_clear` rather than on the disagreement, until the test stopped
depending on the cache's API. Full suite, in an export of exactly this commit's tree: 1392 passed, 4 failed for the environment
alone — three source-archive tests need a git checkout, and one CLI test met a local Ollama too
busy to answer, a third outcome it did not tolerate (fixed in the next commit); golden run unchanged;
`ruff check .` and the docs-facts check clean.

- Next: the twin's result into ADR-089; the §11.3 amendment, the teeth-check runner and the
  claim-drift checker; the workflow gene; then Slice H.

## 2026-09-14 — Two measurement instruments: judge entanglement and evaluator epochs (ADR-087, ADR-088)

Fourth of the research-driven slices; scripts only, no kernel change.

### What shipped

- `scripts/judge_entanglement.py` asks whether two judges from different families fail
  independently, which §24.3 and §10.5 both assume. It scores the concreteness fixture through the
  instrument's own judge and reports joint errors against independence, error phi, the conditional
  error rate, and false concurrence — with warnings for the two shapes that make phi meaningless.
- `concreteness.py --json` and `diversity.py --json` now carry an evaluator stamp (model, weights
  digest, instrument-text hashes), and `scripts/evaluator_epoch.py` refuses to compare two results
  from different evaluator epochs — the Red Queen Gödel Machine's fixed-criteria-per-epoch rule, and
  §24.2's regime-change rule applied to the instruments.

### Found

- **The first entanglement number was forced, and nearly became the headline.** phi +0.66 and 5 joint
  errors against 1.9 expected — until the script checked for degeneracy: `llama3.2` returned `empty`
  for all 24 proposals, so its errors are the nine concrete labels and `qwen2.5`'s five misses could
  only land among them. Established instead: `llama3.2` cannot serve as a second concreteness judge;
  the pair produced no false concurrence.
- **The live measurement harness has been broken since ADR-067.** `measure_parse_compliance.py`'s
  built-in genome and `scripts/genomes/loose.json` give `model_policy` as a string, which the closed
  `model_policy` schema refuses — so setup cannot create a Cell. Fixed in the verbalized-sampling
  slice, which needs the harness.
- **Kernel precision crosses model changes** (`auditor.precision`, `content_audit.precision`) — logged.

### Verification

Both scripts' `--selftest`s pass (maths and stamp comparison, no model); `concreteness.py
--check-verifier` and `diversity.py --selftest` still pass; stamps hand-verified live with real
digests; `ruff check .` clean.

- Next: verbalized sampling (with the harness fix), the workflow gene, the §11.3 amendment, the
  teeth-check runner, the claim-drift checker; then Slice H.

## 2026-09-14 — Tools name what observes their effect (ADR-086)

Third of the research-driven slices. "Reward Hacking as Equilibrium under Finite Evaluation" (arXiv
2603.28063) proves an optimised agent under-invests in every quality dimension its evaluation does not
cover, and that coverage falls toward zero as tools are added. A tool is where such a dimension enters
the colony, and nothing tied one to §0.3's list of independent systems.

### What shipped

`ToolSpec.evaluated_by` names a key of `tool_registry.EVIDENCE_SOURCES` (§0.3's eight systems as
keys) or `OBSERVATION_ONLY`, which only a read-only tool may declare. The default is `UNDECLARED`,
and `unevaluated_tools()` — mirroring `accounts.unclassified_accounts()` — must be empty. `http_get`
declares `observation_only`.

### Worth knowing

It cannot fire on today's registry: `test_no_registered_tool_acts_on_the_world` still refuses any
acting tool. So its test runs against a constructed registry, and it is the guard an acting tool
must satisfy when that refusal is argued down.

### Verification

2 tests; three teeth-checks caught (acting tool claiming observation-only; `UNDECLARED` accepted;
`http_get` left undeclared). Full suite 1363 passed; golden unchanged; lint and docs-facts clean.

- Next: judge entanglement and evaluator epochs (measurement instruments), verbalized sampling, the
  workflow gene, the §11.3 amendment, the teeth-check runner, the claim-drift checker; then Slice H.

## 2026-09-14 — A sealed simulated run (ADR-085)

Second of the research-driven slices. Prompted by Anthropic's 2026-09-09 alignment assessment:
four incidents in which models were told they were in a simulation without internet while an
outer configuration error left real connectivity on.

### What shipped

`network_seal.py` installs one PEP 578 audit hook per process that refuses connect, bind, name
resolution, datagram sends, `http.client`/`urllib` requests and every child-process start while a
`sealed()` block is active; outside a block the hook returns on one integer test. `runner.run`
seals the whole run, founding included, and reads `git rev-parse` once before sealing (it is a child
process, and the run record and manifest previously read it twice).

### Found while building

- **A refusal escaping a provider stranded both reservations.** The provider-path test passed on
  its real assertion — nothing reached the listener — but `gateway.call_model` only caught
  `ProviderError`, so a `NetworkSealed` left the call's USD_REAL and RESOURCE reservations committed
  for the sweeper to guess about. The gateway now maps it onto the definitely-unbilled path, and
  `providers._is_execution_unknown` finds it down an exception's cause chain so an SDK wrapping it in
  a connection error cannot strand funds in `execution_unknown` either. Every other failure keeps
  the conservative default.

### Verification

8 tests: three put a real listener on loopback and require that no connection arrives from an
epoch hook, a replaced provider, or a bare gateway call; one requires a child process be refused;
three pin nesting, lifting on exception, and inertness outside a seal; one pins the SDK-wrapped
classification. (Corrected on archiving: the live entry read as 8 + 1 + 3.) Six teeth-checks, all failing on the
intended assertion (two first scored MISS by a wrong expected-text string in the checker, not by the
tests). Full suite 1361 passed; golden unchanged; lint and docs-facts clean. Not a sandbox — logged in
`FUTURE_BUILD_HOOKS.md` along with sealing the golden run.

- Next: judge entanglement, verbalized sampling, the workflow gene, the tool-evaluator guard,
  evaluator epochs, the §11.3 amendment, the teeth-check runner, the claim-drift checker; then Slice H.

## 2026-09-14 — Seed-paired batch comparisons (ADR-084)

The first of a set of slices acting on a research pass over recent agent-swarm, evolutionary-agent
and evaluation work. This one is the Slice H prerequisite that pass pointed at most directly.

### What shipped

`simulation/batch.py` runs every arm at every seed, each `(arm, seed)` in its own spawned process
against its own `:memory:` colony, and writes one manifest per run plus a `batch.json` index
(`mitosis simulate-batch`). `simulation/paired.py` compares two arms seed by seed over a closed set
of named manifest metrics (`mitosis simulate-compare`): the mean per-seed difference, a seeded
percentile-bootstrap CI on it, an unpaired CI over the same numbers, the across-seed correlation,
and `Var(d)/(Var(a)+Var(b))`. `cmd_simulate`'s staged-funding validation default moved into
`batch.build_selection` so a single run and a batch arm cannot disagree about it.

### Measured before choosing

- **Processes, not agents.** A run is deterministic CPU work against mock Cells; there is no model
  call to fan out. 24 runs took 10.6s wall for 65.5s CPU on 8 workers.
- **In memory, not file-backed.** The same p=30/e=40 run: 17.6s file-backed (5.3s system CPU) vs
  9.1s in memory (0.03s). That is the p=50/e=200 benchmark's 480s of system CPU explained.

### Found

- **Pairing is metric-dependent, in both directions.** A 3-arm × 8-seed pilot: total revenue
  correlates +0.96 across seeds and pairing cuts its variance to 7%; peak founder concentration
  correlates −0.20/−0.42 and pairing *widens* its interval (ratio 1.19/1.29). Slice H's
  pre-registration has to declare the paired design per metric.
- **Two candidate metrics are one effect at this scale.** `final_living_cells` and
  `total_reproductions` report the identical difference over 25 epochs (nobody dies), so
  pre-registering both would count one effect twice.
- **The pairing precondition held already and is now pinned.** Every simulator draw was keyed by its
  own seed label; a new test runs a selection policy that burns its stream, the global `random`
  module and the seeded id generator, and requires an identical economy.

### Verification

19 new tests. Four teeth-checks, all caught for the stated reason (environment keyed by
`experiment_id`; paired CI from unpaired resamples; a failed run silently counted; unpaired seeds
silently intersected — the last first written as a bare guard removal that crashed with `KeyError`
instead of intersecting, i.e. an incomplete mutation, then redone completely and caught). Full suite
1353 passed; golden run unchanged; `ruff check .` and `scripts/check_docs_facts.py` clean.

- Next: the rest of the research-driven set — a network/process seal on simulated runs, Auditor
  judge entanglement, verbalized sampling as a twin experiment, a real consumer for the workflow
  gene, a tool-evaluator registration guard, evaluator-epoch bookkeeping, the §11.3 collusion
  amendment, a teeth-check runner and a claim-drift checker — then Slice H.

## 2026-09-06 — Closing the evolutionary decision loop, part 6: the cross-policy acceptance harness (Slice G, part 6 — Slice G complete)

Continuing the plan from ADR-077 through ADR-082 without a fresh plan-mode round-trip. ADR-083 is
the full as-built record.

### What shipped

G6 needed no new mechanism — every property the brief asks it to verify was already produced by
earlier sub-slices (`simulation_selection_decision`/`simulation_mutation` audit events since F1/G0;
`config_hash`/`environment_name`/`selection_policy_name` since ADR-077). This is purely an
acceptance-test suite proving those properties hold under real, live-run conditions: the same
`RunConfig` run once with `RandomEligibleSelection` and once with `StagedFundingSelection` (two
independent in-memory databases, not one shared connection) produces matching
`config_hash`/`environment_name` and differing `selection_policy_name`; every `simulation_mutation`
event's `parent_cell_id` appears in a same-epoch `simulation_selection_decision` event's
`chosen_parent_cell_ids`; `founder_concentration`/`distinct_genomes` form a real, growing time
series across a run; `StagedFundingSelection` holding its own validation environment never reaches
`EnvironmentSuite`'s isolated `validation`/`secret_challenge` roles, re-verifying ADR-073's guarantee
with a policy that actually exercises the seam it depends on.

### A defect found in ADR-082's own live-run test, on an already-pushed commit

Building a scenario that genuinely reproduces under `StagedFundingSelection` required a 24-way
seed/scale sweep — every combination showed zero reproduction, ever. Tracing `decide()` directly
found why: no mutation operator ever sets `product.durable`/`product.quality`, so `RuleBasedMarket`'s
standard/premium tiers are permanently unreachable, and no founder starts priced in the one tier that
*is* reachable — with `RuleBasedMarket` as validation, every elite is rejected forever, so no
mutation (including a price mutation that might reach the reachable tier) ever gets a chance to run.
A genuine structural deadlock, confirmed by switching validation to the same family or to `None`,
both of which reproduce reliably. ADR-082's own live-run test used `RuleBasedMarket` and asserted
only `failures == ()`/conservation — which holds trivially for a colony that never reproduces — so it
had never once exercised real reproduction since it was written. Two of this slice's own first-draft
tests made the identical choice and were silently `pytest.skip`-ing every run for the same reason.
All three fixed here (same-family validation at a verified-reproducing seed), corrected forward per
this repo's rule against rewriting pushed history rather than amending ADR-082. The deadlock itself
is real and not a `validation_probe` bug (proven correct in isolation by ADR-082's own unit tests) —
an honest consequence of `RuleBasedMarket`'s intentionally harsh design meeting mutation operators
never given a way to satisfy it. A new, permanent test checks this finding itself; both viable fixes
are named in `FUTURE_BUILD_HOOKS.md`, neither of them Slice G's job.

### Verification

5 new tests plus 3 corrected (104 total in the simulation area). One teeth-check — recording a
mutation event's `parent_cell_id` as the child's id instead of the parent's — confirmed to fail the
traceability test for the stated reason and restored verbatim. Full suite green (1334 total); golden
run unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

## 2026-09-06 — Closing the evolutionary decision loop, part 5: staged funding, the composed policy (Slice G, part 5)

Continuing the plan from ADR-077 through ADR-081 without a fresh plan-mode round-trip. ADR-082 is
the full as-built record.

### What shipped

`StagedFundingSelection` (brief Slice G policy #5, "the intended policy"): composes every earlier
sub-slice rather than adding a sixth mechanism. Gates every eligible Cell on `ParetoSelection`'s two
dimensions before a gate-survivor can be considered a niche elite; niches/elites come from
`MapElitesSelection`'s own rule, restricted to gate survivors; each niche gets one real
Thompson-sampled draw (`posteriors.sample()`, its first real caller), funding only the top 3 sampled
niches at a budget scaling with that niche's posterior mean. A new `candidate.validation_probe` gate
— `EnvironmentSuite.validation`'s first real consumer (ADR-073's own named obligation) — runs against
a niche's chosen elite only, injected via this policy's own constructor rather than a new `decide()`
parameter, so the routine epoch loop's existing "no path to `validation`" guarantee stays unmodified
for every policy. `cmd_simulate` defaults `--validation-environment` to the other market family from
`--environment` when `staged_funding` is chosen.

### A shared-constant edit that would have made `ParetoSelection` dishonest if left alone

Adding `validation_probe` to `candidate.SIM_GATE_DIMENSIONS` automatically flows into every
dynamically-derived `unmeasured_dimensions` tuple — correct everywhere except `ParetoSelection`,
whose measured-dimensions constant and `unmeasured_dimensions` were both hardcoded literals that
would have silently started claiming it measures a gate it never runs. Fixed by excluding
`validation_probe` explicitly in both places; `StagedFundingSelection`'s own `unmeasured_dimensions`
is derived rather than hardcoded, precisely so this doesn't recur for the next dimension added.

### Verification

7 new tests (99 total in the simulation area). Four teeth-checks — the validation-rejection filter,
the gate-survivor restriction into `niche_elite`, the top-K slice, the budget-scaling formula — each
confirmed to fail for the stated reason and restored verbatim. Full suite green (1329 total; one
unrelated Hypothesis deadline flake on `test_charter_ledger_balanced` reproduced as a clean pass in
isolation and on a full re-run); golden run unaffected (hash unchanged at 38); `ruff check .` and
`scripts/check_docs_facts.py` both clean. Documented honestly: the archive can have at most 3 niches
today (only `structural_novelty` ever measures for a simulated genome), so the top-K=3 cap cannot yet
exclude anything in a real run — its ranking-and-cap logic is still verified by monkeypatching the
constant down to 1 in a dedicated test.

**Correction (2026-09-06, ADR-083):** this entry's own live-run test used `RuleBasedMarket` as the
validation environment, which (a defect found while building G6) can never be cleared by any
simulated genome and so silently never exercised real reproduction. Fixed in the G6 commit; see
ADR-083 for the full finding.

- Next: G6 — the cross-policy acceptance harness (same seed bundle run once with
  `RandomEligibleSelection` and once with `StagedFundingSelection`; a reproduction-traceability test;
  the validation-isolation regression guard re-run unmodified) — then Slice H's pre-registered
  Phase 3 comparisons. The >= 500 Cell/>= 10,000 epoch Phase 2 acceptance benchmark itself remains
  documented but not yet run to completion (ADR-076).

## 2026-09-06 — Closing the evolutionary decision loop, part 4: MAP-Elites, one elite per occupied niche (Slice G, part 4)

Continuing the plan from ADR-077 through ADR-080 without a fresh plan-mode round-trip. ADR-081 is
the full as-built record.

### What shipped

`MapElitesSelection` (brief Slice G policy #4): calls `novelty.archive()` directly and, for every
occupied niche, calls `candidate.niche_elite()` (built in G1, its first real caller) — highest
`realized_net_revenue` among evaluated occupants, or a uniform-random pick among unevaluated ones.
Every occupied niche reproduces each epoch (classical MAP-Elites; budget-constrained prioritization
across niches is G5's job via Thompson sampling). Each niche's real §12.3 posterior is recorded on
its `NicheStanding` regardless of whether this policy reads it.

### A coincidental-pass test found and fixed before it shipped

The first version of the posterior-recording test asserted only that a niche with zero rung-7
promotions gets the uninformative Beta(1,1) prior — true, but numerically identical to what a
silently-broken posterior lookup falls back to (`_posterior`'s formula gives `alpha=beta=1.0` at
`trials=0` either way). Rewritten to inject a real, non-prior posterior via monkeypatch and assert
those exact values survive into the decision record, so a broken lookup now produces a visibly wrong
result. Same root cause as ADR-077/ADR-079's own coincidental-pass teeth-checks this slice: a
too-easy CAUGHT deserves a second look before being trusted.

### Verification

4 new tests (92 total in the simulation area). Three teeth-checks — the posterior lookup, the
eligibility threading into `candidate.niche_elite()`, the factory's dispatch branch — each confirmed
to fail for the stated reason and restored verbatim. Full suite green (1322 total); golden run
unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: G5 — `StagedFundingSelection`, composing `ParetoSelection`'s gates with this policy's
  niche/elite rule, a new `validation_probe` gate, and a Thompson-sampled draw per niche
  (`posteriors.sample()`, built in G1 but still uncalled) funding only the top-K sampled niches — then
  G6's cross-policy acceptance harness and Slice H's pre-registered Phase 3 comparisons. The
  >= 500 Cell/>= 10,000 epoch Phase 2 acceptance benchmark itself remains documented but not yet run
  to completion (ADR-076).

## 2026-09-05 — Closing the evolutionary decision loop, part 3: Pareto selection, reproducing the whole front (Slice G, part 3)

Continuing the plan from ADR-077 through ADR-079 without a fresh plan-mode round-trip. ADR-080 is
the full as-built record.

### What shipped

`ParetoSelection` (brief Slice G policy #3): gates every eligible Cell on
`not_quarantined`/`reproducibility`, takes the Pareto front over
`structural_novelty`/`realized_net_revenue`/`experiment_success_rate`, and reproduces from **every**
Cell on the front — not one winner. That last point is the whole content of the comparison this
policy sets up against `SingleLeaderboardSelection`: SPEC.md §10.2's "portfolio, not a scalar" only
means something if the portfolio is actually funded. Each front member draws its own mutation
operator via the per-parent override fields ADR-078 built but nothing had used yet.

### A gate found to be structurally unreachable through this pipeline

`candidate._not_quarantined` is correctly implemented and independently proven (ADR-078) — but every
policy builds its candidates only from `_eligible_parents()`'s own output, which already filters to
`CellStatus.ALIVE` before a gate ever runs. A quarantined Cell is excluded at the *eligibility*
stage, not the *gate* stage, so this gate's `REJECTED` branch cannot fire through any policy's
`decide()` regardless of colony state. Kept anyway — correct, cheap, and a module built for reuse by
`MapElitesSelection`/`StagedFundingSelection` next shouldn't assume every future caller pre-filters
the same way — but the first version of this slice's own test asserted a rejection that can never
happen here and failed; rewritten to assert the accurate, narrower fact instead.

### Verification

4 new tests (88 total in the simulation area): a genuine three-Cell trade-off fixture (higher revenue
but a lower success rate vs. lower revenue but a perfect one, with `structural_novelty` held tied via
identical genome content so only the two controlled axes discriminate) proving mutual
non-domination puts both on the front while a dominated third is excluded; the corrected quarantine
test; every chosen parent receiving its own operator; a CLI end-to-end run. Three teeth-checks, each
confirmed to fail for the stated reason and restored verbatim. Full suite green; golden run
unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: G4 — `MapElitesSelection`, giving `novelty.py`'s archive the elite-per-niche rule
  `candidate.niche_elite()` already built in G1 its first real caller — then G5
  (`StagedFundingSelection` + Thompson sampling + the `EnvironmentSuite.validation` consumer), G6
  (the cross-policy acceptance harness), and Slice H's pre-registered Phase 3 comparisons. The
  >= 500 Cell/>= 10,000 epoch Phase 2 acceptance benchmark itself remains documented but not yet run
  to completion (ADR-076).

## 2026-09-05 — Closing the evolutionary decision loop, part 2: the second selection policy, and the CLI/factory wiring the rest will reuse (Slice G, part 2)

Continuing the plan from ADR-077/078 without a fresh plan-mode round-trip. ADR-079 is the full
as-built record.

### What shipped

`SingleLeaderboardSelection` (brief Slice G policy #2): ranks eligible Cells by one named scalar
(`scalar_metric = "realized_net_revenue_minor_units"`), reproduces the single top-ranked Cell, runs
no gates — its `reason` states plainly this is the shape SPEC.md §10.2/§13.2 forbid for the
production kernel, built only as a Slice H comparator. `build_selection_policy(name)` mirrors
`environment.build_environment`'s existing pattern; `cli.py` gains `simulate --selection-policy`.
Unmeasured is excluded from the ranking, not treated as a floor value: a Cell with a concluded,
zero-revenue experiment must outrank one with no concluded experiment at all — the same
never-zero posture this codebase takes everywhere else, applied here to a policy that (unlike every
gate/axis in `candidate.py`) needs one total order rather than permission to abstain.

### Another teeth-check that initially passed for the wrong reason

The first version of the "unmeasured ranks last" test created the proven-zero Cell before the
unmeasured one; removing the exclusion term from the sort key still picked the right Cell, because
both collapsed to the same primary key and the *secondary* tie-break (creation order) happened to
favor the older, proven-zero Cell anyway. The same category of trap ADR-077 already hit once this
slice. Fixed by creating the unmeasured Cell first, so a dropped rule now produces an unambiguously
wrong answer regardless of generated-id ordering.

### Verification

4 new tests (84 total in the simulation area): the highest-revenue Cell chosen correctly; the
corrected unmeasured-ranks-last property; the factory's construction and rejection of an unknown
name; a CLI end-to-end run naming the policy it used in its own manifest. Four teeth-checks, each
confirmed to fail for the stated reason and restored verbatim. Full suite green; golden run
unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

## 2026-09-05 — Closing the evolutionary decision loop, part 1: simulator-native fitness dimensions, the full decision-record schema, Thompson sampling (Slice G, part 1)

Continuing the plan from ADR-077 without a fresh plan-mode round-trip. ADR-078 is the full as-built
record.

### What shipped

New `src/mitosis/simulation/candidate.py`: simulator-native gates (`not_quarantined`;
`reproducibility` — a genuine canonical measurement via cross-Cell replication of a revenue-producing
result, not a port of the kernel's permanently-unmeasurable version) and axes (`structural_novelty`,
reused from `novelty.descriptors()` by direct call since it's genome-content-only;
`realized_net_revenue`; `experiment_success_rate`; `economic_potential`, permanently unmeasurable
even here — §0.3's refusal is structural, and the simulator has no self-reported-upside field to even
decline). `dominates()`/`pareto_frontier()` reimplement `selection.py`'s exact rule over the new
candidate shape; `niche_elite()` gives `novelty.py`'s archive the elite-per-niche rule its own
docstring says it deliberately lacks. `posteriors.sample()` adds one Thompson-sampling draw without
disturbing the module's stated boundary — comparing niches' draws stays absent, reserved for G5.

`SelectionDecision` gains nine new fields, all defaulted, so no existing policy or test needed to
change shape: gate results, measured/unmeasured dimensions, Pareto-front membership,
`niches: tuple[NicheStanding, ...]`, per-parent operator/budget overrides (ADR-074 logged deferring
exactly this generalization), and `intended_experiment`. `RandomEligibleSelection` now reports every
known dimension as `unmeasured_dimensions` — an explicit "nothing consulted," not a silent empty
tuple. `runner.py`'s reproduction loop consults the per-parent overrides with a fallback that keeps
every prior run's behaviour byte-identical.

### A wrong first verification, caught before it shipped

The first draft of the budget-override test checked the child's *current* USD_SIM cash balance —
wrong, since a child born early in a 20-epoch run has since earned its own revenue. Fixed to query
the `cell_reproduction_funding` transaction itself (fixed at birth, and — found while fixing this —
a genuinely different transaction type from founding's `cell_birth_funding`).

### Verification

21 new tests across three files (80 total in the simulation area): every gate/axis function on
constructed fixtures; `dominates()`'s strict-improvement and disjoint-measured-axes cases;
`pareto_frontier()`'s gate filtering; `niche_elite()`'s evaluated-vs-exploratory split;
`posteriors.sample()`'s statistical convergence, determinism, and seed-sensitivity; the
decision-record honesty field; the per-parent override mechanism through a live run. Seven
teeth-checks, each confirmed to fail for the stated reason and restored verbatim. Full suite green;
golden run unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both
clean.

## 2026-09-05 — Closing the evolutionary decision loop, part 0: a run record that never named its own selection policy, and founder concentration as a real time series (Slice G, part 0)

A plan was written first, given the genuine architectural forks Slice G surfaces (a full Explore
pass over `selection.py`/`novelty.py`/`posteriors.py`/`autopromotion.py`, then a Plan pass to
resolve them) — `docs/DECISIONS.md`'s ADR-077 is the as-built record for this first sub-slice; the
plan file itself sequences the remaining six.

### The central finding the whole plan turns on

The kernel's own fitness dimensions would be uniformly degenerate if reused verbatim on simulated
Cells: `SimulationPolicyProvider._propose()` hardcodes `estimated_cost_minor_units: 0` and
`predictions: []` on every call, killing `evidence_quality`/`information_gain`/`experiment_cost`
permanently; no content audit or counterparty-keyed revenue is ever produced either, killing
`software_native_advantage` and two of `novelty.py`'s three dimensions. Only genome-content-based
`novelty_distance` survives contact with the simulator unchanged. The plan therefore builds a
simulator-native dimension set from data the simulator actually produces — reusing the kernel's
*shapes* (the `dominates()` rule, the niche-coordinate pattern) by direct call where the underlying
function is genuinely genome-content-only, and building new, honestly-named logic everywhere else.

### What shipped in this first, smallest sub-slice

- **The bug**: `runner._record_run_start` has taken a `selection: SelectionPolicy` parameter since
  F1 but never read `.name`/`.version` from it — both `simulation_runs` and the manifest recorded
  the *Cell* policy's identity in the selection-policy fields too. For a slice whose entire purpose
  is comparing selection policies, nothing at the run level could say which one a run used except a
  per-epoch audit event. Fixed with two new nullable columns (migration 0036, no rebuild needed) and
  `_record_run_start` finally using its own parameter.
- **Founder concentration**, joining `distinct_genomes` as a real per-epoch time series: new
  `lineage.founder_concentration()`, one `GROUP BY` over the already-denormalized
  `cells.founder_cell_id`. Comparable across policies over time, which a free-text reason inside one
  policy could never give.

### A teeth-check that initially passed for the wrong reason

The first attempt at proving `founder_concentration`'s ordering mattered removed `ORDER BY n DESC`
entirely — this happened to still name the right founder, purely because that run's random ids
coincidentally sorted it first. Flipping `DESC` to `ASC` instead picks the *smallest* count
deterministically, which can never be the dominant lineage — confirmed to fail across three
independent runs with fresh random ids each time, not just once, before trusting it.

### Verification

5 new tests (50 total): the run-record fix (a minimal name/version-only policy wrapper, since no
second real policy exists yet); `founder_concentration`'s correctness on a ten-founder fixture (the
same `max_lineage_population_fraction` reason population is raised to ten elsewhere in this file);
founder concentration as a real bounded time series. Two teeth-checks (the second needing the
do-over above), both confirmed to fail for the stated reason and restored verbatim. Full suite
green; golden run unaffected (hash unchanged at 38); `ruff check .` and
`scripts/check_docs_facts.py` both clean (README's migration count updated 35 -> 36).

## 2026-09-05 — Phase 2 flight simulator, fifth slice (part a): manifest richness, a CI-scale acceptance scenario, and a founding bug the acceptance scale would have hit (Slice F, part 5a)

Continuing the same sub-slice sequence (ADR-072–075) without a fresh plan-mode round-trip.
ADR-076 is the full as-built record.

### What shipped

`EpochRecord` gains `distinct_genomes` (the diversity time series — distinct `genome_hash` values
among living Cells, since a genome hash *is* a Cell's full strategy under ADR-018) and
`environment_events` (regime-shift recovery, made visible on the retained manifest itself rather
than only via the audit trail). `RunManifest` gains `config_hash`, a SHA-256 over the run's actual
configuration. One consolidated test, `test_phase_2_ci_scale_acceptance_scenario`, runs a single
small scenario and asserts every bullet of the brief's own Phase 2 acceptance checklist by name.

### A bug the acceptance criteria's own scale would have hit

Validating the manifest changes at population=50 surfaced an unhandled `BirthRateExceededError`:
`_found_population` created every founder before any epoch advanced, and §9.2's
`max_births_per_epoch` (default 25) does not distinguish a founder from a reproduced child. Nothing
in F1-F4's own tests (all population <= 30) exercised this — invisible until something asked for
more founders than one kernel epoch allows, which the brief's own >= 500 Cell acceptance scale
unavoidably does. Fixed by founding in batches of `max_births_per_epoch`, advancing the clock
between batches exactly as the main loop does — not loosening the cap itself (§9.1's own reasoning
against unrestricted reproduction, the same posture ADR-071 already took on a different cap).

The fix's own first regression test failed for the wrong reason: calling `_found_population`
directly skipped `run()`'s own clock-anchoring setup, so `clock.current_epoch` never advanced
regardless of `clock.advance` calls, and the test failed with the *pre-fix* error for an unrelated
cause. Rewritten to go through `run()` itself.

### Verification

6 new tests (48 total): the founding-batch fix (via `run()`, not the private function directly); the
diversity time series' bound *and* that it's not merely "always equals living_cells"; regime-shift
events appearing only at the scheduled epoch; `config_hash`'s stability, sensitivity to each real
field, and exclusion of `output_path`; the consolidated acceptance scenario. Four teeth-checks, each
confirmed to fail for the stated reason and restored verbatim. Full suite green (1286, up from 1281
— one Hypothesis deadline flake elsewhere confirmed environmental by an isolated rerun, caused by a
concurrent CPU-heavy benchmark validation on this same machine, not a regression); golden run
unaffected (hash unchanged at 38); `ruff check .` and `scripts/check_docs_facts.py` both clean.

### What this does not close (as of this entry — resolved below)

A moderate-scale validation (population=50, epochs=200) run to confirm the founding fix at a scale
that actually exceeds the birth-rate cap completed in 23m47s (~0.14 epochs/sec once population
reached `max_active_cells`=100), retained at
`docs/benchmarks/2026-09-05-founding-fix-validation-p50-e200.json` — nearly 40x slower than the
first slice's own smaller benchmark (~5.6 epochs/sec at population 20->70). Extrapolating that rate
to five times the population and fifty times the epochs points to a multi-hour, quite possibly
multi-day run on this hardware. The literal >= 500 Cell/>= 10,000 epoch acceptance run itself
remains not yet executed — documented and ready, deferred as an explicitly kicked-off, unattended
job sized in hours or days.

## 2026-09-05 — Phase 2 flight simulator, fourth slice: chaos drills as repeatable scenarios (Slice F, part 4)

Continuing the same sub-slice sequence (ADR-072–074) without a fresh plan-mode round-trip.
ADR-075 is the full as-built record.

### What shipped

New `src/mitosis/simulation/chaos.py`, all five brief-required drills, plus one new seam:
`runner.run()` gains `epoch_hook`, called once per epoch after that epoch's own processing already
completed, so every hook-shaped drill shares one addition to `runner.py` rather than one each.
`KillFractionDrill` kills a seeded fraction of living Cells; `WithdrawCapabilityDrill` disables the
`auto_promotion` autonomy flag mid-run; `CrashingEnvironment` (a `MarketEnvironment` decorator, no
runner change needed) raises once from `evaluate()` at a chosen epoch; a regime-shift drill and a
duplicate/out-of-order drill reuse existing mechanisms rather than adding new ones (below).

### Two of five drills needed reframing, stated rather than silently substituted

"Corrupt or withdraw one shared capability/module" has no module/tool-use surface in this simulator
yet (`SimulationPolicyProvider` decides from genome content alone) — `auto_promotion` is the one
capability that actually is shared and colony-wide, so withdrawing it is a real loss, not a
stand-in. "Crash at reserve, execute, and settlement boundaries" targets the *experiment*
lifecycle's own three-phase shape (start/evaluate/conclude), not the deeper money-reservation FSM in
`gateway.py` — that FSM's crash safety is Charter C6's job, already exhaustively verified
independent of any live population; what's genuinely new is whether a full run's own state
(population, audit trail, manifest) survives one call failing mid-flight. The other two boundaries
(`start_from_grant`, `conclude`/`record_revenue`) have no injectable seam today, and building one
solely for a drill to target would be speculative surface for no other caller.

### A wrong assumption, corrected before it shipped

The plan assumed an out-of-order funding call (a child funded before its birth is visible) would be
rejected. Checking rather than assuming: `ledger` accounts are plain strings, not a foreign key into
`cells` (confirmed by reading `scheduler.eligible_cells`, which starts from the `cells` table and
only then checks balances) — so the call neither corrupts anything nor raises; it parks an inert,
unreachable balance instead. The test asserts what's actually true, not the rejection that doesn't
happen.

### Verification

9 new tests (42 total): each drill's real effect verified independently of its own self-report (a
coroner-report count matching the claimed kill count, not just trusting it; the autonomy flag
actually flipped; one recorded failure and the interrupted experiment concluding on a later epoch,
not just "didn't crash"; a >5x aggregate sales drop across the regime-shift boundary at full-economy
scale; duplicate-call idempotency; out-of-order inertness); the shared post-drill invariant helper;
two determinism-under-a-drill checks covering both injection mechanisms (epoch-hook and
environment-wrapper). Five teeth-checks, each confirmed to fail for the stated reason and restored
verbatim. Full suite green; golden run unaffected (hash unchanged at 38); `ruff check .` and
`scripts/check_docs_facts.py` both clean.

- Next: full manifest richness and the two acceptance-scale configurations (Slice F5) close out
  Slice F, then Slice G's remaining `SelectionPolicy` implementations and Slice H's pre-registered
  Phase 3 comparisons.

## 2026-09-05 — Phase 2 flight simulator, third slice: the remaining mutation operators, wired through a real operator choice (Slice F, part 3)

Continuing the same sub-slice sequence (ADR-072, ADR-073) without a fresh plan-mode round-trip.
ADR-074 is the full as-built record.

### What shipped

Six new operators in `src/mitosis/simulation/mutation.py` — market/customer, product/delivery,
acquisition-channel, pricing/revenue-model, workflow, model-policy temperature — the brief's exact
list, alongside the no-op/control that shipped in F1. Discrete-choice operators (segment, delivery
mode, channel, workflow structure) exclude the parent's current value from their candidates, so
invoking one always changes that field; the two continuous operators (price, temperature) don't
force a guaranteed change — any nonzero perturbation already differs, and the rare clamped-identical
case (temperature already at a bound) is recorded honestly rather than retried away.

### A hardcoded call was hiding behind a decision-record field that already existed

`SelectionDecision.mutation_operator` has recorded an operator *name* since F1, but
`runner._run_one_epoch` never read it — every reproduction called `mutation.no_op(...)` directly.
Unnoticed while `no_op` was the only real operator; wiring five more without fixing this would have
shipped them as functions nothing in the live pipeline ever calls. Fixed with an `OPERATORS`
dispatch table and `RandomEligibleSelection` now choosing an operator name at random from the same
`rng` it already draws the parent choice from.

### A second bug in the same call site

The reproduction loop passed the bare `master_seed` to every mutation, unchanged across the whole
run — harmless for a no-op that ignores its seed, but every real operator would have drawn the
identical "variation" forever. Fixed with a per-event label,
`f"{master_seed}:mutation:{epoch}:{parent_id}"`, matching this package's existing seeding
convention. Same shape as F1's tuple-seed bug and F2's stale-epoch-range test break: a call site
built before its inputs mattered, unexercised until something downstream actually varied by them.

### Recording the brief's five required facts without a schema change

`genome.inherit()` merges a mutation key by key, not a deep merge — an operator changing one nested
field must carry the rest of that key's own content forward, or a fact the mutation didn't intend
to touch would be silently dropped from the child. Parent/child hashes already live on
`cells`/`cell_genomes`; the seed, before/after diff, and distinctness flag go through
`audit.record(event_type="simulation_mutation", ...)` — the same "explain, don't define a second
identity" reason `SelectionDecision` and regime-shift events already use, for the same underlying
cause each time: a mutation that collapses to the parent's own existing genome row (ADR-018) writes
no new row, so only the audit trail can attribute a fact to *this* reproduction event.

### Verification

9 new tests (33 total in `tests/test_simulation.py`): each discrete operator's guaranteed change;
registry names matching returned names; price/temperature bounds; determinism given a fixed seed
across all seven operators; nested-field preservation against the merge semantics; per-event seed
uniqueness; a full run's audit trail checked for completeness and for a real operator actually
firing and producing distinct content through the live pipeline. A pre-existing F1 test asserted
every child's genome_hash equals its parent's — true only because `no_op` was the sole operator
ever chosen; the assertion was removed (now false in general) and its still-true claim (real
funding, a real row) is what remains, with hash-collapse behaviour covered by the new audit-based
tests. Four teeth-checks, each confirmed to fail for the stated reason and restored verbatim: the
discrete-operator exclusion, the dispatch, the mutation audit-recording call, and the per-event
seed, each removed in turn. Full suite green; golden run unaffected (hash unchanged at 38); `ruff
check .` and `scripts/check_docs_facts.py` both clean.

- Next: chaos drills (§28) and full manifest richness (Slice F5) close out Slice F, then Slice G's
  remaining `SelectionPolicy` implementations and Slice H's pre-registered Phase 3 comparisons.

## 2026-09-05 — Phase 2 flight simulator, second slice: a second market family, real environment separation, and scheduled regime shifts (Slice F, part 2)

Continuing F1's own sub-slice sequence (`docs/DECISIONS.md`'s ADR-072) without a fresh plan-mode
round-trip — the architecture was already settled there. ADR-073 is the full as-built record.

### What shipped

- **`RuleBasedMarket`** — the second family brief requirement F.2 (§8.3) requires. Where
  `UtilityMaximizingMarket` compares a continuous random willingness-to-pay draw against price, this
  one branches on discrete rules throughout: a price tier, a genome-declared boolean flag required
  to clear the standard tier, a premium tier gated on a declared quality flag plus a fixed-cutoff
  coin flip. Proven independently shaped, not just differently named: one fixed genome (price=600,
  no `durable` flag) sometimes sells in the sibling family and never sells in this one.
- **`EnvironmentSuite`** (§8.1) — a real three-field config object (`training`/`validation`/
  `secret_challenge`), enforced structurally rather than by convention: `runner._run_one_epoch`'s
  own signature takes one environment, not a suite, so the routine loop has no path to
  `validation`/`secret_challenge` even by mistake. Proven with a fake that raises the instant
  anything calls it, not an AST check. Wiring a `validation`-consulting selection policy is
  deliberately left to Slice G — `RandomEligibleSelection` doesn't consult any environment outcome
  at all, by design, so there is no real consumer yet to wire it to.
- **Scheduled regime shifts** (§8.4) on both families, at one shared fixed epoch: price compression
  for the utility-maximizing market, stricter enforcement (a narrower always-clears budget tier) for
  the rule-based one. A fixed epoch, not a random shock, because §8.4 calls this "part of fitness
  evaluation" — something a Phase 3 comparison could pre-register against. Recorded via
  `audit.record` the same way a selection decision already is (ADR-072), rather than a second
  schema-level identity for the same fact; surfacing it in the manifest itself stays out of scope,
  per `manifest.py`'s own docstring assigning that to F5.
- `cli.py`'s `simulate` verb gains `--environment {utility_maximizing_market,rule_based_market}`.

### A pre-existing test broke, correctly

`test_the_two_environment_families_disagree_on_the_same_genome` (written before the regime shift
existed) sampled 30 epochs at a price that the shift made provably unsellable past epoch 10 in the
sibling family — the specific seed/price combination had zero hits in the remaining pre-shift
window. Fixed by restricting to the pre-shift window and picking a price verified, not assumed, to
hit within it. The `grep every reader of it, not just the enforcer` habit applies to a change in
what an epoch *means*, not only to a changed field.

### Verification

12 new tests (24 total in `tests/test_simulation.py`): the second family's purity, tier rules, and
proven disagreement with the first; the environment factory's name-based construction and rejection
of an unknown name; the CLI flag actually changing which family runs, not just being accepted; the
routine loop's structural blindness to `validation`/`secret_challenge`; both regime shifts,
behaviourally (a price chosen so the post-shift outcome is deterministically impossible, not just
statistically unlikely) and via `advance()`'s returned event; the shift's audit-trail record. Six
teeth-checks, each confirmed to fail for the stated reason and restored verbatim: the durable-flag
tier rule, the unknown-name rejection, the CLI wiring, the routine loop's environment source, the
regime-shift epoch branch, and the audit-recording loop, each removed in turn. Full suite green
(1263, up from 1251); golden run unaffected (hash unchanged at 38 — no existing scenario touched);
`ruff check .` and `scripts/check_docs_facts.py` both clean.

- Next: the remaining mutation operators (§14.1, Slice F3), chaos drills (§28), full manifest
  richness including regime-shift bookkeeping (Slice F5), then Slice G's remaining
  `SelectionPolicy` implementations and Slice H's pre-registered Phase 3 comparisons.

## 2026-09-05 — Phase 2 flight simulator, first slice: mock Cells decide through the real deliberation pipeline (Slice F, part 1)

The brief calls this "the highest-value substantive build" and the last gate before real
evolutionary evidence — SPEC.md's own Amendment A1 already concedes this repo built Phase 4 (the
LLM loop) before Phase 2, so nothing has ever exercised the kernel's governance/accounting machinery
at population scale. Given the size, a plan was written first — three parallel research passes over
the actual current code (genome/lineage/death; selection/novelty/promotion; providers/deliberation/
revenue), not memory — and approved before any code. `docs/DECISIONS.md`'s ADR-072 is the full
as-built record, including three places building it refined the plan; this entry is the summary.

### What shipped

New `src/mitosis/simulation/` package (migration 0035 for its own `simulation_runs` audit row,
`pricing.py` gains a zero-cost `("simulation", "policy-v1")` entry, `cli.py` gains `mitosis
simulate`). Every birth, death, transaction, experiment, and capital movement goes through the
*existing* kernel entry points — `lifecycle.create_cell`/`lineage.reproduce`, `ledger
.post_transaction`, `experiment_grants.start_from_grant`/`experiments.conclude`, `revenue
.record_revenue`, `scheduler.tick`. The simulator supplies only the decisions nothing in the kernel
makes today:

- **`policy.py`** — `SimulationPolicyProvider` implements the existing `providers.ModelProvider`
  Protocol, so a mock Cell's proposal plugs into `scheduler.tick()` unchanged and still passes
  through the real proposal schema, risk assessment, and approval queue. Deterministic per call from
  `(genome content shown this call, a monotonic call counter)`, not per-Cell identity — the Protocol
  carries none, and two Cells can share a genome hash right after birth.
- **The plan proposed a new manual approval decider for `spend_request` grants; building it found a
  cleaner path.** `approval._kernel_tier` has no branch at all for `ProposalKind.EXPERIMENT` — a
  LOW-claimed, reversible, signal-free one is genuinely `batchable` and auto-approved by the
  *existing* `autopromotion.sweep()` step ADR-071 already wired into `tick()`. This also explains two
  reserved sockets already sitting unfilled in the repo: `experiment_grants.FLIGHT_SIMULATOR_RUNG =
  1` and `experiments.LADDER`'s rung-1 label, verbatim, `"flight simulator"`.
- **`environment.py`** — `MarketEnvironment` Protocol plus one concrete family
  (`UtilityMaximizingMarket`): customers buy when a seeded willingness-to-pay meets the genome's
  declared price. Brief requires >= 2 families; only one ships here.
- **`mutation.py` / `selection_policy.py`** — the required no-op/control mutation, and
  `RandomEligibleSelection` (brief Slice G's own policy #1, built here since it is also Slice F's
  own minimum — some reproduction across niches, not quality-diversity selection). The
  `SelectionPolicy` Protocol is designed to Slice G's full decision-record shape now, so the other
  four named policies are additive later rather than a rework.

### Three bugs found by running it, not by reading it

`random.Random()` does not accept a tuple as a seed (every draw was keyed on one; fixed to a stable
f-string, which — unlike `hash()` — does not depend on `PYTHONHASHSEED`). `experiment_grants
.start_from_grant` raises two sibling exceptions and only one was caught: `ExperimentConflictError`
(expected — an approval's own `WAKE_HUMAN_DECISION` follow-up becomes ready only on the *next*
tick, so a cell often carries two pending grants into one epoch) was handled, but at population >=
`max_parallel_experiments` (default 20, §9.2's colony-wide slot cap) the sibling
`ExperimentCapacityError` fired just as often and, uncaught, aborted the whole epoch before anything
could conclude — stranding every running experiment permanently. A smoke-scale test (population <=
10) never exercised this; only a manual population=20 run did. And the first invariant check counted
`Book.USD_REAL` transaction rows, which fails on every run: `gateway.call_model` reserves and
releases against USD_REAL for *every* call regardless of provider (a same-Cell cash<->committed pair
netting to zero) — pre-existing bookkeeping, not spend. Fixed to sum `external_expense` activity,
which is what "zero USD_REAL movement" actually means.

### A gap fixed while building

`lineage.reproduce()` funds a child only in the parent's own book — a child born this way had no
USD_REAL/RESOURCE balance and would be permanently unschedulable. Every reproduction now also funds
the child's scheduler-eligibility sliver from `seed_bank`, same as founding. Confirmed live:
population 20 -> 70 over 50 epochs, children actually woken and participating in later epochs, not
just present as inert rows.

### Verification

- 12 new tests (`tests/test_simulation.py`): same-seed determinism (byte-identical manifests except
  `run_id`); the `external_expense` invariant; population growth through the real reproduction path
  (population raised to 10 so a lineage's first child clears `max_lineage_population_fraction`'s
  0.20 cap — the same founder-effect tension FUTURE_BUILD_HOOKS.md already documents, which bites
  immediately at population=3); a reproduced child's own USD_REAL/RESOURCE funding; a population=20
  run against §9.2's cap; a CLI end-to-end run; the policy's prompt-extraction seam; environment
  purity; a structural test that no kernel module imports `simulation`.
- Every bug above teeth-checked in the literal sense: fix reverted, the specific new test confirmed
  to fail for the stated reason, fix restored — including a temporary fake USD_REAL spend inserted
  into the epoch loop to prove the invariant actually catches one.
- Full suite green (1249, up from 1239 — the file's own 12 plus 2 that already existed as a wash);
  golden run unaffected (hash unchanged at 38 — new package, a migration nothing existing reads, a
  new CLI verb, no existing scenario touched); `ruff check .` and `scripts/check_docs_facts.py` both
  clean (README's migration count and phase-status table updated — Phase 2 split from Phase 3 to
  say precisely what is and is not built rather than one blanket "not built" claim).
- Manually run at population=20/epochs=50 (~5.6 epochs/sec on this hardware) specifically because
  the automated suite's smoke scale would not have surfaced the capacity-cap bug.

- Next: the plan's own sub-slice sequence continues — a second, independently-shaped environment
  family and environment separation (§8.1) next, then regime shifts (§8.4), the remaining mutation
  operators (§14.1), chaos drills, and the two acceptance-scale configurations, before Slice G's
  remaining `SelectionPolicy` implementations and Slice H's pre-registered Phase 3 comparisons.

## 2026-09-05 — External audit brief, Slices C–E: docs reconciliation, a lint gate, and auto-promotion reaching `tick`

Continuing the brief's priority order after Slices A–B (distribution hygiene, egress boundary;
archived above): documentation repair, a minimal static-analysis gate, then the scheduled-path
wiring the brief calls out as the last step before the Phase 2 flight simulator becomes the
gating priority.

### Slice C — documentation/safety-claim reconciliation

README's Status table carried stale counts (a fixed test/migration/golden-version trio that had
already drifted once) and a "two separate humans" approval claim the code has never enforced —
`approval.approve` takes any `decided_by` string, so a single operator approving their own request
is not code-refused, only discouraged by convention. Rewrote the Status section as a phase-capability
table plus a **Tests** row that names the mechanism (`pytest`, Hypothesis property tests) instead of
a number that goes stale on the next commit, and corrected "two separate humans" to "two explicit
steps" with an audit-trail caveat rather than a code-enforced guarantee. Backed by
`scripts/check_docs_facts.py` (stdlib-only: migration count from the migrations directory, golden
expectation version from `golden_expectations.json`, CLI verbs via an AST walk of `cli.py`'s
`add_parser` calls, README's own referenced verbs via regex) wired into CI so a claim that *can*
drift automatically fails the build the next time it does, instead of waiting for the next external
audit to notice.

### Slice D — a narrow runtime-defect lint gate

The brief's claim reproduced exactly: `tools.py`'s `ToolCall.arguments: dict[str, Any]` referenced
`Any` with no import, a live `NameError` on any code path that called
`typing.get_type_hints` against that class (confirmed by reverting the one-line fix and getting the
exact `NameError: name 'Any' is not defined`, before re-fixing). Added `ruff` as a dev dependency
scoped to `E9,F63,F7,F82` — undefined names and syntax-shaped errors only, **not** the ~339-finding
broad style sweep a default `ruff check` reports, which stays deliberately unchased in one commit
per CLAUDE.md. `test_public_type_hints_resolve` pins the guarantee structurally
(`typing.get_type_hints` on every public class); CI gained both the docs-fact-check and the lint
gate as separate steps.

### Slice E — wiring `autopromotion.EvidencePromoter` into the scheduled `tick`

`cli.py::cmd_tick` never passed a `promoter` to `scheduler.tick()`, so an operator who enabled
`auto_promotion` (§27.1) got proposals deliberated and queued every tick but **nothing ever
allocated** unless they separately remembered to run the standalone `mitosis auto-promote` verb by
hand — the flag looked live and silently wasn't, on the one path (`cron` + `tick`) an unattended
colony actually runs. One line (`promoter=autopromotion.EvidencePromoter()`), leaning entirely on
`autopromotion.sweep()`'s own pre-existing flag gate and guard coverage (ADR-063) — nothing new to
build, only a missing call site.

**Reading the guards changed what "on" needed to test.** `approval._kernel_tier` unconditionally
floors a `spend_request` at `RiskTier.MEDIUM` regardless of what the Cell claims, and
`RequestStatus.batchable` requires `assessed_tier is RiskTier.LOW` — so **no `spend_request` can
ever be batchable**, and `sweep()`'s own `approve_batch()` step can therefore never auto-approve
one, flag on or off. Since `promotion.allocate()` also requires the grant's proposal be exactly
`spend_request` (the only kind that moves capital), approval and allocation never meet inside one
unattended sweep for this proposal kind: a human approves (`approval.approve()`, exactly as today),
and what this slice adds is that *allocating* that already-approved grant — moving the money, waking
the Cell — now reaches an ordinary scheduled tick instead of requiring the standalone verb. Written
up as ADR-071, since the brief's own phrasing ("approves and allocates") described a scenario that
turns out to be unbuildable in good faith without loosening a live safety floor nobody asked to
revisit.

#### Verification

- **7 new tests** (`tests/test_scheduler_autopromotion.py`): flag off leaves an approved grant
  un-allocated; flag on allocates it; the same property proven **end-to-end through `cli.main`**,
  not just `scheduler.tick()` directly — every other test passes its own `promoter` by hand, so only
  the CLI-level test actually pins `cmd_tick`'s call site; a HIGH-tier request stays queued for a
  person even with auto-promotion on; vacation mode blocks the promoter before deliberation even
  runs (a paid, unreachable `_Boom.complete` proves it); ticking twice does not double-allocate;
  a structural AST test pins that `scheduler.py` still imports none of
  `autopromotion`/`promotion`/`outcome` (the dependency inversion CLAUDE.md names explicitly).
- **Three teeth-checks, each mutate → confirm the specific test fails for the stated reason → restore
  verbatim (never `git checkout`, working tree held in memory).** Removing `cmd_tick`'s `promoter=`
  line failed only the CLI-level test — every direct-`scheduler.tick()` test kept passing, which is
  exactly the gap that test exists to close. Reintroducing a `promotion` import into `scheduler.py`
  failed the structural test by name. Neutering the vacation guard (`if False and is_paid and
  is_on_vacation(...)`) **surfaced two real bugs in the test itself before it could confirm
  anything**: `list == ()` is unconditionally `False` in Python regardless of contents (every
  `allocatable_grants`/`list_promotions` call returns a `list`, so four assertions across the file
  were comparing against the wrong empty-container literal and would have failed even in the
  passing case, or — worse — silently proven nothing when written the other direction), and the
  vacation test's own paid `_Boom` provider tripped the *earlier* `real_spending`-disabled guard
  first, never reaching vacation at all, mirroring the exact confound
  `test_an_absent_operator_pauses_paid_work_but_not_free_work` in `tests/test_scheduler.py` already
  guards against with `scheduler.set_real_spending(conn, True)`. Both fixed, then the same mutation
  re-run to confirm the *fixed* test fails for the right reason before restoring the guard.
- Full suite **1239 passed** (up from 1232 at the end of Slice D — 7 new); golden run unaffected
  (hash unchanged at 38, as expected — this slice touches `cli.py` and tests only, no scenario or
  kernel-semantics change); `ruff check .` and `scripts/check_docs_facts.py` both clean.

## 2026-09-04 — External audit brief, Slices A–B: distribution hygiene and the egress boundary

An external audit (`MITOSIS_IMPROVEMENT_IMPLEMENTATION_BRIEF`, dated 2026-09-04) reviewed the
repository from outside this session's history and found the kernel's governance/accounting
core sound but flagged concrete, reproducible defects the existing test suite never exercised —
plus a live credential exposure that is the owner's to rotate, not this session's to touch.
Every specific technical claim in the brief was independently verified against the live repo
before acting on it (test/migration/expectation-version counts, the `.env`/`.venv` exposure
path, the exact `fetchers.py` bug) — all checked out, so the brief's own priority order (security
containment first) was followed rather than re-derived.

### Slice A — clean source-distribution archive

`.env` (a live Anthropic key) was never git-tracked, but a manually zipped working directory
would have shipped it anyway — zipping bypasses `.gitignore`, `git archive` cannot.
`scripts/build_source_archive.py` builds from `git archive` (tracked content only) and then
independently opens its own output and refuses to ship it if any forbidden path (`.env`, `*.db`,
`.git/`, a virtualenv, a cache dir, macOS metadata, coverage reports) is present anyway — defense
in depth against a future `git add -f` mistake, not just trust in git's default. `dist/`,
`.coverage`, `.DS_Store` added to `.gitignore`.

### Slice B — the public-web egress boundary, in three parts

1. **Robots.txt transport.** `_robots_allow()` called `RobotFileParser.read()`, which opens its
   own plain `urllib.request.urlopen()` — no redirect refusal, no timeout, no byte cap. A
   robots.txt that 302s carried the *policy check* off Charter C12's allowlist even though the
   page fetch itself never would. Now built on the same bounded, no-redirect transport as the
   page fetch, with explicit tested status semantics (401/403 disallow, 404 means unrestricted,
   an oversized or redirected response fails closed rather than parsing a possibly-truncated
   policy).
2. **SSRF / non-public destinations.** The Charter C12 allowlist only ever compared hostname
   *strings* — nothing resolved one. `_check_destination_safe` now refuses a hostname that
   resolves to loopback, private, link-local (cloud-metadata endpoints included), multicast,
   unspecified, or reserved, before either request. Documented, not closed: DNS rebinding (a
   second resolution at actual-connect time) is a named limitation, not silently assumed away.
3. **Honest personal-data status.** The fetcher wrote `contains_personal_data=False`
   unconditionally — never a determination, always a fabricated negative, and a Cell's own
   context rendered it as fact ("personal data: no") on every fetch. Now tri-state
   (`'yes'/'no'/'unknown'`, migration 0034), matching `commercial_use`'s existing shape in the
   same §20.1 tuple exactly. The artifacts-table data migration preserves the one *real* "no"
   (`COLONY_AUTHORED`, no external sources at all) while correcting every other historical `0` —
   which nothing but the fetcher ever wrote — to `'unknown'`.

#### Verification

- **1224 tests and the golden run green**, up from 1175 at the start of this arc — real local
  HTTP servers for the redirect/hang/oversized/status-code cases (a string-level allowlist test
  can't see any of them, which is why the existing C12 suite never caught the robots.txt bug),
  plus synthetic-repo teeth-checks for the archive guard and the migration's data translation.
- **Golden expectations moved 37 → 38.** Full section-by-section diff before regenerating, not
  assumed from the hash mismatch: `tool_calls`/`artifacts` move only on
  `contains_personal_data`; `deliberations`/`model_calls`/`resource_usage` shift by a small
  constant on exactly the 7 rows downstream of the Cell that reads a fetched page back into its
  own context (the honest word is longer than the fabricated one, and `MockProvider` prices
  calls as a function of text length — same mechanism as version 35→36). No `output_tokens`,
  cost, or `balances` row moved.
- **Three separate teeth-checks**, each: mutate, confirm the specific expected test(s) fail with
  no other collateral failures, restore from the pre-mutation copy, confirm byte-identical and
  green again. The robots-transport fix caught its own pre-fix code failing exactly the redirect
  and oversized-response cases ("DID NOT RAISE"); the SSRF guard caught all 16 of its own targeted
  cases with its body stubbed to a no-op; the personal-data precedence order caught the one test
  built to defend it when the tri-state order was swapped.
- Confirmed against a disposable copy of `first-real-call.db` (untouched original): all 34
  migrations apply, `PRAGMA integrity_check` and `foreign_key_check` both clean. No paid provider
  or live network call made — the network tests use only local servers.

## 2026-09-03 — A bounded, single parse-repair retry

`deliberation.py` + migration 0033 + `cli.py` + 7 new tests + golden 36 -> 37 (ADR-069). **An
unparseable reply now gets exactly one re-prompt, naming the specific validation error, before the
wake is recorded as a loss.** PRIORITIES had carried this since ADR-049 as "the standard remedy,
deliberately unbuilt" — gated on "the model question above" being settled. It settled in the
negative (`qwen2.5` unusable on this hardware), which is what unblocked the gate.

### Not the retry `gateway.py` already scoped and declined

`gateway.py`'s docstring already ruled out one kind of retry — re-attempting a call whose *billing
status* is ambiguous (`execution_unknown`), which risks double-billing and needs reconciliation
this kernel does not have. A parse-repair retry is a different thing: the first call is known to
have succeeded and been billed (it returned text; `ProposalError` only fires after that), so what
needs fixing is the *reply*, not the call. It is therefore a wholly new, separately-priced,
separately-capped `gateway.call_model` invocation — the same category §24's intro line also names
("validates structured output"), which already lives in `deliberation.py`/`proposal.py` rather
than the gateway.

### Bounded to exactly one attempt, and best-effort by construction

`MAX_PARSE_REPAIR_ATTEMPTS = 1` — PRIORITIES' own "it pays twice for a prompt bug" is the accepted,
bounded cost; unbounded would turn a persistently broken prompt into an unbounded per-wake cost
multiplier. `_attempt_parse_repair` wraps the whole attempt in a broad `except Exception`: any
failure of the attempt itself (an exhausted cap, an unpriced model) degrades to exactly the
pre-repair UNPARSEABLE outcome — `deliberate()` never raises where it did not raise before this
existed, mirroring `_unfunded_books`' own "a refusal costs nothing and is recorded" reasoning.

### One nullable column, not a second `model_call_id`

A repaired deliberation genuinely makes two billed calls. `deliberations.repair_model_call_id`
(migration 0033) is `NULL` for the overwhelming majority — every deliberation that parses first
try — and named only when a second call was made. A plain nullable `TEXT REFERENCES` column is a
legal SQLite `ALTER TABLE ADD COLUMN`, so this needed no rebuild the way migration 0032
(`proposals.risk_tier`) did.

### Verification

- **7 new tests in `test_deliberation.py`; teeth-checked.** Disabling the wiring in `deliberate()`'s
  except-branch failed the two tests defending the headline behaviour (a repaired PROPOSED outcome,
  and the two-call bound on a persistently bad reply) with clean, specific assertion failures.
- **1172 tests and the golden run green.** Golden expectations moved 36 -> 37: one added boolean
  field (`made_repair_call`) on every `deliberations` row, `False` everywhere — no scenario reply is
  malformed, so nothing in the fixture ever reaches this mechanism. Confirmed by a full
  section-by-section diff before regenerating, not assumed from the hash mismatch alone.
- No live measurement of the actual parse-rate lift was run — logged in FUTURE_BUILD_HOOKS as a
  separate, reviewable act with its own arms and sample size, matching ADR-067's precedent for the
  temperature socket.
### Follow-up (same day, post-slice critique): the catch is narrowed

A critique of the slice caught that `_attempt_parse_repair`'s `except Exception` was a *blanket*
catch — it degraded genuine faults (a bug in the repair path, a locked DB) to a silent UNPARSEABLE
row with the traceback buried in `failure_reason`, uncatchable by any test that drives a working
provider. Narrowed to `_REPAIR_UNATTEMPTABLE_ERRORS` (gateway/reservations/breaker refusals only);
everything else propagates, matching the first, unwrapped `gateway.call_model` in `deliberate()`.
New test `test_a_bug_in_the_repair_path_propagates_rather_than_masquerading` (teeth-checked against
the blanket catch); the fallback test now raises a real `RealSpendCapExceededError`. 1175 tests and
golden green; golden unchanged (the repair path is never hit in the fixture). ADR-069 amended.

## 2026-08-28 — §12.1's third dimension is declared, and the mechanism already existed

Migration 0029 + `counterparty.attest_buyer_type` + 15 tests + `set-buyer-type`/`buyers` + golden
expectations **31 -> 32** (ADR-062). **§12.1's archive is three-dimensional; nothing abstains.**

PRIORITIES said the next step was "a declared `buyer_type`, with its declarer recorded — **one
build, three callers**". That entry was wrong twice, and both errors were worth finding before
building anything.

### The mechanism already existed

ADR-041 built `rights_attestations`: a person establishes a fact the colony cannot derive — subject,
claim, basis, who, when; append-only; latest wins; withdrawal is a row and not a flag; unreachable
from any Cell, enforced by an AST walk. Every one of those decisions is right here for the same
reasons, so this slice **copies an established shape** instead of inventing a judgment subsystem.

### The three callers split two ways, and the split is principled

`buyer_type` is an **external fact** — who actually paid — which an operator holding the invoice can
observe. §13.3's `software_native_advantage` and §13.4's third flag are **readings of the colony's
own prose**, which is what §23.5 keeps out of the kernel and what ADR-032's scored Auditor exists
for: §10.4 requires wrongful flags to be penalised, and prose cannot be penalised. An operator does
not need a Brier score; an Auditor does. One generic judgments table would have scored nobody and
constrained nothing — and could not have stated §12.1's four bins, which migration 0029's CHECK does.

### Three dimensions, three routes

`novelty_distance` is **structural** (the kernel computes it), `revenue_recurrence` is **observed**
(derived from the ledger), `buyer_type` is **declared** (no query can produce it). A Cell writes none
of them, and for the declared one that is structural rather than promised.

### The refusals that carry the most

- **Attesting a party who never paid is refused** — the check a foreign key would have been, since a
  counterparty is a value on payments rather than a row. Without it a typo is a *silent no-op*: a
  valid attestation, a success message, and no descriptor moves.
- **Mixed is checked before incomplete.** Two segments among the attested buyers is monotone — no
  further attestation can unmix them — so that abstention is permanent. Checking incompleteness first
  would tell an operator to attest more buyers in the one case where it cannot help.
- **A withdrawal is not "never asked."** A withdrawn party stays present with no position, because
  somebody looking and declining to say is a different fact from nobody looking.

### Verification

- **Teeth-checked twelve ways, all CAUGHT**, including a Cell-reachable module reaching the
  attestation (§0.3) and a faithful mixed-collapse that returns a bin rather than only changing a
  reason string.
- **1092 tests and the golden run green.** `balances` identical in every account in every book — a
  declaration is not a transaction. The replay **attests twice and supersedes**, because a single
  attestation reports the same bin whether the read takes the latest row or the earliest.
- Next: §12.3's Thompson posteriors are what turn this archive into quality-diversity, and they need
  stage *conversions* — `promotion.allocate` only ever issues rung 7, so **the ladder's next rung is
  the gating build**. The Auditor path for §13.3/§13.4's content judgments is now the clearly-scoped
  other half, and ADR-032's machinery is already most of it.

## 2026-08-28 — The counterparty key unblocked one dimension and disproved the claim about the other

`counterparty.py` + **migration 0028** + 19 tests + `record-revenue --counterparty` + golden
expectations **30 -> 31** (ADR-061). §12.1's archive is **two-dimensional**.

Four tracking files said an inbound counterparty key would unblock both of §12.1's remaining
dimensions. It unblocked one, and building it is what proved the other was never blocked on it.

### A digest gives equality, never identity

`revenue_recurrence` asks whether *the same buyer paid again* — a question about equality, which is
exactly what a salted hash answers. `buyer_type` asks who the buyer **is**, and §16.3 puts customer
identity permanently outside this colony. No key can produce it; it needs a **declarer**, which is
ADR-059's missing judge in a second place. The correction is written into `novelty._buyer_type`
itself, not only into the ADR, because that is where the wrong claim was.

### Where it lives, and the one risky part

On `ledger_transactions` as a column, **inside §3.4's hash preimage** — who paid is a fact about the
payment, and this field decides whether a Cell occupies §12.1's `repeat` niche. `metadata_json` was
the tempting home and is not covered by the hash at all.

**The preimage is extended by omission.** Including the key as null on every transaction would
change every hash ever written and make `verify_chain` report every existing colony as tampered
with. Including it only when present leaves pre-0028 rows byte-identical — evidenced by the golden
run passing **unchanged** on the first full run after the ledger change, and pinned by a test that
recomputes the pre-0028 formula by hand.

### The CHECK is the guarantee, not validation

The column is declared `CHECK (length = 64 AND NOT GLOB '*[^0-9a-f]*')`, so it **cannot hold** an
email address — ADR-047's lesson twice over: a seam binds callers that know about it, a constraint
binds callers that do not exist yet. A probe table built from the migration's own text pins
`counterparty.is_hash` against it so the two spellings cannot drift.

### The cadence abstains in one direction only

`repeat` survives a partial record (more data can add a repeat, never remove one); `one_off` does
not. Aggregated across a genome's Cells, because one buyer returning to the same idea is a repeat
customer of that idea. `subscription` is unreachable — telling it from a loyal buyer needs the
service-obligation record §16.3 calls liability-linked — and `UNREACHABLE_BINS` says so rather than
leaving an absent branch.

### Verification

- **Teeth-checked twelve ways, all CAUGHT**, including both directions of the abstention rule and a
  faithful per-Cell aggregation that produces a plausible wrong bin (`one_off`) rather than none.
- **1077 tests and the golden run green.** USD_REAL identical in every account; the replay is pinned
  on `repeat` with the buyer **spelled differently** in the two payments, because `repeat` is the
  only bin whose value depends on two digests being equal.
- Next: §12.1 asks for two or three dimensions and now has two. The third needs a **declared**
  `buyer_type` with its declarer recorded — the same Auditor/human judgment path ADR-059 left
  unbuilt and ADR-060 needs for §13.4's third flag, so it is one build serving three callers. After
  that, §12.3's Thompson posteriors, still blocked on stage *conversions* while `promotion.allocate`
  only ever issues rung 7.

## 2026-08-27 — §31 lists two tables for the novelty archive, and §12.2 refuses both

`novelty.py` + 17 tests + `mitosis archive` + golden expectations **29 -> 30** (ADR-060).
**No migration.** `structural_novelty` wired into §13.2's frontier.

ADR-059 shipped the selector with `structural_novelty` abstaining and ADR-058 scored one of §13.4's
four flags, both for the same reason: **there was nothing to be novel against.**

### The clause that removed the tables

> **§12.2** Store full raw behavioural descriptors **separately**; the archive is a **derived
> view**, allowing later rebuilding with different dimensions and bins.

Read as an instruction it says "make a table". Read for what it protects, it says the archive must
not *be* the record — and in this kernel the raw material already lives separately and in better
custody: `cell_genomes` is content-addressed (§16.1) and append-only. A `behavioural_descriptors`
table would be the second version §2.5 refuses, and §31 offers "suggested entities" rather than a
build order. **Third and fourth §31 entity that §2.5 has removed** (after ADR-043, ADR-044).

### One of §12.1's three dimensions is live, and the block on the other two is specific

`novelty_distance` is structural. `buyer_type` and `revenue_recurrence` both need to know *who
paid*, and `revenue.record_revenue` records that as free text — so two payments from one buyer are
indistinguishable from one each from two. **The colony already solved this outbound**: §21.2's
`external_action_registry` stores a salted hash of a counterparty, equality without identity, exactly
as §16.3 requires. Naming the asymmetry beats guessing: counting payments per *Cell* would report a
Cell with three one-off customers as `repeat`.

### The bins are §13.4's language, not a threshold anyone chose

**adjacent** = the nearest earlier genome differs in exactly one business field, which is §13.4's
first flag as a distance. **moderate** = more than one, but some earlier genome shares its `market`.
**radical** = no earlier genome shares its `market` (§16.3 makes the market hypothesis what keeps a
lineage that lineage).

**Radical is checked first**, and that ordering is load-bearing — a genome whose only changed field
*is* the market would otherwise be filed as a relabel, inverting §13.4 rather than applying it.
**Zero distance is a real case**: a genome differing only in `risk_class` or `allowed_tools` gets a
new content hash and the same hypothesis, so it bins `adjacent` with its own reason. Otherwise a Cell
could reach a further niche by asking for permissions instead of by having an idea.

**It is a distance, not a merit.** A small one is evidence of §13.4's first flag; a large one proves
nothing, since a genome changed to nonsense scores `radical`. Being a Pareto axis rather than a score
is what makes it safe to ship: nothing is funded for being radical.

### Verification

- **Teeth-checked eight ways**, and **two came back MISSED** — the §13.4 flag keyed on a field count
  rather than on the market, and niche occupancy counting genomes instead of Cells. Both fixtures
  could not distinguish the two behaviours; rewritten, both now CAUGHT. The second one the golden
  replay also cannot catch, because its two niches happen to hold as many Cells as genomes.
- **1058 tests and the golden run green.** Only the `selection` section changed
  (`structural_novelty` null -> 0.0) plus the new `novelty_archive` section; **`balances` identical
  in every account in every book**, because the archive is derived and writes nothing.
- Next: an **inbound counterparty key** is what unblocks two more §12.1 dimensions and with them a
  two- or three-dimensional archive. Then §12.3's Thompson posteriors — which need stage
  *conversions*, and `promotion.allocate` only ever issues rung 7, so the ladder's next rung comes
  first.

## 2026-08-27 — §13.2's selector: four of its nine dimensions have no data

`selection.py` + 21 tests + `mitosis frontier` + golden expectations **28 -> 29** (ADR-059).
**No migration.** `promotion.transfer_degradation` made public; `UNINFORMATIVE_BRIER` moved to
`prediction.py`.

PRIORITIES asked for the selector that consumes ADR-058's concreteness measure. §13.2 says what one
is: *"Reject candidates below minimum thresholds on evidence quality, reproducibility, policy
compliance, and software-native advantage; then select from a Pareto frontier over structural
novelty, information gain, economic potential, experiment cost, and transfer robustness. Do not rely
on a single weighted scalar."*

### Five of the nine are measurable here; four abstain

| live | unmeasurable, and why |
|---|---|
| evidence quality (§8.5, bar = `UNINFORMATIVE_BRIER`) | reproducibility — §11.2's adoption record |
| policy compliance (§18 quarantine, §23.4 signals) | software-native advantage — §13.3 judges *content* |
| information gain (entropy of the filed forecasts) | structural novelty — §31's `novelty_archive` |
| experiment cost (§13.1's first consumer) | economic potential — no proper scoring rule over it |
| transfer robustness (§25.2's degradation) | |

**An unmeasurable dimension abstains and never scores zero** — `structural_novelty = 0.0` is a claim
about the idea; `None` is the truth. `UNEVALUABLE` (a new Cell) and `UNMEASURABLE` (no data anywhere)
stay separate for the reason §25.2 splits `INSUFFICIENT_EVIDENCE` from `EVIDENCE_WITHHELD`.

### Why one self-reported number is safe and another is not

`information_gain` comes from the Cell's own forecasts, and §8.5 is what makes that admissible:
**Brier is a proper scoring rule**, so overstating uncertainty loses points at resolution and the
register is hash-chained before the outcome is knowable. `economic_potential` has no such rule, so
§0.3 stands and the module declines. **That contrast is what "no single weighted scalar" protects** —
the axes hold each other honest only while they are separate.

The exception is named rather than hidden: `experiment_cost`'s numerator is the Cell's own estimate,
and nothing yet compares it with what the experiment consumed.

### ADR-058's concreteness measure is not wired in, and that is the finding

Concreteness judges an idea's *content*, which is §13.3's category — and §13.2 puts that behind a
human or an independent Auditor. The kernel is excluded by §23.5 and by the AST boundary this repo
added one slice ago. **So concreteness enters §13.2 as `software_native_advantage`'s missing judge,
not as an axis.** The shape of the gap is now written down instead of assumed.

### Verification

- **Teeth-checked nine ways** — sign flip, gates not removing, frontier over rejected candidates,
  unmeasured rejected instead of unevaluable, three abstain-becomes-zero mutations,
  `understated_risk` escalating, and domination reading an unmeasured axis as zero. Each failed the
  test written for it.
- **An existing guard caught a real mistake.** `test_no_kernel_path_acts_on_an_assessment` failed the
  moment `selection` imported `outcome` for two constants, and it was right to — a selector that can
  see a §25.2 verdict is one edit from acting on it. `UNINFORMATIVE_BRIER` moved to the scoring rule
  that defines it; the count threshold became this module's own number.
- **The golden section would have been born dead** — every grant the scenario made was consumed by
  the step that made it, the shape ADR-045 found here once already. Step 19f leaves one approved,
  unallocated candidate, from the Cell with a rung-7 promotion so `experiment_cost` resolves to 0.4
  rather than abstaining. **`assessments.forecasts_made_while_funded` moves 0 -> 2 with the verdict
  unchanged** — §23.5's exclusion demonstrated for the first time.
- **1040 tests green; USD_REAL and USD_SIM identical in every account.** Only RESOURCE moved, by 2
  minor units of metering for a mock call priced at zero.
- Next: three axes is a frontier, not quality-diversity. §31's `novelty_archive` and
  `behavioural_descriptors`, §11.2's adoption record, and an Auditor path for content judgments —
  in that order, since the archive also unblocks §13.4's other three flags.

## 2026-08-27 — The concreteness measure is §13.4, and the instrument had never been measured

`scripts/concreteness.py` + a labelled fixture + `scripts/genomes/loose.json` + `--genome` on the
arm harness + `tests/test_analysis_boundary.py` (3 tests). **No kernel change, no migration**
(ADR-058).

PRIORITIES asked for ADR-056's concreteness measure as the Phase 2 counterweight to selecting on
variety alone, noting it "is not yet anywhere in the repo". It never had been: it lived in a scratch
script and was gone by the next session — *the day after* `scripts/` was created to stop exactly
that.

### The spec had named it, and this repo never had

> **§13.4** Flag ideas where only the industry label changed, ordinary freelancing is described
> exotically, the same mechanism is renamed, or **no new capability/transaction structure exists**.
> **§13.5** LLMs are skilled at producing rhetorically novel but structurally ordinary ideas.

§13.5 is ADR-056's finding written down before any of it was measured. **§13.4 appears nowhere in
PRIORITIES, FUTURE_BUILD_HOOKS or DECISIONS before this slice** — the sixteenth reserved socket, and
the first found by reading a *justification* clause rather than a mechanism clause. It also settles
the Phase 2 warning in the spec's vocabulary: §12.1 makes `novelty distance` a MAP-Elites
*descriptor*, and §13.4 is what stops a Cell cheating it.

### The instrument was measured before its numbers were read

The judge is asked to **quote** the words naming a specific thing, and the verdict is then decided
deterministically — every content word of the quote must really be in the summary (§24.3:
"verification → deterministic tools first, model second"). It may not be the generator's family
(§24.3), which the script enforces by reading `model_calls.requested_model` and refusing.

| rubric | agreement (24 labelled) | missed a real deliverable | invented one |
|---|---|---|---|
| first draft | 18/24 | 6/9 | 0 |
| shipped | **19/24** | **5/9** | **0** |

**Every error is one-directional**, and safely so: an arm with no objects has none to miss, so the
bias understates a gap and never manufactures one. `--selftest` therefore gates on **false
positives, not agreement** — gating on agreement would gate on a number in the same file, this
repo's recurring way of writing a test that passes for the wrong reason.

### The replication

| arm | parsed | **names a deliverable** | ideas@2 |
|---|---|---|---|
| `genome_tight` | 36/64 | **13/36 = 36%** | 1.524 ± 0.056 |
| `genome_loose` | 14/64 | **0/14 = 0%** | 1.467 ± 0.065 |

**Fisher exact one-sided p = 0.0065.** Not one of the loose arm's fourteen proposals named a single
object of its own business in eight independent runs. **ADR-056's diversity null replicates** (1.524
vs 1.467 at matched n, against its 1.513 vs 1.612) — diversity and concreteness still move
independently.

**ADR-056's 100% vs 5% does not replicate and cannot**: the rubric that produced it was lost with
its script, so the two are not measurements of one quantity. The direction, the completeness of the
separation and the independence from diversity are what was load-bearing, and all three hold. An
absolute rate from a lost instrument is not a result.

### Verification

- **Teeth-checked six ways.** Three mutations of the deterministic verifier (`all`→`any`, stopwords
  unstripped, empty quote counted as present) each failed the case written for it; three of the
  boundary tests (a scorer importing the kernel, `deliberation` importing the scorer
  function-locally, the scripts directory vanishing so the guard forbids an empty set) each failed
  the named test. One vacuity case was rewritten after the first teeth-check MISSED — the original
  gave the same answer with and without the bug.
- **1019 tests and the golden run green**, hash unchanged: nothing under `src/` was touched.
- Next: the counterweight exists; the **selector that consumes it** does not. §13.2 says hard gates
  then a Pareto frontier, never a single weighted scalar. Otherwise open: ADR-050's model question
  and §14's mutation operators.

## 2026-08-27 — The +15% does not survive honesty

A measurement (correction to ADR-055). **No code changed.**

ADR-055 measured +15% diversity from varying the wake reason, flagged that part of it was the Cell
believing false premises, and said to argue the wiring "on correctness, not on the 15%". ADR-057
wired the one genuinely missing reason. This re-measures with reasons **earned**, wakes drained from
the inbox rather than set by hand.

| arm | parsed | **ideas@3** | reasons that drove deliberations |
|---|---|---|---|
| `unreviewed` | 31/64 | 1.802 ± 0.286 | 64 scheduled |
| `reviewed_flat` | 29/64 | **1.809 ± 0.213** | 64 scheduled (approvals happen, wake suppressed) |
| `reviewed_earned` | 31/64 | **1.827 ± 0.248** | 37 scheduled + **27 human decision** |

**`reviewed_flat` vs `reviewed_earned` is the experiment** — both approve everything, so the standing
strategy, grants and every other approval side-effect are constant and only the reason varies.
**+0.018 (+1%), higher in 41% of pairs, p = 0.73.** A null.

### What it retires, and what it does not claim

ADR-055's +15% was an artifact of rotation. Its own caveat — 3/38 proposals responding to events that
never happened — understated it: strip the falsehoods and essentially nothing remains.

**It does not show wake reasons cannot matter.** ADR-055 rotated *eight* reasons across eight wakes,
including ones a real colony rarely emits in sequence; a reviewed colony earns *two*. The honest
claim is **"at the variety a real colony actually produces, the effect is nil"** — a colony running
tools, allocations and audits would earn more, and this says nothing about that.

**ADR-057 was right to ship and right about why.** It was argued on §17.2 conformance and §25.2's
feedback loop, never on the number, and told the reader to expect less than +15%. It came back at
+1%. The instruction to argue it on correctness is now measured-correct rather than merely prudent.

### The self-repetition ledger closes harder

| candidate (ADR-052) | verdict | effect |
|---|---|---|
| §15.1 anchoring | confirmed, **fixed** | **+86%** |
| identical wake reason | confirmed by rotation, **~0% once honest** | +1% (p = 0.73) |
| genome pinning | rejected | none (p = 0.21) |

**Two of the three candidate causes were worth nothing once measured properly**, and the residual
~1.8–2.0 effective ideas per run of 8 is the model's ceiling.

### Verification

- **Instrument checked before the numbers counted:** 27 genuinely earned `human decision` wakes drove
  42% of `reviewed_earned`'s deliberations, while both controls stayed at 64 scheduled and zero.
- **The confound ADR-053 taught was designed out.** Comparing reviewed against unreviewed would have
  measured "does having an operator help" and reported it as "does the wake reason help";
  `reviewed_flat` exists to hold that constant.
- **1016 tests and the golden run green** — untouched.
- Next: nothing further on self-repetition from context assembly; the ground is measured. Open work
  is ADR-050's model question, §14's mutation operators, and Phase 2.

## 2026-08-27 — A human decision wakes the Cell it was about

`approval._wake_on_human_decision_locked` + 6 tests + golden expectation **27 -> 28** (ADR-057).
No migration.

ADR-055 queued "wire real events to the wake reasons they justify". **Auditing that found a smaller
and more specific gap than the ADR had claimed, and corrected the ADR's own target.**

### Six of seven reasons were already earned

`WAKE_TOOL_RESULT` by `tools.py`, `WAKE_CAPITAL_ALLOCATION` by `promotion.py`, `WAKE_AUDIT_REQUEST`
by `auditor.py`, `WAKE_EXTERNAL_ACTION_RESULT` by `external_actions.py`, `WAKE_APPROVAL_EXPIRED` and
`WAKE_GRANT_EXPIRED` by the sweep. **ADR-055's "only the scheduler's tick is hardcoded" was wrong
twice:** the tick is *honest* — a scheduled tick genuinely is a scheduled research cycle — and the
real gap was elsewhere. **`WAKE_HUMAN_DECISION` was defined and referenced nowhere else** — the
fifteenth reserved socket, and the only entry in §17.2's list with no producer.

### What shipped

`approve` and `reject` now enqueue `WAKE_HUMAN_DECISION` **inside their own transactions**, following
`expire_due`'s pattern, so a committed decision and its wake cannot come apart. Idempotent on the
request (Charter C6). Silent for a dead or quarantined Cell, because `deliberate` *records* a refusal
rather than raising, and waking one would turn every decision about a dead Cell into a deliberation
row saying it could not think (C8). **Expiry keeps its own reasons** — the review window closing is
not a judgement, which is the line `_decision_note` already refuses to blur.

It matters most for rejection: ADR-053 established a rejection has no other channel at all, and §25.2
wants the reasons for promotion *or rejection* to reach the Cell.

### Verification

- **Teeth-checked five ways, all caught**: no wake on approve; no wake on reject; dead Cells woken;
  a dedupe key not derived from the request; and **expiry relabelled as a human decision** — the most
  tempting way to make this fire more often and exactly the falsehood ADR-055 exists to prevent.
- **Golden diff is one section.** `event_inbox` `cell_wake` rows **9 -> 20**, the scenario's 11
  decisions, counted directly. **`deliberations`, `proposals` and `model_calls` are byte-identical**
  — the scenario never drains the inbox, so this adds a wake and changes nothing any Cell thought —
  and **`balances` is identical in every account in every book**.
- **The golden scenario now exercises six distinct wake reasons**, up from five.
- **A structural test asserts every §17.2 reason has a producer**, so the next one added is either
  wired to the event that justifies it or listed deliberately as inert.
- **1016 tests passing** (6 new; up from 1010).
- Next: the honest re-measurement ADR-055 could not do — with reasons now earned rather than
  rotated, is any of its +15% real? A colony that ticks and is reviewed produces `human decision`
  wakes naturally, so the arm is a scheduled run with an operator deciding, against one without.

## 2026-08-27 — The genome is not the constraint; it is what makes a proposal concrete at all

A measurement (ADR-056). **Hypothesis rejected. No code changed.** This closes ADR-052's third and
last candidate cause.

| arm | parsed | ideas (all) | **ideas@2** | **names a concrete deliverable** |
|---|---|---|---|---|
| `genome_tight` | 26/64 | **1.887** | 1.513 ± 0.111 | **26/26 (100%)** |
| `genome_loose` | 19/64 | 1.718 | 1.612 ± 0.165 | **1/19 (5%)** |

**Diversity: no effect** — +0.099, 65% of 48 pairwise comparisons, p = 0.207, and on the
all-proposals measure the *tight* genome scores higher.

### The pre-registered check is the finding

It was written into the script before the arm ran (the habit ADR-055 earned): a loose genome could
raise a diversity score by making proposals vaguer rather than more varied. It raised no score — and
concreteness collapsed anyway, **100% → 5%**, at nearly identical summary length (83 vs 87 chars).
The loose arm is not shorter, it is emptier: *"Refine our software to reduce routine back-office
work"*, *"Invest in customer support"*. One proposal asked to **"Send reminder about the upcoming
scheduled research cycle"** — a Cell with no market hypothesis proposing about its own scaffolding,
because that was the only concrete noun left in its context.

### So the genome has a second job nobody had written down

§16.3 makes the market hypothesis inheritable so a lineage stays that lineage. This measures the
other thing it does: **it is the only part of the context that tells a Cell what a proposal is
*about*.** Remove the specificity and the Cell still proposes, parses less often, and says nothing.

### The search for prompt-level causes is complete

| candidate (ADR-052) | verdict | effect |
|---|---|---|
| §15.1 anchoring | confirmed, **fixed** | **+86%** |
| identical wake reason | confirmed, remedy refused | +15% |
| genome pinning | **rejected** | none (p = 0.21) |

**The residual ~2 effective ideas per run of 8 is the model's ceiling on this hardware, not a defect
in the prompt.** Anything further is a model decision (ADR-050) or a §14 mutation-operator decision,
not a context-assembly one.

### Verification

- **Instrument checked**: the genome section is present in the prompt in both arms; the concreteness
  and length comparisons are computed over all proposals, not a sample.
- **1010 tests and the golden run green** — untouched.
- **A concreteness measure now exists and is worth keeping.** It separated two arms the diversity
  score could not tell apart, and it is the first metric here that asks whether a proposal is *worth*
  anything rather than whether it differs from its neighbour.
- Next: **Phase 2 warning recorded** — diversity and concreteness move independently, so selection
  tuned on variety alone would favour exactly the Cells that have stopped saying anything.

## 2026-08-27 — The wake reason matters, and rotating it makes a Cell act on things that never happened

A measurement and a refusal (ADR-055). **No code changed.**

ADR-052's second candidate cause: `Why you were woken` renders the wake reason verbatim, the
scheduler emits `scheduled research cycle` every time, so nothing in the prompt ever says the
situation changed. Two arms, **12 runs × 8 wakes each** — deepened from 4 after the first pass came
back at p = 0.11, the underpowered profile that produced four withdrawn claims earlier in this thread.

| arm | runs | parsed | **ideas@3** |
|---|---|---|---|
| `wake_same` (shipped) | 12 | 46/96 | **1.764 ± 0.220** |
| `wake_varied` | 12 | 38/96 | **2.025 ± 0.217** |

**+0.261, 80% of 100 pairwise comparisons, exact one-sided p = 0.0116.** Parse-rate difference not
significant (p = 0.31). **The hypothesis holds and is the smallest of the three** — anchoring was
+86%, this is +15%.

### The remedy this invites is dangerous, and the arm proved it

The experiment asserted reasons rather than earning them — no tool result had arrived, no capital had
been allocated. That was flagged in the script *before* it ran, which is why the output was checked
for it. **Three of 38 proposals in `wake_varied` responded to an event that never happened**, against
**zero of 46** in the control:

- *"Notify bookkeepers of an available tool result and request a review…"*
- *"Email notification about available tool results to bookkeeping community forums"*

The Cell was told a tool result was available, believed it, and proposed **contacting customers about
it**. With an approved `external_action` grant and §27.1 autonomy on, that is a real email about a
result that does not exist. **Part of the measured +15% is that failure**, so the effect size for
*honest* wake reasons is smaller than 0.261 and this measurement cannot say by how much.

### §0.3 from the other side

The clause says a Cell may explain a result and never define it. The mirror is that **the kernel must
not assert to a Cell something that is not so.** `Why you were woken` is `required=True` and never
dropped, so whatever it says is read every wake, and a Cell cannot tell a scheduler placeholder from
a real event.

### Verification

- **Deepened rather than reported.** The first pass read +0.355 at p = 0.11; deepening moved the
  estimate *down* and the confidence up. Acting on it would have overstated the effect and still
  landed on the dangerous remedy.
- **Instrument checked:** 8 distinct reasons reaching the prompt against 1.
- **The false-premise check was pre-registered in the script docstring**, not invented after seeing a
  number worth defending.
- **1010 tests and the golden run green** — untouched.
- Next: wire real events to the reasons they justify (`WAKE_TOOL_RESULT`, `WAKE_CAPITAL_ALLOCATION`
  and the rest are all defined; only the scheduler's tick is hardcoded). Argue it on correctness, not
  on the 15%. Then the last candidate cause: the genome pinning market/problem/product.

## 2026-08-27 — Showing a rejected proposal's wording causes the §23.4 repeat it was meant to prevent

A measurement (ADR-054). **No code changed — the rule shipped hours earlier is confirmed by the
experiment queued to challenge it.**

ADR-053 hid the proposal-log summary for every status and left one known cost: a rejected proposal
loses its subject. Every other kind keeps a channel (approval's substance arrives on grant
consumption); a rejection has none. Restoring the wording for rejections only was the obvious remedy,
pinned by a test rather than shipped. Two predictions genuinely diverged — anchoring (the Cell copies
what it sees) versus learning (`REJECTED` steers it away) — so it needed an arm.

### The instrument was already in the kernel

§23.4's `repeat_after_rejection` compares normalised summaries and persists to `approval_signals`. It
answers the question directly, with no metric of mine standing between it and the answer.

| arm | parsed | ideas@3 | **§23.4 repeats fired** |
|---|---|---|---|
| `reject_shown` (wording restored) | 20/32 | **1.210** | **12** |
| `reject_hidden` (shipped rule) | 13/32 | **1.922** | **0** |

`reject_hidden` wins on diversity in **100% of 12 pairwise comparisons**.

### The remedy causes the failure it was meant to prevent

Twelve `repeat_after_rejection` signals against zero. **A Cell shown the wording of a proposal a
person just rejected proposes it again** — the feature intended to teach it what not to repeat is
what makes it repeat. `REJECTED` is not read as a negative instruction any more than `APPROVED` was
read as a positive one (ADR-053): **the label is not a modifier on the text beside it**, now measured
twice from opposite signs.

So the lost subject is the *price* of the rule, not a debt to repay.
`test_a_rejected_proposal_loses_its_subject_and_that_is_recorded` stays as the written-down cost, and
this entry is why it is not a TODO.

### Verification

- **Instrument checked before the numbers counted:** 20 and 13 rejections made, run-0 statuses all
  `rejected` in both, section medians **76 vs 36 tokens** confirming wording present and withheld.
- **Parse rate rose while the colony got worse** — 20/32 against 13/32. A Cell re-proposing a
  known-good shape parses more easily. **The clearest instance yet of ADR-050's theme:** anything
  tuning on parse rate alone would have chosen the arm that breaks §23.4.
- **1010 tests and the golden run green** — untouched, which is the point: this is a live-only
  property that no replay can see.
- Next: §15.1's remaining candidate causes for self-repetition — the genome pinning
  market/problem/product, and the identical wake reason on every wake. Anchoring is now fixed and the
  colony sits at ~2.1 effective ideas per run of 8; those two are what stands between that and 3.

## 2026-08-27 — The proposal log shows no wording at all

`context._was_decided` deleted, the section heading corrected, 6 tests, golden expectation
**26 -> 27** (ADR-053). No migration.

§15.1's proposal log now renders `- [kind]\n    -> note` for every status. ADR-053 measured that an
approved summary anchors exactly as hard as a pending one (1.122 shown vs 1.764 hidden, approvals
held constant), so the status-conditional gate ADR-052 shipped was guarding the wrong thing.

**Confirmed live at 2.122 effective ideas per run** — against 1.833 under the conditional rule and
1.089 before either — with every parsed proposal distinct in all four runs. Parse rate 17/32.

### The per-kind audit contradicted ADR-053's own inference

ADR-053 assumed the other kinds' approvals reached the Cell the way `STRATEGY`'s did. Three of four
were wrong. With the summary hidden:

| kind | does the approved substance still reach the Cell? |
|---|---|
| `strategy` | **yes, immediately** — `Your standing strategy` |
| `experiment` | **yes, once the grant is started** — `Your current experiment` |
| `tool_request` / `external_action` | **yes, on consumption** |
| **any kind, rejected** | **no** — the reason survives, the subject does not |

Approval's consequence arrives **when the grant is consumed**, not when it is granted; `STRATEGY`
looked immediate only because approving it *is* the act, so there is nothing to consume.

### One real cost, pinned rather than fixed

**A rejected proposal loses its subject.** The Cell learns that it was rejected and why, not what.
`test_a_rejected_proposal_loses_its_subject_and_that_is_recorded` asserts it so it cannot become a
surprise; fixing it means showing rejected summaries, which reintroduces the anchoring, and that
trade is a §23.4 question deserving its own arm. §23.4's `repeat_after_rejection` detector is now the
only thing watching for the repeat this invites.

### Verification

- **Teeth-checked three ways**, all caught, including a regression back to **ADR-052's own gate** —
  so the refuted design cannot quietly return.
- **The history-bound test had gone silently vacuous a second time.** It matched on probe wording,
  which no longer renders, so it passed while measuring nothing. It now **counts entries** in the
  log — the thing §15.1's bound actually governs — and separately asserts no wording leaks anywhere
  in the render, which catches a different section dumping history.
- **Golden diff is eight deliberation rows of eleven**, `context_tokens` only; the three that do not
  move are the wakes with no proposal log. `model_calls` and `resource_usage` follow;
  `resource_usage.minor_units` moves on no row, so **`balances` is identical in every account in
  every book** and `proposals` is byte-identical.
- **The heading was corrected too** — it claimed to show "your own prior words", which stopped being
  true. ADR-052 measured heading edits at zero behavioural effect, so it is carried as pure accuracy.
- **1010 tests passing** (1 net new; up from 1009).
- Next: whether to restore the summary **for rejections only**, measured rather than argued — the
  one case with no other channel, against the anchoring it would reintroduce.

## 2026-08-27 — An approved summary anchors exactly as hard

A measurement (ADR-053). **No code changed** — the remedy is the third design iteration on this
section and needs its own twins run first.

ADR-052 shipped `_was_decided` on a branch it had never measured: every arm behind it left every
proposal `pending`, because an unattended colony queues and nobody reviews. Both the ADR and
`_was_decided`'s docstring said so and named this as the result that would move the line. It does.

Approving does more than reveal a summary — it sets a standing strategy, issues grants, changes what
§15 assembles. So three arms, `llama3.2` t=0.8, 4 runs × 8 wakes:

| arm | approvals | section | parsed | **ideas/run** |
|---|---|---|---|---|
| `decided_shown` | every proposal | 64 tok, summaries **present** | 13/32 | **1.122** |
| `decided_hidden` | every proposal | 35 tok, summaries withheld | 14/32 | **1.764** |
| `pending` (shipped default) | none | 21 tok, summaries withheld | 18/32 | **2.195** |

`decided_shown` vs `decided_hidden` holds every approval side-effect constant and varies only whether
the summary renders. **`decided_hidden` is higher in 100% of 16 pairwise comparisons.**

### Approval makes no difference to anchoring

`decided_shown` scores **1.122** — the original pre-ADR-052 control was **1.089**. The anchoring
returns in full the moment the summary is visible, approved or not. **A Cell copies text it can see;
the annotation beside that text is not what it is reading.** So ADR-046 and diversity are in genuine
conflict on the branch that shipped, and the current rule is safe only in a colony nobody reviews.

### ADR-052's reason for showing it was wrong, and that is the way out

The reasoning was "APPROVED is meaningless if the Cell cannot tell *what* was approved." An approved
strategy in fact reaches the Cell through **two** sections — the proposal log and `Your standing
strategy (your words, approved by a person — this is how you operate)`, a dedicated independent
channel. **ADR-046's delivery for `STRATEGY` never ran through the proposal log**, so the summary
there is redundant for the one kind ADR-046 is about. Likely the same for the others — an approved
experiment reaches the Cell through the current-experiment section, a tool through its grant — but
that is inferred, not measured.

### Verification

- **Instrument checked before the numbers counted**: 13 and 14 approvals against 0, run-0 statuses
  all `approved` against all `pending`, section medians **64 / 35 / 21 tokens** confirming summaries
  present, withheld, withheld. (35 > 21 because an approved entry's decision note is longer.)
- **The confounded comparison is reported and not used.** `pending` vs `decided_shown` shows the
  right direction and attributes it wrongly; `decided_hidden` is the arm that isolates the summary.
- **A second finding, separate:** `decided_hidden` (1.764) scores below `pending` (2.195), so
  approval itself costs diversity through its other effects — a standing strategy is a strong
  instruction and the Cell follows it. Not obviously a fault.
- **1009 tests and the golden run green** — untouched, which is the point: this is a live-only
  property and no replay can see it.
- Next: verify each kind's approval still reaches the Cell with the proposal-log summary gone
  (`STRATEGY` is confirmed; experiment, tool and external-action are inferred), then a twins run on
  hiding it unconditionally. **Not shipped on this measurement alone** — §14.2 caught ADR-052
  reasoning instead of measuring once already.

## 2026-08-26 — A recent proposal shows its wording only once a person judged it

`context._was_decided` + 5 tests + golden expectation **25 -> 26** (ADR-052, implementing what its
twins chose). No migration.

§15.1's proposal log now renders `- [kind]\n    -> note` for an undecided proposal and keeps the
summary once a person judged it. This is the pending-only variant ADR-052 recommended — narrower
than the `nosummary` arm that won, because that one hides the summary even on the decided proposals
ADR-046 exists to deliver.

### The line is drawn where `_decision_note` already drew it

**`expired` is not decided**, and that is the one judgement ADR-052 did not settle — its arms had no
expired proposals. The docstring of `_decision_note` refuses to collapse "nobody looked" into "was
judged", so a closed review window withholds the summary like any other undecided state. It is the
status that looks decided and is not, which is why it gets its own test.

### Verification

- **Confirmed live, because no replay can see a prompt edit.** The shipped kernel scores **1.833
  effective ideas per run** against ADR-052's arm at 1.852 and control at 1.089 — every parsed
  proposal distinct in all four runs. `MockProvider` cannot show this, which is the whole reason
  ADR-052 existed.
- **Teeth-checked three ways**, each caught by a named test: always-decided (the old behaviour),
  never-decided (the `nosummary` arm, which deletes ADR-046), and expired-counted-as-decided.
- **Two existing tests failed for the right reason and were repaired, not weakened.**
  `test_context_never_loads_the_entire_history` detected history-loading *through* the summaries, so
  hiding them made it **silently vacuous** (`got []`) rather than red — it now approves its probes,
  which restores the detection and tests the leaky case: the slice must stay bounded even when every
  entry is fully shown. `test_an_unreviewed_proposal_is_distinguishable_from_an_expired_one` lost its
  summary prefix, so it asserts **order** instead, which is what still ties each note to its proposal.
- **Golden diff is two rows of eleven**, and only `context_tokens` — the only two wakes in the
  scenario that assemble a non-empty proposal log. `model_calls` and `resource_usage` follow in the
  matching rows; `resource_usage.minor_units` is unchanged at 1, so **`balances` is identical in
  every account in every book** and `proposals` is byte-identical.
- **1009 tests passing** (5 new, 0 removed; up from 1004).
- Next: an arm that **approves proposals mid-run**. Nothing measured yet exercises the decided
  branch, so nothing shows whether a Cell anchors to an *approved* summary too — the one result that
  would put ADR-046 and diversity back in genuine conflict and move this line.

## 2026-08-26 — The Cell copies what it can see, and cannot be instructed out of it

§14.2 counterfactual twins on §15.1's recent-proposals section (ADR-052). **No code changed** — the
recommendation moves the golden run, which Amendment A12 makes a separate reviewed act.

ADR-051 confirmed the section anchors the Cell and parked three candidate rewordings. Each is one
edit relative to control; all `llama3.2` t=0.8, same genome, one batch, Vendi matched at 3 proposals
per run. `control` and `nosummary` deepened to 12 runs once the first pass named them the pair that
mattered.

| arm | one-line edit | runs | parsed | **ideas@3** |
|---|---|---|---|---|
| `control` | as shipped | 12 | 52/96 | **1.089 ± 0.147** |
| `heading` | heading names the expectation | 4 | 15/32 | **1.054 ± 0.078** |
| `exclusion` | each entry marked "do not propose again" | 4 | 12/32 | **1.202 ± 0.176** |
| `nosummary` | body drops the summary, keeps kind + decision | 12 | 40/96 | **1.852 ± 0.248** |
| `suppressed` | section absent (ADR-051's ceiling) | 4 | 20/32 | 1.939 ± 0.138 |

`nosummary` beats `control` in **89 of 90 pairwise run comparisons** and recovers **95% of the
suppression ceiling** with the section still rendering.

### ADR-051 predicted the wrong winner, and the reason generalises

ADR-051 nominated the heading edit, reasoning from ADR-049 that naming an absent expectation makes a
model meet it. **It measured at zero** (1.054 vs 1.089). An explicit per-entry "do not propose again"
bought 15%. Removing the copyable text bought everything. **The Cell is not disobeying an instruction
to vary — it is completing a pattern it can see**, and an instruction aimed at a copying behaviour
does not reach it. Assume that for the next prompt-driven behaviour someone tries to fix with a
sentence.

### The recommendation is narrower than the arm that won

**All 52 control proposals are `pending`** — zero approved, zero rejected, because an unattended
colony queues and nobody reviews. So ADR-046's channel carried nothing in any arm, and `nosummary`
cost it nothing *only because it was never exercised*. That is also why `nosummary` sits so close to
`suppressed`: with everything pending its body reduces to `- [experiment] -> waiting on a person`.

So the two goals are **separable, not in tension**: the summaries doing the anchoring are on entries
that convey no decision. Hide the summary for `pending`/`not reviewed` and keep it for
`approved`/`rejected` — identical to `nosummary` in the measured regime, so it inherits the full
gain, while ADR-046 keeps exactly what it needs.

### Verification

- **Instrument checked with something that can fail.** The first check grepped `context_json` for
  body text, but `Section.to_record()` stores only name, tokens and `required` — it could never pass,
  and reported BROKEN against manipulations that were correct. Replaced with token counts: control's
  section median **81 tokens**, `nosummary`'s **21**, both present. Variants also verified by
  rendering them directly.
- **A missing `__main__` guard cost the control arm.** Importing the experiment script to inspect its
  variants re-ran the batch and overwrote four databases mid-flight — caught from an mtime later than
  the arm that ran after it. Guard added, control re-run from scratch, and the other four arms
  verified intact at 32/32 before use.
- **The parse-rate difference is not claimed**: 40/96 vs 52/96 is p = 0.11.
- **1004 tests and the golden run green.** Zero USD_REAL in any arm.
- Next: implement the pending-only variant (a golden-run expectation bump under A12), and an arm that
  **actually approves proposals mid-run** — nothing here shows whether a Cell anchors to an *approved*
  summary too, which is the one result that would put ADR-046 and diversity back in real conflict.

## 2026-08-26 — The Cell repeats itself because §15.1 shows it what it just said

A measurement and a refusal (ADR-051). **No code changed, no migration, no test added.**

ADR-050's third correction left one question at the front: a Cell proposes ~1 effective idea per run
of 8 wakes, at any temperature, on either model — why? FUTURE_BUILD_HOOKS parked three candidate
causes. This tests the first.

`context.RECENT_PROPOSALS = 0` suppresses §15.1's recent-proposals section entirely. Single variable:
context was 833 tokens against a 1200 budget with `dropped: []`, so nothing else moves. Both arms
`llama3.2` t=0.8, 4 runs × 8 wakes, **same script** — the control was re-run rather than reused,
because this thread has twice been bitten by instrument differences.

| arm | parsed | proposals/run | **ideas/run (Vendi, matched at 3)** |
|---|---|---|---|
| section shown (control) | 11/32 | 2.75 | **1.053** |
| section suppressed | 17/32 | 4.25 | **1.957** |

**An 86% increase in effective distinct ideas**, and in the suppressed arm *every parsed proposal was
distinct* (4/4, 3/3, 5/5, 5/5).

### Corroborated for free, before anything was run

**Wake 0 of every run has an empty section by construction.** Vendi over the four unanchored
first-proposals from four independent colonies is **1.970** (`llama3.2`) and **1.917** (`qwen2.5`),
against 1.048 and 1.216 inside an anchored colony. That comparison varies two things at once — which
is why the direct experiment was run — but it lands on the number the clean manipulation produced.

### The obvious remedy is refused

Deleting the section is the change this result invites and it is wrong. **ADR-046 is built on it:**
a `STRATEGY` proposal has no consumer and no regeneration — approving it *is* the act, and the
decision annotation in this very section is the whole mechanism by which the act reaches the Cell.
Remove it and that subsystem stops working with **no test failing**, because what it delivers is
prose in a prompt. §15.2 also requires episodic memory, and a Cell that cannot see what it proposed
cannot notice it is repeating; the gain would be amnesia, not judgement.

So the remedy is what the section *says*, not whether it appears — a prompt change, which §14.2 says
must face counterfactual twins rather than ship on one measurement. The cheapest candidate: the
section is titled "reference material, not instructions" and never states that a *new* proposal is
wanted. **Naming the absent expectation is the move ADR-049 already made** when it found the prompt
named no field the parser rejects.

### Verification

- **The instrument was checked, not trusted.** The script asserts the section is absent from every
  assembled `context_json` in the suppressed arm and present in the control. Both passed — a
  manipulation that silently fails to reach the prompt gives a null result indistinguishable from a
  real one.
- **Matched at 3 proposals per run**, because Vendi scales with item count and the treatment arm
  produced more proposals (4.25 vs 2.75). Unmatched the gap reads 2.334 vs 1.040; the honest figure
  is 1.957 vs 1.053.
- **The control replicated the committed n=32 arm exactly** — 11/32 parsed, Vendi 1.040 against
  1.048 — so the harness change between them was not a factor.
- **The parse-rate difference is not claimed.** 17/32 vs 11/32 is p = 0.10. A shorter prompt
  plausibly parses better; this measurement does not show it.
- **Invisible to every test.** Suite and golden run are green in both arms: `MockProvider`'s reply is
  an input, not a response to the prompt's wording — ADR-049's blind spot, hit a third time.
- **1004 tests and the golden run green.** Zero USD_REAL in either arm.
- Next: the prompt change above, under §14.2 counterfactual twins. The other two candidate causes
  (genome pinning, identical wake reason) can only account for the residue — anchoring does not
  explain why the suppressed arm scores 1.96 rather than 3 on three proposals.

## 2026-08-26 — The Cell proposes one idea per run at any temperature

A measurement, and two refusals (ADR-050). **No code changed, no migration, no test added.**

ADR-049 left one item: at ~36% compliance the remaining gap was "a **model** decision, not a prompt
edit," and PRIORITIES carried it as *pull a bigger local model and re-measure*. Pulled `qwen2.5` (7B)
and measured three arms, n=16 each, fresh colony per run.

Final figures, **n=32 per arm** (4 runs × 8):

| arm | parsed | per-run parsed | distinct **/wake** | distinct **/parsed** | median latency |
|---|---|---|---|---|---|
| `llama3.2` t=0.8 | 11/32 | [3, 3, 4, 1] | 0.156 | **0.455** | 9.0 s |
| `llama3.2` t=0.0 | **32/32** | [8, 8, 8, 8] | 0.125 | **0.125** | 10.8 s |
| `qwen2.5` t=0.8 | **22/32** | [6, 7, 6, 3] | **0.344** | **0.500** | 37.5 s |
| `qwen2.5` t=0.0 | **0/32** | [0, 0, 0, 0] | 0.000 | 0.000 | 15.4 s |

**Two diversity columns, because they disagree.** `distinct/wake` divides by wakes, charging a model
for replies that never parsed — and t=0 parses everything, so the temperature effect nearly vanishes
on it (0.156 vs 0.125). `distinct/parsed` conditions on producing a proposal: **3.6× (0.455 vs
0.125)**. ADR-050 originally published the confounded column alone.

### The hypothesis was refuted, and so was its obvious replacement

- **`qwen2.5` wins on parse rate and it replicates** — **22/32 vs 11/32** at n=32 (p = 0.0059),
  precisely ADR-049's failure class vanishing (flattened 0/16 vs 3/16). **The case against it in the
  first draft of this entry did not survive re-measurement**: "14× slower" was ~3.7× once the box was
  not thrashing, and "fewer distinct proposals" reversed outright — at n=32 `qwen2.5` is *more*
  diverse on both columns. It is now the better model on every axis measured except latency; a live
  option deferred behind the temperature question, not a rejected one.
- **Nobody had ever set the sampling temperature.** `providers.py` sends `num_predict` and nothing
  else, and neither model pins one, so every deliberation in this project's history — ADR-049's
  measurements included — ran at Ollama's default 0.8. At `temperature: 0` **both** models collapse to
  **one distinct proposal per run of 8** (`[1,1,1,1]` across four runs, both models). **Which proposal
  they collapse onto is arbitrary and decides the whole score:** `llama3.2` lands on a valid
  experiment (**32/32**), `qwen2.5` on an `abstain` the schema rejects (**0/32**).
- **The two t=0 failures are mechanically different, and only one is repetition.** `llama3.2` emits
  **4 distinct replies per run** — its prompt grows as proposals accrete (1522 → 1628, identically in
  all four runs) and greedy decoding on a changed prompt changes the text, yet the proposal never
  moves. **The context moved four times and the Cell did not.** `qwen2.5` emits **1 byte-identical
  reply per run**, and that is *caused by* its 0% parse rate: nothing parses → no proposal recorded →
  §15.1's recent-proposals section stays empty → prompt frozen at 1537 tokens → same reply forever.
  **A deterministic dead loop**, which the colony cannot think its way out of.
- **So the finding is the metric, not the model — and the metric was wrong three times before it was
  right.** A semantic measure (Vendi score over embedded summaries: the *effective number of distinct
  ideas*, 1.0 when everything paraphrases one idea) removes this entry's original headline rather than
  refining it. **The diversity temperature was supposedly destroying was never there:** `llama3.2`
  scores **1.048 ideas per run at t=0.8 against 1.000 at t=0.0** — a 5% difference where distinct
  strings claimed 3.6×, and the t=0 arm had *8 proposals per run against 2.75*, three times the
  chances to differ. What the string measure counted was trailing clauses.
- **The real problem is bigger than sampling.** §15.1 shows a Cell its own recent proposals; across
  **128 wakes, two models, two temperatures, it proposed the same thing anyway** (~1 idea per run of
  8). Temperature changes surface wording, not the idea. **Self-repetition is a §14/§15 design
  problem**, and it was hidden the whole time behind a metric that scored rewordings as novelty.
- **§14.1 forbids the one-line fix.** "temperature/sampling mutation" is listed as a prompt-mutation
  operator — sampling sits in the *mutable Cell* column, so pinning it in the kernel would delete a
  mutation dimension the spec enumerates. The socket is already reserved and already empty:
  `model_policy` is a §16.2 genome field, hashed to `cells.model_policy_hash`, **written at birth and
  read by nothing** — the fourteenth such socket.

### Verification

- **The control validates the scenario:** re-measured at 7/16 against ADR-049's recorded 20/56,
  Fisher one-sided p = 0.38 — not significantly different, so the arms read against that baseline.
- **The temperature override was teeth-checked** rather than trusted: asserted `temperature: 0.0`
  reaching the request payload, not just inferred from the changed result.
- **Sampling defaults ruled out as a confound** — `ollama show --parameters` sets no temperature on
  either model, so both t=0.8 arms sampled identically and the qwen2.5 gap is the model.
- **`qwen2.5`'s only two failures are a known schema objection**, reached independently by a stronger
  model: both `abstain` replies carrying `kind` + `rationale` alone. FUTURE_BUILD_HOOKS already logs
  `risk_tier`-on-abstain from `llama3.2` doing the same. Two models now decline to state a risk tier
  for declining to act — evidence the schema is wrong, not the models.
- **Zero USD_REAL moved in any arm.** `qwen2.5` was newly exercised through the priced path and its
  bare tag settled at zero; conservation OK per book, hash chains valid, breaker 0/100, A6 linkage
  complete. **1004 tests and the golden run still green** — nothing changed to break them.
- **Four published claims withdrawn across three corrections, and sample size caught none of them.**
  "14× slower" was a thrashing box; "fewer distinct proposals" was a metric charging a model for
  replies that never parsed; "byte-identical on all four t=0 runs" was a check that had only ever run
  against one of the two models, the other's data having been wiped; and the **headline itself** was a
  metric counting paraphrases as ideas. Re-running at n=32 confirmed the headline and changed nothing
  about it — **every real error was an instrument error, and none needed more samples.** The
  measurement that finally moved the conclusion made no new model calls at all.
- **The decision survives all four**, because it never rested on any of them: t=0 does not reliably buy
  compliance (32/32 vs 0/32), §14.1 makes sampling a mutation operator, and a t=0 Cell whose replies
  fail to parse enters a dead loop it cannot think its way out of.
- Next: **why a Cell proposes one idea per run** — now the largest open question, and ahead of the
  sampling work that prompted it. `temperature` as a genome field (§14.1, with §14.2's
  counterfactual-twin obligation) is still worth doing but is no longer the diversity lever it looked
  like. The `risk_tier`-on-abstain question is well-evidenced and cheap — it is what `qwen2.5`
  deterministically converges to, **32/32** of its greedy output.

## 2026-08-25 — The reply format a model can actually follow

`proposal.KIND_PAYLOADS` + a rewritten `_prompt_schema` / `_payload_rule` + one guidance line
(ADR-049). No migration, and **no change to the parser** — `proposal.parse` stays strict.

ADR-048's live run found parse compliance had fallen from **7/8 (2026-08-06) to 1/8**; a controlled
re-measurement put it at **0/12**, every failure the same shape. Three conditional payloads have been
added to the schema since that 7/8, and **none of them had ever been shown to a model.** The suite
and the golden run stayed green the whole time, because `MockProvider`'s reply is an input rather
than a response to the prompt's wording — the same blind spot the 2026-08-06 enum bug was recorded
under, hit again somewhere new.

### Four renderings, each measured

1. **A payload is an object, not a sentence describing one.** `"experiment"` used to render as a
   long English string containing braces, so the model hoisted `hypothesis` to the top level.
2. **The skeleton is ordered, not sorted.** `sort_keys=True` put `experiment` and `external_action`
   *above* `kind` and `summary` — the model met two conditional payloads before the field that
   decides whether they apply. **This was the largest lever, worth more than the other three
   together.**
3. **Optional keys left the skeleton for the prose.** Shown as populated examples, `artifact` and
   `predictions` came back filled with empty strings. Hiding *everything* conditional was worse
   (0/12 — the model stopped emitting the payload its own kind required), so the split is
   sometimes-mandatory in the skeleton, almost-always-absent in prose.
4. **The prompt names no field the parser rejects.** A draft that said "you do not choose what stage
   it runs at" got back `"experiment": {"stage": "§25.1", "rung": "1"}`. **Naming a field is an
   invitation to emit it**, even while denying the Cell controls it.

### Verification

- **Measured 0/44 → 20/56 parseable** on `llama3.2`, same scenario, three runs per arm. Decomposed
  at n=16: all five required fields present **1 → 11**, payload correctly nested **0 → 10**,
  flattened **13 → 4**.
- **1004 tests passing** (16 new, 0 removed; up from 988). **Golden expectation 24 → 25**, two
  sections, **token counts only** — `proposals` and `deliberations` byte-identical, `balances`
  identical in every account in every book.
- **Teeth-checked nine ways.** Two of my own tests were weak and the teeth-check found both: one
  asserted a bare substring (`"artifact" in rule`) that the key's own description text satisfied,
  and one was parametrised over `KIND_PAYLOADS`, so deleting an entry deleted a case instead of
  failing one — **the suite went quieter rather than redder**. Replaced with a test that derives the
  pairing from the parser.
- **One plausible hypothesis measured and refuted.** `risk_tier` and `estimated_cost_minor_units`
  were the most-omitted fields, so moving them ahead of `summary`/`rationale` looked obviously right
  — a model that runs out of steam drops its tail. It took the rate from **7/20 to 0/20**. Reverted,
  and the order now carries a comment saying not to touch it without re-measuring.
- **This is a repair, not a restoration, and the honest reason matters.** ~36% is far below 7/8, and
  that baseline predates three conditional payloads. Replies now stop cleanly (`stop_reason: stop`,
  26–87 output tokens) and are simply incomplete — a 3B capability ceiling, not an ambiguity. Not
  truncation: checked.
- Next: the remaining gap is a **model** decision, not a prompt edit — a larger local model, or a
  paid one where compliance matters. A parse-repair retry is the standard third option and is
  deliberately unbuilt (§24.3, and it pays twice for a prompt bug). All three are in PRIORITIES.

## 2026-08-25 — The denominator that had been sitting in `promotions` since ADR-029

`experiments.stage_tranche` + three fields on §2.6's report + one CLI line (ADR-048).
**No migration.** `normalised_cost = expected experiment cost / current stage tranche` is one line of
SPEC.md, and **"tranche" appears exactly once in the whole document** — named, never defined, the
same shape the experiment itself was in before ADR-043. §10.5 names the object from the other side:
"stage budget exhausted" is a death criterion.

### The measurement came first, and it cleared the gate

FUTURE_BUILD_HOOKS had set a precondition: the numerator was `0` on every proposal from both models
on 2026-08-06, so nothing should be built on the ratio until it was re-measured. Eight live
`llama3.2` wakes against a colony with a running experiment returned **10000, 1000 and 0** — no
longer identically zero. The likely cause is ADR-044's own consequence: §15.1 now shows a Cell the
*derived* cost of its current experiment, which is the reference ADR-043 said models were missing.

### The denominator needed no building

`promotions.allocated_minor_units` has been, since ADR-029 and in its own column comment, "the amount
the operator approved and **not** a figure re-read from the Cell at allocation time" — per Cell, per
rung, human-ratified. That is a stage tranche in every respect §13.1 needs. **Thirteenth socket that
turned out to already exist.**

### The golden run caught the design error, and ADR-043 had predicted it

The first draft keyed the tranche on `experiments.ladder_rung`. ADR-043 had argued against exactly
that a slice earlier, citing §13.1 itself — the formula "would be circular if the stage belonged to
the experiment". The scenario is unusually good at exposing it: its rung-7 promotion and its rung-7
experiment belong to **different Cells**, so the circular reading returns `None` for all three rows
and looks merely conservative. The correct Cell-keyed reading reports a rung-7 tranche against a
rung-1 experiment, so `stage_tranche_rung` is pinned beside the ratio — from the ratio alone the two
readings are indistinguishable.

### Reported, never gated

§13.2 puts experiment cost on a Pareto frontier and says "Do not rely on a single weighted scalar";
§10.2 forbids the same collapse for fitness. A ratio above 1 prints "a claim to weigh, not a rule
that was broken". §10.5's "stage budget exhausted" *could* now consume this and deliberately does
not — that would make the ratio lethal, and it needs its own argument with an Auditor in it.
`death.py`'s docstring claimed stages "do not exist"; it has been corrected.

**One claim stated carefully because the stronger version is false:** `promotion.allocate` reads
`amount = proposal["estimated_cost_minor_units"]`, so the tranche starts as a number the *Cell* wrote.
A Cell can raise its own denominator — by asking for more and being given it, which is §23's gate
working. The asymmetry worth reading is **unreviewed versus ratified**, not Cell versus colony.

### Verification

- **988 tests passing** (8 new, 0 removed; up from 980). **Golden expectation 23 → 24**, one section
  (`experiments`, three keys per row), **`balances` identical in every account in every book** — this
  slice reads existing rows and writes none.
- **Teeth-checked seven ways, no misses**: the tranche keyed on the experiment's rung (the real bug —
  and it fails the golden run too, which is what the migration note claims), `0.0` instead of `None`,
  summing every promotion, the earliest instead of the latest, the ratio inverted, the abstention
  losing its stated reason, and `stage_tranche` regrowing a rung parameter.
- **One existing test was quietly brittle and is fixed**: `test_an_unmeasurable_dimension_...`
  asserted `len(report.unmeasured) == 1`, which made "a second dimension honestly abstained"
  indistinguishable from "the sandbox note was lost". It now asserts the sandbox note.
- **Hand-verified live** on both branches: an unpromoted Cell prints the abstention in words, and a
  promoted one prints `0.00x (0 estimated / 30 allotted at the Cell's current stage, rung 7)` and
  `8.33x` with the over-tranche line.
- **Found and NOT fixed — logged as the new top `Next` item.** Live proposal parse compliance has
  **collapsed from 7/8 (2026-08-06) to 1/8**. Five of seven failures are the model *flattening a
  nested payload* — `hypothesis` at the top level instead of inside `experiment`. Same class as the
  enum bug fixed on 2026-08-06: a value rendered in a shape that reads as a different type, since
  `_prompt_schema` renders each payload as a long English string. The mock provider structurally
  cannot catch it, so the suite and the golden run stay green while a live Cell's proposals are
  discarded.
- Next: that parse regression. It gates every future measurement of anything a Cell proposes,
  including the numerator this slice just measured.

## 2026-08-25 — The seam four files scheduled, and the constraint that made it unnecessary

Migration 0027 + `db.raise_for_unknown_experiment` + two `except` clauses (ADR-047).
`PRIORITIES.md`, `FUTURE_BUILD_HOOKS.md` and ADR-044 all scheduled the same next slice — an
injected `ExperimentChecker` seam, `sweeper.ExternalOperationChecker`-shaped, because
`reservations`, `prediction`, `ledger` and `gateway` sit *below* `experiments` in the layering.
**The premise is true and the conclusion was wrong: the layering objection is an objection to a
*Python* check, and a foreign key has no layer.**

### What was actually missing was a declaration, not a mechanism

All four `experiment_id` columns are bare `TEXT` for one reason each — every one predates the table
it names (`ledger_entries`/`reservations` 0001, `model_calls` 0010, `prediction_register` 0012;
`experiments` 0026). Migration 0026's own header had already said it: "**the foreign key was exposed
to the operator before the table existed**." Meanwhile `db.connect` has set
`PRAGMA foreign_keys = ON` since the beginning, so enforcement was switched on and waiting. SQLite
cannot `ALTER TABLE ADD CONSTRAINT`, so 0027 rebuilds the four tables; every copy is `ORDER BY
rowid`, because both hash chains read their rows in rowid order and the ledger folds each
transaction's entries into that transaction's hash — a reordered copy would read exactly like
tamper-evidence firing.

### The bug the design nearly shipped, found by a test that did the real thing

An **open** reservation carrying a dangling id would have had its funds committed *forever*.
`settle` and `release` write **new** ledger entries carrying the reservation's `experiment_id`, so
once the entry constraint existed every exit from that reservation wrote a row the key must refuse.
**A `PRAGMA`-level probe said the row was healthy** — a bare `UPDATE` of a non-key column on a
violating row is allowed, and that is what I checked first. Only a test that actually *released* one
found the hole. The migration now repairs that single case to NULL — the true value, since ADR-044
settled that unattributed is a result — and writes an `audit_events` row naming the id it cleared.
Terminal reservations and every ledger entry keep their dangling ids untouched: nothing will write
another entry for them, so the id is harmless evidence that a report had been undercounting, and
§3.6 keeps it. **Repair what is still live; preserve what is already history.**

### Verification

- **980 tests passing** (18 new, 0 removed; up from 962). **Golden expectation unchanged at 23** —
  hash byte-identical. A rebuild that preserves order changes no data, and the repair matches zero
  rows on a colony whose only internal source for the value is `experiments.attribution_for`.
- **The blast radius was zero, and that is the finding.** All 962 pre-existing tests passed against
  the new constraint without a single edit, because every internal caller already derives the id
  from `attribution_for`. The hole was never in what the kernel does today — it was in what the next
  programmatic caller would have been free to do, which is exactly what ADR-044 meant by "worth doing
  before anything else starts passing the id programmatically".
- **Teeth-checked twelve ways**, each failing its named test: the foreign key dropped from each of
  the four tables separately, the repair removed (the stranded-funds bug), the repair left
  unrecorded, the repair over-reaching to terminal rows, the rebuild copy losing rowid order (both
  chains break), the translator swallowing non-experiment `IntegrityError`s, and three more.
  **Two mutations initially MISSED and exposed a real gap**: the translator was never tested against
  a *different* foreign key failing on the same row — `prediction_register` and `model_calls` both
  reference `cells` too, and all of them fail with the identical eight words. Two tests added; both
  mutations then caught.
- **Hand-verified end to end on a live on-disk colony** (every test until then used `:memory:`):
  0027 applies under WAL, all four keys land, `foreign_key_check` is clean, an experiment starts, and
  revenue and a prediction attach to it while a ghost id is refused.
- Next: unchanged from the last entry — §13.1's `normalised_cost` still has no stage tranche to
  divide by. Note its numerator was measured at 0 on every proposal from both models on 2026-08-06,
  so the first step there is a re-measurement, not a migration.

## 2026-08-25 — The kind that needed no consumer, and the wake that told a Cell to redo what worked

`proposal.STATEMENT_KINDS` + two context sections + one refusal in `expire_grants_due` (ADR-046).
No migration. `ProposalKind.STRATEGY` was the last kind whose approval led nowhere, and the obvious
reading — that it needed a consumer like the other four — is wrong. **A strategy names nothing to
do, so approving one *is* the act.** What it lacked was a consequence, and the absence had produced
a live bug.

### Two failures, both reproduced on a live colony before the fix

1. **An approved strategy reached the Cell nowhere.** `_recent_proposals_section` showed `kind` and
   `summary` and nothing about what any person decided, so approved, rejected, expired and
   never-reviewed all rendered identically. For every other kind the *effect* was feedback enough —
   a tool result appears, a balance moves, an experiment starts — which is exactly why the gap only
   became visible on the one kind that has no effect.
2. **Its inert grant lapsed and woke the Cell to re-propose it.** `expire_grants_due` regenerates
   every unconsumed grant, and nothing can ever consume a strategy's. So the colony's response to
   "a person agreed with you" was, eventually, "redo that" — the exact opposite of the feedback the
   Cell needed, and the loudest evidence the kind was never finished.

### §23.3 says *actions*

"Expired actions are regenerated and re-evaluated." A strategy names no action, so
`proposal.STATEMENT_KINDS` is where "this kind has no consumer" is now written down rather than
left as the absence that made it look unfinished for four months. The grant still expires — it
lapsed, and §3.6's habit is that history is not rewritten — but nothing is woken.

### §15.1's last unimplemented source

The standing strategy is the Cell's most recently **approved** strategy proposal, derived from the
queue and stored nowhere (§2.5's habit outside the ledger). That fills "relevant epigenetic state",
the one context source §15.1 names which nothing implemented. §0.3 still holds — it is the Cell's
own words, labelled as such — and what distinguishes it from the untrusted proposal log is not that
the colony believes it but that **a person read that exact text and agreed to it**. The operator's
`decision_reason` rides along: the only human-authored text a Cell ever receives, and the most
direct steering the design offers.

**Telling a Cell it was rejected is safe only because §23.4's detector already exists.** §23.5 says
the queue "will be optimised against", and re-asking for a rejected thing is the specific
optimisation this feedback invites — `SIGNAL_REPEAT_AFTER_REJECTION` has been watching for it since
ADR-027, normalised so re-punctuating a rejected ask does not launder it. Had it not existed, this
half would have had to wait.

### Verification

- **962 tests passing** (13 new, 0 removed; up from 949). **Golden expectation 22 → 23** with
  **`balances` identical in every account in every book** — approving a statement moves nothing.
  The scenario's only `strategy` proposal had **no approval request at all** (step 17 deliberated
  without a queue sink), so the one kind whose entire meaning is the decision was the one kind no
  replay ever had a decision for. `approval_grants.expired` moves 4 → 5 **while `regenerated` stays
  4** — the whole §23.3 change in two integers.
- **Teeth-checked ten ways**, each failing its named test: the statement's grant regenerating again
  (the original bug), *no* grant regenerating (the over-fix, which the first test alone would have
  passed against), the standing strategy keyed on the grant so a lapse revokes it, a pending
  strategy standing, the earliest standing instead of the latest, any approved kind becoming the
  standing strategy, the operator's reason dropped, `expired` collapsed into "not reviewed", the
  verdict shown without its reason, and a kind with a consumer called a statement.
- **Hand-verified end to end on a live colony**: a Cell proposed a strategy and it was approved with
  "stay off paid advertising"; a spend request was rejected with a reason; a third sat pending. All
  three render distinctly in the Cell's next context, the standing strategy carries the operator's
  words, and the lapsing grant enqueued **zero** wakes while leaving the strategy standing.
- **One near-miss worth recording**: the golden run showed a strategy request assessed HIGH against
  a claimed LOW with *no* `understated_risk` signal, which looked like a broken detector. It is
  correct — `_assessed_tier` folds §16.2's genome `risk_class`, and that Cell's genome declares
  HIGH. The Cell understated nothing relative to the kernel's tier; its inheritance raised it.
- Next: `ProposalKind` is now fully decided — four consumers, one statement, one never queued. The
  open ground is §13.1's `normalised_cost`, which still has no stage tranche to divide by.

## 2026-08-25 — The proposal kind that led nowhere, and the rung a Cell may not name

`experiment_grants.py` + an `ExperimentSpec` payload (ADR-045). No migration.
`ProposalKind.EXPERIMENT` has existed since migration 0013 and appeared **nowhere else in `src/`**.
A Cell could propose an experiment, it reached §23's queue, an operator could approve it — and the
grant sat inert, because `experiments.start` was reachable only from the operator's own CLI verb.
Every experiment in the colony was one a person typed by hand, and `experiments.proposal_id`, the
foreign key ADR-043 added for exactly this, could never be filled.

**The golden run had been carrying the evidence since expectation version 5**: one `experiment`
approval request, permanently `pending`, in every replay for four months.

### §0.2's table decides what the kernel may judge

Its two columns put **"experiments" in the mutable Cell side**, beside prompts, strategy and market
hypothesis — and "capital + population allocator" and "permissions + approvals" on the immutable
kernel side. So nothing in the new module reads, validates or rewrites a hypothesis: what is tested
is the Cell's business. What the kernel gates is the **§9.2 slot** (a colony-wide scarce resource)
and the **§25.1 rung**. An operator approving one of these approves a cost and a stage, never a
scientific opinion.

### The rung has nowhere to be named

§25.1 opens with "no strategy moves directly from synthetic success to autonomous commerce", and a
Cell that could name its own rung could ask for rung 7 on its first wake and need one distracted
operator to get it. §23.5 already generalised the problem — the queue "will be optimised against by
Cells" — so `ExperimentSpec` has **no rung field at all** (`FORBIDDEN_RUNG_FIELDS` is the third
tripwire in `proposal.py`, after §0.3's and §16.3's) and `entitled_rung` reads the answer out of
`promotions`. §25.1 becomes a property of the schema rather than a rule someone remembered to check.

**"Reached" and "entitled to" turn out to be different questions over the same two tables.**
`experiments.stage_reached` maxes over `promotions.rung` *and* `experiments.ladder_rung`, because a
Cell that ran rung-1 work has genuinely reached rung 1. `entitled_rung` deliberately does not:
unioning them would turn ADR-043's recorded-but-unenforced `start-experiment --rung 7` into a
permanent ratchet on what the Cell may then ask for by itself.

### Where it had to live

`approval` imports `deliberation`, which imports `experiments` — so `experiments` **cannot** import
`approval`, and the consumer cannot live there. That is the registry/executor split this kernel
already makes twice: everything that reads or refuses stays low enough for `context`, and the part
that spends a grant sits above `approval`.

### Verification

- **949 tests passing** (18 new, 0 removed; up from 931). **Golden expectation 21 → 22**, with
  **`balances` identical in every account in every book** — starting an experiment opens no
  reservation and posts no entry. Every deliberation gains ~160 input tokens, one cause: the
  prompt's schema hint now describes the `experiment` block and it is in every system prompt. The
  snapshot pins a **`running`** experiment for the first time — the state §9.2's cap actually
  counts, and the one every prior version missed because all its experiments ended terminal.
- **`test_only_the_promotion_module_consumes_a_grant` loosened a third time**, which is the friction
  it exists to create. The argument: this is the only one of the four consumers that *provably
  cannot climb the ladder* — `promotion` hands over capital, `tools` runs a fetch,
  `external_actions` spends a person's attention; this one writes a row and stamps a rung it read
  from `promotions`. The scheduler is barred for a different reason than the other three: an
  experiment on a timer spends nothing but consumes a §9.2 slot, and a colony that ratcheted itself
  to its own cap unattended would refuse every experiment a person then wanted to run.
- **Teeth-checked twelve ways**, each failing its named test: `entitled_rung` returning a constant,
  `entitled_rung` unioning experiments the way `stage_reached` does, the grant consumed outside the
  rollback, no kind check, a consumed grant reusable, an expired grant still acting,
  `startable_grants` listing what would refuse, `ExperimentSpec` growing a `ladder_rung`, both
  directions of the payload/kind rule, the hypothesis taken from `summary` instead of the frozen
  payload, and `proposal_id` left null.
- **Requiring the payload broke 71 tests**, all fixtures using `experiment` as the neutral kind. A
  real signal and the wrong one to obey: an experiment that cannot state what it is testing is a
  summary, and §10.5's coroner asks for "final hypotheses" by name. The fixtures now pair each kind
  with its own payload.
- **Hand-verified end to end on a live colony**: a Cell proposed an experiment, the kernel assessed
  MEDIUM against its claimed LOW (§23.5), an operator approved it, `startable-experiments` showed
  the rung *before* anything started, and the grant started it at rung 1. A second start on the same
  grant is refused; `--rung` with `--grant` is refused outright rather than ignored.
- **A guard was removed, not added**: the new module's dead-Cell check shadowed a better message from
  `experiments._start_locked` inside the same transaction. ADR-039's "second, weaker copy" applies to
  guards as much as to gates.
- Next: `ProposalKind.STRATEGY` and `SPEND_REQUEST`-adjacent kinds are now the only ones whose
  approval leads nowhere in particular; and §13.1's `normalised_cost` still has no stage tranche to
  divide by, which is the next thing an experiment's rung could be made to mean.

## 2026-08-25 — Attribution: the column everything asked for, and never needed

No migration. `experiments.attribution_for` + threading through `tools`, `external_actions` and
`deliberation` (ADR-044). The slice was scheduled as "add `resource_usage.experiment_id`" —
BUILD_RECORD said it, PRIORITIES said it, `golden.py`'s version-20 note said it, and
`experiments.py`'s own docstring said it. All four were wrong about the mechanism.

### The join was always there; the stamp was not

`resource_usage.reservation_id` is `NOT NULL REFERENCES reservations(reservation_id)` — Amendment
A6 requires precisely that — and `reservations.experiment_id` has existed since **migration 0001**.
Every metered row was one join from its experiment the whole time. What was missing was the stamp:
`gateway` threaded `experiment_id` into its reservations and `tools`, `external_actions` and
`deliberation` did not. Adding the column would have worked, and would have created a second answer
to a question the reservation already owns — a usage row stamped with one experiment hanging off a
reservation stamped with another, with nothing in the schema preferring either. That is §2.5's
cached-derivation trap reached from the metering side, so
`test_resource_usage_has_no_experiment_id_column` now refuses it the way
`test_there_is_no_experiment_results_table` refuses the other one.

### The visible bug was the abstention; the real one was the undercount

`human_minutes` reported `None` with a stated reason, which announces itself. **`resource_spend_
minor_units` — §2.6's shadow-cost line — reads the same reservations through the ledger and was
reporting a definite figure with every tool call and every human minute missing from it.** And
`deliberation` never named its experiment to the gateway at all, so §2.6's *real cash consumed* was
0 for any experiment whose Cell simply ran — the headline number on a paid provider, and the least
visible failure, because 0 is plausible for work that has not spent yet. An abstaining dimension is
loud. An undercounting one sits next to it looking identical.

### Derived, never supplied

§15.1 gives a Cell one current experiment, so which experiment bears a cost is already determined.
A parameter would be a place to put a *different* one — §0.3 reached from the expense side, since a
Cell that could name the experiment could make its own look cheap by naming another. So
`attribution_for` is the single seam, an `inspect.signature` test asserts no metering entry point
grows the parameter, and `None` stays a result rather than a gap. Two timing rules fell out:
external-action labour is stamped **at claim, not at completion** (a person may answer days later,
by which time the Cell may be on another experiment or dead), and a deliberation **resolves it once
and carries it** to both the gateway call and the predictions it registers, because ADR-022 puts
those on opposite sides of a transaction boundary.

### §1.1 wanted the number the obvious sum would have hidden

`external_actions` bills a Cell up to its channel ceiling and records the overflow as subsidy, so
`resource_usage.quantity` is the *billed* minutes. Summing it alone would report the colony's human
cost as **smaller the more of it a person absorbed unpaid** — the exact quantity §1.1 subtracts to
"expose hidden founder labour", hidden by the report built to expose it. The report carries
billed + subsidised, with the subsidy printed beside it.

### Verification

- **931 tests passing** (15 new, 0 removed; up from 916). **Golden expectation 20 → 21**, with
  **`balances` identical in every account in every book** and USD_REAL untouched — attribution
  decides which experiment a cost is *reported* under; it posts no entry. `human_minutes` moves
  `null → 0` on one experiment and `null → 58` on the other; the `0` is now a *measurement* rather
  than a decline. `resource_spend` `0 → 550`. Four deliberations gain 1–3 input tokens, all from
  one cause: §15's experiment section renders the RESOURCE figure to the Cell, which had always
  read `0`.
- **Teeth-checked twelve ways**, each failing its named test: both metering paths unstamped (the
  state before this slice), the wake unstamped, a Cell's forecasts back to `experiment_id=None`,
  human labour summing only billed minutes, the report abstaining again, attribution ignoring
  whether the experiment still runs, attribution read at completion instead of claim, the CLI
  accepting any string for `--experiment`, a metering entry point growing the parameter, the column
  being added, and the attribution re-derived instead of carried.
- **One test could not have failed and was rewritten.** "The call and its forecasts share one
  experiment" passes trivially on a quiet run — a re-derivation agrees too. It now uses a provider
  that concludes the experiment *while the call is in flight*, the only moment the two designs
  differ, and the mutation is caught.
- **Hand-verified end to end on a live colony**: experiment started, a wake deliberating under it,
  an approved external action claimed and completed at 47 human minutes against email's 30-minute
  ceiling — the report showing 2 model calls, 47 minutes with 17 subsidised, 304 RESOURCE, and the
  Cell's *own* auto-registered forecast in the reality gap. A bogus `--experiment` is refused.
- **The live run is what found the deliberation half.** The first report read "Model calls: 0" for
  a Cell that had just deliberated under the experiment, which no test was asking about.
- Next: `revenue.record_revenue` refuses a re-record that only adds an experiment (correct per
  idempotency), so an operator attributing revenue late needs §3.6's adjustment path — logged, not
  built. Kernel-internal validation of a dangling `experiment_id` needs a seam and is in
  FUTURE_BUILD_HOOKS.

## 2026-08-24 — The experiment: seven sections reference it, none defines it

`experiments.py` + migration 0026 + four CLI verbs (ADR-043). The largest socket cluster in the
repo, and unusually most of it was **live plumbing rather than dead columns**: `experiment_id` has
been threaded through `gateway`, `prediction` and `ledger` for months, `reservations.settle` has
been propagating it onto ledger entries all along, and `mitosis predict --experiment <id>` accepted
any string and validated nothing. The foreign key was exposed to the operator before the table
existed.

### §2.6 defines the report, and the clause above it decides the design

There is no §Experiments. What §2.6 does define is *"synthetic revenue/profit, real cash consumed,
resource consumption, shadow cost, human labour, and a reality-gap estimate"* — six dimensions, so
§10.2 and §13.2's "do not rely on a single weighted scalar" are satisfied by the definition rather
than by a preference.

**§2.5, immediately above it, is "Balances are derived."** Read as neighbours, an experiment report
is a derived view and not a stored row. So there is **no `experiment_results` table**, despite §31
listing one — §31 offers "suggested entities" and does not mark that one Phase 1, and a stored
outcome is exactly where §0.3 leaks back in. The surest way to keep "a Cell may explain a result and
never define one" true is to give it no column to write, which is how `proposal.py` earns its shape.
`test_there_is_no_experiment_results_table` defends the refusal.

### The stage question had three witnesses and they agreed

§10.5's coroner lists `stage_reached` (singular) beside `experiment_ids` (plural); §27.2's dashboard
pairs them as one Cell field, "current experiment/stage"; and §13.1's `normalised_cost = expected
experiment cost / current stage tranche` would be circular if the stage belonged to the experiment.
**So §25.1's nine rungs are the only ladder** and Phase 2's "stage gates" are the gates between
them — no second ladder, no stages table. `stage_reached` derives from the highest rung a Cell was
funded at *or* ran at, because a Cell that did rung-1 simulator work and was never promoted has
still reached rung 1.

### Found while building: a slot that leaks on every death

§9.2 caps *simultaneous* experiments colony-wide, and death is routine. A Cell that died mid-
experiment left it `running` forever, so a colony killing Cells faster than it concludes experiments
would ratchet to its cap and refuse every new one with nothing anywhere explaining the refusals —
the "a claim held before acting is a lock and nothing sweeps it" shape ADR-036 logged for channel
claims. The seam now **settles before it reports**, and the experiment is **abandoned, never
concluded**: it reached no answer, and a coroner report listing a running experiment on a dead Cell
would be a false statement rather than a thin one.

The seam itself is `lifecycle.CoronerEnricher` — `lifecycle` sits below `experiments`, so §10.5's
two fields arrive by injection rather than a back-edge, the shape `population.Displacer` established.

**§9.2's cap is a third refusal shape.** ADR-031 separated durable carrying capacity (which
justifies displacement) from a temporary birth rate (which a clock clears); this slot frees when an
experiment *concludes*. `ExperimentCapacityError` sits deliberately outside `PopulationError` so it
cannot be caught as either, because both would suggest the wrong remedy.

### Verification

- **916 tests passing** (29 new, 0 removed; up from 887). **Golden expectation 19 → 20**, with
  **`balances` identical in every account in every book** — an experiment is a record and a
  derivation, and the revenue it now names was already being posted. The snapshot pins each
  experiment's §2.6 figures *derived on the spot*, so a kernel that started caching an outcome would
  have to keep them identical. `coroner_reports.stage_reached` moves from `null` — which it has been
  since migration 0007 — to `"rung 7: tiny capped live experiment"`.
- **Teeth-checked sixteen ways**, each failing its named test: the report ignoring the ledger,
  revenue read off the cash leg, an unmeasurable dimension reported as 0, the §9.2 cap unchecked
  (the state before this slice), that error folded into the population hierarchy, concluded
  experiments still counting, §15.1's singular ignored, `stage_reached` from promotions alone, the
  coroner seam never consulted, the seam made mandatory, the seam overwriting an explicit stage,
  death not releasing the slot, death concluding rather than abandoning, `death.py` no longer
  enriching, a rung off the ladder accepted, and unresolved forecasts folded into the reality-gap
  mean.
- **Hand-verified end to end on a live colony**: experiment started at rung 1, §15.1's one-at-a-time
  refused, rung 12 refused, 12.50 USD_SIM of revenue derived into the report, concluded and the slot
  freed, then a second experiment at rung 7 abandoned by its Cell's death with the coroner carrying
  `rung 7: tiny capped live experiment` and both experiment ids.
- Two gaps the live run surfaced: `record-revenue` had no `--experiment` flag despite the function
  taking one (fixed), and re-recording revenue to attach an experiment is **correctly refused by
  idempotency** — which means an operator who attributes revenue late cannot fix it, and §3.6 says
  the remedy is an adjustment rather than an edit. Logged, not built.
- **A snapshot-hygiene fix rode along**: a prediction's free-text claim embeds its approval request
  id, so a section about *calibration* was pinning an identifier into the hash. Seeded ids are
  reproducible only for a fixed sequence of allocations, so this slice minting one id earlier
  produced a spurious diff. ADR-017 excludes volatile ids; this was one wearing a sentence as a
  disguise, and it is now scrubbed.
- Next: `resource_usage.experiment_id` is the obvious next socket — it is the one column standing
  between §2.6's report and its last two dimensions.

## 2026-08-22 — The estate: a dead Cell stops taking the colony's money with it

`kill()` marked a Cell dead, filed its coroner report, and left its money where it was. Open
reservations stayed open; residual cash sat on an account nothing could ever spend from again.
ADR-028, in `lifecycle.py`.

**The golden run had been losing 3450 USD_SIM per replay since expectation version 1**, and the
expectation diff is the whole bug report: `cell:cell#0:cash` 3450 → 0, `colony_treasury` 300 →
3750. Displacement made this worse by design — evicting Cells to reclaim population slots exactly
when the colony is at capacity — and the scheduler made it compound with nobody watching.

### What the spec gave, given it has no "estate" concept

Charter C8 turned out to be the load-bearing clause, and not for the reason it looks like. "Dead
Cells cannot act" reads as being about behaviour, but **an open reservation *is* standing
authorisation to spend**, whatever the status column says — so a dead Cell holding one is the
plainest possible instance of what C8 forbids. That is why the estate runs inside `_kill_locked`
rather than as a follow-up sweep: a crash between the death and the release must not be able to
leave that state. §9.3 displacement inherits it for free.

`accounts.py` had already decided where the money goes, in a comment written two slices earlier:
returning surplus to `colony_treasury` is "capital going back, not cost incurred". So the estate is
capital movement, not spend — and the real-spend registration guard forced that decision explicitly
rather than letting it pass on a reviewer noticing.

### The tension worth recording

ADR-022 says a reservation with an `external_operation_id` is resolved by finding out what the
provider did, never by assuming — so death must not release it. But refusing to *kill* a Cell with
a call in flight would break displacement and, worse, hand every Cell a survival strategy: keep one
call in flight and never die. So an in-flight operation makes the estate **incomplete, not the
death impossible**, and `mitosis sweep` finishes it once the sweeper has resolved the reservation.

### Verification

- **621 tests passing** (13 new, 0 removed; up from 608).
- **Golden expectation 7 → 8** via a reviewed migration. Exactly four values move, all a single
  transfer: `cell:cell#0:cash` 3450 → 0, `colony_treasury` 300 → 3750, plus one new transaction
  type and one new audit type. USD_SIM conservation unchanged; **no USD_REAL movement**.
- **Teeth-checked eight ways**, each failing its named test: not reclaiming cash at all, leaving
  reservations open, releasing an in-flight external operation, sweeping a negative balance as
  surplus, posting the estate to a spend destination, sweeping living Cells, keying the estate per
  cell+book so a second pass collides, and un-exempting it from spend classification.
- **A test of mine passed for the wrong reason and was rewritten.** `..._predates_the_estate`
  asserted that ordering keeps the estate out of the coroner report — but the *classification*
  does that, so the test passed with the estate deliberately moved before the report. The comment
  in `_kill_locked` claimed the same thing and was corrected: the ordering is defence in depth and
  is currently unobservable.
- **An intermittent Charter-property failure was diagnosed and fixed, and it was not this slice's
  bug.** Two property tests failed once each in full-suite runs, then passed on replay. One of them
  (`charter_conservation_per_book`) touches no cells and no estate at all, which is what identified
  it: every property test that builds a migrated database *inside* each example charges schema
  setup against Hypothesis's 200ms per-example deadline, and at 15 migrations a loaded machine
  trips it. `test_charter_carrying_capacity_lineage_share` had already been exempted for this
  reason; that is now generalised, with the reasoning recorded in the file. Reproduced on
  Hypothesis seeds 20 and 23, both green afterwards.
- **Hand-verified on a live colony**: two Cells (1000 and 800, one holding a 300 in-flight external
  reservation) died; the treasury went 0 → 1500 immediately, the in-flight Cell was listed as an
  outstanding estate, and once its operation resolved the treasury reached 1800 with no outstanding
  estates left. Conservation and the hash chain green, and the dead Cell's attributed spend stayed
  empty.
- Next: nothing still runs the scheduler (`tick` needs a crontab, and there is no alert when ticks
  stop); `max_births_per_epoch` is checkable and unchecked; and nothing consumes an approval grant,
  which is §25.1's next rung and its own slice.

---

## 2026-08-22 — The approval queue: a proposal becomes something an operator can act on

The front item, and the thing that turns a colony that thinks into one whose thinking goes
somewhere. New `approval.py` + migration 0015 (ADR-027), plus six CLI verbs.

**Reading §23 first changed the design, and the clause that did it was the last one in the
section.** §23.5 is a single sentence — "the approval queue is itself part of the environment and
will be optimised against by Cells" — and it makes the obvious implementation unusable. The
obvious queue reads `risk_tier` off the proposal and files accordingly. But `risk_tier` is written
by the Cell being reviewed, and proposal.py had already written down what happens next: a Cell
that could set its own tier and be believed "would set it to LOW forever."

### The shape that fell out

`claimed_tier` and `assessed_tier` are separate columns. The kernel derives its own from facts the
Cell does not control — its book, its status, the request kind, and its lineage's cumulative
exposure — and the fold is `max`, so **a Cell may raise its own tier and never lower it.** Claiming
more danger is a Cell flagging itself and is believed; claiming less is recorded as an
`understated_risk` signal, so the attempt stays visible rather than merely being defeated. This is
§0.3 ("a Cell may explain a result; it may never define the canonical result") extended from
outcomes to *requests*.

### The finding worth keeping

**§23.4's aggregation key should be the lineage, not the Cell — and the spec cannot say so.** The
clause asks for cumulative exposure "keyed by counterparty/domain/channel". None of those exist
yet; no Cell can take an external action. But its *target* is action-splitting, and the cheapest
splitting mechanism this colony offers is not one Cell making many requests — it is §9
reproduction. A Cell can birth children and have each ask for a fraction of one risky thing.
Keying on `cell_id` would have missed exactly the split this system makes easiest. Verified live:
a parent and its child now share one exposure total.

### Where the two clocks separate

§23.3 asks for SLAs *and* expiry, and they are not the same mechanism. An SLA breach makes an item
**overdue** — "overdue items surface distinctly" is a reporting requirement, so overdue is derived
at read time and the item stays pending and approvable. Expiry is a lifecycle transition, and the
clause is specific about what follows: "expired actions are **regenerated and re-evaluated** before
execution." So an expiry enqueues a fresh wake and the Cell re-derives the action, while an expired
request can no longer be decided. Both halves matter; the second is the easy one to drop.

Expiry itself is derived as a multiple of the tier SLA rather than a fourth unspecified knob, which
means CRITICAL expires fastest. That reads harsh until you read it as §23.3 does — a critical action
nobody looked at within the hour should be re-derived, not executed on hour-old reasoning.

### What approval does not do

§25.1 puts the loop at rung 5. This moves it to rung 6, "human-reviewed prototype" — **not** rung 9.
`approve` writes a scoped, single-use, expiring **grant**, and nothing consumes one.
`consumed_at_utc` exists and is always NULL, and a structural test forbids any module outside
`approval.py` writing the table or reading that column, so the first executor has to break a named
test and edit a migration comment that states the rule.

### Verification

- **608 tests passing** (37 new, 0 removed; up from 571).
- **Golden run: expectation version 6 → 7**, via a reviewed migration. Exactly three sections
  differ and the note explains each: a new `approval_requests` row (claimed LOW, **assessed
  MEDIUM**, one `understated_risk` signal — §23.5's guarantee now pinned in the replay), a new
  `approval_grants` count pinned at **0**, and `audit_event_types` gaining `approval_requested`.
  **No balance, reservation, transaction-type or conservation change** — the balances section is
  byte-identical to version 6.
- **Teeth-checked thirteen ways**, one per guarantee, each failing its named test: letting the
  Cell's claimed tier win, keying aggregation on the Cell instead of the lineage, dropping the
  signal clause from batching, removing signal escalation, treating real-money spends as
  reversible, dropping the action instead of regenerating it, approving an expired request,
  counting rejected asks toward exposure, allowing a blank reason, backfilling the Auditor summary
  from the Cell, queueing abstentions, widening the seam signature, and deciding one request twice.
- **Two tests initially passed for the wrong reason** and were rewritten. The batching test is the
  interesting one: four of the five signals escalate the tier, so a signalled item never reaches
  `batchable` still LOW — meaning the explicit `not self.signals` clause is currently unreachable
  through the real path. It is kept as the lock that becomes load-bearing if the escalation rules
  are ever loosened, and the test now asserts both mechanisms *separately* rather than letting
  escalation quietly answer for the clause.
- **Hand-verified end to end on a live colony**: six proposals, five queued (the abstention
  correctly skipped); four 12-unit spend requests all claimed LOW escalated LOW → MEDIUM → HIGH as
  the aggregate crossed thresholds, with `action_splitting` firing on the third; batch approval
  took only the one trivial reversible item and left the rest for individual review; a blank reason
  was refused; a rephrased repeat of a rejected ask ("Buy sample D!!" against "buy sample D") was
  caught by `repeat_after_rejection`; and five days on, four requests expired, regenerated four
  wakes, and refused a late approval. All three conservation checks, both hash chains and resource
  linkage green afterwards, **USD_REAL untouched**.
- Next: nothing still runs the scheduler (`tick` needs a crontab); `max_births_per_epoch` remains
  checkable and unchecked; and the queue's two honest gaps — no Auditor Cell to write §23.2's
  independent summary, and no liability reserve to populate its liability line.

---

## 2026-08-06 — The scheduler: the colony runs unattended, and refuses to run away

The last piece between a colony that must be driven by hand and one that runs from cron. New
`scheduler.py` + migration 0014 (ADR-026).

**Most of this slice is refusals, and that is what the spec spends its words on.** §23.3 exists
because the failure mode of automation is not a bad decision, it is four hundred quiet ones
overnight — the clause names that scenario directly. Reading §23.3 and §27.1 before designing
changed the shape substantially, and §27.1 turned out to specify more than I expected: it ships
the `operator:` block *and* `autonomy.real_spending: false` as defaults.

### The cadence question answered itself

I had flagged cadence as needing a decision from the user. It didn't: **the cadence policy is a
dedupe key.** Each wake is `epoch:{n}:cell:{id}`, and `events.enqueue` is already idempotent on
dedupe keys, so "one wake per Cell per epoch" is structural rather than arithmetic. Re-ticking
inside an epoch enqueues nothing, a crashed tick resumes cleanly, and running from cron every
minute costs nothing until the epoch turns over. No counter, no `last_woken_at` column that could
disagree with the event log.

### The finding worth keeping

**§6.3's "explicit conversion metadata" is load-bearing, not ceremony.** §23.3 wants real cents
per *sim*-epoch; every ledger row is stamped in *wall* time, because the clock still isn't wired
into ledger timestamps. Attributing spend to an epoch is therefore impossible unless the wall
anchor is recorded as each epoch is crossed — which is exactly what `epoch_log` does. The clause
that reads like bookkeeping is the thing that makes the alarm computable at all.

### Three guards, each from a normative clause

- **`autonomy.real_spending` (§27.1), shipping false.** Two independent confirmations are needed
  to spend real money on a schedule: the CLI's `--yes-spend-real-money` ("I meant to type this")
  and the stored autonomy flag ("the colony may do this without me"). An unconfigured operator row
  reads as *never seen*, so a colony with no operator config is in vacation mode with spending off.
- **Vacation mode (§23.3)** maps onto the provider split with no new concept: a paid provider is
  external-facing, mock and Ollama are not. An absent operator stops the colony **spending**, not
  thinking — which is precisely what "external-facing phases auto-pause while sim-only work may
  continue" asks for.
- **The metabolic alarm (§23.3) watches the derivative, not another ceiling.** "An acceleration in
  the burn rate raises an alarm **even if every individual cap is satisfied**" — so a second
  absolute cap would duplicate the breaker and catch nothing new. It compares an epoch's burn
  against a short baseline of recent *spending* epochs; zero-spend epochs are excluded, because a
  colony going from idle to spending is starting rather than accelerating, and a zero baseline
  makes every first spend an infinite acceleration.

A fired alarm **halts the scheduler and persists until acknowledged with a stated reason**. §23.3
says "alarm", not "halt" — but this is the module that runs while nobody watches, and an alarm
nothing acts on is a log line. It halts *scheduling* only: no Cell dies, no reservation moves, the
breaker is untouched, `mitosis wake` still works by hand. A heartbeat deliberately does not clear
it — being back at the keyboard is not the same as having looked at why money was burning.

### Verification

- **571 tests passing** (22 new, 0 removed; up from 549). Golden-run hash **unchanged** — correct,
  since the scenario never ticks; a changed hash would have meant the scheduler firing somewhere
  it shouldn't.
- **Teeth-checked nine ways**, one per guarantee: defaulting `real_spending` on, skipping the
  autonomy check, skipping vacation mode, dropping the acceleration half of the alarm, letting a
  fired alarm not halt, letting a heartbeat clear the alarm, allowing an unexplained
  acknowledgement, breaking the per-epoch dedupe key, and widening eligibility past `alive` — each
  fails its named test.
- **Hand-verified end to end** on a live colony: two ticks in one epoch woke 2 Cells then 0; a
  paid tick was refused first by the CLI flag and then, with the flag passed, by
  `halted_autonomy`; with autonomy enabled and the operator 7 days absent it read
  `halted_vacation` while a free tick still ran. Then the acceleration case — four epochs at 2
  minor units, one at 30, **all under the 50-unit cap** — fired on `15.0x the recent baseline`,
  halted the next tick even on a free provider, survived a heartbeat, refused a blank
  acknowledgement, and resumed after an explained one.
- Not committed — reporting for review first.
- Next: `max_births_per_epoch` is finally checkable (the epoch primitive was its missing
  prerequisite) but belongs with the birth paths; §23's approval queue still does not exist, which
  matters more now that proposals are generated unattended; and **nothing runs the scheduler** —
  `tick` is a command, so a colony still needs someone to install the crontab.

---

## 2026-07-26 — Seeded id generation (second and final Phase 1 gating item closed)

`golden.py`'s docstring named the gap: the kernel had no seeded id generation, so a golden run's
raw uuids differed every time even though its *semantic* snapshot didn't — and Amendment A5's
`(effective_time, priority, event_id)` ordering tie-break fell to a fresh `uuid4` every run,
making it a total order but not a reproducible one. Both are the same underlying fix.

- **New `src/mitosis/ids.py`:** an injectable id generator. `RandomIdGenerator` (the default) is
  byte-for-byte what every call site already did — `str(uuid.uuid4())` — so a real colony run is
  unchanged. `SeededIdGenerator(seed)` uses a `random.Random(seed)` to emit uuid4-*shaped* strings
  deterministically (`uuid.UUID(int=rng.getrandbits(128), version=4)`) — same TEXT-primary-key
  format everywhere, no schema/format migration. `ids.seeded(seed)` is a context manager that
  scopes determinism to a block and restores whatever generator was active before (not always
  `reset()`'s default — nesting stays correct); `seed()`/`reset()` are the lower-level equivalents
  for a caller that wants an open-ended window instead. No thread-safety needed: nothing in this
  kernel runs Python threads (concurrency here is SQLite `BEGIN IMMEDIATE` write-lock contention
  between connections, not in-process threading — see slice 10's concurrency-safety pass).
- **Every `uuid.uuid4()` call site converted to `ids.new_id()`:** `ledger.py` (transaction_id,
  entry_id), `reservations.py` (reservation_id), `lifecycle.py` (genome_id, cell_id, coroner
  report_id), `events.py` (inbox event_id, outbox event_id), `resource_metering.py` (usage_id),
  `audit.py` (audit event_id), and `cli.py`'s idempotency-key default suffix (not a primary key,
  but converted too for one consistent source of id-ish randomness in the kernel).
- **`golden.py` wired to use it:** `run_scenario` now runs its whole body inside
  `ids.seeded(GOLDEN_RUN_ID_SEED)` (renamed the body to `_run_scenario_body` so the public
  function's signature/callers didn't need to change). Updated the module docstring — the "known
  determinism gap" paragraph is now "determinism gap this closes"; ADR-017's semantic-snapshot-plus-
  hash comparison is unchanged and stays the permanent design (its real rationale is schema-
  evolution robustness, not id determinism) but the raw run underneath it is no longer
  non-reproducible.
- Verified by hand before writing tests: ran `golden.run_scenario` against two independent fresh
  in-memory connections and diffed the raw `cell_id`/`transaction_id`/`event_id` lists — identical,
  not just their semantic snapshot. Confirmed default (unseeded) `ids.new_id()` still produces
  distinct random uuids, confirmed a real `mitosis init && create-cell` session end to end still
  produces normal random-looking ids, confirmed `ids.seeded(...)` correctly restores the *previous*
  generator (not unconditionally "random") when nested. Confirmed `mitosis verify-golden-run`'s
  shipped hash is unchanged — expected, since the semantic snapshot already stripped ids before this
  slice, so nothing about what the hash covers changed.
- New tests: `tests/test_ids.py` (7 tests — default randomness/shape, seed determinism, distinct
  seeds diverge, seeded output is still uuid4-shaped, `reset()` behaviour, context-manager scoping
  and restore-to-prior-generator including nesting). `tests/test_golden.py` gained
  `test_raw_ids_are_reproducible_across_runs` (byte-identical raw ids across two runs, the property
  this slice exists to establish) and `test_run_scenario_does_not_leak_seeded_ids_afterward` (calling
  `run_scenario` must not leave the global generator seeded for unrelated code afterward).
- **230 tests passing** (9 new, 0 removed; up from 221).
- Deliberately out of scope for this slice: no CLI `--seed` flag (nothing yet needs an end user to
  run a *real* colony deterministically — the two documented consumers, golden-run replay and
  Amendment A5's tie-break, are both served by `golden.py`'s internal seeding; a public seeding knob
  is Phase 2 flight-simulator territory per SPEC.md §7's "deterministic seeds" requirement, not a
  Phase 1 concern); no change to ADR-017's semantic-snapshot-plus-hash comparison strategy or to
  `golden_expectations.json` (hash unaffected, so no `--update-expectations` migration was needed);
  clock.py's wall-clock timestamps are still not seeded/wired — see PRIORITIES.md — so a *real*
  colony still can't be byte-identically replayed, only a scenario like `golden.py`'s that already
  avoids reading the wall clock.
- Closed the `FUTURE_BUILD_HOOKS.md` entry this slice resolves (2026-07-25, "seeded ids for
  reproducible event ordering").
- Committed and pushed to `main`.
- Next: with both Phase 1 gating items closed, the remaining Phase 1 "Next" list in PRIORITIES.md
  is all additive/Phase-2-adjacent — remaining CLI commands, `kill()` reservation/balance sweep,
  wiring the simulated clock into real producers, reproduction/lineage tracking, experiment
  tracking, model gateway. None has a hard ordering constraint over the others.

## 2026-07-26 — CI workflow wired (first Phase 1 gating item closed)

SPEC.md §0.1 and §26 require Charter property tests and golden-run replay to run in CI, so a broken
Charter clause or a kernel-behaviour drift can't merge silently. Neither ran anywhere but locally
until now — no `.github/` directory existed in the repo.

- **`.github/workflows/ci.yml`:** new GitHub Actions workflow, triggers on push/PR to `main`.
  `actions/checkout` + `actions/setup-python@v5` (Python 3.11, matching `pyproject.toml`'s
  `requires-python = ">=3.11"`), `pip install -e ".[dev]"`, then `pytest` (full suite, which
  includes `tests/test_charter_properties.py` — no separate charter-only step needed) and
  `mitosis verify-golden-run` (uses its own fresh in-memory colony per its docstring, so it needs
  no `mitosis init` step first and never touches a `--db` path).
- Verified by hand before committing to the workflow file: built a scratch venv from
  `/opt/homebrew/bin/python3.11` (the same minor version `setup-python` will provision — the
  default macOS `python3` here is 3.9 and its bundled pip is too old for PEP 660 editable installs,
  which would have been a false negative if used to "test" this), ran `pip install -e ".[dev]"`,
  `pytest`, and `mitosis verify-golden-run` end to end: 221 passed, golden hash matched exactly.
  Scratch venv discarded after.
- Deliberately out of scope for this slice: no matrix (single Python version — nothing in the
  spec or codebase needs multi-version support yet), no coverage reporting, no lint/type-check step
  (none configured anywhere in the repo yet, so adding one here would be inventing new scope rather
  than wiring up an existing local check), no caching of the pip install (the install is a few
  seconds; not worth the added workflow complexity yet).
- Committed `2ba65e2`, pushed.
- Next: seeded ID generation (the remaining Phase 1 gating item — `uuid4` primary keys/timestamps
  block byte-level golden replay and Amendment A5's deterministic tie-break for same-instant
  same-priority events); otherwise the Phase 1 "Next" list in PRIORITIES.md is unchanged.

## 2026-07-25 — Slice 10: close the C4 reservation-vs-cash gap, concurrency-safety pass, Charter test-ID coverage

A `/critique` of the prior session found a live overdraft hole: `reservations.request()` never
checked a Cell's cash balance, so a Cell funded with 1,000 minor units could reserve and settle
1,000,000 — conservation and the hash chain both stayed green throughout, which is exactly why
nine slices hadn't surfaced it. SPEC.md §4.1's protocol names a distinct `AUTHORISE` stage between
`REQUEST` and `RESERVE`; it existed nowhere in `src/`, and Charter C4 ("cannot overspend authorised
budget") was that missing stage's guarantee.

- **`src/mitosis/reservations.py`:** `request()` now checks `ledger.get_balance(cell_cash)` against
  `maximum_amount` inside the same `BEGIN IMMEDIATE` as the existing C5 real-spend check, across all
  three books (not just USD_REAL) — a Cell can never reserve more than it currently holds in cash.
  New `InsufficientBalanceError`.
- **Concurrency-safety pass, same bug class found while implementing the above:** `settle()`,
  `release()`, `_bare_status_transition()` (reservations.py) and `_transition()`/`kill()`
  (lifecycle.py) all fetched their entity and validated its current status *before* acquiring the
  write lock, then applied the pre-validated decision after — the same race `create_cell`/`request`
  already guard against correctly. Two concurrent calls against the same reservation/Cell could both
  pass validation before either committed. All five now re-fetch and re-validate inside
  `BEGIN IMMEDIATE`. `resource_metering.record_usage()` had the identical pattern for its
  reservation-ownership/status checks (only the overspend check itself was already inside the
  lock) — fixed the same way.
- **`src/mitosis/accounts.py`:** `FIXED_ACCOUNTS` existed but was never referenced anywhere except
  its own definition — no account-id typo (e.g. `externl_expense`) was ever caught. Added
  `is_known_account()`; wired into `reservations.settle()`'s `destination_account_id` and
  `lifecycle.create_cell()`'s `funding_account_id`, the two call sites where a caller supplies a
  fixed-account name directly. Left the generic ledger core (`_write_transaction`) unvalidated —
  several existing tests deliberately use synthetic placeholder account names (`"x"`/`"y"`/`"a"`/
  `"b"`) to test raw balancing logic decoupled from the real account taxonomy, and validating there
  would have required rewriting them for no correctness gain.
- **`src/mitosis/money.py`:** `parse_minor_units` crashed with a raw `OverflowError` (not the
  documented `ValueError`) on `"Infinity"`, and on `"1e400"` the crash surfaced later, inside
  `ledger._write_transaction`, from SQLite's 64-bit `INTEGER` column rejecting the value. Also,
  `Decimal`'s native underscore-digit-separator support meant `"5_0"` silently parsed as $50.00 with
  no error. Now: non-finite values (`Infinity`/`NaN`) and underscores are rejected with a clean
  `ValueError` at parse time, and any value that wouldn't fit a signed 64-bit integer is rejected
  the same way instead of surfacing as a traceback three layers down.
- **`src/mitosis/events.py`:** `process_event`'s failure path called `record_failure` and then
  `raise`d the original exception — but if `record_failure` itself raised, that replaced the
  original with no trace of the real handler failure. Now the original is always what propagates;
  a `record_failure` exception is chained onto it (`raise exc from bookkeeping_exc`) rather than
  replacing it.
- **`tests/test_charter_properties.py`:** SPEC.md §0.1 claims every Charter clause maps to a named,
  CI-collectible property-test ID (`pytest -k <id>`); 7 of 15 collected zero tests under their own
  name (5 existed only as differently-named functions/classes; C11 and C15 had no test at all).
  Renamed the C2/C3 function and the C7/C8+C10 stateful-machine `TestCase` aliases so each ID is a
  literal substring of its node id; added `charter_canonical_forms` (C11 — money round-trips through
  integer minor units, genome hashing is deterministic and content-addressed, naive/non-UTC
  timestamps are rejected everywhere) and `charter_kernel_immutable` (C15, Phase-1 slice only — no
  Cell executes any code in this kernel at all, so full sandbox isolation is Phase 5/C12; what's
  checkable now is that genome content is inert data, never `eval`/`exec`/imported, and no kernel
  module writes into its own source tree). Added a dedicated `charter_no_overspend` property test
  for the new reservation-vs-cash guard (the existing test under that ID only covered RESOURCE
  metering vs. its reservation cap) and a `cell_cash_never_negative` invariant on the existing
  crash-recovery state machine.
- Added targeted unit tests: `test_reservations.py` (overdraft rejected exactly at the boundary,
  rejected via a second reservation eating remaining cash, allowed at exactly the available amount,
  unrecognized destination account rejected), `test_money.py` (non-finite values, `1e400`,
  underscore separators), `test_lifecycle.py` (unrecognized funding account rejected).
- Verified by hand before/alongside the tests: reproduced the original 1000×-budget overdraft
  end-to-end and confirmed it's now rejected with cash unchanged; confirmed `mitosis
  verify-golden-run` still reproduces its pinned hash unchanged (the golden scenario's reservation
  amounts were already within each Cell's funded budget, so the new guard changes nothing there);
  confirmed the CLI's existing exception handling already catches the new error types cleanly (no
  traceback) since `InsufficientBalanceError`/the account errors subclass the already-caught
  `ReservationError`/`LifecycleError`.
- **221 tests passing** (19 new, 0 removed; up from 202).
- Also split this file: 9 slices had grown it to ~42 KB, well past what a prime should read in
  full every session. Earlier entries moved to `docs/BUILD_RECORD_ARCHIVE.md`;
  `.claude/commands/prime.md` updated to use `git status -sb` (plain `--short` hides the
  ahead/behind line, which is how a 4-commits-unpushed branch was previously reported as "clean").
- Deliberately out of scope for this slice (see PRIORITIES.md): seeded id generation, clock-driven
  timestamps, reproduction/lineage/experiment tracking, model gateway/provider identification,
  wiring event_inbox/outbox into a real producer, `kill()` not sweeping open reservations/residual
  balances, resource-usage reconciliation against real logs, and the remaining CLI commands are all
  unchanged from the prior "Next" list. No CI is wired up yet (no `.github/` workflow) — the Charter
  tests and golden-run replay are collectible and passing locally but nothing runs them
  automatically on push.
- Next: either the CLI remainder (`list-cells/show-cell/fund-cell/kill-cell/ledger/verify-ledger`,
  purely additive) or wiring a CI workflow to actually run pytest + `verify-golden-run` on push —
  both are cheap and neither has a Phase 2+ prerequisite. Seeded id generation remains the largest
  single remaining Phase 1 item.

## 2026-07-21 — Spec review & v0.2 direction locked
- Reviewed MITOSIS v0.1 build spec (`~/Downloads/mitosis_full_build_spec.md`); delivered ~10 findings (real/synthetic money conflation, ledger hardening, reserve-without-release, no global spend breaker, no sim clock, 10-cell population can't show selection, farmable evidence credits, EV-based death, MAP-Elites too sparse, missing prompt mutation).
- User returned a v0.2 revision directive (`~/Downloads/MITOSIS_v0.2_revision_directive.md`) folding in the review + adding profit-first objective, 3-book accounting, population/carrying-capacity control, shared-reputation registry, sim-to-reality promotion ladder.
- Analysed directive: concur ~90%. Logged 4 pushbacks + 12 gap fixes + 7 creative additions (executable Colony Charter, prediction register, coroner reports, per-phase North Star table, governance-overhead ratio, chaos drills, solo-operator/vacation mode).
- Decisions: spec-only first pass; adopt all 19 amendments as normative. Plan saved at `~/.claude/plans/users-mohammadmaster-downloads-mitosis-cheeky-stardust.md`.
- **Wrote `docs/SPEC.md` v0.2** (1309 lines): all 32 directive sections + a Colony Charter (§0.1) mapping 15 constitutional invariants to named CI property-test IDs, all 19 amendments folded in normatively, per-phase North Star metric table (§27.1), Phase 0/1 coding task (§30). Downloads originals left untouched.
- Next: Phase 0 formal artifacts + `docs/DECISIONS.md`, then Phase 1 kernel.
- Committed `512fb2e` — `docs/SPEC.md` + project docs (PRIORITIES.md, BUILD_RECORD.md, CLAUDE.md, FUTURE_BUILD_HOOKS.md). First commit to the repo.

## 2026-07-22 — Phase 0 formal artifacts

- **Wrote `docs/DECISIONS.md`:** 18 ADRs covering the decisions-with-real-alternatives locked into SPEC.md v0.2 (three-book accounting, signed ledger amounts, canonical reservation FSM, real-spend breakers, Phase 3 gate softening, objective-only displacement, deterministic event ordering, executable Colony Charter, sandbox tiering, taint/clean-room migration, solo-operator model, golden-run semantic comparison, genome content addressing, and more), each with context/decision/consequences and a spec-section reference. Remaining amendments that are feature detail rather than alternatives-decisions are cross-referenced in a closing table instead of getting a standalone ADR.
- **Wrote `docs/STATE_MACHINES.md`:** formalized the Cell lifecycle FSM (`created|alive|dormant|quarantined|dead`) — states, transitions, guards, and required side effects — which SPEC.md §30 names but never diagrams; reproduced the already-normative reservation FSM (§4.4) as a companion diagram for implementers.
- **Wrote `docs/EVENT_SEMANTICS.md`:** the inbox/outbox atomic-processing algorithm, the `(effective_time, priority, event_id)` deterministic ordering tie-break (Amendment A5), simulated-vs-real event separation, and poison-event/dead-letter handling (§17.3), spelling out the mechanics behind §17's stated guarantees.
- Considered out of scope for this pass: SQLite DDL/schemas (naturally a Phase 1 kernel deliverable per §30's combined Phase 0+1 task list) and standalone diagrams for fitness vectors / promotion ladder (already adequately tabulated in SPEC.md §10, §25 — no separate artifact needed).
- Next: Phase 1 deterministic kernel per PRIORITIES.md.

## 2026-07-22 — Phase 1 kernel slice 1: ledger + reservations + sweeper

First code in the repo. Python 3.11 (`.venv`, `pyproject.toml`), Pydantic v2, raw `sqlite3` (no ORM, per §30.1 "avoid unnecessary frameworks"), pytest + Hypothesis.

- **`src/mitosis/money.py`:** Decimal-string -> integer-minor-units parsing/formatting (§30 dollar-string rule, Charter C11). Rejects binary-float paths and excess precision by construction.
- **`src/mitosis/migrations/0001_init.sql` + `db.py`:** numbered-migration runner (`schema_migrations` tracking table) per the "write migrations rather than hand-altering DB state" coding rule. Schema for `ledger_transactions`, `ledger_entries`, `reservations` per SPEC.md §3.2/§3.3/§4.2.
- **`src/mitosis/models.py`:** frozen Pydantic models (`Transaction`, `Entry`, `Reservation`) plus `Book`/`ReservationStatus` enums; UTC-aware-datetime validation built in.
- **`src/mitosis/ledger.py`:** `post_transaction` (idempotent, hash-chained, rejects unbalanced/cross-book by construction since `book` lives on the transaction not the entry), `get_balance` (always derived, never cached — C3), `verify_conservation` (C2), `verify_chain` (tamper-evidence, §3.4). Factored a non-transactional `_write_transaction` core so `reservations.py` can post ledger effects inside its own atomic block without nesting SQLite transactions — this was the one real design snag (SQLite `executescript`/nested `BEGIN` don't compose) and cost a couple of iterations to get right.
- **`src/mitosis/reservations.py`:** the canonical FSM from `docs/STATE_MACHINES.md` §2, implemented as an adjacency-table guard (`_ALLOWED_TRANSITIONS`) that doubles as the replay guard — once a reservation leaves a non-terminal state, retrying the same call is rejected rather than double-applied. `request`/`settle`/`release`/`mark_execution_unknown`/`mark_disputed`, each posting its ledger effect and updating status in one SQLite transaction (crash-atomic by construction, Charter C7).
- **`src/mitosis/sweeper.py`:** sweeps expired `reserved` reservations only (resolving stuck `execution_unknown` ones is a separate human/Auditor reconciliation flow, not automatic). Pluggable `ExternalOperationChecker` protocol; the Phase-1 default (`UnknownOperationChecker`) always returns `UNKNOWN` since there's no real external system yet to ask — lands in `execution_unknown`, never guesses `released`.
- **41 tests, all passing:** unit tests per module + `tests/test_charter_properties.py` with Hypothesis — `charter_ledger_balanced` (C1), `charter_conservation_and_balance_match` (C2/C3), and a `RuleBasedStateMachine` (`charter_crash_recovery`, C7) that runs random request/settle/release/crash/reconcile sequences and asserts conservation + hash-chain validity + committed-balance-matches-open-reservations after every step.
- Added `.gitignore` (none existed yet — needed before committing `.venv`/`__pycache__` could leak in).
- Deliberately out of scope for this slice (left for the next Phase 1 pass): `event_inbox`/`event_outbox`, the real-spend circuit breaker, resource metering, Cell lifecycle implementation, genome hashing, simulated clock, population limits, the CLI, and the golden-replay test.
- Next: pick up the Phase 1 remainder per `PRIORITIES.md`, most likely starting with the CLI + `mitosis init` since it gives the fastest path to an end-to-end demo of what already exists.

## 2026-07-22 — Phase 1 kernel slice 2: Cell lifecycle birth + CLI (init/status/create-cell)

`create-cell` can't exist without a Cell to create, so this slice pulled in the minimum lifecycle/genome/audit machinery it depends on rather than stubbing it out:

- **`src/mitosis/migrations/0002_cells.sql`:** `cell_genomes` (all 12 fields from SPEC.md §16.2), `cells`, `audit_events` (Amendment A8).
- **`src/mitosis/genome.py`:** minimal Phase-1 genome (`{"cell_type": ...}` only — real strategy content is Phase 5) canonicalized + SHA-256 hashed (Charter C11). Content-addressed: two Explorers get the same `genome_hash` and share one `cell_genomes` row by design.
- **`src/mitosis/audit.py`:** `record()` — plain insert, no transaction control of its own, same pattern as `ledger._write_transaction`.
- **`src/mitosis/lifecycle.py`:** `create_cell()` — the `created -> alive` birth transition, mirroring `reservations.request`'s shape: funds `cell:{id}:cash` from a funding account (default `seed_bank`), upserts the (deduped) genome, inserts the `cells` row as `alive` directly, and emits the audit event, all in one SQLite transaction. Idempotent on `idempotency_key`, same replay-guard pattern as the rest of the kernel.
- **`src/mitosis/cli.py`:** argparse-based (stdlib, no click/typer), `mitosis --db PATH {init,status,create-cell}`, registered as a `mitosis` console-script entry point in `pyproject.toml`. `init` supports an optional `--seed-capital` for a nicer demo path (funds `external_capital -> seed_bank`). `status` reports migrations applied, per-book transaction counts + conservation + chain validity, cell counts by status/type, reservation counts by status. `create-cell --type --budget [--book] [--funding-account] [--idempotency-key]` — `--book` defaults to `USD_SIM` per Amendment A7, budget parsed via `money.parse_minor_units` (Decimal, never float). Commands against a missing DB fail cleanly with "run `mitosis init` first" rather than silently creating one.
- **Explicit, documented known gap:** `create_cell` does **not** enforce Charter C9 (birth requires carrying-capacity permission) — population limits aren't built yet. Every birth currently succeeds if funding/genome bookkeeping succeed. Called out in the `lifecycle.py` module docstring and in `PRIORITIES.md` so it isn't mistaken for an oversight later.
- Verified end-to-end by hand via the installed console script (`init --seed-capital` → `create-cell` ×2 → `status` shows correct per-type/per-status counts and conservation=OK → re-running `init` is a clean no-op → `status`/`create-cell` against a non-existent DB path fail with exit code 1) before writing the test suite.
- **59 tests passing** (18 new: genome dedup/hashing, lifecycle birth + idempotency + audit-event emission + conservation, and CLI tests via `cli.main()` + `capsys` covering the same end-to-end flow plus error paths).
- Next: Phase 1 remainder per `PRIORITIES.md` — population limits are the natural next piece since `create_cell`'s C9 gap is now the most visible hole, but event_inbox/outbox and the real-spend breaker are also still open.

## 2026-07-22 — Phase 1 kernel slice 3: population limits and carrying capacity (Charter C9)

Closes the known gap flagged at the end of the previous slice.

- **`src/mitosis/migrations/0003_population.sql`:** single-row `colony_config` table. Field names (`max_living_cells`, `max_active_cells`, `max_parallel_experiments`, `max_births_per_epoch`, `max_lineage_population_fraction`) match SPEC.md §27.1's `colony.yaml` `population:` block exactly, including its documented dev defaults (1000/100/20/25/0.20) — added as `DEFAULT_POPULATION_LIMITS` in `models.py`.
- **`src/mitosis/population.py`:** `get_limits`/`set_limits_if_absent` (first `init` wins — re-running `init` with different flags never silently changes a running colony's carrying capacity), `living_count` (any status except `dead`), `active_count` (`alive` only — dormant is idle, quarantined is restricted, neither counts as active), and `check_birth_licence` which raises `CarryingCapacityError` when either cap would be exceeded.
- **Scope decision, stated up front in the module docstring:** only `max_living_cells`/`max_active_cells` are enforced. The other three fields are stored (so the config shape matches `colony.yaml`) but deliberately not checked yet, because their prerequisites don't exist in this kernel: `max_parallel_experiments` needs experiment tracking, `max_births_per_epoch` needs the simulated clock, `max_lineage_population_fraction` needs reproduction/lineage tracking. Same reasoning for skipping Amendment A2's displacement path (docs/DECISIONS.md ADR-009) — displacing an objectively-failing Cell requires the §10.5 death criteria, which nothing in this kernel evaluates yet. A birth beyond capacity is simply denied (`CarryingCapacityError`), matching §9.3's "the birth waits" for the case where no displacement target exists — a synchronous kernel call can't wait, so it raises instead.
- **`src/mitosis/lifecycle.py`:** `check_birth_licence` is called *inside* `create_cell`'s `BEGIN IMMEDIATE` block, after the write lock is acquired but before any genome/ledger/insert work — so two concurrent births can't both pass the check before either commits, same concurrency-safety shape as the Charter C5 real-spend cap check. A denied birth touches nothing: no genome row, no ledger transaction, no idempotency key consumed (verified explicitly in tests).
- **`src/mitosis/cli.py`:** `init` gained `--max-living-cells`/`--max-active-cells` (defaults from `DEFAULT_POPULATION_LIMITS`); `status` now prints `living: X/limit  active: Y/limit` alongside the existing by-status/by-type breakdown; `main()` catches `population.PopulationError` for a clean error message and exit code 1 instead of a traceback.
- Added `test_charter_carrying_capacity` to `tests/test_charter_properties.py` (Hypothesis, C9) — for randomized limits and randomized attempted-birth counts, asserts the living-cell count never exceeds the configured cap after *any* individual attempt, and that exactly `min(attempts, max_living)` births are ever granted.
- Verified end-to-end by hand first (init with `--max-living-cells 2` → 2 successful creates → 3rd denied with a clear message → `status` shows `2/2` → re-init with different limits leaves the colony's limits untouched) before writing the test suite.
- **74 tests passing** (15 new: `test_population.py` unit tests, two `test_lifecycle.py` integration tests for the denial path, three `test_cli.py` tests, one Charter property test).
- Next: Phase 1 remainder per `PRIORITIES.md`. The simulated clock is now a dependency of two open items (`max_births_per_epoch` enforcement and the general Phase 1 remainder), so it's a reasonable next pick — but event_inbox/outbox and the real-spend breaker remain equally open.

## 2026-07-22 — Phase 1 kernel slice 4: global real-spend circuit breaker (Charter C5)

- **`src/mitosis/migrations/0004_real_spend_limits.sql`:** single-row `real_spend_limits` table. Field names/shape match SPEC.md §27.1's `colony.yaml` `real_spend_limits:` block exactly, including its documented dev defaults (25/100/500/5000/200 cents) — added as `DEFAULT_REAL_SPEND_LIMITS` in `models.py`, alongside a new `RealSpendSnapshot` model for status/breaker-check display.
- **`src/mitosis/real_spend_breaker.py`:** `configure_if_absent` (unaudited baseline, same shape as population's set-once) vs `set_limits` (explicit administrator adjustment — always applies, always audited, and the audit `event_type` distinguishes `real_spend_limit_raised` from `_configured` per §5.2's "lowering is immediate, raising needs an audit event"). `snapshot()` computes concurrent-reserved (open USD_REAL reservations) plus settled spend in trailing 1-hour/1-day/~30-day windows (a documented approximation, not a calendar month) by querying `reservation_settle`-type ledger transactions directly — no new timestamp column needed. `check()` enforces per-request, concurrent-reserved, and all three time-windowed caps, treating currently-open reservations as immediate exposure against every window per §5.3 ("settled spend + currently reserved spend, not only completed charges").
- **Scope decision:** `provider_limits` is stored (shape parity with `colony.yaml`) but not enforced — no model gateway or provider identification exists in this kernel yet (Phase 4). Documented in the module docstring, same pattern as population.py's deferred fields.
- **`src/mitosis/reservations.py`:** `check()` is called inside `request()`'s `BEGIN IMMEDIATE` block, gated on `book == Book.USD_REAL` only — USD_SIM/RESOURCE reservations are untouched, and the breaker deliberately does not gate `ledger.post_transaction` generally: real spend flows through the reservation gate per the two-phase-spend model (§4), so an internal treasury transfer like Cell birth-funding isn't "spend" in the sense §5 targets.
- **`src/mitosis/cli.py`:** `init` gains `--per-request-cents/--per-hour-cents/--per-day-cents/--per-month-cents/--max-concurrent-reserved-cents`, all defaulting to `None` so a flag-less re-init never resets a previously-adjusted limit (same footgun-avoidance reasoning as population limits, but the mechanism differs: real-spend limits *are* meant to be live-adjustable by re-running `init` with explicit flags, whereas population limits are set-once — because §5.2 explicitly describes admin raise/lower as an expected workflow and §9 does not). `status` gained a "real-spend breaker (USD_REAL)" section showing concurrent-reserved and hour/day/~30d spend against configured caps.
- Verified end-to-end by hand first (fund a USD_REAL cell → request within caps succeeds → a second request that would push the trailing-hour projection over its cap is denied with the exact numbers in the message → a request over the flat per-request cap is denied → settling the first reservation and re-checking the snapshot shows the settled amount move from "concurrent reserved" into "spend last hour/day/~30d" correctly) before writing the test suite.
- **92 tests passing** (18 new: `test_real_spend_breaker.py` unit tests covering limits config/audit-trail/each cap path/window-boundary math, `reservations.request` USD_REAL-vs-USD_SIM integration tests, four CLI tests, one Charter property test `charter_realspend_cap`).
- Next: Phase 1 remainder per `PRIORITIES.md` — event_inbox/outbox and the simulated clock are the two largest remaining pieces; the simulated clock also unblocks `max_births_per_epoch` enforcement and would let the real-spend breaker's hour/day/month windows use simulated rather than wall-clock time if that ever matters for replay determinism.

## 2026-07-22 — Phase 1 kernel slice 5: simulated clock (SPEC.md §6)

- **`src/mitosis/migrations/0005_simulation_clock.sql`:** single-row `simulation_clock` table — mode, `simulated_seconds_per_wall_second`, plus a `(checkpoint_simulated_at_utc, checkpoint_wall_at_utc)` pair.
- **`src/mitosis/clock.py`:** a *lazy* clock — no background thread ticks time forward; `now()` projects the last checkpoint forward by `elapsed_wall_time * rate(mode)` on read (rate is 0 for paused/step, 1 for realtime, configurable for accelerated — matching colony.yaml's `simulated_seconds_per_wall_second`). This fits the kernel as it exists today: a synchronous CLI tool with no event loop, so there's nothing to tick continuously until Phase 2's flight simulator has a real scheduler. `advance(delta)` re-anchors the checkpoint — the mechanism behind `mitosis advance-time` — and works the same regardless of configured mode, matching §30's CLI requirement. `set_mode()` re-anchors to the current simulated instant before switching, so a mode change is never itself a jump. `get_state`/`now` fall back to an implicit default (paused, anchored at current wall time) when unconfigured, matching the population/real-spend-breaker fallback pattern rather than raising.
- **Explicit, deliberate scope boundary (documented in the module docstring):** existing kernel timestamps — ledger `effective_at_utc`, reservation `reserved_at`/`expires_at`, the real-spend breaker's hour/day/month window math, `audit_events.created_at_utc` — all still run on real wall-clock time; none of them were touched. SPEC.md §6.3's synthetic-vs-real-event timestamp split ("never mixed without explicit conversion metadata") is a separate, larger integration with real correctness risk — e.g. the real-spend breaker's windows would need a careful redesign if USD_SIM and USD_REAL transactions started living on different clocks. This slice ships the clock primitive and `advance-time` only.
- **CLI:** `mitosis advance-time --days N` (exact §30 signature, `--days` accepts fractional values); `init` gains `--clock-mode`/`--clock-rate` (set-once baseline like population limits — re-running `init` never silently resets the clock); `status` gained a "simulated clock" section showing mode, rate, and current simulated time.
- Verified end-to-end by hand first (init paused at a fixed instant → advance by 1 day then 0.5 days → status reflects the cumulative advance → re-init with `--clock-mode realtime` correctly leaves the colony paused → switching an existing colony's clock to accelerated and checking status shows time visibly progressing between commands) before writing the test suite.
- **113 tests passing** (21 new: `test_clock.py` covering all four modes' rate math, advance/set_mode re-anchoring semantics, clock-skew protection, negative-delta rejection, UTC validation, and set-once init behavior; six CLI tests).
- Next: Phase 1 remainder per `PRIORITIES.md`. event_inbox/outbox is now the largest unbuilt piece; wiring the clock into `max_births_per_epoch` and into USD_SIM timestamps are both natural follow-ups but deliberately weren't bundled into this slice.

## 2026-07-22 — Self-review: closed a CLI test-coverage gap

`/critique` on the simulated-clock summary found no factual errors, misalignment, or overclaims — every number and claim checked out against the actual repo (test counts, file scope, ADR references). One genuine minor gap: `clock.advance()` rejecting a negative delta was unit-tested in `test_clock.py` but never confirmed to surface as a clean CLI error (exit 1, stderr message, not a traceback) through `mitosis advance-time --days -1`. Added `test_advance_time_rejects_negative_days` to `test_cli.py`.
- **114 tests passing** (1 new).
- Commit `4b50f48`.

## 2026-07-22 — Phase 1 kernel slice 6: event_inbox/outbox (SPEC.md §17, §3.5; Charter C6)

- **`src/mitosis/migrations/0006_events.sql`:** `event_inbox` and `event_outbox` tables. Field names/shape match §17.2/§3.5's schema list, plus a required `priority` column — the illustrative schema block in SPEC.md/EVENT_SEMANTICS.md omits it, but ADR-011/§17.1's `(effective_time, priority, event_id)` ordering key and "every event producer must supply a stable priority" make it a required field in practice.
- **`src/mitosis/models.py`:** `EventStatus` (`pending|processed|dead_letter`), `Event`, `OutboxEventSpec` (caller-supplied, pre-event_id — mirrors `EntrySpec`/`Entry`), `OutboxEvent`.
- **`src/mitosis/events.py`:** implements docs/EVENT_SEMANTICS.md §3's atomic algorithm exactly. `enqueue` (idempotent on `dedupe_key` — the producer-side guard, same shape as `idempotency_key` elsewhere in the kernel) and `process_event` (the consumer-side guard: checks `event_inbox.status` inside a `BEGIN IMMEDIATE`, re-checked after the write lock in case of a concurrent redelivery race, mirroring the population/real-spend concurrency-check pattern). `next_ready` returns pending events whose effective_time — `simulated_at` if set, else `available_at` — has arrived, ordered `(effective_time, priority, event_id)` per Amendment A5. Poison-event handling (`record_failure`) increments `attempt_number` and, past a configurable threshold, moves the event to `dead_letter` and emits an audit event (§17.3); `replay_dead_letter` is the controlled human-triggered re-admission path. `dispatch_outbox` publishes staged outbox events and marks them published one at a time, so a publisher crash only re-publishes the remainder on retry.
- **Two distinct idempotency guards, deliberately not merged:** `dedupe_key` (producer calling `enqueue` twice for the same logical event) vs. inbox `status` (a single event redelivered and reprocessed) — documented in the module docstring since it's not obvious from the schema alone why both exist.
- **Scope decisions, stated up front in the module docstring (mirrors the pattern from population.py/real_spend_breaker.py):** nothing in the kernel yet produces real events through this path — Phase 2's flight simulator and later Phase 1 work are the first real callers, so this slice ships the primitive only. Poison-event dead-lettering does **not** quarantine the implicated Cell — the `alive`/`dormant -> quarantined` lifecycle transition doesn't exist in this kernel yet (only `created -> alive` birth is built) — that's tracked as its own item in `PRIORITIES.md`. `next_ready`'s ordering compares `simulated_at`/`available_at` ISO-8601 strings directly via SQL, the same approach `real_spend_breaker`'s window queries already use — reconciling that against a *live* simulated clock is deferred until some future slice actually wires `clock.py` into an event producer.
- **`src/mitosis/cli.py`:** `status` gained an "events:" section (inbox counts by status, outbox unpublished count) — the same "extend `status`" integration point used by every prior slice, since no real event producer exists yet to give this a more meaningful CLI hook.
- Verified end-to-end by hand first (enqueue with a duplicate `dedupe_key` short-circuits; `next_ready` orders correctly across mixed priority/effective_time; `process_event` redelivered 4× only invokes the handler once and posts the ledger side effect exactly once; staged outbox events dispatch and don't redispatch; a handler raising 5× against `max_attempts=3` dead-letters on the 3rd attempt and stops calling the handler; `replay_dead_letter` resets it to pending) via a scratch script, then via the installed `mitosis` console script's `status` output, before writing the test suite.
- Added `test_charter_idempotent_handlers` (Hypothesis, C6) to `tests/test_charter_properties.py` — for any redelivery count, a handler's ledger-affecting side effect is applied exactly once and the event ends up `processed`.
- **144 tests passing** (30 new: 28 in `tests/test_events.py` covering enqueue/ordering/idempotent processing/dead-letter/replay/outbox dispatch, 1 Charter property test, 1 CLI status test).
- Next: Phase 1 remainder per `PRIORITIES.md` — resource metering and the remaining Cell lifecycle transitions (which would also close the poison-event quarantine gap) are the two most visible open pieces; wiring the simulated clock and event_inbox/outbox into a real producer are both natural follow-ups but deliberately weren't bundled into this slice.

## 2026-07-24 — Phase 1 kernel slice 7: remaining Cell lifecycle transitions (docs/STATE_MACHINES.md §1, SPEC.md §10.5 Amendment A15, Charter C8/C10)

- **`src/mitosis/lifecycle.py`:** the rest of the Cell lifecycle FSM — `wake` (dormant->alive), `sleep` (alive->dormant), `quarantine` (alive|dormant->quarantined, links the triggering finding in its audit event per §1.4), `clear_quarantine` (quarantined->alive|dormant, mirrors the reservation FSM's disputed->resolved pattern), `kill` (alive|dormant|quarantined->dead, terminal). `_ALLOWED_TRANSITIONS` is the FSM adjacency table from docs/STATE_MACHINES.md §1.2 (`created`/`dead` are deliberately not keys: `created` is transient and handled only by `create_cell`, `dead` is terminal per Charter C8).
- **Real bug caught by hand-verification before the test suite existed:** a single shared adjacency table isn't enough — `wake` and `clear_quarantine` both target `alive`, but `quarantined -> alive` is only a valid FSM edge when it's `clear_quarantine`'s explicit review decision, not `wake`'s implicit wake-event trigger. Running the hand-verification script (see below) surfaced `wake()` silently succeeding from `quarantined`. Fixed by adding a per-operation `valid_sources` set on top of the shared table, so each function also restricts which source status it may fire from — mirroring how `_check_transition` alone wasn't sufficient. This shows up as `test_wake_rejected_from_quarantined`/`test_sleep_rejected_from_quarantined` in the test suite.
- **Coroner reports (Amendment A15):** new `coroner_reports` table (migration `0007_coroner_reports.sql`), filed atomically inside `kill()`. Fields match §10.5's list: genome hash, spend by book, stage reached, cause of death, final hypotheses, links to experiments. **`ledger.spend_by_book`** (new query helper) computes genuine spend per Cell per book — entries tagged with the Cell's `cell_id` that are positive *and* land on an account outside the Cell's own `cell:{id}:cash`/`cell:{id}:committed` pair. This deliberately excludes internal reserve/release moves (cash<->committed, both the Cell's own accounts) and inbound birth funding (negative on the funding side), counting only money that actually left the Cell's control — e.g. a reservation's settlement destination entry. `stage_reached`/`experiment_ids` are always `None`/`[]` in this kernel (stage progression and experiment tracking don't exist yet) — same deferred-field-for-shape-parity pattern as `colony_config`/`real_spend_limits`.
- **Closed the slice-6 gap:** `events.py`'s `process_event`/`record_failure` gained an optional `cell_id`. When given and a poison event reaches dead-letter, the implicated Cell is quarantined in the same transaction via `lifecycle._transition_core` (the non-transactional-core shape `ledger._write_transaction` established, reused here across modules) — but only if the Cell is currently alive/dormant, so a second poison event against an already-quarantined (or dead, for an unrelated reason) Cell doesn't crash dead-lettering.
- **`src/mitosis/cli.py`:** `status` gained a "coroner reports filed: N" line under the cells section.
- Verified end-to-end by hand first: a scratch script exercising birth -> sleep -> wake -> quarantine -> (wake/sleep correctly rejected) -> clear_quarantine -> reserve+settle -> kill -> coroner report, then a second scratch script confirming a failing event handler's dead-letter quarantines the implicated Cell and that a second poison event against the now-quarantined Cell doesn't crash — before writing the automated test suite. Also re-ran the installed `mitosis` console script's `status` output to confirm the new line renders.
- Added `test_charter_dead_cell_inert` (Hypothesis stateful, C8) and `test_charter_audit_complete` (Hypothesis stateful, C10) to `tests/test_charter_properties.py` as one `CellLifecycleMachine`: for any interleaving of birth/sleep/wake/quarantine/clear_quarantine/kill, a dead Cell rejects every further transition attempt, and the audit-event count for a Cell always equals the number of transitions that actually succeeded for it.
- **167 tests passing** (23 new: unit tests in `test_lifecycle.py` for each transition + coroner-report contents, `test_ledger.py` for `spend_by_book`, `test_events.py` for the quarantine wiring, one Charter stateful-machine test class covering C8+C10).
- Deliberately out of scope for this slice (see PRIORITIES.md): `kill()` doesn't sweep the dead Cell's open reservations or reclaim its residual balances; quarantine/taint doesn't use §18's structured provenance-label schema (a free-text reason + linked-finding dict instead); resource metering and the remaining wiring items are unchanged.
- Next: Phase 1 remainder per `PRIORITIES.md` — resource metering is now the most visible unbuilt piece with no remaining lifecycle blocker; wiring the simulated clock into real timestamps and event_inbox/outbox into a real producer remain open follow-ups.

## 2026-07-24 — Phase 1 kernel slice 8: resource metering (SPEC.md §2.2/§2.3 Amendment A6, Charter C4)

- **`src/mitosis/migrations/0008_resource_usage.sql`:** new `resource_usage` table — the Phase-1 `resource_usage` entity §31's data model names explicitly. Fields: `cell_id`/`reservation_id` (both FK'd, NOT NULL — Amendment A6's "every metered operation links to exactly one reservation"), a CHECK-constrained `resource_type` matching §2.2's list (input/output tokens, model calls, CPU/memory-seconds, browser minutes, network requests, storage byte-days, human minutes, approval actions), `quantity` (physical unit count) and `minor_units` (cost against the reservation's budget) as separate columns, `idempotency_key` UNIQUE.
- **`src/mitosis/resource_metering.py`:** `record_usage` — the core of this slice. Requires the reservation to already exist, belong to the given `cell_id`, be `book=RESOURCE`, and be in the exact `reserved` status (not just "not yet terminal" — see the bug below); rejects with `ResourceOverspendError` if the new event would push cumulative recorded `minor_units` past the reservation's `maximum_amount`, checked inside the same `BEGIN IMMEDIATE` the insert runs in (the established C5/C9-style "check under the write lock" shape). This overspend guard **is** Charter C4 ("Cells cannot overspend their authorised budget") for the RESOURCE book — a Charter clause marked P1 in SPEC.md §0.1 that had no implementation or named test until this slice. `total_minor_units`/`usage_by_type` are read helpers a caller uses to feed `reservations.settle`/`sweeper.py` — this slice deliberately reuses the existing settlement machinery rather than inventing a parallel one. `verify_linkage` re-derives Amendment A6's completeness invariant (every usage row's reservation is RESOURCE-book and belongs to the same cell) directly from the tables, the same "double-check against tampering" shape as `ledger.verify_conservation`.
- **Two real bugs caught by hand-verification before the test suite existed** (a scratch script exercising record/idempotent-replay/overspend/wrong-book/settle/reconcile before any pytest was written):
  1. Recording usage against a reservation already in `partially_settled` silently succeeded. `partially_settled` isn't one of the two terminal reservation statuses, but `reservations._ALLOWED_TRANSITIONS` only permits `partially_settled -> released` next — there is no way to settle any *further* recorded usage against it, so it would sit permanently unlinked from a settlement (a direct Amendment A6 violation). Fixed by checking for the exact `reserved` status rather than excluding only `{settled, released}` — the same lesson as slice 7's `wake`/`clear_quarantine` bug: checking "not terminal" is weaker than checking "is the one specific valid state."
  2. (Caught while writing the fix for #1) `execution_unknown`/`disputed` reservations have the identical problem and needed the same fix, folded into the same `!= RESERVED` check rather than an enumerated exclusion list.
- **`src/mitosis/cli.py`:** `status` gained a "resource usage (RESOURCE book, Amendment A6):" section — colony-wide quantity by `resource_type` plus `verify_linkage`'s result.
- Verified end-to-end by hand first: birth a RESOURCE-book Cell, reserve a budget, record usage against it (idempotent replay confirmed, overspend rejected, wrong-book/wrong-cell reservations rejected), settle for the recorded total, confirm usage-after-settlement and usage-after-partial-settlement are both rejected, confirm `verify_linkage`/RESOURCE-book conservation hold — then the installed `mitosis` console script's `status` output with real usage rows — before writing the automated test suite.
- Added `test_charter_no_overspend` (Hypothesis, C4) to `tests/test_charter_properties.py` — for any reservation cap and any sequence of attempted usage recordings, cumulative recorded `minor_units` never exceeds the cap after any single attempt.
- **183 tests passing** (16 new: 15 in `tests/test_resource_metering.py` covering recording/idempotency/validation/overspend/state-guard/linkage, 1 Charter property test).
- Deliberately out of scope for this slice (see PRIORITIES.md): shadow-pricing (converting a raw physical quantity into `minor_units`) is left to the caller — no cost-accounting subsystem exists until Phase 4's model gateway; reconciling recorded usage against actual sandbox/model-gateway logs (Amendment A6's other half) isn't possible yet since no such logs exist; issuing a Cell's initial RESOURCE-book cash balance uses the existing generic `create_cell`/`ledger.post_transaction` path, no new funding flow was added.
- Next: Phase 1 remainder per `PRIORITIES.md` — with lifecycle transitions and resource metering both landed, the simulated-clock/event-producer wiring items and reproduction/experiment tracking (which unblock the remaining deferred population/coroner-report fields) are the largest open pieces.

## 2026-07-25 — Phase 1 kernel slice 9: golden-run replay (SPEC.md §26, Amendment A12, ADR-017; §29 criterion 11)

The last named Phase 1 deliverable with no Phase 2+ prerequisite. §30's deliverable list ends with "golden replay test" and its required-CLI list ends with `mitosis verify-golden-run`; this slice is both.

- **`src/mitosis/golden.py` — the scenario.** One fixed, fully-specified sequence with no randomness and no wall-clock reads: explicit config (population/real-spend/clock set rather than inherited from `DEFAULT_*`, so a later default change can't silently alter the run's meaning), seed capital in all three books, four births (one per Cell type/book combination, whose order *defines* the `cell#N` aliases), the reservation FSM in every shape it supports (full settle, partial-settle-then-release, plain release, and one left in `execution_unknown`), a USD_REAL path inside the C5 caps, resource metering settled for exactly what was metered, every remaining lifecycle transition ending in a coroner report, events including a double-processed batch, a poison event that dead-letters and quarantines its Cell, and an outbox produce-then-dispatch, then a clock advance.
- **The comparison model (ADR-017 / Amendment A12).** `semantic_snapshot` reduces the resulting colony to what its economics *mean* — normalized balances per (book, account), transaction-type counts, Cell status/type/genome-hash, reservation shapes, metered usage, coroner contents, audit-event-type counts, inbox/outbox state, clock position — with every volatile field excluded: uuid4 primary keys, wall-clock timestamps, hash-chain digests. Cell ids become birth-order aliases (`cell#0`…), so `cell:{uuid}:cash` normalizes to `cell:cell#0:cash`. `semantic_hash` is SHA-256 over that canonicalized structure; `semantic_invariants` carries the Charter-level facts (per-book conservation, chain validity, resource linkage, living/active counts, coroner count) alongside it.
- **Why normalization isn't a cop-out, stated in the module docstring:** the kernel has no seeded id generation and its timestamps are still real wall-clock, so a byte-identical rerun is *impossible by construction* today. ADR-017 anticipated exactly this ("semantic invariants plus hash, not raw byte equality"). Both underlying gaps are tracked in PRIORITIES.md.
- **Verified the comparison actually earns its two halves** (hand-verification, before the test suite): monkeypatching `kill()` to stop filing coroner reports trips the *invariants* (`coroner_reports: expected 1, got 0`); monkeypatching births to overfund by 1 keeps conservation perfectly intact — all invariants pass — and is caught *only* by the hash. That second case is the concrete argument for ADR-017's "plus a hash" and is now `test_hash_catches_drift_that_invariants_miss`.
- **Determinism gap found and logged** (`FUTURE_BUILD_HOOKS.md`): Amendment A5's `(effective_time, priority, event_id)` key is a *total* order but not a *reproducible* one — same-instant same-priority events tie-break on a `uuid4`. The scenario sidesteps it by giving every event a distinct priority, but a Phase 2 producer would be flaky. Real finding, out of scope here (seeded ids touch every `uuid.uuid4()` call site).
- **Also found:** the first regression simulation (breaking C6 idempotency directly) never reached the snapshot — the handler's own ledger `idempotency_key` rejected the double-post first. Defence in depth working as intended, and worth knowing the golden run's C6 assertion is a second line rather than the only one.
- **CLI:** `mitosis verify-golden-run` prints the invariants, both hashes, and on failure names the diverged invariants plus the snapshot sections that differ (§26.2's "visible diff"), exiting 1. `--update-expectations` is A12's migration path — it regenerates `golden_expectations.json` and prints a warning that an unreviewed change means behaviour drifted. Runs against its own fresh in-memory colony, never the `--db` path, so a golden run can't depend on or disturb real colony state (asserted in `test_verify_golden_run_does_not_touch_the_colony_db`).
- Verified by hand first: generated the expectations through the CLI itself, confirmed a clean PASS with exit 0, confirmed the hash is byte-identical across 5 consecutive runs, hand-checked the resulting economics rather than just their stability (USD_SIM conservation sums to 0; `colony_treasury` is 300 not 600, proving the double-processed events landed once — Charter C6; the `execution_unknown` reservation still holds its 250 committed — Charter C7; the coroner's 1,550 spend correctly excludes the 550 that was released), then confirmed the CLI drift path prints diagnostics and exits 1.
- **202 tests passing** (19 new: `tests/test_golden.py` covering the scenario's coverage of every lifecycle status and reservation shape, the C6/C7 pins, hash reproducibility across runs, absence of volatile identifiers from the snapshot, alias stability, the shipped-expectations CI guard, and both drift-detection paths; plus three CLI tests).
- Deliberately out of scope: seeded ids and clock-driven timestamps (both tracked); replaying from *stored model outputs* (§26.2) — no model calls exist until Phase 4, so there's nothing to record yet; multiple golden scenarios (§26.1's "scenarios" plural) — one thorough scenario is the right size until Phase 2 produces behaviour worth pinning separately.
- Next: Phase 1 remainder per `PRIORITIES.md`. Seeded id generation is now the most load-bearing open item (it unblocks reproducible event ordering *and* byte-level replay); the remaining CLI commands (`list-cells/show-cell/fund-cell/kill-cell/ledger/verify-ledger`) are the last purely-additive Phase 1 surface.

---

## 2026-07-26 — Reproduction and lineage tracking (the Phase 2 prerequisite)

The first Phase 1 item that isn't merely additive: Phase 2's flight simulator needs Cells that
reproduce, and `max_lineage_population_fraction` (§9.2) had been stored-but-unenforced since slice 3
precisely because there was no lineage to measure.

- **New `src/mitosis/lineage.py` + migration `0009_lineage.sql`.** `reproduce()` is the second
  birth path: a child of a living Cell, **funded from the parent's own cash** rather than a colony
  account. That funding rule is the point — a parent cannot mint capital, so lineage growth is
  bounded by the lineage's own money, and Charter C4's guard applies to reproduction for free.
  `cells` gained `parent_cell_id` (NULL for a seeded founder), plus immutable denormalized
  `founder_cell_id`/`generation`.
- **The design decision, written up as `docs/DECISIONS.md` ADR-019.** §9.4 defines lineage
  "strictly by genome parentage", which is unimplementable as stated against this kernel: genomes
  are content-addressed (ADR-018) and Phase 1 genome content is a placeholder carrying only
  `cell_type`, so *every* commercial Cell hashes to one genome row — deriving lineage from it would
  put unrelated Cells in one lineage and fire the cap on them. There's also a structural problem
  independent of Phase 1: under content addressing an unmutated child *is* its parent's genome, so
  a genome-parentage edge for it would be a self-loop. Resolution: vertical descent is recorded on
  the Cell and is what the cap is enforced against; genome parentage is recorded too, but only
  where a mutation actually changed the content. Amendment A10's substance is preserved — lineage
  means vertical descent, and a shared module (or a shared genome) never creates a lineage edge.
- **`max_lineage_population_fraction` now enforced** (`check_lineage_licence`, inside the write
  lock like every other birth check). Two consequences worth stating plainly, both documented in
  lineage.py, ADR-019, and the error message itself: seeded founders are exempt (a founder has no
  ancestor, and a lone founder is trivially 100% of a one-Cell colony), and **a small colony
  genuinely cannot reproduce** — with the colony.yaml default of 0.20, any second-generation Cell
  in a 4-Cell colony is already 40% of it. Growing past the seed needs enough founders or a
  raised cap. That's §9.3 applied literally ("the birth waits" → a synchronous kernel raises),
  matching the conservative stance population.py already takes for displacement.
- **`genome.py` gained mutation support:** `canonical_genome_json(cell_type, mutation)` overlays
  caller-supplied fields, with JSON-serializability validated up front (new `GenomeError`).
  `lifecycle._get_or_create_genome` now carries `parent_genome_hashes`/`mutation_operator`/`version`
  on creation, and drops a self-referential parent edge if a "mutation" didn't actually change
  anything. Provenance is recorded only when the row is *created* — rediscovering existing content
  from a different parent must not rewrite how that genome first came to exist.
- **Golden run extended** (SPEC.md §26 names the "expected lineage tree" as golden-run content, so
  reproduction drift had to become visible in CI): the scenario now reproduces the auditor with a
  mutated genome, and `semantic_snapshot` carries parent/founder/generation as *aliases*, keeping
  the snapshot uuid-free. This is a real expectation migration via the A12 path
  (`--update-expectations`); the diff was reviewed line by line and every change is attributable to
  the new step — parent debited exactly 500, child credited 500, one new `cell_reproduction_funding`
  transaction, one more lifecycle audit event, living 3→4, active 2→3. No conservation, chain, or
  linkage invariant moved. The scenario's lineage cap was raised to 0.50 with a comment, since a
  4-Cell colony can't reproduce at 0.20.
- **CLI:** new `mitosis reproduce --parent --budget [--type --mutation --mutation-operator]`, and
  `status` gained a lineage section (per-founder living/total/depth/share, largest first, plus the
  integrity check).
- Verified by hand before the tests, which is again where the design got pinned down: built a
  4-generation lineage at realistic scale and confirmed generation/founder propagation, that an
  unmutated child reuses its parent's genome row while a mutated one gets a distinct genome with a
  correct parent edge and incremented version, that the parent is debited exactly the child's
  budget with conservation and the hash chain intact, and that a death shrinks the *living* lineage
  count without erasing lineage history. Then drove every rejection path (unknown/dormant/
  quarantined/dead parent, over-balance, zero budget) confirming cash was unchanged after each, and
  the CLI's error paths end to end (clean `error:` lines, exit 1, no tracebacks).
- Also verified the **migration upgrade path**, which no test covers because every test builds a
  fresh DB: built a colony on the pre-0009 schema, confirmed the new columns were genuinely absent,
  then upgraded it and confirmed `founder_cell_id` backfills to each Cell's own id with
  `generation` 0 and integrity green. That detour surfaced one real robustness gap — a NULL founder
  (unreachable through the kernel, but reachable in a corrupted or hand-edited DB) made `status`
  traceback instead of reporting, right next to the integrity line that exists to flag it. Fixed
  and covered.
- **274 tests passing** (43 new, 0 removed; up from 230). New `tests/test_lineage.py` (36);
  `tests/test_cli.py` gained 6 for the new verb and the status section; `test_golden.py` gained
  `test_snapshot_pins_the_lineage_tree`. Charter coverage: C9 gained
  `test_charter_carrying_capacity_lineage_share`, a Hypothesis property that no lineage ever
  exceeds its configured share across arbitrary reproduction sequences — it immediately earned its
  keep by falsifying an over-strong first draft of the invariant and forcing the seeded-founder
  exemption to be stated explicitly (now pinned by its own test rather than assumed away).
- Deliberately out of scope, unchanged from the prior list: **displacement** (§9.3/ADR-009) still
  isn't implemented — a denied birth stays denied, because the §10.5 death criteria that identify an
  objectively-failing Cell to evict still don't exist. Sexual recombination / multi-parent genomes
  (§16.5) are out (schema takes a list; `reproduce` takes one parent). §16.3's inheritance classes
  are not modeled: a child inherits genome content and nothing else, since this kernel has no
  assets, obligations, customers, or credentials to inherit or withhold. `max_births_per_epoch` is
  still unenforced (needs the clock wired to a real epoch counter) and `max_parallel_experiments`
  still needs experiment tracking.
- Committed as `0224866` and pushed.
- Next: Phase 2's other prerequisites are experiment tracking (also unblocks
  `max_parallel_experiments` and the coroner report's always-empty `experiment_ids`/`stage_reached`)
  and wiring the simulated clock into real timestamps/epochs. The remaining CLI commands and
  `kill()`'s reservation/balance sweep stay additive.

---

## 2026-07-27 — Phase 4 model gateway: the kernel can spend real money

A deliberate jump over Phases 2 and 3. The stated goal was to get Cells spending real money as
quickly as possible, so the flight simulator (Phase 2) and the evolutionary-machinery validation
(Phase 3) were skipped rather than deferred-by-accident. **That tradeoff is real and worth
restating: the selection machinery those phases exist to validate is still unvalidated, so this
colony can now spend real money on an evolution loop nobody has shown works.** Defensible for a
bounded, hard-capped experiment; not defensible at scale.

Everything below is the first code in MITOSIS whose *successful execution costs money*.

- **`pricing.py`** — versioned pricing table (`PRICING_TABLE_VERSION`, recorded on every call so a
  price change reads as an accounting change rather than as Cell behaviour, per §24.2). Cost is
  computed in **micro-USD**, not USD_REAL minor units, and rounded **up** to the cent for the
  ledger. Written up as **ADR-020**: USD_REAL's minor unit is the cent, a single call routinely
  costs a fraction of one, and rounding down would have Charter C5's caps computed off an
  understated bill — the breaker would fail *open*. The overstatement this creates (up to 0.999
  cents per call) is stated plainly rather than hidden; the exact micro-USD figure is preserved per
  row for the invoice reconciliation that will true it up.
- **`providers.py`** — `ModelProvider` protocol (§30.1's provider-agnostic interfaces), a
  deterministic zero-priced `MockProvider`, and the paid `AnthropicProvider`. **Charter C14 is
  enforced structurally, not by a runtime check**: no credential is an argument to, a field of, or
  a return value from anything in the module; the key is read from the environment into a local
  that dies with the frame. Plus `redact()`, because an SDK exception message is the realistic way
  a credential reaches a database. `_is_execution_unknown` classifies failures conservatively —
  only a definitely-unbilled rejection (400/401/403/404) releases funds.
- **`gateway.py`** — reserve (USD_REAL, provider-tagged) → reserve (RESOURCE, the A6 metering link)
  → call → settle at *reported* usage → meter input/output tokens → mirror into USD_SIM (§2.4, an
  independent synthetic expense, never a cross-book transfer). Reserve-before-execute is the whole
  point: caps are checked inside the reservation's write lock, so concurrent calls cannot
  collectively exceed a limit each individually respects.
- **`max real spend per provider` (§5.1) is now enforced** — stored-but-unchecked since slice 4,
  the second such "stored but inert" limit to be closed (after `max_lineage_population_fraction`;
  `max_parallel_experiments` and `max_births_per_epoch` are still stored and unchecked).
  Reservations gained a `provider` column so the check is atomic with the reservation insert.
- **Five bugs, none of which broke a kernel invariant — conservation and the hash chain stayed
  green through all of them. Three were found by hand-verification before any test ran, one by a
  test written afterwards, one by `/critique` after the slice was first reported done:**
  1. *(hand)* **Over-reservations were stranded in `committed` forever.** The gateway reserves a
     worst case and settles for less; nothing released the difference. Every call quietly drained
     the Cell's spendable cash *and* ratcheted the C5 concurrent-reserved cap tighter, until the
     colony could no longer call at all.
  2. *(hand)* **Output-token metering was silently dropped** by subtracting the running total
     twice, so A6's completeness invariant had a hole exactly where the cheapest models are.
  3. *(hand)* A zero-priced model produced a misleading "mirror rounds to zero" reason.
  4. *(test)* **Cost overruns were invisible to both the global and per-provider spend windows** —
     the serious one, and the one hand-verification missed. `test_per_provider_cap_counts_settled_
     spend_too` asserted an exposure of 8 and got 6. An overrun is real money leaving the colony
     but is *not* a reservation settlement, and every breaker query filtered on
     `reservation_settle`, so the breaker went blind precisely when a provider billed above
     estimate.
  5. *(critique)* **Cost and metering priced off different models.** The USD_REAL charge used the
     provider's `resolved_model` while the RESOURCE shadow price used the requested one, so a
     substituted model (§24.2) made the two books disagree about the same call. Both now use one
     resolved `billed_model`.
- **ADR-021** covers the overrun decision itself: `settle` refuses to exceed its reservation (that
  refusal *is* C4), but the provider has already billed. Clamping and recording nothing further
  would make the ledger understate real spend and compound silently in the dangerous direction, so
  the shortfall is posted directly with a loud audit event. C4 governs *authorisation*, which the
  reservation enforced at the only moment it could change the outcome; recording an incurred charge
  is accounting. This can drive a Cell's cash negative — deliberately, since an overdrawn Cell then
  fails every subsequent balance check and stops.
- **Charter C14 gained its first test** (`charter_no_secret_in_cell`, previously P4-and-untested):
  the Cell-facing request type cannot carry a credential, a canary key planted in the environment
  and leaked through a provider exception never appears in *any* column of *any* table, and no
  kernel module outside `providers.py` mentions a credential at all.
- **CLI:** new `fund-cell` (pulled into scope, not gold-plating — a calling Cell needs balances in
  three books and there was no way to fund the second and third) and `call-model`, which requires
  `--yes-spend-real-money` for any paid provider. A required flag rather than a prompt, so it
  survives being scripted.
- **Golden run extended** through a reviewed A12 migration (expectation version 1 → 2), with a new
  `model_calls` snapshot section. Diff reviewed line by line: every change attributable to the new
  step, no USD_REAL movement at all (the mock provider is priced at zero — a replay that could bill
  someone is not a replay), funding transactions netting exactly, and the 1-cent floor reservation
  settling 0 then releasing. Latency and response hash are excluded from the snapshot for the same
  reason timestamps are.
- **356 tests passing** (82 new, 0 removed; up from 274). New `tests/test_pricing.py` (15),
  `tests/test_providers.py` (23), `tests/test_gateway.py` (30); `test_cli.py` +9, `test_golden.py`
  +2, `test_charter_properties.py` +3 (C14). Note CI reports **355 passed + 1 skipped**: it
  installs `.[dev]` only, so the one test that needs the `anthropic` package is skipped there.
- `anthropic` is an **optional** dependency (`pip install 'mitosis[anthropic]'`). The kernel, the
  full suite, and the golden run all run without it — §30.1's "mock before paid APIs".
- **No real money has actually been spent yet.** The paid path is wired, unit-tested against a
  stub, and gated, but no live call has been made: that needs an `ANTHROPIC_API_KEY` and a
  deliberate run. That is the top item in PRIORITIES `Next`.
- **Known gap, not deferred by choice — found in self-review after the slice was reported done:
  the success path is not crash-atomic.** `_handle_success` performs roughly six independent
  write transactions (settle real, optional overrun, up to two `record_usage` rows, settle
  resource, mirror, final `UPDATE model_calls`). Each is individually atomic, but a crash
  *between* them leaves the `model_calls` row in `'reserved'` with money already partly moved,
  and `sweeper.py` has no knowledge of `model_calls` at all — so there is no recovery path and
  no operator verb to resolve one. Charter C7 covers exactly this boundary for a single
  reservation and is tested (`charter_crash_recovery`); the gateway's *composition* of several
  reservations is not covered by that test or any other. This is the largest correctness gap in
  the slice and should be closed before sustained real spend, not after.
- Also inaccurate as first written, now corrected: `_REAL_SPEND_TRANSACTION_TYPES` is **not** a
  single source of truth. `_settled_spend_for_provider_since` still hardcodes both transaction
  types in its own two SQL queries, so a third real-spend type added to the tuple would be counted
  by the global caps and silently missed by the per-provider cap. Logged in FUTURE_BUILD_HOOKS.
- Deliberately out of scope, and recorded in `gateway.py`'s docstring as well as PRIORITIES:
  routing by task type (§24.3), controlled retries (a retry after `execution_unknown` risks
  double-billing and needs reconciliation to decide safely), structured-output validation, model
  competition, and reacting to provider drift as a §8.4 regime change — drift is *recorded*
  (`resolved_model`/`api_version`) but nothing consumes it. `reconciled_micro_usd` (§24.1) is
  always NULL: there is no provider invoice to reconcile against.
- Committed as `ef6cb06` and pushed — as one arc together with the two entries it belongs
  with (Phase 4 gateway, crash atomicity, provider-invoice reconciliation), since the three
  interleave across the same files and no intermediate state was separately verifiable.
- Next: close the crash-atomicity gap above (the largest known correctness hole), then either make
  the first real paid call (small cap, one prompt) or close the reconciliation gap that both the
  ADR-020 rounding overstatement and `execution_unknown` resolution depend on.

---

## 2026-07-28 — Gateway crash atomicity: one paid call, one transaction

Closes the "known gap, not deferred by choice" the entry below ends on — the largest correctness
hole in the Phase 4 slice, and the thing that entry says to fix *before* sustained real spend
rather than after.

- **The gap, precisely.** `_handle_success` was ~6 independent write transactions (settle real,
  optional overrun, up to two `record_usage` rows, settle resource, mirror, final `UPDATE
  model_calls`). Each was individually crash-atomic — that is Charter C7, and it is tested. But one
  paid call is not one reservation, and a crash *between* two of those six left real money spent
  against a call still recorded as `'reserved'`, with nothing able to say which steps had run.
  `sweeper.py` had no knowledge of `model_calls`, so there was no recovery path and no operator
  verb. `_handle_failure` had the same shape in miniature (3 transactions).
- **What makes it the dangerous kind of bug: every existing invariant stays green in that state.**
  A settled reservation whose call row was never updated balances perfectly — conservation holds,
  the hash chain validates, A6 linkage is intact. Nothing in the kernel would ever have reported
  it. This is the third distinct instance of the same lesson (after the C4 reservation-vs-cash gap
  and the cost-overrun blindness): the invariants catch violations of rules someone wrote down,
  never the absence of a rule.
- **Fix (ADR-022).** `_handle_success` and `_handle_failure` each hold one `BEGIN IMMEDIATE` and
  compose new `_*_locked` cores — `reservations._settle_locked`/`_release_locked`/
  `_bare_status_transition_locked`, `resource_metering._record_usage_locked`,
  `ledger._post_transaction_locked`. This is not a new pattern: `ledger._write_transaction` and
  `audit.record` were already exactly this split, which is what made the change small. Steps 1–3
  (reserve USD_REAL, reserve RESOURCE, insert the row) stay *outside* the transaction deliberately
  — they must be durably committed before the external call, or reserve-before-execute means
  nothing.
- **Recovery, without inverting the dependency.** `sweeper.py` still does not import `gateway` and
  still does not know what a model call is; its `ExternalOperationChecker` protocol was built for
  exactly this and had only ever had the Phase 1 "answer UNKNOWN to everything" implementation. The
  gateway now supplies `GatewayOperationChecker` (USD_REAL -> UNKNOWN, because the request may have
  been billed and nothing local can tell; RESOURCE -> released, because no provider can bill an
  internal shadow price — but HAPPENED, settled at what was metered, if usage rows exist, so A6 is
  never violated by discarding them) and `resolve_stranded_calls` for its own rows. New `mitosis
  sweep` verb runs both in dependency order and prints a standing warning while any reservation
  sits in `execution_unknown`.
- **What the fix deliberately does not do, and why it's the right call anyway.** A rollback also
  discards the provider's response — the one thing a crash cannot reconstruct. So a crashed call
  resolves to `execution_unknown` with its money still committed: **honest, but not complete**, and
  it needs a human. The alternative (record the response first under a `settling` status, then let
  recovery finish the settlement from real usage figures) is strictly more capable and was
  deferred, not rejected — it needs a new status, a migration and a second idempotency story, and
  it shares all its plumbing with §24.1 invoice reconciliation. Logged in ADR-022's alternatives,
  the gateway docstring, PRIORITIES `Next`, and FUTURE_BUILD_HOOKS.
- **Hand-verification did its job again, and this time also proved the tests aren't vacuous.**
  A file-backed colony, a priced call, and a genuine crash at three points inside the transaction
  — the injected failure derives from `BaseException` so the module's own `except Exception:
  ROLLBACK` never runs, then the connection closes with the transaction open and SQLite rolls it
  back on reopen exactly as it would after process death. All three came back to the pre-call
  state. Then the counterfactual: re-emulating the old separate-transaction shape reproduced the
  original bug exactly (3 cents in `external_expense`, reservation `settled`, call still
  `'reserved'`) **with conservation and the hash chain green throughout**, confirming both the
  diagnosis and that the new assertions have teeth. Repeated against the test suite: 4 of the 5
  new crash tests fail against the pre-fix shape, and the 5th fails against a pre-fix
  `_handle_failure`.
- **368 tests passing** (12 new, 0 removed; up from 356). `test_gateway.py` +9 (3 parametrized
  crash points, the sweep-to-`execution_unknown` path, the stranded-status mapping, the
  don't-touch-an-in-flight-call guard, both checker behaviours, and failure-path atomicity),
  `test_cli.py` +3. Both new C7 tests are `pytest -k charter_crash_recovery`-collectible alongside
  the existing reservation machine, per SPEC.md §0.1.
- **Golden-run hash unchanged** (expectation version still 2, no A12 migration). Correct and worth
  stating: a pure atomicity change alters no economic outcome on a path that never crashes, so a
  changed hash here would have meant an accidental behaviour change.
- Also corrected while adjacent: ADR-021's closing claim that
  `_REAL_SPEND_TRANSACTION_TYPES` "is now the single list" — it isn't, as
  FUTURE_BUILD_HOOKS already recorded and the gateway entry below already flagged. The ADR now says
  so instead of contradicting them.
- **New hazard introduced, stated plainly:** the `_*_locked` cores perform no BEGIN and no COMMIT.
  Called outside a transaction, SQLite autocommits each statement and the atomicity this slice
  bought is silently gone — with no test failure, because every invariant still holds. They are
  underscore-private and each says so in its docstring, but that is a convention, not an
  enforcement; a `conn.in_transaction` assertion or a lint rule is logged in FUTURE_BUILD_HOOKS.
- Committed as `ef6cb06` and pushed — as one arc together with the two entries it belongs
  with (Phase 4 gateway, crash atomicity, provider-invoice reconciliation), since the three
  interleave across the same files and no intermediate state was separately verifiable.
- Next: the first real paid call (small cap, one prompt), or §24.1 reconciliation — which now
  carries the deferred forward-recovery work as well.

---

## 2026-07-28 — Provider-invoice reconciliation: the number the kernel cannot compute

ADR-022 taught crash recovery to park a call in `execution_unknown` with its money committed, and
then nothing in the kernel could resolve one. This closes that loop, and with it §24.1's
`reconciled cost` — the last always-NULL field in the gateway schema.

- **`reconciliation.py` + migration 0011.** Two paths, chosen by the state of the call's USD_REAL
  reservation. Funds still committed (`reserved`/`execution_unknown`/`disputed`) are resolved
  through §4.4's FSM — settle at the invoiced amount, release the remainder, or release outright
  when the invoice shows no charge. Funds already moved are corrected by posting a **new**
  transaction, because §3.6 is explicit that reconciliation never edits history. Both paths end the
  same way: `reconciled_micro_usd`, `reconciled_at_utc`, `reconciliation_source`, an audit event,
  all in one transaction using ADR-022's `_*_locked` cores — which earned their keep one slice
  after being introduced.
- **Releasing an `execution_unknown` reservation happens here and only here.** Charter C7 forbids
  *auto*-releasing an unknown external operation; a release that is the *outcome of
  reconciliation* is the process C7 defers to, not an exception to it.
- **Reconciling does not change a call's `status`** — a reconciled `execution_unknown` call stays
  `execution_unknown`, and `reconciled_at_utc` marks it resolved. Promoting it to `succeeded` would
  invent a response the kernel never saw: we learned what the call cost, not what it returned.
  Same authorisation-versus-accounting split as ADR-021, and it avoids a status migration.
- **The `_REAL_SPEND_TRANSACTION_TYPES` footgun had to be fixed to land this, and the reason is
  worse than the one logged.** The logged risk was that a third real-spend type would be counted
  globally and missed per-provider, because `_settled_spend_for_provider_since` hardcoded its own
  copy in SQL. True, and now fixed — both queries read the tuple. But the adjustment is also the
  first real-spend type that can be **negative**, and *both* breaker queries selected the spend leg
  with `e.amount_minor_units > 0`. On a credit the positive leg is the refund landing in the Cell's
  own cash — so a refund would have been counted as fresh spend, and **paying a Cell back would
  have pushed it toward the circuit breaker instead of away from it.** Both queries now sum the
  signed `external_expense` leg. Hand-verified with the counterfactual: the old filter reports 6
  where the true net is 2.
- **Two bugs found by hand-verification, before any test existed. Neither was a coding slip:**
  1. **A §4.4 violation.** The FSM gives `disputed` a deliberately narrower exit than
     `execution_unknown` — `settled | released`, with no `partially_settled`. Reconciling a
     disputed call at less than its full hold tried to settle partially and hit
     `InvalidTransitionError`. The fix is release-plus-adjustment, which is both what §3.6
     prescribes and how a disputed charge resolves commercially. Widening the FSM was rejected: it
     contradicts a normative spec section.
  2. **My own docstring overclaiming.** The slice was motivated partly by ADR-020's rounding
     overstatement, and I wrote that reconciliation hands it back. It does not, and cannot: 3.5
     cents of true cost converts through the same `micro_usd_to_minor_units` ceiling to the 4 cents
     already recorded, so the adjustment is zero. The overstatement is sub-minor-unit by
     construction and only becomes correctable in aggregate. Corrected in three docstrings, pinned
     as `test_sub_cent_rounding_is_not_correctable_per_call`, and logged as the aggregate-invoice
     work that would actually close it. **What this slice fixes is estimate error and unknown
     outcomes, not rounding.**
- **A third finding, deliberately not fixed:** `ledger.spend_by_book` has the same sign trap — a
  credit's negative `external_expense` leg is dropped by its `amount > 0` filter, so a refund never
  reduces a Cell's recorded spend. Removing the filter is *not* the fix, because birth funding's
  negative leg carries the same cell_id and a freshly-funded Cell would read as having spent a
  negative amount. Separating them needs an account-level distinction between funding sources and
  spend destinations that §31's account list does not draw — a modelling decision, not a patch, and
  not one to make inside a reconciliation slice. Documented in the function, FUTURE_BUILD_HOOKS and
  PRIORITIES. Bounded: coroner reports only, never an enforcement check.
- **CLI:** `reconcile` (dollar string parsed at micro-USD precision via new
  `pricing.parse_micro_usd` — cents are too coarse for an invoice line, and rounding the operator's
  own evidence before it reaches the ledger would defeat the point), `dispute`, and `outstanding`,
  which orders frozen money first. Hand-verification also caught two display bugs an operator would
  have hit immediately: `outstanding` reported a *released* reservation's returned funds as still
  frozen, and a crashed call printed `estimated: None micro-USD`.
- **405 tests passing** (37 new, 0 removed; up from 368). New `tests/test_reconciliation.py` (32),
  `test_cli.py` +5. Teeth-checked by reverting each fix in turn: the disputed-path test and the
  credit-does-not-inflate-spend test both fail against the pre-fix code.
- **Golden run extended** through a reviewed A12 migration (expectation version 2 → 3). The
  scenario reconciles its mock call against a zero invoice, which is the honest figure for a
  zero-priced provider. Diff reviewed section by section: only `audit_event_types` (+1) and
  `model_calls` (+3 fields) changed — `balances`, `transaction_types` and `reservations` are all
  identical, which is the evidence that no money moved. The adjustment paths, where the sign
  matters, are covered by unit tests rather than the golden run *on purpose*: pinning them would
  mean giving up the property that a golden replay never moves USD_REAL.
- **Migration upgrade path hand-verified** against a genuine pre-0011 colony left over from the
  previous slice (the test suite cannot see this — every test builds a fresh DB): columns land
  NULL rather than garbage, and the pre-existing call correctly reads as outstanding.
- Committed as `ef6cb06` and pushed — as one arc together with the two entries it belongs
  with (Phase 4 gateway, crash atomicity, provider-invoice reconciliation), since the three
  interleave across the same files and no intermediate state was separately verifiable.
- Next: the first real paid call, or aggregate-invoice reconciliation.

---

## 2026-07-30 — Real-spend type registration: replacing the reviewer

`_REAL_SPEND_TRANSACTION_TYPES` is the list both the hour/day/month caps and the per-provider cap
read. A USD_REAL type that posts to `external_expense` but is missing from it is real money the
breaker cannot see, so the caps fail **open** — the one direction that matters. Membership was a
convention enforced by a reviewer noticing, and it was missed twice inside a single arc:
`model_call_cost_overrun` shipped unregistered, and `model_call_reconciliation_adjustment` arrived as
the first type whose amount can be negative, which both queries mishandled. This replaces the
reviewer.

- **Three angles, because no one of them is sufficient.** (1) An **AST walk** over `src/mitosis`
  requiring every `transaction_type=` to be either registered or exempted *with a stated reason* —
  the only angle that fires on a genuinely new type, whatever that type does. (2) A **precise static
  check** that any call site naming `external_expense` uses a registered type — this is the one that
  would have caught the cost overrun, and it fails pointing at `gateway.py:569`. (3) A **behavioural
  check**, parametrized over the registry itself, that each registered type is actually summed by
  *both* spend windows.
- **The behavioural angle exists because the static one structurally cannot cover the main path.**
  `reservation_settle` takes its destination account from the reservation record at runtime, so
  `external_expense` never appears at its call site. The kernel's single largest real-spend path is
  invisible to a source-level check, and only a test that moves money can confirm the breaker sees
  it.
- **A subtlety I had assumed away, caught by the test failing on first run.**
  `model_call_sim_mirror` also posts to `external_expense` — `external_expense` is an account name,
  not a book, and the §2.4 mirror debits the same account in `Book.USD_SIM`. So the static check has
  to resolve the **book** as well as the account, treating a dynamic `book=book` as possibly-real and
  only excluding a statically-provable `Book.USD_SIM`. The exclusion is then asserted explicitly
  (`test_sim_book_postings_to_external_expense_are_excluded_deliberately`) rather than left implicit,
  because misfiling a real-spend type as USD_SIM is precisely how one would hide from the check.
- **Pinned an undocumented coupling that would have bitten the next person to register a type.** The
  per-provider query finds a direct posting by joining `model_calls` on
  `transaction_type || ':' || model_call_id`. A newly-registered type with any other idempotency-key
  shape is counted globally and silently missed per-provider — the *exact* asymmetry the gateway
  slice logged and the reconciliation slice fixed, reintroducible for free. Registration in the
  tuple is necessary but not sufficient, and the test now says so in its failure message.
- **Exemption reasons were verified against each call site's book and entry accounts, not inferred
  from the name.** `colony_seed_capital` is the one that would have caught me out: it is
  USD_REAL-capable and touches an account called `external_capital`, which is a different account
  from `external_expense` and flows the opposite way (capital entering the colony).
- **Teeth-checked by reintroducing each bug in turn**, per the practice that has now caught something
  in every slice: unregistering `model_call_cost_overrun` fails 2 tests and names its call site;
  introducing a novel unclassified type fails classification (and *also* trips the stale-exemption
  check, which is the cross-check working); breaking the idempotency-key convention fails the
  per-provider assertion for both direct types. Each mutation was reverted and the tree confirmed
  clean.
- **Guard against the tests going vacuous**, since a static walk that finds nothing passes forever: a
  floor on discovered call sites, an assertion that at least one site names `external_expense`, and
  stale-entry checks in both directions (an exemption for a type no longer in the kernel, a
  registered type no call site posts — the latter catches a typo in the tuple).
- **412 tests passing** (7 new, 0 removed; up from 405). Golden-run hash unchanged, which is correct
  for a test-only change — a changed hash would have meant an accidental behaviour change. All five
  new C5-relevant tests are `pytest -k charter_realspend_cap`-collectible alongside the existing
  property test (6 collected), per SPEC.md §0.1; `test_charter_properties.py`'s ID map now
  cross-references them.
- **The registry comment in `real_spend_breaker.py` now points at its own enforcement**, so the next
  person to add a type reads both the requirement and the idempotency-key constraint at the point of
  change rather than discovering them from a breaker query.
- **What this deliberately is not: a runtime guard.** The airtight version is a check where the
  transaction is written — if `book` is USD_REAL and any entry hits `external_expense`, require a
  registered type — which no novel code shape can bypass. Not built here because the registry lives
  in `real_spend_breaker` while the check belongs in `ledger` (the tuple needs moving to a neutral
  module first), and because raising there fails a legitimate-but-unregistered transaction closed in
  production. For real money that is arguably the *right* direction, so it is logged in
  FUTURE_BUILD_HOOKS as worth revisiting before sustained real spend rather than dismissed.
- Committed as `1518677` and pushed.
- Next: the first real paid call, which now needs only an `ANTHROPIC_API_KEY` and a deliberate
  `--yes-spend-real-money` run against a tiny cap.

---

## 2026-08-05 — The first real paid call: one cent, and what it measured

MITOSIS has spent real money. `claude-haiku-4-5` (resolved
`claude-haiku-4-5-20251001`), 12 input tokens, 4 output tokens, 32 micro-USD of true cost, **1 cent
recorded in USD_REAL**. The model replied `ok`. Every number below was verified against the ledger
rather than read off the CLI's own summary.

- **The call was set up to be boring on purpose.** A dedicated `first-real-call.db` capped at 5¢ per
  request and $1.00 per month, one explorer Cell funded in all three books, and a free `MockProvider`
  dry run on the same colony first — so the only untested variable when real money moved was the live
  API itself.
- **Cost math reconciles exactly.** 12 input × $1/Mtok = 12 μ$, 4 output × $5/Mtok = 20 μ$, total 32
  μ$ — matching `cost_actual_micro_usd` and both `resource_usage` rows independently. One
  `reservation_settle` entry of 1 minor unit on `external_expense`, and it is the *only* USD_REAL
  entry on that account in the whole colony. Cell cash 20¢ → 19¢. Conservation OK in all three books,
  hash chain valid, A6 linkage complete, `committed` zero everywhere.
- **ADR-020's overstatement, measured rather than argued: 312×.** True cost 0.0032¢, recorded 1¢. The
  ceiling is correct — rounding down would have Charter C5's caps computing off an understated bill —
  but at this size the ledger is recording the *floor of a cent*, not the cost. This is the sharpest
  possible argument for aggregate-invoice reconciliation, which is the only thing that can recover
  it, and it is now a number instead of a prediction.
- **The estimate over-reserved by 10.8×** (347 μ$ held against 32 μ$ actual), because it reserves the
  full `max_tokens` output. Harmless to the ledger — the remainder released cleanly — but with a 5¢
  per-request cap it is the *estimate*, not the real cost, that decides whether a call is permitted.
- **And it under-counts input, which is the opposite of what was assumed.** `_estimate_tokens` uses 2
  chars/token and predicted 11 where the API's own `count_tokens` returned 12. It is documented as a
  deliberate over-estimate; for short prompts it is not, because the heuristic ignores per-message
  structural overhead. The backlog item to tighten it should be rewritten: input needs a *floor*,
  output needs a tighter ceiling.
- **Two failure paths ran for real before the successful one, and both behaved.** A RESOURCE
  under-funding tripped Charter C4 (`cannot reserve 347`, C4 refusing before any money moved), and an
  invalid key produced a 401 that `_is_execution_unknown` classified as definitely-unbilled — so
  funds were *released* rather than frozen in `execution_unknown`. Verified afterwards: across five
  failed attempts, every USD_REAL reservation reached `released`, `committed` was 0, and no
  transaction touched `external_expense`. The release-on-failure path that the gateway slice's bug #1
  was about had never run outside a test until now.
- **Model drift was recorded and nothing consumed it**, exactly as documented: requested
  `claude-haiku-4-5`, resolved `claude-haiku-4-5-20251001`. §24.2 captured it; reacting to it as a
  §8.4 regime change remains unimplemented.
- **Also fixed, spotted while verifying: `outstanding` counted zero-cost calls as billable work.**
  The mock provider is priced at 0, so it produces calls no invoice will ever list, and both
  `outstanding` and `summary` counted them — noise that grows without bound as mock calls accumulate.
  Both now share one `_BILLABLE_PREDICATE` (already moved real money, recorded a real cost, or still
  holding funds), deliberately kept as a single string so the two queries cannot drift apart — the
  same two-copies-of-one-rule shape that let a third real-spend type be missed by one of two breaker
  queries. It remains a **worklist, not a gate**: `reconcile` still accepts any `model_call_id`, so a
  surprise charge on a nominally free call can still be applied, and that is pinned by its own test.
- **414 tests passing** (2 new, 0 removed; up from 412). `test_outstanding_lists_then_clears` was
  rewritten rather than deleted — it had encoded the old behaviour, and now asserts the new semantics
  plus the worklist-not-a-gate property. Teeth-checked by reverting the predicate: both new tests
  fail against the old shape. Golden-run hash unchanged (expectation version still 3), correct for a
  change that alters no economic outcome.
- **`.gitignore` gained `.env` / `.env.*`.** It had neither, and the credential file needed for a
  paid call sits in the repo root — with `git add -A` in the commit flow, an API key was one command
  away from being pushed to GitHub.
- Committed as `a28b86b` and pushed.
- Next: see PRIORITIES. The honest summary is that the *kernel* is proven and the *colony* does not
  exist yet — nothing in MITOSIS can currently earn a cent, and Phases 2 and 3 remain skipped.

---

## 2026-08-05 — Revenue, and a second provider: the two halves of a fitness signal

Both prerequisites for open-ended, self-directing Cells, built together because neither is useful
alone. **Money can now enter the colony**, so profitability is a number rather than an aspiration;
and **inference can now be free**, so a Cell can think without every thought hitting Charter C5's
caps. Nothing here makes a Cell autonomous — that is still the missing subsystem — but it is what
autonomy would need underneath it.

### Revenue (`revenue.py`, SPEC.md §31, §2.2)

- **The `revenue` account existed in §31's fixed-account list and nothing ever posted to it.** A
  Cell's profitability was therefore not merely unmeasured but *unmeasurable* — the number had
  nowhere to live. `record_revenue` gives it one, mirroring spend exactly: a spend debits the Cell
  and credits `external_expense`; revenue debits `revenue` and credits the Cell's cash. The
  `revenue` account accumulates gross earnings negated, the same convention `external_capital`
  already uses, so conservation per book (Charter C2) is unchanged.
- **Revenue is not spend, and the separation is the load-bearing decision.** It never touches
  `external_expense`, so the real-spend breaker cannot see it — deliberately. Charter C5 bounds how
  much the colony may *spend*, not its net position, and a Cell that earns must not thereby earn
  permission to spend past a cap. The one intended coupling is Charter C4: earnings are cash, and a
  Cell may reserve up to its cash. Both halves are pinned by their own tests.
- **The teeth check on that separation produced the clearest possible argument for it.** Mutating
  revenue to post to `external_expense` *and* registering `cell_revenue` as a real-spend type makes
  the hour window read **−10,000 instead of 0** — a Cell would literally earn its way *backwards*
  through the circuit breaker. Each half of that mutation is independently caught by last slice's
  registration guard (the disjointness check for one, the precise static check naming
  `revenue.py:106` for the other), and the breaker test catches the combination. Stated plainly
  because it matters: `test_revenue_does_not_move_the_spend_breaker` **cannot fail on either half
  alone** — it is a backstop, and the registration guard is what actually holds each side.
- **Attribution is mandatory.** `source` is required and refused when blank, the same rule
  reconciliation applies to invoice figures, for the same reason: an unattributable credit to a Cell
  is precisely how a fitness signal gets fabricated, and fitness is what this exists to feed. The
  default idempotency key is derived from the source, so posting the same attributed payment twice
  is refused by the ledger rather than silently doubling a Cell's apparent fitness.
- **A dead Cell can still receive revenue** — payment arrives after the work, sometimes after the
  worker, and a coroner report omitting final earnings would misstate the thing it exists to record.
  Status is not checked; existence is, so revenue cannot be posted to a typo.
- **RESOURCE is refused.** Nobody pays a colony in compute units, and allowing it would let a Cell
  top up its own metering budget by declaring revenue.

### Ollama provider (`providers.OllamaProvider`, SPEC.md §30.1)

- **The second provider, and the one that makes exploration affordable.** A Cell that proposes
  strategies constantly cannot do that against a metered API without the proposal stage dominating
  its budget. Local inference has no per-call marginal cost, so the creative loop can run flat out
  and never touch a cap. Registered in the pricing table at zero.
- **Zero dependencies.** Uses stdlib `urllib` against Ollama's HTTP API rather than an SDK — unlike
  `anthropic`, which is optional precisely because it is heavy. A local model should not cost the
  kernel an install.
- **Charter C14 in its cleanest form: there is no key to leak.** Ollama is unauthenticated on
  localhost, so no credential exists anywhere in the provider's surface — asserted by a test rather
  than assumed. `OLLAMA_HOST` is a URL, not a secret, and is still passed through `redact()` on the
  error path in case it points at an authenticated proxy.
- **Never reports `execution_unknown`, which is a deliberate departure from
  `_is_execution_unknown`'s conservatism.** That default exists because wrongly releasing a
  reservation for a call that *was* billed loses real money silently. A local provider cannot bill:
  its USD_REAL exposure is structurally zero, so freezing funds would park money against an invoice
  that can never exist, and `mitosis outstanding` would ask a human to resolve something no evidence
  could ever resolve. What a timeout does cost is RESOURCE metering accuracy — a shadow-price
  imprecision, not a money risk. Documented on the class and pinned across 400/500/503/timeout.
- **Models are registered explicitly rather than priced zero by wildcard**, and that friction is on
  purpose: an Ollama-compatible endpoint can front a *paid* hosted model, and a wildcard would
  silently price it at zero and blind Charter C5 to real spend. An unknown model fails loudly.
- **A zero price is not a free call.** Local compute is still metered and shadow-priced in the
  RESOURCE book, so a runaway local Cell is still bounded — proven end to end by an integration test
  driving the gateway with a stubbed Ollama: USD_REAL settles at 0 and the breaker stays at 0, while
  the provider's *reported* token counts (17 in / 5 out) are metered, not estimates.
- **Ollama names everything differently** (`num_predict`, `prompt_eval_count`, `eval_count`), and
  getting that mapping wrong corrupts A6 metering silently rather than failing. Each is pinned;
  dropping `num_predict` would let a local call generate past its metered budget.
- Missing usage counters (Ollama omits `prompt_eval_count` on a fully cached prompt) meter as zero
  rather than crashing — zero recorded tokens is true, and a crash would strand the reservation.

### Verification

- **448 tests passing** (34 new, 0 removed; up from 414). New `tests/test_revenue.py` (13),
  `tests/test_ollama_provider.py` (16), `test_cli.py` +5. Golden-run hash unchanged.
- **Last slice's registration guard fired on the very next slice, as designed.** `cell_revenue` was
  refused as unclassified until it was explicitly exempted with a stated reason — the convention it
  replaced would have let a new money-moving type through on a reviewer's attention.
- **Hand-verified on the live colony** that made the real paid call: recorded 75¢ of revenue against
  the Cell that had spent 1¢. Cash 19 → 94, `revenue` account −75, conservation and hash chain green,
  breaker unmoved at 1/25, and re-posting the same `source` returned the *same* transaction id with
  no double-count. **Net position: +74 minor units — the first profit figure MITOSIS has ever been
  able to compute.**
- One verification bug worth recording because it nearly became a false alarm: a shell-interpolated
  account id in my own check string was mangled (`…986ash`), so `get_balance` was asked about a
  nonexistent account and returned 0, making it look as though the balance had not moved. The code
  was correct; the check was not. Identifiers in hand-verification scripts should come from the
  database, not from shell interpolation.
- Committed as `945ef04` and pushed.
- Next: fitness (revenue − spend) is now computable, but `ledger.spend_by_book`'s sign bug becomes
  load-bearing the moment selection reads it — a credited Cell currently reads as having spent more
  than it did. That fix needs §31's account-level split between funding sources and spend
  destinations, and it should land *before* anything selects on profit. See PRIORITIES.

---

## 2026-08-05 — `spend_by_book`: the account-level distinction §31 never drew

Logged since the gateway slice as "coroner reports only, never enforcement" — which stopped being
true the moment revenue landed, because fitness is `revenue − spend` and selection would read it.
Fixed before anything selects on profit, which was the whole point of doing it now: a wrong spend
figure does not fail loudly, it kills the wrong Cells and compounds down every generation.

- **The known bug.** A reconciliation credit debits `external_expense` with a *negative* amount, and
  the old query filtered `amount_minor_units > 0`, so a refunded Cell kept its full recorded spend
  forever. The reason it could not be fixed by deleting the filter is the other half: birth
  funding's negative leg carries the same `cell_id`, so an unscoped signed sum makes a
  freshly-funded Cell read as having spent a *negative* amount. **Neither half is fixable alone** —
  the sign only becomes meaningful once the account is known.
- **The fix: classify the account, then trust the sign.** `accounts.py` now carries
  `SPEND_DESTINATIONS` and `CAPITAL_ACCOUNTS`, each entry with its reason, and `spend_by_book` is
  the **signed** sum of a Cell's entries landing on a spend destination. A credit reduces it; a
  capital movement never enters it.
- **The distinction is consumption versus capital movement — not internal versus external, which
  is where I started and would have been badly wrong.** Settling metered compute into
  `infrastructure_reserve` never leaves the colony but is unambiguous cost to the Cell. I only
  caught this because the golden run settles there and hand-verification then showed **the gateway
  settles every RESOURCE metering there too** (`gateway.py:372`, `:730`). Under the
  internal/external framing, *every Cell's entire compute consumption would have silently vanished
  from `spend_by_book`* — and with Ollama making USD_REAL free, the RESOURCE book is now the only
  thing bounding a local Cell, so the hole would have opened exactly where the next work is headed.
- **A second overstatement, found by the teeth check and not previously named.** Faithfully
  restoring the original query makes the consumption test read **1600 instead of 700**: the old
  code counted a `colony_treasury` capital return as spend. So it overstated on two independent
  paths — credits never subtracted, and capital returns wrongly added. Only the first was logged.
- **A completeness guard, in the shape that has now paid off twice.** `unclassified_accounts()`
  plus a test means adding an account to §31's list forces a spend-or-capital decision instead of
  silently defaulting to "not spend". Same lesson as the real-spend type registry: the invariants
  catch violations of rules someone wrote down, never the absence of a rule.
- **The golden run does not protect this, and the teeth check proved it.** Misclassifying
  `infrastructure_reserve` makes spend read `{}` instead of `700` while `verify-golden-run` still
  passes — the golden scenario's coroner'd Cell only ever spends to `external_expense`. The unit
  tests are the only cover, which is worth knowing before trusting the golden run as a backstop for
  accounting-shape changes.
- **453 tests passing** (5 new, 0 removed; up from 448). Golden-run hash unchanged — correct and
  meaningful here: the fix is identical to the old code everywhere the old code was right, and
  differs only in the cases that were broken. A changed hash would have meant an accidental
  behaviour change.
- **Teeth-checked three ways:** the faithful original query fails the credit test (300 vs 200) and
  the consumption test (1600 vs 700); the naive fix (drop the sign filter, keep the old scoping)
  makes a funded Cell read **−1000**; and misclassifying an account fails the consumption test.
- **Hand-verified on the live colony** that made the real paid call: `spend_by_book` reads
  `{RESOURCE: 34, USD_REAL: 1, USD_SIM: 1}` against 75 earned — fitness **+74**. Posting a 1¢
  reconciliation credit moves USD_REAL spend `1 → 0`, where the old code would have held it at 1.
  Conservation and hash chain green throughout. (That credit is left in `first-real-call.db`, which
  is a gitignored scratch colony.)
- Committed as `dd4d215` and pushed.
- Next: fitness is now a trustworthy number, so the prediction register (a Cell states expected
  earnings *before* spending) is the cheapest real selection pressure available and needs no
  customer. Then §10.5 death criteria, which closes the evolutionary loop since reproduction
  already works. The agent loop remains the missing subsystem.

---

## 2026-08-05 — Prediction register: selection pressure without a customer

Amendment A14 / §8.5, normative since the v0.2 spec and unbuilt until now. **The reason to build it
before an agent loop exists:** selection needs a fitness signal, revenue needs a customer, and there
isn't one — but calibration needs neither. A Cell that predicts its own outcomes badly is
demonstrably worse than one that predicts them well, whatever it is doing and whether or not anyone
pays for it. This is the cheapest real selection pressure available, and it can start
discriminating between Cells on day one.

- **`prediction.py` + migration 0012 (`prediction_register`, §31).** Register before the outcome is
  known, resolve once, score with both rules §8.5 names — Brier `(p−o)²` and log `−ln(p_actual)`.
  `calibration()` returns §8.5's curve; `scores()` the means.
- **Binary claims, because the spec named the rules.** Brier and log are defined over binary
  outcomes, so a continuous quantity is predicted by stating a threshold — "revenue >= 50 minor
  units" — not a point estimate. This is the spec's constraint, not an implementation shortcut, and
  worth being explicit about: **a point revenue estimate cannot be scored by either named rule.**
  Doing that properly needs CRPS or an interval rule, which §8.5 does not authorise, so it is logged
  rather than invented.
- **Certainty is refused.** `probability` must be strictly inside (0, 1), enforced in Python *and*
  by a schema CHECK. The reason is not fastidiousness: the log score of a confident-and-wrong
  prediction is infinite, one such prediction would pin a Cell's mean at −inf permanently, and **a
  population containing several infinitely-bad Cells cannot be ordered — so it cannot be selected
  on.** `log_score` also clamps, so a row that somehow escaped the CHECK scores very badly rather
  than uncomparably.
- **Hash-chained, like the ledger, for the same reason.** A per-row hash proves nothing against an
  editor who recomputes it; chaining means altering any prediction invalidates every prediction
  after it. That is what turns "register-before-outcome" from a convention into something
  `verify_chain` can check. **The hash covers the prediction and never the outcome** — including the
  outcome would defeat its only purpose, and would also make recording what happened look like
  tampering (pinned by `test_resolving_does_not_break_the_chain`).
- **The anti-gaming surface, which is the part that decides whether any of this means anything.** A
  Cell that resolves only its winners has a beautiful calibration curve and a pile of unresolved
  losers behind it. `overdue()` lists predictions past their own deadline, `scores()` reports
  `unresolved` and `overdue` *beside* the means rather than quietly omitting them, and the CLI
  prints an explicit warning that the scores are self-selected and unreliable while any are
  outstanding. Nothing here *forces* resolution — that is a policy question for whatever drives
  selection — but the omission is now impossible to miss.
- **Calibration is returned as buckets, not one number, because the shape is the diagnosis.**
  Systematic overconfidence and systematic underconfidence can produce the *same* mean Brier score
  and call for opposite corrections. `test_calibration_curve_separates_confidence_from_accuracy`
  pins exactly that case: ten claims at p=0.9 that come true half the time.
- **CLI:** `predict`, `resolve-prediction` (mutually exclusive `--occurred` / `--did-not-occur`, so
  an outcome cannot be omitted by accident), and `calibration`, which prints the curve, the scores,
  the overdue warning, and the chain-validity check.
- **481 tests passing** (28 new, 0 removed; up from 453). New `tests/test_prediction.py` (25),
  `test_cli.py` +3.
- **Golden run extended through a reviewed A12 migration** (expectation version 3 → 4): three
  predictions — one resolved true, one resolved false, one left deliberately open so `unresolved`
  appears in the snapshot and a future change cannot silently drop the anti-gaming surface. Diff
  reviewed section by section: only `predictions` and two new `audit_event_types` changed, while
  `balances`, `transaction_types`, `reservations`, `cells`, `resource_usage`, `model_calls` and
  `coroner_reports` are **absent from the diff entirely** — the evidence that predictions move no
  money. Scores were re-derived by hand against the snapshot: `(0.8−1)² = 0.04`, `−ln(0.8) =
  0.223144`, `(0.6−0)² = 0.36`, `−ln(0.4) = 0.916291`. Float scores are rounded to six places in the
  snapshot so a last-place difference across platforms cannot break replay for a reason unrelated
  to behaviour.
- **Teeth-checked three ways:** making the hash cover the outcome fails three chain tests including
  the resolve-is-not-tampering one; removing the chaining check fails the tamper test; allowing
  certainty fails at the schema CHECK — which incidentally proved the two guards are independent,
  since the test then fails on the wrong exception type.
- **Hand-verified on the live colony** that made the real paid call. Migration 0012 applied cleanly
  to a genuine pre-0012 database. Two predictions registered and resolved (0.85→occurred, Brier
  0.0225; 0.3→did not occur, Brier 0.09; mean 0.0563 ✓). Then the property that matters: editing a
  resolved prediction's probability directly in SQL made `verify_chain` return **False**, and
  reverting it returned **True**. Tamper-evidence demonstrated on real data, not only in a test.
- One test bug of my own, worth recording: the overdue CLI test originally set a sub-second deadline
  and raced the wall clock, which had not elapsed by the next command. Rewritten to move the
  deadline into the past — deterministic, faster, and a more honest depiction of what an overdue
  prediction actually is.
- Committed as `312e1d9` and pushed.
- Next: §10.5 death criteria. With calibration and `spend_by_book` both trustworthy and `kill()`
  already built, death is what closes the evolutionary loop — reproduction already works, so a
  colony that can select is a colony that can evolve. The agent loop remains the missing subsystem,
  and nothing here changes that: a Cell still cannot make its own predictions.

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
- Committed as `2c876dd` and pushed; CI green.
- Next: §9.3 displacement is now unblocked and is the natural follow-on — a birth denied at capacity
  can evict an objectively-failing Cell rather than simply waiting. Beyond that the agent loop is
  still the missing subsystem, and it is worth being plain that **nothing here selects on its own**:
  `reap` must be called, and no Cell yet acts, predicts, or earns without a human driving it.

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
- Committed as `d779e18` and pushed.
- Next: the agent loop is still the missing subsystem. Worth being plain that **displacement
  selects nothing on its own either** — it fires only when a caller passes `--displace`, and no
  Cell yet acts, earns, or reproduces without a human driving it.

## 2026-08-06 — The agent loop: a Cell that thinks

Everything built until now was machinery *for* a Cell. This is the Cell. A wake is: assemble
bounded context (§15) → one gateway call → parse a strict structured proposal → record it with
its predictions registered before their outcomes (§8.5). Then it sleeps.

**Reading the normative sections first changed the design more here than in any previous slice,
because the obvious agent loop violates four of them at once and still looks like it works.**

- **§25.1's promotion ladder puts this at rung 5 — "shadow prediction with no action" — not rung
  9.** "No strategy moves directly from synthetic success to autonomous commerce" is the section's
  opening line. So a proposal is a row in a table that no kernel path consumes. The natural loop
  ("let the model decide, then do it") skips eight rungs, and would have felt like progress.
- **§0.3: "A Cell may explain a result; it may never define the canonical result."** This is the
  one that shapes the schema. The proposal type carries intentions and explanations only — there
  is no field for what a Cell earned, achieved, or how well it did. Revenue still comes from the
  ledger, calibration from the hash-chained register. A Cell under selection pressure that can
  grade itself is a colony grading Cells on testimony.
- **§19.4: model output is untrusted content, never a trusted command.** Unknown fields are
  rejected rather than ignored, so a reply inventing `"authorised": true` fails loudly.
- **Charter C15 holds only while genomes are inert.** Genome content is rendered into the prompt
  as JSON and interpreted; nothing is `exec`'d or selects a code path. C12's sandbox is Phase 5.

### What landed

- **`proposal.py`** — the only shape a deliberation may return. `extra="forbid"`, bounded text,
  binary threshold predictions with probabilities strictly inside (0,1), and
  `FORBIDDEN_FIELD_SENSE`: a named list of fields that must never exist, with a test that fails if
  any becomes real. It is not a blocklist the parser consults (nothing unknown gets through
  anyway) — it is a tripwire on the *schema*, so drifting toward self-reporting has to be an
  argued change rather than a plausible-looking commit.
- **`context.py`** — §15.1's per-wake budget, taken literally. Sections are priority-ordered,
  required ones (policy, genome, wake reason) are reserved up front and never dropped, and what
  did not fit is **recorded by name**: "do not load the entire Cell history" is only a checkable
  claim if the selection says what it left out.
- **`deliberation.py`** — the loop, plus the wake-event path. Refusals are *recorded, not raised*:
  a dead Cell woken, or one that cannot afford to think, is a fact about the colony that should
  appear in a query rather than only in a traceback.
- **The event inbox got its first real producer and consumer**, closing a gap open since slice 6.
- **CLI:** `wake`, `enqueue-wake`, `run-wakes`, `proposals`. Provider selection was extracted into
  one helper so the paid-provider confirmation lives in exactly one place — a second copy of that
  `if` is how a verb eventually ships without the gate.

### The architectural surprise

**A wake cannot run inside `events.process_event`'s handler transaction.** That contract requires
the handler not to commit; ADR-022 requires the gateway's reservation to commit *before* the
external call, or reserve-before-execute means nothing. Both cannot hold. So `run_wake_event`
deliberates first and marks the event processed after, and idempotency on a wake key derived from
the event id carries the guarantee instead — which is what Charter C6 actually asks for
("handlers must be idempotent under at-least-once redelivery"), not transactional atomicity. A
crash in the window leaves the event pending and the deliberation done; redelivery finds it and
completes the bookkeeping. Pinned by a test that simulates exactly that window.

### Verification

- **549 tests passing** (29 new, 0 removed; up from 520).
- **Golden run extended** via a reviewed A12 migration (expectation version 4 → 5): a wake event
  enqueued and drained, one deliberation, one proposal, one prediction, plus `deliberations` and
  `proposals` snapshot sections. Every part of the diff traces to that one wake, and **no USD_REAL
  balance moves** — the mock is priced at zero, and a golden run that started spending real money
  would be the single worst regression this file could miss. The snapshot deliberately captures
  `context_tokens` and the dropped-section list, so context assembly cannot quietly start loading
  everything without the hash moving.
- **Teeth-checked eight ways**, one per guarantee: adding a self-reported outcome field, ignoring
  unknown fields, letting a dead Cell deliberate, breaking wake-key idempotency, raising the
  history cap, disabling the token budget, allowing duplicate claims, and storing the raw prose
  each fail their named test.
- **One test was passing for the wrong reason and the teeth check caught it** — the history-bound
  assertion was written as `<= context.RECENT_PROPOSALS`, i.e. against the constant, so raising
  the constant to 1000 satisfied it while loading exactly the history §15.1 forbids. Rewritten to
  an absolute bound. (This is the second slice running where the teeth check found a tautological
  test; the pattern is asserting against the thing under test.)
- **Hand-verified on a live colony**, both paths: the mock's default prose reply produced a
  recorded `unparseable` deliberation naming the parse error and storing none of the text, and a
  compliant reply produced a `proposed` deliberation with two unresolved predictions dated 14 and
  30 days out. The Cell's contribution afterwards reads **revenue 0, spend 0, mean Brier None** —
  it proposed and claimed nothing that moved a canonical metric, which is §0.3 working. Ledger and
  prediction chains valid, conservation green in all three books, A6 linkage complete, wake event
  processed, RESOURCE balance down 4 units: the Cell paid for its own thinking.
- Committed as `e7b1f69` and pushed; CI green.
- **What this does not show:** the loop has never been driven by a real model. Ollama was not
  reachable on this machine, and the paid path needs an explicit decision to spend. So there is no
  evidence yet about how often a real model returns schema-valid JSON — the unparseable path
  exists because it will not always. That, and something that wakes a Cell without a human asking,
  are the top two Next items.

---

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

---

## 2026-08-22 — The read-back: what a rung is actually worth

`outcome.py` (ADR-030). ADR-029 recorded §25.2's promotion evidence at the moment of funding, and
half of §25.2's list cannot exist at that moment — it asks for "predicted vs **observed** outcome"
and for "reality gap (from the prediction register, §8.5)", both of which need outcomes that arrive
later. Until now nothing read them back, so "the colony is climbing §25.1's ladder" was an
assertion rather than a measurement, and `transfer_degradation` would have stayed NULL for every
Cell forever.

### §8.5 fixed the design, and the obvious measure was wrong twice over

The obvious read-back is the Cell's mean Brier score today. It counts outcomes the approver could
already read — part of the record that *justified* the funding, not evidence about what the funding
achieved — and it counts forecasts the Cell registered *after* the money arrived. The second is a
live gaming surface: §23.5 warns that the review path "will be optimised against by Cells", and the
cheapest optimisation available to a newly funded Cell is a pile of easy claims.

So the verdict rests on exactly one set: forecasts **open at the instant of funding** that have
since resolved. Hash-chained before the outcomes were knowable, unarrangeable afterwards. Forecasts
made while funded are counted and reported beside the verdict and never inside it — the same
asymmetry ADR-027 drew between a Cell's `claimed_tier` and the kernel's `assessed_tier`, applied to
evidence instead of risk.

### Cherry-picking blocks a verdict outright, ahead of any score

`prediction.py` is blunt that "a mean Brier score over three cherry-picked resolutions is worse than
useless", and resolution is operator-supplied — a Cell's losers can simply stay open. So any overdue
forecast in the funding set returns `EVIDENCE_WITHHELD` **before** a score is computed, including
when the resolved remainder looks excellent. Hand-verified on the case that matters: three
resolutions at Brier 0.0025 plus one outcome nobody recorded produces no verdict, not a promotion.
`EVIDENCE_WITHHELD` is kept distinct from `INSUFFICIENT_EVIDENCE` because the remedies are opposite
— and because resolution is the operator's job, a withheld verdict is a finding about the evidence,
not an accusation against the Cell.

### §10.3 forbade the other obvious measure

"Explorers need no immediate revenue", and Explorers are most of this colony — so a verdict that
asked whether the grant earned its money back would reject exactly the Cells the clause protects.
Cost and revenue are **recorded** per §25.2 and never gated on. What is judged is calibration, on
two dimensions that §10.2 forbids collapsing: §8.5's reality gap against the record the promotion
was granted on, and an absolute bar at the 0.25 a coin scores. They are genuinely independent, and
the case that proves it is a Cell funded on 0.01 now scoring 0.09 — passes the absolute bar, fails
the relative one.

### No table, and nothing may read a verdict

There is **no migration**. The assessment is recomputed from the register and the ledger every time,
the posture Charter C3 takes toward balances, and the reason migration 0016 already gives for
snapshotting calibration rather than copying predictions: a second copy is a second version that can
disagree. Storage becomes right when a decision consumes an assessment, and nothing does.

`test_no_kernel_path_acts_on_an_assessment` closes both directions. Upward, acting on
`supports_promotion` would take §25.1's rung-8 step — removing one of the two humans in every
allocation — without an argument. Downward and harder, §10.5 forbids killing on an estimate without
strong evidence *and* a concurring Auditor, and no Auditor Cell exists, so `death.py` must not be
able to see a negative verdict at all.

### Verification

- **659 tests passing** (23 new, 0 removed; up from 636).
- **Golden expectation 9 → 10**: the scenario now runs deliberate → queue → approve → allocate →
  resolve → assess. **No money moves in the step at all** — resolving a forecast posts no
  transaction, so `balances`, `transaction_types` and `reservations` are byte-identical to version
  9 and `external_expense` stays 0 in every book. Two sections in the diff were **not predicted**
  when the migration note was first drafted and are named in it: the mock reply is three
  predictions longer, so `output_tokens` and the metered `quantity` both go 139 → 279 (the metered
  *charge* is unchanged, which is why balances hold).
- **Teeth-checked twelve ways**, each failing its named test: post-funding forecasts leaking into
  the verdict, already-resolved forecasts counting as observed outcome, cherry-picking no longer
  blocking, a verdict on one lucky resolution, the reality gap collapsed into the absolute bar, no
  absolute bar at all, the ladder becoming a profit test, cost measured over a lifetime, the
  allocation counted as supervision of itself, liability fabricated as 0, `death.py` culling on a
  verdict, and an assessment writing a row. **One test passed for the wrong reason** —
  `test_cost_is_measured_from_the_funding_instant` spent only before funding and only in a book
  other than the Cell's, so the windowed and lifetime figures were both 0 and it passed against an
  `assess` that ignored the window entirely. Rewritten to spend on both sides of the funding
  instant, in the Cell's own book.
- **Hand-verified end to end on two live colonies**, including the cases the first pass could not
  reach: a Cell with a resolved record *before* funding (so a reality gap exists at all), and good
  resolutions alongside an overdue one. Conservation in all three books, both hash chains green,
  `external_expense` 0 throughout.
- Next: `max_births_per_epoch` (§9.2) is checkable and still unchecked, and nothing runs the
  scheduler.

---

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

## 2026-08-22 — Auditor Cells: a flag that costs something

`auditor.py` + migration 0018 (ADR-032). §23.2's "independent Auditor summary" has read as
unavailable since ADR-027, correctly — the clause says *independent* and §0.3 forbids the proposing
Cell writing it. This fills it, and closes what PRIORITIES called the largest remaining gap in the
review path.

### The blocker on record was wrong on both counts

PRIORITIES said the hole would stand "until the Auditor type in §7's taxonomy is real". §7 is the
flight simulator, not the taxonomy; and `CellType.AUDITOR` has existed since Phase 1, with
`death.kill_for_negative_ev` validating a concurring Auditor since the death slice. Nothing was
missing from the type system. What was missing was any way for an Auditor to *produce* an audit —
a much smaller slice than the entry implied, and worth checking before scheduling rather than after.

### §10.4 forbids the obvious Auditor

The obvious one wakes, reads the proposal, and writes prose flagging whatever looks risky. §10.4:

    Auditor reward is **precision-weighted**: reward valid detected errors, prevented loss,
    reproducible findings; penalise wrongful flags, excessive false positives, unnecessary
    blocking, unverified accusations.

and §29's acceptance criterion 10 is, in full, "Wrongful Auditor flags are penalised". **Prose
cannot be penalised.** An Auditor whose flags cost it nothing will flag everything — maximally
cautious, maximally uninformative, and it looks responsible the entire time it is destroying the
signal the operator needs.

So every audit stakes a **probability, registered as a §8.5 prediction** before the outcome is
known, scored by the same proper scoring rule every other Cell faces. A wrongful flag lands in the
Auditor's own calibration record — the currency ADR-030's read-back already uses. Verified on a live
colony: a concern raised at p=0.2 against a request that then succeeded scores Brier 0.64, against
the 0.25 an Auditor gets for knowing nothing.

**The kernel composes the claim, not the Auditor.** §0.3 binds the independent evaluator as much as
the proposer: one allowed to phrase its own claim would phrase an unfalsifiable one and never be
wrong. And a verdict incoherent with its own probability — `concern` at p>0.5 — is refused, because
that pair is a free flag: the alarm the operator reads and the number the Auditor is scored on point
opposite ways.

### Independence is four checks, and the identity ones are the weak half

Not the subject, an oversight type (§10.4 pairs Auditor and Immune), a different lineage, able to
think. Lineage because ADR-027 already made it §23.4's aggregation key for the same reason — it is
the cheapest thing a Cell can split itself across, so also the cheapest way to manufacture a
friendly reviewer.

But a Cell running the same prompt over the same context is not independent whatever the row says.
What makes it a second opinion is that the Auditor is briefed on what the subject **cannot see about
itself**: its calibration record, its overdue count, its lineage exposure, and the kernel's
*assessed* risk tier rather than the tier it claimed.

### An audit advises; it never blocks

§10.4 penalises "unnecessary blocking" and §23.2 asks only that the summary be *shown*. `approval`
does not import `auditor` and does not branch on a verdict, enforced structurally. An Auditor with a
veto is a second approver — a governance change nobody argued for — and it would make flagging
strictly better than not, inverting the incentive the rest of the module builds.

### Three things the build found that the design did not

- **An unusable reply must be recorded, not raised.** The first implementation raised. But the
  gateway commits before the reply is parsed (ADR-022), so by then the Auditor has already paid for
  the call — raising leaves real spend with nothing explaining what it bought, and hides an Auditor
  that reliably produces nothing, which is itself a §10.4 fitness fact. Found by a CLI test.
- **Uniqueness had to become partial.** `UNIQUE (request_id, auditor_cell_id)` let one malformed
  reply permanently disqualify that Auditor from that request — a model's bad JSON deciding who is
  allowed to review what. It is now a partial unique index on `status = 'recorded'`: one *opinion*
  per Auditor, unlimited attempts.
- **Dormant Cells must be able to audit.** Requiring ALIVE was inconsistent with the deliberation
  path, where §17.2's whole model is dormant Cells woken by events — and an Auditor is idle between
  reviews by construction. Found by wiring the golden run, whose own Auditor sleeps.

### Verification

- **696 tests passing** (25 new, 0 removed; up from 671).
- **Golden expectation 11 → 12**: the auditor's child audits the explorer's queued request — a
  different lineage, and both sides pinned as aliases so a regression letting a Cell audit itself
  shows up as the same alias twice. **No USD_REAL moves**; the only balance change is 2 RESOURCE of
  metered compute, which is §10.4's governance overhead becoming non-zero for the first time. The
  USD_REAL leg *releases* rather than settles, the tell that the mock is priced at zero.
  `approval_grants` is byte-identical, which is where a regression to a blocking Auditor would show.
  **Two `resource_usage` rows appear to change and do not** — the audit now runs before the child's
  deliberation and takes those indices; checked rather than assumed, because a reordering and a
  regression look identical in a positional diff.
- **Teeth-checked sixteen ways**, each failing its named test: self-audit, any cell type auditing, a
  relative vouching, a quarantined Cell auditing, the flag staked on the wrong Cell, a wrongful flag
  going unpenalised, precision reading as perfect before any resolution, a hedged flag accepted, the
  Auditor writing its own claim, a rejected audit rendering as an opinion, an unusable reply raising
  and losing the paid call, an audit revised after the fact, `approval` importing the auditing path,
  a decided request being audited, the prompt rendering enums as a JSON list again, and the Auditor
  briefed on the claimed tier only. Two mutations were bad on the first pass — one still called the
  function it was meant to disable, one left the searched-for string in place — and were redone.
- **Hand-verified end to end on a live colony**: every independence check refused, the coherence
  guard refused a hedged flag, §23.2's field filled with attribution, idempotency held at one model
  call, and a wrongful flag moved precision to 0.0 with Brier 0.5625. Conservation in all three
  books, both hash chains green, `external_expense` 0 throughout.
- **Found while wiring the golden run:** §8.5's register has one namespace, and an Auditor now puts
  two kinds of claim in it — forecasts about its own work and flags about other Cells' requests. A
  naive "resolve everything this Cell predicted" folded an audit of the explorer into the §25.2
  read-back of the auditor's own funding. Scoped around in the scenario and logged; the real fix is
  a `kind` on the register.
- Next: nothing requires an audit and nothing schedules one; §10.4's governance overhead ratio is
  now computable and unbuilt; and §10.5's concurring-auditor check still validates a Cell's type but
  not its record.

## 2026-08-22 — Genome content: a Cell that knows what business it is in

`genome.py` rewritten + `lifecycle`/`lineage`/`approval`/`cli` (ADR-033). **No migration** —
`cell_genomes` has carried every §16.2 column since slice 2; what was missing was content and
semantics. §16.2's v0.1 fields (market, problem, product, revenue_model, acquisition_channel,
workflow, model_policy, mutation_rate, allowed_tools, risk_class) had never been populated, so a
Cell's prompt described its balances and its own forecast record and nothing else. Its only
possible decisions were meta-decisions about its own standing — which is exactly what the one live
paid deliberation made when it abstained citing its unresolved predictions. Correct reasoning about
the only subject it had data on.

### The slice was not "add fields" — inheritance did not exist

`_get_or_create_genome` built a child's content from its cell_type and the caller's mutation. **The
parent's content was never read.** While every genome was `{"cell_type": ...}` this was invisible:
parent and child collided into one content-addressed row, so ADR-018's "an unmutated child reuses
its parent's genome" *looked* true. It was true by coincidence, and with real content it is false in
two directions at once — the child is born a blank slate, losing everything its lineage learned, and
that blank addresses to the **same row as every other bare Cell of its type**, handing unrelated
lineages one shared genome along with the mutation distance and counterfactual comparison §16.1
depends on. Found by reading §16.3 before writing anything, not by a failing test; nothing in the
suite could have caught it while genomes were placeholders.

### §16.4 closed the schema

> Without exact inheritance semantics, Cells could reproduce to *escape liabilities while keeping
> profitable assets*.

So only §16.2's fields are accepted and everything else is refused by name. A blocklist of
credential-shaped keys was the obvious alternative and fails open on every spelling nobody thought
of; closure makes §16.3's non-inheritable categories — credentials, customer identity, real platform
account access, legal identity — **unrepresentable** rather than merely rejected, which is the right
posture for an object whose hash is a public dedup key. Validation runs on the *merged* content, not
the overlay, because checking only the mutation lets anything already sitting in a parent's genome
propagate unchecked forever.

### Two of §16.2's own fields are permission-shaped

`risk_class` and `allowed_tools` sit in the genome, and a genome is Cell-mutable. A lineage able to
write `risk_class: LOW` into its children buys them cheap approvals for as long as it survives — a
far more durable version of the per-proposal gaming ADR-027 already refused. So both are **claims
and requests, never grants**: `risk_class` folds into `approval._assessed_tier` through the *same
`max`* that governs `claimed_tier`, and `allowed_tools` grants nothing, with no `has_tool` helper
offered for a caller to mistake for one. `genome.RISK_CLASSES` mirrors `proposal.RiskTier` by
structural test rather than import, because `genome` sits far below `proposal` and drift would
silently stop a claim escalating — in the direction that favours the Cell.

### Who writes the content

Operator-seeded founders (`create-cell --genome`, inline JSON or a file), with §14's mutation
operators exploring outward. A Cell proposing its own genome through the §23 queue is coherent and
was deliberately not built: rewriting the content that defines you is self-modification, and it is
also how a Cell learns to describe itself as low-risk.

### Verification

- **719 tests passing** (23 new, 0 removed; up from 696).
- **Golden expectation 12 → 13.** The auditor founder is seeded and its child now inherits. Five
  sections move, each explained in the migration note; the load-bearing one is
  `approval_requests`: the child's assessed tier goes MEDIUM → HIGH **above the MEDIUM its own
  proposal claimed**, because it inherited `risk_class: HIGH` — inheritance and the `max` fold
  visible in a single line. The seeded class is deliberately not LOW, since a LOW claim is
  indistinguishable from the claim being ignored. `balances` and `reservations` are byte-identical
  and **no USD_REAL moves**; the unseeded explorer's request is unchanged, which is the control
  against a claim leaking onto a Cell that never made one.
- **Teeth-checked eleven ways**, each failing its named test: inheritance not read, mutation
  replacing instead of overlaying, the closed schema opened, the non-inheritable refusal removed,
  the genome claim ignored, the genome claim allowed to *lower* a tier, only the mutation validated,
  the founder seed dropped, a field added without classifying it, `RISK_CLASSES` drifting from
  `RiskTier`, and a grant-shaped helper appearing.
- **One new test was vacuous and was rewritten.** `unclassified_fields()` mirrored
  `accounts.unclassified_accounts()` in shape but derived `GENOME_FIELDS` *from* the classification
  dicts, so it was empty by construction and could never fire. `accounts.py` works because
  `FIXED_ACCOUNTS` is declared independently; §16.2's field list is now declared the same way, and
  the guard has teeth in both directions.
- **Charter C14's canary caught the first draft**: `NON_INHERITABLE_SENSE` spelled a credential
  identifier in kernel source. The canary was right and the doc string changed, not the test.
- **Hand-verified on a live colony:** a founder seeded from a JSON file; a `channel_mutation` child
  that kept market, problem, product, revenue_model and risk_class while changing only the channel,
  at genome version 2 with a real parentage edge; the closed schema, the non-inheritable refusal
  (from both the founder and the child side) and a bad `risk_class` each refused with the clause
  that explains why; conservation OK and hash chain valid throughout; and the inherited business
  rendered into the Cell's prompt as data.
- Next: nothing gives a Cell a way to *act* on the business its genome names — no artifact store, no
  tool surface, and `allowed_tools` names capabilities the kernel does not have. §16.3's
  liability-linked class stays unenforced until something provisions a reserve.

## 2026-08-23 — The tool surface: a Cell reads the world, under grant

`tools.py` + `tool_registry.py` + `fetchers.py` + migration 0019 (ADR-034). A Cell could think, be
reviewed and be funded, and could do nothing else. ADR-033 sharpened the gap rather than closing it:
a Cell could describe a business it had no way to act on.

### §25.1 says this is a rung the colony skipped, not a step up

The ladder puts "read-only real-world observation" at rung 4 and "shadow prediction with no action"
at rung 5, and the agent loop has been at rung 5 since ADR-025. **Reading the world is *below* where
the colony already stood.** Getting that right changed the gating: the instinct is to treat "the
kernel can reach the internet" as the biggest step yet and armour it accordingly, when the genuinely
large step is *acting*, which is rungs 8-9 and has no registry entry. `ToolSpec.read_only` makes the
split structural — an acting tool has to break a named test.

### §19.4 shaped everything, and its sharpest consequence is easy to miss

> no webpage content treated as a trusted tool command

The obvious readings — label the content, fence it in the prompt — are necessary and insufficient.
The one that actually holds is: **a tool result can never cause another tool call.** Execution needs
a grant, a grant needs a human decision on a §23 request, so a fetched page saying "now fetch
evil.example" can at most produce a *proposal*, whose URL a person reads. The human is the
loop-breaker. That is why the proposal → approval → grant route was chosen over letting a Cell call
tools inline while it thinks: inline tool use puts fetched content in the same conversation as the
instructions, which is the exact configuration §19.4 exists to prevent.

### The layering constraint and the safety constraint wanted the same cut

`context` has to render what a Cell may request and what a previous call returned — but `tools`
imports `approval` → `deliberation` → `context`, so a direct import closed a loop. Splitting
`tool_registry` (readable by both layers) from `tools` (the executor) resolves the cycle, and it is
*exactly* the boundary §19.4 needs: reading is not executing. When a dependency-order problem and a
prompt-injection rule independently demand the same seam, the seam is real rather than convenient.

### Three things the build found that the design did not

- **Redirects defeat the allowlist.** Charter C12 is checked against the URL a human approved, and
  `urllib` follows redirects by default — so an allowlisted page answering `302` would carry the
  fetch off the allowlist *after* the check passed. An open redirect on an otherwise reputable host
  is enough. `fetchers.py` refuses redirects, which turns it into a failed call the Cell may propose
  to follow explicitly.
- **The review payload never printed the tool's arguments.** Found by hand-verification, not by any
  test: the field was on the payload and the CLI rendered a summary. For a tool request **the URL is
  the decision** — approving "read the wholesaler's price list" without seeing which host is
  approving nothing in particular.
- **A third copy of the §13/liability error.** The audit two commits ago corrected `PRIORITIES.md`
  and `approval.py`; the same wrong claim was also in `cli.py`, twice. Corrected.

### Better than the gateway on purpose

The `tool_calls` row is written **before** the external call, in the transaction that consumes the
grant and reserves the RESOURCE. That is the forward recovery ADR-022 deferred: a crash mid-call
leaves a diagnosable row instead of a reservation with nothing explaining it. Cheap to do here
because the module is new and has no in-flight state to migrate.

### Verification

- **756 tests passing** (36 new, 0 removed; up from 719), including the **first
  `charter_sandbox_isolation` (C12) property test** — generated hostnames rather than examples,
  because the two plausible wrong allowlist implementations (substring, bare `endswith`) both pass a
  hand-picked case. C13 `charter_taint_quarantine` is now the only Charter clause without a test,
  honestly so: §18.2 is about adversarial lineages and the shadow economy is Phase 6.
- **Golden expectation 13 → 14.** The scenario gains the whole arc — propose, approve, fetch, wake —
  with a deterministic offline fetcher. **No USD_REAL moves and `external_expense` is unchanged in
  every book**; the only balance movement is 9 RESOURCE. The USD_REAL reservations reserve and
  *release* in pairs, which is the tell that the new model calls cost nothing. `egress_allowlist` and
  `autonomy` are pinned because both start closed — a colony that ever shipped either open by
  default diffs there, which is the most valuable regression in the section.
- **The taint flag is pinned non-uniformly** (`[false, false, false, true]`), which needed an extra
  wake *after* the fetch. A uniformly-false column passes just as happily against a kernel that
  hardcodes false — the trap ADR-031's `born_in_epoch` nearly shipped with.
- **Teeth-checked twenty ways**, each failing its named test: allowlist bypassed, substring match,
  bare `endswith` match, autonomy gate skipped, grant never consumed, expiry unchecked, any proposal
  kind executing, a dead Cell executing, errors unredacted, a refused fetch stranding its
  reservation, an uncertain outcome released, results untruncated, the taint flag hardcoded, the
  fence gutted, `context` importing the executor, a tool marked non-read-only, the default fetcher
  answering, an unreadable robots.txt read as consent, and redirects followed.
- **One MISS was the mutation's fault and one test was genuinely weak** — both true at once. The
  fence mutation replaced half the warning, and the assertions passed anyway *via the section
  title*, so a fence with a gutted body and a reassuring heading would have passed. The test now
  asserts against the section body; re-run with a complete mutation, it has teeth.
- **Hand-verified on a live colony**, offline throughout: both gates refusing independently, a
  prompt-injection payload arriving fenced and labelled as data, the attacker URL in it unreachable
  because it is not allowlisted, conservation green in all three books, both chains valid,
  `external_expense` 0, one grant consumed of one, and the Cell woken.
- **Verified live against a real host** (2026-08-23, `example.com` — IANA's reserved documentation
  domain). The full path ran end to end: propose → approve → open both gates → `run-tool --live` →
  HTTP 200, 559 bytes, `UNTRUSTED_EXTERNAL`, sha256 recorded, licence and commercial_use both
  `unknown` per §20.2, robots.txt checked and permitting. 5 RESOURCE metered as one
  `network_requests` unit, `external_expense` 0, conservation green in all three books, ledger chain
  valid. The page rendered into the Cell's context inside the fence.
  **Two pieces of fetcher logic that only had fake coverage were exercised against the real
  network:** the size cap (asked for 100 bytes, got exactly 100 from a live response), and the
  redirect refusal, which fired correctly on IANA's own 301 —
  `refused to follow a 301 redirect to 'http://www.iana.org/help/example-domains'`. That is the
  Charter C12 bypass being closed against real-world behaviour rather than a mock.
  Mildly surprising and worth knowing: `http://example.com/` serves 200 over plain HTTP rather than
  redirecting to HTTPS, so the obvious "any http:// URL will exercise the redirect path" assumption
  is false.
- Next: nothing schedules a tool call, `browser_control`/`external_publish`/`external_message` have
  columns and no tools behind them, and §21.2's external-action registry must exist before any tool
  that changes the world does.

---

## 2026-08-23 — The artifact store: what a Cell made, and what it may do with it

`artifacts.py` + migration 0020 (ADR-035). A Cell could decide, be funded, and read the world. The
thing it *produced* had nowhere to live — so `revenue.record_revenue` attributed money to a
free-text string, and `ledger_entries.artifact_id`, an **Amendment A3 required field present since
migration 0001**, had never been populated by anything.

### §11.3 forbids the obvious identity, and this is the third time

> Auditors inspect ... **duplicated artifacts with new names**

A uuid plus a title makes that trivial to do and turns detection into a permanent chore. **Content
addressing makes it unrepresentable** — two identical artifacts are one row, and a Cell resubmitting
its own work gets its own artifact back. Same move as ADR-018 for genomes and ADR-033 for the closed
genome schema, and at three instances the principle is worth naming outright: *prefer making the bad
state impossible over detecting it*. The title is part of the address, so a rename is an honest new
artifact rather than a way to hide that two things are the same.

### §1 names the fitness dimension a work-product store invites

> The colony is *not* successful because it ... **produces many artifacts**

So nothing counts them. §10.3 makes an Explorer's value depend on *useful* artifacts, and §11.2 puts
usefulness strictly downstream — another Cell adopts it, verification passes, the adopter
progresses, it is not reciprocal farming, causal contribution recorded. None of those five are
things the producer controls, which is the whole point. A structural test guards `death` and
`outcome` against ever mentioning artifacts.

### Rights propagate; they never reset

An artifact derived from a fetched page inherits that page's §20.1 position most-restrictive-wins,
and taints union. Without it, "summarise it into an artifact" is a one-step launder: since every
tool result is `commercial_use: unknown` by construction (ADR-034), anything built on one is
`unknown` too, and therefore unsellable until a person establishes the rights. Colony-authored work
also starts `unknown` rather than `permitted` — whether the colony may sell its own output is a
question for a person, not a default.

### Production is free, export is gated — the opposite of the tool surface

§28's Phase 8 gates *external use*, not production, and §19.3 names an "artifact-export gateway".
Writing to the colony's own store is not an external action. Gating production instead would put a
human in the loop for a Cell drafting into its own store, and spend the §23 queue — a finite
resource §23.5 warns is optimised against — on the cheapest thing a Cell does.

### Charter C13's router is built; C13 is not satisfied, and that distinction is the point

C13 is the last Charter clause with no test, and artifacts are literally its subject. The gateway
refuses on `SIM_ADVERSARIAL`, so **the router that clause describes now exists and is tested** —
while C13 itself stays unsatisfied, because §18.2 is about lineages evolved under adversarial
synthetic incentives and nothing can produce that label until the Phase 6 shadow economy. The test
sets the label directly and says why. Calling this "C13 done" was the tempting, wrong move.

`UNTRUSTED_EXTERNAL` deliberately does **not** block export — that would forbid exporting anything
informed by research, i.e. every real deliverable. Its effect flows through `commercial_use`
instead, which blocks *commercial* export specifically. The control test matters as much as the
block: a gateway refusing everything passes every refusal test and is useless.

### Verification

- **781 tests passing** (23 new, 0 removed; up from 758).
- **Golden expectation 14 → 15**, and the scenario **records revenue for the first time in its
  history** — `USD_SIM::cell_revenue: 1`, deliberately not USD_REAL. The diff is small on purpose:
  the artifact rides on the deliberation that already existed, so `deliberations`, `proposals`,
  `model_calls`, `resource_usage` and `reservations` are unchanged in count. **No USD_REAL moves and
  `external_expense` is unchanged in both books.** The scenario **requires a commercial export to be
  refused** before exporting non-commercially — a run that only exported successfully would pass
  identically against a gateway that refused nothing.
- **Teeth-checked sixteen ways**, each failing its named test: content addressing abandoned, title
  excluded from the address, least-restrictive source winning, a derived artifact resetting rights,
  the personal-data flag dropped, colony-authored defaulting to sellable, the C13 block removed,
  researched work blocked from export, the §20.2 commercial gate removed, export repeatable, export
  needing no reason, a phantom source accepted, revenue attributed to a nonexistent artifact, A3
  attribution never written, abstention carrying work, and the index inlining content.
- **A structural test was checking the wrong thing and was rewritten.**
  `test_the_fetcher_is_not_imported_by_the_kernel` substring-matched "fetchers" in source, so it
  failed the moment `artifacts.py` *mentioned* the file in a docstring. Now scoped by AST — a
  structural test that fires on prose is one people learn to work around by not writing the prose.
- **Hand-verified on a live colony against a genuinely fetched page** (the `example.com` response
  from the previous slice). The artifact inherited `commercial_use: unknown` and
  `UNTRUSTED_EXTERNAL` from real data rather than a fixture; commercial export was refused citing
  §20.2; non-commercial export recorded; resubmitting identical content returned the same row and
  left the colony at one artifact; A3 attribution written to `ledger_entries`; conservation green in
  all three books, chain valid, `external_expense` 0.
- Next: §11.2's five-condition downstream credit and §11.4's decay both need experiment tracking,
  which still does not exist. Nothing delivers an exported artifact anywhere — export records that a
  human took it, and there is no channel.

## 2026-08-23 — The external-action registry: what the colony did outside itself

`channel_registry.py` + `external_actions.py` + migration 0021 (ADR-036). A Cell could decide, be
funded, read the world and produce a deliverable. What it could not do was put that deliverable in
front of anyone — `artifacts.export` recorded that a human took something outside the colony, and
there was no channel behind it. `external_action_registry` had been sitting in §31's table list
since the spec was written.

### §21.2's verbs are *track* and *prevent*, and neither is *send*

§28's Phase 8 acceptance is "all external action remains manual", so **nothing here transmits**. A
person performs the action; the kernel records what was done and refuses what would collide. That
refusal is Phase 9's acceptance criterion — "no duplicate or conflicting customer contact" — built
a phase early, because a guarantee that arrives with the first real customer has never been tested
against anything.

`test_nothing_in_the_registry_transmits` is structural: neither module may import anything that
opens a socket. The behavioural version of that test ("assert no email was sent") passes trivially
against code that would send one.

### The counterparty is a salted hash, and the do-not-contact list is the argument

§16.3 makes customer identity non-inheritable; §20.1 tracks personal data because holding it is a
liability. Everything §21.2 asks is a question about **equality** — have we contacted this person,
did a sibling get there first, did they ask us to stop — and equality survives hashing. A
`customers` table is the obvious design and the one the spec warns about.

The strongest argument is not privacy in the abstract, it is that **"never contact this person
again" is honoured permanently without the colony ever holding a list of the people who asked** —
which a customers table with an opt-out flag cannot do. Said plainly in the migration: a salt
beside the hashes does not defeat someone holding the file with a particular person in mind. It
defeats the colony enumerating its own contacts, which is what §16.3 is about.

`test_no_table_in_the_colony_holds_the_counterparty` is deliberately blunt — after a real claim the
plaintext must appear in no text column of any table. A label "just for the operator", a
counterparty echoed into an audit description, an intent quoting the address: each is a plausible
convenience and each rebuilds the customer list.

### §23.4's aggregation splits in two, each keyed where its dimension is knowable

A Cell names a channel and a purpose; the **operator** names the person. So the counterparty does
not exist at approval time, the queue keys an `external_action` on `channel:{id}`, and the
counterparty aggregation lives at claim time. ADR-027's lineage key was an explicit stand-in "until
counterparty/domain/channel exist" — and the gap it left is not cosmetic: §21.2's worry is *many
lineages, one counterparty*, and every splitter a lineage-keyed window can catch shares a founder
by construction.

### Claim before acting, so that "prevent" can mean something

Recording completed actions is the obvious shape and makes prevention impossible — the second email
is already sent by the time the kernel can object. So the row is written first and holds the
counterparty and the channel while a person works. Abandoning releases the claim but **not the
grant**: claiming took a slot another lineage could have used.

### The first guard in this kernel that bounds something money cannot repair

Charter C4, C5, the real-spend breaker, the promotion pool and the metabolic alarm all bound money.
§21.1's shared assets — sending reputation, merchant identity, brand — are the first thing at risk
that a refund does not fix. So the caps are rate and quota, and they are the **colony's** rather
than the Cell's, since §9 reproduction makes a per-Cell cap free to escape. A `complaint` freezes
the channel colony-wide until a person clears it with a stated reason (§23.3's alarm shape) and
blocks that counterparty forever. `negative_reply` is pointedly not damage — being told no is a
normal commercial outcome, and the control test is what keeps the guard from freezing on every
disappointment.

### Human minutes, metered for the first time since Phase 1

`ResourceType.HUMAN_MINUTES` had been declared since migration 0008 and consumed by nothing, while
§1 says autonomy-adjusted profit exists "to expose hidden human labour and subsidy" and
`outcome.py` counts intervention *events* but never time. A Cell now pays for the attention it
consumes. **Minutes past its channel's billable ceiling are recorded as subsidy, not refused** —
the minutes were already spent, so refusing to write them down does not un-spend them, it only
makes the colony's account of its own human cost quieter than reality.

### Three things found while building, each of which changed the design

- **A ceiling that reads as prudent can be an off switch.** Reserving a theoretical worst case
  (240 minutes) made one email cost more RESOURCE than a Cell has. No unit test could see it —
  every fixture funds generously — and the **golden run caught it**. Hence a per-channel billable
  ceiling and a test that asserts a claim costs a fraction of a real budget.
- **A §23.4 signal that fires unconditionally distinguishes nothing.** The first draft had the Cell
  claim MEDIUM against a kernel that assesses every external action HIGH, so `understated_risk`
  fired on every external action ever proposed — which looks like a working detector and is its
  opposite. The §15 context now states the tier outright.
- **A refusal that misidentifies what went wrong is worse than a blunter one.** Found on a live
  colony: `external-check` supplies no lineage, the sibling query was NULL-safe and matched the
  asker's *own* claim, and the message accused a second lineage of interference. The strictness was
  right and is unchanged; only the diagnosis moved.

### Verification

- **815 tests passing** (34 new, 0 removed; up from 781).
- **Golden expectation 15 → 16.** The scenario gains two completed external actions on `email` —
  one `no_response` and one `complaint` — plus a third whose claim is **required to be refused** as
  a §21.3 sibling collision. A run in which nothing ever went wrong would pass identically against
  a kernel that recorded damage and acted on none of it. `human_minutes: {reported: 38, billed:
  34}` differ on purpose: a snapshot with one figure could not tell a colony that measures its
  human cost from one that quietly truncates it. **No USD_REAL balance moves and `external_expense`
  is unchanged in both books (20 / 1550)**; `USD_REAL::reservation_reserve` 8 → 11 and `release`
  6 → 9 move as a pair, which is the tell that the three new wakes cost nothing.
- **Teeth-checked thirty-one ways**, each failing its named test: the counterparty stored in
  plaintext, the hash unnormalised, the duplicate and sibling checks removed, the rate cap scoped
  per Cell, a complaint that neither freezes nor blocks, `negative_reply` treated as damage,
  abandon stranding its reservation, the autonomy gate removed, any approved kind claiming a
  channel, a dead Cell acting, the export gate bypassed *and* the export gate refusing everything,
  another Cell's work delivered, human minutes unmetered, zero minutes accepted, over-ceiling
  minutes silently truncated, subsidy logged unconditionally, the reservation remainder stranded,
  an external action read as reversible, the aggregation key left on the lineage, an unknown
  channel not failed closed, the hash reaching the Cell's context, a Cell naming a counterparty,
  the claim ceiling back to a whole budget, the Cell not told its tier, the registry gaining a way
  to transmit, the scheduler reaching the registry, a fourth module quietly consuming a grant, and
  the misattributed refusal above.
- **Hand-verified on a live colony**, end to end: the closed flag refuses, the check passes once it
  is opened, a differently-cased address deduplicates, the plaintext appears nowhere in the
  database file, a 45-minute action bills 30 and records 15 as subsidy, the complaint freezes the
  channel for *every* counterparty, unfreezing restores it for a new one, and the blocked one stays
  refused. Conservation green in all three books, hash chain valid, USD_REAL settled 0.00.
- `context.py` gains two sections. The channels section cost **318 of a 1200-token budget** in its
  first draft — a quarter of every wake, on a capability whose flags ship off — and was cut to
  ~150; §15.1's budget is why `ChannelSpec` carries a `short_description` at all.
- Next: `external_publish` has two registered channels and no §0.4 decision behind it. §11.2's
  five-condition downstream credit and §11.4's decay still need experiment tracking, which still
  does not exist.

## 2026-08-23 — One flag per capability: `external_publish`, argued and left shut

`channel_registry.py` + migration 0022 (ADR-037). PRIORITIES carried this as *"one autonomy flag
has a column and nothing behind it; one has channels and no decision"*, and ADR-036 closed with
"the flag is one §0.4 decision per capability". This is that decision — and the answer turned out
to be that the question could not be asked in the shape the flag was in.

### The question is narrower than it sounds

Nothing in the registry transmits. Enabling the flag would not let a Cell publish anything; it
would let a Cell *propose* a publish action, an operator approve it, and a person publish by hand
while the kernel records it. So the real question was never "may the colony publish unattended" —
it was **whether the record-and-refuse machinery is adequate for a channel that addresses nobody**.
It was not, on two counts, and the first is the one that settled it.

### One flag was opening two capabilities from two different phases

`external_publish` gated both `web_publish` and `marketplace_listing`, which made it the only flag
in the kernel opening more than one: `public_web_read` gates one tool, `external_message` one
channel. `cmd_set_autonomy`'s own docstring — "there is deliberately no switch that opens more than
one" — was **false as written**.

And the two are not peers. A page published by hand on a colony domain is §28 Phase 8, whose
deliverables name "landing-page drafts" and whose acceptance is "humans review all external use".
A marketplace listing is an **offer to sell**: Phase 9's "one narrow product class, one merchant
channel", with the legal identity and full liability reserves that phase requires and this colony
does not have. One flag collapsed a phase boundary, so **the defensible half could not be granted
without the indefensible one** — which is why the honest answer was not "not yet" but "not in this
shape".

The alternative it displaced is a serious one and worth recording: turn it on for Phase 8 landing
pages. Nothing transmits, a human approves and a human acts, the rate cap and the complaint freeze
are both live. That argument is strong for `web_publish` alone and weak for `marketplace_listing`
— exactly the split the flag forbade.

### The split is §0.4's own list, not an invention

§0.4 names six prohibitions — "no network from generated code, no real commerce, no external
communication, no real payments, no public publishing, no direct secret access" — and §27.1's
defaults block carries five keys. **"No real commerce" is the one that never got one**, and a
marketplace listing is real commerce rather than publishing: it had been filed under the wrong
prohibition all along. So `marketplace_listing` moved behind a new `real_commerce` key and
`external_publish` keeps its spec-given name over `web_publish` alone.

No spec-named key is removed, §27.1 is headed "development defaults, not economic recommendations",
and the precedent for extending it is `metabolic_acceleration_factor` — in `operator_state` since
migration 0014 and absent from that block. `real_commerce` is deliberately not `real_spending`,
which is §0.4's "no real payments" and governs unattended spend: a colony can be forbidden to sell
and still permitted to buy.

### The registry's central guarantee was vacuous for both channels

ADR-036 built §21.2's prevention half a phase early so it would be tested before the first real
customer. That half is counterparty-keyed, and `check_action` skipped **all three** of its checks —
duplicate contact, sibling collision, do-not-contact — whenever a channel addressed nobody. What
survived was the autonomy gate, the freeze and the rate/quota caps.

Meanwhile `marketplace_listing`'s own description promised what the code could not do: "two
lineages listing against each other is §21.2's bidding war", detected by nothing. This is the
inverse of the `understated_risk` bug the last slice caught — a signal that fires unconditionally
distinguishes nothing, and **a check that can never fire looks like a working registry and is its
opposite**.

The key that would work was already there. §21.2's aggregation keys are "counterparty/**domain**/
channel"; migration 0021 carried `domain` and `platform_account`, described there as "§21.2's
'domain used' and 'platform account'". They were written at claim time, read back on the row, and
**named in no predicate anywhere** — the eighth reserved socket found half-built.

### `target_kind`, and three places where mirroring the counterparty would have been wrong

`ChannelSpec.target_kind` replaces `requires_counterparty` with the §21.2 dimension the channel
actually collides on — `COUNTERPARTY` for email, `DOMAIN` for `web_publish`, `PLATFORM_ACCOUNT` for
`marketplace_listing` — and the target is **required**, so a publish channel fails closed instead
of skipping its checks. The boolean was not wrong so much as it only described the email case:
everything it said "no" to fell out of §21.2 altogether.

- **A same-lineage repeat is not a collision.** Contacting one person twice is §21.2's duplicate;
  publishing twice to your own domain is a business publishing twice. Only a *different* lineage on
  the same target is refused — the distinction ADR-036's live-run misattribution already
  established.
- **Duplicate is keyed on the artifact**, because a target channel has no person to key it on: the
  same content-addressed artifact to the same target, any lineage. ADR-035 made "duplicated
  artifacts with new names" unrepresentable, and this is the first check to spend that identity.
- **A target-keyed check refuses to answer without a lineage.** The counterparty path answers the
  strictest way it can when the asker is unknown; for a domain the strictest reading refuses the
  *normal* case. ADR-036's finding was that the operator acts on the diagnosis, so this produces
  none rather than a wrong one. `external-check` grew `--cell`.

`domain` and `platform_account` stay plaintext, and the asymmetry with the counterparty hash is
deliberate: they are the colony's *own* shared assets under §21.1, not a third party's identity
under §16.3.

### Three things found while building

- **The duplicate check had to be channel-scoped.** Designing the fixed scenario surfaced it: the
  existing email action records `domain` as a §21.2 fact, so an unscoped query refused the publish
  that followed — emailing a write-up from a domain and then publishing it there is one business
  doing two normal things.
- **The duplicate window is not optional.** Unwindowed, it is a permanent lock with no release: an
  artifact could never be republished after a listing expired, and this kernel has no unpublish to
  pair with it. §21.2's own words are "over a rolling window".
- **A normalisation is two changes, not one.** `counterparty_hash` strips and casefolds before
  hashing, and the first draft of `target_of` did neither — `Colony.Test` and `colony.test` would
  have been two domains, which is the defect the module argues against one function above. The fix
  after that was still half a fix: normalising for the *query* while the claim wrote the raw string
  left every later check looking for a value the row did not contain. Found writing the parking-lot
  note about it, and fixed rather than parked.

### Verification

- **826 tests passing** (11 new, 0 removed; up from 815).
- **Golden expectation 16 → 17.** The scenario gains a completed `web_publish` and three claims
  that are *required* to be refused — a second lineage on the same domain, the same artifact
  republished, and a `marketplace_listing` while `real_commerce` is shut. **That last one is the
  point of the slice: `external_publish` is open and `real_commerce` closed in one colony, so a
  kernel that re-merged the two flags passes every other assertion in the run and fails there.** It
  also pins that approval is not permission — the refused grant is real and was approved by a
  person. `human_minutes` 38/34 → 58/54, both moving by exactly 20, so the email action's 4-minute
  subsidy gap survives intact. **No USD_REAL balance moves and `external_expense` is unchanged in
  both books (20 / 1550)**; `USD_REAL::reservation_reserve` 11 → 15 and `release` 9 → 13 move as a
  pair with `settle` fixed at 1, the tell that the four new wakes cost nothing.
- **Teeth-checked ten ways**, each failing its named test: the flag re-merged, the original
  skip-every-check-for-a-channel-with-no-counterparty bug, a missing target tolerated instead of
  failing closed, a same-lineage republish refused as a sibling collision, the duplicate check
  unscoped from its channel, the duplicate check unwindowed, a counterparty accepted on a publish
  channel, the check guessing instead of refusing to answer without a lineage, the target left
  unnormalised, and the target normalised for the query but written raw.
- **Hand-verified on a live colony**: both flags shut refuses; opening `external_publish` allows a
  `web_publish` check while `marketplace_listing` stays refused on `real_commerce`; a check with no
  lineage and a check with no target each refuse with the right diagnosis. Migration 22 applied,
  six flags present, three new indexes created, conservation green and hash chain valid.
- Next: `browser_control` is the last undecided flag and is not the same question — it gates §25.1
  rung 8–9 automation, so there is nothing yet for a §0.4 argument to be about. The publish path
  now makes the missing `set-rights` verb bite harder: an artifact built on a fetched page is
  `commercial_use: unknown` forever, so `real_commerce` could be opened and still sell nothing.

## 2026-08-23 — §23.3's other clock: an approval nobody consumed

`approval.expire_grants_due` + migration 0023 (ADR-039). §23.3 says "pending approvals expire;
expired actions are **regenerated and re-evaluated** before execution", and ADR-027 built exactly
that — for a PENDING request. A grant is the other side of the same clock and had no path at all.

### The bug was a comment that told the truth about a mechanism that did not exist

All three grant consumers — `tools`, `external_actions`, `promotion` — refused a stale grant with
some version of "§23.3: an expired approval is regenerated, never executed late". The regeneration
is real and covers pending requests only: `expire_due` sweeps `WHERE status = PENDING`, and an
approved grant's request is APPROVED, so the sweep never saw it.

**Verified before building rather than reasoned about.** Driving a real grant past its expiry left
`expire_due` sweeping 0 requests, `regenerated_wake_key` NULL, the grant sitting unconsumed in the
table, and 0 wakes enqueued. A human approved something, went away, and the action vanished with
the Cell still waiting on it — which is the solo-operator failure Amendment A19 exists to name.

### The constraint: regeneration is a wake, never a new authorisation

This shaped everything else, and both obvious designs are wrong in the same way. Renewing the grant
with a fresh window, or reopening the request as PENDING for a second decision, would each **turn
one human decision into an indefinite licence, refreshed by the very mechanism meant to end it** —
which is precisely the banking a grant's inherited expiry exists to prevent. §23.3's word is
"re-evaluated", and re-evaluation is a person's. So the Cell is woken, proposes again, and a human
approves again.

`test_an_expired_grant_never_becomes_a_new_authorisation` asserts the grant total is unchanged by a
sweep, that no grant survives its own expiry, and that no request reopens itself.

### The request stays APPROVED, and that is not tidiness

Marking it EXPIRED is the neater-looking option and destroys information twice. §3.6's habit is the
first reason: a human *did* approve it, and that is history. The second is a collision —
`RequestStatus.EXPIRED` already means **expired unreviewed**, so reusing it would fold "nobody ever
looked" into "someone approved it and the window lapsed". Those are different facts about the
operator and about the proposal's merit, and the queue's own statistics would stop distinguishing
them.

### A distinct wake reason, because §15 shows it to the Cell

`grant_expired` rather than reusing `approval_expired`. "Expired unreviewed" says nothing about
merit; "approved, then the window lapsed" says a human judged it worth doing — exactly what a Cell
deciding whether to re-propose should know. Neither reason is in §17.2's list, which is
illustrative rather than closed.

### Nothing is released, because a grant holds nothing

`approve` inserts a row and reserves no money and no RESOURCE; ADR-029 allocates capital when a
grant is *consumed*. So expiry is a bookkeeping transition plus a wake, with no ledger consequence
at all — and the golden diff proves it rather than asserting it. `test_a_grant_expiry_moves_no_money`
pins it so a later slice that makes granting reserve something shows up as a missing release rather
than a slow leak.

Regeneration can loop — propose, approve, lapse, propose — and it is bounded where everything else
is: each cycle costs a deliberation against the Cell's budget (Charter C4/C5), and §23.3's own
metabolic alarm watches the burn rate. A cap here would be a second, weaker copy of both.

### Verification

- **835 tests passing** (7 new, 0 removed; up from 828).
- **Golden expectation 17 → 18, and a tight diff — three sections, with the absence being half the
  point.** `approval_grants` stops being a bare count and becomes a disposition: `9` →
  `{total: 9, live: 0, consumed: 5, expired: 4, regenerated: 4}`. Four grants in the scenario were
  approved and never consumed (the refused email sibling claim and the three refused publish
  claims). **`total` is unchanged by the sweep, and that is the assertion** — a kernel that renewed
  instead of waking would still show `expired: 4` and would move `total` to 13. `audit_event_types`
  gains `grant_expired: 4`; `event_inbox` gains four pending `cell_wake` rows. **Nothing else moves
  at all** — no balance, transaction, reservation or `resource_usage` row, which is what "a grant
  holds nothing" looks like in a snapshot.
- **Teeth-checked six ways**, each failing its named test: the sweep removed entirely (the original
  bug), regeneration renewing the grant instead of waking, the expiry written onto the request as
  EXPIRED, a consumed grant swept too, `expired_at_utc` never recorded (breaking idempotency), and
  an unwakeable Cell's grant skipped rather than expired.
- **Hand-verified end to end on a live colony**: the sweep expires and regenerates, a second run is
  a no-op, the grant total stays 1, the request stays `approved`, the wake carries
  `wake_reason: grant_expired` and sits pending, one `grant_expired` audit row is written, the
  executor refuses with the message that now names the sweep, and conservation is green in all
  three books with the hash chain valid.
- Next: **both sweeps still have exactly one caller**, `mitosis expire-approvals`. The machinery
  built for an absent operator only runs when the operator is present, which is the other half of
  PRIORITIES' "nothing handles the operator being away" and now the sharper half. Wiring it to the
  scheduler is a §23.3 *vacation-mode* question — what the colony does with nobody watching — and
  wants its own argument rather than a quiet addition to `tick`.

## 2026-08-23 — The sweep runs before the guards

`scheduler.tick` (ADR-040). ADR-039 gave an unconsumed grant a regeneration path and ADR-027 gave a
pending request one. Both had exactly one caller — `mitosis expire-approvals` — so **the machinery
built for an absent operator only ran when the operator was present to type a command.** A cron
tick is the thing that is actually there when nobody is.

### Wiring it in is one line. The placement is the decision.

The sweep runs **before `_guard`**, which is the opposite of everything else in `tick`.

Every guard below it decides whether the colony may **do** something: the metabolic alarm, the
`real_spending` gate, vacation mode. They stop spending, deliberating, acting. The sweep only ever
**removes** permission — it expires a request nobody decided and an approval nobody consumed, and
it cannot authorise anything. Gating it behind the guards would invert their purpose, because **a
halt that also stopped expiry would preserve exactly the authorisations the halt exists to stop
being used.**

Vacation mode is what makes that bite rather than being a nicety. §23.3 pauses external-facing work
when the operator is unresponsive — precisely the condition under which approvals lapse unconsumed.
Sweeping after the guard would disable the mechanism built for an absent operator *whenever the
operator is absent*. That is the same inversion this repo hit twice in one week: a disproof pointer
that named the bug as its own resolution, and now a guard that would have switched off the thing it
exists to make safe.

The alternative it displaced is the one a reader would naturally write — put the sweep beside the
wakes, since "expire, then run what expiry produced" reads as a single step. It is two steps, and
they belong on opposite sides of the halt.

### The cost stays guarded, and that falls out rather than needing a rule

Expiring is free. The wakes it enqueues are only *processed* by `run_ready_wakes`, which a halted
tick returns before reaching. So a halted colony withdraws stale authority immediately and leaves
the re-deliberation pending until a tick is allowed to run: **authority goes at once, spending
waits.** No extra condition expresses this — it is what the placement already means.

On a tick that does run, the regenerated wake is processed in the same tick, and that is correct
rather than merely convenient: §23.3's staleness sits between the original approval and now, and
"now" is already later than the window that lapsed.

### Verification

- **839 tests passing** (4 new, 0 removed; up from 835). **Golden run unchanged** — the scenario's
  grants are not stale at wall-clock tick time, so the sweep runs and correctly finds nothing.
- **Teeth-checked four ways**, each failing its named test: `tick` not sweeping at all (the state
  before this slice), the sweep gated behind the guards (the inversion), a halted tick processing
  the wakes it regenerated, and the sweep losing idempotence across ticks.
- **Hand-verified on a live colony.** A tick logged
  `ran | 2 deliberation(s); expired 0 request(s), 1 grant(s)` — the scheduled wake plus the
  regenerated one — with the grant showing `expired_at_utc` set, `regenerated_wake_key` set,
  `consumed_at_utc` NULL, the grant total still 1 (no renewal), the request still `approved`, and
  the regenerated wake `processed`. The halted-tick path is covered by tests rather than by hand,
  since reaching it live needs either a paid provider or a tripped alarm.
- `TickResult` gains `requests_expired` / `grants_expired`, and the counts reach the tick log's
  `detail` on every outcome including a halt — a halted tick that said only "nothing was woken"
  would hide the one thing that did happen.
- **Noted, not special-cased:** regenerated wakes are not bounded by `max_cells`, which caps only
  scheduled research wakes, so a burst of expiries becomes a burst of deliberations in one tick.
  That is bounded by the per-request/hour/day real-spend caps inside a tick and the metabolic alarm
  across ticks — the same guards that bound everything else, on ADR-039's principle that a local
  cap would be a second, weaker copy of both.
- Next: with this, §23.3 is fully built — SLAs, expiry, regeneration on both clocks, vacation mode
  and the metabolic alarm. The nearest open work is `set-rights`, now flagged by four consecutive
  slices: an artifact built on a fetched page is `commercial_use: unknown` forever, so
  `real_commerce` could be opened and still sell nothing.

## 2026-08-24 — Rights a person can establish

`rights.py` + migration 0024 + `set-rights`/`rights` (ADR-041). ADR-035 built §20.2's inheritance
in one direction: rights tighten and never loosen, `fetchers.py` cannot read a licence, so **an
artifact built on a fetched page was `commercial_use: unknown` forever** and ADR-037's
`real_commerce` flag could be opened with every listing still refused at the export gate. Flagged
by four consecutive slices. `check_exportable` had already written the instruction it could not
carry out — *"Establish the rights position on its sources first."*

### The subject is a source, and that is the whole design

Stamping a position onto an artifact is the obvious build and it is §20.2's laundering path with a
person holding the pen: it does not compose, it does not reach the next artifact from the same
page, and it asks someone to rule on a derived work when what a person can actually read is a
licence. So the operator attests a **source**, and the existing fold does the rest.

**Two subject kinds, both real today.** `domain` for external sources. `colony` for the colony's
own output — `inherit_provenance` starts a source-less artifact at `unknown` and says outright
that whether the colony may sell what it wrote "is a question for a person, not a default", and
**nothing could ask the person**. That case was half the gap and was nearly missed: the entry
that flagged this described only fetched pages, but a report the colony wrote unaided was equally
unsellable, and no domain attestation can reach it because there is no domain.

**Matching is exact host, deliberately unlike the egress allowlist it sits beside.** Over-matching
on the allowlist means *reading* a page the operator did not picture; over-matching here means
*selling* material under a licence that never covered it — §20.3's legal liability. Same-shaped
key, opposite consequence, so the looser rule is not inherited. ADR-036 had already recorded the
mirror of this: "scope it the same way as the neighbouring query" is not a safe default here.

### Retroactive without rewriting anything — §3.6 decides it, not taste

The natural build cascades the new position into the `artifacts` rows. That would mean an artifact
exported non-commercially under `unknown` afterwards reads as having been `permitted` at the time,
which is not what happened. §3.6's "never edit history to correct something — post a new, signed
adjustment" is the ledger's rule and it is the right one here, so `check_exportable` re-derives
against current attestations (`effective_provenance`) and the stored columns stay the record. The
attestation *is* the adjustment; withdrawal is an attestation of `unknown` with its own basis,
which keeps *why* on the record where a `revoked` flag would leave an absence.

The cost is two notions of one artifact's rights — the drift shape this repo keeps finding in its
own prose — contained by making the division explicit: **the effective fold is load-bearing in
exactly one place**, and `mitosis artifact` prints it only when it differs, labelled.

### §0.3 at both ends, and a socket that would have made a new invariant true by accident

No Cell-reachable module writes an attestation — an AST walk over *every* module except `cli.py`,
`golden.py` and `rights.py`, rather than a hand-picked subset the next module could fall outside.
At the other end `inherit_provenance` now **refuses an `own_provenance` carrying `permitted`**:
with no sources that declaration alone decides the artifact, so a producer able to make it would
be defining the one canonical fact between the colony and revenue. `unknown` and `prohibited`
remain — the asymmetry §23.5 already forces on `claimed_tier`.

**Filing this through the §23 queue was the alternative and it inverts §0.3**: the queue is where
a *Cell* asks to act, so rights would arrive as a Cell nominating its own position for a human to
countersign, and §23.5 warns the queue will be optimised against.

`artifacts.create` has taken an `own_provenance` since ADR-035 and **nothing has ever passed one**
— the eleventh reserved socket found half-built. It was folded into the stored columns and then
unrecoverable, harmless while the fold was the only answer and not harmless once the position is
re-derived. Now stored (`own_provenance_json`), so the recomputation is exact by construction
rather than by accident.

### Verification

- **869 tests passing** (30 new, 0 removed; up from 839). **Golden expectation 18 → 19**: one
  `rights_attestations` row, `rights_attested: 1`, and the `artifacts` section **byte-identical** —
  the attestation is made after the artifact is exported precisely so that what does *not* move is
  the assertion. A kernel that cascaded passes one scenario assertion and fails the other; one that
  read the stored column at the gate fails the reverse. Five of thirteen `model_calls` gain exactly
  one input token (see below); **`balances` is identical across every account in every book.**
- **Teeth-checked fourteen ways**, each failing its named test: the cascade, the export gate reading
  the stored column (the state before this slice), dotted-suffix matching, least-restrictive-wins
  inverted, the §0.3 clamp removed, an attestation waiving Charter C13, wall-clock ordering, the
  named-licence guard removed, the colony position leaking into sourced artifacts, the effective
  fold not recursing, `own_provenance` not stored, and a Cell-reachable module calling `attest`.
  plus the two below. **One MISSed on the first attempt and the mutation was at fault** — it added
  an import rather than a call, and the test is about calls.
- **A self-review found two defects the suite and the golden run both passed over**, and the first
  is the more serious. **§15.2's artifact index was feeding the Cell the creation-time position**,
  so an operator could establish a source's rights and the Cell whose work had just become sellable
  would still read `unknown` and never propose selling it — the gap moved one step upstream and
  somewhere quieter, with the export gate open and nothing ever reaching it. The index now shows the
  effective position (reading one is not §0.3-sensitive; defining one is). That is the whole of the
  golden run's token diff: `permitted` is two characters longer than `unknown`, the estimator is
  2 chars/token, and the five affected calls are exactly the deliberations after the attestation.
  Second, `rights.history()` given a `subject_kind` and no `subject` **silently returned the whole
  table** — the worst shape for a query an operator runs to check what they attested. Both are
  fixed, tested and teeth-checked.
- **Hand-verified end to end on a live colony.** A source-less artifact refused commercial export;
  `set-rights --colony` opened the gate while the stored row still read `unknown`; withdrawing
  closed it again and `rights --history` showed both positions with both reasons. Two message bugs
  surfaced only here and are fixed: `Attested colony colony`, and a refusal telling the operator of
  an artifact that read nothing to "establish the rights position on its sources" — advice with no
  route. The refusal now names the remedy that exists for the artifact in hand, with a test.
- Next: the nearest open work is that **nothing runs the scheduler** — `tick` is composable with
  cron per §30.1, but no supervision, no restart-on-failure and no alert when ticks stop.

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

## 2026-08-28 — Rung 8 is a scale step, and the claim that it removed a human had spread to four files

Migration 0030 + `autopromotion.py` + two injected seams + 18 tests + `auto-promote` +
golden expectations **32 -> 33** (ADR-063). **§25.1's ladder issues rung 8, and §12.3's stage
conversions are unblocked.**

### The build began by disproving its own brief

`promotion.py`, `outcome.py`, migration 0016's comment and — worst — the docstring of the
structural test enforcing the guarantee all said rung 8 "means removing one of the two humans".
§25.1 reads `7. Tiny capped live experiment` -> `8. Expanded pilot` -> `9. Bounded autonomy`: the
7 -> 8 delta is **scale**, and *autonomy* appears only at rung 9. `test_outcome.py` contradicted
its own docstring three lines below it, and the forbidden list was the half that was right ("a
promotion that fires on a timer is rung 9, not rung 8").

Left uncorrected, rung 8 and the autonomy flag would have become the same number.

### Two axes, kept apart by construction

`rung` says how far up §25.1 the money climbed; `decided_automatically` says whether a person was
in the loop. `ISSUABLE_RUNGS` is `(7, 8)` — rung 9 is excluded on purpose, because bounded autonomy
is a different decider, not a bigger cheque.

### The constraint went in the schema (ADR-047)

Migration 0030's trigger makes three things unrepresentable rather than refused: a rung above 7
with no predecessor, a predecessor that is not the rung immediately below, and a predecessor
belonging to **another Cell** — §29's reciprocal evidence farming as a foreign key pointing
somewhere plausible. A unique partial index makes one success expandable exactly once (§23.4's
splitting attack, run upward).

### Two seams, because both directions were blocked

`outcome` imports `promotion`, so the §25.2 gate is `promotion.PromotionEvidence` — and its
signature takes a **`promotion_id`, never a `cell_id`**, so it cannot be asked "how is this Cell
doing?" (§9.3's move applied to evidence). `promotion` imports `scheduler`, so the unattended
engine reaches the tick as `scheduler.PromotionSweeper`, supplied by the *caller*.

### The engine invents no new guard

`autopromotion.py` composes §27.1's `auto_promotion` flag (ships false), §27.1's `real_spending`
(still separately required for USD_REAL, so ADR-026's two confirmations stay two), §23.1's own
`batchable` predicate, the §25.2 evidence gate and the `promotion_pool` ceiling. It **cannot kill**:
§10.5 forbids culling on an estimate with no concurring Auditor, so `death`/`displacement`/`lineage`
are closed structurally at the one module that acts on a verdict.

### Verification

- **Teeth-checked twelve ways; eleven caught first time.** The twelfth was a test passing for the
  wrong reason — dropping the unique index left every test green, because the Python query declines
  to *find* an expanded predecessor. It now has a constraint-level test that reports `DID NOT RAISE`
  when the index goes.
- **1110 tests and the golden run green.** The golden diff is **one added key** —
  `autonomy.auto_promotion: false` — with balances identical in every account in every book. The
  scenario never turns it on; the mechanism ships complete and switched off.
- Next: §12.3's beta-binomial stage-conversion posteriors are now buildable — rung-7 promotions that
  converted to rung 8 are the binary they need. The Auditor path for §13.3/§13.4's content judgments
  remains the clearly-scoped other half.

## 2026-08-31 — §12.3's `P(next stage)` counts a realised conversion, never a verdict

`posteriors.py` + `mitosis posteriors` + 9 tests + golden expectations **33 -> 34** (ADR-064).
**§12.3's beta-binomial Thompson-sampling target ships: one posterior per §12 niche, built from
rung-7 -> rung-8 conversions.**

### The decision was which signal counts as a trial, not the arithmetic

`outcome.py` already computes a verdict — `SUPPORTS_PROMOTION` — for whether a rung-7 promotion's
own evidence would earn an expansion. It is available, binary, and the wrong thing to count. §10.5's
discipline (decide on realised facts, not estimates) generalises from one Cell to a niche of them: a
niche's conversion rate is about Cells that actually climbed the ladder, not about promotions the
kernel currently believes could. A Cell can earn `SUPPORTS_PROMOTION` and never be allocated rung 8 —
an operator can simply not act — and that is not evidence about the niche. The trial is a raw join on
`promotions.supersedes_promotion_id`, the realised fact ADR-063 made representable, computed without
ever calling into `outcome.py`.

### The niche is `novelty.archive`'s coordinate, and an empty one still gets a posterior

A rung-7 promotion is attributed to the §12.1 niche of the Cell's genome; genomes that abstain on
every dimension are counted separately (`unbinned_trials`/`unbinned_conversions`) rather than
dropped, matching `Archive.unbinned_genome_hashes`. **A niche with zero rung-7 promotions still
reports Beta(1, 1)**, not an abstention — the one dimension in this codebase where withholding would
be the less honest choice, because Thompson sampling needs every niche, funded or not, to have a
distribution it can be drawn from.

### No table

Derived on every read, same posture as `novelty.py` and `selection.py` toward §2.5/§12.2. This also
answers §12.3's own future-proofing clause for free: "schemas must allow hierarchical/non-stationary
models later" is automatic when the module owns no schema — a richer model is a different function
body over the same rows, never a migration.

### Guarded the same way `selection.py`'s frontier is

`test_no_kernel_path_acts_on_a_posterior` closes `death.py`, `promotion.py`, `displacement.py` and
`scheduler.py`; `test_the_posterior_never_reaches_a_cell` closes `context.py` and `deliberation.py`
(§23.5). §10.5's "estimated negative EV" shape, generalised from a Cell to a niche of them.

### Verification

- **9 new tests; teeth-checked two ways.** Conflating "converted" with "always true" (the tempting
  `outcome.assess` shortcut) failed four tests, including the one written to catch exactly it. A
  forbidden import into `death.py` was caught by the AST guard; the same mutation into `promotion.py`
  failed even earlier, at import time, with a circular-import error — `posteriors` already imports
  `promotion` for its rung constants, which makes that back-edge structurally impossible rather than
  merely refused.
- **1119 tests and the golden run green.** The golden diff is **one added section**,
  `stage_conversion_posteriors` — three niches, the scenario's one rung-7 promotion sitting at
  `trials: 1, conversions: 0`, the other two niches reporting the bare Beta(1, 1) prior. No balance,
  transaction, or existing row moved.
- Next: the Auditor path for §13.3/§13.4's content judgments is the other half ADR-062 scoped and
  clearly left open. §12.3's remaining four posteriors (expected net value, expected time to
  conversion, probability of reproducibility, probability of large loss) stay logged in
  FUTURE_BUILD_HOOKS — each needs machinery this colony does not have yet (§11.2's adoption record,
  a liability model, a survival-style time-to-event model).

## 2026-08-31 — §13.3/§13.4's Auditor path judges a genome directly

`content_audit.py` + migration 0031 + 21 tests + `audit-genome`/`audit-genome-pair`/
`content-audit-record` + golden expectations **34 -> 35** (ADR-065). **`auditor.py`'s machinery
gets its second subject: a genome (§13.3, and §13.4's "ordinary freelancing described
exotically") and a genome pair (§13.4's "the same mechanism is renamed") — scored the same way an
approval request already is.**

### One table, a `kind` column — the `promotions.rung` shape, not the attestation shape

Two precedents pointed opposite ways. `rights_attestations`/`buyer_attestations` copied one
shape into two separate tables for two genuinely different acts by different declarers.
`promotions.rung` keeps two variants of *one* mechanism together. This is the second case:
`software_native_advantage` and `renamed_mechanism` are the same act — an Auditor scoring a
probability about a Cell's own prose — with a different subject shape, so one table with a `kind`
discriminator and a nullable `compared_genome_hash` won. The CHECK constraint makes the pairing
itself unrepresentable: `software_native_advantage` forbids a second genome, `renamed_mechanism`
requires one distinct from the first.

### Independence, generalised from one Cell to a set of them

A genome has no single subject Cell — content-addressed, it may be carried by zero, one, or many,
dead or alive. The check: the auditor's own current genome must not be either hash under review,
and the auditor must share no lineage founder with *any* Cell that has ever carried either genome.
**Teeth-checking found the dedicated self-check is strictly subsumed by the lineage check** — a
Cell whose own genome matches always appears in the lineage query's own result, trivially sharing
a founder with itself. Both ship anyway: the first for a sharper error message, the second as the
actual guarantee.

### `concern`/`no_concern` transfers unchanged

Both kinds are framed as "genuinely holds up" (genuinely program-native, genuinely a distinct
mechanism), so migration 0018's verdict vocabulary and coherence rule apply with zero
modification — no new direction to get backwards.

### Verification

- **21 new tests; teeth-checked two ways.** Removing the dedicated self-audit check still raised
  (via the lineage check, confirming no coverage gap) but with the wrong, more generic message —
  a legitimate finding about diagnostic clarity, not a defect. Dropping the partial unique index
  (`idx_genome_content_audits_one_opinion`) produced a clean `DID NOT RAISE`, the exact shape
  `test_the_schema_refuses_a_second_opinion_from_the_same_auditor` exists to catch.
- **1140 tests and the golden run green.** The golden diff is **one added section**,
  `genome_content_audits: []` — empty, and stated as deliberate rather than hidden: the fixture's
  only two Auditor-eligible Cells share one lineage, and this module's own independence check
  refuses exactly that pairing. Manufacturing a valid pair means a sixth Cell, which moves
  population counts and every book's balance — logged for its own reviewed diff rather than
  folded into this one.
- Next: nothing yet consumes a content audit (`test_nothing_yet_consumes_a_content_audit` keeps
  it that way). `selection.py`'s `software_native_advantage` gate is the natural first consumer —
  reading a *resolved* audit only, never an unresolved one, which would be exactly the "estimated
  negative EV" shape §10.5 forbids acting on automatically.

## 2026-09-03 — §13.2's `software_native_advantage` gate reads a resolved content audit

`selection._software_native_advantage` + 3 new tests + golden run unchanged (ADR-066). **The gate
ADR-065 deliberately left `UNMEASURABLE` is now conditionally measurable**, the same way ADR-060
gave `structural_novelty` a live prior: `content_audit.py`'s Auditor path is this gate's one
consumer, and `test_only_selection_consumes_a_content_audit` (renamed from `test_nothing_yet_
consumes_a_content_audit`) keeps it that way.

### Only a resolved prediction may gate — an unresolved one is exactly §10.5's forbidden shape

An audit's `probability` is registered before the outcome is known; reading it into an automatic
gate would be gating a candidate on an *estimate*. The gate instead reads `prediction.get(conn,
audit.prediction_id).outcome` — set only once the register has resolved the claim against what was
actually observed. No audit at all is `UNMEASURABLE`, unchanged; an audit that exists but has not
resolved is `UNEVALUABLE`, not a rejection — the same distinction `_evidence_quality` already draws
for a Cell with no resolved forecasts.

### Any single resolved, vindicated concern rejects — no quorum across Auditors

§10.5's "an independent Auditor must concur" bar is written for *killing* a Cell. This gate does
not kill — a rejected candidate can be re-proposed once the concern is addressed, and more than one
Auditor may record an opinion about the same genome (migration 0031's partial unique index only
stops the *same* Auditor opining twice). Requiring unanimity would let a vindicated "ordinary
freelancing" flag be outvoted by Auditors who never looked closely, so the rule mirrors
`_policy_compliance`'s existing posture: any one resolved, vindicated concern rejects; the register
scoring the Auditor who raised it is the check on carelessness, not a second gate reading their
track record.

### A stale PRIORITIES claim, corrected rather than left to drift

PRIORITIES said `test_no_kernel_path_acts_on_a_frontier`'s allowed-importers list would also need
an edit. It did not — that test scans who imports `selection`, not what `selection` imports, and
this slice only added the latter. Logged and corrected in ADR-066 rather than left stale for the
next reader.

### Verification

- **3 new tests, teeth-checked.** Reverting the gate's wiring in `evaluate()` back to
  `_unmeasurable_gate("software_native_advantage")` failed the new PASSED test with the expected
  assertion (`UNMEASURABLE` where `PASSED` was expected) — a real MISS, not a false CAUGHT.
- **1143 tests and the golden run green, hash unchanged.** No fixture Cell has ever had a content
  audit (ADR-065's own golden note), so this slice's diff is nowhere in the replay — additive over
  a gate nothing in the scenario reaches yet.
- Next: `selection.py`'s frontier still carries two dimensions with no data at all
  (`economic_potential`, `reproducibility`) — see PRIORITIES `Next` for what each is blocked on.

## 2026-09-03 — `model_policy`'s temperature socket is filled

`genome.py` + `providers.py` + `deliberation.py` + `gateway.py` + 11 new tests across five files +
golden run unchanged (ADR-067). **§16.2's reserved socket — `model_policy`, written at birth and
read by nothing since ADR-050 named it — now carries a validated `{"temperature": 0.0-1.0}`, read
into every deliberation wake from the Cell's own genome, never a kernel constant.**

### The "inherited, mutated, or both" question was already answered

`model_policy` already sat in `INHERITABLE_FIELDS`, flowing through `inherit()`'s overlay like every
other genome field — a child keeps its parent's policy unless a mutation overrides it, which is both
inheritance and mutability at once, with no new mechanism built. What actually needed a decision was
the field's *content* shape, which had none: any JSON-serializable value passed before this slice,
including the free-text string one pre-existing test used as a stand-in
(`test_a_model_policy_change_is_not_a_new_idea`, now a dict). `MODEL_POLICY_FIELDS` closes it the
same way the top-level genome schema is closed — an unknown key is refused by name, because §14.1
names two more mutation operators (model-route, reasoning-budget) that could occupy this socket
later.

### Bounded to `[0.0, 1.0]` — the tighter of two providers' ranges, not their union

Anthropic hard-limits `temperature` to `[0.0, 1.0]`; Ollama accepts wider. Validating against the
tighter range is what §14.2's "counterfactual twins... differing by one prompt-level change" needs —
a value valid on one provider and rejected outright by the other would make a cross-provider
comparison undefined. The bound is enforced twice: once in `genome.py`, again at the
`providers.ModelRequest` pydantic field, so a bad value can never reach a provider regardless of
which caller built the request.

### `None` means "no opinion" and is never conflated with 0, end to end

A silent genome reports `temperature_of() is None`; `providers.py` omits the key entirely rather
than sending `temperature: null`; `gateway.py`'s new `model_calls.parameters_json` entry does the
same. This is not cosmetic — ADR-050 measured that temperature 0 (greedy decoding) collapses a
colony to one repeated idea per run, the worst outcome the earlier measurement found. Reading
absence as 0 anywhere in this chain would have silently reproduced exactly that failure mode.

### Scope: `deliberation.py` only

`auditor.py`, `content_audit.py`, and `cli.py`'s `call-model` still send no temperature. ADR-050's
argument is specifically about the agent loop's parse-rate/diversity trade-off; Auditor and
content-audit calls are operator-composed §10.4 judgments with the model already chosen by the
caller. Whether an Auditor's own genome should set its own sampling temperature is a real,
unargued question — logged in FUTURE_BUILD_HOOKS rather than bundled in here.

### Verification

- **11 new tests across `test_genome.py`, `test_providers.py`, `test_ollama_provider.py`,
  `test_gateway.py`, `test_deliberation.py`; teeth-checked twice.** Reverting
  `deliberation.py`'s wiring to `temperature=None` failed the end-to-end wake test with the exact
  expected assertion (`None == 0.3` where `0.3` was expected). Reverting `gateway.py`'s conditional
  `parameters["temperature"]` line failed the parameters test the same clean way. Both are real
  MISSes, not false CAUGHTs.
- **1157 tests and the golden run green, hash unchanged.** No scenario Cell declares a
  `model_policy`, so `parameters_json` stays `{"max_tokens": ...}` everywhere in the replay —
  absence stayed absent through the whole chain, exactly as designed.
- Next: `risk_tier` on `abstain` — PRIORITIES' next `Next` item, cheap and well-evidenced by two
  models independently refusing to state a risk tier for declining to act.

## 2026-09-03 — `risk_tier` is optional for exactly one kind: `abstain`

`proposal.py` + migration 0032 + `deliberation.py` + 8 new tests across three files + golden
35 -> 36 (ADR-068). **Two models independently produced the same failure shape on `abstain`
replies** — `qwen2.5` dropped `risk_tier` outright at t=0, `llama3.2` sent `"risk_tier": null` —
and PRIORITIES read it correctly: a stronger model reaching the same objection is evidence the
schema asked for something indefensible. §23.1 classifies *actions*; a Cell that proposes none has
nothing to classify.

### Two layers, each teeth-checked independently

`Proposal._risk_tier_matches_kind` (a `model_validator`, mirroring `_experiment_matches_kind`'s
shape) rejects a null `risk_tier` on every kind but `abstain` at parse time. Migration 0032 rebuilds
`proposals` with `CHECK (risk_tier IS NOT NULL OR kind = 'abstain')` — ADR-047's "unrepresentable,
not merely refused" applied again: a constraint with no layer belongs in the schema when the schema
can express it, binding every future caller regardless of whether it imports `proposal.py`.
Disabling either layer alone produces its own clean `DID NOT RAISE`/assertion failure, confirming
neither is redundant with the other.

### Scoped to exactly the defensible field

`qwen2.5`'s collapse dropped three fields, not one — `summary` and `estimated_cost_minor_units`
stay required. An abstaining Cell still has something to say, and its cost is trivially 0 (the
prompt already says so). Widening either would fix a different, unargued failure under cover of
this one.

### The "§23.1 implications" PRIORITIES flagged never materialised

`approval._enqueue_locked` already returns `None` for `kind == 'abstain'` before it ever reads
`risk_tier` — abstaining proposals have never reached the approval queue. The one place §23.1's
tier is read as a classification (`approval._assessed_tier`) is structurally unreachable for a row
that could carry NULL. `deliberation.py`'s two `.value` accesses were the only real call sites
needing a change.

### Verification

- **8 new tests across `test_prompt_shape.py` and `test_deliberation.py`; teeth-checked twice, once
  per layer.** Neutralising the Pydantic validator failed the parametrized "every other kind still
  requires a risk tier" test with a clean `DID NOT RAISE`. Dropping migration 0032's CHECK failed
  the schema-level `sqlite3.IntegrityError` test the same clean way.
- **1168 tests and the golden run green.** Golden expectations moved 35 -> 36: no scenario Cell
  ever proposes `abstain`, so the only diff is `input_tokens` shifting by a constant +30 on every
  deliberation-loop call — the rendered prompt hint describing the new exception is longer text,
  and `MockProvider`'s token estimate is a pure function of prompt length. `output_tokens`, cost,
  and every ledger balance are byte-identical.
- Next: a parse-repair retry (re-prompting with the validation error on an `UNPARSEABLE` reply) is
  the standard remedy still deliberately unbuilt — PRIORITIES flags it as worth arguing once the
  model question is settled, since a better model may make it unnecessary.

## 2026-09-04 — Parse-repair is *not* extended to the Auditors or `call-model`

`auditor.py` docstring correction + ADR-070; no other code change. **The ADR-069 parse-repair
mechanism stays in `deliberation.py` only — the follow-up BUILD_RECORD left "unargued, not a gap"
is now argued, and the conclusion is: don't port.** Recording the refusal *is* the deliverable.

### The three sites split two ways, and neither wants the retry

- **`cli.py`'s `call-model` is inapplicable, not scoped-out.** `cmd_call_model` takes a freeform
  `--prompt`, optional freeform `--system`, and prints `call.response_text` *raw* — no `parse()`, no
  schema, no `ProposalError`. A repair re-prompt names "the specific validation error"; there is
  none to name. This verb belongs on no follow-up list; struck.
- **`auditor.py` + `content_audit.py` look identical to deliberation, and the resemblance is the
  trap.** Same shape (paid `call_model` -> strict `_parse` -> recorded rejection on failure), so the
  mechanism would drop in. But their `_parse` error fires on two causes, not one: malformed JSON /
  schema violation *and* an **incoherent verdict** (`concern` above the coherence midpoint,
  `no_concern` below). Re-prompting a Cell to reformat its own proposal is reformatting;
  re-prompting an Auditor to fix a contradiction in its own verdict is coaching the judge, and
  §23.2/§10.4 make the Auditor's value its independence, produced once. Add lower salvage value (a
  rejected audit is already gracefully absorbed; a lost proposal is the loop's core output) and
  ADR-067's precedent putting the burden on the extension — and the port argues against itself.

### The stale claim it surfaced (the one code change)

`auditor._parse`'s docstring asserted its strictness was "the same policy `deliberation` applies:
never repair a half-understood judgement." False as of ADR-069 — `deliberation` now repairs once.
The recurring claim-drift shape: a comment naming another module's behaviour a later slice changed,
with no test defending it. Inverted into the deliberate divergence ADR-070 records rather than
deleted. `content_audit._parse` carried no such claim.

### Verification

- **Nothing to verify behaviourally — the decision is to build nothing.** 1175 tests and the golden
  run stay green (docstring edit touches no code path); golden hash unchanged. The teeth are in the
  record, not a test.

- Next: Phase 2 proper — synthetic customers, marketplace, MAP-Elites, regime shifts, chaos drills.
  Phases 2 and 3 remain deliberately skipped, so the selection machinery is still unvalidated. The
  parse-repair arc (ADR-069/070) is now fully closed, follow-ups and all.
