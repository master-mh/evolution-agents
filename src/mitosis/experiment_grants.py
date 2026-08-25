"""Turning an approved experiment proposal into a running experiment
(SPEC.md §0.2, §0.3, §9.2, §15.1, §23, §25.1, §25.2; ADR-045).

`ProposalKind.EXPERIMENT` has existed since migration 0013 and led nowhere. A
Cell could propose an experiment, the proposal reached §23's queue, an operator
could approve it, and the grant sat there — `experiments.start` was reachable
only from the operator's own CLI verb, so every experiment in the colony was one
a person typed out by hand. `experiments.proposal_id` has had a foreign key
waiting for this since migration 0026, and nothing could ever fill it.

**§0.2 decides what this module may and may not judge.** Its two-column table
puts "experiments" in the **mutable Cell** column, beside prompts, strategy and
market hypothesis — and puts "capital + population allocator" and "permissions +
approvals" in the immutable kernel. So *what is tested* is entirely the Cell's:
nothing here reads the hypothesis, validates it, scores it, or rewrites it. What
the kernel gates is the **slot** (§9.2 caps simultaneous experiments
colony-wide) and the **rung** (§25.1's staged-autonomy ladder), because those
are colony resources rather than the Cell's. An operator approving one of these
is approving a cost and a stage, never a scientific opinion.

**The rung is derived, and that is the whole safety story.** §25.1 opens with
"no strategy moves directly from synthetic success to autonomous commerce", and
its ladder runs from a flight simulator to bounded autonomy over real money. A
Cell that could name its own rung could ask for rung 7 on its first wake and
need only one distracted operator to get it. §23.5 already generalised the
problem — "the approval queue is itself part of the environment and will be
optimised against by Cells" — so `ExperimentSpec` has no rung field at all
(`proposal.FORBIDDEN_RUNG_FIELDS` makes adding one trip an alarm) and
`entitled_rung` reads the answer out of `promotions`.

**"Reached" and "entitled to" are different questions over the same two
tables.** `experiments.stage_reached` takes the maximum over `promotions.rung`
*and* `experiments.ladder_rung`, because a Cell that ran rung-1 simulator work
has genuinely reached rung 1. This module deliberately does **not**: it reads
`promotions` only. Running at a rung is something that happened; being promoted
to one is a decision a person made against §25.2 evidence. Unioning them here
would make the operator's escape hatch (`mitosis start-experiment --rung 7`,
recorded-but-unenforced by ADR-043) into a permanent ratchet on what the Cell
may then ask for by itself.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import approval, audit, experiments, lifecycle
from .models import CellStatus
from .proposal import ProposalKind

#: §25.1 rung 1, "flight simulator". The floor every living Cell has without
#: being promoted to anything: it is where the ladder starts, and by its own
#: definition it touches nothing outside the colony.
FLIGHT_SIMULATOR_RUNG = 1


class ExperimentGrantError(Exception):
    pass


def entitled_rung(conn: sqlite3.Connection, cell_id: str) -> int:
    """The highest §25.1 rung this Cell may run an experiment at by itself.

    `promotions.rung` only — see the module docstring on why this is narrower
    than `experiments.stage_reached`. Floor is rung 1, so a Cell that has never
    been promoted can still run flight-simulator work, which is exactly what
    §25.1's ladder wants it doing first.
    """
    row = conn.execute(
        "SELECT MAX(rung) AS rung FROM promotions WHERE cell_id = ?", (cell_id,)
    ).fetchone()
    rung = row["rung"] if row else None
    return max(FLIGHT_SIMULATOR_RUNG, int(rung)) if rung is not None else FLIGHT_SIMULATOR_RUNG


def experiment_of(proposal_row: sqlite3.Row) -> str:
    """The hypothesis an approved proposal asked to test.

    Read from `payload_json` — the proposal exactly as parsed and recorded —
    never from anything the Cell can touch afterwards. Same asymmetry
    `tools.tool_request_of` and `external_actions.external_action_of` apply:
    what starts is what the operator was shown at §23.2.
    """
    payload = json.loads(proposal_row["payload_json"])
    block = payload.get("experiment")
    if not isinstance(block, dict):
        raise ExperimentGrantError(
            f"proposal {proposal_row['proposal_id']} is an experiment but carries "
            "no experiment payload"
        )
    hypothesis = block.get("hypothesis")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ExperimentGrantError(
            f"proposal {proposal_row['proposal_id']} has a malformed experiment"
        )
    return hypothesis.strip()


def start_from_grant(
    conn: sqlite3.Connection,
    *,
    grant_id: str,
    started_by: str,
    now: datetime | None = None,
) -> experiments.Experiment:
    """Consume an approved grant by starting the experiment it authorised.

    **One transaction.** A consumed grant with no experiment behind it would be
    an approval a person can never use again and nothing to show for it; an
    experiment holding a §9.2 slot with its grant still open would let the same
    approval be spent twice. The §9.2 and §15.1 refusals therefore roll the
    consumption back — the grant stays available, which is right, because
    neither refusal is about the request being wrong.
    """
    now = now or datetime.now(timezone.utc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        experiment = _start_from_grant_locked(
            conn, grant_id=grant_id, started_by=started_by, now=now
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return experiment


def _start_from_grant_locked(
    conn: sqlite3.Connection,
    *,
    grant_id: str,
    started_by: str,
    now: datetime,
) -> experiments.Experiment:
    """Caller holds the write lock. Every check runs inside it — including the
    §9.2 count `experiments._start_locked` makes, which is why the slot cannot
    be taken between the check and the insert."""
    grant = approval.get_grant(conn, grant_id)
    if grant is None:
        raise ExperimentGrantError(f"no such grant: {grant_id}")
    if grant.consumed_at_utc is not None:
        raise ExperimentGrantError(
            f"grant {grant_id} was already consumed at "
            f"{grant.consumed_at_utc.isoformat()} — a grant authorises one experiment"
        )
    if now >= grant.expires_at_utc:
        # §23.3: an experiment approved against last month's evidence is a
        # different experiment. `approval.expire_grants_due` regenerates it as a
        # wake, so the Cell proposes again against a world that has moved on.
        raise ExperimentGrantError(
            f"grant {grant_id} expired at {grant.expires_at_utc.isoformat()} — §23.3 "
            "forbids acting on stale terms. Run `mitosis expire-approvals` to "
            "regenerate it: the Cell proposes again and is approved afresh."
        )

    request = approval.get_request(conn, grant.request_id)
    if request is None or request.status != approval.RequestStatus.APPROVED:
        raise ExperimentGrantError(
            f"grant {grant_id} does not correspond to an approved request"
        )

    proposal = conn.execute(
        "SELECT * FROM proposals WHERE proposal_id = ?", (grant.proposal_id,)
    ).fetchone()
    if proposal is None:
        raise ExperimentGrantError(f"grant {grant_id} names a missing proposal")

    kind = ProposalKind(proposal["kind"])
    if kind is not ProposalKind.EXPERIMENT:
        # The mirror of the refusals in `tools` and `external_actions`, and it
        # matters in the same way: a §9.2 slot is a scarce colony resource, and
        # approving a fetch is not approving that the Cell take one.
        raise ExperimentGrantError(
            f"grant {grant_id} is for a {kind.value} proposal; only an experiment "
            "proposal starts an experiment"
        )

    cell = lifecycle.get_cell(conn, grant.cell_id)
    if cell is None:
        raise ExperimentGrantError(f"grant {grant_id} names an unknown cell")
    # **There is deliberately no status check here.** Charter C8's "a dead Cell
    # does not act" is enforced by `experiments._start_locked`, inside the same
    # transaction, with a message that also explains why dormancy is different.
    # A copy here would refuse a beat earlier and change nothing — the rollback
    # already leaves the grant unconsumed — while shadowing the better error.
    # ADR-039's "second, weaker copy" applies to guards as well as to gates.

    rung = entitled_rung(conn, cell.cell_id)

    conn.execute(
        "UPDATE approval_grants SET consumed_at_utc = ? WHERE grant_id = ?",
        (now.isoformat(), grant_id),
    )

    experiment = experiments._start_locked(
        conn,
        cell_id=cell.cell_id,
        hypothesis=experiment_of(proposal),
        # §13.1's "expected experiment cost", carried across from the figure the
        # operator was shown. Recorded and not load-bearing, exactly as ADR-043
        # left it: the 2026-08-06 live run found every model priced its own work
        # at 0, so a cap resting on this would be a cap the Cell sets itself.
        expected_cost_minor_units=proposal["estimated_cost_minor_units"],
        ladder_rung=rung,
        proposal_id=grant.proposal_id,
        now=now,
    )

    audit.record(
        conn,
        event_type="experiment_started_from_grant",
        cell_id=cell.cell_id,
        description=(
            f"grant {grant_id} started {experiment.experiment_id} at "
            f"rung {rung} ({experiment.rung_name})"
        ),
        metadata={
            "grant_id": grant_id,
            "proposal_id": grant.proposal_id,
            "experiment_id": experiment.experiment_id,
            "ladder_rung": rung,
            "started_by": started_by,
        },
    )
    return experiment


def startable_grants(conn: sqlite3.Connection, *, now: datetime | None = None) -> list[dict]:
    """Approved experiment grants that `start_from_grant` would accept, with the
    rung each would run at.

    Read-only, and offered for the same reason `channel_registry.check_action`
    is: an operator should be able to see what would happen before doing it —
    including the rung, which is the one thing about the experiment that is not
    in the proposal they read.
    """
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        """
        SELECT g.grant_id, g.cell_id, g.proposal_id, g.expires_at_utc, p.summary
        FROM approval_grants g
        JOIN proposals p ON p.proposal_id = g.proposal_id
        WHERE g.consumed_at_utc IS NULL AND p.kind = ?
        ORDER BY g.granted_at_utc
        """,
        (ProposalKind.EXPERIMENT.value,),
    ).fetchall()

    startable = []
    for row in rows:
        if datetime.fromisoformat(row["expires_at_utc"]) <= now:
            continue
        cell = lifecycle.get_cell(conn, row["cell_id"])
        if cell is None or cell.status != CellStatus.ALIVE:
            continue
        if experiments.current_for(conn, row["cell_id"]) is not None:
            continue
        rung = entitled_rung(conn, row["cell_id"])
        startable.append(
            {
                "grant_id": row["grant_id"],
                "cell_id": row["cell_id"],
                "summary": row["summary"],
                "ladder_rung": rung,
                "rung_name": experiments.LADDER.get(rung, "unknown rung"),
                "expires_at_utc": row["expires_at_utc"],
            }
        )
    return startable
