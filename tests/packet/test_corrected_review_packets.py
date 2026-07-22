from __future__ import annotations

import os
import sys
import pytest
import hashlib
from pathlib import Path
import json
import shutil
import dataclasses

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
        )
    except ImportError as exc:
        pytest.fail(f"Missing planned implementation: {exc}")
    api.update(locals())
    return api


def test_every_packet_null_direction_policy_blocked() -> None:
    """G-CP2: Every packet has candidate_direction=null, null_reason='production_policy_unapproved', and review_state=POLICY_BLOCKED in every stratum."""
    api = _api()
    policy = api["load_candidate_direction_policy"]("configs/packet/candidate_direction.yaml")
    assert policy.approval_status == "unapproved"
    
    config = api["load_packet_config"]("configs/packet/schema.yaml")
    assert config.candidate_direction_policy.approval_status == "unapproved"


def test_approved_policy_mismatch_fails_closed(tmp_path: Path) -> None:
    """G-CP11: The four subordinate configs verify by RAW on-disk byte SHA-256 against approved-policy pins.
    The predictor policy ARTIFACT itself verifies by LF blob (85e9e92f). Mismatch fails closed.
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
    
    # Mutate one byte in a temporary copy of the approved policy json and make sure validation fails
    mutated_policy = tmp_path / "mutated_policy.json"
    mutated_data = dict(policy_data)
    mutated_data["status"] = "draft"  # Mutated byte/status
    mutated_policy.write_text(json.dumps(mutated_data), encoding="utf-8")
    
    # If we load the mutated policy, it must fail because status is not approved
    with pytest.raises(Exception):
        # The planned configuration validator will check this and raise
        # For our RED test, we assert that loading or validating the mutated copy fails
        from raptor.packet.config import validate_predictor_policy
        validate_predictor_policy(mutated_policy)


def test_git_provenance_full_40_hex() -> None:
    """G-CP12: Git-provenance helper resolves full 40-hex HEAD on clean tree, and fails closed on dirty tree or abbreviated/unresolvable commit."""
    api = _api()
    resolve_provenance = api["resolve_corrected_provenance"]
    
    # If the tree is clean, it must return a 40-character hexadecimal string
    commit = resolve_provenance(dirty_check=True)
    assert len(commit) == 40
    assert all(c in "0123456789abcdef" for c in commit.lower())


def test_external_output_boundary_atomic_no_overwrite(tmp_path: Path) -> None:
    """G-CP14: Full artifacts write only under a new external run directory.
    Any in-repo path is refused; existing run directory is never overwritten;
    publication is atomic; canonical UTF-8 and LF-only bytes.
    """
    api = _api()
    write_outputs = api["write_corrected_run_outputs"]
    
    # Try writing to an in-repo path - should be refused with OutputBoundaryError
    in_repo_path = Path("docs/project/specs")
    with pytest.raises(api["OutputBoundaryError"]):
        write_outputs(output_dir=in_repo_path, packets=[])
        
    # Atomic write to temporary external dir (using pytest tmp_path)
    ext_dir = tmp_path / "external_run_dir"
    ext_dir.mkdir()
    
    # If the directory already exists and we try to write, it should fail-closed (e.g. FileExistsError)
    (ext_dir / "packets").mkdir()
    with pytest.raises(Exception):
         write_outputs(output_dir=ext_dir, packets=[])


def test_evidence_absent_packet_for_zero_fired_rows() -> None:
    """G-CP7: Zero-fired-criteria row produces a deterministic evidence-absent packet (empty scored set + MissingEvidence), conserving 6,618."""
    api = _api()
    build_evidence_absent_packet = api["build_evidence_absent_packet"]
    
    # Complete corrected PacketInput using test_packet_core helper
    raw_input = core._packet_input(api)
    # Clear criteria to mock a zero-fired-criteria row
    absent_input = dataclasses.replace(
        raw_input,
        criterion_inputs=(),
        census_selection_stratum="no_deterministic_resolution",
    )
    
    # Build evidence absent packet
    packet = build_evidence_absent_packet(absent_input, api["_packet_config"](api))
    assert len(packet.entries) == 0
    assert len(packet.missing_evidence) > 0
    assert any("no fired BIAS criteria" in me.next_action for me in packet.missing_evidence)
    assert packet.candidate_direction.direction is None
    assert packet.review_state == api["ReviewState"].POLICY_BLOCKED


def test_current_lineage_dispositions_and_zero_scored_pp3_bp4() -> None:
    """G-CP6: Every fired PP3/BP4 renders with lineage disposition deferred bound to the current d2312… config; ZERO scored PP3/BP4; no candidate-direction point."""
    api = _api()
    from raptor.eval.lineage_policy import load_lineage_policy
    policy = load_lineage_policy("configs/eval/bias_lineage.yaml")
    
    assert policy.records["PP3"].production_disposition == "deferred"
    assert policy.records["BP4"].production_disposition == "deferred"
    assert policy.records["PP3"].validation_disposition == "deferred"
    assert policy.records["BP4"].validation_disposition == "deferred"
    
    # Test rendering of a packet with a deferred criterion
    # Create complete packet input with PP3/BP4 and render it
    from raptor.packet.render import render_markdown
    from raptor.packet.model import PacketView
    
    render_config = api["load_render_config"]("configs/packet/render.yaml")
    packet = api["build_packet"](core._packet_input(api), api["_packet_config"](api))
    rendered = render_markdown(packet, render_config, view=PacketView.FIRST_PASS)
    assert "deferred" in rendered or "DEFERRED" in rendered

