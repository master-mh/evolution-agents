"""A Cell proposes an experiment and an approved grant starts it
(SPEC.md §0.2, §0.3, §9.2, §15.1, §23, §25.1, §25.2; ADR-045).

`ProposalKind.EXPERIMENT` existed from migration 0013 and led nowhere. These
defend the two halves of wiring it: that the *hypothesis* is entirely the Cell's
(§0.2 puts experiments in the mutable column), and that the *rung* is entirely
not (§25.1's ladder is the colony's staged-autonomy mechanism, and §23.5 says a
Cell will optimise against any input it is allowed to supply).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    approval,
    deliberation,
    experiment_grants,
    experiments,
    lifecycle,
    population,
    promotion,
    proposal as proposal_module,
    providers,
)
from mitosis.models import Book, CellType, EntrySpec, PopulationLimits
from mitosis.accounts import cell_cash
from mitosis.ledger import post_transaction

GENOME = {"market": "independent bookshops", "workflow": "probe cheaply"}
HYPOTHESIS = "independent bookshops will pay 4 GBP for a weekly stock digest"


@pytest.fixture
def conn():
    from mitosis import db

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


def _reply(**overrides) -> str:
    payload = {
        "kind": "experiment",
        "summary": "probe the bookshop market for demand",
        "rationale": "no realised record yet; a cheap probe is the fastest way to get one",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 25,
        "predictions": [],
        "experiment": {"hypothesis": HYPOTHESIS},
    }
    payload.update(overrides)
    for kind in ("experiment", "tool_request", "external_action"):
        if payload["kind"] != kind:
            payload.pop(kind, None)
    return json.dumps(payload)


def _fund(conn, cell, amount: int = 50_000) -> None:
    for book, currency in (
        (Book.USD_REAL, "USD"), (Book.RESOURCE, "RESOURCE"), (Book.USD_SIM, "USD"),
    ):
        post_transaction(
            conn, book=book, currency=currency,
            transaction_type="cell_birth_funding",
            idempotency_key=f"fund:{cell.cell_id}:{book.value}", description="fund",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
                EntrySpec(
                    account_id=cell_cash(cell.cell_id), amount_minor_units=amount,
                    cell_id=cell.cell_id,
                ),
            ],
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


def _approved_grant(conn, cell, *, wake_key: str = "w1", **overrides):
    """The real path: deliberate, queue, approve."""
    result = deliberation.deliberate(
        conn, cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=_reply(**overrides)),
        wake_key=wake_key, model="mock-1", proposal_sink=approval.QueueSink(),
    )
    row = conn.execute(
        "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
        (result.proposal_id,),
    ).fetchone()
    return approval.approve(
        conn, request_id=row["request_id"], decided_by="operator", reason="worth a slot"
    )


def _promote_to_rung_7(conn, cell) -> None:
    """The real §25.2 path, because a promotion inserted by hand would let
    `entitled_rung` pass against a table nothing ever writes."""
    for book, amount in ((Book.USD_SIM, 5_000),):
        post_transaction(
            conn, book=book, currency="USD",
            transaction_type="colony_seed_capital",
            idempotency_key=f"seed:{book.value}", description="seed",
            entries=[
                EntrySpec(account_id="external_capital", amount_minor_units=-amount),
                EntrySpec(account_id="colony_treasury", amount_minor_units=amount),
            ],
        )
        promotion.fund_pool(
            conn, book=book, amount_minor_units=amount, idempotency_key=f"pool:{book.value}"
        )
    grant = _approved_grant(
        conn, cell, wake_key="promo", kind="spend_request",
        summary="buy the sample dataset", risk_tier="MEDIUM",
        estimated_cost_minor_units=40,
    )
    promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="earned it"
    )


# --- the socket is wired ------------------------------------------------------


def test_a_proposed_experiment_becomes_a_real_one(conn):
    """The whole point of ADR-045: propose -> §23 review -> approve -> start.

    Before this, every experiment in the colony was one an operator typed out by
    hand, and `experiments.proposal_id` — a foreign key waiting since migration
    0026 — could never be filled by anything.
    """
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    experiment = experiment_grants.start_from_grant(
        conn, grant_id=grant.grant_id, started_by="operator"
    )

    assert experiment.hypothesis == HYPOTHESIS
    assert experiment.proposal_id == grant.proposal_id
    assert experiment.is_running
    assert experiments.current_for(conn, cell.cell_id).experiment_id == experiment.experiment_id


def test_the_hypothesis_comes_from_the_frozen_proposal(conn):
    """§0.3's asymmetry, applied to the payload: what starts is what the
    operator was shown at §23.2, never something re-read from the Cell.

    `tools` and `external_actions` both read their frozen payload for the same
    reason. A Cell that could revise the hypothesis after approval would be
    approving its own experiment through a second door.
    """
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    proposal = conn.execute(
        "SELECT * FROM proposals WHERE proposal_id = ?", (grant.proposal_id,)
    ).fetchone()

    assert experiment_grants.experiment_of(proposal) == HYPOTHESIS


def test_the_expected_cost_carries_across_from_the_proposal(conn):
    """§13.1's expected cost, recorded and deliberately not load-bearing
    (ADR-043). It is the figure the operator saw, so it is the figure stored."""
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    experiment = experiment_grants.start_from_grant(
        conn, grant_id=grant.grant_id, started_by="operator"
    )

    assert experiment.expected_cost_minor_units == 25


# --- §25.1: the rung is derived, never asked for ------------------------------


def test_an_unpromoted_cell_starts_at_the_flight_simulator(conn):
    """§25.1: "no strategy moves directly from synthetic success to autonomous
    commerce". A Cell nobody has promoted gets rung 1, which by the ladder's own
    definition touches nothing outside the colony."""
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    experiment = experiment_grants.start_from_grant(
        conn, grant_id=grant.grant_id, started_by="operator"
    )

    assert experiment.ladder_rung == experiment_grants.FLIGHT_SIMULATOR_RUNG == 1


def test_a_promoted_cell_starts_at_the_rung_it_was_promoted_to(conn):
    """The other half, and the one that proves the derivation reads something.

    A test that only pinned rung 1 would pass against an `entitled_rung` that
    returned the constant 1 — the detector that cannot distinguish the two
    outcomes.
    """
    cell = _make_cell(conn)
    _promote_to_rung_7(conn, cell)
    assert experiment_grants.entitled_rung(conn, cell.cell_id) == 7

    grant = _approved_grant(conn, cell, wake_key="w2")
    experiment = experiment_grants.start_from_grant(
        conn, grant_id=grant.grant_id, started_by="operator"
    )

    assert experiment.ladder_rung == 7


def test_entitlement_ignores_a_rung_the_operator_started_by_hand(conn):
    """**"Reached" and "entitled to" are different questions over the same two
    tables**, and this is the distinction the module exists to hold.

    `experiments.stage_reached` maxes over `promotions` *and*
    `experiments.ladder_rung`, because a Cell that ran rung-1 work has genuinely
    reached rung 1. `entitled_rung` reads `promotions` only. Unioning them would
    turn the operator's recorded-but-unenforced `--rung` escape hatch (ADR-043)
    into a permanent ratchet: one hand-started rung-7 experiment and the Cell
    could ask for rung 7 by itself forever after.
    """
    cell = _make_cell(conn)
    started_by_hand = experiments.start(
        conn, cell_id=cell.cell_id, hypothesis="operator's own probe", ladder_rung=7
    )
    experiments.conclude(
        conn, experiment_id=started_by_hand.experiment_id,
        concluded_by="operator", note="done",
    )

    assert "rung 7" in experiments.stage_reached(conn, cell.cell_id)
    assert experiment_grants.entitled_rung(conn, cell.cell_id) == 1

    grant = _approved_grant(conn, cell)
    experiment = experiment_grants.start_from_grant(
        conn, grant_id=grant.grant_id, started_by="operator"
    )
    assert experiment.ladder_rung == 1


def test_a_cell_cannot_choose_its_own_rung(conn):
    """The schema tripwire (`proposal.FORBIDDEN_RUNG_FIELDS`).

    §23.5: "the approval queue is itself part of the environment and will be
    optimised against by Cells", so no input to this decision may be a value the
    Cell supplies. `extra="forbid"` rejects these today; the dict exists so that
    widening the schema toward a Cell-chosen rung has to be an argued change to
    §25.1 rather than a plausible-looking commit.
    """
    fields = set(proposal_module.ExperimentSpec.model_fields)
    forbidden = fields & set(proposal_module.FORBIDDEN_RUNG_FIELDS)
    assert not forbidden, (
        f"ExperimentSpec grew {sorted(forbidden)} — §25.1's rung is derived from "
        "promotions, never requested. See ADR-045."
    )
    for name in proposal_module.FORBIDDEN_RUNG_FIELDS:
        with pytest.raises(Exception):
            proposal_module.ExperimentSpec(hypothesis=HYPOTHESIS, **{name: 7})


def test_an_experiment_proposal_must_carry_a_hypothesis():
    """The first direction. Without it an `experiment` reaches the queue with
    nothing to start, and the failure surfaces after a human has approved it."""
    with pytest.raises(Exception, match="must carry an experiment"):
        proposal_module.parse(_reply(experiment=None))


def test_only_an_experiment_proposal_may_carry_a_hypothesis():
    """The second direction, and the one that matters more here.

    `experiment` is the *permissive* kind — the one a reviewer reads as "yes, go
    think about that" — so unlike `tool_request` the risk runs outward: a
    hypothesis riding on an approved `external_action` would let a Cell take a
    §9.2 slot on the back of an approval that was read as being about an email.
    """
    payload = json.loads(_reply())
    payload["kind"] = "strategy"
    payload["experiment"] = {"hypothesis": HYPOTHESIS}
    with pytest.raises(Exception, match="only an experiment proposal"):
        proposal_module.parse(json.dumps(payload))


def test_the_schema_cap_matches_what_the_kernel_enforces():
    """Two limits on one string, in two modules that cannot import each other.

    If the proposal's cap were the looser of the two, a Cell could write a
    hypothesis that parses, reaches the queue, is approved by a person — and
    then fails at the one moment the approval has already been spent.
    """
    assert proposal_module.MAX_HYPOTHESIS_CHARS == experiments.MAX_HYPOTHESIS_CHARS


# --- what an approval of another kind does not buy -----------------------------


def test_a_grant_for_another_kind_cannot_start_an_experiment(conn):
    """A §9.2 slot is a scarce colony resource, and approving a fetch is not
    approving that a Cell take one. The mirror of the refusals `tools` and
    `external_actions` make about each other."""
    cell = _make_cell(conn)
    grant = _approved_grant(
        conn, cell, kind="strategy", summary="a note on pricing",
    )

    with pytest.raises(experiment_grants.ExperimentGrantError, match="only an experiment"):
        experiment_grants.start_from_grant(
            conn, grant_id=grant.grant_id, started_by="operator"
        )


def test_a_grant_starts_one_experiment_and_not_two(conn):
    """A grant authorises one thing. Without this, one approval could take every
    §9.2 slot in the colony."""
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    experiment = experiment_grants.start_from_grant(
        conn, grant_id=grant.grant_id, started_by="operator"
    )
    experiments.conclude(
        conn, experiment_id=experiment.experiment_id, concluded_by="operator", note="done"
    )

    with pytest.raises(experiment_grants.ExperimentGrantError, match="already consumed"):
        experiment_grants.start_from_grant(
            conn, grant_id=grant.grant_id, started_by="operator"
        )


def test_an_expired_grant_is_refused(conn):
    """§23.3 forbids acting on stale terms: an experiment approved against last
    month's evidence is a different experiment."""
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)

    with pytest.raises(experiment_grants.ExperimentGrantError, match="expired"):
        experiment_grants.start_from_grant(
            conn, grant_id=grant.grant_id, started_by="operator",
            now=grant.expires_at_utc + timedelta(seconds=1),
        )


def test_a_dead_cell_does_not_start_a_proposed_experiment(conn):
    """Charter C8. A Cell approved and then killed does not act on the approval.

    The refusal comes from `experiments._start_locked`, not from this module —
    deliberately, since a copy here would refuse a beat earlier and change
    nothing. What this pins is the part that *is* ADR-045's: the grant is not
    spent on the refusal, because the consumption and the start share one
    transaction.
    """
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="fixture: died after approval")

    with pytest.raises(experiments.ExperimentError):
        experiment_grants.start_from_grant(
            conn, grant_id=grant.grant_id, started_by="operator"
        )
    assert approval.get_grant(conn, grant.grant_id).consumed_at_utc is None


# --- a refusal must not spend the approval ------------------------------------


def test_the_ninety_two_cap_refuses_without_spending_the_grant(conn):
    """§9.2's cap is a capacity shortage, not a verdict on the request.

    If the grant were consumed by the refusal, a colony that was briefly full
    would silently destroy approvals a person had already given — and the Cell
    would have to be woken, propose again, and be approved again, for no reason
    other than timing.
    """
    limits = population.get_limits(conn)
    others = [_make_cell(conn, key=f"filler-{i}") for i in range(limits.max_parallel_experiments)]
    for index, other in enumerate(others):
        experiments.start(conn, cell_id=other.cell_id, hypothesis=f"filler {index}")

    cell = _make_cell(conn, key="proposer")
    grant = _approved_grant(conn, cell)

    with pytest.raises(experiments.ExperimentCapacityError):
        experiment_grants.start_from_grant(
            conn, grant_id=grant.grant_id, started_by="operator"
        )

    assert approval.get_grant(conn, grant.grant_id).consumed_at_utc is None
    # And it works once a slot frees, which is what makes the refusal temporary
    # rather than a loss.
    experiments.conclude(
        conn,
        experiment_id=experiments.current_for(conn, others[0].cell_id).experiment_id,
        concluded_by="operator", note="done",
    )
    assert experiment_grants.start_from_grant(
        conn, grant_id=grant.grant_id, started_by="operator"
    ).is_running


def test_the_one_running_rule_refuses_without_spending_the_grant(conn):
    """§15.1's singular "current experiment", same reasoning as the cap above:
    the Cell has to conclude the one it is running, not lose the approval."""
    cell = _make_cell(conn)
    experiments.start(conn, cell_id=cell.cell_id, hypothesis="already going")
    grant = _approved_grant(conn, cell)

    with pytest.raises(experiments.ExperimentConflictError):
        experiment_grants.start_from_grant(
            conn, grant_id=grant.grant_id, started_by="operator"
        )
    assert approval.get_grant(conn, grant.grant_id).consumed_at_utc is None


# --- what the operator can see before acting ----------------------------------


def test_startable_grants_shows_the_rung_before_anything_starts(conn):
    """The rung is the one thing about the experiment that is *not* in the
    proposal a person reviewed, so it has to be visible before they act — the
    same reason `channel_registry.check_action` exists."""
    cell = _make_cell(conn)
    _promote_to_rung_7(conn, cell)
    grant = _approved_grant(conn, cell, wake_key="w2")

    startable = experiment_grants.startable_grants(conn)

    assert [item["grant_id"] for item in startable] == [grant.grant_id]
    assert startable[0]["ladder_rung"] == 7
    assert "live experiment" in startable[0]["rung_name"]


def test_startable_grants_hides_what_would_refuse(conn):
    """A listing that showed grants `start_from_grant` would reject would send
    an operator to a guaranteed error — the shape ADR-029's
    `allocatable_grants` already had to get right."""
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    experiments.start(conn, cell_id=cell.cell_id, hypothesis="already going")

    assert experiment_grants.startable_grants(conn) == []

    experiments.conclude(
        conn,
        experiment_id=experiments.current_for(conn, cell.cell_id).experiment_id,
        concluded_by="operator", note="done",
    )
    assert [item["grant_id"] for item in experiment_grants.startable_grants(conn)] == [
        grant.grant_id
    ]
