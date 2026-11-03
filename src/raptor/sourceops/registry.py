from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from raptor.sourceops.model import (
    Consumer,
    DanglingConsumerOrSourceError,
    DeclarationDriftError,
    DeclarationReferenceError,
    ForbiddenCrossLaneClaimError,
    ForbiddenRoleFlow,
    ImmutableHistoryViolation,
    Registry,
    RegistryHashMismatch,
    RegistrySchemaError,
    SourceBlockedError,
    SourceMetadataIncomplete,
    SourceOpsError,
    ValidationError,
    ValidationResult,
)

VALIDATION_SCHEMA_ID = "raptor.source_registry.validation.v1"
REGISTRY_SCHEMA_ID = "raptor.source_registry.v1"
VALIDATION_CEILING = (
    "V2 can establish that source lifecycle metadata and change-impact routing are complete, deterministic, and fail-closed. "
    "It cannot establish that a source is scientifically sufficient, that a criterion is valid, that a variant direction is correct, "
    "or that any clinical or research scope is authorized."
)
REGISTRY_HASH_BASIS = "raptor.source_registry_content_hash.v1"
RESERVED_CONSUMER_IDS = {"rescuescreen", "atlas-technical-coverage-panel", "atlas-independent-validation-panel"}
ALLOWED_PERMITTED_USE_VALUES = {
    "governed_repository_reference_only",
    "historical_reference_only",
    "historical_reference_only_blocked_policy_only_reuse",
    "orthogonal_validation_only",
    "research_context_only",
    "shadow_only_non_authoritative",
    "metadata_template_only",
    "policy_reference_only",
    "verified_for_declared_use",
}
ALLOWED_REDISTRIBUTION_VALUES = {
    "allowed_with_repo_workflow",
    "forbidden",
    "forbidden_without_immutable_history_approval",
    "forbidden_without_review",
    "forbidden_without_template_approval",
    "forbidden_without_policy_approval",
    "forbidden_until_access_and_licensing_are_confirmed",
    "forbidden_until_biased_release_and_data_are_confirmed",
    "restricted_by_operator_policy",
}
ALLOWED_CLOUD_EGRESS_VALUES = {
    "forbidden",
    "forbidden_without_explicit_review",
    "forbidden_without_policy_approval",
    "restricted_by_operator_policy",
}


def _marker_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[_\s-]+", "-", text)
    return text


def _placeholder_text(value: Any) -> bool:
    text = _marker_text(value)
    if not text:
        return True
    markers = (
        "confirm-pending",
        "pending",
        "unknown",
        "tbd",
        "proposed",
        "unverified",
        "placeholder",
        "review-required",
        "not-yet-verified",
    )
    return any(marker in text for marker in markers)


def _looks_external_reference(value: str) -> bool:
    lowered = value.strip().lower()
    return bool(lowered) and lowered.startswith(("https", "http", "s3", "gs", "azure", "ftp", "file"))


def _looks_absolute_repo_path(value: str) -> bool:
    if not value:
        return False
    return value.startswith("/") or (len(value) >= 2 and value[1] == ":")


def _error(code: str, message: str, error_type: str, details: dict[str, Any] | None = None) -> ValidationError:
    return ValidationError(code=code, message=message, type=error_type, details=details or {})


def _parse_utc_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_duration_seconds(value: Any) -> float | None:
    if not isinstance(value, str):
        raise ValueError("duration is not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty duration")
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", text, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"invalid freshness duration: {value!r}")
    days = float(match.group(1) or 0)
    hours = float(match.group(2) or 0)
    minutes = float(match.group(3) or 0)
    seconds = float(match.group(4) or 0)
    return (days * 86400.0) + (hours * 3600.0) + (minutes * 60.0) + seconds


def _is_allowed_licence_value(value: Any, allowed: set[str]) -> bool:
    if not isinstance(value, str):
        return False
    text = _marker_text(value)
    if not text or _placeholder_text(value):
        return False
    return text in { _marker_text(item) for item in allowed }


def _is_known_permitted_use(value: Any) -> bool:
    return _is_allowed_licence_value(value, ALLOWED_PERMITTED_USE_VALUES)


def _is_known_redistribution(value: Any) -> bool:
    return _is_allowed_licence_value(value, ALLOWED_REDISTRIBUTION_VALUES)


def _is_known_cloud_egress(value: Any) -> bool:
    return _is_allowed_licence_value(value, ALLOWED_CLOUD_EGRESS_VALUES)


def _resolve_declaration_pointer(raw_locator: str, *, repo_root: str | os.PathLike[str]) -> Any:
    if not isinstance(raw_locator, str):
        raise DeclarationReferenceError("declaration locator must be a string")
    normalized = raw_locator.replace("\\", "/").strip()
    if not normalized:
        raise DeclarationReferenceError("declaration locator is empty")
    file_part, sep, pointer = normalized.partition("#")
    if not sep or not file_part or not pointer:
        raise DeclarationReferenceError(f"declaration locator must include '<path>#<pointer>': {raw_locator!r}")

    file_path = safe_repo_relative_path(repo_root, file_part)
    try:
        yaml_data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise DeclarationReferenceError(f"declaration locator file is unreadable or malformed YAML: {raw_locator!r}") from exc
    current: Any = yaml_data
    idx = 0
    while idx < len(pointer):
        if pointer[idx] == ".":
            idx += 1
            continue
        if pointer[idx] == "[":
            closing = pointer.find("]", idx + 1)
            if closing == -1:
                raise DeclarationReferenceError(f"declaration locator has unclosed list index: {raw_locator!r}")
            index_text = pointer[idx + 1 : closing].strip()
            if not index_text:
                raise DeclarationReferenceError(f"declaration locator list index cannot be empty: {raw_locator!r}")
            if index_text.startswith(("'", '"')) and index_text.endswith(("'", '"')) and len(index_text) >= 2:
                key = index_text[1:-1]
                if not isinstance(current, dict):
                    raise DeclarationReferenceError(f"declaration locator key selector requires a mapping in {raw_locator!r}")
                if key not in current:
                    raise DeclarationReferenceError(f"declared path missing key {key!r} in {raw_locator!r}")
                current = current[key]
                idx = closing + 1
                continue
            if not index_text.isdigit():
                if not isinstance(current, dict):
                    raise DeclarationReferenceError(f"declaration locator list index must be numeric: {raw_locator!r}")
                if index_text not in current:
                    raise DeclarationReferenceError(f"declared path missing key {index_text!r} in {raw_locator!r}")
                current = current[index_text]
                idx = closing + 1
                continue
            if not isinstance(current, list):
                raise DeclarationReferenceError(f"declaration locator index requires a list in {raw_locator!r}")
            item_index = int(index_text)
            if item_index >= len(current):
                raise DeclarationReferenceError(f"declaration locator index {item_index} out of range in {raw_locator!r}")
            current = current[item_index]
            idx = closing + 1
            continue

        start = idx
        while idx < len(pointer) and pointer[idx] not in ".[":
            idx += 1
        token = pointer[start:idx]
        if not token:
            raise DeclarationReferenceError(f"declaration locator has an empty token in {raw_locator!r}")
        if isinstance(current, dict):
            if token in current:
                current = current[token]
                continue
            candidates = sorted((key for key in current if isinstance(key, str)), key=len, reverse=True)
            match_key = None
            for key in candidates:
                if pointer.startswith(key, start):
                    end_pos = start + len(key)
                    if end_pos == len(pointer) or pointer[end_pos] in ".[":
                        match_key = key
                        break
            if match_key is None:
                raise DeclarationReferenceError(f"declared path missing key {token!r} in {raw_locator!r}")
            current = current[match_key]
            next_pos = start + len(match_key)
            if next_pos < len(pointer) and pointer[next_pos] == ".":
                idx = next_pos + 1
            else:
                idx = next_pos
            continue
        if isinstance(current, list):
            if not token.isdigit():
                raise DeclarationReferenceError(f"declaration locator token {token!r} requires a list index in {raw_locator!r}")
            item_index = int(token)
            if item_index >= len(current):
                raise DeclarationReferenceError(f"declaration locator index {item_index} out of range in {raw_locator!r}")
            current = current[item_index]
            continue
        raise DeclarationReferenceError(f"declared path cannot continue through scalar value for {token!r} in {raw_locator!r}")
    return current


def _scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return str(value)


def _component_fidelity_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        for key in (
            "urn",
            "version",
            "value",
            "version_or_snapshot",
            "doi",
            "pmid",
            "pmc",
            "locus",
            "transcript",
            "kind",
            "identifier",
            "entry_id",
            "accession",
            "sha256",
            "verification",
            "license",
            "licence",
            "status",
            "name",
            "gene",
        ):
            candidate = value.get(key)
            if candidate is not None and not isinstance(candidate, (dict, list, tuple)):
                return candidate
        for nested in value.values():
            if nested is None:
                continue
            if not isinstance(nested, (dict, list, tuple)):
                return nested
            candidate = _component_fidelity_scalar(nested)
            if candidate is not None:
                return candidate
        return value
    if isinstance(value, (list, tuple)):
        if len(value) == 1:
            return _component_fidelity_scalar(value[0])
        flattened: list[Any] = []
        for item in value:
            candidate = _component_fidelity_scalar(item)
            if candidate is not None:
                flattened.append(candidate)
        return flattened if flattened else value
    return value


def _value_matches_component_stored(observed: Any, declared: Any) -> bool:
    if observed is None and declared is None:
        return True
    if observed is None or declared is None:
        return False

    observed_candidates = _component_fidelity_scalar(observed)
    declared_candidates = _component_fidelity_scalar(declared)

    observed_values = [observed_candidates] if not isinstance(observed_candidates, (list, tuple)) else list(observed_candidates)
    declared_values = [declared_candidates] if not isinstance(declared_candidates, (list, tuple)) else list(declared_candidates)

    for observed_value in observed_values:
        for declared_value in declared_values:
            if _scalar_text(observed_value) == _scalar_text(declared_value):
                return True
    return False


def canonical_registry_hash(payload: Registry | Mapping[str, Any]) -> str:
    if isinstance(payload, Registry):
        data = copy.deepcopy(dict(payload._raw_mapping)) if payload._raw_mapping is not None else copy.deepcopy(payload.as_dict())
    else:
        data = copy.deepcopy(dict(payload))
    data.pop("registry_content_hash", None)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_repo_relative_path(repo_root: str | os.PathLike[str], raw_path: str) -> Path:
    if not isinstance(raw_path, str):
        raise DeclarationReferenceError("declaration path must be a string")
    candidate = raw_path.replace("\\", "/").strip()
    if not candidate or _looks_external_reference(candidate) or _looks_absolute_repo_path(candidate):
        raise DeclarationReferenceError(f"declaration path invalid or external: {raw_path!r}")
    if candidate.startswith("../") or candidate == "..":
        raise DeclarationReferenceError(f"declaration path escapes repo root: {raw_path!r}")
    if any(part == ".." for part in candidate.split("/")):
        raise DeclarationReferenceError(f"declaration path escapes repo root: {raw_path!r}")
    root = Path(repo_root).resolve(strict=False)
    resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DeclarationReferenceError(f"declaration path escapes repo root: {raw_path!r}") from exc
    if not resolved.exists() or not resolved.is_file():
        raise DeclarationReferenceError(f"declaration file does not exist: {raw_path!r}")
    if resolved.is_symlink():
        raise DeclarationReferenceError(f"declaration path resolves through a symlink: {raw_path!r}")
    return resolved


def canonical_lf_sha256(path: str | os.PathLike[str]) -> str:
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise DeclarationReferenceError(f"declaration file is not valid UTF-8 text: {file_path!s}") from exc
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_registry(path: str | os.PathLike[str]) -> Registry:
    registry_path = Path(path)
    if not registry_path.exists():
        raise FileNotFoundError(f"Registry not found: {registry_path}")
    if registry_path.is_dir():
        raise IsADirectoryError(f"Registry path is a directory: {registry_path}")
    try:
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError, OSError, TypeError, ValueError) as exc:
        raise RegistrySchemaError(f"malformed YAML in registry: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegistrySchemaError("registry payload must parse into a mapping")
    return Registry.from_mapping(payload)


def _validate_coverage_exclusion(exclusion: Mapping[str, Any], *, repo_root: str | os.PathLike[str]) -> str:
    if not isinstance(exclusion, Mapping):
        raise RegistrySchemaError("coverage exclusion must be a mapping")
    for field in ("owner", "reason", "review_condition"):
        value = exclusion.get(field)
        if not isinstance(value, str):
            raise RegistrySchemaError(f"coverage exclusion {field!r} must be a string")
        if not value.strip() or _placeholder_text(value):
            raise SourceMetadataIncomplete(f"coverage exclusion {field!r} cannot be blank or placeholder")

    declaration_path = exclusion.get("declaration_path")
    declaration_locator = exclusion.get("declaration_locator")
    if not isinstance(declaration_path, str) or not declaration_path.strip():
        raise DeclarationReferenceError("coverage exclusion declaration_path must be a non-empty string")
    if not isinstance(declaration_locator, str) or not declaration_locator.strip():
        raise DeclarationReferenceError("coverage exclusion declaration_locator must be a non-empty string")

    normalized_path = declaration_path.replace("\\", "/").strip()
    normalized_locator = declaration_locator.replace("\\", "/").strip()
    declaration_file = safe_repo_relative_path(repo_root, normalized_path)

    file_part = normalized_path
    pointer = normalized_locator
    if "#" in normalized_locator:
        file_part, _, pointer = normalized_locator.partition("#")
        if not file_part or not pointer:
            raise DeclarationReferenceError(f"coverage exclusion declaration_locator must include a file and pointer: {declaration_locator!r}")

    loc_file = safe_repo_relative_path(repo_root, file_part)
    if loc_file.resolve(strict=False) != declaration_file.resolve(strict=False):
        raise DeclarationReferenceError(f"coverage exclusion declaration_locator file does not match declaration_path: {declaration_locator!r}")
    if not pointer or not pointer.strip():
        raise DeclarationReferenceError(f"coverage exclusion declaration_locator pointer is empty: {declaration_locator!r}")

    root = Path(repo_root).resolve(strict=False)
    relative_file = loc_file.relative_to(root).as_posix()
    locator_ref = f"{relative_file}#{pointer}"
    _resolve_declaration_pointer(locator_ref, repo_root=repo_root)
    return locator_ref


def _accounted_locators(payload: Mapping[str, Any], *, repo_root: str | os.PathLike[str] | None = None) -> list[str]:
    accounted: list[str] = []
    records = payload.get("source_records")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            refs = record.get("declaration_refs")
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, dict):
                        path = ref.get("path")
                        if isinstance(path, str) and path.strip():
                            accounted.append(path.replace("\\", "/").strip())
            components = record.get("components")
            if isinstance(components, list):
                for component in components:
                    if isinstance(component, dict):
                        locator = component.get("declaration_locator")
                        if isinstance(locator, str) and locator.strip():
                            accounted.append(locator.replace("\\", "/"))
    exclusions = payload.get("coverage_exclusions", [])
    if isinstance(exclusions, list) and repo_root is not None:
        for exclusion in exclusions:
            if not isinstance(exclusion, dict):
                continue
            try:
                accounted.append(_validate_coverage_exclusion(exclusion, repo_root=repo_root))
            except (DeclarationReferenceError, RegistrySchemaError, SourceMetadataIncomplete, TypeError, ValueError, OSError, UnicodeError, yaml.YAMLError):
                continue
    elif isinstance(exclusions, list):
        for exclusion in exclusions:
            if not isinstance(exclusion, dict):
                continue
            path = exclusion.get("declaration_path")
            locator = exclusion.get("declaration_locator")
            if isinstance(path, str) and isinstance(locator, str):
                path_norm = path.replace("\\", "/").strip()
                locator_norm = locator.replace("\\", "/").strip()
                if path_norm and locator_norm:
                    if "#" in locator_norm:
                        accounted.append(locator_norm)
                    else:
                        accounted.append(f"{path_norm}#{locator_norm}")
    return accounted


def _is_stale_source(source: Mapping[str, Any]) -> bool:
    refresh = source.get("refresh")
    if not isinstance(refresh, Mapping):
        return False
    last_checked = refresh.get("last_checked_at")
    sla = refresh.get("freshness_sla")
    if not isinstance(last_checked, str) or not isinstance(sla, str):
        return False
    try:
        checked = _parse_utc_timestamp(last_checked)
        delta = _parse_duration_seconds(sla)
    except ValueError:
        return False
    if delta is None:
        return False
    return (datetime.now(timezone.utc) - checked) > timedelta(seconds=delta)


def validate_registry(payload: Registry | Mapping[str, Any], *, repo_root: str | os.PathLike[str] | None = None) -> ValidationResult:
    result = ValidationResult(schema=VALIDATION_SCHEMA_ID, registry_valid=False, validation_ceiling=VALIDATION_CEILING)
    try:
        if isinstance(payload, Registry):
            payload_dict = copy.deepcopy(dict(payload._raw_mapping)) if payload._raw_mapping is not None else copy.deepcopy(payload.as_dict())
        else:
            payload_dict = copy.deepcopy(dict(payload))
        Registry.from_mapping(payload_dict)
    except SourceOpsError as exc:
        result.errors.append(_error(exc.code, exc.message, exc.__class__.__name__, getattr(exc, "details", {})))
        return result
    except (TypeError, ValueError) as exc:
        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", str(exc), "RegistrySchemaError"))
        return result

    required_top = {
        "schema",
        "registry_id",
        "registry_version",
        "created_at",
        "registry_content_hash",
        "hash_basis",
        "source_records",
        "consumers",
        "coverage_exclusions",
        "preservation_rules",
    }
    missing = required_top - set(payload_dict)
    if missing:
        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", "missing required top-level registry keys", "RegistrySchemaError", {"missing": sorted(missing)}))
    if payload_dict.get("schema") != REGISTRY_SCHEMA_ID:
        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"registry schema must be {REGISTRY_SCHEMA_ID!r}", "RegistrySchemaError", {"expected": REGISTRY_SCHEMA_ID, "actual": payload_dict.get("schema")}))
    if payload_dict.get("hash_basis") != REGISTRY_HASH_BASIS:
        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", "hash_basis is invalid", "RegistrySchemaError", {"expected": REGISTRY_HASH_BASIS, "actual": payload_dict.get("hash_basis")}))
    if "registry_content_hash" not in payload_dict:
        result.errors.append(_error("REGISTRY_HASH_MISMATCH", "registry content hash missing", "RegistryHashMismatch"))
    else:
        computed_hash = canonical_registry_hash(payload_dict)
        if payload_dict.get("registry_content_hash") != computed_hash:
            result.errors.append(_error("REGISTRY_HASH_MISMATCH", "registry content hash mismatch", "RegistryHashMismatch", {"expected": payload_dict.get("registry_content_hash"), "actual": computed_hash}))

    records = payload_dict.get("source_records")
    if not isinstance(records, list):
        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", "source_records must be a list", "RegistrySchemaError"))
        records = []

    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        source_id = record.get("source_id")
        refs = record.get("declaration_refs")
        if not isinstance(refs, list):
            result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"source {source_id!r} declaration_refs must be a list", "RegistrySchemaError", {"source_id": source_id}))
            continue
        for ref_idx, ref in enumerate(refs):
            if not isinstance(ref, dict):
                result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"source {source_id!r} declaration_refs[{ref_idx}] must be a mapping", "RegistrySchemaError", {"source_id": source_id, "index": ref_idx}))
                continue
            ref_path = ref.get("path")
            if not isinstance(ref_path, str):
                result.errors.append(_error("DECLARATION_REFERENCE_INVALID", f"source {source_id!r} declaration_refs[{ref_idx}].path must be a string", "DeclarationReferenceError", {"source_id": source_id, "index": ref_idx}))
                continue
            try:
                resolved = safe_repo_relative_path(repo_root or os.getcwd(), ref_path)
            except DeclarationReferenceError as exc:
                result.errors.append(_error("DECLARATION_REFERENCE_INVALID", str(exc), "DeclarationReferenceError", {"source_id": source_id, "path": ref_path}))
                continue
            expected = ref.get("canonical_lf_sha256")
            if isinstance(expected, str):
                try:
                    actual = canonical_lf_sha256(resolved)
                except (DeclarationReferenceError, OSError, UnicodeError, ValueError) as exc:
                    result.errors.append(_error("DECLARATION_REFERENCE_INVALID", f"source {source_id!r} declaration_refs[{ref_idx}] cannot be hashed: {exc}", "DeclarationReferenceError", {"source_id": source_id, "path": ref_path, "index": ref_idx}))
                    continue
                if actual != expected:
                    result.errors.append(_error("DECLARATION_DRIFT", f"declaration drift for {ref_path!r}", "DeclarationDriftError", {"source_id": source_id, "path": ref_path, "expected": expected, "actual": actual}))

    source_by_id: dict[str, Mapping[str, Any]] = {}
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"source_records[{idx}] must be a mapping", "RegistrySchemaError"))
            continue
        source_id = record.get("source_id")
        if isinstance(source_id, str):
            if source_id in source_by_id:
                result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"duplicate source_id {source_id!r}", "RegistrySchemaError", {"source_id": source_id}))
            else:
                source_by_id[source_id] = record

    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        source_id = record.get("source_id")

        lifecycle_state = record.get("lifecycle_state")
        if record.get("record_kind") == "METADATA_CATALOG_TEMPLATE":
            if lifecycle_state != "METADATA_ONLY":
                result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"metadata catalog {source_id!r} must use METADATA_ONLY", "ForbiddenRoleFlow", {"source_id": source_id}))
            components = record.get("components")
            if components not in (None, [], ()):
                result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"metadata catalog {source_id!r} must have zero components", "ForbiddenRoleFlow", {"source_id": source_id}))

        if lifecycle_state in {"VERIFIED_ACTIVE", "PINNED_HISTORICAL"}:
            if record.get("record_kind") == "METADATA_CATALOG_TEMPLATE":
                result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"metadata catalog {source_id!r} cannot be active or historical", "ForbiddenRoleFlow", {"source_id": source_id}))
            owner = record.get("owner")
            if not isinstance(owner, str) or _placeholder_text(owner):
                result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} must carry a concrete owner", "SourceMetadataIncomplete", {"source_id": source_id}))
            licence = record.get("licence")
            if isinstance(licence, dict):
                for field in ("status", "permitted_use", "redistribution", "cloud_egress"):
                    value = licence.get(field)
                    if not isinstance(value, str) or _placeholder_text(value):
                        result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} licence.{field} cannot be placeholder", "SourceMetadataIncomplete", {"source_id": source_id, "field": field}))
                if not _is_known_permitted_use(licence.get("permitted_use")):
                    result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} has an invalid or laundered permitted_use", "SourceMetadataIncomplete", {"source_id": source_id, "value": licence.get("permitted_use")}))
                if not _is_known_redistribution(licence.get("redistribution")):
                    result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} has an invalid or unauthorised redistribution claim", "SourceMetadataIncomplete", {"source_id": source_id, "value": licence.get("redistribution")}))
                if not _is_known_cloud_egress(licence.get("cloud_egress")):
                    result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} has an invalid or unauthorised cloud_egress claim", "SourceMetadataIncomplete", {"source_id": source_id, "value": licence.get("cloud_egress")}))
                if lifecycle_state == "PINNED_HISTORICAL" and licence.get("permitted_use") not in {"historical_reference_only", "historical_reference_only_blocked_policy_only_reuse"}:
                    result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} historical lifecycle cannot authorize new permitted use", "SourceMetadataIncomplete", {"source_id": source_id, "value": licence.get("permitted_use")}))
            release = record.get("release")
            if isinstance(release, dict):
                for field in ("version_or_snapshot", "content_pin_status"):
                    value = release.get(field)
                    if not isinstance(value, str) or _placeholder_text(value):
                        result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} release.{field} cannot be placeholder", "SourceMetadataIncomplete", {"source_id": source_id, "field": field}))

        licence = record.get("licence")
        if isinstance(licence, dict):
            for field, validator in (
                ("permitted_use", _is_known_permitted_use),
                ("redistribution", _is_known_redistribution),
                ("cloud_egress", _is_known_cloud_egress),
            ):
                value = licence.get(field)
                if not isinstance(value, str):
                    continue
                if _placeholder_text(value):
                    continue
                if not validator(value):
                    result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} has an invalid or laundered {field}", "SourceMetadataIncomplete", {"source_id": source_id, "field": field, "value": value}))

        if lifecycle_state in {"CONFIRM_PENDING", "ACCESS_BLOCKED"}:
            if not isinstance(record.get("blocked_reasons"), list) or not record.get("blocked_reasons"):
                result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"blocked source {source_id!r} requires blocked_reasons", "RegistrySchemaError", {"source_id": source_id}))
            if not isinstance(record.get("missing_inputs"), list) or not record.get("missing_inputs"):
                result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"blocked source {source_id!r} requires missing_inputs", "RegistrySchemaError", {"source_id": source_id}))
            unblock = record.get("unblock_condition")
            if not isinstance(unblock, str) or _placeholder_text(unblock):
                result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"blocked source {source_id!r} requires a concrete unblock_condition", "RegistrySchemaError", {"source_id": source_id}))

        refresh = record.get("refresh")
        if isinstance(refresh, dict):
            last_checked = refresh.get("last_checked_at")
            sla = refresh.get("freshness_sla")
            if not isinstance(last_checked, str):
                result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"source {source_id!r} refresh.last_checked_at must be a string", "RegistrySchemaError", {"source_id": source_id}))
            else:
                try:
                    _parse_utc_timestamp(last_checked)
                except ValueError:
                    result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} refresh.last_checked_at is not a valid UTC timestamp", "SourceMetadataIncomplete", {"source_id": source_id, "value": last_checked}))
            if not isinstance(sla, str):
                result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"source {source_id!r} refresh.freshness_sla must be a string", "RegistrySchemaError", {"source_id": source_id}))
            else:
                try:
                    _parse_duration_seconds(sla)
                except ValueError:
                    result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"source {source_id!r} refresh.freshness_sla is not a valid ISO8601 duration", "SourceMetadataIncomplete", {"source_id": source_id, "value": sla}))

        rollback = record.get("rollback")
        if isinstance(rollback, dict):
            predecessor = rollback.get("predecessor_source_id")
            immutable_required = rollback.get("immutable_predecessor_required")
            if immutable_required is False and record.get("lifecycle_state") in {"VERIFIED_ACTIVE", "PINNED_HISTORICAL"}:
                result.errors.append(_error("IMMUTABLE_HISTORY_VIOLATION", f"source {source_id!r} requires immutable_predecessor_required=true in lifecycle {record.get('lifecycle_state')!r}", "ImmutableHistoryViolation", {"source_id": source_id, "lifecycle_state": record.get("lifecycle_state")}))
            if predecessor is None:
                origin_reason = rollback.get("origin_reason")
                if not isinstance(origin_reason, str) or _placeholder_text(origin_reason):
                    result.errors.append(_error("IMMUTABLE_HISTORY_VIOLATION", f"source {source_id!r} null predecessor requires concrete origin_reason", "ImmutableHistoryViolation", {"source_id": source_id}))
            elif not isinstance(predecessor, str) or not predecessor.strip():
                result.errors.append(_error("IMMUTABLE_HISTORY_VIOLATION", f"source {source_id!r} predecessor_source_id must be a non-empty string or null", "ImmutableHistoryViolation", {"source_id": source_id}))
            elif predecessor == source_id:
                result.errors.append(_error("IMMUTABLE_HISTORY_VIOLATION", f"source {source_id!r} cannot precede itself", "ImmutableHistoryViolation", {"source_id": source_id}))
            elif predecessor in source_by_id:
                predecessor_record = source_by_id[predecessor]
                if predecessor_record.get("authoritative_locator") != record.get("authoritative_locator"):
                    result.errors.append(_error("IMMUTABLE_HISTORY_VIOLATION", f"source {source_id!r} cannot chain to unrelated predecessor {predecessor!r}", "ImmutableHistoryViolation", {"source_id": source_id, "predecessor": predecessor}))
                predecessor_state = predecessor_record.get("lifecycle_state")
                if predecessor_state not in {"VERIFIED_ACTIVE", "PINNED_HISTORICAL"}:
                    result.errors.append(_error("IMMUTABLE_HISTORY_VIOLATION", f"source {source_id!r} predecessor {predecessor!r} is not an immutable historical member of the same lineage", "ImmutableHistoryViolation", {"source_id": source_id, "predecessor": predecessor, "predecessor_state": predecessor_state}))
                predecessor_rollback = predecessor_record.get("rollback")
                if not isinstance(predecessor_rollback, dict) or predecessor_rollback.get("immutable_predecessor_required") is not True:
                    result.errors.append(_error("IMMUTABLE_HISTORY_VIOLATION", f"source {source_id!r} predecessor {predecessor!r} is missing immutable lineage requirements", "ImmutableHistoryViolation", {"source_id": source_id, "predecessor": predecessor}))
            else:
                result.errors.append(_error("DANGLING_CONSUMER_OR_SOURCE", f"source {source_id!r} predecessor {predecessor!r} is missing", "DanglingConsumerOrSourceError", {"source_id": source_id, "predecessor": predecessor}))

        components = record.get("components")
        if isinstance(components, list):
            seen_component_ids: set[str] = set()
            for component in components:
                if not isinstance(component, dict):
                    continue
                cid = component.get("component_id")
                if isinstance(cid, str):
                    if cid in seen_component_ids:
                        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"duplicate component_id {cid!r} in source {source_id!r}", "RegistrySchemaError", {"source_id": source_id, "component_id": cid}))
                        continue
                    seen_component_ids.add(cid)
                comp_state = component.get("lifecycle_state")
                role = component.get("source_role")
                version = component.get("version_or_snapshot")
                licence_status = component.get("licence_status")
                if comp_state in {"VERIFIED_ACTIVE", "PINNED_HISTORICAL"}:
                    if _placeholder_text(version):
                        result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"component {cid!r} on source {source_id!r} has placeholder version_or_snapshot", "SourceMetadataIncomplete", {"source_id": source_id, "component_id": cid}))
                    if _placeholder_text(licence_status):
                        result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"component {cid!r} on source {source_id!r} has placeholder licence_status", "SourceMetadataIncomplete", {"source_id": source_id, "component_id": cid}))
                    if role == "licensing_tag":
                        result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"licensing_tag component {cid!r} cannot be active or historical", "ForbiddenRoleFlow", {"source_id": source_id, "component_id": cid}))
                if lifecycle_state in {"VERIFIED_ACTIVE", "PINNED_HISTORICAL"} and comp_state in {"CONFIRM_PENDING", "ACCESS_BLOCKED", "METADATA_ONLY", "RETIRED"}:
                    result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"composite source {source_id!r} cannot verify non-admissible component {cid!r} in state {comp_state!r}", "ForbiddenRoleFlow", {"source_id": source_id, "component_id": cid, "component_state": comp_state}))
                if role == "licensing_tag" and isinstance(licence_status, str):
                    lowered = _marker_text(licence_status)
                    if any(token in lowered for token in ("all-uses", "approved", "permitted-use", "cleared")):
                        result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"licensing_tag component {cid!r} is being laundered into approval metadata", "SourceMetadataIncomplete", {"source_id": source_id, "component_id": cid}))
                locator = component.get("declaration_locator")
                if isinstance(locator, str):
                    if not isinstance(repo_root, (str, os.PathLike)):
                        result.errors.append(_error("DECLARATION_REFERENCE_INVALID", f"component {cid!r} on source {source_id!r} has an invalid declaration locator context: {locator!r}", "DeclarationReferenceError", {"source_id": source_id, "component_id": cid, "locator": locator}))
                    else:
                        try:
                            declared_value = _resolve_declaration_pointer(locator, repo_root=repo_root)
                        except (DeclarationReferenceError, TypeError, ValueError, KeyError, IndexError, AttributeError) as exc:
                            result.errors.append(_error("DECLARATION_REFERENCE_INVALID", f"component {cid!r} on source {source_id!r} has an invalid declaration locator {locator!r}: {exc}", "DeclarationReferenceError", {"source_id": source_id, "component_id": cid, "locator": locator, "error": str(exc)}))
                        else:
                            if isinstance(version, str) and not _value_matches_component_stored(version, declared_value):
                                result.errors.append(_error("DECLARATION_DRIFT", f"component {cid!r} disagrees with authoritative declaration {locator!r}", "DeclarationDriftError", {"source_id": source_id, "component_id": cid, "locator": locator, "expected": _scalar_text(declared_value), "actual": version}))
                            if isinstance(licence_status, str) and role == "licensing_tag" and not _value_matches_component_stored(licence_status, declared_value):
                                result.errors.append(_error("DECLARATION_DRIFT", f"licensing_tag component {cid!r} disagrees with authoritative declaration {locator!r}", "DeclarationDriftError", {"source_id": source_id, "component_id": cid, "locator": locator, "expected": _scalar_text(declared_value), "actual": licence_status}))

    coverage_exclusions = payload_dict.get("coverage_exclusions")
    covered_ids: set[str] = set()
    if isinstance(coverage_exclusions, list):
        for idx, exclusion in enumerate(coverage_exclusions):
            if not isinstance(exclusion, dict):
                continue
            exclusion_id = exclusion.get("exclusion_id")
            if isinstance(exclusion_id, str):
                if exclusion_id in covered_ids:
                    result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"duplicate exclusion_id {exclusion_id!r}", "RegistrySchemaError", {"exclusion_id": exclusion_id}))
                    continue
                covered_ids.add(exclusion_id)

            try:
                _validate_coverage_exclusion(exclusion, repo_root=repo_root if repo_root is not None else os.getcwd())
            except (RegistrySchemaError, SourceMetadataIncomplete, DeclarationReferenceError, TypeError, ValueError, OSError, UnicodeError, yaml.YAMLError) as exc:
                code = getattr(exc, "code", None) or ("REGISTRY_SCHEMA_ERROR" if isinstance(exc, RegistrySchemaError) else "SOURCE_METADATA_INCOMPLETE" if isinstance(exc, SourceMetadataIncomplete) else "DECLARATION_REFERENCE_INVALID")
                result.errors.append(_error(code, f"coverage exclusion {exclusion_id!r} is invalid: {exc}", exc.__class__.__name__, {"exclusion_id": exclusion_id, "index": idx}))
    elif coverage_exclusions is not None:
        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", "coverage_exclusions must be a list", "RegistrySchemaError"))

    preservation_rules = payload_dict.get("preservation_rules")
    seen_rule_ids: set[str] = set()
    if isinstance(preservation_rules, list):
        for idx, rule in enumerate(preservation_rules):
            if not isinstance(rule, dict):
                continue
            rule_id = rule.get("rule_id")
            if isinstance(rule_id, str):
                if rule_id in seen_rule_ids:
                    result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"duplicate rule_id {rule_id!r}", "RegistrySchemaError", {"rule_id": rule_id}))
                    continue
                seen_rule_ids.add(rule_id)
    elif preservation_rules is not None:
        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", "preservation_rules must be a list", "RegistrySchemaError"))

    consumers = payload_dict.get("consumers")
    if not isinstance(consumers, list):
        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", "consumers must be a list", "RegistrySchemaError"))
        consumers = []

    consumer_by_id: dict[str, Mapping[str, Any]] = {}
    for idx, consumer in enumerate(consumers):
        if not isinstance(consumer, dict):
            result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"consumers[{idx}] must be a mapping", "RegistrySchemaError"))
            continue
        consumer_id = consumer.get("consumer_id")
        if isinstance(consumer_id, str):
            if consumer_id in consumer_by_id:
                result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"duplicate consumer_id {consumer_id!r}", "RegistrySchemaError", {"consumer_id": consumer_id}))
                continue
            consumer_by_id[consumer_id] = consumer
        required = consumer.get("required_sources")
        if consumer_id in RESERVED_CONSUMER_IDS and (not isinstance(required, list) or bool(required)):
            result.errors.append(_error("FORBIDDEN_CROSS_LANE_CLAIM", f"reserved consumer {consumer_id!r} must be empty and non-activatable", "ForbiddenCrossLaneClaimError", {"consumer_id": consumer_id}))
        if isinstance(required, list):
            if not required and consumer_id not in RESERVED_CONSUMER_IDS:
                result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"consumer {consumer_id!r} requires at least one required source", "RegistrySchemaError", {"consumer_id": consumer_id}))
            for source_id in required:
                if not isinstance(source_id, str):
                    result.errors.append(_error("DANGLING_CONSUMER_OR_SOURCE", f"consumer {consumer_id!r} lists a non-string source id", "DanglingConsumerOrSourceError", {"consumer_id": consumer_id, "source_id": source_id}))
                    continue
                if source_id not in source_by_id:
                    result.errors.append(_error("DANGLING_CONSUMER_OR_SOURCE", f"consumer {consumer_id!r} references unknown source {source_id!r}", "DanglingConsumerOrSourceError", {"consumer_id": consumer_id, "source_id": source_id}))
                else:
                    source = source_by_id[source_id]
                    if source.get("record_kind") == "METADATA_CATALOG_TEMPLATE":
                        result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"metadata catalog {source_id!r} cannot satisfy consumer {consumer_id!r}", "ForbiddenRoleFlow", {"source_id": source_id, "consumer_id": consumer_id}))

    for record in records:
        if not isinstance(record, dict):
            continue
        source_id = record.get("source_id")
        linked_consumers = record.get("consumers")
        if isinstance(linked_consumers, list):
            for consumer_id in linked_consumers:
                if not isinstance(consumer_id, str):
                    continue
                if consumer_id not in consumer_by_id:
                    result.errors.append(_error("DANGLING_CONSUMER_OR_SOURCE", f"source {source_id!r} references unknown consumer {consumer_id!r}", "DanglingConsumerOrSourceError", {"source_id": source_id, "consumer_id": consumer_id}))
                    continue
                consumer = consumer_by_id[consumer_id]
                required = consumer.get("required_sources")
                if isinstance(required, list) and source_id not in required:
                    result.errors.append(_error("DANGLING_CONSUMER_OR_SOURCE", f"source {source_id!r} and consumer {consumer_id!r} are not reciprocal", "DanglingConsumerOrSourceError", {"source_id": source_id, "consumer_id": consumer_id}))

    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        consumer_id = consumer.get("consumer_id")
        required = consumer.get("required_sources")
        forbidden_roles = consumer.get("forbidden_source_roles")
        if not isinstance(required, list) or not isinstance(forbidden_roles, list):
            continue
        if not forbidden_roles:
            continue
        for source_id in required:
            if not isinstance(source_id, str):
                continue
            source = source_by_id.get(source_id)
            if not isinstance(source, dict):
                continue
            components = source.get("components")
            roles = {
                component.get("source_role")
                for component in (components if isinstance(components, list) else [])
                if isinstance(component, dict) and isinstance(component.get("source_role"), str)
            }
            overlap = sorted(role for role in roles if role in forbidden_roles)
            if overlap:
                result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"consumer {consumer_id!r} requires source {source_id!r} with forbidden role(s) {overlap!r}", "ForbiddenRoleFlow", {"consumer_id": consumer_id, "source_id": source_id, "forbidden_roles": overlap}))

    source_root_context = repo_root if repo_root is not None else os.getcwd()
    for record in records:
        if not isinstance(record, dict):
            continue
        source_id = record.get("source_id")
        locator = record.get("authoritative_locator")
        if not isinstance(locator, str):
            continue
        try:
            declared_root = safe_repo_relative_path(source_root_context, locator)
            root_mapping = yaml.safe_load(declared_root.read_text(encoding="utf-8"))
        except (DeclarationReferenceError, OSError, TypeError, ValueError, yaml.YAMLError):
            continue
        if not isinstance(root_mapping, Mapping):
            continue
        schema_name = root_mapping.get("schema")
        if root_mapping.get("sources") == [] and isinstance(schema_name, str) and "catalog" in schema_name.lower():
            kind = record.get("record_kind")
            lifecycle_state = record.get("lifecycle_state")
            components = record.get("components")
            if kind != "METADATA_CATALOG_TEMPLATE" or lifecycle_state != "METADATA_ONLY" or components not in (None, [], ()):
                result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"metadata template semantics for source {source_id!r} are invalid for authoritative catalog root {locator!r}", "ForbiddenRoleFlow", {"source_id": source_id, "authoritative_locator": locator, "record_kind": kind, "lifecycle_state": lifecycle_state}))

    required_nested = {
        "configs/ingest/tsc.yaml#assembly_patch",
        "configs/ingest/tsc.yaml#normalizer.version",
        "configs/ingest/tsc.yaml#TSC1.protein_accession",
        "configs/ingest/tsc.yaml#TSC2.protein_accession",
        "configs/eval/core_annotation_bundle.yaml#runtime.annotator",
        "configs/eval/core_annotation_bundle.yaml#runtime.bias_version",
        "configs/eval/core_annotation_bundle.yaml#runtime.nirvana_data_version",
        "configs/external/mave_sources.yaml#sources[0]",
        "configs/atlas/packs/tsc2/pack.yaml#assembly_pins[0]",
        "configs/atlas/packs/tsc2/pack.yaml#transcript_pins[0]",
        "configs/acmg/tsc.yaml#genes.TSC1",
        "configs/acmg/tsc.yaml#genes.TSC2",
        "configs/acmg/tsc.yaml#licensing.revel",
    }
    accounted = _accounted_locators(payload_dict, repo_root=repo_root if repo_root is not None else os.getcwd())
    root_paths: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        refs = record.get("declaration_refs")
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, dict) and ref.get("role") == "authoritative_root":
                    path = ref.get("path")
                    if isinstance(path, str) and path.strip():
                        root_paths.append(path.replace("\\", "/").strip())
    if len(root_paths) != 7 or len(set(root_paths)) != 7:
        result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", "authoritative root declarations are missing or duplicated", "SourceMetadataIncomplete", {"count": len(root_paths), "unique_count": len(set(root_paths))}))
    for root in sorted(set(root_paths)):
        count = sum(1 for item in root_paths if item == root)
        if count != 1:
            result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"root declaration path {root!r} is omitted or duplicated", "SourceMetadataIncomplete", {"path": root, "count": count}))
    for locator in sorted(required_nested):
        count = sum(1 for item in accounted if item == locator)
        if count != 1:
            result.errors.append(_error("SOURCE_METADATA_INCOMPLETE", f"required nested declaration locator {locator!r} is omitted or duplicated", "SourceMetadataIncomplete", {"locator": locator, "count": count}))

    if not result.errors:
        result.registry_valid = True
    return result


def status_for_consumer(payload: Registry | Mapping[str, Any], consumer_id: str, *, repo_root: str | os.PathLike[str] | None = None) -> ValidationResult:
    result = ValidationResult(schema=VALIDATION_SCHEMA_ID, registry_valid=False, validation_ceiling=VALIDATION_CEILING)
    if isinstance(payload, Registry):
        payload_dict = copy.deepcopy(dict(payload._raw_mapping)) if payload._raw_mapping is not None else copy.deepcopy(payload.as_dict())
    else:
        payload_dict = copy.deepcopy(dict(payload))

    validation = validate_registry(payload_dict, repo_root=repo_root)
    result.registry_valid = validation.registry_valid
    result.errors = list(validation.errors)
    if validation.errors:
        result.consumer_state = "INVALID"
        result.consumer = {"consumer_id": consumer_id, "state": "INVALID"}
        return result

    consumers = payload_dict.get("consumers")
    if not isinstance(consumers, list):
        result.errors.append(_error("CONSUMER_NOT_FOUND", f"unknown consumer_id {consumer_id!r}", "ConsumerNotFoundError", {"consumer_id": consumer_id}))
        result.consumer_state = "UNKNOWN"
        result.consumer = {"consumer_id": consumer_id, "state": "UNKNOWN"}
        return result

    consumer = next((entry for entry in consumers if isinstance(entry, dict) and entry.get("consumer_id") == consumer_id), None)
    if consumer is None:
        result.errors.append(_error("CONSUMER_NOT_FOUND", f"unknown consumer_id {consumer_id!r}", "ConsumerNotFoundError", {"consumer_id": consumer_id}))
        result.consumer_state = "UNKNOWN"
        result.consumer = {"consumer_id": consumer_id, "state": "UNKNOWN"}
        return result

    source_records = payload_dict.get("source_records")
    source_by_id = {record.get("source_id"): record for record in (source_records if isinstance(source_records, list) else []) if isinstance(record, dict) and isinstance(record.get("source_id"), str)}
    required = consumer.get("required_sources")
    if not isinstance(required, list):
        result.errors.append(_error("REGISTRY_SCHEMA_ERROR", f"consumer {consumer_id!r} has invalid required_sources", "RegistrySchemaError", {"consumer_id": consumer_id}))
        result.consumer_state = "BLOCKED"
        result.consumer = {"consumer_id": consumer_id, "state": "BLOCKED", "required_sources": required}
        return result

    if consumer_id in RESERVED_CONSUMER_IDS:
        result.errors.append(_error("FORBIDDEN_CROSS_LANE_CLAIM", f"reserved consumer {consumer_id!r} cannot become READY", "ForbiddenCrossLaneClaimError", {"consumer_id": consumer_id}))
        result.consumer_state = "BLOCKED"
        result.consumer = {"consumer_id": consumer_id, "state": "BLOCKED", "required_sources": required}
        return result

    if not required:
        result.errors.append(_error("SOURCE_BLOCKED", f"consumer {consumer_id!r} has no required sources", "SourceBlockedError", {"consumer_id": consumer_id}))
        result.consumer_state = "BLOCKED"
        result.consumer = {"consumer_id": consumer_id, "state": "BLOCKED", "required_sources": required}
        return result

    for source_id in required:
        if not isinstance(source_id, str):
            result.errors.append(_error("DANGLING_CONSUMER_OR_SOURCE", f"consumer {consumer_id!r} has a non-string source id", "DanglingConsumerOrSourceError", {"consumer_id": consumer_id, "source_id": source_id}))
            result.consumer_state = "BLOCKED"
            result.consumer = {"consumer_id": consumer_id, "state": "BLOCKED", "required_sources": required}
            return result
        source = source_by_id.get(source_id)
        if source is None:
            result.errors.append(_error("DANGLING_CONSUMER_OR_SOURCE", f"consumer {consumer_id!r} references unknown source {source_id!r}", "DanglingConsumerOrSourceError", {"consumer_id": consumer_id, "source_id": source_id}))
            result.consumer_state = "BLOCKED"
            result.consumer = {"consumer_id": consumer_id, "state": "BLOCKED", "required_sources": required}
            return result
        state = source.get("lifecycle_state")
        if state in {"CONFIRM_PENDING", "ACCESS_BLOCKED", "METADATA_ONLY", "RETIRED"}:
            result.errors.append(_error("SOURCE_BLOCKED", f"source {source_id!r} is blocked or non-activatable for consumer {consumer_id!r}", "SourceBlockedError", {"consumer_id": consumer_id, "source_id": source_id, "state": state}))
            result.consumer_state = "BLOCKED"
            result.consumer = {"consumer_id": consumer_id, "state": "BLOCKED", "required_sources": required}
            return result
        if source.get("record_kind") == "METADATA_CATALOG_TEMPLATE":
            result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"metadata catalog {source_id!r} cannot satisfy consumer {consumer_id!r}", "ForbiddenRoleFlow", {"consumer_id": consumer_id, "source_id": source_id}))
            result.consumer_state = "BLOCKED"
            result.consumer = {"consumer_id": consumer_id, "state": "BLOCKED", "required_sources": required}
            return result
        forbidden_roles = consumer.get("forbidden_source_roles", [])
        if isinstance(forbidden_roles, list):
            components = source.get("components")
            roles = {component.get("source_role") for component in (components if isinstance(components, list) else []) if isinstance(component, dict) and isinstance(component.get("source_role"), str)}
            overlap = sorted(role for role in roles if role in forbidden_roles)
            if overlap:
                result.errors.append(_error("FORBIDDEN_ROLE_FLOW", f"source {source_id!r} contains forbidden role(s) {overlap!r} for consumer {consumer_id!r}", "ForbiddenRoleFlow", {"consumer_id": consumer_id, "source_id": source_id, "forbidden_roles": overlap}))
                result.consumer_state = "BLOCKED"
                result.consumer = {"consumer_id": consumer_id, "state": "BLOCKED", "required_sources": required}
                return result
        if consumer.get("freshness_required") is True and _is_stale_source(source):
            result.errors.append(_error("SOURCE_STALE", f"source {source_id!r} is stale for consumer {consumer_id!r}", "SourceBlockedError", {"consumer_id": consumer_id, "source_id": source_id}))
            result.consumer_state = "BLOCKED"
            result.consumer = {"consumer_id": consumer_id, "state": "BLOCKED", "required_sources": required}
            return result

    result.registry_valid = True
    result.consumer_state = "READY"
    result.consumer = {"consumer_id": consumer_id, "state": "READY", "required_sources": required}
    return result
