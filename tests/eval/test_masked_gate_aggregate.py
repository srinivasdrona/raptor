from __future__ import annotations

from scripts.build_masked_holdout_gate_aggregate import build_aggregate, build_aggregate_v2


def _get_consistent_scope(scope_key: str, scope_status: str) -> dict:
    stratum, _, direction = scope_key.partition(":")
    
    # default thresholds based on real config
    if stratum == "missense":
        p_thresh, r_thresh = 0.90, 0.85
    elif stratum == "truncating" and direction == "pathogenic":
        p_thresh, r_thresh = 0.95, 0.95
    else:
        p_thresh, r_thresh = None, None
        
    if scope_status == "VALIDATED":
        precision_lb = p_thresh if p_thresh is not None else 0.96
        recall_lb = r_thresh if r_thresh is not None else 0.96
        actual_count, called_count = 40, 40
        coverage_adequate = True
        metric_status = "MET"
    elif scope_status == "UNDERPOWERED":
        precision_lb = p_thresh if p_thresh is not None else 0.96
        recall_lb = r_thresh if r_thresh is not None else 0.96
        actual_count, called_count = 10, 10
        coverage_adequate = False
        metric_status = "MET"
    elif scope_status == "FAIL":
        precision_lb = 0.5
        recall_lb = 0.5
        actual_count, called_count = 40, 40
        coverage_adequate = True
        metric_status = "UNMET"
    else:  # DESCRIPTIVE / NO_THRESHOLD
        precision_lb = 0.0
        recall_lb = 0.0
        actual_count, called_count = 1, 1
        coverage_adequate = False
        metric_status = "NO_THRESHOLD"
        p_thresh, r_thresh = None, None
        
    return {
        "stratum": stratum,
        "direction": direction,
        "precision_lb": precision_lb,
        "recall_lb": recall_lb,
        "precision_threshold": p_thresh,
        "recall_threshold": r_thresh,
        "actual_count": actual_count,
        "called_count": called_count,
        "min_count": 36,
        "coverage_adequate": coverage_adequate,
        "metric_status": metric_status,
        "scope_status": scope_status,
        "reasons": []
    }


def test_gate_aggregate_is_derived_from_terminal_envelope() -> None:
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {
            "removed_count": 2,
            "zero_survivors": True,
        },
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {
                "status": "FAIL",
                "stratum": "missense",
                "reason": "below threshold",
                "vus_authorized": False,
                "per_stratum": {},
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": ["PM1"],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    aggregate = build_aggregate(
        envelope,
        date="2026-07-13",
        terminal_json_hash="json",
        terminal_report_hash="text",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )
    assert aggregate["status"] == "FAIL"
    assert aggregate["metrics"] == envelope["report"]["metrics"]
    assert aggregate["policy"]["pm1_status"] == "SKIPPED_ZERO_SUPPORT_BASELINE_MISMATCH"
    assert aggregate["integrity"]["returned_artifacts_verified"] == 2
    assert aggregate["external_report_hashes"]["MASKED_EVAL_REPORT.json"] == "json"


def test_e1_v2_schema_and_scope_specific_primary() -> None:
    """E1 v2 schema + scope-specific primary:
    - schema == "raptor.tsc.masked_holdout_gate.v2"
    - contains scopes, research_scope_flags, governance_statement, research_use_disclaimer
    - metrics are retained (descriptive-only)
    - vus_authorized == full_spectrum_vus_authorized
    """
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {
            "removed_count": 2,
            "zero_survivors": True,
        },
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {
                "status": "FAIL",
                "stratum": "missense",
                "reason": "below threshold",
                "vus_authorized": False,
                "per_stratum": {},
            },
            # v2 scope_gate decision in report
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "PASS",
                "full_spectrum_vus_authorized": True,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "FULL_SPECTRUM",
                "governance_statement": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "reason": "all validated",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
                    "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                # No evaluation-only criteria skipped in this fixture -- this test
                # exercises v2 schema shape/authorization derivation, not the
                # separate parity-skip enforcement rule (see the dedicated
                # blocker_1a/1b/1c and finding_4 tests below for that).
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    aggregate = build_aggregate_v2(
        envelope,
        date="2026-07-14",
        terminal_json_hash="json",
        terminal_report_hash="text",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )

    assert aggregate["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert aggregate["full_spectrum_status"] == "PASS"
    assert "status" not in aggregate
    assert "binding_stratum" not in aggregate
    assert aggregate["vus_authorized"] is True  # because full_spectrum_vus_authorized is True
    assert aggregate["research_scope_flags"] == {"truncating_pathogenic_research_scope_validated": True}
    assert aggregate["governance_statement"] == "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission."
    assert aggregate["research_use_disclaimer"] == "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission."
    assert "scopes" in aggregate
    assert aggregate["scopes"]["missense:pathogenic"] == _get_consistent_scope("missense:pathogenic", "VALIDATED")
    assert "metrics" in aggregate  # descriptive-only


def test_e2_partial_to_full_spectrum_false() -> None:
    """E2 partial -> full-spectrum false:
    - truncating validated, missense not
    - aggregate vus_authorized is False
    - research_scope_flags.truncating flag is True
    - governance statement matches TRUNCATING_PATHOGENIC_ONLY verbatim
    - research_use_disclaimer is correct
    """
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {
            "removed_count": 2,
            "zero_survivors": True,
        },
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {
                "status": "FAIL",
                "stratum": "missense",
                "reason": "below threshold",
                "vus_authorized": False,
                "per_stratum": {},
            },
            # v2 scope_gate decision in report
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "FAIL",
                "full_spectrum_vus_authorized": False,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "TRUNCATING_PATHOGENIC_ONLY",
                "governance_statement": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
                "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "reason": "truncating validated but missense failed",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
                    "missense:benign": _get_consistent_scope("missense:benign", "FAIL"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                # No evaluation-only criteria skipped in this fixture -- this test
                # exercises v2 partial-authorization derivation, not the separate
                # parity-skip enforcement rule (see the dedicated blocker_1a/1b/1c
                # and finding_4 tests below for that).
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    aggregate = build_aggregate_v2(
        envelope,
        date="2026-07-14",
        terminal_json_hash="json",
        terminal_report_hash="text",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )

    assert aggregate["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert aggregate["full_spectrum_status"] == "FAIL"
    assert "status" not in aggregate
    assert "binding_stratum" not in aggregate
    assert aggregate["vus_authorized"] is False  # because full_spectrum_vus_authorized is False
    assert aggregate["research_scope_flags"] == {"truncating_pathogenic_research_scope_validated": True}
    assert aggregate["governance_statement"] == "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated."
    assert aggregate["research_use_disclaimer"] == "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission."


# =========================================================================
# RED REGRESSION TESTS FOR GPT-5.4 FINDINGS
# =========================================================================

def test_finding_4_build_aggregate_v2_rejects_inconsistent_envelope() -> None:
    """Finding 4 [High]: build_aggregate_v2 must raise ValueError/explicit integrity
    error when passed an inconsistent/tampered envelope.
    """
    def make_base_envelope(scope_gate_overrides: dict) -> dict:
        scope_gate = {
            "schema_version": "2",
            "full_spectrum_status": "PASS",
            "full_spectrum_vus_authorized": True,
            "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
            "governance_state": "FULL_SPECTRUM",
            "governance_statement": "statement",
            "research_use_disclaimer": "disclaimer",
            "reason": "reason",
            "scopes": {
                "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
                "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
                "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
            }
        }
        scope_gate.update(scope_gate_overrides)
        return {
            "content_hash": "content",
            "predictor_policy": {"status": "approved"},
            "mask_attestation": {"removed_count": 2, "zero_survivors": True},
            "lineage_audit": {"effective_blocking_criteria": []},
            "verified_return_artifacts": {"a": "hash", "b": "hash"},
            "report": {
                "labels_snapshot": "snapshot",
                "benchmark_size": 3,
                "train_dev_size": 1,
                "holdout_size": 2,
                "holdout_label_counts": {"P": 1, "B": 1},
                "holdout_class_counts": {"missense": 2},
                "metrics": {"missense": {"precision": 0.5}},
                "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
                "scope_gate": scope_gate,
                "config_pins": {
                    "bias_tsv_sha256": "bias",
                    "manifest_sha256": "manifest",
                    "mask_ledger_sha256": "ledger",
                    "remask_audit_sha256": "remask",
                    "return_manifest_sha256": "return",
                    "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                    "operational_skipped_criteria": ["PM1", "PS4"],
                    "evaluation_skipped_criteria": [],
                    "oracle_thresholds": {"confidence": 0.95},
                },
            },
        }

    # Case A: full_spectrum_vus_authorized=True but a required scope is FAIL
    env_a = make_base_envelope({
        "full_spectrum_vus_authorized": True,
        "scopes": {
            "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
            "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
            "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
        }
    })
    import pytest
    with pytest.raises((ValueError, AssertionError), match="inconsistent|tampered|integrity"):
        build_aggregate_v2(
            env_a, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case B: narrow truncating flag is True when truncating scope failed
    env_b = make_base_envelope({
        "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
        "scopes": {
            "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
            "missense:benign": _get_consistent_scope("missense:benign", "FAIL"),
            "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "FAIL"),
        }
    })
    with pytest.raises((ValueError, AssertionError), match="inconsistent|tampered|integrity"):
        build_aggregate_v2(
            env_b, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case C: full_spectrum_status PASS but full_spectrum_vus_authorized is False
    env_c = make_base_envelope({
        "full_spectrum_status": "PASS",
        "full_spectrum_vus_authorized": False
    })
    with pytest.raises((ValueError, AssertionError), match="inconsistent|tampered|integrity"):
        build_aggregate_v2(
            env_c, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_finding_4_build_aggregate_v2_rejects_skipped_criteria_with_authorization() -> None:
    """Finding 4 [High]: An envelope with evaluation_skipped_criteria nonempty
    and any scope/full-spectrum authorization true must raise ValueError or demote,
    never publish authorization (parity break).
    """
    env = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "FAIL",
                "full_spectrum_vus_authorized": False,
                # Here, we have a research scope authorized (True)
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "TRUNCATING_PATHOGENIC_ONLY",
                "governance_statement": "statement",
                "research_use_disclaimer": "disclaimer",
                "reason": "reason",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
                    "missense:benign": _get_consistent_scope("missense:benign", "FAIL"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                # NON-EMPTY evaluation skipped criteria (parity break!)
                "evaluation_skipped_criteria": ["PM1"],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    import pytest
    # Since we have a parity break (evaluation_skipped_criteria is nonempty) and authorization is True,
    # build_aggregate_v2 must raise ValueError or demote/reject.
    with pytest.raises((ValueError, AssertionError), match="parity break|skipped|inconsistent"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


# =========================================================================
# ADDITIONAL GEMINI 3.5 FLASH RED REGRESSION TESTS FOR FINAL GATE BLOCKERS
# =========================================================================

def test_blocker_1a_skips_nonempty_narrow_true_fails() -> None:
    """Blocker 1a: report.config_pins.evaluation_skipped_criteria is nonempty,
    and a narrow research flag would otherwise be true (TRUNCATING_PATHOGENIC_ONLY).
    This must fail loud by raising ValueError/explicit integrity error.
    """
    from raptor.eval.config import (
        _PINNED_GOVERNANCE_STATEMENTS,
        _PINNED_RESEARCH_USE_DISCLAIMER,
    )
    
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "FAIL",
                "full_spectrum_vus_authorized": False,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "TRUNCATING_PATHOGENIC_ONLY",
                "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["TRUNCATING_PATHOGENIC_ONLY"],
                "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
                "reason": "truncating validated",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
                    "missense:benign": _get_consistent_scope("missense:benign", "FAIL"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": ["PM1"],  # NON-EMPTY SKIP!
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    import pytest
    with pytest.raises((ValueError, AssertionError), match="skipped|parity|authorization"):
        build_aggregate_v2(
            envelope, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_1b_skips_nonempty_full_spectrum_true_fails() -> None:
    """Blocker 1b: report.config_pins.evaluation_skipped_criteria is nonempty,
    and full-spectrum authorization would otherwise be true.
    This must fail loud by raising ValueError/explicit integrity error.
    """
    from raptor.eval.config import (
        _PINNED_GOVERNANCE_STATEMENTS,
        _PINNED_RESEARCH_USE_DISCLAIMER,
    )
    
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "PASS",
                "full_spectrum_vus_authorized": True,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "FULL_SPECTRUM",
                "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["FULL_SPECTRUM"],
                "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
                "reason": "all validated",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
                    "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": ["PM1"],  # NON-EMPTY SKIP!
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    import pytest
    with pytest.raises((ValueError, AssertionError), match="skipped|parity|authorization"):
        build_aggregate_v2(
            envelope, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_1c_skips_nonempty_no_authorization_succeeds() -> None:
    """Blocker 1c: report.config_pins.evaluation_skipped_criteria is nonempty,
    but no authorization is true (NONE_VALIDATED state). This must succeed
    and publish.
    """
    from raptor.eval.config import (
        _PINNED_GOVERNANCE_STATEMENTS,
        _PINNED_RESEARCH_USE_DISCLAIMER,
    )
    
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "FAIL",
                "full_spectrum_vus_authorized": False,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": False},
                "governance_state": "NONE_VALIDATED",
                "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["NONE_VALIDATED"],
                "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
                "reason": "none validated",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
                    "missense:benign": _get_consistent_scope("missense:benign", "FAIL"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "FAIL"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": ["PM1"],  # NON-EMPTY SKIP!
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    # This should succeed since there is no active authorization
    agg = build_aggregate_v2(
        envelope, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    assert agg["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert agg["vus_authorized"] is False
    assert agg["research_scope_flags"]["truncating_pathogenic_research_scope_validated"] is False


def test_blocker_2a_missing_scope_raises_error() -> None:
    """Blocker 2a: All pinned full-spectrum scopes must be present.
    Missing any of them (e.g. missense:pathogenic or missense:benign or truncating:pathogenic)
    must raise ValueError or explicit integrity error.
    """
    from raptor.eval.config import (
        _PINNED_GOVERNANCE_STATEMENTS,
        _PINNED_RESEARCH_USE_DISCLAIMER,
    )
    
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "FAIL",
                "full_spectrum_vus_authorized": False,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "TRUNCATING_PATHOGENIC_ONLY",
                "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["TRUNCATING_PATHOGENIC_ONLY"],
                "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
                "reason": "missing scopes",
                "scopes": {
                    # Missing missense:pathogenic and missense:benign entirely!
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    import pytest
    with pytest.raises((ValueError, AssertionError), match="scopes|missing|integrity"):
        build_aggregate_v2(
            envelope, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_2b_status_mismatch_fail_vs_underpowered() -> None:
    """Blocker 2b: missense:pathogenic is FAIL, but envelope says UNDERPOWERED.
    Must raise ValueError / reject.
    """
    from raptor.eval.config import (
        _PINNED_GOVERNANCE_STATEMENTS,
        _PINNED_RESEARCH_USE_DISCLAIMER,
    )
    
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "UNDERPOWERED",  # MISMATCH! Recomputation must say FAIL because missense:pathogenic is FAIL.
                "full_spectrum_vus_authorized": False,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "TRUNCATING_PATHOGENIC_ONLY",
                "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["TRUNCATING_PATHOGENIC_ONLY"],
                "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
                "reason": "one is fail",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
                    "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    import pytest
    with pytest.raises((ValueError, AssertionError), match="status|mismatch|integrity"):
        build_aggregate_v2(
            envelope, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_2b_status_mismatch_underpowered_vs_fail() -> None:
    """Blocker 2b: missense:pathogenic is UNDERPOWERED, but envelope says FAIL.
    Must raise ValueError / reject.
    """
    from raptor.eval.config import (
        _PINNED_GOVERNANCE_STATEMENTS,
        _PINNED_RESEARCH_USE_DISCLAIMER,
    )
    
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "FAIL",  # MISMATCH! Recomputed must be UNDERPOWERED (no FAIL is present).
                "full_spectrum_vus_authorized": False,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "TRUNCATING_PATHOGENIC_ONLY",
                "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["TRUNCATING_PATHOGENIC_ONLY"],
                "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
                "reason": "mixed underpowered",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "UNDERPOWERED"),
                    "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    import pytest
    with pytest.raises((ValueError, AssertionError), match="status|mismatch|integrity"):
        build_aggregate_v2(
            envelope, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_2c_status_mismatch_validated_vs_fail() -> None:
    """Blocker 2c: All required scopes validated (PASS), but envelope says FAIL/UNDERPOWERED.
    Must raise ValueError / reject.
    """
    from raptor.eval.config import (
        _PINNED_GOVERNANCE_STATEMENTS,
        _PINNED_RESEARCH_USE_DISCLAIMER,
    )
    
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "FAIL",  # MISMATCH! All required VALIDATED => recomputed status should be PASS.
                "full_spectrum_vus_authorized": True,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "FULL_SPECTRUM",
                "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["FULL_SPECTRUM"],
                "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
                "reason": "all validated",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
                    "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    import pytest
    with pytest.raises((ValueError, AssertionError), match="status|mismatch|integrity"):
        build_aggregate_v2(
            envelope, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_2d_valid_mixed_status_underpowered_builds() -> None:
    """Blocker 2d: Mixed scopes with one UNDERPOWERED and no FAIL should recompute
    to UNDERPOWERED and build successfully if matched.
    """
    from raptor.eval.config import (
        _PINNED_GOVERNANCE_STATEMENTS,
        _PINNED_RESEARCH_USE_DISCLAIMER,
    )
    
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "UNDERPOWERED",  # MATCHES expected recomputed status (no FAIL, but not all VALIDATED)
                "full_spectrum_vus_authorized": False,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "TRUNCATING_PATHOGENIC_ONLY",
                "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["TRUNCATING_PATHOGENIC_ONLY"],
                "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
                "reason": "underpowered scope present",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "UNDERPOWERED"),
                    "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    # Since mixed UNDERPOWERED matched correctly, this must build successfully.
    agg = build_aggregate_v2(
        envelope, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    assert agg["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert agg["full_spectrum_status"] == "UNDERPOWERED"


def test_blocker_3_dispatch_helper_build_aggregate_for_envelope() -> None:
    """Blocker 3: Test that build_aggregate_for_envelope dispatches to build_aggregate_v2
    or build_aggregate depending on the presence of scope_gate.
    """
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_for_envelope

    # 1. Envelope with non-null scope_gate should yield v2 schema
    envelope_v2 = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "PASS",
                "full_spectrum_vus_authorized": True,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "FULL_SPECTRUM",
                "governance_statement": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "reason": "reason",
                "scopes": {
                    "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
                    "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
                    "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
                }
            },
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    res_v2 = build_aggregate_for_envelope(
        envelope_v2,
        date="2026-07-14",
        terminal_json_hash="j",
        terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )
    assert res_v2["schema"] == "raptor.tsc.masked_holdout_gate.v2"

    # 2. Envelope with no scope_gate should yield v1 schema
    envelope_v1 = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 3,
            "train_dev_size": 1,
            "holdout_size": 2,
            "holdout_label_counts": {"P": 1, "B": 1},
            "holdout_class_counts": {"missense": 2},
            "metrics": {"missense": {"precision": 0.5}},
            "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": ["PM1"],
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    res_v1 = build_aggregate_for_envelope(
        envelope_v1,
        date="2026-07-14",
        terminal_json_hash="j",
        terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )
    assert res_v1["schema"] == "raptor.tsc.masked_holdout_gate.v1"


def test_blocker_1_aggregate_trusts_forged_scope_status() -> None:
    """Blocker 1 [RED TEST]: build_aggregate_v2 must independently validate
    every scope's metric_status, coverage_adequate, and scope_status consistency
    against the underlying numeric/axis fields, rather than trusting the
    envelope-supplied scope_status at face value.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    def make_envelope(scopes_payload: dict, evaluation_skipped: list = None) -> dict:
        return {
            "content_hash": "content",
            "predictor_policy": {"status": "approved"},
            "mask_attestation": {"removed_count": 2, "zero_survivors": True},
            "lineage_audit": {"effective_blocking_criteria": []},
            "verified_return_artifacts": {"a": "hash", "b": "hash"},
            "report": {
                "labels_snapshot": "snapshot",
                "benchmark_size": 3,
                "train_dev_size": 1,
                "holdout_size": 2,
                "holdout_label_counts": {"P": 1, "B": 1},
                "holdout_class_counts": {"missense": 2},
                "metrics": {"missense": {"precision": 0.5}},
                "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
                "scope_gate": {
                    "schema_version": "2",
                    "full_spectrum_status": "PASS" if all(s.get("scope_status") == "VALIDATED" for s in scopes_payload.values()) else "FAIL",
                    "full_spectrum_vus_authorized": all(s.get("scope_status") == "VALIDATED" for s in scopes_payload.values()),
                    "research_scope_flags": {"truncating_pathogenic_research_scope_validated": scopes_payload.get("truncating:pathogenic", {}).get("scope_status") == "VALIDATED"},
                    "governance_state": "FULL_SPECTRUM" if all(s.get("scope_status") == "VALIDATED" for s in scopes_payload.values()) else "NONE_VALIDATED",
                    "governance_statement": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                    "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                    "reason": "reason",
                    "scopes": scopes_payload
                },
                "config_pins": {
                    "bias_tsv_sha256": "bias",
                    "manifest_sha256": "manifest",
                    "mask_ledger_sha256": "ledger",
                    "remask_audit_sha256": "remask",
                    "return_manifest_sha256": "return",
                    "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                    "operational_skipped_criteria": ["PM1", "PS4"],
                    "evaluation_skipped_criteria": evaluation_skipped or [],
                    "oracle_thresholds": {
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
                    },
                },
            },
        }

    # Helper to generate a baseline valid passing scope dictionary
    def get_valid_scopes():
        return {
            "missense:pathogenic": {
                "stratum": "missense",
                "direction": "pathogenic",
                "precision_lb": 0.92,
                "recall_lb": 0.87,
                "precision_threshold": 0.90,
                "recall_threshold": 0.85,
                "actual_count": 40,
                "called_count": 40,
                "min_count": 36,
                "coverage_adequate": True,
                "metric_status": "MET",
                "scope_status": "VALIDATED",
                "reasons": []
            },
            "missense:benign": {
                "stratum": "missense",
                "direction": "benign",
                "precision_lb": 0.92,
                "recall_lb": 0.87,
                "precision_threshold": 0.90,
                "recall_threshold": 0.85,
                "actual_count": 40,
                "called_count": 40,
                "min_count": 36,
                "coverage_adequate": True,
                "metric_status": "MET",
                "scope_status": "VALIDATED",
                "reasons": []
            },
            "truncating:pathogenic": {
                "stratum": "truncating",
                "direction": "pathogenic",
                "precision_lb": 0.96,
                "recall_lb": 0.96,
                "precision_threshold": 0.95,
                "recall_threshold": 0.95,
                "actual_count": 40,
                "called_count": 40,
                "min_count": 36,
                "coverage_adequate": True,
                "metric_status": "MET",
                "scope_status": "VALIDATED",
                "reasons": []
            }
        }

    # 1. Genuine / valid envelope still builds successfully.
    genuine_scopes = get_valid_scopes()
    genuine_env = make_envelope(genuine_scopes)
    agg = build_aggregate_v2(
        genuine_env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    assert agg["full_spectrum_status"] == "PASS"

    # 2. Forge 1: Forge only scope_status to VALIDATED for required missense scope,
    # but keep its metric_status UNMET / low lower bounds.
    forged_scopes_1 = get_valid_scopes()
    forged_scopes_1["missense:pathogenic"].update({
        "precision_lb": 0.75,
        "recall_lb": 0.75,
        "metric_status": "UNMET",
        "scope_status": "VALIDATED"  # FORGED!
    })
    forged_env_1 = make_envelope(forged_scopes_1)
    with pytest.raises(ValueError, match="integrity|forged|tampered|inconsistent"):
        build_aggregate_v2(
            forged_env_1, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # 3. Forge 2: Forge scope_status=VALIDATED with metric_status MET but coverage_adequate False.
    forged_scopes_2 = get_valid_scopes()
    forged_scopes_2["missense:pathogenic"].update({
        "actual_count": 10,
        "called_count": 10,
        "coverage_adequate": False,
        "scope_status": "VALIDATED"  # FORGED!
    })
    forged_env_2 = make_envelope(forged_scopes_2)
    with pytest.raises(ValueError, match="integrity|forged|tampered|inconsistent"):
        build_aggregate_v2(
            forged_env_2, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # 4. Forge 3: Forge inconsistent combinations.
    # Case A: NO_THRESHOLD must map to DESCRIPTIVE. Forge to VALIDATED.
    forged_scopes_3a = get_valid_scopes()
    # Add a mock "truncating:benign" with NO_THRESHOLD but forged scope_status "VALIDATED"
    forged_scopes_3a["truncating:benign"] = {
        "stratum": "truncating",
        "direction": "benign",
        "precision_lb": 0.0,
        "recall_lb": 0.0,
        "precision_threshold": None,
        "recall_threshold": None,
        "actual_count": 1,
        "called_count": 1,
        "min_count": 36,
        "coverage_adequate": False,
        "metric_status": "NO_THRESHOLD",
        "scope_status": "VALIDATED",  # FORGED!
        "reasons": []
    }
    forged_env_3a = make_envelope(forged_scopes_3a)
    with pytest.raises(ValueError, match="integrity|forged|tampered|inconsistent"):
        build_aggregate_v2(
            forged_env_3a, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case B: MET + adequate => VALIDATED. Forge to UNDERPOWERED.
    forged_scopes_3b = get_valid_scopes()
    forged_scopes_3b["missense:pathogenic"].update({
        "scope_status": "UNDERPOWERED"  # Inconsistent: MET + adequate must be VALIDATED
    })
    forged_env_3b = make_envelope(forged_scopes_3b)
    with pytest.raises(ValueError, match="integrity|forged|tampered|inconsistent"):
        build_aggregate_v2(
            forged_env_3b, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case C: MET + inadequate => UNDERPOWERED. Forge to VALIDATED.
    forged_scopes_3c = get_valid_scopes()
    forged_scopes_3c["missense:pathogenic"].update({
        "actual_count": 10,
        "called_count": 10,
        "coverage_adequate": False,
        "metric_status": "MET",
        "scope_status": "VALIDATED"  # FORGED! MET + inadequate must be UNDERPOWERED
    })
    forged_env_3c = make_envelope(forged_scopes_3c)
    with pytest.raises(ValueError, match="integrity|forged|tampered|inconsistent"):
        build_aggregate_v2(
            forged_env_3c, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case D: UNMET => FAIL regardless of coverage. Forge to UNDERPOWERED.
    forged_scopes_3d = get_valid_scopes()
    forged_scopes_3d["missense:pathogenic"].update({
        "precision_lb": 0.75,
        "recall_lb": 0.75,
        "actual_count": 10,
        "called_count": 10,
        "coverage_adequate": False,
        "metric_status": "UNMET",
        "scope_status": "UNDERPOWERED"  # FORGED! UNMET must map to FAIL
    })
    forged_env_3d = make_envelope(forged_scopes_3d)
    with pytest.raises(ValueError, match="integrity|forged|tampered|inconsistent"):
        build_aggregate_v2(
            forged_env_3d, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # 5. Axis verification (bounds vs metric_status/scope_status):
    # Attacker forges metric_status=MET and scope_status=VALIDATED while numeric LB remains below threshold.
    forged_scopes_4 = get_valid_scopes()
    forged_scopes_4["missense:pathogenic"].update({
        "precision_lb": 0.75,       # BELOW THRESHOLD (0.90)!
        "recall_lb": 0.87,
        "metric_status": "MET",     # FORGED metric_status!
        "scope_status": "VALIDATED" # FORGED scope_status!
    })
    forged_env_4 = make_envelope(forged_scopes_4)
    with pytest.raises(ValueError, match="integrity|forged|tampered|inconsistent"):
        build_aggregate_v2(
            forged_env_4, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_regression_require_complete_v2_scope_evidence() -> None:
    """GPT-5.4 Blocker RED regression test: every required v2 scope entry
    must contain the complete serialized DirectionVerdict payload.
    Minimal entries or entries with missing fields must raise ValueError.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    from raptor.eval.config import (
        _PINNED_GOVERNANCE_STATEMENTS,
        _PINNED_RESEARCH_USE_DISCLAIMER,
    )

    def make_envelope(scopes_payload: dict) -> dict:
        return {
            "content_hash": "content",
            "predictor_policy": {"status": "approved"},
            "mask_attestation": {"removed_count": 2, "zero_survivors": True},
            "lineage_audit": {"effective_blocking_criteria": []},
            "verified_return_artifacts": {"a": "hash", "b": "hash"},
            "report": {
                "labels_snapshot": "snapshot",
                "benchmark_size": 3,
                "train_dev_size": 1,
                "holdout_size": 2,
                "holdout_label_counts": {"P": 1, "B": 1},
                "holdout_class_counts": {"missense": 2},
                "metrics": {"missense": {"precision": 0.5}},
                "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
                "scope_gate": {
                    "schema_version": "2",
                    "full_spectrum_status": "PASS",
                    "full_spectrum_vus_authorized": True,
                    "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                    "governance_state": "FULL_SPECTRUM",
                    "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["FULL_SPECTRUM"],
                    "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
                    "reason": "all validated",
                    "scopes": scopes_payload
                },
                "config_pins": {
                    "bias_tsv_sha256": "bias",
                    "manifest_sha256": "manifest",
                    "mask_ledger_sha256": "ledger",
                    "remask_audit_sha256": "remask",
                    "return_manifest_sha256": "return",
                    "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                    "operational_skipped_criteria": ["PM1", "PS4"],
                    "evaluation_skipped_criteria": [],
                    "oracle_thresholds": {
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
                    },
                },
            }
        }

    def get_valid_scopes():
        return {
            "missense:pathogenic": {
                "stratum": "missense",
                "direction": "pathogenic",
                "precision_lb": 0.92,
                "recall_lb": 0.87,
                "precision_threshold": 0.90,
                "recall_threshold": 0.85,
                "actual_count": 40,
                "called_count": 40,
                "min_count": 36,
                "coverage_adequate": True,
                "metric_status": "MET",
                "scope_status": "VALIDATED",
                "reasons": []
            },
            "missense:benign": {
                "stratum": "missense",
                "direction": "benign",
                "precision_lb": 0.92,
                "recall_lb": 0.87,
                "precision_threshold": 0.90,
                "recall_threshold": 0.85,
                "actual_count": 40,
                "called_count": 40,
                "min_count": 36,
                "coverage_adequate": True,
                "metric_status": "MET",
                "scope_status": "VALIDATED",
                "reasons": []
            },
            "truncating:pathogenic": {
                "stratum": "truncating",
                "direction": "pathogenic",
                "precision_lb": 0.96,
                "recall_lb": 0.96,
                "precision_threshold": 0.95,
                "recall_threshold": 0.95,
                "actual_count": 40,
                "called_count": 40,
                "min_count": 36,
                "coverage_adequate": True,
                "metric_status": "MET",
                "scope_status": "VALIDATED",
                "reasons": []
            }
        }

    # 1. Minimal entry: only {"scope_status": "VALIDATED"}
    # This must raise ValueError, but currently doesn't (bypasses).
    minimal_scopes = {
        "missense:pathogenic": {"scope_status": "VALIDATED"},
        "missense:benign": {"scope_status": "VALIDATED"},
        "truncating:pathogenic": {"scope_status": "VALIDATED"}
    }
    with pytest.raises(ValueError, match="integrity|complete|missing|invalid"):
        build_aggregate_v2(
            make_envelope(minimal_scopes),
            date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # 2. Cover missing subsets of required fields
    required_fields = [
        "precision_lb", "recall_lb", "precision_threshold", "recall_threshold",
        "actual_count", "called_count", "min_count", "coverage_adequate", "metric_status",
        "stratum", "direction", "reasons"
    ]
    
    for field in required_fields:
        scopes = get_valid_scopes()
        # Delete required field from one scope
        del scopes["missense:pathogenic"][field]
        with pytest.raises(ValueError, match="integrity|complete|missing|invalid"):
            build_aggregate_v2(
                make_envelope(scopes),
                date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
                published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
                production_policy_status="unapproved"
            )



