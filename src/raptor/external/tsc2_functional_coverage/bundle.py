"""RAPTOR v2 TSC2 functional coverage map -- output bundle manifest,
canonical hashing/JSONL, create-only/symlink-safe publication and a
compact, aggregate-only committed summary.

``build_coverage_bundle_manifest`` computes a canonical ``content_hash``
(SHA-256 of UTF-8 canonical JSON, sorted object keys, ``(",", ":")``
separators, array order preserved, only the top-level ``content_hash``
key itself excluded) over a manifest whose top-level field is
``coverage_statistics`` -- never ``expected_pilot`` (the frozen pilot
expectation lives only in config/spec/tests and is compared generically
by the operator's own gate, never embedded in a published manifest).

``canonical_coverage_jsonl_bytes`` reuses
``raptor.external.tsc2_functional_coverage.model.FunctionalCoverageRow``
directly to fully revalidate every row and reject a duplicate ``spdi``,
then emits one canonical sorted-key JSON object per line (sorted
lexicographically by ``spdi``), UTF-8, LF-only, with a final newline.

``publish_coverage_bundle`` reuses this repository's already-hardened
external/create-only/symlink-safe/race-safe/manifest-last publication
primitive -- ``raptor.external.tsc2_sources.bundle.
_publish_directory_no_replace`` -- verbatim (the SAME function object,
never a reimplementation) for the actual atomic no-clobber directory
rename, and reuses that module's other private boundary helpers (run-name
validation, the publication-reservation lock, and the safe relative-path
join) rather than duplicating their hardened, previously-tested logic.
This module exposes its OWN monkeypatchable ``_is_symlink_or_reparse_point``
(used for output-root lexical-ancestry checks) and imports
``_write_bytes_exclusive`` as a bare name (used to populate the staging
directory, manifest LAST) so both are independently testable.

``build_committed_summary`` is a strict field-whitelist projection off an
already-built manifest: pins/hashes, output artifact integrity and the
manifest's ``coverage_statistics`` sub-objects flattened to the top level
-- never a per-row identity, SPDI/HGVS/VCF-key string, raw score, source
functional class, or any clinical/evidence-strength claim.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb`` or
``raptor.rescuescreen``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from raptor.external.tsc2_sources.bundle import BundleBoundaryError as _SourceBundleBoundaryError
from raptor.external.tsc2_sources.bundle import MANIFEST_FILENAME
from raptor.external.tsc2_sources.bundle import _publish_directory_no_replace
from raptor.external.tsc2_sources.bundle import _release_reservation
from raptor.external.tsc2_sources.bundle import _reserve_run_name
from raptor.external.tsc2_sources.bundle import _safe_join
from raptor.external.tsc2_sources.bundle import _validate_run_name
from raptor.external.tsc2_sources.bundle import _write_bytes_exclusive

from .model import LEAKAGE_MARKER_ORDER, SOURCE_ORDER, CoverageContractError, FunctionalCoverageRow

BUNDLE_SCHEMA = "raptor.external.tsc2_functional_coverage_bundle.v1"
SUMMARY_SCHEMA = "raptor.external.tsc2_functional_coverage_summary.v1"

#: The exact, whitelisted (artifact_id -> relative_path) mapping the
#: output bundle's single coverage artifact must use (spec
#: ``output.external_bundle.artifacts.coverage``).
_CANONICAL_ARTIFACT_RELATIVE_PATHS: dict[str, str] = {
    "tsc2-functional-coverage-jsonl": "coverage/functional_identity_coverage.jsonl",
}

#: The exact, fixed boundaries mapping every coverage manifest must carry
#: verbatim (spec ``boundaries``).
_REQUIRED_BOUNDARIES: dict[str, str] = {
    "network": "forbidden",
    "score_semantic_use": "forbidden",
    "score_output": "forbidden",
    "label_access": "forbidden",
    "clinical_use": "forbidden",
    "evidence_strength_use": "forbidden",
    "ps3_bs3_use": "forbidden",
    "atlas_claim_promotion": "forbidden",
}

_REQUIRED_INPUT_MANIFEST_KEYS = frozenset(
    {"functional_identity_promotion", "vus_manifest", "prospective_holdout_manifest", "atlas_identity_map"}
)
_REQUIRED_STATISTICS_KEYS = frozenset(
    {"functional", "cohorts", "cross_cohort", "functional_cohort_membership_patterns", "leakage_markers"}
)

#: Every non-empty ordered combination of ``SOURCE_ORDER`` (singles, then
#: pairs, then the full triple, each in ``SOURCE_ORDER`` order) -- the
#: exact, fixed key vocabulary every ``source_membership_patterns``
#: mapping must carry. Derived programmatically from ``SOURCE_ORDER``
#: rather than hardcoded.
def _all_source_membership_pattern_keys(source_order: tuple[str, ...]) -> tuple[str, ...]:
    import itertools

    keys: list[str] = list(source_order)
    for size in range(2, len(source_order) + 1):
        for combo in itertools.combinations(source_order, size):
            keys.append("+".join(combo))
    return tuple(keys)


_SOURCE_MEMBERSHIP_PATTERN_KEYS = _all_source_membership_pattern_keys(SOURCE_ORDER)

#: The fixed, domain-specific functional-cohort-membership pattern
#: vocabulary (never a hardcoded "expected pilot" numeric literal -- only
#: the seven possible flag combinations this join can ever produce, given
#: VUS/PROSPECTIVE_HOLDOUT mutual exclusivity).
_FUNCTIONAL_COHORT_MEMBERSHIP_PATTERN_KEYS = (
    "NONE",
    "VUS",
    "VUS+ATLAS_CONTRAST",
    "PROSPECTIVE_HOLDOUT",
    "PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST",
    "PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR",
    "ATLAS_CONTRAST",
)

_REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "bundle_id",
        "created_at",
        "input_manifests",
        "artifacts",
        "counts",
        "coverage_statistics",
        "boundaries",
        "content_hash",
    }
)
_REQUIRED_MANIFEST_FIELDS_NO_HASH = _REQUIRED_MANIFEST_FIELDS - {"content_hash"}
_REQUIRED_ARTIFACT_FIELDS = frozenset({"artifact_id", "relative_path", "byte_length", "sha256", "row_count"})
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class CoverageBundleBoundaryError(ValueError):
    """Raised for output-path boundary violations: writing inside the
    repository, writing onto a pre-existing (create-only) final run path,
    or writing onto a symlink/reparse-point path component anywhere from
    the filesystem anchor down to the final run leaf."""


class CoverageManifestError(ValueError):
    """Raised when a coverage manifest's ``content_hash`` does not match
    its recomputed canonical hash, when a published artifact payload's
    actual bytes do not match its manifest-declared ``byte_length``/
    ``sha256``, or when the manifest itself violates its schema/
    whitelist/count invariants."""


# ---------------------------------------------------------------------------
# Canonical JSONL.
# ---------------------------------------------------------------------------


def canonical_coverage_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    """Fully revalidate every row through
    ``raptor.external.tsc2_functional_coverage.model.FunctionalCoverageRow``
    (never merely checking its key set), reject a duplicate ``spdi``, and
    return one canonical sorted-key compact JSON object per line -- sorted
    lexicographically by ``spdi`` -- UTF-8, LF-only, with a final newline.
    Deterministic regardless of the input rows' order."""
    validated_rows: list[dict[str, Any]] = []
    seen_spdi: set[str] = set()
    for row in rows:
        try:
            validated = FunctionalCoverageRow(**row).to_dict()
        except (CoverageContractError, TypeError) as exc:
            raise CoverageManifestError(f"coverage row failed schema revalidation: {exc}") from exc
        if validated["spdi"] in seen_spdi:
            raise CoverageManifestError(f"duplicate spdi {validated['spdi']!r} in canonical coverage JSONL output")
        seen_spdi.add(validated["spdi"])
        validated_rows.append(validated)

    validated_rows.sort(key=lambda r: r["spdi"])
    if not validated_rows:
        return b""
    lines = [
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for row in validated_rows
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Manifest schema/contract + canonical hashing.
# ---------------------------------------------------------------------------


def _require_nonneg_int(value: Any, *, context: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CoverageManifestError(f"{context} must be a non-negative int, got {value!r}")


def _validate_numeric_leaves(value: Any, *, context: str) -> None:
    """Recursively require every leaf of a nested statistics mapping to be
    a strict, non-negative int (never a bool, float or string) -- the
    coverage_statistics contract's "all count types strict nonnegative
    ints" invariant."""
    if isinstance(value, dict):
        for key, sub_value in value.items():
            _validate_numeric_leaves(sub_value, context=f"{context}.{key}")
        return
    _require_nonneg_int(value, context=context)


def _require_exact_keys(value: Any, expected_keys: frozenset[str] | set[str], *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(expected_keys):
        raise CoverageManifestError(f"{context} must have exactly the keys {sorted(expected_keys)!r}")
    return value


def _require_keys_with_optional(
    value: Any, required_keys: frozenset[str] | set[str], optional_keys: frozenset[str] | set[str], *, context: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoverageManifestError(f"{context} must be a mapping")
    actual = set(value)
    if not set(required_keys).issubset(actual) or not actual.issubset(set(required_keys) | set(optional_keys)):
        raise CoverageManifestError(
            f"{context} must have exactly the keys {sorted(required_keys)!r}, optionally also "
            f"{sorted(optional_keys)!r}"
        )
    return value


def _pattern_membership_sum(patterns: dict[str, int], source: str) -> int:
    return sum(count for pattern, count in patterns.items() if source in pattern.split("+"))


_COHORT_KEYS_WITH_SOURCE_PATTERNS = frozenset(
    {"identities", "TSC1", "TSC2", "functional_overlap_unique", "source_overlap_unique", "source_membership_patterns"}
)
_PRIORITY_COHORT_REQUIRED_KEYS = frozenset(
    {
        "identities",
        "candidate_LP_review",
        "candidate_LB_review",
        "TSC1",
        "TSC2",
        "functional_overlap_unique",
        "candidate_LP_review_overlap",
        "candidate_LB_review_overlap",
        "source_overlap_unique",
    }
)
#: ``source_membership_patterns`` is OPTIONAL for the priority cohort:
#: config/spec's frozen ``expected_pilot.cohorts.priority`` never carries
#: it, but a caller-supplied manifest MAY still include it (e.g. a
#: fixture that computes it anyway) without being rejected.
_PRIORITY_COHORT_OPTIONAL_KEYS = frozenset({"source_membership_patterns"})
_ATLAS_CONTRAST_COHORT_KEYS = frozenset(
    {
        "raw_records",
        "resolved_unique_spdi",
        "unresolved_records",
        "functional_overlap_unique",
        "source_overlap_unique",
        "source_membership_patterns",
    }
)
_ATLAS_ANCHOR_COHORT_KEYS = frozenset(
    {"identities", "functional_overlap_unique", "source_overlap_unique", "prospective_holdout_overlap"}
)
_CROSS_COHORT_KEYS = frozenset(
    {
        "vus__prospective_holdout",
        "priority__prospective_holdout",
        "vus__atlas_contrast",
        "priority__atlas_contrast",
        "prospective_holdout__atlas_contrast",
        "functional__vus__atlas_contrast",
        "functional__prospective_holdout__atlas_contrast",
        "functional__atlas_contrast_outside_vus_holdout",
    }
)


def _validate_source_dicts(cohort: dict[str, Any], *, context: str, functional_overlap: int) -> None:
    source_unique = _require_exact_keys(
        cohort["source_overlap_unique"], set(SOURCE_ORDER), context=f"{context}.source_overlap_unique"
    )
    for source in SOURCE_ORDER:
        if source_unique[source] > functional_overlap:
            raise CoverageManifestError(
                f"{context}.source_overlap_unique[{source!r}] exceeds {context}.functional_overlap_unique"
            )
    if "source_membership_patterns" in cohort:
        patterns = _require_exact_keys(
            cohort["source_membership_patterns"], set(_SOURCE_MEMBERSHIP_PATTERN_KEYS),
            context=f"{context}.source_membership_patterns",
        )
        if sum(patterns.values()) != functional_overlap:
            raise CoverageManifestError(
                f"{context}.source_membership_patterns values do not sum to {functional_overlap!r}"
            )
        for source in SOURCE_ORDER:
            if _pattern_membership_sum(patterns, source) != source_unique[source]:
                raise CoverageManifestError(
                    f"{context}.source_membership_patterns does not reconstruct "
                    f"source_overlap_unique[{source!r}]"
                )


def _validate_coverage_statistics(stats: dict[str, Any], *, counts: dict[str, Any]) -> None:
    """Enforce the exact nested key vocabulary of every
    ``coverage_statistics`` sub-object, tie ``counts.rows`` to
    ``functional.unique_spdi``, and re-derive every source-membership/
    cohort-overlap/leakage-marker aggregate from its own constituent
    parts -- never trusting a single top-level count in isolation."""
    _require_exact_keys(stats, _REQUIRED_STATISTICS_KEYS, context="coverage_statistics")

    functional = _require_exact_keys(
        stats["functional"],
        {"verified_observations", "unique_spdi", "source_unique", "source_membership_patterns"},
        context="coverage_statistics.functional",
    )
    if functional["unique_spdi"] != counts["rows"]:
        raise CoverageManifestError("coverage_statistics.functional.unique_spdi does not match manifest.counts.rows")
    source_unique = _require_exact_keys(
        functional["source_unique"], set(SOURCE_ORDER), context="coverage_statistics.functional.source_unique"
    )
    if sum(source_unique.values()) != functional["verified_observations"]:
        raise CoverageManifestError(
            "coverage_statistics.functional.source_unique values do not sum to verified_observations"
        )
    patterns = _require_exact_keys(
        functional["source_membership_patterns"], set(_SOURCE_MEMBERSHIP_PATTERN_KEYS),
        context="coverage_statistics.functional.source_membership_patterns",
    )
    if sum(patterns.values()) != functional["unique_spdi"]:
        raise CoverageManifestError(
            "coverage_statistics.functional.source_membership_patterns values do not sum to unique_spdi"
        )
    for source in SOURCE_ORDER:
        if _pattern_membership_sum(patterns, source) != source_unique[source]:
            raise CoverageManifestError(
                f"coverage_statistics.functional.source_membership_patterns does not reconstruct "
                f"source_unique[{source!r}]"
            )

    cohorts = _require_exact_keys(
        stats["cohorts"], {"vus", "priority", "prospective_holdout", "atlas_contrast", "atlas_anchor"},
        context="coverage_statistics.cohorts",
    )
    for cohort_name, key_set in (
        ("vus", _COHORT_KEYS_WITH_SOURCE_PATTERNS),
        ("prospective_holdout", _COHORT_KEYS_WITH_SOURCE_PATTERNS),
        ("atlas_contrast", _ATLAS_CONTRAST_COHORT_KEYS),
        ("atlas_anchor", _ATLAS_ANCHOR_COHORT_KEYS),
    ):
        cohort = _require_exact_keys(cohorts[cohort_name], key_set, context=f"coverage_statistics.cohorts.{cohort_name}")
        _validate_source_dicts(
            cohort, context=f"coverage_statistics.cohorts.{cohort_name}",
            functional_overlap=cohort["functional_overlap_unique"],
        )
    priority_cohort = _require_keys_with_optional(
        cohorts["priority"], _PRIORITY_COHORT_REQUIRED_KEYS, _PRIORITY_COHORT_OPTIONAL_KEYS,
        context="coverage_statistics.cohorts.priority",
    )
    _validate_source_dicts(
        priority_cohort, context="coverage_statistics.cohorts.priority",
        functional_overlap=priority_cohort["functional_overlap_unique"],
    )
    if priority_cohort["candidate_LP_review"] + priority_cohort["candidate_LB_review"] != priority_cohort["identities"]:
        raise CoverageManifestError(
            "coverage_statistics.cohorts.priority: candidate_LP_review + candidate_LB_review != identities"
        )
    if priority_cohort["candidate_LP_review"] > priority_cohort["identities"]:
        raise CoverageManifestError(
            "coverage_statistics.cohorts.priority.candidate_LP_review exceeds identities"
        )
    if priority_cohort["candidate_LB_review"] > priority_cohort["identities"]:
        raise CoverageManifestError(
            "coverage_statistics.cohorts.priority.candidate_LB_review exceeds identities"
        )
    if (
        priority_cohort["candidate_LP_review_overlap"] + priority_cohort["candidate_LB_review_overlap"]
        != priority_cohort["functional_overlap_unique"]
    ):
        raise CoverageManifestError(
            "coverage_statistics.cohorts.priority: candidate_LP_review_overlap + "
            "candidate_LB_review_overlap != functional_overlap_unique"
        )
    if priority_cohort["candidate_LP_review_overlap"] > priority_cohort["candidate_LP_review"]:
        raise CoverageManifestError(
            "coverage_statistics.cohorts.priority.candidate_LP_review_overlap exceeds candidate_LP_review"
        )
    if priority_cohort["candidate_LB_review_overlap"] > priority_cohort["candidate_LB_review"]:
        raise CoverageManifestError(
            "coverage_statistics.cohorts.priority.candidate_LB_review_overlap exceeds candidate_LB_review"
        )

    for cohort_name in ("vus", "priority", "prospective_holdout"):
        cohort = cohorts[cohort_name]
        if cohort["TSC1"] + cohort["TSC2"] != cohort["identities"]:
            raise CoverageManifestError(f"coverage_statistics.cohorts.{cohort_name}: TSC1 + TSC2 != identities")
        if cohort["functional_overlap_unique"] > cohort["identities"]:
            raise CoverageManifestError(
                f"coverage_statistics.cohorts.{cohort_name}.functional_overlap_unique exceeds identities"
            )
        if cohort["functional_overlap_unique"] > functional["unique_spdi"]:
            raise CoverageManifestError(
                f"coverage_statistics.cohorts.{cohort_name}.functional_overlap_unique exceeds "
                "functional.unique_spdi"
            )
    if cohorts["atlas_contrast"]["functional_overlap_unique"] > cohorts["atlas_contrast"]["resolved_unique_spdi"]:
        raise CoverageManifestError(
            "coverage_statistics.cohorts.atlas_contrast.functional_overlap_unique exceeds resolved_unique_spdi"
        )
    if cohorts["atlas_anchor"]["functional_overlap_unique"] > cohorts["atlas_anchor"]["identities"]:
        raise CoverageManifestError(
            "coverage_statistics.cohorts.atlas_anchor.functional_overlap_unique exceeds identities"
        )
    if cohorts["atlas_anchor"]["prospective_holdout_overlap"] > cohorts["atlas_anchor"]["functional_overlap_unique"]:
        raise CoverageManifestError(
            "coverage_statistics.cohorts.atlas_anchor.prospective_holdout_overlap exceeds "
            "functional_overlap_unique"
        )

    cross_cohort = _require_exact_keys(
        stats["cross_cohort"], _CROSS_COHORT_KEYS, context="coverage_statistics.cross_cohort"
    )
    if cross_cohort["vus__prospective_holdout"] != 0:
        raise CoverageManifestError(
            "coverage_statistics.cross_cohort.vus__prospective_holdout must be exactly 0 (VUS and "
            "prospective-holdout are disjoint)"
        )
    if cross_cohort["priority__prospective_holdout"] != 0:
        raise CoverageManifestError(
            "coverage_statistics.cross_cohort.priority__prospective_holdout must be exactly 0 "
            "(priority is a subset of VUS, which is disjoint from prospective-holdout)"
        )

    vus_identities = cohorts["vus"]["identities"]
    priority_identities = cohorts["priority"]["identities"]
    holdout_identities = cohorts["prospective_holdout"]["identities"]
    atlas_resolved = cohorts["atlas_contrast"]["resolved_unique_spdi"]
    if cross_cohort["vus__atlas_contrast"] > min(vus_identities, atlas_resolved):
        raise CoverageManifestError(
            "coverage_statistics.cross_cohort.vus__atlas_contrast exceeds min(cohorts.vus.identities, "
            "cohorts.atlas_contrast.resolved_unique_spdi)"
        )
    if cross_cohort["prospective_holdout__atlas_contrast"] > min(holdout_identities, atlas_resolved):
        raise CoverageManifestError(
            "coverage_statistics.cross_cohort.prospective_holdout__atlas_contrast exceeds "
            "min(cohorts.prospective_holdout.identities, cohorts.atlas_contrast.resolved_unique_spdi)"
        )
    if cross_cohort["priority__atlas_contrast"] > min(
        priority_identities, atlas_resolved, cross_cohort["vus__atlas_contrast"]
    ):
        raise CoverageManifestError(
            "coverage_statistics.cross_cohort.priority__atlas_contrast exceeds "
            "min(cohorts.priority.identities, cohorts.atlas_contrast.resolved_unique_spdi, "
            "cross_cohort.vus__atlas_contrast)"
        )

    vus_functional_overlap = cohorts["vus"]["functional_overlap_unique"]
    holdout_functional_overlap = cohorts["prospective_holdout"]["functional_overlap_unique"]
    atlas_functional_overlap = cohorts["atlas_contrast"]["functional_overlap_unique"]
    if cross_cohort["functional__vus__atlas_contrast"] > min(
        vus_functional_overlap, atlas_functional_overlap, cross_cohort["vus__atlas_contrast"]
    ):
        raise CoverageManifestError(
            "coverage_statistics.cross_cohort.functional__vus__atlas_contrast exceeds "
            "min(cohorts.vus.functional_overlap_unique, cohorts.atlas_contrast.functional_overlap_unique, "
            "cross_cohort.vus__atlas_contrast)"
        )
    if cross_cohort["functional__prospective_holdout__atlas_contrast"] > min(
        holdout_functional_overlap, atlas_functional_overlap, cross_cohort["prospective_holdout__atlas_contrast"]
    ):
        raise CoverageManifestError(
            "coverage_statistics.cross_cohort.functional__prospective_holdout__atlas_contrast exceeds "
            "min(cohorts.prospective_holdout.functional_overlap_unique, cohorts.atlas_contrast."
            "functional_overlap_unique, cross_cohort.prospective_holdout__atlas_contrast)"
        )
    expected_outside = (
        atlas_functional_overlap
        - cross_cohort["functional__vus__atlas_contrast"]
        - cross_cohort["functional__prospective_holdout__atlas_contrast"]
    )
    if cross_cohort["functional__atlas_contrast_outside_vus_holdout"] != expected_outside:
        raise CoverageManifestError(
            "coverage_statistics.cross_cohort.functional__atlas_contrast_outside_vus_holdout does not "
            "equal cohorts.atlas_contrast.functional_overlap_unique - cross_cohort."
            "functional__vus__atlas_contrast - cross_cohort.functional__prospective_holdout__atlas_contrast "
            "(VUS/holdout are disjoint, so the Atlas functional overlap partitions exactly into these "
            "three exclusive categories)"
        )

    membership_patterns = _require_exact_keys(
        stats["functional_cohort_membership_patterns"], set(_FUNCTIONAL_COHORT_MEMBERSHIP_PATTERN_KEYS),
        context="coverage_statistics.functional_cohort_membership_patterns",
    )
    if sum(membership_patterns.values()) != functional["unique_spdi"]:
        raise CoverageManifestError(
            "coverage_statistics.functional_cohort_membership_patterns values do not sum to "
            "functional.unique_spdi"
        )

    _both_markers_key = "+".join(LEAKAGE_MARKER_ORDER)
    leakage_marker_keys = {LEAKAGE_MARKER_ORDER[0], LEAKAGE_MARKER_ORDER[1], _both_markers_key}
    leakage = _require_exact_keys(
        stats["leakage_markers"], leakage_marker_keys, context="coverage_statistics.leakage_markers"
    )
    expected_holdout_leakage = (
        membership_patterns["PROSPECTIVE_HOLDOUT"]
        + membership_patterns["PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST"]
        + membership_patterns["PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR"]
    )
    if leakage["PROSPECTIVE_HOLDOUT"] != expected_holdout_leakage:
        raise CoverageManifestError(
            "coverage_statistics.leakage_markers.PROSPECTIVE_HOLDOUT is not derived from "
            "functional_cohort_membership_patterns"
        )
    expected_atlas_leakage = (
        membership_patterns["VUS+ATLAS_CONTRAST"]
        + membership_patterns["PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST"]
        + membership_patterns["PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR"]
        + membership_patterns["ATLAS_CONTRAST"]
    )
    if leakage["ATLAS_CONTEXT"] != expected_atlas_leakage:
        raise CoverageManifestError(
            "coverage_statistics.leakage_markers.ATLAS_CONTEXT is not derived from "
            "functional_cohort_membership_patterns"
        )
    expected_both_leakage = (
        membership_patterns["PROSPECTIVE_HOLDOUT+ATLAS_CONTRAST"] + membership_patterns["PROSPECTIVE_HOLDOUT+ATLAS_ANCHOR"]
    )
    both_key = _both_markers_key
    if leakage[both_key] != expected_both_leakage:
        raise CoverageManifestError(
            f"coverage_statistics.leakage_markers[{both_key!r}] is not derived from "
            "functional_cohort_membership_patterns"
        )


def _validate_artifact_record(artifact: Any, *, index: int) -> None:
    if not isinstance(artifact, dict) or set(artifact) != _REQUIRED_ARTIFACT_FIELDS:
        raise CoverageManifestError(
            f"manifest.artifacts[{index}] must have exactly the fields {sorted(_REQUIRED_ARTIFACT_FIELDS)!r}"
        )
    if not isinstance(artifact["artifact_id"], str) or not artifact["artifact_id"]:
        raise CoverageManifestError(f"manifest.artifacts[{index}].artifact_id must be a non-empty string")
    if not isinstance(artifact["relative_path"], str) or not artifact["relative_path"]:
        raise CoverageManifestError(f"manifest.artifacts[{index}].relative_path must be a non-empty string")
    if artifact["artifact_id"] not in _CANONICAL_ARTIFACT_RELATIVE_PATHS:
        raise CoverageManifestError(
            f"manifest.artifacts[{index}].artifact_id {artifact['artifact_id']!r} is not one of the "
            f"whitelisted artifact_ids {sorted(_CANONICAL_ARTIFACT_RELATIVE_PATHS)!r}"
        )
    expected_relative_path = _CANONICAL_ARTIFACT_RELATIVE_PATHS[artifact["artifact_id"]]
    if artifact["relative_path"] != expected_relative_path:
        raise CoverageManifestError(
            f"manifest.artifacts[{index}].relative_path {artifact['relative_path']!r} does not match "
            f"the whitelisted relative_path {expected_relative_path!r} for artifact_id "
            f"{artifact['artifact_id']!r}"
        )
    if not isinstance(artifact["sha256"], str) or not _SHA256_HEX_RE.match(artifact["sha256"]):
        raise CoverageManifestError(f"manifest.artifacts[{index}].sha256 must be a 64-hex-digit string")
    _require_nonneg_int(artifact["byte_length"], context=f"manifest.artifacts[{index}].byte_length")
    _require_nonneg_int(artifact["row_count"], context=f"manifest.artifacts[{index}].row_count")


def _validate_manifest_contract(manifest: dict[str, Any], *, require_content_hash: bool) -> None:
    expected_fields = _REQUIRED_MANIFEST_FIELDS if require_content_hash else _REQUIRED_MANIFEST_FIELDS_NO_HASH
    if set(manifest) != expected_fields:
        missing = expected_fields - set(manifest)
        extra = set(manifest) - expected_fields
        raise CoverageManifestError(
            f"manifest does not have the exact required fields; missing={sorted(missing)!r} "
            f"extra={sorted(extra)!r}"
        )
    if manifest["schema"] != BUNDLE_SCHEMA:
        raise CoverageManifestError(f"manifest schema must be {BUNDLE_SCHEMA!r}, got {manifest['schema']!r}")
    if not isinstance(manifest["bundle_id"], str) or not manifest["bundle_id"]:
        raise CoverageManifestError("manifest.bundle_id must be a non-empty string")
    if not isinstance(manifest["created_at"], str) or not manifest["created_at"]:
        raise CoverageManifestError("manifest.created_at must be a non-empty string")

    input_manifests = manifest["input_manifests"]
    if not isinstance(input_manifests, dict) or set(input_manifests) != _REQUIRED_INPUT_MANIFEST_KEYS:
        raise CoverageManifestError(
            f"manifest.input_manifests must have exactly the keys {sorted(_REQUIRED_INPUT_MANIFEST_KEYS)!r}"
        )
    for key, value in input_manifests.items():
        if not isinstance(value, str) or not _SHA256_HEX_RE.match(value):
            raise CoverageManifestError(f"manifest.input_manifests[{key!r}] must be a 64-hex-digit string")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise CoverageManifestError("manifest.artifacts must be a non-empty list")
    seen_artifact_ids: set[str] = set()
    total_row_count = 0
    for index, artifact in enumerate(artifacts):
        _validate_artifact_record(artifact, index=index)
        if artifact["artifact_id"] in seen_artifact_ids:
            raise CoverageManifestError(f"duplicate artifact_id {artifact['artifact_id']!r} in manifest.artifacts")
        seen_artifact_ids.add(artifact["artifact_id"])
        total_row_count += artifact["row_count"]
    if seen_artifact_ids != set(_CANONICAL_ARTIFACT_RELATIVE_PATHS):
        missing_ids = set(_CANONICAL_ARTIFACT_RELATIVE_PATHS) - seen_artifact_ids
        raise CoverageManifestError(
            f"manifest.artifacts must contain exactly the whitelisted artifact_id(s) "
            f"{sorted(_CANONICAL_ARTIFACT_RELATIVE_PATHS)!r}; missing={sorted(missing_ids)!r}"
        )

    counts = manifest["counts"]
    if not isinstance(counts, dict) or set(counts) != {"rows", "artifacts"}:
        raise CoverageManifestError("manifest.counts must have exactly the fields 'rows'/'artifacts'")
    _require_nonneg_int(counts["rows"], context="manifest.counts.rows")
    _require_nonneg_int(counts["artifacts"], context="manifest.counts.artifacts")
    if total_row_count != counts["rows"]:
        raise CoverageManifestError(
            f"sum of artifact row_count values {total_row_count!r} does not match manifest.counts.rows "
            f"{counts['rows']!r}"
        )
    if len(artifacts) != counts["artifacts"]:
        raise CoverageManifestError(
            f"len(manifest.artifacts) {len(artifacts)!r} does not match manifest.counts.artifacts "
            f"{counts['artifacts']!r}"
        )

    coverage_statistics = manifest["coverage_statistics"]
    if not isinstance(coverage_statistics, dict) or set(coverage_statistics) != _REQUIRED_STATISTICS_KEYS:
        raise CoverageManifestError(
            f"manifest.coverage_statistics must have exactly the keys {sorted(_REQUIRED_STATISTICS_KEYS)!r}"
        )
    _validate_numeric_leaves(coverage_statistics, context="manifest.coverage_statistics")
    _validate_coverage_statistics(coverage_statistics, counts=counts)

    if manifest["boundaries"] != _REQUIRED_BOUNDARIES:
        raise CoverageManifestError(
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
    """Raise ``CoverageManifestError`` if the manifest violates its own
    schema/whitelist invariants, or if ``manifest['content_hash']`` does
    not match the manifest's recomputed canonical content hash."""
    _validate_manifest_contract(manifest, require_content_hash=True)
    recomputed = compute_manifest_content_hash(manifest)
    if recomputed != manifest["content_hash"]:
        raise CoverageManifestError(
            f"coverage manifest content_hash mismatch: recorded {manifest['content_hash']!r} != "
            f"recomputed {recomputed!r}"
        )


def build_coverage_bundle_manifest(
    *,
    bundle_id: str,
    created_at: str,
    input_manifests: dict[str, str],
    artifacts: list[dict[str, Any]],
    counts: dict[str, Any],
    coverage_statistics: dict[str, Any],
    boundaries: dict[str, Any],
) -> dict[str, Any]:
    """Build, validate and canonically self-hash a
    ``raptor.external.tsc2_functional_coverage_bundle.v1`` manifest. The
    manifest's statistics field is ALWAYS named ``coverage_statistics`` --
    never ``expected_pilot`` (the frozen pilot expectation is compared
    generically by the operator's own gate, never embedded here). Raises
    ``CoverageManifestError`` if the assembled manifest violates its
    schema/whitelist invariants."""
    manifest: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "bundle_id": bundle_id,
        "created_at": created_at,
        "input_manifests": dict(input_manifests),
        "artifacts": [dict(artifact) for artifact in artifacts],
        "counts": dict(counts),
        "coverage_statistics": coverage_statistics,
        "boundaries": dict(boundaries),
    }
    _validate_manifest_contract(manifest, require_content_hash=False)
    manifest["content_hash"] = compute_manifest_content_hash(manifest)
    return manifest


# ---------------------------------------------------------------------------
# Path safety + publication.
# ---------------------------------------------------------------------------


def _is_symlink_or_reparse_point(path: Path) -> bool:
    """True iff ``path`` is a POSIX symlink, a Windows junction, or
    otherwise carries ``FILE_ATTRIBUTE_REPARSE_POINT`` -- checked via
    lstat-style calls that never follow the link. Exposed at module scope
    (and always called through this bare name, never an indirection) so
    tests can monkeypatch it directly."""
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
        raise CoverageBundleBoundaryError(f"unable to inspect {path} for a symlink/reparse point: {exc}") from exc
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", None)
    file_attributes = getattr(st, "st_file_attributes", None)
    return bool(file_attributes is not None and reparse_attribute is not None and file_attributes & reparse_attribute)


def _assert_no_reparse_ancestry(path: Path, *, role: str) -> None:
    """Reject a symlink/reparse point anywhere from the filesystem anchor
    down to ``path`` itself, walking lexically (never ``resolve()``) so
    an aliased ancestor of a caller-supplied root can't hide behind the
    root itself not being a symlink."""
    path = Path(path)
    if not path.is_absolute():
        path = Path.cwd() / path
    current = Path(path.anchor)
    if _is_symlink_or_reparse_point(current):
        raise CoverageBundleBoundaryError(
            f"{role} path {path} has a symlink/reparse ancestor at {current}; refusing for safety"
        )
    for part in path.parts[1:]:
        current = current / part
        if _is_symlink_or_reparse_point(current):
            raise CoverageBundleBoundaryError(
                f"{role} path {path} has a symlink/reparse ancestor at {current}; refusing for safety"
            )


def _cleanup_staging_dir(staging_dir: Path) -> None:
    """Remove ``staging_dir`` (a directory this process itself created and
    is solely responsible for). Raises ``CoverageBundleBoundaryError``
    naming the staging-cleanup failure on any ``OSError`` -- never a
    silently-swallowed ``ignore_errors=True`` removal. A concurrently-
    vanished directory (``FileNotFoundError``) is not an error."""
    try:
        shutil.rmtree(staging_dir)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise CoverageBundleBoundaryError(
            f"staging cleanup failed: unable to remove staging directory {staging_dir}: {exc}"
        ) from exc


def publish_coverage_bundle(
    *,
    repo_root: Path,
    output_root: Path,
    run_name: str,
    manifest: dict[str, Any],
    artifact_payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Publish ``manifest`` and ``artifact_payloads`` (keyed by
    ``relative_path``) to ``output_root/run_name`` -- external, create-
    only, atomic and symlink-safe. Every artifact is written into a
    staging directory first (via the bare, monkeypatchable
    ``_write_bytes_exclusive``), the manifest is written into staging
    LAST, and only then is the whole staging directory published onto
    the (never pre-existing) final run path via the reused, verbatim
    ``raptor.external.tsc2_sources.bundle._publish_directory_no_replace``.
    A single ``finally`` spanning both the staging-write phase and the
    publish phase removes ``staging_dir`` if it still exists -- a
    successful atomic rename has already moved it onto ``final_run_dir``,
    so that cleanup is a no-op on the success path. Only
    ``_SourceBundleBoundaryError`` (staging writes), ``FileExistsError``
    and ``OSError`` (the publish rename) are translated into this
    module's own boundary error; any other exception (e.g. a payload/
    hash mismatch) propagates unchanged after cleanup. A competing
    writer's already-published final directory is never deleted/
    replaced/touched."""
    validate_manifest_content_hash(manifest)

    repo_root = Path(repo_root)
    output_root = Path(output_root)

    try:
        _validate_run_name(run_name)
    except _SourceBundleBoundaryError as exc:
        raise CoverageBundleBoundaryError(str(exc)) from exc

    _assert_no_reparse_ancestry(output_root, role="output_root")

    resolved_repo_root = repo_root.resolve()
    resolved_output_root = output_root.resolve()
    try:
        resolved_output_root.relative_to(resolved_repo_root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    if inside_repo:
        raise CoverageBundleBoundaryError(
            f"output_root {output_root} resolves inside repo_root {repo_root}; the external coverage "
            "bundle must never be written inside the repository"
        )

    final_run_dir = output_root / run_name
    if _is_symlink_or_reparse_point(final_run_dir) or final_run_dir.exists():
        raise CoverageBundleBoundaryError(
            f"output run path {final_run_dir} already exists (or is a symlink/reparse point); runs "
            "are create-only and are never overwritten or silently resumed"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_ancestry(output_root, role="output_root")

    try:
        reservation_path = _reserve_run_name(output_root, run_name)
    except _SourceBundleBoundaryError as exc:
        raise CoverageBundleBoundaryError(str(exc)) from exc

    try:
        if _is_symlink_or_reparse_point(final_run_dir) or final_run_dir.exists():
            raise CoverageBundleBoundaryError(
                f"output run path {final_run_dir} already exists (or is a symlink/reparse point); "
                "runs are create-only and are never overwritten or silently resumed"
            )

        staging_dir = output_root / f".{run_name}.staging-{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=False, exist_ok=False)

        try:
            try:
                created_files: list[Path] = []
                for artifact in manifest["artifacts"]:
                    relative_path = artifact["relative_path"]
                    payload = artifact_payloads.get(relative_path)
                    if payload is None:
                        raise CoverageManifestError(
                            f"missing coverage artifact payload bytes for relative_path {relative_path!r}"
                        )
                    if len(payload) != artifact["byte_length"]:
                        raise CoverageManifestError(
                            f"artifact {relative_path!r} byte_length mismatch: expected "
                            f"{artifact['byte_length']!r}, observed {len(payload)!r} bytes"
                        )
                    observed_sha256 = hashlib.sha256(payload).hexdigest()
                    if observed_sha256.lower() != artifact["sha256"].lower():
                        raise CoverageManifestError(
                            f"artifact {relative_path!r} sha256 mismatch: expected {artifact['sha256']!r}, "
                            f"observed {observed_sha256!r}"
                        )
                    destination = _safe_join(staging_dir, relative_path)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    _write_bytes_exclusive(destination, payload, created_files)

                manifest_bytes = json.dumps(
                    manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
                _write_bytes_exclusive(staging_dir / MANIFEST_FILENAME, manifest_bytes, created_files)
            except _SourceBundleBoundaryError as exc:
                raise CoverageBundleBoundaryError(str(exc)) from exc

            try:
                _publish_directory_no_replace(staging_dir, final_run_dir)
            except FileExistsError as exc:
                raise CoverageBundleBoundaryError(
                    f"output run path {final_run_dir} was concurrently created by another writer during "
                    "publication; refusing to replace a competing publication"
                ) from exc
            except OSError as exc:
                raise CoverageBundleBoundaryError(
                    f"failed to atomically publish run directory {final_run_dir}: {exc}"
                ) from exc
        finally:
            # A successful atomic rename has already moved staging_dir onto
            # final_run_dir -- there is no longer a path here to remove. On
            # any failure (translated or not), remove whatever staging
            # content this process itself created; a competing writer's
            # already-published final directory is never touched.
            if staging_dir.exists():
                _cleanup_staging_dir(staging_dir)
    finally:
        _release_reservation(reservation_path)

    return {"run_dir": str(final_run_dir), "manifest_path": str(final_run_dir / MANIFEST_FILENAME)}


# ---------------------------------------------------------------------------
# Committed summary (aggregate-only whitelist projection).
# ---------------------------------------------------------------------------


def build_committed_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the compact, aggregate-only committed summary from an
    already-built coverage manifest: pins/hashes, output artifact
    integrity, and the manifest's ``coverage_statistics`` sub-objects
    flattened to the top level. NEVER includes a per-row identity, SPDI/
    HGVS/VCF-key string, raw score, source functional class, or any
    clinical/evidence-strength claim (enforced structurally: this
    function is a strict field-whitelist projection). Always fully
    re-validates ``manifest`` (schema/whitelist invariants AND its own
    recomputed ``content_hash``) via ``validate_manifest_content_hash``
    BEFORE projecting any field."""
    validate_manifest_content_hash(manifest)

    stats = manifest["coverage_statistics"]
    output_artifacts = [
        {
            "artifact_id": artifact["artifact_id"],
            "relative_path": artifact["relative_path"],
            "sha256": artifact["sha256"],
            "byte_length": artifact["byte_length"],
            "row_count": artifact["row_count"],
        }
        for artifact in manifest["artifacts"]
    ]

    return {
        "schema": SUMMARY_SCHEMA,
        "bundle_id": manifest["bundle_id"],
        "manifest_content_hash": manifest["content_hash"],
        "input_hashes": dict(manifest["input_manifests"]),
        "functional": dict(stats["functional"]),
        "cohorts": stats["cohorts"],
        "cross_cohort": dict(stats["cross_cohort"]),
        "functional_cohort_membership_patterns": dict(stats["functional_cohort_membership_patterns"]),
        "leakage_markers": dict(stats["leakage_markers"]),
        "output_artifacts": output_artifacts,
        "boundaries": dict(manifest["boundaries"]),
    }


__all__ = [
    "BUNDLE_SCHEMA",
    "SUMMARY_SCHEMA",
    "CoverageBundleBoundaryError",
    "CoverageManifestError",
    "canonical_coverage_jsonl_bytes",
    "compute_manifest_content_hash",
    "validate_manifest_content_hash",
    "build_coverage_bundle_manifest",
    "publish_coverage_bundle",
    "build_committed_summary",
    "_publish_directory_no_replace",
    "_is_symlink_or_reparse_point",
    "_write_bytes_exclusive",
]
