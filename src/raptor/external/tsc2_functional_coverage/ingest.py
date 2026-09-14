"""RAPTOR v2 TSC2 functional coverage map -- frozen-input validation,
raw-byte pinning and path safety for every one of this slice's seven
external input roots (functional promotion, VUS identity/BIAS, priority
queue, prospective holdout, Atlas identity map/panel, Atlas anchor).

``validate_input_roots_absolute`` rejects any relative input/output root
BEFORE any reader is ever invoked (FC-01): every root this slice reads
from must be an explicit, absolute path -- there is no
current-working-directory fallback for any of them.

``read_input_payload`` is the single, path-safety-hardened raw-byte
reader every other validator in this module (and the operator script)
uses to read a pinned artifact's actual bytes from
``<root>/<run_name>/<relative_path>``: it independently re-verifies the
run_name/relative_path shape, walks every filesystem-anchor-to-leaf path
component with the monkeypatchable ``_is_symlink_or_reparse_point``
predicate (POSIX symlink, Windows junction, or a raw
``FILE_ATTRIBUTE_REPARSE_POINT`` -- never merely ``Path.is_symlink()``)
before any ``resolve()``/open, and re-verifies the actual bytes'
length/sha256 against the caller's pinned expectation. A caller may
inject already-read bytes via ``payload_override`` (still hash/length
re-verified) to decouple a raw-byte-pinning test from the filesystem.

``validate_functional_promotion_manifest`` re-verifies the already-
published functional-identity-promotion bundle manifest's own canonical
content hash, ``bundle_id`` and per-source artifact records (byte_length/
sha256/row_count/relative_path, plus each artifact's ``source_id`` field)
against this slice's exact pinned expectations -- BEFORE any artifact
payload is read.

``validate_promoted_functional_rows`` fully reconstructs every promoted
row through the existing ``raptor.external.tsc2_functional.model.
NormalizedFunctionalRow`` (never a reimplementation of that schema),
rejects a duplicate ``(source_id, source_row)`` key, an unknown
``source_id``, any identity_state other than the pinned
``required_identity_state``, and any source-row-count drift.

``validate_vus_inputs``/``validate_prospective_holdout_inputs`` byte-pin
and schema-validate the frozen VUS/holdout manifests -- raw bytes are
hash/length verified BEFORE any JSON/JSONL parse, every manifest identity
(``variant_id``) and BIAS join key (``vcf_key``) must be duplicate-free,
and ``acmgClassification``/any labeled/adjudication field is never read
for either cohort.

``reproduce_priority_subset`` reproduces the internal, non-authoritative
VUS priority subset through the existing disabled/manual census seam
(``raptor.census.strata.reproduce_census_strata``, using
``raptor.scorer.bias_source.BiasTsvSource``/``raptor.scorer.config``/
``raptor.eval.config`` for real operation) and requires the frozen
external priority queue's canonical-SPDI set to equal the reproduced
subset exactly. Callers may inject ``reproduce_census_strata_fn`` to
decouple pure-Python join/pin tests from the real BIAS/eval/scorer stack.

``load_atlas_contrast_replays`` calls only the public
``raptor.atlas.identity_map.load_identity_map``/``raptor.atlas.pack.
load_disease_pack`` seams (never reimplementing their hash/lock/pack-
binding verification) and replays EVERY raw inventory row through the
returned offline mapper, preserving resolved/unresolved records exactly
and never joining an unresolved identity.

``validate_atlas_anchor_input`` reads only the pinned $R611Q$ Atlas gate
result's nested ``variant.spdi`` as identity context; the anchor's own
Gate-8/accepted-claim-count boundary fields are re-verified but never
promoted into a claim.

This module performs no network I/O. Its only cross-domain seams are
``raptor.census.strata``, ``raptor.scorer.bias_source``,
``raptor.scorer.config``, ``raptor.eval.config``,
``raptor.atlas.identity_map`` and ``raptor.atlas.pack`` -- it never
imports ``raptor.packet``, ``raptor.kb`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

import yaml

from raptor.external.tsc2_functional.model import (
    NormalizationContractError,
    NormalizedFunctionalRow,
)
from raptor.external.tsc2_sources.bundle import BundleBoundaryError as _SourceBundleBoundaryError
from raptor.external.tsc2_sources.bundle import _validate_run_name

from .model import SOURCE_ORDER

_TSC1_ACCESSION = "NC_000009.12"
_TSC2_ACCESSION = "NC_000016.10"
_ACCESSION_TO_GENE = {_TSC1_ACCESSION: "TSC1", _TSC2_ACCESSION: "TSC2"}
_ACCESSION_TO_CONTIG = {_TSC1_ACCESSION: "chr9", _TSC2_ACCESSION: "chr16"}

#: A canonical SPDI identity string: ``<accession>:<position0>:<deleted>:
#: <inserted>``. Real ClinVar-derived VUS/holdout/priority-queue identity
#: rows legitimately include pure insertions (empty ``deleted``) and pure
#: deletions (empty ``inserted``) -- unlike the stricter, always-non-empty
#: ``FunctionalCoverageRow.spdi`` contract (``model._SPDI_RE``), which
#: only ever carries an already-verified functional SNV/delins.
_VARIANT_ID_RE = re.compile(r"^(?P<accession>NC_000009\.12|NC_000016\.10):(?P<position>[0-9]+):(?P<ref>[ACGT]*):(?P<alt>[ACGT]*)$")
_VCF_KEY_RE = re.compile(r"^(?P<contig>[^:]+):(?P<position>[0-9]+):(?P<ref>[ACGT]*):(?P<alt>[ACGT]*)$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_REQUIRED_MANIFEST_ROW_FIELDS = frozenset({"accession", "contig", "variant_id", "vcf_key"})

_REQUIRED_PREDICTOR_POLICY = {
    "schema": "bp4pp3-predictor-policy/2",
    "status": "approved",
    "mode": "disabled_manual",
}

#: Default priority-queue row field set/review_state/gate_status (spec
#: ``inputs.priority_subset_policy.queue``) -- used whenever a caller's
#: ``queue_pin`` omits these (otherwise identical, universally pinned)
#: values rather than re-pinning them redundantly.
_DEFAULT_QUEUE_EXACT_FIELDS = (
    "packet_id",
    "evidence_core_hash",
    "canonical_spdi",
    "gene",
    "review_state",
    "gate_status",
    "quality_flags",
    "contradiction",
)


class CoverageInputError(RuntimeError):
    """Base error for every frozen-input validation failure in this
    module: a byte-hash/length mismatch, a schema/field-set violation, a
    duplicate identity/join key, a forbidden labeled-artifact field, an
    input-root that is not absolute, or an Atlas replay/anchor boundary
    violation. Every other validator's failure mode in this module is
    either this class directly or (for a pinned-manifest self-hash/
    artifact-record mismatch specifically) its ``InputPinMismatchError``
    subclass."""


class InputPinMismatchError(CoverageInputError):
    """Raised when a pinned manifest/artifact's recomputed content hash,
    ``bundle_id``, ``source_id``, or any pinned field (``relative_path``/
    ``sha256``/``byte_length``/``row_count``) does not match this slice's
    exact pinned expectation, or when a pinned artifact's actual on-disk
    (or injected) bytes/path violate this slice's read-time integrity or
    path-safety requirements."""


def validate_input_roots_absolute(
    *,
    functional_promotion_root: Path | str,
    vus_identity_root: Path | str,
    vus_bias_root: Path | str,
    priority_queue_root: Path | str,
    prospective_holdout_root: Path | str,
    atlas_identity_map_root: Path | str,
    atlas_panel_root: Path | str,
    output_root: Path | str | None = None,
    reader_probe_fn: Callable[..., Any] | None = None,
) -> None:
    """Raise ``CoverageInputError`` unless EVERY supplied root is an
    absolute path. This check is performed before any of this module's
    readers are ever invoked -- a relative root is rejected here,
    unconditionally, with no fallback to the current working directory.
    ``reader_probe_fn`` (if supplied) is accepted only for callers that
    wish to assert it is never invoked; this function itself never calls
    it."""
    del reader_probe_fn
    roots: dict[str, Path | str] = {
        "functional_promotion_root": functional_promotion_root,
        "vus_identity_root": vus_identity_root,
        "vus_bias_root": vus_bias_root,
        "priority_queue_root": priority_queue_root,
        "prospective_holdout_root": prospective_holdout_root,
        "atlas_identity_map_root": atlas_identity_map_root,
        "atlas_panel_root": atlas_panel_root,
    }
    if output_root is not None:
        roots["output_root"] = output_root
    for name, value in roots.items():
        if not Path(value).is_absolute():
            raise CoverageInputError(f"{name} must be an absolute path, got {value!r}")


# ---------------------------------------------------------------------------
# Path safety: monkeypatchable symlink/reparse-point predicate + raw-byte
# pinned reader.
# ---------------------------------------------------------------------------


def _is_symlink_or_reparse_point(path: Path) -> bool:
    """True iff ``path`` is a POSIX symlink, a Windows junction, or
    otherwise carries ``FILE_ATTRIBUTE_REPARSE_POINT`` -- checked via
    lstat-style calls that never follow the link. A missing path is
    ``False``; any other OS-level inspection failure becomes
    ``CoverageInputError`` instead of a raw ``OSError``. Exposed at
    module scope (and never called through an indirection) so tests can
    monkeypatch it directly."""
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
        raise CoverageInputError(f"unable to inspect {path} for a symlink/reparse point: {exc}") from exc
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", None)
    file_attributes = getattr(st, "st_file_attributes", None)
    return bool(file_attributes is not None and reparse_attribute is not None and file_attributes & reparse_attribute)


def _validate_relative_path_safe(relative_path: Any, *, label: str) -> None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise CoverageInputError(f"{label}: relative_path must be a non-blank string")
    if "\x00" in relative_path:
        raise CoverageInputError(f"{label}: relative_path must not contain a NUL byte")
    if "\\" in relative_path:
        raise CoverageInputError(f"{label}: relative_path must use forward-slash separators only: {relative_path!r}")
    if PureWindowsPath(relative_path).drive or PurePosixPath(relative_path).is_absolute():
        raise CoverageInputError(f"{label}: relative_path must not be absolute: {relative_path!r}")
    parts = PurePosixPath(relative_path).parts
    if not parts or any(part in (".", "..") for part in parts):
        raise CoverageInputError(f"{label}: relative_path must not contain traversal components: {relative_path!r}")


def _validate_no_symlink_components(root: Path, run_name: str | None, relative_path: str, *, label: str) -> Path:
    """Reject a symlink/reparse point anywhere from the filesystem anchor
    down to the artifact leaf, walking lexically (never ``resolve()``)
    so an aliased ancestor of a caller-supplied ``root`` can't hide
    behind ``root`` itself not being a symlink. When ``run_name`` is
    ``None`` the artifact is addressed directly as ``root/relative_path``
    (no intervening run directory segment)."""
    root = Path(root)
    if not root.is_absolute():
        root = Path.cwd() / root
    current = Path(root.anchor)
    if _is_symlink_or_reparse_point(current):
        raise CoverageInputError(f"{label}: {current} is a symlink/reparse point; refusing for safety")
    middle = (run_name,) if run_name is not None else ()
    for part in (*root.parts[1:], *middle, *PurePosixPath(relative_path).parts):
        current = current / part
        if _is_symlink_or_reparse_point(current):
            raise CoverageInputError(
                f"{label}: path component {current} is a symlink/reparse point; refusing to read "
                "through a symlink even when its target remains inside the run directory"
            )
    return current


def read_input_payload(
    *,
    root: Path | str,
    run_name: str | None,
    relative_path: str,
    label: str,
    expected_sha256: str,
    expected_byte_length: int,
    payload_override: bytes | None = None,
) -> bytes:
    """Read (or accept an injected ``payload_override``) and re-verify a
    pinned artifact's raw bytes: byte_length and sha256 must match the
    caller's expectation exactly. When reading from disk, every path
    component from the filesystem anchor to the artifact leaf (the
    caller-supplied ``root``, ``run_name`` -- if any -- and every
    ``relative_path`` segment) is checked with the monkeypatchable
    ``_is_symlink_or_reparse_point`` predicate before any
    ``resolve()``/open; a resolve()+``relative_to()`` containment check
    is retained as defense-in-depth, never as the first safety check.
    ``run_name=None`` addresses the artifact directly as
    ``root/relative_path`` -- for the VUS/holdout/priority-queue inputs
    that have no intervening bundle run directory. Raises
    ``InputPinMismatchError`` on any path-safety, missing-file, or hash/
    length mismatch."""
    if payload_override is not None:
        payload = payload_override
    else:
        if run_name is not None:
            try:
                _validate_run_name(run_name)
            except _SourceBundleBoundaryError as exc:
                raise InputPinMismatchError(f"{label}: {exc}") from exc
        _validate_relative_path_safe(relative_path, label=label)

        run_dir = Path(root) / run_name if run_name is not None else Path(root)
        artifact_path = _validate_no_symlink_components(Path(root), run_name, relative_path, label=label)

        try:
            resolved_artifact_path = artifact_path.resolve()
            resolved_run_dir = run_dir.resolve()
            resolved_artifact_path.relative_to(resolved_run_dir)
        except ValueError as exc:
            raise InputPinMismatchError(f"{label}: artifact path escapes its run directory {run_dir}") from exc

        if _is_symlink_or_reparse_point(artifact_path) or not artifact_path.is_file():
            raise InputPinMismatchError(f"{label}: pinned artifact not found at a trusted path {artifact_path}")

        payload = artifact_path.read_bytes()

    if len(payload) != expected_byte_length:
        raise InputPinMismatchError(
            f"{label}: byte_length mismatch: expected {expected_byte_length!r}, observed {len(payload)!r}"
        )
    observed_sha256 = hashlib.sha256(payload).hexdigest()
    if observed_sha256.lower() != str(expected_sha256).lower():
        raise InputPinMismatchError(
            f"{label}: sha256 mismatch: expected {expected_sha256!r}, observed {observed_sha256!r}"
        )
    return payload


# ---------------------------------------------------------------------------
# Functional-identity-promotion manifest + promoted-row validation.
# ---------------------------------------------------------------------------


def validate_functional_promotion_manifest(
    *,
    promotion_manifest: dict[str, Any],
    expected_pins: dict[str, Any],
) -> dict[str, Any]:
    """Re-verify the already-published functional-identity-promotion
    bundle manifest against ``expected_pins`` (``bundle_id``,
    ``manifest_content_hash``, ``required_identity_state``, and each
    source's pinned ``artifact_id``/``relative_path``/``sha256``/
    ``byte_length``/``row_count``) BEFORE any artifact payload is read.
    Source keys are matched to their exact pinned ``artifact_id`` only --
    the manifest's own artifact records are never required (or assumed)
    to carry a ``source_id`` field. Raises ``InputPinMismatchError`` on
    any hash/bundle_id/artifact-field mismatch, or if the manifest does
    not contain EXACTLY one artifact matching each pinned ``artifact_id``
    (a missing, extra or duplicate artifact_id all fail closed)."""
    if not isinstance(promotion_manifest, dict):
        raise InputPinMismatchError("functional_promotion manifest must be a mapping")
    basis = {key: value for key, value in promotion_manifest.items() if key != "content_hash"}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    recomputed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    recorded = promotion_manifest.get("content_hash")
    if recomputed != recorded:
        raise InputPinMismatchError(
            f"functional_promotion manifest content_hash is not internally consistent: recorded "
            f"{recorded!r} != recomputed {recomputed!r}"
        )
    if recomputed != expected_pins["manifest_content_hash"]:
        raise InputPinMismatchError(
            f"functional_promotion manifest content_hash {recomputed!r} does not match the pinned "
            f"expectation {expected_pins['manifest_content_hash']!r}"
        )
    if promotion_manifest.get("bundle_id") != expected_pins["bundle_id"]:
        raise InputPinMismatchError(
            f"functional_promotion manifest bundle_id {promotion_manifest.get('bundle_id')!r} does not "
            f"match the pinned expectation {expected_pins['bundle_id']!r}"
        )

    artifacts = promotion_manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise InputPinMismatchError("functional_promotion manifest.artifacts must be a list")

    pinned_artifact_ids = {expected_artifact["artifact_id"] for expected_artifact in expected_pins["artifacts"].values()}
    unknown_artifact_ids = {
        artifact.get("artifact_id")
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("artifact_id") not in pinned_artifact_ids
    }
    if unknown_artifact_ids:
        raise InputPinMismatchError(
            f"functional_promotion manifest.artifacts contains unpinned artifact_id(s): "
            f"{sorted(str(x) for x in unknown_artifact_ids)!r}"
        )

    validated_artifacts: dict[str, dict[str, Any]] = {}
    for source_id, expected_artifact in expected_pins["artifacts"].items():
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, dict) and artifact.get("artifact_id") == expected_artifact["artifact_id"]
        ]
        if len(matches) != 1:
            raise InputPinMismatchError(
                f"functional_promotion manifest.artifacts must contain exactly one artifact with "
                f"artifact_id {expected_artifact['artifact_id']!r}, found {len(matches)}"
            )
        actual = matches[0]
        for field_name in ("relative_path", "sha256", "byte_length", "row_count"):
            if actual.get(field_name) != expected_artifact[field_name]:
                raise InputPinMismatchError(
                    f"functional_promotion manifest artifact {expected_artifact['artifact_id']!r} field "
                    f"{field_name!r} does not match the pinned expectation: {actual.get(field_name)!r} "
                    f"!= {expected_artifact[field_name]!r}"
                )
        validated_artifacts[source_id] = {
            "artifact_id": actual["artifact_id"],
            "relative_path": actual["relative_path"],
            "sha256": actual["sha256"],
            "byte_length": actual["byte_length"],
            "row_count": actual["row_count"],
        }

    return {
        "bundle_id": expected_pins["bundle_id"],
        "manifest_content_hash": recomputed,
        "required_identity_state": expected_pins["required_identity_state"],
        "artifacts": validated_artifacts,
    }


def validate_promoted_functional_rows(
    *,
    promoted_rows: list[dict[str, Any]],
    required_identity_state: str,
    expected_source_rows: dict[str, int],
    source_order: tuple[str, ...] | list[str] = SOURCE_ORDER,
) -> list[dict[str, Any]]:
    """Fully reconstruct every promoted row through
    ``raptor.external.tsc2_functional.model.NormalizedFunctionalRow``
    (never merely checking its key set), reject a duplicate
    ``(source_id, source_row)`` key, an unknown ``source_id``, any
    ``identity_state`` other than ``required_identity_state``, and any
    per-source row-count drift from ``expected_source_rows``. Returns the
    fully revalidated rows (``NormalizedFunctionalRow.to_dict()`` shape)."""
    allowed_sources = frozenset(source_order)
    seen_keys: set[tuple[Any, Any]] = set()
    validated_rows: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {source_id: 0 for source_id in source_order}

    for row in promoted_rows:
        try:
            validated = NormalizedFunctionalRow(**row).to_dict()
        except (NormalizationContractError, TypeError) as exc:
            raise CoverageInputError(f"promoted functional row failed schema revalidation: {exc}") from exc

        source_id = validated["source_id"]
        if source_id not in allowed_sources:
            raise CoverageInputError(f"promoted functional row has unknown source_id {source_id!r}")
        if validated["identity_state"] != required_identity_state:
            raise CoverageInputError(
                f"promoted functional row identity_state {validated['identity_state']!r} does not "
                f"match required_identity_state {required_identity_state!r}"
            )
        key = (source_id, validated["source_row"])
        if key in seen_keys:
            raise CoverageInputError(f"duplicate (source_id, source_row) key {key!r} in promoted functional rows")
        seen_keys.add(key)
        source_counts[source_id] += 1
        validated_rows.append(validated)

    for source_id, expected_count in expected_source_rows.items():
        actual_count = source_counts.get(source_id, 0)
        if actual_count != expected_count:
            raise CoverageInputError(
                f"promoted functional row count for source_id {source_id!r} is {actual_count!r}, "
                f"expected {expected_count!r}"
            )

    return validated_rows


# ---------------------------------------------------------------------------
# VUS universe.
# ---------------------------------------------------------------------------


def _parse_jsonl_rows(payload: bytes, *, label: str) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CoverageInputError(f"{label}: payload is not valid UTF-8: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise CoverageInputError(f"{label}: line {line_no} is not valid JSON: {exc}") from exc
    return rows


def _gene_from_accession(accession: str) -> str:
    return _ACCESSION_TO_GENE.get(accession, "UNKNOWN")


def _validate_pin(payload: bytes, *, expected_pin: dict[str, Any], label: str, row_count: int | None = None) -> None:
    if len(payload) != expected_pin["byte_length"]:
        raise CoverageInputError(
            f"{label}: byte_length mismatch: expected {expected_pin['byte_length']!r}, observed "
            f"{len(payload)!r}"
        )
    observed_sha256 = hashlib.sha256(payload).hexdigest()
    if observed_sha256.lower() != str(expected_pin["sha256"]).lower():
        raise CoverageInputError(
            f"{label}: sha256 mismatch: expected {expected_pin['sha256']!r}, observed {observed_sha256!r}"
        )
    if row_count is not None and "row_count" in expected_pin and row_count != expected_pin["row_count"]:
        raise CoverageInputError(
            f"{label}: row_count mismatch: expected {expected_pin['row_count']!r}, observed {row_count!r}"
        )


def _is_required_values_subset(required: Any, actual: Any) -> bool:
    """True iff every key/value pair in ``required`` is present (with an
    identical value, recursing into nested mappings) in ``actual`` --
    ``actual`` may carry additional fields (top-level or nested) that
    ``required`` does not mention. Never the other way around: a key
    ``required`` pins but ``actual`` lacks, or a mismatched value at any
    depth, fails."""
    if isinstance(required, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _is_required_values_subset(value, actual[key]) for key, value in required.items())
    return required == actual


def _validate_identity_manifest_rows(
    rows: list[dict[str, Any]], *, expected_fields: frozenset[str], label: str
) -> None:
    """Cross-validate every identity manifest row (spec ``join_rules``):
    the field set is exact; ``accession`` is one of the two recognized
    TSC1/TSC2 GRCh38 accessions; ``contig`` matches that accession's fixed
    contig; ``variant_id`` is a canonical SPDI whose OWN accession prefix
    agrees with the row's ``accession`` field; ``vcf_key`` is exactly
    ``(contig, position0 + 1, ref, alt)`` re-derived from ``variant_id``.
    ``variant_id``/``vcf_key`` must each be duplicate-free across the
    whole manifest."""
    seen_variant_ids: set[str] = set()
    seen_vcf_keys: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != expected_fields:
            missing = expected_fields - set(row) if isinstance(row, dict) else expected_fields
            extra = set(row) - expected_fields if isinstance(row, dict) else set()
            raise CoverageInputError(
                f"{label}: row {index} does not have the exact required fields; missing="
                f"{sorted(missing)!r} extra={sorted(extra)!r}"
            )
        accession = row["accession"]
        contig = row["contig"]
        variant_id = row["variant_id"]
        vcf_key = row["vcf_key"]

        if accession not in _ACCESSION_TO_CONTIG:
            raise CoverageInputError(f"{label}: row {index} accession {accession!r} is not a recognized accession")
        expected_contig = _ACCESSION_TO_CONTIG[accession]
        if contig != expected_contig:
            raise CoverageInputError(
                f"{label}: row {index} contig {contig!r} does not match accession {accession!r} "
                f"(expected {expected_contig!r})"
            )

        variant_match = _VARIANT_ID_RE.match(variant_id) if isinstance(variant_id, str) else None
        if variant_match is None:
            raise CoverageInputError(f"{label}: row {index} variant_id is not a canonical SPDI: {variant_id!r}")
        if variant_match["accession"] != accession:
            raise CoverageInputError(
                f"{label}: row {index} variant_id accession {variant_match['accession']!r} does not "
                f"match row accession {accession!r}"
            )

        vcf_match = _VCF_KEY_RE.match(vcf_key) if isinstance(vcf_key, str) else None
        if vcf_match is None:
            raise CoverageInputError(f"{label}: row {index} vcf_key is not chr:pos:ref:alt: {vcf_key!r}")
        spdi_position0 = int(variant_match["position"])
        spdi_ref = variant_match["ref"]
        spdi_alt = variant_match["alt"]
        if len(spdi_ref) == 1 and len(spdi_alt) == 1:
            # A pure SNV needs no VCF reference-base anchor padding: the
            # VCF key is exactly (contig, position0 + 1, ref, alt).
            expected_vcf_key = f"{contig}:{spdi_position0 + 1}:{spdi_ref}:{spdi_alt}"
            if vcf_key != expected_vcf_key:
                raise CoverageInputError(
                    f"{label}: row {index} vcf_key {vcf_key!r} does not match the value derived from "
                    f"variant_id/contig {expected_vcf_key!r}"
                )
        else:
            # An indel (unequal-length or empty deleted/inserted) is
            # conventionally VCF-represented with a single leading
            # reference-anchor base prepended to both REF/ALT -- a base
            # this manifest-level check has no reference-genome access to
            # independently recompute. Verify what IS derivable without
            # that anchor: the VCF position is the SPDI position0 (the
            # anchor's own 1-based position) or position0 + 1, and the
            # net REF/ALT length delta agrees exactly with the SPDI
            # deleted/inserted length delta.
            vcf_position0 = int(vcf_match["position"])
            if vcf_position0 not in (spdi_position0, spdi_position0 + 1):
                raise CoverageInputError(
                    f"{label}: row {index} vcf_key position {vcf_position0!r} is not position0 or "
                    f"position0 + 1 of variant_id {variant_id!r}"
                )
            spdi_delta = len(spdi_ref) - len(spdi_alt)
            vcf_delta = len(vcf_match["ref"]) - len(vcf_match["alt"])
            if vcf_delta != spdi_delta:
                raise CoverageInputError(
                    f"{label}: row {index} vcf_key {vcf_key!r} net ref/alt length delta {vcf_delta!r} "
                    f"does not match variant_id {variant_id!r} deleted/inserted length delta "
                    f"{spdi_delta!r}"
                )

        if variant_id in seen_variant_ids:
            raise CoverageInputError(f"{label}: duplicate variant_id {variant_id!r}")
        if vcf_key in seen_vcf_keys:
            raise CoverageInputError(f"{label}: duplicate vcf_key {vcf_key!r}")
        seen_variant_ids.add(variant_id)
        seen_vcf_keys.add(vcf_key)


def _count_genes(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"TSC1": 0, "TSC2": 0}
    for row in rows:
        gene = _gene_from_accession(row["accession"])
        counts[gene] = counts.get(gene, 0) + 1
    return counts


def validate_vus_inputs(
    *,
    manifest_payload: bytes,
    provenance_payload: bytes,
    bias_payload: bytes,
    expected_manifest_pin: dict[str, Any],
    expected_provenance_pin: dict[str, Any],
    expected_bias_pin: dict[str, Any],
    expected_gene_counts: dict[str, int],
) -> dict[str, Any]:
    """Byte-pin (hash/length/row_count) and schema-validate the frozen
    6,618-row VUS identity manifest, its provenance JSON and its BIAS TSV
    -- every payload's raw hash/length is verified BEFORE any JSON/JSONL
    row is parsed. Rejects a duplicate ``variant_id``/``vcf_key`` and any
    gene-count drift. Never reads ``acmgClassification`` (or any other
    BIAS column) for identity or priority purposes -- the BIAS payload is
    verified only as pinned raw bytes here."""
    _validate_pin(manifest_payload, expected_pin=expected_manifest_pin, label="vus_manifest")
    rows = _parse_jsonl_rows(manifest_payload, label="vus_manifest")
    if "row_count" in expected_manifest_pin and len(rows) != expected_manifest_pin["row_count"]:
        raise CoverageInputError(
            f"vus_manifest: row_count mismatch: expected {expected_manifest_pin['row_count']!r}, "
            f"observed {len(rows)!r}"
        )
    _validate_identity_manifest_rows(
        rows, expected_fields=frozenset(expected_manifest_pin["required_fields"]), label="vus_manifest"
    )

    _validate_pin(provenance_payload, expected_pin=expected_provenance_pin, label="vus_provenance", row_count=1)
    try:
        provenance = json.loads(provenance_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageInputError(f"vus_provenance: payload is not valid JSON: {exc}") from exc
    if not _is_required_values_subset(expected_provenance_pin["required_values"], provenance):
        raise CoverageInputError(
            f"vus_provenance required_values mismatch: {provenance!r} != "
            f"{expected_provenance_pin['required_values']!r}"
        )

    _validate_pin(bias_payload, expected_pin=expected_bias_pin, label="vus_bias")
    bias_row_count = max(len(bias_payload.decode("utf-8").splitlines()) - 1, 0)
    if "row_count" in expected_bias_pin and bias_row_count != expected_bias_pin["row_count"]:
        raise CoverageInputError(
            f"vus_bias: row_count mismatch: expected {expected_bias_pin['row_count']!r}, observed "
            f"{bias_row_count!r}"
        )

    gene_counts = _count_genes(rows)
    if gene_counts != expected_gene_counts:
        raise CoverageInputError(f"vus gene_counts mismatch: {gene_counts!r} != {expected_gene_counts!r}")

    return {"identity_count": len(rows), "gene_counts": gene_counts, "rows": rows}


# ---------------------------------------------------------------------------
# Prospective holdout.
# ---------------------------------------------------------------------------


def validate_prospective_holdout_inputs(
    *,
    manifest_payload: bytes,
    provenance_payload: bytes,
    expected_manifest_pin: dict[str, Any],
    expected_provenance_pin: dict[str, Any],
    expected_gene_counts: dict[str, int],
    forbidden_reads: list[str],
) -> dict[str, Any]:
    """Byte-pin (BEFORE any JSON/JSONL parse) and schema-validate the
    frozen 2,608-row label-free prospective holdout export manifest and
    provenance. Rejects any extra field (including ``classification``/
    any label), a duplicate ``variant_id``/``vcf_key``, and any gene-count
    drift. Never opens any path in ``forbidden_reads`` (a labeled/
    adjudication artifact) -- those names are validated as a static
    exclusion list only."""
    del forbidden_reads  # a static exclusion list this validator never opens.
    _validate_pin(manifest_payload, expected_pin=expected_manifest_pin, label="holdout_manifest")
    rows = _parse_jsonl_rows(manifest_payload, label="holdout_manifest")
    if "row_count" in expected_manifest_pin and len(rows) != expected_manifest_pin["row_count"]:
        raise CoverageInputError(
            f"holdout_manifest: row_count mismatch: expected {expected_manifest_pin['row_count']!r}, "
            f"observed {len(rows)!r}"
        )
    _validate_identity_manifest_rows(
        rows, expected_fields=frozenset(expected_manifest_pin["required_fields"]), label="holdout_manifest"
    )

    _validate_pin(provenance_payload, expected_pin=expected_provenance_pin, label="holdout_provenance", row_count=1)
    try:
        provenance = json.loads(provenance_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageInputError(f"holdout_provenance: payload is not valid JSON: {exc}") from exc
    if not _is_required_values_subset(expected_provenance_pin["required_values"], provenance):
        raise CoverageInputError(
            f"holdout_provenance required_values mismatch: {provenance!r} != "
            f"{expected_provenance_pin['required_values']!r}"
        )

    gene_counts = _count_genes(rows)
    if gene_counts != expected_gene_counts:
        raise CoverageInputError(f"holdout gene_counts mismatch: {gene_counts!r} != {expected_gene_counts!r}")

    return {"identity_count": len(rows), "gene_counts": gene_counts, "rows": rows}


# ---------------------------------------------------------------------------
# Priority-subset reproduction (disabled/manual census seam).
# ---------------------------------------------------------------------------


def _real_reproduce_census_strata(
    *,
    manifest_rows: list[dict[str, Any]],
    bias_payload: bytes,
    scorer_config_pin: dict[str, Any],
    eval_config_pin: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reproduce the disabled/manual VUS census strata for real: verify
    the pinned scorer/eval config raw bytes, load them through
    ``raptor.scorer.config``/``raptor.eval.config``, parse ``bias_payload``
    through ``raptor.scorer.bias_source.BiasTsvSource`` and join via
    ``raptor.census.strata.reproduce_census_strata``. Never imports
    ``raptor.packet``."""
    from raptor.census.strata import ManifestEntry, reproduce_census_strata
    from raptor.eval.config import load_config as load_eval_config
    from raptor.scorer.bias_source import BiasTsvSource
    from raptor.scorer.config import load_config as load_scorer_config

    for pin, label in ((scorer_config_pin, "scorer_config"), (eval_config_pin, "eval_config")):
        config_path = Path(pin["path"])
        raw_bytes = config_path.read_bytes()
        observed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if observed_sha256.lower() != str(pin["raw_sha256"]).lower():
            raise CoverageInputError(
                f"{label}: raw_sha256 mismatch: expected {pin['raw_sha256']!r}, observed "
                f"{observed_sha256!r}"
            )

    scorer_config = load_scorer_config(scorer_config_pin["path"])
    eval_config = load_eval_config(eval_config_pin["path"])

    manifest_by_vcf_key = {}
    for row in manifest_rows:
        entry = ManifestEntry(variant_id=str(row["variant_id"]), vcf_key=str(row["vcf_key"]))
        manifest_by_vcf_key[entry.vcf_key] = entry

    with tempfile.NamedTemporaryFile(suffix=".tsv", delete=False) as handle:
        handle.write(bias_payload)
        bias_tsv_path = Path(handle.name)
    try:
        bias_rows = list(BiasTsvSource(bias_tsv_path).records())
    finally:
        bias_tsv_path.unlink(missing_ok=True)

    entries = reproduce_census_strata(bias_rows, manifest_by_vcf_key, scorer_config, eval_config)
    return [{"variant_id": entry.variant_id, "stratum": entry.stratum} for entry in entries]


def reproduce_priority_subset(
    *,
    vus_manifest_payload: bytes,
    bias_payload: bytes,
    aggregate_manifest_payload: bytes,
    queue_payload: bytes,
    expected: dict[str, Any],
    queue_pin: dict[str, Any],
    aggregate_manifest_pin: dict[str, Any],
    predictor_policy: dict[str, Any],
    scorer_config_pin: dict[str, Any],
    eval_config_pin: dict[str, Any],
    lineage_policy_pin: dict[str, Any],
    packet_policy_pin: dict[str, Any],
    reproduce_census_strata_fn: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Reproduce the internal priority subset (candidate_LP_review union
    candidate_LB_review) through the disabled/manual census
    seam and require the frozen external priority queue's canonical-SPDI
    set to equal the reproduced subset exactly.

    ``predictor_policy`` must be exactly the frozen, approved,
    disabled-manual BP4/PP3 predictor policy. ``lineage_policy_pin``/
    ``packet_policy_pin`` are cross-checked as frozen file pins only --
    their content is never read for identity/priority computation.
    Never reads ``acmgClassification`` and never treats a committed
    aggregate as the identity oracle: the aggregate manifest is
    byte/schema-pinned but the reproduced subset is always independently
    recomputed."""
    if predictor_policy != _REQUIRED_PREDICTOR_POLICY:
        raise CoverageInputError(
            f"approved_predictor_policy mismatch: {predictor_policy!r} != {_REQUIRED_PREDICTOR_POLICY!r}"
        )
    for pin, label in ((lineage_policy_pin, "lineage_policy"), (packet_policy_pin, "packet_policy")):
        if reproduce_census_strata_fn is None:
            raw_bytes = Path(pin["path"]).read_bytes()
            observed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            if observed_sha256.lower() != str(pin["raw_sha256"]).lower():
                raise CoverageInputError(
                    f"{label}: raw_sha256 mismatch: expected {pin['raw_sha256']!r}, observed "
                    f"{observed_sha256!r}"
                )

    _validate_pin(
        aggregate_manifest_payload, expected_pin=aggregate_manifest_pin, label="priority_aggregate_manifest",
        row_count=1,
    )
    try:
        aggregate_manifest = json.loads(aggregate_manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageInputError(f"priority_aggregate_manifest: payload is not valid JSON: {exc}") from exc
    if not _is_required_values_subset(aggregate_manifest_pin["required_values"], aggregate_manifest):
        raise CoverageInputError(
            f"priority_aggregate_manifest required_values mismatch: {aggregate_manifest!r} != "
            f"{aggregate_manifest_pin['required_values']!r}"
        )

    _validate_pin(queue_payload, expected_pin=queue_pin, label="priority_queue")
    queue_rows = _parse_jsonl_rows(queue_payload, label="priority_queue")
    if "row_count" in queue_pin and len(queue_rows) != queue_pin["row_count"]:
        raise CoverageInputError(
            f"priority_queue: row_count mismatch: expected {queue_pin['row_count']!r}, observed "
            f"{len(queue_rows)!r}"
        )

    exact_fields = frozenset(queue_pin.get("exact_fields", _DEFAULT_QUEUE_EXACT_FIELDS))
    required_review_state = queue_pin.get("required_review_state", "POLICY_BLOCKED")
    required_gate_status = queue_pin.get("required_gate_status", "UNVERIFIED")
    seen_spdi: set[str] = set()
    seen_packet_ids: set[str] = set()
    seen_evidence_hashes: set[str] = set()
    queue_by_spdi: dict[str, str] = {}
    for index, row in enumerate(queue_rows):
        if not isinstance(row, dict) or set(row) != exact_fields:
            raise CoverageInputError(
                f"priority_queue: row {index} does not have the exact required fields "
                f"{sorted(exact_fields)!r}, got {sorted(row) if isinstance(row, dict) else row!r}"
            )
        packet_id = row["packet_id"]
        evidence_core_hash = row["evidence_core_hash"]
        spdi = row["canonical_spdi"]
        gene = row["gene"]
        quality_flags = row["quality_flags"]
        contradiction = row["contradiction"]

        if not isinstance(packet_id, str) or not packet_id.strip():
            raise CoverageInputError(f"priority_queue: row {index} packet_id must be a non-blank string")
        if not isinstance(evidence_core_hash, str) or not _SHA256_HEX_RE.match(evidence_core_hash):
            raise CoverageInputError(
                f"priority_queue: row {index} evidence_core_hash must be a 64-hex-digit string"
            )
        spdi_match = _VARIANT_ID_RE.match(spdi) if isinstance(spdi, str) else None
        if spdi_match is None:
            raise CoverageInputError(f"priority_queue: row {index} canonical_spdi is not a canonical SPDI: {spdi!r}")
        expected_gene = _gene_from_accession(spdi_match["accession"])
        if gene != expected_gene:
            raise CoverageInputError(
                f"priority_queue: row {index} gene {gene!r} does not match accession-derived gene "
                f"{expected_gene!r}"
            )
        if not isinstance(quality_flags, list) or not all(
            isinstance(flag, str) and flag.strip() for flag in quality_flags
        ):
            raise CoverageInputError(
                f"priority_queue: row {index} quality_flags must be a list of non-blank strings"
            )
        if not isinstance(contradiction, bool):
            raise CoverageInputError(f"priority_queue: row {index} contradiction must be a strict bool")
        if row["review_state"] != required_review_state:
            raise CoverageInputError(
                f"priority_queue: row {index} review_state {row['review_state']!r} != "
                f"{required_review_state!r}"
            )
        if row["gate_status"] != required_gate_status:
            raise CoverageInputError(
                f"priority_queue: row {index} gate_status {row['gate_status']!r} != "
                f"{required_gate_status!r}"
            )
        if packet_id in seen_packet_ids:
            raise CoverageInputError(f"priority_queue: duplicate packet_id {packet_id!r}")
        if evidence_core_hash in seen_evidence_hashes:
            raise CoverageInputError(f"priority_queue: duplicate evidence_core_hash {evidence_core_hash!r}")
        if spdi in seen_spdi:
            raise CoverageInputError(f"priority_queue: duplicate canonical_spdi {spdi!r}")
        seen_packet_ids.add(packet_id)
        seen_evidence_hashes.add(evidence_core_hash)
        seen_spdi.add(spdi)
        queue_by_spdi[spdi] = gene

    manifest_rows = _parse_jsonl_rows(vus_manifest_payload, label="vus_manifest_for_priority")

    if reproduce_census_strata_fn is not None:
        entries = reproduce_census_strata_fn(manifest_rows=manifest_rows, bias_payload=bias_payload)
    else:
        entries = _real_reproduce_census_strata(
            manifest_rows=manifest_rows,
            bias_payload=bias_payload,
            scorer_config_pin=scorer_config_pin,
            eval_config_pin=eval_config_pin,
        )

    reproduced: dict[str, str] = {
        entry["variant_id"]: entry["stratum"]
        for entry in entries
        if entry["stratum"] in ("candidate_LP_review", "candidate_LB_review")
    }
    reproduced_spdi_set = set(reproduced)
    if reproduced_spdi_set != seen_spdi:
        only_reproduced = sorted(reproduced_spdi_set - seen_spdi)[:5]
        only_queue = sorted(seen_spdi - reproduced_spdi_set)[:5]
        raise CoverageInputError(
            "reproduced priority subset does not exactly equal the frozen external priority queue's "
            f"canonical-SPDI set: only_in_reproduced={only_reproduced!r} only_in_queue={only_queue!r}"
        )

    stratum_counts = {"candidate_LP_review": 0, "candidate_LB_review": 0}
    gene_counts = {"TSC1": 0, "TSC2": 0}
    for spdi, stratum in reproduced.items():
        stratum_counts[stratum] += 1
        gene = queue_by_spdi[spdi]
        gene_counts[gene] = gene_counts.get(gene, 0) + 1

    if stratum_counts["candidate_LP_review"] != expected["candidate_LP_review"]:
        raise CoverageInputError(
            f"candidate_LP_review count {stratum_counts['candidate_LP_review']!r} != expected "
            f"{expected['candidate_LP_review']!r}"
        )
    if stratum_counts["candidate_LB_review"] != expected["candidate_LB_review"]:
        raise CoverageInputError(
            f"candidate_LB_review count {stratum_counts['candidate_LB_review']!r} != expected "
            f"{expected['candidate_LB_review']!r}"
        )
    if len(reproduced) != expected["total"]:
        raise CoverageInputError(f"priority subset total {len(reproduced)!r} != expected {expected['total']!r}")
    if gene_counts != expected["gene_counts"]:
        raise CoverageInputError(f"priority subset gene_counts {gene_counts!r} != expected {expected['gene_counts']!r}")

    return {
        "identity_count": len(reproduced),
        "stratum_counts": stratum_counts,
        "gene_counts": gene_counts,
        "priority_by_spdi": dict(reproduced),
    }


# ---------------------------------------------------------------------------
# Atlas contrast identities (public loader seam + raw inventory replay).
# ---------------------------------------------------------------------------


def load_atlas_contrast_replays(
    *,
    map_path: Path,
    response_root: Path,
    lock_path: Path,
    disease_pack_path: Path,
    raw_inventory_path: Path,
    map_payload: bytes,
    lock_payload: bytes,
    raw_inventory_payload: bytes,
    response_bundle_observed: dict[str, Any],
    raw_inventory_rows: list[dict[str, Any]],
    expected_map_pin: dict[str, Any],
    expected_lock_pin: dict[str, Any],
    expected_raw_inventory_pin: dict[str, Any],
    expected_response_bundle_pin: dict[str, Any],
    expected_counts: dict[str, int],
    load_disease_pack_fn: Callable[..., Any] | None = None,
    load_identity_map_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Byte-verify the raw identity map, the tracked lock's schema and
    canonical self-hash (never its raw bytes -- the lock is a self-hashed
    structure, not a fixed-byte artifact), the raw inventory's raw bytes/
    count, and the caller-observed response-tree commitment fields
    (``response_bundle_observed``, already computed by the caller --
    typically by walking the response root the same way the public loader
    itself will) against ``expected_*_pin`` -- all BEFORE the public
    ``raptor.atlas.pack.load_disease_pack``/``raptor.atlas.identity_map.
    load_identity_map`` seams are ever invoked (never reimplementing
    their own internal hash/lock/pack-binding verification). Every raw
    inventory row is then replayed through the returned offline mapper.
    Resolved and unresolved records are preserved exactly (never joined
    together); an unresolved record must never carry a non-null
    ``spdi_canonical``, and every resolved ``spdi_canonical`` must be a
    canonical TSC1/TSC2 SPDI string. Typed ``AtlasPackError``/
    ``AtlasIdentityMapError`` raised by the public loaders are translated
    into ``CoverageInputError`` -- never caught by a broad ``except
    Exception``."""
    if len(map_payload) != expected_map_pin["byte_length"]:
        raise CoverageInputError("atlas raw_identity_map: byte_length mismatch")
    if hashlib.sha256(map_payload).hexdigest().lower() != str(expected_map_pin["sha256"]).lower():
        raise CoverageInputError("atlas raw_identity_map: sha256 mismatch")
    try:
        parsed_map = yaml.safe_load(map_payload.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise CoverageInputError(f"atlas raw_identity_map: payload is not valid YAML: {exc}") from exc
    if not isinstance(parsed_map, dict) or parsed_map.get("schema") != expected_map_pin["schema"]:
        raise CoverageInputError("atlas raw_identity_map: schema mismatch")
    map_records = parsed_map.get("records")
    if not isinstance(map_records, list) or len(map_records) != expected_map_pin["map_record_count"]:
        raise CoverageInputError("atlas raw_identity_map: map_record_count mismatch")

    try:
        parsed_lock = yaml.safe_load(lock_payload.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise CoverageInputError(f"atlas tracked_lock: payload is not valid YAML: {exc}") from exc
    if not isinstance(parsed_lock, dict):
        raise CoverageInputError("atlas tracked_lock: payload must decode to a mapping")
    if parsed_lock.get("schema") != expected_lock_pin["schema"]:
        raise CoverageInputError("atlas tracked_lock: schema mismatch")
    from raptor.atlas.identity_map import identity_map_lock_content_hash

    recomputed_lock_hash = identity_map_lock_content_hash(parsed_lock)
    if recomputed_lock_hash != parsed_lock.get("lock_content_hash"):
        raise CoverageInputError(
            "atlas tracked_lock: lock_content_hash is not internally consistent: recorded "
            f"{parsed_lock.get('lock_content_hash')!r} != recomputed {recomputed_lock_hash!r}"
        )
    if recomputed_lock_hash != expected_lock_pin["lock_content_hash"]:
        raise CoverageInputError(
            f"atlas tracked_lock: lock_content_hash {recomputed_lock_hash!r} does not match the "
            f"pinned expectation {expected_lock_pin['lock_content_hash']!r}"
        )

    if len(raw_inventory_payload) != expected_raw_inventory_pin["byte_length"]:
        raise CoverageInputError("atlas raw_inventory: byte_length mismatch")
    if hashlib.sha256(raw_inventory_payload).hexdigest().lower() != str(expected_raw_inventory_pin["sha256"]).lower():
        raise CoverageInputError("atlas raw_inventory: sha256 mismatch")
    if len(raw_inventory_rows) != expected_raw_inventory_pin["row_count"]:
        raise CoverageInputError(
            f"atlas raw_inventory: row_count mismatch: expected {expected_raw_inventory_pin['row_count']!r}, "
            f"observed {len(raw_inventory_rows)!r}"
        )

    for field_name in ("sha256", "file_count", "byte_count"):
        if response_bundle_observed.get(field_name) != expected_response_bundle_pin[field_name]:
            raise CoverageInputError(
                f"atlas response_bundle: observed {field_name} {response_bundle_observed.get(field_name)!r} "
                f"does not match the pinned expectation {expected_response_bundle_pin[field_name]!r}"
            )

    if load_disease_pack_fn is None:
        from raptor.atlas.pack import load_disease_pack as load_disease_pack_fn  # type: ignore[assignment]
    if load_identity_map_fn is None:
        from raptor.atlas.identity_map import load_identity_map as load_identity_map_fn  # type: ignore[assignment]

    from raptor.atlas.model import AtlasError

    try:
        disease_pack = load_disease_pack_fn(disease_pack_path)
    except AtlasError as exc:
        raise CoverageInputError(f"atlas disease pack load failed: {exc}") from exc

    try:
        mapper = load_identity_map_fn(
            map_path=map_path,
            response_root=response_root,
            lock_path=lock_path,
            disease_pack=disease_pack,
            raw_inventory_path=raw_inventory_path,
        )
    except AtlasError as exc:
        raise CoverageInputError(f"atlas identity map load failed: {exc}") from exc


    resolved_spdis: set[str] = set()
    unresolved_count = 0
    for row in raw_inventory_rows:
        replay = mapper.replay(
            row["raw_record_id"], row["raw_identity_string"], row["source_reported_consequence_hint"]
        )
        identity_state = replay["identity_state"] if isinstance(replay, dict) else replay.identity_state
        spdi_canonical = replay["spdi_canonical"] if isinstance(replay, dict) else replay.spdi_canonical
        if identity_state == "resolved":
            if not isinstance(spdi_canonical, str) or not _VARIANT_ID_RE.match(spdi_canonical):
                raise CoverageInputError(
                    f"atlas replay for {row['raw_record_id']!r} is resolved but spdi_canonical "
                    f"{spdi_canonical!r} is not a canonical SPDI"
                )
            resolved_spdis.add(spdi_canonical)
        elif identity_state == "unresolved":
            if spdi_canonical is not None:
                raise CoverageInputError(
                    f"atlas replay for {row['raw_record_id']!r} is unresolved but carries a non-null "
                    f"spdi_canonical {spdi_canonical!r}"
                )
            unresolved_count += 1
        else:
            raise CoverageInputError(
                f"atlas replay for {row['raw_record_id']!r} has unknown identity_state {identity_state!r}"
            )

    if len(raw_inventory_rows) != expected_counts["raw_records"]:
        raise CoverageInputError(
            f"atlas raw_records count {len(raw_inventory_rows)!r} != expected "
            f"{expected_counts['raw_records']!r}"
        )
    if len(resolved_spdis) != expected_counts["resolved_unique_spdi"]:
        raise CoverageInputError(
            f"atlas resolved_unique_spdi count {len(resolved_spdis)!r} != expected "
            f"{expected_counts['resolved_unique_spdi']!r}"
        )
    if unresolved_count != expected_counts["unresolved_records"]:
        raise CoverageInputError(
            f"atlas unresolved_records count {unresolved_count!r} != expected "
            f"{expected_counts['unresolved_records']!r}"
        )

    return {
        "raw_records": len(raw_inventory_rows),
        "resolved_count": len(resolved_spdis),
        "unresolved_count": unresolved_count,
        "resolved_spdis": resolved_spdis,
    }


# ---------------------------------------------------------------------------
# Atlas anchor ($R611Q$).
# ---------------------------------------------------------------------------


def validate_atlas_anchor_input(
    *,
    anchor_payload: dict[str, Any],
    anchor_payload_bytes: bytes,
    expected_pin: dict[str, Any],
) -> dict[str, Any]:
    """Byte-pin the $R611Q$ Atlas anchor gate result and read only its
    nested ``variant.spdi`` as identity context. Every boundary field
    (``gate_8``/``accepted_claim_count``/``promote_candidate_invoked``)
    is re-verified but never promoted into a claim; this function returns
    identity context only."""
    if hashlib.sha256(anchor_payload_bytes).hexdigest().lower() != str(expected_pin["raw_sha256"]).lower():
        raise CoverageInputError("atlas_anchor: raw_sha256 mismatch")
    if anchor_payload.get("schema") != expected_pin["schema"]:
        raise CoverageInputError(
            f"atlas_anchor: schema {anchor_payload.get('schema')!r} != expected {expected_pin['schema']!r}"
        )
    required = expected_pin["required"]
    for key, expected_value in required.items():
        if key == "variant":
            variant = anchor_payload.get("variant")
            if not isinstance(variant, dict) or variant.get("spdi") != expected_value["spdi"]:
                raise CoverageInputError(
                    f"atlas_anchor: variant.spdi {variant.get('spdi') if isinstance(variant, dict) else variant!r} "
                    f"!= expected {expected_value['spdi']!r}"
                )
            continue
        if anchor_payload.get(key) != expected_value:
            raise CoverageInputError(
                f"atlas_anchor: {key} {anchor_payload.get(key)!r} != expected {expected_value!r}"
            )

    return {"spdi": anchor_payload["variant"]["spdi"]}


__all__ = [
    "CoverageInputError",
    "InputPinMismatchError",
    "validate_input_roots_absolute",
    "read_input_payload",
    "validate_functional_promotion_manifest",
    "validate_promoted_functional_rows",
    "validate_vus_inputs",
    "reproduce_priority_subset",
    "validate_prospective_holdout_inputs",
    "load_atlas_contrast_replays",
    "validate_atlas_anchor_input",
]
