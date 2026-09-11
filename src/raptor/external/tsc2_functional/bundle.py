"""RAPTOR v2 TSC2 functional normalization -- output bundle manifest,
canonical hashing/JSONL, create-only/symlink-safe publication and a
compact, aggregate-only committed summary.

This mirrors ``raptor.external.tsc2_sources.bundle`` (the source-ingestion
bundle) closely but for the ``raptor.external.tsc2_functional_identity_
bundle.v1`` manifest schema: ``build_normalization_manifest`` computes the
same canonical ``content_hash`` (SHA-256 of UTF-8 canonical JSON, sorted
object keys, ``(",", ":")`` separators, array order preserved, only the
top-level ``content_hash`` key itself excluded).

``canonical_jsonl_bytes`` validates every row's exact field set and
rejects a duplicate ``(source_id, source_row)`` key, then emits one
canonical sorted-key JSON object per line, UTF-8, LF-only, with a final
newline -- deterministic regardless of input dict/JSON key order.

``publish_normalized_bundle`` reuses this package's already-hardened
external/create-only/symlink-safe/race-safe/manifest-last publication
primitive -- ``raptor.external.tsc2_sources.bundle._publish_directory_
no_replace`` -- verbatim (the SAME function object, not a reimplementation)
for the actual atomic no-clobber directory rename, and reuses that
module's other private boundary helpers (run-name validation, symlink-
ancestry checks, the publication-reservation lock, and the safe relative-
path join) rather than duplicating their hardened, previously-tested
logic; boundary/hash violations raised by those helpers are translated
into this module's own ``FunctionalBundleBoundaryError``/
``NormalizationManifestError`` domain errors.

``build_committed_summary`` is a strict field-whitelist projection off an
already-built manifest: aggregate pins, counts and hashes only -- never a
per-row identity, HGVS/SPDI string, raw score, source functional class, or
any clinical/evidence-strength claim.

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

from raptor.external.tsc2_sources.bundle import BundleBoundaryError as _SourceBundleBoundaryError
from raptor.external.tsc2_sources.bundle import MANIFEST_FILENAME
from raptor.external.tsc2_sources.bundle import _assert_no_symlink_ancestry
from raptor.external.tsc2_sources.bundle import _publish_directory_no_replace
from raptor.external.tsc2_sources.bundle import _release_reservation
from raptor.external.tsc2_sources.bundle import _reserve_run_name
from raptor.external.tsc2_sources.bundle import _safe_join
from raptor.external.tsc2_sources.bundle import _validate_run_name

from .model import (
    ALLOWED_IDENTITY_STATES,
    ALLOWED_VARIANT_KINDS,
    IDENTITY_STATE_TO_UNRESOLVED_REASON,
    REQUIRED_ROW_FIELDS,
    NormalizationContractError,
    NormalizedFunctionalRow,
)

FUNCTIONAL_BUNDLE_SCHEMA = "raptor.external.tsc2_functional_identity_bundle.v1"
FUNCTIONAL_SUMMARY_SCHEMA = "raptor.external.tsc2_functional_identity_summary.v1"

_REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "bundle_id",
        "created_at",
        "input_bundle",
        "reference",
        "artifacts",
        "counts",
        "identity_state_counts",
        "variant_kind_counts",
        "boundaries",
        "content_hash",
    }
)
_REQUIRED_MANIFEST_FIELDS_NO_HASH = _REQUIRED_MANIFEST_FIELDS - {"content_hash"}

_REQUIRED_ARTIFACT_FIELDS = frozenset(
    {"artifact_id", "source_id", "relative_path", "byte_length", "sha256", "row_count"}
)
_REQUIRED_COUNTS_FIELDS = frozenset({"sources", "artifacts", "rows"})
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")

#: Known follow-on normalization gaps (spec ``follow_on``) -- static,
#: aggregate-only text, never a clinical/evidence-strength claim.
_NORMALIZATION_GAPS: tuple[str, ...] = (
    "VAMP-seq protein-level scores lack a frozen nucleotide crosswalk needed to project "
    "transcript or genomic identity",
    "cliPE cDNA scores lack an injected NM_000548.5-to-genome projector needed for genomic "
    "SPDI resolution",
    "SGE genomic-reference-mismatch rows require adjudication with the source owners",
    "source-specific score transformations have not been reproduced in this slice",
    "no calibration, leakage-partition or knowledge-base overlap computation has been "
    "performed for this slice",
)


class FunctionalBundleBoundaryError(ValueError):
    """Raised for normalization-manifest schema violations and for
    output-path boundary violations: writing inside the repository,
    writing onto a pre-existing (create-only) final run path, or writing
    onto a symlink/reparse-point run leaf."""


class NormalizationManifestError(ValueError):
    """Raised when a normalization manifest's ``content_hash`` does not
    match its recomputed canonical hash, when a normalized artifact's
    actual bytes do not match its manifest-declared ``byte_length``/
    ``sha256``, or when the manifest itself violates its schema/
    conservation invariants (exact field sets, no duplicate artifact_id/
    source_id/relative_path, and exact count/sum relationships between
    ``counts``, ``identity_state_counts``, ``variant_kind_counts`` and the
    artifacts' own ``row_count`` values)."""


def _validate_safe_relative_path(relative_path: Any, *, context: str) -> None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise NormalizationManifestError(f"{context}: relative_path must be a non-blank string")
    if PureWindowsPath(relative_path).drive or PurePosixPath(relative_path).is_absolute():
        raise NormalizationManifestError(f"{context}: relative_path must not be absolute: {relative_path!r}")
    parts = PurePosixPath(relative_path).parts
    if not parts or any(part in (".", "..") for part in parts):
        raise NormalizationManifestError(
            f"{context}: relative_path must not contain traversal components: {relative_path!r}"
        )


def _validate_artifact_record(artifact: Any, *, index: int) -> None:
    if not isinstance(artifact, dict) or set(artifact) != _REQUIRED_ARTIFACT_FIELDS:
        actual = set(artifact) if isinstance(artifact, dict) else set()
        missing = _REQUIRED_ARTIFACT_FIELDS - actual
        extra = actual - _REQUIRED_ARTIFACT_FIELDS
        raise NormalizationManifestError(
            f"artifacts[{index}] does not have the exact required fields; "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
        )
    if not isinstance(artifact["artifact_id"], str) or not artifact["artifact_id"].strip():
        raise NormalizationManifestError(f"artifacts[{index}].artifact_id must be a non-blank string")
    if not isinstance(artifact["source_id"], str) or not artifact["source_id"].strip():
        raise NormalizationManifestError(f"artifacts[{index}].source_id must be a non-blank string")
    _validate_safe_relative_path(artifact["relative_path"], context=f"artifacts[{index}]")
    byte_length = artifact["byte_length"]
    if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length < 0:
        raise NormalizationManifestError(f"artifacts[{index}].byte_length must be a non-negative int")
    row_count = artifact["row_count"]
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
        raise NormalizationManifestError(f"artifacts[{index}].row_count must be a non-negative int")
    sha256 = artifact["sha256"]
    if not isinstance(sha256, str) or not _SHA256_HEX_RE.match(sha256):
        raise NormalizationManifestError(f"artifacts[{index}].sha256 must be a 64-hex-digit string")


def _validate_manifest_contract(manifest: dict[str, Any], *, require_content_hash: bool) -> None:
    """Validate a normalization manifest's exact schema and conservation
    invariants: exact top-level/artifact/counts field sets, no duplicate
    artifact_id/source_id/relative_path, and exact sum relationships
    between ``counts.rows``, the artifacts' own ``row_count`` values, and
    ``identity_state_counts``/``variant_kind_counts`` (which must also use
    only the fixed allowed vocabularies). Raises
    ``NormalizationManifestError`` on any violation."""
    expected_fields = _REQUIRED_MANIFEST_FIELDS if require_content_hash else _REQUIRED_MANIFEST_FIELDS_NO_HASH
    if set(manifest) != expected_fields:
        missing = expected_fields - set(manifest)
        extra = set(manifest) - expected_fields
        raise NormalizationManifestError(
            f"manifest does not have the exact required fields; missing={sorted(missing)!r} "
            f"extra={sorted(extra)!r}"
        )
    if manifest["schema"] != FUNCTIONAL_BUNDLE_SCHEMA:
        raise NormalizationManifestError(
            f"manifest schema must be {FUNCTIONAL_BUNDLE_SCHEMA!r}, got {manifest['schema']!r}"
        )

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise NormalizationManifestError("manifest.artifacts must be a non-empty list")

    seen_artifact_ids: set[str] = set()
    seen_source_ids: set[str] = set()
    seen_relative_paths: set[str] = set()
    total_row_count = 0
    for index, artifact in enumerate(artifacts):
        _validate_artifact_record(artifact, index=index)
        artifact_id = artifact["artifact_id"]
        source_id = artifact["source_id"]
        relative_path = artifact["relative_path"]
        if artifact_id in seen_artifact_ids:
            raise NormalizationManifestError(f"duplicate artifact_id {artifact_id!r} in manifest.artifacts")
        seen_artifact_ids.add(artifact_id)
        if source_id in seen_source_ids:
            raise NormalizationManifestError(f"duplicate source_id {source_id!r} in manifest.artifacts")
        seen_source_ids.add(source_id)
        if relative_path in seen_relative_paths:
            raise NormalizationManifestError(
                f"duplicate relative_path {relative_path!r} in manifest.artifacts"
            )
        seen_relative_paths.add(relative_path)
        total_row_count += artifact["row_count"]

    counts = manifest["counts"]
    if not isinstance(counts, dict) or set(counts) != _REQUIRED_COUNTS_FIELDS:
        raise NormalizationManifestError(
            f"manifest.counts must have exactly the fields {sorted(_REQUIRED_COUNTS_FIELDS)!r}"
        )
    if counts["artifacts"] != len(artifacts):
        raise NormalizationManifestError(
            f"manifest.counts.artifacts {counts['artifacts']!r} does not match the artifacts list "
            f"length {len(artifacts)!r}"
        )
    if counts["sources"] != len(seen_source_ids):
        raise NormalizationManifestError(
            f"manifest.counts.sources {counts['sources']!r} does not match the number of unique "
            f"artifact source_id values {len(seen_source_ids)!r}"
        )
    if total_row_count != counts["rows"]:
        raise NormalizationManifestError(
            f"sum of artifact row_count values {total_row_count!r} does not match "
            f"manifest.counts.rows {counts['rows']!r}"
        )

    identity_state_counts = manifest["identity_state_counts"]
    unknown_states = set(identity_state_counts) - ALLOWED_IDENTITY_STATES
    if unknown_states:
        raise NormalizationManifestError(
            f"manifest.identity_state_counts has unknown identity_state key(s): {sorted(unknown_states)!r}"
        )
    if sum(identity_state_counts.values()) != counts["rows"]:
        raise NormalizationManifestError(
            "manifest.identity_state_counts values do not sum to manifest.counts.rows"
        )

    variant_kind_counts = manifest["variant_kind_counts"]
    unknown_kinds = set(variant_kind_counts) - ALLOWED_VARIANT_KINDS
    if unknown_kinds:
        raise NormalizationManifestError(
            f"manifest.variant_kind_counts has unknown variant_kind key(s): {sorted(unknown_kinds)!r}"
        )
    if sum(variant_kind_counts.values()) != counts["rows"]:
        raise NormalizationManifestError(
            "manifest.variant_kind_counts values do not sum to manifest.counts.rows"
        )


def compute_manifest_content_hash(manifest: dict[str, Any]) -> str:
    """SHA-256 of the manifest's UTF-8 canonical JSON (sorted object keys,
    ``(",", ":")`` separators, array order preserved), excluding ONLY the
    top-level ``content_hash`` key itself."""
    basis = {key: value for key, value in manifest.items() if key != "content_hash"}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_manifest_content_hash(manifest: dict[str, Any]) -> None:
    """Raise ``NormalizationManifestError`` if the manifest violates its
    own schema/conservation invariants (``_validate_manifest_contract``),
    or if ``manifest['content_hash']`` does not match the manifest's
    recomputed canonical content hash."""
    _validate_manifest_contract(manifest, require_content_hash=True)
    recomputed = compute_manifest_content_hash(manifest)
    if recomputed != manifest["content_hash"]:
        raise NormalizationManifestError(
            f"normalization manifest content_hash mismatch: recorded {manifest['content_hash']!r} "
            f"!= recomputed {recomputed!r}"
        )


def build_normalization_manifest(
    *,
    bundle_id: str,
    created_at: str,
    input_bundle: dict[str, Any],
    reference: dict[str, Any],
    artifacts: list[dict[str, Any]],
    counts: dict[str, Any],
    identity_state_counts: dict[str, int],
    variant_kind_counts: dict[str, int],
    boundaries: dict[str, Any],
) -> dict[str, Any]:
    """Build, validate and canonically self-hash a
    ``raptor.external.tsc2_functional_identity_bundle.v1`` manifest. Raises
    ``NormalizationManifestError`` if the assembled manifest violates its
    schema/conservation invariants (see ``_validate_manifest_contract``)."""
    manifest: dict[str, Any] = {
        "schema": FUNCTIONAL_BUNDLE_SCHEMA,
        "bundle_id": bundle_id,
        "created_at": created_at,
        "input_bundle": dict(input_bundle),
        "reference": dict(reference),
        "artifacts": [dict(artifact) for artifact in artifacts],
        "counts": dict(counts),
        "identity_state_counts": dict(identity_state_counts),
        "variant_kind_counts": dict(variant_kind_counts),
        "boundaries": dict(boundaries),
    }
    _validate_manifest_contract(manifest, require_content_hash=False)
    manifest["content_hash"] = compute_manifest_content_hash(manifest)
    return manifest


def canonical_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    """Validate and fully revalidate every row (reconstructing it through
    ``model.NormalizedFunctionalRow`` -- never merely checking its key
    set) and reject a duplicate ``(source_id, source_row)`` key, then
    return one canonical sorted-key compact JSON object per line, UTF-8,
    LF-only, with a final newline. Deterministic regardless of any row's
    dict/JSON key order, and regardless of reordering unrelated rows --
    only a byte change to an actual row changes the output."""
    seen: set[tuple[Any, Any]] = set()
    lines: list[str] = []
    for row in rows:
        row_keys = set(row)
        if row_keys != REQUIRED_ROW_FIELDS:
            missing = REQUIRED_ROW_FIELDS - row_keys
            extra = row_keys - REQUIRED_ROW_FIELDS
            raise NormalizationContractError(
                "normalized row does not have the exact required fields; "
                f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
            )
        validated = NormalizedFunctionalRow(**row).to_dict()
        key = (validated["source_id"], validated["source_row"])
        if key in seen:
            raise NormalizationContractError(
                f"duplicate (source_id, source_row) key {key!r} in canonical JSONL output"
            )
        seen.add(key)
        lines.append(json.dumps(validated, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def publish_normalized_bundle(
    *,
    repo_root: Path,
    output_root: Path,
    run_name: str,
    manifest: dict[str, Any],
    artifact_payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Publish ``manifest`` and ``artifact_payloads`` (keyed by
    ``relative_path``) to ``output_root/run_name`` -- external,
    create-only, atomic and symlink-safe. Reuses
    ``raptor.external.tsc2_sources.bundle``'s already-hardened private
    boundary helpers (translating any ``BundleBoundaryError`` they raise
    into ``FunctionalBundleBoundaryError``) and its exact
    ``_publish_directory_no_replace`` primitive for the actual atomic
    no-clobber directory rename. On ANY failure the staging directory is
    removed and NO manifest is ever published to the final run path; a
    competing writer's already-published final directory is never
    deleted/replaced/touched."""
    validate_manifest_content_hash(manifest)

    repo_root = Path(repo_root)
    output_root = Path(output_root)

    try:
        _validate_run_name(run_name)
    except _SourceBundleBoundaryError as exc:
        raise FunctionalBundleBoundaryError(str(exc)) from exc

    try:
        _assert_no_symlink_ancestry(output_root, role="output_root")
    except _SourceBundleBoundaryError as exc:
        raise FunctionalBundleBoundaryError(str(exc)) from exc

    resolved_repo_root = repo_root.resolve()
    resolved_output_root = output_root.resolve()
    try:
        resolved_output_root.relative_to(resolved_repo_root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    if inside_repo:
        raise FunctionalBundleBoundaryError(
            f"output_root {output_root} resolves inside repo_root {repo_root}; the external "
            "normalization bundle must never be written inside the repository"
        )

    final_run_dir = output_root / run_name
    if final_run_dir.is_symlink():
        raise FunctionalBundleBoundaryError(
            f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
        )
    if final_run_dir.exists():
        raise FunctionalBundleBoundaryError(
            f"output run path {final_run_dir} already exists; runs are create-only and are "
            "never overwritten or silently resumed"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    try:
        _assert_no_symlink_ancestry(output_root, role="output_root")
    except _SourceBundleBoundaryError as exc:
        raise FunctionalBundleBoundaryError(str(exc)) from exc

    try:
        reservation_path = _reserve_run_name(output_root, run_name)
    except _SourceBundleBoundaryError as exc:
        raise FunctionalBundleBoundaryError(str(exc)) from exc

    try:
        if final_run_dir.is_symlink():
            raise FunctionalBundleBoundaryError(
                f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
            )
        if final_run_dir.exists():
            raise FunctionalBundleBoundaryError(
                f"output run path {final_run_dir} already exists; runs are create-only and are "
                "never overwritten or silently resumed"
            )

        staging_dir = output_root / f".{run_name}.staging-{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=False, exist_ok=False)

        try:
            for artifact in manifest["artifacts"]:
                relative_path = artifact["relative_path"]
                payload = artifact_payloads.get(relative_path)
                if payload is None:
                    raise NormalizationManifestError(
                        f"missing normalized artifact payload bytes for relative_path "
                        f"{relative_path!r} (artifact_id={artifact.get('artifact_id')!r})"
                    )
                if len(payload) != artifact["byte_length"]:
                    raise NormalizationManifestError(
                        f"artifact {artifact['artifact_id']!r} byte_length mismatch: expected "
                        f"{artifact['byte_length']!r}, observed {len(payload)!r} bytes"
                    )
                observed_sha256 = hashlib.sha256(payload).hexdigest()
                if observed_sha256.lower() != artifact["sha256"].lower():
                    raise NormalizationManifestError(
                        f"artifact {artifact['artifact_id']!r} sha256 mismatch: expected "
                        f"{artifact['sha256']!r}, observed {observed_sha256!r}"
                    )
                destination = _safe_join(staging_dir, relative_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)

            manifest_path = staging_dir / MANIFEST_FILENAME
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                encoding="utf-8",
            )
        except _SourceBundleBoundaryError as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise FunctionalBundleBoundaryError(str(exc)) from exc
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        try:
            _publish_directory_no_replace(staging_dir, final_run_dir)
        except FileExistsError as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise FunctionalBundleBoundaryError(
                f"output run path {final_run_dir} was concurrently created by another writer "
                "during publication; refusing to replace a competing publication"
            ) from exc
        except OSError as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise FunctionalBundleBoundaryError(
                f"failed to atomically publish run directory {final_run_dir}: {exc}"
            ) from exc
    finally:
        _release_reservation(reservation_path)

    return {
        "run_dir": str(final_run_dir),
        "manifest_path": str(final_run_dir / MANIFEST_FILENAME),
    }


def build_committed_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the compact, aggregate-only committed summary from an
    already-built normalization manifest: pins/hashes, counts, per-source
    row counts, per-artifact integrity metadata, aggregate unresolved-
    reason counts (derived deterministically from
    ``identity_state_counts`` via
    ``model.IDENTITY_STATE_TO_UNRESOLVED_REASON``) and a fixed list of
    known follow-on normalization gaps. NEVER includes a per-row identity,
    HGVS/SPDI string, raw score, source functional class, patient
    information, or any clinical/evidence-strength claim (enforced
    structurally: this function is a strict field-whitelist projection)."""
    identity_state_counts = manifest["identity_state_counts"]
    unresolved_reason_counts: dict[str, int] = {}
    for state, reason in IDENTITY_STATE_TO_UNRESOLVED_REASON.items():
        if reason is None:
            continue
        unresolved_reason_counts[reason] = identity_state_counts.get(state, 0)

    source_row_counts = {
        artifact["source_id"]: artifact["row_count"] for artifact in manifest["artifacts"]
    }
    artifact_integrity = {
        artifact["artifact_id"]: {
            "source_id": artifact["source_id"],
            "sha256": artifact["sha256"],
            "byte_length": artifact["byte_length"],
            "row_count": artifact["row_count"],
        }
        for artifact in manifest["artifacts"]
    }

    return {
        "schema": FUNCTIONAL_SUMMARY_SCHEMA,
        "bundle_id": manifest["bundle_id"],
        "manifest_content_hash": manifest["content_hash"],
        "input_bundle_content_hash": manifest["input_bundle"]["content_hash"],
        "reference_sha256": manifest["reference"]["sha256"],
        "counts": manifest["counts"],
        "identity_state_counts": identity_state_counts,
        "variant_kind_counts": manifest["variant_kind_counts"],
        "source_row_counts": source_row_counts,
        "artifact_integrity": artifact_integrity,
        "unresolved_reason_counts": unresolved_reason_counts,
        "normalization_gaps": list(_NORMALIZATION_GAPS),
    }


__all__ = [
    "FUNCTIONAL_BUNDLE_SCHEMA",
    "FUNCTIONAL_SUMMARY_SCHEMA",
    "FunctionalBundleBoundaryError",
    "NormalizationManifestError",
    "compute_manifest_content_hash",
    "validate_manifest_content_hash",
    "build_normalization_manifest",
    "canonical_jsonl_bytes",
    "publish_normalized_bundle",
    "build_committed_summary",
    "_publish_directory_no_replace",
]
