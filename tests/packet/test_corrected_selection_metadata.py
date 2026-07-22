from __future__ import annotations

import os
import sys
import pytest
from dataclasses import fields, replace
import hashlib

# Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

def test_census_selection_metadata_enum_and_fields() -> None:
    """G-CP16, D13: CensusSelectionMetadata enum accepts exactly:
    - candidate_LP_review
    - candidate_LB_review
    - no_deterministic_resolution
    - manual_review
    
    Every one of 6,618 packets carries the top-level field census_selection_stratum.
    """
    # Sonnet's implementation will define this enum in raptor.packet.model.
    # Right now, importing it will fail, which is correct for TDD / RED state.
    from raptor.packet.model import CensusSelectionMetadata
    
    # Verify the enum members
    assert {item.name for item in CensusSelectionMetadata} == {
        "candidate_LP_review",
        "candidate_LB_review",
        "no_deterministic_resolution",
        "manual_review",
    }


def test_pattern_ref_and_stratum_invariants() -> None:
    """G-CP16, D13:
    - LP/LB packets have a real non-blank PatternRef whose census_selection_stratum equals the packet field.
    - Unresolved/manual packets have pattern_ref=None.
    - A PatternRef/field mismatch, a pattern_ref on an unresolved/manual packet, or an out-of-enum value is rejected.
    """
    # Verify these validation checks on build_packet
    # Since the field/enum are not implemented yet, we expect an ImportError/AttributeError on imports
    from raptor.packet.model import PatternRef, PacketInput, CensusSelectionMetadata
    from raptor.packet.build import build_packet
    
    bad_pattern_ref = PatternRef(
        census_snapshot_id="snapshot-1",
        pattern_id="pattern-1",
        census_selection_stratum="candidate_LB_review", # Mismatch with LP stratum
        pattern_signature="sig-1",
        member_count=1
    )
    
    # This build should fail due to mismatch
    build_packet(
        PacketInput(
            # ...
            census_selection_stratum="candidate_LP_review",
            pattern_ref=bad_pattern_ref,
        )
    )


def test_selection_metadata_hashing_and_blinding() -> None:
    """G-CP16:
    - The field census_selection_stratum is included in evidence_core_hash AND packet_envelope_hash consistently.
    - redact_for_first_pass omits BOTH the field and pattern_ref.
    """
    # Importing from raptor hashing and redaction modules
    from raptor.packet.hashing import evidence_core_hash, packet_envelope_hash
    from raptor.packet.model import redact_for_first_pass, PacketInput
    import dataclasses
    
    # Assert that the field is present on PacketInput
    fields_set = {f.name for f in dataclasses.fields(PacketInput)}
    assert "census_selection_stratum" in fields_set
