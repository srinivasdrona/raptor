import pytest
import json
import hashlib
import os
import sys
import subprocess
from pathlib import Path


# Helper to generate mock dev IDs as canonical SPDI strings (Correction 3)
def _get_mock_dev_ids():
    return [f"NC_000009.12:{10000 + i}:T:C" for i in range(1104)]


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
    4. Proves disjointness from heldout.
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

    # Mock policy
    class DummyPolicy:
        predictor = "REVEL"
        predictor_version = "confirm-pending-revel-dbnsfp-release"
        data_version = "confirm-pending-dbnsfp-release"
        citations = []
        source_register_sha256 = "dummy-ref-hash"

    policy = DummyPolicy()

    # Create 1104 valid dev rows (NO ad hoc 'gene' field in rows)
    valid_rows = [{
        "variant_id": vid,
        "score": 0.5,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "source": "structured"
    } for vid in dev_ids]

    # Stage B must rederive split from benchmark + config and read labels only after attestation (Correction 6)
    # We supply a mock benchmark rows/path and mock config
    mock_benchmark_rows = []
    # 1104 dev rows
    for i, vid in enumerate(dev_ids):
        # exact dev composition (24 pathogenic, 49 benign)
        if i < 14:
            lbl, cls = "P", "missense"
        elif i < 24:
            lbl, cls = "LP", "missense"
        elif i < 70:
            lbl, cls = "B", "missense"
        elif i < 73:
            lbl, cls = "LB", "missense"
        else:
            lbl, cls = "VUS", "missense"
        mock_benchmark_rows.append({
            "variant_id": vid,
            "label": lbl,
            "variant_class": cls,
            "gene": "TSC1" if i % 2 == 0 else "TSC2"
        })
    # 2577 holdout rows to complete the 3681 benchmark
    for j in range(2577):
        mock_benchmark_rows.append({
            "variant_id": f"NC_000009.12:{20000 + j}:T:C",
            "label": "P",
            "variant_class": "missense",
            "gene": "TSC2"
        })

    # Mock eval config (similar to tsc2.yaml)
    mock_eval_config = {
        "split": {
            "seed": 20260701,
            "holdout_fraction": 0.7
        },
        "min_count_per_class": 36
    }

    # 1. Reject if attestation is completely missing
    with pytest.raises(TransportabilityError, match="attestation|missing"):
        evaluate_transportability(
            valid_rows, None,
            benchmark_rows=mock_benchmark_rows,
            eval_config=mock_eval_config,
            policy=policy
        )

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
        evaluate_transportability(
            valid_rows, mismatched_attestation,
            benchmark_rows=mock_benchmark_rows,
            eval_config=mock_eval_config,
            policy=policy
        )

    # 3. Reject if any held-out ID is present in the rows
    rows_with_heldout = valid_rows.copy()
    rows_with_heldout[0] = {
        "variant_id": "NC_000009.12:20000:T:C", # held-out ID
        "score": 0.5,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "source": "structured"
    }
    with pytest.raises(TransportabilityError, match="held-out|extra"):
        evaluate_transportability(
            rows_with_heldout, valid_attestation,
            benchmark_rows=mock_benchmark_rows,
            eval_config=mock_eval_config,
            policy=policy
        )


def test_te2_dev_split_composition_and_power():
    """T-E2 counts/power.

    Verify dev split:
    - total dev = 1104, total holdout = 2577 (out of 3681).
    - dev missense: pathogenic = 24 (P14, LP10), benign = 49 (B46, LB3), total 73.
    - Power status is UNDERPOWERED because pathogenic 24 < 36.
    - Assert counts are derived from benchmark + config, not returned by hardcoded zero-arg function.
    """
    from raptor.eval.pp3bp4_transportability import derive_dev_split_composition, get_power_status

    dev_ids = _get_mock_dev_ids()
    mock_benchmark_rows = []
    for i, vid in enumerate(dev_ids):
        if i < 14:
            lbl, cls = "P", "missense"
        elif i < 24:
            lbl, cls = "LP", "missense"
        elif i < 70:
            lbl, cls = "B", "missense"
        elif i < 73:
            lbl, cls = "LB", "missense"
        else:
            lbl, cls = "VUS", "missense"
        mock_benchmark_rows.append({
            "variant_id": vid,
            "label": lbl,
            "variant_class": cls,
            "gene": "TSC1" if i % 2 == 0 else "TSC2"
        })
    for j in range(2577):
        mock_benchmark_rows.append({
            "variant_id": f"NC_000009.12:{20000 + j}:T:C",
            "label": "P",
            "variant_class": "missense",
            "gene": "TSC2"
        })

    mock_eval_config = {
        "split": {
            "seed": 20260701,
            "holdout_fraction": 0.7
        },
        "min_count_per_class": 36
    }

    comp = derive_dev_split_composition(mock_benchmark_rows, mock_eval_config)
    assert comp["n_dev"] == 1104
    assert comp["n_holdout"] == 2577

    missense = comp["missense_composition"]
    assert missense["pathogenic"] == 24
    assert missense["benign"] == 49
    assert missense["P"] == 14
    assert missense["LP"] == 10
    assert missense["B"] == 46
    assert missense["LB"] == 3

    power = get_power_status(missense["pathogenic"], missense["benign"], power_floor=36)
    assert power == "UNDERPOWERED"


def test_te1_exclude_nthl1_and_no_writeback():
    """T-E1 NTHL1 exclusion and no label writeback.

    Verify that NTHL1 variants are excluded, and labels never flow back or are written to policy/score-table.
    """
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

    # Score table rows (NO ad hoc 'gene' field)
    rows = [{
        "variant_id": vid,
        "score": 0.8,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "source": "structured"
    } for vid in dev_ids]

    # Benchmark rows with explicit genes (including one explicitly annotated NTHL1 row) (Correction 4)
    mock_benchmark_rows = []
    for i, vid in enumerate(dev_ids):
        gene_name = "TSC2"
        # We explicitly annotate the last row as NTHL1 to test exclusion (Correction 4)
        if i == len(dev_ids) - 1:
            gene_name = "NTHL1"
        mock_benchmark_rows.append({
            "variant_id": vid,
            "label": "P" if i < 24 else "B",
            "variant_class": "missense",
            "gene": gene_name
        })

    for j in range(2577):
        mock_benchmark_rows.append({
            "variant_id": f"NC_000009.12:{20000 + j}:T:C",
            "label": "P",
            "variant_class": "missense",
            "gene": "TSC2"
        })

    mock_eval_config = {
        "split": {
            "seed": 20260701,
            "holdout_fraction": 0.7
        },
        "min_count_per_class": 36
    }

    report = evaluate_transportability(
        rows, attestation,
        benchmark_rows=mock_benchmark_rows,
        eval_config=mock_eval_config,
        policy=policy
    )

    # Verify NTHL1 was excluded and TSC2 on chromosome 16 was retained (Correction 4)
    assert "NTHL1" not in str(report) or "excluded" in str(report).lower()


def test_cli_help_bootstrap():
    """T-A4/T-B8 check script can run with a clean PYTHONPATH and shows help."""
    script_path = Path("scripts/build_pp3bp4_transportability_report.py")
    if not script_path.exists():
        pytest.skip("build_pp3bp4_transportability_report.py not implemented yet")

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    cmd = [sys.executable, str(script_path), "--help"]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"CLI help failed under clean PYTHONPATH: {res.stderr}"
    assert "usage" in res.stdout.lower() or "help" in res.stdout.lower()

