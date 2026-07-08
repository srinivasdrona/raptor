import pytest
from raptor.scorer.config import load_config
import yaml

def test_ac7_config_validation(tmp_path):
    config_data = {
        "bias_version": "1.0.0",
        "bias_data_version": "2015",
        "included_criteria": ["PVS1", "PM2"],
        "strength_map": {"1": "supporting"},
        "acmg_criteria": {
            "PVS1": {"direction": "pathogenic", "strength_vocab": ["stand_alone", "very_strong", "strong", "moderate", "supporting"]},
            "PM2": {"direction": "pathogenic", "strength_vocab": ["stand_alone", "very_strong", "strong", "moderate", "supporting"]},
        },
        "edge_cases": {},
        "genes": {"TSC2": "NM_000548.5"},
        "licensing": {
            "revel": "non-commercial",
            "cadd": "non-commercial"
        }
    }
    
    valid_path = tmp_path / "valid.yaml"
    with open(valid_path, "w") as f:
        yaml.dump(config_data, f)
        
    config = load_config(str(valid_path))
    assert config.bias_version == "1.0.0"
    assert "revel" in config.licensing
    
    invalid_data = dict(config_data)
    del invalid_data["bias_version"]
    invalid_path = tmp_path / "invalid.yaml"
    with open(invalid_path, "w") as f:
        yaml.dump(invalid_data, f)
        
    with pytest.raises(Exception):
        load_config(str(invalid_path))
        
    blank_data = dict(config_data)
    blank_data["bias_data_version"] = ""
    blank_path = tmp_path / "blank.yaml"
    with open(blank_path, "w") as f:
        yaml.dump(blank_data, f)
        
    with pytest.raises(Exception):
        load_config(str(blank_path))
