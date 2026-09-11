from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.util
import inspect
import io
import json
import os
import zipfile
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "src" / "raptor" / "external" / "tsc2_vamp_crosswalk"
OPERATOR_SCRIPT = REPO_ROOT / "scripts" / "fetch_tsc2_vamp_genomic_crosswalk.py"
CONFIG_PATH = REPO_ROOT / "configs" / "external" / "tsc2_vamp_genomic_crosswalk_v1.yaml"
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-vamp-genomic-crosswalk-acquisition-v1.yaml"

CROSSWALK_SCHEMA = "raptor.external.vamp_genomic_crosswalk_row.v1"
BUNDLE_SCHEMA = "raptor.external.vamp_genomic_crosswalk_bundle.v1"
SUMMARY_SCHEMA = "raptor.external.vamp_genomic_crosswalk_summary.v1"

SOURCE_ID = "igvf_vamp_seq"
SOURCE_BUNDLE_ID = "tsc2-source-pilot-2026-09-09"
SOURCE_MANIFEST_CONTENT_HASH = "63bd6eb4e7182b7f2d345cd78b3a110a59c361c72d521b88990c475919865808"

SCORES_ARTIFACT_ID = "igvf_vamp_seq-download-tsv-gz"
SCORES_RELATIVE_PATH = "igvf/igvf_vamp_seq-IGVFFI9747KART.tsv.gz"
SCORES_SHA256 = "39f052e6e4819ff245fcee8d63fa1b4c3b09b2d9a0d529f5c14de5deaafa497e"
SCORES_MD5 = "1a397944b7a5158b3d63999dfcf926db"
SCORES_BYTE_LENGTH = 439700
SCORES_ROW_COUNT = 9253
PROTEIN_ACCESSION = "ENSP00000219476.3"

ZENODO_RECORD_ID = 20837254
ZENODO_DOI = "10.5281/zenodo.20837254"
ZENODO_FILENAME = "FowlerLab/TSC2_analysis-V1.zip"
ZENODO_DOWNLOAD_URL = "https://zenodo.org/api/records/20837254/files/FowlerLab/TSC2_analysis-V1.zip/content"
ZENODO_SHA256 = "f9ceaec5d4608d3d2f804b4f919d42030aceb7d72170efb7e1c49ec0c725f403"
ZENODO_MD5 = "8c35d120b65dbd93bc38d07c11b9538b"
ZENODO_BYTE_LENGTH = 5746881

LIB1_MEMBER_PATH = "FowlerLab-TSC2_analysis-9561612/GMM_classifications/TSC2.lib1.gmm.tsv"
LIB2_MEMBER_PATH = "FowlerLab-TSC2_analysis-9561612/GMM_classifications/TSC2.lib2.gmm.tsv"
LIB1_SHA256 = "08841e283e2a59a4013cf9c85aba87c76dac268c2d083753cbff3970bcbe29b4"
LIB1_MD5 = "03c9e3c0e6924832262f7aa89ceddd80"
LIB1_BYTE_LENGTH = 3248988
LIB1_ROW_COUNT = 3567
LIB2_SHA256 = "aec6e4da43096bbb947b1e0cc762913c3f0049c793af4d59b4005da09528be8c"
LIB2_MD5 = "31ba2f9f0f5aeca4cea9047ded48e157"
LIB2_BYTE_LENGTH = 4933368
LIB2_ROW_COUNT = 5540

REFERENCE_ACCESSION = "NC_000016.10"
REFERENCE_ASSEMBLY = "GRCh38"
REFERENCE_FASTA_FILENAME = "NC_000016.10.fasta"
REFERENCE_FASTA_SHA256 = "22dc1bb93de407e0653791c36e4097fbaf64c9efa2510c83b7777f607a61e4d0"
TRANSCRIPT = "NM_000548.5"
ENSEMBL_TRANSCRIPT = "ENST00000219476.9"
GENE = "TSC2"
CHROM = "16"

RUN_NAME = "tsc2-vamp-genomic-crosswalk-2026-09-12"
BUNDLE_ID = "tsc2-vamp-genomic-crosswalk-2026-09-12"
SUMMARY_PATH = REPO_ROOT / "data" / "census" / "tsc2_vamp_genomic_crosswalk_2026-09-12.json"

TOTAL_SCORE_ROWS = 9253
ARCHIVE_CROSSWALK_ROWS = 9107
STATUS_COUNTS = {
    "CROSSWALK_SPDI_VERIFIED": 9050,
    "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 57,
    "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
    "ARCHIVE_CROSSWALK_ABSENT": 146,
}
EXPECTED_COUNTS = {
    "total_score_rows": 9253,
    "archive_crosswalk_rows": 9107,
    "status_counts": STATUS_COUNTS,
}

STATUS_VOCABULARY = {
    "CROSSWALK_SPDI_VERIFIED",
    "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH",
    "SOURCE_COORDINATE_REFERENCE_MISMATCH",
    "ARCHIVE_CROSSWALK_ABSENT",
}
UNRESOLVED_REASON_VOCABULARY = {
    None,
    "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT",
    "SOURCE_REF_DOES_NOT_MATCH_PINNED_FASTA",
    "PROTEIN_VARIANT_NOT_IN_ARCHIVE",
}

GMM_REQUIRED_COLUMNS = [
    "ID",
    "Gene",
    "Chrom",
    "STRAND",
    "hg38_start",
    "hg38_end",
    "ref_allele",
    "alt_allele",
    "hgvs_c",
    "hgvs_p",
    "Ref_seq_transcript_ID",
    "Ensembl_transcript_ID",
]
GMM_IGNORED_COLUMNS = ["abundance_score", "functional_class", "clinical_label", "ps3_evidence"]
VAMP_SCORE_HEADER = ["variant", "score", "standard_error", "rep1", "rep2", "rep3", "functional_class"]

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
FORBIDDEN_SUMMARY_TOKENS = (
    "score_raw",
    "functional_class",
    "auth_reported_score",
    "classification",
    "pathogenic",
    "benign",
    "ps3",
    "bs3",
    "patient",
)


def _load_module(module_name: str):
    try:
        return import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"TSC2 VAMP crosswalk module {module_name!r} is not implemented: {exc}")


def _symbol(module: Any, symbol_name: str):
    if not hasattr(module, symbol_name):
        pytest.fail(f"module {module.__name__!r} is missing public symbol {symbol_name!r}")
    return getattr(module, symbol_name)


def _endpoint_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_vamp_crosswalk.endpoint")
    return {
        "VampCrosswalkEndpointSecurityError": _symbol(module, "VampCrosswalkEndpointSecurityError"),
        "VampCrosswalkTransportValidationError": _symbol(module, "VampCrosswalkTransportValidationError"),
        "build_zenodo_archive_download_url": _symbol(module, "build_zenodo_archive_download_url"),
        "assert_allowed_zenodo_final_url": _symbol(module, "assert_allowed_zenodo_final_url"),
        "fetch_with_transport": _symbol(module, "fetch_with_transport"),
    }


def _archive_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_vamp_crosswalk.archive")
    return {
        "ArchiveValidationError": _symbol(module, "ArchiveValidationError"),
        "validate_zenodo_archive_and_extract_members": _symbol(module, "validate_zenodo_archive_and_extract_members"),
        "parse_gmm_identity_rows": _symbol(module, "parse_gmm_identity_rows"),
    }


def _model_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_vamp_crosswalk.model")
    return {
        "VAMP_GENOMIC_CROSSWALK_ROW_SCHEMA": _symbol(module, "VAMP_GENOMIC_CROSSWALK_ROW_SCHEMA"),
        "ALLOWED_CROSSWALK_STATUSES": _symbol(module, "ALLOWED_CROSSWALK_STATUSES"),
        "ALLOWED_UNRESOLVED_REASONS": _symbol(module, "ALLOWED_UNRESOLVED_REASONS"),
        "CrosswalkContractError": _symbol(module, "CrosswalkContractError"),
        "VampGenomicCrosswalkRow": _symbol(module, "VampGenomicCrosswalkRow"),
    }


def _ingest_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_vamp_crosswalk.ingest")
    return {
        "VampCrosswalkIngestError": _symbol(module, "VampCrosswalkIngestError"),
        "FrozenInputError": _symbol(module, "FrozenInputError"),
        "ReferenceIntegrityError": _symbol(module, "ReferenceIntegrityError"),
        "CrosswalkNormalizationError": _symbol(module, "CrosswalkNormalizationError"),
        "validate_frozen_vamp_scores": _symbol(module, "validate_frozen_vamp_scores"),
        "validate_reference_fasta_checksum": _symbol(module, "validate_reference_fasta_checksum"),
        "build_vamp_genomic_crosswalk": _symbol(module, "build_vamp_genomic_crosswalk"),
    }


def _bundle_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_vamp_crosswalk.bundle")
    return {
        "VampCrosswalkBundleBoundaryError": _symbol(module, "VampCrosswalkBundleBoundaryError"),
        "VampCrosswalkManifestError": _symbol(module, "VampCrosswalkManifestError"),
        "canonical_crosswalk_jsonl_bytes": _symbol(module, "canonical_crosswalk_jsonl_bytes"),
        "compute_manifest_content_hash": _symbol(module, "compute_manifest_content_hash"),
        "validate_manifest_content_hash": _symbol(module, "validate_manifest_content_hash"),
        "build_crosswalk_bundle_manifest": _symbol(module, "build_crosswalk_bundle_manifest"),
        "publish_vamp_crosswalk_bundle": _symbol(module, "publish_vamp_crosswalk_bundle"),
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


def _load_operator_module():
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 VAMP crosswalk operator script is not implemented: {OPERATOR_SCRIPT}")
    spec = importlib.util.spec_from_file_location("raptor_tsc2_vamp_crosswalk_operator_module", OPERATOR_SCRIPT)
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
    return hashlib.md5(blob).hexdigest()  # nosec B303 - matching pinned upstream MD5


def _gzip_tsv(header: list[str], rows: list[list[str]]) -> bytes:
    text = "\n".join(["\t".join(header), *["\t".join(map(str, row)) for row in rows]]) + "\n"
    return gzip.compress(text.encode("utf-8"))


def _tsv_text(header: list[str], rows: list[list[str]], *, line_ending: str = "\n") -> str:
    return line_ending.join(["\t".join(header), *["\t".join(map(str, row)) for row in rows]]) + line_ending


def _build_zip(entries: list[tuple[str, bytes, bool]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload, as_symlink in entries:
            if as_symlink:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (0o120777 << 16)
                zf.writestr(info, payload)
            else:
                zf.writestr(name, payload)
    return buffer.getvalue()


def _synthetic_archive_fixture() -> dict[str, Any]:
    header = [*GMM_REQUIRED_COLUMNS, *GMM_IGNORED_COLUMNS]
    lib1_rows = [
        [
            "lib1-1",
            GENE,
            CHROM,
            "+",
            "2065519.0",
            "2065519.0",
            "G",
            "A",
            "c.1600G>A",
            "p.Gly534Arg",
            TRANSCRIPT,
            ENSEMBL_TRANSCRIPT,
            "0.11",
            "damaging",
            "none",
            "none",
        ]
    ]
    lib2_rows = [
        [
            "lib2-1",
            GENE,
            CHROM,
            "+",
            "2065546",
            "2065548",
            "CCG",
            "TGA",
            "c.1627_1629delinsTGA",
            "p.Pro543Ter",
            TRANSCRIPT,
            ENSEMBL_TRANSCRIPT,
            "-0.64",
            "lof",
            "none",
            "none",
        ]
    ]
    lib1_payload = _tsv_text(header, lib1_rows).encode("utf-8")
    lib2_payload = _tsv_text(header, lib2_rows).encode("utf-8")
    archive_bytes = _build_zip(
        [
            (LIB1_MEMBER_PATH, lib1_payload, False),
            (LIB2_MEMBER_PATH, lib2_payload, False),
        ]
    )
    return {
        "archive_bytes": archive_bytes,
        "archive_pins": {
            "record_id": ZENODO_RECORD_ID,
            "filename": ZENODO_FILENAME,
            "download_url": ZENODO_DOWNLOAD_URL,
            "byte_length": len(archive_bytes),
            "md5": _md5(archive_bytes),
            "sha256": _sha256(archive_bytes),
        },
        "required_members": {
            "library1": {
                "path": LIB1_MEMBER_PATH,
                "byte_length": len(lib1_payload),
                "md5": _md5(lib1_payload),
                "sha256": _sha256(lib1_payload),
                "row_count": 1,
            },
            "library2": {
                "path": LIB2_MEMBER_PATH,
                "byte_length": len(lib2_payload),
                "md5": _md5(lib2_payload),
                "sha256": _sha256(lib2_payload),
                "row_count": 1,
            },
        },
    }


def _synthetic_scores_fixture() -> dict[str, Any]:
    rows = [
        [f"{PROTEIN_ACCESSION}:p.Gly534Arg", "0.62", "0.03", "0.60", "0.63", "0.63", "damaging"],
        [f"{PROTEIN_ACCESSION}:p.Met600Val", "0.02", "0.01", "0.03", "0.02", "0.01", "neutral"],
        [f"{PROTEIN_ACCESSION}:p.Pro543Ter", "-0.70", "0.02", "-0.72", "-0.70", "-0.69", "lof"],
    ]
    payload = _gzip_tsv(VAMP_SCORE_HEADER, rows)
    return {
        "rows": rows,
        "payload": payload,
        "pins": {
            "sha256": _sha256(payload),
            "md5": _md5(payload),
            "byte_length": len(payload),
            "row_count": 3,
            "protein_accession": PROTEIN_ACCESSION,
        },
    }


def _synthetic_scores_fixture_from_tokens(tokens: list[str]) -> dict[str, Any]:
    rows: list[list[str]] = []
    for token in tokens:
        rows.append([token, "0.10", "0.01", "0.10", "0.10", "0.10", "neutral"])
    payload = _gzip_tsv(VAMP_SCORE_HEADER, rows)
    return {
        "rows": rows,
        "payload": payload,
        "pins": {
            "sha256": _sha256(payload),
            "md5": _md5(payload),
            "byte_length": len(payload),
            "row_count": len(rows),
            "protein_accession": PROTEIN_ACCESSION,
        },
    }


def _synthetic_archive_fixture_from_rows(
    *,
    lib1_rows: list[list[str]],
    lib2_rows: list[list[str]],
) -> dict[str, Any]:
    header = [*GMM_REQUIRED_COLUMNS, *GMM_IGNORED_COLUMNS]
    lib1_payload = _tsv_text(header, lib1_rows).encode("utf-8")
    lib2_payload = _tsv_text(header, lib2_rows).encode("utf-8")
    archive_bytes = _build_zip(
        [
            (LIB1_MEMBER_PATH, lib1_payload, False),
            (LIB2_MEMBER_PATH, lib2_payload, False),
        ]
    )
    return {
        "archive_bytes": archive_bytes,
        "archive_pins": {
            "record_id": ZENODO_RECORD_ID,
            "filename": ZENODO_FILENAME,
            "download_url": ZENODO_DOWNLOAD_URL,
            "byte_length": len(archive_bytes),
            "md5": _md5(archive_bytes),
            "sha256": _sha256(archive_bytes),
        },
        "required_members": {
            "library1": {
                "path": LIB1_MEMBER_PATH,
                "byte_length": len(lib1_payload),
                "md5": _md5(lib1_payload),
                "sha256": _sha256(lib1_payload),
                "row_count": len(lib1_rows),
            },
            "library2": {
                "path": LIB2_MEMBER_PATH,
                "byte_length": len(lib2_payload),
                "md5": _md5(lib2_payload),
                "sha256": _sha256(lib2_payload),
                "row_count": len(lib2_rows),
            },
        },
    }


def _minimal_crosswalk_row(*, source_row: int, status: str, protein_variant: str) -> dict[str, Any]:
    verified = status == "CROSSWALK_SPDI_VERIFIED"
    cdna_length_mismatch = status == "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH"
    mismatch = status == "SOURCE_COORDINATE_REFERENCE_MISMATCH"
    absent = status == "ARCHIVE_CROSSWALK_ABSENT"
    assert verified or cdna_length_mismatch or mismatch or absent
    return {
        "schema": CROSSWALK_SCHEMA,
        "source_id": SOURCE_ID,
        "source_row": source_row,
        "protein_variant": protein_variant,
        "archive_member": "library1" if not absent else None,
        "archive_row": 1 if not absent else None,
        "transcript": TRANSCRIPT if not absent else None,
        "hgvs_c": "c.1600G>A" if not absent else None,
        "assembly": REFERENCE_ASSEMBLY if verified else None,
        "genomic_spdi": "NC_000016.10:2065518:G:A" if verified else None,
        "status": status,
        "unresolved_reason": (
            None
            if verified
            else "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT"
            if cdna_length_mismatch
            else "SOURCE_REF_DOES_NOT_MATCH_PINNED_FASTA"
            if mismatch
            else "PROTEIN_VARIANT_NOT_IN_ARCHIVE"
        ),
    }


def _mk_normalized_variant(model_api: dict[str, Any], raw: Any, *, variant_id: str) -> Any:
    return model_api["NormalizedVariant"](
        variant_id=variant_id,
        hgvs_g=f"{raw.chromosome}:g.{raw.position}{raw.ref}>{raw.alt}",
        hgvs_c=None,
        hgvs_p=None,
        hgvs_c_null_reason="not_required_for_crosswalk_slice",
        hgvs_p_null_reason="not_required_for_crosswalk_slice",
        variant_class=model_api["VariantClass"].SNV if len(raw.ref) == 1 and len(raw.alt) == 1 else model_api["VariantClass"].MNV,
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
        run_id="vamp-crosswalk-test",
    )


def test_vx00_binding_spec_exists_and_is_v1_0_4() -> None:
    if not SPEC_PATH.is_file():
        pytest.fail(f"binding spec is missing: {SPEC_PATH}")
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["spec_id"] == "raptor-v2-vamp-genomic-crosswalk-acquisition-v1"
    assert spec["spec_version"] == "1.0.4"


def test_vx01_zenodo_url_builder_and_allowlist_binding_contract() -> None:
    api = _endpoint_api()
    url = api["build_zenodo_archive_download_url"](record_id=ZENODO_RECORD_ID, filename=ZENODO_FILENAME)
    assert url == ZENODO_DOWNLOAD_URL
    parts = urlsplit(url)
    assert parts.scheme == "https"
    assert parts.netloc == "zenodo.org"
    assert parts.query == ""
    encoded_resource = parts.path.split("/files/")[1].split("/content")[0]
    assert unquote(encoded_resource) == ZENODO_FILENAME

    api["assert_allowed_zenodo_final_url"](requested_url=url, final_url=url)
    err = api["VampCrosswalkEndpointSecurityError"]
    with pytest.raises(err):
        api["assert_allowed_zenodo_final_url"](requested_url=url, final_url=url.replace("zenodo.org", "evil.example.org"))
    with pytest.raises(err):
        api["assert_allowed_zenodo_final_url"](
            requested_url=url, final_url=url.replace("TSC2_analysis-V1.zip", "TSC2_analysis-V2.zip")
        )
    with pytest.raises(err):
        api["assert_allowed_zenodo_final_url"](requested_url=url, final_url=url + "?download=1")


def test_vx02_transport_result_is_typed_200_bytes_and_error_messages_are_sanitized() -> None:
    api = _endpoint_api()
    payload = b"PK\x03\x04synthetic-zip"

    def ok_transport(_url: str) -> dict[str, Any]:
        return {
            "final_url": ZENODO_DOWNLOAD_URL,
            "http_status": 200,
            "media_type": "application/zip",
            "body": payload,
        }

    result = api["fetch_with_transport"](requested_url=ZENODO_DOWNLOAD_URL, transport=ok_transport)
    assert result["final_url"] == ZENODO_DOWNLOAD_URL
    assert result["http_status"] == 200
    assert result["byte_length"] == len(payload)
    assert result["sha256"] == _sha256(payload)

    err = api["VampCrosswalkTransportValidationError"]
    for malformed in (
        {"http_status": 200, "media_type": "application/zip", "body": payload},
        {"final_url": ZENODO_DOWNLOAD_URL, "http_status": 302, "media_type": "application/zip", "body": payload},
        {"final_url": ZENODO_DOWNLOAD_URL, "http_status": 200, "media_type": "", "body": payload},
        {"final_url": ZENODO_DOWNLOAD_URL, "http_status": 200, "media_type": "application/zip", "body": "x"},
    ):
        with pytest.raises(err):
            api["fetch_with_transport"](requested_url=ZENODO_DOWNLOAD_URL, transport=lambda _u, m=malformed: m)

    class SecretTransportError(RuntimeError):
        pass

    def bad_transport(_url: str) -> dict[str, Any]:
        raise SecretTransportError("api_key=SECRET should not leak")

    with pytest.raises(err) as raised:
        api["fetch_with_transport"](requested_url=ZENODO_DOWNLOAD_URL, transport=bad_transport)
    assert "SECRET" not in str(raised.value)


def test_vx03_archive_hash_size_and_member_pin_validation_with_safe_zip_handling() -> None:
    api = _archive_api()
    fixture = _synthetic_archive_fixture()

    extracted = api["validate_zenodo_archive_and_extract_members"](
        archive_bytes=fixture["archive_bytes"],
        expected_archive=fixture["archive_pins"],
        required_members=fixture["required_members"],
    )
    assert set(extracted) == {"library1", "library2"}
    assert all(isinstance(blob, bytes) and blob for blob in extracted.values())

    err = api["ArchiveValidationError"]

    with pytest.raises(err):
        api["validate_zenodo_archive_and_extract_members"](
            archive_bytes=fixture["archive_bytes"] + b"x",
            expected_archive=fixture["archive_pins"],
            required_members=fixture["required_members"],
        )
    bad_archive = deepcopy(fixture["archive_pins"])
    bad_archive["sha256"] = "0" * 64
    with pytest.raises(err):
        api["validate_zenodo_archive_and_extract_members"](
            archive_bytes=fixture["archive_bytes"],
            expected_archive=bad_archive,
            required_members=fixture["required_members"],
        )

    lib1_text = b"ID\tGene\tChrom\nx\tTSC2\t16\n"
    lib2_text = b"ID\tGene\tChrom\nx\tTSC2\t16\n"
    traversal_zip = _build_zip(
        [
            (LIB1_MEMBER_PATH, lib1_text, False),
            (LIB2_MEMBER_PATH, lib2_text, False),
            ("../../escape.tsv", lib2_text, False),
        ]
    )
    with pytest.raises(err):
        api["validate_zenodo_archive_and_extract_members"](
            archive_bytes=traversal_zip,
            expected_archive={
                **fixture["archive_pins"],
                "byte_length": len(traversal_zip),
                "sha256": _sha256(traversal_zip),
                "md5": _md5(traversal_zip),
            },
            required_members=fixture["required_members"],
        )

    duplicate_zip = _build_zip(
        [
            (LIB1_MEMBER_PATH, lib1_text, False),
            (LIB1_MEMBER_PATH, lib2_text, False),
            (LIB2_MEMBER_PATH, lib2_text, False),
        ]
    )
    with pytest.raises(err):
        api["validate_zenodo_archive_and_extract_members"](
            archive_bytes=duplicate_zip,
            expected_archive={
                **fixture["archive_pins"],
                "byte_length": len(duplicate_zip),
                "sha256": _sha256(duplicate_zip),
                "md5": _md5(duplicate_zip),
            },
            required_members=fixture["required_members"],
        )

    symlink_zip = _build_zip(
        [
            (LIB1_MEMBER_PATH, lib1_text, True),
            (LIB2_MEMBER_PATH, lib2_text, False),
        ]
    )
    with pytest.raises(err):
        api["validate_zenodo_archive_and_extract_members"](
            archive_bytes=symlink_zip,
            expected_archive={
                **fixture["archive_pins"],
                "byte_length": len(symlink_zip),
                "sha256": _sha256(symlink_zip),
                "md5": _md5(symlink_zip),
            },
            required_members={
                "library1": {
                    "path": LIB1_MEMBER_PATH,
                    "byte_length": len(lib1_text),
                    "md5": _md5(lib1_text),
                    "sha256": _sha256(lib1_text),
                    "row_count": 1,
                },
                "library2": {
                    "path": LIB2_MEMBER_PATH,
                    "byte_length": len(lib2_text),
                    "md5": _md5(lib2_text),
                    "sha256": _sha256(lib2_text),
                    "row_count": 1,
                },
            },
        )


def test_vx04_parse_gmm_members_requires_exact_columns_pins_and_uniqueness_but_ignores_nonrequired_fields() -> None:
    archive_api = _archive_api()
    fixture = _synthetic_archive_fixture()
    members = archive_api["validate_zenodo_archive_and_extract_members"](
        archive_bytes=fixture["archive_bytes"],
        expected_archive=fixture["archive_pins"],
        required_members=fixture["required_members"],
    )
    rows = archive_api["parse_gmm_identity_rows"](
        members=members,
        required_columns=GMM_REQUIRED_COLUMNS,
        required_values={
            "Gene": GENE,
            "Chrom": CHROM,
            "Ref_seq_transcript_ID": TRANSCRIPT,
            "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
        },
    )
    assert len(rows) == 2
    assert [row["protein_variant"] for row in rows] == ["p.Gly534Arg", "p.Pro543Ter"]
    assert [row["hgvs_c"] for row in rows] == ["c.1600G>A", "c.1627_1629delinsTGA"]
    assert all("functional_class" not in row for row in rows)
    assert all("clinical_label" not in row for row in rows)
    assert rows[0]["source_start"] == 2065519
    assert rows[0]["source_end"] == 2065519

    crlf_members = {
        "library1": _tsv_text(
            [*GMM_REQUIRED_COLUMNS, *GMM_IGNORED_COLUMNS],
            [
                [
                    "lib1-crlf",
                    GENE,
                    CHROM,
                    "+",
                    "2065519.0",
                    "2065519.0",
                    "G",
                    "A",
                    "c.1600G>A",
                    "p.Gly534Arg",
                    TRANSCRIPT,
                    ENSEMBL_TRANSCRIPT,
                    "0.21",
                    "damaging",
                    "none",
                    "none",
                ]
            ],
            line_ending="\r\n",
        ).encode("utf-8"),
        "library2": _tsv_text(
            [*GMM_REQUIRED_COLUMNS, *GMM_IGNORED_COLUMNS],
            [
                [
                    "lib2-crlf",
                    GENE,
                    CHROM,
                    "+",
                    "2065546",
                    "2065548",
                    "CCG",
                    "TGA",
                    "c.1627_1629delinsTGA",
                    "p.Pro543Ter",
                    TRANSCRIPT,
                    ENSEMBL_TRANSCRIPT,
                    "-0.60",
                    "lof",
                    "none",
                    "none",
                ]
            ],
            line_ending="\r\n",
        ).encode("utf-8"),
    }
    crlf_rows = archive_api["parse_gmm_identity_rows"](
        members=crlf_members,
        required_columns=GMM_REQUIRED_COLUMNS,
        required_values={
            "Gene": GENE,
            "Chrom": CHROM,
            "Ref_seq_transcript_ID": TRANSCRIPT,
            "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
        },
    )
    assert [row["protein_variant"] for row in crlf_rows] == ["p.Gly534Arg", "p.Pro543Ter"]
    assert all("\r" not in row["protein_variant"] for row in crlf_rows)
    assert all("\r" not in row["hgvs_c"] for row in crlf_rows)

    err = archive_api["ArchiveValidationError"]
    bad_header_text = _tsv_text(["ID", "Gene", "Chrom"], [["x", "TSC2", "16"]]).encode("utf-8")
    with pytest.raises(err):
        archive_api["parse_gmm_identity_rows"](
            members={"library1": bad_header_text, "library2": bad_header_text},
            required_columns=GMM_REQUIRED_COLUMNS,
            required_values={
                "Gene": GENE,
                "Chrom": CHROM,
                "Ref_seq_transcript_ID": TRANSCRIPT,
                "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
            },
        )
    dup_payload = _tsv_text(
        [*GMM_REQUIRED_COLUMNS, *GMM_IGNORED_COLUMNS],
        [
            [
                "id1",
                GENE,
                CHROM,
                "+",
                "2065519",
                "2065519",
                "G",
                "A",
                "c.1600G>A",
                "p.Gly534Arg",
                TRANSCRIPT,
                ENSEMBL_TRANSCRIPT,
                "0.1",
                "x",
                "y",
                "z",
            ],
            [
                "id2",
                GENE,
                CHROM,
                "+",
                "2065520",
                "2065520",
                "A",
                "G",
                "c.1601A>G",
                "p.Gly534Arg",
                TRANSCRIPT,
                ENSEMBL_TRANSCRIPT,
                "0.2",
                "x",
                "y",
                "z",
            ],
        ],
    ).encode("utf-8")
    with pytest.raises(err):
        archive_api["parse_gmm_identity_rows"](
            members={"library1": dup_payload, "library2": bad_header_text},
            required_columns=GMM_REQUIRED_COLUMNS,
            required_values={
                "Gene": GENE,
                "Chrom": CHROM,
                "Ref_seq_transcript_ID": TRANSCRIPT,
                "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
            },
        )


def test_vx05_frozen_vamp_score_pin_header_rowcount_and_exact_protein_token_uniqueness() -> None:
    ingest_api = _ingest_api()
    fixture = _synthetic_scores_fixture()
    parsed = ingest_api["validate_frozen_vamp_scores"](
        score_tsv_gz_bytes=fixture["payload"],
        expected_header=VAMP_SCORE_HEADER,
        expected_sha256=fixture["pins"]["sha256"],
        expected_md5=fixture["pins"]["md5"],
        expected_byte_length=fixture["pins"]["byte_length"],
        expected_rows=fixture["pins"]["row_count"],
        required_protein_accession=fixture["pins"]["protein_accession"],
    )
    assert len(parsed) == 3
    assert [row["source_row"] for row in parsed] == [1, 2, 3]
    assert [row["protein_variant"] for row in parsed] == [r[0] for r in fixture["rows"]]

    err = ingest_api["FrozenInputError"]
    with pytest.raises(err):
        ingest_api["validate_frozen_vamp_scores"](
            score_tsv_gz_bytes=fixture["payload"],
            expected_header=VAMP_SCORE_HEADER,
            expected_sha256="0" * 64,
            expected_md5=fixture["pins"]["md5"],
            expected_byte_length=fixture["pins"]["byte_length"],
            expected_rows=fixture["pins"]["row_count"],
            required_protein_accession=fixture["pins"]["protein_accession"],
        )
    dup_rows = [
        [f"{PROTEIN_ACCESSION}:p.Gly534Arg", "0.62", "0.03", "0.60", "0.63", "0.63", "damaging"],
        [f"{PROTEIN_ACCESSION}:p.Gly534Arg", "0.02", "0.01", "0.03", "0.02", "0.01", "neutral"],
    ]
    dup_payload = _gzip_tsv(VAMP_SCORE_HEADER, dup_rows)
    with pytest.raises(err):
        ingest_api["validate_frozen_vamp_scores"](
            score_tsv_gz_bytes=dup_payload,
            expected_header=VAMP_SCORE_HEADER,
            expected_sha256=_sha256(dup_payload),
            expected_md5=_md5(dup_payload),
            expected_byte_length=len(dup_payload),
            expected_rows=2,
            required_protein_accession=PROTEIN_ACCESSION,
        )


def test_vx06_build_crosswalk_joins_by_full_protein_token_in_score_order_and_conserves_all_rows(tmp_path: Path) -> None:
    ingest_api = _ingest_api()
    ingest_model_api = _ingest_model_api()
    archive_fixture = _synthetic_archive_fixture()
    score_fixture = _synthetic_scores_fixture()
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nNNNNNGCCGNNNNNN\n"
    reference_path.write_bytes(reference_bytes)

    class StubNormalizer:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, Any]] = []

        def normalize(self, raw: Any, cfg: Any) -> Any:
            self.calls.append((raw, cfg))
            return _mk_normalized_variant(
                ingest_model_api,
                raw,
                variant_id=f"{raw.chromosome}:{int(raw.position) - 1}:{raw.ref}:{raw.alt}",
            )

    normalizer = StubNormalizer()
    fasta_calls: list[tuple[str, int, int, str]] = []

    def fasta_checker(*, accession: str, start_1based: int, end_1based: int, expected_ref: str) -> str:
        fasta_calls.append((accession, start_1based, end_1based, expected_ref))
        return expected_ref

    result = ingest_api["build_vamp_genomic_crosswalk"](
        source_id=SOURCE_ID,
        score_tsv_gz_bytes=score_fixture["payload"],
        archive_zip_bytes=archive_fixture["archive_bytes"],
        score_pins={
            "sha256": score_fixture["pins"]["sha256"],
            "md5": score_fixture["pins"]["md5"],
            "byte_length": score_fixture["pins"]["byte_length"],
            "row_count": score_fixture["pins"]["row_count"],
            "protein_accession": PROTEIN_ACCESSION,
        },
        archive_pins={
            **archive_fixture["archive_pins"],
            "required_members": archive_fixture["required_members"],
        },
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        required_columns=GMM_REQUIRED_COLUMNS,
        required_values={
            "Gene": GENE,
            "Chrom": CHROM,
            "Ref_seq_transcript_ID": TRANSCRIPT,
            "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
        },
        transcript=TRANSCRIPT,
        genomic_accession=REFERENCE_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        normalizer=normalizer,
        normalizer_config={"run_id": "vx06"},
        fasta_deleted_allele_checker=fasta_checker,
    )
    rows = result["crosswalk_rows"]
    assert [row["source_row"] for row in rows] == [1, 2, 3]
    assert [row["protein_variant"] for row in rows] == [r[0] for r in score_fixture["rows"]]
    assert [row["status"] for row in rows] == [
        "CROSSWALK_SPDI_VERIFIED",
        "ARCHIVE_CROSSWALK_ABSENT",
        "CROSSWALK_SPDI_VERIFIED",
    ]
    assert rows[0]["genomic_spdi"] == "NC_000016.10:2065518:G:A"
    assert rows[1]["genomic_spdi"] is None and rows[1]["unresolved_reason"] == "PROTEIN_VARIANT_NOT_IN_ARCHIVE"
    assert rows[2]["genomic_spdi"] == "NC_000016.10:2065545:CCG:TGA"
    assert len(rows) == 3
    assert len({row["source_row"] for row in rows}) == 3
    assert result["status_counts"] == {
        "CROSSWALK_SPDI_VERIFIED": 2,
        "ARCHIVE_CROSSWALK_ABSENT": 1,
    }
    assert len(normalizer.calls) == 2
    first_raw, cfg = normalizer.calls[0]
    assert cfg == {"run_id": "vx06"}
    assert first_raw.chromosome == REFERENCE_ACCESSION
    assert first_raw.position == 2065519
    assert first_raw.ref == "G"
    assert first_raw.alt == "A"
    assert first_raw.gene == GENE
    assert fasta_calls == [
        (REFERENCE_ACCESSION, 2065519, 2065519, "G"),
        (REFERENCE_ACCESSION, 2065546, 2065548, "CCG"),
    ]


def test_vx07_reference_checksum_checked_before_normalization_and_manual_outcome_aborts(tmp_path: Path) -> None:
    ingest_api = _ingest_api()
    ingest_model_api = _ingest_model_api()
    archive_fixture = _synthetic_archive_fixture()
    score_fixture = _synthetic_scores_fixture()
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)

    class CountingNormalizer:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, Any]] = []

        def normalize(self, raw: Any, cfg: Any) -> Any:
            self.calls.append((raw, cfg))
            return _mk_manual_queue_item(ingest_model_api, raw, error_code="TRANSCRIPT_MISMATCH")

    normalizer = CountingNormalizer()
    with pytest.raises(ingest_api["ReferenceIntegrityError"]):
        ingest_api["build_vamp_genomic_crosswalk"](
            source_id=SOURCE_ID,
            score_tsv_gz_bytes=score_fixture["payload"],
            archive_zip_bytes=archive_fixture["archive_bytes"],
            score_pins={
                "sha256": score_fixture["pins"]["sha256"],
                "md5": score_fixture["pins"]["md5"],
                "byte_length": score_fixture["pins"]["byte_length"],
                "row_count": score_fixture["pins"]["row_count"],
                "protein_accession": PROTEIN_ACCESSION,
            },
            archive_pins={
                **archive_fixture["archive_pins"],
                "required_members": archive_fixture["required_members"],
            },
            reference_fasta_path=reference_path,
            expected_reference_sha256="0" * 64,
            required_columns=GMM_REQUIRED_COLUMNS,
            required_values={
                "Gene": GENE,
                "Chrom": CHROM,
                "Ref_seq_transcript_ID": TRANSCRIPT,
                "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
            },
            transcript=TRANSCRIPT,
            genomic_accession=REFERENCE_ACCESSION,
            assembly=REFERENCE_ASSEMBLY,
            normalizer=normalizer,
            normalizer_config={"run_id": "vx07"},
            fasta_deleted_allele_checker=lambda **_kwargs: "A",
        )
    assert normalizer.calls == []

    class ManualOutcomeNormalizer:
        def normalize(self, raw: Any, _cfg: Any) -> Any:
            return _mk_manual_queue_item(ingest_model_api, raw, error_code="TRANSCRIPT_MISMATCH")

    with pytest.raises(ingest_api["CrosswalkNormalizationError"]):
        ingest_api["build_vamp_genomic_crosswalk"](
            source_id=SOURCE_ID,
            score_tsv_gz_bytes=score_fixture["payload"],
            archive_zip_bytes=archive_fixture["archive_bytes"],
            score_pins={
                "sha256": score_fixture["pins"]["sha256"],
                "md5": score_fixture["pins"]["md5"],
                "byte_length": score_fixture["pins"]["byte_length"],
                "row_count": score_fixture["pins"]["row_count"],
                "protein_accession": PROTEIN_ACCESSION,
            },
            archive_pins={
                **archive_fixture["archive_pins"],
                "required_members": archive_fixture["required_members"],
            },
            reference_fasta_path=reference_path,
            expected_reference_sha256=_sha256(reference_bytes),
            required_columns=GMM_REQUIRED_COLUMNS,
            required_values={
                "Gene": GENE,
                "Chrom": CHROM,
                "Ref_seq_transcript_ID": TRANSCRIPT,
                "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
            },
            transcript=TRANSCRIPT,
            genomic_accession=REFERENCE_ACCESSION,
            assembly=REFERENCE_ASSEMBLY,
            normalizer=ManualOutcomeNormalizer(),
            normalizer_config={"run_id": "vx07b"},
            fasta_deleted_allele_checker=lambda **kwargs: kwargs["expected_ref"],
        )


def test_vx08_mismatch_and_absent_rows_are_retained_with_null_spdi_and_exact_reasons(tmp_path: Path) -> None:
    ingest_api = _ingest_api()
    ingest_model_api = _ingest_model_api()
    archive_fixture = _synthetic_archive_fixture()
    score_fixture = _synthetic_scores_fixture()
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nACGTACGTACGT\n"
    reference_path.write_bytes(reference_bytes)

    class StubNormalizer:
        def normalize(self, raw: Any, _cfg: Any) -> Any:
            return _mk_normalized_variant(
                ingest_model_api,
                raw,
                variant_id=f"{raw.chromosome}:{int(raw.position) - 1}:{raw.ref}:{raw.alt}",
            )

    mismatch_once = {"done": False}

    def fasta_checker(*, accession: str, start_1based: int, end_1based: int, expected_ref: str) -> str:
        assert accession == REFERENCE_ACCESSION
        assert end_1based - start_1based + 1 == len(expected_ref)
        if not mismatch_once["done"]:
            mismatch_once["done"] = True
            return "T" * len(expected_ref)
        return expected_ref

    result = ingest_api["build_vamp_genomic_crosswalk"](
        source_id=SOURCE_ID,
        score_tsv_gz_bytes=score_fixture["payload"],
        archive_zip_bytes=archive_fixture["archive_bytes"],
        score_pins={
            "sha256": score_fixture["pins"]["sha256"],
            "md5": score_fixture["pins"]["md5"],
            "byte_length": score_fixture["pins"]["byte_length"],
            "row_count": score_fixture["pins"]["row_count"],
            "protein_accession": PROTEIN_ACCESSION,
        },
        archive_pins={
            **archive_fixture["archive_pins"],
            "required_members": archive_fixture["required_members"],
        },
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        required_columns=GMM_REQUIRED_COLUMNS,
        required_values={
            "Gene": GENE,
            "Chrom": CHROM,
            "Ref_seq_transcript_ID": TRANSCRIPT,
            "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
        },
        transcript=TRANSCRIPT,
        genomic_accession=REFERENCE_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        normalizer=StubNormalizer(),
        normalizer_config={"run_id": "vx08"},
        fasta_deleted_allele_checker=fasta_checker,
    )
    rows = result["crosswalk_rows"]
    assert [row["source_row"] for row in rows] == [1, 2, 3]
    assert rows[0]["status"] == "SOURCE_COORDINATE_REFERENCE_MISMATCH"
    assert rows[0]["genomic_spdi"] is None
    assert rows[0]["unresolved_reason"] == "SOURCE_REF_DOES_NOT_MATCH_PINNED_FASTA"
    assert rows[1]["status"] == "ARCHIVE_CROSSWALK_ABSENT"
    assert rows[1]["genomic_spdi"] is None
    assert rows[1]["unresolved_reason"] == "PROTEIN_VARIANT_NOT_IN_ARCHIVE"
    assert len(rows) == 3


def test_vx08b_cross_exon_interval_length_mismatch_is_blocked_before_normalizer(tmp_path: Path) -> None:
    ingest_api = _ingest_api()
    ingest_model_api = _ingest_model_api()
    score_fixture = _synthetic_scores_fixture_from_tokens([f"{PROTEIN_ACCESSION}:p.Pro543Ter"])
    long_ref = "A" * 301
    archive_fixture = _synthetic_archive_fixture_from_rows(
        lib1_rows=[
            [
                "lib1-cross-exon",
                GENE,
                CHROM,
                "+",
                "2065000",
                "2065300",
                long_ref,
                "TGA",
                "c.1627_1629delinsTGA",
                "p.Pro543Ter",
                TRANSCRIPT,
                ENSEMBL_TRANSCRIPT,
                "-0.10",
                "lof",
                "none",
                "none",
            ]
        ],
        lib2_rows=[],
    )
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nA\n"
    reference_path.write_bytes(reference_bytes)

    class GuardNormalizer:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        def normalize(self, raw: Any, cfg: Any) -> Any:
            self.calls.append((raw, cfg))
            return _mk_normalized_variant(
                ingest_model_api,
                raw,
                variant_id=f"{raw.chromosome}:{int(raw.position) - 1}:{raw.ref}:{raw.alt}",
            )

    normalizer = GuardNormalizer()

    result = ingest_api["build_vamp_genomic_crosswalk"](
        source_id=SOURCE_ID,
        score_tsv_gz_bytes=score_fixture["payload"],
        archive_zip_bytes=archive_fixture["archive_bytes"],
        score_pins={
            "sha256": score_fixture["pins"]["sha256"],
            "md5": score_fixture["pins"]["md5"],
            "byte_length": score_fixture["pins"]["byte_length"],
            "row_count": score_fixture["pins"]["row_count"],
            "protein_accession": PROTEIN_ACCESSION,
        },
        archive_pins={
            **archive_fixture["archive_pins"],
            "required_members": archive_fixture["required_members"],
        },
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        required_columns=GMM_REQUIRED_COLUMNS,
        required_values={
            "Gene": GENE,
            "Chrom": CHROM,
            "Ref_seq_transcript_ID": TRANSCRIPT,
            "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
        },
        transcript=TRANSCRIPT,
        genomic_accession=REFERENCE_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        normalizer=normalizer,
        normalizer_config={"run_id": "vx08b"},
        fasta_deleted_allele_checker=lambda **kwargs: kwargs["expected_ref"],
    )
    assert normalizer.calls == []
    row = result["crosswalk_rows"][0]
    assert row["status"] == "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH"
    assert row["unresolved_reason"] == "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT"
    assert row["genomic_spdi"] is None
    assert result["status_counts"] == {"SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 1}


def test_vx08c_accepted_snv_and_delins_require_cdna_genomic_ref_alt_length_equivalence(tmp_path: Path) -> None:
    ingest_api = _ingest_api()
    ingest_model_api = _ingest_model_api()
    score_fixture = _synthetic_scores_fixture_from_tokens(
        [f"{PROTEIN_ACCESSION}:p.Gly534Arg", f"{PROTEIN_ACCESSION}:p.Pro543Ter"]
    )
    archive_fixture = _synthetic_archive_fixture_from_rows(
        lib1_rows=[
            [
                "lib1-snv",
                GENE,
                CHROM,
                "+",
                "2065519",
                "2065519",
                "G",
                "A",
                "c.1600G>A",
                "p.Gly534Arg",
                TRANSCRIPT,
                ENSEMBL_TRANSCRIPT,
                "0.10",
                "neutral",
                "none",
                "none",
            ]
        ],
        lib2_rows=[
            [
                "lib2-delins",
                GENE,
                CHROM,
                "+",
                "2065546",
                "2065548",
                "CCG",
                "TGA",
                "c.1627_1629delinsTGA",
                "p.Pro543Ter",
                TRANSCRIPT,
                ENSEMBL_TRANSCRIPT,
                "-0.10",
                "lof",
                "none",
                "none",
            ]
        ],
    )
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nGCCG\n"
    reference_path.write_bytes(reference_bytes)

    class RecordingNormalizer:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        def normalize(self, raw: Any, cfg: Any) -> Any:
            self.calls.append((raw, cfg))
            return _mk_normalized_variant(
                ingest_model_api,
                raw,
                variant_id=f"{raw.chromosome}:{int(raw.position) - 1}:{raw.ref}:{raw.alt}",
            )

    normalizer = RecordingNormalizer()
    fasta_lengths: list[tuple[int, int, int]] = []

    def fasta_checker(*, accession: str, start_1based: int, end_1based: int, expected_ref: str) -> str:
        assert accession == REFERENCE_ACCESSION
        fasta_lengths.append((end_1based - start_1based + 1, len(expected_ref), len(expected_ref)))
        return expected_ref

    result = ingest_api["build_vamp_genomic_crosswalk"](
        source_id=SOURCE_ID,
        score_tsv_gz_bytes=score_fixture["payload"],
        archive_zip_bytes=archive_fixture["archive_bytes"],
        score_pins={
            "sha256": score_fixture["pins"]["sha256"],
            "md5": score_fixture["pins"]["md5"],
            "byte_length": score_fixture["pins"]["byte_length"],
            "row_count": score_fixture["pins"]["row_count"],
            "protein_accession": PROTEIN_ACCESSION,
        },
        archive_pins={
            **archive_fixture["archive_pins"],
            "required_members": archive_fixture["required_members"],
        },
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        required_columns=GMM_REQUIRED_COLUMNS,
        required_values={
            "Gene": GENE,
            "Chrom": CHROM,
            "Ref_seq_transcript_ID": TRANSCRIPT,
            "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
        },
        transcript=TRANSCRIPT,
        genomic_accession=REFERENCE_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        normalizer=normalizer,
        normalizer_config={"run_id": "vx08c"},
        fasta_deleted_allele_checker=fasta_checker,
    )
    rows = result["crosswalk_rows"]
    assert [row["status"] for row in rows] == ["CROSSWALK_SPDI_VERIFIED", "CROSSWALK_SPDI_VERIFIED"]
    assert len(normalizer.calls) == 2
    raw_snv, _ = normalizer.calls[0]
    raw_delins, _ = normalizer.calls[1]
    assert [row["hgvs_c"] for row in rows] == ["c.1600G>A", "c.1627_1629delinsTGA"]
    cdna_lengths = [1, 3]
    for cdna_length, (interval_length, ref_length, _), raw in zip(
        cdna_lengths, fasta_lengths, (raw_snv, raw_delins), strict=True
    ):
        assert cdna_length == interval_length == ref_length == len(raw.ref) == len(raw.alt)


def test_vx08d_accepted_inv_length_equivalence_is_enforced_when_supported(tmp_path: Path) -> None:
    ingest_api = _ingest_api()
    ingest_module = _load_module("raptor.external.tsc2_vamp_crosswalk.ingest")
    source_text = inspect.getsource(ingest_module).lower()
    if "inv" not in source_text:
        pytest.skip("ingest hgvs_c length parser does not yet advertise inv support")

    ingest_model_api = _ingest_model_api()
    score_fixture = _synthetic_scores_fixture_from_tokens([f"{PROTEIN_ACCESSION}:p.Gly560Val"])
    archive_fixture = _synthetic_archive_fixture_from_rows(
        lib1_rows=[
            [
                "lib1-inv",
                GENE,
                CHROM,
                "+",
                "2065600",
                "2065602",
                "ATG",
                "GTA",
                "c.1681_1683inv",
                "p.Gly560Val",
                TRANSCRIPT,
                ENSEMBL_TRANSCRIPT,
                "0.02",
                "neutral",
                "none",
                "none",
            ]
        ],
        lib2_rows=[],
    )
    reference_path = tmp_path / REFERENCE_FASTA_FILENAME
    reference_bytes = b">NC_000016.10\nATG\n"
    reference_path.write_bytes(reference_bytes)

    class RecordingNormalizer:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        def normalize(self, raw: Any, _cfg: Any) -> Any:
            self.calls.append(raw)
            return _mk_normalized_variant(
                ingest_model_api,
                raw,
                variant_id=f"{raw.chromosome}:{int(raw.position) - 1}:{raw.ref}:{raw.alt}",
            )

    normalizer = RecordingNormalizer()
    fasta_lengths: list[int] = []

    def fasta_checker(*, accession: str, start_1based: int, end_1based: int, expected_ref: str) -> str:
        assert accession == REFERENCE_ACCESSION
        fasta_lengths.append(end_1based - start_1based + 1)
        return expected_ref

    result = ingest_api["build_vamp_genomic_crosswalk"](
        source_id=SOURCE_ID,
        score_tsv_gz_bytes=score_fixture["payload"],
        archive_zip_bytes=archive_fixture["archive_bytes"],
        score_pins={
            "sha256": score_fixture["pins"]["sha256"],
            "md5": score_fixture["pins"]["md5"],
            "byte_length": score_fixture["pins"]["byte_length"],
            "row_count": score_fixture["pins"]["row_count"],
            "protein_accession": PROTEIN_ACCESSION,
        },
        archive_pins={
            **archive_fixture["archive_pins"],
            "required_members": archive_fixture["required_members"],
        },
        reference_fasta_path=reference_path,
        expected_reference_sha256=_sha256(reference_bytes),
        required_columns=GMM_REQUIRED_COLUMNS,
        required_values={
            "Gene": GENE,
            "Chrom": CHROM,
            "Ref_seq_transcript_ID": TRANSCRIPT,
            "Ensembl_transcript_ID": ENSEMBL_TRANSCRIPT,
        },
        transcript=TRANSCRIPT,
        genomic_accession=REFERENCE_ACCESSION,
        assembly=REFERENCE_ASSEMBLY,
        normalizer=normalizer,
        normalizer_config={"run_id": "vx08d"},
        fasta_deleted_allele_checker=fasta_checker,
    )
    assert result["status_counts"] == {"CROSSWALK_SPDI_VERIFIED": 1}
    row = result["crosswalk_rows"][0]
    assert row["genomic_spdi"] is not None
    assert row["hgvs_c"] == "c.1681_1683inv"
    assert len(normalizer.calls) == 1
    raw = normalizer.calls[0]
    assert 3 == len(raw.ref) == len(raw.alt) == fasta_lengths[0]


def test_vx09_crosswalk_row_status_vocabulary_and_invariants() -> None:
    model_api = _model_api()
    assert model_api["VAMP_GENOMIC_CROSSWALK_ROW_SCHEMA"] == CROSSWALK_SCHEMA
    assert set(model_api["ALLOWED_CROSSWALK_STATUSES"]) == STATUS_VOCABULARY
    assert set(model_api["ALLOWED_UNRESOLVED_REASONS"]) == UNRESOLVED_REASON_VOCABULARY

    verified = _minimal_crosswalk_row(source_row=1, status="CROSSWALK_SPDI_VERIFIED", protein_variant=f"{PROTEIN_ACCESSION}:p.Gly534Arg")
    cdna_length_mismatch = _minimal_crosswalk_row(
        source_row=2,
        status="SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH",
        protein_variant=f"{PROTEIN_ACCESSION}:p.Pro543Ter",
    )
    mismatch = _minimal_crosswalk_row(
        source_row=3, status="SOURCE_COORDINATE_REFERENCE_MISMATCH", protein_variant=f"{PROTEIN_ACCESSION}:p.Gly560Val"
    )
    absent = _minimal_crosswalk_row(
        source_row=4, status="ARCHIVE_CROSSWALK_ABSENT", protein_variant=f"{PROTEIN_ACCESSION}:p.Met600Val"
    )

    for row in (verified, cdna_length_mismatch, mismatch, absent):
        built = model_api["VampGenomicCrosswalkRow"](**row).to_dict()
        assert built["source_id"] == SOURCE_ID
        assert built["source_row"] >= 1
        assert built["protein_variant"].startswith(f"{PROTEIN_ACCESSION}:p.")

    broken = deepcopy(verified)
    broken["genomic_spdi"] = None
    with pytest.raises(model_api["CrosswalkContractError"]):
        model_api["VampGenomicCrosswalkRow"](**broken)


def test_vx10_canonical_crosswalk_jsonl_is_deterministic_and_rejects_duplicate_source_rows() -> None:
    bundle_api = _bundle_api()
    model_api = _model_api()
    rows = [
        _minimal_crosswalk_row(source_row=1, status="CROSSWALK_SPDI_VERIFIED", protein_variant=f"{PROTEIN_ACCESSION}:p.Gly534Arg"),
        _minimal_crosswalk_row(source_row=2, status="ARCHIVE_CROSSWALK_ABSENT", protein_variant=f"{PROTEIN_ACCESSION}:p.Met600Val"),
    ]
    shuffled_keys = [dict(reversed(list(row.items()))) for row in rows]
    blob_a = bundle_api["canonical_crosswalk_jsonl_bytes"](rows)
    blob_b = bundle_api["canonical_crosswalk_jsonl_bytes"](shuffled_keys)
    assert blob_a == blob_b
    assert blob_a.endswith(b"\n")
    assert b"\r\n" not in blob_a

    duplicate_rows = [rows[0], deepcopy(rows[0])]
    with pytest.raises(model_api["CrosswalkContractError"]):
        bundle_api["canonical_crosswalk_jsonl_bytes"](duplicate_rows)


def test_vx11_manifest_hash_and_count_conservation_are_enforced() -> None:
    bundle_api = _bundle_api()
    rows = [
        _minimal_crosswalk_row(source_row=1, status="CROSSWALK_SPDI_VERIFIED", protein_variant=f"{PROTEIN_ACCESSION}:p.Gly534Arg"),
        _minimal_crosswalk_row(
            source_row=2,
            status="SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH",
            protein_variant=f"{PROTEIN_ACCESSION}:p.Pro543Ter",
        ),
        _minimal_crosswalk_row(source_row=3, status="ARCHIVE_CROSSWALK_ABSENT", protein_variant=f"{PROTEIN_ACCESSION}:p.Met600Val"),
    ]
    crosswalk_payload = bundle_api["canonical_crosswalk_jsonl_bytes"](rows)
    args = {
        "bundle_id": BUNDLE_ID,
        "created_at": "2026-09-12T00:00:00Z",
        "input_scores": {
            "artifact_id": SCORES_ARTIFACT_ID,
            "sha256": SCORES_SHA256,
            "md5": SCORES_MD5,
            "byte_length": SCORES_BYTE_LENGTH,
            "row_count": SCORES_ROW_COUNT,
        },
        "archive": {
            "record_id": ZENODO_RECORD_ID,
            "doi": ZENODO_DOI,
            "filename": ZENODO_FILENAME,
            "sha256": ZENODO_SHA256,
            "md5": ZENODO_MD5,
            "byte_length": ZENODO_BYTE_LENGTH,
        },
        "reference": {"accession": REFERENCE_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        "artifacts": [
            {
                "artifact_id": "crosswalk-jsonl",
                "relative_path": "crosswalk/igvf_vamp_seq_genomic_crosswalk.jsonl",
                "sha256": _sha256(crosswalk_payload),
                "byte_length": len(crosswalk_payload),
                "row_count": 3,
            }
        ],
        "counts": {"rows": 3, "status_rows": 3},
        "status_counts": {
            "CROSSWALK_SPDI_VERIFIED": 1,
            "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 1,
            "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
            "ARCHIVE_CROSSWALK_ABSENT": 1,
        },
        "boundaries": {"network": "operator_only", "clinical_use": "forbidden", "evidence_strength_use": "forbidden"},
    }
    manifest = bundle_api["build_crosswalk_bundle_manifest"](**args)
    assert manifest["schema"] == BUNDLE_SCHEMA
    assert manifest["content_hash"] == bundle_api["compute_manifest_content_hash"](manifest)
    bundle_api["validate_manifest_content_hash"](manifest)

    drifted = deepcopy(manifest)
    drifted["status_counts"]["ARCHIVE_CROSSWALK_ABSENT"] = 2
    with pytest.raises(bundle_api["VampCrosswalkManifestError"]):
        bundle_api["build_crosswalk_bundle_manifest"](**{**args, "status_counts": drifted["status_counts"]})


def test_vx12_committed_summary_is_aggregate_only_and_omits_sensitive_fields() -> None:
    bundle_api = _bundle_api()
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "bundle_id": BUNDLE_ID,
        "content_hash": "a" * 64,
        "input_scores": {"sha256": SCORES_SHA256, "row_count": SCORES_ROW_COUNT},
        "archive": {"doi": ZENODO_DOI, "sha256": ZENODO_SHA256, "md5": ZENODO_MD5, "byte_length": ZENODO_BYTE_LENGTH},
        "reference": {"sha256": REFERENCE_FASTA_SHA256},
        "counts": {"rows": TOTAL_SCORE_ROWS},
        "status_counts": STATUS_COUNTS,
        "verified_unique_spdi": 9050,
        "follow_on_unresolved": {
            "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 57,
            "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
            "ARCHIVE_CROSSWALK_ABSENT": 146,
        },
        "boundaries": {"clinical_use": "forbidden", "evidence_strength_use": "forbidden"},
        "pacbio_fastq_download": "NO_GO",
    }
    summary = bundle_api["build_committed_summary"](manifest)
    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "archive",
        "input_scores_sha256",
        "reference_sha256",
        "counts",
        "status_counts",
        "verified_unique_spdi",
        "follow_on_unresolved",
        "boundaries",
        "pacbio_fastq_download",
    }
    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["bundle_id"] == BUNDLE_ID
    assert summary["boundaries"] == {"clinical_use": "forbidden", "evidence_strength_use": "forbidden"}
    assert summary["pacbio_fastq_download"] == "NO_GO"
    serialized = json.dumps(summary, sort_keys=True).lower()
    assert "protein_variant" not in serialized
    assert "hgvs_c" not in serialized
    assert "genomic_spdi" not in serialized
    assert not any(token in serialized for token in FORBIDDEN_SUMMARY_TOKENS)


def test_vx13_publication_reuses_hardened_no_clobber_and_refuses_unsafe_paths(tmp_path: Path) -> None:
    bundle_api = _bundle_api()
    source_bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    assert bundle_api["_publish_directory_no_replace"] is _symbol(source_bundle_module, "_publish_directory_no_replace")

    crosswalk_payload = b'{"schema":"x"}\n'
    archive_payload = b"PK\x03\x04zip"
    manifest = bundle_api["build_crosswalk_bundle_manifest"](
        bundle_id=BUNDLE_ID,
        created_at="2026-09-12T00:00:00Z",
        input_scores={
            "artifact_id": SCORES_ARTIFACT_ID,
            "sha256": SCORES_SHA256,
            "md5": SCORES_MD5,
            "byte_length": SCORES_BYTE_LENGTH,
            "row_count": SCORES_ROW_COUNT,
        },
        archive={
            "record_id": ZENODO_RECORD_ID,
            "doi": ZENODO_DOI,
            "filename": ZENODO_FILENAME,
            "sha256": ZENODO_SHA256,
            "md5": ZENODO_MD5,
            "byte_length": ZENODO_BYTE_LENGTH,
        },
        reference={"accession": REFERENCE_ACCESSION, "sha256": REFERENCE_FASTA_SHA256},
        artifacts=[
            {
                "artifact_id": "raw-archive",
                "relative_path": "raw/FowlerLab-TSC2_analysis-V1.zip",
                "sha256": _sha256(archive_payload),
                "byte_length": len(archive_payload),
                "row_count": 0,
            },
            {
                "artifact_id": "crosswalk-jsonl",
                "relative_path": "crosswalk/igvf_vamp_seq_genomic_crosswalk.jsonl",
                "sha256": _sha256(crosswalk_payload),
                "byte_length": len(crosswalk_payload),
                "row_count": 1,
            },
        ],
        counts={"rows": 1, "status_rows": 1},
        status_counts={"ARCHIVE_CROSSWALK_ABSENT": 1},
        boundaries={"network": "operator_only", "clinical_use": "forbidden", "evidence_strength_use": "forbidden"},
    )

    output_root = tmp_path / "external"
    output_root.mkdir()
    preexisting = output_root / RUN_NAME
    preexisting.mkdir()
    repo_root = tmp_path / "repo-preexisting"
    repo_root.mkdir()
    with pytest.raises(bundle_api["VampCrosswalkBundleBoundaryError"]):
        bundle_api["publish_vamp_crosswalk_bundle"](
            repo_root=repo_root,
            output_root=output_root,
            run_name=RUN_NAME,
            manifest=manifest,
            crosswalk_payload=crosswalk_payload,
            archive_payload=archive_payload,
        )
    assert preexisting.exists()
    assert list(preexisting.iterdir()) == []

    inside_repo = tmp_path / "repo-inside"
    inside_repo.mkdir()
    with pytest.raises(bundle_api["VampCrosswalkBundleBoundaryError"]):
        bundle_api["publish_vamp_crosswalk_bundle"](
            repo_root=inside_repo,
            output_root=inside_repo / "not-allowed",
            run_name=RUN_NAME,
            manifest=manifest,
            crosswalk_payload=crosswalk_payload,
            archive_payload=archive_payload,
        )


def test_vx14_package_and_operator_stay_offline_and_block_forbidden_import_domains() -> None:
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
        pytest.fail("TSC2 VAMP crosswalk implementation targets are missing: " + ", ".join(str(path) for path in missing))

    offenders: list[str] = []
    for path in targets:
        for imported, lineno in _module_imports(path):
            lowered = imported.lower()
            if any(lowered == blocked or lowered.startswith(blocked + ".") for blocked in FORBIDDEN_NETWORK_IMPORTS):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
            if any(imported == blocked or imported.startswith(blocked + ".") for blocked in FORBIDDEN_IMPORT_PREFIXES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
    assert not offenders, "forbidden imports detected:\n" + "\n".join(offenders)


def test_vx15_operator_enforces_sequential_pipeline_rate_retry_and_no_fastq_download_paths() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 VAMP crosswalk operator script is not implemented: {OPERATOR_SCRIPT}")
    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    main_node = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"), None)
    if main_node is None:
        pytest.fail("operator script is missing main(argv=...)")

    calls: list[tuple[str, int]] = []
    for node in ast.walk(main_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append((node.func.id, node.lineno))
            elif isinstance(node.func, ast.Attribute):
                calls.append((node.func.attr, node.lineno))

    names = [name for name, _ in calls]
    assert "fetch_with_transport" in names
    assert "validate_zenodo_archive_and_extract_members" in names
    assert "build_vamp_genomic_crosswalk" in names
    assert "publish_vamp_crosswalk_bundle" in names
    assert names.index("fetch_with_transport") < names.index("validate_zenodo_archive_and_extract_members")
    assert names.index("validate_zenodo_archive_and_extract_members") < names.index("build_vamp_genomic_crosswalk")
    assert names.index("build_vamp_genomic_crosswalk") < names.index("publish_vamp_crosswalk_bundle")

    source = OPERATOR_SCRIPT.read_text(encoding="utf-8").lower()
    assert "fastq" not in source
    assert "pacbio" not in source or "no_go" in source
    assert "min_interval_seconds" in source or "sleep(" in source
    assert "retryable_http" in source
    assert "max_attempts_per_request" in source


def test_vx15d_operator_zenodo_transport_uses_pinned_accept_star_and_observes_octet_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator_module()
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    expected_accept = "*/*"

    transport_cls = getattr(operator, "_RateLimitedHttpsTransport", None)
    if transport_cls is None:
        pytest.fail("operator script is missing _RateLimitedHttpsTransport")

    observed: dict[str, Any] = {}
    events: list[str] = []

    class _FakeSocket:
        def settimeout(self, timeout: float) -> None:
            observed["socket_timeout"] = timeout
            events.append("settimeout")

    class _FakeResponse:
        def __init__(self, status: int, media_type: str, body: bytes) -> None:
            self.status = status
            self._media_type = media_type
            self._body = body

        def read(self) -> bytes:
            events.append("read")
            return self._body

        def getheader(self, name: str) -> str:
            if name.lower() == "content-type":
                return self._media_type
            return ""

    class _FakeHTTPSConnection:
        def __init__(self, host: str, timeout: float | None = None, context: Any = None) -> None:
            observed["host"] = host
            observed["constructor_timeout"] = timeout
            observed["context"] = context
            self.sock = _FakeSocket()
            events.append("init")

        def connect(self) -> None:
            observed["connect_called"] = True
            events.append("connect")

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            observed["method"] = method
            observed["path"] = path
            observed["accept"] = headers.get("Accept")
            events.append("request")
            assert headers.get("Accept") == expected_accept

        def getresponse(self) -> _FakeResponse:
            events.append("getresponse")
            media = "application/octet-stream"
            if observed.get("accept") != expected_accept:
                return _FakeResponse(406, media, b"not acceptable")
            return _FakeResponse(200, media, b"PK\x03\x04zip-bytes")

        def close(self) -> None:
            events.append("close")

    monkeypatch.setattr(operator.http.client, "HTTPSConnection", _FakeHTTPSConnection)
    monkeypatch.setattr(operator.time, "sleep", lambda _seconds: None)

    timeout_cfg = config["rate_limits_retries"]["timeout_seconds"]
    connect_timeout = float(timeout_cfg["connect"])
    read_timeout = float(timeout_cfg["read"])
    transport = transport_cls(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        min_interval_seconds=0.0,
        retryable_http=set(config["rate_limits_retries"]["retry_policy"]["retryable_http"]),
        max_attempts_per_request=1,
        backoff_base_seconds=0.0,
        backoff_cap_seconds=0.0,
    )
    response = transport(ZENODO_DOWNLOAD_URL)
    assert response["media_type"] == "application/octet-stream"
    assert observed.get("accept") == expected_accept

    # If the operator implementation explicitly uses separate connect/read
    # socket semantics, verify configured values are honored per role.
    if observed.get("connect_called") and "socket_timeout" in observed:
        assert observed["constructor_timeout"] == connect_timeout
        assert observed["socket_timeout"] == read_timeout


def test_vx15b_operator_expected_pilot_validator_compares_all_axes_and_names_mismatch_axis() -> None:
    operator = _load_operator_module()
    helper = getattr(operator, "_validate_expected_pilot_result", None)
    if helper is None:
        pytest.fail(
            "operator must define _validate_expected_pilot_result(manifest, expected_pilot) "
            "and call it before publish_vamp_crosswalk_bundle"
        )
    domain_error = getattr(operator, "VampCrosswalkOperatorError", RuntimeError)

    manifest = {
        "input_scores": {"row_count": 3},
        "counts": {"rows": 3},
        "status_counts": {
            "CROSSWALK_SPDI_VERIFIED": 2,
            "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 1,
            "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
            "ARCHIVE_CROSSWALK_ABSENT": 0,
        },
        "verified_unique_spdi": 2,
    }
    expected_pilot = {
        "total_score_rows": 3,
        "archive_crosswalk_rows": 3,
        "status_counts": {
            "CROSSWALK_SPDI_VERIFIED": 2,
            "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 1,
            "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
            "ARCHIVE_CROSSWALK_ABSENT": 0,
        },
        "verified_unique_spdi": 2,
        "conservation": {
            "input_score_rows": 3,
            "output_crosswalk_rows": 3,
            "dropped_rows": 0,
            "duplicate_source_rows": 0,
        },
    }
    helper(manifest=deepcopy(manifest), expected_pilot=deepcopy(expected_pilot))

    drifts: list[tuple[str, dict[str, Any]]] = [
        ("total_score_rows", {**expected_pilot, "total_score_rows": 4}),
        ("archive_crosswalk_rows", {**expected_pilot, "archive_crosswalk_rows": 2}),
        (
            "status_counts",
            {
                **expected_pilot,
                "status_counts": {
                    **expected_pilot["status_counts"],
                    "SOURCE_COORDINATE_REFERENCE_MISMATCH": 1,
                },
            },
        ),
        ("verified_unique_spdi", {**expected_pilot, "verified_unique_spdi": 1}),
        (
            "conservation",
            {
                **expected_pilot,
                "conservation": {
                    **expected_pilot["conservation"],
                    "output_crosswalk_rows": 2,
                },
            },
        ),
    ]
    for axis, drifted_expected in drifts:
        with pytest.raises(domain_error) as raised:
            helper(manifest=deepcopy(manifest), expected_pilot=drifted_expected)
        assert axis in str(raised.value)


def test_vx15c_operator_calls_expected_pilot_validator_before_publication() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 VAMP crosswalk operator script is not implemented: {OPERATOR_SCRIPT}")
    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    main_node = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"), None)
    if main_node is None:
        pytest.fail("operator script is missing main(argv=...)")

    first_lines: dict[str, int] = {}
    for node in ast.walk(main_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                first_lines.setdefault(node.func.id, node.lineno)
            elif isinstance(node.func, ast.Attribute):
                first_lines.setdefault(node.func.attr, node.lineno)

    assert "_validate_expected_pilot_result" in first_lines
    assert "publish_vamp_crosswalk_bundle" in first_lines
    assert first_lines["_validate_expected_pilot_result"] < first_lines["publish_vamp_crosswalk_bundle"]


def test_vx15e_operator_expands_sparse_status_counts_with_expected_zeroes_before_manifest_and_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operator = _load_operator_module()

    source_root = tmp_path / "source-root"
    reference_root = tmp_path / "reference-root"
    output_root = tmp_path / "output-root"
    source_root.mkdir(parents=True, exist_ok=True)
    reference_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    source_run_name = "source-run"
    source_relative_path = "igvf/igvf_vamp_seq.tsv.gz"
    source_score_path = source_root / source_run_name / source_relative_path
    source_score_path.parent.mkdir(parents=True, exist_ok=True)
    source_score_path.write_bytes(b"synthetic-vamp-score-bytes")
    (reference_root / REFERENCE_FASTA_FILENAME).write_text(">NC_000016.10\nACGT\n", encoding="utf-8")

    expected_status_counts = {
        "CROSSWALK_SPDI_VERIFIED": 9050,
        "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 57,
        "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
        "ARCHIVE_CROSSWALK_ABSENT": 146,
    }
    observed_sparse_status_counts = {
        "CROSSWALK_SPDI_VERIFIED": 9050,
        "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 57,
        "ARCHIVE_CROSSWALK_ABSENT": 146,
    }
    config = {
        "inputs": {
            "frozen_vamp_scores": {
                "run_name": source_run_name,
                "manifest_filename": "bundle_manifest.json",
                "source_bundle_id": SOURCE_BUNDLE_ID,
                "source_manifest_content_hash": SOURCE_MANIFEST_CONTENT_HASH,
                "artifact_id": SCORES_ARTIFACT_ID,
                "relative_path": source_relative_path,
                "sha256": SCORES_SHA256,
                "md5": SCORES_MD5,
                "byte_length": SCORES_BYTE_LENGTH,
                "row_count": SCORES_ROW_COUNT,
                "protein_accession": PROTEIN_ACCESSION,
            },
            "zenodo_archive": {
                "record_id": ZENODO_RECORD_ID,
                "doi": ZENODO_DOI,
                "filename": ZENODO_FILENAME,
                "download_url": ZENODO_DOWNLOAD_URL,
                "sha256": ZENODO_SHA256,
                "md5": ZENODO_MD5,
                "byte_length": ZENODO_BYTE_LENGTH,
                "required_members": {},
            },
            "genomic_reference": {
                "accession": REFERENCE_ACCESSION,
                "assembly": REFERENCE_ASSEMBLY,
                "fasta_filename": REFERENCE_FASTA_FILENAME,
                "sha256": REFERENCE_FASTA_SHA256,
            },
            "identity_pins": {
                "transcript": TRANSCRIPT,
                "genomic_accession": REFERENCE_ACCESSION,
                "assembly": REFERENCE_ASSEMBLY,
            },
        },
        "archive_table_contract": {"required_columns": list(GMM_REQUIRED_COLUMNS), "required_values": {}},
        "rate_limits_retries": {
            "min_interval_seconds": 0.0,
            "timeout_seconds": {"connect": 1.0, "read": 1.0},
            "retry_policy": {
                "retryable_http": [500],
                "non_retryable_http": [400],
                "max_attempts_per_request": 1,
                "backoff_base_seconds": 0.0,
                "backoff_cap_seconds": 0.0,
            },
        },
        "outputs": {
            "external_bundle": {
                "run_name": RUN_NAME,
                "bundle_id": BUNDLE_ID,
                "artifacts": {
                    "raw_archive": {"relative_path": "raw/FowlerLab-TSC2_analysis-V1.zip"},
                    "crosswalk_jsonl": {"relative_path": "crosswalk/igvf_vamp_seq_genomic_crosswalk.jsonl"},
                },
            }
        },
        "expected_pilot": {
            "total_score_rows": TOTAL_SCORE_ROWS,
            "archive_crosswalk_rows": ARCHIVE_CROSSWALK_ROWS,
            "status_counts": expected_status_counts,
            "verified_unique_spdi": 9050,
            "conservation": {
                "input_score_rows": TOTAL_SCORE_ROWS,
                "output_crosswalk_rows": TOTAL_SCORE_ROWS,
                "dropped_rows": 0,
                "duplicate_source_rows": 0,
            },
        },
    }

    call_order: list[str] = []
    captured: dict[str, Any] = {}

    monkeypatch.setattr(operator, "_load_config", lambda _path: deepcopy(config))
    monkeypatch.setattr(operator, "_read_source_bundle_manifest", lambda _source_root, _config: {})
    monkeypatch.setattr(operator, "_validate_source_bundle_manifest_pin", lambda _manifest, _config: None)
    monkeypatch.setattr(operator, "_resolve_safe_path_in_run_dir", lambda _run_dir, _rel, context: source_score_path)
    monkeypatch.setattr(operator, "validate_reference_fasta_checksum", lambda **_kwargs: None)
    monkeypatch.setattr(operator, "build_zenodo_archive_download_url", lambda **_kwargs: ZENODO_DOWNLOAD_URL)
    monkeypatch.setattr(
        operator,
        "fetch_with_transport",
        lambda **_kwargs: {
            "final_url": ZENODO_DOWNLOAD_URL,
            "http_status": 200,
            "media_type": "application/octet-stream",
            "body": b"PK\x03\x04zip",
        },
    )
    monkeypatch.setattr(operator, "assert_allowed_zenodo_final_url", lambda **_kwargs: None)
    monkeypatch.setattr(operator, "validate_zenodo_archive_and_extract_members", lambda **_kwargs: None)
    monkeypatch.setattr(operator, "SeqRepoGenomicNormalizer", lambda **_kwargs: object())
    monkeypatch.setattr(
        operator,
        "build_vamp_genomic_crosswalk",
        lambda **_kwargs: {
            "crosswalk_rows": [
                _minimal_crosswalk_row(
                    source_row=1,
                    status="CROSSWALK_SPDI_VERIFIED",
                    protein_variant=f"{PROTEIN_ACCESSION}:p.Gly534Arg",
                ),
                _minimal_crosswalk_row(
                    source_row=2,
                    status="ARCHIVE_CROSSWALK_ABSENT",
                    protein_variant=f"{PROTEIN_ACCESSION}:p.Met600Val",
                ),
            ],
            "status_counts": deepcopy(observed_sparse_status_counts),
        },
    )
    monkeypatch.setattr(operator, "canonical_crosswalk_jsonl_bytes", lambda rows: b"".join(b"{}\n" for _ in rows))

    def _capture_manifest_build(**kwargs: Any) -> dict[str, Any]:
        call_order.append("build")
        captured["manifest_input_status_counts"] = deepcopy(kwargs["status_counts"])
        return {
            "schema": BUNDLE_SCHEMA,
            "bundle_id": kwargs["bundle_id"],
            "content_hash": "0" * 64,
            "input_scores": {"row_count": kwargs["input_scores"]["row_count"]},
            "counts": {"rows": kwargs["counts"]["rows"]},
            "status_counts": deepcopy(kwargs["status_counts"]),
            "verified_unique_spdi": kwargs["verified_unique_spdi"],
        }

    def _capture_expected_validation(*, manifest: dict[str, Any], expected_pilot: dict[str, Any]) -> None:
        call_order.append("validate")
        captured["validated_manifest_status_counts"] = deepcopy(manifest["status_counts"])
        captured["expected_status_count_keys"] = tuple(expected_pilot["status_counts"].keys())

    monkeypatch.setattr(operator, "build_crosswalk_bundle_manifest", _capture_manifest_build)
    monkeypatch.setattr(operator, "_validate_expected_pilot_result", _capture_expected_validation)
    monkeypatch.setattr(
        operator,
        "publish_vamp_crosswalk_bundle",
        lambda **_kwargs: call_order.append("publish") or {"run_dir": str(output_root / RUN_NAME)},
    )

    exit_code = operator.main(
        [
            "--config",
            str(tmp_path / "config.yaml"),
            "--source-root",
            str(source_root),
            "--reference-root",
            str(reference_root),
            "--output-root",
            str(output_root),
        ]
    )
    assert exit_code == 0
    assert captured["manifest_input_status_counts"] == expected_status_counts
    assert captured["validated_manifest_status_counts"] == expected_status_counts
    assert set(captured["expected_status_count_keys"]) == set(expected_status_counts)
    assert call_order[:3] == ["build", "validate", "publish"]


def test_vx15f_operator_expected_pilot_rejects_unknown_statuses() -> None:
    operator = _load_operator_module()
    helper = getattr(operator, "_validate_expected_pilot_result", None)
    if helper is None:
        pytest.fail("operator must define _validate_expected_pilot_result(manifest, expected_pilot)")
    domain_error = getattr(operator, "VampCrosswalkOperatorError", RuntimeError)

    manifest = {
        "input_scores": {"row_count": 3},
        "counts": {"rows": 3},
        "status_counts": {
            "CROSSWALK_SPDI_VERIFIED": 2,
            "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 1,
            "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
            "ARCHIVE_CROSSWALK_ABSENT": 0,
            "UNEXPECTED_STATUS": 1,
        },
        "verified_unique_spdi": 2,
    }
    expected_pilot = {
        "total_score_rows": 3,
        "archive_crosswalk_rows": 3,
        "status_counts": {
            "CROSSWALK_SPDI_VERIFIED": 2,
            "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 1,
            "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
            "ARCHIVE_CROSSWALK_ABSENT": 0,
        },
        "verified_unique_spdi": 2,
        "conservation": {
            "input_score_rows": 3,
            "output_crosswalk_rows": 3,
            "dropped_rows": 0,
            "duplicate_source_rows": 0,
        },
    }

    with pytest.raises(domain_error) as raised:
        helper(manifest=manifest, expected_pilot=expected_pilot)
    assert "status_counts" in str(raised.value)


def test_vx16_operator_cli_requires_explicit_roots_without_cwd_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    operator = _load_operator_module()
    for env_name in (
        "RAPTOR_TSC2_SOURCE_ROOT",
        "RAPTOR_TSC2_REFERENCE_ROOT",
        "RAPTOR_TSC2_VAMP_CROSSWALK_ROOT",
    ):
        monkeypatch.delenv(env_name, raising=False)

    cwd_before = os.getcwd()
    exit_code = operator.main(["--config", str(CONFIG_PATH)])
    assert os.getcwd() == cwd_before
    assert exit_code == 1


def test_vx17_config_pins_exact_source_archive_reference_and_expected_status_totals() -> None:
    if not CONFIG_PATH.is_file():
        pytest.fail(f"TSC2 VAMP crosswalk config is not implemented: {CONFIG_PATH}")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["spec_id"] == "raptor-v2-vamp-genomic-crosswalk-acquisition-v1"
    assert config["spec_version"] == "1.0.4"

    source = config["inputs"]["frozen_vamp_scores"]
    assert source["source_bundle_id"] == SOURCE_BUNDLE_ID
    assert source["source_manifest_content_hash"] == SOURCE_MANIFEST_CONTENT_HASH
    assert source["artifact_id"] == SCORES_ARTIFACT_ID
    assert source["relative_path"] == SCORES_RELATIVE_PATH
    assert source["sha256"] == SCORES_SHA256
    assert source["md5"] == SCORES_MD5
    assert source["byte_length"] == SCORES_BYTE_LENGTH
    assert source["row_count"] == SCORES_ROW_COUNT
    assert source["protein_accession"] == PROTEIN_ACCESSION

    archive = config["inputs"]["zenodo_archive"]
    assert archive["record_id"] == ZENODO_RECORD_ID
    assert archive["doi"] == ZENODO_DOI
    assert archive["filename"] == ZENODO_FILENAME
    assert archive["download_url"] == ZENODO_DOWNLOAD_URL
    assert archive["request_accept"] == "*/*"
    assert archive["sha256"] == ZENODO_SHA256
    assert archive["md5"] == ZENODO_MD5
    assert archive["byte_length"] == ZENODO_BYTE_LENGTH
    assert archive["required_members"]["library1"]["path"] == LIB1_MEMBER_PATH
    assert archive["required_members"]["library1"]["sha256"] == LIB1_SHA256
    assert archive["required_members"]["library1"]["md5"] == LIB1_MD5
    assert archive["required_members"]["library1"]["byte_length"] == LIB1_BYTE_LENGTH
    assert archive["required_members"]["library1"]["row_count"] == LIB1_ROW_COUNT
    assert archive["required_members"]["library2"]["path"] == LIB2_MEMBER_PATH
    assert archive["required_members"]["library2"]["sha256"] == LIB2_SHA256
    assert archive["required_members"]["library2"]["md5"] == LIB2_MD5
    assert archive["required_members"]["library2"]["byte_length"] == LIB2_BYTE_LENGTH
    assert archive["required_members"]["library2"]["row_count"] == LIB2_ROW_COUNT

    reference = config["inputs"]["genomic_reference"]
    assert reference["accession"] == REFERENCE_ACCESSION
    assert reference["assembly"] == REFERENCE_ASSEMBLY
    assert reference["fasta_filename"] == REFERENCE_FASTA_FILENAME
    assert reference["sha256"] == REFERENCE_FASTA_SHA256

    assert config["go_no_go"]["pacbio_fastq_download"] == "NO_GO"
    assert config["outputs"]["external_bundle"]["run_name"] == RUN_NAME
    assert config["outputs"]["external_bundle"]["bundle_id"] == BUNDLE_ID
    assert config["outputs"]["committed_summary"]["path"] == str(SUMMARY_PATH.relative_to(REPO_ROOT)).replace("\\", "/")
    assert config["outputs"]["committed_summary"]["schema"] == SUMMARY_SCHEMA

    expected = config["expected_pilot"]
    assert expected["total_score_rows"] == TOTAL_SCORE_ROWS
    assert expected["archive_crosswalk_rows"] == ARCHIVE_CROSSWALK_ROWS
    assert expected["status_counts"] == STATUS_COUNTS
    assert expected["verified_unique_spdi"] == STATUS_COUNTS["CROSSWALK_SPDI_VERIFIED"]
    assert expected["conservation"]["input_score_rows"] == TOTAL_SCORE_ROWS
    assert expected["conservation"]["output_crosswalk_rows"] == TOTAL_SCORE_ROWS
    assert expected["conservation"]["dropped_rows"] == 0
    assert expected["conservation"]["duplicate_source_rows"] == 0


def test_vx18_committed_summary_exists_and_matches_final_pilot_contract_without_row_level_content() -> None:
    if not SUMMARY_PATH.is_file():
        pytest.fail(f"committed summary is missing: {SUMMARY_PATH}")

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "archive",
        "input_scores_sha256",
        "reference_sha256",
        "counts",
        "status_counts",
        "verified_unique_spdi",
        "follow_on_unresolved",
        "boundaries",
        "pacbio_fastq_download",
    }
    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["bundle_id"] == BUNDLE_ID
    assert summary["manifest_content_hash"] == "f80759aa43874d201efb69c52b611d9ebd8c40712159bf1f291c86195dd33ba0"
    assert summary["archive"] == {
        "record_id": ZENODO_RECORD_ID,
        "doi": ZENODO_DOI,
        "filename": "FowlerLab/TSC2_analysis-V1.zip",
        "sha256": ZENODO_SHA256,
        "md5": ZENODO_MD5,
        "byte_length": ZENODO_BYTE_LENGTH,
    }
    assert summary["input_scores_sha256"] == SCORES_SHA256
    assert summary["reference_sha256"] == REFERENCE_FASTA_SHA256
    assert summary["counts"] == {"rows": TOTAL_SCORE_ROWS, "status_rows": TOTAL_SCORE_ROWS}
    assert summary["status_counts"] == STATUS_COUNTS
    assert summary["verified_unique_spdi"] == STATUS_COUNTS["CROSSWALK_SPDI_VERIFIED"]
    assert summary["follow_on_unresolved"] == {
        "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": STATUS_COUNTS["SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH"],
        "SOURCE_COORDINATE_REFERENCE_MISMATCH": STATUS_COUNTS["SOURCE_COORDINATE_REFERENCE_MISMATCH"],
        "ARCHIVE_CROSSWALK_ABSENT": STATUS_COUNTS["ARCHIVE_CROSSWALK_ABSENT"],
    }
    assert summary["pacbio_fastq_download"] == "NO_GO"
    assert summary["boundaries"] == {
        "clinical_use": "forbidden",
        "evidence_strength_use": "forbidden",
        "network": "operator_only",
    }

    serialized = json.dumps(summary, sort_keys=True).lower()
    forbidden_row_tokens = (
        "protein_variant",
        "hgvs_c",
        "hgvs_p",
        "tx_spdi",
        "genomic_spdi",
        "score_raw",
        "functional_class",
        "auth_reported_score",
        "classification",
        "pathogenic",
        "benign",
        "ps3",
        "bs3",
    )
    assert not any(token in serialized for token in forbidden_row_tokens)
