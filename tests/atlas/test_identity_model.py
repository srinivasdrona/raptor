"""
Gemini RED tests for Mechanism Atlas: Identity Model (Revised)
Spec coverage:
- Schema shape + frozen/immutability + typed-error discrimination.
- Match exact spec fields: AtlasIdentity uses spdi_canonical, gene, transcript_pin, hgvs_c, hgvs_p, hgvs_g, identity_state (not status).
- Resolved identity requires canonical GRCh38 spdi_canonical; unresolved/alias-only cannot admit.
- SPDI-keyed transcript reconciliation via injected resolver.
- Unknown/conflicting/context-dependent profiles remain distinct.
"""

import pytest
from dataclasses import is_dataclass, fields

# 1. Guard planned imports so all tests collect
try:
    from raptor.atlas.model import (
        AtlasIdentity,
        AtlasSchemaError,
        AtlasIdentityError,
    )
    from raptor.atlas.identity import reconcile_transcript
    IMPLEMENTED = True
except (ImportError, ModuleNotFoundError):
    # Fallbacks for metadata reflection only so tests collect
    AtlasIdentity = None
    AtlasSchemaError = ValueError
    AtlasIdentityError = RuntimeError
    reconcile_transcript = None
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

def test_schema_shape_and_immutability():
    check_implemented()
    assert is_dataclass(AtlasIdentity)
    
    # 3. Match exact spec fields: spdi_canonical, gene, transcript_pin, hgvs_c, hgvs_p, hgvs_g, identity_state
    field_names = {f.name for f in fields(AtlasIdentity)}
    expected_fields = {"spdi_canonical", "gene", "transcript_pin", "hgvs_c", "hgvs_p", "hgvs_g", "identity_state"}
    assert expected_fields.issubset(field_names), f"Missing fields in AtlasIdentity: {expected_fields - field_names}"
    assert "status" not in field_names, "AtlasIdentity must use 'identity_state', not 'status'"

    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:11111:A:T",
        gene="TSC2",
        transcript_pin="NM_000548.5",
        hgvs_c="c.100A>T",
        hgvs_p="p.Lys34Met",
        hgvs_g="g.11111A>T",
        identity_state="resolved"
    )
    assert_no_cribbing(identity.__dict__)
    
    with pytest.raises(Exception):
        identity.identity_state = "unresolved"  # type: ignore


def test_resolved_identity_requires_canonical_spdi():
    check_implemented()
    # Resolved admission requires canonical GRCh38 spdi_canonical; aliases cannot admit
    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:11111:A:T",
        gene="TSC2",
        transcript_pin="NM_000548.5",
        hgvs_c="c.100A>T",
        hgvs_p="p.Lys34Met",
        hgvs_g="g.11111A>T",
        identity_state="resolved"
    )
    assert identity.spdi_canonical == "NC_000016.10:11111:A:T"
    assert_no_cribbing(identity.__dict__)

    # Unresolved/alias-only cannot admit (raises AtlasIdentityError)
    with pytest.raises(AtlasIdentityError):
        AtlasIdentity(
            spdi_canonical=None,
            gene="TSC2",
            transcript_pin="NM_000548.5",
            hgvs_c="c.100A>T",
            hgvs_p="p.Lys34Met",
            hgvs_g="g.11111A>T",
            identity_state="resolved"
        )


def test_transcript_reconciliation_by_resolver():
    check_implemented()
    # Test transcript reconciliation keyed by injected resolver/SPDI, never assert bare c. equality.
    def fake_resolver(spdi: str, transcript: str) -> bool:
        assert_no_cribbing(spdi)
        assert_no_cribbing(transcript)
        return spdi == "NC_000016.10:11111:A:T" and transcript == "NM_000548.5"

    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:11111:A:T",
        gene="TSC2",
        transcript_pin="NM_000548.5",
        hgvs_c="c.100A>T",
        hgvs_p="p.Lys34Met",
        hgvs_g="g.11111A>T",
        identity_state="resolved"
    )
    assert_no_cribbing(identity.__dict__)

    # Reconciling with matching transcript should succeed using fake_resolver
    reconciled = reconcile_transcript(identity, "NM_000548.5", resolver=fake_resolver)
    assert reconciled is True

    # Reconciling with mismatching transcript should fail
    with pytest.raises(AtlasIdentityError):
        reconcile_transcript(identity, "NM_999999.1", resolver=fake_resolver)


def test_unknown_and_conflicting_states_remain_distinct():
    check_implemented()
    # Unknown/conflicting/context-dependent profiles remain distinct and do not coerce
    id_unknown = AtlasIdentity(
        spdi_canonical="NC_000016.10:11111:A:T",
        gene="TSC2",
        transcript_pin="NM_000548.5",
        hgvs_c="c.100A>T",
        hgvs_p="p.Lys34Met",
        hgvs_g="g.11111A>T",
        identity_state="unknown"
    )
    
    id_conflict = AtlasIdentity(
        spdi_canonical="NC_000016.10:11111:A:G",
        gene="TSC2",
        transcript_pin="NM_000548.5",
        hgvs_c="c.100A>G",
        hgvs_p="p.Lys34Arg",
        hgvs_g="g.11111A>G",
        identity_state="conflicting"
    )
    
    assert id_unknown != id_conflict
    assert id_unknown.identity_state == "unknown"
    assert id_conflict.identity_state == "conflicting"
    assert_no_cribbing(id_unknown.__dict__)
    assert_no_cribbing(id_conflict.__dict__)


def test_typed_error_discrimination():
    check_implemented()
    # Verify typed errors exist and inherit correctly
    with pytest.raises(AtlasIdentityError):
        raise AtlasIdentityError("Identity error")

    with pytest.raises(AtlasSchemaError):
        raise AtlasSchemaError("Schema error")

    assert issubclass(AtlasIdentityError, Exception)
    assert issubclass(AtlasSchemaError, Exception)
