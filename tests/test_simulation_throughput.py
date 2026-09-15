"""A simulated colony keeps experimenting for as long as it runs (Slice H;
ADR-095).

The Slice H pilot found every arm of a 40-epoch batch concluding no experiment
at all from epoch 27 on, for three reasons that compose. Each is defended here
by the property it broke rather than by its mechanism:

- a mock Cell proposed on *every* wake, and every approval earns another wake
  (§17.2), so proposals bred proposals;
- the resulting flood tripped §23.4's `queue_flooding` signal, and a flagged
  request never ages out of a simulated run (the queue's clocks are wall time),
  so it counted against its lineage for good;
- and slots went to the oldest grants first, which no simulated grant ever
  outlives, so children waited epochs for a first experiment.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mitosis import approval, db
from mitosis.models import Book
from mitosis.providers import ModelRequest
from mitosis.simulation import batch, runner
from mitosis.simulation.environment import EnvironmentSuite, UtilityMaximizingMarket
from mitosis.simulation.policy import POLICY_MODEL_ID, SimulationPolicyProvider
from mitosis.simulation.selection_policy import SingleLeaderboardSelection

_GENOME = {"market": {"segment": "smb"}, "product": {"name": "p"}}


def _reply_to(wake_reason: str) -> dict:
    prompt = (
        "## Your genome (immutable; this is who you are)\n"
        f"{json.dumps(_GENOME)}\n\n"
        f"## Why you were woken\n{wake_reason}\n\n"
        "## Colony state\nnothing"
    )
    response = SimulationPolicyProvider(master_seed=1).complete(
        ModelRequest(model=POLICY_MODEL_ID, messages=({"role": "user", "content": prompt},), max_tokens=500)
    )
    return json.loads(response.text)


@pytest.mark.parametrize(
    "wake_reason", ["human decision", "approval expired", "grant expired", "capital allocation"],
)
def test_a_mock_cell_abstains_on_every_wake_but_its_research_cycle(wake_reason):
    reply = _reply_to(wake_reason)
    assert reply["kind"] == "abstain"
    assert "risk_tier" not in reply  # ADR-068: the one kind that classifies no action


def test_a_mock_cell_proposes_an_experiment_on_its_research_cycle():
    assert _reply_to("scheduled research cycle")["kind"] == "experiment"


@pytest.fixture(scope="module")
def flooding_run():
    """Four founders, no lineage cap, a policy that always reproduces the top
    earner: one lineage grows past five living Cells, so its research cycle
    alone files more than §23.4's five pending requests in one tick."""
    conn = db.connect_and_migrate()
    manifest = runner.run(
        conn,
        runner.RunConfig(scenario_name="flood", master_seed=7, epochs=12, population=4, lineage_cap=1.0),
        suite=EnvironmentSuite.training_only(UtilityMaximizingMarket()),
        selection=SingleLeaderboardSelection(),
    )
    yield conn, manifest
    conn.close()


def test_a_run_files_no_more_requests_than_its_cells_had_research_cycles(flooding_run):
    """Proposals cannot breed proposals: a Cell is woken for research once per
    epoch, so the requests a run files are bounded by the living Cells at each
    tick. Policy v1 filed 114 in one epoch of a 20-Cell colony."""
    conn, manifest = flooding_run
    living_at_each_tick = [4] + [record.living_cells for record in manifest.epochs[:-1]]
    research_cycles = sum(living_at_each_tick)
    requests = conn.execute("SELECT COUNT(*) FROM approval_requests").fetchone()[0]
    assert requests <= research_cycles


def test_a_lineage_flagged_for_flooding_is_not_barred_for_the_rest_of_the_run(flooding_run):
    """The ratchet: a flagged request left pending counted toward its lineage
    forever, so every later request from it was flagged too. Non-vacuous — the
    fixture does trip the signal — and each flag is resolved by a named, recorded
    simulator decision, never by dropping the signal."""
    conn, manifest = flooding_run
    flagged = conn.execute(
        "SELECT COUNT(*) FROM approval_signals WHERE signal = ?", (approval.SIGNAL_QUEUE_FLOODING,)
    ).fetchone()[0]
    assert flagged > 0
    pending_flood_only = [
        r for r in approval.queue(conn)
        if {s.signal for s in r.signals} == {approval.SIGNAL_QUEUE_FLOODING}
    ]
    assert not pending_flood_only
    reviewed = conn.execute(
        "SELECT decision_reason FROM approval_requests WHERE decided_by = ?", (runner.SIMULATION_DECIDER,)
    ).fetchall()
    assert len(reviewed) == flagged
    assert all("ADR-095" in row["decision_reason"] for row in reviewed)
    assert manifest.epochs[-1].experiments_concluded > 0


def test_the_simulator_reviews_only_synthetic_experiments_flagged_for_nothing_but_flooding(monkeypatch):
    """The review is a stand-in for a person, so it is kept to the one case the
    ratchet needs. A request with any other §23.4 signal, a request that is not
    an experiment, and a request on a real-money book all stay pending for the
    operator."""
    flood = approval.Signal(approval.SIGNAL_QUEUE_FLOODING, "lineage has 5 pending")
    other = approval.Signal(approval.SIGNAL_UNDERSTATED_RISK, "claimed LOW")
    requests = [
        SimpleNamespace(request_id="flood-only", proposal_id="exp", cell_id="sim", signals=(flood,)),
        SimpleNamespace(request_id="two-signals", proposal_id="exp", cell_id="sim", signals=(flood, other)),
        SimpleNamespace(request_id="not-an-experiment", proposal_id="spend", cell_id="sim", signals=(flood,)),
        SimpleNamespace(request_id="real-money", proposal_id="exp", cell_id="real", signals=(flood,)),
        SimpleNamespace(request_id="unflagged", proposal_id="exp", cell_id="sim", signals=()),
    ]
    kinds = {"exp": "experiment", "spend": "spend_request"}
    books = {"sim": Book.USD_SIM, "real": Book.USD_REAL}

    class _Conn:
        def execute(self, sql, params):
            return SimpleNamespace(fetchone=lambda: {"kind": kinds[params[0]]})

    approved: list[str] = []
    monkeypatch.setattr(runner.approval, "queue", lambda conn: requests)
    monkeypatch.setattr(runner.lifecycle, "get_cell", lambda conn, cell_id: SimpleNamespace(book=books[cell_id]))
    monkeypatch.setattr(
        runner.approval, "approve",
        lambda conn, *, request_id, decided_by, reason: approved.append(request_id),
    )
    runner._review_flood_flagged_experiments(_Conn())
    assert approved == ["flood-only"]


def test_no_cell_waits_more_than_an_epoch_for_its_first_experiment():
    """24 Cells, 20 slots (§9.2): a queue served oldest-grant-first let founders'
    backlog hold every slot while children waited. Selection acts on children, so
    a Cell nobody has tested yet goes first."""
    first_alive: dict[str, int] = {}
    first_experiment: dict[str, int] = {}

    def hook(conn, epoch):
        for row in conn.execute("SELECT cell_id FROM cells WHERE status = 'alive'").fetchall():
            first_alive.setdefault(row["cell_id"], epoch)
        for row in conn.execute("SELECT DISTINCT cell_id FROM experiments").fetchall():
            first_experiment.setdefault(row["cell_id"], epoch)

    conn = db.connect_and_migrate()
    try:
        manifest = runner.run(
            conn,
            runner.RunConfig(scenario_name="slots", master_seed=3, epochs=10, population=24),
            suite=EnvironmentSuite.training_only(UtilityMaximizingMarket()),
            selection=batch.build_selection(
                "random_eligible", environment_name=UtilityMaximizingMarket.name, validation_environment=None,
            ),
            epoch_hook=hook,
        )
    finally:
        conn.close()
    assert sum(record.reproductions for record in manifest.epochs) > 0
    last_epoch = manifest.epochs[-1].epoch
    waits = [
        first_experiment.get(cell_id, last_epoch + 1) - born
        for cell_id, born in first_alive.items()
        if born < last_epoch
    ]
    max_wait = max(waits)
    assert max_wait <= 1
