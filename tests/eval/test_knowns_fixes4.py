"""PRD-07 checker round-4 finding (planner-authored, spec-correct invariant).

1 MAJOR: `benchmark._excluded` keyed single-submitter exclusion on
`submitter_count < 2` only. But a ClinVar 1-star `"criteria provided, single submitter"`
record can carry `NumberSubmitters >= 2` (extra submissions WITHOUT assertion criteria
inflate the count while the germline review stays single-submitter). Such a low-confidence
1-star label must NOT enter the truth set -- exclusion must key on the REVIEW STATUS
(`"single submitter"`, case-insensitive), not only the raw submitter count.
"""
from __future__ import annotations

from raptor.eval.model import LabeledVariant
from raptor.eval.benchmark import build_benchmark
from conftest import make_eval_config


def _lv(vid, review, submitters=3, label="P", source="clinvar"):
    return LabeledVariant(vid, label, review, submitters, source, "s1", False, "missense")


def test_single_submitter_review_status_excluded_even_when_count_high():
    """A 1-star 'criteria provided, single submitter' label with NumberSubmitters>1 must
    be excluded (low confidence), while a genuine multi-submitter concordant label is kept."""
    labels = [
        _lv("keep", "criteria provided, multiple submitters, no conflicts",
            source="clinvar_2star_concordant"),
        _lv("drop_single", "criteria provided, single submitter", submitters=3),
        _lv("drop_single_caps", "Criteria provided, SINGLE SUBMITTER", submitters=5),
    ]
    bm = build_benchmark(labels, make_eval_config(labels_snapshot="s1"))
    assert {r.variant_id for r in bm} == {"keep"}, (
        "1-star single-submitter labels (NumberSubmitters>1) must be excluded by review status"
    )
