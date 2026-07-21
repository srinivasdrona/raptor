"""Test for the post-hoc re-adjudication of the frozen R2 masked-holdout gate.

Loads the byte-frozen R2 record via its canonical LF hash and asserts the derived axes.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import pytest

from raptor.eval.config import EvalConfig
from raptor.eval.model import Metrics
from raptor.eval.tiered_gate import (
    decide_tiered_gate,
    TieredReadjudicationInputError,
)


class MockRunMeta:
    def __init__(self, integrity_dict: dict, policy_dict: dict):
        self.effective_lineage_blockers = integrity_dict.get("effective_lineage_blockers", [])
        self.remask_survivors = integrity_dict.get("remask_survivors", 0)
        self.canonical_join_rows = integrity_dict.get("canonical_join_rows", 0)
        self.bias_rows = integrity_dict.get("bias_rows", 0)
        self.returned_artifacts_verified = integrity_dict.get("returned_artifacts_verified", 0)
        self.evaluation_skipped = policy_dict.get("evaluation_skipped", [])


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
            "status": "PENDING"
        }
    }


def test_frozen_r2_re_adjudication():
    """Test loading and re-adjudicating the canonical-LF-verified R2 record."""
    r2_path = Path("data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json")
    assert r2_path.exists(), f"Could not find R2 record at {r2_path}"

    raw_bytes = r2_path.read_bytes()
    
    # 1. Verify the on-disk file line-endings-normalized (LF) SHA-256 hash
    lf_bytes = raw_bytes.replace(b"\r\n", b"\n")
    calculated_lf_hash = hashlib.sha256(lf_bytes).hexdigest()
    expected_lf_hash = "7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f"
    assert calculated_lf_hash == expected_lf_hash, f"LF Hash mismatch! Got {calculated_lf_hash}"

    # 2. Reconstruct state from R2 payload
    payload = json.loads(lf_bytes.decode("utf-8"))
    
    # Check R2 source hash
    source_content_hash = payload["content_hash"]
    assert source_content_hash == "2ead589d2f129f988d9932bb01153891902f0d675000554887a1524e567413b2"

    # Reconstruct Metrics map
    metrics_map = {}
    for stratum_name, data in payload["metrics"].items():
        if stratum_name == "overall":
            continue
        m = Metrics(
            precision=data.get("precision", 0.0),
            recall=data.get("recall", 0.0),
            concordance=data.get("concordance", 0.0),
            counts=data.get("counts", {}),
            stratum=stratum_name,
            gating=data.get("gating", True),
            benign_precision=data.get("benign_precision", 0.0),
            benign_recall=data.get("benign_recall", 0.0),
            precision_lb=data.get("precision_lb", 0.0),
            recall_lb=data.get("recall_lb", 0.0),
            benign_precision_lb=data.get("benign_precision_lb", 0.0),
            benign_recall_lb=data.get("benign_recall_lb", 0.0),
        )
        metrics_map[stratum_name] = m

    # Construct EvalConfig with versioned tiered_authorization
    config = EvalConfig(
        automatable_criteria=payload["thresholds"]["strata"]["missense"]["directions"] + ["PM1", "PP3", "BP4", "PP5", "BP6", "PS4"],
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
        oracle_thresholds=payload["thresholds"],
        labels_snapshot=payload["benchmark"]["snapshot"],
        tiered_authorization=make_tiered_authorization_dict(),
    )

    # Construct RunMeta from integrity and policy
    run_meta = MockRunMeta(payload["integrity"], payload["policy"])

    # 3. Call decide_tiered_gate
    decision = decide_tiered_gate(metrics_map, config, run_meta)

    # 4. Verify outcomes for ALL SIX SCOPES across ALL AXES (Section 5 outcome pins)
    
    # (a) missense:pathogenic -> NO_CALLS/NOT_ESTIMABLE/BLOCKED/0-of-51/null/NO_CALLS/NOT_AUTHORIZED
    v_mp = decision.scopes["missense:pathogenic"]
    assert v_mp.data_sufficiency == "NO_CALLS"
    assert v_mp.conditional_performance == "NOT_ESTIMABLE"
    assert v_mp.policy_parity == "BLOCKED"
    assert v_mp.end_to_end_correct_call_coverage == "0/51"
    assert v_mp.precision_lb is None
    assert v_mp.recall_lb is None
    assert v_mp.scope_evidence_status == "NO_CALLS"
    assert v_mp.authorization_status == "NOT_AUTHORIZED"

    # (b) missense:benign -> UNDERPOWERED/NOT_ESTIMABLE/CLEAR/9-of-103/null/UNDERPOWERED/NOT_AUTHORIZED
    v_mb = decision.scopes["missense:benign"]
    assert v_mb.data_sufficiency == "UNDERPOWERED"
    assert v_mb.conditional_performance == "NOT_ESTIMABLE"
    assert v_mb.policy_parity == "CLEAR"
    assert v_mb.end_to_end_correct_call_coverage == "9/103"
    assert v_mb.precision_lb is None
    assert v_mb.recall_lb is None
    assert v_mb.scope_evidence_status == "UNDERPOWERED"
    assert v_mb.authorization_status == "NOT_AUTHORIZED"

    # (c) truncating:pathogenic -> ADEQUATE/MET/CLEAR/189-of-210/SUPPORTED_POSTHOC/PENDING_PROSPECTIVE
    v_tp = decision.scopes["truncating:pathogenic"]
    assert v_tp.data_sufficiency == "ADEQUATE"
    assert v_tp.conditional_performance == "MET"
    assert v_tp.policy_parity == "CLEAR"
    assert v_tp.end_to_end_correct_call_coverage == "189/210"
    assert v_tp.precision_lb == 0.9806713599320976
    assert v_tp.recall_lb == 0.9806713599320976
    assert v_tp.scope_evidence_status == "SUPPORTED_POSTHOC"
    assert v_tp.authorization_status == "PENDING_PROSPECTIVE"

    # (d) truncating:benign -> NO_CALLS/NOT_APPLICABLE/CLEAR/0-of-1/NOT_APPLICABLE/NOT_AUTHORIZED
    v_tb = decision.scopes["truncating:benign"]
    assert v_tb.data_sufficiency == "NO_CALLS"
    assert v_tb.conditional_performance == "NOT_APPLICABLE"
    assert v_tb.policy_parity == "CLEAR"
    assert v_tb.end_to_end_correct_call_coverage == "0/1"
    assert v_tb.precision_lb is None
    assert v_tb.recall_lb is None
    assert v_tb.scope_evidence_status == "NOT_APPLICABLE"
    assert v_tb.authorization_status == "NOT_AUTHORIZED"

    # (e) other:pathogenic -> ADEQUATE/NOT_APPLICABLE/CLEAR/89-of-117/NOT_APPLICABLE/NOT_AUTHORIZED
    v_op = decision.scopes["other:pathogenic"]
    assert v_op.data_sufficiency == "ADEQUATE"
    assert v_op.conditional_performance == "NOT_APPLICABLE"
    assert v_op.policy_parity == "CLEAR"
    assert v_op.end_to_end_correct_call_coverage == "89/117"
    assert v_op.precision_lb is None
    assert v_op.recall_lb is None
    assert v_op.scope_evidence_status == "NOT_APPLICABLE"
    assert v_op.authorization_status == "NOT_AUTHORIZED"

    # (f) other:benign -> ADEQUATE/NOT_APPLICABLE/CLEAR/112-of-2095/NOT_APPLICABLE/NOT_AUTHORIZED
    # (called 113, fp=1, assert correct coverage is 112/2095, never called/actual 113/2095)
    v_ob = decision.scopes["other:benign"]
    assert v_ob.data_sufficiency == "ADEQUATE"
    assert v_ob.conditional_performance == "NOT_APPLICABLE"
    assert v_ob.policy_parity == "CLEAR"
    assert v_ob.end_to_end_correct_call_coverage == "112/2095"
    assert v_ob.called_count == 113
    assert v_ob.tn == 112
    assert v_ob.fp == 1
    assert v_ob.precision_lb is None
    assert v_ob.recall_lb is None
    assert v_ob.scope_evidence_status == "NOT_APPLICABLE"
    assert v_ob.authorization_status == "NOT_AUTHORIZED"

    # 5. Verify aggregates and statements
    assert decision.full_spectrum_status == "NOT_VALIDATED"
    assert decision.full_spectrum_authorization == "NOT_AUTHORIZED"
    assert decision.research_scope_evidence_status == "SUPPORTED_POSTHOC"
    assert decision.research_scope_authorization == "PENDING_PROSPECTIVE"
    assert decision.research_scope_flags["truncating_pathogenic_research_scope_validated"] is False
    assert decision.governance_state == "RESEARCH_ONLY_NO_CLINICAL_USE"
    
    expected_gov_statement = (
        "This is a post-hoc re-adjudication of the frozen ADR-0012 "
        "masked-holdout counts for research evidence only; no scope is authorized, "
        "and this authorizes no clinical classification, VUS worklist, or ClinVar "
        "submission pending a prospective validation on unseen data."
    )
    assert decision.governance_statement == expected_gov_statement

    expected_no_new_evidence = (
        "No new evidence was generated: this record re-interprets the frozen R2 aggregate "
        "(source_canonical_lf_sha256 7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f) "
        "under the versioned tiered rule and performs no new run, scoring, annotation, "
        "benchmark read, network access, or data generation."
    )
    assert decision.no_new_evidence_statement == expected_no_new_evidence

    expected_disclaimer = "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission."
    assert decision.research_use_disclaimer == expected_disclaimer

    assert decision.prospective_validation_status == "PENDING"
    assert decision.source_content_hash == "2ead589d2f129f988d9932bb01153891902f0d675000554887a1524e567413b2"
    assert decision.source_canonical_lf_sha256 == "7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f"
    assert decision.post_hoc is True

    # 6. Verify record has NO field pinning its OWN canonical-LF file SHA
    record_dict = decision.__dict__ if hasattr(decision, "__dict__") else decision
    assert "canonical_lf_file_sha256" not in record_dict
    assert "file_sha256" not in record_dict

    # 7. Verify wrong-hash (CRLF e914... hash supplied as a canonical LF pin) is rejected
    wrong_lf_hash = "e914f65231c8004b1c7a96d2fe80bd49bac591433112699ff91cc5b027e55207"
    # Construct config with bad source hash
    bad_tiered_auth = make_tiered_authorization_dict()
    bad_tiered_auth["no_new_evidence_statement"] = (
        "No new evidence was generated: this record re-interprets the frozen R2 aggregate "
        f"(source_canonical_lf_sha256 {wrong_lf_hash}) "
        "under the versioned tiered rule and performs no new run..."
    )
    bad_config = EvalConfig(
        automatable_criteria=config.automatable_criteria,
        tavtigian_points=config.tavtigian_points,
        tavtigian_cutoffs=config.tavtigian_cutoffs,
        min_count_per_class=36,
        split=config.split,
        oracle_thresholds=config.oracle_thresholds,
        labels_snapshot=config.labels_snapshot,
        tiered_authorization=bad_tiered_auth,
    )
    # Raising InputError on wrong source hash pin vs calculation or incorrect calculation vs pin
    with pytest.raises(TieredReadjudicationInputError):
        # We supply the real metrics but passing the bad_config which claims the LF hash of R2 is the wrong_lf_hash.
        # Inside the code, it calculates 7c55... for the file, compares against the pin in config (which is e914...), and raises InputError.
        decide_tiered_gate(metrics_map, bad_config, run_meta)
