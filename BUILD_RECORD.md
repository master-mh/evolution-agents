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
gate reading a resolved content audit, model_policy's temperature socket, and
risk_tier becoming optional for abstain,
2026-07-21 through 2026-09-03):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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

- Next: `auditor.py`/`content_audit.py`/`cli.py`'s `call-model` get no parse-repair retry (scoped
  out the same way ADR-067 scoped temperature to `deliberation.py` only) — an unargued follow-up,
  not a gap in this slice. Otherwise, Phase 2 proper: synthetic customers, marketplace, MAP-Elites,
  regime shifts, chaos drills — Phases 2 and 3 remain deliberately skipped, so the selection
  machinery is still unvalidated.
