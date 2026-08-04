# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, and the
`spend_by_book` account fix, 2026-07-21 through 2026-08-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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
- Not yet committed — reporting for review first.
- Next: §10.5 death criteria. With calibration and `spend_by_book` both trustworthy and `kill()`
  already built, death is what closes the evolutionary loop — reproduction already works, so a
  colony that can select is a colony that can evolve. The agent loop remains the missing subsystem,
  and nothing here changes that: a Cell still cannot make its own predictions.
