"""Seed-paired comparison of two simulator arms (SPEC.md §28 Phase 3: "a
pre-registered effect with a confidence interval excluding zero"; ADR-084).

**The design.** `batch.py` runs every arm at every seed, so for a metric `m`
each seed `s` yields a pair `(m(baseline, s), m(treatment, s))`. The effect is
estimated from the per-seed differences `d_s = m(treatment, s) - m(baseline, s)`
— common random numbers — rather than from two independent samples.

**When pairing helps, stated as arithmetic rather than hoped for.**
`Var(d) = Var(a) + Var(b) - 2·Cov(a, b)`, so pairing narrows the interval
exactly when the two arms' outcomes are *positively correlated across seeds*
(the condition "When Does Pairing Seeds Reduce Variance?", arXiv 2512.24145,
proves for multi-agent economic simulators). It is not guaranteed here: an
arm's descendants are different Cells from the other arm's, and the
environment keys its draws by `cell_id`, so after the first reproduction the
two arms stop sharing randomness for any Cell but a founder. So every
comparison **reports the correlation and the variance ratio it actually got**,
alongside an unpaired interval over the same data — a pre-registration can
then declare the paired analysis honestly, having measured in a pilot whether
it buys anything at the scale it will run.

**Deliberately a percentile bootstrap, deliberately seeded.** No normality
assumption about a metric like "final living Cells", which is bounded by
carrying capacity; and a fixed resampling seed, so the same batch reports the
same interval every time it is read (§26's replay discipline, applied to the
analysis as well as the run).

**Refuses unpaired input.** A seed present in one arm and missing from the
other is an error, never silently dropped: a comparison that quietly used 7 of
8 pairs would report an interval for a design nobody pre-registered.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import batch


class PairedComparisonError(Exception):
    pass


def _epochs(manifest: dict) -> list[dict]:
    return list(manifest.get("epochs") or [])


def _revenue_per_concluded_experiment(epochs: list[dict]) -> float:
    """Revenue divided by experiments concluded — a *rate*, so an arm cannot
    raise it by reproducing more Cells (ADR-094): `total_revenue_minor_units`
    grows with headcount under any policy, and §9.2's
    `max_parallel_experiments` caps how many conclude per epoch anyway.
    Undefined, and refused rather than reported as zero, when nothing
    concluded — a zero would read as "sold nothing" about an arm that never
    tried."""
    concluded = sum(e["experiments_concluded"] for e in epochs)
    if concluded == 0:
        raise PairedComparisonError("no experiment concluded in the window this metric reads")
    return float(sum(e["revenue_minor_units"] for e in epochs)) / concluded


def _second_half(epochs: list[dict]) -> list[dict]:
    """The later half of a run, by position (`epochs[n // 2:]`), not by a
    regime-shift epoch — so a static-market arm and a shifting one are read
    over the same epochs, and the window a pre-registration names cannot move
    with a setting under comparison."""
    return epochs[len(epochs) // 2:]


def _final_mean_price(epochs: list[dict]) -> float:
    if not epochs:
        raise PairedComparisonError("a run with no completed epoch has no final price")
    return float(epochs[-1]["mean_price_minor_units"])


#: What a comparison may be computed over — each a function of one run
#: manifest, and each a canonical outcome the simulator itself recorded
#: (§0.3), never anything a Cell wrote. Named here rather than accepted as an
#: arbitrary expression, so a pre-registration names one of these and the
#: analysis cannot quietly compute something else under the same name.
METRICS: dict[str, Callable[[dict], float]] = {
    "final_living_cells": lambda m: float(m["final_living_cells"]),
    "total_revenue_minor_units": lambda m: float(sum(e["revenue_minor_units"] for e in _epochs(m))),
    "total_sales": lambda m: float(sum(e["sales"] for e in _epochs(m))),
    "total_reproductions": lambda m: float(sum(e["reproductions"] for e in _epochs(m))),
    "final_distinct_genomes": lambda m: float(_epochs(m)[-1]["distinct_genomes"]) if _epochs(m) else 0.0,
    "peak_founder_concentration": lambda m: max(
        (float(e["founder_concentration"]) for e in _epochs(m)), default=0.0
    ),
    # Slice H (ADR-094): trait and rate metrics, which headcount cannot move.
    "revenue_per_concluded_experiment": lambda m: _revenue_per_concluded_experiment(_epochs(m)),
    "second_half_revenue_per_concluded_experiment": lambda m: _revenue_per_concluded_experiment(
        _second_half(_epochs(m))
    ),
    "final_mean_price_minor_units": lambda m: _final_mean_price(_epochs(m)),
}

DEFAULT_RESAMPLES = 5_000
DEFAULT_CONFIDENCE = 0.95
DEFAULT_BOOTSTRAP_SEED = 0


@dataclass(frozen=True)
class PairedComparison:
    metric: str
    baseline: str
    treatment: str
    seeds: tuple[int, ...]
    baseline_values: tuple[float, ...]
    treatment_values: tuple[float, ...]
    mean_difference: float
    paired_ci: tuple[float, float]
    unpaired_ci: tuple[float, float]
    #: Pearson correlation of the two arms across seeds; `None` when either
    #: arm's values do not vary, where correlation is undefined.
    seed_correlation: float | None
    #: `Var(d) / (Var(a) + Var(b))`: below 1 means pairing narrowed the
    #: interval, above 1 means it widened it. `None` when neither arm varies.
    variance_ratio: float | None
    confidence: float
    resamples: int

    @property
    def paired_ci_excludes_zero(self) -> bool:
        low, high = self.paired_ci
        return low > 0 or high < 0

    def summary(self) -> str:
        corr = "undefined" if self.seed_correlation is None else f"{self.seed_correlation:+.3f}"
        ratio = "undefined" if self.variance_ratio is None else f"{self.variance_ratio:.3f}"
        pct = round(self.confidence * 100)
        return (
            f"{self.metric}: {self.treatment} - {self.baseline} over {len(self.seeds)} paired seed(s)\n"
            f"  mean difference      {self.mean_difference:+.4f}\n"
            f"  paired {pct}% CI       [{self.paired_ci[0]:+.4f}, {self.paired_ci[1]:+.4f}]"
            f"{'  (excludes 0)' if self.paired_ci_excludes_zero else ''}\n"
            f"  unpaired {pct}% CI     [{self.unpaired_ci[0]:+.4f}, {self.unpaired_ci[1]:+.4f}]\n"
            f"  seed correlation     {corr}\n"
            f"  variance ratio       {ratio}  (<1: pairing narrowed the interval)"
        )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


def _correlation(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2:
        return None
    mean_a, mean_b = _mean(a), _mean(b)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    denom = math.sqrt(sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b))
    return cov / denom if denom > 0 else None


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear interpolation between order statistics (the common "type 7")."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def compare_values(
    baseline: dict[int, float],
    treatment: dict[int, float],
    *,
    metric: str = "value",
    baseline_name: str = "baseline",
    treatment_name: str = "treatment",
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> PairedComparison:
    if set(baseline) != set(treatment):
        only_baseline = sorted(set(baseline) - set(treatment))
        only_treatment = sorted(set(treatment) - set(baseline))
        raise PairedComparisonError(
            f"seeds are not paired: only in {baseline_name}: {only_baseline}; "
            f"only in {treatment_name}: {only_treatment}"
        )
    if not baseline:
        raise PairedComparisonError("no seeds to compare")
    if not 0 < confidence < 1:
        raise PairedComparisonError("confidence must be strictly between 0 and 1")
    if resamples < 1:
        raise PairedComparisonError("resamples must be at least 1")

    seeds = sorted(baseline)
    a = [float(baseline[s]) for s in seeds]
    b = [float(treatment[s]) for s in seeds]
    d = [y - x for x, y in zip(a, b)]
    n = len(seeds)

    rng = random.Random(f"paired:{bootstrap_seed}")
    paired_means = []
    unpaired_means = []
    for _ in range(resamples):
        paired_means.append(_mean([d[rng.randrange(n)] for _ in range(n)]))
        unpaired_means.append(
            _mean([b[rng.randrange(n)] for _ in range(n)]) - _mean([a[rng.randrange(n)] for _ in range(n)])
        )
    paired_means.sort()
    unpaired_means.sort()
    tail = (1 - confidence) / 2

    var_sum = _variance(a) + _variance(b)
    return PairedComparison(
        metric=metric,
        baseline=baseline_name,
        treatment=treatment_name,
        seeds=tuple(seeds),
        baseline_values=tuple(a),
        treatment_values=tuple(b),
        mean_difference=_mean(d),
        paired_ci=(_percentile(paired_means, tail), _percentile(paired_means, 1 - tail)),
        unpaired_ci=(_percentile(unpaired_means, tail), _percentile(unpaired_means, 1 - tail)),
        seed_correlation=_correlation(a, b),
        variance_ratio=_variance(d) / var_sum if var_sum > 0 else None,
        confidence=confidence,
        resamples=resamples,
    )


def load_arm(out_dir: Path, arm: str, metric: str) -> dict[int, float]:
    """Metric values for one arm, by seed, read through the batch index — never
    by globbing, so only runs the batch itself recorded are counted."""
    if metric not in METRICS:
        raise PairedComparisonError(
            f"unknown metric {metric!r}; available: {', '.join(sorted(METRICS))}"
        )
    index_path = out_dir / batch.INDEX_FILENAME
    if not index_path.exists():
        raise PairedComparisonError(f"no {batch.INDEX_FILENAME} in {out_dir} — run `simulate-batch` first")
    index = json.loads(index_path.read_text())
    values: dict[int, float] = {}
    for run in index["runs"]:
        if run["arm"] != arm:
            continue
        manifest = json.loads((out_dir / run["manifest_path"]).read_text())
        if manifest["failures"]:
            # A failed run's metric is not the arm's outcome at that seed, and
            # dropping only that seed would unpair the design — so refuse.
            raise PairedComparisonError(
                f"{arm} at seed {run['seed']} recorded {len(manifest['failures'])} failure(s); "
                "a comparison over a failed run is not the comparison that was planned"
            )
        try:
            values[int(run["seed"])] = METRICS[metric](manifest)
        except PairedComparisonError as exc:
            raise PairedComparisonError(f"{metric} for {arm} at seed {run['seed']}: {exc}") from None
        except KeyError as exc:
            # A manifest written before the field this metric reads existed.
            raise PairedComparisonError(
                f"{metric} for {arm} at seed {run['seed']}: the manifest has no {exc.args[0]!r} "
                "field — it predates this metric, so rerun the batch"
            ) from None
    if not values:
        raise PairedComparisonError(f"arm {arm!r} is not in this batch; arms: {index['arms']}")
    return values


def compare_batch(
    out_dir: Path, *, baseline: str, treatment: str, metric: str,
    resamples: int = DEFAULT_RESAMPLES, confidence: float = DEFAULT_CONFIDENCE,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> PairedComparison:
    return compare_values(
        load_arm(out_dir, baseline, metric),
        load_arm(out_dir, treatment, metric),
        metric=metric, baseline_name=baseline, treatment_name=treatment,
        resamples=resamples, confidence=confidence, bootstrap_seed=bootstrap_seed,
    )
