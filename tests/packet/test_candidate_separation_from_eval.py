"""Tests for PRD-04 Task A candidate separation from eval."""

import importlib
import inspect
import sys
from pathlib import Path

def test_ac_d6_separation_from_eval():
    """AC-D6: packet.direction imports no eval.combine; candidate points/thresholds are separate."""
    import raptor.packet.direction
    import ast

    # Assert eval.combine is not imported by raptor.packet.direction
    for name, module in sys.modules.items():
        if name == "raptor.eval.combine":
            # If it happens to be loaded globally, ensure direction.py doesn't have a reference to it
            assert not hasattr(raptor.packet.direction, "combine")

    with Path("src/raptor/packet/direction.py").open("r", encoding="utf-8") as f:
        source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    assert "eval.combine" not in name.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "eval.combine" not in node.module

def test_ac_d7_no_classification():
    """AC-D7: no clinical classification is produced."""
    # Verified by the schema / direction output returning ReviewState types, not classifications.
    from raptor.packet.model import CandidateDirection
    # CandidateDirection fields: direction, null_reason, etc. None of these are clinical classification
    assert "classification" not in CandidateDirection.__annotations__
    from raptor.packet.config import load_candidate_direction_policy
    from raptor.packet.direction import compute_candidate_direction
    policy = load_candidate_direction_policy("configs/packet/candidate_direction.yaml")
    result = compute_candidate_direction([], policy)
    assert result.direction is None
    assert result.null_reason == "production_policy_unapproved"
