from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-kickoff.yaml"
REGISTRY_PATH = REPO_ROOT / "configs" / "sourceops" / "source_registry.yaml"
VALIDATION_SCHEMA_ID = "raptor.source_registry.validation.v1"
VALIDATION_CEILING = (
    "V2 can establish that source lifecycle metadata and change-impact routing "
    "are complete, deterministic, and fail-closed. It cannot establish that a "
    "source is scientifically sufficient, that a criterion is valid, that a "
    "variant direction is correct, or that any clinical or research scope is "
    "authorized."
)


def _first_slice_spec() -> dict[str, Any]:
    kickoff = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    if not isinstance(kickoff, dict) or not isinstance(kickoff.get("first_implementation_slice"), dict):
        pytest.fail("Kickoff spec must include first_implementation_slice")
    return kickoff["first_implementation_slice"]


def _load_registry_payload() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        pytest.fail(f"SourceOps registry file is not implemented: {REGISTRY_PATH}")
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        pytest.fail("source_registry.yaml must parse into a mapping")
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


def _write_probe_registry(path: Path, payload: dict[str, Any]) -> None:
    dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    path.write_text(dumped, encoding="utf-8")


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


def _run_status(registry_path: Path, consumer_id: str) -> subprocess.CompletedProcess[str]:
    return _run_cli("status", "--registry", str(registry_path), "--consumer", consumer_id)


def _parse_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if not result.stdout.strip():
        pytest.fail(
            "CLI stdout must contain JSON.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover
        pytest.fail(f"stdout is not valid JSON: {exc}\nstdout={result.stdout!r}\nstderr={result.stderr!r}")
    if not isinstance(payload, dict):
        pytest.fail("CLI payload must be a JSON object")
    return payload


def _error_codes(report: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    if isinstance(report.get("errors"), list):
        for err in report["errors"]:
            if isinstance(err, dict) and isinstance(err.get("code"), str):
                codes.add(err["code"])
    if isinstance(report.get("error"), dict) and isinstance(report["error"].get("code"), str):
        codes.add(report["error"]["code"])
    for key in ("code", "error_code", "failure_code"):
        value = report.get(key)
        if isinstance(value, str):
            codes.add(value)
    return {code for code in codes if code}


def _first_consumer_with_required_sources(payload: dict[str, Any]) -> tuple[str, str]:
    consumers = payload.get("consumers")
    if not isinstance(consumers, list):
        pytest.fail("registry consumers must be a list")
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        consumer_id = consumer.get("consumer_id")
        required = consumer.get("required_sources")
        if isinstance(consumer_id, str) and isinstance(required, list) and required:
            source_id = required[0]
            if isinstance(source_id, str):
                return consumer_id, source_id
    pytest.fail("Expected at least one consumer with non-empty required_sources")


def _source_record_by_id(payload: dict[str, Any], source_id: str) -> dict[str, Any]:
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("registry source_records must be a list")
    for record in records:
        if isinstance(record, dict) and record.get("source_id") == source_id:
            return record
    pytest.fail(f"required source_id {source_id!r} not found in source_records")


def _consumer_by_id(payload: dict[str, Any], consumer_id: str) -> dict[str, Any] | None:
    consumers = payload.get("consumers")
    if not isinstance(consumers, list):
        pytest.fail("registry consumers must be a list")
    for consumer in consumers:
        if isinstance(consumer, dict) and consumer.get("consumer_id") == consumer_id:
            return consumer
    return None


def _consumer_state(report: dict[str, Any]) -> str | None:
    state = report.get("consumer_state")
    if isinstance(state, str):
        return state
    consumer = report.get("consumer")
    if isinstance(consumer, dict):
        inner = consumer.get("state")
        if isinstance(inner, str):
            return inner
    return None


def _append_synthetic_verified_source_and_consumer(
    payload: dict[str, Any], *, source_id: str, consumer_id: str, freshness_required: bool
) -> tuple[str, str]:
    records = payload.get("source_records")
    consumers = payload.get("consumers")
    if not isinstance(records, list) or not isinstance(consumers, list):
        pytest.fail("registry must expose list-valued source_records and consumers")

    probe_ref_path = "docs/project/specs/raptor-v2-kickoff.yaml"
    probe_ref_file = REPO_ROOT / Path(probe_ref_path)
    normalized = probe_ref_file.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    ref_copy = {
        "path": probe_ref_path,
        "role": "derived_probe_reference",
        "canonical_lf_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "authority_scope": "repository",
    }

    source_row = {
        "source_id": source_id,
        "display_name": "Synthetic verified probe source",
        "record_kind": "SINGLE_SOURCE",
        "lifecycle_state": "VERIFIED_ACTIVE",
        "owner": "sourceops-contract-test",
        "authoritative_locator": probe_ref_path,
        "declaration_refs": [ref_copy],
        "licence": {
            "status": "verified",
            "identifier_or_family": "synthetic-probe-source",
            "terms_locator": f"{probe_ref_path}#first_implementation_slice",
            "permitted_use": "verified_for_declared_use",
            "redistribution": "restricted_by_operator_policy",
            "cloud_egress": "forbidden",
            "verification_basis": "synthetic_contract_probe",
        },
        "release": {
            "version_or_snapshot": "synthetic-v1",
            "release_date": "2026-08-16",
            "retrieved_at": "2026-08-16T00:00:00Z",
            "content_pin_status": "hash_bound_probe",
        },
        "acquisition": {
            "method": "synthetic_contract_probe",
            "operator_contract": "no_network_fetching",
            "writes_outside_repository": False,
        },
        "refresh": {
            "cadence": "manual",
            "freshness_sla": "P30D",
            "last_checked_at": "2026-08-16T00:00:00Z",
            "next_check_rule": "manual operator review",
        },
        "consumers": [consumer_id],
        "drift_policy": {
            "materiality_basis": "synthetic probe only",
            "actions": [
                "record_only",
                "block_consumer",
                "stage_diff",
                "rebuild_benchmark",
                "review_policy",
                "invalidate_packets",
                "reground_atlas",
                "rerun_validation",
                "rollback",
            ],
            "approval_required": True,
        },
        "rollback": {
            "predecessor_source_id": None,
            "immutable_predecessor_required": True,
            "rollback_artifact": "configs/sourceops/rollbacks/synthetic-ready-source.yaml",
            "origin_reason": "synthetic lineage root for FM1/freshness contract probe",
        },
    }

    consumer_row = {
        "consumer_id": consumer_id,
        "owner": "sourceops-contract-test",
        "required_sources": [source_id],
        "freshness_required": freshness_required,
        "on_blocked_source": "block_consumer",
        "forbidden_source_roles": [],
    }

    records.append(source_row)
    consumers.append(consumer_row)
    return consumer_id, source_id


def _mutate_immutable_history_violation(payload: dict[str, Any]) -> str:
    record = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    refresh = record.get("refresh")
    if not isinstance(refresh, dict):
        pytest.fail("immutable-history probe requires refresh mapping")
    refresh["cadence"] = "daily"
    refresh["next_check_rule"] = "daily refresh tick"
    rollback = record.get("rollback")
    if not isinstance(rollback, dict):
        pytest.fail("immutable-history probe requires rollback mapping")
    rollback["immutable_predecessor_required"] = False
    return "eval-gate"


def _mutate_source_metadata_incomplete(payload: dict[str, Any]) -> str:
    record = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    licence = record.get("licence")
    if not isinstance(licence, dict):
        pytest.fail("source-metadata probe requires licence mapping")
    licence["permitted_use"] = "policy_only_reuse_permitted_now"
    return "eval-gate"


def _mutate_forbidden_role_flow(payload: dict[str, Any]) -> str:
    eval_gate = next(
        (
            consumer
            for consumer in payload.get("consumers", [])
            if isinstance(consumer, dict) and consumer.get("consumer_id") == "eval-gate"
        ),
        None,
    )
    if eval_gate is None:
        pytest.fail("forbidden-role probe requires eval-gate consumer")
    required = eval_gate.get("required_sources")
    if not isinstance(required, list):
        pytest.fail("eval-gate required_sources must be a list for forbidden-role probe")
    if "atlas-tsc2-catalog-template" not in required:
        required.append("atlas-tsc2-catalog-template")

    catalog = _source_record_by_id(payload, "atlas-tsc2-catalog-template")
    linked = catalog.get("consumers")
    if not isinstance(linked, list):
        catalog["consumers"] = ["eval-gate"]
    elif "eval-gate" not in linked:
        linked.append("eval-gate")
    return "eval-gate"


def test_ac08_cli_json_determinism_and_exit_contract() -> None:
    if not REGISTRY_PATH.exists():
        pytest.fail(f"SourceOps registry file is not implemented: {REGISTRY_PATH}")
    first_slice = _first_slice_spec()
    minimum_commands = first_slice["test_contract"]["minimum_commands"]
    commands_text = "\n".join(command["command"] for command in minimum_commands if isinstance(command, dict))
    assert "python -m raptor.sourceops.cli validate --registry" in commands_text
    assert "python -m raptor.sourceops.cli status --registry" in commands_text

    validate_first = _run_validate(REGISTRY_PATH)
    validate_second = _run_validate(REGISTRY_PATH)
    assert validate_first.returncode == 0, validate_first.stderr or validate_first.stdout
    assert validate_second.returncode == 0, validate_second.stderr or validate_second.stdout
    assert validate_first.stdout == validate_second.stdout, "validate JSON must be byte-deterministic"

    validate_report = _parse_json(validate_first)
    assert validate_report.get("schema") == VALIDATION_SCHEMA_ID
    assert validate_report.get("registry_valid") is True

    status_first = _run_status(REGISTRY_PATH, "eval-gate")
    status_second = _run_status(REGISTRY_PATH, "eval-gate")
    assert status_first.returncode == 0, status_first.stderr or status_first.stdout
    assert status_second.returncode == 0, status_second.stderr or status_second.stdout
    assert status_first.stdout == status_second.stdout, "status JSON must be byte-deterministic"

    status_report = _parse_json(status_first)
    assert status_report.get("schema") == VALIDATION_SCHEMA_ID
    assert _consumer_state(status_report) == "READY"


def test_ac08_status_distinguishes_malformed_registry_from_blocked_consumer(tmp_path: Path) -> None:
    payload = _load_registry_payload()

    malformed = copy.deepcopy(payload)
    malformed["registry_content_hash"] = "0" * 64
    malformed_path = tmp_path / "malformed_hash.yaml"
    _write_probe_registry(malformed_path, malformed)

    malformed_consumer, _ = _first_consumer_with_required_sources(payload)
    malformed_status = _run_status(malformed_path, malformed_consumer)
    assert malformed_status.returncode == 2, malformed_status.stderr or malformed_status.stdout
    malformed_report = _parse_json(malformed_status)
    assert "REGISTRY_HASH_MISMATCH" in _error_codes(malformed_report)

    blocked = copy.deepcopy(payload)
    consumer_id, source_id = _first_consumer_with_required_sources(blocked)
    record = _source_record_by_id(blocked, source_id)
    record["lifecycle_state"] = "CONFIRM_PENDING"
    record["blocked_reasons"] = ["verification inputs incomplete"]
    record["missing_inputs"] = ["content pin", "permission confirmation"]
    record["unblock_condition"] = "operator confirms missing inputs"
    record["reviewed_by"] = "contract-test"
    record["reviewed_at"] = "2026-08-16T00:00:00Z"
    blocked["registry_content_hash"] = _canonical_registry_hash(blocked)

    blocked_path = tmp_path / "blocked_consumer.yaml"
    _write_probe_registry(blocked_path, blocked)
    blocked_validate = _run_validate(blocked_path)
    assert blocked_validate.returncode == 0, blocked_validate.stderr or blocked_validate.stdout
    blocked_status = _run_status(blocked_path, consumer_id)
    assert blocked_status.returncode == 3, blocked_status.stderr or blocked_status.stdout
    blocked_report = _parse_json(blocked_status)
    assert _consumer_state(blocked_report) == "BLOCKED"


def test_ac07_duplicate_consumer_id_must_invalidate_registry_and_never_launder_ready(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    consumers = payload.get("consumers")
    if not isinstance(consumers, list):
        pytest.fail("registry consumers must be a list")

    blocked_consumer = _consumer_by_id(payload, "ingest")
    if blocked_consumer is None:
        pytest.fail("duplicate consumer probe requires baseline ingest consumer")
    required_sources = blocked_consumer.get("required_sources")
    if not isinstance(required_sources, list) or "tsc-ingest-and-reference-declarations" not in required_sources:
        pytest.fail("baseline ingest consumer must remain bound to blocked ingest source")
    if "frozen-core-annotation-bundle" not in required_sources:
        required_sources.append("frozen-core-annotation-bundle")

    duplicate = copy.deepcopy(blocked_consumer)
    duplicate["required_sources"] = ["frozen-core-annotation-bundle"]
    ingest_index = next(
        (
            idx
            for idx, consumer in enumerate(consumers)
            if isinstance(consumer, dict) and consumer.get("consumer_id") == "ingest"
        ),
        None,
    )
    if ingest_index is None:
        pytest.fail("duplicate consumer probe requires ingest index in consumers list")
    consumers.insert(ingest_index, duplicate)

    permissive_source = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    linked_consumers = permissive_source.get("consumers")
    if not isinstance(linked_consumers, list):
        permissive_source["consumers"] = ["ingest"]
    elif "ingest" not in linked_consumers:
        linked_consumers.append("ingest")

    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac07_duplicate_consumer_id_laundering_probe.yaml"
    _write_probe_registry(probe_path, payload)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 2, validate_result.stderr or validate_result.stdout
    validate_report = _parse_json(validate_result)
    assert validate_report.get("registry_valid") is False
    validate_codes = _error_codes(validate_report)
    assert validate_codes, validate_report
    assert "REGISTRY_HASH_MISMATCH" not in validate_codes
    validate_errors = validate_report.get("errors")
    assert isinstance(validate_errors, list) and validate_errors, validate_report
    duplicate_markers = {"consumer_id", "consumer id", "consumer-id"}
    assert any(
        isinstance(entry, dict)
        and entry.get("code") == "REGISTRY_SCHEMA_ERROR"
        and isinstance(entry.get("type"), str)
        and bool(entry.get("type"))
        and "duplicate" in str(entry.get("message", "")).lower()
        and any(marker in str(entry.get("message", "")).lower() for marker in duplicate_markers)
        for entry in validate_errors
    ), validate_errors

    status_result = _run_status(probe_path, "ingest")
    assert status_result.returncode == 2, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert status_report.get("registry_valid") is False
    assert _consumer_state(status_report) == "INVALID"
    status_codes = _error_codes(status_report)
    assert status_codes, status_report
    status_errors = status_report.get("errors")
    assert isinstance(status_errors, list) and status_errors, status_report
    assert any(
        isinstance(entry, dict)
        and isinstance(entry.get("code"), str)
        and bool(entry.get("code"))
        and isinstance(entry.get("type"), str)
        and bool(entry.get("type"))
        and "duplicate" in str(entry.get("message", "")).lower()
        and any(marker in str(entry.get("message", "")).lower() for marker in duplicate_markers)
        for entry in status_errors
    ), status_errors
    assert not (status_result.returncode == 0 and _consumer_state(status_report) == "READY"), (
        "duplicate consumer_id must never be resolved as READY/0"
    )


def test_ac08_component_locator_yaml_parse_failure_is_typed_and_deterministic(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    source = _source_record_by_id(payload, "tsc-ingest-and-reference-declarations")
    components = source.get("components")
    if not isinstance(components, list):
        pytest.fail("component locator parse probe requires ingest components list")
    target = next(
        (
            component
            for component in components
            if isinstance(component, dict) and component.get("component_id") == "tsc-ingest-clinvar-snapshot-id"
        ),
        None,
    )
    if target is None:
        pytest.fail("component locator parse probe requires tsc-ingest-clinvar-snapshot-id component")
    target["declaration_locator"] = "README.md#sourceops.non_yaml_locator_probe"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac08_component_locator_yaml_parse_probe.yaml"
    _write_probe_registry(probe_path, payload)

    validate_first = _run_validate(probe_path)
    validate_second = _run_validate(probe_path)
    assert validate_first.returncode == 2, validate_first.stderr or validate_first.stdout
    assert validate_second.returncode == 2, validate_second.stderr or validate_second.stdout
    assert validate_first.stdout == validate_second.stdout, (
        "YAML parse failures must produce byte-deterministic typed validate JSON"
    )
    assert "Traceback" not in validate_first.stderr, validate_first.stderr
    validate_report = _parse_json(validate_first)
    assert validate_report.get("registry_valid") is False
    validate_codes = _error_codes(validate_report)
    assert validate_codes.intersection({"DECLARATION_REFERENCE_INVALID", "REGISTRY_SCHEMA_ERROR"}), validate_report

    status_first = _run_status(probe_path, "eval-gate")
    status_second = _run_status(probe_path, "eval-gate")
    assert status_first.returncode == 2, status_first.stderr or status_first.stdout
    assert status_second.returncode == 2, status_second.stderr or status_second.stdout
    assert status_first.stdout == status_second.stdout, (
        "YAML parse failures must produce byte-deterministic typed status JSON"
    )
    assert "Traceback" not in status_first.stderr, status_first.stderr
    status_report = _parse_json(status_first)
    assert status_report.get("registry_valid") is False
    assert _consumer_state(status_report) == "INVALID"
    status_codes = _error_codes(status_report)
    assert status_codes.intersection({"DECLARATION_REFERENCE_INVALID", "REGISTRY_SCHEMA_ERROR"}), status_report


@pytest.mark.parametrize(
    "mutator,expected_code",
    [
        (_mutate_immutable_history_violation, "IMMUTABLE_HISTORY_VIOLATION"),
        (_mutate_source_metadata_incomplete, "SOURCE_METADATA_INCOMPLETE"),
        (_mutate_forbidden_role_flow, "FORBIDDEN_ROLE_FLOW"),
    ],
    ids=["immutable-history", "source-metadata-incomplete", "forbidden-role-flow"],
)
def test_ac08_status_returns_invalid_exit_2_for_registry_validation_errors(
    tmp_path: Path, mutator: Any, expected_code: str
) -> None:
    payload = _load_registry_payload()
    consumer_id = mutator(payload)
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / f"ac08_status_invalid_{expected_code.lower()}.yaml"
    _write_probe_registry(probe_path, payload)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 2, validate_result.stderr or validate_result.stdout
    validate_report = _parse_json(validate_result)
    assert expected_code in _error_codes(validate_report), (
        f"expected {expected_code} in validate errors, got {sorted(_error_codes(validate_report))}"
    )

    status_result = _run_status(probe_path, consumer_id)
    assert status_result.returncode == 2, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "INVALID"
    assert expected_code in _error_codes(status_report), (
        f"status must retain {expected_code} provenance; got {sorted(_error_codes(status_report))}"
    )


def test_ac08_status_only_blocked_outcomes_remain_exit_3(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    consumer_id, source_id = _append_synthetic_verified_source_and_consumer(
        payload,
        source_id="synthetic-status-blocked-source",
        consumer_id="synthetic-status-blocked-consumer",
        freshness_required=False,
    )
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    ready_path = tmp_path / "ac08_status_blocked_ready_case.yaml"
    _write_probe_registry(ready_path, payload)
    ready_validate = _run_validate(ready_path)
    assert ready_validate.returncode == 0, ready_validate.stderr or ready_validate.stdout
    ready_status = _run_status(ready_path, consumer_id)
    assert ready_status.returncode == 0, ready_status.stderr or ready_status.stdout
    assert _consumer_state(_parse_json(ready_status)) == "READY"

    blocked_payload = copy.deepcopy(payload)
    blocked_source = _source_record_by_id(blocked_payload, source_id)
    blocked_source["lifecycle_state"] = "CONFIRM_PENDING"
    blocked_source["blocked_reasons"] = ["synthetic demotion for blocked-outcome partition probe"]
    blocked_source["missing_inputs"] = ["independent verification input"]
    blocked_source["unblock_condition"] = "verification review complete"
    blocked_source["reviewed_by"] = "sourceops-contract-test"
    blocked_source["reviewed_at"] = "2026-08-16T00:00:00Z"
    blocked_payload["registry_content_hash"] = _canonical_registry_hash(blocked_payload)
    blocked_path = tmp_path / "ac08_status_blocked_case.yaml"
    _write_probe_registry(blocked_path, blocked_payload)
    blocked_validate = _run_validate(blocked_path)
    assert blocked_validate.returncode == 0, blocked_validate.stderr or blocked_validate.stdout
    blocked_status = _run_status(blocked_path, consumer_id)
    assert blocked_status.returncode == 3, blocked_status.stderr or blocked_status.stdout
    assert _consumer_state(_parse_json(blocked_status)) == "BLOCKED"

    reserved_status = _run_status(REGISTRY_PATH, "rescuescreen")
    assert reserved_status.returncode == 3, reserved_status.stderr or reserved_status.stdout
    assert _consumer_state(_parse_json(reserved_status)) == "BLOCKED"


def test_status_unknown_consumer_id_returns_exit_4() -> None:
    if not REGISTRY_PATH.exists():
        pytest.fail(f"SourceOps registry file is not implemented: {REGISTRY_PATH}")
    result = _run_status(REGISTRY_PATH, "consumer-id-that-does-not-exist")
    assert result.returncode == 4, result.stderr or result.stdout
    report = _parse_json(result)
    assert _error_codes(report), "Not-found result must include typed code information"


@pytest.mark.parametrize(
    "invocation",
    [
        ("validate",),
        ("status", "--consumer", "eval-gate"),
    ],
    ids=["validate", "status"],
)
def test_ac08_missing_registry_path_returns_deterministic_typed_json(
    tmp_path: Path, invocation: tuple[str, ...]
) -> None:
    missing_registry = tmp_path / "missing_source_registry.yaml"
    first = _run_cli(*invocation, "--registry", str(missing_registry))
    second = _run_cli(*invocation, "--registry", str(missing_registry))
    assert first.returncode == 2, first.stderr or first.stdout
    assert second.returncode == 2, second.stderr or second.stdout
    assert first.stdout == second.stdout, "missing-registry errors must be deterministic JSON"
    report = _parse_json(first)
    assert "REGISTRY_SCHEMA_ERROR" in _error_codes(report)


@pytest.mark.parametrize(
    "invocation",
    [
        ("validate",),
        ("status", "--consumer", "eval-gate"),
    ],
    ids=["validate", "status"],
)
def test_ac08_unreadable_registry_path_returns_deterministic_typed_json(
    tmp_path: Path, invocation: tuple[str, ...]
) -> None:
    unreadable_registry = tmp_path / "registry_dir"
    unreadable_registry.mkdir()
    first = _run_cli(*invocation, "--registry", str(unreadable_registry))
    second = _run_cli(*invocation, "--registry", str(unreadable_registry))
    assert first.returncode == 2, first.stderr or first.stdout
    assert second.returncode == 2, second.stderr or second.stdout
    assert first.stdout == second.stdout, "unreadable-registry errors must be deterministic JSON"
    report = _parse_json(first)
    assert "REGISTRY_SCHEMA_ERROR" in _error_codes(report)


def test_ac08_unknown_source_exit_4_if_source_query_surface_exists() -> None:
    help_result = _run_cli("--help")
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    has_source_subcommand = " source " in help_text or "{validate,status,source}" in help_text
    if not has_source_subcommand:
        pytest.skip("No source query command is exposed by this CLI surface")
    result = _run_cli("source", "--registry", str(REGISTRY_PATH), "--source", "source-id-that-does-not-exist")
    assert result.returncode == 4, result.stderr or result.stdout
    report = _parse_json(result)
    assert _error_codes(report), "unknown-source result must include typed code information"


def test_ac08_freshness_required_truth_table_stale_blocks_only_freshness_required(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    source = _source_record_by_id(payload, "frozen-core-annotation-bundle")
    refresh = source.get("refresh")
    if not isinstance(refresh, dict):
        pytest.fail("freshness truth-table probe requires refresh mapping")
    refresh["freshness_sla"] = "PT1H"
    refresh["last_checked_at"] = "1999-01-01T00:00:00Z"
    refresh["next_check_rule"] = "hourly freshness check"

    consumers = payload.get("consumers")
    if not isinstance(consumers, list):
        pytest.fail("consumers must be a list")
    probe_consumer = {
        "consumer_id": "freshness-optional-probe",
        "owner": "sourceops-contract-test",
        "required_sources": ["frozen-core-annotation-bundle"],
        "freshness_required": False,
        "on_blocked_source": "block_consumer",
        "forbidden_source_roles": [],
    }
    consumers.append(probe_consumer)
    linked = source.get("consumers")
    if not isinstance(linked, list):
        source["consumers"] = ["freshness-optional-probe"]
    elif "freshness-optional-probe" not in linked:
        linked.append("freshness-optional-probe")

    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "ac08_freshness_truth_table_probe.yaml"
    _write_probe_registry(probe_path, payload)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 0, validate_result.stderr or validate_result.stdout

    stale_required = _run_status(probe_path, "eval-gate")
    assert stale_required.returncode == 3, stale_required.stderr or stale_required.stdout
    stale_required_report = _parse_json(stale_required)
    assert _consumer_state(stale_required_report) == "BLOCKED"
    assert "SOURCE_STALE" in _error_codes(stale_required_report)

    stale_optional = _run_status(probe_path, "freshness-optional-probe")
    assert stale_optional.returncode == 0, stale_optional.stderr or stale_optional.stdout
    stale_optional_report = _parse_json(stale_optional)
    assert _consumer_state(stale_optional_report) == "READY"


def test_ac08_untyped_freshness_sla_cannot_bypass_staleness_or_validation(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    consumer_id, source_id = _append_synthetic_verified_source_and_consumer(
        payload,
        source_id="synthetic-untyped-sla-source",
        consumer_id="synthetic-untyped-sla-consumer",
        freshness_required=True,
    )
    source = _source_record_by_id(payload, source_id)
    refresh = source.get("refresh")
    if not isinstance(refresh, dict):
        pytest.fail("untyped freshness SLA probe requires refresh mapping")
    refresh["freshness_sla"] = "not-stale-for-plan-v2"
    refresh["last_checked_at"] = "1999-01-01T00:00:00Z"
    refresh["next_check_rule"] = "synthetic stale probe"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)

    probe_path = tmp_path / "ac08_untyped_freshness_sla_probe.yaml"
    _write_probe_registry(probe_path, payload)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 2, validate_result.stderr or validate_result.stdout
    validate_report = _parse_json(validate_result)
    assert _error_codes(validate_report).intersection({"REGISTRY_SCHEMA_ERROR", "SOURCE_METADATA_INCOMPLETE"}), (
        "non-typed freshness_sla must fail validation instead of creating a permanent stale exemption"
    )

    status_result = _run_status(probe_path, consumer_id)
    assert status_result.returncode == 2, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "INVALID"


def test_ac08_retired_lifecycle_is_valid_but_non_admissible_for_ready_consumers(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    consumer_id, source_id = _append_synthetic_verified_source_and_consumer(
        payload,
        source_id="synthetic-retired-source",
        consumer_id="synthetic-retired-consumer",
        freshness_required=False,
    )
    source = _source_record_by_id(payload, source_id)
    source["lifecycle_state"] = "RETIRED"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)

    probe_path = tmp_path / "ac08_retired_lifecycle_probe.yaml"
    _write_probe_registry(probe_path, payload)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 0, validate_result.stderr or validate_result.stdout
    validate_report = _parse_json(validate_result)
    assert validate_report.get("registry_valid") is True

    status_result = _run_status(probe_path, consumer_id)
    assert status_result.returncode == 3, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "BLOCKED"
    assert "SOURCE_BLOCKED" in _error_codes(status_report)


def test_fm3_validate_and_status_share_same_invalid_registry_state(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    consumer_id = _mutate_immutable_history_violation(payload)
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe_path = tmp_path / "fm3_validate_status_same_registry.yaml"
    _write_probe_registry(probe_path, payload)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 2, validate_result.stderr or validate_result.stdout
    validate_report = _parse_json(validate_result)
    assert "IMMUTABLE_HISTORY_VIOLATION" in _error_codes(validate_report)

    status_result = _run_status(probe_path, consumer_id)
    assert status_result.returncode == 2, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "INVALID"
    assert "IMMUTABLE_HISTORY_VIOLATION" in _error_codes(status_report)


def test_fm1_blocked_metadata_never_launders_to_ready(tmp_path: Path) -> None:
    payload = _load_registry_payload()
    consumer_id, source_id = _append_synthetic_verified_source_and_consumer(
        payload,
        source_id="synthetic-fm1-ready-source",
        consumer_id="synthetic-fm1-ready-consumer",
        freshness_required=False,
    )
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    ready_path = tmp_path / "fm1_ready_probe.yaml"
    _write_probe_registry(ready_path, payload)

    ready_validate = _run_validate(ready_path)
    assert ready_validate.returncode == 0, ready_validate.stderr or ready_validate.stdout
    ready_status = _run_status(ready_path, consumer_id)
    assert ready_status.returncode == 0, ready_status.stderr or ready_status.stdout
    ready_report = _parse_json(ready_status)
    assert _consumer_state(ready_report) == "READY"

    blocked_payload = copy.deepcopy(payload)
    record = _source_record_by_id(blocked_payload, source_id)
    record["lifecycle_state"] = "CONFIRM_PENDING"
    record["blocked_reasons"] = ["awaiting legal/permitted-use confirmation"]
    record["missing_inputs"] = ["permitted use confirmation", "verified content pin"]
    record["unblock_condition"] = "legal review complete and pin verified"
    record["reviewed_by"] = "sourceops-fm1-probe"
    record["reviewed_at"] = "2026-08-16T00:00:00Z"
    blocked_payload["registry_content_hash"] = _canonical_registry_hash(blocked_payload)

    probe_path = tmp_path / "fm1_blocked_probe.yaml"
    _write_probe_registry(probe_path, blocked_payload)

    validate_result = _run_validate(probe_path)
    assert validate_result.returncode == 0, validate_result.stderr or validate_result.stdout
    validate_report = _parse_json(validate_result)
    assert validate_report.get("registry_valid") is True

    status_result = _run_status(probe_path, consumer_id)
    assert status_result.returncode == 3, status_result.stderr or status_result.stdout
    status_report = _parse_json(status_result)
    assert _consumer_state(status_report) == "BLOCKED"


def test_ac13_validation_report_states_operational_ceiling_verbatim() -> None:
    if not REGISTRY_PATH.exists():
        pytest.fail(f"SourceOps registry file is not implemented: {REGISTRY_PATH}")
    result = _run_validate(REGISTRY_PATH)
    assert result.returncode == 0, result.stderr or result.stdout
    report = _parse_json(result)
    assert report.get("validation_ceiling") == VALIDATION_CEILING
