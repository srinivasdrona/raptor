"""
Gemini RED tests for Mechanism Atlas: Source Registry and Claims Grounding (Revised)
Spec coverage:
- SourceRegisterEntry constructor enforces role/source_type pairings locally.
- EntryRef owns span.
- ObservedClaim does not independently know the register entry; uses validate_claim_grounding seam.
- Assert span is absent from dataclasses.fields(ObservedClaim).
- Test all disallowed roles/types and pending/unresolved.
- verify_source fails closed on drift.
"""

import pytest
from dataclasses import is_dataclass, fields

# 1. Guard planned imports so all tests collect
try:
    from raptor.atlas.model import (
        SourceRegisterEntry,
        EntryRef,
        ObservedClaim,
        AtlasSchemaError,
        AtlasProvenanceError,
        AtlasSourceVerificationError,
    )
    from raptor.atlas.registry import verify_source, validate_claim_grounding
    IMPLEMENTED = True
except (ImportError, ModuleNotFoundError):
    SourceRegisterEntry = None
    EntryRef = None
    ObservedClaim = None
    AtlasSchemaError = ValueError
    AtlasProvenanceError = RuntimeError
    AtlasSourceVerificationError = RuntimeError
    verify_source = None
    validate_claim_grounding = None
    IMPLEMENTED = False

def check_implemented():
    if not IMPLEMENTED:
        pytest.fail("RED test: raptor.atlas is not implemented yet", pytrace=False)

# 2. Anti-cribbing check
def assert_no_cribbing(obj):
    forbidden = ["r611q", "arg611", "mtor", "rescue", "zygosity", "stability", "localization"]
    if isinstance(obj, str):
        for f in forbidden:
            assert f not in obj.lower(), f"Anti-cribbing violation: found '{f}' in '{obj}'"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_cribbing(k)
            assert_no_cribbing(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            assert_no_cribbing(item)

def test_source_schemas_shape_and_immutability():
    check_implemented()
    assert is_dataclass(SourceRegisterEntry)
    assert is_dataclass(EntryRef)
    assert is_dataclass(ObservedClaim)

    # 5. Span ownership: assert span is absent from ObservedClaim fields
    claim_fields = {f.name for f in fields(ObservedClaim)}
    assert "span" not in claim_fields, "ObservedClaim must not carry 'span' field"

    # Expect TypeError on direct constructor unexpected arg
    with pytest.raises(TypeError):
        ObservedClaim(
            claim_id="claim-1",
            variant_id="NC_000016.10:22222:G:C",
            source_ref=EntryRef(entry_id="lit-1", span=None),
            statement="synthetic assay signal A",
            verification="verified",
            span={"locator": "Fig1"}  # type: ignore
        )


def test_source_register_constructor_enforces_pairings():
    check_implemented()
    # 4. SourceRegisterEntry constructor enforces role/source_type pairings locally
    # Valid pairing: PRIMARY-LIT + direct_evidence_leaf
    entry = SourceRegisterEntry(
        entry_id="lit-1",
        source_type="PRIMARY-LIT",
        role="direct_evidence_leaf",
        urn_or_ids={"pmid": "12345"},
        verification="verified"
    )
    assert_no_cribbing(entry.__dict__)

    # Invalid pairings raise AtlasSchemaError in constructor
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


def test_claim_grounding_validation_seam():
    check_implemented()
    # 4. validate_claim_grounding(claim, source_registry) seam asserts verified leaf+type+verification+span
    good_entry = SourceRegisterEntry(
        entry_id="lit-1",
        source_type="PRIMARY-LIT",
        role="direct_evidence_leaf",
        urn_or_ids={"pmid": "12345"},
        verification="verified"
    )
    
    good_span = {"locator": "Fig1", "exact_quote": "synthetic assay signal A", "page_or_figure": "3"}
    ref = EntryRef(entry_id="lit-1", span=good_span)
    
    claim = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:22222:G:C",
        source_ref=ref,
        statement="synthetic assay signal A",
        verification="verified"
    )
    
    assert_no_cribbing(claim.__dict__)
    
    registry = {good_entry.entry_id: good_entry}
    
    # Should pass grounding validation
    validate_claim_grounding(claim, registry)

    # Failure cases:
    # A. Missing span on EntryRef raises AtlasSchemaError/AtlasProvenanceError
    bad_ref_no_span = EntryRef(entry_id="lit-1", span=None)
    bad_claim_no_span = ObservedClaim(
        claim_id="claim-2",
        variant_id="NC_000016.10:22222:G:C",
        source_ref=bad_ref_no_span,
        statement="synthetic assay signal A",
        verification="verified"
    )
    with pytest.raises((AtlasSchemaError, AtlasProvenanceError)):
        validate_claim_grounding(bad_claim_no_span, registry)

    # B. Pending source raises AtlasProvenanceError
    pending_entry = SourceRegisterEntry(
        entry_id="lit-2",
        source_type="PRIMARY-LIT",
        role="direct_evidence_leaf",
        urn_or_ids={"pmid": "12346"},
        verification="confirm_pending"
    )
    pending_ref = EntryRef(entry_id="lit-2", span=good_span)
    pending_claim = ObservedClaim(
        claim_id="claim-3",
        variant_id="NC_000016.10:22222:G:C",
        source_ref=pending_ref,
        statement="synthetic assay signal A",
        verification="verified"
    )
    registry_pending = {pending_entry.entry_id: pending_entry}
    with pytest.raises(AtlasProvenanceError):
        validate_claim_grounding(pending_claim, registry_pending)

    # C. Non-grounding role raises AtlasProvenanceError
    context_entry = SourceRegisterEntry(
        entry_id="lit-3",
        source_type="PRIMARY-LIT",
        role="context",
        urn_or_ids={"pmid": "12347"},
        verification="verified"
    )
    context_ref = EntryRef(entry_id="lit-3", span=good_span)
    context_claim = ObservedClaim(
        claim_id="claim-4",
        variant_id="NC_000016.10:22222:G:C",
        source_ref=context_ref,
        statement="synthetic assay signal A",
        verification="verified"
    )
    registry_context = {context_entry.entry_id: context_entry}
    with pytest.raises(AtlasProvenanceError):
        validate_claim_grounding(context_claim, registry_context)


def test_source_register_fail_closed_verification():
    check_implemented()
    # verify_source(entry) raises on drift or pending status
    good_entry = SourceRegisterEntry(
        entry_id="lit-1",
        source_type="PRIMARY-LIT",
        role="direct_evidence_leaf",
        urn_or_ids={"pmid": "12345"},
        license="CC0-1.0",
        sha256="74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717",
        variant_count=208,
        verification="verified"
    )
    
    # Should verify fine
    verify_source(good_entry)

    # Drift in sha256
    drifted_sha = SourceRegisterEntry(
        entry_id="lit-1",
        source_type="PRIMARY-LIT",
        role="direct_evidence_leaf",
        urn_or_ids={"pmid": "12345"},
        license="CC0-1.0",
        sha256="wrong-sha-hash-drift",
        variant_count=208,
        verification="verified"
    )
    with pytest.raises(AtlasSourceVerificationError):
        verify_source(drifted_sha)

    # confirm_pending treated as verified raises
    pending_entry = SourceRegisterEntry(
        entry_id="lit-2",
        source_type="PRIMARY-LIT",
        role="direct_evidence_leaf",
        urn_or_ids={"pmid": "12346"},
        verification="confirm_pending"
    )
    with pytest.raises(AtlasSourceVerificationError):
        verify_source(pending_entry)
