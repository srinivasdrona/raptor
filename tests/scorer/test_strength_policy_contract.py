from __future__ import annotations

from copy import deepcopy
import dataclasses
from pathlib import Path
from typing import Any

import pytest
import yaml

try:
    from raptor.scorer.strength_policy import (
        StrengthLadder,
        StrengthLadderError,
        StrengthPolicy,
        StrengthPolicyDecision,
        StrengthPolicyError,
        UnknownStrengthPolicyPairError,
        apply_strength_policy,
        load_strength_ladder,
        load_strength_policy,
    )
except ImportError:
    StrengthLadder = None
    StrengthPolicy = None
    StrengthPolicyDecision = None
    StrengthLadderError = ValueError
    StrengthPolicyError = ValueError
    UnknownStrengthPolicyPairError = KeyError
    apply_strength_policy = None
    load_strength_ladder = None
    load_strength_policy = None


PINNED_BIAS_VERSION = "3.0.0"
PINNED_BIAS_COMMIT = "ade13f206f3e2c2efe3ec92715d974645fc8da8f"

SCORER_VOCAB = {
    "PS1": ("strong",),
    "PM2": ("supporting", "moderate"),
    "PM4": ("moderate",),
    "PM5": ("moderate", "strong"),
    "BP3": ("supporting",),
    "BP4": ("supporting",),
    "BS1": ("moderate", "strong"),
}

PLANNED_LADDER = {
    "PS1": ["moderate"],
    "PM2": ["supporting", "moderate", "strong"],
    "PM4": ["supporting", "moderate", "strong"],
    "PM5": ["supporting", "moderate"],
    "BP3": ["strong"],
    "BP4": ["supporting", "strong"],
    "BS1": ["strong"],
}

PLANNED_OUTCOMES = (
    ("PS1", "moderate", "manual", None),
    ("PM2", "supporting", "accept", "supporting"),
    ("PM2", "moderate", "accept", "moderate"),
    ("PM2", "strong", "cap", "moderate"),
    ("PM4", "supporting", "manual", None),
    ("PM4", "moderate", "accept", "moderate"),
    ("PM4", "strong", "cap", "moderate"),
    ("PM5", "supporting", "manual", None),
    ("PM5", "moderate", "accept", "moderate"),
    ("BP3", "strong", "cap", "supporting"),
    ("BP4", "supporting", "accept", "supporting"),
    ("BP4", "strong", "cap", "supporting"),
    ("BS1", "strong", "accept", "strong"),
)


def _require_api() -> None:
    if (
        StrengthLadder is None
        or StrengthPolicy is None
        or StrengthPolicyDecision is None
        or load_strength_ladder is None
        or load_strength_policy is None
        or apply_strength_policy is None
    ):
        pytest.fail("raptor.scorer.strength_policy public API is not implemented")


def _write_yaml(tmp_path: Path, name: str, raw: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _ladder_dict() -> dict[str, Any]:
    return {
        "schema": "bias-strength-ladder",
        "bias_version": PINNED_BIAS_VERSION,
        "bias_commit": PINNED_BIAS_COMMIT,
        "criteria": deepcopy(PLANNED_LADDER),
    }


def _policy_dict(*, status: str = "approved", owner_approved: bool = True) -> dict[str, Any]:
    return {
        "schema": "acmg-strength-policy",
        "policy_id": "synthetic-strength-policy",
        "version": "1",
        "status": status,
        "owner_approved": owner_approved,
        "default_disposition": "manual",
        "records": {
            "PS1": {
                "moderate": {"disposition": "manual"},
            },
            "PM2": {
                "supporting": {"disposition": "accept", "emit": "supporting"},
                "moderate": {"disposition": "accept", "emit": "moderate"},
                "strong": {"disposition": "cap", "emit": "moderate"},
            },
            "PM4": {
                "supporting": {"disposition": "manual"},
                "moderate": {"disposition": "accept", "emit": "moderate"},
                "strong": {"disposition": "cap", "emit": "moderate"},
            },
            "PM5": {
                "supporting": {"disposition": "manual"},
                "moderate": {"disposition": "accept", "emit": "moderate"},
            },
            "BP3": {
                "strong": {"disposition": "cap", "emit": "supporting"},
            },
            "BP4": {
                "supporting": {"disposition": "accept", "emit": "supporting"},
                "strong": {"disposition": "cap", "emit": "supporting"},
            },
            "BS1": {
                "strong": {"disposition": "accept", "emit": "strong"},
            },
        },
        "gene_overrides": {
            "TSC1": {
                "BS1": {
                    "strong": {"disposition": "forbid"},
                }
            }
        },
    }


def _load_valid_policy(tmp_path: Path, *, status: str = "approved", owner_approved: bool = True):
    _require_api()
    ladder = load_strength_ladder(_write_yaml(tmp_path, "ladder.yaml", _ladder_dict()))
    policy = load_strength_policy(
        _write_yaml(tmp_path, "policy.yaml", _policy_dict(status=status, owner_approved=owner_approved)),
        ladder=ladder,
        scorer_strength_vocab=SCORER_VOCAB,
    )
    assert isinstance(ladder, StrengthLadder)
    assert isinstance(policy, StrengthPolicy)
    return ladder, policy


def _direction_for(criterion: str) -> str:
    return "benign" if criterion.startswith("B") else "pathogenic"


def _call(criterion: str, strength: str) -> dict[str, str]:
    return {
        "criterion": criterion,
        "strength": strength,
        "direction": _direction_for(criterion),
        "rationale": f"{criterion}_{strength}",
    }


def _record(*calls: dict[str, str], gene: str = "TSC2") -> dict[str, Any]:
    return {
        "variant_id": "chr16:100:A:T",
        "gene_name": gene,
        "calls": list(calls),
    }


def _eval_surface(surface: dict[str, Any]) -> tuple[Any, ...]:
    if surface["disposition"] in {"accept", "cap"}:
        emitted = surface["emitted_call"]
        return (
            "emit",
            emitted["criterion"],
            emitted["strength"],
            emitted["direction"],
            surface["audit"]["policy_id"],
        )
    if surface["disposition"] == "manual":
        return (
            "manual",
            surface["manual_record"]["variant_id"],
            surface["criterion"],
            surface["requested_strength"],
            surface["audit"]["policy_id"],
        )
    return (
        "drop",
        surface["criterion"],
        surface["requested_strength"],
        surface["audit"]["policy_id"],
    )


def _production_surface(surface: dict[str, Any]) -> tuple[Any, ...]:
    if surface["emitted_call"] is not None:
        emitted = surface["emitted_call"]
        return (
            "emit",
            emitted.get("criterion"),
            emitted.get("strength"),
            emitted.get("direction"),
            surface["audit"].get("policy_id"),
        )
    if surface["manual_record"] is not None:
        return (
            "manual",
            surface["manual_record"].get("variant_id"),
            surface["criterion"],
            surface["requested_strength"],
            surface["audit"].get("policy_id"),
        )
    return (
        "drop",
        surface["criterion"],
        surface["requested_strength"],
        surface["audit"].get("policy_id"),
    )


@pytest.mark.parametrize(
    ("target", "mutation", "expected_error"),
    [
        ("ladder", lambda raw: raw.__setitem__("schema", "not-the-ladder"), StrengthLadderError),
        ("ladder", lambda raw: raw.__setitem__("unexpected", True), StrengthLadderError),
        ("policy", lambda raw: raw.__setitem__("schema", "not-acmg-strength-policy"), StrengthPolicyError),
        ("policy", lambda raw: raw.__setitem__("unexpected", True), StrengthPolicyError),
        ("policy", lambda raw: raw.__setitem__("status", "pending"), StrengthPolicyError),
        (
            "policy",
            lambda raw: raw["records"]["PM2"]["supporting"].__setitem__("disposition", "route-somewhere"),
            StrengthPolicyError,
        ),
        ("policy", lambda raw: raw.__setitem__("default_disposition", "accept"), StrengthPolicyError),
    ],
    ids=[
        "ladder-wrong-schema",
        "ladder-unknown-field",
        "policy-wrong-schema",
        "policy-unknown-field",
        "policy-bad-status",
        "policy-bad-disposition",
        "policy-default-accept",
    ],
)
def test_strength_policy_rejects_wrong_schema_unknown_fields_bad_enums_and_default_accept(
    tmp_path: Path,
    target: str,
    mutation,
    expected_error,
) -> None:
    _require_api()
    ladder_raw = _ladder_dict()
    policy_raw = _policy_dict()

    if target == "ladder":
        mutation(ladder_raw)
        with pytest.raises(expected_error):
            load_strength_ladder(_write_yaml(tmp_path, "ladder.yaml", ladder_raw))
        return

    ladder = load_strength_ladder(_write_yaml(tmp_path, "ladder.yaml", ladder_raw))
    mutation(policy_raw)
    with pytest.raises(expected_error):
        load_strength_policy(
            _write_yaml(tmp_path, "policy.yaml", policy_raw),
            ladder=ladder,
            scorer_strength_vocab=SCORER_VOCAB,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw["records"]["PM2"].pop("strong"),
        lambda raw: raw["records"]["BS1"].update(
            {"moderate": {"disposition": "accept", "emit": "moderate"}}
        ),
    ],
    ids=["missing-ladder-strength", "extra-ladder-strength"],
)
def test_strength_policy_rejects_missing_or_extra_emitted_strengths_relative_to_ladder(
    tmp_path: Path, mutation
) -> None:
    _require_api()
    ladder = load_strength_ladder(_write_yaml(tmp_path, "ladder.yaml", _ladder_dict()))
    policy_raw = _policy_dict()
    mutation(policy_raw)

    with pytest.raises(StrengthPolicyError):
        load_strength_policy(
            _write_yaml(tmp_path, "policy.yaml", policy_raw),
            ladder=ladder,
            scorer_strength_vocab=SCORER_VOCAB,
        )


@pytest.mark.parametrize(
    ("criterion", "strength", "expected_disposition", "expected_emit"),
    PLANNED_OUTCOMES,
    ids=[f"{criterion}-{strength}" for criterion, strength, _, _ in PLANNED_OUTCOMES],
)
def test_apply_strength_policy_handles_every_planned_ladder_strength(
    tmp_path: Path,
    criterion: str,
    strength: str,
    expected_disposition: str,
    expected_emit: str | None,
) -> None:
    _, policy = _load_valid_policy(tmp_path)
    call = _call(criterion, strength)
    record = _record(call)

    decision = apply_strength_policy(record=record, call=call, policy=policy)

    assert isinstance(decision, StrengthPolicyDecision)
    assert decision.disposition == expected_disposition
    assert decision.criterion == criterion
    assert decision.requested_strength == strength
    assert decision.audit["criterion"] == criterion
    assert decision.audit["requested_strength"] == strength
    if expected_emit is None:
        assert decision.emitted_call is None
        assert decision.manual_record == record
    else:
        assert decision.manual_record is None
        assert decision.emitted_call == {
            **call,
            "strength": expected_emit,
        }
        assert decision.audit["emitted_strength"] == expected_emit


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw["records"]["PM4"].__setitem__(
            "supporting", {"disposition": "cap", "emit": "moderate"}
        ),
        lambda raw: raw["records"]["PM2"].__setitem__(
            "strong", {"disposition": "accept", "emit": "strong"}
        ),
        lambda raw: raw["records"]["BP4"].__setitem__(
            "strong", {"disposition": "cap", "emit": "moderate"}
        ),
    ],
    ids=["cap-inflates", "accept-outside-vocab", "cap-target-outside-vocab"],
)
def test_strength_policy_rejects_invalid_cap_and_emit_targets(
    tmp_path: Path, mutation
) -> None:
    _require_api()
    ladder = load_strength_ladder(_write_yaml(tmp_path, "ladder.yaml", _ladder_dict()))
    policy_raw = _policy_dict()
    mutation(policy_raw)

    with pytest.raises(StrengthPolicyError):
        load_strength_policy(
            _write_yaml(tmp_path, "policy.yaml", policy_raw),
            ladder=ladder,
            scorer_strength_vocab=SCORER_VOCAB,
        )


@pytest.mark.parametrize(
    ("status", "owner_approved"),
    [("unapproved", True), ("approved", False)],
    ids=["status-unapproved", "owner-approval-false"],
)
def test_unapproved_policy_or_owner_approval_false_fail_closed_to_manual(
    tmp_path: Path, status: str, owner_approved: bool
) -> None:
    _, policy = _load_valid_policy(tmp_path, status=status, owner_approved=owner_approved)
    call = _call("PM2", "supporting")
    record = _record(call)

    decision = apply_strength_policy(record=record, call=call, policy=policy)

    assert decision.disposition == "manual"
    assert decision.emitted_call is None
    assert decision.manual_record == record


def test_manual_forbid_cap_and_accept_preserve_deterministic_audited_calls(
    tmp_path: Path,
) -> None:
    _, policy = _load_valid_policy(tmp_path)

    manual_call = _call("PM5", "supporting")
    manual_record = _record(manual_call)
    manual_decision = apply_strength_policy(record=manual_record, call=manual_call, policy=policy)
    assert manual_decision.disposition == "manual"
    assert manual_decision.manual_record == manual_record
    assert manual_decision.emitted_call is None

    forbid_call = _call("BS1", "strong")
    keep_call = _call("PM2", "supporting")
    mixed_record = _record(forbid_call, keep_call, gene="TSC1")
    forbid_decision = apply_strength_policy(record=mixed_record, call=forbid_call, policy=policy)
    keep_decision = apply_strength_policy(record=mixed_record, call=keep_call, policy=policy)
    assert forbid_decision.disposition == "forbid"
    assert forbid_decision.manual_record is None
    assert forbid_decision.emitted_call is None
    assert keep_decision.disposition == "accept"
    assert keep_decision.emitted_call == keep_call

    cap_call = _call("BP4", "strong")
    cap_record = _record(cap_call)
    first = apply_strength_policy(record=cap_record, call=cap_call, policy=policy)
    second = apply_strength_policy(record=cap_record, call=deepcopy(cap_call), policy=policy)
    assert dataclasses.asdict(first) == dataclasses.asdict(second)


def test_unknown_strength_policy_pair_raises_without_default(tmp_path: Path) -> None:
    _, policy = _load_valid_policy(tmp_path)
    unknown_call = _call("PM2", "very_strong")

    with pytest.raises(UnknownStrengthPolicyPairError):
        apply_strength_policy(record=_record(unknown_call), call=unknown_call, policy=policy)


def test_strength_policy_rejects_gene_override_outside_tsc1_tsc2(tmp_path: Path) -> None:
    _require_api()
    ladder = load_strength_ladder(_write_yaml(tmp_path, "ladder.yaml", _ladder_dict()))
    policy_raw = _policy_dict()
    policy_raw["gene_overrides"]["NTHL1"] = {
        "PM2": {
            "supporting": {"disposition": "manual"},
        }
    }

    with pytest.raises(StrengthPolicyError):
        load_strength_policy(
            _write_yaml(tmp_path, "policy.yaml", policy_raw),
            ladder=ladder,
            scorer_strength_vocab=SCORER_VOCAB,
        )


@pytest.mark.parametrize(
    ("criterion", "strength", "gene"),
    [
        ("PM2", "strong", "TSC2"),
        ("PM5", "supporting", "TSC2"),
        ("BS1", "strong", "TSC1"),
    ],
    ids=["cap-surface", "manual-surface", "forbid-surface"],
)
def test_eval_and_production_can_consume_the_same_pure_policy_surface(
    tmp_path: Path, criterion: str, strength: str, gene: str
) -> None:
    _, policy = _load_valid_policy(tmp_path)
    call = _call(criterion, strength)
    decision = apply_strength_policy(record=_record(call, gene=gene), call=call, policy=policy)

    assert dataclasses.is_dataclass(decision)
    surface = dataclasses.asdict(decision)
    assert _eval_surface(surface) == _production_surface(surface)
