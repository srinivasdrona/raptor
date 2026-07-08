"""PRD-02 sec 10.3 `contract.py` — FR9/AC6 source-contract check.

Asserts the ClinVar `variant_summary.txt` column contract *before* parsing
any row: R-B1 (ClinVar schema/API drift) must fail loudly, not silently
mis-align columns.
"""
from __future__ import annotations

from typing import Iterable


class SourceContractError(Exception):
    """Raised when the `variant_summary` header does not match the pinned column contract."""


class VariantSummaryContract:
    """The pinned NCBI ClinVar `variant_summary.txt.gz` column contract (v1)."""

    #: Order matches the current public ClinVar `variant_summary.txt.gz` header.
    REQUIRED_COLUMNS: tuple[str, ...] = (
        "#AlleleID",
        "Type",
        "Name",
        "GeneID",
        "GeneSymbol",
        "HGNC_ID",
        "ClinicalSignificance",
        "ClinSigSimple",
        "LastEvaluated",
        "RS# (dbSNP)",
        "nsv/esv (dbVar)",
        "RCVaccession",
        "PhenotypeIDS",
        "PhenotypeList",
        "Origin",
        "OriginSimple",
        "Assembly",
        "ChromosomeAccession",
        "Chromosome",
        "Start",
        "Stop",
        "ReferenceAllele",
        "AlternateAllele",
        "Cytogenetic",
        "ReviewStatus",
        "NumberSubmitters",
        "Guidelines",
        "TestedInGTR",
        "OtherIDs",
        "SubmitterCategories",
        "VariationID",
        "PositionVCF",
        "ReferenceAlleleVCF",
        "AlternateAlleleVCF",
        "SomaticClinicalImpact",
        "SomaticClinicalImpactLastEvaluated",
        "ReviewStatusClinicalImpact",
        "Oncogenicity",
        "OncogenicityLastEvaluated",
        "ReviewStatusOncogenicity",
        "SCVsForAggregateGermlineClassification",
        "SCVsForAggregateSomaticClinicalImpact",
        "SCVsForAggregateOncogenicityClassification",
    )

    @classmethod
    def assert_columns(cls, header: Iterable[str]) -> None:
        """Raise `SourceContractError` if any required column is missing (FR9/AC6).

        Extra/reordered trailing columns (ClinVar has added some over time)
        are tolerated -- what must never drift silently is the *presence*
        of every column this module's field-index lookups depend on
        (especially `VariationID`, `PositionVCF`, `ReferenceAlleleVCF`,
        `AlternateAlleleVCF`, `GeneSymbol`, `ChromosomeAccession`).
        """
        header_list = list(header)
        missing = [c for c in cls.REQUIRED_COLUMNS if c not in header_list]
        if missing:
            raise SourceContractError(
                "variant_summary column contract violated -- missing required "
                f"column(s): {missing!r} (got header: {header_list!r})"
            )
