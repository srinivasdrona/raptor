from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import csv
import json
import hashlib
import pytest

try:
    from raptor.census.cli import main, OutputBoundaryError, REPO_ROOT
    HAS_CLI = True
except ImportError:
    main = None
    class OutputBoundaryError(Exception):
        pass
    REPO_ROOT = Path(__file__).resolve().parents[2]
    HAS_CLI = False


def check_cli_implemented() -> None:
    if not HAS_CLI:
        pytest.fail("Missing planned implementation: raptor.census.cli")


def _get_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def cli_args_dict(tmp_path: Path):
    # Derive repository root
    repo_root = Path(__file__).resolve().parents[2]

    # Copy actual approved configs/policies to tmp_path to make it completely robust, isolated, and valid
    scorer_config = tmp_path / "tsc.yaml"
    scorer_config.write_bytes((repo_root / "configs/acmg/tsc.yaml").read_bytes())

    eval_config = tmp_path / "tsc2.yaml"
    eval_config.write_bytes((repo_root / "configs/eval/tsc2.yaml").read_bytes())

    predictor_policy_dir = tmp_path / "configs" / "eval"
    predictor_policy_dir.mkdir(parents=True, exist_ok=True)
    predictor_policy = predictor_policy_dir / "bp4pp3_predictor_policy.json"
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

    historical_stats = tmp_path / "data" / "census" / "tsc_vus_clinvar_2026-07-07_stats.json"
    historical_stats.parent.mkdir(parents=True, exist_ok=True)
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
        monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(census_cli, "_resolve_code_commit", lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f")
        synthetic_hash = _get_sha256(Path(cli_args_dict["--historical-stats"]))
        monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_hash, raising=False)

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
        str(census_dir / "tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"),
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
        monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(census_cli, "_resolve_code_commit", lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f")
        synthetic_hash = _get_sha256(Path(cli_args_dict["--historical-stats"]))
        monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_hash, raising=False)

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
        monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(census_cli, "_resolve_code_commit", lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f")
        synthetic_hash = _get_sha256(Path(cli_args_dict["--historical-stats"]))
        monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_hash, raising=False)

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


def test_g_vc14_policy_hash_verification(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """G-VC14 policy/hash verification fails closed on invalid/unapproved predictor policy, or drifted config hash."""
    check_cli_implemented()

    if HAS_CLI:
        import raptor.census.cli as census_cli
        monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(census_cli, "_resolve_code_commit", lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f")
        synthetic_hash = _get_sha256(Path(cli_args_dict["--historical-stats"]))
        monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_hash, raising=False)

    # 1. Non-approved status fails closed
    bad_policy_status_dict = {"schema": "bp4pp3-predictor-policy/2", "status": "unapproved", "mode": "disabled_manual"}
    bad_policy_bytes = json.dumps(bad_policy_status_dict).encode("utf-8")
    
    canonical_policy_path = tmp_path / "configs" / "eval" / "bp4pp3_predictor_policy.json"
    canonical_policy_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_policy_path.write_bytes(bad_policy_bytes)
    
    custom_hash = hashlib.sha256(bad_policy_bytes).hexdigest()
    if HAS_CLI:
        monkeypatch.setattr(census_cli, "APPROVED_PREDICTOR_POLICY_SHA256", custom_hash, raising=False)
        
    args_dict_status = dict(cli_args_dict)
    args_dict_status["--predictor-policy"] = str(canonical_policy_path)
    args_status = _make_args(args_dict_status, ["--dry-run"])
    with pytest.raises((ValueError, SystemExit)):
        main(args_status)

    # 2. Unknown field fails closed
    bad_policy_field_dict = {"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual", "unknown_field_xyz": 123}
    bad_policy_bytes = json.dumps(bad_policy_field_dict).encode("utf-8")
    
    canonical_policy_path.write_bytes(bad_policy_bytes)
    custom_hash = hashlib.sha256(bad_policy_bytes).hexdigest()
    if HAS_CLI:
        monkeypatch.setattr(census_cli, "APPROVED_PREDICTOR_POLICY_SHA256", custom_hash, raising=False)
        
    args_dict_field = dict(cli_args_dict)
    args_dict_field["--predictor-policy"] = str(canonical_policy_path)
    args_field = _make_args(args_dict_field, ["--dry-run"])
    with pytest.raises((ValueError, SystemExit)):
        main(args_field)

    # 3. Invalid mode fails closed
    bad_policy_mode_dict = {"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "invalid_mode_abc"}
    bad_policy_bytes = json.dumps(bad_policy_mode_dict).encode("utf-8")
    
    canonical_policy_path.write_bytes(bad_policy_bytes)
    custom_hash = hashlib.sha256(bad_policy_bytes).hexdigest()
    if HAS_CLI:
        monkeypatch.setattr(census_cli, "APPROVED_PREDICTOR_POLICY_SHA256", custom_hash, raising=False)
        
    args_dict_mode = dict(cli_args_dict)
    args_dict_mode["--predictor-policy"] = str(canonical_policy_path)
    args_mode = _make_args(args_dict_mode, ["--dry-run"])
    with pytest.raises((ValueError, SystemExit)):
        main(args_mode)

    # Prove one-byte drift fails closed for the four policy-bound config surfaces (excluding --predictor-policy)
    bound_keys = [
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


def test_historical_census_sha256_constant() -> None:
    """Historical source integrity must expose and require a testable module constant."""
    import raptor.census.cli as census_cli
    assert hasattr(census_cli, "HISTORICAL_CENSUS_SHA256")
    assert census_cli.HISTORICAL_CENSUS_SHA256 == "389e93d5b37f686b8d5e1115e2ebbfcdee6a060417300e5ed38d46304abac6e7"


def test_invalid_vcf_hash_fails(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """Fail closed on invalid/non-hex/short provenance `vcf_hash`."""
    check_cli_implemented()
    import raptor.census.cli as census_cli
    monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(census_cli, "_resolve_code_commit", lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f")
    synthetic_hash = _get_sha256(Path(cli_args_dict["--historical-stats"]))
    monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_hash, raising=False)

    # Short/non-hex hash
    provenance_file = Path(cli_args_dict["--provenance"])
    provenance_file.write_text(
        json.dumps({
            "vcf_hash": "short_non_hex",
            "source_snapshot": "clinvar_2026-07-07"
        }),
        encoding="utf-8"
    )

    census_dir = tmp_path / "data" / "census"
    census_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = census_dir / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"

    args = _make_args(cli_args_dict, ["--emit-census-record", str(canonical_path)])
    with pytest.raises(ValueError):
        main(args)

    assert not canonical_path.exists()


def test_blank_missing_source_snapshot_fails(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """Fail closed on blank or missing `source_snapshot`."""
    check_cli_implemented()
    import raptor.census.cli as census_cli
    monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(census_cli, "_resolve_code_commit", lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f")
    synthetic_hash = _get_sha256(Path(cli_args_dict["--historical-stats"]))
    monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_hash, raising=False)

    census_dir = tmp_path / "data" / "census"
    census_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = census_dir / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"

    # Case 1: blank
    provenance_file = Path(cli_args_dict["--provenance"])
    provenance_file.write_text(
        json.dumps({
            "vcf_hash": "3fff6de7ae9b2b202642e498c4c49532cf1aaf5c2734f0e8341d5ace88fa3a09",
            "source_snapshot": "   "
        }),
        encoding="utf-8"
    )

    args = _make_args(cli_args_dict, ["--emit-census-record", str(canonical_path)])
    with pytest.raises(ValueError):
        main(args)

    assert not canonical_path.exists()

    # Case 2: missing
    provenance_file.write_text(
        json.dumps({
            "vcf_hash": "3fff6de7ae9b2b202642e498c4c49532cf1aaf5c2734f0e8341d5ace88fa3a09"
        }),
        encoding="utf-8"
    )

    args = _make_args(cli_args_dict, ["--emit-census-record", str(canonical_path)])
    with pytest.raises(ValueError):
        main(args)

    assert not canonical_path.exists()


def test_git_failure_fails_closed(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """Fail closed when git resolution / _resolve_code_commit fails."""
    check_cli_implemented()
    import raptor.census.cli as census_cli
    monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
    synthetic_hash = _get_sha256(Path(cli_args_dict["--historical-stats"]))
    monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_hash, raising=False)

    import subprocess
    def mock_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "git rev-parse")
    monkeypatch.setattr(subprocess, "run", mock_run)

    census_dir = tmp_path / "data" / "census"
    census_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = census_dir / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"

    args = _make_args(cli_args_dict, ["--emit-census-record", str(canonical_path)])
    with pytest.raises((subprocess.CalledProcessError, RuntimeError, OSError)):
        main(args)

    assert not canonical_path.exists()


def test_code_commit_is_fixed_width_full_sha(monkeypatch) -> None:
    """Code provenance uses the full 40-hex commit, never an abbreviation."""
    import raptor.census.cli as census_cli

    full_sha = "ade13f206f3e2c2efe3ec92715d974645fc8da8f"

    class Result:
        stdout = full_sha + "\n"

    def full_result(args, **kwargs):
        assert args == ["git", "rev-parse", "HEAD"]
        return Result()

    monkeypatch.setattr(census_cli.subprocess, "run", full_result)
    assert census_cli._resolve_code_commit() == full_sha

    class ShortResult:
        stdout = full_sha[:7] + "\n"

    monkeypatch.setattr(
        census_cli.subprocess, "run", lambda *args, **kwargs: ShortResult()
    )
    with pytest.raises(census_cli.CodeCommitResolutionError):
        census_cli._resolve_code_commit()


def test_historical_stats_path_rejection(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """Fail closed when `--historical-stats` path is an arbitrary alternate path."""
    check_cli_implemented()
    import raptor.census.cli as census_cli
    monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(census_cli, "_resolve_code_commit", lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f")
    synthetic_hash = _get_sha256(Path(cli_args_dict["--historical-stats"]))
    monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_hash, raising=False)

    alternate_path = tmp_path / "alternate_stats.json"
    alternate_path.write_text("{}", encoding="utf-8")

    args_dict_alt = dict(cli_args_dict)
    args_dict_alt["--historical-stats"] = str(alternate_path)
    args_alt = _make_args(args_dict_alt, ["--dry-run"])

    with pytest.raises(ValueError):
        main(args_alt)


def test_historical_stats_one_byte_tamper_fails(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """Fail closed on one-byte tamper of historical stats file."""
    check_cli_implemented()
    import raptor.census.cli as census_cli
    monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(census_cli, "_resolve_code_commit", lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f")

    # Set historical expected SHA to some synthetic value
    synthetic_content = b'{"some_key": "some_value"}\n'
    synthetic_sha = hashlib.sha256(synthetic_content).hexdigest()
    monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_sha, raising=False)

    # Write synthetic content to the canonical path
    canonical_hist_path = tmp_path / "data" / "census" / "tsc_vus_clinvar_2026-07-07_stats.json"
    canonical_hist_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_hist_path.write_bytes(synthetic_content)

    # Now tamper with it by one byte
    tampered_content = synthetic_content + b"\n"
    canonical_hist_path.write_bytes(tampered_content)

    census_dir = tmp_path / "data" / "census"
    census_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = census_dir / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"

    args = _make_args(cli_args_dict, ["--emit-census-record", str(canonical_path)])
    with pytest.raises(ValueError):
        main(args)

    assert not canonical_path.exists()


def test_anchor_approved_predictor_policy(cli_args_dict, tmp_path: Path, monkeypatch) -> None:
    """Test anchoring approved predictor policy.
    
    - Expose APPROVED_PREDICTOR_POLICY_SHA256 equal to 85e9e92fa9f4c221c02af30e787315a88ed2bef51f6f58d25c5dc267eb55a34a;
    - Require --predictor-policy resolves exactly to REPO_ROOT/configs/eval/bp4pp3_predictor_policy.json and canonical-LF hash matches;
    - Byte-identical policy at an alternate path is rejected;
    - One-byte/metadata-only tampering at canonical path fails before output even when the four subordinate config hashes still match.
    - No output on every failure.
    """
    check_cli_implemented()
    import raptor.census.cli as census_cli

    # Ensure constant exists and is correct
    assert hasattr(census_cli, "APPROVED_PREDICTOR_POLICY_SHA256")
    assert census_cli.APPROVED_PREDICTOR_POLICY_SHA256 == "85e9e92fa9f4c221c02af30e787315a88ed2bef51f6f58d25c5dc267eb55a34a"

    # Setup standard mocking
    monkeypatch.setattr(census_cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(census_cli, "_resolve_code_commit", lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f")
    synthetic_hash = _get_sha256(Path(cli_args_dict["--historical-stats"]))
    monkeypatch.setattr(census_cli, "HISTORICAL_CENSUS_SHA256", synthetic_hash, raising=False)

    # 1. Happy path: canonical path and matching LF-canonical hash
    canonical_policy_path = tmp_path / "configs" / "eval" / "bp4pp3_predictor_policy.json"
    assert canonical_policy_path.exists()
    
    # We monkeypatch the expected constant to the LF-canonical hash of the policy in the fixture
    # (which was copied from the real policy, so it has the real hash)
    policy_bytes = canonical_policy_path.read_bytes()
    real_lf_hash = hashlib.sha256(policy_bytes.replace(b"\r\n", b"\n")).hexdigest()
    # It must be exactly the expected constant
    assert real_lf_hash == "85e9e92fa9f4c221c02af30e787315a88ed2bef51f6f58d25c5dc267eb55a34a"

    # 2. Byte-identical policy at an alternate path is rejected
    alternate_policy_path = tmp_path / "configs" / "eval" / "alt_predictor_policy.json"
    alternate_policy_path.write_bytes(policy_bytes)
    
    args_dict_alt = dict(cli_args_dict)
    args_dict_alt["--predictor-policy"] = str(alternate_policy_path)
    args_alt = _make_args(args_dict_alt, ["--dry-run"])
    with pytest.raises((ValueError, SystemExit)):
        main(args_alt)

    # 3. One-byte/metadata-only tampering of predictor_source_hash, correction_hash, runtime_bundle_hash or decision_reference at canonical path fails before output
    policy_dict = json.loads(policy_bytes.decode("utf-8"))
    
    for tampered_key in ("predictor_source_hash", "correction_hash", "runtime_bundle_hash", "decision_reference"):
        tampered_dict = dict(policy_dict)
        # Modify the metadata value by 1 byte/char
        val = tampered_dict.get(tampered_key, "")
        if isinstance(val, str):
            tampered_dict[tampered_key] = val[:-1] + ("0" if val[-1] != "0" else "1") if val else "1"
        else:
            tampered_dict[tampered_key] = "tampered"
            
        tampered_bytes = json.dumps(tampered_dict).encode("utf-8")
        canonical_policy_path.write_bytes(tampered_bytes)
        
        args_dict_tampered = dict(cli_args_dict)
        args_tampered = _make_args(args_dict_tampered, ["--dry-run"])
        with pytest.raises((ValueError, SystemExit)):
            main(args_tampered)
            
    # Restore correct policy content
    canonical_policy_path.write_bytes(policy_bytes)
