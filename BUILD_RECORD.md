# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, and the first two thirds
of the Phase 4 gateway arc, 2026-07-21 through 2026-07-28):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

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
