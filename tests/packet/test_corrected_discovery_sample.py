from __future__ import annotations

import os
import sys
import pytest
from types import SimpleNamespace

# Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
# Copilot-Session: 7c146921-f3dd-4a1e-8cf0-8f574de49204

def _api():
    try:
        from raptor.packet.corrected_universe import select_discovery_sample
    except ImportError as exc:
        pytest.fail(f"Missing planned implementation: {exc}")
    return locals()


def test_eight_case_discovery_sample_selection() -> None:
    """G-CP13: Deterministic eight-case sample is 2/2/2/2 across LP/LB/unresolved/manual from the full packet universe.
    Selection rule: within each stratum, sort the stratum's packets by canonical SPDI (byte order) and take the first two.
    """
    api = _api()
    select_discovery_sample = api["select_discovery_sample"]
    
    # 1. Define small SimpleNamespace/value-object packet fixtures
    # Packets expose packet_id, identity.canonical_spdi and census selection metadata (census_selection_stratum)
    packets = [
        # candidate_LP_review stratum
        SimpleNamespace(
            packet_id="lp-p1",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:100002:A:G"),
            census_selection_stratum=SimpleNamespace(census_selection_stratum="candidate_LP_review")
        ),
        SimpleNamespace(
            packet_id="lp-p2",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:100001:A:T"), # first in byte order
            census_selection_stratum=SimpleNamespace(census_selection_stratum="candidate_LP_review")
        ),
        SimpleNamespace(
            packet_id="lp-p3",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:100003:C:G"),
            census_selection_stratum=SimpleNamespace(census_selection_stratum="candidate_LP_review")
        ),
        SimpleNamespace(
            packet_id="lp-p4",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:100000:G:A"), # second in byte order
            census_selection_stratum=SimpleNamespace(census_selection_stratum="candidate_LP_review")
        ),
        
        # candidate_LB_review stratum
        SimpleNamespace(
            packet_id="lb-p1",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:200001:A:T"), # first
            census_selection_stratum=SimpleNamespace(census_selection_stratum="candidate_LB_review")
        ),
        SimpleNamespace(
            packet_id="lb-p2",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:200002:C:G"), # second
            census_selection_stratum=SimpleNamespace(census_selection_stratum="candidate_LB_review")
        ),
        SimpleNamespace(
            packet_id="lb-p3",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:200003:G:A"),
            census_selection_stratum=SimpleNamespace(census_selection_stratum="candidate_LB_review")
        ),
        
        # no_deterministic_resolution stratum
        SimpleNamespace(
            packet_id="unres-p1",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:300003:C:G"),
            census_selection_stratum=SimpleNamespace(census_selection_stratum="no_deterministic_resolution")
        ),
        SimpleNamespace(
            packet_id="unres-p2",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:300001:A:T"), # first
            census_selection_stratum=SimpleNamespace(census_selection_stratum="no_deterministic_resolution")
        ),
        SimpleNamespace(
            packet_id="unres-p3",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:300002:G:A"), # second
            census_selection_stratum=SimpleNamespace(census_selection_stratum="no_deterministic_resolution")
        ),
        
        # manual_review stratum
        SimpleNamespace(
            packet_id="man-p1",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:400002:C:G"), # second
            census_selection_stratum=SimpleNamespace(census_selection_stratum="manual_review")
        ),
        SimpleNamespace(
            packet_id="man-p2",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:400001:A:T"), # first
            census_selection_stratum=SimpleNamespace(census_selection_stratum="manual_review")
        ),
        SimpleNamespace(
            packet_id="man-p3",
            identity=SimpleNamespace(canonical_spdi="NC_000009.12:400003:G:A"),
            census_selection_stratum=SimpleNamespace(census_selection_stratum="manual_review")
        ),
    ]
    
    # 2. Call the sample selection
    selected = select_discovery_sample(packets)
    
    # 3. Assert exact 8 packet IDs (first two SPDI byte-order in each stratum), 2/2/2/2
    # Sorted SPDIs per stratum:
    # LP: NC_000009.12:100000:G:A (lp-p4), NC_000009.12:100001:A:T (lp-p2)
    # LB: NC_000009.12:200001:A:T (lb-p1), NC_000009.12:200002:C:G (lb-p2)
    # Unres: NC_000009.12:300001:A:T (unres-p2), NC_000009.12:300002:G:A (unres-p3)
    # Man: NC_000009.12:400001:A:T (man-p2), NC_000009.12:400002:C:G (man-p1)
    
    assert len(selected) == 8
    selected_ids = {p.packet_id for p in selected}
    expected_ids = {"lp-p4", "lp-p2", "lb-p1", "lb-p2", "unres-p2", "unres-p3", "man-p2", "man-p1"}
    assert selected_ids == expected_ids
    
    # 4. Permutation Invariance: shuffling input packets produces the exact same selected IDs
    shuffled_packets = list(reversed(packets))
    selected_shuffled = select_discovery_sample(shuffled_packets)
    assert {p.packet_id for p in selected_shuffled} == expected_ids
    
    # 5. Insufficient stratum fails closed: if we remove one manual packet so we only have 1 (less than 2 required), it fails
    insufficient_packets = [p for p in packets if p.packet_id != "man-p3" and p.packet_id != "man-p2"]
    with pytest.raises(Exception):
        select_discovery_sample(insufficient_packets)
        
    # 6. Verify no candidate_direction or comparator is read/queried on the dummy packets
    # (Since they are SimpleNamespace, trying to read candidate_direction would raise AttributeError if queried,
    # ensuring no machine classes or comparators leak during discovery sample selection).

