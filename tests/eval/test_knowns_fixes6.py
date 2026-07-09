"""PRD-07 checker round-6 finding — the exclusion policy, closed DEFINITIVELY.

The root cause of the round-4/5/6 one-per-round churn was using raw `submitter_count < 2`
as a confidence proxy. It is wrong in BOTH directions:
  * a 1-star `single submitter` label can have NumberSubmitters>=2 (round 4);
  * a 3-star `reviewed by expert panel` / 4-star `practice guideline` label can have
    NumberSubmitters==1 and was being wrongly DROPPED (round 6).
Confidence is REVIEW-STATUS-driven. This test locks the FULL policy matrix over ClinVar's
finite review-status vocabulary, so the class is closed once (rule-of-2/C1 in the kit
catalog), not refined per round. Raw count is only a fallback proxy for an UNRECOGNIZED
status.
"""
from __future__ import annotations

import pytest

from raptor.eval.model import LabeledVariant
from raptor.eval.benchmark import build_benchmark
from conftest import make_eval_config


def _lv(vid, review, submitters=3, label="P", source="clingen_vcep"):
    return LabeledVariant(vid, label, review, submitters, source, "s1", False, "missense")


# High-confidence: KEPT regardless of submitter count (incl. single expert-panel submission).
_KEEP_STATUSES = [
    "practice guideline",
    "reviewed by expert panel",
    "criteria provided, multiple submitters, no conflicts",
]

# Low-confidence: EXCLUDED regardless of submitter count (incl. count-inflated single-submitter).
_EXCLUDE_STATUSES = [
    "criteria provided, single submitter",
    "criteria provided, conflicting classifications",
    "criteria provided, conflicting interpretations of pathogenicity",
    "no assertion criteria provided",
    "no assertion provided",
    "no classifications from unflagged records",
]


@pytest.mark.parametrize("count", [1, 5])
@pytest.mark.parametrize("status", _KEEP_STATUSES)
def test_high_confidence_status_kept_any_count(status, count):
    """A high-confidence review status is kept even with NumberSubmitters==1 -- an
    expert-panel/practice-guideline label must never be dropped by the count proxy."""
    bm = build_benchmark([_lv("v", status, submitters=count)], make_eval_config(labels_snapshot="s1"))
    assert {r.variant_id for r in bm} == {"v"}, f"{status!r} (count={count}) must be KEPT"


@pytest.mark.parametrize("count", [1, 5])
@pytest.mark.parametrize("status", _EXCLUDE_STATUSES)
def test_low_confidence_status_excluded_any_count(status, count):
    """A low-confidence review status is excluded even with NumberSubmitters>=2."""
    bm = build_benchmark([_lv("v", status, submitters=count)], make_eval_config(labels_snapshot="s1"))
    assert bm == [], f"{status!r} (count={count}) must be EXCLUDED"


def test_expert_panel_single_submitter_wins_dedup_over_default_clinvar():
    """An expert-panel label (count=1) must WIN the dedup over a default ClinVar duplicate
    (count=5) -- never dropped so the lower-ranked ClinVar label wins by default."""
    labels = [
        _lv("v", "reviewed", submitters=5, label="B", source="clinvar"),
        _lv("v", "reviewed by expert panel", submitters=1, label="P", source="clingen_vcep"),
    ]
    bm = build_benchmark(labels, make_eval_config(labels_snapshot="s1"))
    assert len(bm) == 1
    assert bm[0].source == "clingen_vcep" and bm[0].label == "P"
