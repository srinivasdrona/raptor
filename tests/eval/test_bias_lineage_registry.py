from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

try:
    from raptor.eval.lineage_policy import load_lineage_policy
    from raptor.eval.lineage_registry import (
        LineageRegistryMismatchError,
        assert_registry_consistency,
    )
    from raptor.eval.config import load_config as load_eval_config
    from raptor.scorer.config import load_config as load_scorer_config
except ImportError:
    LineageRegistryMismatchError = Exception
    assert_registry_consistency = None
    load_eval_config = None
    load_lineage_policy = None
    load_scorer_config = None


POLICY_PATH = Path("configs/eval/bias_lineage.yaml")
SCORER_CONFIG_PATH = Path("configs/acmg/tsc.yaml")
EVAL_CONFIG_PATH = Path("configs/eval/tsc2.yaml")


def _configs():
    if assert_registry_consistency is None:
        pytest.fail("raptor.eval.lineage_registry is not implemented")
    if not POLICY_PATH.is_file():
        pytest.fail(f"{POLICY_PATH} is not implemented")
    return (
        load_lineage_policy(POLICY_PATH),
        load_scorer_config(SCORER_CONFIG_PATH),
        load_eval_config(EVAL_CONFIG_PATH),
    )


def _replace_included(scorer_config, eval_config, criteria):
    values = tuple(criteria)
    return (
        replace(scorer_config, included_criteria=values),
        replace(eval_config, automatable_criteria=values),
    )


def _assert_breach(exc, kind: str, criteria: set[str]) -> None:
    assert exc.value.sets_by_kind[kind] == criteria


def test_ac_l4_corrected_registry_and_intentional_subset_pass() -> None:
    policy, scorer_config, eval_config = _configs()

    assert set(scorer_config.acmg_criteria) == set(policy.can_fire)
    assert set(scorer_config.included_criteria) == set(eval_config.automatable_criteria)
    assert "BS3" not in scorer_config.included_criteria
    assert "BS4" not in scorer_config.included_criteria
    assert_registry_consistency(policy, scorer_config, eval_config)


def test_ac_l4_included_eval_parity_is_required() -> None:
    policy, scorer_config, eval_config = _configs()
    drifty_scorer = replace(
        scorer_config,
        included_criteria=tuple(scorer_config.included_criteria) + ("PVS1",),
    )

    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(policy, drifty_scorer, eval_config)
    assert "included_automatable_drift" in exc.value.sets_by_kind


def test_ac_l4_phantom_automation_is_structured_breach() -> None:
    policy, scorer_config, eval_config = _configs()
    included = tuple(scorer_config.included_criteria) + ("BS3", "BS4")
    drifty_scorer, drifty_eval = _replace_included(scorer_config, eval_config, included)

    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(policy, drifty_scorer, drifty_eval)
    _assert_breach(exc, "scored_not_can_fire", {"BS3", "BS4"})


def test_ac_l4_scorer_registry_must_equal_can_fire() -> None:
    policy, scorer_config, eval_config = _configs()
    drifty_registry = dict(scorer_config.acmg_criteria)
    drifty_registry.pop("PS3")
    drifty_registry["BS3"] = {
        "direction": "benign",
        "strength_vocab": ["strong"],
    }
    drifty_scorer = replace(scorer_config, acmg_criteria=drifty_registry)

    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(policy, drifty_scorer, eval_config)
    _assert_breach(exc, "registry_can_fire_drift", {"PS3", "BS3"})


def test_ac_l4_allowed_criterion_cannot_be_silently_omitted() -> None:
    policy, scorer_config, eval_config = _configs()
    included = tuple(c for c in scorer_config.included_criteria if c != "PVS1")
    drifty_scorer, drifty_eval = _replace_included(scorer_config, eval_config, included)

    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(policy, drifty_scorer, drifty_eval)
    _assert_breach(exc, "omitted_without_disposition", {"PVS1"})


def test_ac_l4_forbidden_and_transitive_sets_cannot_drift() -> None:
    policy, scorer_config, eval_config = _configs()
    ps4 = replace(
        policy.records["PS4"],
        validation_disposition="allowed",
        production_disposition="allowed",
    )
    forbidden_drift = replace(
        policy,
        records={**policy.records, "PS4": ps4},
    )
    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(forbidden_drift, scorer_config, eval_config)
    assert "forbidden_set_drift" in exc.value.sets_by_kind

    transitive_drift = replace(
        policy,
        transitive_suspect=tuple(
            criterion for criterion in policy.transitive_suspect if criterion != "BP1"
        ),
    )
    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(transitive_drift, scorer_config, eval_config)
    _assert_breach(exc, "transitive_set_drift", {"BP1"})


def test_ac_l13_bs2_is_deferred_intentional_omission() -> None:
    policy, scorer_config, eval_config = _configs()

    assert "BS2" not in scorer_config.included_criteria
    assert "BS2" not in eval_config.automatable_criteria
    assert policy.records["BS2"].decision_dependency == "bs2-policy"
    assert_registry_consistency(policy, scorer_config, eval_config)


def test_ac_l13_bs2_cannot_be_included_before_policy_decision() -> None:
    policy, scorer_config, eval_config = _configs()
    included = tuple(scorer_config.included_criteria) + ("BS2",)
    drifty_scorer, drifty_eval = _replace_included(scorer_config, eval_config, included)

    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(policy, drifty_scorer, drifty_eval)
    _assert_breach(exc, "deferred_included_without_decision", {"BS2"})
