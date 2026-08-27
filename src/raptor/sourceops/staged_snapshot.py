from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import sys
import threading
import time
import uuid
from datetime import datetime

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from raptor.sourceops.model import CliResult, SourceOpsError, VerifyStageResult
from raptor.sourceops.registry import load_registry, validate_registry

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGED_SNAPSHOT_VALIDATION_CEILING = "V2-S2 records offline deterministic observations about supplied staged bytes and their declared comparison to one V2-S1 baseline. It makes no materiality, approval, promotion, lifecycle, scientific, legal, clinical, consumer-impact, or rollback decision."
CANONICAL_REGISTRY_REL = "configs/sourceops/source_registry.yaml"
STAGING_PARENT_REL = ".raptor/sourceops/staging"
OUTPUT_PARENT_REL = ".raptor/sourceops/generated/staged-snapshots"
# Scratch files for the temp-then-hard-link publish protocol live only
# inside the target leaf directory and are always named with this prefix,
# so a concurrent identical writer's in-flight temp file is never mistaken
# for an unexpected leaf entry (see `_write_atomic_json`/`_ensure_output_leaf`).
TEMP_ARTIFACT_PREFIX = ".sourceops-artifact-tmp-"
# The whole-leaf transaction lock is a single, fixed-name internal entry
# (never a per-run-unique name) so every writer contends on the exact same
# path; see `_ensure_output_leaf`/`_acquire_transaction_lock`. Ownership of a
# leaf's transaction is arbitrated in-process by `_LEAF_TRANSACTION_LOCKS`
# (real, unconditional mutual exclusion between concurrent callers that
# share this interpreter's memory -- e.g. threads within one long-lived
# process) *and*, authoritatively, by the on-disk file of this same fixed
# name -- the sole thing a genuinely separate process can observe, and
# never merely advisory. It is created exclusively
# (`O_CREAT|O_EXCL|O_WRONLY`) with deterministic, parseable owner metadata
# (`pid`, unique `token`, `version`) written and `fsync`-ed before
# ownership is ever considered active, and a caller must not proceed past
# it without winning it. If the file already exists, its bytes are
# inspected without following links: a parsed, live owner pid is
# bounded-polled/waited for release
# before retrying; invalid/foreign bytes or a dead/orphaned owner fail
# closed immediately; and either way the lock and any foreign leaf content
# are preserved byte-for-byte -- this run never reclaims, deletes, or
# seizes a lock file it did not itself create. Only the run that itself
# created the file (matching token) ever removes it, and only after this
# run's own publish or rollback has fully finished.
TRANSACTION_LOCK_NAME = ".sourceops-transaction.lock"
_TRANSACTION_LOCK_ACQUIRE_TIMEOUT_SECONDS = 30.0
_TRANSACTION_LOCK_FILE_RETRY_SLEEP_SECONDS = 0.01
_TRANSACTION_LOCK_RELEASE_RETRY_SECONDS = 8.0
_LEAF_TRANSACTION_LOCKS: dict[str, threading.Lock] = {}
_LEAF_TRANSACTION_REGISTRY_GUARD = threading.Lock()
# Records, per lock path, the exact token this process itself most
# recently wrote when it created that lock file -- consulted only by
# `_release_transaction_lock` so a run can positively confirm (belt-and-
# suspenders on top of `O_CREAT|O_EXCL` exclusivity) that it still owns
# the file before ever unlinking it.
_TRANSACTION_LOCK_OWN_TOKENS: dict[str, str] = {}

MANIFEST_SCHEMA_ID = "raptor.sourceops.staged_snapshot_manifest.v1"
MANIFEST_HASH_BASIS = "raptor.sourceops.staged_snapshot_manifest_content_hash.v1"
VERIFICATION_SCHEMA_ID = "raptor.sourceops.staged_snapshot_verification.v1"
VERIFICATION_HASH_BASIS = "raptor.sourceops.staged_snapshot_verification_content_hash.v1"
DIFF_SCHEMA_ID = "raptor.sourceops.staged_snapshot_diff.v1"
DIFF_HASH_BASIS = "raptor.sourceops.staged_snapshot_diff_content_hash.v1"
INPUT_TREE_HASH_BASIS = "raptor.sourceops.staged_snapshot_input_tree_content_hash.v1"
CLI_SCHEMA_ID = "raptor.sourceops.staged_snapshot_cli_result.v1"

FILE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
STAGE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

DIFF_KIND_ORDER = {"CONTENT": 0, "METADATA": 1, "DECLARATION": 2}
FACT_KIND_ORDER = {"IDENTITY": 0, "VERSION": 1, "CHECKSUM": 2, "MANIFEST": 3, "COMPONENT": 4, "METADATA": 5}
SUBJECT_TYPE_ORDER = {"SOURCE": 0, "FILE": 1, "COMPONENT": 2, "DECLARATION": 3}
DUPLICATE_KEY_MSG = "duplicate mapping key"
MAXIMUM_MANIFEST_PARSED_DEPTH = 16


def _json_safe_scalar(value: Any) -> str:
    """Deterministic string form for a value with no direct JSON scalar or
    object-key representation (non-finite float, or any other Python-specific
    value). Never falls back to a raw ``repr()`` of an arbitrary object,
    which could embed a non-deterministic memory address.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value == float("inf"):
            return "inf"
        if value == float("-inf"):
            return "-inf"
        return repr(value)
    if isinstance(value, int):
        return str(value)
    return f"<{type(value).__name__}>"


def _json_safe_detail(value: Any) -> Any:
    """Recursively normalize an error detail value (``subject``/``expected``/
    ``actual``) so it is always JSON-serializable with ``allow_nan=False``.

    The staged manifest is untrusted YAML input and can legally parse into
    non-finite floats (``.nan``/``.inf``/``-.inf``) or, in principle, other
    values without a direct JSON representation. Error envelopes must report
    a deterministic, JSON-safe fact about what was observed instead of
    letting a raw Python object reach ``json.dumps(allow_nan=False)`` and
    crash the CLI boundary. This normalizer is used only for error-detail
    construction; it never touches manifest content used for hashing or
    semantic validation, which must keep rejecting non-finite values as
    invalid rather than silently normalizing them into valid data.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return _json_safe_scalar(value)
        return value
    if isinstance(value, dict):
        return {
            (key if isinstance(key, str) else _json_safe_scalar(key)): _json_safe_detail(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe_detail(item) for item in value]
    return _json_safe_scalar(value)


class StagedSnapshotError(SourceOpsError):
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, *, code: str | None = None, phase: str, exit_code: int, subject: Any = None, expected: Any = None, actual: Any = None) -> None:
        final_code = code or self.code
        super().__init__(message, code=final_code)
        self.code = final_code
        self.phase = phase
        self.exit_code = exit_code
        self.subject = _json_safe_detail(subject)
        self.expected = _json_safe_detail(expected)
        self.actual = _json_safe_detail(actual)

    def as_error_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "type": self.__class__.__name__,
            "phase": self.phase,
            "message": self.message,
            "subject": self.subject,
            "expected": self.expected,
            "actual": self.actual,
        }


class CliUsageError(StagedSnapshotError):
    code = "CLI_USAGE_ERROR"


class BaselineRegistryPathError(StagedSnapshotError):
    code = "BASELINE_REGISTRY_PATH_INVALID"


class StagingRootError(StagedSnapshotError):
    code = "STAGING_ROOT_INVALID"


class StagingManifestMissingError(StagedSnapshotError):
    code = "STAGING_MANIFEST_MISSING"


class StagingManifestTypeError(StagedSnapshotError):
    code = "STAGING_MANIFEST_TYPE_INVALID"


class StagingManifestReadError(StagedSnapshotError):
    code = "STAGING_MANIFEST_READ_FAILED"


class StagingManifestLimitError(StagedSnapshotError):
    code = "STAGING_MANIFEST_LIMIT_EXCEEDED"


class StagingManifestEncodingError(StagedSnapshotError):
    code = "STAGING_MANIFEST_ENCODING_INVALID"


class StagingManifestYamlError(StagedSnapshotError):
    code = "STAGING_MANIFEST_YAML_INVALID"


class StagingManifestSchemaError(StagedSnapshotError):
    code = "STAGING_MANIFEST_SCHEMA_INVALID"


class StagingDuplicateIdError(StagedSnapshotError):
    code = "STAGING_DUPLICATE_ID"


class StagingDuplicatePathError(StagedSnapshotError):
    code = "STAGING_DUPLICATE_PATH"


class StagingManifestHashMismatch(StagedSnapshotError):
    code = "STAGING_MANIFEST_HASH_MISMATCH"


class BaselineRegistryInvalidError(StagedSnapshotError):
    code = "BASELINE_REGISTRY_INVALID"


class BaselineDeclarationInvalidError(StagedSnapshotError):
    code = "BASELINE_DECLARATION_INVALID"


class UnknownSourceError(StagedSnapshotError):
    code = "UNKNOWN_SOURCE"


class BaselineRegistryHashMismatch(StagedSnapshotError):
    code = "BASELINE_REGISTRY_HASH_MISMATCH"


class BaselineDeclarationBindingMismatch(StagedSnapshotError):
    code = "BASELINE_DECLARATION_BINDING_MISMATCH"


class BaselineChangedDuringRunError(StagedSnapshotError):
    code = "BASELINE_CHANGED_DURING_RUN"


class StagingPathError(StagedSnapshotError):
    code = "STAGING_PATH_INVALID"


class StagingEntryTypeError(StagedSnapshotError):
    code = "STAGING_ENTRY_TYPE_INVALID"


class StagingTreeMismatchError(StagedSnapshotError):
    code = "STAGING_TREE_MISMATCH"


class StagingLimitError(StagedSnapshotError):
    code = "STAGING_LIMIT_EXCEEDED"


class ContentBindingError(StagedSnapshotError):
    code = "CONTENT_BINDING_INVALID"


class ComponentMappingError(StagedSnapshotError):
    code = "COMPONENT_MAPPING_INVALID"


class StagingFileSizeMismatch(StagedSnapshotError):
    code = "STAGING_FILE_SIZE_MISMATCH"


class StagingFileChecksumMismatch(StagedSnapshotError):
    code = "STAGING_FILE_CHECKSUM_MISMATCH"


class StagingTextEncodingError(StagedSnapshotError):
    code = "STAGING_TEXT_ENCODING_INVALID"


class StagingFileReadError(StagedSnapshotError):
    code = "STAGING_FILE_READ_FAILED"


class StagingInputMutationError(StagedSnapshotError):
    code = "STAGING_INPUT_MUTATED"


class OutputBoundaryError(StagedSnapshotError):
    code = "OUTPUT_BOUNDARY_INVALID"


class OutputCollisionError(StagedSnapshotError):
    code = "OUTPUT_COLLISION"


class OutputWriteError(StagedSnapshotError):
    code = "OUTPUT_WRITE_FAILED"


class InternalStageError(StagedSnapshotError):
    code = "INTERNAL_ERROR"


@dataclass(frozen=True)
class StageSnapshot:
    manifest_bytes: bytes
    files: dict[str, tuple[dict[str, Any], bytes, dict[str, Any]]]  # path -> (metadata, raw, stat)


def _is_windows_reparse(path: Path) -> bool:
    # Detect any Windows reparse point (junction, mount point, native
    # symlink, or other reparse tag) from the lstat metadata itself, so
    # detection does not depend on os.path.isjunction (added in 3.12) being
    # importable. st_file_attributes (3.5+) and st_reparse_tag (3.8+) are
    # both populated by an lstat() call (no follow) on every supported
    # Python/Windows combination; os.path.isjunction is consulted only as
    # an additional signal, never as the sole basis for a negative result.
    if os.name != "nt":
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    reparse_attr = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    file_attributes = int(getattr(st, "st_file_attributes", 0))
    reparse_tag = int(getattr(st, "st_reparse_tag", 0))
    if reparse_tag != 0 or (file_attributes & reparse_attr) != 0:
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is None:
        return False
    try:
        return bool(isjunction(str(path)))
    except OSError:
        return False


def _repo_root() -> Path:
    return REPO_ROOT


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _canonical_path_subject(path: Path, *, root: Path) -> str:
    """Canonical forward-slash error ``subject`` for a filesystem Path.

    This is the single site that turns a filesystem Path into an error
    ``subject``: the Path is expressed relative to its governing root (the
    staging root for staging-phase subjects, the repository root for
    output-phase and ancestor-boundary subjects) and rendered with
    ``PurePath.as_posix()``. Every path-derived subject across staging,
    output, root-boundary, ancestor-reparse, write, and collision sites
    must be built through this helper so it can never leak a native
    Windows backslash separator, a drive letter, or an absolute path.
    """
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.as_posix()
    return relative.as_posix()


def _assert_no_reparse_ancestors(path: Path, *, root: Path, error: type[StagedSnapshotError], phase: str, subject: Any, message: str, exit_code: int = 2) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise error(message, phase=phase, exit_code=exit_code, subject=subject) from exc
    current = root
    for part in relative.parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(st.st_mode) or _is_windows_reparse(current):
            raise error(message, phase=phase, exit_code=exit_code, subject=_canonical_path_subject(current, root=root))


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _duplicate_casefold_count(values: Iterable[str]) -> tuple[str | None, int, str | None]:
    counts: dict[str, int] = {}
    matches: dict[str, list[str]] = {}
    for value in values:
        if not isinstance(value, str):
            continue
        key = value.casefold()
        counts[key] = counts.get(key, 0) + 1
        matches.setdefault(key, []).append(value)
    collisions = sorted((key for key, count in counts.items() if count > 1), key=lambda key: key)
    if not collisions:
        return None, 0, None
    key = collisions[0]
    canonical = sorted(matches[key], key=lambda item: item.casefold())[0]
    return key, counts[key], canonical


def _ancestor_relation(first: str, second: str) -> bool:
    if not first or not second:
        return False
    left = first.strip("/").split("/")
    right = second.strip("/").split("/")
    if len(left) < len(right):
        return right[: len(left)] == left
    return left[: len(right)] == right


def _manifest_hash_for(mapping: dict[str, Any]) -> str:
    cloned = copy.deepcopy(mapping)
    cloned.pop("manifest_content_hash", None)
    return _sha256_hex(_canonical_json_bytes(cloned))


def _artifact_hash_for(payload: dict[str, Any]) -> str:
    cloned = copy.deepcopy(payload)
    cloned.pop("artifact_content_hash", None)
    return _sha256_hex(_canonical_json_bytes(cloned))


def _normalize_repo_rel(raw: str, *, check_canonical: bool = False) -> str:
    if not isinstance(raw, str):
        raise ValueError("path must be a string")
    normalized = raw.replace("\\", "/").strip()
    if not normalized:
        raise ValueError("empty path")
    if normalized.startswith("file://") or normalized.startswith("/") or normalized.startswith("//") or re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError("absolute or uri path")
    if ".." in normalized.split("/"):
        raise ValueError("traversal path")
    if "//" in normalized or normalized.startswith("./"):
        raise ValueError("unsafe path")
    if normalized.startswith("~"):
        raise ValueError("unsafe path")
    if "\x00" in normalized:
        raise ValueError("NUL path")
    if any(ord(ch) < 32 for ch in normalized):
        raise ValueError("control chars")
    if check_canonical and normalized != CANONICAL_REGISTRY_REL:
        raise ValueError("not canonical registry path")
    return normalized


def _is_valid_stage_segment(segment: str) -> bool:
    if not segment or segment.startswith("."):
        return False
    if segment in {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}:
        return False
    if segment.endswith(".") or segment.endswith(" "):
        return False
    if any(ch.isspace() for ch in segment):
        return False
    if ":" in segment:
        return False
    return bool(STAGE_SEGMENT_RE.fullmatch(segment))


def _validate_staging_root(staging_root_rel: str) -> Path:
    root_value = staging_root_rel.replace("\\", "/").strip()
    if not root_value:
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=staging_root_rel)
    if root_value.startswith("file://") or root_value.startswith("/") or root_value.startswith("//"):
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value)
    if re.match(r"^[A-Za-z]:/", root_value):
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value)
    if "/../" in root_value or root_value.startswith("../") or root_value == "..":
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value)
    parts = root_value.split("/")
    if len(parts) != 4:
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value)
    if parts[0] != ".raptor" or parts[1] != "sourceops" or parts[2] != "staging":
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value)
    stage_name = parts[3]
    if not _is_valid_stage_segment(stage_name):
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value)
    stage_root = REPO_ROOT / root_value
    if not stage_root.is_relative_to(REPO_ROOT):
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value)
    _assert_no_reparse_ancestors(stage_root, root=REPO_ROOT, error=StagingRootError, phase="BOUNDARY", subject=root_value, message="staging root is outside the designated safe staging boundary")
    if not stage_root.exists():
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value)
    try:
        st = os.lstat(stage_root)
    except OSError as exc:
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value) from exc
    if _is_windows_reparse(stage_root) or stat.S_ISLNK(st.st_mode) or stat.S_ISREG(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise StagingRootError("staging root is outside the designated safe staging boundary", phase="BOUNDARY", exit_code=2, subject=root_value)
    return stage_root


def _validate_registry_path(registry_rel: str) -> Path:
    normalized = registry_rel.replace("\\", "/").strip()
    if normalized != CANONICAL_REGISTRY_REL:
        raise BaselineRegistryPathError("baseline registry path is not the canonical safe V2-S1 registry", phase="BOUNDARY", exit_code=6, subject=normalized)
    path = REPO_ROOT / normalized
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise BaselineRegistryPathError("baseline registry path is not the canonical safe V2-S1 registry", phase="BOUNDARY", exit_code=6, subject=normalized) from exc
    if not resolved.is_relative_to(REPO_ROOT):
        raise BaselineRegistryPathError("baseline registry path is not the canonical safe V2-S1 registry", phase="BOUNDARY", exit_code=6, subject=normalized)
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise BaselineRegistryPathError("baseline registry path is not the canonical safe V2-S1 registry", phase="BOUNDARY", exit_code=6, subject=normalized)
    return path


def _safe_yaml_loader() -> type[yaml.SafeLoader]:
    class StrictLoader(yaml.SafeLoader):
        pass

    def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.nodes.ScalarNode) and key_node.value == "<<":
                raise yaml.constructor.ConstructorError("while constructing a mapping", key_node.start_mark, "merge key is not allowed", key_node.start_mark)
            key = loader.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                ) from exc
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
    return StrictLoader


def _reject_excessive_manifest_depth(text: str, *, limit: int = MAXIMUM_MANIFEST_PARSED_DEPTH) -> None:
    """Bound YAML container nesting depth with an iterative token/event scan
    before any recursive compose or construct step ever runs.

    ``yaml.parse()`` drives PyYAML's scanner/parser as a flat generator over
    ``SequenceStart``/``SequenceEnd``/``MappingStart``/``MappingEnd`` events
    using an internal state machine, not one Python call frame per nesting
    level. That keeps this walk safe even for a manifest engineered to
    exhaust the Python call stack, unlike ``yaml.compose_all()``/
    ``yaml.load_all()``, whose Composer recurses once per nesting level and
    can raise ``RecursionError`` deep inside PyYAML on extreme input. Malformed
    or otherwise-unsafe YAML encountered during this scan is left for the
    existing MANIFEST_SCHEMA-phase checks that run immediately afterward.
    """
    depth = 0
    try:
        for event in yaml.parse(text):
            if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
                depth += 1
                if depth > limit:
                    raise StagingManifestLimitError(
                        "staged manifest exceeds a closed size or structure limit",
                        phase="MANIFEST_READ",
                        exit_code=2,
                        subject="manifest.yaml",
                        expected=f"<= {limit} parsed depth",
                        actual=depth,
                    )
            elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                depth -= 1
    except yaml.YAMLError:
        return


def _reject_unsafe_yaml_events(text: str) -> None:
    try:
        for event in yaml.parse(text):
            if isinstance(event, yaml.events.AliasEvent):
                raise StagingManifestYamlError("staged manifest is not one safe YAML mapping document", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml")
    except yaml.YAMLError as exc:
        raise StagingManifestYamlError("staged manifest is not one safe YAML mapping document", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml") from exc


def _reject_unsafe_yaml_nodes(text: str) -> None:
    try:
        docs = list(yaml.compose_all(text))
    except yaml.YAMLError as exc:
        raise StagingManifestYamlError("staged manifest is not one safe YAML mapping document", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml") from exc
    for doc in docs:
        def walk(node: yaml.nodes.Node) -> None:
            if isinstance(node, yaml.nodes.ScalarNode):
                tag = node.tag
                if tag not in {"tag:yaml.org,2002:str", "tag:yaml.org,2002:int", "tag:yaml.org,2002:float", "tag:yaml.org,2002:bool", "tag:yaml.org,2002:null", "tag:yaml.org,2002:seq", "tag:yaml.org,2002:map"}:
                    raise StagingManifestYamlError("staged manifest is not one safe YAML mapping document", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml")
                return
            if isinstance(node, yaml.nodes.MappingNode):
                for key_node, value_node in node.value:
                    if isinstance(key_node, yaml.nodes.ScalarNode) and key_node.value == "<<":
                        raise StagingManifestYamlError("staged manifest is not one safe YAML mapping document", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml")
                    walk(key_node)
                    walk(value_node)
                return
            if isinstance(node, yaml.nodes.SequenceNode):
                for item in node.value:
                    walk(item)
        if doc is not None:
            walk(doc)


def _count_manifest_nodes(value: Any) -> int:
    if isinstance(value, dict):
        total = 1
        for child in value.values():
            total += 1 + _count_manifest_nodes(child)
        return total
    if isinstance(value, list):
        total = 1
        for child in value:
            total += _count_manifest_nodes(child)
        return total
    return 1


def _measure_manifest_depth(value: Any) -> int:
    if isinstance(value, dict):
        if not value:
            return 1
        return 1 + max(_measure_manifest_depth(child) for child in value.values())
    if isinstance(value, list):
        if not value:
            return 1
        return 1 + max(_measure_manifest_depth(child) for child in value)
    return 0


def _assert_manifest_keys_are_strings(value: Any, *, subject: str) -> None:
    # The parsed tree must be JSON-compatible: every mapping key at every
    # nesting level has to be str. Ordinary YAML scalars (int/bool/float/
    # null) survive strict construction as hashable non-string keys, so this
    # walk is the only place that closes that gap before any closed-key-set
    # detail construction (which sorts keys and would raise a raw TypeError
    # on a mixed-type key set) or typed conversion ever sees the mapping.
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise StagingManifestSchemaError(
                    "staged manifest violates the closed typed schema",
                    phase="MANIFEST_SCHEMA",
                    exit_code=2,
                    subject=subject,
                    expected="string mapping key",
                    actual=key,
                )
            _assert_manifest_keys_are_strings(child, subject=f"{subject}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_manifest_keys_are_strings(item, subject=f"{subject}[{index}]")


def _load_manifest_yaml(raw: bytes) -> dict[str, Any]:
    if len(raw) > 262144:
        raise StagingManifestLimitError("staged manifest exceeds a closed size or structure limit", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml")
    if b"\x00" in raw:
        raise StagingManifestEncodingError("staged manifest is not valid strict UTF-8", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StagingManifestEncodingError("staged manifest is not valid strict UTF-8", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml") from exc
    if not text.strip():
        raise StagingManifestYamlError("staged manifest is not one safe YAML mapping document", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml")
    # Depth must be bounded with a non-recursive scan before anything below
    # this point composes or constructs a node/Python tree; PyYAML's Composer
    # recurses once per nesting level and can otherwise exhaust the Python
    # call stack on pathological input (see _reject_excessive_manifest_depth).
    _reject_excessive_manifest_depth(text, limit=MAXIMUM_MANIFEST_PARSED_DEPTH)
    try:
        _reject_unsafe_yaml_events(text)
        _reject_unsafe_yaml_nodes(text)
        try:
            documents = list(yaml.load_all(text, Loader=_safe_yaml_loader()))
        except yaml.YAMLError as exc:
            raise StagingManifestYamlError("staged manifest is not one safe YAML mapping document", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml") from exc
        if len(documents) != 1 or documents[0] is None:
            raise StagingManifestYamlError("staged manifest is not one safe YAML mapping document", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml")
        manifest = documents[0]
        if _count_manifest_nodes(manifest) > 10000 or _measure_manifest_depth(manifest) > MAXIMUM_MANIFEST_PARSED_DEPTH:
            raise StagingManifestLimitError("staged manifest exceeds a closed size or structure limit", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml")
        if not isinstance(manifest, dict):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml")
        _assert_manifest_keys_are_strings(manifest, subject="manifest")
    except RecursionError as exc:
        # Defense in depth: the depth pre-scan above is expected to reject
        # every manifest that could otherwise exhaust the Python call stack
        # during compose/construct, but any residual RecursionError from this
        # point forward is still a structure-limit fact, never a raw
        # INTERNAL_ERROR or an escaping interpreter traceback.
        raise StagingManifestLimitError(
            "staged manifest exceeds a closed size or structure limit",
            phase="MANIFEST_READ",
            exit_code=2,
            subject="manifest.yaml",
        ) from exc
    return manifest


def _validate_identifier(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="identifier", actual=type(value).__name__)
    if not re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", value):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="identifier", actual=value)
    return value


def _validate_hash(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="lowercase_sha256", actual=type(value).__name__)
    if not HASH_RE.fullmatch(value):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="lowercase_sha256", actual=value)
    return value


def _validate_general_string(value: Any, *, field_name: str, max_len: int = 1024) -> str:
    if not isinstance(value, str):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="string", actual=type(value).__name__)
    if not value or value.strip() != value:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="trimmed string", actual=value)
    if any((ord(ch) < 32 and ch not in {"\n", "\t"}) or ord(ch) == 127 for ch in value):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="no control chars", actual=value)
    if len(value) > max_len:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected=f"<= {max_len} chars", actual=len(value))
    return value


def _validate_path_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="string", actual=type(value).__name__)
    if not value or value.strip() != value:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="non-empty trimmed string", actual=value)
    if "\\" in value:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="forward-slash path", actual=value)
    if value.startswith(("/", "./", "../", "file://")) or value.startswith("~"):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="repo-relative path", actual=value)
    if re.match(r"^[A-Za-z]:/", value):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="repo-relative path", actual=value)
    if value.startswith("//") or "//" in value:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="repo-relative path", actual=value)
    if value.endswith(".") or value.endswith(" "):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="path", actual=value)
    segments = value.split("/")
    if len(segments) > 8:
        raise StagingLimitError("staging tree exceeds a closed file, directory, depth, or byte limit", phase="INVENTORY", exit_code=2, subject=field_name, expected="<= 8 path segments", actual=len(segments))
    for segment in segments:
        if not segment:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="valid path segment", actual=value)
        if segment in {".", ".."}:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="valid path segment", actual=value)
        if ":" in segment or any(ch.isspace() for ch in segment):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="valid path segment", actual=value)
        if segment.lower() in {"con", "prn", "aux", "nul"} and segment == segment.lower():
            raise StagingPathError("a staged path is unsafe or escapes the designated root", phase="INVENTORY", exit_code=2, subject=value)
        if segment.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", segment, re.IGNORECASE):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="valid path segment", actual=value)
        if len(segment) > 100:
            raise StagingLimitError("staging tree exceeds a closed file, directory, depth, or byte limit", phase="INVENTORY", exit_code=2, subject=field_name, expected="<= 100 characters per path segment", actual=len(segment))
        if len(value) > 120:
            raise StagingLimitError("staging tree exceeds a closed file, directory, depth, or byte limit", phase="INVENTORY", exit_code=2, subject=field_name, expected="<= 120 characters total", actual=len(value))
        if not PATH_SEGMENT_RE.fullmatch(segment):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=field_name, expected="path segment regex", actual=value)
    return value


def _validate_manifest_shape(manifest: dict[str, Any]) -> dict[str, Any]:
    required_top = [
        "schema",
        "manifest_content_hash",
        "hash_basis",
        "observed_at",
        "source_binding",
        "candidate",
        "files",
        "content_bindings",
        "component_projection",
    ]
    if set(manifest) != set(required_top):
        missing = [k for k in required_top if k not in manifest]
        extra = [k for k in manifest if k not in required_top]
        if missing or extra:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest", expected=required_top, actual=sorted(manifest.keys()))
    if manifest.get("schema") != MANIFEST_SCHEMA_ID:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="schema", expected=MANIFEST_SCHEMA_ID, actual=manifest.get("schema"))
    if manifest.get("hash_basis") != MANIFEST_HASH_BASIS:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="hash_basis", expected=MANIFEST_HASH_BASIS, actual=manifest.get("hash_basis"))
    _validate_hash(manifest.get("manifest_content_hash"), field_name="manifest_content_hash")
    if not isinstance(manifest.get("observed_at"), str) or not UTC_TS_RE.fullmatch(manifest["observed_at"]):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="observed_at", expected="UTC timestamp", actual=manifest.get("observed_at"))
    source_binding = manifest.get("source_binding")
    if not isinstance(source_binding, dict):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="source_binding", expected="mapping", actual=type(source_binding).__name__)
    if set(source_binding) != {"source_id", "registry_content_hash", "declaration_refs"}:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="source_binding", expected=["source_id", "registry_content_hash", "declaration_refs"], actual=sorted(source_binding.keys()))
    _validate_identifier(source_binding.get("source_id"), field_name="source_binding.source_id")
    _validate_hash(source_binding.get("registry_content_hash"), field_name="source_binding.registry_content_hash")
    refs = source_binding.get("declaration_refs")
    if not isinstance(refs, list):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="source_binding.declaration_refs", expected="list", actual=refs)
    if not (1 <= len(refs) <= 16):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="source_binding.declaration_refs", expected="1..16 entries", actual=len(refs))
    for idx, ref in enumerate(refs):
        if not isinstance(ref, dict):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"source_binding.declaration_refs[{idx}]", expected="mapping", actual=type(ref).__name__)
        if set(ref) != {"path", "role", "canonical_lf_sha256", "authority_scope"}:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"source_binding.declaration_refs[{idx}]", expected=["path", "role", "canonical_lf_sha256", "authority_scope"], actual=sorted(ref.keys()))
        _validate_path_string(ref.get("path"), field_name=f"source_binding.declaration_refs[{idx}].path")
        if not isinstance(ref.get("role"), str) or not ref["role"].strip():
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"source_binding.declaration_refs[{idx}].role", expected="non-empty string", actual=ref.get("role"))
        _validate_hash(ref.get("canonical_lf_sha256"), field_name=f"source_binding.declaration_refs[{idx}].canonical_lf_sha256")
        if not isinstance(ref.get("authority_scope"), str) or not ref["authority_scope"].strip():
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"source_binding.declaration_refs[{idx}].authority_scope", expected="non-empty string", actual=ref.get("authority_scope"))
    candidate = manifest.get("candidate")
    if not isinstance(candidate, dict):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate", expected="mapping", actual=type(candidate).__name__)
    if set(candidate) != {"snapshot_id", "identity", "release", "licence", "acquisition"}:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate", expected=["snapshot_id", "identity", "release", "licence", "acquisition"], actual=sorted(candidate.keys()))
    _validate_identifier(candidate.get("snapshot_id"), field_name="candidate.snapshot_id")
    identity = candidate.get("identity")
    if not isinstance(identity, dict) or set(identity) != {"display_name", "record_kind", "owner", "authoritative_locator"}:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.identity", expected=["display_name", "record_kind", "owner", "authoritative_locator"], actual=sorted(identity.keys()) if isinstance(identity, dict) else type(identity).__name__)
    _validate_general_string(identity.get("display_name"), field_name="candidate.identity.display_name")
    # record_kind must be type-checked before the closed-enum membership test:
    # a non-string value (e.g. a YAML sequence/mapping) is unhashable and
    # would otherwise raise a raw TypeError out of `not in {...}` instead of
    # failing closed with the typed schema error.
    record_kind = identity.get("record_kind")
    if not isinstance(record_kind, str) or record_kind not in {"SINGLE_SOURCE", "COMPOSITE_MANIFEST", "POLICY_SOURCE_REGISTER", "METADATA_CATALOG_TEMPLATE"}:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.identity.record_kind", expected=["SINGLE_SOURCE", "COMPOSITE_MANIFEST", "POLICY_SOURCE_REGISTER", "METADATA_CATALOG_TEMPLATE"], actual=record_kind)
    _validate_general_string(identity.get("owner"), field_name="candidate.identity.owner")
    _validate_general_string(identity.get("authoritative_locator"), field_name="candidate.identity.authoritative_locator")

    release = candidate.get("release")
    if not isinstance(release, dict) or set(release) != {"version_or_snapshot", "release_date", "retrieved_at", "content_pin_status"}:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.release", expected=["version_or_snapshot", "release_date", "retrieved_at", "content_pin_status"], actual=sorted(release.keys()) if isinstance(release, dict) else type(release).__name__)
    _validate_general_string(release.get("version_or_snapshot"), field_name="candidate.release.version_or_snapshot")
    if release.get("release_date") is not None:
        if not isinstance(release["release_date"], str):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.release.release_date", expected="date or null", actual=release.get("release_date"))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release["release_date"]):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.release.release_date", expected="YYYY-MM-DD or null", actual=release.get("release_date"))
        try:
            if datetime.strptime(release["release_date"], "%Y-%m-%d").date() > datetime.strptime(manifest["observed_at"], "%Y-%m-%dT%H:%M:%SZ").date():
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.release.release_date", expected="<= observed_at date", actual=release["release_date"])
        except ValueError as exc:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.release.release_date", expected="YYYY-MM-DD or null", actual=release.get("release_date")) from exc
    if not isinstance(release.get("retrieved_at"), str) or not UTC_TS_RE.fullmatch(release["retrieved_at"]):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.release.retrieved_at", expected="UTC timestamp", actual=release.get("retrieved_at"))
    try:
        retrieved_dt = datetime.strptime(release["retrieved_at"], "%Y-%m-%dT%H:%M:%SZ")
        observed_dt = datetime.strptime(manifest["observed_at"], "%Y-%m-%dT%H:%M:%SZ")
        if retrieved_dt > observed_dt:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.release.retrieved_at", expected="<= observed_at", actual=release["retrieved_at"])
    except ValueError as exc:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.release.retrieved_at", expected="UTC timestamp", actual=release.get("retrieved_at")) from exc
    _validate_general_string(release.get("content_pin_status"), field_name="candidate.release.content_pin_status")

    licence = candidate.get("licence")
    if not isinstance(licence, dict):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.licence", expected="mapping", actual=type(licence).__name__)
    if set(licence) != {"status", "identifier_or_family", "terms_locator", "permitted_use", "redistribution", "cloud_egress", "verification_basis"}:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.licence", expected=["status", "identifier_or_family", "terms_locator", "permitted_use", "redistribution", "cloud_egress", "verification_basis"], actual=sorted(licence.keys()))
    for key in licence:
        _validate_general_string(licence.get(key), field_name=f"candidate.licence.{key}")

    acquisition = candidate.get("acquisition")
    if not isinstance(acquisition, dict) or set(acquisition) != {"method", "operator_contract", "writes_outside_repository"}:
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.acquisition", expected=["method", "operator_contract", "writes_outside_repository"], actual=sorted(acquisition.keys()) if isinstance(acquisition, dict) else type(acquisition).__name__)
    _validate_general_string(acquisition.get("method"), field_name="candidate.acquisition.method")
    _validate_general_string(acquisition.get("operator_contract"), field_name="candidate.acquisition.operator_contract")
    if not isinstance(acquisition.get("writes_outside_repository"), bool):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="candidate.acquisition.writes_outside_repository", expected="boolean", actual=type(acquisition.get("writes_outside_repository")).__name__)

    files = manifest.get("files")
    if not isinstance(files, list) or not (1 <= len(files) <= 64):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="files", expected="1..64 entries", actual=len(files) if isinstance(files, list) else type(files).__name__)
    file_required_keys = {"file_id", "path", "role", "media_type", "checksum", "component_ids"}
    for idx, row in enumerate(files):
        if not isinstance(row, dict):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}]", expected="mapping", actual=type(row).__name__)
        if set(row) != file_required_keys:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}]", expected=["file_id", "path", "role", "media_type", "checksum", "component_ids"], actual=sorted(row.keys()))
    # file_id must be a validated identifier string before it is used to build,
    # sort, or compare the files[*].file_id sequence below: mixed scalar types
    # (int, bool, float, null) are not mutually comparable and must fail closed
    # here rather than raise a raw TypeError out of sorted()/duplicate detection.
    for idx, row in enumerate(files):
        file_id = row.get("file_id")
        if not isinstance(file_id, str) or not FILE_IDENTIFIER_RE.fullmatch(file_id):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].file_id", expected="file_identifier", actual=file_id)
    duplicated_id = _duplicate_casefold_count([row["file_id"] for row in files])
    if duplicated_id[0] is not None:
        raise StagingDuplicateIdError("staged manifest contains a duplicate or case-colliding identifier", phase="MANIFEST_SCHEMA", exit_code=2, subject=duplicated_id[2] or "files.file_id", expected="unique", actual=duplicated_id[1])
    duplicated_path = _duplicate_casefold_count([row["path"] for row in files])
    if duplicated_path[0] is not None:
        raise StagingDuplicatePathError("staged manifest contains a duplicate or case-colliding file path", phase="MANIFEST_SCHEMA", exit_code=2, subject=duplicated_path[2] or "files.path", expected="unique", actual=duplicated_path[1])
    file_ids = [row["file_id"] for row in files]
    if file_ids != sorted(file_ids):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="files", expected="strictly ascending file_id order", actual=file_ids)
    file_paths = []
    for idx, row in enumerate(files):
        path = row.get("path")
        _validate_path_string(path, field_name=f"files[{idx}].path")
        if path == "manifest.yaml":
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].path", expected="non-manifest path", actual=path)
        file_paths.append(path)
        # role/media_type/checksum.mode must be type-checked before their
        # closed-enum membership tests: a non-string value (e.g. a YAML
        # sequence/mapping) is unhashable and would otherwise raise a raw
        # TypeError out of `not in {...}` instead of failing closed with the
        # typed schema error.
        role_value = row.get("role")
        if not isinstance(role_value, str) or role_value not in {"SNAPSHOT_CONTENT", "CANDIDATE_DECLARATION", "AUXILIARY_METADATA"}:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].role", expected=["SNAPSHOT_CONTENT", "CANDIDATE_DECLARATION", "AUXILIARY_METADATA"], actual=role_value)
        media_type_value = row.get("media_type")
        if not isinstance(media_type_value, str) or media_type_value not in {"application/octet-stream", "application/gzip", "application/json", "application/x-yaml", "text/plain", "text/csv", "text/tab-separated-values"}:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].media_type", expected=["application/octet-stream", "application/gzip", "application/json", "application/x-yaml", "text/plain", "text/csv", "text/tab-separated-values"], actual=media_type_value)
        checksum = row.get("checksum")
        if not isinstance(checksum, dict):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].checksum", expected="mapping", actual=type(checksum).__name__)
        if set(checksum) != {"mode", "raw_byte_size", "raw_sha256", "canonical_lf_utf8_bytes", "canonical_lf_sha256"}:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].checksum", expected=["mode", "raw_byte_size", "raw_sha256", "canonical_lf_utf8_bytes", "canonical_lf_sha256"], actual=sorted(checksum.keys()))
        checksum_mode_value = checksum.get("mode")
        if not isinstance(checksum_mode_value, str) or checksum_mode_value not in {"RAW_BYTES", "CANONICAL_LF_TEXT"}:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].checksum.mode", expected=["RAW_BYTES", "CANONICAL_LF_TEXT"], actual=checksum_mode_value)
        if checksum.get("mode") == "RAW_BYTES":
            raw_size = checksum.get("raw_byte_size")
            if raw_size is None or not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size <= 0:
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].checksum.raw_byte_size", expected="positive int", actual=raw_size)
            _validate_hash(checksum.get("raw_sha256"), field_name=f"files[{idx}].checksum.raw_sha256")
            if checksum.get("canonical_lf_utf8_bytes") is not None or checksum.get("canonical_lf_sha256") is not None:
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].checksum", expected="null canonical fields for RAW_BYTES", actual=checksum)
        else:
            canonical_size = checksum.get("canonical_lf_utf8_bytes")
            if canonical_size is None or not isinstance(canonical_size, int) or isinstance(canonical_size, bool) or canonical_size <= 0:
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].checksum.canonical_lf_utf8_bytes", expected="positive int", actual=canonical_size)
            _validate_hash(checksum.get("canonical_lf_sha256"), field_name=f"files[{idx}].checksum.canonical_lf_sha256")
            if checksum.get("raw_byte_size") is not None or checksum.get("raw_sha256") is not None:
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].checksum", expected="null raw fields for CANONICAL_LF_TEXT", actual=checksum)
        component_ids = row.get("component_ids")
        if not isinstance(component_ids, list):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].component_ids", expected="list", actual=type(component_ids).__name__)
        if len(component_ids) > 64:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].component_ids", expected="<= 64 entries", actual=len(component_ids))
        for cidx, comp_id in enumerate(component_ids):
            if not isinstance(comp_id, str) or not FILE_IDENTIFIER_RE.fullmatch(comp_id):
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].component_ids[{cidx}]", expected="identifier", actual=comp_id)
        if component_ids != sorted(component_ids):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"files[{idx}].component_ids", expected="sorted ascending", actual=component_ids)
        duplicate_component = _duplicate_casefold_count(component_ids)
        if duplicate_component[0] is not None:
            raise StagingDuplicateIdError("staged manifest contains a duplicate or case-colliding identifier", phase="MANIFEST_SCHEMA", exit_code=2, subject=duplicate_component[2] or f"files[{idx}].component_ids", expected="unique", actual=duplicate_component[1])
    for left_index, left_path in enumerate(file_paths):
        for right_index in range(left_index + 1, len(file_paths)):
            right_path = file_paths[right_index]
            if left_path == right_path:
                continue
            if _ancestor_relation(left_path, right_path):
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=left_path, expected="no ancestor path relation", actual=right_path)
    known_file_ids = {row["file_id"] for row in files}
    content_bindings = manifest.get("content_bindings")
    if not isinstance(content_bindings, list) or not (1 <= len(content_bindings) <= 64):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="content_bindings", expected="1..64 entries", actual=len(content_bindings) if isinstance(content_bindings, list) else type(content_bindings).__name__)
    binding_required_keys = {"binding_id", "baseline_kind", "baseline_id", "candidate_file_id"}
    for idx, row in enumerate(content_bindings):
        if not isinstance(row, dict):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}]", expected="mapping", actual=type(row).__name__)
        if set(row) != binding_required_keys:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}]", expected=["binding_id", "baseline_kind", "baseline_id", "candidate_file_id"], actual=sorted(row.keys()))
    # binding_id must be a validated identifier string before it is used to
    # build, sort, or compare the content_bindings[*].binding_id sequence
    # below; see the matching files.file_id guard above for the same
    # mixed-scalar-type TypeError rationale.
    for idx, row in enumerate(content_bindings):
        binding_id = row.get("binding_id")
        if not isinstance(binding_id, str) or not FILE_IDENTIFIER_RE.fullmatch(binding_id):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].binding_id", expected="file_identifier", actual=binding_id)
    duplicate_binding = _duplicate_casefold_count([row["binding_id"] for row in content_bindings])
    if duplicate_binding[0] is not None:
        raise StagingDuplicateIdError("staged manifest contains a duplicate or case-colliding identifier", phase="MANIFEST_SCHEMA", exit_code=2, subject=duplicate_binding[2] or "content_bindings.binding_id", expected="unique", actual=duplicate_binding[1])
    binding_ids = [row["binding_id"] for row in content_bindings]
    if binding_ids != sorted(binding_ids):
        raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="content_bindings", expected="strictly ascending binding_id order", actual=binding_ids)
    seen_casefold_binding_ids = set(); seen_candidate_file_ids = set(); seen_baselines = set()
    for idx, row in enumerate(content_bindings):
        binding_id = row.get("binding_id")
        if binding_id.casefold() in seen_casefold_binding_ids:
            raise StagingDuplicateIdError("staged manifest contains a duplicate or case-colliding identifier", phase="MANIFEST_SCHEMA", exit_code=2, subject=binding_id, expected="unique", actual=2)
        seen_casefold_binding_ids.add(binding_id.casefold())
        # baseline_kind must be type-checked before the closed-enum
        # membership test: a non-string value (e.g. a YAML sequence/mapping)
        # is unhashable and would otherwise raise a raw TypeError out of
        # `not in {...}` instead of failing closed with the typed schema
        # error.
        baseline_kind = row.get("baseline_kind")
        if not isinstance(baseline_kind, str) or baseline_kind not in {"NONE", "DECLARATION_REF", "COMPONENT_CHECKSUM"}:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].baseline_kind", expected=["NONE", "DECLARATION_REF", "COMPONENT_CHECKSUM"], actual=baseline_kind)
        baseline_id = row.get("baseline_id")
        candidate_file_id = row.get("candidate_file_id")
        if baseline_kind == "NONE":
            if baseline_id is not None:
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].baseline_id", expected=None, actual=baseline_id)
            if candidate_file_id is None:
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].candidate_file_id", expected="non-null identifier", actual=candidate_file_id)
            # candidate_file_id must be type-checked here, before it is later
            # tested for `not in known_file_ids` below: a non-string value
            # (e.g. a YAML sequence/mapping) is unhashable and would
            # otherwise raise a raw TypeError out of that membership test
            # instead of failing closed with the typed schema error.
            if not isinstance(candidate_file_id, str):
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].candidate_file_id", expected="non-null identifier", actual=candidate_file_id)
        else:
            if baseline_id is not None and not isinstance(baseline_id, str):
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].baseline_id", expected="string_or_null", actual=baseline_id)
            if candidate_file_id is not None and not isinstance(candidate_file_id, str):
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].candidate_file_id", expected="string_or_null", actual=candidate_file_id)
            if baseline_id is not None:
                if baseline_id in seen_baselines:
                    raise StagingDuplicateIdError("staged manifest contains a duplicate or case-colliding identifier", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].baseline_id", expected="unique baseline target", actual=baseline_id)
                seen_baselines.add(baseline_id)
            if candidate_file_id is not None:
                if candidate_file_id in seen_candidate_file_ids:
                    raise StagingDuplicateIdError("staged manifest contains a duplicate or case-colliding identifier", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].candidate_file_id", expected="unique candidate file", actual=candidate_file_id)
                seen_candidate_file_ids.add(candidate_file_id)
        if candidate_file_id is not None and candidate_file_id not in known_file_ids:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"content_bindings[{idx}].candidate_file_id", expected="known file_id", actual=candidate_file_id)
    projection = manifest.get("component_projection")
    if projection is not None:
        if not isinstance(projection, dict):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="component_projection", expected="mapping or null", actual=type(projection).__name__)
        if set(projection) != {"mode", "components"}:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="component_projection", expected=["mode", "components"], actual=sorted(projection.keys()))
        if projection.get("mode") != "COMPLETE":
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="component_projection.mode", expected="COMPLETE", actual=projection.get("mode"))
        components = projection.get("components")
        if not isinstance(components, list):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="component_projection.components", expected="list", actual=type(components).__name__)
        if len(components) > 256:
            raise StagingManifestLimitError("staged manifest exceeds a closed size or structure limit", phase="MANIFEST_READ", exit_code=2, subject="component_projection.components", expected="<= 256 entries", actual=len(components))
        seen = set(); seen_casefold = set();
        for idx, comp in enumerate(components):
            if not isinstance(comp, dict):
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"component_projection.components[{idx}]", expected="mapping", actual=type(comp).__name__)
            if set(comp) != {"component_id", "display_name", "source_role", "version_or_snapshot", "licence_status", "declaration_locator"}:
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"component_projection.components[{idx}]", expected=["component_id", "display_name", "source_role", "version_or_snapshot", "licence_status", "declaration_locator"], actual=sorted(comp.keys()))
            cid = comp.get("component_id")
            if not isinstance(cid, str) or not FILE_IDENTIFIER_RE.fullmatch(cid):
                raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"component_projection.components[{idx}].component_id", expected="identifier", actual=cid)
            if cid.casefold() in seen_casefold:
                raise StagingDuplicateIdError("staged manifest contains a duplicate or case-colliding identifier", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"component_projection.components[{idx}].component_id", expected="unique component_id", actual=cid)
            seen_casefold.add(cid.casefold())
            for field in ("display_name", "source_role", "version_or_snapshot", "licence_status", "declaration_locator"):
                if not isinstance(comp.get(field), str) or not comp[field].strip():
                    raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject=f"component_projection.components[{idx}].{field}", expected="non-empty string", actual=comp.get(field))
        if sorted(components, key=lambda x: x["component_id"]) != components:
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="component_projection.components", expected="ascending component_id order", actual=components)

    return manifest


def _manifest_is_valid(manifest: dict[str, Any]) -> bool:
    try:
        _validate_manifest_shape(manifest)
    except StagedSnapshotError:
        return False
    return True


def _validate_unlisted_tree(stage_root: Path, manifest: dict[str, Any]) -> None:
    listed = {entry["path"]: entry for entry in manifest["files"]}
    allowed_entries = {"manifest.yaml"}
    allowed_entries.update(listed.keys())
    on_disk: set[str] = set()
    seen_dirs: list[Path] = []

    # Explicit deterministic stack, never Python call-stack recursion: an
    # adversarial or pathologically deep/wide staged tree must fail closed
    # on its first offending entry (a path-segment or directory-count limit
    # breach) instead of ever exhausting the interpreter recursion limit.
    # Every directory's entries are discovered with one no-follow lstat
    # (entry.stat(follow_symlinks=False)) and sorted by path before any of
    # them are pushed, so traversal order — and therefore the first
    # reported offender — is stable and platform-independent. Both limits
    # are enforced the instant an offending directory is discovered, before
    # it is ever pushed for its own scan, so its contents are never
    # enumerated and the traversal never descends past the offender.
    pending: list[Path] = [stage_root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as it:
                raw_entries = sorted(it, key=lambda entry: entry.path)
        except OSError as exc:
            raise StagingTreeMismatchError("staging tree has a missing, unknown, or unneeded entry", phase="INVENTORY", exit_code=2, subject=_canonical_path_subject(directory, root=stage_root)) from exc
        children: list[Path] = []
        for entry in raw_entries:
            item_path = Path(entry.path)
            if entry.is_symlink() or _is_windows_reparse(item_path):
                raise StagingEntryTypeError("staging tree contains a link, reparse point, special entry, or listed directory", phase="INVENTORY", exit_code=2, subject=_canonical_path_subject(item_path, root=stage_root))
            try:
                stat_result = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise StagingFileReadError("staged content could not be read as a bounded local regular file", phase="CONTENT", exit_code=2, subject=_canonical_path_subject(item_path, root=stage_root)) from exc
            if stat.S_ISDIR(stat_result.st_mode):
                if item_path.name == "manifest.yaml":
                    raise StagingTreeMismatchError("staging tree has a missing, unknown, or unneeded entry", phase="INVENTORY", exit_code=2, subject="manifest.yaml")
                segment_count = len(item_path.relative_to(stage_root).parts)
                if segment_count > 8:
                    raise StagingLimitError("staging tree exceeds a closed file, directory, depth, or byte limit", phase="INVENTORY", exit_code=2, subject=_canonical_path_subject(item_path, root=stage_root), expected="<= 8 path segments", actual=segment_count)
                seen_dirs.append(item_path)
                if len(seen_dirs) > 64:
                    raise StagingLimitError("staging tree exceeds a closed file, directory, depth, or byte limit", phase="INVENTORY", exit_code=2, subject=_canonical_path_subject(item_path, root=stage_root), expected="<= 64 directories", actual=len(seen_dirs))
                children.append(item_path)
            elif stat.S_ISREG(stat_result.st_mode):
                rel = _canonical_path_subject(item_path, root=stage_root)
                if any(part.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", part, re.IGNORECASE) for part in rel.split("/")):
                    raise StagingPathError("a staged path is unsafe or escapes the designated root", phase="INVENTORY", exit_code=2, subject=rel)
                on_disk.add(rel)
            else:
                raise StagingEntryTypeError("staging tree contains a link, reparse point, special entry, or listed directory", phase="INVENTORY", exit_code=2, subject=_canonical_path_subject(item_path, root=stage_root))
        # Depth-first, sorted-ascending traversal: push in reverse so the
        # smallest path is popped (and therefore visited) next, matching
        # the pre-order walk this iterative form replaces.
        pending.extend(reversed(children))

    for rel in listed:
        if rel not in on_disk:
            raise StagingTreeMismatchError("staging tree has a missing, unknown, or unneeded entry", phase="INVENTORY", exit_code=2, subject=rel)
    manifest_path = stage_root / "manifest.yaml"
    if not manifest_path.exists() or not manifest_path.is_file() or manifest_path.is_symlink():
        raise StagingManifestMissingError("staging root does not contain manifest.yaml", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml")
    if not manifest_path.is_file() or stat.S_ISDIR(os.lstat(manifest_path).st_mode):
        raise StagingManifestTypeError("manifest.yaml is a link, reparse point, directory, or special entry", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml")
    all_rel_paths = {"manifest.yaml"}
    all_rel_paths.update(on_disk)
    if not all_rel_paths.issubset(allowed_entries):
        extra = sorted(all_rel_paths - allowed_entries)
        raise StagingTreeMismatchError("staging tree has a missing, unknown, or unneeded entry", phase="INVENTORY", exit_code=2, subject=extra[0])
    empty_dirs = []
    for raw_dir in sorted(seen_dirs):
        if not any(child for child in raw_dir.iterdir()):
            empty_dirs.append(_canonical_path_subject(raw_dir, root=stage_root))
    if empty_dirs:
        raise StagingTreeMismatchError("staging tree has a missing, unknown, or unneeded entry", phase="INVENTORY", exit_code=2, subject=empty_dirs[0])


def _snapshot_stage_tree(stage_root: Path) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"entries": []}
    file_records: list[dict[str, Any]] = []
    for root, dirs, files in os.walk(stage_root, topdown=True, followlinks=False):
        root_path = Path(root)
        dirs[:] = sorted(dirs)
        files = sorted(files)
        for name in files:
            path = root_path / name
            rel = _canonical_path_subject(path, root=stage_root)
            try:
                st = os.lstat(path)
            except OSError as exc:
                raise StagingFileReadError("staged content could not be read as a bounded local regular file", phase="CONTENT", exit_code=2, subject=rel) from exc
            # Classify strictly from the lstat result obtained above: reject
            # a symlink, a Windows reparse point/junction, and any
            # non-regular entry (FIFO, socket, device, ...) here, before any
            # read/open of this entry happens. A dangling or externally-
            # resolvable symlink must never be followed, and a blocking
            # special file must never be opened.
            if stat.S_ISLNK(st.st_mode) or _is_windows_reparse(path) or not stat.S_ISREG(st.st_mode):
                raise StagingEntryTypeError("staging tree contains a link, reparse point, special entry, or listed directory", phase="INVENTORY", exit_code=2, subject=rel)
            file_records.append({"path": rel, "full": path, "stat": st})
        for name in dirs:
            path = root_path / name
            rel = _canonical_path_subject(path, root=stage_root)
            try:
                st = os.lstat(path)
            except OSError as exc:
                raise StagingFileReadError("staged content could not be read as a bounded local regular file", phase="CONTENT", exit_code=2, subject=rel) from exc
            if stat.S_ISLNK(st.st_mode) or _is_windows_reparse(path) or not stat.S_ISDIR(st.st_mode):
                raise StagingEntryTypeError("staging tree contains a link, reparse point, special entry, or listed directory", phase="INVENTORY", exit_code=2, subject=rel)
            snapshot["entries"].append({
                "path": rel,
                "kind": "directory",
                "st_dev": st.st_dev,
                "st_ino": st.st_ino,
                "st_size": st.st_size,
                "st_mtime_ns": st.st_mtime_ns,
                "st_ctime_ns": st.st_ctime_ns,
            })
    # Pre-read size limits are enforced deterministically in canonical
    # sorted path order, over every regular file in the tree (whether or
    # not it is listed in the manifest) except manifest.yaml, before any
    # staged file content is read below. The per-file and cumulative
    # limits both fail closed on the first offending path in that order,
    # and that offending file is never opened for reading.
    total_bytes = 0
    for record in sorted(file_records, key=lambda item: item["path"]):
        rel = record["path"]
        if rel == "manifest.yaml":
            continue
        size = record["stat"].st_size
        if size > 16777216:
            raise StagingLimitError("staging tree exceeds a closed file, directory, depth, or byte limit", phase="INVENTORY", exit_code=2, subject=rel, expected="<= 16777216 bytes per file", actual=size)
        total_bytes += size
        if total_bytes > 67108864:
            raise StagingLimitError("staging tree exceeds a closed file, directory, depth, or byte limit", phase="INVENTORY", exit_code=2, subject=rel, expected="<= 67108864 total bytes", actual=total_bytes)
    for record in file_records:
        path = record["full"]
        st = record["stat"]
        rel = record["path"]
        # Mirrors `_read_file_observations`: an unreadable staged file
        # (e.g. a permission error) must fail closed as the typed
        # STAGING_FILE_READ_FAILED/CONTENT/exit-2 error here too, never
        # escape as a raw OSError into the closed INTERNAL_ERROR/exit-70
        # boundary in `verify_stage`.
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise StagingFileReadError("staged content could not be read as a bounded local regular file", phase="CONTENT", exit_code=2, subject=rel) from exc
        snapshot["entries"].append({
            "path": rel,
            "kind": "file",
            "st_dev": st.st_dev,
            "st_ino": st.st_ino,
            "st_size": st.st_size,
            "st_mtime_ns": st.st_mtime_ns,
            "st_ctime_ns": st.st_ctime_ns,
            "bytes_sha256": _sha256_hex(raw),
        })
    snapshot["entries"].sort(key=lambda entry: entry["path"])
    manifest_path = stage_root / "manifest.yaml"
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise StagingManifestReadError("staged manifest could not be read as a bounded local regular file", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml") from exc
    snapshot["manifest_bytes_sha256"] = _sha256_hex(manifest_bytes)
    return snapshot


def _snapshot_baseline_files(source_record: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"entries": []}
    for binding in source_record.get("declaration_refs", []):
        path_value = binding.get("path")
        if not isinstance(path_value, str):
            continue
        path = repo_root / path_value.replace("\\", "/")
        try:
            st = os.lstat(path)
            raw = path.read_bytes()
        except OSError as exc:
            raise BaselineDeclarationInvalidError("current V2-S1 declaration precondition is invalid or drifted", phase="BASELINE", exit_code=6, subject=path_value) from exc
        snapshot["entries"].append({
            "path": path_value,
            "kind": "file",
            "st_dev": st.st_dev,
            "st_ino": st.st_ino,
            "st_size": st.st_size,
            "st_mtime_ns": st.st_mtime_ns,
            "st_ctime_ns": st.st_ctime_ns,
            "sha256": _sha256_hex(raw),
        })
    registry_path = repo_root / CANONICAL_REGISTRY_REL
    try:
        reg_bytes = registry_path.read_bytes()
        reg_st = os.lstat(registry_path)
    except OSError as exc:
        raise BaselineRegistryInvalidError("current V2-S1 registry is invalid", phase="BASELINE", exit_code=6, subject=CANONICAL_REGISTRY_REL) from exc
    snapshot["registry"] = {
        "path": CANONICAL_REGISTRY_REL,
        "kind": "file",
        "st_dev": reg_st.st_dev,
        "st_ino": reg_st.st_ino,
        "st_size": reg_st.st_size,
        "st_mtime_ns": reg_st.st_mtime_ns,
        "st_ctime_ns": reg_st.st_ctime_ns,
        "sha256": _sha256_hex(reg_bytes),
    }
    return snapshot


def _file_is_valid_for_checksum(file_row: dict[str, Any], raw_bytes: bytes) -> tuple[bool, str | None]:
    checksum = file_row["checksum"]
    if checksum["mode"] == "RAW_BYTES":
        if len(raw_bytes) != checksum["raw_byte_size"]:
            return False, "SIZE"
        if _sha256_hex(raw_bytes) != checksum["raw_sha256"]:
            return False, "CHECKSUM"
        return True, None
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise StagingTextEncodingError("canonical-LF staged content is not valid strict UTF-8", phase="CONTENT", exit_code=2, subject=file_row["path"])
    canonical = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    if len(canonical) != checksum["canonical_lf_utf8_bytes"]:
        return False, "SIZE"
    if _sha256_hex(canonical) != checksum["canonical_lf_sha256"]:
        return False, "CHECKSUM"
    return True, None


def _build_source_fact(baseline: dict[str, Any], candidate: dict[str, Any], *, fact_path: str, baseline_pointer: str, candidate_pointer: str, diff_kind: str, fact_kind: str, subject_type: str, subject_id: str, baseline_origin: str, candidate_origin: str) -> dict[str, Any]:
    before_present = _lookup_path(baseline, baseline_pointer) is not _MISSING
    after_present = _lookup_path(candidate, candidate_pointer) is not _MISSING
    before_value = _lookup_path(baseline, baseline_pointer) if before_present else None
    after_value = _lookup_path(candidate, candidate_pointer) if after_present else None
    if before_present and after_present and _canonical_json_bytes(before_value) == _canonical_json_bytes(after_value):
        classification = "UNCHANGED"
    elif not before_present and after_present:
        classification = "ADDED"
    elif before_present and not after_present:
        classification = "REMOVED"
    else:
        classification = "CHANGED"
    return {
        "difference_kind": diff_kind,
        "fact_kind": fact_kind,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "fact_path": fact_path,
        "classification": classification,
        "before": {"present": before_present, "value": None if not before_present else before_value},
        "after": {"present": after_present, "value": None if not after_present else after_value},
        "provenance": {"baseline_origin": baseline_origin, "candidate_origin": candidate_origin},
    }


def _lookup_path(mapping: dict[str, Any], path: str) -> Any:
    if path == "":
        return mapping
    current: Any = mapping
    for part in path.strip("/").split("/"):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


_MISSING = object()


def _compare_source_facts(source_record: dict[str, Any], candidate: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    projections = [
        ("/identity/display_name", "display_name", "identity/display_name", "METADATA", "IDENTITY", "SOURCE"),
        ("/identity/record_kind", "record_kind", "identity/record_kind", "METADATA", "IDENTITY", "SOURCE"),
        ("/identity/owner", "owner", "identity/owner", "METADATA", "METADATA", "SOURCE"),
        ("/identity/authoritative_locator", "authoritative_locator", "identity/authoritative_locator", "DECLARATION", "IDENTITY", "SOURCE"),
        ("/release/version_or_snapshot", "release/version_or_snapshot", "release/version_or_snapshot", "METADATA", "VERSION", "SOURCE"),
        ("/release/release_date", "release/release_date", "release/release_date", "METADATA", "VERSION", "SOURCE"),
        ("/release/retrieved_at", "release/retrieved_at", "release/retrieved_at", "METADATA", "METADATA", "SOURCE"),
        ("/release/content_pin_status", "release/content_pin_status", "release/content_pin_status", "METADATA", "CHECKSUM", "SOURCE"),
        ("/licence/status", "licence/status", "licence/status", "METADATA", "METADATA", "SOURCE"),
        ("/licence/identifier_or_family", "licence/identifier_or_family", "licence/identifier_or_family", "METADATA", "METADATA", "SOURCE"),
        ("/licence/terms_locator", "licence/terms_locator", "licence/terms_locator", "METADATA", "METADATA", "SOURCE"),
        ("/licence/permitted_use", "licence/permitted_use", "licence/permitted_use", "METADATA", "METADATA", "SOURCE"),
        ("/licence/redistribution", "licence/redistribution", "licence/redistribution", "METADATA", "METADATA", "SOURCE"),
        ("/licence/cloud_egress", "licence/cloud_egress", "licence/cloud_egress", "METADATA", "METADATA", "SOURCE"),
        ("/licence/verification_basis", "licence/verification_basis", "licence/verification_basis", "METADATA", "METADATA", "SOURCE"),
        ("/acquisition/method", "acquisition/method", "acquisition/method", "METADATA", "METADATA", "SOURCE"),
        ("/acquisition/operator_contract", "acquisition/operator_contract", "acquisition/operator_contract", "METADATA", "METADATA", "SOURCE"),
        ("/acquisition/writes_outside_repository", "acquisition/writes_outside_repository", "acquisition/writes_outside_repository", "METADATA", "METADATA", "SOURCE"),
    ]
    for fact_path, baseline_pointer, candidate_pointer, diff_kind, fact_kind, subject_type in projections:
        baseline_value = _lookup_path(source_record, baseline_pointer)
        candidate_value = _lookup_path(candidate, candidate_pointer)
        before_present = baseline_value is not _MISSING
        after_present = candidate_value is not _MISSING
        before_value = None if not before_present else baseline_value
        after_value = None if not after_present else candidate_value
        if before_present and after_present and _canonical_json_bytes(before_value) == _canonical_json_bytes(after_value):
            classification = "UNCHANGED"
        elif not before_present and after_present:
            classification = "ADDED"
        elif before_present and not after_present:
            classification = "REMOVED"
        else:
            classification = "CHANGED"
        facts.append(
            {
                "difference_kind": diff_kind,
                "fact_kind": fact_kind,
                "subject_type": subject_type,
                "subject_id": source_id,
                "fact_path": fact_path,
                "classification": classification,
                "before": {"present": before_present, "value": before_value},
                "after": {"present": after_present, "value": after_value},
                "provenance": {"baseline_origin": "REGISTRY_SOURCE_RECORD", "candidate_origin": "MANIFEST_CANDIDATE"},
            }
        )
    return facts


def _build_content_binding_facts(manifest: dict[str, Any], source_record: dict[str, Any], file_observations: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    binding_rows = manifest["content_bindings"]
    facts: list[dict[str, Any]] = []
    for row in binding_rows:
        binding_id = row["binding_id"]
        baseline_kind = row["baseline_kind"]
        baseline_id = row["baseline_id"]
        candidate_file_id = row["candidate_file_id"]
        subject_id = candidate_file_id if candidate_file_id is not None else baseline_id if baseline_id is not None else binding_id
        if baseline_kind == "NONE":
            after = file_observations.get(candidate_file_id, {})
            diff_kind = "DECLARATION" if after.get("role") == "CANDIDATE_DECLARATION" else "CONTENT"
            after_value = {"file_id": after.get("file_id"), "role": after.get("role"), "media_type": after.get("media_type"), "checksum_mode": after.get("checksum_mode"), "content_byte_size": after.get("content_byte_size"), "content_sha256": after.get("content_sha256")} if after else None
            facts.append(_make_fact(diff_kind, "MANIFEST", "FILE", subject_id, f"/content-bindings/{binding_id}", {"present": False, "value": None}, {"present": True, "value": after_value}, "ABSENT", "STAGED_FILE_OBSERVATION"))
            continue
        if baseline_kind == "DECLARATION_REF":
            baseline_hash = None
            for ref in source_record.get("declaration_refs", []):
                if ref.get("path") == baseline_id:
                    baseline_hash = ref.get("canonical_lf_sha256")
                    break
            if candidate_file_id is None:
                before_value = {"baseline_kind": "DECLARATION_REF", "baseline_id": baseline_id, "checksum_mode": "CANONICAL_LF_TEXT", "content_sha256": baseline_hash}
                facts.append(_make_fact("DECLARATION", "MANIFEST", "DECLARATION", baseline_id or binding_id, f"/content-bindings/{binding_id}", {"present": True, "value": before_value}, {"present": False, "value": None}, "REGISTRY_DECLARATION_REF", "ABSENT"))
            else:
                candidate_ob = file_observations[candidate_file_id]
                before_value = {"baseline_kind": "DECLARATION_REF", "baseline_id": baseline_id, "checksum_mode": "CANONICAL_LF_TEXT", "content_sha256": baseline_hash}
                after_value = {"candidate_file_id": candidate_file_id, "checksum_mode": candidate_ob["checksum_mode"], "content_sha256": candidate_ob["content_sha256"], "content_byte_size": candidate_ob["content_byte_size"]}
                facts.append(_make_fact("DECLARATION", "CHECKSUM", "DECLARATION", baseline_id or binding_id, f"/content-bindings/{binding_id}/sha256", {"present": True, "value": baseline_hash}, {"present": True, "value": candidate_ob["content_sha256"]}, "REGISTRY_DECLARATION_REF", "STAGED_FILE_OBSERVATION"))
        elif baseline_kind == "COMPONENT_CHECKSUM":
            component_hash = None
            for component in (source_record.get("components") or []):
                if component.get("component_id") == baseline_id:
                    component_hash = component.get("version_or_snapshot")
                    break
            if candidate_file_id is None:
                before_value = {"baseline_kind": "COMPONENT_CHECKSUM", "baseline_id": baseline_id, "checksum_mode": "RAW_BYTES", "content_sha256": component_hash}
                facts.append(_make_fact("CONTENT", "MANIFEST", "COMPONENT", baseline_id or binding_id, f"/content-bindings/{binding_id}", {"present": True, "value": before_value}, {"present": False, "value": None}, "REGISTRY_COMPONENT", "ABSENT"))
            else:
                candidate_ob = file_observations[candidate_file_id]
                facts.append(_make_fact("CONTENT", "CHECKSUM", "COMPONENT", baseline_id or binding_id, f"/content-bindings/{binding_id}/sha256", {"present": True, "value": component_hash}, {"present": True, "value": candidate_ob["content_sha256"]}, "REGISTRY_COMPONENT", "STAGED_FILE_OBSERVATION"))
    return facts


def _make_fact(diff_kind: str, fact_kind: str, subject_type: str, subject_id: str, fact_path: str, before: dict[str, Any], after: dict[str, Any], baseline_origin: str, candidate_origin: str) -> dict[str, Any]:
    before_present = bool(before.get("present"))
    after_present = bool(after.get("present"))
    before_value = before.get("value")
    after_value = after.get("value")
    if before_present and after_present and _canonical_json_bytes(before_value) == _canonical_json_bytes(after_value):
        classification = "UNCHANGED"
    elif not before_present and after_present:
        classification = "ADDED"
    elif before_present and not after_present:
        classification = "REMOVED"
    else:
        classification = "CHANGED"
    return {
        "difference_kind": diff_kind,
        "fact_kind": fact_kind,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "fact_path": fact_path,
        "classification": classification,
        "before": {"present": before_present, "value": None if not before_present else before_value},
        "after": {"present": after_present, "value": None if not after_present else after_value},
        "provenance": {"baseline_origin": baseline_origin, "candidate_origin": candidate_origin},
    }


def _component_projection_facts(source_record: dict[str, Any], candidate_projection: dict[str, Any] | None) -> list[dict[str, Any]]:
    if candidate_projection is None:
        return []
    if candidate_projection.get("mode") != "COMPLETE":
        return []
    baseline_map = {item["component_id"]: item for item in (source_record.get("components") or [])}
    candidate_map = {item["component_id"]: item for item in candidate_projection.get("components", [])}
    facts: list[dict[str, Any]] = []
    all_ids = sorted(set(baseline_map) | set(candidate_map), key=lambda x: x)
    for cid in all_ids:
        before = baseline_map.get(cid)
        after = candidate_map.get(cid)
        if before is None:
            value = {key: after[key] for key in ["display_name", "source_role", "version_or_snapshot", "licence_status", "declaration_locator"] if key in after}
            facts.append(_make_fact("METADATA", "COMPONENT", "COMPONENT", cid, f"/components/{cid.replace('~','~0').replace('/','~1')}", {"present": False, "value": None}, {"present": True, "value": value}, "ABSENT", "MANIFEST_COMPONENT"))
            continue
        if after is None:
            value = {key: before[key] for key in ["display_name", "source_role", "version_or_snapshot", "licence_status", "declaration_locator"] if key in before}
            facts.append(_make_fact("METADATA", "COMPONENT", "COMPONENT", cid, f"/components/{cid.replace('~','~0').replace('/','~1')}", {"present": True, "value": value}, {"present": False, "value": None}, "REGISTRY_COMPONENT", "ABSENT"))
            continue
        for field in ["display_name", "source_role", "version_or_snapshot", "licence_status"]:
            facts.append(_make_fact("METADATA" if field != "version_or_snapshot" else "METADATA", "COMPONENT" if field != "version_or_snapshot" else "VERSION", "COMPONENT", cid, f"/components/{cid.replace('~','~0').replace('/','~1')}/{field}", {"present": True, "value": before.get(field)}, {"present": True, "value": after.get(field)}, "REGISTRY_COMPONENT", "MANIFEST_COMPONENT"))
        facts.append(_make_fact("DECLARATION", "COMPONENT", "COMPONENT", cid, f"/components/{cid.replace('~','~0').replace('/','~1')}/declaration_locator", {"present": True, "value": before.get("declaration_locator")}, {"present": True, "value": after.get("declaration_locator")}, "REGISTRY_COMPONENT", "MANIFEST_COMPONENT"))
    return facts


def _build_diff_artifact(manifest: dict[str, Any], source_record: dict[str, Any], file_observations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_id = manifest["source_binding"]["source_id"]
    facts = _compare_source_facts(source_record, manifest["candidate"], source_id)
    facts.extend(_build_content_binding_facts(manifest, source_record, file_observations))
    facts.extend(_component_projection_facts(source_record, manifest.get("component_projection")))
    facts.sort(key=lambda fact: (
        DIFF_KIND_ORDER.get(fact["difference_kind"], 99),
        FACT_KIND_ORDER.get(fact["fact_kind"], 99),
        SUBJECT_TYPE_ORDER.get(fact["subject_type"], 99),
        str(fact["subject_id"]),
        fact["fact_path"],
    ))
    summary = {
        "total_facts": len(facts),
        "classifications": {"ADDED": 0, "REMOVED": 0, "CHANGED": 0, "UNCHANGED": 0},
        "difference_kinds": {"CONTENT": 0, "METADATA": 0, "DECLARATION": 0},
        "fact_kinds": {"IDENTITY": 0, "VERSION": 0, "CHECKSUM": 0, "MANIFEST": 0, "COMPONENT": 0, "METADATA": 0},
    }
    for fact in facts:
        summary["classifications"][fact["classification"]] += 1
        summary["difference_kinds"][fact["difference_kind"]] += 1
        summary["fact_kinds"][fact["fact_kind"]] += 1
    files = []
    total_bound = 0
    for file_id in sorted(file_observations):
        obs = file_observations[file_id]
        files.append({
            "file_id": file_id,
            "path": obs["path"],
            "role": obs["role"],
            "media_type": obs["media_type"],
            "checksum_mode": obs["checksum_mode"],
            "content_byte_size": obs["content_byte_size"],
            "content_sha256": obs["content_sha256"],
            "component_ids": obs["component_ids"],
        })
        total_bound += obs["content_byte_size"]
    input_tree_hash = _sha256_hex(_canonical_json_bytes(files))
    payload = {
        "schema": DIFF_SCHEMA_ID,
        "artifact_content_hash": None,
        "hash_basis": DIFF_HASH_BASIS,
        "manifest_content_hash": manifest["manifest_content_hash"],
        "observed_at": manifest["observed_at"],
        "source_binding": {
            "source_id": source_id,
            "registry_content_hash": manifest["source_binding"]["registry_content_hash"],
            "source_record_content_hash": _sha256_hex(_canonical_json_bytes(source_record)),
            "declaration_refs": manifest["source_binding"]["declaration_refs"],
        },
        "candidate_snapshot_id": manifest["candidate"]["snapshot_id"],
        "input_tree_content_hash": input_tree_hash,
        "component_projection_status": "COMPLETE" if manifest.get("component_projection") is not None else "NOT_PROVIDED",
        "stage_outcome": "OBSERVED_NO_DIFFERENCE" if all(fact["classification"] == "UNCHANGED" for fact in facts) else "OBSERVED_DIFFERENCE",
        "summary": summary,
        "facts": facts,
        "validation_ceiling": STAGED_SNAPSHOT_VALIDATION_CEILING,
    }
    payload["artifact_content_hash"] = _artifact_hash_for(payload)
    return payload


def _build_verification_artifact(manifest: dict[str, Any], source_record: dict[str, Any], file_observations: dict[str, dict[str, Any]], diff_payload: dict[str, Any]) -> dict[str, Any]:
    files = []
    total_bound = 0
    for file_id in sorted(file_observations):
        obs = file_observations[file_id]
        files.append({
            "file_id": file_id,
            "path": obs["path"],
            "role": obs["role"],
            "media_type": obs["media_type"],
            "checksum_mode": obs["checksum_mode"],
            "content_byte_size": obs["content_byte_size"],
            "content_sha256": obs["content_sha256"],
            "component_ids": obs["component_ids"],
        })
        total_bound += obs["content_byte_size"]
    input_tree = {
        "hash_basis": INPUT_TREE_HASH_BASIS,
        "input_tree_content_hash": _sha256_hex(_canonical_json_bytes(files)),
        "files": files,
        "total_bound_content_bytes": total_bound,
    }
    payload = {
        "schema": VERIFICATION_SCHEMA_ID,
        "artifact_content_hash": None,
        "hash_basis": VERIFICATION_HASH_BASIS,
        "manifest_content_hash": manifest["manifest_content_hash"],
        "observed_at": manifest["observed_at"],
        "source_binding": {
            "source_id": manifest["source_binding"]["source_id"],
            "registry_content_hash": manifest["source_binding"]["registry_content_hash"],
            "source_record_content_hash": _sha256_hex(_canonical_json_bytes(source_record)),
            "declaration_refs": manifest["source_binding"]["declaration_refs"],
        },
        "candidate_snapshot_id": manifest["candidate"]["snapshot_id"],
        "component_projection_status": "COMPLETE" if manifest.get("component_projection") is not None else "NOT_PROVIDED",
        "input_tree": input_tree,
        "checks": {
            "manifest_schema_valid": True,
            "manifest_hash_match": True,
            "baseline_registry_valid": True,
            "baseline_hash_match": True,
            "declaration_bindings_match": True,
            "baseline_immutable_during_run": True,
            "inventory_complete": True,
            "content_bindings_valid": True,
            "component_projection_valid": True,
            "file_checksums_match": True,
            "input_immutable_during_run": True,
            "inputs_not_mutated_by_command": True,
        },
        "stage_outcome": diff_payload["stage_outcome"],
        "diff_artifact_content_hash": diff_payload["artifact_content_hash"],
        "validation_ceiling": STAGED_SNAPSHOT_VALIDATION_CEILING,
    }
    payload["artifact_content_hash"] = _artifact_hash_for(payload)
    return payload


def _build_cli_result(*, report_error: dict[str, Any] | None, run_status: str, input_validity: str, stage_outcome: str | None, source_id: str | None = None, registry_hash: str | None = None, manifest_hash: str | None = None, verification_ref: dict[str, Any] | None = None, diff_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "schema": CLI_SCHEMA_ID,
        "command": "verify-stage",
        "run_status": run_status,
        "input_validity": input_validity,
        "stage_outcome": stage_outcome,
        "source_id": source_id,
        "registry_content_hash": registry_hash,
        "manifest_content_hash": manifest_hash,
        "verification_artifact": verification_ref,
        "diff_artifact": diff_ref,
        "error": report_error,
        "validation_ceiling": STAGED_SNAPSHOT_VALIDATION_CEILING,
    }
    return result


def _serialize_json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"


def _closed_internal_error_result_dict() -> dict[str, Any]:
    """Fixed-literal CLI result payload for the terminal INTERNAL_ERROR
    envelope. Every field is a constant string or None, so serializing this
    payload can never itself fail.
    """
    return {
        "schema": CLI_SCHEMA_ID,
        "command": "verify-stage",
        "run_status": "FAILED",
        "input_validity": "NOT_EVALUATED",
        "stage_outcome": None,
        "source_id": None,
        "registry_content_hash": None,
        "manifest_content_hash": None,
        "verification_artifact": None,
        "diff_artifact": None,
        "error": _cli_error_payload("INTERNAL_ERROR", "INTERNAL", "verify-stage failed closed because of an unexpected internal error", type_name="InternalStageError"),
        "validation_ceiling": STAGED_SNAPSHOT_VALIDATION_CEILING,
    }


def _emit_cli_result(payload: dict[str, Any], exit_code: int) -> int:
    """Terminal stdout safety boundary for the verify-stage CLI result.

    Every upstream error path already carries a JSON-safe detail envelope
    (see _json_safe_detail), so this call is expected to always succeed. It
    exists purely as a last-resort guard: if serialization still fails for an
    unforeseen reason, this degrades to the fixed, always-serializable
    INTERNAL_ERROR envelope instead of letting the failure escape as an
    untrapped exit 1 traceback. The fallback is built from constant literals
    only, is written directly, and never recursively retries through this
    function or _serialize_json.
    """
    try:
        encoded = _serialize_json(payload).encode("utf-8")
    except Exception:
        fallback = _closed_internal_error_result_dict()
        fallback_line = json.dumps(fallback, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
        sys.stdout.buffer.write(fallback_line.encode("utf-8"))
        return 70
    sys.stdout.buffer.write(encoded)
    return exit_code


def _validate_manifest_hash(manifest: dict[str, Any]) -> None:
    expected = manifest.get("manifest_content_hash")
    actual = _manifest_hash_for(manifest)
    if expected != actual:
        raise StagingManifestHashMismatch("staged manifest content hash does not match its canonical mapping", phase="MANIFEST_HASH", exit_code=2, subject="manifest_content_hash", expected=expected, actual=actual)


def _normalise_manifest_files(manifest: dict[str, Any]) -> None:
    path_values = [row["path"] for row in manifest["files"]]
    duplicate_path_key, duplicate_path_count, duplicate_path_subject = _duplicate_casefold_count(path_values)
    if duplicate_path_key is not None:
        raise StagingDuplicatePathError("staged manifest contains a duplicate or case-colliding file path", phase="MANIFEST_SCHEMA", exit_code=2, subject=duplicate_path_subject or "files.path", expected="unique", actual=duplicate_path_count)
    ids = [row["file_id"] for row in manifest["files"]]
    duplicate_id_key, duplicate_id_count, duplicate_id_subject = _duplicate_casefold_count(ids)
    if duplicate_id_key is not None:
        raise StagingDuplicateIdError("staged manifest contains a duplicate or case-colliding identifier", phase="MANIFEST_SCHEMA", exit_code=2, subject=duplicate_id_subject or "files.file_id", expected="unique", actual=duplicate_id_count)
    if any(path == "manifest.yaml" for path in path_values):
        raise StagingDuplicatePathError("staged manifest contains a duplicate or case-colliding file path", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml", expected="unique", actual=1)


def _examine_staging_tree(stage_root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    def scan(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda p: p.name):
            rel = _canonical_path_subject(child, root=stage_root)
            try:
                st = os.lstat(child)
            except OSError as exc:
                raise StagingFileReadError("staged content could not be read as a bounded local regular file", phase="CONTENT", exit_code=2, subject=rel) from exc
            if stat.S_ISLNK(st.st_mode) or _is_windows_reparse(child):
                raise StagingEntryTypeError("staging tree contains a link, reparse point, special entry, or listed directory", phase="INVENTORY", exit_code=2, subject=rel)
            if stat.S_ISDIR(st.st_mode):
                if rel == "manifest.yaml":
                    raise StagingTreeMismatchError("staging tree has a missing, unknown, or unneeded entry", phase="INVENTORY", exit_code=2, subject=rel)
                scan(child)
            elif stat.S_ISREG(st.st_mode):
                entries[rel] = {"path": rel, "kind": "file", "st_size": st.st_size}
            else:
                raise StagingEntryTypeError("staging tree contains a link, reparse point, special entry, or listed directory", phase="INVENTORY", exit_code=2, subject=rel)
    scan(stage_root)
    manifest_file = stage_root / "manifest.yaml"
    if not manifest_file.exists() or not manifest_file.is_file():
        raise StagingManifestMissingError("staging root does not contain manifest.yaml", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml")
    entries["manifest.yaml"] = {"path": "manifest.yaml", "kind": "file"}
    if set(entries) - {"manifest.yaml", *[row["path"] for row in manifest["files"]]}:
        extra = sorted(set(entries) - {"manifest.yaml", *[row["path"] for row in manifest["files"]]})
        raise StagingTreeMismatchError("staging tree has a missing, unknown, or unneeded entry", phase="INVENTORY", exit_code=2, subject=extra[0])
    missing = [row["path"] for row in manifest["files"] if row["path"] not in entries]
    if missing:
        raise StagingTreeMismatchError("staging tree has a missing, unknown, or unneeded entry", phase="INVENTORY", exit_code=2, subject=missing[0])
    return entries


def _parse_manifest_from_stage(stage_root: Path) -> dict[str, Any]:
    manifest_path = stage_root / "manifest.yaml"
    if not manifest_path.exists():
        raise StagingManifestMissingError("staging root does not contain manifest.yaml", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml")
    try:
        st = os.lstat(manifest_path)
    except OSError as exc:
        raise StagingManifestReadError("staged manifest could not be read as a bounded local regular file", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml") from exc
    if stat.S_ISLNK(st.st_mode) or stat.S_ISDIR(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise StagingManifestTypeError("manifest.yaml is a link, reparse point, directory, or special entry", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml")
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise StagingManifestReadError("staged manifest could not be read as a bounded local regular file", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml") from exc
    manifest = _load_manifest_yaml(raw)
    _validate_manifest_shape(manifest)
    _normalise_manifest_files(manifest)
    _validate_manifest_hash(manifest)
    return manifest


def _read_file_observations(stage_root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    observations: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    # Sizes must accumulate deterministically in canonical sorted path
    # order (not manifest declaration order or file_id order) so the
    # cumulative-limit subject is always the same offending path.
    for row in sorted(manifest["files"], key=lambda item: item["path"]):
        rel = row["path"]
        if any(part.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", part, re.IGNORECASE) for part in rel.split("/")):
            raise StagingPathError("a staged path is unsafe or escapes the designated root", phase="INVENTORY", exit_code=2, subject=rel)
        full = stage_root / rel.replace("/", os.sep)
        try:
            st = os.lstat(full)
        except OSError as exc:
            raise StagingFileReadError("staged content could not be read as a bounded local regular file", phase="CONTENT", exit_code=2, subject=rel) from exc
        if stat.S_ISLNK(st.st_mode) or _is_windows_reparse(full) or not stat.S_ISREG(st.st_mode):
            raise StagingEntryTypeError("staging tree contains a link, reparse point, special entry, or listed directory", phase="INVENTORY", exit_code=2, subject=rel)
        if st.st_size > 16777216:
            raise StagingLimitError("staging tree exceeds a closed file, directory, depth, or byte limit", phase="INVENTORY", exit_code=2, subject=rel, expected="<= 16777216 bytes per file", actual=st.st_size)
        total_bytes += st.st_size
        if total_bytes > 67108864:
            raise StagingLimitError("staging tree exceeds a closed file, directory, depth, or byte limit", phase="INVENTORY", exit_code=2, subject=rel, expected="<= 67108864 total bytes", actual=total_bytes)
        before_stat = os.lstat(full)
        try:
            raw = full.read_bytes()
        except OSError as exc:
            raise StagingFileReadError("staged content could not be read as a bounded local regular file", phase="CONTENT", exit_code=2, subject=rel) from exc
        for _ in range(2):
            try:
                recheck = full.read_bytes()
            except OSError as exc:
                raise StagingFileReadError("staged content could not be read as a bounded local regular file", phase="CONTENT", exit_code=2, subject=rel) from exc
            if raw != recheck:
                raise StagingInputMutationError("staged manifest or file tree changed during verification", phase="IMMUTABILITY", exit_code=2, subject=rel)
        try:
            after_stat = os.lstat(full)
        except OSError as exc:
            raise StagingInputMutationError("staged manifest or file tree changed during verification", phase="IMMUTABILITY", exit_code=2, subject=rel) from exc
        if before_stat.st_mtime_ns != after_stat.st_mtime_ns or before_stat.st_size != after_stat.st_size or before_stat.st_ino != after_stat.st_ino:
            raise StagingInputMutationError("staged manifest or file tree changed during verification", phase="IMMUTABILITY", exit_code=2, subject=rel)
        checksum = row["checksum"]
        mode = checksum["mode"]
        if mode == "RAW_BYTES":
            desc_size = checksum["raw_byte_size"]
            desc_hash = checksum["raw_sha256"]
            if st.st_size != desc_size:
                raise StagingFileSizeMismatch("staged file content size does not match the manifest", phase="CONTENT", exit_code=2, subject=rel)
            if len(raw) != desc_size or _sha256_hex(raw) != desc_hash:
                raise StagingFileChecksumMismatch("staged file content checksum does not match the manifest", phase="CONTENT", exit_code=2, subject=rel)
            content_byte_size = len(raw)
            sha256 = _sha256_hex(raw)
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise StagingTextEncodingError("canonical-LF staged content is not valid strict UTF-8", phase="CONTENT", exit_code=2, subject=rel) from exc
            canonical = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
            if len(canonical) != checksum["canonical_lf_utf8_bytes"]:
                raise StagingFileSizeMismatch("staged file content size does not match the manifest", phase="CONTENT", exit_code=2, subject=rel)
            if _sha256_hex(canonical) != checksum["canonical_lf_sha256"]:
                raise StagingFileChecksumMismatch("staged file content checksum does not match the manifest", phase="CONTENT", exit_code=2, subject=rel)
            content_byte_size = len(canonical)
            sha256 = _sha256_hex(canonical)
        observations[row["file_id"]] = {
            "file_id": row["file_id"],
            "path": rel,
            "role": row["role"],
            "media_type": row["media_type"],
            "checksum_mode": mode,
            "content_byte_size": content_byte_size,
            "content_sha256": sha256,
            "component_ids": list(row["component_ids"]),
        }
    return observations


# Both baseline passes load through the public V2-S1 `load_registry`, never
# raw `yaml.safe_load`. Its own internal parsing already turns malformed
# YAML and non-UTF-8 bytes into a typed `SourceOpsError`; a bare `OSError`
# (missing file, a directory in its place) can still reach here directly
# from the loader's own path preflight, so both are handled identically.
_REGISTRY_LOAD_FAILURE_TYPES = (SourceOpsError, yaml.YAMLError, UnicodeDecodeError, OSError)


def _registry_raw_mapping(registry: Any) -> dict[str, Any]:
    """Return the exact raw mapping V2-S1 parsed for ``registry``.

    ``load_registry`` already ran this through strict typed validation; its
    kept raw mapping is reused here (mirroring how ``validate_registry``
    itself resolves a ``Registry`` instance) so the hash and
    declaration-binding comparisons below see precisely what V2-S1
    validated, without hand-deriving a second copy.
    """
    raw = getattr(registry, "_raw_mapping", None)
    return dict(raw) if raw is not None else registry.as_dict()


def _validate_baseline_state(registry_path: Path, source_id: str, manifest: dict[str, Any], repo_root: Path, *, validation_out: list[Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        registry_model = load_registry(registry_path)
    except _REGISTRY_LOAD_FAILURE_TYPES as exc:
        # The public V2-S1 loader already turns malformed YAML, non-UTF-8
        # bytes, a non-mapping root, and any typed schema failure into a
        # closed SourceOpsError; a raw path failure (missing file, a
        # directory in its place) surfaces as a plain OSError instead. Both
        # map to the same fixed, textless BASELINE_REGISTRY_INVALID here.
        raise BaselineRegistryInvalidError("current V2-S1 registry is invalid", phase="BASELINE", exit_code=6, subject=CANONICAL_REGISTRY_REL) from exc
    registry_dict = _registry_raw_mapping(registry_model)
    validation = validate_registry(registry_model, repo_root=repo_root)
    if validation_out is not None:
        validation_out.append(validation)
    if validation.errors:
        codes = set()
        for entry in validation.errors:
            if isinstance(entry, dict):
                code = entry.get("code")
                if code is not None:
                    codes.add(code)
                continue
            code = getattr(entry, "code", None)
            if code is not None:
                codes.add(code)
        if "DECLARATION_DRIFT" in codes or "DECLARATION_REFERENCE_INVALID" in codes:
            raise BaselineDeclarationInvalidError("current V2-S1 declaration precondition is invalid or drifted", phase="BASELINE", exit_code=6, subject=source_id)
        raise BaselineRegistryInvalidError("current V2-S1 registry is invalid", phase="BASELINE", exit_code=6, subject=CANONICAL_REGISTRY_REL)
    source_record = None
    for row in registry_dict.get("source_records", []):
        if isinstance(row, dict) and row.get("source_id") == source_id:
            source_record = row
            break
    if source_record is None:
        raise UnknownSourceError("source_id is not present in the validated baseline registry", phase="BASELINE", exit_code=4, subject=source_id)
    current_hash = registry_dict.get("registry_content_hash")
    bound_hash = manifest["source_binding"]["registry_content_hash"]
    if current_hash != bound_hash:
        raise BaselineRegistryHashMismatch("manifest registry_content_hash does not match the current validated registry", phase="BASELINE", exit_code=5, subject=source_id, expected=current_hash, actual=bound_hash)
    if manifest["source_binding"]["declaration_refs"] != source_record.get("declaration_refs"):
        raise BaselineDeclarationBindingMismatch("manifest declaration bindings do not match the selected baseline source", phase="BASELINE", exit_code=5, subject=source_id, expected=source_record.get("declaration_refs"), actual=manifest["source_binding"]["declaration_refs"])
    return registry_dict, source_record


def _resolve_output_paths(manifest_hash: str) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    leaf = REPO_ROOT / OUTPUT_PARENT_REL / manifest_hash
    return leaf, leaf


def _accept_existing_artifact_if_identical(path: Path, encoded: bytes) -> str | None:
    """Resolve whatever currently occupies ``path`` without ever writing to it.

    Returns ``path.name`` once a pre-existing regular file there is confirmed
    byte-identical to ``encoded`` (this is the "another writer already won"
    branch of the concurrent-writer rule: re-lstat/no-follow, then accept
    only identical bytes). Returns ``None``, without raising, when nothing
    occupies ``path`` yet, so the caller knows it is free to publish.

    A link, reparse point, or other non-regular entry fails closed with
    OUTPUT_BOUNDARY_INVALID. A single initial byte mismatch is re-read once
    more before it is treated as a genuine OUTPUT_COLLISION: a legitimate
    concurrent winner publishing the exact same content can never itself
    expose a partial read (its bytes are fully committed before its final
    path becomes visible at all, see `_write_atomic_json`), but a defensive
    second read guards against any transient short read from elsewhere
    without ever poisoning a run over identical content.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(path, root=REPO_ROOT)) from exc
    if stat.S_ISLNK(st.st_mode) or _is_windows_reparse(path) or not stat.S_ISREG(st.st_mode):
        raise OutputBoundaryError("generated artifact path is not a safe real path below the fixed output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(path, root=REPO_ROOT))
    for _attempt in range(2):
        try:
            existing = path.read_bytes()
        except OSError:
            continue
        if existing == encoded:
            return path.name
    raise OutputCollisionError("content-addressed output path already contains non-identical or unknown content", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(path, root=REPO_ROOT))


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> tuple[str, bool]:
    """Publish ``payload`` at ``path`` race-safely and return ``(name, created)``.

    ``created`` is ``True`` only when this call itself won publication of
    ``path`` (so a caller can track exactly which finals it must roll back
    on a later handled failure); it is ``False`` when identical content
    already occupied ``path`` (pre-existing or a concurrent winner).

    The full encoded bytes are always produced (via ``_serialize_json``)
    before any filesystem write. A fresh publish never opens `path` itself
    for writing: it writes the complete bytes to a unique temp file inside
    the same directory first, then publishes with `os.link`, which only
    ever succeeds once the source bytes are already fully committed and
    only ever fails with FileExistsError when a directory entry already
    occupies `path`. This means `path` can never become observable in a
    partially-written state (unlike create-then-write), and (unlike
    `os.rename`, which silently replaces an existing destination) a
    winner's bytes are never replaced.
    """
    encoded = _serialize_json(payload).encode("utf-8")
    for _attempt in range(8):
        accepted = _accept_existing_artifact_if_identical(path, encoded)
        if accepted is not None:
            return accepted, False
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.parent / f"{TEMP_ARTIFACT_PREFIX}{uuid.uuid4().hex}-{path.name}"
        try:
            with open(temp_path, "xb") as handle:
                handle.write(encoded)
            os.link(temp_path, path)
        except FileExistsError:
            # Either the unique temp name itself collided (never expected
            # with a fresh uuid4 per attempt) or another writer published
            # `path` first while this temp file was being written; loop
            # back and resolve `path` afresh instead of assuming collision.
            continue
        except StagedSnapshotError:
            raise
        except OSError as exc:
            raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(path, root=REPO_ROOT)) from exc
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return path.name, True
    raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(path, root=REPO_ROOT))


def _final_matches_expected_bytes(path: Path, expected: bytes) -> bool:
    """True only if a regular, non-linked file already sits at ``path`` with
    exactly ``expected`` bytes (the definition of "this exact final is fully
    published"), used only to decide whether a rollback must stand down.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        return False
    try:
        return path.read_bytes() == expected
    except OSError:
        return False


def _rollback_leaf_publish(
    leaf: Path,
    created_finals: list[Path],
    *,
    created_leaf_this_run: bool,
    expected_artifacts: dict[Path, bytes],
) -> None:
    """Undo exactly what this run published after a handled write/publish failure.

    This run's two-artifact transaction for ``leaf`` is isolated by exact,
    in-memory ownership state (``created_finals`` records only the finals
    *this* call itself newly created; nothing about another writer's own
    successful transaction is ever inferred or touched). Before retracting
    anything, this checks whether the leaf has, in the meantime, already
    reached the complete published state: if every expected artifact path
    now holds exactly its expected bytes, some writer (this run's own first
    artifact shared with a concurrent identical writer's second, or a
    concurrent writer alone) has already relied on and finished this exact
    pair, and this run must never retract a final that a completed,
    successful publication may already depend on. Only when the pair is
    not yet complete does this run retract precisely the
    finals it itself created here (never a pre-existing or concurrent
    winner's bytes, and never a previous run's output); the leaf is never
    scanned for the shared temp-name prefix to sweep up "stray" entries,
    because a fellow live writer's own in-flight temp uses that identical
    prefix and must survive untouched. The leaf directory itself is removed
    only if this run created it and it is now empty. Every step is
    best-effort so a rollback failure never masks the original error that
    triggered it.
    """
    if created_finals:
        try:
            already_complete = all(_final_matches_expected_bytes(path, expected) for path, expected in expected_artifacts.items())
        except OSError:
            already_complete = False
        if already_complete:
            return
    for final_path in created_finals:
        try:
            final_path.unlink(missing_ok=True)
        except OSError:
            pass
    if created_leaf_this_run:
        try:
            if leaf.is_dir() and not leaf.is_symlink() and not any(leaf.iterdir()):
                leaf.rmdir()
        except OSError:
            pass


def _artifact_publish_identity(payload: dict[str, Any], *, artifact_label: str, filename_prefix: str) -> tuple[str, str]:
    declared = payload.get("artifact_content_hash")
    if not isinstance(declared, str) or not HASH_RE.fullmatch(declared):
        raise OutputWriteError(
            "verified artifacts could not be written atomically inside the output boundary",
            phase="OUTPUT",
            exit_code=7,
            subject=f"{artifact_label}.artifact_content_hash",
            expected="lowercase_sha256",
            actual=declared,
        )
    recomputed = _artifact_hash_for(payload)
    if declared != recomputed:
        raise OutputWriteError(
            "verified artifacts could not be written atomically inside the output boundary",
            phase="OUTPUT",
            exit_code=7,
            subject=f"{artifact_label}.artifact_content_hash",
            expected=recomputed,
            actual=declared,
        )
    return declared, f"{filename_prefix}-{declared}.json"


def _leaf_transaction_lock(leaf: Path) -> threading.Lock:
    """Return this interpreter's single shared mutex for ``leaf``.

    The registry is process-global and keyed by the leaf's own string path,
    so every call for the same leaf -- from any thread in this process --
    contends on the exact same ``threading.Lock`` instance, while a
    different leaf never contends with this one. Getting-or-creating the
    per-leaf lock is itself guarded so two threads can never each end up
    with their own, separate lock object for what should be one leaf.
    """
    key = str(leaf)
    with _LEAF_TRANSACTION_REGISTRY_GUARD:
        lock = _LEAF_TRANSACTION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LEAF_TRANSACTION_LOCKS[key] = lock
        return lock


def _acquire_transaction_lock(leaf: Path) -> threading.Lock:
    """Win exclusive, in-process ownership of ``leaf``'s transaction.

    This thread must win the process-wide mutex for this exact leaf
    (bounded wait; a losing thread retries until the current owner
    releases or the wait is exhausted, at which point this fails closed
    rather than ever adopting a partial state unsupervised). Once won, the
    leaf's existence, contents, and an on-disk lock witness file are all
    inspected and mutated only by the single thread holding this mutex --
    see the caller, which does not reuse anything it observed about the
    leaf from before this call returned.
    """
    in_process_lock = _leaf_transaction_lock(leaf)
    if not in_process_lock.acquire(timeout=_TRANSACTION_LOCK_ACQUIRE_TIMEOUT_SECONDS):
        raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(leaf, root=REPO_ROOT))
    return in_process_lock


def _transaction_lock_metadata_bytes(token: str) -> bytes:
    """Serialize this process's deterministic, parseable lock ownership record."""
    payload = {"pid": os.getpid(), "token": token, "version": 1}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _parse_transaction_lock_metadata(raw: bytes) -> dict[str, Any] | None:
    """Parse lock-file bytes into ``{"pid": int, "token": str}``, or ``None``.

    ``None`` covers every way the bytes fail to be this run's own
    deterministic schema: non-UTF-8 bytes, invalid JSON, a non-mapping
    payload, or a missing/malformed ``pid``/``token``. Unknown extra keys
    (for example a foreign writer's own ``"state"`` field) never cause a
    parse failure on their own -- only ``pid``/``token`` presence and type
    are required.
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    pid = payload.get("pid")
    token = payload.get("token")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if not isinstance(token, str) or not token:
        return None
    return {"pid": pid, "token": token}


def _pid_is_alive(pid: int) -> bool:
    """Best-effort, conservative liveness probe for a foreign lock owner.

    Only a definitive "no such process" (`ProcessLookupError`) is ever
    treated as dead. Any other outcome -- confirmed alive, a permission
    error (the process exists but this run cannot signal it), or any other
    unexpected failure of the probe itself -- is treated as alive, so this
    run only ever waits/fails closed and never silently reclaims a lock it
    could not positively prove is orphaned.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _create_transaction_lock_file(lock_path: Path) -> bool:
    """Win exclusive, authoritative on-disk ownership of ``lock_path``.

    This is the sole hard gate a genuinely separate process can observe:
    the file is created with `O_CREAT|O_EXCL|O_WRONLY` (atomic, exclusive
    creation) and its deterministic owner metadata (`pid`, unique `token`,
    `version`) is written and `fsync`-ed before this call ever reports
    ownership as won; a caller must not proceed past this call without it.
    If the file already exists, its bytes are lstat-ed/read without
    following links, then parsed. Invalid/foreign bytes this run cannot
    parse, or a parsed owner pid that is confirmed dead (`_pid_is_alive`
    is `False`), both fail closed immediately: this run never waits on,
    seizes, deletes, or reclaims either the lock or whatever else already
    sits in the leaf. A parsed, live owner (including this run's own pid
    and direct parent pid) is bounded-polled: this call sleeps and retries
    winning the file until either it succeeds (the owner released it) or
    the overall wait exceeds `_TRANSACTION_LOCK_ACQUIRE_TIMEOUT_SECONDS`,
    at which point it also fails closed rather than ever waiting
    unboundedly. Every fail-closed exit raises `OutputWriteError` directly
    (never a bare `OSError`/`TimeoutError`), so this can never degrade
    into an `INTERNAL_ERROR`.
    """
    token = uuid.uuid4().hex
    metadata = _transaction_lock_metadata_bytes(token)
    deadline = time.monotonic() + _TRANSACTION_LOCK_ACQUIRE_TIMEOUT_SECONDS
    lock_subject = _canonical_path_subject(lock_path, root=REPO_ROOT)
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileNotFoundError:
            # A previous owner can complete rollback and remove the leaf
            # directory while this run is still waiting. Recreate/check the
            # leaf and retry winning the exact same lock path.
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject) from exc
            try:
                leaf_stat = os.lstat(lock_path.parent)
            except OSError as exc:
                raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject) from exc
            if stat.S_ISLNK(leaf_stat.st_mode) or _is_windows_reparse(lock_path.parent) or not stat.S_ISDIR(leaf_stat.st_mode):
                raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject)
            if time.monotonic() >= deadline:
                raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject)
            continue
        except FileExistsError:
            pass
        except OSError as exc:
            raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject) from exc
        else:
            try:
                os.write(fd, metadata)
                os.fsync(fd)
            finally:
                os.close(fd)
            _TRANSACTION_LOCK_OWN_TOKENS[str(lock_path)] = token
            return True

        try:
            lock_stat = os.lstat(lock_path)
        except FileNotFoundError:
            # Released between this call's `FileExistsError` and this
            # `lstat` -- retry winning it fresh instead of ever treating a
            # transient gap as a foreign/invalid owner.
            continue
        except OSError as exc:
            raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject) from exc

        if stat.S_ISLNK(lock_stat.st_mode) or not stat.S_ISREG(lock_stat.st_mode):
            raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject)

        try:
            raw = lock_path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject) from exc

        parsed = _parse_transaction_lock_metadata(raw)
        if parsed is None:
            raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject)

        owner_pid = parsed["pid"]
        if not _pid_is_alive(owner_pid):
            try:
                current_stat = os.lstat(lock_path)
            except FileNotFoundError:
                # The owner may have released between this read and liveness
                # probe; retry from scratch instead of failing closed on stale
                # bytes we no longer observe on disk.
                continue
            except OSError as exc:
                raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject) from exc

            if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISREG(current_stat.st_mode):
                raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject)

            try:
                current_raw = lock_path.read_bytes()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject) from exc

            if current_raw != raw:
                # Concurrent release/reacquire changed ownership metadata;
                # re-evaluate the current lock owner instead of treating the
                # stale snapshot as authoritative orphan bytes.
                continue
            raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject)

        if time.monotonic() >= deadline:
            raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=lock_subject)
        time.sleep(_TRANSACTION_LOCK_FILE_RETRY_SLEEP_SECONDS)


def _release_transaction_lock(in_process_lock: threading.Lock, lock_path: Path, owns_lock_file: bool, *, created_leaf_this_run: bool) -> None:
    """Release exactly the ownership this run itself won; best-effort only.

    The on-disk lock entry is removed only if this run is the one that
    created it *and* the file's currently-persisted token still matches
    the exact token this run itself wrote when it created it -- a lock
    file found already held by someone else at acquire time (`owns_lock_file`
    is `False`) is never this run's to delete, and neither is one whose
    recorded token this run can no longer positively confirm as its own.
    If this run also created the leaf directory itself and it is now
    empty (no finals were ever published into it), that directory is
    removed too -- but this, and the lock-file removal above it, both
    happen strictly *before* the in-process mutex is released below,
    never after: releasing the mutex first could hand a waiting
    same-process thread ownership of this exact leaf while this run is
    still deciding whether to delete it out from under that new owner.
    """
    leaf = lock_path.parent
    try:
        try:
            if owns_lock_file:
                expected_token = _TRANSACTION_LOCK_OWN_TOKENS.pop(str(lock_path), None)
                if expected_token is not None:
                    try:
                        current = _parse_transaction_lock_metadata(lock_path.read_bytes())
                    except OSError:
                        current = None
                    if current is not None and current["token"] == expected_token:
                        release_deadline = time.monotonic() + _TRANSACTION_LOCK_RELEASE_RETRY_SECONDS
                        while True:
                            try:
                                lock_path.unlink(missing_ok=True)
                                break
                            except OSError:
                                if time.monotonic() >= release_deadline:
                                    break
                                time.sleep(_TRANSACTION_LOCK_FILE_RETRY_SLEEP_SECONDS)
                                try:
                                    latest = _parse_transaction_lock_metadata(lock_path.read_bytes())
                                except FileNotFoundError:
                                    break
                                except OSError:
                                    continue
                                if latest is None or latest["token"] != expected_token:
                                    break
        except OSError:
            pass
        if created_leaf_this_run:
            try:
                if leaf.is_dir() and not leaf.is_symlink() and not any(leaf.iterdir()):
                    leaf.rmdir()
            except OSError:
                pass
    finally:
        in_process_lock.release()


def _ensure_output_leaf(verification_payload: dict[str, Any], diff_payload: dict[str, Any], manifest_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    leaf = REPO_ROOT / OUTPUT_PARENT_REL / manifest_hash
    safe_parent = REPO_ROOT / OUTPUT_PARENT_REL
    _assert_no_reparse_ancestors(safe_parent, root=REPO_ROOT, error=OutputBoundaryError, phase="OUTPUT", subject=_canonical_path_subject(safe_parent, root=REPO_ROOT), message="generated artifact path is not a safe real path below the fixed output boundary", exit_code=7)
    if not safe_parent.exists():
        safe_parent.mkdir(parents=True, exist_ok=True)
    if not safe_parent.is_dir() or safe_parent.is_symlink() or _is_windows_reparse(safe_parent):
        raise OutputBoundaryError("generated artifact path is not a safe real path below the fixed output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(safe_parent, root=REPO_ROOT))
    _assert_no_reparse_ancestors(leaf, root=REPO_ROOT, error=OutputBoundaryError, phase="OUTPUT", subject=_canonical_path_subject(leaf, root=REPO_ROOT), message="generated artifact path is not a safe real path below the fixed output boundary", exit_code=7)

    # Artifact identity is the payload's self-excluding
    # `artifact_content_hash`; filenames and CLI `ref.content_hash` must use
    # this exact value. Concurrent-winner acceptance remains byte-exact over
    # full persisted bytes in `_accept_existing_artifact_if_identical`.
    v_hash, v_name = _artifact_publish_identity(
        verification_payload,
        artifact_label="verification_artifact",
        filename_prefix="v",
    )
    d_hash, d_name = _artifact_publish_identity(
        diff_payload,
        artifact_label="diff_artifact",
        filename_prefix="d",
    )
    expected_names = sorted([v_name, d_name])

    # Every writer -- whether it will create the leaf's first final, rely
    # on one it finds already present, or roll one back -- must win this
    # exact same per-leaf transaction lock before it so much as checks
    # whether the leaf exists, let alone inspects or touches a single byte
    # inside it below. This is what makes the whole "does the leaf exist,
    # what is already inside it, publish whatever is missing, roll back on
    # failure" sequence a single indivisible transaction for every caller
    # sharing this interpreter: a concurrent identical writer (thread) can
    # never observe (let alone adopt) a leaf -- or a final inside it --
    # that this run has not yet fully committed to keeping, and never
    # races this run's own creation, rollback, or empty-leaf cleanup. A
    # leaf existence/absence fact checked before this lock was won would go
    # stale the instant a previous owner completes its own rollback and
    # removes the leaf entirely while this run was still waiting, so
    # nothing about the leaf itself is decided until after this call
    # returns.
    in_process_lock = _acquire_transaction_lock(leaf)
    created_leaf_this_run = False
    lock_path = leaf / TRANSACTION_LOCK_NAME
    owns_lock_file = False
    try:
        if not leaf.exists():
            try:
                leaf.mkdir(parents=True, exist_ok=False)
                created_leaf_this_run = True
            except FileExistsError:
                # This exact leaf/mutex pairing means only one thread in
                # this process can ever be here at a time, so this guards
                # only the inherent TOCTOU between the `exists()` check
                # and this `mkdir` call itself (for example a symlink
                # attack racing to replace the parent), never a genuine
                # concurrent in-process writer.
                pass

        try:
            leaf_stat = os.lstat(leaf)
        except OSError as exc:
            raise OutputBoundaryError("generated artifact path is not a safe real path below the fixed output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(leaf, root=REPO_ROOT)) from exc
        if stat.S_ISLNK(leaf_stat.st_mode) or _is_windows_reparse(leaf) or not stat.S_ISDIR(leaf_stat.st_mode):
            raise OutputBoundaryError("generated artifact path is not a safe real path below the fixed output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(leaf, root=REPO_ROOT))

        owns_lock_file = _create_transaction_lock_file(lock_path)

        # Absent (just created above), existing-empty, existing-with-
        # exactly-the-two-expected-identical-artifacts, and existing-with-a-
        # partial subset of the expected names (left by a previous lock
        # owner that has since released, whether it published or rolled
        # back) are all safe starting states, evaluated fresh under this
        # run's own lock ownership: only a name outside the expected pair
        # (and never this run's own lock or a concurrent writer's own
        # in-flight temp file) is unconditionally rejected here, checked
        # once before either artifact is touched below.
        try:
            current_names = {
                entry.name
                for entry in leaf.iterdir()
                if not entry.name.startswith(TEMP_ARTIFACT_PREFIX) and entry.name != TRANSACTION_LOCK_NAME
            }
        except OSError as exc:
            raise OutputBoundaryError("generated artifact path is not a safe real path below the fixed output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(leaf, root=REPO_ROOT)) from exc
        if current_names - set(expected_names):
            raise OutputCollisionError("content-addressed output path already contains non-identical or unknown content", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(leaf, root=REPO_ROOT))

        v_path = leaf / v_name
        d_path = leaf / d_name
        # Exact expected bytes for each final, computed once up front from the
        # same pure `_serialize_json` encoding `_write_atomic_json` itself uses.
        # A rollback consults this (never the directory contents alone) to tell
        # a merely-absent sibling apart from a genuinely completed pair.
        expected_artifacts = {
            v_path: _serialize_json(verification_payload).encode("utf-8"),
            d_path: _serialize_json(diff_payload).encode("utf-8"),
        }
        created_finals: list[Path] = []
        try:
            v_written_name, v_created = _write_atomic_json(v_path, verification_payload)
            if v_written_name != v_name:
                raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(v_path, root=REPO_ROOT), expected=v_name, actual=v_written_name)
            if v_created:
                created_finals.append(v_path)
            d_written_name, d_created = _write_atomic_json(d_path, diff_payload)
            if d_written_name != d_name:
                raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(d_path, root=REPO_ROOT), expected=d_name, actual=d_written_name)
            if d_created:
                created_finals.append(d_path)
        except StagedSnapshotError:
            _rollback_leaf_publish(leaf, created_finals, created_leaf_this_run=False, expected_artifacts=expected_artifacts)
            raise
        except Exception as exc:
            _rollback_leaf_publish(leaf, created_finals, created_leaf_this_run=False, expected_artifacts=expected_artifacts)
            raise OutputWriteError("verified artifacts could not be written atomically inside the output boundary", phase="OUTPUT", exit_code=7, subject=_canonical_path_subject(leaf, root=REPO_ROOT)) from exc
    finally:
        _release_transaction_lock(in_process_lock, lock_path, owns_lock_file, created_leaf_this_run=created_leaf_this_run)
    v_ref = {"path": f".raptor/sourceops/generated/staged-snapshots/{manifest_hash}/{v_name}", "content_hash": v_hash}
    d_ref = {"path": f".raptor/sourceops/generated/staged-snapshots/{manifest_hash}/{d_name}", "content_hash": d_hash}
    return v_ref, d_ref


def _cli_error_payload(code: str, phase: str, message: str, *, subject: Any = None, expected: Any = None, actual: Any = None, type_name: str = "StagedSnapshotError") -> dict[str, Any]:
    return {"code": code, "type": type_name, "phase": phase, "message": message, "subject": subject, "expected": expected, "actual": actual}


def _has_checksum_token(source_role: Any) -> bool:
    if not isinstance(source_role, str):
        return False
    return any(token.casefold() == "checksum" for token in re.split(r"[-_\s]+", source_role) if token)


def _validate_content_bindings_and_component_projection(manifest: dict[str, Any], source_record: dict[str, Any]) -> None:
    file_rows = manifest.get("files", [])
    files_by_id = {row["file_id"]: row for row in file_rows if isinstance(row, dict)}
    if not isinstance(source_record, dict):
        raise BaselineRegistryInvalidError("current V2-S1 registry is invalid", phase="BASELINE", exit_code=6, subject=CANONICAL_REGISTRY_REL)
    declaration_paths = {ref.get("path") for ref in source_record.get("declaration_refs", []) if isinstance(ref, dict)}
    # An explicit `components: null` baseline means an empty component
    # baseline, not an absent/defaulted field; `.get(..., [])` alone would
    # not catch this because the key is present with value None.
    source_components_raw = source_record.get("components") or []
    source_component_ids = {comp.get("component_id") for comp in source_components_raw if isinstance(comp, dict)}
    source_components = {comp.get("component_id"): comp for comp in source_components_raw if isinstance(comp, dict) and isinstance(comp.get("component_id"), str)}
    candidate_record_kind = manifest.get("candidate", {}).get("identity", {}).get("record_kind")
    covered_file_ids: set[str] = set()
    for row in manifest.get("content_bindings", []):
        if not isinstance(row, dict):
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="content_bindings", expected="mapping list", actual=type(row).__name__)
        baseline_kind = row.get("baseline_kind")
        baseline_id = row.get("baseline_id")
        candidate_file_id = row.get("candidate_file_id")
        if baseline_kind == "COMPONENT_CHECKSUM":
            if baseline_id is None or baseline_id not in source_component_ids:
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
            component = source_components.get(baseline_id)
            if not isinstance(component, dict):
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
            if not _has_checksum_token(component.get("source_role")):
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
            version_value = component.get("version_or_snapshot")
            if not isinstance(version_value, str) or not re.fullmatch(r"[0-9a-f]{64}", version_value):
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
        if candidate_file_id is not None:
            if candidate_file_id not in files_by_id:
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=candidate_file_id)
            if candidate_file_id in covered_file_ids:
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=candidate_file_id)
            covered_file_ids.add(candidate_file_id)
            file_row = files_by_id[candidate_file_id]
            checksum = file_row.get("checksum") if isinstance(file_row.get("checksum"), dict) else {}
            if baseline_kind == "DECLARATION_REF":
                if file_row.get("role") != "CANDIDATE_DECLARATION":
                    raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=candidate_file_id)
                if file_row.get("media_type") not in {"application/json", "application/x-yaml", "text/plain", "text/csv", "text/tab-separated-values"}:
                    raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=candidate_file_id)
                if checksum.get("mode") != "CANONICAL_LF_TEXT":
                    raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=candidate_file_id)
            elif baseline_kind == "COMPONENT_CHECKSUM":
                if file_row.get("role") not in {"SNAPSHOT_CONTENT", "AUXILIARY_METADATA"}:
                    raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=candidate_file_id)
                if checksum.get("mode") != "RAW_BYTES":
                    raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=candidate_file_id)
                if baseline_id is not None and baseline_id not in file_row.get("component_ids", []):
                    raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
            elif baseline_kind == "NONE":
                if file_row.get("role") not in {"SNAPSHOT_CONTENT", "CANDIDATE_DECLARATION", "AUXILIARY_METADATA"}:
                    raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=candidate_file_id)
        if baseline_kind == "DECLARATION_REF":
            if baseline_id is None or baseline_id not in declaration_paths:
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
        elif baseline_kind == "COMPONENT_CHECKSUM":
            if baseline_id is None or baseline_id not in source_component_ids:
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
            component = source_components.get(baseline_id)
            if not isinstance(component, dict):
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
            if not _has_checksum_token(component.get("source_role")):
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
            version_value = component.get("version_or_snapshot")
            if not isinstance(version_value, str) or not re.fullmatch(r"[0-9a-f]{64}", version_value):
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
        elif baseline_kind == "NONE":
            if baseline_id is not None:
                raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_id)
        else:
            raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=baseline_kind)
    all_file_ids = {row["file_id"] for row in file_rows if isinstance(row, dict)}
    if all_file_ids != covered_file_ids:
        missing = sorted(all_file_ids - covered_file_ids)
        raise ContentBindingError("a content binding is unknown, duplicate, ambiguous, or mode-incompatible", phase="CONTENT", exit_code=2, subject=missing[0] if missing else None)
    file_component_ids: dict[str, str] = {}
    for row in file_rows:
        if not isinstance(row, dict):
            continue
        for component_id in row.get("component_ids", []):
            previous = file_component_ids.get(component_id)
            if previous is not None and previous != row["file_id"]:
                raise ComponentMappingError("component projection or file mapping violates complete closed semantics", phase="CONTENT", exit_code=2, subject=component_id)
            if previous is None:
                file_component_ids[component_id] = row["file_id"]
    projection = manifest.get("component_projection")
    if projection is None:
        unknown_baseline_components = sorted(set(file_component_ids) - source_component_ids)
        if unknown_baseline_components:
            raise ComponentMappingError("component projection or file mapping violates complete closed semantics", phase="CONTENT", exit_code=2, subject=unknown_baseline_components[0])
        return
    if projection.get("mode") != "COMPLETE":
        raise ComponentMappingError("component projection or file mapping violates complete closed semantics", phase="CONTENT", exit_code=2, subject=projection.get("mode"))
    if candidate_record_kind in {"SINGLE_SOURCE", "METADATA_CATALOG_TEMPLATE"} and projection.get("components"):
        raise ComponentMappingError("component projection or file mapping violates complete closed semantics", phase="CONTENT", exit_code=2, subject="component_projection")
    # A candidate component_id absent from the baseline is a valid ADDED
    # component under COMPLETE projection semantics; it must not be rejected.
    projection_entries = projection.get("components", [])
    projection_ids = {entry.get("component_id") for entry in projection_entries if isinstance(entry, dict)}
    unknown_projection_components = sorted(set(file_component_ids) - projection_ids)
    if unknown_projection_components:
        raise ComponentMappingError("component projection or file mapping violates complete closed semantics", phase="CONTENT", exit_code=2, subject=unknown_projection_components[0])


def verify_stage(registry_rel: str, staging_root_rel: str) -> VerifyStageResult:
    source_id = None
    registry_hash = None
    manifest_hash = None
    diff_payload = None
    try:
        registry_path = _validate_registry_path(registry_rel)
        stage_root = _validate_staging_root(staging_root_rel)
        manifest_path = stage_root / "manifest.yaml"
        try:
            import importlib
            sourceops_pkg = importlib.import_module("raptor.sourceops")
            manifest_model = sourceops_pkg.load_manifest(str(manifest_path))
            manifest = manifest_model.as_dict()
        except StagedSnapshotError:
            # Already a closed, typed staging error: propagate unchanged.
            raise
        except TypeError as exc:
            # A foreseeable manifest type/schema failure (e.g. an unhashable
            # container value reaching a closed-enum membership test). The
            # internal validators are expected to guard against this before
            # it ever escapes as a raw TypeError, but this boundary is a
            # closed backstop: it must still fail with the typed schema
            # error and a fixed message, never the raw exception text, and
            # never as an INTERNAL_ERROR.
            raise StagingManifestSchemaError("staged manifest violates the closed typed schema", phase="MANIFEST_SCHEMA", exit_code=2, subject="manifest.yaml") from exc
        # Any other exception here is genuinely unexpected (not a closed
        # staging error and not a foreseeable type/schema failure): it must
        # not be broad-caught as a schema error. Let it propagate to the
        # single closed internal-error boundary below.
        source_id = manifest["source_binding"]["source_id"]
        manifest_hash = manifest["manifest_content_hash"]
        baseline_validation_holder: list[Any] = []
        registry_dict, source_record = _validate_baseline_state(registry_path, source_id, manifest, REPO_ROOT, validation_out=baseline_validation_holder)
        registry_hash = registry_dict.get("registry_content_hash")
        first_stage_snapshot = _snapshot_stage_tree(stage_root)
        _validate_unlisted_tree(stage_root, manifest)
        file_observations = _read_file_observations(stage_root, manifest)
        _validate_content_bindings_and_component_projection(manifest, source_record)

        baseline_snapshot = _snapshot_baseline_files(source_record, REPO_ROOT)
        baseline_validation = baseline_validation_holder[0]
        candidate_hash = manifest["manifest_content_hash"]

        diff_payload = _build_diff_artifact(manifest, source_record, file_observations)
        verification_payload = _build_verification_artifact(manifest, source_record, file_observations, diff_payload)

        second_stage_snapshot = _snapshot_stage_tree(stage_root)
        if first_stage_snapshot != second_stage_snapshot:
            raise StagingInputMutationError("staged manifest or file tree changed during verification", phase="IMMUTABILITY", exit_code=2, subject=staging_root_rel)
        second_baseline_snapshot = _snapshot_baseline_files(source_record, REPO_ROOT)
        try:
            second_validation = validate_registry(load_registry(registry_path), repo_root=REPO_ROOT)
        except _REGISTRY_LOAD_FAILURE_TYPES as exc:
            # The second baseline pass reruns the same public V2-S1
            # `load_registry` used by the first pass. A first-pass loader
            # failure is BASELINE_REGISTRY_INVALID (checked above, before any
            # staging work); the identical failure surfacing only now means
            # the registry became unreadable/malformed after the first
            # baseline snapshot was already taken, which is exactly FM10B's
            # concurrent-mutation threat, never an unrelated INTERNAL_ERROR.
            raise BaselineChangedDuringRunError("validated registry or selected declaration changed during verification", phase="BASELINE", exit_code=6, subject=source_id) from exc
        if baseline_snapshot != second_baseline_snapshot or baseline_validation.as_report() != second_validation.as_report():
            raise BaselineChangedDuringRunError("validated registry or selected declaration changed during verification", phase="BASELINE", exit_code=6, subject=source_id)
        v_ref, d_ref = _ensure_output_leaf(verification_payload, diff_payload, candidate_hash)
        report = CliResult(
            schema=CLI_SCHEMA_ID,
            command="verify-stage",
            run_status="COMPLETED",
            input_validity="VALID",
            stage_outcome=diff_payload["stage_outcome"],
            source_id=source_id,
            registry_content_hash=registry_hash,
            manifest_content_hash=manifest_hash,
            verification_artifact=v_ref,
            diff_artifact=d_ref,
            error=None,
            validation_ceiling=STAGED_SNAPSHOT_VALIDATION_CEILING,
        )
        return VerifyStageResult(0, report)
    except StagedSnapshotError as exc:
        error_payload = exc.as_error_dict()
        if exc.code in {"BASELINE_REGISTRY_PATH_INVALID", "UNKNOWN_SOURCE", "BASELINE_REGISTRY_HASH_MISMATCH", "BASELINE_DECLARATION_BINDING_MISMATCH", "BASELINE_REGISTRY_INVALID", "BASELINE_DECLARATION_INVALID", "BASELINE_CHANGED_DURING_RUN"}:
            input_validity = "NOT_EVALUATED"
        elif exc.code in {"STAGING_ROOT_INVALID", "STAGING_MANIFEST_MISSING", "STAGING_MANIFEST_TYPE_INVALID", "STAGING_MANIFEST_READ_FAILED", "STAGING_MANIFEST_LIMIT_EXCEEDED", "STAGING_MANIFEST_ENCODING_INVALID", "STAGING_MANIFEST_YAML_INVALID", "STAGING_MANIFEST_SCHEMA_INVALID", "STAGING_DUPLICATE_ID", "STAGING_DUPLICATE_PATH", "STAGING_MANIFEST_HASH_MISMATCH", "STAGING_PATH_INVALID", "STAGING_ENTRY_TYPE_INVALID", "STAGING_TREE_MISMATCH", "STAGING_LIMIT_EXCEEDED", "CONTENT_BINDING_INVALID", "COMPONENT_MAPPING_INVALID", "STAGING_FILE_SIZE_MISMATCH", "STAGING_FILE_CHECKSUM_MISMATCH", "STAGING_TEXT_ENCODING_INVALID", "STAGING_FILE_READ_FAILED", "STAGING_INPUT_MUTATED"}:
            input_validity = "INVALID"
        else:
            input_validity = "NOT_EVALUATED"
        if exc.code in {"OUTPUT_BOUNDARY_INVALID", "OUTPUT_COLLISION", "OUTPUT_WRITE_FAILED"}:
            input_validity = "VALID"
        stage_outcome = None
        if exc.code in {"OUTPUT_BOUNDARY_INVALID", "OUTPUT_COLLISION", "OUTPUT_WRITE_FAILED"} and isinstance(diff_payload, dict):
            stage_outcome = diff_payload.get("stage_outcome")
        result = CliResult(
            schema=CLI_SCHEMA_ID,
            command="verify-stage",
            run_status="FAILED",
            input_validity=input_validity,
            stage_outcome=stage_outcome,
            source_id=source_id,
            registry_content_hash=registry_hash,
            manifest_content_hash=manifest_hash,
            verification_artifact=None,
            diff_artifact=None,
            error=error_payload,
            validation_ceiling=STAGED_SNAPSHOT_VALIDATION_CEILING,
        )
        return VerifyStageResult(exc.exit_code, result)
    except Exception as exc:  # closed internal-error boundary: genuinely unexpected failures (not a closed staging error, not a foreseeable manifest type/schema failure) fail closed here, never as exit 2 or with raw exception text.
        payload = _cli_error_payload("INTERNAL_ERROR", "INTERNAL", "verify-stage failed closed because of an unexpected internal error", type_name="InternalStageError")
        result = CliResult(
            schema=CLI_SCHEMA_ID,
            command="verify-stage",
            run_status="FAILED",
            input_validity="NOT_EVALUATED",
            stage_outcome=None,
            source_id=None,
            registry_content_hash=None,
            manifest_content_hash=None,
            verification_artifact=None,
            diff_artifact=None,
            error=payload,
            validation_ceiling=STAGED_SNAPSHOT_VALIDATION_CEILING,
        )
        return VerifyStageResult(70, result)


def _normalise_verify_args(argv: list[str]) -> dict[str, Any]:
    if not argv:
        raise CliUsageError("verify-stage arguments do not match the closed command contract", phase="CLI", exit_code=2, subject=None, expected=["--registry", "--staging-root"], actual=None)
    parsed: dict[str, str] = {}
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token in {"--registry", "--staging-root"}:
            if idx + 1 >= len(argv):
                raise CliUsageError("verify-stage arguments do not match the closed command contract", phase="CLI", exit_code=2, subject=token, expected="value", actual=None)
            if token in parsed:
                raise CliUsageError("verify-stage arguments do not match the closed command contract", phase="CLI", exit_code=2, subject=token, expected="unique", actual=parsed[token])
            parsed[token] = argv[idx + 1]
            idx += 2
            continue
        if token.startswith("--"):
            raise CliUsageError("verify-stage arguments do not match the closed command contract", phase="CLI", exit_code=2, subject=token, expected=["--registry", "--staging-root"], actual=token)
        raise CliUsageError("verify-stage arguments do not match the closed command contract", phase="CLI", exit_code=2, subject=token, expected=["--registry", "--staging-root"], actual=token)
    if "--registry" not in parsed or "--staging-root" not in parsed:
        raise CliUsageError("verify-stage arguments do not match the closed command contract", phase="CLI", exit_code=2, subject=None, expected=["--registry", "--staging-root"], actual=parsed)
    return parsed


def _main_verify_cli(argv: list[str]) -> int:
    try:
        parsed = _normalise_verify_args(argv)
    except CliUsageError as exc:
        report = CliResult(
            schema=CLI_SCHEMA_ID,
            command="verify-stage",
            run_status="FAILED",
            input_validity="NOT_EVALUATED",
            stage_outcome=None,
            source_id=None,
            registry_content_hash=None,
            manifest_content_hash=None,
            verification_artifact=None,
            diff_artifact=None,
            error=exc.as_error_dict(),
            validation_ceiling=STAGED_SNAPSHOT_VALIDATION_CEILING,
        )
        return _emit_cli_result(report.as_dict(), exc.exit_code)
    try:
        outcome = verify_stage(parsed["--registry"], parsed["--staging-root"])
        code = outcome.exit_code
        result = outcome.report
    except Exception:  # pragma: no cover
        payload = _cli_error_payload("INTERNAL_ERROR", "INTERNAL", "verify-stage failed closed because of an unexpected internal error", type_name="InternalStageError")
        result = CliResult(
            schema=CLI_SCHEMA_ID,
            command="verify-stage",
            run_status="FAILED",
            input_validity="NOT_EVALUATED",
            stage_outcome=None,
            source_id=None,
            registry_content_hash=None,
            manifest_content_hash=None,
            verification_artifact=None,
            diff_artifact=None,
            error=payload,
            validation_ceiling=STAGED_SNAPSHOT_VALIDATION_CEILING,
        )
        code = 70
    return _emit_cli_result(result.as_dict(), code)
