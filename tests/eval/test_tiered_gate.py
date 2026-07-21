"""Synthetic axis tests for the versioned tiered gate v3.

Asserts every independent axis, precedence, coverage, and typed fail-closed errors
using hand-built Metrics fixtures.
"""
from __future__ import annotations

import pytest
from raptor.eval.config import EvalConfig
from raptor.eval.model import Metrics
try:
    from raptor.eval.tiered_gate import (
        decide_tiered_gate,
        TieredReadjudicationError,
        TieredReadjudicationInputError,
        TieredReadjudicationConfigError,
    )
except ImportError:
    class TieredReadjudicationError(Exception):
        pass
    class TieredReadjudicationInputError(TieredReadjudicationError):
        pass
    class TieredReadjudicationConfigError(TieredReadjudicationError):
        pass

    def decide_tiered_gate(*args, **kwargs):
        pytest.fail("Missing planned implementation of decide_tiered_gate", pytrace=False)

try:
    from raptor.eval.model import TieredScopeVerdict, TieredGateDecision
except ImportError:
    class TieredScopeVerdict:
        pass
    class TieredGateDecision:
        pass


class MockRunMeta:
    """Mock whole-run integrity metadata for A0_run_integrity testing."""
    def __init__(
        self,
        effective_lineage_blockers=None,
        remask_survivors=0,
        canonical_join_rows=100,
        bias_rows=100,
        returned_artifacts_verified=1,
        evaluation_skipped=None,
    ):
        self.effective_lineage_blockers = effective_lineage_blockers if effective_lineage_blockers is not None else []
        self.remask_survivors = remask_survivors
        self.canonical_join_rows = canonical_join_rows
        self.bias_rows = bias_rows
        self.returned_artifacts_verified = returned_artifacts_verified
        self.evaluation_skipped = evaluation_skipped if evaluation_skipped is not None else ["PM1"]


def make_tiered_authorization_dict():
    """Build a complete, pinned tiered_authorization config dictionary."""
    return {
        "schema_version": 3,
        "axis_enums": {
            "A0_run_integrity": ["PASS", "INVALID"],
            "A1_data_sufficiency": ["ADEQUATE", "UNDERPOWERED", "NO_CALLS"],
            "A2_conditional_performance": ["MET", "UNMET", "NOT_ESTIMABLE", "NOT_APPLICABLE"],
            "A3_policy_parity": ["CLEAR", "BLOCKED"],
            "A5_scope_evidence_status": [
                "INVALID", "NOT_APPLICABLE", "NO_CALLS", "UNDERPOWERED",
                "BLOCKED_POLICY", "NOT_SUPPORTED", "SUPPORTED_POSTHOC", "VALIDATED_PROSPECTIVE"
            ],
            "A6_authorization_status": ["NOT_AUTHORIZED", "PENDING_PROSPECTIVE", "AUTHORIZED_RESEARCH_ONLY"]
        },
        "criterion_scope_applicability": {
            "PM1": ["missense:pathogenic"],
            "PP3": ["missense:pathogenic", "other:pathogenic"],
            "BP4": ["missense:benign", "other:benign"],
            "PP5": ["missense:pathogenic", "truncating:pathogenic", "other:pathogenic"],
            "BP6": ["missense:benign", "truncating:benign", "other:benign"],
            "PS4": ["missense:pathogenic", "truncating:pathogenic", "other:pathogenic"],
        },
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": ["truncating:pathogenic"]
            }
        },
        "governance_statements": {
            "RESEARCH_ONLY_NO_CLINICAL_USE": (
                "This is a post-hoc re-adjudication of the frozen ADR-0012 "
                "masked-holdout counts for research evidence only; no scope is authorized, "
                "and this authorizes no clinical classification, VUS worklist, or ClinVar "
                "submission pending a prospective validation on unseen data."
            ),
            "TRUNCATING_PATHOGENIC_PROSPECTIVE_AUTHORIZED": (
                "Prospective validation on unseen data has authorized the "
                "truncating-pathogenic research scope for research-evidence use only; "
                "full-spectrum VUS automation remains not authorized while missense is "
                "unvalidated, and this authorizes no clinical classification, VUS worklist, "
                "or ClinVar submission."
            )
        },
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "no_new_evidence_statement": (
            "No new evidence was generated: this record re-interprets the frozen R2 aggregate "
            "(source_canonical_lf_sha256 7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f) "
            "under the versioned tiered rule and performs no new run, scoring, annotation, "
            "benchmark read, network access, or data generation."
        ),
        "prospective_validation": {
            "status": "PENDING",
            "dataset_rule": {
                "registered_dataset": (
                    "The FIRST NCBI ClinVar GRCh38 variant_summary MONTHLY archive whose NCBI-published "
                    "official archive date is on or after 2026-08-01 — i.e. the 2026-08 monthly release, "
                    "file variant_summary_2026-08.txt.gz under "
                    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary/. "
                    "Selection is deterministic and yields EXACTLY ONE archive: order the monthly archives by "
                    "official published archive date ascending, take the first with date >= 2026-08-01; "
                    "ties broken by lexicographically smallest archive filename."
                ),
                "freeze_before_labels_scoring": {
                    "snapshot": "clinvar_2026-08-01",
                    "url": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary/variant_summary_2026-08.txt.gz",
                    "official_md5_to_be_frozen_when_exists": "PENDING_ARCHIVE_GENERATION",
                    "official_sha256_to_be_frozen_when_exists": "PENDING_ARCHIVE_GENERATION",
                },
                "unavailable_or_contract_invalid": {
                    "fallback_status": "BLOCKED_DATA",
                    "outcome_dependent_fallback": False,
                },
                "future_authorized_surfaces_pinned": {
                    "active": False,
                    "pinned_surfaces": ["full_spectrum", "research_scopes"],
                }
            }
        }
    }


def make_test_config(**overrides) -> EvalConfig:
    """Build a frozen EvalConfig."""
    base = dict(
        automatable_criteria=["PVS1", "PS1", "PM1", "PM2", "PM4", "PM5", "PP2", "BA1", "BS1", "BP1", "BP3", "BP7"],
        tavtigian_points={
            "supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8, "stand_alone": 8,
        },
        tavtigian_cutoffs={
            "pathogenic_min": 10, "likely_pathogenic_min": 6,
            "vus_min": 0, "vus_max": 5,
            "likely_benign_max": -1, "benign_max": -7,
        },
        min_count_per_class=36,
        split={"seed": 42, "holdout_fraction": 0.3},
        oracle_thresholds={
            "confidence": 0.95,
            "strata": {
                "missense": {
                    "precision": 0.90,
                    "recall": 0.85,
                    "gating": True,
                    "directions": ["pathogenic", "benign"],
                },
                "truncating": {
                    "precision": 0.95,
                    "recall": 0.95,
                    "gating": True,
                    "directions": ["pathogenic"],
                },
            },
        },
        labels_snapshot="clinvar_2026-07-07",
    )
    base.update(overrides)
    return EvalConfig(**base)


def test_synthetic_no_calls():
    """Test 1: NO_CALLS (called=0) -> data NO_CALLS, conditional NOT_ESTIMABLE, lower bounds null."""
    config = make_test_config()
    run_meta = MockRunMeta()
    
    m_missense = Metrics(
        precision=0.0, recall=0.0, concordance=0.0,
        counts={
            "total": 51, "total_called": 0, "abstain": 51,
            "path_actual": 51, "path_called": 0, "benign_actual": 0, "benign_called": 0,
            "tp": 0, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="missense", gating=True
    )
    m_missense.precision_lb = 0.0
    m_missense.recall_lb = 0.0

    metrics = {"missense": m_missense}
    decision = decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())

    verdict = decision.scopes["missense:pathogenic"]
    assert verdict.data_sufficiency == "NO_CALLS"
    assert verdict.conditional_performance == "NOT_ESTIMABLE"
    assert verdict.precision_lb is None
    assert verdict.recall_lb is None
    assert verdict.scope_evidence_status == "NO_CALLS"
    assert verdict.authorization_status == "NOT_AUTHORIZED"


def test_synthetic_underpowered():
    """Test 2: UNDERPOWERED (0 < min(actual, called) < 36) -> NOT_ESTIMABLE, scope UNDERPOWERED.

    Asserts a nonzero stored precision_lb on <36 calls is NOT read as MET.
    """
    config = make_test_config()
    run_meta = MockRunMeta()

    # Underpowered scenario (min count per class is 36, but called count is 9)
    m_missense = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 103, "total_called": 9, "abstain": 94,
            "path_actual": 0, "path_called": 0, "benign_actual": 103, "benign_called": 9,
            "tp": 0, "tn": 9, "fp": 0, "fn": 0
        },
        stratum="missense", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_missense.benign_precision_lb = 0.6637
    m_missense.benign_recall_lb = 0.6637

    metrics = {"missense": m_missense}
    decision = decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())

    verdict = decision.scopes["missense:benign"]
    assert verdict.data_sufficiency == "UNDERPOWERED"
    assert verdict.conditional_performance == "NOT_ESTIMABLE"
    assert verdict.scope_evidence_status == "UNDERPOWERED"
    assert verdict.authorization_status == "NOT_AUTHORIZED"


def test_synthetic_adequate_met():
    """Test 3: ADEQUATE+MET -> SUPPORTED_POSTHOC + authorization PENDING_PROSPECTIVE."""
    config = make_test_config()
    run_meta = MockRunMeta()

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 211, "total_called": 189, "abstain": 22,
            "path_actual": 210, "path_called": 189, "benign_actual": 1, "benign_called": 0,
            "tp": 189, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="truncating", gating=True
    )
    m_truncating.precision_lb = 0.9806
    m_truncating.recall_lb = 0.9806

    metrics = {"truncating": m_truncating}
    decision = decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())

    verdict = decision.scopes["truncating:pathogenic"]
    assert verdict.data_sufficiency == "ADEQUATE"
    assert verdict.conditional_performance == "MET"
    assert verdict.scope_evidence_status == "SUPPORTED_POSTHOC"
    assert verdict.authorization_status == "PENDING_PROSPECTIVE"
    # Never authorized prospectively from a post-hoc run
    assert verdict.authorization_status != "AUTHORIZED_RESEARCH_ONLY"


def test_synthetic_adequate_unmet():
    """Test 4: ADEQUATE+UNMET -> NOT_SUPPORTED + authorization NOT_AUTHORIZED."""
    config = make_test_config()
    run_meta = MockRunMeta()

    m_truncating = Metrics(
        precision=0.90, recall=0.90, concordance=0.90,
        counts={
            "total": 211, "total_called": 189, "abstain": 22,
            "path_actual": 210, "path_called": 189, "benign_actual": 1, "benign_called": 0,
            "tp": 170, "tn": 0, "fp": 19, "fn": 0
        },
        stratum="truncating", gating=True
    )
    # 0.88 is below the 0.95 threshold
    m_truncating.precision_lb = 0.88
    m_truncating.recall_lb = 0.88

    metrics = {"truncating": m_truncating}
    decision = decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())

    verdict = decision.scopes["truncating:pathogenic"]
    assert verdict.data_sufficiency == "ADEQUATE"
    assert verdict.conditional_performance == "UNMET"
    assert verdict.scope_evidence_status == "NOT_SUPPORTED"
    assert verdict.authorization_status == "NOT_AUTHORIZED"


def test_synthetic_no_threshold():
    """Test 5: No registered threshold -> NOT_APPLICABLE (never fabricated threshold)."""
    config = make_test_config()
    run_meta = MockRunMeta()

    m_other = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 117, "total_called": 89, "abstain": 28,
            "path_actual": 117, "path_called": 89, "benign_actual": 0, "benign_called": 0,
            "tp": 89, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="other", gating=True
    )
    m_other.precision_lb = 0.9396
    m_other.recall_lb = 0.9593

    metrics = {"other": m_other}
    decision = decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())

    verdict = decision.scopes["other:pathogenic"]
    assert verdict.data_sufficiency == "ADEQUATE"
    assert verdict.conditional_performance == "NOT_APPLICABLE"
    assert verdict.precision_threshold is None
    assert verdict.recall_threshold is None
    assert verdict.scope_evidence_status == "NOT_APPLICABLE"
    assert verdict.authorization_status == "NOT_AUTHORIZED"


def test_synthetic_pm1_excluded_blocking():
    """Test 6: PM1 excluded -> BLOCKS only missense:pathogenic.

    Asserts that truncating:pathogenic and every benign scope stay CLEAR (global-blocker leakage guard),
    and asserts the exact reason "policy_parity=BLOCKED: PM1 evaluation_skipped applies_to missense:pathogenic"
    is present.
    """
    config = make_test_config()
    # PM1 is skipped/excluded
    run_meta = MockRunMeta(evaluation_skipped=["PM1"])

    m_missense = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 154, "total_called": 40, "abstain": 114,
            "path_actual": 51, "path_called": 40, "benign_actual": 103, "benign_called": 0,
            "tp": 40, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="missense", gating=True
    )
    m_missense.precision_lb = 0.95
    m_missense.recall_lb = 0.95

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 211, "total_called": 189, "abstain": 22,
            "path_actual": 210, "path_called": 189, "benign_actual": 1, "benign_called": 0,
            "tp": 189, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="truncating", gating=True
    )
    m_truncating.precision_lb = 0.9806
    m_truncating.recall_lb = 0.9806

    metrics = {"missense": m_missense, "truncating": m_truncating}
    decision = decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())

    # missense:pathogenic is blocked by PM1
    assert decision.scopes["missense:pathogenic"].policy_parity == "BLOCKED"
    
    # Assert exact reason is present
    assert "policy_parity=BLOCKED: PM1 evaluation_skipped applies_to missense:pathogenic" in decision.scopes["missense:pathogenic"].reasons
    
    # truncating:pathogenic and benign scopes stay CLEAR
    assert decision.scopes["truncating:pathogenic"].policy_parity == "CLEAR"

    # Other scopes must not contain it
    for scope_key, other_v in decision.scopes.items():
        if scope_key != "missense:pathogenic":
            assert "policy_parity=BLOCKED: PM1 evaluation_skipped applies_to missense:pathogenic" not in other_v.reasons


def test_synthetic_correct_call_coverage():
    """Test 7: A4 correct-call coverage uses CORRECT counts (tp/tn) and actual denominators.

    Asserts that other:benign with fp=1 yields tn/actual < called/actual.
    """
    config = make_test_config()
    run_meta = MockRunMeta()

    m_other = Metrics(
        precision=0.988, recall=1.0, concordance=0.995,
        counts={
            "total": 2212, "total_called": 202, "abstain": 2010,
            "path_actual": 117, "path_called": 89, "benign_actual": 2095, "benign_called": 113,
            "tp": 89, "tn": 112, "fp": 1, "fn": 0
        },
        stratum="other", gating=True
    )
    m_other.precision_lb = 0.9396
    m_other.recall_lb = 0.9593

    metrics = {"other": m_other}
    decision = decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())

    verdict = decision.scopes["other:benign"]
    assert verdict.end_to_end_correct_call_coverage == "112/2095"
    assert verdict.called_count == 113
    assert verdict.actual_count == 2095
    assert verdict.tp == 89
    assert verdict.tn == 112
    assert verdict.fp == 1


def test_synthetic_typed_fail_closed_errors():
    """Test 8: Typed fail-closed error (no decision / no artifact).

    Triggers are:
    - non-int/bool/negative counts
    - unknown excluded criterion
    - criterion-map applies_to drift
    """
    config = make_test_config()

    # Case A: malformed/negative counts -> TieredReadjudicationInputError
    m_bad = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": -10, "total_called": 9, "abstain": 0,
            "path_actual": 10, "path_called": 9, "benign_actual": 0, "benign_called": 0,
            "tp": 9, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="missense", gating=True
    )
    metrics_bad = {"missense": m_bad}
    run_meta = MockRunMeta()
    with pytest.raises(TieredReadjudicationInputError):
        decide_tiered_gate(metrics_bad, config, run_meta, make_tiered_authorization_dict())

    # Case B: Unknown skipped criterion (not in criterion_scope_applicability map)
    run_meta_unknown = MockRunMeta(evaluation_skipped=["UNKNOWN_CRITERION"])
    m_normal = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 50, "total_called": 40, "abstain": 10,
            "path_actual": 50, "path_called": 40, "benign_actual": 0, "benign_called": 0,
            "tp": 40, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="missense", gating=True
    )
    metrics_normal = {"missense": m_normal}
    with pytest.raises(TieredReadjudicationConfigError):
        decide_tiered_gate(metrics_normal, config, run_meta_unknown, make_tiered_authorization_dict())

    # Case C: Config drift in criterion_scope_applicability mapping
    bad_applicability = make_tiered_authorization_dict()
    bad_applicability["criterion_scope_applicability"]["PM1"] = ["missense:pathogenic", "truncating:pathogenic"]
    with pytest.raises(TieredReadjudicationConfigError):
        decide_tiered_gate(metrics_normal, config, run_meta, bad_applicability)


@pytest.mark.parametrize(
    "override_config_kwargs",
    [
        # drift in confidence
        {"oracle_thresholds": {"confidence": 0.90, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}}},
        # drift in missense precision
        {"oracle_thresholds": {"confidence": 0.95, "strata": {"missense": {"precision": 0.89, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}}},
        # drift in missense recall
        {"oracle_thresholds": {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.84, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}}},
        # drift in missense directions
        {"oracle_thresholds": {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}}},
        # drift in missense gating
        {"oracle_thresholds": {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": False, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}}},
        # drift in truncating precision
        {"oracle_thresholds": {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.90, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}}},
        # drift in truncating recall
        {"oracle_thresholds": {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.90, "gating": True, "directions": ["pathogenic"]}}}},
        # drift in min_count_per_class (below pre-registered floor)
        {"min_count_per_class": 35},
        # drift in min_count_per_class (above pre-registered floor)
        {"min_count_per_class": 37},
        # drift with extra registered 'other' threshold
        {"oracle_thresholds": {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}, "other": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}}}},
        # drift with extra registered 'foo' threshold
        {"oracle_thresholds": {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}, "foo": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}}}},
    ]
)
def test_oracle_pin_drift_raises_config_error(override_config_kwargs):
    """Assert that hand-built EvalConfig drift in confidence, thresholds, directions, gating, or min_count
    raises TieredReadjudicationConfigError before decision despite an otherwise valid tiered block.
    """
    config = make_test_config(**override_config_kwargs)
    run_meta = MockRunMeta()
    m = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"total": 50, "total_called": 40, "abstain": 10, "path_actual": 50, "path_called": 40, "benign_actual": 0, "benign_called": 0, "tp": 40, "tn": 0, "fp": 0, "fn": 0},
        stratum="missense", gating=True
    )
    metrics = {"missense": m}
    
    with pytest.raises(TieredReadjudicationConfigError):
        decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())


@pytest.mark.parametrize(
    "invalid_oracle_thresholds",
    [
        # confidence as numeric string
        {"confidence": "0.95", "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}},
        # confidence as boolean
        {"confidence": True, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}},
        # missense precision as numeric string
        {"confidence": 0.95, "strata": {"missense": {"precision": "0.90", "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}},
        # missense precision as boolean
        {"confidence": 0.95, "strata": {"missense": {"precision": True, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}},
        # missense recall as numeric string
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": "0.85", "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}},
        # missense recall as boolean
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": False, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}},
        # truncating precision as numeric string
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": "0.95", "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}},
        # truncating precision as boolean
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": True, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}}},
        # truncating recall as numeric string
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": "0.95", "gating": True, "directions": ["pathogenic"]}}},
        # truncating recall as boolean
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}, "truncating": {"precision": 0.95, "recall": False, "gating": True, "directions": ["pathogenic"]}}},
    ]
)
def test_oracle_pin_drift_numeric_strings_and_booleans(invalid_oracle_thresholds):
    """Assert that numeric strings or booleans for thresholds raise TieredReadjudicationConfigError
    instead of being accepted or raising TypeError.
    """
    config = make_test_config(oracle_thresholds=invalid_oracle_thresholds)
    run_meta = MockRunMeta()
    m = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"total": 50, "total_called": 40, "abstain": 10, "path_actual": 50, "path_called": 40, "benign_actual": 0, "benign_called": 0, "tp": 40, "tn": 0, "fp": 0, "fn": 0},
        stratum="missense", gating=True
    )
    metrics = {"missense": m}
    with pytest.raises(TieredReadjudicationConfigError):
        decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())


def test_oracle_pin_drift_keeps_valid_numeric_types():
    """Assert that valid int and float threshold behaviors are accepted and do not raise errors."""
    valid_oracle_thresholds = {
        "confidence": 0.95,
        "strata": {
            "missense": {
                "precision": 0.9,  # 0.9 instead of 0.90, valid float/int comparison
                "recall": 0.85,
                "gating": True,
                "directions": ["pathogenic", "benign"],
            },
            "truncating": {
                "precision": 0.95,
                "recall": 0.95,
                "gating": True,
                "directions": ["pathogenic"],
            },
        },
    }
    config = make_test_config(oracle_thresholds=valid_oracle_thresholds)
    run_meta = MockRunMeta()
    m = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"total": 50, "total_called": 40, "abstain": 10, "path_actual": 50, "path_called": 40, "benign_actual": 0, "benign_called": 0, "tp": 40, "tn": 0, "fp": 0, "fn": 0},
        stratum="missense", gating=True
    )
    metrics = {"missense": m}
    decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())


@pytest.mark.parametrize(
    "invalid_bound",
    [
        -0.1,
        1.1,
        float("inf"),
        float("-inf"),
        float("nan"),
        "0.95",
        True,
    ],
)
def test_conditional_lower_bounds_fail_closed(invalid_bound):
    """Malformed confidence bounds never become MET or post-hoc support."""
    config = make_test_config()
    run_meta = MockRunMeta()
    metrics_row = Metrics(
        precision=1.0,
        recall=1.0,
        concordance=1.0,
        counts={
            "total": 50,
            "total_called": 40,
            "abstain": 10,
            "path_actual": 40,
            "path_called": 40,
            "benign_actual": 10,
            "benign_called": 0,
            "tp": 40,
            "tn": 0,
            "fp": 0,
            "fn": 0,
        },
        stratum="truncating",
        gating=True,
    )
    metrics_row.precision_lb = invalid_bound
    metrics_row.recall_lb = invalid_bound

    with pytest.raises(TieredReadjudicationInputError):
        decide_tiered_gate(
            {"truncating": metrics_row},
            config,
            run_meta,
            make_tiered_authorization_dict(),
        )


def test_synthetic_full_spectrum_requires():
    """Test 9: full_spectrum authorization requires ALL three requires-scopes VALIDATED_PROSPECTIVE.

    SUPPORTED_POSTHOC alone never authorizes; dropping a missense scope is config drift and raises error.
    """
    # 1. Underpowered/posthoc run -> status stays NOT_VALIDATED and full_spectrum_authorization stays NOT_AUTHORIZED
    config = make_test_config()
    run_meta = MockRunMeta()

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 211, "total_called": 189, "abstain": 22,
            "path_actual": 210, "path_called": 189, "benign_actual": 1, "benign_called": 0,
            "tp": 189, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="truncating", gating=True
    )
    m_truncating.precision_lb = 0.9806
    m_truncating.recall_lb = 0.9806

    m_missense_under = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 103, "total_called": 9, "abstain": 94,
            "path_actual": 0, "path_called": 0, "benign_actual": 103, "benign_called": 9,
            "tp": 0, "tn": 9, "fp": 0, "fn": 0
        },
        stratum="missense", gating=True
    )
    m_missense_under.benign_precision_lb = 0.6637
    m_missense_under.benign_recall_lb = 0.6637

    metrics = {"truncating": m_truncating, "missense": m_missense_under}
    decision = decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())

    assert decision.full_spectrum_status == "NOT_VALIDATED"
    assert decision.full_spectrum_authorization == "NOT_AUTHORIZED"

    # 2. Config drift error when dropping a required scope
    bad_spectrum = make_tiered_authorization_dict()
    bad_spectrum["full_spectrum"]["requires"] = ["truncating:pathogenic"]
    with pytest.raises(TieredReadjudicationConfigError):
        decide_tiered_gate(metrics, config, run_meta, bad_spectrum)


def test_synthetic_invalid_run_integrity():
    """Test 10: INVALID run integrity (A0) -> every scope A5 INVALID, no authorization, but artifact is emitted."""
    config = make_test_config()
    # Integrity fails because returned_artifacts_verified < 1 and remask_survivors > 0
    run_meta_invalid = MockRunMeta(
        remask_survivors=1,
        returned_artifacts_verified=0
    )

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 211, "total_called": 189, "abstain": 22,
            "path_actual": 210, "path_called": 189, "benign_actual": 1, "benign_called": 0,
            "tp": 189, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="truncating", gating=True
    )
    m_truncating.precision_lb = 0.9806
    m_truncating.recall_lb = 0.9806

    metrics = {"truncating": m_truncating}
    decision = decide_tiered_gate(metrics, config, run_meta_invalid, make_tiered_authorization_dict())

    assert decision.run_integrity == "INVALID"
    for scope_key, verdict in decision.scopes.items():
        assert verdict.scope_evidence_status == "INVALID"
        assert verdict.authorization_status == "NOT_AUTHORIZED"

    assert decision.full_spectrum_status == "NOT_VALIDATED"
    assert decision.full_spectrum_authorization == "NOT_AUTHORIZED"
    assert decision.research_scope_evidence_status == "NOT_SUPPORTED"
    assert decision.research_scope_authorization == "NOT_AUTHORIZED"


def test_synthetic_post_hoc_never_authorizes():
    """Test 11: Post-hoc path NEVER emits AUTHORIZED_RESEARCH_ONLY, VALIDATED_PROSPECTIVE, or a true research flag."""
    config = make_test_config()
    run_meta = MockRunMeta()

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={
            "total": 211, "total_called": 189, "abstain": 22,
            "path_actual": 210, "path_called": 189, "benign_actual": 1, "benign_called": 0,
            "tp": 189, "tn": 0, "fp": 0, "fn": 0
        },
        stratum="truncating", gating=True
    )
    m_truncating.precision_lb = 0.9806
    m_truncating.recall_lb = 0.9806

    metrics = {"truncating": m_truncating}
    decision = decide_tiered_gate(metrics, config, run_meta, make_tiered_authorization_dict())

    # Research scope should be SUPPORTED_POSTHOC but authorization remains PENDING_PROSPECTIVE
    assert decision.research_scope_evidence_status == "SUPPORTED_POSTHOC"
    assert decision.research_scope_authorization == "PENDING_PROSPECTIVE"
    # Canonical boolean flag remains False
    assert decision.research_scope_flags["truncating_pathogenic_research_scope_validated"] is False
    assert decision.governance_state == "RESEARCH_ONLY_NO_CLINICAL_USE"


@pytest.mark.parametrize(
    "missing_key",
    [
        "total",
        "total_called",
        "abstain",
        "path_actual",
        "path_called",
        "benign_actual",
        "benign_called",
        "tp",
        "tn",
        "fp",
        "fn",
    ],
)
def test_synthetic_missing_counts_fail_closed(missing_key):
    """Assert that deletion of any required Metrics.counts key raises TieredReadjudicationInputError."""
    config = make_test_config()
    run_meta = MockRunMeta()

    counts = {
        "total": 50,
        "total_called": 40,
        "abstain": 10,
        "path_actual": 50,
        "path_called": 40,
        "benign_actual": 0,
        "benign_called": 0,
        "tp": 40,
        "tn": 0,
        "fp": 0,
        "fn": 0,
    }

    # Delete the parameterized key
    del counts[missing_key]

    m_bad = Metrics(
        precision=1.0,
        recall=1.0,
        concordance=1.0,
        counts=counts,
        stratum="missense",
        gating=True,
    )
    metrics_bad = {"missense": m_bad}

    with pytest.raises(TieredReadjudicationInputError):
        decide_tiered_gate(metrics_bad, config, run_meta, make_tiered_authorization_dict())
