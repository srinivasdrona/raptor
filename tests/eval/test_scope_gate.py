from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import Metrics, make_eval_config
from raptor.eval.scope_gate import decide_scope_gate


GOVERNANCE_STATEMENT = (
    "Full-spectrum VUS automation is not authorized. Evidence supports only the "
    "validated truncating-pathogenic scope; missense remains unvalidated."
)
NONE_VALIDATED_STATEMENT = (
    "Full-spectrum VUS automation is not authorized; no pre-registered research "
    "scope is currently validated."
)
RESEARCH_USE_DISCLAIMER = (
    "Research-evidence validation only; this authorizes no clinical classification, "
    "VUS worklist, or ClinVar submission."
)


def _thresholds() -> dict:
    return {
        "confidence": 0.95,
        "strata": {
            "missense": {
                "precision": 0.90,
                "recall": 0.85,
                "gating": True,
                "directions": ["pathogenic", "benign"],
            },
            "truncating": {
                "precision": 0.95,
                "recall": 0.95,
                "gating": True,
                "directions": ["pathogenic"],
            },
        },
    }


def _scope_authorization() -> dict:
    return {
        "schema_version": 2,
        "full_spectrum": {
            "requires": [
                "missense:pathogenic",
                "missense:benign",
                "truncating:pathogenic",
            ],
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": ["truncating:pathogenic"],
            },
        },
        "governance_statements": {
            "FULL_SPECTRUM": (
                "All pre-registered research scopes are validated for research-evidence "
                "use only; this authorizes no clinical classification, VUS worklist, or "
                "ClinVar submission."
            ),
            "TRUNCATING_PATHOGENIC_ONLY": GOVERNANCE_STATEMENT,
            "NONE_VALIDATED": NONE_VALIDATED_STATEMENT,
        },
        "research_use_disclaimer": RESEARCH_USE_DISCLAIMER,
    }


def _config(**overrides):
    values = {
        "min_count_per_class": 36,
        "oracle_thresholds": _thresholds(),
        "scope_authorization": _scope_authorization(),
    }
    values.update(overrides)
    return make_eval_config(**values)


def _metrics(
    stratum: str,
    *,
    path_lb: tuple[float, float] = (0.99, 0.99),
    benign_lb: tuple[float, float] = (0.99, 0.99),
    path_actual: int = 40,
    path_called: int = 40,
    benign_actual: int = 40,
    benign_called: int = 40,
) -> Metrics:
    metric = Metrics(
        precision=path_lb[0],
        recall=path_lb[1],
        concordance=0.9,
        counts={
            "path_actual": path_actual,
            "path_called": path_called,
            "benign_actual": benign_actual,
            "benign_called": benign_called,
        },
        stratum=stratum,
        gating=True,
        benign_precision=benign_lb[0],
        benign_recall=benign_lb[1],
    )
    metric.precision_lb, metric.recall_lb = path_lb
    metric.benign_precision_lb, metric.benign_recall_lb = benign_lb
    return metric


def _partial_metrics() -> dict[str, Metrics]:
    return {
        "missense": _metrics(
            "missense",
            path_lb=(0.80, 0.80),
            benign_lb=(0.80, 0.80),
            path_called=17,
            benign_called=34,
        ),
        "truncating": _metrics(
            "truncating",
            path_lb=(0.96, 0.96),
            benign_actual=1,
            benign_called=1,
        ),
    }


def _all_required_met() -> dict[str, Metrics]:
    return {
        "missense": _metrics(
            "missense", path_lb=(0.91, 0.86), benign_lb=(0.91, 0.86)
        ),
        "truncating": _metrics("truncating", path_lb=(0.96, 0.96)),
    }


def _assert_nothing_validated(decision) -> None:
    assert decision.full_spectrum_vus_authorized is False
    assert not any(decision.research_scope_flags.values())
    assert all(
        scope.scope_status != "VALIDATED" for scope in decision.scopes.values()
    )


def _assert_safe_disclaimer(decision) -> None:
    assert decision.research_use_disclaimer.strip()
    assert "no clinical classification" in decision.research_use_disclaimer
    assert "VUS worklist" in decision.research_use_disclaimer
    assert "ClinVar submission" in decision.research_use_disclaimer


def test_all_scopes_are_evaluated_without_missense_short_circuit() -> None:
    decision = decide_scope_gate(_partial_metrics(), _config())

    assert {
        "missense:pathogenic",
        "missense:benign",
        "truncating:pathogenic",
        "truncating:benign",
    } <= decision.scopes.keys()
    assert decision.scopes["missense:pathogenic"].scope_status == "FAIL"
    assert decision.scopes["truncating:pathogenic"].scope_status == "VALIDATED"


def test_metric_failure_and_called_coverage_inadequacy_are_independent_axes() -> None:
    decision = decide_scope_gate(_partial_metrics(), _config())

    for key in ("missense:pathogenic", "missense:benign"):
        verdict = decision.scopes[key]
        assert verdict.metric_status == "UNMET"
        assert verdict.coverage_adequate is False
        assert verdict.scope_status == "FAIL"


def test_unregistered_truncating_benign_direction_is_descriptive() -> None:
    decision = decide_scope_gate(_partial_metrics(), _config())
    verdict = decision.scopes["truncating:benign"]

    assert verdict.precision_threshold is None
    assert verdict.recall_threshold is None
    assert verdict.metric_status == "NO_THRESHOLD"
    assert verdict.scope_status == "DESCRIPTIVE"
    assert verdict.coverage_adequate is False
    assert decision.research_scope_flags[
        "truncating_pathogenic_research_scope_validated"
    ] is True


@pytest.mark.parametrize(
    ("lb", "count", "metric_status", "coverage_adequate", "scope_status"),
    [
        (0.96, 36, "MET", True, "VALIDATED"),
        (0.96, 35, "MET", False, "UNDERPOWERED"),
        (0.94, 36, "UNMET", True, "FAIL"),
        (0.94, 35, "UNMET", False, "FAIL"),
    ],
)
def test_truncating_pathogenic_requires_metric_and_coverage(
    lb: float,
    count: int,
    metric_status: str,
    coverage_adequate: bool,
    scope_status: str,
) -> None:
    metrics = _all_required_met()
    metrics["truncating"] = _metrics(
        "truncating",
        path_lb=(lb, lb),
        path_actual=count,
        path_called=count,
    )

    verdict = decide_scope_gate(metrics, _config()).scopes[
        "truncating:pathogenic"
    ]
    assert verdict.metric_status == metric_status
    assert verdict.coverage_adequate is coverage_adequate
    assert verdict.scope_status == scope_status
    assert (verdict.scope_status == "VALIDATED") is (
        metric_status == "MET" and coverage_adequate
    )


def test_unregistered_other_scopes_are_descriptive_and_authorize_nothing() -> None:
    decision = decide_scope_gate(
        {"other": _metrics("other", path_lb=(1.0, 1.0), benign_lb=(1.0, 1.0))},
        _config(),
    )

    for key in ("other:pathogenic", "other:benign"):
        verdict = decision.scopes[key]
        assert verdict.precision_threshold is None
        assert verdict.recall_threshold is None
        assert verdict.metric_status == "NO_THRESHOLD"
        assert verdict.scope_status == "DESCRIPTIVE"
    _assert_nothing_validated(decision)


def test_full_spectrum_requires_every_preregistered_scope() -> None:
    decision = decide_scope_gate(_all_required_met(), _config())

    assert decision.full_spectrum_vus_authorized is True
    assert decision.full_spectrum_status == "PASS"


@pytest.mark.parametrize(
    "failed_scope",
    [
        "missense:pathogenic",
        "missense:benign",
        "truncating:pathogenic",
    ],
)
def test_each_nonvalidated_required_scope_blocks_full_spectrum(
    failed_scope: str,
) -> None:
    metrics = _all_required_met()
    stratum, direction = failed_scope.split(":")
    metric = metrics[stratum]
    if direction == "pathogenic":
        metric.precision_lb = 0.1
    else:
        metric.benign_precision_lb = 0.1

    decision = decide_scope_gate(metrics, _config())
    assert decision.scopes[failed_scope].scope_status == "FAIL"
    assert decision.full_spectrum_vus_authorized is False
    assert decision.full_spectrum_status == "FAIL"


def test_narrow_research_flag_is_independent_of_failed_missense() -> None:
    decision = decide_scope_gate(_partial_metrics(), _config())

    assert decision.research_scope_flags[
        "truncating_pathogenic_research_scope_validated"
    ] is True
    assert decision.full_spectrum_vus_authorized is False
    assert decision.governance_state == "TRUNCATING_PATHOGENIC_ONLY"


def test_overall_pooled_metrics_do_not_influence_scope_flags() -> None:
    low_overall = _partial_metrics()
    low_overall["overall"] = _metrics(
        "overall", path_lb=(0.0, 0.0), benign_lb=(0.0, 0.0)
    )
    high_overall = deepcopy(low_overall)
    high_overall["overall"] = _metrics(
        "overall", path_lb=(1.0, 1.0), benign_lb=(1.0, 1.0)
    )

    low = decide_scope_gate(low_overall, _config())
    high = decide_scope_gate(high_overall, _config())
    assert low.full_spectrum_vus_authorized == high.full_spectrum_vus_authorized
    assert low.research_scope_flags == high.research_scope_flags
    assert low.governance_state == high.governance_state


def test_governance_statement_is_selected_only_for_supported_state() -> None:
    partial = decide_scope_gate(_partial_metrics(), _config())
    none = decide_scope_gate(
        {
            "missense": _metrics(
                "missense", path_lb=(0.1, 0.1), benign_lb=(0.1, 0.1)
            ),
            "truncating": _metrics("truncating", path_lb=(0.1, 0.1)),
        },
        _config(),
    )

    assert partial.governance_statement == GOVERNANCE_STATEMENT
    assert partial.governance_state == "TRUNCATING_PATHOGENIC_ONLY"
    assert none.governance_statement == NONE_VALIDATED_STATEMENT
    assert none.governance_state == "NONE_VALIDATED"
    assert none.governance_statement != GOVERNANCE_STATEMENT


def test_verbatim_governance_has_separate_mandatory_research_disclaimer() -> None:
    decision = decide_scope_gate(_partial_metrics(), _config())

    assert decision.governance_statement == GOVERNANCE_STATEMENT
    assert decision.research_use_disclaimer == RESEARCH_USE_DISCLAIMER
    assert "no clinical classification" in decision.research_use_disclaimer
    assert "VUS worklist" in decision.research_use_disclaimer
    assert "ClinVar submission" in decision.research_use_disclaimer


def test_missing_scope_authorization_fails_closed() -> None:
    decision = decide_scope_gate(
        _all_required_met(), _config(scope_authorization=None)
    )

    assert decision.full_spectrum_status in {"BLOCKED_CONFIG", "UNVERIFIED"}
    assert decision.governance_state == "NONE_VALIDATED"
    _assert_safe_disclaimer(decision)
    _assert_nothing_validated(decision)


@pytest.mark.parametrize(
    "mutation",
    ["unregistered_scope", "missing_governance", "missing_disclaimer"],
)
def test_hand_built_malformed_scope_authorization_fails_closed(
    mutation: str,
) -> None:
    authorization = _scope_authorization()
    if mutation == "unregistered_scope":
        authorization["research_scopes"]["bad"] = {
            "requires": ["ghost:pathogenic"]
        }
    elif mutation == "missing_governance":
        del authorization["governance_statements"]["NONE_VALIDATED"]
    else:
        del authorization["research_use_disclaimer"]

    decision = decide_scope_gate(
        _all_required_met(), _config(scope_authorization=authorization)
    )
    assert decision.full_spectrum_status in {"BLOCKED_CONFIG", "UNVERIFIED"}
    assert decision.governance_state == "NONE_VALIDATED"
    _assert_safe_disclaimer(decision)
    _assert_nothing_validated(decision)


def test_empty_thresholds_are_descriptive_and_unverified() -> None:
    decision = decide_scope_gate(
        _partial_metrics(), _config(oracle_thresholds={})
    )

    assert decision.full_spectrum_status == "UNVERIFIED"
    assert decision.scopes
    assert all(
        verdict.metric_status == "NO_THRESHOLD"
        and verdict.scope_status == "DESCRIPTIVE"
        for verdict in decision.scopes.values()
    )
    _assert_nothing_validated(decision)


def test_zero_minimum_count_fails_closed() -> None:
    decision = decide_scope_gate(
        _all_required_met(), _config(min_count_per_class=0)
    )

    assert decision.full_spectrum_status in {"BLOCKED_CONFIG", "UNVERIFIED"}
    _assert_nothing_validated(decision)


def test_missing_required_metrics_cannot_validate_or_authorize() -> None:
    decision = decide_scope_gate(
        {"missense": _all_required_met()["missense"]}, _config()
    )
    verdict = decision.scopes["truncating:pathogenic"]

    assert verdict.metric_status == "UNMET"
    assert verdict.coverage_adequate is False
    assert verdict.scope_status != "VALIDATED"
    assert decision.full_spectrum_vus_authorized is False
    assert decision.research_scope_flags[
        "truncating_pathogenic_research_scope_validated"
    ] is False
