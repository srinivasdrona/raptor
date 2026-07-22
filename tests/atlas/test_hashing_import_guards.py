"""
Gemini RED tests for Mechanism Atlas: Hashing and Static Import Guards
Spec coverage:
- Build complete frozen constituent objects for MechanismProfile with no loose dict stand-ins.
- Hashing canonical order and dedup over defined include/exclude fields.
- Both core and envelope hashes bind top-level pack_binding; run_metadata is excluded.
- Swapping the pack changes both hashes (detectable, fail closed).
- RunMetadata.pack_binding_audit copy must equal MechanismProfile.pack_binding (raises AtlasSchemaError).
- Dangling edge/evidence claim references raise AtlasSchemaError.
- One-way DisMech export with pack_binding equality validation.
- Static AST/module-graph import boundary checks (no sys.modules checks; fail if atlas files are absent).
"""

import sys
import ast
import hashlib
import json
import pytest
from pathlib import Path

# 1. Guard planned imports so all tests collect cleanly
try:
    from raptor.atlas.model import (
        MechanismProfile,
        AtlasIdentity,
        ObservedClaim,
        EntryRef,
        Span,
        PackBinding,
        CandidateClass,
        MechanismEdge,
        EvidenceAssessment,
        Provenance,
        RunMetadata,
        ContextRecord,
        DisMechRecord,
        AtlasSchemaError,
        AtlasIdentityError,
        AtlasProvenanceError,
        AtlasLeakageError,
        AtlasExportError,
    )
    from raptor.atlas.hashing import evidence_core_hash, profile_envelope_hash
    from raptor.atlas.export import export_dismech
    from raptor.atlas.guards import assert_atlas_import_boundary, assert_no_consumer_import
    IMPLEMENTED = True
except (ImportError, ModuleNotFoundError):
    MechanismProfile = None
    AtlasIdentity = None
    ObservedClaim = None
    EntryRef = None
    Span = None
    PackBinding = None
    CandidateClass = None
    MechanismEdge = None
    EvidenceAssessment = None
    Provenance = None
    RunMetadata = None
    ContextRecord = None
    DisMechRecord = None
    AtlasSchemaError = ValueError
    AtlasIdentityError = ValueError
    AtlasProvenanceError = ValueError
    AtlasLeakageError = ValueError
    AtlasExportError = ValueError
    evidence_core_hash = None
    profile_envelope_hash = None
    export_dismech = None
    assert_atlas_import_boundary = None
    assert_no_consumer_import = None
    IMPLEMENTED = False

def check_implemented():
    if not IMPLEMENTED:
        pytest.fail("RED test: raptor.atlas hashing/guards implementation is missing", pytrace=False)

# 2. Anti-cribbing checker: ban real R611Q/PMIDs, allow legitimate terms.
def assert_no_cribbing(obj):
    forbidden_ids = [
        "pmc11185720",
        "10.1101/2024.06.07.597916",
        "c.1832G>A",
        "p.Arg611Gln"
    ]
    if isinstance(obj, str):
        for f in forbidden_ids:
            assert f not in obj.lower(), f"Anti-cribbing violation: found real-content phrase '{f}' in '{obj}'"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_cribbing(k)
            assert_no_cribbing(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            assert_no_cribbing(item)


def test_static_ast_import_guards():
    """Verify that raptor.atlas package has static AST-based import guards."""
    check_implemented()
    # 1. Assert assert_atlas_import_boundary checks actual files on disk
    # and fails if the atlas source files do not exist yet (planned absence is RED).
    assert_atlas_import_boundary("src/raptor/atlas")


def test_static_ast_consumer_guards():
    """Verify that no consumer module imports raptor.atlas."""
    check_implemented()
    # 2. reverse check: ensure no packet/scorer/eval imports atlas
    assert_no_consumer_import("raptor.atlas")


def test_no_banned_criteria_or_leakage():
    """Verify that forbidden classifier values/scoring elements raise AtlasLeakageError."""
    check_implemented()
    # This is tested statically or dynamically within the profile build or candidate validation.
    # E.g. trying to inject classifier_score or PP3 as mechanism truth.
    # Let's ensure a test checks that the guards fail on banned elements.
    from raptor.atlas.guards import validate_mechanism_inputs
    with pytest.raises(AtlasLeakageError):
        validate_mechanism_inputs({"classifier_score": 0.9})
    with pytest.raises(AtlasLeakageError):
        validate_mechanism_inputs({"clinvar_derived_criterion": "PP3"})


def test_complete_mechanism_profile_and_hash_coherence():
    """Build complete MechanismProfile from spec with exact components, and assert hashing coherence."""
    check_implemented()

    # 1. Build constituent elements
    pack_binding = PackBinding(
        pack_id="synthpack",
        pack_version="1.0.0",
        pack_content_hash="9fa7643161ea0d8741ce8ffe0169f1f0109300a93c61cb5037cb86ca5abd7377"
    )

    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T",
        gene="SYNGENE1",
        assembly="GRCh38",
        transcript_pin="NM_900001.1",
        hgvs_c="c.100A>T",
        hgvs_p="p.Lys34Met",
        hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    span1 = Span(locator="Fig 1", exact_quote="synthetic quote A", page_or_figure="10")
    ref1 = EntryRef(entry_id="synthsrc-0001", span=span1)
    claim1 = ObservedClaim(
        claim_id="claim-1",
        claim_text="synthetic assay signal A",
        claim_kind="pathway",
        source_ref=ref1,
        verification="verified",
        directionality="increase"
    )

    span2 = Span(locator="Fig 2", exact_quote="synthetic quote B", page_or_figure="11")
    ref2 = EntryRef(entry_id="synthsrc-0001", span=span2)
    claim2 = ObservedClaim(
        claim_id="claim-2",
        claim_text="synthetic assay signal B",
        claim_kind="pathway",
        source_ref=ref2,
        verification="verified",
        directionality="decrease"
    )

    # Clean up verification (fixtures must be clearly synthetic)
    assert_no_cribbing(claim1.__dict__)
    assert_no_cribbing(claim2.__dict__)

    # 2. Build candidate classes
    cc1 = CandidateClass(class_id="reduced_abundance_instability", state="supported", confidence="high")
    cc2 = CandidateClass(class_id="mislocalization", state="supported", confidence="moderate")

    # 3. Build edges
    context = ContextRecord(
        assay="abundance-seq",
        model_system="cell line",
        cell_type="HEK293",
        tissue="kidney",
        zygosity_context="germline",
        assay_limitations=("power-limit",)
    )

    edge = MechanismEdge(
        from_layer="protein_abundance",
        to_layer="protein_stability",
        effect="decrease",
        supporting_claims=("claim-1",),
        contradicting_claims=(),
        context=context,
        edge_state="supported"
    )

    # 4. Build evidence assessment
    evidence = EvidenceAssessment(
        supporting=("claim-1", "claim-2"),
        contradicting=(),
        missing_evidence=("co-IP-assay",),
        unknowns=()
    )

    # 5. Build provenance (No pack_binding!)
    provenance = Provenance(
        source_pins=(ref1, ref2),
        version_pins=("v1.0",),
        content_hashes={"evidence_core_hash": "placeholder_core", "profile_envelope_hash": "placeholder_env"}
    )

    # 6. Build run metadata (With pack_binding_audit copy that matches profile.pack_binding)
    run_metadata = RunMetadata(
        run_id="run-001",
        generated_at="2026-07-23T01:10:00Z",
        tool_versions=("v1.0",),
        pack_binding_audit=pack_binding
    )

    # Assemble the full MechanismProfile
    profile = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(claim1, claim2),
        candidate_classes=(cc1, cc2),
        edges=(edge,),
        evidence=evidence,
        provenance=provenance,
        run_metadata=run_metadata
    )

    # Core and envelope hashing over this profile
    h_core1 = evidence_core_hash(profile)
    h_env1 = profile_envelope_hash(profile)

    # Assert run_metadata is excluded from hashes:
    # Build a profile with changed metadata (different run_id and different pack_binding_audit which matches too)
    run_metadata_changed = RunMetadata(
        run_id="run-002",
        generated_at="2026-07-23T02:00:00Z",
        tool_versions=("v1.0.1",),
        pack_binding_audit=pack_binding
    )
    profile_meta_changed = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(claim1, claim2),
        candidate_classes=(cc1, cc2),
        edges=(edge,),
        evidence=evidence,
        provenance=provenance,
        run_metadata=run_metadata_changed
    )

    assert evidence_core_hash(profile_meta_changed) == h_core1, "Core hash must exclude run_metadata"
    assert profile_envelope_hash(profile_meta_changed) == h_env1, "Envelope hash must exclude run_metadata"

    # Assert pack_binding swap changes both hashes (fail closed under wrong pack)
    different_pack_binding = PackBinding(
        pack_id="synthpack",
        pack_version="1.0.1",  # mutated version
        pack_content_hash="different_content_hash"
    )
    different_run_metadata = RunMetadata(
        run_id="run-001",
        generated_at="2026-07-23T01:10:00Z",
        tool_versions=("v1.0",),
        pack_binding_audit=different_pack_binding
    )
    profile_wrong_pack = MechanismProfile(
        identity=identity,
        pack_binding=different_pack_binding,
        claims=(claim1, claim2),
        candidate_classes=(cc1, cc2),
        edges=(edge,),
        evidence=evidence,
        provenance=provenance,
        run_metadata=different_run_metadata
    )

    assert evidence_core_hash(profile_wrong_pack) != h_core1, "Swapping pack_binding must change core hash"
    assert profile_envelope_hash(profile_wrong_pack) != h_env1, "Swapping pack_binding must change envelope hash"


def test_run_metadata_audit_mismatch_raises():
    """Verify that a mismatch between run_metadata.pack_binding_audit and profile.pack_binding raises AtlasSchemaError."""
    check_implemented()

    pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash"
    )
    different_pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.1", pack_content_hash="mock_hash"
    )

    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    run_metadata_mismatch = RunMetadata(
        run_id="run-001", generated_at="2026-07-23T01:10:00Z", tool_versions=("v1.0",),
        pack_binding_audit=different_pack_binding  # Mismatches!
    )

    with pytest.raises(AtlasSchemaError):
        MechanismProfile(
            identity=identity,
            pack_binding=pack_binding,
            claims=(),
            candidate_classes=(),
            edges=(),
            evidence=EvidenceAssessment((), (), (), ()),
            provenance=Provenance((), (), {}),
            run_metadata=run_metadata_mismatch
        )


def test_dangling_claims_rejected():
    """Verify that dangling claim references in edges or evidence are rejected with AtlasSchemaError."""
    check_implemented()

    pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash"
    )
    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    good_span = Span(locator="Fig 1", exact_quote="synthetic quote A", page_or_figure="10")
    ref = EntryRef(entry_id="synthsrc-0001", span=good_span)
    claim = ObservedClaim(
        claim_id="claim-1", claim_text="synthetic assay signal A", claim_kind="pathway",
        source_ref=ref, verification="verified", directionality="increase"
    )

    # 1. Edge references dangling claim-nonexistent
    bad_edge = MechanismEdge(
        from_layer="protein_abundance", to_layer="protein_stability", effect="decrease",
        supporting_claims=("claim-nonexistent",), contradicting_claims=(),
        context=ContextRecord("assay", "system", None, None, "germline", ()),
        edge_state="supported"
    )

    with pytest.raises(AtlasSchemaError):
        MechanismProfile(
            identity=identity,
            pack_binding=pack_binding,
            claims=(claim,),
            candidate_classes=(),
            edges=(bad_edge,),
            evidence=EvidenceAssessment(("claim-1",), (), (), ()),
            provenance=Provenance((), (), {}),
            run_metadata=None
        )

    # 2. Evidence assessment references dangling claim-nonexistent
    bad_evidence = EvidenceAssessment(
        supporting=("claim-nonexistent",), contradicting=(), missing_evidence=(), unknowns=()
    )

    with pytest.raises(AtlasSchemaError):
        MechanismProfile(
            identity=identity,
            pack_binding=pack_binding,
            claims=(claim,),
            candidate_classes=(),
            edges=(),
            evidence=bad_evidence,
            provenance=Provenance((), (), {}),
            run_metadata=None
        )


def test_one_way_dismech_export():
    """Verify DisMech export contract, target schema, and pack_binding equality validation."""
    check_implemented()

    pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash"
    )
    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )
    profile = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(),
        candidate_classes=(),
        edges=(),
        evidence=EvidenceAssessment((), (), (), ()),
        provenance=Provenance((), (), {}),
        run_metadata=None
    )

    record = export_dismech(profile)
    assert isinstance(record, DisMechRecord)
    assert record.spdi_canonical == "NC_000000.0:1000:A:T"
    assert record.pack_binding == pack_binding
    assert_no_cribbing(record.__dict__)

