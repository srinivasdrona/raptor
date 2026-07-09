"""PRD-07 checker round-1 findings (planner-authored, spec-correct invariants).

2 blockers + 4 majors:
  BLOCKER-1  H1 leak: the ClinVar LABEL (ClinicalSignificance) travelled into the
             `RawVariant.raw_source_value` handed to `normalizer.normalize()` -- the
             scorer-side identity path must NEVER see a label. The RawVariant built for
             normalization must be label-free.
  BLOCKER-2  the real ClinVar snapshot is gzipped (`variant_summary.txt.gz`); the loader
             opened it as plain UTF-8 text -> must transparently read `.gz`.
  MAJOR-1    real ClinVar aggregate strings were missing: `Pathogenic, low penetrance`,
             `Likely pathogenic, low penetrance`, and the NEWER conflicting spelling
             `Conflicting classifications of pathogenicity` -> silently NON_SCOREABLE.
  MAJOR-2    protein parsing: single-letter `p.R611Q` missense mislabelled `other`
             (drops real missense from the R-A2c gated stratum); stop-loss extension
             (`ext`) mislabelled `truncating`.
  MAJOR-3    `benchmark._SOURCE_RANK` ties `clinvar_2star_concordant` with default
             `clinvar` -> a low-quality submission can win a dedup by order.
  MAJOR-4    multi-gene rows `"subset of N genes: TSC1:PKD1"` leave a leading-space
             `" TSC1"` token -> TSC1 silently dropped.
"""
from __future__ import annotations

import pytest

from raptor.eval.knowns import (
    map_clinical_significance,
    classify_variant,
    LabeledVariantReader,
    load_known_labels,
)
from raptor.eval.model import LabeledVariant
from raptor.eval.benchmark import build_benchmark
from raptor.ingest.model import NormalizedVariant, VariantClass
from conftest import make_eval_config
from _knowns_fixtures import write_variant_summary, write_variant_summary_gz, FakeNormalizer


def _norm(variation_id: str, variant_id: str) -> NormalizedVariant:
    return NormalizedVariant(
        variant_id=variant_id, hgvs_g=None, hgvs_c=None, hgvs_p=None,
        hgvs_c_null_reason=None, hgvs_p_null_reason=None, variant_class=VariantClass.SNV,
        gene="TSC1", variation_id=variation_id, snapshot_id="s", snapshot_date="d",
        source_file_checksum="", row_locator="1", raw_source_value="",
    )


def _snv_row(variation_id="1", gene="TSC1", sig="Pathogenic", review="criteria provided, single submitter",
             submitters="1", name="NM_1(TSC1):c.1A>G (p.Arg1Gln)"):
    return {
        "VariationID": variation_id, "GeneSymbol": gene, "ClinicalSignificance": sig,
        "ReviewStatus": review, "NumberSubmitters": submitters, "Name": name,
        "ChromosomeAccession": "NC_000009.12", "PositionVCF": "100",
        "ReferenceAlleleVCF": "A", "AlternateAlleleVCF": "G",
    }


# --------------------------------------------------------------------------
# [BLOCKER-1] the label must never reach the normalizer (H1/AC5)
# --------------------------------------------------------------------------
def test_label_never_reaches_normalizer(tmp_path):
    """The RawVariant handed to `normalizer.normalize()` must carry NO label -- the
    scorer-side identity path is structurally label-blind (H1). A distinctive
    ClinicalSignificance value must not appear in ANY field of the captured RawVariant."""
    label_value = "Pathogenic"
    fp = write_variant_summary(tmp_path, [_snv_row(sig=label_value)])
    fake = FakeNormalizer({"1": _norm("1", "vid")})
    config = make_eval_config(labels_snapshot="s1")

    list(LabeledVariantReader(fp, config, fake, snapshot_id="s1", snapshot_date="d"))

    assert fake.calls, "normalizer was never called"
    for raw in fake.calls:
        blob = "\t".join(
            str(getattr(raw, f)) for f in (
                "chromosome", "position", "ref", "alt", "gene", "variation_id",
                "snapshot_id", "snapshot_date", "source_file_checksum", "row_locator",
                "raw_source_value",
            )
        )
        assert label_value not in blob, f"label leaked into RawVariant given to normalizer: {raw!r}"


# --------------------------------------------------------------------------
# [BLOCKER-2] the real ClinVar snapshot is gzipped
# --------------------------------------------------------------------------
def test_reads_gzipped_variant_summary(tmp_path):
    """The real ClinVar `variant_summary.txt.gz` is gzipped -- the loader must read it."""
    fp = write_variant_summary_gz(tmp_path, [_snv_row()])
    fake = FakeNormalizer({"1": _norm("1", "vid")})
    labels = load_known_labels(fp, make_eval_config(labels_snapshot="s1"), fake)
    assert [l.variant_id for l in labels] == ["vid"]


# --------------------------------------------------------------------------
# [MAJOR-1] missing real ClinVar aggregate strings
# --------------------------------------------------------------------------
def test_label_map_low_penetrance_and_new_conflicting_spelling():
    assert map_clinical_significance("Pathogenic, low penetrance") == "P"
    assert map_clinical_significance("Likely pathogenic, low penetrance") == "LP"
    # newer ClinVar spelling (2023+) alongside the older one
    assert map_clinical_significance("Conflicting classifications of pathogenicity") == "Conflicting"
    assert map_clinical_significance("Conflicting interpretations of pathogenicity") == "Conflicting"


# --------------------------------------------------------------------------
# [MAJOR-2] protein parsing: single-letter missense + stop-loss extension
# --------------------------------------------------------------------------
def test_classify_single_letter_missense():
    """ClinVar mostly uses 3-letter p., but a single-letter substitution is still a
    missense -- it must NOT be dropped from the R-A2c-gated missense stratum."""
    assert classify_variant("NM_1(TSC1):c.1A>G (p.R611Q)") == "missense"


def test_classify_stop_loss_extension_is_not_truncating():
    """A stop-loss EXTENSION (`ext`) makes a LONGER protein -- it is not a truncating
    (nonsense/frameshift) change, so it must not be counted as `truncating`."""
    assert classify_variant("NM_1(TSC1):c.1A>G (p.Ter1808ArgextTer3)") == "other"


# --------------------------------------------------------------------------
# [MAJOR-3] source hierarchy: 2-star must outrank default clinvar
# --------------------------------------------------------------------------
def test_source_hierarchy_2star_outranks_default_clinvar():
    """A ClinVar 2-star concordant label must win the dedup over a plain/default clinvar
    label for the same variant -- higher-quality source wins, never tie-break by order."""
    # default clinvar listed FIRST, so an order-only tie-break would wrongly keep it.
    # (review status is a KEPT one -- not single-submitter/conflicting -- so the test
    # exercises the SOURCE-RANK tie-break, not an exclusion.)
    labels = [
        LabeledVariant("v", "B", "criteria provided, multiple submitters, no conflicts", 3, "clinvar", "s1", False, "missense"),
        LabeledVariant("v", "P", "criteria provided, multiple submitters, no conflicts", 3,
                       "clinvar_2star_concordant", "s1", False, "missense"),
    ]
    bm = build_benchmark(labels, make_eval_config(labels_snapshot="s1"))
    assert len(bm) == 1
    assert bm[0].source == "clinvar_2star_concordant"
    assert bm[0].label == "P"


# --------------------------------------------------------------------------
# [MAJOR-4] multi-gene rows must not silently drop a target gene
# --------------------------------------------------------------------------
def test_multigene_row_matches_target_gene(tmp_path):
    """`"subset of N genes: TSC1:PKD1"` must still match TSC1 (leading-space token must
    be stripped) -- a TSC1 variant must not be silently dropped."""
    row = _snv_row(variation_id="7", gene="subset of 2 genes: TSC1:PKD1")
    fp = write_variant_summary(tmp_path, [row])
    fake = FakeNormalizer({"7": _norm("7", "vid7")})
    labels = load_known_labels(fp, make_eval_config(labels_snapshot="s1"), fake)
    assert [l.variant_id for l in labels] == ["vid7"], "multi-gene TSC1 row was silently dropped"
