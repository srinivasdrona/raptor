import pytest
from raptor.eval.report import EvalReport
from raptor.eval.model import GateDecision, Metrics

# The new ScopeGateDecision class and DirectionVerdict class are expected to be imported.
# In the RED state, this will fail or raise ImportError, which is correct.
from raptor.eval.model import ScopeGateDecision, DirectionVerdict


def test_d1_renders_scope_section():
    """D1 renders scope section:
    EvalReport(..., scope_gate=<v2 decision>) -> render() contains each scope key, its
    metric_status, coverage_adequate, thresholds (e.g., "0.95"), scope_status, the research flag,
    the governance statement, and the research_use_disclaimer verbatim.
    """
    m = Metrics(1.0, 1.0, 1.0, {}, "missense", True, 1.0, 1.0)
    gate = GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False)

    # Let's mock a v2 ScopeGateDecision
    # Fields of DirectionVerdict:
    # stratum, direction, precision_lb, recall_lb, precision_threshold, recall_threshold,
    # actual_count, called_count, min_count, coverage_adequate, metric_status, scope_status, reasons
    scopes = {
        "truncating:pathogenic": DirectionVerdict(
            stratum="truncating",
            direction="pathogenic",
            precision_lb=0.96,
            recall_lb=0.96,
            precision_threshold=0.95,
            recall_threshold=0.95,
            actual_count=40,
            called_count=40,
            min_count=36,
            coverage_adequate=True,
            metric_status="MET",
            scope_status="VALIDATED",
            reasons=[]
        ),
        "truncating:benign": DirectionVerdict(
            stratum="truncating",
            direction="benign",
            precision_lb=0.0,
            recall_lb=0.0,
            precision_threshold=None,
            recall_threshold=None,
            actual_count=1,
            called_count=1,
            min_count=36,
            coverage_adequate=False,
            metric_status="NO_THRESHOLD",
            scope_status="DESCRIPTIVE",
            reasons=[]
        )
    }

    v2_decision = ScopeGateDecision(
        schema_version="2",
        scopes=scopes,
        full_spectrum_status="FAIL",
        full_spectrum_vus_authorized=False,
        research_scope_flags={"truncating_pathogenic_research_scope_validated": True},
        governance_state="TRUNCATING_PATHOGENIC_ONLY",
        governance_statement="Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
        research_use_disclaimer="Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        reason="some reason"
    )

    report = EvalReport(
        run_id="run-1",
        generated_at="2026-07-14",
        labels_snapshot="snap-1",
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5, "truncating": 2},
        metrics={"missense": m},
        gate=gate,
        scope_gate=v2_decision
    )

    rendered = report.render()

    # Assert rendered contains each of the required details
    assert "truncating:pathogenic" in rendered
    assert "VALIDATED" in rendered
    assert "MET" in rendered
    assert "0.95" in rendered # threshold
    assert "coverage_adequate=True" in rendered or "coverage_adequate: True" in rendered or "adequate" in rendered

    assert "truncating:benign" in rendered
    assert "DESCRIPTIVE" in rendered
    assert "NO_THRESHOLD" in rendered

    assert "truncating_pathogenic_research_scope_validated=True" in rendered or "truncating_pathogenic_research_scope_validated" in rendered
    assert "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated." in rendered
    assert "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission." in rendered


def test_d2_hash_unchanged_when_absent():
    """D2 hash unchanged when absent:
    two EvalReports identical except one has scope_gate=None and the other never sets it (which defaults to None)
    -> identical content_hash() to a v1-shaped report (additive field must not alter v1 hash).
    """
    m = Metrics(1.0, 1.0, 1.0, {}, "missense", True, 1.0, 1.0)
    gate = GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False)

    report_default = EvalReport(
        run_id="run-1",
        generated_at="2026-07-14",
        labels_snapshot="snap-1",
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5},
        metrics={"missense": m},
        gate=gate
    )

    report_none = EvalReport(
        run_id="run-1",
        generated_at="2026-07-14",
        labels_snapshot="snap-1",
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5},
        metrics={"missense": m},
        gate=gate,
        scope_gate=None
    )

    # Check they have identical hashes
    assert report_default.content_hash() == report_none.content_hash()


def test_d3_hash_includes_scope_gate_when_present():
    """D3 hash includes scope-gate when present:
    two reports differing only in a scope verdict (e.g. truncating VALIDATED vs FAIL)
    -> different content_hash().
    """
    m = Metrics(1.0, 1.0, 1.0, {}, "missense", True, 1.0, 1.0)
    gate = GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False)

    def get_report(status: str) -> EvalReport:
        scopes = {
            "truncating:pathogenic": DirectionVerdict(
                stratum="truncating",
                direction="pathogenic",
                precision_lb=0.96,
                recall_lb=0.96,
                precision_threshold=0.95,
                recall_threshold=0.95,
                actual_count=40,
                called_count=40,
                min_count=36,
                coverage_adequate=True,
                metric_status="MET",
                scope_status=status,
                reasons=[]
            )
        }
        v2_decision = ScopeGateDecision(
            schema_version="2",
            scopes=scopes,
            full_spectrum_status="FAIL",
            full_spectrum_vus_authorized=False,
            research_scope_flags={"truncating_pathogenic_research_scope_validated": (status == "VALIDATED")},
            governance_state="TRUNCATING_PATHOGENIC_ONLY" if status == "VALIDATED" else "NONE_VALIDATED",
            governance_statement="statement",
            research_use_disclaimer="disclaimer",
            reason="reason"
        )
        return EvalReport(
            run_id="run-1",
            generated_at="2026-07-14",
            labels_snapshot="snap-1",
            benchmark_size=10,
            train_dev_size=3,
            holdout_size=7,
            holdout_label_counts={"P": 4, "B": 3},
            holdout_class_counts={"missense": 5, "truncating": 2},
            metrics={"missense": m},
            gate=gate,
            scope_gate=v2_decision
        )

    report_validated = get_report("VALIDATED")
    report_fail = get_report("FAIL")

    # Hashes should be different
    assert report_validated.content_hash() != report_fail.content_hash()


# =========================================================================
# RED REGRESSION TESTS FOR GPT-5.4 FINDINGS
# =========================================================================

def test_finding_5_report_serialization_omits_none_scope_gate() -> None:
    """Finding 5 [Medium]: Pure helper test asserting that when scope_gate is None,
    the serialized report dictionary (e.g. from dataclass asdict() or standard helper)
    omits the `scope_gate` key entirely, rather than outputting `scope_gate: null`.
    """
    from dataclasses import asdict
    m = Metrics(1.0, 1.0, 1.0, {}, "missense", True, 1.0, 1.0)
    gate = GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False)

    report = EvalReport(
        run_id="run-1",
        generated_at="2026-07-14",
        labels_snapshot="snap-1",
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5},
        metrics={"missense": m},
        gate=gate,
        scope_gate=None  # Explicit None
    )

    # Let's check how the serialized dictionary handles scope_gate
    serialized = asdict(report)
    
    # In order to omit None/null keys, we can have a serialization helper or post-process.
    # Asserting that the key is completely absent:
    assert "scope_gate" not in serialized


# =========================================================================
# RED REGRESSION TESTS FOR GPT-5.4 BLOCKERS (PUBLICATION INTEGRITY)
# =========================================================================

def test_blocker_1_eval_report_gate_mandatory_constructor():
    """Assert that EvalReport constructor requires `gate` as a mandatory,
    non-optional argument, and doesn't default to None, and run_id and
    generated_at are the first two mandatory arguments of the constructor."""
    import inspect
    from raptor.eval.report import EvalReport
    from raptor.eval.model import GateDecision

    sig = inspect.signature(EvalReport)
    params = list(sig.parameters.values())

    # Check first parameter is run_id (no default)
    assert params[0].name == "run_id"
    assert params[0].default is inspect.Parameter.empty

    # Check second parameter is generated_at (no default)
    assert params[1].name == "generated_at"
    assert params[1].default is inspect.Parameter.empty

    # Check gate is mandatory (non-optional, no default None)
    gate_param = sig.parameters.get("gate")
    assert gate_param is not None
    assert gate_param.default is inspect.Parameter.empty


def test_blocker_1_report_to_dict_gate_none_raises_loudly():
    """EvalReport/report_to_dict with gate=None and scope_gate present must fail loud
    (TypeError or ValueError) before producing an envelope; it must not advertise/serialize
    a v2-only shape the builder cannot consume."""
    from raptor.eval.report import EvalReport, report_to_dict
    from raptor.eval.model import Metrics, ScopeGateDecision

    # If gate is None (or if we bypass/mock it) and scope_gate is present, report_to_dict must fail loud.
    m = Metrics(1.0, 1.0, 1.0, {}, "missense", True, 1.0, 1.0)
    
    # We try to build a report with gate=None
    with pytest.raises((TypeError, ValueError)):
        # Constructing it or calling report_to_dict with gate=None must fail loud.
        report = EvalReport(
            run_id="run-1",
            generated_at="2026-07-15",
            labels_snapshot="snap",
            benchmark_size=10,
            train_dev_size=3,
            holdout_size=7,
            holdout_label_counts={"P": 4, "B": 3},
            holdout_class_counts={"missense": 5},
            metrics={"missense": m},
            gate=None,  # Passed None
            scope_gate=ScopeGateDecision(
                schema_version="2",
                scopes={},
                full_spectrum_status="FAIL",
                full_spectrum_vus_authorized=False,
                research_scope_flags={},
                governance_state="NONE_VALIDATED",
                governance_statement="statement",
                research_use_disclaimer="disclaimer",
                reason="reason"
            )
        )
        # Or if the constructor somehow accepts it, report_to_dict must fail loud
        report_to_dict(report)


def test_blocker_1_normal_v2_report_serializes_and_aggregates():
    """Normal v2 report with real GateDecision + ScopeGateDecision serializes and aggregates."""
    from raptor.eval.report import EvalReport, report_to_dict
    from raptor.eval.model import Metrics, GateDecision, ScopeGateDecision

    m = Metrics(1.0, 1.0, 1.0, {}, "missense", True, 1.0, 1.0)
    gate = GateDecision(status="FAIL", stratum="missense", reason="below", vus_authorized=False)
    v2_decision = ScopeGateDecision(
        schema_version="2",
        scopes={},
        full_spectrum_status="FAIL",
        full_spectrum_vus_authorized=False,
        research_scope_flags={},
        governance_state="NONE_VALIDATED",
        governance_statement="statement",
        research_use_disclaimer="disclaimer",
        reason="reason"
    )

    report = EvalReport(
        run_id="run-1",
        generated_at="2026-07-15",
        labels_snapshot="snap",
        benchmark_size=10,
        train_dev_size=3,
        holdout_size=7,
        holdout_label_counts={"P": 4, "B": 3},
        holdout_class_counts={"missense": 5},
        metrics={"missense": m},
        gate=gate,
        scope_gate=v2_decision
    )

    serialized = report_to_dict(report)
    assert serialized is not None
    assert "gate" in serialized
    assert "scope_gate" in serialized


def test_blocker_2_direct_hand_built_config_missense_or_truncating_spec_not_dict_returns_blocked_config():
    """Direct hand-built EvalConfig exact top-level structure but missense or truncating
    spec values: string, list, None, int => decide_scope_gate returns BLOCKED_CONFIG/no auth and does not throw."""
    from raptor.eval.config import EvalConfig
    from raptor.eval.scope_gate import decide_scope_gate
    from raptor.eval.model import Metrics

    m = Metrics(1.0, 1.0, 1.0, {}, "missense", True, 1.0, 1.0)

    # Base valid top level structures
    automatable_criteria = ["PVS1", "PS3", "PM1", "PM2", "PP3", "BA1", "BS1", "BS2", "BP4", "BP7"]
    tavtigian_points = {"supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8, "stand_alone": 8}
    tavtigian_cutoffs = {"pathogenic_min": 10, "likely_pathogenic_min": 6, "vus_min": 0, "vus_max": 5, "likely_benign_max": -1, "benign_max": -7}
    split = {"seed": 42, "holdout_fraction": 0.3}
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

    bad_specs = [
        "not-a-dict",                      # string
        ["pathogenic", "benign"],          # list
        None,                              # None
        42                                 # int
    ]

    for bad_spec in bad_specs:
        # missense spec is bad_spec
        cfg_missense_bad = EvalConfig(
            automatable_criteria=automatable_criteria,
            tavtigian_points=tavtigian_points,
            tavtigian_cutoffs=tavtigian_cutoffs,
            min_count_per_class=36,
            split=split,
            oracle_thresholds={
                "confidence": 0.95,
                "strata": {
                    "missense": bad_spec,
                    "truncating": {
                        "precision": 0.95,
                        "recall": 0.95,
                        "gating": True,
                        "directions": ["pathogenic"]
                    }
                }
            },
            labels_snapshot="snap",
            scope_authorization=scope_auth
        )

        # Calling decide_scope_gate must return BLOCKED_CONFIG, not raise/throw an exception!
        decision = decide_scope_gate({"missense": m}, cfg_missense_bad)
        assert decision.full_spectrum_status == "BLOCKED_CONFIG"
        assert decision.full_spectrum_vus_authorized is False

        # truncating spec is bad_spec
        cfg_truncating_bad = EvalConfig(
            automatable_criteria=automatable_criteria,
            tavtigian_points=tavtigian_points,
            tavtigian_cutoffs=tavtigian_cutoffs,
            min_count_per_class=36,
            split=split,
            oracle_thresholds={
                "confidence": 0.95,
                "strata": {
                    "missense": {
                        "precision": 0.90,
                        "recall": 0.85,
                        "gating": True,
                        "directions": ["pathogenic", "benign"]
                    },
                    "truncating": bad_spec
                }
            },
            labels_snapshot="snap",
            scope_authorization=scope_auth
        )

        decision2 = decide_scope_gate({"missense": m}, cfg_truncating_bad)
        assert decision2.full_spectrum_status == "BLOCKED_CONFIG"
        assert decision2.full_spectrum_vus_authorized is False


def test_overall_descriptive_rendering_v1_and_v2() -> None:
    """RED regression tests for preserving `overall` in descriptive rendering:
    1. Construct a legacy v1 `EvalReport` (`scope_gate=None`) whose metrics include
       `overall`, `missense`, `truncating`, and `other`.
       `render()` must include all four descriptive metric rows, including `overall`.
    2. Compare v1 render behavior against the base contract expected text/order
       sufficiently to catch the current omission; do not overfit timestamps/hash.
    3. Construct a v2 `EvalReport` with the same metrics plus scope_gate; its
       general descriptive metrics section must still include `overall`.
    4. Its scope authorization/verdict section must NOT contain `overall:pathogenic`
       or `overall:benign`; canonical scope-gate reason must not contain `overall:`.
    5. `report_to_dict` continues to retain `metrics.overall` while
       `scope_gate.scopes` excludes overall.
    """
    from raptor.eval.report import report_to_dict
    from raptor.eval.scope_gate import canonical_scope_gate_reason

    # Step 1: Construct metrics for overall, missense, truncating, and other
    m_overall = Metrics(
        precision=0.9100, recall=0.8600, concordance=0.9000,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="overall", gating=False, benign_precision=0.9100, benign_recall=0.8600
    )
    m_overall.precision_lb = 0.8500
    m_overall.recall_lb = 0.8000
    m_overall.benign_precision_lb = 0.8500
    m_overall.benign_recall_lb = 0.8000

    m_missense = Metrics(
        precision=0.9200, recall=0.8700, concordance=0.9100,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.9200, benign_recall=0.8700
    )
    m_missense.precision_lb = 0.8600
    m_missense.recall_lb = 0.8100
    m_missense.benign_precision_lb = 0.8600
    m_missense.benign_recall_lb = 0.8100

    m_truncating = Metrics(
        precision=0.9600, recall=0.9600, concordance=0.9500,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="truncating", gating=True, benign_precision=0.9600, benign_recall=0.9600
    )
    m_truncating.precision_lb = 0.9000
    m_truncating.recall_lb = 0.9000
    m_truncating.benign_precision_lb = 0.9000
    m_truncating.benign_recall_lb = 0.9000

    m_other = Metrics(
        precision=0.8100, recall=0.8100, concordance=0.8100,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="other", gating=False, benign_precision=0.8100, benign_recall=0.8100
    )
    m_other.precision_lb = 0.7500
    m_other.recall_lb = 0.7500
    m_other.benign_precision_lb = 0.7500
    m_other.benign_recall_lb = 0.7500

    metrics = {
        "overall": m_overall,
        "missense": m_missense,
        "truncating": m_truncating,
        "other": m_other
    }

    # Construct a real synthetic GateDecision (gate is mandatory)
    gate = GateDecision(
        status="PASS",
        stratum="missense",
        reason="all strata pass",
        vus_authorized=True,
        per_stratum={}
    )

    # 1 & 2: Construct legacy v1 EvalReport and render it
    report_v1 = EvalReport(
        run_id="run-v1",
        generated_at="2026-07-15",
        labels_snapshot="snap-1",
        benchmark_size=160,
        train_dev_size=60,
        holdout_size=100,
        holdout_label_counts={"P": 80, "B": 80},
        holdout_class_counts={"missense": 80, "truncating": 80},
        metrics=metrics,
        gate=gate,
        scope_gate=None
    )

    rendered_v1 = report_v1.render()

    # Compare v1 render behavior against the expected text/order
    # sorted(self.metrics.items()) order:
    # 1. missense, 2. other, 3. overall, 4. truncating
    assert "  - missense: precision=0.9200" in rendered_v1
    assert "  - other: precision=0.8100" in rendered_v1
    assert "  - overall: precision=0.9100" in rendered_v1
    assert "  - truncating: precision=0.9600" in rendered_v1

    idx_missense_v1 = rendered_v1.index("  - missense: precision=0.9200")
    idx_other_v1 = rendered_v1.index("  - other: precision=0.8100")
    idx_overall_v1 = rendered_v1.index("  - overall: precision=0.9100")
    idx_truncating_v1 = rendered_v1.index("  - truncating: precision=0.9600")

    assert idx_missense_v1 < idx_other_v1 < idx_overall_v1 < idx_truncating_v1

    # 3: Construct a v2 EvalReport with the same metrics plus scope_gate
    scopes = {
        "missense:pathogenic": DirectionVerdict(
            stratum="missense", direction="pathogenic", precision_lb=0.86, recall_lb=0.81,
            precision_threshold=0.90, recall_threshold=0.85, actual_count=40, called_count=40,
            min_count=36, coverage_adequate=True, metric_status="MET", scope_status="VALIDATED", reasons=[]
        ),
        "missense:benign": DirectionVerdict(
            stratum="missense", direction="benign", precision_lb=0.86, recall_lb=0.81,
            precision_threshold=0.90, recall_threshold=0.85, actual_count=40, called_count=40,
            min_count=36, coverage_adequate=True, metric_status="MET", scope_status="VALIDATED", reasons=[]
        ),
        "truncating:pathogenic": DirectionVerdict(
            stratum="truncating", direction="pathogenic", precision_lb=0.90, recall_lb=0.90,
            precision_threshold=0.95, recall_threshold=0.95, actual_count=40, called_count=40,
            min_count=36, coverage_adequate=True, metric_status="MET", scope_status="VALIDATED", reasons=[]
        ),
        "truncating:benign": DirectionVerdict(
            stratum="truncating", direction="benign", precision_lb=0.90, recall_lb=0.90,
            precision_threshold=None, recall_threshold=None, actual_count=40, called_count=40,
            min_count=36, coverage_adequate=True, metric_status="NO_THRESHOLD", scope_status="DESCRIPTIVE", reasons=[]
        ),
        "other:pathogenic": DirectionVerdict(
            stratum="other", direction="pathogenic", precision_lb=0.75, recall_lb=0.75,
            precision_threshold=None, recall_threshold=None, actual_count=40, called_count=40,
            min_count=36, coverage_adequate=True, metric_status="NO_THRESHOLD", scope_status="DESCRIPTIVE", reasons=[]
        ),
        "other:benign": DirectionVerdict(
            stratum="other", direction="benign", precision_lb=0.75, recall_lb=0.75,
            precision_threshold=None, recall_threshold=None, actual_count=40, called_count=40,
            min_count=36, coverage_adequate=True, metric_status="NO_THRESHOLD", scope_status="DESCRIPTIVE", reasons=[]
        )
    }

    v2_decision = ScopeGateDecision(
        schema_version="2",
        scopes=scopes,
        full_spectrum_status="PASS",
        full_spectrum_vus_authorized=True,
        research_scope_flags={"truncating_pathogenic_research_scope_validated": True},
        governance_state="FULL_SPECTRUM",
        governance_statement="All pre-registered research scopes are validated.",
        research_use_disclaimer="Disclaimer statement.",
        reason="missense:benign=VALIDATED; missense:pathogenic=VALIDATED; truncating:benign=DESCRIPTIVE; truncating:pathogenic=VALIDATED; other:benign=DESCRIPTIVE; other:pathogenic=DESCRIPTIVE",
        authorization_blockers=[]
    )

    report_v2 = EvalReport(
        run_id="run-v2",
        generated_at="2026-07-15",
        labels_snapshot="snap-1",
        benchmark_size=160,
        train_dev_size=60,
        holdout_size=100,
        holdout_label_counts={"P": 80, "B": 80},
        holdout_class_counts={"missense": 80, "truncating": 80},
        metrics=metrics,
        gate=gate,
        scope_gate=v2_decision
    )

    rendered_v2 = report_v2.render()

    # The general descriptive metrics section in v2 must still include overall and maintain order
    assert "  - overall: precision=0.9100" in rendered_v2
    idx_missense_v2 = rendered_v2.index("  - missense: precision=0.9200")
    idx_other_v2 = rendered_v2.index("  - other: precision=0.8100")
    idx_overall_v2 = rendered_v2.index("  - overall: precision=0.9100")
    idx_truncating_v2 = rendered_v2.index("  - truncating: precision=0.9600")

    assert idx_missense_v2 < idx_other_v2 < idx_overall_v2 < idx_truncating_v2

    # 4: Its scope authorization/verdict section must NOT contain overall:pathogenic or overall:benign,
    # and canonical scope-gate reason must not contain overall:
    scope_section_header = "--- v2 scope-specific research authorization (preregistered, non-clinical) ---"
    assert scope_section_header in rendered_v2
    _, scope_section = rendered_v2.split(scope_section_header, 1)

    assert "overall:pathogenic" not in scope_section
    assert "overall:benign" not in scope_section
    assert "overall:" not in scope_section

    reason_text = canonical_scope_gate_reason(
        {k: v.scope_status for k, v in v2_decision.scopes.items()},
        v2_decision.authorization_blockers
    )
    assert "overall:" not in reason_text
    assert "overall:" not in v2_decision.reason

    # 5: report_to_dict continues to retain metrics.overall while scope_gate.scopes excludes overall
    serialized_v2 = report_to_dict(report_v2)
    assert "overall" in serialized_v2["metrics"]
    assert serialized_v2["metrics"]["overall"]["precision"] == 0.9100

    assert "scope_gate" in serialized_v2
    scopes_dict = serialized_v2["scope_gate"]["scopes"]
    assert "overall:pathogenic" not in scopes_dict
    assert "overall:benign" not in scopes_dict
    for scope_key in scopes_dict:
        assert not scope_key.startswith("overall:")



