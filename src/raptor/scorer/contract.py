"""PRD-01 sec 10.2/10.4 `contract.py` — the BIAS-2015 output source-contract.

Asserts the BIAS output TSV column contract *before* parsing any row: a
BIAS release/column drift (R-B1-style) must fail loudly, never silently
mis-align columns (and must never be swallowed into the manual queue --
this is a whole-run reproducibility breach, not a per-record failure).
"""
from __future__ import annotations

from typing import Iterable


class BiasContractError(Exception):
    """Raised when the BIAS output TSV header does not match the pinned column contract."""


class BiasOutputContract:
    """The pinned BIAS-2015 `*.bias_output.tsv` column contract (PRD-01 sec 10.2)."""

    #: Order matches BIAS-2015's own committed `test/data/*.bias_output.tsv` header.
    REQUIRED_COLUMNS: tuple[str, ...] = (
        "chromosome",
        "position",
        "refAllele",
        "altAllele",
        "variantType",
        "consequence",
        "acmgClassification",
        "alleleFreq",
        "hgvsg",
        "hgvsc",
        "hgvsp",
        "aaChange",
        "geneName",
        "pubmedIds",
        "associatedDiseases",
        "dbSnpids",
        "transcript",
        "rationale",
    )

    @classmethod
    def assert_columns(cls, header: Iterable[str]) -> None:
        """Raise `BiasContractError` if any required column is missing.

        Extra/reordered trailing columns are tolerated -- what must never
        drift silently is the *presence* of every column this module's
        field-index lookups depend on (especially `rationale`, the
        criterion-call payload this whole scorer is built on).
        """
        header_list = list(header)
        missing = [c for c in cls.REQUIRED_COLUMNS if c not in header_list]
        if missing:
            raise BiasContractError(
                "BIAS output column contract violated -- missing required "
                f"column(s): {missing!r} (got header: {header_list!r})"
            )
