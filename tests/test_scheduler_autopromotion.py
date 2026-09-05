"""§25.1's unattended promotion, wired into the scheduled `tick` path
(implementation brief, Slice E).

`autopromotion.sweep()` and `promotion.allocate()` already carry their own
extensive guard coverage (tests/test_expanded_pilot.py) -- the flag gate,
`real_spending` independence, batchable-never-widened, vacation-adjacent
refusals, rung climbing on evidence. Nothing here re-proves those; this file
is about the *wiring* that was actually missing: `cli.py::cmd_tick` never
passed a `promoter` to `scheduler.tick()`, so an enabled `auto_promotion`
flag deliberated and queued proposals every tick but never allocated
anything unattended -- the standalone `auto-promote` verb worked, the
scheduled path silently didn't.

Every grant below is approved the way §23.1 actually allows one to be
approved today: a human calls `approval.approve()` directly.
`approval._kernel_tier` unconditionally floors a `spend_request` at MEDIUM,
so a spend_request can never be *assessed* LOW and therefore never
`batchable` -- no spend_request is ever auto-approved by `sweep()`'s batch
step, flag on or off. What Slice E's wiring adds is that *allocating* an
already-approved grant -- moving the money, waking the Cell -- now reaches
an ordinary scheduled tick, instead of requiring a person to separately run
`mitosis auto-promote`.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from mitosis import (
    approval,
    autopromotion,
    cli,
    clock,
    db,
    deliberation,
    ledger,
    lifecycle,
    promotion,
    providers,
    scheduler,
    tools,
)
from mitosis.models import Book, CellType, EntrySpec

EXPERIMENT_REPLY = json.dumps(
    {
        "kind": "experiment",
        "summary": "probe the market",
        "rationale": "no realised record yet",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 0,
        "predictions": [],
        "experiment": {"hypothesis": "a cheap probe"},
    }
)


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


def _setup(conn) -> None:
    clock.initialize_if_absent(conn)
    scheduler.configure_epochs_if_absent(conn)
    scheduler.initialize_operator_if_absent(conn)
    promotion.fund_pool(
        conn, book=Book.USD_SIM, amount_minor_units=10_000,
        funding_account="seed_bank", idempotency_key="pool",
    )
    conn.commit()


def _make_cell(conn, key: str) -> lifecycle.Cell:
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key=key,
    )
    for book, currency in ((Book.USD_REAL, "USD"), (Book.RESOURCE, "RESOURCE")):
        ledger.post_transaction(
            conn, book=book, currency=currency, transaction_type="cell_birth_funding",
            idempotency_key=f"fund:{key}:{book.value}", description="fund",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-5000, cell_id=cell.cell_id),
                EntrySpec(account_id=f"cell:{cell.cell_id}:cash",
                          amount_minor_units=5000, cell_id=cell.cell_id),
            ],
        )
    return lifecycle.get_cell(conn, cell.cell_id)


def _grant(conn, cell: lifecycle.Cell, tag: str, *, cost: int = 30) -> approval.Grant:
    """A human approves a spend_request, exactly as §23.1 allows one to be
    approved today -- mirrors tests/test_expanded_pilot.py's helper of the
    same name."""
    deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(
            reply=json.dumps(
                {
                    "kind": "spend_request",
                    "summary": f"test request {tag}",
                    "rationale": "exists to be allocated unattended",
                    "risk_tier": "LOW",
                    "estimated_cost_minor_units": cost,
                    "predictions": [],
                }
            )
        ),
        wake_key=f"wake:{tag}",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    request = next(r for r in approval.queue(conn) if r.cell_id == cell.cell_id)
    return approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="test approval"
    )


def _tick(conn, *, reply: str = EXPERIMENT_REPLY, **kwargs):
    return scheduler.tick(conn, provider=providers.MockProvider(reply=reply), model="mock-1", **kwargs)


def test_auto_promotion_off_leaves_an_approved_grant_unallocated_during_a_tick(conn):
    """§27.1 ships `auto_promotion` false. Approval already happened (a human
    decided) -- what the flag must still gate is *allocation* reaching the
    scheduled path, since that is the only new behaviour Slice E adds."""
    _setup(conn)
    tools.set_autonomy(conn, flag="auto_promotion", enabled=False)
    cell = _make_cell(conn, "a")
    _grant(conn, cell, "a")

    result = _tick(conn, promoter=autopromotion.EvidencePromoter())

    assert promotion.allocatable_grants(conn) != []
    assert promotion.list_promotions(conn, cell_id=cell.cell_id) == []
    assert "allocated" not in result.detail


def test_auto_promotion_on_allocates_an_approved_grant_during_a_tick(conn):
    _setup(conn)
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    cell = _make_cell(conn, "a")
    _grant(conn, cell, "a")

    result = _tick(conn, promoter=autopromotion.EvidencePromoter())

    assert promotion.allocatable_grants(conn) == []
    records = promotion.list_promotions(conn, cell_id=cell.cell_id)
    assert len(records) == 1
    assert records[0].allocated_by == autopromotion.DECIDER
    assert records[0].decided_automatically is True
    assert "allocated 1" in result.detail


def test_cli_tick_allocates_an_approved_grant_when_auto_promotion_is_on(tmp_path, capsys):
    """End to end through `cli.main`, not `scheduler.tick` directly. Every
    test above passes a `promoter` by hand, so none of them would notice if
    `cmd_tick` itself forgot to build one -- this is the one that fails if
    that line is ever reverted."""
    db_path = tmp_path / "mitosis.db"
    cli.main(["--db", str(db_path), "init"])

    setup_conn = db.connect_and_migrate(str(db_path))
    _setup(setup_conn)
    tools.set_autonomy(setup_conn, flag="auto_promotion", enabled=True)
    cell = _make_cell(setup_conn, "a")
    _grant(setup_conn, cell, "a")
    setup_conn.close()

    exit_code = cli.main(["--db", str(db_path), "tick"])

    assert exit_code == 0
    assert "allocated 1" in capsys.readouterr().out

    check_conn = db.connect_and_migrate(str(db_path))
    records = promotion.list_promotions(check_conn, cell_id=cell.cell_id)
    assert len(records) == 1
    assert records[0].allocated_by == autopromotion.DECIDER
    check_conn.close()


def test_a_non_batchable_request_is_not_promoted_during_a_tick(conn):
    """§23.1: high-risk stays for a person. A HIGH-tier reply must reach the
    queue and stay there through an auto-promotion-enabled tick."""
    _setup(conn)
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    _make_cell(conn, "a")
    high_tier_reply = json.dumps(
        {
            "kind": "spend_request", "summary": "a high-tier request",
            "rationale": "needs a person", "risk_tier": "HIGH",
            "estimated_cost_minor_units": 30, "predictions": [],
        }
    )

    result = _tick(conn, reply=high_tier_reply, promoter=autopromotion.EvidencePromoter())

    assert result.deliberations
    pending = approval.queue(conn, status=approval.RequestStatus.PENDING)
    assert len(pending) == 1
    assert pending[0].assessed_tier.value == "HIGH"


def test_vacation_mode_prevents_the_promoter_from_running_at_all(conn):
    """§23.3: an unresponsive operator pauses external-facing work. The
    promoter must not even be invoked -- `_guard` returns before it, same as
    it does for deliberation."""
    _setup(conn)
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    # Real spending must be on so the *only* guard `_Boom`'s paid provider can
    # trip is vacation -- otherwise `_guard`'s earlier real_spending check
    # halts first (it also ships off) and the test would pass without ever
    # exercising vacation mode at all.
    scheduler.set_real_spending(conn, True)
    scheduler.heartbeat(conn)
    conn.execute(
        "UPDATE operator_state SET vacation_pause_after_seconds = 0, "
        "last_heartbeat_utc = '2000-01-01T00:00:00+00:00' WHERE id = 1"
    )
    conn.commit()
    cell = _make_cell(conn, "a")
    _grant(conn, cell, "a")

    class _Boom:
        name = providers.ANTHROPIC_PROVIDER

        def complete(self, request):  # pragma: no cover
            raise AssertionError("must not be reached: vacation halts before deliberation")

    result = scheduler.tick(
        conn, provider=_Boom(), model="mock-1", promoter=autopromotion.EvidencePromoter()
    )

    assert result.outcome == scheduler.TickOutcome.HALTED_VACATION
    assert promotion.allocatable_grants(conn) != []


def test_ticking_twice_does_not_allocate_the_same_grant_twice(conn):
    _setup(conn)
    tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
    cell = _make_cell(conn, "a")
    _grant(conn, cell, "a")

    first = _tick(conn, promoter=autopromotion.EvidencePromoter())
    second = _tick(conn, promoter=autopromotion.EvidencePromoter())

    assert "allocated 1" in first.detail
    assert "allocated 1" not in second.detail
    records = promotion.list_promotions(conn, cell_id=cell.cell_id)
    assert len(records) == 1


def test_the_scheduler_does_not_import_autopromotion_promotion_or_outcome():
    """The dependency inversion CLAUDE.md names explicitly: `scheduler.py`
    declares the `PromotionSweeper` Protocol and takes an instance; it must
    never import the modules that implement it, or the CLI-level wiring
    would not have been necessary in the first place."""
    forbidden = {"autopromotion", "promotion", "outcome"}
    source_path = Path(scheduler.__file__)
    imported = set()
    for node in ast.walk(ast.parse(source_path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module in (None, "mitosis", "."):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[-1] for a in node.names)
    collision = forbidden & imported
    assert not collision, f"scheduler.py imports {collision}, breaking the dependency inversion"
