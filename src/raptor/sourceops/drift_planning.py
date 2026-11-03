"""V2-S3 material-drift impact routing and read-only rollback rehearsal.

Authority: docs/project/specs/raptor-v2-s3-drift-gates.yaml

This module independently validates one already-published, immutable V2-S2
staged-snapshot artifact pair against the current, still-valid V2-S1
registry, applies one fixed checked-in materiality policy, and publishes two
deterministic, content-addressed, proposal-only artifacts: an "impact plan"
of per-fact materiality evaluations and proposed (never approved or
executed) impact routes, and a "rollback rehearsal plan" of read-only
rollback lineage, integrity checks, and inert typed rollback operations.

Every route and operation this module produces carries
``proposal_only=True``, ``approval_required=True``,
``approval_state="NOT_GRANTED"`` and ``executed=False``. This module never
downloads, mutates, promotes, rebuilds, invalidates, reruns, or restores
anything; it performs bounded local reads, hashes, deterministic evaluation,
and generated-artifact publication only.
"""

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
from pathlib import Path
from typing import Any

import yaml

from raptor.sourceops.model import (
    ActionDisposition,
    ALLOWED_RECORD_KINDS,
    ALLOWED_SOURCE_LIFECYCLES,
    ArtifactReference,
    DiffFact,
    FactEvaluation,
    FactPathSelector,
    ImpactPlanArtifact,
    ImpactRoutingResult,
    MaterialityAssessment,
    MaterialityPolicy,
    MaterialityRule,
    MaterialitySelectors,
    PlanDriftCliResult,
    PlanDriftResult,
    PreservationBinding,
    ProposedRoute,
    ProposedRollbackOperation,
    Registry,
    RollbackBlocker,
    RollbackFileBinding,
    RollbackIntegrityCheck,
    RollbackMetadataArtifact,
    RollbackPlanArtifact,
    RollbackRehearsal,
    RoutePrerequisite,
    SourceOpsError,
    V2S2ArtifactPair,
    V2S2ArtifactRef,
    freeze_json,
    thaw_json,
)
from raptor.sourceops.registry import load_registry, validate_registry
from raptor.sourceops.staged_snapshot import FILE_IDENTIFIER_RE

REPO_ROOT = Path(__file__).resolve().parents[3]

CANONICAL_REGISTRY_REL = "configs/sourceops/source_registry.yaml"
MATERIALITY_POLICY_REL = "configs/sourceops/materiality_policy.yaml"
V2S2_INPUT_PARENT_REL = ".raptor/sourceops/generated/staged-snapshots"
DRIFT_OUTPUT_PARENT_REL = ".raptor/sourceops/generated/drift-plans"

POLICY_SCHEMA_ID = "raptor.sourceops.materiality_policy.v1"
POLICY_HASH_BASIS = "raptor.sourceops.materiality_policy_content_hash.v1"
VERIFICATION_SCHEMA_ID = "raptor.sourceops.staged_snapshot_verification.v1"
VERIFICATION_HASH_BASIS = "raptor.sourceops.staged_snapshot_verification_content_hash.v1"
DIFF_SCHEMA_ID = "raptor.sourceops.staged_snapshot_diff.v1"
DIFF_HASH_BASIS = "raptor.sourceops.staged_snapshot_diff_content_hash.v1"
IMPACT_SCHEMA_ID = "raptor.sourceops.drift_impact_plan.v1"
IMPACT_HASH_BASIS = "raptor.sourceops.drift_impact_plan_content_hash.v1"
ROLLBACK_PLAN_SCHEMA_ID = "raptor.sourceops.rollback_rehearsal_plan.v1"
ROLLBACK_PLAN_HASH_BASIS = "raptor.sourceops.rollback_rehearsal_plan_content_hash.v1"
ROLLBACK_ARTIFACT_SCHEMA_ID = "raptor.sourceops.rollback_artifact.v1"
ROLLBACK_ARTIFACT_HASH_BASIS = "raptor.sourceops.rollback_artifact_content_hash.v1"
CLI_RESULT_SCHEMA_ID = "raptor.sourceops.drift_plan_cli_result.v1"
REGISTRY_SCHEMA_ID = "raptor.source_registry.v1"

# Fixed hash basis and sentinel for the non-cyclic rollback source-record
# binding hash (authority_amendment V2-S3-A1-ROLLBACK-BINDING-AND-RED-NON-VACUITY).
# The rollback input artifact is content-addressed by its own filename, and
# the raw source record embeds that artifact's path at
# ``rollback.rollback_artifact``; hashing the full raw record (which is what
# the registry/source-record content hashes do) would make the artifact's
# own filename hash depend on itself. This domain-separated hash instead
# replaces only that one field with a fixed sentinel before hashing, so it
# never depends on -- and is never fed back into -- the artifact's path.
ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS = "raptor.sourceops.rollback_source_record_binding_hash.v1"
ROLLBACK_SOURCE_RECORD_BINDING_SENTINEL = "__RAPTOR_ROLLBACK_ARTIFACT_CONTENT_ADDRESS_V1__"

VALIDATION_CEILING = (
    "V2-S3 can establish that one valid V2-S2 observation was evaluated by one exact approved mechanical policy, "
    "that proposed routes follow the current declared SourceOps graph, and that a rollback lineage is mechanically "
    "ready, not applicable, or blocked. It cannot approve or execute any route, establish scientific or legal "
    "sufficiency, alter evidence, authorize promotion, or satisfy a clinical, RescueScreen, or independent-panel gate."
)

ALLOWED_ACTIONS_IN_ORDER: tuple[str, ...] = (
    "record_only",
    "block_consumer",
    "stage_diff",
    "rebuild_benchmark",
    "review_policy",
    "invalidate_packets",
    "reground_atlas",
    "rerun_validation",
    "rollback",
)
RESERVED_CONSUMER_IDS = {"rescuescreen", "atlas-technical-coverage-panel", "atlas-independent-validation-panel"}

ALLOWED_DIFFERENCE_KINDS = ("CONTENT", "METADATA", "DECLARATION")
ALLOWED_FACT_KINDS = ("IDENTITY", "VERSION", "CHECKSUM", "MANIFEST", "COMPONENT", "METADATA")
ALLOWED_SUBJECT_TYPES = ("SOURCE", "FILE", "COMPONENT", "DECLARATION")
ALLOWED_CLASSIFICATIONS = ("ADDED", "REMOVED", "CHANGED", "UNCHANGED")
ALLOWED_BASELINE_ORIGINS = {"REGISTRY_SOURCE_RECORD", "REGISTRY_DECLARATION_REF", "REGISTRY_COMPONENT", "ABSENT"}
ALLOWED_CANDIDATE_ORIGINS = {"MANIFEST_CANDIDATE", "STAGED_FILE_OBSERVATION", "MANIFEST_COMPONENT", "ABSENT"}
DIFFERENCE_KIND_ORDER = {name: index for index, name in enumerate(ALLOWED_DIFFERENCE_KINDS)}
FACT_KIND_ORDER = {name: index for index, name in enumerate(ALLOWED_FACT_KINDS)}
SUBJECT_TYPE_ORDER = {name: index for index, name in enumerate(ALLOWED_SUBJECT_TYPES)}
REQUIRED_SOURCE_FACT_PATHS = (
    "/identity/display_name",
    "/identity/record_kind",
    "/identity/owner",
    "/identity/authoritative_locator",
    "/release/version_or_snapshot",
    "/release/release_date",
    "/release/retrieved_at",
    "/release/content_pin_status",
    "/licence/status",
    "/licence/identifier_or_family",
    "/licence/terms_locator",
    "/licence/permitted_use",
    "/licence/redistribution",
    "/licence/cloud_egress",
    "/licence/verification_basis",
    "/acquisition/method",
    "/acquisition/operator_contract",
    "/acquisition/writes_outside_repository",
)

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
V_FILENAME_RE = re.compile(r"^v-[0-9a-f]{64}\.json$")
D_FILENAME_RE = re.compile(r"^d-[0-9a-f]{64}\.json$")
ROLLBACK_ARTIFACT_FILENAME_RE = re.compile(r"^rb-[0-9a-f]{64}\.json$")

# ``read_and_structure_limits`` (runtime_boundaries) from the authority file.
VERIFICATION_ARTIFACT_BYTES = 2_097_152
DIFF_ARTIFACT_BYTES = 16_777_216
MATERIALITY_POLICY_BYTES = 524_288
REGISTRY_BYTES = 1_048_576
DECLARATION_OR_PRESERVATION_FILE_BYTES = 16_777_216
ROLLBACK_ARTIFACT_BYTES = 2_097_152
ROLLBACK_BOUND_FILE_BYTES = 16_777_216
MAXIMUM_DIFF_FACTS = 2048
MAXIMUM_JSON_NODES = 200_000
MAXIMUM_JSON_DEPTH = 32
MAXIMUM_POLICY_NODES = 20_000
MAXIMUM_POLICY_DEPTH = 20
MAXIMUM_POLICY_RULES = 64
MAXIMUM_ROLLBACK_FILE_BINDINGS = 64
EACH_OUTPUT_ARTIFACT_BYTES = 16_777_216
TOTAL_OUTPUT_ARTIFACT_BYTES = 33_554_432

_TRANSACTION_LOCK_NAME = ".sourceops-transaction.lock"
_TEMP_ARTIFACT_PREFIX = ".sourceops-artifact-tmp-"
_TRANSACTION_ACQUIRE_TIMEOUT_SECONDS = 30.0
_TRANSACTION_RETRY_SLEEP_SECONDS = 0.01
_LEAF_LOCKS: dict[str, threading.Lock] = {}
_LEAF_LOCKS_GUARD = threading.Lock()
_LOCK_OWN_TOKENS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# JSON-safety and canonicalization helpers.
# ---------------------------------------------------------------------------


def _json_safe_scalar(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value in (float("inf"), float("-inf")):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, int):
        return str(value)
    return f"<{type(value).__name__}>"


def _json_safe_detail(value: Any, *, _depth: int = 0) -> Any:
    if _depth >= 8:
        return _json_safe_scalar(value)
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and len(value) > 1024:
            return value[:1024]
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return _json_safe_scalar(value)
        return value
    if isinstance(value, dict):
        items = list(value.items())[:64]
        return {(key if isinstance(key, str) else _json_safe_scalar(key)): _json_safe_detail(item, _depth=_depth + 1) for key, item in items}
    if isinstance(value, (list, tuple)):
        return [_json_safe_detail(item, _depth=_depth + 1) for item in list(value)[:64]]
    return _json_safe_scalar(value)


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _self_excluding_hash(mapping: dict[str, Any], field_name: str) -> str:
    basis = copy.deepcopy(mapping)
    basis.pop(field_name, None)
    return _sha256_hex(_canonical_json_bytes(basis))


def _canonical_lf_bytes(raw: bytes) -> bytes:
    text = raw.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _canonical_path_subject(path: Path, *, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.as_posix()
    return relative.as_posix()


# ---------------------------------------------------------------------------
# Closed error catalog.
# ---------------------------------------------------------------------------


class DriftPlanningError(SourceOpsError):
    """Base class for every closed, typed V2-S3 plan-drift failure."""

    code = "DRIFT_INTERNAL_ERROR"
    phase = "INTERNAL"
    exit_code = 70

    def __init__(self, message: str, *, subject: Any = None, expected: Any = None, actual: Any = None) -> None:
        super().__init__(message, code=self.code)
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


def _make_error(name: str, code: str, phase: str, exit_code: int) -> type[DriftPlanningError]:
    return type(name, (DriftPlanningError,), {"code": code, "phase": phase, "exit_code": exit_code})


DriftCliUsageError = _make_error("DriftCliUsageError", "CLI_USAGE_ERROR", "CLI", 2)
DriftInputLeafError = _make_error("DriftInputLeafError", "DRIFT_INPUT_LEAF_INVALID", "BOUNDARY", 2)
DriftInputArtifactSetError = _make_error("DriftInputArtifactSetError", "DRIFT_INPUT_ARTIFACT_SET_INVALID", "INPUT_DISCOVERY", 2)
DriftInputLeafNotFinalizedError = _make_error("DriftInputLeafNotFinalizedError", "DRIFT_INPUT_LEAF_NOT_FINALIZED", "INPUT_DISCOVERY", 2)
DriftArtifactReadError = _make_error("DriftArtifactReadError", "DRIFT_ARTIFACT_READ_FAILED", "ARTIFACT_READ", 2)
DriftArtifactLimitError = _make_error("DriftArtifactLimitError", "DRIFT_ARTIFACT_LIMIT_EXCEEDED", "ARTIFACT_READ", 2)
DriftArtifactEncodingError = _make_error("DriftArtifactEncodingError", "DRIFT_ARTIFACT_ENCODING_INVALID", "ARTIFACT_READ", 2)
DriftArtifactJsonError = _make_error("DriftArtifactJsonError", "DRIFT_ARTIFACT_JSON_INVALID", "ARTIFACT_SCHEMA", 2)
DriftArtifactCanonicalBytesError = _make_error("DriftArtifactCanonicalBytesError", "DRIFT_ARTIFACT_CANONICAL_BYTES_INVALID", "ARTIFACT_SCHEMA", 2)
DriftVerificationSchemaError = _make_error("DriftVerificationSchemaError", "DRIFT_VERIFICATION_SCHEMA_INVALID", "ARTIFACT_SCHEMA", 2)
DriftDiffSchemaError = _make_error("DriftDiffSchemaError", "DRIFT_DIFF_SCHEMA_INVALID", "ARTIFACT_SCHEMA", 2)
DriftArtifactFilenameHashMismatch = _make_error("DriftArtifactFilenameHashMismatch", "DRIFT_ARTIFACT_FILENAME_HASH_MISMATCH", "ARTIFACT_HASH", 2)
DriftArtifactHashMismatch = _make_error("DriftArtifactHashMismatch", "DRIFT_ARTIFACT_HASH_MISMATCH", "ARTIFACT_HASH", 2)
DriftArtifactCrossBindingMismatch = _make_error("DriftArtifactCrossBindingMismatch", "DRIFT_ARTIFACT_CROSS_BINDING_MISMATCH", "ARTIFACT_CROSS_BINDING", 2)
DriftInputTreeHashMismatch = _make_error("DriftInputTreeHashMismatch", "DRIFT_INPUT_TREE_HASH_MISMATCH", "ARTIFACT_CROSS_BINDING", 2)
DriftBaselineRegistryError = _make_error("DriftBaselineRegistryError", "DRIFT_BASELINE_REGISTRY_INVALID", "BASELINE", 5)
DriftBaselineDeclarationError = _make_error("DriftBaselineDeclarationError", "DRIFT_BASELINE_DECLARATION_INVALID", "BASELINE", 5)
DriftUnknownSourceError = _make_error("DriftUnknownSourceError", "DRIFT_UNKNOWN_SOURCE", "BASELINE", 4)
DriftBaselineBindingMismatch = _make_error("DriftBaselineBindingMismatch", "DRIFT_BASELINE_BINDING_MISMATCH", "BASELINE", 5)
DriftBaselineActionPolicyError = _make_error("DriftBaselineActionPolicyError", "DRIFT_BASELINE_ACTION_POLICY_INVALID", "BASELINE", 5)
DriftLineageError = _make_error("DriftLineageError", "DRIFT_LINEAGE_INVALID", "BASELINE", 5)
DriftFactInvariantError = _make_error("DriftFactInvariantError", "DRIFT_FACT_INVARIANT_INVALID", "FACT_VALIDATION", 2)
DriftPolicyReadError = _make_error("DriftPolicyReadError", "DRIFT_POLICY_READ_FAILED", "POLICY_READ", 6)
DriftPolicyEncodingError = _make_error("DriftPolicyEncodingError", "DRIFT_POLICY_ENCODING_INVALID", "POLICY_READ", 6)
DriftPolicyYamlError = _make_error("DriftPolicyYamlError", "DRIFT_POLICY_YAML_INVALID", "POLICY_SCHEMA", 6)
DriftPolicySchemaError = _make_error("DriftPolicySchemaError", "DRIFT_POLICY_SCHEMA_INVALID", "POLICY_SCHEMA", 6)
DriftPolicyHashMismatch = _make_error("DriftPolicyHashMismatch", "DRIFT_POLICY_HASH_MISMATCH", "POLICY_HASH", 6)
DriftPolicyBindingMismatch = _make_error("DriftPolicyBindingMismatch", "DRIFT_POLICY_BINDING_MISMATCH", "POLICY_HASH", 6)
DriftPolicyAmbiguityError = _make_error("DriftPolicyAmbiguityError", "DRIFT_POLICY_AMBIGUOUS", "POLICY_HASH", 6)
DriftMaterialityEvaluationError = _make_error("DriftMaterialityEvaluationError", "DRIFT_MATERIALITY_EVALUATION_INVALID", "MATERIALITY", 6)
DriftRouteInvariantError = _make_error("DriftRouteInvariantError", "DRIFT_ROUTE_INVARIANT_INVALID", "ROUTING", 70)
DriftInputMutationError = _make_error("DriftInputMutationError", "DRIFT_INPUT_MUTATED", "IMMUTABILITY", 2)
DriftBaselineMutationError = _make_error("DriftBaselineMutationError", "DRIFT_BASELINE_CHANGED_DURING_RUN", "IMMUTABILITY", 5)
DriftPolicyMutationError = _make_error("DriftPolicyMutationError", "DRIFT_POLICY_CHANGED_DURING_RUN", "IMMUTABILITY", 6)
DriftRollbackMutationError = _make_error("DriftRollbackMutationError", "DRIFT_ROLLBACK_INPUT_MUTATED", "IMMUTABILITY", 8)
DriftOutputBoundaryError = _make_error("DriftOutputBoundaryError", "DRIFT_OUTPUT_BOUNDARY_INVALID", "OUTPUT", 7)
DriftOutputLimitError = _make_error("DriftOutputLimitError", "DRIFT_OUTPUT_LIMIT_EXCEEDED", "OUTPUT", 7)
DriftOutputCollisionError = _make_error("DriftOutputCollisionError", "DRIFT_OUTPUT_COLLISION", "OUTPUT", 7)
DriftOutputWriteError = _make_error("DriftOutputWriteError", "DRIFT_OUTPUT_WRITE_FAILED", "OUTPUT", 7)
DriftInternalError = _make_error("DriftInternalError", "DRIFT_INTERNAL_ERROR", "INTERNAL", 70)

_INPUT_DISCOVERY_CODES = {DriftInputLeafError.code, DriftInputArtifactSetError.code, DriftInputLeafNotFinalizedError.code}
_ARTIFACT_INVALID_CODES = {
    DriftArtifactReadError.code,
    DriftArtifactLimitError.code,
    DriftArtifactEncodingError.code,
    DriftArtifactJsonError.code,
    DriftArtifactCanonicalBytesError.code,
    DriftVerificationSchemaError.code,
    DriftDiffSchemaError.code,
    DriftArtifactFilenameHashMismatch.code,
    DriftArtifactHashMismatch.code,
    DriftArtifactCrossBindingMismatch.code,
    DriftInputTreeHashMismatch.code,
    DriftFactInvariantError.code,
}
_BASELINE_CODES = {
    DriftBaselineRegistryError.code,
    DriftBaselineDeclarationError.code,
    DriftUnknownSourceError.code,
    DriftBaselineBindingMismatch.code,
    DriftBaselineActionPolicyError.code,
    DriftLineageError.code,
}
_POLICY_CODES = {
    DriftPolicyReadError.code,
    DriftPolicyEncodingError.code,
    DriftPolicyYamlError.code,
    DriftPolicySchemaError.code,
    DriftPolicyHashMismatch.code,
    DriftPolicyBindingMismatch.code,
    DriftPolicyAmbiguityError.code,
}


# ---------------------------------------------------------------------------
# No-follow filesystem safety helpers.
# ---------------------------------------------------------------------------


def _lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except OSError:
        return None


def _assert_no_reparse_ancestors(path: Path, *, root: Path, error: type[DriftPlanningError], message: str, subject: Any = None) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise error(message, subject=subject if subject is not None else _canonical_path_subject(path, root=root)) from exc
    current = root
    for part in relative.parts:
        current = current / part
        st = _lstat_or_none(current)
        if st is None:
            break
        if stat.S_ISLNK(st.st_mode):
            raise error(message, subject=_canonical_path_subject(current, root=root))


_LOCK_OR_TEMP_HINT_RE = re.compile(r"lock|tmp|temp", re.IGNORECASE)


def _looks_lock_or_temp(name: str) -> bool:
    return name.startswith(".") or bool(_LOCK_OR_TEMP_HINT_RE.search(name))


def _discover_v2s2_pair(manifest_hash: str) -> tuple[Path, Path]:
    parent = REPO_ROOT / V2S2_INPUT_PARENT_REL
    leaf = parent / manifest_hash
    boundary_message = "V2-S2 input leaf is outside the fixed safe generated boundary"
    _assert_no_reparse_ancestors(parent, root=REPO_ROOT, error=DriftInputLeafError, message=boundary_message)
    _assert_no_reparse_ancestors(leaf, root=REPO_ROOT, error=DriftInputLeafError, message=boundary_message)

    leaf_st = _lstat_or_none(leaf)
    if leaf_st is None:
        raise DriftInputArtifactSetError("V2-S2 input leaf does not contain exactly one final artifact pair", subject=manifest_hash)
    if stat.S_ISLNK(leaf_st.st_mode) or not stat.S_ISDIR(leaf_st.st_mode):
        raise DriftInputLeafError(boundary_message, subject=manifest_hash)

    try:
        entries = sorted(os.scandir(leaf), key=lambda entry: entry.name)
    except OSError as exc:
        raise DriftInputLeafError(boundary_message, subject=manifest_hash) from exc

    verification_matches: list[Path] = []
    diff_matches: list[Path] = []
    has_special = False
    has_lock_or_temp = False
    for entry in entries:
        entry_path = leaf / entry.name
        st = _lstat_or_none(entry_path)
        if st is None:
            has_special = True
            continue
        is_symlink = stat.S_ISLNK(st.st_mode)
        is_regular = stat.S_ISREG(st.st_mode) and not is_symlink
        matches_v = bool(V_FILENAME_RE.fullmatch(entry.name))
        matches_d = bool(D_FILENAME_RE.fullmatch(entry.name))
        if (matches_v or matches_d) and not is_regular:
            has_special = True
            continue
        if is_symlink or stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode) or stat.S_ISBLK(st.st_mode) or stat.S_ISCHR(st.st_mode):
            has_special = True
            continue
        if _looks_lock_or_temp(entry.name):
            has_lock_or_temp = True
            continue
        if is_regular and matches_v:
            verification_matches.append(entry_path)
            continue
        if is_regular and matches_d:
            diff_matches.append(entry_path)
            continue
        # An extra, unrelated, well-formed regular file or plain directory:
        # it breaks the "exactly one pair" count below but is not itself
        # evidence of an in-progress lock/temp/special publication.

    total_entries = len(entries)
    if len(verification_matches) != 1 or len(diff_matches) != 1 or total_entries != 2:
        if has_special or has_lock_or_temp:
            raise DriftInputLeafNotFinalizedError("V2-S2 input leaf contains a lock, temporary, linked, special, or partial entry", subject=manifest_hash)
        raise DriftInputArtifactSetError("V2-S2 input leaf does not contain exactly one final artifact pair", subject=manifest_hash)

    return verification_matches[0], diff_matches[0]


def _read_bounded_file(path: Path, *, max_bytes: int, read_error: type[DriftPlanningError], limit_error: type[DriftPlanningError], subject: Any) -> bytes:
    st = _lstat_or_none(path)
    if st is None or stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise read_error("expected a bounded local regular file", subject=subject)
    if st.st_size > max_bytes:
        raise limit_error("bounded byte limit exceeded", subject=subject, expected=max_bytes, actual=st.st_size)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise read_error("bounded local regular file could not be read", subject=subject) from exc
    if len(raw) > max_bytes:
        raise limit_error("bounded byte limit exceeded", subject=subject, expected=max_bytes, actual=len(raw))
    return raw


# ---------------------------------------------------------------------------
# Strict, duplicate-safe, finite, canonical JSON parsing.
# ---------------------------------------------------------------------------


def _strict_json_object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant: {token}")


def _strict_json_loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_strict_json_object_pairs_hook, parse_constant=_reject_json_constant)


def _measure_json_structure(value: Any, *, max_nodes: int, max_depth: int) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise ValueError("JSON structure limit exceeded")
        if isinstance(current, dict):
            for item in current.values():
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            for item in current:
                stack.append((item, depth + 1))


def _read_strict_canonical_artifact(path: Path, *, max_bytes: int, subject: Any) -> tuple[dict[str, Any], bytes]:
    raw = _read_bounded_file(path, max_bytes=max_bytes, read_error=DriftArtifactReadError, limit_error=DriftArtifactLimitError, subject=subject)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise DriftArtifactEncodingError("V2-S2 artifact is not strict UTF-8 without a BOM", subject=subject)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DriftArtifactEncodingError("V2-S2 artifact is not strict UTF-8 without a BOM", subject=subject) from exc
    try:
        parsed = _strict_json_loads(text)
    except (ValueError, RecursionError) as exc:
        raise DriftArtifactJsonError("V2-S2 artifact is not one duplicate-safe finite JSON mapping", subject=subject) from exc
    if not isinstance(parsed, dict):
        raise DriftArtifactJsonError("V2-S2 artifact is not one duplicate-safe finite JSON mapping", subject=subject)
    try:
        _measure_json_structure(parsed, max_nodes=MAXIMUM_JSON_NODES, max_depth=MAXIMUM_JSON_DEPTH)
    except ValueError as exc:
        raise DriftArtifactLimitError("V2-S2 artifact exceeds a closed byte or structure limit", subject=subject) from exc
    recomputed = _canonical_json_bytes(parsed) + b"\n"
    if recomputed != raw:
        raise DriftArtifactCanonicalBytesError("V2-S2 artifact bytes are not canonical JSON with exactly one LF", subject=subject)
    return parsed, raw


# ---------------------------------------------------------------------------
# Materiality policy loading and closed-schema validation.
# ---------------------------------------------------------------------------


def _strict_yaml_loader() -> type[yaml.SafeLoader]:
    class _StrictLoader(yaml.SafeLoader):
        pass

    def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.nodes.ScalarNode) and key_node.value == "<<":
                raise yaml.constructor.ConstructorError("while constructing a mapping", key_node.start_mark, "merge key is not allowed", key_node.start_mark)
            key = loader.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise yaml.constructor.ConstructorError("while constructing a mapping", node.start_mark, "mapping keys must be strings", key_node.start_mark)
            if key in mapping:
                raise yaml.constructor.ConstructorError("while constructing a mapping", node.start_mark, f"duplicate key {key!r}", key_node.start_mark)
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
    return _StrictLoader


_POLICY_TOP_LEVEL_KEYS = {"schema", "policy_id", "policy_version", "policy_content_hash", "hash_basis", "approval_binding", "registry_binding", "artifact_binding", "evaluator", "rules"}
_POLICY_RULE_KEYS = {"priority", "rule_id", "rationale_id", "selectors", "outcome"}
_POLICY_SELECTOR_KEYS = {"classifications", "difference_kinds", "fact_kinds", "subject_types", "fact_path", "source_roles", "source_lifecycles", "consumer_freshness_profiles", "record_kinds"}
_POLICY_FACT_PATH_KEYS = {"mode", "values"}
_POLICY_OUTCOMES = {"NO_OBSERVED_CHANGE", "NON_MATERIAL_CHANGE", "MATERIAL_CHANGE"}
_POLICY_FACT_PATH_MODES = {"ANY", "EXACT", "PREFIX"}
_CONSUMER_FRESHNESS_PROFILES = {"NO_CONSUMERS", "NONE_REQUIRED", "SOME_REQUIRED", "ALL_REQUIRED"}


def _validate_selector_list(values: Any, *, allowed: set[str] | None, field_name: str) -> None:
    if not isinstance(values, list) or not values:
        raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject=field_name)
    if len(values) > 1 and "ANY" in values:
        raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject=field_name)
    for item in values:
        if not isinstance(item, str) or not item:
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject=field_name)
        if allowed is not None and item != "ANY" and item not in allowed:
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject=field_name, expected=sorted(allowed | {"ANY"}), actual=item)


def _validate_policy_schema(parsed: dict[str, Any]) -> None:
    if set(parsed.keys()) != _POLICY_TOP_LEVEL_KEYS:
        raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="<policy>", expected=sorted(_POLICY_TOP_LEVEL_KEYS), actual=sorted(parsed.keys()))
    for key in ("schema", "policy_id", "policy_version", "policy_content_hash", "hash_basis"):
        value = parsed[key]
        if not isinstance(value, str) or not value or len(value) > 1024:
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject=key)
    if parsed["schema"] != POLICY_SCHEMA_ID or parsed["hash_basis"] != POLICY_HASH_BASIS:
        raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="schema")
    if not HASH_RE.fullmatch(parsed["policy_content_hash"]):
        raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="policy_content_hash")
    for key in ("approval_binding", "registry_binding", "artifact_binding", "evaluator"):
        if not isinstance(parsed[key], dict):
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject=key)

    rules = parsed["rules"]
    if not isinstance(rules, list) or not (1 <= len(rules) <= MAXIMUM_POLICY_RULES):
        raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules")

    priorities: list[int] = []
    rule_ids: list[str] = []
    rationale_ids: list[str] = []
    for row in rules:
        if not isinstance(row, dict) or set(row.keys()) != _POLICY_RULE_KEYS:
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[]")
        priority = row["priority"]
        if not isinstance(priority, int) or isinstance(priority, bool) or not (0 <= priority <= 9999):
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].priority")
        rule_id = row["rule_id"]
        rationale_id = row["rationale_id"]
        if not isinstance(rule_id, str) or not rule_id or len(rule_id) > 128:
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].rule_id")
        if not isinstance(rationale_id, str) or not rationale_id or len(rationale_id) > 128:
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].rationale_id")
        if row["outcome"] not in _POLICY_OUTCOMES:
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].outcome")
        selectors = row["selectors"]
        if not isinstance(selectors, dict) or set(selectors.keys()) != _POLICY_SELECTOR_KEYS:
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].selectors")
        _validate_selector_list(selectors["classifications"], allowed=set(ALLOWED_CLASSIFICATIONS), field_name="rules[].selectors.classifications")
        _validate_selector_list(selectors["difference_kinds"], allowed=set(ALLOWED_DIFFERENCE_KINDS), field_name="rules[].selectors.difference_kinds")
        _validate_selector_list(selectors["fact_kinds"], allowed=set(ALLOWED_FACT_KINDS), field_name="rules[].selectors.fact_kinds")
        _validate_selector_list(selectors["subject_types"], allowed=set(ALLOWED_SUBJECT_TYPES), field_name="rules[].selectors.subject_types")
        _validate_selector_list(selectors["source_roles"], allowed=None, field_name="rules[].selectors.source_roles")
        _validate_selector_list(selectors["source_lifecycles"], allowed=set(ALLOWED_SOURCE_LIFECYCLES), field_name="rules[].selectors.source_lifecycles")
        _validate_selector_list(selectors["consumer_freshness_profiles"], allowed=_CONSUMER_FRESHNESS_PROFILES, field_name="rules[].selectors.consumer_freshness_profiles")
        _validate_selector_list(selectors["record_kinds"], allowed=set(ALLOWED_RECORD_KINDS), field_name="rules[].selectors.record_kinds")
        fact_path = selectors["fact_path"]
        if not isinstance(fact_path, dict) or set(fact_path.keys()) != _POLICY_FACT_PATH_KEYS:
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].selectors.fact_path")
        mode = fact_path["mode"]
        values = fact_path["values"]
        if mode not in _POLICY_FACT_PATH_MODES or not isinstance(values, list):
            raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].selectors.fact_path.mode")
        if mode == "ANY":
            if values:
                raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].selectors.fact_path.values")
        else:
            if not values or any((not isinstance(item, str)) or item == "ANY" for item in values):
                raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].selectors.fact_path.values")
            if len(set(values)) != len(values):
                raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].selectors.fact_path.values")
            if mode == "PREFIX" and any(not item.endswith("/") for item in values):
                raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject="rules[].selectors.fact_path.values")
        priorities.append(priority)
        rule_ids.append(rule_id.casefold())
        rationale_ids.append(rationale_id.casefold())

    if priorities != sorted(priorities) or len(set(priorities)) != len(priorities):
        raise DriftPolicyAmbiguityError("fixed materiality policy contains ambiguous, duplicate, or unordered rules", subject="rules[].priority")
    if len(set(rule_ids)) != len(rule_ids):
        raise DriftPolicyAmbiguityError("fixed materiality policy contains ambiguous, duplicate, or unordered rules", subject="rules[].rule_id")
    if len(set(rationale_ids)) != len(rationale_ids):
        raise DriftPolicyAmbiguityError("fixed materiality policy contains ambiguous, duplicate, or unordered rules", subject="rules[].rationale_id")


def _build_materiality_rule(row: dict[str, Any]) -> MaterialityRule:
    selectors = row["selectors"]
    fact_path = selectors["fact_path"]
    return MaterialityRule(
        priority=row["priority"],
        rule_id=row["rule_id"],
        rationale_id=row["rationale_id"],
        selectors=MaterialitySelectors(
            classifications=tuple(selectors["classifications"]),
            difference_kinds=tuple(selectors["difference_kinds"]),
            fact_kinds=tuple(selectors["fact_kinds"]),
            subject_types=tuple(selectors["subject_types"]),
            fact_path=FactPathSelector(mode=fact_path["mode"], values=tuple(fact_path["values"])),
            source_roles=tuple(selectors["source_roles"]),
            source_lifecycles=tuple(selectors["source_lifecycles"]),
            consumer_freshness_profiles=tuple(selectors["consumer_freshness_profiles"]),
            record_kinds=tuple(selectors["record_kinds"]),
        ),
        outcome=row["outcome"],
    )


def load_materiality_policy() -> MaterialityPolicy:
    """Load and validate only the fixed production materiality policy.

    Reads ``configs/sourceops/materiality_policy.yaml`` (no override is
    accepted anywhere) as a bounded, no-follow, regular UTF-8 file; parses it
    with a strict duplicate-key-free YAML loader; validates its closed
    schema; and requires its self-excluding hash to match the declared
    ``policy_content_hash``. Registry-hash binding is cross-checked by the
    caller once the current registry is known (see ``plan_drift``).
    """
    path = REPO_ROOT / MATERIALITY_POLICY_REL
    read_failed = "fixed materiality policy could not be read as a bounded local regular file"
    _assert_no_reparse_ancestors(path.parent, root=REPO_ROOT, error=DriftPolicyReadError, message=read_failed)
    st = _lstat_or_none(path)
    if st is None or stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise DriftPolicyReadError(read_failed, subject=MATERIALITY_POLICY_REL)
    if st.st_size > MATERIALITY_POLICY_BYTES:
        raise DriftPolicyReadError(read_failed, subject=MATERIALITY_POLICY_REL, expected=MATERIALITY_POLICY_BYTES, actual=st.st_size)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DriftPolicyReadError(read_failed, subject=MATERIALITY_POLICY_REL) from exc
    if len(raw) > MATERIALITY_POLICY_BYTES:
        raise DriftPolicyReadError(read_failed, subject=MATERIALITY_POLICY_REL, expected=MATERIALITY_POLICY_BYTES, actual=len(raw))
    if raw.startswith(b"\xef\xbb\xbf"):
        raise DriftPolicyEncodingError("fixed materiality policy is not strict UTF-8", subject=MATERIALITY_POLICY_REL)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DriftPolicyEncodingError("fixed materiality policy is not strict UTF-8", subject=MATERIALITY_POLICY_REL) from exc

    try:
        parsed = yaml.load(text, Loader=_strict_yaml_loader())
    except yaml.YAMLError as exc:
        raise DriftPolicyYamlError("fixed materiality policy is not one safe duplicate-free YAML mapping", subject=MATERIALITY_POLICY_REL) from exc
    if not isinstance(parsed, dict):
        raise DriftPolicyYamlError("fixed materiality policy is not one safe duplicate-free YAML mapping", subject=MATERIALITY_POLICY_REL)
    try:
        _measure_json_structure(parsed, max_nodes=MAXIMUM_POLICY_NODES, max_depth=MAXIMUM_POLICY_DEPTH)
    except ValueError as exc:
        raise DriftPolicySchemaError("fixed materiality policy violates its closed schema", subject=MATERIALITY_POLICY_REL) from exc

    _validate_policy_schema(parsed)

    declared_hash = parsed["policy_content_hash"]
    recomputed_hash = _self_excluding_hash(parsed, "policy_content_hash")
    if declared_hash != recomputed_hash:
        raise DriftPolicyHashMismatch("fixed materiality policy self-hash does not match its canonical mapping", subject="policy_content_hash", expected=recomputed_hash, actual=declared_hash)

    approval_binding = parsed["approval_binding"]
    if approval_binding.get("mode") != "HUMAN_ADJUDICATED_EXACT_HASH":
        raise DriftPolicyBindingMismatch("fixed materiality policy does not bind the current registry or V2-S2 schemas", subject="approval_binding.mode")
    artifact_binding = parsed["artifact_binding"]
    if (
        artifact_binding.get("diff_schema") != DIFF_SCHEMA_ID
        or artifact_binding.get("diff_hash_basis") != DIFF_HASH_BASIS
        or artifact_binding.get("verification_schema") != VERIFICATION_SCHEMA_ID
        or artifact_binding.get("verification_hash_basis") != VERIFICATION_HASH_BASIS
    ):
        raise DriftPolicyBindingMismatch("fixed materiality policy does not bind the current registry or V2-S2 schemas", subject="artifact_binding")
    registry_binding = parsed["registry_binding"]
    if registry_binding.get("schema") != REGISTRY_SCHEMA_ID:
        raise DriftPolicyBindingMismatch("fixed materiality policy does not bind the current registry or V2-S2 schemas", subject="registry_binding.schema")

    rules = tuple(_build_materiality_rule(row) for row in parsed["rules"])

    return MaterialityPolicy(
        schema=parsed["schema"],
        policy_id=parsed["policy_id"],
        policy_version=parsed["policy_version"],
        policy_content_hash=parsed["policy_content_hash"],
        hash_basis=parsed["hash_basis"],
        approval_binding=freeze_json(approval_binding),
        registry_binding=freeze_json(registry_binding),
        artifact_binding=freeze_json(artifact_binding),
        evaluator=freeze_json(parsed["evaluator"]),
        rules=rules,
        raw_mapping=freeze_json(parsed),
    )


# ---------------------------------------------------------------------------
# Current V2-S1 registry and per-source baseline preconditions.
# ---------------------------------------------------------------------------


def _registry_raw_mapping(registry: Registry) -> dict[str, Any]:
    raw = getattr(registry, "_raw_mapping", None)
    return dict(raw) if raw is not None else registry.as_dict()


def _find_raw_source_record(registry_dict: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    for row in registry_dict.get("source_records", []):
        if isinstance(row, dict) and row.get("source_id") == source_id:
            return row
    return None


def _load_and_validate_current_registry() -> tuple[Registry, dict[str, Any]]:
    registry_path = REPO_ROOT / CANONICAL_REGISTRY_REL
    invalid_msg = "current V2-S1 registry is invalid"
    st = _lstat_or_none(registry_path)
    if st is None or stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise DriftBaselineRegistryError(invalid_msg, subject=CANONICAL_REGISTRY_REL)
    if st.st_size > REGISTRY_BYTES:
        raise DriftBaselineRegistryError(invalid_msg, subject=CANONICAL_REGISTRY_REL, expected=REGISTRY_BYTES, actual=st.st_size)
    try:
        registry = load_registry(registry_path)
    except (SourceOpsError, OSError) as exc:
        raise DriftBaselineRegistryError(invalid_msg, subject=CANONICAL_REGISTRY_REL) from exc
    result = validate_registry(registry, repo_root=REPO_ROOT)
    if not result.registry_valid:
        codes = {item.code for item in result.errors}
        if codes & {"DECLARATION_DRIFT", "DECLARATION_REFERENCE_INVALID"}:
            raise DriftBaselineDeclarationError("current V2-S1 declaration or preservation precondition is invalid", subject=CANONICAL_REGISTRY_REL)
        raise DriftBaselineRegistryError(invalid_msg, subject=CANONICAL_REGISTRY_REL)
    return registry, _registry_raw_mapping(registry)


def _validate_safe_repo_relative_string(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("path must be a string")
    normalized = raw.replace("\\", "/").strip()
    if not normalized:
        raise ValueError("empty path")
    if normalized.startswith("file://") or normalized.startswith("/") or normalized.startswith("//"):
        raise ValueError("absolute or uri path")
    if re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError("drive path")
    if any(part == ".." for part in normalized.split("/")):
        raise ValueError("traversal path")
    if "//" in normalized or normalized.startswith("./"):
        raise ValueError("unsafe path")
    if "\x00" in normalized or any(ord(ch) < 32 for ch in normalized):
        raise ValueError("control chars")
    if len(normalized) > 240 or len(normalized.split("/")) > 12:
        raise ValueError("path too long")
    return normalized


def _has_unsafe_ancestor(path: Path, *, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        st = _lstat_or_none(current)
        if st is None:
            break
        if stat.S_ISLNK(st.st_mode):
            return True
    return False


def _validate_safe_repo_relative_path_no_follow(raw: Any) -> str:
    normalized = _validate_safe_repo_relative_string(raw)
    if _has_unsafe_ancestor(REPO_ROOT / normalized, root=REPO_ROOT):
        raise ValueError("path resolves through a link")
    return normalized


_BASELINE_ACTION_MSG = "current source actions, approval flag, consumer edges, or reserved boundary are invalid"


def _validate_action_and_consumer_preconditions(source_record: Any, registry: Registry) -> None:
    actions = list(source_record.drift_policy.actions)
    casefolded = [item.casefold() for item in actions]
    if len(set(casefolded)) != len(casefolded):
        raise DriftBaselineActionPolicyError(_BASELINE_ACTION_MSG, subject=source_record.source_id, expected="unique", actual=actions)
    unknown = [item for item in actions if item not in ALLOWED_ACTIONS_IN_ORDER]
    if unknown:
        raise DriftBaselineActionPolicyError(_BASELINE_ACTION_MSG, subject=source_record.source_id, expected=list(ALLOWED_ACTIONS_IN_ORDER), actual=unknown)
    expected_relative_order = [item for item in ALLOWED_ACTIONS_IN_ORDER if item in actions]
    if actions != expected_relative_order:
        raise DriftBaselineActionPolicyError(_BASELINE_ACTION_MSG, subject=source_record.source_id, expected=expected_relative_order, actual=actions)
    if source_record.drift_policy.approval_required is not True:
        raise DriftBaselineActionPolicyError(_BASELINE_ACTION_MSG, subject=source_record.source_id)

    consumers = list(source_record.consumers)
    casefolded_consumers = [item.casefold() for item in consumers]
    if len(set(casefolded_consumers)) != len(casefolded_consumers):
        raise DriftBaselineActionPolicyError(_BASELINE_ACTION_MSG, subject=source_record.source_id)
    reserved_hits = [item for item in consumers if item in RESERVED_CONSUMER_IDS]
    if reserved_hits:
        raise DriftBaselineActionPolicyError(_BASELINE_ACTION_MSG, subject=source_record.source_id, actual=reserved_hits)
    consumer_by_id = {item.consumer_id: item for item in registry.consumers}
    for consumer_id in consumers:
        consumer = consumer_by_id.get(consumer_id)
        if consumer is None:
            raise DriftBaselineActionPolicyError(_BASELINE_ACTION_MSG, subject=consumer_id)
        if source_record.source_id not in consumer.required_sources:
            raise DriftBaselineActionPolicyError(_BASELINE_ACTION_MSG, subject=consumer_id)


_LINEAGE_MSG = "current rollback predecessor lineage is not a valid immutable chain"


def _validate_lineage_precondition(source_record: Any, registry: Registry) -> None:
    rollback = source_record.rollback
    if rollback.immutable_predecessor_required is not True:
        raise DriftLineageError(_LINEAGE_MSG, subject=source_record.source_id)
    if rollback.predecessor_source_id is None:
        try:
            _validate_safe_repo_relative_path_no_follow(rollback.rollback_artifact)
        except ValueError as exc:
            raise DriftLineageError(_LINEAGE_MSG, subject=source_record.source_id) from exc
        return
    by_id = {item.source_id: item for item in registry.source_records}
    seen: set[str] = set()
    current = source_record
    cap = len(registry.source_records) + 1
    steps = 0
    while current.rollback.predecessor_source_id is not None:
        steps += 1
        if steps > cap:
            raise DriftLineageError(_LINEAGE_MSG, subject=source_record.source_id)
        predecessor_id = current.rollback.predecessor_source_id
        if predecessor_id == current.source_id or predecessor_id in seen:
            raise DriftLineageError(_LINEAGE_MSG, subject=source_record.source_id)
        predecessor = by_id.get(predecessor_id)
        if predecessor is None:
            raise DriftLineageError(_LINEAGE_MSG, subject=predecessor_id)
        if predecessor.lifecycle_state not in {"VERIFIED_ACTIVE", "PINNED_HISTORICAL"}:
            raise DriftLineageError(_LINEAGE_MSG, subject=predecessor_id)
        if predecessor.rollback.immutable_predecessor_required is not True:
            raise DriftLineageError(_LINEAGE_MSG, subject=predecessor_id)
        if predecessor.authoritative_locator != current.authoritative_locator:
            raise DriftLineageError(_LINEAGE_MSG, subject=predecessor_id)
        seen.add(predecessor_id)
        current = predecessor


def _validate_source_baseline(pair: V2S2ArtifactPair, registry: Registry, registry_dict: dict[str, Any]) -> Any:
    source_record = next((item for item in registry.source_records if item.source_id == pair.source_id), None)
    if source_record is None:
        raise DriftUnknownSourceError("V2-S2 source_id is not present in the current valid registry", subject=pair.source_id)

    if registry_dict.get("registry_content_hash") != pair.registry_content_hash:
        raise DriftBaselineBindingMismatch(
            "V2-S2 source, registry, record, or declaration binding is stale or mismatched",
            subject=pair.source_id,
            expected=registry_dict.get("registry_content_hash"),
            actual=pair.registry_content_hash,
        )

    raw_record = _find_raw_source_record(registry_dict, pair.source_id)
    if raw_record is None:
        raise DriftUnknownSourceError("V2-S2 source_id is not present in the current valid registry", subject=pair.source_id)

    pair_source_binding = thaw_json(pair.diff)["source_binding"]
    if pair_source_binding["declaration_refs"] != raw_record.get("declaration_refs"):
        raise DriftBaselineBindingMismatch(
            "V2-S2 source, registry, record, or declaration binding is stale or mismatched",
            subject=pair.source_id,
            expected=raw_record.get("declaration_refs"),
            actual=pair_source_binding["declaration_refs"],
        )
    recomputed_record_hash = _sha256_hex(_canonical_json_bytes(raw_record))
    if pair_source_binding.get("source_record_content_hash") != recomputed_record_hash:
        raise DriftBaselineBindingMismatch(
            "V2-S2 source, registry, record, or declaration binding is stale or mismatched",
            subject=pair.source_id,
            expected=recomputed_record_hash,
            actual=pair_source_binding.get("source_record_content_hash"),
        )

    _validate_action_and_consumer_preconditions(source_record, registry)
    _validate_lineage_precondition(source_record, registry)
    return source_record


# ---------------------------------------------------------------------------
# Fact-universe structural validation.
# ---------------------------------------------------------------------------


_FACT_INVARIANT_MSG = "V2-S2 fact, summary, ordering, classification, provenance, or baseline invariant is invalid"


def _validate_source_fact_universe_shape(facts: tuple[DiffFact, ...]) -> None:
    counts: dict[str, int] = {}
    for fact in facts:
        if fact.subject_type == "SOURCE":
            counts[fact.fact_path] = counts.get(fact.fact_path, 0) + 1
    bad = [path for path in REQUIRED_SOURCE_FACT_PATHS if counts.get(path, 0) != 1]
    if bad:
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=bad[0], expected="exactly_one", actual=counts.get(bad[0], 0))
    for fact in facts:
        if fact.subject_type != "SOURCE":
            continue
        before = thaw_json(fact.before)
        after = thaw_json(fact.after)
        if before.get("present") is not True or after.get("present") is not True:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
        provenance = thaw_json(fact.provenance)
        if provenance.get("baseline_origin") != "REGISTRY_SOURCE_RECORD" or provenance.get("candidate_origin") != "MANIFEST_CANDIDATE":
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
    for fact in facts:
        if fact.fact_path.startswith("/content-bindings/") and fact.subject_type not in {"FILE", "COMPONENT", "DECLARATION"}:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)


def _validate_facts_match_current_source(facts: tuple[DiffFact, ...], current_source: dict[str, Any]) -> None:
    release = current_source.get("release") or {}
    licence = current_source.get("licence") or {}
    acquisition = current_source.get("acquisition") or {}
    pointer_map = {
        "/identity/display_name": current_source.get("display_name"),
        "/identity/record_kind": current_source.get("record_kind"),
        "/identity/owner": current_source.get("owner"),
        "/identity/authoritative_locator": current_source.get("authoritative_locator"),
        "/release/version_or_snapshot": release.get("version_or_snapshot"),
        "/release/release_date": release.get("release_date"),
        "/release/retrieved_at": release.get("retrieved_at"),
        "/release/content_pin_status": release.get("content_pin_status"),
        "/licence/status": licence.get("status"),
        "/licence/identifier_or_family": licence.get("identifier_or_family"),
        "/licence/terms_locator": licence.get("terms_locator"),
        "/licence/permitted_use": licence.get("permitted_use"),
        "/licence/redistribution": licence.get("redistribution"),
        "/licence/cloud_egress": licence.get("cloud_egress"),
        "/licence/verification_basis": licence.get("verification_basis"),
        "/acquisition/method": acquisition.get("method"),
        "/acquisition/operator_contract": acquisition.get("operator_contract"),
        "/acquisition/writes_outside_repository": acquisition.get("writes_outside_repository"),
    }
    for fact in facts:
        if fact.subject_type != "SOURCE" or fact.fact_path not in pointer_map:
            continue
        expected = pointer_map[fact.fact_path]
        before_value = thaw_json(fact.before).get("value")
        if _canonical_json_bytes(before_value) != _canonical_json_bytes(expected):
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected=expected, actual=before_value)


_COMPONENT_FACT_PATH_PREFIX = "/components/"
_COMPONENT_REQUIRED_FIELDS = ("display_name", "source_role", "version_or_snapshot", "licence_status", "declaration_locator")
_COMPONENT_AGGREGATE_KEYS = frozenset(_COMPONENT_REQUIRED_FIELDS)
_CONTENT_BASELINE_SUBJECT_TYPE = {
    "REGISTRY_DECLARATION_REF": "DECLARATION",
    "REGISTRY_COMPONENT": "COMPONENT",
    "ABSENT": "FILE",
}


def _has_checksum_role(source_role: Any) -> bool:
    if not isinstance(source_role, str):
        return False
    return any(token.casefold() == "checksum" for token in re.split(r"[-_\s]+", source_role) if token)


def _escape_rfc6901(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _content_binding_locator(fact_path: str) -> tuple[str, str] | None:
    """Splits a ``/content-bindings/<binding_id>[/sha256]`` fact path.

    Returns ``(binding_id, "sha256")`` or ``(binding_id, "value")``, or
    ``None`` when ``fact_path`` is not a content-binding path at all.
    """
    prefix = "/content-bindings/"
    if not fact_path.startswith(prefix):
        return None
    remainder = fact_path[len(prefix):]
    if remainder.endswith("/sha256"):
        binding_id = remainder[: -len("/sha256")]
        return (binding_id, "sha256") if binding_id else None
    return (remainder, "value") if remainder else None


def _validate_content_fact_universe(facts: tuple[DiffFact, ...], current_source: dict[str, Any], verification_files: list[dict[str, Any]]) -> None:
    """Independently recompute and cross-check every content-binding fact.

    Every ``before`` value is cross-checked against the current registry's
    own declaration_refs/components -- never trusted from the diff itself --
    and every ``after`` value is cross-checked against the verification
    artifact's independently observed ``input_tree.files`` -- never trusted
    from the diff alone either. A forged, omitted, duplicated, or
    unrecognised baseline/candidate target fails closed here.
    """
    declaration_hash_by_path = {
        ref.get("path"): ref.get("canonical_lf_sha256")
        for ref in (current_source.get("declaration_refs") or [])
        if isinstance(ref, dict)
    }
    component_by_id = {
        comp.get("component_id"): comp
        for comp in (current_source.get("components") or [])
        if isinstance(comp, dict) and isinstance(comp.get("component_id"), str)
    }
    files_by_id = {row.get("file_id"): row for row in verification_files if isinstance(row, dict)}
    files_by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in verification_files:
        if isinstance(row, dict) and isinstance(row.get("content_sha256"), str):
            files_by_hash.setdefault(row["content_sha256"], []).append(row)
    match_count_by_file_id = {file_id: 0 for file_id in files_by_id if isinstance(file_id, str)}
    seen_baseline_targets: set[tuple[str, str]] = set()

    for fact in facts:
        located = _content_binding_locator(fact.fact_path)
        if located is None:
            continue
        binding_id, variant = located
        if not FILE_IDENTIFIER_RE.fullmatch(binding_id):
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)

        before = thaw_json(fact.before)
        after = thaw_json(fact.after)
        provenance = thaw_json(fact.provenance)
        baseline_origin = provenance.get("baseline_origin")
        candidate_origin = provenance.get("candidate_origin")
        if fact.subject_type != _CONTENT_BASELINE_SUBJECT_TYPE.get(baseline_origin):
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)

        if baseline_origin == "REGISTRY_DECLARATION_REF":
            if fact.subject_id not in declaration_hash_by_path:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected="known declaration_ref path", actual=fact.subject_id)
            target_key = (baseline_origin, fact.subject_id)
            if target_key in seen_baseline_targets:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected="unique baseline target", actual=fact.subject_id)
            seen_baseline_targets.add(target_key)
            baseline_hash = declaration_hash_by_path[fact.subject_id]
            if before.get("present") is not True:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
            expected_before = baseline_hash if variant == "sha256" else {"baseline_kind": "DECLARATION_REF", "baseline_id": fact.subject_id, "checksum_mode": "CANONICAL_LF_TEXT", "content_sha256": baseline_hash}
            if _canonical_json_bytes(before.get("value")) != _canonical_json_bytes(expected_before):
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected=expected_before, actual=before.get("value"))
        elif baseline_origin == "REGISTRY_COMPONENT":
            component = component_by_id.get(fact.subject_id)
            if component is None:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected="known component_id", actual=fact.subject_id)
            if not _has_checksum_role(component.get("source_role")):
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
            target_key = (baseline_origin, fact.subject_id)
            if target_key in seen_baseline_targets:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected="unique baseline target", actual=fact.subject_id)
            seen_baseline_targets.add(target_key)
            component_hash = component.get("version_or_snapshot")
            if before.get("present") is not True:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
            expected_before = component_hash if variant == "sha256" else {"baseline_kind": "COMPONENT_CHECKSUM", "baseline_id": fact.subject_id, "checksum_mode": "RAW_BYTES", "content_sha256": component_hash}
            if _canonical_json_bytes(before.get("value")) != _canonical_json_bytes(expected_before):
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected=expected_before, actual=before.get("value"))
        elif baseline_origin == "ABSENT":
            if before.get("present") is not False or before.get("value") is not None:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
        else:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)

        if candidate_origin == "STAGED_FILE_OBSERVATION":
            if after.get("present") is not True:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
            after_value = after.get("value")
            if variant == "sha256":
                if not isinstance(after_value, str):
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
                observed_candidates = files_by_hash.get(after_value, [])
                if not observed_candidates:
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected="an observed input-tree file", actual=after_value)
                matched_file = observed_candidates[0]
            else:
                if not isinstance(after_value, dict):
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
                matched_file = files_by_id.get(after_value.get("file_id"))
                if matched_file is None:
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected="known input-tree file_id", actual=after_value.get("file_id"))
                observed = {
                    "file_id": matched_file.get("file_id"),
                    "role": matched_file.get("role"),
                    "media_type": matched_file.get("media_type"),
                    "checksum_mode": matched_file.get("checksum_mode"),
                    "content_byte_size": matched_file.get("content_byte_size"),
                    "content_sha256": matched_file.get("content_sha256"),
                }
                if _canonical_json_bytes(after_value) != _canonical_json_bytes(observed):
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected=observed, actual=after_value)
            file_id = matched_file.get("file_id")
            if file_id not in match_count_by_file_id:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
            match_count_by_file_id[file_id] += 1
        elif candidate_origin == "ABSENT":
            if after.get("present") is not False or after.get("value") is not None:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
        else:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)

    for file_id, count in match_count_by_file_id.items():
        if count != 1:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=file_id, expected="exactly_one_content_fact", actual=count)


def _validate_component_fact_universe(
    facts: tuple[DiffFact, ...],
    current_source: dict[str, Any],
    component_projection_status: Any,
) -> None:
    """Independently recompute and cross-check every component-projection fact.

    Selects only true ``/components/<id>`` or ``/components/<id>/<field>``
    projection facts (per the V2-S2 component projection contract) -- never
    every ``subject_type == "COMPONENT"`` fact. A ``COMPONENT_CHECKSUM``
    content-binding fact also carries ``subject_type == "COMPONENT"`` but
    lives under ``/content-bindings/...``; that fact belongs exclusively to
    ``_validate_content_fact_universe`` and must never be considered,
    double-validated, or rejected here. ``NOT_PROVIDED`` requires zero
    ``/components/...`` projection facts. ``COMPLETE``
    requires the exact current/candidate component universe: every current
    baseline component must be represented (no silent omissions), every
    ``before`` value is cross-checked against the current registry (never
    trusted from the diff). Per the amended authority, a projected component
    id is never required to appear in
    ``verification.input_tree.files[*].component_ids`` (or in a content
    binding): V2-S2 permits an explicit empty ``component_ids`` list, and
    file anchoring is not a precondition of a COMPLETE projection. An
    uncorroborated or unfamiliar candidate component value that otherwise
    matches this closed structural shape is a valid observed fact; it is
    handed off to the materiality policy (changed/added/removed component
    facts are material under the component rule or the conservative
    terminal default), never rejected here for lacking a file anchor.
    """
    component_facts = tuple(
        fact
        for fact in facts
        if fact.subject_type == "COMPONENT" and fact.fact_path.startswith(_COMPONENT_FACT_PATH_PREFIX)
    )
    if component_projection_status == "NOT_PROVIDED":
        if component_facts:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject="component_projection_status", expected=0, actual=len(component_facts))
        return
    if component_projection_status != "COMPLETE":
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject="component_projection_status")

    registry_components = {
        comp.get("component_id"): comp
        for comp in (current_source.get("components") or [])
        if isinstance(comp, dict) and isinstance(comp.get("component_id"), str)
    }
    by_subject: dict[str, list[DiffFact]] = {}
    for fact in component_facts:
        by_subject.setdefault(fact.subject_id, []).append(fact)

    for component_id in sorted(set(registry_components) | set(by_subject)):
        group = by_subject.get(component_id)
        if not group:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=component_id, expected="represented component", actual=None)

        escaped = _escape_rfc6901(component_id)
        aggregate_path = f"{_COMPONENT_FACT_PATH_PREFIX}{escaped}"
        field_paths = {f"{aggregate_path}/{field}": field for field in _COMPONENT_REQUIRED_FIELDS}
        for fact in group:
            if fact.fact_path != aggregate_path and fact.fact_path not in field_paths:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)

        registry_component = registry_components.get(component_id)

        if len(group) == 1 and group[0].fact_path == aggregate_path:
            fact = group[0]
            before = thaw_json(fact.before)
            after = thaw_json(fact.after)
            if before.get("present") is True and after.get("present") is False:
                if registry_component is None:
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
                value = before.get("value")
                if not isinstance(value, dict) or set(value.keys()) != _COMPONENT_AGGREGATE_KEYS:
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
                expected = {field: registry_component.get(field) for field in _COMPONENT_REQUIRED_FIELDS}
                if _canonical_json_bytes(value) != _canonical_json_bytes(expected):
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected=expected, actual=value)
            elif before.get("present") is False and after.get("present") is True:
                if registry_component is not None:
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
                value = after.get("value")
                if not isinstance(value, dict) or set(value.keys()) != _COMPONENT_AGGREGATE_KEYS:
                    raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
            else:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
            continue

        if len(group) != 5 or {fact.fact_path for fact in group} != set(field_paths):
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=component_id, expected=sorted(field_paths), actual=sorted(fact.fact_path for fact in group))
        if registry_component is None:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=component_id, expected="known component_id", actual=component_id)
        for fact in group:
            field = field_paths[fact.fact_path]
            before = thaw_json(fact.before)
            after = thaw_json(fact.after)
            if before.get("present") is not True or after.get("present") is not True:
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path)
            expected_before = registry_component.get(field)
            if _canonical_json_bytes(before.get("value")) != _canonical_json_bytes(expected_before):
                raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=fact.fact_path, expected=expected_before, actual=before.get("value"))


def _validate_content_and_component_fact_universe(pair: V2S2ArtifactPair, current_source: dict[str, Any]) -> None:
    verification = thaw_json(pair.verification)
    verification_files = verification["input_tree"]["files"]
    _validate_content_fact_universe(pair.facts, current_source, verification_files)
    _validate_component_fact_universe(pair.facts, current_source, verification.get("component_projection_status"))


# ---------------------------------------------------------------------------
# V2-S2 artifact pair discovery, strict validation, and typed fact building.
# ---------------------------------------------------------------------------

_VERIFICATION_TOP_LEVEL_KEYS = {
    "schema", "artifact_content_hash", "hash_basis", "manifest_content_hash", "observed_at",
    "source_binding", "candidate_snapshot_id", "component_projection_status", "input_tree",
    "checks", "stage_outcome", "diff_artifact_content_hash", "validation_ceiling",
}
_DIFF_TOP_LEVEL_KEYS = {
    "schema", "artifact_content_hash", "hash_basis", "manifest_content_hash", "observed_at",
    "source_binding", "candidate_snapshot_id", "input_tree_content_hash", "component_projection_status",
    "stage_outcome", "summary", "facts", "validation_ceiling",
}
_SOURCE_BINDING_KEYS = {"source_id", "registry_content_hash", "source_record_content_hash", "declaration_refs"}
_DIFF_FACT_KEYS = {"difference_kind", "fact_kind", "subject_type", "subject_id", "fact_path", "classification", "before", "after", "provenance"}
_FACT_ENVELOPE_KEYS = {"present", "value"}
_PROVENANCE_KEYS = {"baseline_origin", "candidate_origin"}
_SUMMARY_KEYS = {"total_facts", "classifications", "difference_kinds", "fact_kinds"}
_INPUT_TREE_KEYS = {"hash_basis", "input_tree_content_hash", "files", "total_bound_content_bytes"}
_STAGE_OUTCOMES = {"OBSERVED_NO_DIFFERENCE", "OBSERVED_DIFFERENCE"}


def _require_exact_keys(mapping: Any, required: set[str], *, error: type[DriftPlanningError], message: str, subject: str) -> dict[str, Any]:
    if not isinstance(mapping, dict) or set(mapping.keys()) != required:
        actual = sorted(mapping.keys()) if isinstance(mapping, dict) else type(mapping).__name__
        raise error(message, subject=subject, expected=sorted(required), actual=actual)
    return mapping


def _recompute_fact_classification(fact_row: dict[str, Any], *, subject: str) -> str:
    before = fact_row.get("before")
    after = fact_row.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
    before_present = before.get("present")
    after_present = after.get("present")
    if not isinstance(before_present, bool) or not isinstance(after_present, bool):
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
    if not before_present and before.get("value") is not None:
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
    if not after_present and after.get("value") is not None:
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
    if not before_present and not after_present:
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
    if not before_present and after_present:
        return "ADDED"
    if before_present and not after_present:
        return "REMOVED"
    before_bytes = _canonical_json_bytes(before.get("value"))
    after_bytes = _canonical_json_bytes(after.get("value"))
    return "UNCHANGED" if before_bytes == after_bytes else "CHANGED"


def _fact_sort_key(fact_row: dict[str, Any]) -> tuple[int, int, int, str, str]:
    return (
        DIFFERENCE_KIND_ORDER.get(fact_row.get("difference_kind"), 999),
        FACT_KIND_ORDER.get(fact_row.get("fact_kind"), 999),
        SUBJECT_TYPE_ORDER.get(fact_row.get("subject_type"), 999),
        fact_row.get("subject_id", ""),
        fact_row.get("fact_path", ""),
    )


def _validate_and_build_facts(diff_dict: dict[str, Any]) -> tuple[DiffFact, ...]:
    facts_raw = diff_dict.get("facts")
    if not isinstance(facts_raw, list) or not (1 <= len(facts_raw) <= MAXIMUM_DIFF_FACTS):
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject="facts")

    seen_keys: set[tuple[str, str, str, str, str]] = set()
    recomputed_counts = {name: 0 for name in ALLOWED_CLASSIFICATIONS}
    recomputed_diff_kind = {name: 0 for name in ALLOWED_DIFFERENCE_KINDS}
    recomputed_fact_kind = {name: 0 for name in ALLOWED_FACT_KINDS}
    built: list[DiffFact] = []
    previous_sort_key: tuple[int, int, int, str, str] | None = None

    for index, row in enumerate(facts_raw):
        subject = f"facts[{index}]"
        if not isinstance(row, dict) or set(row.keys()) != _DIFF_FACT_KEYS:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
        if row["difference_kind"] not in ALLOWED_DIFFERENCE_KINDS or row["fact_kind"] not in ALLOWED_FACT_KINDS or row["subject_type"] not in ALLOWED_SUBJECT_TYPES:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
        if not isinstance(row["subject_id"], str) or not row["subject_id"]:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
        if not isinstance(row["fact_path"], str) or not row["fact_path"]:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
        before = _require_exact_keys(row["before"], _FACT_ENVELOPE_KEYS, error=DriftFactInvariantError, message=_FACT_INVARIANT_MSG, subject=f"{subject}.before")
        after = _require_exact_keys(row["after"], _FACT_ENVELOPE_KEYS, error=DriftFactInvariantError, message=_FACT_INVARIANT_MSG, subject=f"{subject}.after")
        provenance = _require_exact_keys(row["provenance"], _PROVENANCE_KEYS, error=DriftFactInvariantError, message=_FACT_INVARIANT_MSG, subject=f"{subject}.provenance")
        if provenance["baseline_origin"] not in ALLOWED_BASELINE_ORIGINS or provenance["candidate_origin"] not in ALLOWED_CANDIDATE_ORIGINS:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=f"{subject}.provenance")

        recomputed = _recompute_fact_classification(row, subject=subject)
        if row["classification"] not in ALLOWED_CLASSIFICATIONS or row["classification"] != recomputed:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject, expected=recomputed, actual=row.get("classification"))

        key = (row["difference_kind"], row["fact_kind"], row["subject_type"], row["subject_id"], row["fact_path"])
        if key in seen_keys:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject)
        seen_keys.add(key)

        sort_key = _fact_sort_key(row)
        if previous_sort_key is not None and sort_key < previous_sort_key:
            raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject=subject, expected="ascending_order")
        previous_sort_key = sort_key

        recomputed_counts[recomputed] += 1
        recomputed_diff_kind[row["difference_kind"]] += 1
        recomputed_fact_kind[row["fact_kind"]] += 1

        fact_id = "fact-" + _sha256_hex(_canonical_json_bytes(row))
        built.append(
            DiffFact(
                difference_kind=row["difference_kind"],
                fact_kind=row["fact_kind"],
                subject_type=row["subject_type"],
                subject_id=row["subject_id"],
                fact_path=row["fact_path"],
                classification=row["classification"],
                before=freeze_json(before),
                after=freeze_json(after),
                provenance=freeze_json(provenance),
                fact_id=fact_id,
                fact_index=index,
            )
        )

    summary = _require_exact_keys(diff_dict.get("summary"), _SUMMARY_KEYS, error=DriftFactInvariantError, message=_FACT_INVARIANT_MSG, subject="summary")
    if summary.get("total_facts") != len(facts_raw):
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject="summary.total_facts", expected=len(facts_raw), actual=summary.get("total_facts"))
    if summary.get("classifications") != recomputed_counts:
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject="summary.classifications", expected=recomputed_counts, actual=summary.get("classifications"))
    if summary.get("difference_kinds") != recomputed_diff_kind:
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject="summary.difference_kinds", expected=recomputed_diff_kind, actual=summary.get("difference_kinds"))
    if summary.get("fact_kinds") != recomputed_fact_kind:
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject="summary.fact_kinds", expected=recomputed_fact_kind, actual=summary.get("fact_kinds"))

    derived_stage_outcome = "OBSERVED_NO_DIFFERENCE" if recomputed_counts["UNCHANGED"] == len(facts_raw) else "OBSERVED_DIFFERENCE"
    if diff_dict.get("stage_outcome") != derived_stage_outcome:
        raise DriftFactInvariantError(_FACT_INVARIANT_MSG, subject="stage_outcome", expected=derived_stage_outcome, actual=diff_dict.get("stage_outcome"))

    return tuple(built)


def load_v2_s2_artifact_pair(manifest_content_hash: str) -> V2S2ArtifactPair:
    """Discover and independently validate only the fixed final V2-S2 leaf.

    No path override is accepted: the leaf is always derived from
    ``.raptor/sourceops/generated/staged-snapshots/<manifest_content_hash>``.
    """
    if not isinstance(manifest_content_hash, str) or not HASH_RE.fullmatch(manifest_content_hash):
        raise DriftInputLeafError("V2-S2 input leaf is outside the fixed safe generated boundary", subject="manifest_content_hash")

    verification_path, diff_path = _discover_v2s2_pair(manifest_content_hash)

    verification, _ = _read_strict_canonical_artifact(verification_path, max_bytes=VERIFICATION_ARTIFACT_BYTES, subject=_canonical_path_subject(verification_path, root=REPO_ROOT))
    _require_exact_keys(verification, _VERIFICATION_TOP_LEVEL_KEYS, error=DriftVerificationSchemaError, message="V2-S2 verification artifact violates its closed schema", subject="verification")
    if verification.get("schema") != VERIFICATION_SCHEMA_ID or verification.get("hash_basis") != VERIFICATION_HASH_BASIS:
        raise DriftVerificationSchemaError("V2-S2 verification artifact violates its closed schema", subject="verification.schema")
    if verification.get("stage_outcome") not in _STAGE_OUTCOMES:
        raise DriftVerificationSchemaError("V2-S2 verification artifact violates its closed schema", subject="verification.stage_outcome")
    _require_exact_keys(verification.get("source_binding"), _SOURCE_BINDING_KEYS, error=DriftVerificationSchemaError, message="V2-S2 verification artifact violates its closed schema", subject="verification.source_binding")
    input_tree = _require_exact_keys(verification.get("input_tree"), _INPUT_TREE_KEYS, error=DriftVerificationSchemaError, message="V2-S2 verification artifact violates its closed schema", subject="verification.input_tree")

    declared_v_hash = verification.get("artifact_content_hash")
    recomputed_v_hash = _self_excluding_hash(verification, "artifact_content_hash")
    if not isinstance(declared_v_hash, str) or declared_v_hash != recomputed_v_hash:
        raise DriftArtifactHashMismatch("V2-S2 artifact self-hash does not match its canonical mapping", subject="verification.artifact_content_hash", expected=recomputed_v_hash, actual=declared_v_hash)
    if verification_path.name != f"v-{declared_v_hash}.json":
        raise DriftArtifactFilenameHashMismatch("V2-S2 artifact filename does not match its declared content hash", subject=_canonical_path_subject(verification_path, root=REPO_ROOT), expected=f"v-{declared_v_hash}.json", actual=verification_path.name)

    diff, _ = _read_strict_canonical_artifact(diff_path, max_bytes=DIFF_ARTIFACT_BYTES, subject=_canonical_path_subject(diff_path, root=REPO_ROOT))
    _require_exact_keys(diff, _DIFF_TOP_LEVEL_KEYS, error=DriftDiffSchemaError, message="V2-S2 diff artifact violates its closed schema", subject="diff")
    if diff.get("schema") != DIFF_SCHEMA_ID or diff.get("hash_basis") != DIFF_HASH_BASIS:
        raise DriftDiffSchemaError("V2-S2 diff artifact violates its closed schema", subject="diff.schema")
    if diff.get("stage_outcome") not in _STAGE_OUTCOMES:
        raise DriftDiffSchemaError("V2-S2 diff artifact violates its closed schema", subject="diff.stage_outcome")
    diff_source_binding = _require_exact_keys(diff.get("source_binding"), _SOURCE_BINDING_KEYS, error=DriftDiffSchemaError, message="V2-S2 diff artifact violates its closed schema", subject="diff.source_binding")

    declared_d_hash = diff.get("artifact_content_hash")
    recomputed_d_hash = _self_excluding_hash(diff, "artifact_content_hash")
    if not isinstance(declared_d_hash, str) or declared_d_hash != recomputed_d_hash:
        raise DriftArtifactHashMismatch("V2-S2 artifact self-hash does not match its canonical mapping", subject="diff.artifact_content_hash", expected=recomputed_d_hash, actual=declared_d_hash)
    if diff_path.name != f"d-{declared_d_hash}.json":
        raise DriftArtifactFilenameHashMismatch("V2-S2 artifact filename does not match its declared content hash", subject=_canonical_path_subject(diff_path, root=REPO_ROOT), expected=f"d-{declared_d_hash}.json", actual=diff_path.name)

    cross_binding_msg = "V2-S2 diff and verification artifacts do not bind the same observation"
    for key in ("manifest_content_hash", "observed_at", "source_binding", "candidate_snapshot_id", "component_projection_status", "stage_outcome"):
        if verification.get(key) != diff.get(key):
            raise DriftArtifactCrossBindingMismatch(cross_binding_msg, subject=key, expected=verification.get(key), actual=diff.get(key))
    if verification.get("diff_artifact_content_hash") != declared_d_hash:
        raise DriftArtifactCrossBindingMismatch(cross_binding_msg, subject="diff_artifact_content_hash", expected=declared_d_hash, actual=verification.get("diff_artifact_content_hash"))
    if verification.get("manifest_content_hash") != manifest_content_hash:
        raise DriftArtifactCrossBindingMismatch(cross_binding_msg, subject="manifest_content_hash", expected=manifest_content_hash, actual=verification.get("manifest_content_hash"))

    files = input_tree.get("files")
    if not isinstance(files, list) or not files:
        raise DriftInputTreeHashMismatch("V2-S2 input-tree hash or summary does not recompute", subject="input_tree.files")
    recomputed_tree_hash = _sha256_hex(_canonical_json_bytes(files))
    if input_tree.get("input_tree_content_hash") != recomputed_tree_hash:
        raise DriftInputTreeHashMismatch("V2-S2 input-tree hash or summary does not recompute", subject="input_tree.input_tree_content_hash", expected=recomputed_tree_hash, actual=input_tree.get("input_tree_content_hash"))
    if diff.get("input_tree_content_hash") != recomputed_tree_hash:
        raise DriftInputTreeHashMismatch("V2-S2 input-tree hash or summary does not recompute", subject="diff.input_tree_content_hash", expected=recomputed_tree_hash, actual=diff.get("input_tree_content_hash"))
    try:
        recomputed_total_bytes = sum(int(item["content_byte_size"]) for item in files)
    except (KeyError, TypeError, ValueError) as exc:
        raise DriftInputTreeHashMismatch("V2-S2 input-tree hash or summary does not recompute", subject="input_tree.files") from exc
    if input_tree.get("total_bound_content_bytes") != recomputed_total_bytes:
        raise DriftInputTreeHashMismatch("V2-S2 input-tree hash or summary does not recompute", subject="input_tree.total_bound_content_bytes", expected=recomputed_total_bytes, actual=input_tree.get("total_bound_content_bytes"))

    facts = _validate_and_build_facts(diff)
    _validate_source_fact_universe_shape(facts)

    pair = V2S2ArtifactPair(
        manifest_content_hash=manifest_content_hash,
        source_id=diff_source_binding["source_id"],
        observed_at=diff["observed_at"],
        registry_content_hash=diff_source_binding["registry_content_hash"],
        verification=freeze_json(verification),
        diff=freeze_json(diff),
        verification_ref=V2S2ArtifactRef(path=_canonical_path_subject(verification_path, root=REPO_ROOT), content_hash=declared_v_hash, schema=VERIFICATION_SCHEMA_ID),
        diff_ref=V2S2ArtifactRef(path=_canonical_path_subject(diff_path, root=REPO_ROOT), content_hash=declared_d_hash, schema=DIFF_SCHEMA_ID),
        facts=facts,
        stage_outcome=diff["stage_outcome"],
    )

    # Independently cross-check every content-binding and component-projection
    # fact against the current production registry's source record right here
    # -- not only later inside plan_drift -- so a forged content or component
    # baseline (for example a COMPONENT_CHECKSUM value) is rejected by this
    # loader alone, before evaluate_materiality or any other caller ever
    # consumes the pair. When the current registry cannot resolve this exact
    # source_id, that is an unknown-source condition for the caller
    # (plan_drift/evaluate_materiality) to report -- never a fabricated
    # fact-invariant failure manufactured here from an absent baseline.
    _, current_registry_dict = _load_and_validate_current_registry()
    current_raw_record = _find_raw_source_record(current_registry_dict, pair.source_id)
    if current_raw_record is not None:
        _validate_content_and_component_fact_universe(pair, current_raw_record)

    return pair


# ---------------------------------------------------------------------------
# Materiality evaluation.
# ---------------------------------------------------------------------------


def _consumer_freshness_profile(source_record: Any, registry: Registry) -> str:
    consumer_ids = list(source_record.consumers)
    if not consumer_ids:
        return "NO_CONSUMERS"
    consumer_by_id = {item.consumer_id: item for item in registry.consumers}
    flags = [consumer_by_id[cid].freshness_required for cid in consumer_ids if cid in consumer_by_id]
    if flags and all(flags):
        return "ALL_REQUIRED"
    if flags and not any(flags):
        return "NONE_REQUIRED"
    return "SOME_REQUIRED"


def _derive_source_role(fact: DiffFact, source_record: Any) -> str:
    if fact.subject_type == "SOURCE":
        return "SOURCE_RECORD"
    after = thaw_json(fact.after)
    before = thaw_json(fact.before)
    if fact.subject_type == "DECLARATION":
        role = None
        for ref in source_record.declaration_refs:
            if ref.path == fact.subject_id or ref.role == fact.subject_id:
                role = ref.role
                break
        if role is None and isinstance(after.get("value"), dict):
            role = after["value"].get("role")
        return f"DECLARATION_REF:{role or 'unknown'}"
    if fact.subject_type == "COMPONENT":
        role = None
        for component in source_record.components:
            if component.component_id == fact.subject_id:
                role = component.source_role
                break
        if role is None and isinstance(after.get("value"), dict):
            role = after["value"].get("source_role")
        if role is None and isinstance(before.get("value"), dict):
            role = before["value"].get("source_role")
        return f"COMPONENT:{role or 'unknown'}"
    if fact.subject_type == "FILE":
        role = None
        if isinstance(after.get("value"), dict):
            role = after["value"].get("role")
        return f"STAGED_FILE:{role or 'unknown'}"
    return "UNKNOWN"


def _selector_matches_list(value: str, selector_values: tuple[str, ...]) -> bool:
    if selector_values == ("ANY",):
        return True
    return value in selector_values


def _selector_matches_fact_path(fact_path: str, selector: FactPathSelector) -> bool:
    if selector.mode == "ANY":
        return True
    if selector.mode == "EXACT":
        return fact_path in selector.values
    if selector.mode == "PREFIX":
        return any(fact_path.startswith(prefix) for prefix in selector.values)
    return False


def _match_rule(rule: MaterialityRule, *, classification: str, difference_kind: str, fact_kind: str, subject_type: str, fact_path: str, source_role: str, source_lifecycle: str, consumer_freshness_profile: str, record_kind: str) -> bool:
    selectors = rule.selectors
    return (
        _selector_matches_list(classification, selectors.classifications)
        and _selector_matches_list(difference_kind, selectors.difference_kinds)
        and _selector_matches_list(fact_kind, selectors.fact_kinds)
        and _selector_matches_list(subject_type, selectors.subject_types)
        and _selector_matches_fact_path(fact_path, selectors.fact_path)
        and _selector_matches_list(source_role, selectors.source_roles)
        and _selector_matches_list(source_lifecycle, selectors.source_lifecycles)
        and _selector_matches_list(consumer_freshness_profile, selectors.consumer_freshness_profiles)
        and _selector_matches_list(record_kind, selectors.record_kinds)
    )


def evaluate_materiality(pair: V2S2ArtifactPair, registry: Registry, policy: MaterialityPolicy) -> MaterialityAssessment:
    """Pure, deterministic per-fact policy evaluation with no filesystem mutation."""
    source_record = next((item for item in registry.source_records if item.source_id == pair.source_id), None)
    if source_record is None:
        raise DriftUnknownSourceError("V2-S2 source_id is not present in the current valid registry", subject=pair.source_id)

    freshness_profile = _consumer_freshness_profile(source_record, registry)
    ordered_rules = sorted(policy.rules, key=lambda rule: rule.priority)

    evaluations: list[FactEvaluation] = []
    counts = {"NO_OBSERVED_CHANGE": 0, "NON_MATERIAL_CHANGE": 0, "MATERIAL_CHANGE": 0}
    for fact in pair.facts:
        if fact.classification not in ALLOWED_CLASSIFICATIONS:
            raise DriftMaterialityEvaluationError("materiality evaluation did not produce one closed result per valid fact", subject=fact.fact_id)
        source_role = _derive_source_role(fact, source_record)
        matched = next(
            (
                rule
                for rule in ordered_rules
                if _match_rule(
                    rule,
                    classification=fact.classification,
                    difference_kind=fact.difference_kind,
                    fact_kind=fact.fact_kind,
                    subject_type=fact.subject_type,
                    fact_path=fact.fact_path,
                    source_role=source_role,
                    source_lifecycle=source_record.lifecycle_state,
                    consumer_freshness_profile=freshness_profile,
                    record_kind=source_record.record_kind,
                )
            ),
            None,
        )
        if matched is not None:
            outcome, rule_id, rationale_id = matched.outcome, matched.rule_id, matched.rationale_id
            conservative_default = rationale_id == "CONSERVATIVE_DEFAULT"
        else:
            outcome = "MATERIAL_CHANGE"
            rule_id = str(policy.evaluator.get("conservative_unmatched_rule_id", "SYSTEM-UNMATCHED-MATERIAL-001"))
            rationale_id = "CONSERVATIVE_DEFAULT"
            conservative_default = True

        counts[outcome] += 1
        evaluations.append(
            FactEvaluation(
                fact_id=fact.fact_id,
                fact_index=fact.fact_index,
                fact_locator=freeze_json(fact.locator()),
                context=freeze_json(
                    {
                        "source_role": source_role,
                        "source_lifecycle": source_record.lifecycle_state,
                        "consumer_freshness_profile": freshness_profile,
                        "record_kind": source_record.record_kind,
                    }
                ),
                evaluation=outcome,
                rule_id=rule_id,
                rationale_id=rationale_id,
                conservative_default=conservative_default,
            )
        )

    if counts["MATERIAL_CHANGE"] > 0:
        aggregate = "MATERIAL_CHANGE"
    elif counts["NON_MATERIAL_CHANGE"] > 0:
        aggregate = "NON_MATERIAL_CHANGE"
    else:
        aggregate = "NO_OBSERVED_CHANGE"

    expected_stage_outcome = "OBSERVED_NO_DIFFERENCE" if aggregate == "NO_OBSERVED_CHANGE" else "OBSERVED_DIFFERENCE"
    if pair.stage_outcome != expected_stage_outcome:
        raise DriftMaterialityEvaluationError("materiality evaluation did not produce one closed result per valid fact", subject="stage_outcome", expected=expected_stage_outcome, actual=pair.stage_outcome)

    rule_id_order: list[str] = []
    for rule in ordered_rules:
        if rule.rule_id not in rule_id_order:
            rule_id_order.append(rule.rule_id)
    conservative_id = policy.evaluator.get("conservative_unmatched_rule_id")
    if isinstance(conservative_id, str) and conservative_id not in rule_id_order:
        rule_id_order.append(conservative_id)

    full_counts = {"total_facts": len(pair.facts), **counts}
    return MaterialityAssessment(
        outcome=aggregate,
        counts=freeze_json(full_counts),
        evaluations=tuple(evaluations),
        source_id=pair.source_id,
        rule_id_priority_order=tuple(rule_id_order),
    )


# ---------------------------------------------------------------------------
# Read-only rollback rehearsal.
# ---------------------------------------------------------------------------


def _path_ancestor_relation(first: str, second: str) -> bool:
    if not first or not second:
        return False
    left = first.strip("/").split("/")
    right = second.strip("/").split("/")
    if len(left) <= len(right):
        return right[: len(left)] == left
    return left[: len(right)] == right


_ROLLBACK_ARTIFACT_TOP_LEVEL_KEYS = {
    "schema", "artifact_content_hash", "hash_basis", "rollback_source_record_binding_hash_basis", "current_source_id",
    "current_rollback_source_record_binding_hash", "predecessor_source_id", "predecessor_rollback_source_record_binding_hash",
    "current_declaration_refs", "predecessor_declaration_refs", "file_bindings", "preservation_bindings",
}
_ROLLBACK_FILE_BINDING_KEYS = {
    "binding_id", "predecessor_path", "predecessor_content_byte_size", "predecessor_canonical_lf_sha256",
    "current_path", "current_content_byte_size", "current_canonical_lf_sha256",
}
_ROLLBACK_PRESERVATION_BINDING_KEYS = {"rule_id", "path", "content_byte_size", "canonical_lf_sha256"}
_ROLLBACK_INTEGRITY_CHECK_NAMES = (
    "CURRENT_SOURCE_BINDING", "PREDECESSOR_SOURCE_BINDING", "LINEAGE_ACYCLIC", "ROLLBACK_PATH_SAFE",
    "ROLLBACK_ARTIFACT_PRESENT", "ROLLBACK_ARTIFACT_HASH_MATCH", "ROLLBACK_ARTIFACT_BINDINGS_MATCH",
    "CURRENT_FILES_MATCH", "PREDECESSOR_FILES_MATCH", "PRESERVATION_BINDINGS_MATCH",
    "PRESERVATION_TARGETS_CLEAR", "INPUTS_IMMUTABLE",
)
# Every rehearsal outcome (BLOCKED or READY) reports these 12 checks through
# real, per-call execution tracking in ``_rehearse_non_null_rollback``
# (see ``check_status`` there): each check starts NOT_APPLICABLE and is only
# ever set to PASS or FAIL once it has genuinely executed, in whatever order
# it actually runs -- never derived from this tuple's fixed reporting-order
# position. That real tracking is what lets ``PRESERVATION_TARGETS_CLEAR``
# (which genuinely executes ahead of ``CURRENT_FILES_MATCH``,
# ``PREDECESSOR_FILES_MATCH``, and ``PRESERVATION_BINDINGS_MATCH``, even
# though it is reported after them) always report exactly what it actually
# did, with no special-cased vector required.


def _rollback_source_record_binding_hash(raw_source_record: dict[str, Any]) -> str:
    """Compute the non-cyclic ``rollback_source_record_binding_hash.v1`` for one raw source record.

    Deep-copies the complete validated raw source-record mapping and
    replaces only ``rollback.rollback_artifact`` with the fixed sentinel;
    removes no key and transforms no other value; preserves every sequence
    and explicit null exactly; then hashes the canonical UTF-8 bytes (sorted
    keys, compact separators, ``ensure_ascii=False``, ``allow_nan=False``,
    no trailing LF). Because the transformed bytes never depend on the
    rollback artifact's own path, this hash is stable across reassigning
    that path to its final content-addressed value -- the property that
    makes a non-null rollback artifact's own filename hash constructable
    without a cryptographic fixpoint.
    """
    transformed = copy.deepcopy(raw_source_record)
    rollback = transformed.get("rollback")
    if not isinstance(rollback, dict) or "rollback_artifact" not in rollback:
        raise DriftBaselineBindingMismatch(
            "V2-S2 source, registry, record, or declaration binding is stale or mismatched",
            subject=raw_source_record.get("source_id"),
        )
    rollback["rollback_artifact"] = ROLLBACK_SOURCE_RECORD_BINDING_SENTINEL
    return _sha256_hex(_canonical_json_bytes(transformed))


def _build_rollback_lineage(source_record: Any, registry: Registry, registry_dict: dict[str, Any]) -> dict[str, Any]:
    """Build the ``lineage`` mapping shared by every rehearsal outcome.

    Walks the current source's predecessor chain -- current source first,
    then each predecessor, ending at the null-predecessor root -- and
    independently recomputes, for every visited record, both its full raw
    source-record content hash and its normalized rollback source-record
    binding hash directly from the current registry; neither is ever
    trusted from a stored or declared value. A missing record or a cycle is
    a baseline defect (never a rollback blocker) and raises the matching
    typed error.
    """
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    walker = source_record
    cap = len(registry.source_records) + 1
    while True:
        if len(chain) > cap:
            raise DriftLineageError(_LINEAGE_MSG, subject=source_record.source_id)
        walker_raw = _find_raw_source_record(registry_dict, walker.source_id)
        if walker_raw is None:
            raise DriftBaselineBindingMismatch(
                "V2-S2 source, registry, record, or declaration binding is stale or mismatched",
                subject=walker.source_id,
            )
        chain.append(
            {
                "source_id": walker.source_id,
                "source_record_content_hash": _sha256_hex(_canonical_json_bytes(walker_raw)),
                "rollback_source_record_binding_hash": _rollback_source_record_binding_hash(walker_raw),
            }
        )
        seen.add(walker.source_id)
        next_id = walker.rollback.predecessor_source_id
        if next_id is None:
            break
        next_walker = next((item for item in registry.source_records if item.source_id == next_id), None)
        if next_walker is None or next_id in seen:
            raise DriftLineageError(_LINEAGE_MSG, subject=next_id)
        walker = next_walker

    current_entry = chain[0]
    predecessor_id = source_record.rollback.predecessor_source_id
    if predecessor_id is None:
        return {
            "status": "NO_PREDECESSOR",
            "rollback_source_record_binding_hash_basis": ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS,
            "current_source_id": source_record.source_id,
            "current_source_record_content_hash": current_entry["source_record_content_hash"],
            "current_rollback_source_record_binding_hash": current_entry["rollback_source_record_binding_hash"],
            "current_declaration_refs": [item.as_dict() for item in source_record.declaration_refs],
            "predecessor_source_id": None,
            "predecessor_source_record_content_hash": None,
            "predecessor_rollback_source_record_binding_hash": None,
            "predecessor_declaration_refs": [],
            "chain": chain,
        }

    predecessor_entry = chain[1]
    predecessor = next(item for item in registry.source_records if item.source_id == predecessor_id)
    return {
        "status": "PREDECESSOR_PRESENT",
        "rollback_source_record_binding_hash_basis": ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS,
        "current_source_id": source_record.source_id,
        "current_source_record_content_hash": current_entry["source_record_content_hash"],
        "current_rollback_source_record_binding_hash": current_entry["rollback_source_record_binding_hash"],
        "current_declaration_refs": [item.as_dict() for item in source_record.declaration_refs],
        "predecessor_source_id": predecessor_id,
        "predecessor_source_record_content_hash": predecessor_entry["source_record_content_hash"],
        "predecessor_rollback_source_record_binding_hash": predecessor_entry["rollback_source_record_binding_hash"],
        "predecessor_declaration_refs": [item.as_dict() for item in predecessor.declaration_refs],
        "chain": chain,
    }


def _rehearse_non_null_rollback(source_record: Any, registry: Registry, registry_dict: dict[str, Any]) -> RollbackRehearsal:
    # Independently re-validate the current-source binding and predecessor
    # lineage here, even though the full plan-drift pipeline already
    # validates both earlier: ``rehearse_rollback`` is a required public
    # function that a caller may invoke directly (bypassing that earlier
    # validation), so CURRENT_SOURCE_BINDING/PREDECESSOR_SOURCE_BINDING/
    # LINEAGE_ACYCLIC must never be reported PASS on trust alone. A failure
    # here is a baseline defect, never a rollback blocker: it raises the
    # matching typed error (exit 5) instead of a BLOCKED rehearsal.
    _validate_lineage_precondition(source_record, registry)
    predecessor_id = source_record.rollback.predecessor_source_id
    predecessor = next(item for item in registry.source_records if item.source_id == predecessor_id)
    lineage = _build_rollback_lineage(source_record, registry, registry_dict)
    current_binding_hash = lineage["current_rollback_source_record_binding_hash"]
    predecessor_binding_hash = lineage["predecessor_rollback_source_record_binding_hash"]

    # Populated as each becomes genuinely established below. A blocker fired
    # before a given assignment always reports its conservative default
    # (None/empty), so only a safe path, a hash-validated artifact, and
    # fully content-validated bindings are ever echoed back to the caller.
    safe_path: str | None = None
    validated_hash: str | None = None
    validated_file_bindings: tuple[RollbackFileBinding, ...] = ()
    validated_preservation_bindings: tuple[PreservationBinding, ...] = ()

    # Actual per-check execution state, keyed by check name. Every check
    # starts NOT_APPLICABLE (never reached yet); a check is set to PASS only
    # at the point it has genuinely executed and succeeded, and to FAIL only
    # at the point it has genuinely executed and failed. ``_status_checks``
    # always reports these 12 in the fixed canonical order of
    # ``_ROLLBACK_INTEGRITY_CHECK_NAMES`` regardless of the order they were
    # actually set in, so a check that genuinely runs out of its canonical
    # reporting order (PRESERVATION_TARGETS_CLEAR runs ahead of
    # CURRENT_FILES_MATCH/PREDECESSOR_FILES_MATCH/PRESERVATION_BINDINGS_MATCH)
    # is always reported exactly as it actually executed -- never derived
    # from a fixed index.
    check_status: dict[str, str] = {name: "NOT_APPLICABLE" for name in _ROLLBACK_INTEGRITY_CHECK_NAMES}
    # CURRENT_SOURCE_BINDING, PREDECESSOR_SOURCE_BINDING, and LINEAGE_ACYCLIC
    # have already genuinely executed and passed above: any failure there
    # raises a typed baseline exception and never reaches this point at all.
    check_status["CURRENT_SOURCE_BINDING"] = "PASS"
    check_status["PREDECESSOR_SOURCE_BINDING"] = "PASS"
    check_status["LINEAGE_ACYCLIC"] = "PASS"

    def _status_checks() -> tuple[RollbackIntegrityCheck, ...]:
        return tuple(RollbackIntegrityCheck(check=name, status=check_status[name]) for name in _ROLLBACK_INTEGRITY_CHECK_NAMES)

    def _blocked(code: str, *, subject: Any = None, expected: Any = None, actual: Any = None, failed_check: str) -> RollbackRehearsal:
        check_status[failed_check] = "FAIL"
        return RollbackRehearsal(
            outcome="BLOCKED",
            reason_code=code,
            blocker=RollbackBlocker(code=code, phase="ROLLBACK", subject=subject, expected=expected, actual=actual),
            rollback_route_eligible=False,
            proposed_operations=(),
            lineage=freeze_json(lineage),
            # ROLLBACK_PATH_INVALID must never echo any path value, safe or
            # not; every other blocker fires only after the path is already
            # confirmed safe, so it is reported back.
            rollback_artifact_registry_path=None if code == "ROLLBACK_PATH_INVALID" else safe_path,
            rollback_artifact_status="BLOCKED",
            rollback_artifact_content_hash=validated_hash,
            rollback_file_bindings=validated_file_bindings,
            rollback_preservation_bindings=validated_preservation_bindings,
            integrity_checks=_status_checks(),
        )

    try:
        safe_path = _validate_safe_repo_relative_path_no_follow(source_record.rollback.rollback_artifact)
    except ValueError:
        return _blocked("ROLLBACK_PATH_INVALID", subject=source_record.source_id, failed_check="ROLLBACK_PATH_SAFE")
    safe_path_obj = Path(safe_path)
    if safe_path_obj.parent.as_posix() != "configs/sourceops/rollbacks" or not ROLLBACK_ARTIFACT_FILENAME_RE.fullmatch(safe_path_obj.name):
        return _blocked("ROLLBACK_PATH_INVALID", subject=safe_path, failed_check="ROLLBACK_PATH_SAFE")
    check_status["ROLLBACK_PATH_SAFE"] = "PASS"

    artifact_path = REPO_ROOT / safe_path
    st = _lstat_or_none(artifact_path)
    if st is None:
        return _blocked("ROLLBACK_ARTIFACT_MISSING", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_PRESENT")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        return _blocked("ROLLBACK_ARTIFACT_TYPE_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_PRESENT")
    if st.st_size > ROLLBACK_ARTIFACT_BYTES:
        return _blocked("ROLLBACK_ARTIFACT_LIMIT_EXCEEDED", subject=safe_path, expected=ROLLBACK_ARTIFACT_BYTES, actual=st.st_size, failed_check="ROLLBACK_ARTIFACT_PRESENT")
    check_status["ROLLBACK_ARTIFACT_PRESENT"] = "PASS"

    try:
        raw = artifact_path.read_bytes()
    except OSError:
        return _blocked("ROLLBACK_ARTIFACT_READ_FAILED", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    if len(raw) > ROLLBACK_ARTIFACT_BYTES:
        return _blocked("ROLLBACK_ARTIFACT_LIMIT_EXCEEDED", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    if raw.startswith(b"\xef\xbb\xbf"):
        return _blocked("ROLLBACK_ARTIFACT_ENCODING_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _blocked("ROLLBACK_ARTIFACT_ENCODING_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    try:
        parsed = _strict_json_loads(text)
    except (ValueError, RecursionError):
        return _blocked("ROLLBACK_ARTIFACT_JSON_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    if not isinstance(parsed, dict):
        return _blocked("ROLLBACK_ARTIFACT_JSON_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    try:
        _measure_json_structure(parsed, max_nodes=MAXIMUM_JSON_NODES, max_depth=MAXIMUM_JSON_DEPTH)
    except ValueError:
        return _blocked("ROLLBACK_ARTIFACT_LIMIT_EXCEEDED", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    if _canonical_json_bytes(parsed) + b"\n" != raw:
        return _blocked("ROLLBACK_ARTIFACT_CANONICAL_BYTES_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    if set(parsed.keys()) != _ROLLBACK_ARTIFACT_TOP_LEVEL_KEYS:
        return _blocked("ROLLBACK_ARTIFACT_SCHEMA_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    if parsed.get("schema") != ROLLBACK_ARTIFACT_SCHEMA_ID or parsed.get("hash_basis") != ROLLBACK_ARTIFACT_HASH_BASIS:
        return _blocked("ROLLBACK_ARTIFACT_SCHEMA_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    file_bindings_raw = parsed.get("file_bindings")
    preservation_bindings_raw = parsed.get("preservation_bindings")
    if not isinstance(file_bindings_raw, list) or len(file_bindings_raw) > MAXIMUM_ROLLBACK_FILE_BINDINGS or not isinstance(preservation_bindings_raw, list):
        return _blocked("ROLLBACK_ARTIFACT_SCHEMA_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    for row in file_bindings_raw:
        if not isinstance(row, dict) or set(row.keys()) != _ROLLBACK_FILE_BINDING_KEYS:
            return _blocked("ROLLBACK_ARTIFACT_SCHEMA_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    for row in preservation_bindings_raw:
        if not isinstance(row, dict) or set(row.keys()) != _ROLLBACK_PRESERVATION_BINDING_KEYS:
            return _blocked("ROLLBACK_ARTIFACT_SCHEMA_INVALID", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")

    declared_hash = parsed.get("artifact_content_hash")
    if not isinstance(declared_hash, str) or safe_path_obj.name != f"rb-{declared_hash}.json":
        return _blocked("ROLLBACK_ARTIFACT_FILENAME_HASH_MISMATCH", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    recomputed_hash = _self_excluding_hash(parsed, "artifact_content_hash")
    if declared_hash != recomputed_hash:
        return _blocked("ROLLBACK_ARTIFACT_HASH_MISMATCH", subject=safe_path, expected=recomputed_hash, actual=declared_hash, failed_check="ROLLBACK_ARTIFACT_HASH_MATCH")
    validated_hash = declared_hash
    check_status["ROLLBACK_ARTIFACT_HASH_MATCH"] = "PASS"

    if (
        parsed.get("rollback_source_record_binding_hash_basis") != ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS
        or parsed.get("current_source_id") != source_record.source_id
        or parsed.get("predecessor_source_id") != predecessor_id
        or parsed.get("current_rollback_source_record_binding_hash") != current_binding_hash
        or parsed.get("predecessor_rollback_source_record_binding_hash") != predecessor_binding_hash
        or parsed.get("current_declaration_refs") != lineage["current_declaration_refs"]
        or parsed.get("predecessor_declaration_refs") != lineage["predecessor_declaration_refs"]
    ):
        return _blocked("ROLLBACK_ARTIFACT_BINDING_MISMATCH", subject=safe_path, failed_check="ROLLBACK_ARTIFACT_BINDINGS_MATCH")
    check_status["ROLLBACK_ARTIFACT_BINDINGS_MATCH"] = "PASS"

    # Safety gate: never process a file binding's restoration target any
    # further -- not even to check whether it is the *correct* declaration
    # path -- once it is known to overlap a preservation-protected path.
    # This runs ahead of the structural/content file-binding checks below so
    # a preservation conflict can never be masked or reclassified by them
    # (the amended authority requires preservation overlap to be evaluated
    # only by this dedicated check, never implied by another rule's shape).
    # It genuinely executes here, before CURRENT_FILES_MATCH,
    # PREDECESSOR_FILES_MATCH, and PRESERVATION_BINDINGS_MATCH, even though
    # PRESERVATION_TARGETS_CLEAR is reported after them below.
    preservation_paths = [item.path for item in registry.preservation_rules]
    for row in file_bindings_raw:
        target = row.get("current_path")
        if isinstance(target, str):
            for preserved in preservation_paths:
                if target == preserved or _path_ancestor_relation(target, preserved):
                    return _blocked("ROLLBACK_PRESERVATION_CONFLICT", subject=target, failed_check="PRESERVATION_TARGETS_CLEAR")
    check_status["PRESERVATION_TARGETS_CLEAR"] = "PASS"

    binding_ids = [row["binding_id"] for row in file_bindings_raw]
    # binding_id must be exactly the ASCII "bind-" prefix plus its own
    # 1-based sequence position, zero-padded to three decimal digits -- the
    # sole construction algorithm the authority and every fixture use.
    # Checking equality against this canonical sequence enforces uniqueness
    # and strict ascending order as one exact rule, and (unlike a bare
    # self-sort/uniqueness check) still rejects a single out-of-pattern
    # binding_id even when only one file binding is present.
    expected_binding_ids = [f"bind-{position:03d}" for position in range(1, len(binding_ids) + 1)]
    if binding_ids != expected_binding_ids:
        return _blocked("ROLLBACK_FILE_BINDING_INVALID", subject=safe_path, failed_check="CURRENT_FILES_MATCH")
    current_paths = {ref.path for ref in source_record.declaration_refs}
    predecessor_paths = {ref.path for ref in predecessor.declaration_refs}
    bound_current_paths = {row["current_path"] for row in file_bindings_raw}
    bound_predecessor_paths = {row["predecessor_path"] for row in file_bindings_raw}
    if bound_current_paths != current_paths or bound_predecessor_paths != predecessor_paths or len(current_paths) != len(predecessor_paths):
        return _blocked("ROLLBACK_FILE_BINDING_INVALID", subject=safe_path, failed_check="CURRENT_FILES_MATCH")
    declaration_hash_by_path = {ref.path: ref.canonical_lf_sha256 for ref in source_record.declaration_refs}
    predecessor_hash_by_path = {ref.path: ref.canonical_lf_sha256 for ref in predecessor.declaration_refs}
    for row in file_bindings_raw:
        if (
            row.get("current_canonical_lf_sha256") != declaration_hash_by_path.get(row.get("current_path"))
            or row.get("predecessor_canonical_lf_sha256") != predecessor_hash_by_path.get(row.get("predecessor_path"))
            or not isinstance(row.get("current_content_byte_size"), int)
            or not isinstance(row.get("predecessor_content_byte_size"), int)
            or row.get("current_content_byte_size") > DECLARATION_OR_PRESERVATION_FILE_BYTES
            or row.get("predecessor_content_byte_size") > ROLLBACK_BOUND_FILE_BYTES
        ):
            return _blocked("ROLLBACK_FILE_BINDING_INVALID", subject=safe_path, failed_check="CURRENT_FILES_MATCH")

    for row in file_bindings_raw:
        try:
            current_bytes = _canonical_lf_bytes((REPO_ROOT / row["current_path"]).read_bytes())
        except (OSError, UnicodeDecodeError):
            return _blocked("ROLLBACK_CURRENT_CONTENT_MISMATCH", subject=row["current_path"], failed_check="CURRENT_FILES_MATCH")
        if len(current_bytes) != row["current_content_byte_size"] or _sha256_hex(current_bytes) != row["current_canonical_lf_sha256"]:
            return _blocked("ROLLBACK_CURRENT_CONTENT_MISMATCH", subject=row["current_path"], failed_check="CURRENT_FILES_MATCH")
    check_status["CURRENT_FILES_MATCH"] = "PASS"

    for row in file_bindings_raw:
        try:
            predecessor_bytes = _canonical_lf_bytes((REPO_ROOT / row["predecessor_path"]).read_bytes())
        except (OSError, UnicodeDecodeError):
            return _blocked("ROLLBACK_PREDECESSOR_CONTENT_UNAVAILABLE", subject=row["predecessor_path"], failed_check="PREDECESSOR_FILES_MATCH")
        if len(predecessor_bytes) != row["predecessor_content_byte_size"] or _sha256_hex(predecessor_bytes) != row["predecessor_canonical_lf_sha256"]:
            return _blocked("ROLLBACK_PREDECESSOR_CONTENT_UNAVAILABLE", subject=row["predecessor_path"], failed_check="PREDECESSOR_FILES_MATCH")
    check_status["PREDECESSOR_FILES_MATCH"] = "PASS"

    expected_preservation = [{"rule_id": item.rule_id, "path": item.path} for item in registry.preservation_rules]
    actual_preservation_ids = [{"rule_id": row.get("rule_id"), "path": row.get("path")} for row in preservation_bindings_raw]
    if actual_preservation_ids != expected_preservation:
        return _blocked("ROLLBACK_PRESERVATION_BINDING_MISMATCH", subject=safe_path, failed_check="PRESERVATION_BINDINGS_MATCH")
    for row in preservation_bindings_raw:
        try:
            preserved_bytes = _canonical_lf_bytes((REPO_ROOT / row["path"]).read_bytes())
        except (OSError, UnicodeDecodeError):
            return _blocked("ROLLBACK_PRESERVATION_BINDING_MISMATCH", subject=row["path"], failed_check="PRESERVATION_BINDINGS_MATCH")
        if len(preserved_bytes) != row.get("content_byte_size") or _sha256_hex(preserved_bytes) != row.get("canonical_lf_sha256"):
            return _blocked("ROLLBACK_PRESERVATION_BINDING_MISMATCH", subject=row["path"], failed_check="PRESERVATION_BINDINGS_MATCH")
    check_status["PRESERVATION_BINDINGS_MATCH"] = "PASS"

    # Every file and preservation binding has now been fully
    # content-validated (the preservation-conflict safety gate above has
    # already run): build the typed tuples now so the round-trip check and,
    # if this rehearsal reaches READY, the response report these as
    # genuinely validated bindings instead of an empty list.
    validated_file_bindings = tuple(
        RollbackFileBinding(
            binding_id=row["binding_id"],
            predecessor_path=row["predecessor_path"],
            predecessor_content_byte_size=row["predecessor_content_byte_size"],
            predecessor_canonical_lf_sha256=row["predecessor_canonical_lf_sha256"],
            current_path=row["current_path"],
            current_content_byte_size=row["current_content_byte_size"],
            current_canonical_lf_sha256=row["current_canonical_lf_sha256"],
        )
        for row in file_bindings_raw
    )
    validated_preservation_bindings = tuple(
        PreservationBinding(rule_id=row["rule_id"], path=row["path"], content_byte_size=row["content_byte_size"], canonical_lf_sha256=row["canonical_lf_sha256"])
        for row in preservation_bindings_raw
    )

    # Round-trip the validated raw mapping through the closed public
    # RollbackMetadataArtifact model as a defensive cross-check: if the typed
    # model and the independently validated raw artifact ever disagreed on a
    # single field, that would itself be an integrity bug worth failing
    # closed on, never a silently accepted rollback plan.
    typed_rollback_artifact = RollbackMetadataArtifact(
        schema=parsed["schema"],
        artifact_content_hash=parsed["artifact_content_hash"],
        hash_basis=parsed["hash_basis"],
        rollback_source_record_binding_hash_basis=parsed["rollback_source_record_binding_hash_basis"],
        current_source_id=parsed["current_source_id"],
        current_rollback_source_record_binding_hash=parsed["current_rollback_source_record_binding_hash"],
        predecessor_source_id=parsed["predecessor_source_id"],
        predecessor_rollback_source_record_binding_hash=parsed["predecessor_rollback_source_record_binding_hash"],
        current_declaration_refs=tuple(freeze_json(item) for item in parsed["current_declaration_refs"]),
        predecessor_declaration_refs=tuple(freeze_json(item) for item in parsed["predecessor_declaration_refs"]),
        file_bindings=validated_file_bindings,
        preservation_bindings=validated_preservation_bindings,
    )
    if typed_rollback_artifact.as_dict() != parsed:
        return _blocked("ROLLBACK_ARTIFACT_BINDING_MISMATCH", subject=safe_path, failed_check="INPUTS_IMMUTABLE")
    check_status["INPUTS_IMMUTABLE"] = "PASS"

    operations: list[ProposedRollbackOperation] = []

    def _op(operation_type: str, *, source_path: str | None = None, target_path: str | None = None, expected_source_hash: str | None = None, expected_target_hash: str | None = None) -> None:
        seq = len(operations) + 1
        operations.append(
            ProposedRollbackOperation(
                operation_id=f"op-{seq}",
                sequence=seq,
                operation_type=operation_type,
                source_path=source_path,
                target_path=target_path,
                expected_source_hash=expected_source_hash,
                expected_target_hash=expected_target_hash,
                preservation_rule_id=None,
                proposal_only=True,
                approval_required=True,
                approval_state="NOT_GRANTED",
                executed=False,
            )
        )

    _op("REVALIDATE_INPUT_BINDINGS")
    _op("REVALIDATE_PRESERVATION_BOUNDARIES")
    for binding in validated_file_bindings:
        _op("RESTORE_DECLARATION_FROM_PREDECESSOR", source_path=binding.predecessor_path, target_path=binding.current_path, expected_source_hash=binding.predecessor_canonical_lf_sha256, expected_target_hash=binding.current_canonical_lf_sha256)
    for binding in validated_file_bindings:
        _op("VERIFY_RESTORED_DECLARATION_HASH", target_path=binding.current_path, expected_source_hash=binding.predecessor_canonical_lf_sha256)
    _op("REQUEST_HUMAN_ADJUDICATION")

    return RollbackRehearsal(
        outcome="READY_FOR_HUMAN_ADJUDICATION",
        reason_code="REHEARSAL_INTEGRITY_VALID",
        blocker=None,
        rollback_route_eligible=True,
        proposed_operations=tuple(operations),
        lineage=freeze_json(lineage),
        rollback_artifact_registry_path=safe_path,
        rollback_artifact_status="VERIFIED",
        rollback_artifact_content_hash=validated_hash,
        rollback_file_bindings=validated_file_bindings,
        rollback_preservation_bindings=validated_preservation_bindings,
        integrity_checks=_status_checks(),
    )


def rehearse_rollback(pair: V2S2ArtifactPair, registry: Registry) -> RollbackRehearsal:
    """Bounded, read-only rollback validation and inert typed plan construction."""
    source_record = next((item for item in registry.source_records if item.source_id == pair.source_id), None)
    if source_record is None:
        raise DriftUnknownSourceError("V2-S2 source_id is not present in the current valid registry", subject=pair.source_id)

    if source_record.rollback.predecessor_source_id is None:
        try:
            safe_path = _validate_safe_repo_relative_path_no_follow(source_record.rollback.rollback_artifact)
        except ValueError as exc:
            raise DriftLineageError(_LINEAGE_MSG, subject=source_record.source_id) from exc
        registry_dict = _registry_raw_mapping(registry)
        lineage = _build_rollback_lineage(source_record, registry, registry_dict)
        return RollbackRehearsal(
            outcome="NOT_APPLICABLE",
            reason_code="NO_PREDECESSOR",
            blocker=None,
            rollback_route_eligible=False,
            proposed_operations=(),
            lineage=freeze_json(lineage),
            rollback_artifact_registry_path=safe_path,
            rollback_artifact_status="NOT_REQUIRED",
            rollback_artifact_content_hash=None,
            rollback_file_bindings=(),
            rollback_preservation_bindings=(),
            integrity_checks=(),
        )

    registry_dict = _registry_raw_mapping(registry)
    return _rehearse_non_null_rollback(source_record, registry, registry_dict)


# ---------------------------------------------------------------------------
# Proposed impact routing.
# ---------------------------------------------------------------------------


def _reason_rule_ids_in_priority_order(rule_ids: set[str], priority_order: tuple[str, ...]) -> tuple[str, ...]:
    ordered = [rule_id for rule_id in priority_order if rule_id in rule_ids]
    ordered.extend(sorted(rule_id for rule_id in rule_ids if rule_id not in priority_order))
    return tuple(ordered)


_ROUTE_PREREQUISITE_ORDER = (
    "VALIDATED_V2_S2_PAIR",
    "CURRENT_BASELINE_MATCH",
    "POLICY_BASELINE_MATCH",
    "MATERIAL_CHANGE",
    "CURRENT_CONSUMER_EDGE",
    "ROLLBACK_REHEARSAL_READY",
    "HUMAN_ADJUDICATION",
)


def _route_prerequisites(*, material_gated: bool, consumer_target: bool, rollback_target: bool) -> tuple[RoutePrerequisite, ...]:
    satisfied = {"VALIDATED_V2_S2_PAIR", "CURRENT_BASELINE_MATCH", "POLICY_BASELINE_MATCH"}
    if material_gated:
        satisfied.add("MATERIAL_CHANGE")
    if consumer_target:
        satisfied.add("CURRENT_CONSUMER_EDGE")
    if rollback_target:
        satisfied.add("ROLLBACK_REHEARSAL_READY")
    prereqs = [RoutePrerequisite(prerequisite=name, status="SATISFIED") for name in _ROUTE_PREREQUISITE_ORDER if name != "HUMAN_ADJUDICATION" and name in satisfied]
    prereqs.append(RoutePrerequisite(prerequisite="HUMAN_ADJUDICATION", status="REQUIRED"))
    return tuple(prereqs)


def route_impact(assessment: MaterialityAssessment, registry: Registry, rehearsal: RollbackRehearsal) -> ImpactRoutingResult:
    """Pure, deterministic proposal derivation from current declared actions and edges."""
    source_record = next((item for item in registry.source_records if item.source_id == assessment.source_id), None)
    if source_record is None:
        raise DriftUnknownSourceError("V2-S2 source_id is not present in the current valid registry", subject=assessment.source_id)

    declared_actions = tuple(source_record.drift_policy.actions)
    non_reserved_consumers = [cid for cid in source_record.consumers if cid not in RESERVED_CONSUMER_IDS]
    consumer_owner = {item.consumer_id: item.owner for item in registry.consumers}

    changed_evaluations = [item for item in assessment.evaluations if item.evaluation != "NO_OBSERVED_CHANGE"]
    material_evaluations = [item for item in assessment.evaluations if item.evaluation == "MATERIAL_CHANGE"]
    changed_fact_ids = tuple(item.fact_id for item in changed_evaluations)
    material_fact_ids = tuple(item.fact_id for item in material_evaluations)
    material_rule_ids = _reason_rule_ids_in_priority_order({item.rule_id for item in material_evaluations}, assessment.rule_id_priority_order)
    changed_rule_ids = _reason_rule_ids_in_priority_order({item.rule_id for item in changed_evaluations}, assessment.rule_id_priority_order)

    dispositions: list[ActionDisposition] = []
    routes: list[ProposedRoute] = []
    seen_route_keys: set[tuple[str, str, str]] = set()

    def _add_route(*, action: str, target_type: str, target_id: str, owner: str, reason_fact_ids: tuple[str, ...], reason_rule_ids: tuple[str, ...], material_gated: bool) -> str:
        route_id = f"{action}:{target_type}:{target_id}"
        key = (action, target_type, target_id)
        if key in seen_route_keys:
            raise DriftRouteInvariantError("proposed impact routes violate the closed dedupe, order, target, or approval contract", subject=route_id)
        seen_route_keys.add(key)
        routes.append(
            ProposedRoute(
                route_id=route_id,
                action=action,
                state="PROPOSED",
                source_id=source_record.source_id,
                target=freeze_json({"type": target_type, "id": target_id, "owner": owner}),
                consumer_id=None if target_type == "SOURCE" else target_id,
                prerequisites=_route_prerequisites(material_gated=material_gated, consumer_target=target_type == "CONSUMER", rollback_target=action == "rollback"),
                reason_fact_ids=reason_fact_ids,
                reason_rule_ids=reason_rule_ids,
                proposal_only=True,
                approval_required=True,
                approval_state="NOT_GRANTED",
                executed=False,
            )
        )
        return route_id

    for action in ALLOWED_ACTIONS_IN_ORDER:
        if action not in declared_actions:
            dispositions.append(ActionDisposition(action=action, disposition="NOT_DECLARED_BY_SOURCE", reason_id="ACTION_NOT_DECLARED", route_ids=()))
            continue
        if action == "stage_diff":
            dispositions.append(ActionDisposition(action=action, disposition="EVIDENCED_BY_VALIDATED_INPUT", reason_id="VALIDATED_V2_S2_DIFF_PRESENT", route_ids=()))
            continue
        if action == "record_only":
            route_id = _add_route(
                action=action,
                target_type="SOURCE",
                target_id=source_record.source_id,
                owner=source_record.owner,
                reason_fact_ids=changed_fact_ids,
                reason_rule_ids=changed_rule_ids,
                material_gated=False,
            )
            dispositions.append(ActionDisposition(action=action, disposition="PROPOSED", reason_id="COMPLETED_ASSESSMENT_REQUIRES_RECORD", route_ids=(route_id,)))
            continue
        if assessment.outcome == "NO_OBSERVED_CHANGE":
            dispositions.append(ActionDisposition(action=action, disposition="NOT_PROPOSED_NO_OBSERVED_CHANGE", reason_id="NO_OBSERVED_CHANGE", route_ids=()))
            continue
        if assessment.outcome == "NON_MATERIAL_CHANGE":
            dispositions.append(ActionDisposition(action=action, disposition="NOT_PROPOSED_NON_MATERIAL", reason_id="NON_MATERIAL_CHANGE", route_ids=()))
            continue

        if action == "block_consumer":
            route_ids = tuple(
                _add_route(action=action, target_type="CONSUMER", target_id=consumer_id, owner=consumer_owner.get(consumer_id, ""), reason_fact_ids=material_fact_ids, reason_rule_ids=material_rule_ids, material_gated=True)
                for consumer_id in sorted(non_reserved_consumers)
            )
            if route_ids:
                dispositions.append(ActionDisposition(action=action, disposition="PROPOSED", reason_id="MATERIAL_ROUTE_CONDITION_MET", route_ids=route_ids))
            else:
                dispositions.append(ActionDisposition(action=action, disposition="NOT_PROPOSED_NO_TARGET_EDGE", reason_id="TARGET_EDGE_ABSENT", route_ids=()))
            continue
        if action in {"rebuild_benchmark", "invalidate_packets", "reground_atlas"}:
            fixed_target = {"rebuild_benchmark": "eval-benchmark", "invalidate_packets": "packet", "reground_atlas": "atlas"}[action]
            if fixed_target in non_reserved_consumers:
                route_id = _add_route(action=action, target_type="CONSUMER", target_id=fixed_target, owner=consumer_owner.get(fixed_target, ""), reason_fact_ids=material_fact_ids, reason_rule_ids=material_rule_ids, material_gated=True)
                dispositions.append(ActionDisposition(action=action, disposition="PROPOSED", reason_id="MATERIAL_ROUTE_CONDITION_MET", route_ids=(route_id,)))
            else:
                dispositions.append(ActionDisposition(action=action, disposition="NOT_PROPOSED_NO_TARGET_EDGE", reason_id="TARGET_EDGE_ABSENT", route_ids=()))
            continue
        if action in {"review_policy", "rerun_validation"}:
            route_id = _add_route(action=action, target_type="SOURCE", target_id=source_record.source_id, owner=source_record.owner, reason_fact_ids=material_fact_ids, reason_rule_ids=material_rule_ids, material_gated=True)
            dispositions.append(ActionDisposition(action=action, disposition="PROPOSED", reason_id="MATERIAL_ROUTE_CONDITION_MET", route_ids=(route_id,)))
            continue
        if action == "rollback":
            if source_record.rollback.predecessor_source_id is None:
                dispositions.append(ActionDisposition(action=action, disposition="NOT_PROPOSED_NO_PREDECESSOR", reason_id="NO_PREDECESSOR", route_ids=()))
            elif rehearsal.outcome != "READY_FOR_HUMAN_ADJUDICATION":
                dispositions.append(ActionDisposition(action=action, disposition="NOT_PROPOSED_REHEARSAL_BLOCKED", reason_id="ROLLBACK_REHEARSAL_BLOCKED", route_ids=()))
            else:
                route_id = _add_route(action=action, target_type="SOURCE", target_id=source_record.source_id, owner=source_record.owner, reason_fact_ids=material_fact_ids, reason_rule_ids=material_rule_ids, material_gated=True)
                dispositions.append(ActionDisposition(action=action, disposition="PROPOSED", reason_id="MATERIAL_ROUTE_CONDITION_MET", route_ids=(route_id,)))
            continue

    return ImpactRoutingResult(source_declared_actions=declared_actions, action_dispositions=tuple(dispositions), routes=tuple(routes))


# ---------------------------------------------------------------------------
# Artifact payload construction.
# ---------------------------------------------------------------------------


def _artifact_ref_dict(ref: V2S2ArtifactRef) -> dict[str, Any]:
    return {"path": ref.path, "content_hash": ref.content_hash, "schema": ref.schema}


def _input_binding_dict(*, pair: V2S2ArtifactPair, registry_dict: dict[str, Any], source_record: Any, policy: MaterialityPolicy) -> dict[str, Any]:
    raw_record = _find_raw_source_record(registry_dict, source_record.source_id)
    return {
        "manifest_content_hash": pair.manifest_content_hash,
        "diff_artifact": _artifact_ref_dict(pair.diff_ref),
        "verification_artifact": _artifact_ref_dict(pair.verification_ref),
        "registry": {
            "path": CANONICAL_REGISTRY_REL,
            "schema": REGISTRY_SCHEMA_ID,
            "registry_id": registry_dict.get("registry_id"),
            "content_hash": registry_dict.get("registry_content_hash"),
        },
        "source": {
            "source_id": source_record.source_id,
            "source_record_content_hash": _sha256_hex(_canonical_json_bytes(raw_record)) if raw_record is not None else None,
            "rollback_source_record_binding_hash_basis": ROLLBACK_SOURCE_RECORD_BINDING_HASH_BASIS,
            "rollback_source_record_binding_hash": _rollback_source_record_binding_hash(raw_record) if raw_record is not None else None,
            "declaration_refs": [item.as_dict() for item in source_record.declaration_refs],
        },
        "policy": {
            "path": MATERIALITY_POLICY_REL,
            "schema": policy.schema,
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "content_hash": policy.policy_content_hash,
            "approval_mode": thaw_json(policy.approval_binding).get("mode"),
        },
    }


def _build_impact_plan_payload(*, pair: V2S2ArtifactPair, registry_dict: dict[str, Any], source_record: Any, policy: MaterialityPolicy, assessment: MaterialityAssessment, routing: ImpactRoutingResult) -> dict[str, Any]:
    diff_dict = thaw_json(pair.diff)
    draft = ImpactPlanArtifact(
        schema=IMPACT_SCHEMA_ID,
        artifact_content_hash="0" * 64,
        hash_basis=IMPACT_HASH_BASIS,
        observed_at=pair.observed_at,
        input_binding=freeze_json(_input_binding_dict(pair=pair, registry_dict=registry_dict, source_record=source_record, policy=policy)),
        observation=freeze_json(
            {
                "stage_outcome": pair.stage_outcome,
                "summary": diff_dict["summary"],
                "fact_ids": [item.fact_id for item in pair.facts],
            }
        ),
        policy_evaluation=freeze_json(
            {
                "outcome": assessment.outcome,
                "counts": thaw_json(assessment.counts),
                "evaluations": [item.as_dict() for item in assessment.evaluations],
            }
        ),
        proposal=freeze_json(
            {
                "source_declared_actions": list(routing.source_declared_actions),
                "action_dispositions": [item.as_dict() for item in routing.action_dispositions],
                "routes": [item.as_dict() for item in routing.routes],
            }
        ),
        proposal_only=True,
        approval_required=True,
        approval_state="NOT_GRANTED",
        executed=False,
        validation_ceiling=VALIDATION_CEILING,
    )
    # ``as_dict()`` is the one JSON boundary: the typed artifact is built and
    # carried internally, and only converted to a fresh plain mapping here so
    # its self-hash (and later, its persisted bytes) can be computed.
    payload = draft.as_dict()
    payload["artifact_content_hash"] = _self_excluding_hash(payload, "artifact_content_hash")
    return payload


def _build_rollback_plan_payload(*, pair: V2S2ArtifactPair, registry_dict: dict[str, Any], source_record: Any, policy: MaterialityPolicy, impact_payload: dict[str, Any], rehearsal: RollbackRehearsal) -> dict[str, Any]:
    draft = RollbackPlanArtifact(
        schema=ROLLBACK_PLAN_SCHEMA_ID,
        artifact_content_hash="0" * 64,
        hash_basis=ROLLBACK_PLAN_HASH_BASIS,
        observed_at=pair.observed_at,
        input_binding=freeze_json(_input_binding_dict(pair=pair, registry_dict=registry_dict, source_record=source_record, policy=policy)),
        impact_plan_content_hash=impact_payload["artifact_content_hash"],
        lineage=rehearsal.lineage,
        rollback_artifact=freeze_json(rehearsal.rollback_artifact_dict()),
        integrity_checks=rehearsal.integrity_checks,
        rehearsal=freeze_json(rehearsal.rehearsal_dict()),
        proposal_only=True,
        approval_required=True,
        approval_state="NOT_GRANTED",
        executed=False,
        validation_ceiling=VALIDATION_CEILING,
    )
    payload = draft.as_dict()
    payload["artifact_content_hash"] = _self_excluding_hash(payload, "artifact_content_hash")
    return payload


# ---------------------------------------------------------------------------
# Two-pass immutable-input snapshotting.
# ---------------------------------------------------------------------------


def _snapshot_entry(path: Path) -> tuple[Any, ...]:
    st = _lstat_or_none(path)
    if st is None:
        return ("MISSING",)
    if stat.S_ISLNK(st.st_mode):
        return ("LINK",)
    if stat.S_ISDIR(st.st_mode):
        try:
            names = tuple(sorted(entry.name for entry in os.scandir(path)))
        except OSError:
            names = None
        return ("DIR", names)
    if stat.S_ISREG(st.st_mode):
        try:
            digest = _sha256_hex(path.read_bytes())
        except OSError:
            digest = None
        return ("FILE", st.st_size, digest)
    return ("OTHER",)


def _governing_declaration_and_preservation_paths(registry_dict: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for record in registry_dict.get("source_records", []) or []:
        if not isinstance(record, dict):
            continue
        for ref in record.get("declaration_refs", []) or []:
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                paths.append(ref["path"])
    for rule in registry_dict.get("preservation_rules", []) or []:
        if isinstance(rule, dict) and isinstance(rule.get("path"), str):
            paths.append(rule["path"])
    return paths


def _load_structurally_stable_rollback_artifact(artifact_path: Path) -> dict[str, Any] | None:
    """Best-effort, read-only structural parse of one candidate rollback artifact.

    Mirrors (without replacing) the early structural/self-hash validation
    that ``_rehearse_non_null_rollback`` independently performs -- safe
    filename/location shape, bounded size, strict UTF-8, strict
    duplicate-safe JSON, structure limits, canonical bytes, closed
    top-level/row schema, and a matching content-addressed self-hash -- so
    its ``file_bindings`` are trustworthy enough to read
    ``current_path``/``predecessor_path`` from. Returns ``None`` on any
    failure instead of raising: this helper only conservatively seeds which
    files a candidate non-null rollback binds *before* the first
    governing-input snapshot in ``_plan_drift_impl``; it never authorizes a
    rollback. The one authoritative outcome (READY or the exact granular
    blocker code) is still computed, once, by ``_rehearse_non_null_rollback``.
    """
    relative = _canonical_path_subject(artifact_path, root=REPO_ROOT)
    safe_path_obj = Path(relative)
    if safe_path_obj.parent.as_posix() != "configs/sourceops/rollbacks" or not ROLLBACK_ARTIFACT_FILENAME_RE.fullmatch(safe_path_obj.name):
        return None
    st = _lstat_or_none(artifact_path)
    if st is None or stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_size > ROLLBACK_ARTIFACT_BYTES:
        return None
    try:
        raw = artifact_path.read_bytes()
    except OSError:
        return None
    if len(raw) > ROLLBACK_ARTIFACT_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        parsed = _strict_json_loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(parsed, dict):
        return None
    try:
        _measure_json_structure(parsed, max_nodes=MAXIMUM_JSON_NODES, max_depth=MAXIMUM_JSON_DEPTH)
    except ValueError:
        return None
    if _canonical_json_bytes(parsed) + b"\n" != raw:
        return None
    if set(parsed.keys()) != _ROLLBACK_ARTIFACT_TOP_LEVEL_KEYS:
        return None
    if parsed.get("schema") != ROLLBACK_ARTIFACT_SCHEMA_ID or parsed.get("hash_basis") != ROLLBACK_ARTIFACT_HASH_BASIS:
        return None
    file_bindings_raw = parsed.get("file_bindings")
    preservation_bindings_raw = parsed.get("preservation_bindings")
    if not isinstance(file_bindings_raw, list) or len(file_bindings_raw) > MAXIMUM_ROLLBACK_FILE_BINDINGS or not isinstance(preservation_bindings_raw, list):
        return None
    for row in file_bindings_raw:
        if not isinstance(row, dict) or set(row.keys()) != _ROLLBACK_FILE_BINDING_KEYS:
            return None
    for row in preservation_bindings_raw:
        if not isinstance(row, dict) or set(row.keys()) != _ROLLBACK_PRESERVATION_BINDING_KEYS:
            return None
    declared_hash = parsed.get("artifact_content_hash")
    if not isinstance(declared_hash, str) or safe_path_obj.name != f"rb-{declared_hash}.json":
        return None
    if declared_hash != _self_excluding_hash(parsed, "artifact_content_hash"):
        return None
    return parsed


def _collect_rollback_bound_paths(*, registry: Registry, rollback_artifact_path: Path | None) -> list[Path]:
    """Every real repo file one candidate non-null rollback binds or must preserve.

    Seeds ``rollback_bound_paths`` in ``_plan_drift_impl`` before the first
    governing-input snapshot so a mutation to a file the rollback binds is
    classified as ``DRIFT_ROLLBACK_INPUT_MUTATED`` (exit 8) rather than
    going undetected or being misclassified as a baseline change. Always
    includes every current authoritative preservation-rule path (required
    by authority, independent of the rollback artifact's own validity);
    adds each file binding's ``current_path``/``predecessor_path`` only
    once the artifact is structurally stable, and only once each candidate
    path is independently confirmed safe and no-follow -- an unsafe or
    unresolvable candidate is silently excluded rather than trusted.
    """
    candidates: set[Path] = {REPO_ROOT / rule.path for rule in registry.preservation_rules}
    if rollback_artifact_path is not None:
        parsed = _load_structurally_stable_rollback_artifact(rollback_artifact_path)
        if parsed is not None:
            for row in parsed.get("file_bindings", []) or []:
                if not isinstance(row, dict):
                    continue
                for key in ("current_path", "predecessor_path"):
                    try:
                        safe_bound_rel = _validate_safe_repo_relative_path_no_follow(row.get(key))
                    except ValueError:
                        continue
                    candidates.add(REPO_ROOT / safe_bound_rel)
    return sorted(candidates, key=lambda item: _canonical_path_subject(item, root=REPO_ROOT))


def _snapshot_governing_inputs(
    *,
    verification_path: Path,
    diff_path: Path,
    registry_dict: dict[str, Any],
    rollback_artifact_path: Path | None,
    rollback_bound_paths: list[Path],
) -> dict[str, dict[str, tuple[Any, ...]]]:
    input_group = {"verification": _snapshot_entry(verification_path), "diff": _snapshot_entry(diff_path)}
    # A path that is both a declaration/preservation baseline path and a
    # rollback file/preservation binding target is classified only under the
    # rollback group below: rollback-mutation precedence is strict, so the
    # same byte change is never also duplicated into (and never masked by) a
    # DRIFT_BASELINE_CHANGED_DURING_RUN classification.
    rollback_bound_subjects = {_canonical_path_subject(bound_path, root=REPO_ROOT) for bound_path in rollback_bound_paths}
    baseline_group: dict[str, tuple[Any, ...]] = {"registry": _snapshot_entry(REPO_ROOT / CANONICAL_REGISTRY_REL)}
    for rel in _governing_declaration_and_preservation_paths(registry_dict):
        if rel in rollback_bound_subjects:
            continue
        baseline_group[rel] = _snapshot_entry(REPO_ROOT / rel)
    policy_group = {"policy": _snapshot_entry(REPO_ROOT / MATERIALITY_POLICY_REL)}
    rollback_group: dict[str, tuple[Any, ...]] = {}
    if rollback_artifact_path is not None:
        rollback_group["artifact"] = _snapshot_entry(rollback_artifact_path)
    for bound_path in rollback_bound_paths:
        rollback_group[_canonical_path_subject(bound_path, root=REPO_ROOT)] = _snapshot_entry(bound_path)
    return {"input": input_group, "baseline": baseline_group, "policy": policy_group, "rollback": rollback_group}


# ---------------------------------------------------------------------------
# Transactional, race-safe, whole-leaf pair publication.
# ---------------------------------------------------------------------------


def _leaf_lock(leaf: Path) -> threading.Lock:
    key = str(leaf)
    with _LEAF_LOCKS_GUARD:
        lock = _LEAF_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LEAF_LOCKS[key] = lock
        return lock


def _acquire_leaf_lock(leaf: Path) -> threading.Lock:
    lock = _leaf_lock(leaf)
    if not lock.acquire(timeout=_TRANSACTION_ACQUIRE_TIMEOUT_SECONDS):
        raise DriftOutputWriteError("drift-plan artifact pair could not be published atomically", subject=_canonical_path_subject(leaf, root=REPO_ROOT))
    return lock


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _lock_metadata_bytes(token: str) -> bytes:
    payload = {"pid": os.getpid(), "token": token, "version": 1}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _parse_lock_metadata(raw: bytes) -> dict[str, Any] | None:
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


def _create_lock_file(lock_path: Path) -> bool:
    """Win exclusive, authoritative on-disk ownership of ``lock_path``.

    Mirrors the proven V2-S2 transaction-lock semantics (exclusive
    ``O_CREAT|O_EXCL`` creation with parseable owner metadata, bounded
    liveness-checked waiting, and fail-closed on any foreign/invalid/dead
    owner) as an independent V2-S3 implementation.
    """
    token = uuid.uuid4().hex
    metadata = _lock_metadata_bytes(token)
    deadline = time.monotonic() + _TRANSACTION_ACQUIRE_TIMEOUT_SECONDS
    subject = _canonical_path_subject(lock_path, root=REPO_ROOT)
    write_failed = "drift-plan artifact pair could not be published atomically"
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pass
        except OSError as exc:
            raise DriftOutputWriteError(write_failed, subject=subject) from exc
        else:
            try:
                os.write(fd, metadata)
                os.fsync(fd)
            finally:
                os.close(fd)
            _LOCK_OWN_TOKENS[str(lock_path)] = token
            return True

        st = _lstat_or_none(lock_path)
        if st is None:
            continue
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise DriftOutputWriteError(write_failed, subject=subject)
        try:
            raw = lock_path.read_bytes()
        except OSError as exc:
            raise DriftOutputWriteError(write_failed, subject=subject) from exc
        parsed = _parse_lock_metadata(raw)
        if parsed is None:
            raise DriftOutputWriteError(write_failed, subject=subject)
        if not _pid_alive(parsed["pid"]):
            raise DriftOutputWriteError(write_failed, subject=subject)
        if time.monotonic() >= deadline:
            raise DriftOutputWriteError(write_failed, subject=subject)
        time.sleep(_TRANSACTION_RETRY_SLEEP_SECONDS)


def _release_lock_file(lock_path: Path, owns_lock_file: bool) -> None:
    if not owns_lock_file:
        return
    token = _LOCK_OWN_TOKENS.pop(str(lock_path), None)
    if token is None:
        return
    try:
        current = _parse_lock_metadata(lock_path.read_bytes())
    except OSError:
        current = None
    if current is not None and current["token"] == token:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _accept_existing_if_identical(path: Path, encoded: bytes) -> bool:
    st = _lstat_or_none(path)
    if st is None:
        return False
    write_failed = "drift-plan artifact pair could not be published atomically"
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise DriftOutputBoundaryError("drift-plan output path is not a safe real path below the fixed boundary", subject=_canonical_path_subject(path, root=REPO_ROOT))
    for _attempt in range(2):
        try:
            existing = path.read_bytes()
        except OSError:
            continue
        if existing == encoded:
            return True
    raise DriftOutputCollisionError("content-addressed drift-plan leaf contains non-identical or unknown content", subject=_canonical_path_subject(path, root=REPO_ROOT))


def _write_atomic(path: Path, encoded: bytes) -> None:
    write_failed = "drift-plan artifact pair could not be published atomically"
    for _attempt in range(8):
        if _accept_existing_if_identical(path, encoded):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.parent / f"{_TEMP_ARTIFACT_PREFIX}{uuid.uuid4().hex}-{path.name}"
        try:
            with open(temp_path, "xb") as handle:
                handle.write(encoded)
            os.link(temp_path, path)
        except FileExistsError:
            continue
        except OSError as exc:
            raise DriftOutputWriteError(write_failed, subject=_canonical_path_subject(path, root=REPO_ROOT)) from exc
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return
    raise DriftOutputWriteError(write_failed, subject=_canonical_path_subject(path, root=REPO_ROOT))


def _publish_plan_pair(impact_payload: dict[str, Any], rollback_payload: dict[str, Any], *, diff_hash: str, policy_hash: str) -> tuple[ArtifactReference, ArtifactReference]:
    parent_root = REPO_ROOT / DRIFT_OUTPUT_PARENT_REL
    boundary_msg = "drift-plan output path is not a safe real path below the fixed boundary"
    _assert_no_reparse_ancestors(parent_root, root=REPO_ROOT, error=DriftOutputBoundaryError, message=boundary_msg)
    parent_root.mkdir(parents=True, exist_ok=True)
    diff_root = parent_root / diff_hash
    leaf = diff_root / policy_hash
    _assert_no_reparse_ancestors(leaf, root=REPO_ROOT, error=DriftOutputBoundaryError, message=boundary_msg)

    impact_hash = impact_payload["artifact_content_hash"]
    rollback_hash = rollback_payload["artifact_content_hash"]
    impact_name = f"impact-{impact_hash}.json"
    rollback_name = f"rollback-{rollback_hash}.json"
    expected_names = {impact_name, rollback_name}

    impact_encoded = _canonical_json_bytes(impact_payload) + b"\n"
    rollback_encoded = _canonical_json_bytes(rollback_payload) + b"\n"
    if len(impact_encoded) > EACH_OUTPUT_ARTIFACT_BYTES or len(rollback_encoded) > EACH_OUTPUT_ARTIFACT_BYTES:
        raise DriftOutputLimitError("drift-plan artifact pair exceeds a closed output byte limit", subject=_canonical_path_subject(leaf, root=REPO_ROOT))
    if len(impact_encoded) + len(rollback_encoded) > TOTAL_OUTPUT_ARTIFACT_BYTES:
        raise DriftOutputLimitError("drift-plan artifact pair exceeds a closed output byte limit", subject=_canonical_path_subject(leaf, root=REPO_ROOT))

    lock = _acquire_leaf_lock(leaf)
    owns_lock_file = False
    lock_path = leaf / _TRANSACTION_LOCK_NAME
    try:
        if not leaf.exists():
            try:
                leaf.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                pass
        leaf_stat = _lstat_or_none(leaf)
        if leaf_stat is None or stat.S_ISLNK(leaf_stat.st_mode) or not stat.S_ISDIR(leaf_stat.st_mode):
            raise DriftOutputBoundaryError(boundary_msg, subject=_canonical_path_subject(leaf, root=REPO_ROOT))

        owns_lock_file = _create_lock_file(lock_path)

        try:
            current_names = {entry.name for entry in os.scandir(leaf) if not entry.name.startswith(_TEMP_ARTIFACT_PREFIX) and entry.name != _TRANSACTION_LOCK_NAME}
        except OSError as exc:
            raise DriftOutputBoundaryError(boundary_msg, subject=_canonical_path_subject(leaf, root=REPO_ROOT)) from exc
        if current_names - expected_names:
            raise DriftOutputCollisionError("content-addressed drift-plan leaf contains non-identical or unknown content", subject=_canonical_path_subject(leaf, root=REPO_ROOT))

        impact_path = leaf / impact_name
        rollback_path = leaf / rollback_name
        _write_atomic(impact_path, impact_encoded)
        _write_atomic(rollback_path, rollback_encoded)

        impact_ref = ArtifactReference(path=_canonical_path_subject(impact_path, root=REPO_ROOT), content_hash=impact_hash, schema=IMPACT_SCHEMA_ID)
        rollback_ref = ArtifactReference(path=_canonical_path_subject(rollback_path, root=REPO_ROOT), content_hash=rollback_hash, schema=ROLLBACK_PLAN_SCHEMA_ID)
        return impact_ref, rollback_ref
    finally:
        _release_lock_file(lock_path, owns_lock_file)
        lock.release()


# ---------------------------------------------------------------------------
# plan_drift() orchestration.
# ---------------------------------------------------------------------------


def _baseline_validity_for_code(code: str) -> str:
    if code == DriftUnknownSourceError.code:
        return "UNKNOWN_SOURCE"
    if code == DriftBaselineBindingMismatch.code:
        return "MISMATCH"
    return "INVALID"


def _policy_validity_for_code(code: str) -> str:
    if code in {DriftPolicyHashMismatch.code, DriftPolicyBindingMismatch.code}:
        return "MISMATCH"
    return "INVALID"


def _failure_cli_result(exc: DriftPlanningError, manifest_content_hash: str | None) -> PlanDriftCliResult:
    code = exc.code
    input_validity = "NOT_EVALUATED"
    baseline_validity = "NOT_EVALUATED"
    policy_validity = "NOT_EVALUATED"
    assessment_outcome = "NOT_EVALUATED"
    rollback_outcome = "NOT_EVALUATED"

    if code in _INPUT_DISCOVERY_CODES or code in _ARTIFACT_INVALID_CODES:
        input_validity = "INVALID"
        assessment_outcome = "INVALID"
    elif code in _BASELINE_CODES:
        input_validity = "VALID"
        baseline_validity = _baseline_validity_for_code(code)
    elif code in _POLICY_CODES:
        input_validity = "VALID"
        baseline_validity = "VALID"
        policy_validity = _policy_validity_for_code(code)
        assessment_outcome = "INVALID"
    elif code == DriftMaterialityEvaluationError.code:
        input_validity = "VALID"
        baseline_validity = "VALID"
        policy_validity = "VALID"
        assessment_outcome = "INVALID"
    elif code == DriftRouteInvariantError.code:
        input_validity = "VALID"
        baseline_validity = "VALID"
        policy_validity = "VALID"
    elif code in {DriftInputMutationError.code, DriftBaselineMutationError.code, DriftPolicyMutationError.code, DriftRollbackMutationError.code}:
        input_validity = "VALID"
        baseline_validity = "VALID"
        policy_validity = "VALID"
    elif code in {DriftOutputBoundaryError.code, DriftOutputLimitError.code, DriftOutputCollisionError.code, DriftOutputWriteError.code}:
        input_validity = "VALID"
        baseline_validity = "VALID"
        policy_validity = "VALID"
        assessment_outcome = getattr(exc, "computed_assessment_outcome", "NOT_EVALUATED")
        rollback_outcome = getattr(exc, "computed_rollback_outcome", "NOT_EVALUATED")

    return PlanDriftCliResult(
        schema=CLI_RESULT_SCHEMA_ID,
        command="plan-drift",
        run_status="FAILED",
        input_validity=input_validity,
        baseline_validity=baseline_validity,
        policy_validity=policy_validity,
        assessment_outcome=assessment_outcome,
        rollback_rehearsal_outcome=rollback_outcome,
        source_id=None,
        manifest_content_hash=manifest_content_hash,
        diff_artifact_content_hash=None,
        verification_artifact_content_hash=None,
        registry_content_hash=None,
        policy_content_hash=None,
        impact_plan=None,
        rollback_plan=None,
        error=exc.as_error_dict(),
        proposal_only=True,
        approval_required=True,
        approval_state="NOT_GRANTED",
        executed=False,
        validation_ceiling=VALIDATION_CEILING,
    )


def _internal_error_cli_result(manifest_content_hash: str | None) -> PlanDriftCliResult:
    error = DriftInternalError("plan-drift failed closed because of an unexpected internal error").as_error_dict()
    return PlanDriftCliResult(
        schema=CLI_RESULT_SCHEMA_ID,
        command="plan-drift",
        run_status="FAILED",
        input_validity="NOT_EVALUATED",
        baseline_validity="NOT_EVALUATED",
        policy_validity="NOT_EVALUATED",
        assessment_outcome="NOT_EVALUATED",
        rollback_rehearsal_outcome="NOT_EVALUATED",
        source_id=None,
        manifest_content_hash=manifest_content_hash,
        diff_artifact_content_hash=None,
        verification_artifact_content_hash=None,
        registry_content_hash=None,
        policy_content_hash=None,
        impact_plan=None,
        rollback_plan=None,
        error=error,
        proposal_only=True,
        approval_required=True,
        approval_state="NOT_GRANTED",
        executed=False,
        validation_ceiling=VALIDATION_CEILING,
    )


def _plan_drift_impl(manifest_content_hash: str) -> PlanDriftResult:
    if not isinstance(manifest_content_hash, str) or not HASH_RE.fullmatch(manifest_content_hash):
        raise DriftInputLeafError("V2-S2 input leaf is outside the fixed safe generated boundary", subject="manifest_content_hash")

    verification_path, diff_path = _discover_v2s2_pair(manifest_content_hash)
    pair = load_v2_s2_artifact_pair(manifest_content_hash)

    registry, registry_dict = _load_and_validate_current_registry()
    source_record = _validate_source_baseline(pair, registry, registry_dict)
    current_raw_record = _find_raw_source_record(registry_dict, pair.source_id) or {}
    _validate_facts_match_current_source(pair.facts, current_raw_record)
    # Content-binding and component-projection fact-universe validation
    # already ran inside load_v2_s2_artifact_pair (against this same current
    # production registry); re-running it here would be redundant double
    # validation of the identical facts and current_source data.

    policy = load_materiality_policy()
    if policy.registry_binding.get("registry_content_hash") != registry_dict.get("registry_content_hash"):
        raise DriftPolicyBindingMismatch(
            "fixed materiality policy does not bind the current registry or V2-S2 schemas",
            subject="registry_binding.registry_content_hash",
            expected=registry_dict.get("registry_content_hash"),
            actual=policy.registry_binding.get("registry_content_hash"),
        )

    rollback_artifact_path: Path | None = None
    rollback_bound_paths: list[Path] = []
    if source_record.rollback.predecessor_source_id is not None:
        try:
            safe_rel = _validate_safe_repo_relative_path_no_follow(source_record.rollback.rollback_artifact)
            rollback_artifact_path = REPO_ROOT / safe_rel
        except ValueError:
            rollback_artifact_path = None
        rollback_bound_paths = _collect_rollback_bound_paths(registry=registry, rollback_artifact_path=rollback_artifact_path)

    first_snapshot = _snapshot_governing_inputs(
        verification_path=verification_path,
        diff_path=diff_path,
        registry_dict=registry_dict,
        rollback_artifact_path=rollback_artifact_path,
        rollback_bound_paths=rollback_bound_paths,
    )

    assessment = evaluate_materiality(pair, registry, policy)
    rehearsal = rehearse_rollback(pair, registry)
    routing = route_impact(assessment, registry, rehearsal)

    impact_payload = _build_impact_plan_payload(pair=pair, registry_dict=registry_dict, source_record=source_record, policy=policy, assessment=assessment, routing=routing)
    rollback_payload = _build_rollback_plan_payload(pair=pair, registry_dict=registry_dict, source_record=source_record, policy=policy, impact_payload=impact_payload, rehearsal=rehearsal)

    second_snapshot = _snapshot_governing_inputs(
        verification_path=verification_path,
        diff_path=diff_path,
        registry_dict=registry_dict,
        rollback_artifact_path=rollback_artifact_path,
        rollback_bound_paths=rollback_bound_paths,
    )
    if first_snapshot["input"] != second_snapshot["input"]:
        raise DriftInputMutationError("V2-S2 artifact pair changed during planning", subject=manifest_content_hash)
    if first_snapshot["baseline"] != second_snapshot["baseline"]:
        raise DriftBaselineMutationError("registry, declaration, preservation, or lineage input changed during planning", subject=manifest_content_hash)
    if first_snapshot["policy"] != second_snapshot["policy"]:
        raise DriftPolicyMutationError("materiality policy changed during planning", subject=manifest_content_hash)
    if first_snapshot["rollback"] != second_snapshot["rollback"]:
        raise DriftRollbackMutationError("rollback artifact or bound file changed during rehearsal", subject=manifest_content_hash)

    try:
        impact_ref, rollback_ref = _publish_plan_pair(impact_payload, rollback_payload, diff_hash=pair.diff_ref.content_hash, policy_hash=policy.policy_content_hash)
    except DriftPlanningError as exc:
        exc.computed_assessment_outcome = assessment.outcome
        exc.computed_rollback_outcome = rehearsal.outcome
        raise

    exit_code = 8 if rehearsal.outcome == "BLOCKED" else 0
    cli_result = PlanDriftCliResult(
        schema=CLI_RESULT_SCHEMA_ID,
        command="plan-drift",
        run_status="COMPLETED",
        input_validity="VALID",
        baseline_validity="VALID",
        policy_validity="VALID",
        assessment_outcome=assessment.outcome,
        rollback_rehearsal_outcome=rehearsal.outcome,
        source_id=pair.source_id,
        manifest_content_hash=pair.manifest_content_hash,
        diff_artifact_content_hash=pair.diff_ref.content_hash,
        verification_artifact_content_hash=pair.verification_ref.content_hash,
        registry_content_hash=registry_dict.get("registry_content_hash"),
        policy_content_hash=policy.policy_content_hash,
        impact_plan=impact_ref,
        rollback_plan=rollback_ref,
        error=None,
        proposal_only=True,
        approval_required=True,
        approval_state="NOT_GRANTED",
        executed=False,
        validation_ceiling=VALIDATION_CEILING,
    )
    return PlanDriftResult(exit_code=exit_code, cli_result=cli_result)


def plan_drift(manifest_content_hash: str) -> PlanDriftResult:
    """Complete production plan-drift operation used by the CLI.

    Never raises: every closed, typed failure and any genuinely unexpected
    error are both caught here and turned into a ``PlanDriftResult`` with
    the appropriate exit code and JSON-safe error envelope.
    """
    try:
        return _plan_drift_impl(manifest_content_hash)
    except DriftPlanningError as exc:
        return PlanDriftResult(exit_code=exc.exit_code, cli_result=_failure_cli_result(exc, manifest_content_hash if isinstance(manifest_content_hash, str) else None))
    except Exception:
        return PlanDriftResult(exit_code=70, cli_result=_internal_error_cli_result(manifest_content_hash if isinstance(manifest_content_hash, str) else None))


# ---------------------------------------------------------------------------
# CLI wiring.
# ---------------------------------------------------------------------------


def _normalise_plan_drift_args(argv: list[str]) -> str:
    usage_msg = "plan-drift arguments do not match the closed command contract"
    if not argv:
        raise DriftCliUsageError(usage_msg, expected=["--manifest-hash"], actual=None)
    parsed: dict[str, str] = {}
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token != "--manifest-hash":
            raise DriftCliUsageError(usage_msg, subject=token, expected="--manifest-hash", actual=token)
        if idx + 1 >= len(argv):
            raise DriftCliUsageError(usage_msg, subject=token, expected="value", actual=None)
        if token in parsed:
            raise DriftCliUsageError(usage_msg, subject=token, expected="unique", actual=parsed[token])
        parsed[token] = argv[idx + 1]
        idx += 2
    value = parsed["--manifest-hash"]
    if not HASH_RE.fullmatch(value):
        raise DriftCliUsageError(usage_msg, subject="--manifest-hash", expected="^[0-9a-f]{64}$", actual=value)
    return value


def _serialize_plan_drift_json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _emit_plan_drift_result(payload: dict[str, Any], exit_code: int) -> int:
    try:
        encoded = _serialize_plan_drift_json(payload)
    except Exception:
        fallback = _internal_error_cli_result(None).as_dict()
        sys.stdout.buffer.write(_serialize_plan_drift_json(fallback))
        return 70
    sys.stdout.buffer.write(encoded)
    return exit_code


def _main_plan_drift_cli(argv: list[str]) -> int:
    try:
        manifest_hash = _normalise_plan_drift_args(argv)
    except DriftCliUsageError as exc:
        return _emit_plan_drift_result(_failure_cli_result(exc, None).as_dict(), exc.exit_code)
    try:
        outcome = plan_drift(manifest_hash)
    except Exception:
        return _emit_plan_drift_result(_internal_error_cli_result(manifest_hash).as_dict(), 70)
    return _emit_plan_drift_result(outcome.cli_result.as_dict(), outcome.exit_code)
