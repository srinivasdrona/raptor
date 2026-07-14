from __future__ import annotations

from scripts.build_masked_holdout_gate_aggregate import build_aggregate


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


GOVERNANCE_STATEMENT = (
    "Full-spectrum VUS automation is not authorized. Evidence supports only the "
    "validated truncating-pathogenic scope; missense remains unvalidated."
)
RESEARCH_USE_DISCLAIMER = (
    "Research-evidence validation only; this authorizes no clinical classification, "
    "VUS worklist, or ClinVar submission."
)


def _build_aggregate_v2(envelope: dict) -> dict:
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    return build_aggregate_v2(envelope)


def _v2_envelope() -> dict:
    return {
        "report": {
            "metrics": {
                "overall": {
                    "precision_lb": 1.0,
                    "recall_lb": 1.0,
                },
                "missense": {
                    "precision_lb": 0.80,
                    "recall_lb": 0.80,
                },
            },
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "FAIL",
                "full_spectrum_vus_authorized": False,
                "research_scope_flags": {
                    "truncating_pathogenic_research_scope_validated": True,
                },
                "governance_state": "TRUNCATING_PATHOGENIC_ONLY",
                "governance_statement": GOVERNANCE_STATEMENT,
                "research_use_disclaimer": RESEARCH_USE_DISCLAIMER,
                "reason": "synthetic partial result",
                "scopes": {
                    "missense:pathogenic": {
                        "metric_status": "UNMET",
                        "coverage_adequate": False,
                        "scope_status": "FAIL",
                    },
                    "missense:benign": {
                        "metric_status": "UNMET",
                        "coverage_adequate": False,
                        "scope_status": "FAIL",
                    },
                    "truncating:pathogenic": {
                        "metric_status": "MET",
                        "coverage_adequate": True,
                        "scope_status": "VALIDATED",
                    },
                    "truncating:benign": {
                        "metric_status": "NO_THRESHOLD",
                        "coverage_adequate": False,
                        "scope_status": "DESCRIPTIVE",
                    },
                },
            },
        },
    }


def test_v2_aggregate_uses_scope_gate_as_primary_verdict() -> None:
    envelope = _v2_envelope()
    aggregate = _build_aggregate_v2(envelope)
    scope_gate = envelope["report"]["scope_gate"]

    assert aggregate["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert aggregate["scopes"] == scope_gate["scopes"]
    assert aggregate["research_scope_flags"] == scope_gate["research_scope_flags"]
    assert aggregate["governance_state"] == scope_gate["governance_state"]
    assert aggregate["governance_statement"] == GOVERNANCE_STATEMENT
    assert aggregate["research_use_disclaimer"] == RESEARCH_USE_DISCLAIMER
    assert aggregate["metrics"] == envelope["report"]["metrics"]
    assert "overall" in aggregate["metrics"]
    assert aggregate["vus_authorized"] == scope_gate[
        "full_spectrum_vus_authorized"
    ]
    assert aggregate["vus_authorized"] is False


def test_v2_partial_result_never_becomes_full_spectrum_authorization() -> None:
    aggregate = _build_aggregate_v2(_v2_envelope())

    assert aggregate["vus_authorized"] is False
    assert aggregate["full_spectrum_status"] == "FAIL"
    assert aggregate["research_scope_flags"][
        "truncating_pathogenic_research_scope_validated"
    ] is True
    assert aggregate["governance_statement"] == GOVERNANCE_STATEMENT
    assert aggregate["research_use_disclaimer"] == RESEARCH_USE_DISCLAIMER
