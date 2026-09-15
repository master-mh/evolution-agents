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
import re
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
    arm: str, *, environment_name: str, validation_environment: str | None,
    static_market: bool = False,
) -> simulation_selection_policy.SelectionPolicy:
    """One selection policy by name, with `StagedFundingSelection`'s validation
    environment defaulting to the *other* market family (§8.1/§8.3's
    cross-family check) — the rule `cmd_simulate` has applied since ADR-082,
    moved here so a batch arm and a single run cannot disagree about it. A
    static-market arm validates against a static market too: an arm whose
    training market never shifts but whose validation market does would be
    testing two regimes at once under one name."""
    kwargs: dict = {}
    if arm == simulation_selection_policy.StagedFundingSelection.name:
        other_family = (
            simulation_environment.RuleBasedMarket.name
            if environment_name == simulation_environment.UtilityMaximizingMarket.name
            else simulation_environment.UtilityMaximizingMarket.name
        )
        kwargs["validation"] = simulation_environment.build_environment(
            validation_environment or other_family, static=static_market,
        )
    return simulation_selection_policy.build_selection_policy(arm, **kwargs)


#: An arm's label becomes a manifest filename and a `simulate-compare` name.
_LABEL_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")
_STATIC_MARKET_OPTION = "static_market"
_LINEAGE_CAP_OPTION = "lineage_cap"


@dataclass(frozen=True)
class ArmSpec:
    """One arm of a batch: a selection policy plus the two §28 Phase 3 settings
    that are not a policy (ADR-094) — whether the market shifts, and the
    lineage cap. The `label` is what the batch index, the manifest filename
    and `simulate-compare` call it."""

    label: str
    selection: str
    static_market: bool = False
    lineage_cap: float | None = None

    def settings(self) -> tuple:
        return (self.selection, self.static_market, self.lineage_cap)


def parse_arm(text: str) -> ArmSpec:
    """`POLICY` — the policy under its own name, market and cap as default — or
    `LABEL=POLICY` followed by any of `+static_market` and `+lineage_cap=F`.

    An arm with options must be given a label of its own: `map_elites` in a
    batch always means plain `map_elites`, so no reader of a manifest named
    after a policy has to wonder which market it ran against."""
    head, *options = [part.strip() for part in text.split("+")]
    label, has_label, selection = head.partition("=")
    if not has_label:
        label = selection = head
    label, selection = label.strip(), selection.strip()
    if not label or not selection:
        raise BatchError(f"arm {text!r} names no policy")
    if not _LABEL_PATTERN.fullmatch(label):
        raise BatchError(f"arm label {label!r} may use only letters, digits, '_', '.' and '-'")
    if options and not has_label:
        raise BatchError(
            f"arm {text!r} changes a setting, so it needs a label of its own "
            f"(e.g. {selection}_variant={text})"
        )
    static_market = False
    lineage_cap: float | None = None
    seen: set[str] = set()
    for option in options:
        key, has_value, value = option.partition("=")
        if key in seen:
            raise BatchError(f"arm {text!r} sets {key} twice")
        seen.add(key)
        if key == _STATIC_MARKET_OPTION and not has_value:
            static_market = True
        elif key == _LINEAGE_CAP_OPTION and has_value:
            try:
                lineage_cap = float(value)
            except ValueError:
                raise BatchError(f"arm {text!r}: lineage_cap {value!r} is not a number") from None
            if not 0 < lineage_cap <= 1:
                raise BatchError(f"arm {text!r}: lineage_cap must be in (0, 1], not {lineage_cap}")
        else:
            raise BatchError(
                f"arm {text!r}: unknown option {option!r}; available: "
                f"+{_STATIC_MARKET_OPTION}, +{_LINEAGE_CAP_OPTION}=F"
            )
    return ArmSpec(label=label, selection=selection, static_market=static_market, lineage_cap=lineage_cap)


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
    #: The policy this arm runs; `arm` is only its label. `None` means the
    #: label is the policy, as for every batch before ADR-094.
    selection: str | None = None
    static_market: bool = False
    lineage_cap: float | None = None


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
                lineage_cap=job.lineage_cap,
            ),
            suite=simulation_environment.EnvironmentSuite.training_only(
                simulation_environment.build_environment(job.environment, static=job.static_market)
            ),
            selection=build_selection(
                job.selection or job.arm, environment_name=job.environment,
                validation_environment=job.validation_environment,
                static_market=job.static_market,
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
    """Every arm (`parse_arm`'s grammar) at every seed. Refuses a repeated arm
    or seed rather than de-duplicating it: a batch that silently ran one arm
    twice would report a comparison of an arm against itself under two names —
    which is also why two labels for identical settings are refused."""
    if not arms or not seeds:
        raise BatchError("a batch needs at least one arm and one seed")
    specs = [parse_arm(arm) for arm in arms]
    labels = [spec.label for spec in specs]
    if len(set(labels)) != len(labels):
        raise BatchError(f"arm named twice: {labels}")
    by_settings: dict[tuple, str] = {}
    for spec in specs:
        if spec.settings() in by_settings:
            raise BatchError(
                f"arms {by_settings[spec.settings()]!r} and {spec.label!r} have identical settings; "
                "comparing them would compare an arm with itself"
            )
        by_settings[spec.settings()] = spec.label
    if len(set(seeds)) != len(seeds):
        raise BatchError(f"seed named twice: {seeds}")
    for spec in specs:
        # An unknown name fails here, before any process starts, rather than
        # inside a worker after the other arms have already spent their time.
        simulation_selection_policy.build_selection_policy(spec.selection)
    # Once for the whole batch: every run names the same code, and no worker
    # starts a `git` of its own — one that timed out under load would record
    # "unknown" in one manifest of a pair and the pair would stop comparing.
    code_version = runner._code_version()
    return [
        BatchJob(
            arm=spec.label, seed=seed, epochs=epochs, population=population, scenario=scenario,
            environment=environment, validation_environment=validation_environment,
            output_path=str(out_dir / manifest_filename(spec.label, seed)), code_version=code_version,
            selection=spec.selection, static_market=spec.static_market, lineage_cap=spec.lineage_cap,
        )
        for spec in specs
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
        # What each label ran, so a comparison's reader never has to trust that
        # a label like `uncapped` means what it says (ADR-094).
        "arm_settings": {
            job.arm: {
                "selection": job.selection or job.arm,
                "static_market": job.static_market,
                "lineage_cap": job.lineage_cap,
            }
            for job in jobs
        },
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
