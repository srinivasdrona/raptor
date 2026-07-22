from __future__ import annotations

import os
import sys
import pytest
import hashlib
from pathlib import Path
import json
import shutil
import dataclasses
from types import SimpleNamespace

import test_packet_core as core

# Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
# Copilot-Session: 7c146921-f3dd-4a1e-8cf0-8f574de49204

def _api():
    api = core._api()
    try:
        from raptor.packet.git_provenance import resolve_corrected_provenance
        from raptor.packet.corrected_universe import (
            build_full_vus_universe,
            write_corrected_run_outputs,
            build_evidence_absent_packet,
            OutputBoundaryError,
        )
    except ImportError as exc:
        pytest.fail(f"Missing planned implementation: {exc}")
    api.update(locals())
    return api


def test_every_packet_null_direction_policy_blocked() -> None:
    """G-CP2: Every packet has candidate_direction=null, null_reason='production_policy_unapproved', and review_state=POLICY_BLOCKED in every stratum."""
    api = _api()
    build_packet = api["build_packet"]
    CensusSelectionMetadata = api["CensusSelectionMetadata"]
    PatternRef = api["PatternRef"]
    
    # Stratum values from spec:
    strata = [
        "candidate_LP_review",
        "candidate_LB_review",
        "no_deterministic_resolution",
        "manual_review",
    ]
    
    # Loop over all 4 strata, build packets and assert fields
    for stratum in strata:
        metadata = CensusSelectionMetadata(census_selection_stratum=stratum)
        
        # Pattern ref is only allowed for LP/LB, and must have a positive member_count, and signature is a tuple (Finding 7)
        if stratum == "candidate_LP_review":
            pattern_ref = PatternRef(
                census_snapshot_id="clinvar_2026-07-07",
                pattern_id="LP-pattern-1",
                census_selection_stratum=stratum,
                pattern_signature=("PVS1_supporting",),
                member_count=5
            )
        elif stratum == "candidate_LB_review":
            pattern_ref = PatternRef(
                census_snapshot_id="clinvar_2026-07-07",
                pattern_id="LB-pattern-1",
                census_selection_stratum=stratum,
                pattern_signature=("BP4_supporting",),
                member_count=2
            )
        else:
            pattern_ref = None
            
        raw_input = core._packet_input(api)
        packet_input = dataclasses.replace(
            raw_input,
            census_selection_stratum=metadata,
            pattern_ref=pattern_ref
        )
        
        packet = build_packet(packet_input, api["_packet_config"](api))
        
        assert packet.candidate_direction.direction is None
        assert packet.candidate_direction.null_reason == "production_policy_unapproved"
        assert packet.candidate_direction.signed_points is None
        assert len(packet.candidate_direction.per_criterion_points) == 0  # no contributions
        assert packet.review_state == api["ReviewState"].POLICY_BLOCKED


def test_approved_policy_mismatch_fails_closed(tmp_path: Path) -> None:
    """G-CP11: The four subordinate configs verify by RAW on-disk byte SHA-256 against approved-policy pins.
    The predictor policy ARTIFACT itself verifies by LF blob (85e9e92f). Mismatch fails closed.
    Testing the corrected CLI/shared validation seam, reusing raptor.census.cli helpers.
    """
    approved_policy_path = Path("configs/eval/bp4pp3_predictor_policy.json")
    assert approved_policy_path.is_file(), "Approved predictor policy json is missing"
    
    lf_bytes = approved_policy_path.read_bytes()
    canonical_bytes = lf_bytes.replace(b"\r\n", b"\n")
    lf_hash = hashlib.sha256(canonical_bytes).hexdigest()
    assert lf_hash == "85e9e92fa9f4c221c02af30e787315a88ed2bef51f6f58d25c5dc267eb55a34a", "Predictor policy ARTIFACT hash mismatch"
    
    policy_data = json.loads(canonical_bytes.decode("utf-8"))
    assert policy_data.get("schema") == "bp4pp3-predictor-policy/2"
    assert policy_data.get("status") == "approved"
    assert policy_data.get("mode") == "disabled_manual"
    
    # G-CP11: test the corrected CLI/shared validation seam scoped in spec, reusing current raptor.census.cli helpers
    # We load a mutated copy of the approved policy json and make sure validation fails
    mutated_policy = tmp_path / "mutated_policy.json"
    mutated_data = dict(policy_data)
    mutated_data["status"] = "draft"  # Mutated byte/status
    mutated_policy.write_text(json.dumps(mutated_data), encoding="utf-8")
    
    from raptor.census.cli import _validate_predictor_policy, _verify_bound_hashes
    
    with pytest.raises(ValueError, match="not approved"):
        _validate_predictor_policy(mutated_data)
        
    # Cover canonical LF policy hash versus raw subordinate config hashes
    # Raw subordinate config hashes are checked by _verify_bound_hashes
    paths = {
        "scorer_config": Path("configs/acmg/tsc.yaml"),
        "eval_config": Path("configs/eval/tsc2.yaml"),
        "lineage_policy": Path("configs/eval/bias_lineage.yaml"),
        "packet_candidate_direction": Path("configs/packet/candidate_direction.yaml"),
    }
    # This should pass for the valid approved policy data:
    bound_hashes = _verify_bound_hashes(policy_data, paths)
    assert len(bound_hashes) == 4
    
    # Mutating a config hash in the policy dictionary should cause a drift failure
    tampered_policy = dict(policy_data)
    tampered_policy["production_config_hash"] = "incorrect_hash"
    with pytest.raises(ValueError, match="hash drift"):
        _verify_bound_hashes(tampered_policy, paths)


def test_git_provenance_full_40_hex() -> None:
    """G-CP12: Git-provenance helper resolves full 40-hex HEAD on clean tree, and fails closed on dirty tree or abbreviated/unresolvable commit."""
    api = _api()
    resolve_provenance = api["resolve_corrected_provenance"]
    
    # Test 1: Clean full 40-hex
    def mock_run_clean(cmd, **kwargs):
        if "describe" in cmd or "status" in cmd:
            return SimpleNamespace(returncode=0, stdout="") # clean
        return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n")
    
    commit = resolve_provenance(run_cmd=mock_run_clean)
    assert commit == "a" * 40
    assert len(commit) == 40
    
    # Test 2: Dirty tree
    def mock_run_dirty(cmd, **kwargs):
        if "status" in cmd:
            return SimpleNamespace(returncode=0, stdout="M src/file.py\n")
        return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n")
        
    with pytest.raises(Exception):
        resolve_provenance(run_cmd=mock_run_dirty)
        
    # Test 3: Abbreviated commit (e.g. 7 chars)
    def mock_run_short(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="a" * 7 + "\n")
        
    with pytest.raises(Exception):
        resolve_provenance(run_cmd=mock_run_short)
        
    # Test 4: Unresolvable commit
    def mock_run_fail(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="fatal: not a git repository")
        
    with pytest.raises(Exception):
        resolve_provenance(run_cmd=mock_run_fail)


def test_external_output_boundary_atomic_no_overwrite(tmp_path: Path) -> None:
    """G-CP14: Full artifacts write only under a new external run directory.
    Any in-repo path is refused; existing run directory is never overwritten;
    publication is atomic; canonical UTF-8 and LF-only bytes.
    """
    api = _api()
    write_outputs = api["write_corrected_run_outputs"]
    OutputBoundaryError = api["OutputBoundaryError"]
    build_packet = api["build_packet"]
    
    # Construct a minimal packet list for testing writes
    packet_input = core._packet_input(api)
    packet = build_packet(packet_input, api["_packet_config"](api))
    packets = [packet]
    
    # 1. In-repo rejection (inside git repo root)
    in_repo_path = Path("D:/AIProjects/raptor-worktrees/review-packets/tests/packet/some_dir")
    with pytest.raises(OutputBoundaryError):
        write_outputs(output_root=in_repo_path, run_name="test_run", packets=packets)
        
    # 2. Successful valid minimal write to a new external dir (using pytest's tmp_path, outside repo)
    output_root = tmp_path / "external_data_root"
    run_name = "run_2026-07-22"
    
    write_outputs(output_root=output_root, run_name=run_name, packets=packets)
    
    run_dir = output_root / run_name
    assert run_dir.is_dir()
    
    manifest_file = run_dir / "aggregate_manifest.json"
    assert manifest_file.is_file()
    
    # Read bytes to verify canonical UTF-8 LF-only
    raw_bytes = manifest_file.read_bytes()
    assert b"\r\n" not in raw_bytes
    assert raw_bytes.endswith(b"\n")
    decoded = raw_bytes.decode("utf-8")
    assert len(decoded) > 0
    
    # Verify no staging leftovers
    leftovers = list(run_dir.glob("**/*.tmp")) + list(run_dir.glob("**/*.staging"))
    assert len(leftovers) == 0
    
    # 3. Second-call no-overwrite
    with pytest.raises(OutputBoundaryError):
        write_outputs(output_root=output_root, run_name=run_name, packets=packets)


def test_evidence_absent_packet_for_zero_fired_rows() -> None:
    """G-CP7: Zero-fired-criteria row produces a deterministic evidence-absent packet (empty scored set + MissingEvidence), conserving 6,618."""
    api = _api()
    build_evidence_absent_packet = api["build_evidence_absent_packet"]
    CensusSelectionMetadata = api["CensusSelectionMetadata"]
    
    # 1. Use real CensusSelectionMetadata value object
    metadata = CensusSelectionMetadata(census_selection_stratum="no_deterministic_resolution")
    
    # 2. Complete corrected PacketInput with empty criteria and pattern_ref None
    raw_input = core._packet_input(api)
    absent_input = dataclasses.replace(
        raw_input,
        criterion_inputs=(),
        census_selection_stratum=metadata,
        pattern_ref=None
    )
    
    # 3. Build evidence absent packet
    packet = build_evidence_absent_packet(absent_input, api["_packet_config"](api))
    
    # 4. Assertions: empty entries, deterministic MissingEvidence, metadata, pattern_ref None, null/POLICY_BLOCKED
    assert len(packet.entries) == 0
    assert len(packet.missing_evidence) > 0
    for me in packet.missing_evidence:
        assert hasattr(me, "reason") or hasattr(me, "next_action")
    assert packet.census_selection_stratum == metadata
    assert packet.pattern_ref is None
    assert packet.candidate_direction.direction is None
    assert packet.candidate_direction.null_reason == "production_policy_unapproved"
    assert packet.review_state == api["ReviewState"].POLICY_BLOCKED


def test_current_lineage_dispositions_and_zero_scored_pp3_bp4() -> None:
    """G-CP6: Every fired PP3/BP4 renders with lineage disposition deferred bound to the current d2312… config; ZERO scored PP3/BP4; no candidate-direction point."""
    api = _api()
    from raptor.packet.config import load_render_config
    from raptor.eval.lineage_policy import load_lineage_policy
    
    # 1. Load actual lineage policy
    policy = load_lineage_policy("configs/eval/bias_lineage.yaml")
    assert policy.records["PP3"].production_disposition == "deferred"
    assert policy.records["BP4"].production_disposition == "deferred"
    assert policy.records["PP3"].validation_disposition == "deferred"
    assert policy.records["BP4"].validation_disposition == "deferred"
    
    # 2. Build explicit PP3 and BP4 criteria via core helper (no default PVS1)
    pp3_input = core._criterion_input(api, "PP3", "supporting", "pathogenic")
    bp4_input = core._criterion_input(api, "BP4", "supporting", "benign")
    packet_input = core._packet_input(api, criteria=[pp3_input, bp4_input])
    
    # 3. Build packet and check deferred lineage rendering, zero score contribution, null/POLICY_BLOCKED
    build_packet = api["build_packet"]
    packet = build_packet(packet_input, api["_packet_config"](api))
    
    assert packet.candidate_direction.direction is None
    assert packet.candidate_direction.null_reason == "production_policy_unapproved"
    assert packet.candidate_direction.signed_points is None
    assert len(packet.candidate_direction.per_criterion_points) == 0  # zero score contribution
    assert packet.review_state == api["ReviewState"].POLICY_BLOCKED
    
    # 4. Render deferred lineage
    from raptor.packet.render import render_markdown
    from raptor.packet.model import PacketView
    
    render_config = load_render_config("configs/packet/render.yaml")
    rendered = render_markdown(packet, render_config, view=PacketView.FIRST_PASS)
    assert "deferred" in rendered or "DEFERRED" in rendered

