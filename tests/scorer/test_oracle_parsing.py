import pytest
import json
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.parse import parse_rationale

def test_oracle_parsing(fixtures_dir):
    tsv_path = fixtures_dir / "bias_output_slice.tsv"
    json_path = fixtures_dir / "expected_evidence.json"
    
    with open(json_path) as f:
        expected = json.load(f)
        
    source = BiasTsvSource(str(tsv_path))
    records = list(source.records())
    
    assert len(records) >= len(expected), "Should have enough parsed records"
    
    strength_map = {"1": "supporting", "2": "moderate", "3": "strong", "4": "very_strong", "5": "stand_alone"}
    
    for i, exp_item in enumerate(expected):
        rec = records[i]
        derived_id = f"{rec.chromosome}:{rec.position}:{rec.ref_allele}:{rec.alt_allele}"
        assert derived_id == exp_item["variant_id"]
        
        calls = parse_rationale(rec.criteria, strength_map)
        expected_evidence = exp_item["evidence"]
        
        assert len(calls) == len(expected_evidence), f"Record {derived_id} fired criteria count mismatch"
        
        actual_evidence = []
        for call in calls:
            actual_evidence.append({
                "criterion": call.criterion,
                "strength": call.strength,
                "direction": call.direction
            })
            
        actual_evidence.sort(key=lambda x: x["criterion"])
        expected_evidence_sorted = sorted(expected_evidence, key=lambda x: x["criterion"])
        
        assert actual_evidence == expected_evidence_sorted, f"Mismatch on {derived_id}"
