import json
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

try:
    from raptor.eval.lineage_policy import load_lineage_policy, LineagePolicyError
except ImportError:
    load_lineage_policy = None
    LineagePolicyError = Exception

POLICY_PATH = Path("configs/eval/bias_lineage.yaml")

def test_ac_b4_bs2_deferred_with_rationale() -> None:
    if load_lineage_policy is None:
        pytest.fail("raptor.eval.lineage_policy is not implemented")
    if not POLICY_PATH.is_file():
        pytest.fail(f"{POLICY_PATH} is not implemented")

    policy = load_lineage_policy(POLICY_PATH)
    bs2_record = policy.records["BS2"]

    assert bs2_record.validation_disposition == "deferred"
    assert bs2_record.production_disposition == "deferred"
    assert bs2_record.decision_dependency == "bs2-policy"

    # Check decision_rationale exists and is non-empty
    assert hasattr(bs2_record, "decision_rationale"), "BS2 record lacks decision_rationale"
    assert bs2_record.decision_rationale, "BS2 record decision_rationale is empty"

    # Must mention penetrance, age, mosaicism
    rationale_lower = bs2_record.decision_rationale.lower()
    assert "penetrance" in rationale_lower
    assert "age" in rationale_lower
    assert "mosaicism" in rationale_lower
    ps3_record = policy.records["PS3"]
    assert ps3_record.validation_disposition == "deferred"
    assert ps3_record.decision_rationale

def test_ac_b4_strengthened_invariant(tmp_path: Path) -> None:
    if load_lineage_policy is None:
        pytest.fail("raptor.eval.lineage_policy is not implemented")

    raw = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))

    # Remove rationale from BS2
    raw["records"]["BS2"]["decision_rationale"] = ""

    mutated_path = tmp_path / "mutated_policy.yaml"
    mutated_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(LineagePolicyError, match="decision_rationale"):
        load_lineage_policy(mutated_path)

def test_ac_b5_bs2_not_included_in_automatable() -> None:
    acmg_path = Path("configs/acmg/tsc.yaml")
    tsc2_path = Path("configs/eval/tsc2.yaml")

    if not acmg_path.is_file() or not tsc2_path.is_file():
        pytest.fail("Config files missing")

    acmg_conf = yaml.safe_load(acmg_path.read_text(encoding="utf-8"))
    tsc2_conf = yaml.safe_load(tsc2_path.read_text(encoding="utf-8"))

    assert "BS2" not in acmg_conf["included_criteria"]
    assert "BS2" not in tsc2_conf["automatable_criteria"]

def test_ac_b5_bs2_trips_deferred_included() -> None:
    if load_lineage_policy is None:
        pytest.fail("raptor.eval.lineage_policy is not implemented")

    from raptor.eval.lineage_registry import assert_registry_consistency, LineageRegistryMismatchError

    policy = load_lineage_policy(POLICY_PATH)

    # Create mock configurations where BS2 is included
    class MockConfig:
        def __init__(self, included, acmg_criteria):
            self.included_criteria = included
            self.automatable_criteria = included
            self.acmg_criteria = acmg_criteria

    acmg_keys = {c: {} for c in policy.can_fire}
    # Create configs with BS2 included
    included = [c for c in policy.can_fire if c not in ("BS2", "PS3", "PS4", "PP5", "BP6")] + ["BS2"]

    mock_scorer = MockConfig(included, acmg_keys)
    mock_eval = MockConfig(included, acmg_keys)

    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(policy, mock_scorer, mock_eval)

    assert "deferred_included_without_decision" in exc.value.sets_by_kind
    assert "BS2" in exc.value.sets_by_kind["deferred_included_without_decision"]
