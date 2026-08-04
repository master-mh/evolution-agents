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
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

from . import (
    clock,
    db,
    events,
    gateway,
    ids,
    ledger,
    lifecycle,
    lineage,
    population,
    prediction,
    providers,
    real_spend_breaker,
    reconciliation,
    reservations,
    resource_metering,
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
EXPECTATION_VERSION = 4

# Fixed instants. The scenario must never read the wall clock for anything
# that reaches the snapshot, so these are constants rather than `now()`.
SCENARIO_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
SCENARIO_RESERVATION_EXPIRY = datetime(2030, 1, 1, tzinfo=timezone.utc)

# Fixed seed for ids.py (see module docstring) — every raw uuid the scenario
# generates, not just its semantic snapshot, is reproducible run to run.
GOLDEN_RUN_ID_SEED = 20260101


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
    auditor = lifecycle.create_cell(
        conn, cell_type=CellType.AUDITOR, budget_minor_units=2_000,
        book=Book.USD_SIM, idempotency_key="golden:birth:auditor",
    )

    # The other birth path: a child of the auditor, funded from the auditor's
    # own cash rather than a colony account, carrying a mutated genome so the
    # run pins a real genome-parentage edge as well as a cell-parentage one
    # (SPEC.md §26 names the "expected lineage tree" as golden-run content).
    lineage.reproduce(
        conn, parent_cell_id=auditor.cell_id, budget_minor_units=500,
        idempotency_key="golden:birth:auditor-child",
        mutation={"strategy": "golden-child-v2"},
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
        conn, cell_id=auditor.cell_id, book=Book.USD_SIM, currency="USD",
        maximum_amount=400, expires_at=SCENARIO_RESERVATION_EXPIRY,
        idempotency_key="golden:res:released",
    )
    reservations.release(conn, released.reservation_id)

    # Left open in execution_unknown on purpose: Charter C7 says an unknown
    # external operation is reconciled, never auto-released, so the golden
    # run pins that funds stay committed.
    stuck = reservations.request(
        conn, cell_id=auditor.cell_id, book=Book.USD_SIM, currency="USD",
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
    lifecycle.sleep(conn, auditor.cell_id)

    lifecycle.quarantine(
        conn, explorer.cell_id, reason="golden-run policy violation",
        linked_finding={"finding": "golden-run synthetic finding"},
    )
    lifecycle.clear_quarantine(conn, explorer.cell_id, to_status=CellStatus.ALIVE)

    lifecycle.kill(
        conn, commercial.cell_id,
        cause_of_death="stage budget exhausted",
        final_hypotheses=["golden-run hypothesis A", "golden-run hypothesis B"],
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
                max_attempts=3, cell_id=auditor.cell_id,
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

    # 12. Simulated clock.
    clock.advance(conn, timedelta(days=7))


# --- semantic snapshot -------------------------------------------------------


def _cell_aliases(conn: sqlite3.Connection) -> dict[str, str]:
    """cell_id -> stable birth-order alias. Insertion order (`rowid`) is the
    birth order the scenario fixes, so aliases are reproducible even though
    the underlying uuid4s are not."""
    rows = conn.execute("SELECT cell_id FROM cells ORDER BY rowid").fetchall()
    return {row["cell_id"]: f"cell#{index}" for index, row in enumerate(rows)}


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
    prediction_rows = [
        {
            "cell": aliases.get(row["cell_id"], "cell#?"),
            "claim": row["claim"],
            "probability": row["probability"],
            "outcome": row["outcome"],
            "resolved": row["resolved_at_utc"] is not None,
            "resolution_source": row["resolution_source"],
            "brier_score": None if row["brier_score"] is None else round(row["brier_score"], 6),
            "log_score": None if row["log_score"] is None else round(row["log_score"], 6),
        }
        for row in conn.execute("SELECT * FROM prediction_register ORDER BY rowid").fetchall()
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
