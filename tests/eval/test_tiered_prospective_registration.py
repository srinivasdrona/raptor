"""Prospective validation registration tests for versioned tiered gate v3.

Asserts that the locked prospective contract is correctly registered, status is PENDING,
the dataset selection rule is deterministic and singular, and contract modification is rejected.
"""
from __future__ import annotations

import pytest
from raptor.eval.config import EvalConfig
from raptor.eval.tiered_gate import (
    decide_tiered_gate,
    TieredReadjudicationConfigError,
)


def make_tiered_authorization_dict():
    """Build the exact versioned tiered_authorization configuration block."""
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
                },
                "unavailable_or_contract_invalid": {
                    "fallback_status": "BLOCKED_DATA",
                    "outcome_dependent_fallback": False,
                }
            }
        }
    }


def make_test_config(**overrides) -> EvalConfig:
    """Build a frozen EvalConfig containing the new tiered_authorization block."""
    base = dict(
        automatable_criteria=["PVS1", "PS3", "PM1", "PM2", "PP3", "BA1", "BS1", "BS2", "BP4", "BP7"],
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
        tiered_authorization=make_tiered_authorization_dict(),
    )
    base.update(overrides)
    return EvalConfig(**base)


def test_prospective_contract_exists_and_pending():
    """Assert that the locked prospective contract exists and has PENDING status."""
    config = make_test_config()
    tiered_auth = config.tiered_authorization
    assert tiered_auth is not None
    assert tiered_auth["prospective_validation"]["status"] == "PENDING"


def test_prospective_rule_is_deterministic_and_singular():
    """Assert that the dataset rule is deterministic, singular, and specifies variant_summary_2026-08.txt.gz."""
    config = make_test_config()
    rule = config.tiered_authorization["prospective_validation"]["dataset_rule"]
    
    # Selection rule must resolve to exactly one registered archive (no logical OR fallback)
    assert "The FIRST NCBI ClinVar GRCh38 variant_summary MONTHLY archive" in rule["registered_dataset"]
    assert "variant_summary_2026-08.txt.gz" in rule["registered_dataset"]
    assert "Selection is deterministic and yields EXACTLY ONE archive" in rule["registered_dataset"]

    # BLOCKED_DATA path chooses NO outcome-dependent fallback
    assert rule["unavailable_or_contract_invalid"]["fallback_status"] == "BLOCKED_DATA"
    assert rule["unavailable_or_contract_invalid"]["outcome_dependent_fallback"] is False


def test_contract_edits_rejected_post_lock():
    """Assert that any modification to states, thresholds, scope map, or dataset-rule is rejected post-lock."""
    # 1. Modifying a threshold
    bad_tiered_auth = make_tiered_authorization_dict()
    bad_config_threshold = make_test_config(min_count_per_class=35)
    
    from raptor.eval.model import Metrics
    m = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"total": 50, "total_called": 40, "abstain": 10, "path_actual": 50, "path_called": 40, "benign_actual": 0, "benign_called": 0, "tp": 40, "tn": 0, "fp": 0, "fn": 0},
        stratum="missense", gating=True
    )
    m.precision_lb = 0.95
    m.recall_lb = 0.95
    metrics = {"missense": m}
    
    class SimpleRunMeta:
        def __init__(self):
            self.effective_lineage_blockers = []
            self.remask_survivors = 0
            self.canonical_join_rows = 100
            self.bias_rows = 100
            self.returned_artifacts_verified = 1
            self.evaluation_skipped = ["PM1"]
            
    run_meta = SimpleRunMeta()

    with pytest.raises(TieredReadjudicationConfigError):
        decide_tiered_gate(metrics, bad_config_threshold, run_meta)

    # 2. Modifying the scope map
    bad_tiered_auth_map = make_tiered_authorization_dict()
    bad_tiered_auth_map["criterion_scope_applicability"]["PM1"] = ["missense:pathogenic", "truncating:pathogenic"]
    bad_config_map = make_test_config(tiered_authorization=bad_tiered_auth_map)
    with pytest.raises(TieredReadjudicationConfigError):
        decide_tiered_gate(metrics, bad_config_map, run_meta)

    # 3. Modifying the dataset rule
    bad_tiered_auth_rule = make_tiered_authorization_dict()
    bad_tiered_auth_rule["prospective_validation"]["dataset_rule"]["registered_dataset"] = "Some other dataset OR variant_summary_2026-08"
    bad_config_rule = make_test_config(tiered_authorization=bad_tiered_auth_rule)
    with pytest.raises(TieredReadjudicationConfigError):
        decide_tiered_gate(metrics, bad_config_rule, run_meta)
