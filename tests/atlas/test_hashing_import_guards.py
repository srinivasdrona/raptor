"""
Gemini RED tests for Mechanism Atlas: Hashing and Import Guards (Revised)
Spec coverage:
- Build complete valid synthetic MechanismProfile fields from spec.
- Hash coherence: exclude run_metadata, canonical order/dedup claims, source_ref.span is hash source.
- Dangling claim refs in edges/evidence are rejected.
- Leakage guards: no packet/scorer/eval imports, no consumer imports atlas, no classifier/ClinVar truth.
- One-way DisMech export precondition and contract.
"""

import sys
import pytest

# 1. Guard planned imports so all tests collect
try:
    from raptor.atlas.model import (
        MechanismProfile,
        AtlasIdentity,
        ObservedClaim,
        EntryRef,
        DisMechRecord,
        AtlasLeakageError,
        AtlasExportError,
        AtlasSchemaError,
    )
    from raptor.atlas.hashing import (
        evidence_core_hash,
        profile_envelope_hash,
        claim_hash,
    )
    from raptor.atlas.export import export_dismech
    IMPLEMENTED = True
except (ImportError, ModuleNotFoundError):
    MechanismProfile = None
    AtlasIdentity = None
    ObservedClaim = None
    EntryRef = None
    DisMechRecord = None
    AtlasLeakageError = ValueError
    AtlasExportError = RuntimeError
    AtlasSchemaError = ValueError
    evidence_core_hash = None
    profile_envelope_hash = None
    claim_hash = None
    export_dismech = None
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

def test_atlas_import_guards():
    """Verify that raptor.atlas does not import packet/scorer/eval or Discovery SDKs."""
    forbidden = ["raptor.packet", "raptor.scorer", "raptor.eval", "microsoft_discovery_sdk", "discovery_agent_client"]
    import sys
    for mod in forbidden:
        assert mod not in sys.modules or sys.modules[mod] is None


def test_consumer_import_guards():
    check_implemented()
    from raptor.atlas.guards import assert_no_consumer_import
    with pytest.raises(AtlasLeakageError):
        assert_no_consumer_import("raptor.scorer")


def test_no_classifier_or_clinvar_as_truth():
    check_implemented()
    from raptor.atlas.guards import validate_mechanism_inputs
    with pytest.raises(AtlasLeakageError):
        validate_mechanism_inputs({"classifier_score": 0.85})
    with pytest.raises(AtlasLeakageError):
        validate_mechanism_inputs({"clinvar_derived_criterion": "PP3"})


def test_hash_coherence_and_exclusions():
    check_implemented()
    # 6. Hash tests build complete valid synthetic MechanismProfile fields from spec
    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:33333:A:C",
        gene="TSC2",
        transcript_pin="NM_000548.5",
        hgvs_c="c.200A>C",
        hgvs_p="p.Lys67Gln",
        hgvs_g="g.33333A>C",
        identity_state="resolved"
    )
    
    ref1 = EntryRef(entry_id="lit-1", span={"locator": "Fig1", "exact_quote": "synthetic assay signal A", "page_or_figure": "3"})
    claim1 = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:33333:A:C",
        source_ref=ref1,
        statement="synthetic assay signal A",
        verification="verified"
    )

    ref2 = EntryRef(entry_id="lit-1", span={"locator": "Fig2", "exact_quote": "synthetic assay signal B", "page_or_figure": "4"})
    claim2 = ObservedClaim(
        claim_id="claim-2",
        variant_id="NC_000016.10:33333:A:C",
        source_ref=ref2,
        statement="synthetic assay signal B",
        verification="verified"
    )

    assert_no_cribbing(claim1.__dict__)
    assert_no_cribbing(claim2.__dict__)

    # Build MechanismProfile with all fields: identity, claims, candidate_classes, edges, evidence, provenance, run_metadata
    profile1 = MechanismProfile(
        identity=identity,
        claims=(claim1, claim2),
        candidate_classes=("class-A",),
        edges=({"source_claim": "claim-1", "target_claim": "claim-2"},),
        evidence=({"claim_id": "claim-1"},),
        provenance=({"provenance_key": "val"},),
        run_metadata={"timestamp": "2026-07-22T09:00:00", "operator": "synthetic-agent"}
    )

    profile2 = MechanismProfile(
        identity=identity,
        claims=(claim2, claim1),  # reverse claims order to assert canonical ordering / dedup
        candidate_classes=("class-A",),
        edges=({"source_claim": "claim-1", "target_claim": "claim-2"},),
        evidence=({"claim_id": "claim-1"},),
        provenance=({"provenance_key": "val"},),
        run_metadata={"timestamp": "2026-07-22T12:00:00", "operator": "different-synthetic-agent"}  # changed metadata
    )

    # Core hash excludes run_metadata and enforces canonical claims ordering/dedup
    h1_core = evidence_core_hash(profile1)
    h2_core = evidence_core_hash(profile2)
    assert h1_core == h2_core, "Core hash must be identical under canonical claims ordering and run_metadata exclusion"

    # Profile envelope hash must also exclude run_metadata and be deterministic
    h1_env = profile_envelope_hash(profile1)
    h2_env = profile_envelope_hash(profile2)
    assert h1_env == h2_env, "Envelope hash must exclude run_metadata"

    # Changing span changes claim and profile hash
    ref1_mutated = EntryRef(entry_id="lit-1", span={"locator": "Fig1-mutated", "exact_quote": "synthetic assay signal A", "page_or_figure": "3"})
    claim1_mutated = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:33333:A:C",
        source_ref=ref1_mutated,
        statement="synthetic assay signal A",
        verification="verified"
    )
    profile_mutated = MechanismProfile(
        identity=identity,
        claims=(claim1_mutated, claim2),
        candidate_classes=("class-A",),
        edges=({"source_claim": "claim-1", "target_claim": "claim-2"},),
        evidence=({"claim_id": "claim-1"},),
        provenance=({"provenance_key": "val"},),
        run_metadata=None
    )
    assert claim_hash(claim1) != claim_hash(claim1_mutated), "Claim hash must read source_ref.span"
    assert evidence_core_hash(profile1) != evidence_core_hash(profile_mutated), "Profile hash must change when source_ref.span changes"


def test_dangling_claim_references_rejected():
    check_implemented()
    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:33333:A:C",
        gene="TSC2",
        transcript_pin="NM_000548.5",
        hgvs_c="c.200A>C",
        hgvs_p="p.Lys67Gln",
        hgvs_g="g.33333A>C",
        identity_state="resolved"
    )
    ref = EntryRef(entry_id="lit-1", span={"locator": "Fig1", "exact_quote": "synthetic assay signal A", "page_or_figure": "3"})
    claim = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:33333:A:C",
        source_ref=ref,
        statement="synthetic assay signal A",
        verification="verified"
    )
    
    # MechanismProfile has a claim reference "claim-nonexistent" in edges/evidence which is not in profile.claims
    with pytest.raises(AtlasSchemaError):
        MechanismProfile(
            identity=identity,
            claims=(claim,),
            candidate_classes=(),
            edges=({"source_claim": "claim-nonexistent", "target_claim": "claim-1"},),  # dangling claim ref
            evidence=(),
            provenance=(),
            run_metadata=None
        )


def test_one_way_dismech_export():
    check_implemented()
    # Test export precondition (profile must be valid/clean) and structure
    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:33333:A:C",
        gene="TSC2",
        transcript_pin="NM_000548.5",
        hgvs_c="c.200A>C",
        hgvs_p="p.Lys67Gln",
        hgvs_g="g.33333A>C",
        identity_state="resolved"
    )
    ref = EntryRef(entry_id="lit-1", span={"locator": "Fig1", "exact_quote": "synthetic assay signal A", "page_or_figure": "3"})
    claim = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:33333:A:C",
        source_ref=ref,
        statement="synthetic assay signal A",
        verification="verified"
    )
    profile = MechanismProfile(
        identity=identity,
        claims=(claim,),
        candidate_classes=(),
        edges=(),
        evidence=(),
        provenance=(),
        run_metadata=None
    )
    
    record = export_dismech(profile)
    assert isinstance(record, DisMechRecord)
    assert record.variant_id == "NC_000016.10:33333:A:C"
    assert_no_cribbing(record.__dict__)
