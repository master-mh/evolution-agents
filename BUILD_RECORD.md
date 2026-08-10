# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, and §9.3 displacement, 2026-07-21 through
2026-08-06): [docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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
- Not committed — reporting for review first.
- **What this does not show:** the loop has never been driven by a real model. Ollama was not
  reachable on this machine, and the paid path needs an explicit decision to spend. So there is no
  evidence yet about how often a real model returns schema-valid JSON — the unparseable path
  exists because it will not always. That, and something that wakes a Cell without a human asking,
  are the top two Next items.
