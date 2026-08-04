# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, and revenue + Ollama, 2026-07-21
through 2026-08-05): [docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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
- Not yet committed — reporting for review first.
- Next: fitness is now a trustworthy number, so the prediction register (a Cell states expected
  earnings *before* spending) is the cheapest real selection pressure available and needs no
  customer. Then §10.5 death criteria, which closes the evolutionary loop since reproduction
  already works. The agent loop remains the missing subsystem.
