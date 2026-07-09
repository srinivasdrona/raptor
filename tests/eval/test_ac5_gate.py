"""AC5 — gate honesty (GP-9/H13): never PASS with unset thresholds; PASS is gated on
the MISSENSE-stratified held-out metric (R-A2c), not the overall number.
"""
from raptor.eval.gate import decide_gate
from conftest import make_eval_config, Metrics


def test_ac5_empty_thresholds_unverified():
    cfg = make_eval_config(oracle_thresholds={})
    metrics = {"missense": Metrics(1.0, 1.0, 1.0, {}, "missense", True)}
    d = decide_gate(metrics, cfg)
    assert d.status == "UNVERIFIED"
    assert d.vus_authorized is False


def test_ac5_gate_is_missense_stratified():
    cfg = make_eval_config(oracle_thresholds={"precision": 0.9, "recall": 0.9})

    # overall passes but MISSENSE fails -> must FAIL (R-A2c distribution shift)
    fail = {
        "overall": Metrics(0.95, 0.95, 0.95, {}, "overall", True),
        "missense": Metrics(0.80, 0.80, 0.80, {}, "missense", True),
    }
    d = decide_gate(fail, cfg)
    assert d.status == "FAIL", "gate must fail when the missense stratum fails, even if overall passes"
    assert d.vus_authorized is False

    # missense passes -> PASS + authorized
    ok = {
        "overall": Metrics(0.95, 0.95, 0.95, {}, "overall", True),
        "missense": Metrics(0.95, 0.95, 0.95, {}, "missense", True),
    }
    d = decide_gate(ok, cfg)
    assert d.status == "PASS"
    assert d.vus_authorized is True


def test_ac5_underpowered_missense_not_authorized():
    """A non-gating (below-min-count) missense stratum must NOT yield PASS/authorization."""
    cfg = make_eval_config(oracle_thresholds={"precision": 0.9, "recall": 0.9})
    metrics = {"missense": Metrics(1.0, 1.0, 1.0, {}, "missense", False)}  # gating False
    d = decide_gate(metrics, cfg)
    assert d.status in ("UNDERPOWERED", "UNVERIFIED", "FAIL")
    assert d.vus_authorized is False
