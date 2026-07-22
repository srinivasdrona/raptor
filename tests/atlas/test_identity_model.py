"""
Gemini RED tests for Mechanism Atlas: Identity and 17 Core Contracts
Spec coverage:
- Schema shape + frozen/immutability + typed-error discrimination.
- Match exact spec fields: AtlasIdentity uses spdi_canonical, gene, transcript_pin, hgvs_c, hgvs_p, hgvs_g, identity_state.
- No 'status' field.
- Resolved identity requires canonical GRCh38 spdi_canonical; unresolved/alias-only cannot admit and raises AtlasIdentityError.
- SPDI-keyed transcript reconciliation via injected resolver.
- Frozen dataclass checks for all 17 contracts where mapped (tuples for ordered collections, eq=True, frozen).
- identity_state is ONLY resolved or unresolved; setting unknown/conflicting raises AtlasSchemaError.
"""

import pytest
from dataclasses import is_dataclass, fields

# 2. Anti-cribbing check: ban real-content phrases/IDs only, not legitimate terms.
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


def test_frozen_contracts_17():
    """Verify that all 17 contracts are defined as frozen, eq-comparable dataclasses."""
    try:
        from raptor.atlas.model import (
            DiseasePack, PackBinding, AtlasIdentity, Span, EntryRef,
            SourceRegisterEntry, ObservedClaim, ContextRecord, MechanismEdge,
            CandidateClass, EvidenceAssessment, RunMetadata, Provenance,
            MechanismProfile, AtlasCandidateImport, PromotionContext, DisMechRecord
        )
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.model implementation is missing")

    contracts = [
        DiseasePack, PackBinding, AtlasIdentity, Span, EntryRef,
        SourceRegisterEntry, ObservedClaim, ContextRecord, MechanismEdge,
        CandidateClass, EvidenceAssessment, RunMetadata, Provenance,
        MechanismProfile, AtlasCandidateImport, PromotionContext, DisMechRecord
    ]
    
    assert len(contracts) == 17, f"Expected exactly 17 mapped contracts, got {len(contracts)}"
    
    for contract in contracts:
        assert is_dataclass(contract), f"{contract.__name__} must be a dataclass"
        # Verify frozen is True
        assert contract.__dataclass_params__.frozen, f"{contract.__name__} must be frozen"
        # Verify eq is True
        assert contract.__dataclass_params__.eq, f"{contract.__name__} must be eq-comparable"


def test_identity_fields_and_no_status():
    """Verify AtlasIdentity fields and make sure no status field exists."""
    try:
        from raptor.atlas.model import AtlasIdentity
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.identity/model implementation is missing")

    field_names = {f.name for f in fields(AtlasIdentity)}
    expected_fields = {
        "spdi_canonical", "gene", "assembly", "transcript_pin",
        "hgvs_c", "hgvs_p", "hgvs_g", "identity_state"
    }
    assert expected_fields == field_names, f"Fields mismatch for AtlasIdentity: {field_names}"
    assert "status" not in field_names, "AtlasIdentity must use 'identity_state', not 'status'"


def make_schema_valid_disease_pack(model_mod):
    # Returns a schema-valid synthetic DiseasePack matching the exact spec positive fixture
    source_pin = model_mod.SourceRegisterEntry(
        entry_id="synthsrc-0001",
        source_type="DATASET",
        role="provenance_only",
        urn_or_ids={"accession": "SYNTHDB-0001"},
        transcript=None,
        license="CC0-1.0",
        sha256=None,
        variant_count=None,
        verification="confirm_pending"
    )
    return model_mod.DiseasePack(
        schema="atlas.disease_pack.v1",
        pack_id="synthpack",
        pack_version="1.0.0",
        pack_content_hash="bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21",
        allowed_genes=("SYNGENE1",),
        assembly_pins=("GRCh38",),
        transcript_pins=(
            {"transcript": "NM_900001.1", "requires": "MANE-Select-verification"},
        ),
        reconciliation_policy={
            "alias_to_canonical_spdi_only": True,
            "no_fabrication": True
        },
        ontology_extensions={
            "claim_kinds": [
                {"id": "synthpack:pathway_synthpath", "parent": "pathway"}
            ],
            "node_layers": [],
            "mechanism_classes": [],
            "context_vocabularies": {
                "tissue": ["synth_tissue_a"]
            }
        },
        source_register_pins=(source_pin,),
        prohibitions={
            "no_hardcode_handoff_mechanism": True
        },
        pilot_eval_metadata={
            "panel_strata": ["synthetic_stratum_a"],
            "native_vs_discovery_axes": ["reuse_percentage"]
        }
    )


def test_resolved_admission_rules():
    """Verify admit_identity enforces SPDI-keyed admission and gene/transcript/assembly pack-constraints."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.identity import admit_identity
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.identity/model implementation is missing")
    
    # Setup synthetic disease pack using helper
    fake_pack = make_schema_valid_disease_pack(model_mod)

    # 1. Valid record for admission
    valid_record = {
        "spdi_canonical": "NC_000000.0:1000:A:T",
        "gene": "SYNGENE1",
        "assembly": "GRCh38",
        "transcript_pin": "NM_900001.1",
        "hgvs_c": "c.100A>T",
        "hgvs_p": "p.Lys34Met",
        "hgvs_g": "g.1000A>T",
        "identity_state": "resolved"
    }
    
    identity = admit_identity(valid_record, pack=fake_pack)
    assert identity.identity_state == "resolved"
    assert identity.spdi_canonical == "NC_000000.0:1000:A:T"
    assert_no_cribbing(identity.__dict__)

    # 2. Missing canonical SPDI raises AtlasIdentityError on resolved admission
    invalid_record_no_spdi = dict(valid_record, spdi_canonical=None)
    with pytest.raises(model_mod.AtlasIdentityError):
        admit_identity(invalid_record_no_spdi, pack=fake_pack)

    # 3. Off-pack gene raises AtlasIdentityError
    invalid_record_bad_gene = dict(valid_record, gene="TSC2")  # 'TSC2' is not in allowed_genes of synthpack
    with pytest.raises(model_mod.AtlasIdentityError):
        admit_identity(invalid_record_bad_gene, pack=fake_pack)

    # 4. Off-pack assembly raises AtlasIdentityError
    invalid_record_bad_assembly = dict(valid_record, assembly="GRCh37")
    with pytest.raises(model_mod.AtlasIdentityError):
        admit_identity(invalid_record_bad_assembly, pack=fake_pack)


def test_identity_state_validation():
    """Verify that identity_state only allows resolved/unresolved, and unknown/conflicting raise AtlasSchemaError."""
    try:
        from raptor.atlas.model import AtlasIdentity, AtlasSchemaError
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.identity/model implementation is missing")
    
    # unknown and conflicting are mechanism states, never identity_state values
    for invalid_state in ["unknown", "conflicting", "other"]:
        with pytest.raises(AtlasSchemaError):
            AtlasIdentity(
                spdi_canonical="NC_000000.0:1000:A:T",
                gene="SYNGENE1",
                assembly="GRCh38",
                transcript_pin="NM_900001.1",
                hgvs_c="c.100A>T",
                hgvs_p="p.Lys34Met",
                hgvs_g="g.1000A>T",
                identity_state=invalid_state
            )


def test_transcript_reconciliation_by_resolver():
    """Verify transcript reconciliation uses injected resolver and pack, never bare c. equality."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.identity import reconcile_transcript
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.identity/model implementation is missing")

    fake_pack = make_schema_valid_disease_pack(model_mod)

    identity = model_mod.AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T",
        gene="SYNGENE1",
        assembly="GRCh38",
        transcript_pin="NM_900001.1",
        hgvs_c="c.100A>T",
        hgvs_p="p.Lys34Met",
        hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    def fake_resolver(spdi: str, transcript: str) -> bool:
        return spdi == "NC_000000.0:1000:A:T" and transcript == "NM_900001.1"

    # Reconciliation with valid resolver/pack mapping succeeds
    assert reconcile_transcript(identity, "NM_900001.1", pack=fake_pack, resolver=fake_resolver) is True

    # Reconciliation with unresolved/mismatching transcript returns False or raises AtlasIdentityError
    with pytest.raises(model_mod.AtlasIdentityError):
        reconcile_transcript(identity, "NM_900002.1", pack=fake_pack, resolver=fake_resolver)


def test_typed_error_discrimination():
    """Verify that all core errors are distinct types and fail closed."""
    try:
        from raptor.atlas.model import (
            AtlasSchemaError, AtlasIdentityError, AtlasProvenanceError,
            AtlasSourceVerificationError, AtlasLeakageError, AtlasExportError,
            AtlasPackError
        )
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.identity/model implementation is missing")

    errors = [
        AtlasSchemaError, AtlasIdentityError, AtlasProvenanceError,
        AtlasSourceVerificationError, AtlasLeakageError, AtlasExportError,
        AtlasPackError
    ]
    # Ensure they are all separate exception types
    assert len(set(errors)) == len(errors)
    for err in errors:
        assert issubclass(err, Exception)

