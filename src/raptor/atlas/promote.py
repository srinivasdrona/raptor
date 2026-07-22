"""Discovery candidate import validation and promotion (8 ordered gates).

``validate_candidate_import`` enforces, in strict order, the eight
promotion gates defined by the spec. Each gate short-circuits on failure
-- no later gate's collaborators are invoked once an earlier gate raises.
``promote_candidate`` re-validates and then builds a frozen tuple of
:class:`~raptor.atlas.model.ObservedClaim` without ever mutating the
input candidate.
"""

from __future__ import annotations

from typing import Any

from raptor.atlas.guards import scan_for_classification_leakage
from raptor.atlas.model import (
    AtlasCandidateImport,
    AtlasIdentityError,
    AtlasProvenanceError,
    AtlasSchemaError,
    DIRECT_EVIDENCE_LEAF_SOURCE_TYPES,
    EntryRef,
    ObservedClaim,
    PromotionContext,
    Span,
)


def _extract_citation_key(bib: Any):
    if not isinstance(bib, dict):
        return None
    return bib.get("pmid") or bib.get("doi") or bib.get("accession")


def _gate1_canonical_spdi_readmission(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    variant = candidate.candidate_variant
    provenance = candidate.retrieval_provenance
    pack = context.disease_pack

    declared_binding = provenance.get("pack_binding") or {}
    actual_binding = {
        "pack_id": pack.pack_id,
        "pack_version": pack.pack_version,
        "pack_content_hash": pack.pack_content_hash,
    }
    if declared_binding != actual_binding:
        raise AtlasSchemaError(
            "candidate retrieval_provenance.pack_binding does not match the "
            "promotion context's bound disease pack"
        )

    if not variant.get("spdi_proposed"):
        raise AtlasIdentityError("candidate_variant.spdi_proposed is required for readmission")

    gene_proposed = variant.get("gene_proposed")
    if gene_proposed not in pack.allowed_genes:
        raise AtlasIdentityError(
            f"candidate_variant.gene_proposed {gene_proposed!r} is not in the bound "
            "disease pack's allowed_genes"
        )


def _gate2_source_type_role_validation(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    for source in candidate.proposed_sources:
        if source.get("role") == "direct_evidence_leaf" and source.get("source_type") not in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES:
            raise AtlasSchemaError(
                f"proposed source {source.get('entry_id')!r} cannot ground a direct "
                f"evidence leaf with source_type {source.get('source_type')!r}"
            )


def _gate3_citation_resolution(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    for source in candidate.proposed_sources:
        citation_key = _extract_citation_key(source.get("bib"))
        if not context.citation_resolver(citation_key):
            raise AtlasProvenanceError(
                f"citation resolver could not resolve proposed source {source.get('entry_id')!r}"
            )


def _gate4_exact_span_resolution(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    for claim in candidate.proposed_claims:
        span_proposed = claim.get("span_proposed")
        if not isinstance(span_proposed, dict) or not span_proposed.get("locator"):
            raise AtlasSchemaError(
                f"proposed claim {claim.get('claim_text')!r} lacks a complete span_proposed"
            )


def _gate5_context_ontology_pack_validation(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    for claim in candidate.proposed_claims:
        claim_kind = claim.get("claim_kind_proposed")
        context_name = claim.get("context_proposed")
        if not context.context_validator(claim_kind, context_name):
            raise AtlasSchemaError(
                f"context validator rejected proposed claim kind {claim_kind!r} "
                f"in context {context_name!r}"
            )


def _gate6_duplicate_conflict_rules(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    duplicate_index = context.duplicate_index or {}
    for value in duplicate_index.values():
        if "conflict" in str(value):
            raise AtlasProvenanceError(
                "duplicate/conflict register indicates an unresolved conflict for this candidate"
            )


def _gate7_no_classification_leakage(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    scan_for_classification_leakage(candidate.proposed_claims, _path="proposed_claims")
    scan_for_classification_leakage(candidate.proposed_sources, _path="proposed_sources")
    scan_for_classification_leakage(candidate.candidate_variant, _path="candidate_variant")
    scan_for_classification_leakage(candidate.retrieval_provenance, _path="retrieval_provenance")


def _gate8_named_human_oracle_span_review(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    for claim in candidate.proposed_claims:
        signoff = context.human_oracle_reviewer(claim.get("source_ref_proposed"))
        if not signoff:
            raise AtlasProvenanceError(
                f"human oracle reviewer did not sign off on proposed claim referencing "
                f"{claim.get('source_ref_proposed')!r}"
            )


def validate_candidate_import(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    """Run all eight promotion gates, in exact order, short-circuiting on
    the first failure."""

    _gate1_canonical_spdi_readmission(candidate, context)
    _gate2_source_type_role_validation(candidate, context)
    _gate3_citation_resolution(candidate, context)
    _gate4_exact_span_resolution(candidate, context)
    _gate5_context_ontology_pack_validation(candidate, context)
    _gate6_duplicate_conflict_rules(candidate, context)
    _gate7_no_classification_leakage(candidate, context)
    _gate8_named_human_oracle_span_review(candidate, context)


def promote_candidate(candidate: AtlasCandidateImport, context: PromotionContext) -> tuple:
    """Validate ``candidate`` against ``context`` and, only if every gate
    passes, return a frozen tuple of newly-admitted :class:`ObservedClaim`
    objects. Never mutates ``candidate``."""

    validate_candidate_import(candidate, context)

    accepted = []
    for index, claim in enumerate(candidate.proposed_claims):
        span_proposed = claim.get("span_proposed") or {}
        span = Span(
            locator=span_proposed.get("locator"),
            exact_quote=span_proposed.get("exact_quote"),
            page_or_figure=span_proposed.get("page_or_figure"),
        )
        source_ref = EntryRef(entry_id=claim.get("source_ref_proposed"), span=span)
        accepted.append(
            ObservedClaim(
                claim_id=f"promoted-{index}",
                claim_text=claim.get("claim_text"),
                claim_kind=claim.get("claim_kind_proposed"),
                source_ref=source_ref,
                verification="verified",
                directionality=claim.get("directionality", "unknown"),
            )
        )

    return tuple(accepted)
