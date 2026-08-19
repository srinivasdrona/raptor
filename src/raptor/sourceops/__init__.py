"""Offline SourceOps registry and validation package."""

from raptor.sourceops.model import (
    CliResult,
    ManifestChecksum,
    ManifestComponentProjection,
    ManifestContentBinding,
    ManifestDocument,
    ManifestFile,
    ValidationError,
    VerifyStageResult,
)
from raptor.sourceops.registry import VALIDATION_CEILING, VALIDATION_SCHEMA_ID, canonical_registry_hash, load_registry, status_for_consumer, validate_registry
from raptor.sourceops.staged_snapshot import StagedSnapshotError, verify_stage


def load_manifest(path):
    import os
    import stat
    from pathlib import Path

    from raptor.sourceops.staged_snapshot import (
        StagingManifestMissingError,
        StagingManifestReadError,
        StagingManifestTypeError,
        _is_windows_reparse,
        _load_manifest_yaml,
        _normalise_manifest_files,
        _validate_manifest_hash,
        _validate_manifest_shape,
    )

    manifest_path = Path(path)
    try:
        st = os.lstat(manifest_path)
    except OSError as exc:
        raise StagingManifestMissingError("staging root does not contain manifest.yaml", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml") from exc
    if stat.S_ISLNK(st.st_mode) or _is_windows_reparse(manifest_path) or not stat.S_ISREG(st.st_mode):
        raise StagingManifestTypeError("manifest.yaml is a link, reparse point, directory, or special entry", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml")
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise StagingManifestReadError("staged manifest could not be read as a bounded local regular file", phase="MANIFEST_READ", exit_code=2, subject="manifest.yaml") from exc

    manifest = _load_manifest_yaml(raw)
    _validate_manifest_shape(manifest)
    _normalise_manifest_files(manifest)
    _validate_manifest_hash(manifest)
    return ManifestDocument.from_mapping(manifest)


__all__ = [
    "VALIDATION_CEILING",
    "VALIDATION_SCHEMA_ID",
    "ValidationError",
    "CliResult",
    "ManifestDocument",
    "ManifestFile",
    "ManifestChecksum",
    "ManifestContentBinding",
    "ManifestComponentProjection",
    "VerifyStageResult",
    "canonical_registry_hash",
    "load_registry",
    "status_for_consumer",
    "validate_registry",
    "verify_stage",
    "load_manifest",
]
