"""Deterministic, non-gating orthogonal rank-correlation + power metrics.

`compute_orthogonal_metrics` compares a RAPTOR-side score/proxy against a
MAVE functional score across a set of `OrthogonalObservation`s. It sorts by
`variant_id` internally, so
`compute_orthogonal_metrics(rows, ...) == compute_orthogonal_metrics(list(reversed(rows)), ...)`
always holds (determinism regardless of input order). It never gates
anything -- `validation_mode` is always `"NON_GATING"`, and small-`n`
classes are explicitly flagged `UNDERPOWERED` rather than silently reported
as if they were adequately powered.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from ._stats import bootstrap_ci, spearman_kendall
from .endpoint import FunctionalClass, classify_functional_score
from .partition import PartitionKind

#: Below this per-class count, a class's concordance is descriptive-only
#: (UNDERPOWERED), mirroring the eval harness's `min_count_per_class`
#: pattern (`configs/eval/tsc2.yaml`) but sized for the much smaller MAVE
#: overlap cohorts (`configs/eval/mave_tsc2.yaml: min_class_n`). Never
#: gating regardless of status.
MIN_CLASS_N = 10


class OrthogonalObservation(NamedTuple):
    variant_id: str
    raptor_score: float
    mave_score: float
    partition: "PartitionKind"


@dataclass(frozen=True)
class CorrelationResult:
    n: int
    statistic: float
    bootstrap_ci: tuple[float, float]


@dataclass(frozen=True)
class ClassPowerResult:
    n: int
    status: str
    gating: str


@dataclass(frozen=True)
class OrthogonalMetricsResult:
    validation_mode: str
    spearman: CorrelationResult
    kendall: CorrelationResult
    agreement_matrix: dict
    class_power: dict


def compute_orthogonal_metrics(
    rows,
    *,
    bootstrap_resamples: int,
    random_seed: int,
) -> OrthogonalMetricsResult:
    """Compute deterministic, non-gating rank-correlation + class-power
    metrics for a set of `OrthogonalObservation`s. Sorted by `variant_id`
    before any statistic is computed, so the result never depends on the
    caller's row order."""
    ordered = sorted(rows, key=lambda row: row.variant_id)
    raptor_scores = [row.raptor_score for row in ordered]
    mave_scores = [row.mave_score for row in ordered]

    spearman_stat, kendall_stat = spearman_kendall(raptor_scores, mave_scores)
    spearman_ci = bootstrap_ci(
        raptor_scores,
        mave_scores,
        lambda xs, ys: spearman_kendall(xs, ys)[0],
        resamples=bootstrap_resamples,
        seed=random_seed,
    )
    kendall_ci = bootstrap_ci(
        raptor_scores,
        mave_scores,
        lambda xs, ys: spearman_kendall(xs, ys)[1],
        resamples=bootstrap_resamples,
        seed=random_seed + 1,
    )

    raptor_classes = [classify_functional_score(row.raptor_score) for row in ordered]
    mave_classes = [classify_functional_score(row.mave_score) for row in ordered]

    agreement_matrix = {
        row_class.value: {
            col_class.value: sum(
                1
                for r_class, m_class in zip(raptor_classes, mave_classes)
                if r_class is row_class and m_class is col_class
            )
            for col_class in FunctionalClass
        }
        for row_class in FunctionalClass
    }

    class_power = {}
    for functional_class in FunctionalClass:
        n = sum(1 for m_class in mave_classes if m_class is functional_class)
        status = "UNDERPOWERED" if n < MIN_CLASS_N else "OK"
        class_power[functional_class] = ClassPowerResult(n=n, status=status, gating="NON_GATING")

    return OrthogonalMetricsResult(
        validation_mode="NON_GATING",
        spearman=CorrelationResult(n=len(ordered), statistic=spearman_stat, bootstrap_ci=spearman_ci),
        kendall=CorrelationResult(n=len(ordered), statistic=kendall_stat, bootstrap_ci=kendall_ci),
        agreement_matrix=agreement_matrix,
        class_power=class_power,
    )


__all__ = [
    "MIN_CLASS_N",
    "OrthogonalObservation",
    "CorrelationResult",
    "ClassPowerResult",
    "OrthogonalMetricsResult",
    "compute_orthogonal_metrics",
]
