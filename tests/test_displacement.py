"""§9.3 birth-by-displacement (Amendment A2, ADR-009)."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    cli,
    db,
    death,
    displacement,
    ledger,
    lifecycle,
    lineage,
    population,
    prediction,
    revenue,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellStatus, CellType, EntrySpec, PopulationLimits


def _limits(*, living: int = 2, active: int = 2) -> PopulationLimits:
    return PopulationLimits(
        max_living_cells=living,
        max_active_cells=active,
        max_parallel_experiments=20,
        max_births_per_epoch=25,
        max_lineage_population_fraction=1.0,
    )


def _set_limits(conn, limits: PopulationLimits) -> None:
    population.set_limits_if_absent(conn, limits)
    conn.commit()


def _make_cell(conn, *, key: str, budget: int = 500, cell_type: CellType = CellType.COMMERCIAL):
    return lifecycle.create_cell(
        conn,
        cell_type=cell_type,
        budget_minor_units=budget,
        book=Book.USD_SIM,
        idempotency_key=key,
    )


def _drain(conn, cell, amount: int | None = None) -> None:
    """Spend `amount` (default: the Cell's whole balance, so it meets
    `budget_exhausted`). Either way the spend is realised, which is what makes
    a Cell comparable under §10.5 domination."""
    balance = amount if amount is not None else ledger.get_balance(
        conn, cell_cash(cell.cell_id), cell.book
    )
    ledger.post_transaction(
        conn,
        book=cell.book,
        currency="USD",
        transaction_type="model_call_sim_mirror",
        idempotency_key=f"drain:{cell.cell_id}",
        description="drain",
        entries=[
            EntrySpec(
                account_id=cell_cash(cell.cell_id),
                amount_minor_units=-balance,
                cell_id=cell.cell_id,
            ),
            EntrySpec(
                account_id="infrastructure_reserve",
                amount_minor_units=balance,
                cell_id=cell.cell_id,
            ),
        ],
    )


# --- the constitutional guarantee -------------------------------------------


def test_the_displacer_cannot_see_the_proposed_child():
    """ADR-009 / §9.3: a child's forecast may never trigger a kill.

    The guarantee is structural, so it is asserted structurally: if a
    parameter describing the child ever appears on this seam, the forecast
    becomes reachable and the gaming surface ADR-009 closes by construction
    reopens. Everything the displacer may see describes the colony.
    """
    params = set(inspect.signature(population.Displacer.displace).parameters)
    assert params == {"self", "conn", "require_active", "exclude"}

    impl = set(inspect.signature(displacement.ObjectiveDisplacer.displace).parameters)
    assert impl == params


def test_negative_ev_is_never_a_displaceable_criterion():
    """§10.5 admits negative EV only with strong evidence *and* a concurring
    independent Auditor. Displacement must not become the unsigned back door."""
    assert death.DeathCriterion.NEGATIVE_EV not in displacement.DISPLACEABLE_CRITERIA
    assert death.DeathCriterion.DISPLACEMENT not in displacement.DISPLACEABLE_CRITERIA
    assert death.DeathCriterion.BUDGET_EXHAUSTED in displacement.DISPLACEABLE_CRITERIA


def test_a_healthy_colony_at_capacity_denies_the_birth_rather_than_evicting(conn):
    """§9.3: "If no objectively-failing Cell exists and the colony is at
    capacity, the birth waits." Losing money is not failing — a funded Cell is
    never displaceable, however badly it is doing."""
    _set_limits(conn, _limits(living=2, active=2))
    _make_cell(conn, key="a")
    _make_cell(conn, key="b")

    with pytest.raises(population.CarryingCapacityError) as exc:
        lifecycle.create_cell(
            conn,
            cell_type=CellType.COMMERCIAL,
            budget_minor_units=100,
            book=Book.USD_SIM,
            idempotency_key="c",
            displacer=displacement.ObjectiveDisplacer(),
        )

    assert "no Cell is objectively failing" in str(exc.value)
    assert population.living_count(conn) == 2


# --- the birth path ---------------------------------------------------------


def test_a_birth_at_capacity_displaces_an_objectively_failing_cell(conn):
    _set_limits(conn, _limits(living=2, active=2))
    doomed = _make_cell(conn, key="a")
    _make_cell(conn, key="b")
    _drain(conn, doomed)

    child = lifecycle.create_cell(
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key="c",
        displacer=displacement.ObjectiveDisplacer(),
    )

    assert child.status is CellStatus.ALIVE
    assert lifecycle.get_cell(conn, doomed.cell_id).status is CellStatus.DEAD
    assert population.living_count(conn) == 2


def test_displacement_is_opt_in(conn):
    """Without a displacer the old behaviour stands: denial, not eviction.
    Eviction is a death, and a death is irreversible — a caller has to say so."""
    _set_limits(conn, _limits(living=2, active=2))
    doomed = _make_cell(conn, key="a")
    _make_cell(conn, key="b")
    _drain(conn, doomed)

    with pytest.raises(population.CarryingCapacityError):
        _make_cell(conn, key="c")

    assert lifecycle.get_cell(conn, doomed.cell_id).status is CellStatus.ALIVE


def test_the_coroner_report_records_displacement_and_its_underlying_grounds(conn):
    """A displaced Cell's death must be traceable to the objective criterion it
    already met, not merely to "something needed the slot"."""
    _set_limits(conn, _limits(living=2, active=2))
    doomed = _make_cell(conn, key="a")
    _make_cell(conn, key="b")
    _drain(conn, doomed)

    lifecycle.create_cell(
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key="c",
        displacer=displacement.ObjectiveDisplacer(),
    )

    report = lifecycle.get_coroner_report(conn, doomed.cell_id)
    assert report is not None
    assert report.cause_of_death.startswith("displacement:")
    assert death.DeathCriterion.BUDGET_EXHAUSTED.value in report.cause_of_death


def test_the_birth_records_which_cell_it_displaced(conn):
    """The child cannot influence the selection, but once selection is done the
    audit trail should answer "who took its slot" in both directions."""
    _set_limits(conn, _limits(living=2, active=2))
    doomed = _make_cell(conn, key="a")
    _make_cell(conn, key="b")
    _drain(conn, doomed)

    child = lifecycle.create_cell(
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key="c",
        displacer=displacement.ObjectiveDisplacer(),
    )

    row = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE cell_id = ? "
        "AND event_type = 'cell_lifecycle_transition'",
        (child.cell_id,),
    ).fetchone()
    assert doomed.cell_id in row["metadata_json"]


def test_an_ordinary_birth_is_not_annotated_with_a_displacement(conn):
    _set_limits(conn, _limits(living=10, active=10))
    child = _make_cell(conn, key="a")

    row = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE cell_id = ? "
        "AND event_type = 'cell_lifecycle_transition'",
        (child.cell_id,),
    ).fetchone()
    assert "displaced_cell_id" not in row["metadata_json"]


# --- the three restrictions -------------------------------------------------


def test_a_parent_never_displaces_itself_to_birth_its_own_child(conn):
    """The child is funded from the parent's cash. Displacing the parent would
    move money out of a dead Cell (Charter C8), and would let a lineage buy
    room by killing its own root."""
    _set_limits(conn, _limits(living=2, active=2))
    parent = _make_cell(conn, key="a")
    other = _make_cell(conn, key="b")

    # Make the parent itself objectively failing on the domination criterion,
    # while keeping enough cash to fund a child.
    revenue.record_revenue(
        conn,
        cell_id=other.cell_id,
        amount_minor_units=900,
        book=Book.USD_SIM,
        source="invoice:test",
    )
    _drain(conn, parent)
    ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="cell_birth_funding",
        idempotency_key="refund-parent",
        description="give the parent cash back",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-300, cell_id=parent.cell_id),
            EntrySpec(
                account_id=cell_cash(parent.cell_id),
                amount_minor_units=300,
                cell_id=parent.cell_id,
            ),
        ],
    )
    assert death.is_objectively_failing(conn, parent.cell_id)

    with pytest.raises(population.CarryingCapacityError):
        lineage.reproduce(
            conn,
            parent_cell_id=parent.cell_id,
            budget_minor_units=100,
            idempotency_key="child",
            displacer=displacement.ObjectiveDisplacer(),
        )

    assert lifecycle.get_cell(conn, parent.cell_id).status is CellStatus.ALIVE


def test_a_cell_mid_operation_is_never_displaced(conn):
    """Committed funds mean a reservation is open; killing then strands it,
    since kill() sweeps nothing.

    The Cell here is **genuinely objectively failing** — dominated by a
    near-duplicate on realised record — so `death.findings` is non-empty and
    this guard is the only thing standing between it and eviction. Reaching
    for `budget_exhausted` instead would test nothing: that criterion already
    refuses to fire while funds are committed, so `death` would do the work
    and the guard could be deleted with every test still green.
    """
    from mitosis import reservations

    _set_limits(conn, _limits(living=2, active=2))
    busy = _make_cell(conn, key="a")
    peer = _make_cell(conn, key="b")

    _drain(conn, busy, 200)
    revenue.record_revenue(
        conn,
        cell_id=peer.cell_id,
        amount_minor_units=900,
        book=Book.USD_SIM,
        source="invoice:test",
    )
    reservations.request(
        conn,
        cell_id=busy.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=100,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key="res",
    )

    assert death.is_objectively_failing(conn, busy.cell_id)
    assert displacement.candidates(conn) == []

    with pytest.raises(population.CarryingCapacityError):
        lifecycle.create_cell(
            conn,
            cell_type=CellType.COMMERCIAL,
            budget_minor_units=100,
            book=Book.USD_SIM,
            idempotency_key="c",
            displacer=displacement.ObjectiveDisplacer(),
        )
    assert lifecycle.get_cell(conn, busy.cell_id).status is CellStatus.ALIVE


def test_displacing_a_dormant_cell_cannot_relieve_the_active_cap(conn):
    """Only killing an `alive` Cell frees an active slot. Evicting a dormant one
    to relieve an active-cap breach would be a death that bought nothing."""
    _set_limits(conn, _limits(living=10, active=1))
    sleeping = _make_cell(conn, key="a")
    _drain(conn, sleeping)
    lifecycle.sleep(conn, sleeping.cell_id)
    _make_cell(conn, key="b")  # the one active Cell, healthy

    assert displacement.candidates(conn, require_active=False) != []
    assert displacement.candidates(conn, require_active=True) == []

    with pytest.raises(population.CarryingCapacityError):
        lifecycle.create_cell(
            conn,
            cell_type=CellType.COMMERCIAL,
            budget_minor_units=100,
            book=Book.USD_SIM,
            idempotency_key="c",
            displacer=displacement.ObjectiveDisplacer(),
        )
    assert lifecycle.get_cell(conn, sleeping.cell_id).status is CellStatus.DORMANT


def test_a_dormant_failing_cell_can_relieve_the_living_cap(conn):
    """The converse: when it is the living cap that binds, any living Cell is a
    valid target, dormant included."""
    _set_limits(conn, _limits(living=2, active=10))
    sleeping = _make_cell(conn, key="a")
    _drain(conn, sleeping)
    lifecycle.sleep(conn, sleeping.cell_id)
    _make_cell(conn, key="b")

    lifecycle.create_cell(
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key="c",
        displacer=displacement.ObjectiveDisplacer(),
    )
    assert lifecycle.get_cell(conn, sleeping.cell_id).status is CellStatus.DEAD


# --- atomicity and bounding -------------------------------------------------


def test_only_one_cell_is_ever_displaced_per_birth(conn):
    _set_limits(conn, _limits(living=3, active=3))
    a, b, c = (_make_cell(conn, key=k) for k in "abc")
    for cell in (a, b, c):
        _drain(conn, cell)

    lifecycle.create_cell(
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key="d",
        displacer=displacement.ObjectiveDisplacer(),
    )

    dead = [
        cell
        for cell in (a, b, c)
        if lifecycle.get_cell(conn, cell.cell_id).status is CellStatus.DEAD
    ]
    assert len(dead) == 1


def test_the_lineage_cap_is_checked_against_the_population_displacement_leaves(conn):
    """Eviction shrinks the living population, which *raises* every surviving
    lineage's share — so §9.4's cap has to be checked after displacement, not
    before, and the rollback has to undo the eviction when it fails.

    The numbers are chosen so the ordering is the only thing under test. Cap
    0.5, three living Cells, a founder lineage of one: *before* displacement
    the projection is 2/4 = 0.50 and passes; *after* it is 2/3 = 0.67 and
    fails. Check it first and the birth succeeds into a colony that violates
    §9.4, having killed a Cell to get there.
    """
    _set_limits(
        conn,
        PopulationLimits(
            max_living_cells=3,
            max_active_cells=3,
            max_parallel_experiments=20,
            max_births_per_epoch=25,
            max_lineage_population_fraction=0.50,
        ),
    )
    parent = _make_cell(conn, key="a")
    doomed = _make_cell(conn, key="b")
    _make_cell(conn, key="c")
    _drain(conn, doomed)

    with pytest.raises(lineage.LineageCapExceededError):
        lineage.reproduce(
            conn,
            parent_cell_id=parent.cell_id,
            budget_minor_units=100,
            idempotency_key="child",
            displacer=displacement.ObjectiveDisplacer(),
        )

    # The eviction rolled back with the birth: one atomic step, or neither.
    assert lifecycle.get_cell(conn, doomed.cell_id).status is CellStatus.ALIVE
    assert lifecycle.get_coroner_report(conn, doomed.cell_id) is None
    assert population.living_count(conn) == 3
    assert ledger.verify_chain(conn)
    assert ledger.verify_conservation(conn, Book.USD_SIM)


def test_reproduction_can_displace_a_cell_outside_its_lineage(conn):
    _set_limits(conn, _limits(living=2, active=2))
    parent = _make_cell(conn, key="a")
    doomed = _make_cell(conn, key="b")
    _drain(conn, doomed)

    child = lineage.reproduce(
        conn,
        parent_cell_id=parent.cell_id,
        budget_minor_units=100,
        idempotency_key="child",
        displacer=displacement.ObjectiveDisplacer(),
    )

    assert child.parent_cell_id == parent.cell_id
    assert lifecycle.get_cell(conn, doomed.cell_id).status is CellStatus.DEAD
    assert ledger.verify_chain(conn)
    assert ledger.verify_conservation(conn, Book.USD_SIM)


def test_candidate_order_is_deterministic_and_not_a_ranking(conn):
    """Order is birth order, so replay is deterministic (§26). Ranking by how
    badly a Cell is doing would reintroduce §10.2's forbidden scalar collapse
    as "pick the worst one"."""
    _set_limits(conn, _limits(living=5, active=5))
    cells = [_make_cell(conn, key=k) for k in "abc"]
    for cell in cells:
        _drain(conn, cell)

    # Give the middle Cell the worst realised record of the three: a confident
    # call that went the other way. Order must not move — it is still the
    # second candidate, not the first.
    registered = prediction.register(
        conn,
        cell_id=cells[1].cell_id,
        claim="revenue >= 50 minor units by epoch 4",
        probability=0.95,
        resolves_by=datetime.now(timezone.utc) + timedelta(days=1),
    )
    prediction.resolve(conn, registered.prediction_id, occurred=False, source="test")

    ordered = [cell.cell_id for cell, _ in displacement.candidates(conn)]
    assert ordered == [c.cell_id for c in cells]


def test_a_displacer_that_frees_the_wrong_slot_cannot_sneak_a_birth_past_the_cap(conn):
    """`Displacer` is a seam, so the caps are re-checked after it runs rather
    than assumed relieved. A displacer that ignores `require_active` must
    produce a denied birth — never a birth over the cap, and never a second
    kill to chase the slot it missed."""

    class WrongSlotDisplacer:
        def displace(self, conn, *, require_active, exclude):
            cell, finding = displacement.candidates(conn, require_active=False)[0]
            lifecycle._kill_locked(conn, cell, cause_of_death="wrong slot")
            return population.Displacement(
                cell_id=cell.cell_id, criterion=finding.criterion.value, evidence={}
            )

    _set_limits(conn, _limits(living=10, active=1))
    sleeping = _make_cell(conn, key="a")
    _drain(conn, sleeping)
    lifecycle.sleep(conn, sleeping.cell_id)
    _make_cell(conn, key="b")

    with pytest.raises(population.CarryingCapacityError) as exc:
        lifecycle.create_cell(
            conn,
            cell_type=CellType.COMMERCIAL,
            budget_minor_units=100,
            book=Book.USD_SIM,
            idempotency_key="c",
            displacer=WrongSlotDisplacer(),
        )

    assert "did not free a slot" in str(exc.value)
    assert lifecycle.get_cell(conn, sleeping.cell_id).status is CellStatus.DORMANT
    assert population.active_count(conn) == 1


# --- CLI --------------------------------------------------------------------


def _cli_colony(tmp_path, *, living: int, active: int):
    """A CLI-driven colony with tight caps.

    The caps are written with raw SQL because there is no supported path to
    change a population limit after `init`: `set_limits_if_absent` is
    deliberately write-once, and unlike the real-spend breaker there is no
    audited raise/lower verb. That gap is logged in FUTURE_BUILD_HOOKS — it is
    also why the golden run cannot reach carrying capacity to exercise
    displacement.
    """
    db_path = tmp_path / "colony.db"
    cli.main(["--db", str(db_path), "init"])
    connection = db.connect_and_migrate(db_path)
    connection.execute(
        "UPDATE colony_config SET max_living_cells = ?, max_active_cells = ? WHERE id = 1",
        (living, active),
    )
    connection.commit()
    return db_path, connection


def test_cli_displacement_candidates_reports_nothing_for_a_healthy_colony(tmp_path, capsys):
    db_path, connection = _cli_colony(tmp_path, living=2, active=2)
    _make_cell(connection, key="a")
    connection.close()

    assert cli.main(["--db", str(db_path), "displacement-candidates"]) == 0
    out = capsys.readouterr().out
    assert "No Cell may currently be displaced" in out
    assert "would wait, not evict" in out


def test_cli_create_cell_can_displace_at_capacity(tmp_path, capsys):
    db_path, connection = _cli_colony(tmp_path, living=2, active=2)
    doomed = _make_cell(connection, key="a")
    _make_cell(connection, key="b")
    _drain(connection, doomed)
    connection.close()

    # Without --displace the birth is refused; the flag is the whole consent.
    assert (
        cli.main(
            ["--db", str(db_path), "create-cell", "--type", "explorer", "--budget", "1.00"]
        )
        == 1
    )
    assert "at capacity" in capsys.readouterr().err

    assert (
        cli.main(
            [
                "--db", str(db_path), "create-cell",
                "--type", "explorer", "--budget", "1.00", "--displace",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert f"displaced: {doomed.cell_id}" in out
    assert "budget_exhausted" in out
