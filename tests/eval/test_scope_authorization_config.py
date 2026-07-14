import pytest
import yaml
from pathlib import Path
from raptor.eval.config import load_config, ConfigError


def make_valid_base_raw_config() -> dict:
    return {
        "automatable_criteria": ["PVS1", "PS3", "PM1", "PM2", "PP3", "BA1", "BS1", "BS2", "BP4", "BP7"],
        "tavtigian_points": {"supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8, "stand_alone": 8},
        "tavtigian_cutoffs": {"pathogenic_min": 10, "likely_pathogenic_min": 6, "vus_min": 0,
                              "vus_max": 5, "likely_benign_max": -1, "benign_max": -7},
        "min_count_per_class": 36,
        "split": {"seed": 42, "holdout_fraction": 0.3},
        "labels_snapshot": "clinvar_2026-07-01",
        "oracle_thresholds": {
            "confidence": 0.95,
            "strata": {
                "missense": {"precision": 0.90, "recall": 0.85, "gating": True, "directions": ["pathogenic", "benign"]},
                "truncating": {"precision": 0.95, "recall": 0.95, "gating": True, "directions": ["pathogenic"]}
            }
        }
    }


def test_c1_absent_block_loads_v1_compat(tmp_path):
    """C1 absent block loads (v1 compat):
    A valid tsc2-shaped YAML without `scope_authorization` -> load_config OK,
    EvalConfig.scope_authorization is None.
    """
    raw = make_valid_base_raw_config()
    p = tmp_path / "v1_config.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")

    cfg = load_config(p)
    assert cfg.scope_authorization is None


def test_c2_valid_block_parses(tmp_path):
    """C2 valid block parses:
    A valid config containing `scope_authorization` loads correctly.
    """
    raw = make_valid_base_raw_config()
    raw["scope_authorization"] = {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": ["truncating:pathogenic"]
            }
        },
        "governance_statements": {
            "FULL_SPECTRUM": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
            "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
            "NONE_VALIDATED": "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
        }
    }

    p = tmp_path / "v2_config.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")

    cfg = load_config(p)
    assert cfg.scope_authorization is not None
    assert cfg.scope_authorization["schema_version"] == 2
    assert cfg.scope_authorization["research_use_disclaimer"] == "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission."
    assert cfg.scope_authorization["full_spectrum"]["requires"] == ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]


@pytest.mark.parametrize(
    "invalid_scope",
    [
        "missense:orange",   # unknown direction
        "ghost:pathogenic",  # unknown stratum
        "truncating:benign"  # unregistered direction for truncating
    ]
)
def test_c3_unknown_scope_rejected(tmp_path, invalid_scope):
    """C3 unknown scope rejected:
    Any scope in full_spectrum.requires or research_scopes requires that is not a
    valid and registered stratum direction should be rejected with ConfigError.
    """
    raw = make_valid_base_raw_config()
    raw["scope_authorization"] = {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic", invalid_scope]
        },
        "research_scopes": {},
        "governance_statements": {
            "FULL_SPECTRUM": "FULL", "TRUNCATING_PATHOGENIC_ONLY": "TRUNC", "NONE_VALIDATED": "NONE"
        }
    }

    p = tmp_path / "invalid_scope.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(p)


def test_c4_full_spectrum_semantics_lock(tmp_path):
    """C4 full-spectrum semantics lock:
    full_spectrum.requires must equal exactly {"missense:pathogenic", "missense:benign", "truncating:pathogenic"}.
    If anything is missing or extra, a ConfigError must be raised (anti-cherry-pick).
    """
    # Try dropping "missense:benign"
    raw = make_valid_base_raw_config()
    raw["scope_authorization"] = {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {
            "requires": ["missense:pathogenic", "truncating:pathogenic"]
        },
        "research_scopes": {},
        "governance_statements": {
            "FULL_SPECTRUM": "FULL", "TRUNCATING_PATHOGENIC_ONLY": "TRUNC", "NONE_VALIDATED": "NONE"
        }
    }

    p = tmp_path / "deviated_fs_requires.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(p)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 3},
        {"schema_version": "1"},
        {"research_use_disclaimer": ""},  # missing/blank disclaimer
        {"research_use_disclaimer": "This is a weak statement"},  # not matching strict text (or let's assert blank/missing)
        {"governance_statements": {"FULL_SPECTRUM": ""}},  # blank statement
        {"governance_statements": {"FULL_SPECTRUM": "FULL", "TRUNCATING_PATHOGENIC_ONLY": "TRUNC"}}  # missing state
    ]
)
def test_c5_missing_blank_or_invalid_fields_rejected(tmp_path, changes):
    """C5 missing/blank governance statement, missing/blank/invalid research_use_disclaimer,
    or bad schema_version must be rejected with ConfigError.
    """
    raw = make_valid_base_raw_config()
    scope_auth = {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": ["truncating:pathogenic"]
            }
        },
        "governance_statements": {
            "FULL_SPECTRUM": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
            "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
            "NONE_VALIDATED": "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
        }
    }

    # Apply changes
    for key, val in changes.items():
        if isinstance(val, dict) and key in scope_auth:
            scope_auth[key].update(val)
        else:
            scope_auth[key] = val

    raw["scope_authorization"] = scope_auth

    p = tmp_path / "invalid_fields.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(p)


@pytest.mark.parametrize(
    "invalid_requires",
    [
        ["missense:pathogenic"],  # wrong scope
        [],                       # empty
        ["truncating:pathogenic", "missense:pathogenic"],  # multiple/extras
        ["missense:pathogenic", "truncating:pathogenic"],  # reordered/extras
    ]
)
def test_c6_research_scope_flag_mapping_lock(tmp_path, invalid_requires):
    """Finding 1: Config loader must reject any mapping where
    truncating_pathogenic_research_scope_validated.requires is not exactly ["truncating:pathogenic"].
    """
    raw = make_valid_base_raw_config()
    raw["scope_authorization"] = {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": invalid_requires
            }
        },
        "governance_statements": {
            "FULL_SPECTRUM": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
            "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
            "NONE_VALIDATED": "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
        }
    }

    p = tmp_path / "invalid_flag_requires.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(p)


def test_c7_research_scope_keys_pinned(tmp_path):
    """Finding 1: The keys of research_scopes must be exactly pinned to
    {"truncating_pathogenic_research_scope_validated"}.
    Any missing or extra keys must be rejected by the config loader.
    """
    # Case A: Missing the required key (empty research_scopes)
    raw = make_valid_base_raw_config()
    raw["scope_authorization"] = {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]
        },
        "research_scopes": {},
        "governance_statements": {
            "FULL_SPECTRUM": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
            "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
            "NONE_VALIDATED": "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
        }
    }
    p = tmp_path / "missing_key.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)

    # Case B: Extra key in research_scopes
    raw["scope_authorization"]["research_scopes"] = {
        "truncating_pathogenic_research_scope_validated": {
            "requires": ["truncating:pathogenic"]
        },
        "extra_scope_unauthorized": {
            "requires": ["missense:pathogenic"]
        }
    }
    p = tmp_path / "extra_key.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


# =========================================================================
# RED REGRESSION TESTS FOR GPT-5.4 FINDINGS
# =========================================================================

def test_finding_1_config_load_rejects_governance_drift(tmp_path) -> None:
    """Finding 1 [High]: Pin all three governance state strings—not only
    TRUNCATING_PATHOGENIC_ONLY—because all are authorization surfaces. Any drift
    from the exact pinned governance statements must be rejected by the loader.
    """
    raw = make_valid_base_raw_config()
    
    # Case A: Drift in FULL_SPECTRUM statement
    scope_auth_a = {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {"requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]},
        "research_scopes": {"truncating_pathogenic_research_scope_validated": {"requires": ["truncating:pathogenic"]}},
        "governance_statements": {
            "FULL_SPECTRUM": "Tampered full-spectrum text is unauthorized.",
            "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
            "NONE_VALIDATED": "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
        }
    }
    raw["scope_authorization"] = scope_auth_a
    p = tmp_path / "drift_fs.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="governance_statements.*FULL_SPECTRUM"):
        load_config(p)

    # Case B: Drift in NONE_VALIDATED statement
    scope_auth_b = {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {"requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]},
        "research_scopes": {"truncating_pathogenic_research_scope_validated": {"requires": ["truncating:pathogenic"]}},
        "governance_statements": {
            "FULL_SPECTRUM": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
            "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
            "NONE_VALIDATED": "Tampered none-validated text is unauthorized."
        }
    }
    raw["scope_authorization"] = scope_auth_b
    p = tmp_path / "drift_none.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="governance_statements.*NONE_VALIDATED"):
        load_config(p)


def test_finding_2_config_load_rejects_min_count_drift(tmp_path) -> None:
    """Finding 2 [High]: The pre-registered floor is exactly 36. Any drift
    below or above 36 must be rejected by the loader (ConfigError).
    """
    for drifted_count in [1, 35, 37]:
        raw = make_valid_base_raw_config()
        raw["min_count_per_class"] = drifted_count
        raw["scope_authorization"] = {
            "schema_version": 2,
            "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
            "full_spectrum": {"requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]},
            "research_scopes": {"truncating_pathogenic_research_scope_validated": {"requires": ["truncating:pathogenic"]}},
            "governance_statements": {
                "FULL_SPECTRUM": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
                "NONE_VALIDATED": "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
            }
        }
        p = tmp_path / f"drift_min_count_{drifted_count}.yaml"
        p.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ConfigError, match="min_count_per_class"):
            load_config(p)


@pytest.mark.parametrize(
    "falsy_scope_auth",
    [{}, [], False, "", None]
)
def test_finding_5_falsy_scope_authorization_fails_loud(tmp_path, falsy_scope_auth) -> None:
    """Finding 5 [Medium]: Only key ABSENCE means legacy config. Present but falsy
    scope_authorization blocks (such as {}, [], false, "", or null) must fail loud.
    """
    raw = make_valid_base_raw_config()
    raw["scope_authorization"] = falsy_scope_auth
    p = tmp_path / "falsy_scope_auth.yaml"
    # To dump null for None, yaml does it naturally
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


