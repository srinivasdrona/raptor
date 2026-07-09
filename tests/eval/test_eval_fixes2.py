"""PRD-06 checker round-2 findings (planner-authored, spec-correct invariants).

2 blockers + 1 major, all eval-integrity: the gate must not authorize on a single
cherry-picked metric; the combiner must derive the pathogenic/benign sign from the
criterion FAMILY (not a launderable arg); the conflict exclusion must not be
over-broad. RED against the round-1-fixed harness.
"""
from __future__ import annotations

import pytest
import yaml

from raptor.eval.config import load_config, ConfigError
from raptor.eval.combine import implied_direction
from raptor.eval.gate import decide_gate
from raptor.eval.benchmark import build_benchmark
from raptor.eval.model import Metrics
from conftest import make_eval_config, make_labeled


def _valid_raw() -> dict:
    return {
        "automatable_criteria": ["PVS1", "PS4", "PM1", "PM2", "PP3", "BA1", "BS1", "BS2", "BP4", "BP7"],
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
# [BLOCKER] the gate must not authorize on a single cherry-picked metric —
# precision AND recall are mandatory gating targets (concordance can't substitute)
# --------------------------------------------------------------------------
def test_gate_concordance_only_cannot_pass():
    """A concordance-only threshold must NOT yield PASS while precision/recall are
    degenerate (0) — authorizing clinical use on concordance alone is a false PASS."""
    cfg = make_eval_config(oracle_thresholds={"concordance": 1.0})
    metrics = {"missense": Metrics(precision=0.0, recall=0.0, concordance=1.0,
                                   counts={}, stratum="missense", gating=True)}
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS"
    assert d.vus_authorized is False


def test_config_requires_precision_and_recall_when_thresholds_set(tmp_path):
    """A non-empty oracle_thresholds MUST include both precision and recall — a
    concordance-only (or precision-only) threshold block fails loud at load."""
    for bad in ({"concordance": 0.9}, {"precision": 0.9}, {"recall": 0.9}):
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, oracle_thresholds=bad))
    # both present -> loads (concordance optional-additional)
    load_config(_write_config(tmp_path, oracle_thresholds={"precision": 0.9, "recall": 0.9}))
    load_config(_write_config(tmp_path, oracle_thresholds={"precision": 0.9, "recall": 0.9, "concordance": 0.8}))


def test_gate_still_passes_with_precision_and_recall_met():
    """Control: a genuinely-passing case (precision+recall thresholds met) still PASSes."""
    cfg = make_eval_config(oracle_thresholds={"precision": 0.9, "recall": 0.9})
    metrics = {"missense": Metrics(0.95, 0.95, 0.95, {}, "missense", True)}
    d = decide_gate(metrics, cfg)
    assert d.status == "PASS"
    assert d.vus_authorized is True


# --------------------------------------------------------------------------
# [BLOCKER] combiner must derive sign from the criterion FAMILY, not the arg
# --------------------------------------------------------------------------
def test_combiner_sign_from_family_not_supplied_direction():
    """The pathogenic/benign sign is a property of the ACMG criterion family
    (P*→pathogenic, B*→benign); a mislabeled `direction` arg must NOT flip it
    (a laundering vector)."""
    cfg = make_eval_config()
    # BA1 mislabeled pathogenic must still be benign (-8 / LB), never +8/LP
    r = implied_direction([("BA1", "stand_alone", "pathogenic")], cfg)
    assert (r.points, r.implied) == (-8, "LB")
    # PVS1 mislabeled benign must still be pathogenic (+8 / LP)
    r = implied_direction([("PVS1", "very_strong", "benign")], cfg)
    assert (r.points, r.implied) == (8, "LP")


# --------------------------------------------------------------------------
# [MAJOR] conflict exclusion must not be over-broad
# --------------------------------------------------------------------------
def test_conflict_exclusion_not_overbroad():
    """"no conflicts reported" is a CONCORDANT status and must be KEPT; only a
    genuinely conflicting status ("conflicting classifications") is excluded."""
    variants = [
        make_labeled("keep_noconflict", label="P",
                     review_status="criteria provided, multiple submitters, no conflicts reported",
                     submitter_count=4),
        make_labeled("drop_conflicting", label="P",
                     review_status="criteria provided, conflicting classifications", submitter_count=5),
    ]
    ids = {r.variant_id for r in build_benchmark(variants, make_eval_config())}
    assert ids == {"keep_noconflict"}, "over-broad conflict match dropped a concordant variant"
