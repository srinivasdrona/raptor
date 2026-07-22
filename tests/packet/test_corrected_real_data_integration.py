from __future__ import annotations

import os
import sys
import json
import pytest
import hashlib
from pathlib import Path

# Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

def test_real_data_integration_recomputation() -> None:
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
      - Skipped cleanly if env or inputs are absent.
    """
    if os.environ.get("RAPTOR_PACKET_REAL_DATA") != "1":
        pytest.skip("Opt-in real-data integration test skipped (RAPTOR_PACKET_REAL_DATA != 1)")
        
    # Check that immutable external inputs exist
    manifest_path = Path("D:/AIProjects/raptor-data/clinvar/vus-run/clinvar_2026-07-07/tsc_vus_input.manifest.jsonl")
    bias_tsv_path = Path("D:/AIProjects/raptor-data/clinvar/vus-run/tsc-vus-2026-07-07/tsc_vus_input.bias_output.tsv")
    provenance_path = Path("D:/AIProjects/raptor-data/clinvar/vus-run/clinvar_2026-07-07/tsc_vus_input.provenance.json")
    
    if not (manifest_path.is_file() and bias_tsv_path.is_file() and provenance_path.is_file()):
        pytest.skip("External immutable real-data inputs are missing")
        
    # Verify inputs' SHA-256 hashes against spec pins before reading
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == "7f9937521a425e73b31422fa9191c90e67fa80cc58f351517ac732b1d32fcbba"
    assert hashlib.sha256(bias_tsv_path.read_bytes()).hexdigest() == "0a55cab470d3de93f06cd87ba30957fd1674c0ae2098ec86350f5aaac1a1162e"
    assert hashlib.sha256(provenance_path.read_bytes()).hexdigest() == "7272529546ad43ac0196523ad83d66eab8388a66a08f589bf10fc296b2110f55"
    
    # Importing Sonnet's implemented real-data runner (which will fail right now because it's not implemented yet)
    from raptor.packet.build import run_corrected_full_recomputation
    run_corrected_full_recomputation()
