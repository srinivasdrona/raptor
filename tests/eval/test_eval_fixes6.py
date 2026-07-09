"""PRD-06 checker round-6 findings (planner-authored, spec-correct invariants).

1 blocker + 2 majors -- the last residual laundering surfaces:

  BLOCKER  the PP5/BP6 ban was only `strip().upper()`-normalized, so HIDDEN/INTERNAL
           whitespace ('PP5\\u200b', 'P P5') and other non-ACMG codes bypassed it and
           scored. Fix: validate criterion codes against the exact ACMG-2015 code set --
           config REJECTS a non-ACMG/forbidden automatable code (governed input), the
           combiner SKIPS any non-ACMG/forbidden code (runtime evidence, never scored).
  MAJOR-1  a criterion fires at most ONCE (ACMG); duplicate calls were summed and could
           inflate the implied call -> a duplicate (canonical) criterion must fail loud.
  MAJOR-2  the gate's fail-closed PASS defense checked per-class CALLED counts but not
           per-truth-class counts -> a hand-built Metrics could bypass the min-count
           proof; require path_actual/benign_actual too.
"""
from __future__ import annotations

import pytest
import yaml

from raptor.eval.config import load_config, ConfigError
from raptor.eval.combine import implied_direction
from raptor.eval.gate import decide_gate
from raptor.eval.model import Metrics
from conftest import make_eval_config


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
# [BLOCKER] strict ACMG canonicalization -- hidden/internal whitespace + non-ACMG
# --------------------------------------------------------------------------
def test_config_rejects_hidden_or_internal_whitespace_code(tmp_path):
    """Zero-width ('PP5\\u200b') / internal ('P P5') whitespace must not smuggle a
    forbidden (or any malformed) code past the ban -- such a code is not a canonical
    ACMG code and must fail loud at load."""
    for bad in (["PVS1", "PM2", "PP5\u200b"], ["PVS1", "PM2", "P P5"], ["PVS1", "PM2", "BP6\u200b"]):
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, automatable_criteria=bad))


def test_config_rejects_non_acmg_code(tmp_path):
    """A criterion code that is not a canonical ACMG-2015 code is a config error."""
    for bad in (["PVS1", "ZZZ9"], ["PVS1", "FOO"], ["PVS1", "PP99"]):
        with pytest.raises(ConfigError):
            load_config(_write_config(tmp_path, automatable_criteria=bad))


def test_combiner_never_scores_hidden_whitespace_forbidden():
    """A zero-width / internal-whitespace PP5 in a hand-built config must never be
    scored; the checker's exact scenario (poisoned PP5 + real PVS1) must yield only the
    PVS1 contribution (8), never 12."""
    cfg = make_eval_config(automatable_criteria=["PVS1", "PM2", "PP5\u200b", "P P5"])
    assert implied_direction([("PP5\u200b", "strong", "pathogenic")], cfg).points == 0
    assert implied_direction([("P P5", "strong", "pathogenic")], cfg).points == 0
    r = implied_direction([("PP5\u200b", "strong", "pathogenic"),
                           ("PVS1", "very_strong", "pathogenic")], cfg)
    assert r.points == 8


# --------------------------------------------------------------------------
# [MAJOR-1] a criterion fires at most once -- duplicates must fail loud
# --------------------------------------------------------------------------
def test_combiner_rejects_duplicate_criterion():
    """A criterion fires at most once (ACMG). A duplicate call is corrupt scorer output
    and must fail loud -- never silently summed into an inflated point total."""
    cfg = make_eval_config()
    with pytest.raises(ValueError):
        implied_direction([("PP3", "supporting", "pathogenic"),
                           ("PP3", "supporting", "pathogenic")], cfg)
    # case/whitespace variants of the SAME canonical criterion are still duplicates
    with pytest.raises(ValueError):
        implied_direction([("PM2", "moderate", "pathogenic"),
                           ("pm2 ", "moderate", "pathogenic")], cfg)


# --------------------------------------------------------------------------
# [MAJOR-2] the PASS-time coverage defense must also prove per-truth-class counts
# --------------------------------------------------------------------------
def test_gate_fail_closed_on_missing_truth_counts():
    """The fail-closed PASS defense must require per-truth-class counts
    (path_actual/benign_actual), not only CALLED counts -- a hand-built Metrics with
    called counts but no truth-count proof must not authorize a VUS run."""
    cfg = make_eval_config(oracle_thresholds={"precision": 0.9, "recall": 0.9})
    counts = {"path_called": 20, "benign_called": 20}  # called present, truth counts absent
    metrics = {"missense": Metrics(0.95, 0.95, 0.95, counts, "missense", gating=True,
                                   benign_precision=0.95, benign_recall=0.95)}
    d = decide_gate(metrics, cfg)
    assert d.status != "PASS"
    assert d.vus_authorized is False
