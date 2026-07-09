import pytest
from raptor.eval.checks import oracle_blind_checks

def test_ac8_oracle_blind_checks():
    # AC8: oracle_blind_checks flags inconsistent criteria combinations (without labels)
    evidence = {
        # BA1 (stand alone benign) + PVS1 (very strong pathogenic) is a glaring contradiction
        "v1": [("BA1", "stand_alone", "benign"), ("PVS1", "very_strong", "pathogenic")]
    }
    
    flags = oracle_blind_checks(evidence)
    
    # We assert that at least one flag is returned
    assert len(flags) > 0, "Expected an inconsistency flag for BA1 + PVS1"
    
    # We assert that the flag describes the conflict involving BA1 and PVS1
    assert "BA1" in flags[0] and "PVS1" in flags[0], "Flag must specify the conflicting criteria"
