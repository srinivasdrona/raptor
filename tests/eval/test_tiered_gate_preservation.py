"""Preservation and regression tests for versioned tiered gate v3.

Asserts that v1 and v2 gate code, models, and records are preserved byte-identically,
and existing behavior is unchanged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from raptor.eval.gate import decide_gate
from raptor.eval.scope_gate import decide_scope_gate
from raptor.eval.model import (
    LabeledVariant,
    BenchmarkRow,
    ImpliedCall,
    Metrics,
    StratumVerdict,
    GateDecision,
    DirectionVerdict,
    ScopeGateDecision,
)
from conftest import make_eval_config


def test_v1_v2_code_and_records_unmodified_in_git():
    """Assert that v1/v2 gate files and historical records are completely untouched."""
    files_to_check = [
        "src/raptor/eval/gate.py",
        "src/raptor/eval/scope_gate.py",
        "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json",
        "data/census/tsc_masked_holdout_gate_2026-07-13.json",
    ]
    for file_path in files_to_check:
        path = Path(file_path)
        assert path.exists(), f"Expected file {file_path} to exist"
        
        # Run git diff --exit-code to verify there are absolutely no modified/staged changes
        res = subprocess.run(["git", "diff", "--exit-code", file_path], capture_output=True)
        assert res.returncode == 0, f"File {file_path} has been modified relative to git HEAD!"


def test_v1_v2_model_classes_preserved():
    """Assert that existing model.py v1/v2 dataclasses remain unchanged.

    New models should only be appended, never altering existing definitions.
    """
    model_path = "src/raptor/eval/model.py"
    # Ensure no deletions/modifications are made to existing lines in model.py.
    # We can check that 'git diff' contains only additions ('+') and no deletions ('-').
    res = subprocess.run(["git", "diff", model_path], capture_output=True, text=True)
    diff_output = res.stdout
    for line in diff_output.splitlines():
        if line.startswith("-") and not line.startswith("---"):
            raise AssertionError(f"Deletions or modifications detected in model.py: {line}")


def test_tsc2_yaml_changes_are_additive_only():
    """Assert that configs/eval/tsc2.yaml only contains the additive tiered_authorization block."""
    config_path = "configs/eval/tsc2.yaml"
    # Verify that there are no deletions of existing thresholds, splits, or configurations
    res = subprocess.run(["git", "diff", config_path], capture_output=True, text=True)
    diff_output = res.stdout
    for line in diff_output.splitlines():
        if line.startswith("-") and not line.startswith("---"):
            # Check if this deletion belongs to some other key or is an actual modification of a threshold
            raise AssertionError(f"Deletions/modifications detected in tsc2.yaml: {line}")


def test_legacy_gate_decisions_behavior():
    """Assert that decide_gate (v1) and decide_scope_gate (v2) behave exactly as before."""
    # 1. Test decide_gate (v1) unchanged behavior
    cfg = make_eval_config(
        min_count_per_class=10,
        oracle_thresholds={
            "confidence": 0.95,
            "strata": {
                "missense": {
                    "precision": 0.90,
                    "recall": 0.85,
                    "gating": True,
                    "directions": ["pathogenic", "benign"],
                }
            }
        }
    )

    m_missense = Metrics(
        precision=0.85, recall=0.80, concordance=0.8,
        counts={"path_called": 20, "benign_called": 20, "path_actual": 20, "benign_actual": 20},
        stratum="missense", gating=True, benign_precision=0.85, benign_recall=0.80
    )
    m_missense.precision_lb = 0.70
    m_missense.recall_lb = 0.70
    m_missense.benign_precision_lb = 0.70
    m_missense.benign_recall_lb = 0.70

    metrics = {"missense": m_missense}
    decision = decide_gate(metrics, cfg)

    # It fails because lower bound (0.70) is below thresholds (0.90, 0.85)
    assert decision.status == "FAIL"
    assert decision.vus_authorized is False

    # 2. Test decide_scope_gate (v2) unchanged behavior
    # Construct a v2 scope_authorization configuration with exact pinned strings
    v2_scope_auth = {
        "schema_version": "2",
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": ["truncating:pathogenic"]
            }
        },
        "governance_statements": {
            "FULL_SPECTRUM": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
            "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
            "NONE_VALIDATED": "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
        }
    }

    v2_cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds={
            "confidence": 0.95,
            "strata": {
                "missense": {
                    "precision": 0.90,
                    "recall": 0.85,
                    "gating": True,
                    "directions": ["pathogenic", "benign"],
                },
                "truncating": {
                    "precision": 0.95,
                    "recall": 0.95,
                    "gating": True,
                    "directions": ["pathogenic"],
                }
            }
        },
        scope_authorization=v2_scope_auth
    )

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 0, "path_actual": 40, "benign_actual": 0, "tp": 40, "tn": 0, "fp": 0, "fn": 0},
        stratum="truncating", gating=True
    )
    m_truncating.precision_lb = 0.97
    m_truncating.recall_lb = 0.97

    # missense is underpowered
    m_missense_under = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 0, "benign_called": 5, "path_actual": 0, "benign_actual": 5, "tp": 0, "tn": 5, "fp": 0, "fn": 0},
        stratum="missense", gating=True
    )
    m_missense_under.benign_precision_lb = 0.60
    m_missense_under.benign_recall_lb = 0.60

    metrics_v2 = {"truncating": m_truncating, "missense": m_missense_under}
    v2_decision = decide_scope_gate(metrics_v2, v2_cfg)

    # In v2, truncating gets VALIDATED and missense gets FAIL (misleading v2 behavior)
    assert v2_decision.scopes["truncating:pathogenic"].scope_status == "VALIDATED"
    assert v2_decision.scopes["missense:benign"].scope_status == "FAIL"
    assert v2_decision.research_scope_flags["truncating_pathogenic_research_scope_validated"] is True
