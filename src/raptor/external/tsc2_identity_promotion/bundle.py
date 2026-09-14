"""RAPTOR v2 TSC2 functional-identity promotion -- output bundle manifest,
canonical hashing/JSONL, create-only/symlink-safe publication and a
compact, aggregate-only committed summary.

This mirrors ``raptor.external.tsc2_functional.bundle`` closely but for
the ``raptor.external.tsc2_functional_identity_promotion_bundle.v1``
manifest schema: ``build_identity_promotion_manifest`` computes the same
canonical ``content_hash`` (SHA-256 of UTF-8 canonical JSON, sorted object
keys, ``(",", ":")`` separators, array order preserved, only the
top-level ``content_hash`` key itself excluded).

``canonical_jsonl_bytes`` reuses ``raptor.external.tsc2_functional.model``
directly (the SAME ``NormalizedFunctionalRow``/``REQUIRED_ROW_FIELDS`` the
row-contract amendment lives in -- never a reimplementation) to fully
revalidate every row and reject a duplicate ``(source_id, source_row)``
key, then emits one canonical sorted-key JSON object per line, UTF-8,
LF-only, with a final newline.

``publish_identity_promotion_bundle`` reuses this repository's already-
hardened external/create-only/symlink-safe/race-safe/manifest-last
publication primitive -- ``raptor.external.tsc2_sources.bundle.
_publish_directory_no_replace`` -- verbatim (the SAME function object,
not a reimplementation) for the actual atomic no-clobber directory
rename, and reuses that module's other private boundary helpers (run-name
validation, symlink-ancestry checks, the publication-reservation lock,
and the safe relative-path join) rather than duplicating their hardened,
previously-tested logic; boundary/hash violations raised by those helpers
are translated into this module's own
``PromotionBundleBoundaryError``/``PromotionManifestError`` domain errors.

``build_committed_summary`` is a strict field-whitelist projection off an
already-built manifest: aggregate pins, counts, hashes and overlap
statistics only -- never a per-row identity, HGVS/SPDI string, raw score,
source functional class, or any clinical/evidence-strength claim.

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

from raptor.external.tsc2_functional.model import (
    ALLOWED_IDENTITY_STATES,
    ALLOWED_UNRESOLVED_REASONS,
    ALLOWED_VARIANT_KINDS,
    IDENTITY_STATE_TO_UNRESOLVED_REASON,
    REQUIRED_ROW_FIELDS,
    NormalizationContractError,
    NormalizedFunctionalRow,
)
from raptor.external.tsc2_sources.bundle import BundleBoundaryError as _SourceBundleBoundaryError
from raptor.external.tsc2_sources.bundle import MANIFEST_FILENAME
from raptor.external.tsc2_sources.bundle import _assert_no_symlink_ancestry
from raptor.external.tsc2_sources.bundle import _publish_directory_no_replace
from raptor.external.tsc2_sources.bundle import _release_reservation
from raptor.external.tsc2_sources.bundle import _reserve_run_name
from raptor.external.tsc2_sources.bundle import _safe_join
from raptor.external.tsc2_sources.bundle import _validate_run_name

PROMOTION_BUNDLE_SCHEMA = "raptor.external.tsc2_functional_identity_promotion_bundle.v1"
PROMOTION_SUMMARY_SCHEMA = "raptor.external.tsc2_functional_identity_promotion_summary.v1"

#: The exact three source_id values this slice promotes.
_SOURCE_IDS = ("mavedb_clipe", "igvf_vamp_seq", "igvf_sge")

#: The exact three pairwise overlap keys this slice's config/spec pins.
_OVERLAP_PAIR_KEYS = frozenset(
    {"mavedb_clipe__igvf_sge", "igvf_vamp_seq__igvf_sge", "mavedb_clipe__igvf_vamp_seq"}
)

#: The two source_ids each pairwise overlap key is computed from -- used
#: to bound each pairwise count by ``min`` of its two source counts.
_OVERLAP_PAIR_SOURCES: dict[str, tuple[str, str]] = {
    "mavedb_clipe__igvf_sge": ("mavedb_clipe", "igvf_sge"),
    "igvf_vamp_seq__igvf_sge": ("igvf_vamp_seq", "igvf_sge"),
    "mavedb_clipe__igvf_vamp_seq": ("mavedb_clipe", "igvf_vamp_seq"),
}

#: The exact, whitelisted (artifact_id -> relative_path) mapping this
#: slice's three promoted per-source JSONL artifacts must use -- an
#: artifact_id outside this map (however plausible-looking, e.g. a
#: clinical/HGVS-sounding id smuggled in by a self-hashed, otherwise
#: internally-consistent manifest) or a relative_path that does not match
#: its artifact_id's pinned value is always rejected. Reject missing,
#: extra or alternate artifact_id/relative_path pairings.
_CANONICAL_ARTIFACT_RELATIVE_PATHS: dict[str, str] = {
    "mavedb_clipe-promoted-jsonl": "normalized/mavedb_clipe.jsonl",
    "igvf_vamp_seq-promoted-jsonl": "normalized/igvf_vamp_seq.jsonl",
    "igvf_sge-promoted-jsonl": "normalized/igvf_sge.jsonl",
}

#: The exact, fixed boundaries mapping every promotion manifest must
#: carry verbatim -- no additional/missing key and no value other than
#: ``"forbidden"`` is ever tolerated, regardless of whether the manifest
#: is otherwise internally self-hash-consistent.
_REQUIRED_BOUNDARIES: dict[str, str] = {
    "network": "forbidden",
    "clinical_use": "forbidden",
    "evidence_strength_use": "forbidden",
}

_REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "bundle_id",
        "created_at",
        "input_manifests",
        "artifacts",
        "counts",
        "source_row_counts",
        "identity_state_counts",
        "unresolved_reason_counts",
        "variant_kind_counts",
        "verified_observations_by_source",
        "verified_observations",
        "verified_unique_spdi",
        "duplicate_verified_observations",
        "source_overlap",
        "conservation",
        "boundaries",
        "content_hash",
    }
)
_REQUIRED_MANIFEST_FIELDS_NO_HASH = _REQUIRED_MANIFEST_FIELDS - {"content_hash"}

_REQUIRED_ARTIFACT_FIELDS = frozenset({"artifact_id", "relative_path", "byte_length", "sha256", "row_count"})
_REQUIRED_INPUT_MANIFEST_KEYS = frozenset({"functional_normalization", "clipe_projector", "vamp_crosswalk"})
_REQUIRED_CONSERVATION_FIELDS = frozenset({"input_rows", "output_rows", "dropped_rows", "duplicate_source_rows"})
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class PromotionBundleBoundaryError(ValueError):
    """Raised for output-path boundary violations: writing inside the
    repository, writing onto a pre-existing (create-only) final run path,
    or writing onto a symlink/reparse-point run leaf."""


class PromotionManifestError(ValueError):
    """Raised when a promotion manifest's ``content_hash`` does not match
    its recomputed canonical hash, when a published artifact payload's
    actual bytes do not match its manifest-declared ``byte_length``/
    ``sha256``, or when the manifest itself violates its schema/
    conservation invariants."""


def _validate_safe_relative_path(relative_path: Any, *, context: str) -> None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise PromotionManifestError(f"{context}: relative_path must be a non-blank string")
    if PureWindowsPath(relative_path).drive or PurePosixPath(relative_path).is_absolute():
        raise PromotionManifestError(f"{context}: relative_path must not be absolute: {relative_path!r}")
    parts = PurePosixPath(relative_path).parts
    if not parts or any(part in (".", "..") for part in parts):
        raise PromotionManifestError(
            f"{context}: relative_path must not contain traversal components: {relative_path!r}"
        )


def _validate_artifact_record(artifact: Any, *, index: int) -> None:
    if not isinstance(artifact, dict) or set(artifact) != _REQUIRED_ARTIFACT_FIELDS:
        actual = set(artifact) if isinstance(artifact, dict) else set()
        missing = _REQUIRED_ARTIFACT_FIELDS - actual
        extra = actual - _REQUIRED_ARTIFACT_FIELDS
        raise PromotionManifestError(
            f"artifacts[{index}] does not have the exact required fields; "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
        )
    if not isinstance(artifact["artifact_id"], str) or not artifact["artifact_id"].strip():
        raise PromotionManifestError(f"artifacts[{index}].artifact_id must be a non-blank string")
    _validate_safe_relative_path(artifact["relative_path"], context=f"artifacts[{index}]")
    canonical_relative_path = _CANONICAL_ARTIFACT_RELATIVE_PATHS.get(artifact["artifact_id"])
    if canonical_relative_path is None:
        raise PromotionManifestError(
            f"artifacts[{index}].artifact_id {artifact['artifact_id']!r} is not one of the exact "
            f"whitelisted artifact_ids {sorted(_CANONICAL_ARTIFACT_RELATIVE_PATHS)!r}"
        )
    if artifact["relative_path"] != canonical_relative_path:
        raise PromotionManifestError(
            f"artifacts[{index}].relative_path {artifact['relative_path']!r} does not match the "
            f"pinned relative_path {canonical_relative_path!r} for artifact_id "
            f"{artifact['artifact_id']!r}"
        )
    byte_length = artifact["byte_length"]
    if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length < 0:
        raise PromotionManifestError(f"artifacts[{index}].byte_length must be a non-negative int")
    row_count = artifact["row_count"]
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
        raise PromotionManifestError(f"artifacts[{index}].row_count must be a non-negative int")
    sha256 = artifact["sha256"]
    if not isinstance(sha256, str) or not _SHA256_HEX_RE.match(sha256):
        raise PromotionManifestError(f"artifacts[{index}].sha256 must be a 64-hex-digit string")


def _validate_count_dict(value: Any, *, allowed_keys: frozenset[str], context: str) -> None:
    if not isinstance(value, dict):
        raise PromotionManifestError(f"{context} must be a mapping")
    unknown = set(value) - allowed_keys
    if unknown:
        raise PromotionManifestError(f"{context} has unknown key(s): {sorted(unknown)!r}")
    for key, count in value.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise PromotionManifestError(f"{context}[{key!r}] must be a non-negative int")


def _validate_manifest_contract(manifest: dict[str, Any], *, require_content_hash: bool) -> None:
    """Validate a promotion manifest's exact schema and conservation
    invariants. Raises ``PromotionManifestError`` on any violation."""
    expected_fields = _REQUIRED_MANIFEST_FIELDS if require_content_hash else _REQUIRED_MANIFEST_FIELDS_NO_HASH
    if set(manifest) != expected_fields:
        missing = expected_fields - set(manifest)
        extra = set(manifest) - expected_fields
        raise PromotionManifestError(
            f"manifest does not have the exact required fields; missing={sorted(missing)!r} "
            f"extra={sorted(extra)!r}"
        )
    if manifest["schema"] != PROMOTION_BUNDLE_SCHEMA:
        raise PromotionManifestError(f"manifest schema must be {PROMOTION_BUNDLE_SCHEMA!r}, got {manifest['schema']!r}")

    input_manifests = manifest["input_manifests"]
    if not isinstance(input_manifests, dict) or set(input_manifests) != _REQUIRED_INPUT_MANIFEST_KEYS:
        raise PromotionManifestError(
            f"manifest.input_manifests must have exactly the keys {sorted(_REQUIRED_INPUT_MANIFEST_KEYS)!r}"
        )
    for key, value in input_manifests.items():
        if not isinstance(value, str) or not _SHA256_HEX_RE.match(value):
            raise PromotionManifestError(f"manifest.input_manifests[{key!r}] must be a 64-hex-digit string")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise PromotionManifestError("manifest.artifacts must be a non-empty list")
    seen_artifact_ids: set[str] = set()
    seen_relative_paths: set[str] = set()
    total_row_count = 0
    for index, artifact in enumerate(artifacts):
        _validate_artifact_record(artifact, index=index)
        artifact_id = artifact["artifact_id"]
        relative_path = artifact["relative_path"]
        if artifact_id in seen_artifact_ids:
            raise PromotionManifestError(f"duplicate artifact_id {artifact_id!r} in manifest.artifacts")
        seen_artifact_ids.add(artifact_id)
        if relative_path in seen_relative_paths:
            raise PromotionManifestError(f"duplicate relative_path {relative_path!r} in manifest.artifacts")
        seen_relative_paths.add(relative_path)
        total_row_count += artifact["row_count"]

    if seen_artifact_ids != set(_CANONICAL_ARTIFACT_RELATIVE_PATHS):
        missing_ids = set(_CANONICAL_ARTIFACT_RELATIVE_PATHS) - seen_artifact_ids
        extra_ids = seen_artifact_ids - set(_CANONICAL_ARTIFACT_RELATIVE_PATHS)
        raise PromotionManifestError(
            "manifest.artifacts must contain exactly the three whitelisted artifact_ids "
            f"{sorted(_CANONICAL_ARTIFACT_RELATIVE_PATHS)!r}; missing={sorted(missing_ids)!r} "
            f"extra={sorted(extra_ids)!r}"
        )

    counts = manifest["counts"]
    if not isinstance(counts, dict) or set(counts) != {"rows"}:
        raise PromotionManifestError("manifest.counts must have exactly the field 'rows'")
    if not isinstance(counts["rows"], int) or isinstance(counts["rows"], bool) or counts["rows"] < 0:
        raise PromotionManifestError(f"manifest.counts.rows must be a non-negative int, got {counts['rows']!r}")
    if total_row_count != counts["rows"]:
        raise PromotionManifestError(
            f"sum of artifact row_count values {total_row_count!r} does not match manifest.counts.rows "
            f"{counts['rows']!r}"
        )

    source_row_counts = manifest["source_row_counts"]
    if not isinstance(source_row_counts, dict) or set(source_row_counts) != set(_SOURCE_IDS):
        raise PromotionManifestError(
            f"manifest.source_row_counts must have exactly the keys {sorted(_SOURCE_IDS)!r}"
        )
    for source_id, count in source_row_counts.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise PromotionManifestError(f"manifest.source_row_counts[{source_id!r}] must be a non-negative int")
    if sum(source_row_counts.values()) != counts["rows"]:
        raise PromotionManifestError("manifest.source_row_counts values do not sum to manifest.counts.rows")

    identity_state_counts = manifest["identity_state_counts"]
    if not isinstance(identity_state_counts, dict) or set(identity_state_counts) != set(ALLOWED_IDENTITY_STATES):
        raise PromotionManifestError(
            f"manifest.identity_state_counts must have exactly the keys {sorted(ALLOWED_IDENTITY_STATES)!r}"
        )
    for state, count in identity_state_counts.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise PromotionManifestError(f"manifest.identity_state_counts[{state!r}] must be a non-negative int")
    if sum(identity_state_counts.values()) != counts["rows"]:
        raise PromotionManifestError("manifest.identity_state_counts values do not sum to manifest.counts.rows")

    expected_unresolved_keys = {
        reason for reason in IDENTITY_STATE_TO_UNRESOLVED_REASON.values() if reason is not None
    }
    unresolved_reason_counts = manifest["unresolved_reason_counts"]
    if not isinstance(unresolved_reason_counts, dict) or set(unresolved_reason_counts) != expected_unresolved_keys:
        raise PromotionManifestError(
            f"manifest.unresolved_reason_counts must have exactly the keys {sorted(expected_unresolved_keys)!r}"
        )
    for reason, count in unresolved_reason_counts.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise PromotionManifestError(f"manifest.unresolved_reason_counts[{reason!r}] must be a non-negative int")

    for state, reason in IDENTITY_STATE_TO_UNRESOLVED_REASON.items():
        if reason is None:
            continue
        if unresolved_reason_counts[reason] != identity_state_counts[state]:
            raise PromotionManifestError(
                f"manifest.unresolved_reason_counts[{reason!r}] {unresolved_reason_counts[reason]!r} "
                f"does not match manifest.identity_state_counts[{state!r}] {identity_state_counts[state]!r}"
            )

    variant_kind_counts = manifest["variant_kind_counts"]
    if not isinstance(variant_kind_counts, dict) or set(variant_kind_counts) != set(ALLOWED_VARIANT_KINDS):
        raise PromotionManifestError(
            f"manifest.variant_kind_counts must have exactly the keys {sorted(ALLOWED_VARIANT_KINDS)!r}"
        )
    for kind, count in variant_kind_counts.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise PromotionManifestError(f"manifest.variant_kind_counts[{kind!r}] must be a non-negative int")
    if sum(variant_kind_counts.values()) != counts["rows"]:
        raise PromotionManifestError("manifest.variant_kind_counts values do not sum to manifest.counts.rows")

    verified_observations_by_source = manifest["verified_observations_by_source"]
    _validate_count_dict(
        verified_observations_by_source, allowed_keys=frozenset(_SOURCE_IDS),
        context="manifest.verified_observations_by_source",
    )
    if set(verified_observations_by_source) != set(_SOURCE_IDS):
        raise PromotionManifestError(
            f"manifest.verified_observations_by_source must have exactly the keys {sorted(_SOURCE_IDS)!r}"
        )
    if sum(verified_observations_by_source.values()) != manifest["verified_observations"]:
        raise PromotionManifestError(
            "manifest.verified_observations_by_source values do not sum to manifest.verified_observations"
        )
    if manifest["verified_observations"] != identity_state_counts["GENOMIC_SPDI_VERIFIED"]:
        raise PromotionManifestError(
            "manifest.verified_observations does not match "
            "manifest.identity_state_counts['GENOMIC_SPDI_VERIFIED']"
        )

    for field_name in ("verified_observations", "verified_unique_spdi", "duplicate_verified_observations"):
        value = manifest[field_name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PromotionManifestError(f"manifest.{field_name} must be a non-negative int")

    source_overlap = manifest["source_overlap"]
    if not isinstance(source_overlap, dict) or set(source_overlap) != {"pairwise", "triple"}:
        raise PromotionManifestError("manifest.source_overlap must have exactly the keys 'pairwise'/'triple'")
    pairwise = source_overlap["pairwise"]
    if not isinstance(pairwise, dict) or set(pairwise) != _OVERLAP_PAIR_KEYS:
        raise PromotionManifestError(
            f"manifest.source_overlap.pairwise must have exactly the keys {sorted(_OVERLAP_PAIR_KEYS)!r}"
        )
    for key, count in pairwise.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise PromotionManifestError(f"manifest.source_overlap.pairwise[{key!r}] must be a non-negative int")
    triple = source_overlap["triple"]
    if not isinstance(triple, int) or isinstance(triple, bool) or triple < 0:
        raise PromotionManifestError("manifest.source_overlap.triple must be a non-negative int")

    # Overlap set arithmetic (spec's cross-source overlap invariants): each
    # pairwise intersection can never exceed either of its two source
    # counts, the triple intersection can never exceed any pairwise
    # intersection, and verified_unique_spdi/duplicate_verified_observations
    # are EXACTLY determined (never merely bounded) by inclusion-exclusion
    # over the three verified-observation sets.
    for pair_key, (source_a, source_b) in _OVERLAP_PAIR_SOURCES.items():
        bound = min(verified_observations_by_source[source_a], verified_observations_by_source[source_b])
        if pairwise[pair_key] > bound:
            raise PromotionManifestError(
                f"manifest.source_overlap.pairwise[{pair_key!r}] {pairwise[pair_key]!r} exceeds the "
                f"maximum possible intersection {bound!r} of sources {source_a!r}/{source_b!r}"
            )
    triple_bound = min(pairwise.values())
    if triple > triple_bound:
        raise PromotionManifestError(
            f"manifest.source_overlap.triple {triple!r} exceeds the maximum possible triple "
            f"intersection {triple_bound!r} (bounded by the smallest pairwise intersection)"
        )

    # Venn-region nonnegativity (A=mavedb_clipe, B=igvf_vamp_seq,
    # C=igvf_sge): each disjoint region implied by the pinned
    # pairwise/triple counts must itself be >= 0, catching impossible
    # overlap shapes that the upper-bound checks above miss.
    ab_only = pairwise["mavedb_clipe__igvf_vamp_seq"] - triple
    ac_only = pairwise["mavedb_clipe__igvf_sge"] - triple
    bc_only = pairwise["igvf_vamp_seq__igvf_sge"] - triple
    a_only = (
        verified_observations_by_source["mavedb_clipe"]
        - pairwise["mavedb_clipe__igvf_vamp_seq"]
        - pairwise["mavedb_clipe__igvf_sge"]
        + triple
    )
    b_only = (
        verified_observations_by_source["igvf_vamp_seq"]
        - pairwise["mavedb_clipe__igvf_vamp_seq"]
        - pairwise["igvf_vamp_seq__igvf_sge"]
        + triple
    )
    c_only = (
        verified_observations_by_source["igvf_sge"]
        - pairwise["mavedb_clipe__igvf_sge"]
        - pairwise["igvf_vamp_seq__igvf_sge"]
        + triple
    )
    for region_name, region_value in (
        ("AB_only", ab_only),
        ("AC_only", ac_only),
        ("BC_only", bc_only),
        ("A_only", a_only),
        ("B_only", b_only),
        ("C_only", c_only),
    ):
        if region_value < 0:
            raise PromotionManifestError(
                f"manifest.source_overlap implies a negative Venn region {region_name}={region_value!r}; "
                "the pinned pairwise/triple overlap counts describe an impossible overlap shape"
            )

    expected_unique_spdi = sum(verified_observations_by_source.values()) - sum(pairwise.values()) + triple
    if manifest["verified_unique_spdi"] != expected_unique_spdi:
        raise PromotionManifestError(
            f"manifest.verified_unique_spdi {manifest['verified_unique_spdi']!r} does not match the "
            "inclusion-exclusion value derived from verified_observations_by_source/source_overlap "
            f"{expected_unique_spdi!r}"
        )
    expected_duplicate_observations = manifest["verified_observations"] - manifest["verified_unique_spdi"]
    if manifest["duplicate_verified_observations"] != expected_duplicate_observations:
        raise PromotionManifestError(
            f"manifest.duplicate_verified_observations {manifest['duplicate_verified_observations']!r} "
            f"does not match verified_observations - verified_unique_spdi {expected_duplicate_observations!r}"
        )

    conservation = manifest["conservation"]
    if not isinstance(conservation, dict) or set(conservation) != _REQUIRED_CONSERVATION_FIELDS:
        raise PromotionManifestError(
            f"manifest.conservation must have exactly the keys {sorted(_REQUIRED_CONSERVATION_FIELDS)!r}"
        )
    for field_name in _REQUIRED_CONSERVATION_FIELDS:
        value = conservation[field_name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PromotionManifestError(f"manifest.conservation[{field_name!r}] must be a non-negative int")
    if conservation["input_rows"] != conservation["output_rows"] + conservation["dropped_rows"]:
        raise PromotionManifestError(
            "manifest.conservation.input_rows must equal output_rows + dropped_rows"
        )
    if conservation["output_rows"] != counts["rows"]:
        raise PromotionManifestError("manifest.conservation.output_rows must equal manifest.counts.rows")

    if manifest["boundaries"] != _REQUIRED_BOUNDARIES:
        raise PromotionManifestError(
            f"manifest.boundaries must be exactly {_REQUIRED_BOUNDARIES!r}, got {manifest['boundaries']!r}"
        )


def compute_manifest_content_hash(manifest: dict[str, Any]) -> str:
    """SHA-256 of the manifest's UTF-8 canonical JSON (sorted object keys,
    ``(",", ":")`` separators, array order preserved), excluding ONLY the
    top-level ``content_hash`` key itself."""
    basis = {key: value for key, value in manifest.items() if key != "content_hash"}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_manifest_content_hash(manifest: dict[str, Any]) -> None:
    """Raise ``PromotionManifestError`` if the manifest violates its own
    schema/conservation invariants, or if ``manifest['content_hash']``
    does not match the manifest's recomputed canonical content hash."""
    _validate_manifest_contract(manifest, require_content_hash=True)
    recomputed = compute_manifest_content_hash(manifest)
    if recomputed != manifest["content_hash"]:
        raise PromotionManifestError(
            f"promotion manifest content_hash mismatch: recorded {manifest['content_hash']!r} != "
            f"recomputed {recomputed!r}"
        )


def build_identity_promotion_manifest(
    *,
    bundle_id: str,
    created_at: str,
    input_manifests: dict[str, str],
    artifacts: list[dict[str, Any]],
    counts: dict[str, Any],
    source_row_counts: dict[str, int],
    identity_state_counts: dict[str, int],
    unresolved_reason_counts: dict[str, int],
    variant_kind_counts: dict[str, int],
    verified_observations_by_source: dict[str, int],
    verified_observations: int,
    verified_unique_spdi: int,
    duplicate_verified_observations: int,
    source_overlap: dict[str, Any],
    conservation: dict[str, int],
    boundaries: dict[str, Any],
) -> dict[str, Any]:
    """Build, validate and canonically self-hash a
    ``raptor.external.tsc2_functional_identity_promotion_bundle.v1``
    manifest. Raises ``PromotionManifestError`` if the assembled manifest
    violates its schema/conservation invariants."""
    manifest: dict[str, Any] = {
        "schema": PROMOTION_BUNDLE_SCHEMA,
        "bundle_id": bundle_id,
        "created_at": created_at,
        "input_manifests": dict(input_manifests),
        "artifacts": [dict(artifact) for artifact in artifacts],
        "counts": dict(counts),
        "source_row_counts": dict(source_row_counts),
        "identity_state_counts": dict(identity_state_counts),
        "unresolved_reason_counts": dict(unresolved_reason_counts),
        "variant_kind_counts": dict(variant_kind_counts),
        "verified_observations_by_source": dict(verified_observations_by_source),
        "verified_observations": verified_observations,
        "verified_unique_spdi": verified_unique_spdi,
        "duplicate_verified_observations": duplicate_verified_observations,
        "source_overlap": {
            "pairwise": dict(source_overlap["pairwise"]),
            "triple": source_overlap["triple"],
        },
        "conservation": dict(conservation),
        "boundaries": dict(boundaries),
    }
    _validate_manifest_contract(manifest, require_content_hash=False)
    manifest["content_hash"] = compute_manifest_content_hash(manifest)
    return manifest


def canonical_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    """Validate and fully revalidate every row (reconstructing it through
    ``raptor.external.tsc2_functional.model.NormalizedFunctionalRow`` --
    never merely checking its key set) and reject a duplicate
    ``(source_id, source_row)`` key, then return one canonical sorted-key
    compact JSON object per line, UTF-8, LF-only, with a final newline.
    Deterministic regardless of any row's dict/JSON key order, and
    regardless of reordering unrelated rows -- only a byte change to an
    actual row changes the output."""
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


def publish_identity_promotion_bundle(
    *,
    repo_root: Path,
    output_root: Path,
    run_name: str,
    manifest: dict[str, Any],
    payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Publish ``manifest`` and ``payloads`` (keyed by ``artifact_id``) to
    ``output_root/run_name`` -- external, create-only, atomic and
    symlink-safe. Reuses ``raptor.external.tsc2_sources.bundle``'s
    already-hardened private boundary helpers (translating any
    ``BundleBoundaryError`` they raise into
    ``PromotionBundleBoundaryError``) and its exact
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
        raise PromotionBundleBoundaryError(str(exc)) from exc

    try:
        _assert_no_symlink_ancestry(output_root, role="output_root")
    except _SourceBundleBoundaryError as exc:
        raise PromotionBundleBoundaryError(str(exc)) from exc

    resolved_repo_root = repo_root.resolve()
    resolved_output_root = output_root.resolve()
    try:
        resolved_output_root.relative_to(resolved_repo_root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    if inside_repo:
        raise PromotionBundleBoundaryError(
            f"output_root {output_root} resolves inside repo_root {repo_root}; the external "
            "promotion bundle must never be written inside the repository"
        )

    final_run_dir = output_root / run_name
    if final_run_dir.is_symlink():
        raise PromotionBundleBoundaryError(
            f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
        )
    if final_run_dir.exists():
        raise PromotionBundleBoundaryError(
            f"output run path {final_run_dir} already exists; runs are create-only and are never "
            "overwritten or silently resumed"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    try:
        _assert_no_symlink_ancestry(output_root, role="output_root")
    except _SourceBundleBoundaryError as exc:
        raise PromotionBundleBoundaryError(str(exc)) from exc

    try:
        reservation_path = _reserve_run_name(output_root, run_name)
    except _SourceBundleBoundaryError as exc:
        raise PromotionBundleBoundaryError(str(exc)) from exc

    try:
        if final_run_dir.is_symlink():
            raise PromotionBundleBoundaryError(
                f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
            )
        if final_run_dir.exists():
            raise PromotionBundleBoundaryError(
                f"output run path {final_run_dir} already exists; runs are create-only and are "
                "never overwritten or silently resumed"
            )

        staging_dir = output_root / f".{run_name}.staging-{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=False, exist_ok=False)

        try:
            for artifact in manifest["artifacts"]:
                artifact_id = artifact["artifact_id"]
                relative_path = artifact["relative_path"]
                payload = payloads.get(artifact_id)
                if payload is None:
                    raise PromotionManifestError(
                        f"missing promoted artifact payload bytes for artifact_id {artifact_id!r} "
                        f"(relative_path={relative_path!r})"
                    )
                if len(payload) != artifact["byte_length"]:
                    raise PromotionManifestError(
                        f"artifact {artifact_id!r} byte_length mismatch: expected "
                        f"{artifact['byte_length']!r}, observed {len(payload)!r} bytes"
                    )
                observed_sha256 = hashlib.sha256(payload).hexdigest()
                if observed_sha256.lower() != artifact["sha256"].lower():
                    raise PromotionManifestError(
                        f"artifact {artifact_id!r} sha256 mismatch: expected {artifact['sha256']!r}, "
                        f"observed {observed_sha256!r}"
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
            raise PromotionBundleBoundaryError(str(exc)) from exc
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        try:
            _publish_directory_no_replace(staging_dir, final_run_dir)
        except FileExistsError as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise PromotionBundleBoundaryError(
                f"output run path {final_run_dir} was concurrently created by another writer "
                "during publication; refusing to replace a competing publication"
            ) from exc
        except OSError as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise PromotionBundleBoundaryError(
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
    already-built promotion manifest: pins/hashes, counts, per-source row
    counts, per-artifact integrity metadata, identity/unresolved/variant-
    kind counts, verified-observation/unique-SPDI/overlap statistics and
    conservation. NEVER includes a per-row identity, HGVS/SPDI string, raw
    score, source functional class, or any clinical/evidence-strength
    claim (enforced structurally: this function is a strict field-
    whitelist projection).

    Always fully re-validates ``manifest`` (schema/whitelist/arithmetic
    invariants AND its own recomputed ``content_hash``) via
    ``validate_manifest_content_hash`` BEFORE projecting any field: a
    manifest that is internally self-hash-consistent (i.e. its
    ``content_hash`` was recomputed after tampering) but violates the
    artifact-id whitelist, the exact boundaries mapping, or any count/
    arithmetic invariant must never reach the committed summary."""
    validate_manifest_content_hash(manifest)

    artifact_integrity = {
        artifact["artifact_id"]: {
            "sha256": artifact["sha256"],
            "byte_length": artifact["byte_length"],
            "row_count": artifact["row_count"],
        }
        for artifact in manifest["artifacts"]
    }

    return {
        "schema": PROMOTION_SUMMARY_SCHEMA,
        "bundle_id": manifest["bundle_id"],
        "manifest_content_hash": manifest["content_hash"],
        "input_manifest_hashes": manifest["input_manifests"],
        "artifact_integrity": artifact_integrity,
        "source_row_counts": manifest["source_row_counts"],
        "identity_state_counts": manifest["identity_state_counts"],
        "unresolved_reason_counts": manifest["unresolved_reason_counts"],
        "variant_kind_counts": manifest["variant_kind_counts"],
        "verified_observations_by_source": manifest["verified_observations_by_source"],
        "verified_observations": manifest["verified_observations"],
        "verified_unique_spdi": manifest["verified_unique_spdi"],
        "duplicate_verified_observations": manifest["duplicate_verified_observations"],
        "source_overlap": manifest["source_overlap"],
        "conservation": manifest["conservation"],
        "boundaries": manifest["boundaries"],
    }


__all__ = [
    "PROMOTION_BUNDLE_SCHEMA",
    "PROMOTION_SUMMARY_SCHEMA",
    "PromotionBundleBoundaryError",
    "PromotionManifestError",
    "compute_manifest_content_hash",
    "validate_manifest_content_hash",
    "build_identity_promotion_manifest",
    "canonical_jsonl_bytes",
    "publish_identity_promotion_bundle",
    "build_committed_summary",
    "_publish_directory_no_replace",
]
