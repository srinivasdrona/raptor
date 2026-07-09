"""PRD-07 checker round-5 finding (planner-authored) — closed COMPREHENSIVELY.

ClinVar's review-status vocabulary is FINITE, so rather than iterate one low-quality
status per round, exclude the ENTIRE low-confidence set at once:
  * 1-star `criteria provided, single submitter`  (round 4)
  * any `conflicting` status                        (round 1 era)
  * 0-star `no assertion criteria provided` / `no assertion provided` /
    newer `no classifications ...`                  (this round)
Only the high-confidence remainder (2-star concordant, expert panel, practice guideline)
is kept.

Also fixes the `_SOURCE_RANK` INVERSION the checker re-flagged: expert adjudication and
curated literature were ranked BELOW default ClinVar, so a default DB entry could win a
dedup over an expert/curated label. Correct order (highest first): oracle_adjudication >
clingen (VCEP/3-star) > curated_literature > clinvar_2star_concordant > clinvar.
"""
from __future__ import annotations

from raptor.eval.model import LabeledVariant
from raptor.eval.benchmark import build_benchmark
from conftest import make_eval_config


def _lv(vid, review, submitters=3, label="P", source="clinvar"):
    return LabeledVariant(vid, label, review, submitters, source, "s1", False, "missense")


def test_zero_star_no_assertion_labels_excluded():
    """0-star records carry no ACMG criteria -> excluded even with a definitive label and
    NumberSubmitters>=2 (real TSC data shows ~12 such multi-SCV records would bypass a
    count-only check)."""
    labels = [
        _lv("keep", "criteria provided, multiple submitters, no conflicts",
            source="clinvar_2star_concordant"),
        _lv("drop_noassert_criteria", "no assertion criteria provided"),
        _lv("drop_noassert", "no assertion provided"),
        _lv("drop_noclass", "no classifications from unflagged records"),
    ]
    bm = build_benchmark(labels, make_eval_config(labels_snapshot="s1"))
    assert {r.variant_id for r in bm} == {"keep"}


def test_high_confidence_statuses_kept():
    """Regression: the high-confidence remainder must still be kept."""
    labels = [
        _lv("a", "criteria provided, multiple submitters, no conflicts", source="clinvar_2star_concordant"),
        _lv("b", "reviewed by expert panel", source="clingen_vcep"),
        _lv("c", "practice guideline", source="clingen_vcep"),
    ]
    bm = build_benchmark(labels, make_eval_config(labels_snapshot="s1"))
    assert {r.variant_id for r in bm} == {"a", "b", "c"}


def test_source_hierarchy_expert_and_curated_outrank_default_clinvar():
    """Expert adjudication and curated literature must OUTRANK a default ClinVar label for
    the same variant -- the hierarchy must not be inverted."""
    for higher in ("oracle_adjudication", "curated_literature", "clingen_vcep"):
        labels = [
            _lv("v", "reviewed", label="B", source="clinvar"),
            _lv("v", "reviewed", label="P", source=higher),
        ]
        bm = build_benchmark(labels, make_eval_config(labels_snapshot="s1"))
        assert len(bm) == 1, f"{higher} vs clinvar should dedup to one row"
        assert bm[0].source == higher, f"{higher} must outrank default clinvar"
        assert bm[0].label == "P"
