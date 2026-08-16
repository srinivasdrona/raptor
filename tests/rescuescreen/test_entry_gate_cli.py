from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_MANIFEST_PATH = REPO_ROOT / "configs" / "rescuescreen" / "entry_gates.yaml"


def _require_cli_module() -> None:
    try:
        spec = importlib.util.find_spec("raptor.rescuescreen.cli")
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        pytest.fail("implementation missing: raptor.rescuescreen.cli")


def _require_committed_manifest_path() -> Path:
    if not COMMITTED_MANIFEST_PATH.is_file():
        pytest.fail(f"implementation missing: {COMMITTED_MANIFEST_PATH}")
    return COMMITTED_MANIFEST_PATH


def _read_committed_manifest_mapping() -> dict[str, Any]:
    parsed = yaml.safe_load(_require_committed_manifest_path().read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), "committed manifest must parse to a mapping"
    return parsed


def _oracle_manifest_content_hash(manifest_mapping: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(manifest_mapping))
    payload.pop("manifest_content_hash", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _with_valid_manifest_hash(manifest_mapping: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(manifest_mapping))
    payload["manifest_content_hash"] = _oracle_manifest_content_hash(payload)
    return payload


def _valid_evidence_ref(index: int) -> dict[str, str]:
    return {
        "artifact_id": f"artifact-{index}",
        "artifact_schema": "atlas.claim.bundle.v1",
        "content_hash": "a" * 64,
        "reviewed_by": f"reviewer-{index}",
        "reviewed_at": f"2026-08-{index:02d}T00:00:00Z",
    }


def _all_satisfied_manifest_from(base_manifest: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(base_manifest))
    gates = payload.get("gates", [])
    assert isinstance(gates, list), "manifest gates must be a list in test fixture"
    for index, gate in enumerate(gates, start=1):
        assert isinstance(gate, dict), "manifest gate must be a mapping in test fixture"
        gate["status"] = "SATISFIED"
        gate["evidence_refs"] = [_valid_evidence_ref(index)]
        gate["note"] = f"{gate.get('gate_id', f'gate-{index}')} reviewed evidence registered"
    return _with_valid_manifest_hash(payload)


def _write_manifest(tmp_path: Path, file_name: str, manifest_mapping: Mapping[str, Any]) -> Path:
    rendered = yaml.safe_dump(manifest_mapping, sort_keys=False, allow_unicode=True)
    out_path = tmp_path / file_name
    out_path.write_bytes(rendered.encode("utf-8"))
    return out_path


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    src = str(REPO_ROOT / "src")
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return env


def _run_status(manifest_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "raptor.rescuescreen.cli",
            "status",
            "--manifest",
            str(manifest_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=_cli_env(),
    )


def _parse_cli_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    text = result.stdout.strip() or result.stderr.strip()
    assert text, "CLI returned no JSON output"
    payload = json.loads(text)
    assert isinstance(payload, dict), "CLI JSON must be an object"
    return payload


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def test_rseg_ac09_cli_committed_manifest_exits_3_and_is_deterministic_json() -> None:
    _require_cli_module()
    manifest_path = _require_committed_manifest_path()

    first = _run_status(manifest_path)
    second = _run_status(manifest_path)
    assert first.returncode == 3, first.stderr or first.stdout
    assert second.returncode == 3, second.stderr or second.stdout

    first_payload = _parse_cli_json(first)
    second_payload = _parse_cli_json(second)
    assert _canonical_json_bytes(first_payload) == _canonical_json_bytes(second_payload)

    assert first_payload["schema"] == "rescuescreen.entry_gate_status.v1"
    assert first_payload["overall_status"] == "BLOCKED"
    assert first_payload["first_blocking_gate"] == "EG-1"
    assert first_payload["blocking_fail_state"] == "MECHANISM_UNVERIFIED"
    assert first_payload["eligible_next_stage"] is None
    assert first_payload["stage_execution_authorized"] is False


def test_rseg_ac09_cli_all_satisfied_fixture_exits_0_ready_for_s1_but_not_authorized(tmp_path: Path) -> None:
    _require_cli_module()
    all_satisfied = _all_satisfied_manifest_from(_read_committed_manifest_mapping())
    manifest_path = _write_manifest(tmp_path, "all_satisfied.yaml", all_satisfied)

    first = _run_status(manifest_path)
    second = _run_status(manifest_path)
    assert first.returncode == 0, first.stderr or first.stdout
    assert second.returncode == 0, second.stderr or second.stdout

    first_payload = _parse_cli_json(first)
    second_payload = _parse_cli_json(second)
    assert _canonical_json_bytes(first_payload) == _canonical_json_bytes(second_payload)

    assert first_payload["overall_status"] == "READY_FOR_S1_REVIEW"
    assert first_payload["eligible_next_stage"] == "S1"
    assert first_payload["stage_execution_authorized"] is False


def test_rseg_ac09_cli_invalid_manifest_exits_2_with_deterministic_json(tmp_path: Path) -> None:
    _require_cli_module()
    invalid_manifest = _all_satisfied_manifest_from(_read_committed_manifest_mapping())
    invalid_manifest.pop("lane_id", None)
    invalid_manifest = _with_valid_manifest_hash(invalid_manifest)
    manifest_path = _write_manifest(tmp_path, "invalid.yaml", invalid_manifest)

    first = _run_status(manifest_path)
    second = _run_status(manifest_path)
    assert first.returncode == 2, first.stderr or first.stdout
    assert second.returncode == 2, second.stderr or second.stdout

    first_payload = _parse_cli_json(first)
    second_payload = _parse_cli_json(second)
    assert _canonical_json_bytes(first_payload) == _canonical_json_bytes(second_payload)


def test_rseg_ac09_cli_corrupt_inputs_exit_2_without_tracebacks(tmp_path: Path) -> None:
    _require_cli_module()
    non_utf8_path = tmp_path / "non_utf8.yaml"
    non_utf8_path.write_bytes(b"\xff\xfe\x00")
    non_string_key = _read_committed_manifest_mapping()
    non_string_key[123] = "value"
    non_string_key["extra"] = "value"
    non_string_key_path = _write_manifest(
        tmp_path,
        "non_string_key.yaml",
        non_string_key,
    )
    recursive_alias_path = tmp_path / "recursive_alias.yaml"
    recursive_alias_path.write_text("&root\ngates: *root\n", encoding="utf-8")
    deep_nesting_path = tmp_path / "deep_nesting.yaml"
    deep_nesting_path.write_text(
        "gates: " + ("[" * 1_000) + "value" + ("]" * 1_000) + "\n",
        encoding="utf-8",
    )

    for manifest_path in (
        non_utf8_path,
        non_string_key_path,
        recursive_alias_path,
        deep_nesting_path,
    ):
        first = _run_status(manifest_path)
        second = _run_status(manifest_path)
        assert first.returncode == 2, first.stderr or first.stdout
        assert second.returncode == 2, second.stderr or second.stdout
        assert "Traceback" not in first.stderr
        assert "Traceback" not in second.stderr

        first_payload = _parse_cli_json(first)
        second_payload = _parse_cli_json(second)
        assert first_payload["schema"] == "rescuescreen.entry_gate_error.v1"
        assert _canonical_json_bytes(first_payload) == _canonical_json_bytes(second_payload)
