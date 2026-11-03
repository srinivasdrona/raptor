from __future__ import annotations

import copy
import functools
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "configs" / "sourceops" / "source_registry.yaml"
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-s2-staged-snapshot.yaml"
STAGING_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "staging"
OUTPUT_PARENT = REPO_ROOT / ".raptor" / "sourceops" / "generated" / "staged-snapshots"
CANONICAL_REGISTRY_REL = "configs/sourceops/source_registry.yaml"
FORBIDDEN_DIFF_KEYS = {
    "ready",
    "blocked",
    "lifecycle_state",
    "materiality",
    "severity",
    "approval",
    "recommendation",
    "promote",
    "action",
    "consumer_impacts",
    "rollback",
}

MIXED_IDENTIFIER_WRONG_TYPE_CASES = (
    ("files-file-id-int", "files", "file_id", 7),
    ("files-file-id-bool", "files", "file_id", False),
    ("content-bindings-binding-id-float", "content_bindings", "binding_id", 3.5),
    ("content-bindings-binding-id-null", "content_bindings", "binding_id", None),
)

NON_STRING_MAPPING_KEY_CASE_IDS = (
    "top-level-int-key",
    "source-binding-bool-on-key",
    "files-checksum-float-key",
    "content-binding-null-key",
)

NON_FINITE_YAML_FLOAT_TOKENS = (".nan", ".inf", "-.inf")

NON_FINITE_WRONG_TYPE_VALUE_CASES = (
    ("release-date-nan", "release_date", ".nan"),
    ("release-date-inf", "release_date", ".inf"),
    ("release-date-neg-inf", "release_date", "-.inf"),
    ("checksum-bytes-nan", "canonical_lf_utf8_bytes", ".nan"),
    ("checksum-bytes-inf", "canonical_lf_utf8_bytes", ".inf"),
    ("checksum-bytes-neg-inf", "canonical_lf_utf8_bytes", "-.inf"),
)

UNHASHABLE_MANIFEST_FIELD_CASES = (
    ("candidate-record-kind", "candidate.identity.record_kind"),
    ("files-role", "files[0].role"),
    ("files-media-type", "files[0].media_type"),
    ("files-checksum-mode", "files[0].checksum.mode"),
    ("content-binding-baseline-kind", "content_bindings[0].baseline_kind"),
    ("content-binding-none-candidate-file-id", "content_bindings[none].candidate_file_id"),
)

UNHASHABLE_CONTAINER_VALUE_CASES = (
    ("yaml-sequence", ["unhashable-sequence-probe"]),
    ("yaml-mapping", {"unhashable": "mapping-probe"}),
)

UNHASHABLE_CONTAINER_FIELD_CASES = tuple(
    (f"{field_case_id}-{shape_case_id}", field_case_id, field_subject, wrong_value)
    for field_case_id, field_subject in UNHASHABLE_MANIFEST_FIELD_CASES
    for shape_case_id, wrong_value in UNHASHABLE_CONTAINER_VALUE_CASES
)

UNHASHABLE_SCALAR_CONTROL_CASES = (
    ("candidate-record-kind-scalar-int", "candidate-record-kind", 7),
    ("files-role-scalar-int", "files-role", 11),
    ("files-media-type-scalar-int", "files-media-type", 13),
    ("files-checksum-mode-scalar-int", "files-checksum-mode", 17),
    ("content-binding-baseline-kind-scalar-int", "content-binding-baseline-kind", 19),
    ("content-binding-none-candidate-file-id-scalar-int", "content-binding-none-candidate-file-id", 23),
)


@functools.lru_cache(maxsize=1)
def _spec() -> dict[str, Any]:
    loaded = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail("V2-S2 spec must parse into a mapping")
    return loaded


def _validation_ceiling() -> str:
    ceiling = _spec()["product_contract"]["validation_ceiling"]
    if not isinstance(ceiling, str) or not ceiling.strip():
        pytest.fail("spec product_contract.validation_ceiling must be a non-empty string")
    return ceiling


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_manifest_hash(manifest: dict[str, Any]) -> str:
    basis = copy.deepcopy(manifest)
    basis.pop("manifest_content_hash", None)
    return _sha256_hex(_canonical_json_bytes(basis))


def _canonical_lf_bytes(raw: bytes) -> bytes:
    text = raw.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _checksum_raw(raw: bytes) -> dict[str, Any]:
    return {
        "mode": "RAW_BYTES",
        "raw_byte_size": len(raw),
        "raw_sha256": _sha256_hex(raw),
        "canonical_lf_utf8_bytes": None,
        "canonical_lf_sha256": None,
    }


def _checksum_canonical_text(raw: bytes) -> dict[str, Any]:
    canonical = _canonical_lf_bytes(raw)
    return {
        "mode": "CANONICAL_LF_TEXT",
        "raw_byte_size": None,
        "raw_sha256": None,
        "canonical_lf_utf8_bytes": len(canonical),
        "canonical_lf_sha256": _sha256_hex(canonical),
    }


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


def _run_cli_bytes(*args: str) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=False,
        env=env,
    )


def _run_verify_stage(staging_root_rel: str, *, registry_rel: str = CANONICAL_REGISTRY_REL) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        "verify-stage",
        "--registry",
        registry_rel,
        "--staging-root",
        staging_root_rel,
    )


def _run_verify_stage_bytes(
    staging_root_rel: str,
    *,
    registry_rel: str = CANONICAL_REGISTRY_REL,
) -> subprocess.CompletedProcess[bytes]:
    return _run_cli_bytes(
        "verify-stage",
        "--registry",
        registry_rel,
        "--staging-root",
        staging_root_rel,
    )


def _parse_json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if not result.stdout.strip():
        pytest.fail(
            "verify-stage must emit one deterministic JSON object on stdout.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"stdout is not valid JSON: {exc}\nstdout={result.stdout!r}\nstderr={result.stderr!r}")
    if not isinstance(payload, dict):
        pytest.fail("verify-stage stdout JSON must be a top-level object")
    return payload


def _assert_stdout_one_line_json(result: subprocess.CompletedProcess[str]) -> None:
    assert result.stdout.endswith("\n"), "stdout must end with exactly one LF"
    assert result.stdout.count("\n") == 1, "stdout must contain exactly one JSON line"
    assert result.stderr == "", f"stderr must be empty for handled results, got: {result.stderr!r}"


def _assert_stdout_bytes_one_lf_canonical_json_and_empty_stderr(result: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    assert result.stderr == b"", f"stderr must be empty bytes for handled results, got: {result.stderr!r}"
    assert result.stdout.endswith(b"\n"), "stdout must end with exactly one LF byte"
    assert not result.stdout.endswith(b"\r\n"), "stdout must not end with CRLF"
    assert result.stdout.count(b"\n") == 1, "stdout must contain exactly one JSON line"
    decoded = result.stdout.decode("utf-8")
    payload = json.loads(decoded)
    assert isinstance(payload, dict), "stdout payload must be a JSON object"
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    assert decoded == canonical, "stdout JSON must already be canonical and single-line"
    return payload


def _assert_json_compatible_with_allow_nan_false(value: Any, *, label: str) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        pytest.fail(f"{label} must be JSON-compatible with allow_nan=false: {exc}\nvalue={value!r}")


def _load_registry_payload() -> dict[str, Any]:
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        pytest.fail("source_registry.yaml must parse into a mapping")
    return payload


def _source_record(payload: dict[str, Any], source_id: str) -> dict[str, Any]:
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("registry source_records must be a list")
    for record in records:
        if isinstance(record, dict) and record.get("source_id") == source_id:
            return copy.deepcopy(record)
    pytest.fail(f"source_id not found: {source_id!r}")


def _candidate_from_source(source: dict[str, Any], *, snapshot_id: str) -> dict[str, Any]:
    identity = {
        "display_name": source["display_name"],
        "record_kind": source["record_kind"],
        "owner": source["owner"],
        "authoritative_locator": source["authoritative_locator"],
    }
    release = {
        "version_or_snapshot": source["release"]["version_or_snapshot"],
        "release_date": source["release"]["release_date"],
        "retrieved_at": source["release"]["retrieved_at"],
        "content_pin_status": source["release"]["content_pin_status"],
    }
    return {
        "snapshot_id": snapshot_id,
        "identity": identity,
        "release": release,
        "licence": copy.deepcopy(source["licence"]),
        "acquisition": copy.deepcopy(source["acquisition"]),
    }


def _complete_component_projection(source: dict[str, Any]) -> dict[str, Any]:
    components = []
    for component in source.get("components") or []:
        if not isinstance(component, dict):
            pytest.fail("source components must be mappings")
        components.append(
            {
                "component_id": component["component_id"],
                "display_name": component["display_name"],
                "source_role": component["source_role"],
                "version_or_snapshot": component["version_or_snapshot"],
                "licence_status": component["licence_status"],
                "declaration_locator": component["declaration_locator"],
            }
        )
    components.sort(key=lambda row: row["component_id"])
    return {"mode": "COMPLETE", "components": components}


def _build_manifest(
    *,
    source: dict[str, Any],
    registry_hash: str,
    observed_at: str,
    snapshot_id: str,
    files: list[dict[str, Any]],
    content_bindings: list[dict[str, Any]],
    component_projection: dict[str, Any] | None,
    candidate_mutator: Any | None = None,
) -> dict[str, Any]:
    candidate = _candidate_from_source(source, snapshot_id=snapshot_id)
    if callable(candidate_mutator):
        candidate_mutator(candidate)
    files_sorted = sorted(files, key=lambda row: row["file_id"])
    bindings_sorted = sorted(content_bindings, key=lambda row: row["binding_id"])
    manifest = {
        "schema": _spec()["manifest_contract"]["schema_id"],
        "manifest_content_hash": "0" * 64,
        "hash_basis": _spec()["manifest_contract"]["hash_basis"],
        "observed_at": observed_at,
        "source_binding": {
            "source_id": source["source_id"],
            "registry_content_hash": registry_hash,
            "declaration_refs": copy.deepcopy(source["declaration_refs"]),
        },
        "candidate": candidate,
        "files": files_sorted,
        "content_bindings": bindings_sorted,
        "component_projection": component_projection,
    }
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    return manifest


@contextmanager
def _stage_case(
    *,
    prefix: str,
    manifest: dict[str, Any],
    files: dict[str, bytes],
    manifest_newline: str = "\n",
) -> Iterator[tuple[Path, str]]:
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"{prefix}-{uuid.uuid4().hex[:12]}"
    stage_root = STAGING_PARENT / stage_name
    stage_root.mkdir(parents=False, exist_ok=False)
    try:
        for rel_path, raw in files.items():
            path = stage_root / Path(rel_path.replace("/", os.sep))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        dumped = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
        if manifest_newline != "\n":
            dumped = dumped.replace("\n", manifest_newline)
        (stage_root / "manifest.yaml").write_text(dumped, encoding="utf-8", newline="")
        yield stage_root, f".raptor/sourceops/staging/{stage_name}"
    finally:
        _remove_path(stage_root)


@contextmanager
def _stage_case_with_raw_manifest(
    *,
    prefix: str,
    manifest_bytes: bytes,
    files: dict[str, bytes] | None = None,
) -> Iterator[tuple[Path, str]]:
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"{prefix}-{uuid.uuid4().hex[:12]}"
    stage_root = STAGING_PARENT / stage_name
    stage_root.mkdir(parents=False, exist_ok=False)
    try:
        for rel_path, raw in (files or {}).items():
            path = stage_root / Path(rel_path.replace("/", os.sep))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (stage_root / "manifest.yaml").write_bytes(manifest_bytes)
        yield stage_root, f".raptor/sourceops/staging/{stage_name}"
    finally:
        _remove_path(stage_root)


def _remove_path(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except (FileNotFoundError, OSError):
        return

    if stat.S_ISLNK(mode) or stat.S_ISREG(mode):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError:
            try:
                os.chmod(path, 0o700)
                path.unlink(missing_ok=True)
            except OSError:
                return
        return

    if stat.S_ISDIR(mode):
        try:
            for child in list(path.iterdir()):
                _remove_path(child)
            path.rmdir()
            return
        except (FileNotFoundError, OSError):
            pass

        def _onerror(func: Any, target: str, _exc_info: Any) -> None:
            try:
                os.chmod(target, 0o700)
                func(target)
            except OSError:
                return

        try:
            shutil.rmtree(path, onerror=_onerror)
            return
        except OSError:
            pass

    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _replace_once(payload: str, needle: str, replacement: str, *, case_id: str) -> str:
    if needle not in payload:
        pytest.fail(f"{case_id}: expected YAML marker not found: {needle!r}")
    replaced = payload.replace(needle, replacement, 1)
    if replaced == payload:
        pytest.fail(f"{case_id}: YAML replacement did not mutate payload")
    return replaced


def _replace_yaml_line_value(payload: str, *, field_name: str, value_token: str, case_id: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(field_name)}:\s*).*$", flags=re.MULTILINE)
    replaced, count = pattern.subn(rf"\1{value_token}", payload, count=1)
    if count != 1:
        pytest.fail(f"{case_id}: expected exactly one YAML line for field {field_name!r}, got {count}")
    if replaced == payload:
        pytest.fail(f"{case_id}: YAML replacement for field {field_name!r} did not mutate payload")
    return replaced


def _build_manifest_yaml_with_non_string_mapping_key(case_id: str) -> tuple[bytes, dict[str, bytes]]:
    manifest, files = _build_no_change_case(projection_complete=False)
    dumped = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)

    if case_id == "top-level-int-key":
        mutated = "7: non-string-top-level-key-probe\n" + dumped
    elif case_id == "source-binding-bool-on-key":
        mutated = _replace_once(
            dumped,
            "source_binding:\n",
            "source_binding:\n  on: non-string-source-binding-key-probe\n",
            case_id=case_id,
        )
    elif case_id == "files-checksum-float-key":
        mutated = _replace_once(
            dumped,
            "  checksum:\n",
            "  checksum:\n    3.5: non-string-checksum-key-probe\n",
            case_id=case_id,
        )
    elif case_id == "content-binding-null-key":
        mutated = _replace_once(
            dumped,
            "content_bindings:\n- binding_id: bind-declaration\n",
            "content_bindings:\n- null: non-string-content-binding-key-probe\n  binding_id: bind-declaration\n",
            case_id=case_id,
        )
    else:  # pragma: no cover - test authoring guard
        pytest.fail(f"unknown non-string key case id: {case_id!r}")
    return mutated.encode("utf-8"), files


def _build_manifest_yaml_with_non_finite_mapping_keys(non_finite_token: str) -> tuple[bytes, dict[str, bytes]]:
    manifest, files = _build_no_change_case(projection_complete=False)
    dumped = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    mutated = f"{non_finite_token}: non-finite-top-level-key-probe\n" + dumped
    mutated = _replace_once(
        mutated,
        "source_binding:\n",
        f"source_binding:\n  {non_finite_token}: non-finite-nested-key-probe\n",
        case_id=f"non-finite-mapping-key-{non_finite_token}",
    )
    return mutated.encode("utf-8"), files


def _build_manifest_yaml_with_non_finite_wrong_type_value(
    *,
    case_id: str,
    field_name: str,
    value_token: str,
) -> tuple[bytes, dict[str, bytes]]:
    manifest, files = _build_no_change_case(projection_complete=False)
    dumped = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    if field_name not in {"release_date", "canonical_lf_utf8_bytes"}:
        pytest.fail(f"{case_id}: unsupported non-finite wrong-type field {field_name!r}")
    mutated = _replace_yaml_line_value(
        dumped,
        field_name=field_name,
        value_token=value_token,
        case_id=case_id,
    )
    return mutated.encode("utf-8"), files


def _build_manifest_yaml_with_deep_flow_sequence(depth: int) -> bytes:
    if depth <= 0:
        pytest.fail(f"depth must be positive, got {depth}")
    nested = "[" * depth + "0" + "]" * depth
    raw = f"schema: raptor.sourceops.staged_snapshot_manifest.v1\nprobe: {nested}\n".encode("utf-8")
    limit = int(_spec()["manifest_contract"]["raw_manifest_limits"]["maximum_bytes"])
    assert len(raw) < limit, "deep-flow-sequence probe must stay below raw manifest byte limit"
    return raw


def _build_manifest_yaml_with_string_unknown_key_control() -> tuple[bytes, dict[str, bytes]]:
    manifest, files = _build_no_change_case(projection_complete=False)
    dumped = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    mutated = "unknown_schema_probe_key: control\n" + dumped
    return mutated.encode("utf-8"), files


def _none_baseline_binding_row(manifest: dict[str, Any]) -> dict[str, Any]:
    bindings = manifest.get("content_bindings")
    if not isinstance(bindings, list):
        pytest.fail("unhashable probe fixture requires content_bindings to be a list")
    for row in bindings:
        if isinstance(row, dict) and row.get("baseline_kind") == "NONE":
            return row
    pytest.fail("unhashable probe fixture requires at least one content binding with baseline_kind NONE")


def _apply_unhashable_manifest_probe_value(
    manifest: dict[str, Any],
    *,
    field_case_id: str,
    value: Any,
) -> None:
    if field_case_id == "candidate-record-kind":
        manifest["candidate"]["identity"]["record_kind"] = value
    elif field_case_id == "files-role":
        manifest["files"][0]["role"] = value
    elif field_case_id == "files-media-type":
        manifest["files"][0]["media_type"] = value
    elif field_case_id == "files-checksum-mode":
        manifest["files"][0]["checksum"]["mode"] = value
    elif field_case_id == "content-binding-baseline-kind":
        manifest["content_bindings"][0]["baseline_kind"] = value
    elif field_case_id == "content-binding-none-candidate-file-id":
        _none_baseline_binding_row(manifest)["candidate_file_id"] = value
    else:  # pragma: no cover - test authoring guard
        pytest.fail(f"unknown unhashable field case id: {field_case_id!r}")


def _current_unhashable_manifest_probe_string_value(
    manifest: dict[str, Any],
    *,
    field_case_id: str,
) -> str:
    if field_case_id == "candidate-record-kind":
        value = manifest["candidate"]["identity"]["record_kind"]
    elif field_case_id == "files-role":
        value = manifest["files"][0]["role"]
    elif field_case_id == "files-media-type":
        value = manifest["files"][0]["media_type"]
    elif field_case_id == "files-checksum-mode":
        value = manifest["files"][0]["checksum"]["mode"]
    elif field_case_id == "content-binding-baseline-kind":
        value = manifest["content_bindings"][0]["baseline_kind"]
    elif field_case_id == "content-binding-none-candidate-file-id":
        value = _none_baseline_binding_row(manifest).get("candidate_file_id")
    else:  # pragma: no cover - test authoring guard
        pytest.fail(f"unknown unhashable field case id: {field_case_id!r}")
    if not isinstance(value, str) or not value:
        pytest.fail(f"{field_case_id}: expected non-empty string control value, got {value!r}")
    return value


def _remove_output_leaf(manifest_hash: str) -> None:
    leaf = OUTPUT_PARENT / manifest_hash
    _remove_path(leaf)


def _artifact_abs_path(ref: dict[str, Any]) -> Path:
    path_value = ref.get("path")
    assert isinstance(path_value, str) and path_value.strip(), f"artifact path is invalid: {ref}"
    return REPO_ROOT / Path(path_value.replace("/", os.sep))


def _assert_self_excluding_hash(payload: dict[str, Any]) -> str:
    declared = payload.get("artifact_content_hash")
    assert isinstance(declared, str) and re.fullmatch(r"[0-9a-f]{64}", declared), "artifact_content_hash must be lowercase SHA-256"
    basis = copy.deepcopy(payload)
    basis.pop("artifact_content_hash", None)
    assert declared == _sha256_hex(_canonical_json_bytes(basis)), "artifact_content_hash mismatch"
    return declared


def _assert_no_forbidden_keys(node: Any) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            assert key not in FORBIDDEN_DIFF_KEYS, f"forbidden key in diff surface: {key!r}"
            _assert_no_forbidden_keys(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_forbidden_keys(item)


def _error_code(report: dict[str, Any]) -> str | None:
    error = report.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    return None


@functools.lru_cache(maxsize=1)
def _error_catalog() -> dict[str, dict[str, Any]]:
    rows = _spec()["error_contract"]["errors"]
    if not isinstance(rows, list):
        pytest.fail("error_contract.errors must be a list")
    table: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("code"), str):
            table[row["code"]] = row
    return table


def _assert_exact_error_from_authority(
    report: dict[str, Any],
    *,
    expected_code: str,
    expected_exit: int,
) -> dict[str, Any]:
    error = report.get("error")
    assert isinstance(error, dict), f"error envelope must be a mapping, got {error!r}"
    required = set(_spec()["error_contract"]["error_envelope_required_exact"])
    assert set(error) == required
    authority = _error_catalog()[expected_code]
    assert expected_exit == authority["exit"]
    assert error["code"] == authority["code"] == expected_code
    assert error["type"] == authority["type"]
    assert error["phase"] == authority["phase"]
    assert error["message"] == authority["message"]
    return error


def _build_no_change_case(*, projection_complete: bool) -> tuple[dict[str, Any], dict[str, bytes]]:
    registry = _load_registry_payload()
    source = _source_record(registry, "tsc-ingest-and-reference-declarations")
    tsc_bytes = (REPO_ROOT / "configs" / "ingest" / "tsc.yaml").read_bytes()
    decl_file_id = "decl-tsc-yaml"
    decl_rel = "candidate/ingest/tsc.yaml"
    files = [
        {
            "file_id": decl_file_id,
            "path": decl_rel,
            "role": "CANDIDATE_DECLARATION",
            "media_type": "application/x-yaml",
            "checksum": _checksum_canonical_text(tsc_bytes),
            "component_ids": [],
        }
    ]
    bindings = [
        {
            "binding_id": "bind-declaration",
            "baseline_kind": "DECLARATION_REF",
            "baseline_id": source["declaration_refs"][0]["path"],
            "candidate_file_id": decl_file_id,
        }
    ]
    manifest = _build_manifest(
        source=source,
        registry_hash=registry["registry_content_hash"],
        observed_at="2026-08-17T05:00:00Z",
        snapshot_id="candidate-tsc-ingest-no-change-001",
        files=files,
        content_bindings=bindings,
        component_projection=_complete_component_projection(source) if projection_complete else None,
    )
    return manifest, {decl_rel: tsc_bytes}


def _build_two_file_two_binding_case() -> tuple[dict[str, Any], dict[str, bytes]]:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    files = copy.deepcopy(files)
    extra_raw = b"sequence-order-probe\n"
    extra_rel = "candidate/extra/sequence-order-probe.bin"
    manifest["files"].append(
        {
            "file_id": "zz-sequence-order-probe",
            "path": extra_rel,
            "role": "SNAPSHOT_CONTENT",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(extra_raw),
            "component_ids": [],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "zz-bind-sequence-order-probe",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "zz-sequence-order-probe",
        }
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files[extra_rel] = extra_raw
    return manifest, files


def _build_changed_case() -> tuple[dict[str, Any], dict[str, bytes]]:
    registry = _load_registry_payload()
    source = _source_record(registry, "tsc-ingest-and-reference-declarations")
    tsc_bytes = (REPO_ROOT / "configs" / "ingest" / "tsc.yaml").read_bytes()
    changed_decl = tsc_bytes + b"\n# staged-candidate-change\n"
    extra_raw = b"\x00staged-added-bytes\xff"
    files = [
        {
            "file_id": "decl-tsc-yaml",
            "path": "candidate/ingest/tsc.yaml",
            "role": "CANDIDATE_DECLARATION",
            "media_type": "application/x-yaml",
            "checksum": _checksum_canonical_text(changed_decl),
            "component_ids": [],
        },
        {
            "file_id": "extra-payload",
            "path": "candidate/extra/payload.bin",
            "role": "AUXILIARY_METADATA",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(extra_raw),
            "component_ids": [],
        },
    ]
    bindings = [
        {
            "binding_id": "bind-added-extra",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "extra-payload",
        },
        {
            "binding_id": "bind-declaration",
            "baseline_kind": "DECLARATION_REF",
            "baseline_id": source["declaration_refs"][0]["path"],
            "candidate_file_id": "decl-tsc-yaml",
        },
    ]
    projection = _complete_component_projection(source)
    if projection["components"]:
        projection["components"][0]["version_or_snapshot"] = "candidate-component-version-change"

    def _mutate_candidate(candidate: dict[str, Any]) -> None:
        candidate["release"]["version_or_snapshot"] = f"{candidate['release']['version_or_snapshot']}-candidate"

    manifest = _build_manifest(
        source=source,
        registry_hash=registry["registry_content_hash"],
        observed_at="2026-08-17T05:00:00Z",
        snapshot_id="candidate-tsc-ingest-changed-001",
        files=files,
        content_bindings=bindings,
        component_projection=projection,
        candidate_mutator=_mutate_candidate,
    )
    return manifest, {
        "candidate/ingest/tsc.yaml": changed_decl,
        "candidate/extra/payload.bin": extra_raw,
    }


def test_no_change_real_ingest_candidate_produces_deterministic_no_difference_artifacts() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-no-change", manifest=manifest, files=files) as (_, staging_rel):
            first = _run_verify_stage(staging_rel)
            _assert_stdout_one_line_json(first)
            assert first.returncode == 0, first.stdout
            first_report = _parse_json_stdout(first)

            second = _run_verify_stage(staging_rel)
            _assert_stdout_one_line_json(second)
            assert second.returncode == 0, second.stdout
            assert first.stdout == second.stdout, "successful verify-stage stdout must be byte-deterministic"
            report = _parse_json_stdout(second)

        cli_keys = set(_spec()["cli_contract"]["stdout"]["top_level_required_exact"])
        assert set(report) == cli_keys
        assert report["schema"] == _spec()["cli_contract"]["stdout"]["schema_id"]
        assert report["command"] == "verify-stage"
        assert report["run_status"] == "COMPLETED"
        assert report["input_validity"] == "VALID"
        assert report["stage_outcome"] == "OBSERVED_NO_DIFFERENCE"
        assert report["source_id"] == "tsc-ingest-and-reference-declarations"
        assert report["registry_content_hash"] == _load_registry_payload()["registry_content_hash"]
        assert report["manifest_content_hash"] == manifest_hash
        assert report["error"] is None
        assert report["validation_ceiling"] == _validation_ceiling()

        verification_ref = report["verification_artifact"]
        diff_ref = report["diff_artifact"]
        assert isinstance(verification_ref, dict) and isinstance(diff_ref, dict)
        v_path = _artifact_abs_path(verification_ref)
        d_path = _artifact_abs_path(diff_ref)
        assert v_path.parent == d_path.parent == OUTPUT_PARENT / manifest_hash
        assert v_path.is_file() and d_path.is_file()

        v_payload = json.loads(v_path.read_text(encoding="utf-8"))
        d_payload = json.loads(d_path.read_text(encoding="utf-8"))
        assert isinstance(v_payload, dict) and isinstance(d_payload, dict)
        assert set(v_payload) == set(_spec()["artifact_contracts"]["verification_artifact"]["top_level_required_exact"])
        assert set(d_payload) == set(_spec()["artifact_contracts"]["diff_artifact"]["top_level_required_exact"])
        assert v_payload["schema"] == _spec()["artifact_contracts"]["verification_artifact"]["schema_id"]
        assert d_payload["schema"] == _spec()["diff_model"]["schema_id"]
        assert v_payload["observed_at"] == manifest["observed_at"] == d_payload["observed_at"]
        assert v_payload["manifest_content_hash"] == manifest_hash == d_payload["manifest_content_hash"]
        assert v_payload["component_projection_status"] == "COMPLETE"
        assert d_payload["component_projection_status"] == "COMPLETE"
        assert d_payload["stage_outcome"] == "OBSERVED_NO_DIFFERENCE"
        assert d_payload["summary"]["classifications"]["ADDED"] == 0
        assert d_payload["summary"]["classifications"]["REMOVED"] == 0
        assert d_payload["summary"]["classifications"]["CHANGED"] == 0
        assert d_payload["summary"]["classifications"]["UNCHANGED"] == d_payload["summary"]["total_facts"] > 0
        assert all(fact["classification"] == "UNCHANGED" for fact in d_payload["facts"])
        _assert_no_forbidden_keys(d_payload)

        v_hash = _assert_self_excluding_hash(v_payload)
        d_hash = _assert_self_excluding_hash(d_payload)
        assert v_path.name == f"v-{v_hash}.json"
        assert d_path.name == f"d-{d_hash}.json"
        assert verification_ref["content_hash"] == v_hash
        assert diff_ref["content_hash"] == d_hash
    finally:
        _remove_output_leaf(manifest_hash)


def test_changed_candidate_produces_fact_only_observed_difference() -> None:
    manifest, files = _build_changed_case()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-changed", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(result)
        assert result.returncode == 0, result.stdout
        report = _parse_json_stdout(result)
        assert report["run_status"] == "COMPLETED"
        assert report["input_validity"] == "VALID"
        assert report["stage_outcome"] == "OBSERVED_DIFFERENCE"
        assert report["error"] is None

        diff_ref = report["diff_artifact"]
        assert isinstance(diff_ref, dict)
        diff_payload = json.loads(_artifact_abs_path(diff_ref).read_text(encoding="utf-8"))
        assert diff_payload["stage_outcome"] == "OBSERVED_DIFFERENCE"
        assert diff_payload["summary"]["classifications"]["ADDED"] >= 1
        assert diff_payload["summary"]["classifications"]["CHANGED"] >= 1
        assert diff_payload["summary"]["classifications"]["ADDED"] + diff_payload["summary"]["classifications"]["CHANGED"] + diff_payload["summary"]["classifications"]["REMOVED"] > 0
        assert any(fact["fact_path"] == "/release/version_or_snapshot" and fact["classification"] == "CHANGED" for fact in diff_payload["facts"])
        assert any(
            fact["classification"] == "ADDED"
            and fact["fact_kind"] == "MANIFEST"
            and fact["before"] == {"present": False, "value": None}
            for fact in diff_payload["facts"]
        )
        _assert_no_forbidden_keys(diff_payload)
    finally:
        _remove_output_leaf(manifest_hash)


def test_canonical_lf_text_and_raw_bytes_cross_newline_determinism() -> None:
    registry = _load_registry_payload()
    source = _source_record(registry, "tsc-ingest-and-reference-declarations")
    text_lf = b"line-1\nline-2\nline-3\n"
    text_crlf = b"line-1\r\nline-2\r\nline-3\r\n"
    raw_bytes = b"\xff\xfe\x00raw-bytes"
    files_model = [
        {
            "file_id": "decl-tsc-yaml",
            "path": "candidate/ingest/tsc.yaml",
            "role": "CANDIDATE_DECLARATION",
            "media_type": "application/x-yaml",
            "checksum": _checksum_canonical_text(text_lf),
            "component_ids": [],
        },
        {
            "file_id": "raw-bytes",
            "path": "candidate/raw/nonutf8.bin",
            "role": "AUXILIARY_METADATA",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(raw_bytes),
            "component_ids": [],
        },
    ]
    bindings = [
        {
            "binding_id": "bind-declaration",
            "baseline_kind": "DECLARATION_REF",
            "baseline_id": source["declaration_refs"][0]["path"],
            "candidate_file_id": "decl-tsc-yaml",
        },
        {
            "binding_id": "bind-raw-addition",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "raw-bytes",
        },
    ]
    manifest = _build_manifest(
        source=source,
        registry_hash=registry["registry_content_hash"],
        observed_at="2026-08-17T05:00:00Z",
        snapshot_id="candidate-cross-newline-001",
        files=files_model,
        content_bindings=bindings,
        component_projection=None,
    )
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(
            prefix="s2-newline-a",
            manifest=manifest,
            files={
                "candidate/ingest/tsc.yaml": text_lf,
                "candidate/raw/nonutf8.bin": raw_bytes,
            },
        ) as (_, staging_rel_a):
            run_a = _run_verify_stage(staging_rel_a)
        with _stage_case(
            prefix="s2-newline-b",
            manifest=manifest,
            files={
                "candidate/ingest/tsc.yaml": text_crlf,
                "candidate/raw/nonutf8.bin": raw_bytes,
            },
        ) as (_, staging_rel_b):
            run_b = _run_verify_stage(staging_rel_b)

        _assert_stdout_one_line_json(run_a)
        _assert_stdout_one_line_json(run_b)
        assert run_a.returncode == 0, run_a.stdout
        assert run_b.returncode == 0, run_b.stdout
        assert run_a.stdout == run_b.stdout, "LF and CRLF canonical text copies must yield identical successful stdout"
    finally:
        _remove_output_leaf(manifest_hash)


def test_explicit_null_release_date_differs_from_omitted_required_key() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest["candidate"]["release"]["release_date"] = None
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-null-date", manifest=manifest, files=files) as (_, staging_rel):
            changed_run = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(changed_run)
        assert changed_run.returncode == 0, changed_run.stdout
        changed_report = _parse_json_stdout(changed_run)
        assert changed_report["stage_outcome"] == "OBSERVED_DIFFERENCE"
        diff_payload = json.loads(_artifact_abs_path(changed_report["diff_artifact"]).read_text(encoding="utf-8"))
        release_date_facts = [
            fact for fact in diff_payload["facts"] if fact["fact_path"] == "/release/release_date"
        ]
        assert release_date_facts, "release_date diff fact must be emitted"
        fact = release_date_facts[0]
        assert fact["classification"] == "CHANGED"
        assert fact["after"] == {"present": True, "value": None}
    finally:
        _remove_output_leaf(manifest_hash)

    omitted = copy.deepcopy(manifest)
    del omitted["candidate"]["release"]["release_date"]
    omitted["manifest_content_hash"] = _canonical_manifest_hash(omitted)
    omitted_hash = omitted["manifest_content_hash"]
    _remove_output_leaf(omitted_hash)
    try:
        with _stage_case(prefix="s2-omit-date", manifest=omitted, files=files) as (_, staging_rel):
            omitted_run = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(omitted_run)
        assert omitted_run.returncode == 2, omitted_run.stdout
        omitted_report = _parse_json_stdout(omitted_run)
        assert _error_code(omitted_report) == "STAGING_MANIFEST_SCHEMA_INVALID"
    finally:
        _remove_output_leaf(omitted_hash)


@pytest.mark.parametrize(
    "case_id,manifest_builder,file_bytes,expected_code",
    [
        (
            "manifest-hash-mismatch",
            lambda m: {**m, "manifest_content_hash": "0" * 64},
            None,
            "STAGING_MANIFEST_HASH_MISMATCH",
        ),
        (
            "manifest-non-utf8",
            None,
            b"\xff\xfe\xfd",
            "STAGING_MANIFEST_ENCODING_INVALID",
        ),
        (
            "manifest-duplicate-key",
            None,
            b"schema: one\nschema: two\n",
            "STAGING_MANIFEST_YAML_INVALID",
        ),
        (
            "manifest-multi-document",
            None,
            b"---\nschema: one\n---\nschema: two\n",
            "STAGING_MANIFEST_YAML_INVALID",
        ),
        (
            "manifest-alias-anchor",
            None,
            b"schema: &s raptor.sourceops.staged_snapshot_manifest.v1\nx: *s\n",
            "STAGING_MANIFEST_YAML_INVALID",
        ),
    ],
)
def test_manifest_invalidity_cases_fail_without_artifacts(
    case_id: str,
    manifest_builder: Any,
    file_bytes: bytes | None,
    expected_code: str,
) -> None:
    base_manifest, files = _build_no_change_case(projection_complete=True)
    manifest_hash = base_manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    stage_prefix = f"s2-invalid-{case_id}"

    if file_bytes is None:
        manifest = manifest_builder(base_manifest)
        with _stage_case(prefix=stage_prefix, manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
    else:
        STAGING_PARENT.mkdir(parents=True, exist_ok=True)
        stage_name = f"{stage_prefix}-{uuid.uuid4().hex[:10]}"
        stage_root = STAGING_PARENT / stage_name
        stage_root.mkdir(parents=False, exist_ok=False)
        try:
            (stage_root / "manifest.yaml").write_bytes(file_bytes)
            staging_rel = f".raptor/sourceops/staging/{stage_name}"
            result = _run_verify_stage(staging_rel)
        finally:
            _remove_path(stage_root)

    _assert_stdout_one_line_json(result)
    assert result.returncode == 2, result.stdout
    report = _parse_json_stdout(result)
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == "INVALID"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    assert report["stage_outcome"] is None
    assert _error_code(report) == expected_code
    _remove_output_leaf(manifest_hash)


def test_component_projection_null_vs_complete_semantics() -> None:
    manifest_null, files = _build_no_change_case(projection_complete=False)
    null_hash = manifest_null["manifest_content_hash"]
    _remove_output_leaf(null_hash)
    try:
        with _stage_case(prefix="s2-proj-null", manifest=manifest_null, files=files) as (_, staging_rel):
            null_run = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(null_run)
        assert null_run.returncode == 0, null_run.stdout
        null_report = _parse_json_stdout(null_run)
        diff_payload = json.loads(_artifact_abs_path(null_report["diff_artifact"]).read_text(encoding="utf-8"))
        assert diff_payload["component_projection_status"] == "NOT_PROVIDED"
        assert not any(fact["fact_kind"] == "COMPONENT" for fact in diff_payload["facts"])
    finally:
        _remove_output_leaf(null_hash)

    manifest_complete, files_complete = _build_no_change_case(projection_complete=True)
    components = manifest_complete["component_projection"]["components"]
    if components:
        components.pop()
    manifest_complete["manifest_content_hash"] = _canonical_manifest_hash(manifest_complete)
    complete_hash = manifest_complete["manifest_content_hash"]
    _remove_output_leaf(complete_hash)
    try:
        with _stage_case(prefix="s2-proj-complete", manifest=manifest_complete, files=files_complete) as (_, staging_rel):
            complete_run = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(complete_run)
        assert complete_run.returncode == 0, complete_run.stdout
        complete_report = _parse_json_stdout(complete_run)
        assert complete_report["stage_outcome"] == "OBSERVED_DIFFERENCE"
        complete_diff = json.loads(_artifact_abs_path(complete_report["diff_artifact"]).read_text(encoding="utf-8"))
        assert complete_diff["component_projection_status"] == "COMPLETE"
        assert any(
            fact["fact_kind"] == "COMPONENT" and fact["classification"] == "REMOVED"
            for fact in complete_diff["facts"]
        )
    finally:
        _remove_output_leaf(complete_hash)


def test_diff_fact_ordering_summary_and_self_hash_rules() -> None:
    manifest, files = _build_changed_case()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-ordering", manifest=manifest, files=files) as (_, staging_rel):
            run = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(run)
        assert run.returncode == 0, run.stdout
        report = _parse_json_stdout(run)
        diff_payload = json.loads(_artifact_abs_path(report["diff_artifact"]).read_text(encoding="utf-8"))

        facts = diff_payload["facts"]
        assert isinstance(facts, list) and facts
        diff_rank = {"CONTENT": 0, "METADATA": 1, "DECLARATION": 2}
        fact_rank = {"IDENTITY": 0, "VERSION": 1, "CHECKSUM": 2, "MANIFEST": 3, "COMPONENT": 4, "METADATA": 5}
        subject_rank = {"SOURCE": 0, "FILE": 1, "COMPONENT": 2, "DECLARATION": 3}
        sort_keys = [
            (
                diff_rank[f["difference_kind"]],
                fact_rank[f["fact_kind"]],
                subject_rank[f["subject_type"]],
                f["subject_id"],
                f["fact_path"],
            )
            for f in facts
        ]
        assert sort_keys == sorted(sort_keys), "diff facts must follow canonical ordering"
        assert len(set(sort_keys)) == len(sort_keys), "diff fact key tuple must be unique"

        summary = diff_payload["summary"]
        assert summary["total_facts"] == len(facts)
        assert sum(summary["classifications"].values()) == summary["total_facts"]
        assert sum(summary["difference_kinds"].values()) == summary["total_facts"]
        assert sum(summary["fact_kinds"].values()) == summary["total_facts"]

        _assert_self_excluding_hash(diff_payload)
    finally:
        _remove_output_leaf(manifest_hash)


def _assert_failed_code_and_no_artifacts(
    result: subprocess.CompletedProcess[str],
    expected_code: str,
    *,
    expected_exit: int = 2,
    exact_authority_error: bool = False,
) -> dict[str, Any]:
    _assert_stdout_one_line_json(result)
    assert result.returncode == expected_exit, result.stdout
    report = _parse_json_stdout(result)
    assert report["run_status"] == "FAILED"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    assert _error_code(report) == expected_code
    if exact_authority_error:
        _assert_exact_error_from_authority(report, expected_code=expected_code, expected_exit=expected_exit)
    return report


def _assert_exact_invalid_failure_without_internal(
    result: subprocess.CompletedProcess[str],
    *,
    expected_code: str,
    expected_exit: int = 2,
) -> dict[str, Any]:
    report = _assert_failed_code_and_no_artifacts(
        result,
        expected_code,
        expected_exit=expected_exit,
        exact_authority_error=True,
    )
    assert report["input_validity"] == "INVALID"
    assert report["stage_outcome"] is None
    assert _error_code(report) != "INTERNAL_ERROR"
    assert "INTERNAL_ERROR" not in result.stdout
    return report


@pytest.mark.parametrize(
    "case_id,sequence_key,required_key",
    [
        ("files-file-id", "files", "file_id"),
        ("files-path", "files", "path"),
        ("content-bindings-binding-id", "content_bindings", "binding_id"),
    ],
)
def test_v2s2_bl6_row_required_keys_fail_closed_before_duplicate_and_path_scans(
    case_id: str,
    sequence_key: str,
    required_key: str,
) -> None:
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    assert len(manifest["files"]) >= 2
    assert len(manifest["content_bindings"]) >= 2
    del manifest[sequence_key][0][required_key]
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix=f"s2-bl6-row-required-{case_id}", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_exact_invalid_failure_without_internal(result, expected_code="STAGING_MANIFEST_SCHEMA_INVALID")
        assert "KeyError" not in result.stdout
        assert "KeyError" not in result.stderr
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac01_ac02_unknown_declaration_binding_target_is_content_binding_invalid() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest = copy.deepcopy(manifest)
    manifest["content_bindings"][0]["baseline_id"] = "configs/ingest/nonexistent-declaration.yaml"
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-bind-unknown-decl", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(result, "CONTENT_BINDING_INVALID")


def test_v2s2_ac01_ac02_unknown_component_binding_target_is_content_binding_invalid() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    component_raw = b"\x00component-checksum-bytes\xff"
    manifest["files"].append(
        {
            "file_id": "component-bytes",
            "path": "candidate/components/component.bin",
            "role": "SNAPSHOT_CONTENT",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(component_raw),
            "component_ids": ["unknown-component-id"],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "bind-unknown-component",
            "baseline_kind": "COMPONENT_CHECKSUM",
            "baseline_id": "unknown-component-id",
            "candidate_file_id": "component-bytes",
        }
    )
    manifest["files"] = sorted(manifest["files"], key=lambda row: row["file_id"])
    manifest["content_bindings"] = sorted(manifest["content_bindings"], key=lambda row: row["binding_id"])
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files = copy.deepcopy(files)
    files["candidate/components/component.bin"] = component_raw
    with _stage_case(prefix="s2-bind-unknown-comp", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(result, "CONTENT_BINDING_INVALID")


def test_v2s2_ac01_ac04_every_staged_file_must_be_bound_exactly_once() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    extra_raw = b"unbound-file-bytes"
    manifest["files"].append(
        {
            "file_id": "unbound-file",
            "path": "candidate/extra/unbound.bin",
            "role": "AUXILIARY_METADATA",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(extra_raw),
            "component_ids": [],
        }
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files = copy.deepcopy(files)
    files["candidate/extra/unbound.bin"] = extra_raw
    with _stage_case(prefix="s2-unbound-file", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(result, "CONTENT_BINDING_INVALID")


def test_v2s2_ac05_declaration_binding_requires_declaration_role_and_canonical_text() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["files"][0]["role"] = "SNAPSHOT_CONTENT"
    manifest["files"][0]["checksum"] = _checksum_raw(files["candidate/ingest/tsc.yaml"])
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-bind-role-mode", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(result, "CONTENT_BINDING_INVALID")


def test_v2s2_ac05_canonical_text_media_type_must_be_from_allowed_set() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["files"][0]["media_type"] = "application/octet-stream"
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-media-compat", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(result, "CONTENT_BINDING_INVALID")


def test_v2s2_ac08_single_source_complete_component_projection_is_component_mapping_invalid() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest = copy.deepcopy(manifest)
    baseline_components = manifest["component_projection"]["components"]
    assert baseline_components, "real-source fixture must expose at least one baseline component"
    manifest["candidate"]["identity"]["record_kind"] = "SINGLE_SOURCE"
    manifest["component_projection"] = {
        "mode": "COMPLETE",
        "components": [copy.deepcopy(baseline_components[0])],
    }
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-projection-single-source", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        result,
        "COMPONENT_MAPPING_INVALID",
        exact_authority_error=True,
    )


def test_v2s2_ac08_metadata_catalog_template_non_empty_complete_projection_is_component_mapping_invalid() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest = copy.deepcopy(manifest)
    baseline_components = manifest["component_projection"]["components"]
    assert baseline_components, "real-source fixture must expose at least one baseline component"
    baseline_source = _source_record(_load_registry_payload(), manifest["source_binding"]["source_id"])
    baseline_component_ids = {
        row["component_id"] for row in (baseline_source.get("components") or []) if isinstance(row, dict)
    }
    selected_component = copy.deepcopy(baseline_components[0])
    assert selected_component["component_id"] in baseline_component_ids
    manifest["candidate"]["identity"]["record_kind"] = "METADATA_CATALOG_TEMPLATE"
    manifest["component_projection"] = {"mode": "COMPLETE", "components": [selected_component]}
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        result: subprocess.CompletedProcess[str]
        with _stage_case(prefix="s2-projection-metadata-template", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_exact_invalid_failure_without_internal(
            result,
            expected_code="COMPONENT_MAPPING_INVALID",
        )
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "record_kind",
    ("SINGLE_SOURCE", "METADATA_CATALOG_TEMPLATE"),
    ids=("single-source", "metadata-template"),
)
def test_v2s2_ac08_null_source_components_normalize_to_empty_for_complete_projection(
    record_kind: str,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, _ = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["candidate"]["identity"]["record_kind"] = record_kind
    manifest["component_projection"] = {"mode": "COMPLETE", "components": []}
    source_record = _source_record(_load_registry_payload(), manifest["source_binding"]["source_id"])
    source_record["components"] = None

    staged_mod._validate_content_bindings_and_component_projection(manifest, source_record)


@pytest.mark.parametrize(
    "record_kind",
    ("SINGLE_SOURCE", "METADATA_CATALOG_TEMPLATE"),
    ids=("single-source", "metadata-template"),
)
def test_v2s2_ac08_null_source_components_still_enforce_record_kind_projection_rule(
    record_kind: str,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, _ = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["candidate"]["identity"]["record_kind"] = record_kind
    manifest["component_projection"] = {
        "mode": "COMPLETE",
        "components": [
            {
                "component_id": "zz-null-components-projection-probe",
                "display_name": "Null components projection probe",
                "source_role": "required_primary_sources",
                "version_or_snapshot": "probe-version",
                "licence_status": "declared",
                "declaration_locator": "configs/ingest/tsc.yaml#/null-components-probe",
            }
        ],
    }
    source_record = _source_record(_load_registry_payload(), manifest["source_binding"]["source_id"])
    source_record["components"] = None

    with pytest.raises(staged_mod.ComponentMappingError) as excinfo:
        staged_mod._validate_content_bindings_and_component_projection(manifest, source_record)
    error = excinfo.value
    assert error.code == "COMPONENT_MAPPING_INVALID"
    assert getattr(error, "phase", None) == "CONTENT"
    assert getattr(error, "subject", None) == "component_projection"
    assert not isinstance(error, TypeError)


def test_v2s2_ac08_component_projection_facts_treat_null_source_components_as_empty() -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    source_record = {"components": None}
    candidate_projection = {
        "mode": "COMPLETE",
        "components": [
            {
                "component_id": "zz-added-null-components-fact-probe",
                "display_name": "Added null-components fact probe",
                "source_role": "required_primary_sources",
                "version_or_snapshot": "probe-version",
                "licence_status": "declared",
                "declaration_locator": "configs/ingest/tsc.yaml#/null-components-fact-probe",
            }
        ],
    }

    facts = staged_mod._component_projection_facts(source_record, candidate_projection)
    assert isinstance(facts, list)
    assert len(facts) == 1
    fact = facts[0]
    assert fact["subject_id"] == "zz-added-null-components-fact-probe"
    assert fact["classification"] == "ADDED"
    assert fact["difference_kind"] == "METADATA"


def test_v2s2_ac08_null_source_components_component_binding_is_typed_content_binding_invalid() -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, _ = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    component_file_id = "null-components-component-binding-file"
    missing_component_id = "missing-component-under-null-components"
    component_raw = b"null-components-component-binding-probe\n"
    manifest["files"].append(
        {
            "file_id": component_file_id,
            "path": "candidate/components/null-components-component-binding-probe.bin",
            "role": "SNAPSHOT_CONTENT",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(component_raw),
            "component_ids": [missing_component_id],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "bind-null-components-component-binding-probe",
            "baseline_kind": "COMPONENT_CHECKSUM",
            "baseline_id": missing_component_id,
            "candidate_file_id": component_file_id,
        }
    )
    manifest["files"] = sorted(manifest["files"], key=lambda row: row["file_id"])
    manifest["content_bindings"] = sorted(manifest["content_bindings"], key=lambda row: row["binding_id"])
    source_record = _source_record(_load_registry_payload(), manifest["source_binding"]["source_id"])
    source_record["components"] = None

    with pytest.raises(staged_mod.ContentBindingError) as excinfo:
        staged_mod._validate_content_bindings_and_component_projection(manifest, source_record)
    error = excinfo.value
    assert error.code == "CONTENT_BINDING_INVALID"
    assert getattr(error, "phase", None) == "CONTENT"
    assert getattr(error, "subject", None) == missing_component_id
    assert not isinstance(error, TypeError)


def test_v2s2_ac01_retrieved_at_must_not_be_after_observed_at() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["observed_at"] = "2000-01-01T00:00:00Z"
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-ts-order", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(result, "STAGING_MANIFEST_SCHEMA_INVALID")


def test_v2s2_ac01_bool_is_not_valid_integer_for_raw_byte_size() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    raw = b"x"
    manifest["files"][0]["checksum"] = {
        "mode": "RAW_BYTES",
        "raw_byte_size": True,
        "raw_sha256": _sha256_hex(raw),
        "canonical_lf_utf8_bytes": None,
        "canonical_lf_sha256": None,
    }
    manifest["files"][0]["media_type"] = "application/octet-stream"
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files = {"candidate/ingest/tsc.yaml": raw}
    with _stage_case(prefix="s2-bool-not-int", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(result, "STAGING_MANIFEST_SCHEMA_INVALID")


@pytest.mark.parametrize(
    "component_count,expected_code",
    [
        (256, None),
        (257, "STAGING_MANIFEST_LIMIT_EXCEEDED"),
    ],
    ids=["count-256-control", "count-257-limit"],
)
def test_v2s2_ac04_component_projection_count_boundary_uses_manifest_limit_catalog_row(
    component_count: int,
    expected_code: str | None,
) -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["candidate"]["identity"]["record_kind"] = "COMPOSITE_MANIFEST"
    components: list[dict[str, Any]] = []
    for idx in range(component_count):
        component_id = f"component-{idx:03d}"
        components.append(
            {
                "component_id": component_id,
                "display_name": f"Component {idx}",
                "source_role": "checksum-source",
                "version_or_snapshot": "1111111111111111111111111111111111111111111111111111111111111111",
                "licence_status": "declared",
                "declaration_locator": f"configs/ingest/tsc.yaml#/components/{idx}",
            }
        )
    manifest["component_projection"] = {"mode": "COMPLETE", "components": components}
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix=f"s2-component-limit-{component_count}", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        if expected_code is None:
            _assert_stdout_one_line_json(result)
            assert result.returncode == 0, result.stdout
            report = _parse_json_stdout(result)
            assert report["run_status"] == "COMPLETED"
            assert report["input_validity"] == "VALID"
            assert report["stage_outcome"] in {"OBSERVED_NO_DIFFERENCE", "OBSERVED_DIFFERENCE"}
            assert isinstance(report["verification_artifact"], dict)
            assert isinstance(report["diff_artifact"], dict)
            assert report["error"] is None
        else:
            report = _assert_exact_invalid_failure_without_internal(
                result,
                expected_code=expected_code,
                expected_exit=2,
            )
            assert report["source_id"] is None
            assert report["registry_content_hash"] is None
            assert report["manifest_content_hash"] is None
            assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_fm11_plain_scalar_with_ampersand_asterisk_and_bang_is_not_rejected_lexically() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["candidate"]["identity"]["authoritative_locator"] = "https://example.test/source?x=a&y=*ok!value"
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-yaml-plain-chars", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(result)
        assert result.returncode == 0, result.stdout
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "case_id,manifest_bytes",
    [
        ("anchor-alias", b"schema: &schema raptor.sourceops.staged_snapshot_manifest.v1\nschema_copy: *schema\n"),
        ("merge-key", b"base: &base {schema: raptor.sourceops.staged_snapshot_manifest.v1}\n<<: *base\n"),
        ("custom-tag", b"schema: !custom raptor.sourceops.staged_snapshot_manifest.v1\n"),
    ],
)
def test_v2s2_fm11_yaml_anchor_alias_merge_and_custom_tag_are_rejected(
    case_id: str,
    manifest_bytes: bytes,
) -> None:
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"s2-yaml-{case_id}-{uuid.uuid4().hex[:10]}"
    stage_root = STAGING_PARENT / stage_name
    stage_root.mkdir(parents=False, exist_ok=False)
    try:
        (stage_root / "manifest.yaml").write_bytes(manifest_bytes)
        result = _run_verify_stage(f".raptor/sourceops/staging/{stage_name}")
    finally:
        _remove_path(stage_root)
    _assert_failed_code_and_no_artifacts(result, "STAGING_MANIFEST_YAML_INVALID")


def test_v2s2_fm03_duplicate_and_case_collision_codes_are_exact() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)

    duplicate_file_id = copy.deepcopy(manifest)
    duplicate_file_id["files"].append(
        {
            "file_id": "decl-tsc-yaml",
            "path": "candidate/dup/second.bin",
            "role": "AUXILIARY_METADATA",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(b"dup"),
            "component_ids": [],
        }
    )
    duplicate_file_id["content_bindings"].append(
        {
            "binding_id": "bind-dup-file-id",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "decl-tsc-yaml",
        }
    )
    duplicate_file_id["files"] = sorted(duplicate_file_id["files"], key=lambda row: row["file_id"])
    duplicate_file_id["content_bindings"] = sorted(
        duplicate_file_id["content_bindings"],
        key=lambda row: row["binding_id"],
    )
    duplicate_file_id["manifest_content_hash"] = _canonical_manifest_hash(duplicate_file_id)
    with _stage_case(prefix="s2-dup-file-id", manifest=duplicate_file_id, files=files) as (_, staging_rel):
        duplicate_file_id_result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(duplicate_file_id_result, "STAGING_DUPLICATE_ID")

    duplicate_path = copy.deepcopy(manifest)
    duplicate_path["files"].append(
        {
            "file_id": "path-collision",
            "path": "candidate/INGEST/tsc.yaml",
            "role": "AUXILIARY_METADATA",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(b"path"),
            "component_ids": [],
        }
    )
    duplicate_path["content_bindings"].append(
        {
            "binding_id": "bind-path-collision",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "path-collision",
        }
    )
    duplicate_path["files"] = sorted(duplicate_path["files"], key=lambda row: row["file_id"])
    duplicate_path["content_bindings"] = sorted(
        duplicate_path["content_bindings"],
        key=lambda row: row["binding_id"],
    )
    duplicate_path["manifest_content_hash"] = _canonical_manifest_hash(duplicate_path)
    with _stage_case(prefix="s2-dup-path", manifest=duplicate_path, files=files) as (_, staging_rel):
        duplicate_path_result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(duplicate_path_result, "STAGING_DUPLICATE_PATH")

    duplicate_binding_id = copy.deepcopy(manifest)
    duplicate_binding_id["files"].append(
        {
            "file_id": "binding-id-case-probe",
            "path": "candidate/binding/probe.bin",
            "role": "AUXILIARY_METADATA",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(b"binding"),
            "component_ids": [],
        }
    )
    duplicate_binding_id["content_bindings"].append(
        {
            "binding_id": "BIND-DECLARATION",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "binding-id-case-probe",
        }
    )
    duplicate_binding_id["files"] = sorted(duplicate_binding_id["files"], key=lambda row: row["file_id"])
    duplicate_binding_id["content_bindings"] = sorted(
        duplicate_binding_id["content_bindings"],
        key=lambda row: row["binding_id"],
    )
    duplicate_binding_id["manifest_content_hash"] = _canonical_manifest_hash(duplicate_binding_id)
    files_for_binding_case = copy.deepcopy(files)
    files_for_binding_case["candidate/binding/probe.bin"] = b"binding"
    with _stage_case(prefix="s2-dup-binding-id", manifest=duplicate_binding_id, files=files_for_binding_case) as (_, staging_rel):
        duplicate_binding_result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(duplicate_binding_result, "STAGING_DUPLICATE_ID")

    duplicate_component_id = copy.deepcopy(manifest)
    duplicate_component_id["candidate"]["identity"]["record_kind"] = "COMPOSITE_MANIFEST"
    duplicate_component_id["component_projection"] = {
        "mode": "COMPLETE",
        "components": [
            {
                "component_id": "component-alpha",
                "display_name": "Component Alpha",
                "source_role": "checksum-source",
                "version_or_snapshot": "1111111111111111111111111111111111111111111111111111111111111111",
                "licence_status": "declared",
                "declaration_locator": "configs/ingest/tsc.yaml#/alpha",
            },
            {
                "component_id": "COMPONENT-ALPHA",
                "display_name": "Component Alpha Copy",
                "source_role": "checksum-source",
                "version_or_snapshot": "1111111111111111111111111111111111111111111111111111111111111111",
                "licence_status": "declared",
                "declaration_locator": "configs/ingest/tsc.yaml#/alpha-copy",
            },
        ],
    }
    duplicate_component_id["manifest_content_hash"] = _canonical_manifest_hash(duplicate_component_id)
    with _stage_case(prefix="s2-dup-component-id", manifest=duplicate_component_id, files=files) as (_, staging_rel):
        duplicate_component_result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(duplicate_component_result, "STAGING_DUPLICATE_ID")


def test_v2s2_ac08_none_binding_on_candidate_declaration_uses_declaration_difference_kind() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    added_raw = b"version: 1\nname: declaration-added\n"
    manifest["files"].append(
        {
            "file_id": "added-candidate-declaration",
            "path": "candidate/declarations/added.yaml",
            "role": "CANDIDATE_DECLARATION",
            "media_type": "application/x-yaml",
            "checksum": _checksum_canonical_text(added_raw),
            "component_ids": [],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "bind-added-candidate-declaration",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "added-candidate-declaration",
        }
    )
    manifest["files"] = sorted(manifest["files"], key=lambda row: row["file_id"])
    manifest["content_bindings"] = sorted(manifest["content_bindings"], key=lambda row: row["binding_id"])
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files = copy.deepcopy(files)
    files["candidate/declarations/added.yaml"] = added_raw
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-decl-diff-kind", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(result)
        assert result.returncode == 0, result.stdout
        report = _parse_json_stdout(result)
        diff_payload = json.loads(_artifact_abs_path(report["diff_artifact"]).read_text(encoding="utf-8"))
        fact = next(
            row for row in diff_payload["facts"] if row["fact_path"] == "/content-bindings/bind-added-candidate-declaration"
        )
        assert fact["classification"] == "ADDED"
        assert fact["difference_kind"] == "DECLARATION"
        computed_kind_counts = {"CONTENT": 0, "METADATA": 0, "DECLARATION": 0}
        for row in diff_payload["facts"]:
            computed_kind_counts[row["difference_kind"]] += 1
        assert diff_payload["summary"]["difference_kinds"] == computed_kind_counts
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_b13_input_tree_content_hash_uses_files_sequence_basis_only() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-input-tree-hash", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(result)
        assert result.returncode == 0, result.stdout
        report = _parse_json_stdout(result)
        verification_payload = json.loads(_artifact_abs_path(report["verification_artifact"]).read_text(encoding="utf-8"))
        diff_payload = json.loads(_artifact_abs_path(report["diff_artifact"]).read_text(encoding="utf-8"))
        files_sequence = verification_payload["input_tree"]["files"]
        expected_hash = _sha256_hex(_canonical_json_bytes(files_sequence))
        assert verification_payload["input_tree"]["input_tree_content_hash"] == expected_hash
        assert diff_payload["input_tree_content_hash"] == expected_hash
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl3_complete_projection_accepts_added_component_and_preserves_classifications() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest = copy.deepcopy(manifest)
    baseline_components = [copy.deepcopy(row) for row in manifest["component_projection"]["components"]]
    assert len(baseline_components) >= 2, "real-source fixture must expose at least two baseline components"
    removed_component = baseline_components[1]
    changed_component_id = baseline_components[0]["component_id"]

    candidate_components = [row for row in baseline_components if row["component_id"] != removed_component["component_id"]]
    for row in candidate_components:
        if row["component_id"] == changed_component_id:
            row["display_name"] = f"{row['display_name']} (candidate)"
    added_component = {
        "component_id": "zz-added-component-probe",
        "display_name": "Added component probe",
        "source_role": "candidate_checksum_source",
        "version_or_snapshot": "probe-version-001",
        "licence_status": "declared",
        "declaration_locator": "configs/ingest/tsc.yaml#/added-component-probe",
    }
    candidate_components.append(added_component)
    candidate_components.sort(key=lambda row: row["component_id"])
    manifest["component_projection"]["components"] = candidate_components
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl3-added-component", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(result)
        assert result.returncode == 0, result.stdout
        report = _parse_json_stdout(result)
        diff_payload = json.loads(_artifact_abs_path(report["diff_artifact"]).read_text(encoding="utf-8"))

        added_fact = next(
            row
            for row in diff_payload["facts"]
            if row["subject_type"] == "COMPONENT" and row["subject_id"] == added_component["component_id"] and row["classification"] == "ADDED"
        )
        assert added_fact["fact_kind"] == "COMPONENT"
        assert added_fact["provenance"] == {"baseline_origin": "ABSENT", "candidate_origin": "MANIFEST_COMPONENT"}
        classifications = diff_payload["summary"]["classifications"]
        assert classifications["ADDED"] >= 1
        assert classifications["REMOVED"] >= 1
        assert classifications["CHANGED"] >= 1
        assert classifications["UNCHANGED"] >= 1
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl5_declaration_ref_binding_rejects_raw_bytes_mode() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    declaration_raw = files["candidate/ingest/tsc.yaml"]
    manifest["files"][0]["checksum"] = _checksum_raw(declaration_raw)
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-bl5-decl-raw", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        result,
        "CONTENT_BINDING_INVALID",
        exact_authority_error=True,
    )


def test_v2s2_bl5_component_checksum_variant_constraints_are_enforced() -> None:
    registry = _load_registry_payload()
    source = _source_record(registry, "tsc-ingest-and-reference-declarations")
    components = [row for row in (source.get("components") or []) if isinstance(row, dict)]
    valid_component = next(
        row
        for row in components
        if re.fullmatch(r"[0-9a-f]{64}", str(row.get("version_or_snapshot")))
        and any(token.casefold() == "checksum" for token in re.split(r"[-_\s]+", str(row.get("source_role", ""))))
    )
    invalid_hash_component = next(
        row
        for row in components
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("version_or_snapshot")))
        and any(token.casefold() == "checksum" for token in re.split(r"[-_\s]+", str(row.get("source_role", ""))))
    )
    component_raw = b"component-checksum-binding-probe\n"
    component_rel = "candidate/components/checksum-probe.bin"
    component_file = {
        "file_id": "checksum-probe-file",
        "path": component_rel,
        "role": "SNAPSHOT_CONTENT",
        "media_type": "application/octet-stream",
        "checksum": _checksum_raw(component_raw),
        "component_ids": [valid_component["component_id"]],
    }
    component_binding = {
        "binding_id": "bind-component-checksum-probe",
        "baseline_kind": "COMPONENT_CHECKSUM",
        "baseline_id": valid_component["component_id"],
        "candidate_file_id": "checksum-probe-file",
    }

    control_manifest, control_files = _build_no_change_case(projection_complete=False)
    control_manifest = copy.deepcopy(control_manifest)
    control_manifest["files"].append(copy.deepcopy(component_file))
    control_manifest["content_bindings"].append(copy.deepcopy(component_binding))
    control_manifest["files"] = sorted(control_manifest["files"], key=lambda row: row["file_id"])
    control_manifest["content_bindings"] = sorted(
        control_manifest["content_bindings"],
        key=lambda row: row["binding_id"],
    )
    control_manifest["manifest_content_hash"] = _canonical_manifest_hash(control_manifest)
    control_files = copy.deepcopy(control_files)
    control_files[component_rel] = component_raw
    control_hash = control_manifest["manifest_content_hash"]
    _remove_output_leaf(control_hash)
    try:
        with _stage_case(prefix="s2-bl5-component-control", manifest=control_manifest, files=control_files) as (_, staging_rel):
            control_result = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(control_result)
        assert control_result.returncode == 0, control_result.stdout
    finally:
        _remove_output_leaf(control_hash)

    canonical_manifest = copy.deepcopy(control_manifest)
    canonical_probe_file = next(row for row in canonical_manifest["files"] if row["file_id"] == component_file["file_id"])
    canonical_probe_file["checksum"] = _checksum_canonical_text(component_raw)
    canonical_probe_file["media_type"] = "application/json"
    canonical_manifest["manifest_content_hash"] = _canonical_manifest_hash(canonical_manifest)
    with _stage_case(prefix="s2-bl5-component-canonical", manifest=canonical_manifest, files=control_files) as (_, staging_rel):
        canonical_result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        canonical_result,
        "CONTENT_BINDING_INVALID",
        exact_authority_error=True,
    )

    missing_component_id_manifest = copy.deepcopy(control_manifest)
    missing_probe_file = next(
        row for row in missing_component_id_manifest["files"] if row["file_id"] == component_file["file_id"]
    )
    missing_probe_file["component_ids"] = []
    missing_component_id_manifest["manifest_content_hash"] = _canonical_manifest_hash(missing_component_id_manifest)
    with _stage_case(prefix="s2-bl5-component-ids", manifest=missing_component_id_manifest, files=control_files) as (_, staging_rel):
        missing_component_id_result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        missing_component_id_result,
        "CONTENT_BINDING_INVALID",
        exact_authority_error=True,
    )

    invalid_hash_manifest = copy.deepcopy(control_manifest)
    invalid_probe_binding = next(
        row for row in invalid_hash_manifest["content_bindings"] if row["binding_id"] == component_binding["binding_id"]
    )
    invalid_probe_binding["baseline_id"] = invalid_hash_component["component_id"]
    invalid_probe_file = next(row for row in invalid_hash_manifest["files"] if row["file_id"] == component_file["file_id"])
    invalid_probe_file["component_ids"] = [invalid_hash_component["component_id"]]
    invalid_hash_manifest["manifest_content_hash"] = _canonical_manifest_hash(invalid_hash_manifest)
    with _stage_case(prefix="s2-bl5-component-hash", manifest=invalid_hash_manifest, files=control_files) as (_, staging_rel):
        invalid_hash_result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        invalid_hash_result,
        "CONTENT_BINDING_INVALID",
        exact_authority_error=True,
    )


def test_v2s2_bl5_component_checksum_null_candidate_requires_sha256_baseline() -> None:
    registry = _load_registry_payload()
    source = _source_record(registry, "tsc-ingest-and-reference-declarations")
    components = [row for row in (source.get("components") or []) if isinstance(row, dict)]
    valid_component = next(
        row
        for row in components
        if re.fullmatch(r"[0-9a-f]{64}", str(row.get("version_or_snapshot")))
        and any(token.casefold() == "checksum" for token in re.split(r"[-_\s]+", str(row.get("source_role", ""))))
    )
    invalid_component = next(
        row
        for row in components
        if str(row.get("version_or_snapshot")) == "confirm-pending"
        and any(token.casefold() == "checksum" for token in re.split(r"[-_\s]+", str(row.get("source_role", ""))))
    )

    control_manifest, control_files = _build_no_change_case(projection_complete=False)
    control_manifest = copy.deepcopy(control_manifest)
    control_binding_id = "zz-bind-null-candidate-checksum-valid"
    control_manifest["content_bindings"].append(
        {
            "binding_id": control_binding_id,
            "baseline_kind": "COMPONENT_CHECKSUM",
            "baseline_id": valid_component["component_id"],
            "candidate_file_id": None,
        }
    )
    control_manifest["manifest_content_hash"] = _canonical_manifest_hash(control_manifest)
    control_hash = control_manifest["manifest_content_hash"]
    _remove_output_leaf(control_hash)
    try:
        with _stage_case(prefix="s2-bl5-null-candidate-valid", manifest=control_manifest, files=control_files) as (_, staging_rel):
            control_result = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(control_result)
        assert control_result.returncode == 0, control_result.stdout
        control_report = _parse_json_stdout(control_result)
        assert control_report["stage_outcome"] == "OBSERVED_DIFFERENCE"
        diff_payload = json.loads(_artifact_abs_path(control_report["diff_artifact"]).read_text(encoding="utf-8"))
        removal_fact = next(row for row in diff_payload["facts"] if row["fact_path"] == f"/content-bindings/{control_binding_id}")
        assert removal_fact["classification"] == "REMOVED"
        assert removal_fact["before"]["present"] is True
        assert removal_fact["after"] == {"present": False, "value": None}
        assert removal_fact["before"]["value"]["content_sha256"] == valid_component["version_or_snapshot"]
    finally:
        _remove_output_leaf(control_hash)

    invalid_manifest = copy.deepcopy(control_manifest)
    invalid_manifest["content_bindings"][-1]["baseline_id"] = invalid_component["component_id"]
    invalid_manifest["manifest_content_hash"] = _canonical_manifest_hash(invalid_manifest)
    invalid_hash = invalid_manifest["manifest_content_hash"]
    _remove_output_leaf(invalid_hash)
    try:
        with _stage_case(prefix="s2-bl5-null-candidate-invalid", manifest=invalid_manifest, files=control_files) as (_, staging_rel):
            invalid_result = _run_verify_stage(staging_rel)
        _assert_exact_invalid_failure_without_internal(
            invalid_result,
            expected_code="CONTENT_BINDING_INVALID",
        )
        assert '"content_sha256":"confirm-pending"' not in invalid_result.stdout
        assert '"content_sha256": "confirm-pending"' not in invalid_result.stdout
        assert not (OUTPUT_PARENT / invalid_hash).exists()
    finally:
        _remove_output_leaf(invalid_hash)


def test_v2s2_bl5_component_checksum_source_role_requires_checksum_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    registry = _load_registry_payload()
    source = _source_record(registry, "tsc-ingest-and-reference-declarations")
    components = [row for row in (source.get("components") or []) if isinstance(row, dict)]
    valid_component = next(
        row
        for row in components
        if re.fullmatch(r"[0-9a-f]{64}", str(row.get("version_or_snapshot")))
        and any(token.casefold() == "checksum" for token in re.split(r"[-_\s]+", str(row.get("source_role", ""))))
    )
    component_raw = b"component-source-role-probe\n"
    component_rel = "candidate/components/source-role-probe.bin"
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["files"].append(
        {
            "file_id": "source-role-probe-file",
            "path": component_rel,
            "role": "SNAPSHOT_CONTENT",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(component_raw),
            "component_ids": [valid_component["component_id"]],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "bind-source-role-probe",
            "baseline_kind": "COMPONENT_CHECKSUM",
            "baseline_id": valid_component["component_id"],
            "candidate_file_id": "source-role-probe-file",
        }
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files = copy.deepcopy(files)
    files[component_rel] = component_raw

    real_validate_baseline_state = staged_mod._validate_baseline_state

    def _mutated_validate(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        registry_dict, source_record = real_validate_baseline_state(*args, **kwargs)
        mutated = copy.deepcopy(source_record)
        for row in mutated.get("components") or []:
            if row.get("component_id") == valid_component["component_id"]:
                row["source_role"] = "reference_pin"
                break
        return registry_dict, mutated

    monkeypatch.setattr(staged_mod, "_validate_baseline_state", _mutated_validate, raising=True)
    with _stage_case(prefix="s2-bl5-source-role", manifest=manifest, files=files) as (_, staging_rel):
        code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    assert code == 2
    assert payload["run_status"] == "FAILED"
    assert payload["verification_artifact"] is None
    assert payload["diff_artifact"] is None
    assert _error_code(payload) == "CONTENT_BINDING_INVALID"
    _assert_exact_error_from_authority(payload, expected_code="CONTENT_BINDING_INVALID", expected_exit=2)


def test_v2s2_bl6_files_sequence_must_be_strictly_ascending_by_file_id() -> None:
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    manifest["files"] = sorted(
        manifest["files"],
        key=lambda row: row["file_id"],
        reverse=True,
    )
    manifest["content_bindings"] = sorted(
        manifest["content_bindings"],
        key=lambda row: row["binding_id"],
    )
    assert all(row["role"] != "AUXILIARY_METADATA" for row in manifest["files"])
    assert [row["file_id"] for row in manifest["files"]] == sorted(
        (row["file_id"] for row in manifest["files"]),
        reverse=True,
    )
    assert [row["binding_id"] for row in manifest["content_bindings"]] == sorted(
        row["binding_id"] for row in manifest["content_bindings"]
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl6-files-order", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_exact_invalid_failure_without_internal(
            result,
            expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
        )
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl6_files_and_content_bindings_both_descending_without_auxiliary_roles_are_schema_invalid() -> None:
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    manifest["files"] = sorted(manifest["files"], key=lambda row: row["file_id"], reverse=True)
    manifest["content_bindings"] = sorted(
        manifest["content_bindings"],
        key=lambda row: row["binding_id"],
        reverse=True,
    )
    assert all(row["role"] != "AUXILIARY_METADATA" for row in manifest["files"])
    assert [row["file_id"] for row in manifest["files"]] == sorted(
        (row["file_id"] for row in manifest["files"]),
        reverse=True,
    )
    assert [row["binding_id"] for row in manifest["content_bindings"]] == sorted(
        (row["binding_id"] for row in manifest["content_bindings"]),
        reverse=True,
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl6-both-desc", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        report = _assert_exact_invalid_failure_without_internal(
            result,
            expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
        )
        assert report["error"]["type"] == "StagingManifestSchemaError"
        assert report["error"]["phase"] == "MANIFEST_SCHEMA"
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl6_content_bindings_sequence_must_be_strictly_ascending_by_binding_id() -> None:
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    manifest["files"] = sorted(
        manifest["files"],
        key=lambda row: row["file_id"],
    )
    manifest["content_bindings"] = sorted(
        manifest["content_bindings"],
        key=lambda row: row["binding_id"],
        reverse=True,
    )
    assert all(row["role"] != "AUXILIARY_METADATA" for row in manifest["files"])
    assert [row["file_id"] for row in manifest["files"]] == sorted(
        row["file_id"] for row in manifest["files"]
    )
    assert [row["binding_id"] for row in manifest["content_bindings"]] == sorted(
        (row["binding_id"] for row in manifest["content_bindings"]),
        reverse=True,
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl6-bind-order", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_exact_invalid_failure_without_internal(
            result,
            expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
        )
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "case_id,sequence_key,identifier_key,wrong_value",
    MIXED_IDENTIFIER_WRONG_TYPE_CASES,
)
def test_v2s2_bl6_mixed_scalar_and_string_identifiers_fail_schema_without_internal_error(
    case_id: str,
    sequence_key: str,
    identifier_key: str,
    wrong_value: Any,
) -> None:
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    manifest[sequence_key][0][identifier_key] = wrong_value
    mixed_identifiers = [row[identifier_key] for row in manifest[sequence_key]]
    assert any(isinstance(value, str) for value in mixed_identifiers)
    assert any(not isinstance(value, str) for value in mixed_identifiers)
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-mixed-id", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        report = _assert_exact_invalid_failure_without_internal(
            result,
            expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
        )
        assert report["error"]["type"] == "StagingManifestSchemaError"
        assert report["error"]["phase"] == "MANIFEST_SCHEMA"
        assert report["error"]["message"] == "staged manifest violates the closed typed schema"
        for raw_exception_text in ("TypeError", "not supported between instances"):
            assert raw_exception_text not in result.stdout
            assert raw_exception_text not in result.stderr
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl6_manifest_schema_phase_precedes_baseline_unknown_source_for_descending_files() -> None:
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    manifest["source_binding"]["source_id"] = "unknown-source-order-precedence-probe"
    manifest["files"] = sorted(
        manifest["files"],
        key=lambda row: row["file_id"],
        reverse=True,
    )
    manifest["content_bindings"] = sorted(
        manifest["content_bindings"],
        key=lambda row: row["binding_id"],
    )
    assert [row["file_id"] for row in manifest["files"]] == sorted(
        (row["file_id"] for row in manifest["files"]),
        reverse=True,
    )
    assert [row["binding_id"] for row in manifest["content_bindings"]] == sorted(
        row["binding_id"] for row in manifest["content_bindings"]
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl6-phase-precedence", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        report = _assert_exact_invalid_failure_without_internal(
            result,
            expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
        )
        assert _error_code(report) != "UNKNOWN_SOURCE"
        assert result.returncode != 4
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl6_file_paths_cannot_be_ancestor_of_each_other() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["files"][0]["path"] = "candidate/ancestor"
    manifest["content_bindings"][0]["candidate_file_id"] = "decl-tsc-yaml"
    manifest["files"].append(
        {
            "file_id": "descendant-file",
            "path": "candidate/ancestor/child.bin",
            "role": "AUXILIARY_METADATA",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(b"child"),
            "component_ids": [],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "zz-bind-descendant-file",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "descendant-file",
        }
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"s2-bl6-ancestor-{uuid.uuid4().hex[:10]}"
    stage_root = STAGING_PARENT / stage_name
    stage_root.mkdir(parents=False, exist_ok=False)
    try:
        dumped = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
        (stage_root / "manifest.yaml").write_text(dumped, encoding="utf-8", newline="")
        result = _run_verify_stage(f".raptor/sourceops/staging/{stage_name}")
    finally:
        _remove_path(stage_root)
    _assert_failed_code_and_no_artifacts(
        result,
        "STAGING_MANIFEST_SCHEMA_INVALID",
        exact_authority_error=True,
    )


def test_v2s2_bl6_component_ids_must_match_candidate_projection_identities() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest = copy.deepcopy(manifest)
    baseline_component_id = manifest["component_projection"]["components"][0]["component_id"]
    manifest["component_projection"] = {
        "mode": "COMPLETE",
        "components": [
            {
                "component_id": "candidate-component-only",
                "display_name": "Candidate component only",
                "source_role": "candidate_checksum_source",
                "version_or_snapshot": "candidate-version-only",
                "licence_status": "declared",
                "declaration_locator": "configs/ingest/tsc.yaml#/candidate-component-only",
            }
        ],
    }
    manifest["files"][0]["component_ids"] = [baseline_component_id]
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-bl6-component-identity", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        result,
        "COMPONENT_MAPPING_INVALID",
        exact_authority_error=True,
    )


def test_v2s2_bl6_one_component_cannot_map_to_multiple_files() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest = copy.deepcopy(manifest)
    shared_component_id = "shared-component-probe"
    manifest["component_projection"] = {
        "mode": "COMPLETE",
        "components": [
            {
                "component_id": shared_component_id,
                "display_name": "Shared component probe",
                "source_role": "candidate_checksum_source",
                "version_or_snapshot": "shared-probe-version",
                "licence_status": "declared",
                "declaration_locator": "configs/ingest/tsc.yaml#/shared-component-probe",
            }
        ],
    }
    manifest["files"][0]["component_ids"] = [shared_component_id]
    manifest["files"].append(
        {
            "file_id": "shared-component-second-file",
            "path": "candidate/components/shared-second.bin",
            "role": "SNAPSHOT_CONTENT",
            "media_type": "application/octet-stream",
            "checksum": _checksum_raw(b"shared-component-second"),
            "component_ids": [shared_component_id],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "zz-bind-shared-component-second",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "shared-component-second-file",
        }
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files = copy.deepcopy(files)
    files["candidate/components/shared-second.bin"] = b"shared-component-second"
    with _stage_case(prefix="s2-bl6-component-multi-map", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        result,
        "COMPONENT_MAPPING_INVALID",
        exact_authority_error=True,
    )


def test_v2s2_bl6_component_id_casefold_collisions_are_duplicate_ids() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    baseline_component_id = _source_record(_load_registry_payload(), manifest["source_binding"]["source_id"])["components"][0]["component_id"]
    manifest["files"][0]["component_ids"] = [baseline_component_id.upper(), baseline_component_id]
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-bl6-component-casefold", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        result,
        "STAGING_DUPLICATE_ID",
        exact_authority_error=True,
    )


def test_v2s2_bl7_general_string_rules_reject_whitespace_control_and_overlength() -> None:
    cases = {
        "leading-space": lambda m: m["candidate"]["identity"].__setitem__("display_name", f" {m['candidate']['identity']['display_name']}"),
        "trailing-space": lambda m: m["candidate"]["identity"].__setitem__("owner", f"{m['candidate']['identity']['owner']} "),
        "control-char": lambda m: m["candidate"]["release"].__setitem__("content_pin_status", "ok\u0007bad"),
        "over-1024": lambda m: m["candidate"]["acquisition"].__setitem__("operator_contract", "x" * 1025),
    }
    for case_id, mutate in cases.items():
        manifest, files = _build_no_change_case(projection_complete=False)
        manifest = copy.deepcopy(manifest)
        mutate(manifest)
        manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
        with _stage_case(prefix=f"s2-bl7-string-{case_id}", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_failed_code_and_no_artifacts(
            result,
            "STAGING_MANIFEST_SCHEMA_INVALID",
            exact_authority_error=True,
        )


def test_v2s2_bl7_release_date_must_not_exceed_observed_at_utc_date() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["observed_at"] = "2026-08-17T00:00:00Z"
    manifest["candidate"]["release"]["release_date"] = "2026-08-18"
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-bl7-release-date", manifest=manifest, files=files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        result,
        "STAGING_MANIFEST_SCHEMA_INVALID",
        exact_authority_error=True,
    )


def test_v2s2_bl7_declaration_ref_bounds_and_component_id_count_are_closed() -> None:
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest = copy.deepcopy(manifest)
    manifest["source_binding"]["declaration_refs"] = []
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-bl7-decl-refs-empty", manifest=manifest, files=files) as (_, staging_rel):
        empty_refs_result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        empty_refs_result,
        "STAGING_MANIFEST_SCHEMA_INVALID",
        exact_authority_error=True,
    )

    over_component_ids = copy.deepcopy(_build_no_change_case(projection_complete=False)[0])
    over_component_ids["files"][0]["component_ids"] = [f"component-id-{idx:02d}" for idx in range(65)]
    over_component_ids["manifest_content_hash"] = _canonical_manifest_hash(over_component_ids)
    with _stage_case(prefix="s2-bl7-component-ids", manifest=over_component_ids, files=files) as (_, staging_rel):
        over_component_result = _run_verify_stage(staging_rel)
    _assert_failed_code_and_no_artifacts(
        over_component_result,
        "STAGING_MANIFEST_SCHEMA_INVALID",
        exact_authority_error=True,
    )


def test_v2s2_bl10_component_added_removed_value_shape_excludes_component_id() -> None:
    manifest, files = _build_no_change_case(projection_complete=True)
    manifest = copy.deepcopy(manifest)
    baseline_components = [copy.deepcopy(row) for row in manifest["component_projection"]["components"]]
    assert baseline_components, "real-source fixture must include baseline components"
    removed_component = baseline_components[0]
    added_component = {
        "component_id": "zz-added-shape-probe",
        "display_name": "Added shape probe",
        "source_role": "candidate_checksum_source",
        "version_or_snapshot": "added-shape-version-001",
        "licence_status": "declared",
        "declaration_locator": "configs/ingest/tsc.yaml#/added-shape-probe",
    }
    manifest["component_projection"]["components"] = sorted(
        [row for row in baseline_components if row["component_id"] != removed_component["component_id"]] + [added_component],
        key=lambda row: row["component_id"],
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl10-component-shape", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(result)
        assert result.returncode == 0, result.stdout
        report = _parse_json_stdout(result)
        diff_payload = json.loads(_artifact_abs_path(report["diff_artifact"]).read_text(encoding="utf-8"))
        added_fact = next(
            row
            for row in diff_payload["facts"]
            if row["subject_type"] == "COMPONENT" and row["subject_id"] == added_component["component_id"] and row["classification"] == "ADDED"
        )
        removed_fact = next(
            row
            for row in diff_payload["facts"]
            if row["subject_type"] == "COMPONENT" and row["subject_id"] == removed_component["component_id"] and row["classification"] == "REMOVED"
        )
        expected_keys = {"display_name", "source_role", "version_or_snapshot", "licence_status", "declaration_locator"}
        added_value = added_fact["after"]["value"]
        removed_value = removed_fact["before"]["value"]
        assert isinstance(added_value, dict) and isinstance(removed_value, dict)
        assert set(added_value) == expected_keys
        assert set(removed_value) == expected_keys
        assert "component_id" not in added_value and "component_id" not in removed_value
        _assert_self_excluding_hash(diff_payload)
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac06_declaration_vs_registry_invalid_exit_mapping_with_validator_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    from raptor.sourceops.model import ValidationError, ValidationResult

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _build_no_change_case(projection_complete=False)
    with _stage_case(prefix="s2-baseline-seam-declaration", manifest=manifest, files=files) as (_, staging_rel):
        declaration_error = ValidationResult(
            schema="raptor.source_registry.validation.v1",
            registry_valid=False,
            errors=[ValidationError(code="DECLARATION_DRIFT", message="drift", type="DeclarationDriftError")],
        )
        monkeypatch.setattr(staged_mod, "validate_registry", lambda *_args, **_kwargs: declaration_error, raising=True)
        code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    assert code == 6
    assert payload["run_status"] == "FAILED"
    assert _error_code(payload) == "BASELINE_DECLARATION_INVALID"

    with _stage_case(prefix="s2-baseline-seam-registry", manifest=manifest, files=files) as (_, staging_rel):
        registry_error = ValidationResult(
            schema="raptor.source_registry.validation.v1",
            registry_valid=False,
            errors=[ValidationError(code="REGISTRY_HASH_MISMATCH", message="hash", type="RegistryHashMismatch")],
        )
        monkeypatch.setattr(staged_mod, "validate_registry", lambda *_args, **_kwargs: registry_error, raising=True)
        code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    assert code == 6
    assert payload["run_status"] == "FAILED"
    assert _error_code(payload) == "BASELINE_REGISTRY_INVALID"


def test_v2s2_ac14_public_loader_and_typed_immutable_models_are_required() -> None:
    import importlib
    from collections.abc import Mapping
    from typing import Any, get_args, get_origin, get_type_hints

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    model_mod = importlib.import_module("raptor.sourceops.model")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest", None)
    assert callable(loader), "public SourceOps load_manifest loader is required by V2-S2 AC14"

    def _annotation_contains_any(annotation: Any) -> bool:
        if annotation is Any:
            return True
        return any(_annotation_contains_any(arg) for arg in get_args(annotation))

    manifest_hints = get_type_hints(model_mod.ManifestDocument)
    required_manifest_fields = tuple(_spec()["manifest_contract"]["top_level"]["required_exact"])
    for field_name in required_manifest_fields:
        assert field_name in manifest_hints, f"ManifestDocument must type-annotate required field {field_name!r}"
    for field_name in ("source_binding", "candidate", "files", "content_bindings", "component_projection"):
        annotation = manifest_hints[field_name]
        assert not _annotation_contains_any(annotation), f"ManifestDocument.{field_name} must not use Any"
        assert get_origin(annotation) not in {dict, list}, f"ManifestDocument.{field_name} must not be a mutable dict/list annotation"

    verify_hints = get_type_hints(model_mod.VerifyStageResult)
    assert "report" in verify_hints, "VerifyStageResult must have a typed report field"
    assert not _annotation_contains_any(verify_hints["report"])
    assert get_origin(verify_hints["report"]) is not dict

    manifest, files = _build_no_change_case(projection_complete=False)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-typed-loader", manifest=manifest, files=files) as (stage_root, staging_rel):
            manifest_model = loader(str(stage_root / "manifest.yaml"))
            assert not isinstance(manifest_model, Mapping), "load_manifest must return a typed immutable model"
            for field_name in required_manifest_fields:
                assert hasattr(manifest_model, field_name), f"typed manifest model is missing field {field_name!r}"
            with pytest.raises((AttributeError, TypeError)):
                setattr(manifest_model, "schema", "mutated")

            source_binding_model = getattr(manifest_model, "source_binding")
            candidate_model = getattr(manifest_model, "candidate")
            assert not isinstance(source_binding_model, Mapping), "source_binding must be a typed immutable row"
            assert not isinstance(candidate_model, Mapping), "candidate must be a typed immutable row"

            files_value = getattr(manifest_model, "files")
            assert isinstance(files_value, tuple), "manifest files must be immutable sequences"
            with pytest.raises((AttributeError, TypeError)):
                files_value.append("mutate-attempt")  # type: ignore[attr-defined]

            first_file = files_value[0]
            with pytest.raises((AttributeError, TypeError)):
                setattr(first_file, "path", "candidate/mutated-path")
            with pytest.raises((AttributeError, TypeError)):
                first_file.component_ids += ("mutate",)  # type: ignore[operator]

            verification_result = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
            assert not isinstance(verification_result, tuple), "verify_stage must return an immutable typed result object"
            report_model = verification_result.report
            assert not isinstance(report_model, Mapping), "VerifyStageResult.report must be typed, not a mutable dict"
            for field_name in _spec()["cli_contract"]["stdout"]["top_level_required_exact"]:
                assert hasattr(report_model, field_name), f"typed CLI result is missing {field_name!r}"
            with pytest.raises((AttributeError, TypeError)):
                setattr(report_model, "run_status", "MUTATED")
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize("case_id", NON_STRING_MAPPING_KEY_CASE_IDS)
def test_v2s2_bl9_non_string_yaml_mapping_keys_fail_closed_schema_envelope(case_id: str) -> None:
    manifest_bytes, files = _build_manifest_yaml_with_non_string_mapping_key(case_id)
    with _stage_case_with_raw_manifest(
        prefix=f"s2-bl9-non-string-keys-{case_id}",
        manifest_bytes=manifest_bytes,
        files=files,
    ) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    report = _assert_exact_invalid_failure_without_internal(
        result,
        expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
    )
    assert report["error"]["type"] == "StagingManifestSchemaError"
    assert report["error"]["phase"] == "MANIFEST_SCHEMA"
    assert report["error"]["message"] == "staged manifest violates the closed typed schema"
    for raw_exception_text in ("TypeError", "not supported between instances", "unhashable type"):
        assert raw_exception_text not in result.stdout
        assert raw_exception_text not in result.stderr


@pytest.mark.parametrize("case_id", NON_STRING_MAPPING_KEY_CASE_IDS)
def test_v2s2_bl9_load_manifest_rejects_non_string_yaml_mapping_keys_with_typed_schema_error(case_id: str) -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    manifest_bytes, files = _build_manifest_yaml_with_non_string_mapping_key(case_id)
    with _stage_case_with_raw_manifest(
        prefix=f"s2-bl9-loader-non-string-keys-{case_id}",
        manifest_bytes=manifest_bytes,
        files=files,
    ) as (stage_root, _):
        with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
            loader(str(stage_root / "manifest.yaml"))
    error = excinfo.value
    assert error.code == "STAGING_MANIFEST_SCHEMA_INVALID"
    assert error.__class__.__name__ == "StagingManifestSchemaError"
    assert getattr(error, "phase", None) == "MANIFEST_SCHEMA"
    assert str(error) == "staged manifest violates the closed typed schema"
    assert not isinstance(error, TypeError)
    for raw_exception_text in ("TypeError", "not supported between instances", "unhashable type"):
        assert raw_exception_text not in str(error)


@pytest.mark.parametrize("non_finite_token", NON_FINITE_YAML_FLOAT_TOKENS, ids=("nan", "pos-inf", "neg-inf"))
def test_v2s2_bl9_non_finite_yaml_mapping_keys_fail_schema_without_serialization_escape(non_finite_token: str) -> None:
    manifest_bytes, files = _build_manifest_yaml_with_non_finite_mapping_keys(non_finite_token)
    with _stage_case_with_raw_manifest(
        prefix=f"s2-bl9-non-finite-keys-{non_finite_token.replace('.', '').replace('-', 'neg')}",
        manifest_bytes=manifest_bytes,
        files=files,
    ) as (_, staging_rel):
        result = _run_verify_stage_bytes(staging_rel)
    stderr_text = result.stderr.decode("utf-8", errors="replace")
    assert result.returncode != 1, f"verify-stage must not escape with exit 1\nstderr={stderr_text!r}"
    report = _assert_stdout_bytes_one_lf_canonical_json_and_empty_stderr(result)
    _assert_exact_error_from_authority(
        report,
        expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
        expected_exit=2,
    )
    assert result.returncode == 2
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == "INVALID"
    assert report["stage_outcome"] is None
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    assert _error_code(report) != "INTERNAL_ERROR"
    _assert_json_compatible_with_allow_nan_false(report["error"], label="CLI error envelope")
    stdout_text = result.stdout.decode("utf-8")
    for raw_exception_text in ("Traceback", "Out of range float values are not JSON compliant", "maximum recursion depth exceeded"):
        assert raw_exception_text not in stdout_text
        assert raw_exception_text not in stderr_text


@pytest.mark.parametrize("non_finite_token", NON_FINITE_YAML_FLOAT_TOKENS, ids=("nan", "pos-inf", "neg-inf"))
def test_v2s2_bl9_load_manifest_rejects_non_finite_yaml_mapping_keys_with_json_compatible_typed_schema_error(
    non_finite_token: str,
) -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    manifest_bytes, files = _build_manifest_yaml_with_non_finite_mapping_keys(non_finite_token)
    with _stage_case_with_raw_manifest(
        prefix=f"s2-bl9-loader-non-finite-keys-{non_finite_token.replace('.', '').replace('-', 'neg')}",
        manifest_bytes=manifest_bytes,
        files=files,
    ) as (stage_root, _):
        with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
            loader(str(stage_root / "manifest.yaml"))
    error = excinfo.value
    assert error.code == "STAGING_MANIFEST_SCHEMA_INVALID"
    assert error.__class__.__name__ == "StagingManifestSchemaError"
    assert getattr(error, "phase", None) == "MANIFEST_SCHEMA"
    assert str(error) == "staged manifest violates the closed typed schema"
    assert not isinstance(error, (TypeError, ValueError))
    for detail_name in ("subject", "expected", "actual"):
        _assert_json_compatible_with_allow_nan_false(
            getattr(error, detail_name, None),
            label=f"load_manifest error.{detail_name}",
        )
    for raw_exception_text in ("TypeError", "ValueError", "Out of range float values are not JSON compliant"):
        assert raw_exception_text not in str(error)


@pytest.mark.parametrize(
    "case_id,field_name,value_token",
    NON_FINITE_WRONG_TYPE_VALUE_CASES,
    ids=tuple(case_id for case_id, _, _ in NON_FINITE_WRONG_TYPE_VALUE_CASES),
)
def test_v2s2_bl9_non_finite_wrong_typed_values_fail_schema_without_serialization_escape(
    case_id: str,
    field_name: str,
    value_token: str,
) -> None:
    manifest_bytes, files = _build_manifest_yaml_with_non_finite_wrong_type_value(
        case_id=case_id,
        field_name=field_name,
        value_token=value_token,
    )
    with _stage_case_with_raw_manifest(
        prefix=f"s2-bl9-non-finite-values-{case_id}",
        manifest_bytes=manifest_bytes,
        files=files,
    ) as (_, staging_rel):
        result = _run_verify_stage_bytes(staging_rel)
    stderr_text = result.stderr.decode("utf-8", errors="replace")
    assert result.returncode != 1, f"verify-stage must not escape with exit 1\nstderr={stderr_text!r}"
    report = _assert_stdout_bytes_one_lf_canonical_json_and_empty_stderr(result)
    _assert_exact_error_from_authority(
        report,
        expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
        expected_exit=2,
    )
    assert result.returncode == 2
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == "INVALID"
    assert report["stage_outcome"] is None
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    assert _error_code(report) != "INTERNAL_ERROR"
    _assert_json_compatible_with_allow_nan_false(report["error"], label="CLI error envelope")
    stdout_text = result.stdout.decode("utf-8")
    for raw_exception_text in ("Traceback", "Out of range float values are not JSON compliant", "maximum recursion depth exceeded"):
        assert raw_exception_text not in stdout_text
        assert raw_exception_text not in stderr_text


@pytest.mark.parametrize(
    "case_id,field_name,value_token",
    NON_FINITE_WRONG_TYPE_VALUE_CASES,
    ids=tuple(case_id for case_id, _, _ in NON_FINITE_WRONG_TYPE_VALUE_CASES),
)
def test_v2s2_bl9_load_manifest_rejects_non_finite_wrong_typed_values_with_json_compatible_typed_schema_error(
    case_id: str,
    field_name: str,
    value_token: str,
) -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    manifest_bytes, files = _build_manifest_yaml_with_non_finite_wrong_type_value(
        case_id=case_id,
        field_name=field_name,
        value_token=value_token,
    )
    with _stage_case_with_raw_manifest(
        prefix=f"s2-bl9-loader-non-finite-values-{case_id}",
        manifest_bytes=manifest_bytes,
        files=files,
    ) as (stage_root, _):
        with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
            loader(str(stage_root / "manifest.yaml"))
    error = excinfo.value
    assert error.code == "STAGING_MANIFEST_SCHEMA_INVALID"
    assert error.__class__.__name__ == "StagingManifestSchemaError"
    assert getattr(error, "phase", None) == "MANIFEST_SCHEMA"
    assert str(error) == "staged manifest violates the closed typed schema"
    assert not isinstance(error, (TypeError, ValueError))
    for detail_name in ("subject", "expected", "actual"):
        _assert_json_compatible_with_allow_nan_false(
            getattr(error, detail_name, None),
            label=f"load_manifest error.{detail_name}",
        )
    for raw_exception_text in ("TypeError", "ValueError", "Out of range float values are not JSON compliant"):
        assert raw_exception_text not in str(error)


@pytest.mark.parametrize(
    "case_id,field_case_id,field_subject,wrong_value",
    UNHASHABLE_CONTAINER_FIELD_CASES,
    ids=tuple(case_id for case_id, _, _, _ in UNHASHABLE_CONTAINER_FIELD_CASES),
)
def test_v2s2_bl9_unhashable_container_values_fail_closed_schema_envelope_without_internal_escape(
    case_id: str,
    field_case_id: str,
    field_subject: str,
    wrong_value: Any,
) -> None:
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    _apply_unhashable_manifest_probe_value(
        manifest,
        field_case_id=field_case_id,
        value=copy.deepcopy(wrong_value),
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl9-ucli", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        report = _assert_exact_invalid_failure_without_internal(
            result,
            expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
        )
        assert report["error"]["type"] == "StagingManifestSchemaError"
        assert report["error"]["phase"] == "MANIFEST_SCHEMA"
        assert report["error"]["message"] == "staged manifest violates the closed typed schema"
        assert report["error"]["subject"] is not None, f"{field_subject}: subject must remain populated"
        for raw_exception_text in ("TypeError", "unhashable type", "INTERNAL_ERROR", "Traceback"):
            assert raw_exception_text not in result.stdout
            assert raw_exception_text not in result.stderr
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "case_id,field_case_id,field_subject,wrong_value",
    UNHASHABLE_CONTAINER_FIELD_CASES,
    ids=tuple(case_id for case_id, _, _, _ in UNHASHABLE_CONTAINER_FIELD_CASES),
)
def test_v2s2_bl9_load_manifest_rejects_unhashable_container_values_with_typed_schema_error(
    case_id: str,
    field_case_id: str,
    field_subject: str,
    wrong_value: Any,
) -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    _apply_unhashable_manifest_probe_value(
        manifest,
        field_case_id=field_case_id,
        value=copy.deepcopy(wrong_value),
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix="s2-bl9-uldr", manifest=manifest, files=files) as (stage_root, _):
        with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
            loader(str(stage_root / "manifest.yaml"))
    error = excinfo.value
    assert error.code == "STAGING_MANIFEST_SCHEMA_INVALID"
    assert error.__class__.__name__ == "StagingManifestSchemaError"
    assert getattr(error, "phase", None) == "MANIFEST_SCHEMA"
    assert str(error) == "staged manifest violates the closed typed schema"
    assert not isinstance(error, TypeError)
    assert getattr(error, "subject", None) is not None, f"{field_subject}: subject must remain populated"
    for raw_exception_text in ("TypeError", "unhashable type", "INTERNAL_ERROR", "Traceback"):
        assert raw_exception_text not in str(error)


@pytest.mark.parametrize(
    "case_id,field_case_id,wrong_value",
    UNHASHABLE_SCALAR_CONTROL_CASES,
    ids=tuple(case_id for case_id, _, _ in UNHASHABLE_SCALAR_CONTROL_CASES),
)
def test_v2s2_bl9_unhashable_probe_scalar_controls_fail_schema_without_internal_escape(
    case_id: str,
    field_case_id: str,
    wrong_value: Any,
) -> None:
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    _apply_unhashable_manifest_probe_value(
        manifest,
        field_case_id=field_case_id,
        value=wrong_value,
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl9-uscalar", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_exact_invalid_failure_without_internal(
            result,
            expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
        )
        for raw_exception_text in ("TypeError", "unhashable type", "INTERNAL_ERROR", "Traceback"):
            assert raw_exception_text not in result.stdout
            assert raw_exception_text not in result.stderr
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "field_case_id,field_subject",
    UNHASHABLE_MANIFEST_FIELD_CASES,
    ids=tuple(case_id for case_id, _ in UNHASHABLE_MANIFEST_FIELD_CASES),
)
def test_v2s2_bl9_unhashable_probe_valid_string_controls_remain_green(
    field_case_id: str,
    field_subject: str,
) -> None:
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    control_value = _current_unhashable_manifest_probe_string_value(
        manifest,
        field_case_id=field_case_id,
    )
    _apply_unhashable_manifest_probe_value(
        manifest,
        field_case_id=field_case_id,
        value=control_value,
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl9-uvalid", manifest=manifest, files=files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_stdout_one_line_json(result)
        assert result.returncode == 0, f"{field_subject}: {result.stdout}"
        report = _parse_json_stdout(result)
        assert report["run_status"] == "COMPLETED"
        assert report["input_validity"] == "VALID"
        assert report["error"] is None
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "case_id,exception_factory,expected_code,expected_exit,expected_input_validity,forbidden_tokens",
    [
        (
            "foreseeable-typeerror",
            lambda: TypeError("synthetic unhashable type loader probe"),
            "STAGING_MANIFEST_SCHEMA_INVALID",
            2,
            "INVALID",
            ("TypeError", "unhashable type", "synthetic unhashable type loader probe"),
        ),
        (
            "unexpected-runtimeerror",
            lambda: RuntimeError("synthetic unexpected loader boundary failure"),
            "INTERNAL_ERROR",
            70,
            "NOT_EVALUATED",
            ("RuntimeError", "synthetic unexpected loader boundary failure"),
        ),
    ],
    ids=("foreseeable-typeerror", "unexpected-runtimeerror"),
)
def test_v2s2_bl9_verify_stage_loader_boundary_maps_foreseeable_type_failures_to_schema_invalid_and_unexpected_to_internal70(
    case_id: str,
    exception_factory: Any,
    expected_code: str,
    expected_exit: int,
    expected_input_validity: str,
    forbidden_tokens: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    real_loader = sourceops_pkg.load_manifest

    def _boundary_loader(path: str) -> Any:
        _ = real_loader(path)
        raise exception_factory()

    monkeypatch.setattr(sourceops_pkg, "load_manifest", _boundary_loader, raising=True)
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl9-uboundary", manifest=manifest, files=files) as (_, staging_rel):
            outcome = sourceops_pkg.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        report = outcome.report.as_dict()
        assert outcome.exit_code == expected_exit
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == expected_input_validity
        assert report["stage_outcome"] is None
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        _assert_exact_error_from_authority(
            report,
            expected_code=expected_code,
            expected_exit=expected_exit,
        )
        if expected_code == "STAGING_MANIFEST_SCHEMA_INVALID":
            assert report["error"]["type"] == "StagingManifestSchemaError"
            assert report["error"]["phase"] == "MANIFEST_SCHEMA"
        else:
            assert report["error"]["phase"] == "INTERNAL"
        flattened_report = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        for token in forbidden_tokens:
            assert token not in flattened_report
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "case_id,manifest_bytes",
    [
        (
            "complex-list-key",
            b"schema: raptor.sourceops.staged_snapshot_manifest.v1\n? [a, b]\n: complex-list-key-probe\n",
        ),
        (
            "complex-mapping-key",
            b"schema: raptor.sourceops.staged_snapshot_manifest.v1\n? {a: 1}\n: complex-mapping-key-probe\n",
        ),
    ],
    ids=("complex-list-key", "complex-mapping-key"),
)
def test_v2s2_bl9_complex_yaml_mapping_keys_fail_closed_yaml_envelope(
    case_id: str,
    manifest_bytes: bytes,
) -> None:
    with _stage_case_with_raw_manifest(
        prefix=f"s2-bl9-complex-keys-{case_id}",
        manifest_bytes=manifest_bytes,
    ) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    report = _assert_exact_invalid_failure_without_internal(
        result,
        expected_code="STAGING_MANIFEST_YAML_INVALID",
    )
    assert report["error"]["type"] == "StagingManifestYamlError"
    assert report["error"]["phase"] == "MANIFEST_SCHEMA"
    assert report["error"]["message"] == "staged manifest is not one safe YAML mapping document"
    for raw_exception_text in ("TypeError", "unhashable type", "not supported between instances"):
        assert raw_exception_text not in result.stdout
        assert raw_exception_text not in result.stderr


@pytest.mark.parametrize(
    "case_id,manifest_bytes",
    [
        (
            "complex-list-key",
            b"schema: raptor.sourceops.staged_snapshot_manifest.v1\n? [a, b]\n: complex-list-key-probe\n",
        ),
        (
            "complex-mapping-key",
            b"schema: raptor.sourceops.staged_snapshot_manifest.v1\n? {a: 1}\n: complex-mapping-key-probe\n",
        ),
    ],
    ids=("complex-list-key", "complex-mapping-key"),
)
def test_v2s2_bl9_load_manifest_rejects_complex_yaml_mapping_keys_with_typed_yaml_error(
    case_id: str,
    manifest_bytes: bytes,
) -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    with _stage_case_with_raw_manifest(
        prefix=f"s2-bl9-loader-complex-keys-{case_id}",
        manifest_bytes=manifest_bytes,
    ) as (stage_root, _):
        with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
            loader(str(stage_root / "manifest.yaml"))
    error = excinfo.value
    assert error.code == "STAGING_MANIFEST_YAML_INVALID"
    assert error.__class__.__name__ == "StagingManifestYamlError"
    assert getattr(error, "phase", None) == "MANIFEST_SCHEMA"
    assert str(error) == "staged manifest is not one safe YAML mapping document"
    assert not isinstance(error, TypeError)
    for raw_exception_text in ("TypeError", "unhashable type", "not supported between instances"):
        assert raw_exception_text not in str(error)


def test_v2s2_bl9_unknown_string_mapping_key_control_remains_schema_invalid() -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    manifest_bytes, files = _build_manifest_yaml_with_string_unknown_key_control()
    with _stage_case_with_raw_manifest(
        prefix="s2-bl9-string-key-control",
        manifest_bytes=manifest_bytes,
        files=files,
    ) as (stage_root, staging_rel):
        cli_result = _run_verify_stage(staging_rel)
        with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
            loader(str(stage_root / "manifest.yaml"))
    report = _assert_exact_invalid_failure_without_internal(
        cli_result,
        expected_code="STAGING_MANIFEST_SCHEMA_INVALID",
    )
    assert report["error"]["type"] == "StagingManifestSchemaError"
    assert _error_code(report) != "STAGING_MANIFEST_YAML_INVALID"
    error = excinfo.value
    assert error.code == "STAGING_MANIFEST_SCHEMA_INVALID"
    assert error.__class__.__name__ == "StagingManifestSchemaError"
    assert getattr(error, "phase", None) == "MANIFEST_SCHEMA"
    assert str(error) == "staged manifest violates the closed typed schema"


@pytest.mark.parametrize(
    "depth,expected_code",
    [
        (8, "STAGING_MANIFEST_SCHEMA_INVALID"),
        (17, "STAGING_MANIFEST_LIMIT_EXCEEDED"),
        (40, "STAGING_MANIFEST_LIMIT_EXCEEDED"),
        (2500, "STAGING_MANIFEST_LIMIT_EXCEEDED"),
    ],
    ids=("depth-8-control", "depth-17-control", "depth-40-control", "depth-2500-extreme"),
)
def test_v2s2_bl9_deep_flow_sequence_depth_controls_and_extreme_nesting_fail_closed(
    depth: int,
    expected_code: str,
) -> None:
    manifest_bytes = _build_manifest_yaml_with_deep_flow_sequence(depth)
    with _stage_case_with_raw_manifest(
        prefix=f"s2-bl9-flow-depth-{depth}",
        manifest_bytes=manifest_bytes,
    ) as (_, staging_rel):
        result = _run_verify_stage_bytes(staging_rel)
    stderr_text = result.stderr.decode("utf-8", errors="replace")
    assert result.returncode != 1, f"verify-stage must not escape with exit 1\nstderr={stderr_text!r}"
    report = _assert_stdout_bytes_one_lf_canonical_json_and_empty_stderr(result)
    _assert_exact_error_from_authority(report, expected_code=expected_code, expected_exit=2)
    assert result.returncode == 2
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == "INVALID"
    assert report["stage_outcome"] is None
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    assert _error_code(report) != "INTERNAL_ERROR"
    _assert_json_compatible_with_allow_nan_false(report["error"], label="CLI error envelope")
    stdout_text = result.stdout.decode("utf-8")
    for raw_exception_text in ("Traceback", "RecursionError", "maximum recursion depth exceeded"):
        assert raw_exception_text not in stdout_text
        assert raw_exception_text not in stderr_text


def test_v2s2_bl9_load_manifest_maps_extreme_flow_sequence_nesting_to_typed_limit_error() -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    manifest_bytes = _build_manifest_yaml_with_deep_flow_sequence(2500)
    with _stage_case_with_raw_manifest(
        prefix="s2-bl9-loader-flow-depth-2500",
        manifest_bytes=manifest_bytes,
    ) as (stage_root, _):
        with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
            loader(str(stage_root / "manifest.yaml"))
    error = excinfo.value
    assert error.code == "STAGING_MANIFEST_LIMIT_EXCEEDED"
    assert error.__class__.__name__ == "StagingManifestLimitError"
    assert getattr(error, "phase", None) == "MANIFEST_READ"
    assert str(error) == "staged manifest exceeds a closed size or structure limit"
    assert not isinstance(error, RecursionError)
    for detail_name in ("subject", "expected", "actual"):
        _assert_json_compatible_with_allow_nan_false(
            getattr(error, detail_name, None),
            label=f"load_manifest error.{detail_name}",
        )
    for raw_exception_text in ("RecursionError", "maximum recursion depth exceeded", "Traceback"):
        assert raw_exception_text not in str(error)


def test_v2s2_bl9_load_manifest_runs_same_strict_validation_as_verify_stage() -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    invalid_cases = {
        "duplicate-key": b"schema: one\nschema: two\n",
        "alias": b"schema: &s raptor.sourceops.staged_snapshot_manifest.v1\nschema_copy: *s\n",
    }
    for case_id, raw in invalid_cases.items():
        STAGING_PARENT.mkdir(parents=True, exist_ok=True)
        stage_name = f"s2-bl9-loader-{case_id}-{uuid.uuid4().hex[:10]}"
        stage_root = STAGING_PARENT / stage_name
        stage_root.mkdir(parents=False, exist_ok=False)
        try:
            manifest_path = stage_root / "manifest.yaml"
            manifest_path.write_bytes(raw)
            verify_result = _run_verify_stage(f".raptor/sourceops/staging/{stage_name}")
            _assert_stdout_one_line_json(verify_result)
            verify_report = _parse_json_stdout(verify_result)
            expected_code = _error_code(verify_report)
            assert expected_code is not None
            with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
                loader(str(manifest_path))
            assert excinfo.value.code == expected_code
        finally:
            _remove_path(stage_root)


@pytest.mark.parametrize(
    "case_id,reverse_files,reverse_bindings",
    [
        ("files-descending", True, False),
        ("bindings-descending", False, True),
    ],
)
def test_v2s2_bl9_load_manifest_rejects_descending_sequences_before_baseline(
    case_id: str,
    reverse_files: bool,
    reverse_bindings: bool,
) -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    manifest["source_binding"]["source_id"] = "unknown-source-loader-order-probe"
    manifest["files"] = sorted(
        manifest["files"],
        key=lambda row: row["file_id"],
        reverse=reverse_files,
    )
    manifest["content_bindings"] = sorted(
        manifest["content_bindings"],
        key=lambda row: row["binding_id"],
        reverse=reverse_bindings,
    )
    if reverse_files:
        assert [row["file_id"] for row in manifest["files"]] == sorted(
            (row["file_id"] for row in manifest["files"]),
            reverse=True,
        )
        assert [row["binding_id"] for row in manifest["content_bindings"]] == sorted(
            row["binding_id"] for row in manifest["content_bindings"]
        )
    if reverse_bindings:
        assert [row["file_id"] for row in manifest["files"]] == sorted(
            row["file_id"] for row in manifest["files"]
        )
        assert [row["binding_id"] for row in manifest["content_bindings"]] == sorted(
            (row["binding_id"] for row in manifest["content_bindings"]),
            reverse=True,
        )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix=f"s2-bl9-loader-order-{case_id}", manifest=manifest, files=files) as (stage_root, _):
        with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
            loader(str(stage_root / "manifest.yaml"))
    assert excinfo.value.code == "STAGING_MANIFEST_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "case_id,sequence_key,identifier_key,wrong_value",
    MIXED_IDENTIFIER_WRONG_TYPE_CASES,
)
def test_v2s2_bl9_load_manifest_rejects_mixed_scalar_identifier_types_with_typed_schema_error(
    case_id: str,
    sequence_key: str,
    identifier_key: str,
    wrong_value: Any,
) -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    loader = getattr(sourceops_pkg, "load_manifest")
    manifest, files = _build_two_file_two_binding_case()
    manifest = copy.deepcopy(manifest)
    manifest[sequence_key][0][identifier_key] = wrong_value
    mixed_identifiers = [row[identifier_key] for row in manifest[sequence_key]]
    assert any(isinstance(value, str) for value in mixed_identifiers)
    assert any(not isinstance(value, str) for value in mixed_identifiers)
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case(prefix=f"s2-bl9-loader-mixed-id-type-{case_id}", manifest=manifest, files=files) as (stage_root, _):
        with pytest.raises(staged_mod.StagedSnapshotError) as excinfo:
            loader(str(stage_root / "manifest.yaml"))
    error = excinfo.value
    assert error.code == "STAGING_MANIFEST_SCHEMA_INVALID"
    assert error.__class__.__name__ == "StagingManifestSchemaError"
    assert getattr(error, "phase", None) == "MANIFEST_SCHEMA"
    assert str(error) == "staged manifest violates the closed typed schema"
    assert not isinstance(error, TypeError)
    assert "TypeError" not in str(error)


def test_v2s2_bl9_verify_stage_consumes_public_typed_manifest_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    sourceops_pkg = importlib.import_module("raptor.sourceops")
    real_loader = sourceops_pkg.load_manifest
    call_count = {"value": 0}

    def _counting_loader(path: str) -> Any:
        call_count["value"] += 1
        return real_loader(path)

    monkeypatch.setattr(sourceops_pkg, "load_manifest", _counting_loader, raising=True)
    manifest, files = _build_no_change_case(projection_complete=False)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-bl9-loader-seam", manifest=manifest, files=files) as (_, staging_rel):
            result = sourceops_pkg.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert result.exit_code == 0
        assert call_count["value"] >= 1, "verify_stage must obtain the manifest through the public typed loader"
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_b13_all_authority_ids_are_mapped_to_named_tests() -> None:
    import ast

    expected_ids = {f"V2S2-AC{idx:02d}" for idx in range(1, 19)}
    expected_ids.update({f"V2S2-FM{idx:02d}" for idx in range(1, 10)})
    expected_ids.update({"V2S2-FM10", "V2S2-FM10B"})
    expected_ids.update({f"V2S2-FM{idx:02d}" for idx in range(11, 17)})

    coverage_map: dict[str, tuple[str, ...]] = {
        "V2S2-AC01": (
            "test_manifest_invalidity_cases_fail_without_artifacts",
            "test_v2s2_ac01_manifest_missing_emits_exact_code",
            "test_v2s2_ac01_manifest_type_invalid_emits_exact_code",
            "test_v2s2_ac01_manifest_read_failed_emits_exact_code",
            "test_v2s2_ac01_manifest_limit_exceeded_emits_exact_code",
            "test_v2s2_ac04_component_projection_count_boundary_uses_manifest_limit_catalog_row",
            "test_v2s2_ac01_retrieved_at_must_not_be_after_observed_at",
            "test_v2s2_ac01_bool_is_not_valid_integer_for_raw_byte_size",
            "test_v2s2_bl6_row_required_keys_fail_closed_before_duplicate_and_path_scans",
            "test_v2s2_bl7_general_string_rules_reject_whitespace_control_and_overlength",
            "test_v2s2_bl7_release_date_must_not_exceed_observed_at_utc_date",
            "test_v2s2_bl7_declaration_ref_bounds_and_component_id_count_are_closed",
            "test_v2s2_bl7_manifest_node_and_depth_limits_use_manifest_limit_code",
            "test_v2s2_bl6_manifest_schema_phase_precedes_baseline_unknown_source_for_descending_files",
            "test_v2s2_bl6_mixed_scalar_and_string_identifiers_fail_schema_without_internal_error",
            "test_v2s2_bl9_load_manifest_rejects_mixed_scalar_identifier_types_with_typed_schema_error",
            "test_v2s2_bl9_non_string_yaml_mapping_keys_fail_closed_schema_envelope",
            "test_v2s2_bl9_load_manifest_rejects_non_string_yaml_mapping_keys_with_typed_schema_error",
            "test_v2s2_bl9_non_finite_yaml_mapping_keys_fail_schema_without_serialization_escape",
            "test_v2s2_bl9_load_manifest_rejects_non_finite_yaml_mapping_keys_with_json_compatible_typed_schema_error",
            "test_v2s2_bl9_non_finite_wrong_typed_values_fail_schema_without_serialization_escape",
            "test_v2s2_bl9_load_manifest_rejects_non_finite_wrong_typed_values_with_json_compatible_typed_schema_error",
            "test_v2s2_bl9_unhashable_container_values_fail_closed_schema_envelope_without_internal_escape",
            "test_v2s2_bl9_load_manifest_rejects_unhashable_container_values_with_typed_schema_error",
            "test_v2s2_bl9_unhashable_probe_scalar_controls_fail_schema_without_internal_escape",
            "test_v2s2_bl9_complex_yaml_mapping_keys_fail_closed_yaml_envelope",
            "test_v2s2_bl9_load_manifest_rejects_complex_yaml_mapping_keys_with_typed_yaml_error",
            "test_v2s2_bl9_unknown_string_mapping_key_control_remains_schema_invalid",
            "test_v2s2_bl9_deep_flow_sequence_depth_controls_and_extreme_nesting_fail_closed",
            "test_v2s2_bl9_load_manifest_maps_extreme_flow_sequence_nesting_to_typed_limit_error",
        ),
        "V2S2-AC02": (
            "test_verify_stage_exit_partition_unknown_source_vs_hash_vs_binding_mismatch",
            "test_v2s2_ac01_ac02_unknown_declaration_binding_target_is_content_binding_invalid",
            "test_v2s2_ac01_ac02_unknown_component_binding_target_is_content_binding_invalid",
            "test_v2s2_ac02_ac06_initial_malformed_registry_yaml_maps_to_baseline_registry_invalid",
            "test_v2s2_ac02_ac06_initial_nonutf8_registry_maps_to_baseline_registry_invalid",
            "test_v2s2_ac02_ac06_initial_wrong_typed_registry_maps_to_baseline_registry_invalid",
        ),
        "V2S2-AC03": (
            "test_staging_root_boundary_rejects_non_canonical_paths",
            "test_v2s2_ac03_ac13_fm01_fm12_staging_root_empty_or_whitespace_emits_catalog_error",
            "test_manifest_path_rules_reject_unsafe_and_case_colliding_paths",
            "test_symlink_staging_entries_are_rejected_when_supported",
            "test_v2s2_ac03_fm02_windows_stage_root_junction_is_rejected",
            "test_v2s2_ac03_fm02_windows_nested_junction_entry_is_rejected",
            "test_v2s2_ac03_fm02_windows_stage_root_junction_without_isjunction_is_rejected",
            "test_v2s2_ac03_fm02_windows_nested_junction_without_isjunction_is_rejected",
            "test_v2s2_ac03_fm02_windows_is_windows_reparse_detects_real_junction_without_isjunction",
            "test_v2s2_fm02_dangling_symlink_listed_file_path_is_inventory_entry_type_invalid",
            "test_v2s2_fm02_external_symlink_target_is_rejected_before_read_bytes",
            "test_v2s2_fm02_posix_fifo_listed_file_is_rejected_before_read",
            "test_v2s2_ac03_staging_path_invalid_unlisted_reserved_entry_emits_catalog_envelope",
            "test_v2s2_bl1_staging_parent_link_component_is_rejected_even_when_target_inside_repo",
            "test_v2s2_bl2_staging_nested_directory_link_components_are_rejected",
            "test_v2s2_bl8_staging_path_invalid_uses_inventory_phase_and_exact_message",
        ),
        "V2S2-AC04": (
            "test_staging_tree_exactness_rejects_unknown_missing_and_unneeded_entries",
            "test_v2s2_ac01_ac04_every_staged_file_must_be_bound_exactly_once",
            "test_v2s2_ac04_staging_limit_exceeded_depth_emits_exact_code",
            "test_v2s2_ac04_component_projection_count_boundary_uses_manifest_limit_catalog_row",
            "test_v2s2_bl7_inventory_limit_per_file_size_uses_exact_limit_error",
            "test_v2s2_bl7_inventory_limit_total_bound_bytes_uses_exact_limit_error",
            "test_v2s2_bl7_snapshot_per_file_limit_rejects_before_read",
            "test_v2s2_bl7_snapshot_total_limit_rejects_before_read_of_offending_file",
            "test_v2s2_bl7_unlisted_oversized_file_fails_limit_before_tree_mismatch_without_read",
            "test_v2s2_bl7_unlisted_total_limit_subject_is_deterministic_before_read",
            "test_v2s2_bl7_boundary_sized_file_remains_eligible_for_content_validation",
            "test_v2s2_bl7_directory_count_limit_is_enforced_at_inventory_phase",
            "test_v2s2_bl7_unlisted_extreme_depth_guard_avoids_recursion_and_internal_escape",
        ),
        "V2S2-AC05": (
            "test_canonical_lf_text_and_raw_bytes_cross_newline_determinism",
            "test_v2s2_ac05_declaration_binding_requires_declaration_role_and_canonical_text",
            "test_v2s2_ac05_canonical_text_media_type_must_be_from_allowed_set",
            "test_v2s2_ac05_staging_text_encoding_invalid_emits_exact_code",
            "test_v2s2_bl5_declaration_ref_binding_rejects_raw_bytes_mode",
            "test_v2s2_bl5_component_checksum_variant_constraints_are_enforced",
            "test_v2s2_bl5_component_checksum_null_candidate_requires_sha256_baseline",
            "test_v2s2_bl5_component_checksum_source_role_requires_checksum_token",
        ),
        "V2S2-AC06": (
            "test_v2s2_ac06_declaration_vs_registry_invalid_exit_mapping_with_validator_seam",
            "test_v2s2_bl11_initial_baseline_must_use_v2s1_load_registry",
            "test_v2s2_bl11_second_pass_reruns_validator_and_detects_changed_validation_result",
            "test_v2s2_ac02_ac06_initial_malformed_registry_yaml_maps_to_baseline_registry_invalid",
            "test_v2s2_ac02_ac06_initial_nonutf8_registry_maps_to_baseline_registry_invalid",
            "test_v2s2_ac02_ac06_initial_wrong_typed_registry_maps_to_baseline_registry_invalid",
            "test_v2s2_ac06_ac07_bl11_baseline_passes_use_public_load_registry_twice",
            "test_v2s2_ac06_bl11_first_pass_public_loader_failure_is_mapped_to_baseline_registry_invalid",
        ),
        "V2S2-AC07": (
            "test_two_pass_staging_input_mutation_detection_blocks_artifact_writes",
            "test_v2s2_ac07_fm10b_registry_mutation_between_baseline_snapshots_fails_closed",
            "test_v2s2_ac07_fm10b_declaration_mutation_between_baseline_snapshots_fails_closed",
            "test_v2s2_bl7_snapshot_per_file_limit_rejects_before_read",
            "test_v2s2_bl7_snapshot_total_limit_rejects_before_read_of_offending_file",
            "test_v2s2_bl11_registry_mutation_between_validation_and_output_is_detected",
            "test_v2s2_bl11_second_pass_reruns_validator_and_detects_changed_validation_result",
            "test_v2s2_ac06_ac07_fm10b_mid_run_registry_malformed_yaml_maps_to_baseline_changed_during_run",
            "test_v2s2_ac06_ac07_fm10b_mid_run_registry_nonutf8_maps_to_baseline_changed_during_run",
            "test_v2s2_ac06_ac07_bl11_baseline_passes_use_public_load_registry_twice",
        ),
        "V2S2-AC08": (
            "test_diff_fact_ordering_summary_and_self_hash_rules",
            "test_component_projection_null_vs_complete_semantics",
            "test_v2s2_ac08_single_source_complete_component_projection_is_component_mapping_invalid",
            "test_v2s2_ac08_metadata_catalog_template_non_empty_complete_projection_is_component_mapping_invalid",
            "test_v2s2_ac08_none_binding_on_candidate_declaration_uses_declaration_difference_kind",
            "test_v2s2_bl3_complete_projection_accepts_added_component_and_preserves_classifications",
            "test_v2s2_bl6_files_sequence_must_be_strictly_ascending_by_file_id",
            "test_v2s2_bl6_files_and_content_bindings_both_descending_without_auxiliary_roles_are_schema_invalid",
            "test_v2s2_bl6_content_bindings_sequence_must_be_strictly_ascending_by_binding_id",
            "test_v2s2_bl6_manifest_schema_phase_precedes_baseline_unknown_source_for_descending_files",
            "test_v2s2_bl6_file_paths_cannot_be_ancestor_of_each_other",
            "test_v2s2_bl6_component_ids_must_match_candidate_projection_identities",
            "test_v2s2_bl6_one_component_cannot_map_to_multiple_files",
            "test_v2s2_bl6_component_id_casefold_collisions_are_duplicate_ids",
            "test_v2s2_bl10_component_added_removed_value_shape_excludes_component_id",
        ),
        "V2S2-AC09": (
            "test_no_change_real_ingest_candidate_produces_deterministic_no_difference_artifacts",
            "test_changed_candidate_produces_fact_only_observed_difference",
        ),
        "V2S2-AC10": (
            "test_canonical_lf_text_and_raw_bytes_cross_newline_determinism",
            "test_v2s2_ac10_ac11_ac13_fm12_stdout_bytes_contract_holds_on_success_and_failure",
            "test_verify_stage_exit_partition_baseline_path_invalid_input_invalid_and_output_collision",
            "test_v2s2_fm09_timezone_locale_mtime_and_command_time_do_not_change_stdout_bytes",
        ),
        "V2S2-AC11": (
            "test_no_change_real_ingest_candidate_produces_deterministic_no_difference_artifacts",
            "test_diff_fact_ordering_summary_and_self_hash_rules",
            "test_v2s2_b13_input_tree_content_hash_uses_files_sequence_basis_only",
            "test_v2s2_bl10_component_added_removed_value_shape_excludes_component_id",
        ),
        "V2S2-AC12": (
            "test_v2s2_ac12_ac13_fm16_concurrent_identical_writers_succeed_idempotently",
            "test_v2s2_ac12_fm16_leaf_mkdir_fileexists_race_recovers_without_internal70",
            "test_v2s2_ac12_fm16_mid_publication_identical_winner_is_accepted_without_poisoning",
            "test_v2s2_ac12_ac15_fm10_fm16_second_artifact_write_failure_leaves_no_new_leaf_and_retry_succeeds",
            "test_v2s2_ac12_fm16_existing_empty_output_leaf_is_accepted",
            "test_v2s2_fm16_preexisting_differing_expected_artifact_fails_output_collision_without_overwrite",
            "test_v2s2_fm16_preexisting_special_output_leaf_fails_output_boundary_invalid",
            "test_v2s2_fm16_output_link_or_reparse_leaf_fails_output_boundary_invalid",
            "test_v2s2_ac12_ac15_fm16_windows_output_ancestor_junction_without_isjunction_is_rejected",
            "test_v2s2_bl1_output_ancestor_link_components_rejected_without_external_writes",
            "test_v2s2_ac12_ac13_fm16_rollback_loser_must_not_delete_winner_artifacts",
            "test_v2s2_ac12_fm16_rollback_must_not_delete_other_live_writer_temp",
            "test_v2s2_ac12_ac13_fm16_rollback_adoption_race_requires_transactional_leaf_publication",
            "test_v2s2_ac12_ac13_fm16_live_exact_transaction_lock_blocks_peer_cli_until_release",
            "test_v2s2_ac12_ac13_fm16_exact_transaction_lock_orphan_or_foreign_bytes_fail_closed_and_preserved",
            "test_v2s2_ac12_ac13_fm16_sigkill_orphan_exact_transaction_lock_fails_closed",
        ),
        "V2S2-AC13": (
            "test_v2s2_ac12_ac13_fm16_concurrent_identical_writers_succeed_idempotently",
            "test_v2s2_ac13_unreadable_staged_file_maps_to_staging_file_read_failed",
            "test_verify_stage_usage_failures_are_closed_json_with_exit_2",
            "test_v2s2_ac03_ac13_fm01_fm12_staging_root_empty_or_whitespace_emits_catalog_error",
            "test_v2s2_ac10_ac11_ac13_fm12_stdout_bytes_contract_holds_on_success_and_failure",
            "test_verify_stage_exit_partition_baseline_path_invalid_input_invalid_and_output_collision",
            "test_v2s2_bl6_mixed_scalar_and_string_identifiers_fail_schema_without_internal_error",
            "test_v2s2_bl9_non_string_yaml_mapping_keys_fail_closed_schema_envelope",
            "test_v2s2_bl9_non_finite_yaml_mapping_keys_fail_schema_without_serialization_escape",
            "test_v2s2_bl9_non_finite_wrong_typed_values_fail_schema_without_serialization_escape",
            "test_v2s2_bl9_unhashable_container_values_fail_closed_schema_envelope_without_internal_escape",
            "test_v2s2_bl9_unhashable_probe_scalar_controls_fail_schema_without_internal_escape",
            "test_v2s2_bl9_complex_yaml_mapping_keys_fail_closed_yaml_envelope",
            "test_v2s2_bl9_unknown_string_mapping_key_control_remains_schema_invalid",
            "test_v2s2_bl9_deep_flow_sequence_depth_controls_and_extreme_nesting_fail_closed",
            "test_v2s2_ac12_ac13_fm16_rollback_loser_must_not_delete_winner_artifacts",
            "test_v2s2_ac12_ac13_fm16_rollback_adoption_race_requires_transactional_leaf_publication",
            "test_v2s2_ac12_ac13_fm16_live_exact_transaction_lock_blocks_peer_cli_until_release",
            "test_v2s2_ac12_ac13_fm16_exact_transaction_lock_orphan_or_foreign_bytes_fail_closed_and_preserved",
            "test_v2s2_ac12_ac13_fm16_sigkill_orphan_exact_transaction_lock_fails_closed",
            "test_v2s2_ac02_ac06_initial_malformed_registry_yaml_maps_to_baseline_registry_invalid",
            "test_v2s2_ac02_ac06_initial_nonutf8_registry_maps_to_baseline_registry_invalid",
            "test_v2s2_ac02_ac06_initial_wrong_typed_registry_maps_to_baseline_registry_invalid",
            "test_v2s2_ac06_ac07_fm10b_mid_run_registry_malformed_yaml_maps_to_baseline_changed_during_run",
            "test_v2s2_ac06_ac07_fm10b_mid_run_registry_nonutf8_maps_to_baseline_changed_during_run",
            "test_v2s2_ac06_bl11_first_pass_public_loader_failure_is_mapped_to_baseline_registry_invalid",
        ),
        "V2S2-AC14": (
            "test_v2s2_ac14_public_loader_and_typed_immutable_models_are_required",
            "test_v2s2_bl9_load_manifest_runs_same_strict_validation_as_verify_stage",
            "test_v2s2_bl9_load_manifest_rejects_descending_sequences_before_baseline",
            "test_v2s2_bl9_load_manifest_rejects_mixed_scalar_identifier_types_with_typed_schema_error",
            "test_v2s2_bl9_load_manifest_rejects_non_string_yaml_mapping_keys_with_typed_schema_error",
            "test_v2s2_bl9_load_manifest_rejects_non_finite_yaml_mapping_keys_with_json_compatible_typed_schema_error",
            "test_v2s2_bl9_load_manifest_rejects_non_finite_wrong_typed_values_with_json_compatible_typed_schema_error",
            "test_v2s2_bl9_load_manifest_rejects_unhashable_container_values_with_typed_schema_error",
            "test_v2s2_bl9_verify_stage_loader_boundary_maps_foreseeable_type_failures_to_schema_invalid_and_unexpected_to_internal70",
            "test_v2s2_bl9_load_manifest_rejects_complex_yaml_mapping_keys_with_typed_yaml_error",
            "test_v2s2_bl9_unknown_string_mapping_key_control_remains_schema_invalid",
            "test_v2s2_bl9_load_manifest_maps_extreme_flow_sequence_nesting_to_typed_limit_error",
            "test_v2s2_bl9_verify_stage_consumes_public_typed_manifest_loader",
        ),
        "V2S2-AC15": (
            "test_non_mutation_of_registry_domain_preservation_and_stage_on_failure",
            "test_non_mutation_on_success_and_output_boundary_location",
            "test_v2s2_ac13_unreadable_staged_file_maps_to_staging_file_read_failed",
            "test_v2s2_ac12_ac15_fm10_fm16_second_artifact_write_failure_leaves_no_new_leaf_and_retry_succeeds",
            "test_v2s2_fm02_external_symlink_target_is_rejected_before_read_bytes",
            "test_v2s2_ac03_fm02_windows_stage_root_junction_without_isjunction_is_rejected",
            "test_v2s2_ac03_fm02_windows_nested_junction_without_isjunction_is_rejected",
            "test_v2s2_ac12_ac15_fm16_windows_output_ancestor_junction_without_isjunction_is_rejected",
            "test_v2s2_bl7_snapshot_per_file_limit_rejects_before_read",
        ),
        "V2S2-AC16": (
            "test_staged_snapshot_module_import_and_network_boundary",
        ),
        "V2S2-AC17": (
            "test_changed_candidate_produces_fact_only_observed_difference",
            "test_no_change_real_ingest_candidate_produces_deterministic_no_difference_artifacts",
        ),
        "V2S2-AC18": (
            "test_verify_stage_help_surface_and_validate_status_compatibility_baseline",
            "test_verify_stage_stdout_determinism_and_validate_status_compatibility_after_run",
        ),
        "V2S2-FM01": (
            "test_staging_root_boundary_rejects_non_canonical_paths",
            "test_v2s2_ac03_ac13_fm01_fm12_staging_root_empty_or_whitespace_emits_catalog_error",
            "test_manifest_path_rules_reject_unsafe_and_case_colliding_paths",
            "test_staging_tree_exactness_rejects_unknown_missing_and_unneeded_entries",
            "test_v2s2_ac03_staging_path_invalid_unlisted_reserved_entry_emits_catalog_envelope",
            "test_v2s2_bl1_staging_parent_link_component_is_rejected_even_when_target_inside_repo",
        ),
        "V2S2-FM02": (
            "test_symlink_staging_entries_are_rejected_when_supported",
            "test_v2s2_ac03_fm02_windows_stage_root_junction_is_rejected",
            "test_v2s2_ac03_fm02_windows_nested_junction_entry_is_rejected",
            "test_v2s2_ac03_fm02_windows_stage_root_junction_without_isjunction_is_rejected",
            "test_v2s2_ac03_fm02_windows_nested_junction_without_isjunction_is_rejected",
            "test_v2s2_ac03_fm02_windows_is_windows_reparse_detects_real_junction_without_isjunction",
            "test_v2s2_fm02_dangling_symlink_listed_file_path_is_inventory_entry_type_invalid",
            "test_v2s2_fm02_external_symlink_target_is_rejected_before_read_bytes",
            "test_v2s2_fm02_posix_fifo_listed_file_is_rejected_before_read",
            "test_v2s2_bl1_staging_parent_link_component_is_rejected_even_when_target_inside_repo",
            "test_v2s2_bl1_output_ancestor_link_components_rejected_without_external_writes",
            "test_v2s2_bl2_staging_nested_directory_link_components_are_rejected",
        ),
        "V2S2-FM03": (
            "test_v2s2_fm03_duplicate_and_case_collision_codes_are_exact",
            "test_v2s2_bl6_component_id_casefold_collisions_are_duplicate_ids",
            "test_v2s2_bl8_duplicate_detail_assignment_is_closed_and_deterministic",
        ),
        "V2S2-FM04": (
            "test_manifest_invalidity_cases_fail_without_artifacts",
            "test_v2s2_ac05_staging_text_encoding_invalid_emits_exact_code",
            "test_v2s2_bl5_declaration_ref_binding_rejects_raw_bytes_mode",
            "test_v2s2_bl5_component_checksum_variant_constraints_are_enforced",
            "test_v2s2_bl5_component_checksum_null_candidate_requires_sha256_baseline",
        ),
        "V2S2-FM05": (
            "test_verify_stage_exit_partition_unknown_source_vs_hash_vs_binding_mismatch",
            "test_v2s2_b6_phase_order_registry_hash_mismatch_wins_over_unlisted_tree_defect",
        ),
        "V2S2-FM06": (
            "test_verify_stage_exit_partition_unknown_source_vs_hash_vs_binding_mismatch",
        ),
        "V2S2-FM07": (
            "test_two_pass_staging_input_mutation_detection_blocks_artifact_writes",
        ),
        "V2S2-FM08": (
            "test_two_pass_staging_input_mutation_detection_blocks_artifact_writes",
            "test_v2s2_ac04_staging_limit_exceeded_depth_emits_exact_code",
            "test_v2s2_bl7_directory_count_limit_is_enforced_at_inventory_phase",
            "test_v2s2_bl7_unlisted_extreme_depth_guard_avoids_recursion_and_internal_escape",
            "test_v2s2_bl7_snapshot_per_file_limit_rejects_before_read",
            "test_v2s2_bl7_snapshot_total_limit_rejects_before_read_of_offending_file",
            "test_v2s2_bl7_unlisted_total_limit_subject_is_deterministic_before_read",
        ),
        "V2S2-FM09": (
            "test_v2s2_fm09_timezone_locale_mtime_and_command_time_do_not_change_stdout_bytes",
        ),
        "V2S2-FM10": (
            "test_non_mutation_of_registry_domain_preservation_and_stage_on_failure",
            "test_non_mutation_on_success_and_output_boundary_location",
            "test_v2s2_ac13_unreadable_staged_file_maps_to_staging_file_read_failed",
            "test_v2s2_ac12_ac15_fm10_fm16_second_artifact_write_failure_leaves_no_new_leaf_and_retry_succeeds",
            "test_v2s2_fm02_external_symlink_target_is_rejected_before_read_bytes",
            "test_v2s2_bl7_snapshot_per_file_limit_rejects_before_read",
        ),
        "V2S2-FM10B": (
            "test_v2s2_ac07_fm10b_registry_mutation_between_baseline_snapshots_fails_closed",
            "test_v2s2_ac07_fm10b_declaration_mutation_between_baseline_snapshots_fails_closed",
            "test_v2s2_bl11_registry_mutation_between_validation_and_output_is_detected",
            "test_v2s2_bl11_second_pass_reruns_validator_and_detects_changed_validation_result",
            "test_v2s2_ac06_ac07_fm10b_mid_run_registry_malformed_yaml_maps_to_baseline_changed_during_run",
            "test_v2s2_ac06_ac07_fm10b_mid_run_registry_nonutf8_maps_to_baseline_changed_during_run",
        ),
        "V2S2-FM11": (
            "test_manifest_invalidity_cases_fail_without_artifacts",
            "test_v2s2_fm11_plain_scalar_with_ampersand_asterisk_and_bang_is_not_rejected_lexically",
            "test_v2s2_fm11_yaml_anchor_alias_merge_and_custom_tag_are_rejected",
            "test_v2s2_ac05_staging_text_encoding_invalid_emits_exact_code",
            "test_v2s2_ac08_null_source_components_normalize_to_empty_for_complete_projection",
            "test_v2s2_ac08_null_source_components_still_enforce_record_kind_projection_rule",
            "test_v2s2_ac08_component_projection_facts_treat_null_source_components_as_empty",
            "test_v2s2_ac08_null_source_components_component_binding_is_typed_content_binding_invalid",
            "test_v2s2_bl9_non_string_yaml_mapping_keys_fail_closed_schema_envelope",
            "test_v2s2_bl9_load_manifest_rejects_non_string_yaml_mapping_keys_with_typed_schema_error",
            "test_v2s2_bl9_non_finite_yaml_mapping_keys_fail_schema_without_serialization_escape",
            "test_v2s2_bl9_load_manifest_rejects_non_finite_yaml_mapping_keys_with_json_compatible_typed_schema_error",
            "test_v2s2_bl9_non_finite_wrong_typed_values_fail_schema_without_serialization_escape",
            "test_v2s2_bl9_load_manifest_rejects_non_finite_wrong_typed_values_with_json_compatible_typed_schema_error",
            "test_v2s2_bl9_unhashable_container_values_fail_closed_schema_envelope_without_internal_escape",
            "test_v2s2_bl9_load_manifest_rejects_unhashable_container_values_with_typed_schema_error",
            "test_v2s2_bl9_unhashable_probe_scalar_controls_fail_schema_without_internal_escape",
            "test_v2s2_bl9_complex_yaml_mapping_keys_fail_closed_yaml_envelope",
            "test_v2s2_bl9_load_manifest_rejects_complex_yaml_mapping_keys_with_typed_yaml_error",
            "test_v2s2_bl9_unknown_string_mapping_key_control_remains_schema_invalid",
            "test_v2s2_bl9_load_manifest_runs_same_strict_validation_as_verify_stage",
            "test_v2s2_bl9_load_manifest_rejects_descending_sequences_before_baseline",
            "test_v2s2_bl9_deep_flow_sequence_depth_controls_and_extreme_nesting_fail_closed",
            "test_v2s2_bl9_load_manifest_maps_extreme_flow_sequence_nesting_to_typed_limit_error",
            "test_v2s2_bl6_mixed_scalar_and_string_identifiers_fail_schema_without_internal_error",
        ),
        "V2S2-FM12": (
            "test_v2s2_ac10_ac11_ac13_fm12_stdout_bytes_contract_holds_on_success_and_failure",
            "test_verify_stage_exit_partition_baseline_path_invalid_input_invalid_and_output_collision",
            "test_verify_stage_exit_code_partition_never_uses_3",
            "test_v2s2_ac03_ac13_fm01_fm12_staging_root_empty_or_whitespace_emits_catalog_error",
            "test_v2s2_bl6_mixed_scalar_and_string_identifiers_fail_schema_without_internal_error",
            "test_v2s2_bl9_non_string_yaml_mapping_keys_fail_closed_schema_envelope",
            "test_v2s2_bl9_non_finite_yaml_mapping_keys_fail_schema_without_serialization_escape",
            "test_v2s2_bl9_non_finite_wrong_typed_values_fail_schema_without_serialization_escape",
            "test_v2s2_bl9_unhashable_container_values_fail_closed_schema_envelope_without_internal_escape",
            "test_v2s2_bl9_unhashable_probe_scalar_controls_fail_schema_without_internal_escape",
            "test_v2s2_bl9_complex_yaml_mapping_keys_fail_closed_yaml_envelope",
            "test_v2s2_bl9_unknown_string_mapping_key_control_remains_schema_invalid",
            "test_v2s2_bl9_deep_flow_sequence_depth_controls_and_extreme_nesting_fail_closed",
        ),
        "V2S2-FM13": (
            "test_no_change_real_ingest_candidate_produces_deterministic_no_difference_artifacts",
        ),
        "V2S2-FM14": (
            "test_changed_candidate_produces_fact_only_observed_difference",
            "test_v2s2_ac08_none_binding_on_candidate_declaration_uses_declaration_difference_kind",
        ),
        "V2S2-FM15": (
            "test_explicit_null_release_date_differs_from_omitted_required_key",
            "test_v2s2_bl6_row_required_keys_fail_closed_before_duplicate_and_path_scans",
        ),
        "V2S2-FM16": (
            "test_v2s2_ac12_ac13_fm16_concurrent_identical_writers_succeed_idempotently",
            "test_v2s2_ac12_fm16_leaf_mkdir_fileexists_race_recovers_without_internal70",
            "test_v2s2_ac12_fm16_mid_publication_identical_winner_is_accepted_without_poisoning",
            "test_v2s2_ac12_ac15_fm10_fm16_second_artifact_write_failure_leaves_no_new_leaf_and_retry_succeeds",
            "test_v2s2_ac12_fm16_existing_empty_output_leaf_is_accepted",
            "test_v2s2_fm16_preexisting_differing_expected_artifact_fails_output_collision_without_overwrite",
            "test_v2s2_fm16_preexisting_special_output_leaf_fails_output_boundary_invalid",
            "test_v2s2_fm16_output_link_or_reparse_leaf_fails_output_boundary_invalid",
            "test_v2s2_ac12_ac15_fm16_windows_output_ancestor_junction_without_isjunction_is_rejected",
            "test_v2s2_bl1_output_ancestor_link_components_rejected_without_external_writes",
            "test_v2s2_ac12_ac13_fm16_rollback_loser_must_not_delete_winner_artifacts",
            "test_v2s2_ac12_fm16_rollback_must_not_delete_other_live_writer_temp",
            "test_v2s2_ac12_ac13_fm16_rollback_adoption_race_requires_transactional_leaf_publication",
            "test_v2s2_ac12_ac13_fm16_live_exact_transaction_lock_blocks_peer_cli_until_release",
            "test_v2s2_ac12_ac13_fm16_exact_transaction_lock_orphan_or_foreign_bytes_fail_closed_and_preserved",
            "test_v2s2_ac12_ac13_fm16_sigkill_orphan_exact_transaction_lock_fails_closed",
        ),
    }

    assert set(coverage_map) == expected_ids
    test_files = [
        REPO_ROOT / "tests" / "sourceops" / "test_staged_snapshot_contract.py",
        REPO_ROOT / "tests" / "sourceops" / "test_staged_snapshot_cli.py",
        REPO_ROOT / "tests" / "sourceops" / "test_staged_snapshot_safety.py",
    ]
    all_named_tests: set[str] = set()
    for path in test_files:
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in parsed.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                all_named_tests.add(node.name)
    for authority_id, mapped_tests in coverage_map.items():
        assert mapped_tests, f"{authority_id} must map to at least one test"
        for test_name in mapped_tests:
            assert test_name in all_named_tests, f"{authority_id} maps to unknown test {test_name!r}"
