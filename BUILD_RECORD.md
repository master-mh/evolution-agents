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
auto-promotion reaching the scheduled `tick`, the flight simulator's first
slice (mock Cells deciding through the real deliberation pipeline), its
second (a second market family, environment separation, regime shifts), its
third (the remaining mutation operators, wired through a real choice), and
its fourth (chaos drills as repeatable scenarios),
2026-07-21 through 2026-09-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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

### What this does not close

The second acceptance-scale configuration: a moderate-scale validation (population=50, epochs=200)
run to confirm the founding fix at a scale that actually exceeds the birth-rate cap took over
fifteen CPU-minutes and was still running when this entry was written — well below a naive
extrapolation from the first slice's own smaller benchmark (~5.6 epochs/sec at population 20->70).
The brief's own >= 500 Cell/>= 10,000 epoch acceptance run is a genuinely multi-hour undertaking on
this hardware, exactly the case its own accommodation describes ("if runtime makes 500x10,000
unsuitable for ordinary CI, keep a small deterministic CI scenario, and a separately documented
benchmark command whose result artifact is retained"). The command is documented
(`mitosis simulate --population 500 --epochs 10000 --seed <n> --output <path>`) and the mechanism it
depends on is now proven correct; running it to completion and retaining its manifest is deferred to
a following slice rather than blocking this already-complete work on an unattended multi-hour job.

- Next: the >= 500 Cell/>= 10,000 epoch acceptance benchmark, run to completion with its manifest
  retained, closes out Slice F; then Slice G's remaining `SelectionPolicy` implementations and
  Slice H's pre-registered Phase 3 comparisons.
