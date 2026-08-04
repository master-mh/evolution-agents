# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, and the first real paid call, 2026-07-21 through 2026-08-05):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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
- Not yet committed — reporting for review first.
- Next: fitness (revenue − spend) is now computable, but `ledger.spend_by_book`'s sign bug becomes
  load-bearing the moment selection reads it — a credited Cell currently reads as having spent more
  than it did. That fix needs §31's account-level split between funding sources and spend
  destinations, and it should land *before* anything selects on profit. See PRIORITIES.
