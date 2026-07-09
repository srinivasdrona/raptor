import pytest
from raptor.eval.knowns import load_known_labels
from raptor.ingest.model import NormalizedVariant, VariantClass
from conftest import make_eval_config
from _knowns_fixtures import write_variant_summary, FakeNormalizer

def test_ac7_determinism_provenance(tmp_path):
    rows = [{"VariationID": "1", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic", "ReviewStatus": "criteria provided, single submitter", "NumberSubmitters": "1"}]
    file_path = write_variant_summary(tmp_path, rows)
    
    norm = NormalizedVariant(
        variant_id="vid", hgvs_g=None, hgvs_c=None, hgvs_p=None, hgvs_c_null_reason=None, hgvs_p_null_reason=None,
        variant_class=VariantClass.SNV, gene="TSC1", variation_id="1", snapshot_id="s", snapshot_date="d", source_file_checksum="c", row_locator="1", raw_source_value=""
    )
    fake = FakeNormalizer({"1": norm})
    config = make_eval_config(labels_snapshot="s1", clinvar_snapshot_file_checksum="")
    
    labels1 = load_known_labels(file_path, config, fake)
    labels2 = load_known_labels(file_path, config, fake)
    
    # Determinism: object equality (lists match)
    assert labels1 == labels2
    assert len(labels1) == 1
    
    # Provenance
    assert labels1[0].snapshot == "s1"
    assert labels1[0].source == "clinvar"
    assert labels1[0].raptor_influenced is False
