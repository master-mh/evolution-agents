"""The flight simulator's orchestration loop (SPEC.md §7, §8, §28 Phase 2;
implementation brief Slice F).

Reuses existing kernel entry points throughout rather than maintaining a
second economic truth (brief requirement F.7): `lifecycle.create_cell` /
`lineage.reproduce` for population, `ledger` for money, `scheduler.tick` for
the wake/deliberation/auto-approval half (leaning on ADR-071's promoter
wiring), `experiment_grants` / `experiments` for turning an approved proposal
into a running, concluded experiment, `revenue.record_revenue` for posting
the environment's canonical outcome. This module supplies only the
*decisions* nothing in the kernel makes today: what a mock Cell proposes
(`policy.py`), what a customer does (`environment.py`), and which Cell
reproduces (`selection_policy.py`).
"""

from __future__ import annotations

import json
import random
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .. import (
    audit,
    autopromotion,
    clock,
    experiment_grants,
    experiments,
    ids,
    ledger,
    lifecycle,
    lineage,
    population,
    promotion,
    revenue,
    scheduler,
    tools,
)
from ..models import Book, CellStatus, CellType, ClockMode, EntrySpec
from . import mutation
from .environment import EnvironmentSuite, ExperimentAction, MarketEnvironment, UtilityMaximizingMarket
from .manifest import EpochRecord, RunManifest
from .policy import POLICY_MODEL_ID, POLICY_VERSION, SIMULATION_PROVIDER, SimulationPolicyProvider
from .selection_policy import RandomEligibleSelection, SelectionPolicy

#: A named, recorded, accountable decider for the simulator's own economy
#: decisions -- the same shape `autopromotion.DECIDER` established for the
#: kernel's unattended sweep, kept distinct because these are the simulator's
#: policy decisions rather than the kernel's own batchable-request sweep.
SIMULATION_DECIDER = "simulation"

_FOUNDING_BUDGET_MINOR_UNITS = 5_000
_SEED_ACCOUNT = "seed_bank"
_POOL_FUNDING_MINOR_UNITS = 100_000


class SimulationError(Exception):
    pass


@dataclass(frozen=True)
class RunConfig:
    scenario_name: str
    master_seed: int
    epochs: int
    population: int
    output_path: str | None = None


def _code_version() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _real_external_spend(conn) -> int:
    """Money actually leaving the colony in `Book.USD_REAL` -- `external_expense`
    activity, not transaction-row count. Every model call reserves and
    releases against USD_REAL regardless of provider (a `reservation_reserve`
    /`reservation_release` pair, cash <-> the Cell's own `committed` account,
    netting to zero every time for a zero-priced provider) -- that is
    pre-existing reservation-FSM bookkeeping for any free provider
    (`mock`/`ollama` included), not real spend, and counting those rows would
    make this invariant fire on every ordinary tick regardless of what a
    simulation run actually did."""
    row = conn.execute(
        "SELECT COALESCE(SUM(ABS(e.amount_minor_units)), 0) AS total "
        "FROM ledger_entries e JOIN ledger_transactions t ON t.transaction_id = e.transaction_id "
        "WHERE t.book = ? AND e.account_id = 'external_expense'",
        (Book.USD_REAL.value,),
    ).fetchone()
    return int(row["total"])


def _genome_content_of(conn, genome_hash: str) -> dict:
    row = conn.execute(
        "SELECT canonical_genome_json FROM cell_genomes WHERE genome_hash = ?",
        (genome_hash,),
    ).fetchone()
    if row is None:
        raise SimulationError(f"no genome recorded for hash {genome_hash}")
    return json.loads(row["canonical_genome_json"])


def _founder_genome(index: int) -> dict:
    return {
        "market": {"segment": f"segment-{index}"},
        "product": {"name": f"product-{index}"},
        "revenue_model": {"price_minor_units": 400 + 50 * (index % 3)},
    }


def _fund_scheduler_eligibility(conn, *, cell_id: str, key: str, amount_minor_units: int) -> None:
    """`scheduler.eligible_cells` requires a nonzero balance in USD_REAL *and*
    RESOURCE regardless of a Cell's own book -- a pre-existing scheduler rule,
    not something this slice introduces. Every Cell needs this, founder or
    reproduced child alike, or it is born permanently unschedulable. Sourced
    from `_SEED_ACCOUNT` like founding itself, never from a parent's own cash
    -- a child's *operating* budget comes from its parent (`lineage.reproduce`
    already enforces that via Charter C4); this sliver is colony
    infrastructure, the same category the founding pool itself is in.
    """
    for book, currency in ((Book.USD_REAL, "USD"), (Book.RESOURCE, "RESOURCE")):
        ledger.post_transaction(
            conn, book=book, currency=currency, transaction_type="cell_birth_funding",
            idempotency_key=f"{key}:{book.value}", description="simulation eligibility funding",
            entries=[
                EntrySpec(account_id=_SEED_ACCOUNT,
                          amount_minor_units=-amount_minor_units, cell_id=cell_id),
                EntrySpec(account_id=f"cell:{cell_id}:cash",
                          amount_minor_units=amount_minor_units, cell_id=cell_id),
            ],
        )


def _found_population(conn, config: RunConfig) -> list[lifecycle.Cell]:
    founders = []
    for i in range(config.population):
        key = f"sim:{config.scenario_name}:{config.master_seed}:founder:{i}"
        cell = lifecycle.create_cell(
            conn, cell_type=CellType.COMMERCIAL,
            budget_minor_units=_FOUNDING_BUDGET_MINOR_UNITS, book=Book.USD_SIM,
            idempotency_key=key, genome_content=_founder_genome(i),
        )
        # This is the one USD_REAL movement in the whole run that happens
        # before any epoch runs -- `run()` measures the invariant from this
        # point forward, not from before founding.
        _fund_scheduler_eligibility(
            conn, cell_id=cell.cell_id, key=key,
            amount_minor_units=_FOUNDING_BUDGET_MINOR_UNITS,
        )
        founders.append(cell)
    return founders


def _record_run_start(conn, *, run_id: str, config: RunConfig,
                       environment: MarketEnvironment, selection: SelectionPolicy,
                       started: datetime) -> None:
    conn.execute(
        """
        INSERT INTO simulation_runs (
            run_id, scenario_name, master_seed, code_version, environment_name,
            environment_version, policy_name, policy_version, population_target,
            epochs_target, status, started_at_utc, finished_at_utc, manifest_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, NULL, NULL)
        """,
        (
            run_id, config.scenario_name, config.master_seed, _code_version(),
            environment.name, environment.version, SIMULATION_PROVIDER, POLICY_VERSION,
            config.population, config.epochs, started.isoformat(),
        ),
    )
    conn.commit()


def _record_run_finish(conn, *, run_id: str, manifest: RunManifest, output_path: str | None) -> None:
    status = "completed" if not manifest.failures else "failed"
    conn.execute(
        "UPDATE simulation_runs SET status = ?, finished_at_utc = ?, manifest_path = ? "
        "WHERE run_id = ?",
        (status, datetime.now(timezone.utc).isoformat(), output_path, run_id),
    )
    conn.commit()


def _run_one_epoch(
    conn, *, epoch: int, run_id: str, policy: SimulationPolicyProvider,
    environment: MarketEnvironment, selection: SelectionPolicy, master_seed: int,
) -> EpochRecord:
    scheduler.tick(
        conn, provider=policy, model=POLICY_MODEL_ID,
        promoter=autopromotion.EvidencePromoter(),
    )

    started = 0
    for grant in experiment_grants.startable_grants(conn):
        try:
            experiment_grants.start_from_grant(
                conn, grant_id=grant["grant_id"], started_by=SIMULATION_DECIDER,
            )
            started += 1
        except experiments.ExperimentError:
            # `startable_grants()` is a snapshot taken once before this loop,
            # so it cannot see two conflicts this same loop can create as it
            # runs: a per-cell `ExperimentConflictError` (a cell can
            # legitimately carry two pending grants into one epoch -- an
            # approval's own WAKE_HUMAN_DECISION follow-up, §17.2, becomes
            # ready only on the *next* tick, alongside that epoch's regular
            # scheduled-research wake), and a colony-wide
            # `ExperimentCapacityError` once this loop's own earlier starts
            # fill every §9.2 slot. Both leave the grant unconsumed and
            # startable again once a slot frees -- the same "skip, don't
            # crash" posture `autopromotion.sweep()` takes on a per-grant
            # `PromotionError`. Catching the shared base rather than one
            # subclass is deliberate: at population >= `max_parallel_
            # experiments` (default 20) the capacity case is not a corner
            # case, it is the common one.
            pass

    concluded = 0
    sales = 0
    revenue_minor_units = 0
    for cell in lifecycle.list_cells(conn):
        if cell.status is not CellStatus.ALIVE:
            continue
        current = experiments.current_for(conn, cell.cell_id)
        if current is None:
            continue
        outcome = environment.evaluate(
            experiment=ExperimentAction(
                cell_id=cell.cell_id,
                genome_content=_genome_content_of(conn, cell.genome_hash),
                hypothesis=current.hypothesis,
            ),
            epoch=epoch,
        )
        if outcome.purchased and outcome.revenue_minor_units > 0:
            revenue.record_revenue(
                conn, cell_id=cell.cell_id, amount_minor_units=outcome.revenue_minor_units,
                source=f"{environment.name} sale", book=Book.USD_SIM,
                experiment_id=current.experiment_id,
                idempotency_key=f"sim:{run_id}:epoch:{epoch}:cell:{cell.cell_id}:sale",
            )
            sales += 1
            revenue_minor_units += outcome.revenue_minor_units
        experiments.conclude(
            conn, experiment_id=current.experiment_id, concluded_by=SIMULATION_DECIDER,
            note=outcome.note,
        )
        concluded += 1

    # A tuple is not an accepted `random.Random` seed type -- a stable string
    # is, and (unlike `hash()`) its seeding does not depend on
    # `PYTHONHASHSEED`, so this reproduces across separate processes.
    rng = random.Random(f"{master_seed}:selection:{epoch}")
    seed_label = f"seed={master_seed}:selection:epoch={epoch}"
    decision = selection.decide(conn, epoch=epoch, rng=rng, seed_label=seed_label)
    audit.record(
        conn, event_type="simulation_selection_decision", cell_id=None,
        description=decision.reason,
        metadata={"run_id": run_id, **asdict(decision)},
    )

    reproductions = 0
    for parent_id in decision.chosen_parent_cell_ids:
        parent = lifecycle.get_cell(conn, parent_id)
        if parent is None:
            continue
        parent_content = _genome_content_of(conn, parent.genome_hash)
        mutation_dict, operator_name = mutation.no_op(parent_content, seed=master_seed)
        reproduce_key = f"sim:{run_id}:epoch:{epoch}:reproduce:{parent_id}"
        try:
            child = lineage.reproduce(
                conn, parent_cell_id=parent_id,
                budget_minor_units=decision.child_budget_minor_units,
                idempotency_key=reproduce_key,
                mutation=mutation_dict, mutation_operator=operator_name,
            )
            # A child otherwise inherits no USD_REAL/RESOURCE balance of its
            # own (`lineage.reproduce` funds only the parent's own book, by
            # design -- funding cannot cross books) and would be born
            # permanently unschedulable without this, the same sliver every
            # founder gets.
            _fund_scheduler_eligibility(
                conn, cell_id=child.cell_id, key=reproduce_key,
                amount_minor_units=_FOUNDING_BUDGET_MINOR_UNITS,
            )
            reproductions += 1
        except (lineage.LineageError, population.PopulationError):
            # A refused reproduction is a fact the audit trail already has
            # (population/lineage caps, insufficient balance) -- not a run
            # failure, the same posture `autopromotion.sweep()` takes on a
            # per-grant `PromotionError`.
            pass

    for event in environment.advance(epoch=epoch):
        # A colony-wide happening the environment produced on its own clock
        # (SPEC.md §8.4's scheduled regime shifts), not one Cell's action --
        # recorded the same way `SelectionDecision` is, since neither
        # deserves a second, schema-level identity for a fact `audit`
        # already carries. Manifest-level regime-shift bookkeeping is F5's
        # addition (see `manifest.py`'s own docstring); this is what makes a
        # shift a real, queryable event now rather than inert Protocol
        # plumbing nothing ever calls.
        audit.record(
            conn, event_type="simulation_environment_event", cell_id=None,
            description=event.detail,
            metadata={
                "run_id": run_id, "epoch": epoch,
                "environment": environment.name, "kind": event.kind,
            },
        )

    living = sum(1 for c in lifecycle.list_cells(conn) if c.status is CellStatus.ALIVE)
    return EpochRecord(
        epoch=epoch, living_cells=living, experiments_started=started,
        experiments_concluded=concluded, sales=sales,
        revenue_minor_units=revenue_minor_units, reproductions=reproductions,
    )


def run(
    conn, config: RunConfig, *,
    suite: EnvironmentSuite | None = None,
    selection: SelectionPolicy | None = None,
) -> RunManifest:
    suite = suite or EnvironmentSuite.training_only(UtilityMaximizingMarket())
    selection = selection or RandomEligibleSelection()
    run_id = ids.new_id()
    started = datetime.now(timezone.utc)

    with ids.seeded(config.master_seed):
        # `validation`/`secret_challenge` are reset so a later slice can use
        # them without an "unreset" footgun -- but §8.1 means only `training`
        # is ever passed into the epoch loop below.
        for candidate in (suite.training, suite.validation, suite.secret_challenge):
            if candidate is not None:
                candidate.reset(seed=config.master_seed)
        _record_run_start(
            conn, run_id=run_id, config=config, environment=suite.training,
            selection=selection, started=started,
        )

        clock.initialize_if_absent(conn, mode=ClockMode.PAUSED)
        scheduler.configure_epochs_if_absent(conn)
        scheduler.initialize_operator_if_absent(conn)
        tools.set_autonomy(conn, flag="auto_promotion", enabled=True)
        promotion.fund_pool(
            conn, book=Book.USD_SIM, amount_minor_units=_POOL_FUNDING_MINOR_UNITS,
            funding_account=_SEED_ACCOUNT, idempotency_key=f"sim:{run_id}:pool",
        )

        _found_population(conn, config)
        real_spend_before = _real_external_spend(conn)
        policy = SimulationPolicyProvider(master_seed=config.master_seed)

        epoch_records: list[EpochRecord] = []
        failures: list[str] = []
        for epoch in range(config.epochs):
            try:
                epoch_records.append(
                    _run_one_epoch(
                        conn, epoch=epoch, run_id=run_id, policy=policy,
                        environment=suite.training, selection=selection,
                        master_seed=config.master_seed,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                # A drill/scenario failure belongs in the manifest, not a
                # crashed process (brief: "do not store only a final scalar
                # score" -- a run that stops recording its own failures at
                # the first one is the thing that instruction rules out).
                failures.append(f"epoch {epoch}: {exc}")
            clock.advance(conn, timedelta(seconds=clock.DEFAULT_EPOCH_DURATION_SECONDS))

        conservation = {
            book.value: ledger.verify_conservation(conn, book)
            for book in (Book.USD_REAL, Book.USD_SIM, Book.RESOURCE)
        }
        real_spend_after = _real_external_spend(conn)
        final_living = sum(1 for c in lifecycle.list_cells(conn) if c.status is CellStatus.ALIVE)

        manifest = RunManifest(
            run_id=run_id,
            scenario_name=config.scenario_name,
            master_seed=config.master_seed,
            code_version=_code_version(),
            environment_name=suite.training.name,
            environment_version=suite.training.version,
            policy_name=SIMULATION_PROVIDER,
            policy_version=POLICY_VERSION,
            population_target=config.population,
            epochs_target=config.epochs,
            epochs_completed=len(epoch_records),
            final_living_cells=final_living,
            conservation_ok=conservation,
            usd_real_spend_unchanged=(real_spend_after == real_spend_before),
            epochs=tuple(epoch_records),
            failures=tuple(failures),
        )
        if config.output_path:
            manifest.write(config.output_path)
        _record_run_finish(conn, run_id=run_id, manifest=manifest, output_path=config.output_path)
        return manifest
