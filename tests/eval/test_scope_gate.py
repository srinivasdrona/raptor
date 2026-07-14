import pytest
from conftest import make_eval_config, Metrics, with_point_estimate_lb

# Real production modules/symbols are expected to be imported.
# Since they don't exist yet, we expect these imports to fail in the RED state.
from raptor.eval.scope_gate import decide_scope_gate
from raptor.eval.model import DirectionVerdict, ScopeGateDecision


def make_v2_auth_config() -> dict:
    """Build the valid scope_authorization config block."""
    return {
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


def make_oracle_thresholds() -> dict:
    return {
        "confidence": 0.95,
        "strata": {
            "missense": {
                "precision": 0.90,
                "recall": 0.85,
                "gating": True,
                "directions": ["pathogenic", "benign"]
            },
            "truncating": {
                "precision": 0.95,
                "recall": 0.95,
                "gating": True,
                "directions": ["pathogenic"]
            }
        }
    }


# ==============================================================================
# Group A — `decide_scope_gate` core
# ==============================================================================

def test_a1_no_short_circuit_all_scopes_present():
    """A1 no-short-circuit / all scopes present:
    Even when missense FAILs, truncating:pathogenic can independently VALIDATE.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    # Missense FAILs (LBs below threshold)
    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.75
    m_missense.recall_lb = 0.75
    m_missense.benign_precision_lb = 0.75
    m_missense.benign_recall_lb = 0.75

    # Truncating PASSes (LBs clear threshold, n powered)
    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}
    decision = decide_scope_gate(metrics, cfg)

    assert isinstance(decision, ScopeGateDecision)
    assert decision.schema_version == "2"
    
    # Assert all scopes present
    expected_scopes = {"missense:pathogenic", "missense:benign", "truncating:pathogenic", "truncating:benign"}
    assert expected_scopes.issubset(decision.scopes.keys())

    # Assert missense:pathogenic and missense:benign FAIL
    assert decision.scopes["missense:pathogenic"].scope_status == "FAIL"
    assert decision.scopes["missense:benign"].scope_status == "FAIL"

    # Assert truncating:pathogenic VALIDATED despite missense failing
    assert decision.scopes["truncating:pathogenic"].scope_status == "VALIDATED"


def test_a2_missense_two_axis_preserved():
    """A2 missense two-axis preserved:
    If a scope is both metric-UNMET and coverage-inadequate, both are recorded.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    # Missense lower bounds below threshold, and counts < min_count=36
    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 17, "benign_called": 34, "path_actual": 20, "benign_actual": 35},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.70
    m_missense.recall_lb = 0.70
    m_missense.benign_precision_lb = 0.70
    m_missense.benign_recall_lb = 0.70

    metrics = {"missense": m_missense}
    decision = decide_scope_gate(metrics, cfg)

    # missense:pathogenic axis check
    verdict_path = decision.scopes["missense:pathogenic"]
    assert verdict_path.metric_status == "UNMET"
    assert verdict_path.coverage_adequate is False
    assert verdict_path.scope_status == "FAIL"

    # missense:benign axis check
    verdict_benign = decision.scopes["missense:benign"]
    assert verdict_benign.metric_status == "UNMET"
    assert verdict_benign.coverage_adequate is False
    assert verdict_benign.scope_status == "FAIL"


def test_a3_truncating_benign_descriptive_no_invented_threshold():
    """A3 truncating:benign descriptive, no invented threshold:
    truncating has no benign threshold registered, benign count = 1.
    Should be DESCRIPTIVE and coverage_adequate=False, no threshold.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"truncating": m_truncating}
    decision = decide_scope_gate(metrics, cfg)

    verdict_benign = decision.scopes["truncating:benign"]
    assert verdict_benign.precision_threshold is None
    assert verdict_benign.recall_threshold is None
    assert verdict_benign.metric_status == "NO_THRESHOLD"
    assert verdict_benign.coverage_adequate is False
    assert verdict_benign.scope_status == "DESCRIPTIVE"


@pytest.mark.parametrize(
    "precision_lb, recall_lb, called_count, expected_status",
    [
        (0.96, 0.96, 40, "VALIDATED"),       # met, powered
        (0.96, 0.96, 35, "UNDERPOWERED"),    # met, underpowered
        (0.90, 0.96, 40, "FAIL"),            # unmet (precision < 0.95), powered
        (0.90, 0.96, 35, "FAIL"),            # unmet (precision < 0.95), underpowered
    ]
)
def test_a4_truncating_pathogenic_parametrized_fail_closed(precision_lb, recall_lb, called_count, expected_status):
    """A4 truncating:pathogenic parametrized fail-closed:
    Verifies that VALIDATED is ONLY reached when both met and powered.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": called_count, "benign_called": 1, "path_actual": called_count, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = precision_lb
    m_truncating.recall_lb = recall_lb
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"truncating": m_truncating}
    decision = decide_scope_gate(metrics, cfg)

    assert decision.scopes["truncating:pathogenic"].scope_status == expected_status


def test_a5_other_descriptive_only():
    """A5 other descriptive-only:
    Metrics includes `other` (no threshold). All directions must be DESCRIPTIVE.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_other = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 10, "benign_called": 10, "path_actual": 10, "benign_actual": 10},
        stratum="other", gating=False, benign_precision=1.0, benign_recall=1.0
    )
    m_other.precision_lb = 0.9
    m_other.recall_lb = 0.9
    m_other.benign_precision_lb = 0.9
    m_other.benign_recall_lb = 0.9

    metrics = {"other": m_other}
    decision = decide_scope_gate(metrics, cfg)

    assert decision.scopes["other:pathogenic"].scope_status == "DESCRIPTIVE"
    assert decision.scopes["other:benign"].scope_status == "DESCRIPTIVE"


def test_a6_full_spectrum_requires_all():
    """A6 full-spectrum requires all:
    - ALL three required scopes VALIDATED -> full_spectrum_vus_authorized=True, status="PASS"
    - If any of the required scopes are non-VALIDATED -> full_spectrum_vus_authorized=False, status != "PASS"
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    # Helper to build passing/failing metrics
    def get_metrics(missense_path_pass=True, missense_benign_pass=True, trunc_path_pass=True):
        m_missense = Metrics(
            precision=1.0, recall=1.0, concordance=1.0,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="missense", gating=True, benign_precision=1.0, benign_recall=1.0
        )
        m_missense.precision_lb = 0.92 if missense_path_pass else 0.80
        m_missense.recall_lb = 0.87 if missense_path_pass else 0.80
        m_missense.benign_precision_lb = 0.92 if missense_benign_pass else 0.80
        m_missense.benign_recall_lb = 0.87 if missense_benign_pass else 0.80

        m_truncating = Metrics(
            precision=1.0, recall=1.0, concordance=1.0,
            counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
            stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
        )
        m_truncating.precision_lb = 0.96 if trunc_path_pass else 0.90
        m_truncating.recall_lb = 0.96 if trunc_path_pass else 0.90
        m_truncating.benign_precision_lb = 0.0
        m_truncating.benign_recall_lb = 0.0

        return {"missense": m_missense, "truncating": m_truncating}

    # Case 1: All pass
    decision = decide_scope_gate(get_metrics(), cfg)
    assert decision.full_spectrum_vus_authorized is True
    assert decision.full_spectrum_status == "PASS"

    # Case 2: missense:pathogenic fails
    decision = decide_scope_gate(get_metrics(missense_path_pass=False), cfg)
    assert decision.full_spectrum_vus_authorized is False
    assert decision.full_spectrum_status == "FAIL"

    # Case 3: missense:benign fails
    decision = decide_scope_gate(get_metrics(missense_benign_pass=False), cfg)
    assert decision.full_spectrum_vus_authorized is False
    assert decision.full_spectrum_status == "FAIL"

    # Case 4: truncating:pathogenic fails
    decision = decide_scope_gate(get_metrics(trunc_path_pass=False), cfg)
    assert decision.full_spectrum_vus_authorized is False
    assert decision.full_spectrum_status == "FAIL"


def test_a7_narrow_research_flag_independent():
    """A7 narrow research flag independent:
    truncating:pathogenic VALIDATED + missense FAIL -> research flag for truncating is True, but full_spectrum is False.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    # Missense fails
    m_missense = Metrics(
        precision=0.8, recall=0.8, concordance=0.8,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.8, benign_recall=0.8
    )
    m_missense.precision_lb = 0.75
    m_missense.recall_lb = 0.75
    m_missense.benign_precision_lb = 0.75
    m_missense.benign_recall_lb = 0.75

    # Truncating VALIDATED
    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96
    m_truncating.benign_precision_lb = 0.0
    m_truncating.benign_recall_lb = 0.0

    metrics = {"missense": m_missense, "truncating": m_truncating}
    decision = decide_scope_gate(metrics, cfg)

    assert decision.full_spectrum_vus_authorized is False
    assert decision.research_scope_flags["truncating_pathogenic_research_scope_validated"] is True


def test_a8_governance_statement_matches_state():
    """A8 governance statement matches state:
    Assert state is correctly resolved and mapped to the verbatim statement.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    def get_decision(missense_pass=True, trunc_path_pass=True):
        m_missense = Metrics(
            precision=1.0, recall=1.0, concordance=1.0,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="missense", gating=True, benign_precision=1.0, benign_recall=1.0
        )
        m_missense.precision_lb = 0.92 if missense_pass else 0.75
        m_missense.recall_lb = 0.87 if missense_pass else 0.75
        m_missense.benign_precision_lb = 0.92 if missense_pass else 0.75
        m_missense.benign_recall_lb = 0.87 if missense_pass else 0.75

        m_truncating = Metrics(
            precision=1.0, recall=1.0, concordance=1.0,
            counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
            stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
        )
        m_truncating.precision_lb = 0.96 if trunc_path_pass else 0.75
        m_truncating.recall_lb = 0.96 if trunc_path_pass else 0.75
        m_truncating.benign_precision_lb = 0.0
        m_truncating.benign_recall_lb = 0.0

        return decide_scope_gate({"missense": m_missense, "truncating": m_truncating}, cfg)

    # 1. FULL_SPECTRUM
    d_full = get_decision(missense_pass=True, trunc_path_pass=True)
    assert d_full.governance_state == "FULL_SPECTRUM"
    assert d_full.governance_statement == "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission."

    # 2. TRUNCATING_PATHOGENIC_ONLY
    d_trunc = get_decision(missense_pass=False, trunc_path_pass=True)
    assert d_trunc.governance_state == "TRUNCATING_PATHOGENIC_ONLY"
    assert d_trunc.governance_statement == "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated."

    # 3. NONE_VALIDATED
    d_none = get_decision(missense_pass=False, trunc_path_pass=False)
    assert d_none.governance_state == "NONE_VALIDATED"
    assert d_none.governance_statement == "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."


def test_a9_no_clinical_and_has_research_use_disclaimer():
    """A9 no clinical/full-spectrum authorization language and has research_use_disclaimer:
    Assert there is a separate research_use_disclaimer field in the decision, 
    with the exact strict text.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    # Truncating VALIDATED
    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96

    decision = decide_scope_gate({"truncating": m_truncating}, cfg)

    assert hasattr(decision, "research_use_disclaimer")
    assert decision.research_use_disclaimer == "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission."


# ==============================================================================
# Group B — fail-closed
# ==============================================================================

def test_b1_missing_block():
    """B1 missing block:
    scope_authorization=None -> full_spectrum_status in {"BLOCKED_CONFIG", "UNVERIFIED"},
    all flags False, NONE_VALIDATED.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=None
    )

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96

    decision = decide_scope_gate({"truncating": m_truncating}, cfg)

    assert decision.full_spectrum_status in ("BLOCKED_CONFIG", "UNVERIFIED")
    assert decision.full_spectrum_vus_authorized is False
    assert all(not val for val in decision.research_scope_flags.values())
    assert decision.governance_state == "NONE_VALIDATED"


def test_b2_malformed_block():
    """B2 malformed block (hand-built EvalConfig):
    Requires names an unregistered scope, should fail-closed during decide_scope_gate.
    """
    malformed_auth = make_v2_auth_config()
    malformed_auth["full_spectrum"]["requires"] = ["ghost:pathogenic"]

    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=malformed_auth
    )

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96

    decision = decide_scope_gate({"truncating": m_truncating}, cfg)
    assert decision.full_spectrum_status in ("BLOCKED_CONFIG", "UNVERIFIED")
    assert decision.full_spectrum_vus_authorized is False
    assert decision.governance_state == "NONE_VALIDATED"


def test_b3_empty_oracle_thresholds():
    """B3 empty oracle_thresholds:
    oracle_thresholds={} -> all scopes DESCRIPTIVE, status="UNVERIFIED", nothing validated.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds={},
        scope_authorization=make_v2_auth_config()
    )

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96

    decision = decide_scope_gate({"truncating": m_truncating}, cfg)

    assert decision.full_spectrum_status == "UNVERIFIED"
    assert decision.full_spectrum_vus_authorized is False
    assert decision.governance_state == "NONE_VALIDATED"
    for scope in decision.scopes.values():
        assert scope.scope_status == "DESCRIPTIVE"


def test_b4_min_count_less_or_equal_zero():
    """B4 min_count_per_class <= 0:
    Should fail closed, nothing validated.
    """
    # Use make_eval_config overrides to force min_count_per_class <= 0.
    # Note that ConfigError might be thrown during config loading/creation if validated there,
    # but we can also test the gate behavior if config somehow has it <= 0.
    # We will test both the gate's resilience to bad config values and the validation.
    cfg = make_eval_config(
        min_count_per_class=0, # If config loader allows it or we hand-construct
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96

    decision = decide_scope_gate({"truncating": m_truncating}, cfg)
    assert decision.full_spectrum_status in ("BLOCKED_CONFIG", "UNVERIFIED")
    assert decision.full_spectrum_vus_authorized is False
    assert decision.governance_state == "NONE_VALIDATED"


def test_b5_absent_required_metrics():
    """B5 absent required metrics:
    `metrics` omits `truncating` -> `truncating:pathogenic` coverage_adequate=False,
    and cannot be VALIDATED.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    m_missense = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_missense.precision_lb = 0.92
    m_missense.recall_lb = 0.87
    m_missense.benign_precision_lb = 0.92
    m_missense.benign_recall_lb = 0.87

    # metrics omits 'truncating'
    metrics = {"missense": m_missense}
    decision = decide_scope_gate(metrics, cfg)

    # truncating:pathogenic verdict should be UNDERPOWERED or FAIL, but definitely not VALIDATED
    assert decision.scopes["truncating:pathogenic"].scope_status != "VALIDATED"
    assert decision.full_spectrum_vus_authorized is False
