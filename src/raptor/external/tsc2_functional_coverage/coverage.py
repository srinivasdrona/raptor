"""RAPTOR v2 TSC2 functional coverage map -- exact-SPDI join, output-row
construction and full-cohort coverage statistics.

``build_functional_coverage_rows`` fully re-validates every functional row
through ``raptor.external.tsc2_functional.model.NormalizedFunctionalRow``
(never trusting a caller's pre-validated shape) and keeps only rows whose
``identity_state`` is ``GENOMIC_SPDI_VERIFIED`` -- score_raw and
functional class are read only as part of that schema revalidation and
are NEVER consulted for any coverage/priority/leakage decision or emitted
in the output row (a raw-score mutation on an otherwise-identical row set
never changes the built coverage rows). Every join (VUS/priority/
prospective-holdout/Atlas-contrast/Atlas-anchor membership) is EXACT
string-equality only -- no trim, case-fold or liftover. The full VUS and
prospective-holdout identity sets must be disjoint; any intersection
aborts the whole run before a single row is built.

``compute_coverage_statistics`` computes every cohort/source/cross-cohort/
leakage-marker aggregate from the full validated cohort sets (never only
the rows that happen to have functional coverage), so a cohort's
``identities``/gene counts reflect its ENTIRE frozen manifest, while its
``functional_overlap_unique``/source-membership aggregates reflect only
those cohort identities that are ALSO present in the built coverage rows.

``validate_expected_pilot_counts`` is a generic, non-hardcoded structural
equality gate: it never encodes an expected pilot literal itself, it only
compares an already-computed statistics mapping against a caller-supplied
expectation.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb`` or
``raptor.rescuescreen``.
"""
from __future__ import annotations

from typing import Any

from raptor.external.tsc2_functional.model import (
    NormalizationContractError,
    NormalizedFunctionalRow,
)

from .model import (
    LEAKAGE_MARKER_ORDER,
    SOURCE_ORDER,
    CoverageContractError,
    FunctionalCoverageRow,
)

_VERIFIED_IDENTITY_STATE = "GENOMIC_SPDI_VERIFIED"

#: The only allowed ``priority_by_spdi`` stratum values.
_PRIORITY_STRATA = frozenset({"candidate_LP_review", "candidate_LB_review"})

#: Fixed, ordered functional-cohort-membership flag vocabulary (never a
#: hardcoded expected COUNT -- only the flag ordering used to build each
#: coverage row's membership-pattern key).
_MEMBERSHIP_FLAG_ORDER = ("VUS", "PROSPECTIVE_HOLDOUT", "ATLAS_CONTRAST", "ATLAS_ANCHOR")


class CoverageBuildError(RuntimeError):
    """Raised for any functional-row schema-revalidation failure, a VUS/
    prospective-holdout identity-set intersection, or any other join/
    output-row-construction invariant violation."""


def _source_membership_key(source_ids: list[str]) -> str:
    return "+".join(source_ids)


def build_functional_coverage_rows(
    *,
    functional_rows: list[dict[str, Any]],
    vus_spdis: set[str],
    priority_by_spdi: dict[str, str],
    prospective_holdout_spdis: set[str],
    atlas_contrast_spdis: set[str],
    atlas_anchor_spdi: str | None,
    source_order: tuple[str, ...] | list[str] = SOURCE_ORDER,
    leakage_marker_order: tuple[str, ...] | list[str] = LEAKAGE_MARKER_ORDER,
) -> list[dict[str, Any]]:
    """Fully re-validate every functional row, keep only
    ``GENOMIC_SPDI_VERIFIED`` rows, join them by exact-string-equality SPDI
    to the VUS/priority/prospective-holdout/Atlas-contrast/Atlas-anchor
    cohorts, and return one ``FunctionalCoverageRow.to_dict()`` per unique
    verified SPDI, sorted lexicographically by ``spdi``. Raises
    ``CoverageBuildError`` if the VUS and prospective-holdout identity sets
    intersect, if ``priority_by_spdi`` is not an exact subset of
    ``vus_spdis`` or carries a value outside its fixed vocabulary, or on
    any row-construction invariant violation."""
    if vus_spdis & prospective_holdout_spdis:
        overlap = sorted(vus_spdis & prospective_holdout_spdis)[:5]
        raise CoverageBuildError(
            f"VUS and prospective-holdout identity sets must be disjoint; found intersection "
            f"(sample): {overlap!r}"
        )
    if not set(priority_by_spdi).issubset(vus_spdis):
        outside_vus = sorted(set(priority_by_spdi) - vus_spdis)[:5]
        raise CoverageBuildError(
            f"priority_by_spdi contains SPDI(s) outside the VUS universe (sample): {outside_vus!r}"
        )
    invalid_strata = {stratum for stratum in priority_by_spdi.values() if stratum not in _PRIORITY_STRATA}
    if invalid_strata:
        raise CoverageBuildError(f"priority_by_spdi contains invalid stratum value(s): {sorted(invalid_strata)!r}")

    sources_by_spdi: dict[str, set[str]] = {}
    for row in functional_rows:
        try:
            validated = NormalizedFunctionalRow(**row).to_dict()
        except (NormalizationContractError, TypeError) as exc:
            raise CoverageBuildError(f"functional row failed schema revalidation: {exc}") from exc
        if validated["identity_state"] != _VERIFIED_IDENTITY_STATE:
            continue
        spdi = validated["spdi"]
        source_id = validated["source_id"]
        sources_by_spdi.setdefault(spdi, set()).add(source_id)

    output_rows: list[dict[str, Any]] = []
    for spdi in sorted(sources_by_spdi):
        observed_sources = sources_by_spdi[spdi]
        source_ids = [source_id for source_id in source_order if source_id in observed_sources]

        vus = spdi in vus_spdis
        priority_stratum = priority_by_spdi.get(spdi) if vus else None
        prospective_holdout = spdi in prospective_holdout_spdis
        atlas_contrast = spdi in atlas_contrast_spdis
        atlas_anchor = atlas_anchor_spdi is not None and spdi == atlas_anchor_spdi

        leakage_markers = [
            marker
            for marker in leakage_marker_order
            if (marker == "PROSPECTIVE_HOLDOUT" and prospective_holdout)
            or (marker == "ATLAS_CONTEXT" and (atlas_contrast or atlas_anchor))
        ]

        try:
            row = FunctionalCoverageRow(
                schema="raptor.external.tsc2_functional_coverage_row.v1",
                spdi=spdi,
                source_ids=source_ids,
                observation_count=len(source_ids),
                vus_2026_07=vus,
                priority_stratum=priority_stratum,
                prospective_holdout_2026_08=prospective_holdout,
                atlas_contrast_candidate=atlas_contrast,
                atlas_anchor_r611q=atlas_anchor,
                leakage_markers=leakage_markers,
            ).to_dict()
        except CoverageContractError as exc:
            raise CoverageBuildError(f"failed to build coverage row for spdi {spdi!r}: {exc}") from exc
        output_rows.append(row)

    return output_rows


def _empty_source_counter() -> dict[str, int]:
    return {source_id: 0 for source_id in SOURCE_ORDER}


def _empty_pattern_counter() -> dict[str, int]:
    patterns: list[str] = list(SOURCE_ORDER)
    for i in range(len(SOURCE_ORDER)):
        for j in range(i + 1, len(SOURCE_ORDER)):
            patterns.append(f"{SOURCE_ORDER[i]}+{SOURCE_ORDER[j]}")
    patterns.append("+".join(SOURCE_ORDER))
    return {pattern: 0 for pattern in patterns}


def compute_coverage_statistics(
    *,
    coverage_rows: list[dict[str, Any]],
    vus_spdis: set[str],
    priority_spdis: set[str],
    priority_by_spdi: dict[str, str],
    prospective_holdout_spdis: set[str],
    atlas_contrast_spdis: set[str],
    atlas_anchor_spdi: str | None,
    vus_gene_counts: dict[str, int],
    priority_gene_counts: dict[str, int],
    prospective_holdout_gene_counts: dict[str, int],
    atlas_raw_records: int,
    atlas_resolved_count: int,
    atlas_unresolved_count: int,
) -> dict[str, Any]:
    """Compute every functional/cohort/cross-cohort/leakage-marker
    aggregate from the FULL validated cohort sets (``vus_spdis``/
    ``priority_spdis``/``prospective_holdout_spdis``/
    ``atlas_contrast_spdis``/``atlas_anchor_spdi``) and gene counts --
    never only from ``coverage_rows`` -- so cohort identity/gene counts
    and cross-cohort intersections are correct even where a cohort
    identity has no functional coverage at all. Only the functional
    overlap/source-membership aggregates are derived from
    ``coverage_rows``. Raises ``CoverageBuildError`` if any coverage row
    fails schema revalidation, if ``priority_spdis``/``priority_by_spdi``
    disagree or violate their fixed vocabulary/VUS-subset invariant, if
    the VUS/holdout cohorts intersect, if a cohort's gene counts do not
    sum to its identity count, or if the Atlas raw/resolved/unresolved
    counts are not internally consistent."""
    validated_rows: list[dict[str, Any]] = []
    for row in coverage_rows:
        try:
            validated_rows.append(FunctionalCoverageRow(**row).to_dict())
        except (CoverageContractError, TypeError) as exc:
            raise CoverageBuildError(f"coverage row failed schema revalidation: {exc}") from exc
    coverage_rows = validated_rows

    if vus_spdis & prospective_holdout_spdis:
        raise CoverageBuildError("VUS and prospective-holdout identity sets must be disjoint")
    if set(priority_by_spdi) != set(priority_spdis):
        raise CoverageBuildError("priority_spdis and priority_by_spdi keys do not agree exactly")
    if not set(priority_by_spdi).issubset(vus_spdis):
        raise CoverageBuildError("priority_by_spdi/priority_spdis must be a subset of vus_spdis")
    invalid_strata = {stratum for stratum in priority_by_spdi.values() if stratum not in _PRIORITY_STRATA}
    if invalid_strata:
        raise CoverageBuildError(f"priority_by_spdi contains invalid stratum value(s): {sorted(invalid_strata)!r}")

    for count_name, count_value in (
        ("atlas_raw_records", atlas_raw_records),
        ("atlas_resolved_count", atlas_resolved_count),
        ("atlas_unresolved_count", atlas_unresolved_count),
    ):
        if isinstance(count_value, bool) or not isinstance(count_value, int) or count_value < 0:
            raise CoverageBuildError(f"{count_name} must be a non-negative int, got {count_value!r}")
    if atlas_raw_records != atlas_resolved_count + atlas_unresolved_count:
        raise CoverageBuildError(
            f"atlas_raw_records {atlas_raw_records!r} does not equal atlas_resolved_count + "
            f"atlas_unresolved_count ({atlas_resolved_count!r} + {atlas_unresolved_count!r})"
        )

    for cohort_name, gene_counts, identities in (
        ("vus", vus_gene_counts, vus_spdis),
        ("priority", priority_gene_counts, priority_spdis),
        ("prospective_holdout", prospective_holdout_gene_counts, prospective_holdout_spdis),
    ):
        total = sum(gene_counts.values())
        if total != len(identities):
            raise CoverageBuildError(
                f"{cohort_name} gene_counts sum to {total!r} but the cohort has {len(identities)!r} "
                "identities"
            )

    functional_source_unique = _empty_source_counter()
    functional_pattern_counts = _empty_pattern_counter()
    verified_observations = 0

    vus_overlap_rows: list[dict[str, Any]] = []
    priority_overlap_rows: list[dict[str, Any]] = []
    holdout_overlap_rows: list[dict[str, Any]] = []
    atlas_contrast_overlap_rows: list[dict[str, Any]] = []
    atlas_anchor_overlap_rows: list[dict[str, Any]] = []

    membership_patterns: dict[str, int] = {"NONE": 0}
    _both_markers_key = "+".join(LEAKAGE_MARKER_ORDER)
    leakage_counts = {
        LEAKAGE_MARKER_ORDER[0]: 0,
        LEAKAGE_MARKER_ORDER[1]: 0,
        _both_markers_key: 0,
    }

    cross_functional_vus_atlas_contrast = 0
    cross_functional_holdout_atlas_contrast = 0
    cross_functional_atlas_contrast_outside_vus_holdout = 0

    for row in coverage_rows:
        source_ids = row["source_ids"]
        verified_observations += row["observation_count"]
        for source_id in source_ids:
            functional_source_unique[source_id] += 1
        functional_pattern_counts[_source_membership_key(source_ids)] += 1

        vus = row["vus_2026_07"]
        holdout = row["prospective_holdout_2026_08"]
        atlas_contrast = row["atlas_contrast_candidate"]
        atlas_anchor = row["atlas_anchor_r611q"]

        if vus:
            vus_overlap_rows.append(row)
        if row["priority_stratum"] is not None:
            priority_overlap_rows.append(row)
        if holdout:
            holdout_overlap_rows.append(row)
        if atlas_contrast:
            atlas_contrast_overlap_rows.append(row)
        if atlas_anchor:
            atlas_anchor_overlap_rows.append(row)

        flags = [
            flag
            for flag in _MEMBERSHIP_FLAG_ORDER
            if (flag == "VUS" and vus)
            or (flag == "PROSPECTIVE_HOLDOUT" and holdout)
            or (flag == "ATLAS_CONTRAST" and atlas_contrast)
            or (flag == "ATLAS_ANCHOR" and atlas_anchor)
        ]
        pattern_key = "+".join(flags) if flags else "NONE"
        membership_patterns[pattern_key] = membership_patterns.get(pattern_key, 0) + 1

        markers = set(row["leakage_markers"])
        if LEAKAGE_MARKER_ORDER[0] in markers:
            leakage_counts[LEAKAGE_MARKER_ORDER[0]] += 1
        if LEAKAGE_MARKER_ORDER[1] in markers:
            leakage_counts[LEAKAGE_MARKER_ORDER[1]] += 1
        if markers == set(LEAKAGE_MARKER_ORDER):
            leakage_counts[_both_markers_key] += 1

        if vus and atlas_contrast:
            cross_functional_vus_atlas_contrast += 1
        if holdout and atlas_contrast:
            cross_functional_holdout_atlas_contrast += 1
        if atlas_contrast and not vus and not holdout:
            cross_functional_atlas_contrast_outside_vus_holdout += 1

    def _cohort_source_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = _empty_source_counter()
        for r in rows:
            for source_id in r["source_ids"]:
                counts[source_id] += 1
        return counts

    def _cohort_pattern_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = _empty_pattern_counter()
        for r in rows:
            counts[_source_membership_key(r["source_ids"])] += 1
        return counts

    priority_lp_overlap = sum(1 for r in priority_overlap_rows if r["priority_stratum"] == "candidate_LP_review")
    priority_lb_overlap = sum(1 for r in priority_overlap_rows if r["priority_stratum"] == "candidate_LB_review")

    priority_stratum_counts = {"candidate_LP_review": 0, "candidate_LB_review": 0}
    for stratum in priority_by_spdi.values():
        if stratum in priority_stratum_counts:
            priority_stratum_counts[stratum] += 1

    stats: dict[str, Any] = {
        "functional": {
            "verified_observations": verified_observations,
            "unique_spdi": len(coverage_rows),
            "source_unique": functional_source_unique,
            "source_membership_patterns": functional_pattern_counts,
        },
        "cohorts": {
            "vus": {
                "identities": len(vus_spdis),
                "TSC1": vus_gene_counts.get("TSC1", 0),
                "TSC2": vus_gene_counts.get("TSC2", 0),
                "functional_overlap_unique": len(vus_overlap_rows),
                "source_overlap_unique": _cohort_source_stats(vus_overlap_rows),
                "source_membership_patterns": _cohort_pattern_stats(vus_overlap_rows),
            },
            "priority": {
                "identities": len(priority_spdis),
                "candidate_LP_review": priority_stratum_counts["candidate_LP_review"],
                "candidate_LB_review": priority_stratum_counts["candidate_LB_review"],
                "TSC1": priority_gene_counts.get("TSC1", 0),
                "TSC2": priority_gene_counts.get("TSC2", 0),
                "functional_overlap_unique": len(priority_overlap_rows),
                "candidate_LP_review_overlap": priority_lp_overlap,
                "candidate_LB_review_overlap": priority_lb_overlap,
                "source_overlap_unique": _cohort_source_stats(priority_overlap_rows),
            },
            "prospective_holdout": {
                "identities": len(prospective_holdout_spdis),
                "TSC1": prospective_holdout_gene_counts.get("TSC1", 0),
                "TSC2": prospective_holdout_gene_counts.get("TSC2", 0),
                "functional_overlap_unique": len(holdout_overlap_rows),
                "source_overlap_unique": _cohort_source_stats(holdout_overlap_rows),
                "source_membership_patterns": _cohort_pattern_stats(holdout_overlap_rows),
            },
            "atlas_contrast": {
                "raw_records": atlas_raw_records,
                "resolved_unique_spdi": atlas_resolved_count,
                "unresolved_records": atlas_unresolved_count,
                "functional_overlap_unique": len(atlas_contrast_overlap_rows),
                "source_overlap_unique": _cohort_source_stats(atlas_contrast_overlap_rows),
                "source_membership_patterns": _cohort_pattern_stats(atlas_contrast_overlap_rows),
            },
            "atlas_anchor": {
                "identities": 1 if atlas_anchor_spdi is not None else 0,
                "functional_overlap_unique": len(atlas_anchor_overlap_rows),
                "source_overlap_unique": _cohort_source_stats(atlas_anchor_overlap_rows),
                "prospective_holdout_overlap": sum(
                    1 for r in atlas_anchor_overlap_rows if r["prospective_holdout_2026_08"]
                ),
            },
        },
        "cross_cohort": {
            "vus__prospective_holdout": len(vus_spdis & prospective_holdout_spdis),
            "priority__prospective_holdout": len(priority_spdis & prospective_holdout_spdis),
            "vus__atlas_contrast": len(vus_spdis & atlas_contrast_spdis),
            "priority__atlas_contrast": len(priority_spdis & atlas_contrast_spdis),
            "prospective_holdout__atlas_contrast": len(prospective_holdout_spdis & atlas_contrast_spdis),
            "functional__vus__atlas_contrast": cross_functional_vus_atlas_contrast,
            "functional__prospective_holdout__atlas_contrast": cross_functional_holdout_atlas_contrast,
            "functional__atlas_contrast_outside_vus_holdout": cross_functional_atlas_contrast_outside_vus_holdout,
        },
        "functional_cohort_membership_patterns": membership_patterns,
        "leakage_markers": leakage_counts,
    }
    return stats


def validate_expected_pilot_counts(*, computed_stats: dict[str, Any], expected_pilot: dict[str, Any]) -> None:
    """Generic, non-hardcoded recursive structural-equality gate: raises
    ``CoverageBuildError`` naming the first differing path if
    ``computed_stats`` does not exactly equal ``expected_pilot``. Scalar
    leaves are compared by EXACT type as well as value (``True != 1`` and
    ``1.0 != 1``), so a bool/float smuggled in for an expected strict int
    is always rejected. Never encodes an expected pilot literal itself."""

    def _walk(actual: Any, expected: Any, path: str) -> None:
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                raise CoverageBuildError(f"expected_pilot gate failed at {path or '<root>'}: expected a mapping")
            missing = set(expected) - set(actual)
            extra = set(actual) - set(expected)
            if missing or extra:
                raise CoverageBuildError(
                    f"expected_pilot gate failed at {path or '<root>'}: missing={sorted(missing)!r} "
                    f"extra={sorted(extra)!r}"
                )
            for key in expected:
                _walk(actual[key], expected[key], f"{path}.{key}" if path else str(key))
            return
        if type(actual) is not type(expected) or actual != expected:
            raise CoverageBuildError(
                f"expected_pilot gate failed at {path or '<root>'}: {actual!r} ({type(actual).__name__}) != "
                f"{expected!r} ({type(expected).__name__})"
            )

    _walk(computed_stats, expected_pilot, "")



__all__ = [
    "CoverageBuildError",
    "build_functional_coverage_rows",
    "compute_coverage_statistics",
    "validate_expected_pilot_counts",
]
