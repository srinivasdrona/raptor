from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import re
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-functional-coverage-map-v1.yaml"
CONFIG_PATH = REPO_ROOT / "configs" / "external" / "tsc2_functional_coverage_map_v1.yaml"
OPERATOR_SCRIPT = REPO_ROOT / "scripts" / "build_tsc2_functional_coverage_map.py"
PACKAGE_ROOT = REPO_ROOT / "src" / "raptor" / "external" / "tsc2_functional_coverage"
SUMMARY_PATH = REPO_ROOT / "data" / "census" / "tsc2_functional_coverage_map_2026-09-14.json"
ANCHOR_PATH = REPO_ROOT / "data" / "atlas" / "runs" / "2026-08-03" / "r611q_gate_result.json"

MODEL_PATH = PACKAGE_ROOT / "model.py"
INGEST_PATH = PACKAGE_ROOT / "ingest.py"
COVERAGE_PATH = PACKAGE_ROOT / "coverage.py"
BUNDLE_PATH = PACKAGE_ROOT / "bundle.py"
INIT_PATH = PACKAGE_ROOT / "__init__.py"

SPEC_ID = "raptor-v2-functional-coverage-map-v1"
SPEC_VERSION = "1.0.1"
CONFIG_CANONICAL_LF_SHA256 = "e5082dcbe75338949f386c6b193016befc0f9f7e56b6371267ba07584576ad05"
COVERAGE_ROW_SCHEMA = "raptor.external.tsc2_functional_coverage_row.v1"
BUNDLE_SCHEMA = "raptor.external.tsc2_functional_coverage_bundle.v1"
SUMMARY_SCHEMA = "raptor.external.tsc2_functional_coverage_summary.v1"

SOURCE_ORDER = ["mavedb_clipe", "igvf_vamp_seq", "igvf_sge"]
LEAKAGE_MARKER_ORDER = ["PROSPECTIVE_HOLDOUT", "ATLAS_CONTEXT"]
SOURCE_MEMBERSHIP_PATTERN_KEYS = [
    "mavedb_clipe",
    "igvf_vamp_seq",
    "igvf_sge",
    "mavedb_clipe+igvf_vamp_seq",
    "mavedb_clipe+igvf_sge",
    "igvf_vamp_seq+igvf_sge",
    "mavedb_clipe+igvf_vamp_seq+igvf_sge",
]
FUNCTIONAL_COHORT_MEMBERSHIP_PATTERN_KEYS = [
    "NONE",
    "VUS",
    "VUS+ATLAS_CONTRAST",
    "PROSPECTIVE_HOLDOUT",
    "PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST",
    "PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR",
    "ATLAS_CONTRAST",
]
REQUIRED_COVERAGE_ROW_FIELDS = [
    "schema",
    "spdi",
    "source_ids",
    "observation_count",
    "vus_2026_07",
    "priority_stratum",
    "prospective_holdout_2026_08",
    "atlas_contrast_candidate",
    "atlas_anchor_r611q",
    "leakage_markers",
]
PRIORITY_STRATUM_VALUES = ["candidate_LP_review", "candidate_LB_review", None]

FUNCTIONAL_PROMOTION_RUN_NAME = "tsc2-functional-identity-promotion-2026-09-14"
FUNCTIONAL_PROMOTION_BUNDLE_ID = "tsc2-functional-identity-promotion-2026-09-14"
FUNCTIONAL_PROMOTION_MANIFEST = "bundle_manifest.json"
FUNCTIONAL_PROMOTION_MANIFEST_HASH = "c66639976bf9369cfd07568011a85f5ac50fd0ea9467c54210768574645941ed"
FUNCTIONAL_PROMOTION_ARTIFACTS = {
    "mavedb_clipe": {
        "artifact_id": "mavedb_clipe-promoted-jsonl",
        "relative_path": "normalized/mavedb_clipe.jsonl",
        "sha256": "9241052425a0a785b7da23edef678365f485a2ba973568bf3c5b38270399e2ff",
        "byte_length": 106045,
        "row_count": 208,
    },
    "igvf_vamp_seq": {
        "artifact_id": "igvf_vamp_seq-promoted-jsonl",
        "relative_path": "normalized/igvf_vamp_seq.jsonl",
        "sha256": "dc639dd6ec0f9aeaf4113f5b36d46a2d715d5830eb6dbb370860925a7c9648db",
        "byte_length": 5116593,
        "row_count": 9253,
    },
    "igvf_sge": {
        "artifact_id": "igvf_sge-promoted-jsonl",
        "relative_path": "normalized/igvf_sge.jsonl",
        "sha256": "2292e5770911e13fcd2536287fd04fc7f23354c9bc81ebf01533aa441114ea52",
        "byte_length": 227381,
        "row_count": 453,
    },
}

REAL_VUS_MANIFEST_PIN = {
    "relative_path": "tsc_vus_input.manifest.jsonl",
    "sha256": "7f9937521a425e73b31422fa9191c90e67fa80cc58f351517ac732b1d32fcbba",
    "byte_length": 838920,
    "row_count": 6618,
    "required_fields": ["accession", "contig", "variant_id", "vcf_key"],
}
REAL_VUS_PROVENANCE_PIN = {
    "relative_path": "tsc_vus_input.provenance.json",
    "sha256": "7272529546ad43ac0196523ad83d66eab8388a66a08f589bf10fc296b2110f55",
    "byte_length": 784,
    "required_values": {
        "conservation_count": 6618,
        "corpus_kind": "clinvar_vus_internal_evidence_census",
        "authorization": "internal_non_authoritative_evidence_only",
        "source_snapshot": "clinvar_2026-07-07",
        "manifest_hash": "7f9937521a425e73b31422fa9191c90e67fa80cc58f351517ac732b1d32fcbba",
        "identity_file_sha256": "c4ec45f036addeb38661adb21e16396482bb4e5ef54326b7c9662479cd33024e",
        "vcf_hash": "3fff6de7ae9b2b202642e498c4c49532cf1aaf5c2734f0e8341d5ace88fa3a09",
    },
}
REAL_VUS_BIAS_PIN = {
    "relative_path": "tsc_vus_input.bias_output.tsv",
    "sha256": "0a55cab470d3de93f06cd87ba30957fd1674c0ae2098ec86350f5aaac1a1162e",
    "byte_length": 6095122,
    "row_count": 6618,
}

REAL_PRIORITY_QUEUE_PIN = {
    "relative_path": "candidate_priority_queue.jsonl",
    "sha256": "013be368aa8243aabbde03023cff1ec01d7487bcb2e35c6715259edb625d3670",
    "byte_length": 61713,
    "row_count": 164,
    "exact_fields": [
        "packet_id",
        "evidence_core_hash",
        "canonical_spdi",
        "gene",
        "review_state",
        "gate_status",
        "quality_flags",
        "contradiction",
    ],
    "required_review_state": "POLICY_BLOCKED",
    "required_gate_status": "UNVERIFIED",
}
REAL_PRIORITY_AGGREGATE_PIN = {
    "relative_path": "aggregate_manifest.json",
    "sha256": "516f3607636d169205fa8584c88ad635afa62a06d046ddb0c300859453e17f0e",
    "byte_length": 3051,
    "required_values": {
        "universe_size": 6618,
        "conservation": {
            "manifest_identities": 6618,
            "bias_rows": 6618,
            "candidate_LP_review": 157,
            "candidate_LB_review": 7,
            "no_deterministic_resolution": 6424,
            "manual_review": 30,
        },
        "source_hashes": {
            "manifest_sha256": "7f9937521a425e73b31422fa9191c90e67fa80cc58f351517ac732b1d32fcbba",
            "bias_tsv_sha256": "0a55cab470d3de93f06cd87ba30957fd1674c0ae2098ec86350f5aaac1a1162e",
            "input_vcf_sha256": "3fff6de7ae9b2b202642e498c4c49532cf1aaf5c2734f0e8341d5ace88fa3a09",
        },
        "run_pins": {
            "code_commit": "74a37d14be4f2bf99a56dc49d537446d6a4b3c88",
            "source_snapshot": "clinvar_2026-07-07",
        },
    },
}

REAL_HOLDOUT_MANIFEST_PIN = {
    "relative_path": "holdout_input.manifest.jsonl",
    "sha256": "809ac116a7e0c33e5749173f683f10fd8cd623b5d04ef4919cb972dd9196ace8",
    "byte_length": 325794,
    "row_count": 2608,
    "required_fields": ["accession", "contig", "variant_id", "vcf_key"],
}
REAL_HOLDOUT_PROVENANCE_PIN = {
    "relative_path": "holdout_input.provenance.json",
    "sha256": "58c4732fd4eed308b4b576393f65a37acfff951d9e6062490d1526ec8109f8fd",
    "byte_length": 354,
    "required_values": {
        "archive_sha256": "230ba6d5ac0869bfb46fecb8d19bd8dbfa9a133bfda2e3f8f5b5b662ae7bf500",
        "benchmark_snapshot": "clinvar_2026-08-monthly-amendment-v3",
        "conservation_count": 2608,
        "manifest_hash": "809ac116a7e0c33e5749173f683f10fd8cd623b5d04ef4919cb972dd9196ace8",
        "vcf_hash": "ea0f97bdd896e96f7f64c1f5f6ceda4e2e43156485bf635a6d11f7369dc4e77b",
    },
}
REAL_HOLDOUT_FORBIDDEN_READS = [
    "benchmark.jsonl",
    "train_dev.jsonl",
    "holdout.jsonl",
    "terminal_eval.json",
    "prospective_evidence.json",
    "any label or adjudication artifact",
]

REAL_ATLAS_MAP_PIN = {
    "relative_path": "raw_identity_map.yaml",
    "raw_sha256": "f993d069a8d679953eff2af10c07dfe993746cf3211e8ac2f678fce94e0dcbf7",
    "byte_length": 38067,
    "schema": "atlas.raw_identity_map.v2",
    "map_content_hash": "3adbf3484de28607fa3c133b2bebc4a9d7926b4c2d5b3863b0634507c599cd26",
    "map_record_count": 35,
}
REAL_ATLAS_RESPONSE_BUNDLE_PIN = {
    "sha256": "fbedf2aae5aa26936807f2d8f26389a18a861fc884b461fdd8ebaf6b7e9f96bc",
    "file_count": 88,
    "byte_count": 904564,
}
REAL_ATLAS_RAW_INVENTORY_PIN = {
    "relative_path": "discovery_inventory.raw.yaml",
    "sha256": "fee39ffa9c826b6e0ccb85ad583b09c2f81794036b115d91a91eab521365befb",
    "byte_length": 6062,
    "row_count": 35,
}
REAL_ATLAS_TRACKED_LOCK_PIN = {
    "path": "configs/atlas/panels/tsc2/atlas-phase2-raw-identity-map-lock-v4.yaml",
    "schema": "atlas.raw_identity_map_lock.v2",
    "lock_content_hash": "85bc2b10e65bd8140a775537204f3c7c7048cd5444d7057fbea9501b7cd4b104",
}
REAL_ATLAS_DISEASE_PACK_PIN = {
    "path": "configs/atlas/packs/tsc2/pack.yaml",
    "pack_id": "tsc2",
    "pack_version": "1.0.0-phase1",
    "pack_content_hash": "1294478c6d112f91e5719ee345d2b5be1925567ec4f4abdff50b0e092ff08927",
}
REAL_ATLAS_ANCHOR_PIN = {
    "path": "data/atlas/runs/2026-08-03/r611q_gate_result.json",
    "raw_sha256": "63792ff7df903beba8e0630299b0d694c7d11b51810e351f0af08cacfa675442",
    "schema": "raptor.atlas_public_gate_result.v1",
    "required": {
        "run_id": "r611q-gate1-7-v1",
        "scope": "deterministic_fidelity_only",
        "variant": {"spdi": "NC_000016.10:2070570:G:A"},
        "gate_8": "BLOCKED_HUMAN_REVIEW",
        "accepted_claim_count": 0,
        "promote_candidate_invoked": False,
    },
}

OUTPUT_RUN_NAME = "tsc2-functional-coverage-map-2026-09-14"
OUTPUT_BUNDLE_ID = "tsc2-functional-coverage-map-2026-09-14"
OUTPUT_ARTIFACT_ID = "tsc2-functional-coverage-jsonl"
OUTPUT_ARTIFACT_PATH = "coverage/functional_identity_coverage.jsonl"
OUTPUT_ROW_COUNT = 9552

EXPECTED_PILOT = {
    "functional": {
        "verified_observations": 9681,
        "unique_spdi": 9552,
        "source_unique": {"mavedb_clipe": 208, "igvf_vamp_seq": 9050, "igvf_sge": 423},
        "source_membership_patterns": {
            "mavedb_clipe": 164,
            "igvf_vamp_seq": 8959,
            "igvf_sge": 307,
            "mavedb_clipe+igvf_vamp_seq": 6,
            "mavedb_clipe+igvf_sge": 31,
            "igvf_vamp_seq+igvf_sge": 78,
            "mavedb_clipe+igvf_vamp_seq+igvf_sge": 7,
        },
    },
    "cohorts": {
        "vus": {
            "identities": 6618,
            "TSC1": 2249,
            "TSC2": 4369,
            "functional_overlap_unique": 335,
            "source_overlap_unique": {"mavedb_clipe": 66, "igvf_vamp_seq": 194, "igvf_sge": 105},
            "source_membership_patterns": {
                "mavedb_clipe": 50,
                "igvf_vamp_seq": 178,
                "igvf_sge": 79,
                "mavedb_clipe+igvf_vamp_seq": 2,
                "mavedb_clipe+igvf_sge": 12,
                "igvf_vamp_seq+igvf_sge": 12,
                "mavedb_clipe+igvf_vamp_seq+igvf_sge": 2,
            },
        },
        "priority": {
            "identities": 164,
            "candidate_LP_review": 157,
            "candidate_LB_review": 7,
            "TSC1": 52,
            "TSC2": 112,
            "functional_overlap_unique": 4,
            "candidate_LP_review_overlap": 4,
            "candidate_LB_review_overlap": 0,
            "source_overlap_unique": {"mavedb_clipe": 0, "igvf_vamp_seq": 0, "igvf_sge": 4},
        },
        "prospective_holdout": {
            "identities": 2608,
            "TSC1": 718,
            "TSC2": 1890,
            "functional_overlap_unique": 171,
            "source_overlap_unique": {"mavedb_clipe": 25, "igvf_vamp_seq": 122, "igvf_sge": 40},
            "source_membership_patterns": {
                "mavedb_clipe": 19,
                "igvf_vamp_seq": 111,
                "igvf_sge": 26,
                "mavedb_clipe+igvf_vamp_seq": 1,
                "mavedb_clipe+igvf_sge": 4,
                "igvf_vamp_seq+igvf_sge": 9,
                "mavedb_clipe+igvf_vamp_seq+igvf_sge": 1,
            },
        },
        "atlas_contrast": {
            "raw_records": 35,
            "resolved_unique_spdi": 25,
            "unresolved_records": 10,
            "functional_overlap_unique": 6,
            "source_overlap_unique": {"mavedb_clipe": 3, "igvf_vamp_seq": 2, "igvf_sge": 2},
            "source_membership_patterns": {
                "mavedb_clipe": 2,
                "igvf_vamp_seq": 1,
                "igvf_sge": 2,
                "mavedb_clipe+igvf_vamp_seq": 1,
                "mavedb_clipe+igvf_sge": 0,
                "igvf_vamp_seq+igvf_sge": 0,
                "mavedb_clipe+igvf_vamp_seq+igvf_sge": 0,
            },
        },
        "atlas_anchor": {
            "identities": 1,
            "functional_overlap_unique": 1,
            "source_overlap_unique": {"mavedb_clipe": 1, "igvf_vamp_seq": 0, "igvf_sge": 0},
            "prospective_holdout_overlap": 1,
        },
    },
    "cross_cohort": {
        "vus__prospective_holdout": 0,
        "priority__prospective_holdout": 0,
        "vus__atlas_contrast": 3,
        "priority__atlas_contrast": 0,
        "prospective_holdout__atlas_contrast": 3,
        "functional__vus__atlas_contrast": 1,
        "functional__prospective_holdout__atlas_contrast": 3,
        "functional__atlas_contrast_outside_vus_holdout": 2,
    },
    "functional_cohort_membership_patterns": {
        "NONE": 9044,
        "VUS": 334,
        "VUS+ATLAS_CONTRAST": 1,
        "PROSPECTIVE_HOLDOUT": 167,
        "PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST": 3,
        "PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR": 1,
        "ATLAS_CONTRAST": 2,
    },
    "leakage_markers": {
        "PROSPECTIVE_HOLDOUT": 171,
        "ATLAS_CONTEXT": 7,
        "PROSPECTIVE_HOLDOUT+ATLAS_CONTEXT": 4,
    },
}

BOUNDARIES = {
    "network": "forbidden",
    "score_semantic_use": "forbidden",
    "score_output": "forbidden",
    "label_access": "forbidden",
    "clinical_use": "forbidden",
    "evidence_strength_use": "forbidden",
    "ps3_bs3_use": "forbidden",
    "atlas_claim_promotion": "forbidden",
}

SPDI_CANONICAL_RE = re.compile(r"^NC_0000(?:09\.12|16\.10):[0-9]+:[ACGT]+:[ACGT]+$")
FORBIDDEN_QUOTED_ROW_KEYS = (
    '"variant_id"',
    '"vcf_key"',
    '"spdi"',
    '"hgvs"',
    '"score_raw"',
    '"functional_class"',
    '"label"',
    '"classification"',
    '"ps3"',
    '"bs3"',
    '"clinical_status"',
)
SUMMARY_TOP_LEVEL_KEYS = {
    "schema",
    "bundle_id",
    "manifest_content_hash",
    "input_hashes",
    "functional",
    "cohorts",
    "cross_cohort",
    "functional_cohort_membership_patterns",
    "leakage_markers",
    "output_artifacts",
    "boundaries",
}

ALLOWED_DOMAIN_SEAMS = {
    "raptor.census.strata",
    "raptor.scorer.bias_source",
    "raptor.scorer.config",
    "raptor.eval.config",
    "raptor.atlas.identity_map",
    "raptor.atlas.model",
    "raptor.atlas.pack",
}
REQUIRED_DOMAIN_SEAMS = {
    "raptor.census.strata",
    "raptor.scorer.bias_source",
    "raptor.scorer.config",
    "raptor.eval.config",
    "raptor.atlas.identity_map",
    "raptor.atlas.pack",
}
FORBIDDEN_DOMAIN_PREFIXES = ("raptor.packet", "raptor.kb", "raptor.rescuescreen")
FORBIDDEN_NETWORK_IMPORTS = ("socket", "http", "http.client", "urllib.request", "requests", "httpx", "aiohttp")
FORBIDDEN_OTHER_DOMAIN_PREFIXES = ("raptor.census", "raptor.scorer", "raptor.eval", "raptor.atlas")
FORBIDDEN_OVERLAP_LITERAL_PATTERNS = (
    r"\b9681\b",
    r"\b9552\b",
    r"\b6618\b",
    r"\b2608\b",
    r"\b164\b",
    r"\b157\b",
    r"\b335\b",
    r"\b171\b",
    r"\b9044\b",
    r"\bPROSPECTIVE_HOLDOUT\+ATLAS_CONTEXT\b",
)


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _load_spec() -> dict[str, Any]:
    if not SPEC_PATH.is_file():
        pytest.fail(f"binding spec is missing: {SPEC_PATH}")
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def _load_module(module_name: str):
    try:
        return import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"TSC2 functional coverage module {module_name!r} is not implemented: {exc}")


def _symbol(module: Any, symbol_name: str):
    if not hasattr(module, symbol_name):
        pytest.fail(f"module {module.__name__!r} is missing required symbol {symbol_name!r}")
    return getattr(module, symbol_name)


def _load_operator_module():
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 functional coverage operator script is not implemented: {OPERATOR_SCRIPT}")
    spec = importlib.util.spec_from_file_location("raptor_tsc2_functional_coverage_map_operator", OPERATOR_SCRIPT)
    if spec is None or spec.loader is None:
        pytest.fail(f"unable to load operator module spec from {OPERATOR_SCRIPT}")
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


def _model_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_functional_coverage.model")
    return {
        "COVERAGE_ROW_SCHEMA": _symbol(module, "COVERAGE_ROW_SCHEMA"),
        "REQUIRED_COVERAGE_ROW_FIELDS": _symbol(module, "REQUIRED_COVERAGE_ROW_FIELDS"),
        "SOURCE_ORDER": _symbol(module, "SOURCE_ORDER"),
        "PRIORITY_STRATUM_VALUES": _symbol(module, "PRIORITY_STRATUM_VALUES"),
        "LEAKAGE_MARKER_ORDER": _symbol(module, "LEAKAGE_MARKER_ORDER"),
        "CoverageContractError": _symbol(module, "CoverageContractError"),
        "FunctionalCoverageRow": _symbol(module, "FunctionalCoverageRow"),
    }


def _ingest_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_functional_coverage.ingest")
    return {
        "InputPinMismatchError": _symbol(module, "InputPinMismatchError"),
        "CoverageInputError": _symbol(module, "CoverageInputError"),
        "validate_input_roots_absolute": _symbol(module, "validate_input_roots_absolute"),
        "validate_functional_promotion_manifest": _symbol(module, "validate_functional_promotion_manifest"),
        "validate_promoted_functional_rows": _symbol(module, "validate_promoted_functional_rows"),
        "validate_vus_inputs": _symbol(module, "validate_vus_inputs"),
        "reproduce_priority_subset": _symbol(module, "reproduce_priority_subset"),
        "validate_prospective_holdout_inputs": _symbol(module, "validate_prospective_holdout_inputs"),
        "load_atlas_contrast_replays": _symbol(module, "load_atlas_contrast_replays"),
        "validate_atlas_anchor_input": _symbol(module, "validate_atlas_anchor_input"),
        "read_input_payload": _symbol(module, "read_input_payload"),
    }


def _coverage_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_functional_coverage.coverage")
    return {
        "CoverageBuildError": _symbol(module, "CoverageBuildError"),
        "build_functional_coverage_rows": _symbol(module, "build_functional_coverage_rows"),
        "compute_coverage_statistics": _symbol(module, "compute_coverage_statistics"),
        "validate_expected_pilot_counts": _symbol(module, "validate_expected_pilot_counts"),
    }


def _bundle_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_functional_coverage.bundle")
    return {
        "CoverageBundleBoundaryError": _symbol(module, "CoverageBundleBoundaryError"),
        "CoverageManifestError": _symbol(module, "CoverageManifestError"),
        "canonical_coverage_jsonl_bytes": _symbol(module, "canonical_coverage_jsonl_bytes"),
        "compute_manifest_content_hash": _symbol(module, "compute_manifest_content_hash"),
        "validate_manifest_content_hash": _symbol(module, "validate_manifest_content_hash"),
        "build_coverage_bundle_manifest": _symbol(module, "build_coverage_bundle_manifest"),
        "publish_coverage_bundle": _symbol(module, "publish_coverage_bundle"),
        "build_committed_summary": _symbol(module, "build_committed_summary"),
        "_publish_directory_no_replace": _symbol(module, "_publish_directory_no_replace"),
    }


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        (
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            + b"\n"
        )
        for row in rows
    )


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _canonical_lf(payload: bytes) -> bytes:
    return payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _yaml_bytes(payload: dict[str, Any], *, sort_keys: bool = True) -> bytes:
    return yaml.safe_dump(payload, sort_keys=sort_keys).encode("utf-8")


def _identity_map_lock_content_hash(lock_payload: bytes) -> str:
    parsed = yaml.safe_load(lock_payload.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("lock payload must decode to a mapping")
    atlas_identity_map = import_module("raptor.atlas.identity_map")
    lock_hash_fn = _symbol(atlas_identity_map, "identity_map_lock_content_hash")
    return lock_hash_fn(parsed)


def _response_bundle_observed(file_payloads: dict[str, bytes]) -> dict[str, Any]:
    files = []
    total_bytes = 0
    for relative_path, payload in sorted(file_payloads.items()):
        total_bytes += len(payload)
        files.append(
            {
                "relative_path": str(relative_path).replace("\\", "/"),
                "sha256": _sha256(payload),
                "byte_length": len(payload),
            }
        )
    commitment = _sha256(_json_bytes({"files": files}))
    return {"sha256": commitment, "file_count": len(files), "byte_count": total_bytes}


def _tsv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    lines = ["\t".join(header)]
    lines.extend("\t".join(row) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _flip_first_byte(blob: bytes) -> bytes:
    if not blob:
        return b"\x00"
    return bytes([blob[0] ^ 0x01]) + blob[1:]


def _pin_from_payload(
    *,
    payload: bytes,
    relative_path: str,
    row_count: int,
    required_fields: list[str] | None = None,
    required_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = {
        "relative_path": relative_path,
        "sha256": _sha256(payload),
        "byte_length": len(payload),
        "row_count": row_count,
    }
    if required_fields is not None:
        out["required_fields"] = required_fields
    if required_values is not None:
        out["required_values"] = required_values
    return out


def _parse_spdi(spdi: str) -> tuple[str, int, str, str]:
    accession, pos_text, ref, alt = spdi.split(":")
    return accession, int(pos_text), ref, alt


def _spdi_to_hgvs_g(spdi: str) -> str:
    accession, pos0, ref, alt = _parse_spdi(spdi)
    if len(ref) != len(alt):
        raise ValueError(f"only SNV/equal-length delins supported in synthetic fixture: {spdi}")
    if len(ref) == 1:
        return f"{accession}:g.{pos0 + 1}{ref}>{alt}"
    start = pos0 + 1
    end = pos0 + len(ref)
    return f"{accession}:g.{start}_{end}delins{alt}"


def _promoted_row(*, source_id: str, source_row: int, spdi: str, score_raw: str) -> dict[str, Any]:
    accession, pos0, ref, alt = _parse_spdi(spdi)
    hgvs_g = _spdi_to_hgvs_g(spdi)
    if len(ref) == 1:
        hgvs_c = f"NM_000548.5:c.{1600 + source_row}{ref}>{alt}"
        hgvs_p = "p.Gly534Arg"
    else:
        start = 1627 + source_row
        end = start + len(ref) - 1
        hgvs_c = f"NM_000548.5:c.{start}_{end}delins{alt}"
        hgvs_p = "p.Pro543Ter"
    assert accession == "NC_000016.10"
    row = {
        "schema": "raptor.external.normalized_functional_row.v1",
        "source_id": source_id,
        "source_row": source_row,
        "source_record_id": f"{source_id}:{source_row}",
        "gene": "TSC2",
        "assembly": "GRCh38",
        "transcript": "NM_000548.5",
        "protein_accession": "ENSP00000219476.3" if source_id == "igvf_vamp_seq" else None,
        "hgvs_c": hgvs_c,
        "hgvs_p": hgvs_p,
        "hgvs_g": hgvs_g,
        "spdi": spdi,
        "variant_kind": "MISSENSE" if len(ref) == 1 else "STOP_GAINED",
        "identity_state": "GENOMIC_SPDI_VERIFIED",
        "unresolved_reason": None,
        "score_name": "score",
        "score_raw": score_raw,
    }
    assert set(row) == {
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
    return row


def _manifest_rows(*, tsc1: int, tsc2: int, pos0_start_tsc1: int, pos0_start_tsc2: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for i in range(tsc1):
        pos0 = pos0_start_tsc1 + i
        rows.append(
            {
                "accession": "NC_000009.12",
                "contig": "chr9",
                "variant_id": f"NC_000009.12:{pos0}:A:G",
                "vcf_key": f"chr9:{pos0 + 1}:A:G",
            }
        )
    for i in range(tsc2):
        pos0 = pos0_start_tsc2 + i
        rows.append(
            {
                "accession": "NC_000016.10",
                "contig": "chr16",
                "variant_id": f"NC_000016.10:{pos0}:C:T",
                "vcf_key": f"chr16:{pos0 + 1}:C:T",
            }
        )
    return rows


def _gene_from_accession(accession: str) -> str:
    if accession == "NC_000009.12":
        return "TSC1"
    if accession == "NC_000016.10":
        return "TSC2"
    return "UNKNOWN"


def _gene_counts_from_manifest(rows: list[dict[str, str]]) -> dict[str, int]:
    out = {"TSC1": 0, "TSC2": 0}
    for row in rows:
        out[_gene_from_accession(row["accession"])] += 1
    return out


def _priority_subset_from_manifest(vus_rows: list[dict[str, str]]) -> list[tuple[str, str]]:
    tsc1 = [row["variant_id"] for row in vus_rows if row["accession"] == "NC_000009.12"][:52]
    tsc2 = [row["variant_id"] for row in vus_rows if row["accession"] == "NC_000016.10"][:112]
    ordered = tsc1 + tsc2
    assert len(ordered) == 164
    return [(spdi, "candidate_LP_review" if i < 157 else "candidate_LB_review") for i, spdi in enumerate(ordered)]


def _priority_queue_rows(subset: list[tuple[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, (spdi, _stratum) in enumerate(subset, start=1):
        gene = "TSC1" if spdi.startswith("NC_000009.12:") else "TSC2"
        rows.append(
            {
                "packet_id": f"packet-{i:03d}",
                "evidence_core_hash": hashlib.sha256(f"packet-{i:03d}".encode("utf-8")).hexdigest(),
                "canonical_spdi": spdi,
                "gene": gene,
                "review_state": "POLICY_BLOCKED",
                "gate_status": "UNVERIFIED",
                "quality_flags": [],
                "contradiction": False,
            }
        )
    return rows


class _ReplayRecord(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc


def _atlas_replay_rows() -> list[_ReplayRecord]:
    rows: list[_ReplayRecord] = []
    for idx in range(1, 26):
        rows.append(
            _ReplayRecord(
                {
                "raw_record_id": f"raw-{idx}",
                "identity_state": "resolved",
                "spdi_canonical": f"NC_000016.10:{900000 + idx}:G:A",
                }
            )
        )
    for idx in range(26, 36):
        rows.append(
            _ReplayRecord(
                {
                "raw_record_id": f"raw-{idx}",
                "identity_state": "unresolved",
                "spdi_canonical": None,
                }
            )
        )
    return rows


def _anchor_payload_nested() -> dict[str, Any]:
    return {
        "schema": "raptor.atlas_public_gate_result.v1",
        "run_id": "r611q-gate1-7-v1",
        "scope": "deterministic_fidelity_only",
        "variant": {
            "spdi": "NC_000016.10:2070570:G:A",
            "hgvs_c": "NM_000548.5:c.1832G>A",
            "hgvs_p": "NP_000539.2:p.Arg611Gln",
        },
        "gate_8": "BLOCKED_HUMAN_REVIEW",
        "accepted_claim_count": 0,
        "promote_candidate_invoked": False,
    }


def _synthetic_functional_promotion_manifest_fixture() -> dict[str, Any]:
    source_rows = {
        "mavedb_clipe": [_promoted_row(source_id="mavedb_clipe", source_row=1, spdi="NC_000016.10:100:A:G", score_raw="0.1")],
        "igvf_vamp_seq": [_promoted_row(source_id="igvf_vamp_seq", source_row=1, spdi="NC_000016.10:100:A:G", score_raw="0.2")],
        "igvf_sge": [_promoted_row(source_id="igvf_sge", source_row=1, spdi="NC_000016.10:200:C:T", score_raw="0.3")],
    }
    payloads = {source: _jsonl_bytes(rows) for source, rows in source_rows.items()}
    artifacts = [
        {
            "artifact_id": "mavedb_clipe-promoted-jsonl",
            "relative_path": "normalized/mavedb_clipe.jsonl",
            "sha256": _sha256(payloads["mavedb_clipe"]),
            "byte_length": len(payloads["mavedb_clipe"]),
            "row_count": 1,
        },
        {
            "artifact_id": "igvf_vamp_seq-promoted-jsonl",
            "relative_path": "normalized/igvf_vamp_seq.jsonl",
            "sha256": _sha256(payloads["igvf_vamp_seq"]),
            "byte_length": len(payloads["igvf_vamp_seq"]),
            "row_count": 1,
        },
        {
            "artifact_id": "igvf_sge-promoted-jsonl",
            "relative_path": "normalized/igvf_sge.jsonl",
            "sha256": _sha256(payloads["igvf_sge"]),
            "byte_length": len(payloads["igvf_sge"]),
            "row_count": 1,
        },
    ]
    manifest = {
        "schema": "raptor.external.tsc2_functional_identity_promotion_bundle.v1",
        "bundle_id": "synthetic-functional-promotion-bundle",
        "content_hash": "",
        "artifacts": artifacts,
        "counts": {"rows": 3, "artifacts": 3},
        "boundaries": {
            "network": "forbidden",
            "clinical_use": "forbidden",
            "evidence_strength_use": "forbidden",
        },
    }
    manifest_for_hash = dict(manifest)
    manifest_for_hash.pop("content_hash", None)
    manifest["content_hash"] = _sha256(_json_bytes(manifest_for_hash))
    expected = {
        "bundle_id": manifest["bundle_id"],
        "manifest_content_hash": manifest["content_hash"],
        "required_identity_state": "GENOMIC_SPDI_VERIFIED",
        "artifacts": {
            "mavedb_clipe": dict(artifacts[0]),
            "igvf_vamp_seq": dict(artifacts[1]),
            "igvf_sge": dict(artifacts[2]),
        },
    }
    return {"manifest": manifest, "expected": expected, "payloads_by_source": payloads}


def _coverage_row(
    *,
    spdi: str,
    source_ids: list[str],
    vus: bool,
    priority: str | None,
    holdout: bool,
    atlas_contrast: bool,
    atlas_anchor: bool,
) -> dict[str, Any]:
    markers: list[str] = []
    if holdout:
        markers.append("PROSPECTIVE_HOLDOUT")
    if atlas_contrast or atlas_anchor:
        markers.append("ATLAS_CONTEXT")
    return {
        "schema": COVERAGE_ROW_SCHEMA,
        "spdi": spdi,
        "source_ids": source_ids,
        "observation_count": len(source_ids),
        "vus_2026_07": vus,
        "priority_stratum": priority,
        "prospective_holdout_2026_08": holdout,
        "atlas_contrast_candidate": atlas_contrast,
        "atlas_anchor_r611q": atlas_anchor,
        "leakage_markers": markers,
    }


def _minimal_manifest_and_payload(bundle_api: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bytes]]:
    rows = [
        _coverage_row(
            spdi="NC_000016.10:2065518:G:A",
            source_ids=["mavedb_clipe", "igvf_vamp_seq"],
            vus=True,
            priority=None,
            holdout=False,
            atlas_contrast=True,
            atlas_anchor=False,
        )
    ]
    payload = bundle_api["canonical_coverage_jsonl_bytes"](rows)
    zero_source_patterns = {key: 0 for key in SOURCE_MEMBERSHIP_PATTERN_KEYS}
    overlap_source_patterns = dict(zero_source_patterns)
    overlap_source_patterns["mavedb_clipe+igvf_vamp_seq"] = 1
    stats = {
        "functional": {
            "verified_observations": 2,
            "unique_spdi": 1,
            "source_unique": {"mavedb_clipe": 1, "igvf_vamp_seq": 1, "igvf_sge": 0},
            "source_membership_patterns": overlap_source_patterns,
        },
        "cohorts": {
            "vus": {
                "identities": 1,
                "TSC1": 0,
                "TSC2": 1,
                "functional_overlap_unique": 1,
                "source_overlap_unique": {"mavedb_clipe": 1, "igvf_vamp_seq": 1, "igvf_sge": 0},
                "source_membership_patterns": overlap_source_patterns,
            },
            "priority": {
                "identities": 0,
                "candidate_LP_review": 0,
                "candidate_LB_review": 0,
                "TSC1": 0,
                "TSC2": 0,
                "functional_overlap_unique": 0,
                "candidate_LP_review_overlap": 0,
                "candidate_LB_review_overlap": 0,
                "source_overlap_unique": {"mavedb_clipe": 0, "igvf_vamp_seq": 0, "igvf_sge": 0},
                "source_membership_patterns": zero_source_patterns,
            },
            "prospective_holdout": {
                "identities": 0,
                "TSC1": 0,
                "TSC2": 0,
                "functional_overlap_unique": 0,
                "source_overlap_unique": {"mavedb_clipe": 0, "igvf_vamp_seq": 0, "igvf_sge": 0},
                "source_membership_patterns": zero_source_patterns,
            },
            "atlas_contrast": {
                "raw_records": 1,
                "resolved_unique_spdi": 1,
                "unresolved_records": 0,
                "functional_overlap_unique": 1,
                "source_overlap_unique": {"mavedb_clipe": 1, "igvf_vamp_seq": 1, "igvf_sge": 0},
                "source_membership_patterns": overlap_source_patterns,
            },
            "atlas_anchor": {
                "identities": 0,
                "functional_overlap_unique": 0,
                "source_overlap_unique": {"mavedb_clipe": 0, "igvf_vamp_seq": 0, "igvf_sge": 0},
                "prospective_holdout_overlap": 0,
            },
        },
        "cross_cohort": {
            "vus__prospective_holdout": 0,
            "priority__prospective_holdout": 0,
            "vus__atlas_contrast": 1,
            "priority__atlas_contrast": 0,
            "prospective_holdout__atlas_contrast": 0,
            "functional__vus__atlas_contrast": 1,
            "functional__prospective_holdout__atlas_contrast": 0,
            "functional__atlas_contrast_outside_vus_holdout": 0,
        },
        "functional_cohort_membership_patterns": {
            "NONE": 0,
            "VUS": 0,
            "VUS+ATLAS_CONTRAST": 1,
            "PROSPECTIVE_HOLDOUT": 0,
            "PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST": 0,
            "PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR": 0,
            "ATLAS_CONTRAST": 0,
        },
        "leakage_markers": {"PROSPECTIVE_HOLDOUT": 0, "ATLAS_CONTEXT": 1, "PROSPECTIVE_HOLDOUT+ATLAS_CONTEXT": 0},
    }
    manifest = bundle_api["build_coverage_bundle_manifest"](
        bundle_id=OUTPUT_BUNDLE_ID,
        created_at="2026-09-14T00:00:00Z",
        input_manifests={
            "functional_identity_promotion": FUNCTIONAL_PROMOTION_MANIFEST_HASH,
            "vus_manifest": REAL_VUS_MANIFEST_PIN["sha256"],
            "prospective_holdout_manifest": REAL_HOLDOUT_MANIFEST_PIN["sha256"],
            "atlas_identity_map": REAL_ATLAS_MAP_PIN["map_content_hash"],
        },
        artifacts=[
            {
                "artifact_id": OUTPUT_ARTIFACT_ID,
                "relative_path": OUTPUT_ARTIFACT_PATH,
                "sha256": _sha256(payload),
                "byte_length": len(payload),
                "row_count": 1,
            }
        ],
        counts={"rows": 1, "artifacts": 1},
        coverage_statistics=stats,
        boundaries=deepcopy(BOUNDARIES),
    )
    return manifest, {OUTPUT_ARTIFACT_PATH: payload}


def _compute_statistics(
    fn: Any,
    *,
    coverage_rows: list[dict[str, Any]],
    full_context: dict[str, Any],
) -> dict[str, Any]:
    sig = inspect.signature(fn)
    if "validated_inputs" in sig.parameters:
        return fn(coverage_rows=coverage_rows, validated_inputs=full_context)
    required = {
        "coverage_rows",
        "vus_spdis",
        "priority_spdis",
        "priority_by_spdi",
        "prospective_holdout_spdis",
        "atlas_contrast_spdis",
        "atlas_anchor_spdi",
        "vus_gene_counts",
        "priority_gene_counts",
        "prospective_holdout_gene_counts",
        "atlas_raw_records",
        "atlas_resolved_count",
        "atlas_unresolved_count",
    }
    missing = required - set(sig.parameters)
    assert not missing, f"compute_coverage_statistics missing required full-context parameters: {sorted(missing)}"
    return fn(coverage_rows=coverage_rows, **full_context)


def _invoke_validate_manifest_content_hash(validate_fn: Any, manifest: dict[str, Any]) -> Any:
    sig = inspect.signature(validate_fn)
    if "manifest" in sig.parameters:
        return validate_fn(manifest=manifest)
    if len(sig.parameters) == 1:
        return validate_fn(manifest)
    raise AssertionError(f"validate_manifest_content_hash unsupported signature: {sig}")


def _assert_nonnegative_int_tree(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _assert_nonnegative_int_tree(child, path=f"{path}.{key}")
        return
    assert isinstance(value, int) and not isinstance(value, bool), f"{path} must be int, got {type(value).__name__}"
    assert value >= 0, f"{path} must be nonnegative"


def _pattern_membership_sum(patterns: dict[str, int], source: str) -> int:
    return sum(count for pattern, count in patterns.items() if source in pattern.split("+"))


def test_fc00_binding_spec_exists_and_is_v1_0_0() -> None:
    spec = _load_spec()
    assert spec["spec_id"] == SPEC_ID
    assert spec["spec_version"] == SPEC_VERSION


def test_fc01_required_implementation_surfaces_exist() -> None:
    required = [MODEL_PATH, INGEST_PATH, COVERAGE_PATH, BUNDLE_PATH, INIT_PATH, OPERATOR_SCRIPT, CONFIG_PATH]
    missing = [path for path in required if not path.exists()]
    assert not missing, "missing required implementation surfaces:\n" + "\n".join(str(path) for path in missing)


def test_fc02_promoted_row_fixture_is_valid_exact_17_field_normalized_row() -> None:
    snv = _promoted_row(source_id="mavedb_clipe", source_row=1, spdi="NC_000016.10:2065518:G:A", score_raw="0.61")
    delins = _promoted_row(source_id="igvf_sge", source_row=2, spdi="NC_000016.10:2065545:CCG:TGA", score_raw="-0.71")
    assert len(snv) == 17
    assert len(delins) == 17
    assert snv["hgvs_g"] == "NC_000016.10:g.2065519G>A"
    assert delins["hgvs_g"] == "NC_000016.10:g.2065546_2065548delinsTGA"
    assert snv["hgvs_c"].startswith("NM_000548.5:c.")
    assert snv["hgvs_p"].startswith("p.")
    assert delins["hgvs_c"].startswith("NM_000548.5:c.")
    assert delins["hgvs_p"].startswith("p.")
    assert "functional_class" not in snv
    assert "functional_class" not in delins


def test_fc03_model_row_contract_is_exact_field_set_order_and_domains() -> None:
    api = _model_api()
    row_ctor = api["FunctionalCoverageRow"]
    err = api["CoverageContractError"]

    assert api["COVERAGE_ROW_SCHEMA"] == COVERAGE_ROW_SCHEMA
    assert list(api["REQUIRED_COVERAGE_ROW_FIELDS"]) == REQUIRED_COVERAGE_ROW_FIELDS
    assert list(api["SOURCE_ORDER"]) == SOURCE_ORDER
    assert list(api["PRIORITY_STRATUM_VALUES"]) == PRIORITY_STRATUM_VALUES
    assert list(api["LEAKAGE_MARKER_ORDER"]) == LEAKAGE_MARKER_ORDER

    valid = row_ctor(
        schema=COVERAGE_ROW_SCHEMA,
        spdi="NC_000016.10:2065518:G:A",
        source_ids=["mavedb_clipe", "igvf_vamp_seq"],
        observation_count=2,
        vus_2026_07=True,
        priority_stratum="candidate_LP_review",
        prospective_holdout_2026_08=False,
        atlas_contrast_candidate=True,
        atlas_anchor_r611q=False,
        leakage_markers=["ATLAS_CONTEXT"],
    )
    assert valid.to_dict() == {
        "schema": COVERAGE_ROW_SCHEMA,
        "spdi": "NC_000016.10:2065518:G:A",
        "source_ids": ["mavedb_clipe", "igvf_vamp_seq"],
        "observation_count": 2,
        "vus_2026_07": True,
        "priority_stratum": "candidate_LP_review",
        "prospective_holdout_2026_08": False,
        "atlas_contrast_candidate": True,
        "atlas_anchor_r611q": False,
        "leakage_markers": ["ATLAS_CONTEXT"],
    }

    invalid_cases: list[dict[str, Any]] = [
        {"spdi": "NC_000016.10:notanumber:G:A"},
        {"spdi": "NC_000017.11:2065518:G:A"},
        {"source_ids": ["mavedb_clipe", "mavedb_clipe"]},
        {"source_ids": ["igvf_sge", "mavedb_clipe"]},
        {"source_ids": ["mavedb_clipe", "unknown_source"]},
        {"observation_count": True},
        {"observation_count": 0},
        {"observation_count": 3},
        {"vus_2026_07": False, "priority_stratum": "candidate_LP_review"},
        {"priority_stratum": "candidate_NOT_REAL"},
        {"prospective_holdout_2026_08": True, "leakage_markers": []},
        {"atlas_contrast_candidate": True, "leakage_markers": []},
        {"atlas_anchor_r611q": True, "leakage_markers": []},
        {"prospective_holdout_2026_08": False, "leakage_markers": ["PROSPECTIVE_HOLDOUT"]},
        {"atlas_contrast_candidate": False, "atlas_anchor_r611q": False, "leakage_markers": ["ATLAS_CONTEXT"]},
        {"prospective_holdout_2026_08": True, "atlas_contrast_candidate": True, "leakage_markers": ["ATLAS_CONTEXT", "PROSPECTIVE_HOLDOUT"]},
        {"vus_2026_07": "true"},
        {"prospective_holdout_2026_08": 1},
        {"atlas_contrast_candidate": "false"},
        {"atlas_anchor_r611q": "false"},
    ]
    for overrides in invalid_cases:
        kwargs = {
            "schema": COVERAGE_ROW_SCHEMA,
            "spdi": "NC_000016.10:2065518:G:A",
            "source_ids": ["mavedb_clipe", "igvf_vamp_seq"],
            "observation_count": 2,
            "vus_2026_07": True,
            "priority_stratum": "candidate_LP_review",
            "prospective_holdout_2026_08": False,
            "atlas_contrast_candidate": True,
            "atlas_anchor_r611q": False,
            "leakage_markers": ["ATLAS_CONTEXT"],
        }
        kwargs.update(overrides)
        with pytest.raises((err, TypeError, ValueError)):
            row_ctor(**kwargs)

    with pytest.raises((err, TypeError, ValueError)):
        row_ctor(
            schema=COVERAGE_ROW_SCHEMA,
            spdi="NC_000016.10:2065518:G:A",
            source_ids=["mavedb_clipe"],
            observation_count=1,
            vus_2026_07=False,
            priority_stratum=None,
            prospective_holdout_2026_08=False,
            atlas_contrast_candidate=False,
            atlas_anchor_r611q=False,
            leakage_markers=[],
            score_raw="-1.0",
        )
    with pytest.raises((err, TypeError, ValueError)):
        row_ctor(
            schema=COVERAGE_ROW_SCHEMA,
            spdi="NC_000016.10:2065518:G:A",
            source_ids=["mavedb_clipe"],
            observation_count=1,
            vus_2026_07=False,
            priority_stratum=None,
            prospective_holdout_2026_08=False,
            atlas_contrast_candidate=False,
            atlas_anchor_r611q=False,
            leakage_markers=[],
            classification="VUS",
        )


def test_fc04_ingest_exposes_raw_byte_pinning_surfaces_for_vus_holdout_and_priority() -> None:
    api = _ingest_api()

    vus_sig = inspect.signature(api["validate_vus_inputs"])
    assert {"manifest_payload", "provenance_payload", "bias_payload"}.issubset(vus_sig.parameters), vus_sig

    holdout_sig = inspect.signature(api["validate_prospective_holdout_inputs"])
    assert {"manifest_payload", "provenance_payload"}.issubset(holdout_sig.parameters), holdout_sig

    priority_sig = inspect.signature(api["reproduce_priority_subset"])
    assert {"queue_payload", "aggregate_manifest_payload"}.issubset(priority_sig.parameters), priority_sig


def test_fc04b_validate_input_roots_absolute_for_every_input_and_reject_before_reader(tmp_path: Path) -> None:
    api = _ingest_api()
    err = api["CoverageInputError"]
    validator = api["validate_input_roots_absolute"]
    sig = inspect.signature(validator)
    required = {
        "functional_promotion_root",
        "vus_identity_root",
        "vus_bias_root",
        "priority_queue_root",
        "prospective_holdout_root",
        "atlas_identity_map_root",
        "atlas_panel_root",
    }
    assert required.issubset(sig.parameters), sig

    absolute_roots = {
        "functional_promotion_root": (tmp_path / "functional-root").resolve(),
        "vus_identity_root": (tmp_path / "vus-identity-root").resolve(),
        "vus_bias_root": (tmp_path / "vus-bias-root").resolve(),
        "priority_queue_root": (tmp_path / "priority-root").resolve(),
        "prospective_holdout_root": (tmp_path / "holdout-root").resolve(),
        "atlas_identity_map_root": (tmp_path / "atlas-map-root").resolve(),
        "atlas_panel_root": (tmp_path / "atlas-panel-root").resolve(),
    }
    if "output_root" in sig.parameters:
        absolute_roots["output_root"] = (tmp_path / "output-root").resolve()
    for path in absolute_roots.values():
        path.mkdir(parents=True, exist_ok=True)
    validator(**absolute_roots)

    reader_called = {"value": False}

    def _fail_if_called(*_args: Any, **_kwargs: Any) -> None:
        reader_called["value"] = True
        raise AssertionError("reader must not be invoked for relative-root rejection")

    for key in required:
        kwargs = dict(absolute_roots)
        kwargs[key] = Path("relative-not-allowed")
        if "reader_probe_fn" in sig.parameters:
            kwargs["reader_probe_fn"] = _fail_if_called
        with pytest.raises(err):
            validator(**kwargs)
        assert reader_called["value"] is False


def test_fc04c_functional_promotion_manifest_exact_pins_and_raw_artifact_payload_validation(
    tmp_path: Path,
) -> None:
    api = _ingest_api()
    err = api["InputPinMismatchError"]
    coverage_err = api["CoverageInputError"]
    fixture = _synthetic_functional_promotion_manifest_fixture()

    validated = api["validate_functional_promotion_manifest"](
        promotion_manifest=deepcopy(fixture["manifest"]),
        expected_pins=deepcopy(fixture["expected"]),
    )
    assert validated["artifacts"]["mavedb_clipe"]["artifact_id"] == "mavedb_clipe-promoted-jsonl"

    drifted = deepcopy(fixture["manifest"])
    drifted["content_hash"] = "0" * 64
    with pytest.raises(err):
        api["validate_functional_promotion_manifest"](
            promotion_manifest=drifted,
            expected_pins=deepcopy(fixture["expected"]),
        )

    unknown_artifact = deepcopy(fixture["manifest"])
    unknown_artifact["artifacts"][0]["artifact_id"] = "not-a-pinned-artifact-id"
    with pytest.raises(err):
        api["validate_functional_promotion_manifest"](
            promotion_manifest=unknown_artifact,
            expected_pins=deepcopy(fixture["expected"]),
        )

    duplicate = deepcopy(fixture["manifest"])
    duplicate["artifacts"].append(deepcopy(duplicate["artifacts"][0]))
    with pytest.raises(err):
        api["validate_functional_promotion_manifest"](
            promotion_manifest=duplicate,
            expected_pins=deepcopy(fixture["expected"]),
        )

    missing_artifact = deepcopy(fixture["manifest"])
    missing_artifact["artifacts"] = missing_artifact["artifacts"][:-1]
    missing_artifact["counts"]["artifacts"] = 2
    with pytest.raises(err):
        api["validate_functional_promotion_manifest"](
            promotion_manifest=missing_artifact,
            expected_pins=deepcopy(fixture["expected"]),
        )

    read_sig = inspect.signature(api["read_input_payload"])
    assert {"expected_sha256", "expected_byte_length"}.issubset(read_sig.parameters), read_sig
    payload = fixture["payloads_by_source"]["mavedb_clipe"]
    root = tmp_path / "input-root"
    run_name = "synthetic-functional-promotion-run"
    relpath = "normalized/mavedb_clipe.jsonl"
    file_path = root / run_name / relpath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(payload)
    payload_out = api["read_input_payload"](
        root=root,
        run_name=run_name,
        relative_path=relpath,
        label="functional_promotion_artifact",
        expected_sha256=_sha256(payload),
        expected_byte_length=len(payload),
    )
    assert payload_out == payload

    with pytest.raises((err, coverage_err)):
        api["read_input_payload"](
            root=root,
            run_name=run_name,
            relative_path=relpath,
            label="functional_promotion_artifact",
            expected_sha256="0" * 64,
            expected_byte_length=len(payload),
        )


def test_fc04d_operator_validates_input_roots_before_any_reader_calls() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 functional coverage operator script is missing: {OPERATOR_SCRIPT}")
    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    main_node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if main_node is None:
        pytest.fail("operator script must define main(argv=...)")

    first_seen: dict[str, int] = {}
    for node in ast.walk(main_node):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            continue
        first_seen.setdefault(name, node.lineno)

    assert "validate_input_roots_absolute" in first_seen
    assert "read_input_payload" in first_seen
    assert first_seen["validate_input_roots_absolute"] < first_seen["read_input_payload"]


def test_fc05_promoted_rows_are_revalidated_and_score_raw_mutation_does_not_change_coverage_rows() -> None:
    ingest_api = _ingest_api()
    coverage_api = _coverage_api()
    read_input_payload = ingest_api["read_input_payload"]
    ingest_err = ingest_api["CoverageInputError"]

    rows = [
        _promoted_row(source_id="mavedb_clipe", source_row=1, spdi="NC_000016.10:2065518:G:A", score_raw="0.1"),
        _promoted_row(source_id="igvf_vamp_seq", source_row=1, spdi="NC_000016.10:2065518:G:A", score_raw="-1.2"),
        _promoted_row(source_id="igvf_sge", source_row=1, spdi="NC_000016.10:2065545:CCG:TGA", score_raw="4.2"),
    ]
    validated = ingest_api["validate_promoted_functional_rows"](
        promoted_rows=deepcopy(rows),
        required_identity_state="GENOMIC_SPDI_VERIFIED",
        expected_source_rows={"mavedb_clipe": 1, "igvf_vamp_seq": 1, "igvf_sge": 1},
        source_order=SOURCE_ORDER,
    )
    assert len(validated) == 3

    # Raw artifact bytes are pinned by hash+length before parse.
    payload = _jsonl_bytes([rows[0]])
    payload_pin = {"sha256": _sha256(payload), "byte_length": len(payload)}
    sig = inspect.signature(read_input_payload)
    required = {"root", "run_name", "relative_path", "label"}
    assert required.issubset(sig.parameters), sig
    assert {"expected_sha256", "expected_byte_length"}.issubset(sig.parameters), sig

    # Logical read test without filesystem dependency: use injected raw bytes if supported.
    read_kwargs = {
        "root": REPO_ROOT,
        "run_name": "synthetic-run",
        "relative_path": "synthetic/path.jsonl",
        "label": "functional_promotion_artifact",
        "expected_sha256": payload_pin["sha256"],
        "expected_byte_length": payload_pin["byte_length"],
    }
    if "payload_override" in sig.parameters:
        assert read_input_payload(payload_override=payload, **read_kwargs) == payload
        with pytest.raises((ingest_api["InputPinMismatchError"], ingest_err)):
            read_input_payload(payload_override=_flip_first_byte(payload), **read_kwargs)

    # Promoted-row validation negatives.
    duplicate_source_row = deepcopy(rows)
    duplicate_source_row.append(deepcopy(rows[0]))
    with pytest.raises(ingest_err):
        ingest_api["validate_promoted_functional_rows"](
            promoted_rows=duplicate_source_row,
            required_identity_state="GENOMIC_SPDI_VERIFIED",
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 1, "igvf_sge": 1},
            source_order=SOURCE_ORDER,
        )

    wrong_source = deepcopy(rows)
    wrong_source[0]["source_id"] = "unknown_source"
    with pytest.raises(ingest_err):
        ingest_api["validate_promoted_functional_rows"](
            promoted_rows=wrong_source,
            required_identity_state="GENOMIC_SPDI_VERIFIED",
            expected_source_rows={"mavedb_clipe": 0, "igvf_vamp_seq": 1, "igvf_sge": 1},
            source_order=SOURCE_ORDER,
        )

    wrong_state = deepcopy(rows)
    wrong_state[1]["identity_state"] = "GENOMIC_REFERENCE_MISMATCH"
    with pytest.raises(ingest_err):
        ingest_api["validate_promoted_functional_rows"](
            promoted_rows=wrong_state,
            required_identity_state="GENOMIC_SPDI_VERIFIED",
            expected_source_rows={"mavedb_clipe": 1, "igvf_vamp_seq": 1, "igvf_sge": 1},
            source_order=SOURCE_ORDER,
        )

    bad_accession = deepcopy(rows)
    bad_accession[0]["spdi"] = "NC_000017.11:2065518:G:A"
    with pytest.raises(ingest_err):
        ingest_api["validate_promoted_functional_rows"](
            promoted_rows=bad_accession,
            required_identity_state="GENOMIC_SPDI_VERIFIED",
            expected_source_rows={"mavedb_clipe": 1, "igvf_vamp_seq": 1, "igvf_sge": 1},
            source_order=SOURCE_ORDER,
        )

    noncanonical = deepcopy(rows)
    noncanonical[0]["spdi"] = "NC_000016.10:2065518:G:AA"
    with pytest.raises(ingest_err):
        ingest_api["validate_promoted_functional_rows"](
            promoted_rows=noncanonical,
            required_identity_state="GENOMIC_SPDI_VERIFIED",
            expected_source_rows={"mavedb_clipe": 1, "igvf_vamp_seq": 1, "igvf_sge": 1},
            source_order=SOURCE_ORDER,
        )

    unequal_length = deepcopy(rows)
    unequal_length[0]["spdi"] = "NC_000016.10:2065518:GG:A"
    with pytest.raises(ingest_err):
        ingest_api["validate_promoted_functional_rows"](
            promoted_rows=unequal_length,
            required_identity_state="GENOMIC_SPDI_VERIFIED",
            expected_source_rows={"mavedb_clipe": 1, "igvf_vamp_seq": 1, "igvf_sge": 1},
            source_order=SOURCE_ORDER,
        )

    source_count_mismatch = deepcopy(rows)
    with pytest.raises(ingest_err):
        ingest_api["validate_promoted_functional_rows"](
            promoted_rows=source_count_mismatch,
            required_identity_state="GENOMIC_SPDI_VERIFIED",
            expected_source_rows={"mavedb_clipe": 2, "igvf_vamp_seq": 1, "igvf_sge": 1},
            source_order=SOURCE_ORDER,
        )

    baseline = coverage_api["build_functional_coverage_rows"](
        functional_rows=deepcopy(rows),
        vus_spdis={"NC_000016.10:2065518:G:A"},
        priority_by_spdi={"NC_000016.10:2065518:G:A": "candidate_LP_review"},
        prospective_holdout_spdis={"NC_000016.10:2065545:CCG:TGA"},
        atlas_contrast_spdis={"NC_000016.10:2065518:G:A"},
        atlas_anchor_spdi="NC_000016.10:2065545:CCG:TGA",
        source_order=SOURCE_ORDER,
        leakage_marker_order=LEAKAGE_MARKER_ORDER,
    )

    score_mutated = deepcopy(rows)
    score_mutated[0]["score_raw"] = "-9999"
    score_mutated[1]["score_raw"] = "9999"
    score_mutated[2]["score_raw"] = "0"
    mutated = coverage_api["build_functional_coverage_rows"](
        functional_rows=score_mutated,
        vus_spdis={"NC_000016.10:2065518:G:A"},
        priority_by_spdi={"NC_000016.10:2065518:G:A": "candidate_LP_review"},
        prospective_holdout_spdis={"NC_000016.10:2065545:CCG:TGA"},
        atlas_contrast_spdis={"NC_000016.10:2065518:G:A"},
        atlas_anchor_spdi="NC_000016.10:2065545:CCG:TGA",
        source_order=SOURCE_ORDER,
        leakage_marker_order=LEAKAGE_MARKER_ORDER,
    )
    assert baseline == mutated
    assert "functional_class" not in json.dumps(baseline, sort_keys=True)


def test_fc06_vus_validation_uses_raw_byte_pins_and_enforces_schema_duplicate_identity_and_duplicate_vcf_key() -> None:
    api = _ingest_api()
    err = api["CoverageInputError"]

    rows = _manifest_rows(tsc1=2249, tsc2=4369, pos0_start_tsc1=100000, pos0_start_tsc2=200000)
    manifest_payload = _jsonl_bytes(rows)
    provenance_payload = _json_bytes(
        {
            "conservation_count": 6618,
            "corpus_kind": "clinvar_vus_internal_evidence_census",
            "authorization": "internal_non_authoritative_evidence_only",
            "source_snapshot": "clinvar_2026-07-07",
            "manifest_hash": _sha256(manifest_payload),
            "identity_file_sha256": "synthetic-identity-sha",
            "vcf_hash": "synthetic-vcf-hash",
        }
    )
    bias_rows = [[row["variant_id"], "unused"] for row in rows]
    bias_payload = _tsv_bytes(["variant_id", "acmgClassification"], bias_rows)

    expected_manifest = _pin_from_payload(
        payload=manifest_payload,
        relative_path="synthetic_vus.manifest.jsonl",
        row_count=6618,
        required_fields=["accession", "contig", "variant_id", "vcf_key"],
    )
    expected_provenance = _pin_from_payload(
        payload=provenance_payload,
        relative_path="synthetic_vus.provenance.json",
        row_count=1,
        required_values=json.loads(provenance_payload.decode("utf-8")),
    )
    expected_bias = _pin_from_payload(
        payload=bias_payload,
        relative_path="synthetic_vus.bias.tsv",
        row_count=6618,
    )

    result = api["validate_vus_inputs"](
        manifest_payload=manifest_payload,
        provenance_payload=provenance_payload,
        bias_payload=bias_payload,
        expected_manifest_pin=expected_manifest,
        expected_provenance_pin=expected_provenance,
        expected_bias_pin=expected_bias,
        expected_gene_counts={"TSC1": 2249, "TSC2": 4369},
    )
    assert result["identity_count"] == 6618
    assert result["gene_counts"] == {"TSC1": 2249, "TSC2": 4369}

    with pytest.raises(err):
        api["validate_vus_inputs"](
            manifest_payload=_flip_first_byte(manifest_payload),
            provenance_payload=provenance_payload,
            bias_payload=bias_payload,
            expected_manifest_pin=expected_manifest,
            expected_provenance_pin=expected_provenance,
            expected_bias_pin=expected_bias,
            expected_gene_counts={"TSC1": 2249, "TSC2": 4369},
        )

    drifted_pin = deepcopy(expected_manifest)
    drifted_pin["byte_length"] += 1
    with pytest.raises(err):
        api["validate_vus_inputs"](
            manifest_payload=manifest_payload,
            provenance_payload=provenance_payload,
            bias_payload=bias_payload,
            expected_manifest_pin=drifted_pin,
            expected_provenance_pin=expected_provenance,
            expected_bias_pin=expected_bias,
            expected_gene_counts={"TSC1": 2249, "TSC2": 4369},
        )

    dup_identity = deepcopy(rows)
    dup_identity.append(deepcopy(dup_identity[0]))
    with pytest.raises(err):
        api["validate_vus_inputs"](
            manifest_payload=_jsonl_bytes(dup_identity),
            provenance_payload=provenance_payload,
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in dup_identity]),
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(dup_identity),
                relative_path="dup_identity.jsonl",
                row_count=len(dup_identity),
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=expected_provenance,
            expected_bias_pin=_pin_from_payload(
                payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in dup_identity]),
                relative_path="dup_identity.tsv",
                row_count=len(dup_identity),
            ),
            expected_gene_counts={"TSC1": 2250, "TSC2": 4369},
        )

    dup_vcf = deepcopy(rows)
    dup_vcf[1]["vcf_key"] = dup_vcf[0]["vcf_key"]
    with pytest.raises(err):
        api["validate_vus_inputs"](
            manifest_payload=_jsonl_bytes(dup_vcf),
            provenance_payload=provenance_payload,
            bias_payload=bias_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(dup_vcf),
                relative_path="dup_vcf.jsonl",
                row_count=len(dup_vcf),
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=expected_provenance,
            expected_bias_pin=expected_bias,
            expected_gene_counts={"TSC1": 2249, "TSC2": 4369},
        )

    contig_mismatch = deepcopy(rows)
    contig_mismatch[0]["contig"] = "chr16"
    with pytest.raises(err):
        api["validate_vus_inputs"](
            manifest_payload=_jsonl_bytes(contig_mismatch),
            provenance_payload=provenance_payload,
            bias_payload=bias_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(contig_mismatch),
                relative_path="contig_mismatch.jsonl",
                row_count=len(contig_mismatch),
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=expected_provenance,
            expected_bias_pin=expected_bias,
            expected_gene_counts={"TSC1": 2249, "TSC2": 4369},
        )

    variant_id_mismatch = deepcopy(rows)
    variant_id_mismatch[0]["variant_id"] = "NC_000009.12:100000:A:T"
    with pytest.raises(err):
        api["validate_vus_inputs"](
            manifest_payload=_jsonl_bytes(variant_id_mismatch),
            provenance_payload=provenance_payload,
            bias_payload=bias_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(variant_id_mismatch),
                relative_path="variant_id_mismatch.jsonl",
                row_count=len(variant_id_mismatch),
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=expected_provenance,
            expected_bias_pin=expected_bias,
            expected_gene_counts={"TSC1": 2249, "TSC2": 4369},
        )

    vcf_pos_mismatch = deepcopy(rows)
    vcf_pos_mismatch[0]["vcf_key"] = "chr9:100000:A:G"
    with pytest.raises(err):
        api["validate_vus_inputs"](
            manifest_payload=_jsonl_bytes(vcf_pos_mismatch),
            provenance_payload=provenance_payload,
            bias_payload=bias_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(vcf_pos_mismatch),
                relative_path="vcf_pos_mismatch.jsonl",
                row_count=len(vcf_pos_mismatch),
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=expected_provenance,
            expected_bias_pin=expected_bias,
            expected_gene_counts={"TSC1": 2249, "TSC2": 4369},
        )


def test_fc07_priority_subset_raw_pins_queue_contract_and_exact_set_equality() -> None:
    api = _ingest_api()
    err = api["CoverageInputError"]

    vus_rows = _manifest_rows(tsc1=2249, tsc2=4369, pos0_start_tsc1=100000, pos0_start_tsc2=200000)
    subset = _priority_subset_from_manifest(vus_rows)
    queue_rows = _priority_queue_rows(subset)
    queue_payload = _jsonl_bytes(queue_rows)
    aggregate_payload = _json_bytes(
        {
            "universe_size": 6618,
            "conservation": {
                "manifest_identities": 6618,
                "bias_rows": 6618,
                "candidate_LP_review": 157,
                "candidate_LB_review": 7,
                "no_deterministic_resolution": 6424,
                "manual_review": 30,
            },
            "source_hashes": {
                "manifest_sha256": "synthetic-manifest-sha",
                "bias_tsv_sha256": "synthetic-bias-sha",
                "input_vcf_sha256": "synthetic-vcf-sha",
            },
            "run_pins": {"code_commit": "synthetic", "source_snapshot": "clinvar_2026-07-07"},
        }
    )
    def _queue_pin(payload: bytes, *, relative_path: str, row_count: int) -> dict[str, Any]:
        pin = _pin_from_payload(payload=payload, relative_path=relative_path, row_count=row_count)
        pin["exact_fields"] = list(REAL_PRIORITY_QUEUE_PIN["exact_fields"])
        pin["required_review_state"] = "POLICY_BLOCKED"
        pin["required_gate_status"] = "UNVERIFIED"
        return pin

    queue_pin = _queue_pin(queue_payload, relative_path="priority_queue.jsonl", row_count=164)
    aggregate_pin = _pin_from_payload(payload=aggregate_payload, relative_path="aggregate_manifest.json", row_count=1)
    aggregate_pin["required_values"] = json.loads(aggregate_payload.decode("utf-8"))

    def _reproduce_fn(**kwargs: Any) -> list[dict[str, Any]]:
        manifest_rows = kwargs.get("manifest_rows") or kwargs.get("vus_manifest_rows")
        if manifest_rows is None:
            raise AssertionError("reproduce_census_strata_fn must receive manifest rows")
        lookup = {spdi: stratum for spdi, stratum in subset}
        out: list[dict[str, Any]] = []
        for item in manifest_rows:
            out.append({"variant_id": item["variant_id"], "stratum": lookup.get(item["variant_id"], "no_deterministic_resolution")})
        return out

    result = api["reproduce_priority_subset"](
        vus_manifest_payload=_jsonl_bytes(vus_rows),
        bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
        aggregate_manifest_payload=aggregate_payload,
        queue_payload=queue_payload,
        expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
        queue_pin=queue_pin,
        aggregate_manifest_pin=aggregate_pin,
        predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
        scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
        eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
        lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
        packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
        reproduce_census_strata_fn=_reproduce_fn,
    )
    assert result["identity_count"] == 164
    assert result["stratum_counts"] == {"candidate_LP_review": 157, "candidate_LB_review": 7}
    assert result["gene_counts"] == {"TSC1": 52, "TSC2": 112}

    queue_drift = deepcopy(queue_rows)
    queue_drift[0]["canonical_spdi"] = "NC_000016.10:999999:G:A"
    with pytest.raises(err):
        api["reproduce_priority_subset"](
            vus_manifest_payload=_jsonl_bytes(vus_rows),
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
            aggregate_manifest_payload=aggregate_payload,
            queue_payload=_jsonl_bytes(queue_drift),
            expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
            queue_pin=_queue_pin(_jsonl_bytes(queue_drift), relative_path="queue_drift.jsonl", row_count=164),
            aggregate_manifest_pin=aggregate_pin,
            predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
            scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
            eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
            lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
            packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
            reproduce_census_strata_fn=_reproduce_fn,
        )

    duplicate_queue = deepcopy(queue_rows)
    duplicate_queue.append(deepcopy(duplicate_queue[-1]))
    with pytest.raises(err):
        api["reproduce_priority_subset"](
            vus_manifest_payload=_jsonl_bytes(vus_rows),
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
            aggregate_manifest_payload=aggregate_payload,
            queue_payload=_jsonl_bytes(duplicate_queue),
            expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
            queue_pin=_queue_pin(_jsonl_bytes(duplicate_queue), relative_path="queue_dup.jsonl", row_count=165),
            aggregate_manifest_pin=aggregate_pin,
            predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
            scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
            eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
            lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
            packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
            reproduce_census_strata_fn=_reproduce_fn,
        )

    malformed_spdi = deepcopy(queue_rows)
    malformed_spdi[0]["canonical_spdi"] = "NC_000016.10:200000:N:T"
    with pytest.raises(err):
        api["reproduce_priority_subset"](
            vus_manifest_payload=_jsonl_bytes(vus_rows),
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
            aggregate_manifest_payload=aggregate_payload,
            queue_payload=_jsonl_bytes(malformed_spdi),
            expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
            queue_pin=_queue_pin(_jsonl_bytes(malformed_spdi), relative_path="queue_malformed_spdi.jsonl", row_count=164),
            aggregate_manifest_pin=aggregate_pin,
            predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
            scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
            eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
            lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
            packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
            reproduce_census_strata_fn=_reproduce_fn,
        )

    wrong_gene = deepcopy(queue_rows)
    wrong_gene[0]["gene"] = "TSC2" if wrong_gene[0]["canonical_spdi"].startswith("NC_000009.12:") else "TSC1"
    with pytest.raises(err):
        api["reproduce_priority_subset"](
            vus_manifest_payload=_jsonl_bytes(vus_rows),
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
            aggregate_manifest_payload=aggregate_payload,
            queue_payload=_jsonl_bytes(wrong_gene),
            expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
            queue_pin=_queue_pin(_jsonl_bytes(wrong_gene), relative_path="queue_wrong_gene.jsonl", row_count=164),
            aggregate_manifest_pin=aggregate_pin,
            predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
            scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
            eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
            lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
            packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
            reproduce_census_strata_fn=_reproduce_fn,
        )

    duplicate_packet_id = deepcopy(queue_rows)
    duplicate_packet_id[1]["packet_id"] = duplicate_packet_id[0]["packet_id"]
    with pytest.raises(err):
        api["reproduce_priority_subset"](
            vus_manifest_payload=_jsonl_bytes(vus_rows),
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
            aggregate_manifest_payload=aggregate_payload,
            queue_payload=_jsonl_bytes(duplicate_packet_id),
            expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
            queue_pin=_queue_pin(_jsonl_bytes(duplicate_packet_id), relative_path="queue_dup_packet_id.jsonl", row_count=164),
            aggregate_manifest_pin=aggregate_pin,
            predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
            scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
            eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
            lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
            packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
            reproduce_census_strata_fn=_reproduce_fn,
        )

    duplicate_evidence_hash = deepcopy(queue_rows)
    duplicate_evidence_hash[1]["evidence_core_hash"] = duplicate_evidence_hash[0]["evidence_core_hash"]
    with pytest.raises(err):
        api["reproduce_priority_subset"](
            vus_manifest_payload=_jsonl_bytes(vus_rows),
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
            aggregate_manifest_payload=aggregate_payload,
            queue_payload=_jsonl_bytes(duplicate_evidence_hash),
            expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
            queue_pin=_queue_pin(_jsonl_bytes(duplicate_evidence_hash), relative_path="queue_dup_evidence_hash.jsonl", row_count=164),
            aggregate_manifest_pin=aggregate_pin,
            predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
            scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
            eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
            lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
            packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
            reproduce_census_strata_fn=_reproduce_fn,
        )

    contradiction_not_bool = deepcopy(queue_rows)
    contradiction_not_bool[0]["contradiction"] = 1
    with pytest.raises(err):
        api["reproduce_priority_subset"](
            vus_manifest_payload=_jsonl_bytes(vus_rows),
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
            aggregate_manifest_payload=aggregate_payload,
            queue_payload=_jsonl_bytes(contradiction_not_bool),
            expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
            queue_pin=_queue_pin(_jsonl_bytes(contradiction_not_bool), relative_path="queue_contradiction_not_bool.jsonl", row_count=164),
            aggregate_manifest_pin=aggregate_pin,
            predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
            scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
            eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
            lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
            packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
            reproduce_census_strata_fn=_reproduce_fn,
        )

    quality_flags_not_list = deepcopy(queue_rows)
    quality_flags_not_list[0]["quality_flags"] = "NEEDS_REVIEW"
    with pytest.raises(err):
        api["reproduce_priority_subset"](
            vus_manifest_payload=_jsonl_bytes(vus_rows),
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
            aggregate_manifest_payload=aggregate_payload,
            queue_payload=_jsonl_bytes(quality_flags_not_list),
            expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
            queue_pin=_queue_pin(_jsonl_bytes(quality_flags_not_list), relative_path="queue_quality_flags_not_list.jsonl", row_count=164),
            aggregate_manifest_pin=aggregate_pin,
            predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
            scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
            eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
            lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
            packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
            reproduce_census_strata_fn=_reproduce_fn,
        )

    quality_flags_non_string = deepcopy(queue_rows)
    quality_flags_non_string[0]["quality_flags"] = ["ok", 123]
    with pytest.raises(err):
        api["reproduce_priority_subset"](
            vus_manifest_payload=_jsonl_bytes(vus_rows),
            bias_payload=_tsv_bytes(["variant_id", "acmgClassification"], [[r["variant_id"], "unused"] for r in vus_rows]),
            aggregate_manifest_payload=aggregate_payload,
            queue_payload=_jsonl_bytes(quality_flags_non_string),
            expected={"candidate_LP_review": 157, "candidate_LB_review": 7, "total": 164, "gene_counts": {"TSC1": 52, "TSC2": 112}},
            queue_pin=_queue_pin(_jsonl_bytes(quality_flags_non_string), relative_path="queue_quality_flags_non_string.jsonl", row_count=164),
            aggregate_manifest_pin=aggregate_pin,
            predictor_policy={"schema": "bp4pp3-predictor-policy/2", "status": "approved", "mode": "disabled_manual"},
            scorer_config_pin={"path": "synthetic/scorer", "raw_sha256": "a" * 64},
            eval_config_pin={"path": "synthetic/eval", "raw_sha256": "b" * 64},
            lineage_policy_pin={"path": "synthetic/lineage", "raw_sha256": "c" * 64},
            packet_policy_pin={"path": "synthetic/packet", "raw_sha256": "d" * 64},
            reproduce_census_strata_fn=_reproduce_fn,
        )


def test_fc08_holdout_validation_uses_raw_byte_pins_enforces_schema_and_blocks_labeled_artifacts() -> None:
    api = _ingest_api()
    err = api["CoverageInputError"]

    rows = _manifest_rows(tsc1=718, tsc2=1890, pos0_start_tsc1=500000, pos0_start_tsc2=700000)
    manifest_payload = _jsonl_bytes(rows)
    provenance_payload = _json_bytes(
        {
            "archive_sha256": "synthetic-archive-hash",
            "benchmark_snapshot": "clinvar_2026-08-monthly-amendment-v3",
            "conservation_count": 2608,
            "manifest_hash": _sha256(manifest_payload),
            "vcf_hash": "synthetic-vcf",
        }
    )
    manifest_pin = _pin_from_payload(
        payload=manifest_payload,
        relative_path="synthetic_holdout.manifest.jsonl",
        row_count=2608,
        required_fields=["accession", "contig", "variant_id", "vcf_key"],
    )
    provenance_pin = _pin_from_payload(
        payload=provenance_payload,
        relative_path="synthetic_holdout.provenance.json",
        row_count=1,
        required_values=json.loads(provenance_payload.decode("utf-8")),
    )

    validated = api["validate_prospective_holdout_inputs"](
        manifest_payload=manifest_payload,
        provenance_payload=provenance_payload,
        expected_manifest_pin=manifest_pin,
        expected_provenance_pin=provenance_pin,
        expected_gene_counts={"TSC1": 718, "TSC2": 1890},
        forbidden_reads=["benchmark.jsonl", "train_dev.jsonl", "holdout.jsonl", "terminal_eval.json", "prospective_evidence.json"],
    )
    assert validated["identity_count"] == 2608
    assert validated["gene_counts"] == {"TSC1": 718, "TSC2": 1890}

    with_label = deepcopy(rows)
    with_label[0]["classification"] = "VUS"
    with pytest.raises(err):
        api["validate_prospective_holdout_inputs"](
            manifest_payload=_jsonl_bytes(with_label),
            provenance_payload=provenance_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(with_label),
                relative_path="with_label.jsonl",
                row_count=2608,
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=provenance_pin,
            expected_gene_counts={"TSC1": 718, "TSC2": 1890},
            forbidden_reads=["benchmark.jsonl"],
        )

    dup_identity = deepcopy(rows)
    dup_identity.append(deepcopy(dup_identity[0]))
    with pytest.raises(err):
        api["validate_prospective_holdout_inputs"](
            manifest_payload=_jsonl_bytes(dup_identity),
            provenance_payload=provenance_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(dup_identity),
                relative_path="dup_identity_holdout.jsonl",
                row_count=2609,
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=provenance_pin,
            expected_gene_counts={"TSC1": 719, "TSC2": 1890},
            forbidden_reads=["benchmark.jsonl"],
        )

    dup_vcf = deepcopy(rows)
    dup_vcf[1]["vcf_key"] = dup_vcf[0]["vcf_key"]
    with pytest.raises(err):
        api["validate_prospective_holdout_inputs"](
            manifest_payload=_jsonl_bytes(dup_vcf),
            provenance_payload=provenance_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(dup_vcf),
                relative_path="dup_vcf_holdout.jsonl",
                row_count=2608,
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=provenance_pin,
            expected_gene_counts={"TSC1": 718, "TSC2": 1890},
            forbidden_reads=["benchmark.jsonl"],
        )

    contig_mismatch = deepcopy(rows)
    contig_mismatch[0]["contig"] = "chr16"
    with pytest.raises(err):
        api["validate_prospective_holdout_inputs"](
            manifest_payload=_jsonl_bytes(contig_mismatch),
            provenance_payload=provenance_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(contig_mismatch),
                relative_path="holdout_contig_mismatch.jsonl",
                row_count=len(contig_mismatch),
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=provenance_pin,
            expected_gene_counts={"TSC1": 718, "TSC2": 1890},
            forbidden_reads=["benchmark.jsonl"],
        )

    variant_id_mismatch = deepcopy(rows)
    variant_id_mismatch[0]["variant_id"] = "NC_000009.12:500000:A:T"
    with pytest.raises(err):
        api["validate_prospective_holdout_inputs"](
            manifest_payload=_jsonl_bytes(variant_id_mismatch),
            provenance_payload=provenance_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(variant_id_mismatch),
                relative_path="holdout_variant_id_mismatch.jsonl",
                row_count=len(variant_id_mismatch),
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=provenance_pin,
            expected_gene_counts={"TSC1": 718, "TSC2": 1890},
            forbidden_reads=["benchmark.jsonl"],
        )

    vcf_pos_mismatch = deepcopy(rows)
    vcf_pos_mismatch[0]["vcf_key"] = "chr9:500000:A:G"
    with pytest.raises(err):
        api["validate_prospective_holdout_inputs"](
            manifest_payload=_jsonl_bytes(vcf_pos_mismatch),
            provenance_payload=provenance_payload,
            expected_manifest_pin=_pin_from_payload(
                payload=_jsonl_bytes(vcf_pos_mismatch),
                relative_path="holdout_vcf_pos_mismatch.jsonl",
                row_count=len(vcf_pos_mismatch),
                required_fields=["accession", "contig", "variant_id", "vcf_key"],
            ),
            expected_provenance_pin=provenance_pin,
            expected_gene_counts={"TSC1": 718, "TSC2": 1890},
            forbidden_reads=["benchmark.jsonl"],
        )


def test_fc09_atlas_contrast_loader_must_call_public_load_identity_map_seam_and_replay_inventory() -> None:
    api = _ingest_api()
    err = api["CoverageInputError"]
    sig = inspect.signature(api["load_atlas_contrast_replays"])
    required_params = {
        "map_payload",
        "lock_payload",
        "raw_inventory_payload",
        "response_bundle_observed",
        "expected_map_pin",
        "expected_lock_pin",
        "expected_raw_inventory_pin",
        "expected_response_bundle_pin",
    }
    assert required_params.issubset(sig.parameters), sig

    called: dict[str, Any] = {}

    class _FakeMapper:
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self.rows = rows

        def replay(self, raw_record_id: str, _raw_identity_string: str, _hint: str) -> dict[str, Any]:
            idx = int(raw_record_id.split("-")[1]) - 1
            return self.rows[idx]

    replay_rows = _atlas_replay_rows()

    def _fake_load_disease_pack(pack_path: Path | None = None, **kwargs: Any):
        called["pack_path"] = pack_path or kwargs.get("path") or kwargs.get("disease_pack_path")
        return object()

    def _fake_load_identity_map(
        *,
        map_path: Path | None = None,
        response_root: Path | None = None,
        lock_path: Path | None = None,
        disease_pack: object | None = None,
        raw_inventory_path: Path | None = None,
        **kwargs: Any,
    ):
        map_path = map_path or kwargs.get("map")
        response_root = response_root or kwargs.get("official_response_root")
        lock_path = lock_path or kwargs.get("lock")
        raw_inventory_path = raw_inventory_path or kwargs.get("raw_inventory")
        called["map_path"] = map_path
        called["response_root"] = response_root
        called["lock_path"] = lock_path
        called["disease_pack"] = disease_pack
        called["raw_inventory_path"] = raw_inventory_path
        return _FakeMapper(replay_rows)

    raw_inventory_rows = [
        {"raw_record_id": f"raw-{i}", "raw_identity_string": f"p.Synthetic{i}", "source_reported_consequence_hint": "missense_substitution"}
        for i in range(1, 36)
    ]
    map_payload = yaml.safe_dump(
        {"schema": "atlas.raw_identity_map.v2", "map_record_count": 35, "records": [{"raw_record_id": row["raw_record_id"]} for row in raw_inventory_rows]},
        sort_keys=False,
    ).encode("utf-8")
    lock_payload_body = {"schema": "atlas.raw_identity_map_lock.v2", "map_content_hash": "synthetic-map-content-hash"}
    lock_payload = _yaml_bytes(lock_payload_body, sort_keys=True)
    lock_payload_body["lock_content_hash"] = _identity_map_lock_content_hash(lock_payload)
    lock_payload = _yaml_bytes(lock_payload_body, sort_keys=True)
    raw_inventory_payload = yaml.safe_dump(
        {"schema": "atlas.discovery_inventory.raw.v1", "row_count": 35, "records": raw_inventory_rows},
        sort_keys=False,
    ).encode("utf-8")
    response_bundle_observed = _response_bundle_observed(
        {
            "official_responses/alpha.json": b'{"id":"alpha","status":"ok"}\n',
            "official_responses/beta.json": b'{"id":"beta","status":"ok"}\n',
        }
    )
    expected_map_pin = {
        "schema": "atlas.raw_identity_map.v2",
        "sha256": _sha256(map_payload),
        "byte_length": len(map_payload),
        "map_record_count": 35,
    }
    expected_lock_pin = {
        "schema": "atlas.raw_identity_map_lock.v2",
        "lock_content_hash": lock_payload_body["lock_content_hash"],
    }
    expected_raw_inventory_pin = {
        "sha256": _sha256(raw_inventory_payload),
        "byte_length": len(raw_inventory_payload),
        "row_count": 35,
    }
    expected_response_bundle_pin = dict(response_bundle_observed)

    result = api["load_atlas_contrast_replays"](
        map_path=Path("synthetic/raw_identity_map.yaml"),
        response_root=Path("synthetic/official_responses"),
        lock_path=Path("synthetic/lock.yaml"),
        disease_pack_path=Path("synthetic/pack.yaml"),
        raw_inventory_path=Path("synthetic/discovery_inventory.raw.yaml"),
        map_payload=map_payload,
        lock_payload=lock_payload,
        raw_inventory_payload=raw_inventory_payload,
        response_bundle_observed=response_bundle_observed,
        raw_inventory_rows=raw_inventory_rows,
        expected_map_pin=expected_map_pin,
        expected_lock_pin=expected_lock_pin,
        expected_raw_inventory_pin=expected_raw_inventory_pin,
        expected_response_bundle_pin=expected_response_bundle_pin,
        expected_counts={"raw_records": 35, "resolved_unique_spdi": 25, "unresolved_records": 10},
        load_disease_pack_fn=_fake_load_disease_pack,
        load_identity_map_fn=_fake_load_identity_map,
    )
    assert called["map_path"] == Path("synthetic/raw_identity_map.yaml")
    assert called["response_root"] == Path("synthetic/official_responses")
    assert called["lock_path"] == Path("synthetic/lock.yaml")
    assert called["raw_inventory_path"] == Path("synthetic/discovery_inventory.raw.yaml")
    assert result["resolved_count"] == 25
    assert result["unresolved_count"] == 10

    bad_replay_rows = deepcopy(replay_rows)
    bad_replay_rows[-1]["spdi_canonical"] = "NC_000016.10:999999:G:A"

    def _fake_bad_loader(**_kwargs: Any):
        return _FakeMapper(bad_replay_rows)

    with pytest.raises(err):
        api["load_atlas_contrast_replays"](
            map_path=Path("synthetic/raw_identity_map.yaml"),
            response_root=Path("synthetic/official_responses"),
            lock_path=Path("synthetic/lock.yaml"),
            disease_pack_path=Path("synthetic/pack.yaml"),
            raw_inventory_path=Path("synthetic/discovery_inventory.raw.yaml"),
            map_payload=map_payload,
            lock_payload=lock_payload,
            raw_inventory_payload=raw_inventory_payload,
            response_bundle_observed=response_bundle_observed,
            raw_inventory_rows=raw_inventory_rows,
            expected_map_pin=expected_map_pin,
            expected_lock_pin=expected_lock_pin,
            expected_raw_inventory_pin=expected_raw_inventory_pin,
            expected_response_bundle_pin=expected_response_bundle_pin,
            expected_counts={"raw_records": 35, "resolved_unique_spdi": 25, "unresolved_records": 10},
            load_disease_pack_fn=_fake_load_disease_pack,
            load_identity_map_fn=_fake_bad_loader,
        )

    bad_map_pin = dict(expected_map_pin)
    bad_map_pin["sha256"] = "0" * 64
    with pytest.raises(err):
        api["load_atlas_contrast_replays"](
            map_path=Path("synthetic/raw_identity_map.yaml"),
            response_root=Path("synthetic/official_responses"),
            lock_path=Path("synthetic/lock.yaml"),
            disease_pack_path=Path("synthetic/pack.yaml"),
            raw_inventory_path=Path("synthetic/discovery_inventory.raw.yaml"),
            map_payload=map_payload,
            lock_payload=lock_payload,
            raw_inventory_payload=raw_inventory_payload,
            response_bundle_observed=response_bundle_observed,
            raw_inventory_rows=raw_inventory_rows,
            expected_map_pin=bad_map_pin,
            expected_lock_pin=expected_lock_pin,
            expected_raw_inventory_pin=expected_raw_inventory_pin,
            expected_response_bundle_pin=expected_response_bundle_pin,
            expected_counts={"raw_records": 35, "resolved_unique_spdi": 25, "unresolved_records": 10},
            load_disease_pack_fn=_fake_load_disease_pack,
            load_identity_map_fn=_fake_load_identity_map,
        )

    bad_lock_payload = _yaml_bytes(
        {
            "schema": "atlas.raw_identity_map_lock.v2",
            "map_content_hash": "mutated-map-content-hash",
            "lock_content_hash": lock_payload_body["lock_content_hash"],
        },
        sort_keys=True,
    )
    with pytest.raises(err):
        api["load_atlas_contrast_replays"](
            map_path=Path("synthetic/raw_identity_map.yaml"),
            response_root=Path("synthetic/official_responses"),
            lock_path=Path("synthetic/lock.yaml"),
            disease_pack_path=Path("synthetic/pack.yaml"),
            raw_inventory_path=Path("synthetic/discovery_inventory.raw.yaml"),
            map_payload=map_payload,
            lock_payload=bad_lock_payload,
            raw_inventory_payload=raw_inventory_payload,
            response_bundle_observed=response_bundle_observed,
            raw_inventory_rows=raw_inventory_rows,
            expected_map_pin=expected_map_pin,
            expected_lock_pin=expected_lock_pin,
            expected_raw_inventory_pin=expected_raw_inventory_pin,
            expected_response_bundle_pin=expected_response_bundle_pin,
            expected_counts={"raw_records": 35, "resolved_unique_spdi": 25, "unresolved_records": 10},
            load_disease_pack_fn=_fake_load_disease_pack,
            load_identity_map_fn=_fake_load_identity_map,
        )

    bad_lock_pin = dict(expected_lock_pin)
    bad_lock_pin["lock_content_hash"] = "0" * 64
    with pytest.raises(err):
        api["load_atlas_contrast_replays"](
            map_path=Path("synthetic/raw_identity_map.yaml"),
            response_root=Path("synthetic/official_responses"),
            lock_path=Path("synthetic/lock.yaml"),
            disease_pack_path=Path("synthetic/pack.yaml"),
            raw_inventory_path=Path("synthetic/discovery_inventory.raw.yaml"),
            map_payload=map_payload,
            lock_payload=lock_payload,
            raw_inventory_payload=raw_inventory_payload,
            response_bundle_observed=response_bundle_observed,
            raw_inventory_rows=raw_inventory_rows,
            expected_map_pin=expected_map_pin,
            expected_lock_pin=bad_lock_pin,
            expected_raw_inventory_pin=expected_raw_inventory_pin,
            expected_response_bundle_pin=expected_response_bundle_pin,
            expected_counts={"raw_records": 35, "resolved_unique_spdi": 25, "unresolved_records": 10},
            load_disease_pack_fn=_fake_load_disease_pack,
            load_identity_map_fn=_fake_load_identity_map,
        )

    bad_response_observed = dict(response_bundle_observed)
    bad_response_observed["byte_count"] += 1
    with pytest.raises(err):
        api["load_atlas_contrast_replays"](
            map_path=Path("synthetic/raw_identity_map.yaml"),
            response_root=Path("synthetic/official_responses"),
            lock_path=Path("synthetic/lock.yaml"),
            disease_pack_path=Path("synthetic/pack.yaml"),
            raw_inventory_path=Path("synthetic/discovery_inventory.raw.yaml"),
            map_payload=map_payload,
            lock_payload=lock_payload,
            raw_inventory_payload=raw_inventory_payload,
            response_bundle_observed=bad_response_observed,
            raw_inventory_rows=raw_inventory_rows,
            expected_map_pin=expected_map_pin,
            expected_lock_pin=expected_lock_pin,
            expected_raw_inventory_pin=expected_raw_inventory_pin,
            expected_response_bundle_pin=expected_response_bundle_pin,
            expected_counts={"raw_records": 35, "resolved_unique_spdi": 25, "unresolved_records": 10},
            load_disease_pack_fn=_fake_load_disease_pack,
            load_identity_map_fn=_fake_load_identity_map,
        )


def test_fc09b_operator_rejects_reparse_response_root_before_tree_hash_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator_module()
    op_error = getattr(operator, "Tsc2FunctionalCoverageMapOperatorError", RuntimeError)
    helper = (
        getattr(operator, "_compute_response_bundle_observed", None)
        or getattr(operator, "_hash_response_bundle", None)
        or getattr(operator, "_compute_official_response_bundle_observed", None)
    )
    if helper is None:
        pytest.fail(
            "operator must expose a monkeypatchable response-root hashing helper "
            "(for reparse rejection before response-tree hashing)"
        )

    sentinel = "sentinel-reparse-ancestor"
    response_root = tmp_path / sentinel / "official_responses"
    response_root.mkdir(parents=True, exist_ok=True)
    hash_calls = {"count": 0}

    def _fake_hash_fn(_root: Path) -> tuple[str, int, int]:
        hash_calls["count"] += 1
        return ("0" * 64, 0, 0)

    def _fake_reparse_predicate(path: Path) -> bool:
        return sentinel in str(path).replace("\\", "/")

    monkeypatch.setattr(operator, "_is_symlink_or_reparse_point", _fake_reparse_predicate)

    kwargs = {"response_root": response_root}
    sig = inspect.signature(helper)
    if "compute_bundle_hash_fn" in sig.parameters:
        kwargs["compute_bundle_hash_fn"] = _fake_hash_fn
    else:
        atlas_identity_map = import_module("raptor.atlas.identity_map")
        monkeypatch.setattr(atlas_identity_map, "_compute_bundle_hash", _fake_hash_fn)

    with pytest.raises(op_error):
        helper(**kwargs)
    assert hash_calls["count"] == 0


def test_fc10_anchor_validation_uses_nested_variant_spdi_and_raw_byte_pin() -> None:
    api = _ingest_api()
    err = api["CoverageInputError"]

    payload = _anchor_payload_nested()
    payload_bytes = _json_bytes(payload)
    pin = {
        "raw_sha256": _sha256(payload_bytes),
        "schema": "raptor.atlas_public_gate_result.v1",
        "required": {
            "run_id": "r611q-gate1-7-v1",
            "scope": "deterministic_fidelity_only",
            "variant": {"spdi": "NC_000016.10:2070570:G:A"},
            "gate_8": "BLOCKED_HUMAN_REVIEW",
            "accepted_claim_count": 0,
            "promote_candidate_invoked": False,
        },
    }

    out = api["validate_atlas_anchor_input"](anchor_payload=payload, anchor_payload_bytes=payload_bytes, expected_pin=pin)
    assert out["spdi"] == "NC_000016.10:2070570:G:A"

    bad = deepcopy(payload)
    bad["gate_8"] = "PASSED"
    with pytest.raises(err):
        api["validate_atlas_anchor_input"](
            anchor_payload=bad,
            anchor_payload_bytes=_json_bytes(bad),
            expected_pin=pin,
        )


def test_fc10b_tracked_anchor_file_hash_and_schema_are_exact() -> None:
    if not ANCHOR_PATH.is_file():
        pytest.fail(f"tracked anchor file missing: {ANCHOR_PATH}")
    anchor_bytes = ANCHOR_PATH.read_bytes()
    assert _sha256(anchor_bytes) == REAL_ATLAS_ANCHOR_PIN["raw_sha256"]
    payload = json.loads(anchor_bytes.decode("utf-8"))
    assert payload["schema"] == REAL_ATLAS_ANCHOR_PIN["schema"]
    assert payload["variant"]["spdi"] == REAL_ATLAS_ANCHOR_PIN["required"]["variant"]["spdi"]
    assert payload["gate_8"] == "BLOCKED_HUMAN_REVIEW"
    assert payload["accepted_claim_count"] == 0
    assert payload["promote_candidate_invoked"] is False


def test_fc11_exact_spdi_joins_row_contract_and_vus_holdout_disjoint_abort() -> None:
    api = _coverage_api()
    err = api["CoverageBuildError"]

    rows = [
        _promoted_row(source_id="mavedb_clipe", source_row=1, spdi="NC_000016.10:100:A:G", score_raw="0.1"),
        _promoted_row(source_id="igvf_vamp_seq", source_row=1, spdi="NC_000016.10:100:A:G", score_raw="0.2"),
        _promoted_row(source_id="igvf_sge", source_row=1, spdi="NC_000016.10:200:C:T", score_raw="0.3"),
    ]
    out = api["build_functional_coverage_rows"](
        functional_rows=rows,
        vus_spdis={"NC_000016.10:100:A:G"},
        priority_by_spdi={},
        prospective_holdout_spdis={"NC_000016.10:200:C:T"},
        atlas_contrast_spdis={"NC_000016.10:100:A:G"},
        atlas_anchor_spdi="NC_000016.10:200:C:T",
        source_order=SOURCE_ORDER,
        leakage_marker_order=LEAKAGE_MARKER_ORDER,
    )
    by_spdi = {row["spdi"]: row for row in out}
    assert by_spdi["NC_000016.10:100:A:G"]["source_ids"] == ["mavedb_clipe", "igvf_vamp_seq"]
    assert by_spdi["NC_000016.10:100:A:G"]["atlas_contrast_candidate"] is True
    assert by_spdi["NC_000016.10:200:C:T"]["atlas_anchor_r611q"] is True
    for row in out:
        assert set(row) == set(REQUIRED_COVERAGE_ROW_FIELDS)
        assert SPDI_CANONICAL_RE.match(row["spdi"])

    with pytest.raises(err):
        api["build_functional_coverage_rows"](
            functional_rows=rows,
            vus_spdis={"NC_000016.10:100:A:G"},
            priority_by_spdi={},
            prospective_holdout_spdis={"NC_000016.10:100:A:G"},
            atlas_contrast_spdis=set(),
            atlas_anchor_spdi="NC_000016.10:200:C:T",
            source_order=SOURCE_ORDER,
            leakage_marker_order=LEAKAGE_MARKER_ORDER,
        )

    strict = api["build_functional_coverage_rows"](
        functional_rows=rows,
        vus_spdis={" NC_000016.10:100:A:G "},
        priority_by_spdi={},
        prospective_holdout_spdis={"NC_000016.10:200:C:T"},
        atlas_contrast_spdis={"nc_000016.10:100:A:G"},
        atlas_anchor_spdi="NC_000016.10:200:C:T",
        source_order=SOURCE_ORDER,
        leakage_marker_order=LEAKAGE_MARKER_ORDER,
    )
    strict_map = {row["spdi"]: row for row in strict}
    assert strict_map["NC_000016.10:100:A:G"]["vus_2026_07"] is False
    assert strict_map["NC_000016.10:100:A:G"]["atlas_contrast_candidate"] is False


def test_fc12_statistics_use_full_cohort_sets_not_only_coverage_rows() -> None:
    api = _coverage_api()
    rows = [
        _coverage_row(
            spdi="NC_000016.10:100:A:G",
            source_ids=["mavedb_clipe"],
            vus=True,
            priority="candidate_LP_review",
            holdout=False,
            atlas_contrast=True,
            atlas_anchor=False,
        ),
        _coverage_row(
            spdi="NC_000016.10:200:C:T",
            source_ids=["igvf_sge"],
            vus=False,
            priority=None,
            holdout=True,
            atlas_contrast=True,
            atlas_anchor=False,
        ),
        _coverage_row(
            spdi="NC_000016.10:300:G:A",
            source_ids=["mavedb_clipe", "igvf_sge"],
            vus=False,
            priority=None,
            holdout=False,
            atlas_contrast=False,
            atlas_anchor=True,
        ),
    ]
    context = {
        "vus_spdis": {"NC_000016.10:100:A:G", "NC_000016.10:999:T:C", "NC_000009.12:111:A:G"},
        "priority_spdis": {"NC_000016.10:100:A:G"},
        "priority_by_spdi": {"NC_000016.10:100:A:G": "candidate_LP_review"},
        "prospective_holdout_spdis": {"NC_000016.10:200:C:T", "NC_000016.10:777:G:T"},
        "atlas_contrast_spdis": {"NC_000016.10:100:A:G", "NC_000016.10:200:C:T", "NC_000016.10:999:T:C"},
        "atlas_anchor_spdi": "NC_000016.10:300:G:A",
        "vus_gene_counts": {"TSC1": 1, "TSC2": 2},
        "priority_gene_counts": {"TSC1": 0, "TSC2": 1},
        "prospective_holdout_gene_counts": {"TSC1": 0, "TSC2": 2},
        "atlas_raw_records": 35,
        "atlas_resolved_count": 25,
        "atlas_unresolved_count": 10,
    }
    stats = _compute_statistics(api["compute_coverage_statistics"], coverage_rows=rows, full_context=context)
    assert stats["cohorts"]["vus"]["identities"] == 3
    assert stats["cohorts"]["vus"]["TSC1"] == 1
    assert stats["cohorts"]["vus"]["TSC2"] == 2
    assert stats["cross_cohort"]["vus__atlas_contrast"] == 2
    assert stats["cross_cohort"]["prospective_holdout__atlas_contrast"] == 1
    assert stats["cross_cohort"]["functional__vus__atlas_contrast"] == 1
    assert stats["cross_cohort"]["functional__prospective_holdout__atlas_contrast"] == 1
    assert stats["cohorts"]["atlas_contrast"]["unresolved_records"] == 10


def test_fc12b_manifest_coverage_statistics_nested_whitelist_arithmetic_and_hash_guard() -> None:
    bundle_api = _bundle_api()
    manifest_err = bundle_api["CoverageManifestError"]
    boundary_err = bundle_api["CoverageBundleBoundaryError"]
    manifest, _ = _minimal_manifest_and_payload(bundle_api)
    stats = manifest["coverage_statistics"]

    assert set(stats) == {
        "functional",
        "cohorts",
        "cross_cohort",
        "functional_cohort_membership_patterns",
        "leakage_markers",
    }
    assert set(stats["functional"]) == {"verified_observations", "unique_spdi", "source_unique", "source_membership_patterns"}
    assert set(stats["cohorts"]) == {"vus", "priority", "prospective_holdout", "atlas_contrast", "atlas_anchor"}
    assert set(stats["cohorts"]["vus"]) == {"identities", "TSC1", "TSC2", "functional_overlap_unique", "source_overlap_unique", "source_membership_patterns"}
    assert set(stats["cohorts"]["priority"]) == {
        "identities",
        "candidate_LP_review",
        "candidate_LB_review",
        "TSC1",
        "TSC2",
        "functional_overlap_unique",
        "candidate_LP_review_overlap",
        "candidate_LB_review_overlap",
        "source_overlap_unique",
        "source_membership_patterns",
    }
    assert set(stats["cohorts"]["prospective_holdout"]) == {"identities", "TSC1", "TSC2", "functional_overlap_unique", "source_overlap_unique", "source_membership_patterns"}
    assert set(stats["cohorts"]["atlas_contrast"]) == {
        "raw_records",
        "resolved_unique_spdi",
        "unresolved_records",
        "functional_overlap_unique",
        "source_overlap_unique",
        "source_membership_patterns",
    }
    assert set(stats["cohorts"]["atlas_anchor"]) == {"identities", "functional_overlap_unique", "source_overlap_unique", "prospective_holdout_overlap"}
    assert set(stats["cross_cohort"]) == {
        "vus__prospective_holdout",
        "priority__prospective_holdout",
        "vus__atlas_contrast",
        "priority__atlas_contrast",
        "prospective_holdout__atlas_contrast",
        "functional__vus__atlas_contrast",
        "functional__prospective_holdout__atlas_contrast",
        "functional__atlas_contrast_outside_vus_holdout",
    }
    assert set(stats["functional_cohort_membership_patterns"]) == set(FUNCTIONAL_COHORT_MEMBERSHIP_PATTERN_KEYS)
    assert set(stats["leakage_markers"]) == {"PROSPECTIVE_HOLDOUT", "ATLAS_CONTEXT", "PROSPECTIVE_HOLDOUT+ATLAS_CONTEXT"}

    _assert_nonnegative_int_tree(stats, path="coverage_statistics")

    artifact = manifest["artifacts"][0]
    assert manifest["counts"]["rows"] == stats["functional"]["unique_spdi"] == artifact["row_count"]
    assert sum(stats["functional"]["source_unique"].values()) == stats["functional"]["verified_observations"]
    assert sum(stats["functional"]["source_membership_patterns"].values()) == stats["functional"]["unique_spdi"]
    for source in SOURCE_ORDER:
        assert _pattern_membership_sum(stats["functional"]["source_membership_patterns"], source) == stats["functional"]["source_unique"][source]

    for cohort_name in ("vus", "priority", "prospective_holdout", "atlas_contrast"):
        cohort = stats["cohorts"][cohort_name]
        assert set(cohort["source_membership_patterns"]) == set(SOURCE_MEMBERSHIP_PATTERN_KEYS)
        assert sum(cohort["source_membership_patterns"].values()) == cohort["functional_overlap_unique"]
        for source in SOURCE_ORDER:
            assert _pattern_membership_sum(cohort["source_membership_patterns"], source) == cohort["source_overlap_unique"][source]

    for cohort_name in ("vus", "priority", "prospective_holdout"):
        cohort = stats["cohorts"][cohort_name]
        assert cohort["TSC1"] + cohort["TSC2"] == cohort["identities"]
        assert cohort["functional_overlap_unique"] <= cohort["identities"]
        assert cohort["functional_overlap_unique"] <= stats["functional"]["unique_spdi"]
    assert stats["cohorts"]["atlas_contrast"]["functional_overlap_unique"] <= stats["cohorts"]["atlas_contrast"]["resolved_unique_spdi"]
    assert stats["cohorts"]["atlas_anchor"]["functional_overlap_unique"] <= stats["cohorts"]["atlas_anchor"]["identities"]
    assert stats["cohorts"]["atlas_anchor"]["prospective_holdout_overlap"] <= stats["cohorts"]["atlas_anchor"]["functional_overlap_unique"]

    assert stats["cross_cohort"]["vus__prospective_holdout"] <= min(stats["cohorts"]["vus"]["identities"], stats["cohorts"]["prospective_holdout"]["identities"])
    assert stats["cross_cohort"]["priority__prospective_holdout"] <= min(stats["cohorts"]["priority"]["identities"], stats["cohorts"]["prospective_holdout"]["identities"])
    assert stats["cross_cohort"]["vus__atlas_contrast"] <= min(stats["cohorts"]["vus"]["identities"], stats["cohorts"]["atlas_contrast"]["resolved_unique_spdi"])
    assert stats["cross_cohort"]["priority__atlas_contrast"] <= min(stats["cohorts"]["priority"]["identities"], stats["cohorts"]["atlas_contrast"]["resolved_unique_spdi"])
    assert stats["cross_cohort"]["prospective_holdout__atlas_contrast"] <= min(
        stats["cohorts"]["prospective_holdout"]["identities"],
        stats["cohorts"]["atlas_contrast"]["resolved_unique_spdi"],
    )
    assert stats["cross_cohort"]["functional__vus__atlas_contrast"] <= stats["cohorts"]["vus"]["functional_overlap_unique"]
    assert stats["cross_cohort"]["functional__vus__atlas_contrast"] <= stats["cohorts"]["atlas_contrast"]["functional_overlap_unique"]
    assert stats["cross_cohort"]["functional__prospective_holdout__atlas_contrast"] <= stats["cohorts"]["prospective_holdout"]["functional_overlap_unique"]
    assert stats["cross_cohort"]["functional__prospective_holdout__atlas_contrast"] <= stats["cohorts"]["atlas_contrast"]["functional_overlap_unique"]
    assert stats["cross_cohort"]["functional__atlas_contrast_outside_vus_holdout"] <= stats["cohorts"]["atlas_contrast"]["functional_overlap_unique"]

    assert sum(stats["functional_cohort_membership_patterns"].values()) == stats["functional"]["unique_spdi"]
    assert stats["leakage_markers"]["PROSPECTIVE_HOLDOUT"] == (
        stats["functional_cohort_membership_patterns"]["PROSPECTIVE_HOLDOUT"]
        + stats["functional_cohort_membership_patterns"]["PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST"]
        + stats["functional_cohort_membership_patterns"]["PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR"]
    )
    assert stats["leakage_markers"]["ATLAS_CONTEXT"] == (
        stats["functional_cohort_membership_patterns"]["VUS+ATLAS_CONTRAST"]
        + stats["functional_cohort_membership_patterns"]["PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST"]
        + stats["functional_cohort_membership_patterns"]["PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR"]
        + stats["functional_cohort_membership_patterns"]["ATLAS_CONTRAST"]
    )
    assert stats["leakage_markers"]["PROSPECTIVE_HOLDOUT+ATLAS_CONTEXT"] == (
        stats["functional_cohort_membership_patterns"]["PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST"]
        + stats["functional_cohort_membership_patterns"]["PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR"]
    )

    _invoke_validate_manifest_content_hash(bundle_api["validate_manifest_content_hash"], deepcopy(manifest))
    mutated = deepcopy(manifest)
    mutated["coverage_statistics"]["functional"]["source_membership_patterns"]["spdi"] = 1
    with pytest.raises((manifest_err, boundary_err)):
        _invoke_validate_manifest_content_hash(bundle_api["validate_manifest_content_hash"], mutated)


def test_fc12c_statistics_reject_row_membership_flags_disagreeing_with_full_inputs() -> None:
    api = _coverage_api()
    err = api["CoverageBuildError"]
    compute = api["compute_coverage_statistics"]

    row_priority_vus = _coverage_row(
        spdi="NC_000016.10:100:A:G",
        source_ids=["mavedb_clipe"],
        vus=True,
        priority="candidate_LP_review",
        holdout=False,
        atlas_contrast=True,
        atlas_anchor=False,
    )
    row_holdout_anchor = _coverage_row(
        spdi="NC_000016.10:200:C:T",
        source_ids=["igvf_sge"],
        vus=False,
        priority=None,
        holdout=True,
        atlas_contrast=False,
        atlas_anchor=True,
    )
    base_rows = [row_priority_vus, row_holdout_anchor]
    context = {
        "vus_spdis": {"NC_000016.10:100:A:G"},
        "priority_spdis": {"NC_000016.10:100:A:G"},
        "priority_by_spdi": {"NC_000016.10:100:A:G": "candidate_LP_review"},
        "prospective_holdout_spdis": {"NC_000016.10:200:C:T"},
        "atlas_contrast_spdis": {"NC_000016.10:100:A:G"},
        "atlas_anchor_spdi": "NC_000016.10:200:C:T",
        "vus_gene_counts": {"TSC1": 0, "TSC2": 1},
        "priority_gene_counts": {"TSC1": 0, "TSC2": 1},
        "prospective_holdout_gene_counts": {"TSC1": 0, "TSC2": 1},
        "atlas_raw_records": 2,
        "atlas_resolved_count": 2,
        "atlas_unresolved_count": 0,
    }

    _compute_statistics(compute, coverage_rows=deepcopy(base_rows), full_context=deepcopy(context))

    mutated_sets: list[list[dict[str, Any]]] = [
        [
            _coverage_row(
                spdi="NC_000016.10:100:A:G",
                source_ids=["mavedb_clipe"],
                vus=False,
                priority=None,
                holdout=False,
                atlas_contrast=True,
                atlas_anchor=False,
            ),
            deepcopy(row_holdout_anchor),
        ],
        [
            _coverage_row(
                spdi="NC_000016.10:100:A:G",
                source_ids=["mavedb_clipe"],
                vus=True,
                priority="candidate_LB_review",
                holdout=False,
                atlas_contrast=True,
                atlas_anchor=False,
            ),
            deepcopy(row_holdout_anchor),
        ],
        [
            _coverage_row(
                spdi="NC_000016.10:100:A:G",
                source_ids=["mavedb_clipe"],
                vus=True,
                priority=None,
                holdout=False,
                atlas_contrast=True,
                atlas_anchor=False,
            ),
            deepcopy(row_holdout_anchor),
        ],
        [
            deepcopy(row_priority_vus),
            _coverage_row(
                spdi="NC_000016.10:200:C:T",
                source_ids=["igvf_sge"],
                vus=False,
                priority=None,
                holdout=False,
                atlas_contrast=False,
                atlas_anchor=True,
            ),
        ],
        [
            _coverage_row(
                spdi="NC_000016.10:100:A:G",
                source_ids=["mavedb_clipe"],
                vus=True,
                priority="candidate_LP_review",
                holdout=False,
                atlas_contrast=False,
                atlas_anchor=False,
            ),
            deepcopy(row_holdout_anchor),
        ],
        [
            deepcopy(row_priority_vus),
            _coverage_row(
                spdi="NC_000016.10:200:C:T",
                source_ids=["igvf_sge"],
                vus=False,
                priority=None,
                holdout=True,
                atlas_contrast=False,
                atlas_anchor=False,
            ),
        ],
    ]

    for mutated_rows in mutated_sets:
        with pytest.raises(err):
            _compute_statistics(compute, coverage_rows=mutated_rows, full_context=deepcopy(context))


def test_fc12d_manifest_rejects_cross_cohort_arithmetic_self_hash_mutations() -> None:
    bundle_api = _bundle_api()
    manifest_err = bundle_api["CoverageManifestError"]
    validate = bundle_api["validate_manifest_content_hash"]
    recompute = bundle_api["compute_manifest_content_hash"]
    manifest, _ = _minimal_manifest_and_payload(bundle_api)

    def _reject(mutator: Any) -> None:
        candidate = deepcopy(manifest)
        mutator(candidate)
        candidate["content_hash"] = recompute(candidate)
        with pytest.raises(manifest_err):
            _invoke_validate_manifest_content_hash(validate, candidate)

    _reject(lambda m: m["coverage_statistics"]["cross_cohort"].__setitem__("vus__prospective_holdout", 1))
    _reject(lambda m: m["coverage_statistics"]["cross_cohort"].__setitem__("priority__atlas_contrast", 1))
    _reject(lambda m: m["coverage_statistics"]["cross_cohort"].__setitem__("functional__vus__atlas_contrast", 2))
    _reject(
        lambda m: m["coverage_statistics"]["cross_cohort"].__setitem__(
            "functional__atlas_contrast_outside_vus_holdout", 1
        )
    )


def test_fc13_manifest_uses_coverage_statistics_field_and_expected_pilot_comparison_uses_it() -> None:
    bundle_api = _bundle_api()
    operator = _load_operator_module()
    op_error = getattr(operator, "Tsc2FunctionalCoverageMapOperatorError", RuntimeError)
    helper = getattr(operator, "_validate_expected_pilot_result", None)
    if helper is None:
        pytest.fail("operator must define _validate_expected_pilot_result(manifest, expected_pilot)")

    manifest, _ = _minimal_manifest_and_payload(bundle_api)
    assert "coverage_statistics" in manifest
    assert "expected_pilot" not in manifest

    pilot_manifest = {"coverage_statistics": deepcopy(EXPECTED_PILOT)}
    helper(manifest=pilot_manifest, expected_pilot=deepcopy(EXPECTED_PILOT))

    bool_leak = {"coverage_statistics": deepcopy(EXPECTED_PILOT)}
    bool_leak["coverage_statistics"]["functional_cohort_membership_patterns"]["VUS+ATLAS_CONTRAST"] = True
    with pytest.raises(op_error):
        helper(manifest=bool_leak, expected_pilot=deepcopy(EXPECTED_PILOT))

    float_leak = {"coverage_statistics": deepcopy(EXPECTED_PILOT)}
    float_leak["coverage_statistics"]["functional_cohort_membership_patterns"]["VUS+ATLAS_CONTRAST"] = 1.0
    with pytest.raises(op_error):
        helper(manifest=float_leak, expected_pilot=deepcopy(EXPECTED_PILOT))

    with pytest.raises(op_error):
        helper(manifest={"expected_pilot": deepcopy(EXPECTED_PILOT)}, expected_pilot=deepcopy(EXPECTED_PILOT))


def test_fc13b_operator_expected_pilot_gate_runs_before_publication() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 functional coverage operator script is missing: {OPERATOR_SCRIPT}")
    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    main_node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if main_node is None:
        pytest.fail("operator script must define main(argv=...)")
    seen: dict[str, int] = {}
    for node in ast.walk(main_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                seen.setdefault(node.func.id, node.lineno)
            elif isinstance(node.func, ast.Attribute):
                seen.setdefault(node.func.attr, node.lineno)
    assert "_validate_expected_pilot_result" in seen
    assert "publish_coverage_bundle" in seen
    assert seen["_validate_expected_pilot_result"] < seen["publish_coverage_bundle"]


def test_fc13c_operator_dry_run_flag_and_branch_prevent_publish_and_summary_writes_after_gate() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 functional coverage operator script is missing: {OPERATOR_SCRIPT}")
    source = OPERATOR_SCRIPT.read_text(encoding="utf-8")
    assert "--dry-run" in source

    tree = ast.parse(source, filename=str(OPERATOR_SCRIPT))
    main_node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if main_node is None:
        pytest.fail("operator script must define main(argv=...)")

    publish_line = None
    summary_line = None
    gate_line = None
    dry_run_if_lines: list[int] = []
    for node in ast.walk(main_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                continue
            if name == "publish_coverage_bundle" and publish_line is None:
                publish_line = node.lineno
            if name == "build_committed_summary" and summary_line is None:
                summary_line = node.lineno
            if name == "_validate_expected_pilot_result" and gate_line is None:
                gate_line = node.lineno
        elif isinstance(node, ast.If):
            names_in_test = {
                child.id
                for child in ast.walk(node.test)
                if isinstance(child, ast.Name)
            }
            attrs_in_test = {
                child.attr
                for child in ast.walk(node.test)
                if isinstance(child, ast.Attribute)
            }
            if "dry_run" in names_in_test or "dry_run" in attrs_in_test:
                dry_run_if_lines.append(node.lineno)

    assert gate_line is not None, "main must call _validate_expected_pilot_result before dry-run exit"
    assert publish_line is not None, "main must publish via publish_coverage_bundle in non-dry-run mode"
    assert dry_run_if_lines, "main must branch on dry_run"
    assert gate_line < min(dry_run_if_lines) < publish_line
    if summary_line is not None:
        assert min(dry_run_if_lines) < summary_line


def test_fc14_input_reader_and_publication_probe_monkeypatchable_reparse_predicate_for_root_and_lexical_ancestors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ingest_api = _ingest_api()
    bundle_api = _bundle_api()
    ingest_module = _load_module("raptor.external.tsc2_functional_coverage.ingest")
    bundle_module = _load_module("raptor.external.tsc2_functional_coverage.bundle")

    read_input_payload = ingest_api["read_input_payload"]
    ingest_error = ingest_api["CoverageInputError"]
    publish_error = bundle_api["CoverageBundleBoundaryError"]

    if not hasattr(ingest_module, "_is_symlink_or_reparse_point"):
        pytest.fail("ingest must expose _is_symlink_or_reparse_point for monkeypatchable path safety checks")
    if not hasattr(bundle_module, "_is_symlink_or_reparse_point"):
        pytest.fail("bundle must expose _is_symlink_or_reparse_point for monkeypatchable path safety checks")

    sentinel = "sentinel-reparse-ancestor"
    supplied_root = tmp_path / sentinel / "safe-root"
    run_dir = supplied_root / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload_path = run_dir / "inputs" / "manifest.jsonl"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = b"{}\n"
    payload_path.write_bytes(payload_bytes)

    ingest_probed: list[str] = []

    def _fake_ingest_predicate(path: Path) -> bool:
        text = str(path).replace("\\", "/")
        ingest_probed.append(text)
        return sentinel in text

    monkeypatch.setattr(ingest_module, "_is_symlink_or_reparse_point", _fake_ingest_predicate)
    read_sig = inspect.signature(read_input_payload)
    read_kwargs = {
        "root": supplied_root,
        "run_name": "run-1",
        "relative_path": "inputs/manifest.jsonl",
        "label": "vus_manifest",
    }
    if "expected_sha256" in read_sig.parameters:
        read_kwargs["expected_sha256"] = _sha256(payload_bytes)
    if "expected_byte_length" in read_sig.parameters:
        read_kwargs["expected_byte_length"] = len(payload_bytes)
    with pytest.raises(ingest_error):
        read_input_payload(**read_kwargs)
    assert any(sentinel in path for path in ingest_probed)

    manifest, payloads = _minimal_manifest_and_payload(bundle_api)
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    output_root = tmp_path / sentinel / "external"
    output_root.mkdir(parents=True, exist_ok=True)

    bundle_probed: list[str] = []

    def _fake_bundle_predicate(path: Path) -> bool:
        text = str(path).replace("\\", "/")
        bundle_probed.append(text)
        return sentinel in text

    monkeypatch.setattr(bundle_module, "_is_symlink_or_reparse_point", _fake_bundle_predicate)
    with pytest.raises(publish_error):
        bundle_api["publish_coverage_bundle"](
            repo_root=repo_root,
            output_root=output_root,
            run_name="coverage-run",
            manifest=manifest,
            artifact_payloads=payloads,
        )
    assert any(sentinel in path for path in bundle_probed)


def test_fc15_publication_create_only_outside_repo_and_no_clobber_manifest_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_api = _bundle_api()
    bundle_module = _load_module("raptor.external.tsc2_functional_coverage.bundle")
    source_bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    assert bundle_api["_publish_directory_no_replace"] is _symbol(source_bundle_module, "_publish_directory_no_replace")

    manifest, payloads = _minimal_manifest_and_payload(bundle_api)
    boundary_err = bundle_api["CoverageBundleBoundaryError"]
    manifest_err = bundle_api["CoverageManifestError"]

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    inside_repo_output = repo_root / "inside-repo-output"
    inside_repo_output.mkdir(parents=True, exist_ok=True)
    with pytest.raises(boundary_err):
        bundle_api["publish_coverage_bundle"](
            repo_root=repo_root,
            output_root=inside_repo_output,
            run_name=OUTPUT_RUN_NAME,
            manifest=manifest,
            artifact_payloads=payloads,
        )

    output_root = tmp_path / "external-output"
    output_root.mkdir(parents=True, exist_ok=True)
    preexisting = output_root / OUTPUT_RUN_NAME
    preexisting.mkdir(parents=True, exist_ok=True)
    with pytest.raises((boundary_err, manifest_err)):
        bundle_api["publish_coverage_bundle"](
            repo_root=repo_root,
            output_root=output_root,
            run_name=OUTPUT_RUN_NAME,
            manifest=manifest,
            artifact_payloads=payloads,
        )
    assert preexisting.exists()
    assert not (preexisting / "bundle_manifest.json").exists()

    bad_payloads = deepcopy(payloads)
    bad_payloads[OUTPUT_ARTIFACT_PATH] = bad_payloads[OUTPUT_ARTIFACT_PATH] + b"#"
    with pytest.raises((boundary_err, manifest_err)):
        bundle_api["publish_coverage_bundle"](
            repo_root=repo_root,
            output_root=output_root,
            run_name="bad-payload-run",
            manifest=manifest,
            artifact_payloads=bad_payloads,
        )

    safe_output = tmp_path / "safe-output"
    safe_output.mkdir(parents=True, exist_ok=True)
    write_order: list[str] = []
    real_write_bytes = getattr(bundle_module, "_write_bytes_exclusive", None)
    if real_write_bytes is None:
        pytest.fail("bundle module must expose _write_bytes_exclusive for manifest-last publication check")

    def _record_write(destination_path: Path, payload: bytes, created_files: list[Path]) -> None:
        write_order.append(destination_path.name)
        real_write_bytes(destination_path, payload, created_files)

    monkeypatch.setattr(bundle_module, "_write_bytes_exclusive", _record_write)
    result = bundle_api["publish_coverage_bundle"](
        repo_root=repo_root,
        output_root=safe_output,
        run_name="successful-run",
        manifest=manifest,
        artifact_payloads=payloads,
    )

    if isinstance(result, dict):
        run_path = Path(result.get("run_dir") or result.get("run_path") or "")
    else:
        run_path = Path(str(result))
    assert run_path
    if not run_path.is_absolute():
        run_path = (safe_output / run_path).resolve()
    assert run_path.exists()
    assert (run_path / OUTPUT_ARTIFACT_PATH).read_bytes() == payloads[OUTPUT_ARTIFACT_PATH]
    assert (run_path / "bundle_manifest.json").is_file()
    assert write_order and write_order[-1] == "bundle_manifest.json"
    assert "bundle_manifest.json" not in write_order[:-1]

    with pytest.raises(boundary_err):
        bundle_api["publish_coverage_bundle"](
            repo_root=repo_root,
            output_root=safe_output,
            run_name="successful-run",
            manifest=manifest,
            artifact_payloads=payloads,
        )


def test_fc15b_publication_cleanup_raises_typed_boundary_error_when_staging_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_api = _bundle_api()
    bundle_module = _load_module("raptor.external.tsc2_functional_coverage.bundle")
    boundary_err = bundle_api["CoverageBundleBoundaryError"]

    repo_root = (tmp_path / "repo").resolve()
    repo_root.mkdir(parents=True, exist_ok=True)
    output_root = (tmp_path / "external").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest, payloads = _minimal_manifest_and_payload(bundle_api)
    bad_payloads = deepcopy(payloads)
    bad_payloads[OUTPUT_ARTIFACT_PATH] = bad_payloads[OUTPUT_ARTIFACT_PATH] + b"drift"

    def _failing_rmtree(_path: Path, ignore_errors: bool = False) -> None:
        raise OSError("cleanup failed for staging directory")

    monkeypatch.setattr(bundle_module.shutil, "rmtree", _failing_rmtree)
    with pytest.raises(boundary_err, match="cleanup"):
        bundle_api["publish_coverage_bundle"](
            repo_root=repo_root,
            output_root=output_root,
            run_name="cleanup-failure-run",
            manifest=manifest,
            artifact_payloads=bad_payloads,
        )

    tree = ast.parse(BUNDLE_PATH.read_text(encoding="utf-8"), filename=str(BUNDLE_PATH))
    broad_handlers = [
        handler.lineno
        for handler in ast.walk(tree)
        if isinstance(handler, ast.ExceptHandler)
        and (
            handler.type is None
            or (isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"})
        )
    ]
    assert not broad_handlers, f"bundle.py must not use broad exception handlers: lines={broad_handlers}"


def test_fc16_static_import_boundaries_allow_only_named_seams_and_forbid_network_packet_kb_rescuescreen() -> None:
    targets = [MODEL_PATH, INGEST_PATH, COVERAGE_PATH, BUNDLE_PATH, OPERATOR_SCRIPT]
    missing = [path for path in targets if not path.is_file()]
    if missing:
        pytest.fail("required modules/scripts missing:\n" + "\n".join(str(path) for path in missing))

    required_seams_seen: set[str] = set()
    offenders: list[str] = []
    for path in targets:
        for imported, lineno in _module_imports(path):
            lowered = imported.lower()
            if any(lowered == n or lowered.startswith(n + ".") for n in FORBIDDEN_NETWORK_IMPORTS):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
                continue
            if any(imported == p or imported.startswith(p + ".") for p in FORBIDDEN_DOMAIN_PREFIXES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
                continue

            for prefix in FORBIDDEN_OTHER_DOMAIN_PREFIXES:
                if imported == prefix or imported.startswith(prefix + "."):
                    if imported not in ALLOWED_DOMAIN_SEAMS:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
                    else:
                        required_seams_seen.add(imported)
                    break

    assert not offenders, "domain boundary violations:\n" + "\n".join(offenders)
    assert REQUIRED_DOMAIN_SEAMS.issubset(required_seams_seen), f"missing required seams: {sorted(REQUIRED_DOMAIN_SEAMS - required_seams_seen)}"


def test_fc17_production_overlap_literals_are_forbidden_outside_operator_expected_pilot_gate() -> None:
    package_targets = [MODEL_PATH, INGEST_PATH, COVERAGE_PATH, BUNDLE_PATH]
    missing = [path for path in package_targets if not path.is_file()]
    if missing:
        pytest.fail("required package modules missing:\n" + "\n".join(str(path) for path in missing))

    offenders: list[str] = []
    for path in package_targets:
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_OVERLAP_LITERAL_PATTERNS:
            if re.search(pattern, text):
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains forbidden expected-pilot literal pattern {pattern!r}")
    assert not offenders, "\n".join(offenders)

    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 functional coverage operator script is not implemented: {OPERATOR_SCRIPT}")
    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    gate_fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_validate_expected_pilot_result"), None)
    if gate_fn is None:
        pytest.fail("operator must define _validate_expected_pilot_result")

    source_lines = OPERATOR_SCRIPT.read_text(encoding="utf-8").splitlines()
    gate_start = gate_fn.lineno
    gate_end = max(getattr(n, "lineno", gate_start) for n in ast.walk(gate_fn))

    for pattern in FORBIDDEN_OVERLAP_LITERAL_PATTERNS:
        for match in re.finditer(pattern, "\n".join(source_lines)):
            line_no = "\n".join(source_lines)[: match.start()].count("\n") + 1
            assert gate_start <= line_no <= gate_end, (
                f"forbidden expected-pilot literal {pattern!r} must appear only in _validate_expected_pilot_result; "
                f"found at line {line_no}"
            )


def test_fc17b_operator_config_trust_gate_uses_exact_default_absolute_path_and_pinned_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator_module()
    op_error = getattr(operator, "Tsc2FunctionalCoverageMapOperatorError", RuntimeError)
    load_config = getattr(operator, "_load_config", None)
    if load_config is None:
        pytest.fail("operator must define _load_config(config_path)")

    source = OPERATOR_SCRIPT.read_text(encoding="utf-8")
    assert CONFIG_CANONICAL_LF_SHA256 in source, "operator must embed pinned canonical-LF config hash"

    pinned_names = [
        name for name, value in vars(operator).items() if isinstance(value, str) and value == CONFIG_CANONICAL_LF_SHA256
    ]
    assert pinned_names, "operator module must expose pinned canonical-LF config hash constant"

    default_config = getattr(operator, "DEFAULT_CONFIG", None)
    assert isinstance(default_config, Path), "operator.DEFAULT_CONFIG must be a Path"
    assert default_config.is_absolute(), "operator.DEFAULT_CONFIG must be absolute"
    assert default_config == CONFIG_PATH, "operator.DEFAULT_CONFIG must target the canonical config path"

    safe_load_calls = {"count": 0}
    real_safe_load = operator.yaml.safe_load

    def _spy_safe_load(payload: Any) -> Any:
        safe_load_calls["count"] += 1
        return real_safe_load(payload)

    monkeypatch.setattr(operator.yaml, "safe_load", _spy_safe_load)

    with pytest.raises(op_error):
        load_config(Path("configs/external/tsc2_functional_coverage_map_v1.yaml"))
    assert safe_load_calls["count"] == 0

    config_copy = (tmp_path / "copy.yaml").resolve()
    config_copy.write_bytes(default_config.read_bytes())
    with pytest.raises(op_error):
        load_config(config_copy)
    assert safe_load_calls["count"] == 0

    alias_path = (tmp_path / "config-alias.yaml").resolve()
    alias_path.symlink_to(default_config)
    with pytest.raises(op_error):
        load_config(alias_path)
    assert safe_load_calls["count"] == 0

    drifted = (tmp_path / "drifted-default.yaml").resolve()
    drifted.write_bytes(_canonical_lf(default_config.read_bytes()) + b"\n# drifted\n")
    monkeypatch.setattr(operator, "DEFAULT_CONFIG", drifted)
    with pytest.raises(op_error):
        load_config(drifted)
    assert safe_load_calls["count"] == 0


def test_fc17c_main_loads_and_verifies_config_before_any_root_resolution_or_reader_calls() -> None:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 functional coverage operator script is missing: {OPERATOR_SCRIPT}")
    tree = ast.parse(OPERATOR_SCRIPT.read_text(encoding="utf-8"), filename=str(OPERATOR_SCRIPT))
    main_node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if main_node is None:
        pytest.fail("operator script must define main(argv=...)")

    first_seen: dict[str, int] = {}
    for node in ast.walk(main_node):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            continue
        first_seen.setdefault(name, node.lineno)

    assert "_load_config" in first_seen
    assert "_resolve_root" in first_seen
    assert "read_input_payload" in first_seen
    assert first_seen["_load_config"] < first_seen["_resolve_root"] < first_seen["read_input_payload"]


def test_fc18_config_pins_binding_spec_exactly_and_uses_real_frozen_values() -> None:
    if not CONFIG_PATH.is_file():
        pytest.fail(f"TSC2 functional coverage config is not implemented: {CONFIG_PATH}")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["spec_id"] == SPEC_ID
    assert config["spec_version"] == SPEC_VERSION

    fn = config["inputs"]["functional_identity_promotion"]
    assert fn["run_name"] == FUNCTIONAL_PROMOTION_RUN_NAME
    assert fn["bundle_id"] == FUNCTIONAL_PROMOTION_BUNDLE_ID
    assert fn["manifest_filename"] == FUNCTIONAL_PROMOTION_MANIFEST
    assert fn["manifest_content_hash"] == FUNCTIONAL_PROMOTION_MANIFEST_HASH
    assert fn["required_identity_state"] == "GENOMIC_SPDI_VERIFIED"
    assert fn["artifacts"] == FUNCTIONAL_PROMOTION_ARTIFACTS

    assert config["inputs"]["vus_universe"]["manifest"] == REAL_VUS_MANIFEST_PIN
    assert config["inputs"]["vus_universe"]["provenance"] == REAL_VUS_PROVENANCE_PIN
    assert config["inputs"]["vus_universe"]["bias_tsv"] == REAL_VUS_BIAS_PIN
    assert config["inputs"]["priority_subset_policy"]["aggregate_manifest"] == REAL_PRIORITY_AGGREGATE_PIN
    assert config["inputs"]["priority_subset_policy"]["queue"] == REAL_PRIORITY_QUEUE_PIN
    assert config["inputs"]["prospective_holdout"]["manifest"] == REAL_HOLDOUT_MANIFEST_PIN
    assert config["inputs"]["prospective_holdout"]["provenance"] == REAL_HOLDOUT_PROVENANCE_PIN
    assert config["inputs"]["prospective_holdout"]["forbidden_reads"] == REAL_HOLDOUT_FORBIDDEN_READS

    assert config["inputs"]["atlas_contrast_identities"]["map"] == REAL_ATLAS_MAP_PIN
    assert config["inputs"]["atlas_contrast_identities"]["response_bundle"] == REAL_ATLAS_RESPONSE_BUNDLE_PIN
    assert config["inputs"]["atlas_contrast_identities"]["raw_inventory"] == REAL_ATLAS_RAW_INVENTORY_PIN
    assert config["inputs"]["atlas_contrast_identities"]["tracked_lock"] == REAL_ATLAS_TRACKED_LOCK_PIN
    assert config["inputs"]["atlas_contrast_identities"]["disease_pack"] == REAL_ATLAS_DISEASE_PACK_PIN
    assert config["inputs"]["atlas_anchor"] == REAL_ATLAS_ANCHOR_PIN

    row_contract = config["coverage_row_contract"]
    assert row_contract["schema"] == COVERAGE_ROW_SCHEMA
    assert row_contract["exact_fields"] == REQUIRED_COVERAGE_ROW_FIELDS
    assert row_contract["source_order"] == SOURCE_ORDER
    assert row_contract["priority_stratum_values"] == PRIORITY_STRATUM_VALUES
    assert row_contract["leakage_marker_order"] == LEAKAGE_MARKER_ORDER

    ext = config["output"]["external_bundle"]
    assert ext["run_name"] == OUTPUT_RUN_NAME
    assert ext["bundle_id"] == OUTPUT_BUNDLE_ID
    assert ext["manifest_schema"] == BUNDLE_SCHEMA
    assert ext["artifacts"]["coverage"]["artifact_id"] == OUTPUT_ARTIFACT_ID
    assert ext["artifacts"]["coverage"]["relative_path"] == OUTPUT_ARTIFACT_PATH
    assert ext["artifacts"]["coverage"]["row_count"] == OUTPUT_ROW_COUNT
    assert ext["create_only"] is True
    assert ext["manifest_last"] is True
    assert ext["symlink_and_reparse_safe"] is True

    summary = config["output"]["committed_summary"]
    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["path"] == str(SUMMARY_PATH.relative_to(REPO_ROOT)).replace("\\", "/")
    assert config["expected_pilot"] == EXPECTED_PILOT
    assert config["boundaries"] == BOUNDARIES


def test_fc19_committed_summary_is_present_and_aggregate_only() -> None:
    if not SUMMARY_PATH.is_file():
        pytest.fail(f"committed summary is missing: {SUMMARY_PATH}")
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert set(summary) == SUMMARY_TOP_LEVEL_KEYS, (
        f"summary top-level keys mismatch. expected={sorted(SUMMARY_TOP_LEVEL_KEYS)} actual={sorted(summary)}"
    )
    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["bundle_id"] == OUTPUT_BUNDLE_ID
    assert summary["boundaries"] == BOUNDARIES

    serialized = json.dumps(summary, sort_keys=True)
    serialized_lower = serialized.lower()
    assert '"label_access"' in serialized_lower
    assert '"ps3_bs3_use"' in serialized_lower
    assert not any(token in serialized_lower for token in FORBIDDEN_QUOTED_ROW_KEYS)
    assert not re.search(r"\bNC_0000(?:09\.12|16\.10):\d+:[ACGT]+:[ACGT]+\b", serialized)
