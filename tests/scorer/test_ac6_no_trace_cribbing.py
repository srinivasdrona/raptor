import pytest
from raptor.scorer.model import BiasRecord
from raptor.scorer.contract import BiasOutputContract
import dataclasses

def test_ac6_no_trace_cribbing():
    fields = {f.name for f in dataclasses.fields(BiasRecord)}
    forbidden = {"clinvar", "erepo", "benchmark", "label", "expert_panel"}
    for f in fields:
        for bad in forbidden:
            assert bad not in f.lower(), f"BiasRecord contains forbidden field: {f}"
            
    assert "acmg_classification" in fields
    
    contract = BiasOutputContract()
    header = ["chromosome", "position", "refAllele", "altAllele", "variantType", "consequence", 
              "acmgClassification", "alleleFreq", "hgvsg", "hgvsc", "hgvsp", "aaChange", 
              "geneName", "pubmedIds", "associatedDiseases", "dbSnpids", "transcript", "rationale"]
    contract.assert_columns(header)
