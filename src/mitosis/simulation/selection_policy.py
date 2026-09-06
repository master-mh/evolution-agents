"""A replaceable, recorded selection policy (implementation brief Slice G;
`docs/DECISIONS.md`'s Slice G ADRs and the approved plan file have the full
architecture).

`SelectionPolicy` decides which Cell(s) reproduce each epoch and records a
full decision, not just a list of winners (brief Slice G's own requirement).
`RandomEligibleSelection` (policy #1, F1), `SingleLeaderboardSelection`
(policy #2, an intentionally-forbidden single-scalar shape kept only as a
Phase 3 comparator), `ParetoSelection` (policy #3, reproduces the whole
Pareto front), `MapElitesSelection` (policy #4, one elite per occupied
niche), and `StagedFundingSelection` (policy #5, "the intended policy" --
composes #3's gates plus a new `validation_probe` gate, #4's niche/elite
rule, and a genuinely budget-constrained Thompson-sampled choice across
niches) all ship here.
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass
from typing import Protocol

from .. import ledger, lifecycle, novelty, posteriors
from ..accounts import cell_cash
from ..models import Book, CellStatus
from . import candidate, environment, mutation

#: Generous for a toy F1 economy: a parent needs this much left over *after*
#: funding a child so it can still pay for its own next wake (§15.4).
_CHILD_BUDGET_MINOR_UNITS = 100
_MIN_RETAINED_CASH_MINOR_UNITS = 50

#: Every simulator-native dimension name (`candidate.py`), for a policy that
#: consults none of them to report honestly -- `unmeasured_dimensions` names
#: what *could* be measured and wasn't, never an unexplained empty tuple.
_ALL_SIM_DIMENSIONS: tuple[str, ...] = tuple(
    sorted(set(candidate.SIM_GATE_DIMENSIONS) | set(candidate.SIM_FRONTIER_DIMENSIONS))
)


@dataclass(frozen=True)
class NicheStanding:
    """One niche's standing at decision time -- brief Slice G's "niche
    assignment and current niche occupant" plus "posterior values or samples
    actually used", bundled per niche rather than as parallel tuples that
    could disagree on length or order."""

    coordinate: tuple[tuple[str, str], ...]
    living_cell_ids: tuple[str, ...]
    elite_cell_id: str | None
    posterior_trials: int
    posterior_conversions: int
    posterior_alpha: float
    posterior_beta: float
    posterior_mean: float
    thompson_sample: float | None
    funded_this_epoch: bool


@dataclass(frozen=True)
class SelectionDecision:
    """Brief Slice G's required decision-record fields. New fields are all
    defaulted, so a policy with nothing to report for one (like
    `RandomEligibleSelection`, which runs no gates and consults no niches)
    states that explicitly in `reason`/`intended_experiment` rather than
    leaving a silently-empty field with no explanation -- the same posture
    this dataclass's own F1 docstring already established for its first,
    smaller field set."""

    policy_name: str
    policy_version: str
    epoch: int
    rng_seed_label: str
    eligible_cell_ids: tuple[str, ...]
    chosen_parent_cell_ids: tuple[str, ...]
    mutation_operator: str
    child_budget_minor_units: int
    reason: str
    gate_results: tuple[candidate.GateResult, ...] = ()
    measured_dimensions: tuple[str, ...] = ()
    unmeasured_dimensions: tuple[str, ...] = ()
    pareto_front_cell_ids: tuple[str, ...] = ()
    niches: tuple[NicheStanding, ...] = ()
    #: (parent_cell_id, operator) overrides for a policy reproducing from
    #: multiple parents in one epoch, each wanting its own operator -- a
    #: policy that reproduces from at most one parent (like
    #: `RandomEligibleSelection`) never populates this; `runner.py` falls
    #: back to `mutation_operator` above when a parent has no entry here.
    parent_mutation_operators: tuple[tuple[str, str], ...] = ()
    #: Same pattern as `parent_mutation_operators`, for a per-niche budget
    #: that scales with that niche's own posterior confidence.
    parent_child_budgets: tuple[tuple[str, int], ...] = ()
    intended_experiment: str = ""


class SelectionPolicy(Protocol):
    name: str
    version: str

    def decide(
        self, conn, *, epoch: int, rng: random.Random, seed_label: str
    ) -> SelectionDecision: ...


def _eligible_parents(conn, *, book: Book) -> list[lifecycle.Cell]:
    eligible = []
    for cell in lifecycle.list_cells(conn):
        if cell.status is not CellStatus.ALIVE or cell.book is not book:
            continue
        cash = ledger.get_balance(conn, cell_cash(cell.cell_id), book)
        if cash >= _CHILD_BUDGET_MINOR_UNITS + _MIN_RETAINED_CASH_MINOR_UNITS:
            eligible.append(cell)
    return eligible


class RandomEligibleSelection:
    name = "random_eligible"
    version = "1"

    def __init__(self, *, book: Book = Book.USD_SIM) -> None:
        self._book = book

    def decide(
        self, conn, *, epoch: int, rng: random.Random, seed_label: str
    ) -> SelectionDecision:
        eligible = _eligible_parents(conn, book=self._book)
        chosen = tuple(cell.cell_id for cell in rng.sample(eligible, k=min(1, len(eligible))))
        # Reuses this same call's `rng` rather than drawing a second one --
        # the choice is still deterministic given `seed_label`, just a later
        # value in the one stream this decision already consumes from.
        operator = rng.choice(sorted(mutation.OPERATORS)) if chosen else mutation.NO_OP_OPERATOR
        return SelectionDecision(
            policy_name=self.name,
            policy_version=self.version,
            epoch=epoch,
            rng_seed_label=seed_label,
            eligible_cell_ids=tuple(c.cell_id for c in eligible),
            chosen_parent_cell_ids=chosen,
            mutation_operator=operator,
            child_budget_minor_units=_CHILD_BUDGET_MINOR_UNITS,
            reason=(
                f"{len(eligible)} cell(s) eligible ({self._book.value} cash >= "
                f"{_CHILD_BUDGET_MINOR_UNITS + _MIN_RETAINED_CASH_MINOR_UNITS}); "
                f"chose {len(chosen)} uniformly at random -- brief Slice G policy #1, "
                "no quality-diversity signal consulted; mutation operator chosen "
                "uniformly at random among all registered operators"
            ),
            unmeasured_dimensions=_ALL_SIM_DIMENSIONS,
            intended_experiment=(
                "none -- this policy does not read a candidate's proposed "
                "hypothesis before choosing it, by design (brief Slice G policy #1)"
            ),
        )


#: Brief Slice G policy #2's own named scalar -- a class attribute, not a
#: buried literal, so the decision record can state exactly what it
#: collapsed fitness into.
_SCALAR_METRIC = "realized_net_revenue_minor_units"


class SingleLeaderboardSelection:
    """Brief Slice G policy #2: "a single-leaderboard baseline with an
    explicitly declared scalar metric, used only as an experimental
    control." SPEC.md §10.2/§13.2 both forbid exactly this shape for the
    production kernel — built here on purpose, clearly labelled, so Slice H
    has a real comparator for "intended selection vs random mutation" and
    "Pareto vs a single scalar," never as a candidate default."""

    name = "single_leaderboard"
    version = "1"
    scalar_metric = _SCALAR_METRIC

    def __init__(self, *, book: Book = Book.USD_SIM) -> None:
        self._book = book

    def decide(
        self, conn, *, epoch: int, rng: random.Random, seed_label: str
    ) -> SelectionDecision:
        eligible = _eligible_parents(conn, book=self._book)

        def _rank_key(cell: lifecycle.Cell) -> tuple:
            revenue_axis = candidate._realized_net_revenue(conn, cell.cell_id)
            # Unmeasured (no concluded experiment yet) ranks last: a
            # leaderboard needs one total order over every eligible cell,
            # and "has proven nothing yet" cannot outrank a proven, even
            # small, positive result -- stated here rather than silently
            # decided, since `Axis.value is None` is never "zero" elsewhere
            # in this codebase.
            has_evidence = revenue_axis.value is not None
            return (
                not has_evidence, -(revenue_axis.value or 0.0),
                cell.generation, cell.created_at_utc, cell.cell_id,
            )

        ranked = sorted(eligible, key=_rank_key)
        chosen = (ranked[0].cell_id,) if ranked else ()
        operator = rng.choice(sorted(mutation.OPERATORS)) if chosen else mutation.NO_OP_OPERATOR
        return SelectionDecision(
            policy_name=self.name,
            policy_version=self.version,
            epoch=epoch,
            rng_seed_label=seed_label,
            eligible_cell_ids=tuple(c.cell_id for c in eligible),
            chosen_parent_cell_ids=chosen,
            mutation_operator=operator,
            child_budget_minor_units=_CHILD_BUDGET_MINOR_UNITS,
            reason=(
                f"{len(eligible)} cell(s) eligible; ranked by {_SCALAR_METRIC} descending "
                "(a cell with no concluded experiment yet ranks last, never tied with a "
                "proven zero), chose the single top-ranked cell -- brief Slice G policy #2, "
                "an intentionally-forbidden single-scalar shape (SPEC.md §10.2/§13.2) built "
                "only as a Phase 3 experimental control, never a default. No gates run."
            ),
            measured_dimensions=("realized_net_revenue",),
            unmeasured_dimensions=tuple(d for d in _ALL_SIM_DIMENSIONS if d != "realized_net_revenue"),
            intended_experiment=(
                "none -- this policy ranks by realized revenue alone and does not read a "
                "candidate's proposed hypothesis before choosing it"
            ),
        )


#: Every SIM dimension except `economic_potential` (permanently unmeasurable)
#: and `validation_probe` (only `StagedFundingSelection` ever supplies a
#: validation environment to judge it) -- `ParetoSelection` runs both gates
#: and consults every axis it *can* measure, nothing more.
_PARETO_MEASURED_DIMENSIONS: tuple[str, ...] = tuple(
    d for d in _ALL_SIM_DIMENSIONS if d not in ("economic_potential", "validation_probe")
)


class ParetoSelection:
    """Brief Slice G policy #3: Pareto selection without MAP-Elites. Gates
    on `candidate.SIM_GATE_DIMENSIONS` (`not_quarantined`, `reproducibility`)
    and takes the Pareto front over every measurable axis
    (`structural_novelty`, `realized_net_revenue`, `experiment_success_rate`
    — `economic_potential` stays unmeasurable, see `candidate.py`).
    Reproduces from *every* Cell on the resulting front, not a single
    winner -- SPEC.md §10.2's portfolio, not a scalar with an extra step,
    and what actually distinguishes this from `SingleLeaderboardSelection`."""

    name = "pareto"
    version = "1"

    def __init__(self, *, book: Book = Book.USD_SIM) -> None:
        self._book = book

    def decide(
        self, conn, *, epoch: int, rng: random.Random, seed_label: str
    ) -> SelectionDecision:
        eligible = _eligible_parents(conn, book=self._book)
        candidates = [candidate.cell_candidate(conn, cell) for cell in eligible]
        rejected = sum(1 for c in candidates if not c.passes_gates)
        # Sorted by cell_id, not discovery order: which requests get
        # refused if a rate cap is hit mid-epoch (`lineage.reproduce`'s own
        # caps do the actual bounding, see the Slice G plan's "Reproduction
        # bounds" note) is then itself seed-reproducible.
        chosen = tuple(sorted(candidate.pareto_frontier(candidates)))
        operator_overrides = tuple(
            (cell_id, rng.choice(sorted(mutation.OPERATORS))) for cell_id in chosen
        )
        gate_results = tuple(g for c in candidates for g in c.gates)
        return SelectionDecision(
            policy_name=self.name,
            policy_version=self.version,
            epoch=epoch,
            rng_seed_label=seed_label,
            eligible_cell_ids=tuple(c.cell_id for c in eligible),
            chosen_parent_cell_ids=chosen,
            # Vestigial for this policy: every chosen parent has its own
            # entry in `parent_mutation_operators` below, so `runner.py`
            # never falls back to this field. `NO_OP_OPERATOR` is used
            # rather than a drawn value, so nothing implies this field
            # carries a real decision for a multi-parent policy.
            mutation_operator=mutation.NO_OP_OPERATOR,
            child_budget_minor_units=_CHILD_BUDGET_MINOR_UNITS,
            reason=(
                f"{len(eligible)} cell(s) eligible, {rejected} rejected by a gate "
                f"(not_quarantined/reproducibility); {len(chosen)} cell(s) on the Pareto "
                "front over structural_novelty/realized_net_revenue/experiment_success_rate "
                "-- brief Slice G policy #3, reproducing the whole front rather than one winner"
            ),
            gate_results=gate_results,
            measured_dimensions=_PARETO_MEASURED_DIMENSIONS,
            unmeasured_dimensions=("economic_potential", "validation_probe"),
            pareto_front_cell_ids=chosen,
            parent_mutation_operators=operator_overrides,
            intended_experiment=(
                "none -- this policy selects parents by realised standing, not by "
                "reading a candidate's proposed hypothesis"
            ),
        )


def _living_cell_ids_in_niche(conn, niche: novelty.Niche) -> tuple[str, ...]:
    """Every living Cell in a niche, matching `novelty.py`'s own definition
    of living (`status IN ('created','alive','dormant','quarantined')`,
    i.e. not dead) -- broader than `_eligible_parents`'s alive-with-cash
    filter on purpose: this field describes niche *occupancy*, a colony
    fact, not reproduction *eligibility*, which the decision record already
    carries separately."""
    return tuple(sorted(
        cell.cell_id for cell in lifecycle.list_cells(conn)
        if cell.status is not CellStatus.DEAD and cell.genome_hash in niche.genome_hashes
    ))


class MapElitesSelection:
    """Brief Slice G policy #4: MAP-Elites/quality-diversity selection with
    a defined elite rule. Niches come from a direct, unmodified call to
    `novelty.archive()`; `candidate.niche_elite()` (built in G1, its first
    real caller) picks one elite per occupied niche. Reproduces from
    *every* occupied niche's elite each epoch -- MAP-Elites' classical
    behaviour is to keep re-trying every occupied niche, not to allocate a
    scarce budget across them (that budget-constrained choice is
    `StagedFundingSelection`'s job, via Thompson sampling, in a later
    sub-slice). Each niche's real posterior is still recorded on its
    `NicheStanding` for transparency -- `thompson_sample` stays `None`
    because this policy never draws one, not because the posterior itself
    is unavailable."""

    name = "map_elites"
    version = "1"

    def __init__(self, *, book: Book = Book.USD_SIM) -> None:
        self._book = book

    def decide(
        self, conn, *, epoch: int, rng: random.Random, seed_label: str
    ) -> SelectionDecision:
        eligible = _eligible_parents(conn, book=self._book)
        eligible_ids = frozenset(c.cell_id for c in eligible)
        archive = novelty.archive(conn)
        posterior_by_coordinate = {p.coordinate: p for p in posteriors.posteriors(conn).niches}

        niche_standings: list[NicheStanding] = []
        chosen: list[str] = []
        operator_overrides: list[tuple[str, str]] = []
        # Sorted by coordinate, not archive discovery order: which niches
        # get to reproduce first (relevant only if a colony-wide rate cap
        # is hit mid-epoch, `lineage.reproduce`'s own job to enforce) is
        # then itself seed-reproducible.
        for niche in sorted(archive.niches, key=lambda n: n.coordinate):
            elite_cell_id = candidate.niche_elite(conn, niche, eligible_ids, rng=rng)
            funded = elite_cell_id is not None
            if funded:
                chosen.append(elite_cell_id)
                operator_overrides.append(
                    (elite_cell_id, rng.choice(sorted(mutation.OPERATORS)))
                )
            posterior = posterior_by_coordinate.get(niche.coordinate)
            niche_standings.append(NicheStanding(
                coordinate=niche.coordinate,
                living_cell_ids=_living_cell_ids_in_niche(conn, niche),
                elite_cell_id=elite_cell_id,
                posterior_trials=posterior.trials if posterior else 0,
                posterior_conversions=posterior.conversions if posterior else 0,
                posterior_alpha=posterior.alpha if posterior else posteriors.PRIOR_ALPHA,
                posterior_beta=posterior.beta if posterior else posteriors.PRIOR_BETA,
                posterior_mean=posterior.posterior_mean if posterior else 0.5,
                thompson_sample=None,
                funded_this_epoch=funded,
            ))
        chosen_tuple = tuple(chosen)
        return SelectionDecision(
            policy_name=self.name,
            policy_version=self.version,
            epoch=epoch,
            rng_seed_label=seed_label,
            eligible_cell_ids=tuple(c.cell_id for c in eligible),
            chosen_parent_cell_ids=chosen_tuple,
            # Vestigial, as in `ParetoSelection`: every chosen parent has
            # its own entry in `parent_mutation_operators`.
            mutation_operator=mutation.NO_OP_OPERATOR,
            child_budget_minor_units=_CHILD_BUDGET_MINOR_UNITS,
            reason=(
                f"{len(archive.niches)} niche(s) in the archive ({len(archive.unbinned_genome_hashes)} "
                "unbinned genome(s) outside any of them); an elite chosen for "
                f"{sum(1 for n in niche_standings if n.funded_this_epoch)} occupied niche(s) -- "
                "brief Slice G policy #4, reproducing every occupied niche's elite, not a "
                "budget-constrained subset (posteriors recorded per niche but not sampled from; "
                "see StagedFundingSelection)"
            ),
            # `structural_novelty` decides niche coordinates (`novelty.archive`);
            # `realized_net_revenue` decides the elite *within* an occupied
            # niche (`candidate.niche_elite`'s own tie-break). No gate runs --
            # this policy never calls `candidate.cell_candidate()` at all.
            measured_dimensions=("structural_novelty", "realized_net_revenue"),
            unmeasured_dimensions=tuple(
                d for d in _ALL_SIM_DIMENSIONS
                if d not in ("structural_novelty", "realized_net_revenue")
            ),
            niches=tuple(niche_standings),
            parent_mutation_operators=tuple(operator_overrides),
            intended_experiment=(
                "none -- this policy selects parents by niche occupancy and realised "
                "standing, not by reading a candidate's proposed hypothesis"
            ),
        )


#: How many niches this colony backs per epoch under staged funding -- a
#: small, explicit cap on a scarce budget (the entire point of a Thompson
#: *sampled* choice across niches, as opposed to `MapElitesSelection`'s own
#: "fund every occupied niche" posture). Not derived from anything else in
#: this module; a future Slice would need a real reason to change it.
_STAGED_FUNDING_TOP_K = 3

#: A niche's per-parent child budget scales with its own posterior mean --
#: a niche with a real rung-7->8 track record gets more than the untested
#: base amount, one with a poor track record gets less. `1.0` doubles the
#: base budget at full confidence (mean=1.0); the uninformative prior
#: (mean=0.5, the common case for a niche with zero trials) yields 1.5x.
_STAGED_FUNDING_BUDGET_SCALE = 1.0


def _staged_child_budget(posterior_mean: float) -> int:
    return _CHILD_BUDGET_MINOR_UNITS + round(
        _CHILD_BUDGET_MINOR_UNITS * _STAGED_FUNDING_BUDGET_SCALE * posterior_mean
    )


#: Derived, not hardcoded as its own complement, so a future dimension added
#: to `candidate.py` shows up in `unmeasured_dimensions` automatically rather
#: than needing this policy remembered too.
_STAGED_FUNDING_MEASURED_DIMENSIONS: tuple[str, ...] = (
    "not_quarantined", "reproducibility", "structural_novelty",
    "realized_net_revenue", "validation_probe",
)


def _uninformative_posterior(coordinate: tuple[tuple[str, str], ...]) -> posteriors.StageConversionPosterior:
    return posteriors.StageConversionPosterior(
        coordinate=coordinate, trials=0, conversions=0,
        alpha=posteriors.PRIOR_ALPHA, beta=posteriors.PRIOR_BETA, posterior_mean=0.5,
        reason="no rung-7 promotion has been issued to a Cell in this niche yet",
    )


class StagedFundingSelection:
    """Brief Slice G policy #5 -- "the intended policy," composing every
    earlier sub-slice rather than adding a sixth independent mechanism.

    Gates every eligible Cell on `ParetoSelection`'s own two dimensions
    (`not_quarantined`, `reproducibility`) before a gate-survivor can even be
    considered as a niche elite. Niches and their elites come from
    `MapElitesSelection`'s own rule (`novelty.archive()` +
    `candidate.niche_elite()`, restricted to gate survivors). Each niche's
    real §12.3 posterior gets one Thompson-sampled draw
    (`posteriors.sample()`, built in G1, its first real caller) -- funding
    only the top `_STAGED_FUNDING_TOP_K` sampled niches this epoch, at a
    per-niche budget that scales with that niche's own posterior mean
    (`_staged_child_budget`), rather than MAP-Elites' own "fund every
    occupied niche" posture.

    Before a niche's elite is even eligible to be funded, it must also clear
    `candidate.validation_probe` -- `EnvironmentSuite.validation`'s first
    real consumer, injected through *this constructor*, not a new
    `decide()` parameter. `SelectionPolicy.decide()` and
    `runner._run_one_epoch()` stay byte-identical to every other policy's,
    so `test_the_routine_epoch_loop_never_touches_validation_or_
    secret_challenge_environments`'s existing guarantee keeps holding,
    unmodified, for this policy and every other one alike. `validation=None`
    (the default) makes `validation_probe` report `UNEVALUABLE` for every
    elite -- an honestly weaker policy, not a crash, when a caller has
    nothing to probe with.
    """

    name = "staged_funding"
    version = "1"

    def __init__(
        self, *, book: Book = Book.USD_SIM,
        validation: environment.MarketEnvironment | None = None,
    ) -> None:
        self._book = book
        self._validation = validation

    def decide(
        self, conn, *, epoch: int, rng: random.Random, seed_label: str
    ) -> SelectionDecision:
        if self._validation is not None:
            # A stable int derived from `seed_label`, not `rng` -- resetting
            # an environment does not consume from the one draw stream this
            # decision's other choices (operators, `niche_elite`'s explore
            # branch) already share, and is harmless to repeat every call:
            # `evaluate()` is a pure function of its own inputs regardless of
            # how many times `reset()` ran first (`environment.py`'s own
            # docstring), so resetting with the same derived seed every
            # epoch is idempotent, not merely convenient.
            self._validation.reset(seed=zlib.crc32(seed_label.encode()))

        eligible = _eligible_parents(conn, book=self._book)
        eligible_by_id = {cell.cell_id: cell for cell in eligible}
        candidates = [candidate.cell_candidate(conn, cell) for cell in eligible]
        gate_results: list[candidate.GateResult] = [g for c in candidates for g in c.gates]
        gate_survivor_ids = frozenset(c.cell_id for c in candidates if c.passes_gates)
        rejected_by_gate = sum(1 for c in candidates if not c.passes_gates)

        archive = novelty.archive(conn)
        posterior_by_coordinate = {p.coordinate: p for p in posteriors.posteriors(conn).niches}
        genome_content_by_hash = {r.genome_hash: r.content for r in novelty.genome_records(conn)}

        # One row per niche, computed before any funding decision so the
        # top-K ranking below sees every niche's real draw, not a partial
        # set biased by evaluation order.
        rows: list[tuple[
            novelty.Niche, str | None, posteriors.StageConversionPosterior, float,
            candidate.GateResult | None,
        ]] = []
        for niche in sorted(archive.niches, key=lambda n: n.coordinate):
            elite_cell_id = candidate.niche_elite(conn, niche, gate_survivor_ids, rng=rng)
            posterior = posterior_by_coordinate.get(niche.coordinate) or _uninformative_posterior(
                niche.coordinate
            )
            thompson_sample = posteriors.sample(posterior, rng=rng)
            validation_gate = None
            if elite_cell_id is not None:
                elite_genome_hash = eligible_by_id[elite_cell_id].genome_hash
                validation_gate = candidate.validation_probe(
                    self._validation, cell_id=elite_cell_id,
                    genome_content=genome_content_by_hash[elite_genome_hash], epoch=epoch,
                )
                gate_results.append(validation_gate)
            rows.append((niche, elite_cell_id, posterior, thompson_sample, validation_gate))

        fundable = [
            row for row in rows
            if row[1] is not None
            and (row[4] is None or row[4].outcome is not candidate.GateOutcome.REJECTED)
        ]
        fundable.sort(key=lambda row: (-row[3], row[0].coordinate))
        funded_rows = fundable[:_STAGED_FUNDING_TOP_K]
        funded_coordinates = {row[0].coordinate for row in funded_rows}
        rejected_by_validation = sum(
            1 for row in rows
            if row[4] is not None and row[4].outcome is candidate.GateOutcome.REJECTED
        )

        niche_standings = tuple(
            NicheStanding(
                coordinate=niche.coordinate,
                living_cell_ids=_living_cell_ids_in_niche(conn, niche),
                elite_cell_id=elite_cell_id,
                posterior_trials=posterior.trials,
                posterior_conversions=posterior.conversions,
                posterior_alpha=posterior.alpha,
                posterior_beta=posterior.beta,
                posterior_mean=posterior.posterior_mean,
                thompson_sample=thompson_sample,
                funded_this_epoch=niche.coordinate in funded_coordinates,
            )
            for niche, elite_cell_id, posterior, thompson_sample, _ in rows
        )
        chosen = tuple(row[1] for row in funded_rows)
        operator_overrides = tuple(
            (row[1], rng.choice(sorted(mutation.OPERATORS))) for row in funded_rows
        )
        budget_overrides = tuple(
            (row[1], _staged_child_budget(row[2].posterior_mean)) for row in funded_rows
        )

        return SelectionDecision(
            policy_name=self.name,
            policy_version=self.version,
            epoch=epoch,
            rng_seed_label=seed_label,
            eligible_cell_ids=tuple(eligible_by_id),
            chosen_parent_cell_ids=chosen,
            # Vestigial, as in `ParetoSelection`/`MapElitesSelection`: every
            # funded parent has its own entries below.
            mutation_operator=mutation.NO_OP_OPERATOR,
            child_budget_minor_units=_CHILD_BUDGET_MINOR_UNITS,
            reason=(
                f"{len(eligible)} cell(s) eligible, {rejected_by_gate} rejected by a gate "
                f"(not_quarantined/reproducibility); {len(archive.niches)} niche(s) in the "
                f"archive, {rejected_by_validation} elite(s) rejected by validation_probe; "
                f"funded the top {len(funded_rows)} of {len(fundable)} fundable niche(s) by a "
                f"Thompson-sampled draw each (cap={_STAGED_FUNDING_TOP_K}) -- brief Slice G "
                "policy #5, composing ParetoSelection's gates plus validation_probe, "
                "MapElitesSelection's niche/elite rule, and a budget-constrained sampled choice "
                "across niches instead of funding every one"
            ),
            gate_results=tuple(gate_results),
            measured_dimensions=_STAGED_FUNDING_MEASURED_DIMENSIONS,
            unmeasured_dimensions=tuple(
                d for d in _ALL_SIM_DIMENSIONS if d not in _STAGED_FUNDING_MEASURED_DIMENSIONS
            ),
            niches=niche_standings,
            parent_mutation_operators=operator_overrides,
            parent_child_budgets=budget_overrides,
            intended_experiment=(
                "none -- this policy selects parents by niche occupancy, realised standing, "
                "and a sampled capital-allocation draw, not by reading a candidate's proposed "
                "hypothesis"
            ),
        )


class UnknownSelectionPolicyError(Exception):
    pass


def build_selection_policy(
    name: str, *, validation: environment.MarketEnvironment | None = None,
) -> SelectionPolicy:
    """A name -> instance factory, mirroring `environment.build_environment`,
    so a CLI flag or scenario config can select a policy without importing
    every concrete class itself. `validation` is used only when `name` is
    `StagedFundingSelection.name` -- see that class's own docstring for why
    the seam is a constructor argument, never a new `decide()` parameter."""
    if name == RandomEligibleSelection.name:
        return RandomEligibleSelection()
    if name == SingleLeaderboardSelection.name:
        return SingleLeaderboardSelection()
    if name == ParetoSelection.name:
        return ParetoSelection()
    if name == MapElitesSelection.name:
        return MapElitesSelection()
    if name == StagedFundingSelection.name:
        return StagedFundingSelection(validation=validation)
    raise UnknownSelectionPolicyError(
        f"no selection policy named {name!r}; available: "
        f"{RandomEligibleSelection.name}, {SingleLeaderboardSelection.name}, "
        f"{ParetoSelection.name}, {MapElitesSelection.name}, {StagedFundingSelection.name}"
    )
