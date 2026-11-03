from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.util
import json
import math
import re
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "raptor"
PACKAGE_ROOT = SRC_ROOT / "external" / "tsc2_functional"
OPERATOR_SCRIPT = REPO_ROOT / "scripts" / "normalize_tsc2_functional_bundle.py"
CONFIG_PATH = REPO_ROOT / "configs" / "external" / "tsc2_functional_identity_normalization_v1.yaml"

NORMALIZATION_SCHEMA = "raptor.external.normalized_functional_row.v1"
BUNDLE_SCHEMA = "raptor.external.tsc2_functional_identity_bundle.v1"
SUMMARY_SCHEMA = "raptor.external.tsc2_functional_identity_summary.v1"

INPUT_BUNDLE_ID = "tsc2-source-pilot-2026-09-09"
INPUT_BUNDLE_RUN_NAME = "tsc2-source-pilot-2026-09-09"
INPUT_MANIFEST_FILENAME = "bundle_manifest.json"
INPUT_MANIFEST_CONTENT_HASH = "63bd6eb4e7182b7f2d345cd78b3a110a59c361c72d521b88990c475919865808"

NORMALIZATION_RUN_NAME = "tsc2-functional-identity-normalization-pilot-2026-09-11"
NORMALIZATION_BUNDLE_ID = "tsc2-functional-identity-normalization-pilot-2026-09-11"

REFERENCE_ACCESSION = "NC_000016.10"
REFERENCE_ASSEMBLY = "GRCh38"
REFERENCE_FASTA_FILENAME = "NC_000016.10.fasta"
REFERENCE_FASTA_SHA256 = "22dc1bb93de407e0653791c36e4097fbaf64c9efa2510c83b7777f607a61e4d0"

MAVEDB_SCORES_SHA256 = "74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717"
VAMP_DOWNLOAD_MD5 = "1a397944b7a5158b3d63999dfcf926db"
VAMP_DOWNLOAD_BYTES = 439700
SGE_DOWNLOAD_MD5 = "c188e0a9dd4c67dfac13381d3879aedf"
SGE_DOWNLOAD_BYTES = 35101

SOURCE_TRANSCRIPT = "NM_000548.5"
SOURCE_GDNA_ACCESSION = "NC_000016.10"
SGE_SOURCE_TRANSCRIPT = "NM_000548_5"
SGE_SOURCE_GDNA_ACCESSION = "NC_000016_10"
VAMP_PROTEIN_ACCESSION = "ENSP00000219476.3"

REQUIRED_SOURCE_IDS = ["mavedb_clipe", "igvf_vamp_seq", "igvf_sge"]
EXPECTED_TOTAL_ROWS = 9914
EXPECTED_SOURCE_ROWS = {"mavedb_clipe": 208, "igvf_vamp_seq": 9253, "igvf_sge": 453}
EXPECTED_IDENTITY_STATE_COUNTS = {
    "GENOMIC_SPDI_VERIFIED": 423,
    "GENOMIC_REFERENCE_MISMATCH": 27,
    "TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 208,
    "PROTEIN_ONLY_CROSSWALK_REQUIRED": 9253,
    "REFERENCE_CONTROL": 3,
}
EXPECTED_VARIANT_KIND_COUNTS = {
    "MISSENSE": 9340,
    "SYNONYMOUS": 496,
    "STOP_GAINED": 63,
    "OTHER": 12,
    "REFERENCE_CONTROL": 3,
}
EXPECTED_UNRESOLVED_REASON_COUNTS = {
    "CDNA_PROJECTOR_REQUIRED": 208,
    "NUCLEOTIDE_CROSSWALK_REQUIRED": 9253,
    "REFERENCE_ALLELE_MISMATCH": 27,
    "NOT_A_VARIANT": 3,
}
EXPECTED_SGE_VARIANT_KIND_COUNTS = {
    "MISSENSE": 318,
    "SYNONYMOUS": 104,
    "STOP_GAINED": 16,
    "OTHER": 12,
    "REFERENCE_CONTROL": 3,
}

MAVEDB_HEADER = ["accession", "hgvs_nt", "hgvs_splice", "hgvs_pro", "score"]
VAMP_HEADER = ["variant", "score", "standard_error", "rep1", "rep2", "rep3", "functional_class"]
SGE_HEADER = [
    "sequence",
    "reference",
    "hgvs_nt",
    "hgvs_p",
    "hgvs_g",
    "presort__replicate_1",
    "pS6_Hi__replicate_1",
    "pS6_Lo__replicate_1",
    "pS6_log2_score__replicate_1",
    "presort__replicate_2",
    "pS6_Hi__replicate_2",
    "pS6_Lo__replicate_2",
    "pS6_log2_score__replicate_2",
    "presort__replicate_3",
    "pS6_Hi__replicate_3",
    "pS6_Lo__replicate_3",
    "pS6_log2_score__replicate_3",
    "presort__replicate_4",
    "pS6_Hi__replicate_4",
    "pS6_Lo__replicate_4",
    "pS6_log2_score__replicate_4",
    "pS6_score",
]

FORBIDDEN_IMPORT_PREFIXES = (
    "raptor.scorer",
    "raptor.eval",
    "raptor.packet",
    "raptor.census",
    "raptor.kb",
    "raptor.atlas",
    "raptor.rescuescreen",
)
FORBIDDEN_NETWORK_IMPORTS = ("urllib", "requests", "httpx", "aiohttp")
FORBIDDEN_CLINICAL_TOKENS = ("classification", "pathogenic", "benign", "ps3", "bs3")
FORBIDDEN_ROW_LEVEL_KEYS = ('"hgvs_c"', '"hgvs_p"', '"hgvs_g"', '"score_raw"', '"functional_class"')
SPDI_VALUE_PATTERN = re.compile(r"\bNC_000016\.10:\d+:[ACGT]+:[ACGT]+\b")


def _load_module(module_name: str):
    try:
        return import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"TSC2 functional normalization module {module_name!r} is not implemented: {exc}")


def _symbol(module: Any, symbol_name: str):
    if not hasattr(module, symbol_name):
        pytest.fail(
            f"TSC2 functional normalization module {module.__name__!r} is missing public "
            f"symbol {symbol_name!r}"
        )
    return getattr(module, symbol_name)


def _source_bundle_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.bundle")
    return {
        "build_bundle_manifest": _symbol(module, "build_bundle_manifest"),
    }


def _load_operator_module():
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 functional normalization operator script is not implemented: {OPERATOR_SCRIPT}")
    spec = importlib.util.spec_from_file_location("raptor_tsc2_functional_operator_test_module", OPERATOR_SCRIPT)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load operator module spec from {OPERATOR_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_functional.model")
    return {
        "NORMALIZED_FUNCTIONAL_ROW_SCHEMA": _symbol(module, "NORMALIZED_FUNCTIONAL_ROW_SCHEMA"),
        "REQUIRED_ROW_FIELDS": _symbol(module, "REQUIRED_ROW_FIELDS"),
        "ALLOWED_VARIANT_KINDS": _symbol(module, "ALLOWED_VARIANT_KINDS"),
        "ALLOWED_IDENTITY_STATES": _symbol(module, "ALLOWED_IDENTITY_STATES"),
        "ALLOWED_UNRESOLVED_REASONS": _symbol(module, "ALLOWED_UNRESOLVED_REASONS"),
        "NormalizedFunctionalRow": _symbol(module, "NormalizedFunctionalRow"),
        "NormalizationContractError": _symbol(module, "NormalizationContractError"),
        "ScoreValidationError": _symbol(module, "ScoreValidationError"),
        "NormalizationOutcomeError": _symbol(module, "NormalizationOutcomeError"),
    }


def _normalize_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_functional.normalize")
    return {
        "normalize_mavedb": _symbol(module, "normalize_mavedb"),
        "normalize_vamp_seq": _symbol(module, "normalize_vamp_seq"),
        "normalize_sge": _symbol(module, "normalize_sge"),
    }


def _ingest_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_functional.ingest")
    return {
        "InputPinMismatchError": _symbol(module, "InputPinMismatchError"),
        "ReferenceIntegrityError": _symbol(module, "ReferenceIntegrityError"),
        "FunctionalNormalizationError": _symbol(module, "FunctionalNormalizationError"),
        "validate_frozen_source_bundle": _symbol(module, "validate_frozen_source_bundle"),
        "validate_reference_fasta_checksum": _symbol(module, "validate_reference_fasta_checksum"),
        "normalize_functional_bundle": _symbol(module, "normalize_functional_bundle"),
    }


def _bundle_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_functional.bundle")
    return {
        "FunctionalBundleBoundaryError": _symbol(module, "FunctionalBundleBoundaryError"),
        "NormalizationManifestError": _symbol(module, "NormalizationManifestError"),
        "build_normalization_manifest": _symbol(module, "build_normalization_manifest"),
        "compute_manifest_content_hash": _symbol(module, "compute_manifest_content_hash"),
        "validate_manifest_content_hash": _symbol(module, "validate_manifest_content_hash"),
        "canonical_jsonl_bytes": _symbol(module, "canonical_jsonl_bytes"),
        "publish_normalized_bundle": _symbol(module, "publish_normalized_bundle"),
        "build_committed_summary": _symbol(module, "build_committed_summary"),
        "_publish_directory_no_replace": _symbol(module, "_publish_directory_no_replace"),
    }


def _ingest_model_api() -> dict[str, Any]:
    module = _load_module("raptor.ingest.model")
    return {
        "RawVariant": _symbol(module, "RawVariant"),
        "NormalizedVariant": _symbol(module, "NormalizedVariant"),
        "ManualQueueItem": _symbol(module, "ManualQueueItem"),
        "VariantClass": _symbol(module, "VariantClass"),
    }


def _md5_bytes(blob: bytes) -> str:
    return hashlib.md5(blob).hexdigest()  # nosec B303 - compatibility with published MD5 fingerprints


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _csv_payload(header: list[str], rows: list[list[str]]) -> str:
    lines = [",".join(header)]
    lines.extend(",".join(str(cell) for cell in row) for row in rows)
    return "\n".join(lines) + "\n"


def _gzip_tsv_payload(header: list[str], rows: list[list[str]], *, line_ending: str = "\n") -> bytes:
    text = line_ending.join(["\t".join(header), *["\t".join(str(cell) for cell in row) for row in rows]]) + line_ending
    return gzip.compress(text.encode("utf-8"))


def _sge_row(
    *,
    hgvs_nt: str,
    hgvs_p: str,
    hgvs_g: str,
    score: str,
    sequence: str = "ATGAAACGCTCTTACAGGCTGCCACGTTAG",
    reference: str = "ATGAAACGCTCTTACAGGCTGCCACGTTAG",
) -> list[str]:
    return [
        sequence,
        reference,
        hgvs_nt,
        hgvs_p,
        hgvs_g,
        "100",
        "10",
        "5",
        "1.0",
        "101",
        "11",
        "6",
        "1.1",
        "102",
        "12",
        "7",
        "1.2",
        "103",
        "13",
        "8",
        "1.3",
        score,
    ]


def _source_artifact_record(*, artifact_id: str, source_id: str, relative_path: str, payload: bytes) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "source_id": source_id,
        "role": "TEST_ARTIFACT",
        "requested_url": f"https://example.invalid/{artifact_id}",
        "final_url": f"https://example.invalid/{artifact_id}",
        "http_status": 200,
        "media_type": "application/octet-stream",
        "relative_path": relative_path,
        "byte_length": len(payload),
        "sha256": _sha256_bytes(payload),
        "md5": _md5_bytes(payload),
        "fetched_at": "2026-09-11T00:00:00Z",
        "verification": "HASHED",
    }


def _source_record(*, source_id: str, source_kind: str, artifact_ids: list[str]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "lifecycle_state": "STAGED_VERIFIED",
        "access_state": "PUBLIC",
        "licence_state": "PUBLIC_METADATA",
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "identifiers": {"primary": source_id},
        "artifact_ids": artifact_ids,
        "observations": {"fixture": True},
        "limitations": [],
    }


def _build_synthetic_source_bundle_fixture() -> dict[str, Any]:
    source_bundle_api = _source_bundle_api()

    mavedb_payload = _csv_payload(
        MAVEDB_HEADER,
        [
            ["m1", "c.100A>G", "", "p.Lys34Arg", "0.200"],
            ["m2", "c.120A>T", "", "p.Lys40Ter", "-0.600"],
        ],
    ).encode("utf-8")
    vamp_payload = _gzip_tsv_payload(
        VAMP_HEADER,
        [
            ["ENSP00000219476.3:p.Arg174Cys", "0.620", "0.030", "0.600", "0.630", "0.630", "damaging"],
            ["ENSP00000219476.3:p.Lys40=", "0.050", "0.020", "0.060", "0.050", "0.040", "wt-like"],
        ],
    )
    sge_payload = _gzip_tsv_payload(
        SGE_HEADER,
        [
            _sge_row(hgvs_nt="NM_000548_5:c.=", hgvs_p="p.=", hgvs_g="NC_000016_10:g.=", score="0.0"),
            _sge_row(
                hgvs_nt="NM_000548_5:c.100A>G",
                hgvs_p="p.Lys34Arg",
                hgvs_g="NC_000016_10:g.2044829C>T",
                score="0.7",
            ),
        ],
    )

    payloads_by_artifact_id = {
        "mavedb_clipe-scores-csv": mavedb_payload,
        "igvf_vamp_seq-download-tsv-gz": vamp_payload,
        "igvf_sge-download-tsv-gz": sge_payload,
    }

    artifacts = [
        _source_artifact_record(
            artifact_id="mavedb_clipe-scores-csv",
            source_id="mavedb_clipe",
            relative_path="mavedb/mavedb_clipe-scores.csv",
            payload=mavedb_payload,
        ),
        _source_artifact_record(
            artifact_id="igvf_vamp_seq-download-tsv-gz",
            source_id="igvf_vamp_seq",
            relative_path="igvf/igvf_vamp_seq-IGVFFI9747KART.tsv.gz",
            payload=vamp_payload,
        ),
        _source_artifact_record(
            artifact_id="igvf_sge-download-tsv-gz",
            source_id="igvf_sge",
            relative_path="igvf/igvf_sge-IGVFFI3097DFGF.tsv.gz",
            payload=sge_payload,
        ),
    ]
    sources = [
        _source_record(
            source_id="mavedb_clipe",
            source_kind="mavedb",
            artifact_ids=["mavedb_clipe-scores-csv"],
        ),
        _source_record(
            source_id="igvf_vamp_seq",
            source_kind="igvf",
            artifact_ids=["igvf_vamp_seq-download-tsv-gz"],
        ),
        _source_record(
            source_id="igvf_sge",
            source_kind="igvf",
            artifact_ids=["igvf_sge-download-tsv-gz"],
        ),
    ]

    manifest = source_bundle_api["build_bundle_manifest"](
        bundle_id="synthetic-source-bundle",
        created_at="2026-09-11T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=artifacts,
        sources=sources,
        truncation={},
        boundaries={"network": "injected", "external_output_only": True},
    )
    expected_artifact_pins = [
        {
            "artifact_id": artifact["artifact_id"],
            "source_id": artifact["source_id"],
            "relative_path": artifact["relative_path"],
            "sha256": artifact["sha256"],
            "md5": artifact["md5"],
            "byte_length": artifact["byte_length"],
        }
        for artifact in artifacts
    ]
    return {
        "source_manifest": manifest,
        "artifact_payloads": payloads_by_artifact_id,
        "expected_bundle_id": manifest["bundle_id"],
        "expected_manifest_content_hash": manifest["content_hash"],
        "expected_artifacts": expected_artifact_pins,
    }


def _build_synthetic_source_bundle_fixture_with_preceding_decoys() -> dict[str, Any]:
    source_bundle_api = _source_bundle_api()

    mavedb_metadata_payload = b'{"urn":"urn:mavedb:00001201-a-1"}'
    mavedb_scores_payload = _csv_payload(
        MAVEDB_HEADER,
        [
            ["m1", "c.100A>G", "", "p.Lys34Arg", "0.200"],
            ["m2", "c.120A>T", "", "p.Lys40Ter", "-0.600"],
        ],
    ).encode("utf-8")
    vamp_analysis_payload = b'{"analysis_set":"IGVFDS5595BTYJ"}'
    vamp_file_payload = b'{"file_accession":"IGVFFI9747KART"}'
    vamp_download_payload = _gzip_tsv_payload(
        VAMP_HEADER,
        [
            ["ENSP00000219476.3:p.Arg174Cys", "0.620", "0.030", "0.600", "0.630", "0.630", "damaging"],
            ["ENSP00000219476.3:p.Lys40=", "0.050", "0.020", "0.060", "0.050", "0.040", "wt-like"],
        ],
    )
    sge_analysis_payload = b'{"analysis_set":"IGVFDS1782FCXW"}'
    sge_file_payload = b'{"file_accession":"IGVFFI3097DFGF"}'
    sge_download_payload = _gzip_tsv_payload(
        SGE_HEADER,
        [
            _sge_row(hgvs_nt="NM_000548_5:c.=", hgvs_p="p.=", hgvs_g="NC_000016_10:g.=", score="0.0"),
            _sge_row(
                hgvs_nt="NM_000548_5:c.100A>G",
                hgvs_p="p.Lys34Arg",
                hgvs_g="NC_000016_10:g.2044829C>T",
                score="0.7",
            ),
        ],
    )

    artifacts = [
        _source_artifact_record(
            artifact_id="mavedb_clipe-metadata-json",
            source_id="mavedb_clipe",
            relative_path="mavedb/mavedb_clipe-metadata.json",
            payload=mavedb_metadata_payload,
        ),
        _source_artifact_record(
            artifact_id="mavedb_clipe-scores-csv",
            source_id="mavedb_clipe",
            relative_path="mavedb/mavedb_clipe-scores.csv",
            payload=mavedb_scores_payload,
        ),
        _source_artifact_record(
            artifact_id="igvf_vamp_seq-analysis-json",
            source_id="igvf_vamp_seq",
            relative_path="igvf/igvf_vamp_seq-analysis.json",
            payload=vamp_analysis_payload,
        ),
        _source_artifact_record(
            artifact_id="igvf_vamp_seq-file-json",
            source_id="igvf_vamp_seq",
            relative_path="igvf/igvf_vamp_seq-file.json",
            payload=vamp_file_payload,
        ),
        _source_artifact_record(
            artifact_id="igvf_vamp_seq-download-tsv-gz",
            source_id="igvf_vamp_seq",
            relative_path="igvf/igvf_vamp_seq-IGVFFI9747KART.tsv.gz",
            payload=vamp_download_payload,
        ),
        _source_artifact_record(
            artifact_id="igvf_sge-analysis-json",
            source_id="igvf_sge",
            relative_path="igvf/igvf_sge-analysis.json",
            payload=sge_analysis_payload,
        ),
        _source_artifact_record(
            artifact_id="igvf_sge-file-json",
            source_id="igvf_sge",
            relative_path="igvf/igvf_sge-file.json",
            payload=sge_file_payload,
        ),
        _source_artifact_record(
            artifact_id="igvf_sge-download-tsv-gz",
            source_id="igvf_sge",
            relative_path="igvf/igvf_sge-IGVFFI3097DFGF.tsv.gz",
            payload=sge_download_payload,
        ),
    ]
    sources = [
        _source_record(
            source_id="mavedb_clipe",
            source_kind="mavedb",
            artifact_ids=["mavedb_clipe-metadata-json", "mavedb_clipe-scores-csv"],
        ),
        _source_record(
            source_id="igvf_vamp_seq",
            source_kind="igvf",
            artifact_ids=[
                "igvf_vamp_seq-analysis-json",
                "igvf_vamp_seq-file-json",
                "igvf_vamp_seq-download-tsv-gz",
            ],
        ),
        _source_record(
            source_id="igvf_sge",
            source_kind="igvf",
            artifact_ids=[
                "igvf_sge-analysis-json",
                "igvf_sge-file-json",
                "igvf_sge-download-tsv-gz",
            ],
        ),
    ]
    manifest = source_bundle_api["build_bundle_manifest"](
        bundle_id="synthetic-source-bundle-with-decoys",
        created_at="2026-09-11T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=artifacts,
        sources=sources,
        truncation={},
        boundaries={"network": "injected", "external_output_only": True},
    )

    required_artifact_ids = {
        "mavedb_clipe-scores-csv",
        "igvf_vamp_seq-download-tsv-gz",
        "igvf_sge-download-tsv-gz",
    }
    required_artifact_pins = [
        {
            "artifact_id": artifact["artifact_id"],
            "source_id": artifact["source_id"],
            "relative_path": artifact["relative_path"],
            "sha256": artifact["sha256"],
            "md5": artifact["md5"],
            "byte_length": artifact["byte_length"],
        }
        for artifact in artifacts
        if artifact["artifact_id"] in required_artifact_ids
    ]
    pinned_payloads = {
        artifact["artifact_id"]: payload
        for artifact, payload in zip(
            artifacts,
            [
                mavedb_metadata_payload,
                mavedb_scores_payload,
                vamp_analysis_payload,
                vamp_file_payload,
                vamp_download_payload,
                sge_analysis_payload,
                sge_file_payload,
                sge_download_payload,
            ],
            strict=True,
        )
        if artifact["artifact_id"] in required_artifact_ids
    }

    return {
        "source_manifest": manifest,
        "artifact_payloads": pinned_payloads,
        "expected_bundle_id": manifest["bundle_id"],
        "expected_manifest_content_hash": manifest["content_hash"],
        "expected_artifacts": required_artifact_pins,
    }


def _minimal_normalized_row(*, source_id: str, source_row: int) -> dict[str, Any]:
    return {
        "schema": NORMALIZATION_SCHEMA,
        "source_id": source_id,
        "source_row": source_row,
        "source_record_id": f"{source_id}:{source_row}",
        "gene": "TSC2",
        "assembly": REFERENCE_ASSEMBLY if source_id == "igvf_sge" else None,
        "transcript": SOURCE_TRANSCRIPT if source_id in {"mavedb_clipe", "igvf_sge"} else None,
        "protein_accession": VAMP_PROTEIN_ACCESSION if source_id == "igvf_vamp_seq" else None,
        "hgvs_c": "NM_000548.5:c.100A>G" if source_id != "igvf_vamp_seq" else None,
        "hgvs_p": "p.Lys34Arg",
        "hgvs_g": "NC_000016.10:g.2044829C>T" if source_id == "igvf_sge" else None,
        "spdi": None if source_id != "igvf_sge" else "NC_000016.10:2044828:C:T",
        "variant_kind": "MISSENSE",
        "identity_state": (
            "TRANSCRIPT_ONLY_PROJECTOR_REQUIRED"
            if source_id == "mavedb_clipe"
            else "PROTEIN_ONLY_CROSSWALK_REQUIRED"
            if source_id == "igvf_vamp_seq"
            else "GENOMIC_SPDI_VERIFIED"
        ),
        "unresolved_reason": (
            "CDNA_PROJECTOR_REQUIRED"
            if source_id == "mavedb_clipe"
            else "NUCLEOTIDE_CROSSWALK_REQUIRED"
            if source_id == "igvf_vamp_seq"
            else None
        ),
        "score_name": "score",
        "score_raw": "0.125",
    }


def _assert_exact_row_schema(row: dict[str, Any], model_api: dict[str, Any]) -> None:
    required = set(model_api["REQUIRED_ROW_FIELDS"])
    assert set(row) == required
    assert row["schema"] == model_api["NORMALIZED_FUNCTIONAL_ROW_SCHEMA"]
    assert row["variant_kind"] in set(model_api["ALLOWED_VARIANT_KINDS"])
    assert row["identity_state"] in set(model_api["ALLOWED_IDENTITY_STATES"])
    assert row["unresolved_reason"] in set(model_api["ALLOWED_UNRESOLVED_REASONS"])
    assert isinstance(row["source_row"], int) and row["source_row"] >= 1
    assert isinstance(row["source_record_id"], str) and row["source_record_id"]
    value = float(row["score_raw"])
    assert math.isfinite(value)


def _module_imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.module, node.lineno))
    return imports


def _flip_first_byte(blob: bytes) -> bytes:
    if not blob:
        return blob
    return bytes([blob[0] ^ 0x01]) + blob[1:]


def _mk_normalized_variant(model_api: dict[str, Any], raw: Any, *, variant_id: str) -> Any:
    return model_api["NormalizedVariant"](
        variant_id=variant_id,
        hgvs_g=f"{raw.chromosome}:g.{raw.position}{raw.ref}>{raw.alt}",
        hgvs_c=None,
        hgvs_p=None,
        hgvs_c_null_reason="awaiting_uta_projection",
        hgvs_p_null_reason="awaiting_uta_projection",
        variant_class=model_api["VariantClass"].SNV,
        gene=raw.gene,
        variation_id=raw.variation_id,
        snapshot_id=raw.snapshot_id,
        snapshot_date=raw.snapshot_date,
        source_file_checksum=raw.source_file_checksum,
        row_locator=raw.row_locator,
        raw_source_value=raw.raw_source_value,
    )


def _mk_manual_queue_item(model_api: dict[str, Any], raw: Any, *, error_code: str) -> Any:
    return model_api["ManualQueueItem"](
        raw_input=raw.raw_source_value,
        source_ref=raw.row_locator,
        failure_stage="normalize",
        error_code=error_code,
        reason=f"simulated-{error_code.lower()}",
        attempted_coords=f"{raw.chromosome}:{raw.position}",
        tool_error=None,
        config_pins={"gene": raw.gene},
        run_id="fn-test",
    )


def _tiny_plan(*, manifest: dict[str, Any], reference_sha256: str) -> dict[str, Any]:
    required_by_source = {
        item["source_id"]: item
        for item in manifest["artifacts"]
        if item["artifact_id"]
        in {"mavedb_clipe-scores-csv", "igvf_vamp_seq-download-tsv-gz", "igvf_sge-download-tsv-gz"}
    }
    return {
        "bundle_id": NORMALIZATION_BUNDLE_ID,
        "created_at": "2026-09-11T00:00:00Z",
        "reference": {
            "accession": REFERENCE_ACCESSION,
            "assembly": REFERENCE_ASSEMBLY,
            "sha256": reference_sha256,
        },
        "expected_source_rows": {"mavedb_clipe": 2, "igvf_vamp_seq": 2, "igvf_sge": 2},
        "identity_pins": {
            "gene": "TSC2",
            "transcript": SOURCE_TRANSCRIPT,
            "genomic_accession": SOURCE_GDNA_ACCESSION,
            "sge_source_transcript": SGE_SOURCE_TRANSCRIPT,
            "sge_source_genomic_accession": SGE_SOURCE_GDNA_ACCESSION,
            "vamp_source_protein": VAMP_PROTEIN_ACCESSION,
        },
        "header_pins": {
            "mavedb_clipe": list(MAVEDB_HEADER),
            "igvf_vamp_seq": list(VAMP_HEADER),
            "igvf_sge": list(SGE_HEADER),
        },
        "input_bundle": {
            "bundle_id": manifest["bundle_id"],
            "manifest_content_hash": manifest["content_hash"],
            "artifacts": [
                {
                    "artifact_id": required_by_source["mavedb_clipe"]["artifact_id"],
                    "source_id": "mavedb_clipe",
                    "relative_path": required_by_source["mavedb_clipe"]["relative_path"],
                    "sha256": required_by_source["mavedb_clipe"]["sha256"],
                    "md5": required_by_source["mavedb_clipe"]["md5"],
                    "byte_length": required_by_source["mavedb_clipe"]["byte_length"],
                },
                {
                    "artifact_id": required_by_source["igvf_vamp_seq"]["artifact_id"],
                    "source_id": "igvf_vamp_seq",
                    "relative_path": required_by_source["igvf_vamp_seq"]["relative_path"],
                    "sha256": required_by_source["igvf_vamp_seq"]["sha256"],
                    "md5": required_by_source["igvf_vamp_seq"]["md5"],
                    "byte_length": required_by_source["igvf_vamp_seq"]["byte_length"],
                },
                {
                    "artifact_id": required_by_source["igvf_sge"]["artifact_id"],
                    "source_id": "igvf_sge",
                    "relative_path": required_by_source["igvf_sge"]["relative_path"],
                    "sha256": required_by_source["igvf_sge"]["sha256"],
                    "md5": required_by_source["igvf_sge"]["md5"],
                    "byte_length": required_by_source["igvf_sge"]["byte_length"],
                },
            ],
        },
    }


def _expected_pilot_contract() -> dict[str, Any]:
    return {
        "total_rows": EXPECTED_TOTAL_ROWS,
        "source_rows": dict(EXPECTED_SOURCE_ROWS),
        "identity_state_counts": dict(EXPECTED_IDENTITY_STATE_COUNTS),
        "variant_kind_counts": dict(EXPECTED_VARIANT_KIND_COUNTS),
    }


def _manifest_for_expected_pilot_gate() -> dict[str, Any]:
    return {
        "counts": {"sources": 3, "artifacts": 3, "rows": EXPECTED_TOTAL_ROWS},
        "artifacts": [
            {"artifact_id": "mavedb_clipe-normalized-jsonl", "source_id": "mavedb_clipe", "row_count": 208},
            {"artifact_id": "igvf_vamp_seq-normalized-jsonl", "source_id": "igvf_vamp_seq", "row_count": 9253},
            {"artifact_id": "igvf_sge-normalized-jsonl", "source_id": "igvf_sge", "row_count": 453},
        ],
        "identity_state_counts": dict(EXPECTED_IDENTITY_STATE_COUNTS),
        "variant_kind_counts": dict(EXPECTED_VARIANT_KIND_COUNTS),
    }


def test_fn01_source_bundle_and_artifact_pins_fail_closed_on_any_drift() -> None:
    ingest_api = _ingest_api()
    fixture = _build_synthetic_source_bundle_fixture()

    ingest_api["validate_frozen_source_bundle"](
        source_manifest=fixture["source_manifest"],
        artifact_payloads=fixture["artifact_payloads"],
        expected_bundle_id=fixture["expected_bundle_id"],
        expected_manifest_content_hash=fixture["expected_manifest_content_hash"],
        expected_artifacts=fixture["expected_artifacts"],
    )

    drifted_manifest = deepcopy(fixture["source_manifest"])
    drifted_manifest["content_hash"] = "0" * 64
    with pytest.raises(ingest_api["InputPinMismatchError"]):
        ingest_api["validate_frozen_source_bundle"](
            source_manifest=drifted_manifest,
            artifact_payloads=fixture["artifact_payloads"],
            expected_bundle_id=fixture["expected_bundle_id"],
            expected_manifest_content_hash=fixture["expected_manifest_content_hash"],
            expected_artifacts=fixture["expected_artifacts"],
        )

    drifted_payloads = deepcopy(fixture["artifact_payloads"])
    drifted_payloads["igvf_vamp_seq-download-tsv-gz"] = _flip_first_byte(
        drifted_payloads["igvf_vamp_seq-download-tsv-gz"]
    )
    with pytest.raises(ingest_api["InputPinMismatchError"]):
        ingest_api["validate_frozen_source_bundle"](
            source_manifest=fixture["source_manifest"],
            artifact_payloads=drifted_payloads,
            expected_bundle_id=fixture["expected_bundle_id"],
            expected_manifest_content_hash=fixture["expected_manifest_content_hash"],
            expected_artifacts=fixture["expected_artifacts"],
        )

    for key, mutated in (
        ("sha256", "f" * 64),
        ("md5", "e" * 32),
        ("byte_length", fixture["expected_artifacts"][0]["byte_length"] + 1),
    ):
        drifted_expected_artifacts = deepcopy(fixture["expected_artifacts"])
        drifted_expected_artifacts[0][key] = mutated
        with pytest.raises(ingest_api["InputPinMismatchError"]):
            ingest_api["validate_frozen_source_bundle"](
                source_manifest=fixture["source_manifest"],
                artifact_payloads=fixture["artifact_payloads"],
                expected_bundle_id=fixture["expected_bundle_id"],
                expected_manifest_content_hash=fixture["expected_manifest_content_hash"],
                expected_artifacts=drifted_expected_artifacts,
            )


def test_fn02_operator_and_package_modules_remain_offline_and_boundary_safe() -> None:
    missing_targets: list[Path] = []
    targets: list[Path] = []

    if not PACKAGE_ROOT.is_dir():
        missing_targets.append(PACKAGE_ROOT)
    else:
        targets.extend(sorted(path for path in PACKAGE_ROOT.rglob("*.py") if path.is_file()))

    if not OPERATOR_SCRIPT.is_file():
        missing_targets.append(OPERATOR_SCRIPT)
    else:
        targets.append(OPERATOR_SCRIPT)

    if missing_targets:
        formatted = ", ".join(str(path) for path in missing_targets)
        pytest.fail(f"TSC2 functional normalization implementation targets are missing: {formatted}")

    offenders: list[str] = []
    for path in targets:
        for imported, lineno in _module_imports(path):
            lowered = imported.lower()
            if any(lowered == blocked or lowered.startswith(blocked + ".") for blocked in FORBIDDEN_NETWORK_IMPORTS):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
            if any(imported == blocked or imported.startswith(blocked + ".") for blocked in FORBIDDEN_IMPORT_PREFIXES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")

    assert not offenders, "functional normalization slice must stay offline and segregated:\n" + "\n".join(
        offenders
    )


def test_fn02b_operator_main_without_source_root_arg_or_env_fails_before_cwd_probe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator_module()
    monkeypatch.delenv(operator.DEFAULT_SOURCE_ROOT_ENV, raising=False)
    monkeypatch.delenv(operator.DEFAULT_REFERENCE_ROOT_ENV, raising=False)
    monkeypatch.delenv(operator.DEFAULT_OUTPUT_ROOT_ENV, raising=False)

    exit_code = operator.main(["--config", str(CONFIG_PATH)])
    captured = capsys.readouterr()
    stderr = captured.err

    assert exit_code == 1
    assert "--source-root" in stderr or operator.DEFAULT_SOURCE_ROOT_ENV in stderr
    assert "source bundle manifest not found" not in stderr.lower()


def test_fn02c_read_artifact_payloads_uses_config_pinned_relative_path_not_manifest_override(
    tmp_path: Path,
) -> None:
    operator = _load_operator_module()
    source_root = tmp_path / "source-root"
    run_dir = source_root / "run-001"
    pinned_relpath = "mavedb/mavedb_clipe-scores.csv"
    pinned_path = run_dir / pinned_relpath
    pinned_path.parent.mkdir(parents=True, exist_ok=True)
    safe_bytes = b"SAFE_PINNED_BYTES"
    pinned_path.write_bytes(safe_bytes)

    escaped_path = source_root / "escaped.csv"
    escaped_bytes = b"ESCAPED_BYTES"
    escaped_path.write_bytes(escaped_bytes)

    config = {
        "inputs": {
            "source_bundle": {
                "run_name": "run-001",
                "required_artifacts": {
                    "mavedb_clipe": {
                        "artifact_id": "mavedb_clipe-scores-csv",
                        "relative_path": pinned_relpath,
                    }
                },
            }
        }
    }
    source_manifest = {
        "artifacts": [
            {
                "artifact_id": "mavedb_clipe-scores-csv",
                "source_id": "mavedb_clipe",
                "relative_path": "../escaped.csv",
            }
        ]
    }

    payloads = operator._read_artifact_payloads(source_root, config, source_manifest)
    assert payloads["mavedb_clipe-scores-csv"] == safe_bytes
    assert payloads["mavedb_clipe-scores-csv"] != escaped_bytes


@pytest.mark.parametrize(
    ("pinned_relpath", "manifest_relpath", "make_symlink"),
    [
        ("../escaped.csv", "../escaped.csv", False),
        ("mavedb/mavedb_clipe-scores.csv", "mavedb/mavedb_clipe-scores.csv", True),
    ],
    ids=["path-escapes-run-dir", "symlinked-pinned-artifact-path"],
)
def test_fn02d_read_artifact_payloads_rejects_escaped_or_symlinked_pinned_path(
    tmp_path: Path,
    pinned_relpath: str,
    manifest_relpath: str,
    make_symlink: bool,
) -> None:
    operator = _load_operator_module()
    source_root = tmp_path / "source-root"
    run_dir = source_root / "run-001"
    run_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "inputs": {
            "source_bundle": {
                "run_name": "run-001",
                "required_artifacts": {
                    "mavedb_clipe": {
                        "artifact_id": "mavedb_clipe-scores-csv",
                        "relative_path": pinned_relpath,
                    }
                },
            }
        }
    }
    source_manifest = {
        "artifacts": [
            {
                "artifact_id": "mavedb_clipe-scores-csv",
                "source_id": "mavedb_clipe",
                "relative_path": manifest_relpath,
            }
        ]
    }

    if make_symlink:
        outside = source_root / "outside.csv"
        outside.write_bytes(b"outside")
        pinned_path = run_dir / pinned_relpath
        pinned_path.parent.mkdir(parents=True, exist_ok=True)
        pinned_path.symlink_to(outside)
    else:
        (source_root / "escaped.csv").write_bytes(b"escaped")

    with pytest.raises(operator.Tsc2FunctionalOperatorError):
        operator._read_artifact_payloads(source_root, config, source_manifest)


def test_fn02e_validate_expected_pilot_counts_checks_all_axes_and_derives_source_rows_from_artifacts() -> None:
    operator = _load_operator_module()
    if not hasattr(operator, "_validate_expected_pilot_counts"):
        pytest.fail(
            "TSC2 functional normalization operator is missing helper "
            "'_validate_expected_pilot_counts'"
        )
    validate = operator._validate_expected_pilot_counts

    expected_pilot = _expected_pilot_contract()
    manifest = _manifest_for_expected_pilot_gate()
    manifest["source_rows"] = {"mavedb_clipe": 1, "igvf_vamp_seq": 1, "igvf_sge": 1}
    manifest["source_row_counts"] = {"mavedb_clipe": 2, "igvf_vamp_seq": 2, "igvf_sge": 2}

    validate(manifest, expected_pilot)

    drifted_total = deepcopy(manifest)
    drifted_total["counts"]["rows"] += 1
    with pytest.raises(operator.Tsc2FunctionalOperatorError, match="total_rows"):
        validate(drifted_total, expected_pilot)

    drifted_source_rows = deepcopy(manifest)
    drifted_source_rows["artifacts"][0]["row_count"] += 1
    with pytest.raises(operator.Tsc2FunctionalOperatorError, match="source_rows"):
        validate(drifted_source_rows, expected_pilot)

    drifted_identity = deepcopy(manifest)
    drifted_identity["identity_state_counts"]["GENOMIC_SPDI_VERIFIED"] -= 1
    drifted_identity["identity_state_counts"]["TRANSCRIPT_ONLY_PROJECTOR_REQUIRED"] += 1
    with pytest.raises(operator.Tsc2FunctionalOperatorError, match="identity_state_counts"):
        validate(drifted_identity, expected_pilot)

    drifted_variant_kinds = deepcopy(manifest)
    drifted_variant_kinds["variant_kind_counts"]["MISSENSE"] -= 1
    drifted_variant_kinds["variant_kind_counts"]["OTHER"] += 1
    with pytest.raises(operator.Tsc2FunctionalOperatorError, match="variant_kind_counts"):
        validate(drifted_variant_kinds, expected_pilot)


def test_fn02f_operator_main_calls_expected_pilot_validator_before_publication() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 functional normalization operator script is not implemented: {OPERATOR_SCRIPT}")

    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    main_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        ),
        None,
    )
    if main_node is None:
        pytest.fail("operator script is missing main(argv=...)")

    calls: list[tuple[str, int]] = []
    for node in ast.walk(main_node):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.append((node.func.id, node.lineno))
        elif isinstance(node.func, ast.Attribute):
            calls.append((node.func.attr, node.lineno))

    validator_lines = [line for name, line in calls if name == "_validate_expected_pilot_counts"]
    publish_lines = [line for name, line in calls if name == "publish_normalized_bundle"]
    assert validator_lines, "main must call _validate_expected_pilot_counts before publication"
    assert publish_lines, "main must publish with publish_normalized_bundle"
    assert min(validator_lines) < min(publish_lines)


def test_fn03_reference_checksum_mismatch_fails_before_normalizer_call(tmp_path: Path) -> None:
    ingest_api = _ingest_api()
    fixture = _build_synthetic_source_bundle_fixture()
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_path.write_text(">NC_000016.10\nACGTACGT\n", encoding="utf-8")

    class StubNormalizer:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, Any]] = []

        def normalize(self, raw: Any, config: object) -> Any:
            self.calls.append((raw, config))
            return raw

    normalizer = StubNormalizer()
    plan = {
        "bundle_id": NORMALIZATION_BUNDLE_ID,
        "created_at": "2026-09-11T00:00:00Z",
        "expected_source_rows": {"mavedb_clipe": 2, "igvf_vamp_seq": 2, "igvf_sge": 2},
        "reference": {
            "accession": REFERENCE_ACCESSION,
            "assembly": REFERENCE_ASSEMBLY,
            "sha256": "0" * 64,
        },
        "identity_pins": {
            "gene": "TSC2",
            "transcript": SOURCE_TRANSCRIPT,
            "genomic_accession": SOURCE_GDNA_ACCESSION,
            "sge_source_transcript": SGE_SOURCE_TRANSCRIPT,
            "sge_source_genomic_accession": SGE_SOURCE_GDNA_ACCESSION,
            "vamp_source_protein": VAMP_PROTEIN_ACCESSION,
        },
    }

    with pytest.raises(ingest_api["ReferenceIntegrityError"]):
        ingest_api["normalize_functional_bundle"](
            plan=plan,
            source_manifest=fixture["source_manifest"],
            artifact_payloads=fixture["artifact_payloads"],
            reference_fasta_path=reference_path,
            normalizer=normalizer,
            normalizer_config={"run_id": "fn03"},
        )

    assert normalizer.calls == []


def test_fn03b_normalize_functional_bundle_uses_plan_pinned_artifact_ids_not_first_artifact_by_source(
    tmp_path: Path,
) -> None:
    ingest_api = _ingest_api()
    ingest_model_api = _ingest_model_api()
    fixture = _build_synthetic_source_bundle_fixture_with_preceding_decoys()
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)
    plan = _tiny_plan(
        manifest=fixture["source_manifest"],
        reference_sha256=_sha256_bytes(reference_bytes),
    )

    class StubNormalizer:
        def normalize(self, raw: Any, _config: object) -> Any:
            return _mk_normalized_variant(
                ingest_model_api,
                raw,
                variant_id=f"{raw.chromosome}:{int(raw.position) - 1}:{raw.ref}:{raw.alt}",
            )

    result = ingest_api["normalize_functional_bundle"](
        plan=plan,
        source_manifest=fixture["source_manifest"],
        artifact_payloads=fixture["artifact_payloads"],
        reference_fasta_path=reference_path,
        normalizer=StubNormalizer(),
        normalizer_config={"run_id": "fn03b"},
    )

    rows_by_source = result["rows_by_source"]
    assert set(rows_by_source) == {"mavedb_clipe", "igvf_vamp_seq", "igvf_sge"}
    assert len(rows_by_source["mavedb_clipe"]) == 2
    assert len(rows_by_source["igvf_vamp_seq"]) == 2
    assert len(rows_by_source["igvf_sge"]) == 2


def test_fn04_exact_row_schema_allowed_states_and_one_based_source_row_conservation() -> None:
    model_api = _model_api()
    normalize_api = _normalize_api()

    mavedb_rows = normalize_api["normalize_mavedb"](
        source_id="mavedb_clipe",
        csv_text=_csv_payload(
            MAVEDB_HEADER,
            [
                ["m1", "c.100A>G", "", "p.Lys34Arg", "0.21"],
                ["m2", "c.120A>T", "", "p.Lys40Ter", "-0.10"],
            ],
        ),
        expected_header=MAVEDB_HEADER,
        expected_rows=2,
        transcript=SOURCE_TRANSCRIPT,
    )
    vamp_rows = normalize_api["normalize_vamp_seq"](
        source_id="igvf_vamp_seq",
        tsv_gz_bytes=_gzip_tsv_payload(
            VAMP_HEADER,
            [
                ["ENSP00000219476.3:p.Arg174Cys", "0.62", "0.03", "0.60", "0.63", "0.63", "damaging"],
                ["ENSP00000219476.3:p.Lys40=", "0.05", "0.02", "0.06", "0.05", "0.04", "wt-like"],
            ],
        ),
        expected_header=VAMP_HEADER,
        expected_rows=2,
        required_protein_accession=VAMP_PROTEIN_ACCESSION,
    )
    all_rows = mavedb_rows + vamp_rows

    assert [row["source_row"] for row in mavedb_rows] == [1, 2]
    assert [row["source_row"] for row in vamp_rows] == [1, 2]
    assert len({(row["source_id"], row["source_row"]) for row in all_rows}) == len(all_rows)
    for row in all_rows:
        _assert_exact_row_schema(row, model_api)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "raptor.external.normalized_functional_row.v0"),
        ("gene", "TSC1"),
        ("source_id", ""),
        ("score_name", ""),
        ("score_raw", "NaN"),
        ("spdi", "not-an-spdi"),
        ("spdi", "NC_000017.11:2044828:C:T"),
        ("spdi", "NC_000016.10:2044827:C:T"),
        ("spdi", "NC_000016.10:2044828:G:T"),
        ("spdi", "NC_000016.10:2044828:C:A"),
    ],
    ids=[
        "wrong-schema",
        "wrong-gene",
        "blank-source-id",
        "blank-score-name",
        "non-finite-score",
        "malformed-spdi",
        "wrong-spdi-accession",
        "wrong-spdi-position",
        "wrong-spdi-ref",
        "wrong-spdi-alt",
    ],
)
def test_fn04b_row_model_rejects_invalid_schema_identity_and_spdi_binding(field: str, value: Any) -> None:
    model_api = _model_api()
    base = {
        "source_id": "igvf_sge",
        "source_row": 1,
        "source_record_id": "NC_000016.10:g.2044829C>T",
        "gene": "TSC2",
        "assembly": "GRCh38",
        "transcript": "NM_000548.5",
        "protein_accession": None,
        "hgvs_c": "NM_000548.5:c.100A>G",
        "hgvs_p": "p.Lys34Arg",
        "hgvs_g": "NC_000016.10:g.2044829C>T",
        "spdi": "NC_000016.10:2044828:C:T",
        "variant_kind": "MISSENSE",
        "identity_state": "GENOMIC_SPDI_VERIFIED",
        "unresolved_reason": None,
        "score_name": "pS6_score",
        "score_raw": "0.71",
        "schema": NORMALIZATION_SCHEMA,
    }
    base[field] = value
    with pytest.raises(model_api["NormalizationContractError"]):
        model_api["NormalizedFunctionalRow"](**base)


def test_fn04c_canonical_jsonl_revalidates_full_row_invariants_not_only_keys() -> None:
    bundle_api = _bundle_api()
    model_api = _model_api()
    invalid_row = _minimal_normalized_row(source_id="mavedb_clipe", source_row=1)
    invalid_row["source_id"] = ""
    with pytest.raises(model_api["NormalizationContractError"]):
        bundle_api["canonical_jsonl_bytes"]([invalid_row])


def test_fn05_mavedb_exact_header_count_pin_hgvs_prefix_variant_kind_and_no_spdi() -> None:
    model_api = _model_api()
    normalize_api = _normalize_api()
    csv_text = _csv_payload(
        MAVEDB_HEADER,
        [
            ["r1", "c.100A>G", "", "p.Lys34Arg", "0.40"],
            ["r2", "c.120A>T", "", "p.Lys40=", "0.05"],
            ["r3", "c.150G>A", "", "p.Trp50Ter", "-0.70"],
        ],
    )
    rows = normalize_api["normalize_mavedb"](
        source_id="mavedb_clipe",
        csv_text=csv_text,
        expected_header=MAVEDB_HEADER,
        expected_rows=3,
        transcript=SOURCE_TRANSCRIPT,
    )

    assert [row["hgvs_c"] for row in rows] == [
        "NM_000548.5:c.100A>G",
        "NM_000548.5:c.120A>T",
        "NM_000548.5:c.150G>A",
    ]
    assert [row["variant_kind"] for row in rows] == ["MISSENSE", "SYNONYMOUS", "STOP_GAINED"]
    assert all(row["score_raw"] in {"0.40", "0.05", "-0.70"} for row in rows)
    assert all(row["spdi"] is None for row in rows)
    assert all(row["identity_state"] == "TRANSCRIPT_ONLY_PROJECTOR_REQUIRED" for row in rows)
    assert all(row["unresolved_reason"] == "CDNA_PROJECTOR_REQUIRED" for row in rows)

    with pytest.raises(model_api["NormalizationContractError"]):
        normalize_api["normalize_mavedb"](
            source_id="mavedb_clipe",
            csv_text=csv_text,
            expected_header=MAVEDB_HEADER,
            expected_rows=208,
            transcript=SOURCE_TRANSCRIPT,
        )

    with pytest.raises(model_api["NormalizationContractError"]):
        normalize_api["normalize_mavedb"](
            source_id="mavedb_clipe",
            csv_text=_csv_payload(MAVEDB_HEADER, [["", "c.100A>G", "", "p.Lys34Arg", "0.10"]]),
            expected_header=MAVEDB_HEADER,
            expected_rows=1,
            transcript=SOURCE_TRANSCRIPT,
        )
    with pytest.raises(model_api["NormalizationContractError"]):
        normalize_api["normalize_mavedb"](
            source_id="mavedb_clipe",
            csv_text=_csv_payload(
                MAVEDB_HEADER, [["m1", "NM_000548_5:c.100A>G", "", "p.Lys34Arg", "0.10"]]
            ),
            expected_header=MAVEDB_HEADER,
            expected_rows=1,
            transcript=SOURCE_TRANSCRIPT,
        )
    with pytest.raises(model_api["NormalizationContractError"]):
        normalize_api["normalize_mavedb"](
            source_id="mavedb_clipe",
            csv_text=_csv_payload(MAVEDB_HEADER, [["m1", "c.100A>G", "", "", "0.10"]]),
            expected_header=MAVEDB_HEADER,
            expected_rows=1,
            transcript=SOURCE_TRANSCRIPT,
        )


def test_fn06_vamp_exact_header_real_variant_token_and_wrong_accession_rejected() -> None:
    model_api = _model_api()
    normalize_api = _normalize_api()

    rows = normalize_api["normalize_vamp_seq"](
        source_id="igvf_vamp_seq",
        tsv_gz_bytes=_gzip_tsv_payload(
            VAMP_HEADER,
            [
                ["ENSP00000219476.3:p.Arg174Cys", "0.62", "0.03", "0.60", "0.63", "0.63", "damaging"],
                ["ENSP00000219476.3:p.Lys40=", "0.05", "0.02", "0.06", "0.05", "0.04", "wt-like"],
            ],
        ),
        expected_header=VAMP_HEADER,
        expected_rows=2,
        required_protein_accession=VAMP_PROTEIN_ACCESSION,
    )
    assert [row["variant_kind"] for row in rows] == ["MISSENSE", "SYNONYMOUS"]
    assert all(row["protein_accession"] == VAMP_PROTEIN_ACCESSION for row in rows)
    assert all(row["transcript"] is None and row["assembly"] is None and row["spdi"] is None for row in rows)
    assert all("functional_class" not in row for row in rows)

    with pytest.raises(model_api["NormalizationContractError"]):
        normalize_api["normalize_vamp_seq"](
            source_id="igvf_vamp_seq",
            tsv_gz_bytes=_gzip_tsv_payload(
                VAMP_HEADER,
                [["ENSP00000399999.1:p.Arg174Cys", "0.62", "0.03", "0.60", "0.63", "0.63", "damaging"]],
            ),
            expected_header=VAMP_HEADER,
            expected_rows=1,
            required_protein_accession=VAMP_PROTEIN_ACCESSION,
        )
    with pytest.raises(model_api["NormalizationContractError"]):
        normalize_api["normalize_vamp_seq"](
            source_id="igvf_vamp_seq",
            tsv_gz_bytes=_gzip_tsv_payload(
                VAMP_HEADER,
                [["ENSP00000219476.3:p.?", "0.62", "0.03", "0.60", "0.63", "0.63", "damaging"]],
            ),
            expected_header=VAMP_HEADER,
            expected_rows=1,
            required_protein_accession=VAMP_PROTEIN_ACCESSION,
        )


def test_fn06c_crlf_gzip_tsv_line_endings_parse_identically_to_lf_for_vamp_and_sge() -> None:
    normalize_api = _normalize_api()
    ingest_model_api = _ingest_model_api()

    vamp_rows_lf = normalize_api["normalize_vamp_seq"](
        source_id="igvf_vamp_seq",
        tsv_gz_bytes=_gzip_tsv_payload(
            VAMP_HEADER,
            [
                ["ENSP00000219476.3:p.Arg174Cys", "0.62", "0.03", "0.60", "0.63", "0.63", "damaging"],
                ["ENSP00000219476.3:p.Lys40=", "0.05", "0.02", "0.06", "0.05", "0.04", "wt-like"],
            ],
            line_ending="\n",
        ),
        expected_header=VAMP_HEADER,
        expected_rows=2,
        required_protein_accession=VAMP_PROTEIN_ACCESSION,
    )
    vamp_rows_crlf = normalize_api["normalize_vamp_seq"](
        source_id="igvf_vamp_seq",
        tsv_gz_bytes=_gzip_tsv_payload(
            VAMP_HEADER,
            [
                ["ENSP00000219476.3:p.Arg174Cys", "0.62", "0.03", "0.60", "0.63", "0.63", "damaging"],
                ["ENSP00000219476.3:p.Lys40=", "0.05", "0.02", "0.06", "0.05", "0.04", "wt-like"],
            ],
            line_ending="\r\n",
        ),
        expected_header=VAMP_HEADER,
        expected_rows=2,
        required_protein_accession=VAMP_PROTEIN_ACCESSION,
    )
    assert vamp_rows_crlf == vamp_rows_lf
    assert all("\r" not in row["hgvs_p"] for row in vamp_rows_crlf)
    assert all("\r" not in row["score_raw"] for row in vamp_rows_crlf)

    class StubNormalizer:
        def normalize(self, raw: Any, _config: object) -> Any:
            return _mk_normalized_variant(
                ingest_model_api,
                raw,
                variant_id=f"{raw.chromosome}:{int(raw.position) - 1}:{raw.ref}:{raw.alt}",
            )

    sge_rows_lf = normalize_api["normalize_sge"](
        source_id="igvf_sge",
        tsv_gz_bytes=_gzip_tsv_payload(
            SGE_HEADER,
            [
                _sge_row(hgvs_nt="NM_000548_5:c.=", hgvs_p="p.=", hgvs_g="NC_000016_10:g.=", score="0.00"),
                _sge_row(
                    hgvs_nt="NM_000548_5:c.100A>G",
                    hgvs_p="p.Lys34Arg",
                    hgvs_g="NC_000016_10:g.2044829C>T",
                    score="0.71",
                ),
            ],
            line_ending="\n",
        ),
        expected_header=SGE_HEADER,
        expected_rows=2,
        expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
        expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
        normalized_transcript=SOURCE_TRANSCRIPT,
        normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        gene="TSC2",
        normalizer=StubNormalizer(),
        normalizer_config={"run_id": "fn06c"},
    )
    sge_rows_crlf = normalize_api["normalize_sge"](
        source_id="igvf_sge",
        tsv_gz_bytes=_gzip_tsv_payload(
            SGE_HEADER,
            [
                _sge_row(hgvs_nt="NM_000548_5:c.=", hgvs_p="p.=", hgvs_g="NC_000016_10:g.=", score="0.00"),
                _sge_row(
                    hgvs_nt="NM_000548_5:c.100A>G",
                    hgvs_p="p.Lys34Arg",
                    hgvs_g="NC_000016_10:g.2044829C>T",
                    score="0.71",
                ),
            ],
            line_ending="\r\n",
        ),
        expected_header=SGE_HEADER,
        expected_rows=2,
        expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
        expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
        normalized_transcript=SOURCE_TRANSCRIPT,
        normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        gene="TSC2",
        normalizer=StubNormalizer(),
        normalizer_config={"run_id": "fn06c"},
    )
    assert sge_rows_crlf == sge_rows_lf
    for row in sge_rows_crlf:
        for value in row.values():
            if isinstance(value, str):
                assert "\r" not in value


def test_fn07_sge_accession_prefix_rules_reference_controls_snv_parsing_and_rawvariant_provenance() -> None:
    model_api = _model_api()
    normalize_api = _normalize_api()
    ingest_model_api = _ingest_model_api()

    class StubNormalizer:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, Any]] = []

        def normalize(self, raw: Any, config: object) -> Any:
            self.calls.append((raw, config))
            return _mk_normalized_variant(ingest_model_api, raw, variant_id="NC_000016.10:2044828:C:T")

    normalizer = StubNormalizer()
    rows = normalize_api["normalize_sge"](
        source_id="igvf_sge",
        tsv_gz_bytes=_gzip_tsv_payload(
            SGE_HEADER,
            [
                _sge_row(hgvs_nt="NM_000548_5:c.=", hgvs_p="p.=", hgvs_g="NC_000016_10:g.=", score="0.00"),
                _sge_row(
                    hgvs_nt="NM_000548_5:c.100A>G",
                    hgvs_p="p.Lys34Arg",
                    hgvs_g="NC_000016_10:g.2044829C>T",
                    score="0.71",
                ),
            ],
        ),
        expected_header=SGE_HEADER,
        expected_rows=2,
        expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
        expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
        normalized_transcript=SOURCE_TRANSCRIPT,
        normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        gene="TSC2",
        normalizer=normalizer,
        normalizer_config={"run_id": "fn07"},
    )

    assert rows[0]["identity_state"] == "REFERENCE_CONTROL"
    assert rows[0]["variant_kind"] == "REFERENCE_CONTROL"
    assert rows[0]["unresolved_reason"] == "NOT_A_VARIANT"
    assert rows[0]["spdi"] is None
    assert len(normalizer.calls) == 1
    raw, config = normalizer.calls[0]
    assert config == {"run_id": "fn07"}
    assert isinstance(raw, ingest_model_api["RawVariant"])
    assert raw.chromosome == SOURCE_GDNA_ACCESSION
    assert raw.position == 2044829
    assert raw.ref == "C"
    assert raw.alt == "T"
    assert raw.gene == "TSC2"
    assert "igvf_sge" in raw.row_locator
    assert "2" in raw.row_locator

    with pytest.raises(model_api["NormalizationContractError"]):
        normalize_api["normalize_sge"](
            source_id="igvf_sge",
            tsv_gz_bytes=_gzip_tsv_payload(
                SGE_HEADER,
                [
                    _sge_row(
                        hgvs_nt="XM_000548_5:c.100A>G",
                        hgvs_p="p.Lys34Arg",
                        hgvs_g="NC_000016_10:g.2044829C>T",
                        score="0.71",
                    )
                ],
            ),
            expected_header=SGE_HEADER,
            expected_rows=1,
            expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
            expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
            normalized_transcript=SOURCE_TRANSCRIPT,
            normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
            assembly=REFERENCE_ASSEMBLY,
            gene="TSC2",
            normalizer=normalizer,
            normalizer_config={"run_id": "fn07"},
        )
    with pytest.raises(model_api["NormalizationContractError"]):
        normalize_api["normalize_sge"](
            source_id="igvf_sge",
            tsv_gz_bytes=_gzip_tsv_payload(
                SGE_HEADER,
                [
                    _sge_row(
                        hgvs_nt="NM_000548_5:c.100A>G",
                        hgvs_p="p.Lys34Arg",
                        hgvs_g="NC_000016_10:g.2044829C>Tjunk",
                        score="0.71",
                    )
                ],
            ),
            expected_header=SGE_HEADER,
            expected_rows=1,
            expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
            expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
            normalized_transcript=SOURCE_TRANSCRIPT,
            normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
            assembly=REFERENCE_ASSEMBLY,
            gene="TSC2",
            normalizer=normalizer,
            normalizer_config={"run_id": "fn07"},
        )


def test_fn08_sge_manual_queue_mapping_ref_mismatch_blocks_other_manual_outcomes_abort() -> None:
    model_api = _model_api()
    normalize_api = _normalize_api()
    ingest_model_api = _ingest_model_api()

    class RefMismatchNormalizer:
        def normalize(self, raw: Any, _config: object) -> Any:
            return _mk_manual_queue_item(ingest_model_api, raw, error_code="REF_MISMATCH")

    rows = normalize_api["normalize_sge"](
        source_id="igvf_sge",
        tsv_gz_bytes=_gzip_tsv_payload(
            SGE_HEADER,
            [
                _sge_row(
                    hgvs_nt="NM_000548_5:c.220A>T",
                    hgvs_p="p.Lys74Asn",
                    hgvs_g="NC_000016_10:g.2044950A>T",
                    score="0.42",
                )
            ],
        ),
        expected_header=SGE_HEADER,
        expected_rows=1,
        expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
        expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
        normalized_transcript=SOURCE_TRANSCRIPT,
        normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        gene="TSC2",
        normalizer=RefMismatchNormalizer(),
        normalizer_config={"run_id": "fn08"},
    )
    assert rows[0]["identity_state"] == "GENOMIC_REFERENCE_MISMATCH"
    assert rows[0]["unresolved_reason"] == "REFERENCE_ALLELE_MISMATCH"
    assert rows[0]["spdi"] is None

    class OtherManualNormalizer:
        def normalize(self, raw: Any, _config: object) -> Any:
            return _mk_manual_queue_item(ingest_model_api, raw, error_code="NORMALIZATION_FAILED")

    with pytest.raises(model_api["NormalizationOutcomeError"]):
        normalize_api["normalize_sge"](
            source_id="igvf_sge",
            tsv_gz_bytes=_gzip_tsv_payload(
                SGE_HEADER,
                [
                    _sge_row(
                        hgvs_nt="NM_000548_5:c.220A>T",
                        hgvs_p="p.Lys74Asn",
                        hgvs_g="NC_000016_10:g.2044950A>T",
                        score="0.42",
                    )
                ],
            ),
            expected_header=SGE_HEADER,
            expected_rows=1,
            expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
            expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
            normalized_transcript=SOURCE_TRANSCRIPT,
            normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
            assembly=REFERENCE_ASSEMBLY,
            gene="TSC2",
            normalizer=OtherManualNormalizer(),
            normalizer_config={"run_id": "fn08"},
        )


@pytest.mark.parametrize("bad_score", ["", "not-a-number", "NaN", "inf", "-inf"])
def test_fn09_score_rejection_for_blank_non_numeric_nan_or_infinite_values(bad_score: str) -> None:
    model_api = _model_api()
    normalize_api = _normalize_api()

    with pytest.raises(model_api["ScoreValidationError"]):
        normalize_api["normalize_mavedb"](
            source_id="mavedb_clipe",
            csv_text=_csv_payload(MAVEDB_HEADER, [["m1", "c.100A>G", "", "p.Lys34Arg", bad_score]]),
            expected_header=MAVEDB_HEADER,
            expected_rows=1,
            transcript=SOURCE_TRANSCRIPT,
        )
    with pytest.raises(model_api["ScoreValidationError"]):
        normalize_api["normalize_vamp_seq"](
            source_id="igvf_vamp_seq",
            tsv_gz_bytes=_gzip_tsv_payload(
                VAMP_HEADER,
                [["ENSP00000219476.3:p.Arg174Cys", bad_score, "0.03", "0.60", "0.63", "0.63", "damaging"]],
            ),
            expected_header=VAMP_HEADER,
            expected_rows=1,
            required_protein_accession=VAMP_PROTEIN_ACCESSION,
        )
    with pytest.raises(model_api["ScoreValidationError"]):
        normalize_api["normalize_sge"](
            source_id="igvf_sge",
            tsv_gz_bytes=_gzip_tsv_payload(
                SGE_HEADER,
                [
                    _sge_row(
                        hgvs_nt="NM_000548_5:c.100A>G",
                        hgvs_p="p.Lys34Arg",
                        hgvs_g="NC_000016_10:g.2044829C>T",
                        score=bad_score,
                    )
                ],
            ),
            expected_header=SGE_HEADER,
            expected_rows=1,
            expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
            expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
            normalized_transcript=SOURCE_TRANSCRIPT,
            normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
            assembly=REFERENCE_ASSEMBLY,
            gene="TSC2",
            normalizer=object(),
            normalizer_config={"run_id": "fn09"},
        )


def test_fn10_reference_mismatch_row_retains_source_hgvs_and_score_with_explicit_blocked_state() -> None:
    normalize_api = _normalize_api()
    ingest_model_api = _ingest_model_api()

    class RefMismatchNormalizer:
        def normalize(self, raw: Any, _config: object) -> Any:
            return _mk_manual_queue_item(ingest_model_api, raw, error_code="REF_MISMATCH")

    rows = normalize_api["normalize_sge"](
        source_id="igvf_sge",
        tsv_gz_bytes=_gzip_tsv_payload(
            SGE_HEADER,
            [
                _sge_row(
                    hgvs_nt="NM_000548_5:c.220A>T",
                    hgvs_p="p.Lys74Asn",
                    hgvs_g="NC_000016_10:g.2044950A>T",
                    score="0.42",
                )
            ],
        ),
        expected_header=SGE_HEADER,
        expected_rows=1,
        expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
        expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
        normalized_transcript=SOURCE_TRANSCRIPT,
        normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        gene="TSC2",
        normalizer=RefMismatchNormalizer(),
        normalizer_config={"run_id": "fn10"},
    )
    row = rows[0]
    assert row["hgvs_c"] == "NM_000548.5:c.220A>T"
    assert row["hgvs_g"] == "NC_000016.10:g.2044950A>T"
    assert row["score_raw"] == "0.42"
    assert row["spdi"] is None
    assert row["identity_state"] == "GENOMIC_REFERENCE_MISMATCH"
    assert row["unresolved_reason"] == "REFERENCE_ALLELE_MISMATCH"


@pytest.mark.parametrize(
    "variant_id",
    [
        "NC_000017.11:2044828:C:T",
        "NC_000016.10:2044827:C:T",
        "NC_000016.10:2044828:G:T",
        "NC_000016.10:2044828:C:A",
    ],
    ids=["wrong-accession", "wrong-position", "wrong-ref", "wrong-alt"],
)
def test_fn10b_sge_normalizer_success_result_must_bind_to_exact_source_snv_spdi(variant_id: str) -> None:
    model_api = _model_api()
    normalize_api = _normalize_api()
    ingest_model_api = _ingest_model_api()

    class VariantIdNormalizer:
        def normalize(self, raw: Any, _config: object) -> Any:
            return _mk_normalized_variant(ingest_model_api, raw, variant_id=variant_id)

    with pytest.raises(model_api["NormalizationOutcomeError"]):
        normalize_api["normalize_sge"](
            source_id="igvf_sge",
            tsv_gz_bytes=_gzip_tsv_payload(
                SGE_HEADER,
                [
                    _sge_row(
                        hgvs_nt="NM_000548_5:c.100A>G",
                        hgvs_p="p.Lys34Arg",
                        hgvs_g="NC_000016_10:g.2044829C>T",
                        score="0.77",
                    )
                ],
            ),
            expected_header=SGE_HEADER,
            expected_rows=1,
            expected_source_transcript=SGE_SOURCE_TRANSCRIPT,
            expected_source_genomic_accession=SGE_SOURCE_GDNA_ACCESSION,
            normalized_transcript=SOURCE_TRANSCRIPT,
            normalized_genomic_accession=SOURCE_GDNA_ACCESSION,
            assembly=REFERENCE_ASSEMBLY,
            gene="TSC2",
            normalizer=VariantIdNormalizer(),
            normalizer_config={"run_id": "fn10b"},
        )


def test_fn11_output_manifest_shape_count_conservation_and_hash_determinism() -> None:
    bundle_api = _bundle_api()
    row = _minimal_normalized_row(source_id="mavedb_clipe", source_row=1)
    payload = bundle_api["canonical_jsonl_bytes"]([row])
    artifact = {
        "artifact_id": "mavedb_clipe-normalized-jsonl",
        "source_id": "mavedb_clipe",
        "relative_path": "normalized/mavedb_clipe.jsonl",
        "byte_length": len(payload),
        "sha256": _sha256_bytes(payload),
        "row_count": 1,
    }
    manifest_a = bundle_api["build_normalization_manifest"](
        bundle_id=NORMALIZATION_BUNDLE_ID,
        created_at="2026-09-11T00:00:00Z",
        input_bundle={"bundle_id": INPUT_BUNDLE_ID, "content_hash": INPUT_MANIFEST_CONTENT_HASH},
        reference={"accession": REFERENCE_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        artifacts=[artifact],
        counts={"sources": 1, "artifacts": 1, "rows": 1},
        identity_state_counts={"TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 1},
        variant_kind_counts={"MISSENSE": 1},
        boundaries={"network": "forbidden", "external_output_only": True},
    )
    manifest_b = bundle_api["build_normalization_manifest"](
        bundle_id=NORMALIZATION_BUNDLE_ID,
        created_at="2026-09-11T00:00:00Z",
        input_bundle={"content_hash": INPUT_MANIFEST_CONTENT_HASH, "bundle_id": INPUT_BUNDLE_ID},
        reference={"sha256": REFERENCE_FASTA_SHA256, "accession": REFERENCE_ACCESSION},
        artifacts=[dict(reversed(list(artifact.items())))],
        counts={"rows": 1, "sources": 1, "artifacts": 1},
        identity_state_counts={"TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 1},
        variant_kind_counts={"MISSENSE": 1},
        boundaries={"external_output_only": True, "network": "forbidden"},
    )

    assert set(manifest_a) == {
        "schema",
        "bundle_id",
        "created_at",
        "input_bundle",
        "reference",
        "artifacts",
        "counts",
        "identity_state_counts",
        "variant_kind_counts",
        "boundaries",
        "content_hash",
    }
    assert manifest_a["schema"] == BUNDLE_SCHEMA
    assert manifest_a["counts"] == {"sources": 1, "artifacts": 1, "rows": 1}
    assert manifest_a["content_hash"] == manifest_b["content_hash"]
    assert bundle_api["compute_manifest_content_hash"](manifest_a) == manifest_a["content_hash"]

    mutated = deepcopy(manifest_a)
    mutated["artifacts"][0]["sha256"] = "0" * 64
    assert bundle_api["compute_manifest_content_hash"](mutated) != manifest_a["content_hash"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda args: args.update({"counts": {"sources": 2, "artifacts": 2, "rows": 999}}),
        lambda args: args.update(
            {"identity_state_counts": {"TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 1, "PROTEIN_ONLY_CROSSWALK_REQUIRED": 9}}
        ),
        lambda args: args.update({"variant_kind_counts": {"MISSENSE": 1}}),
        lambda args: args["artifacts"].append(deepcopy(args["artifacts"][0])),
        lambda args: args["artifacts"][1].update({"artifact_id": args["artifacts"][0]["artifact_id"]}),
        lambda args: args["artifacts"][1].update({"source_id": args["artifacts"][0]["source_id"]}),
        lambda args: args["artifacts"][1].update({"relative_path": args["artifacts"][0]["relative_path"]}),
        lambda args: args["artifacts"][0].update({"unexpected": "extra-field"}),
        lambda args: args["artifacts"][0].update({"row_count": args["artifacts"][0]["row_count"] + 1}),
    ],
    ids=[
        "counts-rows-mismatch",
        "identity-sum-mismatch",
        "variant-sum-mismatch",
        "duplicate-artifact-record",
        "duplicate-artifact-id",
        "duplicate-artifact-source-id",
        "duplicate-artifact-relative-path",
        "unexpected-artifact-field",
        "artifact-row-sum-mismatch",
    ],
)
def test_fn11b_manifest_builder_rejects_conservation_and_artifact_integrity_violations(mutate) -> None:
    bundle_api = _bundle_api()
    row_a = _minimal_normalized_row(source_id="mavedb_clipe", source_row=1)
    row_b = _minimal_normalized_row(source_id="igvf_vamp_seq", source_row=1)
    payload_a = bundle_api["canonical_jsonl_bytes"]([row_a])
    payload_b = bundle_api["canonical_jsonl_bytes"]([row_b])
    args = {
        "bundle_id": NORMALIZATION_BUNDLE_ID,
        "created_at": "2026-09-11T00:00:00Z",
        "input_bundle": {"bundle_id": INPUT_BUNDLE_ID, "content_hash": INPUT_MANIFEST_CONTENT_HASH},
        "reference": {"accession": REFERENCE_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        "artifacts": [
            {
                "artifact_id": "mavedb_clipe-normalized-jsonl",
                "source_id": "mavedb_clipe",
                "relative_path": "normalized/mavedb_clipe.jsonl",
                "byte_length": len(payload_a),
                "sha256": _sha256_bytes(payload_a),
                "row_count": 1,
            },
            {
                "artifact_id": "igvf_vamp_seq-normalized-jsonl",
                "source_id": "igvf_vamp_seq",
                "relative_path": "normalized/igvf_vamp_seq.jsonl",
                "byte_length": len(payload_b),
                "sha256": _sha256_bytes(payload_b),
                "row_count": 1,
            },
        ],
        "counts": {"sources": 2, "artifacts": 2, "rows": 2},
        "identity_state_counts": {"TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 1, "PROTEIN_ONLY_CROSSWALK_REQUIRED": 1},
        "variant_kind_counts": {"MISSENSE": 2},
        "boundaries": {"network": "forbidden", "external_output_only": True},
    }
    mutate(args)
    with pytest.raises(bundle_api["NormalizationManifestError"]):
        bundle_api["build_normalization_manifest"](**args)


def test_fn12_canonical_jsonl_is_deterministic_lf_final_newline_and_rejects_duplicate_source_row() -> None:
    bundle_api = _bundle_api()
    model_api = _model_api()

    rows = [
        _minimal_normalized_row(source_id="mavedb_clipe", source_row=1),
        _minimal_normalized_row(source_id="igvf_vamp_seq", source_row=1),
    ]
    shuffled = [dict(reversed(list(row.items()))) for row in rows]
    blob_a = bundle_api["canonical_jsonl_bytes"](rows)
    blob_b = bundle_api["canonical_jsonl_bytes"](shuffled)

    assert blob_a == blob_b
    assert blob_a.endswith(b"\n")
    text = blob_a.decode("utf-8")
    assert "\r\n" not in text
    lines = [line for line in text.split("\n") if line]
    assert len(lines) == 2
    assert lines[0].index('"assembly"') < lines[0].index('"gene"')

    duplicate_rows = [
        _minimal_normalized_row(source_id="mavedb_clipe", source_row=1),
        _minimal_normalized_row(source_id="mavedb_clipe", source_row=1),
    ]
    with pytest.raises(model_api["NormalizationContractError"]):
        bundle_api["canonical_jsonl_bytes"](duplicate_rows)


def test_fn13_publication_reuses_hardened_source_ingestion_helper_and_refuses_unsafe_destinations(
    tmp_path: Path,
) -> None:
    bundle_api = _bundle_api()
    source_bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    assert bundle_api["_publish_directory_no_replace"] is _symbol(
        source_bundle_module, "_publish_directory_no_replace"
    )

    row = _minimal_normalized_row(source_id="mavedb_clipe", source_row=1)
    payload = bundle_api["canonical_jsonl_bytes"]([row])
    manifest = bundle_api["build_normalization_manifest"](
        bundle_id=NORMALIZATION_BUNDLE_ID,
        created_at="2026-09-11T00:00:00Z",
        input_bundle={"bundle_id": INPUT_BUNDLE_ID, "content_hash": INPUT_MANIFEST_CONTENT_HASH},
        reference={"accession": REFERENCE_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        artifacts=[
            {
                "artifact_id": "mavedb_clipe-normalized-jsonl",
                "source_id": "mavedb_clipe",
                "relative_path": "normalized/mavedb_clipe.jsonl",
                "byte_length": len(payload),
                "sha256": _sha256_bytes(payload),
                "row_count": 1,
            }
        ],
        counts={"sources": 1, "artifacts": 1, "rows": 1},
        identity_state_counts={"TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 1},
        variant_kind_counts={"MISSENSE": 1},
        boundaries={"network": "forbidden", "external_output_only": True},
    )
    artifact_payloads = {"normalized/mavedb_clipe.jsonl": payload}

    output_root = tmp_path / "external-root"
    output_root.mkdir()
    preexisting = output_root / NORMALIZATION_RUN_NAME
    preexisting.mkdir()
    with pytest.raises(bundle_api["FunctionalBundleBoundaryError"]):
        bundle_api["publish_normalized_bundle"](
            repo_root=tmp_path / "repo",
            output_root=output_root,
            run_name=NORMALIZATION_RUN_NAME,
            manifest=manifest,
            artifact_payloads=artifact_payloads,
        )
    assert preexisting.exists()
    assert list(preexisting.iterdir()) == []

    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    with pytest.raises(bundle_api["FunctionalBundleBoundaryError"]):
        bundle_api["publish_normalized_bundle"](
            repo_root=repo_root,
            output_root=repo_root / "outside-violating-root",
            run_name=NORMALIZATION_RUN_NAME,
            manifest=manifest,
            artifact_payloads=artifact_payloads,
        )


def test_fn14_summary_aggregate_contract_and_unresolved_reason_derivation_from_identity_counts() -> None:
    bundle_api = _bundle_api()
    row_a = _minimal_normalized_row(source_id="mavedb_clipe", source_row=1)
    row_b = _minimal_normalized_row(source_id="igvf_vamp_seq", source_row=1)
    payload_a = bundle_api["canonical_jsonl_bytes"]([row_a])
    payload_b = bundle_api["canonical_jsonl_bytes"]([row_b])
    identity_counts = {
        "GENOMIC_SPDI_VERIFIED": 7,
        "GENOMIC_REFERENCE_MISMATCH": 3,
        "TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 5,
        "PROTEIN_ONLY_CROSSWALK_REQUIRED": 11,
        "REFERENCE_CONTROL": 2,
    }
    manifest = bundle_api["build_normalization_manifest"](
        bundle_id=NORMALIZATION_BUNDLE_ID,
        created_at="2026-09-11T00:00:00Z",
        input_bundle={"bundle_id": INPUT_BUNDLE_ID, "content_hash": INPUT_MANIFEST_CONTENT_HASH},
        reference={"accession": REFERENCE_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        artifacts=[
            {
                "artifact_id": "mavedb_clipe-normalized-jsonl",
                "source_id": "mavedb_clipe",
                "relative_path": "normalized/mavedb_clipe.jsonl",
                "byte_length": len(payload_a),
                "sha256": _sha256_bytes(payload_a),
                "row_count": 17,
            },
            {
                "artifact_id": "igvf_vamp_seq-normalized-jsonl",
                "source_id": "igvf_vamp_seq",
                "relative_path": "normalized/igvf_vamp_seq.jsonl",
                "byte_length": len(payload_b),
                "sha256": _sha256_bytes(payload_b),
                "row_count": 11,
            },
        ],
        counts={"sources": 2, "artifacts": 2, "rows": sum(identity_counts.values())},
        identity_state_counts=identity_counts,
        variant_kind_counts={"MISSENSE": sum(identity_counts.values())},
        boundaries={"network": "forbidden", "external_output_only": True},
    )
    assert "unresolved_reason_counts" not in manifest

    summary = bundle_api["build_committed_summary"](manifest)
    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "input_bundle_content_hash",
        "reference_sha256",
        "counts",
        "identity_state_counts",
        "variant_kind_counts",
        "source_row_counts",
        "artifact_integrity",
        "unresolved_reason_counts",
        "normalization_gaps",
    }
    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["manifest_content_hash"] == manifest["content_hash"]
    assert summary["unresolved_reason_counts"] == {
        "REFERENCE_ALLELE_MISMATCH": identity_counts["GENOMIC_REFERENCE_MISMATCH"],
        "CDNA_PROJECTOR_REQUIRED": identity_counts["TRANSCRIPT_ONLY_PROJECTOR_REQUIRED"],
        "NUCLEOTIDE_CROSSWALK_REQUIRED": identity_counts["PROTEIN_ONLY_CROSSWALK_REQUIRED"],
        "NOT_A_VARIANT": identity_counts["REFERENCE_CONTROL"],
    }


def test_fn15_summary_and_manifest_exclude_row_level_content_full_spdi_values_and_clinical_claims() -> None:
    bundle_api = _bundle_api()
    row = _minimal_normalized_row(source_id="mavedb_clipe", source_row=1)
    payload = bundle_api["canonical_jsonl_bytes"]([row])
    manifest = bundle_api["build_normalization_manifest"](
        bundle_id=NORMALIZATION_BUNDLE_ID,
        created_at="2026-09-11T00:00:00Z",
        input_bundle={"bundle_id": INPUT_BUNDLE_ID, "content_hash": INPUT_MANIFEST_CONTENT_HASH},
        reference={"accession": REFERENCE_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        artifacts=[
            {
                "artifact_id": "mavedb_clipe-normalized-jsonl",
                "source_id": "mavedb_clipe",
                "relative_path": "normalized/mavedb_clipe.jsonl",
                "byte_length": len(payload),
                "sha256": _sha256_bytes(payload),
                "row_count": 1,
            }
        ],
        counts={"sources": 1, "artifacts": 1, "rows": 1},
        identity_state_counts={"TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 1},
        variant_kind_counts={"MISSENSE": 1},
        boundaries={"network": "forbidden", "external_output_only": True},
    )
    summary = bundle_api["build_committed_summary"](manifest)
    merged = json.dumps({"manifest": manifest, "summary": summary}, sort_keys=True)

    assert not any(token in merged for token in FORBIDDEN_ROW_LEVEL_KEYS)
    assert SPDI_VALUE_PATTERN.search(merged) is None
    assert not any(token in merged.lower() for token in FORBIDDEN_CLINICAL_TOKENS)


def test_fn16_config_pins_exact_input_hashes_accessions_run_names_and_expected_totals() -> None:
    if not CONFIG_PATH.is_file():
        pytest.fail(f"TSC2 functional normalization config is not implemented: {CONFIG_PATH}")

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["spec_version"] == "1.0.1"
    assert config["inputs"]["source_bundle"]["bundle_id"] == INPUT_BUNDLE_ID
    assert config["inputs"]["source_bundle"]["run_name"] == INPUT_BUNDLE_RUN_NAME
    assert config["inputs"]["source_bundle"]["manifest_filename"] == INPUT_MANIFEST_FILENAME
    assert config["inputs"]["source_bundle"]["manifest_content_hash"] == INPUT_MANIFEST_CONTENT_HASH

    required_artifacts = config["inputs"]["source_bundle"]["required_artifacts"]
    assert required_artifacts["mavedb_clipe"]["sha256"] == MAVEDB_SCORES_SHA256
    assert required_artifacts["igvf_vamp_seq"]["md5"] == VAMP_DOWNLOAD_MD5
    assert required_artifacts["igvf_vamp_seq"]["byte_length"] == VAMP_DOWNLOAD_BYTES
    assert required_artifacts["igvf_sge"]["md5"] == SGE_DOWNLOAD_MD5
    assert required_artifacts["igvf_sge"]["byte_length"] == SGE_DOWNLOAD_BYTES

    assert config["inputs"]["genomic_reference"]["accession"] == REFERENCE_ACCESSION
    assert config["inputs"]["genomic_reference"]["assembly"] == REFERENCE_ASSEMBLY
    assert config["inputs"]["genomic_reference"]["fasta_filename"] == REFERENCE_FASTA_FILENAME
    assert config["inputs"]["genomic_reference"]["sha256"] == REFERENCE_FASTA_SHA256

    assert config["inputs"]["identity_pins"]["gene"] == "TSC2"
    assert config["inputs"]["identity_pins"]["transcript"] == SOURCE_TRANSCRIPT
    assert config["inputs"]["identity_pins"]["genomic_accession"] == SOURCE_GDNA_ACCESSION
    assert config["inputs"]["identity_pins"]["sge_source_transcript"] == SGE_SOURCE_TRANSCRIPT
    assert config["inputs"]["identity_pins"]["sge_source_genomic_accession"] == SGE_SOURCE_GDNA_ACCESSION
    assert config["inputs"]["identity_pins"]["vamp_source_protein"] == VAMP_PROTEIN_ACCESSION

    assert config["output"]["external_bundle"]["run_name"] == NORMALIZATION_RUN_NAME
    assert config["output"]["external_bundle"]["bundle_id"] == NORMALIZATION_BUNDLE_ID
    assert config["output"]["external_bundle"]["manifest_schema"] == BUNDLE_SCHEMA
    assert config["output"]["committed_summary"]["schema"] == SUMMARY_SCHEMA

    assert config["expected_pilot"]["total_rows"] == EXPECTED_TOTAL_ROWS
    assert config["expected_pilot"]["source_rows"] == EXPECTED_SOURCE_ROWS
    assert config["expected_pilot"]["identity_state_counts"] == EXPECTED_IDENTITY_STATE_COUNTS
    assert config["expected_pilot"]["variant_kind_counts"] == EXPECTED_VARIANT_KIND_COUNTS
    assert config["source_rules"]["igvf_sge"]["expected_variant_kinds"] == EXPECTED_SGE_VARIANT_KIND_COUNTS


def test_fn17_committed_pilot_summary_file_matches_published_v1_0_1_contract_and_excludes_sensitive_content() -> None:
    summary_path = REPO_ROOT / "data" / "census" / "tsc2_functional_identity_normalization_pilot_2026-09-11.json"
    if not summary_path.is_file():
        pytest.fail(f"committed pilot summary is missing: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "input_bundle_content_hash",
        "reference_sha256",
        "counts",
        "identity_state_counts",
        "variant_kind_counts",
        "source_row_counts",
        "artifact_integrity",
        "unresolved_reason_counts",
        "normalization_gaps",
    }
    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["bundle_id"] == NORMALIZATION_BUNDLE_ID
    assert summary["manifest_content_hash"] == "74f15f22cfb6e876a8fab3a16c841e6f33317eadd58ef04547e4c060162afb48"
    assert summary["input_bundle_content_hash"] == INPUT_MANIFEST_CONTENT_HASH
    assert summary["reference_sha256"] == REFERENCE_FASTA_SHA256
    assert summary["counts"] == {"sources": 3, "artifacts": 3, "rows": EXPECTED_TOTAL_ROWS}
    assert summary["identity_state_counts"] == EXPECTED_IDENTITY_STATE_COUNTS
    assert summary["variant_kind_counts"] == EXPECTED_VARIANT_KIND_COUNTS
    assert summary["source_row_counts"] == EXPECTED_SOURCE_ROWS
    assert summary["unresolved_reason_counts"] == EXPECTED_UNRESOLVED_REASON_COUNTS
    assert summary["artifact_integrity"] == {
        "mavedb_clipe-normalized-jsonl": {
            "source_id": "mavedb_clipe",
            "sha256": "2328f46bf5a2ae087eddeaa2ad0fb6f44de2b60a2e9e3ad0c034c73907f5031e",
            "byte_length": 102100,
            "row_count": 208,
        },
        "igvf_vamp_seq-normalized-jsonl": {
            "source_id": "igvf_vamp_seq",
            "sha256": "26f34a7a8d52d01ffbdef50427ac1ab0b268a523a29a55ce77452fc56bb83adb",
            "byte_length": 4522418,
            "row_count": 9253,
        },
        "igvf_sge-normalized-jsonl": {
            "source_id": "igvf_sge",
            "sha256": "2292e5770911e13fcd2536287fd04fc7f23354c9bc81ebf01533aa441114ea52",
            "byte_length": 227381,
            "row_count": 453,
        },
    }

    serialized = json.dumps(summary, sort_keys=True)
    lowered = serialized.lower()
    assert '"score_raw"' not in serialized
    assert '"functional_class"' not in serialized
    assert '"requested_url"' not in serialized
    assert '"final_url"' not in serialized
    assert "http://" not in lowered and "https://" not in lowered
    assert "patient" not in lowered
    assert "hgvs_" not in lowered
    assert SPDI_VALUE_PATTERN.search(serialized) is None
    assert not any(token in lowered for token in FORBIDDEN_CLINICAL_TOKENS)
