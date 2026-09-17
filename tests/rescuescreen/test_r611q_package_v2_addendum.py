from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "r611q-package-v2-addendum-v1.yaml"
PACKAGE_MODULE_PATH = REPO_ROOT / "src" / "raptor" / "rescuescreen" / "package_v2.py"
PACKAGE_MODULE_NAME = "raptor.rescuescreen.package_v2"
OPERATOR_SCRIPT_PATH = REPO_ROOT / "scripts" / "build_r611q_package_v2_addendum.py"
CONFIG_PATH = REPO_ROOT / "configs" / "rescuescreen" / "r611q_package_v2_addendum.yaml"
R611Q_DATA_ROOT = REPO_ROOT / "data" / "rescuescreen" / "r611q"
PILOT_SUMMARY_DIR = R611Q_DATA_ROOT / "package-v2-addendum"
PILOT_SUMMARY_JSON_PATH = PILOT_SUMMARY_DIR / "package_summary.json"
PILOT_SUMMARY_README_PATH = PILOT_SUMMARY_DIR / "README.md"

EXPECTED_EXTERNAL_ARTIFACTS = (
    "R611Q_EXPERT_REVIEW_PACKET_V2.md",
    "R611Q_EXPERT_REVIEW_FORM_V2.yaml",
    "R611Q_PACKAGE_V2_IMPACT.json",
    "R611Q_PACKAGE_V2_SUMMARY.md",
    "package_manifest.json",
)

REQUIRED_PACKAGE_API_EXPORTS = (
    "build_r611q_package_v2_addendum",
    "verify_repository_v1_manifests",
    "validate_external_expert_inputs",
    "validate_delta_bundle",
    "select_boundary_observation",
    "compose_packet_v2",
    "compose_form_v2",
    "build_impact_record_v2",
    "render_external_package",
    "build_repository_summary",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "socket",
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "grpc",
    "ftplib",
    "telnetlib",
    "smtplib",
    "imaplib",
    "poplib",
    "raptor.eval",
    "raptor.scorer",
    "raptor.acmg",
    "raptor.clinical",
)

EXPECTED_REPO_V1_MANIFEST_PINS = {
    "literature-v1": {
        "directory": R611Q_DATA_ROOT / "literature-v1",
        "manifest_sha256": "3546b6e20fe0abd945f2079c381c6a9551d55c2c6d44dc8c573f1df4917020c3",
        "manifest_byte_length": 548,
        "files_listed": 6,
    },
    "synthesis-v1": {
        "directory": R611Q_DATA_ROOT / "synthesis-v1",
        "manifest_sha256": "cd56533c1cdb5735217a18e53e5a5bd72c53379f472d0d79adfa96ba9f0350a7",
        "manifest_byte_length": 551,
        "files_listed": 6,
    },
    "structure-readiness-v1": {
        "directory": R611Q_DATA_ROOT / "structure-readiness-v1",
        "manifest_sha256": "5e0ecb473ff906eb45c9c76007bfcd7c3877d411cbaf6b8c63c398493484e82a",
        "manifest_byte_length": 2633,
        "files_listed": 29,
    },
}

EXPECTED_READINESS_SUMMARY_PIN = {
    "path": R611Q_DATA_ROOT / "RESCUESCREEN_EVIDENCE_READINESS_SUMMARY.md",
    "sha256": "8cacf0ff4bb026f851cf7779ac27496d5ee083869281b509cc01d1057acda1a7",
    "byte_length": 29865,
}

BOUNDARY_SEMANTIC_CONSTRAINT = {
    "source_role": "DIRECT_ALLELE_EXPERIMENT",
    "primary_result_state": "PRIMARY_R611Q_RESULT",
    "baseline_relation": "NARROWS",
    "novelty": "NEW_PRIMARY_OBSERVATION",
    "claim_kind": "P_COMPLEX_BINDING",
}

ALLOWED_DECISIONS = ("support", "revise", "reject", "defer")
DELTA_SCHEMA = "raptor.external.r611q_literature_delta_review_bundle.v1"
PACKAGE_MANIFEST_SCHEMA = "raptor.external.r611q_package_v2_addendum_manifest.v1"
MANIFEST_LINE_RE = re.compile(r"^([0-9a-f]{64})  ([^\x00]+)$")
TEXT_CHAR_LOCATOR_RE = re.compile(r"^text-char:\d+:\d+$")

EXPECTED_EXTERNAL_PUBLICATION_PROTOCOL = {
    "platform": "POSIX_dir_fd_required",
    "root_open": "O_DIRECTORY_and_O_NOFOLLOW",
    "staging_and_final_creation": "descriptor_relative",
    "artifact_writes": "O_CREAT_O_EXCL_O_NOFOLLOW",
    "commit_marker": "package_manifest.json_written_last",
    "final_root_identity_check": "required",
    "unsupported_platform": "fail_closed",
}

EXPECTED_SUMMARY_PUBLICATION_PROTOCOL = {
    "trusted_existing_parent": "data/rescuescreen/r611q",
    "parent_open": "descriptor_relative_from_repo_root_with_O_NOFOLLOW",
    "final_directory_creation": "descriptor_relative_create_only",
    "file_writes": "O_CREAT_O_EXCL_O_NOFOLLOW",
    "final_identity_check": "required",
    "rollback": "descriptor_relative_invocation_created_paths_only",
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _acceptable_file_hashes(path: Path) -> set[str]:
    payload = path.read_bytes()
    hashes = {_sha256_bytes(payload)}
    if b"\r\n" not in payload:
        return hashes
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return hashes
    hashes.add(_sha256_bytes(text.replace("\r\n", "\n").encode("utf-8")))
    return hashes


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), f"{path} must parse to a mapping"
    return parsed


def _canonical_json_hash(mapping: Mapping[str, Any], *, drop_field: str | None = None) -> str:
    payload = copy.deepcopy(dict(mapping))
    if drop_field is not None:
        payload.pop(drop_field, None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_bytes(canonical)


def _safe_relative_path(relative_path: str) -> None:
    assert isinstance(relative_path, str) and relative_path, "manifest path must be a nonblank string"
    assert "\\" not in relative_path, f"manifest path uses backslash: {relative_path!r}"
    assert "\x00" not in relative_path, f"manifest path contains null byte: {relative_path!r}"
    pure = PurePosixPath(relative_path)
    assert not pure.is_absolute(), f"manifest path must be relative: {relative_path!r}"
    assert not relative_path.startswith(("./", "../")), f"manifest path traversal: {relative_path!r}"
    assert all(part not in {"", ".", ".."} for part in pure.parts), f"manifest path traversal: {relative_path!r}"
    if pure.parts:
        assert ":" not in pure.parts[0], f"manifest path must not include a drive letter: {relative_path!r}"


def _parse_sha256_manifest(manifest_path: Path) -> list[tuple[str, str]]:
    text = manifest_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines, f"{manifest_path} is empty"
    parsed: list[tuple[str, str]] = []
    for line_number, line in enumerate(lines, start=1):
        match = MANIFEST_LINE_RE.fullmatch(line)
        assert match, f"{manifest_path}:{line_number} must match 'sha256  relative/path'"
        digest, relative_path = match.group(1), match.group(2)
        _safe_relative_path(relative_path)
        parsed.append((digest, relative_path))

    listed_paths = [relative for _, relative in parsed]
    assert listed_paths == sorted(listed_paths), f"{manifest_path} entries must be sorted by relative path"
    assert len(listed_paths) == len(set(listed_paths)), f"{manifest_path} has duplicate relative paths"
    return parsed


def _verify_manifest_file_set(directory: Path, *, expected_manifest_pin: Mapping[str, Any]) -> None:
    manifest_path = directory / "manifest.sha256"
    manifest_bytes = manifest_path.read_bytes()
    assert len(manifest_bytes) == expected_manifest_pin["manifest_byte_length"]
    assert _sha256_bytes(manifest_bytes) == expected_manifest_pin["manifest_sha256"]

    entries = _parse_sha256_manifest(manifest_path)
    assert len(entries) == expected_manifest_pin["files_listed"]

    actual_files = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != "manifest.sha256"
    }
    listed_files = {relative_path for _, relative_path in entries}
    assert listed_files == actual_files, f"{directory} manifest coverage mismatch"

    for digest, relative_path in entries:
        file_path = directory / relative_path
        assert file_path.is_file(), f"manifest-listed file missing: {file_path}"
        assert not file_path.is_symlink(), f"manifest-listed file must not be symlink/reparse: {file_path}"
        assert digest in _acceptable_file_hashes(file_path), f"content hash mismatch for {file_path}"


def _validate_pinned_file(path: Path, *, expected_sha256: str, expected_byte_length: int) -> None:
    payload = path.read_bytes()
    assert len(payload) == expected_byte_length, f"byte-length mismatch for {path}"
    assert _sha256_bytes(payload) == expected_sha256, f"sha256 mismatch for {path}"


def _build_synthetic_delta_bundle() -> tuple[dict[str, Any], dict[str, bytes], list[dict[str, Any]], list[dict[str, Any]]]:
    quote = (
        "Grouped overexpression co-IP in HEK293T reported no observed effect for "
        "R611Q/R905Q/N1620S on TSC2-TSC2 self-association."
    )
    locator = "text-char:120:240"
    quote_hash = _sha256_bytes(quote.encode("utf-8"))
    candidate_id = "cand-synth-001"
    source_id = "source-synth-a"

    candidate_spans = [
        {
            "candidate_id": candidate_id,
            "source_id": source_id,
            "exact_quote": quote,
            "locator": locator,
            "quote_sha256": quote_hash,
            "semantic_tags": ["PRIMARY", "GROUPED"],
        },
        {
            "candidate_id": "cand-synth-noise",
            "source_id": "source-synth-z",
            "exact_quote": "Unrelated source text",
            "locator": "text-char:3:27",
            "quote_sha256": _sha256_bytes(b"Unrelated source text"),
            "semantic_tags": ["CONTEXT_ONLY"],
        },
    ]

    review_records = [
        {
            "candidate_id": candidate_id,
            "source_id": source_id,
            "exact_quote": quote,
            "locator": locator,
            "quote_sha256": quote_hash,
            "source_role": "DIRECT_ALLELE_EXPERIMENT",
            "primary_result_state": "PRIMARY_R611Q_RESULT",
            "baseline_relation": "NARROWS",
            "novelty": "NEW_PRIMARY_OBSERVATION",
            "claim_kind": "P_COMPLEX_BINDING",
            "accepted_claim_count": 0,
            "gate_8_state": "BLOCKED_HUMAN_REVIEW",
            "contradiction_state": "NONE",
        },
        {
            "candidate_id": "cand-synth-noise",
            "source_id": "source-synth-z",
            "exact_quote": "Unrelated source text",
            "locator": "text-char:3:27",
            "quote_sha256": _sha256_bytes(b"Unrelated source text"),
            "source_role": "SECONDARY_CONTEXT",
            "primary_result_state": "CONTEXT_ONLY",
            "baseline_relation": "NARROWS",
            "novelty": "KNOWN",
            "claim_kind": "BACKGROUND",
            "accepted_claim_count": 0,
            "gate_8_state": "BLOCKED_HUMAN_REVIEW",
            "contradiction_state": "NONE",
        },
    ]

    candidate_spans_bytes = ("\n".join(json.dumps(row, sort_keys=True) for row in candidate_spans) + "\n").encode("utf-8")
    review_records_bytes = ("\n".join(json.dumps(row, sort_keys=True) for row in review_records) + "\n").encode("utf-8")
    addendum_bytes = (
        "# Synthetic addendum\n"
        "- Contains one direct grouped boundary observation.\n"
        "- No accepted claims and Gate 8 remains blocked.\n"
    ).encode("utf-8")

    artifacts = {
        "normalized/candidate-spans.jsonl": candidate_spans_bytes,
        "reviewed/review-records.jsonl": review_records_bytes,
        "reviewed/R611Q_LITERATURE_DELTA_ADDENDUM.md": addendum_bytes,
    }
    required_artifacts: dict[str, dict[str, Any]] = {}
    for relative_path, payload in artifacts.items():
        key = {
            "normalized/candidate-spans.jsonl": "candidate_spans",
            "reviewed/review-records.jsonl": "review_records",
            "reviewed/R611Q_LITERATURE_DELTA_ADDENDUM.md": "addendum",
        }[relative_path]
        required_artifacts[key] = {
            "relative_path": relative_path,
            "sha256": _sha256_bytes(payload),
            "byte_length": len(payload),
        }

    manifest: dict[str, Any] = {
        "schema": DELTA_SCHEMA,
        "required_artifacts": required_artifacts,
        "frozen_counts": {
            "candidate_spans": 2,
            "direct_grouped_experiments": 1,
            "narrowing_relations": 1,
            "contradictions": 0,
            "accepted_claims": 0,
        },
    }
    manifest["manifest_content_hash"] = _canonical_json_hash(manifest, drop_field="manifest_content_hash")
    return manifest, artifacts, review_records, candidate_spans


def _validate_delta_bundle_oracle(
    manifest: Mapping[str, Any],
    *,
    manifest_file_sha256: str,
    manifest_byte_length: int,
    artifacts: Mapping[str, bytes],
) -> None:
    assert manifest["schema"] == DELTA_SCHEMA
    assert manifest["manifest_content_hash"] == _canonical_json_hash(manifest, drop_field="manifest_content_hash")

    required_artifacts = manifest["required_artifacts"]
    assert set(required_artifacts) == {"candidate_spans", "review_records", "addendum"}
    for key, descriptor in required_artifacts.items():
        assert set(descriptor) == {"relative_path", "sha256", "byte_length"}
        relative_path = descriptor["relative_path"]
        assert relative_path in artifacts
        payload = artifacts[relative_path]
        assert descriptor["sha256"] == _sha256_bytes(payload)
        assert descriptor["byte_length"] == len(payload)

    expected_paths = {item["relative_path"] for item in required_artifacts.values()}
    assert set(artifacts) == expected_paths, "no extra substitution artifact is allowed"

    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert len(manifest_bytes) == manifest_byte_length
    assert _sha256_bytes(manifest_bytes) == manifest_file_sha256


def _select_boundary_record(
    review_records: list[Mapping[str, Any]],
    candidate_spans: list[Mapping[str, Any]],
) -> Mapping[str, Any]:
    span_by_identity = {(span["candidate_id"], span["source_id"]): span for span in candidate_spans}
    matches: list[Mapping[str, Any]] = []

    for record in review_records:
        if record.get("contradiction_state") not in {"NONE", "NO_CONTRADICTION"}:
            raise AssertionError("delta bundle contradiction is not allowed")
        if int(record.get("accepted_claim_count", -1)) != 0:
            raise AssertionError("delta bundle accepted claim count must remain zero")
        if record.get("gate_8_state") != "BLOCKED_HUMAN_REVIEW":
            raise AssertionError("Gate 8 effect must remain blocked")

        if all(record.get(key) == value for key, value in BOUNDARY_SEMANTIC_CONSTRAINT.items()):
            identity = (record["candidate_id"], record["source_id"])
            span = span_by_identity.get(identity)
            assert span is not None, "selected review record has no matching candidate span"
            assert span["exact_quote"] == record["exact_quote"]
            assert span["locator"] == record["locator"]
            assert span["quote_sha256"] == record["quote_sha256"]
            matches.append(record)

    if not matches:
        raise AssertionError("expected exactly one semantic boundary match; found zero")
    if len(matches) > 1:
        raise AssertionError(f"expected exactly one semantic boundary match; found {len(matches)}")
    return matches[0]


def _canonical_source_id_from_article_identity(article_identity: Mapping[str, Any]) -> str:
    assert isinstance(article_identity, Mapping), "article_identity must be a mapping"
    for key, prefix in (("pmid", "PMID"), ("PMCID", "PMCID"), ("doi", "DOI")):
        raw = article_identity.get(key)
        if raw is None and key == "PMCID":
            raw = article_identity.get("pmcid")
        value = str(raw).strip() if raw is not None else ""
        if value:
            return f"{prefix}:{value}"
    raise AssertionError("article_identity must provide PMID, PMCID, or DOI")


def _build_selector_identity_fixture(
    *,
    duplicate_record_quote_fields: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    article_identity = {"pmid": "99999999", "pmcid": "PMC9000001", "doi": "10.0000/synthetic.r611q.001"}
    source_id = _canonical_source_id_from_article_identity(article_identity)
    exact_quote = "Grouped HEK293T tagged-overexpression co-IP reports no observed effect on TSC2-TSC2 association."
    locator = "text-char:40:142"
    exact_quote_sha256 = _sha256_bytes(exact_quote.encode("utf-8"))

    primary_span = {
        "candidate_id": "cand-selector-001",
        "source_id": source_id,
        "article_identity": copy.deepcopy(article_identity),
        "exact_quote": exact_quote,
        "locator": locator,
        "exact_quote_sha256": exact_quote_sha256,
        # Kept for compatibility with the current synthetic contract helper.
        "quote_sha256": exact_quote_sha256,
    }
    context_span = {
        "candidate_id": "cand-selector-noise",
        "source_id": "PMID:11111111",
        "article_identity": {"pmid": "11111111", "pmcid": "", "doi": ""},
        "exact_quote": "Context-only observation",
        "locator": "text-char:1:24",
        "exact_quote_sha256": _sha256_bytes(b"Context-only observation"),
        "quote_sha256": _sha256_bytes(b"Context-only observation"),
    }
    candidate_spans = [primary_span, context_span]

    primary_record = {
        "candidate_id": primary_span["candidate_id"],
        "source_id": source_id,
        "article_identity": copy.deepcopy(article_identity),
        "source_role": "DIRECT_ALLELE_EXPERIMENT",
        "primary_result_state": "PRIMARY_R611Q_RESULT",
        "baseline_relation": "NARROWS",
        "delta_value": "NEW_PRIMARY_OBSERVATION",
        "claim_kind": "P_COMPLEX_BINDING",
        "proposition_ids": ["P_COMPLEX_BINDING"],
        "acceptance_state": "PROPOSED_UNACCEPTED",
        "gate_effect": "NONE",
        "accepted_claim_count": 0,
        "gate_8_state": "BLOCKED_HUMAN_REVIEW",
        "contradiction_state": "NONE",
    }
    if duplicate_record_quote_fields:
        primary_record.update(
            {
                "exact_quote": primary_span["exact_quote"],
                "locator": primary_span["locator"],
                "quote_sha256": primary_span["quote_sha256"],
            }
        )

    context_record = {
        "candidate_id": context_span["candidate_id"],
        "source_id": context_span["source_id"],
        "article_identity": copy.deepcopy(context_span["article_identity"]),
        "source_role": "SECONDARY_CONTEXT",
        "primary_result_state": "CONTEXT_ONLY",
        "baseline_relation": "NARROWS",
        "delta_value": "KNOWN",
        "claim_kind": "BACKGROUND",
        "proposition_ids": ["BACKGROUND"],
        "acceptance_state": "PROPOSED_UNACCEPTED",
        "gate_effect": "NONE",
        "accepted_claim_count": 0,
        "gate_8_state": "BLOCKED_HUMAN_REVIEW",
        "contradiction_state": "NONE",
    }
    if duplicate_record_quote_fields:
        context_record.update(
            {
                "exact_quote": context_span["exact_quote"],
                "locator": context_span["locator"],
                "quote_sha256": context_span["quote_sha256"],
            }
        )

    return [primary_record, context_record], candidate_spans


def _selector_error_type_from_module(module: Any) -> type[BaseException]:
    for error_name in ("BoundarySelectionError", "PackageV2Error"):
        candidate = getattr(module, error_name, None)
        if isinstance(candidate, type) and issubclass(candidate, Exception):
            return candidate
    pytest.fail("package_v2 module does not expose a selector error type")


def _compose_packet_v2(v1_packet_bytes: bytes, *, boundary_record: Mapping[str, Any]) -> bytes:
    section = (
        "\n\n--- r611q-package-v2-addendum :: r611q-claim-2 ---\n"
        "claim_id: r611q-claim-2\n"
        "acceptance_state: PROPOSED_UNACCEPTED\n"
        "baseline_relation: NARROWS\n"
        "assertion: Grouped substitutions R611Q/R905Q/N1620S were reported in tagged-overexpression "
        "HEK293T co-immunoprecipitation without an allele-specific magnitude for TSC2-TSC2 association.\n"
        "limitation: Preserved TSC2-TSC2 self-association does not establish preserved TSC1 binding.\n"
        "final_state: accepted_claims=0; gate_8=BLOCKED_HUMAN_REVIEW\n"
        f"quote_sha256: {boundary_record['quote_sha256']}\n"
    ).encode("utf-8")
    return v1_packet_bytes + section


def _build_form_v2(
    v1_form_yaml_bytes: bytes,
    *,
    base_packet_sha256: str,
    delta_manifest_hash: str,
) -> dict[str, Any]:
    parsed = yaml.safe_load(v1_form_yaml_bytes.decode("utf-8"))
    assert isinstance(parsed, dict), "v1 form YAML must parse to a mapping"
    claims = parsed.get("claims")
    assert isinstance(claims, list) and len(claims) >= 2, "v1 form must contain at least two claims"

    form_v2 = copy.deepcopy(parsed)
    claim_zero, claim_one = copy.deepcopy(claims[0]), copy.deepcopy(claims[1])
    form_v2["claims"] = [claim_zero, claim_one]
    form_v2["claims"].append(
        {
            "claim_id": "r611q-claim-2",
            "decision": None,
            "decision_options": list(ALLOWED_DECISIONS),
            "acceptance_state": "PROPOSED_UNACCEPTED",
            "relation": "NARROWS_NOT_CONTRADICTS",
            "limitations": [
                "grouped_three_substitution_attribution",
                "hek293t_tagged_overexpression_coip",
                "no_allele_specific_magnitude",
                "tsc2_tsc2_not_tsc1_binding",
            ],
        }
    )

    form_v2["packet_status"] = "UNREVIEWED"
    form_v2["accepted_claim_count"] = 0
    form_v2["gate_8_state"] = "BLOCKED_HUMAN_REVIEW"
    form_v2["base_packet_sha256"] = base_packet_sha256
    form_v2["base_form_sha256"] = _sha256_bytes(v1_form_yaml_bytes)
    form_v2["delta_manifest_hash"] = delta_manifest_hash
    return form_v2


def _assert_form_v2_preserves_v1(form_v1: Mapping[str, Any], form_v2: Mapping[str, Any]) -> None:
    assert form_v2["variant"] == form_v1["variant"]
    assert form_v2["bindings"] == form_v1["bindings"]
    assert form_v2["reviewer"] == form_v1["reviewer"]
    assert form_v2["scope"] == form_v1["scope"]
    assert form_v2["claims"][0] == form_v1["claims"][0]
    assert form_v2["claims"][1] == form_v1["claims"][1]
    assert len(form_v2["claims"]) == len(form_v1["claims"]) + 1
    claim2 = form_v2["claims"][2]
    assert claim2["claim_id"] == "r611q-claim-2"
    assert claim2["decision"] is None
    assert tuple(claim2["decision_options"]) == ALLOWED_DECISIONS
    assert form_v2["packet_status"] == "UNREVIEWED"
    assert int(form_v2["accepted_claim_count"]) == 0
    assert form_v2["gate_8_state"] == "BLOCKED_HUMAN_REVIEW"


def _validate_impact_record_oracle(impact: Mapping[str, Any]) -> None:
    assert impact["literature_v1"] == "IMMUTABLE"
    assert impact["synthesis_v1"] == "IMMUTABLE"
    assert impact["structure_readiness_v1"] == "IMMUTABLE"
    assert impact["route_effect"]["RH-2"] == "PLAUSIBLE_NOT_DEMONSTRATED"
    assert impact["coip_interpretation"] == "TSC2-TSC2_NON_DISCRIMINATING"
    assert impact["assay_falsifier"]["AF-4"] == "TSC1-TSC2_WITH_MATCHED_ABUNDANCE"
    assert impact["model_contexts"] == {"count": 4, "package_effect": "CONTEXT_ONLY"}
    assert impact["clinical_occurrences"] == {"count": 2, "package_effect": "OCCURRENCE_ONLY"}
    assert impact["secondary_reviews"] == {"count": 3, "package_effect": "NO_PROPOSITION_SUPPORT"}
    assert impact["contradictions"] == 0
    assert impact["stage_execution_authorized"] is False
    assert impact["historical_4169_expansion"] is False


def _render_external_package_oracle(
    output_root: Path,
    *,
    package_id: str,
    repository_summary_target: str,
    artifacts: Mapping[str, bytes],
) -> tuple[Path, tuple[str, ...]]:
    assert repository_summary_target == "data/rescuescreen/r611q/package-v2-addendum"
    assert package_id == "r611q-package-v2-addendum-2026-09-17"
    assert set(artifacts) == set(EXPECTED_EXTERNAL_ARTIFACTS[:-1]), "external render requires exact four payload artifacts"
    assert output_root.is_absolute(), "external render root must be absolute"
    assert not output_root.is_symlink(), "external render root must not be a symlink/reparse"

    package_dir = output_root / package_id
    if package_dir.exists():
        raise AssertionError("external package path already exists (create-only contract)")
    package_dir.mkdir(parents=True)

    written_order: list[str] = []
    manifest_rows: list[dict[str, Any]] = []
    for artifact_name in EXPECTED_EXTERNAL_ARTIFACTS[:-1]:
        target = package_dir / artifact_name
        resolved_parent = target.resolve().parent
        assert str(resolved_parent).startswith(str(package_dir.resolve())), "artifact path escaped package directory"
        payload = artifacts[artifact_name]
        target.write_bytes(payload)
        written_order.append(artifact_name)
        manifest_rows.append(
            {
                "name": artifact_name,
                "sha256": _sha256_bytes(payload),
                "byte_length": len(payload),
            }
        )

    manifest = {
        "schema": PACKAGE_MANIFEST_SCHEMA,
        "package_id": package_id,
        "create_only": True,
        "repository_summary_target": repository_summary_target,
        "artifacts": manifest_rows,
    }
    manifest["manifest_content_hash"] = _canonical_json_hash(manifest, drop_field="manifest_content_hash")
    manifest_payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    (package_dir / "package_manifest.json").write_bytes(manifest_payload)
    written_order.append("package_manifest.json")

    return package_dir, tuple(written_order)


def _derive_repository_summary_oracle(
    *,
    input_hashes: Mapping[str, str],
    output_hashes: Mapping[str, str],
    accepted_claim_count: int,
    gate_8_state: str,
    stage_execution_authorized: bool,
) -> tuple[dict[str, Any], str]:
    summary = {
        "schema": "raptor.repository.r611q_package_v2_addendum_summary.v1",
        "inputs": dict(input_hashes),
        "outputs": dict(output_hashes),
        "counts": {"accepted_claims": accepted_claim_count},
        "state": {
            "gate_8": gate_8_state,
            "stage_execution_authorized": stage_execution_authorized,
            "historical_tsc2_corpus_expansion": "deferred",
        },
        "decisions": {
            "package_update_warranted": True,
            "broader_historical_corpus_expansion_warranted": False,
        },
    }
    readme = (
        "# R611Q package-v2 addendum summary\n\n"
        "This repository summary is aggregate-only. It includes input/output hashes, counts and state, "
        "with no source-identity details.\n"
    )
    forbidden = ("pmid", "pmcid", "doi", "title", "candidate_id", "locator", "patient")
    serialized = json.dumps(summary, sort_keys=True).lower() + "\n" + readme.lower()
    assert all(token not in serialized for token in forbidden), "summary leaked restricted identity content"
    return summary, readme


def _require_package_v2_module():
    try:
        spec = importlib.util.find_spec(PACKAGE_MODULE_NAME)
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        pytest.fail(f"implementation missing: {PACKAGE_MODULE_NAME} ({PACKAGE_MODULE_PATH})")
    module = importlib.import_module(PACKAGE_MODULE_NAME)
    missing = [name for name in REQUIRED_PACKAGE_API_EXPORTS if not hasattr(module, name)]
    assert not missing, f"package_v2 API missing required exports: {missing}"
    return module


def _load_operator_module() -> Any:
    if not OPERATOR_SCRIPT_PATH.is_file():
        pytest.fail(f"implementation missing: {OPERATOR_SCRIPT_PATH}")

    spec = importlib.util.spec_from_file_location(
        "r611q_package_v2_addendum_operator",
        OPERATOR_SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"unable to load operator module spec: {OPERATOR_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_operator_fixture_and_config(
    tmp_path: Path,
    *,
    repository_summary_directory: str = "data/rescuescreen/r611q/package-v2-addendum",
) -> tuple[Any, Any, Path, Path, Path, Path, Path, str]:
    module = _load_operator_module()
    fixture_root = tmp_path / "operator-fixture"
    fixture = module._materialize_offline_fixture(fixture_root)

    config = copy.deepcopy(fixture.config_defaults)
    output = config.setdefault("output", {})
    output["package_id"] = "r611q-package-v2-addendum-2026-09-17"
    output["root_must_preexist"] = True
    output["publication_protocol"] = copy.deepcopy(EXPECTED_EXTERNAL_PUBLICATION_PROTOCOL)
    output["external_artifacts"] = list(EXPECTED_EXTERNAL_ARTIFACTS)
    output["repository_summary"] = {
        "directory": repository_summary_directory,
        "json_path": f"{repository_summary_directory}/package_summary.json",
        "readme_path": f"{repository_summary_directory}/README.md",
        "publication_protocol": copy.deepcopy(EXPECTED_SUMMARY_PUBLICATION_PROTOCOL),
    }
    config["spec_id"] = "r611q-package-v2-addendum-v1"
    config["spec_version"] = "1.0.3"

    config_path = tmp_path / "operator_config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    expected_summary_dir = (fixture.repo_root / repository_summary_directory).resolve()
    expected_summary_json = expected_summary_dir / "package_summary.json"
    expected_summary_readme = expected_summary_dir / "README.md"
    return (
        module,
        fixture,
        config_path,
        expected_summary_dir,
        expected_summary_json,
        expected_summary_readme,
        fixture.repo_root.resolve(),
        output["package_id"],
    )


def _run_operator_main(
    module: Any,
    *,
    config_path: Path,
    repo_root: Path,
    v1_packet_path: Path,
    v1_form_path: Path,
    delta_bundle_root: Path,
    output_root: Path,
    repository_summary_dir: Path | None = None,
) -> int:
    argv = [
        "--config",
        str(config_path),
        "--repo-root",
        str(repo_root),
        "--v1-packet",
        str(v1_packet_path),
        "--v1-form",
        str(v1_form_path),
        "--delta-bundle-root",
        str(delta_bundle_root),
        "--output-root",
        str(output_root),
    ]
    if repository_summary_dir is not None:
        argv.extend(["--repository-summary-dir", str(repository_summary_dir)])
    return int(module.main(argv))


def _write_operator_config(config_path: Path, config: Mapping[str, Any]) -> None:
    config_path.write_text(
        yaml.safe_dump(dict(config), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _install_publication_call_guards(module: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    called = {"summary_publish": False, "external_render": False}

    def unexpected_summary_publish(*_args: Any, **_kwargs: Any):
        called["summary_publish"] = True
        raise module.PackageV2Error("unexpected summary publication call before path validation")

    def unexpected_external_render(*_args: Any, **_kwargs: Any):
        called["external_render"] = True
        raise module.PackageV2Error("unexpected external publication call before path validation")

    monkeypatch.setattr(module, "publish_repository_summary_descriptor_relative", unexpected_summary_publish)
    monkeypatch.setattr(module, "render_external_package", unexpected_external_render)
    return called


def _import_names_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_r611q_pv2a_ac01_spec_surface_and_exact_pins() -> None:
    assert SPEC_PATH.is_file(), f"missing spec: {SPEC_PATH}"
    spec = _read_yaml_mapping(SPEC_PATH)

    assert spec["schema"] == "raptor.project.spec.v1"
    assert spec["spec_id"] == "r611q-package-v2-addendum-v1"
    assert spec["spec_version"] == "1.0.3"
    implementation = spec["implementation"]
    assert implementation["package"] == "src/raptor/rescuescreen/package_v2.py"
    assert implementation["operator"] == "scripts/build_r611q_package_v2_addendum.py"
    assert implementation["config"] == "configs/rescuescreen/r611q_package_v2_addendum.yaml"
    assert implementation["tests"] == "tests/rescuescreen/test_r611q_package_v2_addendum.py"
    assert implementation["network"] == "forbidden"

    external = spec["output"]["external_package"]
    assert external["environment_variable"] == "RAPTOR_R611Q_PACKAGE_V2_ROOT"
    assert external["root_must_preexist"] is True
    assert external["run_name"] == "r611q-package-v2-addendum-2026-09-17"
    assert external["package_id"] == "r611q-package-v2-addendum-2026-09-17"
    assert tuple(external["artifacts"]) == EXPECTED_EXTERNAL_ARTIFACTS
    assert external["publication_protocol"] == EXPECTED_EXTERNAL_PUBLICATION_PROTOCOL
    assert spec["output"]["repository_summary"]["directory"] == "data/rescuescreen/r611q/package-v2-addendum"
    assert spec["output"]["repository_summary"]["json_path"] == "data/rescuescreen/r611q/package-v2-addendum/package_summary.json"
    assert spec["output"]["repository_summary"]["readme_path"] == "data/rescuescreen/r611q/package-v2-addendum/README.md"
    assert spec["output"]["repository_summary"]["publication_protocol"] == EXPECTED_SUMMARY_PUBLICATION_PROTOCOL

    expected_structure_manifest_pin = {
        "directory": "data/rescuescreen/r611q/structure-readiness-v1",
        "manifest_path": "data/rescuescreen/r611q/structure-readiness-v1/manifest.sha256",
        "manifest_file_sha256": EXPECTED_REPO_V1_MANIFEST_PINS["structure-readiness-v1"]["manifest_sha256"],
        "manifest_byte_length": EXPECTED_REPO_V1_MANIFEST_PINS["structure-readiness-v1"]["manifest_byte_length"],
        "files_listed": EXPECTED_REPO_V1_MANIFEST_PINS["structure-readiness-v1"]["files_listed"],
    }
    assert spec["inputs"]["v1_repository_package"]["structure_readiness"] == expected_structure_manifest_pin


def test_r611q_pv2a_ac01_required_package_operator_and_config_surfaces_exist() -> None:
    missing = [str(path) for path in (PACKAGE_MODULE_PATH, OPERATOR_SCRIPT_PATH, CONFIG_PATH) if not path.is_file()]
    assert not missing, f"implementation missing required addendum surfaces: {missing}"


def test_r611q_pv2a_ac01_config_exact_pins_and_output_names() -> None:
    if not CONFIG_PATH.is_file():
        pytest.fail(f"implementation missing: {CONFIG_PATH}")

    config = _read_yaml_mapping(CONFIG_PATH)
    assert config["spec_id"] == "r611q-package-v2-addendum-v1"
    assert config["spec_version"] == "1.0.3"
    assert config["output"]["package_id"] == "r611q-package-v2-addendum-2026-09-17"
    assert config["output"]["root_must_preexist"] is True
    assert tuple(config["output"]["external_artifacts"]) == EXPECTED_EXTERNAL_ARTIFACTS
    assert config["output"]["publication_protocol"] == EXPECTED_EXTERNAL_PUBLICATION_PROTOCOL
    assert config["output"]["repository_summary"]["publication_protocol"] == EXPECTED_SUMMARY_PUBLICATION_PROTOCOL


def test_r611q_pv2a_ac02_offline_static_import_boundary() -> None:
    if not PACKAGE_MODULE_PATH.is_file():
        pytest.fail(f"implementation missing: {PACKAGE_MODULE_PATH}")
    if not OPERATOR_SCRIPT_PATH.is_file():
        pytest.fail(f"implementation missing: {OPERATOR_SCRIPT_PATH}")

    for path in (PACKAGE_MODULE_PATH, OPERATOR_SCRIPT_PATH):
        imports = _import_names_for(path)
        for imported in imports:
            for forbidden in FORBIDDEN_IMPORT_PREFIXES:
                assert not (imported == forbidden or imported.startswith(f"{forbidden}.")), (
                    f"{path} imports forbidden dependency {imported}"
                )


def test_r611q_pv2a_ac03_v1_manifest_oracle_enforces_exact_pins_and_coverage() -> None:
    for pin in EXPECTED_REPO_V1_MANIFEST_PINS.values():
        _verify_manifest_file_set(pin["directory"], expected_manifest_pin=pin)


def test_r611q_pv2a_ac03_structure_manifest_lf_normalization_and_git_eol_contract() -> None:
    gitattributes_path = REPO_ROOT / ".gitattributes"
    assert gitattributes_path.is_file(), f"missing .gitattributes: {gitattributes_path}"
    lines = gitattributes_path.read_text(encoding="utf-8").splitlines()
    effective_lines = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]

    lf_rule_index = next(
        (
            index
            for index, line in enumerate(effective_lines)
            if line.startswith("data/rescuescreen/r611q/structure-readiness-v1/** ")
            and "text" in line.split()
            and "eol=lf" in line.split()
        ),
        None,
    )
    assert lf_rule_index is not None, "missing recursive LF rule for structure-readiness-v1/**"

    gzip_override_index = next(
        (
            index
            for index, line in enumerate(effective_lines)
            if line.startswith("data/rescuescreen/r611q/structure-readiness-v1/**/*.gz ")
            and ("-text" in line.split() or "binary" in line.split())
        ),
        None,
    )
    assert gzip_override_index is not None, "missing recursive gzip binary/-text override for structure-readiness-v1/**/*.gz"
    assert gzip_override_index > lf_rule_index, "gzip override must appear after recursive LF rule"

    manifest_entries = _parse_sha256_manifest(
        EXPECTED_REPO_V1_MANIFEST_PINS["structure-readiness-v1"]["directory"] / "manifest.sha256"
    )
    tracked_non_gzip = [
        f"data/rescuescreen/r611q/structure-readiness-v1/{relative_path}"
        for _, relative_path in manifest_entries
        if not relative_path.endswith(".gz")
    ]
    result = subprocess.run(
        ["git", "--no-pager", "ls-files", "--eol", "--", *tracked_non_gzip],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    rows = [line for line in result.stdout.splitlines() if line.strip()]
    observed_by_path: dict[str, str] = {}
    for row in rows:
        if "\t" not in row:
            continue
        _, path = row.split("\t", 1)
        observed_by_path[path] = row
    missing_paths = [path for path in tracked_non_gzip if path not in observed_by_path]
    assert not missing_paths, f"git ls-files --eol missing tracked paths: {missing_paths}"

    for path in tracked_non_gzip:
        meta = observed_by_path[path].split("\t", 1)[0]
        worktree_tokens = [token for token in meta.split() if token.startswith("w/")]
        assert worktree_tokens, f"unable to parse git --eol row for {path!r}: {observed_by_path[path]!r}"
        assert all(token != "w/crlf" for token in worktree_tokens), f"worktree CRLF forbidden for {path}: {observed_by_path[path]}"


def test_r611q_pv2a_ac03_manifest_parser_rejects_traversal_duplicate_and_unsorted(tmp_path: Path) -> None:
    good_dir = tmp_path / "bundle"
    good_dir.mkdir()
    (good_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
    (good_dir / "beta.txt").write_text("beta", encoding="utf-8")
    good_manifest = (
        f"{_sha256_file(good_dir / 'alpha.txt')}  alpha.txt\n"
        f"{_sha256_file(good_dir / 'beta.txt')}  beta.txt\n"
    )
    manifest_path = good_dir / "manifest.sha256"
    manifest_path.write_text(good_manifest, encoding="utf-8")
    _parse_sha256_manifest(manifest_path)

    bad_duplicate = (
        f"{_sha256_file(good_dir / 'alpha.txt')}  alpha.txt\n"
        f"{_sha256_file(good_dir / 'alpha.txt')}  alpha.txt\n"
    )
    manifest_path.write_text(bad_duplicate, encoding="utf-8")
    with pytest.raises(AssertionError):
        _parse_sha256_manifest(manifest_path)

    bad_unsorted = (
        f"{_sha256_file(good_dir / 'beta.txt')}  beta.txt\n"
        f"{_sha256_file(good_dir / 'alpha.txt')}  alpha.txt\n"
    )
    manifest_path.write_text(bad_unsorted, encoding="utf-8")
    with pytest.raises(AssertionError):
        _parse_sha256_manifest(manifest_path)

    bad_escape = f"{_sha256_file(good_dir / 'alpha.txt')}  ../escape.txt\n"
    manifest_path.write_text(bad_escape, encoding="utf-8")
    with pytest.raises(AssertionError):
        _parse_sha256_manifest(manifest_path)


def test_r611q_pv2a_ac03_oracle_manifest_verifier_never_writes_v1_files(monkeypatch: pytest.MonkeyPatch) -> None:
    protected_roots = tuple(pin["directory"].resolve() for pin in EXPECTED_REPO_V1_MANIFEST_PINS.values())
    real_open = builtins.open

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any):
        try:
            resolved = Path(file).resolve(strict=False)
        except TypeError:
            return real_open(file, mode, *args, **kwargs)

        if any(str(resolved).startswith(str(root)) for root in protected_roots):
            assert all(flag not in mode for flag in ("w", "a", "x", "+")), f"verifier attempted write mode {mode!r}"
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    for pin in EXPECTED_REPO_V1_MANIFEST_PINS.values():
        _verify_manifest_file_set(pin["directory"], expected_manifest_pin=pin)


def test_r611q_pv2a_ac04_pinned_readiness_summary_hash_and_length() -> None:
    _validate_pinned_file(
        EXPECTED_READINESS_SUMMARY_PIN["path"],
        expected_sha256=EXPECTED_READINESS_SUMMARY_PIN["sha256"],
        expected_byte_length=EXPECTED_READINESS_SUMMARY_PIN["byte_length"],
    )


def test_r611q_pv2a_ac04_external_packet_form_byte_validation_oracle(tmp_path: Path) -> None:
    packet_path = tmp_path / "packet_v1.md"
    form_path = tmp_path / "form_v1.yaml"
    packet_payload = b"# Synthetic packet v1\r\nLine two.\r\n"
    form_payload = b"variant: TSC2-R611Q\nclaims:\n  - claim_id: r611q-claim-0\n"
    packet_path.write_bytes(packet_payload)
    form_path.write_bytes(form_payload)

    _validate_pinned_file(
        packet_path,
        expected_sha256=_sha256_bytes(packet_payload),
        expected_byte_length=len(packet_payload),
    )
    _validate_pinned_file(
        form_path,
        expected_sha256=_sha256_bytes(form_payload),
        expected_byte_length=len(form_payload),
    )

    with pytest.raises(AssertionError):
        _validate_pinned_file(packet_path, expected_sha256="0" * 64, expected_byte_length=len(packet_payload))


def test_r611q_pv2a_ac05_delta_bundle_oracle_selects_exactly_one_semantic_boundary() -> None:
    manifest, artifacts, review_records, candidate_spans = _build_synthetic_delta_bundle()
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    _validate_delta_bundle_oracle(
        manifest,
        manifest_file_sha256=_sha256_bytes(manifest_bytes),
        manifest_byte_length=len(manifest_bytes),
        artifacts=artifacts,
    )

    selected = _select_boundary_record(review_records, candidate_spans)
    assert selected["claim_kind"] == "P_COMPLEX_BINDING"

    remapped_reviews = copy.deepcopy(review_records)
    remapped_spans = copy.deepcopy(candidate_spans)
    remapped_reviews[0]["candidate_id"] = "cand-remapped"
    remapped_spans[0]["candidate_id"] = "cand-remapped"
    remapped_reviews[0]["source_id"] = "source-remapped"
    remapped_spans[0]["source_id"] = "source-remapped"
    remapped_selected = _select_boundary_record(remapped_reviews, remapped_spans)
    assert remapped_selected["candidate_id"] == "cand-remapped"


def test_r611q_pv2a_ac05_delta_bundle_oracle_rejects_invalid_boundary_states() -> None:
    _, _, review_records, candidate_spans = _build_synthetic_delta_bundle()

    zero_match = copy.deepcopy(review_records)
    zero_match[0]["novelty"] = "KNOWN"
    with pytest.raises(AssertionError):
        _select_boundary_record(zero_match, candidate_spans)

    multiple_match = copy.deepcopy(review_records)
    extra = copy.deepcopy(multiple_match[0])
    extra["candidate_id"] = "cand-extra"
    extra["source_id"] = "source-extra"
    multiple_match.append(extra)
    extended_spans = copy.deepcopy(candidate_spans)
    span_extra = copy.deepcopy(extended_spans[0])
    span_extra["candidate_id"] = "cand-extra"
    span_extra["source_id"] = "source-extra"
    extended_spans.append(span_extra)
    with pytest.raises(AssertionError):
        _select_boundary_record(multiple_match, extended_spans)

    contradictory = copy.deepcopy(review_records)
    contradictory[0]["contradiction_state"] = "CONTRADICTS"
    with pytest.raises(AssertionError):
        _select_boundary_record(contradictory, candidate_spans)

    accepted = copy.deepcopy(review_records)
    accepted[0]["accepted_claim_count"] = 1
    with pytest.raises(AssertionError):
        _select_boundary_record(accepted, candidate_spans)

    gate_effect = copy.deepcopy(review_records)
    gate_effect[0]["gate_8_state"] = "SATISFIED"
    with pytest.raises(AssertionError):
        _select_boundary_record(gate_effect, candidate_spans)


def test_r611q_pv2a_selector_source_integrity_real_schema_does_not_require_record_quote_duplication() -> None:
    module = _require_package_v2_module()
    review_records, candidate_spans = _build_selector_identity_fixture(duplicate_record_quote_fields=False)
    selected = module.select_boundary_observation(review_records, candidate_spans)
    assert selected["candidate_id"] == candidate_spans[0]["candidate_id"]
    assert selected["source_id"] == candidate_spans[0]["source_id"]
    assert selected["article_identity"] == candidate_spans[0]["article_identity"]
    assert selected["locator"] == candidate_spans[0]["locator"]
    assert selected["quote_sha256"] == candidate_spans[0]["exact_quote_sha256"]


def test_r611q_pv2a_selector_source_integrity_rejects_article_identity_mismatch_despite_matching_candidate_id() -> None:
    module = _require_package_v2_module()
    selector_error = _selector_error_type_from_module(module)
    review_records, candidate_spans = _build_selector_identity_fixture(duplicate_record_quote_fields=True)
    review_records[0]["article_identity"] = {"pmid": "22222222", "pmcid": "PMC2222222", "doi": "10.0000/mismatch"}
    with pytest.raises(selector_error):
        module.select_boundary_observation(review_records, candidate_spans)


def test_r611q_pv2a_selector_source_integrity_rejects_source_id_not_canonical_for_article_identity() -> None:
    module = _require_package_v2_module()
    selector_error = _selector_error_type_from_module(module)
    review_records, candidate_spans = _build_selector_identity_fixture(duplicate_record_quote_fields=True)
    noncanonical = "PMCID:PMC9000001"
    review_records[0]["source_id"] = noncanonical
    candidate_spans[0]["source_id"] = noncanonical
    with pytest.raises(selector_error):
        module.select_boundary_observation(review_records, candidate_spans)


def test_r611q_pv2a_selector_source_integrity_rejects_source_mismatch() -> None:
    module = _require_package_v2_module()
    selector_error = _selector_error_type_from_module(module)
    review_records, candidate_spans = _build_selector_identity_fixture(duplicate_record_quote_fields=True)
    review_records[0]["source_id"] = "PMID:88888888"
    with pytest.raises(selector_error):
        module.select_boundary_observation(review_records, candidate_spans)


@pytest.mark.parametrize("missing_field", ["candidate_id", "source_id", "article_identity"])
def test_r611q_pv2a_selector_source_integrity_rejects_missing_record_identity(
    missing_field: str,
) -> None:
    module = _require_package_v2_module()
    selector_error = _selector_error_type_from_module(module)
    review_records, candidate_spans = _build_selector_identity_fixture(duplicate_record_quote_fields=True)
    if missing_field == "article_identity":
        review_records[0][missing_field] = {}
    else:
        review_records[0].pop(missing_field, None)
    with pytest.raises(selector_error):
        module.select_boundary_observation(review_records, candidate_spans)


def test_r611q_pv2a_selector_source_integrity_rejects_duplicate_candidate_spans() -> None:
    module = _require_package_v2_module()
    selector_error = _selector_error_type_from_module(module)
    review_records, candidate_spans = _build_selector_identity_fixture(duplicate_record_quote_fields=True)
    candidate_spans.append(copy.deepcopy(candidate_spans[0]))
    with pytest.raises(selector_error):
        module.select_boundary_observation(review_records, candidate_spans)


def test_r611q_pv2a_selector_source_integrity_rejects_candidate_quote_hash_mismatch() -> None:
    module = _require_package_v2_module()
    selector_error = _selector_error_type_from_module(module)
    review_records, candidate_spans = _build_selector_identity_fixture(duplicate_record_quote_fields=True)
    tampered_hash = "f" * 64
    candidate_spans[0]["exact_quote_sha256"] = tampered_hash
    candidate_spans[0]["quote_sha256"] = tampered_hash
    review_records[0]["quote_sha256"] = tampered_hash
    with pytest.raises(selector_error):
        module.select_boundary_observation(review_records, candidate_spans)


@pytest.mark.parametrize(
    "state_value",
    ["ACCEPTED", "ACCEPTED_WITH_NARROWER_WORDING", "REJECTED", "PENDING", None, "__MISSING__"],
)
def test_r611q_pv2a_selector_acceptance_boundary_rejects_non_unaccepted_states(state_value: Any) -> None:
    module = _require_package_v2_module()
    selector_error = _selector_error_type_from_module(module)
    review_records, candidate_spans = _build_selector_identity_fixture(duplicate_record_quote_fields=True)
    if state_value == "__MISSING__":
        review_records[0].pop("acceptance_state", None)
    else:
        review_records[0]["acceptance_state"] = state_value
    with pytest.raises(selector_error):
        module.select_boundary_observation(review_records, candidate_spans)


@pytest.mark.parametrize("gate_effect_value", ["SATISFIES", "BLOCKED_HUMAN_REVIEW", "", None])
def test_r611q_pv2a_selector_acceptance_boundary_rejects_non_none_gate_effects(
    gate_effect_value: Any,
) -> None:
    module = _require_package_v2_module()
    selector_error = _selector_error_type_from_module(module)
    review_records, candidate_spans = _build_selector_identity_fixture(duplicate_record_quote_fields=True)
    review_records[0]["gate_effect"] = gate_effect_value
    with pytest.raises(selector_error):
        module.select_boundary_observation(review_records, candidate_spans)


def test_r611q_pv2a_ac06_packet_v2_composition_keeps_exact_prefix_and_boundary_language() -> None:
    _, _, review_records, candidate_spans = _build_synthetic_delta_bundle()
    boundary = _select_boundary_record(review_records, candidate_spans)

    packet_v1 = b"# Packet V1\r\nLine one with spacing.  \r\nLine two.\r\n"
    packet_v2 = _compose_packet_v2(packet_v1, boundary_record=boundary)
    assert packet_v2.startswith(packet_v1), "packet v2 must begin with exact v1 packet bytes"

    text = packet_v2.decode("utf-8")
    assert "r611q-claim-2" in text
    assert "R611Q/R905Q/N1620S" in text
    assert "HEK293T" in text
    assert "tagged-overexpression" in text
    assert "co-immunoprecipitation" in text
    assert "no observed effect" not in text  # prevent direct quote copy from source artifact
    assert "allele-specific magnitude" in text
    assert "TSC2-TSC2" in text
    assert "does not establish preserved TSC1 binding" in text
    assert "NARROWS" in text and "CONTRADICTS" not in text
    assert "PROPOSED_UNACCEPTED" in text
    assert "accepted_claims=0" in text
    assert "BLOCKED_HUMAN_REVIEW" in text


def test_r611q_pv2a_ac07_form_v2_parsing_preserves_v1_and_appends_claim2() -> None:
    form_v1 = {
        "variant": {"gene": "TSC2", "protein": "p.Arg611Gln"},
        "bindings": {"packet_id": "packet-v1-synth", "form_schema": "atlas.expert_review_form.v1"},
        "reviewer": {"assigned_to": "reviewer-synth"},
        "scope": "boundary-only",
        "claims": [
            {"claim_id": "r611q-claim-0", "decision": None, "decision_options": list(ALLOWED_DECISIONS)},
            {"claim_id": "r611q-claim-1", "decision": None, "decision_options": list(ALLOWED_DECISIONS)},
        ],
        "packet_status": "UNREVIEWED",
        "accepted_claim_count": 0,
        "gate_8_state": "BLOCKED_HUMAN_REVIEW",
    }
    form_v1_bytes = yaml.safe_dump(form_v1, sort_keys=False, allow_unicode=True).encode("utf-8")
    form_v2 = _build_form_v2(
        form_v1_bytes,
        base_packet_sha256="a" * 64,
        delta_manifest_hash="b" * 64,
    )
    _assert_form_v2_preserves_v1(form_v1, form_v2)


def test_r611q_pv2a_ac07_form_v2_rejects_mutated_original_claims() -> None:
    form_v1 = {
        "variant": {"gene": "TSC2", "protein": "p.Arg611Gln"},
        "bindings": {"packet_id": "packet-v1-synth", "form_schema": "atlas.expert_review_form.v1"},
        "reviewer": {"assigned_to": "reviewer-synth"},
        "scope": "boundary-only",
        "claims": [
            {"claim_id": "r611q-claim-0", "decision": None, "decision_options": list(ALLOWED_DECISIONS)},
            {"claim_id": "r611q-claim-1", "decision": None, "decision_options": list(ALLOWED_DECISIONS)},
        ],
        "packet_status": "UNREVIEWED",
        "accepted_claim_count": 0,
        "gate_8_state": "BLOCKED_HUMAN_REVIEW",
    }
    form_v1_bytes = yaml.safe_dump(form_v1, sort_keys=False, allow_unicode=True).encode("utf-8")
    form_v2 = _build_form_v2(
        form_v1_bytes,
        base_packet_sha256="a" * 64,
        delta_manifest_hash="b" * 64,
    )
    form_v2["claims"][1]["decision_options"] = ["tampered"]
    with pytest.raises(AssertionError):
        _assert_form_v2_preserves_v1(form_v1, form_v2)


def test_r611q_pv2a_ac08_impact_record_oracle_preserves_boundaries() -> None:
    impact = {
        "literature_v1": "IMMUTABLE",
        "synthesis_v1": "IMMUTABLE",
        "structure_readiness_v1": "IMMUTABLE",
        "route_effect": {"RH-2": "PLAUSIBLE_NOT_DEMONSTRATED"},
        "coip_interpretation": "TSC2-TSC2_NON_DISCRIMINATING",
        "assay_falsifier": {"AF-4": "TSC1-TSC2_WITH_MATCHED_ABUNDANCE"},
        "model_contexts": {"count": 4, "package_effect": "CONTEXT_ONLY"},
        "clinical_occurrences": {"count": 2, "package_effect": "OCCURRENCE_ONLY"},
        "secondary_reviews": {"count": 3, "package_effect": "NO_PROPOSITION_SUPPORT"},
        "contradictions": 0,
        "stage_execution_authorized": False,
        "historical_4169_expansion": False,
    }
    _validate_impact_record_oracle(impact)


def test_r611q_pv2a_ac09_external_package_render_oracle_self_hashes_and_manifest_last(tmp_path: Path) -> None:
    output_root = (tmp_path / "external").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "R611Q_EXPERT_REVIEW_PACKET_V2.md": b"# packet v2\n",
        "R611Q_EXPERT_REVIEW_FORM_V2.yaml": b"schema: atlas.expert_review_form.v2\n",
        "R611Q_PACKAGE_V2_IMPACT.json": b"{\"impact\":\"bounded\"}\n",
        "R611Q_PACKAGE_V2_SUMMARY.md": b"# summary\n",
    }
    package_dir, written_order = _render_external_package_oracle(
        output_root,
        package_id="r611q-package-v2-addendum-2026-09-17",
        repository_summary_target="data/rescuescreen/r611q/package-v2-addendum",
        artifacts=artifacts,
    )
    assert written_order == EXPECTED_EXTERNAL_ARTIFACTS
    for name in EXPECTED_EXTERNAL_ARTIFACTS:
        assert (package_dir / name).is_file(), f"missing external artifact {name}"

    manifest = json.loads((package_dir / "package_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == PACKAGE_MANIFEST_SCHEMA
    assert manifest["manifest_content_hash"] == _canonical_json_hash(manifest, drop_field="manifest_content_hash")


def test_r611q_pv2a_ac10_repository_summary_oracle_stays_aggregate_only() -> None:
    summary, readme = _derive_repository_summary_oracle(
        input_hashes={
            "literature_manifest_sha256": "1" * 64,
            "synthesis_manifest_sha256": "2" * 64,
            "structure_manifest_sha256": "3" * 64,
            "delta_manifest_sha256": "4" * 64,
        },
        output_hashes={
            "packet_v2_sha256": "5" * 64,
            "form_v2_sha256": "6" * 64,
            "impact_sha256": "7" * 64,
            "summary_sha256": "8" * 64,
        },
        accepted_claim_count=0,
        gate_8_state="BLOCKED_HUMAN_REVIEW",
        stage_execution_authorized=False,
    )
    assert summary["counts"]["accepted_claims"] == 0
    assert summary["state"]["gate_8"] == "BLOCKED_HUMAN_REVIEW"
    assert summary["state"]["stage_execution_authorized"] is False
    assert "aggregate-only" in readme.lower()


def test_r611q_pv2a_ac11_pilot_repo_summary_files_exist_then_pin_aggregate_only_contract() -> None:
    if not PILOT_SUMMARY_JSON_PATH.is_file() or not PILOT_SUMMARY_README_PATH.is_file():
        pytest.fail(
            "pilot regression RED by design: missing "
            "data/rescuescreen/r611q/package-v2-addendum/package_summary.json and/or README.md"
        )

    summary = json.loads(PILOT_SUMMARY_JSON_PATH.read_text(encoding="utf-8"))
    readme = PILOT_SUMMARY_README_PATH.read_text(encoding="utf-8")
    text = json.dumps(summary, sort_keys=True).lower() + "\n" + readme.lower()
    forbidden = ("pmid", "pmcid", "doi", "title", "candidate_id", "locator", "patient")
    assert all(token not in text for token in forbidden), "repository summary leaked source identity content"


def test_r611q_pv2a_ac12_required_package_api_surface_for_end_to_end_operator() -> None:
    _require_package_v2_module()


def test_r611q_pv2a_ac12_operator_synthetic_end_to_end_contract(tmp_path: Path) -> None:
    if not OPERATOR_SCRIPT_PATH.is_file():
        pytest.fail(f"implementation missing: {OPERATOR_SCRIPT_PATH}")

    synthetic_config = tmp_path / "synthetic_config.yaml"
    synthetic_config.write_text(
        yaml.safe_dump(
            {
                "spec_id": "r611q-package-v2-addendum-v1",
                "spec_version": "1.0.3",
                "output": {
                    "package_id": "r611q-package-v2-addendum-2026-09-17",
                    "root_must_preexist": True,
                    "external_artifacts": list(EXPECTED_EXTERNAL_ARTIFACTS),
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    out_root = tmp_path / "external-out"
    out_root.mkdir(parents=True, exist_ok=True)
    summary_root = tmp_path / "repo-summary-out"

    run = subprocess.run(
        [
            sys.executable,
            str(OPERATOR_SCRIPT_PATH),
            "--config",
            str(synthetic_config),
            "--output-root",
            str(out_root),
            "--repository-summary-dir",
            str(summary_root),
            "--offline",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    assert run.returncode == 0, run.stderr or run.stdout


def test_r611q_pv2a_publication_rejects_absent_external_root_before_any_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (
        module,
        fixture,
        config_path,
        summary_dir,
        summary_json_path,
        summary_readme_path,
        repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    output_root = (tmp_path / "absent-external-root").resolve()
    package_dir = output_root / package_id
    assert not output_root.exists()

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert not output_root.exists(), "root_must_preexist requires rejecting absent output root before any write"
    assert not package_dir.exists(), "final external package must not be created when output root is absent"
    assert not summary_dir.exists(), "summary directory must not be created when output root precheck fails"
    assert not summary_json_path.exists()
    assert not summary_readme_path.exists()


def test_r611q_pv2a_publication_external_root_descriptor_race_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _require_package_v2_module()
    publish_seam = getattr(module, "_publish_directory_no_replace", None)
    assert callable(publish_seam), "render_external_package must publish through _publish_directory_no_replace"

    output_root = (tmp_path / "external-root").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    package_id = "r611q-package-v2-addendum-2026-09-17"
    package_dir = output_root / package_id
    attacker_target = (tmp_path / "attacker-external-target").resolve()
    attacker_target.mkdir(parents=True, exist_ok=True)

    symlink_probe = tmp_path / "root-race-symlink-probe"
    try:
        symlink_probe.symlink_to(attacker_target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable in this environment")
    finally:
        if symlink_probe.is_symlink():
            symlink_probe.unlink()

    artifacts = {
        "R611Q_EXPERT_REVIEW_PACKET_V2.md": b"# packet\n",
        "R611Q_EXPERT_REVIEW_FORM_V2.yaml": b"schema: atlas.expert_review_form.v2\n",
        "R611Q_PACKAGE_V2_IMPACT.json": b"{\"impact\":\"bounded\"}\n",
        "R611Q_PACKAGE_V2_SUMMARY.md": b"# summary\n",
    }

    real_open = module.os.open
    real_rmdir = module.os.rmdir
    injected = {"done": False}

    def swap_root_after_descriptor_open(path: Any, flags: int, *args: Any, **kwargs: Any):
        try:
            candidate = Path(path)
        except TypeError:
            return real_open(path, flags, *args, **kwargs)
        required_flags = module.os.O_RDONLY | module.os.O_DIRECTORY | module.os.O_NOFOLLOW
        if (
            not injected["done"]
            and kwargs.get("dir_fd") is None
            and candidate == output_root
            and (flags & required_flags) == required_flags
        ):
            fd = real_open(path, flags, *args, **kwargs)
            assert not any(output_root.iterdir()), "output root must be pinned before staging/final creation"
            real_rmdir(path)
            candidate.symlink_to(attacker_target, target_is_directory=True)
            injected["done"] = True
            return fd
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", swap_root_after_descriptor_open)

    with pytest.raises((module.PackageV2Error, OSError)):
        module.render_external_package(
            output_root,
            package_id=package_id,
            repository_summary_target="data/rescuescreen/r611q/package-v2-addendum",
            artifacts=artifacts,
        )

    assert injected["done"], "test must inject the output-root descriptor race"
    assert output_root.is_symlink(), "racing symlink must remain untouched on failure"
    assert output_root.resolve() == attacker_target
    assert not (attacker_target / package_id).exists(), "attacker target must not receive final package content"
    assert list(attacker_target.rglob("*")) == [], "attacker target must remain empty"
    assert not list(attacker_target.glob(f".{package_id}.staging-*")), "no staging content may leak to attacker target"


def test_r611q_pv2a_publication_summary_final_dir_descriptor_race_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        module,
        fixture,
        config_path,
        summary_dir,
        summary_json_path,
        summary_readme_path,
        repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    output_root = (tmp_path / "external-outside").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    package_dir = output_root / package_id
    attacker_target = (tmp_path / "attacker-summary-target").resolve()
    attacker_target.mkdir(parents=True, exist_ok=True)
    assert not summary_dir.exists()

    symlink_probe = tmp_path / "summary-race-symlink-probe"
    try:
        symlink_probe.symlink_to(attacker_target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable in this environment")
    finally:
        if symlink_probe.is_symlink():
            symlink_probe.unlink()

    real_open = module.os.open
    injected = {"done": False}

    def swap_summary_dir_after_open(path: Any, flags: int, *args: Any, **kwargs: Any):
        dir_fd = kwargs.get("dir_fd")
        try:
            name = Path(path).name
        except TypeError:
            return real_open(path, flags, *args, **kwargs)
        required_flags = module.os.O_RDONLY | module.os.O_DIRECTORY | module.os.O_NOFOLLOW
        if (
            not injected["done"]
            and dir_fd is not None
            and name == "package-v2-addendum"
            and (flags & required_flags) == required_flags
        ):
            fd = real_open(path, flags, *args, **kwargs)
            module.os.rmdir(path, dir_fd=dir_fd)
            summary_dir.symlink_to(attacker_target, target_is_directory=True)
            injected["done"] = True
            return fd
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", swap_summary_dir_after_open)

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
    )
    captured = capsys.readouterr()

    assert injected["done"], "test must inject the summary final-directory descriptor race"
    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert summary_dir.is_symlink(), "racing summary symlink should remain untouched"
    assert summary_dir.resolve() == attacker_target
    assert not summary_json_path.exists(), "summary JSON must not be written through symlink-swapped directory"
    assert not summary_readme_path.exists(), "summary README must not be written through symlink-swapped directory"
    assert list(attacker_target.rglob("*")) == [], "attacker summary target must remain empty"
    assert not package_dir.exists(), "external package must not be published after summary race failure"


def test_r611q_pv2a_publication_render_fails_closed_without_descriptor_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _require_package_v2_module()
    output_root = (tmp_path / "external-root").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    package_id = "r611q-package-v2-addendum-2026-09-17"
    package_dir = output_root / package_id
    artifacts = {
        "R611Q_EXPERT_REVIEW_PACKET_V2.md": b"# packet\n",
        "R611Q_EXPERT_REVIEW_FORM_V2.yaml": b"schema: atlas.expert_review_form.v2\n",
        "R611Q_PACKAGE_V2_IMPACT.json": b"{\"impact\":\"bounded\"}\n",
        "R611Q_PACKAGE_V2_SUMMARY.md": b"# summary\n",
    }

    monkeypatch.setattr(module.os, "supports_dir_fd", ())
    with pytest.raises(module.PackageV2Error) as excinfo:
        module.render_external_package(
            output_root,
            package_id=package_id,
            repository_summary_target="data/rescuescreen/r611q/package-v2-addendum",
            artifacts=artifacts,
        )
    message = str(excinfo.value)
    assert "refusing to fall back to path-based writes" in message
    assert not package_dir.exists(), "fail-closed descriptor capability check must prevent final package creation"
    assert not list(output_root.glob(f".{package_id}.staging-*")), "staging must be cleaned on fail-closed rejection"


def test_r611q_pv2a_publication_preexisting_summary_fails_before_external_creation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (
        module,
        fixture,
        config_path,
        _summary_dir,
        summary_json_path,
        _summary_readme_path,
        _repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.write_text("{\"preexisting\":true}\n", encoding="utf-8")

    output_root = (tmp_path / "external-outside").resolve()
    package_dir = output_root / package_id

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=fixture.repo_root.resolve(),
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert not package_dir.exists(), "external package must not be created before summary create-only preflight"


@pytest.mark.parametrize(
    "summary_dir_builder",
    ["inside-repo-alternate", "outside-repo"],
)
def test_r611q_pv2a_publication_repository_summary_dir_must_match_configured_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    summary_dir_builder: str,
) -> None:
    (
        module,
        fixture,
        config_path,
        expected_summary_dir,
        _summary_json_path,
        _summary_readme_path,
        repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    output_root = (tmp_path / "external-outside").resolve()
    package_dir = output_root / package_id

    if summary_dir_builder == "inside-repo-alternate":
        repository_summary_dir = (repo_root / "data" / "rescuescreen" / "r611q" / "alternate-summary-target").resolve()
    else:
        repository_summary_dir = (tmp_path / "outside-summary-target").resolve()
    assert repository_summary_dir != expected_summary_dir

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
        repository_summary_dir=repository_summary_dir,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert not package_dir.exists(), "external package must not be published when repository-summary-dir is non-canonical"


def test_r611q_pv2a_publication_external_output_root_must_resolve_outside_repo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (
        module,
        fixture,
        config_path,
        _summary_dir,
        _summary_json_path,
        _summary_readme_path,
        repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    output_root = (repo_root / "external-package-under-repo-root").resolve()
    package_dir = output_root / package_id

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert not package_dir.exists(), "external package root inside repo must be rejected before publication"


def test_r611q_pv2a_publication_summary_create_only_is_atomic_and_sanitized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        module,
        fixture,
        config_path,
        _summary_dir,
        summary_json_path,
        summary_readme_path,
        repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    output_root = (tmp_path / "external-outside").resolve()
    package_dir = output_root / package_id

    real_write_text = Path.write_text
    target_readme = summary_readme_path.resolve()

    def fail_second_summary_write(path_obj: Path, text: str, *args: Any, **kwargs: Any) -> int:
        candidate = Path(path_obj).resolve()
        if candidate == target_readme:
            raise module.PackageV2Error("simulated second-file write failure")
        return int(real_write_text(path_obj, text, *args, **kwargs))

    monkeypatch.setattr(Path, "write_text", fail_second_summary_write)

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert not summary_json_path.exists(), "summary publication must be all-or-nothing on second-file write failure"
    assert not summary_readme_path.exists(), "summary publication must be all-or-nothing on second-file write failure"
    assert not package_dir.exists(), "external package must not be finalized when summary publication is interrupted"


def test_r611q_pv2a_publication_rolls_back_summary_when_external_render_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        module,
        fixture,
        config_path,
        summary_dir,
        summary_json_path,
        summary_readme_path,
        repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    output_root = (tmp_path / "external-outside").resolve()
    package_dir = output_root / package_id
    assert not summary_dir.exists(), "test fixture expects summary directory to be create-on-run"

    def fail_render_after_summary(*args: Any, **kwargs: Any):
        raise module.PackageV2Error("simulated external render failure after summary publication")

    monkeypatch.setattr(module, "render_external_package", fail_render_after_summary)

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert not package_dir.exists(), "external package must not exist on render failure"
    assert not summary_json_path.exists(), "summary JSON must be rolled back when external render fails"
    assert not summary_readme_path.exists(), "summary README must be rolled back when external render fails"
    assert not summary_dir.exists(), "newly created summary directory must be removed on second-phase failure"


def test_r611q_pv2a_publication_no_replace_race_preserves_racing_directory_on_finalize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _require_package_v2_module()
    output_root = (tmp_path / "external-root").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    package_id = "r611q-package-v2-addendum-2026-09-17"
    package_dir = output_root / package_id

    artifacts = {
        "R611Q_EXPERT_REVIEW_PACKET_V2.md": b"# packet\n",
        "R611Q_EXPERT_REVIEW_FORM_V2.yaml": b"schema: atlas.expert_review_form.v2\n",
        "R611Q_PACKAGE_V2_IMPACT.json": b"{\"impact\":\"bounded\"}\n",
        "R611Q_PACKAGE_V2_SUMMARY.md": b"# summary\n",
    }

    publish_seam = getattr(module, "_publish_directory_no_replace", None)
    assert callable(publish_seam), (
        "render_external_package must use an explicit no-replace publish seam "
        "such as _publish_directory_no_replace(staging_dir, destination_dir)"
    )

    real_mkdir = module.os.mkdir
    race_inode: dict[str, int] = {}
    race_injected = {"done": False}

    def race_on_destination_claim(path: Any, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
        path_str = os.fsdecode(path) if isinstance(path, (bytes, bytearray)) else str(path)
        path_obj = Path(path_str)
        is_legacy_claim = dir_fd is None and path_obj == package_dir
        is_descriptor_relative_claim = dir_fd is not None and path_str == package_id
        if (is_legacy_claim or is_descriptor_relative_claim) and not race_injected["done"]:
            # Simulate an external racer claiming destination first:
            # create empty destination with a real mkdir and then force the
            # production destination-claim call to receive FileExistsError.
            if dir_fd is None:
                real_mkdir(path, mode)
            else:
                real_mkdir(path, mode, dir_fd=dir_fd)
            inode_stat = (
                module.os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
                if dir_fd is not None
                else module.os.stat(path, follow_symlinks=False)
            )
            race_inode["value"] = inode_stat.st_ino
            race_injected["done"] = True
            if dir_fd is None:
                real_mkdir(path, mode)  # raises FileExistsError on POSIX/WSL
            else:
                real_mkdir(path, mode, dir_fd=dir_fd)  # raises FileExistsError on POSIX/WSL
            return
        if dir_fd is None:
            real_mkdir(path, mode)
        else:
            real_mkdir(path, mode, dir_fd=dir_fd)

    def forbid_rename(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("render_external_package must not use os.rename for no-replace destination claim")

    monkeypatch.setattr(module.os, "mkdir", race_on_destination_claim)
    monkeypatch.setattr(module.os, "rename", forbid_rename)

    with pytest.raises((module.PackageV2Error, FileExistsError)):
        module.render_external_package(
            output_root,
            package_id=package_id,
            repository_summary_target="data/rescuescreen/r611q/package-v2-addendum",
            artifacts=artifacts,
        )

    assert race_injected["done"], "test must inject the destination-claim race at final package directory"
    assert package_dir.exists(), "racing directory must remain present"
    assert package_dir.is_dir(), "racing path must stay a directory"
    assert package_dir.stat().st_ino == race_inode["value"], "racing directory must not be replaced"
    assert list(package_dir.iterdir()) == [], "racing directory must remain untouched and empty"


def test_r611q_pv2a_publication_symlink_ancestry_rejected_for_output_and_summary_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (
        module,
        fixture,
        config_path,
        summary_dir,
        summary_json_path,
        summary_readme_path,
        repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)

    outside_target = (tmp_path / "outside-target").resolve()
    outside_target.mkdir(parents=True, exist_ok=True)
    output_link = tmp_path / "output-root-symlink"
    summary_ancestor_link = repo_root / "data-symlink"
    try:
        output_link.symlink_to(outside_target, target_is_directory=True)
        summary_ancestor_link.symlink_to(repo_root / "data", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable in this environment")

    supplied_summary_dir = summary_ancestor_link / "rescuescreen" / "r611q" / "package-v2-addendum"
    package_dir = outside_target / package_id
    assert supplied_summary_dir.resolve() == summary_dir.resolve(), "symlinked summary path must resolve to canonical target"

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_link,
        repository_summary_dir=supplied_summary_dir,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert not package_dir.exists(), "symlinked output-root ancestry must be rejected before external publication"
    assert not summary_json_path.exists(), "symlinked summary path ancestry must be rejected before summary publication"
    assert not summary_readme_path.exists(), "symlinked summary path ancestry must be rejected before summary publication"


def test_r611q_pv2a_publication_rejects_post_claim_symlink_swap_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _require_package_v2_module()
    publish_seam = getattr(module, "_publish_directory_no_replace", None)
    assert callable(publish_seam), "render_external_package must publish through _publish_directory_no_replace"

    output_root = (tmp_path / "external-root").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    package_id = "r611q-package-v2-addendum-2026-09-17"
    package_dir = output_root / package_id
    attacker_target = (tmp_path / "attacker-outside-target").resolve()
    attacker_target.mkdir(parents=True, exist_ok=True)

    probe_link = tmp_path / "symlink-probe"
    try:
        probe_link.symlink_to(attacker_target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable in this environment")
    finally:
        if probe_link.is_symlink():
            probe_link.unlink()

    artifacts = {
        "R611Q_EXPERT_REVIEW_PACKET_V2.md": b"# packet\n",
        "R611Q_EXPERT_REVIEW_FORM_V2.yaml": b"schema: atlas.expert_review_form.v2\n",
        "R611Q_PACKAGE_V2_IMPACT.json": b"{\"impact\":\"bounded\"}\n",
        "R611Q_PACKAGE_V2_SUMMARY.md": b"# summary\n",
    }

    real_mkdir = module.os.mkdir
    real_rmdir = module.os.rmdir
    injected = {"done": False}

    real_symlink = module.os.symlink

    def swap_destination_to_symlink(path: Any, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
        path_str = os.fsdecode(path) if isinstance(path, (bytes, bytearray)) else str(path)
        path_obj = Path(path_str)
        is_legacy_claim = dir_fd is None and path_obj == package_dir
        is_descriptor_relative_claim = dir_fd is not None and path_str == package_id
        if (is_legacy_claim or is_descriptor_relative_claim) and not injected["done"]:
            # Simulate winning the race immediately after destination claim:
            # claim destination, replace with attacker symlink, then return.
            if dir_fd is None:
                real_mkdir(path, mode)
                real_rmdir(path)
                path_obj.symlink_to(attacker_target, target_is_directory=True)
            else:
                real_mkdir(path, mode, dir_fd=dir_fd)
                real_rmdir(path, dir_fd=dir_fd)
                real_symlink(str(attacker_target), path, target_is_directory=True, dir_fd=dir_fd)
            injected["done"] = True
            return
        if dir_fd is None:
            real_mkdir(path, mode)
        else:
            real_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "mkdir", swap_destination_to_symlink)

    with pytest.raises((module.PackageV2Error, OSError)):
        module.render_external_package(
            output_root,
            package_id=package_id,
            repository_summary_target="data/rescuescreen/r611q/package-v2-addendum",
            artifacts=artifacts,
        )

    assert injected["done"], "test must inject a post-claim symlink swap on destination mkdir claim"
    assert package_dir.is_symlink(), "racing destination symlink should remain untouched by failed publication"
    assert package_dir.resolve() == attacker_target, "racing symlink target should remain attacker-controlled"
    assert list(attacker_target.rglob("*")) == [], "failed publication must not materialize payload/manifest in attacker target"
    assert not list(output_root.glob(f".{package_id}.staging-*")), "staging directories must be cleaned on publication failure"


@pytest.mark.parametrize(
    ("label", "package_id_template"),
    [
        ("absolute_posix", "{ABS}/outside-package"),
        ("dotdot", ".."),
        ("dot", "."),
        ("nested_slash", "nested/package"),
        ("backslash", "nested\\package"),
        ("drive_colon", "C:package"),
        ("nul", "bad\x00package"),
        ("leading_whitespace", " package"),
        ("trailing_whitespace", "package "),
    ],
)
def test_r611q_pv2a_descriptor_relative_escape_render_rejects_unsafe_package_id(
    tmp_path: Path,
    label: str,
    package_id_template: str,
) -> None:
    module = _require_package_v2_module()
    output_root = (tmp_path / f"external-root-{label}").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    outside_abs_root = (tmp_path / "outside-absolute-target").resolve()
    package_id = package_id_template.replace("{ABS}", outside_abs_root.as_posix())

    artifacts = {
        "R611Q_EXPERT_REVIEW_PACKET_V2.md": b"# packet\n",
        "R611Q_EXPERT_REVIEW_FORM_V2.yaml": b"schema: atlas.expert_review_form.v2\n",
        "R611Q_PACKAGE_V2_IMPACT.json": b"{\"impact\":\"bounded\"}\n",
        "R611Q_PACKAGE_V2_SUMMARY.md": b"# summary\n",
    }

    with pytest.raises(module.PackageV2Error):
        module.render_external_package(
            output_root,
            package_id=package_id,
            repository_summary_target="data/rescuescreen/r611q/package-v2-addendum",
            artifacts=artifacts,
        )

    assert not outside_abs_root.exists(), "unsafe absolute package_id must not create an outside directory"
    assert not any(output_root.iterdir()), "unsafe package_id must be rejected before external publication writes"


@pytest.mark.parametrize(
    ("label", "bad_package_id_template"),
    [
        ("absolute_posix", "{ABS}/outside-package"),
        ("dotdot", ".."),
        ("dot", "."),
        ("nested_slash", "nested/package"),
        ("backslash", "nested\\package"),
        ("drive_colon", "C:package"),
        ("nul", "bad\x00package"),
        ("leading_whitespace", " package"),
        ("trailing_whitespace", "package "),
    ],
)
def test_r611q_pv2a_descriptor_relative_escape_operator_rejects_unsafe_package_id_before_publication(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    bad_package_id_template: str,
) -> None:
    (
        module,
        fixture,
        config_path,
        summary_dir,
        summary_json_path,
        summary_readme_path,
        repo_root,
        _package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    output_root = (tmp_path / f"external-outside-{label}").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    outside_abs_root = (tmp_path / "outside-absolute-target").resolve()
    bad_package_id = bad_package_id_template.replace("{ABS}", outside_abs_root.as_posix())

    config = _read_yaml_mapping(config_path)
    config["output"]["package_id"] = bad_package_id
    _write_operator_config(config_path, config)
    called = _install_publication_call_guards(module, monkeypatch)

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert not called["summary_publish"], "unsafe package_id must fail before summary publication path"
    assert not called["external_render"], "unsafe package_id must fail before external publication path"
    assert not outside_abs_root.exists(), "unsafe package_id must not create outside directories"
    assert not summary_dir.exists(), "unsafe package_id must fail before summary directory creation"
    assert not summary_json_path.exists()
    assert not summary_readme_path.exists()
    assert not any(output_root.iterdir()), "unsafe package_id must fail before external output writes"


@pytest.mark.parametrize(
    ("label", "directory_value", "json_path_value", "readme_path_value"),
    [
        (
            "directory_absolute",
            "{ABS}/summary-out",
            "{ABS}/summary-out/package_summary.json",
            "{ABS}/summary-out/README.md",
        ),
        (
            "directory_empty_component",
            "data/rescuescreen/r611q//package-v2-addendum",
            "data/rescuescreen/r611q//package-v2-addendum/package_summary.json",
            "data/rescuescreen/r611q//package-v2-addendum/README.md",
        ),
        (
            "directory_dot_component",
            "data/rescuescreen/r611q/./package-v2-addendum",
            "data/rescuescreen/r611q/./package-v2-addendum/package_summary.json",
            "data/rescuescreen/r611q/./package-v2-addendum/README.md",
        ),
        (
            "directory_dotdot_component",
            "data/rescuescreen/r611q/../package-v2-addendum",
            "data/rescuescreen/r611q/../package-v2-addendum/package_summary.json",
            "data/rescuescreen/r611q/../package-v2-addendum/README.md",
        ),
        (
            "directory_backslash",
            "data\\rescuescreen\\r611q\\package-v2-addendum",
            "data\\rescuescreen\\r611q\\package-v2-addendum\\package_summary.json",
            "data\\rescuescreen\\r611q\\package-v2-addendum\\README.md",
        ),
        (
            "directory_drive_colon",
            "C:/rescuescreen/r611q/package-v2-addendum",
            "C:/rescuescreen/r611q/package-v2-addendum/package_summary.json",
            "C:/rescuescreen/r611q/package-v2-addendum/README.md",
        ),
        (
            "directory_nul",
            "data/rescuescreen/r611q/package-v2-\x00addendum",
            "data/rescuescreen/r611q/package-v2-\x00addendum/package_summary.json",
            "data/rescuescreen/r611q/package-v2-\x00addendum/README.md",
        ),
        (
            "directory_single_component",
            "package-v2-addendum",
            "package-v2-addendum/package_summary.json",
            "package-v2-addendum/README.md",
        ),
        (
            "json_parent_mismatch",
            "data/rescuescreen/r611q/package-v2-addendum",
            "data/rescuescreen/r611q/alternate-target/package_summary.json",
            "data/rescuescreen/r611q/package-v2-addendum/README.md",
        ),
        (
            "json_escape_parent",
            "data/rescuescreen/r611q/package-v2-addendum",
            "data/rescuescreen/r611q/package-v2-addendum/../escape/package_summary.json",
            "data/rescuescreen/r611q/package-v2-addendum/README.md",
        ),
        (
            "json_absolute",
            "data/rescuescreen/r611q/package-v2-addendum",
            "{ABS}/absolute-summary/package_summary.json",
            "data/rescuescreen/r611q/package-v2-addendum/README.md",
        ),
        (
            "readme_parent_mismatch",
            "data/rescuescreen/r611q/package-v2-addendum",
            "data/rescuescreen/r611q/package-v2-addendum/package_summary.json",
            "data/rescuescreen/r611q/alternate-target/README.md",
        ),
        (
            "readme_absolute",
            "data/rescuescreen/r611q/package-v2-addendum",
            "data/rescuescreen/r611q/package-v2-addendum/package_summary.json",
            "{ABS}/absolute-summary/README.md",
        ),
        (
            "json_wrong_filename",
            "data/rescuescreen/r611q/package-v2-addendum",
            "data/rescuescreen/r611q/package-v2-addendum/summary.json",
            "data/rescuescreen/r611q/package-v2-addendum/README.md",
        ),
        (
            "readme_wrong_filename",
            "data/rescuescreen/r611q/package-v2-addendum",
            "data/rescuescreen/r611q/package-v2-addendum/package_summary.json",
            "data/rescuescreen/r611q/package-v2-addendum/README.txt",
        ),
    ],
)
def test_r611q_pv2a_descriptor_relative_escape_operator_rejects_summary_path_mutations_before_publication(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    directory_value: str,
    json_path_value: str,
    readme_path_value: str,
) -> None:
    (
        module,
        fixture,
        config_path,
        summary_dir,
        summary_json_path,
        summary_readme_path,
        repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    output_root = (tmp_path / f"external-outside-{label}").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    package_dir = output_root / package_id
    outside_abs_root = (tmp_path / "outside-summary-target").resolve()

    directory = directory_value.replace("{ABS}", outside_abs_root.as_posix())
    json_path = json_path_value.replace("{ABS}", outside_abs_root.as_posix())
    readme_path = readme_path_value.replace("{ABS}", outside_abs_root.as_posix())

    config = _read_yaml_mapping(config_path)
    summary_output = config["output"]["repository_summary"]
    summary_output["directory"] = directory
    summary_output["json_path"] = json_path
    summary_output["readme_path"] = readme_path
    _write_operator_config(config_path, config)
    called = _install_publication_call_guards(module, monkeypatch)

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "r611q-package-v2-addendum error:" in captured.err
    assert "Traceback" not in captured.err
    assert not called["summary_publish"], "summary path validation must fail before summary publication"
    assert not called["external_render"], "summary path validation must fail before external publication"
    assert not outside_abs_root.exists(), "unsafe summary path mutation must not create outside directories"
    assert not summary_dir.exists(), "mutated summary path config must fail before summary publication writes"
    assert not summary_json_path.exists()
    assert not summary_readme_path.exists()
    assert not package_dir.exists(), "mutated summary path config must fail before external publication"
    assert "repository summary written:" not in captured.out
    assert "external package written:" not in captured.out


def test_r611q_pv2a_descriptor_relative_escape_operator_accepts_exact_real_shape_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (
        module,
        fixture,
        config_path,
        summary_dir,
        summary_json_path,
        summary_readme_path,
        repo_root,
        package_id,
    ) = _prepare_operator_fixture_and_config(tmp_path)
    output_root = (tmp_path / "external-outside-positive").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    package_dir = output_root / package_id

    config = _read_yaml_mapping(config_path)
    summary_output = config["output"]["repository_summary"]
    assert summary_output["directory"] == "data/rescuescreen/r611q/package-v2-addendum"
    assert summary_output["json_path"] == "data/rescuescreen/r611q/package-v2-addendum/package_summary.json"
    assert summary_output["readme_path"] == "data/rescuescreen/r611q/package-v2-addendum/README.md"
    _write_operator_config(config_path, config)

    exit_code = _run_operator_main(
        module,
        config_path=config_path,
        repo_root=repo_root,
        v1_packet_path=fixture.packet_path.resolve(),
        v1_form_path=fixture.form_path.resolve(),
        delta_bundle_root=fixture.delta_bundle_root.resolve(),
        output_root=output_root,
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err or captured.out
    assert package_dir.is_dir()
    assert summary_dir.is_dir()
    assert summary_json_path.is_file()
    assert summary_readme_path.is_file()


def _install_summary_publish_input_guards(
    module: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, int]:
    calls = {"open": 0, "mkdir": 0, "write": 0}

    def reject_open(*_args: Any, **_kwargs: Any):
        calls["open"] += 1
        raise AssertionError("invalid summary publish inputs must be rejected before any os.open call")

    def reject_mkdir(*_args: Any, **_kwargs: Any):
        calls["mkdir"] += 1
        raise AssertionError("invalid summary publish inputs must be rejected before any os.mkdir call")

    def reject_write(*_args: Any, **_kwargs: Any):
        calls["write"] += 1
        raise AssertionError(
            "invalid summary publish inputs must be rejected before any descriptor-relative file write"
        )

    monkeypatch.setattr(module.os, "open", reject_open)
    monkeypatch.setattr(module.os, "mkdir", reject_mkdir)
    monkeypatch.setattr(module, "_write_exclusive_via_dir_fd", reject_write)
    return calls


@pytest.mark.parametrize(
    ("label", "repository_summary_target_template"),
    [
        ("blank", ""),
        ("absolute_posix", "{ABS}/summary-target"),
        ("dot", "."),
        ("dotdot", ".."),
        ("leading_dot_component", "./data/rescuescreen/r611q/package-v2-addendum"),
        ("leading_dotdot_component", "../data/rescuescreen/r611q/package-v2-addendum"),
        ("dot_component", "data/rescuescreen/./r611q/package-v2-addendum"),
        ("dotdot_component", "data/rescuescreen/r611q/../package-v2-addendum"),
        ("empty_component", "data/rescuescreen/r611q//package-v2-addendum"),
        ("backslash", "data\\rescuescreen\\r611q\\package-v2-addendum"),
        ("drive_colon", "C:/rescuescreen/r611q/package-v2-addendum"),
        ("drive_colon_relative", "C:rescuescreen/r611q/package-v2-addendum"),
        ("nul", "data/rescuescreen/r611q/package-v2-addendum\x00x"),
        ("leading_whitespace", " data/rescuescreen/r611q/package-v2-addendum"),
        ("trailing_whitespace", "data/rescuescreen/r611q/package-v2-addendum "),
    ],
)
def test_r611q_pv2a_summary_publish_helper_rejects_unsafe_target_before_open_mkdir_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    repository_summary_target_template: str,
) -> None:
    module = _require_package_v2_module()
    repo_root = (tmp_path / f"repo-{label}").resolve()
    trusted_parent = repo_root / "data" / "rescuescreen" / "r611q"
    trusted_parent.mkdir(parents=True, exist_ok=True)
    canonical_target_dir = (repo_root / "data" / "rescuescreen" / "r611q" / "package-v2-addendum").resolve()
    outside_abs_root = (tmp_path / "outside-summary-target").resolve()
    repository_summary_target = repository_summary_target_template.replace("{ABS}", outside_abs_root.as_posix())

    calls = _install_summary_publish_input_guards(module, monkeypatch)
    with pytest.raises(module.PackageV2Error):
        module.publish_repository_summary_descriptor_relative(
            repo_root,
            repository_summary_target,
            json_name="package_summary.json",
            readme_name="README.md",
            json_bytes=b"{\"schema\":\"summary\"}\n",
            readme_bytes=b"# summary\n",
        )

    assert calls == {"open": 0, "mkdir": 0, "write": 0}
    assert not canonical_target_dir.exists(), "invalid target must fail with no summary directory creation"
    assert not outside_abs_root.exists(), "invalid target must not create outside directories"


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("json_name", "/package_summary.json"),
        ("json_name", "."),
        ("json_name", ".."),
        ("json_name", "nested/package_summary.json"),
        ("json_name", "nested\\package_summary.json"),
        ("json_name", "C:package_summary.json"),
        ("json_name", "package_summary.json\x00x"),
        ("json_name", " package_summary.json"),
        ("json_name", "package_summary.json "),
        ("json_name", "summary.json"),
        ("json_name", "README.md"),
        ("readme_name", "/README.md"),
        ("readme_name", "."),
        ("readme_name", ".."),
        ("readme_name", "nested/README.md"),
        ("readme_name", "nested\\README.md"),
        ("readme_name", "C:README.md"),
        ("readme_name", "README.md\x00x"),
        ("readme_name", " README.md"),
        ("readme_name", "README.md "),
        ("readme_name", "README.txt"),
        ("readme_name", "package_summary.json"),
    ],
)
def test_r611q_pv2a_summary_publish_helper_rejects_unsafe_names_before_open_mkdir_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    bad_value: str,
) -> None:
    module = _require_package_v2_module()
    repo_root = (tmp_path / "repo").resolve()
    trusted_parent = repo_root / "data" / "rescuescreen" / "r611q"
    trusted_parent.mkdir(parents=True, exist_ok=True)
    canonical_target_dir = (trusted_parent / "package-v2-addendum").resolve()

    json_name = "package_summary.json"
    readme_name = "README.md"
    if field_name == "json_name":
        json_name = bad_value
    else:
        readme_name = bad_value

    calls = _install_summary_publish_input_guards(module, monkeypatch)
    with pytest.raises(module.PackageV2Error):
        module.publish_repository_summary_descriptor_relative(
            repo_root,
            "data/rescuescreen/r611q/package-v2-addendum",
            json_name=json_name,
            readme_name=readme_name,
            json_bytes=b"{\"schema\":\"summary\"}\n",
            readme_bytes=b"# summary\n",
        )

    assert calls == {"open": 0, "mkdir": 0, "write": 0}
    assert not canonical_target_dir.exists(), "invalid summary filenames must fail before any directory creation"


def test_r611q_pv2a_summary_publish_helper_accepts_canonical_target_and_names(
    tmp_path: Path,
) -> None:
    module = _require_package_v2_module()
    repo_root = (tmp_path / "repo-positive").resolve()
    trusted_parent = repo_root / "data" / "rescuescreen" / "r611q"
    trusted_parent.mkdir(parents=True, exist_ok=True)

    json_bytes = b"{\"schema\":\"summary\"}\n"
    readme_bytes = b"# summary\n"
    publication = module.publish_repository_summary_descriptor_relative(
        repo_root,
        "data/rescuescreen/r611q/package-v2-addendum",
        json_name="package_summary.json",
        readme_name="README.md",
        json_bytes=json_bytes,
        readme_bytes=readme_bytes,
    )
    try:
        final_dir = trusted_parent / "package-v2-addendum"
        assert final_dir.is_dir()
        assert (final_dir / "package_summary.json").read_bytes() == json_bytes
        assert (final_dir / "README.md").read_bytes() == readme_bytes
    finally:
        publication.commit()
