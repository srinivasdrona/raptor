import pytest
import scipy.stats
from collections import defaultdict

# The required module stats.py doesn't exist yet, so this will fail to import.
# That is expected. We still write the tests.
try:
    from raptor.eval.stats import clopper_pearson_lower, InsufficientCountError
except ImportError:
    pass

from raptor.eval.model import Metrics, GateDecision, BenchmarkRow, ImpliedCall
from raptor.eval.config import ConfigError
from raptor.eval.gate import decide_gate

# We also need make_eval_config from conftest
from conftest import make_eval_config

# AC-G1
def test_acg1_clopper_pearson_oracle():
    assert clopper_pearson_lower(0, 10) == 0.0

    with pytest.raises(InsufficientCountError):
        clopper_pearson_lower(0, 0)

    lb_35 = clopper_pearson_lower(35, 35)
    lb_36 = clopper_pearson_lower(36, 36)
    assert lb_36 >= 0.90 > lb_35

    lb_71 = clopper_pearson_lower(71, 71)
    lb_72 = clopper_pearson_lower(72, 72)
    assert lb_72 >= 0.95 > lb_71

    lb_367 = clopper_pearson_lower(367, 367)
    lb_368 = clopper_pearson_lower(368, 368)
    assert lb_368 >= 0.99 > lb_367

    # Grid testing against scipy
    for k, n in [(0, 10), (1, 10), (5, 10), (10, 10), (35, 35), (36, 36), (53, 54), (71, 72), (367, 368)]:
        expected = 0.0 if k == 0 else scipy.stats.beta.ppf(0.025, k, n-k+1)
        # Note: tolerance 1e-7
        assert clopper_pearson_lower(k, n, confidence=0.95) == pytest.approx(expected, abs=1e-7)

# AC-G2
def test_acg2_gate_uses_lower_bound():
    # Construct config with nested oracle_thresholds
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds={
            "confidence": 0.95,
            "strata": {
                "missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]},
                "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}
            }
        }
    )

    # Scenario: missense point estimate clears 0.90, but lower bound does not because small n (e.g. 20)
    # precision = 20/20 = 1.0 > 0.90, but lower bound < 0.90
    m_fail = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"tp": 20, "fp": 0, "tn": 20, "fn": 0, "path_called": 20, "benign_called": 20, "path_actual": 20, "benign_actual": 20},
        stratum="missense", gating=False, benign_precision=1.0, benign_recall=1.0
    )
    # doer might add precision_lb/recall_lb, but compute_metrics does it. We mock precision_lb if needed,
    # but the simplest is to let compute_metrics run, OR if decide_gate checks it directly from Metrics, we assign it.
    # decide_gate should check m.precision_lb
    m_fail.precision_lb = 0.80
    m_fail.recall_lb = 0.80
    m_fail.benign_precision_lb = 0.80
    m_fail.benign_recall_lb = 0.80

    d = decide_gate({"missense": m_fail}, cfg)
    assert d.status in ("FAIL", "UNDERPOWERED")
    assert not d.vus_authorized

# AC-G3
def test_acg3_per_stratum_gating():
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds={
            "confidence": 0.95,
            "strata": {
                "missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]},
                "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}
            }
        }
    )
    # Missense binds: requires precision_lb >= 0.90, recall_lb >= 0.85 both dirs
    m_pass = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"tp": 40, "fp": 0, "tn": 40, "fn": 0, "path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_pass.precision_lb = 0.91
    m_pass.recall_lb = 0.86
    m_pass.benign_precision_lb = 0.91
    m_pass.benign_recall_lb = 0.86

    # Truncating benign n=1 is report only, never changes verdict.
    # Truncating pathogenic lower bound below 0.95 -> FAIL
    t_fail = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"tp": 40, "fp": 0, "tn": 1, "fn": 0, "path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    t_fail.precision_lb = 0.90  # below 0.95
    t_fail.recall_lb = 0.90
    t_fail.benign_precision_lb = 0.0
    t_fail.benign_recall_lb = 0.0

    d = decide_gate({"missense": m_pass, "truncating": t_fail}, cfg)
    assert d.status == "FAIL"

    # Truncating clears pathogenic
    t_pass = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"tp": 80, "fp": 0, "tn": 1, "fn": 0, "path_called": 80, "benign_called": 1, "path_actual": 80, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    t_pass.precision_lb = 0.96
    t_pass.recall_lb = 0.96
    t_pass.benign_precision_lb = 0.0
    t_pass.benign_recall_lb = 0.0

    d2 = decide_gate({"missense": m_pass, "truncating": t_pass}, cfg)
    assert d2.status == "PASS"


def test_acg3_truncating_pathogenic_gate_is_not_disabled_by_sparse_benign() -> None:
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
    missense = Metrics(
        precision=1.0,
        recall=1.0,
        concordance=1.0,
        counts={
            "tp": 80,
            "fp": 0,
            "tn": 80,
            "fn": 0,
            "path_called": 80,
            "benign_called": 80,
            "path_actual": 80,
            "benign_actual": 80,
        },
        stratum="missense",
        gating=True,
        benign_precision=1.0,
        benign_recall=1.0,
    )
    missense.precision_lb = missense.recall_lb = 0.96
    missense.benign_precision_lb = missense.benign_recall_lb = 0.96
    truncating = Metrics(
        precision=1.0,
        recall=1.0,
        concordance=1.0,
        counts={
            "tp": 40,
            "fp": 0,
            "tn": 1,
            "fn": 0,
            "path_called": 40,
            "benign_called": 1,
            "path_actual": 40,
            "benign_actual": 1,
        },
        stratum="truncating",
        gating=False,
        benign_precision=1.0,
        benign_recall=1.0,
    )
    truncating.precision_lb = truncating.recall_lb = 0.9119
    truncating.benign_precision_lb = truncating.benign_recall_lb = 0.0

    decision = decide_gate(
        {"missense": missense, "truncating": truncating},
        cfg,
    )
    assert decision.status == "FAIL"
    assert decision.vus_authorized is False
    assert decision.per_stratum["truncating"].met is False
    assert decision.per_stratum["truncating"].powered is True

# AC-G4
def test_acg4_gate_honesty_preserved():
    # empty oracle_thresholds -> UNVERIFIED
    cfg_empty = make_eval_config(oracle_thresholds={})
    m = Metrics(1.0, 1.0, 1.0, {}, "missense", True, 1.0, 1.0)
    m.precision_lb = 0.95; m.recall_lb = 0.95; m.benign_precision_lb = 0.95; m.benign_recall_lb = 0.95
    d = decide_gate({"missense": m}, cfg_empty)
    assert d.status == "UNVERIFIED"

    # below min_count -> UNDERPOWERED
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds={
            "confidence": 0.95,
            "strata": {
                "missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}
            }
        }
    )
    m_under = Metrics(1.0, 1.0, 1.0, {"path_called": 35, "benign_called": 35, "path_actual": 35, "benign_actual": 35}, "missense", False, 1.0, 1.0)
    m_under.precision_lb = 0.95; m_under.recall_lb = 0.95; m_under.benign_precision_lb = 0.95; m_under.benign_recall_lb = 0.95
    d = decide_gate({"missense": m_under}, cfg)
    assert d.status == "UNDERPOWERED"

# AC-G5
def test_acg5_pre_registration_lock(tmp_path):
    import yaml
    from raptor.eval.config import load_config

    # We need to construct a valid raw config and override it
    raw = {
        "automatable_criteria": ["PVS1", "PS3", "PM1", "PM2", "PP3", "BA1", "BS1", "BS2", "BP4", "BP7"],
        "tavtigian_points": {"supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8, "stand_alone": 8},
        "tavtigian_cutoffs": {"pathogenic_min": 10, "likely_pathogenic_min": 6, "vus_min": 0,
                              "vus_max": 5, "likely_benign_max": -1, "benign_max": -7},
        "min_count_per_class": 36,
        "split": {"seed": 42, "holdout_fraction": 0.3},
        "labels_snapshot": "clinvar_2026-07-01",
        "oracle_thresholds": {
            "confidence": 0.95,
            "strata": {
                "missense": {"precision": 0.89, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]},
                "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}
            }
        }
    }
    p = tmp_path / "eval.yaml"
    p.write_text(yaml.safe_dump(raw))

    with pytest.raises(ConfigError, match=r"(?i)mismatch|differ|0\.90|pinned|rubric"):
        load_config(p)

    for stratum, mutation in (
        ("missense", {"gating": False}),
        ("missense", {"directions": ["pathogenic"]}),
        ("truncating", {"gating": False}),
        ("truncating", {"directions": ["pathogenic", "benign"]}),
    ):
        pinned = yaml.safe_load(yaml.safe_dump(raw))
        pinned["oracle_thresholds"]["strata"]["missense"]["precision"] = 0.90
        pinned["oracle_thresholds"]["strata"][stratum].update(mutation)
        drift = tmp_path / f"{stratum}-{next(iter(mutation))}.yaml"
        drift.write_text(yaml.safe_dump(pinned))
        with pytest.raises(ConfigError, match=r"(?i)pinned|semantics|gating|directions"):
            load_config(drift)

# AC-G6
def test_acg6_determinism_and_report():
    from raptor.eval.report import EvalReport

    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds={
            "confidence": 0.95,
            "strata": {
                "missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]}
            }
        }
    )
    m = Metrics(1.0, 1.0, 1.0, {"tp": 40, "fp": 0, "tn": 40, "fn": 0, "path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40}, "missense", True, 1.0, 1.0)
    m.precision_lb = 0.91; m.recall_lb = 0.91; m.benign_precision_lb = 0.91; m.benign_recall_lb = 0.91
    d = decide_gate({"missense": m}, cfg)

    # We just need to check the report states the lower bound.
    # The actual EvalReport initialization might require more arguments like config, etc.
    # Since we are writing before the implementation, we can just assert it doesn't fail
    # or rely on the doer to make sure the report has the info.
    report = EvalReport(
        run_id="r1", generated_at="now", labels_snapshot="123", benchmark_size=100, train_dev_size=20, holdout_size=80, holdout_label_counts={}, holdout_class_counts={},
        metrics={"missense": m},
        gate=d,

    )
    rendered = report.render()
    assert "0.91" in rendered # the lower bound
    assert "0.90" in rendered # the threshold

# AC-G7
def test_acg7_additive_no_behavior_removed():
    # Existing fields should still exist.
    cfg = make_eval_config(oracle_thresholds={})
    m = Metrics(1.0, 1.0, 1.0, {}, "missense", True, 1.0, 1.0)
    d = decide_gate({"missense": m}, cfg)
    assert hasattr(d, "status")
    assert hasattr(d, "stratum")
    assert hasattr(d, "reason")
    assert hasattr(d, "vus_authorized")
    assert hasattr(d, "per_stratum")
