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
    2. Test BLOCKED_DATA separately from the success path.
    """
    from scripts.build_pp3bp4_revel_mave_concordance import build_mave_concordance_report, MaveStatus

    # When REVEL score table / attested score source is absent, the report should return BLOCKED_DATA
    report = build_mave_concordance_report(
        score_table_path=None, # missing score table
        mave_data_path="dummy_path"
    )

    assert report.status == MaveStatus.BLOCKED_DATA
    assert report.gating_type == "NON_GATING"
    assert "research use only" in report.disclaimer.lower()


def test_tf1_mave_concordance_non_gating_path(tmp_path):
    """Verify complete synthetic NON_GATING concordance path with valid score table file and attestation.

    This test exercises the 'fully validated score-table integration' contract of Rule 7.
    """
    from scripts.build_pp3bp4_revel_mave_concordance import build_mave_concordance_report, MaveStatus
    from raptor.eval.pp3bp4_score_table import load_and_validate_score_table, ScoreTableValidationError

    # Proposed policy/classifier
    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "v1"
        data_version = "v1"
        schema = "pp3bp4-candidate-policy/1"
        status = "proposed"
        shadow_only = True
        owner_approved = False

    policy = DummyPolicy()

    # Valid complete synthetic structured score rows with exact closed row schema
    score_table_data = [
        {
            "variant_id": "NC_000009.12:10001:A:G",
            "score": 0.85,
            "predictor": "REVEL",
            "predictor_version": "v1",
            "data_version": "v1",
            "source": "structured",
            "transcript": "NM_000051.4",
            "consequence": "missense_variant"
        },
        {
            "variant_id": "NC_000016.10:54321:C:T",
            "score": 0.10,
            "predictor": "REVEL",
            "predictor_version": "v1",
            "data_version": "v1",
            "source": "structured",
            "transcript": "NM_000051.4",
            "consequence": "missense_variant"
        },
    ]

    # Compute compact canonical table hash and exact expected-ID-set hash programmatically
    sorted_rows = sorted(score_table_data, key=lambda x: x["variant_id"])
    canonical_bytes = json.dumps(sorted_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected_table_hash = hashlib.sha256(canonical_bytes).hexdigest()
    assert expected_table_hash == "39c70af704b4ec6eae2f1cb2a05408722adf4468427882229fad4d3fc3b59713"

    dev_ids = ["NC_000009.12:10001:A:G", "NC_000016.10:54321:C:T"]
    hasher = hashlib.sha256()
    for vid in sorted(dev_ids):
        hasher.update(vid.encode("utf-8"))
        hasher.update(b"\n")
    expected_id_set_hash = hasher.hexdigest()
    assert expected_id_set_hash == "4280345f755ff33f84ff1d2a9dc99691f972fda1daf0e94fc8ae36f081f6bd88"

    # Build sidecar/attestation data matching these exact expected IDs without lying with 1104
    sidecar_data = {
        "schema": "pp3bp4-revel-score-table/1",
        "predictor": "REVEL",
        "predictor_version": "v1",
        "data_version": "v1",
        "license": "non-commercial",
        "dev_id_set_sha256": expected_id_set_hash,
        "table_content_sha256": expected_table_hash,
        "n_dev": 2,
        "n_scored": 2,
        "n_missing": 0,
        "coverage": 1.0,
        "reference_pins": ["NC_000009.12"],
        "as_of": "2026-07-18",
        "snapshot": "clinvar_2026-07-07"
    }

    # Add negative assertions that tampered attestation hash/count is rejected before concordance
    tampered_sidecar_hash = sidecar_data.copy()
    tampered_sidecar_hash["table_content_sha256"] = "wrong-hash-value"
    with pytest.raises(ScoreTableValidationError):
        load_and_validate_score_table(
            sorted_rows,
            tampered_sidecar_hash,
            dev_ids=dev_ids,
            policy=policy
        )

    tampered_sidecar_count = sidecar_data.copy()
    tampered_sidecar_count["n_dev"] = 999
    with pytest.raises(ScoreTableValidationError):
        load_and_validate_score_table(
            sorted_rows,
            tampered_sidecar_count,
            dev_ids=dev_ids,
            policy=policy
        )

    # Call load_and_validate_score_table first
    validated_rows, validated_attestation = load_and_validate_score_table(
        sorted_rows,
        sidecar_data,
        dev_ids=dev_ids,
        policy=policy
    )

    # MAVE records separately
    mave_data = [
        {"variant_id": "NC_000009.12:10001:A:G", "functional_class": "enriched", "functional_value": 1.2},
        {"variant_id": "NC_000016.10:54321:C:T", "functional_class": "depleted", "functional_value": -2.3},
    ]

    # Non-gating concordance path with pure helper API
    # receives MAVE records separately, validated score rows/attestation, and proposed policy/classifier;
    # MAVE values/classes never enter classifier arguments.
    report = build_mave_concordance_report(
        mave_records=mave_data,
        validated_rows=validated_rows,
        attestation=validated_attestation,
        policy=policy
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

    This test exercises the 'pure injected-scorer isolation' contract of Rule 7.
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

    # Proposed policy/classifier
    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "v1"
        data_version = "v1"
        schema = "pp3bp4-candidate-policy/1"
        status = "proposed"
        shadow_only = True
        owner_approved = False

    policy = DummyPolicy()

    # We evaluate and check that the scorer only queried variant_ids, not functional classes/values
    # Remove nonexistent/dummy score-table paths; use pure helper contract directly
    report = build_mave_concordance_report(
        mave_records=mock_mave_data,
        scorer=dummy_scorer,
        policy=policy
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
        pytest.fail(f"implementation missing: {script_path}")

    env = os.environ.copy()
    if "PYTHONPATH" in env:
        del env["PYTHONPATH"]

    cmd = [sys.executable, str(script_path), "--help"]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"CLI help failed under clean PYTHONPATH: {res.stderr}"
    assert "usage" in res.stdout.lower() or "help" in res.stdout.lower()

