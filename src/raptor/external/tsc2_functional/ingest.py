"""RAPTOR v2 TSC2 functional normalization -- frozen-input validation and
the pure, offline normalization entry point.

``validate_frozen_source_bundle`` re-verifies the already-published TSC2
source-ingestion bundle (``raptor.external.tsc2_sources.bundle``) against
this slice's pinned bundle id/manifest content hash/per-artifact identity
(``artifact_id``/``source_id``/``relative_path``/``sha256``/``md5``/
``byte_length``) -- recomputing the manifest's own canonical content hash
via that module's ``compute_bundle_content_hash`` (never trusting the
manifest's own recorded value) and hashing/length-checking the ACTUAL
injected artifact bytes, never merely trusting a declared value anywhere.

``validate_reference_fasta_checksum`` verifies the pinned
``NC_000016.10`` FASTA's actual sha256 -- this MUST be checked before any
SGE row is ever handed to the genomic normalizer (FN-03/FN-08).

``normalize_functional_bundle`` is the single, pure orchestration entry
point ``scripts/normalize_tsc2_functional_bundle.py`` calls: it verifies
the reference FASTA checksum FIRST (before touching the source bundle or
calling the normalizer at all), then the frozen source bundle, then
normalizes all three sources (``normalize.py``) and hands back everything
the operator needs to build/publish a normalization bundle
(``bundle.py``).

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from raptor.external.tsc2_sources.bundle import compute_bundle_content_hash

from .model import GENE
from .normalize import normalize_mavedb, normalize_sge, normalize_vamp_seq

#: The three source ids this slice normalizes, in the spec's fixed order.
REQUIRED_SOURCE_IDS: tuple[str, ...] = ("mavedb_clipe", "igvf_vamp_seq", "igvf_sge")

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class FunctionalNormalizationError(ValueError):
    """Base error for this slice's ingest-time domain errors."""


class InputPinMismatchError(FunctionalNormalizationError):
    """Raised when the frozen TSC2 source bundle's manifest content hash,
    bundle id, or any pinned artifact's identity/relative path/sha256/md5/
    byte length -- or its ACTUAL injected bytes -- differs from this
    slice's frozen expectations."""


class ReferenceIntegrityError(FunctionalNormalizationError):
    """Raised when the pinned ``NC_000016.10`` reference FASTA is missing
    or its actual sha256 does not match the pinned value. Always raised
    before any SGE row is handed to the genomic normalizer."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_reference_fasta_checksum(*, reference_fasta_path: Path | str, expected_sha256: str) -> str:
    """Return the actual sha256 of ``reference_fasta_path`` if it matches
    ``expected_sha256``; otherwise raise ``ReferenceIntegrityError``. Also
    raises if the file does not exist. This MUST be called -- and MUST
    succeed -- before any SGE row is normalized (FN-03/FN-08)."""
    path = Path(reference_fasta_path)
    if not path.is_file():
        raise ReferenceIntegrityError(
            f"pinned reference FASTA not found at {path}; refusing to normalize any SGE row "
            "without a verified reference"
        )
    actual = _sha256_file(path)
    if actual.lower() != str(expected_sha256).lower():
        raise ReferenceIntegrityError(
            f"reference FASTA checksum mismatch at {path}: pinned {expected_sha256!r} != "
            f"actual sha256 {actual!r}; refusing to normalize any SGE row against an "
            "unverified/altered reference"
        )
    return actual


def validate_frozen_source_bundle(
    *,
    source_manifest: dict[str, Any],
    artifact_payloads: dict[str, bytes],
    expected_bundle_id: str,
    expected_manifest_content_hash: str,
    expected_artifacts: list[dict[str, Any]],
) -> None:
    """Re-verify the already-published TSC2 source-ingestion bundle against
    this slice's frozen pins. ``artifact_payloads`` is keyed by
    ``artifact_id``. Raises ``InputPinMismatchError`` if:

    - the manifest's own recomputed canonical content hash (via
      ``raptor.external.tsc2_sources.bundle.compute_bundle_content_hash`` --
      the existing source-bundle validator, never a hand-rolled
      recomputation) does not match its own recorded ``content_hash`` OR
      the pinned ``expected_manifest_content_hash``;
    - ``source_manifest['bundle_id']`` does not match ``expected_bundle_id``;
    - any pinned artifact (identified by ``artifact_id``) is missing from
      the manifest, or any of its pinned fields (``source_id``,
      ``relative_path``, ``sha256``, ``md5``, ``byte_length``, ...) does not
      match the manifest's own recorded value;
    - the ACTUAL injected artifact bytes' length/sha256/md5 do not match
      the pinned values (never merely trusting a declared value).
    """
    recomputed_hash = compute_bundle_content_hash(source_manifest)
    if recomputed_hash != expected_manifest_content_hash:
        raise InputPinMismatchError(
            "source bundle manifest recomputed canonical content hash "
            f"{recomputed_hash!r} does not match the pinned "
            f"{expected_manifest_content_hash!r}"
        )
    if source_manifest.get("content_hash") != expected_manifest_content_hash:
        raise InputPinMismatchError(
            "source bundle manifest's own recorded content_hash "
            f"{source_manifest.get('content_hash')!r} does not match the pinned "
            f"{expected_manifest_content_hash!r}"
        )
    if source_manifest.get("bundle_id") != expected_bundle_id:
        raise InputPinMismatchError(
            f"source bundle manifest bundle_id {source_manifest.get('bundle_id')!r} does not "
            f"match the pinned {expected_bundle_id!r}"
        )

    artifacts_by_id = {
        artifact.get("artifact_id"): artifact for artifact in source_manifest.get("artifacts", [])
    }
    for expected in expected_artifacts:
        artifact_id = expected["artifact_id"]
        manifest_artifact = artifacts_by_id.get(artifact_id)
        if manifest_artifact is None:
            raise InputPinMismatchError(
                f"pinned artifact {artifact_id!r} is missing from the source bundle manifest"
            )
        for field, expected_value in expected.items():
            if field == "artifact_id":
                continue
            if manifest_artifact.get(field) != expected_value:
                raise InputPinMismatchError(
                    f"source bundle manifest artifact {artifact_id!r} field {field!r} "
                    f"{manifest_artifact.get(field)!r} does not match the pinned "
                    f"{expected_value!r}"
                )

        payload = artifact_payloads.get(artifact_id)
        if payload is None:
            raise InputPinMismatchError(
                f"no injected artifact bytes supplied for pinned artifact {artifact_id!r}"
            )
        expected_length = expected.get("byte_length")
        if expected_length is not None and len(payload) != expected_length:
            raise InputPinMismatchError(
                f"artifact {artifact_id!r} actual byte length {len(payload)} does not match "
                f"the pinned {expected_length!r}"
            )
        expected_sha256 = expected.get("sha256")
        if expected_sha256 is not None:
            actual_sha256 = hashlib.sha256(payload).hexdigest()
            if actual_sha256.lower() != str(expected_sha256).lower():
                raise InputPinMismatchError(
                    f"artifact {artifact_id!r} actual sha256 {actual_sha256!r} does not match "
                    f"the pinned {expected_sha256!r}"
                )
        expected_md5 = expected.get("md5")
        if expected_md5 is not None:
            actual_md5 = hashlib.md5(payload).hexdigest()  # nosec B303 - pinned fingerprint compatibility
            if actual_md5.lower() != str(expected_md5).lower():
                raise InputPinMismatchError(
                    f"artifact {artifact_id!r} actual md5 {actual_md5!r} does not match the "
                    f"pinned {expected_md5!r}"
                )


def _select_pinned_artifact_ids(
    expected_artifacts: list[dict[str, Any]], required_source_ids: tuple[str, ...]
) -> dict[str, str]:
    """Return ``{source_id: artifact_id}`` selected EXACTLY from the
    plan-pinned ``expected_artifacts`` list -- never the first artifact a
    real source bundle happens to list for that ``source_id`` (a real
    source bundle lists metadata artifacts before the required score/
    download artifact). Raises ``InputPinMismatchError`` if any required
    ``source_id`` is missing a pin, or if any ``artifact_id``/``source_id``
    pin is duplicated."""
    by_source: dict[str, str] = {}
    seen_artifact_ids: set[str] = set()
    for item in expected_artifacts:
        source_id = item.get("source_id")
        artifact_id = item.get("artifact_id")
        if source_id not in required_source_ids:
            continue
        if artifact_id in seen_artifact_ids:
            raise InputPinMismatchError(
                f"plan input_bundle.artifacts pins duplicate artifact_id {artifact_id!r}"
            )
        seen_artifact_ids.add(artifact_id)
        if source_id in by_source:
            raise InputPinMismatchError(
                f"plan input_bundle.artifacts pins more than one artifact for source_id {source_id!r}"
            )
        by_source[source_id] = artifact_id

    missing = [source_id for source_id in required_source_ids if source_id not in by_source]
    if missing:
        raise InputPinMismatchError(
            f"plan input_bundle.artifacts is missing a pinned artifact_id for source_id(s): {missing!r}"
        )
    return by_source


def normalize_functional_bundle(
    *,
    plan: dict[str, Any],
    source_manifest: dict[str, Any],
    artifact_payloads: dict[str, bytes],
    reference_fasta_path: Path | str,
    normalizer: Any,
    normalizer_config: Any,
) -> dict[str, Any]:
    """Pure, offline orchestration: verify the reference FASTA checksum
    FIRST (before touching the source bundle or calling ``normalizer`` at
    all), then the frozen source bundle, then normalize all three sources.

    ``plan`` carries: ``reference`` (``accession``/``assembly``/``sha256``),
    ``expected_source_rows`` (per-source expected row counts),
    ``identity_pins`` (``gene``/``transcript``/``genomic_accession``/
    ``sge_source_transcript``/``sge_source_genomic_accession``/
    ``vamp_source_protein``), and (only needed once the reference check
    passes) ``input_bundle`` (``bundle_id``/``manifest_content_hash``/
    ``artifacts`` pins for ``validate_frozen_source_bundle``).

    Returns ``{"rows_by_source": {...}, "gene": ..., "identity_pins": ...}``
    for the operator to hand to ``bundle.build_normalization_manifest``/
    ``bundle.canonical_jsonl_bytes``.
    """
    reference = plan["reference"]
    validate_reference_fasta_checksum(
        reference_fasta_path=reference_fasta_path, expected_sha256=reference["sha256"]
    )

    input_bundle_plan = plan.get("input_bundle") or {}
    expected_artifacts = input_bundle_plan.get("artifacts", [])
    validate_frozen_source_bundle(
        source_manifest=source_manifest,
        artifact_payloads=artifact_payloads,
        expected_bundle_id=input_bundle_plan.get("bundle_id"),
        expected_manifest_content_hash=input_bundle_plan.get("manifest_content_hash"),
        expected_artifacts=expected_artifacts,
    )

    identity_pins = plan["identity_pins"]
    expected_source_rows = plan["expected_source_rows"]
    gene = identity_pins.get("gene", GENE)

    artifact_id_by_source = _select_pinned_artifact_ids(expected_artifacts, REQUIRED_SOURCE_IDS)

    mavedb_payload = artifact_payloads[artifact_id_by_source["mavedb_clipe"]]
    vamp_payload = artifact_payloads[artifact_id_by_source["igvf_vamp_seq"]]
    sge_payload = artifact_payloads[artifact_id_by_source["igvf_sge"]]

    mavedb_rows = normalize_mavedb(
        source_id="mavedb_clipe",
        csv_text=mavedb_payload.decode("utf-8"),
        expected_header=plan["header_pins"]["mavedb_clipe"],
        expected_rows=expected_source_rows["mavedb_clipe"],
        transcript=identity_pins["transcript"],
    )
    vamp_rows = normalize_vamp_seq(
        source_id="igvf_vamp_seq",
        tsv_gz_bytes=vamp_payload,
        expected_header=plan["header_pins"]["igvf_vamp_seq"],
        expected_rows=expected_source_rows["igvf_vamp_seq"],
        required_protein_accession=identity_pins["vamp_source_protein"],
    )
    sge_rows = normalize_sge(
        source_id="igvf_sge",
        tsv_gz_bytes=sge_payload,
        expected_header=plan["header_pins"]["igvf_sge"],
        expected_rows=expected_source_rows["igvf_sge"],
        expected_source_transcript=identity_pins["sge_source_transcript"],
        expected_source_genomic_accession=identity_pins["sge_source_genomic_accession"],
        normalized_transcript=identity_pins["transcript"],
        normalized_genomic_accession=identity_pins["genomic_accession"],
        assembly=reference["assembly"],
        gene=gene,
        normalizer=normalizer,
        normalizer_config=normalizer_config,
    )

    return {
        "rows_by_source": {
            "mavedb_clipe": mavedb_rows,
            "igvf_vamp_seq": vamp_rows,
            "igvf_sge": sge_rows,
        },
        "gene": gene,
        "identity_pins": identity_pins,
    }


__all__ = [
    "REQUIRED_SOURCE_IDS",
    "FunctionalNormalizationError",
    "InputPinMismatchError",
    "ReferenceIntegrityError",
    "validate_frozen_source_bundle",
    "validate_reference_fasta_checksum",
    "normalize_functional_bundle",
]
