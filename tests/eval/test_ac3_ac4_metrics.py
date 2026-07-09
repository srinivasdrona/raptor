"""AC3 — metrics validated against a HAND-COMPUTED confusion matrix (independent of
the implementation); AC4 — min-count rule tags an under-powered stratum non-gating.
"""
import pytest
from raptor.eval.metrics import compute_metrics
from conftest import make_eval_config, ImpliedCall, BenchmarkRow


def test_ac3_hand_computed_metrics_missense_stratum():
    # Hand-computed on the missense stratum:
    #   v1 P/LP=LP (TP), v2 LP/LP (TP), v3 B/LB (TN), v4 LB/LB (TN),
    #   v5 P/LB (FN), v6 B/LP (FP), v7 P/no_call (abstain), v8 B/no_call (abstain)
    #   called=6, abstain=2; concordance=(TP+TN)/6=4/6; precision=TP/(TP+FP)=2/3; recall=TP/(TP+FN)=2/3
    implied = [
        ImpliedCall("v1", "LP", 9), ImpliedCall("v2", "LP", 7),
        ImpliedCall("v3", "LB", -8), ImpliedCall("v4", "LB", -5),
        ImpliedCall("v5", "LB", -6), ImpliedCall("v6", "LP", 6),
        ImpliedCall("v7", "no_call", 2), ImpliedCall("v8", "no_call", 1),
    ]
    bm = [
        BenchmarkRow("v1", "P", "missense"), BenchmarkRow("v2", "LP", "missense"),
        BenchmarkRow("v3", "B", "missense"), BenchmarkRow("v4", "LB", "missense"),
        BenchmarkRow("v5", "P", "missense"), BenchmarkRow("v6", "B", "missense"),
        BenchmarkRow("v7", "P", "missense"), BenchmarkRow("v8", "B", "missense"),
    ]
    cfg = make_eval_config(min_count_per_class=2)  # allow gating on this small fixture
    metrics = compute_metrics(implied, bm, cfg)

    assert "missense" in metrics, "missense stratum must be reported separately (R-A2c)"
    m = metrics["missense"]
    assert m.gating is True
    assert pytest.approx(m.concordance, abs=0.01) == 0.6667
    assert pytest.approx(m.precision, abs=0.01) == 0.6667
    assert pytest.approx(m.recall, abs=0.01) == 0.6667
    assert m.counts["total_called"] == 6
    assert m.counts["abstain"] == 2


def test_ac4_under_min_count_is_non_gating():
    implied = [ImpliedCall("v1", "LP", 9)]
    bm = [BenchmarkRow("v1", "P", "truncating")]
    cfg = make_eval_config(min_count_per_class=10)
    metrics = compute_metrics(implied, bm, cfg)
    assert "truncating" in metrics
    assert metrics["truncating"].gating is False, "a below-min-count stratum must be non-gating (FR5)"
