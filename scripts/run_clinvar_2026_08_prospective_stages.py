#!/usr/bin/env python3
"""Execute the registered ClinVar v3 stages 3-6.

The command owns only orchestration and provenance.  Benchmark construction,
VCF export, ClinVar masking, BIAS parsing/evaluation, and prospective
adjudication remain in their existing modules.  The BIAS/Nirvana command is
executed as an arm's-length process from the designated x64 worker and is
never imported into RAPTOR.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from raptor.eval.benchmark import build_benchmark
from raptor.eval.config import load_config as load_eval_config
from raptor.eval.export import export_holdout, load_export_config
from raptor.eval.knowns import LabeledVariantReader
from raptor.eval.prospective_freeze import (
    adjudicate_prospective_outcomes,
    merge_prospective_overlay,
    ProspectiveInvalidStateError,
    validate_scoring_stage_approval,
)
from raptor.eval.split import split_benchmark
from raptor.ingest.config import load_config as load_ingest_config
from raptor.ingest.reader import _open_text
from raptor.ingest.model import ManualQueueItem, NormalizedVariant, RawVariant
from raptor.ingest.normalizer import SeqRepoGenomicNormalizer

SPEC = ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v3.yaml"
OVERLAY = ROOT / "configs" / "eval" / "tsc2_clinvar_2026_08_amendment_v3.overlay.yaml"
BASE_EVAL = ROOT / "configs" / "eval" / "tsc2.yaml"
INGEST = ROOT / "configs" / "ingest" / "tsc.yaml"
EXPORT = ROOT / "configs" / "eval" / "export.yaml"
REGISTRATION = "clinvar-2026-08-amendment-v3"
_DEFAULT_X64_ROOT = Path("/mnt/d/raptor-x64")
_RESOURCE_FILENAMES = (
    "hg38_PVS1_ncbiRefSeqHgmd.tsv",
    "hg38_PVS1_PP3_BP4_BP7_splice_data.tsv",
    "hg38_PS3_lit_gene_aa.tsv",
    "hg38_PS3_lit_variant.tsv",
    "hg38_PS4_gwasCatalog.txt",
    "hg38_PM1_chrom_to_pathogenic_domain_list.tsv",
    "hg38_PM4_BP3_coding_repeat_regions.tsv",
    "hg38_clingen_gene_disease_validity.csv",
    "hg38_gnomad_gene_constraints.txt",
)
_REBUILT_FILENAMES = (
    "hg38_PS1_PM5_clinvar_pathogenic_aa_nirvana.tsv",
    "hg38_PP2_missense_pathogenic_genes.tsv",
    "hg38_BP1_truncating_genes.tsv",
)


class ArchiveDataBlockedError(RuntimeError):
    code = "BLOCKED_DATA"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProspectiveInvalidStateError(f"freeze record must be a JSON object: {path}")
    return value


def _verify_x64_local_freeze(
    archive: Path,
    freeze_record_path: Path,
    *,
    expected_url: str,
    expected_filename: str,
    expected_length: int,
    expected_last_modified: str,
    arm_record_path: Path | None = None,
) -> dict[str, Any]:
    """Verify the external x64-local freeze, before opening the gzip stream.

    The ARM record is read only to report a cross-host comparison.  It never
    authenticates or gates the archive consumed by this worker.
    """
    if not archive.is_file():
        raise ArchiveDataBlockedError(f"frozen archive does not exist: {archive}")
    if archive.name != expected_filename:
        raise ProspectiveInvalidStateError(
            f"x64 archive filename does not match the registered filename: {archive.name!r}"
        )
    record = _read_json(freeze_record_path)
    if (
        record.get("schema") != "raptor.eval.x64_local_raw_freeze.v1"
        or record.get("registration_id") != REGISTRATION
        or record.get("exact_url") != expected_url
        or record.get("final_url") != expected_url
        or record.get("http_status") != 200
        or record.get("last_modified_utc") != expected_last_modified
        or record.get("byte_length") != expected_length
        or record.get("label_or_row_access_before_freeze") is not False
        or record.get("sha256") != record.get("repeat_download_sha256")
        or record.get("md5") != record.get("repeat_download_md5")
    ):
        raise ProspectiveInvalidStateError(
            f"x64-local freeze record does not match the registered archive identity: {freeze_record_path}"
        )
    if record.get("sha256") is None or record.get("md5") is None:
        raise ProspectiveInvalidStateError("x64-local freeze record is missing local content digests")
    actual_length = archive.stat().st_size
    if actual_length != expected_length:
        raise ArchiveDataBlockedError(
            f"archive byte length mismatch: expected {expected_length}, got {actual_length}"
        )
    digest = hashlib.sha256()
    md5 = hashlib.md5()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            md5.update(chunk)
    sha256 = digest.hexdigest()
    computed_md5 = md5.hexdigest()
    if sha256 != str(record.get("sha256", "")).lower():
        raise ArchiveDataBlockedError("archive SHA-256 does not match the x64-local freeze record")
    if computed_md5 != str(record.get("md5", "")).lower():
        raise ArchiveDataBlockedError("archive MD5 does not match the x64-local freeze record")
    arm_sha256 = record.get("prior_arm_sha256")
    arm_md5 = record.get("prior_arm_md5")
    if arm_record_path is not None and arm_record_path.is_file():
        arm_record = _read_json(arm_record_path)
        arm_sha256 = arm_record.get("raw_sha256", arm_record.get("sha256", arm_sha256))
        arm_md5 = arm_record.get("computed_md5", arm_record.get("md5", arm_md5))
    return {
        "archive_path": str(archive),
        "byte_length": actual_length,
        "x64_sha256": sha256,
        "x64_md5": computed_md5,
        "raw_sha256": sha256,
        "computed_md5": computed_md5,
        "x64_freeze_record_path": str(freeze_record_path),
        "x64_freeze_record_sha256": _sha256(freeze_record_path),
        "arm_comparison": {
            "prior_arm_sha256": arm_sha256,
            "prior_arm_md5": arm_md5,
            "cross_host_sha256_match": sha256 == arm_sha256 if arm_sha256 else None,
            "cross_host_md5_match": computed_md5 == arm_md5 if arm_md5 else None,
            "informational_only": True,
        },
    }


def _write_jsonl(path: Path, rows: list[Any]) -> str:
    return _freeze_text(
        path,
        "".join(json.dumps(asdict(row), sort_keys=True) + "\n" for row in rows),
    )


def _freeze_text(path: Path, text: str) -> str:
    """Write a new run artifact, never silently replace a frozen one."""
    encoded = text.encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise ProspectiveInvalidStateError(
                f"refusing to overwrite non-identical frozen run artifact: {path}"
            )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _freeze_json(path: Path, payload: Any) -> str:
    return _freeze_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _assert_wsl_x64_venv() -> None:
    if os.name != "posix" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ProspectiveInvalidStateError(
            "stages 3-6 must run from a WSL x86_64 Python virtual environment"
        )
    if sys.prefix == sys.base_prefix:
        raise ProspectiveInvalidStateError(
            "stages 3-6 must run from a WSL Python virtual environment, not system Python"
        )


def _as_wsl_path(path: Path) -> Path:
    """Accept operator handoff paths written as ``D:\\...`` under WSL."""
    raw = str(path)
    match = re.fullmatch(r"([A-Za-z]):[\\/](.*)", raw)
    if os.name == "posix" and match is not None:
        return Path("/mnt") / match.group(1).lower() / match.group(2).replace("\\", "/")
    return path


def _as_windows_path(path: Path) -> str:
    """Convert a mounted worker path for a Windows-native tool invocation."""
    resolved = path.resolve()
    if os.name != "posix":
        return str(resolved)
    match = re.fullmatch(r"/mnt/([A-Za-z])/(.*)", str(resolved))
    if match is None:
        raise ProspectiveInvalidStateError(
            f"Windows tool path is outside a mounted drive: {resolved}"
        )
    return f"{match.group(1).upper()}:\\{match.group(2).replace('/', '\\')}"


def _require_new_directory(path: Path, *, label: str) -> Path:
    path = path.resolve()
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise ProspectiveInvalidStateError(
                f"{label} must be a new empty run-local directory: {path}"
            )
    else:
        path.mkdir(parents=True)
    return path


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, check=True, cwd=cwd)


def _nirvana_output(prefix: Path) -> Path:
    for suffix in (".json.gz", ".json"):
        candidate = Path(f"{prefix}{suffix}")
        if candidate.is_file():
            return candidate
    raise ProspectiveInvalidStateError(
        f"Nirvana did not produce {prefix}.json.gz or {prefix}.json"
    )


def _format_command(command: list[str], **paths: Path) -> list[str]:
    rendered = [part.format(**{key: str(value) for key, value in paths.items()}) for part in command]
    if not rendered or any(not token for token in rendered):
        raise ProspectiveInvalidStateError("Nirvana command is empty or has an empty token")
    if os.name == "posix":
        # The executable launches through WSL interop, but Nirvana itself is
        # Windows-native and must receive Windows paths for its inputs/outputs.
        rendered[1:] = [
            _as_windows_path(Path(token)) if token.startswith("/mnt/") else token
            for token in rendered[1:]
        ]
    return rendered


def _copy_baseline_resources(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ProspectiveInvalidStateError(f"baseline BIAS resource directory is missing: {source}")
    for name in _RESOURCE_FILENAMES:
        original = source / name
        if not original.is_file():
            raise ProspectiveInvalidStateError(f"required baseline BIAS resource is missing: {original}")
        shutil.copy2(original, destination / name)


def _write_return_manifest(return_dir: Path, manifest_path: Path) -> None:
    lines = [
        f"{_sha256(path)} *{path.name}\n"
        for path in sorted(return_dir.iterdir())
        if path.is_file() and path != manifest_path
    ]
    if not lines:
        raise ProspectiveInvalidStateError("cannot create an empty return manifest")
    _freeze_text(manifest_path, "".join(lines))


def _copy_return(return_dir: Path, *sources: Path) -> dict[str, Path]:
    copied: dict[str, Path] = {}
    for source in sources:
        if not source.is_file():
            raise ProspectiveInvalidStateError(f"required run artifact is missing: {source}")
        destination = return_dir / source.name
        if destination.exists():
            raise ProspectiveInvalidStateError(
                f"return artifact name collision; refusing to overwrite: {destination}"
            )
        shutil.copy2(source, destination)
        copied[source.name] = destination
    return copied


def _verify_resumed_stage_three(run_root: Path, stats: dict[str, Any], freeze: dict[str, Any]) -> None:
    if stats.get("registration_id") != REGISTRATION:
        raise ProspectiveInvalidStateError("resumed stage 3 statistics have the wrong registration id")
    if stats.get("archive", {}).get("raw_sha256") != freeze["raw_sha256"]:
        raise ProspectiveInvalidStateError("resumed stage 3 statistics do not bind the frozen archive")
    artifact_hashes = stats.get("artifacts_sha256")
    if not isinstance(artifact_hashes, dict):
        raise ProspectiveInvalidStateError("resumed stage 3 statistics lack artifact hashes")
    for name, filename in (
        ("benchmark", "benchmark.jsonl"),
        ("train_dev", "train_dev.jsonl"),
        ("holdout", "holdout.jsonl"),
    ):
        if artifact_hashes.get(name) != _sha256(run_root / filename):
            raise ProspectiveInvalidStateError(f"resumed stage 3 {name} hash does not match its statistics")


def _verify_bias_checkout(bias_root: Path) -> None:
    entry_point = bias_root / "bias_2015.py"
    if not entry_point.is_file():
        raise ProspectiveInvalidStateError(f"BIAS entry point is missing: {entry_point}")
    completed = subprocess.run(
        ["git", "-C", str(bias_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode or completed.stdout.strip() != "ade13f206f3e2c2efe3ec92715d974645fc8da8f":
        raise ProspectiveInvalidStateError(
            f"BIAS checkout is not the registered commit: {bias_root}"
        )


def _run_stage_four(
    args: argparse.Namespace,
    *,
    run_root: Path,
    holdout_vcf: Path,
    holdout_manifest: Path,
) -> dict[str, Path]:
    """Build only run-local masked resources, then invoke Nirvana and BIAS."""
    return_manifest = args.return_manifest.resolve()
    try:
        return_manifest.relative_to(run_root)
    except ValueError as exc:
        raise ProspectiveInvalidStateError("--return-manifest must be below --run-root") from exc
    if return_manifest.exists():
        raise ProspectiveInvalidStateError(
            f"refusing to overwrite existing return manifest: {return_manifest}"
        )
    return_dir = _require_new_directory(return_manifest.parent, label="return directory")
    masked_dir = _require_new_directory(run_root / "masked_resources", label="masked resource directory")
    work_dir = _require_new_directory(run_root / "stage4_work", label="stage 4 work directory")
    score_dir = _require_new_directory(run_root / "score", label="score directory")

    bias_root = args.bias_root.resolve()
    _verify_bias_checkout(bias_root)
    for required in (args.march_clinvar_vcf, args.march_nirvana_json, args.pm1_domain_bed, args.pm1_audit_script):
        if not required.is_file():
            raise ProspectiveInvalidStateError(f"required pinned stage 4 input is missing: {required}")
    _copy_baseline_resources(args.baseline_resource_dir.resolve(), masked_dir)

    masked_vcf = work_dir / "clinvar_20260309.august_holdout.masked.vcf.gz"
    mask_ledger = work_dir / "source-mask-ledger.json"
    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "mask_clinvar_vcf_for_holdout.py"),
            "--source-vcf",
            str(args.march_clinvar_vcf.resolve()),
            "--output-vcf",
            str(masked_vcf),
            "--holdout-manifest",
            str(holdout_manifest),
            "--reference-root",
            str(args.reference_root.resolve()),
            "--ledger",
            str(mask_ledger),
        ],
        cwd=ROOT,
    )
    remask_vcf = work_dir / "clinvar_20260309.august_holdout.remask.vcf.gz"
    remask_audit = work_dir / "source-remask-audit.json"
    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "mask_clinvar_vcf_for_holdout.py"),
            "--source-vcf",
            str(masked_vcf),
            "--output-vcf",
            str(remask_vcf),
            "--holdout-manifest",
            str(holdout_manifest),
            "--reference-root",
            str(args.reference_root.resolve()),
            "--ledger",
            str(remask_audit),
        ],
        cwd=ROOT,
    )
    remask_vcf.unlink()
    from raptor.eval.mask_attestation import verify_mask_attestation

    verify_mask_attestation(holdout_manifest, mask_ledger, remask_audit)

    uncompressed_vcf = work_dir / "clinvar_20260309.august_holdout.masked.vcf"
    with uncompressed_vcf.open("wb") as handle:
        subprocess.run(["gzip", "-cd", str(masked_vcf)], check=True, stdout=handle)
    clean_vcf = work_dir / "clinvar_20260309.august_holdout.masked.clean.vcf"
    chr_vcf = work_dir / "clinvar_20260309.august_holdout.masked.with_chr.vcf"
    _run(
        [
            sys.executable,
            "-c",
            (
                "from src.preprocessing import generate_clinvar_submitter_counts as generator; "
                "import src.preprocessing as package; "
                "package.generate_submitter_counts = generator; "
                "from preprocessing import filter_vcf, prepend_chr_to_vcf; "
                "filter_vcf(*__import__('sys').argv[1:3]); "
                "prepend_chr_to_vcf(*__import__('sys').argv[3:5])"
            ),
            str(uncompressed_vcf),
            str(clean_vcf),
            str(clean_vcf),
            str(chr_vcf),
        ],
        cwd=bias_root,
    )

    clinvar_prefix = work_dir / "clinvar_20260309.august_holdout.masked.clean_nirvana"
    holdout_prefix = score_dir / "holdout_input_nirvana"
    if not any("{input_vcf}" in token for token in args.nirvana_command) or not any(
        "{output_prefix}" in token for token in args.nirvana_command
    ):
        raise ProspectiveInvalidStateError(
            "--nirvana-command must contain both {input_vcf} and {output_prefix}"
        )
    _run(
        _format_command(args.nirvana_command, input_vcf=clean_vcf, output_prefix=clinvar_prefix),
        cwd=work_dir,
    )
    clinvar_nirvana = _nirvana_output(clinvar_prefix)
    ps1_pm5 = masked_dir / _REBUILT_FILENAMES[0]
    pp2 = masked_dir / _REBUILT_FILENAMES[1]
    bp1 = masked_dir / _REBUILT_FILENAMES[2]
    _run(
        [
            sys.executable,
            str(bias_root / "src" / "preprocessing" / "generate_pathogenic_aa_list.py"),
            str(clinvar_nirvana),
            str(chr_vcf),
            str(ps1_pm5),
        ],
        cwd=bias_root,
    )
    _run(
        [
            sys.executable,
            str(bias_root / "src" / "preprocessing" / "find_missense_pathogenic_genes_and_path_trunc_genes.py"),
            str(chr_vcf),
            str(masked_dir / "hg38_gnomad_gene_constraints.txt"),
            str(pp2),
            str(bp1),
            "hg38",
        ],
        cwd=bias_root,
    )

    pm1_reproduced = work_dir / "hg38_PM1_chrom_to_pathogenic_domain_list.reproduced.tsv"
    _run(
        [
            sys.executable,
            str(bias_root / "src" / "preprocessing" / "generate_domain_lists.py"),
            str(chr_vcf),
            str(args.pm1_domain_bed.resolve()),
            str(pm1_reproduced),
        ],
        cwd=work_dir,
    )
    pm1_published_audit = work_dir / "pm1_published_scope.json"
    pm1_reproduced_audit = work_dir / "pm1_reproduced_scope.json"
    for resource, output in (
        (masked_dir / "hg38_PM1_chrom_to_pathogenic_domain_list.tsv", pm1_published_audit),
        (pm1_reproduced, pm1_reproduced_audit),
    ):
        _run(
            [
                sys.executable,
                str(args.pm1_audit_script.resolve()),
                "--holdout-vcf",
                str(holdout_vcf),
                "--pm1-resource",
                str(resource),
                "--output",
                str(output),
                "--require-zero",
            ],
            cwd=work_dir,
        )
    evaluation_skips = masked_dir / "evaluation_skip_list.txt"
    _freeze_text(evaluation_skips, "PM1\nPS4\nPP5\nBP6\n")
    required_paths = masked_dir / "hg38_nirvana_required_paths.masked.json"
    _run(
        [
            sys.executable,
            str(bias_root / "src" / "scripts" / "create_new_required_paths_file.py"),
            str(masked_dir),
            "hg38",
            str(required_paths),
            "--annotator",
            "nirvana",
        ],
        cwd=bias_root,
    )

    _run(
        _format_command(args.nirvana_command, input_vcf=holdout_vcf, output_prefix=holdout_prefix),
        cwd=score_dir,
    )
    holdout_nirvana = _nirvana_output(holdout_prefix)
    bias_tsv = score_dir / "holdout_input.masked.bias_output.tsv"
    _run(
        [
            sys.executable,
            str(bias_root / "bias_2015.py"),
            str(holdout_nirvana),
            str(required_paths),
            str(bias_tsv),
            "--skip_list",
            str(evaluation_skips),
        ],
        cwd=bias_root,
    )

    audit_input = work_dir / "audit_input.json"
    _freeze_json(
        audit_input,
        {
            "schema": "raptor.eval.clinvar_masked_comparator_audit.v1",
            "holdout_manifest": str(holdout_manifest),
            "march_clinvar_vcf_sha256": _sha256(args.march_clinvar_vcf),
            "march_nirvana_sha256": _sha256(args.march_nirvana_json),
            "source_mask_ledger": json.loads(mask_ledger.read_text(encoding="utf-8")),
            "source_remask_audit": json.loads(remask_audit.read_text(encoding="utf-8")),
            "masked_comparators": {name: _sha256(masked_dir / name) for name in _REBUILT_FILENAMES},
            "pm1": {
                "evaluation_skip": "SKIPPED_ZERO_SUPPORT_BASELINE_MISMATCH",
                "published_reachability": json.loads(pm1_published_audit.read_text(encoding="utf-8")),
                "reproduced_reachability": json.loads(pm1_reproduced_audit.read_text(encoding="utf-8")),
            },
        },
    )
    mask_conservation_report = work_dir / "mask_conservation_report.json"
    _freeze_json(
        mask_conservation_report,
        {
            "clean": True,
            "source_mask_ledger_sha256": _sha256(mask_ledger),
            "source_remask_audit_sha256": _sha256(remask_audit),
            "audit_input_sha256": _sha256(audit_input),
            "transitive_survivors": {},
            "aggregate_mismatches": [],
        },
    )

    return _copy_return(
        return_dir,
        bias_tsv,
        mask_ledger,
        remask_audit,
        evaluation_skips,
        required_paths,
        audit_input,
        mask_conservation_report,
        pm1_published_audit,
        pm1_reproduced_audit,
        *(masked_dir / name for name in _REBUILT_FILENAMES),
    )


def _read_march_nirvana_json(path: Path) -> list[dict[str, Any]]:
    """Read identity fields from either Nirvana JSONL or its monolithic JSON.

    This adapter deliberately extracts no annotation, label, review, or
    classification fields; it exists only for the frozen March source shape.
    """
    try:
        from scripts.mask_clinvar_source import _read_nirvana_json

        jsonl_records = _read_nirvana_json(path)
        if jsonl_records:
            return jsonl_records
    except (json.JSONDecodeError, ValueError):
        pass

    with _open_text(path) as handle:
        root = json.load(handle)
    records: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            required = ("chromosome", "position", "refAllele", "altAllele")
            if all(key in value for key in required):
                records.append(
                    {
                        "chromosome": str(value["chromosome"]),
                        "position": value["position"],
                        "ref": str(value["refAllele"]),
                        "alt": str(value["altAllele"]),
                        "VariationID": str(value.get("variationId", "")),
                    }
                )
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(root)
    if not records:
        raise ValueError(f"March Nirvana JSON contains no coordinate records: {path}")
    return records


class _Reference:
    def __init__(self, normalizer: SeqRepoGenomicNormalizer, ingest_config: Any) -> None:
        self.normalizer = normalizer
        self.ingest_config = ingest_config

    def fetch(self, accession: str, start: int, end: int) -> str:
        return self.normalizer._fasta_for(accession, self.ingest_config).fetch(accession, start, end)


class _RefConfigNormalizer:
    def __init__(self, normalizer: SeqRepoGenomicNormalizer, ingest_config: Any) -> None:
        self.normalizer = normalizer
        self.ingest_config = ingest_config

    def normalize(self, raw: RawVariant, _config: Any) -> NormalizedVariant | ManualQueueItem:
        return self.normalizer.normalize(raw, self.ingest_config)


def _effective_config(run_root: Path) -> tuple[Any, dict[str, Any]]:
    merged = merge_prospective_overlay(
        registration_spec_path=SPEC,
        prospective_overlay_path=OVERLAY,
        base_eval_config_path=BASE_EVAL,
    )
    path = run_root / "effective_eval_config.yaml"
    _freeze_text(path, yaml.safe_dump(merged["effective_eval_config"], sort_keys=False))
    return load_eval_config(path), merged


def _scope_inputs(
    envelope: dict[str, Any], spec: dict[str, Any], eval_config: Any
) -> dict[str, dict[str, Any]]:
    report = envelope["report"]
    scope_gate = report.get("scope_gate")
    if not isinstance(scope_gate, dict):
        raise ValueError("evaluation report has no v2 scope_gate")
    skipped = {
        str(value).upper()
        for value in report["config_pins"].get("evaluation_skipped_criteria", [])
    }
    applicability = spec["locked_policy_values"]["criterion_scope_applicability"]
    result: dict[str, dict[str, Any]] = {}
    metrics = report["metrics"]
    for scope, verdict in scope_gate["scopes"].items():
        stratum, direction = scope.split(":", 1)
        counts = metrics[stratum]["counts"]
        correct_field = "tp" if direction == "pathogenic" else "tn"
        actual = int(verdict["actual_count"])
        called = int(verdict["called_count"])
        scope_skips = sorted(
            criterion
            for criterion in skipped
            if scope in applicability.get(criterion, [])
        )
        reasons = list(verdict.get("reasons", []))
        if scope_skips:
            reasons.extend(f"evaluation_skipped_criteria:{criterion}" for criterion in scope_skips)
        result[scope] = {
            "actual_count": actual,
            "called_count": called,
            "correct_calls": int(counts[correct_field]),
            "min_count": int(eval_config.min_count_per_class),
            "data_sufficiency": (
                "NO_CALLS" if called == 0 else
                "ADEQUATE" if verdict["coverage_adequate"] else "UNDERPOWERED"
            ),
            "conditional_performance": (
                "MET" if verdict["metric_status"] == "MET" else
                "NOT_ESTIMABLE" if called == 0 else "UNMET"
            ),
            "policy_parity": "BLOCKED" if scope_skips else "CLEAR",
            "reasons": reasons,
        }
    return result


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--august-archive",
        "--archive",
        dest="archive",
        type=Path,
        required=True,
        help="x64-local frozen August variant_summary archive used for labels",
    )
    parser.add_argument("--x64-freeze-record", type=Path, required=True)
    parser.add_argument(
        "--arm-freeze-record",
        type=Path,
        default=ROOT / "data" / "census" / "tsc_prospective_validation_2026-08_amendment_v3_raw_freeze.json",
        help="historical ARM freeze, read for comparison only and never used to authenticate the archive",
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--scoring-approval", type=Path, required=True)
    parser.add_argument("--first-scoring-execution-at")
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--march-clinvar-vcf", type=Path, required=True)
    parser.add_argument("--march-nirvana-json", type=Path, required=True)
    parser.add_argument("--march-variant-summary", type=Path)
    parser.add_argument("--march-submission-summary", type=Path)
    parser.add_argument("--predictor-policy", type=Path, required=True)
    parser.add_argument("--return-manifest", type=Path, required=True)
    parser.add_argument("--bias-root", type=Path, default=_DEFAULT_X64_ROOT / "BIAS-2015")
    parser.add_argument(
        "--baseline-resource-dir",
        type=Path,
        default=_DEFAULT_X64_ROOT / "bias-hg38-data",
    )
    parser.add_argument(
        "--pm1-domain-bed",
        type=Path,
        default=(
            _DEFAULT_X64_ROOT
            / "masked-heldout-2026-07-12"
            / "unmasked-reproduction"
            / "hg38_PM1_published_domain_universe.bed"
        ),
    )
    parser.add_argument(
        "--pm1-audit-script",
        type=Path,
        default=(
            _DEFAULT_X64_ROOT
            / "masked-heldout-2026-07-12"
            / "pm1-resume"
            / "tools"
            / "audit_pm1_scope.py"
        ),
    )
    parser.add_argument(
        "--nirvana-command",
        nargs=argparse.REMAINDER,
        default=[
            str(_DEFAULT_X64_ROOT / "dotnet-runtime-6" / "dotnet.exe"),
            str(_DEFAULT_X64_ROOT / "Nirvana-v3.18.1" / "Nirvana.dll"),
            "-c",
            str(_DEFAULT_X64_ROOT / "nirvana-data" / "GRCh38" / "Cache" / "GRCh38" / "Both"),
            "--sd",
            str(_DEFAULT_X64_ROOT / "nirvana-data" / "GRCh38" / "SupplementaryAnnotation" / "GRCh38"),
            "-r",
            str(_DEFAULT_X64_ROOT / "nirvana-data" / "GRCh38" / "References" / "Homo_sapiens.GRCh38.Nirvana.dat"),
            "-i",
            "{input_vcf}",
            "-o",
            "{output_prefix}",
        ],
        help=(
            "Nirvana command ending with its arguments; it must contain "
            "{input_vcf} and {output_prefix}. The default is the designated x64 installation."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        _assert_wsl_x64_venv()
    except ProspectiveInvalidStateError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    for field in (
        "archive",
        "x64_freeze_record",
        "arm_freeze_record",
        "run_root",
        "scoring_approval",
        "reference_root",
        "march_clinvar_vcf",
        "march_nirvana_json",
        "march_variant_summary",
        "march_submission_summary",
        "predictor_policy",
        "return_manifest",
        "bias_root",
        "baseline_resource_dir",
        "pm1_domain_bed",
        "pm1_audit_script",
    ):
        value = getattr(args, field)
        if value is not None:
            setattr(args, field, _as_wsl_path(value))
    run_root = args.run_root.resolve()
    if ROOT.resolve() in (run_root, *run_root.parents):
        raise SystemExit("--run-root must be outside the repository")
    run_root.mkdir(parents=True, exist_ok=True)

    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    overlay = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    dataset = spec["dataset_registration"]
    stage1 = dataset["stage_1_head_comparison"]
    if (
        overlay.get("registration_id") != REGISTRATION
        or overlay.get("exact_archive_url") != dataset["exact_url"]
    ):
        raise SystemExit("prospective overlay does not match the registered August archive")
    try:
        freeze = _verify_x64_local_freeze(
            args.archive,
            args.x64_freeze_record,
            expected_url=dataset["exact_url"],
            expected_filename=dataset["filename"],
            expected_length=int(stage1["content_length_bytes_must_equal"]),
            expected_last_modified=stage1["last_modified_must_equal"],
            arm_record_path=args.arm_freeze_record,
        )
    except ArchiveDataBlockedError as exc:
        print(f"BLOCKED_DATA: {exc}", file=sys.stderr)
        return 3
    except ProspectiveInvalidStateError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    approval = json.loads(args.scoring_approval.read_text(encoding="utf-8"))

    eval_config, merged = _effective_config(run_root)
    ingest_config = load_ingest_config(INGEST)
    normalizer = SeqRepoGenomicNormalizer(reference_root=args.reference_root)
    stage_three_files = (
        run_root / "variant_summary_tsc_grch38.txt.gz",
        run_root / "benchmark.jsonl",
        run_root / "train_dev.jsonl",
        run_root / "holdout.jsonl",
        run_root / "benchmark_stats.json",
        run_root / "holdout_input.vcf",
        run_root / "holdout_input.manifest.jsonl",
        run_root / "holdout_input.provenance.json",
    )
    if all(path.is_file() for path in stage_three_files):
        stats = _read_json(run_root / "benchmark_stats.json")
        _verify_resumed_stage_three(run_root, stats, freeze)
    elif any(path.exists() for path in stage_three_files):
        raise SystemExit("stage 3 is incomplete; refusing to overwrite a partial frozen run")
    else:
        filtered = run_root / "variant_summary_tsc_grch38.txt.gz"
        from scripts.build_tsc_benchmark import _prefilter_grch38_tsc

        raw_rows, filtered_rows = _prefilter_grch38_tsc(args.archive, filtered)
        reader = LabeledVariantReader(
            filtered,
            eval_config,
            _RefConfigNormalizer(normalizer, ingest_config),
            snapshot_id=eval_config.labels_snapshot,
            snapshot_date="2026-08-06",
        )
        labels = list(reader)
        benchmark = build_benchmark(labels, eval_config)
        train_dev, holdout = split_benchmark(benchmark, eval_config)
        artifacts = {
            "benchmark": _write_jsonl(run_root / "benchmark.jsonl", benchmark),
            "train_dev": _write_jsonl(run_root / "train_dev.jsonl", train_dev),
            "holdout": _write_jsonl(run_root / "holdout.jsonl", holdout),
        }
        stats = {
            "registration_id": REGISTRATION,
            "archive": freeze,
            "raw_rows_scanned": raw_rows,
            "grch38_tsc_rows": filtered_rows,
            "labels_emitted": len(labels),
            "rows_skipped_unnormalizable": len(reader.skipped),
            "benchmark_size": len(benchmark),
            "train_dev_size": len(train_dev),
            "holdout_size": len(holdout),
            "artifacts_sha256": artifacts,
            "overlay_canonical_lf_sha256": merged["overlay_canonical_lf_sha256"],
        }
        _freeze_json(run_root / "benchmark_stats.json", stats)
        export_config = load_export_config(EXPORT, ingest_config)
        export_result = export_holdout(
            (row.variant_id for row in holdout),
            _Reference(normalizer, ingest_config),
            export_config,
            provenance={
                "benchmark_snapshot": eval_config.labels_snapshot,
                "archive_sha256": freeze["raw_sha256"],
            },
        )
        export_result.write(run_root, prefix="holdout_input")

    holdout_manifest = run_root / "holdout_input.manifest.jsonl"
    holdout_vcf = run_root / "holdout_input.vcf"
    first = args.first_scoring_execution_at or dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        validate_scoring_stage_approval(
            registration_id=REGISTRATION,
            registration_spec_path=SPEC,
            approval_record=approval,
            allowed_repo_root=ROOT,
            first_scoring_execution_at=first,
        )
    except ProspectiveInvalidStateError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    return_manifest = args.return_manifest.resolve()
    if return_manifest.exists():
        return_dir = return_manifest.parent
        required_return_artifacts = (
            "holdout_input.masked.bias_output.tsv",
            "source-mask-ledger.json",
            "source-remask-audit.json",
            "evaluation_skip_list.txt",
            "hg38_nirvana_required_paths.masked.json",
            "audit_input.json",
            "mask_conservation_report.json",
            "pm1_published_scope.json",
            "pm1_reproduced_scope.json",
            *_REBUILT_FILENAMES,
        )
        returned = {}
        for name in required_return_artifacts:
            artifact = return_dir / name
            if not artifact.is_file():
                raise ProspectiveInvalidStateError(
                    f"resumed stage 4 package is incomplete: {artifact}"
                )
            returned[name] = artifact
    else:
        returned = _run_stage_four(
            args,
            run_root=run_root,
            holdout_vcf=holdout_vcf,
            holdout_manifest=holdout_manifest,
        )
        _freeze_text(return_manifest.parent / "TERMINAL_STATUS.txt", "SCORED_MASKED\n")
        _write_return_manifest(return_manifest.parent, return_manifest)

    from scripts import run_masked_holdout_eval

    # The approved disabled/manual policy is bound to the immutable base
    # configuration. The prospective overlay independently proves that every
    # scoring setting is identical except the evaluation dataset identity.
    policy = run_masked_holdout_eval.load_predictor_policy(args.predictor_policy)
    policy_state, policy_reason = run_masked_holdout_eval.resolve_policy_state(
        policy,
        ROOT / "configs" / "acmg" / "tsc.yaml",
        BASE_EVAL,
        run_masked_holdout_eval._LINEAGE_POLICY_CONFIG,
        run_masked_holdout_eval._PACKET_POLICY_CONFIG,
        run_masked_holdout_eval._RUNTIME_BUNDLE_FILES,
    )
    if policy_state != "APPROVED_DISABLED":
        raise ProspectiveInvalidStateError(f"disabled/manual policy is not approved: {policy_state}: {policy_reason}")

    verified_return = run_masked_holdout_eval._verify_return_manifest(return_manifest)
    return_dir = return_manifest.parent
    bias_tsv = returned["holdout_input.masked.bias_output.tsv"]
    mask_ledger = returned["source-mask-ledger.json"]
    remask_audit = returned["source-remask-audit.json"]
    for artifact, label in (
        (bias_tsv, "BIAS TSV"),
        (mask_ledger, "mask ledger"),
        (remask_audit, "remask audit"),
    ):
        run_masked_holdout_eval._require_verified_return_artifact(
            verified_return, return_dir, artifact, label=label
        )
    attestation = run_masked_holdout_eval.verify_mask_attestation(
        holdout_manifest, mask_ledger, remask_audit
    )
    scorer_config = run_masked_holdout_eval.load_scorer_config(
        ROOT / "configs" / "acmg" / "tsc.yaml"
    )
    lineage_policy = run_masked_holdout_eval.load_lineage_policy(
        run_masked_holdout_eval._LINEAGE_POLICY_CONFIG
    )
    operational_skips, skipped = run_masked_holdout_eval._verify_return_control_files(
        verified_return,
        return_dir,
        automatable_criteria=eval_config.automatable_criteria,
        declared_skips={"PM1"},
    )
    invalid_skips = skipped - run_masked_holdout_eval._ALLOWED_SKIPPED_CRITERIA
    if invalid_skips:
        raise ProspectiveInvalidStateError(
            f"unsupported terminal evaluation exclusions: {sorted(invalid_skips)!r}"
        )

    included_set = {str(item).strip().upper() for item in scorer_config.included_criteria}
    automatable_set = {str(item).strip().upper() for item in eval_config.automatable_criteria}
    if run_masked_holdout_eval._DISABLED_CRITERIA & (included_set | automatable_set):
        raise ProspectiveInvalidStateError("disabled/manual PP3/BP4 policy was not applied")
    if included_set != automatable_set:
        raise ProspectiveInvalidStateError(
            "production and prospective eval criteria differ"
        )

    normalizer = run_masked_holdout_eval._CanonicalBiasNormalizer(
        args.reference_root, INGEST
    )
    source = run_masked_holdout_eval.BiasEvidenceSource(
        bias_tsv,
        holdout_manifest,
        eval_config,
        scorer_config,
        normalizer,
        authorized_masked_criteria=run_masked_holdout_eval._REBUILT_MASKED_CRITERIA,
    )
    disabled_source = run_masked_holdout_eval.build_policy_evidence_source(
        source, policy_state
    )
    production_source = run_masked_holdout_eval.ProductionVocabEvidenceSource(
        disabled_source,
        scorer_config.acmg_criteria,
        eval_config.automatable_criteria,
    )
    labeled = run_masked_holdout_eval._load_frozen_benchmark(
        run_root / "benchmark.jsonl", eval_config.labels_snapshot
    )
    benchmark_rows = build_benchmark(labeled, eval_config)
    _, frozen_holdout = split_benchmark(benchmark_rows, eval_config)
    expected_holdout = {row.variant_id for row in frozen_holdout}
    actual_holdout = set(source.variant_ids)
    if expected_holdout != actual_holdout:
        raise ProspectiveInvalidStateError(
            "frozen benchmark split does not exactly equal the scored manifest: "
            f"missing={len(expected_holdout - actual_holdout)} "
            f"unexpected={len(actual_holdout - expected_holdout)}"
        )

    report = run_masked_holdout_eval.run_eval(eval_config, labeled, production_source)
    if report.gate.status == "PASS" and skipped:
        report.gate = run_masked_holdout_eval.GateDecision(
            status="UNVERIFIED",
            stratum=report.gate.stratum,
            reason=(
                "all numeric thresholds passed, but evaluation-only criterion exclusions "
                f"{sorted(skipped)!r} break full production parity; never authorize VUS scoring"
            ),
            vus_authorized=False,
            per_stratum=report.gate.per_stratum,
        )
    report.scope_gate = run_masked_holdout_eval.compute_report_scope_gate(
        report.metrics, eval_config, skipped=skipped
    )
    policy_pins = run_masked_holdout_eval.build_disabled_policy_pins(
        policy, disabled_source, scorer_config, eval_config, lineage_policy
    )
    if policy_pins["pp3bp4_scored_calls"] != 0:
        raise ProspectiveInvalidStateError("PP3/BP4 scorer calls were not fully suppressed")
    report.config_pins.update(
        {
            "bias_tsv_sha256": _sha256(bias_tsv),
            "manifest_sha256": attestation.manifest_sha256,
            "mask_ledger_sha256": attestation.ledger_sha256,
            "remask_audit_sha256": attestation.remask_audit_sha256,
            "return_manifest_sha256": _sha256(return_manifest),
            "policy_eval_config_sha256": _sha256(BASE_EVAL),
            "prospective_eval_config_sha256": _sha256(
                run_root / "effective_eval_config.yaml"
            ),
            "mask_authorized_criteria": sorted(
                run_masked_holdout_eval._REBUILT_MASKED_CRITERIA
            ),
            "operational_skipped_criteria": sorted(operational_skips),
            "evaluation_skipped_criteria": sorted(skipped),
            "lineage_audit_hash": source.lineage_report.content_hash(),
            "production_vocab_manual_routed_counts": production_source.manual_routed_counts,
            "verified_return_artifact_count": len(verified_return),
            **policy_pins,
        }
    )
    envelope = {
        "report": run_masked_holdout_eval.report_to_dict(report),
        "content_hash": report.content_hash(),
        "predictor_policy": run_masked_holdout_eval.asdict(policy),
        "mask_attestation": run_masked_holdout_eval.asdict(attestation),
        "lineage_audit": {
            **source.lineage_report.to_dict(),
            "authorized_masked_criteria": sorted(
                run_masked_holdout_eval._REBUILT_MASKED_CRITERIA
            ),
            "effective_blocking_criteria": sorted(
                set(source.lineage_report.blocking_criteria)
                - run_masked_holdout_eval._REBUILT_MASKED_CRITERIA
            ),
        },
        "verified_return_artifacts": dict(sorted(verified_return.items())),
    }
    _freeze_text(run_root / "terminal_report.txt", report.render() + "\n")
    eval_json = run_root / "terminal_eval.json"
    _freeze_json(eval_json, envelope)
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    adjudication = adjudicate_prospective_outcomes(
        registration_id=REGISTRATION,
        registration_spec_path=SPEC,
        scoring_stage_approval_record=approval,
        allowed_repo_root=ROOT,
        first_scoring_execution_at=first,
        run_integrity="PASS",
        stage12_outcome=None,
        scopes=_scope_inputs(envelope, spec, eval_config),
        required_scopes=["missense:pathogenic", "missense:benign", "truncating:pathogenic"],
        narrow_scope="truncating:pathogenic",
    )
    evidence = {
        "schema": "raptor.eval.clinvar_prospective_stages.v1",
        "registration_id": REGISTRATION,
        "freeze": freeze,
        "benchmark": stats,
        "export": {
            "vcf_sha256": _sha256(holdout_vcf),
            "manifest_sha256": _sha256(holdout_manifest),
        },
        "masked_resources": {
            name: _sha256(path) for name, path in sorted(returned.items())
        },
        "return_manifest_sha256": _sha256(return_manifest),
        "terminal_eval": envelope,
        "adjudication": adjudication,
        "first_scoring_execution_at": first,
    }
    evidence_path = run_root / "prospective_evidence.json"
    _freeze_json(evidence_path, evidence)
    print(json.dumps({
        "evidence": str(evidence_path),
        "evidence_sha256": _sha256(evidence_path),
        "full_spectrum_terminal_outcome": adjudication["full_spectrum_terminal_outcome"],
        "narrow_scope_terminal_outcome": adjudication["narrow_scope"]["terminal_outcome"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
