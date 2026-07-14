import json
from pathlib import Path
from conftest import make_eval_config, Metrics, with_point_estimate_lb
from raptor.eval.gate import decide_gate


def test_f1_v1_gate_unchanged():
    """F1 v1 gate unchanged:
    decide_gate with a failing missense stratum should result in status="FAIL",
    vus_authorized=False, and its per_stratum output contains ONLY 'missense'.
    This documents and asserts the intentionally frozen v1 short-circuit behavior.
    """
    cfg = make_eval_config(
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
                },
            },
        },
    )

    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.75
    m_missense.recall_lb = 0.75
    m_missense.benign_precision_lb = 0.75
    m_missense.benign_recall_lb = 0.75

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}

    decision = decide_gate(metrics, cfg)

    assert decision.status == "FAIL"
    assert decision.vus_authorized is False
    assert decision.stratum == "missense"
    
    # The v1 decide_gate short-circuits: per_stratum has only "missense"
    assert "missense" in decision.per_stratum
    assert "truncating" not in decision.per_stratum


def test_f2_immutable_artifact_invariants():
    """F2 immutable artifact invariants:
    Load data/census/tsc_masked_holdout_gate_2026-07-13.json and assert:
    - schema == "raptor.tsc.masked_holdout_gate.v1"
    - status == "FAIL"
    - binding_stratum == "missense"
    - vus_authorized == False
    - NO v2-specific keys (scopes, research_scope_flags, governance_statement, research_use_disclaimer)
    """
    path = Path("data/census/tsc_masked_holdout_gate_2026-07-13.json")
    assert path.exists(), f"Could not find 2026-07-13 artifact at {path}"

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema"] == "raptor.tsc.masked_holdout_gate.v1"
    assert payload["status"] == "FAIL"
    assert payload["binding_stratum"] == "missense"
    assert payload["vus_authorized"] is False

    # Check absence of v2 keys at root and under report (if present)
    v2_keys = ["scopes", "research_scope_flags", "governance_statement", "research_use_disclaimer", "scope_gate"]
    for key in v2_keys:
        assert key not in payload, f"Accidental leak/write of v2 key '{key}' into v1 artifact"

    if "report" in payload:
        for key in v2_keys:
            assert key not in payload["report"], f"Accidental leak of v2 key '{key}' under report"
