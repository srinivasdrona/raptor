from __future__ import annotations

import copy
from typing import Any

import pytest

from tests.eval._clinvar_2026_08_prospective_red_helpers import require_api, require_exception


REQUIRED_SCOPES = ("missense:pathogenic", "missense:benign", "truncating:pathogenic")
NARROW_SCOPE = "truncating:pathogenic"


def _scope(
    *,
    actual_count: int,
    called_count: int,
    correct_calls: int,
    min_count: int,
    data_sufficiency: str,
    conditional_performance: str,
    policy_parity: str,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "actual_count": actual_count,
        "called_count": called_count,
        "correct_calls": correct_calls,
        "min_count": min_count,
        "data_sufficiency": data_sufficiency,
        "conditional_performance": conditional_performance,
        "policy_parity": policy_parity,
        "reasons": list(reasons or []),
    }


def _base_scopes() -> dict[str, dict[str, Any]]:
    return {
        "missense:pathogenic": _scope(
            actual_count=40,
            called_count=40,
            correct_calls=40,
            min_count=36,
            data_sufficiency="ADEQUATE",
            conditional_performance="MET",
            policy_parity="CLEAR",
            reasons=["missense_pathogenic_met"],
        ),
        "missense:benign": _scope(
            actual_count=50,
            called_count=50,
            correct_calls=50,
            min_count=36,
            data_sufficiency="ADEQUATE",
            conditional_performance="MET",
            policy_parity="CLEAR",
            reasons=["missense_benign_met"],
        ),
        "truncating:pathogenic": _scope(
            actual_count=60,
            called_count=60,
            correct_calls=60,
            min_count=36,
            data_sufficiency="ADEQUATE",
            conditional_performance="MET",
            policy_parity="CLEAR",
            reasons=["truncating_pathogenic_met"],
        ),
    }


def _adjudicate(
    *,
    run_integrity: str = "PASS",
    stage12_outcome: str | None = None,
    scopes: dict[str, dict[str, Any]] | None = None,
    cli_overrides: dict[str, Any] | None = None,
    env_overrides: dict[str, str] | None = None,
    transport_metadata_not_content_identity: bool = True,
) -> dict[str, Any]:
    fn = require_api("adjudicate_prospective_outcomes")
    result = fn(
        run_integrity=run_integrity,
        stage12_outcome=stage12_outcome,
        scopes=copy.deepcopy(scopes or _base_scopes()),
        required_scopes=list(REQUIRED_SCOPES),
        narrow_scope=NARROW_SCOPE,
        cli_overrides=cli_overrides or {},
        env_overrides=env_overrides or {},
        transport_metadata_not_content_identity=transport_metadata_not_content_identity,
    )
    if not isinstance(result, dict):
        pytest.fail("adjudicate_prospective_outcomes must return a mapping")
    return result


def _require_adjudication_contract() -> None:
    require_api("adjudicate_prospective_outcomes")
    require_api("TERMINAL_OUTCOME_VOCAB")
    require_api("A5_PRECEDENCE")
    require_api("FULL_SPECTRUM_PRECEDENCE")
    require_exception("ProspectiveInvalidStateError")
    assert set(require_api("TERMINAL_OUTCOME_VOCAB")) == {
        "PASS",
        "FAIL",
        "NOT_ESTIMABLE",
        "BLOCKED_POLICY",
        "BLOCKED_DATA",
        "INVALID",
    }
    assert list(require_api("A5_PRECEDENCE")) == [
        "INVALID",
        "NOT_APPLICABLE",
        "NO_CALLS",
        "UNDERPOWERED",
        "BLOCKED_POLICY",
        "NOT_SUPPORTED",
        "VALIDATED_PROSPECTIVE",
    ]
    assert list(require_api("FULL_SPECTRUM_PRECEDENCE")) == [
        "BLOCKED_DATA",
        "INVALID",
        "BLOCKED_POLICY",
        "FAIL",
        "NOT_ESTIMABLE",
        "PASS",
    ]


def test_adjudication_contract_symbols_exist() -> None:
    _require_adjudication_contract()


def test_a0_to_a6_exact_values_a4_calculation_and_reason_preservation() -> None:
    _require_adjudication_contract()
    scopes = {
        "missense:pathogenic": _scope(
            actual_count=40,
            called_count=35,
            correct_calls=30,
            min_count=36,
            data_sufficiency="ADEQUATE",
            conditional_performance="UNMET",
            policy_parity="CLEAR",
            reasons=["precision_lb_below_registered_threshold"],
        ),
        "missense:benign": _scope(
            actual_count=25,
            called_count=0,
            correct_calls=0,
            min_count=36,
            data_sufficiency="NO_CALLS",
            conditional_performance="NOT_ESTIMABLE",
            policy_parity="BLOCKED",
            reasons=["no_callable_predictions"],
        ),
        "truncating:pathogenic": _scope(
            actual_count=60,
            called_count=60,
            correct_calls=58,
            min_count=36,
            data_sufficiency="ADEQUATE",
            conditional_performance="MET",
            policy_parity="CLEAR",
            reasons=["registered_thresholds_met"],
        ),
    }
    result = _adjudicate(scopes=scopes)

    mp = result["scopes"]["missense:pathogenic"]
    assert mp["A0"] == "PASS"
    assert mp["A1"] == "ADEQUATE"
    assert mp["A2"] == "UNMET"
    assert mp["A3"] == "CLEAR"
    assert mp["A4"] == "30/40"
    assert mp["A5"] == "NOT_SUPPORTED"
    assert mp["A6"] == "NOT_AUTHORIZED"
    assert "precision_lb_below_registered_threshold" in mp["reasons"]

    mb = result["scopes"]["missense:benign"]
    assert mb["A0"] == "PASS"
    assert mb["A1"] == "NO_CALLS"
    assert mb["A2"] == "NOT_ESTIMABLE"
    assert mb["A3"] == "BLOCKED"
    assert mb["A4"] == "0/25"
    assert mb["A5"] == "NO_CALLS"
    assert mb["A6"] == "NOT_AUTHORIZED"
    assert "no_callable_predictions" in mb["reasons"]

    tp = result["scopes"]["truncating:pathogenic"]
    assert tp["A0"] == "PASS"
    assert tp["A1"] == "ADEQUATE"
    assert tp["A2"] == "MET"
    assert tp["A3"] == "CLEAR"
    assert tp["A4"] == "58/60"
    assert tp["A5"] == "VALIDATED_PROSPECTIVE"
    assert tp["A6"] == "AUTHORIZED_RESEARCH_ONLY"
    assert "registered_thresholds_met" in tp["reasons"]


@pytest.mark.parametrize(
    ("run_integrity", "scope_payload", "expected_a5"),
    (
        ("INVALID", _scope(actual_count=1, called_count=1, correct_calls=1, min_count=36, data_sufficiency="ADEQUATE", conditional_performance="MET", policy_parity="CLEAR"), "INVALID"),
        ("PASS", _scope(actual_count=5, called_count=0, correct_calls=0, min_count=36, data_sufficiency="NO_CALLS", conditional_performance="NOT_APPLICABLE", policy_parity="BLOCKED"), "NOT_APPLICABLE"),
        ("PASS", _scope(actual_count=5, called_count=0, correct_calls=0, min_count=36, data_sufficiency="NO_CALLS", conditional_performance="NOT_ESTIMABLE", policy_parity="BLOCKED"), "NO_CALLS"),
        ("PASS", _scope(actual_count=20, called_count=10, correct_calls=9, min_count=36, data_sufficiency="UNDERPOWERED", conditional_performance="NOT_ESTIMABLE", policy_parity="BLOCKED"), "UNDERPOWERED"),
        ("PASS", _scope(actual_count=40, called_count=40, correct_calls=39, min_count=36, data_sufficiency="ADEQUATE", conditional_performance="MET", policy_parity="BLOCKED"), "BLOCKED_POLICY"),
        ("PASS", _scope(actual_count=40, called_count=40, correct_calls=20, min_count=36, data_sufficiency="ADEQUATE", conditional_performance="UNMET", policy_parity="CLEAR"), "NOT_SUPPORTED"),
        ("PASS", _scope(actual_count=40, called_count=40, correct_calls=40, min_count=36, data_sufficiency="ADEQUATE", conditional_performance="MET", policy_parity="CLEAR"), "VALIDATED_PROSPECTIVE"),
    ),
)
def test_a5_precedence_parameterized(
    run_integrity: str,
    scope_payload: dict[str, Any],
    expected_a5: str,
) -> None:
    _require_adjudication_contract()
    scopes = _base_scopes()
    scopes["missense:pathogenic"] = scope_payload
    result = _adjudicate(run_integrity=run_integrity, scopes=scopes)
    assert result["scopes"]["missense:pathogenic"]["A5"] == expected_a5


@pytest.mark.parametrize(
    ("case_id", "kwargs", "expected_terminal", "expected_status", "expected_auth"),
    (
        ("blocked-data", {"stage12_outcome": "BLOCKED_DATA"}, "BLOCKED_DATA", "NOT_VALIDATED", "NOT_AUTHORIZED"),
        ("invalid", {"run_integrity": "INVALID"}, "INVALID", "INVALID", "NOT_AUTHORIZED"),
        (
            "blocked-policy",
            {
                "scopes": {
                    **_base_scopes(),
                    "missense:pathogenic": _scope(
                        actual_count=40,
                        called_count=40,
                        correct_calls=40,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="MET",
                        policy_parity="BLOCKED",
                        reasons=["policy_block"],
                    ),
                }
            },
            "BLOCKED_POLICY",
            "BLOCKED_POLICY",
            "NOT_AUTHORIZED",
        ),
        (
            "fail",
            {
                "scopes": {
                    **_base_scopes(),
                    "missense:pathogenic": _scope(
                        actual_count=40,
                        called_count=40,
                        correct_calls=18,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="UNMET",
                        policy_parity="CLEAR",
                        reasons=["unmet_lb"],
                    ),
                }
            },
            "FAIL",
            "NOT_VALIDATED",
            "NOT_AUTHORIZED",
        ),
        (
            "not-estimable",
            {
                "scopes": {
                    **_base_scopes(),
                    "missense:pathogenic": _scope(
                        actual_count=20,
                        called_count=10,
                        correct_calls=9,
                        min_count=36,
                        data_sufficiency="UNDERPOWERED",
                        conditional_performance="NOT_ESTIMABLE",
                        policy_parity="CLEAR",
                        reasons=["underpowered"],
                    ),
                }
            },
            "NOT_ESTIMABLE",
            "NOT_VALIDATED",
            "NOT_AUTHORIZED",
        ),
        ("pass", {"scopes": _base_scopes()}, "PASS", "VALIDATED_PROSPECTIVE", "AUTHORIZED_RESEARCH_ONLY"),
    ),
)
def test_terminal_outcome_maps_to_exact_status_and_authorization(
    case_id: str,
    kwargs: dict[str, Any],
    expected_terminal: str,
    expected_status: str,
    expected_auth: str,
) -> None:
    _require_adjudication_contract()
    result = _adjudicate(**kwargs)
    assert result["full_spectrum_terminal_outcome"] == expected_terminal
    assert result["full_spectrum_status"] == expected_status
    assert result["full_spectrum_authorization"] == expected_auth
    if expected_terminal != "PASS":
        assert result["full_spectrum_authorization"] == "NOT_AUTHORIZED"


@pytest.mark.parametrize(
    ("case_id", "kwargs", "expected_terminal"),
    (
        ("blocked_data_over_invalid", {"stage12_outcome": "BLOCKED_DATA", "run_integrity": "INVALID"}, "BLOCKED_DATA"),
        (
            "invalid_over_blocked_policy",
            {
                "run_integrity": "INVALID",
                "scopes": {
                    **_base_scopes(),
                    "missense:pathogenic": _scope(
                        actual_count=40,
                        called_count=40,
                        correct_calls=40,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="MET",
                        policy_parity="BLOCKED",
                    ),
                },
            },
            "INVALID",
        ),
        (
            "blocked_policy_over_fail",
            {
                "scopes": {
                    "missense:pathogenic": _scope(
                        actual_count=40,
                        called_count=40,
                        correct_calls=40,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="MET",
                        policy_parity="BLOCKED",
                    ),
                    "missense:benign": _scope(
                        actual_count=50,
                        called_count=50,
                        correct_calls=10,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="UNMET",
                        policy_parity="CLEAR",
                    ),
                    "truncating:pathogenic": _scope(
                        actual_count=60,
                        called_count=60,
                        correct_calls=60,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="MET",
                        policy_parity="CLEAR",
                    ),
                }
            },
            "BLOCKED_POLICY",
        ),
        (
            "fail_over_not_estimable",
            {
                "scopes": {
                    "missense:pathogenic": _scope(
                        actual_count=40,
                        called_count=40,
                        correct_calls=10,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="UNMET",
                        policy_parity="CLEAR",
                    ),
                    "missense:benign": _scope(
                        actual_count=20,
                        called_count=10,
                        correct_calls=9,
                        min_count=36,
                        data_sufficiency="UNDERPOWERED",
                        conditional_performance="NOT_ESTIMABLE",
                        policy_parity="CLEAR",
                    ),
                    "truncating:pathogenic": _scope(
                        actual_count=60,
                        called_count=60,
                        correct_calls=60,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="MET",
                        policy_parity="CLEAR",
                    ),
                }
            },
            "FAIL",
        ),
        (
            "not_estimable_over_pass",
            {
                "scopes": {
                    "missense:pathogenic": _scope(
                        actual_count=20,
                        called_count=10,
                        correct_calls=9,
                        min_count=36,
                        data_sufficiency="UNDERPOWERED",
                        conditional_performance="NOT_ESTIMABLE",
                        policy_parity="CLEAR",
                    ),
                    "missense:benign": _scope(
                        actual_count=50,
                        called_count=50,
                        correct_calls=50,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="MET",
                        policy_parity="CLEAR",
                    ),
                    "truncating:pathogenic": _scope(
                        actual_count=60,
                        called_count=60,
                        correct_calls=60,
                        min_count=36,
                        data_sufficiency="ADEQUATE",
                        conditional_performance="MET",
                        policy_parity="CLEAR",
                    ),
                }
            },
            "NOT_ESTIMABLE",
        ),
    ),
)
def test_adjacent_terminal_precedence_cases(case_id: str, kwargs: dict[str, Any], expected_terminal: str) -> None:
    _require_adjudication_contract()
    result = _adjudicate(**kwargs)
    assert result["full_spectrum_terminal_outcome"] == expected_terminal


@pytest.mark.parametrize(
    ("case_id", "blocked_scope"),
    (
        (
            "no-calls-not-applicable",
            _scope(
                actual_count=5,
                called_count=0,
                correct_calls=0,
                min_count=36,
                data_sufficiency="NO_CALLS",
                conditional_performance="NOT_APPLICABLE",
                policy_parity="BLOCKED",
                reasons=["policy_block_even_without_calls"],
            ),
        ),
        (
            "underpowered-not-estimable",
            _scope(
                actual_count=20,
                called_count=10,
                correct_calls=9,
                min_count=36,
                data_sufficiency="UNDERPOWERED",
                conditional_performance="NOT_ESTIMABLE",
                policy_parity="BLOCKED",
                reasons=["policy_block_even_when_underpowered"],
            ),
        ),
    ),
)
def test_a3_blocked_forces_full_spectrum_blocked_policy_even_when_a1_or_a2_not_decisive(
    case_id: str,
    blocked_scope: dict[str, Any],
) -> None:
    _require_adjudication_contract()
    scopes = _base_scopes()
    scopes["missense:pathogenic"] = blocked_scope
    result = _adjudicate(run_integrity="PASS", scopes=scopes)
    assert result["full_spectrum_terminal_outcome"] == "BLOCKED_POLICY"
    assert result["full_spectrum_status"] == "BLOCKED_POLICY"
    assert result["full_spectrum_authorization"] == "NOT_AUTHORIZED"


@pytest.mark.parametrize(
    ("case_id", "narrow_blocked_scope"),
    (
        (
            "narrow-no-calls",
            _scope(
                actual_count=5,
                called_count=0,
                correct_calls=0,
                min_count=36,
                data_sufficiency="NO_CALLS",
                conditional_performance="NOT_APPLICABLE",
                policy_parity="BLOCKED",
                reasons=["narrow_policy_block_no_calls"],
            ),
        ),
        (
            "narrow-underpowered",
            _scope(
                actual_count=20,
                called_count=10,
                correct_calls=8,
                min_count=36,
                data_sufficiency="UNDERPOWERED",
                conditional_performance="NOT_ESTIMABLE",
                policy_parity="BLOCKED",
                reasons=["narrow_policy_block_underpowered"],
            ),
        ),
    ),
)
def test_a3_blocked_forces_narrow_scope_blocked_policy_even_when_not_estimable_by_calls(
    case_id: str,
    narrow_blocked_scope: dict[str, Any],
) -> None:
    _require_adjudication_contract()
    scopes = _base_scopes()
    scopes[NARROW_SCOPE] = narrow_blocked_scope
    result = _adjudicate(run_integrity="PASS", scopes=scopes)
    assert result["full_spectrum_terminal_outcome"] == "BLOCKED_POLICY"
    assert result["narrow_scope"]["scope"] == NARROW_SCOPE
    assert result["narrow_scope"]["terminal_outcome"] == "BLOCKED_POLICY"
    assert result["narrow_scope"]["authorization_status"] == "NOT_AUTHORIZED"


def test_full_spectrum_blocked_policy_and_narrow_scope_independence() -> None:
    _require_adjudication_contract()
    result = _adjudicate(
        scopes={
            "missense:pathogenic": _scope(
                actual_count=40,
                called_count=40,
                correct_calls=40,
                min_count=36,
                data_sufficiency="ADEQUATE",
                conditional_performance="MET",
                policy_parity="BLOCKED",
                reasons=["policy_block"],
            ),
            "missense:benign": _scope(
                actual_count=50,
                called_count=50,
                correct_calls=20,
                min_count=36,
                data_sufficiency="ADEQUATE",
                conditional_performance="UNMET",
                policy_parity="CLEAR",
                reasons=["fail_lb"],
            ),
            "truncating:pathogenic": _scope(
                actual_count=60,
                called_count=60,
                correct_calls=60,
                min_count=36,
                data_sufficiency="ADEQUATE",
                conditional_performance="MET",
                policy_parity="CLEAR",
                reasons=["tp_pass"],
            ),
        }
    )
    assert result["full_spectrum_terminal_outcome"] == "BLOCKED_POLICY"
    assert result["full_spectrum_authorization"] == "NOT_AUTHORIZED"
    assert result["narrow_scope"]["scope"] == NARROW_SCOPE
    assert result["narrow_scope"]["terminal_outcome"] == "PASS"
    assert result["narrow_scope"]["authorization_status"] == "AUTHORIZED_RESEARCH_ONLY"
    assert "tp_pass" in result["scopes"][NARROW_SCOPE]["reasons"]


def test_blocked_data_or_invalid_globally_forces_narrow_scope_not_authorized() -> None:
    _require_adjudication_contract()
    blocked = _adjudicate(stage12_outcome="BLOCKED_DATA")
    invalid = _adjudicate(run_integrity="INVALID")
    assert blocked["narrow_scope"]["authorization_status"] == "NOT_AUTHORIZED"
    assert invalid["narrow_scope"]["authorization_status"] == "NOT_AUTHORIZED"


def test_override_inputs_or_missing_metadata_note_are_typed_invalid() -> None:
    _require_adjudication_contract()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with pytest.raises(invalid_error) as exc_override:
        _adjudicate(
            cli_overrides={"labels_snapshot": "override"},
            env_overrides={"RAPTOR_LABELS_SNAPSHOT_OVERRIDE": "override"},
        )
    assert getattr(exc_override.value, "code", None) == "INVALID"

    with pytest.raises(invalid_error) as exc_note:
        _adjudicate(transport_metadata_not_content_identity=False)
    assert getattr(exc_note.value, "code", None) == "INVALID"


def test_missing_axis_or_unknown_axis_value_is_typed_invalid() -> None:
    _require_adjudication_contract()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    missing_axis = _base_scopes()
    del missing_axis["missense:pathogenic"]["policy_parity"]
    with pytest.raises(invalid_error) as exc_missing:
        _adjudicate(scopes=missing_axis)
    assert getattr(exc_missing.value, "code", None) == "INVALID"

    unknown_axis = _base_scopes()
    unknown_axis["missense:pathogenic"]["data_sufficiency"] = "MAYBE"
    with pytest.raises(invalid_error) as exc_unknown:
        _adjudicate(scopes=unknown_axis)
    assert getattr(exc_unknown.value, "code", None) == "INVALID"
