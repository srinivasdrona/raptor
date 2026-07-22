"""
Gemini RED tests for Mechanism Atlas: Source Registry and Grounding
Spec coverage:
- SourceRegisterEntry, EntryRef, Span, and ObservedClaim exact fields from spec.
- ObservedClaim uses claim_text (not statement), and contains NO span/variant_id fields.
- Span is owned solely by EntryRef (source_ref.span).
- SourceRegisterEntry constructor enforces role/source_type pairing rules.
- validate_claim_grounding(claim, registry, *, pack) enforces resolved entry, direct leaf, allowed type, verified state and nonempty span.
- verify_source fails closed on drift/pending.
- Mutating EntryRef.span changes hashes; no claim-local override exists.
"""

import pytest
from dataclasses import is_dataclass, fields

# 2. Anti-cribbing rule: ban real-content phrases/IDs only, not legitimate terms.
def assert_no_cribbing(obj):
    forbidden_ids = [
        "pmc11185720",
        "10.1101/2024.06.07.597916",
        "c.1832G>A",
        "p.Arg611Gln"
    ]
    if isinstance(obj, str):
        for f in forbidden_ids:
            assert f not in obj.lower(), f"Anti-cribbing violation: found real-content ID/phrase '{f}' in '{obj}'"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_cribbing(k)
            assert_no_cribbing(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            assert_no_cribbing(item)


def test_schema_shapes_and_span_ownership():
    """Verify exact fields for source register, EntryRef, Span, and ObservedClaim from spec."""
    try:
        from raptor.atlas.model import SourceRegisterEntry, EntryRef, Span, ObservedClaim
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.registry implementation is missing")

    assert is_dataclass(SourceRegisterEntry)
    assert is_dataclass(EntryRef)
    assert is_dataclass(Span)
    assert is_dataclass(ObservedClaim)

    # 1. Verify Span fields
    span_fields = {f.name for f in fields(Span)}
    assert span_fields == {"locator", "exact_quote", "page_or_figure"}

    # 2. Verify EntryRef fields
    ref_fields = {f.name for f in fields(EntryRef)}
    assert ref_fields == {"entry_id", "span"}

    # 3. Verify ObservedClaim fields
    claim_fields = {f.name for f in fields(ObservedClaim)}
    expected_fields = {"claim_id", "claim_text", "claim_kind", "source_ref", "verification", "directionality"}
    assert claim_fields == expected_fields, f"ObservedClaim fields mismatch: {claim_fields}"
    assert "span" not in claim_fields, "ObservedClaim must NOT contain a span field"
    assert "variant_id" not in claim_fields, "ObservedClaim must NOT contain a variant_id field"
    assert "statement" not in claim_fields, "ObservedClaim must NOT contain a statement field"

    # Direct constructor with span/variant_id/statement raises TypeError
    for extra in ["span", "variant_id", "statement"]:
        with pytest.raises(TypeError):
            kwargs = {
                "claim_id": "c-1",
                "claim_text": "text",
                "claim_kind": "pathway",
                "source_ref": EntryRef(entry_id="ref", span=None),
                "verification": "unverified",
                "directionality": "none",
                extra: "bad_field"
            }
            ObservedClaim(**kwargs)


def test_source_register_pairing_rules():
    """Verify that constructor enforces pairing rules of role and source_type."""
    try:
        from raptor.atlas.model import SourceRegisterEntry, AtlasSchemaError
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.registry implementation is missing")

    # Valid pairing: PRIMARY-LIT / DATASET can ground direct_evidence_leaf
    for valid_type in ["PRIMARY-LIT", "DATASET"]:
        entry = SourceRegisterEntry(
            entry_id="good-1",
            source_type=valid_type,
            role="direct_evidence_leaf",
            urn_or_ids={"pmid": "123"},
            verification="verified"
        )
        assert entry.role == "direct_evidence_leaf"
        assert_no_cribbing(entry.__dict__)

    # Invalid pairing: PRIMARY-OFFICIAL, PRIMARY-DOC, SECONDARY-SYNTH, CROSSWALK, UNVERIFIED
    # cannot ground direct_evidence_leaf. Must raise AtlasSchemaError in constructor.
    disallowed_types = ["PRIMARY-OFFICIAL", "PRIMARY-DOC", "SECONDARY-SYNTH", "CROSSWALK", "UNVERIFIED"]
    for bad_type in disallowed_types:
        with pytest.raises(AtlasSchemaError):
            SourceRegisterEntry(
                entry_id=f"bad-{bad_type}",
                source_type=bad_type,
                role="direct_evidence_leaf",
                urn_or_ids={"id": "abc"},
                verification="verified"
            )


def test_claim_grounding_validation_pipeline():
    """Verify that validate_claim_grounding strictly enforces citation resolution, leaf type, role, and non-empty span."""
    try:
        from raptor.atlas.model import (
            SourceRegisterEntry, EntryRef, Span, ObservedClaim, DiseasePack,
            AtlasSchemaError, AtlasProvenanceError
        )
        from raptor.atlas.registry import validate_claim_grounding
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.registry implementation is missing")

    # Setup fake disease pack
    fake_pack = DiseasePack(
        schema="atlas.disease_pack.v1",
        pack_id="synthpack",
        pack_version="1.0.0",
        pack_content_hash="mock_hash",
        allowed_genes=("SYNGENE1",),
        assembly_pins=("GRCh38",),
        transcript_pins=({"transcript": "NM_900001.1", "requires": "MANE-Select-verification"},),
        reconciliation_policy={},
        ontology_extensions={},
        source_register_pins=(),
        prohibitions={},
        pilot_eval_metadata={}
    )

    good_entry = SourceRegisterEntry(
        entry_id="lit-1",
        source_type="PRIMARY-LIT",
        role="direct_evidence_leaf",
        urn_or_ids={"pmid": "12345"},
        verification="verified"
    )

    good_span = Span(locator="Fig 1", exact_quote="synthetic assay signal A", page_or_figure="3")
    good_ref = EntryRef(entry_id="lit-1", span=good_span)

    good_claim = ObservedClaim(
        claim_id="claim-1",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=good_ref,
        verification="verified",
        directionality="none"
    )

    registry = {good_entry.entry_id: good_entry}

    # 1. Successful grounding validation
    validate_claim_grounding(good_claim, registry, pack=fake_pack)

    # 2. Failure: missing span on EntryRef raises AtlasSchemaError/AtlasProvenanceError
    bad_ref_no_span = EntryRef(entry_id="lit-1", span=None)
    bad_claim_no_span = ObservedClaim(
        claim_id="claim-2",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=bad_ref_no_span,
        verification="verified",
        directionality="none"
    )
    with pytest.raises((AtlasSchemaError, AtlasProvenanceError)):
        validate_claim_grounding(bad_claim_no_span, registry, pack=fake_pack)

    # 3. Failure: non-grounding role (e.g. provenance_only) raises AtlasProvenanceError
    bad_role_entry = SourceRegisterEntry(
        entry_id="lit-2",
        source_type="PRIMARY-LIT",
        role="provenance_only",
        urn_or_ids={"pmid": "12346"},
        verification="verified"
    )
    bad_role_ref = EntryRef(entry_id="lit-2", span=good_span)
    bad_role_claim = ObservedClaim(
        claim_id="claim-3",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=bad_role_ref,
        verification="verified",
        directionality="none"
    )
    registry_bad_role = {bad_role_entry.entry_id: bad_role_entry}
    with pytest.raises(AtlasProvenanceError):
        validate_claim_grounding(bad_role_claim, registry_bad_role, pack=fake_pack)

    # 4. Failure: unverified or pending source entry raises AtlasProvenanceError
    pending_entry = SourceRegisterEntry(
        entry_id="lit-3",
        source_type="PRIMARY-LIT",
        role="direct_evidence_leaf",
        urn_or_ids={"pmid": "12347"},
        verification="confirm_pending"
    )
    pending_ref = EntryRef(entry_id="lit-3", span=good_span)
    pending_claim = ObservedClaim(
        claim_id="claim-4",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=pending_ref,
        verification="verified",
        directionality="none"
    )
    registry_pending = {pending_entry.entry_id: pending_entry}
    with pytest.raises(AtlasProvenanceError):
        validate_claim_grounding(pending_claim, registry_pending, pack=fake_pack)


def test_source_verification_fails_closed():
    """Verify that verify_source fails closed on metadata pin drift or non-verified states."""
    try:
        from raptor.atlas.model import SourceRegisterEntry, AtlasSourceVerificationError
        from raptor.atlas.registry import verify_source
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.registry implementation is missing")

    good_entry = SourceRegisterEntry(
        entry_id="mave-001",
        source_type="DATASET",
        role="direct_evidence_leaf",
        urn_or_ids={"accession": "MAVEDB-001"},
        transcript="NM_900001.1",
        license="CC0-1.0",
        sha256="74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717",
        variant_count=100,
        verification="verified"
    )

    # Good entry verifies fine
    verify_source(good_entry)

    # 1. SHA-256 metadata drift raises AtlasSourceVerificationError
    drifted_sha = SourceRegisterEntry(
        entry_id="mave-001",
        source_type="DATASET",
        role="direct_evidence_leaf",
        urn_or_ids={"accession": "MAVEDB-001"},
        transcript="NM_900001.1",
        license="CC0-1.0",
        sha256="wrong-drifted-sha",
        variant_count=100,
        verification="verified"
    )
    with pytest.raises(AtlasSourceVerificationError):
        verify_source(drifted_sha)

    # 2. License drift raises AtlasSourceVerificationError
    drifted_license = SourceRegisterEntry(
        entry_id="mave-001",
        source_type="DATASET",
        role="direct_evidence_leaf",
        urn_or_ids={"accession": "MAVEDB-001"},
        transcript="NM_900001.1",
        license="CC-BY-4.0",  # changed
        sha256="74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717",
        variant_count=100,
        verification="verified"
    )
    with pytest.raises(AtlasSourceVerificationError):
        verify_source(drifted_license)

    # 3. confirm_pending status raises AtlasSourceVerificationError
    pending_entry = SourceRegisterEntry(
        entry_id="mave-001",
        source_type="DATASET",
        role="direct_evidence_leaf",
        urn_or_ids={"accession": "MAVEDB-001"},
        verification="confirm_pending"
    )
    with pytest.raises(AtlasSourceVerificationError):
        verify_source(pending_entry)


def test_span_mutation_changes_hash():
    """Verify that mutating EntryRef.span changes the profile's hashes."""
    try:
        from raptor.atlas.model import (
            MechanismProfile, AtlasIdentity, ObservedClaim, EntryRef, Span,
            PackBinding, EvidenceAssessment, Provenance
        )
        from raptor.atlas.hashing import evidence_core_hash
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas hashing/model implementation is missing")

    pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash"
    )

    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    good_span = Span(locator="Fig 1", exact_quote="synthetic assay signal A", page_or_figure="3")
    good_ref = EntryRef(entry_id="lit-1", span=good_span)

    claim = ObservedClaim(
        claim_id="claim-1",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=good_ref,
        verification="verified",
        directionality="none"
    )

    profile1 = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(claim,),
        candidate_classes=(),
        edges=(),
        evidence=EvidenceAssessment((), (), (), ()),
        provenance=Provenance((good_ref,), (), {}),
        run_metadata=None
    )

    h1 = evidence_core_hash(profile1)

    # Mutate span
    mutated_span = Span(locator="Fig 1", exact_quote="synthetic assay signal A (mutated)", page_or_figure="3")
    mutated_ref = EntryRef(entry_id="lit-1", span=mutated_span)
    mutated_claim = ObservedClaim(
        claim_id="claim-1",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=mutated_ref,
        verification="verified",
        directionality="none"
    )

    profile2 = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(mutated_claim,),
        candidate_classes=(),
        edges=(),
        evidence=EvidenceAssessment((), (), (), ()),
        provenance=Provenance((mutated_ref,), (), {}),
        run_metadata=None
    )

    h2 = evidence_core_hash(profile2)
    assert h1 != h2, "Mutating EntryRef.span must change profile core hash"


