# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, and the full Phase 4
gateway arc, 2026-07-21 through 2026-07-28):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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
- Not yet committed — reporting for review first.
- Next: the first real paid call, which now needs only an `ANTHROPIC_API_KEY` and a deliberate
  `--yes-spend-real-money` run against a tiny cap.
