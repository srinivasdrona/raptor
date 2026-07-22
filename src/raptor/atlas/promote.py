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
from raptor.atlas.identity import validate_canonical_spdi_shape
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


def _is_valid_named_signoff(signoff: Any) -> bool:
    """A valid Gate 8 signoff is either a nonblank named string (the
    Phase-1 synthetic signoff shape used by every frozen fixture) or an
    explicitly structured mapping carrying a nonblank ``reviewer_id`` or
    ``name`` AND an ``accepted`` flag that is exactly ``True``. Booleans
    and any other generic truthy object (e.g. ``1``, arbitrary objects,
    or a bare ``True`` returned by an adversarial ``lambda``) are
    rejected -- a NAMED signoff is required, not mere truthiness."""

    if isinstance(signoff, bool):
        return False
    if isinstance(signoff, str):
        return bool(signoff.strip())
    if isinstance(signoff, dict):
        reviewer = signoff.get("reviewer_id") or signoff.get("name")
        return (
            isinstance(reviewer, str)
            and bool(reviewer.strip())
            and signoff.get("accepted") is True
        )
    return False


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

    spdi_proposed = variant.get("spdi_proposed")
    if not spdi_proposed:
        raise AtlasIdentityError("candidate_variant.spdi_proposed is required for readmission")
    # Reuse the SOLE shared canonical SPDI shape validator (also used by
    # admit_identity) -- readmission is never a bare presence check or an
    # alias-equality shortcut.
    validate_canonical_spdi_shape(spdi_proposed)

    gene_proposed = variant.get("gene_proposed")
    if gene_proposed not in pack.allowed_genes:
        raise AtlasIdentityError(
            f"candidate_variant.gene_proposed {gene_proposed!r} is not in the bound "
            "disease pack's allowed_genes"
        )


def _gate2_source_type_role_validation(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    sources_by_id: dict = {}
    for source in candidate.proposed_sources:
        entry_id = source.get("entry_id")
        if entry_id in sources_by_id:
            raise AtlasSchemaError(
                f"candidate.proposed_sources contains a duplicate entry_id {entry_id!r}"
            )
        sources_by_id[entry_id] = source
        if source.get("role") == "direct_evidence_leaf" and source.get("source_type") not in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES:
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} cannot ground a direct "
                f"evidence leaf with source_type {source.get('source_type')!r}"
            )

    # Every proposed claim is unconditionally promoted to verification="verified"
    # by promote_candidate, so the source it will be grounded against must
    # resolve exactly (not by bare alias/id equality against an unrelated
    # register) to a direct_evidence_leaf-role, PRIMARY-LIT/DATASET-typed
    # source carrying a resolvable bibliographic proposal. A provenance_only,
    # context, or crosswalk source can never ground a verified claim.
    for claim in candidate.proposed_claims:
        source_ref = claim.get("source_ref_proposed")
        linked_source = sources_by_id.get(source_ref)
        if linked_source is None:
            raise AtlasSchemaError(
                f"proposed claim references source_ref_proposed {source_ref!r} which is "
                "missing from candidate.proposed_sources"
            )
        if linked_source.get("role") != "direct_evidence_leaf":
            raise AtlasSchemaError(
                f"proposed claim's linked source {source_ref!r} has role "
                f"{linked_source.get('role')!r}; only a direct_evidence_leaf source can "
                "ground a claim that will become verified"
            )
        if linked_source.get("source_type") not in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES:
            raise AtlasSchemaError(
                f"proposed claim's linked source {source_ref!r} has source_type "
                f"{linked_source.get('source_type')!r}, which is not one of "
                f"{DIRECT_EVIDENCE_LEAF_SOURCE_TYPES}"
            )
        if _extract_citation_key(linked_source.get("bib")) is None:
            raise AtlasSchemaError(
                f"proposed claim's linked source {source_ref!r} lacks a resolvable "
                "bibliographic proposal (pmid/doi/accession)"
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
        if not _is_valid_named_signoff(signoff):
            raise AtlasProvenanceError(
                f"human oracle reviewer did not provide a valid NAMED signoff for "
                f"proposed claim referencing {claim.get('source_ref_proposed')!r}"
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
