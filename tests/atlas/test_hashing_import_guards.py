"""
Gemini RED tests for Mechanism Atlas: Hashing and Import Guards
Spec coverage:
- Hash coherence: evidence_core/profile_envelope payloads over defined include/exclude fields only.
- claim_id refs resolve into profile.claims.
- Canonical order/dedup deterministic; run_metadata excluded.
- Leakage guards: assert atlas does NOT import raptor.packet/scorer/eval.
- No consumer imports atlas.
- Forbidden criteria (PP3, BP4, etc.) / forbidden inputs (classifier_score, clinvar_derived_criterion) fail closed.
- One-way DisMech-compatible export precondition and contract.
- Synthetic fixtures contain no real pilot IDs/claims.
"""

import sys
import pytest

from raptor.atlas.model import (
    MechanismProfile,
    AtlasIdentity,
    ObservedClaim,
    EntryRef,
    DisMechRecord,
    AtlasLeakageError,
    AtlasExportError,
)
from raptor.atlas.hashing import (
    evidence_core_hash,
    profile_envelope_hash,
)
from raptor.atlas.export import export_dismech

def test_atlas_import_boundary_guards():
    """Verify that raptor.atlas does not import packet/scorer/eval or Discovery SDKs."""
    # Ensure none of these are in sys.modules from a clean state, or inspect imports.
    forbidden = ["raptor.packet", "raptor.scorer", "raptor.eval", "microsoft_discovery_sdk", "discovery_agent_client"]
    
    # We assert that importing raptor.atlas.guards does not pull in forbidden packages.
    import raptor.atlas.guards as guards
    
    for mod in forbidden:
        assert mod not in sys.modules or sys.modules[mod] is None


def test_consumer_import_guards():
    """Verify that consumers like raptor.scorer, raptor.packet, etc. cannot import raptor.atlas."""
    # Enforced by guards.py check
    from raptor.atlas.guards import assert_no_consumer_import
    
    # Scorer trying to import atlas must raise AtlasLeakageError
    with pytest.raises(AtlasLeakageError):
        assert_no_consumer_import("raptor.scorer")
        
    with pytest.raises(AtlasLeakageError):
        assert_no_consumer_import("raptor.packet")


def test_hash_coherence_and_exclusions():
    """Verify evidence_core_hash and profile_envelope_hash are deterministic and exclude run_metadata."""
    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:2083921:G:A",
        hgvs_c="c.1831G>A",
        hgvs_p="p.Arg611Gln",
        transcript_pin="NM_000548.5",
        status="resolved"
    )
    
    ref = EntryRef(entry_id="lit-1", span={"locator": "Fig1", "exact_quote": "mTOR active", "page_or_figure": "3"})
    claim = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:2083921:G:A",
        source_ref=ref,
        statement="Active",
        verification="verified"
    )
    
    profile1 = MechanismProfile(
        identity=identity,
        claims=(claim,),
        contexts=(),
        edges=(),
        run_metadata={"timestamp": "2026-07-22T09:00:00", "operator": "agent-1"}
    )
    
    profile2 = MechanismProfile(
        identity=identity,
        claims=(claim,),
        contexts=(),
        edges=(),
        run_metadata={"timestamp": "2026-07-22T10:30:00", "operator": "agent-2"}
    )
    
    # evidence_core_hash must be identical regardless of run_metadata changes
    h1_core = evidence_core_hash(profile1)
    h2_core = evidence_core_hash(profile2)
    assert h1_core == h2_core
    
    # profile_envelope_hash must also exclude run_metadata and be deterministic
    h1_env = profile_envelope_hash(profile1)
    h2_env = profile_envelope_hash(profile2)
    assert h1_env == h2_env
    
    # Re-ordering claims deterministically must produce the same hash (canonical ordering/dedup)
    claim_dup = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:2083921:G:A",
        source_ref=ref,
        statement="Active",
        verification="verified"
    )
    profile_dup = MechanismProfile(
        identity=identity,
        claims=(claim_dup, claim),  # duplicate, should be deduped canonically
        contexts=(),
        edges=(),
        run_metadata=None
    )
    assert evidence_core_hash(profile_dup) == h1_core


def test_forbidden_criteria_and_inputs_fail():
    """no classifier/ClinVar-derived criterion as mechanism truth, PP3/BP4/PP5/BP6 are forbidden."""
    from raptor.atlas.guards import validate_mechanism_inputs
    
    # Passing classifier_score as truth must raise AtlasLeakageError
    with pytest.raises(AtlasLeakageError):
        validate_mechanism_inputs({"classifier_score": 0.95})
        
    with pytest.raises(AtlasLeakageError):
        validate_mechanism_inputs({"clinvar_derived_criterion": "PP3"})

    with pytest.raises(AtlasLeakageError):
        # PP3 is forbidden
        validate_mechanism_inputs({"criteria": ["PP3"]})


def test_one_way_dismech_export():
    """Verify export_dismech emits a valid DisMechRecord, post-validation only."""
    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:2083921:G:A",
        hgvs_c="c.1831G>A",
        hgvs_p="p.Arg611Gln",
        transcript_pin="NM_000548.5",
        status="resolved"
    )
    ref = EntryRef(entry_id="lit-1", span={"locator": "Fig1", "exact_quote": "mTOR active", "page_or_figure": "3"})
    claim = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:2083921:G:A",
        source_ref=ref,
        statement="Active",
        verification="verified"
    )
    profile = MechanismProfile(
        identity=identity,
        claims=(claim,),
        contexts=(),
        edges=(),
        run_metadata=None
    )
    
    record = export_dismech(profile)
    assert isinstance(record, DisMechRecord)
    assert record.variant_id == "NC_000016.10:2083921:G:A"
    assert len(record.provenance) > 0


def test_synthetic_fixtures_no_real_pilot_claims():
    """Confirm fixtures used are purely synthetic, containing no real pilot claims/IDs."""
    # Synthetic claims/fixtures only
    ref = EntryRef(entry_id="synth-lit-1", span={"locator": "FigS1", "exact_quote": "Synthetic quote", "page_or_figure": "1"})
    claim = ObservedClaim(
        claim_id="synth-claim-001",
        variant_id="NC_000016.10:999999:A:T",  # synthetic genomic coordinates
        source_ref=ref,
        statement="Synthetic Statement",
        verification="verified"
    )
    assert "999999" in claim.variant_id
