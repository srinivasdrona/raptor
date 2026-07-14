"""PRD-06 checker round-1 findings (planner-authored, spec-correct invariants).

Covers the 2 blockers + 4 majors + 1 minor. RED against the pre-fix harness.
The eval harness is the eval-integrity boundary, so every one of these is about
"can it emit a false/laundered PASS or silently mis-measure?".
"""
from __future__ import annotations

import math

import pytest
import yaml

from raptor.eval.config import load_config, ConfigError
from raptor.eval.combine import implied_direction
from raptor.eval.gate import decide_gate
from raptor.eval.benchmark import build_benchmark
from raptor.eval.split import split_benchmark
from raptor.eval.model import BenchmarkRow, Metrics
from raptor.eval.harness import run_eval
from conftest import make_eval_config, make_labeled, evidence_for, oracle_thresholds_for, with_point_estimate_lb


# --------------------------------------------------------------------------
# config helpers
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# [BLOCKER] gate must never false-PASS on invalid / non-finite thresholds/metrics
# --------------------------------------------------------------------------
def test_gate_nan_metric_never_passes():
    """A NaN metric must NOT satisfy a threshold (`nan < x` is False in Python) —
    the gate must treat non-finite as unmet, never PASS."""
    cfg = make_eval_config(oracle_thresholds=oracle_thresholds_for(0.9, 0.9))
    metrics = {"missense": with_point_estimate_lb(Metrics(float("nan"), float("nan"), float("nan"), {}, "missense", True))}
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS"
    assert d.vus_authorized is False


def test_gate_unknown_threshold_key_never_passes():
    """A stratum spec missing the required `precision`/`recall` keys entirely
    (the new nested schema has no free-form metric-name lookup to spoof —
    only the fixed precision/recall fields gate) must never be silently
    satisfied — never a PASS."""
    cfg = make_eval_config(oracle_thresholds={
        "confidence": 0.95,
        "strata": {"missense": {"gating": True, "directions": ["pathogenic", "benign"]}},
    })
    metrics = {"missense": with_point_estimate_lb(Metrics(1.0, 1.0, 1.0, {}, "missense", True))}
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS"
    assert d.vus_authorized is False


def test_config_rejects_invalid_oracle_thresholds(tmp_path):
    """load_config must fail loud on a malformed nested threshold block —
    missing strata/missense, a non-finite value, or an out-of-(0,1] value
    (else a bad pin reaches the gate)."""
    for bad in (
        {"confidence": 0.95, "strata": {}},
        {"confidence": 0.95, "strata": {"missense": {"precision": float("nan"), "recall": 0.85, "gating": True}}},
        {"confidence": 0.95, "strata": {"missense": {"precision": 1.5, "recall": 0.85, "gating": True}}},
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.9, "recall": -0.1, "gating": True}}},
    ):
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, oracle_thresholds=bad))
    # a valid, pinned threshold block still loads
    load_config(_write_config(tmp_path, oracle_thresholds=oracle_thresholds_for(0.90, 0.85)))


# --------------------------------------------------------------------------
# [BLOCKER] combiner must only score automatable criteria (R-A2 circularity)
# --------------------------------------------------------------------------
def test_combiner_ignores_non_automatable_criteria():
    """PP5/BP6 (excluded for ClinVar-circularity) and unknown criteria must
    contribute ZERO — never scored into the implied direction."""
    cfg = make_eval_config()  # automatable_criteria excludes PP5/BP6/ZZZ
    # PP5 alone -> ignored -> 0 points -> no_call (not LP)
    r = implied_direction([("PP5", "strong", "pathogenic")], cfg)
    assert (r.points, r.implied) == (0, "no_call")
    # PP5 + PVS1 -> only PVS1 counts -> +8 (not +12)
    r = implied_direction([("PP5", "strong", "pathogenic"), ("PVS1", "very_strong", "pathogenic")], cfg)
    assert r.points == 8
    # unknown criterion ignored
    r = implied_direction([("ZZZ", "very_strong", "pathogenic")], cfg)
    assert (r.points, r.implied) == (0, "no_call")


# --------------------------------------------------------------------------
# [MAJOR] split must not leak duplicate variant_ids
# --------------------------------------------------------------------------
def test_split_rejects_or_dedups_duplicate_ids():
    """A benchmark must have one row per variant identity; a duplicate must not
    silently land in BOTH halves. Fail loud (or dedup) — never leak."""
    rows = [BenchmarkRow("dup", "P", "missense"), BenchmarkRow("dup", "P", "missense"),
            BenchmarkRow("x", "B", "missense")]
    try:
        train, holdout = split_benchmark(rows, make_eval_config())
    except Exception:
        return  # fail-loud on duplicate is acceptable
    train_ids = {r.variant_id for r in train}
    holdout_ids = {r.variant_id for r in holdout}
    assert train_ids.isdisjoint(holdout_ids), "duplicate variant_id leaked across the split"


# --------------------------------------------------------------------------
# [MAJOR] benchmark exclusions: conflicting review_status + invalid labels
# --------------------------------------------------------------------------
def test_benchmark_excludes_conflicting_review_status():
    variants = [
        make_labeled("keep", label="P", review_status="criteria provided, multiple submitters", submitter_count=3),
        make_labeled("drop", label="P", review_status="criteria provided, conflicting classifications", submitter_count=5),
    ]
    ids = {r.variant_id for r in build_benchmark(variants, make_eval_config())}
    assert ids == {"keep"}, "a conflicting-review-status variant must be excluded (R-A2)"


def test_benchmark_excludes_non_scoreable_labels():
    """Only {P,LP,LB,B} are scoreable; anything else (VUS, not_provided) must be
    excluded so metrics never silently mis-count against an unmappable label."""
    variants = [
        make_labeled("v_p", label="P", submitter_count=3),
        make_labeled("v_vus", label="VUS", submitter_count=3),
        make_labeled("v_np", label="not_provided", submitter_count=3),
    ]
    ids = {r.variant_id for r in build_benchmark(variants, make_eval_config())}
    assert ids == {"v_p"}


# --------------------------------------------------------------------------
# [MAJOR] config validation: stand_alone required + holdout_fraction sane
# --------------------------------------------------------------------------
def test_config_requires_stand_alone_point(tmp_path):
    """`stand_alone` is used (BA1) — a config missing it must fail loud at load,
    not KeyError at runtime."""
    pts = {"supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8}  # no stand_alone
    with pytest.raises(ConfigError):
        load_config(_write_config(tmp_path, tavtigian_points=pts))


@pytest.mark.parametrize("frac", [1.5, -0.5, 0.0, 1.0, "nope"])
def test_config_rejects_bad_holdout_fraction(tmp_path, frac):
    with pytest.raises(ConfigError):
        load_config(_write_config(tmp_path, split={"seed": 42, "holdout_fraction": frac}))


# --------------------------------------------------------------------------
# [MINOR] report must carry code version + config pins (FR9/AC9 provenance)
# --------------------------------------------------------------------------
def test_report_states_code_version_and_config_pins():
    variants = [make_labeled(f"v{i}", label=("P" if i % 2 else "B"), submitter_count=3) for i in range(12)]
    report = run_eval(make_eval_config(), variants, evidence_for(variants))
    low = report.render().lower()
    assert "code version" in low or "code_version" in low, "report omits code version (FR9)"
    assert "config pins" in low or "pins" in low or "seed" in low, "report omits config pins (FR9)"


# --------------------------------------------------------------------------
# [BLOCKER 1] load_config accepts oracle drift (confidence and exact strata)
# --------------------------------------------------------------------------
def test_config_rejects_oracle_drift(tmp_path):
    """BLOCKER 1: _validate_oracle_thresholds must pin confidence exactly 0.95 and 
    exact stratum keys missense+truncating; no missing/extra ghost.
    
    RED tests:
      * load_config temp clone with confidence .5, 0.9, 1.0, bool, NaN => ConfigError.
      * add extra ghost stratum (even well-formed/gating false or true) => ConfigError.
      * omit missense or truncating => ConfigError.
      * exact config loads.
      * show extra gated stratum cannot reach v1 decide_gate because loader rejects it.
    """
    # 1. confidence validation
    for bad_conf in (0.5, 0.9, 1.0, True, False, float("nan")):
        bad_thresholds = {
            "confidence": bad_conf,
            "strata": {
                "missense": {
                    "precision": 0.90,
                    "recall": 0.85,
                    "gating": True,
                    "directions": ["pathogenic", "benign"]
                },
                "truncating": {
                    "precision": 0.95,
                    "recall": 0.95,
                    "gating": True,
                    "directions": ["pathogenic"]
                }
            }
        }
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, oracle_thresholds=bad_thresholds))

    # 2. Extra ghost stratum (even well-formed/gating false or true)
    ghost_thresholds = {
        "confidence": 0.95,
        "strata": {
            "missense": {
                "precision": 0.90,
                "recall": 0.85,
                "gating": True,
                "directions": ["pathogenic", "benign"]
            },
            "truncating": {
                "precision": 0.95,
                "recall": 0.95,
                "gating": True,
                "directions": ["pathogenic"]
            },
            "ghost": {
                "precision": 0.90,
                "recall": 0.80,
                "gating": False,
                "directions": ["pathogenic"]
            }
        }
    }
    with pytest.raises(ConfigError):
        load_config(_write_config(tmp_path, oracle_thresholds=ghost_thresholds))

    # 3. Omit missense
    missing_missense = {
        "confidence": 0.95,
        "strata": {
            "truncating": {
                "precision": 0.95,
                "recall": 0.95,
                "gating": True,
                "directions": ["pathogenic"]
            }
        }
    }
    with pytest.raises(ConfigError):
        load_config(_write_config(tmp_path, oracle_thresholds=missing_missense))

    # 4. Omit truncating
    missing_truncating = {
        "confidence": 0.95,
        "strata": {
            "missense": {
                "precision": 0.90,
                "recall": 0.85,
                "gating": True,
                "directions": ["pathogenic", "benign"]
            }
        }
    }
    with pytest.raises(ConfigError):
        load_config(_write_config(tmp_path, oracle_thresholds=missing_truncating))

    # 5. Exact valid config loads
    valid_thresholds = {
        "confidence": 0.95,
        "strata": {
            "missense": {
                "precision": 0.90,
                "recall": 0.85,
                "gating": True,
                "directions": ["pathogenic", "benign"]
            },
            "truncating": {
                "precision": 0.95,
                "recall": 0.95,
                "gating": True,
                "directions": ["pathogenic"]
            }
        }
    }
    loaded = load_config(_write_config(tmp_path, oracle_thresholds=valid_thresholds))
    assert loaded is not None

