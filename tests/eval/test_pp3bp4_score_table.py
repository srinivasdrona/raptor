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


# Helper to canonicalize, sort by variant_id, recompute counts, hash, and update sidecar
def _canonicalize_rows_and_rebuild_sidecar(rows, sidecar_template):
    # Ensure every row has a closed, consistent schema: transcript and consequence keys are required
    rebuilt_rows = []
    for r in rows:
        row_copy = r.copy()
        if "transcript" not in row_copy:
            row_copy["transcript"] = "NM_000051.4"
        if "consequence" not in row_copy:
            row_copy["consequence"] = "missense_variant"
        rebuilt_rows.append(row_copy)
    
    # Row-order invariance: sort rows by variant_id before hashing
    sorted_rows = sorted(rebuilt_rows, key=lambda x: x["variant_id"])
    
    n_total = len(sorted_rows)
    n_scored = sum(1 for r in sorted_rows if r.get("score") is not None)
    n_missing = n_total - n_scored
    coverage = n_scored / n_total if n_total > 0 else 1.0
    
    canonical_bytes = json.dumps(sorted_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    table_hash = hashlib.sha256(canonical_bytes).hexdigest()
    
    sidecar = sidecar_template.copy()
    sidecar["n_scored"] = n_scored
    sidecar["n_missing"] = n_missing
    sidecar["coverage"] = coverage
    sidecar["table_content_sha256"] = table_hash
    if "generated_at" in sidecar:
        del sidecar["generated_at"]
    sidecar["as_of"] = "2026-07-18"
    
    return sorted_rows, sidecar


def test_ts1_score_table_success(tmp_path):
    """T-S1 score-table success & coverage conservation.

    Verifies a valid score table with 1104 dev IDs can be loaded, validates properly,
    preserves missing rows instead of silent row loss, and maintains the conservation
    invariant n_scored + n_missing == 1104.
    """
    from raptor.eval.pp3bp4_score_table import load_and_validate_score_table

    dev_ids = _get_mock_dev_ids(1104)
    dev_hash = _compute_ids_hash(dev_ids)

    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "confirm-pending-revel-dbnsfp-release"
        data_version = "confirm-pending-dbnsfp-release"

    policy = DummyPolicy()

    # Closed row schema: require transcript and consequence
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
    for i in range(1000, 1104):
        rows_data.append({
            "variant_id": dev_ids[i],
            "score": None,
            "predictor": "REVEL",
            "predictor_version": "confirm-pending-revel-dbnsfp-release",
            "data_version": "confirm-pending-dbnsfp-release",
            "source": "structured",
            "transcript": "NM_000051.4",
            "consequence": "missense_variant"
        })

    sidecar_template = {
        "schema": "pp3bp4-revel-score-table/1",
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "license": "non-commercial",
        "dev_id_set_sha256": dev_hash,
        "n_dev": 1104,
        "reference_pins": ["NC_000009.12"],
        "snapshot": "clinvar_2026-07-07"
    }

    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(rows_data, sidecar_template)

    # Run validation
    rows, attestation = load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    assert len(rows) == 1104
    assert attestation.n_dev == 1104
    assert attestation.n_scored == 1000
    assert attestation.n_missing == 104
    assert attestation.n_scored + attestation.n_missing == 1104
    assert attestation.dev_id_set_sha256 == dev_hash
    assert attestation.table_content_sha256 == sidecar["table_content_sha256"]
    assert attestation.as_of == "2026-07-18"


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

    # Helper to generate basic valid rows (transcript/consequence required)
    def get_valid_rows():
        return [{
            "variant_id": vid,
            "score": 0.5,
            "predictor": "REVEL",
            "predictor_version": "v1",
            "data_version": "v1",
            "source": "structured",
            "transcript": "NM_000051.4",
            "consequence": "missense_variant"
        } for vid in dev_ids]

    sidecar_template = {
        "schema": "pp3bp4-revel-score-table/1",
        "predictor": "REVEL",
        "predictor_version": "v1",
        "data_version": "v1",
        "license": "non-commercial",
        "dev_id_set_sha256": dev_hash,
        "n_dev": 1104,
        "reference_pins": ["NC_000009.12"],
        "snapshot": "clinvar_2026-07-07"
    }

    # 1. Duplicate variant_id in score table
    bad_rows = get_valid_rows()
    bad_rows[1]["variant_id"] = bad_rows[0]["variant_id"]
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="duplicate"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 2. Extra ID not in dev set
    bad_rows = get_valid_rows()
    bad_rows[0]["variant_id"] = "NC_000009.12:99999:T:C"
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="extra|dev set"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 3. Held-out ID present
    bad_rows = get_valid_rows()
    bad_rows[0]["variant_id"] = "NC_000009.12:20000:T:C"
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="extra|heldout|dev set"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 4. Out-of-range score
    bad_rows = get_valid_rows()
    bad_rows[0]["score"] = 1.5
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="range|finite"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # Infinity/NaN
    bad_rows = get_valid_rows()
    bad_rows[0]["score"] = float("inf")
    # For infinity/NaN we also recompute sidecar hashes properly
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="finite|range"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    bad_rows = get_valid_rows()
    bad_rows[0]["score"] = float("nan")
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="finite|range"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 5. Version mismatch
    bad_rows = get_valid_rows()
    bad_rows[0]["predictor_version"] = "wrong-version"
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="version"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    bad_sidecar_template = sidecar_template.copy()
    bad_sidecar_template["predictor_version"] = "wrong-version"
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(get_valid_rows(), bad_sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="version"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 6. Reject HGVS and raw coordinates
    bad_rows = get_valid_rows()
    bad_rows[0]["variant_id"] = "NC_000009.12:g.12345A>G"
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="SPDI|format|canonical"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    bad_rows = get_valid_rows()
    bad_rows[0]["variant_id"] = "9:12345:A:G" # Raw coordinate
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="SPDI|format|canonical"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 7. Source is bias_rationale
    bad_rows = get_valid_rows()
    bad_rows[0]["source"] = "bias_rationale"
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="bias_rationale"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 8. Row contains bool-as-number
    bad_rows = get_valid_rows()
    bad_rows[0]["score"] = True
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="type|bool|number"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 9. Closed schema: row contains extra 'gene' field
    bad_rows = get_valid_rows()
    bad_rows[0]["gene"] = "TSC2"
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(bad_rows, sidecar_template)
    with pytest.raises(ScoreTableValidationError, match="closed schema|extra field|gene"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)

    # 10. Hash mismatch specific test
    valid_rows = get_valid_rows()
    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(valid_rows, sidecar_template)
    sidecar["table_content_sha256"] = "wrong_hash" # target is hash mismatch!
    with pytest.raises(ScoreTableValidationError, match="hash|mismatch"):
        load_and_validate_score_table(sorted_rows, sidecar, dev_ids=dev_ids, policy=policy)


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
        "source": "structured",
        "transcript": "NM_000051.4",
        "consequence": "missense_variant"
    } for vid in dev_ids]

    sidecar_template = {
        "schema": "pp3bp4-revel-score-table/1",
        "predictor": "REVEL",
        "predictor_version": "v1",
        "data_version": "v1",
        "license": "non-commercial",
        "dev_id_set_sha256": dev_hash,
        "n_dev": 1104,
        "reference_pins": ["NC_000009.12"],
        "snapshot": "clinvar_2026-07-07"
    }

    sorted_rows, sidecar = _canonicalize_rows_and_rebuild_sidecar(valid_rows, sidecar_template)

    # Missing field
    missing_sidecar = sidecar.copy()
    del missing_sidecar["dev_id_set_sha256"]
    with pytest.raises(ScoreTableValidationError, match="missing|field"):
        load_and_validate_score_table(sorted_rows, missing_sidecar, dev_ids=dev_ids, policy=policy)

    # Extra field
    extra_sidecar = sidecar.copy()
    extra_sidecar["unexpected_field"] = "value"
    with pytest.raises(ScoreTableValidationError, match="extra|unexpected|field"):
        load_and_validate_score_table(sorted_rows, extra_sidecar, dev_ids=dev_ids, policy=policy)


def test_ts2_attestation_fields():
    """T-S2 attestation structure.

    Verify that ScoreTableAttestation has the required fields.
    """
    from raptor.eval.pp3bp4_score_table import ScoreTableAttestation

    fields = ScoreTableAttestation.__dataclass_fields__ if hasattr(ScoreTableAttestation, "__dataclass_fields__") else {}
    expected_fields = {
        "schema", "predictor", "predictor_version", "data_version", "license",
        "dev_id_set_sha256", "table_content_sha256", "n_dev", "n_scored",
        "n_missing", "coverage", "reference_pins", "as_of", "snapshot"
    }
    for f in expected_fields:
        assert f in fields, f"ScoreTableAttestation missing field: {f}"

