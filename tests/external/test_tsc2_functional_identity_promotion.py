from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-functional-identity-promotion-v1.yaml"
CONFIG_PATH = REPO_ROOT / "configs" / "external" / "tsc2_functional_identity_promotion_v1.yaml"
OPERATOR_SCRIPT = REPO_ROOT / "scripts" / "promote_tsc2_functional_identities.py"
PACKAGE_ROOT = REPO_ROOT / "src" / "raptor" / "external" / "tsc2_identity_promotion"

NORMALIZED_ROW_SCHEMA = "raptor.external.normalized_functional_row.v1"
CLIPE_MAPPING_SCHEMA = "raptor.external.clipe_cdna_spdi_mapping_row.v1"
VAMP_CROSSWALK_SCHEMA = "raptor.external.vamp_genomic_crosswalk_row.v1"
PROMOTION_BUNDLE_SCHEMA = "raptor.external.tsc2_functional_identity_promotion_bundle.v1"
PROMOTION_SUMMARY_SCHEMA = "raptor.external.tsc2_functional_identity_promotion_summary.v1"

GENE = "TSC2"
TRANSCRIPT = "NM_000548.5"
GENOMIC_ACCESSION = "NC_000016.10"
ASSEMBLY = "GRCh38"
VAMP_PROTEIN_ACCESSION = "ENSP00000219476.3"

FUNCTIONAL_RUN_NAME = "tsc2-functional-identity-normalization-pilot-2026-09-11"
FUNCTIONAL_BUNDLE_ID = "tsc2-functional-identity-normalization-pilot-2026-09-11"
FUNCTIONAL_MANIFEST_HASH = "74f15f22cfb6e876a8fab3a16c841e6f33317eadd58ef04547e4c060162afb48"
FUNCTIONAL_MAVEDB_RELATIVE_PATH = "normalized/mavedb_clipe.jsonl"
FUNCTIONAL_MAVEDB_SHA256 = "2328f46bf5a2ae087eddeaa2ad0fb6f44de2b60a2e9e3ad0c034c73907f5031e"
FUNCTIONAL_MAVEDB_BYTE_LENGTH = 102100
FUNCTIONAL_MAVEDB_ROWS = 208
FUNCTIONAL_VAMP_RELATIVE_PATH = "normalized/igvf_vamp_seq.jsonl"
FUNCTIONAL_VAMP_SHA256 = "26f34a7a8d52d01ffbdef50427ac1ab0b268a523a29a55ce77452fc56bb83adb"
FUNCTIONAL_VAMP_BYTE_LENGTH = 4522418
FUNCTIONAL_VAMP_ROWS = 9253
FUNCTIONAL_SGE_RELATIVE_PATH = "normalized/igvf_sge.jsonl"
FUNCTIONAL_SGE_SHA256 = "2292e5770911e13fcd2536287fd04fc7f23354c9bc81ebf01533aa441114ea52"
FUNCTIONAL_SGE_BYTE_LENGTH = 227381
FUNCTIONAL_SGE_ROWS = 453

CLIPE_RUN_NAME = "tsc2-clipe-cdna-spdi-projector-2026-09-12"
CLIPE_BUNDLE_ID = "tsc2-clipe-cdna-spdi-projector-2026-09-12"
CLIPE_MANIFEST_HASH = "247665b9758860124b196d037b913626b7699b87ba1bb1c32b0e461bb4473529"
CLIPE_MAPPING_RELATIVE_PATH = "mapping/mavedb_clipe_nm000548_5_to_nc000016_10.jsonl"
CLIPE_MAPPING_SHA256 = "44c75161b77d15a3eff53b576d9b1ac0264365169ea9f42d4581461e0759db7d"
CLIPE_MAPPING_BYTE_LENGTH = 143028
CLIPE_MAPPING_ROWS = 208

VAMP_RUN_NAME = "tsc2-vamp-genomic-crosswalk-2026-09-12"
VAMP_BUNDLE_ID = "tsc2-vamp-genomic-crosswalk-2026-09-12"
VAMP_MANIFEST_HASH = "f80759aa43874d201efb69c52b611d9ebd8c40712159bf1f291c86195dd33ba0"
VAMP_CROSSWALK_RELATIVE_PATH = "crosswalk/igvf_vamp_seq_genomic_crosswalk.jsonl"
VAMP_CROSSWALK_SHA256 = "e8c2c6aea9039586f2c7244d36fcf4629a0a99ac91bd4c469038430c34aa9896"
VAMP_CROSSWALK_BYTE_LENGTH = 3558841
VAMP_CROSSWALK_ROWS = 9253

OUTPUT_RUN_NAME = "tsc2-functional-identity-promotion-2026-09-14"
OUTPUT_BUNDLE_ID = "tsc2-functional-identity-promotion-2026-09-14"
SUMMARY_PATH = REPO_ROOT / "data" / "census" / "tsc2_functional_identity_promotion_2026-09-14.json"
PROMOTED_ARTIFACTS = [
    ("mavedb_clipe-promoted-jsonl", "normalized/mavedb_clipe.jsonl"),
    ("igvf_vamp_seq-promoted-jsonl", "normalized/igvf_vamp_seq.jsonl"),
    ("igvf_sge-promoted-jsonl", "normalized/igvf_sge.jsonl"),
]

EXPECTED_TOTAL_ROWS = 9914
EXPECTED_SOURCE_ROWS = {"mavedb_clipe": 208, "igvf_vamp_seq": 9253, "igvf_sge": 453}
EXPECTED_IDENTITY_STATE_COUNTS = {
    "GENOMIC_SPDI_VERIFIED": 9681,
    "GENOMIC_REFERENCE_MISMATCH": 27,
    "GENOMIC_CROSSWALK_LENGTH_MISMATCH": 57,
    "PROTEIN_ONLY_ARCHIVE_CROSSWALK_ABSENT": 146,
    "REFERENCE_CONTROL": 3,
    "TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 0,
    "PROTEIN_ONLY_CROSSWALK_REQUIRED": 0,
}
EXPECTED_UNRESOLVED_REASON_COUNTS = {
    "REFERENCE_ALLELE_MISMATCH": 27,
    "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT": 57,
    "PROTEIN_VARIANT_NOT_IN_ARCHIVE": 146,
    "NOT_A_VARIANT": 3,
    "CDNA_PROJECTOR_REQUIRED": 0,
    "NUCLEOTIDE_CROSSWALK_REQUIRED": 0,
}
EXPECTED_VARIANT_KIND_COUNTS = {
    "MISSENSE": 9340,
    "SYNONYMOUS": 496,
    "STOP_GAINED": 63,
    "OTHER": 12,
    "REFERENCE_CONTROL": 3,
}
EXPECTED_VERIFIED_BY_SOURCE = {"mavedb_clipe": 208, "igvf_vamp_seq": 9050, "igvf_sge": 423}
EXPECTED_VERIFIED_OBSERVATIONS = 9681
EXPECTED_VERIFIED_UNIQUE_SPDI = 9552
EXPECTED_DUPLICATE_VERIFIED_OBSERVATIONS = 129
EXPECTED_PAIRWISE = {
    "mavedb_clipe__igvf_sge": 38,
    "igvf_vamp_seq__igvf_sge": 85,
    "mavedb_clipe__igvf_vamp_seq": 13,
}
EXPECTED_TRIPLE = 7

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
FORBIDDEN_CLINICAL_TOKENS = ("classification", "pathogenic", "benign", "ps3", "bs3", "clinical_label")
REQUIRED_BOUNDARIES = {
    "network": "forbidden",
    "clinical_use": "forbidden",
    "evidence_strength_use": "forbidden",
}


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _load_module(module_name: str):
    try:
        return import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"functional identity promotion module {module_name!r} is not implemented: {exc}")


def _symbol(module: Any, symbol_name: str):
    if not hasattr(module, symbol_name):
        pytest.fail(f"module {module.__name__!r} is missing required symbol {symbol_name!r}")
    return getattr(module, symbol_name)


def _functional_model_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_functional.model")
    return {
        "NORMALIZED_FUNCTIONAL_ROW_SCHEMA": _symbol(module, "NORMALIZED_FUNCTIONAL_ROW_SCHEMA"),
        "REQUIRED_ROW_FIELDS": _symbol(module, "REQUIRED_ROW_FIELDS"),
        "ALLOWED_IDENTITY_STATES": _symbol(module, "ALLOWED_IDENTITY_STATES"),
        "ALLOWED_UNRESOLVED_REASONS": _symbol(module, "ALLOWED_UNRESOLVED_REASONS"),
        "IDENTITY_STATE_TO_UNRESOLVED_REASON": _symbol(module, "IDENTITY_STATE_TO_UNRESOLVED_REASON"),
        "NormalizedFunctionalRow": _symbol(module, "NormalizedFunctionalRow"),
        "NormalizationContractError": _symbol(module, "NormalizationContractError"),
    }


def _promotion_model_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_identity_promotion.model")
    return {
        "PromotionModelError": _symbol(module, "PromotionModelError"),
        "spdi_to_hgvs_g": _symbol(module, "spdi_to_hgvs_g"),
    }


def _promotion_ingest_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_identity_promotion.ingest")
    return {
        "InputPinMismatchError": _symbol(module, "InputPinMismatchError"),
        "PromotionJoinError": _symbol(module, "PromotionJoinError"),
        "PromotionInvariantError": _symbol(module, "PromotionInvariantError"),
        "validate_input_bundle_manifests": _symbol(module, "validate_input_bundle_manifests"),
        "read_pinned_artifact_payloads": _symbol(module, "read_pinned_artifact_payloads"),
        "promote_functional_identities": _symbol(module, "promote_functional_identities"),
        "compute_verified_spdi_overlap": _symbol(module, "compute_verified_spdi_overlap"),
    }


def _promotion_bundle_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_identity_promotion.bundle")
    return {
        "PromotionBundleBoundaryError": _symbol(module, "PromotionBundleBoundaryError"),
        "PromotionManifestError": _symbol(module, "PromotionManifestError"),
        "canonical_jsonl_bytes": _symbol(module, "canonical_jsonl_bytes"),
        "compute_manifest_content_hash": _symbol(module, "compute_manifest_content_hash"),
        "validate_manifest_content_hash": _symbol(module, "validate_manifest_content_hash"),
        "build_identity_promotion_manifest": _symbol(module, "build_identity_promotion_manifest"),
        "publish_identity_promotion_bundle": _symbol(module, "publish_identity_promotion_bundle"),
        "build_committed_summary": _symbol(module, "build_committed_summary"),
        "_publish_directory_no_replace": _symbol(module, "_publish_directory_no_replace"),
    }


def _load_operator_module():
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"functional identity promotion operator script is not implemented: {OPERATOR_SCRIPT}")
    spec = importlib.util.spec_from_file_location("raptor_tsc2_identity_promotion_operator", OPERATOR_SCRIPT)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load operator module spec from {OPERATOR_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, node.lineno))
    return found


def _functional_row(
    *,
    source_id: str,
    source_row: int,
    source_record_id: str,
    variant_kind: str,
    identity_state: str,
    unresolved_reason: str | None,
    protein_accession: str | None,
    hgvs_c: str | None,
    hgvs_p: str | None,
    hgvs_g: str | None,
    spdi: str | None,
    score_raw: str = "0.50",
) -> dict[str, Any]:
    transcript_value = TRANSCRIPT if (spdi is not None or hgvs_c is not None or source_id != "igvf_vamp_seq") else None
    return {
        "schema": NORMALIZED_ROW_SCHEMA,
        "source_id": source_id,
        "source_row": source_row,
        "source_record_id": source_record_id,
        "gene": GENE,
        "assembly": ASSEMBLY if spdi is not None else None,
        "transcript": transcript_value,
        "protein_accession": protein_accession,
        "hgvs_c": hgvs_c,
        "hgvs_p": hgvs_p,
        "hgvs_g": hgvs_g,
        "spdi": spdi,
        "variant_kind": variant_kind,
        "identity_state": identity_state,
        "unresolved_reason": unresolved_reason,
        "score_name": "functional_score",
        "score_raw": score_raw,
    }


def _spdi_to_hgvs_g_local(spdi: str) -> str:
    accession, position_text, deleted, inserted = spdi.split(":")
    position0 = int(position_text)
    start1 = position0 + 1
    if len(deleted) == 1 and len(inserted) == 1:
        return f"{accession}:g.{start1}{deleted}>{inserted}"
    end1 = start1 + len(deleted) - 1
    return f"{accession}:g.{start1}_{end1}delins{inserted}"


def _clipe_mapping_row(
    *,
    source_row: int,
    source_record_id: str,
    hgvs_c: str,
    genomic_spdi: str | None,
    status: str = "PROJECTED_FASTA_VERIFIED",
) -> dict[str, Any]:
    hgvs_nt_source = hgvs_c.split(":", 1)[1]
    if re.fullmatch(r"c\.\d+[ACGT]>[ACGT]", hgvs_nt_source):
        variant_shape = "SNV"
    else:
        variant_shape = "DELINS"

    tx_spdi: str | None
    normalized_genomic_spdi: str | None
    hgvs_g: str | None
    fasta_deleted_observed: str | None
    assembly: str | None
    genomic_accession: str | None
    error_detail: str | None
    if status == "PROJECTED_FASTA_VERIFIED":
        if genomic_spdi is None:
            raise ValueError("PROJECTED_FASTA_VERIFIED mapping rows require a non-null genomic_spdi in test fixtures")
        accession, position_text, deleted, inserted = genomic_spdi.split(":")
        if variant_shape == "SNV":
            tx_pos = int(re.search(r"^c\.(\d+)", hgvs_nt_source).group(1)) + 109  # type: ignore[union-attr]
        else:
            tx_pos = int(re.search(r"^c\.(\d+)_", hgvs_nt_source).group(1)) + 109  # type: ignore[union-attr]
        tx_spdi = f"{TRANSCRIPT}:{tx_pos}:{deleted}:{inserted}"
        normalized_genomic_spdi = genomic_spdi
        hgvs_g = _spdi_to_hgvs_g_local(genomic_spdi)
        fasta_deleted_observed = deleted
        assembly = ASSEMBLY
        genomic_accession = accession
        error_detail = None
    else:
        tx_spdi = None
        normalized_genomic_spdi = None
        hgvs_g = None
        fasta_deleted_observed = None
        assembly = None
        genomic_accession = None
        error_detail = "sanitized error"

    return {
        "schema": CLIPE_MAPPING_SCHEMA,
        "source_id": "mavedb_clipe",
        "source_row": source_row,
        "source_record_id": source_record_id,
        "gene": GENE,
        "transcript": TRANSCRIPT,
        "hgvs_c": hgvs_c,
        "hgvs_nt_source": hgvs_nt_source,
        "tx_spdi": tx_spdi,
        "genomic_spdi": normalized_genomic_spdi,
        "hgvs_g": hgvs_g,
        "assembly": assembly,
        "genomic_accession": genomic_accession,
        "status": status,
        "fasta_deleted_observed": fasta_deleted_observed,
        "error_detail": error_detail,
        "step1_body_sha256": "a" * 64,
        "step2_body_sha256": "b" * 64,
        "variant_shape": variant_shape,
    }


def _vamp_crosswalk_row(
    *,
    source_row: int,
    protein_variant: str,
    status: str,
    hgvs_c: str | None = None,
    genomic_spdi: str | None = None,
) -> dict[str, Any]:
    unresolved_reason = {
        "CROSSWALK_SPDI_VERIFIED": None,
        "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT",
        "SOURCE_COORDINATE_REFERENCE_MISMATCH": "SOURCE_REF_DOES_NOT_MATCH_PINNED_FASTA",
        "ARCHIVE_CROSSWALK_ABSENT": "PROTEIN_VARIANT_NOT_IN_ARCHIVE",
    }[status]
    if status == "ARCHIVE_CROSSWALK_ABSENT":
        archive_member = None
        archive_row = None
        transcript = None
        normalized_hgvs_c = None
        assembly = None
        normalized_spdi = None
    elif status == "CROSSWALK_SPDI_VERIFIED":
        archive_member = "library1"
        archive_row = 1
        transcript = TRANSCRIPT
        normalized_hgvs_c = hgvs_c if hgvs_c is not None else "c.1600G>A"
        assembly = ASSEMBLY
        normalized_spdi = genomic_spdi if genomic_spdi is not None else "NC_000016.10:2065518:G:A"
    else:
        archive_member = "library1"
        archive_row = 1
        transcript = TRANSCRIPT
        normalized_hgvs_c = hgvs_c if hgvs_c is not None else "c.1600G>A"
        assembly = None
        normalized_spdi = None

    return {
        "schema": VAMP_CROSSWALK_SCHEMA,
        "source_id": "igvf_vamp_seq",
        "source_row": source_row,
        "protein_variant": protein_variant,
        "archive_member": archive_member,
        "archive_row": archive_row,
        "transcript": transcript,
        "hgvs_c": normalized_hgvs_c,
        "assembly": assembly,
        "genomic_spdi": normalized_spdi,
        "status": status,
        "unresolved_reason": unresolved_reason,
    }


def _source_manifests_fixture() -> dict[str, Any]:
    functional_bundle = _load_module("raptor.external.tsc2_functional.bundle")
    clipe_bundle = _load_module("raptor.external.tsc2_cdna_projector.bundle")
    vamp_bundle = _load_module("raptor.external.tsc2_vamp_crosswalk.bundle")

    functional_run_name = "synthetic-functional-normalization-input"
    clipe_run_name = "synthetic-clipe-projector-input"
    vamp_run_name = "synthetic-vamp-crosswalk-input"

    functional_rows_by_source = {
        "mavedb_clipe": [
            _functional_row(
                source_id="mavedb_clipe",
                source_row=1,
                source_record_id="urn:mavedb:synthetic#1",
                variant_kind="MISSENSE",
                identity_state="TRANSCRIPT_ONLY_PROJECTOR_REQUIRED",
                unresolved_reason="CDNA_PROJECTOR_REQUIRED",
                protein_accession=None,
                hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
                hgvs_p="p.Gly534Arg",
                hgvs_g=None,
                spdi=None,
                score_raw="0.55",
            )
        ],
        "igvf_vamp_seq": [
            _functional_row(
                source_id="igvf_vamp_seq",
                source_row=1,
                source_record_id=f"{VAMP_PROTEIN_ACCESSION}:p.Gly534Arg",
                variant_kind="MISSENSE",
                identity_state="PROTEIN_ONLY_CROSSWALK_REQUIRED",
                unresolved_reason="NUCLEOTIDE_CROSSWALK_REQUIRED",
                protein_accession=VAMP_PROTEIN_ACCESSION,
                hgvs_c=None,
                hgvs_p="p.Gly534Arg",
                hgvs_g=None,
                spdi=None,
                score_raw="0.62",
            )
        ],
        "igvf_sge": [
            _functional_row(
                source_id="igvf_sge",
                source_row=1,
                source_record_id="NC_000016.10:g.2065519G>A",
                variant_kind="MISSENSE",
                identity_state="GENOMIC_SPDI_VERIFIED",
                unresolved_reason=None,
                protein_accession=None,
                hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
                hgvs_p="p.Gly534Arg",
                hgvs_g="NC_000016.10:g.2065519G>A",
                spdi="NC_000016.10:2065518:G:A",
                score_raw="0.57",
            )
        ],
    }
    canonical_normalized = _symbol(functional_bundle, "canonical_jsonl_bytes")
    build_normalization_manifest = _symbol(functional_bundle, "build_normalization_manifest")
    validate_normalization_manifest_hash = _symbol(functional_bundle, "validate_manifest_content_hash")

    functional_payloads = {
        source_id: canonical_normalized(rows)
        for source_id, rows in functional_rows_by_source.items()
    }
    functional_artifacts = [
        {
            "artifact_id": "normalized-mavedb-clipe",
            "source_id": "mavedb_clipe",
            "relative_path": "normalized/mavedb_clipe.jsonl",
            "byte_length": len(functional_payloads["mavedb_clipe"]),
            "sha256": _sha256(functional_payloads["mavedb_clipe"]),
            "row_count": 1,
        },
        {
            "artifact_id": "normalized-igvf-vamp-seq",
            "source_id": "igvf_vamp_seq",
            "relative_path": "normalized/igvf_vamp_seq.jsonl",
            "byte_length": len(functional_payloads["igvf_vamp_seq"]),
            "sha256": _sha256(functional_payloads["igvf_vamp_seq"]),
            "row_count": 1,
        },
        {
            "artifact_id": "normalized-igvf-sge",
            "source_id": "igvf_sge",
            "relative_path": "normalized/igvf_sge.jsonl",
            "byte_length": len(functional_payloads["igvf_sge"]),
            "sha256": _sha256(functional_payloads["igvf_sge"]),
            "row_count": 1,
        },
    ]
    functional_manifest = build_normalization_manifest(
        bundle_id="synthetic-functional-normalization-bundle",
        created_at="2026-09-14T00:00:00Z",
        input_bundle={"bundle_id": "synthetic-source-bundle", "content_hash": "1" * 64},
        reference={"accession": GENOMIC_ACCESSION, "sha256": "2" * 64},
        artifacts=functional_artifacts,
        counts={"sources": 3, "artifacts": 3, "rows": 3},
        identity_state_counts={
            "TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 1,
            "PROTEIN_ONLY_CROSSWALK_REQUIRED": 1,
            "GENOMIC_SPDI_VERIFIED": 1,
        },
        variant_kind_counts={"MISSENSE": 3},
        boundaries={"network": "forbidden", "external_output_only": True},
    )
    validate_normalization_manifest_hash(functional_manifest)

    canonical_mapping = _symbol(clipe_bundle, "canonical_mapping_jsonl_bytes")
    canonical_request_index = _symbol(clipe_bundle, "canonical_request_index_jsonl_bytes")
    build_projector_manifest = _symbol(clipe_bundle, "build_projector_bundle_manifest")
    validate_projector_manifest_hash = _symbol(clipe_bundle, "validate_manifest_content_hash")

    clipe_rows = [
        _clipe_mapping_row(
            source_row=1,
            source_record_id="urn:mavedb:synthetic#1",
            hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
            genomic_spdi="NC_000016.10:2065518:G:A",
        ),
        _clipe_mapping_row(
            source_row=2,
            source_record_id="urn:mavedb:synthetic#2",
            hgvs_c=f"{TRANSCRIPT}:c.1627_1629delinsTGA",
            genomic_spdi="NC_000016.10:2065545:CCG:TGA",
        ),
    ]
    clipe_mapping_payload = canonical_mapping(clipe_rows)
    clipe_request_index_payload = canonical_request_index(
        [
            {
                "source_row": 1,
                "step": "step1",
                "requested_url": "https://api.ncbi.nlm.nih.gov/variation/v0/hgvs/NM_000548.5%3Ac.1600G%3EA/contextuals",
                "final_url": "https://api.ncbi.nlm.nih.gov/variation/v0/hgvs/NM_000548.5%3Ac.1600G%3EA/contextuals",
                "http_status": 200,
                "body_sha256": "a" * 64,
                "elapsed_ms": 1,
            },
            {
                "source_row": 1,
                "step": "step2",
                "requested_url": "https://api.ncbi.nlm.nih.gov/variation/v0/spdi/NM_000548.5%3A1709%3AG%3AA/canonical_representative",
                "final_url": "https://api.ncbi.nlm.nih.gov/variation/v0/spdi/NM_000548.5%3A1709%3AG%3AA/canonical_representative",
                "http_status": 200,
                "body_sha256": "b" * 64,
                "elapsed_ms": 1,
            },
        ]
    )
    clipe_manifest = build_projector_manifest(
        bundle_id="synthetic-clipe-projector-bundle",
        created_at="2026-09-14T00:00:00Z",
        input_scores={"artifact_id": "synthetic-scores", "sha256": "3" * 64, "byte_length": 12, "row_count": 2},
        reference={"accession": GENOMIC_ACCESSION, "sha256": "2" * 64},
        endpoint_pins={
            "base_url": "https://api.ncbi.nlm.nih.gov/variation/v0",
            "step_sequence": ["contextuals", "canonical_representative"],
            "min_interval_seconds": 1.0,
        },
        artifacts=[
            {
                "artifact_id": "mapping-jsonl",
                "relative_path": "mapping/mavedb_clipe_nm000548_5_to_nc000016_10.jsonl",
                "byte_length": len(clipe_mapping_payload),
                "sha256": _sha256(clipe_mapping_payload),
                "row_count": 2,
            },
            {
                "artifact_id": "request-index-jsonl",
                "relative_path": "logs/request_index.jsonl",
                "byte_length": len(clipe_request_index_payload),
                "sha256": _sha256(clipe_request_index_payload),
                "row_count": 2,
            },
        ],
        status_counts={"PROJECTED_FASTA_VERIFIED": 2},
        shape_counts={"SNV": 1, "DELINS": 1},
        success_count=2,
        failure_count=0,
        boundaries={"network": "operator_only", "clinical_use": "forbidden", "evidence_strength_use": "forbidden"},
        request_budget_observed={"step1": 2, "step2": 2},
    )
    validate_projector_manifest_hash(clipe_manifest)

    canonical_crosswalk = _symbol(vamp_bundle, "canonical_crosswalk_jsonl_bytes")
    build_crosswalk_manifest = _symbol(vamp_bundle, "build_crosswalk_bundle_manifest")
    validate_crosswalk_manifest_hash = _symbol(vamp_bundle, "validate_manifest_content_hash")
    vamp_rows = [
        _vamp_crosswalk_row(
            source_row=1,
            protein_variant=f"{VAMP_PROTEIN_ACCESSION}:p.Gly534Arg",
            status="CROSSWALK_SPDI_VERIFIED",
            hgvs_c="c.1600G>A",
            genomic_spdi="NC_000016.10:2065518:G:A",
        ),
        _vamp_crosswalk_row(
            source_row=2,
            protein_variant=f"{VAMP_PROTEIN_ACCESSION}:p.Pro543Ter",
            status="SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH",
            hgvs_c="c.1627_1629delinsTGA",
        ),
        _vamp_crosswalk_row(
            source_row=3,
            protein_variant=f"{VAMP_PROTEIN_ACCESSION}:p.Met600Val",
            status="ARCHIVE_CROSSWALK_ABSENT",
        ),
    ]
    vamp_crosswalk_payload = canonical_crosswalk(vamp_rows)
    vamp_manifest = build_crosswalk_manifest(
        bundle_id="synthetic-vamp-crosswalk-bundle",
        created_at="2026-09-14T00:00:00Z",
        input_scores={
            "artifact_id": "synthetic-vamp-scores",
            "sha256": "4" * 64,
            "md5": "5" * 32,
            "byte_length": 20,
            "row_count": 3,
        },
        archive={
            "record_id": 1,
            "doi": "10.0/synthetic",
            "filename": "synthetic.zip",
            "sha256": "6" * 64,
            "md5": "7" * 32,
            "byte_length": 30,
        },
        reference={"accession": GENOMIC_ACCESSION, "sha256": "2" * 64},
        artifacts=[
            {
                "artifact_id": "crosswalk-jsonl",
                "relative_path": "crosswalk/igvf_vamp_seq_genomic_crosswalk.jsonl",
                "sha256": _sha256(vamp_crosswalk_payload),
                "byte_length": len(vamp_crosswalk_payload),
                "row_count": 3,
            }
        ],
        counts={"rows": 3, "status_rows": 3},
        status_counts={
            "CROSSWALK_SPDI_VERIFIED": 1,
            "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 1,
            "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
            "ARCHIVE_CROSSWALK_ABSENT": 1,
        },
        boundaries={"network": "operator_only", "clinical_use": "forbidden", "evidence_strength_use": "forbidden"},
        verified_unique_spdi=1,
        follow_on_unresolved={
            "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": 1,
            "SOURCE_COORDINATE_REFERENCE_MISMATCH": 0,
            "ARCHIVE_CROSSWALK_ABSENT": 1,
        },
    )
    validate_crosswalk_manifest_hash(vamp_manifest)

    return {
        "run_names": {
            "functional_normalization": functional_run_name,
            "clipe_projector": clipe_run_name,
            "vamp_crosswalk": vamp_run_name,
        },
        "functional_normalization_manifest": functional_manifest,
        "clipe_manifest": clipe_manifest,
        "vamp_manifest": vamp_manifest,
        "artifact_payloads": {
            "functional_normalization": functional_payloads,
            "clipe_projector_mapping": clipe_mapping_payload,
            "vamp_crosswalk": vamp_crosswalk_payload,
        },
        "expected_pins": {
            "functional_normalization_bundle": {
                "run_name": functional_run_name,
                "bundle_id": functional_manifest["bundle_id"],
                "manifest_content_hash": functional_manifest["content_hash"],
                "artifacts": {
                    "mavedb_clipe": {
                        "artifact_id": "normalized-mavedb-clipe",
                        "relative_path": "normalized/mavedb_clipe.jsonl",
                        "sha256": _sha256(functional_payloads["mavedb_clipe"]),
                        "byte_length": len(functional_payloads["mavedb_clipe"]),
                        "row_count": 1,
                    },
                    "igvf_vamp_seq": {
                        "artifact_id": "normalized-igvf-vamp-seq",
                        "relative_path": "normalized/igvf_vamp_seq.jsonl",
                        "sha256": _sha256(functional_payloads["igvf_vamp_seq"]),
                        "byte_length": len(functional_payloads["igvf_vamp_seq"]),
                        "row_count": 1,
                    },
                    "igvf_sge": {
                        "artifact_id": "normalized-igvf-sge",
                        "relative_path": "normalized/igvf_sge.jsonl",
                        "sha256": _sha256(functional_payloads["igvf_sge"]),
                        "byte_length": len(functional_payloads["igvf_sge"]),
                        "row_count": 1,
                    },
                },
            },
            "clipe_projector_bundle": {
                "run_name": clipe_run_name,
                "bundle_id": clipe_manifest["bundle_id"],
                "manifest_content_hash": clipe_manifest["content_hash"],
                "mapping": {
                    "artifact_id": "mapping-jsonl",
                    "relative_path": "mapping/mavedb_clipe_nm000548_5_to_nc000016_10.jsonl",
                    "sha256": _sha256(clipe_mapping_payload),
                    "byte_length": len(clipe_mapping_payload),
                    "row_count": 2,
                },
            },
            "vamp_crosswalk_bundle": {
                "run_name": vamp_run_name,
                "bundle_id": vamp_manifest["bundle_id"],
                "manifest_content_hash": vamp_manifest["content_hash"],
                "crosswalk": {
                    "artifact_id": "crosswalk-jsonl",
                    "relative_path": "crosswalk/igvf_vamp_seq_genomic_crosswalk.jsonl",
                    "sha256": _sha256(vamp_crosswalk_payload),
                    "byte_length": len(vamp_crosswalk_payload),
                    "row_count": 3,
                },
            },
        },
    }


def _tiny_promotable_fixture() -> dict[str, Any]:
    functional_rows = [
        _functional_row(
            source_id="mavedb_clipe",
            source_row=1,
            source_record_id="urn:mavedb:00001201-a-1#1",
            variant_kind="MISSENSE",
            identity_state="TRANSCRIPT_ONLY_PROJECTOR_REQUIRED",
            unresolved_reason="CDNA_PROJECTOR_REQUIRED",
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
            hgvs_p="p.Gly534Arg",
            hgvs_g=None,
            spdi=None,
            score_raw="0.61",
        ),
        _functional_row(
            source_id="mavedb_clipe",
            source_row=2,
            source_record_id="urn:mavedb:00001201-a-1#2",
            variant_kind="STOP_GAINED",
            identity_state="TRANSCRIPT_ONLY_PROJECTOR_REQUIRED",
            unresolved_reason="CDNA_PROJECTOR_REQUIRED",
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.1627_1629delinsTGA",
            hgvs_p="p.Pro543Ter",
            hgvs_g=None,
            spdi=None,
            score_raw="-0.71",
        ),
        _functional_row(
            source_id="igvf_vamp_seq",
            source_row=1,
            source_record_id="ENSP00000219476.3:p.Gly534Arg",
            variant_kind="MISSENSE",
            identity_state="PROTEIN_ONLY_CROSSWALK_REQUIRED",
            unresolved_reason="NUCLEOTIDE_CROSSWALK_REQUIRED",
            protein_accession=VAMP_PROTEIN_ACCESSION,
            hgvs_c=None,
            hgvs_p="p.Gly534Arg",
            hgvs_g=None,
            spdi=None,
            score_raw="0.62",
        ),
        _functional_row(
            source_id="igvf_vamp_seq",
            source_row=2,
            source_record_id="ENSP00000219476.3:p.Pro543Ter",
            variant_kind="STOP_GAINED",
            identity_state="PROTEIN_ONLY_CROSSWALK_REQUIRED",
            unresolved_reason="NUCLEOTIDE_CROSSWALK_REQUIRED",
            protein_accession=VAMP_PROTEIN_ACCESSION,
            hgvs_c=None,
            hgvs_p="p.Pro543Ter",
            hgvs_g=None,
            spdi=None,
            score_raw="-0.64",
        ),
        _functional_row(
            source_id="igvf_vamp_seq",
            source_row=3,
            source_record_id="ENSP00000219476.3:p.Met600Val",
            variant_kind="MISSENSE",
            identity_state="PROTEIN_ONLY_CROSSWALK_REQUIRED",
            unresolved_reason="NUCLEOTIDE_CROSSWALK_REQUIRED",
            protein_accession=VAMP_PROTEIN_ACCESSION,
            hgvs_c=None,
            hgvs_p="p.Met600Val",
            hgvs_g=None,
            spdi=None,
            score_raw="0.01",
        ),
        _functional_row(
            source_id="igvf_sge",
            source_row=1,
            source_record_id="NC_000016.10:g.2065519G>A",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
            hgvs_p="p.Gly534Arg",
            hgvs_g="NC_000016.10:g.2065519G>A",
            spdi="NC_000016.10:2065518:G:A",
            score_raw="0.55",
        ),
        _functional_row(
            source_id="igvf_sge",
            source_row=2,
            source_record_id="NC_000016.10:g.2065546_2065548delinsTGA",
            variant_kind="STOP_GAINED",
            identity_state="GENOMIC_REFERENCE_MISMATCH",
            unresolved_reason="REFERENCE_ALLELE_MISMATCH",
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.1627_1629delinsTGA",
            hgvs_p="p.Pro543Ter",
            hgvs_g=None,
            spdi=None,
            score_raw="-0.30",
        ),
    ]
    clipe_mapping_rows = [
        _clipe_mapping_row(
            source_row=1,
            source_record_id="urn:mavedb:00001201-a-1#1",
            hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
            genomic_spdi="NC_000016.10:2065518:G:A",
            status="PROJECTED_FASTA_VERIFIED",
        ),
        _clipe_mapping_row(
            source_row=2,
            source_record_id="urn:mavedb:00001201-a-1#2",
            hgvs_c=f"{TRANSCRIPT}:c.1627_1629delinsTGA",
            genomic_spdi="NC_000016.10:2065545:CCG:TGA",
            status="PROJECTED_FASTA_VERIFIED",
        ),
    ]
    vamp_crosswalk_rows = [
        _vamp_crosswalk_row(
            source_row=1,
            protein_variant=f"{VAMP_PROTEIN_ACCESSION}:p.Gly534Arg",
            status="CROSSWALK_SPDI_VERIFIED",
            hgvs_c="c.1600G>A",
            genomic_spdi="NC_000016.10:2065518:G:A",
        ),
        _vamp_crosswalk_row(
            source_row=2,
            protein_variant=f"{VAMP_PROTEIN_ACCESSION}:p.Pro543Ter",
            status="SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH",
            hgvs_c="c.1627_1629delinsTGA",
            genomic_spdi=None,
        ),
        _vamp_crosswalk_row(
            source_row=3,
            protein_variant=f"{VAMP_PROTEIN_ACCESSION}:p.Met600Val",
            status="ARCHIVE_CROSSWALK_ABSENT",
            hgvs_c=None,
            genomic_spdi=None,
        ),
    ]
    return {
        "functional_rows": functional_rows,
        "clipe_mapping_rows": clipe_mapping_rows,
        "vamp_crosswalk_rows": vamp_crosswalk_rows,
    }


def _tiny_promoted_rows() -> list[dict[str, Any]]:
    return [
        _functional_row(
            source_id="mavedb_clipe",
            source_row=1,
            source_record_id="urn:mavedb:00001201-a-1#1",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
            hgvs_p="p.Gly534Arg",
            hgvs_g="NC_000016.10:g.2065519G>A",
            spdi="NC_000016.10:2065518:G:A",
            score_raw="0.61",
        ),
        _functional_row(
            source_id="mavedb_clipe",
            source_row=2,
            source_record_id="urn:mavedb:00001201-a-1#2",
            variant_kind="STOP_GAINED",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.1627_1629delinsTGA",
            hgvs_p="p.Pro543Ter",
            hgvs_g="NC_000016.10:g.2065546_2065548delinsTGA",
            spdi="NC_000016.10:2065545:CCG:TGA",
            score_raw="-0.71",
        ),
        _functional_row(
            source_id="igvf_vamp_seq",
            source_row=1,
            source_record_id="ENSP00000219476.3:p.Gly534Arg",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=VAMP_PROTEIN_ACCESSION,
            hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
            hgvs_p="p.Gly534Arg",
            hgvs_g="NC_000016.10:g.2065519G>A",
            spdi="NC_000016.10:2065518:G:A",
            score_raw="0.62",
        ),
        _functional_row(
            source_id="igvf_vamp_seq",
            source_row=2,
            source_record_id="ENSP00000219476.3:p.Pro543Ter",
            variant_kind="STOP_GAINED",
            identity_state="GENOMIC_CROSSWALK_LENGTH_MISMATCH",
            unresolved_reason="SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT",
            protein_accession=VAMP_PROTEIN_ACCESSION,
            hgvs_c=f"{TRANSCRIPT}:c.1627_1629delinsTGA",
            hgvs_p="p.Pro543Ter",
            hgvs_g=None,
            spdi=None,
            score_raw="-0.64",
        ),
        _functional_row(
            source_id="igvf_vamp_seq",
            source_row=3,
            source_record_id="ENSP00000219476.3:p.Met600Val",
            variant_kind="MISSENSE",
            identity_state="PROTEIN_ONLY_ARCHIVE_CROSSWALK_ABSENT",
            unresolved_reason="PROTEIN_VARIANT_NOT_IN_ARCHIVE",
            protein_accession=VAMP_PROTEIN_ACCESSION,
            hgvs_c=None,
            hgvs_p="p.Met600Val",
            hgvs_g=None,
            spdi=None,
            score_raw="0.01",
        ),
        _functional_row(
            source_id="igvf_sge",
            source_row=1,
            source_record_id="NC_000016.10:g.2065519G>A",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
            hgvs_p="p.Gly534Arg",
            hgvs_g="NC_000016.10:g.2065519G>A",
            spdi="NC_000016.10:2065518:G:A",
            score_raw="0.55",
        ),
        _functional_row(
            source_id="igvf_sge",
            source_row=2,
            source_record_id="NC_000016.10:g.2065546_2065548delinsTGA",
            variant_kind="STOP_GAINED",
            identity_state="GENOMIC_REFERENCE_MISMATCH",
            unresolved_reason="REFERENCE_ALLELE_MISMATCH",
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.1627_1629delinsTGA",
            hgvs_p="p.Pro543Ter",
            hgvs_g=None,
            spdi=None,
            score_raw="-0.30",
        ),
    ]


def _tiny_promotion_manifest_fixture(api: dict[str, Any]) -> dict[str, Any]:
    promoted_rows = _tiny_promoted_rows()
    rows_by_source = {
        "mavedb_clipe": [row for row in promoted_rows if row["source_id"] == "mavedb_clipe"],
        "igvf_vamp_seq": [row for row in promoted_rows if row["source_id"] == "igvf_vamp_seq"],
        "igvf_sge": [row for row in promoted_rows if row["source_id"] == "igvf_sge"],
    }
    payloads_by_source = {
        source_id: api["canonical_jsonl_bytes"](rows)
        for source_id, rows in rows_by_source.items()
    }
    payloads_by_artifact_id = {
        artifact_id: payloads_by_source[source_id]
        for (artifact_id, _relative_path), source_id in zip(
            PROMOTED_ARTIFACTS, ("mavedb_clipe", "igvf_vamp_seq", "igvf_sge")
        )
    }
    artifacts = []
    for (artifact_id, relative_path), source_id in zip(
        PROMOTED_ARTIFACTS, ("mavedb_clipe", "igvf_vamp_seq", "igvf_sge")
    ):
        payload = payloads_by_source[source_id]
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "relative_path": relative_path,
                "sha256": _sha256(payload),
                "byte_length": len(payload),
                "row_count": len(rows_by_source[source_id]),
            }
        )

    build_args = {
        "bundle_id": OUTPUT_BUNDLE_ID,
        "created_at": "2026-09-14T00:00:00Z",
        "input_manifests": {
            "functional_normalization": FUNCTIONAL_MANIFEST_HASH,
            "clipe_projector": CLIPE_MANIFEST_HASH,
            "vamp_crosswalk": VAMP_MANIFEST_HASH,
        },
        "artifacts": artifacts,
        "counts": {"rows": len(promoted_rows)},
        "source_row_counts": {"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
        "identity_state_counts": {
            "GENOMIC_SPDI_VERIFIED": 4,
            "GENOMIC_REFERENCE_MISMATCH": 1,
            "GENOMIC_CROSSWALK_LENGTH_MISMATCH": 1,
            "PROTEIN_ONLY_ARCHIVE_CROSSWALK_ABSENT": 1,
            "REFERENCE_CONTROL": 0,
            "TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": 0,
            "PROTEIN_ONLY_CROSSWALK_REQUIRED": 0,
        },
        "unresolved_reason_counts": {
            "REFERENCE_ALLELE_MISMATCH": 1,
            "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT": 1,
            "PROTEIN_VARIANT_NOT_IN_ARCHIVE": 1,
            "NOT_A_VARIANT": 0,
            "CDNA_PROJECTOR_REQUIRED": 0,
            "NUCLEOTIDE_CROSSWALK_REQUIRED": 0,
        },
        "variant_kind_counts": {
            "MISSENSE": 4,
            "SYNONYMOUS": 0,
            "STOP_GAINED": 3,
            "OTHER": 0,
            "REFERENCE_CONTROL": 0,
        },
        "verified_observations_by_source": {"mavedb_clipe": 2, "igvf_vamp_seq": 1, "igvf_sge": 1},
        "verified_observations": 4,
        "verified_unique_spdi": 2,
        "duplicate_verified_observations": 2,
        "source_overlap": {
            "pairwise": {"mavedb_clipe__igvf_sge": 1, "igvf_vamp_seq__igvf_sge": 1, "mavedb_clipe__igvf_vamp_seq": 1},
            "triple": 1,
        },
        "conservation": {"input_rows": len(promoted_rows), "output_rows": len(promoted_rows), "dropped_rows": 0, "duplicate_source_rows": 0},
        "boundaries": dict(REQUIRED_BOUNDARIES),
    }
    manifest = api["build_identity_promotion_manifest"](**build_args)
    return {
        "promoted_rows": promoted_rows,
        "rows_by_source": rows_by_source,
        "payloads_by_source": payloads_by_source,
        "payloads_by_artifact_id": payloads_by_artifact_id,
        "artifacts": artifacts,
        "build_args": build_args,
        "manifest": manifest,
    }


def test_fp00_binding_spec_exists_and_is_v1_0_2() -> None:
    if not SPEC_PATH.is_file():
        pytest.fail(f"binding spec is missing: {SPEC_PATH}")
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["spec_id"] == "raptor-v2-functional-identity-promotion-v1"
    assert spec["spec_version"] == "1.0.2"


def test_fp01_existing_row_schema_stays_exact_17_fields_and_adds_new_state_reason_bindings() -> None:
    api = _functional_model_api()
    assert api["NORMALIZED_FUNCTIONAL_ROW_SCHEMA"] == NORMALIZED_ROW_SCHEMA
    assert set(api["REQUIRED_ROW_FIELDS"]) == {
        "schema",
        "source_id",
        "source_row",
        "source_record_id",
        "gene",
        "assembly",
        "transcript",
        "protein_accession",
        "hgvs_c",
        "hgvs_p",
        "hgvs_g",
        "spdi",
        "variant_kind",
        "identity_state",
        "unresolved_reason",
        "score_name",
        "score_raw",
    }
    assert len(api["REQUIRED_ROW_FIELDS"]) == 17
    assert "GENOMIC_CROSSWALK_LENGTH_MISMATCH" in api["ALLOWED_IDENTITY_STATES"]
    assert "PROTEIN_ONLY_ARCHIVE_CROSSWALK_ABSENT" in api["ALLOWED_IDENTITY_STATES"]
    assert "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT" in api["ALLOWED_UNRESOLVED_REASONS"]
    assert "PROTEIN_VARIANT_NOT_IN_ARCHIVE" in api["ALLOWED_UNRESOLVED_REASONS"]
    bindings = api["IDENTITY_STATE_TO_UNRESOLVED_REASON"]
    assert bindings["GENOMIC_CROSSWALK_LENGTH_MISMATCH"] == "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT"
    assert bindings["PROTEIN_ONLY_ARCHIVE_CROSSWALK_ABSENT"] == "PROTEIN_VARIANT_NOT_IN_ARCHIVE"


def test_fp02_verified_row_spdi_hgvs_g_validation_supports_snv_and_equal_length_delins() -> None:
    api = _functional_model_api()
    row_ctor = api["NormalizedFunctionalRow"]
    err = api["NormalizationContractError"]

    snv = row_ctor(
        source_id="mavedb_clipe",
        source_row=1,
        source_record_id="r1",
        gene=GENE,
        assembly=ASSEMBLY,
        transcript=TRANSCRIPT,
        protein_accession=None,
        hgvs_c=f"{TRANSCRIPT}:c.1600G>A",
        hgvs_p="p.Gly534Arg",
        hgvs_g="NC_000016.10:g.2065519G>A",
        spdi="NC_000016.10:2065518:G:A",
        variant_kind="MISSENSE",
        identity_state="GENOMIC_SPDI_VERIFIED",
        unresolved_reason=None,
        score_name="score",
        score_raw="0.61",
    )
    assert snv.to_dict()["spdi"] == "NC_000016.10:2065518:G:A"

    delins = row_ctor(
        source_id="mavedb_clipe",
        source_row=2,
        source_record_id="r2",
        gene=GENE,
        assembly=ASSEMBLY,
        transcript=TRANSCRIPT,
        protein_accession=None,
        hgvs_c=f"{TRANSCRIPT}:c.1627_1629delinsTGA",
        hgvs_p="p.Pro543Ter",
        hgvs_g="NC_000016.10:g.2065546_2065548delinsTGA",
        spdi="NC_000016.10:2065545:CCG:TGA",
        variant_kind="STOP_GAINED",
        identity_state="GENOMIC_SPDI_VERIFIED",
        unresolved_reason=None,
        score_name="score",
        score_raw="-0.71",
    )
    assert delins.to_dict()["hgvs_g"] == "NC_000016.10:g.2065546_2065548delinsTGA"

    bad_pairs = [
        ("NC_000016.10:2065545::TGA", "NC_000016.10:g.2065546_2065548delinsTGA"),
        ("NC_000016.10:2065545:CCG:", "NC_000016.10:g.2065546_2065548delinsTGA"),
        ("NC_000016.10:2065545:CC:TGA", "NC_000016.10:g.2065546_2065548delinsTGA"),
        ("NC_000017.11:2065545:CCG:TGA", "NC_000017.11:g.2065546_2065548delinsTGA"),
        ("NC_000016.10:-1:CCG:TGA", "NC_000016.10:g.0_2delinsTGA"),
        ("NC_000016.10:2065545:CCG:TNA", "NC_000016.10:g.2065546_2065548delinsTNA"),
        ("NC_000016.10:2065545:CCG:TGA", "NC_000016.10:g.2065546_2065549delinsTGA"),
    ]
    for spdi, hgvs_g in bad_pairs:
        with pytest.raises(err):
            row_ctor(
                source_id="mavedb_clipe",
                source_row=3,
                source_record_id="r3",
                gene=GENE,
                assembly=ASSEMBLY,
                transcript=TRANSCRIPT,
                protein_accession=None,
                hgvs_c=f"{TRANSCRIPT}:c.1627_1629delinsTGA",
                hgvs_p="p.Pro543Ter",
                hgvs_g=hgvs_g,
                spdi=spdi,
                variant_kind="STOP_GAINED",
                identity_state="GENOMIC_SPDI_VERIFIED",
                unresolved_reason=None,
                score_name="score",
                score_raw="-0.71",
            )


def test_fp03_spdi_to_hgvs_g_is_deterministic_for_one_base_and_multibase_and_rejects_invalid_inputs() -> None:
    api = _promotion_model_api()
    err = api["PromotionModelError"]
    fn = api["spdi_to_hgvs_g"]

    assert fn("NC_000016.10:2065518:G:A") == "NC_000016.10:g.2065519G>A"
    assert fn("NC_000016.10:2065518:AA:TT") == "NC_000016.10:g.2065519_2065520delinsTT"
    assert fn("NC_000016.10:2065545:CCG:TGA") == "NC_000016.10:g.2065546_2065548delinsTGA"

    bad_spdis = [
        "",
        "NC_000016.10:2065545::TGA",
        "NC_000016.10:2065545:CCG:",
        "NC_000016.10:2065545:CC:TGA",
        "NC_000017.11:2065518:G:A",
        "NC_000016.10:-1:G:A",
        "NC_000016.10:2065518:G:N",
        "NC_000016.10:2065518:G:AA",
    ]
    for spdi in bad_spdis:
        with pytest.raises(err):
            fn(spdi)


def test_fp04_input_manifest_and_artifact_pins_are_exact_fail_closed_and_unambiguous() -> None:
    api = _promotion_ingest_api()
    fixture = _source_manifests_fixture()
    err = api["InputPinMismatchError"]

    validated = api["validate_input_bundle_manifests"](
        functional_normalization_manifest=deepcopy(fixture["functional_normalization_manifest"]),
        clipe_projector_manifest=deepcopy(fixture["clipe_manifest"]),
        vamp_crosswalk_manifest=deepcopy(fixture["vamp_manifest"]),
        expected_pins=deepcopy(fixture["expected_pins"]),
    )
    assert validated["functional_normalization_bundle"]["bundle_id"] == fixture["expected_pins"]["functional_normalization_bundle"]["bundle_id"]
    assert (
        validated["clipe_projector_bundle"]["mapping"]["relative_path"]
        == fixture["expected_pins"]["clipe_projector_bundle"]["mapping"]["relative_path"]
    )
    assert (
        validated["vamp_crosswalk_bundle"]["crosswalk"]["relative_path"]
        == fixture["expected_pins"]["vamp_crosswalk_bundle"]["crosswalk"]["relative_path"]
    )

    drifted_hash = deepcopy(fixture["vamp_manifest"])
    drifted_hash["content_hash"] = "0" * 64
    with pytest.raises(err):
        api["validate_input_bundle_manifests"](
            functional_normalization_manifest=deepcopy(fixture["functional_normalization_manifest"]),
            clipe_projector_manifest=deepcopy(fixture["clipe_manifest"]),
            vamp_crosswalk_manifest=drifted_hash,
            expected_pins=deepcopy(fixture["expected_pins"]),
        )

    duplicate_artifact = deepcopy(fixture["clipe_manifest"])
    duplicate_artifact["artifacts"].append(deepcopy(duplicate_artifact["artifacts"][0]))
    with pytest.raises(err):
        api["validate_input_bundle_manifests"](
            functional_normalization_manifest=deepcopy(fixture["functional_normalization_manifest"]),
            clipe_projector_manifest=duplicate_artifact,
            vamp_crosswalk_manifest=deepcopy(fixture["vamp_manifest"]),
            expected_pins=deepcopy(fixture["expected_pins"]),
        )

    decoy_first = deepcopy(fixture["functional_normalization_manifest"])
    decoy_first["counts"]["artifacts"] += 1
    decoy_first["counts"]["sources"] += 1
    decoy_first["artifacts"].insert(
        0,
        {
            "artifact_id": "decoy-first",
            "source_id": "decoy",
            "relative_path": "normalized/decoy.jsonl",
            "sha256": "f" * 64,
            "byte_length": 10,
            "row_count": 0,
        },
    )
    functional_bundle = _load_module("raptor.external.tsc2_functional.bundle")
    compute_hash = _symbol(functional_bundle, "compute_manifest_content_hash")
    decoy_first["content_hash"] = compute_hash(decoy_first)
    expected_with_decoy = deepcopy(fixture["expected_pins"])
    expected_with_decoy["functional_normalization_bundle"]["manifest_content_hash"] = decoy_first["content_hash"]
    selected = api["validate_input_bundle_manifests"](
        functional_normalization_manifest=decoy_first,
        clipe_projector_manifest=deepcopy(fixture["clipe_manifest"]),
        vamp_crosswalk_manifest=deepcopy(fixture["vamp_manifest"]),
        expected_pins=expected_with_decoy,
    )
    assert (
        selected["functional_normalization_bundle"]["artifacts"]["mavedb_clipe"]["artifact_id"]
        == fixture["expected_pins"]["functional_normalization_bundle"]["artifacts"]["mavedb_clipe"]["artifact_id"]
    )


def test_fp05_pinned_artifact_reads_use_trusted_paths_and_reject_escape_or_symlink(
    tmp_path: Path,
) -> None:
    api = _promotion_ingest_api()
    fixture = _source_manifests_fixture()
    validated = api["validate_input_bundle_manifests"](
        functional_normalization_manifest=deepcopy(fixture["functional_normalization_manifest"]),
        clipe_projector_manifest=deepcopy(fixture["clipe_manifest"]),
        vamp_crosswalk_manifest=deepcopy(fixture["vamp_manifest"]),
        expected_pins=deepcopy(fixture["expected_pins"]),
    )
    err = api["InputPinMismatchError"]
    expected_payloads = fixture["artifact_payloads"]
    run_names = fixture["run_names"]

    fn_root = tmp_path / "functional"
    cp_root = tmp_path / "clipe"
    vx_root = tmp_path / "vamp"
    for root, run_name in (
        (fn_root, run_names["functional_normalization"]),
        (cp_root, run_names["clipe_projector"]),
        (vx_root, run_names["vamp_crosswalk"]),
    ):
        (root / run_name).mkdir(parents=True, exist_ok=True)

    fn_artifacts = validated["functional_normalization_bundle"]["artifacts"]
    cp_mapping = validated["clipe_projector_bundle"]["mapping"]
    vx_crosswalk = validated["vamp_crosswalk_bundle"]["crosswalk"]

    (fn_root / run_names["functional_normalization"] / fn_artifacts["mavedb_clipe"]["relative_path"]).parent.mkdir(
        parents=True, exist_ok=True
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["mavedb_clipe"]["relative_path"]).write_bytes(
        expected_payloads["functional_normalization"]["mavedb_clipe"]
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["igvf_vamp_seq"]["relative_path"]).parent.mkdir(
        parents=True, exist_ok=True
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["igvf_vamp_seq"]["relative_path"]).write_bytes(
        expected_payloads["functional_normalization"]["igvf_vamp_seq"]
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["igvf_sge"]["relative_path"]).parent.mkdir(
        parents=True, exist_ok=True
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["igvf_sge"]["relative_path"]).write_bytes(
        expected_payloads["functional_normalization"]["igvf_sge"]
    )
    (cp_root / run_names["clipe_projector"] / cp_mapping["relative_path"]).parent.mkdir(parents=True, exist_ok=True)
    (cp_root / run_names["clipe_projector"] / cp_mapping["relative_path"]).write_bytes(
        expected_payloads["clipe_projector_mapping"]
    )
    (vx_root / run_names["vamp_crosswalk"] / vx_crosswalk["relative_path"]).parent.mkdir(parents=True, exist_ok=True)
    (vx_root / run_names["vamp_crosswalk"] / vx_crosswalk["relative_path"]).write_bytes(
        expected_payloads["vamp_crosswalk"]
    )

    payloads = api["read_pinned_artifact_payloads"](
        functional_normalization_root=fn_root,
        clipe_projector_root=cp_root,
        vamp_crosswalk_root=vx_root,
        validated_inputs=validated,
    )
    assert payloads["functional_normalization"]["mavedb_clipe"] == expected_payloads["functional_normalization"]["mavedb_clipe"]
    assert payloads["functional_normalization"]["igvf_vamp_seq"] == expected_payloads["functional_normalization"]["igvf_vamp_seq"]
    assert payloads["functional_normalization"]["igvf_sge"] == expected_payloads["functional_normalization"]["igvf_sge"]
    assert payloads["clipe_projector_mapping"] == expected_payloads["clipe_projector_mapping"]
    assert payloads["vamp_crosswalk"] == expected_payloads["vamp_crosswalk"]

    altered = fn_root / run_names["functional_normalization"] / fn_artifacts["mavedb_clipe"]["relative_path"]
    altered.write_bytes(expected_payloads["functional_normalization"]["mavedb_clipe"] + b"#")
    with pytest.raises(err):
        api["read_pinned_artifact_payloads"](
            functional_normalization_root=fn_root,
            clipe_projector_root=cp_root,
            vamp_crosswalk_root=vx_root,
            validated_inputs=validated,
        )
    altered.write_bytes(expected_payloads["functional_normalization"]["mavedb_clipe"])

    escaped = deepcopy(validated)
    escaped["functional_normalization_bundle"]["artifacts"]["mavedb_clipe"]["relative_path"] = "..\\..\\escape.jsonl"
    with pytest.raises(err):
        api["read_pinned_artifact_payloads"](
            functional_normalization_root=fn_root,
            clipe_projector_root=cp_root,
            vamp_crosswalk_root=vx_root,
            validated_inputs=escaped,
        )

    symlink_validated = deepcopy(validated)
    target = tmp_path / "outside.jsonl"
    target.write_bytes(b"outside")
    symlink_path = fn_root / run_names["functional_normalization"] / "normalized" / "symlinked.jsonl"
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    symlink_path.symlink_to(target)
    symlink_validated["functional_normalization_bundle"]["artifacts"]["mavedb_clipe"]["relative_path"] = (
        "normalized/symlinked.jsonl"
    )
    with pytest.raises(err):
        api["read_pinned_artifact_payloads"](
            functional_normalization_root=fn_root,
            clipe_projector_root=cp_root,
            vamp_crosswalk_root=vx_root,
            validated_inputs=symlink_validated,
        )

    # Symlink target remains inside the same run directory; still reject
    # any symlinked artifact path before path resolution/following.
    inrun_target = fn_root / run_names["functional_normalization"] / "normalized" / "inrun-target.jsonl"
    inrun_target.write_bytes(expected_payloads["functional_normalization"]["mavedb_clipe"])
    inrun_link = fn_root / run_names["functional_normalization"] / "normalized" / "inrun-link.jsonl"
    if inrun_link.exists() or inrun_link.is_symlink():
        inrun_link.unlink()
    inrun_link.symlink_to(inrun_target.name)
    inrun_symlink_validated = deepcopy(validated)
    inrun_symlink_validated["functional_normalization_bundle"]["artifacts"]["mavedb_clipe"]["relative_path"] = (
        "normalized/inrun-link.jsonl"
    )
    with pytest.raises(err):
        api["read_pinned_artifact_payloads"](
            functional_normalization_root=fn_root,
            clipe_projector_root=cp_root,
            vamp_crosswalk_root=vx_root,
            validated_inputs=inrun_symlink_validated,
        )

    # Component symlink inside run tree should also be rejected.
    component_target_dir = fn_root / run_names["functional_normalization"] / "normalized-target"
    component_target_dir.mkdir(parents=True, exist_ok=True)
    (component_target_dir / "mavedb.jsonl").write_bytes(expected_payloads["functional_normalization"]["mavedb_clipe"])
    component_link_dir = fn_root / run_names["functional_normalization"] / "normalized-component-link"
    if component_link_dir.exists() or component_link_dir.is_symlink():
        component_link_dir.unlink()
    component_link_dir.symlink_to(component_target_dir, target_is_directory=True)
    component_symlink_validated = deepcopy(validated)
    component_symlink_validated["functional_normalization_bundle"]["artifacts"]["mavedb_clipe"]["relative_path"] = (
        "normalized-component-link/mavedb.jsonl"
    )
    with pytest.raises(err):
        api["read_pinned_artifact_payloads"](
            functional_normalization_root=fn_root,
            clipe_projector_root=cp_root,
            vamp_crosswalk_root=vx_root,
            validated_inputs=component_symlink_validated,
        )

    # Root itself must not be a symlink/junction-like alias.
    fn_root_symlink = tmp_path / "functional-root-symlink"
    if fn_root_symlink.exists() or fn_root_symlink.is_symlink():
        fn_root_symlink.unlink()
    fn_root_symlink.symlink_to(fn_root, target_is_directory=True)
    with pytest.raises(err):
        api["read_pinned_artifact_payloads"](
            functional_normalization_root=fn_root_symlink,
            clipe_projector_root=cp_root,
            vamp_crosswalk_root=vx_root,
            validated_inputs=validated,
        )


def test_fp05a_pinned_artifact_reads_reject_windows_reparse_like_component_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _promotion_ingest_api()
    fixture = _source_manifests_fixture()
    validated = api["validate_input_bundle_manifests"](
        functional_normalization_manifest=deepcopy(fixture["functional_normalization_manifest"]),
        clipe_projector_manifest=deepcopy(fixture["clipe_manifest"]),
        vamp_crosswalk_manifest=deepcopy(fixture["vamp_manifest"]),
        expected_pins=deepcopy(fixture["expected_pins"]),
    )
    err = api["InputPinMismatchError"]
    expected_payloads = fixture["artifact_payloads"]
    run_names = fixture["run_names"]

    fn_root = tmp_path / "functional"
    cp_root = tmp_path / "clipe"
    vx_root = tmp_path / "vamp"
    for root, run_name in (
        (fn_root, run_names["functional_normalization"]),
        (cp_root, run_names["clipe_projector"]),
        (vx_root, run_names["vamp_crosswalk"]),
    ):
        (root / run_name).mkdir(parents=True, exist_ok=True)

    fn_artifacts = validated["functional_normalization_bundle"]["artifacts"]
    cp_mapping = validated["clipe_projector_bundle"]["mapping"]
    vx_crosswalk = validated["vamp_crosswalk_bundle"]["crosswalk"]
    (fn_root / run_names["functional_normalization"] / fn_artifacts["mavedb_clipe"]["relative_path"]).parent.mkdir(
        parents=True, exist_ok=True
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["mavedb_clipe"]["relative_path"]).write_bytes(
        expected_payloads["functional_normalization"]["mavedb_clipe"]
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["igvf_vamp_seq"]["relative_path"]).parent.mkdir(
        parents=True, exist_ok=True
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["igvf_vamp_seq"]["relative_path"]).write_bytes(
        expected_payloads["functional_normalization"]["igvf_vamp_seq"]
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["igvf_sge"]["relative_path"]).parent.mkdir(
        parents=True, exist_ok=True
    )
    (fn_root / run_names["functional_normalization"] / fn_artifacts["igvf_sge"]["relative_path"]).write_bytes(
        expected_payloads["functional_normalization"]["igvf_sge"]
    )
    (cp_root / run_names["clipe_projector"] / cp_mapping["relative_path"]).parent.mkdir(parents=True, exist_ok=True)
    (cp_root / run_names["clipe_projector"] / cp_mapping["relative_path"]).write_bytes(
        expected_payloads["clipe_projector_mapping"]
    )
    (vx_root / run_names["vamp_crosswalk"] / vx_crosswalk["relative_path"]).parent.mkdir(parents=True, exist_ok=True)
    (vx_root / run_names["vamp_crosswalk"] / vx_crosswalk["relative_path"]).write_bytes(
        expected_payloads["vamp_crosswalk"]
    )

    ingest_module = _load_module("raptor.external.tsc2_identity_promotion.ingest")
    reparse_predicate_name = "_is_symlink_or_reparse_point"
    if getattr(ingest_module, reparse_predicate_name, None) is None:
        pytest.fail(
            "ingest must expose _is_symlink_or_reparse_point(path) and use it before resolve/open"
        )
    probed_components: list[str] = []

    def _fake_reparse_predicate(path: Path) -> bool:
        path_text = str(path).replace("\\", "/")
        probed_components.append(path_text)
        return "simulated-reparse-component" in path_text

    monkeypatch.setattr(ingest_module, reparse_predicate_name, _fake_reparse_predicate)
    simulated_reparse_path = (
        fn_root
        / run_names["functional_normalization"]
        / "normalized"
        / "simulated-reparse-component"
        / "mavedb.jsonl"
    )
    simulated_reparse_path.parent.mkdir(parents=True, exist_ok=True)
    simulated_reparse_path.write_bytes(expected_payloads["functional_normalization"]["mavedb_clipe"])
    reparse_validated = deepcopy(validated)
    reparse_validated["functional_normalization_bundle"]["artifacts"]["mavedb_clipe"]["relative_path"] = (
        "normalized/simulated-reparse-component/mavedb.jsonl"
    )
    with pytest.raises(err):
        api["read_pinned_artifact_payloads"](
            functional_normalization_root=fn_root,
            clipe_projector_root=cp_root,
            vamp_crosswalk_root=vx_root,
            validated_inputs=reparse_validated,
        )
    assert any("simulated-reparse-component" in component for component in probed_components)


def test_fp06_source_row_revalidation_rejects_duplicate_or_noncontiguous_keys_and_schema_drift() -> None:
    api = _promotion_ingest_api()
    fixture = _tiny_promotable_fixture()
    err = api["PromotionJoinError"]

    bad_schema = deepcopy(fixture)
    bad_schema["functional_rows"][0]["schema"] = "raptor.external.normalized_functional_row.v0"
    with pytest.raises(err):
        api["promote_functional_identities"](
            functional_rows=bad_schema["functional_rows"],
            clipe_mapping_rows=bad_schema["clipe_mapping_rows"],
            vamp_crosswalk_rows=bad_schema["vamp_crosswalk_rows"],
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
        )

    duplicate = deepcopy(fixture)
    duplicate["functional_rows"].append(deepcopy(duplicate["functional_rows"][0]))
    with pytest.raises(err):
        api["promote_functional_identities"](
            functional_rows=duplicate["functional_rows"],
            clipe_mapping_rows=duplicate["clipe_mapping_rows"],
            vamp_crosswalk_rows=duplicate["vamp_crosswalk_rows"],
            expected_source_rows={"mavedb_clipe": 3, "igvf_vamp_seq": 3, "igvf_sge": 2},
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
        )

    noncontiguous = deepcopy(fixture)
    noncontiguous["clipe_mapping_rows"][1]["source_row"] = 5
    with pytest.raises(err):
        api["promote_functional_identities"](
            functional_rows=noncontiguous["functional_rows"],
            clipe_mapping_rows=noncontiguous["clipe_mapping_rows"],
            vamp_crosswalk_rows=noncontiguous["vamp_crosswalk_rows"],
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
        )


def test_fp07_clipe_join_is_exact_and_promotes_all_rows_with_status_projected_only() -> None:
    api = _promotion_ingest_api()
    fixture = _tiny_promotable_fixture()

    result = api["promote_functional_identities"](
        functional_rows=fixture["functional_rows"],
        clipe_mapping_rows=fixture["clipe_mapping_rows"],
        vamp_crosswalk_rows=fixture["vamp_crosswalk_rows"],
        expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
    )
    clipe_rows = [row for row in result["promoted_rows"] if row["source_id"] == "mavedb_clipe"]
    assert len(clipe_rows) == 2
    assert all(row["identity_state"] == "GENOMIC_SPDI_VERIFIED" for row in clipe_rows)
    assert all(row["unresolved_reason"] is None for row in clipe_rows)
    assert [row["source_row"] for row in clipe_rows] == [1, 2]
    assert all(row["spdi"].startswith("NC_000016.10:") for row in clipe_rows)

    mismatch = deepcopy(fixture)
    mismatch["clipe_mapping_rows"][0]["hgvs_c"] = f"{TRANSCRIPT}:c.1600G>T"
    with pytest.raises(api["PromotionJoinError"]):
        api["promote_functional_identities"](
            functional_rows=mismatch["functional_rows"],
            clipe_mapping_rows=mismatch["clipe_mapping_rows"],
            vamp_crosswalk_rows=mismatch["vamp_crosswalk_rows"],
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
        )

    bad_status = deepcopy(fixture)
    bad_status["clipe_mapping_rows"][1]["status"] = "STEP2_HTTP_ERROR"
    with pytest.raises(api["PromotionJoinError"]):
        api["promote_functional_identities"](
            functional_rows=bad_status["functional_rows"],
            clipe_mapping_rows=bad_status["clipe_mapping_rows"],
            vamp_crosswalk_rows=bad_status["vamp_crosswalk_rows"],
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
        )


def test_fp08_vamp_join_maps_three_statuses_and_rejects_reference_mismatch_or_unknown_status() -> None:
    api = _promotion_ingest_api()
    fixture = _tiny_promotable_fixture()

    result = api["promote_functional_identities"](
        functional_rows=fixture["functional_rows"],
        clipe_mapping_rows=fixture["clipe_mapping_rows"],
        vamp_crosswalk_rows=fixture["vamp_crosswalk_rows"],
        expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
    )
    vamp_rows = [row for row in result["promoted_rows"] if row["source_id"] == "igvf_vamp_seq"]
    by_row = {row["source_row"]: row for row in vamp_rows}
    assert by_row[1]["identity_state"] == "GENOMIC_SPDI_VERIFIED"
    assert by_row[1]["unresolved_reason"] is None
    assert by_row[1]["spdi"] == "NC_000016.10:2065518:G:A"
    assert by_row[2]["identity_state"] == "GENOMIC_CROSSWALK_LENGTH_MISMATCH"
    assert by_row[2]["unresolved_reason"] == "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT"
    assert by_row[2]["spdi"] is None
    assert by_row[2]["transcript"] == TRANSCRIPT
    assert by_row[2]["hgvs_c"] == f"{TRANSCRIPT}:c.1627_1629delinsTGA"
    assert by_row[3]["identity_state"] == "PROTEIN_ONLY_ARCHIVE_CROSSWALK_ABSENT"
    assert by_row[3]["unresolved_reason"] == "PROTEIN_VARIANT_NOT_IN_ARCHIVE"
    assert by_row[3]["spdi"] is None
    assert by_row[3]["transcript"] is None
    assert by_row[3]["hgvs_c"] is None

    ref_mismatch = deepcopy(fixture)
    ref_mismatch["vamp_crosswalk_rows"][1]["status"] = "SOURCE_COORDINATE_REFERENCE_MISMATCH"
    with pytest.raises(api["PromotionJoinError"]):
        api["promote_functional_identities"](
            functional_rows=ref_mismatch["functional_rows"],
            clipe_mapping_rows=ref_mismatch["clipe_mapping_rows"],
            vamp_crosswalk_rows=ref_mismatch["vamp_crosswalk_rows"],
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
        )

    unknown = deepcopy(fixture)
    unknown["vamp_crosswalk_rows"][2]["status"] = "NOT_A_REAL_STATUS"
    with pytest.raises(api["PromotionJoinError"]):
        api["promote_functional_identities"](
            functional_rows=unknown["functional_rows"],
            clipe_mapping_rows=unknown["clipe_mapping_rows"],
            vamp_crosswalk_rows=unknown["vamp_crosswalk_rows"],
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
        )


def test_fp09_sge_rows_are_copied_semantically_identical_and_revalidated() -> None:
    api = _promotion_ingest_api()
    fixture = _tiny_promotable_fixture()
    result = api["promote_functional_identities"](
        functional_rows=fixture["functional_rows"],
        clipe_mapping_rows=fixture["clipe_mapping_rows"],
        vamp_crosswalk_rows=fixture["vamp_crosswalk_rows"],
        expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
    )
    promoted_sge = [row for row in result["promoted_rows"] if row["source_id"] == "igvf_sge"]
    original_sge = [row for row in fixture["functional_rows"] if row["source_id"] == "igvf_sge"]
    assert promoted_sge == original_sge

    malformed = deepcopy(fixture)
    malformed["functional_rows"][-1]["score_raw"] = "NaN"
    with pytest.raises(api["PromotionJoinError"]):
        api["promote_functional_identities"](
            functional_rows=malformed["functional_rows"],
            clipe_mapping_rows=malformed["clipe_mapping_rows"],
            vamp_crosswalk_rows=malformed["vamp_crosswalk_rows"],
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
        )


def test_fp10_conservation_and_duplicate_source_row_rejection_hold_across_sources() -> None:
    api = _promotion_ingest_api()
    fixture = _tiny_promotable_fixture()
    result = api["promote_functional_identities"](
        functional_rows=fixture["functional_rows"],
        clipe_mapping_rows=fixture["clipe_mapping_rows"],
        vamp_crosswalk_rows=fixture["vamp_crosswalk_rows"],
        expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 2},
        transcript=TRANSCRIPT,
        genomic_accession=GENOMIC_ACCESSION,
        assembly=ASSEMBLY,
    )
    assert result["counts"]["input_rows"] == 7
    assert result["counts"]["output_rows"] == 7
    assert result["counts"]["dropped_rows"] == 0

    duplicate = deepcopy(fixture)
    duplicate["functional_rows"].append(
        _functional_row(
            source_id="igvf_sge",
            source_row=2,
            source_record_id="NC_000016.10:g.duplicate",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_REFERENCE_MISMATCH",
            unresolved_reason="REFERENCE_ALLELE_MISMATCH",
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.200A>G",
            hgvs_p="p.Lys67Arg",
            hgvs_g=None,
            spdi=None,
        )
    )
    with pytest.raises(api["PromotionJoinError"]):
        api["promote_functional_identities"](
            functional_rows=duplicate["functional_rows"],
            clipe_mapping_rows=duplicate["clipe_mapping_rows"],
            vamp_crosswalk_rows=duplicate["vamp_crosswalk_rows"],
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 3, "igvf_sge": 3},
            transcript=TRANSCRIPT,
            genomic_accession=GENOMIC_ACCESSION,
            assembly=ASSEMBLY,
        )


def test_fp11_verified_spdi_overlap_is_deterministic_and_reports_union_duplicates_pairwise_and_triple() -> None:
    api = _promotion_ingest_api()
    promoted_rows = [
        _functional_row(
            source_id="mavedb_clipe",
            source_row=1,
            source_record_id="m1",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.1A>G",
            hgvs_p="p.X1",
            hgvs_g="NC_000016.10:g.101A>G",
            spdi="NC_000016.10:100:A:G",
        ),
        _functional_row(
            source_id="mavedb_clipe",
            source_row=2,
            source_record_id="m2",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.2A>G",
            hgvs_p="p.X2",
            hgvs_g="NC_000016.10:g.201A>G",
            spdi="NC_000016.10:200:A:G",
        ),
        _functional_row(
            source_id="igvf_vamp_seq",
            source_row=1,
            source_record_id="v1",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=VAMP_PROTEIN_ACCESSION,
            hgvs_c=f"{TRANSCRIPT}:c.2A>G",
            hgvs_p="p.X2",
            hgvs_g="NC_000016.10:g.201A>G",
            spdi="NC_000016.10:200:A:G",
        ),
        _functional_row(
            source_id="igvf_vamp_seq",
            source_row=2,
            source_record_id="v2",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=VAMP_PROTEIN_ACCESSION,
            hgvs_c=f"{TRANSCRIPT}:c.3A>G",
            hgvs_p="p.X3",
            hgvs_g="NC_000016.10:g.301A>G",
            spdi="NC_000016.10:300:A:G",
        ),
        _functional_row(
            source_id="igvf_sge",
            source_row=1,
            source_record_id="s1",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.2A>G",
            hgvs_p="p.X2",
            hgvs_g="NC_000016.10:g.201A>G",
            spdi="NC_000016.10:200:A:G",
        ),
        _functional_row(
            source_id="igvf_sge",
            source_row=2,
            source_record_id="s2",
            variant_kind="MISSENSE",
            identity_state="GENOMIC_SPDI_VERIFIED",
            unresolved_reason=None,
            protein_accession=None,
            hgvs_c=f"{TRANSCRIPT}:c.4A>G",
            hgvs_p="p.X4",
            hgvs_g="NC_000016.10:g.401A>G",
            spdi="NC_000016.10:400:A:G",
        ),
    ]

    overlap_a = api["compute_verified_spdi_overlap"](rows=promoted_rows)
    overlap_b = api["compute_verified_spdi_overlap"](rows=list(reversed(promoted_rows)))
    assert overlap_a == overlap_b
    assert overlap_a["verified_observations_by_source"] == {"mavedb_clipe": 2, "igvf_vamp_seq": 2, "igvf_sge": 2}
    assert overlap_a["verified_observations"] == 6
    assert overlap_a["verified_unique_spdi"] == 4
    assert overlap_a["duplicate_verified_observations"] == 2
    assert overlap_a["source_overlap"]["pairwise"]["mavedb_clipe__igvf_vamp_seq"] == 1
    assert overlap_a["source_overlap"]["pairwise"]["mavedb_clipe__igvf_sge"] == 1
    assert overlap_a["source_overlap"]["pairwise"]["igvf_vamp_seq__igvf_sge"] == 1
    assert overlap_a["source_overlap"]["triple"] == 1


def test_fp12_operator_expected_pilot_gate_checks_all_axes_before_publication() -> None:
    operator = _load_operator_module()
    helper = getattr(operator, "_validate_expected_pilot_result", None)
    if helper is None:
        pytest.fail("operator must define _validate_expected_pilot_result(manifest, expected_pilot)")
    domain_error = getattr(operator, "FunctionalIdentityPromotionOperatorError", RuntimeError)

    manifest = {
        "counts": {"rows": EXPECTED_TOTAL_ROWS},
        "source_row_counts": deepcopy(EXPECTED_SOURCE_ROWS),
        "identity_state_counts": deepcopy(EXPECTED_IDENTITY_STATE_COUNTS),
        "unresolved_reason_counts": deepcopy(EXPECTED_UNRESOLVED_REASON_COUNTS),
        "variant_kind_counts": deepcopy(EXPECTED_VARIANT_KIND_COUNTS),
        "verified_observations_by_source": deepcopy(EXPECTED_VERIFIED_BY_SOURCE),
        "verified_observations": EXPECTED_VERIFIED_OBSERVATIONS,
        "verified_unique_spdi": EXPECTED_VERIFIED_UNIQUE_SPDI,
        "duplicate_verified_observations": EXPECTED_DUPLICATE_VERIFIED_OBSERVATIONS,
        "source_overlap": {"pairwise": deepcopy(EXPECTED_PAIRWISE), "triple": EXPECTED_TRIPLE},
        "conservation": {"input_rows": EXPECTED_TOTAL_ROWS, "output_rows": EXPECTED_TOTAL_ROWS, "dropped_rows": 0, "duplicate_source_rows": 0},
    }
    expected = {
        "total_rows": EXPECTED_TOTAL_ROWS,
        "source_rows": deepcopy(EXPECTED_SOURCE_ROWS),
        "identity_state_counts": deepcopy(EXPECTED_IDENTITY_STATE_COUNTS),
        "unresolved_reason_counts": deepcopy(EXPECTED_UNRESOLVED_REASON_COUNTS),
        "variant_kind_counts": deepcopy(EXPECTED_VARIANT_KIND_COUNTS),
        "verified_observations_by_source": deepcopy(EXPECTED_VERIFIED_BY_SOURCE),
        "verified_observations": EXPECTED_VERIFIED_OBSERVATIONS,
        "verified_unique_spdi": EXPECTED_VERIFIED_UNIQUE_SPDI,
        "duplicate_verified_observations": EXPECTED_DUPLICATE_VERIFIED_OBSERVATIONS,
        "source_overlap": {"pairwise": deepcopy(EXPECTED_PAIRWISE), "triple": EXPECTED_TRIPLE},
        "conservation": {"input_rows": EXPECTED_TOTAL_ROWS, "output_rows": EXPECTED_TOTAL_ROWS, "dropped_rows": 0, "duplicate_source_rows": 0},
    }
    helper(manifest=deepcopy(manifest), expected_pilot=deepcopy(expected))

    drifts: list[tuple[str, dict[str, Any]]] = [
        ("total_rows", {**expected, "total_rows": EXPECTED_TOTAL_ROWS - 1}),
        ("identity_state_counts", {**expected, "identity_state_counts": {**expected["identity_state_counts"], "GENOMIC_SPDI_VERIFIED": 1}}),
        ("unresolved_reason_counts", {**expected, "unresolved_reason_counts": {**expected["unresolved_reason_counts"], "PROTEIN_VARIANT_NOT_IN_ARCHIVE": 0}}),
        ("variant_kind_counts", {**expected, "variant_kind_counts": {**expected["variant_kind_counts"], "MISSENSE": 1}}),
        ("verified_unique_spdi", {**expected, "verified_unique_spdi": 123}),
        ("source_overlap", {**expected, "source_overlap": {"pairwise": {**EXPECTED_PAIRWISE, "mavedb_clipe__igvf_sge": 1}, "triple": EXPECTED_TRIPLE}}),
        ("conservation", {**expected, "conservation": {**expected["conservation"], "output_rows": 0}}),
    ]
    for axis, drifted in drifts:
        with pytest.raises(domain_error) as raised:
            helper(manifest=deepcopy(manifest), expected_pilot=drifted)
        assert axis in str(raised.value)

    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"functional identity promotion operator script is not implemented: {OPERATOR_SCRIPT}")
    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    main_node = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"), None)
    if main_node is None:
        pytest.fail("operator script is missing main(argv=...)")
    first_seen: dict[str, int] = {}
    for node in ast.walk(main_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                first_seen.setdefault(node.func.id, node.lineno)
            elif isinstance(node.func, ast.Attribute):
                first_seen.setdefault(node.func.attr, node.lineno)
    assert "_validate_expected_pilot_result" in first_seen
    assert "publish_identity_promotion_bundle" in first_seen
    assert first_seen["_validate_expected_pilot_result"] < first_seen["publish_identity_promotion_bundle"]


def test_fp13_canonical_jsonl_manifest_crossrefs_and_aggregate_only_summary_contract() -> None:
    api = _promotion_bundle_api()
    fixture = _tiny_promotion_manifest_fixture(api)
    promoted = fixture["promoted_rows"]
    manifest = fixture["manifest"]
    payload_all = api["canonical_jsonl_bytes"](promoted)
    assert payload_all.endswith(b"\n")
    assert payload_all == api["canonical_jsonl_bytes"](list(promoted))
    assert [(artifact["artifact_id"], artifact["relative_path"]) for artifact in manifest["artifacts"]] == PROMOTED_ARTIFACTS
    assert manifest["boundaries"] == REQUIRED_BOUNDARIES
    assert manifest["schema"] == PROMOTION_BUNDLE_SCHEMA
    assert manifest["content_hash"] == api["compute_manifest_content_hash"](manifest)
    api["validate_manifest_content_hash"](manifest)

    summary = api["build_committed_summary"](manifest)
    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "input_manifest_hashes",
        "artifact_integrity",
        "source_row_counts",
        "identity_state_counts",
        "unresolved_reason_counts",
        "variant_kind_counts",
        "verified_observations_by_source",
        "verified_observations",
        "verified_unique_spdi",
        "duplicate_verified_observations",
        "source_overlap",
        "conservation",
        "boundaries",
    }
    assert summary["schema"] == PROMOTION_SUMMARY_SCHEMA
    merged = json.dumps(summary, sort_keys=True).lower()
    assert "hgvs_c" not in merged
    assert "hgvs_p" not in merged
    assert "hgvs_g" not in merged
    assert "spdi" not in merged or "verified_unique_spdi" in merged
    assert "score_raw" not in merged


def test_fp13a_manifest_artifact_whitelist_rejects_noncanonical_ids_and_paths() -> None:
    api = _promotion_bundle_api()
    fixture = _tiny_promotion_manifest_fixture(api)
    base_args = deepcopy(fixture["build_args"])
    err = api["PromotionManifestError"]

    bad_id = deepcopy(base_args)
    bad_id["artifacts"][0]["artifact_id"] = "clinical_hgvs_rows"
    with pytest.raises(err):
        api["build_identity_promotion_manifest"](**bad_id)

    bad_hgvs_like_id = deepcopy(base_args)
    bad_hgvs_like_id["artifacts"][1]["artifact_id"] = "hgvs_g_rows"
    with pytest.raises(err):
        api["build_identity_promotion_manifest"](**bad_hgvs_like_id)

    bad_path = deepcopy(base_args)
    bad_path["artifacts"][2]["relative_path"] = "normalized/igvf_sge_alt.jsonl"
    with pytest.raises(err):
        api["build_identity_promotion_manifest"](**bad_path)


def test_fp13b_manifest_boundaries_are_exact_and_summary_validates_manifest_first() -> None:
    api = _promotion_bundle_api()
    fixture = _tiny_promotion_manifest_fixture(api)
    manifest = fixture["manifest"]
    err = api["PromotionManifestError"]
    assert manifest["boundaries"] == REQUIRED_BOUNDARIES

    for drifted_boundaries in (
        {"network": "allowed", "clinical_use": "forbidden", "evidence_strength_use": "forbidden"},
        {"network": "forbidden", "clinical_use": "forbidden"},
        {"network": "forbidden", "clinical_use": "forbidden", "evidence_strength_use": "forbidden", "extra": "forbidden"},
    ):
        drifted = deepcopy(manifest)
        drifted["boundaries"] = drifted_boundaries
        drifted["content_hash"] = api["compute_manifest_content_hash"](drifted)
        with pytest.raises(err):
            api["validate_manifest_content_hash"](drifted)

    summary_drift = deepcopy(manifest)
    summary_drift["boundaries"] = {
        "network": "forbidden",
        "clinical_use": "forbidden",
        "evidence_strength_use": "forbidden",
        "unexpected": "forbidden",
    }
    summary_drift["content_hash"] = api["compute_manifest_content_hash"](summary_drift)
    with pytest.raises(err):
        api["build_committed_summary"](summary_drift)


def test_fp13c_variant_kind_counts_require_nonnegative_ints_and_no_bool() -> None:
    api = _promotion_bundle_api()
    fixture = _tiny_promotion_manifest_fixture(api)
    manifest = fixture["manifest"]
    err = api["PromotionManifestError"]

    for key, invalid_value in (("MISSENSE", -1), ("STOP_GAINED", "3"), ("OTHER", True)):
        drifted = deepcopy(manifest)
        drifted["variant_kind_counts"][key] = invalid_value
        drifted["content_hash"] = api["compute_manifest_content_hash"](drifted)
        with pytest.raises(err):
            api["validate_manifest_content_hash"](drifted)


def test_fp13c2_manifest_counts_and_unresolved_reason_counts_require_nonbool_nonnegative_ints() -> None:
    api = _promotion_bundle_api()
    fixture = _tiny_promotion_manifest_fixture(api)
    manifest = fixture["manifest"]
    err = api["PromotionManifestError"]

    for invalid_rows in (6.0, True, -1, "7"):
        drifted = deepcopy(manifest)
        drifted["counts"]["rows"] = invalid_rows
        drifted["content_hash"] = api["compute_manifest_content_hash"](drifted)
        with pytest.raises(err):
            api["validate_manifest_content_hash"](drifted)

    unresolved_mutations = (
        ("REFERENCE_ALLELE_MISMATCH", 6.0),
        ("SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT", -1),
        ("PROTEIN_VARIANT_NOT_IN_ARCHIVE", "1"),
        ("NOT_A_VARIANT", True),
    )
    for reason, invalid_value in unresolved_mutations:
        drifted = deepcopy(manifest)
        drifted["unresolved_reason_counts"][reason] = invalid_value
        drifted["content_hash"] = api["compute_manifest_content_hash"](drifted)
        with pytest.raises(err):
            api["validate_manifest_content_hash"](drifted)


def test_fp13d_overlap_arithmetic_invariants_reject_impossible_self_hashed_manifests() -> None:
    api = _promotion_bundle_api()
    fixture = _tiny_promotion_manifest_fixture(api)
    manifest = fixture["manifest"]
    err = api["PromotionManifestError"]

    verified_by_source = manifest["verified_observations_by_source"]
    pairwise = manifest["source_overlap"]["pairwise"]
    triple = manifest["source_overlap"]["triple"]
    unique_expected = (
        sum(verified_by_source.values())
        - sum(pairwise.values())
        + triple
    )
    assert manifest["verified_unique_spdi"] == unique_expected
    assert manifest["duplicate_verified_observations"] == manifest["verified_observations"] - manifest["verified_unique_spdi"]

    too_large_pairwise = deepcopy(manifest)
    too_large_pairwise["source_overlap"]["pairwise"]["mavedb_clipe__igvf_vamp_seq"] = 3
    too_large_pairwise["content_hash"] = api["compute_manifest_content_hash"](too_large_pairwise)
    with pytest.raises(err):
        api["validate_manifest_content_hash"](too_large_pairwise)

    too_large_triple = deepcopy(manifest)
    too_large_triple["source_overlap"]["triple"] = 2
    too_large_triple["content_hash"] = api["compute_manifest_content_hash"](too_large_triple)
    with pytest.raises(err):
        api["validate_manifest_content_hash"](too_large_triple)

    wrong_unique = deepcopy(manifest)
    wrong_unique["verified_unique_spdi"] = 3
    wrong_unique["content_hash"] = api["compute_manifest_content_hash"](wrong_unique)
    with pytest.raises(err):
        api["validate_manifest_content_hash"](wrong_unique)

    wrong_duplicate = deepcopy(manifest)
    wrong_duplicate["duplicate_verified_observations"] = 1
    wrong_duplicate["content_hash"] = api["compute_manifest_content_hash"](wrong_duplicate)
    with pytest.raises(err):
        api["validate_manifest_content_hash"](wrong_duplicate)


def test_fp13d2_venn_region_nonnegativity_rejects_impossible_overlap_shapes() -> None:
    api = _promotion_bundle_api()
    fixture = _tiny_promotion_manifest_fixture(api)
    manifest = fixture["manifest"]
    err = api["PromotionManifestError"]

    impossible = deepcopy(manifest)
    impossible["counts"]["rows"] = 6
    impossible["source_row_counts"] = {"mavedb_clipe": 2, "igvf_vamp_seq": 2, "igvf_sge": 2}
    impossible["identity_state_counts"] = {
        key: (6 if key == "GENOMIC_SPDI_VERIFIED" else 0)
        for key in impossible["identity_state_counts"]
    }
    impossible["unresolved_reason_counts"] = {key: 0 for key in impossible["unresolved_reason_counts"]}
    impossible["variant_kind_counts"] = {
        key: (6 if key == "MISSENSE" else 0)
        for key in impossible["variant_kind_counts"]
    }
    impossible["verified_observations_by_source"] = {"mavedb_clipe": 2, "igvf_vamp_seq": 2, "igvf_sge": 2}
    impossible["verified_observations"] = 6
    impossible["verified_unique_spdi"] = 2
    impossible["duplicate_verified_observations"] = 4
    impossible["source_overlap"] = {
        "pairwise": {
            "mavedb_clipe__igvf_vamp_seq": 2,
            "mavedb_clipe__igvf_sge": 2,
            "igvf_vamp_seq__igvf_sge": 0,
        },
        "triple": 0,
    }
    impossible["conservation"] = {"input_rows": 6, "output_rows": 6, "dropped_rows": 0, "duplicate_source_rows": 0}
    for artifact in impossible["artifacts"]:
        artifact["row_count"] = 2
    impossible["content_hash"] = api["compute_manifest_content_hash"](impossible)
    with pytest.raises(err):
        api["validate_manifest_content_hash"](impossible)

    triple_exceeds_pair = deepcopy(impossible)
    triple_exceeds_pair["source_overlap"] = {
        "pairwise": {
            "mavedb_clipe__igvf_vamp_seq": 0,
            "mavedb_clipe__igvf_sge": 1,
            "igvf_vamp_seq__igvf_sge": 1,
        },
        "triple": 1,
    }
    triple_exceeds_pair["verified_unique_spdi"] = 5
    triple_exceeds_pair["duplicate_verified_observations"] = 1
    triple_exceeds_pair["content_hash"] = api["compute_manifest_content_hash"](triple_exceeds_pair)
    with pytest.raises(err):
        api["validate_manifest_content_hash"](triple_exceeds_pair)


def test_fp13e_summary_rejects_artifact_and_boundary_drift_even_with_self_hash() -> None:
    api = _promotion_bundle_api()
    fixture = _tiny_promotion_manifest_fixture(api)
    manifest = fixture["manifest"]
    err = api["PromotionManifestError"]

    artifact_drift = deepcopy(manifest)
    artifact_drift["artifacts"][0]["artifact_id"] = "clinical_variant_export"
    artifact_drift["content_hash"] = api["compute_manifest_content_hash"](artifact_drift)
    with pytest.raises(err):
        api["build_committed_summary"](artifact_drift)

    boundary_drift = deepcopy(manifest)
    boundary_drift["boundaries"] = {"network": "forbidden", "clinical_use": "forbidden", "evidence_strength_use": "forbidden", "scope": "all"}
    boundary_drift["content_hash"] = api["compute_manifest_content_hash"](boundary_drift)
    with pytest.raises(err):
        api["build_committed_summary"](boundary_drift)


def test_fp14_publication_is_no_clobber_and_refuses_inside_repo_preexisting_or_symlinked_destinations(
    tmp_path: Path,
) -> None:
    api = _promotion_bundle_api()
    source_bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    assert api["_publish_directory_no_replace"] is _symbol(source_bundle_module, "_publish_directory_no_replace")
    fixture = _tiny_promotion_manifest_fixture(api)
    manifest = fixture["manifest"]
    payloads = fixture["payloads_by_artifact_id"]
    output_root = tmp_path / "external"
    output_root.mkdir(parents=True, exist_ok=True)
    preexisting = output_root / OUTPUT_RUN_NAME
    preexisting.mkdir(parents=True, exist_ok=True)
    with pytest.raises(api["PromotionBundleBoundaryError"]):
        api["publish_identity_promotion_bundle"](
            repo_root=tmp_path / "repo-a",
            output_root=output_root,
            run_name=OUTPUT_RUN_NAME,
            manifest=manifest,
            payloads=payloads,
        )
    assert preexisting.exists()
    assert list(preexisting.iterdir()) == []

    repo_root = tmp_path / "repo-b"
    repo_root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(api["PromotionBundleBoundaryError"]):
        api["publish_identity_promotion_bundle"](
            repo_root=repo_root,
            output_root=repo_root / "inside-repo",
            run_name=OUTPUT_RUN_NAME,
            manifest=manifest,
            payloads=payloads,
        )

    linked = tmp_path / "linked-root"
    linked.symlink_to(output_root, target_is_directory=True)
    with pytest.raises(api["PromotionBundleBoundaryError"]):
        api["publish_identity_promotion_bundle"](
            repo_root=tmp_path / "repo-c",
            output_root=linked,
            run_name=OUTPUT_RUN_NAME,
            manifest=manifest,
            payloads=payloads,
        )


def test_fp15_package_and_operator_stay_offline_and_exclude_clinical_ps3_bs3_content() -> None:
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
        pytest.fail("functional identity promotion implementation targets are missing: " + ", ".join(str(path) for path in missing))

    offenders: list[str] = []
    merged_source = ""
    for path in targets:
        merged_source += "\n" + path.read_text(encoding="utf-8").lower()
        for imported, lineno in _module_imports(path):
            lowered = imported.lower()
            if any(lowered == blocked or lowered.startswith(blocked + ".") for blocked in FORBIDDEN_NETWORK_IMPORTS):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
            if any(imported == blocked or imported.startswith(blocked + ".") for blocked in FORBIDDEN_IMPORT_PREFIXES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
    assert not offenders, "forbidden imports detected:\n" + "\n".join(offenders)
    assert not any(token in merged_source for token in FORBIDDEN_CLINICAL_TOKENS)


def test_fp16_config_pins_all_input_hashes_and_output_names_from_spec() -> None:
    if not CONFIG_PATH.is_file():
        pytest.fail(f"functional identity promotion config is not implemented: {CONFIG_PATH}")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["spec_id"] == "raptor-v2-functional-identity-promotion-v1"
    assert config["spec_version"] == "1.0.2"

    functional = config["inputs"]["functional_normalization_bundle"]
    assert functional["run_name"] == FUNCTIONAL_RUN_NAME
    assert functional["bundle_id"] == FUNCTIONAL_BUNDLE_ID
    assert functional["manifest_content_hash"] == FUNCTIONAL_MANIFEST_HASH
    assert functional["artifacts"]["mavedb_clipe"]["relative_path"] == FUNCTIONAL_MAVEDB_RELATIVE_PATH
    assert functional["artifacts"]["mavedb_clipe"]["sha256"] == FUNCTIONAL_MAVEDB_SHA256
    assert functional["artifacts"]["mavedb_clipe"]["byte_length"] == FUNCTIONAL_MAVEDB_BYTE_LENGTH
    assert functional["artifacts"]["mavedb_clipe"]["row_count"] == FUNCTIONAL_MAVEDB_ROWS
    assert functional["artifacts"]["igvf_vamp_seq"]["relative_path"] == FUNCTIONAL_VAMP_RELATIVE_PATH
    assert functional["artifacts"]["igvf_vamp_seq"]["sha256"] == FUNCTIONAL_VAMP_SHA256
    assert functional["artifacts"]["igvf_vamp_seq"]["byte_length"] == FUNCTIONAL_VAMP_BYTE_LENGTH
    assert functional["artifacts"]["igvf_vamp_seq"]["row_count"] == FUNCTIONAL_VAMP_ROWS
    assert functional["artifacts"]["igvf_sge"]["relative_path"] == FUNCTIONAL_SGE_RELATIVE_PATH
    assert functional["artifacts"]["igvf_sge"]["sha256"] == FUNCTIONAL_SGE_SHA256
    assert functional["artifacts"]["igvf_sge"]["byte_length"] == FUNCTIONAL_SGE_BYTE_LENGTH
    assert functional["artifacts"]["igvf_sge"]["row_count"] == FUNCTIONAL_SGE_ROWS

    clipe = config["inputs"]["clipe_projector_bundle"]
    assert clipe["run_name"] == CLIPE_RUN_NAME
    assert clipe["bundle_id"] == CLIPE_BUNDLE_ID
    assert clipe["manifest_content_hash"] == CLIPE_MANIFEST_HASH
    assert clipe["mapping"]["relative_path"] == CLIPE_MAPPING_RELATIVE_PATH
    assert clipe["mapping"]["sha256"] == CLIPE_MAPPING_SHA256
    assert clipe["mapping"]["byte_length"] == CLIPE_MAPPING_BYTE_LENGTH
    assert clipe["mapping"]["row_count"] == CLIPE_MAPPING_ROWS

    vamp = config["inputs"]["vamp_crosswalk_bundle"]
    assert vamp["run_name"] == VAMP_RUN_NAME
    assert vamp["bundle_id"] == VAMP_BUNDLE_ID
    assert vamp["manifest_content_hash"] == VAMP_MANIFEST_HASH
    assert vamp["crosswalk"]["relative_path"] == VAMP_CROSSWALK_RELATIVE_PATH
    assert vamp["crosswalk"]["sha256"] == VAMP_CROSSWALK_SHA256
    assert vamp["crosswalk"]["byte_length"] == VAMP_CROSSWALK_BYTE_LENGTH
    assert vamp["crosswalk"]["row_count"] == VAMP_CROSSWALK_ROWS

    out = config["output"]["external_bundle"]
    assert out["run_name"] == OUTPUT_RUN_NAME
    assert out["bundle_id"] == OUTPUT_BUNDLE_ID
    assert out["manifest_schema"] == PROMOTION_BUNDLE_SCHEMA
    summary = config["output"]["committed_summary"]
    assert summary["path"] == str(SUMMARY_PATH.relative_to(REPO_ROOT)).replace("\\", "/")
    assert summary["schema"] == PROMOTION_SUMMARY_SCHEMA

    expected = config["expected_pilot"]
    assert expected["total_rows"] == EXPECTED_TOTAL_ROWS
    assert expected["source_rows"] == EXPECTED_SOURCE_ROWS
    assert expected["identity_state_counts"] == EXPECTED_IDENTITY_STATE_COUNTS
    assert expected["unresolved_reason_counts"] == EXPECTED_UNRESOLVED_REASON_COUNTS
    assert expected["variant_kind_counts"] == EXPECTED_VARIANT_KIND_COUNTS
    assert expected["verified_observations_by_source"] == EXPECTED_VERIFIED_BY_SOURCE
    assert expected["verified_observations"] == EXPECTED_VERIFIED_OBSERVATIONS
    assert expected["verified_unique_spdi"] == EXPECTED_VERIFIED_UNIQUE_SPDI
    assert expected["duplicate_verified_observations"] == EXPECTED_DUPLICATE_VERIFIED_OBSERVATIONS
    assert expected["source_overlap"]["pairwise"] == EXPECTED_PAIRWISE
    assert expected["source_overlap"]["triple"] == EXPECTED_TRIPLE
    assert expected["conservation"] == {
        "input_rows": EXPECTED_TOTAL_ROWS,
        "output_rows": EXPECTED_TOTAL_ROWS,
        "dropped_rows": 0,
        "duplicate_source_rows": 0,
    }
