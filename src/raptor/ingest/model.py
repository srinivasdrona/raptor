"""PRD-02 sec 10.3 `model.py` — the record shapes flowing through the ingest pipeline.

`RawVariant` is what the reader emits; `NormalizedVariant`/`ManualQueueItem`
are the two possible `Normalizer.normalize()` outcomes (FR3/FR6); every
input row must yield exactly one of them (AC1 conservation).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Union


class VariantClass(str, Enum):
    """FR3 variant-class matrix. Values are the exact strings persisted to
    the KB `variants.class` / used in `IngestReport.class_histogram`."""

    SNV = "SNV"
    MNV = "MNV"
    SMALL_INDEL = "SMALL_INDEL"
    NONCODING_SPDI_ONLY = "NONCODING_SPDI_ONLY"
    SPLICE_REGION = "SPLICE_REGION"
    IMPRECISE_SV = "IMPRECISE_SV"
    COMPLEX_MULTIGENE = "COMPLEX_MULTIGENE"
    PROJECTION_FAILURE = "PROJECTION_FAILURE"


@dataclass(frozen=True)
class RawVariant:
    """A single parsed ClinVar `variant_summary` row, filtered to gene (FR1).

    Carries only coordinates + source-ref fields (FR5) -- no oracle/label
    column (AC5: no trace-cribbing) -- so the normalizer can never see a
    ClinVar-provided answer to check its own output against.
    """

    chromosome: str  # RefSeq genomic accession, e.g. "NC_000009.12" (ChromosomeAccession)
    position: int | str  # PositionVCF (1-based); "-1"/non-numeric for imprecise SV/CNV rows
    ref: str  # ReferenceAlleleVCF
    alt: str  # AlternateAlleleVCF
    gene: str  # the gene this row was filtered for (config gene-list entry)
    variation_id: str  # ClinVar VariationID
    snapshot_id: str
    snapshot_date: str
    source_file_checksum: str
    row_locator: str
    raw_source_value: str


@dataclass(frozen=True)
class NormalizedVariant:
    """FR2/FR3 successful-normalization outcome. `variant_id` = canonical
    GRCh38 genomic SPDI (sec 2.1, the join key). `hgvs_c`/`hgvs_p` are
    deferred to the UTA step in this increment (sec 10.6) -- always `None`
    with `*_null_reason="awaiting_uta_projection"`."""

    variant_id: str
    hgvs_g: str | None
    hgvs_c: str | None
    hgvs_p: str | None
    hgvs_c_null_reason: str | None
    hgvs_p_null_reason: str | None
    variant_class: VariantClass
    gene: str
    variation_id: str
    snapshot_id: str
    snapshot_date: str
    source_file_checksum: str
    row_locator: str
    raw_source_value: str


@dataclass(frozen=True)
class ManualQueueItem:
    """FR6 manual-queue record: an input that could not be normalized to a
    trustworthy `variant_id` (never a silent drop, R-A10)."""

    raw_input: str
    source_ref: str
    failure_stage: str
    error_code: str
    reason: str
    attempted_coords: str | None
    tool_error: str | None
    config_pins: Mapping[str, Any]
    run_id: str
    excluded_from_scorer: bool = True


NormalizationOutcome = Union[NormalizedVariant, ManualQueueItem]
