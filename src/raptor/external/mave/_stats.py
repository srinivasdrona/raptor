"""Internal, deterministic rank-correlation + bootstrap-CI helpers shared by
`endpoint.LabelBlindReport` (via `report.py`) and `orthogonal_metrics.py`.

Not part of the public `raptor.external.mave` contract exercised directly by
tests -- a private helper so the two correlation call-sites (label-blind
report, orthogonal-metrics module) share one seeded-bootstrap implementation
rather than drifting.
"""
from __future__ import annotations

import random
from typing import Callable, Sequence

from scipy.stats import kendalltau, spearmanr


def spearman_kendall(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """Return `(spearman_statistic, kendall_statistic)` for paired samples."""
    spearman_result = spearmanr(xs, ys)
    kendall_result = kendalltau(xs, ys)
    return float(spearman_result.statistic), float(kendall_result.statistic)


def bootstrap_ci(
    xs: Sequence[float],
    ys: Sequence[float],
    statistic: Callable[[Sequence[float], Sequence[float]], float],
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    """Percentile bootstrap CI for `statistic(xs, ys)`, resampling pairs
    (index resampling, with replacement) `resamples` times from a `seed`-ed
    `random.Random` -- deterministic given the same (sorted) input and seed,
    independent of the caller's original row order."""
    n = len(xs)
    if n < 2:
        return (float("nan"), float("nan"))

    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(resamples):
        indices = [rng.randrange(n) for _ in range(n)]
        sample_x = [xs[i] for i in indices]
        sample_y = [ys[i] for i in indices]
        values.append(statistic(sample_x, sample_y))

    values.sort()
    lo_index = max(0, min(len(values) - 1, round(0.025 * (len(values) - 1))))
    hi_index = max(0, min(len(values) - 1, round(0.975 * (len(values) - 1))))
    return (values[lo_index], values[hi_index])


__all__ = ["spearman_kendall", "bootstrap_ci"]
