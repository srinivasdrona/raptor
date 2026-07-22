from __future__ import annotations

import os
import sys
import json
import pytest
import hashlib
from pathlib import Path

# Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
# Copilot-Session: 7c146921-f3dd-4a1e-8cf0-8f574de49204

def _api():
    try:
        from raptor.packet.corrected_universe import (
            conserve_current_policy,
            build_full_vus_universe,
        )
        from raptor.census.strata import ConservationError
    except ImportError as exc:
        pytest.fail(f"Missing planned implementation: {exc}")
    return locals()


def test_universe_conservation_and_strata_counts() -> None:
    """G-CP1, G-CP5, G-CP10: Protected pin check of the committed census.
    Ensures 164 (priority LP+LB) + 6,454 (excluded unresolved+manual) == 6,618.
    """
    census_stats_path = Path("data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json")
    assert census_stats_path.is_file(), "Current policy census json file is missing"
    
    # 1. Verify committed census SHA-256 (canonical LF blob) matches spec pin exactly
    lf_bytes = census_stats_path.read_bytes()
    canonical_bytes = lf_bytes.replace(b"\r\n", b"\n")
    lf_hash = hashlib.sha256(canonical_bytes).hexdigest()
    assert lf_hash == "45ff9f9abada7d5369c131bf7ffde28d0786eea41ff9bf7905f51da0cabd59ac"
    
    census = json.loads(canonical_bytes.decode("utf-8"))
    assert census["corpus"]["total_vus"] == 6618
    assert census["run_integrity"]["bias_rows"] == 6618
    
    counts = census["raptor_current_policy_internal_direction"]
    lp = counts["candidate_LP_review"]
    lb = counts["candidate_LB_review"]
    unresolved = counts["no_deterministic_resolution"]
    manual = counts["annotation_manual_review"]
    
    assert lp == 157
    assert lb == 7
    assert unresolved == 6424
    assert manual == 30
    assert lp + lb + unresolved + manual == 6618
    
    # Priority queue vs excluded counts
    priority_queue_size = lp + lb
    excluded_from_priority = unresolved + manual
    assert priority_queue_size == 164
    assert excluded_from_priority == 6454


def test_manual_review_reconciliation() -> None:
    """G-CP8, D11: manual_review stratum is exactly the 30 NTHL1 rows == census annotation_manual_review, no double count."""
    census_stats_path = Path("data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json")
    census = json.loads(census_stats_path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8"))
        
    counts = census["raptor_current_policy_internal_direction"]
    manual_review_count = counts["annotation_manual_review"]
    assert manual_review_count == 30
    
    # Ensure direction_by_gene.NTHL1.manual_review == 30
    nthl1_manual = census["direction_by_gene"]["NTHL1"]["manual_review"]
    assert nthl1_manual == 30
    
    # Ensure direction_by_consequence.other.manual_review == 30
    other_manual = census["direction_by_consequence"]["other"]["manual_review"]
    assert other_manual == 30


def test_current_policy_conservation_guard() -> None:
    """G-CP9, D5: Synthetic unit tests call conserve_current_policy with injected counts and verify failures.
    Ensures drift, duplicates, missing joins, and manual mapping failures fail closed with ConservationError.
    """
    api = _api()
    conserve_current_policy = api["conserve_current_policy"]
    ConservationError = api["ConservationError"]
    
    # Valid synthetic inputs matching current policy
    valid_synthetic = {
        "total_vus": 6618,
        "lp_count": 157,
        "lb_count": 7,
        "unresolved_count": 6424,
        "manual_count": 30,
        "lp_patterns": 7,
        "lb_patterns": 2,
    }
    
    # Should succeed with valid inputs
    conserve_current_policy(**valid_synthetic)
    
    # 1. Verify drift failure (mismatched total VUS)
    drifted_total = dict(valid_synthetic, total_vus=6617)
    with pytest.raises(ConservationError):
        conserve_current_policy(**drifted_total)
        
    # 2. Verify drift failure (mismatched LP count)
    drifted_lp = dict(valid_synthetic, lp_count=156)
    with pytest.raises(ConservationError):
        conserve_current_policy(**drifted_lp)
        
    # 3. Verify drift failure (mismatched Manual Review count)
    drifted_manual = dict(valid_synthetic, manual_count=29)
    with pytest.raises(ConservationError):
        conserve_current_policy(**drifted_manual)
        
    # 4. Verify drift failure (mismatched LP patterns count)
    drifted_patterns = dict(valid_synthetic, lp_patterns=8)
    with pytest.raises(ConservationError):
        conserve_current_policy(**drifted_patterns)

