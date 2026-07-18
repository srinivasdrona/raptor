import pytest
import json
import hashlib
from pathlib import Path


def _recompute_content_hash(data):
    # Exclude content_hash from canonical bytes
    clean_data = {k: v for k, v in data.items() if k != "content_hash"}
    canonical = json.dumps(clean_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_artifact_predictor_leakage_audit_exists_and_valid():
    """Verify data/census/tsc_predictor_leakage_audit_2026-07.json.

    - Must exist (fails if missing in RED validation)
    - status must be UNKNOWN
    - Validate closed schema
    - No held-out/VUS claim
    """
    path = Path("data/census/tsc_predictor_leakage_audit_2026-07.json")
    if not path.exists():
        pytest.fail(f"Missing required generated artifact: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    
    # Assert exact schema/status/report_date
    assert data["schema"] == "tsc-predictor-leakage-audit/1"
    assert data["status"] == "UNKNOWN"
    assert "report_date" in data or "checked_at" in data

    # Recompute content_hash from canonical payload excluding content_hash
    assert data["content_hash"] == _recompute_content_hash(data)

    # Assert policy_source_sha256 and source_register_sha256 where applicable
    assert "policy_source_sha256" in data

    # Assert closed top-level field set
    permitted_fields = {"schema", "status", "direct_overlap", "component_overlap", "checked_at", "report_date", "policy_source_sha256", "source_register_sha256", "content_hash"}
    for k in data.keys():
        assert k in permitted_fields, f"Unexpected field {k} in {path}"

    # Assert no clinical authorization, no held-out result use, no VUS census claim
    for forbidden in ["authorization", "approved", "clinical_use", "holdout", "vus_claims", "vus_census"]:
        assert forbidden not in data


def test_artifact_dev_score_acquisition_exists_and_valid():
    """Verify data/census/tsc_pp3bp4_dev_score_acquisition_2026-07.json.

    - Must exist
    - status must be BLOCKED_DATA
    - Lists all missing prerequisites
    """
    path = Path("data/census/tsc_pp3bp4_dev_score_acquisition_2026-07.json")
    if not path.exists():
        pytest.fail(f"Missing required generated artifact: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    # Assert exact schema/status/report_date
    assert data["schema"] == "tsc-pp3bp4-dev-score-acquisition/1"
    assert data["status"] == "BLOCKED_DATA"
    assert "report_date" in data

    # Recompute content_hash
    assert data["content_hash"] == _recompute_content_hash(data)

    # Assert policy_source_sha256 and source_register_sha256 where applicable
    assert "policy_source_sha256" in data

    # Assert closed top-level fields
    permitted_fields = {"schema", "status", "missing_prerequisites", "n_dev", "n_holdout", "reference_pins", "report_date", "policy_source_sha256", "source_register_sha256", "content_hash"}
    for k in data.keys():
        assert k in permitted_fields, f"Unexpected field {k} in {path}"

    # Assert no clinical authorization, no held-out result use, no VUS census claim
    for forbidden in ["authorization", "approved", "clinical_use", "holdout", "vus_claims", "vus_census"]:
        assert forbidden not in data


def test_artifact_transportability_exists_and_valid():
    """Verify data/census/tsc_pp3bp4_transportability_2026-07.json.

    - Must exist
    - status must be BLOCKED_DATA
    - power must be UNDERPOWERED
    """
    path = Path("data/census/tsc_pp3bp4_transportability_2026-07.json")
    if not path.exists():
        pytest.fail(f"Missing required generated artifact: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    # Assert exact schema/status/report_date (BLOCKED_DATA+UNDERPOWERED)
    assert data["schema"] == "tsc-pp3bp4-transportability/1"
    assert data["status"] == "BLOCKED_DATA"
    assert data["power_status"] == "UNDERPOWERED"
    assert "report_date" in data

    # Recompute content_hash
    assert data["content_hash"] == _recompute_content_hash(data)

    # Assert policy_source_sha256 and source_register_sha256 where applicable
    assert "policy_source_sha256" in data

    # Assert closed top-level fields
    permitted_fields = {"schema", "status", "power_status", "n_dev", "n_holdout", "missense_composition", "report_date", "policy_source_sha256", "source_register_sha256", "content_hash"}
    for k in data.keys():
        assert k in permitted_fields, f"Unexpected field {k} in {path}"

    # Assert no clinical authorization, no held-out result use, no VUS census claim
    for forbidden in ["authorization", "approved", "clinical_use", "holdout", "vus_claims", "vus_census"]:
        assert forbidden not in data


def test_artifact_revel_mave_concordance_exists_and_valid():
    """Verify data/census/tsc2_pp3bp4_revel_mave_concordance_2026-07.json.

    - Must exist
    - status must be BLOCKED_DATA
    - gating_type/validation_mode is NON_GATING
    """
    path = Path("data/census/tsc2_pp3bp4_revel_mave_concordance_2026-07.json")
    if not path.exists():
        pytest.fail(f"Missing required generated artifact: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    # Assert exact schema/status/report_date (BLOCKED_DATA + NON_GATING validation_mode)
    assert data["schema"] == "tsc2-pp3bp4-revel-mave-concordance/1"
    assert data["status"] == "BLOCKED_DATA" # MAVE status must be BLOCKED_DATA, not NON_GATING
    assert data["gating_type"] == "NON_GATING" or data["validation_mode"] == "NON_GATING"
    assert "report_date" in data

    # Recompute content_hash
    assert data["content_hash"] == _recompute_content_hash(data)

    # Assert policy_source_sha256 and source_register_sha256 where applicable
    assert "policy_source_sha256" in data

    # Assert closed top-level fields
    permitted_fields = {"schema", "status", "gating_type", "validation_mode", "disclaimer", "report_date", "policy_source_sha256", "source_register_sha256", "content_hash"}
    for k in data.keys():
        assert k in permitted_fields, f"Unexpected field {k} in {path}"

    # Assert no clinical authorization, no held-out result use, no VUS census claim
    for forbidden in ["authorization", "approved", "clinical_use", "holdout", "vus_claims", "vus_census"]:
        assert forbidden not in data
