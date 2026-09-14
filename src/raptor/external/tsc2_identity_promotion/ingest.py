"""RAPTOR v2 TSC2 functional-identity promotion -- frozen-input validation,
the exact cliPE/VAMP/SGE join, and deterministic verified-SPDI overlap.

``validate_input_bundle_manifests`` re-verifies all three already-published
upstream bundle manifests (the functional normalization bundle, the cliPE
cDNA->SPDI projector bundle and the VAMP-seq genomic crosswalk bundle)
against this slice's exact pinned expectations BEFORE any of their
artifact bytes are even read: each manifest's own canonical content hash
is recomputed (never trusted from a caller-supplied field alone) and must
match BOTH its own recorded ``content_hash`` (internal self-consistency)
AND the caller's pinned expectation, its ``bundle_id`` must match, and
exactly one artifact record matching each pinned ``artifact_id`` must be
present with exactly the pinned ``relative_path``/``sha256``/
``byte_length``/``row_count``.

``read_pinned_artifact_payloads`` then reads each artifact's actual bytes
from ``<root>/<run_name>/<relative_path>`` -- a trusted, pinned path this
function independently re-verifies for safety (no absolute path, no
traversal component, no backslash separator, and the resolved real path
must stay within ``<root>/<run_name>``, so neither a symlinked leaf nor an
escaping relative path is ever followed) -- and re-verifies the actual
bytes' length/sha256 against the manifest-pinned values.

``promote_functional_identities`` is the pure, offline join: it fully
revalidates every functional row, cliPE mapping row and VAMP crosswalk row
against their exact schemas (``raptor.external.tsc2_functional.model``,
``raptor.external.tsc2_cdna_projector.model``,
``raptor.external.tsc2_vamp_crosswalk.model``), requires every source's
``source_row`` sequence to be duplicate-free and contiguous 1..N, joins
cliPE mapping rows onto their functional row by ``(source_row,
source_record_id)`` (requiring ``hgvs_c`` agreement and a
``PROJECTED_FASTA_VERIFIED`` status on EVERY mapping row), joins VAMP
crosswalk rows onto their functional row by ``(source_row,
protein_variant)`` (requiring the full protein token to agree and mapping
exactly the three non-reference-mismatch crosswalk statuses to their
promoted identity state/reason), and copies every SGE row through
byte-identically after revalidation. Every input row is conserved: nothing
is ever silently dropped, and any invariant violation aborts the WHOLE
run.

``compute_verified_spdi_overlap`` computes deterministic (row-order
independent) verified-observation, unique-SPDI and pairwise/triple
cross-source overlap counts from a list of already-promoted rows.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from raptor.external.tsc2_cdna_projector.model import (
    REQUIRED_MAPPING_ROW_FIELDS,
    ClipeCdnaSpdiMappingRow,
    ProjectionContractError,
)
from raptor.external.tsc2_functional.model import (
    REQUIRED_ROW_FIELDS,
    NormalizationContractError,
    NormalizedFunctionalRow,
)
from raptor.external.tsc2_sources.bundle import BundleBoundaryError as _SourceBundleBoundaryError
from raptor.external.tsc2_sources.bundle import _validate_run_name
from raptor.external.tsc2_vamp_crosswalk.model import (
    REQUIRED_CROSSWALK_ROW_FIELDS,
    CrosswalkContractError,
    VampGenomicCrosswalkRow,
)

from .model import PromotionModelError, spdi_to_hgvs_g

#: The exact three source_id values this slice promotes (spec ``inputs``/
#: ``join_rules``) -- never caller-configurable.
_SOURCE_IDS = ("mavedb_clipe", "igvf_vamp_seq", "igvf_sge")

#: VAMP crosswalk status -> promoted-field mapping (spec
#: ``join_rules.vamp.status_mapping``). ``SOURCE_COORDINATE_REFERENCE_
#: MISMATCH`` and any unknown status are handled separately -- both abort
#: the whole run rather than mapping onto an entry here.
_VAMP_STATUS_TO_IDENTITY = {
    "CROSSWALK_SPDI_VERIFIED": ("GENOMIC_SPDI_VERIFIED", None),
    "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": (
        "GENOMIC_CROSSWALK_LENGTH_MISMATCH",
        "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT",
    ),
    "ARCHIVE_CROSSWALK_ABSENT": ("PROTEIN_ONLY_ARCHIVE_CROSSWALK_ABSENT", "PROTEIN_VARIANT_NOT_IN_ARCHIVE"),
}

#: Status this join is pinned to see zero occurrences of (spec
#: ``join_rules.vamp.status_mapping.SOURCE_COORDINATE_REFERENCE_MISMATCH``).
_VAMP_REFERENCE_MISMATCH_STATUS = "SOURCE_COORDINATE_REFERENCE_MISMATCH"

_SUCCESS_MAPPING_STATUS = "PROJECTED_FASTA_VERIFIED"


class InputPinMismatchError(RuntimeError):
    """Raised when an input bundle manifest's recomputed content hash, its
    ``bundle_id``, or a pinned artifact record's ``relative_path``/
    ``sha256``/``byte_length``/``row_count`` does not match this slice's
    exact pinned expectation (or is otherwise ambiguous -- e.g. more or
    fewer than exactly one matching artifact_id), or when a pinned
    artifact's actual on-disk bytes/path violate this slice's read-time
    integrity or path-safety requirements."""


class PromotionJoinError(RuntimeError):
    """Raised for any row-schema revalidation failure, duplicate or
    non-contiguous ``source_row`` sequence, cliPE/VAMP join mismatch
    (wrong ``source_record_id``/``protein_variant``/``hgvs_c``, a cliPE
    mapping status other than ``PROJECTED_FASTA_VERIFIED``, or a VAMP
    crosswalk ``SOURCE_COORDINATE_REFERENCE_MISMATCH``/unknown status),
    or any input/output row-count conservation violation."""


class PromotionInvariantError(RuntimeError):
    """Raised for an internal cross-check failure that should never occur
    given the other validations in this module having already passed
    (e.g. an output row count that does not equal the input row count
    after every row was individually accounted for) -- a defensive,
    fail-closed safety net rather than a normally-reachable error path."""


def _compute_manifest_content_hash(manifest: dict[str, Any]) -> str:
    """SHA-256 of the manifest's UTF-8 canonical JSON (sorted object keys,
    ``(",", ":")`` separators, array order preserved), excluding ONLY the
    top-level ``content_hash`` key itself. Identical algorithm to every
    other bundle module in this repository (``tsc2_sources.bundle``,
    ``tsc2_functional.bundle``, ``tsc2_cdna_projector.bundle``,
    ``tsc2_vamp_crosswalk.bundle``) -- reimplemented here (rather than
    imported from one arbitrary sibling) only because this function must
    validate manifests from all three of those distinct schemas."""
    basis = {key: value for key, value in manifest.items() if key != "content_hash"}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _verify_manifest_hash(manifest: Any, expected_hash: str, *, label: str) -> str:
    if not isinstance(manifest, dict):
        raise InputPinMismatchError(f"{label}: manifest must be a mapping")
    recomputed = _compute_manifest_content_hash(manifest)
    recorded = manifest.get("content_hash")
    if recomputed != recorded:
        raise InputPinMismatchError(
            f"{label}: manifest content_hash is not internally consistent: recorded {recorded!r} "
            f"!= recomputed {recomputed!r}"
        )
    if recomputed != expected_hash:
        raise InputPinMismatchError(
            f"{label}: manifest content_hash {recomputed!r} does not match the pinned expectation "
            f"{expected_hash!r}"
        )
    return recomputed


def _select_single_artifact(artifacts: Any, *, artifact_id: str, label: str) -> dict[str, Any]:
    if not isinstance(artifacts, list):
        raise InputPinMismatchError(f"{label}: manifest artifacts must be a list")
    matches = [
        artifact for artifact in artifacts if isinstance(artifact, dict) and artifact.get("artifact_id") == artifact_id
    ]
    if len(matches) != 1:
        raise InputPinMismatchError(
            f"{label}: expected exactly one artifact with artifact_id {artifact_id!r}, found "
            f"{len(matches)}"
        )
    return matches[0]


def _verify_and_select_artifact(artifacts: Any, *, expected: dict[str, Any], label: str) -> dict[str, Any]:
    actual = _select_single_artifact(artifacts, artifact_id=expected["artifact_id"], label=label)
    for field_name in ("relative_path", "sha256", "byte_length", "row_count"):
        if actual.get(field_name) != expected[field_name]:
            raise InputPinMismatchError(
                f"{label}: artifact field {field_name!r} does not match the pinned expectation: "
                f"{actual.get(field_name)!r} != {expected[field_name]!r}"
            )
    return {
        "artifact_id": actual["artifact_id"],
        "relative_path": actual["relative_path"],
        "sha256": actual["sha256"],
        "byte_length": actual["byte_length"],
        "row_count": actual["row_count"],
    }


def validate_input_bundle_manifests(
    *,
    functional_normalization_manifest: dict[str, Any],
    clipe_projector_manifest: dict[str, Any],
    vamp_crosswalk_manifest: dict[str, Any],
    expected_pins: dict[str, Any],
) -> dict[str, Any]:
    """Re-verify all three input bundle manifests against ``expected_pins``
    (the exact structure this slice's config/spec pins: a
    ``manifest_content_hash``/``bundle_id``/``run_name`` per bundle plus
    each bundle's pinned artifact record(s)) and return the selected,
    verified pin data (``run_name``/``bundle_id``/``manifest_content_hash``
    plus the matched artifact record(s)) for
    ``read_pinned_artifact_payloads`` to use. Raises
    ``InputPinMismatchError`` on any hash/bundle_id/artifact-field
    mismatch, or if any manifest does not contain EXACTLY one artifact
    matching a pinned ``artifact_id``."""
    fn_expected = expected_pins["functional_normalization_bundle"]
    cp_expected = expected_pins["clipe_projector_bundle"]
    vx_expected = expected_pins["vamp_crosswalk_bundle"]

    fn_hash = _verify_manifest_hash(
        functional_normalization_manifest, fn_expected["manifest_content_hash"],
        label="functional_normalization_bundle",
    )
    if functional_normalization_manifest.get("bundle_id") != fn_expected["bundle_id"]:
        raise InputPinMismatchError(
            "functional_normalization_bundle: bundle_id "
            f"{functional_normalization_manifest.get('bundle_id')!r} does not match the pinned "
            f"expectation {fn_expected['bundle_id']!r}"
        )
    fn_artifacts_out = {
        key: _verify_and_select_artifact(
            functional_normalization_manifest.get("artifacts"),
            expected=artifact_expected,
            label=f"functional_normalization_bundle.artifacts.{key}",
        )
        for key, artifact_expected in fn_expected["artifacts"].items()
    }

    cp_hash = _verify_manifest_hash(
        clipe_projector_manifest, cp_expected["manifest_content_hash"], label="clipe_projector_bundle",
    )
    if clipe_projector_manifest.get("bundle_id") != cp_expected["bundle_id"]:
        raise InputPinMismatchError(
            f"clipe_projector_bundle: bundle_id {clipe_projector_manifest.get('bundle_id')!r} does "
            f"not match the pinned expectation {cp_expected['bundle_id']!r}"
        )
    cp_mapping_out = _verify_and_select_artifact(
        clipe_projector_manifest.get("artifacts"),
        expected=cp_expected["mapping"],
        label="clipe_projector_bundle.mapping",
    )

    vx_hash = _verify_manifest_hash(
        vamp_crosswalk_manifest, vx_expected["manifest_content_hash"], label="vamp_crosswalk_bundle",
    )
    if vamp_crosswalk_manifest.get("bundle_id") != vx_expected["bundle_id"]:
        raise InputPinMismatchError(
            f"vamp_crosswalk_bundle: bundle_id {vamp_crosswalk_manifest.get('bundle_id')!r} does not "
            f"match the pinned expectation {vx_expected['bundle_id']!r}"
        )
    vx_crosswalk_out = _verify_and_select_artifact(
        vamp_crosswalk_manifest.get("artifacts"),
        expected=vx_expected["crosswalk"],
        label="vamp_crosswalk_bundle.crosswalk",
    )

    return {
        "functional_normalization_bundle": {
            "run_name": fn_expected["run_name"],
            "bundle_id": fn_expected["bundle_id"],
            "manifest_content_hash": fn_hash,
            "artifacts": fn_artifacts_out,
        },
        "clipe_projector_bundle": {
            "run_name": cp_expected["run_name"],
            "bundle_id": cp_expected["bundle_id"],
            "manifest_content_hash": cp_hash,
            "mapping": cp_mapping_out,
        },
        "vamp_crosswalk_bundle": {
            "run_name": vx_expected["run_name"],
            "bundle_id": vx_expected["bundle_id"],
            "manifest_content_hash": vx_hash,
            "crosswalk": vx_crosswalk_out,
        },
    }


def _validate_relative_path_safe(relative_path: Any, *, label: str) -> None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise InputPinMismatchError(f"{label}: relative_path must be a non-blank string")
    if "\x00" in relative_path:
        raise InputPinMismatchError(f"{label}: relative_path must not contain a NUL byte")
    if "\\" in relative_path:
        raise InputPinMismatchError(
            f"{label}: relative_path must use forward-slash separators only, got {relative_path!r}"
        )
    if PureWindowsPath(relative_path).drive or PurePosixPath(relative_path).is_absolute():
        raise InputPinMismatchError(f"{label}: relative_path must not be absolute: {relative_path!r}")
    parts = PurePosixPath(relative_path).parts
    if not parts or any(part in (".", "..") for part in parts):
        raise InputPinMismatchError(
            f"{label}: relative_path must not contain traversal components: {relative_path!r}"
        )


def _is_symlink_or_reparse_point(path: Path) -> bool:
    """True iff ``path`` is a POSIX symlink, a Windows junction, or
    otherwise carries ``FILE_ATTRIBUTE_REPARSE_POINT`` -- checked via
    lstat-style calls that never follow the link. A missing path is
    ``False``; any other OS-level inspection failure becomes
    ``InputPinMismatchError`` instead of a raw ``OSError``."""
    try:
        if path.is_symlink():
            return True
        isjunction = getattr(os.path, "isjunction", None)
        if isjunction is not None and isjunction(path):
            return True
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise InputPinMismatchError(f"unable to inspect {path} for a symlink/reparse point: {exc}") from exc
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", None)
    file_attributes = getattr(st, "st_file_attributes", None)
    return bool(file_attributes is not None and reparse_attribute is not None and file_attributes & reparse_attribute)


def _validate_no_symlink_components(root: Path, run_name: str, relative_path: str, *, label: str) -> Path:
    """Reject a symlink/reparse point anywhere from the filesystem anchor
    down to the artifact leaf, walking lexically (never ``resolve()``)
    so an aliased *ancestor* of a caller-supplied ``root`` can't hide
    behind ``root`` itself not being a symlink. A relative ``root`` is
    anchored at ``cwd`` by lexical join only. Every cumulative component
    -- the anchor, each of ``root``'s own directories, ``run_name``, and
    each ``relative_path`` segment -- is checked with
    ``_is_symlink_or_reparse_point`` before any ``resolve()``/open, and a
    same-directory symlink is rejected exactly like an escaping one."""
    root = Path(root)
    if not root.is_absolute():
        root = Path.cwd() / root
    current = Path(root.anchor)
    if _is_symlink_or_reparse_point(current):
        raise InputPinMismatchError(f"{label}: {current} is a symlink/reparse point; refusing for safety")
    for part in (*root.parts[1:], run_name, *PurePosixPath(relative_path).parts):
        current = current / part
        if _is_symlink_or_reparse_point(current):
            raise InputPinMismatchError(
                f"{label}: path component {current} is a symlink/reparse point; refusing to read "
                "through a symlink even when its target remains inside the run directory"
            )
    return current


def _read_pinned_artifact(*, root: Path | str, run_name: str, artifact: dict[str, Any], label: str) -> bytes:
    try:
        _validate_run_name(run_name)
    except _SourceBundleBoundaryError as exc:
        raise InputPinMismatchError(f"{label}: {exc}") from exc

    relative_path = artifact["relative_path"]
    _validate_relative_path_safe(relative_path, label=label)

    run_dir = Path(root) / run_name
    artifact_path = _validate_no_symlink_components(Path(root), run_name, relative_path, label=label)

    # Containment is structurally guaranteed once every component is
    # confirmed real (no ".."/absolute components are permitted by
    # ``_validate_relative_path_safe`` and no symlink can redirect the
    # walk) -- this resolve()+relative_to() is preserved as a defense-in-
    # depth containment check, never the FIRST safety check performed.
    try:
        resolved_artifact_path = artifact_path.resolve()
        resolved_run_dir = run_dir.resolve()
        resolved_artifact_path.relative_to(resolved_run_dir)
    except ValueError as exc:
        raise InputPinMismatchError(f"{label}: artifact path escapes its run directory {run_dir}") from exc

    if _is_symlink_or_reparse_point(artifact_path) or not artifact_path.is_file():
        raise InputPinMismatchError(f"{label}: pinned artifact not found at a trusted path {artifact_path}")

    payload = artifact_path.read_bytes()
    if len(payload) != artifact["byte_length"]:
        raise InputPinMismatchError(
            f"{label}: byte_length mismatch: expected {artifact['byte_length']!r}, observed "
            f"{len(payload)!r}"
        )
    observed_sha256 = hashlib.sha256(payload).hexdigest()
    if observed_sha256.lower() != str(artifact["sha256"]).lower():
        raise InputPinMismatchError(
            f"{label}: sha256 mismatch: expected {artifact['sha256']!r}, observed {observed_sha256!r}"
        )
    return payload


def read_pinned_artifact_payloads(
    *,
    functional_normalization_root: Path | str,
    clipe_projector_root: Path | str,
    vamp_crosswalk_root: Path | str,
    validated_inputs: dict[str, Any],
) -> dict[str, Any]:
    """Read and re-verify (byte_length + sha256) every pinned artifact's
    actual bytes from ``<root>/<run_name>/<relative_path>`` -- a trusted
    path this function independently re-validates for safety (no
    absolute/backslash/traversal component, and the resolved real path
    must stay within ``<root>/<run_name>``, so neither an escaping
    relative path nor a symlinked leaf/ancestor is ever followed). Raises
    ``InputPinMismatchError`` on any path-safety, missing-file, or hash/
    length mismatch."""
    fn = validated_inputs["functional_normalization_bundle"]
    cp = validated_inputs["clipe_projector_bundle"]
    vx = validated_inputs["vamp_crosswalk_bundle"]

    functional_payloads = {
        key: _read_pinned_artifact(
            root=functional_normalization_root,
            run_name=fn["run_name"],
            artifact=artifact,
            label=f"functional_normalization_bundle.artifacts.{key}",
        )
        for key, artifact in fn["artifacts"].items()
    }
    clipe_projector_mapping = _read_pinned_artifact(
        root=clipe_projector_root,
        run_name=cp["run_name"],
        artifact=cp["mapping"],
        label="clipe_projector_bundle.mapping",
    )
    vamp_crosswalk = _read_pinned_artifact(
        root=vamp_crosswalk_root,
        run_name=vx["run_name"],
        artifact=vx["crosswalk"],
        label="vamp_crosswalk_bundle.crosswalk",
    )

    return {
        "functional_normalization": functional_payloads,
        "clipe_projector_mapping": clipe_projector_mapping,
        "vamp_crosswalk": vamp_crosswalk,
    }


def _revalidate_functional_row(row: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != REQUIRED_ROW_FIELDS:
        raise PromotionJoinError(f"{label}: functional row does not have the exact required fields")
    try:
        return NormalizedFunctionalRow(**row).to_dict()
    except NormalizationContractError as exc:
        raise PromotionJoinError(f"{label}: functional row failed contract revalidation: {exc}") from exc


def _revalidate_mapping_row(row: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != REQUIRED_MAPPING_ROW_FIELDS:
        raise PromotionJoinError(f"{label}: cliPE mapping row does not have the exact required fields")
    try:
        return ClipeCdnaSpdiMappingRow(**row).to_dict()
    except ProjectionContractError as exc:
        raise PromotionJoinError(f"{label}: cliPE mapping row failed contract revalidation: {exc}") from exc


def _revalidate_crosswalk_row(row: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != REQUIRED_CROSSWALK_ROW_FIELDS:
        raise PromotionJoinError(f"{label}: VAMP crosswalk row does not have the exact required fields")
    try:
        return VampGenomicCrosswalkRow(**row).to_dict()
    except CrosswalkContractError as exc:
        raise PromotionJoinError(f"{label}: VAMP crosswalk row failed contract revalidation: {exc}") from exc


def _require_contiguous_unique_source_rows(rows: list[dict[str, Any]], *, label: str) -> None:
    seen: set[int] = set()
    for row in rows:
        source_row = row["source_row"]
        if source_row in seen:
            raise PromotionJoinError(f"{label}: duplicate source_row {source_row!r}")
        seen.add(source_row)
    if sorted(seen) != list(range(1, len(seen) + 1)):
        raise PromotionJoinError(
            f"{label}: source_row values must be contiguous 1..N, got {sorted(seen)!r}"
        )


def promote_functional_identities(
    *,
    functional_rows: list[dict[str, Any]],
    clipe_mapping_rows: list[dict[str, Any]],
    vamp_crosswalk_rows: list[dict[str, Any]],
    expected_source_rows: dict[str, int],
    transcript: str,
    genomic_accession: str,
    assembly: str,
) -> dict[str, Any]:
    """Fully revalidate every functional/mapping/crosswalk row against its
    exact schema, join cliPE mapping rows and VAMP crosswalk rows onto
    their functional row and promote resolved identities, and copy every
    SGE row through byte-identically. Every input row is conserved (never
    dropped); any schema/join/conservation violation raises
    ``PromotionJoinError`` for the WHOLE call rather than skipping a
    single bad row."""
    if set(expected_source_rows) != set(_SOURCE_IDS):
        raise PromotionJoinError(
            f"expected_source_rows must have exactly the keys {sorted(_SOURCE_IDS)!r}, got "
            f"{sorted(expected_source_rows)!r}"
        )

    total_input_rows = len(functional_rows)

    revalidated_functional = [
        _revalidate_functional_row(row, label=f"functional_rows[{index}]")
        for index, row in enumerate(functional_rows)
    ]
    revalidated_mapping = [
        _revalidate_mapping_row(row, label=f"clipe_mapping_rows[{index}]")
        for index, row in enumerate(clipe_mapping_rows)
    ]
    revalidated_crosswalk = [
        _revalidate_crosswalk_row(row, label=f"vamp_crosswalk_rows[{index}]")
        for index, row in enumerate(vamp_crosswalk_rows)
    ]

    by_source: dict[str, list[dict[str, Any]]] = {source_id: [] for source_id in _SOURCE_IDS}
    global_seen_keys: set[tuple[str, int]] = set()
    for row in revalidated_functional:
        source_id = row["source_id"]
        if source_id not in by_source:
            raise PromotionJoinError(f"functional row has unexpected source_id {source_id!r}")
        key = (source_id, row["source_row"])
        if key in global_seen_keys:
            raise PromotionJoinError(f"duplicate (source_id, source_row) key {key!r} in functional_rows")
        global_seen_keys.add(key)
        by_source[source_id].append(row)

    for source_id in _SOURCE_IDS:
        _require_contiguous_unique_source_rows(by_source[source_id], label=f"functional_rows[{source_id}]")
        if len(by_source[source_id]) != expected_source_rows[source_id]:
            raise PromotionJoinError(
                f"functional_rows[{source_id}]: expected {expected_source_rows[source_id]!r} rows, "
                f"found {len(by_source[source_id])!r}"
            )

    _require_contiguous_unique_source_rows(revalidated_mapping, label="clipe_mapping_rows")
    if len(revalidated_mapping) != expected_source_rows["mavedb_clipe"]:
        raise PromotionJoinError(
            f"clipe_mapping_rows: expected {expected_source_rows['mavedb_clipe']!r} rows, found "
            f"{len(revalidated_mapping)!r}"
        )
    _require_contiguous_unique_source_rows(revalidated_crosswalk, label="vamp_crosswalk_rows")
    if len(revalidated_crosswalk) != expected_source_rows["igvf_vamp_seq"]:
        raise PromotionJoinError(
            f"vamp_crosswalk_rows: expected {expected_source_rows['igvf_vamp_seq']!r} rows, found "
            f"{len(revalidated_crosswalk)!r}"
        )

    clipe_by_row = {row["source_row"]: row for row in revalidated_mapping}
    promoted_clipe: list[dict[str, Any]] = []
    for functional_row in by_source["mavedb_clipe"]:
        mapping_row = clipe_by_row[functional_row["source_row"]]
        if mapping_row["source_record_id"] != functional_row["source_record_id"]:
            raise PromotionJoinError(
                f"cliPE join mismatch at source_row {functional_row['source_row']!r}: mapping "
                f"source_record_id {mapping_row['source_record_id']!r} != functional row "
                f"source_record_id {functional_row['source_record_id']!r}"
            )
        if mapping_row["hgvs_c"] != functional_row["hgvs_c"]:
            raise PromotionJoinError(
                f"cliPE join mismatch at source_row {functional_row['source_row']!r}: mapping hgvs_c "
                f"{mapping_row['hgvs_c']!r} != functional row hgvs_c {functional_row['hgvs_c']!r}"
            )
        if mapping_row["status"] != _SUCCESS_MAPPING_STATUS:
            raise PromotionJoinError(
                f"cliPE mapping row at source_row {functional_row['source_row']!r} has status "
                f"{mapping_row['status']!r}, expected {_SUCCESS_MAPPING_STATUS!r}"
            )
        try:
            hgvs_g = spdi_to_hgvs_g(mapping_row["genomic_spdi"])
        except PromotionModelError as exc:
            raise PromotionJoinError(
                f"cliPE mapping row at source_row {functional_row['source_row']!r}: failed to derive "
                f"hgvs_g from genomic_spdi {mapping_row['genomic_spdi']!r}: {exc}"
            ) from exc
        promoted = dict(functional_row)
        promoted.update(
            {
                "assembly": assembly,
                "transcript": transcript,
                "spdi": mapping_row["genomic_spdi"],
                "hgvs_g": hgvs_g,
                "identity_state": "GENOMIC_SPDI_VERIFIED",
                "unresolved_reason": None,
            }
        )
        promoted_clipe.append(_revalidate_functional_row(promoted, label=f"promoted mavedb_clipe row {functional_row['source_row']!r}"))

    crosswalk_by_row = {row["source_row"]: row for row in revalidated_crosswalk}
    promoted_vamp: list[dict[str, Any]] = []
    for functional_row in by_source["igvf_vamp_seq"]:
        crosswalk_row = crosswalk_by_row[functional_row["source_row"]]
        expected_protein_variant = f"{functional_row['protein_accession']}:{functional_row['hgvs_p']}"
        if crosswalk_row["protein_variant"] != expected_protein_variant:
            raise PromotionJoinError(
                f"VAMP join mismatch at source_row {functional_row['source_row']!r}: crosswalk "
                f"protein_variant {crosswalk_row['protein_variant']!r} != functional row token "
                f"{expected_protein_variant!r}"
            )
        status = crosswalk_row["status"]
        if status == _VAMP_REFERENCE_MISMATCH_STATUS:
            raise PromotionJoinError(
                f"VAMP crosswalk row at source_row {functional_row['source_row']!r} has status "
                f"{_VAMP_REFERENCE_MISMATCH_STATUS!r}, which this promotion run is pinned to see zero "
                "occurrences of"
            )
        if status not in _VAMP_STATUS_TO_IDENTITY:
            raise PromotionJoinError(
                f"VAMP crosswalk row at source_row {functional_row['source_row']!r} has unknown "
                f"status {status!r}"
            )
        identity_state, unresolved_reason = _VAMP_STATUS_TO_IDENTITY[status]
        promoted = dict(functional_row)
        if status == "CROSSWALK_SPDI_VERIFIED":
            hgvs_c = f"{transcript}:{crosswalk_row['hgvs_c']}"
            try:
                hgvs_g = spdi_to_hgvs_g(crosswalk_row["genomic_spdi"])
            except PromotionModelError as exc:
                raise PromotionJoinError(
                    f"VAMP crosswalk row at source_row {functional_row['source_row']!r}: failed to "
                    f"derive hgvs_g from genomic_spdi {crosswalk_row['genomic_spdi']!r}: {exc}"
                ) from exc
            promoted.update(
                {
                    "assembly": assembly,
                    "transcript": transcript,
                    "hgvs_c": hgvs_c,
                    "spdi": crosswalk_row["genomic_spdi"],
                    "hgvs_g": hgvs_g,
                    "identity_state": identity_state,
                    "unresolved_reason": unresolved_reason,
                }
            )
        elif status == "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH":
            hgvs_c = f"{transcript}:{crosswalk_row['hgvs_c']}"
            promoted.update(
                {
                    "assembly": None,
                    "transcript": transcript,
                    "hgvs_c": hgvs_c,
                    "spdi": None,
                    "hgvs_g": None,
                    "identity_state": identity_state,
                    "unresolved_reason": unresolved_reason,
                }
            )
        else:  # ARCHIVE_CROSSWALK_ABSENT
            promoted.update(
                {
                    "assembly": None,
                    "transcript": None,
                    "hgvs_c": None,
                    "spdi": None,
                    "hgvs_g": None,
                    "identity_state": identity_state,
                    "unresolved_reason": unresolved_reason,
                }
            )
        promoted_vamp.append(_revalidate_functional_row(promoted, label=f"promoted igvf_vamp_seq row {functional_row['source_row']!r}"))

    promoted_sge = [
        _revalidate_functional_row(dict(row), label=f"promoted igvf_sge row {row['source_row']!r}")
        for row in by_source["igvf_sge"]
    ]
    for original, promoted in zip(by_source["igvf_sge"], promoted_sge):
        if original != promoted:
            raise PromotionInvariantError(
                f"igvf_sge row {original['source_row']!r} was not copied byte-identically at the "
                "semantic field level"
            )

    promoted_rows = promoted_clipe + promoted_vamp + promoted_sge
    output_rows = len(promoted_rows)
    input_rows = len(revalidated_functional)
    if output_rows != input_rows:
        raise PromotionInvariantError(
            f"output row count {output_rows!r} does not equal input row count {input_rows!r}"
        )

    return {
        "promoted_rows": promoted_rows,
        "counts": {
            "input_rows": total_input_rows,
            "output_rows": output_rows,
            "dropped_rows": 0,
        },
    }


#: Every unordered pair of the three verified-identity sources, using the
#: exact pairwise key naming this slice's config/spec pins.
_OVERLAP_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("mavedb_clipe", "igvf_sge", "mavedb_clipe__igvf_sge"),
    ("igvf_vamp_seq", "igvf_sge", "igvf_vamp_seq__igvf_sge"),
    ("mavedb_clipe", "igvf_vamp_seq", "mavedb_clipe__igvf_vamp_seq"),
)


def compute_verified_spdi_overlap(*, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute deterministic (row-order independent) verified-observation,
    unique-SPDI and pairwise/triple cross-source overlap counts from
    ``rows`` (any list of already-promoted rows -- only rows with
    ``identity_state == "GENOMIC_SPDI_VERIFIED"`` are counted)."""
    spdi_sets: dict[str, set[str]] = {source_id: set() for source_id in _SOURCE_IDS}
    observations_by_source: dict[str, int] = {source_id: 0 for source_id in _SOURCE_IDS}
    all_spdi: list[str] = []

    for row in rows:
        if row.get("identity_state") != "GENOMIC_SPDI_VERIFIED":
            continue
        source_id = row["source_id"]
        spdi = row["spdi"]
        observations_by_source[source_id] = observations_by_source.get(source_id, 0) + 1
        spdi_sets.setdefault(source_id, set()).add(spdi)
        all_spdi.append(spdi)

    verified_observations = sum(observations_by_source.values())
    verified_unique_spdi = len(set(all_spdi))
    duplicate_verified_observations = verified_observations - verified_unique_spdi

    pairwise = {
        key: len(spdi_sets.get(source_a, set()) & spdi_sets.get(source_b, set()))
        for source_a, source_b, key in _OVERLAP_PAIRS
    }
    triple = len(spdi_sets.get("mavedb_clipe", set()) & spdi_sets.get("igvf_vamp_seq", set()) & spdi_sets.get("igvf_sge", set()))

    return {
        "verified_observations_by_source": observations_by_source,
        "verified_observations": verified_observations,
        "verified_unique_spdi": verified_unique_spdi,
        "duplicate_verified_observations": duplicate_verified_observations,
        "source_overlap": {"pairwise": pairwise, "triple": triple},
    }


__all__ = [
    "InputPinMismatchError",
    "PromotionJoinError",
    "PromotionInvariantError",
    "validate_input_bundle_manifests",
    "read_pinned_artifact_payloads",
    "promote_functional_identities",
    "compute_verified_spdi_overlap",
]
