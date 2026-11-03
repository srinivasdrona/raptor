"""External VAMP-seq genomic-crosswalk bundle manifest, canonical hashing/
JSONL, create-only/symlink-safe atomic publication and a compact,
aggregate-only committed summary.

This mirrors ``raptor.external.tsc2_sources.bundle`` closely but for the
``raptor.external.vamp_genomic_crosswalk_bundle.v1`` manifest schema:
``build_crosswalk_bundle_manifest`` computes the same canonical
``content_hash`` (SHA-256 of UTF-8 canonical JSON, sorted object keys,
``(",", ":")`` separators, array order preserved, only the top-level
``content_hash`` key itself excluded) and structurally validates the
manifest (exact field sets, unique/safe artifact ids/paths, and full
``status_counts``/artifact-row-count conservation against ``counts.rows``)
BEFORE that hash is computed -- an invalid manifest never acquires a
valid-looking hash.

``canonical_crosswalk_jsonl_bytes`` revalidates every row by reconstructing
it through ``model.VampGenomicCrosswalkRow`` and rejects a duplicate
``(source_id, source_row)`` key, then emits one canonical sorted-key JSON
object per line, UTF-8, LF-only, with a final newline -- deterministic
regardless of input dict/JSON key order.

``publish_vamp_crosswalk_bundle`` reuses this repository's already-
hardened external/create-only/symlink-safe/race-safe/manifest-last
publication primitive -- ``raptor.external.tsc2_sources.bundle.
_publish_directory_no_replace`` -- verbatim (the SAME function object, not
a reimplementation) for the actual atomic no-clobber directory rename, and
reuses that module's other private boundary helpers (run-name validation,
symlink-ancestry checks, the publication-reservation lock, and the safe
relative-path join); boundary/hash violations raised by those helpers are
translated into this module's own ``VampCrosswalkBundleBoundaryError``/
``VampCrosswalkManifestError`` domain errors.

``build_committed_summary`` is a strict field-whitelist projection off an
already-built manifest: aggregate pins, counts, hashes and the archive's
public DOI/hash metadata only -- NEVER a per-row protein variant, hgvs_c,
genomic SPDI, score, or any clinical/evidence-strength claim.

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

from .model import CrosswalkContractError, VampGenomicCrosswalkRow

CROSSWALK_BUNDLE_SCHEMA = "raptor.external.vamp_genomic_crosswalk_bundle.v1"
CROSSWALK_SUMMARY_SCHEMA = "raptor.external.vamp_genomic_crosswalk_summary.v1"

_REQUIRED_MANIFEST_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema", "bundle_id", "created_at", "input_scores", "archive", "reference", "artifacts",
        "counts", "status_counts", "boundaries", "content_hash", "verified_unique_spdi",
        "follow_on_unresolved", "pacbio_fastq_download",
    }
)
_REQUIRED_ARTIFACT_FIELDS = frozenset({"artifact_id", "relative_path", "byte_length", "sha256", "row_count"})
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class VampCrosswalkBundleBoundaryError(ValueError):
    """Raised for manifest schema violations and for output-path boundary
    violations: writing inside the repository, writing onto a pre-
    existing (create-only) final run path, or writing onto a symlink/
    reparse-point run leaf."""


class VampCrosswalkManifestError(ValueError):
    """Raised when a manifest's ``content_hash`` does not match its
    recomputed canonical hash, when the manifest fails strict structural
    validation (exact field sets, unique/safe artifact ids/paths, or count
    conservation), or when a published artifact payload's actual bytes do
    not match its manifest-declared ``byte_length``/``sha256``."""


def _canonical_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    lines = [json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for row in rows]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def canonical_crosswalk_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    """Revalidate every row by reconstructing it through
    ``model.VampGenomicCrosswalkRow`` (never merely trusting its already-
    dict shape), reject a duplicate ``(source_id, source_row)`` key, then
    return one canonical, sorted-key compact JSON object per line (UTF-8,
    LF-only, final trailing newline) -- deterministic regardless of any
    row's dict/JSON key order. Raises ``model.CrosswalkContractError`` on
    any row-contract violation or duplicate key."""
    seen: set[tuple[Any, Any]] = set()
    validated_rows: list[dict[str, Any]] = []
    for row in rows:
        validated = VampGenomicCrosswalkRow(**row).to_dict()
        key = (validated["source_id"], validated["source_row"])
        if key in seen:
            raise CrosswalkContractError(
                f"duplicate (source_id, source_row) key {key!r} in canonical crosswalk JSONL output"
            )
        seen.add(key)
        validated_rows.append(validated)
    return _canonical_jsonl_bytes(validated_rows)


def _is_safe_relative_path(relative_path: Any) -> bool:
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
    """Strict structural validation of a ``build_crosswalk_bundle_
    manifest`` output: the exact top-level field set, the exact per-
    artifact field set, unique artifact ids/relative_paths, safe (non-
    traversal, non-absolute) relative_paths, well-typed hashes/counts, and
    full count conservation -- the ``status_counts`` sum and the
    ``crosswalk-jsonl`` artifact's own ``row_count`` must both equal
    ``counts["rows"]``. Raises ``VampCrosswalkManifestError`` on any
    violation. Called from BOTH ``build_crosswalk_bundle_manifest``
    (before its content hash is computed) and ``validate_manifest_
    content_hash`` (before publication)."""
    if set(manifest) != _REQUIRED_MANIFEST_TOP_LEVEL_FIELDS:
        missing = _REQUIRED_MANIFEST_TOP_LEVEL_FIELDS - set(manifest)
        extra = set(manifest) - _REQUIRED_MANIFEST_TOP_LEVEL_FIELDS
        raise VampCrosswalkManifestError(
            "manifest does not have the exact required top-level fields; "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
        )

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list):
        raise VampCrosswalkManifestError("manifest artifacts must be a list")

    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    artifacts_by_id: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != _REQUIRED_ARTIFACT_FIELDS:
            actual_keys = set(artifact) if isinstance(artifact, dict) else set()
            missing = _REQUIRED_ARTIFACT_FIELDS - actual_keys
            extra = actual_keys - _REQUIRED_ARTIFACT_FIELDS
            raise VampCrosswalkManifestError(
                "manifest artifact does not have the exact required fields; "
                f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
            )
        artifact_id = artifact["artifact_id"]
        relative_path = artifact["relative_path"]
        sha256_value = artifact["sha256"]
        byte_length = artifact["byte_length"]
        row_count = artifact["row_count"]

        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise VampCrosswalkManifestError(f"artifact_id must be a non-blank string, got {artifact_id!r}")
        if artifact_id in seen_ids:
            raise VampCrosswalkManifestError(f"duplicate artifact_id in manifest: {artifact_id!r}")
        seen_ids.add(artifact_id)

        if not _is_safe_relative_path(relative_path):
            raise VampCrosswalkManifestError(
                f"artifact {artifact_id!r} relative_path is unsafe (absolute or traversal): {relative_path!r}"
            )
        if relative_path in seen_paths:
            raise VampCrosswalkManifestError(f"duplicate relative_path in manifest: {relative_path!r}")
        seen_paths.add(relative_path)

        if not isinstance(sha256_value, str) or not _SHA256_HEX_RE.match(sha256_value):
            raise VampCrosswalkManifestError(
                f"artifact {artifact_id!r} sha256 is not a 64-hex-character string: {sha256_value!r}"
            )
        if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length < 0:
            raise VampCrosswalkManifestError(
                f"artifact {artifact_id!r} byte_length must be a non-negative int: {byte_length!r}"
            )
        if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
            raise VampCrosswalkManifestError(
                f"artifact {artifact_id!r} row_count must be a non-negative int: {row_count!r}"
            )
        artifacts_by_id[artifact_id] = artifact

    counts = manifest.get("counts")
    total_rows = counts.get("rows") if isinstance(counts, dict) else None
    if not isinstance(total_rows, int) or isinstance(total_rows, bool) or total_rows < 0:
        raise VampCrosswalkManifestError(f"counts.rows must be a non-negative int: {total_rows!r}")

    status_counts = manifest["status_counts"]
    if not isinstance(status_counts, dict):
        raise VampCrosswalkManifestError("status_counts must be a mapping")
    status_sum = sum(status_counts.values())
    if status_sum != total_rows:
        raise VampCrosswalkManifestError(
            f"status_counts sum ({status_sum}) does not equal counts.rows ({total_rows})"
        )

    crosswalk_artifact = artifacts_by_id.get("crosswalk-jsonl")
    if crosswalk_artifact is not None and crosswalk_artifact["row_count"] != total_rows:
        raise VampCrosswalkManifestError(
            f"crosswalk-jsonl artifact row_count ({crosswalk_artifact['row_count']}) does not equal "
            f"counts.rows ({total_rows})"
        )


def compute_manifest_content_hash(manifest: dict[str, Any]) -> str:
    """SHA-256 of the manifest's UTF-8 canonical JSON (sorted object keys,
    ``(",", ":")`` separators, array order preserved), excluding ONLY the
    top-level ``content_hash`` key itself."""
    basis = {key: value for key, value in manifest.items() if key != "content_hash"}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_manifest_content_hash(manifest: dict[str, Any]) -> None:
    """Raise ``VampCrosswalkManifestError`` if ``manifest['content_hash']``
    is missing or does not match the manifest's recomputed canonical
    content hash, OR if the manifest fails strict structural validation
    (see ``_validate_manifest_structure``)."""
    if "content_hash" not in manifest:
        raise VampCrosswalkManifestError("manifest is missing the required content_hash field")
    recomputed = compute_manifest_content_hash(manifest)
    if recomputed != manifest["content_hash"]:
        raise VampCrosswalkManifestError(
            f"manifest content_hash mismatch: recorded {manifest['content_hash']!r} != recomputed {recomputed!r}"
        )
    _validate_manifest_structure(manifest)


def build_crosswalk_bundle_manifest(
    *,
    bundle_id: str,
    created_at: str,
    input_scores: dict[str, Any],
    archive: dict[str, Any],
    reference: dict[str, Any],
    artifacts: list[dict[str, Any]],
    counts: dict[str, Any],
    status_counts: dict[str, int],
    boundaries: dict[str, Any],
    verified_unique_spdi: int | None = None,
    follow_on_unresolved: dict[str, int] | None = None,
    pacbio_download_decision: str = "NO_GO",
) -> dict[str, Any]:
    """Build and canonically self-hash a
    ``raptor.external.vamp_genomic_crosswalk_bundle.v1`` manifest from
    already-verified input pins, archive/reference pins, artifact records
    and aggregate counts. Structurally validated (``_validate_manifest_
    structure``) BEFORE its content hash is computed -- an invalid
    manifest never acquires a valid-looking hash. ``pacbio_download_
    decision`` is stored under the manifest's fixed
    ``pacbio_fastq_download`` key (spec ``go_no_go.pacbio_fastq_download``)."""
    manifest: dict[str, Any] = {
        "schema": CROSSWALK_BUNDLE_SCHEMA,
        "bundle_id": bundle_id,
        "created_at": created_at,
        "input_scores": dict(input_scores),
        "archive": dict(archive),
        "reference": dict(reference),
        "artifacts": list(artifacts),
        "counts": dict(counts),
        "status_counts": dict(status_counts),
        "boundaries": dict(boundaries),
        "verified_unique_spdi": verified_unique_spdi,
        "follow_on_unresolved": dict(follow_on_unresolved) if follow_on_unresolved else {},
        "pacbio_fastq_download": pacbio_download_decision,
        "content_hash": None,  # placeholder so the pre-hash field set matches the final shape
    }
    _validate_manifest_structure(manifest)
    manifest["content_hash"] = compute_manifest_content_hash(manifest)
    return manifest


def publish_vamp_crosswalk_bundle(
    *,
    repo_root: Path,
    output_root: Path,
    run_name: str,
    manifest: dict[str, Any],
    crosswalk_payload: bytes,
    archive_payload: bytes,
) -> dict[str, Any]:
    """Publish ``manifest`` and its two artifact payloads
    (``crosswalk_payload`` keyed to the manifest's ``"crosswalk-jsonl"``
    artifact_id, ``archive_payload`` keyed to ``"raw-archive"``) to
    ``output_root/run_name`` -- external, create-only, atomic and
    symlink-safe. Raises ``VampCrosswalkBundleBoundaryError`` on any
    create-only/symlink/repo-containment/publication-race violation, and
    ``VampCrosswalkManifestError`` on a manifest-hash/structure or
    artifact byte-length/hash mismatch. On ANY failure the staging
    directory is removed and NO manifest is ever published to the final
    run path; a competing writer's already-published final directory is
    never deleted/replaced/touched."""
    validate_manifest_content_hash(manifest)

    repo_root = Path(repo_root)
    output_root = Path(output_root)

    try:
        _validate_run_name(run_name)
    except _SourceBundleBoundaryError as exc:
        raise VampCrosswalkBundleBoundaryError(str(exc)) from exc

    try:
        _assert_no_symlink_ancestry(output_root, role="output_root")
    except _SourceBundleBoundaryError as exc:
        raise VampCrosswalkBundleBoundaryError(str(exc)) from exc

    resolved_repo_root = repo_root.resolve()
    resolved_output_root = output_root.resolve()
    try:
        resolved_output_root.relative_to(resolved_repo_root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    if inside_repo:
        raise VampCrosswalkBundleBoundaryError(
            f"output_root {output_root} resolves inside repo_root {repo_root}; the external "
            "crosswalk bundle must never be written inside the repository"
        )

    final_run_dir = output_root / run_name
    if final_run_dir.is_symlink():
        raise VampCrosswalkBundleBoundaryError(
            f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
        )
    if final_run_dir.exists():
        raise VampCrosswalkBundleBoundaryError(
            f"output run path {final_run_dir} already exists; runs are create-only and are never "
            "overwritten or silently resumed"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    try:
        _assert_no_symlink_ancestry(output_root, role="output_root")
    except _SourceBundleBoundaryError as exc:
        raise VampCrosswalkBundleBoundaryError(str(exc)) from exc

    try:
        reservation_path = _reserve_run_name(output_root, run_name)
    except _SourceBundleBoundaryError as exc:
        raise VampCrosswalkBundleBoundaryError(str(exc)) from exc

    try:
        if final_run_dir.is_symlink():
            raise VampCrosswalkBundleBoundaryError(
                f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
            )
        if final_run_dir.exists():
            raise VampCrosswalkBundleBoundaryError(
                f"output run path {final_run_dir} already exists; runs are create-only and are "
                "never overwritten or silently resumed"
            )

        staging_dir = output_root / f".{run_name}.staging-{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=False, exist_ok=False)

        try:
            for artifact in manifest["artifacts"]:
                artifact_id = artifact["artifact_id"]
                relative_path = artifact["relative_path"]
                if artifact_id == "crosswalk-jsonl":
                    payload = crosswalk_payload
                elif artifact_id == "raw-archive":
                    payload = archive_payload
                else:
                    payload = None
                if payload is None:
                    raise VampCrosswalkManifestError(
                        f"missing artifact payload bytes for relative_path {relative_path!r} "
                        f"(artifact_id={artifact_id!r})"
                    )
                if len(payload) != artifact["byte_length"]:
                    raise VampCrosswalkManifestError(
                        f"artifact {artifact_id!r} byte_length mismatch: expected "
                        f"{artifact['byte_length']!r}, observed {len(payload)!r} bytes"
                    )
                observed_sha256 = hashlib.sha256(payload).hexdigest()
                if observed_sha256.lower() != artifact["sha256"].lower():
                    raise VampCrosswalkManifestError(
                        f"artifact {artifact_id!r} sha256 mismatch: expected {artifact['sha256']!r}, "
                        f"observed {observed_sha256!r}"
                    )
                try:
                    destination = _safe_join(staging_dir, relative_path)
                except _SourceBundleBoundaryError as exc:
                    raise VampCrosswalkBundleBoundaryError(str(exc)) from exc
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
            raise VampCrosswalkBundleBoundaryError(
                f"output run path {final_run_dir} was concurrently created by another writer "
                "during publication; refusing to replace a competing publication"
            ) from exc
        except OSError as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise VampCrosswalkBundleBoundaryError(
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
    reference hashes, the archive's public DOI/hash metadata, counts,
    status counts, verified-unique-SPDI count, residual follow-on
    unresolved counts, boundary flags, and the fixed PacBio no-go decision.
    NEVER includes a protein variant, hgvs_c string, genomic SPDI, score,
    functional class, or any clinical/evidence-strength claim (enforced
    structurally: this function is a strict field-whitelist projection and
    reads/copies no field beyond the aggregate ones listed below)."""
    return {
        "schema": CROSSWALK_SUMMARY_SCHEMA,
        "bundle_id": manifest["bundle_id"],
        "manifest_content_hash": manifest["content_hash"],
        "archive": dict(manifest.get("archive", {})),
        "input_scores_sha256": manifest["input_scores"]["sha256"],
        "reference_sha256": manifest["reference"]["sha256"],
        "counts": dict(manifest.get("counts", {})),
        "status_counts": dict(manifest.get("status_counts", {})),
        "verified_unique_spdi": manifest.get("verified_unique_spdi"),
        "follow_on_unresolved": dict(manifest.get("follow_on_unresolved", {})),
        "boundaries": dict(manifest.get("boundaries", {})),
        "pacbio_fastq_download": manifest.get("pacbio_fastq_download", "NO_GO"),
    }


__all__ = [
    "CROSSWALK_BUNDLE_SCHEMA",
    "CROSSWALK_SUMMARY_SCHEMA",
    "VampCrosswalkBundleBoundaryError",
    "VampCrosswalkManifestError",
    "canonical_crosswalk_jsonl_bytes",
    "compute_manifest_content_hash",
    "validate_manifest_content_hash",
    "build_crosswalk_bundle_manifest",
    "publish_vamp_crosswalk_bundle",
    "build_committed_summary",
    "_publish_directory_no_replace",
]
