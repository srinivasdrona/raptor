from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_clinvar_2026_08_prospective_stages import (
    ArchiveDataBlockedError,
    ProspectiveInvalidStateError,
    _as_windows_path,
    _as_wsl_path,
    _format_command,
    _freeze_text,
    _read_march_nirvana_json,
    _scope_inputs,
    _write_return_manifest,
    _verify_resumed_stage_three,
    _verify_x64_local_freeze,
)


ROOT = Path(__file__).resolve().parents[2]


def test_x64_local_freeze_is_content_gate_and_arm_comparison_is_informational(tmp_path: Path) -> None:
    archive = tmp_path / "variant_summary_2026-08.txt.gz"
    archive.write_bytes(b"frozen-x64")
    sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    md5 = hashlib.md5(archive.read_bytes()).hexdigest()
    record = tmp_path / "x64_raw_freeze.json"
    record.write_text(
        json.dumps(
            {
                "schema": "raptor.eval.x64_local_raw_freeze.v1",
                "registration_id": "clinvar-2026-08-amendment-v3",
                "exact_url": "https://example.test/archive",
                "final_url": "https://example.test/archive",
                "http_status": 200,
                "last_modified_utc": "2026-08-06T04:05:02Z",
                "byte_length": len(b"frozen-x64"),
                "sha256": sha256,
                "md5": md5,
                "repeat_download_sha256": sha256,
                "repeat_download_md5": md5,
                "label_or_row_access_before_freeze": False,
                "prior_arm_sha256": "0" * 64,
                "prior_arm_md5": "0" * 32,
            }
        ),
        encoding="utf-8",
    )
    result = _verify_x64_local_freeze(
        archive,
        record,
        expected_url="https://example.test/archive",
        expected_filename=archive.name,
        expected_length=len(b"frozen-x64"),
        expected_last_modified="2026-08-06T04:05:02Z",
    )
    assert result["raw_sha256"] == sha256
    assert result["arm_comparison"]["informational_only"] is True
    assert result["arm_comparison"]["cross_host_sha256_match"] is False


def test_x64_local_freeze_rejects_content_before_parse(tmp_path: Path) -> None:
    archive = Path(__file__)
    record = tmp_path / "x64_raw_freeze.json"
    record.write_text(
        json.dumps(
            {
                "schema": "raptor.eval.x64_local_raw_freeze.v1",
                "registration_id": "clinvar-2026-08-amendment-v3",
                "exact_url": "https://example.test/archive",
                "final_url": "https://example.test/archive",
                "http_status": 200,
                "last_modified_utc": "2026-08-06T04:05:02Z",
                "byte_length": 1,
                "sha256": "0" * 64,
                "md5": "0" * 32,
                "repeat_download_sha256": "0" * 64,
                "repeat_download_md5": "0" * 32,
                "label_or_row_access_before_freeze": False,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArchiveDataBlockedError, match="byte length mismatch"):
        _verify_x64_local_freeze(
            archive,
            record,
            expected_url="https://example.test/archive",
            expected_filename=archive.name,
            expected_length=1,
            expected_last_modified="2026-08-06T04:05:02Z",
        )


def test_march_nirvana_adapter_reads_monolithic_json_identity_only(tmp_path: Path) -> None:
    path = tmp_path / "march.json"
    path.write_text(
        json.dumps(
            {
                "variants": [
                    {
                        "chromosome": "chr9",
                        "position": 123,
                        "refAllele": "A",
                        "altAllele": "G",
                        "variationId": 77,
                        "clinicalSignificance": "must not be read",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert _read_march_nirvana_json(path) == [
        {
            "chromosome": "chr9",
            "position": 123,
            "ref": "A",
            "alt": "G",
            "VariationID": "77",
        }
    ]


def test_scope_inputs_reuses_report_counts_and_marks_applicable_skips() -> None:
    envelope = {
        "report": {
            "config_pins": {"evaluation_skipped_criteria": ["PM1"]},
            "metrics": {
                "missense": {
                    "counts": {
                        "tp": 4,
                        "tn": 3,
                        "path_actual": 5,
                        "path_called": 4,
                        "benign_actual": 4,
                        "benign_called": 3,
                    }
                }
            },
            "scope_gate": {
                "scopes": {
                    "missense:pathogenic": {
                        "actual_count": 5,
                        "called_count": 4,
                        "coverage_adequate": False,
                        "metric_status": "UNMET",
                        "reasons": ["precision_lb=0.1<0.9"],
                    },
                    "missense:benign": {
                        "actual_count": 4,
                        "called_count": 3,
                        "coverage_adequate": False,
                        "metric_status": "UNMET",
                        "reasons": [],
                    },
                }
            },
        }
    }
    spec = {
        "locked_policy_values": {
            "criterion_scope_applicability": {"PM1": ["missense:pathogenic"]}
        }
    }
    result = _scope_inputs(envelope, spec, SimpleNamespace(min_count_per_class=36))
    assert result["missense:pathogenic"]["correct_calls"] == 4
    assert result["missense:pathogenic"]["policy_parity"] == "BLOCKED"
    assert "evaluation_skipped_criteria:PM1" in result["missense:pathogenic"]["reasons"]
    assert result["missense:benign"]["policy_parity"] == "CLEAR"


def test_runner_does_not_offer_skip_verify_flag() -> None:
    source = (ROOT / "scripts/run_clinvar_2026_08_prospective_stages.py").read_text(
        encoding="utf-8"
    )
    assert "--skip-verify" not in source
    assert "--x64-freeze-record" in source
    assert "--march-clinvar-vcf" in source
    assert "--march-nirvana-json" in source
    assert "--march-variant-summary" in source
    assert "--march-submission-summary" in source
    assert "raw_freeze_record_path" not in source


def test_stage_runner_builds_run_local_bias_pipeline_and_uses_effective_config() -> None:
    source = (ROOT / "scripts/run_clinvar_2026_08_prospective_stages.py").read_text(
        encoding="utf-8"
    )
    assert "--scoring-command" not in source
    assert "mask_clinvar_vcf_for_holdout.py" in source
    assert "generate_pathogenic_aa_list.py" in source
    assert "find_missense_pathogenic_genes_and_path_trunc_genes.py" in source
    assert "generate_domain_lists.py" in source
    assert "create_new_required_paths_file.py" in source
    assert 'declared_skips={"PM1"}' in source
    assert "policy_eval_config_sha256" in source
    assert "policy_state, policy_reason" in source
    assert "BASE_EVAL," in source
    assert "verify_mask_attestation(holdout_manifest, mask_ledger, remask_audit)" in source


def test_freeze_text_refuses_to_replace_nonidentical_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "frozen.json"
    _freeze_text(artifact, "first\n")
    assert _freeze_text(artifact, "first\n") == hashlib.sha256(b"first\n").hexdigest()
    with pytest.raises(ProspectiveInvalidStateError, match="refusing to overwrite"):
        _freeze_text(artifact, "second\n")


def test_return_manifest_uses_verified_checksum_format(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.tsv"
    artifact.write_text("content\n", encoding="utf-8")
    manifest = tmp_path / "RETURN_MANIFEST.sha256.txt"
    _write_return_manifest(tmp_path, manifest)
    assert manifest.read_text(encoding="utf-8") == (
        f"{hashlib.sha256(artifact.read_bytes()).hexdigest()} *artifact.tsv\n"
    )


def test_nirvana_command_formatter_substitutes_only_explicit_paths(tmp_path: Path) -> None:
    command = _format_command(
        ["nirvana", "-i", "{input_vcf}", "-o", "{output_prefix}"],
        input_vcf=tmp_path / "holdout.vcf",
        output_prefix=tmp_path / "holdout_nirvana",
    )
    assert command == [
        "nirvana",
        "-i",
        str(tmp_path / "holdout.vcf"),
        "-o",
        str(tmp_path / "holdout_nirvana"),
    ]


def test_resumed_stage_three_requires_frozen_artifact_hashes(tmp_path: Path) -> None:
    for filename, content in (
        ("benchmark.jsonl", "benchmark\n"),
        ("train_dev.jsonl", "train\n"),
        ("holdout.jsonl", "holdout\n"),
    ):
        (tmp_path / filename).write_text(content, encoding="utf-8")
    archive_sha = "a" * 64
    stats = {
        "registration_id": "clinvar-2026-08-amendment-v3",
        "archive": {"raw_sha256": archive_sha},
        "artifacts_sha256": {
            key: hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest()
            for key, filename in (
                ("benchmark", "benchmark.jsonl"),
                ("train_dev", "train_dev.jsonl"),
                ("holdout", "holdout.jsonl"),
            )
        },
    }
    _verify_resumed_stage_three(tmp_path, stats, {"raw_sha256": archive_sha})
    (tmp_path / "holdout.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ProspectiveInvalidStateError, match="holdout hash"):
        _verify_resumed_stage_three(tmp_path, stats, {"raw_sha256": archive_sha})


@pytest.mark.skipif(os.name != "posix", reason="Windows paths are converted only by the WSL operator")
def test_wsl_operator_paths_map_to_the_designated_mount() -> None:
    assert _as_wsl_path(Path(r"D:\raptor-x64\BIAS-2015")) == Path(
        "/mnt/d/raptor-x64/BIAS-2015"
    )


@pytest.mark.skipif(os.name != "posix", reason="Windows paths are needed only for WSL interop")
def test_nirvana_receives_windows_paths_from_wsl() -> None:
    assert _as_windows_path(Path("/mnt/d/raptor-x64/Nirvana-v3.18.1/Nirvana.dll")) == (
        r"D:\raptor-x64\Nirvana-v3.18.1\Nirvana.dll"
    )
    assert _format_command(
        ["/mnt/d/raptor-x64/dotnet-runtime-6/dotnet.exe", "{input_vcf}"],
        input_vcf=Path("/mnt/d/raptor-x64/run/holdout.vcf"),
        output_prefix=Path("/mnt/d/raptor-x64/run/out"),
    ) == [
        "/mnt/d/raptor-x64/dotnet-runtime-6/dotnet.exe",
        r"D:\raptor-x64\run\holdout.vcf",
    ]
