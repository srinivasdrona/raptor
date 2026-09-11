"""External TSC2 source-ingestion bundle manifest, canonical hashing,
create-only/symlink-safe atomic publication and a compact, aggregate-only
committed pilot summary.

A bundle manifest (``raptor.external.tsc2_source_bundle.v1``) is built by
``build_bundle_manifest`` from already-verified ``fetched_artifact`` and
``source_record`` dicts (see the spec's ``schemas`` section) -- it validates
each record's EXACT field set, cross-references every ``source.artifact_ids``
entry against the ``artifacts`` list (and vice versa), rejects forbidden
clinical/ACMG/classification status vocabulary
(``assert_no_forbidden_status_vocabulary``), and computes a canonical
``content_hash`` (SHA-256 of UTF-8 canonical JSON -- sorted object keys,
``(",", ":")`` separators, array order preserved, only the top-level
``content_hash`` key itself excluded) that is key-order invariant but
byte-sensitive to any artifact/source content change.

``write_bundle_run`` publishes a manifest + its artifact payloads to an
EXTERNAL (never-inside-the-repo), create-only, symlink-safe run directory:
every artifact is hashed/length-verified against its manifest record, all
bytes are written to a unique staging sibling directory first, the manifest
is written into that staging directory LAST, and only then is the whole
staging directory atomically renamed onto the (never pre-existing) final
run path. Any failure during staging removes the staging directory and
raises -- the final run path is never created and no manifest is ever
published for a partial/failed run.

This module performs no network I/O and never imports ``raptor.sourceops``,
``raptor.scorer``, ``raptor.eval``, ``raptor.packet``, ``raptor.census``,
``raptor.kb`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

BUNDLE_MANIFEST_SCHEMA = "raptor.external.tsc2_source_bundle.v1"
PILOT_SUMMARY_SCHEMA = "raptor.external.tsc2_source_pilot_summary.v1"
MANIFEST_FILENAME = "bundle_manifest.json"

_REQUIRED_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_id",
        "source_id",
        "role",
        "requested_url",
        "final_url",
        "http_status",
        "media_type",
        "relative_path",
        "byte_length",
        "sha256",
        "md5",
        "fetched_at",
        "verification",
    }
)
_VALID_VERIFICATIONS = frozenset({"HASHED", "PUBLISHED_MD5_VERIFIED", "METADATA_ONLY"})

_REQUIRED_SOURCE_FIELDS = frozenset(
    {
        "source_id",
        "source_kind",
        "lifecycle_state",
        "access_state",
        "licence_state",
        "permitted_use",
        "identifiers",
        "artifact_ids",
        "observations",
        "limitations",
    }
)
_VALID_LIFECYCLE_STATES = frozenset(
    {"STAGED_VERIFIED", "STAGED_LICENCE_REVIEW_REQUIRED", "METADATA_ONLY", "BLOCKED"}
)

#: Clinical/ACMG/classification vocabulary that must never appear (as a
#: case-insensitive substring) anywhere in a source record: this package
#: stages untrusted discovery/functional-dataset leads, never evidence.
FORBIDDEN_STATUS_TOKENS: tuple[str, ...] = (
    "classification",
    "pathogenic",
    "benign",
    "ps3",
    "bs3",
    "validated mechanism",
    "accepted claim",
    "acmg",
)


class BundleBoundaryError(ValueError):
    """Raised for manifest schema/cross-reference violations, and for
    output-path boundary violations: writing inside the repository,
    writing onto a pre-existing (create-only) final run path, or writing
    onto a symlink/reparse-point run leaf."""


class BundleHashMismatchError(ValueError):
    """Raised when an artifact payload's actual bytes do not match its
    manifest-declared ``byte_length``/``sha256``, or when a manifest's
    ``content_hash`` does not match its recomputed canonical hash."""


class StatusVocabularyError(ValueError):
    """Raised when a source record contains forbidden clinical/ACMG/
    classification status vocabulary (see ``FORBIDDEN_STATUS_TOKENS``)."""


def _iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_strings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _iter_strings(nested)


def assert_no_forbidden_status_vocabulary(sources: list[dict[str, Any]]) -> None:
    """Raise ``StatusVocabularyError`` if any string value anywhere within
    any source record contains a forbidden clinical/ACMG/classification
    token (case-insensitive substring match) -- e.g. ``lifecycle_state``,
    ``observations``, ``limitations``. Never silently strips/renames the
    offending value; a caller must never emit it in the first place."""
    for source in sources:
        for text in _iter_strings(source):
            lowered = text.lower()
            for token in FORBIDDEN_STATUS_TOKENS:
                if token in lowered:
                    raise StatusVocabularyError(
                        f"source {source.get('source_id')!r} contains forbidden clinical/ACMG/"
                        f"classification status vocabulary {token!r} in value {text!r}"
                    )


def _validate_artifact_schema(artifact: dict[str, Any]) -> None:
    if set(artifact) != _REQUIRED_ARTIFACT_FIELDS:
        missing = _REQUIRED_ARTIFACT_FIELDS - set(artifact)
        extra = set(artifact) - _REQUIRED_ARTIFACT_FIELDS
        raise BundleBoundaryError(
            "artifact record does not have the exact required fields; "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
        )
    if artifact["verification"] not in _VALID_VERIFICATIONS:
        raise BundleBoundaryError(
            f"artifact {artifact.get('artifact_id')!r} has an unknown verification state "
            f"{artifact['verification']!r} (expected one of {sorted(_VALID_VERIFICATIONS)!r})"
        )


def _validate_source_schema(source: dict[str, Any]) -> None:
    if set(source) != _REQUIRED_SOURCE_FIELDS:
        missing = _REQUIRED_SOURCE_FIELDS - set(source)
        extra = set(source) - _REQUIRED_SOURCE_FIELDS
        raise BundleBoundaryError(
            "source record does not have the exact required fields; "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
        )
    if source["lifecycle_state"] not in _VALID_LIFECYCLE_STATES:
        raise BundleBoundaryError(
            f"source {source.get('source_id')!r} has an unknown lifecycle_state "
            f"{source['lifecycle_state']!r} (expected one of {sorted(_VALID_LIFECYCLE_STATES)!r})"
        )


def _validate_cross_references(
    artifacts: list[dict[str, Any]], sources: list[dict[str, Any]]
) -> None:
    artifacts_by_id: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        artifact_id = artifact["artifact_id"]
        if artifact_id in artifacts_by_id:
            raise BundleBoundaryError(f"duplicate artifact_id in bundle manifest: {artifact_id!r}")
        artifacts_by_id[artifact_id] = artifact

    source_ids: set[str] = set()
    for source in sources:
        source_id = source["source_id"]
        if source_id in source_ids:
            raise BundleBoundaryError(f"duplicate source_id in bundle manifest: {source_id!r}")
        source_ids.add(source_id)
        for artifact_id in source["artifact_ids"]:
            artifact = artifacts_by_id.get(artifact_id)
            if artifact is None:
                raise BundleBoundaryError(
                    f"source {source_id!r} references unknown artifact_id {artifact_id!r}"
                )
            if artifact["source_id"] != source_id:
                raise BundleBoundaryError(
                    f"artifact {artifact_id!r} source_id {artifact['source_id']!r} does not "
                    f"match referencing source {source_id!r}"
                )

    for artifact_id, artifact in artifacts_by_id.items():
        if artifact["source_id"] not in source_ids:
            raise BundleBoundaryError(
                f"artifact {artifact_id!r} references unknown source_id "
                f"{artifact['source_id']!r}"
            )


def compute_bundle_content_hash(manifest: dict[str, Any]) -> str:
    """SHA-256 of the manifest's UTF-8 canonical JSON (sorted object keys,
    ``(",", ":")`` separators, array order preserved), excluding ONLY the
    top-level ``content_hash`` key itself."""
    basis = {key: value for key, value in manifest.items() if key != "content_hash"}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_manifest_hash(manifest: dict[str, Any]) -> None:
    """Raise ``BundleHashMismatchError`` if ``manifest['content_hash']`` does
    not match the manifest's recomputed canonical content hash."""
    if "content_hash" not in manifest:
        raise BundleHashMismatchError("manifest is missing the required content_hash field")
    recomputed = compute_bundle_content_hash(manifest)
    if recomputed != manifest["content_hash"]:
        raise BundleHashMismatchError(
            f"manifest content_hash mismatch: recorded {manifest['content_hash']!r} != "
            f"recomputed {recomputed!r}"
        )


def build_bundle_manifest(
    *,
    bundle_id: str,
    created_at: str,
    query: dict[str, Any],
    artifacts: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    truncation: dict[str, Any],
    boundaries: dict[str, Any],
) -> dict[str, Any]:
    """Build and canonically self-hash a ``raptor.external.tsc2_source_
    bundle.v1`` manifest from already-verified artifact/source records.
    Raises ``BundleBoundaryError`` on a malformed record or a broken
    artifact/source cross-reference, and ``StatusVocabularyError`` if any
    source contains forbidden clinical/ACMG/classification vocabulary."""
    artifacts = list(artifacts)
    sources = list(sources)

    for artifact in artifacts:
        _validate_artifact_schema(artifact)
    for source in sources:
        _validate_source_schema(source)

    assert_no_forbidden_status_vocabulary(sources)
    _validate_cross_references(artifacts, sources)

    manifest: dict[str, Any] = {
        "schema": BUNDLE_MANIFEST_SCHEMA,
        "bundle_id": bundle_id,
        "created_at": created_at,
        "query": query,
        "artifacts": artifacts,
        "sources": sources,
        "counts": {"sources": len(sources), "artifacts": len(artifacts)},
        "truncation": truncation,
        "boundaries": boundaries,
    }
    manifest["content_hash"] = compute_bundle_content_hash(manifest)
    return manifest


def _safe_join(base: Path, relative_path: str) -> Path:
    candidate = (base / relative_path).resolve()
    base_resolved = base.resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise BundleBoundaryError(
            f"artifact relative_path escapes the staging directory: {relative_path!r}"
        ) from exc
    return candidate


def _validate_run_name(run_name: str) -> None:
    """Raise ``BundleBoundaryError`` unless ``run_name`` is exactly one
    safe, relative path component: not blank, not absolute (POSIX or
    Windows-style), not containing a path separator, and not a traversal
    component (``.``/``..``)."""
    if not isinstance(run_name, str) or not run_name.strip():
        raise BundleBoundaryError("run_name must be a non-blank string")
    if "\x00" in run_name:
        raise BundleBoundaryError(f"run_name must not contain a NUL byte: {run_name!r}")
    if "/" in run_name or "\\" in run_name:
        raise BundleBoundaryError(
            f"run_name must be exactly one safe path component (no separators): {run_name!r}"
        )
    if PureWindowsPath(run_name).drive or PurePosixPath(run_name).is_absolute():
        raise BundleBoundaryError(f"run_name must not be an absolute path: {run_name!r}")
    if run_name in (".", ".."):
        raise BundleBoundaryError(f"run_name must not be a traversal component: {run_name!r}")


def _assert_no_symlink_ancestry(path: Path, *, role: str) -> None:
    """Raise ``BundleBoundaryError`` if ``path`` itself, or any of its
    ancestor directories, is a symlink/reparse point. Only EXISTING
    ancestors are checked (a not-yet-created leaf is never itself a
    symlink); this walks all the way to the filesystem root, not merely
    ``path``'s immediate parent."""
    current = path
    while True:
        if current.is_symlink():
            raise BundleBoundaryError(
                f"{role} path {path} has a symlink/reparse ancestor at {current}; refusing "
                "for safety"
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def _reserve_run_name(output_root: Path, run_name: str) -> Path:
    """Create-EXCLUSIVELY (``O_CREAT | O_EXCL``, mode ``0o600``) reserve
    ``run_name`` within ``output_root`` via a sibling publication-
    reservation lock file -- BEFORE any staging directory is created and
    BEFORE any artifact bytes are written. Only ONE compliant concurrent
    writer can ever win this reservation for a given ``run_name``; every
    other compliant writer fails FAST here (raising ``BundleBoundaryError``,
    doing no staging work at all) instead of only colliding later at the
    final atomic ``os.replace``. Returns the reservation lock file's own
    path; the caller MUST remove exactly that path (and never any other
    writer's reservation) in every success and failure path."""
    lock_path = output_root / f".{run_name}.publish.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise BundleBoundaryError(
            f"run_name {run_name!r} is already reserved by a concurrent writer under "
            f"{output_root}; refusing to race a compliant concurrent publication"
        ) from exc
    os.close(fd)
    return lock_path


def _release_reservation(lock_path: Path) -> None:
    """Remove ONLY this process's own reservation lock file (never a
    different writer's reservation -- each reservation is a distinct,
    exclusively-created path keyed by its own ``run_name``). Tolerates the
    lock file already being gone (e.g. a prior partial cleanup attempt)."""
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def write_bundle_run(
    *,
    repo_root: Path,
    output_root: Path,
    run_name: str,
    manifest: dict[str, Any],
    artifact_payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Publish ``manifest`` and ``artifact_payloads`` to
    ``output_root/run_name`` -- external, create-only, atomic and
    symlink-safe. Raises ``BundleBoundaryError`` if ``run_name`` is not
    exactly one safe relative path component (rejecting absolute, nested
    and traversal names), if ``output_root`` (or any of its ancestors) is a
    symlink/reparse point (checked both before AND after ``output_root`` is
    created), if ``output_root`` resolves inside ``repo_root``, if the
    final run path already exists (checked both before AND after acquiring
    the publication reservation below), if the final run path is a
    symlink/reparse point, or if ``run_name`` is already reserved by a
    concurrent compliant writer (a ``.{run_name}.publish.lock`` sibling
    file created ``O_CREAT|O_EXCL`` -- a losing writer fails here, before
    any staging work). Raises ``BundleHashMismatchError`` if any artifact
    payload's bytes do not match its manifest-declared
    ``byte_length``/``sha256``, or if the manifest's own ``content_hash``
    does not match its recomputed value. On ANY failure -- including a
    concurrent writer winning the final atomic publication, or the
    publication step itself raising -- the staging directory is removed and
    NO manifest is ever published to the final run path; a competing
    writer's already-published final directory is never
    deleted/replaced/touched. This process's own reservation lock is always
    removed (success or failure) before returning/raising."""
    validate_manifest_hash(manifest)
    _validate_run_name(run_name)

    repo_root = Path(repo_root)
    output_root = Path(output_root)

    _assert_no_symlink_ancestry(output_root, role="output_root")

    resolved_repo_root = repo_root.resolve()
    resolved_output_root = output_root.resolve()
    try:
        resolved_output_root.relative_to(resolved_repo_root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    if inside_repo:
        raise BundleBoundaryError(
            f"output_root {output_root} resolves inside repo_root {repo_root}; the external "
            "bundle must never be written inside the repository"
        )

    final_run_dir = output_root / run_name
    if final_run_dir.is_symlink():
        raise BundleBoundaryError(
            f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
        )
    if final_run_dir.exists():
        raise BundleBoundaryError(
            f"output run path {final_run_dir} already exists; runs are create-only and are "
            "never overwritten or silently resumed"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    # Re-check ancestry AFTER creating output_root: `mkdir` may have just
    # created one or more of its ancestor directories, and a TOCTOU window
    # exists between the pre-creation check above and this point.
    _assert_no_symlink_ancestry(output_root, role="output_root")

    reservation_path = _reserve_run_name(output_root, run_name)
    try:
        # Re-check the final run path is still absent now that WE hold the
        # publication reservation: a non-compliant writer (one bypassing
        # this reservation protocol entirely) could have published directly
        # into the TOCTOU window between the pre-reservation check above and
        # winning this lock. Never delete/replace whatever is there -- just
        # fail loud, exactly like the pre-reservation existence check does.
        if final_run_dir.is_symlink():
            raise BundleBoundaryError(
                f"output run path {final_run_dir} is a symlink/reparse point; refusing for "
                "safety"
            )
        if final_run_dir.exists():
            raise BundleBoundaryError(
                f"output run path {final_run_dir} already exists; runs are create-only and "
                "are never overwritten or silently resumed"
            )

        staging_dir = output_root / f".{run_name}.staging-{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=False, exist_ok=False)

        try:
            for artifact in manifest["artifacts"]:
                relative_path = artifact["relative_path"]
                payload = artifact_payloads.get(relative_path)
                if payload is None:
                    raise BundleHashMismatchError(
                        f"missing artifact payload bytes for relative_path {relative_path!r} "
                        f"(artifact_id={artifact.get('artifact_id')!r})"
                    )
                if len(payload) != artifact["byte_length"]:
                    raise BundleHashMismatchError(
                        f"artifact {artifact['artifact_id']!r} byte_length mismatch: expected "
                        f"{artifact['byte_length']!r}, observed {len(payload)!r} bytes"
                    )
                observed_sha256 = hashlib.sha256(payload).hexdigest()
                if observed_sha256.lower() != artifact["sha256"].lower():
                    raise BundleHashMismatchError(
                        f"artifact {artifact['artifact_id']!r} sha256 hash mismatch: expected "
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
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        try:
            os.replace(staging_dir, final_run_dir)
        except FileExistsError as exc:
            # A concurrent writer won the race and already published (or is
            # publishing) the final run path between our earlier existence
            # check and this atomic rename: never replace it, never touch it
            # -- only remove OUR OWN staging directory and fail loud.
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise BundleBoundaryError(
                f"output run path {final_run_dir} was concurrently created by another writer "
                "during publication; refusing to replace a competing publication"
            ) from exc
        except OSError as exc:
            # Any other publication failure (permissions, a non-empty
            # destination on platforms that reject that, etc.): clean up
            # staging and fail loud -- the final path must never be left
            # partially published.
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise BundleBoundaryError(
                f"failed to atomically publish run directory {final_run_dir}: {exc}"
            ) from exc
    finally:
        _release_reservation(reservation_path)

    return {
        "run_dir": str(final_run_dir),
        "manifest_path": str(final_run_dir / MANIFEST_FILENAME),
    }


def build_pilot_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the compact, aggregate-only committed pilot summary from an
    already-built bundle manifest: counts, truncation, per-source
    lifecycle/access/licence state, per-artifact sha256 hashes, and a fixed
    list of known follow-on normalization gaps. NEVER includes full text,
    per-variant rows, patient information, or any classification/evidence-
    strength claim (enforced structurally: this function reads no field
    beyond the aggregate ones listed below)."""
    source_states = {
        source["source_id"]: {
            "source_kind": source["source_kind"],
            "lifecycle_state": source["lifecycle_state"],
            "access_state": source["access_state"],
            "licence_state": source["licence_state"],
        }
        for source in manifest["sources"]
    }
    artifact_hashes = {
        artifact["artifact_id"]: artifact["sha256"] for artifact in manifest["artifacts"]
    }
    normalization_gaps = [
        "functional-dataset rows are not yet normalized to a canonical transcript/assembly identity",
        "abundance/activity score transformations and interpretive thresholds are not yet reproduced",
        "no overlap or calibration audit against any external knowledge base has been computed",
        "no assay-specific evidentiary-strength policy has been implemented for this slice",
    ]
    return {
        "schema": PILOT_SUMMARY_SCHEMA,
        "bundle_id": manifest["bundle_id"],
        "counts": manifest["counts"],
        "truncation": manifest["truncation"],
        "source_states": source_states,
        "artifact_hashes": artifact_hashes,
        "normalization_gaps": normalization_gaps,
    }


__all__ = [
    "BUNDLE_MANIFEST_SCHEMA",
    "PILOT_SUMMARY_SCHEMA",
    "MANIFEST_FILENAME",
    "FORBIDDEN_STATUS_TOKENS",
    "BundleBoundaryError",
    "BundleHashMismatchError",
    "StatusVocabularyError",
    "assert_no_forbidden_status_vocabulary",
    "compute_bundle_content_hash",
    "validate_manifest_hash",
    "build_bundle_manifest",
    "write_bundle_run",
    "build_pilot_summary",
]
