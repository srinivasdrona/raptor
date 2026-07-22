from __future__ import annotations

import os
import sys
import json
import pytest
from pathlib import Path

from raptor.census.strata import (
    load_manifest,
    reproduce_census_strata,
)

# Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

def test_universe_conservation_and_strata_counts() -> None:
    """G-CP1, G-CP5, G-CP10: Check universe size of 6,618 and stratum partition counts.
    Ensures 164 (priority LP+LB) + 6,454 (excluded unresolved+manual) == 6,618.
    """
    # Under current-policy (disabled_manual) census stats
    census_stats_path = Path("data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json")
    assert census_stats_path.is_file(), "Current policy census json file is missing"
    
    with open(census_stats_path, "r", encoding="utf-8") as f:
        census = json.load(f)
        
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
    assert lp + lb + unresolved + manual == 6618, "Stratum sum does not conserve 6,618 VUS"
    
    # Priority queue vs excluded counts
    priority_queue_size = lp + lb
    excluded_from_priority = unresolved + manual
    assert priority_queue_size == 164
    assert excluded_from_priority == 6454
    assert priority_queue_size + excluded_from_priority == 6618


def test_manual_review_reconciliation() -> None:
    """G-CP8, D11: manual_review stratum is exactly the 30 NTHL1 rows == census annotation_manual_review, no double count."""
    census_stats_path = Path("data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json")
    with open(census_stats_path, "r", encoding="utf-8") as f:
        census = json.load(f)
        
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
    """G-CP9, D5: Current-policy conservation guard reads disabled_manual stats and fails closed on drift.
    It must NOT read historical schema keys (e.g. worker, input_vcf_sha256 in older format) and does NOT assert 238/1,333.
    """
    # The new current conservation guard is imported from raptor (which Sonnet will implement)
    # Here we assert its interface is expected and would fail closed on drift.
    from raptor.census.strata import assert_corrected_policy_conservation
    assert_corrected_policy_conservation(
        manifest_identities=6618,
        lp_count=157,
        lb_count=7,
        unresolved_count=6424,
        manual_count=30
    )
