"""RAPTOR v2 VAMP-seq protein -> genomic SPDI crosswalk -- row contract.

``raptor.external.vamp_genomic_crosswalk_row.v1`` (see the binding spec's
``crosswalk_row`` section) is the single per-score-row output shape this
slice ever emits: exactly one row per frozen IGVF VAMP-seq score row
(``source_row`` 1..9253), a strict field set, a fixed ``status``/
``unresolved_reason`` vocabulary, and cross-field invariants tying a
``CROSSWALK_SPDI_VERIFIED`` row to a non-null, pattern-conformant
``genomic_spdi`` pinned to ``NC_000016.10`` plus its archive provenance
(``archive_member``/``archive_row``/``transcript``/``hgvs_c``), a
``SOURCE_COORDINATE_REFERENCE_MISMATCH`` row to that SAME archive
provenance but a null ``assembly``/``genomic_spdi``, and an
``ARCHIVE_CROSSWALK_ABSENT`` row to an entirely null identity/coordinate
payload.

``VampGenomicCrosswalkRow`` is a validated, frozen dataclass; ``to_dict()``
is the only representation this package's public API ever hands back.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any

#: The fixed identity pins for this entire slice (spec ``inputs``) --
#: never configurable per row/call.
SOURCE_ID = "igvf_vamp_seq"
PROTEIN_ACCESSION = "ENSP00000219476.3"
TRANSCRIPT = "NM_000548.5"
GENOMIC_ACCESSION = "NC_000016.10"
ASSEMBLY = "GRCh38"

VAMP_GENOMIC_CROSSWALK_ROW_SCHEMA = "raptor.external.vamp_genomic_crosswalk_row.v1"

REQUIRED_CROSSWALK_ROW_FIELDS: frozenset[str] = frozenset(
    {
        "schema", "source_id", "source_row", "protein_variant", "archive_member", "archive_row",
        "transcript", "hgvs_c", "assembly", "genomic_spdi", "status", "unresolved_reason",
    }
)

#: Spec ``crosswalk_row.status_values`` -- exact fixed set.
ALLOWED_CROSSWALK_STATUSES: frozenset[str] = frozenset(
    {
        "CROSSWALK_SPDI_VERIFIED",
        "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH",
        "SOURCE_COORDINATE_REFERENCE_MISMATCH",
        "ARCHIVE_CROSSWALK_ABSENT",
    }
)
#: Spec ``crosswalk_row.unresolved_reason_values`` -- exact fixed set.
ALLOWED_UNRESOLVED_REASONS: frozenset[Any] = frozenset(
    {
        None,
        "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT",
        "SOURCE_REF_DOES_NOT_MATCH_PINNED_FASTA",
        "PROTEIN_VARIANT_NOT_IN_ARCHIVE",
    }
)

_STATUS_TO_UNRESOLVED_REASON: dict[str, str | None] = {
    "CROSSWALK_SPDI_VERIFIED": None,
    "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH": "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT",
    "SOURCE_COORDINATE_REFERENCE_MISMATCH": "SOURCE_REF_DOES_NOT_MATCH_PINNED_FASTA",
    "ARCHIVE_CROSSWALK_ABSENT": "PROTEIN_VARIANT_NOT_IN_ARCHIVE",
}

#: A frozen ``NC_000016.10:<pos>:<ref>:<alt>`` verified genomic SPDI string.
_GENOMIC_SPDI_RE = re.compile(rf"^{re.escape(GENOMIC_ACCESSION)}:\d+:[ACGT]+:[ACGT]+$")


class CrosswalkContractError(ValueError):
    """Raised for any structural/schema/vocabulary/invariant violation of
    the VAMP genomic-crosswalk row contract: an unknown ``status``/
    ``unresolved_reason``, a mismatched ``status``/``unresolved_reason``
    pairing, a non-conformant ``genomic_spdi``, a ``CROSSWALK_SPDI_
    VERIFIED`` row missing its identity payload, or any other status
    carrying a field it must not."""


@dataclass(frozen=True)
class VampGenomicCrosswalkRow:
    """A single validated ``raptor.external.vamp_genomic_crosswalk_row.v1``
    row. Construction validates the exact vocabulary and cross-field
    invariants (see module docstring); ``to_dict()`` is the only shape
    handed back across this package's public API."""

    source_id: str
    source_row: int
    protein_variant: str
    archive_member: str | None
    archive_row: int | None
    transcript: str | None
    hgvs_c: str | None
    assembly: str | None
    genomic_spdi: str | None
    status: str
    unresolved_reason: str | None
    schema: str = VAMP_GENOMIC_CROSSWALK_ROW_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != VAMP_GENOMIC_CROSSWALK_ROW_SCHEMA:
            raise CrosswalkContractError(
                f"schema must be {VAMP_GENOMIC_CROSSWALK_ROW_SCHEMA!r}, got {self.schema!r}"
            )
        if self.source_id != SOURCE_ID:
            raise CrosswalkContractError(f"source_id must be {SOURCE_ID!r}, got {self.source_id!r}")
        if not isinstance(self.source_row, int) or isinstance(self.source_row, bool) or self.source_row < 1:
            raise CrosswalkContractError(f"source_row must be a one-based positive int, got {self.source_row!r}")
        if not isinstance(self.protein_variant, str) or not self.protein_variant.startswith(f"{PROTEIN_ACCESSION}:p."):
            raise CrosswalkContractError(
                f"protein_variant must retain the exact {PROTEIN_ACCESSION}:p... score token, got "
                f"{self.protein_variant!r}"
            )
        if self.status not in ALLOWED_CROSSWALK_STATUSES:
            raise CrosswalkContractError(
                f"status {self.status!r} is not one of {sorted(ALLOWED_CROSSWALK_STATUSES)!r}"
            )
        if self.unresolved_reason not in ALLOWED_UNRESOLVED_REASONS:
            raise CrosswalkContractError(
                f"unresolved_reason {self.unresolved_reason!r} is not one of "
                f"{sorted(str(v) for v in ALLOWED_UNRESOLVED_REASONS)!r}"
            )
        expected_reason = _STATUS_TO_UNRESOLVED_REASON[self.status]
        if self.unresolved_reason != expected_reason:
            raise CrosswalkContractError(
                f"status {self.status!r} requires unresolved_reason {expected_reason!r}, got "
                f"{self.unresolved_reason!r}"
            )

        if self.status == "ARCHIVE_CROSSWALK_ABSENT":
            for field_name, value in (
                ("archive_member", self.archive_member), ("archive_row", self.archive_row),
                ("transcript", self.transcript), ("hgvs_c", self.hgvs_c),
                ("assembly", self.assembly), ("genomic_spdi", self.genomic_spdi),
            ):
                if value is not None:
                    raise CrosswalkContractError(
                        f"status ARCHIVE_CROSSWALK_ABSENT must carry a null {field_name}, got {value!r}"
                    )
            return

        # Both CROSSWALK_SPDI_VERIFIED and SOURCE_COORDINATE_REFERENCE_MISMATCH
        # carry the archive provenance that was actually matched.
        if not isinstance(self.archive_member, str) or not self.archive_member.strip():
            raise CrosswalkContractError("archive_member must be a non-blank string for an archive-matched row")
        if not isinstance(self.archive_row, int) or isinstance(self.archive_row, bool) or self.archive_row < 1:
            raise CrosswalkContractError(f"archive_row must be a one-based positive int, got {self.archive_row!r}")
        if self.transcript != TRANSCRIPT:
            raise CrosswalkContractError(f"transcript must be {TRANSCRIPT!r}, got {self.transcript!r}")
        if not isinstance(self.hgvs_c, str) or not self.hgvs_c.startswith("c."):
            raise CrosswalkContractError(f"hgvs_c must be a bare 'c.' string, got {self.hgvs_c!r}")

        if self.status == "SOURCE_COORDINATE_REFERENCE_MISMATCH" or self.status == "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH":
            if self.assembly is not None or self.genomic_spdi is not None:
                raise CrosswalkContractError(
                    f"status {self.status!r} must carry a null assembly/genomic_spdi"
                )
            return

        # status == CROSSWALK_SPDI_VERIFIED
        if self.assembly != ASSEMBLY:
            raise CrosswalkContractError(f"assembly must be {ASSEMBLY!r}, got {self.assembly!r}")
        if not isinstance(self.genomic_spdi, str) or not _GENOMIC_SPDI_RE.match(self.genomic_spdi):
            raise CrosswalkContractError(
                f"CROSSWALK_SPDI_VERIFIED requires a canonical {GENOMIC_ACCESSION} genomic_spdi, got "
                f"{self.genomic_spdi!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


__all__ = [
    "SOURCE_ID",
    "PROTEIN_ACCESSION",
    "TRANSCRIPT",
    "GENOMIC_ACCESSION",
    "ASSEMBLY",
    "VAMP_GENOMIC_CROSSWALK_ROW_SCHEMA",
    "REQUIRED_CROSSWALK_ROW_FIELDS",
    "ALLOWED_CROSSWALK_STATUSES",
    "ALLOWED_UNRESOLVED_REASONS",
    "CrosswalkContractError",
    "VampGenomicCrosswalkRow",
]
