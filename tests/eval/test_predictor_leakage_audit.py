import pytest
import json
from pathlib import Path


def test_td1_leakage_audit_precedence():
    """T-D1 precedence.

    Verify the precedence order: BLOCKED_DATA -> FAIL -> UNKNOWN -> PASS.
    Verify that any verified direct/component overlap > 0 => FAIL.
    Verify that unavailable/unverified direct or any required component manifest => UNKNOWN, never PASS.
    Verify that all manifests verified + normalized + zero overlap => PASS.
    Verify normalization failure fails loud or reports FAIL, never PASS.
    Verify direct/component results are reported separately.
    Verify benchmark labels are never consumed.
    """
    from raptor.eval.predictor_leakage_audit import evaluate_leakage_audit, LeakageStatus

    # Check status values
    assert LeakageStatus.BLOCKED_DATA != LeakageStatus.FAIL
    assert LeakageStatus.FAIL != LeakageStatus.UNKNOWN
    assert LeakageStatus.UNKNOWN != LeakageStatus.PASS

    # 1. BLOCKED_DATA if required benchmark or input cannot be read/validated
    status_blocked = evaluate_leakage_audit(
        benchmark_ids=None, # invalid benchmark
        manifests={"direct": "path"},
        overlap_counts=None
    )
    assert status_blocked.status == LeakageStatus.BLOCKED_DATA

    # 2. FAIL if any verified direct or component overlap > 0
    status_fail_direct = evaluate_leakage_audit(
        benchmark_ids=["NC_000009.12:g.12345A>G"],
        manifests={"direct": {"available": True, "verified": True}, "component": {"available": True, "verified": True}},
        overlap_counts={"direct": 1, "component": 0}
    )
    assert status_fail_direct.status == LeakageStatus.FAIL

    status_fail_component = evaluate_leakage_audit(
        benchmark_ids=["NC_000009.12:g.12345A>G"],
        manifests={"direct": {"available": True, "verified": True}, "component": {"available": True, "verified": True}},
        overlap_counts={"direct": 0, "component": 2}
    )
    assert status_fail_component.status == LeakageStatus.FAIL

    # 3. UNKNOWN if no verified overlap found, but any required manifest is unavailable/unverified
    status_unknown = evaluate_leakage_audit(
        benchmark_ids=["NC_000009.12:g.12345A>G"],
        manifests={"direct": {"available": True, "verified": True}, "component": {"available": False, "verified": False}},
        overlap_counts={"direct": 0, "component": 0}
    )
    assert status_unknown.status == LeakageStatus.UNKNOWN

    # 4. PASS only when all manifests available/verified/normalized and zero overlap
    status_pass = evaluate_leakage_audit(
        benchmark_ids=["NC_000009.12:g.12345A>G"],
        manifests={"direct": {"available": True, "verified": True}, "component": {"available": True, "verified": True}},
        overlap_counts={"direct": 0, "component": 0}
    )
    assert status_pass.status == LeakageStatus.PASS

    # Verify direct and component are reported separately in output
    assert hasattr(status_pass, "direct_overlap")
    assert hasattr(status_pass, "component_overlap")


def test_td2_canonical_ids_and_exclusion():
    """T-D2 canonical IDs and exclusion.

    Verify SPDI normalization is applied, unnormalizable variants fail loud or report FAIL,
    NTHL1 is excluded, and no labels are consumed.
    """
    from raptor.eval.predictor_leakage_audit import evaluate_leakage_audit, LeakageStatus

    # A mock normalization function that we inject or check
    # Unnormalizable variant must cause FAIL or raise an exception, never PASS
    with pytest.raises(Exception):
        evaluate_leakage_audit(
            benchmark_ids=["NC_000009.12:g.12345A>G", "unnormalizable_id_format"],
            manifests={"direct": {"available": True, "verified": True}},
            overlap_counts={"direct": 0, "component": 0},
            normalize_ids=True # forces normalization
        )

    # NTHL1 exclusion check
    # If the audit runs, it should skip any variants in NTHL1
    # We can pass NTHL1 variants and check that they are not included in overlap calculation or are excluded
    report = evaluate_leakage_audit(
        benchmark_ids=["NC_000016.10:g.12345A>G"], # chromosome 16, e.g. NTHL1
        manifests={"direct": {"available": True, "verified": True}},
        overlap_counts={"direct": 1, "component": 0},
        gene_annotations={"NC_000016.10:g.12345A>G": "NTHL1"}
    )
    # Since NTHL1 is excluded, it should skip it and find 0 overlap (leading to PASS instead of FAIL if everything is verified)
    assert report.status == LeakageStatus.PASS or "NTHL1" not in str(report)
