"""Golden-run replay (SPEC.md §26, Amendment A12; docs/DECISIONS.md ADR-017).

A golden run is a fixed scenario driven through the kernel, reduced to a
**semantic snapshot** and hashed. Re-running it later and comparing detects
accidental changes to economic behaviour (§26.3) — the reason §29's
acceptance criterion 11 and §30's deliverable list both name it.

Comparison is **semantic invariants plus a hash, not raw byte equality**
(ADR-017): `semantic_snapshot` deliberately excludes every volatile field —
uuid4 primary keys, wall-clock timestamps, hash-chain digests — and keeps
only what the kernel's economics actually mean: which accounts hold what
balance in which book, which Cells reached which lifecycle status with which
(content-addressed, therefore stable) genome hash, which reservations
settled for how much, what resources were metered, which audit-event types
fired and how often. Cell ids are replaced by birth-order aliases
(`cell#0`, `cell#1`, ...) so the snapshot survives the kernel generating
different uuids on every run.

That normalization is kept even now that ids.py exists (ADR-017's real
rationale is schema-evolution robustness — a byte-for-byte comparison would
break on any legitimate added field — not id determinism), but the raw run
itself no longer has to be non-reproducible underneath it: `run_scenario`
seeds `ids.py` (`GOLDEN_RUN_ID_SEED`, below) for its whole duration, so two
runs now produce not just the same semantic snapshot but the same raw
uuids in the same order — `test_semantic_hash_is_reproducible_across_runs`
in `tests/test_golden.py` checks the former, `test_raw_ids_are_reproducible_
across_runs` the latter. Kernel timestamps are still real wall-clock outside
this scenario's own fixed `SCENARIO_EPOCH` (see clock.py's docstring), so a
true byte-identical rerun of a *real* colony remains out of reach — but
that gap no longer exists for a scenario that, like this one, never reads
the wall clock for anything reaching the snapshot.

**Determinism gap this closes.** Amendment A5's ordering key
`(effective_time, priority, event_id)` is a *total* order, but was not
previously a *reproducible* one: when two events share an effective_time
and a priority, the tie-break falls to `event_id`, which was a fresh uuid4
every run. `_SCENARIO` sidesteps needing that tie-break at all by giving
every event a distinct priority — still true, and left that way since it's
also the clearest scenario to read — but with `ids.py` seeded, a future
scenario (or a real Phase 2 producer under a seeded run) that *does* rely
on the event_id tie-break now gets the same order every time, because it
gets the same event_ids every time.

Expectations are **versioned** (§26.2/A12): `golden_expectations.json` ships
`expectation_version` alongside the hash and invariants, and updating it is
a deliberate, visible act (`mitosis verify-golden-run --update-expectations`)
rather than something a routine change regenerates silently.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

from . import (
    approval,
    artifacts,
    channel_registry,
    auditor,
    clock,
    deliberation,
    db,
    events,
    experiments,
    external_actions,
    gateway,
    ids,
    ledger,
    lifecycle,
    lineage,
    outcome,
    population,
    prediction,
    promotion,
    providers,
    real_spend_breaker,
    reconciliation,
    reservations,
    resource_metering,
    revenue,
    rights,
    tool_registry,
    tools,
)
from .models import (
    Book,
    CellStatus,
    CellType,
    ClockMode,
    EntrySpec,
    PopulationLimits,
    RealSpendLimits,
    ResourceType,
)

EXPECTATIONS_FILENAME = "golden_expectations.json"

# Bumped only by a deliberate, reviewed expectation migration (§26.2, A12).
#   1 -> 2: the scenario gained a model-gateway call on the mock provider,
#           and the snapshot gained a `model_calls` section (§24).
#   2 -> 3: the scenario gained a provider-invoice reconciliation of that
#           call, and `model_calls` gained the §24.1 reconciled-cost fields.
#           No money moves — the mock's true cost is zero and the invoice
#           agrees — so the balances section is unchanged by this step.
#   3 -> 4: the scenario gained three §8.5 predictions (one resolved true,
#           one resolved false, one left open) and a `predictions` snapshot
#           section. Predictions move no money, so `balances`,
#           `transaction_types` and `reservations` are all unchanged; the
#           diff is confined to `predictions` and two new audit event types.
#   4 -> 5: the scenario gained the agent loop (§15/§17.2) — a wake event
#           enqueued and drained, one deliberation, one proposal, one
#           prediction — plus `deliberations` and `proposals` snapshot
#           sections. Reviewed diff, every part traceable to that one wake:
#           +1 mock model call (cost 0), so +1 USD_REAL reserve and +1
#           USD_REAL *release* (a zero-cost call releases rather than
#           settles), +1 RESOURCE reserve/settle pair and +2 resource_usage
#           rows, RESOURCE cell#1 cash -2 with infrastructure_reserve +2,
#           +1 unresolved prediction, +1 processed cell_wake event, and the
#           new `cell_deliberated` audit type. **No USD_REAL balance moves**,
#           which is the property a golden replay has to keep (§26): the mock
#           provider is priced at zero, and a run that started spending real
#           money would be the single worst regression this file could miss.
#   5 -> 6: the proposal schema hint stopped rendering enum choices as JSON
#           arrays. The first real-model run (llama3.2, local) returned
#           `"risk_tier": ["MEDIUM"]` — a correct choice in the wrong shape,
#           because the prompt showed the field as a list. Prompt text only:
#           the deliberation's `input_tokens` goes 1383 -> 1450 and its metered
#           `resource_usage.quantity` follows. **No balance, reservation, or
#           transaction type changes**, which is what a pure prompt edit should
#           look like — anything else in this diff would have meant the loop's
#           economics moved, not just its wording.
#   6 -> 7: the scenario's proposal now enters §23's approval queue, because
#           both the CLI and the scheduler wire that sink — a golden run
#           without it would pin a path the colony no longer takes. Three
#           sections differ and nothing else does:
#           (a) new `approval_requests`: one entry, claimed LOW / **assessed
#               MEDIUM**, exposure 25, reversible, pending, sla 14400s, one
#               `understated_risk` signal. That single row is §23.5's central
#               guarantee made visible in the replay — the scenario's Cell
#               asked to be reviewed as LOW and the kernel declined, so a
#               regression that let a Cell set its own tier would show up here
#               as `assessed_tier: LOW` rather than passing silently.
#           (b) new `approval_grants`: 0. Pinned as a count precisely because
#               it must stay 0 — §25.1 puts this loop at rung 6, and a golden
#               run that began issuing grants to itself would be the drift
#               this file exists to catch.
#           (c) `audit_event_types` gains `approval_requested`, and only that.
#           **No balance, reservation, transaction-type or conservation change**
#           — queueing a proposal for review moves no money, and the balances
#           section is byte-identical to version 6.
#   7 -> 8: a dead Cell's estate is now reclaimed as part of its death — open
#           reservations released, residual cash returned to `colony_treasury`
#           (Charter C8, C1; ADR-028). The diff makes the bug it fixes visible
#           and is the reason to keep this section short: the scenario's dead
#           Cell had been silently holding **3450 USD_SIM** on
#           `cell:cell#0:cash` since version 1, and every death before this
#           lost that capital to a Cell that could never spend it again.
#           Exactly four values move: `cell:cell#0:cash` 3450 -> 0,
#           `colony_treasury` 300 -> 3750 (the same 3450, so this is a
#           transfer and USD_SIM conservation is unchanged), one new
#           `cell_estate_reclaim` transaction type, and one new
#           `cell_estate_reclaimed` audit type. **No USD_REAL movement** — the
#           scenario's dead Cell holds no real money — and no reservation,
#           prediction, proposal or approval section changes.
#   8 -> 9: the scenario now runs the colony's **core loop end to end** (§31:
#           "... -> allocate capital -> ..."), which had never been covered:
#           the auditor's child deliberates a spend request, it is queued under
#           §23, approved, and its grant allocated at §25.1 rung 7 (ADR-029).
#           Every line of the diff traces to that one block:
#           (a) cell#4 funded 20 USD_REAL and 2000 RESOURCE from `seed_bank` so
#               it can pay for its own thinking (§15.4). **Transfers, not
#               spend** — `external_expense` is unchanged in every book.
#           (b) its deliberation adds one mock model call: +1 RESOURCE
#               reserve/settle pair, `infrastructure_reserve` +2, cell#4
#               RESOURCE cash 2000 -> 1998, and a USD_REAL reserve/**release**
#               pair (a zero-cost call releases rather than settles, which is
#               the tell that no real money moved).
#           (c) `promotion_pool` funded 500 from `colony_treasury`
#               (3750 -> 3250), then 30 allocated to cell#4 (pool -> 470,
#               cell#4 USD_SIM 500 -> 530).
#           (d) a new `promotions` section: one row, **rung 7**, 30 USD_SIM,
#               liability and transfer degradation both null because neither is
#               knowable at a first promotion, and two named humans.
#           (e) audit gains `approval_granted`, `capital_allocated` and
#               `promotion_pool_funded`; `approval_requested` and
#               `cell_deliberated` each go 1 -> 2.
#           **The allocation deliberately runs on a USD_SIM Cell.** The
#           explorer is USD_REAL and `promotion.allocate` refuses it without
#           §27.1's `autonomy.real_spending`, which this scenario must never
#           enable — a replay that started moving real money is the worst
#           regression this file could miss. Conservation holds in all three
#           books; both hash chains and resource linkage stay green.
#   9 -> 10: the loop now closes back on itself. Version 9 funded a Cell and
#           stopped; §25.2 asks for "predicted vs **observed** outcome" at each
#           rung, and observed outcomes only exist afterwards. The scenario
#           gains three forecasts on the spend request and resolves all three
#           after the allocation, and the snapshot gains an `assessments`
#           section. Six sections differ and nothing else does:
#           (a) `predictions` gains three rows on cell#4 — p=0.8, resolved
#               true, Brier 0.04 and log 0.223144 each — joining the six
#               already there.
#           (b) `audit_event_types`: `prediction_registered` 4 -> 7 and
#               `prediction_resolved` 2 -> 5. Three registrations and three
#               resolutions, which is the whole of what this step does.
#           (c) the `promotions` row's `unresolved_predictions` goes 0 -> 3.
#               That snapshot is taken at funding, when all three forecasts are
#               still open — which is exactly the state the read-back needs.
#               Its being 0 before was a scenario funding a Cell that had
#               promised nothing.
#           (d) new `assessments`: one row, **verdict `supports_promotion`**,
#               3 of 3 funding forecasts resolved, observed Brier
#               0.03999999999999998 (pinned as the float it is, since it is the
#               number the verdict turns on), zero overdue, `funded_mean_brier`
#               and `reality_gap` both null — cell#4 had no resolved record at
#               funding, so there is no baseline it could have degraded from —
#               liability null, 30 allocated and **0 consumed**, and 3 human
#               interventions, being the three operator resolutions with the
#               allocation itself correctly excluded.
#           (e) `model_calls[2].output_tokens` 139 -> 279 and, following it,
#               `resource_usage[9].quantity` 139 -> 279. **Not predicted when
#               this diff was first written, and worth naming for the reason
#               v5 -> v6 was:** the mock provider's reply is now three
#               predictions longer, and output tokens are estimated from the
#               reply's length. 279 still sits well inside the 700-token
#               `DEFAULT_MAX_TOKENS` budget, so nothing was truncated.
#           **No money moves at all in this step.** Resolving a forecast posts
#           no transaction, and although the metered *quantity* above doubled,
#           the metered *charge* did not — so `balances`, `transaction_types`
#           and `reservations` are byte-identical to version 9 and
#           `external_expense` stays 0 in every book. **What this pins is a
#           verdict, not an action** — nothing in the kernel may read one
#           (`test_no_kernel_path_acts_on_an_assessment`), so if a later slice
#           makes a verdict move money or end a Cell, the diff appears here
#           first, in a section that today reports and does nothing.
#  10 -> 11: §9.2's `max_births_per_epoch` is enforced, so a Cell now records
#           the epoch it was born in (migration 0017), and the `cells` section
#           pins it. Two sections differ and nothing else does:
#           (a) `cells[*].born_in_epoch`: null -> 0 for the four founders and
#               **1 for cell#4**, the auditor's child. The scenario turns one
#               epoch immediately before that reproduction on purpose — a
#               snapshot where every Cell was born in epoch 0 would pass just as
#               happily against a kernel that stamped a constant, which is
#               exactly the regression that would leave the cap unenforced.
#           (b) `clock.simulated_at` 2026-01-08 -> 2026-01-09, being that one
#               epoch. The clock is paused, so the advance is exact, and
#               nothing else in the scenario moves with it: reservations expire
#               in 2030 and no tick runs here.
#           **No money moves.** `balances`, `transaction_types`, `reservations`,
#           `resource_usage`, `predictions`, `promotions` and `assessments` are
#           all byte-identical to version 10, and `external_expense` stays 0 in
#           every book. The scenario also now anchors epoch zero explicitly at
#           `SCENARIO_EPOCH`; without an anchor a colony reports epoch 0 forever
#           and (a) would have been a column of zeroes.
#  11 -> 12: §23.2's "independent Auditor summary" is producible, so the
#           scenario produces one (ADR-032). The auditor's child — an AUDITOR
#           by inheritance, of a different lineage from the explorer — audits
#           the explorer's queued request. Seven sections differ:
#           (a) new `audits`: one row, **auditor cell#4 / subject cell#1**.
#               Both sides are pinned as aliases so the *independence* is what
#               the snapshot checks — a regression letting a Cell audit itself,
#               or a relative do it, appears here as the same alias twice
#               rather than passing silently. Recorded, `concern`, p=0.3, with
#               a prediction attached (§10.4: a flag that stakes nothing is a
#               free flag).
#           (b) `balances`: RESOURCE cell#4 cash 1998 -> 1996 and
#               `infrastructure_reserve` 1856 -> 1858. That is the audit's
#               metered compute, and it is §10.4's governance overhead becoming
#               non-zero for the first time. **USD_REAL is unchanged.**
#           (c) `reservations` gains two rows for cell#4: a USD_REAL
#               reserve/**release** (max 1, settled 0) and a RESOURCE
#               reserve/settle (max 2, settled 2). The release is the tell that
#               no real money moved — the mock is priced at zero.
#           (d) `resource_usage` gains two rows (input 1461, output 279) and
#               **rows [8]/[9] appear to change, 1461 -> 1190 and 279 -> 104.
#               They did not.** The audit now runs before the child's
#               deliberation, so the audit's smaller call takes those indices
#               and the deliberation's unchanged numbers move to [10]/[11].
#               Checked rather than assumed, because a reordering and a
#               regression look identical in a positional diff.
#           (e) `transaction_types`: RESOURCE reserve/settle 4 -> 5, USD_REAL
#               reserve 5 -> 6 and release 3 -> 4. One more zero-cost call.
#           (f) `predictions` gains the audit's flag, left **unresolved on
#               purpose**, and `promotions.unresolved_predictions` goes 3 -> 4
#               because it was open when the capital moved. The §25.2
#               assessment therefore now reads 3 of 4 resolved with 1 still
#               open and none overdue — which also covers the
#               outstanding-but-not-yet-due path that version 11 could not
#               reach. The verdict stays `supports_promotion`.
#           (g) `audit_event_types`: new `request_audited` 1,
#               `model_call_settled` 3 -> 4, `prediction_registered` 7 -> 8.
#           **No USD_REAL balance moves and `external_expense` stays 0 in every
#           book.** `cells`, `proposals`, `deliberations`, `approval_requests`,
#           `approval_grants`, `coroner_reports`, the event tables and the clock
#           are all byte-identical to version 11 — an audit advises and changes
#           no decision, which is exactly what §10.4's ban on "unnecessary
#           blocking" requires, and `approval_grants` staying put is where a
#           regression to a blocking Auditor would show.
#   12 -> 13 (genome content, §16.2/§16.3/§16.4; ADR-033). The auditor founder
#           is seeded with real genome content — market, problem, workflow and a
#           `risk_class` of HIGH — and its child now *inherits* that content
#           instead of having a genome rebuilt from cell_type alone. Five
#           sections move and each follows from one of those two facts:
#           (a) `cells`: two `genome_hash` values change — the auditor's (it now
#               carries content) and its child's (it inherits that content and
#               mutates `acquisition_channel` where the old scenario set a
#               `strategy` key the closed schema no longer accepts). The other
#               three Cells are unseeded and untouched, which is the control:
#               a regression that leaked content across lineages would move them.
#           (b) `deliberations`: `context_tokens` 289 -> 343, and
#           (c) `model_calls`: `input_tokens` 1461 -> 1570, and
#           (d) `resource_usage`: `quantity` 1461 -> 1570 — all one cause. The
#               genome renders into the prompt as data (§15, Charter C15), so a
#               genome with content is a longer prompt, and A6 linkage carries
#               the token count into metered RESOURCE 1:1. The three must move
#               together; one moving alone would mean metering had come unstuck
#               from the call it meters.
#           (e) `approval_requests`: the child's `assessed_tier` MEDIUM -> HIGH
#               and `sla_seconds` 14400 -> 3600. **This is the load-bearing line
#               of the diff.** The child inherited `risk_class: HIGH` and §16.2's
#               claim folds into `_assessed_tier` with the same `max` ADR-027
#               applies to `claimed_tier` — so the tier rose above what the
#               proposal itself claimed (still MEDIUM) and the SLA shortened to
#               match. It demonstrates both halves of the slice at once:
#               inheritance carried the claim from parent to child, and a claim
#               escalates review. A genome that could *lower* a tier would show
#               here as the opposite move, which is why the seeded class is
#               deliberately not LOW.
#           **No money moves: `balances` and `reservations` are byte-identical
#           to version 12, and `external_expense` stays 0 in every book.** The
#           unseeded explorer's request is unchanged, which is the check against
#           a genome claim leaking onto a Cell that never made one.
#   13 -> 14 (the tool surface, §19/§18.1/§20.1/§0.4; ADR-034). The scenario
#           gains §25.1's rung 4: cell#4 proposes a read-only fetch, a human
#           approves it, the grant runs the tool, and the Cell is woken once
#           more so the result is in its context. Three sections are new and
#           the rest follow from two extra deliberations plus one tool call.
#           (a) **`tool_calls` (new)**: one succeeded `http_get`, taint
#               UNTRUSTED_EXTERNAL, licence and commercial_use both `unknown`.
#               The rights columns are pinned in full on purpose — a slice that
#               began defaulting a licence to "permitted" would be
#               manufacturing a rights position (§20.2), and this is the only
#               place that would show. `result_bytes` is pinned and the text is
#               not: the fixture's wording is not an economic fact, but how much
#               of a page reaches a Cell is.
#           (b) **`egress_allowlist` (new)**: exactly `golden.test`, added
#               mid-scenario. **`autonomy` (new)**: four flags false, one true.
#               Both start closed and are opened by an explicit step, so a
#               colony that ever shipped either open by default diffs here.
#               That is the single most valuable regression in this section.
#           (c) `proposals` 2 -> 4, and the rows gain `derived_from_untrusted`.
#               The values are `[false, false, false, true]` and the last one is
#               the reason the scenario wakes cell#4 *again* after the fetch: a
#               column that is uniformly false passes just as happily against a
#               kernel that hardcodes false, which is how ADR-031's
#               `born_in_epoch` nearly shipped untested. The `true` is §18/§19.4
#               taint propagation working.
#           (d) `approval_requests` 2 -> 3, `approval_grants` 1 -> 2. The new
#               request is the tool request: claimed LOW, **assessed HIGH**,
#               signal `understated_risk`. HIGH rather than the MEDIUM a
#               read-only tool alone earns, because cell#4 inherited
#               `risk_class: HIGH` from the seeded auditor genome — ADR-033 and
#               ADR-034 composing, and worth pinning as such.
#           (e) `deliberations` 2 -> 4 and `model_calls` 4 -> 6: the tool
#               request and the post-fetch wake. Existing rows' `context_tokens`
#               and `input_tokens` rise (282 -> 381, 343 -> 442; 1450 -> 1790,
#               1570 -> 1910) from one cause — every Cell's context now carries
#               the "Tools you may request" section (§0.4), which is what makes
#               a tool_request proposal possible at all.
#           (f) `resource_usage` 12 -> 17 and `reservations` 15 -> 20. Four rows
#               belong to the two new model calls; the fifth is the tool call's
#               `network_requests` quantity 1 / 5 minor units, with a matching
#               RESOURCE reservation tagged `external_operation_type=tool_call`.
#               A fetch is metered and never billed.
#           (g) `balances`: **RESOURCE only** — cell#4 cash 1996 -> 1987 and
#               `infrastructure_reserve` 1858 -> 1867, the same 9 units.
#               `transaction_types` gains RESOURCE reserve/settle 5 -> 8 and
#               USD_REAL reserve 6 -> 8 / release 4 -> 6. **The USD_REAL pair
#               moves together — reserved and released, never settled — which is
#               the tell that the new model calls cost nothing.**
#           **No USD_REAL balance moves and `external_expense` is unchanged in
#           every book (20 / 1550).** `cells`, `predictions`, `audits`,
#           `promotions`, `assessments` and `coroner_reports` are byte-identical:
#           a tool call observes, and changes nothing about who exists, what
#           anyone forecast, or what anyone was paid.
#   14 -> 15 (the artifact store, §20/§18.1/§11/§15.2/§19.3, A3; ADR-035). The
#           post-fetch wake now hands in a deliverable, both export gates are
#           exercised against it, and the money that follows names it. The diff
#           is deliberately small — the artifact rides on the deliberation that
#           already existed, so `deliberations`, `proposals`, `model_calls`,
#           `resource_usage` and `reservations` are all **unchanged in count**.
#           (a) **`artifacts` (new)**: one `report`, 55 bytes, cited from the
#               fetched page. `commercial_use: unknown` and taint
#               `["UNTRUSTED_EXTERNAL"]` are both **inherited, not declared** —
#               if either ever reads `permitted` or `[]`, §20.2's laundering
#               path has reopened and this line is where it shows. `exported:
#               true`, `export_is_commercial: 0`: the scenario tries a
#               commercial export first and **requires it to be refused**, then
#               exports non-commercially. A run that only exported successfully
#               would pass identically against a gateway that refused nothing.
#               The content is excluded and a hash prefix pinned instead —
#               content addressing is the §11.3 mechanism, so what matters is
#               that identical work yields an identical address.
#           (b) **`artifact_lineage` (new)**: `{edges: 1, from_tool_calls: 1,
#               from_artifacts: 0}` — §11.4's contribution graph, shape only,
#               since source ids are volatile.
#           (c) **`artifact_attributed_ledger_entries` (new)**: 1. Amendment
#               A3's `ledger_entries.artifact_id` has existed since migration
#               0001 and was populated for the first time here.
#           (d) `balances`: **USD_SIM only** — cell#4 cash 530 -> 570 and the
#               `revenue` account appearing at -40 (revenue accumulates
#               negative, the same convention `external_capital` uses).
#               `transaction_types` gains `USD_SIM::cell_revenue: 1`, which is
#               **the first time in the golden run's history that money has
#               entered the colony at all** rather than moving within it.
#           **No USD_REAL balance moves and `external_expense` is unchanged in
#           every book (20 / 1550).** The revenue is deliberately USD_SIM: a
#           golden run must never move real money, and `record_revenue` is the
#           one verb that brings money in.
#   15 -> 16 (the external-action registry, §21/§23.4/§16.3/§28 Phase 8;
#           ADR-036). The largest diff since the gateway, and most of it is one
#           cause: the scenario gains **three deliberations** (two granted
#           external actions plus the one whose claim is refused), and every
#           section that counts wakes moves with them.
#           (a) **`external_actions` (new)**: two rows, both `completed`, both
#               on `email`, both `addressed: true`, both `delivers_artifact:
#               true`. Outcomes are deliberately `no_response` and `complaint`
#               — a run where nothing ever went wrong would pass identically
#               against a kernel that recorded damage and acted on none of it.
#               **There is no `counterparty_hash` field and there must never
#               be**: the salt is generated per colony, so the value is
#               volatile — but the real reason is that a snapshot is a file
#               people read, and a stable per-person token in one would undo in
#               the readable artifact what §16.3 asked the schema not to hold.
#           (b) **`channel_frozen` (new)**: `{email: true, ...}`. The complaint
#               froze the channel colony-wide (§21.1) and nothing in the
#               scenario clears it, so the run ends with a halted channel —
#               which is the honest end state and pins that a complaint does
#               something rather than merely being written down.
#           (c) **`counterparty_blocks` (new)**: `["complaint"]` — reasons, not
#               hashes. The do-not-contact list is the strongest thing hashing
#               buys and this is the line that proves it is populated.
#           (d) **`human_minutes` (new)**: `{reported: 38, billed: 34}`, and
#               **the two differ on purpose**. §2.2's `HUMAN_MINUTES` had been
#               declared since Phase 1 and metered by nothing. The first action
#               runs 4 minutes past what the email channel bills a Cell for, so
#               the Cell pays 30 and the registry records 34 — §1's "hidden
#               human labour and subsidy", exposed rather than capped away. A
#               snapshot with only one figure could not distinguish a colony
#               that measures its human cost from one that quietly truncates it.
#           (e) `approval_requests` 3 -> 6 and `approval_grants` 2 -> 5. All
#               three new requests are `reversible: false`, `HIGH`, and carry
#               **no signals**, and every part of that is load-bearing.
#               `exposure_minor_units: 0` beside a HIGH tier is the tell that
#               this kind is dangerous for a reason that has nothing to do with
#               money. The empty `signals` list is the *second* draft: the
#               first claimed MEDIUM and tripped `understated_risk` on all
#               three, which looked like a working detector and was the
#               opposite — a §23.4 signal that fires on every external action
#               ever proposed distinguishes nothing. The context now states the
#               tier, so an understated claim is a real one again.
#           (f) `resource_usage` gains two `human_minutes` rows (30 and 4) and
#               `transaction_types` gains `RESOURCE::reservation_release: 1` —
#               one claim settles fully (its 30 billable minutes exactly
#               exhaust the reservation) and one settles partially and releases
#               the rest, so both branches of the settle/release pair replay.
#           (g) `deliberations` `context_tokens` rise across the board (381 ->
#               554 on cell#1) because every Cell now sees a "Channels you may
#               request" section. The first draft of that section cost 318 of
#               a 1200-token budget — a quarter of every wake, on a capability
#               whose flags ship off — and was cut to ~150; §15.1's budget is
#               the reason the registry ships a `short_description` at all.
#           (h) `autonomy` gains `external_message: true` — opened inside the
#               scenario rather than in setup, so a colony that ever shipped
#               the flag open by default diffs here.
#           **No USD_REAL balance moves and `external_expense` is unchanged in
#           every book (20 / 1550).** `USD_REAL::reservation_reserve` 8 -> 11
#           and `release` 6 -> 9 move as a pair — the three new wakes reserve
#           and release, never settle, which is the tell that they cost nothing.
#           `cells`, `predictions`, `artifacts`, `coroner_reports` and
#           `promotions` are byte-identical: an external action reaches outside
#           the colony and changes nothing about who exists inside it.
#   16 -> 17 (one autonomy flag per capability, and the §21.2 key a publish
#             channel collides on; §0.4, §21.2/§21.3, §27.1, §28 Phases 8-9;
#             ADR-037).
#           The scenario gains four publish cases and every section below moves
#           because of them. **The one that is the point of the slice is (d).**
#           (a) **`autonomy`** gains `real_commerce: false` and flips
#               `external_publish` to true. `external_publish` was gating two
#               capabilities — `web_publish` and `marketplace_listing` — which
#               made it the only flag in the kernel opening more than one, and
#               made `cmd_set_autonomy`'s "there is deliberately no switch that
#               opens more than one" false as written. §0.4 lists six
#               prohibitions and §27.1's block carries five keys; "no real
#               commerce" is the one that never got one, and a listing is
#               commerce rather than publishing.
#           (b) **`external_actions`** gains one row: `web_publish`,
#               `delivered`, `domain: golden.test`, 20 human minutes, carrying
#               the artifact. Three further claims are *refused* and therefore
#               write no row — which is what makes the counts below the
#               assertion rather than the row itself.
#           (c) **`human_minutes`** 38/34 -> 58/54. Both move by exactly 20:
#               the publish is under `web_publish`'s 45-minute ceiling, so it
#               records no subsidy, and the 4-minute gap from the email action
#               survives unchanged. A run whose only human-minute figure came
#               from an over-ceiling action could not tell the two apart.
#           (d) **The split flag, proved in one colony.** `external_publish` is
#               open and `real_commerce` is shut, so a `marketplace_listing`
#               claim is refused while `web_publish` succeeds. **A kernel that
#               re-merged the two flags passes every other assertion in this
#               run and fails here.** It also pins that approval is not
#               permission: the refused grant is real and was approved by a
#               person (§25.1 rung 6, not rung 9).
#           (e) **The §21.3 checks that did not exist.** A second lineage on
#               `golden.test` is refused as a sibling collision, and the same
#               lineage republishing the same artifact there is refused as a
#               duplicate — while the same lineage publishing *different*
#               content would not be. Before ADR-037 both claims succeeded:
#               every §21.2 check was counterparty-keyed, so a channel that
#               addresses nobody skipped all of them.
#           (f) `deliberations`, `proposals`, `model_calls`, `approval_requests`
#               /`grants`, `assessments`, `event_inbox` and `audit_event_types`
#               all move by the four new wakes the four cases need. Each is a
#               mock call priced at zero.
#           (g) `resource_usage`, `reservations` and `transaction_types` move
#               with them: `RESOURCE::reservation_reserve`/`settle` 13 -> 18
#               (four wakes plus the claim) and `release` 1 -> 2 (the claim
#               settles 20 of the 45 minutes reserved and releases the rest).
#               `RESOURCE::cell#4:cash` -206 and `infrastructure_reserve` +208
#               is the same movement seen from both ends.
#           **No USD_REAL balance moves and `external_expense` is unchanged in
#           every book (20 / 1550).** `USD_REAL::reservation_reserve` 11 -> 15
#           and `release` 9 -> 13 move as a pair with `settle` fixed at 1 —
#           four new wakes that reserve and release and never settle, which is
#           the tell that they cost nothing. `cells`, `predictions`,
#           `artifacts`, `artifact_lineage`, `coroner_reports`, `promotions`,
#           `counterparty_blocks` and `channel_frozen` are all byte-identical:
#           publishing reaches outside the colony, and a refusal reaches
#           nothing at all.
#   17 -> 18 (§23.3's other clock: an approval nobody consumed is regenerated;
#             §23.3/Amendment A19, §3.6, §17.2; ADR-039).
#           A tight diff — three sections — and what is *absent* from it is half
#           the point.
#           (a) **`approval_grants`** stops being a bare count and becomes a
#               disposition: `9` -> `{total: 9, live: 0, consumed: 5,
#               expired: 4, regenerated: 4}`. Four grants in this scenario were
#               approved by a person and never consumed — the refused email
#               sibling claim and the three refused publish claims — which is
#               exactly §23.3's solo-operator case. **`total` is unchanged by
#               the sweep, and that is the assertion**: regeneration must be a
#               wake and never a fresh grant, because renewing it is the banking
#               a grant's inherited expiry exists to prevent. A kernel that
#               renewed instead of waking would still show `expired: 4` and
#               would move `total` to 13.
#           (b) **`audit_event_types`** gains `grant_expired: 4`.
#           (c) **`event_inbox`** gains four pending `cell_wake` rows — the
#               regeneration itself, the Cell being asked for the action again.
#           **Nothing else moves at all.** No balance, no transaction, no
#           reservation, no resource_usage row: `approve` inserts a row and
#           reserves nothing (ADR-029 allocates capital when a grant is
#           *consumed*), so an expired grant has nothing to release and expiry
#           has no ledger consequence. A diff that touched the books here would
#           mean granting had quietly started holding something.
#   18 -> 19 (rights an operator establishes; §20.1/§20.2/§20.3, §0.3, §3.6;
#             ADR-041).
#           **Two sections, and the section that does *not* move is the
#           assertion.** The scenario attests `golden.test` as CC-BY-4.0 with
#           commercial use permitted, *after* the artifact citing it was made and
#           exported.
#           (a) **`rights_attestations` (new)**: one row — `domain golden.test`,
#               `CC-BY-4.0`, `permitted`, by `golden-operator`, with its basis
#               pinned in full. §20.3 makes an unfounded position a liability
#               rather than a mistake, so a regression that kept the permission
#               and dropped the operator's stated reason is precisely what this
#               section exists to fail on.
#           (b) **`audit_event_types`** gains `rights_attested: 1`.
#           (c) **`artifacts` is byte-identical**, and that is the point of
#               placing the attestation last. `commercial_use` still reads
#               `unknown` on the one artifact in the run: §3.6 says post an
#               adjustment rather than edit history, so establishing a rights
#               position must not rewrite what an artifact was born with. The
#               scenario asserts that column directly *and* asserts that
#               `check_exportable(commercial=True)` — which refused a few lines
#               earlier — now passes. A kernel that cascaded the new position
#               into the table passes the second and fails the first; one that
#               read the stored column at the export gate fails the second and
#               would leave every pre-attestation artifact permanently
#               unsellable, which is the gap ADR-041 was built to close.
#           (d) **`model_calls` and `resource_usage`**: five rows of thirteen
#               gain exactly one input token each. §15.2's artifact index shows
#               the Cell the *effective* position rather than the stored one —
#               otherwise an operator could establish a source's rights and the
#               Cell whose work became sellable would still read `unknown` and
#               never propose selling it, moving this slice's gap one step
#               upstream instead of closing it. The five are the deliberations
#               after the attestation; `permitted` is two characters longer than
#               `unknown` and `providers._estimate_tokens` is 2 chars/token, so
#               the arithmetic is exact and the count of affected calls is the
#               count of calls that could see it.
#           **No money moves**, in either book: an attestation is a statement
#           about a licence and touches no accounting table at all. `balances` is
#           identical across every account — the extra token moves the recorded
#           raw `quantity` and rounds to the same RESOURCE charge, and USD_REAL
#           is untouched as it must be.
#   19 -> 20 (the experiment; §2.5/§2.6, §9.2, §10.5, §15.1, §25.1; ADR-043).
#           Two experiments: one at rung 7 on the Cell the scenario kills, one
#           at rung 1 on the Cell that earns.
#           (a) **`experiments` (new)**: both rows, each carrying its **derived**
#               §2.6 figures rather than stored ones. `synthetic_revenue: 40` on
#               the second is the assertion — a derivation reading the Cell's
#               cash leg instead of the `revenue` account, or the wrong book,
#               fails here rather than only in the hash. `sandbox_cpu_seconds`
#               and `human_minutes` are **null, not 0**: §19.3's sandbox is
#               Phase 5 and `resource_usage` carries no experiment_id, and a 0
#               would claim they consumed nothing.
#           (b) **`coroner_reports.stage_reached`**: `null` -> `"rung 7: tiny
#               capped live experiment"`. §10.5 has required this of every death
#               since migration 0007 and no kernel could supply it. The row's
#               experiment is `abandoned` with `concluded_by: "kernel"` — the
#               §9.2 slot being released, because a colony that leaked one per
#               death would ratchet to its cap and refuse every new experiment
#               with nothing explaining why. Abandoned and never concluded: it
#               reached no answer.
#           (c) **`audit_event_types`** gains `experiment_started: 2`,
#               `experiment_concluded: 1`, `experiment_abandoned_on_death: 1`.
#           (d) **`deliberations.context_tokens`** +62 on each of five, and
#               `model_calls`/`resource_usage` follow. §15.1 names "current
#               experiment" second in its list, right after the genome, and the
#               five are exactly the deliberations that ran while one was open.
#               The section shows the *derived* report, which also answers what
#               the 2026-08-06 live run found: every model set
#               `estimated_cost_minor_units` to 0 because §15 context showed
#               balances but never what anything had cost.
#           (e) **`predictions.claim`** has its embedded uuid scrubbed to
#               `<id>`. Not a behaviour change — a snapshot-hygiene fix this
#               slice surfaced. The auto-registered promotion forecast names its
#               approval request in free text, so a section about *calibration*
#               was pinning an identifier, and any future slice that mints one
#               id earlier would produce a spurious diff here. ADR-017 excludes
#               volatile ids; this was one wearing a sentence as a disguise.
#           **`balances` is identical across every account in every book.** An
#           experiment is a record and a derivation; it moves no money, and the
#           revenue it now names was already being posted.
#   20 -> 21 (experiment attribution for metered ops; §2.6, §1.1, A6; ADR-044).
#           Version 20's own note above says `human_minutes` is null because
#           "`resource_usage` carries no experiment_id". That was true of the
#           column and false of the fact: `resource_usage.reservation_id` is NOT
#           NULL and a reservation has carried `experiment_id` since migration
#           0001, so the join always reached. What was missing was the stamp —
#           `tools` and `external_actions` opened RESOURCE reservations without
#           one while the gateway threaded it.
#           (a) **`experiments.human_minutes`**: `null` -> `0` on the rung-7 row
#               and `null` -> `58` on the rung-1 row. The `0` is not a
#               regression into the trap version 20 avoided — it is now a
#               *measurement*: no external action was claimed while that
#               experiment ran, so zero minutes is a true statement rather than
#               a declined one. The 58 is step 19's three completed actions
#               (34 + 4 + 20 reported), which matches `human_minutes.reported`
#               colony-wide because every one of them was claimed while the
#               rung-1 experiment was open.
#           (b) **`experiments.subsidised_human_minutes` (new)**: `0` and `4`.
#               §1.1 subtracts shadow-priced human labour *and* founder subsidy
#               to get autonomy-adjusted profit, and `external_actions` bills a
#               Cell only up to its channel ceiling — so summing the billed
#               `quantity` alone would report the colony's human cost as
#               *smaller* the more of it a person absorbed unpaid. Both halves
#               are pinned; the total is billed + subsidised.
#           (c) **`experiments.resource_spend`**: `0` -> `540` on the rung-1
#               row. **This is the bug the slice was actually fixing.** The
#               shadow-cost dimension reads the same reservations through the
#               ledger, so it was reporting a definite figure with every tool
#               call and every human minute missing from it. An abstaining
#               dimension is visible; an undercounting one is not.
#           (d) **`model_calls` and `resource_usage`**: four rows gain exactly
#               one input token. §15's experiment section renders "Spent so far:
#               ... {resource_spend} RESOURCE" to the Cell, which read `0` on
#               every wake before this and now reads the real figure; the string
#               grows two characters and `providers._estimate_tokens` is 2
#               chars/token, so the arithmetic is exact. The four are the
#               deliberations that ran after the first tool call was metered
#               under the experiment — the Cell can now see what its own work
#               costs, which is what that section's docstring says it is for.
#           (e) **`experiments.resource_spend`**: `540` -> `550`, the second
#               half of the same fix. A wake never named the experiment it was
#               thinking about, so `deliberation` called the gateway with no
#               attribution and hardcoded `experiment_id=None` on every forecast
#               a Cell registered. Five of thirteen model calls now carry it —
#               the five that ran while an experiment was open. §2.6's "real
#               cash consumed" stays 0 here only because the golden provider is
#               priced at zero; on a paid provider this was the report's largest
#               hole, and the least visible, because 0 is a plausible figure for
#               an experiment that has not spent yet.
#           (f) **`deliberations.context_tokens`** +1 to +2 on four rows, and
#               `model_calls`/`resource_usage` follow, for the same reason as
#               (d): the RESOURCE figure rendered into §15's experiment section
#               grew a digit.
#           (g) **`experiments.resolved_predictions` /
#               `unresolved_predictions` (new)**: `0`/`0` on both. §2.6's sixth
#               dimension was derived but never pinned. It stays 0 because the
#               scenario's five in-experiment deliberations propose no
#               forecasts — the prediction half of (e) is covered by
#               `tests/test_deliberation.py` rather than here, and this pin is
#               what will notice if a future scenario starts exercising it.
#           **`balances` is identical across every account in every book**, and
#           USD_REAL is untouched. Attribution decides which experiment a cost is
#           *reported* under; it moves no money and posts no entry. The RESOURCE
#           charge is unchanged too — the extra input tokens move the recorded
#           raw `quantity` and round to the same minor units.
EXPECTATION_VERSION = 21

# Fixed instants. The scenario must never read the wall clock for anything
# that reaches the snapshot, so these are constants rather than `now()`.
SCENARIO_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
SCENARIO_RESERVATION_EXPIRY = datetime(2030, 1, 1, tzinfo=timezone.utc)

# Fixed seed for ids.py (see module docstring) — every raw uuid the scenario
# generates, not just its semantic snapshot, is reproducible run to run.
GOLDEN_RUN_ID_SEED = 20260101

# The mock provider's reply for the scenario's deliberation (step 13). A fixed
# input, not a model's choice: what the golden run pins is the loop's handling
# of a reply, not a model's ability to produce one.
GOLDEN_PROPOSAL_REPLY = json.dumps(
    {
        "kind": "experiment",
        "summary": "golden-run probe of the synthetic market",
        "rationale": "fixed scenario proposal; exists to pin the loop, not to be clever",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 25,
        "predictions": [
            {
                "claim": "golden-run probe returns a measurable signal",
                "probability": 0.55,
                "horizon_days": 30,
            }
        ],
    },
    sort_keys=True,
)


# The commercial Cell's reply for the §25 promotion step. A spend request,
# because only a spend request allocates capital — an approved experiment is a
# human saying "yes, think about that", not a capital decision.
GOLDEN_SPEND_REQUEST_REPLY = json.dumps(
    {
        "kind": "spend_request",
        "summary": "golden-run capped purchase of a sample dataset",
        "rationale": "fixed scenario spend request; exists to pin rung 7, not to be clever",
        "risk_tier": "MEDIUM",
        "estimated_cost_minor_units": 30,
        # Three forecasts, because §25.2's read-back needs an *observed* outcome
        # to compare against and `outcome.MIN_RESOLVED_FOR_A_VERDICT` will not
        # state a verdict on fewer. Registered here, before the request is
        # approved, so they are open at the instant the capital moves — which is
        # the only set the read-back is allowed to judge on.
        "predictions": [
            {
                "claim": f"golden-run purchase clears checkpoint {index}",
                "probability": 0.8,
                "horizon_days": 30,
            }
            for index in range(3)
        ],
    },
    sort_keys=True,
)


# The tool request for the §19 step. `predictions: []` on purpose: the read-back
# above is scoped by claim text, and a forecast here would put a fourth claim in
# cell#4's register for a reader to mistake for part of the funding evidence.
GOLDEN_TOOL_REQUEST_REPLY = json.dumps(
    {
        "kind": "tool_request",
        "summary": "golden-run read of a fixed public page",
        "rationale": "fixed scenario tool request; exists to pin rung 4, not to be clever",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 0,
        "predictions": [],
        "tool_request": {
            "tool": "http_get",
            "arguments": {"url": "https://golden.test/pricing"},
        },
    },
    sort_keys=True,
)


# The wake *after* the fetch. Deliberately a strategy rather than another tool
# request: what is being pinned is that the taint flag propagates, and reusing
# `tool_request` would confuse "the Cell read something" with "the Cell wants to
# read something else".
def _post_fetch_reply(tool_call_id: str) -> str:
    """Built per-run rather than fixed, because the artifact must cite the tool
    call that actually ran. A hard-coded source id would pin the *shape* of
    provenance while proving nothing about whether rights really propagate."""
    return json.dumps(
        {
            "kind": "strategy",
            "summary": "golden-run strategy note written after reading a page",
            "rationale": (
                "fixed scenario; exists to pin that a proposal made from a context "
                "containing external content is flagged as such"
            ),
            "risk_tier": "LOW",
            "estimated_cost_minor_units": 0,
            "predictions": [],
            "artifact": {
                "kind": "report",
                "title": "golden-run write-up of a fetched page",
                "content": "Fixed scenario artifact. Derived from one fetched page.",
                "source_tool_call_ids": [tool_call_id],
            },
        },
        sort_keys=True,
    )


# The §21 external-action request. Built per-run because it delivers the
# artifact the scenario actually produced — a hard-coded id would pin the shape
# of delivery while proving nothing about the export gate in front of it.
def _external_action_reply(
    artifact_id: str, *, intent: str, channel: str = "email"
) -> str:
    """Note what is *not* here: anyone's name. A Cell names a channel and a
    purpose; the operator names the counterparty at claim time and the kernel
    stores a salted hash of it (§16.3). A reply carrying an address would fail
    `proposal.parse` outright, which is the point of the tripwire."""
    return json.dumps(
        {
            "kind": "external_action",
            "summary": "golden-run outreach on a fixed channel",
            "rationale": (
                "fixed scenario external action; exists to pin §21.2's registry "
                "and the refusals in front of it"
            ),
            # HIGH because the kernel assesses every external action HIGH and
            # the context now says so. A MEDIUM claim here would trip
            # `understated_risk` on every single external action ever proposed,
            # which is a signal that fires unconditionally and therefore
            # carries no information — the §23.4 detections are only worth
            # having while they distinguish something.
            "risk_tier": "HIGH",
            "estimated_cost_minor_units": 0,
            "predictions": [],
            "external_action": {
                "channel": channel,
                "intent": intent,
                "artifact_id": artifact_id,
            },
        },
        sort_keys=True,
    )


# The Auditor's reply for the §23.2 step. A `concern` at p=0.3 — coherent with
# its verdict, which the kernel checks: a flag that quietly predicts success
# would be a costless flag (§10.4).
GOLDEN_AUDIT_REPLY = json.dumps(
    {
        "verdict": "concern",
        "summary": (
            "the Cell claimed LOW and the kernel assessed MEDIUM, and its "
            "register still shows unresolved claims; fixed scenario text"
        ),
        "probability": 0.3,
    },
    sort_keys=True,
)


class GoldenRunError(Exception):
    pass


# --- the scenario ------------------------------------------------------------


def run_scenario(conn: sqlite3.Connection) -> None:
    """Drive a fixed sequence through the kernel, exercising every Phase 1
    subsystem: configuration, ledger, births under carrying capacity, the
    reservation FSM (settle / partial-settle / release / execution_unknown),
    the real-spend breaker, resource metering, the full Cell lifecycle
    including a coroner report, the event inbox/outbox including a poison
    event, and the simulated clock.

    Ordered and fully specified: no randomness, no wall-clock reads, no
    input from outside this function — every id the kernel generates while
    this runs is seeded (`GOLDEN_RUN_ID_SEED`) too, so the whole run,
    not just its semantic snapshot, is reproducible run to run.
    """
    with ids.seeded(GOLDEN_RUN_ID_SEED):
        _run_scenario_body(conn)


class _GoldenFetcher:
    """Deterministic, offline. A golden run must never touch a network.

    The same argument as the mock provider being priced at zero: a replay that
    reached out would make the run depend on somebody else's uptime, and a
    replay that started *billing* someone would be the worst regression this
    file could miss. The §20.1 metadata is fixed too, so a change in what the
    kernel records about data rights shows up as a diff rather than as noise.
    """

    def fetch(self, url: str, *, max_bytes: int):
        return tool_registry.FetchResult(
            text="Golden fixture page. Widgets are listed at 4 units.",
            http_status=200,
            source=url,
            licence="unknown",
            permitted_uses="review only; no storage, redistribution or training",
            commercial_use="unknown",
            contains_personal_data=False,
        )


def _run_scenario_body(conn: sqlite3.Connection) -> None:
    # 1. Configuration — set explicitly rather than relying on defaults, so
    #    a later change to DEFAULT_* constants doesn't silently alter the
    #    golden run's meaning.
    population.set_limits_if_absent(
        conn,
        PopulationLimits(
            max_living_cells=10,
            max_active_cells=10,
            max_parallel_experiments=20,
            max_births_per_epoch=25,
            # Deliberately above the colony.yaml default of 0.20: this
            # scenario runs a 4-Cell colony, where any second-generation
            # Cell is already 40% of the living population. See lineage.py
            # on why a small colony can't reproduce under a tight cap.
            max_lineage_population_fraction=0.50,
        ),
    )
    real_spend_breaker.set_limits(
        conn,
        RealSpendLimits(
            per_request_minor_units=25,
            per_hour_minor_units=100,
            per_day_minor_units=500,
            per_month_minor_units=5000,
            max_concurrent_reserved_minor_units=200,
            provider_limits={},
        ),
    )
    clock.initialize_if_absent(conn, mode=ClockMode.PAUSED, start_at=SCENARIO_EPOCH)
    #    Anchor epoch zero explicitly, at the same fixed instant. §9.2's
    #    `max_births_per_epoch` counts against it, and an unanchored colony
    #    reports epoch 0 forever — which would make `born_in_epoch` below a
    #    column of zeroes that pins nothing.
    clock.configure_epochs_if_absent(conn, genesis=SCENARIO_EPOCH)

    # 2. Seed capital into each book.
    for book, currency, amount in (
        (Book.USD_SIM, "USD", 100_000),
        (Book.USD_REAL, "USD", 10_000),
        (Book.RESOURCE, "RESOURCE", 50_000),
    ):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="colony_seed_capital",
            idempotency_key=f"golden:seed:{book.value}",
            description=f"golden-run seed capital ({book.value})",
            entries=[
                EntrySpec(account_id="external_capital", amount_minor_units=-amount),
                EntrySpec(account_id="seed_bank", amount_minor_units=amount),
            ],
            effective_at_utc=SCENARIO_EPOCH,
        )

    # 3. Births — one per book, in a fixed order (this order defines the
    #    cell#N aliases the snapshot uses).
    commercial = lifecycle.create_cell(
        conn, cell_type=CellType.COMMERCIAL, budget_minor_units=5_000,
        book=Book.USD_SIM, idempotency_key="golden:birth:commercial",
    )
    explorer = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=1_000,
        book=Book.USD_REAL, idempotency_key="golden:birth:explorer",
    )
    builder = lifecycle.create_cell(
        conn, cell_type=CellType.BUILDER, budget_minor_units=8_000,
        book=Book.RESOURCE, idempotency_key="golden:birth:builder",
    )
    # Seeded with real §16.2 content, and the only founder that is: the run
    # then pins both halves of inheritance against each other — this Cell's
    # content, and a child below that must carry it forward. A `risk_class` is
    # deliberately included and deliberately *not* LOW, because the claim folds
    # into approval's assessed tier with `max` and a LOW one would be
    # indistinguishable from the claim being ignored entirely.
    auditor_cell = lifecycle.create_cell(
        conn, cell_type=CellType.AUDITOR, budget_minor_units=2_000,
        book=Book.USD_SIM, idempotency_key="golden:birth:auditor",
        genome_content={
            "market": "colony-internal oversight",
            "problem": "requests are reviewed without an independent record",
            "workflow": "read the request, stake a probability, record it",
            "risk_class": "HIGH",
        },
    )

    # The other birth path: a child of the auditor, funded from the auditor's
    # own cash rather than a colony account, carrying a mutated genome so the
    # run pins a real genome-parentage edge as well as a cell-parentage one
    # (SPEC.md §26 names the "expected lineage tree" as golden-run content).
    #    One epoch turns before this birth, on purpose: §9.2's cap counts per
    #    epoch, so a snapshot where every Cell was born in epoch 0 would pass
    #    just as happily against a kernel that stamped a constant. The clock is
    #    paused, so the advance is exact and nothing else in the scenario moves
    #    with it — reservations expire in 2030 and no tick runs here.
    clock.advance(conn, timedelta(seconds=clock.DEFAULT_EPOCH_DURATION_SECONDS))
    auditor_child = lineage.reproduce(
        conn, parent_cell_id=auditor_cell.cell_id, budget_minor_units=500,
        idempotency_key="golden:birth:auditor-child",
        mutation={"acquisition_channel": "golden-child-channel-v2"},
        mutation_operator="golden_run_mutation",
    )

    # 4. Reservation FSM — every settlement shape the kernel supports.
    full = reservations.request(
        conn, cell_id=commercial.cell_id, book=Book.USD_SIM, currency="USD",
        maximum_amount=1_200, expires_at=SCENARIO_RESERVATION_EXPIRY,
        idempotency_key="golden:res:full",
    )
    reservations.settle(
        conn, full.reservation_id, settled_amount=1_200,
        destination_account_id="external_expense",
    )

    partial = reservations.request(
        conn, cell_id=commercial.cell_id, book=Book.USD_SIM, currency="USD",
        maximum_amount=900, expires_at=SCENARIO_RESERVATION_EXPIRY,
        idempotency_key="golden:res:partial",
    )
    reservations.settle(
        conn, partial.reservation_id, settled_amount=350,
        destination_account_id="external_expense",
    )
    reservations.release(conn, partial.reservation_id)

    released = reservations.request(
        conn, cell_id=auditor_cell.cell_id, book=Book.USD_SIM, currency="USD",
        maximum_amount=400, expires_at=SCENARIO_RESERVATION_EXPIRY,
        idempotency_key="golden:res:released",
    )
    reservations.release(conn, released.reservation_id)

    # Left open in execution_unknown on purpose: Charter C7 says an unknown
    # external operation is reconciled, never auto-released, so the golden
    # run pins that funds stay committed.
    stuck = reservations.request(
        conn, cell_id=auditor_cell.cell_id, book=Book.USD_SIM, currency="USD",
        maximum_amount=250, expires_at=SCENARIO_RESERVATION_EXPIRY,
        idempotency_key="golden:res:stuck",
        external_operation_type="mock_external_call",
        external_operation_id="golden-ext-1",
    )
    reservations.mark_execution_unknown(conn, stuck.reservation_id)

    # 5. Real-spend path (Charter C5) — two requests inside the configured
    #    caps, one settled, one left reserved as standing exposure.
    real_settled = reservations.request(
        conn, cell_id=explorer.cell_id, book=Book.USD_REAL, currency="USD",
        maximum_amount=20, expires_at=SCENARIO_RESERVATION_EXPIRY,
        idempotency_key="golden:res:real-settled",
    )
    reservations.settle(
        conn, real_settled.reservation_id, settled_amount=20,
        destination_account_id="external_expense",
    )
    reservations.request(
        conn, cell_id=explorer.cell_id, book=Book.USD_REAL, currency="USD",
        maximum_amount=15, expires_at=SCENARIO_RESERVATION_EXPIRY,
        idempotency_key="golden:res:real-open",
    )

    # 6. Resource metering (Amendment A6, Charter C4) against a RESOURCE
    #    reservation, settled for exactly what was metered.
    metered = reservations.request(
        conn, cell_id=builder.cell_id, book=Book.RESOURCE, currency="RESOURCE",
        maximum_amount=3_000, expires_at=SCENARIO_RESERVATION_EXPIRY,
        idempotency_key="golden:res:metered",
    )
    for suffix, resource_type, quantity, minor_units in (
        ("input", ResourceType.INPUT_TOKENS, 4_000, 800),
        ("output", ResourceType.OUTPUT_TOKENS, 1_200, 600),
        ("calls", ResourceType.MODEL_CALLS, 6, 300),
        ("cpu", ResourceType.CPU_SECONDS, 45, 150),
    ):
        resource_metering.record_usage(
            conn, cell_id=builder.cell_id, reservation_id=metered.reservation_id,
            resource_type=resource_type, quantity=quantity, minor_units=minor_units,
            idempotency_key=f"golden:usage:{suffix}",
        )
    reservations.settle(
        conn, metered.reservation_id,
        settled_amount=resource_metering.total_minor_units(conn, metered.reservation_id),
        destination_account_id="infrastructure_reserve",
    )

    # 7. Lifecycle — every remaining transition, ending in a coroner report.
    lifecycle.sleep(conn, builder.cell_id)
    lifecycle.wake(conn, builder.cell_id)
    lifecycle.sleep(conn, auditor_cell.cell_id)

    lifecycle.quarantine(
        conn, explorer.cell_id, reason="golden-run policy violation",
        linked_finding={"finding": "golden-run synthetic finding"},
    )
    lifecycle.clear_quarantine(conn, explorer.cell_id, to_status=CellStatus.ALIVE)

    # 7b. An experiment the death interrupts (§9.2, §10.5, §25.1; ADR-043).
    #     Started at rung 7 — §25.1's "tiny capped live experiment", the rung
    #     `promotion.py` funds — and never concluded, because its Cell dies two
    #     statements later. **Two things are pinned by that.** The coroner report
    #     gains a `stage_reached` and a link to the experiment, which §10.5
    #     requires of every death and which was `null` in every prior expectation
    #     version. And the experiment is left `abandoned`, never `concluded`: it
    #     reached no answer, and a colony that recorded one would be filing a
    #     finding nobody made. A kernel that failed to release it would leak the
    #     §9.2 slot on every death, with nothing anywhere explaining the refusals
    #     that followed.
    experiments.start(
        conn,
        cell_id=commercial.cell_id,
        hypothesis="fixed scenario: a capped live experiment the Cell does not survive",
        ladder_rung=7,
        expected_cost_minor_units=25,
    )

    lifecycle.kill(
        conn, commercial.cell_id,
        cause_of_death="stage budget exhausted",
        final_hypotheses=["golden-run hypothesis A", "golden-run hypothesis B"],
        coroner_enricher=experiments.ExperimentCoroner(),
    )

    # 8. Events. Distinct priorities keep next_ready's order reproducible —
    #    see the module docstring on A5's uuid tie-break.
    for suffix, priority, payload in (
        ("alpha", 10, {"step": 1}),
        ("beta", 20, {"step": 2}),
        ("gamma", 30, {"step": 3}),
    ):
        events.enqueue(
            conn, event_type=f"golden_{suffix}", source="golden_run",
            priority=priority, dedupe_key=f"golden:event:{suffix}",
            payload=payload, available_at=SCENARIO_EPOCH,
        )

    def handler(handler_conn, event):
        ledger._write_transaction(
            handler_conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="event_side_effect",
            idempotency_key=f"golden:event_effect:{event.event_type}",
            description=f"golden-run side effect for {event.event_type}",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-100),
                EntrySpec(account_id="colony_treasury", amount_minor_units=100),
            ],
            effective_at_utc=SCENARIO_EPOCH,
        )
        return []

    ready = events.next_ready(conn, now=SCENARIO_EPOCH)
    for event in ready:
        # Processed twice each: at-least-once redelivery must be a no-op the
        # second time (Charter C6), which the snapshot's balances pin down.
        events.process_event(conn, event.event_id, handler)
        events.process_event(conn, event.event_id, handler)

    # A poison event that dead-letters and quarantines its Cell (§17.3).
    poison = events.enqueue(
        conn, event_type="golden_poison", source="golden_run", priority=40,
        dedupe_key="golden:event:poison", available_at=SCENARIO_EPOCH,
    )

    def failing_handler(handler_conn, event):
        raise RuntimeError("golden-run poison event")

    for _ in range(3):
        try:
            events.process_event(
                conn, poison.event_id, failing_handler,
                max_attempts=3, cell_id=auditor_cell.cell_id,
            )
        except RuntimeError:
            pass

    # Outbox: staged by a handler, then dispatched.
    staged = events.enqueue(
        conn, event_type="golden_producer", source="golden_run", priority=50,
        dedupe_key="golden:event:producer", available_at=SCENARIO_EPOCH,
    )

    def producing_handler(handler_conn, event):
        from .models import OutboxEventSpec

        return [
            OutboxEventSpec(
                event_type="golden_produced", source="golden_handler",
                priority=60, dedupe_key="golden:outbox:produced",
                payload={"from": event.event_type},
            )
        ]

    events.process_event(conn, staged.event_id, producing_handler)
    events.dispatch_outbox(conn, lambda outbox_event: None)

    # 9. Model gateway (§24). Runs on the mock provider, which is priced at
    #    zero and is deterministic — so this step exercises the whole
    #    reserve -> call -> settle -> meter -> mirror path in CI without any
    #    external dependency and without spending a cent (§30.1 "mock before
    #    paid APIs"). The paid provider is deliberately unreachable from the
    #    golden run: a replay that could bill someone is not a replay.
    #    The explorer is the USD_REAL-funded Cell, but a model call needs
    #    balances in three books — USD_REAL for the provider charge, RESOURCE
    #    for A6 token metering, USD_SIM for the §2.4 mirror — so it is topped
    #    up first. That a Cell needs all three to make one call is itself
    #    worth pinning.
    for book, currency, amount in (
        (Book.RESOURCE, "RESOURCE", 5_000),
        (Book.USD_SIM, "USD", 400),
    ):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="cell_funding",
            idempotency_key=f"golden:gateway-funding:{book.value}",
            effective_at_utc=SCENARIO_EPOCH,
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
                EntrySpec(
                    account_id=f"cell:{explorer.cell_id}:cash",
                    amount_minor_units=amount,
                    cell_id=explorer.cell_id,
                ),
            ],
        )

    gateway.call_model(
        conn,
        cell_id=explorer.cell_id,
        provider=providers.MockProvider(reply="golden run reply"),
        request=providers.ModelRequest(
            model="mock-1",
            messages=({"role": "user", "content": "golden run prompt"},),
            max_tokens=64,
        ),
        idempotency_key="golden:model_call:1",
    )

    # 10. Provider-invoice reconciliation (§24.1, §3.6). The invoice confirms
    #     the estimate — for the mock provider the honest figure is zero,
    #     which is also what the pricing table predicted — so this posts no
    #     adjustment and moves no money. That is the point twice over: it
    #     pins the §24.1 metadata path (`reconciled_micro_usd`,
    #     `reconciled_at_utc`, the audit event) *and* it preserves the
    #     property that a golden replay never moves USD_REAL. The
    #     adjustment-posting paths, where the sign matters, are covered by
    #     tests/test_reconciliation.py rather than here, because pinning them
    #     would mean giving up that property for coverage the unit tests
    #     already provide.
    reconciliation.reconcile_model_call(
        conn,
        gateway.get_model_call_by_idempotency_key(conn, "golden:model_call:1").model_call_id,
        invoiced_micro_usd=0,
        source="golden-run-invoice",
    )

    # 11. Prediction register (§8.5, Amendment A14). Two predictions, resolved
    #     opposite ways, so the snapshot pins both scoring rules and both
    #     outcomes rather than only the flattering case. A third is left
    #     deliberately unresolved: `unresolved` appearing in the snapshot is
    #     what stops a future change from silently dropping the anti-gaming
    #     surface, which a register of only-resolved predictions would.
    #     `resolves_by` is derived from SCENARIO_EPOCH, never `now()`, so
    #     nothing here reads the wall clock.
    for suffix, claim, probability, outcome in (
        ("hit", "golden-run claim A", 0.8, True),
        ("miss", "golden-run claim B", 0.6, False),
    ):
        registered = prediction.register(
            conn,
            cell_id=builder.cell_id,
            claim=claim,
            probability=probability,
            resolves_by=SCENARIO_RESERVATION_EXPIRY,
            idempotency_key=f"golden:prediction:{suffix}",
        )
        prediction.resolve(
            conn, registered.prediction_id, occurred=outcome, source="golden-run-outcome"
        )
    prediction.register(
        conn,
        cell_id=builder.cell_id,
        claim="golden-run claim C (left open on purpose)",
        probability=0.5,
        resolves_by=SCENARIO_RESERVATION_EXPIRY,
        idempotency_key="golden:prediction:open",
    )

    # 13. The agent loop (§15, §17.2, §25.1). A wake event is enqueued and
    #     drained, so this covers the event path end to end as well — the
    #     inbox's first real producer *and* consumer.
    #
    #     The mock provider returns a fixed, valid proposal, which is what
    #     makes this deterministic: the reply is an input to the scenario, not
    #     a model's choice. What the run actually pins is everything around it
    #     — context assembly staying inside its budget, strict parsing, the
    #     proposal and its prediction committing together, and the wake event
    #     ending up processed.
    deliberation.enqueue_wake(
        conn,
        cell_id=explorer.cell_id,
        wake_reason=deliberation.WAKE_SCHEDULED_RESEARCH,
        dedupe_key="golden:wake:1",
        available_at=SCENARIO_EPOCH,
    )
    #     The §23 queue is wired in, because it is now part of what happens
    #     when a Cell proposes: both the CLI and the scheduler pass this sink,
    #     so a golden run without it would pin a path the colony no longer
    #     takes. The scenario's reply claims LOW on a 25-minor-unit experiment,
    #     which the kernel independently assesses as MEDIUM — so this also pins
    #     §23.5's central guarantee, that a Cell cannot set the tier it is
    #     reviewed at.
    deliberation.run_ready_wakes(
        conn,
        provider=providers.MockProvider(reply=GOLDEN_PROPOSAL_REPLY),
        model="mock-1",
        now=SCENARIO_RESERVATION_EXPIRY,
        proposal_sink=approval.QueueSink(),
    )

    # 14. §25.1's ladder, rung 7 — the colony's core loop closing (§31:
    #     "... -> allocate capital -> scale, mutate, collaborate, sleep, or
    #     die"). The proposal recorded above is reviewed, approved, and its
    #     grant allocated, which funds the Cell from the promotion pool and
    #     wakes it under §17.2's "capital allocation" reason.
    #
    #     Pinned here because this is the only path in the kernel where a
    #     Cell's own output leads, through a human, to money moving into its
    #     account — and because the pool is a USD_SIM pot: an allocation that
    #     ever moved USD_REAL in a replay would be the worst regression this
    #     file could miss.
    #     Run on the auditor's *child* rather than the explorer, and the reason
    #     is the guard itself: the explorer is a USD_REAL Cell, and allocating
    #     to it is refused without §27.1's `autonomy.real_spending` — which the
    #     scenario must never enable, since a replay that started moving real
    #     money is the worst regression this file could miss. The refusal is
    #     asserted below rather than worked around.
    promotion.fund_pool(
        conn,
        book=Book.USD_SIM,
        amount_minor_units=500,
        idempotency_key="golden:pool:usd_sim",
    )
    #     §15.4: a Cell pays for its own thinking, so the child needs a balance
    #     in the books the gateway reserves before it can deliberate at all.
    #     Both are transfers, not spend — the mock provider is priced at zero.
    for fund_book, fund_currency, fund_amount in (
        (Book.USD_REAL, "USD", 20),
        (Book.RESOURCE, "RESOURCE", 2_000),
    ):
        ledger.post_transaction(
            conn,
            book=fund_book,
            currency=fund_currency,
            transaction_type="cell_funding",
            idempotency_key=f"golden:fund:auditor-child:{fund_book.value}",
            description="fund the auditor's child so it can deliberate",
            entries=[
                EntrySpec(
                    account_id="seed_bank",
                    amount_minor_units=-fund_amount,
                    cell_id=auditor_child.cell_id,
                ),
                EntrySpec(
                    account_id=f"cell:{auditor_child.cell_id}:cash",
                    amount_minor_units=fund_amount,
                    cell_id=auditor_child.cell_id,
                ),
            ],
        )
    #     §23.2's independent Auditor summary, which had been reported
    #     unavailable since ADR-027 because nothing could produce one.
    #
    #     The reviewer is the auditor's child — an AUDITOR by inheritance, of a
    #     different lineage from the explorer whose request it reviews. Both
    #     halves are pinned on purpose. The colony's *other* Auditor is
    #     quarantined by the poison event in step 11 and is refused here, which
    #     is the §18.2 guard doing its job inside the replay rather than only in
    #     a unit test; and a same-lineage reviewer would be refused too.
    #
    #     The audit costs a model call the Auditor pays for (§15.4) — §10.4's
    #     governance overhead becoming real and non-zero for the first time. It
    #     advises and never blocks: the explorer's request stays pending, and
    #     the approval below is of a different request entirely.
    auditor.audit_request(
        conn,
        request_id=next(
            r.request_id for r in approval.queue(conn) if r.cell_id == explorer.cell_id
        ),
        auditor_cell_id=auditor_child.cell_id,
        provider=providers.MockProvider(reply=GOLDEN_AUDIT_REPLY),
        model="mock-1",
        idempotency_key="golden:audit:explorer",
    )

    deliberation.deliberate(
        conn,
        cell_id=auditor_child.cell_id,
        provider=providers.MockProvider(reply=GOLDEN_SPEND_REQUEST_REPLY),
        wake_key="golden:wake:auditor-child",
        wake_reason=deliberation.WAKE_CAPITAL_ALLOCATION,
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    auditor_request = next(
        r for r in approval.queue(conn) if r.cell_id == auditor_child.cell_id
    )
    auditor_grant = approval.approve(
        conn,
        request_id=auditor_request.request_id,
        decided_by="golden-operator",
        reason="fixed scenario approval; exists to pin the loop",
    )
    promotion.allocate(
        conn,
        grant_id=auditor_grant.grant_id,
        allocated_by="golden-operator",
        reason="fixed scenario allocation; exists to pin rung 7",
    )

    # 15. §25.2's read-back — the other half of the promotion record, which
    #     cannot exist at allocation time because it needs outcomes.
    #
    #     Resolving all three forecasts *after* the allocation is the point of
    #     the step: they were open when the capital moved, so they are the only
    #     evidence the assessment is allowed to judge on, and resolving every
    #     one of them is what keeps the verdict out of `evidence_withheld`. A
    #     replay where the assessment silently became decidable on a
    #     self-selected subset would be a real regression and an easy one to
    #     miss, since the score itself would look excellent.
    #
    #     Nothing here promotes anything. The snapshot pins a *verdict*, and if
    #     a later slice ever makes a verdict move money or end a Cell, this
    #     section is where the diff shows up.
    #     Scoped to the spend request's own checkpoints, and the scope matters.
    #     cell#4 is both the proposer here and the Auditor above, so its
    #     register holds two different kinds of claim: forecasts about its own
    #     work, and a flag it raised about someone else's request. §8.5 gives
    #     them one namespace, so a naive "resolve everything this Cell
    #     predicted" would fold an audit of the *explorer* into the §25.2
    #     read-back of cell#4's own funding — see FUTURE_BUILD_HOOKS. The flag
    #     is deliberately left open, which also covers the case where a funding
    #     forecast is still outstanding but not yet overdue.
    for index, open_forecast in enumerate(
        conn.execute(
            "SELECT prediction_id FROM prediction_register "
            " WHERE cell_id = ? AND claim LIKE 'golden-run purchase clears checkpoint%'"
            " ORDER BY rowid",
            (auditor_child.cell_id,),
        ).fetchall()
    ):
        prediction.resolve(
            conn,
            open_forecast["prediction_id"],
            occurred=True,
            source=f"golden-run observation {index}",
        )
    # 16. The tool surface (§19, §25.1 rung 4; ADR-034). The Cell proposes a
    #     read-only fetch, a human approves it, and the grant runs the tool —
    #     the same proposal -> review -> grant path capital already uses, which
    #     is the point: nothing new decides anything.
    #
    #     Both gates are opened here rather than in setup, so the snapshot's
    #     `egress_allowlist` and `autonomy` sections are non-empty and a
    #     regression that shipped either open by default is visible as a diff
    #     against a colony that starts closed.
    tools.allow_domain(
        conn,
        domain="golden.test",
        added_by="golden-operator",
        reason="fixed scenario; the fetcher is deterministic and offline",
    )
    tools.set_autonomy(conn, flag="public_web_read", enabled=True, changed_by="golden-operator")

    deliberation.deliberate(
        conn,
        cell_id=auditor_child.cell_id,
        provider=providers.MockProvider(reply=GOLDEN_TOOL_REQUEST_REPLY),
        wake_key="golden:wake:tool-request",
        wake_reason=deliberation.WAKE_SCHEDULED_RESEARCH,
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    tool_request = next(
        r
        for r in approval.queue(conn)
        if r.cell_id == auditor_child.cell_id and r.status == approval.RequestStatus.PENDING
    )
    tool_grant = approval.approve(
        conn,
        request_id=tool_request.request_id,
        decided_by="golden-operator",
        reason="fixed scenario approval; exists to pin rung 4",
    )
    tool_call = tools.execute_grant(
        conn,
        grant_id=tool_grant.grant_id,
        executed_by="golden-operator",
        reason="fixed scenario tool call",
        fetcher=_GoldenFetcher(),
    )

    #     One more wake, *after* the fetch, and it is the point of the step
    #     rather than a flourish. §18/§19.4's taint flag is only meaningful if
    #     the snapshot contains both values: a column that is uniformly false
    #     passes just as happily against a kernel that hardcodes false, which is
    #     exactly how ADR-031's `born_in_epoch` nearly shipped untested. This
    #     Cell's context now carries an UNTRUSTED_EXTERNAL observation, so its
    #     next proposal must come back flagged.
    deliberation.deliberate(
        conn,
        cell_id=auditor_child.cell_id,
        provider=providers.MockProvider(reply=_post_fetch_reply(tool_call.tool_call_id)),
        wake_key="golden:wake:after-tool-result",
        wake_reason=deliberation.WAKE_TOOL_RESULT,
        model="mock-1",
    )

    # 18. The artifact store (§20, §11.3, §19.3; ADR-035). The write-up above
    #     cites the fetched page, so its §20.1 rights are *inherited*, not
    #     declared: the page is `commercial_use: unknown`, so the artifact is
    #     too. Both export gates are then exercised against that one artifact —
    #     non-commercial passes, commercial is refused — which is the pair that
    #     makes the §20.2 laundering path visible in a replay. A scenario that
    #     only exported successfully would pass identically against a gateway
    #     that refused nothing.
    golden_artifact = conn.execute(
        "SELECT artifact_id FROM artifacts ORDER BY rowid LIMIT 1"
    ).fetchone()["artifact_id"]

    try:
        artifacts.export(
            conn,
            artifact_id=golden_artifact,
            exported_by="golden-operator",
            reason="fixed scenario commercial export; must be refused",
            commercial=True,
        )
        raise AssertionError(
            "§20.2 should have refused a commercial export of unknown-rights content"
        )
    except artifacts.ExportRefused:
        pass

    artifacts.export(
        conn,
        artifact_id=golden_artifact,
        exported_by="golden-operator",
        reason="fixed scenario non-commercial export; exists to pin rung 8 review",
    )

    # 18b. Rights an operator *establishes* (§20.1/§20.2/§3.6; ADR-041). The
    #      refusal above is the state the colony shipped in: rights could only
    #      ever tighten, so an artifact built on a fetched page was `unknown`
    #      forever and `real_commerce` could be opened and still sell nothing.
    #
    #      **The attestation is made after the artifact exists, deliberately.**
    #      What a replay has to pin is that establishing a position reaches
    #      backwards *without rewriting anything*: the stored row still reads
    #      `unknown` — it is the record of what was known when the artifact was
    #      made (§3.6) — while the gate that was refusing now opens. An
    #      implementation that cascaded the new position into the artifacts
    #      table passes the second assertion and fails the first, and one that
    #      read the stored column at the gate does the reverse.
    rights.attest(
        conn,
        subject_kind=rights.SUBJECT_DOMAIN,
        subject="golden.test",
        licence="CC-BY-4.0",
        permitted_uses="redistribution and resale with attribution",
        commercial_use="permitted",
        basis="fixed scenario; the publisher's licensing page states CC-BY-4.0",
        attested_by="golden-operator",
        now=SCENARIO_EPOCH,
    )

    if conn.execute(
        "SELECT commercial_use FROM artifacts WHERE artifact_id = ?", (golden_artifact,)
    ).fetchone()["commercial_use"] != "unknown":
        raise AssertionError(
            "§3.6: an attestation must not rewrite what an artifact was born with"
        )
    artifacts.check_exportable(conn, golden_artifact, commercial=True)

    #     Amendment A3's `ledger_entries.artifact_id`, populated for the first
    #     time. USD_SIM deliberately: a golden run must never move USD_REAL, and
    #     revenue is the one verb that brings money *in*.
    #
    #     **The revenue is now earned under an experiment** (ADR-043), which is
    #     what makes §2.6's report non-trivial in a replay: a report over an
    #     experiment that earned and spent nothing would pass against a kernel
    #     whose derivation was broken in either direction.
    golden_experiment = experiments.start(
        conn,
        cell_id=auditor_child.cell_id,
        hypothesis="fixed scenario: does the write-up earn anything",
        ladder_rung=1,
    )
    revenue.record_revenue(
        conn,
        cell_id=auditor_child.cell_id,
        amount_minor_units=40,
        source="golden-run fixed customer",
        book=Book.USD_SIM,
        artifact_id=golden_artifact,
        experiment_id=golden_experiment.experiment_id,
        idempotency_key="golden:revenue:artifact",
    )

    # 19. The external-action registry (§21, §28 Phase 8; ADR-036). The Cell
    #     proposes a channel and a purpose — never a person — a human approves
    #     it, and a human claims the channel, does the thing, and records what
    #     happened. **Nothing in this step sends anything**, which is why it is
    #     safe in a replay at all.
    #
    #     Three things are pinned that a happier scenario would miss:
    #
    #     (a) **A refusal that fires.** A second lineage claiming the same
    #         counterparty is rejected as a §21.3 sibling collision. Without it
    #         the run would pass identically against a registry that refused
    #         nothing, which is the same trap ADR-035's commercial-export step
    #         was built to avoid.
    #     (b) **Both damage states.** One action completes `no_response` and one
    #         completes `complaint`, so the snapshot contains a frozen channel
    #         *and* an unfrozen history rather than a column that is uniformly
    #         one value — the failure mode ADR-031's `born_in_epoch` nearly
    #         shipped with.
    #     (c) **Human minutes.** §2.2's `HUMAN_MINUTES` has been declared since
    #         Phase 1 and metered by nothing; a replay that never records any
    #         cannot tell whether Phase 8's North Star is computable.
    tools.set_autonomy(
        conn, flag="external_message", enabled=True, changed_by="golden-operator"
    )

    def _granted_external_action(cell, *, wake_key: str, intent: str, channel: str = "email"):
        deliberation.deliberate(
            conn,
            cell_id=cell.cell_id,
            provider=providers.MockProvider(
                reply=_external_action_reply(golden_artifact, intent=intent, channel=channel)
            ),
            wake_key=wake_key,
            wake_reason=deliberation.WAKE_SCHEDULED_RESEARCH,
            model="mock-1",
            proposal_sink=approval.QueueSink(),
        )
        request = next(
            r
            for r in approval.queue(conn)
            if r.cell_id == cell.cell_id and r.status == approval.RequestStatus.PENDING
        )
        return approval.approve(
            conn,
            request_id=request.request_id,
            decided_by="golden-operator",
            reason="fixed scenario approval; §21 external action, performed by hand",
        )

    first_grant = _granted_external_action(
        auditor_child,
        wake_key="golden:wake:external-action",
        intent="introduce the write-up",
    )
    first_action = external_actions.claim(
        conn,
        grant_id=first_grant.grant_id,
        claimed_by="golden-operator",
        counterparty="golden-first@golden.test",
        domain="golden.test",
        platform_account="golden-operator",
    )

    #     (a) The sibling collision. The explorer is a different lineage, so a
    #         lineage-keyed window would see nothing at all here — which is
    #         precisely §21.2's "many lineages, one counterparty". It also has no
    #         RESOURCE cash, and the refusal still lands as a collision rather
    #         than an insufficient balance: the §21.2 checks run *before* the
    #         reservation, so being refused a channel never costs a Cell budget.
    second_grant = _granted_external_action(
        explorer,
        wake_key="golden:wake:external-action-collision",
        intent="introduce the same write-up to the same person",
    )
    try:
        external_actions.claim(
            conn,
            grant_id=second_grant.grant_id,
            claimed_by="golden-operator",
            counterparty="golden-first@golden.test",
        )
        raise AssertionError("§21.3 should have refused a second lineage's contact")
    except channel_registry.SiblingCollision:
        pass

    #     (c) Deliberately *over* the email channel's billable ceiling. The Cell
    #         pays 30 minutes' worth and the registry records 34, and the
    #         4-minute gap is §1's subsidy figure — the quantity that clause
    #         asks to be exposed rather than prevented. A run where every action
    #         came in under the ceiling would pass identically against a kernel
    #         that silently capped what it recorded. It also settles the
    #         reservation *fully* while the second settles partially, so both
    #         branches of the settle/release pair are replayed.
    external_actions.complete(
        conn,
        action_id=first_action.action_id,
        completed_by="golden-operator",
        outcome="no_response",
        human_minutes=34,
        reference="golden-run message reference",
    )

    #     (b) The damaging outcome. The grant refused above is spent, so this
    #         uses a third one against a different counterparty — a complaint
    #         freezes the channel colony-wide and blocks that counterparty
    #         permanently, and both are visible in the snapshot.
    third_grant = _granted_external_action(
        auditor_child,
        wake_key="golden:wake:external-action-complaint",
        intent="a second introduction, which goes badly",
    )
    third_action = external_actions.claim(
        conn,
        grant_id=third_grant.grant_id,
        claimed_by="golden-operator",
        counterparty="golden-second@golden.test",
    )
    external_actions.complete(
        conn,
        action_id=third_action.action_id,
        completed_by="golden-operator",
        outcome="complaint",
        human_minutes=4,
    )

    # 19b. §0.4 one flag per capability, and the §21.2 key a publish channel
    #      collides on (ADR-037). Four things this pins, and the fourth is the
    #      one the whole slice exists for:
    #
    #      (a) **A publish channel works end to end.** `web_publish` addresses
    #          nobody, so before ADR-037 it ran through §21.2's checks and every
    #          counterparty-keyed one was skipped — a registry entry, a rate cap
    #          and a freeze in front of no collision detection at all.
    #      (b) **A sibling collision on a domain.** The check that did not
    #          exist. The explorer is a different lineage on the same domain,
    #          which is §21.3 exactly: externally the colony is one business.
    #      (c) **A duplicate publication.** Same lineage, same artifact, same
    #          domain — refused, while the same lineage publishing *different*
    #          content there would not be. That asymmetry is the point: a person
    #          can be contacted once, a domain can be published to all day, and
    #          what cannot repeat is the content. It is keyed on the artifact
    #          because ADR-035 made content the artifact's identity.
    #      (d) **One flag open and the other shut, in the same colony.**
    #          `external_publish` is on and `real_commerce` is off, so a
    #          `marketplace_listing` claim is refused while `web_publish`
    #          succeeds. A kernel that re-merged the two flags — the state this
    #          slice found — would pass every other assertion in this run and
    #          fail here. It also pins that approval is not permission: the
    #          grant below is real, approved by a person, and still refused.
    tools.set_autonomy(
        conn, flag="external_publish", enabled=True, changed_by="golden-operator"
    )

    publish_grant = _granted_external_action(
        auditor_child,
        wake_key="golden:wake:web-publish",
        intent="publish the write-up",
        channel="web_publish",
    )
    publish_action = external_actions.claim(
        conn,
        grant_id=publish_grant.grant_id,
        claimed_by="golden-operator",
        domain="golden.test",
    )
    external_actions.complete(
        conn,
        action_id=publish_action.action_id,
        completed_by="golden-operator",
        outcome="delivered",
        human_minutes=20,
        reference="golden-run page reference",
    )

    #      (b) A different lineage, the same domain.
    publish_collision_grant = _granted_external_action(
        explorer,
        wake_key="golden:wake:web-publish-collision",
        intent="publish against the same domain",
        channel="web_publish",
    )
    try:
        external_actions.claim(
            conn,
            grant_id=publish_collision_grant.grant_id,
            claimed_by="golden-operator",
            domain="golden.test",
        )
        raise AssertionError("§21.3 should have refused a second lineage on one domain")
    except channel_registry.SiblingCollision:
        pass

    #      (c) The same lineage, the same artifact, the same domain.
    publish_duplicate_grant = _granted_external_action(
        auditor_child,
        wake_key="golden:wake:web-publish-duplicate",
        intent="publish the same write-up again",
        channel="web_publish",
    )
    try:
        external_actions.claim(
            conn,
            grant_id=publish_duplicate_grant.grant_id,
            claimed_by="golden-operator",
            domain="golden.test",
        )
        raise AssertionError("§21.2 should have refused the same artifact twice")
    except channel_registry.DuplicatePublication:
        pass

    #      (d) The other half of the split flag, still shut.
    listing_grant = _granted_external_action(
        auditor_child,
        wake_key="golden:wake:marketplace-listing",
        intent="list the write-up for sale",
        channel="marketplace_listing",
    )
    try:
        external_actions.claim(
            conn,
            grant_id=listing_grant.grant_id,
            claimed_by="golden-operator",
            platform_account="golden-merchant",
        )
        raise AssertionError("autonomy.real_commerce is false; §28 Phase 9 is not open")
    except channel_registry.ChannelAutonomyRefused:
        pass

    # 19c. §23.3's other clock (ADR-039). Several grants in this scenario were
    #      approved by a person and then never consumed — the three publish
    #      claims that were refused, and the email one — which is precisely the
    #      solo-operator case §23.3 (Amendment A19) exists to describe. Sweeping
    #      them pins three things a bare grant count could not:
    #
    #      (a) An unconsumed grant **expires** rather than sitting live forever.
    #          `live` ending at zero is what says the sweep ran at all.
    #      (b) Each one **regenerates as a wake**, so the Cell is asked for the
    #          action again instead of waiting on an approval that is never
    #          coming. `regenerated` counts them.
    #      (c) **No new grant is minted.** `total` is unchanged by the sweep,
    #          which is the property that matters most: renewing the grant is
    #          the obvious design and is exactly the banking a grant's inherited
    #          expiry exists to prevent. A kernel that renewed instead of waking
    #          would satisfy (a) and (b) and fail here.
    #
    #      Far past every grant's window, since grants expire on the wall clock
    #      while this scenario's epochs are simulated (§6.3). The instant itself
    #      is volatile and excluded from the snapshot; the counts are not.
    approval.expire_grants_due(
        conn, now=datetime.now(timezone.utc) + timedelta(days=365)
    )

    # 19d. Concluding the experiment (§2.6, §15.1; ADR-043). Deliberately last,
    #      so every deliberation in steps 19–19c ran with it as the Cell's
    #      *current* experiment and §15.1's context section was assembled from
    #      it — that is where this slice's prompt-token diff comes from, and a
    #      scenario that concluded it earlier would pin the section as absent.
    #
    #      §2.6's report is asserted rather than merely recorded: the experiment
    #      earned 40 USD_SIM and moved no real money, so a derivation reading the
    #      wrong account or the wrong book fails here rather than in a hash.
    golden_report = experiments.report(conn, golden_experiment.experiment_id)
    if golden_report.synthetic_revenue_minor_units != 40:
        raise AssertionError(
            "§2.6: the experiment's synthetic revenue should be derived from the "
            f"ledger as 40, got {golden_report.synthetic_revenue_minor_units}"
        )
    if golden_report.real_spend_minor_units != 0:
        raise AssertionError("a golden run must never move USD_REAL")
    if golden_report.sandbox_cpu_seconds is not None:
        raise AssertionError(
            "§2.6's unmeasurable dimensions must report as unmeasurable, never as 0"
        )
    #      Human labour is measured, not unmeasurable (ADR-044): step 19's
    #      external actions were claimed while this experiment was running, so
    #      their minutes reach it through the reservation. A regression that
    #      stopped stamping the attribution shows up here as 0 rather than as a
    #      silently smaller shadow cost, which is the failure this slice fixed.
    if golden_report.human_minutes <= 0:
        raise AssertionError(
            "§2.6: human labour is attributable through the reservation — "
            f"expected the experiment's minutes to be measured, got {golden_report.human_minutes}"
        )
    if golden_report.human_minutes <= golden_report.subsidised_human_minutes:
        raise AssertionError(
            "§1.1: labour given must exceed the subsidised part, or the split is inverted"
        )

    experiments.conclude(
        conn,
        experiment_id=golden_experiment.experiment_id,
        concluded_by="golden-operator",
        note="fixed scenario: the write-up earned 40 USD_SIM",
    )

    # 20. Simulated clock.
    clock.advance(conn, timedelta(days=7))


# --- semantic snapshot -------------------------------------------------------


def _cell_aliases(conn: sqlite3.Connection) -> dict[str, str]:
    """cell_id -> stable birth-order alias. Insertion order (`rowid`) is the
    birth order the scenario fixes, so aliases are reproducible even though
    the underlying uuid4s are not."""
    rows = conn.execute("SELECT cell_id FROM cells ORDER BY rowid").fetchall()
    return {row["cell_id"]: f"cell#{index}" for index, row in enumerate(rows)}


#: A uuid4 in free text. Matched loosely on shape rather than parsed, because
#: what matters is that no id reaches the hash, not that every match was a real
#: identifier.
_UUID_IN_TEXT = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)


def _scrub_ids(text: str) -> str:
    return _UUID_IN_TEXT.sub("<id>", text or "")


def _normalize_account(account_id: str, aliases: dict[str, str]) -> str:
    """`cell:{uuid}:cash` -> `cell:cell#0:cash`; fixed accounts unchanged."""
    if not account_id.startswith("cell:"):
        return account_id
    _, cell_id, suffix = account_id.split(":", 2)
    return f"cell:{aliases.get(cell_id, 'cell#?')}:{suffix}"


def semantic_snapshot(conn: sqlite3.Connection) -> dict:
    """Reduce a colony to what its economics *mean* — no uuids, no
    wall-clock timestamps, no hash-chain digests (ADR-017)."""
    aliases = _cell_aliases(conn)

    balances = {}
    for row in conn.execute(
        """
        SELECT e.account_id AS account_id, t.book AS book,
               SUM(e.amount_minor_units) AS balance
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        GROUP BY e.account_id, t.book
        """
    ).fetchall():
        key = f"{row['book']}::{_normalize_account(row['account_id'], aliases)}"
        balances[key] = row["balance"]

    transaction_types = {
        f"{row['book']}::{row['transaction_type']}": row["n"]
        for row in conn.execute(
            "SELECT book, transaction_type, COUNT(*) AS n FROM ledger_transactions "
            "GROUP BY book, transaction_type"
        ).fetchall()
    }

    # Parent/founder are carried as aliases, not raw ids, so the lineage tree
    # §26 names ("expected lineage tree") is part of the comparison without
    # reintroducing volatile uuids into the snapshot.
    cells = [
        {
            "alias": aliases[row["cell_id"]],
            "cell_type": row["cell_type"],
            "book": row["book"],
            "status": row["status"],
            "genome_hash": row["genome_hash"],
            "parent": aliases.get(row["parent_cell_id"]) if row["parent_cell_id"] else None,
            "founder": aliases.get(row["founder_cell_id"], "cell#?"),
            "generation": row["generation"],
            # §9.2's per-epoch birth cap counts on this. Pinned because a birth
            # path that stopped stamping it would leave the cap silently
            # unenforced with every other assertion still green.
            "born_in_epoch": row["born_in_epoch"],
        }
        for row in conn.execute("SELECT * FROM cells ORDER BY rowid").fetchall()
    ]

    reservation_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "book": row["book"],
            "maximum_amount": row["maximum_amount"],
            "settled_amount": row["settled_amount"],
            "status": row["status"],
            "external_operation_type": row["external_operation_type"],
        }
        for row in conn.execute("SELECT * FROM reservations ORDER BY rowid").fetchall()
    ]

    resource_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "resource_type": row["resource_type"],
            "quantity": row["quantity"],
            "minor_units": row["minor_units"],
        }
        for row in conn.execute("SELECT * FROM resource_usage ORDER BY rowid").fetchall()
    ]

    coroner_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "genome_hash": row["genome_hash"],
            "spend_by_book": json.loads(row["spend_by_book_json"]),
            "cause_of_death": row["cause_of_death"],
            "final_hypotheses": json.loads(row["final_hypotheses_json"]),
            "stage_reached": row["stage_reached"],
        }
        for row in conn.execute("SELECT * FROM coroner_reports ORDER BY rowid").fetchall()
    ]

    audit_event_types = {
        row["event_type"]: row["n"]
        for row in conn.execute(
            "SELECT event_type, COUNT(*) AS n FROM audit_events GROUP BY event_type"
        ).fetchall()
    }

    inbox = [
        {
            "event_type": row["event_type"],
            "priority": row["priority"],
            "status": row["status"],
            "attempt_number": row["attempt_number"],
        }
        for row in conn.execute(
            "SELECT * FROM event_inbox ORDER BY priority, event_type"
        ).fetchall()
    ]
    outbox = [
        {
            "event_type": row["event_type"],
            "priority": row["priority"],
            "published": row["published_at_utc"] is not None,
        }
        for row in conn.execute(
            "SELECT * FROM event_outbox ORDER BY priority, event_type"
        ).fetchall()
    ]

    # §24 gateway. Deliberately excludes the response hash and latency:
    # response text is the provider's business (and the mock's reply is an
    # implementation detail of the test double), while latency is wall-clock
    # and would make the run non-reproducible — the same reason the snapshot
    # drops timestamps everywhere else. What is pinned is the accounting:
    # who called what, how many tokens, and what it cost.
    # Scores are rounded because Brier and log are floats: a bit-level
    # difference in the last place across platforms would break replay for a
    # reason that has nothing to do with behaviour. Six places is far finer
    # than any calibration decision needs. Hashes and timestamps are excluded
    # for the same reasons they are everywhere else in this snapshot.
    # `claim` is free text a Cell (or `approval.py`) wrote, and it can *embed*
    # an id — the auto-registered promotion forecast names its approval request.
    # Ids are seeded and so reproducible, but only for a fixed sequence of
    # allocations: any later slice that mints one id earlier shifts every id
    # after it and produces a spurious diff here, in a section whose subject is
    # calibration rather than identity. ADR-017 excludes "volatile ids" from the
    # snapshot and this is one wearing a sentence as a disguise, so it is
    # scrubbed rather than pinned. (Found by ADR-043, which shifted the sequence
    # by exactly one.)
    prediction_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "claim": _scrub_ids(row["claim"]),
            "probability": row["probability"],
            "outcome": row["outcome"],
            "resolved": row["resolved_at_utc"] is not None,
            "resolution_source": row["resolution_source"],
            "brier_score": None if row["brier_score"] is None else round(row["brier_score"], 6),
            "log_score": None if row["log_score"] is None else round(row["log_score"], 6),
        }
        for row in conn.execute("SELECT * FROM prediction_register ORDER BY rowid").fetchall()
    ]

    # The agent loop (§15/§17.2). Deliberately records `context_tokens` and the
    # dropped-section list: §15.1's "do not load the entire Cell history" is a
    # behavioural claim, and a snapshot that captured only the proposal would
    # let context assembly silently start loading everything without the hash
    # moving. Proposal *text* is included because it is the model's output for
    # a fixed mock reply — if it ever varies, parsing has changed.
    deliberation_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "wake_reason": row["wake_reason"],
            "status": row["status"],
            "failure_reason": row["failure_reason"],
            "context_tokens": row["context_tokens"],
            "context_dropped": json.loads(row["context_dropped_json"]),
            "made_model_call": row["model_call_id"] is not None,
        }
        for row in conn.execute("SELECT * FROM deliberations ORDER BY rowid").fetchall()
    ]

    proposal_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "kind": row["kind"],
            "summary": row["summary"],
            "risk_tier": row["risk_tier"],
            "estimated_cost_minor_units": row["estimated_cost_minor_units"],
            # §18/§19.4. Pinned because a regression that stopped propagating
            # taint would leave every reviewer's payload looking clean.
            "derived_from_untrusted": bool(row["derived_from_untrusted"]),
        }
        for row in conn.execute("SELECT * FROM proposals ORDER BY rowid").fetchall()
    ]

    # §19's tool surface. The result *text* is deliberately excluded and its
    # length pinned instead: the fixture's wording is not an economic fact, but
    # a change in how much of a page reaches a Cell is. The §20.1 rights
    # columns are pinned in full, because a slice that started defaulting a
    # licence to "permitted" would be manufacturing a rights position and the
    # diff is the only place that would show.
    tool_call_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "tool": row["tool"],
            "arguments": json.loads(row["arguments_json"]),
            "status": row["status"],
            "taint_label": row["taint_label"],
            "licence": row["licence"],
            "commercial_use": row["commercial_use"],
            "contains_personal_data": row["contains_personal_data"],
            "result_bytes": row["result_bytes"],
            "http_status": row["http_status"],
        }
        for row in conn.execute("SELECT * FROM tool_calls ORDER BY rowid").fetchall()
    ]

    # §20/§11.3's store. The content itself is excluded and its *hash prefix*
    # pinned instead — content addressing is the anti-duplication mechanism, so
    # what matters to a replay is that identical work yields an identical
    # address, not what the fixture happens to say. The §20.1 rights columns are
    # pinned in full: this artifact cites a fetched page, so `commercial_use`
    # reading anything other than `unknown` means inheritance stopped working
    # and §20.2's laundering path reopened.
    artifact_rows = [
        {
            "cell": aliases.get(row["created_by_cell_id"], "cell#?"),
            "kind": row["kind"],
            "title": row["title"],
            "hash_prefix": row["artifact_hash"][:12],
            "content_bytes": row["content_bytes"],
            "licence": row["licence"],
            "commercial_use": row["commercial_use"],
            "contains_personal_data": row["contains_personal_data"],
            "taint_labels": json.loads(row["taint_labels_json"]),
            "exported": row["exported_at_utc"] is not None,
            "export_is_commercial": row["export_is_commercial"],
        }
        for row in conn.execute("SELECT * FROM artifacts ORDER BY rowid").fetchall()
    ]

    # §9.2/§25.1's experiments (ADR-043). **The §2.6 report is not stored, so
    # what is pinned is derived on the spot** — which is the assertion: a kernel
    # that started caching an outcome would have to keep this identical, and a
    # kernel whose derivation broke shows it here rather than only in the hash.
    # `abandoned` on the dead Cell's row is the §9.2 slot being released.
    experiment_rows = []
    for row in conn.execute("SELECT * FROM experiments ORDER BY rowid").fetchall():
        derived = experiments.report(conn, row["experiment_id"])
        experiment_rows.append(
            {
                "cell": aliases.get(row["cell_id"], "cell#?"),
                "hypothesis": row["hypothesis"],
                "ladder_rung": row["ladder_rung"],
                "status": row["status"],
                "concluded_by": row["concluded_by"],
                "expected_cost_minor_units": row["expected_cost_minor_units"],
                "synthetic_revenue": derived.synthetic_revenue_minor_units,
                "synthetic_net_profit": derived.synthetic_net_profit_minor_units,
                "real_spend": derived.real_spend_minor_units,
                "resource_spend": derived.resource_spend_minor_units,
                "sandbox_cpu_seconds": derived.sandbox_cpu_seconds,
                # Both halves of §1.1's split. Pinning only the total would let
                # a regression that stopped counting subsidised minutes pass
                # unnoticed on any run where nothing was subsidised, and the
                # subsidy is the figure §1.1 exists to expose.
                "human_minutes": derived.human_minutes,
                "subsidised_human_minutes": derived.subsidised_human_minutes,
                # §2.6's sixth dimension. Pinned even at 0/0: it pins that the
                # derivation still runs, and a scenario change that starts
                # attributing forecasts shows up here instead of only in the
                # hash.
                "resolved_predictions": derived.resolved_predictions,
                "unresolved_predictions": derived.unresolved_predictions,
            }
        )

    # §20.1's establishable half (ADR-041). `attestation_id` and the timestamp
    # are volatile; what a replay pins is the *position* and the fact that a
    # person is on the record for it. `basis` is included in full rather than
    # counted: §20.3 makes an unfounded rights position a liability, so a
    # regression that dropped the operator's stated reason and kept the
    # permission would be the exact failure worth catching.
    rights_attestation_rows = [
        {
            "subject_kind": row["subject_kind"],
            "subject": row["subject"],
            "licence": row["licence"],
            "commercial_use": row["commercial_use"],
            "basis": row["basis"],
            "attested_by": row["attested_by"],
        }
        for row in conn.execute("SELECT * FROM rights_attestations ORDER BY rowid").fetchall()
    ]

    # §11.4's contribution graph. Source ids are volatile, so what is pinned is
    # the *shape*: how many edges, and of which kind.
    artifact_lineage_shape = {
        "edges": conn.execute("SELECT COUNT(*) AS n FROM artifact_lineage").fetchone()["n"],
        "from_tool_calls": conn.execute(
            "SELECT COUNT(*) AS n FROM artifact_lineage WHERE source_tool_call_id IS NOT NULL"
        ).fetchone()["n"],
        "from_artifacts": conn.execute(
            "SELECT COUNT(*) AS n FROM artifact_lineage WHERE source_artifact_id IS NOT NULL"
        ).fetchone()["n"],
    }

    # Amendment A3, populated for the first time. A count rather than ids: what
    # regresses here is attribution disappearing, not which uuid it names.
    attributed_entries = conn.execute(
        "SELECT COUNT(*) AS n FROM ledger_entries WHERE artifact_id IS NOT NULL"
    ).fetchone()["n"]

    # §21.2's registry. **`counterparty_hash` is deliberately absent**, and for
    # once the reason is not that the value is volatile — though it is, since
    # the colony's salt is generated per run. It is that a snapshot is a
    # human-readable artifact checked into the repository, and putting a stable
    # per-person token into one would undo, in the place people actually read,
    # the thing §16.3 asked the schema not to hold. `addressed` says whether
    # there *was* a counterparty; that is the whole of what a replay needs.
    #
    # `human_minutes` and `billed_human_minutes` are both pinned because they
    # differ when a person spends more than the Cell can pay for, and the gap is
    # §1's subsidy figure. A snapshot carrying only one of them could not tell a
    # colony that measured its human cost from one that quietly capped it.
    external_action_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "channel": row["channel"],
            "intent": row["intent"],
            "addressed": row["counterparty_hash"] is not None,
            "domain": row["domain"],
            "platform_account": row["platform_account"],
            "delivers_artifact": row["artifact_id"] is not None,
            "status": row["status"],
            "outcome": row["outcome"],
            "human_minutes": row["human_minutes"],
        }
        for row in conn.execute(
            "SELECT * FROM external_action_registry ORDER BY rowid"
        ).fetchall()
    ]

    # §21.1. A frozen channel and a non-empty do-not-contact list are what a
    # complaint *does*; a replay in which neither ever fires would pass against
    # a kernel that recorded the outcome and acted on nothing.
    channel_freeze_state = {
        channel: bool(channel_registry.channel_frozen(conn, channel)[0])
        for channel in sorted(channel_registry.REGISTRY)
    }
    counterparty_block_reasons = sorted(
        row["reason"]
        for row in conn.execute("SELECT reason FROM counterparty_blocks").fetchall()
    )

    # §2.2's `human_minutes`, metered for the first time. Colony-wide totals
    # rather than per-Cell: Phase 8's North Star is "human minutes/artifact",
    # and the denominator is already pinned by `artifacts` above.
    human_minutes = {
        "reported": channel_registry.human_minutes_total(conn),
        "billed": conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS q FROM resource_usage "
            "WHERE resource_type = 'human_minutes'"
        ).fetchone()["q"],
    }

    # Charter C12 and §27.1. Both start closed, so a colony that shipped with
    # either open would diff here — which is the regression most worth catching
    # in this whole section.
    egress_domains = [
        row["domain"]
        for row in conn.execute("SELECT domain FROM egress_allowlist ORDER BY domain")
    ]
    autonomy_row = conn.execute("SELECT * FROM operator_state WHERE id = 1").fetchone()
    autonomy_flags = (
        {
            flag: bool(autonomy_row[column])
            for flag, column in sorted(tool_registry._AUTONOMY_COLUMNS.items())
        }
        if autonomy_row is not None
        else {}
    )

    # §23's review queue. Ids, timestamps and the aggregation key's embedded
    # cell id are all volatile, so what is pinned is the *classification*: what
    # the Cell claimed, what the kernel assessed, the exposure it was assessed
    # against, and which anti-gaming signals fired.
    approval_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "claimed_tier": row["claimed_tier"],
            "assessed_tier": row["assessed_tier"],
            "exposure_minor_units": row["exposure_minor_units"],
            "reversible": bool(row["reversible"]),
            "status": row["status"],
            "sla_seconds": row["sla_seconds"],
            "signals": sorted(
                signal["signal"]
                for signal in conn.execute(
                    "SELECT signal FROM approval_signals WHERE request_id = ?",
                    (row["request_id"],),
                ).fetchall()
            ),
        }
        for row in conn.execute(
            "SELECT * FROM approval_requests ORDER BY rowid"
        ).fetchall()
    ]

    # Grant **disposition**, not a bare count (ADR-039). The count alone could
    # not see the thing worth pinning: §23.3 regenerates an approval nobody
    # consumed, and regeneration must produce a *wake* and never a new grant. A
    # kernel that renewed the grant instead would keep `total` moving in
    # lockstep and look identical here, so `expired` and `regenerated` are
    # pinned beside it. `live` ending at zero is the tell that the sweep ran.
    #
    # (The comment this replaces said "no grant is ever issued by the scenario",
    # which stopped being true at expectation 7 when the §23 queue landed.)
    grant_disposition = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(consumed_at_utc IS NULL AND expired_at_utc IS NULL) AS live,
               SUM(consumed_at_utc IS NOT NULL) AS consumed,
               SUM(expired_at_utc IS NOT NULL) AS expired,
               SUM(regenerated_wake_key IS NOT NULL) AS regenerated
          FROM approval_grants
        """
    ).fetchone()
    approval_grants = {
        key: int(grant_disposition[key] or 0)
        for key in ("total", "live", "consumed", "expired", "regenerated")
    }

    # §25.2's promotion evidence. Ids and timestamps are volatile; the rung,
    # the amount, and the two humans are the substance.
    promotion_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "rung": row["rung"],
            "book": row["book"],
            "allocated_minor_units": row["allocated_minor_units"],
            "resolved_predictions": row["resolved_predictions"],
            "unresolved_predictions": row["unresolved_predictions"],
            "liability_minor_units": row["liability_minor_units"],
            "transfer_degradation": row["transfer_degradation"],
            "approved_by": row["approved_by"],
            "allocated_by": row["allocated_by"],
        }
        for row in conn.execute("SELECT * FROM promotions ORDER BY rowid").fetchall()
    ]

    # §23.2's independent Auditor summaries. Cell aliases on both sides, so
    # the *independence* itself is what the snapshot pins: a regression that
    # let a Cell audit its own request, or a relative do it, shows up here as
    # the same alias twice rather than passing silently.
    audit_rows = [
        {
            "auditor": aliases.get(row["auditor_cell_id"], "cell#?"),
            "subject": aliases.get(row["subject_cell_id"], "cell#?"),
            "status": row["status"],
            "verdict": row["verdict"],
            "probability": row["probability"],
            "has_prediction": row["prediction_id"] is not None,
            "failure_reason": row["failure_reason"],
        }
        for row in conn.execute("SELECT * FROM audits ORDER BY rowid").fetchall()
    ]

    # §25.2's read-back, derived rather than stored — the assessment has no
    # table, so this section is computed from the register and the ledger at
    # snapshot time exactly as `mitosis assess` computes it.
    #
    # `observed_mean_brier` is pinned as an exact float because it is the number
    # the verdict turns on. Every timestamp-derived field is excluded as usual;
    # `forecasts_overdue` is safely stable because the scenario's forecasts
    # resolve 30 days out and are resolved immediately.
    assessment_rows = [
        {
            "cell": aliases.get(item.cell_id, "cell#?"),
            "rung": item.rung,
            "next_rung": item.next_rung,
            "verdict": item.verdict.value,
            "forecasts_open_at_funding": item.forecasts_open_at_funding,
            "forecasts_resolved_since": item.forecasts_resolved_since,
            "forecasts_still_open": item.forecasts_still_open,
            "forecasts_overdue": item.forecasts_overdue,
            "observed_mean_brier": item.observed_mean_brier,
            "funded_mean_brier": item.funded_mean_brier,
            "reality_gap": item.reality_gap,
            "liability_minor_units": item.liability_minor_units,
            "allocated_minor_units": item.allocated_minor_units,
            "spend_since_minor_units": item.spend_since_minor_units,
            "revenue_since_minor_units": item.revenue_since_minor_units,
            "human_interventions": item.human_interventions,
            "intervention_kinds": item.intervention_kinds,
            "forecasts_made_while_funded": item.forecasts_made_while_funded,
        }
        for item in outcome.assess_all(conn)
    ]

    model_call_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "provider": row["provider"],
            "requested_model": row["requested_model"],
            "resolved_model": row["resolved_model"],
            "status": row["status"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "cost_actual_micro_usd": row["cost_actual_micro_usd"],
            "settled_minor_units": row["settled_minor_units"],
            "mirror_minor_units": row["mirror_minor_units"],
            "pricing_table_version": row["pricing_table_version"],
            # §24.1 reconciled cost. The *source* is pinned but the timestamp
            # is not — `reconciled_at_utc` is wall-clock, same exclusion as
            # every other timestamp in this snapshot; `reconciled` records
            # only that it was set.
            "reconciled_micro_usd": row["reconciled_micro_usd"],
            "reconciled": row["reconciled_at_utc"] is not None,
            "reconciliation_source": row["reconciliation_source"],
        }
        for row in conn.execute("SELECT * FROM model_calls ORDER BY rowid").fetchall()
    ]

    clock_state = clock.get_state(conn)

    return {
        "balances": balances,
        "transaction_types": transaction_types,
        "cells": cells,
        "reservations": reservation_rows,
        "resource_usage": resource_rows,
        "model_calls": model_call_rows,
        "coroner_reports": coroner_rows,
        "predictions": prediction_rows,
        "deliberations": deliberation_rows,
        "proposals": proposal_rows,
        "tool_calls": tool_call_rows,
        "artifacts": artifact_rows,
        "experiments": experiment_rows,
        "rights_attestations": rights_attestation_rows,
        "artifact_lineage": artifact_lineage_shape,
        "external_actions": external_action_rows,
        "channel_frozen": channel_freeze_state,
        "counterparty_blocks": counterparty_block_reasons,
        "human_minutes": human_minutes,
        "artifact_attributed_ledger_entries": attributed_entries,
        "egress_allowlist": egress_domains,
        "autonomy": autonomy_flags,
        "approval_requests": approval_rows,
        "approval_grants": approval_grants,
        "audits": audit_rows,
        "promotions": promotion_rows,
        "assessments": assessment_rows,
        "audit_event_types": audit_event_types,
        "event_inbox": inbox,
        "event_outbox": outbox,
        "clock": {
            "mode": clock_state.mode.value,
            "simulated_at": clock_state.checkpoint_simulated_at_utc.isoformat(),
        },
    }


def semantic_invariants(conn: sqlite3.Connection) -> dict:
    """The Charter-level facts a golden run pins down alongside the hash
    (ADR-017: "semantic invariants *plus* a hash")."""
    return {
        "conservation_usd_real": ledger.verify_conservation(conn, Book.USD_REAL),
        "conservation_usd_sim": ledger.verify_conservation(conn, Book.USD_SIM),
        "conservation_resource": ledger.verify_conservation(conn, Book.RESOURCE),
        "hash_chain_valid": ledger.verify_chain(conn),
        "resource_linkage_complete": resource_metering.verify_linkage(conn),
        "living_cells": population.living_count(conn),
        "active_cells": population.active_count(conn),
        "coroner_reports": lifecycle.count_coroner_reports(conn),
    }


def semantic_hash(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- expectations + verification ---------------------------------------------


@dataclass(frozen=True)
class GoldenRunResult:
    matched: bool
    expectation_version: int
    expected_hash: str
    actual_hash: str
    invariant_failures: list[str] = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)
    invariants: dict = field(default_factory=dict)

    @property
    def hash_matched(self) -> bool:
        return self.expected_hash == self.actual_hash


def _expectations_path() -> Path:
    return Path(str(resources.files("mitosis") / EXPECTATIONS_FILENAME))


def load_expectations() -> dict:
    path = _expectations_path()
    if not path.exists():
        raise GoldenRunError(
            f"no golden-run expectations found at {path} — generate them with "
            "`mitosis verify-golden-run --update-expectations`"
        )
    return json.loads(path.read_text())


def build_expectations() -> dict:
    """Run the scenario fresh and produce an expectations document."""
    conn = db.connect_and_migrate()
    try:
        run_scenario(conn)
        snapshot = semantic_snapshot(conn)
        return {
            "expectation_version": EXPECTATION_VERSION,
            "semantic_hash": semantic_hash(snapshot),
            "invariants": semantic_invariants(conn),
            "snapshot": snapshot,
        }
    finally:
        conn.close()


def write_expectations(expectations: dict) -> Path:
    path = _expectations_path()
    path.write_text(json.dumps(expectations, indent=2, sort_keys=True) + "\n")
    return path


def verify() -> GoldenRunResult:
    """Replay the golden scenario and compare it against the stored
    expectations: semantic invariants first (they name *what* diverged),
    then the hash (it proves nothing else did)."""
    expectations = load_expectations()

    conn = db.connect_and_migrate()
    try:
        run_scenario(conn)
        snapshot = semantic_snapshot(conn)
        invariants = semantic_invariants(conn)
    finally:
        conn.close()

    actual_hash = semantic_hash(snapshot)
    expected_invariants = expectations.get("invariants", {})

    failures = []
    for name, expected_value in expected_invariants.items():
        actual_value = invariants.get(name)
        if actual_value != expected_value:
            failures.append(f"{name}: expected {expected_value!r}, got {actual_value!r}")
    for name in invariants:
        if name not in expected_invariants:
            failures.append(f"{name}: not present in stored expectations")

    expected_hash = expectations.get("semantic_hash", "")
    return GoldenRunResult(
        matched=not failures and expected_hash == actual_hash,
        expectation_version=expectations.get("expectation_version", 0),
        expected_hash=expected_hash,
        actual_hash=actual_hash,
        invariant_failures=failures,
        snapshot=snapshot,
        invariants=invariants,
    )


def diff_snapshots(expected: dict, actual: dict) -> list[str]:
    """Top-level, human-readable differences between two snapshots — what
    §26.2's "visible diff" means in practice when a hash mismatch needs
    explaining."""
    differences = []
    for key in sorted(set(expected) | set(actual)):
        if key not in expected:
            differences.append(f"{key}: absent from expectations, present now")
        elif key not in actual:
            differences.append(f"{key}: present in expectations, absent now")
        elif expected[key] != actual[key]:
            differences.append(f"{key}: differs")
    return differences
