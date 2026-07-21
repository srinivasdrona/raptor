from __future__ import annotations

from scripts.build_masked_holdout_gate_aggregate import build_aggregate, build_aggregate_v2

# NOTE: these two imports must stay at module level (not deferred inside a
# test function body). `conftest` and `test_scope_gate_final_blocker` are
# bare, non-package module names resolved via pytest's rootdir sys.path
# insertion; when the FULL repo test suite runs, other test directories
# (e.g. tests/scorer/conftest.py) also register a same-named `conftest`
# module in `sys.modules`, and whichever was imported *last* during
# collection wins for any *later*, function-body-deferred bare import.
# Importing at module level here resolves them during this module's own
# collection (before other test directories' conftest.py files are
# collected), matching every other tests/eval/*.py file's proven-working
# top-level `from conftest import ...` pattern.
from conftest import make_eval_config
from test_scope_gate_final_blocker import make_v2_auth_config, make_oracle_thresholds


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


def _metrics_from_scopes(scopes: dict) -> dict:
    """CRITICAL FIX cross-surface integrity test helper: `build_aggregate_v2`
    now independently re-derives every scope's evidence from
    `report['metrics']` (never from `scope_gate.scopes` itself), so any
    fixture whose `scope_gate.scopes` entries are meant to be genuinely
    accepted must be backed by a `report['metrics']` payload carrying the
    SAME precision_lb/recall_lb/counts values. This derives that matching
    `metrics` payload directly from a test's own `scopes` mapping so both
    surfaces stay in lockstep by construction.
    """
    default = {"precision_lb": 0.99, "recall_lb": 0.99, "actual_count": 40, "called_count": 40}
    strata = sorted({key.partition(":")[0] for key in scopes})
    metrics = {}
    for stratum in strata:
        patho = scopes.get(f"{stratum}:pathogenic", default)
        benign = scopes.get(f"{stratum}:benign", default)
        metrics[stratum] = {
            "precision_lb": patho["precision_lb"],
            "recall_lb": patho["recall_lb"],
            "benign_precision_lb": benign["precision_lb"],
            "benign_recall_lb": benign["recall_lb"],
            "counts": {
                "path_actual": patho["actual_count"],
                "path_called": patho["called_count"],
                "benign_actual": benign["actual_count"],
                "benign_called": benign["called_count"],
            },
        }
    return metrics


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
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
        "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
        "truncating:benign": _get_consistent_scope("truncating:benign", "DESCRIPTIVE"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
                "oracle_thresholds": make_oracle_thresholds(),
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
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
        "missense:benign": _get_consistent_scope("missense:benign", "FAIL"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
        "truncating:benign": _get_consistent_scope("truncating:benign", "DESCRIPTIVE"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
                "oracle_thresholds": make_oracle_thresholds(),
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
                "metrics": _metrics_from_scopes(scope_gate["scopes"]),
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
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
        "missense:benign": _get_consistent_scope("missense:benign", "FAIL"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
        "truncating:benign": _get_consistent_scope("truncating:benign", "DESCRIPTIVE"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
                "oracle_thresholds": make_oracle_thresholds(),
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
    
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
        "missense:benign": _get_consistent_scope("missense:benign", "FAIL"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
        "truncating:benign": _get_consistent_scope("truncating:benign", "DESCRIPTIVE"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
                "oracle_thresholds": make_oracle_thresholds(),
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
    
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
        "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
        "truncating:benign": _get_consistent_scope("truncating:benign", "DESCRIPTIVE"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
                "oracle_thresholds": make_oracle_thresholds(),
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
    
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
        "missense:benign": _get_consistent_scope("missense:benign", "FAIL"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "FAIL"),
        "truncating:benign": _get_consistent_scope("truncating:benign", "DESCRIPTIVE"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
                "oracle_thresholds": make_oracle_thresholds(),
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
            "metrics": _metrics_from_scopes({
                "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
            }),
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
    
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "FAIL"),
        "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
    
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "UNDERPOWERED"),
        "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
    
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
        "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
    
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "UNDERPOWERED"),
        "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
        "truncating:benign": _get_consistent_scope("truncating:benign", "DESCRIPTIVE"),
    }
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
            "metrics": _metrics_from_scopes(_scopes),
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
                "scopes": _scopes,
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
                "oracle_thresholds": make_oracle_thresholds(),
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
    _scopes_v2 = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
        "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
        "truncating:benign": _get_consistent_scope("truncating:benign", "DESCRIPTIVE"),
    }
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
            "metrics": _metrics_from_scopes(_scopes_v2),
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
                "scopes": _scopes_v2,
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
                "oracle_thresholds": make_oracle_thresholds(),
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

    _FULL_SPECTRUM_REQUIRED_SCOPES = (
        "missense:pathogenic", "missense:benign", "truncating:pathogenic",
    )

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
                "metrics": _metrics_from_scopes(scopes_payload),
                "gate": {"status": "FAIL", "stratum": "missense", "reason": "below", "vus_authorized": False},
                "scope_gate": {
                    "schema_version": "2",
                    # Full-spectrum authorization is derived ONLY from the pinned
                    # full-spectrum required scopes (missense:pathogenic,
                    # missense:benign, truncating:pathogenic) -- never from every
                    # key in `scopes_payload` (which now also always carries the
                    # purely-descriptive, never-VALIDATED `truncating:benign`).
                    "full_spectrum_status": "PASS" if all(scopes_payload.get(k, {}).get("scope_status") == "VALIDATED" for k in _FULL_SPECTRUM_REQUIRED_SCOPES) else "FAIL",
                    "full_spectrum_vus_authorized": all(scopes_payload.get(k, {}).get("scope_status") == "VALIDATED" for k in _FULL_SPECTRUM_REQUIRED_SCOPES),
                    "research_scope_flags": {"truncating_pathogenic_research_scope_validated": scopes_payload.get("truncating:pathogenic", {}).get("scope_status") == "VALIDATED"},
                    "governance_state": "FULL_SPECTRUM" if all(scopes_payload.get(k, {}).get("scope_status") == "VALIDATED" for k in _FULL_SPECTRUM_REQUIRED_SCOPES) else "NONE_VALIDATED",
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
            },
            "truncating:benign": {
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
                "scope_status": "DESCRIPTIVE",
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


# =========================================================================
# CROSS-SURFACE INTEGRITY RED TESTS FOR GPT-5.4
# =========================================================================

def _get_cross_surface_baseline():
    metrics = {
        "missense": {
            "precision": 0.95,
            "recall": 0.90,
            "concordance": 0.92,
            "benign_precision": 0.95,
            "benign_recall": 0.90,
            "precision_lb": 0.91,
            "recall_lb": 0.86,
            "benign_precision_lb": 0.91,
            "benign_recall_lb": 0.86,
            "counts": {
                "path_called": 40,
                "benign_called": 40,
                "path_actual": 40,
                "benign_actual": 40,
            },
            "gating": True,
        },
        "truncating": {
            "precision": 0.98,
            "recall": 0.97,
            "concordance": 0.98,
            "benign_precision": 0.0,
            "benign_recall": 0.0,
            "precision_lb": 0.96,
            "recall_lb": 0.96,
            "benign_precision_lb": 0.0,
            "benign_recall_lb": 0.0,
            "counts": {
                "path_called": 40,
                "benign_called": 1,
                "path_actual": 40,
                "benign_actual": 1,
            },
            "gating": True,
        }
    }
    
    scopes = {
        "missense:pathogenic": {
            "stratum": "missense",
            "direction": "pathogenic",
            "precision_lb": 0.91,
            "recall_lb": 0.86,
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
            "precision_lb": 0.91,
            "recall_lb": 0.86,
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
        },
        "truncating:benign": {
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
            "scope_status": "DESCRIPTIVE",
            "reasons": []
        }
    }
    
    envelope = {
        "content_hash": "content",
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": {
            "labels_snapshot": "snapshot",
            "benchmark_size": 100,
            "train_dev_size": 20,
            "holdout_size": 80,
            "holdout_label_counts": {"P": 40, "B": 40},
            "holdout_class_counts": {"missense": 80},
            "metrics": metrics,
            "gate": {"status": "PASS", "stratum": "missense", "reason": "passed", "vus_authorized": True},
            "scope_gate": {
                "schema_version": "2",
                "full_spectrum_status": "PASS",
                "full_spectrum_vus_authorized": True,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "FULL_SPECTRUM",
                "governance_statement": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "reason": "all validated",
                "scopes": scopes
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
        },
    }
    return envelope


def test_cross_surface_red_1_failing_metrics_with_forged_scopes_rejected():
    """REQUIRED RED TEST 1: Start from realistic v2 envelope with report.metrics
    containing failing missense LBs/counts and/or legacy gate FAIL. Replace
    scope_gate.scopes with complete internally self-consistent VALIDATED entries
    and matching top-level auth/governance. build_aggregate_v2 must reject.
    """
    import pytest
    env = _get_cross_surface_baseline()
    
    # Failing missense metrics
    env["report"]["metrics"]["missense"].update({
        "precision_lb": 0.50, # Failing
        "recall_lb": 0.50, # Failing
    })
    env["report"]["gate"].update({
        "status": "FAIL",
        "vus_authorized": False
    })
    
    # But scopes is forged to show VALIDATED, which is internally self-consistent!
    env["report"]["scope_gate"]["scopes"]["missense:pathogenic"].update({
        "precision_lb": 0.91,
        "recall_lb": 0.86,
        "scope_status": "VALIDATED",
        "metric_status": "MET"
    })
    
    # build_aggregate_v2 must cross-check and reject the forged scopes vs metrics
    with pytest.raises(ValueError, match="cross-check|mismatch|independent|metrics"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_cross_surface_red_2_thresholds_drift_from_pins_rejected():
    """REQUIRED RED TEST 2: Scope entry thresholds drift from pins must reject.
    - missense not exactly .90/.85;
    - truncating:pathogenic not .95/.95;
    - truncating:benign and metrics-only other not both None
    must reject even if internally MET/VALIDATED.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    # Case A: missense drifts to 0.80/0.80
    env_a = _get_cross_surface_baseline()
    env_a["report"]["scope_gate"]["scopes"]["missense:pathogenic"].update({
        "precision_threshold": 0.80, # Drifted from 0.90
        "precision_lb": 0.85,
        "metric_status": "MET",
        "scope_status": "VALIDATED"
    })
    with pytest.raises(ValueError, match="cross-check|mismatch|threshold|drift"):
        build_aggregate_v2(
            env_a, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case B: truncating:pathogenic drifts to 0.90/0.90
    env_b = _get_cross_surface_baseline()
    env_b["report"]["scope_gate"]["scopes"]["truncating:pathogenic"].update({
        "precision_threshold": 0.90, # Drifted from 0.95
        "precision_lb": 0.91,
        "metric_status": "MET",
        "scope_status": "VALIDATED"
    })
    with pytest.raises(ValueError, match="cross-check|mismatch|threshold|drift"):
        build_aggregate_v2(
            env_b, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case C: truncating:benign is not None threshold
    env_c = _get_cross_surface_baseline()
    env_c["report"]["scope_gate"]["scopes"]["truncating:benign"].update({
        "precision_threshold": 0.50, # Drifted from None
        "recall_threshold": 0.50,
        "precision_lb": 0.60,
        "recall_lb": 0.60,
        "metric_status": "MET",
        "scope_status": "VALIDATED"
    })
    with pytest.raises(ValueError, match="cross-check|mismatch|threshold|drift"):
        build_aggregate_v2(
            env_c, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_cross_surface_red_3_lower_bounds_mismatch_metrics_rejected():
    """REQUIRED RED TEST 3: Scope lower bounds differ from corresponding report.metrics
    fields must reject:
    - pathogenic direction uses precision_lb/recall_lb;
    - benign uses benign_precision_lb/benign_recall_lb.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    # Case A: pathogenic precision_lb mismatch
    env_a = _get_cross_surface_baseline()
    env_a["report"]["scope_gate"]["scopes"]["missense:pathogenic"].update({
        "precision_lb": 0.99, # Differ from report.metrics.missense.precision_lb (0.91)
    })
    with pytest.raises(ValueError, match="cross-check|mismatch|lower bound|precision_lb"):
        build_aggregate_v2(
            env_a, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case B: benign recall_lb mismatch
    env_b = _get_cross_surface_baseline()
    env_b["report"]["scope_gate"]["scopes"]["missense:benign"].update({
        "recall_lb": 0.99, # Differ from report.metrics.missense.benign_recall_lb (0.86)
    })
    with pytest.raises(ValueError, match="cross-check|mismatch|lower bound|benign_recall_lb"):
        build_aggregate_v2(
            env_b, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_cross_surface_red_4_counts_mismatch_metrics_rejected():
    """REQUIRED RED TEST 4: Scope actual/called counts differ from report.metrics.counts
    path_actual/path_called or benign_actual/benign_called must reject.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    # Case A: pathogenic actual_count mismatch
    env_a = _get_cross_surface_baseline()
    env_a["report"]["scope_gate"]["scopes"]["missense:pathogenic"].update({
        "actual_count": 50, # Differ from report.metrics.missense.counts.path_actual (40)
    })
    with pytest.raises(ValueError, match="cross-check|mismatch|count|actual_count"):
        build_aggregate_v2(
            env_a, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case B: benign called_count mismatch
    env_b = _get_cross_surface_baseline()
    env_b["report"]["scope_gate"]["scopes"]["missense:benign"].update({
        "called_count": 50, # Differ from report.metrics.missense.counts.benign_called (40)
    })
    with pytest.raises(ValueError, match="cross-check|mismatch|count|called_count"):
        build_aggregate_v2(
            env_b, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_cross_surface_red_5_min_count_drift_rejected():
    """REQUIRED RED TEST 5: Scope min_count must exactly 36. Drift must reject."""
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    env = _get_cross_surface_baseline()
    env["report"]["scope_gate"]["scopes"]["missense:pathogenic"].update({
        "min_count": 10, # Drifted from 36
    })
    with pytest.raises(ValueError, match="cross-check|mismatch|min_count|drift"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_cross_surface_red_6_other_metrics_mapped_correctly():
    """REQUIRED RED TEST 6: Required scope set matches pinned config;
    metrics-only other scope if present must map to report's other metrics
    and remain NO_THRESHOLD/DESCRIPTIVE. If they differ, or if other is forged
    as validated, build_aggregate_v2 must reject.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    # Case A: other stratum is present in metrics and scopes, but other:pathogenic is forged as VALIDATED!
    env_a = _get_cross_surface_baseline()
    env_a["report"]["metrics"]["other"] = {
        "precision": 0.5, "recall": 0.5, "concordance": 0.5,
        "benign_precision": 0.5, "benign_recall": 0.5,
        "precision_lb": 0.4, "recall_lb": 0.4,
        "benign_precision_lb": 0.4, "benign_recall_lb": 0.4,
        "counts": {
            "path_called": 20, "benign_called": 20,
            "path_actual": 20, "benign_actual": 20,
        },
        "gating": False
    }
    env_a["report"]["scope_gate"]["scopes"]["other:pathogenic"] = {
        "stratum": "other",
        "direction": "pathogenic",
        "precision_lb": 0.4,
        "recall_lb": 0.4,
        "precision_threshold": 0.3, # Forged threshold!
        "recall_threshold": 0.3,
        "actual_count": 20,
        "called_count": 20,
        "min_count": 36,
        "coverage_adequate": False,
        "metric_status": "MET",
        "scope_status": "VALIDATED", # Forged status!
        "reasons": []
    }
    
    with pytest.raises(ValueError, match="cross-check|mismatch|other|threshold"):
        build_aggregate_v2(
            env_a, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_cross_surface_red_7_genuine_envelope_builds_successfully():
    """REQUIRED RED TEST 7: A genuine runner/report_to_dict envelope generated
    by compute_report_scope_gate(metrics, config) must build successfully both
    no-skip and PM1 parity-blocked paths.
    """
    # `make_eval_config`/`make_v2_auth_config`/`make_oracle_thresholds` are
    # imported at module level (see top of file) -- NOT re-imported here --
    # to avoid the bare-`conftest`-module sys.modules collision that occurs
    # when this deferred (function-body) import runs during full-repo test
    # execution (after other test directories' same-named conftest.py files
    # have already been collected and cached under the same bare name).
    from scripts.run_masked_holdout_eval import compute_report_scope_gate
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    from raptor.eval.model import Metrics, GateDecision
    from raptor.eval.report import EvalReport, report_to_dict

    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_missense = Metrics(
        precision=0.95, recall=0.90, concordance=0.92,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.95, benign_recall=0.90
    )
    m_missense.precision_lb = 0.91
    m_missense.recall_lb = 0.86
    m_missense.benign_precision_lb = 0.91
    m_missense.benign_recall_lb = 0.86

    m_truncating = Metrics(
        precision=0.98, recall=0.97, concordance=0.98,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=0.0, benign_recall=0.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}

    # Case A: No skip
    decision_a = compute_report_scope_gate(metrics, cfg, skipped=set())
    report_a = EvalReport(
        run_id="run-test-a", generated_at="2026-07-15", labels_snapshot="snap",
        benchmark_size=100, train_dev_size=20, holdout_size=80,
        holdout_label_counts={"P": 40, "B": 40}, holdout_class_counts={"missense": 80},
        metrics=metrics,
        gate=GateDecision(status="PASS", stratum="missense", reason="ok", vus_authorized=True),
        scope_gate=decision_a
    )
    report_a.config_pins = {
        "bias_tsv_sha256": "bias", "manifest_sha256": "manifest",
        "mask_ledger_sha256": "ledger", "remask_audit_sha256": "remask",
        "return_manifest_sha256": "return", "predictor_correction_counts": {"PP3": 1, "BP4": 2},
        "operational_skipped_criteria": ["PM1", "PS4"], "evaluation_skipped_criteria": [],
        "oracle_thresholds": make_oracle_thresholds(),
    }
    env_a = {
        "content_hash": report_a.content_hash(), "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []}, "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": report_to_dict(report_a)
    }
    agg_a = build_aggregate_v2(
        env_a, date="2026-07-15", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    assert agg_a["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert agg_a["vus_authorized"] is True

    # Case B: PM1 skipped parity-blocked path
    decision_b = compute_report_scope_gate(metrics, cfg, skipped={"PM1"})
    report_b = EvalReport(
        run_id="run-test-b", generated_at="2026-07-15", labels_snapshot="snap",
        benchmark_size=100, train_dev_size=20, holdout_size=80,
        holdout_label_counts={"P": 40, "B": 40}, holdout_class_counts={"missense": 80},
        metrics=metrics,
        gate=GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False),
        scope_gate=decision_b
    )
    report_b.config_pins = {
        "bias_tsv_sha256": "bias", "manifest_sha256": "manifest",
        "mask_ledger_sha256": "ledger", "remask_audit_sha256": "remask",
        "return_manifest_sha256": "return", "predictor_correction_counts": {"PP3": 1, "BP4": 2},
        "operational_skipped_criteria": ["PM1", "PS4"], "evaluation_skipped_criteria": ["PM1"],
        "oracle_thresholds": make_oracle_thresholds(),
    }
    env_b = {
        "content_hash": report_b.content_hash(), "predictor_policy": {"status": "approved"},
        "mask_attestation": {"removed_count": 2, "zero_survivors": True},
        "lineage_audit": {"effective_blocking_criteria": []}, "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": report_to_dict(report_b)
    }
    agg_b = build_aggregate_v2(
        env_b, date="2026-07-15", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    assert agg_b["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert agg_b["vus_authorized"] is False


def test_cross_surface_red_8_missing_required_metrics_rejected():
    """REQUIRED RED TEST 8: If report.metrics is missing a required stratum/field/count,
    aggregate must reject rather than fall back to scope payload.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    # Case A: report.metrics is missing "missense" stratum entirely!
    env_a = _get_cross_surface_baseline()
    del env_a["report"]["metrics"]["missense"]
    with pytest.raises(ValueError, match="cross-check|mismatch|missing|metrics"):
        build_aggregate_v2(
            env_a, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case B: report.metrics has "missense" but is missing counts!
    env_b = _get_cross_surface_baseline()
    del env_b["report"]["metrics"]["missense"]["counts"]
    with pytest.raises(ValueError, match="cross-check|mismatch|missing|counts"):
        build_aggregate_v2(
            env_b, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_cross_surface_red_9_legacy_gate_status_coexistence_validated():
    """REQUIRED RED TEST 9: A legacy gate FAIL can coexist with scope-specific
    truncating validation, but full-spectrum scope recomputation must match
    report.metrics + pinned constants, and do not rely on legacy gate status.
    """
    env = _get_cross_surface_baseline()
    
    # Legacy gate status is FAIL (missense failed)
    env["report"]["gate"].update({
        "status": "FAIL",
        "vus_authorized": False,
        "stratum": "missense"
    })
    
    # We modify metrics so that missense is indeed failing
    env["report"]["metrics"]["missense"].update({
        "precision_lb": 0.50, # FAIL
    })
    # And scopes show missense:pathogenic is FAIL, which is consistent with metrics!
    env["report"]["scope_gate"]["scopes"]["missense:pathogenic"].update({
        "precision_lb": 0.50,
        "scope_status": "FAIL",
        "metric_status": "UNMET"
    })
    # But truncating:pathogenic is VALIDATED (both in metrics and scopes)
    env["report"]["metrics"]["truncating"].update({
        "precision_lb": 0.96, # PASS
    })
    env["report"]["scope_gate"]["scopes"]["truncating:pathogenic"].update({
        "precision_lb": 0.96,
        "scope_status": "VALIDATED",
        "metric_status": "MET"
    })
    
    # Update other scope-gate statuses to reflect that missense failed but truncating passed
    from raptor.eval.config import _PINNED_GOVERNANCE_STATEMENTS
    env["report"]["scope_gate"].update({
        "full_spectrum_status": "FAIL",
        "full_spectrum_vus_authorized": False,
        "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
        "governance_state": "TRUNCATING_PATHOGENIC_ONLY",
        "governance_statement": _PINNED_GOVERNANCE_STATEMENTS["TRUNCATING_PATHOGENIC_ONLY"]
    })
    
    # Since everything is consistent with report.metrics (including missense FAIL),
    # this coexistence of legacy gate FAIL and v2 TRUNCATING_PATHOGENIC_ONLY must succeed.
    agg = build_aggregate_v2(
        env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    assert agg["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert agg["vus_authorized"] is False
    assert agg["research_scope_flags"]["truncating_pathogenic_research_scope_validated"] is True


# ==============================================================================
# RED TESTS FOR GPT-5.4 BLOCKERS (PUBLICATION INTEGRITY)
# ==============================================================================

def test_blocker_1_config_pins_oracle_thresholds_tampered_rejected():
    """BLOCKER 1 RED TEST: Modify config_pins.oracle_thresholds missense/truncating
    precision, recall, confidence, gating, directions; builder must reject drift
    or canonicalize output. Prefer fail-loud rejection.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    
    # Case A: Tamper with confidence
    env = _get_cross_surface_baseline()
    env["report"]["config_pins"]["oracle_thresholds"]["confidence"] = 0.50
    with pytest.raises(ValueError, match="confidence|threshold|drift|canonical|tamper"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case B: Tamper with missense precision threshold
    env = _get_cross_surface_baseline()
    env["report"]["config_pins"]["oracle_thresholds"]["strata"]["missense"]["precision"] = 0.10
    with pytest.raises(ValueError, match="precision|threshold|drift|canonical|tamper"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case C: Tamper with truncating recall threshold
    env = _get_cross_surface_baseline()
    env["report"]["config_pins"]["oracle_thresholds"]["strata"]["truncating"]["recall"] = 0.10
    with pytest.raises(ValueError, match="recall|threshold|drift|canonical|tamper"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case D: Missing config_pins.oracle_thresholds
    env = _get_cross_surface_baseline()
    del env["report"]["config_pins"]["oracle_thresholds"]
    with pytest.raises(ValueError, match="oracle_thresholds|missing|malformed"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case E: Missing strata
    env = _get_cross_surface_baseline()
    del env["report"]["config_pins"]["oracle_thresholds"]["strata"]
    with pytest.raises(ValueError, match="strata|missing|malformed"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_1_aggregate_output_thresholds_exact_canonical():
    """BLOCKER 1 RED TEST: Valid v2 aggregate output `thresholds` must equal exact canonical pinned payload.
    Any additional or omitted strata or tampered metadata must be rejected or canonicalized.
    """
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    env = _get_cross_surface_baseline()
    agg = build_aggregate_v2(
        env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    
    expected_thresholds = {
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
    assert agg["thresholds"] == expected_thresholds


def test_blocker_2_omit_truncating_benign_rejected():
    """BLOCKER 2 RED TEST: Missing truncating:benign from scopes must reject (since truncating
    is a pinned threshold stratum, even if it has no registered benign threshold, it must be
    represented descriptively).
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    env = _get_cross_surface_baseline()
    
    # Omit truncating:benign from the scopes table
    if "truncating:benign" in env["report"]["scope_gate"]["scopes"]:
        del env["report"]["scope_gate"]["scopes"]["truncating:benign"]
        
    with pytest.raises(ValueError, match="incomplete|missing|truncating:benign|expected"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_2_metrics_other_omit_one_or_both_rejected():
    """BLOCKER 2 RED TEST: If report.metrics contains an additional descriptive stratum (e.g. 'other'),
    both directions (other:pathogenic, other:benign) must be present in scopes. Missing one or both
    must reject.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    
    # Case A: Omit both other scopes
    env_a = _get_cross_surface_baseline()
    env_a["report"]["metrics"]["other"] = {
        "precision_lb": 0.50, "recall_lb": 0.50, "benign_precision_lb": 0.50, "benign_recall_lb": 0.50,
        "counts": {"path_called": 10, "benign_called": 10, "path_actual": 10, "benign_actual": 10}
    }
    with pytest.raises(ValueError, match="incomplete|missing|other:pathogenic|other:benign|expected"):
        build_aggregate_v2(
            env_a, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # Case B: Omit only other:benign
    env_b = _get_cross_surface_baseline()
    env_b["report"]["metrics"]["other"] = {
        "precision_lb": 0.50, "recall_lb": 0.50, "benign_precision_lb": 0.50, "benign_recall_lb": 0.50,
        "counts": {"path_called": 10, "benign_called": 10, "path_actual": 10, "benign_actual": 10}
    }
    env_b["report"]["scope_gate"]["scopes"]["other:pathogenic"] = {
        "stratum": "other", "direction": "pathogenic",
        "precision_lb": 0.50, "recall_lb": 0.50, "precision_threshold": None, "recall_threshold": None,
        "actual_count": 10, "called_count": 10, "min_count": 36, "coverage_adequate": False,
        "metric_status": "NO_THRESHOLD", "scope_status": "DESCRIPTIVE", "reasons": []
    }
    with pytest.raises(ValueError, match="incomplete|missing|other:benign|expected"):
        build_aggregate_v2(
            env_b, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_2_metrics_other_complete_scopes_accepted():
    """BLOCKER 2 RED TEST: If report.metrics contains 'other' and both complete consistent
    descriptive scopes are provided, build_aggregate_v2 must accept.
    """
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    env = _get_cross_surface_baseline()
    
    env["report"]["metrics"]["other"] = {
        "precision_lb": 0.50, "recall_lb": 0.50, "benign_precision_lb": 0.50, "benign_recall_lb": 0.50,
        "counts": {"path_called": 10, "benign_called": 10, "path_actual": 10, "benign_actual": 10}
    }
    env["report"]["scope_gate"]["scopes"]["other:pathogenic"] = {
        "stratum": "other", "direction": "pathogenic",
        "precision_lb": 0.50, "recall_lb": 0.50, "precision_threshold": None, "recall_threshold": None,
        "actual_count": 10, "called_count": 10, "min_count": 36, "coverage_adequate": False,
        "metric_status": "NO_THRESHOLD", "scope_status": "DESCRIPTIVE", "reasons": []
    }
    env["report"]["scope_gate"]["scopes"]["other:benign"] = {
        "stratum": "other", "direction": "benign",
        "precision_lb": 0.50, "recall_lb": 0.50, "precision_threshold": None, "recall_threshold": None,
        "actual_count": 10, "called_count": 10, "min_count": 36, "coverage_adequate": False,
        "metric_status": "NO_THRESHOLD", "scope_status": "DESCRIPTIVE", "reasons": []
    }
    
    agg = build_aggregate_v2(
        env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    assert agg["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert "other:pathogenic" in agg["scopes"]
    assert "other:benign" in agg["scopes"]


def test_blocker_2_ghost_scope_no_metrics_rejected():
    """BLOCKER 2 RED TEST: If scope contains an extra/unknown 'ghost' scope but no metrics,
    build_aggregate_v2 must reject.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    env = _get_cross_surface_baseline()
    
    env["report"]["scope_gate"]["scopes"]["ghost:pathogenic"] = {
        "stratum": "ghost", "direction": "pathogenic",
        "precision_lb": 0.90, "recall_lb": 0.90, "precision_threshold": None, "recall_threshold": None,
        "actual_count": 10, "called_count": 10, "min_count": 36, "coverage_adequate": True,
        "metric_status": "NO_THRESHOLD", "scope_status": "DESCRIPTIVE", "reasons": []
    }
    
    with pytest.raises(ValueError, match="ghost|metrics|unknown|extra|cross-check"):
        build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_blocker_2_aggregate_output_scopes_exactly_matches_independently_expected():
    """BLOCKER 2 RED TEST: The aggregate output scopes keys must exactly match the set
    independently derived from report.metrics and pinned threshold strata.
    """
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    env = _get_cross_surface_baseline()
    agg = build_aggregate_v2(
        env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    
    expected_keys = {
        "missense:pathogenic", "missense:benign",
        "truncating:pathogenic", "truncating:benign"
    }
    assert set(agg["scopes"].keys()) == expected_keys


def test_blocker_2_aggregate_output_scopes_exactly_matches_independently_expected_with_other():
    """BLOCKER 2 RED TEST: Aggregate output scopes must exactly match independently expected keys
    when additional strata like other are present.
    """
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    env = _get_cross_surface_baseline()
    
    env["report"]["metrics"]["other"] = {
        "precision_lb": 0.50, "recall_lb": 0.50, "benign_precision_lb": 0.50, "benign_recall_lb": 0.50,
        "counts": {"path_called": 10, "benign_called": 10, "path_actual": 10, "benign_actual": 10}
    }
    env["report"]["scope_gate"]["scopes"]["other:pathogenic"] = {
        "stratum": "other", "direction": "pathogenic",
        "precision_lb": 0.50, "recall_lb": 0.50, "precision_threshold": None, "recall_threshold": None,
        "actual_count": 10, "called_count": 10, "min_count": 36, "coverage_adequate": False,
        "metric_status": "NO_THRESHOLD", "scope_status": "DESCRIPTIVE", "reasons": []
    }
    env["report"]["scope_gate"]["scopes"]["other:benign"] = {
        "stratum": "other", "direction": "benign",
        "precision_lb": 0.50, "recall_lb": 0.50, "precision_threshold": None, "recall_threshold": None,
        "actual_count": 10, "called_count": 10, "min_count": 36, "coverage_adequate": False,
        "metric_status": "NO_THRESHOLD", "scope_status": "DESCRIPTIVE", "reasons": []
    }
    
    agg = build_aggregate_v2(
        env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    
    expected_keys = {
        "missense:pathogenic", "missense:benign",
        "truncating:pathogenic", "truncating:benign",
        "other:pathogenic", "other:benign"
    }
    assert set(agg["scopes"].keys()) == expected_keys


def test_blocker_2_reject_unknown_fields_in_scope():
    """BLOCKER 2 RED TEST:
    - Inject `clinical_authorized: true` into one complete scope => build_aggregate_v2 rejects ValueError.
    - Inject arbitrary nested/unknown fields into required, descriptive, and other scope entries => reject.
    - Exact canonical scope succeeds.
    - Aggregate output scope entries have exactly canonical key set and are built/canonicalized rather than preserving input object extras.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2
    
    # 1. Exact canonical scope succeeds
    env_canonical = _get_cross_surface_baseline()
    agg = build_aggregate_v2(
        env_canonical, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    assert agg is not None
    
    # Check that aggregate output scope entries have EXACTLY the canonical key set
    canonical_keys = {
        "stratum", "direction", "precision_lb", "recall_lb", "precision_threshold", "recall_threshold",
        "actual_count", "called_count", "min_count", "coverage_adequate", "metric_status", "scope_status",
        "reasons"
    }
    for scope_key, entry in agg["scopes"].items():
        assert set(entry.keys()) == canonical_keys

    # 2. Inject clinical_authorized: true into one complete scope => build_aggregate_v2 rejects with ValueError
    env_injected_clinical = _get_cross_surface_baseline()
    env_injected_clinical["report"]["scope_gate"]["scopes"]["missense:pathogenic"]["clinical_authorized"] = True
    with pytest.raises((ValueError, TypeError)):
        build_aggregate_v2(
            env_injected_clinical, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # 3. Inject arbitrary nested/unknown fields into required scope entries => reject
    env_injected_unknown_req = _get_cross_surface_baseline()
    env_injected_unknown_req["report"]["scope_gate"]["scopes"]["missense:pathogenic"]["unknown_nested_field"] = {"nested": "value"}
    with pytest.raises((ValueError, TypeError)):
        build_aggregate_v2(
            env_injected_unknown_req, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

    # 4. Inject arbitrary nested/unknown fields into descriptive scope entries => reject
    env_injected_unknown_desc = _get_cross_surface_baseline()
    env_injected_unknown_desc["report"]["scope_gate"]["scopes"]["truncating:benign"]["arbitrary_field"] = 123
    with pytest.raises((ValueError, TypeError)):
        build_aggregate_v2(
            env_injected_unknown_desc, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )


def test_reason_integrity_1_inject_scope_reasons_rejected_or_canonicalized():
    """RED TEST 1: Inject arbitrary scope reasons into otherwise valid required/descriptive scope;
    aggregate must reject mismatch OR output canonical derived reasons, never tampered text.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    # Case A: Required scope (missense:pathogenic)
    env = _get_cross_surface_baseline()
    tampered_msg = "TAMPERED_SCOPE_REASON_XYZ_123"
    env["report"]["scope_gate"]["scopes"]["missense:pathogenic"]["reasons"] = [tampered_msg]

    try:
        agg = build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )
        # If it doesn't reject with ValueError, it must have canonicalized the reason and replaced the tampered text!
        assert tampered_msg not in agg["scopes"]["missense:pathogenic"]["reasons"]
    except ValueError:
        # Rejection via ValueError is also a valid way of handling the mismatch/tamper
        pass

    # Case B: Descriptive scope (truncating:benign)
    env = _get_cross_surface_baseline()
    env["report"]["scope_gate"]["scopes"]["truncating:benign"]["reasons"] = [tampered_msg]

    try:
        agg = build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )
        assert tampered_msg not in agg["scopes"]["truncating:benign"]["reasons"]
    except ValueError:
        pass


def test_reason_integrity_2_inject_top_level_reason_rejected_or_canonicalized():
    """RED TEST 2: Inject arbitrary top-level scope_gate.reason;
    aggregate must reject or replace with canonical derived reason, never publish injected text.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    env = _get_cross_surface_baseline()
    tampered_msg = "TAMPERED_TOP_LEVEL_REASON_ABC_789"
    env["report"]["scope_gate"]["reason"] = tampered_msg

    try:
        agg = build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )
        # If it succeeds, the top-level reason must not contain the tampered text
        assert tampered_msg != agg["scope_gate_reason"]
        assert tampered_msg not in agg["scope_gate_reason"]
    except ValueError:
        # Rejection is also acceptable
        pass


def test_reason_integrity_3_canonical_reasons_deterministic():
    """RED TEST 3: Canonical reasons should be deterministic from verified numeric/policy state:
    - UNMET: identify LB(s) below threshold without arbitrary envelope prose;
    - UNDERPOWERED: identify actual/called coverage below min_count;
    - NO_THRESHOLD/DESCRIPTIVE: indicate no registered threshold (or coverage inadequate if applicable);
    - VALIDATED: empty reasons or a fixed canonical message.
    """
    import pytest
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    # Case A: UNMET
    # Make missense:pathogenic UNMET by reducing lower bounds
    env = _get_cross_surface_baseline()
    env["report"]["metrics"]["missense"]["precision_lb"] = 0.85 # threshold is 0.90
    env["report"]["metrics"]["missense"]["recall_lb"] = 0.86 # threshold is 0.85
    env["report"]["scope_gate"]["scopes"]["missense:pathogenic"]["precision_lb"] = 0.85
    env["report"]["scope_gate"]["scopes"]["missense:pathogenic"]["recall_lb"] = 0.86
    env["report"]["scope_gate"]["scopes"]["missense:pathogenic"]["metric_status"] = "UNMET"
    env["report"]["scope_gate"]["scopes"]["missense:pathogenic"]["scope_status"] = "FAIL"
    # Ensure they are in sync, or we test aggregate recomputation
    env["report"]["scope_gate"]["full_spectrum_status"] = "FAIL"
    env["report"]["scope_gate"]["full_spectrum_vus_authorized"] = False
    env["report"]["scope_gate"]["research_scope_flags"]["truncating_pathogenic_research_scope_validated"] = True
    env["report"]["scope_gate"]["governance_state"] = "TRUNCATING_PATHOGENIC_ONLY"
    env["report"]["scope_gate"]["governance_statement"] = (
        "Full-spectrum VUS automation is not authorized. Evidence supports only the validated "
        "truncating-pathogenic scope; missense remains unvalidated."
    )

    agg = build_aggregate_v2(
        env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    # The reasons for missense:pathogenic must identify precision_lb < threshold
    reasons = agg["scopes"]["missense:pathogenic"]["reasons"]
    assert any("precision_lb" in r and "0.85" in r and "0.9" in r for r in reasons)
    # It must not contain arbitrary envelope prose
    assert not any("arbitrary" in r or "prose" in r for r in reasons)

    # Case B: UNDERPOWERED
    # Make truncating:pathogenic UNDERPOWERED by reducing counts
    env = _get_cross_surface_baseline()
    env["report"]["metrics"]["truncating"]["counts"]["path_called"] = 10
    env["report"]["scope_gate"]["scopes"]["truncating:pathogenic"]["called_count"] = 10
    env["report"]["scope_gate"]["scopes"]["truncating:pathogenic"]["coverage_adequate"] = False
    env["report"]["scope_gate"]["scopes"]["truncating:pathogenic"]["scope_status"] = "UNDERPOWERED"
    env["report"]["scope_gate"]["full_spectrum_status"] = "UNDERPOWERED"
    env["report"]["scope_gate"]["full_spectrum_vus_authorized"] = False
    env["report"]["scope_gate"]["research_scope_flags"]["truncating_pathogenic_research_scope_validated"] = False
    env["report"]["scope_gate"]["governance_state"] = "NONE_VALIDATED"
    env["report"]["scope_gate"]["governance_statement"] = (
        "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
    )

    agg = build_aggregate_v2(
        env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    reasons = agg["scopes"]["truncating:pathogenic"]["reasons"]
    assert any("coverage inadequate" in r or "min(" in r for r in reasons)

    # Case C: NO_THRESHOLD/DESCRIPTIVE
    # Check truncating:benign
    env = _get_cross_surface_baseline()
    agg = build_aggregate_v2(
        env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    reasons = agg["scopes"]["truncating:benign"]["reasons"]
    for r in reasons:
        assert "coverage inadequate" in r or "threshold" in r or "min(" in r

    # Case D: VALIDATED
    assert agg["scopes"]["truncating:pathogenic"]["reasons"] == [] or agg["scopes"]["truncating:pathogenic"]["reasons"] == ["VALIDATED"]


def test_reason_integrity_4_canonical_top_level_reason():
    """RED TEST 4: Canonical top-level reason deterministic from canonical full status,
    authorization blockers, and sorted scope summaries; valid genuine runner envelope builds.
    """
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    env = _get_cross_surface_baseline()
    agg = build_aggregate_v2(
        env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )

    # Under genuine runner behavior:
    expected_canonical_reason = (
        "missense:benign=VALIDATED; "
        "missense:pathogenic=VALIDATED; "
        "truncating:benign=DESCRIPTIVE; "
        "truncating:pathogenic=VALIDATED"
    )
    assert agg["scope_gate_reason"] == expected_canonical_reason


def test_reason_integrity_5_no_arbitrary_injected_strings():
    """RED TEST 5: Aggregate output must not contain arbitrary injected strings anywhere
    in scopes reasons or scope_gate_reason.
    """
    import uuid
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    env = _get_cross_surface_baseline()
    random_uuid_1 = str(uuid.uuid4())
    random_uuid_2 = str(uuid.uuid4())
    random_uuid_3 = str(uuid.uuid4())

    env["report"]["scope_gate"]["reason"] = f"some prefix {random_uuid_1} some suffix"
    env["report"]["scope_gate"]["scopes"]["missense:pathogenic"]["reasons"] = [f"malicious {random_uuid_2}"]
    env["report"]["scope_gate"]["scopes"]["truncating:benign"]["reasons"] = [f"malicious {random_uuid_3}"]

    try:
        agg = build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

        agg_str = str(agg)
        assert random_uuid_1 not in agg_str
        assert random_uuid_2 not in agg_str
        assert random_uuid_3 not in agg_str
    except ValueError:
        pass


def test_reason_integrity_6_pm1_parity_block_retains_blockers_and_canonical_reason():
    """RED TEST 6: PM1 parity-block roundtrip retains explicit authorization_blockers;
    top-level reason can mention canonical block but not input prose.
    """
    import uuid
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2

    env = _get_cross_surface_baseline()
    # Trigger a PM1 parity blocker
    env["report"]["config_pins"]["evaluation_skipped_criteria"] = ["PM1"]
    env["report"]["scope_gate"]["authorization_blockers"] = ["evaluation_skipped_criteria:PM1"]
    env["report"]["scope_gate"]["full_spectrum_vus_authorized"] = False
    env["report"]["scope_gate"]["full_spectrum_status"] = "BLOCKED_POLICY"
    env["report"]["scope_gate"]["research_scope_flags"] = {
        "truncating_pathogenic_research_scope_validated": False
    }
    env["report"]["scope_gate"]["governance_state"] = "NONE_VALIDATED"
    env["report"]["scope_gate"]["governance_statement"] = (
        "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
    )

    # Inject custom tampered prose in reason
    random_uuid = str(uuid.uuid4())
    env["report"]["scope_gate"]["reason"] = f"My custom bypassed reason with {random_uuid}"

    try:
        agg = build_aggregate_v2(
            env, date="2026-07-14", terminal_json_hash="j", terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved"
        )

        # The output must contain the correct canonical blockers
        assert "evaluation_skipped_criteria:PM1" in agg["authorization_blockers"]
        # The top-level reason must not contain the injected custom prose
        assert random_uuid not in agg["scope_gate_reason"]
        # It can mention the canonical block (e.g. BLOCKED_POLICY) or default to the canonical recomputed sorted scopes
        assert "BLOCKED_POLICY" in agg["scope_gate_reason"] or "missense:pathogenic" in agg["scope_gate_reason"]
    except ValueError:
        pass


def test_aggregate_cli_bootstrap() -> None:
    """Test that running build_masked_holdout_gate_aggregate.py --help directly
    as a script from repository root with an entirely cleared PYTHONPATH succeeds,
    proving that it correctly bootstraps its source paths prior to importing
    any raptor submodules.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    # Find the repository root (going up from tests/eval)
    test_dir = Path(__file__).resolve().parent
    repo_root = test_dir.parents[1]

    script_path = repo_root / "scripts" / "build_masked_holdout_gate_aggregate.py"
    assert script_path.exists(), f"Script not found at: {script_path}"

    # Clean/controlled environment: copy os.environ and clear PYTHONPATH
    clean_env = dict(os.environ)
    clean_env.pop("PYTHONPATH", None)

    # Run the current Python interpreter on the script with --help
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=str(repo_root),
        env=clean_env,
        capture_output=True,
        text=True,
    )

    # Assert that it succeeds
    assert result.returncode == 0, (
        f"Script failed with returncode {result.returncode}.\n"
        f"Stdout:\n{result.stdout}\n"
        f"Stderr:\n{result.stderr}\n"
    )
    assert "usage:" in result.stdout.lower() or "options:" in result.stdout.lower()


# =========================================================================
# GEMINI 3.5 FLASH RED TESTS FOR AGGREGATE LIMITATIONS (GPT-5.4 BLOCKER)
# =========================================================================

def test_v2_limitations_genuine_no_skip():
    """RED TEST 1: Genuine no-skip v2 envelope/roundtrip where policy.pm1_status == scored.
    The limitations list must NOT contain any claim that PM1 was excluded, skipped,
    or has zero support.
    """
    env = _get_cross_surface_baseline()
    # No PM1 in evaluation_skipped_criteria, so pm1_status is "scored"
    env["report"]["config_pins"]["evaluation_skipped_criteria"] = []
    
    agg = build_aggregate_v2(
        env, date="2026-07-15", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 5}, reproduced_pm1_scope={"reachable_pm1_rows": 5},
        production_policy_status="unapproved"
    )
    
    assert agg["policy"]["pm1_status"] == "scored"
    
    # Verify that the limitations list does NOT contain any PM1 exclusion/skip claims
    limitations = agg["limitations"]
    for lim in limitations:
        assert "PM1 was excluded" not in lim
        assert "PM1 remains unvalidated" not in lim
        assert "zero support" not in lim
        assert "skipped" not in lim.lower()


def test_v2_limitations_pm1_skipped_parity_block():
    """RED TEST 2: Genuine PM1-skipped parity-block v2 envelope.
    The policy.pm1_status must reflect the skip, and limitations MUST include
    the accurate PM1 exclusion statement.
    """
    env = _get_cross_surface_baseline()
    # Trigger a PM1 parity blocker
    env["report"]["config_pins"]["evaluation_skipped_criteria"] = ["PM1"]
    env["report"]["scope_gate"]["authorization_blockers"] = ["evaluation_skipped_criteria:PM1"]
    env["report"]["scope_gate"]["full_spectrum_vus_authorized"] = False
    env["report"]["scope_gate"]["full_spectrum_status"] = "BLOCKED_POLICY"
    env["report"]["scope_gate"]["research_scope_flags"] = {
        "truncating_pathogenic_research_scope_validated": False
    }
    env["report"]["scope_gate"]["governance_state"] = "NONE_VALIDATED"
    env["report"]["scope_gate"]["governance_statement"] = (
        "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
    )
    env["report"]["scope_gate"]["reason"] = "PM1 skipped"
    
    agg = build_aggregate_v2(
        env, date="2026-07-15", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    
    assert agg["policy"]["pm1_status"] == "SKIPPED_ZERO_SUPPORT_BASELINE_MISMATCH"
    
    # Limitations must include the PM1 exclusion statement
    expected_statement = "PM1 was excluded from this fixed evaluation after both published and reproduced resources had zero held-out-reachable rows; production PM1 remains unvalidated."
    assert expected_statement in agg["limitations"]


def test_v2_other_limitations_remain_accurate():
    """RED TEST 3: Other limitations (evaluation-only BP4/PP3 and nonclinical no authorization)
    remain accurate and present as appropriate, regardless of PM1 skip status.
    """
    # Case A: no-skip
    env_noskip = _get_cross_surface_baseline()
    agg_noskip = build_aggregate_v2(
        env_noskip, date="2026-07-15", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 5}, reproduced_pm1_scope={"reachable_pm1_rows": 5},
        production_policy_status="unapproved"
    )
    
    # Case B: skipped
    env_skip = _get_cross_surface_baseline()
    env_skip["report"]["config_pins"]["evaluation_skipped_criteria"] = ["PM1"]
    env_skip["report"]["scope_gate"]["authorization_blockers"] = ["evaluation_skipped_criteria:PM1"]
    env_skip["report"]["scope_gate"]["full_spectrum_vus_authorized"] = False
    env_skip["report"]["scope_gate"]["full_spectrum_status"] = "BLOCKED_POLICY"
    env_skip["report"]["scope_gate"]["research_scope_flags"] = {
        "truncating_pathogenic_research_scope_validated": False
    }
    env_skip["report"]["scope_gate"]["governance_state"] = "NONE_VALIDATED"
    env_skip["report"]["scope_gate"]["governance_statement"] = (
        "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
    )
    agg_skip = build_aggregate_v2(
        env_skip, date="2026-07-15", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    
    other_expected = [
        "The evaluation-only BP4/PP3 approval does not approve production candidate policy or variant classifications.",
        "No VUS worklist, clinical classification, or ClinVar submission is authorized."
    ]
    
    for agg in (agg_noskip, agg_skip):
        for expected in other_expected:
            assert expected in agg["limitations"]


def test_v2_limitation_derivation_is_dynamic():
    """RED TEST 4: Limitation derivation uses evaluation_skipped_criteria/pm1_status,
    not stale fixed-run text.
    """
    env = _get_cross_surface_baseline()
    # Test that the PM1 limitation inclusion is dynamic. If we dynamically toggle
    # the skip status, the presence of the PM1 limitation matches it.
    
    # No skip -> No PM1 limitation
    env["report"]["config_pins"]["evaluation_skipped_criteria"] = []
    agg_noskip = build_aggregate_v2(
        env, date="2026-07-15", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 5}, reproduced_pm1_scope={"reachable_pm1_rows": 5},
        production_policy_status="unapproved"
    )
    assert not any("PM1" in lim for lim in agg_noskip["limitations"])
    
    # Skipped -> Has PM1 limitation
    env["report"]["config_pins"]["evaluation_skipped_criteria"] = ["PM1"]
    env["report"]["scope_gate"]["authorization_blockers"] = ["evaluation_skipped_criteria:PM1"]
    env["report"]["scope_gate"]["full_spectrum_vus_authorized"] = False
    env["report"]["scope_gate"]["full_spectrum_status"] = "BLOCKED_POLICY"
    env["report"]["scope_gate"]["research_scope_flags"] = {
        "truncating_pathogenic_research_scope_validated": False
    }
    env["report"]["scope_gate"]["governance_state"] = "NONE_VALIDATED"
    env["report"]["scope_gate"]["governance_statement"] = (
        "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
    )
    agg_skip = build_aggregate_v2(
        env, date="2026-07-15", terminal_json_hash="j", terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0}, reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved"
    )
    assert any("PM1 was excluded" in lim for lim in agg_skip["limitations"])


def test_v1_historical_limitations_remain_unchanged():
    """RED TEST 5: v1 builder historical output remains unchanged and still contains
    historical limitations regardless of config.
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
            "config_pins": {
                "bias_tsv_sha256": "bias",
                "manifest_sha256": "manifest",
                "mask_ledger_sha256": "ledger",
                "remask_audit_sha256": "remask",
                "return_manifest_sha256": "return",
                "predictor_correction_counts": {"PP3": 1, "BP4": 2},
                "operational_skipped_criteria": ["PM1", "PS4"],
                "evaluation_skipped_criteria": [],  # No skip, so pm1_status == "scored"
                "oracle_thresholds": {"confidence": 0.95},
            },
        },
    }

    # Case A: Build v1 aggregate with evaluation_skipped_criteria = []
    # Even though PM1 is scored, v1 historical output MUST contain the hardcoded limitation!
    agg_noskip = build_aggregate(
        envelope,
        date="2026-07-15",
        terminal_json_hash="json",
        terminal_report_hash="text",
        published_pm1_scope={"reachable_pm1_rows": 5},
        reproduced_pm1_scope={"reachable_pm1_rows": 5},
        production_policy_status="unapproved",
    )
    assert agg_noskip["policy"]["pm1_status"] == "scored"
    assert "PM1 was excluded from this fixed evaluation after both published and reproduced resources had zero held-out-reachable rows; production PM1 remains unvalidated." in agg_noskip["limitations"]

    # Case B: Build v1 aggregate with evaluation_skipped_criteria = ["PM1"]
    envelope_skip = dict(envelope)
    envelope_skip["report"] = dict(envelope["report"])
    envelope_skip["report"]["config_pins"] = dict(envelope["report"]["config_pins"])
    envelope_skip["report"]["config_pins"]["evaluation_skipped_criteria"] = ["PM1"]
    
    agg_skip = build_aggregate(
        envelope_skip,
        date="2026-07-15",
        terminal_json_hash="json",
        terminal_report_hash="text",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )
    assert agg_skip["policy"]["pm1_status"] == "SKIPPED_ZERO_SUPPORT_BASELINE_MISMATCH"
    assert "PM1 was excluded from this fixed evaluation after both published and reproduced resources had zero held-out-reachable rows; production PM1 remains unvalidated." in agg_skip["limitations"]


# =========================================================================
# G-AG1..G-AG4 DISABLED ENVELOPE AGGREGATE CONTRACT TESTS
# =========================================================================

import pytest


def _make_g_ag_envelope(pins_overrides=None, policy_overrides=None, with_scope_gate=False) -> dict:
    _scopes = {
        "missense:pathogenic": _get_consistent_scope("missense:pathogenic", "VALIDATED"),
        "missense:benign": _get_consistent_scope("missense:benign", "VALIDATED"),
        "truncating:pathogenic": _get_consistent_scope("truncating:pathogenic", "VALIDATED"),
        "truncating:benign": _get_consistent_scope("truncating:benign", "DESCRIPTIVE"),
    }
    
    pins = {
        "bias_tsv_sha256": "bias",
        "manifest_sha256": "manifest",
        "mask_ledger_sha256": "ledger",
        "remask_audit_sha256": "remask",
        "return_manifest_sha256": "return",
        "policy_mode": "disabled_manual",
        "pp3bp4_automation_disabled": True,
        "predictor_correction_applied": False,
        "pp3bp4_suppressed_counts": {"PP3": 1, "BP4": 2},
        "pp3bp4_suppressed_variant_count": 1,
        "pp3bp4_scored_calls": 0,
        "operational_skipped_criteria": ["PM1", "PS4"],
        "evaluation_skipped_criteria": ["PM1"],
        "oracle_thresholds": make_oracle_thresholds(),
    }
    if pins_overrides:
        pins.update(pins_overrides)
        
    policy = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": "c" * 64,
        "eval_config_hash": "d" * 64,
        "lineage_policy_hash": "e" * 64,
        "packet_policy_hash": "f" * 64,
        "runtime_bundle_hash": "0" * 64,  # valid hex character '0'
        "decision_reference": "ADR-0012",
    }
    if policy_overrides:
        policy.update(policy_overrides)
        
    report = {
        "labels_snapshot": "snapshot",
        "benchmark_size": 3,
        "train_dev_size": 1,
        "holdout_size": 2,
        "holdout_label_counts": {"P": 1, "B": 1},
        "holdout_class_counts": {"missense": 2},
        "metrics": _metrics_from_scopes(_scopes) if with_scope_gate else {"missense": {"precision": 0.5}},
        "gate": {
            "status": "FAIL",
            "stratum": "missense",
            "reason": "below threshold",
            "vus_authorized": False,
            "per_stratum": {},
        },
        "config_pins": pins,
    }
    
    if with_scope_gate:
        report["scope_gate"] = {
            "schema_version": "2",
            "full_spectrum_status": "PASS",
            "full_spectrum_vus_authorized": True,
            "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
            "governance_state": "FULL_SPECTRUM",
            "governance_statement": "statement",
            "research_use_disclaimer": "disclaimer",
            "reason": "reason",
            "scopes": _scopes,
        }
        
    envelope = {
        "content_hash": "content",
        "predictor_policy": policy,
        "mask_attestation": {
            "removed_count": 2,
            "zero_survivors": True,
        },
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {"a": "hash", "b": "hash"},
        "report": report,
    }
    return envelope


def test_g_ag1_v1_build_aggregate_disabled_envelope() -> None:
    """G-AG1: build_aggregate (v1) builds aggregate from production-shaped disabled envelope."""
    envelope = _make_g_ag_envelope()
    
    aggregate = build_aggregate(
        envelope,
        date="2026-07-13",
        terminal_json_hash="json",
        terminal_report_hash="text",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="approved",
    )
    assert aggregate["status"] == "FAIL"
    policy_block = aggregate["policy"]
    assert policy_block["policy_mode"] == "disabled_manual"
    assert policy_block["pp3bp4_automation_disabled"] is True
    assert policy_block["predictor_correction_applied"] is False
    assert policy_block["pp3bp4_suppressed_counts"] == {"PP3": 1, "BP4": 2}
    assert policy_block["pp3bp4_suppressed_variant_count"] == 1
    assert policy_block["pp3bp4_scored_calls"] == 0
    assert "predictor_correction_counts" not in policy_block


def test_g_ag2_v2_build_aggregate_disabled_envelope() -> None:
    """G-AG2: build_aggregate_for_envelope handles disabled envelope and yields v2 schema."""
    from scripts.build_masked_holdout_gate_aggregate import build_aggregate_for_envelope
    envelope = _make_g_ag_envelope(with_scope_gate=True)

    aggregate = build_aggregate_for_envelope(
        envelope,
        date="2026-07-14",
        terminal_json_hash="json",
        terminal_report_hash="text",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="approved",
    )

    assert aggregate["schema"] == "raptor.tsc.masked_holdout_gate.v2"
    assert aggregate["full_spectrum_status"] == "PASS"
    assert aggregate["vus_authorized"] is True
    
    policy_block = aggregate["policy"]
    assert policy_block["policy_mode"] == "disabled_manual"
    assert policy_block["pp3bp4_automation_disabled"] is True
    assert policy_block["predictor_correction_applied"] is False
    assert policy_block["pp3bp4_suppressed_counts"] == {"PP3": 1, "BP4": 2}
    assert policy_block["pp3bp4_suppressed_variant_count"] == 1
    assert policy_block["pp3bp4_scored_calls"] == 0
    assert "predictor_correction_counts" not in policy_block


def test_g_ag3_legacy_corrected_envelope_compatibility() -> None:
    """G-AG3: legacy corrected/enabled aggregate requires and emits counts; raises KeyError if missing."""
    pins = {
        "predictor_correction_counts": {"PP3": 1, "BP4": 2},
    }
    envelope = _make_g_ag_envelope(pins_overrides=pins, policy_overrides={"schema": "bp4pp3-predictor-policy"})
    for pin in ("policy_mode", "pp3bp4_automation_disabled", "predictor_correction_applied", "pp3bp4_suppressed_counts", "pp3bp4_suppressed_variant_count", "pp3bp4_scored_calls"):
        del envelope["report"]["config_pins"][pin]
        
    aggregate = build_aggregate(
        envelope,
        date="2026-07-13",
        terminal_json_hash="json",
        terminal_report_hash="text",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="approved",
    )
    assert aggregate["policy"]["predictor_correction_counts"] == {"PP3": 1, "BP4": 2}

    del envelope["report"]["config_pins"]["predictor_correction_counts"]
    with pytest.raises(KeyError):
        build_aggregate(
            envelope,
            date="2026-07-13",
            terminal_json_hash="json",
            terminal_report_hash="text",
            published_pm1_scope={"reachable_pm1_rows": 0},
            reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="approved",
        )


@pytest.mark.parametrize("missing_pin", [
    "policy_mode",
    "pp3bp4_automation_disabled",
    "predictor_correction_applied",
    "pp3bp4_suppressed_counts",
    "pp3bp4_suppressed_variant_count",
    "pp3bp4_scored_calls"
])
def test_g_ag4_malformed_disabled_envelope_missing_pins(missing_pin) -> None:
    """G-AG4: malformed disabled envelopes missing required pins raise ValueError."""
    envelope = _make_g_ag_envelope()
    del envelope["report"]["config_pins"][missing_pin]
    with pytest.raises(ValueError):
        build_aggregate(
            envelope,
            date="2026-07-13",
            terminal_json_hash="json",
            terminal_report_hash="text",
            published_pm1_scope={"reachable_pm1_rows": 0},
            reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="approved",
        )


@pytest.mark.parametrize("bad_pin_value", [
    ("pp3bp4_scored_calls", 1),
    ("pp3bp4_automation_disabled", False),
    ("predictor_correction_applied", True),
    ("policy_mode", "active_enforced")
])
def test_g_ag4_malformed_disabled_envelope_invalid_pin_values(bad_pin_value) -> None:
    """G-AG4: malformed disabled envelopes with invalid/inconsistent pin values raise ValueError."""
    pin_name, value = bad_pin_value
    envelope = _make_g_ag_envelope(pins_overrides={pin_name: value})
    with pytest.raises(ValueError):
        build_aggregate(
            envelope,
            date="2026-07-13",
            terminal_json_hash="json",
            terminal_report_hash="text",
            published_pm1_scope={"reachable_pm1_rows": 0},
            reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="approved",
        )


def test_g_ag4_malformed_disabled_envelope_mixed_shape() -> None:
    """G-AG4: disabled envelopes with mixed shape (counts + suppression pins) raise ValueError."""
    envelope = _make_g_ag_envelope(pins_overrides={"predictor_correction_counts": {"PP3": 1}})
    with pytest.raises(ValueError):
        build_aggregate(
            envelope,
            date="2026-07-13",
            terminal_json_hash="json",
            terminal_report_hash="text",
            published_pm1_scope={"reachable_pm1_rows": 0},
            reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="approved",
        )
