"""PRD-06 sec 10.3 `benchmark.py` — the benchmark builder (FR1).

This is the ONLY place a label enters the eval harness (FR8/AC6/H1): reads
`LabeledVariant` rows, applies the exclusions (conflicting, single-submitter,
any label RAPTOR influenced -- R-A2 circularity) and the label-source
hierarchy (EVAL_PLAN sec 2 -- when the same variant identity appears more
than once, the highest-ranked source wins), and freezes the result as
`BenchmarkRow`s. Nothing downstream of this module ever sees a
`LabeledVariant` or a raw label file.
"""
from __future__ import annotations

from typing import Iterable, List

from .config import EvalConfig
from .model import BenchmarkRow, LabeledVariant

#: Label-source hierarchy, highest confidence first (EVAL_PLAN sec 2). Used
#: only to resolve a variant identity that appears more than once in the
#: labels source -- never to change the label value itself.
_SOURCE_RANK: dict[str, int] = {
    "clingen_vcep": 0,
    "clingen_3star": 0,
    "clinvar_2star_concordant": 1,
    "clinvar": 2,
    "curated_literature": 3,
    "oracle_adjudication": 4,
}


#: Labels the metrics pipeline can score (FR1/R-A2): anything else (VUS,
#: not_provided, etc.) is unmappable and must be excluded, never silently
#: mis-counted.
_SCOREABLE_LABELS: frozenset[str] = frozenset({"P", "LP", "LB", "B"})


def _source_rank(source: str) -> int:
    return _SOURCE_RANK.get(source, len(_SOURCE_RANK))


def _excluded(variant: LabeledVariant) -> bool:
    if variant.label == "Conflicting":
        return True
    if variant.submitter_count < 2:
        return True
    if variant.raptor_influenced:
        return True
    if "conflicting" in (variant.review_status or "").lower():
        return True
    if "single submitter" in (variant.review_status or "").lower():
        # A ClinVar 1-star "criteria provided, single submitter" label is low-confidence
        # and excluded even when NumberSubmitters>1 (extra no-criteria submissions can
        # inflate the count while the germline review stays single-submitter).
        return True
    if variant.label not in _SCOREABLE_LABELS:
        return True
    return False


def build_benchmark(labeled: Iterable[LabeledVariant], config: EvalConfig) -> List[BenchmarkRow]:
    """Build the frozen benchmark set (FR1): exclude conflicting,
    single-submitter, and RAPTOR-influenced labels; where the same
    `variant_id` recurs, keep the highest-ranked source (label hierarchy).
    Order is preserved from first occurrence (deterministic given
    deterministic input order)."""
    kept: dict[str, LabeledVariant] = {}
    order: list[str] = []
    for variant in labeled:
        if _excluded(variant):
            continue
        if variant.snapshot != config.labels_snapshot:
            raise ValueError(
                "provenance breach: labeled variant "
                f"{variant.variant_id!r} carries snapshot {variant.snapshot!r} but "
                f"config.labels_snapshot={config.labels_snapshot!r} -- the report must "
                "never cite a snapshot it did not actually score (MAJOR-2)"
            )
        existing = kept.get(variant.variant_id)
        if existing is None:
            kept[variant.variant_id] = variant
            order.append(variant.variant_id)
        elif _source_rank(variant.source) < _source_rank(existing.source):
            kept[variant.variant_id] = variant

    return [
        BenchmarkRow(
            variant_id=vid,
            label=kept[vid].label,
            variant_class=kept[vid].variant_class,
            source=kept[vid].source,
            snapshot=kept[vid].snapshot,
        )
        for vid in order
    ]
