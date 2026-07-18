import pytest
import json
import hashlib
from pathlib import Path


# Helper to generate mock dev IDs as canonical SPDI strings (Correction 3)
def _get_mock_dev_ids(n=1104):
    return [f"NC_000009.12:{10000 + i}:T:C" for i in range(n)]


# Helper to compute SHA256 of sorted IDs
def _compute_ids_hash(ids):
    sorted_ids = sorted(ids)
    hasher = hashlib.sha256()
    for vid in sorted_ids:
        hasher.update(vid.encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


# Helper to serialize JSON compactly and canonically (Correction 5)
def _compact_canonical_json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_ts1_score_table_success(tmp_path):
    """T-S1 score-table success & coverage conservation.

    Verifies a valid score table with 1104 dev IDs can be loaded, validates properly,
    preserves missing rows instead of silent row loss, and maintains the conservation
    invariant n_scored + n_missing == 1104.
    """
    from raptor.eval.pp3bp4_score_table import load_and_validate_score_table

    dev_ids = _get_mock_dev_ids(1104)
    dev_hash = _compute_ids_hash(dev_ids)

    # Mock policy
    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "confirm-pending-revel-dbnsfp-release"
        data_version = "confirm-pending-dbnsfp-release"

    policy = DummyPolicy()

    # Create score table data: 1000 scored, 104 missing
    # Closed row schema: NO ad hoc 'gene' field allowed! (Correction 5)
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

    # Table content hash using compact canonical JSON algorithm (Correction 5)
    table_hash = hashlib.sha256(_compact_canonical_json(rows_data)).hexdigest()

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

    # Helper to generate basic valid rows (no ad hoc gene field)
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
    bad_rows[0]["variant_id"] = "NC_000009.12:99999:T:C" # extra SPDI, not in dev set
    with pytest.raises(ScoreTableValidationError, match="extra|dev set"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 3. Held-out ID present
    bad_rows = get_valid_rows()
    bad_rows[0]["variant_id"] = "NC_000009.12:20000:T:C" # a heldout ID
    with pytest.raises(ScoreTableValidationError, match="extra|heldout|dev set"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 4. Out-of-range score
    bad_rows = get_valid_rows()
    bad_rows[0]["score"] = 1.5 # out of [0, 1]
    with pytest.raises(ScoreTableValidationError, match="range|finite"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # Infinity/NaN (Correction 5)
    bad_rows = get_valid_rows()
    bad_rows[0]["score"] = float("inf")
    with pytest.raises(ScoreTableValidationError, match="finite|range"):
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

    # 6. Reject HGVS :g. and raw chr:pos:ref:alt coordinates (Correction 3)
    bad_rows = get_valid_rows()
    bad_rows[0]["variant_id"] = "NC_000009.12:g.12345A>G" # HGVS rejected as score-table ID
    with pytest.raises(ScoreTableValidationError, match="SPDI|format|canonical"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    bad_rows = get_valid_rows()
    bad_rows[0]["variant_id"] = "chr9:12345:A:G" # raw coords rejected as score-table ID
    with pytest.raises(ScoreTableValidationError, match="SPDI|format|canonical"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 7. Source is bias_rationale
    bad_rows = get_valid_rows()
    bad_rows[0]["source"] = "bias_rationale"
    with pytest.raises(ScoreTableValidationError, match="bias_rationale"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 8. Row contains bool-as-number (Correction 5)
    bad_rows = get_valid_rows()
    bad_rows[0]["score"] = True # bool-as-number
    with pytest.raises(ScoreTableValidationError, match="type|bool|number"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 9. Closed schema: row contains ad hoc 'gene' field (Correction 5)
    bad_rows = get_valid_rows()
    bad_rows[0]["gene"] = "TSC2" # forbidden ad hoc row field
    with pytest.raises(ScoreTableValidationError, match="closed schema|extra field|gene"):
        load_and_validate_score_table(bad_rows, sidecar, dev_ids=dev_ids, policy=policy)


def test_ts1_missing_or_extra_sidecar_fields():
    """Verify any missing or extra sidecar fields are loudly rejected."""
    from raptor.eval.pp3bp4_score_table import load_and_validate_score_table, ScoreTableValidationError

    dev_ids = _get_mock_dev_ids(1104)
    dev_hash = _compute_ids_hash(dev_ids)

    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "v1"
        data_version = "v1"

    policy = DummyPolicy()

    valid_rows = [{
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

    # Missing field
    missing_sidecar = sidecar.copy()
    del missing_sidecar["dev_id_set_sha256"]
    with pytest.raises(ScoreTableValidationError, match="missing|field"):
        load_and_validate_score_table(valid_rows, missing_sidecar, dev_ids=dev_ids, policy=policy)

    # Extra field
    extra_sidecar = sidecar.copy()
    extra_sidecar["unexpected_field"] = "value"
    with pytest.raises(ScoreTableValidationError, match="extra|unexpected|field"):
        load_and_validate_score_table(valid_rows, extra_sidecar, dev_ids=dev_ids, policy=policy)


def test_ts2_attestation_fields():
    """T-S2 attestation structure.

    Verify that ScoreTableAttestation has the required fields.
    """
    from raptor.eval.pp3bp4_score_table import ScoreTableAttestation

    fields = ScoreTableAttestation.__dataclass_fields__ if hasattr(ScoreTableAttestation, "__dataclass_fields__") else {}
    expected_fields = {
        "schema", "predictor", "predictor_version", "data_version", "license",
        "dev_id_set_sha256", "table_content_sha256", "n_dev", "n_scored",
        "n_missing", "coverage", "reference_pins", "generated_at", "snapshot"
    }
    for f in expected_fields:
        assert f in fields, f"ScoreTableAttestation missing field: {f}"

