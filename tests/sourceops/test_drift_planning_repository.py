from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import json
import os
import stat
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from raptor.sourceops.drift_planning import (
    evaluate_materiality,
    load_materiality_policy,
    load_v2_s2_artifact_pair,
    plan_drift,
    rehearse_rollback,
    route_impact,
)
from raptor.sourceops.registry import load_registry
from tests.sourceops.test_drift_planning_contract import (
    _algorithmic_non_null_ready_fixture,
    _representative_pair,
    _rewrite_pair_leaf,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-s3-drift-gates.yaml"
REGISTRY_PATH = REPO_ROOT / "configs" / "sourceops" / "source_registry.yaml"
POLICY_PATH = REPO_ROOT / "configs" / "sourceops" / "materiality_policy.yaml"
SOURCEOPS_ROOT = REPO_ROOT / "src" / "raptor" / "sourceops"
DRIFT_OUTPUT_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "generated" / "drift-plans"
STAGED_SNAPSHOT_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "generated" / "staged-snapshots"
STAGING_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "staging"
ROLLBACK_PARENT = REPO_ROOT / "configs" / "sourceops" / "rollbacks"
_RUNTIME_CLEANUP_ROOTS = (
    DRIFT_OUTPUT_PARENT,
    STAGED_SNAPSHOT_PARENT,
    STAGING_PARENT,
    ROLLBACK_PARENT,
)
_RUNTIME_ALWAYS_PRESERVED_ROOTS = frozenset(
    {
        DRIFT_OUTPUT_PARENT,
        STAGED_SNAPSHOT_PARENT,
        STAGING_PARENT,
    }
)
_RuntimeSnapshotEntry = tuple[str, bytes | str | None]


def _runtime_display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _iter_runtime_paths_no_follow(root: Path) -> list[Path]:
    try:
        root.lstat()
    except FileNotFoundError:
        return []
    pending = [root]
    discovered: list[Path] = []
    while pending:
        current = pending.pop()
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            continue
        discovered.append(current)
        if stat.S_ISDIR(current_stat.st_mode):
            try:
                with os.scandir(current) as entries:
                    children = sorted((Path(entry.path) for entry in entries), key=lambda item: item.as_posix(), reverse=True)
            except FileNotFoundError:
                continue
            pending.extend(children)
    return discovered


def _snapshot_runtime_namespace() -> dict[Path, _RuntimeSnapshotEntry]:
    snapshot: dict[Path, _RuntimeSnapshotEntry] = {}
    for root in _RUNTIME_CLEANUP_ROOTS:
        for path in _iter_runtime_paths_no_follow(root):
            if path in snapshot:
                continue
            try:
                path_stat = path.lstat()
            except FileNotFoundError:
                continue
            mode = path_stat.st_mode
            if stat.S_ISDIR(mode):
                snapshot[path] = ("dir", None)
                continue
            if stat.S_ISLNK(mode):
                try:
                    snapshot[path] = ("symlink", os.readlink(path))
                except OSError as exc:
                    pytest.fail(f"unable to read symlink target for {_runtime_display(path)}: {exc}")
                continue
            if stat.S_ISREG(mode):
                try:
                    snapshot[path] = ("file", path.read_bytes())
                except OSError as exc:
                    pytest.fail(f"unable to read file bytes for {_runtime_display(path)}: {exc}")
                continue
            snapshot[path] = ("other", None)
    return snapshot


def _remove_created_runtime_paths(
    before: dict[Path, _RuntimeSnapshotEntry],
    after: dict[Path, _RuntimeSnapshotEntry],
) -> None:
    preserved_roots = set(_RUNTIME_ALWAYS_PRESERVED_ROOTS)
    for root in _RUNTIME_CLEANUP_ROOTS:
        if root in before:
            preserved_roots.add(root)
    created_paths = [path for path in after if path not in before and path not in preserved_roots]
    created_paths.sort(key=lambda item: (len(item.parts), item.as_posix()), reverse=True)
    failures: list[str] = []
    for path in created_paths:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        try:
            if stat.S_ISDIR(mode):
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        except OSError as exc:
            failures.append(f"{_runtime_display(path)}: {exc}")
    if failures:
        pytest.fail("V2-S3 runtime cleanup failed to remove test-owned paths:\n" + "\n".join(failures))


def _assert_preexisting_runtime_paths_unchanged(
    before: dict[Path, _RuntimeSnapshotEntry],
    after: dict[Path, _RuntimeSnapshotEntry],
) -> None:
    failures: list[str] = []
    for path, before_entry in sorted(before.items(), key=lambda row: row[0].as_posix()):
        after_entry = after.get(path)
        if after_entry is None:
            failures.append(f"{_runtime_display(path)} was removed")
            continue
        if after_entry[0] != before_entry[0]:
            failures.append(f"{_runtime_display(path)} changed type from {before_entry[0]} to {after_entry[0]}")
            continue
        if after_entry[1] != before_entry[1]:
            descriptor = "bytes" if before_entry[0] == "file" else "target"
            failures.append(f"{_runtime_display(path)} changed {descriptor}")
    if failures:
        pytest.fail("V2-S3 runtime cleanup detected mutation of pre-existing paths:\n" + "\n".join(failures))


@pytest.fixture(autouse=True)
def _v2s3_runtime_namespace_cleanup() -> Iterator[None]:
    before = _snapshot_runtime_namespace()
    yield
    after = _snapshot_runtime_namespace()
    _remove_created_runtime_paths(before, after)
    final = _snapshot_runtime_namespace()
    _assert_preexisting_runtime_paths_unchanged(before, final)


def _spec() -> dict[str, Any]:
    loaded = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail("V2-S3 authority must parse into a mapping")
    return loaded


def _registry() -> dict[str, Any]:
    loaded = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail("source_registry.yaml must parse into a mapping")
    return loaded


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _self_hash(mapping: dict[str, Any], field: str) -> str:
    basis = copy.deepcopy(mapping)
    basis.pop(field, None)
    return _sha256_hex(_canonical_json_bytes(basis))


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


def _production_registry() -> Any:
    return load_registry(str(REGISTRY_PATH))


def _cleanup_drift_output(payload: dict[str, Any]) -> None:
    impact = payload.get("impact_plan")
    if not isinstance(impact, dict):
        return
    rel_path = impact.get("path")
    if not isinstance(rel_path, str):
        return
    impact_path = (REPO_ROOT / rel_path).resolve()
    root = (REPO_ROOT / ".raptor" / "sourceops" / "generated" / "drift-plans").resolve()
    if not str(impact_path).startswith(str(root) + os.sep):
        return
    shutil.rmtree(impact_path.parent.parent, ignore_errors=True)


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _module_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_v2s3_ac05_current_registry_declarations_actions_edges_and_reserved_boundaries_fail_closed() -> None:
    with _representative_pair("no-change") as pair:
        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert result.exit_code in {0, 8}
            assert payload["baseline_validity"] == "VALID"
            assert payload["error"] is None
        finally:
            _cleanup_drift_output(payload)

    spec = _spec()["planning_baseline"]
    registry = _registry()
    roots = spec["current_repository_reality"]["declaration_roots"]
    allowed_actions = spec["v2_s1"]["allowed_action_enum_in_order"]
    reserved = set(spec["v2_s1"]["reserved_consumer_ids"])
    records = {row["source_id"]: row for row in registry["source_records"]}
    consumers = {row["consumer_id"]: row for row in registry["consumers"]}

    assert len(records) == spec["v2_s1"]["source_record_count"] == 7
    for root in roots:
        source = records[root["source_id"]]
        assert source["authoritative_locator"] == root["path"]
        assert _sha256_hex(_canonical_json_bytes(source)) == root["source_record_content_hash"]
        assert source["drift_policy"]["actions"] == allowed_actions
        assert source["drift_policy"]["approval_required"] is True
        assert len({item.casefold() for item in source["consumers"]}) == len(source["consumers"])
        assert not any(consumer in reserved for consumer in source["consumers"])
        for consumer_id in source["consumers"]:
            assert consumer_id in consumers
            assert root["source_id"] in consumers[consumer_id]["required_sources"]


def test_v2s3_ac07_repository_policy_exact_mapping_hash_and_bindings_are_authoritative() -> None:
    load_materiality_policy()
    expected = copy.deepcopy(_spec()["materiality_policy_contract"]["initial_checked_in_mapping"])
    assert expected["policy_content_hash"] == _self_hash(expected, "policy_content_hash")
    assert expected["registry_binding"]["registry_content_hash"] == _registry()["registry_content_hash"]
    assert POLICY_PATH.exists(), f"missing required production policy file: {POLICY_PATH}"
    loaded = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    assert loaded == expected


def test_v2s3_ac13_reserved_consumers_cannot_be_routes_or_approvals() -> None:
    reserved = set(_spec()["planning_baseline"]["v2_s1"]["reserved_consumer_ids"])
    registry = _registry()
    source_edges = [consumer for source in registry["source_records"] for consumer in source["consumers"]]
    assert not reserved.intersection(source_edges), "reserved consumers must not appear on source edges"
    for consumer in registry["consumers"]:
        if consumer["consumer_id"] in reserved:
            assert consumer["required_sources"] == []

    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        typed_registry = _production_registry()
        policy = load_materiality_policy()
        assessment = evaluate_materiality(typed_pair, typed_registry, policy)
        rehearsal = rehearse_rollback(typed_pair, typed_registry)
        routing = route_impact(assessment, typed_registry, rehearsal)
        for route in routing.routes:
            assert route.target["id"] not in reserved

        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert result.exit_code in {0, 8}
            impact = json.loads((REPO_ROOT / payload["impact_plan"]["path"]).read_text(encoding="utf-8"))
            assert all(route["target"]["id"] not in reserved for route in impact["proposal"]["routes"])
        finally:
            _cleanup_drift_output(payload)


def test_v2s3_ac15_current_root_sources_are_no_predecessor_not_applicable() -> None:
    with _representative_pair("no-change") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        typed_registry = _production_registry()
        rehearsal = rehearse_rollback(typed_pair, typed_registry)
        assert rehearsal.outcome == "NOT_APPLICABLE"
        assert rehearsal.reason_code == "NO_PREDECESSOR"
        assert rehearsal.rollback_route_eligible is False
        assert rehearsal.proposed_operations == ()

        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert result.exit_code == 0
            assert payload["rollback_rehearsal_outcome"] == "NOT_APPLICABLE"
            assert payload["error"] is None
        finally:
            _cleanup_drift_output(payload)

    records = _registry()["source_records"]
    assert len(records) == 7
    for source in records:
        rollback = source["rollback"]
        assert rollback["predecessor_source_id"] is None
        assert rollback["immutable_predecessor_required"] is True
        assert not (REPO_ROOT / rollback["rollback_artifact"]).exists(), rollback["rollback_artifact"]
    semantics = _spec()["rollback_rehearsal_contract"]["root_source_semantics"]
    assert semantics["lineage_status"] == "NO_PREDECESSOR"
    assert semantics["rehearsal_outcome"] == "NOT_APPLICABLE"
    assert semantics["rollback_route_eligible"] is False


def test_v2s3_ac24_success_blocked_and_failures_mutate_only_owned_generated_output(monkeypatch: pytest.MonkeyPatch) -> None:
    preservation_paths = [REPO_ROOT / row["path"] for row in _registry()["preservation_rules"]]
    before = {path: path.read_bytes() for path in preservation_paths}
    with _representative_pair("no-change") as pair:
        drift_module = importlib.import_module("raptor.sourceops.drift_planning")
        original_evaluate = drift_module.evaluate_materiality
        original_bytes = pair.diff_path.read_bytes()

        def _mutating_evaluate(typed_pair: Any, registry: Any, policy: Any) -> Any:
            pair.diff_path.write_bytes(original_bytes + b" \n")
            return original_evaluate(typed_pair, registry, policy)

        monkeypatch.setattr(drift_module, "evaluate_materiality", _mutating_evaluate)
        try:
            result = plan_drift(pair.manifest_hash)
        finally:
            pair.diff_path.write_bytes(original_bytes)

    after = {path: path.read_bytes() for path in preservation_paths}
    payload = result.cli_result.as_dict()
    assert before == after
    assert result.exit_code == 2
    assert payload["error"] is not None
    assert payload["error"]["code"] == "DRIFT_INPUT_MUTATED"
    assert payload["impact_plan"] is None
    assert payload["rollback_plan"] is None


def test_v2s3_ac25_v2s1_v2s2_and_existing_cli_behavior_are_preserved() -> None:
    with _representative_pair("no-change") as pair:
        plan = plan_drift(pair.manifest_hash)
        plan_payload = plan.cli_result.as_dict()
        try:
            assert plan.exit_code in {0, 8}
            assert plan_payload["error"] is None
        finally:
            _cleanup_drift_output(plan_payload)

    validate_a = _run_cli("validate", "--registry", "configs/sourceops/source_registry.yaml")
    validate_b = _run_cli("validate", "--registry", "configs/sourceops/source_registry.yaml")
    assert validate_a.returncode == 0
    assert validate_a.stdout == validate_b.stdout
    assert validate_a.stderr == validate_b.stderr == ""

    status_a = _run_cli("status", "--registry", "configs/sourceops/source_registry.yaml", "--consumer", "eval-gate")
    status_b = _run_cli("status", "--registry", "configs/sourceops/source_registry.yaml", "--consumer", "eval-gate")
    assert status_a.returncode == 0
    assert status_a.stdout == status_b.stdout
    assert status_a.stderr == status_b.stderr == ""

    new_cmd = _spec()["cli_contract"]["new_command"]["command"]
    assert new_cmd == "plan-drift"


def test_v2s3_ac26_implementation_uses_only_synthetic_rehearsals_and_leaves_phase_handoff_external() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            assert rehearsal.outcome in {"READY_FOR_HUMAN_ADJUDICATION", "BLOCKED"}

        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert result.exit_code in {0, 8}
            assert payload["error"] is None
        finally:
            _cleanup_drift_output(payload)

    handoff = _spec()["v2_phase_rehearsal_handoff"]
    assert "implementation_acceptance_exclusion" in handoff
    assert "not embedded" in handoff["implementation_acceptance_exclusion"]


def test_v2s3_fm06_stale_registry_declaration_action_edge_and_preservation_fail_before_policy() -> None:
    with _representative_pair("no-change") as pair:
        _rewrite_pair_leaf(
            pair,
            mutate_verification=lambda verification, _diff: verification["source_binding"].__setitem__("source_record_content_hash", "0" * 64),
            mutate_diff=lambda diff, _verification: diff["source_binding"].__setitem__("source_record_content_hash", "0" * 64),
            recompute_summary=False,
        )
        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        assert result.exit_code == 5
        assert payload["error"] is not None
        assert payload["error"]["code"] == "DRIFT_BASELINE_BINDING_MISMATCH"
        assert payload["impact_plan"] is None
        assert payload["rollback_plan"] is None


def test_v2s3_fm14_reserved_consumer_route_and_approval_attempts_fail_closed() -> None:
    reserved = set(_spec()["planning_baseline"]["v2_s1"]["reserved_consumer_ids"])
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        registry = _production_registry()
        policy = load_materiality_policy()
        assessment = evaluate_materiality(typed_pair, registry, policy)
        rehearsal = rehearse_rollback(typed_pair, registry)
        routing = route_impact(assessment, registry, rehearsal)
        assert all(route.target["id"] not in reserved for route in routing.routes)

        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            impact = json.loads((REPO_ROOT / payload["impact_plan"]["path"]).read_text(encoding="utf-8"))
            assert all(route["target"]["id"] not in reserved for route in impact["proposal"]["routes"])
        finally:
            _cleanup_drift_output(payload)


def test_v2s3_fm17_absent_legacy_rollback_paths_are_not_opened_for_root_sources() -> None:
    with _representative_pair("no-change") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        typed_registry = _production_registry()
        rehearsal = rehearse_rollback(typed_pair, typed_registry)
        assert rehearsal.outcome == "NOT_APPLICABLE"
        assert rehearsal.reason_code == "NO_PREDECESSOR"
        assert rehearsal.rollback_artifact_status == "NOT_REQUIRED"

        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert result.exit_code == 0
            assert payload["rollback_rehearsal_outcome"] == "NOT_APPLICABLE"
        finally:
            _cleanup_drift_output(payload)


def test_v2s3_fm21_no_command_dispatch_copy_replace_delete_or_shell_surface_exists() -> None:
    with _representative_pair("material-content") as pair:
        typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            rehearsal = rehearse_rollback(typed_pair, fixture.registry)
            assert all(op.approval_state == "NOT_GRANTED" and op.executed is False for op in rehearsal.proposed_operations)

    forbidden_calls = {"Popen", "check_output", "check_call", "system", "execv", "execl", "spawnv", "spawnve"}
    offenders: list[str] = []
    for py_path in _iter_python_files(SOURCEOPS_ROOT):
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                else:
                    continue
                if name in forbidden_calls:
                    offenders.append(f"{py_path.relative_to(REPO_ROOT)}:{node.lineno}:{name}")
    assert not offenders, "command dispatch and restore mutation surfaces are forbidden:\n" + "\n".join(offenders)


def test_v2s3_fm26_authority_hashes_and_existing_command_bytes_are_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec()["planning_baseline"]
    registry = _registry()
    assert registry["registry_content_hash"] == spec["v2_s1"]["registry_content_hash"]
    assert _self_hash(registry, "registry_content_hash") == registry["registry_content_hash"]

    with _representative_pair("no-change") as pair:
        drift_module = importlib.import_module("raptor.sourceops.drift_planning")
        original_evaluate = drift_module.evaluate_materiality
        original_bytes = pair.diff_path.read_bytes()

        def _mutating_evaluate(typed_pair: Any, typed_registry: Any, policy: Any) -> Any:
            pair.diff_path.write_bytes(original_bytes + b" \n")
            return original_evaluate(typed_pair, typed_registry, policy)

        monkeypatch.setattr(drift_module, "evaluate_materiality", _mutating_evaluate)
        try:
            mutated = plan_drift(pair.manifest_hash)
        finally:
            pair.diff_path.write_bytes(original_bytes)
        mutated_payload = mutated.cli_result.as_dict()
        assert mutated.exit_code == 2
        assert mutated_payload["error"] is not None
        assert mutated_payload["error"]["code"] == "DRIFT_INPUT_MUTATED"

    validate = _run_cli("validate", "--registry", "configs/sourceops/source_registry.yaml")
    status = _run_cli("status", "--registry", "configs/sourceops/source_registry.yaml", "--consumer", "eval-gate")
    assert validate.returncode == 0
    assert status.returncode == 0
    assert validate.stderr == ""
    assert status.stderr == ""
    assert validate.stdout.endswith("\n")
    assert status.stdout.endswith("\n")


def test_v2s3_fm27_network_service_database_workflow_and_domain_import_guards() -> None:
    with _representative_pair("no-change") as pair:
        result = plan_drift(pair.manifest_hash)
        payload = result.cli_result.as_dict()
        try:
            assert result.exit_code in {0, 8}
            assert payload["error"] is None
        finally:
            _cleanup_drift_output(payload)

    forbidden_prefixes = (
        "requests",
        "httpx",
        "urllib.request",
        "socket",
        "sqlite3",
        "prefect",
        "airflow",
        "luigi",
        "raptor.scorer",
        "raptor.eval",
        "raptor.packet",
        "raptor.census",
        "raptor.atlas",
        "raptor.ingest",
        "raptor.kb",
        "raptor.external",
    )
    offenders: list[str] = []
    for py_path in _iter_python_files(SOURCEOPS_ROOT):
        for module in _module_imports(py_path):
            if module.startswith("raptor.sourceops"):
                continue
            if module.startswith(forbidden_prefixes):
                offenders.append(f"{py_path.relative_to(REPO_ROOT)}:{module}")
    assert not offenders, "forbidden network/service/domain imports found:\n" + "\n".join(offenders)


def test_v2s3_mapping_completeness_and_non_vacuous_targets() -> None:
    spec = _spec()["test_author_contract"]
    expected_files = set(spec["required_test_files"])
    expected_ids = {*(f"V2S3-AC{idx:02d}" for idx in range(1, 27)), *(f"V2S3-FM{idx:02d}" for idx in range(1, 28))}

    acceptance = spec["acceptance_mapping"]
    failure = spec["failure_mapping"]
    assert set(acceptance.keys()) | set(failure.keys()) == expected_ids

    mapped_targets = {target for targets in acceptance.values() for target in targets}
    mapped_targets |= {target for targets in failure.values() for target in targets}
    assert mapped_targets

    def _function_call_summary(node: ast.FunctionDef) -> dict[str, Any]:
        call_names: set[str] = set()
        cli_literals: set[str] = set()
        string_literals: set[str] = set()
        has_cli_call = False
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                string_literals.add(child.value)
            if not isinstance(child, ast.Call):
                continue
            callee: str | None = None
            if isinstance(child.func, ast.Name):
                callee = child.func.id
            elif isinstance(child.func, ast.Attribute):
                callee = child.func.attr
            if callee:
                call_names.add(callee)
                if callee in {"_run_cli", "_run_cli_bytes"} and child.args:
                    has_cli_call = True
                    first = child.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        cli_literals.add(first.value)
                elif callee in {"_run_cli", "_run_cli_bytes"}:
                    has_cli_call = True

        return {
            "call_names": call_names,
            "cli_literals": cli_literals,
            "string_literals": string_literals,
            "has_cli_call": has_cli_call,
        }

    discovered_functions: dict[str, dict[str, Any]] = {}
    for rel_path in expected_files:
        path = REPO_ROOT / rel_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            target = f"{rel_path}::{node.name}"
            discovered_functions[target] = _function_call_summary(node)

    missing = sorted(target for target in mapped_targets if target not in discovered_functions)
    assert not missing, f"mapped tests missing from filesystem: {missing}"

    non_vacuity = spec["production_surface_non_vacuity"]
    matrix = non_vacuity["per_id_required_surfaces"]
    new_cli_subcommand = _spec()["cli_contract"]["new_command"]["command"]

    exact_surface_call = {
        "INPUT": "load_v2_s2_artifact_pair",
        "POLICY": "load_materiality_policy",
        "MATERIALITY": "evaluate_materiality",
        "ROUTING": "route_impact",
        "ROLLBACK": "rehearse_rollback",
        "OUTPUT": "plan_drift",
    }

    def _satisfies_surface(summary: dict[str, Any], surface: str) -> bool:
        call_names = summary["call_names"]
        if surface in exact_surface_call:
            return exact_surface_call[surface] in call_names
        if surface == "CLI":
            cli_literals = set(summary["cli_literals"])
            string_literals = set(summary["string_literals"])
            known_subcommands = {"plan-drift", "validate", "status", "verify-stage"}
            return bool(summary["has_cli_call"]) and (bool(cli_literals) or bool(known_subcommands.intersection(string_literals)))
        if surface == "MUTATION":
            mutation_markers = {"setattr", "write_bytes", "unlink", "rename"}
            return "plan_drift" in call_names and bool(mutation_markers.intersection(call_names))
        return False

    violations: list[str] = []
    for criterion_id, targets in {**acceptance, **failure}.items():
        required_surfaces = matrix[criterion_id]
        for target in targets:
            summary = discovered_functions[target]
            for surface in required_surfaces:
                if not _satisfies_surface(summary, surface):
                    violations.append(f"{criterion_id}::{target} missing required surface {surface}")

    opus_requirements = non_vacuity["opus_recheck_per_test_requirements"]
    for target, requirement in opus_requirements.items():
        summary = discovered_functions.get(target)
        if summary is None:
            continue
        call_names = summary["call_names"]
        for required_call in requirement["exact_function_or_cli_calls"]:
            if required_call == "python -m raptor.sourceops.cli":
                if not _satisfies_surface(summary, "CLI"):
                    violations.append(f"{target} missing literal CLI subcommand {new_cli_subcommand}")
                continue
            if required_call not in call_names:
                violations.append(f"{target} missing exact production call {required_call}")

    assert not violations, "production-surface non-vacuity matrix violations:\n" + "\n".join(sorted(violations))
