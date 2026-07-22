from __future__ import annotations

import os
import sys
import pytest
import dataclasses

import test_packet_core as core

# Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
# Copilot-Session: 7c146921-f3dd-4a1e-8cf0-8f574de49204

def _api():
    api = core._api()
    try:
        from raptor.packet.model import CensusSelectionMetadata, PatternRef
        from raptor.packet.build import build_packet
        from raptor.packet.hashing import evidence_core_hash, packet_envelope_hash
    except ImportError as exc:
        pytest.fail(f"Missing planned implementation: {exc}")
    api.update(locals())
    return api


def test_census_selection_metadata_enum_and_fields() -> None:
    """G-CP16, D13: CensusSelectionMetadata as spec's frozen value object with census_selection_stratum.
    Test all four values + invalid.
    """
    api = _api()
    CensusSelectionMetadata = api["CensusSelectionMetadata"]
    
    # Test all four valid values
    valid_values = [
        "candidate_LP_review",
        "candidate_LB_review",
        "no_deterministic_resolution",
        "manual_review",
    ]
    for val in valid_values:
        obj = CensusSelectionMetadata(census_selection_stratum=val)
        assert obj.census_selection_stratum == val
        
    # Test invalid value raises error
    with pytest.raises(Exception):
        CensusSelectionMetadata(census_selection_stratum="invalid_stratum")


def test_pattern_ref_and_stratum_invariants() -> None:
    """G-CP16, D13:
    - LP/LB packets have a real PatternRef whose census_selection_stratum equals the packet field.
    - Unresolved/manual packets have pattern_ref=None.
    - A PatternRef/field mismatch, a pattern_ref on an unresolved/manual packet, or an out-of-enum value is rejected.
    """
    api = _api()
    PatternRef = api["PatternRef"]
    CensusSelectionMetadata = api["CensusSelectionMetadata"]
    build_packet = api["build_packet"]
    
    # Reuse complete fixtures from test_packet_core
    complete_input = core._packet_input(api)
    config = core._packet_config(api)
    
    # 1. LP stratum packet with matching, valid PatternRef must succeed
    lp_metadata = CensusSelectionMetadata(census_selection_stratum="candidate_LP_review")
    # G-CP13/Finding 7: PatternRef.pattern_signature is tuple[str,...], never a string; member_count positive
    valid_lp_pattern = PatternRef(
        census_snapshot_id="clinvar_2026-07-07",
        pattern_id="LP-pattern-1",
        census_selection_stratum="candidate_LP_review",
        pattern_signature=("PVS1_supporting", "PM2_strong"),
        member_count=5
    )
    lp_input = dataclasses.replace(
        complete_input,
        census_selection_stratum=lp_metadata,
        pattern_ref=valid_lp_pattern
    )
    lp_packet = build_packet(lp_input, config)
    assert lp_packet.census_selection_stratum.census_selection_stratum == "candidate_LP_review"
    assert lp_packet.pattern_ref == valid_lp_pattern
    
    # 2. PatternRef/field mismatch (LP packet with LB PatternRef) must reject
    mismatched_pattern = PatternRef(
        census_snapshot_id="clinvar_2026-07-07",
        pattern_id="LB-pattern-1",
        census_selection_stratum="candidate_LB_review",  # LB mismatch
        pattern_signature=("BP4_strong",),
        member_count=2
    )
    mismatched_input = dataclasses.replace(
        complete_input,
        census_selection_stratum=lp_metadata,
        pattern_ref=mismatched_pattern
    )
    with pytest.raises(api["PacketValidationError"]):
        build_packet(mismatched_input, config)
        
    # 3. Unresolved/manual packets with pattern_ref=None must succeed
    unresolved_metadata = CensusSelectionMetadata(census_selection_stratum="no_deterministic_resolution")
    unresolved_input = dataclasses.replace(
        complete_input,
        census_selection_stratum=unresolved_metadata,
        pattern_ref=None
    )
    unresolved_packet = build_packet(unresolved_input, config)
    assert unresolved_packet.pattern_ref is None
    
    # 4. Unresolved/manual packets with a pattern_ref (non-None) must reject
    invalid_unresolved_input = dataclasses.replace(
        complete_input,
        census_selection_stratum=unresolved_metadata,
        pattern_ref=valid_lp_pattern
    )
    with pytest.raises(api["PacketValidationError"]):
        build_packet(invalid_unresolved_input, config)

    # 5. Finding 7: PatternRef rejects string pattern_signature or non-positive member_count
    with pytest.raises(Exception):
        PatternRef(
            census_snapshot_id="clinvar_2026-07-07",
            pattern_id="LP-pattern-1",
            census_selection_stratum="candidate_LP_review",
            pattern_signature="PVS1_supporting",  # rejected: must be tuple
            member_count=5
        )
        
    with pytest.raises(Exception):
        PatternRef(
            census_snapshot_id="clinvar_2026-07-07",
            pattern_id="LP-pattern-1",
            census_selection_stratum="candidate_LP_review",
            pattern_signature=("PVS1_supporting",),
            member_count=0  # rejected: must be positive (> 0)
        )


def test_selection_metadata_hashing_and_blinding() -> None:
    """G-CP16:
    - Assert corrected packet field changes evidence/envelope hashes.
    - redact_for_first_pass has neither metadata nor pattern_ref.
    """
    api = _api()
    PatternRef = api["PatternRef"]
    CensusSelectionMetadata = api["CensusSelectionMetadata"]
    build_packet = api["build_packet"]
    evidence_core_hash = api["evidence_core_hash"]
    packet_envelope_hash = api["packet_envelope_hash"]
    redact_for_first_pass = api["redact_for_first_pass"]
    
    # Reuse complete fixtures
    complete_input = core._packet_input(api)
    config = core._packet_config(api)
    
    lp_metadata = CensusSelectionMetadata(census_selection_stratum="candidate_LP_review")
    valid_lp_pattern = PatternRef(
        census_snapshot_id="clinvar_2026-07-07",
        pattern_id="LP-pattern-1",
        census_selection_stratum="candidate_LP_review",
        pattern_signature=("PVS1_supporting",),
        member_count=5
    )
    
    packet_lp = build_packet(
        dataclasses.replace(complete_input, census_selection_stratum=lp_metadata, pattern_ref=valid_lp_pattern),
        config
    )
    
    # Build packet with different stratum metadata to check hash change
    lb_metadata = CensusSelectionMetadata(census_selection_stratum="candidate_LB_review")
    valid_lb_pattern = PatternRef(
        census_snapshot_id="clinvar_2026-07-07",
        pattern_id="LB-pattern-1",
        census_selection_stratum="candidate_LB_review",
        pattern_signature=("BP4_supporting",),
        member_count=3
    )
    packet_lb = build_packet(
        dataclasses.replace(complete_input, census_selection_stratum=lb_metadata, pattern_ref=valid_lb_pattern),
        config
    )
    
    # Core and envelope hashes must differ because the field census_selection_stratum and pattern_ref are hash-bound
    assert evidence_core_hash(packet_lp) != evidence_core_hash(packet_lb)
    assert packet_envelope_hash(packet_lp) != packet_envelope_hash(packet_lb)
    
    # redact_for_first_pass must omit/strip both census_selection_stratum and pattern_ref
    blinded_view = redact_for_first_pass(packet_lp)
    assert not hasattr(blinded_view, "census_selection_stratum")
    assert not hasattr(blinded_view, "pattern_ref")
    assert not hasattr(blinded_view, "candidate_direction")
    assert not hasattr(blinded_view, "external_comparators")

