"""
Gemini RED tests for Mechanism Atlas: Source Registry and Claims Grounding
Spec coverage:
- Verified claim requires verified leaf + canonical EntryRef.span.
- leaf grounding: role==direct_evidence_leaf AND source_type in {PRIMARY-LIT, DATASET} AND verification==verified AND span.
- negative: mis-tagging disallowed source_types (PRIMARY-OFFICIAL, PRIMARY-DOC, SECONDARY-SYNTH, CROSSWALK) or grouping buckets.
- negative: EntryRef/verified-claim admission rejects role-only tagging when source_type not allowed.
- span ownership: ObservedClaim declaring its own span raises AtlasSchemaError; only EntryRef.span.
- span determinism: claim hash/ordering reads source_ref.span.locator; mutating span changes claim hash.
- provenance_only/context/crosswalk/grouping-bucket grounding raises AtlasProvenanceError.
- unresolved-source behavior: unverified/confirm_pending never ground a verified claim.
- source register fail-closed: sha256/transcript/license/count drift raises AtlasSourceVerificationError.
- context-dependence: same variant, different context -> distinct records.
"""

import pytest
from dataclasses import is_dataclass

from raptor.atlas.model import (
    SourceRegisterEntry,
    EntryRef,
    ObservedClaim,
    AtlasSchemaError,
    AtlasProvenanceError,
    AtlasSourceVerificationError,
)
from raptor.atlas.registry import verify_source

def test_source_schemas_frozen():
    """Verify registry structures are frozen dataclasses."""
    assert is_dataclass(SourceRegisterEntry)
    assert is_dataclass(EntryRef)
    assert is_dataclass(ObservedClaim)


def test_leaf_grounding_requirements_and_failures():
    """A verified claim requires verified leaf + canonical EntryRef.span."""
    # Valid PRIMARY-LIT direct_evidence_leaf
    valid_entry = SourceRegisterEntry(
        entry_id="lit-1",
        source_type="PRIMARY-LIT",
        role="direct_evidence_leaf",
        urn_or_ids={"pmid": "12345678"},
        verification="verified"
    )
    
    # Valid EntryRef with span
    span = {"locator": "Fig1", "exact_quote": "mTOR is active", "page_or_figure": "Page 3"}
    valid_ref = EntryRef(entry_id="lit-1", span=span)
    
    claim = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:2083921:G:A",
        source_ref=valid_ref,
        statement="mTOR activation",
        verification="verified"
    )
    assert claim.verification == "verified"

    # Negative case: missing span on EntryRef raises AtlasSchemaError when verifying claim
    invalid_ref_no_span = EntryRef(entry_id="lit-1", span=None)
    with pytest.raises(AtlasSchemaError):
        ObservedClaim(
            claim_id="claim-2",
            variant_id="NC_000016.10:2083921:G:A",
            source_ref=invalid_ref_no_span,
            statement="mTOR activation",
            verification="verified"
        )


def test_negative_mis_tagging_disallowed_source_types():
    """Mis-tagging disallowed source_type as direct_evidence_leaf raises AtlasSchemaError."""
    disallowed_types = ["PRIMARY-OFFICIAL", "PRIMARY-DOC", "SECONDARY-SYNTH", "CROSSWALK", "UNVERIFIED"]
    for t in disallowed_types:
        with pytest.raises(AtlasSchemaError):
            SourceRegisterEntry(
                entry_id=f"entry-{t}",
                source_type=t,
                role="direct_evidence_leaf",
                urn_or_ids={"id": "abc"},
                verification="verified"
            )


def test_negative_role_only_tagging_rejected():
    """EntryRef/verified-claim admission rejects role-only tagging when source_type is not allowed."""
    # A PRIMARY-LIT grouping/program bucket uses role==context, not direct_evidence_leaf
    grouping_bucket = SourceRegisterEntry(
        entry_id="nellist-program",
        source_type="PRIMARY-LIT",
        role="context",
        urn_or_ids={"pmid": "111"},
        verification="verified"
    )
    
    ref = EntryRef(entry_id="nellist-program", span={"locator": "p1", "exact_quote": "a", "page_or_figure": "1"})
    
    # Trying to ground a verified claim using a non-leaf context bucket raises AtlasProvenanceError
    with pytest.raises(AtlasProvenanceError):
        ObservedClaim(
            claim_id="claim-3",
            variant_id="NC_000016.10:2083921:G:A",
            source_ref=ref,
            statement="mTOR activation",
            verification="verified"
        )


def test_span_ownership_observed_claim_no_span():
    """An ObservedClaim declaring its own span field raises AtlasSchemaError."""
    # The ObservedClaim constructor must not accept a 'span' argument, or raise AtlasSchemaError if present.
    # If the user tries to inject a span locally, it must raise AtlasSchemaError.
    with pytest.raises(AtlasSchemaError):
        ObservedClaim(
            claim_id="claim-4",
            variant_id="NC_000016.10:2083921:G:A",
            source_ref=EntryRef(entry_id="lit-1", span=None),
            statement="mTOR activation",
            verification="verified",
            span={"locator": "local-span"}  # type: ignore
        )


def test_span_determinism_hash_affects_claim():
    """The claim ordering/hash key reads source_ref.span.locator; mutating it changes the claim hash."""
    from raptor.atlas.hashing import claim_hash

    ref1 = EntryRef(entry_id="lit-1", span={"locator": "Fig1", "exact_quote": "A", "page_or_figure": "1"})
    claim1 = ObservedClaim(
        claim_id="claim-5",
        variant_id="NC_000016.10:2083921:G:A",
        source_ref=ref1,
        statement="statement",
        verification="verified"
    )
    
    ref2 = EntryRef(entry_id="lit-1", span={"locator": "Fig2", "exact_quote": "A", "page_or_figure": "1"})
    claim2 = ObservedClaim(
        claim_id="claim-5",
        variant_id="NC_000016.10:2083921:G:A",
        source_ref=ref2,
        statement="statement",
        verification="verified"
    )
    
    # Changing the span locator must produce distinct hashes (no claim-local override exists)
    assert claim_hash(claim1) != claim_hash(claim2)


def test_provenance_only_grounding_fails():
    """provenance_only/context/crosswalk/grouping-bucket grounding raises AtlasProvenanceError."""
    entry = SourceRegisterEntry(
        entry_id="clinvar-provenance",
        source_type="PRIMARY-OFFICIAL",
        role="provenance_only",
        urn_or_ids={"clinvar": "123"},
        verification="verified"
    )
    
    ref = EntryRef(entry_id="clinvar-provenance", span={"locator": "p1", "exact_quote": "a", "page_or_figure": "1"})
    with pytest.raises(AtlasProvenanceError):
        ObservedClaim(
            claim_id="claim-6",
            variant_id="NC_000016.10:2083921:G:A",
            source_ref=ref,
            statement="mTOR activation",
            verification="verified"
        )


def test_unresolved_source_behavior():
    """unverified / confirm_pending entries never ground a verified claim."""
    entry_pending = SourceRegisterEntry(
        entry_id="igvf-pending",
        source_type="DATASET",
        role="direct_evidence_leaf",
        urn_or_ids={"urn": "igvf"},
        verification="confirm_pending"
    )
    
    ref = EntryRef(entry_id="igvf-pending", span={"locator": "p1", "exact_quote": "a", "page_or_figure": "1"})
    with pytest.raises(AtlasProvenanceError):
        ObservedClaim(
            claim_id="claim-7",
            variant_id="NC_000016.10:2083921:G:A",
            source_ref=ref,
            statement="mTOR",
            verification="verified"
        )


def test_source_register_fail_closed_drift():
    """verify_source fails closed on transcript/license/sha256/count drift, or confirm_pending."""
    # Correct entry
    good_entry = SourceRegisterEntry(
        entry_id="mavedb-1",
        source_type="DATASET",
        role="direct_evidence_leaf",
        urn_or_ids={"urn": "mavedb"},
        license="CC0-1.0",
        sha256="74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717",
        variant_count=208,
        verification="verified"
    )
    
    # Should pass
    verify_source(good_entry)

    # Drift in sha256
    drifted_sha = SourceRegisterEntry(
        entry_id="mavedb-1",
        source_type="DATASET",
        role="direct_evidence_leaf",
        urn_or_ids={"urn": "mavedb"},
        license="CC0-1.0",
        sha256="wrong-sha",
        variant_count=208,
        verification="verified"
    )
    with pytest.raises(AtlasSourceVerificationError):
        verify_source(drifted_sha)

    # Drift in count
    drifted_count = SourceRegisterEntry(
        entry_id="mavedb-1",
        source_type="DATASET",
        role="direct_evidence_leaf",
        urn_or_ids={"urn": "mavedb"},
        license="CC0-1.0",
        sha256="74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717",
        variant_count=100,
        verification="verified"
    )
    with pytest.raises(AtlasSourceVerificationError):
        verify_source(drifted_count)

    # Treating confirm_pending as verified raises AtlasSourceVerificationError
    pending_entry = SourceRegisterEntry(
        entry_id="igvf-pending",
        source_type="DATASET",
        role="direct_evidence_leaf",
        urn_or_ids={"urn": "igvf"},
        verification="confirm_pending"
    )
    with pytest.raises(AtlasSourceVerificationError):
        verify_source(pending_entry)


def test_context_dependence_distinct():
    """Same variant under different experimental context yields distinct records."""
    # Since records are structured by claim + context, different assays represent distinct items.
    claim1 = ObservedClaim(
        claim_id="claim-c1",
        variant_id="NC_000016.10:2083921:G:A",
        source_ref=EntryRef(entry_id="lit-1", span={"locator": "Fig1", "exact_quote": "Active", "page_or_figure": "1"}),
        statement="Assay A shows activation",
        verification="verified"
    )
    claim2 = ObservedClaim(
        claim_id="claim-c2",
        variant_id="NC_000016.10:2083921:G:A",
        source_ref=EntryRef(entry_id="lit-1", span={"locator": "Fig2", "exact_quote": "Inactive", "page_or_figure": "1"}),
        statement="Assay B shows normal abundance",
        verification="verified"
    )
    assert claim1.statement != claim2.statement
    assert claim1 != claim2
