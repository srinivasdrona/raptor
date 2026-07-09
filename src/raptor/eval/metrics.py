"""PRD-06 sec 10.3 `metrics.py` — class-stratified metrics (FR4/FR5).

Joins `ImpliedCall`s to `BenchmarkRow`s by `variant_id` (identity join,
matching PRD-03's identity discipline), computes precision/recall/
concordance per stratum -- `overall` plus one per `variant_class` present
(missense REPORTED SEPARATELY per R-A2c) -- with `no_call` excluded from the
P/R denominators and counted as `abstain`. A stratum whose per-truth-class
held-out counts fall below `config.min_count_per_class` is tagged
`gating=False` (FR5): descriptive/CI only, never a gate input.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from .config import EvalConfig
from .model import BenchmarkRow, ImpliedCall, Metrics

_PATHOGENIC_LABELS = frozenset({"P", "LP"})
_BENIGN_LABELS = frozenset({"B", "LB"})


def _compute_stratum(
    stratum: str, rows: List[BenchmarkRow], implied_by_id: Dict[str, ImpliedCall], config: EvalConfig
) -> Metrics:
    tp = fp = tn = fn = abstain = 0
    path_actual = benign_actual = 0

    for row in rows:
        is_path_truth = row.label in _PATHOGENIC_LABELS
        is_benign_truth = row.label in _BENIGN_LABELS
        if is_path_truth:
            path_actual += 1
        if is_benign_truth:
            benign_actual += 1

        call = implied_by_id.get(row.variant_id)
        implied = call.implied if call is not None else "no_call"

        if implied == "no_call":
            abstain += 1
        elif implied == "LP":
            if is_path_truth:
                tp += 1
            elif is_benign_truth:
                fp += 1
        elif implied == "LB":
            if is_benign_truth:
                tn += 1
            elif is_path_truth:
                fn += 1

    total_called = tp + fp + tn + fn
    concordance = (tp + tn) / total_called if total_called else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    # BLOCKER-1: the benign-direction mirror of precision/recall (FR4) --
    # tn/(tn+fn) and tn/(tn+fp) (specificity). Without these, a model that
    # calls everything pathogenic looks perfect on the pathogenic side while
    # being wrong on 100% of the benign truth class.
    benign_precision = tn / (tn + fn) if (tn + fn) else 0.0
    benign_recall = tn / (tn + fp) if (tn + fp) else 0.0

    # BLOCKER-1 (abstain-laundering): a stratum where the model CALLED
    # (LP/LB, never abstained) an adequate count of BOTH truth classes --
    # not merely HAD an adequate count of held-out truth rows. Abstaining
    # on an entire truth class shows perfect precision/recall on the other
    # class while demonstrating zero discrimination on the abstained class;
    # such a stratum must never be gating.
    path_called = tp + fn
    benign_called = tn + fp
    gating = (
        min(path_actual, benign_actual) >= config.min_count_per_class
        and min(path_called, benign_called) >= config.min_count_per_class
    )

    counts = {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "abstain": abstain,
        "total_called": total_called,
        "total": len(rows),
        "path_actual": path_actual,
        "benign_actual": benign_actual,
        "path_called": path_called,
        "benign_called": benign_called,
    }

    return Metrics(
        precision=precision,
        recall=recall,
        concordance=concordance,
        counts=counts,
        stratum=stratum,
        gating=gating,
        benign_precision=benign_precision,
        benign_recall=benign_recall,
    )


def compute_metrics(
    implied: Iterable[ImpliedCall], benchmark: Iterable[BenchmarkRow], config: EvalConfig
) -> Dict[str, Metrics]:
    """Compute stratified metrics (FR4) keyed by stratum name: `overall`
    plus each `variant_class` present in `benchmark` (`missense`,
    `truncating`, `other`, ...)."""
    implied_by_id = {c.variant_id: c for c in implied}

    strata: Dict[str, List[BenchmarkRow]] = defaultdict(list)
    for row in benchmark:
        strata["overall"].append(row)
        strata[row.variant_class].append(row)

    return {
        stratum: _compute_stratum(stratum, rows, implied_by_id, config)
        for stratum, rows in strata.items()
    }
