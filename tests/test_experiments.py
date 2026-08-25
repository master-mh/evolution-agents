"""The experiment (SPEC.md §2.5, §2.6, §9.2, §10.5, §13.1, §15.1, §25.1, §31;
Charter C3; ADR-031, ADR-043).

Seven sections reference an experiment and none defines one; §2.6 defines its
*report*, and §2.5 — the clause immediately above — says authoritative figures
are derived from ledger entries and never cached. These defend that reading, and
the two things it must never become: a place a Cell can write what its work
achieved (§0.3), or a second answer to a question the kernel already answers.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mitosis import (
    db,
    death,
    experiments,
    ledger,
    lifecycle,
    population,
    prediction,
    revenue,
)
from mitosis.models import Book, CellType, EntrySpec, PopulationLimits

SRC = pathlib.Path(experiments.__file__).parent


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    population.set_limits_if_absent(
        connection,
        PopulationLimits(
            max_living_cells=1000,
            max_active_cells=100,
            max_parallel_experiments=2,
            max_births_per_epoch=25,
            max_lineage_population_fraction=0.20,
        ),
    )
    connection.commit()
    yield connection
    connection.close()


def _cell(conn, key="a"):
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=100,
        book=Book.USD_SIM, idempotency_key=key,
    )
    conn.commit()
    return lifecycle.get_cell(conn, cell.cell_id)


def _start(conn, cell, *, hypothesis="widgets sell at £4", rung=1, cost=0):
    return experiments.start(
        conn, cell_id=cell.cell_id, hypothesis=hypothesis,
        ladder_rung=rung, expected_cost_minor_units=cost,
    )


def _post(conn, *, book, currency, account, amount, experiment_id, key, cell_id=None):
    """Post a transaction tagged with an experiment, which is the shape
    `reservations.settle` already builds."""
    ledger.post_transaction(
        conn, book=book, currency=currency,
        transaction_type="cell_birth_funding",
        idempotency_key=key, description="fixture",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
            EntrySpec(
                account_id=account, amount_minor_units=amount,
                cell_id=cell_id, experiment_id=experiment_id,
            ),
        ],
    )


# --- §2.5/§2.6: the report is derived, never stored ---------------------------


def test_there_is_no_experiment_results_table(conn):
    """ADR-043's one refusal, made structural.

    §31 lists an `experiment_results` entity and this kernel deliberately does
    not build it: §2.5 says authoritative figures are derived from ledger
    entries and never cached (Charter C3), and §2.6's report is entirely such
    figures. A stored outcome table is where §0.3 leaks back in — a Cell may
    explain a result and never define one, and the surest way to keep that true
    is to give it no column to write.

    If a later slice adds one, this test should be deleted deliberately and the
    ADR revisited — not quietly amended.
    """
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "experiment_results" not in tables


def test_resource_usage_has_no_experiment_id_column(conn):
    """ADR-044's refusal, made structural — the sibling of the one above.

    The obvious fix for "human labour is unattributable" is a column on
    `resource_usage`, and PRIORITIES, BUILD_RECORD and this module's own
    docstring all called for one. It was never needed:
    `resource_usage.reservation_id` is NOT NULL and `reservations.experiment_id`
    has existed since migration 0001, so every metered row is one join from its
    experiment. A column would be a second answer to a question the reservation
    already answers, and the two can disagree — a row stamped with one
    experiment hanging off a reservation stamped with another, with nothing in
    the schema preferring either.

    That is the cached-derivation trap §2.5 and Charter C3 exist to prevent,
    reached from the metering side instead of the balance side.
    """
    columns = {
        r["name"] for r in conn.execute("PRAGMA table_info(resource_usage)")
    }
    assert "experiment_id" not in columns, (
        "resource_usage grew an experiment_id. It is already reachable through "
        "reservation_id (NOT NULL) — see ADR-044 before keeping this."
    )
    reservation_columns = {
        r["name"] for r in conn.execute("PRAGMA table_info(reservations)")
    }
    assert "experiment_id" in reservation_columns
    not_null = {
        r["name"] for r in conn.execute("PRAGMA table_info(resource_usage)") if r["notnull"]
    }
    assert "reservation_id" in not_null, (
        "the join this design rests on is only total because reservation_id "
        "cannot be null (Amendment A6)"
    )


def test_the_experiment_a_cost_belongs_to_is_derived_never_supplied(conn):
    """§0.3 reached from the expense side, made structural.

    Which experiment bears a cost is an answer about what an experiment cost.
    §15.1 gives a Cell one current experiment, so that answer is already
    determined and nothing needs to ask for it — and a metering entry point that
    accepted an `experiment_id` would be a place to put a different one. A Cell
    that could name the experiment could make its own look cheap by naming
    another, which is exactly the shape `proposal.py` has no field for.

    Signatures rather than behaviour, because the failure this guards against is
    a parameter being *added* — which no behavioural test would notice until
    something passed it.
    """
    import inspect

    from mitosis import external_actions, tools

    for func in (tools.execute_grant, external_actions.claim, external_actions.complete):
        assert "experiment_id" not in inspect.signature(func).parameters, (
            f"{func.__module__}.{func.__name__} accepts an experiment_id. "
            "Attribution is derived from the Cell's running experiment "
            "(experiments.attribution_for), not supplied — see ADR-044."
        )


def test_the_report_follows_the_ledger(conn):
    """§2.5 applied to experiments: change the books, the report changes, with
    nothing recomputed or invalidated. A stored figure would drift the moment a
    reconciliation adjustment landed."""
    cell = _cell(conn)
    experiment = _start(conn, cell)
    assert experiments.report(conn, experiment.experiment_id).real_spend_minor_units == 0

    _post(conn, book=Book.USD_REAL, currency="USD", account="external_expense",
          amount=7, experiment_id=experiment.experiment_id, key="spend:1")

    assert experiments.report(conn, experiment.experiment_id).real_spend_minor_units == 7


def test_the_report_separates_the_three_books(conn):
    """§2.4 forbids bridging the books, and §2.6 reports them separately for the
    same reason: a single "cost" number would need an exchange rate the spec
    refuses to define."""
    cell = _cell(conn)
    experiment = _start(conn, cell)
    for book, currency, key in (
        (Book.USD_REAL, "USD", "r"), (Book.USD_SIM, "USD", "s"), (Book.RESOURCE, "RESOURCE", "c")
    ):
        _post(conn, book=book, currency=currency, account="external_expense",
              amount=11, experiment_id=experiment.experiment_id, key=f"spend:{key}")

    report = experiments.report(conn, experiment.experiment_id)
    assert report.real_spend_minor_units == 11
    assert report.synthetic_spend_minor_units == 11
    assert report.resource_spend_minor_units == 11


def test_revenue_earned_under_an_experiment_reaches_its_report(conn):
    """§2.6 leads with "synthetic revenue/profit". Revenue posts a negative leg
    to the `revenue` account, so the report has to read that account and negate
    — reading the Cell's cash leg instead would count every credit as earnings.
    """
    cell = _cell(conn)
    experiment = _start(conn, cell)
    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=40, source="fixture",
        book=Book.USD_SIM, experiment_id=experiment.experiment_id,
        idempotency_key="rev:1",
    )
    report = experiments.report(conn, experiment.experiment_id)
    assert report.synthetic_revenue_minor_units == 40
    assert report.synthetic_net_profit_minor_units == 40


def test_net_profit_is_revenue_minus_spend(conn):
    cell = _cell(conn)
    experiment = _start(conn, cell)
    revenue.record_revenue(
        conn, cell_id=cell.cell_id, amount_minor_units=40, source="fixture",
        book=Book.USD_SIM, experiment_id=experiment.experiment_id, idempotency_key="rev:1",
    )
    _post(conn, book=Book.USD_SIM, currency="USD", account="external_expense",
          amount=15, experiment_id=experiment.experiment_id, key="spend:sim")

    report = experiments.report(conn, experiment.experiment_id)
    assert report.synthetic_net_profit_minor_units == 25


def test_an_unmeasurable_dimension_reports_as_unmeasurable_not_zero(conn):
    """§2.6 asks for sandbox CPU, and §19.3's sandbox is Phase 5, so nothing in
    this kernel can attribute a CPU-second. Reporting `0` would be *claiming* it
    consumed none — the trap ADR-042 hit when a crashed tick recorded that it
    spent nothing: a false statement rather than a missing one.

    Human labour used to be on this list and is not any more (ADR-044). It was
    never unmeasurable; it was unstamped. If the reason a dimension abstains is
    ever again "a column does not exist", check whether the join already reaches
    it before believing the claim.
    """
    cell = _cell(conn)
    experiment = _start(conn, cell)
    report = experiments.report(conn, experiment.experiment_id)
    assert report.sandbox_cpu_seconds is None
    assert len(report.unmeasured) == 1
    assert any("sandbox" in note for note in report.unmeasured)
    assert not any("HUMAN_MINUTES" in note for note in report.unmeasured)


def test_the_reality_gap_counts_unresolved_forecasts_separately(conn):
    """§8.5 via §2.6. `prediction.py` is blunt that "a mean Brier score over
    three cherry-picked resolutions is worse than useless", so the open count
    sits beside the score rather than being folded into it — a report showing
    only a mean would look identical whether one forecast resolved or fifty.
    """
    cell = _cell(conn)
    experiment = _start(conn, cell)
    for i in range(3):
        prediction.register(
            conn, cell_id=cell.cell_id, claim=f"claim {i}", probability=0.6,
            resolves_by=experiment.created_at_utc.replace(year=experiment.created_at_utc.year + 1),
            experiment_id=experiment.experiment_id, idempotency_key=f"p{i}",
        )
    report = experiments.report(conn, experiment.experiment_id)
    assert report.reality_gap_mean_brier is None
    assert report.resolved_predictions == 0
    assert report.unresolved_predictions == 3


# --- §9.2: the third refusal shape --------------------------------------------


def test_the_colony_refuses_more_than_max_parallel_experiments(conn):
    """§9.2's "maximum simultaneous experiments" — the last of its seven limits
    that was stored and never checked."""
    for i in range(2):
        _start(conn, _cell(conn, key=f"c{i}"))
    with pytest.raises(experiments.ExperimentCapacityError):
        _start(conn, _cell(conn, key="overflow"))


def test_the_capacity_refusal_is_neither_of_the_population_ones(conn):
    """ADR-031 separated durable carrying capacity from a temporary birth rate,
    because confusing them invites the wrong remedy — displacement for a queue,
    or waiting for a cap no clock clears. This is a third shape: the slot frees
    when an experiment *concludes*. It must not be catchable as either.
    """
    assert not issubclass(experiments.ExperimentCapacityError, population.PopulationError)
    assert not issubclass(experiments.ExperimentCapacityError, population.CarryingCapacityError)
    assert issubclass(experiments.ExperimentCapacityError, experiments.ExperimentError)


def test_concluding_frees_a_slot(conn):
    """The property that makes it a third shape rather than a carrying-capacity
    problem: nothing has to die for the colony to run another experiment."""
    first = _start(conn, _cell(conn, key="c0"))
    _start(conn, _cell(conn, key="c1"))
    blocked = _cell(conn, key="c2")
    with pytest.raises(experiments.ExperimentCapacityError):
        _start(conn, blocked)

    experiments.conclude(
        conn, experiment_id=first.experiment_id, concluded_by="op", note="answered"
    )
    assert _start(conn, blocked).is_running
    assert conn.execute("SELECT COUNT(*) AS n FROM cells WHERE status = 'dead'").fetchone()["n"] == 0


def test_an_abandoned_experiment_is_distinguishable_from_a_concluded_one(conn):
    """§10.5 treats deaths as the colony's cheapest training data and the same
    holds here: an experiment that ran to a negative finding is evidence, one
    that was dropped is not. Collapsing them would inflate the record of what
    the colony has actually learned.
    """
    cell = _cell(conn)
    experiment = _start(conn, cell)
    ended = experiments.conclude(
        conn, experiment_id=experiment.experiment_id, concluded_by="op",
        note="ran out of budget", abandoned=True,
    )
    assert ended.status == experiments.STATUS_ABANDONED
    assert ended.status != experiments.STATUS_CONCLUDED


# --- §15.1: current experiment, singular --------------------------------------


def test_a_cell_can_only_run_one_experiment_at_a_time(conn):
    """§15.1 assembles context from the Cell's "current experiment" — singular,
    and §27.2's dashboard says "current experiment/stage" for the same reason.
    Enforced by a partial unique index, so two running experiments on one Cell
    are unrepresentable rather than merely refused."""
    cell = _cell(conn)
    _start(conn, cell)
    with pytest.raises(experiments.ExperimentConflictError):
        _start(conn, cell, hypothesis="something else")


def test_the_one_running_rule_is_a_database_constraint_not_only_a_check(conn):
    """The check inside `_start_locked` could be bypassed by a future caller;
    the index cannot. Belt and braces, and the index is the braces."""
    cell = _cell(conn)
    first = _start(conn, cell)
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO experiments (experiment_id, cell_id, hypothesis, "
            "expected_cost_minor_units, ladder_rung, status, created_at_utc) "
            "VALUES ('sneak', ?, 'second', 0, 1, 'running', ?)",
            (cell.cell_id, first.created_at_utc.isoformat()),
        )


def test_a_concluded_experiment_does_not_block_the_next_one(conn):
    cell = _cell(conn)
    first = _start(conn, cell)
    experiments.conclude(
        conn, experiment_id=first.experiment_id, concluded_by="op", note="done"
    )
    assert experiments.current_for(conn, cell.cell_id) is None
    assert _start(conn, cell, hypothesis="next").is_running


# --- §25.1: stage is the Cell's, and there is one ladder ----------------------


def test_stage_reached_reads_both_promotions_and_experiments(conn):
    """§10.5's `stage_reached`. `promotions.rung` records a rung the colony
    *funded* and `experiments.ladder_rung` one the Cell actually *ran at* — a
    Cell that did rung-1 simulator work and was never promoted has still reached
    rung 1, and a figure derived from promotions alone would call that nothing.
    """
    cell = _cell(conn)
    assert experiments.stage_reached(conn, cell.cell_id) is None
    _start(conn, cell, rung=3)
    assert "rung 3" in experiments.stage_reached(conn, cell.cell_id)


def test_a_rung_outside_the_ladder_is_refused(conn):
    """§25.1 has exactly nine rungs. A tenth would be a ladder this kernel does
    not have, and inventing one silently is how a second ladder starts."""
    cell = _cell(conn)
    for bad in (0, 10, -1):
        with pytest.raises(experiments.ExperimentError, match="nine rungs"):
            _start(conn, cell, rung=bad)


# --- §10.5: the coroner seam --------------------------------------------------


def test_a_coroner_report_carries_the_cells_stage_and_experiments(conn):
    """§10.5: "Every death emits a coroner report … stage reached … and links to
    its experiments." Both live above `lifecycle`, so this is the injected seam
    working (`lifecycle.CoronerEnricher`), not an import."""
    cell = _cell(conn)
    experiment = _start(conn, cell, rung=4)
    lifecycle.kill(
        conn, cell.cell_id, cause_of_death="fixture",
        coroner_enricher=experiments.ExperimentCoroner(),
    )
    row = conn.execute(
        "SELECT stage_reached, experiment_ids_json FROM coroner_reports WHERE cell_id = ?",
        (cell.cell_id,),
    ).fetchone()
    assert "rung 4" in row["stage_reached"]
    assert experiment.experiment_id in row["experiment_ids_json"]


def test_a_kill_without_the_seam_still_files_a_report(conn):
    """The seam is optional for the reason `population.Displacer` is: a kernel
    without experiment tracking must still bury its dead. Degrading to a thinner
    report is right; refusing to file one would make an optional feature
    load-bearing for Charter C8."""
    cell = _cell(conn)
    _start(conn, cell)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="fixture")
    row = conn.execute(
        "SELECT stage_reached, experiment_ids_json FROM coroner_reports WHERE cell_id = ?",
        (cell.cell_id,),
    ).fetchone()
    assert row is not None
    assert row["stage_reached"] is None


def test_an_explicit_stage_wins_over_the_seam(conn):
    """A caller that knows better than a general derivation — a replay, a
    migration, a test — must not have its value silently overwritten."""
    cell = _cell(conn)
    _start(conn, cell, rung=2)
    lifecycle.kill(
        conn, cell.cell_id, cause_of_death="fixture",
        stage_reached="rung 9: bounded autonomy",
        coroner_enricher=experiments.ExperimentCoroner(),
    )
    row = conn.execute(
        "SELECT stage_reached FROM coroner_reports WHERE cell_id = ?", (cell.cell_id,)
    ).fetchone()
    assert row["stage_reached"] == "rung 9: bounded autonomy"


def test_an_objective_death_enriches_its_report_without_being_asked(conn):
    """§10.5 says *every* death, so `death.py` supplies the enricher itself
    rather than leaving it to each caller. A kernel that only enriched when
    someone remembered would satisfy the clause by luck."""
    source = pathlib.Path(death.__file__).read_text()
    tree = ast.parse(source)
    enriched = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and any(kw.arg == "coroner_enricher" for kw in node.keywords)
    ]
    kills = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "kill"
    ]
    assert kills, "death.py should still be killing things"
    assert len(enriched) == len(kills)


def test_a_dead_cells_experiment_stops_holding_its_slot(conn):
    """§9.2 caps *simultaneous* experiments colony-wide, and death is routine.

    Without release, a colony that kills Cells faster than it concludes
    experiments ratchets toward its cap and refuses every new experiment with
    nothing explaining why — the same "a claim held before acting is a lock and
    nothing sweeps it" shape ADR-036 logged for channel claims. The estate
    reclamation beside it releases reservations for the same reason.
    """
    doomed = _cell(conn, key="doomed")
    _start(conn, doomed)
    _start(conn, _cell(conn, key="other"))
    blocked = _cell(conn, key="blocked")
    with pytest.raises(experiments.ExperimentCapacityError):
        _start(conn, blocked)

    lifecycle.kill(
        conn, doomed.cell_id, cause_of_death="fixture",
        coroner_enricher=experiments.ExperimentCoroner(),
    )

    assert experiments.running_count(conn) == 1
    assert _start(conn, blocked).is_running


def test_an_experiment_ended_by_death_is_abandoned_not_concluded(conn):
    """It reached no answer. Recording it as concluded would put a finding in
    the record that nobody made — and §10.5 values coroner reports precisely
    because they are honest about what did not finish."""
    cell = _cell(conn)
    experiment = _start(conn, cell)
    lifecycle.kill(
        conn, cell.cell_id, cause_of_death="fixture",
        coroner_enricher=experiments.ExperimentCoroner(),
    )
    ended = experiments.get(conn, experiment.experiment_id)
    assert ended.status == experiments.STATUS_ABANDONED
    assert ended.concluded_by == "kernel"
    assert "died" in ended.conclusion_note


def test_a_coroner_report_never_lists_a_running_experiment(conn):
    """The report is filed after the close-out for a reason: a report saying a
    dead Cell has a running experiment is a false statement, not a thin one."""
    cell = _cell(conn)
    _start(conn, cell)
    lifecycle.kill(
        conn, cell.cell_id, cause_of_death="fixture",
        coroner_enricher=experiments.ExperimentCoroner(),
    )
    still_running = conn.execute(
        "SELECT COUNT(*) AS n FROM experiments e JOIN cells c ON c.cell_id = e.cell_id "
        "WHERE e.status = 'running' AND c.status = 'dead'"
    ).fetchone()["n"]
    assert still_running == 0


# --- §0.3: nothing here is an outcome a Cell wrote -----------------------------


def test_the_experiments_table_has_no_outcome_column(conn):
    """§0.3 — "a Cell may explain a result; it may never define the canonical
    result". `conclusion_note` is prose about *finishing*; the result is
    `report()`, derived from the ledger where no Cell can reach it. A column
    named for success, revenue or a score would be the leak.
    """
    columns = {r[1] for r in conn.execute("PRAGMA table_info(experiments)")}
    for forbidden in ("outcome", "result", "success", "revenue", "profit", "score", "fitness"):
        assert not any(forbidden in c for c in columns), f"{forbidden} in {columns}"


def test_a_cell_may_conclude_its_own_experiment(conn):
    """The other side of the same line, and it must stay open: saying "this is
    finished" is not saying "this worked". A kernel that required an operator to
    close every experiment would stall the loop it exists to run."""
    cell = _cell(conn)
    experiment = _start(conn, cell)
    ended = experiments.conclude(
        conn, experiment_id=experiment.experiment_id,
        concluded_by=cell.cell_id, note="hypothesis did not hold",
    )
    assert ended.status == experiments.STATUS_CONCLUDED


# --- ordinary refusals ---------------------------------------------------------


def test_an_experiment_must_state_a_hypothesis(conn):
    cell = _cell(conn)
    with pytest.raises(experiments.ExperimentError, match="hypothesis"):
        _start(conn, cell, hypothesis="   ")


def test_concluding_must_say_what_was_learned(conn):
    cell = _cell(conn)
    experiment = _start(conn, cell)
    with pytest.raises(experiments.ExperimentError, match="state why"):
        experiments.conclude(
            conn, experiment_id=experiment.experiment_id, concluded_by="op", note=" "
        )


def test_a_dead_cell_cannot_start_an_experiment(conn):
    cell = _cell(conn)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="fixture")
    with pytest.raises(experiments.ExperimentError, match="only a living Cell"):
        _start(conn, lifecycle.get_cell(conn, cell.cell_id))


def test_an_experiment_cannot_be_concluded_twice(conn):
    cell = _cell(conn)
    experiment = _start(conn, cell)
    experiments.conclude(
        conn, experiment_id=experiment.experiment_id, concluded_by="op", note="done"
    )
    with pytest.raises(experiments.ExperimentError, match="already"):
        experiments.conclude(
            conn, experiment_id=experiment.experiment_id, concluded_by="op", note="again"
        )
