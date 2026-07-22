"""
Gemini RED tests for Mechanism Atlas: Identity Model
Spec coverage:
- Schema shape + frozen/immutability + typed-error discrimination for every schema.
- Resolved identity requires canonical GRCh38 spdi_canonical; aliases cannot admit.
- Alias-only / missing-SPDI records are unresolved and admission raises AtlasIdentityError.
- SPDI-keyed transcript reconciliation.
- Unknown/conflicting/context-dependent profiles remain distinct.
"""

import pytest
from dataclasses import is_dataclass

from raptor.atlas.model import (
    AtlasIdentity,
    AtlasSchemaError,
    AtlasIdentityError,
)

def test_schema_shape_and_immutability():
    """Verify that AtlasIdentity is a frozen dataclass."""
    assert is_dataclass(AtlasIdentity)
    
    # Check that it is frozen
    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:2083921:G:A",
        hgvs_c="c.1831G>A",
        hgvs_p="p.Arg611Gln",
        transcript_pin="NM_000548.5",
        status="resolved"
    )
    
    with pytest.raises(Exception):
        identity.status = "unresolved"  # type: ignore


def test_resolved_identity_requires_canonical_spdi():
    """Resolved admission requires canonical GRCh38 spdi_canonical; aliases cannot admit."""
    # Canonical GRCh38 SPDI-based identity works
    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:2083921:G:A",
        hgvs_c="c.1831G>A",
        hgvs_p="p.Arg611Gln",
        transcript_pin="NM_000548.5",
        status="resolved"
    )
    assert identity.spdi_canonical == "NC_000016.10:2083921:G:A"
    
    # Missing/invalid spdi_canonical must fail admission and raise AtlasIdentityError
    with pytest.raises(AtlasIdentityError):
        # Missing spdi_canonical entirely
        AtlasIdentity(
            spdi_canonical=None,
            hgvs_c="c.1831G>A",
            hgvs_p="p.Arg611Gln",
            transcript_pin="NM_000548.5",
            status="resolved"
        )

    with pytest.raises(AtlasIdentityError):
        # Invalid SPDI format
        AtlasIdentity(
            spdi_canonical="invalid-spdi",
            hgvs_c="c.1831G>A",
            hgvs_p="p.Arg611Gln",
            transcript_pin="NM_000548.5",
            status="resolved"
        )


def test_transcript_reconciliation():
    """Verify SPDI-keyed transcript reconciliation behaves correctly."""
    # Real logic in identity.py will reconcile transcripts via SPDI mapping.
    # The test contract expects that a reconciliation function exists or identity handles it.
    from raptor.atlas.identity import reconcile_transcript
    
    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:2083921:G:A",
        hgvs_c="c.1831G>A",
        hgvs_p="p.Arg611Gln",
        transcript_pin="NM_000548.5",
        status="resolved"
    )
    
    # Reconciling with matching transcript should succeed
    reconciled = reconcile_transcript(identity, "NM_000548.5")
    assert reconciled is True

    # Reconciling with mismatching transcript should fail
    with pytest.raises(AtlasIdentityError):
        reconcile_transcript(identity, "NM_123456.1")


def test_unknown_and_conflicting_states_remain_distinct():
    """Unknown, conflicting, and context-dependent profiles must remain distinct and not coerce."""
    # We should be able to instantiate distinct identities/states representing unknown or conflicting data.
    id_unknown = AtlasIdentity(
        spdi_canonical="NC_000016.10:2083921:G:A",
        hgvs_c="c.1831G>A",
        hgvs_p="p.Arg611Gln",
        transcript_pin="NM_000548.5",
        status="unknown"
    )
    
    id_conflict = AtlasIdentity(
        spdi_canonical="NC_000016.10:2083921:G:T",
        hgvs_c="c.1831G>T",
        hgvs_p="p.Arg611Leu",
        transcript_pin="NM_000548.5",
        status="conflicting"
    )
    
    assert id_unknown != id_conflict
    assert id_unknown.status == "unknown"
    assert id_conflict.status == "conflicting"


def test_typed_error_discrimination():
    """Verify that typed errors discriminate and subclass correctly."""
    with pytest.raises(AtlasIdentityError):
        raise AtlasIdentityError("Identity error")

    with pytest.raises(AtlasSchemaError):
        raise AtlasSchemaError("Schema error")

    # They should inherit from a generic AtlasException or RuntimeError
    assert issubclass(AtlasIdentityError, RuntimeError)
    assert issubclass(AtlasSchemaError, ValueError) or issubclass(AtlasSchemaError, RuntimeError)
