import pytest
import json
import hashlib
import os
import sys
import subprocess
from pathlib import Path


# Helper to load the real benchmark rows
def _load_real_benchmark_rows():
    from raptor.eval.model import BenchmarkRow
    env_root = os.environ.get("RAPTOR_DATA_ROOT")
    if env_root:
        real_benchmark_path = Path(env_root) / "clinvar" / "benchmark" / "benchmark.jsonl"
    else:
        real_benchmark_path = Path(__file__).resolve().parents[4] / "raptor-data" / "clinvar" / "benchmark" / "benchmark.jsonl"
    if not real_benchmark_path.exists():
        pytest.fail(f"Missing real frozen benchmark: {real_benchmark_path}")
    
    rows = []
    with open(real_benchmark_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                rows.append(BenchmarkRow(
                    variant_id=data["variant_id"],
                    label=data["label"],
                    variant_class=data["variant_class"],
                    source=data.get("source"),
                    snapshot=data.get("snapshot")
                ))
    return rows


# Helper to load the real config
def _load_real_eval_config():
    from raptor.eval.config import load_config as load_eval_config
    real_eval_config_path = Path("configs/eval/tsc2.yaml")
    if not real_eval_config_path.exists():
        pytest.fail(f"Missing real eval config: {real_eval_config_path}")
    return load_eval_config(str(real_eval_config_path))


# Helper to compute SHA256 of sorted IDs
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
    from raptor.eval.split import split_benchmark

    # Load real benchmark and config to derive actual dev split
    benchmark_rows = _load_real_benchmark_rows()
    eval_config = _load_real_eval_config()
    train_dev, holdout = split_benchmark(benchmark_rows, eval_config)

    dev_ids = [r.variant_id for r in train_dev]
    holdout_ids = [r.variant_id for r in holdout]
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
        as_of="2026-07-18",
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

    # Create synthetic scores ONLY for those exact dev IDs
    valid_rows = [{
        "variant_id": vid,
        "score": 0.5,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "source": "structured",
        "transcript": "NM_000051.4",
        "consequence": "missense_variant"
    } for vid in dev_ids]

    # 1. Reject if attestation is completely missing
    with pytest.raises(TransportabilityError, match="attestation|missing"):
        evaluate_transportability(
            valid_rows, None,
            benchmark_rows=benchmark_rows,
            eval_config=eval_config,
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
        as_of="2026-07-18",
        snapshot="clinvar_2026-07-07"
    )
    with pytest.raises(TransportabilityError, match="mismatch|dev_id_set_sha256"):
        evaluate_transportability(
            valid_rows, mismatched_attestation,
            benchmark_rows=benchmark_rows,
            eval_config=eval_config,
            policy=policy
        )

    # 3. Reject if any held-out ID is present in the rows
    rows_with_heldout = valid_rows.copy()
    rows_with_heldout[0] = {
        "variant_id": holdout_ids[0], # held-out ID
        "score": 0.5,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "source": "structured",
        "transcript": "NM_000051.4",
        "consequence": "missense_variant"
    }
    with pytest.raises(TransportabilityError, match="held-out|extra|disjoint"):
        evaluate_transportability(
            rows_with_heldout, valid_attestation,
            benchmark_rows=benchmark_rows,
            eval_config=eval_config,
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
    from raptor.eval.split import split_benchmark

    benchmark_rows = _load_real_benchmark_rows()
    eval_config = _load_real_eval_config()

    train_dev, holdout = split_benchmark(benchmark_rows, eval_config)
    assert len(train_dev) == 1104
    assert len(holdout) == 2577

    comp = derive_dev_split_composition(benchmark_rows, eval_config)
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


def test_te1_no_writeback():
    """T-E1 no label writeback.

    Verify that labels never flow back or are written to policy/score-table.
    """
    from raptor.eval.pp3bp4_transportability import evaluate_transportability
    from raptor.eval.pp3bp4_score_table import ScoreTableAttestation
    from raptor.eval.split import split_benchmark

    benchmark_rows = _load_real_benchmark_rows()
    eval_config = _load_real_eval_config()
    train_dev, _ = split_benchmark(benchmark_rows, eval_config)

    dev_ids = [r.variant_id for r in train_dev]
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
        as_of="2026-07-18",
        snapshot="clinvar_2026-07-07"
    )

    class DummyPolicy:
        predictor = "REVEL"
        predictor_version="confirm-pending-revel-dbnsfp-release"
        data_version="confirm-pending-dbnsfp-release"
        citations = []
        source_register_sha256 = "dummy-ref-hash"

    policy = DummyPolicy()

    # Score table rows
    rows = [{
        "variant_id": vid,
        "score": 0.8,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "source": "structured",
        "transcript": "NM_000051.4",
        "consequence": "missense_variant"
    } for vid in dev_ids]

    report = evaluate_transportability(
        rows, attestation,
        benchmark_rows=benchmark_rows,
        eval_config=eval_config,
        policy=policy
    )

    # Ensure labels did not flow back (no labels in the report object)
    assert "label" not in str(report).lower()


def test_cli_help_bootstrap():
    """T-A4/T-B8 check script can run with a clean PYTHONPATH and shows help."""
    script_path = Path("scripts/build_pp3bp4_transportability_report.py")
    if not script_path.exists():
        pytest.fail(f"implementation missing: {script_path}")

    env = os.environ.copy()
    if "PYTHONPATH" in env:
        del env["PYTHONPATH"]

    cmd = [sys.executable, str(script_path), "--help"]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"CLI help failed under clean PYTHONPATH: {res.stderr}"
    assert "usage" in res.stdout.lower() or "help" in res.stdout.lower()

