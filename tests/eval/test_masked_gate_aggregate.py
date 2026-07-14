from __future__ import annotations

from scripts.build_masked_holdout_gate_aggregate import build_aggregate, build_aggregate_v2


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
                    "missense:pathogenic": {"scope_status": "VALIDATED"},
                    "missense:benign": {"scope_status": "VALIDATED"},
                    "truncating:pathogenic": {"scope_status": "VALIDATED"},
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
                "evaluation_skipped_criteria": ["PM1"],
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
    assert aggregate["scopes"]["missense:pathogenic"] == {"scope_status": "VALIDATED"}
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
                    "missense:pathogenic": {"scope_status": "FAIL"},
                    "missense:benign": {"scope_status": "FAIL"},
                    "truncating:pathogenic": {"scope_status": "VALIDATED"},
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
                "evaluation_skipped_criteria": ["PM1"],
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
                "missense:pathogenic": {"scope_status": "VALIDATED"},
                "missense:benign": {"scope_status": "VALIDATED"},
                "truncating:pathogenic": {"scope_status": "VALIDATED"},
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
            "missense:pathogenic": {"scope_status": "FAIL"},
            "missense:benign": {"scope_status": "VALIDATED"},
            "truncating:pathogenic": {"scope_status": "VALIDATED"},
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
            "missense:pathogenic": {"scope_status": "FAIL"},
            "missense:benign": {"scope_status": "FAIL"},
            "truncating:pathogenic": {"scope_status": "FAIL"},
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
                    "missense:pathogenic": {"scope_status": "FAIL"},
                    "missense:benign": {"scope_status": "FAIL"},
                    "truncating:pathogenic": {"scope_status": "VALIDATED"},
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


