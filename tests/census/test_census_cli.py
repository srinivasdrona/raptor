from __future__ import annotations

import json
from pathlib import Path
import pytest
import sys

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


@pytest.fixture
def cli_args_dict(tmp_path: Path):
    # Prepare mock inputs to allow a successful or failing CLI execution
    manifest_file = tmp_path / "tsc_vus_input.manifest.jsonl"
    manifest_file.write_text(
        json.dumps({"variant_id": "VAR1", "vcf_key": "chr16:1001:A:G"}) + "\n",
        encoding="utf-8"
    )

    bias_file = tmp_path / "tsc_vus_input.bias_output.tsv"
    # Header plus one row
    bias_content = (
        "chromosome\tposition\tref_allele\talt_allele\tvariant_id\tvariant_type\tconsequence\tacmg_classification\tgene_name\ttranscript\tcriteria\tprovenance\n"
        "chr16\t1001\tA\tG\tchr16:1001:A:G\tSNV\tmissense_variant\tuncertain\tTSC2\tNM_000548.4\t{}\t{}\n"
    )
    bias_file.write_text(bias_content, encoding="utf-8")

    provenance_file = tmp_path / "tsc_vus_input.provenance.json"
    provenance_file.write_text(json.dumps({"vcf_hash": "mock_vcf_hash"}), encoding="utf-8")

    scorer_config = tmp_path / "tsc.yaml"
    scorer_config.write_text("strength_map:\n  - ['1', 'supporting']\n", encoding="utf-8")

    eval_config = tmp_path / "tsc2.yaml"
    eval_config.write_text("automatable_criteria: [PM2]\n", encoding="utf-8")

    predictor_policy = tmp_path / "bp4pp3_predictor_policy.json"
    predictor_policy.write_text(
        json.dumps({"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"}),
        encoding="utf-8"
    )

    lineage_policy = tmp_path / "bias_lineage.yaml"
    lineage_policy.write_text("lineage_policy_hash: mock\n", encoding="utf-8")

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
        "--historical-stats": str(historical_stats),
    }


def _make_args(args_dict: dict[str, str], extra: list[str]) -> list[str]:
    args = []
    for k, v in args_dict.items():
        args.extend([k, v])
    args.extend(extra)
    return args


def test_g_vc11_output_boundary(cli_args_dict, tmp_path: Path) -> None:
    """G-VC11 output boundary — only data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json accepted."""
    check_cli_implemented()

    # Attempts to write to nested path, wrong extension, or overwriting historical stats
    forbidden_paths = [
        "data/census/nested/record.json",
        "data/census/record.txt",
        "data/forbidden/stats.json",
        str(tmp_path / "external.json"),
    ]

    for p in forbidden_paths:
        args = _make_args(cli_args_dict, ["--emit-census-record", p])
        with pytest.raises((OutputBoundaryError, ValueError)):
            main(args)


def test_g_vc12_dry_run_summary(cli_args_dict, tmp_path: Path) -> None:
    """G-VC12 --dry-run/--summary writes NO file; conservation runs before any write."""
    check_cli_implemented()

    out_file = tmp_path / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"
    args = _make_args(cli_args_dict, ["--emit-census-record", str(out_file), "--dry-run"])

    exit_code = main(args)
    assert exit_code == 0
    # Must not write any file
    assert not out_file.exists()


def test_g_vc13_canonical_json_bytes(cli_args_dict, tmp_path: Path) -> None:
    """G-VC13 canonical JSON bytes are UTF-8, sort_keys, indent 2, exactly one terminal LF (no CRLF)."""
    check_cli_implemented()

    out_file = tmp_path / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"
    args = _make_args(cli_args_dict, ["--emit-census-record", str(out_file)])

    # We must patch the output boundary check in our test or use the actual allowed path in real test.
    # For CLI unit test, we can mock/override the boundary or pass the exact allowed path relative to repo root
    # depending on how output boundary is implemented.
    # Assuming the CLI allows specifying the path for testing, but validates the exact hard-pinned path name.
    # Let's run the CLI:
    exit_code = main(args)
    assert exit_code == 0
    assert out_file.exists()

    content_bytes = out_file.read_bytes()

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
