"""§13.2's selector: hard gates, then a Pareto frontier — never a scalar
(SPEC.md §13.2, §13.1, §13.3, §13.4, §10.2, §10.3, §11.2, §23.4, §23.5, §25.2;
ADR-048, ADR-056, ADR-058).

    Reject candidates below minimum thresholds on evidence quality,
    reproducibility, policy compliance, and software-native advantage; then
    select from a Pareto frontier over structural novelty, information gain,
    economic potential, experiment cost, and transfer robustness. **Do not rely
    on a single weighted scalar.**

Four gates, five frontier dimensions, and the two halves are not interchangeable:
a gate *removes* a candidate, a frontier dimension only ever loses to something
better on every dimension at once. `DIMENSION_SENSE` transcribes all nine names
verbatim and forces each into exactly one half, the way `accounts.py` forces
every account into consumption or capital — `unclassified_dimensions()` and its
test fail if a tenth name appears with no decision attached.

**What the candidates are.** Approved grants that have not been consumed and
have not expired, for the two kinds that ask the colony to spend something on
finding something out — an experiment or a spend request. `mitosis allocations`
already listed the spend-request half, ordered `granted_at_utc`: first come,
first funded, which is the absence of selection wearing an ordering's clothes.
`CANDIDATE_KINDS` and `NON_CANDIDATE_SENSE` force every other kind to carry a
reason it is excluded rather than falling out of a filter nobody revisits.

## Two of the nine dimensions cannot be measured, and say so

A dimension with no data reports `None` **with a reason**, never `0.0`. A zero
is a claim ("this idea is not novel"); an abstention is the truth ("nothing here
can tell you"). §2.6's report and ADR-042/043 both settled this shape already.

(**`structural_novelty` was here until ADR-060.** It needed a prior to be novel
*against*; the genome archive is that prior, and §12.1's adjacent/moderate/
radical is now a live ordinal axis. It measures distance, not merit — see
`_structural_novelty`.)
- **`economic_potential`** is the dangerous one. A Cell would happily supply it,
  and §0.3 is the standing answer: "a Cell may *explain* a result; it may never
  *define* the canonical result". `proposal.FORBIDDEN_FIELD_SENSE` already
  refuses `score` and `fitness` for this reason. There is no proper scoring rule
  over a Cell's own estimate of its upside, so there is nothing here to select
  on and this module declines rather than inventing one.
- **`reproducibility`** needs §11.2's independent-adoption record — another Cell
  using the finding and passing verification. §10.5's `EVIDENCE_NOT_REPRODUCIBLE`
  is declared in `death.py` and unimplemented for the same reason.

(**`software_native_advantage` was here too, until this slice.** It is still a
judgment about an idea's content, still admissible only from a human (§23) or an
independent Auditor (§10.4), and the kernel still never makes the judgment
itself — `content_audit.py` is what changed, giving `software_native_advantage`
a live Auditor judge the way ADR-060 gave `structural_novelty` a live prior.
This gate only ever *reads* a judgment someone else already made and the
register already scored; see `_software_native_advantage`.)

## Why a self-reported probability is safe to select on and a self-reported
## upside is not

`information_gain` is computed from the forecasts the Cell registered in the
deliberation that produced the proposal, and those are the Cell's own numbers.
The difference is §8.5: Brier and log score are **proper** scoring rules, so
stating 0.5 when you believe 0.9 loses points in expectation, and the register is
hash-chained before the outcome is knowable. A Cell that games this dimension
pays for it on the evidence-quality gate. That is the whole reason §13.2 asks for
a frontier rather than a weighted sum — the dimensions are supposed to hold each
other honest, and they cannot do that once they have been added together.

**One dimension has no such protection and it is named here rather than hidden:**
`experiment_cost`'s numerator is the Cell's own `estimated_cost_minor_units`, so
a Cell that understates a cost looks cheaper on the frontier. §13.1's denominator
is safe (a human set the tranche), and the ledger records what the experiment
actually consumed — but nothing yet compares the two. See FUTURE_BUILD_HOOKS.

## Nothing acts on a frontier

Same posture as `outcome.assess`: this returns a sentence for a human to read.
Being on the frontier is not an approval, and being off it is not a death —
§10.5 forbids "estimated negative EV alone" killing a Cell without an independent
Auditor concurring, and a Pareto rank is exactly such an estimate.
`test_no_kernel_path_acts_on_a_frontier` costs an explicit edit to whoever
changes that. Derived on every read; there is no `selection` table (§2.5).
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from . import approval, content_audit, experiments, novelty, prediction, promotion
from .models import CellStatus
from .proposal import ProposalKind

#: The proposal kinds §13 evaluates: a request to spend the colony's resources
#: on **finding something out**. §13.1's own formula names the object —
#: "expected experiment cost / current stage tranche" — so an approved,
#: unconsumed experiment grant is as much a candidate as a spend request, and
#: excluding it would leave the clause's cost dimension with nothing to measure.
CANDIDATE_KINDS = frozenset({ProposalKind.EXPERIMENT, ProposalKind.SPEND_REQUEST})

#: Why each remaining kind is not a candidate. Kept as reasons rather than as a
#: silent complement so a seventh kind cannot join by default —
#: `unclassified_kinds()` fails until someone decides.
NON_CANDIDATE_SENSE: dict[ProposalKind, str] = {
    ProposalKind.STRATEGY: (
        "names nothing to do — approving one *is* the act (ADR-046), so there is "
        "no scarce resource for it to compete for"
    ),
    ProposalKind.TOOL_REQUEST: (
        "asks for a capability, not for an experiment. §0.4 grants autonomy tool "
        "by tool and that is a permission question, not a novelty one"
    ),
    ProposalKind.EXTERNAL_ACTION: (
        "asks to *act* on what is already believed. §13 evaluates ideas before "
        "they are tested, and this is the other end of that"
    ),
    ProposalKind.DELIVERABLE: (
        "hands over finished work and asks for nothing — like a strategy, approving "
        "it is the act (ADR-107), so there is no scarce resource for it to compete for"
    ),
    ProposalKind.ABSTAIN: "declines to act, so there is nothing to select",
}


def unclassified_kinds() -> set[ProposalKind]:
    """Proposal kinds nobody has decided are candidates or not."""
    return set(ProposalKind) - CANDIDATE_KINDS - set(NON_CANDIDATE_SENSE)


#: §13.2's four hard gates, transcribed verbatim. A gate removes a candidate.
GATE_DIMENSIONS: dict[str, str] = {
    "evidence_quality": (
        "the proposer's realised calibration (§8.5). Rejects a Cell that has "
        "resolved enough forecasts to be judged and scores worse than a coin "
        "flip; never rejects one that simply has no record yet"
    ),
    "reproducibility": (
        "§11.2's independent-adoption record. No data: nothing yet records one "
        "Cell's finding being reused and verified by another"
    ),
    "policy_compliance": (
        "quarantine (§18) and §23.4's escalating anti-gaming signals, both "
        "realised facts the kernel detected rather than judgments about an idea"
    ),
    "software_native_advantage": (
        "§13.3's list. A judgment about an idea's content, admissible only from "
        "a human or an independent Auditor — never the Cell (§0.3), never the "
        "kernel (§23.5)"
    ),
}

#: §13.2's five frontier dimensions, transcribed verbatim. These never remove a
#: candidate on their own; they only lose to something better everywhere.
FRONTIER_DIMENSIONS: dict[str, str] = {
    "structural_novelty": (
        "§12.1's novelty distance, ordinal: adjacent < moderate < radical. "
        "Structural, from the genome archive — no model and no judgment"
    ),
    "information_gain": (
        "mean normalised entropy of the forecasts registered with this proposal "
        "(§8.5). Safe to select on because Brier is a proper scoring rule"
    ),
    "economic_potential": (
        "a Cell's estimate of its own upside, with no proper scoring rule over "
        "it. §0.3: a Cell may explain a result, never define one"
    ),
    "experiment_cost": (
        "§13.1's normalised_cost = expected experiment cost / current stage "
        "tranche. Dimensionless by construction, which is what §13.1 is for"
    ),
    "transfer_robustness": (
        "§25.2's transfer degradation: how much worse this Cell did at its last "
        "rung than it predicted. None until it has been promoted before"
    ),
}

#: Direction of preference, for every frontier dimension that can be measured.
#: Explicit because a sign error in a domination test does not crash — it
#: silently selects the opposite population, and every test still passes.
HIGHER_IS_BETTER: dict[str, bool] = {
    "structural_novelty": True,
    "information_gain": True,
    "experiment_cost": False,      # a smaller share of the stage tranche
    "transfer_robustness": False,  # a Brier delta: positive means it got worse
}


#: How many resolved forecasts before the evidence-quality gate will reject.
#:
#: **Deliberately this module's own number, not `outcome.MIN_RESOLVED_FOR_A_VERDICT`,
#: even though both are 3.** They answer different questions: that one asks how
#: much evidence is needed to declare a *funded* promotion a success or a
#: failure; this one asks how much is needed before a screening gate may refuse
#: to consider a candidate at all. A colony could reasonably want those to
#: differ, and one constant answering two questions is how a threshold quietly
#: acquires a second meaning. Importing `outcome` would also mean importing a
#: §25.2 verdict into a selector, which `test_no_kernel_path_acts_on_an_assessment`
#: exists to prevent — the guard caught this and was right to.
MIN_RESOLVED_FOR_A_GATE = 3


def unclassified_dimensions() -> set[str]:
    """§13.2's nine names that no dict above has claimed.

    Forces a decision the way `accounts.unclassified_accounts()` does: a
    dimension that is neither a gate nor a frontier axis is one nobody has
    decided the meaning of, and it must not be able to sit in this module
    unnoticed.
    """
    spec_named = {
        "evidence_quality", "reproducibility", "policy_compliance",
        "software_native_advantage", "structural_novelty", "information_gain",
        "economic_potential", "experiment_cost", "transfer_robustness",
    }
    return spec_named - set(GATE_DIMENSIONS) - set(FRONTIER_DIMENSIONS)


class GateOutcome(StrEnum):
    """Four outcomes, and the last two are not the same thing.

    `UNEVALUABLE` means this candidate has no record yet — a new Cell, not a bad
    one. `UNMEASURABLE` means no candidate in this kernel could be measured on
    this dimension, because the data does not exist anywhere. Collapsing them
    into one "unknown" would hide which of the two a build could fix.
    """

    PASSED = "passed"
    REJECTED = "rejected"
    UNEVALUABLE = "unevaluable"
    UNMEASURABLE = "unmeasurable"


@dataclass(frozen=True)
class Gate:
    dimension: str
    outcome: GateOutcome
    reason: str


@dataclass(frozen=True)
class Axis:
    """One frontier dimension for one candidate.

    `value is None` is never "zero on this axis" — `reason` says which of the
    two absences it is, and a `None` axis is skipped by domination entirely.
    """

    dimension: str
    value: float | None
    reason: str

    @property
    def measured(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class Candidate:
    """One allocatable grant, gated and placed.

    Deliberately carries **no score, rank or weight** — §13.2 and §10.2 both
    forbid the scalar, and the surest way to keep a scalar out of a selector is
    to give it nowhere to live. `proposal.py` earns its shape the same way.
    """

    grant_id: str
    proposal_id: str
    cell_id: str
    estimated_cost_minor_units: int
    gates: tuple[Gate, ...]
    axes: tuple[Axis, ...]

    @property
    def rejected_by(self) -> tuple[str, ...]:
        return tuple(g.dimension for g in self.gates if g.outcome is GateOutcome.REJECTED)

    @property
    def passes_gates(self) -> bool:
        return not self.rejected_by

    def axis(self, dimension: str) -> Axis | None:
        return next((a for a in self.axes if a.dimension == dimension), None)


@dataclass(frozen=True)
class Frontier:
    """What §13.2 produces: a set, not an order.

    `frontier` is unordered on purpose. Any order over it would be the weighted
    scalar the clause forbids, arrived at by presentation instead of by
    arithmetic.
    """

    assessed_at_utc: datetime
    candidates: tuple[Candidate, ...]
    frontier_grant_ids: frozenset[str]
    rejected_grant_ids: frozenset[str]
    measured_dimensions: tuple[str, ...]
    unmeasured_dimensions: tuple[str, ...]

    @property
    def on_frontier(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.grant_id in self.frontier_grant_ids)


# --- gates --------------------------------------------------------------------


def _evidence_quality(conn: sqlite3.Connection, cell_id: str) -> Gate:
    """§8.5's register, read as a minimum threshold.

    **The threshold is "worse than saying nothing", not "worse than average".**
    `prediction.UNINFORMATIVE_BRIER` is the score of a flat 0.5 guess; a Cell below
    it is being actively misleading rather than merely uncertain, which is the
    only reading of "below a minimum threshold" that does not quietly select for
    Cells that never forecast.

    **A Cell with no resolved forecasts is `UNEVALUABLE`, never rejected.**
    `death._has_realised_record` names the trap: an unmeasured Cell is not
    inferior, it is unmeasured — and a gate that rejected the unmeasured would
    reject every Cell the colony has just born, which is §9.4's founder problem
    manufactured by the selector.

    **Overdue-but-unresolved forecasts are not this gate's business.**
    `outcome.py` is explicit that resolution is the operator's job, so a
    withheld outcome is "a defect in the evidence, not a finding against the
    Cell". The Cell-attributable version of it already exists as §23.4's
    `selective_evidence` signal — offering *new* forecasts while its own sit
    open — and that is checked under policy compliance, where it belongs.
    """
    scores = prediction.scores(conn, cell_id)
    resolved = int(scores["resolved"])  # type: ignore[arg-type]
    mean_brier = scores["mean_brier"]
    if resolved < MIN_RESOLVED_FOR_A_GATE or mean_brier is None:
        return Gate("evidence_quality", GateOutcome.UNEVALUABLE,
                    f"{resolved} resolved forecasts; {MIN_RESOLVED_FOR_A_GATE} "
                    f"needed before calibration means anything")
    if float(mean_brier) > prediction.UNINFORMATIVE_BRIER:
        return Gate("evidence_quality", GateOutcome.REJECTED,
                    f"mean Brier {float(mean_brier):.3f} over {resolved} resolved "
                    f"forecasts is worse than a flat 0.5 guess ({prediction.UNINFORMATIVE_BRIER})")
    return Gate("evidence_quality", GateOutcome.PASSED,
                f"mean Brier {float(mean_brier):.3f} over {resolved} resolved forecasts")


def _policy_compliance(conn: sqlite3.Connection, cell_id: str, request_id: str) -> Gate:
    """Quarantine (§18) and §23.4's escalating signals — detections, not opinions.

    Both are facts the kernel recorded about behaviour that already happened, so
    rejecting on them is not the "estimated negative EV" §10.5 forbids acting
    on. `understated_risk` is excluded here for the same reason `approval.py`
    excludes it from `_ESCALATING_SIGNALS`: it is derived from the kernel's own
    assessment, and letting it gate would make a finding raise the bar it was
    measured against.
    """
    status = conn.execute("SELECT status FROM cells WHERE cell_id = ?", (cell_id,)).fetchone()
    if status is not None and status["status"] == CellStatus.QUARANTINED.value:
        return Gate("policy_compliance", GateOutcome.REJECTED, "the Cell is quarantined (§18)")

    rows = conn.execute(
        "SELECT signal, detail FROM approval_signals WHERE request_id = ? ORDER BY rowid",
        (request_id,),
    ).fetchall()
    escalating = [r for r in rows if r["signal"] in approval._ESCALATING_SIGNALS]
    if escalating:
        named = ", ".join(f"{r['signal']} ({r['detail']})" for r in escalating)
        return Gate("policy_compliance", GateOutcome.REJECTED, f"§23.4 signals: {named}")
    return Gate("policy_compliance", GateOutcome.PASSED,
                "not quarantined; no escalating §23.4 signal on this request")


def _software_native_advantage(conn: sqlite3.Connection, cell_id: str) -> Gate:
    """§13.3's list, read from a *resolved* `content_audit.py` judgment.

    **Only a resolved prediction may gate.** `content_audit.py`'s own docstring
    names the reason this wiring was deferred: reading an Auditor's probability
    before the register has scored it would gate a candidate on an *estimate*
    — exactly the shape §10.5 forbids acting on automatically. Once the
    prediction resolves it is a realised fact, the same discipline
    `_evidence_quality` and `_policy_compliance` already apply.

    **No audit for this genome is `UNMEASURABLE`**, unchanged from before this
    slice. **An audit that exists but has not resolved is `UNEVALUABLE`**, not
    a rejection — an Auditor's claim before its horizon is up tells this gate
    nothing yet, the same distinction `_evidence_quality` draws for a Cell with
    no resolved forecasts.

    **Any single resolved audit whose claim resolved false rejects.** The claim
    is always "genuinely §13.3" (`content_audit.precision`'s own comment), so a
    false resolution is a vindicated concern — a realised finding, not an
    opinion. This takes the same posture `_policy_compliance` already takes
    with a single escalating signal, rather than requiring every Auditor who
    has ever judged this genome to agree; §10.5's stronger "an Auditor must
    concur" bar is written for killing a Cell, not for screening a candidate
    out of one funding round.
    """
    row = conn.execute("SELECT genome_hash FROM cells WHERE cell_id = ?", (cell_id,)).fetchone()
    if row is None:
        return _unmeasurable_gate("software_native_advantage")

    resolved_outcomes: list[bool] = []
    unresolved = False
    for record in content_audit.audits_for_genome(conn, row["genome_hash"]):
        # `compared_genome_hash` is always NULL for this kind (migration
        # 0031's CHECK), so a match here is always about `genome_hash` itself,
        # never about this genome appearing as the *comparison* side of a
        # `renamed_mechanism` pair.
        if record.kind is not content_audit.Kind.SOFTWARE_NATIVE_ADVANTAGE or not record.is_recorded:
            continue
        assert record.prediction_id is not None
        registered = prediction.get(conn, record.prediction_id)
        assert registered is not None
        if not registered.is_resolved:
            unresolved = True
            continue
        resolved_outcomes.append(bool(registered.outcome))

    if any(outcome is False for outcome in resolved_outcomes):
        n = sum(1 for o in resolved_outcomes if o is False)
        return Gate("software_native_advantage", GateOutcome.REJECTED,
                    f"{n} resolved content audit(s) found this genome does not genuinely "
                    "have §13.3's program-native advantage")
    if resolved_outcomes:
        return Gate("software_native_advantage", GateOutcome.PASSED,
                    f"{len(resolved_outcomes)} resolved content audit(s) found this genome "
                    "genuinely has §13.3's program-native advantage")
    if unresolved:
        return Gate("software_native_advantage", GateOutcome.UNEVALUABLE,
                    "a content audit exists for this genome but has not resolved yet")
    return _unmeasurable_gate("software_native_advantage")


def _unmeasurable_gate(dimension: str) -> Gate:
    return Gate(dimension, GateOutcome.UNMEASURABLE, GATE_DIMENSIONS[dimension])


# --- frontier axes ------------------------------------------------------------


def _information_gain(conn: sqlite3.Connection, proposal_id: str) -> Axis:
    """Mean normalised entropy of the forecasts registered with this proposal.

    A forecast at p = 0.5 resolves to a full bit; one at p = 0.99 tells the
    colony almost nothing it did not already believe. Reaching them is two joins
    — `proposals.deliberation_id` → `deliberation_predictions` → the register —
    and `deliberation_predictions` has had no reader outside `deliberation`
    since migration 0013.

    Normalised by ln 2 so the axis lands in (0, 1], which is what §13.1's "never
    subtract raw dollars from scores in [0,1]" wants of every axis it sits
    beside. `probability` is CHECKed strictly between 0 and 1, so the entropy is
    always defined.
    """
    rows = conn.execute(
        """
        SELECT r.probability
          FROM proposals p
          JOIN deliberation_predictions dp ON dp.deliberation_id = p.deliberation_id
          JOIN prediction_register r ON r.prediction_id = dp.prediction_id
         WHERE p.proposal_id = ?
        """,
        (proposal_id,),
    ).fetchall()
    if not rows:
        return Axis("information_gain", None,
                    "the proposal registered no forecasts, so there is no claim to resolve")
    entropies = []
    for row in rows:
        p = float(row["probability"])
        entropies.append(-(p * math.log(p) + (1 - p) * math.log(1 - p)) / math.log(2))
    return Axis("information_gain", sum(entropies) / len(entropies),
                f"mean normalised entropy of {len(entropies)} registered forecast(s)")


def _experiment_cost(conn: sqlite3.Connection, cell_id: str, estimated: int) -> Axis:
    """§13.1's `normalised_cost`, computed for a candidate rather than a run.

    FUTURE_BUILD_HOOKS asked, when ADR-048 shipped this ratio with no consumer,
    that §13.2 "check that this ratio is the dimension it wants rather than
    assuming it". It is: §13.2 lists "experiment cost" among the five, and §13.1
    exists to make exactly that quantity comparable — "Never subtract raw
    dollars from scores in [0,1]". This is that clause's first consumer.

    `None` when the Cell has never been promoted, which today is most of them:
    there is no stage budget to divide by, and dividing by its own balance would
    be a confident-looking number measuring something §13.1 never named
    (`experiments.stage_tranche` makes the same refusal).
    """
    tranche = experiments.stage_tranche(conn, cell_id)
    if tranche is None:
        return Axis("experiment_cost", None,
                    "the Cell has no promotion, so §13.1 has no stage tranche to divide by")
    rung, allocated = tranche
    if allocated <= 0:
        return Axis("experiment_cost", None, f"the rung-{rung} tranche is {allocated}")
    return Axis("experiment_cost", estimated / allocated,
                f"{estimated} / {allocated} minor units of the rung-{rung} tranche")


def _transfer_robustness(conn: sqlite3.Connection, cell_id: str) -> Axis:
    """§25.2's transfer degradation, reused rather than reinvented.

    `promotion.transfer_degradation` already answers "how much worse did this
    Cell do at its last rung than it predicted", reports `None` rather than 0
    for a Cell never promoted, and gets the sign right (Brier is a loss). §13.2
    calls the dimension transfer *robustness*, so the axis prefers a smaller
    number — see `HIGHER_IS_BETTER`.
    """
    value = promotion.transfer_degradation(conn, cell_id)
    if value is None:
        return Axis("transfer_robustness", None,
                    "no earlier promotion to have degraded from")
    return Axis("transfer_robustness", value,
                f"Brier moved {value:+.3f} since the last promotion (a loss: lower is better)")


#: §12.1's bins as a frontier ordinal. Positions, not scores — the gaps carry no
#: meaning, which is why domination only ever compares them for order.
_NOVELTY_ORDINAL: dict[str, float] = {"adjacent": 0.0, "moderate": 1.0, "radical": 2.0}


def _structural_novelty(conn: sqlite3.Connection, cell_id: str) -> Axis:
    """§12.1's novelty distance, read as §13.2's structural-novelty axis.

    **What it is honest about.** This measures *distance* — how much of the
    business hypothesis differs from everything the colony tried earlier. A
    small distance is evidence of §13.4's first flag ("only the industry label
    changed"). A large one is not proof of new structure: a genome whose every
    field changed to nonsense scores `radical`, and catching that is §13.4's
    fourth flag, which ADR-058 had to build outside the kernel.

    **Being an axis rather than a score is what makes that acceptable.** Nothing
    is funded for being radical; a radical candidate merely avoids being
    dominated by an otherwise-identical adjacent one. §13.2's refusal of a
    weighted scalar is doing real work here — added to anything, this number
    would carry decisions it cannot support.

    Abstains for the founder genome, which has nothing earlier to be novel
    against (`Measurement.UNEVALUABLE`), rather than calling it radical.
    """
    row = conn.execute("SELECT genome_hash FROM cells WHERE cell_id = ?", (cell_id,)).fetchone()
    if row is None:
        return Axis("structural_novelty", None, "no such Cell")
    found = next(
        d for d in novelty.descriptors(conn, row["genome_hash"])
        if d.dimension == "novelty_distance"
    )
    if found.measurement is not novelty.Measurement.MEASURED or found.bin is None:
        return Axis("structural_novelty", None, found.reason)
    return Axis("structural_novelty", _NOVELTY_ORDINAL[found.bin], f"{found.bin}: {found.reason}")


def _unmeasurable_axis(dimension: str) -> Axis:
    return Axis(dimension, None, FRONTIER_DIMENSIONS[dimension])


# --- domination ---------------------------------------------------------------


def dominates(better: Candidate, worse: Candidate) -> bool:
    """Pareto domination over the axes **both** candidates have measured.

    At least as good everywhere, strictly better somewhere — the same rule
    `death._dominates` applies to realised records, and the same refusal: an
    axis only one of them has evidence on is skipped, "because domination on no
    evidence is just an opinion with a body count".

    A pair sharing no measured axis therefore never dominates, and both stay on
    the frontier. That is the honest outcome of a colony that cannot yet measure
    four of §13.2's nine dimensions, and it is why this function is written to
    abstain rather than to fall back on whichever axis happens to exist.
    """
    strictly_better_somewhere = False
    for dimension, higher_is_better in HIGHER_IS_BETTER.items():
        mine, theirs = better.axis(dimension), worse.axis(dimension)
        if mine is None or theirs is None or not (mine.measured and theirs.measured):
            continue
        a, b = float(mine.value), float(theirs.value)  # type: ignore[arg-type]
        if a == b:
            continue
        if (a > b) is higher_is_better:
            strictly_better_somewhere = True
        else:
            return False
    return strictly_better_somewhere


# --- the selector -------------------------------------------------------------


def waiting_candidates(
    conn: sqlite3.Connection, *, now: datetime | None = None
) -> list[tuple[approval.Grant, int]]:
    """Approved grants that have not been consumed and have not expired.

    **Deliberately not `promotion.allocatable_grants`**, though it looked like
    the same list. That one answers "which grants could the capital pool fund
    right now" and therefore filters to spend requests; §13 evaluates
    *experiments* as well, and §13.1's formula is written about an experiment's
    cost. Reusing it would have left the clause's own cost dimension measuring
    only the kind it was not named for.

    Ordered by grant time so the output is stable, which is not an ordering of
    merit — see `Frontier`.
    """
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        """
        SELECT g.grant_id, p.estimated_cost_minor_units
          FROM approval_grants g
          JOIN proposals p ON p.proposal_id = g.proposal_id
         WHERE g.consumed_at_utc IS NULL
           AND g.expires_at_utc > ?
           AND p.kind IN (%s)
           AND p.estimated_cost_minor_units > 0
         ORDER BY g.granted_at_utc, g.rowid
        """ % ",".join("?" * len(CANDIDATE_KINDS)),
        (now.isoformat(), *sorted(k.value for k in CANDIDATE_KINDS)),
    ).fetchall()
    return [
        (approval.get_grant(conn, r["grant_id"]), int(r["estimated_cost_minor_units"]))
        for r in rows
    ]


def evaluate(conn: sqlite3.Connection, *, now: datetime | None = None) -> Frontier:
    """§13.2 over the grants waiting on the promotion pool.

    Gates first, then the frontier over what survives — the clause's own order,
    and it matters: a rejected candidate is not compared at all, so it can never
    dominate a compliant one on cost.
    """
    now = now or datetime.now(timezone.utc)

    candidates: list[Candidate] = []
    for grant, estimated in waiting_candidates(conn, now=now):
        candidates.append(
            Candidate(
                grant_id=grant.grant_id,
                proposal_id=grant.proposal_id,
                cell_id=grant.cell_id,
                estimated_cost_minor_units=estimated,
                gates=(
                    _evidence_quality(conn, grant.cell_id),
                    _unmeasurable_gate("reproducibility"),
                    _policy_compliance(conn, grant.cell_id, grant.request_id),
                    _software_native_advantage(conn, grant.cell_id),
                ),
                axes=(
                    _structural_novelty(conn, grant.cell_id),
                    _information_gain(conn, grant.proposal_id),
                    _unmeasurable_axis("economic_potential"),
                    _experiment_cost(conn, grant.cell_id, estimated),
                    _transfer_robustness(conn, grant.cell_id),
                ),
            )
        )

    surviving = [c for c in candidates if c.passes_gates]
    frontier = {
        c.grant_id for c in surviving
        if not any(dominates(other, c) for other in surviving if other.grant_id != c.grant_id)
    }
    measured = sorted({a.dimension for c in candidates for a in c.axes if a.measured})
    unmeasured = sorted(set(FRONTIER_DIMENSIONS) - set(measured))
    return Frontier(
        assessed_at_utc=now,
        candidates=tuple(candidates),
        frontier_grant_ids=frozenset(frontier),
        rejected_grant_ids=frozenset(c.grant_id for c in candidates if not c.passes_gates),
        measured_dimensions=tuple(measured),
        unmeasured_dimensions=tuple(unmeasured),
    )
