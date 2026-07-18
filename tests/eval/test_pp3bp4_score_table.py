import pytest
import json
import hashlib
from pathlib import Path


# Helper to generate mock dev IDs
def _get_mock_dev_ids(n=1104):
    return [f"NC_000009.12:g.{10000 + i}A>G" for i in range(n)]


# Helper to compute SHA256 of sorted IDs
def _compute_ids_hash(ids):
    sorted_ids = sorted(ids)
    hasher = hashlib.sha256()
    for vid in sorted_ids:
        hasher.update(vid.encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def test_ts1_score_table_success(tmp_path):
    """T-S1 score-table success & coverage conservation.

    Verifies a valid score table with 1104 dev IDs can be loaded, validates properly,
    preserves missing rows instead of silent row loss, and maintains the conservation
    invariant n_scored + n_missing == 1104.
    """
    from raptor.eval.pp3bp4_score_table import load_and_validate_score_table
    from raptor.eval.pp3bp4_candidate_policy import CandidatePolicy

    dev_ids = _get_mock_dev_ids(1104)
    dev_hash = _compute_ids_hash(dev_ids)

    # Mock policy
    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "confirm-pending-revel-dbnsfp-release"
        data_version = "confirm-pending-dbnsfp-release"

    policy = DummyPolicy()

    # Create score table data: 1000 scored, 104 missing
    rows_data = []
    for i in range(1000):
        rows_data.append({
            "variant_id": dev_ids[i],
            "score": 0.5,
            "predictor": "REVEL",
            "predictor_version": "confirm-pending-revel-dbnsfp-release",
            "data_version": "confirm-pending-dbnsfp-release",
            "source": "structured",
            "transcript": "NM_000051.4",
            "consequence": "missense_variant"
        })
    # Missing 104 rows
    for i in range(1000, 1104):
        rows_data.append({
            "variant_id": dev_ids[i],
            "score": None, # recorded missing
            "predictor": "REVEL",
            "predictor_version": "confirm-pending-revel-dbnsfp-release",
            "data_version": "confirm-pending-dbnsfp-release",
            "source": "structured",
            "transcript": "NM_000051.4",
            "consequence": "missense_variant"
        })

    # Table content hash
    content_hasher = hashlib.sha256()
    content_hasher.update(json.dumps(rows_data, sort_keys=True).encode("utf-8"))
    table_hash = content_hasher.hexdigest()

    sidecar_data = {
        "schema": "pp3bp4-revel-score-table/1",
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "license": "non-commercial",
        "dev_id_set_sha256": dev_hash,
        "table_content_sha256": table_hash,
        "n_dev": 1104,
        "n_scored": 1000,
        "n_missing": 104,
        "coverage": 1000 / 1104,
        "reference_pins": ["NC_000009.12"],
        "generated_at": "2026-07-19T00:00:00Z",
        "snapshot": "clinvar_2026-07-07"
    }

    # Run validation
    rows, attestation = load_and_validate_score_table(rows_data, sidecar_data, dev_ids=dev_ids, policy=policy)

    assert len(rows) == 1104
    assert attestation.n_dev == 1104
    assert attestation.n_scored == 1000
    assert attestation.n_missing == 104
    assert attestation.n_scored + attestation.n_missing == 1104
    assert attestation.dev_id_set_sha256 == dev_hash
    assert attestation.table_content_sha256 == table_hash


def test_ts1_score_table_failures(tmp_path):
    """T-S1 score-table failure modes.

    Tests that duplicate IDs, extra IDs, held-out IDs, nonfinite/out-of-range scores,
    version mismatch, raw coordinates, and bias_rationale source are all loudly rejected.
    """
    from raptor.eval.pp3bp4_score_table import load_and_validate_score_table, ScoreTableValidationError

    dev_ids = _get_mock_dev_ids(1104)
    dev_hash = _compute_ids_hash(dev_ids)

    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "v1"
        data_version = "v1"

    policy = DummyPolicy()

    # Helper to generate basic valid rows
    def get_valid_rows():
        return [{
            "variant_id": vid,
            "score": 0.5,
            "predictor": "REVEL",
            "predictor_version": "v1",
            "data_version": "v1",
            "source": "structured"
        } for vid in dev_ids]

    sidecar = {
        "schema": "pp3bp4-revel-score-table/1",
        "predictor": "REVEL",
        "predictor_version": "v1",
        "data_version": "v1",
        "license": "non-commercial",
        "dev_id_set_sha256": dev_hash,
        "table_content_sha256": "placeholder",
        "n_dev": 1104,
        "n_scored": 1104,
        "n_missing": 0,
        "coverage": 1.0,
        "reference_pins": ["NC_000009.12"],
        "generated_at": "2026-07-19T00:00:00Z",
        "snapshot": "clinvar_2026-07-07"
    }

    # 1. Duplicate variant_id in score table
    bad_rows = get_valid_rows()
    bad_rows[1]["variant_id"] = bad_rows[0]["variant_id"]
    with pytest.raises(ScoreTableValidationError, match="duplicate"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 2. Extra ID not in dev set
    bad_rows = get_valid_rows()
    bad_rows[0]["variant_id"] = "NC_000009.12:g.99999A>G" # extra
    with pytest.raises(ScoreTableValidationError, match="extra|dev set"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 3. Held-out ID present
    bad_rows = get_valid_rows()
    # Let's say NC_000009.12:g.20000A>G is a held-out ID
    bad_rows[0]["variant_id"] = "NC_000009.12:g.20000A>G"
    # Ensure it's treated as heldout by adding to dev_ids or checking against holdout set
    # In any case, a heldout ID should be rejected if it's explicitly labeled or identified
    # The loader must reject if an ID is outside dev (which NC_000009.12:g.20000A>G is)
    with pytest.raises(ScoreTableValidationError, match="extra|heldout|dev set"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 4. Out-of-range score
    bad_rows = get_valid_rows()
    bad_rows[0]["score"] = 1.5 # out of [0, 1]
    with pytest.raises(ScoreTableValidationError, match="range|finite"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    bad_rows = get_valid_rows()
    bad_rows[0]["score"] = float("nan")
    with pytest.raises(ScoreTableValidationError, match="finite|range"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 5. Version mismatch (predictor_version or data_version ≠ policy pins)
    bad_rows = get_valid_rows()
    bad_rows[0]["predictor_version"] = "wrong-version"
    with pytest.raises(ScoreTableValidationError, match="version"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    bad_sidecar = sidecar.copy()
    bad_sidecar["predictor_version"] = "wrong-version"
    with pytest.raises(ScoreTableValidationError, match="version"):
        load_and_validate_score_table(get_valid_rows(), bad_sidecar, dev_ids=dev_ids, policy=policy)

    # 6. Raw coordinates (not canonical SPDI)
    bad_rows = get_valid_rows()
    bad_rows[0]["variant_id"] = "chr9:12345:A:G" # raw coords, not NC_000009.12:g.12345A>G
    with pytest.raises(ScoreTableValidationError, match="SPDI|format|canonical"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 7. Source is bias_rationale
    bad_rows = get_valid_rows()
    bad_rows[0]["source"] = "bias_rationale"
    with pytest.raises(ScoreTableValidationError, match="bias_rationale"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)


def test_ts2_attestation_fields():
    """T-S2 attestation structure.

    Verify that ScoreTableAttestation has the required fields.
    """
    from raptor.eval.pp3bp4_score_table import ScoreTableAttestation

    # Let's inspect the fields in ScoreTableAttestation class
    fields = ScoreTableAttestation.__dataclass_fields__ if hasattr(ScoreTableAttestation, "__dataclass_fields__") else {}
    expected_fields = {
        "schema", "predictor", "predictor_version", "data_version", "license",
        "dev_id_set_sha256", "table_content_sha256", "n_dev", "n_scored",
        "n_missing", "coverage", "reference_pins", "generated_at", "snapshot"
    }
    for f in expected_fields:
        assert f in fields, f"ScoreTableAttestation missing field: {f}"
