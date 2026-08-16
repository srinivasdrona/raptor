"""Fail-closed loading and evaluation of RescueScreen entry-gate manifests."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from raptor.rescuescreen.model import (
    EntryGateAssessment,
    EntryGateManifest,
    EntryGateReport,
    GateEvidenceRef,
    RescueScreenHashError,
    RescueScreenPathError,
    RescueScreenSchemaError,
)


GATE_ORDER = ("EG-1", "EG-2", "EG-3", "EG-4", "EG-5")
GATE_STATUSES = ("SATISFIED", "NOT_SATISFIED")
FAIL_STATE_BY_GATE = {
    "EG-1": "MECHANISM_UNVERIFIED",
    "EG-2": "MAPPING_UNVERIFIED",
    "EG-3": "STRUCTURE_COVERAGE_INSUFFICIENT",
    "EG-4": "LICENCE_INCOMPATIBLE",
    "EG-5": "NO_TRACTABLE_ASSAY",
}

_MANIFEST_SCHEMA = "rescuescreen.entry_gate_manifest.v1"
_HASH_BASIS = "rescuescreen.entry_gate_manifest_content_hash.v1"
_REPORT_SCHEMA = "rescuescreen.entry_gate_status.v1"
_MANIFEST_FIELDS = {
    "schema",
    "lane_id",
    "lane_version",
    "manifest_version",
    "created_at",
    "manifest_content_hash",
    "hash_basis",
    "gates",
    "preservation_rules",
}
_GATE_FIELDS = {"gate_id", "status", "fail_state", "evidence_refs", "note"}
_EVIDENCE_FIELDS = {
    "artifact_id",
    "artifact_schema",
    "content_hash",
    "reviewed_by",
    "reviewed_at",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_YAML_NESTING = 64
_VALIDATION_CEILING = (
    "Gate status is an operational assertion about registered evidence references. "
    "It does not establish scientific sufficiency, binding, functional rescue, "
    "clinical relevance, treatment value, or permission to execute a RescueScreen stage."
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RescueScreenSchemaError(message)


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], *, what: str) -> None:
    non_string_keys = [repr(key) for key in value if not isinstance(key, str)]
    _require(
        not non_string_keys,
        f"{what} contains non-string field names {non_string_keys}",
    )
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    _require(not missing, f"{what} is missing required fields {missing}")
    _require(not unknown, f"{what} contains unknown fields {unknown}")


def _nonblank_string(value: Any, *, what: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{what} must be a nonblank string")
    return value


def _reject_yaml_temporals(
    value: Any,
    *,
    what: str,
    _active_containers: set[int] | None = None,
    _depth: int = 0,
) -> None:
    if isinstance(value, (date, datetime)):
        raise RescueScreenSchemaError(f"{what} contains an unquoted YAML date or datetime")
    if not isinstance(value, (dict, list)):
        return
    if _depth > _MAX_YAML_NESTING:
        raise RescueScreenSchemaError(
            f"{what} exceeds the maximum YAML nesting depth of {_MAX_YAML_NESTING}"
        )

    active_containers = _active_containers if _active_containers is not None else set()
    container_id = id(value)
    if container_id in active_containers:
        raise RescueScreenSchemaError(f"{what} contains a recursive YAML alias")

    active_containers.add(container_id)
    try:
        if isinstance(value, dict):
            for key, item in value.items():
                key_label = key if isinstance(key, str) else repr(key)
                _reject_yaml_temporals(
                    item,
                    what=f"{what}.{key_label}",
                    _active_containers=active_containers,
                    _depth=_depth + 1,
                )
        else:
            for index, item in enumerate(value):
                _reject_yaml_temporals(
                    item,
                    what=f"{what}[{index}]",
                    _active_containers=active_containers,
                    _depth=_depth + 1,
                )
    finally:
        active_containers.remove(container_id)


def entry_gate_manifest_content_hash(manifest: Mapping[str, Any]) -> str:
    """Compute the v1 canonical self-excluding manifest hash."""

    if not isinstance(manifest, Mapping):
        raise RescueScreenSchemaError("entry-gate manifest must be a mapping")
    payload = dict(manifest)
    payload.pop("manifest_content_hash", None)
    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        raise RescueScreenSchemaError(f"entry-gate manifest is not canonically serializable: {exc}") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_evidence_ref(value: Any, *, gate_id: str, index: int) -> GateEvidenceRef:
    _require(isinstance(value, dict), f"{gate_id} evidence_refs[{index}] must be a mapping")
    _require_exact_fields(value, _EVIDENCE_FIELDS, what=f"{gate_id} evidence_refs[{index}]")

    content_hash = _nonblank_string(
        value["content_hash"],
        what=f"{gate_id} evidence_refs[{index}].content_hash",
    )
    _require(
        bool(_SHA256_RE.fullmatch(content_hash)),
        f"{gate_id} evidence_refs[{index}].content_hash must be 64 lowercase hexadecimal characters",
    )
    reviewed_at = value["reviewed_at"]
    _require(
        isinstance(reviewed_at, str) and bool(reviewed_at.strip()),
        f"{gate_id} evidence_refs[{index}].reviewed_at must be a quoted nonblank string",
    )

    return GateEvidenceRef(
        artifact_id=_nonblank_string(
            value["artifact_id"],
            what=f"{gate_id} evidence_refs[{index}].artifact_id",
        ),
        artifact_schema=_nonblank_string(
            value["artifact_schema"],
            what=f"{gate_id} evidence_refs[{index}].artifact_schema",
        ),
        content_hash=content_hash,
        reviewed_by=_nonblank_string(
            value["reviewed_by"],
            what=f"{gate_id} evidence_refs[{index}].reviewed_by",
        ),
        reviewed_at=reviewed_at,
    )


def _parse_gate(value: Any, *, expected_gate_id: str, index: int) -> EntryGateAssessment:
    _require(isinstance(value, dict), f"gates[{index}] must be a mapping")
    _require_exact_fields(value, _GATE_FIELDS, what=f"gates[{index}]")

    gate_id = _nonblank_string(value["gate_id"], what=f"gates[{index}].gate_id")
    _require(
        gate_id == expected_gate_id,
        f"gates[{index}].gate_id must be {expected_gate_id!r}, got {gate_id!r}",
    )
    status = _nonblank_string(value["status"], what=f"{gate_id}.status")
    _require(status in GATE_STATUSES, f"{gate_id}.status must be one of {GATE_STATUSES!r}")
    fail_state = _nonblank_string(value["fail_state"], what=f"{gate_id}.fail_state")
    _require(
        fail_state == FAIL_STATE_BY_GATE[gate_id],
        f"{gate_id}.fail_state must be {FAIL_STATE_BY_GATE[gate_id]!r}",
    )

    evidence_values = value["evidence_refs"]
    _require(isinstance(evidence_values, list), f"{gate_id}.evidence_refs must be a list")
    evidence_refs = tuple(
        _parse_evidence_ref(item, gate_id=gate_id, index=evidence_index)
        for evidence_index, item in enumerate(evidence_values)
    )
    _require(
        status != "SATISFIED" or bool(evidence_refs),
        f"{gate_id} cannot be SATISFIED without reviewed evidence_refs",
    )

    return EntryGateAssessment(
        gate_id=gate_id,
        status=status,
        fail_state=fail_state,
        evidence_refs=evidence_refs,
        note=_nonblank_string(value["note"], what=f"{gate_id}.note"),
    )


def _parse_manifest(value: Any) -> EntryGateManifest:
    _require(isinstance(value, dict), "entry-gate manifest must be a mapping")
    _reject_yaml_temporals(value, what="entry-gate manifest")
    _require_exact_fields(value, _MANIFEST_FIELDS, what="entry-gate manifest")

    _require(
        value["schema"] == _MANIFEST_SCHEMA,
        f"entry-gate manifest schema must be {_MANIFEST_SCHEMA!r}",
    )
    _require(
        value["hash_basis"] == _HASH_BASIS,
        f"entry-gate manifest hash_basis must be {_HASH_BASIS!r}",
    )
    declared_hash = _nonblank_string(
        value["manifest_content_hash"],
        what="entry-gate manifest manifest_content_hash",
    )
    _require(
        bool(_SHA256_RE.fullmatch(declared_hash)),
        "entry-gate manifest manifest_content_hash must be 64 lowercase hexadecimal characters",
    )

    gate_values = value["gates"]
    _require(isinstance(gate_values, list), "entry-gate manifest gates must be a list")
    _require(
        len(gate_values) == len(GATE_ORDER),
        f"entry-gate manifest must contain exactly {len(GATE_ORDER)} gates",
    )
    gates = tuple(
        _parse_gate(gate_value, expected_gate_id=gate_id, index=index)
        for index, (gate_id, gate_value) in enumerate(zip(GATE_ORDER, gate_values))
    )

    preservation_values = value["preservation_rules"]
    _require(
        isinstance(preservation_values, list),
        "entry-gate manifest preservation_rules must be a list",
    )
    preservation_rules = tuple(
        _nonblank_string(rule, what=f"preservation_rules[{index}]")
        for index, rule in enumerate(preservation_values)
    )

    return EntryGateManifest(
        schema=value["schema"],
        lane_id=_nonblank_string(value["lane_id"], what="entry-gate manifest lane_id"),
        lane_version=_nonblank_string(
            value["lane_version"],
            what="entry-gate manifest lane_version",
        ),
        manifest_version=_nonblank_string(
            value["manifest_version"],
            what="entry-gate manifest manifest_version",
        ),
        created_at=_nonblank_string(value["created_at"], what="entry-gate manifest created_at"),
        manifest_content_hash=declared_hash,
        hash_basis=value["hash_basis"],
        gates=gates,
        preservation_rules=preservation_rules,
    )


def load_entry_gate_manifest(path: Path | str) -> EntryGateManifest:
    """Load only the explicit manifest path and return an immutable model."""

    manifest_path = Path(path)
    try:
        if manifest_path.is_symlink():
            raise RescueScreenPathError(f"manifest path must not be a symlink: {manifest_path}")
        if not manifest_path.exists():
            raise RescueScreenPathError(f"manifest path does not exist: {manifest_path}")
        if not manifest_path.is_file():
            raise RescueScreenPathError(f"manifest path is not a regular file: {manifest_path}")
        raw_text = manifest_path.read_text(encoding="utf-8")
    except RescueScreenPathError:
        raise
    except (OSError, UnicodeError) as exc:
        raise RescueScreenPathError(f"manifest path is unreadable: {manifest_path}: {exc}") from exc

    try:
        raw = yaml.safe_load(raw_text)
    except (yaml.YAMLError, RecursionError) as exc:
        raise RescueScreenSchemaError(f"entry-gate manifest is not valid YAML: {exc}") from exc

    manifest = _parse_manifest(raw)
    actual_hash = entry_gate_manifest_content_hash(raw)
    if manifest.manifest_content_hash != actual_hash:
        raise RescueScreenHashError(
            "entry-gate manifest_content_hash does not match canonical manifest content"
        )
    return manifest


def _validate_manifest_model(manifest: EntryGateManifest) -> EntryGateManifest:
    _require(
        isinstance(manifest, EntryGateManifest),
        "evaluate_entry_gates requires an EntryGateManifest",
    )
    _require(isinstance(manifest.gates, tuple), "entry-gate manifest gates must be a tuple")
    _require(
        isinstance(manifest.preservation_rules, tuple),
        "entry-gate manifest preservation_rules must be a tuple",
    )
    for gate_index, gate in enumerate(manifest.gates):
        _require(
            isinstance(gate, EntryGateAssessment),
            f"gates[{gate_index}] must be an EntryGateAssessment",
        )
        _require(
            isinstance(gate.evidence_refs, tuple),
            f"{gate.gate_id}.evidence_refs must be a tuple",
        )
        for evidence_index, evidence_ref in enumerate(gate.evidence_refs):
            _require(
                isinstance(evidence_ref, GateEvidenceRef),
                f"{gate.gate_id} evidence_refs[{evidence_index}] must be a GateEvidenceRef",
            )

    raw = {
        "schema": manifest.schema,
        "lane_id": manifest.lane_id,
        "lane_version": manifest.lane_version,
        "manifest_version": manifest.manifest_version,
        "created_at": manifest.created_at,
        "manifest_content_hash": manifest.manifest_content_hash,
        "hash_basis": manifest.hash_basis,
        "gates": [
            {
                "gate_id": gate.gate_id,
                "status": gate.status,
                "fail_state": gate.fail_state,
                "evidence_refs": [
                    {
                        "artifact_id": evidence_ref.artifact_id,
                        "artifact_schema": evidence_ref.artifact_schema,
                        "content_hash": evidence_ref.content_hash,
                        "reviewed_by": evidence_ref.reviewed_by,
                        "reviewed_at": evidence_ref.reviewed_at,
                    }
                    for evidence_ref in gate.evidence_refs
                ],
                "note": gate.note,
            }
            for gate in manifest.gates
        ],
        "preservation_rules": list(manifest.preservation_rules),
    }
    validated = _parse_manifest(raw)
    if validated.manifest_content_hash != entry_gate_manifest_content_hash(raw):
        raise RescueScreenHashError(
            "entry-gate manifest_content_hash does not match canonical manifest content"
        )
    return validated


def evaluate_entry_gates(manifest: EntryGateManifest) -> EntryGateReport:
    """Evaluate readiness without mutating gate state or authorizing execution."""

    validated_manifest = _validate_manifest_model(manifest)
    blocking = tuple(
        gate for gate in validated_manifest.gates if gate.status == "NOT_SATISFIED"
    )
    first = blocking[0] if blocking else None
    ready = not blocking

    return EntryGateReport(
        schema=_REPORT_SCHEMA,
        lane_id=validated_manifest.lane_id,
        lane_version=validated_manifest.lane_version,
        manifest_version=validated_manifest.manifest_version,
        manifest_content_hash=validated_manifest.manifest_content_hash,
        overall_status="READY_FOR_S1_REVIEW" if ready else "BLOCKED",
        first_blocking_gate=first.gate_id if first else None,
        blocking_fail_state=first.fail_state if first else None,
        blocking_gates=tuple(gate.gate_id for gate in blocking),
        eligible_next_stage="S1" if ready else None,
        stage_execution_authorized=False,
        gates=validated_manifest.gates,
        validation_ceiling=_VALIDATION_CEILING,
    )


def entry_gate_report_to_dict(report: EntryGateReport) -> dict[str, Any]:
    """Render a report using the exact deterministic public field surface."""

    return {
        "schema": report.schema,
        "lane_id": report.lane_id,
        "lane_version": report.lane_version,
        "manifest_version": report.manifest_version,
        "manifest_content_hash": report.manifest_content_hash,
        "overall_status": report.overall_status,
        "first_blocking_gate": report.first_blocking_gate,
        "blocking_fail_state": report.blocking_fail_state,
        "blocking_gates": list(report.blocking_gates),
        "eligible_next_stage": report.eligible_next_stage,
        "stage_execution_authorized": report.stage_execution_authorized,
        "gates": [
            {
                "gate_id": gate.gate_id,
                "status": gate.status,
                "fail_state": gate.fail_state,
                "evidence_refs": [
                    {
                        "artifact_id": ref.artifact_id,
                        "artifact_schema": ref.artifact_schema,
                        "content_hash": ref.content_hash,
                        "reviewed_by": ref.reviewed_by,
                        "reviewed_at": ref.reviewed_at,
                    }
                    for ref in gate.evidence_refs
                ],
                "note": gate.note,
            }
            for gate in report.gates
        ],
        "validation_ceiling": report.validation_ceiling,
    }
