"""External cliPE cDNA -> GRCh38 SPDI projector bundle manifest, canonical
hashing/JSONL (mapping rows + request index), create-only/symlink-safe
atomic publication and a compact, aggregate-only committed summary.

This mirrors ``raptor.external.tsc2_sources.bundle`` closely but for the
``raptor.external.clipe_cdna_spdi_projector_bundle.v1`` manifest schema:
``build_projector_bundle_manifest`` computes the same canonical
``content_hash`` (SHA-256 of UTF-8 canonical JSON, sorted object keys,
``(",", ":")`` separators, array order preserved, only the top-level
``content_hash`` key itself excluded).

``canonical_mapping_jsonl_bytes``/``canonical_request_index_jsonl_bytes``
emit one canonical sorted-key JSON object per line, UTF-8, LF-only, with a
final newline -- deterministic regardless of input dict/JSON key order.
The request-index serializer additionally REDACTS any secret/tracking
query VALUE (``api_key``/``key``/``tool``/``email``) from
``requested_url``/``final_url`` before writing, keeping the query KEY
present (so ``api_key=REDACTED`` is visible without ever persisting the
actual secret), while every other field (notably ``body_sha256``) is
preserved verbatim.

``publish_projector_bundle`` reuses this repository's already-hardened
external/create-only/symlink-safe/race-safe/manifest-last publication
primitive -- ``raptor.external.tsc2_sources.bundle._publish_directory_
no_replace`` -- verbatim (the SAME function object, not a
reimplementation) for the actual atomic no-clobber directory rename, and
reuses that module's other private boundary helpers (run-name validation,
symlink-ancestry checks, the publication-reservation lock, and the safe
relative-path join) rather than duplicating their hardened, previously-
tested logic; boundary/hash violations raised by those helpers are
translated into this module's own ``ProjectorBundleBoundaryError``/
``ProjectorManifestError`` domain errors.

``build_committed_summary`` is a strict field-whitelist projection off an
already-built manifest: aggregate pins, counts and hashes only -- never a
per-row identity, HGVS/SPDI string, raw NCBI response body, score, or any
clinical/ACMG/evidence-strength claim (``boundaries.clinical_use`` /
``boundaries.evidence_strength_use`` are always ``"forbidden"`` in the
committed pilot summary).

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from raptor.external.tsc2_sources.bundle import BundleBoundaryError as _SourceBundleBoundaryError
from raptor.external.tsc2_sources.bundle import MANIFEST_FILENAME
from raptor.external.tsc2_sources.bundle import _assert_no_symlink_ancestry
from raptor.external.tsc2_sources.bundle import _publish_directory_no_replace
from raptor.external.tsc2_sources.bundle import _release_reservation
from raptor.external.tsc2_sources.bundle import _reserve_run_name
from raptor.external.tsc2_sources.bundle import _safe_join
from raptor.external.tsc2_sources.bundle import _validate_run_name

from .model import ClipeCdnaSpdiMappingRow, ProjectionContractError

PROJECTOR_BUNDLE_SCHEMA = "raptor.external.clipe_cdna_spdi_projector_bundle.v1"
PROJECTOR_SUMMARY_SCHEMA = "raptor.external.clipe_cdna_spdi_projector_summary.v1"

#: Query keys this slice never persists a real value for (spec
#: ``network_boundary.secret_handling`` / ``outputs.external_bundle.
#: artifacts.request_log.redaction``): the key name is kept (so an
#: auditor can see a secret WAS present) but its value is always replaced.
_REDACTED_QUERY_KEYS = frozenset({"api_key", "key", "tool", "email"})

#: Exact top-level field set a ``build_projector_bundle_manifest`` output
#: must have (see that function) -- an extra or missing top-level field is
#: a structural violation, never silently tolerated.
_REQUIRED_MANIFEST_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema", "bundle_id", "created_at", "input_scores", "reference", "endpoint_pins",
        "artifacts", "counts", "status_counts", "shape_counts", "success_count", "failure_count",
        "request_budget_observed", "pilot_uncertainties", "boundaries", "content_hash",
    }
)
#: Exact field set every manifest artifact record must have.
_REQUIRED_ARTIFACT_FIELDS = frozenset({"artifact_id", "relative_path", "byte_length", "sha256", "row_count"})
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ProjectorBundleBoundaryError(ValueError):
    """Raised for manifest schema violations and for output-path boundary
    violations: writing inside the repository, writing onto a pre-
    existing (create-only) final run path, or writing onto a symlink/
    reparse-point run leaf."""


class ProjectorManifestError(ValueError):
    """Raised when a manifest's ``content_hash`` does not match its
    recomputed canonical hash, or when a published artifact payload's
    actual bytes do not match its manifest-declared ``byte_length``/
    ``sha256``."""


def _redact_url_secrets(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    redacted_pairs = [(key, "REDACTED" if key in _REDACTED_QUERY_KEYS else value) for key, value in pairs]
    new_query = urlencode(redacted_pairs, safe="", quote_via=quote)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _canonical_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    lines = [json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for row in rows]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def canonical_mapping_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    """Revalidate every row by reconstructing it through
    ``model.ClipeCdnaSpdiMappingRow`` (never merely trusting its already-
    dict shape -- this re-runs the full vocabulary/cross-field-invariant
    contract, e.g. rejecting a malformed ``status`` or a malformed
    ``genomic_spdi``), reject a duplicate ``(source_id, source_row)`` key,
    then return one canonical, sorted-key compact JSON object per line
    (UTF-8, LF-only, final trailing newline) -- deterministic regardless
    of any row's dict/JSON key order. Raises ``model.
    ProjectionContractError`` on any row-contract violation or duplicate
    key."""
    seen: set[tuple[Any, Any]] = set()
    validated_rows: list[dict[str, Any]] = []
    for row in rows:
        validated = ClipeCdnaSpdiMappingRow(**row).to_dict()
        key = (validated["source_id"], validated["source_row"])
        if key in seen:
            raise ProjectionContractError(
                f"duplicate (source_id, source_row) key {key!r} in canonical mapping JSONL output"
            )
        seen.add(key)
        validated_rows.append(validated)
    return _canonical_jsonl_bytes(validated_rows)


def canonical_request_index_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    """Same as ``canonical_mapping_jsonl_bytes`` but first redacts any
    secret/tracking query VALUE from each row's ``requested_url``/
    ``final_url`` field (see module docstring); every other field
    (notably ``body_sha256``) is preserved verbatim."""
    sanitized: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        for field_name in ("requested_url", "final_url"):
            value = row.get(field_name)
            if isinstance(value, str):
                row[field_name] = _redact_url_secrets(value)
        sanitized.append(row)
    return _canonical_jsonl_bytes(sanitized)


def _is_safe_relative_path(relative_path: Any) -> bool:
    """A manifest artifact ``relative_path`` must be a non-blank, purely
    relative POSIX-style path with no ``.``/``..`` traversal component and
    no Windows drive letter -- ``"../escape.jsonl"`` and an absolute path
    are both rejected."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        return False
    if relative_path.startswith("/") or relative_path.startswith("\\"):
        return False
    posix = PurePosixPath(relative_path)
    if posix.is_absolute() or any(part in (".", "..") for part in posix.parts):
        return False
    if PureWindowsPath(relative_path).drive:
        return False
    return True


def _validate_manifest_structure(manifest: dict[str, Any]) -> None:
    """Strict structural validation of a ``build_projector_bundle_
    manifest`` output: the exact top-level field set, the exact per-
    artifact field set, unique artifact ids/relative_paths, safe
    (non-traversal, non-absolute) relative_paths, well-typed hashes/
    counts, and full count conservation -- ``success_count +
    failure_count``, the ``status_counts`` sum, the ``status_counts``
    ``PROJECTED_FASTA_VERIFIED`` entry (must equal ``success_count``
    exactly, not merely sum correctly), the ``shape_counts`` sum, and the
    ``mapping-jsonl`` artifact's own ``row_count`` must ALL equal
    ``input_scores["row_count"]``. Raises ``ProjectorManifestError`` on
    any violation. Called from BOTH ``build_projector_bundle_manifest``
    (before its content hash is computed) and ``validate_manifest_
    content_hash`` (before publication) -- a structurally invalid
    manifest is never allowed to acquire a valid-looking hash."""
    if set(manifest) != _REQUIRED_MANIFEST_TOP_LEVEL_FIELDS:
        missing = _REQUIRED_MANIFEST_TOP_LEVEL_FIELDS - set(manifest)
        extra = set(manifest) - _REQUIRED_MANIFEST_TOP_LEVEL_FIELDS
        raise ProjectorManifestError(
            "manifest does not have the exact required top-level fields; "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
        )

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list):
        raise ProjectorManifestError("manifest artifacts must be a list")

    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    artifacts_by_id: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != _REQUIRED_ARTIFACT_FIELDS:
            actual_keys = set(artifact) if isinstance(artifact, dict) else set()
            missing = _REQUIRED_ARTIFACT_FIELDS - actual_keys
            extra = actual_keys - _REQUIRED_ARTIFACT_FIELDS
            raise ProjectorManifestError(
                "manifest artifact does not have the exact required fields; "
                f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
            )
        artifact_id = artifact["artifact_id"]
        relative_path = artifact["relative_path"]
        sha256_value = artifact["sha256"]
        byte_length = artifact["byte_length"]
        row_count = artifact["row_count"]

        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ProjectorManifestError(f"artifact_id must be a non-blank string, got {artifact_id!r}")
        if artifact_id in seen_ids:
            raise ProjectorManifestError(f"duplicate artifact_id in manifest: {artifact_id!r}")
        seen_ids.add(artifact_id)

        if not _is_safe_relative_path(relative_path):
            raise ProjectorManifestError(
                f"artifact {artifact_id!r} relative_path is unsafe (absolute or traversal): "
                f"{relative_path!r}"
            )
        if relative_path in seen_paths:
            raise ProjectorManifestError(f"duplicate relative_path in manifest: {relative_path!r}")
        seen_paths.add(relative_path)

        if not isinstance(sha256_value, str) or not _SHA256_HEX_RE.match(sha256_value):
            raise ProjectorManifestError(
                f"artifact {artifact_id!r} sha256 is not a 64-hex-character string: {sha256_value!r}"
            )
        if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length < 0:
            raise ProjectorManifestError(
                f"artifact {artifact_id!r} byte_length must be a non-negative int: {byte_length!r}"
            )
        if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
            raise ProjectorManifestError(
                f"artifact {artifact_id!r} row_count must be a non-negative int: {row_count!r}"
            )
        artifacts_by_id[artifact_id] = artifact

    total_rows = manifest.get("input_scores", {}).get("row_count") if isinstance(manifest.get("input_scores"), dict) else None
    if not isinstance(total_rows, int) or isinstance(total_rows, bool) or total_rows < 0:
        raise ProjectorManifestError(f"input_scores.row_count must be a non-negative int: {total_rows!r}")

    success_count = manifest["success_count"]
    failure_count = manifest["failure_count"]
    if not isinstance(success_count, int) or isinstance(success_count, bool) or success_count < 0:
        raise ProjectorManifestError(f"success_count must be a non-negative int: {success_count!r}")
    if not isinstance(failure_count, int) or isinstance(failure_count, bool) or failure_count < 0:
        raise ProjectorManifestError(f"failure_count must be a non-negative int: {failure_count!r}")
    if success_count + failure_count != total_rows:
        raise ProjectorManifestError(
            f"success_count + failure_count ({success_count}+{failure_count}={success_count + failure_count}) "
            f"does not equal input_scores.row_count ({total_rows})"
        )

    status_counts = manifest["status_counts"]
    if not isinstance(status_counts, dict):
        raise ProjectorManifestError("status_counts must be a mapping")
    status_sum = sum(status_counts.values())
    if status_sum != total_rows:
        raise ProjectorManifestError(
            f"status_counts sum ({status_sum}) does not equal input_scores.row_count ({total_rows})"
        )
    projected_verified = status_counts.get("PROJECTED_FASTA_VERIFIED", 0)
    if projected_verified != success_count:
        raise ProjectorManifestError(
            f"status_counts['PROJECTED_FASTA_VERIFIED'] ({projected_verified}) does not equal "
            f"success_count ({success_count})"
        )

    shape_counts = manifest["shape_counts"]
    if not isinstance(shape_counts, dict):
        raise ProjectorManifestError("shape_counts must be a mapping")
    shape_sum = sum(shape_counts.values())
    if shape_sum != total_rows:
        raise ProjectorManifestError(
            f"shape_counts sum ({shape_sum}) does not equal input_scores.row_count ({total_rows})"
        )

    mapping_artifact = artifacts_by_id.get("mapping-jsonl")
    if mapping_artifact is not None and mapping_artifact["row_count"] != total_rows:
        raise ProjectorManifestError(
            f"mapping-jsonl artifact row_count ({mapping_artifact['row_count']}) does not equal "
            f"input_scores.row_count ({total_rows})"
        )


def compute_manifest_content_hash(manifest: dict[str, Any]) -> str:
    """SHA-256 of the manifest's UTF-8 canonical JSON (sorted object keys,
    ``(",", ":")`` separators, array order preserved), excluding ONLY the
    top-level ``content_hash`` key itself."""
    basis = {key: value for key, value in manifest.items() if key != "content_hash"}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_manifest_content_hash(manifest: dict[str, Any]) -> None:
    """Raise ``ProjectorManifestError`` if ``manifest['content_hash']`` is
    missing or does not match the manifest's recomputed canonical content
    hash, OR if the manifest fails strict structural validation (see
    ``_validate_manifest_structure``: exact field sets, unique/safe
    artifact ids/paths, and full count conservation)."""
    if "content_hash" not in manifest:
        raise ProjectorManifestError("manifest is missing the required content_hash field")
    recomputed = compute_manifest_content_hash(manifest)
    if recomputed != manifest["content_hash"]:
        raise ProjectorManifestError(
            f"manifest content_hash mismatch: recorded {manifest['content_hash']!r} != "
            f"recomputed {recomputed!r}"
        )
    _validate_manifest_structure(manifest)


def build_projector_bundle_manifest(
    *,
    bundle_id: str,
    created_at: str,
    input_scores: dict[str, Any],
    reference: dict[str, Any],
    endpoint_pins: dict[str, Any],
    artifacts: list[dict[str, Any]],
    status_counts: dict[str, int],
    shape_counts: dict[str, int],
    success_count: int,
    failure_count: int,
    boundaries: dict[str, Any],
    request_budget_observed: dict[str, Any] | None = None,
    pilot_uncertainties: list[str] | None = None,
) -> dict[str, Any]:
    """Build and canonically self-hash a
    ``raptor.external.clipe_cdna_spdi_projector_bundle.v1`` manifest from
    already-verified input pins, endpoint pins, artifact records and
    aggregate counts. Structurally validated (``_validate_manifest_
    structure``: exact field sets, unique/safe artifact ids/paths, and
    full count conservation) BEFORE its content hash is computed -- an
    invalid manifest never acquires a valid-looking hash."""
    artifacts = list(artifacts)
    manifest: dict[str, Any] = {
        "schema": PROJECTOR_BUNDLE_SCHEMA,
        "bundle_id": bundle_id,
        "created_at": created_at,
        "input_scores": dict(input_scores),
        "reference": dict(reference),
        "endpoint_pins": dict(endpoint_pins),
        "artifacts": artifacts,
        "counts": {"rows": input_scores.get("row_count"), "artifacts": len(artifacts)},
        "status_counts": dict(status_counts),
        "shape_counts": dict(shape_counts),
        "success_count": success_count,
        "failure_count": failure_count,
        "request_budget_observed": dict(request_budget_observed) if request_budget_observed else {},
        "pilot_uncertainties": list(pilot_uncertainties) if pilot_uncertainties else [],
        "boundaries": dict(boundaries),
        "content_hash": None,  # placeholder so the pre-hash field set matches the final shape
    }
    _validate_manifest_structure(manifest)
    manifest["content_hash"] = compute_manifest_content_hash(manifest)
    return manifest


def publish_projector_bundle(
    *,
    repo_root: Path,
    output_root: Path,
    run_name: str,
    manifest: dict[str, Any],
    mapping_payload: bytes,
    request_index_payload: bytes,
    raw_payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Publish ``manifest`` and its artifact payloads to
    ``output_root/run_name`` -- external, create-only, atomic and
    symlink-safe. ``mapping_payload``/``request_index_payload`` are looked
    up by their manifest ``artifact_id`` (``"mapping-jsonl"``/
    ``"request-index-jsonl"``); every other artifact's bytes are looked up
    in ``raw_payloads`` by its manifest ``relative_path``. Raises
    ``ProjectorBundleBoundaryError`` if ``run_name`` is not exactly one
    safe relative path component, if ``output_root`` (or any ancestor) is
    a symlink/reparse point, if ``output_root`` resolves inside
    ``repo_root``, if the final run path already exists (create-only), or
    if a concurrent compliant writer wins the publication race. Raises
    ``ProjectorManifestError`` if any artifact payload's bytes do not
    match its manifest-declared ``byte_length``/``sha256``, or if the
    manifest's own ``content_hash`` does not match its recomputed value.
    On ANY failure the staging directory is removed and NO manifest is
    ever published to the final run path; a competing writer's already-
    published final directory is never deleted/replaced/touched."""
    validate_manifest_content_hash(manifest)

    repo_root = Path(repo_root)
    output_root = Path(output_root)

    try:
        _validate_run_name(run_name)
    except _SourceBundleBoundaryError as exc:
        raise ProjectorBundleBoundaryError(str(exc)) from exc

    try:
        _assert_no_symlink_ancestry(output_root, role="output_root")
    except _SourceBundleBoundaryError as exc:
        raise ProjectorBundleBoundaryError(str(exc)) from exc

    resolved_repo_root = repo_root.resolve()
    resolved_output_root = output_root.resolve()
    try:
        resolved_output_root.relative_to(resolved_repo_root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    if inside_repo:
        raise ProjectorBundleBoundaryError(
            f"output_root {output_root} resolves inside repo_root {repo_root}; the external "
            "projector bundle must never be written inside the repository"
        )

    final_run_dir = output_root / run_name
    if final_run_dir.is_symlink():
        raise ProjectorBundleBoundaryError(
            f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
        )
    if final_run_dir.exists():
        raise ProjectorBundleBoundaryError(
            f"output run path {final_run_dir} already exists; runs are create-only and are "
            "never overwritten or silently resumed"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    try:
        _assert_no_symlink_ancestry(output_root, role="output_root")
    except _SourceBundleBoundaryError as exc:
        raise ProjectorBundleBoundaryError(str(exc)) from exc

    try:
        reservation_path = _reserve_run_name(output_root, run_name)
    except _SourceBundleBoundaryError as exc:
        raise ProjectorBundleBoundaryError(str(exc)) from exc

    try:
        if final_run_dir.is_symlink():
            raise ProjectorBundleBoundaryError(
                f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
            )
        if final_run_dir.exists():
            raise ProjectorBundleBoundaryError(
                f"output run path {final_run_dir} already exists; runs are create-only and are "
                "never overwritten or silently resumed"
            )

        staging_dir = output_root / f".{run_name}.staging-{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=False, exist_ok=False)

        try:
            for artifact in manifest["artifacts"]:
                artifact_id = artifact["artifact_id"]
                relative_path = artifact["relative_path"]
                if artifact_id == "mapping-jsonl":
                    payload = mapping_payload
                elif artifact_id == "request-index-jsonl":
                    payload = request_index_payload
                else:
                    payload = raw_payloads.get(relative_path)
                if payload is None:
                    raise ProjectorManifestError(
                        f"missing artifact payload bytes for relative_path {relative_path!r} "
                        f"(artifact_id={artifact_id!r})"
                    )
                if len(payload) != artifact["byte_length"]:
                    raise ProjectorManifestError(
                        f"artifact {artifact_id!r} byte_length mismatch: expected "
                        f"{artifact['byte_length']!r}, observed {len(payload)!r} bytes"
                    )
                observed_sha256 = hashlib.sha256(payload).hexdigest()
                if observed_sha256.lower() != artifact["sha256"].lower():
                    raise ProjectorManifestError(
                        f"artifact {artifact_id!r} sha256 mismatch: expected {artifact['sha256']!r}, "
                        f"observed {observed_sha256!r}"
                    )
                try:
                    destination = _safe_join(staging_dir, relative_path)
                except _SourceBundleBoundaryError as exc:
                    raise ProjectorBundleBoundaryError(str(exc)) from exc
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)

            manifest_path = staging_dir / MANIFEST_FILENAME
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        try:
            _publish_directory_no_replace(staging_dir, final_run_dir)
        except FileExistsError as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise ProjectorBundleBoundaryError(
                f"output run path {final_run_dir} was concurrently created by another writer "
                "during publication; refusing to replace a competing publication"
            ) from exc
        except OSError as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise ProjectorBundleBoundaryError(
                f"failed to atomically publish run directory {final_run_dir}: {exc}"
            ) from exc
    finally:
        _release_reservation(reservation_path)

    return {
        "run_dir": str(final_run_dir),
        "manifest_path": str(final_run_dir / MANIFEST_FILENAME),
    }


def build_committed_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the compact, aggregate-only committed pilot summary from an
    already-built bundle manifest: the manifest's own content hash, input/
    reference hashes, endpoint sequence pin, total/success/failure row
    counts, status/shape counts, observed request budget, residual pilot
    uncertainties, and boundary flags. NEVER includes a requested/final
    URL, an HGVS/SPDI string, a raw NCBI response body, a score, or any
    clinical/evidence-strength claim (enforced structurally: this function
    is a strict field-whitelist projection and reads/copies no field
    beyond the aggregate ones listed below)."""
    endpoint_pins = manifest.get("endpoint_pins", {})
    endpoint_sequence = endpoint_pins.get("step_sequence")
    if endpoint_sequence is None:
        endpoint_sequence = endpoint_pins.get("sequence")

    counts = manifest.get("counts", {})
    total_rows = counts.get("rows")
    if total_rows is None:
        total_rows = manifest.get("input_scores", {}).get("row_count")

    status_counts = dict(manifest.get("status_counts", {}))
    success_count = status_counts.get("PROJECTED_FASTA_VERIFIED", 0)
    failure_count = (total_rows - success_count) if total_rows is not None else None

    return {
        "schema": PROJECTOR_SUMMARY_SCHEMA,
        "bundle_id": manifest["bundle_id"],
        "manifest_content_hash": manifest["content_hash"],
        "input_scores_sha256": manifest["input_scores"]["sha256"],
        "reference_sha256": manifest["reference"]["sha256"],
        "endpoint_sequence": endpoint_sequence,
        "total_rows": total_rows,
        "success_count": success_count,
        "failure_count": failure_count,
        "status_counts": status_counts,
        "shape_counts": dict(manifest.get("shape_counts", {})),
        "request_budget_observed": dict(manifest.get("request_budget_observed", {})),
        "pilot_uncertainties": list(manifest.get("pilot_uncertainties", [])),
        "boundaries": dict(manifest.get("boundaries", {})),
    }


__all__ = [
    "PROJECTOR_BUNDLE_SCHEMA",
    "PROJECTOR_SUMMARY_SCHEMA",
    "ProjectorBundleBoundaryError",
    "ProjectorManifestError",
    "canonical_mapping_jsonl_bytes",
    "canonical_request_index_jsonl_bytes",
    "compute_manifest_content_hash",
    "validate_manifest_content_hash",
    "build_projector_bundle_manifest",
    "publish_projector_bundle",
    "build_committed_summary",
    "_publish_directory_no_replace",
]
