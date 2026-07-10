from __future__ import annotations

import ast
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

try:
    from raptor.eval.lineage_policy import LineagePolicyError, load_lineage_policy
except ImportError:
    LineagePolicyError = Exception
    load_lineage_policy = None


POLICY_PATH = Path("configs/eval/bias_lineage.yaml")
FIXTURE_PATH = Path("tests/fixtures/bias_lineage_source_oracle.json")


def _require_implementation() -> None:
    if load_lineage_policy is None:
        pytest.fail("raptor.eval.lineage_policy is not implemented")
    if not POLICY_PATH.is_file():
        pytest.fail(f"{POLICY_PATH} is not implemented")
    if not FIXTURE_PATH.is_file():
        pytest.fail(f"{FIXTURE_PATH} is not implemented")


def _get_oracle() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _policy_dict() -> dict:
    _require_implementation()
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


def _write_policy(tmp_path: Path, raw: dict, name: str = "policy.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_ac_l1_static_can_fire_oracle() -> None:
    _require_implementation()
    policy = load_lineage_policy(POLICY_PATH)
    oracle = _get_oracle()

    expected_can_fire = {
        item["criterion"] for item in oracle["criteria"] if item["status"] == "can_fire"
    }

    assert set(policy.can_fire) == expected_can_fire


def test_ac_l2_exact_28_slot_partition() -> None:
    _require_implementation()
    policy = load_lineage_policy(POLICY_PATH)
    oracle = _get_oracle()

    expected_can_fire = {
        item["criterion"] for item in oracle["criteria"] if item["status"] == "can_fire"
    }
    expected_stubs = {
        item["criterion"] for item in oracle["criteria"] if item["status"] == "internal_stub"
    }
    expected_all = expected_can_fire | expected_stubs

    stub_codes = {entry.criterion for entry in policy.structurally_forbidden}

    assert set(policy.all_criteria) == expected_all
    assert stub_codes == expected_stubs
    assert set(policy.can_fire).isdisjoint(stub_codes)
    assert set(policy.can_fire) | stub_codes == set(policy.all_criteria)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw["records"]["PVS1"].update({"lineage_class": "not_a_lineage"}),
        lambda raw: raw["records"]["PVS1"].update({"validation_disposition": "not_a_disposition"}),
        lambda raw: raw["records"]["PVS1"].update({"production_disposition": "not_a_disposition"}),
        lambda raw: raw["records"]["PVS1"]["rationale_markers"].append("not-in-marker-vocabulary"),
        lambda raw: raw.update({"oracle_allowed": ["*"]}),
        lambda raw: raw["can_fire"].append("PVS1"),
        lambda raw: raw["records"].pop("PVS1"),
        lambda raw: (
            raw["records"].update({"ZZ99": deepcopy(raw["records"]["PVS1"])}),
            raw["can_fire"].append("ZZ99"),
            raw["all_criteria"].append("ZZ99"),
        ),
        lambda raw: raw["structurally_forbidden"].append(
            {"criterion": "PVS1", "reason": "overlap", "bias_anchor": "test"}
        ),
        lambda raw: raw["can_fire"].remove("PVS1"),
        # New fail-closed tests:
        lambda raw: (
            raw["lineage_classes"].append("bogus_lineage"),
            raw["records"]["PVS1"].update({"lineage_class": "bogus_lineage"})
        ),
        lambda raw: (
            raw["dispositions"].append("bogus_disposition"),
            raw["records"]["PVS1"].update({"validation_disposition": "bogus_disposition"})
        ),
        lambda raw: raw.update({"bias_version": "not.the.pinned.version"}),
        lambda raw: raw.update({"bias_commit": "notthepinnedcommit"}),
    ],
    ids=[
        "unknown-lineage",
        "unknown-validation-disposition",
        "unknown-production-disposition",
        "unknown-marker",
        "wildcard-oracle-allow",
        "duplicate-can-fire",
        "missing-record",
        "unknown-criterion",
        "partition-overlap",
        "partition-gap",
        "enum-and-record-bogus-lineage",
        "enum-and-record-bogus-disposition",
        "unpinned-bias-version",
        "unpinned-bias-commit",
    ],
)
def test_ac_l2_l3_fail_closed_policy_schema(tmp_path: Path, mutation) -> None:
    raw = _policy_dict()
    mutation(raw)

    with pytest.raises(LineagePolicyError):
        load_lineage_policy(_write_policy(tmp_path, raw))


def test_ac_l2_internal_stub_cannot_be_promoted_to_can_fire(tmp_path: Path) -> None:
    raw = _policy_dict()
    ps2_stub = next(
        entry for entry in raw["structurally_forbidden"] if entry["criterion"] == "PS2"
    )
    raw["structurally_forbidden"].remove(ps2_stub)
    raw["can_fire"].append("PS2")
    raw["records"]["PS2"] = {
        "lineage_class": "manual_or_external_input",
        "source_dependencies": {"direct": [], "transitive": []},
        "bias_anchors": ["pathogenic_classifiers.get_ps2"],
        "data_artifacts": [],
        "validation_disposition": "forbidden",
        "production_disposition": "forbidden",
        "rationale_markers": [],
        "notes": "test mutation",
        "decision_dependency": "",
    }

    with pytest.raises(LineagePolicyError):
        load_lineage_policy(_write_policy(tmp_path, raw))


def test_ac_l6_ps3_and_bs2_are_explicitly_deferred() -> None:
    _require_implementation()
    policy = load_lineage_policy(POLICY_PATH)
    ps3 = policy.records["PS3"]
    bs2 = policy.records["BS2"]

    assert ps3.lineage_class == "literature_unvalidated"
    assert ps3.validation_disposition == "deferred"
    assert ps3.production_disposition == "deferred"
    assert ps3.decision_dependency

    assert bs2.lineage_class == "label_independent_population"
    assert bs2.validation_disposition == "deferred"
    assert bs2.production_disposition == "deferred"
    assert bs2.decision_dependency == "bs2-policy"


@pytest.mark.parametrize("criterion", ["PS3", "BS2"])
def test_ac_l6_deferred_record_requires_named_decision(
    tmp_path: Path, criterion: str
) -> None:
    raw = _policy_dict()
    raw["records"][criterion]["decision_dependency"] = ""

    with pytest.raises(LineagePolicyError):
        load_lineage_policy(_write_policy(tmp_path, raw, f"{criterion}.yaml"))


@pytest.mark.skipif(
    not os.environ.get("RAPTOR_BIAS_SOURCE_ROOT")
    or not Path(os.environ.get("RAPTOR_BIAS_SOURCE_ROOT", "")).is_dir(),
    reason="RAPTOR_BIAS_SOURCE_ROOT not set or not a directory",
)
def test_live_source_evidence() -> None:
    root = Path(os.environ["RAPTOR_BIAS_SOURCE_ROOT"])
    oracle = _get_oracle()

    # 1. verify the two external source file SHA-256 values against the fixture
    for rel_path, expected_hash in oracle["files"].items():
        file_path = root / rel_path
        assert file_path.is_file(), f"Expected file {file_path} to exist"
        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"Hash mismatch for {rel_path}"

    # 2. parse them with Python AST, locate the 28 evaluator symbols, check status
    derived_statuses = {}
    for rel_path in oracle["files"].keys():
        file_path = root / rel_path
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("get_"):
                # find if this is one of our criteria
                criterion = None
                for c in oracle["criteria"]:
                    if c["symbol"] == node.name:
                        criterion = c["criterion"]
                        break

                if criterion:
                    body = node.body
                    if (
                        len(body) > 0
                        and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                    ):
                        body = body[1:]

                    is_stub = False
                    if len(body) == 1 and isinstance(body[0], ast.Return):
                        ret_val = body[0].value
                        if isinstance(ret_val, ast.Constant) and ret_val.value == "":
                            is_stub = True
                    elif (
                        len(body) == 2
                        and isinstance(body[0], ast.Assign)
                        and isinstance(body[1], ast.Return)
                    ):
                        assign = body[0]
                        ret = body[1]
                        if len(assign.targets) == 1 and isinstance(assign.targets[0], ast.Name):
                            var_name = assign.targets[0].id
                            if isinstance(assign.value, ast.Constant) and assign.value.value == "":
                                if isinstance(ret.value, ast.Name) and ret.value.id == var_name:
                                    is_stub = True

                    derived_statuses[criterion] = "internal_stub" if is_stub else "can_fire"

    assert len(derived_statuses) == 28, "Did not find all 28 criteria in AST"
    for c in oracle["criteria"]:
        assert derived_statuses[c["criterion"]] == c["status"], f"Status mismatch for {c['criterion']}"
