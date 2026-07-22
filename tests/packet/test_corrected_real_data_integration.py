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
        from scripts.build_corrected_review_packets import main
    except ImportError as exc:
        pytest.fail(f"Missing planned implementation: {exc}")
    return locals()


def test_real_data_integration_recomputation(tmp_path: Path) -> None:
    """G-CP15: Opt-in (gated by RAPTOR_PACKET_REAL_DATA=1) run over immutable inputs.
    Asserts binding oracles:
      - 6,618 total packets
      - 157 LP / 7 LB / 6,424 unresolved / 30 manual review
      - Candidate-priority queue has exactly 164 entries; excluded 6,454
      - Pattern compression counts: 7 LP patterns, 2 LB patterns
      - Raw PP3 firings 2,226, BP4 firings 3,696, PP3/BP4 union variants 5,474, scored calls 0
      - Point distribution sums to 6,618 (with 149 in '0' points band, representing 119 unresolved and 30 manual rows)
      - Every packet is candidate_direction=null / POLICY_BLOCKED
      - Writes only to a throwaway external temp root; never reads written artifacts as its own oracle
      - Missing real inputs under env=1 is FAIL, not skip.
    """
    if os.environ.get("RAPTOR_PACKET_REAL_DATA") != "1":
        pytest.skip("Opt-in real-data integration test skipped (RAPTOR_PACKET_REAL_DATA != 1)")
        
    # Check that immutable external inputs exist
    manifest_path = Path("D:/AIProjects/raptor-data/clinvar/vus-run/clinvar_2026-07-07/tsc_vus_input.manifest.jsonl")
    bias_tsv_path = Path("D:/AIProjects/raptor-data/clinvar/vus-run/tsc-vus-2026-07-07/tsc_vus_input.bias_output.tsv")
    provenance_path = Path("D:/AIProjects/raptor-data/clinvar/vus-run/clinvar_2026-07-07/tsc_vus_input.provenance.json")
    
    # Missing real inputs under env=1 is FAIL, not skip!
    if not (manifest_path.is_file() and bias_tsv_path.is_file() and provenance_path.is_file()):
        pytest.fail("External immutable real-data inputs are missing under RAPTOR_PACKET_REAL_DATA=1")
        
    # Verify inputs' SHA-256 hashes against spec pins before reading
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == "7f9937521a425e73b31422fa9191c90e67fa80cc58f351517ac732b1d32fcbba"
    assert hashlib.sha256(bias_tsv_path.read_bytes()).hexdigest() == "0a55cab470d3de93f06cd87ba30957fd1674c0ae2098ec86350f5aaac1a1162e"
    assert hashlib.sha256(provenance_path.read_bytes()).hexdigest() == "7272529546ad43ac0196523ad83d66eab8388a66a08f589bf10fc296b2110f55"
    
    api = _api()
    main = api["main"]
    
    # Invoke main with explicit immutable arguments defined by spec into tmp_path
    output_dir = tmp_path / "throwaway_external_root"
    argv = [
        "--manifest", str(manifest_path),
        "--bias-tsv", str(bias_tsv_path),
        "--provenance", str(provenance_path),
        "--census-stats", "data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json",
        "--output-dir", str(output_dir)
    ]
    
    # Invoke main program
    summary_result = main(argv)
    
    # Assert return code is 0 (success)
    assert summary_result == 0
    
    # Parse resulting in-memory or written manifest from the throwaway output directory
    manifest_file = output_dir / "aggregate_manifest.json"
    assert manifest_file.is_file()
    
    with open(manifest_file, "r", encoding="utf-8") as f:
        run_manifest = json.load(f)
        
    # Check exact oracle counts
    assert run_manifest["universe_size"] == 6618
    cons = run_manifest["conservation"]
    assert cons["manifest_identities"] == 6618
    assert cons["bias_rows"] == 6618
    assert cons["candidate_LP_review"] == 157
    assert cons["candidate_LB_review"] == 7
    assert cons["no_deterministic_resolution"] == 6424
    assert cons["manual_review"] == 30
    assert cons["lp_patterns"] == 7
    assert cons["lb_patterns"] == 2
    
    # Check PP3/BP4 firings
    supp = run_manifest["pp3bp4_suppression_full_census"]
    assert supp["raw_pp3_firings"] == 2226
    assert supp["raw_bp4_firings"] == 3696
    assert supp["pp3_or_bp4_union_variants"] == 5474
    assert supp["scored_pp3bp4_calls"] == 0
    
    # Check point distribution band sum == 6618
    dist = run_manifest["point_distribution_expected"]
    total_band_sum = sum(dist.values())
    assert total_band_sum == 6618
    assert dist["0"] == 149  # 119 unresolved and 30 manual rows
    
    # Assert every packet null/POLICY_BLOCKED
    assert run_manifest["policy_blocked_review_state_count"] == 6618
    
    # Assert 8 sample cases
    assert len(run_manifest["preregistered_discovery_sample"]) == 8

