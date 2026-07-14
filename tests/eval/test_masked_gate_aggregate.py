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
