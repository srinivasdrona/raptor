"""Evaluation-only evidence wrapper applying the approved BP4/PP3 correction."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .predictor_aggregation import AggregationSpec

_SCORE_TO_STRENGTH = {
    1: "supporting",
    2: "moderate",
    3: "strong",
    4: "very_strong",
}


class PredictorCorrectedEvidenceSource:
    """Replace only BP4/PP3 scoring strengths while retaining corrections."""

    def __init__(self, source: Any, spec: AggregationSpec) -> None:
        self._source = source
        self._spec = spec
        self.variant_ids = source.variant_ids
        self._corrections: dict[str, dict[str, Any]] = defaultdict(dict)

    def get_evidence(self, variant_id: str):
        corrected_calls: list[tuple[str, str, str]] = []
        for criterion, strength, direction in self._source.get_evidence(variant_id):
            if criterion not in {"PP3", "BP4"}:
                corrected_calls.append((criterion, strength, direction))
                continue
            correction = self._source.get_predictor_correction(
                variant_id, criterion, self._spec
            )
            self._corrections[variant_id][criterion] = correction
            if correction.corrected_strength == 0:
                continue
            corrected_calls.append(
                (
                    criterion,
                    _SCORE_TO_STRENGTH[correction.corrected_strength],
                    direction,
                )
            )
        return tuple(corrected_calls)

    def corrections_for(self, variant_id: str) -> dict[str, Any]:
        return dict(self._corrections.get(variant_id, {}))

    def correction_counts(self) -> dict[str, int]:
        counts = {"PP3": 0, "BP4": 0}
        for corrections in self._corrections.values():
            for criterion, correction in corrections.items():
                if correction.emitted_strength != correction.corrected_strength:
                    counts[criterion] += 1
        return counts
