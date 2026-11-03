from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote, urlsplit

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "src" / "raptor" / "external" / "tsc2_cdna_projector"
OPERATOR_SCRIPT = REPO_ROOT / "scripts" / "fetch_tsc2_clipe_cdna_spdi_projector.py"
CONFIG_PATH = REPO_ROOT / "configs" / "external" / "tsc2_clipe_cdna_spdi_projector_v1.yaml"
SPEC_PATH = (
    REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-clipe-cdna-spdi-projector-acquisition-v1.yaml"
)

MAPPING_ROW_SCHEMA = "raptor.external.clipe_cdna_spdi_mapping_row.v1"
BUNDLE_SCHEMA = "raptor.external.clipe_cdna_spdi_projector_bundle.v1"
SUMMARY_SCHEMA = "raptor.external.clipe_cdna_spdi_projector_summary.v1"

SOURCE_ID = "mavedb_clipe"
SOURCE_BUNDLE_ID = "tsc2-source-pilot-2026-09-09"
SOURCE_MANIFEST_CONTENT_HASH = "63bd6eb4e7182b7f2d345cd78b3a110a59c361c72d521b88990c475919865808"
SCORES_ARTIFACT_ID = "mavedb_clipe-scores-csv"
SCORES_RELATIVE_PATH = "mavedb/mavedb_clipe-scores.csv"
SCORES_SHA256 = "74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717"
SCORES_BYTE_LENGTH = 14277
TOTAL_ROWS = 208
SNV_ROWS = 161
DELINS_ROWS = 47

GENE = "TSC2"
TRANSCRIPT = "NM_000548.5"
GENOMIC_ACCESSION = "NC_000016.10"
ASSEMBLY = "GRCh38"
REFERENCE_FASTA_FILENAME = "NC_000016.10.fasta"
REFERENCE_FASTA_SHA256 = "22dc1bb93de407e0653791c36e4097fbaf64c9efa2510c83b7777f607a61e4d0"

BASE_URL = "https://api.ncbi.nlm.nih.gov/variation/v0"
EXPECTED_HOST = "api.ncbi.nlm.nih.gov"
EXPECTED_BASE_PATH = "/variation/v0"

RUN_NAME = "tsc2-clipe-cdna-spdi-projector-2026-09-12"
BUNDLE_ID = "tsc2-clipe-cdna-spdi-projector-2026-09-12"
SUMMARY_PATH = REPO_ROOT / "data" / "census" / "tsc2_clipe_cdna_spdi_projector_pilot_2026-09-12.json"

SCORES_HEADER = ["accession", "hgvs_nt", "hgvs_splice", "hgvs_pro", "score"]

STATUS_VOCABULARY = {
    "PROJECTED_FASTA_VERIFIED",
    "STEP1_HTTP_ERROR",
    "STEP1_INVALID_HGVS",
    "STEP1_SCHEMA_VIOLATION",
    "STEP1_AMBIGUOUS_SPDIS",
    "STEP1_UNEXPECTED_SEQ_ID",
    "STEP2_HTTP_ERROR",
    "STEP2_SCHEMA_VIOLATION",
    "STEP2_NON_PINNED_GENOME",
    "FASTA_REF_MISMATCH",
    "FASTA_OUT_OF_RANGE",
    "NON_ACGT_ALLELE",
    "TRANSPORT_OR_BINDING_ERROR",
    "OPERATOR_SKIPPED",
}
SHAPE_VOCABULARY = {"SNV", "DELINS"}
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
NON_RETRYABLE_HTTP = {400, 401, 403, 404, 422}
MIN_INTERVAL_SECONDS = 1.0
MAX_ATTEMPTS = 4

FORBIDDEN_IMPORT_PREFIXES = (
    "raptor.scorer",
    "raptor.eval",
    "raptor.packet",
    "raptor.census",
    "raptor.kb",
    "raptor.atlas",
    "raptor.rescuescreen",
)
FORBIDDEN_NETWORK_IMPORTS = ("urllib.request", "requests", "httpx", "aiohttp")
FORBIDDEN_TEXT_TOKENS = ("classification", "pathogenic", "benign", "ps3", "bs3", "patient")


def _load_module(module_name: str):
    try:
        return import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"TSC2 cliPE projector module {module_name!r} is not implemented: {exc}")


def _symbol(module: Any, symbol_name: str):
    if not hasattr(module, symbol_name):
        pytest.fail(
            f"TSC2 cliPE projector module {module.__name__!r} is missing public symbol {symbol_name!r}"
        )
    return getattr(module, symbol_name)


def _endpoint_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_cdna_projector.endpoint")
    return {
        "ProjectorEndpointSecurityError": _symbol(module, "ProjectorEndpointSecurityError"),
        "ProjectorTransportValidationError": _symbol(module, "ProjectorTransportValidationError"),
        "build_step1_hgvs_contextuals_url": _symbol(module, "build_step1_hgvs_contextuals_url"),
        "build_step2_spdi_canonical_representative_url": _symbol(
            module, "build_step2_spdi_canonical_representative_url"
        ),
        "build_step3_spdi_hgvs_url": _symbol(module, "build_step3_spdi_hgvs_url"),
        "assert_allowed_projector_final_url": _symbol(module, "assert_allowed_projector_final_url"),
        "fetch_raw_with_transport": _symbol(module, "fetch_raw_with_transport"),
        "fetch_with_transport": _symbol(module, "fetch_with_transport"),
    }


def _parse_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_cdna_projector.parse")
    return {
        "Step1SchemaError": _symbol(module, "Step1SchemaError"),
        "Step2SchemaError": _symbol(module, "Step2SchemaError"),
        "parse_step1_contextuals_response": _symbol(module, "parse_step1_contextuals_response"),
        "parse_step2_canonical_representative_response": _symbol(
            module, "parse_step2_canonical_representative_response"
        ),
    }


def _model_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_cdna_projector.model")
    return {
        "CLIPE_CDNA_SPDI_MAPPING_ROW_SCHEMA": _symbol(module, "CLIPE_CDNA_SPDI_MAPPING_ROW_SCHEMA"),
        "ALLOWED_MAPPING_STATUSES": _symbol(module, "ALLOWED_MAPPING_STATUSES"),
        "ALLOWED_VARIANT_SHAPES": _symbol(module, "ALLOWED_VARIANT_SHAPES"),
        "ProjectionContractError": _symbol(module, "ProjectionContractError"),
        "ClipeCdnaSpdiMappingRow": _symbol(module, "ClipeCdnaSpdiMappingRow"),
    }


def _ingest_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_cdna_projector.ingest")
    return {
        "ProjectorAcquisitionError": _symbol(module, "ProjectorAcquisitionError"),
        "FrozenInputError": _symbol(module, "FrozenInputError"),
        "ReferenceIntegrityError": _symbol(module, "ReferenceIntegrityError"),
        "validate_frozen_scores_input": _symbol(module, "validate_frozen_scores_input"),
        "validate_reference_fasta_checksum": _symbol(module, "validate_reference_fasta_checksum"),
        "project_clipe_rows": _symbol(module, "project_clipe_rows"),
    }


def _source_bundle_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.bundle")
    return {
        "build_bundle_manifest": _symbol(module, "build_bundle_manifest"),
        "compute_bundle_content_hash": _symbol(module, "compute_bundle_content_hash"),
    }


def _bundle_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_cdna_projector.bundle")
    return {
        "ProjectorBundleBoundaryError": _symbol(module, "ProjectorBundleBoundaryError"),
        "ProjectorManifestError": _symbol(module, "ProjectorManifestError"),
        "canonical_mapping_jsonl_bytes": _symbol(module, "canonical_mapping_jsonl_bytes"),
        "canonical_request_index_jsonl_bytes": _symbol(module, "canonical_request_index_jsonl_bytes"),
        "compute_manifest_content_hash": _symbol(module, "compute_manifest_content_hash"),
        "validate_manifest_content_hash": _symbol(module, "validate_manifest_content_hash"),
        "build_projector_bundle_manifest": _symbol(module, "build_projector_bundle_manifest"),
        "publish_projector_bundle": _symbol(module, "publish_projector_bundle"),
        "build_committed_summary": _symbol(module, "build_committed_summary"),
        "_publish_directory_no_replace": _symbol(module, "_publish_directory_no_replace"),
    }


def _load_operator_module():
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 cliPE projector operator script is not implemented: {OPERATOR_SCRIPT}")
    spec = importlib.util.spec_from_file_location("raptor_tsc2_cdna_projector_operator_module", OPERATOR_SCRIPT)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load operator module spec from {OPERATOR_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.module, node.lineno))
    return imports


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _md5(blob: bytes) -> str:
    return hashlib.md5(blob).hexdigest()  # nosec B303 - pinned upstream md5 compatibility


def _scores_csv(rows: list[list[str]]) -> str:
    lines = [",".join(SCORES_HEADER)]
    lines.extend(",".join(str(value) for value in row) for row in rows)
    return "\n".join(lines) + "\n"


def _minimal_mapping_row(*, source_row: int, shape: str = "SNV", status: str = "PROJECTED_FASTA_VERIFIED") -> dict[str, Any]:
    if shape == "SNV":
        hgvs_nt = "c.1600G>A"
        tx_spdi = "NM_000548.5:1709:G:A"
        genomic_spdi = "NC_000016.10:2065518:G:A"
        hgvs_g = "NC_000016.10:g.2065519G>A"
        observed = "G"
    else:
        hgvs_nt = "c.1627_1629delinsTGA"
        tx_spdi = "NM_000548.5:1736:CCG:TGA"
        genomic_spdi = "NC_000016.10:2065545:CCG:TGA"
        hgvs_g = "NC_000016.10:g.2065546_2065548delinsTGA"
        observed = "CCG"
    return {
        "schema": MAPPING_ROW_SCHEMA,
        "source_id": SOURCE_ID,
        "source_row": source_row,
        "source_record_id": f"urn:mavedb:00001201-a-1#{source_row}",
        "gene": GENE,
        "transcript": TRANSCRIPT,
        "hgvs_c": f"{TRANSCRIPT}:{hgvs_nt}",
        "hgvs_nt_source": hgvs_nt,
        "tx_spdi": tx_spdi if status == "PROJECTED_FASTA_VERIFIED" else None,
        "genomic_spdi": genomic_spdi if status == "PROJECTED_FASTA_VERIFIED" else None,
        "hgvs_g": hgvs_g if status == "PROJECTED_FASTA_VERIFIED" else None,
        "assembly": ASSEMBLY if status == "PROJECTED_FASTA_VERIFIED" else None,
        "genomic_accession": GENOMIC_ACCESSION if status == "PROJECTED_FASTA_VERIFIED" else None,
        "status": status,
        "fasta_deleted_observed": observed if status == "PROJECTED_FASTA_VERIFIED" else None,
        "error_detail": None if status == "PROJECTED_FASTA_VERIFIED" else "sanitized",
        "step1_body_sha256": "a" * 64,
        "step2_body_sha256": "b" * 64,
        "variant_shape": shape,
    }


def _minimal_request_index_row(*, source_row: int, step: str, requested_url: str, final_url: str) -> dict[str, Any]:
    body = json.dumps({"ok": True, "step": step, "source_row": source_row}, separators=(",", ":")).encode("utf-8")
    return {
        "source_row": source_row,
        "step": step,
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": 200,
        "body_sha256": _sha256(body),
        "elapsed_ms": 123,
    }


def _step1_payload(*, seq_id: str = TRANSCRIPT, position: int = 1709, deleted: str = "G", inserted: str = "A") -> bytes:
    payload = {
        "data": {
            "input_hgvs_validity": "valid",
            "spdis": [
                {
                    "seq_id": seq_id,
                    "position": position,
                    "deleted_sequence": deleted,
                    "inserted_sequence": inserted,
                }
            ],
        }
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _step2_payload(
    *, seq_id: str = GENOMIC_ACCESSION, position: int = 2065518, deleted: str = "G", inserted: str = "A"
) -> bytes:
    payload = {
        "data": {
            "seq_id": seq_id,
            "position": position,
            "deleted_sequence": deleted,
            "inserted_sequence": inserted,
        }
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _source_artifact_record(*, artifact_id: str, source_id: str, relative_path: str, payload: bytes) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "source_id": source_id,
        "role": "TEST_ARTIFACT",
        "requested_url": f"https://example.invalid/{artifact_id}",
        "final_url": f"https://example.invalid/{artifact_id}",
        "http_status": 200,
        "media_type": "text/csv",
        "relative_path": relative_path,
        "byte_length": len(payload),
        "sha256": _sha256(payload),
        "md5": _md5(payload),
        "fetched_at": "2026-09-12T00:00:00Z",
        "verification": "HASHED",
    }


def _source_record(*, source_id: str, artifact_ids: list[str]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_kind": "functional",
        "lifecycle_state": "STAGED_VERIFIED",
        "access_state": "PUBLIC",
        "licence_state": "PUBLIC_METADATA",
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "identifiers": {"primary": source_id},
        "artifact_ids": artifact_ids,
        "observations": {},
        "limitations": [],
    }


def _build_synthetic_source_bundle_manifest(
    *,
    scores_payload: bytes,
    artifacts: list[dict[str, Any]] | None = None,
    bundle_id: str = SOURCE_BUNDLE_ID,
) -> dict[str, Any]:
    source_bundle_api = _source_bundle_api()
    if artifacts is None:
        artifacts = [
            _source_artifact_record(
                artifact_id=SCORES_ARTIFACT_ID,
                source_id=SOURCE_ID,
                relative_path=SCORES_RELATIVE_PATH,
                payload=scores_payload,
            )
        ]
    sources = [_source_record(source_id=SOURCE_ID, artifact_ids=[item["artifact_id"] for item in artifacts])]
    manifest = source_bundle_api["build_bundle_manifest"](
        bundle_id=bundle_id,
        created_at="2026-09-12T00:00:00Z",
        query={"q": "synthetic"},
        artifacts=artifacts,
        sources=sources,
        truncation={},
        boundaries={"network": "injected", "external_output_only": True},
    )
    return manifest


def _valid_projector_manifest_and_payloads(bundle_api: dict[str, Any]) -> tuple[dict[str, Any], bytes, bytes, dict[str, bytes]]:
    mapping_rows = [_minimal_mapping_row(source_row=1, shape="SNV"), _minimal_mapping_row(source_row=2, shape="DELINS")]
    mapping_payload = bundle_api["canonical_mapping_jsonl_bytes"](mapping_rows)
    request_rows = [
        _minimal_request_index_row(
            source_row=1,
            step="step1",
            requested_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals",
            final_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals",
        ),
        _minimal_request_index_row(
            source_row=1,
            step="step2",
            requested_url=f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
            final_url=f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
        ),
        _minimal_request_index_row(
            source_row=2,
            step="step1",
            requested_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1627_1629delinsTGA', safe='')}/contextuals",
            final_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1627_1629delinsTGA', safe='')}/contextuals",
        ),
        _minimal_request_index_row(
            source_row=2,
            step="step2",
            requested_url=f"{BASE_URL}/spdi/{quote('NM_000548.5:1736:CCG:TGA', safe='')}/canonical_representative",
            final_url=f"{BASE_URL}/spdi/{quote('NM_000548.5:1736:CCG:TGA', safe='')}/canonical_representative",
        ),
    ]
    request_payload = bundle_api["canonical_request_index_jsonl_bytes"](request_rows)

    raw_payloads = {
        "raw/step1/0001-contextuals.json": _step1_payload(),
        "raw/step2/0001-canonical_representative.json": _step2_payload(),
        "raw/step1/0002-contextuals.json": _step1_payload(position=1736, deleted="CCG", inserted="TGA"),
        "raw/step2/0002-canonical_representative.json": _step2_payload(position=2065545, deleted="CCG", inserted="TGA"),
    }
    artifacts = [
        {
            "artifact_id": "mapping-jsonl",
            "relative_path": "mapping/mavedb_clipe_nm000548_5_to_nc000016_10.jsonl",
            "byte_length": len(mapping_payload),
            "sha256": _sha256(mapping_payload),
            "row_count": 2,
        },
        {
            "artifact_id": "request-index-jsonl",
            "relative_path": "logs/request_index.jsonl",
            "byte_length": len(request_payload),
            "sha256": _sha256(request_payload),
            "row_count": 4,
        },
        {
            "artifact_id": "raw-step1-0001",
            "relative_path": "raw/step1/0001-contextuals.json",
            "byte_length": len(raw_payloads["raw/step1/0001-contextuals.json"]),
            "sha256": _sha256(raw_payloads["raw/step1/0001-contextuals.json"]),
            "row_count": 1,
        },
        {
            "artifact_id": "raw-step2-0001",
            "relative_path": "raw/step2/0001-canonical_representative.json",
            "byte_length": len(raw_payloads["raw/step2/0001-canonical_representative.json"]),
            "sha256": _sha256(raw_payloads["raw/step2/0001-canonical_representative.json"]),
            "row_count": 1,
        },
        {
            "artifact_id": "raw-step1-0002",
            "relative_path": "raw/step1/0002-contextuals.json",
            "byte_length": len(raw_payloads["raw/step1/0002-contextuals.json"]),
            "sha256": _sha256(raw_payloads["raw/step1/0002-contextuals.json"]),
            "row_count": 1,
        },
        {
            "artifact_id": "raw-step2-0002",
            "relative_path": "raw/step2/0002-canonical_representative.json",
            "byte_length": len(raw_payloads["raw/step2/0002-canonical_representative.json"]),
            "sha256": _sha256(raw_payloads["raw/step2/0002-canonical_representative.json"]),
            "row_count": 1,
        },
    ]

    manifest = bundle_api["build_projector_bundle_manifest"](
        bundle_id=BUNDLE_ID,
        created_at="2026-09-12T00:00:00Z",
        input_scores={
            "artifact_id": SCORES_ARTIFACT_ID,
            "sha256": SCORES_SHA256,
            "byte_length": SCORES_BYTE_LENGTH,
            "row_count": 2,
        },
        reference={"accession": GENOMIC_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        endpoint_pins={
            "base_url": BASE_URL,
            "step_sequence": ["contextuals", "canonical_representative"],
            "min_interval_seconds": MIN_INTERVAL_SECONDS,
        },
        artifacts=artifacts,
        status_counts={"PROJECTED_FASTA_VERIFIED": 2},
        shape_counts={"SNV": 1, "DELINS": 1},
        success_count=2,
        failure_count=0,
        boundaries={
            "network": "operator_only",
            "clinical_use": "forbidden",
            "evidence_strength_use": "forbidden",
        },
    )
    return manifest, mapping_payload, request_payload, raw_payloads


def test_cp00_binding_spec_exists_and_is_v1_0_6() -> None:
    if not SPEC_PATH.is_file():
        pytest.fail(f"binding spec is missing: {SPEC_PATH}")
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["spec_id"] == "raptor-v2-clipe-cdna-spdi-projector-acquisition-v1"
    assert spec["spec_version"] == "1.0.6"


def test_cp01_endpoint_url_builders_percent_encode_whole_path_segment_no_query_and_pin_resource() -> None:
    api = _endpoint_api()
    hgvs_c = "NM_000548.5:c.1600G>A"
    tx_spdi = "NM_000548.5:1709:G:A"
    genomic_spdi = "NC_000016.10:2065518:G:A"

    step1 = api["build_step1_hgvs_contextuals_url"](hgvs_c=hgvs_c)
    step2 = api["build_step2_spdi_canonical_representative_url"](spdi=tx_spdi)
    step3 = api["build_step3_spdi_hgvs_url"](spdi=genomic_spdi)

    assert step1 == f"{BASE_URL}/hgvs/{quote(hgvs_c, safe='')}/contextuals"
    assert step2 == f"{BASE_URL}/spdi/{quote(tx_spdi, safe='')}/canonical_representative"
    assert step3 == f"{BASE_URL}/spdi/{quote(genomic_spdi, safe='')}/hgvs"

    for url, expected_resource in ((step1, hgvs_c), (step2, tx_spdi), (step3, genomic_spdi)):
        parts = urlsplit(url)
        assert parts.scheme == "https"
        assert parts.netloc == EXPECTED_HOST
        assert parts.path.startswith(EXPECTED_BASE_PATH + "/")
        assert parts.query == ""
        encoded_resource = parts.path.split("/")[4]
        assert unquote(encoded_resource) == expected_resource


def test_cp02_final_url_allowlist_and_resource_binding_enforced_across_redirects() -> None:
    api = _endpoint_api()
    requested = f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals"
    api["assert_allowed_projector_final_url"](requested_url=requested, final_url=requested)

    err = api["ProjectorEndpointSecurityError"]
    with pytest.raises(err):
        api["assert_allowed_projector_final_url"](
            requested_url=requested,
            final_url=requested.replace("https://api.ncbi.nlm.nih.gov", "https://evil.example.org"),
        )
    with pytest.raises(err):
        api["assert_allowed_projector_final_url"](
            requested_url=requested, final_url=requested.replace("/contextuals", "/canonical_representative")
        )
    with pytest.raises(err):
        api["assert_allowed_projector_final_url"](
            requested_url=requested, final_url=requested.replace("1600G%3EA", "1600A%3EG")
        )
    with pytest.raises(err):
        api["assert_allowed_projector_final_url"](
            requested_url=requested, final_url=requested + "?api_key=SECRET"
        )


def test_cp03_reject_direct_hgvs_canonical_and_batch_contextuals_endpoints() -> None:
    api = _endpoint_api()
    err = api["ProjectorEndpointSecurityError"]
    direct = f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/canonical_representative"
    batch = f"{BASE_URL}/hgvs/batch/contextuals"
    with pytest.raises(err):
        api["assert_allowed_projector_final_url"](requested_url=direct, final_url=direct)
    with pytest.raises(err):
        api["assert_allowed_projector_final_url"](requested_url=batch, final_url=batch)


def test_cp04_fetch_with_transport_requires_typed_200_bytes_media_and_sanitizes_transport_errors() -> None:
    api = _endpoint_api()
    requested = f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals"
    body = _step1_payload()

    def ok_transport(_url: str) -> dict[str, Any]:
        return {
            "final_url": requested,
            "http_status": 200,
            "media_type": "application/json; charset=utf-8",
            "body": body,
        }

    result = api["fetch_with_transport"](requested_url=requested, transport=ok_transport)
    assert result["requested_url"] == requested
    assert result["final_url"] == requested
    assert result["http_status"] == 200
    assert result["media_type"].startswith("application/json")
    assert result["byte_length"] == len(body)
    assert result["sha256"] == _sha256(body)

    err = api["ProjectorTransportValidationError"]
    for malformed in (
        {"http_status": 200, "media_type": "application/json", "body": body},
        {"final_url": requested, "http_status": 500, "media_type": "application/json", "body": body},
        {"final_url": requested, "http_status": 200, "media_type": "", "body": body},
        {"final_url": requested, "http_status": 200, "media_type": "application/json", "body": "not-bytes"},
    ):
        with pytest.raises(err):
            api["fetch_with_transport"](requested_url=requested, transport=lambda _url, m=malformed: m)

    class SecretTransportError(RuntimeError):
        pass

    def bad_transport(_url: str) -> dict[str, Any]:
        raise SecretTransportError("api_key=SECRET should not leak")

    with pytest.raises(err) as raised:
        api["fetch_with_transport"](requested_url=requested, transport=bad_transport)
    assert "SECRET" not in str(raised.value)


def test_cp04b_transport_response_headers_are_optional_mapping_and_typed_if_present() -> None:
    api = _endpoint_api()
    requested = f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals"
    body = _step1_payload()

    result = api["fetch_raw_with_transport"](
        requested_url=requested,
        transport=lambda _url: {
            "final_url": requested,
            "http_status": 429,
            "media_type": "application/json",
            "body": body,
            "response_headers": {"Retry-After": "3", "X-Trace": "abc"},
        },
    )
    assert result["http_status"] == 429
    assert result.get("response_headers") == {"Retry-After": "3", "X-Trace": "abc"}

    err = api["ProjectorTransportValidationError"]
    malformed_headers = (
        ["Retry-After: 3"],
        "Retry-After: 3",
        {"Retry-After": 3},
        {1: "3"},
        {"Retry-After": None},
    )
    for headers in malformed_headers:
        with pytest.raises(err):
            api["fetch_raw_with_transport"](
                requested_url=requested,
                transport=lambda _url, h=headers: {
                    "final_url": requested,
                    "http_status": 429,
                    "media_type": "application/json",
                    "body": body,
                    "response_headers": h,
                },
            )


def test_cp05_step1_parser_requires_valid_single_transcript_spdi_and_acgt_alleles() -> None:
    api = _parse_api()
    parsed = api["parse_step1_contextuals_response"](
        body=_step1_payload(), media_type="application/json", expected_seq_id=TRANSCRIPT
    )
    assert parsed["seq_id"] == TRANSCRIPT
    assert parsed["position"] == 1709
    assert parsed["deleted_sequence"] == "G"
    assert parsed["inserted_sequence"] == "A"
    assert parsed["spdi"] == "NM_000548.5:1709:G:A"

    err = api["Step1SchemaError"]
    with pytest.raises(err):
        api["parse_step1_contextuals_response"](
            body=json.dumps({"data": {"input_hgvs_validity": "invalid", "spdis": []}}).encode("utf-8"),
            media_type="application/json",
            expected_seq_id=TRANSCRIPT,
        )
    with pytest.raises(err):
        api["parse_step1_contextuals_response"](
            body=json.dumps(
                {
                    "data": {
                        "input_hgvs_validity": "valid",
                        "spdis": [
                            {"seq_id": TRANSCRIPT, "position": 1, "deleted_sequence": "A", "inserted_sequence": "G"},
                            {"seq_id": TRANSCRIPT, "position": 2, "deleted_sequence": "C", "inserted_sequence": "T"},
                        ],
                    }
                }
            ).encode("utf-8"),
            media_type="application/json",
            expected_seq_id=TRANSCRIPT,
        )
    with pytest.raises(err):
        api["parse_step1_contextuals_response"](
            body=_step1_payload(seq_id="NM_000548.4"), media_type="application/json", expected_seq_id=TRANSCRIPT
        )
    with pytest.raises(err):
        api["parse_step1_contextuals_response"](
            body=_step1_payload(position=-1), media_type="application/json", expected_seq_id=TRANSCRIPT
        )
    with pytest.raises(err):
        api["parse_step1_contextuals_response"](
            body=_step1_payload(deleted="n", inserted="A"), media_type="application/json", expected_seq_id=TRANSCRIPT
        )


def test_cp05b_step1_parser_rejects_nested_warnings_and_empty_alleles() -> None:
    api = _parse_api()
    err = api["Step1SchemaError"]
    with pytest.raises(err):
        api["parse_step1_contextuals_response"](
            body=json.dumps(
                {
                    "data": {
                        "input_hgvs_validity": "valid",
                        "warnings": [{"message": "cross-exon projection warning"}],
                        "spdis": [
                            {
                                "seq_id": TRANSCRIPT,
                                "position": 1709,
                                "deleted_sequence": "G",
                                "inserted_sequence": "A",
                            }
                        ],
                    }
                }
            ).encode("utf-8"),
            media_type="application/json",
            expected_seq_id=TRANSCRIPT,
        )
    with pytest.raises(err):
        api["parse_step1_contextuals_response"](
            body=json.dumps(
                {
                    "data": {
                        "input_hgvs_validity": "valid",
                        "spdis": [
                            {
                                "seq_id": TRANSCRIPT,
                                "position": 1709,
                                "deleted_sequence": "G",
                                "inserted_sequence": "A",
                                "warnings": [{"message": "cross-exon projection warning"}],
                            }
                        ],
                    }
                }
            ).encode("utf-8"),
            media_type="application/json",
            expected_seq_id=TRANSCRIPT,
        )
    for deleted, inserted in (("", "A"), ("G", "")):
        with pytest.raises(err):
            api["parse_step1_contextuals_response"](
                body=_step1_payload(deleted=deleted, inserted=inserted),
                media_type="application/json",
                expected_seq_id=TRANSCRIPT,
            )


def test_cp06_step2_parser_requires_pinned_genome_and_rejects_transcript_or_warning_payloads() -> None:
    api = _parse_api()
    parsed = api["parse_step2_canonical_representative_response"](
        body=_step2_payload(), media_type="application/json", expected_seq_id=GENOMIC_ACCESSION
    )
    assert parsed["seq_id"] == GENOMIC_ACCESSION
    assert parsed["position"] == 2065518
    assert parsed["deleted_sequence"] == "G"
    assert parsed["inserted_sequence"] == "A"
    assert parsed["spdi"] == "NC_000016.10:2065518:G:A"

    err = api["Step2SchemaError"]
    with pytest.raises(err):
        api["parse_step2_canonical_representative_response"](
            body=_step2_payload(seq_id=TRANSCRIPT), media_type="application/json", expected_seq_id=GENOMIC_ACCESSION
        )
    with pytest.raises(err):
        api["parse_step2_canonical_representative_response"](
            body=json.dumps({"data": {"seq_id": GENOMIC_ACCESSION, "position": 1, "deleted_sequence": "A"}}).encode(
                "utf-8"
            ),
            media_type="application/json",
            expected_seq_id=GENOMIC_ACCESSION,
        )
    with pytest.raises(err):
        api["parse_step2_canonical_representative_response"](
            body=json.dumps(
                {
                    "warnings": [{"message": "alignment drift"}],
                    "data": {"seq_id": GENOMIC_ACCESSION, "position": 1, "deleted_sequence": "A", "inserted_sequence": "G"},
                }
            ).encode("utf-8"),
            media_type="application/json",
            expected_seq_id=GENOMIC_ACCESSION,
        )


def test_cp06b_step2_parser_rejects_nested_warnings_and_empty_alleles() -> None:
    api = _parse_api()
    err = api["Step2SchemaError"]
    with pytest.raises(err):
        api["parse_step2_canonical_representative_response"](
            body=json.dumps(
                {
                    "data": {
                        "warnings": [{"message": "cross-exon projection warning"}],
                        "seq_id": GENOMIC_ACCESSION,
                        "position": 2065518,
                        "deleted_sequence": "G",
                        "inserted_sequence": "A",
                    }
                }
            ).encode("utf-8"),
            media_type="application/json",
            expected_seq_id=GENOMIC_ACCESSION,
        )
    for deleted, inserted in (("", "A"), ("G", "")):
        with pytest.raises(err):
            api["parse_step2_canonical_representative_response"](
                body=_step2_payload(deleted=deleted, inserted=inserted),
                media_type="application/json",
                expected_seq_id=GENOMIC_ACCESSION,
            )


def test_cp07_mapping_row_contract_supports_snv_and_delins_and_retains_failure_rows() -> None:
    api = _model_api()
    assert api["CLIPE_CDNA_SPDI_MAPPING_ROW_SCHEMA"] == MAPPING_ROW_SCHEMA
    assert set(api["ALLOWED_MAPPING_STATUSES"]) == STATUS_VOCABULARY
    assert set(api["ALLOWED_VARIANT_SHAPES"]) == SHAPE_VOCABULARY

    snv = _minimal_mapping_row(source_row=1, shape="SNV")
    delins = _minimal_mapping_row(source_row=2, shape="DELINS")
    failure = _minimal_mapping_row(source_row=3, shape="SNV", status="STEP1_INVALID_HGVS")
    assert [snv["source_row"], delins["source_row"], failure["source_row"]] == [1, 2, 3]
    assert failure["tx_spdi"] is None and failure["genomic_spdi"] is None

    constructed = [
        api["ClipeCdnaSpdiMappingRow"](**snv).to_dict(),
        api["ClipeCdnaSpdiMappingRow"](**delins).to_dict(),
        api["ClipeCdnaSpdiMappingRow"](**failure).to_dict(),
    ]
    assert [row["source_row"] for row in constructed] == [1, 2, 3]
    assert [row["source_record_id"] for row in constructed] == [
        "urn:mavedb:00001201-a-1#1",
        "urn:mavedb:00001201-a-1#2",
        "urn:mavedb:00001201-a-1#3",
    ]


def test_cp08_reference_checksum_is_verified_before_any_request_attempt() -> None:
    api = _ingest_api()
    scores_rows = [
        ["urn:mavedb:00001201-a-1#1", "c.1600G>A", "", "p.Gly534Arg", "0.21"],
        ["urn:mavedb:00001201-a-1#2", "c.1627_1629delinsTGA", "", "p.Pro543Ter", "-0.30"],
    ]
    scores_csv = _scores_csv(scores_rows).encode("utf-8")

    calls: list[str] = []

    def transport(_url: str) -> dict[str, Any]:
        calls.append("transport")
        return {
            "final_url": "https://api.ncbi.nlm.nih.gov/variation/v0/hgvs/NM_000548.5%3Ac.1600G%3EA/contextuals",
            "http_status": 200,
            "media_type": "application/json",
            "body": _step1_payload(),
        }

    with pytest.raises(api["ReferenceIntegrityError"]):
        api["project_clipe_rows"](
            source_id=SOURCE_ID,
            scores_csv_bytes=scores_csv,
            expected_header=SCORES_HEADER,
            expected_rows=2,
            expected_scores_sha256=_sha256(scores_csv),
            expected_scores_byte_length=len(scores_csv),
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
            reference_fasta_path=Path("missing.fasta"),
            expected_reference_sha256="0" * 64,
            transport=transport,
            min_interval_seconds=MIN_INTERVAL_SECONDS,
            retry_policy={
                "retryable_http": sorted(RETRYABLE_HTTP),
                "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
                "max_attempts_per_request": MAX_ATTEMPTS,
            },
            sleep=lambda _seconds: None,
        )
    assert calls == []


def test_cp08b_project_clipe_rows_successful_snv_and_delins_flow_is_ordered_and_conservative(tmp_path: Path) -> None:
    api = _ingest_api()
    scores_rows = [
        ["urn:mavedb:00001201-a-1#1", "c.1600G>A", "", "p.Gly534Arg", "0.21"],
        ["urn:mavedb:00001201-a-1#2", "c.1627_1629delinsTGA", "", "p.Pro543Ter", "-0.30"],
    ]
    scores_csv_text = _scores_csv(scores_rows)
    scores_payload = scores_csv_text.encode("utf-8")
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)

    step1_snv = _step1_payload()
    step2_snv = _step2_payload()
    step1_delins = _step1_payload(position=1736, deleted="CCG", inserted="TGA")
    step2_delins = _step2_payload(position=2065545, deleted="CCG", inserted="TGA")
    responses = [
        {
            "final_url": f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals",
            "http_status": 200,
            "media_type": "application/json; charset=utf-8",
            "body": step1_snv,
        },
        {
            "final_url": f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
            "http_status": 200,
            "media_type": "application/json; charset=utf-8",
            "body": step2_snv,
        },
        {
            "final_url": f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1627_1629delinsTGA', safe='')}/contextuals",
            "http_status": 200,
            "media_type": "application/json; charset=utf-8",
            "body": step1_delins,
        },
        {
            "final_url": f"{BASE_URL}/spdi/{quote('NM_000548.5:1736:CCG:TGA', safe='')}/canonical_representative",
            "http_status": 200,
            "media_type": "application/json; charset=utf-8",
            "body": step2_delins,
        },
    ]
    requested_urls: list[str] = []

    def transport(url: str) -> dict[str, Any]:
        requested_urls.append(url)
        return deepcopy(responses[len(requested_urls) - 1])

    fasta_checks: list[tuple[str, int, str]] = []

    def fasta_deleted_allele_checker(*, accession: str, position: int, deleted_sequence: str) -> str:
        fasta_checks.append((accession, position, deleted_sequence))
        return deleted_sequence

    result = api["project_clipe_rows"](
        source_id=SOURCE_ID,
        scores_csv_bytes=scores_payload,
        expected_header=SCORES_HEADER,
        expected_rows=2,
        expected_scores_sha256=_sha256(scores_payload),
        expected_scores_byte_length=len(scores_payload),
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        transport=transport,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": MAX_ATTEMPTS,
        },
        sleep=lambda _seconds: None,
        fasta_deleted_allele_checker=fasta_deleted_allele_checker,
    )
    assert requested_urls == [
        f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals",
        f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
        f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1627_1629delinsTGA', safe='')}/contextuals",
        f"{BASE_URL}/spdi/{quote('NM_000548.5:1736:CCG:TGA', safe='')}/canonical_representative",
    ]
    assert fasta_checks == [
        (GENOMIC_ACCESSION, 2065518, "G"),
        (GENOMIC_ACCESSION, 2065545, "CCG"),
    ]

    rows = result["mapping_rows"]
    assert [row["source_row"] for row in rows] == [1, 2]
    assert [row["status"] for row in rows] == ["PROJECTED_FASTA_VERIFIED", "PROJECTED_FASTA_VERIFIED"]
    assert [row["tx_spdi"] for row in rows] == ["NM_000548.5:1709:G:A", "NM_000548.5:1736:CCG:TGA"]
    assert [row["genomic_spdi"] for row in rows] == ["NC_000016.10:2065518:G:A", "NC_000016.10:2065545:CCG:TGA"]
    assert [row["step1_body_sha256"] for row in rows] == [_sha256(step1_snv), _sha256(step1_delins)]
    assert [row["step2_body_sha256"] for row in rows] == [_sha256(step2_snv), _sha256(step2_delins)]
    assert len({row["source_row"] for row in rows}) == 2

    request_index = result["request_index"]
    assert len(request_index) == 4
    assert [(entry["source_row"], entry["step"]) for entry in request_index] == [
        (1, "step1"),
        (1, "step2"),
        (2, "step1"),
        (2, "step2"),
    ]
    assert result["status_counts"] == {"PROJECTED_FASTA_VERIFIED": 2}
    assert result["shape_counts"] == {"SNV": 1, "DELINS": 1}


def test_cp08c_project_clipe_rows_retains_permanent_step1_failure_and_continues_to_later_success(
    tmp_path: Path,
) -> None:
    api = _ingest_api()
    scores_rows = [
        ["urn:mavedb:00001201-a-1#1", "c.1600A>G", "", "p.Gly534Arg", "0.21"],
        ["urn:mavedb:00001201-a-1#2", "c.1600G>A", "", "p.Gly534Arg", "0.20"],
    ]
    scores_csv_text = _scores_csv(scores_rows)
    scores_payload = scores_csv_text.encode("utf-8")
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)

    invalid_step1 = json.dumps({"data": {"input_hgvs_validity": "invalid", "spdis": []}}, separators=(",", ":")).encode(
        "utf-8"
    )
    valid_step1 = _step1_payload()
    valid_step2 = _step2_payload()
    responses = [
        {
            "final_url": f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600A>G', safe='')}/contextuals",
            "http_status": 200,
            "media_type": "application/json; charset=utf-8",
            "body": invalid_step1,
        },
        {
            "final_url": f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals",
            "http_status": 200,
            "media_type": "application/json; charset=utf-8",
            "body": valid_step1,
        },
        {
            "final_url": f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
            "http_status": 200,
            "media_type": "application/json; charset=utf-8",
            "body": valid_step2,
        },
    ]
    requested_urls: list[str] = []

    def transport(url: str) -> dict[str, Any]:
        requested_urls.append(url)
        return deepcopy(responses[len(requested_urls) - 1])

    fasta_checks: list[tuple[str, int, str]] = []

    def fasta_deleted_allele_checker(*, accession: str, position: int, deleted_sequence: str) -> str:
        fasta_checks.append((accession, position, deleted_sequence))
        return deleted_sequence

    result = api["project_clipe_rows"](
        source_id=SOURCE_ID,
        scores_csv_bytes=scores_payload,
        expected_header=SCORES_HEADER,
        expected_rows=2,
        expected_scores_sha256=_sha256(scores_payload),
        expected_scores_byte_length=len(scores_payload),
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        transport=transport,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": MAX_ATTEMPTS,
        },
        sleep=lambda _seconds: None,
        fasta_deleted_allele_checker=fasta_deleted_allele_checker,
    )
    assert requested_urls == [
        f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600A>G', safe='')}/contextuals",
        f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals",
        f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
    ]
    assert fasta_checks == [(GENOMIC_ACCESSION, 2065518, "G")]

    rows = result["mapping_rows"]
    assert [row["source_row"] for row in rows] == [1, 2]
    assert [row["status"] for row in rows] == ["STEP1_INVALID_HGVS", "PROJECTED_FASTA_VERIFIED"]
    assert rows[0]["tx_spdi"] is None and rows[0]["genomic_spdi"] is None
    assert rows[1]["genomic_spdi"] == "NC_000016.10:2065518:G:A"
    assert result["status_counts"] == {"STEP1_INVALID_HGVS": 1, "PROJECTED_FASTA_VERIFIED": 1}
    assert result["shape_counts"] == {"SNV": 2}
    assert len(result["request_index"]) == 3
    assert [(entry["source_row"], entry["step"]) for entry in result["request_index"]] == [
        (1, "step1"),
        (2, "step1"),
        (2, "step2"),
    ]


def test_cp08d_retryable_http_500_is_retried_then_succeeds(tmp_path: Path) -> None:
    api = _ingest_api()
    scores_csv_text = _scores_csv([["urn:mavedb:00001201-a-1#1", "c.1600G>A", "", "p.Gly534Arg", "0.21"]])
    scores_payload = scores_csv_text.encode("utf-8")
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)

    requested_urls: list[str] = []
    sleep_calls: list[float] = []
    attempts = {"count": 0}

    def transport(url: str) -> dict[str, Any]:
        requested_urls.append(url)
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {
                "final_url": url,
                "http_status": 500,
                "media_type": "application/json",
                "body": b'{"error":"temporary"}',
            }
        if attempts["count"] == 2:
            return {"final_url": url, "http_status": 200, "media_type": "application/json", "body": _step1_payload()}
        return {"final_url": url, "http_status": 200, "media_type": "application/json", "body": _step2_payload()}

    result = api["project_clipe_rows"](
        source_id=SOURCE_ID,
        scores_csv_bytes=scores_payload,
        expected_header=SCORES_HEADER,
        expected_rows=1,
        expected_scores_sha256=_sha256(scores_payload),
        expected_scores_byte_length=len(scores_payload),
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        transport=transport,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": MAX_ATTEMPTS,
        },
        sleep=sleep_calls.append,
        random_uniform=lambda _low, high: high,
        fasta_deleted_allele_checker=lambda **kwargs: str(kwargs["deleted_sequence"]),
    )
    assert len(requested_urls) == 3
    assert requested_urls[0] == requested_urls[1]
    assert requested_urls[2].endswith("/canonical_representative")
    assert result["status_counts"] == {"PROJECTED_FASTA_VERIFIED": 1}
    assert result["mapping_rows"][0]["status"] == "PROJECTED_FASTA_VERIFIED"
    request_index = result["request_index"]
    assert len(request_index) == 3
    assert [entry["attempt"] for entry in request_index] == [1, 2, 1]
    assert [entry["http_status"] for entry in request_index] == [500, 200, 200]
    assert [entry["terminal"] for entry in request_index] == [False, True, True]
    assert sleep_calls.count(MIN_INTERVAL_SECONDS) >= 3
    assert any(value > MIN_INTERVAL_SECONDS for value in sleep_calls)


def test_cp08e_non_retryable_http_400_emits_row_failure_without_retry(tmp_path: Path) -> None:
    api = _ingest_api()
    scores_csv_text = _scores_csv([["urn:mavedb:00001201-a-1#1", "c.1600G>A", "", "p.Gly534Arg", "0.21"]])
    scores_payload = scores_csv_text.encode("utf-8")
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)

    requested_urls: list[str] = []

    def transport(url: str) -> dict[str, Any]:
        requested_urls.append(url)
        return {
            "final_url": url,
            "http_status": 400,
            "media_type": "application/json",
            "body": b'{"error":"invalid hgvs"}',
        }

    result = api["project_clipe_rows"](
        source_id=SOURCE_ID,
        scores_csv_bytes=scores_payload,
        expected_header=SCORES_HEADER,
        expected_rows=1,
        expected_scores_sha256=_sha256(scores_payload),
        expected_scores_byte_length=len(scores_payload),
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        transport=transport,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": MAX_ATTEMPTS,
        },
        sleep=lambda _seconds: None,
        fasta_deleted_allele_checker=lambda **kwargs: str(kwargs.get("deleted_sequence", "")),
    )
    assert requested_urls == [f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals"]
    assert result["status_counts"] == {"STEP1_HTTP_ERROR": 1}
    assert result["mapping_rows"][0]["status"] == "STEP1_HTTP_ERROR"
    assert len(result["request_index"]) == 1


@pytest.mark.parametrize(
    ("exc_factory", "retryable_transport", "expected_calls", "expected_status"),
    [
        (lambda: TimeoutError("timeout"), ["timeout"], 3, "PROJECTED_FASTA_VERIFIED"),
        (lambda: ConnectionError("connection reset"), ["timeout"], 1, "STEP1_HTTP_ERROR"),
    ],
)
def test_cp08f_transport_exception_retrying_requires_allowed_category_not_nonempty_list(
    tmp_path: Path,
    exc_factory: Callable[[], BaseException],
    retryable_transport: list[str],
    expected_calls: int,
    expected_status: str,
) -> None:
    api = _ingest_api()
    scores_csv_text = _scores_csv([["urn:mavedb:00001201-a-1#1", "c.1600G>A", "", "p.Gly534Arg", "0.21"]])
    scores_payload = scores_csv_text.encode("utf-8")
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)

    calls = {"count": 0}

    def transport(url: str) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            raise exc_factory()
        if calls["count"] == 2:
            return {"final_url": url, "http_status": 200, "media_type": "application/json", "body": _step1_payload()}
        return {"final_url": url, "http_status": 200, "media_type": "application/json", "body": _step2_payload()}

    result = api["project_clipe_rows"](
        source_id=SOURCE_ID,
        scores_csv_bytes=scores_payload,
        expected_header=SCORES_HEADER,
        expected_rows=1,
        expected_scores_sha256=_sha256(scores_payload),
        expected_scores_byte_length=len(scores_payload),
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        transport=transport,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": retryable_transport,
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": MAX_ATTEMPTS,
        },
        sleep=lambda _seconds: None,
        fasta_deleted_allele_checker=lambda **kwargs: str(kwargs["deleted_sequence"]),
    )
    assert calls["count"] == expected_calls
    assert result["mapping_rows"][0]["status"] == expected_status


@pytest.mark.parametrize(
    ("status", "retry_after_seconds", "header_name"),
    [
        (429, 7, "Retry-After"),
        (503, 4, "retry-after"),
        (429, 6, "rEtRy-AfTeR"),
    ],
)
def test_cp08g_retryable_http_honors_numeric_retry_after_before_next_attempt_case_insensitive(
    status: int, retry_after_seconds: int, header_name: str
) -> None:
    ingest = _load_module("raptor.external.tsc2_cdna_projector.ingest")
    perform = getattr(ingest, "_perform_step_request", None)
    if perform is None:
        pytest.fail("ingest module must expose private seam _perform_step_request for retry validation")

    sleeps: list[float] = []
    attempts = {"count": 0}
    retry_body = b'{"error":"retry-me"}'
    success_body = _step1_payload()
    request_url = f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals"

    def transport(_url: str) -> dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {
                "final_url": request_url,
                "http_status": status,
                "media_type": "application/json",
                "body": retry_body,
                "response_headers": {header_name: str(retry_after_seconds)},
            }
        return {
            "final_url": request_url,
            "http_status": 200,
            "media_type": "application/json",
            "body": success_body,
            "response_headers": {},
        }

    result = perform(
        url=request_url,
        transport=transport,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": 3,
            "backoff_base_seconds": 2.0,
            "backoff_cap_seconds": 60.0,
            "honor_retry_after_header": True,
        },
        sleep=sleeps.append,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
    )
    assert result["outcome"] == "success"
    assert attempts["count"] == 2
    assert sleeps and sleeps[0] == MIN_INTERVAL_SECONDS
    assert any(value >= retry_after_seconds for value in sleeps[1:])


def test_cp08ga_retryable_http_honors_http_date_retry_after_with_time_seam() -> None:
    ingest = _load_module("raptor.external.tsc2_cdna_projector.ingest")
    perform = getattr(ingest, "_perform_step_request", None)
    if perform is None:
        pytest.fail("ingest module must expose private seam _perform_step_request for retry validation")

    sleeps: list[float] = []
    attempts = {"count": 0}
    base_now = datetime(2026, 9, 12, 0, 0, 0, tzinfo=timezone.utc)
    retry_after_delay = 12.0
    retry_after_value = format_datetime(base_now + timedelta(seconds=retry_after_delay), usegmt=True)
    request_url = f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals"

    def transport(_url: str) -> dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {
                "final_url": request_url,
                "http_status": 503,
                "media_type": "application/json",
                "body": b'{"error":"retry-me"}',
                "response_headers": {"Retry-After": retry_after_value},
            }
        return {
            "final_url": request_url,
            "http_status": 200,
            "media_type": "application/json",
            "body": _step1_payload(),
            "response_headers": {},
        }

    kwargs: dict[str, Any] = {
        "url": request_url,
        "transport": transport,
        "retry_policy": {
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": 3,
            "backoff_base_seconds": 2.0,
            "backoff_cap_seconds": 60.0,
            "honor_retry_after_header": True,
        },
        "sleep": sleeps.append,
        "min_interval_seconds": MIN_INTERVAL_SECONDS,
        "random_uniform": lambda _low, high: high,
    }
    signature = inspect.signature(perform)
    if "current_time" in signature.parameters:
        kwargs["current_time"] = lambda: base_now
    elif "now_utc" in signature.parameters:
        kwargs["now_utc"] = lambda: base_now
    elif "current_timestamp" in signature.parameters:
        kwargs["current_timestamp"] = lambda: base_now.timestamp()

    result = perform(**kwargs)
    assert result["outcome"] == "success"
    assert attempts["count"] == 2
    assert sleeps and sleeps[0] == MIN_INTERVAL_SECONDS
    assert any(value >= retry_after_delay for value in sleeps[1:])


@pytest.mark.parametrize(
    "retry_after_header",
    [
        "not-a-date",
        "Wed, 01 Jan 2020 00:00:00 GMT",
        "inf",
        "-inf",
        "nan",
        "1e309",
    ],
)
def test_cp08gb_retry_after_http_date_malformed_or_past_falls_back_without_crashing(
    retry_after_header: str,
) -> None:
    ingest = _load_module("raptor.external.tsc2_cdna_projector.ingest")
    perform = getattr(ingest, "_perform_step_request", None)
    if perform is None:
        pytest.fail("ingest module must expose private seam _perform_step_request for retry validation")

    sleeps: list[float] = []
    attempts = {"count": 0}
    request_url = f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals"

    def transport(_url: str) -> dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {
                "final_url": request_url,
                "http_status": 429,
                "media_type": "application/json",
                "body": b'{"error":"retry-me"}',
                "response_headers": {"rEtRy-AfTeR": retry_after_header},
            }
        return {
            "final_url": request_url,
            "http_status": 200,
            "media_type": "application/json",
            "body": _step1_payload(),
            "response_headers": {},
        }

    result = perform(
        url=request_url,
        transport=transport,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": 3,
            "backoff_base_seconds": 2.0,
            "backoff_cap_seconds": 60.0,
            "honor_retry_after_header": True,
        },
        sleep=sleeps.append,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        random_uniform=lambda _low, _high: 1.25,
    )
    assert result["outcome"] == "success"
    assert attempts["count"] == 2
    assert all(math.isfinite(value) and value >= 0.0 for value in sleeps)
    assert any(abs(value - 1.25) < 1e-9 for value in sleeps[1:])


def test_cp08h_retry_backoff_requires_injected_uniform_jitter_seam() -> None:
    ingest = _load_module("raptor.external.tsc2_cdna_projector.ingest")
    perform = getattr(ingest, "_perform_step_request", None)
    if perform is None:
        pytest.fail("ingest module must expose private seam _perform_step_request for jitter validation")
    signature = inspect.signature(perform)
    uniform_param = next((name for name in ("random_uniform", "uniform", "jitter_uniform") if name in signature.parameters), None)
    if uniform_param is None:
        pytest.fail(
            "_perform_step_request must accept an injected uniform-random seam "
            "(e.g. random_uniform(low, high)) so retry jitter is testable deterministically"
        )

    sleeps: list[float] = []
    responses = iter(
        [
            {
                "final_url": f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals",
                "http_status": 500,
                "media_type": "application/json",
                "body": b'{"error":"transient"}',
            },
            {
                "final_url": f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals",
                "http_status": 200,
                "media_type": "application/json",
                "body": _step1_payload(),
            },
        ]
    )

    kwargs = {
        "url": f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals",
        "transport": lambda _url: next(responses),
        "retry_policy": {
            "retryable_http": [500],
            "retryable_transport": [],
            "max_attempts_per_request": 2,
            "backoff_base_seconds": 2.0,
            "backoff_cap_seconds": 60.0,
        },
        "sleep": sleeps.append,
        "min_interval_seconds": MIN_INTERVAL_SECONDS,
        uniform_param: (lambda low, high: low + ((high - low) * 0.25)),
    }
    result = perform(**kwargs)
    assert result["outcome"] == "success"
    assert len(sleeps) >= 3
    exp_cap = min(2.0, 60.0)
    jitter_values = [value for value in sleeps if value not in (MIN_INTERVAL_SECONDS,)]
    assert jitter_values
    assert all(0.0 <= value <= exp_cap for value in jitter_values)
    assert any(value < exp_cap for value in jitter_values)


def test_cp08i_retry_exhaustion_aggregate_distinguishes_nonretryable_vs_exhausted_rows(tmp_path: Path) -> None:
    api = _ingest_api()
    scores_csv_text = _scores_csv([["urn:mavedb:00001201-a-1#1", "c.1600G>A", "", "p.Gly534Arg", "0.21"]])
    scores_payload = scores_csv_text.encode("utf-8")
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)

    nonretryable = api["project_clipe_rows"](
        source_id=SOURCE_ID,
        scores_csv_bytes=scores_payload,
        expected_header=SCORES_HEADER,
        expected_rows=1,
        expected_scores_sha256=_sha256(scores_payload),
        expected_scores_byte_length=len(scores_payload),
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        transport=lambda url: {
            "final_url": url,
            "http_status": 400,
            "media_type": "application/json",
            "body": b'{"error":"bad-request"}',
        },
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": MAX_ATTEMPTS,
        },
        sleep=lambda _seconds: None,
        fasta_deleted_allele_checker=lambda **kwargs: str(kwargs.get("deleted_sequence", "")),
    )
    assert "retry_exhausted_count" in nonretryable
    assert "retry_exhausted_rows" in nonretryable
    assert nonretryable["retry_exhausted_count"] == 0
    assert nonretryable["retry_exhausted_rows"] == []

    attempts = {"count": 0}

    def retryable_then_exhausted(url: str) -> dict[str, Any]:
        attempts["count"] += 1
        return {
            "final_url": url,
            "http_status": 503,
            "media_type": "application/json",
            "body": b'{"error":"temporary"}',
        }

    exhausted = api["project_clipe_rows"](
        source_id=SOURCE_ID,
        scores_csv_bytes=scores_payload,
        expected_header=SCORES_HEADER,
        expected_rows=1,
        expected_scores_sha256=_sha256(scores_payload),
        expected_scores_byte_length=len(scores_payload),
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        transport=retryable_then_exhausted,
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": 2,
        },
        sleep=lambda _seconds: None,
        fasta_deleted_allele_checker=lambda **kwargs: str(kwargs.get("deleted_sequence", "")),
    )
    assert attempts["count"] == 2
    assert exhausted["retry_exhausted_count"] == 1
    assert exhausted["retry_exhausted_rows"] == [1]


def test_cp08j_request_index_is_attempt_level_and_raw_attempts_preserve_all_typed_bodies(tmp_path: Path) -> None:
    api = _ingest_api()
    scores_csv_text = _scores_csv([["urn:mavedb:00001201-a-1#1", "c.1600G>A", "", "p.Gly534Arg", "0.21"]])
    scores_payload = scores_csv_text.encode("utf-8")
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)

    step1_retry = b'{"error":"retryable-500"}'
    step1_terminal = _step1_payload()
    step2_terminal = _step2_payload()
    responses = iter(
        [
            {
                "final_url": f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals",
                "http_status": 500,
                "media_type": "application/json",
                "body": step1_retry,
            },
            {
                "final_url": f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals",
                "http_status": 200,
                "media_type": "application/json",
                "body": step1_terminal,
            },
            {
                "final_url": f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
                "http_status": 200,
                "media_type": "application/json",
                "body": step2_terminal,
            },
        ]
    )

    result = api["project_clipe_rows"](
        source_id=SOURCE_ID,
        scores_csv_bytes=scores_payload,
        expected_header=SCORES_HEADER,
        expected_rows=1,
        expected_scores_sha256=_sha256(scores_payload),
        expected_scores_byte_length=len(scores_payload),
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        transport=lambda _url: next(responses),
        min_interval_seconds=MIN_INTERVAL_SECONDS,
        retry_policy={
            "retryable_http": sorted(RETRYABLE_HTTP),
            "retryable_transport": ["timeout", "connection_error", "tls_error"],
            "non_retryable_http": sorted(NON_RETRYABLE_HTTP),
            "max_attempts_per_request": 3,
        },
        sleep=lambda _seconds: None,
        fasta_deleted_allele_checker=lambda **kwargs: str(kwargs["deleted_sequence"]),
    )

    assert "request_index" in result and isinstance(result["request_index"], list)
    assert len(result["request_index"]) == 3
    expected_keys = {
        "source_row",
        "step",
        "attempt",
        "requested_url",
        "final_url",
        "http_status",
        "body_sha256",
        "elapsed_ms",
        "retry_category",
        "terminal",
        "retry_exhausted",
    }
    for entry in result["request_index"]:
        assert set(entry) == expected_keys

    raw_attempts = None
    for field in ("raw_attempt_envelopes", "attempt_envelopes", "http_attempts"):
        if field in result:
            raw_attempts = result[field]
            break
    assert raw_attempts is not None
    assert isinstance(raw_attempts, list)
    assert len(raw_attempts) == 3
    assert [item["attempt"] for item in raw_attempts] == [1, 2, 1]
    assert [item["http_status"] for item in raw_attempts] == [500, 200, 200]
    assert [item["body_sha256"] for item in raw_attempts] == [
        _sha256(step1_retry),
        _sha256(step1_terminal),
        _sha256(step2_terminal),
    ]
    row = result["mapping_rows"][0]
    assert row["step1_body_sha256"] == _sha256(step1_terminal)
    assert row["step2_body_sha256"] == _sha256(step2_terminal)
    assert row["step1_body_sha256"] != _sha256(step1_retry)


def test_cp09_frozen_scores_header_rowcount_duplicate_and_shape_validation_fail_closed() -> None:
    api = _ingest_api()
    rows = [
        ["urn:mavedb:00001201-a-1#1", "c.1600G>A", "", "p.Gly534Arg", "0.21"],
        ["urn:mavedb:00001201-a-1#2", "c.1627_1629delinsTGA", "", "p.Pro543Ter", "-0.30"],
    ]
    csv_text = _scores_csv(rows)
    payload = csv_text.encode("utf-8")
    parsed = api["validate_frozen_scores_input"](
        csv_text=csv_text,
        expected_header=SCORES_HEADER,
        expected_rows=2,
        expected_sha256=_sha256(payload),
        expected_byte_length=len(payload),
        transcript=TRANSCRIPT,
    )
    assert len(parsed) == 2
    assert parsed[0]["source_row"] == 1 and parsed[1]["source_row"] == 2

    err = api["FrozenInputError"]
    with pytest.raises(err):
        api["validate_frozen_scores_input"](
            csv_text=csv_text.replace("hgvs_nt", "HGVS"),
            expected_header=SCORES_HEADER,
            expected_rows=2,
            expected_sha256=_sha256(payload),
            expected_byte_length=len(payload),
            transcript=TRANSCRIPT,
        )
    with pytest.raises(err):
        api["validate_frozen_scores_input"](
            csv_text=csv_text,
            expected_header=SCORES_HEADER,
            expected_rows=208,
            expected_sha256=_sha256(payload),
            expected_byte_length=len(payload),
            transcript=TRANSCRIPT,
        )
    with pytest.raises(err):
        api["validate_frozen_scores_input"](
            csv_text=_scores_csv([rows[0], rows[0]]),
            expected_header=SCORES_HEADER,
            expected_rows=2,
            expected_sha256=_sha256(_scores_csv([rows[0], rows[0]]).encode("utf-8")),
            expected_byte_length=len(_scores_csv([rows[0], rows[0]]).encode("utf-8")),
            transcript=TRANSCRIPT,
        )
    with pytest.raises(err):
        api["validate_frozen_scores_input"](
            csv_text=_scores_csv([["urn:mavedb:00001201-a-1#1", "c.1600_1601insA", "", "p.X", "0.21"]]),
            expected_header=SCORES_HEADER,
            expected_rows=1,
            expected_sha256=_sha256(
                _scores_csv([["urn:mavedb:00001201-a-1#1", "c.1600_1601insA", "", "p.X", "0.21"]]).encode("utf-8")
            ),
            expected_byte_length=len(
                _scores_csv([["urn:mavedb:00001201-a-1#1", "c.1600_1601insA", "", "p.X", "0.21"]]).encode("utf-8")
            ),
            transcript=TRANSCRIPT,
        )
    for bad_hgvs in ("c.1629_1627delinsTGA", "c.1627_1629delinsTG"):
        bad_csv_text = _scores_csv([["urn:mavedb:00001201-a-1#1", bad_hgvs, "", "p.X", "0.21"]])
        bad_payload = bad_csv_text.encode("utf-8")
        with pytest.raises(err):
            api["validate_frozen_scores_input"](
                csv_text=bad_csv_text,
                expected_header=SCORES_HEADER,
                expected_rows=1,
                expected_sha256=_sha256(bad_payload),
                expected_byte_length=len(bad_payload),
                transcript=TRANSCRIPT,
            )


def test_cp09b_validate_frozen_source_bundle_manifest_recomputes_hash_and_rejects_hash_or_artifact_drift() -> None:
    ingest = _load_module("raptor.external.tsc2_cdna_projector.ingest")
    helper = getattr(ingest, "validate_frozen_source_bundle_manifest", None)
    if helper is None:
        pytest.fail(
            "ingest API must expose validate_frozen_source_bundle_manifest("
            "source_manifest, expected_bundle_id, expected_manifest_content_hash, expected_scores_artifact)"
        )
    api = _ingest_api()
    err = api["FrozenInputError"]
    source_bundle_api = _source_bundle_api()

    scores_payload = _scores_csv([["urn:mavedb:00001201-a-1#1", "c.1600G>A", "", "p.Gly534Arg", "0.21"]]).encode("utf-8")
    manifest = _build_synthetic_source_bundle_manifest(scores_payload=scores_payload)
    expected_artifact = {
        "artifact_id": SCORES_ARTIFACT_ID,
        "source_id": SOURCE_ID,
        "relative_path": SCORES_RELATIVE_PATH,
        "sha256": _sha256(scores_payload),
        "byte_length": len(scores_payload),
    }
    helper(
        source_manifest=manifest,
        expected_bundle_id=SOURCE_BUNDLE_ID,
        expected_manifest_content_hash=manifest["content_hash"],
        expected_scores_artifact=expected_artifact,
    )

    altered_hash = deepcopy(manifest)
    altered_hash["content_hash"] = "0" * 64
    with pytest.raises(err):
        helper(
            source_manifest=altered_hash,
            expected_bundle_id=SOURCE_BUNDLE_ID,
            expected_manifest_content_hash=manifest["content_hash"],
            expected_scores_artifact=expected_artifact,
        )

    real_artifact = _source_artifact_record(
        artifact_id=SCORES_ARTIFACT_ID,
        source_id=SOURCE_ID,
        relative_path=SCORES_RELATIVE_PATH,
        payload=scores_payload,
    )
    decoy_artifact = _source_artifact_record(
        artifact_id="mavedb_clipe-scores-csv-decoy",
        source_id=SOURCE_ID,
        relative_path="mavedb/decoy-scores.csv",
        payload=b"accession,hgvs_nt,hgvs_splice,hgvs_pro,score\nx,c.1A>G,,p.X,0.0\n",
    )
    manifest_with_decoy = _build_synthetic_source_bundle_manifest(
        scores_payload=scores_payload,
        artifacts=[decoy_artifact, real_artifact],
    )
    manifest_with_decoy["content_hash"] = source_bundle_api["compute_bundle_content_hash"](manifest_with_decoy)
    with pytest.raises(err):
        helper(
            source_manifest=manifest_with_decoy,
            expected_bundle_id=SOURCE_BUNDLE_ID,
            expected_manifest_content_hash=manifest_with_decoy["content_hash"],
            expected_scores_artifact=expected_artifact,
        )

    duplicate_artifact = deepcopy(real_artifact)
    duplicate_artifact["artifact_id"] = f"{SCORES_ARTIFACT_ID}-duplicate"
    duplicate_artifact["relative_path"] = SCORES_RELATIVE_PATH
    manifest_with_duplicate = _build_synthetic_source_bundle_manifest(
        scores_payload=scores_payload,
        artifacts=[real_artifact, duplicate_artifact],
    )
    manifest_with_duplicate["content_hash"] = source_bundle_api["compute_bundle_content_hash"](manifest_with_duplicate)
    with pytest.raises(err):
        helper(
            source_manifest=manifest_with_duplicate,
            expected_bundle_id=SOURCE_BUNDLE_ID,
            expected_manifest_content_hash=manifest_with_duplicate["content_hash"],
            expected_scores_artifact=expected_artifact,
        )


def test_cp10_canonical_mapping_jsonl_and_request_index_are_deterministic_and_lf_terminated() -> None:
    api = _bundle_api()
    rows_a = [_minimal_mapping_row(source_row=1, shape="SNV"), _minimal_mapping_row(source_row=2, shape="DELINS")]
    rows_b = [dict(reversed(list(row.items()))) for row in rows_a]

    blob_a = api["canonical_mapping_jsonl_bytes"](rows_a)
    blob_b = api["canonical_mapping_jsonl_bytes"](rows_b)
    assert blob_a == blob_b
    assert blob_a.endswith(b"\n")
    assert b"\r\n" not in blob_a

    request_rows = [
        _minimal_request_index_row(
            source_row=1,
            step="step1",
            requested_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals",
            final_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals",
        ),
        _minimal_request_index_row(
            source_row=1,
            step="step2",
            requested_url=f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
            final_url=f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
        ),
    ]
    request_blob = api["canonical_request_index_jsonl_bytes"](request_rows)
    assert request_blob.endswith(b"\n")
    assert b"\r\n" not in request_blob


def test_cp10b_canonical_mapping_jsonl_revalidates_rows_and_rejects_duplicate_source_pairs() -> None:
    bundle_api = _bundle_api()
    model_api = _model_api()
    err = model_api["ProjectionContractError"]

    malformed = _minimal_mapping_row(source_row=1, shape="SNV")
    malformed["status"] = "NOT_A_REAL_STATUS"
    with pytest.raises(err):
        bundle_api["canonical_mapping_jsonl_bytes"]([malformed])

    malformed_spdi = _minimal_mapping_row(source_row=1, shape="SNV")
    malformed_spdi["genomic_spdi"] = "NC_000016.10:bad:G:A"
    with pytest.raises(err):
        bundle_api["canonical_mapping_jsonl_bytes"]([malformed_spdi])

    duplicate_pair = [
        _minimal_mapping_row(source_row=1, shape="SNV"),
        _minimal_mapping_row(source_row=1, shape="SNV"),
    ]
    with pytest.raises(err):
        bundle_api["canonical_mapping_jsonl_bytes"](duplicate_pair)


def test_cp11_request_index_redacts_secret_query_values_and_preserves_raw_body_hashes() -> None:
    api = _bundle_api()
    rows = [
        {
            **_minimal_request_index_row(
                source_row=1,
                step="step1",
                requested_url=(
                    f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals?api_key=SECRET&tool=xyz"
                ),
                final_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals?api_key=SECRET",
            )
        }
    ]
    blob = api["canonical_request_index_jsonl_bytes"](rows)
    text = blob.decode("utf-8")
    assert "SECRET" not in text
    assert "api_key=" not in text or "REDACTED" in text
    assert rows[0]["body_sha256"] in text


def test_cp12_bundle_manifest_hash_schema_crossrefs_and_counts_are_exact() -> None:
    api = _bundle_api()
    mapping_blob = api["canonical_mapping_jsonl_bytes"](
        [_minimal_mapping_row(source_row=1, shape="SNV"), _minimal_mapping_row(source_row=2, shape="DELINS")]
    )
    request_blob = api["canonical_request_index_jsonl_bytes"](
        [
            _minimal_request_index_row(
                source_row=1,
                step="step1",
                requested_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals",
                final_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals",
            )
        ]
    )
    args = {
        "bundle_id": BUNDLE_ID,
        "created_at": "2026-09-12T00:00:00Z",
        "input_scores": {
            "artifact_id": SCORES_ARTIFACT_ID,
            "sha256": SCORES_SHA256,
            "byte_length": SCORES_BYTE_LENGTH,
            "row_count": 2,
        },
        "reference": {"accession": GENOMIC_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        "endpoint_pins": {
            "base_url": BASE_URL,
            "step_sequence": ["contextuals", "canonical_representative"],
            "min_interval_seconds": MIN_INTERVAL_SECONDS,
        },
        "artifacts": [
            {
                "artifact_id": "mapping-jsonl",
                "relative_path": "mapping/mavedb_clipe_nm000548_5_to_nc000016_10.jsonl",
                "byte_length": len(mapping_blob),
                "sha256": _sha256(mapping_blob),
                "row_count": 2,
            },
            {
                "artifact_id": "request-index-jsonl",
                "relative_path": "logs/request_index.jsonl",
                "byte_length": len(request_blob),
                "sha256": _sha256(request_blob),
                "row_count": 1,
            },
        ],
        "status_counts": {"PROJECTED_FASTA_VERIFIED": 2},
        "shape_counts": {"SNV": 1, "DELINS": 1},
        "success_count": 2,
        "failure_count": 0,
        "boundaries": {"network": "operator_only", "clinical_use": "forbidden"},
    }
    manifest = api["build_projector_bundle_manifest"](**args)
    assert manifest["schema"] == BUNDLE_SCHEMA
    assert manifest["bundle_id"] == BUNDLE_ID
    assert manifest["shape_counts"] == {"SNV": 1, "DELINS": 1}
    assert manifest["status_counts"] == {"PROJECTED_FASTA_VERIFIED": 2}
    assert manifest["content_hash"] == api["compute_manifest_content_hash"](manifest)
    api["validate_manifest_content_hash"](manifest)

    drifted = deepcopy(manifest)
    drifted["artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(api["ProjectorManifestError"]):
        api["validate_manifest_content_hash"](drifted)


def test_cp12b_manifest_builder_and_hash_validator_enforce_fields_uniqueness_and_count_conservation() -> None:
    api = _bundle_api()
    mapping_blob = api["canonical_mapping_jsonl_bytes"](
        [_minimal_mapping_row(source_row=1, shape="SNV"), _minimal_mapping_row(source_row=2, shape="DELINS")]
    )
    request_blob = api["canonical_request_index_jsonl_bytes"](
        [
            _minimal_request_index_row(
                source_row=1,
                step="step1",
                requested_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals",
                final_url=f"{BASE_URL}/hgvs/{quote('NM_000548.5:c.1600G>A', safe='')}/contextuals",
            ),
            _minimal_request_index_row(
                source_row=1,
                step="step2",
                requested_url=f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
                final_url=f"{BASE_URL}/spdi/{quote('NM_000548.5:1709:G:A', safe='')}/canonical_representative",
            ),
        ]
    )
    base_manifest = api["build_projector_bundle_manifest"](
        bundle_id=BUNDLE_ID,
        created_at="2026-09-12T00:00:00Z",
        input_scores={
            "artifact_id": SCORES_ARTIFACT_ID,
            "sha256": SCORES_SHA256,
            "byte_length": SCORES_BYTE_LENGTH,
            "row_count": 2,
        },
        reference={"accession": GENOMIC_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        endpoint_pins={
            "base_url": BASE_URL,
            "step_sequence": ["contextuals", "canonical_representative"],
            "min_interval_seconds": MIN_INTERVAL_SECONDS,
        },
        artifacts=[
            {
                "artifact_id": "mapping-jsonl",
                "relative_path": "mapping/mavedb_clipe_nm000548_5_to_nc000016_10.jsonl",
                "byte_length": len(mapping_blob),
                "sha256": _sha256(mapping_blob),
                "row_count": 2,
            },
            {
                "artifact_id": "request-index-jsonl",
                "relative_path": "logs/request_index.jsonl",
                "byte_length": len(request_blob),
                "sha256": _sha256(request_blob),
                "row_count": 2,
            },
        ],
        status_counts={"PROJECTED_FASTA_VERIFIED": 1, "STEP1_INVALID_HGVS": 1},
        shape_counts={"SNV": 1, "DELINS": 1},
        success_count=1,
        failure_count=1,
        boundaries={
            "network": "operator_only",
            "clinical_use": "forbidden",
            "evidence_strength_use": "forbidden",
        },
    )
    api["validate_manifest_content_hash"](base_manifest)

    def _mutated(mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        candidate = deepcopy(base_manifest)
        mutate(candidate)
        candidate["content_hash"] = api["compute_manifest_content_hash"](candidate)
        return candidate

    invalid_manifests = [
        _mutated(lambda m: m.__setitem__("unexpected_top_level", True)),
        _mutated(lambda m: m["artifacts"][0].__setitem__("extra", "forbidden")),
        _mutated(lambda m: m["artifacts"].append(deepcopy(m["artifacts"][0]))),
        _mutated(lambda m: m["artifacts"][1].__setitem__("relative_path", m["artifacts"][0]["relative_path"])),
        _mutated(lambda m: m["artifacts"][0].__setitem__("relative_path", "../escape.jsonl")),
        _mutated(lambda m: m.__setitem__("success_count", 2)),
        _mutated(
            lambda m: (
                m["status_counts"].__setitem__("PROJECTED_FASTA_VERIFIED", 2),
                m["status_counts"].__setitem__("STEP1_INVALID_HGVS", 0),
            )
        ),
        _mutated(lambda m: m["shape_counts"].__setitem__("SNV", 2)),
        _mutated(lambda m: m["artifacts"][0].__setitem__("row_count", 1)),
    ]

    for candidate in invalid_manifests:
        with pytest.raises(api["ProjectorManifestError"]):
            api["validate_manifest_content_hash"](candidate)


def test_cp13_summary_is_aggregate_only_with_boundaries_and_no_row_level_or_clinical_content() -> None:
    api = _bundle_api()
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "bundle_id": BUNDLE_ID,
        "content_hash": "1" * 64,
        "input_scores": {"sha256": SCORES_SHA256, "row_count": TOTAL_ROWS},
        "reference": {"sha256": REFERENCE_FASTA_SHA256},
        "endpoint_pins": {"sequence": ["contextuals", "canonical_representative"]},
        "counts": {"rows": TOTAL_ROWS},
        "status_counts": {"PROJECTED_FASTA_VERIFIED": TOTAL_ROWS},
        "shape_counts": {"SNV": SNV_ROWS, "DELINS": DELINS_ROWS},
        "request_budget_observed": {"step1": TOTAL_ROWS, "step2": TOTAL_ROWS},
        "pilot_uncertainties": ["U1"],
        "boundaries": {"clinical_use": "forbidden", "evidence_strength_use": "forbidden"},
    }
    summary = api["build_committed_summary"](manifest)
    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "input_scores_sha256",
        "reference_sha256",
        "endpoint_sequence",
        "total_rows",
        "success_count",
        "failure_count",
        "status_counts",
        "shape_counts",
        "request_budget_observed",
        "pilot_uncertainties",
        "boundaries",
    }
    assert summary["boundaries"] == {"clinical_use": "forbidden", "evidence_strength_use": "forbidden"}
    merged = json.dumps(summary, sort_keys=True).lower()
    assert "hgvs_c" not in merged
    assert "hgvs_g" not in merged
    assert "genomic_spdi" not in merged
    assert "score_raw" not in merged
    assert "functional_class" not in merged
    assert "http://" not in merged and "https://" not in merged
    assert not any(token in merged for token in FORBIDDEN_TEXT_TOKENS)


def test_cp14_publication_reuses_hardened_no_clobber_helper_and_refuses_unsafe_targets(tmp_path: Path) -> None:
    api = _bundle_api()
    source_bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    assert api["_publish_directory_no_replace"] is _symbol(source_bundle_module, "_publish_directory_no_replace")

    manifest, mapping_payload, request_index_payload, raw_payloads = _valid_projector_manifest_and_payloads(api)
    output_root = tmp_path / "external"
    output_root.mkdir()
    repo_root_for_preexisting = tmp_path / "repo-preexisting"
    repo_root_for_preexisting.mkdir()
    preexisting = output_root / RUN_NAME
    preexisting.mkdir()
    with pytest.raises(api["ProjectorBundleBoundaryError"]):
        api["publish_projector_bundle"](
            repo_root=repo_root_for_preexisting,
            output_root=output_root,
            run_name=RUN_NAME,
            manifest=manifest,
            mapping_payload=mapping_payload,
            request_index_payload=request_index_payload,
            raw_payloads=raw_payloads,
        )
    assert preexisting.exists()
    assert list(preexisting.iterdir()) == []

    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    with pytest.raises(api["ProjectorBundleBoundaryError"]):
        api["publish_projector_bundle"](
            repo_root=repo_root,
            output_root=repo_root / "inside-repo-not-allowed",
            run_name=RUN_NAME,
            manifest=manifest,
            mapping_payload=mapping_payload,
            request_index_payload=request_index_payload,
            raw_payloads=raw_payloads,
        )


def test_cp15_package_and_operator_remain_offline_and_disallow_forbidden_imports() -> None:
    missing: list[Path] = []
    targets: list[Path] = []

    if not PACKAGE_ROOT.is_dir():
        missing.append(PACKAGE_ROOT)
    else:
        targets.extend(sorted(path for path in PACKAGE_ROOT.rglob("*.py") if path.is_file()))

    if not OPERATOR_SCRIPT.is_file():
        missing.append(OPERATOR_SCRIPT)
    else:
        targets.append(OPERATOR_SCRIPT)

    if missing:
        pytest.fail("TSC2 cliPE projector implementation targets are missing: " + ", ".join(str(p) for p in missing))

    offenders: list[str] = []
    for path in targets:
        for imported, lineno in _module_imports(path):
            lowered = imported.lower()
            if any(lowered == token or lowered.startswith(token + ".") for token in FORBIDDEN_NETWORK_IMPORTS):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
            if any(imported == token or imported.startswith(token + ".") for token in FORBIDDEN_IMPORT_PREFIXES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
    assert not offenders, "forbidden imports detected:\n" + "\n".join(offenders)


def test_cp16_operator_enforces_sequential_two_step_flow_rate_limit_and_abort_policy() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 cliPE projector operator script is not implemented: {OPERATOR_SCRIPT}")
    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    main_node = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"), None)
    if main_node is None:
        pytest.fail("operator script is missing main(argv=...)")

    called_names: list[tuple[str, int]] = []
    for node in ast.walk(main_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.append((node.func.id, node.lineno))
            elif isinstance(node.func, ast.Attribute):
                called_names.append((node.func.attr, node.lineno))

    names = [name for name, _ in called_names]
    assert "validate_reference_fasta_checksum" in names
    assert "validate_frozen_scores_input" in names
    assert "project_clipe_rows" in names
    assert "publish_projector_bundle" in names
    assert names.index("validate_reference_fasta_checksum") < names.index("project_clipe_rows")
    assert names.index("validate_frozen_scores_input") < names.index("project_clipe_rows")
    assert names.index("project_clipe_rows") < names.index("publish_projector_bundle")

    source = OPERATOR_SCRIPT.read_text(encoding="utf-8")
    assert "/hgvs/batch/contextuals" not in source
    assert "/hgvs/" not in source or "canonical_representative" not in source.split("/hgvs/")[-1]
    assert "min_interval_seconds" in source or "sleep(" in source
    assert "max_attempts_per_request" in source
    assert "retryable_http" in source
    assert "retryable_transport" in source
    assert "0.05" in source or "5%" in source


def test_cp16b_operator_reads_pinned_source_manifest_and_validates_it_before_scores_use() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 cliPE projector operator script is not implemented: {OPERATOR_SCRIPT}")
    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    main_node = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"), None)
    if main_node is None:
        pytest.fail("operator script is missing main(argv=...)")

    called_lines: dict[str, int] = {}
    for node in ast.walk(main_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_lines.setdefault(node.func.id, node.lineno)
            elif isinstance(node.func, ast.Attribute):
                called_lines.setdefault(node.func.attr, node.lineno)
    assert "validate_frozen_source_bundle_manifest" in called_lines
    assert "validate_frozen_scores_input" in called_lines
    assert called_lines["validate_frozen_source_bundle_manifest"] < called_lines["validate_frozen_scores_input"]

    source = OPERATOR_SCRIPT.read_text(encoding="utf-8")
    assert "manifest_filename" in source
    assert "bundle_manifest.json" in source or "source_bundle_manifest" in source


def test_cp16c_operator_https_transport_sets_connect_and_read_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    operator = _load_operator_module()
    transport_cls = getattr(operator, "_RateLimitedHttpsTransport", None)
    if transport_cls is None:
        pytest.fail("operator must define _RateLimitedHttpsTransport for timeout behavior")

    events: list[tuple[str, Any]] = []
    observed: dict[str, Any] = {}

    class _FakeSocket:
        def settimeout(self, timeout: float) -> None:
            observed["socket_timeout"] = timeout
            events.append(("settimeout", timeout))

    class _FakeResponse:
        status = 200

        def read(self) -> bytes:
            events.append(("read", None))
            return b"{}"

        def getheader(self, _name: str) -> str:
            return "application/json"

    class _FakeHTTPSConnection:
        def __init__(self, host: str, timeout: float | None = None, context: Any = None) -> None:
            observed["host"] = host
            observed["constructor_timeout"] = timeout
            observed["context"] = context
            self.sock = _FakeSocket()
            events.append(("init", timeout))

        def connect(self) -> None:
            events.append(("connect", None))

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            events.append(("request", (method, path, headers)))

        def getresponse(self) -> _FakeResponse:
            events.append(("getresponse", None))
            return _FakeResponse()

        def close(self) -> None:
            events.append(("close", None))

    monkeypatch.setattr(operator.http.client, "HTTPSConnection", _FakeHTTPSConnection)

    transport = transport_cls(connect_timeout=9.0, read_timeout=27.0)
    response = transport(f"{BASE_URL}/hgvs/{quote(f'{TRANSCRIPT}:c.1600G>A', safe='')}/contextuals")
    assert response["http_status"] == 200
    assert observed.get("constructor_timeout") == 9.0
    event_names = [name for name, _ in events]
    assert "connect" in event_names
    assert "settimeout" in event_names
    assert event_names.index("connect") < event_names.index("request")
    assert observed.get("socket_timeout") == 27.0


def test_cp16d_operator_run_abort_threshold_uses_retry_exhaustion_aggregate_not_status_rollup() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 cliPE projector operator script is not implemented: {OPERATOR_SCRIPT}")
    source = OPERATOR_SCRIPT.read_text(encoding="utf-8")
    assert "retry_exhausted_count" in source or "retry_exhausted_rows" in source
    assert "STEP1_HTTP_ERROR" not in re.sub(r"\s+", " ", source.split("run_abort", 1)[-1])


def test_cp16e_operator_raw_publication_uses_attempt_records_not_transport_capture_replay() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 cliPE projector operator script is not implemented: {OPERATOR_SCRIPT}")
    source = OPERATOR_SCRIPT.read_text(encoding="utf-8")
    assert "transport.captured" not in source
    assert "reversed(transport.captured)" not in source
    assert "raw_attempt" in source
    assert re.search(r"raw/.+attempt", source) is not None


def test_cp17_operator_cli_requires_explicit_roots_and_does_not_fall_back_to_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    operator = _load_operator_module()
    for env_name in (
        "RAPTOR_TSC2_SOURCE_ROOT",
        "RAPTOR_TSC2_REFERENCE_ROOT",
        "RAPTOR_TSC2_CDNA_PROJECTOR_ROOT",
    ):
        monkeypatch.delenv(env_name, raising=False)
    cwd_before = os.getcwd()
    exit_code = operator.main(["--config", str(CONFIG_PATH)])
    assert os.getcwd() == cwd_before
    assert exit_code == 1


def test_cp18_config_pins_exact_input_hashes_endpoints_run_name_and_shape_totals() -> None:
    if not CONFIG_PATH.is_file():
        pytest.fail(f"TSC2 cliPE projector config is not implemented: {CONFIG_PATH}")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["spec_id"] == "raptor-v2-clipe-cdna-spdi-projector-acquisition-v1"
    assert config["spec_version"] == "1.0.6"

    source_bundle = config["inputs"]["source_bundle"]
    assert source_bundle["bundle_id"] == SOURCE_BUNDLE_ID
    assert source_bundle["manifest_content_hash"] == SOURCE_MANIFEST_CONTENT_HASH
    scores = source_bundle["scores_artifact"]
    assert scores["artifact_id"] == SCORES_ARTIFACT_ID
    assert scores["relative_path"] == SCORES_RELATIVE_PATH
    assert scores["sha256"] == SCORES_SHA256
    assert scores["byte_length"] == SCORES_BYTE_LENGTH
    assert scores["expected_rows"] == TOTAL_ROWS
    assert scores["exact_header"] == SCORES_HEADER

    ref = config["inputs"]["genomic_reference"]
    assert ref["accession"] == GENOMIC_ACCESSION
    assert ref["assembly"] == ASSEMBLY
    assert ref["fasta_filename"] == REFERENCE_FASTA_FILENAME
    assert ref["sha256"] == REFERENCE_FASTA_SHA256

    pins = config["inputs"]["identity_pins"]
    assert pins["gene"] == GENE
    assert pins["transcript"] == TRANSCRIPT
    assert pins["genomic_accession"] == GENOMIC_ACCESSION
    assert pins["service_host"] == EXPECTED_HOST
    assert pins["service_base_path"] == EXPECTED_BASE_PATH

    assert config["rate_limits_retries"]["min_interval_seconds"] == MIN_INTERVAL_SECONDS
    retry_policy = config["rate_limits_retries"]["retry_policy"]
    assert set(retry_policy["retryable_http"]) == RETRYABLE_HTTP
    assert set(retry_policy["non_retryable_http"]) == NON_RETRYABLE_HTTP
    assert retry_policy["max_attempts_per_request"] == MAX_ATTEMPTS

    output = config["outputs"]["external_bundle"]
    assert output["run_name"] == RUN_NAME
    assert output["bundle_id"] == BUNDLE_ID
    assert output["artifacts"]["mapping_jsonl"]["schema"] == MAPPING_ROW_SCHEMA
    assert output["artifacts"]["mapping_jsonl"]["row_count"] == TOTAL_ROWS
    summary_output = config["outputs"]["committed_summary"]
    assert summary_output["path"] == str(SUMMARY_PATH.relative_to(REPO_ROOT)).replace("\\", "/")
    assert summary_output["schema"] == SUMMARY_SCHEMA
    if "boundaries" in summary_output:
        assert summary_output["boundaries"] == {
            "clinical_use": "forbidden",
            "evidence_strength_use": "forbidden",
        }

    expected = config["expected_pilot_outputs"]["supportable_now"]
    assert expected["total_mapping_rows"] == TOTAL_ROWS
    assert expected["shape_counts"] == {"SNV": SNV_ROWS, "DELINS": DELINS_ROWS}
    assert expected["reference_sha256"] == REFERENCE_FASTA_SHA256
    assert expected["scores_sha256"] == SCORES_SHA256


def test_cp19_committed_summary_exists_and_matches_final_pilot_contract_without_row_level_content() -> None:
    if not SUMMARY_PATH.is_file():
        pytest.fail(f"committed summary is missing: {SUMMARY_PATH}")

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "input_scores_sha256",
        "reference_sha256",
        "total_rows",
        "success_count",
        "failure_count",
        "status_counts",
        "shape_counts",
        "request_budget_observed",
        "endpoint_sequence",
        "boundaries",
        "pilot_uncertainties",
    }
    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["bundle_id"] == BUNDLE_ID
    assert summary["manifest_content_hash"] == "247665b9758860124b196d037b913626b7699b87ba1bb1c32b0e461bb4473529"
    assert summary["input_scores_sha256"] == SCORES_SHA256
    assert summary["reference_sha256"] == REFERENCE_FASTA_SHA256
    assert summary["total_rows"] == TOTAL_ROWS
    assert summary["success_count"] == TOTAL_ROWS
    assert summary["failure_count"] == 0
    assert summary["status_counts"] == {"PROJECTED_FASTA_VERIFIED": TOTAL_ROWS}
    assert summary["shape_counts"] == {"SNV": SNV_ROWS, "DELINS": DELINS_ROWS}
    assert summary["request_budget_observed"]["step1"] == TOTAL_ROWS
    assert summary["request_budget_observed"]["step2"] == TOTAL_ROWS
    assert summary["boundaries"] == {
        "clinical_use": "forbidden",
        "evidence_strength_use": "forbidden",
        "network": "operator_only",
    }
    assert summary["endpoint_sequence"] == ["contextuals", "canonical_representative"]
    assert summary["pilot_uncertainties"] == []

    serialized = json.dumps(summary, sort_keys=True).lower()
    forbidden_row_tokens = (
        "hgvs_nt_source",
        "hgvs_c",
        "hgvs_g",
        "tx_spdi",
        "genomic_spdi",
        "requested_url",
        "final_url",
        "raw_body",
        "raw_attempt",
        "score_raw",
        "functional_class",
        "classification",
        "pathogenic",
        "benign",
        "ps3",
        "bs3",
    )
    assert not any(token in serialized for token in forbidden_row_tokens)
