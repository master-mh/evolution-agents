"""The machine-readable run manifest (implementation brief Slice F's "CLI and
artifacts": "Record configuration hashes, code version, seeds, environment
versions, policy version, invariant results, population/diversity time
series, regime-shift recovery, and all failures. Do not store only a final
scalar score.")

F1 shipped the skeleton and the invariant/config fields; F5 (this file's
current shape) adds the rest, now that F2-F4 give diversity, regime shifts,
and mutation something real to measure:

- `EpochRecord.distinct_genomes` -- the diversity time series. Counted as
  distinct `genome_hash` values among currently-living Cells, because a
  genome hash *is* a Cell's full strategy under ADR-018's content
  addressing: counting distinct hashes counts distinct strategies, not an
  ad hoc proxy for "diversity."
- `EpochRecord.environment_events` -- regime-shift recovery, made visible
  the same way population/diversity already are: a reader sees which epoch
  carried a shift and can read the *following* epochs' own `living_cells`/
  `sales`/`distinct_genomes` to see recovery, rather than the manifest
  declaring a computed "recovered" verdict on the colony's behalf.
- `RunManifest.config_hash` -- SHA-256 over the run's own configuration
  (scenario, seed, epochs, population; not `output_path`, a local write
  destination rather than configuration), so two manifests claiming the same
  configuration can be checked, not just asserted.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class EpochRecord:
    epoch: int
    living_cells: int
    experiments_started: int
    experiments_concluded: int
    sales: int
    revenue_minor_units: int
    reproductions: int
    distinct_genomes: int
    environment_events: tuple[str, ...]


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    scenario_name: str
    master_seed: int
    code_version: str
    config_hash: str
    environment_name: str
    environment_version: str
    policy_name: str
    policy_version: str
    population_target: int
    epochs_target: int
    epochs_completed: int
    final_living_cells: int
    conservation_ok: dict[str, bool]
    usd_real_spend_unchanged: bool
    epochs: tuple[EpochRecord, ...] = ()
    failures: tuple[str, ...] = ()

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    def write(self, path: str) -> None:
        Path(path).write_text(self.to_json())

    def summary(self) -> str:
        conservation = "OK" if all(self.conservation_ok.values()) else "FAILED"
        real = "unchanged" if self.usd_real_spend_unchanged else "MOVED"
        failure_note = f", {len(self.failures)} failure(s)" if self.failures else ""
        return (
            f"run {self.run_id} ({self.scenario_name}, seed {self.master_seed}): "
            f"{self.epochs_completed}/{self.epochs_target} epoch(s), "
            f"{self.final_living_cells} living Cell(s), "
            f"conservation={conservation}, USD_REAL {real}{failure_note}"
        )
