import pytest
from raptor.eval.knowns import map_clinical_significance
from conftest import make_eval_config

def test_ac1_label_map():
    config = make_eval_config()
    
    assert map_clinical_significance("Pathogenic", config) == "P"
    assert map_clinical_significance("Likely pathogenic", config) == "LP"
    assert map_clinical_significance("Likely benign", config) == "LB"
    assert map_clinical_significance("Benign", config) == "B"
    assert map_clinical_significance("Pathogenic/Likely pathogenic", config) == "P"
    assert map_clinical_significance("Benign/Likely benign", config) == "B"
    assert map_clinical_significance("Uncertain significance", config) == "VUS"
    assert map_clinical_significance("Conflicting interpretations of pathogenicity", config) == "Conflicting"
    
    scoreable = {"P", "LP", "LB", "B"}
    
    # Non-scoreables
    res1 = map_clinical_significance("drug response", config)
    assert res1 not in scoreable
    assert res1 != "VUS"
    assert res1 != "Conflicting"
    
    res2 = map_clinical_significance("not provided", config)
    assert res2 not in scoreable
    
    res3 = map_clinical_significance("risk factor", config)
    assert res3 not in scoreable
