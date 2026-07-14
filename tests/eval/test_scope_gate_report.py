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

