import pytest
import json
import hashlib
from pathlib import Path


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
    
    # Assert status is UNKNOWN
    assert data["status"] == "UNKNOWN"

    # Closed schema validation
    expected_fields = {"schema", "status", "direct_overlap", "component_overlap", "checked_at", "policy_source_sha256", "content_hash"}
    for k in data.keys():
        assert k in expected_fields, f"Unexpected field {k} in closed schema of {path}"

    # No held-out/VUS claim
    assert "heldout" not in data
    assert "vus_claims" not in data


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

    assert data["status"] == "BLOCKED_DATA"

    # Must list verified missing prerequisites
    missing = data.get("missing_prerequisites", [])
    assert len(missing) >= 4
    assert any("reference" in m.lower() or "fasta" in m.lower() for m in missing)
    assert any("nirvana" in m.lower() or "dbnsfp" in m.lower() or "annotation" in m.lower() for m in missing)
    assert any("version" in m.lower() for m in missing)
    assert any("license" in m.lower() for m in missing)


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

    assert data["status"] == "BLOCKED_DATA"
    assert data["power_status"] == "UNDERPOWERED" or data["power"] == "UNDERPOWERED"


def test_artifact_revel_mave_concordance_exists_and_valid():
    """Verify data/census/tsc2_pp3bp4_revel_mave_concordance_2026-07.json.

    - Must exist
    - status must be BLOCKED_DATA or NON_GATING
    - gating_type must be NON_GATING
    """
    path = Path("data/census/tsc2_pp3bp4_revel_mave_concordance_2026-07.json")
    if not path.exists():
        pytest.fail(f"Missing required generated artifact: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["status"] in {"BLOCKED_DATA", "NON_GATING"}
    assert data["gating_type"] == "NON_GATING"
