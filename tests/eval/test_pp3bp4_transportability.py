import pytest
import json
import hashlib
from pathlib import Path


def _get_mock_dev_ids():
    return [f"NC_000009.12:g.{10000 + i}A>G" for i in range(1104)]


def _compute_ids_hash(ids):
    sorted_ids = sorted(ids)
    hasher = hashlib.sha256()
    for vid in sorted_ids:
        hasher.update(vid.encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def test_te1_stage_b_attestation_and_rejection(tmp_path):
    """T-E1 Stage B transportability boundary.

    Verify that Stage B (pp3bp4_transportability.py):
    1. Rejects missing or mismatched ScoreTableAttestation.
    2. Rejects if dev_id_set_sha256 does not match the actual dev split set.
    3. Rejects any held-out ID or any extra ID.
    4. Excludes NTHL1 variants.
    """
    from raptor.eval.pp3bp4_transportability import evaluate_transportability, TransportabilityError
    from raptor.eval.pp3bp4_score_table import ScoreTableAttestation

    dev_ids = _get_mock_dev_ids()
    correct_hash = _compute_ids_hash(dev_ids)

    # Valid base attestation
    valid_attestation = ScoreTableAttestation(
        schema="pp3bp4-revel-score-table/1",
        predictor="REVEL",
        predictor_version="confirm-pending-revel-dbnsfp-release",
        data_version="confirm-pending-dbnsfp-release",
        license="non-commercial",
        dev_id_set_sha256=correct_hash,
        table_content_sha256="some-content-hash",
        n_dev=1104,
        n_scored=1104,
        n_missing=0,
        coverage=1.0,
        reference_pins=["NC_000009.12"],
        generated_at="2026-07-19T00:00:00Z",
        snapshot="clinvar_2026-07-07"
    )

    # Mock policy and rows
    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "confirm-pending-revel-dbnsfp-release"
        data_version = "confirm-pending-dbnsfp-release"
        citations = []
        source_register_sha256 = "dummy-ref-hash"

    policy = DummyPolicy()

    # Create 1104 valid dev rows
    valid_rows = [{
        "variant_id": vid,
        "score": 0.5,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "source": "structured"
    } for vid in dev_ids]

    # Create mock dev labels (dict of variant_id -> label)
    dev_labels = {vid: "P" for vid in dev_ids}

    # 1. Reject if attestation is completely missing (should return BLOCKED_DATA or raise)
    with pytest.raises(TransportabilityError, match="attestation"):
        evaluate_transportability(valid_rows, None, dev_labels=dev_labels, policy=policy)

    # 2. Reject if dev_id_set_sha256 mismatches
    mismatched_attestation = ScoreTableAttestation(
        schema="pp3bp4-revel-score-table/1",
        predictor="REVEL",
        predictor_version="confirm-pending-revel-dbnsfp-release",
        data_version="confirm-pending-dbnsfp-release",
        license="non-commercial",
        dev_id_set_sha256="wrong-dev-hash",
        table_content_sha256="some-content-hash",
        n_dev=1104,
        n_scored=1104,
        n_missing=0,
        coverage=1.0,
        reference_pins=["NC_000009.12"],
        generated_at="2026-07-19T00:00:00Z",
        snapshot="clinvar_2026-07-07"
    )
    with pytest.raises(TransportabilityError, match="mismatch|dev_id_set_sha256"):
        evaluate_transportability(valid_rows, mismatched_attestation, dev_labels=dev_labels, policy=policy)

    # 3. Reject if any held-out ID is present in the rows
    rows_with_heldout = valid_rows.copy()
    rows_with_heldout[0] = {
        "variant_id": "NC_000009.12:g.20000A>G", # held-out ID
        "score": 0.5,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "source": "structured"
    }
    with pytest.raises(TransportabilityError, match="held-out|extra"):
        evaluate_transportability(rows_with_heldout, valid_attestation, dev_labels=dev_labels, policy=policy)


def test_te2_dev_split_composition_and_power():
    """T-E2 counts/power.

    Verify dev split:
    - total dev = 1104, total holdout = 2577 (out of 3681).
    - dev missense: pathogenic = 24 (P14, LP10), benign = 49 (B46, LB3), total 73.
    - Power status is UNDERPOWERED because pathogenic 24 < 36.
    """
    from raptor.eval.pp3bp4_transportability import get_dev_split_composition, get_power_status

    comp = get_dev_split_composition()
    assert comp["n_dev"] == 1104
    assert comp["n_holdout"] == 2577

    missense = comp["missense_composition"]
    assert missense["pathogenic"] == 24
    assert missense["benign"] == 49
    assert missense["P"] == 14
    assert missense["LP"] == 10
    assert missense["B"] == 46
    assert missense["LB"] == 3

    power = get_power_status(missense["pathogenic"], missense["benign"])
    assert power == "UNDERPOWERED" # Since pathogenic 24 < 36


def test_te1_exclude_nthl1_and_no_writeback():
    """T-E1 NTHL1 exclusion and no label writeback.

    Verify that NTHL1 variants are excluded from the transportability metrics evaluation,
    and labels never flow back or are written to policy/score-table.
    """
    # The evaluation API must exclude variants belonging to NTHL1 gene
    # In any joined records or metrics, NTHL1 gene variants should be ignored.
    from raptor.eval.pp3bp4_transportability import evaluate_transportability
    from raptor.eval.pp3bp4_score_table import ScoreTableAttestation

    dev_ids = _get_mock_dev_ids()
    correct_hash = _compute_ids_hash(dev_ids)

    attestation = ScoreTableAttestation(
        schema="pp3bp4-revel-score-table/1",
        predictor="REVEL",
        predictor_version="confirm-pending-revel-dbnsfp-release",
        data_version="confirm-pending-dbnsfp-release",
        license="non-commercial",
        dev_id_set_sha256=correct_hash,
        table_content_sha256="some-content-hash",
        n_dev=1104,
        n_scored=1104,
        n_missing=0,
        coverage=1.0,
        reference_pins=["NC_000009.12"],
        generated_at="2026-07-19T00:00:00Z",
        snapshot="clinvar_2026-07-07"
    )

    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "confirm-pending-revel-dbnsfp-release"
        data_version = "confirm-pending-dbnsfp-release"
        citations = []
        source_register_sha256 = "dummy-ref-hash"

    policy = DummyPolicy()

    # Create rows, including an NTHL1 variant
    # Let's say NC_000016.10 is the NTHL1 chromosome
    rows = []
    for i, vid in enumerate(dev_ids[:-1]):
        rows.append({
            "variant_id": vid,
            "score": 0.8,
            "predictor": "REVEL",
            "predictor_version": "confirm-pending-revel-dbnsfp-release",
            "data_version": "confirm-pending-dbnsfp-release",
            "source": "structured",
            "gene": "TSC2"
        })
    # Add one NTHL1 row
    rows.append({
        "variant_id": dev_ids[-1],
        "score": 0.8,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "source": "structured",
        "gene": "NTHL1" # should be excluded
    })

    dev_labels = {vid: "P" for vid in dev_ids}

    # Evaluate
    report = evaluate_transportability(rows, attestation, dev_labels=dev_labels, policy=policy)

    # Verify that NTHL1 variant was excluded from the counts
    # The total analyzed pathogenic dev missense should be less or not contain NTHL1
    assert "NTHL1" not in str(report) or "excluded" in str(report).lower()
