import pytest
from raptor.eval.knowns import LabeledVariantReader
from raptor.ingest.model import NormalizedVariant, ManualQueueItem, VariantClass
from conftest import make_eval_config
from _knowns_fixtures import write_variant_summary, FakeNormalizer

def test_ac3_identity_join(tmp_path):
    rows = [
        {
            "VariationID": "123",
            "GeneSymbol": "TSC1",
            "Name": "NM_1(TSC1):c.1A>G (p.Arg1Gln)",
            "ClinicalSignificance": "Pathogenic",
            "ReviewStatus": "criteria provided, single submitter",
            "NumberSubmitters": "1",
            "ChromosomeAccession": "NC_000009.12",
            "PositionVCF": "100",
            "ReferenceAlleleVCF": "A",
            "AlternateAlleleVCF": "G",
        },
        {
            "VariationID": "456",
            "GeneSymbol": "TSC2",
            "Name": "imprecise",
            "ClinicalSignificance": "Pathogenic",
            "ReviewStatus": "criteria provided, single submitter",
            "NumberSubmitters": "1",
            "ChromosomeAccession": "NC_000016.10",
            "PositionVCF": "na",
            "ReferenceAlleleVCF": "A",
            "AlternateAlleleVCF": "G",
        }
    ]
    file_path = write_variant_summary(tmp_path, rows)
    
    norm1 = NormalizedVariant(
        variant_id="NC_000009.12:99:A:G",
        hgvs_g=None, hgvs_c=None, hgvs_p=None, hgvs_c_null_reason=None, hgvs_p_null_reason=None,
        variant_class=VariantClass.SNV, gene="TSC1", variation_id="123", snapshot_id="s1", snapshot_date="d1", source_file_checksum="chk", row_locator="1", raw_source_value=""
    )
    norm2 = ManualQueueItem(
        raw_input="", source_ref="456", failure_stage="classify", error_code="IMPRECISE", reason="imprecise", attempted_coords=None, tool_error=None, config_pins={}, run_id="", excluded_from_scorer=True
    )
    
    fake_normalizer = FakeNormalizer({"123": norm1, "456": norm2})
    config = make_eval_config(labels_snapshot="s1", clinvar_snapshot_file_checksum="")
    
    reader = LabeledVariantReader(file_path, config, fake_normalizer, snapshot_id="s1", snapshot_date="d1")
    variants = list(reader)
    
    assert len(variants) == 1
    assert variants[0].variant_id == "NC_000009.12:99:A:G"
    
    # Assert missing surfaced (imprecise)
    skipped = getattr(reader, "skipped", getattr(reader, "skipped_items", []))
    if not skipped and hasattr(reader, "skipped_count"):
        count = reader.skipped_count
    else:
        count = len(skipped)
    assert count >= 1
