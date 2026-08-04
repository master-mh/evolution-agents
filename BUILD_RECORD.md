# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, and real-spend type registration, 2026-07-21 through 2026-07-30):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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
- Not yet committed — reporting for review first.
- Next: see PRIORITIES. The honest summary is that the *kernel* is proven and the *colony* does not
  exist yet — nothing in MITOSIS can currently earn a cent, and Phases 2 and 3 remain skipped.
