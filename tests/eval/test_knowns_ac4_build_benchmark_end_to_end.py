import pytest
from raptor.eval.knowns import load_known_labels
from raptor.eval.benchmark import build_benchmark
from raptor.ingest.model import NormalizedVariant, VariantClass
from conftest import make_eval_config
from _knowns_fixtures import write_variant_summary, FakeNormalizer

def test_ac4_build_benchmark_exclusions_and_hierarchy(tmp_path):
    rows = [
        # 1: conflicting
        {"VariationID": "v1", "GeneSymbol": "TSC1", "ClinicalSignificance": "Conflicting interpretations of pathogenicity", "ReviewStatus": "criteria provided, multiple submitters, no conflicts", "NumberSubmitters": "2"},
        # 2: single submitter
        {"VariationID": "v2", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic", "ReviewStatus": "criteria provided, single submitter", "NumberSubmitters": "1"},
        # 3: non-scoreable
        {"VariationID": "v3", "GeneSymbol": "TSC1", "ClinicalSignificance": "drug response", "ReviewStatus": "reviewed by expert panel", "NumberSubmitters": "2"},
        # 4: conflicting review status
        {"VariationID": "v4", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic", "ReviewStatus": "criteria provided, conflicting interpretations", "NumberSubmitters": "2"},
        # 5: kept
        {"VariationID": "v5", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic", "ReviewStatus": "criteria provided, multiple submitters, no conflicts", "NumberSubmitters": "2"},
        # 6: duplicate hierarchy (lower rank)
        {"VariationID": "v6_clinvar", "GeneSymbol": "TSC1", "ClinicalSignificance": "Benign", "ReviewStatus": "criteria provided, multiple submitters, no conflicts", "NumberSubmitters": "2"},
        # 7: duplicate hierarchy (higher rank) -> should win
        {"VariationID": "v6_clingen", "GeneSymbol": "TSC1", "ClinicalSignificance": "Pathogenic", "ReviewStatus": "reviewed by expert panel", "NumberSubmitters": "2"},
    ]
    file_path = write_variant_summary(tmp_path, rows)
    
    mapping = {}
    for r in rows:
        vid = "dup_id" if r["VariationID"].startswith("v6") else f"id_{r['VariationID']}"
        mapping[r["VariationID"]] = NormalizedVariant(
            variant_id=vid, hgvs_g=None, hgvs_c=None, hgvs_p=None, hgvs_c_null_reason=None, hgvs_p_null_reason=None,
            variant_class=VariantClass.SNV, gene="TSC1", variation_id=r["VariationID"], snapshot_id="s1", snapshot_date="d1", source_file_checksum="", row_locator="1", raw_source_value=""
        )
    
    fake = FakeNormalizer(mapping)
    config = make_eval_config(labels_snapshot="s1", clinvar_snapshot_file_checksum="")
    
    labels = load_known_labels(file_path, config, fake)
    benchmark = build_benchmark(labels, config)
    
    kept_ids = [b.variant_id for b in benchmark]
    
    # Should exclude v1, v2, v3, v4
    assert "id_v1" not in kept_ids
    assert "id_v2" not in kept_ids
    assert "id_v3" not in kept_ids
    assert "id_v4" not in kept_ids
    
    # Should keep v5 and deduplicate dup_id
    assert "id_v5" in kept_ids
    assert "dup_id" in kept_ids
    assert len(kept_ids) == 2
    
    # Check deduplication chose higher rank (Pathogenic from v6_clingen over Benign from v6_clinvar)
    dup_row = next(b for b in benchmark if b.variant_id == "dup_id")
    assert dup_row.label == "P"
