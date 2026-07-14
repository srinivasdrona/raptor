"""PRD-06 checker round-3 findings (planner-authored, spec-correct invariants).

2 blockers + 2 majors + 1 minor, all eval-integrity. RED against the round-2-fixed
harness:

  BLOCKER-1  abstain-laundering: a model that calls all pathogenic correctly and
             ABSTAINS on a whole benign truth class shows precision=recall=1.0 but
             has demonstrated ZERO benign discrimination -> such a stratum must be
             NON-GATING (per-class CALLED-coverage floor, FR4 benign-direction /
             FR5), so the gate can never authorize on it.
  BLOCKER-2  degenerate/negative thresholds: an oracle_thresholds value of 0.0 (or
             negative) authorizes on zero performance -> must be strictly positive at
             load, and the gate must treat a non-positive/out-of-range threshold as
             UNMET (defense-in-depth for hand-built configs).
  MAJOR-1    a criterion whose ACMG FAMILY contradicts its stated `direction` (e.g.
             BA1/pathogenic) is corrupt upstream data (it would also blind checks.py)
             -> must FAIL LOUD, never be silently resolved by family.
  MAJOR-2    PP5/BP6 (ClinVar-assertion-derived) circularity must be STRUCTURALLY
             excluded -> forbidden in automatable_criteria at load, and never scored
             by the combiner even if a hand-built config lists them.
  MINOR      the report's config_pins must capture EVERY pin needed to reproduce the
             authorizing run (automatable_criteria, tavtigian_points, holdout_fraction,
             oracle_thresholds), not just seed/min_count/cutoffs.
"""
from __future__ import annotations

import pytest
import yaml

from raptor.eval.config import load_config, ConfigError
from raptor.eval.combine import implied_direction
from raptor.eval.gate import decide_gate
from raptor.eval.metrics import compute_metrics
from raptor.eval.harness import run_eval
from raptor.eval.model import BenchmarkRow, ImpliedCall, Metrics
from conftest import make_eval_config, make_labeled, evidence_for, oracle_thresholds_for, with_point_estimate_lb


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
    """A counts dict with adequate per-class CALLED coverage, so a gate test can
    isolate the threshold logic without tripping the coverage floor."""
    return {
        "tp": path_called, "fp": 0, "tn": benign_called, "fn": 0, "abstain": 0,
        "total_called": path_called + benign_called, "total": path_called + benign_called,
        "path_actual": path_called, "benign_actual": benign_called,
        "path_called": path_called, "benign_called": benign_called,
    }


# --------------------------------------------------------------------------
# [BLOCKER-1] abstain-laundering -> a whole-class abstention is NON-GATING
# --------------------------------------------------------------------------
def test_metrics_abstain_on_whole_class_is_non_gating():
    """A model that calls all pathogenic correctly and ABSTAINS on 100% of benign
    shows precision=recall=1.0, but demonstrated zero benign discrimination. The
    stratum must be NON-GATING (per-class CALLED-coverage floor) so it can never
    authorize a PASS -- however perfect the pathogenic-side metrics look."""
    bm = [BenchmarkRow(f"p{i}", "P", "missense") for i in range(3)] + \
         [BenchmarkRow(f"b{i}", "B", "missense") for i in range(3)]
    implied = [ImpliedCall(f"p{i}", "LP", 8) for i in range(3)] + \
              [ImpliedCall(f"b{i}", "no_call", 2) for i in range(3)]
    m = compute_metrics(implied, bm, make_eval_config(min_count_per_class=3))["missense"]
    assert m.precision == 1.0 and m.recall == 1.0          # metrics look perfect...
    assert m.counts["benign_called"] == 0                   # ...but zero benign were called
    assert m.counts["path_called"] == 3
    assert m.gating is False, "abstaining on an entire truth class must make the stratum non-gating"


def test_metrics_full_coverage_is_gating():
    """Control: adequate CALLED coverage on BOTH truth classes -> gating True."""
    bm = [BenchmarkRow(f"p{i}", "P", "missense") for i in range(3)] + \
         [BenchmarkRow(f"b{i}", "B", "missense") for i in range(3)]
    implied = [ImpliedCall(f"p{i}", "LP", 8) for i in range(3)] + \
              [ImpliedCall(f"b{i}", "LB", -8) for i in range(3)]
    m = compute_metrics(implied, bm, make_eval_config(min_count_per_class=3))["missense"]
    assert m.counts["path_called"] == 3 and m.counts["benign_called"] == 3
    assert m.gating is True


def test_gate_does_not_authorize_when_a_class_was_abstained_end_to_end():
    """Even with thresholds SET and perfect pathogenic-side metrics, a run that
    abstained on an entire truth class must NOT PASS (the gate sees a non-gating
    stratum)."""
    cfg = make_eval_config(oracle_thresholds=oracle_thresholds_for(0.9, 0.9), min_count_per_class=3)
    bm = [BenchmarkRow(f"p{i}", "P", "missense") for i in range(4)] + \
         [BenchmarkRow(f"b{i}", "B", "missense") for i in range(4)]
    implied = [ImpliedCall(f"p{i}", "LP", 8) for i in range(4)] + \
              [ImpliedCall(f"b{i}", "no_call", 2) for i in range(4)]
    metrics = compute_metrics(implied, bm, cfg)
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS"
    assert d.vus_authorized is False


def test_gate_defense_in_depth_rejects_abstained_class_when_counts_present():
    """Defense-in-depth: the gate is the authorization boundary and must not blindly
    trust a hand-built `gating=True`; if per-class CALLED counts are present and a
    class is below the coverage floor, it must not PASS."""
    cfg = make_eval_config(oracle_thresholds=oracle_thresholds_for(0.9, 0.9), min_count_per_class=10)
    starved = _full_counts(path_called=20, benign_called=0)  # benign abstained-out
    metrics = {"missense": with_point_estimate_lb(Metrics(1.0, 1.0, 1.0, starved, "missense", gating=True))}
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS"
    assert d.vus_authorized is False


# --------------------------------------------------------------------------
# [BLOCKER-2] degenerate / negative oracle thresholds must never authorize
# --------------------------------------------------------------------------
def test_config_rejects_nonpositive_threshold(tmp_path):
    """A pre-registered threshold of 0.0 authorizes on zero performance -- not a real
    target. oracle_thresholds values must be strictly positive (0 < v <= 1)."""
    for bad in (
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.0, "recall": 0.9, "gating": True}}},
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.9, "recall": 0.0, "gating": True}}},
    ):
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, oracle_thresholds=bad))
    # a genuine strictly-positive, pinned target (both pinned strata) still loads
    valid = oracle_thresholds_for(0.90, 0.85)
    valid["strata"]["truncating"] = {
        "precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"],
    }
    load_config(_write_config(tmp_path, oracle_thresholds=valid))


def test_gate_rejects_nonpositive_threshold_defense_in_depth():
    """A hand-built config bypassing load_config with a zero/negative threshold must
    never satisfy the gate -- an out-of-range threshold is treated as UNMET."""
    for bad_precision in (0.0, -1.0):
        cfg = make_eval_config(oracle_thresholds=oracle_thresholds_for(bad_precision, 0.9))
        metrics = {"missense": with_point_estimate_lb(Metrics(0.0, 0.95, 1.0, _full_counts(), "missense", True))}
        d = decide_gate(metrics, cfg)
        assert d.status != "PASS", f"non-positive threshold {bad_precision!r} must not authorize"
        assert d.vus_authorized is False


# --------------------------------------------------------------------------
# [MAJOR-1] family/direction mismatch must FAIL LOUD (also protects checks.py)
# --------------------------------------------------------------------------
def test_combiner_family_direction_mismatch_fails_loud():
    """A criterion whose ACMG family contradicts its stated `direction` (BA1 is
    benign-evidence, PVS1 is pathogenic-evidence) is corrupt upstream data -- it would
    also blind the oracle-blind contradiction checks (checks.py keys on `direction`).
    It must raise, never be silently resolved by family."""
    cfg = make_eval_config()
    with pytest.raises(ValueError):
        implied_direction([("BA1", "stand_alone", "pathogenic")], cfg)   # benign family, pathogenic label
    with pytest.raises(ValueError):
        implied_direction([("PVS1", "very_strong", "benign")], cfg)      # pathogenic family, benign label
    # a CONSISTENT direction still scores by family
    assert implied_direction([("BA1", "stand_alone", "benign")], cfg).points == -8
    assert implied_direction([("PVS1", "very_strong", "pathogenic")], cfg).points == 8


# --------------------------------------------------------------------------
# [MAJOR-2] PP5/BP6 ClinVar-circularity must be STRUCTURALLY excluded
# --------------------------------------------------------------------------
def test_config_forbids_clinvar_circular_criteria(tmp_path):
    """PP5/BP6/PS4 derive from a variant's own ClinVar assertion (R-A2 circularity;
    PS4 via BIAS-3.0.0's ClinVar-submitter fallback). Their exclusion must
    be structural, not merely absent-by-convention -- listing them in
    automatable_criteria must fail loud at load."""
    for bad in (["PVS1", "PM2", "PP5"], ["PVS1", "PM2", "BP6"], ["PVS1", "PM2", "PS4"]):
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, automatable_criteria=bad))


def test_combiner_never_scores_forbidden_criteria_even_if_listed():
    """Defense-in-depth: even a hand-built config that lists PP5/BP6/PS4 must never
    score them (they contribute zero points -- never a laundered ClinVar signal)."""
    cfg = make_eval_config(automatable_criteria=["PVS1", "PM2", "PP5", "BP6", "PS4"])
    assert implied_direction([("PP5", "strong", "pathogenic")], cfg).points == 0
    assert implied_direction([("BP6", "strong", "benign")], cfg).points == 0
    assert implied_direction([("PS4", "strong", "pathogenic")], cfg).points == 0


# --------------------------------------------------------------------------
# [MINOR] report provenance must capture every reproducing pin
# --------------------------------------------------------------------------
def test_report_provenance_includes_all_config_pins():
    """FR9/FR10: an auditor must reconstruct the EXACT authorizing config from the
    report -- config_pins must include automatable_criteria, tavtigian_points,
    holdout_fraction, and oracle_thresholds, not just seed/min_count/cutoffs."""
    variants = [make_labeled(f"p{i}", label="P", submitter_count=3) for i in range(4)] + \
               [make_labeled(f"b{i}", label="B", submitter_count=3) for i in range(4)]
    report = run_eval(make_eval_config(), variants, evidence_for(variants))
    pins = report.config_pins
    for key in ("automatable_criteria", "tavtigian_points", "holdout_fraction", "oracle_thresholds"):
        assert key in pins, f"config_pins missing {key!r} -- provenance is not reproducible"
