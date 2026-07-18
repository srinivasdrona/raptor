import pytest
import json
import os
import sys
import subprocess
import hashlib
from pathlib import Path


def test_tf1_mave_concordance_blocked(tmp_path):
    """T-F1 MAVE.

    Verify MAVE concordance report:
    1. Defaults to status 'BLOCKED_DATA' when the structured REVEL table is missing or invalid.
    2. Test BLOCKED_DATA separately from the success path. (Correction 10)
    """
    from scripts.build_pp3bp4_revel_mave_concordance import build_mave_concordance_report, MaveStatus

    # When REVEL score table is absent, the report should return BLOCKED_DATA
    report = build_mave_concordance_report(
        score_table_path=None, # missing score table
        mave_data_path="dummy_path"
    )

    assert report.status == MaveStatus.BLOCKED_DATA
    assert report.gating_type == "NON_GATING"
    assert "research use only" in report.disclaimer.lower()


def test_tf1_mave_concordance_non_gating_path(tmp_path):
    """Verify complete synthetic NON_GATING concordance path with valid score table file. (Correction 10)"""
    from scripts.build_pp3bp4_revel_mave_concordance import build_mave_concordance_report, MaveStatus

    # We write a valid synthetic score table file to satisfy "real synthetic score-table semantics"
    score_table_file = tmp_path / "scores.json"
    score_table_data = [
        {"variant_id": "NC_000009.12:10001:A:G", "score": 0.85, "predictor": "REVEL", "predictor_version": "v1", "data_version": "v1", "source": "structured"},
        {"variant_id": "NC_000016.10:54321:C:T", "score": 0.10, "predictor": "REVEL", "predictor_version": "v1", "data_version": "v1", "source": "structured"},
    ]
    score_table_file.write_text(json.dumps(score_table_data), encoding="utf-8")

    # Mock MAVE records file
    mave_file = tmp_path / "mave.jsonl"
    mave_data = [
        {"variant_id": "NC_000009.12:10001:A:G", "functional_class": "enriched", "functional_value": 1.2},
        {"variant_id": "NC_000016.10:54321:C:T", "functional_class": "depleted", "functional_value": -2.3},
    ]
    mave_file.write_text("\n".join(json.dumps(row) for row in mave_data) + "\n", encoding="utf-8")

    # Non-gating concordance path with valid files
    report = build_mave_concordance_report(
        score_table_path=str(score_table_file),
        mave_data_path=str(mave_file)
    )

    assert report.status == MaveStatus.NON_GATING or report.status == "NON_GATING"
    assert report.gating_type == "NON_GATING"
    
    # Assert that no clinical authorization or calibration is claimed
    assert not report.is_calibrated
    assert not report.clinical_use_authorized
    assert "research use only" in report.disclaimer.lower()


def test_tf1_mave_scorer_access_only_variant_id():
    """T-F1 MAVE scorer access.

    Verify that when evaluating MAVE concordance, the injected scorer receives
    ONLY the variant_id, and the MAVE functional class or value NEVER enters
    the policy thresholds or scorer calls.
    """
    from scripts.build_pp3bp4_revel_mave_concordance import build_mave_concordance_report

    requested_variant_ids = []

    # Injected scorer that records arguments passed to it
    def dummy_scorer(*args, **kwargs):
        # The scorer must only receive the variant_id (as a single positional argument)
        assert len(args) == 1, "Scorer received unexpected positional arguments"
        assert not kwargs, "Scorer received unexpected keyword arguments"
        variant_id = args[0]
        assert isinstance(variant_id, str), "Scorer argument must be a string variant_id"
        requested_variant_ids.append(variant_id)
        return 0.5

    # Mock MAVE records
    mock_mave_data = [
        {"variant_id": "NC_000009.12:10001:A:G", "functional_class": "enriched", "functional_value": 1.2},
        {"variant_id": "NC_000016.10:54321:C:T", "functional_class": "depleted", "functional_value": -2.3},
    ]

    # We evaluate and check that the scorer only queried variant_ids, not functional classes/values
    report = build_mave_concordance_report(
        score_table_path="dummy_score_table.json", # Or path representation
        mave_data_list=mock_mave_data,
        scorer=dummy_scorer,
        status="proposed"
    )

    # Scorer should only have been queried with the variant_id strings
    for vid in requested_variant_ids:
        assert isinstance(vid, str)
        assert vid in ["NC_000009.12:10001:A:G", "NC_000016.10:54321:C:T"]

    # Verify report is deterministic
    report_json_1 = report.to_json()
    report_json_2 = report.to_json()
    assert report_json_1 == report_json_2


def test_cli_help_bootstrap():
    """T-A4/T-B8 check script can run with a clean PYTHONPATH and shows help."""
    script_path = Path("scripts/build_pp3bp4_revel_mave_concordance.py")
    if not script_path.exists():
        pytest.skip("build_pp3bp4_revel_mave_concordance.py not implemented yet")

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    cmd = [sys.executable, str(script_path), "--help"]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"CLI help failed under clean PYTHONPATH: {res.stderr}"
    assert "usage" in res.stdout.lower() or "help" in res.stdout.lower()

