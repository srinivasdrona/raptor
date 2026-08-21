from __future__ import annotations

import json
import os
import stat
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from raptor.sourceops.drift_planning import load_materiality_policy, plan_drift
from tests.sourceops.test_drift_planning_contract import _representative_pair

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-s3-drift-gates.yaml"
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


def _run_cli_bytes(*args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=False,
        env=env,
    )


def _assert_canonical_json_stdout_and_empty_stderr(result: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    assert result.stderr == b"", f"stderr must be empty for handled plan-drift results, got {result.stderr!r}"
    assert result.stdout.endswith(b"\n"), "stdout must end with exactly one LF"
    assert not result.stdout.endswith(b"\r\n"), "stdout must not end with CRLF"
    assert result.stdout.count(b"\n") == 1, "stdout must contain exactly one JSON line"
    decoded = result.stdout.decode("utf-8")
    payload = json.loads(decoded)
    assert isinstance(payload, dict), "stdout must be one top-level JSON object"
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    assert decoded == canonical, "plan-drift stdout must already be canonical JSON"
    return payload


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


def test_v2s3_ac21_plan_drift_cli_json_stderr_and_exit_partition() -> None:
    sentinel_leaf = DRIFT_OUTPUT_PARENT / f"preexisting-sentinel-{uuid.uuid4().hex}" / "policy-proof"
    sentinel_leaf.mkdir(parents=True, exist_ok=False)
    sentinel_path = sentinel_leaf / "sentinel.json"
    sentinel_bytes = b"{\"scope\":\"preexisting\"}\n"
    sentinel_path.write_bytes(sentinel_bytes)
    preexisting_snapshot = _snapshot_runtime_namespace()
    generated_leaf: Path | None = None
    spec = _spec()["cli_contract"]
    try:
        with _representative_pair("no-change") as pair:
            result = _run_cli_bytes("plan-drift", "--manifest-hash", pair.manifest_hash)
            payload = _assert_canonical_json_stdout_and_empty_stderr(result)
            assert result.returncode in {0, 2, 4, 5, 6, 7, 8, 70}
            stdout_contract = spec["stdout"]
            assert set(payload.keys()) == set(stdout_contract["top_level_required_exact"])
            assert payload["schema"] == stdout_contract["constants"]["schema"]
            assert payload["command"] == "plan-drift"
            assert payload["proposal_only"] is True
            assert payload["approval_required"] is True
            assert payload["approval_state"] == "NOT_GRANTED"
            assert payload["executed"] is False
            assert payload["input_validity"] == "VALID"
            assert payload["baseline_validity"] == "VALID"
            assert payload["policy_validity"] == "VALID"
            assert isinstance(payload["impact_plan"], dict)
            assert isinstance(payload["rollback_plan"], dict)
            generated_leaf = (REPO_ROOT / payload["impact_plan"]["path"]).resolve().parent
            assert generated_leaf.exists()
        after_generation = _snapshot_runtime_namespace()
        _remove_created_runtime_paths(preexisting_snapshot, after_generation)
        final_snapshot = _snapshot_runtime_namespace()
        _assert_preexisting_runtime_paths_unchanged(preexisting_snapshot, final_snapshot)
        assert sentinel_path.read_bytes() == sentinel_bytes
        assert generated_leaf is not None and not generated_leaf.exists()
    finally:
        sentinel_path.unlink(missing_ok=True)
        try:
            sentinel_leaf.rmdir()
        except OSError:
            pass
        try:
            sentinel_leaf.parent.rmdir()
        except OSError:
            pass


def test_v2s3_fm01_manifest_hash_is_the_only_input_selector() -> None:
    invalid_invocations = (
        ("plan-drift",),
        ("plan-drift", "--manifest-hash", "ABCDEF" * 10 + "abcd"),
        ("plan-drift", "--manifest-hash", "not-a-hash"),
        ("plan-drift", "--manifest-hash", "../" + ("0" * 61)),
        ("plan-drift", "--manifest-hash", "0" * 64, "--manifest-hash", "1" * 64),
        ("plan-drift", "--manifest-hash", "0" * 64, "extra"),
    )
    for argv in invalid_invocations:
        result = _run_cli_bytes(*argv)
        payload = _assert_canonical_json_stdout_and_empty_stderr(result)
        assert result.returncode == 2
        assert payload["error"]["code"] == "CLI_USAGE_ERROR"
        assert payload["command"] == "plan-drift"


def test_v2s3_fm08_policy_threshold_and_path_overrides_are_usage_errors() -> None:
    policy = load_materiality_policy()
    assert policy.policy_id == "raptor-v2-s3-materiality-v1"
    valid_hash = "1" * 64
    forbidden = _spec()["cli_contract"]["new_command"]["forbidden_arguments"]
    probes = [
        ("plan-drift", "--manifest-hash", valid_hash, "--policy", "configs/sourceops/materiality_policy.yaml"),
        ("plan-drift", "--manifest-hash", valid_hash, "--threshold", "0.4"),
        ("plan-drift", "--manifest-hash", valid_hash, "--output-root", ".raptor/sourceops/generated/drift-plans"),
    ]
    for argv in probes:
        result = _run_cli_bytes(*argv)
        payload = _assert_canonical_json_stdout_and_empty_stderr(result)
        assert result.returncode == 2
        assert payload["error"]["code"] == "CLI_USAGE_ERROR"
    assert "--policy" in forbidden and "--threshold" in forbidden and "--output-root" in forbidden


def test_v2s3_fm23_time_locale_hash_seed_and_mtime_do_not_change_bytes() -> None:
    env_cases = (
        {"TZ": "UTC", "LC_ALL": "C", "PYTHONHASHSEED": "0"},
        {"TZ": "Asia/Kolkata", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "1"},
    )
    with _representative_pair("no-change") as pair:
        plan_result = plan_drift(pair.manifest_hash)
        plan_payload = plan_result.cli_result.as_dict()
        assert plan_result.exit_code in {0, 8}
        assert plan_payload["error"] is None

        first = _run_cli_bytes("plan-drift", "--manifest-hash", pair.manifest_hash, env_overrides=env_cases[0])
        first_payload = _assert_canonical_json_stdout_and_empty_stderr(first)
        second = _run_cli_bytes("plan-drift", "--manifest-hash", pair.manifest_hash, env_overrides=env_cases[1])
        second_payload = _assert_canonical_json_stdout_and_empty_stderr(second)
        try:
            assert first.returncode == second.returncode
            assert first.stdout == second.stdout
            assert first_payload == second_payload
            assert first_payload == plan_payload
        finally:
            _cleanup_drift_output(first_payload)
