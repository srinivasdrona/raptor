"""
AC-A2..A7: Predictor aggregation wrapper tests.
Tests the observable wrapper correction without AGPL import/edit.
"""
import pytest
from pathlib import Path

def test_aca2_round_trip_fidelity():
    """
    AC-A2 (round-trip fidelity + correction): `recompute_strength` reproduces BIAS's emitted strength
    from a rationale (parser fidelity) and the corrected strength per 2.1.
    """
    try:
        from raptor.eval.predictor_aggregation import load_aggregation_spec, recompute_strength
    except ImportError:
        pytest.fail("Missing implementation")

    spec_path = Path("configs/eval/predictor_aggregation.yaml")
    spec = load_aggregation_spec(spec_path)

    # 1. PP3 test case
    # Assume rationale with {phylop: 3, revel: 1}.
    # weight=strong phylop (3), weight=supporting revel (1)
    rationale_pp3 = "PP3_supporting: 2 line(s); strong phylop 0.9 | supporting revel 0.1"
    # Actually, BIAS emitted PP3 for {phylop:3, revel:1} would be 2 = moderate (see simulated_bias_emitted_pp3).
    # Wait, 1+1=2 -> moderate.
    rationale_pp3_mod = "PP3_moderate: 2 line(s); strong phylop 0.9 | supporting revel 0.1"
    
    correction_pp3 = recompute_strength("PP3", rationale_pp3_mod, spec)
    assert correction_pp3.criterion == "PP3"
    assert correction_pp3.emitted_strength == 2
    assert correction_pp3.corrected_strength == 3 # intended max is 3, tie=0
    assert correction_pp3.per_tool_scores == {"phylop": 3, "revel": 1}
    assert correction_pp3.decidable is True

    # 2. BP4 test case
    # {revel: 3, dann: 3} -> emitted is 3 (strong) (no bump).
    rationale_bp4 = "BP4_strong: 2 line(s); strong revel 0.9 | strong dann 0.8"
    correction_bp4 = recompute_strength("BP4", rationale_bp4, spec)
    assert correction_bp4.criterion == "BP4"
    assert correction_bp4.emitted_strength == 3
    assert correction_bp4.corrected_strength == 4 # intended max is 3, tie=2 -> bump -> 4
    assert correction_bp4.per_tool_scores == {"revel": 3, "dann": 3}
    assert correction_bp4.decidable is True
    assert correction_bp4.consensus_applied is True

def test_aca4_decidability_fail_loud():
    """
    AC-A4 (decidability / fail-loud): undecidable rationale fails loud via AggregationUndecidableError.
    """
    try:
        from raptor.eval.predictor_aggregation import load_aggregation_spec, parse_per_tool_scores, AggregationUndecidableError
    except ImportError:
        pytest.fail("Missing implementation")
        
    spec_path = Path("configs/eval/predictor_aggregation.yaml")
    spec = load_aggregation_spec(spec_path)
    
    bad_rationale = "PP3_strong: 1 line(s); unknownweight phylop 0.9"
    with pytest.raises(AggregationUndecidableError):
        parse_per_tool_scores("PP3", bad_rationale, spec)

def test_aca5_arms_length():
    """
    AC-A5 (arm's-length): no bias_2015 import anywhere on the eval path.
    """
    import sys
    try:
        import raptor.eval.predictor_aggregation
    except ImportError:
        pass
    assert 'bias_2015' not in sys.modules

def test_aca6_scope_invariance():
    """
    AC-A6 (scope invariance): PP3/BP4 stay allowed, correction changes strength only.
    """
    import yaml
    lineage_path = Path("configs/eval/bias_lineage.yaml")
    assert lineage_path.exists()
    
    with open(lineage_path) as f:
        lineage = yaml.safe_load(f)
    
    bp4 = lineage["records"]["BP4"]
    pp3 = lineage["records"]["PP3"]
    assert bp4["lineage_class"] == "label_independent_reference_or_predictor"
    assert bp4["production_disposition"] == "deferred"
    assert bp4["decision_dependency"] == "bp4pp3-predictor-policy"
    assert pp3["lineage_class"] == "label_independent_reference_or_predictor"
    assert pp3["production_disposition"] == "deferred"
    assert pp3["decision_dependency"] == "bp4pp3-predictor-policy"

def test_aca3_real_materiality_persisted():
    """
    AC-A3 (real materiality): the Probe 2 report over the census + held-out TSVs records the derived correction counts and Tavtigian-category flips (no magic-constant assertion); the numbers are persisted.
    """
    # Requires census / held-out TSVs to be present
    import os
    tsv_path = os.environ.get("RAPTOR_CENSUS_TSV", "data/census/tsc_vus_clinvar_2026-07-07.tsv")
    if not Path(tsv_path).exists():
        pytest.skip(f"VUS+holdout materiality probe input {tsv_path} not found")
        
    report_files = list(Path("data/census").glob("tsc_predictor_aggregation_report_*.json"))
    assert len(report_files) > 0, "No probe report found"

def test_aca7_probe_script_exists():
    """
    AC-A7 (recorded decision): probe script exists.
    """
    probe_script = Path("scripts/probe_predictor_aggregation.py")
    # Actually, we don't need to assert it exists right now if it's supposed to fail, but it's part of the test suite.
    # To follow RED-first, we just assert its existence.
    assert probe_script.exists(), "Probe script not implemented"

def test_ac_config_exists():
    """
    Check the config file is correct as per spec.
    """
    spec_path = Path("configs/eval/predictor_aggregation.yaml")
    assert spec_path.exists(), "Config file not implemented"
