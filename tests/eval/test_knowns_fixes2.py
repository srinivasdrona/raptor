"""PRD-07 checker round-2 findings (planner-authored, spec-correct invariants).

2 majors + 2 minors (no blockers):
  MAJOR-1  low-penetrance aggregate COMBOS still drop
           (`"Pathogenic/Likely pathogenic, low penetrance"` -> NON_SCOREABLE); the map
           must normalize the `, low penetrance` modifier and re-map the base term.
  MAJOR-2  the protein parser still corrupts the R-A2c MISSENSE stratum:
             * `p.Met1Val` (start-loss) is FALSE-missense;
             * `p.Ter1808Arg` (stop-loss: Ter as the REF) is FALSE-truncating;
             * `p.(Arg611Gln)` (predicted, inner parens) is MISSED-missense.
           The Ter/* marker means TRUNCATING only when it is the ALT (aa -> Ter), never
           when it is the REF (Ter -> aa = stop-loss).
  MINOR-1  exact ClinSig matching is brittle -- `"Pathogenic "` / case drift -> drop;
           `strip()` + case-insensitive lookup.
  MINOR-2  the reader does not expose the actual source-file checksum for audit.

PLANNER NOTE (adversarial): the round-2 checker also flagged single-aa `delins`
(`p.Arg611delinsGln`) as "missed-missense". DECLINED: the R-A2c missense stratum is for
simple aa SUBSTITUTIONS (the distribution-shift concern); a delins is a distinct variant
class. Leaving it in `other` (not the gated stratum) is the conservative, safer choice --
a false-missense corrupts the gate; a missed borderline does not.
"""
from __future__ import annotations

import hashlib

import pytest

from raptor.eval.knowns import map_clinical_significance, classify_variant, LabeledVariantReader
from raptor.ingest.model import NormalizedVariant, VariantClass
from conftest import make_eval_config
from _knowns_fixtures import write_variant_summary, FakeNormalizer


def _norm(variation_id: str, variant_id: str) -> NormalizedVariant:
    return NormalizedVariant(
        variant_id=variant_id, hgvs_g=None, hgvs_c=None, hgvs_p=None,
        hgvs_c_null_reason=None, hgvs_p_null_reason=None, variant_class=VariantClass.SNV,
        gene="TSC1", variation_id=variation_id, snapshot_id="s", snapshot_date="d",
        source_file_checksum="", row_locator="1", raw_source_value="",
    )


def _row(sig="Pathogenic"):
    return {
        "VariationID": "1", "GeneSymbol": "TSC1", "ClinicalSignificance": sig,
        "ReviewStatus": "criteria provided, single submitter", "NumberSubmitters": "1",
        "Name": "NM_1(TSC1):c.1A>G (p.Arg1Gln)", "ChromosomeAccession": "NC_000009.12",
        "PositionVCF": "100", "ReferenceAlleleVCF": "A", "AlternateAlleleVCF": "G",
    }


# --------------------------------------------------------------------------
# [MAJOR-1] low-penetrance aggregate combos must map to their base class
# --------------------------------------------------------------------------
def test_label_map_low_penetrance_combo():
    assert map_clinical_significance("Pathogenic/Likely pathogenic, low penetrance") == "P"
    # base low-penetrance still works (regression from round 1)
    assert map_clinical_significance("Pathogenic, low penetrance") == "P"
    assert map_clinical_significance("Likely pathogenic, low penetrance") == "LP"


# --------------------------------------------------------------------------
# [MINOR-1] exact ClinSig matching must be whitespace/case robust
# --------------------------------------------------------------------------
def test_label_map_strip_and_case_insensitive():
    assert map_clinical_significance("Pathogenic ") == "P"           # trailing space
    assert map_clinical_significance("  Benign") == "B"              # leading space
    assert map_clinical_significance("likely pathogenic") == "LP"    # case drift
    assert map_clinical_significance("UNCERTAIN SIGNIFICANCE") == "VUS"


# --------------------------------------------------------------------------
# [MAJOR-2] protein parser must not corrupt the missense stratum
# --------------------------------------------------------------------------
def test_classify_start_loss_is_not_missense():
    """`p.Met1Val` changes the initiator Met (start codon) -> start-loss (LoF), NOT a
    missense; it must never enter the R-A2c-gated missense stratum."""
    assert classify_variant("NM_1(TSC1):c.1A>G (p.Met1Val)") == "other"
    assert classify_variant("NM_1(TSC1):c.1A>G (p.M1V)") == "other"


def test_classify_stop_loss_substitution_is_not_truncating():
    """`p.Ter1808Arg` changes the STOP codon (Ter) to an aa -> stop-loss, NOT a
    truncating (nonsense) change. Ter/* is truncating only as the ALT, never the REF."""
    assert classify_variant("NM_1(TSC1):c.1A>G (p.Ter1808Arg)") == "other"
    assert classify_variant("NM_1(TSC1):c.1A>G (p.*1808Arg)") == "other"


def test_classify_inner_parens_missense():
    """A predicted consequence `p.(Arg611Gln)` (inner parens) is still a missense."""
    assert classify_variant("NM_1(TSC1):c.1A>G (p.(Arg611Gln))") == "missense"


def test_classify_nonsense_still_truncating():
    """Regression: a genuine nonsense (aa -> Ter/*) stays truncating."""
    assert classify_variant("NM_1(TSC1):c.1A>G (p.Arg611Ter)") == "truncating"
    assert classify_variant("NM_1(TSC1):c.1A>G (p.Gln1503*)") == "truncating"


# --------------------------------------------------------------------------
# [MINOR-2] the reader must expose the actual source-file checksum (audit)
# --------------------------------------------------------------------------
def test_reader_exposes_source_file_checksum(tmp_path):
    """Auditability: the reader exposes the real sha256 of the file it read, so a frozen
    benchmark's exact source file is recoverable even when no pin was supplied."""
    fp = write_variant_summary(tmp_path, [_row()])
    reader = LabeledVariantReader(fp, make_eval_config(labels_snapshot="s1"), FakeNormalizer({"1": _norm("1", "vid")}))
    list(reader)
    expected = hashlib.sha256(fp.read_bytes()).hexdigest()
    assert reader.source_file_checksum == expected
