"""Death criteria (SPEC.md §10.5, Amendment A15; §9.3 displacement hook).

§10.5 is more restrictive than "kill the unprofitable", and most of these tests
exist to hold that line. The criteria are objective and realised; estimated
negative EV cannot kill on its own; and a Cell that is merely doing badly must
survive. The last one is the easiest to break by accident and the most damaging
if broken, because nothing would report it — the colony would simply stop
exploring.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mitosis import death, ledger, lifecycle, prediction, real_spend_breaker, reservations, revenue
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellStatus, CellType, EntrySpec


def _cell(conn, *, cell_type=CellType.EXPLORER, budget=1_000, key="c", book=Book.USD_SIM):
    return lifecycle.create_cell(
        conn,
        cell_type=cell_type,
        budget_minor_units=budget,
        book=book,
        idempotency_key=key,
    )


def _drain(conn, cell):
    """Spend a Cell's entire balance to external_expense — realised, not
    simulated: this is the same path a settled reservation takes."""
    cash = ledger.get_balance(conn, cell_cash(cell.cell_id), cell.book)
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=cell.book,
        currency="USD",
        maximum_amount=cash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        idempotency_key=f"drain:{cell.cell_id}",
    )
    reservations.settle(
        conn,
        reservation.reservation_id,
        settled_amount=cash,
        destination_account_id="external_expense",
    )


def _predict(conn, cell, *, probability, occurred, key):
    registered = prediction.register(
        conn,
        cell_id=cell.cell_id,
        claim=f"claim {key}",
        probability=probability,
        resolves_by=datetime.now(timezone.utc) + timedelta(days=1),
        idempotency_key=key,
    )
    prediction.resolve(conn, registered.prediction_id, occurred=occurred, source="test")


# --- the line §10.5 draws ---------------------------------------------------


def test_losing_money_is_not_a_death_criterion(conn):
    """The single most important test here. A Cell that spent and earned less
    than it spent is *doing badly*, which §10.5 does not make fatal — negative
    EV needs strong evidence and a concurring Auditor. Break this and the colony
    culls on estimates, which selects for Cells that look good to the estimator.
    """
    cell = _cell(conn, budget=1_000)
    reservation = reservations.request(
        conn, cell_id=cell.cell_id, book=Book.USD_SIM, currency="USD", maximum_amount=600,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), idempotency_key="r",
    )
    reservations.settle(
        conn, reservation.reservation_id, settled_amount=600,
        destination_account_id="external_expense",
    )
    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=100, source="inv", book=Book.USD_SIM
    )

    record = death.contribution(conn, cell)
    assert record.net_contribution == -500, "unambiguously unprofitable"
    assert death.findings(conn, cell.cell_id) == []
    assert death.reap(conn) == []


def test_budget_exhaustion_is_a_death_criterion(conn):
    """"Stage budget exhausted": having none left, as opposed to losing money."""
    cell = _cell(conn, budget=1_000)
    _drain(conn, cell)

    found = death.findings(conn, cell.cell_id)
    assert [f.criterion for f in found] == [death.DeathCriterion.BUDGET_EXHAUSTED]
    assert found[0].evidence["cash"] == 0
    assert death.is_objectively_failing(conn, cell.cell_id)


def test_a_cell_mid_operation_is_never_exhausted(conn):
    """Zero cash with funds committed means a call is in flight. Killing then
    would strand the reservation."""
    cell = _cell(conn, budget=1_000)
    reservations.request(
        conn, cell_id=cell.cell_id, book=Book.USD_SIM, currency="USD", maximum_amount=1_000,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), idempotency_key="inflight",
    )
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_SIM) == 0
    assert death.findings(conn, cell.cell_id) == []


# --- reap ------------------------------------------------------------------


def test_reap_is_dry_run_by_default(conn):
    cell = _cell(conn, budget=500)
    _drain(conn, cell)

    found = death.reap(conn)
    assert len(found) == 1
    assert lifecycle.get_cell(conn, cell.cell_id).status is CellStatus.ALIVE, "not killed"

    death.reap(conn, dry_run=False)
    assert lifecycle.get_cell(conn, cell.cell_id).status is CellStatus.DEAD


def test_reap_files_a_coroner_report_naming_the_criterion(conn):
    cell = _cell(conn, budget=500)
    _drain(conn, cell)
    death.reap(conn, dry_run=False)

    row = conn.execute(
        "SELECT cause_of_death FROM coroner_reports WHERE cell_id = ?", (cell.cell_id,)
    ).fetchone()
    assert "budget_exhausted" in row["cause_of_death"]


def test_reap_leaves_healthy_cells_alone(conn):
    healthy = _cell(conn, budget=1_000, key="healthy")
    doomed = _cell(conn, budget=500, key="doomed")
    _drain(conn, doomed)

    death.reap(conn, dry_run=False)
    assert lifecycle.get_cell(conn, healthy.cell_id).status is CellStatus.ALIVE
    assert lifecycle.get_cell(conn, doomed.cell_id).status is CellStatus.DEAD


def test_a_dead_cell_has_no_findings(conn):
    cell = _cell(conn, budget=500)
    _drain(conn, cell)
    death.reap(conn, dry_run=False)
    assert death.findings(conn, cell.cell_id) == []


# --- Pareto domination (§10.2: no scalar collapse) --------------------------


def test_domination_requires_being_better_on_every_dimension(conn):
    """Better on net contribution but worse on calibration is not domination.
    §10.2 forbids collapsing the dimensions, and this is what that means in
    practice: a trade-off is not a verdict."""
    rich = _cell(conn, budget=1_000, key="rich")
    calibrated = _cell(conn, budget=1_000, key="calibrated")
    for cell in (rich, calibrated):
        revenue.record_revenue(
            conn, cell_id=cell.cell_id, amount_minor_units=100, source=f"s{cell.cell_id}",
            book=Book.USD_SIM,
        )
    revenue.record_revenue(
        conn, cell_id=rich.cell_id, amount_minor_units=500, source="extra", book=Book.USD_SIM
    )
    # rich earns more but predicts worse
    _predict(conn, rich, probability=0.1, occurred=True, key="rich-bad")
    _predict(conn, calibrated, probability=0.9, occurred=True, key="cal-good")

    assert death.findings(conn, calibrated.cell_id) == []
    assert death.findings(conn, rich.cell_id) == []


def test_domination_kills_only_when_strictly_worse_everywhere(conn):
    better = _cell(conn, budget=1_000, key="better")
    worse = _cell(conn, budget=1_000, key="worse")
    revenue.record_revenue(
        conn, cell_id=better.cell_id, amount_minor_units=500, source="b", book=Book.USD_SIM
    )
    revenue.record_revenue(
        conn, cell_id=worse.cell_id, amount_minor_units=100, source="w", book=Book.USD_SIM
    )
    _predict(conn, better, probability=0.9, occurred=True, key="b1")
    _predict(conn, worse, probability=0.6, occurred=True, key="w1")

    found = death.findings(conn, worse.cell_id)
    assert [f.criterion for f in found] == [death.DeathCriterion.DOMINATED_BY_NEAR_DUPLICATE]
    assert found[0].evidence["dominated_by"] == better.cell_id
    assert death.findings(conn, better.cell_id) == []


def test_an_idle_cell_does_not_dominate_one_that_invested(conn):
    """The trap this gate exists for: on net contribution alone, a Cell that did
    nothing (net 0) beats one that spent and has not yet returned. That selects
    for inactivity, which quietly ends the experiment."""
    idle = _cell(conn, budget=1_000, key="idle")
    investor = _cell(conn, budget=1_000, key="investor")
    reservation = reservations.request(
        conn, cell_id=investor.cell_id, book=Book.USD_SIM, currency="USD", maximum_amount=300,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), idempotency_key="invest",
    )
    reservations.settle(
        conn, reservation.reservation_id, settled_amount=300,
        destination_account_id="external_expense",
    )

    assert death.contribution(conn, idle).net_contribution == 0
    assert death.contribution(conn, investor).net_contribution == -300
    assert death.findings(conn, investor.cell_id) == [], "idle must not dominate"


def test_cells_with_different_genomes_are_not_near_duplicates(conn):
    """§10.3: Explorers need no immediate revenue, so comparing one against a
    revenue-earning Commercial would kill exactly the Cells whose value is
    exploratory. The near-duplicate restriction handles that without a special
    case."""
    explorer = _cell(conn, cell_type=CellType.EXPLORER, key="ex")
    commercial = _cell(conn, cell_type=CellType.COMMERCIAL, key="com")
    assert explorer.genome_hash != commercial.genome_hash

    revenue.record_revenue(
        conn, cell_id=commercial.cell_id, amount_minor_units=900, source="c", book=Book.USD_SIM
    )
    reservation = reservations.request(
        conn, cell_id=explorer.cell_id, book=Book.USD_SIM, currency="USD", maximum_amount=200,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), idempotency_key="ex-spend",
    )
    reservations.settle(
        conn, reservation.reservation_id, settled_amount=200,
        destination_account_id="external_expense",
    )
    assert death.findings(conn, explorer.cell_id) == []


# --- the negative-EV guard (§10.5's constitutional constraint) --------------


def test_negative_ev_is_never_reachable_from_reap(conn):
    assert death.DeathCriterion.NEGATIVE_EV not in death.AUTOMATIC_CRITERIA


def test_negative_ev_death_requires_a_concurring_auditor(conn):
    subject = _cell(conn, key="subject")
    with pytest.raises(TypeError):
        death.kill_for_negative_ev(conn, subject.cell_id, evidence="looks bad")  # type: ignore[call-arg]


def test_a_cell_cannot_concur_in_its_own_death(conn):
    subject = _cell(conn, cell_type=CellType.AUDITOR, key="self")
    with pytest.raises(death.DeathError, match="cannot concur in its own death"):
        death.kill_for_negative_ev(
            conn,
            subject.cell_id,
            evidence="strong",
            concurring_auditor_cell_id=subject.cell_id,
        )
    assert lifecycle.get_cell(conn, subject.cell_id).status is CellStatus.ALIVE


def test_only_an_auditor_or_immune_cell_can_concur(conn):
    subject = _cell(conn, key="subject")
    bystander = _cell(conn, cell_type=CellType.BUILDER, key="builder")
    with pytest.raises(death.DeathError, match="not an auditor or immune"):
        death.kill_for_negative_ev(
            conn, subject.cell_id, evidence="strong",
            concurring_auditor_cell_id=bystander.cell_id,
        )
    assert lifecycle.get_cell(conn, subject.cell_id).status is CellStatus.ALIVE


def test_a_dead_auditor_cannot_concur(conn):
    subject = _cell(conn, key="subject")
    auditor = _cell(conn, cell_type=CellType.AUDITOR, key="auditor")
    lifecycle.kill(conn, auditor.cell_id, cause_of_death="test")

    with pytest.raises(death.DeathError, match="not alive"):
        death.kill_for_negative_ev(
            conn, subject.cell_id, evidence="strong",
            concurring_auditor_cell_id=auditor.cell_id,
        )
    assert lifecycle.get_cell(conn, subject.cell_id).status is CellStatus.ALIVE


def test_negative_ev_death_requires_stated_evidence(conn):
    subject = _cell(conn, key="subject")
    auditor = _cell(conn, cell_type=CellType.AUDITOR, key="auditor")
    with pytest.raises(death.DeathError, match="evidence is required"):
        death.kill_for_negative_ev(
            conn, subject.cell_id, evidence="   ",
            concurring_auditor_cell_id=auditor.cell_id,
        )


def test_a_properly_concurred_negative_ev_death_proceeds_and_is_traceable(conn):
    subject = _cell(conn, key="subject")
    auditor = _cell(conn, cell_type=CellType.AUDITOR, key="auditor")

    killed = death.kill_for_negative_ev(
        conn,
        subject.cell_id,
        evidence="12 consecutive unprofitable settlements, reproduced twice",
        concurring_auditor_cell_id=auditor.cell_id,
    )
    assert killed.status is CellStatus.DEAD

    row = conn.execute(
        "SELECT cause_of_death FROM coroner_reports WHERE cell_id = ?", (subject.cell_id,)
    ).fetchone()
    assert "negative_ev" in row["cause_of_death"]
    assert auditor.cell_id in row["cause_of_death"], "who agreed is recoverable from the report"

    event = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'negative_ev_death_concurred'"
    ).fetchone()
    assert auditor.cell_id in event["metadata_json"]


# --- §9.3 displacement hook -------------------------------------------------


def test_is_objectively_failing_is_the_displacement_seam(conn):
    """§9.3: "a child may displace only a Cell already failing objective
    criteria". Displacement was blocked on this predicate existing."""
    healthy = _cell(conn, budget=1_000, key="healthy")
    failing = _cell(conn, budget=500, key="failing")
    _drain(conn, failing)

    assert not death.is_objectively_failing(conn, healthy.cell_id)
    assert death.is_objectively_failing(conn, failing.cell_id)


def test_unknown_cell_is_refused_rather_than_reported_healthy(conn):
    with pytest.raises(death.DeathError, match="no such cell"):
        death.findings(conn, "not-a-cell")
