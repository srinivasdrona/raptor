"""PRD-06 checker round-4 findings (planner-authored, spec-correct invariants).

2 blockers + 2 majors + 1 minor. The round-3 coverage floor stopped "abstain on a
whole class" but NOT the deeper class-imbalance laundering the checker then found:

  BLOCKER-1  benign-direction not measured (FR4 REQUIRES it): on a pathogenic-heavy
             benchmark a model that calls EVERYTHING likely-pathogenic scores
             precision~0.9 / recall=1.0 while getting 100% of benign WRONG (tn=0).
             Metrics must compute benign-direction precision/recall and the gate must
             require BOTH directions clear the Oracle thresholds (same pre-registered
             bar applied to each direction -- stricter, no schema change).
  BLOCKER-2  min_count_per_class=0 disables the power/coverage floors -> load must
             reject it (>=1) and the gate must fail-closed for <=0.
  MAJOR-1    the PP5/BP6 ban is case-sensitive -- 'pp5' bypasses it and scores;
             criterion codes must be normalized (upper) before ban/automatable checks.
  MAJOR-2    label-row snapshots are never checked against config.labels_snapshot --
             the report can cite one snapshot while scoring another/mixed set; a
             mismatch must fail loud.
  MINOR      the gate's coverage defense fail-OPENS on missing counts; a Metrics with
             no per-class CALLED counts must not be authorized (fail-closed at PASS).
"""
from __future__ import annotations

import pytest
import yaml

from raptor.eval.config import load_config, ConfigError
from raptor.eval.combine import implied_direction
from raptor.eval.gate import decide_gate
from raptor.eval.metrics import compute_metrics
from raptor.eval.benchmark import build_benchmark
from raptor.eval.model import BenchmarkRow, ImpliedCall, Metrics
from conftest import make_eval_config, make_labeled, oracle_thresholds_for, with_point_estimate_lb


def _valid_raw() -> dict:
    return {
        "automatable_criteria": ["PVS1", "PS3", "PM1", "PM2", "PP3", "BA1", "BS1", "BS2", "BP4", "BP7"],
        "tavtigian_points": {"supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8, "stand_alone": 8},
        "tavtigian_cutoffs": {"pathogenic_min": 10, "likely_pathogenic_min": 6, "vus_min": 0,
                              "vus_max": 5, "likely_benign_max": -1, "benign_max": -7},
        "min_count_per_class": 10,
        "split": {"seed": 42, "holdout_fraction": 0.3},
        "oracle_thresholds": {},
        "labels_snapshot": "clinvar_2026-07-01",
    }


def _write_config(tmp_path, **overrides) -> str:
    raw = _valid_raw()
    raw.update(overrides)
    p = tmp_path / "eval.yaml"
    p.write_text(yaml.safe_dump(raw))
    return str(p)


def _full_counts(path_called: int = 20, benign_called: int = 20) -> dict:
    return {
        "tp": path_called, "fp": 0, "tn": benign_called, "fn": 0, "abstain": 0,
        "total_called": path_called + benign_called, "total": path_called + benign_called,
        "path_actual": path_called, "benign_actual": benign_called,
        "path_called": path_called, "benign_called": benign_called,
    }


# --------------------------------------------------------------------------
# [BLOCKER-1] benign-direction must be measured AND gated (FR4)
# --------------------------------------------------------------------------
def test_metrics_computes_benign_direction():
    """Metrics must expose benign-direction precision/recall (FR4), not only the
    pathogenic direction. Hand-computed: tp=2, fp=1, tn=2, fn=1."""
    bm = [BenchmarkRow("b1", "B", "missense"), BenchmarkRow("b2", "B", "missense"),
          BenchmarkRow("b3", "B", "missense"), BenchmarkRow("p1", "P", "missense"),
          BenchmarkRow("p2", "P", "missense"), BenchmarkRow("p3", "P", "missense")]
    implied = [ImpliedCall("b1", "LB", -8), ImpliedCall("b2", "LB", -8), ImpliedCall("b3", "LP", 8),
               ImpliedCall("p1", "LP", 8), ImpliedCall("p2", "LP", 8), ImpliedCall("p3", "LB", -8)]
    m = compute_metrics(implied, bm, make_eval_config(min_count_per_class=2))["missense"]
    assert m.precision == pytest.approx(2 / 3)          # tp/(tp+fp)
    assert m.recall == pytest.approx(2 / 3)             # tp/(tp+fn)
    assert m.benign_precision == pytest.approx(2 / 3)   # tn/(tn+fn)
    assert m.benign_recall == pytest.approx(2 / 3)      # tn/(tn+fp)  (specificity)


def test_gate_rejects_call_everything_pathogenic():
    """A model that calls EVERYTHING likely-pathogenic on a pathogenic-heavy benchmark
    scores precision>=0.85 / recall=1.0 but mislabels 100% of benign (tn=0). FR4 demands
    benign-direction discrimination; the gate must NOT authorize a VUS run."""
    bm = [BenchmarkRow(f"p{i}", "P", "missense") for i in range(18)] + \
         [BenchmarkRow(f"b{i}", "B", "missense") for i in range(2)]
    implied = [ImpliedCall(f"p{i}", "LP", 8) for i in range(18)] + \
              [ImpliedCall(f"b{i}", "LP", 8) for i in range(2)]  # benign mislabeled LP
    cfg = make_eval_config(oracle_thresholds=oracle_thresholds_for(0.85, 0.85), min_count_per_class=2)
    metrics = compute_metrics(implied, bm, cfg)
    m = metrics["missense"]
    assert m.precision >= 0.85 and m.recall == 1.0     # pathogenic-side looks fine...
    assert m.benign_recall == 0.0                       # ...but zero benign discrimination
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS", "a model mislabeling 100% of benign must never authorize a VUS run"
    assert d.vus_authorized is False


def test_gate_passes_with_good_both_direction_discrimination():
    """Control: a model that discriminates BOTH directions well still PASSes. n=40
    per class (not 10) -- under the real Clopper-Pearson LOWER bound (gate-fidelity,
    Arm C) a perfect n=10 point estimate (LB(10,10)~=0.6915) no longer clears a 0.90
    threshold; n=40 (LB(40,40)~=0.9119) genuinely does. This is the intended effect
    of the fix, not a weakening -- an underpowered "perfect" run must no longer pass."""
    bm = [BenchmarkRow(f"p{i}", "P", "missense") for i in range(40)] + \
         [BenchmarkRow(f"b{i}", "B", "missense") for i in range(40)]
    implied = [ImpliedCall(f"p{i}", "LP", 8) for i in range(40)] + \
              [ImpliedCall(f"b{i}", "LB", -8) for i in range(40)]
    cfg = make_eval_config(oracle_thresholds=oracle_thresholds_for(0.9, 0.9), min_count_per_class=36)
    d = decide_gate(compute_metrics(implied, bm, cfg), cfg)
    assert d.status == "PASS" and d.vus_authorized is True


# --------------------------------------------------------------------------
# [BLOCKER-2] min_count_per_class=0 must not disable the floors
# --------------------------------------------------------------------------
def test_config_rejects_zero_min_count(tmp_path):
    """min_count_per_class=0 makes every stratum trivially gating (FR5 defeated) --
    it must be strictly positive."""
    with pytest.raises(ConfigError):
        load_config(_write_config(tmp_path, min_count_per_class=0))


def test_gate_fails_closed_on_nonpositive_min_count():
    """Defense-in-depth: a hand-built config with min_count<=0 disables the coverage
    floor -- the gate must refuse to authorize (a benign-abstained stratum must not
    slip through)."""
    cfg = make_eval_config(oracle_thresholds=oracle_thresholds_for(0.9, 0.9), min_count_per_class=0)
    counts = _full_counts(path_called=20, benign_called=0)  # benign abstained-out
    metrics = {"missense": with_point_estimate_lb(Metrics(1.0, 1.0, 1.0, counts, "missense", gating=True))}
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS"
    assert d.vus_authorized is False


# --------------------------------------------------------------------------
# [MAJOR-1] the ClinVar-circular ban must be case-insensitive
# --------------------------------------------------------------------------
def test_config_forbids_clinvar_circular_criteria_case_insensitive(tmp_path):
    """A lowercase 'pp5' is still PP5 -- structurally forbidden regardless of casing."""
    with pytest.raises(ConfigError):
        load_config(_write_config(tmp_path, automatable_criteria=["PVS1", "PM2", "pp5"]))
    # PS4 (BIAS-3.0.0 ClinVar-submitter fallback) inherits the same case-insensitive ban.
    with pytest.raises(ConfigError):
        load_config(_write_config(tmp_path, automatable_criteria=["PVS1", "PM2", "ps4"]))


def test_combiner_never_scores_forbidden_criteria_case_insensitive():
    """Even a lowercase 'pp5'/'bp6'/'ps4' must never be scored (case-insensitive R-A2 ban)."""
    cfg = make_eval_config(automatable_criteria=["PVS1", "PM2", "pp5", "bp6", "ps4"])
    assert implied_direction([("pp5", "strong", "pathogenic")], cfg).points == 0
    assert implied_direction([("bp6", "strong", "benign")], cfg).points == 0
    assert implied_direction([("ps4", "strong", "pathogenic")], cfg).points == 0


# --------------------------------------------------------------------------
# [MAJOR-2] label snapshots must match the cited config.labels_snapshot
# --------------------------------------------------------------------------
def test_benchmark_rejects_label_snapshot_mismatch():
    """Provenance integrity: a scored label whose snapshot != config.labels_snapshot
    must fail loud -- the report must never cite a snapshot it did not actually score."""
    cfg = make_eval_config()  # labels_snapshot="clinvar_2026-07-01"
    variants = [make_labeled("v1", label="P", submitter_count=3, snapshot="clinvar_2020-01-01")]
    with pytest.raises(ValueError):
        build_benchmark(variants, cfg)


def test_benchmark_accepts_matching_snapshot():
    """Control: labels whose snapshot matches the config are scored normally."""
    cfg = make_eval_config()
    variants = [make_labeled("v1", label="P", submitter_count=3, snapshot="clinvar_2026-07-01")]
    rows = build_benchmark(variants, cfg)
    assert {r.variant_id for r in rows} == {"v1"}


# --------------------------------------------------------------------------
# [MINOR] the gate coverage defense must fail CLOSED on missing counts
# --------------------------------------------------------------------------
def test_gate_fail_closed_on_missing_coverage_counts():
    """The gate must not PASS a Metrics that lacks per-class CALLED coverage counts:
    it cannot confirm the model was actually measured on both classes."""
    cfg = make_eval_config(oracle_thresholds=oracle_thresholds_for(0.9, 0.9), min_count_per_class=10)
    metrics = {"missense": with_point_estimate_lb(Metrics(0.95, 0.95, 0.95, {}, "missense", gating=True,
                                   benign_precision=0.95, benign_recall=0.95))}
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS"
    assert d.vus_authorized is False
