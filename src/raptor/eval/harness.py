"""PRD-06 sec 10.3 `harness.py` — `run_eval` (FR1-FR10 orchestration).

The end-to-end entry point: benchmark -> split -> combine (held-out only)
-> metrics -> gate -> oracle-blind checks -> report. **Labels flow ONLY
through `build_benchmark`** (FR8/AC6/H1): once the held-out rows are known,
the harness talks to `evidence_source.get_evidence(variant_id)` by plain
`str` variant_id ONLY -- never a label, never a `LabeledVariant` -- so the
evidence/scoring path structurally cannot see a label.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Iterable, Protocol

from .benchmark import build_benchmark
from .checks import oracle_blind_checks
from .combine import implied_direction
from .config import EvalConfig
from .gate import decide_gate
from .metrics import compute_metrics
from .model import ImpliedCall, LabeledVariant
from .report import EvalReport
from .split import split_benchmark

#: Fallback when the `raptor` package is not installed with metadata (e.g. a
#: pure source checkout) -- so `code_version` is still always populated,
#: never blank (FR9/MINOR provenance fix).
_FALLBACK_CODE_VERSION = "unknown"


def _code_version() -> str:
    try:
        return version("raptor")
    except PackageNotFoundError:
        return _FALLBACK_CODE_VERSION


class EvidenceSource(Protocol):
    def get_evidence(self, variant_id: str): ...


def run_eval(config: EvalConfig, labeled: Iterable[LabeledVariant], evidence_source: EvidenceSource) -> EvalReport:
    """Run the full PRD-06 eval pipeline (FR1-FR10).

    Labels (`labeled`) are consumed ONLY by `build_benchmark`. From that
    point on, only `variant_id` strings flow to `evidence_source` -- proven
    by `tests/eval/test_ac6_ac7_ac9_harness.py::test_ac6_labels_never_reach_evidence_source`.
    Any contract breach (e.g. a malformed config) raises through, never
    swallowed (fail-loud).
    """
    benchmark = build_benchmark(labeled, config)
    train_dev, holdout = split_benchmark(benchmark, config)

    evidence_by_id: dict[str, list] = {}
    implied_calls: list[ImpliedCall] = []
    for row in holdout:
        variant_id: str = row.variant_id  # plain str -- never the LabeledVariant/label (FR8/AC6)
        calls = list(evidence_source.get_evidence(variant_id))
        evidence_by_id[variant_id] = calls
        call = implied_direction(calls, config)
        implied_calls.append(ImpliedCall(variant_id=variant_id, implied=call.implied, points=call.points))

    metrics = compute_metrics(implied_calls, holdout, config)
    gate = decide_gate(metrics, config)
    findings = oracle_blind_checks(evidence_by_id)

    holdout_label_counts: dict[str, int] = {}
    holdout_class_counts: dict[str, int] = {}
    for row in holdout:
        holdout_label_counts[row.label] = holdout_label_counts.get(row.label, 0) + 1
        holdout_class_counts[row.variant_class] = holdout_class_counts.get(row.variant_class, 0) + 1

    return EvalReport(
        run_id=str(uuid.uuid4()),
        generated_at=datetime.now(timezone.utc).isoformat(),
        labels_snapshot=config.labels_snapshot,
        benchmark_size=len(benchmark),
        train_dev_size=len(train_dev),
        holdout_size=len(holdout),
        holdout_label_counts=holdout_label_counts,
        holdout_class_counts=holdout_class_counts,
        metrics=metrics,
        gate=gate,
        oracle_blind_findings=findings,
        code_version=_code_version(),
        config_pins={
            "split_seed": config.split["seed"],
            "min_count_per_class": config.min_count_per_class,
            "tavtigian_cutoffs": dict(sorted(config.tavtigian_cutoffs.items())),
            "automatable_criteria": sorted(config.automatable_criteria),
            "tavtigian_points": dict(sorted(config.tavtigian_points.items())),
            "holdout_fraction": config.split["holdout_fraction"],
            "oracle_thresholds": dict(sorted(config.oracle_thresholds.items())),
        },
    )
