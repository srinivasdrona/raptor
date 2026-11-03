"""RAPTOR v2 TSC2 functional coverage map -- output row contract.

``raptor.external.tsc2_functional_coverage_row.v1`` (see the binding spec,
``docs/project/specs/raptor-v2-functional-coverage-map-v1.yaml``,
``coverage_row_contract`` section) is the exact, ten-field output row
shape this package emits: one row per verified functional SPDI, recording
only membership across cohorts (VUS/priority/prospective-holdout/Atlas
contrast/Atlas anchor) and functional source coverage -- never a raw
score, functional class, label, ACMG criterion or evidence-strength claim.

``FunctionalCoverageRow`` is a validated, frozen dataclass: construction
enforces the exact field set/domain/ordering invariants (canonical SPDI
shape restricted to the TSC1/TSC2 GRCh38 accessions, unique
``source_order``-ordered ``source_ids``, an exact ``observation_count ==
len(source_ids)``, a ``priority_stratum`` only when ``vus_2026_07`` is
true, and ``leakage_markers`` present if-and-only-if the corresponding
boolean flag(s) are true, in the fixed ``LEAKAGE_MARKER_ORDER``).
``to_dict()`` is the only representation ever handed back across this
package's public API.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any

COVERAGE_ROW_SCHEMA = "raptor.external.tsc2_functional_coverage_row.v1"

#: The exact, ordered field set every coverage row must carry (spec
#: ``coverage_row_contract.exact_fields``).
REQUIRED_COVERAGE_ROW_FIELDS: tuple[str, ...] = (
    "schema",
    "spdi",
    "source_ids",
    "observation_count",
    "vus_2026_07",
    "priority_stratum",
    "prospective_holdout_2026_08",
    "atlas_contrast_candidate",
    "atlas_anchor_r611q",
    "leakage_markers",
)

#: The exact three functional source_id values, in their fixed join/output
#: order (spec ``coverage_row_contract.source_order``).
SOURCE_ORDER: tuple[str, ...] = ("mavedb_clipe", "igvf_vamp_seq", "igvf_sge")

#: The only allowed ``priority_stratum`` values (spec
#: ``coverage_row_contract.priority_stratum_values``): ``None`` means "not
#: a member of the internal priority queue".
PRIORITY_STRATUM_VALUES: tuple[str | None, ...] = ("candidate_LP_review", "candidate_LB_review", None)

#: The fixed, ordered leakage-marker vocabulary (spec
#: ``coverage_row_contract.leakage_marker_order``).
LEAKAGE_MARKER_ORDER: tuple[str, ...] = ("PROSPECTIVE_HOLDOUT", "ATLAS_CONTEXT")

_SOURCE_ORDER_SET = frozenset(SOURCE_ORDER)
_PRIORITY_STRATUM_SET = frozenset(v for v in PRIORITY_STRATUM_VALUES if v is not None)
_LEAKAGE_MARKER_SET = frozenset(LEAKAGE_MARKER_ORDER)

#: A canonical GRCh38 SPDI restricted to the TSC1/TSC2 identity-contract
#: accessions (spec ``identity_contract``): ``<accession>:<position0>:
#: <deleted>:<inserted>`` with a non-negative integer position and
#: non-empty ACGT deleted/inserted sequences.
_SPDI_RE = re.compile(r"^(?P<accession>NC_000009\.12|NC_000016\.10):(?P<position>[0-9]+):(?P<ref>[ACGT]+):(?P<alt>[ACGT]+)$")


class CoverageContractError(ValueError):
    """Raised for any structural/schema/vocabulary/invariant violation of
    the functional coverage row contract: a non-canonical/wrong-accession
    ``spdi``, a duplicate/unordered/unknown ``source_ids`` entry, an
    ``observation_count`` that is not a strict positive int equal to
    ``len(source_ids)``, a ``priority_stratum`` present while
    ``vus_2026_07`` is false or outside its fixed vocabulary, a non-strict
    boolean flag, or a ``leakage_markers`` list that does not exactly
    reflect the ``prospective_holdout_2026_08``/``atlas_contrast_candidate``/
    ``atlas_anchor_r611q`` flags in the fixed ``LEAKAGE_MARKER_ORDER``."""


def _require_strict_bool(value: Any, *, field_name: str) -> None:
    if not isinstance(value, bool):
        raise CoverageContractError(f"{field_name} must be a strict bool, got {value!r}")


@dataclass(frozen=True)
class FunctionalCoverageRow:
    """A single validated ``raptor.external.tsc2_functional_coverage_row.v1``
    row. Construction validates the exact field set/domain/ordering
    invariants (see module docstring); ``to_dict()`` is the only shape
    handed back across this package's public API."""

    schema: str
    spdi: str
    source_ids: list[str]
    observation_count: int
    vus_2026_07: bool
    priority_stratum: str | None
    prospective_holdout_2026_08: bool
    atlas_contrast_candidate: bool
    atlas_anchor_r611q: bool
    leakage_markers: list[str]

    def __post_init__(self) -> None:
        if self.schema != COVERAGE_ROW_SCHEMA:
            raise CoverageContractError(f"schema must be {COVERAGE_ROW_SCHEMA!r}, got {self.schema!r}")

        if not isinstance(self.spdi, str) or not _SPDI_RE.match(self.spdi):
            raise CoverageContractError(
                f"spdi {self.spdi!r} is not a canonical NC_000009.12/NC_000016.10 SPDI string"
            )

        if not isinstance(self.source_ids, list) or not self.source_ids:
            raise CoverageContractError("source_ids must be a non-empty list")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise CoverageContractError(f"source_ids must not contain a duplicate entry: {self.source_ids!r}")
        if not set(self.source_ids).issubset(_SOURCE_ORDER_SET):
            unknown = sorted(set(self.source_ids) - _SOURCE_ORDER_SET)
            raise CoverageContractError(f"source_ids contains unknown source_id(s): {unknown!r}")
        expected_order = [source_id for source_id in SOURCE_ORDER if source_id in self.source_ids]
        if list(self.source_ids) != expected_order:
            raise CoverageContractError(
                f"source_ids must follow SOURCE_ORDER {SOURCE_ORDER!r}, got {self.source_ids!r}"
            )

        if isinstance(self.observation_count, bool) or not isinstance(self.observation_count, int):
            raise CoverageContractError(f"observation_count must be a strict int, got {self.observation_count!r}")
        if self.observation_count != len(self.source_ids):
            raise CoverageContractError(
                f"observation_count {self.observation_count!r} must equal len(source_ids) "
                f"{len(self.source_ids)!r}"
            )
        if self.observation_count < 1:
            raise CoverageContractError("observation_count must be a positive int")

        _require_strict_bool(self.vus_2026_07, field_name="vus_2026_07")
        _require_strict_bool(self.prospective_holdout_2026_08, field_name="prospective_holdout_2026_08")
        _require_strict_bool(self.atlas_contrast_candidate, field_name="atlas_contrast_candidate")
        _require_strict_bool(self.atlas_anchor_r611q, field_name="atlas_anchor_r611q")

        if self.priority_stratum not in _PRIORITY_STRATUM_SET and self.priority_stratum is not None:
            raise CoverageContractError(
                f"priority_stratum must be one of {PRIORITY_STRATUM_VALUES!r}, got {self.priority_stratum!r}"
            )
        if self.priority_stratum is not None and not self.vus_2026_07:
            raise CoverageContractError("priority_stratum must be null when vus_2026_07 is false")

        if not isinstance(self.leakage_markers, list):
            raise CoverageContractError("leakage_markers must be a list")
        if not set(self.leakage_markers).issubset(_LEAKAGE_MARKER_SET):
            unknown = sorted(set(self.leakage_markers) - _LEAKAGE_MARKER_SET)
            raise CoverageContractError(f"leakage_markers contains unknown marker(s): {unknown!r}")
        if len(set(self.leakage_markers)) != len(self.leakage_markers):
            raise CoverageContractError(f"leakage_markers must not contain a duplicate entry: {self.leakage_markers!r}")
        expected_markers = [
            marker
            for marker in LEAKAGE_MARKER_ORDER
            if (marker == "PROSPECTIVE_HOLDOUT" and self.prospective_holdout_2026_08)
            or (marker == "ATLAS_CONTEXT" and (self.atlas_contrast_candidate or self.atlas_anchor_r611q))
        ]
        if list(self.leakage_markers) != expected_markers:
            raise CoverageContractError(
                f"leakage_markers must be exactly {expected_markers!r} given "
                f"prospective_holdout_2026_08={self.prospective_holdout_2026_08!r}, "
                f"atlas_contrast_candidate={self.atlas_contrast_candidate!r}, "
                f"atlas_anchor_r611q={self.atlas_anchor_r611q!r}; got {self.leakage_markers!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


__all__ = [
    "COVERAGE_ROW_SCHEMA",
    "REQUIRED_COVERAGE_ROW_FIELDS",
    "SOURCE_ORDER",
    "PRIORITY_STRATUM_VALUES",
    "LEAKAGE_MARKER_ORDER",
    "CoverageContractError",
    "FunctionalCoverageRow",
]
