# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, the experiment, experiment attribution,
proposed experiments, the strategy kind decided, the experiment_id foreign keys, §13.1's
normalised cost, the reply format a model can follow, the temperature/diversity
measurement, §15.1 anchoring and the twins that chose the fix, the proposal log that
shows no wording, the §23.4 repeat, the wake reason, the genome, the human-decision wake,
the +15% that did not survive honesty, §13.4's concreteness measure,
§13.2's selector, §12's novelty archive, the inbound counterparty key,
§12.1's declared third dimension, rung 8, §12.3's `P(next stage)`, the
Auditor path for §13.3/§13.4's content judgments, the software_native_advantage
gate reading a resolved content audit, model_policy's temperature socket,
risk_tier becoming optional for abstain, the bounded single parse-repair
retry, the argued refusal to extend it to the Auditors or `call-model`,
an external audit's clean source-distribution archive, its egress-boundary
repair (robots.txt transport, SSRF, honest personal-data status),
documentation/safety-claim reconciliation, a narrow runtime-defect lint gate,
auto-promotion reaching the scheduled `tick`, the flight simulator's five
slices (mock Cells deciding through the real deliberation pipeline; a second
market family with environment separation and regime shifts; the remaining
mutation operators wired through a real choice; chaos drills as repeatable
scenarios; manifest richness, a CI-scale acceptance test, a founding cap bug
fix, and a retained benchmark artifact), and closing the evolutionary
decision loop's six sub-slices (a run record that never named its
own selection policy and founder concentration as a real time series;
simulator-native fitness dimensions, the full decision-record schema, and
Thompson sampling; the single-leaderboard control policy; Pareto selection
reproducing the whole front, and a gate found structurally unreachable
through this pipeline; MAP-Elites, one elite per occupied niche; staged
funding composing everything, and the cross-family validation deadlock it
surfaced; the cross-policy acceptance harness), seed-paired batch
comparisons, a sealed simulated run, tools naming what observes their
effect, and two measurement instruments (judge entanglement and evaluator
epochs), 2026-07-21 through 2026-09-14):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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
