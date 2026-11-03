from __future__ import annotations

import importlib
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
import yaml

from raptor.sourceops.drift_planning import load_materiality_policy, load_v2_s2_artifact_pair, plan_drift, rehearse_rollback
from tests.sourceops.test_drift_planning_contract import (
    _algorithmic_non_null_ready_fixture,
    _policy_with_registry_hash,
    _representative_pair,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-s3-drift-gates.yaml"
SNAPSHOT_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "generated" / "staged-snapshots"
DRIFT_OUTPUT_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "generated" / "drift-plans"
STAGING_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "staging"
ROLLBACK_PARENT = REPO_ROOT / "configs" / "sourceops" / "rollbacks"
POLICY_PATH = REPO_ROOT / "configs" / "sourceops" / "materiality_policy.yaml"
REGISTRY_PATH = REPO_ROOT / "configs" / "sourceops" / "source_registry.yaml"
_RUNTIME_CLEANUP_ROOTS = (
    DRIFT_OUTPUT_PARENT,
    SNAPSHOT_PARENT,
    STAGING_PARENT,
    ROLLBACK_PARENT,
)
_RUNTIME_ALWAYS_PRESERVED_ROOTS = frozenset(
    {
        DRIFT_OUTPUT_PARENT,
        SNAPSHOT_PARENT,
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


def _assert_json_stdout_and_empty_stderr(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.stderr == "", f"stderr must be empty for handled failures, got {result.stderr!r}"
    assert result.stdout.endswith("\n"), "stdout must end with one LF"
    assert result.stdout.count("\n") == 1, "stdout must contain exactly one JSON line"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict), "stdout payload must be a JSON object"
    return payload


def _owned_rmtree(path: Path) -> None:
    if not path.exists():
        return
    shutil.rmtree(path, ignore_errors=True)


@contextmanager
def _snapshot_leaf(manifest_hash: str) -> Iterator[Path]:
    leaf = SNAPSHOT_PARENT / manifest_hash
    created = False
    if leaf.exists():
        pytest.fail(f"snapshot leaf unexpectedly exists before probe: {leaf}")
    leaf.mkdir(parents=True, exist_ok=False)
    created = True
    try:
        yield leaf
    finally:
        if created:
            _owned_rmtree(leaf)


@contextmanager
def _drift_output_leaf(diff_hash: str, policy_hash: str) -> Iterator[Path]:
    root = DRIFT_OUTPUT_PARENT / diff_hash
    leaf = root / policy_hash
    if leaf.exists():
        pytest.fail(f"drift output leaf unexpectedly exists before probe: {leaf}")
    leaf.mkdir(parents=True, exist_ok=False)
    try:
        yield leaf
    finally:
        _owned_rmtree(root)


@contextmanager
def _mutate_during_materiality_evaluation(
    *,
    target_path: Path,
    replacement_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
    patch_registry: Callable[[Any], None] | None = None,
) -> Iterator[dict[str, bool]]:
    drift_module = importlib.import_module("raptor.sourceops.drift_planning")
    original_evaluate = drift_module.evaluate_materiality
    original_bytes = target_path.read_bytes()
    mutation_state = {"applied": False}

    if patch_registry is not None:
        patch_registry(drift_module)

    def _mutating_evaluate(pair: Any, registry: Any, policy: Any) -> Any:
        if not mutation_state["applied"]:
            target_path.write_bytes(replacement_bytes)
            mutation_state["applied"] = True
        return original_evaluate(pair, registry, policy)

    drift_module.evaluate_materiality = _mutating_evaluate
    try:
        yield mutation_state
    finally:
        drift_module.evaluate_materiality = original_evaluate
        target_path.write_bytes(original_bytes)


def test_v2s3_ac01_fixed_leaf_discovery_and_boundary_are_closed() -> None:
    manifest_hash = "a" * 64
    with _snapshot_leaf(manifest_hash) as leaf:
        (leaf / "v-" / "bad").parent.mkdir(parents=True, exist_ok=True)
        (leaf / "v-bad-name.json").write_text("{}", encoding="utf-8")
        (leaf / "d-bad-name.json").write_text("{}", encoding="utf-8")
        (leaf / ".extra.tmp").write_text("x", encoding="utf-8")
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(manifest_hash)
        assert getattr(exc_info.value, "code", None) in {"DRIFT_INPUT_ARTIFACT_SET_INVALID", "DRIFT_INPUT_LEAF_NOT_FINALIZED"}
        result = _run_cli("plan-drift", "--manifest-hash", manifest_hash)
    payload = _assert_json_stdout_and_empty_stderr(result)
    assert result.returncode == 2
    assert payload["error"]["code"] in {"DRIFT_INPUT_ARTIFACT_SET_INVALID", "DRIFT_INPUT_LEAF_NOT_FINALIZED"}


def test_v2s3_ac06_all_governing_inputs_pass_two_immutable_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    registry_mapping = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(registry_mapping, dict)
    preservation_path = REPO_ROOT / registry_mapping["preservation_rules"][0]["path"]
    declaration_path = REPO_ROOT / "configs" / "ingest" / "tsc.yaml"

    with _representative_pair("no-change") as pair:
        mutation_cases = (
            ("input-diff-artifact", pair.diff_path, pair.diff_path.read_bytes() + b" \n", 2, "DRIFT_INPUT_MUTATED"),
            ("baseline-registry", REGISTRY_PATH, REGISTRY_PATH.read_bytes() + b"\n# v2s3-registry-mutation\n", 5, "DRIFT_BASELINE_CHANGED_DURING_RUN"),
            ("baseline-declaration", declaration_path, declaration_path.read_bytes() + b"\n# v2s3-declaration-mutation\n", 5, "DRIFT_BASELINE_CHANGED_DURING_RUN"),
            ("baseline-preservation", preservation_path, preservation_path.read_bytes() + b"\n# v2s3-preservation-mutation\n", 5, "DRIFT_BASELINE_CHANGED_DURING_RUN"),
            ("policy", POLICY_PATH, POLICY_PATH.read_bytes() + b"\n# v2s3-policy-mutation\n", 6, "DRIFT_POLICY_CHANGED_DURING_RUN"),
        )
        for _label, target_path, replacement, expected_exit, expected_code in mutation_cases:
            with _mutate_during_materiality_evaluation(
                target_path=target_path,
                replacement_bytes=replacement,
                monkeypatch=monkeypatch,
            ) as state:
                result = plan_drift(pair.manifest_hash)
            payload = result.cli_result.as_dict()
            assert state["applied"] is True
            assert result.exit_code == expected_exit
            assert payload["error"] is not None
            assert payload["error"]["code"] == expected_code
            assert payload["impact_plan"] is None
            assert payload["rollback_plan"] is None

    with _representative_pair("material-content") as pair:
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
            ready = rehearse_rollback(typed_pair, fixture.registry)
            assert ready.outcome == "READY_FOR_HUMAN_ADJUDICATION"
            bound_current_paths = tuple((REPO_ROOT / row["current_path"]) for row in fixture.rollback_artifact["file_bindings"])
            bound_predecessor_paths = tuple((REPO_ROOT / row["predecessor_path"]) for row in fixture.rollback_artifact["file_bindings"])
            assert bound_current_paths
            assert bound_predecessor_paths

            mutation_cases = (
                ("rollback-artifact", fixture.rollback_artifact_path, fixture.rollback_artifact_path.read_bytes() + b" \n", None),
                (
                    "rollback-bound-current",
                    bound_current_paths[0],
                    bound_current_paths[0].read_bytes() + b"\n# v2s3-ac06-rollback-bound-current-mutation\n",
                    bound_current_paths,
                ),
                (
                    "rollback-bound-predecessor",
                    bound_predecessor_paths[0],
                    bound_predecessor_paths[0].read_bytes() + b"\n# v2s3-ac06-rollback-bound-predecessor-mutation\n",
                    bound_predecessor_paths,
                ),
            )
            for _label, target_path, replacement, expected_bound_set in mutation_cases:
                if expected_bound_set is not None:
                    assert target_path in expected_bound_set
                with monkeypatch.context() as mp:
                    def _patch_registry(drift_module: Any) -> None:
                        source_record = next(item for item in fixture.registry.source_records if item.source_id == pair.source_id)
                        mp.setattr(drift_module, "_load_and_validate_current_registry", lambda: (fixture.registry, fixture.raw_registry))
                        mp.setattr(drift_module, "_validate_source_baseline", lambda _pair, _registry, _registry_dict: source_record)
                        mp.setattr(
                            drift_module,
                            "load_materiality_policy",
                            lambda: _policy_with_registry_hash(fixture.raw_registry["registry_content_hash"]),
                        )
                        # Keep the seam focused on rollback-governing inputs so bound-file
                        # mutation categorization cannot be preempted by baseline snapshots.
                        mp.setattr(drift_module, "_governing_declaration_and_preservation_paths", lambda _registry_dict: [])

                    with _mutate_during_materiality_evaluation(
                        target_path=target_path,
                        replacement_bytes=replacement,
                        monkeypatch=mp,
                        patch_registry=_patch_registry,
                    ) as state:
                        result = plan_drift(pair.manifest_hash)
                payload = result.cli_result.as_dict()
                assert state["applied"] is True
                assert result.exit_code == 8
                assert payload["error"] is not None
                assert payload["error"]["code"] == "DRIFT_ROLLBACK_INPUT_MUTATED"
                assert payload["error"]["code"] != "DRIFT_BASELINE_CHANGED_DURING_RUN"
                assert payload["impact_plan"] is None
                assert payload["rollback_plan"] is None


def test_v2s3_ac20_transactional_pair_publication_is_idempotent_and_race_safe() -> None:
    with _representative_pair("no-change") as pair:
        manifest_hash = pair.manifest_hash
        results: list[dict[str, Any]] = []
        lock = threading.Lock()

        def _worker() -> None:
            outcome = plan_drift(manifest_hash)
            payload = outcome.cli_result.as_dict()
            with lock:
                results.append({"exit_code": outcome.exit_code, "payload": payload})

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(results) == 2
        assert results[0]["exit_code"] == results[1]["exit_code"]
        assert results[0]["payload"] == results[1]["payload"]

        if isinstance(results[0]["payload"].get("impact_plan"), dict):
            _owned_rmtree((REPO_ROOT / results[0]["payload"]["impact_plan"]["path"]).resolve().parent.parent)


def test_v2s3_ac23_limits_first_error_and_json_safe_details_are_deterministic() -> None:
    with _representative_pair("no-change") as pair:
        loaded = load_v2_s2_artifact_pair(pair.manifest_hash)
        assert loaded.manifest_content_hash == pair.manifest_hash

    result = plan_drift("not-a-hash")
    payload = result.cli_result.as_dict()
    assert result.exit_code == 2
    assert payload["error"] is not None
    assert payload["error"]["code"] == "DRIFT_INPUT_LEAF_INVALID"
    assert payload["impact_plan"] is None
    assert payload["rollback_plan"] is None


def test_v2s3_fm02_links_reparses_and_special_input_entries_are_never_followed() -> None:
    manifest_hash = "c" * 64
    with _snapshot_leaf(manifest_hash) as leaf:
        link = leaf / "v-linked.json"
        target = leaf / "target.json"
        target.write_text("{}", encoding="utf-8")
        try:
            link.symlink_to(target.name)
        except OSError:
            pytest.fail("WSL symlink probe must be executable in V2-S3 safety suite")
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(manifest_hash)
        assert getattr(exc_info.value, "code", None) in {"DRIFT_INPUT_LEAF_NOT_FINALIZED", "DRIFT_INPUT_ARTIFACT_SET_INVALID"}
        result = _run_cli("plan-drift", "--manifest-hash", manifest_hash)
    payload = _assert_json_stdout_and_empty_stderr(result)
    assert result.returncode == 2
    assert payload["error"]["code"] in {"DRIFT_INPUT_LEAF_NOT_FINALIZED", "DRIFT_INPUT_ARTIFACT_SET_INVALID"}


def test_v2s3_fm07_each_governing_input_mutation_maps_to_its_exact_category(monkeypatch: pytest.MonkeyPatch) -> None:
    registry_mapping = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(registry_mapping, dict)
    preservation_path = REPO_ROOT / registry_mapping["preservation_rules"][0]["path"]

    with _representative_pair("no-change") as pair:
        mutation_cases = (
            ("input", pair.diff_path, pair.diff_path.read_bytes() + b" \n", 2, "DRIFT_INPUT_MUTATED"),
            ("baseline", preservation_path, preservation_path.read_bytes() + b"\n# v2s3-fm07-preservation-mutation\n", 5, "DRIFT_BASELINE_CHANGED_DURING_RUN"),
            ("policy", POLICY_PATH, POLICY_PATH.read_bytes() + b"\n# v2s3-fm07-policy-mutation\n", 6, "DRIFT_POLICY_CHANGED_DURING_RUN"),
        )
        for _category, target_path, replacement, expected_exit, expected_code in mutation_cases:
            with _mutate_during_materiality_evaluation(
                target_path=target_path,
                replacement_bytes=replacement,
                monkeypatch=monkeypatch,
            ) as state:
                result = plan_drift(pair.manifest_hash)
            payload = result.cli_result.as_dict()
            assert state["applied"] is True
            assert result.exit_code == expected_exit
            assert payload["error"] is not None
            assert payload["error"]["code"] == expected_code
            assert payload["impact_plan"] is None
            assert payload["rollback_plan"] is None

    with _representative_pair("material-content") as pair:
        with _algorithmic_non_null_ready_fixture(pair) as fixture:
            typed_pair = load_v2_s2_artifact_pair(pair.manifest_hash)
            ready = rehearse_rollback(typed_pair, fixture.registry)
            assert ready.outcome == "READY_FOR_HUMAN_ADJUDICATION"
            bound_current_paths = tuple((REPO_ROOT / row["current_path"]) for row in fixture.rollback_artifact["file_bindings"])
            bound_predecessor_paths = tuple((REPO_ROOT / row["predecessor_path"]) for row in fixture.rollback_artifact["file_bindings"])
            assert bound_current_paths
            assert bound_predecessor_paths

            mutation_cases = (
                ("rollback-artifact", fixture.rollback_artifact_path, fixture.rollback_artifact_path.read_bytes() + b" \n", None),
                (
                    "rollback-bound-current",
                    bound_current_paths[0],
                    bound_current_paths[0].read_bytes() + b"\n# v2s3-fm07-rollback-bound-current-mutation\n",
                    bound_current_paths,
                ),
                (
                    "rollback-bound-predecessor",
                    bound_predecessor_paths[0],
                    bound_predecessor_paths[0].read_bytes() + b"\n# v2s3-fm07-rollback-bound-predecessor-mutation\n",
                    bound_predecessor_paths,
                ),
            )
            for _label, target_path, replacement, expected_bound_set in mutation_cases:
                if expected_bound_set is not None:
                    assert target_path in expected_bound_set
                with monkeypatch.context() as mp:
                    def _patch_registry(drift_module: Any) -> None:
                        source_record = next(item for item in fixture.registry.source_records if item.source_id == pair.source_id)
                        mp.setattr(drift_module, "_load_and_validate_current_registry", lambda: (fixture.registry, fixture.raw_registry))
                        mp.setattr(drift_module, "_validate_source_baseline", lambda _pair, _registry, _registry_dict: source_record)
                        mp.setattr(
                            drift_module,
                            "load_materiality_policy",
                            lambda: _policy_with_registry_hash(fixture.raw_registry["registry_content_hash"]),
                        )
                        mp.setattr(drift_module, "_governing_declaration_and_preservation_paths", lambda _registry_dict: [])

                    with _mutate_during_materiality_evaluation(
                        target_path=target_path,
                        replacement_bytes=replacement,
                        monkeypatch=mp,
                        patch_registry=_patch_registry,
                    ) as state:
                        result = plan_drift(pair.manifest_hash)
                payload = result.cli_result.as_dict()
                assert state["applied"] is True
                assert result.exit_code == 8
                assert payload["error"] is not None
                assert payload["error"]["code"] == "DRIFT_ROLLBACK_INPUT_MUTATED"
                assert payload["error"]["code"] != "DRIFT_BASELINE_CHANGED_DURING_RUN"
                assert payload["impact_plan"] is None
                assert payload["rollback_plan"] is None


def test_v2s3_fm24_concurrent_partial_locked_and_colliding_publications_preserve_foreign_bytes() -> None:
    with _representative_pair("no-change") as pair:
        first = plan_drift(pair.manifest_hash)
        first_payload = first.cli_result.as_dict()
        assert first.exit_code in {0, 8}
        assert first_payload["error"] is None
        assert isinstance(first_payload["impact_plan"], dict)
        assert isinstance(first_payload["rollback_plan"], dict)

        diff_hash = first_payload["diff_artifact_content_hash"]
        policy_hash = first_payload["policy_content_hash"]
        root = DRIFT_OUTPUT_PARENT / diff_hash
        leaf = root / policy_hash
        _owned_rmtree(root)
        leaf.mkdir(parents=True, exist_ok=False)

        lock_path = leaf / ".sourceops-transaction.lock"
        lock_path.write_text("{\"owner\":\"foreign\"}\n", encoding="utf-8")
        foreign = leaf / "impact-foreign.json"
        foreign.write_text("{\"foreign\":true}\n", encoding="utf-8")
        before = foreign.read_bytes()
        expected_impact = leaf / f"impact-{first_payload['impact_plan']['content_hash']}.json"
        expected_rollback = leaf / f"rollback-{first_payload['rollback_plan']['content_hash']}.json"

        try:
            result = plan_drift(pair.manifest_hash)
            payload = result.cli_result.as_dict()
            after = foreign.read_bytes()
            lock_after = lock_path.read_bytes()
        finally:
            _owned_rmtree(root)
    assert result.exit_code == 7
    assert payload["error"]["phase"] == "OUTPUT"
    assert payload["error"]["code"] in {"DRIFT_OUTPUT_COLLISION", "DRIFT_OUTPUT_WRITE_FAILED"}
    assert payload["impact_plan"] is None
    assert payload["rollback_plan"] is None
    assert payload["executed"] is False
    assert after == before
    assert lock_after == b"{\"owner\":\"foreign\"}\n"
    assert not expected_impact.exists()
    assert not expected_rollback.exists()


def test_v2s3_fm25_wsl_symlink_special_unreadable_crlf_case_depth_and_size_edges() -> None:
    bounds = _spec()["runtime_boundaries"]["read_and_structure_limits"]
    assert bounds["maximum_path_characters"] if "maximum_path_characters" in bounds else True
    manifest_hash = "f" * 64
    with _snapshot_leaf(manifest_hash) as leaf:
        deep = leaf
        for idx in range(1, 14):
            deep = deep / f"segment-{idx}"
        deep.mkdir(parents=True, exist_ok=True)
        crlf_file = leaf / "v-crlf.json"
        crlf_file.write_bytes(b"{\"x\":1}\r\n")
        unreadable = leaf / "d-unreadable.json"
        unreadable.write_text("{\"x\":2}\n", encoding="utf-8")
        unreadable.chmod(stat.S_IWUSR)
        with pytest.raises(Exception) as exc_info:
            load_v2_s2_artifact_pair(manifest_hash)
        input_code = getattr(exc_info.value, "code", None)
        plan = plan_drift(manifest_hash)
        payload = plan.cli_result.as_dict()
        unreadable.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert input_code in {"DRIFT_INPUT_ARTIFACT_SET_INVALID", "DRIFT_ARTIFACT_READ_FAILED", "DRIFT_ARTIFACT_CANONICAL_BYTES_INVALID"}
    assert payload["error"]["code"] in {"DRIFT_INPUT_ARTIFACT_SET_INVALID", "DRIFT_ARTIFACT_READ_FAILED", "DRIFT_ARTIFACT_CANONICAL_BYTES_INVALID"}
