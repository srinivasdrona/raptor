from __future__ import annotations

from dataclasses import dataclass

import pytest

from conftest import make_eval_config, make_labeled
from raptor.eval.combine import implied_direction
from raptor.eval.harness import run_eval
from raptor.eval.predictor_aggregation import load_aggregation_spec
import raptor.eval.terminal_source as terminal_source


@dataclass
class _Correction:
    emitted_strength: int
    corrected_strength: int


class _Source:
    def __init__(self, evidence_by_id, corrections=None):
        self.variant_ids = tuple(sorted(evidence_by_id))
        self._evidence_by_id = dict(evidence_by_id)
        self._corrections = dict(corrections or {})

    def get_evidence(self, variant_id):
        return self._evidence_by_id[variant_id]

    def get_predictor_correction(self, variant_id, criterion, spec):
        return self._corrections[(variant_id, criterion)]


def _acmg_criteria():
    return {
        "PVS1": {"strength_vocab": ["very_strong", "strong", "moderate", "supporting"]},
        "PM2": {"strength_vocab": ["moderate", "supporting"]},
        "PP3": {"strength_vocab": ["strong", "moderate", "supporting"]},
        "PS4": {"strength_vocab": ["strong", "moderate", "supporting"]},
        "BP4": {"strength_vocab": ["supporting"]},
    }


def _production_source(source, *, acmg_criteria=None, automatable_criteria=None):
    return terminal_source.ProductionVocabEvidenceSource(
        source,
        acmg_criteria or _acmg_criteria(),
        automatable_criteria or ("PVS1", "PM2", "PP3", "BP4"),
    )


def test_predictor_corrected_source_replaces_strength_and_preserves_audit() -> None:
    wrapped = terminal_source.PredictorCorrectedEvidenceSource(
        _Source(
            {
                "v1": (
                    ("PVS1", "very_strong", "pathogenic"),
                    ("PP3", "moderate", "pathogenic"),
                    ("BP4", "supporting", "benign"),
                )
            },
            corrections={
                ("v1", "PP3"): _Correction(emitted_strength=2, corrected_strength=3),
                ("v1", "BP4"): _Correction(emitted_strength=1, corrected_strength=0),
            },
        ),
        load_aggregation_spec("configs/eval/predictor_aggregation.yaml"),
    )

    assert wrapped.get_evidence("v1") == (
        ("PVS1", "very_strong", "pathogenic"),
        ("PP3", "strong", "pathogenic"),
    )
    corrections = wrapped.corrections_for("v1")
    assert corrections["PP3"].corrected_strength == 3
    assert corrections["BP4"].corrected_strength == 0


def test_production_vocab_routes_whole_record_for_valid_pvs1_plus_invalid_bp4_strong() -> None:
    wrapped = _production_source(
        _Source(
            {
                "v1": (
                    ("PVS1", "very_strong", "pathogenic"),
                    ("BP4", "strong", "benign"),
                )
            }
        )
    )

    assert wrapped.get_evidence("v1") == ()
    assert wrapped.manual_routed_counts == {"STRENGTH_OUT_OF_VOCAB": 1}
    assert wrapped.manual_routed_variant_ids == ("v1",)
    assert wrapped.reason_for("v1") == (
        "strength_out_of_vocab: criterion 'BP4' fired with strength 'strong', "
        "which is not in its configured strength_vocab ['supporting']"
    )


def test_production_vocab_preserves_all_valid_calls() -> None:
    corrected = terminal_source.PredictorCorrectedEvidenceSource(
        _Source(
            {
                "v1": (
                    ("PVS1", "very_strong", "pathogenic"),
                    ("PM2", "moderate", "pathogenic"),
                    ("PP3", "moderate", "pathogenic"),
                    ("BP4", "supporting", "benign"),
                )
            },
            corrections={
                ("v1", "PP3"): _Correction(emitted_strength=2, corrected_strength=3),
                ("v1", "BP4"): _Correction(emitted_strength=1, corrected_strength=1),
            },
        ),
        load_aggregation_spec("configs/eval/predictor_aggregation.yaml"),
    )
    wrapped = _production_source(corrected)

    assert wrapped.get_evidence("v1") == (
        ("PVS1", "very_strong", "pathogenic"),
        ("PM2", "moderate", "pathogenic"),
        ("PP3", "strong", "pathogenic"),
        ("BP4", "supporting", "benign"),
    )
    assert wrapped.manual_routed_counts == {}
    assert wrapped.manual_routed_variant_ids == ()
    assert wrapped.reason_for("v1") is None


def test_production_vocab_routes_bp4_when_correction_makes_it_strong() -> None:
    corrected = terminal_source.PredictorCorrectedEvidenceSource(
        _Source(
            {"v1": (("BP4", "supporting", "benign"),)},
            corrections={
                ("v1", "BP4"): _Correction(emitted_strength=1, corrected_strength=3),
            },
        ),
        load_aggregation_spec("configs/eval/predictor_aggregation.yaml"),
    )
    wrapped = _production_source(corrected)

    assert wrapped.get_evidence("v1") == ()
    assert wrapped.manual_routed_counts == {"STRENGTH_OUT_OF_VOCAB": 1}
    assert wrapped.reason_for("v1") == (
        "strength_out_of_vocab: criterion 'BP4' fired with strength 'strong', "
        "which is not in its configured strength_vocab ['supporting']"
    )


def test_production_vocab_routes_raw_pm2_strong() -> None:
    wrapped = _production_source(_Source({"v1": (("PM2", "strong", "pathogenic"),)}))

    assert wrapped.get_evidence("v1") == ()
    assert wrapped.manual_routed_counts == {"STRENGTH_OUT_OF_VOCAB": 1}
    assert wrapped.reason_for("v1") == (
        "strength_out_of_vocab: criterion 'PM2' fired with strength 'strong', "
        "which is not in its configured strength_vocab ['moderate', 'supporting']"
    )


def test_production_vocab_ignores_invalid_non_automatable_strength() -> None:
    wrapped = _production_source(
        _Source(
            {
                "v1": (
                    ("PVS1", "very_strong", "pathogenic"),
                    ("PS4", "very_strong", "pathogenic"),
                )
            }
        ),
        automatable_criteria=("PVS1", "PM2", "PP3", "BP4"),
    )

    assert wrapped.get_evidence("v1") == (
        ("PVS1", "very_strong", "pathogenic"),
        ("PS4", "very_strong", "pathogenic"),
    )
    assert wrapped.manual_routed_counts == {}
    assert wrapped.manual_routed_variant_ids == ()


def test_production_vocab_manual_routing_audit_is_deterministic_idempotent_and_sorted() -> None:
    wrapped = _production_source(
        _Source(
            {
                "v2": (("PM2", "strong", "pathogenic"),),
                "v1": (("BP4", "strong", "benign"),),
            }
        )
    )

    assert wrapped.get_evidence("v2") == ()
    assert wrapped.get_evidence("v1") == ()
    assert wrapped.get_evidence("v2") == ()

    assert wrapped.manual_routed_counts == {"STRENGTH_OUT_OF_VOCAB": 2}
    assert wrapped.manual_routed_variant_ids == ("v1", "v2")
    assert wrapped.reason_for("v1") == (
        "strength_out_of_vocab: criterion 'BP4' fired with strength 'strong', "
        "which is not in its configured strength_vocab ['supporting']"
    )
    assert wrapped.reason_for("v2") == (
        "strength_out_of_vocab: criterion 'PM2' fired with strength 'strong', "
        "which is not in its configured strength_vocab ['moderate', 'supporting']"
    )


def test_production_vocab_fails_loud_when_automatable_vocab_is_missing() -> None:
    wrapped = _production_source(
        _Source({"v1": (("PM2", "moderate", "pathogenic"),)}),
        acmg_criteria={"PVS1": {"strength_vocab": ["very_strong"]}},
        automatable_criteria=("PM2",),
    )

    with pytest.raises(KeyError, match="PM2"):
        wrapped.get_evidence("v1")


def test_production_vocab_routed_record_abstains_in_combiner_and_harness() -> None:
    cfg = make_eval_config(
        automatable_criteria=["BP4"],
        split={"seed": 42, "holdout_fraction": 1.0},
    )
    wrapped = _production_source(
        _Source({"v1": (("BP4", "strong", "benign"),)}),
        automatable_criteria=cfg.automatable_criteria,
    )

    calls = wrapped.get_evidence("v1")
    assert calls == ()
    assert implied_direction(calls, cfg).implied == "no_call"

    report = run_eval(cfg, [make_labeled("v1", label="P")], wrapped)
    assert report.metrics["overall"].counts["abstain"] == 1
    assert report.metrics["overall"].counts["fn"] == 0
    assert report.metrics["overall"].counts["fp"] == 0
