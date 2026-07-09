import pytest
from raptor.eval.benchmark import build_benchmark
from raptor.eval.split import split_benchmark
from conftest import LabeledVariant

def test_ac2_build_benchmark_exclusions(valid_eval_config):
    variants = [
        # Should be included
        LabeledVariant("v1", "P", "reviewed", 2, "clinvar", "snap", False, "missense"),
        # Conflicting - EXCLUDE
        LabeledVariant("v2", "Conflicting", "reviewed", 5, "clinvar", "snap", False, "missense"),
        # Single submitter (< 2) - EXCLUDE
        LabeledVariant("v3", "LB", "reviewed", 1, "clinvar", "snap", False, "missense"),
        # Raptor influenced - EXCLUDE
        LabeledVariant("v4", "P", "reviewed", 3, "clinvar", "snap", True, "truncating")
    ]
    
    bm = build_benchmark(variants, valid_eval_config)
    
    assert len(bm) == 1
    assert bm[0].variant_id == "v1"

def test_ac2_split_no_leakage_and_determinism(valid_eval_config):
    variants = [
        LabeledVariant(f"v{i}", "P", "reviewed", 2, "clinvar", "snap", False, "missense") 
        for i in range(100)
    ]
    bm = build_benchmark(variants, valid_eval_config)

    # 1. Determinism
    train1, holdout1 = split_benchmark(bm, valid_eval_config)
    train2, holdout2 = split_benchmark(bm, valid_eval_config)
    
    assert [r.variant_id for r in train1] == [r.variant_id for r in train2]
    assert [r.variant_id for r in holdout1] == [r.variant_id for r in holdout2]

    # 2. No leakage
    train_ids = {r.variant_id for r in train1}
    holdout_ids = {r.variant_id for r in holdout1}
    
    assert len(train_ids) > 0
    assert len(holdout_ids) > 0
    assert train_ids.isdisjoint(holdout_ids), "Leakage detected: train and holdout intersect!"
