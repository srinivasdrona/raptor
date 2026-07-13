from __future__ import annotations

from dataclasses import dataclass

from raptor.eval.predictor_aggregation import load_aggregation_spec
from raptor.eval.terminal_source import PredictorCorrectedEvidenceSource


@dataclass
class _Correction:
    corrected_strength: int


class _Source:
    variant_ids = ("v1",)

    def get_evidence(self, variant_id):
        assert variant_id == "v1"
        return (
            ("PVS1", "very_strong", "pathogenic"),
            ("PP3", "moderate", "pathogenic"),
            ("BP4", "supporting", "benign"),
        )

    def get_predictor_correction(self, variant_id, criterion, spec):
        assert variant_id == "v1"
        return {
            "PP3": _Correction(3),
            "BP4": _Correction(0),
        }[criterion]


def test_predictor_corrected_source_replaces_strength_and_preserves_audit() -> None:
    wrapped = PredictorCorrectedEvidenceSource(
        _Source(),
        load_aggregation_spec("configs/eval/predictor_aggregation.yaml"),
    )

    assert wrapped.get_evidence("v1") == (
        ("PVS1", "very_strong", "pathogenic"),
        ("PP3", "strong", "pathogenic"),
    )
    corrections = wrapped.corrections_for("v1")
    assert corrections["PP3"].corrected_strength == 3
    assert corrections["BP4"].corrected_strength == 0
