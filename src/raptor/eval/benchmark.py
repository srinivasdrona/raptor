"""PRD-06 sec 10.3 `benchmark.py` — the benchmark builder (FR1).

This is the ONLY place a label enters the eval harness (FR8/AC6/H1): reads
`LabeledVariant` rows, applies the exclusions (conflicting, single-submitter,
any label RAPTOR influenced -- R-A2 circularity) and the label-source
hierarchy (EVALUATION Part I sec 2 -- when the same variant identity appears more
than once, the highest-ranked source wins), and freezes the result as
`BenchmarkRow`s. Nothing downstream of this module ever sees a
`LabeledVariant` or a raw label file.
"""
from __future__ import annotations

from typing import Iterable, List

from .config import EvalConfig
from .model import BenchmarkRow, LabeledVariant

#: Label-source hierarchy, highest confidence first (EVALUATION Part I sec 2). Used
#: only to resolve a variant identity that appears more than once in the
#: labels source -- never to change the label value itself. Lower rank number
#: = higher priority: expert adjudication / ClinGen outrank curated literature,
#: which outranks a 2-star ClinVar consensus, which outranks a default ClinVar
#: entry (a default DB entry must never win a dedup over an expert/curated call).
_SOURCE_RANK: dict[str, int] = {
    "oracle_adjudication": 0,
    "clingen_vcep": 1,
    "clingen_3star": 1,
    "curated_literature": 2,
    "clinvar_2star_concordant": 3,
    "clinvar": 4,
}


#: Labels the metrics pipeline can score (FR1/R-A2): anything else (VUS,
#: not_provided, etc.) is unmappable and must be excluded, never silently
#: mis-counted.
_SCOREABLE_LABELS: frozenset[str] = frozenset({"P", "LP", "LB", "B"})

#: The FINITE set of ClinVar review-status markers that indicate a
#: low-confidence assertion unfit for a truth set (EVALUATION Part I sec 2). A label
#: whose `review_status` contains ANY of these (case-insensitive) is excluded:
#: 1-star `single submitter`, any `conflicting` status, and 0-star
#: `no assertion` / `no classification` records. The high-confidence remainder
#: (2-star `multiple submitters, no conflicts`, `reviewed by expert panel`,
#: `practice guideline`) is kept. ClinVar's review vocabulary is finite, so this
#: enumerates the whole low-quality set at once (never a per-status patch).
_LOW_CONFIDENCE_REVIEW_MARKERS: tuple[str, ...] = (
    "single submitter",
    "conflicting",
    "no assertion",
    "no classification",
)

#: HIGH-confidence review statuses (2-star concordant / expert panel / practice
#: guideline). Confidence is REVIEW-STATUS-driven -- a high-confidence label is
#: kept even when `NumberSubmitters == 1` (a single expert-panel submission is
#: legitimate). Raw `submitter_count` is only a FALLBACK proxy, applied to an
#: UNRECOGNIZED review status (never to override a known high/low tier).
_HIGH_CONFIDENCE_REVIEW_MARKERS: tuple[str, ...] = (
    "practice guideline",
    "reviewed by expert panel",
    "multiple submitters, no conflicts",
)


def _source_rank(source: str) -> int:
    return _SOURCE_RANK.get(source, len(_SOURCE_RANK))


def _excluded(variant: LabeledVariant) -> bool:
    if variant.label == "Conflicting":
        return True
    if variant.raptor_influenced:
        return True
    if variant.label not in _SCOREABLE_LABELS:
        return True
    rs = (variant.review_status or "").lower()
    if any(marker in rs for marker in _LOW_CONFIDENCE_REVIEW_MARKERS):
        return True
    # Confidence is review-status-driven: a high-confidence status is kept
    # regardless of submitter count. The raw-count proxy applies ONLY to an
    # unrecognized status (a conservative fallback for placeholder/unknown data).
    if any(marker in rs for marker in _HIGH_CONFIDENCE_REVIEW_MARKERS):
        return False
    if variant.submitter_count < 2:
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
