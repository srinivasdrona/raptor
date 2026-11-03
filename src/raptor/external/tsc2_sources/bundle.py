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
staging directory published onto the (never pre-existing) final run path
via ``_publish_directory_no_replace``. That helper's FAST PATH is a
genuinely atomic, no-clobber whole-directory rename (``renameat2`` with
``RENAME_NOREPLACE`` on Linux; ``os.rename`` on Windows) that fails instead
of replacing ANY pre-existing destination, including an EMPTY destination
directory (see that helper's docstring for why plain
``os.rename``/``os.replace`` can silently replace an empty directory on
POSIX and must never be used here). On filesystems that reject
``RENAME_NOREPLACE`` itself (observed on DrvFS -- WSL2's passthrough for
Windows drives such as ``/mnt/d/...``), it falls back to a manifest-last
claim-then-populate protocol built from ``os.mkdir``/``O_CREAT|O_EXCL``
alone: as a result, a published run directory's ``bundle_manifest.json``
is ALWAYS the last thing written, and every consumer of these run
directories MUST treat a run directory that exists but does not (yet, or
ever) contain ``bundle_manifest.json`` as UNPUBLISHED/INVALID. Any failure
during staging, or during that publish step, removes the staging directory
(and, for the fallback protocol, only whatever this process itself had
already created under the final path) and raises -- the final run path is
never left containing this process's own partial content, and a competing
writer's pre-existing content there is never touched.

This module performs no network I/O and never imports ``raptor.sourceops``,
``raptor.scorer``, ``raptor.eval``, ``raptor.packet``, ``raptor.census``,
``raptor.kb`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import platform
import shutil
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

BUNDLE_MANIFEST_SCHEMA = "raptor.external.tsc2_source_bundle.v1"
PILOT_SUMMARY_SCHEMA = "raptor.external.tsc2_source_pilot_summary.v1"
MANIFEST_FILENAME = "bundle_manifest.json"

# The six sources the real pilot must cover (spec `real_pilot.required_sources`,
# in the spec's fixed order). `build_pilot_summary` uses this ONLY to compute
# `missing_source_ids` -- it never fabricates or reorders `source_ids` itself.
_REQUIRED_PILOT_SOURCE_IDS = (
    "pubmed",
    "litvar2",
    "pmc",
    "mavedb_clipe",
    "igvf_vamp_seq",
    "igvf_sge",
)

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
    final atomic ``_publish_directory_no_replace`` publish step. Returns
    the reservation lock file's own path; the caller MUST remove exactly
    that path (and never any other writer's reservation) in every success
    and failure path."""
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


#: ``renameat2(2)`` flag requesting an atomic no-clobber rename: the call
#: fails with ``EEXIST`` instead of replacing an existing ``newpath`` (this
#: is the fast-path way on Linux to get a genuinely atomic no-clobber
#: directory rename -- plain POSIX ``rename(2)``/``os.replace`` silently
#: replaces an existing EMPTY destination directory, by design). NOT every
#: Linux-mounted filesystem implements this flag: see
#: ``_RenameAt2FlagUnsupportedError`` below.
_RENAME_NOREPLACE = 0x1
#: Special ``AT_FDCWD`` dirfd value: resolve the paired path argument
#: relative to the current working directory, exactly like plain
#: ``rename(2)`` would.
_AT_FDCWD = -100


class _RenameAt2FlagUnsupportedError(OSError):
    """Internal signal (never escapes ``_publish_directory_no_replace``):
    the kernel rejected ``RENAME_NOREPLACE`` itself with ``EINVAL`` or
    ``EOPNOTSUPP``/``ENOTSUP``, meaning the underlying filesystem driver
    does not implement the flag -- observed on DrvFS (WSL2's passthrough
    for Windows drives, e.g. ``/mnt/d/...``) -- rather than any real
    existence conflict (``EEXIST``/``ENOTEMPTY``) or other genuine
    failure. Raising this (instead of a generic ``OSError``) lets
    ``_publish_directory_no_replace`` fall back to the claim-then-populate
    publish protocol on exactly this filesystem-capability condition, and
    nothing else."""


#: ``errno`` values that specifically mean "this filesystem rejects the
#: ``RENAME_NOREPLACE`` flag" rather than a real existence conflict or
#: other genuine failure: ``EINVAL`` (the flag itself is rejected --
#: observed on DrvFS) and ``EOPNOTSUPP``/``ENOTSUP`` (an explicit
#: "operation not supported" some filesystem drivers may return instead).
#: On Linux, ``EOPNOTSUPP`` and ``ENOTSUP`` share the same numeric value,
#: but both names are included defensively since that is not guaranteed by
#: the ``errno`` module across all C libraries.
_RENAME_NOREPLACE_UNSUPPORTED_ERRNOS = frozenset(
    value
    for value in (
        errno.EINVAL,
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "ENOTSUP", None),
    )
    if value is not None
)


def _renameat2_no_replace_linux(old_path: str, new_path: str) -> None:
    """Invoke the Linux-only ``renameat2(2)`` syscall with
    ``RENAME_NOREPLACE`` via ``ctypes`` (the standard library exposes no
    wrapper for this syscall). Atomically renames ``old_path`` onto
    ``new_path`` -- kernel-enforced, no check-then-rename TOCTOU window --
    and NEVER replaces an existing ``new_path``, in ANY form (empty
    directory, non-empty directory, file, or symlink): the kernel rejects
    the rename with ``EEXIST``/``ENOTEMPTY`` instead. Raises
    ``FileExistsError`` for exactly that case, ``_RenameAt2FlagUnsupportedError``
    if the underlying filesystem rejects the ``RENAME_NOREPLACE`` flag
    itself (``EINVAL``/``EOPNOTSUPP``/``ENOTSUP`` -- e.g. DrvFS), and
    ``OSError`` for any other syscall failure. If ``libc.so.6`` does not
    even export the ``renameat2`` symbol at all (e.g. a glibc predating
    the wrapper), this raises a clear ``OSError`` -- fail closed -- rather
    than letting a raw ``AttributeError`` escape; that is a genuine
    environment limitation, distinct from (and NOT treated the same as) a
    specific filesystem rejecting the flag, so it is never silently routed
    to the claim-then-populate fallback."""
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(
            "libc.so.6 does not export renameat2(2) on this system; no atomic no-clobber "
            "directory rename primitive is available -- refusing to fall back to "
            "clobber-capable rename/replace semantics"
        )
    old_bytes = os.fsencode(old_path)
    new_bytes = os.fsencode(new_path)
    ctypes.set_errno(0)
    result = renameat2(
        ctypes.c_int(_AT_FDCWD),
        ctypes.c_char_p(old_bytes),
        ctypes.c_int(_AT_FDCWD),
        ctypes.c_char_p(new_bytes),
        ctypes.c_uint(_RENAME_NOREPLACE),
    )
    if result == 0:
        return
    errno_value = ctypes.get_errno()
    message = f"renameat2(RENAME_NOREPLACE) {old_path!r} -> {new_path!r} failed: " + os.strerror(
        errno_value
    )
    if errno_value in (errno.EEXIST, errno.ENOTEMPTY):
        raise FileExistsError(errno_value, message)
    if errno_value in _RENAME_NOREPLACE_UNSUPPORTED_ERRNOS:
        raise _RenameAt2FlagUnsupportedError(errno_value, message)
    raise OSError(errno_value, message)


def _claim_subdirectory_chain(
    destination_dir: Path, relative_parent: Path, created_dirs: list[Path]
) -> None:
    """Create every ancestor directory of ``relative_parent`` under
    ``destination_dir`` that this process has not already created earlier
    in the SAME publish call (tracked via ``created_dirs``, appended to in
    place). Each still-missing level is created with plain ``os.mkdir``
    (never ``exist_ok=True``): since ``destination_dir`` itself was just
    exclusively claimed by this process, ANY level that already exists and
    was not created by us this call is an unexpected occupant, and
    ``os.mkdir`` raising ``FileExistsError`` for it is the correct,
    fail-loud outcome -- never silently reused or replaced."""
    if relative_parent == Path("."):
        return
    current = destination_dir
    for part in relative_parent.parts:
        current = current / part
        if current in created_dirs:
            continue
        os.mkdir(str(current))
        created_dirs.append(current)


def _copy_file_exclusive(
    source_path: Path, destination_path: Path, created_files: list[Path]
) -> None:
    """Copy ``source_path``'s bytes onto ``destination_path`` via a
    context-managed exclusive create (``open(..., "xb")``, the
    ``open()``-level equivalent of ``O_CREAT | O_EXCL``): raises
    ``FileExistsError`` immediately -- before any byte is written -- if
    ``destination_path`` already exists, never overwriting it, and the
    context manager guarantees the destination file descriptor is closed
    even if the copy itself fails partway through. ``destination_path`` is
    appended to ``created_files`` the moment the exclusive create
    succeeds (before any bytes are copied), so a failure partway through
    still leaves the (partial) file tracked for rollback."""
    with open(str(destination_path), "xb") as destination_handle:
        created_files.append(destination_path)
        with open(str(source_path), "rb") as source_handle:
            shutil.copyfileobj(source_handle, destination_handle)


def _write_bytes_exclusive(
    destination_path: Path, payload: bytes, created_files: list[Path]
) -> None:
    """Write ``payload`` onto ``destination_path`` via a context-managed
    exclusive create (``open(..., "xb")``): raises ``FileExistsError``
    immediately if ``destination_path`` already exists, never overwriting
    it, and guarantees the file descriptor is closed even if the write
    itself fails partway through. ``destination_path`` is appended to
    ``created_files`` the moment the exclusive create succeeds (before any
    bytes are written), so a failure partway through the write still
    leaves the (partial) file tracked for rollback."""
    with open(str(destination_path), "xb") as destination_handle:
        created_files.append(destination_path)
        destination_handle.write(payload)


def _rollback_claimed_publication(
    destination_dir: Path, created_dirs: list[Path], created_files: list[Path]
) -> None:
    """Undo a failed claim-then-populate publish: remove ONLY the files
    and directories THIS process itself created while populating
    ``destination_dir`` (tracked precisely in ``created_files``/
    ``created_dirs``, removed in reverse creation order), then remove
    ``destination_dir`` itself if it is now empty. Content this process
    did not create is NEVER force-deleted: if a tracked directory is not
    empty after removing our own tracked files (an unexpected occupant is
    present), or if ``destination_dir`` itself is not empty afterwards,
    ``os.rmdir``'s ``ENOTEMPTY`` is deliberately swallowed and that
    directory is left exactly as found -- any other removal failure (a
    real, unexpected error) is left to propagate."""
    for file_path in reversed(created_files):
        try:
            os.remove(str(file_path))
        except FileNotFoundError:
            pass
    for dir_path in reversed(created_dirs):
        try:
            os.rmdir(str(dir_path))
        except FileNotFoundError:
            pass
        except OSError as exc:
            if exc.errno != errno.ENOTEMPTY:
                raise
    try:
        os.rmdir(str(destination_dir))
    except FileNotFoundError:
        pass
    except OSError as exc:
        if exc.errno != errno.ENOTEMPTY:
            raise


def _publish_directory_no_replace_via_claim_then_populate(
    staging_dir: Path, destination_dir: Path
) -> None:
    """Fallback publish protocol for filesystems that reject
    ``renameat2``'s ``RENAME_NOREPLACE`` flag (``EINVAL``/``EOPNOTSUPP``/
    ``ENOTSUP`` -- observed on DrvFS, WSL2's passthrough for Windows
    drives such as ``/mnt/d/AIProjects/raptor-data/...``), where NO
    whole-directory atomic-rename primitive can be relied on at all. This
    is a manifest-last claim-then-populate protocol, never a
    check-then-rename, and it is carefully ordered so that NO fallible
    step remains after the manifest -- the commit marker -- has been
    written:

    1. Read ``bundle_manifest.json``'s bytes from ``staging_dir`` into
       memory FIRST, before touching the destination at all.
    2. Atomically CLAIM ``destination_dir`` with plain ``os.mkdir``: this
       raises ``FileExistsError`` if ``destination_dir`` already exists in
       ANY form (empty directory, non-empty directory, file, or symlink)
       instead of ever replacing it. Unlike ``rename(2)``, POSIX
       ``mkdir(2)`` (and Windows ``CreateDirectoryW``) NEVER special-cases
       an empty destination -- it is a genuinely portable no-clobber
       primitive on every filesystem this module targets, which is why it
       is used here instead of another rename attempt.
    3. Copy every staged file EXCEPT the manifest into the newly claimed
       directory with a context-managed exclusive create
       (``_copy_file_exclusive``), recreating only the subdirectory levels
       needed (again via plain, non-``exist_ok`` ``os.mkdir``) and
       tracking every path this process itself creates.
    4. Remove ``staging_dir`` completely (it is no longer needed -- its
       manifest bytes are already held in memory from step 1).
    5. Write the in-memory manifest bytes onto
       ``destination_dir/bundle_manifest.json`` via a context-managed
       exclusive create, as the TRUE LAST operation. This is the commit
       marker: a ``destination_dir`` that exists but does not (yet, or
       ever) contain ``bundle_manifest.json`` is, by contract,
       UNPUBLISHED/INVALID, and every consumer of these run directories
       MUST treat it that way.

    If step 3, the staging removal in step 4, or the manifest write in
    step 5 fails, ``_rollback_claimed_publication`` removes exactly what
    THIS process created under ``destination_dir`` (files, then
    directories, then -- if left empty -- ``destination_dir`` itself) and
    the original exception is re-raised; a pre-existing competing writer's
    content is never touched, because we only ever reach step 3 after
    winning the exclusive claim in step 2. Once the manifest write in step
    5 succeeds, this function returns immediately with NO further fallible
    operation -- a fully published bundle (manifest included) is never
    reported as a failure because of a later, unrelated cleanup error."""
    manifest_path = staging_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise OSError(
            f"staging directory {staging_dir} is missing its manifest file "
            f"{MANIFEST_FILENAME!r}; refusing to publish"
        )
    manifest_bytes = manifest_path.read_bytes()
    non_manifest_relpaths = sorted(
        p.relative_to(staging_dir)
        for p in staging_dir.rglob("*")
        if p.is_file() and p != manifest_path
    )

    # Step 2: exclusively claim destination_dir. A FileExistsError here
    # propagates unchanged -- nothing has been created yet, so no rollback
    # is needed.
    os.mkdir(str(destination_dir))

    created_dirs: list[Path] = []
    created_files: list[Path] = []
    try:
        # Step 3: populate every non-manifest file.
        for relpath in non_manifest_relpaths:
            _claim_subdirectory_chain(destination_dir, relpath.parent, created_dirs)
            _copy_file_exclusive(staging_dir / relpath, destination_dir / relpath, created_files)
        # Step 4: staging is no longer needed -- its manifest bytes are
        # already held in memory. This is still pre-commit: a failure
        # here still rolls back destination_dir below.
        shutil.rmtree(staging_dir)
        # Step 5: the manifest write is the TRUE LAST fallible operation
        # and the commit marker.
        _write_bytes_exclusive(
            destination_dir / MANIFEST_FILENAME, manifest_bytes, created_files
        )
    except Exception:
        _rollback_claimed_publication(destination_dir, created_dirs, created_files)
        raise


def _publish_directory_no_replace(staging_dir: Path | str, destination_dir: Path | str) -> None:
    """Atomically publish ``staging_dir`` onto ``destination_dir`` using a
    genuinely atomic, no-clobber directory rename primitive -- NEVER a
    check-then-rename (``exists()`` then ``os.rename``/``os.replace``)
    sequence, which always leaves a TOCTOU window a concurrent writer can
    win.

    Plain POSIX ``rename(2)`` (what ``os.replace`` uses on Linux/WSL) has a
    standard, documented behavior that is a trap here: if ``newpath``
    already exists and is an EMPTY directory, the kernel silently replaces
    it. That means a non-compliant concurrent writer that creates (but has
    not yet populated) the destination directory after this module's
    existence checks can have its empty directory silently destroyed by
    our own publish step -- an ``os.replace``-based implementation can
    never protect against this. This function instead uses:

    - On Linux: the ``renameat2(2)`` syscall (via ``ctypes``, since the
      standard library exposes no wrapper) with ``RENAME_NOREPLACE`` as the
      FAST PATH, which is kernel-enforced-atomic and fails with
      ``EEXIST``/``ENOTEMPTY`` if ``destination_dir`` exists in ANY form --
      empty directory, non-empty directory, file, or symlink -- rather
      than ever replacing it. NOT every Linux-mounted filesystem
      implements this flag: DrvFS (WSL2's passthrough for Windows drives,
      e.g. ``/mnt/d/...``) rejects it with ``EINVAL``. When that happens,
      this falls back to ``_publish_directory_no_replace_via_claim_then_populate``
      -- a manifest-last claim-then-populate protocol built entirely from
      primitives (``os.mkdir``, ``O_CREAT|O_EXCL``) that behave
      consistently as no-clobber on EVERY filesystem this module targets,
      including DrvFS.
    - On Windows: plain ``os.rename`` (backed by ``MoveFileExW`` with no
      flags). Windows directory renames already refuse to replace an
      existing destination directory -- even an empty one -- without
      ``MOVEFILE_REPLACE_EXISTING``, and that flag itself only ever
      replaces FILES, never directories; so plain ``os.rename`` is already
      an atomic no-clobber directory rename on Windows and needs no extra
      flag/wrapper.

    Any other platform -- one without a verified atomic no-clobber
    directory rename primitive -- fails closed by raising ``OSError``
    rather than silently falling back to clobber-capable
    ``os.rename``/``os.replace`` semantics.

    Raises ``FileExistsError`` if ``destination_dir`` already exists (in
    any form). Raises ``OSError`` for any other publication failure
    (including an unsupported platform). NOTE: when the claim-then-populate
    fallback is used, a ``destination_dir`` that exists without
    ``bundle_manifest.json`` inside it is UNPUBLISHED/INVALID -- see
    ``_publish_directory_no_replace_via_claim_then_populate``'s docstring."""
    staging_dir = Path(staging_dir)
    destination_dir = Path(destination_dir)
    system = platform.system()
    if system == "Linux":
        try:
            _renameat2_no_replace_linux(str(staging_dir), str(destination_dir))
        except _RenameAt2FlagUnsupportedError:
            _publish_directory_no_replace_via_claim_then_populate(staging_dir, destination_dir)
    elif system == "Windows":
        # Windows MoveFileExW-backed os.rename already refuses to replace
        # an existing directory destination (even an empty one) without
        # MOVEFILE_REPLACE_EXISTING, which itself can only ever replace
        # files, never directories -- so no extra no-clobber wrapper is
        # needed here.
        os.rename(str(staging_dir), str(destination_dir))
    else:
        raise OSError(
            f"no verified atomic no-clobber directory rename primitive is available for "
            f"platform {system!r}; refusing to fall back to clobber-capable rename/replace "
            "semantics"
        )


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
            _publish_directory_no_replace(staging_dir, final_run_dir)
        except FileExistsError as exc:
            # A concurrent writer won the race and already created (or is
            # publishing into) the final run path between our earlier
            # existence check and this atomic no-clobber rename -- in ANY
            # form, including an EMPTY directory (which plain
            # os.replace/os.rename would silently replace on POSIX; see
            # _publish_directory_no_replace's docstring): never replace it,
            # never touch it -- only remove OUR OWN staging directory and
            # fail loud.
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise BundleBoundaryError(
                f"output run path {final_run_dir} was concurrently created by another writer "
                "during publication; refusing to replace a competing publication"
            ) from exc
        except OSError as exc:
            # Any other publication failure (permissions, an unsupported
            # platform, etc.): clean up staging and fail loud -- the final
            # path must never be left partially published.
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
    already-built bundle manifest: the manifest's own content hash, counts,
    exact/missing source-ID coverage, truncation, per-source
    lifecycle/access/licence state, per-source aggregate ``observations``,
    per-artifact integrity metadata (sha256/md5/byte_length/verification --
    NOT a bare hash mapping), and a fixed list of known follow-on
    normalization gaps. NEVER includes a requested/final URL, identifiers,
    full text, per-variant rows, patient information, credentials, or any
    classification/evidence-strength claim (enforced structurally: this
    function is a strict field-whitelist projection and reads/copies no
    field beyond the aggregate ones listed below)."""
    source_ids = [source["source_id"] for source in manifest["sources"]]
    source_id_set = set(source_ids)
    missing_source_ids = [
        source_id
        for source_id in _REQUIRED_PILOT_SOURCE_IDS
        if source_id not in source_id_set
    ]
    source_states = {
        source["source_id"]: {
            "source_kind": source["source_kind"],
            "lifecycle_state": source["lifecycle_state"],
            "access_state": source["access_state"],
            "licence_state": source["licence_state"],
        }
        for source in manifest["sources"]
    }
    source_observations = {
        source["source_id"]: dict(source["observations"]) for source in manifest["sources"]
    }
    artifact_integrity = {
        artifact["artifact_id"]: {
            "sha256": artifact["sha256"],
            "md5": artifact["md5"],
            "byte_length": artifact["byte_length"],
            "verification": artifact["verification"],
        }
        for artifact in manifest["artifacts"]
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
        "manifest_content_hash": manifest["content_hash"],
        "counts": manifest["counts"],
        "source_ids": source_ids,
        "missing_source_ids": missing_source_ids,
        "truncation": manifest["truncation"],
        "source_states": source_states,
        "source_observations": source_observations,
        "artifact_integrity": artifact_integrity,
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
