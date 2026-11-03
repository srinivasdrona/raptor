from __future__ import annotations

import copy
import dataclasses
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, get_type_hints

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-kickoff.yaml"
REGISTRY_PATH = REPO_ROOT / "configs" / "sourceops" / "source_registry.yaml"
VALIDATION_CEILING = (
    "V2 can establish that source lifecycle metadata and change-impact routing "
    "are complete, deterministic, and fail-closed. It cannot establish that a "
    "source is scientifically sufficient, that a criterion is valid, that a "
    "variant direction is correct, or that any clinical or research scope is "
    "authorized."
)

AC_FM_TO_TEST = {
    "V2S1-AC01": "test_ac01_registry_top_level_closed_schema_exact",
    "V2S1-AC02": "test_ac02_registry_hash_canonicality_and_mutation_sensitivity",
    "V2S1-AC03": "tests/sourceops/test_repository_registry.py::test_ac03_exact_seven_records_ids_and_declaration_roots",
    "V2S1-AC04": "tests/sourceops/test_repository_registry.py::test_ac04_authoritative_roots_have_exact_nested_fact_accounting",
    "V2S1-AC05": "test_ac05_verified_and_historical_require_concrete_metadata",
    "V2S1-AC06": "test_ac06_declaration_path_safety_hash_drift_and_escape_guards",
    "V2S1-AC07": "test_ac07_graph_symmetry_and_unknown_predecessor_probes",
    "V2S1-AC08": "tests/sourceops/test_registry_cli.py::test_ac08_cli_json_determinism_and_exit_contract",
    "V2S1-AC09": "tests/sourceops/test_import_and_network_boundary.py::test_ac09_sourceops_dependency_and_network_boundaries",
    "V2S1-AC10": "tests/sourceops/test_repository_registry.py::test_ac10_impact_routes_are_declared_with_human_approval_flags",
    "V2S1-AC11": "test_ac11_typed_immutable_public_model_contract",
    "V2S1-AC12": "tests/sourceops/test_repository_registry.py::test_ac12_preservation_set_is_unchanged_by_sourceops_commands",
    "V2S1-AC13": "tests/sourceops/test_registry_cli.py::test_ac13_validation_report_states_operational_ceiling_verbatim",
    "V2S1-FM1": "tests/sourceops/test_registry_cli.py::test_fm1_blocked_metadata_never_launders_to_ready",
    "V2S1-FM2": "test_fm2_domain_authority_drift_is_fail_closed_and_non_mutating",
    "V2S1-FM3": "test_fm3_pinned_historical_record_cannot_refresh_in_place",
    "V2S1-FM4": "tests/sourceops/test_repository_registry.py::test_fm4_rescuescreen_ready_claim_is_forbidden",
}

EXPECTED_AC_FM_IDS = {
    *(f"V2S1-AC{n:02d}" for n in range(1, 14)),
    *(f"V2S1-FM{n}" for n in range(1, 5)),
}


def _first_slice_spec() -> dict[str, Any]:
    kickoff = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    if not isinstance(kickoff, dict) or not isinstance(kickoff.get("first_implementation_slice"), dict):
        pytest.fail("Kickoff spec must include first_implementation_slice mapping")
    return kickoff["first_implementation_slice"]


def _registry_model_spec() -> dict[str, Any]:
    model = _first_slice_spec().get("registry_model")
    if not isinstance(model, dict):
        pytest.fail("first_implementation_slice.registry_model must be present")
    return model


def _load_registry_payload() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        pytest.fail(f"SourceOps registry file is not implemented: {REGISTRY_PATH}")
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        pytest.fail("SourceOps registry must parse into a mapping")
    return payload


def _canonical_registry_hash(payload: dict[str, Any]) -> str:
    basis = copy.deepcopy(payload)
    basis.pop("registry_content_hash", None)
    canonical = json.dumps(
        basis,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_lf_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _write_yaml(path: Path, payload: dict[str, Any], *, newline: str = "\n") -> None:
    dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    if newline != "\n":
        dumped = dumped.replace("\n", newline)
    path.write_text(dumped, encoding="utf-8", newline="")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


def _run_validate(registry_path: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli("validate", "--registry", str(registry_path))


def _parse_json_report(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if not result.stdout.strip():
        pytest.fail(
            "SourceOps CLI must emit JSON on stdout.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover
        pytest.fail(f"stdout is not valid JSON: {exc}\nstdout={result.stdout!r}\nstderr={result.stderr!r}")
    if not isinstance(report, dict):
        pytest.fail("SourceOps CLI JSON report must be a top-level object")
    return report


def _error_entries(report: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(report.get("errors"), list):
        return [item for item in report["errors"] if isinstance(item, dict)]
    if isinstance(report.get("error"), dict):
        return [report["error"]]
    return []


def _error_codes(report: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for entry in _error_entries(report):
        code = entry.get("code")
        if isinstance(code, str) and code:
            codes.add(code)
    for key in ("code", "error_code", "failure_code"):
        value = report.get(key)
        if isinstance(value, str) and value:
            codes.add(value)
    return codes


def _assert_error_codes(report: dict[str, Any], expected: set[str]) -> None:
    codes = _error_codes(report)
    assert codes, f"No typed error code found in report: {report}"
    assert expected.intersection(codes), f"Expected one of {sorted(expected)}, got {sorted(codes)}"


def _assert_typed_errors(report: dict[str, Any]) -> None:
    entries = _error_entries(report)
    assert entries, f"Expected typed error entries in JSON report: {report}"
    for entry in entries:
        assert isinstance(entry.get("code"), str) and entry["code"], entry
        assert isinstance(entry.get("message"), str) and entry["message"], entry
        error_type = entry.get("type") or entry.get("error_type") or entry.get("exception_type")
        assert isinstance(error_type, str) and error_type, entry


def _assert_closed_mapping(
    obj: Any, required: set[str], optional: set[str], *, label: str, allow_empty: set[str] | None = None
) -> None:
    if not isinstance(obj, dict):
        pytest.fail(f"{label} must be a mapping")
    allow_empty = allow_empty or set()
    keys = set(obj)
    missing = sorted(required - keys)
    extra = sorted(keys - (required | optional))
    assert not missing, f"{label} missing required keys: {missing}"
    assert not extra, f"{label} has unknown keys (closed schema): {extra}"
    for key in sorted(required):
        value = obj.get(key)
        if key in allow_empty:
            continue
        assert value is not None, f"{label}.{key} must not be null"
        if isinstance(value, str):
            assert value.strip(), f"{label}.{key} must be non-empty"


def _first_source_record(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("source_records")
    if not isinstance(records, list) or not records:
        pytest.fail("Registry must contain non-empty source_records")
    if not isinstance(records[0], dict):
        pytest.fail("source_records entries must be mappings")
    return records[0]


def _first_consumer(payload: dict[str, Any]) -> dict[str, Any]:
    consumers = payload.get("consumers")
    if not isinstance(consumers, list) or not consumers:
        pytest.fail("Registry must contain non-empty consumers")
    if not isinstance(consumers[0], dict):
        pytest.fail("consumer entries must be mappings")
    return consumers[0]


def _first_declaration_ref(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    for record in records:
        if not isinstance(record, dict):
            continue
        refs = record.get("declaration_refs")
        if isinstance(refs, list) and refs and isinstance(refs[0], dict):
            return refs[0]
    pytest.fail("Registry must include at least one declaration_refs entry")


def _first_component(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    for record in records:
        if not isinstance(record, dict):
            continue
        components = record.get("components")
        if isinstance(components, list) and components and isinstance(components[0], dict):
            return components[0]
    pytest.fail("Registry must include at least one component row for closed-schema probes")


def _record_for_composite_mutation(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    for record in records:
        if not isinstance(record, dict):
            continue
        components = record.get("components")
        if record.get("record_kind") in {"COMPOSITE_MANIFEST", "POLICY_SOURCE_REGISTER"} and isinstance(
            components, list
        ):
            if not any(isinstance(component, dict) for component in components):
                components.append(
                    {
                        "component_id": "least-permissive-probe-component",
                        "display_name": "Least Permissive Probe Component",
                        "lifecycle_state": "VERIFIED_ACTIVE",
                        "source_role": "evidence",
                        "version_or_snapshot": "probe-v1",
                        "licence_status": "reviewed",
                        "declaration_locator": "probe.synthetic",
                    }
                )
            return record
    record = _first_source_record(payload)
    record["record_kind"] = "COMPOSITE_MANIFEST"
    declaration_refs = record.get("declaration_refs")
    locator = "probe.synthetic"
    if isinstance(declaration_refs, list) and declaration_refs and isinstance(declaration_refs[0], dict):
        ref_path = declaration_refs[0].get("path")
        if isinstance(ref_path, str) and ref_path.strip():
            locator = ref_path.replace("\\", "/")
    record["components"] = [
        {
            "component_id": "least-permissive-probe-component",
            "display_name": "Least Permissive Probe Component",
            "lifecycle_state": "VERIFIED_ACTIVE",
            "source_role": "evidence",
            "version_or_snapshot": "probe-v1",
            "licence_status": "reviewed",
            "declaration_locator": locator,
        }
    ]
    return record


def _placeholder_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    cleaned = value.strip().lower()
    if not cleaned:
        return True
    return any(marker in cleaned for marker in ("confirm-pending", "pending", "unconfirmed", "unknown", "placeholder"))


_UNVERIFIED_TOKEN_RE = re.compile(
    r"(confirm[\s_-]*pending|\bpending\b|\bunconfirmed\b|\bunknown\b|\btbd\b|\bplaceholder\b|\bproposed\b|\bunverified\b)",
    flags=re.IGNORECASE,
)


def _has_unverified_marker(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(_UNVERIFIED_TOKEN_RE.search(value.strip()))


def _source_record_by_id(payload: dict[str, Any], source_id: str) -> dict[str, Any]:
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    for record in records:
        if isinstance(record, dict) and record.get("source_id") == source_id:
            return record
    pytest.fail(f"source_id {source_id!r} not found")


def _assert_sourceops_typed_exception(exc: BaseException, *, expected_code: str | None = None) -> None:
    exc_cls = type(exc)
    assert exc_cls.__module__.startswith("raptor.sourceops"), (
        "load_registry must raise a SourceOps-typed exception, not a generic built-in exception"
    )
    assert exc_cls.__name__ not in {"Exception", "ValueError", "TypeError", "KeyError", "RuntimeError"}, (
        "load_registry must raise a domain-typed SourceOps exception"
    )
    error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None) or getattr(exc, "failure_code", None)
    if expected_code is not None and error_code is not None:
        assert error_code == expected_code


def _mutate_unknown_key(payload: dict[str, Any]) -> None:
    payload["unknown_contract_key"] = True


def _mutate_missing_required(payload: dict[str, Any]) -> None:
    payload.pop("schema", None)


def _mutate_wrong_type(payload: dict[str, Any]) -> None:
    payload["source_records"] = {"not": "a-list"}


def _mutate_duplicate_source_id(payload: dict[str, Any]) -> None:
    records = payload.get("source_records")
    if not isinstance(records, list) or not records:
        pytest.fail("source_records must be non-empty for duplicate-id probe")
    records.append(copy.deepcopy(records[0]))


def _mutate_invalid_lifecycle(payload: dict[str, Any]) -> None:
    record = _first_source_record(payload)
    record["lifecycle_state"] = "NOT_A_VALID_LIFECYCLE_STATE"


def _mutate_ready_lifecycle(payload: dict[str, Any]) -> None:
    record = _first_source_record(payload)
    record["lifecycle_state"] = "READY"


def _mutate_unknown_record_kind(payload: dict[str, Any]) -> None:
    record = _first_source_record(payload)
    record["record_kind"] = "FABRICATED_RECORD_KIND"


def _mutate_single_source_with_components(payload: dict[str, Any]) -> None:
    record = _record_for_composite_mutation(payload)
    record["record_kind"] = "SINGLE_SOURCE"
    components = record.get("components")
    if not isinstance(components, list) or not components:
        record["components"] = [
            {
                "component_id": "single-source-component-shape-probe",
                "display_name": "Single source component shape probe",
                "lifecycle_state": "VERIFIED_ACTIVE",
                "source_role": "evidence",
                "version_or_snapshot": "probe-v1",
                "licence_status": "reviewed",
                "declaration_locator": "configs/ingest/tsc.yaml#assembly",
            }
        ]


def _mutate_composite_without_components(payload: dict[str, Any]) -> None:
    catalog = _source_record_by_id(payload, "atlas-tsc2-catalog-template")
    catalog["record_kind"] = "COMPOSITE_MANIFEST"
    catalog["components"] = None


def _mutate_policy_without_components(payload: dict[str, Any]) -> None:
    catalog = _source_record_by_id(payload, "atlas-tsc2-catalog-template")
    catalog["record_kind"] = "POLICY_SOURCE_REGISTER"
    catalog["components"] = None


def _mutate_unknown_source_key(payload: dict[str, Any]) -> None:
    _first_source_record(payload)["unknown_row_key"] = True


def _mutate_unknown_declaration_ref_key(payload: dict[str, Any]) -> None:
    _first_declaration_ref(payload)["unknown_ref_key"] = True


def _mutate_unknown_component_key(payload: dict[str, Any]) -> None:
    _first_component(payload)["unknown_component_key"] = True


def _mutate_unknown_consumer_key(payload: dict[str, Any]) -> None:
    _first_consumer(payload)["unknown_consumer_key"] = True


def _mutate_unknown_rollback_key(payload: dict[str, Any]) -> None:
    record = _first_source_record(payload)
    rollback = record.get("rollback")
    if not isinstance(rollback, dict):
        pytest.fail("source_record.rollback must be a mapping for closed-schema probe")
    rollback["unknown_rollback_key"] = True


def _mutate_duplicate_component_id_within_source_record(payload: dict[str, Any]) -> None:
    record = _source_record_by_id(payload, "tsc-ingest-and-reference-declarations")
    components = record.get("components")
    if not isinstance(components, list) or not components:
        pytest.fail("duplicate component_id probe requires non-empty components list")
    target = next(
        (
            row
            for row in components
            if isinstance(row, dict) and row.get("component_id") == "tsc-ingest-clinvar-snapshot-id"
        ),
        None,
    )
    if target is None:
        target = next((row for row in components if isinstance(row, dict)), None)
    if target is None:
        pytest.fail("duplicate component_id probe requires at least one component mapping")
    components.append(copy.deepcopy(target))


def _mutate_duplicate_coverage_exclusion_id(payload: dict[str, Any]) -> None:
    exclusions = payload.get("coverage_exclusions")
    if not isinstance(exclusions, list):
        pytest.fail("coverage_exclusions must be a list for duplicate exclusion_id probe")
    duplicate = {
        "exclusion_id": "duplicate-coverage-exclusion-id-probe",
        "declaration_path": "docs/project/specs/raptor-v2-kickoff.yaml",
        "declaration_locator": "first_implementation_slice.synthetic_duplicate_exclusion_probe",
        "owner": "sourceops-contract-test",
        "reason": "synthetic duplicate exclusion id probe",
        "review_condition": "replace with unique exclusion id before promotion",
    }
    exclusions.extend([copy.deepcopy(duplicate), copy.deepcopy(duplicate)])


def _mutate_duplicate_preservation_rule_id(payload: dict[str, Any]) -> None:
    rules = payload.get("preservation_rules")
    if not isinstance(rules, list):
        pytest.fail("preservation_rules must be a list for duplicate rule_id probe")
    duplicate = {
        "rule_id": "duplicate-preservation-rule-id-probe",
        "path": "configs/eval/core_annotation_bundle.yaml",
        "owner": "sourceops-contract-test",
        "reason": "synthetic duplicate preservation rule id probe",
    }
    rules.extend([copy.deepcopy(duplicate), copy.deepcopy(duplicate)])


def _assert_duplicate_identifier_error(report: dict[str, Any], *, identifier_field: str) -> None:
    entries = _error_entries(report)
    marker_texts = {
        identifier_field.lower(),
        identifier_field.replace("_", " ").lower(),
        identifier_field.replace("_", "-").lower(),
    }
    assert any(
        isinstance(entry.get("code"), str)
        and bool(entry.get("code"))
        and isinstance(entry.get("type"), str)
        and bool(entry.get("type"))
        and "duplicate" in str(entry.get("message", "")).lower()
        and any(marker in str(entry.get("message", "")).lower() for marker in marker_texts)
        for entry in entries
    ), f"expected typed duplicate-id error mentioning {identifier_field!r}, got {entries}"


def test_ac01_registry_top_level_closed_schema_exact() -> None:
    payload = _load_registry_payload()
    model = _registry_model_spec()
    required = set(model.get("top_level_required", []))
    optional = set(model.get("top_level_optional", []))
    allowed = required | optional

    assert required, "registry_model.top_level_required must not be empty"
    assert set(payload) == allowed, (
        f"Top-level keys must exactly match contract.\n"
        f"required={sorted(required)} optional={sorted(optional)} actual={sorted(payload)}"
    )
    if "validation_ceiling" in payload:
        assert "validation_ceiling" in allowed, (
            "validation_ceiling is present in source registry but not allowed by "
            "registry_model.top_level_required/optional"
        )


def test_ac01_source_record_and_nested_models_are_closed_and_complete() -> None:
    payload = _load_registry_payload()
    model = _registry_model_spec()
    allowed_record_kinds = set(model.get("record_kinds", {}))
    lifecycle_states = set(model.get("lifecycle_states", {}))
    source_required = set(model.get("source_record_required", []))
    source_optional = set(model.get("source_record_optional", []))

    records = payload.get("source_records")
    assert isinstance(records, list) and records, "source_records must be a non-empty list"
    for idx, record in enumerate(records):
        _assert_closed_mapping(
            record,
            source_required,
            source_optional,
            label=f"source_records[{idx}]",
            allow_empty={"components", "blocked_reasons", "missing_inputs"},
        )
        assert record.get("record_kind") in allowed_record_kinds
        assert record.get("lifecycle_state") in lifecycle_states
        assert record.get("lifecycle_state") != "READY", "READY is consumer readiness, not source lifecycle"

        refs = record.get("declaration_refs")
        assert isinstance(refs, list) and refs, f"source_records[{idx}].declaration_refs must be non-empty"
        ref_required = set(model["declaration_reference"]["required"])
        for ref_idx, ref in enumerate(refs):
            _assert_closed_mapping(ref, ref_required, set(), label=f"source_records[{idx}].declaration_refs[{ref_idx}]")

        component_required = set(model.get("component_required", []))
        components = record.get("components")
        if record["record_kind"] == "SINGLE_SOURCE":
            assert components in (None, []), "SINGLE_SOURCE must not carry components"
        if record["record_kind"] in {"COMPOSITE_MANIFEST", "POLICY_SOURCE_REGISTER"}:
            assert isinstance(components, list), f"{record['record_kind']} must carry components list"
            component_ids: set[str] = set()
            for comp_idx, component in enumerate(components):
                _assert_closed_mapping(
                    component,
                    component_required,
                    set(),
                    label=f"source_records[{idx}].components[{comp_idx}]",
                )
                comp_id = component.get("component_id")
                assert isinstance(comp_id, str) and comp_id
                assert comp_id not in component_ids, f"duplicate component_id in source_records[{idx}]: {comp_id}"
                component_ids.add(comp_id)
        if record["record_kind"] == "METADATA_CATALOG_TEMPLATE":
            assert components == [], "METADATA_CATALOG_TEMPLATE must have zero components"

        _assert_closed_mapping(
            record.get("licence"),
            set(model["licence_model"]["required"]),
            set(),
            label=f"source_records[{idx}].licence",
        )
        _assert_closed_mapping(
            record.get("release"),
            set(model["release_model"]["required"]),
            set(),
            label=f"source_records[{idx}].release",
        )
        _assert_closed_mapping(
            record.get("acquisition"),
            set(model["acquisition_model"]["required"]),
            set(),
            label=f"source_records[{idx}].acquisition",
        )
        _assert_closed_mapping(
            record.get("refresh"),
            set(model["refresh_model"]["required"]),
            set(),
            label=f"source_records[{idx}].refresh",
        )
        _assert_closed_mapping(
            record.get("drift_policy"),
            set(model["drift_policy_model"]["required"]),
            set(),
            label=f"source_records[{idx}].drift_policy",
        )
        _assert_closed_mapping(
            record.get("rollback"),
            set(model["rollback_model"]["required"]),
            set(),
            label=f"source_records[{idx}].rollback",
            allow_empty={"predecessor_source_id"},
        )
        rollback = record.get("rollback")
        assert isinstance(rollback, dict)
        predecessor = rollback.get("predecessor_source_id")
        if predecessor is None:
            origin_reason = rollback.get("origin_reason")
            assert isinstance(origin_reason, str) and origin_reason.strip() and not _placeholder_text(origin_reason), (
                "rollback.predecessor_source_id may be null only with a concrete non-blank origin_reason"
            )
        else:
            assert isinstance(predecessor, str) and predecessor.strip(), (
                "rollback.predecessor_source_id must be a non-empty string when present"
            )


def test_ac01_consumer_exclusion_and_preservation_models_are_closed() -> None:
    payload = _load_registry_payload()
    model = _registry_model_spec()

    consumers = payload.get("consumers")
    assert isinstance(consumers, list) and consumers, "consumers must be a non-empty list"
    consumer_required = set(model["consumer_model"]["required"])
    for idx, consumer in enumerate(consumers):
        _assert_closed_mapping(
            consumer,
            consumer_required,
            set(),
            label=f"consumers[{idx}]",
            allow_empty={"required_sources", "forbidden_source_roles"},
        )
        required_sources = consumer.get("required_sources")
        assert isinstance(required_sources, list)
        assert all(isinstance(source_id, str) and source_id for source_id in required_sources)
        assert isinstance(consumer.get("freshness_required"), bool)
        forbidden_roles = consumer.get("forbidden_source_roles")
        assert isinstance(forbidden_roles, list)
        assert all(isinstance(role, str) and role for role in forbidden_roles)

    exclusions = payload.get("coverage_exclusions")
    assert isinstance(exclusions, list), "coverage_exclusions must be a list"
    exclusion_required = set(model["coverage_exclusion_required"])
    for idx, exclusion in enumerate(exclusions):
        _assert_closed_mapping(exclusion, exclusion_required, set(), label=f"coverage_exclusions[{idx}]")

    preservation_rules = payload.get("preservation_rules")
    assert isinstance(preservation_rules, list), "preservation_rules must be present and declarative"
    assert preservation_rules, "preservation_rules must not be empty"
    serialized = json.dumps(preservation_rules, ensure_ascii=False, sort_keys=True)
    for rel_path in _first_slice_spec()["preservation_set"]["files"]:
        assert rel_path in serialized, f"preservation_rules must reference preserved artifact {rel_path}"
    lower_serialized = serialized.lower()
    forbidden_execution_markers = ("subprocess", "execute", "applied_action", "mutate_file")
    assert not any(marker in lower_serialized for marker in forbidden_execution_markers), (
        "preservation_rules must be declarative only, not executable action descriptions"
    )


@pytest.mark.parametrize(
    "mutator",
    [
        _mutate_unknown_key,
        _mutate_unknown_source_key,
        _mutate_unknown_declaration_ref_key,
        _mutate_unknown_component_key,
        _mutate_unknown_consumer_key,
        _mutate_unknown_rollback_key,
    ],
    ids=[
        "unknown-top-level-key",
        "unknown-source-record-key",
        "unknown-declaration-ref-key",
        "unknown-component-key",
        "unknown-consumer-key",
        "unknown-rollback-key",
    ],
)
def test_ac01_closed_schema_rejects_unknown_keys_at_every_level(
    tmp_path: Path, mutator: Callable[[dict[str, Any]], None]
) -> None:
    payload = _load_registry_payload()
    mutator(payload)
    if "registry_content_hash" in payload:
        payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac01_closed_schema_unknown_key_probe.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"REGISTRY_SCHEMA_ERROR"})
    _assert_typed_errors(report)


@pytest.mark.parametrize(
    "mutator",
    [
        _mutate_missing_required,
        _mutate_wrong_type,
        _mutate_duplicate_source_id,
        _mutate_invalid_lifecycle,
        _mutate_ready_lifecycle,
    ],
    ids=[
        "missing-required",
        "wrong-type",
        "duplicate-id",
        "invented-lifecycle-enum",
        "ready-as-source-lifecycle",
    ],
)
def test_ac01_closed_schema_and_typed_errors_for_mutations(
    tmp_path: Path, mutator: Callable[[dict[str, Any]], None]
) -> None:
    payload = _load_registry_payload()
    mutator(payload)
    if "registry_content_hash" in payload:
        payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac01_probe.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"REGISTRY_SCHEMA_ERROR"})
    _assert_typed_errors(report)


@pytest.mark.parametrize(
    "mutator,identifier_field",
    [
        (_mutate_duplicate_component_id_within_source_record, "component_id"),
        (_mutate_duplicate_coverage_exclusion_id, "exclusion_id"),
        (_mutate_duplicate_preservation_rule_id, "rule_id"),
    ],
    ids=[
        "duplicate-component-id-within-source-record",
        "duplicate-coverage-exclusion-id",
        "duplicate-preservation-rule-id",
    ],
)
def test_ac01_duplicate_identifier_closure_rejects_registry_identity_collisions(
    tmp_path: Path, mutator: Callable[[dict[str, Any]], None], identifier_field: str
) -> None:
    payload = _load_registry_payload()
    mutator(payload)
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / f"ac01_duplicate_identifier_{identifier_field}.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    assert report.get("registry_valid") is False
    assert _error_codes(report), f"duplicate-id probe must emit typed error codes: {report}"
    _assert_typed_errors(report)
    _assert_duplicate_identifier_error(report, identifier_field=identifier_field)
    assert "REGISTRY_HASH_MISMATCH" not in _error_codes(report), (
        "duplicate-id probe must fail on identifier closure, not stale hash mismatch"
    )


@pytest.mark.parametrize(
    "mutator,expected_codes",
    [
        (_mutate_unknown_record_kind, {"REGISTRY_SCHEMA_ERROR"}),
        (_mutate_single_source_with_components, {"REGISTRY_SCHEMA_ERROR"}),
        (_mutate_composite_without_components, {"REGISTRY_SCHEMA_ERROR"}),
        (_mutate_policy_without_components, {"REGISTRY_SCHEMA_ERROR"}),
    ],
    ids=[
        "unknown-record-kind-enum",
        "single-source-with-components",
        "composite-manifest-without-components",
        "policy-register-without-components",
    ],
)
def test_ac01_record_kind_enum_and_component_shape_rules_fail_closed(
    tmp_path: Path, mutator: Callable[[dict[str, Any]], None], expected_codes: set[str]
) -> None:
    payload = _load_registry_payload()
    mutator(payload)
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac01_record_kind_shape_probe.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, expected_codes)
    _assert_typed_errors(report)


@pytest.mark.parametrize(
    "mutator",
    [_mutate_unknown_key, _mutate_wrong_type],
    ids=["unknown-key", "wrong-type"],
)
def test_ac01_load_registry_rejects_invalid_shape_with_typed_sourceops_exception(
    tmp_path: Path, mutator: Callable[[dict[str, Any]], None]
) -> None:
    from raptor.sourceops.registry import load_registry

    payload = _load_registry_payload()
    mutator(payload)
    if "registry_content_hash" in payload:
        payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac01_typed_model_probe.yaml"
    _write_yaml(probe_path, payload)

    with pytest.raises(Exception) as excinfo:
        load_registry(probe_path)
    _assert_sourceops_typed_exception(excinfo.value, expected_code="REGISTRY_SCHEMA_ERROR")


def test_ac02_registry_hash_canonicality_and_mutation_sensitivity(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    first_slice = _first_slice_spec()
    declared_hash = payload.get("registry_content_hash")
    assert isinstance(declared_hash, str) and declared_hash, "registry_content_hash must be present"
    assert declared_hash == _canonical_registry_hash(payload)
    assert payload.get("hash_basis") == first_slice["primary_artifact"]["hash_algorithm"]

    reordered = {key: payload[key] for key in reversed(list(payload.keys()))}
    reordered_path = tmp_path / "registry_reordered_crlf.yaml"
    _write_yaml(reordered_path, reordered, newline="\r\n")
    reordered_result = _run_validate(reordered_path)
    assert reordered_result.returncode == 0, reordered_result.stderr or reordered_result.stdout
    reordered_report = _parse_json_report(reordered_result)
    assert reordered_report.get("schema") == "raptor.source_registry.validation.v1"
    assert reordered_report.get("registry_valid") is True

    records = payload.get("source_records")
    assert isinstance(records, list) and len(records) >= 2, "Expected at least two source records for mutation probe"
    sequence_mutation = copy.deepcopy(payload)
    seq_records = sequence_mutation["source_records"]
    seq_records[0], seq_records[1] = seq_records[1], seq_records[0]
    assert _canonical_registry_hash(sequence_mutation) != declared_hash

    sequence_mutation["registry_content_hash"] = declared_hash
    sequence_path = tmp_path / "registry_sequence_mutation.yaml"
    _write_yaml(sequence_path, sequence_mutation)
    sequence_result = _run_validate(sequence_path)
    assert sequence_result.returncode == 2, sequence_result.stderr or sequence_result.stdout
    sequence_report = _parse_json_report(sequence_result)
    _assert_error_codes(sequence_report, {"REGISTRY_HASH_MISMATCH"})
    _assert_typed_errors(sequence_report)


def test_ac02_hash_preserves_explicit_null_optional_keys(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    explicit_null = copy.deepcopy(payload)
    explicit_record = _source_record_by_id(explicit_null, "frozen-core-annotation-bundle")
    for key in ("unblock_condition", "reviewed_by", "reviewed_at"):
        explicit_record[key] = None

    omitted = copy.deepcopy(payload)
    omitted_record = _source_record_by_id(omitted, "frozen-core-annotation-bundle")
    for key in ("unblock_condition", "reviewed_by", "reviewed_at"):
        omitted_record.pop(key, None)

    assert _canonical_registry_hash(explicit_null) != _canonical_registry_hash(omitted), (
        "explicit null optional keys must be part of semantic hash content and distinct from omission"
    )

    explicit_null["registry_content_hash"] = _canonical_registry_hash(explicit_null)
    probe_path = tmp_path / "ac02_explicit_null_hash_basis.yaml"
    _write_yaml(probe_path, explicit_null)
    result = _run_validate(probe_path)
    assert result.returncode == 0, result.stderr or result.stdout


def test_ac02_hash_uses_raw_mapping_basis_for_explicit_null_vs_omitted_components(tmp_path: Path) -> None:
    payload = _load_registry_payload()

    explicit_null = copy.deepcopy(payload)
    explicit_record = _source_record_by_id(explicit_null, "atlas-tsc2-catalog-template")
    explicit_record["components"] = None
    explicit_hash = _canonical_registry_hash(explicit_null)
    explicit_null["registry_content_hash"] = explicit_hash

    omitted = copy.deepcopy(payload)
    omitted_record = _source_record_by_id(omitted, "atlas-tsc2-catalog-template")
    omitted_record.pop("components", None)
    omitted_hash = _canonical_registry_hash(omitted)
    omitted["registry_content_hash"] = omitted_hash

    assert explicit_hash != omitted_hash, (
        "hash basis must preserve explicit null vs omitted properties for source-record optional fields"
    )

    explicit_path = tmp_path / "ac02_explicit_null_components.yaml"
    _write_yaml(explicit_path, explicit_null)
    explicit_result = _run_validate(explicit_path)
    assert explicit_result.returncode == 0, explicit_result.stderr or explicit_result.stdout

    omitted_path = tmp_path / "ac02_omitted_components.yaml"
    _write_yaml(omitted_path, omitted)
    omitted_result = _run_validate(omitted_path)
    assert omitted_result.returncode == 0, omitted_result.stderr or omitted_result.stdout


def test_ac05_verified_and_historical_require_concrete_metadata() -> None:
    payload = _load_registry_payload()
    records = payload.get("source_records")
    assert isinstance(records, list) and records, "source_records must be non-empty"

    pinned_historical_found = False
    for record in records:
        if not isinstance(record, dict):
            continue
        lifecycle_state = record.get("lifecycle_state")
        if lifecycle_state not in {"VERIFIED_ACTIVE", "PINNED_HISTORICAL"}:
            continue
        if lifecycle_state == "PINNED_HISTORICAL":
            pinned_historical_found = True

        owner = record.get("owner")
        assert isinstance(owner, str) and owner.strip() and not _placeholder_text(owner)

        release = record.get("release")
        assert isinstance(release, dict), f"{record.get('source_id')} release must be structured"
        for field in ("version_or_snapshot", "content_pin_status"):
            value = release.get(field)
            assert isinstance(value, str) and value.strip() and not _placeholder_text(value), (
                f"{record.get('source_id')} {field} cannot be placeholder in {lifecycle_state}"
            )

        licence = record.get("licence")
        assert isinstance(licence, dict), f"{record.get('source_id')} licence must be structured"
        for field in ("status", "permitted_use"):
            value = licence.get(field)
            assert isinstance(value, str) and value.strip() and not _placeholder_text(value), (
                f"{record.get('source_id')} licence.{field} cannot be placeholder in {lifecycle_state}"
            )

        rollback = record.get("rollback")
        assert isinstance(rollback, dict), f"{record.get('source_id')} rollback must be structured"
        assert rollback.get("immutable_predecessor_required") is True, (
            f"{record.get('source_id')} must require immutable predecessor in {lifecycle_state}"
        )
        predecessor = rollback.get("predecessor_source_id")
        if predecessor is None:
            origin_reason = rollback.get("origin_reason")
            assert isinstance(origin_reason, str) and origin_reason.strip() and not _placeholder_text(origin_reason)
        else:
            assert isinstance(predecessor, str) and predecessor.strip() and predecessor != record.get("source_id")
    assert pinned_historical_found, "Baseline must include at least one PINNED_HISTORICAL source record"


def test_ac05_mane_component_cannot_remain_verified_with_confirm_pending_licence(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    ingest = _source_record_by_id(payload, "tsc-ingest-and-reference-declarations")
    components = ingest.get("components")
    if not isinstance(components, list):
        pytest.fail("ingest record must carry components list")
    mane_component = next(
        (
            component
            for component in components
            if isinstance(component, dict)
            and isinstance(component.get("declaration_locator"), str)
            and component["declaration_locator"].endswith("#mane_release")
        ),
        None,
    )
    if mane_component is None:
        pytest.fail("Expected ingest MANE component for lifecycle truthfulness probe")
    mane_component["lifecycle_state"] = "VERIFIED_ACTIVE"
    mane_component["licence_status"] = "ConFiRm_PeNdInG-review"
    assert _has_unverified_marker(mane_component["licence_status"])
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac05_mane_verified_component_pending_licence.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"SOURCE_METADATA_INCOMPLETE", "FORBIDDEN_ROLE_FLOW"})


@pytest.mark.parametrize(
    "marker",
    ["confirm_pending", "CONFIRM-PENDING", "unknown", "tbd", "proposed"],
    ids=["underscore", "hyphen-case", "unknown", "tbd", "proposed"],
)
def test_ac05_composite_least_permissive_rejects_unverified_component_fact_spellings(
    tmp_path: Path, marker: str
) -> None:
    payload = _load_registry_payload()
    record = _record_for_composite_mutation(payload)
    record["lifecycle_state"] = "VERIFIED_ACTIVE"
    components = record.get("components")
    if not isinstance(components, list) or not components:
        pytest.fail("least-permissive marker probe requires at least one component")
    component = next((row for row in components if isinstance(row, dict)), None)
    if component is None:
        pytest.fail("least-permissive marker probe requires component mapping")
    component["lifecycle_state"] = "VERIFIED_ACTIVE"
    component["version_or_snapshot"] = f"{marker}-version-pin"
    component["licence_status"] = f"{marker}-licence-fact"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / f"ac05_least_permissive_marker_{marker.replace('-', '_')}.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"SOURCE_METADATA_INCOMPLETE", "FORBIDDEN_ROLE_FLOW"})


def test_ac05_verified_or_historical_records_reject_unknown_permitted_use_and_placeholder_pins(
    tmp_path: Path,
) -> None:
    payload = _load_registry_payload()
    core = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    core["lifecycle_state"] = "PINNED_HISTORICAL"
    release = core.get("release")
    if not isinstance(release, dict):
        pytest.fail("frozen-core-annotation-bundle release mapping required")
    release["content_pin_status"] = "tbd_content_pin"
    licence = core.get("licence")
    if not isinstance(licence, dict):
        pytest.fail("frozen-core-annotation-bundle licence mapping required")
    licence["permitted_use"] = "unknown_scope_for_declared_use"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac05_unknown_permitted_use_and_placeholder_pin.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"SOURCE_METADATA_INCOMPLETE", "REGISTRY_SCHEMA_ERROR"})


def test_ac05_licensing_tag_components_cannot_be_laundered_into_verified_evidence(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    record = _record_for_composite_mutation(payload)
    record["lifecycle_state"] = "VERIFIED_ACTIVE"
    declaration_refs = record.get("declaration_refs")
    locator = "synthetic-licensing-tag.probe"
    if isinstance(declaration_refs, list) and declaration_refs and isinstance(declaration_refs[0], dict):
        ref_path = declaration_refs[0].get("path")
        if isinstance(ref_path, str) and ref_path.strip():
            locator = f"{ref_path.replace('\\', '/')}#licensing.synthetic"
    record["components"] = [
        {
            "component_id": "synthetic-licensing-tag",
            "display_name": "Synthetic licensing tag metadata",
            "lifecycle_state": "VERIFIED_ACTIVE",
            "source_role": "licensing_tag",
            "version_or_snapshot": "licensing-policy-v1",
            "licence_status": "permitted_use_cleared_for_all_uses",
            "declaration_locator": locator,
        }
    ]
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac05_licensing_tag_laundering_probe.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"SOURCE_METADATA_INCOMPLETE", "FORBIDDEN_ROLE_FLOW"})


@pytest.mark.parametrize(
    "state,placeholder_value",
    [
        ("CONFIRM_PENDING", ""),
        ("ACCESS_BLOCKED", "pending"),
    ],
    ids=["confirm-pending-missing-unblock-condition", "access-blocked-generic-pending-placeholder"],
)
def test_ac05_blocked_state_requirements_fail_closed(
    tmp_path: Path, state: str, placeholder_value: str
) -> None:
    payload = _load_registry_payload()
    record = _first_source_record(payload)
    record["lifecycle_state"] = state
    record["blocked_reasons"] = ["missing approval"]
    record["missing_inputs"] = ["licence verification", "content pin"]
    record["unblock_condition"] = placeholder_value
    record["reviewed_by"] = "sourceops-contract-test"
    record["reviewed_at"] = "2026-08-16T00:00:00Z"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)

    probe_path = tmp_path / "ac05_blocked_state_probe.yaml"
    _write_yaml(probe_path, payload)
    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"REGISTRY_SCHEMA_ERROR", "SOURCE_METADATA_INCOMPLETE"})
    _assert_typed_errors(report)


def test_ac05_rollback_null_predecessor_rule_is_enforced_by_mutation(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    blank_origin = copy.deepcopy(payload)
    first_row = _first_source_record(blank_origin)
    first_rollback = first_row.get("rollback")
    if not isinstance(first_rollback, dict):
        pytest.fail("source_record.rollback must be a mapping for rollback null predecessor probe")
    first_rollback["predecessor_source_id"] = None
    first_rollback["origin_reason"] = "   "

    blank_origin["registry_content_hash"] = _canonical_registry_hash(blank_origin)
    probe_path = tmp_path / "ac05_rollback_null_predecessor_blank_origin.yaml"
    _write_yaml(probe_path, blank_origin)
    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"REGISTRY_SCHEMA_ERROR", "SOURCE_METADATA_INCOMPLETE", "IMMUTABLE_HISTORY_VIOLATION"})
    _assert_typed_errors(report)


def test_ac05_composite_least_permissive_aggregate_rejects_component_laundering(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    record = _record_for_composite_mutation(payload)
    components = record.get("components")
    if not isinstance(components, list):
        pytest.fail("composite/policy source record must include components list")
    component = next((row for row in components if isinstance(row, dict)), None)
    if component is None:
        pytest.fail("composite/policy source record must include at least one component mapping")

    pending_case = copy.deepcopy(payload)
    pending_record = _record_for_composite_mutation(pending_case)
    pending_record["lifecycle_state"] = "VERIFIED_ACTIVE"
    pending_components = pending_record.get("components")
    assert isinstance(pending_components, list) and pending_components
    pending_component = next((row for row in pending_components if isinstance(row, dict)), None)
    if pending_component is None:
        pytest.fail("pending aggregate mutation requires one component row")
    pending_component["lifecycle_state"] = "CONFIRM_PENDING"
    pending_component["version_or_snapshot"] = "component-v1"
    pending_component["licence_status"] = "reviewed"

    metadata_case = copy.deepcopy(payload)
    metadata_record = _record_for_composite_mutation(metadata_case)
    metadata_record["lifecycle_state"] = "VERIFIED_ACTIVE"
    metadata_components = metadata_record.get("components")
    assert isinstance(metadata_components, list) and metadata_components
    metadata_component = next((row for row in metadata_components if isinstance(row, dict)), None)
    if metadata_component is None:
        pytest.fail("metadata aggregate mutation requires one component row")
    metadata_component["lifecycle_state"] = "VERIFIED_ACTIVE"
    metadata_component["version_or_snapshot"] = "confirm-pending-component-version"
    metadata_component["licence_status"] = "confirm-pending-permitted-use"

    for case_id, mutated, expected in (
        ("pending-component-laundered", pending_case, "FORBIDDEN_ROLE_FLOW"),
        ("placeholder-component-metadata-laundered", metadata_case, "SOURCE_METADATA_INCOMPLETE"),
    ):
        mutated["registry_content_hash"] = _canonical_registry_hash(mutated)
        probe_path = tmp_path / f"ac05_least_permissive_component_probe_{case_id}.yaml"
        _write_yaml(probe_path, mutated)
        result = _run_validate(probe_path)
        assert result.returncode == 2, f"{case_id}: {result.stderr or result.stdout}"
        report = _parse_json_report(result)
        codes = _error_codes(report)
        assert expected in codes, f"{case_id} must fail with {expected}; got {sorted(codes)}"
        _assert_typed_errors(report)


def test_ac06_declaration_path_safety_hash_drift_and_escape_guards(tmp_path: Path) -> None:
    base = _load_registry_payload()
    ref = _first_declaration_ref(base)
    model = _registry_model_spec()
    _assert_closed_mapping(
        ref,
        set(model["declaration_reference"]["required"]),
        set(),
        label="declaration_ref",
    )
    original_path = ref.get("path")
    assert isinstance(original_path, str) and original_path, "declaration_refs.path must be a non-empty string"
    original_file = REPO_ROOT / Path(original_path)
    assert original_file.exists(), f"Referenced declaration path must exist in baseline: {original_file}"

    invalid_cases: list[tuple[str, str, set[str]]] = [
        ("absolute-path", str(original_file.resolve()), {"DECLARATION_REFERENCE_INVALID"}),
        ("drive-path", "C:\\Windows\\System32\\drivers\\etc\\hosts", {"DECLARATION_REFERENCE_INVALID"}),
        ("parent-traversal", "../outside/declaration.yaml", {"DECLARATION_REFERENCE_INVALID"}),
        ("missing-file", "configs/sourceops/definitely_missing.yaml", {"DECLARATION_REFERENCE_INVALID"}),
    ]

    for case_id, new_path, expected_codes in invalid_cases:
        payload = copy.deepcopy(base)
        mutable_ref = _first_declaration_ref(payload)
        mutable_ref["path"] = new_path
        payload["registry_content_hash"] = _canonical_registry_hash(payload)
        probe = tmp_path / f"ac06_{case_id}.yaml"
        _write_yaml(probe, payload)
        result = _run_validate(probe)
        assert result.returncode == 2, f"{case_id}: {result.stderr or result.stdout}"
        report = _parse_json_report(result)
        _assert_error_codes(report, expected_codes)

    drift_payload = copy.deepcopy(base)
    drift_ref = _first_declaration_ref(drift_payload)
    drift_ref["canonical_lf_sha256"] = "0" * 64
    drift_payload["registry_content_hash"] = _canonical_registry_hash(drift_payload)
    drift_probe = tmp_path / "ac06_hash_drift.yaml"
    _write_yaml(drift_probe, drift_payload)
    drift_result = _run_validate(drift_probe)
    assert drift_result.returncode == 2, drift_result.stderr or drift_result.stdout
    drift_report = _parse_json_report(drift_result)
    _assert_error_codes(drift_report, {"DECLARATION_DRIFT"})

    outside_target = tmp_path / "outside_decl.yaml"
    outside_target.write_text("schema: synthetic\nvalue: 1\r\n", encoding="utf-8")
    link_path = REPO_ROOT / "tests" / "sourceops" / "_tmp_symlink_escape.yaml"
    try:
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        os.symlink(outside_target, link_path)
    except (AttributeError, NotImplementedError, OSError):
        pytest.skip("Symlink/junction escape probe unavailable on this platform or permission set")
    try:
        escaped_payload = copy.deepcopy(base)
        escaped_ref = _first_declaration_ref(escaped_payload)
        escaped_ref["path"] = str(link_path.relative_to(REPO_ROOT)).replace("\\", "/")
        escaped_ref["canonical_lf_sha256"] = _canonical_lf_sha256(outside_target)
        escaped_payload["registry_content_hash"] = _canonical_registry_hash(escaped_payload)
        escaped_probe = tmp_path / "ac06_symlink_escape.yaml"
        _write_yaml(escaped_probe, escaped_payload)
        escaped_result = _run_validate(escaped_probe)
        assert escaped_result.returncode == 2, escaped_result.stderr or escaped_result.stdout
        escaped_report = _parse_json_report(escaped_result)
        _assert_error_codes(escaped_report, {"DECLARATION_REFERENCE_INVALID"})
    finally:
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()


def test_ac06_component_declaration_locator_matrix_is_fail_closed(tmp_path: Path) -> None:
    base = _load_registry_payload()
    absolute_probe = f"{(REPO_ROOT / 'configs' / 'ingest' / 'tsc.yaml').resolve()}#assembly"
    invalid_cases: list[tuple[str, str]] = [
        ("absolute-path", absolute_probe),
        ("drive-path", "C:\\Windows\\System32\\drivers\\etc\\hosts#anything"),
        ("parent-traversal", "../outside/declaration.yaml#assembly"),
        ("external-uri", "https://example.invalid/sourceops/declaration.yaml#assembly"),
        ("missing-file", "configs/sourceops/definitely_missing.yaml#assembly"),
        ("missing-key", "configs/ingest/tsc.yaml#reference_checksums.DOES_NOT_EXIST"),
        ("invalid-list-index", "configs/eval/core_annotation_bundle.yaml#data_sources[not-an-index]"),
        ("out-of-range-list-index", "configs/eval/core_annotation_bundle.yaml#data_sources[999]"),
    ]

    violations: list[str] = []
    for case_id, locator in invalid_cases:
        payload = copy.deepcopy(base)
        component = _first_component(payload)
        component["declaration_locator"] = locator
        payload["registry_content_hash"] = _canonical_registry_hash(payload)
        probe_path = tmp_path / f"ac06_component_locator_{case_id}.yaml"
        _write_yaml(probe_path, payload)

        result = _run_validate(probe_path)
        report = _parse_json_report(result)
        codes = _error_codes(report)
        entries = _error_entries(report)
        has_typed_locator_error = any(
            entry.get("code") == "DECLARATION_REFERENCE_INVALID"
            and isinstance(entry.get("type"), str)
            and bool(entry.get("type"))
            for entry in entries
        )
        if result.returncode != 2:
            violations.append(f"{case_id}: expected validate exit 2, got {result.returncode}")
        if report.get("registry_valid") is not False:
            violations.append(f"{case_id}: registry_valid must be false for invalid component locator")
        if "DECLARATION_REFERENCE_INVALID" not in codes:
            violations.append(f"{case_id}: expected DECLARATION_REFERENCE_INVALID, got {sorted(codes)}")
        if not has_typed_locator_error:
            violations.append(f"{case_id}: expected typed DECLARATION_REFERENCE_INVALID entry, got {entries}")
        if "REGISTRY_HASH_MISMATCH" in codes:
            violations.append(f"{case_id}: failure must not depend on stale hash")

    assert not violations, "Component declaration_locator fail-closed violations:\n" + "\n".join(violations)


def test_ac06_non_utf8_declaration_content_is_typed_invalid(tmp_path: Path) -> None:
    from raptor.sourceops.registry import validate_registry

    payload = _load_registry_payload()
    ref = _first_declaration_ref(payload)

    fixture_root = tmp_path / "utf8-boundary-repo"
    fixture_rel_path = Path("tests/sourceops/fixtures/non_utf8_declaration_probe.bin")
    fixture_path = fixture_root / fixture_rel_path
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_bytes(b"\xff\xfe\xfdsourceops-non-utf8-probe")

    ref["path"] = str(fixture_rel_path).replace("\\", "/")
    ref["canonical_lf_sha256"] = "0" * 64
    payload["registry_content_hash"] = _canonical_registry_hash(payload)

    try:
        result = validate_registry(payload, repo_root=fixture_root)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        pytest.fail(f"validate_registry must return typed errors for undecodable declaration content, raised {exc!r}")

    report = result.as_report()
    assert result.registry_valid is False
    codes = _error_codes(report)
    assert codes.intersection({"DECLARATION_REFERENCE_INVALID", "REGISTRY_SCHEMA_ERROR"}), (
        "non-UTF-8 declaration content must fail with typed schema/declaration errors"
    )
    entries = _error_entries(report)
    assert any(
        isinstance(entry.get("code"), str)
        and entry["code"] in {"DECLARATION_REFERENCE_INVALID", "REGISTRY_SCHEMA_ERROR"}
        and isinstance(entry.get("type"), str)
        and bool(entry.get("type"))
        for entry in entries
    ), f"expected typed declaration/schema error entry, got {entries}"


def test_ac07_graph_symmetry_and_unknown_predecessor_probes(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    records = payload.get("source_records")
    consumers = payload.get("consumers")
    assert isinstance(records, list) and isinstance(consumers, list)

    source_ids = {record.get("source_id") for record in records if isinstance(record, dict)}
    consumer_map = {
        consumer.get("consumer_id"): consumer
        for consumer in consumers
        if isinstance(consumer, dict) and isinstance(consumer.get("consumer_id"), str)
    }
    assert len(source_ids) == len([s for s in source_ids if isinstance(s, str)])

    for record in records:
        if not isinstance(record, dict):
            continue
        source_id = record.get("source_id")
        linked_consumers = record.get("consumers")
        assert isinstance(linked_consumers, list), f"{source_id!r} must declare source-to-consumer edges"
        for consumer_id in linked_consumers:
            assert consumer_id in consumer_map, f"Unknown consumer edge from source {source_id!r}: {consumer_id!r}"
            required = consumer_map[consumer_id].get("required_sources")
            assert isinstance(required, list)
            assert source_id in required, (
                f"Consumer {consumer_id!r} must reciprocally declare required source {source_id!r}"
            )
        rollback = record.get("rollback")
        assert isinstance(rollback, dict)
        predecessor = rollback.get("predecessor_source_id")
        if predecessor is not None:
            assert predecessor in source_ids, f"{source_id!r} rollback predecessor must exist in source_records"

    for consumer_id, consumer in consumer_map.items():
        required = consumer.get("required_sources")
        assert isinstance(required, list)
        for source_id in required:
            assert source_id in source_ids, f"consumer {consumer_id!r} references unknown source {source_id!r}"
            linked = next(
                (record.get("consumers") for record in records if isinstance(record, dict) and record.get("source_id") == source_id),
                None,
            )
            assert isinstance(linked, list), f"source {source_id!r} must list consumer edges"
            assert consumer_id in linked, (
                f"source {source_id!r} must include consumer {consumer_id!r} in source_record.consumers"
            )

    probe_payload = copy.deepcopy(payload)
    probe_record = _first_source_record(probe_payload)
    rollback = probe_record.get("rollback")
    if not isinstance(rollback, dict):
        pytest.fail("source_record.rollback must be a mapping for unknown predecessor probe")
    rollback["predecessor_source_id"] = "unknown-predecessor-source-id"
    probe_payload["registry_content_hash"] = _canonical_registry_hash(probe_payload)
    probe_path = tmp_path / "ac07_unknown_predecessor_probe.yaml"
    _write_yaml(probe_path, probe_payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"DANGLING_CONSUMER_OR_SOURCE"})


def test_ac07_lineage_rejects_cross_source_predecessor_chain_when_target_id_exists(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    mutated = copy.deepcopy(payload)
    records = mutated.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    target = next((row for row in records if isinstance(row, dict)), None)
    if target is None:
        pytest.fail("lineage probe requires at least one source record")
    target_id = target.get("source_id")
    if not isinstance(target_id, str):
        pytest.fail("lineage probe requires target source_id")
    predecessor_id = next(
        (
            row.get("source_id")
            for row in records
            if isinstance(row, dict)
            and isinstance(row.get("source_id"), str)
            and row.get("source_id") != target_id
        ),
        None,
    )
    if not isinstance(predecessor_id, str):
        pytest.fail("lineage probe requires an existing unrelated predecessor id")
    rollback = target.get("rollback")
    if not isinstance(rollback, dict):
        pytest.fail("source_record.rollback must be a mapping for lineage probe")
    rollback["predecessor_source_id"] = predecessor_id
    rollback["origin_reason"] = "synthetic cross-source predecessor chain probe"
    mutated["registry_content_hash"] = _canonical_registry_hash(mutated)
    probe_path = tmp_path / "ac07_cross_source_predecessor_chain.yaml"
    _write_yaml(probe_path, mutated)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"IMMUTABLE_HISTORY_VIOLATION"})


def test_ac07_immutable_predecessor_must_reference_prior_immutable_lineage_member(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    target = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    mutable_predecessor = _source_record_by_id(payload, "tsc-ingest-and-reference-declarations")
    mutable_predecessor_id = mutable_predecessor.get("source_id")
    if not isinstance(mutable_predecessor_id, str):
        pytest.fail("mutable predecessor probe requires source_id")
    mutable_predecessor["authoritative_locator"] = str(target.get("authoritative_locator"))
    mutable_predecessor["lifecycle_state"] = "CONFIRM_PENDING"
    mutable_predecessor["blocked_reasons"] = ["synthetic predecessor remains pending and mutable"]
    mutable_predecessor["missing_inputs"] = ["independent immutable historical attestation"]
    mutable_predecessor["unblock_condition"] = "independent historical attestation completed"
    mutable_predecessor["reviewed_by"] = "sourceops-contract-test"
    mutable_predecessor["reviewed_at"] = "2026-08-16T00:00:00Z"

    target_rollback = target.get("rollback")
    if not isinstance(target_rollback, dict):
        pytest.fail("target rollback mapping required for immutable predecessor probe")
    target_rollback["predecessor_source_id"] = mutable_predecessor_id
    target_rollback["origin_reason"] = "synthetic predecessor probe"

    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac07_mutable_predecessor_probe.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"IMMUTABLE_HISTORY_VIOLATION"})


@pytest.mark.parametrize(
    "field,bad_value",
    [("last_checked_at", "not-a-timestamp"), ("freshness_sla", "not-a-duration")],
    ids=["malformed-last-checked-at", "malformed-freshness-sla"],
)
def test_ac07_refresh_fields_require_typed_timestamp_and_sla_values(
    tmp_path: Path, field: str, bad_value: str
) -> None:
    payload = _load_registry_payload()
    record = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    refresh = record.get("refresh")
    if not isinstance(refresh, dict):
        pytest.fail("refresh mapping required for typed freshness probe")
    refresh[field] = bad_value
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / f"ac07_typed_refresh_{field}.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"REGISTRY_SCHEMA_ERROR", "SOURCE_METADATA_INCOMPLETE"})


def test_ac11_typed_immutable_public_model_contract() -> None:
    import raptor.sourceops.model as model_mod
    from raptor.sourceops.registry import load_registry

    model = _registry_model_spec()
    top_required = set(model["top_level_required"])
    source_required = set(model["source_record_required"])
    component_required = set(model["component_required"])
    ref_required = set(model["declaration_reference"]["required"])

    public_classes = [
        obj
        for obj in vars(model_mod).values()
        if inspect.isclass(obj) and obj.__module__ == model_mod.__name__
    ]

    def model_hints(cls: type[Any]) -> dict[str, Any]:
        try:
            return dict(get_type_hints(cls, include_extras=True))
        except Exception:  # pragma: no cover - fallback for dynamic model surfaces
            annotations = getattr(cls, "__annotations__", {})
            return dict(annotations) if isinstance(annotations, dict) else {}

    def find_model(required_fields: set[str]) -> tuple[type[Any], dict[str, Any]]:
        for cls in public_classes:
            hints = model_hints(cls)
            if required_fields.issubset(set(hints)):
                return cls, hints
        raise AssertionError(
            f"No public typed model contains required fields {sorted(required_fields)}. "
            "Contract requires typed immutable Python model objects."
        )

    registry_cls, registry_hints = find_model(top_required)
    source_cls, source_hints = find_model(source_required)
    component_cls, component_hints = find_model(component_required)
    ref_cls, ref_hints = find_model(ref_required)

    for cls, hints, required_fields in (
        (registry_cls, registry_hints, top_required),
        (source_cls, source_hints, source_required),
        (component_cls, component_hints, component_required),
        (ref_cls, ref_hints, ref_required),
    ):
        assert required_fields.issubset(set(hints)), f"{cls.__name__} missing required typed fields"
        for field_name in sorted(required_fields):
            hint = hints[field_name]
            assert hint is not Any, f"{cls.__name__}.{field_name} must be typed, not Any"
            if hint in {dict, list, tuple, set}:
                raise AssertionError(
                    f"{cls.__name__}.{field_name} must use parameterized typing, not bare {hint!r}"
                )

    loaded = load_registry(REGISTRY_PATH)
    assert not isinstance(loaded, dict), "load_registry must return typed immutable model, not raw dict"

    def object_field_names(obj: Any) -> set[str]:
        names: set[str] = set()
        cls = type(obj)
        hints = model_hints(cls)
        names.update(hints)
        if dataclasses.is_dataclass(obj):
            names.update(field.name for field in dataclasses.fields(obj))
        dynamic = getattr(obj, "__dict__", None)
        if isinstance(dynamic, dict):
            names.update(key for key in dynamic if not key.startswith("_"))
        namedtuple_fields = getattr(obj, "_fields", None)
        if isinstance(namedtuple_fields, tuple):
            names.update(str(name) for name in namedtuple_fields)
        return names

    def assert_immutable_object(obj: Any, *, label: str) -> None:
        field_names = sorted(object_field_names(obj))
        if not field_names:
            pytest.fail(f"{label} must expose typed fields for immutability checks")
        target = field_names[0]
        marker = object()
        mutation_error_types = (AttributeError, TypeError, dataclasses.FrozenInstanceError, RuntimeError, ValueError)
        with pytest.raises(mutation_error_types):
            setattr(obj, target, marker)
        if hasattr(obj, "__setitem__"):
            with pytest.raises(Exception):
                obj[target] = marker  # type: ignore[index]

    def assert_immutable_sequence(value: Any, *, label: str) -> None:
        assert not isinstance(value, list), f"{label} must be immutable; mutable list is not allowed"
        if isinstance(value, tuple) and value:
            with pytest.raises(TypeError):
                value[0] = value[0]  # type: ignore[index]
        if hasattr(value, "append"):
            with pytest.raises(Exception):
                value.append(object())  # type: ignore[attr-defined]

    visited: set[int] = set()

    def assert_recursive_immutability(obj: Any, *, label: str, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(obj, (str, bytes, int, float, bool, type(None))):
            return
        obj_id = id(obj)
        if obj_id in visited:
            return
        visited.add(obj_id)

        if isinstance(obj, dict):
            pytest.fail(f"{label} must not expose mutable dict payloads in typed model")
        if isinstance(obj, (list, tuple)):
            assert_immutable_sequence(obj, label=label)
            for idx, item in enumerate(obj):
                assert_recursive_immutability(item, label=f"{label}[{idx}]", depth=depth + 1)
            return

        assert_immutable_object(obj, label=label)
        for field_name in sorted(object_field_names(obj)):
            if field_name.startswith("_") or not hasattr(obj, field_name):
                continue
            try:
                value = getattr(obj, field_name)
            except Exception:  # pragma: no cover
                continue
            if isinstance(value, (list, tuple)):
                assert_immutable_sequence(value, label=f"{label}.{field_name}")
            if isinstance(value, dict):
                pytest.fail(f"{label}.{field_name} must be typed immutable state, not dict")
            assert_recursive_immutability(value, label=f"{label}.{field_name}", depth=depth + 1)

    loaded_fields = object_field_names(loaded)
    assert top_required.issubset(loaded_fields), "loaded registry model must expose required top-level fields"
    assert_recursive_immutability(loaded, label=type(loaded).__name__)

    source_records_value = getattr(loaded, "source_records", None)
    assert isinstance(source_records_value, (list, tuple)), "typed registry model must expose source_records sequence"
    assert source_records_value, "source_records must not be empty"
    source_obj = source_records_value[0]
    assert not isinstance(source_obj, dict), "source_records entries must be typed immutable objects, not dict rows"
    assert source_required.issubset(object_field_names(source_obj))

    refs_value = getattr(source_obj, "declaration_refs", None)
    assert isinstance(refs_value, (list, tuple)) and refs_value, "source model must include declaration_refs sequence"
    ref_obj = refs_value[0]
    assert not isinstance(ref_obj, dict), "declaration_refs entries must be typed immutable objects, not dict rows"
    assert ref_required.issubset(object_field_names(ref_obj))

    component_candidates = [
        component
        for candidate_source in source_records_value
        if not isinstance(candidate_source, dict)
        for component in (getattr(candidate_source, "components", None) or [])
    ]
    if component_candidates:
        component_obj = component_candidates[0]
        assert not isinstance(component_obj, dict), "component entries must be typed immutable objects, not dict rows"
        assert component_required.issubset(object_field_names(component_obj))


def test_fm2_domain_authority_drift_is_fail_closed_and_non_mutating(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    ref = _first_declaration_ref(payload)
    ref_path = REPO_ROOT / Path(ref["path"])
    before_bytes = ref_path.read_bytes()
    ref["canonical_lf_sha256"] = "f" * 64
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "fm2_drift_probe.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"DECLARATION_DRIFT"})
    assert ref_path.read_bytes() == before_bytes, "validate must not rewrite domain declarations"


def test_fm3_pinned_historical_record_cannot_refresh_in_place(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    record = next(
        (row for row in records if isinstance(row, dict) and row.get("lifecycle_state") == "PINNED_HISTORICAL"),
        None,
    )
    if record is None:
        pytest.fail("Baseline must include a PINNED_HISTORICAL record for FM3 probe")
    refresh = record.get("refresh")
    if not isinstance(refresh, dict):
        pytest.fail("source_record.refresh must be a mapping")
    refresh["cadence"] = "daily"
    refresh["next_check_rule"] = "daily"
    rollback = record.get("rollback")
    if not isinstance(rollback, dict):
        pytest.fail("source_record.rollback must be a mapping")
    rollback["immutable_predecessor_required"] = False
    rollback["origin_reason"] = "FM3 mutation probe"
    if rollback.get("predecessor_source_id") is None:
        rollback["predecessor_source_id"] = "historical-probe-predecessor"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "fm3_mutable_historical_probe.yaml"
    _write_yaml(probe_path, payload)

    result = _run_validate(probe_path)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json_report(result)
    _assert_error_codes(report, {"IMMUTABLE_HISTORY_VIOLATION"})
    _assert_typed_errors(report)


def test_contract_coverage_map_is_complete() -> None:
    assert set(AC_FM_TO_TEST) == EXPECTED_AC_FM_IDS
    assert all(isinstance(v, str) and v for v in AC_FM_TO_TEST.values())
    assert VALIDATION_CEILING
