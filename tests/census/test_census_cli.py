from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import csv
import json
import hashlib
import pytest

from scripts.build_tsc_calibration_batch import OutputBoundaryError

try:
    from raptor.census.cli import main
    HAS_CLI = True
except ImportError:
    main = None
    HAS_CLI = False


def check_cli_implemented() -> None:
    if not HAS_CLI:
        pytest.fail("Missing planned implementation: raptor.census.cli")


def _get_sha256(path: Path) -> str:
    content = path.read_bytes()
    # Normalize CRLF to LF to be checkout-insensitive
    content_lf = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content_lf).hexdigest()


@pytest.fixture
def cli_args_dict(tmp_path: Path):
    # Derive repository root
    repo_root = Path(__file__).resolve().parents[2]

    # Copy actual approved configs/policies to tmp_path to make it completely robust, isolated, and valid
    scorer_config = tmp_path / "tsc.yaml"
    scorer_config.write_bytes((repo_root / "configs/acmg/tsc.yaml").read_bytes())

    eval_config = tmp_path / "tsc2.yaml"
    eval_config.write_bytes((repo_root / "configs/eval/tsc2.yaml").read_bytes())

    predictor_policy = tmp_path / "bp4pp3_predictor_policy.json"
    predictor_policy.write_bytes((repo_root / "configs/eval/bp4pp3_predictor_policy.json").read_bytes())

    lineage_policy = tmp_path / "bias_lineage.yaml"
    lineage_policy.write_bytes((repo_root / "configs/eval/bias_lineage.yaml").read_bytes())

    packet_candidate_direction = tmp_path / "candidate_direction.yaml"
    packet_candidate_direction.write_bytes((repo_root / "configs/packet/candidate_direction.yaml").read_bytes())

    # Build valid synthetic manifest JSONL
    manifest_file = tmp_path / "tsc_vus_input.manifest.jsonl"
    manifest_file.write_text(
        json.dumps({"variant_id": "NC_000016.10:1001:A:G", "vcf_key": "chr16:1001:A:G"}) + "\n",
        encoding="utf-8"
    )

    # Build valid synthetic TSV using BiasOutputContract.REQUIRED_COLUMNS
    bias_file = tmp_path / "tsc_vus_input.bias_output.tsv"
    
    from raptor.scorer.contract import BiasOutputContract
    header = BiasOutputContract.REQUIRED_COLUMNS
    
    rationale_dict = {"pm": {"pm2": [1, "supporting"]}}
    
    row_data = {
        "chromosome": "chr16",
        "position": "1001",
        "refAllele": "A",
        "altAllele": "G",
        "variantType": "SNV",
        "consequence": "missense_variant",
        "acmgClassification": "uncertain",
        "alleleFreq": "0.01",
        "hgvsg": "g.16_1001A>G",
        "hgvsc": "c.100A>G",
        "hgvsp": "p.Ala34Gly",
        "aaChange": "A34G",
        "geneName": "TSC2",
        "pubmedIds": "",
        "associatedDiseases": "",
        "dbSnpids": "",
        "transcript": "NM_000548.4",
        "rationale": json.dumps(rationale_dict),
    }
    
    with open(bias_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(header)
        writer.writerow([row_data[col] for col in header])

    # Provenance file with valid 64-hex vcf_hash and source_snapshot
    provenance_file = tmp_path / "tsc_vus_input.provenance.json"
    provenance_file.write_text(
        json.dumps({
            "vcf_hash": "3fff6de7ae9b2b202642e498c4c49532cf1aaf5c2734f0e8341d5ace88fa3a09",
            "source_snapshot": "clinvar_2026-07-07"
        }),
        encoding="utf-8"
    )

    historical_stats = tmp_path / "tsc_vus_clinvar_2026-07-07_stats.json"
    historical_stats.write_text(
        json.dumps({
            "corpus": {"total_vus": 1},
            "raptor_current_policy_internal_direction": {
                "candidate_LP_review": 0,
                "candidate_LB_review": 0,
                "no_deterministic_resolution": 1,
                "annotation_manual_review": 0,
            }
        }),
        encoding="utf-8"
    )

    return {
        "--manifest": str(manifest_file),
        "--bias-tsv": str(bias_file),
        "--provenance": str(provenance_file),
        "--scorer-config": str(scorer_config),
        "--eval-config": str(eval_config),
        "--predictor-policy": str(predictor_policy),
        "--lineage-policy": str(lineage_policy),
        "--packet-candidate-direction": str(packet_candidate_direction),
        "--historical-stats": str(historical_stats),
    }


def _make_args(args_dict: dict[str, str], extra: list[str]) -> list[str]:
    args = []
    for k, v in args_dict.items():
        args.extend([k, v])
    args.extend(extra)
    return args


def test_g_vc11_output_boundary(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """G-VC11 output boundary — only data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json accepted."""
    check_cli_implemented()

    # Define testability contract for the planned CLI: monkeypatch REPO_ROOT to tmp_path
    if HAS_CLI:
        import raptor.census.cli as census_cli
        for attr in ("REPO_ROOT", "_REPO_ROOT"):
            if hasattr(census_cli, attr):
                monkeypatch.setattr(census_cli, attr, tmp_path)

    census_dir = tmp_path / "data" / "census"
    census_dir.mkdir(parents=True, exist_ok=True)

    canonical_path = census_dir / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"

    # Attempts to write to nested path, wrong extension, external, or existing canonical output
    forbidden_paths = [
        str(census_dir / "nested" / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"),
        str(census_dir / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.txt"),
        str(census_dir / "wrong_name.json"),
        str(tmp_path / "external.json"),
        # exact historical stats path
        str(census_dir / "tsc_vus_clinvar_2026-07-07_stats.json"),
        # certified masked-gate path
        str(census_dir / "tsc_masked_holdout_gate_2026-07-13.json"),
    ]

    for p in forbidden_paths:
        args = _make_args(cli_args_dict, ["--emit-census-record", p])
        with pytest.raises((OutputBoundaryError, ValueError)):
            main(args)

    # Reject existing canonical output
    canonical_path.write_text("{}", encoding="utf-8")
    args = _make_args(cli_args_dict, ["--emit-census-record", str(canonical_path)])
    with pytest.raises((OutputBoundaryError, ValueError)):
        main(args)

    # Remove existing canonical file to let positive test succeed
    canonical_path.unlink()
    # Positive case: positively accept only the canonical output under a test-injected repo root
    args = _make_args(cli_args_dict, ["--emit-census-record", str(canonical_path)])
    exit_code = main(args)
    assert exit_code == 0
    assert canonical_path.exists()


def test_g_vc12_dry_run_summary(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """G-VC12 --dry-run/--summary writes NO file; conservation runs before any write."""
    check_cli_implemented()

    if HAS_CLI:
        import raptor.census.cli as census_cli
        for attr in ("REPO_ROOT", "_REPO_ROOT"):
            if hasattr(census_cli, attr):
                monkeypatch.setattr(census_cli, attr, tmp_path)

    census_dir = tmp_path / "data" / "census"
    census_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = census_dir / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"

    args = _make_args(cli_args_dict, ["--emit-census-record", str(canonical_path), "--dry-run"])

    exit_code = main(args)
    assert exit_code == 0
    # Must not write any file
    assert not canonical_path.exists()


def test_g_vc13_canonical_json_bytes(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """G-VC13 canonical JSON bytes are UTF-8, sort_keys, indent 2, exactly one terminal LF (no CRLF)."""
    check_cli_implemented()

    if HAS_CLI:
        import raptor.census.cli as census_cli
        for attr in ("REPO_ROOT", "_REPO_ROOT"):
            if hasattr(census_cli, attr):
                monkeypatch.setattr(census_cli, attr, tmp_path)

    census_dir = tmp_path / "data" / "census"
    census_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = census_dir / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"

    if canonical_path.exists():
        canonical_path.unlink()

    args = _make_args(cli_args_dict, ["--emit-census-record", str(canonical_path)])

    exit_code = main(args)
    assert exit_code == 0
    assert canonical_path.exists()

    content_bytes = canonical_path.read_bytes()

    # 1. Exactly one terminal LF
    assert content_bytes.endswith(b"\n")
    assert not content_bytes.endswith(b"\r\n")

    # 2. No CRLF anywhere
    assert b"\r\n" not in content_bytes

    # 3. Valid JSON with keys sorted and indent 2
    decoded = json.loads(content_bytes.decode("utf-8"))
    re_serialized = json.dumps(decoded, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    assert content_bytes == re_serialized


def test_g_vc14_policy_hash_verification(cli_args_dict, tmp_path: Path) -> None:
    """G-VC14 policy/hash verification fails closed on a drifted config hash or non-approved policy."""
    check_cli_implemented()

    # Change policy status to unapproved
    bad_policy = tmp_path / "bad_policy.json"
    bad_policy.write_text(
        json.dumps({"schema": "bp4pp3-predictor-policy/2", "status": "unapproved", "mode": "disabled_manual"}),
        encoding="utf-8"
    )

    args_dict = dict(cli_args_dict)
    args_dict["--predictor-policy"] = str(bad_policy)

    args = _make_args(args_dict, ["--dry-run"])
    with pytest.raises((ValueError, SystemExit)):
        main(args)

    # Prove one-byte drift fails closed for EACH bound config surface
    bound_keys = [
        "--predictor-policy",
        "--scorer-config",
        "--eval-config",
        "--lineage-policy",
        "--packet-candidate-direction",
    ]

    for key in bound_keys:
        if key not in cli_args_dict:
            continue
        drifted_args_dict = dict(cli_args_dict)
        original_file = Path(drifted_args_dict[key])
        
        drifted_file = tmp_path / f"drifted_{original_file.name}"
        drifted_file.write_bytes(original_file.read_bytes() + b"\n")
        drifted_args_dict[key] = str(drifted_file)
        
        args = _make_args(drifted_args_dict, ["--dry-run"])
        with pytest.raises((ValueError, SystemExit)):
            main(args)

