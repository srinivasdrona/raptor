"""Offline raw-identity replay mapper for Atlas panel selection.

Loads, hash-verifies, and deep-freezes an externally acquired
``atlas.raw_identity_map.v1`` manifest plus its candidate-free
``atlas.raw_identity_map_lock.v1`` lock, cross-verifies both against the
raw discovery inventory, the bound disease pack, and the immutable official
NCBI ClinVar response bundle on disk, and returns an
:class:`OfflineRawIdentityMapper` that replays the full RP1-RP7 tuple for a
raw identity by exact-key lookup only.

Every record's resolution classification (``match_state``,
``normalization_outcome``, ``universe_key``, ``identity_state``,
``spdi_canonical``, ``hgvs_c``, ``transcript_pin``, ``residue_index``,
``codon_index``, ``consequence_class``, ``scope_decision``,
``exclusion_code``) is independently RECOMPUTED from the raw official
response bytes plus the bound disease pack and cross-checked against the
manifest's declared value -- declared values are comparands only, never
trusted. ``hgvs_p`` has no derivable ground truth in an ESummary response
and is therefore the sole pass-through field (gated only by whether the
record otherwise passes independent verification).

This module performs no network access and no environment reads: it is
pure offline verification over caller-supplied paths and an
already-constructed :class:`~raptor.atlas.model.DiseasePack`. It is
imported by both the runtime loader (this file) and, for its shared
private classification helper, by the out-of-process acquisition adapter
at ``scripts/build_atlas_raw_identity_map.py`` -- so the two can never
independently drift on what "resolved" means.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import types
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Union

import yaml

from raptor.atlas.model import (
    AtlasIdentityMapAmbiguityError,
    AtlasIdentityMapError,
    AtlasIdentityMapHashError,
    AtlasIdentityMapPathError,
    AtlasIdentityMapResponseError,
    AtlasIdentityMapSchemaError,
    DiseasePack,
    IDENTITY_STATES,
    RawIdentityReplay,
)

__all__ = [
    "OfflineRawIdentityMapper",
    "identity_map_content_hash",
    "identity_map_lock_content_hash",
    "load_identity_map",
]

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

_MAP_SCHEMA_ID = "atlas.raw_identity_map.v1"
_LOCK_SCHEMA_ID = "atlas.raw_identity_map_lock.v1"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_MAP_FIELDS = (
    "schema", "map_id", "map_version", "map_content_hash", "created_at",
    "pack_binding", "reference_binding", "raw_inventory_binding",
    "response_bundle", "acquisition_tool", "records",
)
_REQUIRED_PACK_BINDING_FIELDS = ("pack_id", "pack_version", "pack_content_hash")
_REQUIRED_REFERENCE_BINDING_FIELDS = ("provider", "database", "transcript", "assembly")
_REQUIRED_RAW_INVENTORY_BINDING_FIELDS = ("path", "sha256", "record_count")
_REQUIRED_RESPONSE_BUNDLE_FIELDS = ("sha256", "file_count", "byte_count")
_REQUIRED_ACQUISITION_TOOL_FIELDS = ("relative_path", "sha256")

_REQUIRED_LOCK_FIELDS = (
    "schema", "lock_id", "lock_version", "created_at", "map_id", "map_version",
    "map_content_hash", "map_record_count", "raw_inventory_content_hash",
    "raw_inventory_record_count", "response_bundle_hash", "response_file_count",
    "response_byte_count", "pack_binding", "reference_binding",
    "acquisition_tool_sha256", "lock_content_hash",
)

_REQUIRED_RECORD_FIELDS = (
    "raw_record_id", "raw_identity_string", "source_reported_consequence_hint",
    "search_term", "search_response_relative_path", "search_response_sha256",
    "search_count", "summary_response_pins", "match_state", "normalization_outcome",
    "universe_key", "identity_state", "spdi_canonical", "hgvs_c", "hgvs_p",
    "transcript_pin", "residue_index", "codon_index", "consequence_class",
    "scope_decision", "exclusion_code",
)
_REQUIRED_SUMMARY_PIN_FIELDS = ("uid", "relative_path", "sha256", "byte_length")
_REQUIRED_RAW_ROW_FIELDS = ("raw_record_id", "raw_identity_string", "source_reported_consequence_hint")

MATCH_STATE_RESOLVED = "resolved_unique_official_match"
MATCH_STATE_ZERO = "unresolved_official_zero_match"
MATCH_STATE_AMBIGUOUS = "unresolved_official_ambiguous_match"
MATCH_STATE_ENUM = (MATCH_STATE_RESOLVED, MATCH_STATE_ZERO, MATCH_STATE_AMBIGUOUS)

_UNRESOLVED_EXCLUSION_CODE = "X1"


# ---------------------------------------------------------------------------
# Small generic helpers
# ---------------------------------------------------------------------------


def _is_nonblank_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_schema(condition: bool, message: str) -> None:
    if not condition:
        raise AtlasIdentityMapSchemaError(message)


def _require_hash(condition: bool, message: str) -> None:
    if not condition:
        raise AtlasIdentityMapHashError(message)


def _require_path(condition: bool, message: str) -> None:
    if not condition:
        raise AtlasIdentityMapPathError(message)


def _require_response(condition: bool, message: str) -> None:
    if not condition:
        raise AtlasIdentityMapResponseError(message)


def _require_verified(condition: bool, message: str) -> None:
    if not condition:
        raise AtlasIdentityMapAmbiguityError(message)


def _require_exact_keys(value: Mapping[str, Any], expected: tuple[str, ...], *, what: str) -> None:
    actual = set(value)
    required = set(expected)
    _require_schema(
        actual == required,
        f"{what} fields must be exactly {tuple(expected)!r}; "
        f"missing={tuple(sorted(required - actual))!r} "
        f"extra={tuple(sorted(actual - required))!r}",
    )


# ---------------------------------------------------------------------------
# Canonical self-hashes (public)
# ---------------------------------------------------------------------------


def identity_map_content_hash(manifest: Mapping[str, Any]) -> str:
    """Compute the canonical ``atlas.raw_identity_map.v1`` digest of
    ``manifest``, excluding only the top-level ``map_content_hash`` key."""

    payload = {key: value for key, value in manifest.items() if key != "map_content_hash"}
    canonical_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest().lower()


def identity_map_lock_content_hash(manifest: Mapping[str, Any]) -> str:
    """Compute the canonical ``atlas.raw_identity_map_lock.v1`` digest of
    ``manifest``, excluding only the top-level ``lock_content_hash`` key."""

    payload = {key: value for key, value in manifest.items() if key != "lock_content_hash"}
    canonical_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest().lower()


def _deep_freeze(value: Any) -> Any:
    """Recursively freeze ``value``: every ``dict`` becomes a
    ``types.MappingProxyType`` wrapping a rebuilt dict of already-frozen
    children, every ``list``/``tuple`` becomes a ``tuple`` of already-frozen
    elements, scalars pass through unchanged. Never retains a reference to
    any original mutable container."""

    if isinstance(value, dict):
        return types.MappingProxyType({key: _deep_freeze(v) for key, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


# ---------------------------------------------------------------------------
# Path safety (mirrors raptor.atlas.citation's containment discipline)
# ---------------------------------------------------------------------------


def _resolve_regular_file(path: Union[str, "os.PathLike[str]"], *, what: str) -> Path:
    """Resolve a caller-supplied explicit file path, rejecting a symlink or
    Windows reparse point/junction at the candidate itself (checked via
    ``lstat`` BEFORE following it), and requiring the fully-resolved
    target to exist and be a regular file."""

    candidate = Path(path)
    try:
        candidate_lstat = candidate.lstat()
    except OSError as exc:
        raise AtlasIdentityMapPathError(f"{what} not found at {candidate}") from exc
    if stat.S_ISLNK(candidate_lstat.st_mode):
        raise AtlasIdentityMapPathError(f"{what} {candidate} must be a regular, non-symlink/junction file")
    reparse_bit = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if reparse_bit and (getattr(candidate_lstat, "st_file_attributes", 0) & reparse_bit):
        raise AtlasIdentityMapPathError(f"{what} {candidate} must not be a reparse point/junction")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise AtlasIdentityMapPathError(f"{what} not found at {candidate}") from exc
    if not resolved.is_file():
        raise AtlasIdentityMapPathError(f"{what} {resolved} must be a regular file")
    return resolved


def _resolve_response_root(path: Union[str, "os.PathLike[str]"]) -> Path:
    """Resolve the ``response_root`` directory with the same symlink/
    junction rejection discipline as :func:`_resolve_regular_file`."""

    candidate = Path(path)
    try:
        candidate_lstat = candidate.lstat()
    except OSError as exc:
        raise AtlasIdentityMapPathError(f"response_root not found at {candidate}") from exc
    if stat.S_ISLNK(candidate_lstat.st_mode):
        raise AtlasIdentityMapPathError(
            f"response_root {candidate} must be a regular directory, not a symlink/junction"
        )
    reparse_bit = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if reparse_bit and (getattr(candidate_lstat, "st_file_attributes", 0) & reparse_bit):
        raise AtlasIdentityMapPathError(
            f"response_root {candidate} must not be a reparse point/junction"
        )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise AtlasIdentityMapPathError(f"response_root not found at {candidate}") from exc
    if not resolved.is_dir():
        raise AtlasIdentityMapPathError(f"response_root {resolved} must be an existing directory")
    return resolved


def _resolve_response_artifact(response_root: Path, relative_path: Any) -> Path:
    """Resolve ``relative_path`` under ``response_root`` with full
    containment safety: rejects non-relative paths (drive, absolute,
    leading slash on either separator convention), any ``..`` traversal
    segment, an un-resolved symlink or Windows reparse point/junction AT
    THE CANDIDATE PATH ITSELF (checked via ``lstat`` before following it),
    and -- via resolved realpath containment -- any symlink/junction chain
    that escapes the root."""

    _require_path(
        isinstance(relative_path, str) and bool(relative_path),
        "response artifact relative path must be a nonblank string",
    )

    candidate_relative = Path(relative_path)
    _require_path(
        not candidate_relative.drive
        and not candidate_relative.is_absolute()
        and not relative_path.startswith("/")
        and not relative_path.startswith("\\"),
        f"response artifact relative path {relative_path!r} must be relative "
        "(no drive, no leading slash)",
    )
    _require_path(
        ".." not in candidate_relative.parts,
        f"response artifact relative path {relative_path!r} must not contain a '..' segment",
    )

    candidate = response_root / relative_path
    try:
        candidate_lstat = candidate.lstat()
    except OSError as exc:
        raise AtlasIdentityMapPathError(f"response artifact not found at {candidate}") from exc
    if stat.S_ISLNK(candidate_lstat.st_mode):
        raise AtlasIdentityMapPathError(
            f"response artifact {candidate} must be a regular, non-symlink/junction file"
        )
    reparse_bit = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if reparse_bit and (getattr(candidate_lstat, "st_file_attributes", 0) & reparse_bit):
        raise AtlasIdentityMapPathError(f"response artifact {candidate} must not be a reparse point/junction")

    try:
        real_file = candidate.resolve(strict=True)
    except OSError as exc:
        raise AtlasIdentityMapPathError(f"response artifact not found at {candidate}") from exc

    if real_file != response_root and response_root not in real_file.parents:
        raise AtlasIdentityMapPathError(
            f"response artifact {real_file} escapes the allowed response_root {response_root}"
        )
    if not real_file.is_file():
        raise AtlasIdentityMapPathError(f"response artifact {real_file} is not a regular file")

    return real_file


def _compute_bundle_hash(response_root: Path) -> tuple[str, int, int]:
    """Recompute the whole-tree response bundle hash from disk bytes,
    exactly mirroring the committed ``bundle_hash_algorithm``: sort
    relative POSIX paths, then for each update SHA-256 with
    ``path_utf8 + NUL + raw_file_bytes + NUL``. Any symlink/junction
    anywhere in the tree is rejected before any byte is read."""

    all_entries = list(response_root.rglob("*"))
    reparse_bit = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for entry in all_entries:
        try:
            entry_lstat = entry.lstat()
        except OSError as exc:
            raise AtlasIdentityMapPathError(
                f"response bundle entry cannot be inspected at {entry}"
            ) from exc
        if stat.S_ISLNK(entry_lstat.st_mode) or (
            reparse_bit
            and (getattr(entry_lstat, "st_file_attributes", 0) & reparse_bit)
        ):
            raise AtlasIdentityMapPathError(
                f"response bundle contains a symlink/junction at {entry}, which is not permitted"
            )
    files = sorted(path for path in all_entries if path.is_file())
    digest = hashlib.sha256()
    total_bytes = 0
    for path in files:
        rel = path.relative_to(response_root).as_posix()
        raw = path.read_bytes()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
        total_bytes += len(raw)
    return digest.hexdigest(), len(files), total_bytes


# ---------------------------------------------------------------------------
# YAML / JSON loading helpers
# ---------------------------------------------------------------------------


def _parse_yaml_mapping_bytes(data: bytes, *, what: str) -> dict:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AtlasIdentityMapSchemaError(f"{what} is not valid UTF-8") from exc
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AtlasIdentityMapSchemaError(f"{what} is not valid YAML") from exc
    if not isinstance(parsed, dict):
        raise AtlasIdentityMapSchemaError(f"{what} did not parse to a mapping")
    return parsed


def _parse_json_bytes(data: bytes, *, what: str) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AtlasIdentityMapResponseError(f"{what} is not valid UTF-8") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AtlasIdentityMapResponseError(f"{what} is not valid JSON") from exc


# ---------------------------------------------------------------------------
# Structural schema validation
# ---------------------------------------------------------------------------


def _validate_map_schema(manifest: Any) -> None:
    _require_schema(isinstance(manifest, dict), "raw identity map manifest must be a mapping")
    _require_exact_keys(manifest, _REQUIRED_MAP_FIELDS, what="raw identity map manifest")
    for field_name in _REQUIRED_MAP_FIELDS:
        _require_schema(
            field_name in manifest,
            f"raw identity map manifest is missing required field {field_name!r}",
        )
    _require_schema(
        manifest["schema"] == _MAP_SCHEMA_ID,
        f"raw identity map manifest 'schema' must be exactly {_MAP_SCHEMA_ID!r}, "
        f"got {manifest['schema']!r}",
    )
    _require_schema(_is_nonblank_str(manifest["map_id"]), "raw identity map manifest 'map_id' must be a nonblank string")
    _require_schema(
        _is_nonblank_str(manifest["map_version"]),
        "raw identity map manifest 'map_version' must be a nonblank string",
    )
    _require_schema(
        isinstance(manifest["map_content_hash"], str) and bool(_SHA256_HEX_RE.match(manifest["map_content_hash"])),
        "raw identity map manifest 'map_content_hash' must be a lowercase 64-hex digest",
    )
    _require_schema(
        _is_nonblank_str(manifest["created_at"]),
        "raw identity map manifest 'created_at' must be a nonblank string",
    )

    pack_binding = manifest["pack_binding"]
    _require_schema(isinstance(pack_binding, dict), "raw identity map manifest 'pack_binding' must be a mapping")
    _require_exact_keys(pack_binding, _REQUIRED_PACK_BINDING_FIELDS, what="pack_binding")
    for field_name in _REQUIRED_PACK_BINDING_FIELDS:
        _require_schema(field_name in pack_binding, f"pack_binding is missing required field {field_name!r}")

    reference_binding = manifest["reference_binding"]
    _require_schema(
        isinstance(reference_binding, dict),
        "raw identity map manifest 'reference_binding' must be a mapping",
    )
    _require_exact_keys(
        reference_binding, _REQUIRED_REFERENCE_BINDING_FIELDS, what="reference_binding"
    )
    for field_name in _REQUIRED_REFERENCE_BINDING_FIELDS:
        _require_schema(
            _is_nonblank_str(reference_binding[field_name]),
            f"reference_binding.{field_name} must be a nonblank string",
        )

    raw_inventory_binding = manifest["raw_inventory_binding"]
    _require_schema(
        isinstance(raw_inventory_binding, dict),
        "raw identity map manifest 'raw_inventory_binding' must be a mapping",
    )
    _require_exact_keys(
        raw_inventory_binding,
        _REQUIRED_RAW_INVENTORY_BINDING_FIELDS,
        what="raw_inventory_binding",
    )
    for field_name in _REQUIRED_RAW_INVENTORY_BINDING_FIELDS:
        _require_schema(
            field_name in raw_inventory_binding,
            f"raw_inventory_binding is missing required field {field_name!r}",
        )

    response_bundle = manifest["response_bundle"]
    _require_schema(isinstance(response_bundle, dict), "raw identity map manifest 'response_bundle' must be a mapping")
    _require_exact_keys(
        response_bundle, _REQUIRED_RESPONSE_BUNDLE_FIELDS, what="response_bundle"
    )
    for field_name in _REQUIRED_RESPONSE_BUNDLE_FIELDS:
        _require_schema(field_name in response_bundle, f"response_bundle is missing required field {field_name!r}")

    acquisition_tool = manifest["acquisition_tool"]
    _require_schema(isinstance(acquisition_tool, dict), "raw identity map manifest 'acquisition_tool' must be a mapping")
    _require_exact_keys(
        acquisition_tool, _REQUIRED_ACQUISITION_TOOL_FIELDS, what="acquisition_tool"
    )
    for field_name in _REQUIRED_ACQUISITION_TOOL_FIELDS:
        _require_schema(field_name in acquisition_tool, f"acquisition_tool is missing required field {field_name!r}")

    _require_schema(isinstance(manifest["records"], list), "raw identity map manifest 'records' must be a list")


def _validate_lock_schema(lock: Any) -> None:
    _require_schema(isinstance(lock, dict), "raw identity map lock must be a mapping")
    _require_exact_keys(lock, _REQUIRED_LOCK_FIELDS, what="raw identity map lock")
    for field_name in _REQUIRED_LOCK_FIELDS:
        _require_schema(field_name in lock, f"raw identity map lock is missing required field {field_name!r}")
    _require_schema(
        lock["schema"] == _LOCK_SCHEMA_ID,
        f"raw identity map lock 'schema' must be exactly {_LOCK_SCHEMA_ID!r}, got {lock['schema']!r}",
    )
    _require_schema(
        isinstance(lock["map_content_hash"], str) and bool(_SHA256_HEX_RE.match(lock["map_content_hash"])),
        "raw identity map lock 'map_content_hash' must be a lowercase 64-hex digest",
    )
    _require_schema(
        isinstance(lock["lock_content_hash"], str) and bool(_SHA256_HEX_RE.match(lock["lock_content_hash"])),
        "raw identity map lock 'lock_content_hash' must be a lowercase 64-hex digest",
    )
    _require_schema(
        isinstance(lock["response_bundle_hash"], str) and bool(_SHA256_HEX_RE.match(lock["response_bundle_hash"])),
        "raw identity map lock 'response_bundle_hash' must be a lowercase 64-hex digest",
    )
    _require_schema(
        isinstance(lock["acquisition_tool_sha256"], str) and bool(_SHA256_HEX_RE.match(lock["acquisition_tool_sha256"])),
        "raw identity map lock 'acquisition_tool_sha256' must be a lowercase 64-hex digest",
    )
    _require_schema(_is_int_not_bool(lock["map_record_count"]), "raw identity map lock 'map_record_count' must be an int")
    _require_schema(
        _is_int_not_bool(lock["raw_inventory_record_count"]),
        "raw identity map lock 'raw_inventory_record_count' must be an int",
    )
    _require_schema(
        _is_int_not_bool(lock["response_file_count"]),
        "raw identity map lock 'response_file_count' must be an int",
    )
    _require_schema(
        _is_int_not_bool(lock["response_byte_count"]),
        "raw identity map lock 'response_byte_count' must be an int",
    )
    _require_schema(isinstance(lock["pack_binding"], dict), "raw identity map lock 'pack_binding' must be a mapping")
    _require_exact_keys(
        lock["pack_binding"], _REQUIRED_PACK_BINDING_FIELDS, what="lock pack_binding"
    )
    _require_schema(
        isinstance(lock["reference_binding"], dict),
        "raw identity map lock 'reference_binding' must be a mapping",
    )
    _require_exact_keys(
        lock["reference_binding"],
        _REQUIRED_REFERENCE_BINDING_FIELDS,
        what="lock reference_binding",
    )


def _validate_raw_inventory_schema(raw_manifest: Any) -> None:
    _require_schema(isinstance(raw_manifest, dict), "raw inventory must parse to a mapping")
    _require_schema("rows" in raw_manifest, "raw inventory is missing required field 'rows'")
    rows = raw_manifest["rows"]
    _require_schema(isinstance(rows, list), "raw inventory 'rows' must be a list")
    for row in rows:
        _require_schema(isinstance(row, dict), "raw inventory row must be a mapping")
        for field_name in _REQUIRED_RAW_ROW_FIELDS:
            _require_schema(field_name in row, f"raw inventory row is missing required field {field_name!r}")
            _require_schema(
                _is_nonblank_str(row[field_name]),
                f"raw inventory row field {field_name!r} must be a nonblank string",
            )


def _validate_summary_pin_schema(pin: Any) -> None:
    _require_schema(isinstance(pin, dict), "summary_response_pins entry must be a mapping")
    _require_exact_keys(pin, _REQUIRED_SUMMARY_PIN_FIELDS, what="summary_response_pins entry")
    for field_name in _REQUIRED_SUMMARY_PIN_FIELDS:
        _require_schema(field_name in pin, f"summary_response_pins entry is missing required field {field_name!r}")
    _require_schema(_is_nonblank_str(pin["uid"]), "summary_response_pins entry 'uid' must be a nonblank string")
    _require_schema(
        _is_nonblank_str(pin["relative_path"]),
        "summary_response_pins entry 'relative_path' must be a nonblank string",
    )
    _require_schema(
        isinstance(pin["sha256"], str) and bool(_SHA256_HEX_RE.match(pin["sha256"])),
        "summary_response_pins entry 'sha256' must be a lowercase 64-hex digest",
    )
    _require_schema(
        _is_int_not_bool(pin["byte_length"]) and pin["byte_length"] >= 0,
        "summary_response_pins entry 'byte_length' must be a non-negative int",
    )


def _validate_record_schema(record: Any) -> None:
    _require_schema(isinstance(record, dict), "map record must be a mapping")
    _require_exact_keys(record, _REQUIRED_RECORD_FIELDS, what="map record")
    for field_name in _REQUIRED_RECORD_FIELDS:
        _require_schema(field_name in record, f"map record is missing required field {field_name!r}")

    _require_schema(_is_nonblank_str(record["raw_record_id"]), "map record 'raw_record_id' must be a nonblank string")
    _require_schema(
        _is_nonblank_str(record["raw_identity_string"]),
        "map record 'raw_identity_string' must be a nonblank string",
    )
    _require_schema(
        _is_nonblank_str(record["source_reported_consequence_hint"]),
        "map record 'source_reported_consequence_hint' must be a nonblank string",
    )
    _require_schema(_is_nonblank_str(record["search_term"]), "map record 'search_term' must be a nonblank string")
    _require_schema(
        _is_nonblank_str(record["search_response_relative_path"]),
        "map record 'search_response_relative_path' must be a nonblank string",
    )
    _require_schema(
        isinstance(record["search_response_sha256"], str)
        and bool(_SHA256_HEX_RE.match(record["search_response_sha256"])),
        "map record 'search_response_sha256' must be a lowercase 64-hex digest",
    )
    _require_schema(
        _is_int_not_bool(record["search_count"]) and record["search_count"] >= 0,
        "map record 'search_count' must be a non-negative int",
    )
    _require_schema(
        isinstance(record["summary_response_pins"], list),
        "map record 'summary_response_pins' must be a list",
    )
    for pin in record["summary_response_pins"]:
        _validate_summary_pin_schema(pin)

    _require_schema(
        record["match_state"] in MATCH_STATE_ENUM,
        f"map record 'match_state' must be one of {MATCH_STATE_ENUM}, got {record['match_state']!r}",
    )
    _require_schema(
        record["identity_state"] in IDENTITY_STATES,
        f"map record 'identity_state' must be one of {IDENTITY_STATES}, got {record['identity_state']!r}",
    )
    for optional_str_field in (
        "spdi_canonical", "hgvs_c", "hgvs_p", "transcript_pin", "consequence_class", "exclusion_code",
    ):
        value = record[optional_str_field]
        _require_schema(
            value is None or isinstance(value, str),
            f"map record {optional_str_field!r} must be a string or null, got {value!r}",
        )
    for optional_int_field in ("residue_index", "codon_index"):
        value = record[optional_int_field]
        _require_schema(
            value is None or _is_int_not_bool(value),
            f"map record {optional_int_field!r} must be an int or null, got {value!r}",
        )
    _require_schema(
        _is_nonblank_str(record["normalization_outcome"]),
        "map record 'normalization_outcome' must be a nonblank string",
    )
    _require_schema(_is_nonblank_str(record["universe_key"]), "map record 'universe_key' must be a nonblank string")
    _require_schema(_is_nonblank_str(record["scope_decision"]), "map record 'scope_decision' must be a nonblank string")


# ---------------------------------------------------------------------------
# Disease pack accessors (exactly-one-pin conventions)
# ---------------------------------------------------------------------------


def _single(values: Any, *, what: str) -> str:
    _require_schema(isinstance(values, (tuple, list)), f"disease pack {what} must be a tuple/list")
    _require_verified(len(values) == 1, f"disease pack {what} must pin exactly one value, got {len(values)!r}")
    return values[0]


def _single_allowed_gene(disease_pack: DiseasePack) -> str:
    return _single(disease_pack.allowed_genes, what="allowed_genes")


def _single_assembly_pin(disease_pack: DiseasePack) -> str:
    return _single(disease_pack.assembly_pins, what="assembly_pins")


def _single_pinned_transcript(disease_pack: DiseasePack) -> str:
    """Return the sole pinned transcript accession, accepting either a bare
    string entry or a mapping with a ``transcript`` key (mirrors
    ``identity.py``'s ``_pack_transcript_aliases`` dict-or-string handling)."""

    pin = _single(disease_pack.transcript_pins, what="transcript_pins")
    if isinstance(pin, (dict, types.MappingProxyType)):
        transcript = pin.get("transcript")
        _require_verified(
            _is_nonblank_str(transcript),
            f"disease pack transcript_pins entry {pin!r} must have a nonblank 'transcript' key",
        )
        return transcript
    _require_verified(
        _is_nonblank_str(pin),
        f"disease pack transcript_pins entry {pin!r} must be a nonblank string or mapping",
    )
    return pin


# ---------------------------------------------------------------------------
# Deterministic derivation: title parsing, three-to-one conversion,
# consequence/scope classification
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(
    r"^(?P<transcript>[^()]+)\((?P<gene>[^()]+)\):(?P<hgvs_c>c\.[^\s()]+)\s*\(p\.(?P<protein3>[^()]+)\)\s*$"
)
_PROTEIN_CHANGE_RE = re.compile(r"^p\.(?P<ref>[A-Za-z]{3}|\*)(?P<position>\d+)(?P<alt>[A-Za-z]{3}|\*)$")

_THREE_TO_ONE = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C", "Gln": "Q",
    "Glu": "E", "Gly": "G", "His": "H", "Ile": "I", "Leu": "L", "Lys": "K",
    "Met": "M", "Phe": "F", "Pro": "P", "Ser": "S", "Thr": "T", "Trp": "W",
    "Tyr": "Y", "Val": "V", "Ter": "*",
}

#: Deterministic Sequence-Ontology-style molecular-consequence term to
#: condition-agnostic consequence class. Values are generic bioinformatics
#: vocabulary (not disease-specific literals).
_CONSEQUENCE_TERM_TO_CLASS = {
    "missense variant": "missense_substitution",
    "synonymous variant": "synonymous_substitution",
    "nonsense variant": "nonsense_substitution",
    "stop gained": "nonsense_substitution",
    "stop lost": "stop_lost",
    "start lost": "start_lost",
    "initiator codon variant": "start_lost",
    "frameshift variant": "frameshift_variant",
    "splice donor variant": "splice_variant",
    "splice acceptor variant": "splice_variant",
    "splice region variant": "splice_variant",
    "inframe deletion": "inframe_indel",
    "inframe insertion": "inframe_indel",
}
_IN_SCOPE_CONSEQUENCE_CLASSES = frozenset(
    {
        "missense_substitution", "nonsense_substitution", "frameshift_variant",
        "splice_variant", "inframe_indel", "stop_lost", "start_lost",
    }
)


def _three_to_one(code: str) -> str:
    if code == "*":
        return "*"
    one_letter = _THREE_TO_ONE.get(code)
    _require_response(one_letter is not None, f"unrecognized three-letter amino acid code {code!r}")
    return one_letter


def _parse_protein_change(raw_identity_string: str) -> tuple[str, int, str]:
    match = _PROTEIN_CHANGE_RE.match(raw_identity_string)
    _require_schema(
        match is not None,
        f"raw_identity_string {raw_identity_string!r} is not a recognized 'p.<Ref><Pos><Alt>' "
        "protein change",
    )
    ref = _three_to_one(match.group("ref"))
    alt = _three_to_one(match.group("alt"))
    position = int(match.group("position"))
    return ref, position, alt


def _classify_consequence(molecular_consequence_list: Any) -> tuple[str, str]:
    _require_response(
        isinstance(molecular_consequence_list, list),
        "esummary response 'molecular_consequence_list' must be a list",
    )
    for term in molecular_consequence_list:
        if not isinstance(term, str):
            continue
        consequence_class = _CONSEQUENCE_TERM_TO_CLASS.get(term.strip().lower())
        if consequence_class is not None:
            scope_decision = "in_scope" if consequence_class in _IN_SCOPE_CONSEQUENCE_CLASSES else "out_of_scope"
            return consequence_class, scope_decision
    raise AtlasIdentityMapResponseError(
        f"molecular_consequence_list {molecular_consequence_list!r} does not permit a "
        "deterministic consequence/scope classification"
    )


def _normalize_raw_identity(raw_identity_string: str) -> str:
    """Idempotent normalization used ONLY for the unresolved
    ``universe_key`` hash input (never for exact-key replay comparison,
    which stays character-identical). A no-op for already-clean ASCII
    protein-change strings such as ``\"p.Lys2Glu\"``."""

    normalized = unicodedata.normalize("NFC", raw_identity_string).strip()
    return re.sub(r"\s+", " ", normalized)


class _DerivedRecord:
    """Pure, independently-recomputed resolution classification for one
    raw identity, shared verbatim between the loader (comparand) and the
    acquisition adapter (construction)."""

    __slots__ = (
        "match_state", "normalization_outcome", "universe_key", "identity_state",
        "spdi_canonical", "hgvs_c", "transcript_pin", "residue_index", "codon_index",
        "consequence_class", "scope_decision", "exclusion_code", "search_count", "search_term",
    )

    def __init__(
        self,
        *,
        match_state: str,
        normalization_outcome: str,
        universe_key: str,
        identity_state: str,
        spdi_canonical: Optional[str],
        hgvs_c: Optional[str],
        transcript_pin: Optional[str],
        residue_index: Optional[int],
        codon_index: Optional[int],
        consequence_class: Optional[str],
        scope_decision: str,
        exclusion_code: Optional[str],
        search_count: int,
        search_term: str,
    ) -> None:
        self.match_state = match_state
        self.normalization_outcome = normalization_outcome
        self.universe_key = universe_key
        self.identity_state = identity_state
        self.spdi_canonical = spdi_canonical
        self.hgvs_c = hgvs_c
        self.transcript_pin = transcript_pin
        self.residue_index = residue_index
        self.codon_index = codon_index
        self.consequence_class = consequence_class
        self.scope_decision = scope_decision
        self.exclusion_code = exclusion_code
        self.search_count = search_count
        self.search_term = search_term


def _unresolved_derived(raw_identity_string: str, search_term: str, count: int, match_state: str) -> _DerivedRecord:
    universe_key = "UNRESOLVED:" + hashlib.sha256(
        _normalize_raw_identity(raw_identity_string).encode("utf-8")
    ).hexdigest()
    return _DerivedRecord(
        match_state=match_state,
        normalization_outcome="unresolved_identity",
        universe_key=universe_key,
        identity_state="unresolved",
        spdi_canonical=None,
        hgvs_c=None,
        transcript_pin=None,
        residue_index=None,
        codon_index=None,
        consequence_class=None,
        scope_decision="unresolved",
        exclusion_code=_UNRESOLVED_EXCLUSION_CODE,
        search_count=count,
        search_term=search_term,
    )


def _classify_record(
    *,
    raw_record_id: str,
    raw_identity_string: str,
    search_payload: Mapping[str, Any],
    summary_payloads: Mapping[str, Mapping[str, Any]],
    disease_pack: DiseasePack,
) -> _DerivedRecord:
    """Independently derive the full resolution classification for one raw
    identity from already-parsed, already hash-verified official response
    JSON. Never indexes ``idlist[0]``/any fixed index outside the exact
    ``search_count == 1`` branch below -- an ambiguous (``> 1``) result is
    NEVER disambiguated by picking a preferred candidate."""

    gene = _single_allowed_gene(disease_pack)
    transcript = _single_pinned_transcript(disease_pack)
    assembly = _single_assembly_pin(disease_pack)
    search_term = f"{raw_identity_string}[varname] AND {gene}[gene]"

    _require_response(
        isinstance(search_payload, dict) and not search_payload.get("error"),
        f"esearch response for {raw_record_id!r} reports an error or is not a mapping",
    )
    esearchresult = search_payload.get("esearchresult")
    _require_response(
        isinstance(esearchresult, dict),
        f"esearch response for {raw_record_id!r} is missing 'esearchresult'",
    )
    _require_response(
        not esearchresult.get("ERROR"),
        f"esearch response for {raw_record_id!r} reports ERROR {esearchresult.get('ERROR')!r}",
    )
    try:
        count = int(esearchresult["count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AtlasIdentityMapResponseError(
            f"esearch response for {raw_record_id!r} has a missing/malformed 'count'"
        ) from exc
    idlist = esearchresult.get("idlist")
    _require_response(
        isinstance(idlist, list),
        f"esearch response for {raw_record_id!r} has a missing/malformed 'idlist'",
    )
    _require_response(
        len(idlist) == count,
        f"esearch response for {raw_record_id!r} idlist length does not match its own count",
    )
    _require_response(
        set(idlist) == set(summary_payloads.keys()),
        f"esearch response for {raw_record_id!r} does not have exactly one pinned esummary "
        "response per returned uid",
    )

    if count == 0:
        return _unresolved_derived(raw_identity_string, search_term, count, MATCH_STATE_ZERO)
    if count > 1:
        # Multi-match: NEVER inspect summary content to pick a "best" or
        # "first" candidate. Ambiguity is recorded verbatim.
        return _unresolved_derived(raw_identity_string, search_term, count, MATCH_STATE_AMBIGUOUS)

    uid = idlist[0]
    summary = summary_payloads[uid]
    _require_response(isinstance(summary, dict), f"esummary response for {raw_record_id!r}/{uid} must be a mapping")

    gene_sort = summary.get("gene_sort")
    genes = summary.get("genes")
    gene_identified = gene_sort == gene and isinstance(genes, list) and any(
        isinstance(entry, dict) and entry.get("symbol") == gene for entry in genes
    )
    _require_verified(
        gene_identified,
        f"esummary response for {raw_record_id!r} gene_sort/genes {gene_sort!r}/{genes!r} "
        f"does not identify the pinned gene {gene!r}",
    )

    title = summary.get("title")
    _require_response(isinstance(title, str), f"esummary response for {raw_record_id!r} is missing a 'title' string")
    title_match = _TITLE_RE.match(title)
    _require_verified(
        title_match is not None,
        f"esummary title {title!r} for {raw_record_id!r} is not a recognized "
        "'<transcript>(<gene>):c.<hgvs_c> (p.<protein change>)' title",
    )
    _require_verified(
        title_match.group("transcript") == transcript and title_match.group("gene") == gene,
        f"esummary title {title!r} for {raw_record_id!r} does not identify the pinned "
        f"transcript/gene {transcript!r}({gene!r})",
    )

    ref, position, alt = _parse_protein_change(raw_identity_string)
    _require_verified(
        title_match.group("protein3") == raw_identity_string[len("p."):],
        f"esummary title protein change {title_match.group('protein3')!r} for {raw_record_id!r} "
        f"does not match the queried raw identity string {raw_identity_string!r}",
    )
    alias_one_letter = f"{ref}{position}{alt}"

    protein_change = summary.get("protein_change")
    _require_verified(
        isinstance(protein_change, str) and alias_one_letter in protein_change,
        f"esummary protein_change {protein_change!r} for {raw_record_id!r} does not contain the "
        f"queried alias {alias_one_letter!r} (three-to-one conversion of {raw_identity_string!r})",
    )

    variation_set = summary.get("variation_set")
    _require_response(
        isinstance(variation_set, list),
        f"esummary response for {raw_record_id!r} is missing 'variation_set'",
    )
    qualifying_spdi: Optional[str] = None
    qualifying_count = 0
    for entry in variation_set:
        if not isinstance(entry, dict):
            continue
        for loc in entry.get("variation_loc") or ():
            if isinstance(loc, dict) and loc.get("status") == "current" and loc.get("assembly_name") == assembly:
                qualifying_count += 1
                qualifying_spdi = entry.get("canonical_spdi")
                break
    _require_verified(
        qualifying_count == 1,
        f"esummary response for {raw_record_id!r} does not supply exactly one current "
        f"{assembly!r} variation_loc (found {qualifying_count})",
    )
    _require_response(
        isinstance(qualifying_spdi, str) and qualifying_spdi.count(":") == 3,
        f"esummary canonical_spdi {qualifying_spdi!r} for {raw_record_id!r} is not a well-formed "
        "SPDI string",
    )

    consequence_class, scope_decision = _classify_consequence(summary.get("molecular_consequence_list"))

    hgvs_c = f"{transcript}:{title_match.group('hgvs_c')}"

    return _DerivedRecord(
        match_state=MATCH_STATE_RESOLVED,
        normalization_outcome="resolved_identity",
        universe_key=qualifying_spdi,
        identity_state="resolved",
        spdi_canonical=qualifying_spdi,
        hgvs_c=hgvs_c,
        transcript_pin=transcript,
        residue_index=position,
        codon_index=position,
        consequence_class=consequence_class,
        scope_decision=scope_decision,
        exclusion_code=None,
        search_count=count,
        search_term=search_term,
    )


def _verify_record_matches_declared(record: Mapping[str, Any], derived: _DerivedRecord) -> None:
    expected = {
        "search_count": derived.search_count,
        "search_term": derived.search_term,
        "match_state": derived.match_state,
        "normalization_outcome": derived.normalization_outcome,
        "universe_key": derived.universe_key,
        "identity_state": derived.identity_state,
        "spdi_canonical": derived.spdi_canonical,
        "hgvs_c": derived.hgvs_c,
        "transcript_pin": derived.transcript_pin,
        "residue_index": derived.residue_index,
        "codon_index": derived.codon_index,
        "consequence_class": derived.consequence_class,
        "scope_decision": derived.scope_decision,
        "exclusion_code": derived.exclusion_code,
    }
    for field_name, expected_value in expected.items():
        declared_value = record.get(field_name)
        _require_verified(
            declared_value == expected_value,
            f"map record {record.get('raw_record_id')!r} declares {field_name}={declared_value!r} "
            f"but independently recomputes to {expected_value!r}",
        )

    # hgvs_p has no derivable ground truth in an ESummary response; only its
    # null-ness (resolved <-> non-null, unresolved <-> null) is checked.
    declared_hgvs_p = record.get("hgvs_p")
    if derived.identity_state == "resolved":
        _require_verified(
            _is_nonblank_str(declared_hgvs_p),
            f"map record {record.get('raw_record_id')!r} has a resolved identity_state but a "
            f"null/blank hgvs_p",
        )
    else:
        _require_verified(
            declared_hgvs_p is None,
            f"map record {record.get('raw_record_id')!r} has an unresolved identity_state but a "
            f"non-null hgvs_p {declared_hgvs_p!r}",
        )


# ---------------------------------------------------------------------------
# Offline mapper
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _StoredRecord:
    raw_identity_string: str
    source_reported_consequence_hint: str
    replay: RawIdentityReplay


class OfflineRawIdentityMapper:
    """Offline, hash-verified, deep-frozen :class:`RawIdentityMapper`
    implementation. Never constructed directly by callers -- only returned
    by :func:`load_identity_map`. ``replay`` performs an exact-key lookup
    plus character-identical comparison of the raw identity string and
    source-reported consequence hint; no fallback, repair, or fuzzy match
    is ever attempted."""

    __slots__ = ("_records",)

    def __init__(self, records: Mapping[str, _StoredRecord]) -> None:
        self._records = records

    @property
    def records(self) -> Mapping[str, _StoredRecord]:
        return self._records

    def replay(
        self,
        raw_record_id: str,
        raw_identity_string: str,
        source_reported_consequence_hint: str,
    ) -> RawIdentityReplay:
        stored = self._records.get(raw_record_id)
        if stored is None:
            raise AtlasIdentityMapAmbiguityError(f"unknown raw_record_id {raw_record_id!r}")
        if stored.raw_identity_string != raw_identity_string:
            raise AtlasIdentityMapAmbiguityError(
                f"raw_identity_string {raw_identity_string!r} does not match the pinned value "
                f"{stored.raw_identity_string!r} for raw_record_id {raw_record_id!r}"
            )
        if stored.source_reported_consequence_hint != source_reported_consequence_hint:
            raise AtlasIdentityMapAmbiguityError(
                f"source_reported_consequence_hint {source_reported_consequence_hint!r} does not "
                f"match the pinned value {stored.source_reported_consequence_hint!r} for "
                f"raw_record_id {raw_record_id!r}"
            )
        return stored.replay


# ---------------------------------------------------------------------------
# Cross-binding verification
# ---------------------------------------------------------------------------


def _verify_self_hash(manifest: Mapping[str, Any], *, key: str, compute, path: Path, what: str) -> None:
    declared = manifest.get(key)
    computed = compute(manifest)
    _require_hash(
        isinstance(declared, str) and declared == computed,
        f"{what} at {path} has {key}={declared!r} but recomputes to {computed!r}",
    )


def _verify_lock_matches_map(lock: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    checks = (
        ("map_id", lock.get("map_id"), manifest.get("map_id")),
        ("map_version", lock.get("map_version"), manifest.get("map_version")),
        ("map_content_hash", lock.get("map_content_hash"), manifest.get("map_content_hash")),
        ("map_record_count", lock.get("map_record_count"), len(manifest.get("records", ()))),
        ("pack_binding", lock.get("pack_binding"), manifest.get("pack_binding")),
        ("reference_binding", lock.get("reference_binding"), manifest.get("reference_binding")),
    )
    for name, lock_value, map_value in checks:
        _require_hash(
            lock_value == map_value,
            f"lock {name}={lock_value!r} does not match map {name}={map_value!r}",
        )


def _verify_pack_binding(declared: Mapping[str, Any], disease_pack: DiseasePack) -> None:
    expected = {
        "pack_id": disease_pack.pack_id,
        "pack_version": disease_pack.pack_version,
        "pack_content_hash": disease_pack.pack_content_hash,
    }
    for key, value in expected.items():
        _require_hash(
            declared.get(key) == value,
            f"map pack_binding.{key}={declared.get(key)!r} does not match the bound disease "
            f"pack's {key}={value!r}",
        )


def _verify_reference_binding(
    declared: Mapping[str, Any], disease_pack: DiseasePack
) -> None:
    pinned_transcripts = {
        (
            pin.get("transcript")
            if isinstance(pin, Mapping)
            else pin
        )
        for pin in disease_pack.transcript_pins
    }
    _require_hash(
        declared.get("transcript") in pinned_transcripts,
        "map reference_binding.transcript is not pinned by the bound disease pack",
    )
    _require_hash(
        declared.get("assembly") in set(disease_pack.assembly_pins),
        "map reference_binding.assembly is not pinned by the bound disease pack",
    )


def _verify_raw_inventory_binding(
    declared: Mapping[str, Any],
    actual_sha256: str,
    raw_manifest: Mapping[str, Any],
    lock: Mapping[str, Any],
    actual_path: Path,
) -> None:
    declared_path = declared.get("path")
    _require_path(
        isinstance(declared_path, str)
        and bool(declared_path)
        and not Path(declared_path).drive
        and not Path(declared_path).is_absolute()
        and not declared_path.startswith("/")
        and not declared_path.startswith("\\")
        and ".." not in Path(declared_path).parts,
        "map raw_inventory_binding.path must be a safe relative path",
    )
    _require_hash(
        declared_path == actual_path.name,
        "map raw_inventory_binding.path does not identify the supplied raw inventory file",
    )
    _require_hash(
        declared.get("sha256") == actual_sha256,
        "map raw_inventory_binding.sha256 does not match the recomputed raw inventory hash",
    )
    _require_hash(
        lock.get("raw_inventory_content_hash") == actual_sha256,
        "lock raw_inventory_content_hash does not match the recomputed raw inventory hash",
    )
    row_count = len(raw_manifest.get("rows", ()))
    _require_schema(
        declared.get("record_count") == row_count,
        "map raw_inventory_binding.record_count does not match the actual row count",
    )
    _require_schema(
        lock.get("raw_inventory_record_count") == row_count,
        "lock raw_inventory_record_count does not match the actual row count",
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_identity_map(
    map_path: Union[str, "os.PathLike[str]"],
    *,
    response_root: Union[str, "os.PathLike[str]"],
    lock_path: Union[str, "os.PathLike[str]"],
    disease_pack: DiseasePack,
    raw_inventory_path: Union[str, "os.PathLike[str]"],
) -> OfflineRawIdentityMapper:
    """Load, hash-verify, cross-bind, and deep-freeze a raw identity map and
    its candidate-free lock, returning an offline replay mapper.

    Every self-hash, lock<->map binding, pack binding, raw-inventory
    binding, acquisition-tool hash, response-bundle hash, per-file hash,
    and per-record resolution classification is independently recomputed
    from disk bytes and cross-checked; declared values are comparands
    only, never trusted. Performs no network access and reads no
    environment variables.
    """

    resolved_map_path = _resolve_regular_file(map_path, what="raw identity map manifest")
    resolved_lock_path = _resolve_regular_file(lock_path, what="raw identity map lock")
    resolved_raw_inventory_path = _resolve_regular_file(raw_inventory_path, what="raw inventory")
    resolved_response_root = _resolve_response_root(response_root)

    manifest = _parse_yaml_mapping_bytes(resolved_map_path.read_bytes(), what="raw identity map manifest")
    _validate_map_schema(manifest)
    _verify_self_hash(
        manifest, key="map_content_hash", compute=identity_map_content_hash,
        path=resolved_map_path, what="raw identity map manifest",
    )

    lock = _parse_yaml_mapping_bytes(resolved_lock_path.read_bytes(), what="raw identity map lock")
    _validate_lock_schema(lock)
    _verify_self_hash(
        lock, key="lock_content_hash", compute=identity_map_lock_content_hash,
        path=resolved_lock_path, what="raw identity map lock",
    )

    _verify_lock_matches_map(lock, manifest)
    _verify_pack_binding(manifest["pack_binding"], disease_pack)
    _verify_reference_binding(manifest["reference_binding"], disease_pack)

    raw_inventory_bytes = resolved_raw_inventory_path.read_bytes()
    raw_inventory_sha256 = hashlib.sha256(raw_inventory_bytes).hexdigest()
    raw_manifest = _parse_yaml_mapping_bytes(raw_inventory_bytes, what="raw inventory")
    _validate_raw_inventory_schema(raw_manifest)
    _verify_raw_inventory_binding(
        manifest["raw_inventory_binding"],
        raw_inventory_sha256,
        raw_manifest,
        lock,
        resolved_raw_inventory_path,
    )

    tool_relative_path = manifest["acquisition_tool"]["relative_path"]
    tool_path = _resolve_response_artifact(resolved_response_root, tool_relative_path)
    tool_sha256 = hashlib.sha256(tool_path.read_bytes()).hexdigest()
    _require_hash(
        tool_sha256 == manifest["acquisition_tool"]["sha256"],
        "map acquisition_tool.sha256 does not match the recomputed tool file hash",
    )
    _require_hash(
        tool_sha256 == lock["acquisition_tool_sha256"],
        "lock acquisition_tool_sha256 does not match the recomputed tool file hash",
    )

    bundle_sha256, file_count, byte_count = _compute_bundle_hash(resolved_response_root)
    declared_bundle = manifest["response_bundle"]
    _require_hash(
        (declared_bundle.get("sha256"), declared_bundle.get("file_count"), declared_bundle.get("byte_count"))
        == (bundle_sha256, file_count, byte_count),
        "map response_bundle does not match the recomputed response bundle hash/file_count/byte_count",
    )
    _require_hash(
        (lock.get("response_bundle_hash"), lock.get("response_file_count"), lock.get("response_byte_count"))
        == (bundle_sha256, file_count, byte_count),
        "lock response_bundle_hash/response_file_count/response_byte_count does not match the "
        "recomputed response bundle",
    )

    raw_rows = raw_manifest.get("rows", [])
    raw_rows_by_id: dict = {}
    for row in raw_rows:
        raw_record_id = row["raw_record_id"]
        _require_schema(
            raw_record_id not in raw_rows_by_id,
            f"raw inventory contains a duplicate raw_record_id {raw_record_id!r}",
        )
        raw_rows_by_id[raw_record_id] = row

    map_records = manifest["records"]
    _require_schema(
        len(map_records) == len(raw_rows),
        "map record_count does not match the raw inventory row count",
    )

    records: dict = {}
    for record in map_records:
        _validate_record_schema(record)
        raw_record_id = record["raw_record_id"]
        _require_schema(
            raw_record_id not in records,
            f"raw identity map contains a duplicate raw_record_id {raw_record_id!r}",
        )

        row = raw_rows_by_id.get(raw_record_id)
        _require_schema(
            row is not None,
            f"map record {raw_record_id!r} has no matching raw inventory row",
        )
        _require_schema(
            row["raw_identity_string"] == record["raw_identity_string"]
            and row["source_reported_consequence_hint"] == record["source_reported_consequence_hint"],
            f"map record {raw_record_id!r} disagrees with its raw inventory row",
        )

        search_path = _resolve_response_artifact(resolved_response_root, record["search_response_relative_path"])
        search_bytes = search_path.read_bytes()
        _require_hash(
            hashlib.sha256(search_bytes).hexdigest() == record["search_response_sha256"],
            f"search response for {raw_record_id!r} does not match its declared sha256",
        )
        search_payload = _parse_json_bytes(search_bytes, what=f"search response for {raw_record_id!r}")

        summary_payloads: dict = {}
        for pin in record["summary_response_pins"]:
            summary_path = _resolve_response_artifact(resolved_response_root, pin["relative_path"])
            summary_bytes = summary_path.read_bytes()
            _require_hash(
                len(summary_bytes) == pin["byte_length"] and hashlib.sha256(summary_bytes).hexdigest() == pin["sha256"],
                f"summary response for {raw_record_id!r}/{pin['uid']} does not match its declared "
                "sha256/byte_length",
            )
            summary_json = _parse_json_bytes(summary_bytes, what=f"summary response for {raw_record_id!r}/{pin['uid']}")
            result = summary_json.get("result") if isinstance(summary_json, dict) else None
            _require_response(
                isinstance(result, dict) and pin["uid"] in result,
                f"summary response for {raw_record_id!r}/{pin['uid']} is missing its own uid in 'result'",
            )
            summary_payloads[pin["uid"]] = result[pin["uid"]]

        derived = _classify_record(
            raw_record_id=raw_record_id,
            raw_identity_string=record["raw_identity_string"],
            search_payload=search_payload,
            summary_payloads=summary_payloads,
            disease_pack=disease_pack,
        )
        _verify_record_matches_declared(record, derived)

        replay = RawIdentityReplay(
            normalization_outcome=derived.normalization_outcome,
            universe_key=derived.universe_key,
            identity_state=derived.identity_state,
            spdi_canonical=derived.spdi_canonical,
            hgvs_c=derived.hgvs_c,
            hgvs_p=record["hgvs_p"],
            transcript_pin=derived.transcript_pin,
            residue_index=derived.residue_index,
            codon_index=derived.codon_index,
            consequence_class=derived.consequence_class,
            scope_decision=derived.scope_decision,
            exclusion_code=derived.exclusion_code,
        )
        records[raw_record_id] = _StoredRecord(
            raw_identity_string=record["raw_identity_string"],
            source_reported_consequence_hint=record["source_reported_consequence_hint"],
            replay=replay,
        )

    return OfflineRawIdentityMapper(types.MappingProxyType(records))
