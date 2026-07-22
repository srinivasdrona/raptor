from __future__ import annotations

import os
import sys
import json
import pytest
import hashlib
from pathlib import Path
from types import SimpleNamespace

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


def test_full_vus_universe_conservation() -> None:
    """Finding 4: Exercise planned full conserve_current_policy and build_full_vus_universe with synthetic fixtures."""
    api = _api()
    build_full_vus_universe = api["build_full_vus_universe"]
    conserve_current_policy = api["conserve_current_policy"]
    ConservationError = api["ConservationError"]
    
    # Construct small synthetic manifest/strata/BIAS-like fixtures
    # 4 items to represent all four strata: LP, LB, unresolved, manual_review
    manifest = [
        SimpleNamespace(vcf_key="chr1:100:A:T", gene="TSC1", annotation_manual_review=False),
        SimpleNamespace(vcf_key="chr1:200:G:C", gene="TSC1", annotation_manual_review=False),
        SimpleNamespace(vcf_key="chr1:300:T:A", gene="TSC1", annotation_manual_review=False),
        SimpleNamespace(vcf_key="chr1:400:C:G", gene="NTHL1", annotation_manual_review=True), # manual review mapping
    ]
    
    bias_records = [
        SimpleNamespace(vcf_key="chr1:100:A:T", criteria={"PVS1": "supporting"}),
        SimpleNamespace(vcf_key="chr1:200:G:C", criteria={"BP4": "supporting"}),
        SimpleNamespace(vcf_key="chr1:300:T:A", criteria={}),
        SimpleNamespace(vcf_key="chr1:400:C:G", criteria={}),
    ]
    
    # 1. Test successful building with perfect join and exact manual mapping
    # Conserve: 4 total VUS, 1 LP, 1 LB, 1 unresolved, 1 manual, 1 LP pattern, 1 LB pattern
    packets = build_full_vus_universe(
        manifest=manifest, 
        bias_records=bias_records, 
        source_hash="valid_hash",
        expected_total=4,
        expected_lp=1,
        expected_lb=1,
        expected_unresolved=1,
        expected_manual=1,
        expected_lp_patterns=1,
        expected_lb_patterns=1
    )
    assert len(packets) == 4
    
    # Verify unresolved and manual assembled with pattern_ref None
    for p in packets:
        if p.census_selection_stratum.census_selection_stratum in ("no_deterministic_resolution", "manual_review"):
            assert p.pattern_ref is None
            
    # Verify exact annotation_manual_review -> manual_review mapping
    manual_packets = [p for p in packets if p.census_selection_stratum.census_selection_stratum == "manual_review"]
    assert len(manual_packets) == 1
    assert manual_packets[0].identity.canonical_spdi == "chr1:400:C:G"
    
    # 2. Duplicate join check
    duplicate_bias = bias_records + [bias_records[0]]
    with pytest.raises(ConservationError):
        build_full_vus_universe(manifest, duplicate_bias, source_hash="valid_hash")
        
    # 3. Missing join check
    with pytest.raises(ConservationError):
        build_full_vus_universe(manifest, bias_records[:-1], source_hash="valid_hash")
        
    # 4. Extra join check
    extra_manifest = manifest + [SimpleNamespace(vcf_key="chr1:500:A:T", gene="TSC1", annotation_manual_review=False)]
    with pytest.raises(ConservationError):
        build_full_vus_universe(extra_manifest, bias_records, source_hash="valid_hash")
        
    # 5. Source hash drift check
    with pytest.raises(ConservationError):
        build_full_vus_universe(manifest, bias_records, source_hash="drifted_hash")
        
    # 6. Stratum count drift check
    with pytest.raises(ConservationError):
        build_full_vus_universe(
            manifest=manifest, 
            bias_records=bias_records, 
            source_hash="valid_hash",
            expected_total=4,
            expected_lp=2, # Drift!
            expected_lb=1,
            expected_unresolved=1,
            expected_manual=1
        )

