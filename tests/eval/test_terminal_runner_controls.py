from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_eval_config, Metrics
from raptor.eval.model import ScopeGateDecision
from scripts.run_masked_holdout_eval import (
    _require_verified_return_artifact,
    _verify_return_control_files,
    compute_report_scope_gate,
)
from test_scope_gate import make_v2_auth_config, make_oracle_thresholds


def test_return_controls_require_scored_status_and_manifest_bound_skip_list(
    tmp_path: Path,
) -> None:
    status = tmp_path / "TERMINAL_STATUS.txt"
    skip = tmp_path / "evaluation_skip_list.txt"
    status.write_text("SCORED_MASKED\n", encoding="utf-8")
    skip.write_text("PM1\nPS4\nPP5\nBP6\n", encoding="utf-8")
    verified = {status.name: "a" * 64, skip.name: "b" * 64}

    operational, evaluation = _verify_return_control_files(
        verified,
        tmp_path,
        automatable_criteria={"PM1", "PP3"},
        declared_skips={"PM1"},
    )
    assert operational == {"PM1", "PS4", "PP5", "BP6"}
    assert evaluation == {"PM1"}


def test_return_controls_reject_blocked_status_or_unattested_skip(tmp_path: Path) -> None:
    status = tmp_path / "TERMINAL_STATUS.txt"
    skip = tmp_path / "evaluation_skip_list.txt"
    status.write_text("BLOCKED_MASK_CONSERVATION\n", encoding="utf-8")
    skip.write_text("PM1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SCORED_MASKED"):
        _verify_return_control_files(
            {status.name: "a" * 64, skip.name: "b" * 64},
            tmp_path,
            automatable_criteria={"PM1"},
            declared_skips={"PM1"},
        )

    status.write_text("SCORED_MASKED\n", encoding="utf-8")
    with pytest.raises(ValueError, match="return manifest"):
        _verify_return_control_files(
            {status.name: "a" * 64},
            tmp_path,
            automatable_criteria={"PM1"},
            declared_skips={"PM1"},
        )


def test_return_controls_require_operator_skip_declaration(tmp_path: Path) -> None:
    status = tmp_path / "TERMINAL_STATUS.txt"
    skip = tmp_path / "evaluation_skip_list.txt"
    status.write_text("SCORED_MASKED\n", encoding="utf-8")
    skip.write_text("PM1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="declared skipped criteria"):
        _verify_return_control_files(
            {status.name: "a" * 64, skip.name: "b" * 64},
            tmp_path,
            automatable_criteria={"PM1"},
            declared_skips=set(),
        )


def test_consumed_scoring_artifact_must_be_the_manifest_bound_file(tmp_path: Path) -> None:
    artifact = tmp_path / "holdout.tsv"
    artifact.write_text("scored", encoding="utf-8")
    verified = {artifact.name: "a" * 64}
    _require_verified_return_artifact(verified, tmp_path, artifact, label="BIAS TSV")

    other = tmp_path / "other"
    other.mkdir()
    outside = other / artifact.name
    outside.write_text("different", encoding="utf-8")
    with pytest.raises(ValueError, match="verified return directory"):
        _require_verified_return_artifact(
            verified,
            tmp_path,
            outside,
            label="BIAS TSV",
        )


def test_compute_report_scope_gate_returns_none_when_scope_authorization_absent() -> None:
    """Finding 3: If scope_authorization is None/absent in the config,
    compute_report_scope_gate must return None to leave report.scope_gate as None,
    preserving v1-compatibility (preventing any change to content hash/render/envelope).
    """
    config = make_eval_config(scope_authorization=None)
    metrics = {
        "missense": Metrics(
            precision=1.0, recall=1.0, concordance=1.0,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="missense", gating=True, benign_precision=1.0, benign_recall=1.0
        )
    }

    result = compute_report_scope_gate(metrics, config)
    assert result is None


def test_compute_report_scope_gate_returns_decision_when_scope_authorization_present() -> None:
    """Finding 3: If scope_authorization is present in the config,
    compute_report_scope_gate must return a v2 ScopeGateDecision.
    """
    config = make_eval_config(
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
    metrics = {"truncating": m_truncating}

    result = compute_report_scope_gate(metrics, config)
    assert isinstance(result, ScopeGateDecision)
    assert result.research_scope_flags["truncating_pathogenic_research_scope_validated"] is True


def test_compute_report_scope_gate_applies_skipped_criteria_fail_closed() -> None:
    """Finding 3 (+ final scope-gate blocker): If there are skipped
    (evaluation exclusion) criteria, compute_report_scope_gate must
    fail-closed and return a BLOCKED_POLICY, most-restrictive decision if
    any research scope would otherwise have validated. `BLOCKED_POLICY`
    (not `UNVERIFIED`) explicitly reflects a non-statistical policy block
    (a production-parity break), mirroring the v1 gate's own
    `BLOCKED_POLICY` status -- `UNVERIFIED` stays reserved for a genuinely
    unset/empty `oracle_thresholds` config.
    """
    config = make_eval_config(
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
    metrics = {"truncating": m_truncating}

    # If skipped is non-empty, we should fail closed
    result = compute_report_scope_gate(metrics, config, skipped={"PM1"})
    assert isinstance(result, ScopeGateDecision)
    assert result.full_spectrum_status == "BLOCKED_POLICY"
    assert result.full_spectrum_vus_authorized is False
    assert result.research_scope_flags["truncating_pathogenic_research_scope_validated"] is False
    assert result.governance_state == "NONE_VALIDATED"
    assert "evaluation_skipped_criteria:PM1" in result.authorization_blockers


@pytest.mark.parametrize("hand_built_auth", [{}, [], False, ""])
def test_compute_report_scope_gate_hand_built_truthiness_does_not_return_none(
    hand_built_auth,
) -> None:
    """Finding 4: Hand-built config values like {}, [], False, "" must not downgrade to None
    but should instead go through decide_scope_gate and fail closed or return a blocked decision.
    """
    class MockConfig:
        scope_authorization = hand_built_auth
        min_count_per_class = 36
        oracle_thresholds = {}

    metrics = {}
    result = compute_report_scope_gate(metrics, MockConfig())

    assert result is not None
    assert isinstance(result, ScopeGateDecision)
    assert result.governance_state == "NONE_VALIDATED"


