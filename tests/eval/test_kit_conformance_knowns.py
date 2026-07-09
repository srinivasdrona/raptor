import pytest
import hashlib
from raptor.testkit.invariants import (
    assert_determinism,
    assert_conservation,
    assert_fail_loud_propagates,
    assert_never_emits,
    assert_no_label_leak,
)
from raptor.eval.knowns import LabeledVariantReader, classify_variant
from raptor.ingest.model import NormalizedVariant, ManualQueueItem, VariantClass
from conftest import make_eval_config
from _knowns_fixtures import write_variant_summary, FakeNormalizer

def test_determinism(tmp_path):
    rows = [{"VariationID": "1", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic", "Name": "c.1A>G (p.Arg1Gln)"}]
    config = make_eval_config(clinvar_snapshot_file_checksum="")
    norm = NormalizedVariant(variant_id="vid", hgvs_g=None, hgvs_c=None, hgvs_p=None, hgvs_c_null_reason=None, hgvs_p_null_reason=None, variant_class=VariantClass.SNV, gene="TSC1", variation_id="1", snapshot_id="s", snapshot_date="d", source_file_checksum="c", row_locator="1", raw_source_value="")
    fake = FakeNormalizer({"1": norm})
    
    def run(items, store):
        fp = write_variant_summary(store, items)
        reader = LabeledVariantReader(fp, config, fake, snapshot_id="s", snapshot_date="d")
        return list(reader)
        
    def store_factory():
        import tempfile
        from pathlib import Path
        return Path(tempfile.mkdtemp(dir=tmp_path))
        
    def content_hash(report):
        return hashlib.sha256(repr(report).encode()).hexdigest()
        
    assert_determinism(run, rows, store_factory, content_hash)

def test_conservation(tmp_path):
    rows = [
        {"VariationID": "1", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic", "Name": "c.1A>G (p.Arg1Gln)"},
        {"VariationID": "2", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic", "Name": "c.1A>G"}
    ]
    config = make_eval_config(clinvar_snapshot_file_checksum="")
    norm1 = NormalizedVariant(variant_id="vid1", hgvs_g=None, hgvs_c=None, hgvs_p=None, hgvs_c_null_reason=None, hgvs_p_null_reason=None, variant_class=VariantClass.SNV, gene="TSC1", variation_id="1", snapshot_id="s", snapshot_date="d", source_file_checksum="c", row_locator="1", raw_source_value="")
    norm2 = ManualQueueItem(raw_input="", source_ref="2", failure_stage="x", error_code="y", reason="z", attempted_coords=None, tool_error=None, config_pins={}, run_id="", excluded_from_scorer=True)
    fake = FakeNormalizer({"1": norm1, "2": norm2})
    
    def run(items, store):
        fp = write_variant_summary(store, items)
        reader = LabeledVariantReader(fp, config, fake, snapshot_id="s", snapshot_date="d")
        emitted = list(reader)
        skipped = getattr(reader, "skipped", getattr(reader, "skipped_items", []))
        if not skipped and hasattr(reader, "skipped_count"):
            count = reader.skipped_count
        else:
            count = len(skipped)
        return {"emitted": emitted, "count": count}
        
    def store_factory():
        import tempfile
        from pathlib import Path
        return Path(tempfile.mkdtemp(dir=tmp_path))
        
    def count_accounted(report, store):
        return len(report["emitted"]) + report["count"]
        
    assert_conservation(run, rows, store_factory, count_accounted)

def test_fail_loud_propagation(tmp_path):
    config = make_eval_config(clinvar_snapshot_file_checksum="a" * 64)
    fake = FakeNormalizer({})
    
    def run(items, store):
        fp = store / "bad.txt"
        fp.write_text("Wrong\tHeader\n", encoding="utf-8")
        reader = LabeledVariantReader(fp, config, fake, snapshot_id="s", snapshot_date="d")
        list(reader)
        
    def store_factory():
        import tempfile
        from pathlib import Path
        return Path(tempfile.mkdtemp(dir=tmp_path))
        
    assert_fail_loud_propagates(run, [1], store_factory)

def test_grounding(tmp_path):
    rows = [{"VariationID": "1", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic", "Name": "c.1A>G (p.Arg1Gln)"}]
    file_path = write_variant_summary(tmp_path, rows)
    config = make_eval_config(clinvar_snapshot_file_checksum="")
    norm = NormalizedVariant(variant_id="canonical_spdi_123", hgvs_g=None, hgvs_c=None, hgvs_p=None, hgvs_c_null_reason=None, hgvs_p_null_reason=None, variant_class=VariantClass.SNV, gene="TSC1", variation_id="1", snapshot_id="s", snapshot_date="d", source_file_checksum="c", row_locator="1", raw_source_value="")
    fake = FakeNormalizer({"1": norm})
    
    reader = LabeledVariantReader(file_path, config, fake, snapshot_id="s", snapshot_date="d")
    emitted = list(reader)
    assert len(emitted) == 1
    assert emitted[0].variant_id == "canonical_spdi_123", "Grounding violated: emitted variant_id must be normalizer's real output"


# --- promoted kit invariants (catalog.yaml) ---------------------------------

#: A frozen adversarial corpus of NON-substitution ClinVar `Name` tokens (del/dup,
#: unknown aa, nonsense, frameshift, start-loss, stop-loss, extension, synonymous,
#: splice, delins). classify_variant must never call any of these "missense".
_C1_NON_MISSENSE_NAMES = [
    "NM_1(TSC1):c.1A>G (p.Arg611del)",
    "NM_1(TSC1):c.1A>G (p.Arg611dup)",
    "NM_1(TSC1):c.1A>G (p.Xaa123Gln)",
    "NM_1(TSC1):c.1A>G (p.Arg611Zzz)",
    "NM_1(TSC1):c.1A>G (p.Arg611Ter)",
    "NM_1(TSC1):c.1A>G (p.Gln1503*)",
    "NM_1(TSC1):c.1A>G (p.Ser1043fs)",
    "NM_1(TSC1):c.1A>G (p.Met1Val)",
    "NM_1(TSC1):c.1A>G (p.Ter1808Arg)",
    "NM_1(TSC1):c.1A>G (p.Ter1808ArgextTer3)",
    "NM_1(TSC1):c.1A>G (p.=)",
    "NM_1(TSC1):c.1832+1G>A",
    "NM_1(TSC1):c.1A>G (p.Arg611delinsGly)",
]


def test_c1_classify_never_false_missense():
    """C1 (strict-canonical-whitelist): classify_variant must NEVER return "missense" for a
    non-substitution token -- a permanent backstop for the PRD-07 r3/r6 false-missense class."""
    assert_never_emits(classify_variant, "missense", _C1_NON_MISSENSE_NAMES, label="knowns.classify_variant")


def test_c2_label_never_reaches_normalizer(tmp_path):
    """C2 (H1 anti-circularity): no ClinVar label value (ClinicalSignificance / ReviewStatus)
    may reach the normalizer (scorer-side identity path) -- backstop for the PRD-07 r1 leak."""
    rows = [{
        "VariationID": "1", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic",
        "ReviewStatus": "reviewed by expert panel", "NumberSubmitters": "3",
        "Name": "NM_1(TSC1):c.1A>G (p.Arg611Gln)", "ChromosomeAccession": "NC_000009.12",
        "PositionVCF": "100", "ReferenceAlleleVCF": "A", "AlternateAlleleVCF": "G",
    }]
    fp = write_variant_summary(tmp_path, rows)
    norm = NormalizedVariant(
        variant_id="vid", hgvs_g=None, hgvs_c=None, hgvs_p=None, hgvs_c_null_reason=None,
        hgvs_p_null_reason=None, variant_class=VariantClass.SNV, gene="TSC1", variation_id="1",
        snapshot_id="s", snapshot_date="d", source_file_checksum="", row_locator="1", raw_source_value="",
    )
    fake = FakeNormalizer({"1": norm})

    def run_capturing():
        reader = LabeledVariantReader(fp, make_eval_config(labels_snapshot="s1"), fake,
                                      snapshot_id="s1", snapshot_date="d")
        list(reader)
        return fake.calls  # the RawVariant objects handed to the normalizer

    assert_no_label_leak(run_capturing, ["Pathogenic", "reviewed by expert panel"],
                         label="knowns.LabeledVariantReader")
