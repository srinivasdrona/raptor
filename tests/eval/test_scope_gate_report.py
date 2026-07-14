from __future__ import annotations

from raptor.eval.model import (
    DirectionVerdict,
    GateDecision,
    Metrics,
    ScopeGateDecision,
)
from raptor.eval.report import EvalReport


GOVERNANCE_STATEMENT = (
    "Full-spectrum VUS automation is not authorized. Evidence supports only the "
    "validated truncating-pathogenic scope; missense remains unvalidated."
)
RESEARCH_USE_DISCLAIMER = (
    "Research-evidence validation only; this authorizes no clinical classification, "
    "VUS worklist, or ClinVar submission."
)
V1_HASH = "dbe66b5a9ee37f4918232d79a72aeaea81eea4fd37ee84b13a1f46bb935ef58f"


def _direction_verdict(*, validated: bool) -> DirectionVerdict:
    return DirectionVerdict(
        stratum="truncating",
        direction="pathogenic",
        precision_lb=0.96 if validated else 0.94,
        recall_lb=0.96 if validated else 0.94,
        precision_threshold=0.95,
        recall_threshold=0.95,
        actual_count=40,
        called_count=40,
        min_count=36,
        coverage_adequate=True,
        metric_status="MET" if validated else "UNMET",
        scope_status="VALIDATED" if validated else "FAIL",
        reasons=[] if validated else ["synthetic lower bound below threshold"],
    )


def _scope_gate(*, validated: bool = True) -> ScopeGateDecision:
    truncating = _direction_verdict(validated=validated)
    missense = DirectionVerdict(
        stratum="missense",
        direction="pathogenic",
        precision_lb=0.80,
        recall_lb=0.80,
        precision_threshold=0.90,
        recall_threshold=0.85,
        actual_count=40,
        called_count=17,
        min_count=36,
        coverage_adequate=False,
        metric_status="UNMET",
        scope_status="FAIL",
        reasons=["synthetic lower bound below threshold", "called coverage inadequate"],
    )
    return ScopeGateDecision(
        schema_version="2",
        scopes={
            "missense:pathogenic": missense,
            "truncating:pathogenic": truncating,
        },
        full_spectrum_status="FAIL",
        full_spectrum_vus_authorized=False,
        research_scope_flags={
            "truncating_pathogenic_research_scope_validated": validated,
        },
        governance_state=(
            "TRUNCATING_PATHOGENIC_ONLY" if validated else "NONE_VALIDATED"
        ),
        governance_statement=(
            GOVERNANCE_STATEMENT
            if validated
            else "Full-spectrum VUS automation is not authorized; no scope is validated."
        ),
        research_use_disclaimer=RESEARCH_USE_DISCLAIMER,
        reason="synthetic scope verdicts",
    )


def _report(*, scope_gate_marker="omitted") -> EvalReport:
    metric = Metrics(
        precision=0.80,
        recall=0.70,
        concordance=0.75,
        counts={"path_actual": 40, "path_called": 17},
        stratum="missense",
        gating=False,
        benign_precision=0.60,
        benign_recall=0.50,
        precision_lb=0.65,
        recall_lb=0.55,
        benign_precision_lb=0.45,
        benign_recall_lb=0.35,
    )
    kwargs = {
        "run_id": "synthetic-run",
        "generated_at": "2026-07-14T00:00:00Z",
        "labels_snapshot": "synthetic-snapshot",
        "benchmark_size": 4,
        "train_dev_size": 2,
        "holdout_size": 2,
        "holdout_label_counts": {"B": 1, "P": 1},
        "holdout_class_counts": {"missense": 2},
        "metrics": {"missense": metric},
        "gate": GateDecision(
            status="FAIL",
            stratum="missense",
            reason="synthetic",
            vus_authorized=False,
            per_stratum={},
        ),
    }
    if scope_gate_marker != "omitted":
        kwargs["scope_gate"] = scope_gate_marker
    return EvalReport(**kwargs)


def test_report_renders_scope_axes_governance_and_disclaimer() -> None:
    rendered = _report(scope_gate_marker=_scope_gate()).render()

    assert "missense:pathogenic" in rendered
    assert "truncating:pathogenic" in rendered
    assert "metric_status" in rendered
    assert "UNMET" in rendered
    assert "MET" in rendered
    assert "coverage_adequate" in rendered
    assert "False" in rendered
    assert "scope_status" in rendered
    assert "VALIDATED" in rendered
    assert "0.95" in rendered
    assert "truncating_pathogenic_research_scope_validated" in rendered
    assert GOVERNANCE_STATEMENT in rendered
    assert RESEARCH_USE_DISCLAIMER in rendered


def test_absent_scope_gate_preserves_v1_content_hash() -> None:
    omitted = _report()
    explicit_none = _report(scope_gate_marker=None)

    assert omitted.content_hash() == explicit_none.content_hash()
    assert omitted.content_hash() == V1_HASH


def test_scope_gate_verdict_changes_content_hash() -> None:
    validated = _report(scope_gate_marker=_scope_gate(validated=True))
    failed = _report(scope_gate_marker=_scope_gate(validated=False))

    assert validated.content_hash() != failed.content_hash()


def test_scope_gate_disclaimer_is_part_of_serialized_report_content() -> None:
    original_gate = _scope_gate()
    altered_gate = _scope_gate()
    altered_gate.research_use_disclaimer = (
        "Research-evidence validation only; no clinical use is authorized."
    )

    original = _report(scope_gate_marker=original_gate)
    altered = _report(scope_gate_marker=altered_gate)
    assert original.content_hash() != altered.content_hash()
