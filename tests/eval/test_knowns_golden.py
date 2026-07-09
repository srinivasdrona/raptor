"""Golden-corpus conformance for the ClinVar knowns loader (kit-golden-corpus).

Drives `map_clinical_significance`, `classify_variant`, the gene filter, and the
`build_benchmark` exclusion policy from the FROZEN, CITABLE golden fixture
(`tests/fixtures/clinvar_hgvs_golden.yaml`) instead of a handful of hand-picked
cases. The fixture is an INDEPENDENT oracle derived from NCBI GTR/ClinVar +
HGVS specs (see `docs/reference/clinvar-hgvs-golden-corpus.md`), never from the
implementation under test.

Governance decisions under test (ACMG/AMP 2015 five-tier standard only):
  * risk-allele terms are off the Mendelian axis -> NON_SCOREABLE, and are
    INCLUDED here as inputs but EXCLUDED from the scored benchmark;
  * VUS sub-tiers normalize to the standard `VUS` term, then excluded from the
    scored set like any VUS.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from raptor.eval.knowns import map_clinical_significance, classify_variant, _matched_target_gene
from raptor.eval.benchmark import build_benchmark
from raptor.eval.model import LabeledVariant
from conftest import make_eval_config

_GOLDEN = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "fixtures" / "clinvar_hgvs_golden.yaml").read_text(encoding="utf-8")
)

_SCOREABLE = {"P", "LP", "LB", "B"}


# ---------------------------------------------------------------------------
# AC1 — ClinicalSignificance -> label, over the FULL real vocabulary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", _GOLDEN["label_map"], ids=lambda c: c["sig"])
def test_golden_label_map(case):
    assert map_clinical_significance(case["sig"]) == case["expected"], (
        f"ClinicalSignificance {case['sig']!r} must map to {case['expected']!r}"
    )


# ---------------------------------------------------------------------------
# AC2 — HGVS Name -> variant_class, over the full HGVS pitfall set
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", _GOLDEN["variant_class"], ids=lambda c: c["name"])
def test_golden_variant_class(case):
    assert classify_variant(case["name"]) == case["expected"], (
        f"Name {case['name']!r} must classify as {case['expected']!r}"
    )


def test_golden_never_false_missense():
    """C1 backstop over the golden set: no non-substitution token is ever `missense`."""
    for case in _GOLDEN["variant_class"]:
        if case["expected"] != "missense":
            assert classify_variant(case["name"]) != "missense", (
                f"{case['name']!r} (expected {case['expected']!r}) must never be missense"
            )


# ---------------------------------------------------------------------------
# Gene filter — multi-gene / subset forms
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", _GOLDEN["gene_symbol"], ids=lambda c: c["field"] or "<empty>")
def test_golden_gene_filter(case):
    assert _matched_target_gene(case["field"]) == case["matches"]


# ---------------------------------------------------------------------------
# ReviewStatus -> KEEP/EXCLUDE via the REAL build_benchmark (count held constant)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", _GOLDEN["review_status"], ids=lambda c: c["status"])
def test_golden_review_status_policy(case):
    lv = LabeledVariant("v", "P", case["status"], 3, "clinvar", "s1", False, "missense")
    kept = build_benchmark([lv], make_eval_config(labels_snapshot="s1"))
    if case["expected"] == "KEEP":
        assert [r.variant_id for r in kept] == ["v"], f"{case['status']!r} must be KEPT"
    else:
        assert kept == [], f"{case['status']!r} must be EXCLUDED"


# ---------------------------------------------------------------------------
# Governance: risk-allele + VUS terms are INCLUDED as inputs, EXCLUDED as scored
# ---------------------------------------------------------------------------
def test_risk_allele_and_vus_included_as_input_excluded_as_scored():
    """Every risk-allele / VUS(-subtier) string from the golden set flows through the
    loader's label map (included as an input) and is then EXCLUDED from the scored
    truth set -- never assigned a P/LP/LB/B ground-truth label (no new class invented)."""
    off_axis_sigs = [
        c["sig"] for c in _GOLDEN["label_map"]
        if ("risk" in c["sig"].lower()) or c["sig"].startswith("VUS-") or c["expected"] == "VUS"
    ]
    assert off_axis_sigs, "fixture must contain risk-allele / VUS terms as inputs"

    rows = []
    for i, sig in enumerate(off_axis_sigs):
        label = map_clinical_significance(sig)                 # included: exercised by the loader
        assert label not in _SCOREABLE, f"{sig!r} must never map to a scoreable class ({label!r})"
        rows.append(LabeledVariant(f"v{i}", label, "reviewed by expert panel", 3,
                                   "clingen_vcep", "s1", False, "missense"))

    bm = build_benchmark(rows, make_eval_config(labels_snapshot="s1"))
    assert bm == [], "risk-allele / VUS rows must be EXCLUDED from the scored benchmark"
