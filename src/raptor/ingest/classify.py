"""PRD-02 sec 10.3 `classify.py` (optional module) — FR3 variant-class routing.

Classification here only distinguishes the variant *types* the genomic
(SPDI-only) normalizer can resolve without transcript/gene-model data
(SNV/MNV/SMALL_INDEL). Finer distinctions in FR3's matrix
(non-coding/synonymous/splice-region) require transcript projection and
are deferred to the UTA step (sec 10.6) same as `hgvs_c`/`hgvs_p`.
"""
from __future__ import annotations

from .model import VariantClass


def classify_variant(ref: str, alt: str) -> VariantClass:
    """Classify a *precise* VCF-style (ref, alt) pair (imprecise SV/CNV
    rows must be routed to manual queue before this is called)."""
    ref = (ref or "").upper()
    alt = (alt or "").upper()
    if len(ref) == 1 and len(alt) == 1 and ref != alt:
        return VariantClass.SNV
    if len(ref) == len(alt) and len(ref) > 1:
        return VariantClass.MNV
    return VariantClass.SMALL_INDEL
