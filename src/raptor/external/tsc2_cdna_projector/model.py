"""RAPTOR v2 cliPE cDNA -> GRCh38 SPDI projector -- mapping row contract.

``raptor.external.clipe_cdna_spdi_mapping_row.v1`` (see the binding spec's
``outputs.external_bundle.artifacts.mapping_jsonl`` section) is the single
per-input-row output shape this slice ever emits: exactly one row per
``source_row`` (1..208), a strict field set, a fixed ``status``/
``variant_shape`` vocabulary, and cross-field invariants tying a
``PROJECTED_FASTA_VERIFIED`` row to a non-null, pattern-conformant
``tx_spdi``/``genomic_spdi`` pinned to ``NM_000548.5``/``NC_000016.10``
respectively, and every OTHER status to an all-null identity/coordinate
payload plus a non-blank, sanitized ``error_detail``.

``ClipeCdnaSpdiMappingRow`` is a validated, frozen dataclass; ``to_dict()``
is the only representation this package's public API ever hands back.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any

#: The fixed identity pins for this entire slice (spec ``inputs.identity_pins``)
#: -- never configurable per row/call.
GENE = "TSC2"
TRANSCRIPT = "NM_000548.5"
GENOMIC_ACCESSION = "NC_000016.10"
ASSEMBLY = "GRCh38"

CLIPE_CDNA_SPDI_MAPPING_ROW_SCHEMA = "raptor.external.clipe_cdna_spdi_mapping_row.v1"

REQUIRED_MAPPING_ROW_FIELDS: frozenset[str] = frozenset(
    {
        "schema",
        "source_id",
        "source_row",
        "source_record_id",
        "gene",
        "transcript",
        "hgvs_c",
        "hgvs_nt_source",
        "tx_spdi",
        "genomic_spdi",
        "hgvs_g",
        "assembly",
        "genomic_accession",
        "status",
        "fasta_deleted_observed",
        "error_detail",
        "step1_body_sha256",
        "step2_body_sha256",
        "variant_shape",
    }
)

#: Spec ``error_states.status_vocabulary`` -- exact fixed set.
ALLOWED_MAPPING_STATUSES: frozenset[str] = frozenset(
    {
        "PROJECTED_FASTA_VERIFIED",
        "STEP1_HTTP_ERROR",
        "STEP1_INVALID_HGVS",
        "STEP1_SCHEMA_VIOLATION",
        "STEP1_AMBIGUOUS_SPDIS",
        "STEP1_UNEXPECTED_SEQ_ID",
        "STEP2_HTTP_ERROR",
        "STEP2_SCHEMA_VIOLATION",
        "STEP2_NON_PINNED_GENOME",
        "FASTA_REF_MISMATCH",
        "FASTA_OUT_OF_RANGE",
        "NON_ACGT_ALLELE",
        "TRANSPORT_OR_BINDING_ERROR",
        "OPERATOR_SKIPPED",
    }
)

#: Spec ``input_composition.shapes`` -- cliPE inputs are only ever SNV or
#: equal-length DELINS in this frozen score-set.
ALLOWED_VARIANT_SHAPES: frozenset[str] = frozenset({"SNV", "DELINS"})

_SUCCESS_STATUS = "PROJECTED_FASTA_VERIFIED"

#: Bare cDNA SNV shape: ``c.<pos><ref>><alt>``.
SNV_HGVS_NT_RE = re.compile(r"^c\.(?P<pos>\d+)(?P<ref>[ACGT])>(?P<alt>[ACGT])$")
#: Bare cDNA delins shape: ``c.<start>_<end>delins<seq>``.
DELINS_HGVS_NT_RE = re.compile(r"^c\.(?P<start>\d+)_(?P<end>\d+)delins(?P<seq>[ACGT]+)$")

#: A frozen ``NM_000548.5:<pos>:<del>:<ins>`` transcript SPDI string.
_TX_SPDI_RE = re.compile(rf"^{re.escape(TRANSCRIPT)}:\d+:[ACGT]+:[ACGT]+$")
#: A verified ``NC_000016.10:<pos>:<del>:<ins>`` genomic SPDI string.
_GENOMIC_SPDI_RE = re.compile(rf"^{re.escape(GENOMIC_ACCESSION)}:\d+:[ACGT]+:[ACGT]+$")


class ProjectionContractError(ValueError):
    """Raised for any structural/schema/vocabulary/invariant violation of
    the cliPE cDNA->SPDI mapping-row contract: an unknown ``status``/
    ``variant_shape``, a non-conformant ``tx_spdi``/``genomic_spdi``, a
    ``PROJECTED_FASTA_VERIFIED`` row missing its identity payload, or any
    other status carrying a non-null identity/coordinate field."""


def classify_variant_shape(hgvs_nt: str) -> str:
    """Return ``"SNV"`` or ``"DELINS"`` for a bare cDNA ``hgvs_nt`` value
    matching this slice's frozen shapes (spec ``input_composition.shapes``),
    or raise ``ProjectionContractError`` for anything else (e.g. a pure
    insertion/deletion/duplication, which this frozen 208-row score-set
    never contains). A DELINS match additionally requires ``end >= start``
    and ``end - start + 1 == len(inserted_sequence)`` -- this pinned
    score-set contains only EQUAL-LENGTH delins (spec
    ``input_composition.shapes.delins``), so a reversed span or a span/
    insert length mismatch is rejected as an invalid shape, never silently
    accepted as a DELINS."""
    if not isinstance(hgvs_nt, str):
        raise ProjectionContractError(f"hgvs_nt must be a string, got {type(hgvs_nt).__name__}")
    if SNV_HGVS_NT_RE.match(hgvs_nt):
        return "SNV"
    delins_match = DELINS_HGVS_NT_RE.match(hgvs_nt)
    if delins_match:
        start = int(delins_match["start"])
        end = int(delins_match["end"])
        inserted = delins_match["seq"]
        if end < start:
            raise ProjectionContractError(
                f"hgvs_nt {hgvs_nt!r} has a reversed delins span (end {end} < start {start})"
            )
        if (end - start + 1) != len(inserted):
            raise ProjectionContractError(
                f"hgvs_nt {hgvs_nt!r} delins span length ({end - start + 1}) does not equal "
                f"the inserted sequence length ({len(inserted)}); this pinned score-set contains "
                "only equal-length delins"
            )
        return "DELINS"
    raise ProjectionContractError(
        f"hgvs_nt {hgvs_nt!r} does not match the frozen SNV (c.<pos><ref>><alt>) or equal-"
        "length DELINS (c.<start>_<end>delins<seq>) shapes this score-set is pinned to"
    )


@dataclass(frozen=True)
class ClipeCdnaSpdiMappingRow:
    """A single validated ``raptor.external.clipe_cdna_spdi_mapping_row.v1``
    row. Construction validates the exact vocabulary and cross-field
    invariants (see module docstring); ``to_dict()`` is the only shape
    handed back across this package's public API."""

    source_id: str
    source_row: int
    source_record_id: str
    gene: str
    transcript: str
    hgvs_c: str
    hgvs_nt_source: str
    tx_spdi: str | None
    genomic_spdi: str | None
    hgvs_g: str | None
    assembly: str | None
    genomic_accession: str | None
    status: str
    fasta_deleted_observed: str | None
    error_detail: str | None
    step1_body_sha256: str | None
    step2_body_sha256: str | None
    variant_shape: str
    schema: str = CLIPE_CDNA_SPDI_MAPPING_ROW_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CLIPE_CDNA_SPDI_MAPPING_ROW_SCHEMA:
            raise ProjectionContractError(
                f"schema must be {CLIPE_CDNA_SPDI_MAPPING_ROW_SCHEMA!r}, got {self.schema!r}"
            )
        if self.gene != GENE:
            raise ProjectionContractError(f"gene must be {GENE!r}, got {self.gene!r}")
        if self.transcript != TRANSCRIPT:
            raise ProjectionContractError(f"transcript must be {TRANSCRIPT!r}, got {self.transcript!r}")
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ProjectionContractError("source_id must be a non-blank string")
        if not isinstance(self.source_row, int) or isinstance(self.source_row, bool) or self.source_row < 1:
            raise ProjectionContractError(f"source_row must be a one-based positive int, got {self.source_row!r}")
        if not isinstance(self.source_record_id, str) or not self.source_record_id.strip():
            raise ProjectionContractError("source_record_id must be a non-blank string")
        if not isinstance(self.hgvs_c, str) or not self.hgvs_c.startswith(f"{TRANSCRIPT}:c."):
            raise ProjectionContractError(
                f"hgvs_c must be a {TRANSCRIPT}:c.* string, got {self.hgvs_c!r}"
            )
        expected_shape = classify_variant_shape(self.hgvs_nt_source)
        if self.variant_shape not in ALLOWED_VARIANT_SHAPES:
            raise ProjectionContractError(
                f"variant_shape {self.variant_shape!r} is not one of {sorted(ALLOWED_VARIANT_SHAPES)!r}"
            )
        if self.variant_shape != expected_shape:
            raise ProjectionContractError(
                f"variant_shape {self.variant_shape!r} does not match the shape "
                f"{expected_shape!r} derived from hgvs_nt_source {self.hgvs_nt_source!r}"
            )
        if self.status not in ALLOWED_MAPPING_STATUSES:
            raise ProjectionContractError(
                f"status {self.status!r} is not one of {sorted(ALLOWED_MAPPING_STATUSES)!r}"
            )

        if self.status == _SUCCESS_STATUS:
            if self.error_detail is not None:
                raise ProjectionContractError(
                    f"{_SUCCESS_STATUS} rows must not carry an error_detail, got {self.error_detail!r}"
                )
            if not isinstance(self.tx_spdi, str) or not _TX_SPDI_RE.match(self.tx_spdi):
                raise ProjectionContractError(
                    f"{_SUCCESS_STATUS} requires a canonical {TRANSCRIPT} tx_spdi, got {self.tx_spdi!r}"
                )
            if not isinstance(self.genomic_spdi, str) or not _GENOMIC_SPDI_RE.match(self.genomic_spdi):
                raise ProjectionContractError(
                    f"{_SUCCESS_STATUS} requires a canonical {GENOMIC_ACCESSION} genomic_spdi, "
                    f"got {self.genomic_spdi!r}"
                )
            if self.assembly != ASSEMBLY:
                raise ProjectionContractError(
                    f"{_SUCCESS_STATUS} requires assembly {ASSEMBLY!r}, got {self.assembly!r}"
                )
            if self.genomic_accession != GENOMIC_ACCESSION:
                raise ProjectionContractError(
                    f"{_SUCCESS_STATUS} requires genomic_accession {GENOMIC_ACCESSION!r}, got "
                    f"{self.genomic_accession!r}"
                )
            if not isinstance(self.fasta_deleted_observed, str) or not re.fullmatch(
                r"[ACGT]+", self.fasta_deleted_observed
            ):
                raise ProjectionContractError(
                    f"{_SUCCESS_STATUS} requires a non-blank ACGT fasta_deleted_observed, got "
                    f"{self.fasta_deleted_observed!r}"
                )
            deleted_in_spdi = self.genomic_spdi.split(":")[2]
            if self.fasta_deleted_observed != deleted_in_spdi:
                raise ProjectionContractError(
                    f"fasta_deleted_observed {self.fasta_deleted_observed!r} does not match the "
                    f"genomic_spdi deleted_sequence {deleted_in_spdi!r}"
                )
            if self.hgvs_g is not None and not isinstance(self.hgvs_g, str):
                raise ProjectionContractError("hgvs_g must be a string or null")
        else:
            if not isinstance(self.error_detail, str) or not self.error_detail.strip():
                raise ProjectionContractError(
                    f"status {self.status!r} requires a non-blank error_detail"
                )
            for field_name, value in (
                ("tx_spdi", self.tx_spdi),
                ("genomic_spdi", self.genomic_spdi),
                ("hgvs_g", self.hgvs_g),
                ("assembly", self.assembly),
                ("genomic_accession", self.genomic_accession),
                ("fasta_deleted_observed", self.fasta_deleted_observed),
            ):
                if value is not None:
                    raise ProjectionContractError(
                        f"status {self.status!r} must carry a null {field_name}, got {value!r}"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


__all__ = [
    "GENE",
    "TRANSCRIPT",
    "GENOMIC_ACCESSION",
    "ASSEMBLY",
    "CLIPE_CDNA_SPDI_MAPPING_ROW_SCHEMA",
    "REQUIRED_MAPPING_ROW_FIELDS",
    "ALLOWED_MAPPING_STATUSES",
    "ALLOWED_VARIANT_SHAPES",
    "SNV_HGVS_NT_RE",
    "DELINS_HGVS_NT_RE",
    "ProjectionContractError",
    "classify_variant_shape",
    "ClipeCdnaSpdiMappingRow",
]
