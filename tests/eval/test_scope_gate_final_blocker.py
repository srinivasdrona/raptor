import pytest
import json
from dataclasses import asdict
from conftest import make_eval_config, Metrics, with_point_estimate_lb
from raptor.eval.model import DirectionVerdict, ScopeGateDecision, GateDecision
from raptor.eval.report import EvalReport, report_to_dict
from raptor.eval.scope_gate import canonical_scope_gate_reason
from scripts.run_masked_holdout_eval import compute_report_scope_gate
from scripts.build_masked_holdout_gate_aggregate import build_aggregate_for_envelope, build_aggregate_v2


def make_v2_auth_config() -> dict:
    """Build the valid scope_authorization config block."""
    return {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": ["truncating:pathogenic"]
            }
        },
        "governance_statements": {
            "FULL_SPECTRUM": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
            "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
            "NONE_VALIDATED": "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
        }
    }


def make_oracle_thresholds() -> dict:
    return {
        "confidence": 0.95,
        "strata": {
            "missense": {
                "precision": 0.90,
                "recall": 0.85,
                "gating": True,
                "directions": ["pathogenic", "benign"]
            },
            "truncating": {
                "precision": 0.95,
                "recall": 0.95,
                "gating": True,
                "directions": ["pathogenic"]
            }
        }
    }


def test_runner_helper_skipped_pm1_preserves_validated_and_adds_blocker():
    """Test 1: A runner-helper test: skipped PM1 preserves truncating:pathogenic.scope_status == VALIDATED
    but adds explicit blocker and auth flags false/NONE_VALIDATED.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    # Missense fails
    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.75
    m_missense.recall_lb = 0.75
    m_missense.benign_precision_lb = 0.75
    m_missense.benign_recall_lb = 0.75

    # Truncating VALIDATED
    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}

    # Call runner-helper with skipped PM1
    decision = compute_report_scope_gate(metrics, cfg, skipped={"PM1"})

    assert isinstance(decision, ScopeGateDecision)
    # 1. Statistical status must be preserved
    assert decision.scopes["truncating:pathogenic"].scope_status == "VALIDATED"
    # 2. Explicit machine-readable authorization blockers
    assert "evaluation_skipped_criteria:PM1" in decision.authorization_blockers
    # 3. All auth flags/booleans false and governance state/disclaimer demoted
    assert decision.full_spectrum_vus_authorized is False
    assert decision.research_scope_flags["truncating_pathogenic_research_scope_validated"] is False
    assert decision.governance_state == "NONE_VALIDATED"
    assert decision.governance_statement == cfg.scope_authorization["governance_statements"]["NONE_VALIDATED"]


def test_round_trip_integration_with_skip():
    """Test 2: A full pure runner/report→aggregate round-trip with skip:
    succeeds (schema v2), scopes preserved, blocker serialized, all auth false, safe statement/disclaimer.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.75
    m_missense.recall_lb = 0.75
    m_missense.benign_precision_lb = 0.75
    m_missense.benign_recall_lb = 0.75

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}

    # Helper compute
    decision = compute_report_scope_gate(metrics, cfg, skipped={"PM1"})

    # Construct report
    report = EvalReport(
        run_id="run-test",
        generated_at="2026-07-15",
        labels_snapshot=cfg.labels_snapshot,
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5, "truncating": 2},
        metrics=metrics,
        gate=GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False),
        scope_gate=decision
    )

    # Config pins
    report.config_pins = {
        "bias_tsv_sha256": "bias",
        "manifest_sha256": "manifest",
        "mask_ledger_sha256": "ledger",
        "remask_audit_sha256": "remask",
        "return_manifest_sha256": "return",
        "predictor_correction_counts": {"PP3": 1, "BP4": 2},
        "operational_skipped_criteria": ["PM1", "PS4"],
        "evaluation_skipped_criteria": ["PM1"],
        "oracle_thresholds": make_oracle_thresholds(),
    }

    # Serialize envelope
    envelope = {
        "content_hash": report.content_hash(),
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": report_to_dict(report)
    }

    # build_aggregate_v2 / build_aggregate_for_envelope round-trip
    agg = build_aggregate_for_envelope(
        envelope,
        date="2026-07-15",
        terminal_json_hash="j",
        terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )

    # Asserts
    assert agg["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert agg["vus_authorized"] is False
    assert agg["scopes"]["truncating:pathogenic"]["scope_status"] == "VALIDATED"
    assert "evaluation_skipped_criteria:PM1" in agg["authorization_blockers"]
    assert agg["research_scope_flags"]["truncating_pathogenic_research_scope_validated"] is False
    assert agg["governance_state"] == "NONE_VALIDATED"
    assert agg["governance_statement"] == cfg.scope_authorization["governance_statements"]["NONE_VALIDATED"]


def test_tampered_skipped_envelope_with_auth_true_rejected():
    """Test 3: Tampered skipped envelope with auth true remains rejected.
    If the envelope claims any auth flag is True or governance_state is not NONE_VALIDATED
    while evaluation skips are present, build_aggregate_v2 must reject it.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.75
    m_missense.recall_lb = 0.75
    m_missense.benign_precision_lb = 0.75
    m_missense.benign_recall_lb = 0.75

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}

    decision = compute_report_scope_gate(metrics, cfg, skipped={"PM1"})

    # Tampering: force narrow flag to True despite the skip!
    decision.research_scope_flags["truncating_pathogenic_research_scope_validated"] = True
    decision.governance_state = "TRUNCATING_PATHOGENIC_ONLY"

    report = EvalReport(
        run_id="run-test",
        generated_at="2026-07-15",
        labels_snapshot=cfg.labels_snapshot,
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5, "truncating": 2},
        metrics=metrics,
        gate=GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False),
        scope_gate=decision
    )

    report.config_pins = {
        "bias_tsv_sha256": "bias",
        "manifest_sha256": "manifest",
        "mask_ledger_sha256": "ledger",
        "remask_audit_sha256": "remask",
        "return_manifest_sha256": "return",
        "predictor_correction_counts": {"PP3": 1, "BP4": 2},
        "operational_skipped_criteria": ["PM1", "PS4"],
        "evaluation_skipped_criteria": ["PM1"],
        "oracle_thresholds": make_oracle_thresholds(),
    }

    envelope = {
        "content_hash": report.content_hash(),
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": report_to_dict(report)
    }

    with pytest.raises(ValueError, match="integrity|tampered|skipped|authorization"):
        build_aggregate_v2(
            envelope,
            date="2026-07-15",
            terminal_json_hash="j",
            terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0},
            reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved",
        )


def test_tampered_skipped_envelope_missing_blocker_rejected():
    """Test 4: Tampered skipped envelope missing/wrong blocker is rejected
    if blocker field is part of chosen contract.
    If evaluation skips are present, but authorization_blockers is empty/missing
    or doesn't match the skip, it must be rejected.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.75
    m_missense.recall_lb = 0.75
    m_missense.benign_precision_lb = 0.75
    m_missense.benign_recall_lb = 0.75

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}

    decision = compute_report_scope_gate(metrics, cfg, skipped={"PM1"})

    # Tampering: clear/change the authorization blockers if it exists, or just verify it fails on missing
    if hasattr(decision, "authorization_blockers"):
        decision.authorization_blockers = []

    report = EvalReport(
        run_id="run-test",
        generated_at="2026-07-15",
        labels_snapshot=cfg.labels_snapshot,
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5, "truncating": 2},
        metrics=metrics,
        gate=GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False),
        scope_gate=decision
    )

    report.config_pins = {
        "bias_tsv_sha256": "bias",
        "manifest_sha256": "manifest",
        "mask_ledger_sha256": "ledger",
        "remask_audit_sha256": "remask",
        "return_manifest_sha256": "return",
        "predictor_correction_counts": {"PP3": 1, "BP4": 2},
        "operational_skipped_criteria": ["PM1", "PS4"],
        "evaluation_skipped_criteria": ["PM1"],
        "oracle_thresholds": make_oracle_thresholds(),
    }

    envelope = {
        "content_hash": report.content_hash(),
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": report_to_dict(report)
    }

    with pytest.raises(ValueError, match="integrity|tampered|skipped|blocker"):
        build_aggregate_v2(
            envelope,
            date="2026-07-15",
            terminal_json_hash="j",
            terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0},
            reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved",
        )


def test_no_skip_integration_succeeds_with_normal_validation():
    """Test 5: No-skip integration still succeeds with normal narrow validation.
    No skips are present, and truncating:pathogenic is VALIDATED.
    The narrow flag should be True and governance state should be TRUNCATING_PATHOGENIC_ONLY.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.75
    m_missense.recall_lb = 0.75
    m_missense.benign_precision_lb = 0.75
    m_missense.benign_recall_lb = 0.75

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}

    # Call with NO skips
    decision = compute_report_scope_gate(metrics, cfg, skipped=set())

    assert decision.research_scope_flags["truncating_pathogenic_research_scope_validated"] is True
    assert decision.governance_state == "TRUNCATING_PATHOGENIC_ONLY"

    report = EvalReport(
        run_id="run-test",
        generated_at="2026-07-15",
        labels_snapshot=cfg.labels_snapshot,
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5, "truncating": 2},
        metrics=metrics,
        gate=GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False),
        scope_gate=decision
    )

    report.config_pins = {
        "bias_tsv_sha256": "bias",
        "manifest_sha256": "manifest",
        "mask_ledger_sha256": "ledger",
        "remask_audit_sha256": "remask",
        "return_manifest_sha256": "return",
        "predictor_correction_counts": {"PP3": 1, "BP4": 2},
        "operational_skipped_criteria": ["PM1", "PS4"],
        "evaluation_skipped_criteria": [],
        "oracle_thresholds": make_oracle_thresholds(),
    }

    envelope = {
        "content_hash": report.content_hash(),
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": report_to_dict(report)
    }

    agg = build_aggregate_v2(
        envelope,
        date="2026-07-15",
        terminal_json_hash="j",
        terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )

    assert agg["vus_authorized"] is False
    assert agg["research_scope_flags"]["truncating_pathogenic_research_scope_validated"] is True
    assert agg["governance_state"] == "TRUNCATING_PATHOGENIC_ONLY"
    assert agg["governance_statement"] == cfg.scope_authorization["governance_statements"]["TRUNCATING_PATHOGENIC_ONLY"]


def test_require_canonical_parity_block_reason():
    """Verify compute_report_scope_gate with skipped criteria uses canonical reasoning."""
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    # Missense fails (lower bound < threshold)
    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.75
    m_missense.recall_lb = 0.75
    m_missense.benign_precision_lb = 0.75
    m_missense.benign_recall_lb = 0.75

    # Truncating VALIDATED (lower bound >= threshold)
    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}

    # 1. Call runner-helper with skipped PM1
    decision = compute_report_scope_gate(metrics, cfg, skipped={"PM1"})

    # Determine canonical reason
    scope_statuses = {key: verdict.scope_status for key, verdict in decision.scopes.items()}
    expected_canonical_reason = canonical_scope_gate_reason(scope_statuses, decision.authorization_blockers)

    # Assert decision.reason exactly equals the canonical reason
    assert decision.reason == expected_canonical_reason

    # 2. Serialize/report -> aggregate and assert aggregate scope_gate_reason equals the same exact canonical reason
    report = EvalReport(
        run_id="run-test",
        generated_at="2026-07-15",
        labels_snapshot=cfg.labels_snapshot,
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5, "truncating": 2},
        metrics=metrics,
        gate=GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False),
        scope_gate=decision
    )

    report.config_pins = {
        "bias_tsv_sha256": "bias",
        "manifest_sha256": "manifest",
        "mask_ledger_sha256": "ledger",
        "remask_audit_sha256": "remask",
        "return_manifest_sha256": "return",
        "predictor_correction_counts": {"PP3": 1, "BP4": 2},
        "operational_skipped_criteria": ["PM1", "PS4"],
        "evaluation_skipped_criteria": ["PM1"],
        "oracle_thresholds": make_oracle_thresholds(),
    }

    envelope = {
        "content_hash": report.content_hash(),
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": report_to_dict(report)
    }

    agg = build_aggregate_for_envelope(
        envelope,
        date="2026-07-15",
        terminal_json_hash="j",
        terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )

    assert agg["scope_gate_reason"] == expected_canonical_reason

    # 3. Assert reason includes blocker and sorted scope status summary; no old freeform phrase
    assert "evaluation_skipped_criteria:PM1" in expected_canonical_reason
    assert "missense:benign=UNMET" in expected_canonical_reason
    assert "missense:pathogenic=UNMET" in expected_canonical_reason
    assert "truncating:pathogenic=VALIDATED" in expected_canonical_reason
    assert "all scope metric thresholds may have passed" not in decision.reason
    assert "exclusions" not in decision.reason

    # 4. No-skip reason remains canonical too
    decision_no_skip = compute_report_scope_gate(metrics, cfg, skipped=set())
    no_skip_statuses = {key: verdict.scope_status for key, verdict in decision_no_skip.scopes.items()}
    expected_no_skip_reason = canonical_scope_gate_reason(no_skip_statuses, decision_no_skip.authorization_blockers)
    assert decision_no_skip.reason == expected_no_skip_reason

