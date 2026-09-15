"""Many flight-simulator runs at once: every (arm, seed) pair in its own
process with its own in-memory colony (SPEC.md §7.1's "large batch
experiments", §28 Phase 3's pre-registered comparisons; ADR-084).

**Why processes, and why not model agents.** A simulator run is deterministic,
CPU-bound Python against mock Cells (§7.3) — there is no model call for an
agent swarm to parallelise, and one interpreter runs one run at a time. The
comparisons §28 Phase 3 names are *embarrassingly* parallel: two arms share
nothing but their configuration, so the only honest speed-up is more
interpreters.

**Why an in-memory database per run.** Measured, not assumed: the same
30-founder, 40-epoch run took 9.1s against `:memory:` and 17.6s against a
file-backed WAL database, the difference almost entirely system CPU (5.3s vs
0.03s) — commit durability the kernel needs for a *real* colony and a
throwaway comparison run does not. The retained artifact of a batch run is its
manifest (brief Slice F: "a separately documented benchmark command whose
result artifact is retained"), never its database, so nothing a batch run
produces is lost by not writing one. This changes no kernel pragma: a real
colony still opens through `db.connect` exactly as before.

**Pairing is structural, not a convention.** Every arm is run at *every* seed
in the batch, so `paired.py` can compare arms seed by seed (common random
numbers). What makes that pairing mean something is that no selection policy
can shift another component's randomness — every draw in this package is
seeded from its own `(master_seed, purpose, ...)` label rather than from one
shared stream, which `tests/test_simulation_batch.py` checks by running a
policy that deliberately burns the stream it is given, the global `random`
module, and the seeded id generator.
"""

from __future__ import annotations

import json
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import db
from . import environment as simulation_environment
from . import runner
from . import selection_policy as simulation_selection_policy

#: The batch index every `paired.py` comparison reads — named rather than
#: globbed, so a stray manifest dropped in the same directory is not silently
#: counted as an arm.
INDEX_FILENAME = "batch.json"


class BatchError(Exception):
    pass


def build_selection(
    arm: str, *, environment_name: str, validation_environment: str | None
) -> simulation_selection_policy.SelectionPolicy:
    """One selection policy by name, with `StagedFundingSelection`'s validation
    environment defaulting to the *other* market family (§8.1/§8.3's
    cross-family check) — the rule `cmd_simulate` has applied since ADR-082,
    moved here so a batch arm and a single run cannot disagree about it."""
    kwargs: dict = {}
    if arm == simulation_selection_policy.StagedFundingSelection.name:
        other_family = (
            simulation_environment.RuleBasedMarket.name
            if environment_name == simulation_environment.UtilityMaximizingMarket.name
            else simulation_environment.UtilityMaximizingMarket.name
        )
        kwargs["validation"] = simulation_environment.build_environment(
            validation_environment or other_family
        )
    return simulation_selection_policy.build_selection_policy(arm, **kwargs)


@dataclass(frozen=True)
class BatchJob:
    arm: str
    seed: int
    epochs: int
    population: int
    scenario: str
    environment: str
    validation_environment: str | None
    output_path: str
    #: Read once by `plan`, in the parent. `None` lets `runner.run` read it
    #: itself, which a worker under load can time out on and record "unknown".
    code_version: str | None = None


@dataclass(frozen=True)
class BatchResult:
    arm: str
    seed: int
    manifest_path: str
    wall_seconds: float
    failures: int


def manifest_filename(arm: str, seed: int) -> str:
    return f"{arm}__seed{seed}.json"


def run_job(job: BatchJob) -> BatchResult:
    """One run in a fresh in-memory colony. Module-level so a spawned worker
    process can import it; the colony never outlives this call."""
    conn = db.connect_and_migrate(":memory:")
    started = time.perf_counter()
    try:
        manifest = runner.run(
            conn,
            runner.RunConfig(
                scenario_name=job.scenario, master_seed=job.seed,
                epochs=job.epochs, population=job.population, output_path=job.output_path,
            ),
            suite=simulation_environment.EnvironmentSuite.training_only(
                simulation_environment.build_environment(job.environment)
            ),
            selection=build_selection(
                job.arm, environment_name=job.environment,
                validation_environment=job.validation_environment,
            ),
            code_version=job.code_version,
        )
    finally:
        conn.close()
    return BatchResult(
        arm=job.arm, seed=job.seed, manifest_path=job.output_path,
        wall_seconds=round(time.perf_counter() - started, 3),
        failures=len(manifest.failures),
    )


def plan(
    *, arms: list[str], seeds: list[int], epochs: int, population: int, scenario: str,
    environment: str, validation_environment: str | None, out_dir: Path,
) -> list[BatchJob]:
    """Every arm at every seed. Refuses a repeated arm or seed rather than
    de-duplicating it: a batch that silently ran one arm twice would report a
    comparison of an arm against itself under two names."""
    if not arms or not seeds:
        raise BatchError("a batch needs at least one arm and one seed")
    if len(set(arms)) != len(arms):
        raise BatchError(f"arm named twice: {arms}")
    if len(set(seeds)) != len(seeds):
        raise BatchError(f"seed named twice: {seeds}")
    for arm in arms:
        # An unknown name fails here, before any process starts, rather than
        # inside a worker after the other arms have already spent their time.
        simulation_selection_policy.build_selection_policy(arm)
    # Once for the whole batch: every run names the same code, and no worker
    # starts a `git` of its own — one that timed out under load would record
    # "unknown" in one manifest of a pair and the pair would stop comparing.
    code_version = runner._code_version()
    return [
        BatchJob(
            arm=arm, seed=seed, epochs=epochs, population=population, scenario=scenario,
            environment=environment, validation_environment=validation_environment,
            output_path=str(out_dir / manifest_filename(arm, seed)), code_version=code_version,
        )
        for arm in arms
        for seed in seeds
    ]


def run_batch(jobs: list[BatchJob], *, out_dir: Path, workers: int) -> list[BatchResult]:
    """Run every job, `workers` at a time, and write the batch index.

    `spawn`, not `fork`: a forked worker inherits whatever the parent process
    already imported and opened, and a comparison whose arms ran in differently
    initialised interpreters is not the clean pairing it claims to be. With
    `workers == 1` the jobs run in this process, in order — the same results,
    useful where a subprocess cannot start.
    """
    if workers < 1:
        raise BatchError("workers must be at least 1")
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    if workers == 1:
        results = [run_job(job) for job in jobs]
    else:
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")
        ) as pool:
            results = list(pool.map(run_job, jobs))
    first = jobs[0] if jobs else None
    index = {
        "arms": sorted({job.arm for job in jobs}),
        "seeds": sorted({job.seed for job in jobs}),
        "epochs": first.epochs if first else None,
        "population": first.population if first else None,
        "scenario": first.scenario if first else None,
        "environment": first.environment if first else None,
        "validation_environment": first.validation_environment if first else None,
        "workers": workers,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "runs": [
            {**asdict(result), "manifest_path": Path(result.manifest_path).name}
            for result in results
        ],
    }
    (out_dir / INDEX_FILENAME).write_text(json.dumps(index, indent=2, sort_keys=True))
    return results
