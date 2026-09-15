"""The experiment: what a Cell is testing, and what it cost to find out
(SPEC.md §2.5, §2.6, §9.2, §10.5, §13.1, §15.1, §25.1, §27.2, §31; Charter C3;
ADR-043).

Seven sections reference an experiment and none defines one. What §2.6 *does*
define is the **report**:

    Every experiment report shows synthetic revenue/profit, real cash consumed,
    resource consumption, shadow cost, human labour, and a reality-gap estimate

— six dimensions, not a scalar, which settles §10.2 and §13.2's "do not rely on
a single weighted scalar" from the definition rather than from a preference.

**The decisive clause is the one immediately above it.** §2.5 is "Balances are
derived": authoritative figures come from ledger entries and are never cached
(Charter C3). Read as neighbours, an experiment report is a **derived view, not
a stored row** — and every money line already resolves, because
`reservations.settle` has been propagating `experiment_id` onto ledger entries
all along and `model_calls.experiment_id` has existed since migration 0010. The
plumbing was complete before the object existed.

**So there is no `experiment_results` table, and §31 listing one is not enough
to build it.** §31 offers "suggested entities" and does not mark that one
Phase 1. A stored outcome is where §0.3 would leak back in — a Cell may explain
a result and may never define one — and the surest way to keep that true is to
give it no column to write. `proposal.py` earns its shape the same way.

**Stage is a property of the Cell, not of the experiment, and three clauses
agree.** §10.5's coroner lists `stage_reached` (singular) beside
`experiment_ids` (plural); §27.2's dashboard pairs them as one field, "current
experiment/stage"; and §13.1's `normalised_cost = expected experiment cost /
current stage tranche` would be circular if the stage belonged to the
experiment. So **§25.1's nine rungs are the stage ladder and there is no second
one** — Phase 2's "stage gates" are the gates between those rungs. `promotion.py`
already stamps a rung on every allocation and already calls rung 7 "tiny capped
live experiment", which is what an experiment *is* at that rung.

**§15.1 says "current experiment", singular**, so a Cell has at most one
running at a time. A partial unique index makes that unrepresentable rather than
checked — the move ADR-018, ADR-033 and ADR-035 all make for identity, applied
here to a state.

**An unmeasurable dimension reports as unmeasurable, never as zero.** Sandbox
CPU needs §19's sandbox (Phase 5), so it is `None` with a stated reason. A
report that showed `0` would be making a false claim rather than declining to
make one — the same trap as a crashed tick recording that it spent nothing
(ADR-042).

**A dimension that undercounts is worse than one that abstains, and human
labour was doing that (ADR-044).** This module used to say human labour needed
"a `resource_usage` column that does not exist". It never did:
`resource_usage.reservation_id` is NOT NULL and a reservation has carried
`experiment_id` since migration 0001, so every metered row was always one join
from its experiment. What was missing was the *stamp* — `tools` and
`external_actions` opened their RESOURCE reservations without one, while the
gateway threaded it. So `human_minutes` abstained while `resource_spend_minor_
units`, which reads the same reservations through the ledger, quietly reported a
shadow cost with every tool call and every human minute missing from it. The
abstention was visible; the undercount was not.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import audit, ids, lifecycle, population
from .accounts import SPEND_DESTINATIONS
from .models import Book, CellStatus, ResourceType

STATUS_RUNNING = "running"
STATUS_CONCLUDED = "concluded"
STATUS_ABANDONED = "abandoned"

#: §25.1's ladder, verbatim. The rung an experiment runs at says whether real
#: money can be involved at all: rung 1 is the flight simulator, rung 7 is the
#: "tiny capped live experiment" `promotion.py` already funds.
LADDER: dict[int, str] = {
    1: "flight simulator",
    2: "held-out simulator family",
    3: "historical-data backtest",
    4: "read-only real-world observation",
    5: "shadow prediction with no action",
    6: "human-reviewed prototype",
    7: "tiny capped live experiment",
    8: "expanded pilot",
    9: "bounded autonomy",
}

MAX_HYPOTHESIS_CHARS = 2_000

#: Why a §2.6 dimension is `None`. Stated rather than implied, because "we
#: cannot measure this" and "this measured zero" are different claims.
UNMEASURED_SANDBOX = (
    "sandbox CPU: §19.3's sandbox does not exist (Phase 5), so no CPU is attributable"
)

#: §13.1's denominator is missing. A Cell that has never been promoted has no
#: capital allotted *for a stage* — it runs on whatever it holds, which is a
#: balance, not a tranche. Saying so beats dividing by its balance and calling
#: the result a stage ratio.
UNMEASURED_TRANCHE = (
    "normalised cost: this Cell has never been promoted, so §13.1 has no stage "
    "tranche to divide by (a Cell's own balance is not a stage budget)"
)


class ExperimentError(Exception):
    pass


class ExperimentCapacityError(ExperimentError):
    """§9.2's "maximum simultaneous experiments", and **a third refusal shape**.

    ADR-031 separated `CarryingCapacityError` (durable — the colony has no slot,
    which is why §9.3 lets a birth displace something) from
    `BirthRateExceededError` (temporary — it clears when the epoch turns). This
    is neither. The slot frees when an experiment *concludes*: not on a clock,
    and never by killing anything. Collapsing it into either would invite the
    wrong remedy — displacement for a queue, or waiting for a cap that no clock
    will clear.
    """


class ExperimentConflictError(ExperimentError):
    """§15.1's "current experiment" is singular. The Cell already has one."""


@dataclass(frozen=True)
class Experiment:
    experiment_id: str
    cell_id: str
    proposal_id: str | None
    hypothesis: str
    expected_cost_minor_units: int
    ladder_rung: int
    status: str
    created_at_utc: datetime
    concluded_at_utc: datetime | None
    concluded_by: str | None
    conclusion_note: str | None

    @property
    def is_running(self) -> bool:
        return self.status == STATUS_RUNNING

    @property
    def rung_name(self) -> str:
        return LADDER.get(self.ladder_rung, "unknown rung")


@dataclass(frozen=True)
class ExperimentReport:
    """§2.6's report, derived on every read and stored nowhere (§2.5)."""

    experiment_id: str
    cell_id: str
    hypothesis: str
    status: str
    ladder_rung: int
    rung_name: str
    expected_cost_minor_units: int

    #: Net of refunds and chargebacks: a reversal credits the `revenue` account
    #: with its payment's experiment tag, so reading that account nets it out of
    #: the experiment that made the sale (ADR-097).
    synthetic_revenue_minor_units: int
    synthetic_spend_minor_units: int
    synthetic_net_profit_minor_units: int
    real_spend_minor_units: int
    resource_spend_minor_units: int

    model_calls: int
    input_tokens: int
    output_tokens: int

    #: §2.6's "human labour", and §1.1's split of it. `human_minutes` is what a
    #: person actually gave; `subsidised_human_minutes` is the part of that no
    #: Cell paid for. Reporting only the billed part would make the colony
    #: quietest about its human cost exactly where §1.1 wants it loudest.
    human_minutes: int
    subsidised_human_minutes: int

    #: `None` means not measurable in this kernel. Never zero — see the module
    #: docstring and `unmeasured`.
    sandbox_cpu_seconds: float | None

    reality_gap_mean_brier: float | None
    resolved_predictions: int
    unresolved_predictions: int

    #: §13.1's `normalised_cost = expected experiment cost / current stage
    #: tranche`, and the denominator it used. Both `None` together when the Cell
    #: has no promotion at this rung — never 0.0, which would read as "this
    #: experiment is free" rather than "there is no stage budget to compare it
    #: to". The ratio is dimensionless by construction, which is the whole point
    #: of §13.1: "Never subtract raw dollars from scores in [0,1]."
    stage_tranche_minor_units: int | None
    #: The rung that tranche was allotted for — the Cell's current stage, which
    #: is not necessarily the rung this experiment runs at.
    stage_tranche_rung: int | None
    normalised_cost: float | None

    unmeasured: tuple[str, ...]

    @property
    def spent_real_money(self) -> bool:
        return self.real_spend_minor_units != 0


# --- writing ------------------------------------------------------------------


def start(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    hypothesis: str,
    expected_cost_minor_units: int = 0,
    ladder_rung: int = 1,
    proposal_id: str | None = None,
    now: datetime | None = None,
) -> Experiment:
    """Begin an experiment. **There is no `proposed` state**: the §23 approval
    queue already holds that, and a second copy would give the colony two
    answers to "is this waiting on a person"."""
    now = now or datetime.now(timezone.utc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        experiment = _start_locked(
            conn,
            cell_id=cell_id,
            hypothesis=hypothesis,
            expected_cost_minor_units=expected_cost_minor_units,
            ladder_rung=ladder_rung,
            proposal_id=proposal_id,
            now=now,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return experiment


def _start_locked(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    hypothesis: str,
    expected_cost_minor_units: int = 0,
    ladder_rung: int = 1,
    proposal_id: str | None = None,
    now: datetime,
) -> Experiment:
    """Caller holds the write lock, so a deliberation can fold starting an
    experiment into the transaction that records its proposal.

    **Every check runs inside the lock**, including the §9.2 count: a
    check-then-lock here would let two concurrent starts both read a colony one
    under its cap and both take the last slot.
    """
    hypothesis = (hypothesis or "").strip()
    if not hypothesis:
        raise ExperimentError(
            "an experiment must state a hypothesis — §10.5's coroner asks for "
            "final hypotheses, and one that never had a hypothesis has nothing to file"
        )
    if len(hypothesis) > MAX_HYPOTHESIS_CHARS:
        raise ExperimentError(
            f"hypothesis is {len(hypothesis)} chars, over the {MAX_HYPOTHESIS_CHARS} cap"
        )
    if ladder_rung not in LADDER:
        raise ExperimentError(
            f"ladder_rung must be one of §25.1's nine rungs (1-9), got {ladder_rung}"
        )
    if expected_cost_minor_units < 0:
        raise ExperimentError("expected cost cannot be negative")

    cell = lifecycle.get_cell(conn, cell_id)
    if cell is None:
        raise ExperimentError(f"unknown cell: {cell_id!r}")
    if cell.status != CellStatus.ALIVE:
        raise ExperimentError(
            f"cell {cell_id} is {cell.status.value}; only a living Cell can start an "
            "experiment. Going dormant later does not end one — §17's dormancy is about "
            "when a Cell is woken, not about whether its experiment is still running."
        )

    limits = population.get_limits(conn)
    running = running_count(conn)
    if running >= limits.max_parallel_experiments:
        raise ExperimentCapacityError(
            f"{running} experiments already running, at the §9.2 limit of "
            f"{limits.max_parallel_experiments}. A slot frees when one concludes — "
            "this is not a carrying-capacity shortage and nothing should be killed "
            "for it, and no clock will clear it."
        )

    existing = current_for(conn, cell_id)
    if existing is not None:
        raise ExperimentConflictError(
            f"cell {cell_id} is already running experiment {existing.experiment_id}. "
            "§15.1 assembles context from the Cell's *current* experiment, singular — "
            "conclude that one first."
        )

    experiment_id = ids.new_id()
    conn.execute(
        """
        INSERT INTO experiments (
            experiment_id, cell_id, proposal_id, hypothesis,
            expected_cost_minor_units, ladder_rung, status, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            experiment_id, cell_id, proposal_id, hypothesis,
            expected_cost_minor_units, ladder_rung, STATUS_RUNNING, now.isoformat(),
        ),
    )
    audit.record(
        conn,
        event_type="experiment_started",
        cell_id=cell_id,
        description=f"rung {ladder_rung} ({LADDER[ladder_rung]}): {hypothesis[:120]}",
        metadata={
            "experiment_id": experiment_id,
            "ladder_rung": ladder_rung,
            "expected_cost_minor_units": expected_cost_minor_units,
            "proposal_id": proposal_id,
            "running_after": running + 1,
        },
    )
    return get(conn, experiment_id)


def conclude(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    concluded_by: str,
    note: str,
    abandoned: bool = False,
    now: datetime | None = None,
) -> Experiment:
    """End an experiment, freeing its §9.2 slot.

    **A Cell may conclude its own experiment**, and that is not a §0.3 breach:
    saying "this is finished" is not saying "this worked". Nothing recorded here
    is an outcome — `note` is prose, and the result is `report()`, derived from
    the ledger, `model_calls` and the prediction register, where no Cell can
    reach it.

    `abandoned` distinguishes stopping *without* an answer from reaching one.
    §10.5 treats deaths as the colony's cheapest training data and the same
    applies here: an experiment that ran to a negative finding is evidence, and
    one that was dropped is not, so collapsing them would inflate the record.
    """
    now = now or datetime.now(timezone.utc)
    note = (note or "").strip()
    if not note:
        raise ExperimentError(
            "concluding an experiment must state why — an experiment that ends "
            "without a sentence is one nothing can learn from (§10.5)"
        )
    concluded_by = (concluded_by or "").strip()
    if not concluded_by:
        raise ExperimentError("concluding an experiment must record who ended it")

    conn.execute("BEGIN IMMEDIATE")
    try:
        experiment = get(conn, experiment_id)
        if experiment is None:
            raise ExperimentError(f"no such experiment: {experiment_id}")
        if not experiment.is_running:
            raise ExperimentError(
                f"experiment {experiment_id} is already {experiment.status} "
                f"(at {experiment.concluded_at_utc.isoformat()})"
            )
        status = STATUS_ABANDONED if abandoned else STATUS_CONCLUDED
        conn.execute(
            "UPDATE experiments SET status = ?, concluded_at_utc = ?, "
            "concluded_by = ?, conclusion_note = ? WHERE experiment_id = ?",
            (status, now.isoformat(), concluded_by, note, experiment_id),
        )
        audit.record(
            conn,
            event_type="experiment_concluded",
            cell_id=experiment.cell_id,
            description=f"{status}: {note[:160]}",
            metadata={
                "experiment_id": experiment_id,
                "status": status,
                "concluded_by": concluded_by,
                "ladder_rung": experiment.ladder_rung,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get(conn, experiment_id)


# --- reading ------------------------------------------------------------------


def get(conn: sqlite3.Connection, experiment_id: str) -> Experiment | None:
    row = conn.execute(
        "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
    ).fetchone()
    return _row_to_experiment(row) if row is not None else None


def current_for(conn: sqlite3.Connection, cell_id: str) -> Experiment | None:
    """§15.1's "current experiment", singular by index."""
    row = conn.execute(
        "SELECT * FROM experiments WHERE cell_id = ? AND status = ?",
        (cell_id, STATUS_RUNNING),
    ).fetchone()
    return _row_to_experiment(row) if row is not None else None


def attribution_for(conn: sqlite3.Connection, cell_id: str) -> str | None:
    """Which experiment a metered operation by this Cell belongs to, or `None`.

    **Derived, never supplied.** §15.1 gives a Cell one current experiment, so
    the attribution of work it does right now is already determined and nothing
    needs to be asked for it. A parameter would be a place to put an answer, and
    an answer about which experiment bears a cost is an answer about what an
    experiment cost — §0.3's line, reached from the expense side. A Cell that
    could name the experiment could make its own look cheap by naming another.

    `None` is a real result and not a gap: consumption outside any running
    experiment is unattributed because it *is* unattributed, and forcing it onto
    the nearest experiment would be inventing an attribution rather than
    recording one.

    **Callers must hold the write lock.** The attribution is stamped on a
    reservation, and reading it before the lock is the check-then-lock shape
    this kernel has already fixed once: an experiment concluding between the
    read and the insert would stamp a reservation with an experiment that is no
    longer running.
    """
    experiment = current_for(conn, cell_id)
    return experiment.experiment_id if experiment is not None else None


def list_for(conn: sqlite3.Connection, cell_id: str) -> list[Experiment]:
    return [
        _row_to_experiment(row)
        for row in conn.execute(
            "SELECT * FROM experiments WHERE cell_id = ? ORDER BY rowid", (cell_id,)
        )
    ]


def running_count(conn: sqlite3.Connection) -> int:
    """§9.2's "maximum simultaneous experiments" counts this, colony-wide."""
    return conn.execute(
        "SELECT COUNT(*) AS n FROM experiments WHERE status = ?", (STATUS_RUNNING,)
    ).fetchone()["n"]


def stage_reached(conn: sqlite3.Connection, cell_id: str) -> str | None:
    """§10.5's `stage_reached`: the highest §25.1 rung this Cell ever reached.

    Read from both sources, because they record different halves of the same
    climb: `promotions.rung` is a rung the colony *funded*, and
    `experiments.ladder_rung` is one the Cell actually *ran at*. A Cell that ran
    rung-1 simulator work and was never promoted has still reached rung 1, and a
    figure derived from promotions alone would call that nothing.
    """
    row = conn.execute(
        """
        SELECT MAX(rung) AS rung FROM (
            SELECT rung FROM promotions WHERE cell_id = ?
            UNION ALL
            SELECT ladder_rung AS rung FROM experiments WHERE cell_id = ?
        )
        """,
        (cell_id, cell_id),
    ).fetchone()
    rung = row["rung"] if row else None
    if rung is None:
        return None
    return f"rung {rung}: {LADDER.get(int(rung), 'unknown')}"


def stage_tranche(conn: sqlite3.Connection, cell_id: str) -> tuple[int, int] | None:
    """§13.1's denominator: `(rung, minor_units)` the colony allotted this Cell
    for its **current stage**, or `None` if it has never been promoted.

    **This is the thirteenth socket that turned out to already exist.**
    `normalised_cost = expected experiment cost / current stage tranche` is the
    one line in SPEC.md that uses the word "tranche", and §10.5 names the same
    object from the other side — "stage budget exhausted" is a death criterion.
    Nothing needed inventing: `promotions.allocated_minor_units` has been
    exactly this since ADR-029, and its own column comment already says what
    makes it safe — "the amount the operator approved and **not** a figure
    re-read from the Cell at allocation time". So the denominator is set by a
    human, per Cell, per rung, and §23.5's "a field a Cell can fill is a field
    it will optimise" never applies to it. **This slice ships no migration.**

    Read with a plain `SELECT` rather than through `promotion`, which sits far
    above this module — the same move `stage_reached` and
    `experiment_grants.entitled_rung` already make. A query is not an import.

    **Keyed on the Cell, never on the experiment, and ADR-043 settled why.**
    Stage is a property of the Cell — §10.5's coroner lists `stage_reached`
    (singular) beside `experiment_ids` (plural), §27.2's dashboard pairs them as
    one field — and ADR-043 named §13.1 itself as the third witness: this
    formula "would be circular if the stage belonged to the experiment". Keying
    the denominator on `experiments.ladder_rung` would divide an experiment's
    cost by a budget that experiment's own rung selected. The first draft of
    this function did exactly that, and the golden run caught it by reporting
    `None` for every experiment in a scenario that contains both a rung-7
    promotion and a rung-7 experiment — belonging to different Cells.

    **The latest promotion, not the sum of them.** §13.1 says "*current* stage
    tranche", singular, and a tranche is an instalment rather than a running
    total; `promotion.transfer_degradation` already reads "the Cell's latest
    promotion" the same way.

    **`None` when the Cell has never been promoted**, which today is most of
    them. That is a real answer, not a gap: an unpromoted Cell is spending its
    own balance, and the colony has staked no stage capital on it. Dividing by
    that balance would produce a confident-looking ratio measuring something
    §13.1 never named — the trap ADR-042 and ADR-043 both name, where a figure
    that should abstain reports a number instead.
    """
    row = conn.execute(
        "SELECT rung, allocated_minor_units FROM promotions WHERE cell_id = ? "
        "ORDER BY created_at_utc DESC, rowid DESC LIMIT 1",
        (cell_id,),
    ).fetchone()
    return (int(row["rung"]), int(row["allocated_minor_units"])) if row is not None else None


def report(conn: sqlite3.Connection, experiment_id: str) -> ExperimentReport:
    """§2.6's report. Derived on every read and stored nowhere (§2.5)."""
    experiment = get(conn, experiment_id)
    if experiment is None:
        raise ExperimentError(f"no such experiment: {experiment_id}")

    revenue_sim = -_entry_sum(conn, experiment_id, book=Book.USD_SIM, accounts=("revenue",))
    spend_sim = _entry_sum(
        conn, experiment_id, book=Book.USD_SIM, accounts=tuple(SPEND_DESTINATIONS)
    )
    spend_real = _entry_sum(
        conn, experiment_id, book=Book.USD_REAL, accounts=tuple(SPEND_DESTINATIONS)
    )
    spend_resource = _entry_sum(
        conn, experiment_id, book=Book.RESOURCE, accounts=tuple(SPEND_DESTINATIONS)
    )

    calls = conn.execute(
        """
        SELECT COUNT(*) AS n,
               COALESCE(SUM(input_tokens), 0) AS input_tokens,
               COALESCE(SUM(output_tokens), 0) AS output_tokens
        FROM model_calls WHERE experiment_id = ?
        """,
        (experiment_id,),
    ).fetchone()

    gap = _reality_gap(conn, experiment_id)
    labour = _human_labour(conn, experiment_id)

    # §13.1. The numerator is the Cell's own estimate and the denominator is the
    # operator's allocation, which is the asymmetry that makes the ratio worth
    # reading: a Cell can understate what it expects to spend, and cannot touch
    # what it was given. Both are minor units of the same book — `promotion`
    # allocates in `cells.book` — so the division is within one book and §2.4's
    # ban on an implicit exchange rate is not in play.
    allotted = stage_tranche(conn, experiment.cell_id)
    tranche_rung, tranche = allotted if allotted is not None else (None, None)
    normalised = (
        experiment.expected_cost_minor_units / tranche if tranche is not None else None
    )
    unmeasured = (UNMEASURED_SANDBOX,)
    if tranche is None:
        unmeasured += (UNMEASURED_TRANCHE,)

    return ExperimentReport(
        experiment_id=experiment.experiment_id,
        cell_id=experiment.cell_id,
        hypothesis=experiment.hypothesis,
        status=experiment.status,
        ladder_rung=experiment.ladder_rung,
        rung_name=experiment.rung_name,
        expected_cost_minor_units=experiment.expected_cost_minor_units,
        synthetic_revenue_minor_units=revenue_sim,
        synthetic_spend_minor_units=spend_sim,
        synthetic_net_profit_minor_units=revenue_sim - spend_sim,
        real_spend_minor_units=spend_real,
        resource_spend_minor_units=spend_resource,
        model_calls=calls["n"],
        input_tokens=calls["input_tokens"],
        output_tokens=calls["output_tokens"],
        human_minutes=labour[0],
        subsidised_human_minutes=labour[1],
        sandbox_cpu_seconds=None,
        reality_gap_mean_brier=gap[0],
        resolved_predictions=gap[1],
        unresolved_predictions=gap[2],
        stage_tranche_minor_units=tranche,
        stage_tranche_rung=tranche_rung,
        normalised_cost=normalised,
        unmeasured=unmeasured,
    )


def _entry_sum(
    conn: sqlite3.Connection, experiment_id: str, *, book: Book, accounts: tuple[str, ...]
) -> int:
    """Signed sum of this experiment's entries on the given accounts, in one
    book. Signed and destination-scoped for the reason `ledger.spend_by_book`
    documents: a reconciliation credit must reduce the figure, and a capital
    movement must not inflate it."""
    if not accounts:
        return 0
    placeholders = ", ".join("?" for _ in accounts)
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(e.amount_minor_units), 0) AS total
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.transaction_id = e.transaction_id
        WHERE e.experiment_id = ? AND t.book = ? AND e.account_id IN ({placeholders})
        """,
        (experiment_id, book.value, *accounts),
    ).fetchone()
    return int(row["total"])


def _reality_gap(
    conn: sqlite3.Connection, experiment_id: str
) -> tuple[float | None, int, int]:
    """§2.6's "reality-gap estimate", from §8.5's register.

    The mean Brier score over this experiment's *resolved* forecasts. Unresolved
    ones are counted and excluded — `prediction.py` is blunt that "a mean Brier
    score over three cherry-picked resolutions is worse than useless", so the
    count is reported beside the score rather than folded into it.
    """
    row = conn.execute(
        """
        SELECT AVG(brier_score) AS mean_brier,
               SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS resolved,
               SUM(CASE WHEN outcome IS NULL THEN 1 ELSE 0 END) AS unresolved
        FROM prediction_register WHERE experiment_id = ?
        """,
        (experiment_id,),
    ).fetchone()
    mean = row["mean_brier"]
    return (
        float(mean) if mean is not None else None,
        int(row["resolved"] or 0),
        int(row["unresolved"] or 0),
    )


def _human_labour(conn: sqlite3.Connection, experiment_id: str) -> tuple[int, int]:
    """§2.6's "human labour": (minutes a person gave, of which subsidised).

    **Reached through the reservation, which is why no column was added.**
    `resource_usage.reservation_id` is NOT NULL and a reservation has carried
    `experiment_id` since migration 0001, so every metered row is already one
    join from its experiment. A column here would be a second answer to a
    question the reservation already answers, and two answers that can disagree
    is the cached-derivation trap §2.5 and Charter C3 exist to prevent.

    **The billed minutes are not the labour.** `external_actions` charges a Cell
    up to its channel's ceiling and records the overflow as subsidy, precisely
    because "the minutes were already spent, so refusing to record them does not
    un-spend them". Summing `quantity` alone would therefore report the colony's
    human cost as *smaller* the more of it a person absorbed unpaid — the exact
    figure §1.1 subtracts to "expose hidden founder labour", hidden by the
    report meant to expose it. So the total is billed + subsidised, and the
    subsidy is reported beside it rather than folded away.
    """
    rows = conn.execute(
        """
        SELECT u.quantity AS quantity, u.metadata_json AS metadata_json
        FROM resource_usage u
        JOIN reservations r ON r.reservation_id = u.reservation_id
        WHERE r.experiment_id = ? AND u.resource_type = ?
        """,
        (experiment_id, ResourceType.HUMAN_MINUTES.value),
    ).fetchall()

    billed = 0
    subsidised = 0
    for row in rows:
        billed += int(row["quantity"])
        # A row with no subsidy key contributes nothing, which is a true
        # statement rather than a missing one: nothing was recorded as
        # subsidised. Only `external_actions` writes the key today.
        metadata = json.loads(row["metadata_json"] or "{}")
        recorded = metadata.get("subsidised_human_minutes", 0)
        if isinstance(recorded, int) and not isinstance(recorded, bool) and recorded > 0:
            subsidised += recorded
    return billed + subsidised, subsidised


def _row_to_experiment(row: sqlite3.Row) -> Experiment:
    return Experiment(
        experiment_id=row["experiment_id"],
        cell_id=row["cell_id"],
        proposal_id=row["proposal_id"],
        hypothesis=row["hypothesis"],
        expected_cost_minor_units=row["expected_cost_minor_units"],
        ladder_rung=row["ladder_rung"],
        status=row["status"],
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        concluded_at_utc=(
            datetime.fromisoformat(row["concluded_at_utc"])
            if row["concluded_at_utc"]
            else None
        ),
        concluded_by=row["concluded_by"],
        conclusion_note=row["conclusion_note"],
    )


def _abandon_for_dead_cell_locked(
    conn: sqlite3.Connection, cell_id: str, *, now: datetime | None = None
) -> str | None:
    """Release the §9.2 slot a dying Cell was holding. Caller holds the lock.

    **Abandoned, never concluded.** §10.5 makes deaths the colony's cheapest
    training data precisely because a coroner report is honest about what did
    not finish; an experiment ended by its Cell dying reached no answer, and
    recording it as concluded would put a finding in the record that nobody made.

    Without this the slot leaks. `running_count` is colony-wide and death is
    routine, so a colony that kills Cells faster than it concludes experiments
    would ratchet toward its §9.2 cap and refuse every new experiment — with
    nothing anywhere explaining why.
    """
    experiment = current_for(conn, cell_id)
    if experiment is None:
        return None
    now = now or datetime.now(timezone.utc)
    conn.execute(
        "UPDATE experiments SET status = ?, concluded_at_utc = ?, concluded_by = ?, "
        "conclusion_note = ? WHERE experiment_id = ?",
        (
            STATUS_ABANDONED,
            now.isoformat(),
            "kernel",
            "abandoned: the Cell running it died (§10.5), so the experiment reached no answer",
            experiment.experiment_id,
        ),
    )
    audit.record(
        conn,
        event_type="experiment_abandoned_on_death",
        cell_id=cell_id,
        description=f"released the §9.2 slot held by {experiment.experiment_id}",
        metadata={
            "experiment_id": experiment.experiment_id,
            "ladder_rung": experiment.ladder_rung,
        },
    )
    return experiment.experiment_id


# --- the §10.5 seam -----------------------------------------------------------


class ExperimentCoroner:
    """`lifecycle.CoronerEnricher`, implemented where experiments live.

    §10.5 requires *every* coroner report to carry "stage reached" and "links to
    its experiments", and `lifecycle` sits below this module — so the dependency
    is inverted with an injected seam rather than a back-edge, exactly as
    `population.Displacer` is implemented by `displacement.ObjectiveDisplacer`.
    """

    def close_out(
        self, conn: sqlite3.Connection, cell_id: str
    ) -> tuple[str | None, tuple[str, ...]]:
        """Abandon anything still running, then report. Caller holds the lock."""
        _abandon_for_dead_cell_locked(conn, cell_id)
        return (
            stage_reached(conn, cell_id),
            tuple(e.experiment_id for e in list_for(conn, cell_id)),
        )
