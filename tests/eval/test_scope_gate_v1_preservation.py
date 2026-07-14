from __future__ import annotations

import json
from pathlib import Path

from conftest import Metrics, make_eval_config
from raptor.eval.gate import decide_gate


ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "census"
    / "tsc_masked_holdout_gate_2026-07-13.json"
)


def _thresholds() -> dict:
    return {
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
    }


def test_v1_gate_retains_documented_missense_short_circuit() -> None:
    config = make_eval_config(
        min_count_per_class=36, oracle_thresholds=_thresholds()
    )
    missense = Metrics(
        precision=0.80,
        recall=0.80,
        concordance=0.80,
        counts={
            "path_actual": 40,
            "path_called": 40,
            "benign_actual": 40,
            "benign_called": 40,
        },
        stratum="missense",
        gating=True,
        benign_precision=0.80,
        benign_recall=0.80,
        precision_lb=0.80,
        recall_lb=0.80,
        benign_precision_lb=0.80,
        benign_recall_lb=0.80,
    )

    decision = decide_gate({"missense": missense}, config)
    assert decision.status == "FAIL"
    assert decision.vus_authorized is False
    assert set(decision.per_stratum) == {"missense"}


def test_historical_gate_artifact_remains_v1_without_scope_keys() -> None:
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    assert artifact["schema"] == "raptor.tsc.masked_holdout_gate.v1"
    assert artifact["status"] == "FAIL"
    assert artifact["binding_stratum"] == "missense"
    assert artifact["vus_authorized"] is False
    assert {
        "scopes",
        "research_scope_flags",
        "governance_statement",
        "research_use_disclaimer",
        "scope_gate",
    }.isdisjoint(artifact)
