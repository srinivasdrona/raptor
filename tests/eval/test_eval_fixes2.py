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


# --------------------------------------------------------------------------
# [BLOCKER] the gate must not authorize on a single cherry-picked metric —
# precision AND recall are mandatory gating targets (concordance can't substitute)
# --------------------------------------------------------------------------
def test_gate_concordance_only_cannot_pass():
    """A stratum spec missing the mandatory `recall` key must NOT yield PASS
    while precision/recall are degenerate (0) — concordance is not part of
    the nested per-stratum gating schema at all (precision+recall, both
    directions, are the only gated metrics now), so authorizing on it (or on
    a spec that omits recall) is a false PASS."""
    cfg = make_eval_config(oracle_thresholds={
        "confidence": 0.95,
        "strata": {"missense": {"precision": 0.9, "gating": True, "directions": ["pathogenic", "benign"]}},
    })
    metrics = {"missense": with_point_estimate_lb(Metrics(precision=0.0, recall=0.0, concordance=1.0,
                                   counts={}, stratum="missense", gating=True))}
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS"
    assert d.vus_authorized is False


def test_config_requires_precision_and_recall_when_thresholds_set(tmp_path):
    """A non-empty oracle_thresholds stratum MUST include both precision and
    recall — a spec missing either fails loud at load."""
    for bad in (
        {"confidence": 0.95, "strata": {"missense": {"gating": True}}},
        {"confidence": 0.95, "strata": {"missense": {"precision": 0.9, "gating": True}}},
        {"confidence": 0.95, "strata": {"missense": {"recall": 0.9, "gating": True}}},
    ):
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, oracle_thresholds=bad))
    # both present, pinned exactly, BOTH pinned strata present -> loads
    valid = oracle_thresholds_for(0.90, 0.85)
    valid["strata"]["truncating"] = {
        "precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"],
    }
    load_config(_write_config(tmp_path, oracle_thresholds=valid))


def test_gate_still_passes_with_precision_and_recall_met():
    """Control: a genuinely-passing case (precision+recall thresholds met on BOTH
    directions, with adequate per-class CALLED coverage) still PASSes."""
    cfg = make_eval_config(oracle_thresholds=oracle_thresholds_for(0.9, 0.9))
    counts = {"tp": 20, "fp": 0, "tn": 20, "fn": 0, "abstain": 0, "total_called": 40,
              "total": 40, "path_actual": 20, "benign_actual": 20,
              "path_called": 20, "benign_called": 20}
    metrics = {"missense": with_point_estimate_lb(Metrics(0.95, 0.95, 0.95, counts, "missense", True,
                                   benign_precision=0.95, benign_recall=0.95))}
    d = decide_gate(metrics, cfg)
    assert d.status == "PASS"
    assert d.vus_authorized is True


# --------------------------------------------------------------------------
# [BLOCKER] combiner must derive sign from the criterion FAMILY, not the arg
# --------------------------------------------------------------------------
def test_combiner_sign_from_family_not_supplied_direction():
    """The pathogenic/benign sign is a property of the ACMG criterion family
    (P*→pathogenic, B*→benign), NEVER a launderable `direction` arg. Round-3 MAJOR-1
    corrected this invariant: a `direction` that CONTRADICTS the family (e.g. BA1 is
    benign-evidence but labeled `pathogenic`) is corrupt upstream data -- it would also
    blind checks.py (which keys on `direction`) -- so it must FAIL LOUD, not be silently
    resolved. A laundering attempt therefore RAISES (it can never flip the sign)."""
    cfg = make_eval_config()
    # BA1 mislabeled pathogenic is corrupt -> raise (a laundering attempt cannot flip the sign)
    with pytest.raises(ValueError):
        implied_direction([("BA1", "stand_alone", "pathogenic")], cfg)
    # PVS1 mislabeled benign is corrupt -> raise
    with pytest.raises(ValueError):
        implied_direction([("PVS1", "very_strong", "benign")], cfg)
    # a CONSISTENT direction still scores by family
    assert implied_direction([("BA1", "stand_alone", "benign")], cfg).points == -8
    assert implied_direction([("PVS1", "very_strong", "pathogenic")], cfg).points == 8


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
