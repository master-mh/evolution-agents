"""§13.1's normalised cost (SPEC.md §13.1, §13.2, §10.2, §10.5, §23.2, §25.2;
ADR-029, ADR-043, ADR-048).

    normalised_cost = expected experiment cost / current stage tranche

One line, and the only place in the spec that uses the word "tranche". Its
purpose is stated immediately after it — "Never subtract raw dollars from scores
in `[0,1]`" — so what it produces is a **dimensionless** figure that can sit on
§13.2's Pareto frontier beside scores, and what it must never become is a
verdict: §13.2 and §10.2 both forbid collapsing dimensions into one scalar.

The denominator needed no building. `promotions.allocated_minor_units` has been
the capital the colony allots a Cell for a stage since ADR-029, and §10.5 names
the same object from the other side — "stage budget exhausted" is a death
criterion. These defend the ratio, the thing it is keyed on, and the two
readings that would quietly make it wrong.
"""

from __future__ import annotations

import inspect
import json

import pytest

from mitosis import (
    approval,
    db,
    deliberation,
    experiments,
    ledger,
    lifecycle,
    population,
    promotion,
    providers,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType, EntrySpec, PopulationLimits

GENOME = {"market": "small accounting firms", "workflow": "probe cheaply"}


@pytest.fixture()
def conn():
    connection = db.connect_and_migrate()
    population.set_limits_if_absent(
        connection,
        PopulationLimits(
            max_living_cells=1000,
            max_active_cells=100,
            max_parallel_experiments=5,
            max_births_per_epoch=25,
            max_lineage_population_fraction=0.20,
        ),
    )
    connection.commit()
    yield connection
    connection.close()


def _reply(**overrides) -> str:
    payload = {
        "kind": "spend_request",
        "summary": "buy the sample dataset",
        "rationale": "cheapest way to test the demand hypothesis",
        "risk_tier": "MEDIUM",
        "estimated_cost_minor_units": 40,
        "predictions": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _fund(conn, cell, amount: int = 50_000) -> None:
    for book, currency in (
        (Book.USD_REAL, "USD"), (Book.RESOURCE, "RESOURCE"), (Book.USD_SIM, "USD"),
    ):
        ledger.post_transaction(
            conn, book=book, currency=currency,
            transaction_type="cell_birth_funding",
            idempotency_key=f"fund:{cell.cell_id}:{book.value}",
            description="fund",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-amount,
                          cell_id=cell.cell_id),
                EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=amount,
                          cell_id=cell.cell_id),
            ],
        )


def _seed_pool(conn, amount: int = 10_000, book: Book = Book.USD_SIM) -> None:
    ledger.post_transaction(
        conn, book=book, currency="USD" if book != Book.RESOURCE else "RESOURCE",
        transaction_type="colony_seed_capital",
        idempotency_key=f"seed-treasury:{book.value}",
        description="seed the treasury",
        entries=[
            EntrySpec(account_id="external_capital", amount_minor_units=-amount),
            EntrySpec(account_id="colony_treasury", amount_minor_units=amount),
        ],
    )
    promotion.fund_pool(
        conn, book=book, amount_minor_units=amount, idempotency_key=f"pool:{book.value}"
    )


def _make_cell(conn, *, key: str = "a"):
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key=key,
    )
    genome_hash = lifecycle._get_or_create_genome(conn, CellType.EXPLORER, mutation=GENOME)
    conn.execute(
        "UPDATE cells SET genome_hash = ? WHERE cell_id = ?", (genome_hash, cell.cell_id)
    )
    conn.commit()
    _fund(conn, cell)
    return lifecycle.get_cell(conn, cell.cell_id)


def _promote(conn, cell, *, amount: int, wake_key: str):
    """Drive the real §23 -> §25.1 path: deliberate, queue, approve, allocate.

    `amount` is the Cell's own `estimated_cost_minor_units` on a spend_request,
    because that is genuinely where the figure starts — see
    `test_the_denominator_is_ratified_not_merely_asserted`.
    """
    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=_reply(estimated_cost_minor_units=amount)),
        wake_key=wake_key, model="mock-1", proposal_sink=approval.QueueSink(),
    )
    row = conn.execute(
        "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
        (result.proposal_id,),
    ).fetchone()
    grant = approval.approve(
        conn, request_id=row["request_id"], decided_by="operator", reason="worth testing"
    )
    return promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="tiny capped test"
    )


def _start(conn, cell, *, cost: int, rung: int = 1, hypothesis="widgets sell at 4"):
    return experiments.start(
        conn, cell_id=cell.cell_id, hypothesis=hypothesis,
        ladder_rung=rung, expected_cost_minor_units=cost,
    )


# --- the ratio ---------------------------------------------------------------


def test_normalised_cost_divides_the_estimate_by_the_stage_tranche(conn):
    """§13.1, literally. Both inputs stay on the report beside the ratio,
    because §13.1's purpose is unit *consistency* — the raw figures are what an
    operator acts on and the ratio is what can be compared across Cells."""
    _seed_pool(conn)
    cell = _make_cell(conn)
    _promote(conn, cell, amount=200, wake_key="w1")
    experiment = _start(conn, cell, cost=50)

    report = experiments.report(conn, experiment.experiment_id)
    assert report.stage_tranche_minor_units == 200
    assert report.expected_cost_minor_units == 50
    assert report.normalised_cost == 0.25


def test_the_tranche_is_keyed_on_the_cell_not_on_the_experiments_rung(conn):
    """The reading ADR-043 saw coming, and the golden run caught.

    Stage is a property of the **Cell**: §10.5's coroner lists `stage_reached`
    singular beside `experiment_ids` plural, §27.2's dashboard pairs them as one
    field, and ADR-043 named §13.1 itself as the third witness — the formula
    "would be circular if the stage belonged to the experiment", because then
    the experiment's own rung would pick the budget its cost is judged against.

    A Cell promoted to rung 7 running a rung-1 experiment must still divide by
    its rung-7 tranche. An implementation keyed on `experiments.ladder_rung`
    returns `None` here and merely looks conservative — which is exactly how it
    survived until a scenario had a promotion and an experiment at the same rung
    on *different* Cells.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    _promote(conn, cell, amount=200, wake_key="w1")
    experiment = _start(conn, cell, cost=50, rung=1)

    report = experiments.report(conn, experiment.experiment_id)
    assert report.ladder_rung == 1
    assert report.stage_tranche_rung == 7
    assert report.normalised_cost == 0.25


def test_the_current_tranche_is_the_latest_promotion_not_the_total(conn):
    """§13.1 says "*current* stage tranche", singular — an instalment, not a
    running total. `promotion.transfer_degradation` already reads "the Cell's
    latest promotion" the same way. Summing would make a Cell look cheaper every
    time it was funded again, which inverts the meaning of the ratio."""
    _seed_pool(conn)
    cell = _make_cell(conn)
    _promote(conn, cell, amount=100, wake_key="w1")
    _promote(conn, cell, amount=400, wake_key="w2")
    experiment = _start(conn, cell, cost=100)

    report = experiments.report(conn, experiment.experiment_id)
    assert report.stage_tranche_minor_units == 400
    assert report.normalised_cost == 0.25  # not 100/500, and not 100/100


# --- what it must not become -------------------------------------------------


def test_an_unpromoted_cell_reports_no_tranche_rather_than_zero(conn):
    """ADR-042/ADR-043's rule applied to §13.1's denominator: a dimension that
    cannot be measured abstains and says why.

    `0.0` would read as "this experiment is free". `None` with a stated reason
    reads as "the colony has staked no stage capital on this Cell, so there is
    nothing to divide by" — the true statement, and the one that keeps the
    figure out of any average that would otherwise silently include it.
    """
    cell = _make_cell(conn)
    experiment = _start(conn, cell, cost=50)

    report = experiments.report(conn, experiment.experiment_id)
    assert report.normalised_cost is None
    assert report.stage_tranche_minor_units is None
    assert report.stage_tranche_rung is None
    assert any("never been promoted" in note for note in report.unmeasured)


def test_an_over_tranche_experiment_is_reported_never_refused(conn):
    """§13.2 puts experiment cost on a **Pareto frontier** and says plainly "Do
    not rely on a single weighted scalar"; §10.2 forbids the same collapse for
    fitness. So a ratio above 1 is a claim for a human to weigh, not a rule that
    was broken, and nothing in the kernel may turn this one dimension into a
    verdict.

    ADR-039's "second, weaker copy" is the independent reason: what a Cell may
    actually spend is already bounded by its balance (Charter C4), the
    reservation system and the real-spend breaker. A cap here would duplicate
    those and be weaker than all three.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    _promote(conn, cell, amount=100, wake_key="w1")
    experiment = _start(conn, cell, cost=500)

    report = experiments.report(conn, experiment.experiment_id)
    assert report.normalised_cost == 5.0
    assert report.status == experiments.STATUS_RUNNING
    assert experiments.current_for(conn, cell.cell_id) is not None


def test_the_denominator_is_ratified_not_merely_asserted(conn):
    """§23.5: "a field a Cell can fill is a field it will optimise" — so the
    honest statement of what protects this ratio matters.

    **A Cell is not locked out of its own denominator.** `promotion.allocate`
    reads `amount = proposal["estimated_cost_minor_units"]`, so the tranche
    starts life as a number the Cell wrote. What stands between writing it and
    it becoming a denominator is §23's queue: a person saw that exact figure
    (§23.2), said yes, and real capital moved out of a pool only a person can
    fund. A Cell can therefore raise its denominator only by asking for more
    money and being given it, which is the gate working rather than a leak.

    The asymmetry that makes the ratio worth reading is not "Cell versus
    colony", it is **unreviewed versus ratified**: the numerator is a fresh
    claim about an experiment nobody has approved, and the denominator is a
    figure a human already committed capital against. This test pins the half
    that is genuinely structural — a Cell cannot revise the tranche afterwards,
    and cannot steer which tranche its experiment is measured against.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    allocated = _promote(conn, cell, amount=200, wake_key="w1")
    assert allocated.allocated_minor_units == 200

    modest = _start(conn, cell, cost=10)
    assert experiments.report(conn, modest.experiment_id).stage_tranche_minor_units == 200
    experiments.conclude(
        conn, experiment_id=modest.experiment_id, concluded_by="operator", note="done"
    )

    # The Cell moves the numerator by five orders of magnitude. The denominator
    # is untouched, because changing it would have required another approval.
    greedy = _start(conn, cell, cost=999_999, hypothesis="a very expensive idea")
    after = experiments.report(conn, greedy.experiment_id)
    assert after.stage_tranche_minor_units == 200
    assert after.normalised_cost == 999_999 / 200


def test_the_tranche_lookup_takes_nothing_but_a_cell(conn):
    """Structural, and it defends the previous test's second half.

    Every extra parameter on this function would be a channel through which
    something the Cell controls — a proposal, a hypothesis, an estimate, or the
    experiment's own rung — could select *which* tranche its cost is divided by.
    The rung parameter in particular was in the first draft and was the bug.
    """
    assert list(inspect.signature(experiments.stage_tranche).parameters) == [
        "conn",
        "cell_id",
    ]


def test_the_ratio_stays_inside_one_book(conn):
    """§2.4 forbids an implicit exchange rate between books, and a ratio across
    two of them would be exactly that with the units cancelled out of sight.

    It holds by construction rather than by a check: `promotion.allocate`
    allocates in `cells.book`, so a Cell's tranche is always denominated in the
    one book its balance lives in, and the numerator is minor units of that same
    book. This pins the property that makes the division meaningful, so a future
    multi-book allocation path cannot quietly break it.
    """
    _seed_pool(conn)
    cell = _make_cell(conn)
    _promote(conn, cell, amount=200, wake_key="w1")
    row = conn.execute(
        "SELECT book FROM promotions WHERE cell_id = ?", (cell.cell_id,)
    ).fetchone()
    assert row["book"] == cell.book.value
