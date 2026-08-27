from __future__ import annotations

import ast
import concurrent.futures
import copy
import functools
import hashlib
import json
import os
import signal
import shutil
import stat
import subprocess
import sys
import textwrap
import threading
import time
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
FORBIDDEN_NETWORK_IMPORTS = {
    "socket",
    "http",
    "http.client",
    "urllib",
    "urllib.request",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "paramiko",
    "websockets",
}
FORBIDDEN_ARCHIVE_IMPORTS = {"tarfile", "zipfile", "gzip", "bz2", "lzma", "patoolib", "libarchive"}
FORBIDDEN_DOMAIN_IMPORT_PREFIXES = (
    "raptor.scorer",
    "raptor.eval",
    "raptor.packet",
    "raptor.census",
    "raptor.atlas",
    "raptor.ingest",
    "raptor.kb",
    "raptor.external",
)
PATH_SUBJECT_ERROR_CODES = {
    "BASELINE_REGISTRY_PATH_INVALID",
    "STAGING_ROOT_INVALID",
    "STAGING_MANIFEST_MISSING",
    "STAGING_MANIFEST_TYPE_INVALID",
    "STAGING_MANIFEST_READ_FAILED",
    "STAGING_MANIFEST_LIMIT_EXCEEDED",
    "STAGING_MANIFEST_ENCODING_INVALID",
    "STAGING_MANIFEST_YAML_INVALID",
    "STAGING_DUPLICATE_PATH",
    "STAGING_PATH_INVALID",
    "STAGING_ENTRY_TYPE_INVALID",
    "STAGING_TREE_MISMATCH",
    "STAGING_LIMIT_EXCEEDED",
    "STAGING_FILE_SIZE_MISMATCH",
    "STAGING_FILE_CHECKSUM_MISMATCH",
    "STAGING_TEXT_ENCODING_INVALID",
    "STAGING_FILE_READ_FAILED",
    "STAGING_INPUT_MUTATED",
    "OUTPUT_BOUNDARY_INVALID",
    "OUTPUT_COLLISION",
    "OUTPUT_WRITE_FAILED",
}
_NON_PATH_SUBJECT_PREFIXES = (
    "files[",
    "content_bindings[",
    "component_projection",
    "candidate.",
    "source_binding.",
    "manifest_content_hash",
    "hash_basis",
)


@functools.lru_cache(maxsize=1)
def _spec() -> dict[str, Any]:
    loaded = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail("V2-S2 spec must parse into a mapping")
    return loaded


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _canonical_manifest_hash(manifest: dict[str, Any]) -> str:
    basis = copy.deepcopy(manifest)
    basis.pop("manifest_content_hash", None)
    return _sha256_hex(_canonical_json_bytes(basis))


def _canonical_lf_checksum(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8")
    canonical = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return {
        "mode": "CANONICAL_LF_TEXT",
        "raw_byte_size": None,
        "raw_sha256": None,
        "canonical_lf_utf8_bytes": len(canonical),
        "canonical_lf_sha256": _sha256_hex(canonical),
    }


def _raw_checksum(raw: bytes) -> dict[str, Any]:
    return {
        "mode": "RAW_BYTES",
        "raw_byte_size": len(raw),
        "raw_sha256": _sha256_hex(raw),
        "canonical_lf_utf8_bytes": None,
        "canonical_lf_sha256": None,
    }


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return env


def _run_cli(*args: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=_cli_env(),
        timeout=timeout,
    )


def _run_verify_stage(
    staging_root_rel: str,
    *,
    registry_rel: str = CANONICAL_REGISTRY_REL,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run_cli("verify-stage", "--registry", registry_rel, "--staging-root", staging_root_rel, timeout=timeout)


def _spawn_verify_stage_process(
    staging_root_rel: str,
    *,
    registry_rel: str = CANONICAL_REGISTRY_REL,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "raptor.sourceops.cli",
            "verify-stage",
            "--registry",
            registry_rel,
            "--staging-root",
            staging_root_rel,
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_cli_env(),
    )


def _spawn_python_script_process(script: str, *args: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", script, *args],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_cli_env(),
    )


def _wait_for_path(path: Path, *, timeout_seconds: float, description: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    pytest.fail(f"timed out waiting for {description}: {path}")


def _collect_process_result(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float,
    description: str,
) -> subprocess.CompletedProcess[str]:
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _cleanup_process(process)
        pytest.fail(f"{description} did not exit within {timeout_seconds:.1f}s")
    return subprocess.CompletedProcess(
        args=process.args,
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
    )


def _cleanup_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.kill()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            return


def _parse_json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if not result.stdout.strip():
        pytest.fail(
            "verify-stage must emit one deterministic JSON object on stdout.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        pytest.fail("stdout payload must be a JSON object")
    return payload


def _assert_one_line_stdout_zero_stderr(result: subprocess.CompletedProcess[str]) -> None:
    assert result.stdout.endswith("\n"), "stdout must end with one LF"
    assert result.stdout.count("\n") == 1, "stdout must be exactly one JSON line"
    assert result.stderr == "", f"stderr must be empty, got {result.stderr!r}"


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


def _assert_exact_error_from_authority(report: dict[str, Any], *, expected_code: str, expected_exit: int) -> dict[str, Any]:
    error = report.get("error")
    assert isinstance(error, dict), f"error envelope must be a mapping, got {error!r}"
    required_keys = set(_spec()["error_contract"]["error_envelope_required_exact"])
    assert set(error) == required_keys
    authority = _error_catalog()[expected_code]
    assert expected_exit == authority["exit"]
    assert error["code"] == authority["code"] == expected_code
    assert error["type"] == authority["type"]
    assert error["phase"] == authority["phase"]
    assert error["message"] == authority["message"]
    return error


def _is_path_subject_error(error: dict[str, Any]) -> bool:
    code = error.get("code")
    subject = error.get("subject")
    if code not in PATH_SUBJECT_ERROR_CODES or not isinstance(subject, str) or not subject:
        return False
    if subject.startswith(_NON_PATH_SUBJECT_PREFIXES):
        return False
    if "/" in subject or "\\" in subject:
        return True
    return subject == "manifest.yaml"


def _assert_path_subject_forward_slash(error: dict[str, Any], *, expected: str | None = None) -> str:
    subject = error.get("subject")
    assert isinstance(subject, str) and subject.strip(), f"path subject must be a non-empty string, got {subject!r}"
    assert _is_path_subject_error(error), f"error subject must be classified as a path: {error!r}"
    if expected is not None:
        assert subject == expected
    assert "\\" not in subject, f"path subjects must use forward-slash canonical form, got {subject!r}"
    if expected is not None and "/" in expected:
        assert "/" in subject
    return subject


def _assert_no_backslash_for_path_subject(report: dict[str, Any]) -> None:
    error = report.get("error")
    if isinstance(error, dict) and _is_path_subject_error(error):
        subject = error.get("subject")
        assert isinstance(subject, str)
        assert "\\" not in subject, f"path subjects must never contain backslash: {subject!r}"


def _assert_exact_failure(
    result: subprocess.CompletedProcess[str],
    *,
    expected_code: str,
    expected_exit: int,
    expected_input_validity: str = "INVALID",
) -> dict[str, Any]:
    _assert_one_line_stdout_zero_stderr(result)
    assert result.returncode == expected_exit
    report = _parse_json_stdout(result)
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == expected_input_validity
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    _assert_exact_error_from_authority(report, expected_code=expected_code, expected_exit=expected_exit)
    return report


def _load_registry() -> dict[str, Any]:
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        pytest.fail("source_registry.yaml must parse into a mapping")
    return payload


def _source_record(payload: dict[str, Any], source_id: str) -> dict[str, Any]:
    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    for row in records:
        if isinstance(row, dict) and row.get("source_id") == source_id:
            return copy.deepcopy(row)
    pytest.fail(f"source_id missing: {source_id!r}")


def _base_manifest_and_files() -> tuple[dict[str, Any], dict[str, bytes]]:
    registry = _load_registry()
    source = _source_record(registry, "tsc-ingest-and-reference-declarations")
    decl_bytes = (REPO_ROOT / "configs" / "ingest" / "tsc.yaml").read_bytes()
    manifest = {
        "schema": _spec()["manifest_contract"]["schema_id"],
        "manifest_content_hash": "0" * 64,
        "hash_basis": _spec()["manifest_contract"]["hash_basis"],
        "observed_at": "2026-08-17T05:00:00Z",
        "source_binding": {
            "source_id": source["source_id"],
            "registry_content_hash": registry["registry_content_hash"],
            "declaration_refs": copy.deepcopy(source["declaration_refs"]),
        },
        "candidate": {
            "snapshot_id": "candidate-safety-base-001",
            "identity": {
                "display_name": source["display_name"],
                "record_kind": source["record_kind"],
                "owner": source["owner"],
                "authoritative_locator": source["authoritative_locator"],
            },
            "release": {
                "version_or_snapshot": source["release"]["version_or_snapshot"],
                "release_date": source["release"]["release_date"],
                "retrieved_at": source["release"]["retrieved_at"],
                "content_pin_status": source["release"]["content_pin_status"],
            },
            "licence": copy.deepcopy(source["licence"]),
            "acquisition": copy.deepcopy(source["acquisition"]),
        },
        "files": [
            {
                "file_id": "decl-tsc-yaml",
                "path": "candidate/ingest/tsc.yaml",
                "role": "CANDIDATE_DECLARATION",
                "media_type": "application/x-yaml",
                "checksum": _canonical_lf_checksum(decl_bytes),
                "component_ids": [],
            }
        ],
        "content_bindings": [
            {
                "binding_id": "bind-declaration",
                "baseline_kind": "DECLARATION_REF",
                "baseline_id": source["declaration_refs"][0]["path"],
                "candidate_file_id": "decl-tsc-yaml",
            }
        ],
        "component_projection": None,
    }
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    return manifest, {"candidate/ingest/tsc.yaml": decl_bytes}


@contextmanager
def _stage_case(prefix: str, manifest: dict[str, Any], files: dict[str, bytes]) -> Iterator[tuple[Path, str]]:
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
        (stage_root / "manifest.yaml").write_text(dumped, encoding="utf-8", newline="")
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


def _remove_output_leaf(manifest_hash: str) -> None:
    leaf = OUTPUT_PARENT / manifest_hash
    _remove_path(leaf)


def _artifact_abs_path(ref: dict[str, Any]) -> Path:
    path_value = ref.get("path")
    assert isinstance(path_value, str) and path_value.strip(), f"artifact path is invalid: {ref!r}"
    return REPO_ROOT / Path(path_value.replace("/", os.sep))


def _assert_artifact_payload_hash_and_bytes(path: Path, ref: dict[str, Any], *, prefix: str) -> str:
    ref_hash = ref.get("content_hash")
    assert isinstance(ref_hash, str) and ref_hash.strip(), f"artifact content_hash is invalid: {ref!r}"

    raw = path.read_bytes()
    assert b"\r" not in raw, "artifact bytes must not contain CR"
    assert raw.endswith(b"\n"), "artifact bytes must end with one LF"
    assert raw.count(b"\n") == 1, "artifact bytes must contain exactly one LF terminator"

    payload = json.loads(raw.decode("utf-8"))
    assert isinstance(payload, dict), f"artifact payload must be a JSON object: {path}"
    canonical_payload = _canonical_json_bytes(payload)
    assert raw == canonical_payload + b"\n", "artifact bytes must equal canonical JSON payload plus one LF"

    payload_hash = payload.get("artifact_content_hash")
    assert isinstance(payload_hash, str) and payload_hash.strip(), f"artifact_content_hash is invalid: {payload!r}"
    assert payload_hash == ref_hash

    basis = copy.deepcopy(payload)
    basis.pop("artifact_content_hash", None)
    assert _sha256_hex(_canonical_json_bytes(basis)) == payload_hash
    assert path.name == f"{prefix}-{payload_hash}.json"
    return payload_hash


def _assert_output_leaf_has_exact_artifacts(report: dict[str, Any], *, manifest_hash: str) -> tuple[Path, Path]:
    verification_ref = report.get("verification_artifact")
    diff_ref = report.get("diff_artifact")
    assert isinstance(verification_ref, dict), f"verification_artifact must be present: {report!r}"
    assert isinstance(diff_ref, dict), f"diff_artifact must be present: {report!r}"
    v_path = _artifact_abs_path(verification_ref)
    d_path = _artifact_abs_path(diff_ref)
    leaf = OUTPUT_PARENT / manifest_hash
    assert v_path.parent == leaf == d_path.parent
    assert v_path.is_file() and d_path.is_file()
    v_hash = _assert_artifact_payload_hash_and_bytes(v_path, verification_ref, prefix="v")
    d_hash = _assert_artifact_payload_hash_and_bytes(d_path, diff_ref, prefix="d")
    expected_names = sorted([f"v-{v_hash}.json", f"d-{d_hash}.json"])
    entries = list(leaf.iterdir())
    assert len(entries) == 2
    assert all(entry.is_file() for entry in entries)
    actual_names = sorted(entry.name for entry in entries)
    assert actual_names == expected_names
    return v_path, d_path


def _run_verify_stage_concurrently(
    staging_root_rel: str,
    *,
    worker_count: int,
    registry_rel: str = CANONICAL_REGISTRY_REL,
) -> list[subprocess.CompletedProcess[str]]:
    gate = threading.Barrier(worker_count + 1)

    def _invoke() -> subprocess.CompletedProcess[str]:
        gate.wait(timeout=60)
        return _run_verify_stage(staging_root_rel, registry_rel=registry_rel)

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(_invoke) for _ in range(worker_count)]
        gate.wait(timeout=60)
        return [future.result(timeout=300) for future in futures]


_ROLLBACK_OWNER_PROCESS_SCRIPT = textwrap.dedent(
    """
    import json
    import sys
    import time
    from pathlib import Path

    from raptor.sourceops import staged_snapshot as staged_mod

    registry_rel, staging_root_rel, first_ready_marker, release_marker = sys.argv[1:5]
    first_ready = Path(first_ready_marker)
    release = Path(release_marker)
    real_write_atomic = staged_mod._write_atomic_json
    write_calls = {"value": 0}

    def _patched_write(path, payload):
        write_calls["value"] += 1
        if write_calls["value"] == 1:
            outcome = real_write_atomic(path, payload)
            first_ready.write_text("v-ready", encoding="utf-8")
            while not release.exists():
                time.sleep(0.01)
            return outcome
        if write_calls["value"] == 2:
            raise OSError("synthetic second artifact failure for real-process rollback probe")
        return real_write_atomic(path, payload)

    staged_mod._write_atomic_json = _patched_write
    outcome = staged_mod.verify_stage(registry_rel, staging_root_rel)
    print(json.dumps(outcome.report.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    raise SystemExit(outcome.exit_code)
    """
).strip()


_LOCK_HOLDER_PROCESS_SCRIPT = textwrap.dedent(
    """
    import json
    import sys
    import time
    from pathlib import Path

    from raptor.sourceops import staged_snapshot as staged_mod

    registry_rel, staging_root_rel, lock_ready_marker, release_marker = sys.argv[1:5]
    lock_ready = Path(lock_ready_marker)
    release = Path(release_marker)
    real_create_lock = staged_mod._create_transaction_lock_file
    lock_announced = {"value": False}

    def _patched_create_lock(lock_path):
        created = real_create_lock(lock_path)
        if created and not lock_announced["value"]:
            lock_announced["value"] = True
            lock_ready.write_text("lock-held", encoding="utf-8")
            while not release.exists():
                time.sleep(0.01)
        return created

    staged_mod._create_transaction_lock_file = _patched_create_lock
    outcome = staged_mod.verify_stage(registry_rel, staging_root_rel)
    print(json.dumps(outcome.report.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    raise SystemExit(outcome.exit_code)
    """
).strip()


_ORPHAN_LOCK_OWNER_PROCESS_SCRIPT = textwrap.dedent(
    """
    import sys
    import time
    from pathlib import Path

    from raptor.sourceops import staged_snapshot as staged_mod

    registry_rel, staging_root_rel, lock_ready_marker = sys.argv[1:4]
    lock_ready = Path(lock_ready_marker)
    real_create_lock = staged_mod._create_transaction_lock_file

    def _patched_create_lock(lock_path):
        created = real_create_lock(lock_path)
        if created:
            lock_ready.write_text("lock-held", encoding="utf-8")
            while True:
                time.sleep(0.1)
        return created

    staged_mod._create_transaction_lock_file = _patched_create_lock
    staged_mod.verify_stage(registry_rel, staging_root_rel)
    """
).strip()


def _write_reserved_unlisted_con_entry(stage_root: Path, *, payload: bytes) -> str:
    rel_path = "candidate/con"
    candidate_dir = stage_root / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    entry_path = candidate_dir / "con"
    if os.name != "nt":
        entry_path.write_bytes(payload)
        assert entry_path.exists(), "POSIX reserved-path probe must materialize candidate/con"
        return rel_path

    try:
        entry_path.write_bytes(payload)
    except OSError:
        pass
    if entry_path.exists():
        return rel_path

    extended_path = "\\\\?\\" + str(entry_path.resolve())
    with open(extended_path, "wb") as handle:
        handle.write(payload)
    names = {path.name.casefold() for path in candidate_dir.iterdir()}
    assert "con" in names, "Windows reserved-path probe must materialize candidate/con"
    return rel_path


def _hash_file(path: Path) -> str:
    return _sha256_hex(path.read_bytes())


def _write_sparse_file(path: Path, *, size: int) -> None:
    with path.open("wb") as handle:
        handle.truncate(size)


def _preservation_paths() -> list[Path]:
    rels = _spec()["preservation_and_cross_lane_boundaries"]["frozen_evidence"]["required_zero_diff"]
    return [REPO_ROOT / Path(rel) for rel in rels]


def test_staging_root_boundary_rejects_non_canonical_paths() -> None:
    invalid_roots = [
        ".raptor/sourceops/staging",
        ".raptor/sourceops/staging/../escape",
        ".raptor/sourceops/staging/demo/child",
        ".raptor/sourceops/staging/.hidden",
        "C:/outside/stage",
        r"\\server\share\stage",
        "file:///outside/stage",
        ".raptor/sourceops/staging/CON",
    ]
    for root in invalid_roots:
        result = _run_verify_stage(root)
        _assert_one_line_stdout_zero_stderr(result)
        report = _parse_json_stdout(result)
        assert result.returncode == 2
        assert _error_code(report) == "STAGING_ROOT_INVALID"
        assert report["run_status"] == "FAILED"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None


def test_manifest_path_rules_reject_unsafe_and_case_colliding_paths() -> None:
    base_manifest, files = _base_manifest_and_files()
    unsafe_rows = [
        ("casefold-collision", "candidate/FILE.txt", "candidate/file.txt", "STAGING_DUPLICATE_PATH"),
        ("backslash", "candidate\\bad.txt", None, "STAGING_MANIFEST_SCHEMA_INVALID"),
        ("parent-traversal", "../escape.txt", None, "STAGING_MANIFEST_SCHEMA_INVALID"),
        ("drive-qualified", "C:/escape.txt", None, "STAGING_MANIFEST_SCHEMA_INVALID"),
        ("colon-segment", "candidate/sub:bad.txt", None, "STAGING_MANIFEST_SCHEMA_INVALID"),
        ("device-name", "candidate/CON", None, "STAGING_MANIFEST_SCHEMA_INVALID"),
        ("trailing-space", "candidate/bad .txt", None, "STAGING_MANIFEST_SCHEMA_INVALID"),
    ]

    for case_id, first_path, second_path, expected_code in unsafe_rows:
        manifest = copy.deepcopy(base_manifest)
        manifest["files"] = copy.deepcopy(manifest["files"])
        manifest["content_bindings"] = copy.deepcopy(manifest["content_bindings"])
        manifest["files"].append(
            {
                "file_id": "extra-path-probe-a",
                "path": first_path,
                "role": "AUXILIARY_METADATA",
                "media_type": "application/octet-stream",
                "checksum": _raw_checksum(b"abc"),
                "component_ids": [],
            }
        )
        manifest["content_bindings"].append(
            {
                "binding_id": "bind-extra-path-probe-a",
                "baseline_kind": "NONE",
                "baseline_id": None,
                "candidate_file_id": "extra-path-probe-a",
            }
        )
        stage_files = copy.deepcopy(files)
        if "/" in first_path and "\\" not in first_path and ":" not in first_path and ".." not in first_path and "CON" not in first_path:
            stage_files[first_path] = b"abc"
        if second_path is not None:
            manifest["files"].append(
                {
                    "file_id": "extra-path-probe-b",
                    "path": second_path,
                    "role": "AUXILIARY_METADATA",
                    "media_type": "application/octet-stream",
                    "checksum": _raw_checksum(b"def"),
                    "component_ids": [],
                }
            )
            manifest["content_bindings"].append(
                {
                    "binding_id": "bind-extra-path-probe-b",
                    "baseline_kind": "NONE",
                    "baseline_id": None,
                    "candidate_file_id": "extra-path-probe-b",
                }
            )
            if "/" in second_path and "\\" not in second_path and ":" not in second_path and ".." not in second_path and "CON" not in second_path:
                stage_files[second_path] = b"def"
        manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
        with _stage_case(f"s2-path-{case_id}", manifest, stage_files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_one_line_stdout_zero_stderr(result)
        report = _parse_json_stdout(result)
        assert result.returncode == 2
        assert _error_code(report) == expected_code


def test_staging_tree_exactness_rejects_unknown_missing_and_unneeded_entries() -> None:
    manifest, files = _base_manifest_and_files()

    with _stage_case("s2-tree-missing", manifest, {}) as (_, staging_rel):
        missing = _run_verify_stage(staging_rel)
    missing_report = _assert_exact_failure(missing, expected_code="STAGING_TREE_MISMATCH", expected_exit=2)
    missing_error = missing_report["error"]
    assert isinstance(missing_error, dict)
    _assert_path_subject_forward_slash(missing_error, expected="candidate/ingest/tsc.yaml")
    _assert_no_backslash_for_path_subject(missing_report)

    extra_files = copy.deepcopy(files)
    unknown_file_rel = "candidate/ingest/unknown/deep/extra.txt"
    extra_files[unknown_file_rel] = b"unlisted"
    with _stage_case("s2-tree-extra", manifest, extra_files) as (_, staging_rel):
        extra = _run_verify_stage(staging_rel)
    extra_report = _assert_exact_failure(extra, expected_code="STAGING_TREE_MISMATCH", expected_exit=2)
    extra_error = extra_report["error"]
    assert isinstance(extra_error, dict)
    _assert_path_subject_forward_slash(extra_error, expected=unknown_file_rel)
    _assert_no_backslash_for_path_subject(extra_report)

    with _stage_case("s2-tree-listed-file-dir", manifest, files) as (stage_root, staging_rel):
        listed_file = stage_root / "candidate" / "ingest" / "tsc.yaml"
        listed_file.unlink(missing_ok=False)
        listed_file.mkdir(parents=False, exist_ok=False)
        (listed_file / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        listed_as_dir = _run_verify_stage(staging_rel)
    listed_as_dir_report = _assert_exact_failure(listed_as_dir, expected_code="STAGING_TREE_MISMATCH", expected_exit=2)
    listed_as_dir_error = listed_as_dir_report["error"]
    assert isinstance(listed_as_dir_error, dict)
    _assert_path_subject_forward_slash(listed_as_dir_error, expected="candidate/ingest/tsc.yaml")
    _assert_no_backslash_for_path_subject(listed_as_dir_report)

    with _stage_case("s2-tree-empty-dir", manifest, files) as (stage_root, staging_rel):
        empty_rel = "candidate/ingest/empty/deep"
        (stage_root / Path(empty_rel.replace("/", os.sep))).mkdir(parents=True, exist_ok=True)
        empty_dir = _run_verify_stage(staging_rel)
    empty_dir_report = _assert_exact_failure(empty_dir, expected_code="STAGING_TREE_MISMATCH", expected_exit=2)
    empty_dir_error = empty_dir_report["error"]
    assert isinstance(empty_dir_error, dict)
    _assert_path_subject_forward_slash(empty_dir_error, expected=empty_rel)
    _assert_no_backslash_for_path_subject(empty_dir_report)


def test_symlink_staging_entries_are_rejected_when_supported() -> None:
    manifest, files = _base_manifest_and_files()
    with _stage_case("s2-symlink", manifest, files) as (stage_root, staging_rel):
        target = REPO_ROOT / "configs" / "ingest" / "tsc.yaml"
        symlink_path = stage_root / "candidate" / "ingest" / "tsc.yaml"
        try:
            symlink_path.unlink(missing_ok=True)
            os.symlink(target, symlink_path)
        except (AttributeError, NotImplementedError, OSError) as exc:
            if os.name == "nt":
                pytest.skip(f"symlink creation not available in this Windows environment: {exc!r}")
            pytest.fail(f"symlink creation unexpectedly unavailable on non-Windows platform: {exc!r}")
        result = _run_verify_stage(staging_rel)
    report = _assert_exact_failure(result, expected_code="STAGING_ENTRY_TYPE_INVALID", expected_exit=2)
    error = report["error"]
    assert isinstance(error, dict)
    _assert_path_subject_forward_slash(error, expected="candidate/ingest/tsc.yaml")
    _assert_no_backslash_for_path_subject(report)


def test_v2s2_fm02_dangling_symlink_listed_file_path_is_inventory_entry_type_invalid() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case("s2-fm02-dangling-symlink", manifest, files) as (stage_root, staging_rel):
            symlink_path = stage_root / "candidate" / "ingest" / "tsc.yaml"
            dangling_target = stage_root / "candidate" / "ingest" / "missing-target.yaml"
            symlink_path.unlink(missing_ok=True)
            try:
                os.symlink(dangling_target, symlink_path)
            except (AttributeError, NotImplementedError, OSError) as exc:
                if os.name == "nt":
                    pytest.skip(f"dangling symlink probe unavailable in this Windows environment: {exc!r}")
                pytest.fail(f"dangling symlink probe unexpectedly unavailable on non-Windows platform: {exc!r}")
            result = _run_verify_stage(staging_rel)
        report = _assert_exact_failure(result, expected_code="STAGING_ENTRY_TYPE_INVALID", expected_exit=2)
        assert _error_code(report) != "INTERNAL_ERROR"
        assert "FileNotFoundError" not in result.stdout
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_fm02_external_symlink_target_is_rejected_before_read_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    external_target = REPO_ROOT.parent / f"raptor-s2-fm02-external-target-{uuid.uuid4().hex[:10]}.bin"
    external_target.write_bytes(b"external-target-bytes-must-never-be-read")
    try:
        with _stage_case("s2-fm02-external-symlink", manifest, files) as (stage_root, staging_rel):
            symlink_path = stage_root / "candidate" / "ingest" / "tsc.yaml"
            symlink_path.unlink(missing_ok=True)
            try:
                os.symlink(external_target, symlink_path)
            except (AttributeError, NotImplementedError, OSError) as exc:
                if os.name == "nt":
                    pytest.skip(f"symlink probe unavailable in this Windows environment: {exc!r}")
                pytest.fail(f"symlink probe unexpectedly unavailable on non-Windows platform: {exc!r}")
            read_calls = {"symlink_path": 0, "external_path": 0}
            original_read_bytes = Path.read_bytes

            def _tracking_read_bytes(self: Path) -> bytes:
                if self == symlink_path:
                    read_calls["symlink_path"] += 1
                if self == external_target:
                    read_calls["external_path"] += 1
                return original_read_bytes(self)

            monkeypatch.setattr(Path, "read_bytes", _tracking_read_bytes, raising=True)
            code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert code == 2
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "INVALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        _assert_exact_error_from_authority(report, expected_code="STAGING_ENTRY_TYPE_INVALID", expected_exit=2)
        assert read_calls["symlink_path"] == 0
        assert read_calls["external_path"] == 0
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        external_target.unlink(missing_ok=True)
        _remove_output_leaf(manifest_hash)


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO probe for V2S2-FM02")
def test_v2s2_fm02_posix_fifo_listed_file_is_rejected_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is unavailable on this platform")

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    with _stage_case("s2-fm02-posix-fifo", manifest, files) as (stage_root, _):
        fifo_path = stage_root / "candidate" / "ingest" / "tsc.yaml"
        fifo_path.unlink()
        try:
            os.mkfifo(fifo_path)
        except OSError as exc:
            pytest.skip(f"mkfifo unsupported for this workspace/filesystem: {exc!r}")
        read_calls = {"fifo": 0}
        original_read_bytes = Path.read_bytes

        def _tracking_read_bytes(self: Path) -> bytes:
            if self == fifo_path:
                read_calls["fifo"] += 1
                raise AssertionError("listed FIFO must not be read before entry-type rejection")
            return original_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", _tracking_read_bytes, raising=True)
        with pytest.raises(staged_mod.StagingEntryTypeError) as excinfo:
            staged_mod._snapshot_stage_tree(stage_root)
    error = excinfo.value
    assert error.code == "STAGING_ENTRY_TYPE_INVALID"
    assert error.phase == "INVENTORY"
    assert read_calls["fifo"] == 0


def test_two_pass_staging_input_mutation_detection_blocks_artifact_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    large_raw = (b"x" * (8 * 1024 * 1024)) + b"\n"
    manifest = copy.deepcopy(manifest)
    manifest["files"].append(
        {
            "file_id": "mutation-target",
            "path": "candidate/mutation/target.bin",
            "role": "AUXILIARY_METADATA",
            "media_type": "application/octet-stream",
            "checksum": _raw_checksum(large_raw),
            "component_ids": [],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "bind-mutation-target",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "mutation-target",
        }
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files = copy.deepcopy(files)
    files["candidate/mutation/target.bin"] = large_raw
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)

    try:
        with _stage_case("s2-mutate", manifest, files) as (stage_root, staging_rel):
            target = stage_root / "candidate" / "mutation" / "target.bin"
            mutated = {"value": False}
            real_build_diff = staged_mod._build_diff_artifact

            def _mutating_diff(*args: Any, **kwargs: Any) -> dict[str, Any]:
                if not mutated["value"]:
                    current = target.read_bytes()
                    replacement = b"?" if current[:1] != b"?" else b"!"
                    target.write_bytes(replacement + current[1:])
                    mutated["value"] = True
                return real_build_diff(*args, **kwargs)

            monkeypatch.setattr(staged_mod, "_build_diff_artifact", _mutating_diff, raising=True)
            code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert code == 2
        assert _error_code(report) == "STAGING_INPUT_MUTATED"
        _assert_exact_error_from_authority(report, expected_code="STAGING_INPUT_MUTATED", expected_exit=2)
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        assert not (OUTPUT_PARENT / manifest_hash).exists(), "failed mutation run must not write artifact files"
    finally:
        _remove_output_leaf(manifest_hash)


def test_non_mutation_of_registry_domain_preservation_and_stage_on_failure() -> None:
    manifest, files = _base_manifest_and_files()
    invalid = copy.deepcopy(manifest)
    invalid["manifest_content_hash"] = "0" * 64
    registry_before = _hash_file(REGISTRY_PATH)
    declaration_path = REPO_ROOT / "configs" / "ingest" / "tsc.yaml"
    declaration_before = _hash_file(declaration_path)
    preservation_before = {path: _hash_file(path) for path in _preservation_paths()}
    with _stage_case("s2-nonmut-fail", invalid, files) as (stage_root, staging_rel):
        stage_file = stage_root / "candidate" / "ingest" / "tsc.yaml"
        stage_before = _hash_file(stage_file)
        result = _run_verify_stage(staging_rel)
        stage_after = _hash_file(stage_file)
    _assert_one_line_stdout_zero_stderr(result)
    assert stage_before == stage_after, "verify-stage must not mutate staged input on failure"
    assert _hash_file(REGISTRY_PATH) == registry_before, "registry must remain byte-identical"
    assert _hash_file(declaration_path) == declaration_before, "declaration must remain byte-identical"
    for path, before_hash in preservation_before.items():
        assert _hash_file(path) == before_hash, f"preservation path mutated: {path}"


def test_non_mutation_on_success_and_output_boundary_location() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    registry_before = _hash_file(REGISTRY_PATH)
    declaration_path = REPO_ROOT / "configs" / "ingest" / "tsc.yaml"
    declaration_before = _hash_file(declaration_path)
    preservation_before = {path: _hash_file(path) for path in _preservation_paths()}
    try:
        with _stage_case("s2-nonmut-success", manifest, files) as (stage_root, staging_rel):
            stage_file = stage_root / "candidate" / "ingest" / "tsc.yaml"
            stage_before = _hash_file(stage_file)
            result = _run_verify_stage(staging_rel)
            stage_after = _hash_file(stage_file)
            stage_root_abs = stage_root.resolve()
        _assert_one_line_stdout_zero_stderr(result)
        assert result.returncode == 0, result.stdout
        report = _parse_json_stdout(result)
        verification = report["verification_artifact"]
        diff = report["diff_artifact"]
        assert isinstance(verification, dict) and isinstance(diff, dict)
        v_path = REPO_ROOT / Path(str(verification["path"]).replace("/", os.sep))
        d_path = REPO_ROOT / Path(str(diff["path"]).replace("/", os.sep))
        assert v_path.is_file() and d_path.is_file()
        assert OUTPUT_PARENT in v_path.parents and OUTPUT_PARENT in d_path.parents
        assert stage_root_abs not in v_path.parents and stage_root_abs not in d_path.parents
        assert stage_before == stage_after, "verify-stage must not mutate staged input on success"
    finally:
        _remove_output_leaf(manifest_hash)
    assert _hash_file(REGISTRY_PATH) == registry_before, "registry must remain byte-identical"
    assert _hash_file(declaration_path) == declaration_before, "declaration must remain byte-identical"
    for path, before_hash in preservation_before.items():
        assert _hash_file(path) == before_hash, f"preservation path mutated: {path}"


def test_output_collision_and_link_boundaries_fail_closed() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    expected_subject = f".raptor/sourceops/generated/staged-snapshots/{manifest_hash}"
    _remove_output_leaf(manifest_hash)
    leaf.mkdir(parents=True, exist_ok=True)
    (leaf / "unexpected.extra").write_text("collision", encoding="utf-8")
    try:
        with _stage_case("s2-collision", manifest, files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_one_line_stdout_zero_stderr(result)
        report = _parse_json_stdout(result)
        assert result.returncode == 7
        assert _error_code(report) == "OUTPUT_COLLISION"
        error = _assert_exact_error_from_authority(report, expected_code="OUTPUT_COLLISION", expected_exit=7)
        _assert_path_subject_forward_slash(error, expected=expected_subject)
        _assert_no_backslash_for_path_subject(report)
        assert (leaf / "unexpected.extra").read_text(encoding="utf-8") == "collision"
    finally:
        _remove_output_leaf(manifest_hash)


def test_staged_snapshot_module_import_and_network_boundary() -> None:
    module_path = REPO_ROOT / "src" / "raptor" / "sourceops" / "staged_snapshot.py"
    assert module_path.exists(), f"missing staged snapshot implementation module: {module_path}"
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                top = name.split(".")[0]
                if name in FORBIDDEN_NETWORK_IMPORTS or top in FORBIDDEN_NETWORK_IMPORTS:
                    offenders.append(f"{module_path.name}:{node.lineno}:forbidden-network-import:{name}")
                if name in FORBIDDEN_ARCHIVE_IMPORTS or top in FORBIDDEN_ARCHIVE_IMPORTS:
                    offenders.append(f"{module_path.name}:{node.lineno}:forbidden-archive-import:{name}")
                if any(name.startswith(prefix) for prefix in FORBIDDEN_DOMAIN_IMPORT_PREFIXES):
                    offenders.append(f"{module_path.name}:{node.lineno}:forbidden-domain-import:{name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top = module.split(".")[0]
            if module in FORBIDDEN_NETWORK_IMPORTS or top in FORBIDDEN_NETWORK_IMPORTS:
                offenders.append(f"{module_path.name}:{node.lineno}:forbidden-network-import:{module}")
            if module in FORBIDDEN_ARCHIVE_IMPORTS or top in FORBIDDEN_ARCHIVE_IMPORTS:
                offenders.append(f"{module_path.name}:{node.lineno}:forbidden-archive-import:{module}")
            if any(module.startswith(prefix) for prefix in FORBIDDEN_DOMAIN_IMPORT_PREFIXES):
                offenders.append(f"{module_path.name}:{node.lineno}:forbidden-domain-import:{module}")
    assert not offenders, "staged snapshot module violates offline/network/domain dependency boundaries:\n" + "\n".join(offenders)


def test_output_artifacts_not_written_on_manifest_read_failures() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"s2-bad-manifest-{uuid.uuid4().hex[:10]}"
    stage_root = STAGING_PARENT / stage_name
    stage_root.mkdir(parents=False, exist_ok=False)
    try:
        for rel, raw in files.items():
            path = stage_root / Path(rel.replace("/", os.sep))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (stage_root / "manifest.yaml").write_bytes(b"\xff\xfe\xfd")
        result = _run_verify_stage(f".raptor/sourceops/staging/{stage_name}")
    finally:
        _remove_path(stage_root)
    _assert_one_line_stdout_zero_stderr(result)
    report = _parse_json_stdout(result)
    assert result.returncode == 2
    assert _error_code(report) == "STAGING_MANIFEST_ENCODING_INVALID"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    assert not (OUTPUT_PARENT / manifest_hash).exists(), "failed manifest read must not create output leaf"


def _create_windows_junction(link_path: Path, target_path: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            "failed to create Windows directory junction for FM02 probe; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


def _remove_windows_junction(link_path: Path) -> None:
    if not link_path.exists():
        return
    try:
        os.rmdir(link_path)
    except OSError as exc:
        pytest.fail(f"failed to remove Windows junction at {link_path}: {exc!r}")


def _simulate_missing_windows_isjunction(monkeypatch: pytest.MonkeyPatch, staged_mod: Any) -> None:
    monkeypatch.delattr(staged_mod.os.path, "isjunction", raising=False)
    assert not hasattr(staged_mod.os.path, "isjunction")


def _track_read_bytes_under(monkeypatch: pytest.MonkeyPatch, root: Path) -> dict[str, int]:
    read_calls = {"under_root": 0}
    original_read_bytes = Path.read_bytes
    resolved_root = root.resolve(strict=False)

    def _tracking_read_bytes(self: Path) -> bytes:
        try:
            resolved = self.resolve(strict=False)
        except OSError:
            resolved = self
        if resolved == resolved_root or resolved.is_relative_to(resolved_root):
            read_calls["under_root"] += 1
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _tracking_read_bytes, raising=True)
    return read_calls


@contextmanager
def _swap_directory_with_link(link_path: Path, target_path: Path) -> Iterator[None]:
    backup_path: Path | None = None
    if link_path.exists() or link_path.is_symlink():
        backup_path = link_path.with_name(f"{link_path.name}-bak-{uuid.uuid4().hex[:10]}")
        link_path.rename(backup_path)
    link_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            _create_windows_junction(link_path, target_path)
            assert not link_path.is_symlink(), "Windows junction probe expects a reparse point, not a symlink"
        else:
            link_path.symlink_to(target_path, target_is_directory=True)
        yield
    finally:
        if os.name == "nt":
            _remove_windows_junction(link_path)
        else:
            _remove_path(link_path)
        if backup_path is not None and (backup_path.exists() or backup_path.is_symlink()):
            backup_path.rename(link_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific junction probe for V2S2-FM02")
def test_v2s2_ac03_fm02_windows_stage_root_junction_is_rejected() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"s2-junction-root-{uuid.uuid4().hex[:10]}"
    stage_rel = f".raptor/sourceops/staging/{stage_name}"
    stage_link = STAGING_PARENT / stage_name
    external_target = REPO_ROOT.parent / f"raptor-s2-junction-root-target-{uuid.uuid4().hex[:10]}"
    try:
        external_target.mkdir(parents=True, exist_ok=False)
        for rel_path, raw in files.items():
            candidate_path = external_target / Path(rel_path.replace("/", os.sep))
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_bytes(raw)
        (external_target / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="")
        _create_windows_junction(stage_link, external_target)
        assert not stage_link.is_symlink(), "junction must be detectable even when Path.is_symlink() is false"
        result = _run_verify_stage(stage_rel)
        _assert_one_line_stdout_zero_stderr(result)
        report = _parse_json_stdout(result)
        assert result.returncode == 2
        assert _error_code(report) == "STAGING_ROOT_INVALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_windows_junction(stage_link)
        _remove_path(external_target)
        _remove_output_leaf(manifest_hash)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific junction probe for V2S2-FM02")
def test_v2s2_ac03_fm02_windows_nested_junction_entry_is_rejected() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    external_target = REPO_ROOT.parent / f"raptor-s2-junction-nested-target-{uuid.uuid4().hex[:10]}"
    try:
        with _stage_case("s2-junction-nested", manifest, files) as (stage_root, staging_rel):
            (external_target / "tsc.yaml").parent.mkdir(parents=True, exist_ok=False)
            (external_target / "tsc.yaml").write_bytes(files["candidate/ingest/tsc.yaml"])
            candidate_dir = stage_root / "candidate" / "ingest"
            shutil.rmtree(candidate_dir, ignore_errors=False)
            _create_windows_junction(candidate_dir, external_target)
            assert not candidate_dir.is_symlink(), "junction must be detectable even when Path.is_symlink() is false"
            try:
                result = _run_verify_stage(staging_rel)
            finally:
                _remove_windows_junction(candidate_dir)
        report = _assert_exact_failure(result, expected_code="STAGING_ENTRY_TYPE_INVALID", expected_exit=2)
        error = report["error"]
        assert isinstance(error, dict)
        _assert_path_subject_forward_slash(error, expected="candidate/ingest")
        _assert_no_backslash_for_path_subject(report)
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_path(external_target)
        _remove_output_leaf(manifest_hash)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific junction probe for V2S2-FM02")
@pytest.mark.parametrize("target_scope", ["in_repo", "outside_repo"], ids=["target-in-repo", "target-outside-repo"])
def test_v2s2_ac03_fm02_windows_stage_root_junction_without_isjunction_is_rejected(
    target_scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"s2-junction-root-no-isjunction-{uuid.uuid4().hex[:10]}"
    stage_rel = f".raptor/sourceops/staging/{stage_name}"
    stage_link = STAGING_PARENT / stage_name
    target_root = (
        REPO_ROOT / ".raptor" / "sourceops" / f"s2-junction-root-target-inside-{uuid.uuid4().hex[:10]}"
        if target_scope == "in_repo"
        else REPO_ROOT.parent / f"raptor-s2-junction-root-target-outside-{uuid.uuid4().hex[:10]}"
    )
    try:
        target_root.mkdir(parents=True, exist_ok=False)
        for rel_path, raw in files.items():
            candidate_path = target_root / Path(rel_path.replace("/", os.sep))
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_bytes(raw)
        (target_root / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="")
        _create_windows_junction(stage_link, target_root)
        assert not stage_link.is_symlink(), "junction must be detectable even when Path.is_symlink() is false"
        read_calls = _track_read_bytes_under(monkeypatch, target_root)
        _simulate_missing_windows_isjunction(monkeypatch, staged_mod)
        code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, stage_rel)
        assert code == 2
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "INVALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        _assert_exact_error_from_authority(report, expected_code="STAGING_ROOT_INVALID", expected_exit=2)
        assert read_calls["under_root"] == 0
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_windows_junction(stage_link)
        _remove_path(target_root)
        _remove_output_leaf(manifest_hash)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific junction probe for V2S2-FM02")
@pytest.mark.parametrize("target_scope", ["in_repo", "outside_repo"], ids=["target-in-repo", "target-outside-repo"])
def test_v2s2_ac03_fm02_windows_nested_junction_without_isjunction_is_rejected(
    target_scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    target_root = (
        REPO_ROOT / ".raptor" / "sourceops" / f"s2-junction-nested-target-inside-{uuid.uuid4().hex[:10]}"
        if target_scope == "in_repo"
        else REPO_ROOT.parent / f"raptor-s2-junction-nested-target-outside-{uuid.uuid4().hex[:10]}"
    )
    try:
        with _stage_case("s2-junction-nested-no-isjunction", manifest, files) as (stage_root, staging_rel):
            (target_root / "ingest").mkdir(parents=True, exist_ok=False)
            (target_root / "ingest" / "tsc.yaml").write_bytes(files["candidate/ingest/tsc.yaml"])
            candidate_dir = stage_root / "candidate"
            shutil.rmtree(candidate_dir, ignore_errors=False)
            _create_windows_junction(candidate_dir, target_root)
            assert not candidate_dir.is_symlink(), "junction must be detectable even when Path.is_symlink() is false"
            read_calls = _track_read_bytes_under(monkeypatch, target_root)
            _simulate_missing_windows_isjunction(monkeypatch, staged_mod)
            try:
                code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
            finally:
                _remove_windows_junction(candidate_dir)
        assert code == 2
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "INVALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        _assert_exact_error_from_authority(report, expected_code="STAGING_ENTRY_TYPE_INVALID", expected_exit=2)
        assert read_calls["under_root"] == 0
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_path(target_root)
        _remove_output_leaf(manifest_hash)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific junction probe for V2S2-FM02")
def test_v2s2_ac03_fm02_windows_is_windows_reparse_detects_real_junction_without_isjunction(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    probe_root = REPO_ROOT / ".raptor" / "sourceops" / f"s2-reparse-probe-{uuid.uuid4().hex[:10]}"
    junction_path = probe_root / "junction"
    target_path = probe_root / "target"
    ordinary_dir = probe_root / "ordinary-dir"
    ordinary_file = probe_root / "ordinary-file.txt"
    probe_root.mkdir(parents=True, exist_ok=False)
    target_path.mkdir(parents=True, exist_ok=False)
    ordinary_dir.mkdir(parents=True, exist_ok=False)
    ordinary_file.write_text("ordinary-file", encoding="utf-8")
    _create_windows_junction(junction_path, target_path)
    try:
        junction_stat = os.lstat(junction_path)
        reparse_attr = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400))
        file_attributes = int(getattr(junction_stat, "st_file_attributes", 0))
        reparse_tag = int(getattr(junction_stat, "st_reparse_tag", 0))
        assert reparse_tag != 0 or (file_attributes & reparse_attr) != 0
        _simulate_missing_windows_isjunction(monkeypatch, staged_mod)
        assert staged_mod._is_windows_reparse(junction_path) is True
        assert staged_mod._is_windows_reparse(ordinary_dir) is False
        assert staged_mod._is_windows_reparse(ordinary_file) is False
    finally:
        _remove_windows_junction(junction_path)
        _remove_path(probe_root)


def test_v2s2_ac01_manifest_missing_emits_exact_code() -> None:
    manifest, files = _base_manifest_and_files()
    with _stage_case("s2-manifest-missing", manifest, files) as (stage_root, staging_rel):
        (stage_root / "manifest.yaml").unlink()
        result = _run_verify_stage(staging_rel)
    _assert_one_line_stdout_zero_stderr(result)
    report = _parse_json_stdout(result)
    assert result.returncode == 2
    assert _error_code(report) == "STAGING_MANIFEST_MISSING"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None


def test_v2s2_ac01_manifest_type_invalid_emits_exact_code() -> None:
    manifest, files = _base_manifest_and_files()
    with _stage_case("s2-manifest-type", manifest, files) as (stage_root, staging_rel):
        manifest_path = stage_root / "manifest.yaml"
        manifest_path.unlink()
        manifest_path.mkdir(parents=False, exist_ok=False)
        result = _run_verify_stage(staging_rel)
    _assert_one_line_stdout_zero_stderr(result)
    report = _parse_json_stdout(result)
    assert result.returncode == 2
    assert _error_code(report) == "STAGING_MANIFEST_TYPE_INVALID"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None


def test_v2s2_ac01_manifest_read_failed_emits_exact_code(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    with _stage_case("s2-manifest-read-fail", manifest, files) as (stage_root, staging_rel):
        manifest_path = stage_root / "manifest.yaml"
        original_read_bytes = Path.read_bytes

        def _boom(self: Path) -> bytes:
            if self == manifest_path:
                raise OSError("synthetic manifest read failure")
            return original_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", _boom, raising=True)
        code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    assert code == 2
    assert payload["run_status"] == "FAILED"
    assert payload["verification_artifact"] is None
    assert payload["diff_artifact"] is None
    assert _error_code(payload) == "STAGING_MANIFEST_READ_FAILED"


def test_v2s2_ac01_manifest_limit_exceeded_emits_exact_code() -> None:
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"s2-manifest-limit-{uuid.uuid4().hex[:10]}"
    stage_root = STAGING_PARENT / stage_name
    stage_root.mkdir(parents=False, exist_ok=False)
    try:
        (stage_root / "manifest.yaml").write_bytes(b"m" * 262145)
        result = _run_verify_stage(f".raptor/sourceops/staging/{stage_name}")
    finally:
        _remove_path(stage_root)
    _assert_one_line_stdout_zero_stderr(result)
    report = _parse_json_stdout(result)
    assert result.returncode == 2
    assert _error_code(report) == "STAGING_MANIFEST_LIMIT_EXCEEDED"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None


def test_v2s2_ac05_staging_text_encoding_invalid_emits_exact_code() -> None:
    manifest, files = _base_manifest_and_files()
    files = copy.deepcopy(files)
    files["candidate/ingest/tsc.yaml"] = b"\xff\xfe\xfd"
    with _stage_case("s2-text-encoding", manifest, files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_one_line_stdout_zero_stderr(result)
    report = _parse_json_stdout(result)
    assert result.returncode == 2
    assert _error_code(report) == "STAGING_TEXT_ENCODING_INVALID"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None


def test_v2s2_ac03_staging_path_invalid_unlisted_reserved_entry_emits_catalog_envelope() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case("s2-path-invalid", manifest, files) as (stage_root, staging_rel):
            offending_path = _write_reserved_unlisted_con_entry(stage_root, payload=b"reserved-unlisted-entry")
            result = _run_verify_stage(staging_rel)
        report = _assert_exact_failure(result, expected_code="STAGING_PATH_INVALID", expected_exit=2)
        assert set(report) == set(_spec()["cli_contract"]["stdout"]["top_level_required_exact"])
        assert report["schema"] == _spec()["cli_contract"]["stdout"]["schema_id"]
        assert report["command"] == "verify-stage"
        assert report["source_id"] == manifest["source_binding"]["source_id"]
        assert report["registry_content_hash"] == manifest["source_binding"]["registry_content_hash"]
        assert report["manifest_content_hash"] == manifest_hash
        error = report["error"]
        assert isinstance(error, dict)
        assert error["subject"] == offending_path
        assert error["expected"] is None
        assert error["actual"] is None
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac04_staging_limit_exceeded_depth_emits_exact_code(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    synthetic_root_rel = "candidate/ingest/depth-limit-root"
    offending_suffix = [f"d{idx:04d}" for idx in range(1, 7)]
    offending_rel = f"{synthetic_root_rel}/{'/'.join(offending_suffix)}"
    forbidden_rel = f"{offending_rel}/d0007"

    try:
        with _stage_case("s2-limit-depth", manifest, files) as (stage_root, staging_rel):
            depth_root = stage_root / Path(synthetic_root_rel.replace("/", os.sep))
            depth_root.mkdir(parents=True, exist_ok=False)
            cursor = depth_root
            for idx in range(1, 13):
                cursor = cursor / f"d{idx:04d}"
                cursor.mkdir(parents=False, exist_ok=False)

            scanned_rel: list[str] = []
            scan_calls = {"count": 0}
            real_scandir = staged_mod.os.scandir
            monkeypatch.setattr(staged_mod, "_snapshot_stage_tree", lambda _stage_root: {"entries": []}, raising=True)

            def _rel(directory: Path) -> str:
                try:
                    return directory.relative_to(stage_root).as_posix()
                except ValueError:
                    return directory.as_posix()

            def _tracking_scandir(directory: os.PathLike[str] | str) -> Any:
                directory_path = Path(directory)
                scan_calls["count"] += 1
                scanned_rel.append(_rel(directory_path))
                return real_scandir(directory)

            monkeypatch.setattr(staged_mod.os, "scandir", _tracking_scandir, raising=True)
            try:
                code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
            finally:
                monkeypatch.setattr(staged_mod.os, "scandir", real_scandir, raising=True)

        assert code == 2
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "INVALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        error = _assert_exact_error_from_authority(report, expected_code="STAGING_LIMIT_EXCEEDED", expected_exit=2)
        _assert_path_subject_forward_slash(error, expected=offending_rel)
        _assert_no_backslash_for_path_subject(report)
        assert error["expected"] == "<= 8 path segments"
        assert error["actual"] == 9
        assert forbidden_rel not in scanned_rel
        assert scan_calls["count"] <= 16
        assert _error_code(report) != "INTERNAL_ERROR"
        assert "RecursionError" not in json.dumps(report, sort_keys=True)
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_b6_phase_order_registry_hash_mismatch_wins_over_unlisted_tree_defect() -> None:
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    manifest["source_binding"]["registry_content_hash"] = "f" * 64
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files = copy.deepcopy(files)
    files["candidate/unlisted/extra.bin"] = b"unlisted"
    with _stage_case("s2-phase-order", manifest, files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_one_line_stdout_zero_stderr(result)
    report = _parse_json_stdout(result)
    assert result.returncode == 5
    assert _error_code(report) == "BASELINE_REGISTRY_HASH_MISMATCH"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None


def test_v2s2_ac12_ac13_fm16_concurrent_identical_writers_succeed_idempotently() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    worker_count = 12
    round_count = 4
    _remove_output_leaf(manifest_hash)
    canonical_stdout: str | None = None
    try:
        with _stage_case("s2-fm16-concurrent-identical", manifest, files) as (_, staging_rel):
            for round_idx in range(round_count):
                _remove_output_leaf(manifest_hash)
                results = _run_verify_stage_concurrently(staging_rel, worker_count=worker_count)
                assert len(results) == worker_count
                for result in results:
                    _assert_one_line_stdout_zero_stderr(result)
                return_codes = [result.returncode for result in results]
                assert return_codes == [0] * worker_count, f"round {round_idx} returned non-zero codes: {return_codes!r}"
                stdout_lines = [result.stdout for result in results]
                assert len(set(stdout_lines)) == 1, f"round {round_idx} must emit byte-identical stdout for every writer"
                if canonical_stdout is None:
                    canonical_stdout = stdout_lines[0]
                else:
                    assert stdout_lines[0] == canonical_stdout, "repeated identical batches must keep deterministic stdout"
                report = _parse_json_stdout(results[0])
                assert report["run_status"] == "COMPLETED"
                assert report["input_validity"] == "VALID"
                assert report["error"] is None
                _assert_output_leaf_has_exact_artifacts(report, manifest_hash=manifest_hash)
                assert leaf.exists() and leaf.is_dir()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac12_fm16_leaf_mkdir_fileexists_race_recovers_without_internal70(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    _remove_output_leaf(manifest_hash)
    injected = {"value": 0}
    original_mkdir = Path.mkdir

    def _mkdir_then_fileexists(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == leaf and injected["value"] == 0:
            injected["value"] += 1
            original_mkdir(self, *args, **kwargs)
            raise FileExistsError("synthetic leaf mkdir race")
        return original_mkdir(self, *args, **kwargs)

    try:
        with _stage_case("s2-fm16-leaf-mkdir-race", manifest, files) as (_, staging_rel):
            monkeypatch.setattr(Path, "mkdir", _mkdir_then_fileexists, raising=True)
            code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert injected["value"] == 1
        assert code == 0
        assert report["run_status"] == "COMPLETED"
        assert report["input_validity"] == "VALID"
        assert report["error"] is None
        _assert_output_leaf_has_exact_artifacts(report, manifest_hash=manifest_hash)
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "winner_scope",
    ["winner-one-final-path", "winner-both-final-paths"],
    ids=["winner-one-final-path", "winner-both-final-paths"],
)
def test_v2s2_ac12_fm16_mid_publication_identical_winner_is_accepted_without_poisoning(
    winner_scope: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case("s2-fm16-mid-publication-race", manifest, files) as (_, staging_rel):
            leaf.mkdir(parents=True, exist_ok=False)
            real_write_atomic = staged_mod._write_atomic_json
            original_read_bytes = Path.read_bytes
            write_calls = {"value": 0}
            prewritten_bytes: dict[Path, bytes] = {}
            partial_once_paths: set[Path] = set()

            def _winning_writer(path: Path, payload: dict[str, Any]) -> str:
                write_calls["value"] += 1
                should_prewrite = winner_scope == "winner-both-final-paths" or write_calls["value"] == 1
                if should_prewrite and path not in prewritten_bytes:
                    encoded = staged_mod._serialize_json(payload).encode("utf-8")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(encoded)
                    prewritten_bytes[path] = encoded
                    partial_once_paths.add(path)
                return real_write_atomic(path, payload)

            def _partial_once_read_bytes(self: Path) -> bytes:
                if self in partial_once_paths:
                    partial_once_paths.remove(self)
                    full = prewritten_bytes[self]
                    return full[: max(1, len(full) // 3)]
                return original_read_bytes(self)

            monkeypatch.setattr(staged_mod, "_write_atomic_json", _winning_writer, raising=True)
            monkeypatch.setattr(Path, "read_bytes", _partial_once_read_bytes, raising=True)
            try:
                code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
            finally:
                monkeypatch.setattr(staged_mod, "_write_atomic_json", real_write_atomic, raising=True)
                monkeypatch.setattr(Path, "read_bytes", original_read_bytes, raising=True)

            retry_code, retry_report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)

        assert prewritten_bytes, "race seam must pre-materialize at least one winner artifact path"
        assert code == 0
        assert report["run_status"] == "COMPLETED"
        assert report["input_validity"] == "VALID"
        assert report["error"] is None
        _assert_output_leaf_has_exact_artifacts(report, manifest_hash=manifest_hash)
        assert retry_code == 0
        assert retry_report["run_status"] == "COMPLETED"
        assert retry_report["input_validity"] == "VALID"
        assert retry_report["error"] is None
        _assert_output_leaf_has_exact_artifacts(retry_report, manifest_hash=manifest_hash)
        assert report["verification_artifact"] == retry_report["verification_artifact"]
        assert report["diff_artifact"] == retry_report["diff_artifact"]
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac13_unreadable_staged_file_maps_to_staging_file_read_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case("s2-ac13-staging-file-permission-denied", manifest, files) as (stage_root, staging_rel):
            target_file = stage_root / "candidate" / "ingest" / "tsc.yaml"
            original_read_bytes = Path.read_bytes
            original_open = Path.open

            def _deny_read_bytes(self: Path) -> bytes:
                if self == target_file:
                    raise PermissionError("synthetic permission denied for listed staged file")
                return original_read_bytes(self)

            def _deny_open(self: Path, *args: Any, **kwargs: Any) -> Any:
                if self == target_file:
                    raise PermissionError("synthetic permission denied for listed staged file")
                return original_open(self, *args, **kwargs)

            monkeypatch.setattr(Path, "read_bytes", _deny_read_bytes, raising=True)
            monkeypatch.setattr(Path, "open", _deny_open, raising=True)
            code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert code == 2
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "INVALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        assert _error_code(report) == "STAGING_FILE_READ_FAILED"
        error = _assert_exact_error_from_authority(report, expected_code="STAGING_FILE_READ_FAILED", expected_exit=2)
        _assert_path_subject_forward_slash(error, expected="candidate/ingest/tsc.yaml")
        _assert_no_backslash_for_path_subject(report)
        assert not leaf.exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac12_ac15_fm10_fm16_second_artifact_write_failure_leaves_no_new_leaf_and_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    sentinel = OUTPUT_PARENT / f"s2-preexisting-output-sentinel-{uuid.uuid4().hex[:10]}.txt"
    _remove_output_leaf(manifest_hash)
    OUTPUT_PARENT.mkdir(parents=True, exist_ok=True)
    sentinel.write_bytes(b"preexisting-output-sentinel")
    sentinel_before = sentinel.read_bytes()
    real_write_atomic = staged_mod._write_atomic_json
    write_calls = {"value": 0}

    def _fail_second_artifact(path: Path, payload: dict[str, Any]) -> str:
        write_calls["value"] += 1
        if write_calls["value"] == 2:
            raise OSError("synthetic second artifact write failure")
        return real_write_atomic(path, payload)

    monkeypatch.setattr(staged_mod, "_write_atomic_json", _fail_second_artifact, raising=True)
    try:
        with _stage_case("s2-fm16-second-artifact-failure", manifest, files) as (_, staging_rel):
            first_code, first_report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
            assert first_code == 7
            assert first_report["run_status"] == "FAILED"
            assert first_report["input_validity"] == "VALID"
            assert first_report["verification_artifact"] is None
            assert first_report["diff_artifact"] is None
            assert _error_code(first_report) == "OUTPUT_WRITE_FAILED"
            _assert_exact_error_from_authority(first_report, expected_code="OUTPUT_WRITE_FAILED", expected_exit=7)
            assert not leaf.exists()
            assert sentinel.read_bytes() == sentinel_before

            monkeypatch.setattr(staged_mod, "_write_atomic_json", real_write_atomic, raising=True)
            retry_code, retry_report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
            assert retry_code == 0
            assert retry_report["run_status"] == "COMPLETED"
            assert retry_report["input_validity"] == "VALID"
            assert retry_report["error"] is None
            _assert_output_leaf_has_exact_artifacts(retry_report, manifest_hash=manifest_hash)
            assert sentinel.read_bytes() == sentinel_before

        assert write_calls["value"] >= 2
    finally:
        _remove_path(sentinel)
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac12_fm16_existing_empty_output_leaf_is_accepted() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    _remove_output_leaf(manifest_hash)
    leaf.mkdir(parents=True, exist_ok=False)
    try:
        with _stage_case("s2-empty-leaf", manifest, files) as (_, staging_rel):
            first = _run_verify_stage(staging_rel)
            second = _run_verify_stage(staging_rel)
        _assert_one_line_stdout_zero_stderr(first)
        _assert_one_line_stdout_zero_stderr(second)
        assert first.returncode == 0
        assert second.returncode == 0
        report = _parse_json_stdout(second)
        assert isinstance(report["verification_artifact"], dict)
        assert isinstance(report["diff_artifact"], dict)
        assert len(list(leaf.iterdir())) == 2
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_fm16_preexisting_differing_expected_artifact_fails_output_collision_without_overwrite() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case("s2-differing-artifact", manifest, files) as (_, staging_rel):
            first = _run_verify_stage(staging_rel)
            _assert_one_line_stdout_zero_stderr(first)
            assert first.returncode == 0, first.stdout
            report = _parse_json_stdout(first)
            verification_ref = report["verification_artifact"]
            assert isinstance(verification_ref, dict)
            changed_artifact = REPO_ROOT / Path(str(verification_ref["path"]).replace("/", os.sep))
            changed_artifact.write_bytes(b'{"probe":"different-bytes"}\n')
            preexisting = changed_artifact.read_bytes()
            second = _run_verify_stage(staging_rel)
        _assert_one_line_stdout_zero_stderr(second)
        second_report = _parse_json_stdout(second)
        assert second.returncode == 7
        assert _error_code(second_report) == "OUTPUT_COLLISION"
        assert changed_artifact.read_bytes() == preexisting
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_fm16_preexisting_special_output_leaf_fails_output_boundary_invalid() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    expected_subject = f".raptor/sourceops/generated/staged-snapshots/{manifest_hash}"
    _remove_output_leaf(manifest_hash)
    leaf.parent.mkdir(parents=True, exist_ok=True)
    leaf.write_text("not-a-directory", encoding="utf-8")
    try:
        with _stage_case("s2-special-leaf", manifest, files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_one_line_stdout_zero_stderr(result)
        report = _parse_json_stdout(result)
        assert result.returncode == 7
        assert _error_code(report) == "OUTPUT_BOUNDARY_INVALID"
        error = _assert_exact_error_from_authority(report, expected_code="OUTPUT_BOUNDARY_INVALID", expected_exit=7)
        _assert_path_subject_forward_slash(error, expected=expected_subject)
        _assert_no_backslash_for_path_subject(report)
        assert leaf.read_text(encoding="utf-8") == "not-a-directory"
    finally:
        _remove_path(leaf)
        _remove_output_leaf(manifest_hash)


def test_v2s2_fm16_output_link_or_reparse_leaf_fails_output_boundary_invalid() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    expected_subject = f".raptor/sourceops/generated/staged-snapshots/{manifest_hash}"
    _remove_output_leaf(manifest_hash)
    external_target = REPO_ROOT.parent / f"raptor-s2-output-link-target-{uuid.uuid4().hex[:10]}"
    external_target.mkdir(parents=True, exist_ok=False)
    try:
        if os.name == "nt":
            _create_windows_junction(leaf, external_target)
            assert not leaf.is_symlink(), "junction must be detectable even when Path.is_symlink() is false"
        else:
            leaf.symlink_to(external_target, target_is_directory=True)
        with _stage_case("s2-output-link", manifest, files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel)
        _assert_one_line_stdout_zero_stderr(result)
        report = _parse_json_stdout(result)
        assert result.returncode == 7
        assert _error_code(report) == "OUTPUT_BOUNDARY_INVALID"
        error = _assert_exact_error_from_authority(report, expected_code="OUTPUT_BOUNDARY_INVALID", expected_exit=7)
        _assert_path_subject_forward_slash(error, expected=expected_subject)
        _assert_no_backslash_for_path_subject(report)
    finally:
        if os.name == "nt":
            _remove_windows_junction(leaf)
        else:
            _remove_path(leaf)
        _remove_path(external_target)
        _remove_output_leaf(manifest_hash)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific junction probe for V2S2-FM16")
def test_v2s2_ac12_ac15_fm16_windows_output_ancestor_junction_without_isjunction_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    link_path = REPO_ROOT / ".raptor" / "sourceops" / "generated"
    external_target = REPO_ROOT.parent / f"raptor-s2-output-ancestor-no-isjunction-{uuid.uuid4().hex[:10]}"
    try:
        external_target.mkdir(parents=True, exist_ok=False)
        with _swap_directory_with_link(link_path, external_target):
            with _stage_case("s2-output-ancestor-no-isjunction", manifest, files) as (_, staging_rel):
                _simulate_missing_windows_isjunction(monkeypatch, staged_mod)
                code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert code == 7
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "VALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        _assert_exact_error_from_authority(report, expected_code="OUTPUT_BOUNDARY_INVALID", expected_exit=7)
        leaked_files = [path for path in external_target.rglob("*") if path.is_file()]
        assert not leaked_files, f"no artifact bytes may be written outside repo via output ancestor junctions: {leaked_files}"
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_path(external_target)
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac07_fm10b_registry_mutation_between_baseline_snapshots_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    real_snapshot = staged_mod._snapshot_baseline_files
    call_count = {"value": 0}

    def _mutating_snapshot(source_record: dict[str, Any], repo_root: Path) -> dict[str, Any]:
        snap = real_snapshot(source_record, repo_root)
        call_count["value"] += 1
        if call_count["value"] == 2:
            snap = copy.deepcopy(snap)
            snap["registry"]["sha256"] = "0" * 64
        return snap

    monkeypatch.setattr(staged_mod, "_snapshot_baseline_files", _mutating_snapshot, raising=True)
    try:
        with _stage_case("s2-baseline-registry-mutate", manifest, files) as (_, staging_rel):
            code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    finally:
        _remove_output_leaf(manifest_hash)
    assert code == 6
    assert payload["run_status"] == "FAILED"
    assert _error_code(payload) == "BASELINE_CHANGED_DURING_RUN"
    assert payload["verification_artifact"] is None
    assert payload["diff_artifact"] is None


def test_v2s2_ac07_fm10b_declaration_mutation_between_baseline_snapshots_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    real_snapshot = staged_mod._snapshot_baseline_files
    call_count = {"value": 0}

    def _mutating_snapshot(source_record: dict[str, Any], repo_root: Path) -> dict[str, Any]:
        snap = real_snapshot(source_record, repo_root)
        call_count["value"] += 1
        if call_count["value"] == 2 and snap.get("entries"):
            snap = copy.deepcopy(snap)
            snap["entries"][0]["sha256"] = "f" * 64
        return snap

    monkeypatch.setattr(staged_mod, "_snapshot_baseline_files", _mutating_snapshot, raising=True)
    try:
        with _stage_case("s2-baseline-decl-mutate", manifest, files) as (_, staging_rel):
            code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    finally:
        _remove_output_leaf(manifest_hash)
    assert code == 6
    assert payload["run_status"] == "FAILED"
    assert _error_code(payload) == "BASELINE_CHANGED_DURING_RUN"
    assert payload["verification_artifact"] is None
    assert payload["diff_artifact"] is None


def test_v2s2_bl1_staging_parent_link_component_is_rejected_even_when_target_inside_repo() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    stage_name = f"s2-bl1-stage-{uuid.uuid4().hex[:10]}"
    target_parent = REPO_ROOT / ".raptor" / "sourceops" / f"staging-link-target-{uuid.uuid4().hex[:10]}"
    stage_root = target_parent / stage_name
    try:
        stage_root.mkdir(parents=True, exist_ok=False)
        for rel_path, raw in files.items():
            out_path = stage_root / Path(rel_path.replace("/", os.sep))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(raw)
        dumped = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
        (stage_root / "manifest.yaml").write_text(dumped, encoding="utf-8", newline="")
        with _swap_directory_with_link(STAGING_PARENT, target_parent):
            result = _run_verify_stage(f".raptor/sourceops/staging/{stage_name}")
        _assert_exact_failure(result, expected_code="STAGING_ROOT_INVALID", expected_exit=2)
        assert not (OUTPUT_PARENT / manifest_hash).exists(), "ancestor-link boundary failure must not emit artifacts"
    finally:
        _remove_path(target_parent)
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "ancestor_rel",
    [
        ".raptor/sourceops/generated",
        ".raptor/sourceops/generated/staged-snapshots",
    ],
    ids=["generated-parent", "staged-snapshots-parent"],
)
def test_v2s2_bl1_output_ancestor_link_components_rejected_without_external_writes(ancestor_rel: str) -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    link_path = REPO_ROOT / Path(ancestor_rel.replace("/", os.sep))
    external_target = REPO_ROOT.parent / f"raptor-s2-output-ancestor-{uuid.uuid4().hex[:10]}"
    try:
        external_target.mkdir(parents=True, exist_ok=False)
        with _swap_directory_with_link(link_path, external_target):
            with _stage_case("s2-bl1-output-ancestor", manifest, files) as (_, staging_rel):
                result = _run_verify_stage(staging_rel)
        _assert_exact_failure(
            result,
            expected_code="OUTPUT_BOUNDARY_INVALID",
            expected_exit=7,
            expected_input_validity="VALID",
        )
        leaked_files = [path for path in external_target.rglob("*") if path.is_file()]
        assert not leaked_files, f"no artifact bytes may be written outside repo via output ancestor links: {leaked_files}"
    finally:
        _remove_path(external_target)
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize("ancestor_rel", ["candidate", "candidate/ingest"], ids=["candidate-dir", "candidate-ingest-dir"])
def test_v2s2_bl2_staging_nested_directory_link_components_are_rejected(ancestor_rel: str) -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    target_dir = REPO_ROOT / ".raptor" / "sourceops" / f"staging-link-nested-target-{uuid.uuid4().hex[:10]}"
    try:
        with _stage_case("s2-bl2-nested-link", manifest, files) as (stage_root, staging_rel):
            if ancestor_rel == "candidate":
                (target_dir / "ingest").mkdir(parents=True, exist_ok=False)
                (target_dir / "ingest" / "tsc.yaml").write_bytes(files["candidate/ingest/tsc.yaml"])
            else:
                target_dir.mkdir(parents=True, exist_ok=False)
                (target_dir / "tsc.yaml").write_bytes(files["candidate/ingest/tsc.yaml"])
            link_path = stage_root / Path(ancestor_rel.replace("/", os.sep))
            with _swap_directory_with_link(link_path, target_dir):
                result = _run_verify_stage(staging_rel)
        _assert_exact_failure(result, expected_code="STAGING_ENTRY_TYPE_INVALID", expected_exit=2)
        assert not (OUTPUT_PARENT / manifest_hash).exists(), "staging link ancestors must not emit artifacts"
    finally:
        _remove_path(target_dir)
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl7_inventory_limit_per_file_size_uses_exact_limit_error() -> None:
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    oversized = b"x" * (16 * 1024 * 1024 + 1)
    oversized_rel = "candidate/limits/per-file-oversized.bin"
    manifest["files"].append(
        {
            "file_id": "oversized-file",
            "path": oversized_rel,
            "role": "SNAPSHOT_CONTENT",
            "media_type": "application/octet-stream",
            "checksum": _raw_checksum(oversized),
            "component_ids": [],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "bind-oversized-file",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "oversized-file",
        }
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files = copy.deepcopy(files)
    files[oversized_rel] = oversized
    with _stage_case("s2-bl7-per-file-limit", manifest, files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_exact_failure(result, expected_code="STAGING_LIMIT_EXCEEDED", expected_exit=2)


def test_v2s2_bl7_snapshot_per_file_limit_rejects_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    files = copy.deepcopy(files)
    oversized_rel = "candidate/limits/snapshot-per-file-oversized.bin"
    manifest["files"].append(
        {
            "file_id": "snapshot-per-file-oversized",
            "path": oversized_rel,
            "role": "SNAPSHOT_CONTENT",
            "media_type": "application/octet-stream",
            "checksum": _raw_checksum(b"x"),
            "component_ids": [],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "bind-snapshot-per-file-oversized",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "snapshot-per-file-oversized",
        }
    )
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files[oversized_rel] = b"x"
    with _stage_case("s2-bl7-snapshot-per-file-preread", manifest, files) as (stage_root, staging_rel):
        oversized_path = stage_root / Path(oversized_rel.replace("/", os.sep))
        _write_sparse_file(oversized_path, size=16 * 1024 * 1024 + 1)
        read_calls = {"oversized": 0}
        original_read_bytes = Path.read_bytes

        def _tracking_read_bytes(self: Path) -> bytes:
            if self == oversized_path:
                read_calls["oversized"] += 1
            return original_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", _tracking_read_bytes, raising=True)
        code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    assert code == 2
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == "INVALID"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    _assert_exact_error_from_authority(report, expected_code="STAGING_LIMIT_EXCEEDED", expected_exit=2)
    assert read_calls["oversized"] == 0


def test_v2s2_bl7_inventory_limit_total_bound_bytes_uses_exact_limit_error() -> None:
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    files = copy.deepcopy(files)
    payload = b"z" * (13 * 1024 * 1024)
    for idx in range(5):
        file_id = f"total-bytes-{idx:02d}"
        rel = f"candidate/limits/total-{idx:02d}.bin"
        manifest["files"].append(
            {
                "file_id": file_id,
                "path": rel,
                "role": "SNAPSHOT_CONTENT",
                "media_type": "application/octet-stream",
                "checksum": _raw_checksum(payload),
                "component_ids": [],
            }
        )
        manifest["content_bindings"].append(
            {
                "binding_id": f"bind-total-bytes-{idx:02d}",
                "baseline_kind": "NONE",
                "baseline_id": None,
                "candidate_file_id": file_id,
            }
        )
        files[rel] = payload
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case("s2-bl7-total-bytes-limit", manifest, files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_exact_failure(result, expected_code="STAGING_LIMIT_EXCEEDED", expected_exit=2)


def test_v2s2_bl7_snapshot_total_limit_rejects_before_read_of_offending_file(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    files = copy.deepcopy(files)
    rel_paths: list[str] = []
    payload_size = 13 * 1024 * 1024
    matching_sparse_checksum = _raw_checksum(b"\x00" * payload_size)
    for idx in range(5):
        file_id = f"snapshot-total-{idx:02d}"
        rel = f"candidate/limits/snapshot-total-{idx:02d}.bin"
        rel_paths.append(rel)
        manifest["files"].append(
            {
                "file_id": file_id,
                "path": rel,
                "role": "SNAPSHOT_CONTENT",
                "media_type": "application/octet-stream",
                "checksum": copy.deepcopy(matching_sparse_checksum),
                "component_ids": [],
            }
        )
        manifest["content_bindings"].append(
            {
                "binding_id": f"bind-snapshot-total-{idx:02d}",
                "baseline_kind": "NONE",
                "baseline_id": None,
                "candidate_file_id": file_id,
            }
        )
        files[rel] = b"\x00"
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    offending_rel = rel_paths[-1]
    with _stage_case("s2-bl7-snapshot-total-preread", manifest, files) as (stage_root, staging_rel):
        for rel in rel_paths:
            _write_sparse_file(stage_root / Path(rel.replace("/", os.sep)), size=payload_size)
        offending_path = stage_root / Path(offending_rel.replace("/", os.sep))
        read_calls = {"offending": 0}
        original_read_bytes = Path.read_bytes

        def _tracking_read_bytes(self: Path) -> bytes:
            if self == offending_path:
                read_calls["offending"] += 1
            return original_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", _tracking_read_bytes, raising=True)
        code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    assert code == 2
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == "INVALID"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    _assert_exact_error_from_authority(report, expected_code="STAGING_LIMIT_EXCEEDED", expected_exit=2)
    assert report["error"]["subject"] == offending_rel
    assert read_calls["offending"] == 0


def test_v2s2_bl7_unlisted_oversized_file_fails_limit_before_tree_mismatch_without_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    with _stage_case("s2-bl7-unlisted-oversized", manifest, files) as (stage_root, staging_rel):
        unlisted_rel = "candidate/unlisted-limits/oversized.bin"
        unlisted_path = stage_root / Path(unlisted_rel.replace("/", os.sep))
        unlisted_path.parent.mkdir(parents=True, exist_ok=True)
        _write_sparse_file(unlisted_path, size=16 * 1024 * 1024 + 1)
        read_calls = {"unlisted": 0}
        original_read_bytes = Path.read_bytes

        def _tracking_read_bytes(self: Path) -> bytes:
            if self == unlisted_path:
                read_calls["unlisted"] += 1
            return original_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", _tracking_read_bytes, raising=True)
        code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    assert code == 2
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == "INVALID"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    _assert_exact_error_from_authority(report, expected_code="STAGING_LIMIT_EXCEEDED", expected_exit=2)
    assert report["error"]["subject"] == unlisted_rel
    assert read_calls["unlisted"] == 0


def test_v2s2_bl7_unlisted_total_limit_subject_is_deterministic_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    with _stage_case("s2-bl7-unlisted-total-limit", manifest, files) as (stage_root, staging_rel):
        unlisted_rels = [f"candidate/unlisted-limits/total-{idx:02d}.bin" for idx in range(5)]
        for rel in unlisted_rels:
            path = stage_root / Path(rel.replace("/", os.sep))
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_sparse_file(path, size=13 * 1024 * 1024)
        offending_rel = unlisted_rels[-1]
        offending_path = stage_root / Path(offending_rel.replace("/", os.sep))
        read_calls = {"offending": 0}
        original_read_bytes = Path.read_bytes

        def _tracking_read_bytes(self: Path) -> bytes:
            if self == offending_path:
                read_calls["offending"] += 1
            return original_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", _tracking_read_bytes, raising=True)
        code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
    assert code == 2
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == "INVALID"
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    _assert_exact_error_from_authority(report, expected_code="STAGING_LIMIT_EXCEEDED", expected_exit=2)
    assert report["error"]["subject"] == offending_rel
    assert read_calls["offending"] == 0


def test_v2s2_bl7_boundary_sized_file_remains_eligible_for_content_validation() -> None:
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    files = copy.deepcopy(files)
    boundary_rel = "candidate/limits/boundary-size.bin"
    manifest["files"].append(
        {
            "file_id": "boundary-size-file",
            "path": boundary_rel,
            "role": "SNAPSHOT_CONTENT",
            "media_type": "application/octet-stream",
            "checksum": _raw_checksum(b"x"),
            "component_ids": [],
        }
    )
    manifest["content_bindings"].append(
        {
            "binding_id": "bind-boundary-size-file",
            "baseline_kind": "NONE",
            "baseline_id": None,
            "candidate_file_id": "boundary-size-file",
        }
    )
    manifest["files"] = sorted(manifest["files"], key=lambda row: row["file_id"])
    manifest["content_bindings"] = sorted(manifest["content_bindings"], key=lambda row: row["binding_id"])
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    files[boundary_rel] = b"x"
    with _stage_case("s2-bl7-boundary-size", manifest, files) as (stage_root, staging_rel):
        boundary_path = stage_root / Path(boundary_rel.replace("/", os.sep))
        _write_sparse_file(boundary_path, size=16 * 1024 * 1024)
        result = _run_verify_stage(staging_rel)
    _assert_exact_failure(result, expected_code="STAGING_FILE_SIZE_MISMATCH", expected_exit=2)


def test_v2s2_bl7_directory_count_limit_is_enforced_at_inventory_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)

    class _SyntheticDirEntry:
        def __init__(self, path: Path) -> None:
            self.path = str(path)

        def is_symlink(self) -> bool:
            return False

        def stat(self, *, follow_symlinks: bool = False) -> os.stat_result:
            _ = follow_symlinks
            return os.stat_result((stat.S_IFDIR | 0o755, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    class _SyntheticScandir:
        def __init__(self, entries: list[_SyntheticDirEntry]) -> None:
            self._entries = entries
            self._iterator = iter(self._entries)

        def __enter__(self) -> "_SyntheticScandir":
            self._iterator = iter(self._entries)
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            _ = (exc_type, exc, tb)
            return False

        def __iter__(self) -> "_SyntheticScandir":
            return self

        def __next__(self) -> _SyntheticDirEntry:
            return next(self._iterator)

    synthetic_root_rel = "candidate/ingest/count-limit-root"
    offending_name = "c062"
    offending_rel = f"{synthetic_root_rel}/{offending_name}"
    forbidden_rel = f"{offending_rel}/should-not-visit"
    sibling_count = 70

    try:
        with _stage_case("s2-bl7-dir-limit", manifest, files) as (stage_root, staging_rel):
            synthetic_root = stage_root / Path(synthetic_root_rel.replace("/", os.sep))
            synthetic_root.mkdir(parents=True, exist_ok=False)
            scan_calls = {"count": 0}
            scanned_rel: list[str] = []
            real_scandir = staged_mod.os.scandir
            monkeypatch.setattr(staged_mod, "_snapshot_stage_tree", lambda _stage_root: {"entries": []}, raising=True)

            def _rel(directory: Path) -> str:
                try:
                    return directory.relative_to(stage_root).as_posix()
                except ValueError:
                    return directory.as_posix()

            def _fake_scandir(directory: os.PathLike[str] | str) -> Any:
                directory_path = Path(directory)
                scan_calls["count"] += 1
                scanned_rel.append(_rel(directory_path))
                if directory_path == synthetic_root:
                    entries = [
                        _SyntheticDirEntry(synthetic_root / f"c{idx:03d}")
                        for idx in range(1, sibling_count + 1)
                    ]
                    return _SyntheticScandir(entries)
                if directory_path.parent == synthetic_root and directory_path.name == offending_name:
                    return _SyntheticScandir([_SyntheticDirEntry(directory_path / "should-not-visit")])
                if directory_path.parent == synthetic_root or directory_path.name == "should-not-visit":
                    return _SyntheticScandir([])
                return real_scandir(directory)

            monkeypatch.setattr(staged_mod.os, "scandir", _fake_scandir, raising=True)
            try:
                code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
            finally:
                monkeypatch.setattr(staged_mod.os, "scandir", real_scandir, raising=True)

        assert code == 2
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "INVALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        error = _assert_exact_error_from_authority(report, expected_code="STAGING_LIMIT_EXCEEDED", expected_exit=2)
        _assert_path_subject_forward_slash(error, expected=offending_rel)
        _assert_no_backslash_for_path_subject(report)
        assert error["expected"] == "<= 64 directories"
        assert error["actual"] == 65
        assert forbidden_rel not in scanned_rel
        assert scan_calls["count"] <= 66
        assert _error_code(report) != "INTERNAL_ERROR"
        assert "RecursionError" not in json.dumps(report, sort_keys=True)
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl7_unlisted_extreme_depth_guard_avoids_recursion_and_internal_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)

    class _SyntheticDirEntry:
        def __init__(self, path: Path) -> None:
            self.path = str(path)

        def is_symlink(self) -> bool:
            return False

        def stat(self, *, follow_symlinks: bool = False) -> os.stat_result:
            _ = follow_symlinks
            return os.stat_result((stat.S_IFDIR | 0o755, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    class _SyntheticScandir:
        def __init__(self, entries: list[_SyntheticDirEntry]) -> None:
            self._entries = entries
            self._iterator = iter(self._entries)

        def __enter__(self) -> "_SyntheticScandir":
            self._iterator = iter(self._entries)
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            _ = (exc_type, exc, tb)
            return False

        def __iter__(self) -> "_SyntheticScandir":
            return self

        def __next__(self) -> _SyntheticDirEntry:
            return next(self._iterator)

    synthetic_root_rel = "candidate/ingest/extreme-depth-root"
    depth_limit = 1500
    offending_suffix = [f"d{idx:04d}" for idx in range(1, 7)]
    offending_rel = f"{synthetic_root_rel}/{'/'.join(offending_suffix)}"
    forbidden_rel = f"{offending_rel}/d0007"

    try:
        with _stage_case("s2-bl7-extreme-depth", manifest, files) as (stage_root, staging_rel):
            synthetic_root = stage_root / Path(synthetic_root_rel.replace("/", os.sep))
            synthetic_root.mkdir(parents=True, exist_ok=False)
            scan_calls = {"count": 0}
            scanned_rel: list[str] = []
            real_scandir = staged_mod.os.scandir
            monkeypatch.setattr(staged_mod, "_snapshot_stage_tree", lambda _stage_root: {"entries": []}, raising=True)

            def _rel(directory: Path) -> str:
                try:
                    return directory.relative_to(stage_root).as_posix()
                except ValueError:
                    return directory.as_posix()

            def _fake_scandir(directory: os.PathLike[str] | str) -> Any:
                directory_path = Path(directory)
                scan_calls["count"] += 1
                scanned_rel.append(_rel(directory_path))
                if directory_path == synthetic_root:
                    return _SyntheticScandir([_SyntheticDirEntry(synthetic_root / "d0001")])
                if directory_path.is_relative_to(synthetic_root):
                    synthetic_parts = directory_path.relative_to(synthetic_root).parts
                    if synthetic_parts and all(part.startswith("d") for part in synthetic_parts):
                        depth = len(synthetic_parts)
                        if depth < depth_limit:
                            return _SyntheticScandir([_SyntheticDirEntry(directory_path / f"d{depth + 1:04d}")])
                        return _SyntheticScandir([])
                return real_scandir(directory)

            monkeypatch.setattr(staged_mod.os, "scandir", _fake_scandir, raising=True)
            try:
                code, report = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
            finally:
                monkeypatch.setattr(staged_mod.os, "scandir", real_scandir, raising=True)

        assert code == 2
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "INVALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        error = _assert_exact_error_from_authority(report, expected_code="STAGING_LIMIT_EXCEEDED", expected_exit=2)
        _assert_path_subject_forward_slash(error, expected=offending_rel)
        _assert_no_backslash_for_path_subject(report)
        assert error["expected"] == "<= 8 path segments"
        assert error["actual"] == 9
        assert forbidden_rel not in scanned_rel
        assert scan_calls["count"] <= 16
        assert code != 70
        assert _error_code(report) != "INTERNAL_ERROR"
        serialized = json.dumps(report, sort_keys=True)
        assert "RecursionError" not in serialized
        assert "maximum recursion depth exceeded" not in serialized
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "case_id,manifest_bytes",
    [
        ("too-many-nodes", ("items:\n" + "".join("  - 1\n" for _ in range(10001))).encode("utf-8")),
        (
            "too-deep",
            (
                "".join(f"{'  ' * idx}k{idx}:\n" for idx in range(17))
                + f"{'  ' * 17}leaf: 1\n"
            ).encode("utf-8"),
        ),
    ],
    ids=["too-many-nodes", "too-deep"],
)
def test_v2s2_bl7_manifest_node_and_depth_limits_use_manifest_limit_code(case_id: str, manifest_bytes: bytes) -> None:
    STAGING_PARENT.mkdir(parents=True, exist_ok=True)
    stage_name = f"s2-bl7-manifest-limit-{case_id}-{uuid.uuid4().hex[:10]}"
    stage_root = STAGING_PARENT / stage_name
    stage_root.mkdir(parents=False, exist_ok=False)
    try:
        (stage_root / "manifest.yaml").write_bytes(manifest_bytes)
        result = _run_verify_stage(f".raptor/sourceops/staging/{stage_name}")
    finally:
        _remove_path(stage_root)
    _assert_exact_failure(result, expected_code="STAGING_MANIFEST_LIMIT_EXCEEDED", expected_exit=2)


def test_v2s2_bl8_staging_path_invalid_uses_inventory_phase_and_exact_message() -> None:
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    manifest["files"][0]["path"] = "candidate/con"
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case("s2-bl8-path-phase", manifest, files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    _assert_exact_failure(result, expected_code="STAGING_PATH_INVALID", expected_exit=2)


def test_v2s2_bl8_duplicate_detail_assignment_is_closed_and_deterministic() -> None:
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    files = copy.deepcopy(files)
    for idx, payload in enumerate((b"a", b"b"), start=1):
        file_id = "decl-tsc-yaml"
        rel = f"candidate/duplicate/probe-{idx}.bin"
        manifest["files"].append(
            {
                "file_id": file_id,
                "path": rel,
                "role": "AUXILIARY_METADATA",
                "media_type": "application/octet-stream",
                "checksum": _raw_checksum(payload),
                "component_ids": [],
            }
        )
        manifest["content_bindings"].append(
            {
                "binding_id": f"bind-duplicate-probe-{idx}",
                "baseline_kind": "NONE",
                "baseline_id": None,
                "candidate_file_id": file_id,
            }
        )
        files[rel] = payload
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    with _stage_case("s2-bl8-dup-details", manifest, files) as (_, staging_rel):
        result = _run_verify_stage(staging_rel)
    report = _assert_exact_failure(result, expected_code="STAGING_DUPLICATE_ID", expected_exit=2)
    error = report["error"]
    assert error["subject"] == "decl-tsc-yaml"
    assert error["expected"] == "unique"
    assert error["actual"] == 3


def test_v2s2_bl11_initial_baseline_must_use_v2s1_load_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    calls = {"value": 0}
    real_load_registry = staged_mod.load_registry

    def _tracking_load_registry(path: str) -> Any:
        calls["value"] += 1
        return real_load_registry(path)

    monkeypatch.setattr(staged_mod, "load_registry", _tracking_load_registry, raising=True)
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case("s2-bl11-load-registry", manifest, files) as (_, staging_rel):
            outcome = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert outcome.exit_code == 0
        assert calls["value"] >= 1, "verify_stage must load the baseline through V2-S1 load_registry"
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl11_registry_mutation_between_validation_and_output_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    temp_rel = f"configs/sourceops/source_registry.bl11-{uuid.uuid4().hex[:10]}.yaml"
    temp_path = REPO_ROOT / Path(temp_rel.replace("/", os.sep))
    temp_bytes = REGISTRY_PATH.read_bytes()
    temp_path.write_bytes(temp_bytes)
    monkeypatch.setattr(staged_mod, "CANONICAL_REGISTRY_REL", temp_rel, raising=True)
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    manifest["source_binding"]["registry_content_hash"] = _load_registry()["registry_content_hash"]
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    mutated = {"value": False}
    real_build_verification = staged_mod._build_verification_artifact

    def _mutating_build_verification(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if not mutated["value"]:
            temp_path.write_bytes(temp_bytes + b"\n# baseline-mutated-between-passes\n")
            mutated["value"] = True
        return real_build_verification(*args, **kwargs)

    monkeypatch.setattr(staged_mod, "_build_verification_artifact", _mutating_build_verification, raising=True)
    try:
        with _stage_case("s2-bl11-registry-mutation", manifest, files) as (_, staging_rel):
            code, payload = staged_mod.verify_stage(temp_rel, staging_rel)
        assert code == 6
        assert payload["run_status"] == "FAILED"
        assert _error_code(payload) == "BASELINE_CHANGED_DURING_RUN"
        _assert_exact_error_from_authority(payload, expected_code="BASELINE_CHANGED_DURING_RUN", expected_exit=6)
        assert payload["verification_artifact"] is None
        assert payload["diff_artifact"] is None
        assert not (OUTPUT_PARENT / manifest_hash).exists(), "baseline mutation failure must not emit artifacts"
    finally:
        temp_path.unlink(missing_ok=True)
        _remove_output_leaf(manifest_hash)


def test_v2s2_bl11_second_pass_reruns_validator_and_detects_changed_validation_result(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    from raptor.sourceops.model import ValidationError, ValidationResult

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    validation_calls = {"value": 0}

    def _two_phase_validation(*_args: Any, **_kwargs: Any) -> ValidationResult:
        validation_calls["value"] += 1
        if validation_calls["value"] == 1:
            return ValidationResult(
                schema="raptor.source_registry.validation.v1",
                registry_valid=True,
                errors=[],
            )
        return ValidationResult(
            schema="raptor.source_registry.validation.v1",
            registry_valid=False,
            errors=[ValidationError(code="DECLARATION_DRIFT", message="drift", type="DeclarationDriftError")],
        )

    monkeypatch.setattr(staged_mod, "validate_registry", _two_phase_validation, raising=True)
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case("s2-bl11-validator-second-pass", manifest, files) as (_, staging_rel):
            code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert code == 6
        assert payload["run_status"] == "FAILED"
        assert _error_code(payload) == "BASELINE_CHANGED_DURING_RUN"
        _assert_exact_error_from_authority(payload, expected_code="BASELINE_CHANGED_DURING_RUN", expected_exit=6)
        assert validation_calls["value"] >= 2, "second baseline pass must rerun V2-S1 validation"
        assert payload["verification_artifact"] is None
        assert payload["diff_artifact"] is None
    finally:
        _remove_output_leaf(manifest_hash)


@contextmanager
def _temporary_canonical_registry(
    monkeypatch: pytest.MonkeyPatch,
    staged_mod: Any,
    *,
    raw_bytes: bytes,
) -> Iterator[tuple[str, Path]]:
    temp_rel = f"configs/sourceops/source_registry.v2s2-temp-{uuid.uuid4().hex[:10]}.yaml"
    temp_path = REPO_ROOT / Path(temp_rel.replace("/", os.sep))
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(raw_bytes)
    monkeypatch.setattr(staged_mod, "CANONICAL_REGISTRY_REL", temp_rel, raising=True)
    try:
        yield temp_rel, temp_path
    finally:
        temp_path.unlink(missing_ok=True)


def _assert_baseline_registry_invalid_no_artifacts(payload: dict[str, Any]) -> None:
    assert payload["run_status"] == "FAILED"
    assert payload["input_validity"] == "NOT_EVALUATED"
    assert payload["verification_artifact"] is None
    assert payload["diff_artifact"] is None
    _assert_exact_error_from_authority(payload, expected_code="BASELINE_REGISTRY_INVALID", expected_exit=6)
    serialized = json.dumps(payload, sort_keys=True)
    for marker in ("Traceback", "RegistrySchemaError", "UnicodeDecodeError", "YAMLError"):
        assert marker not in serialized


def _assert_baseline_changed_no_artifacts(payload: dict[str, Any]) -> None:
    assert payload["run_status"] == "FAILED"
    assert payload["input_validity"] == "NOT_EVALUATED"
    assert payload["verification_artifact"] is None
    assert payload["diff_artifact"] is None
    _assert_exact_error_from_authority(payload, expected_code="BASELINE_CHANGED_DURING_RUN", expected_exit=6)
    serialized = json.dumps(payload, sort_keys=True)
    for marker in ("INTERNAL_ERROR", "Traceback", "RegistrySchemaError", "UnicodeDecodeError", "YAMLError"):
        assert marker not in serialized


def test_v2s2_ac12_ac13_fm16_rollback_loser_must_not_delete_winner_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    lock_path = leaf / staged_mod.TRANSACTION_LOCK_NAME
    _remove_output_leaf(manifest_hash)

    run_a_first_artifact_ready = threading.Event()
    release_run_a = threading.Event()
    run_a_result: dict[str, Any] = {}
    run_a_error: dict[str, BaseException] = {}
    run_b_process: subprocess.Popen[str] | None = None
    thread: threading.Thread | None = None
    real_write_atomic = staged_mod._write_atomic_json
    run_a_calls = {"value": 0}

    def _coordinated_write(path: Path, payload: dict[str, Any]) -> tuple[str, bool]:
        if threading.current_thread().name == "v2s2-run-a":
            run_a_calls["value"] += 1
            if run_a_calls["value"] == 1:
                outcome = real_write_atomic(path, payload)
                run_a_first_artifact_ready.set()
                if not release_run_a.wait(timeout=60):
                    raise AssertionError("timed out waiting to release run A")
                return outcome
            if run_a_calls["value"] == 2:
                raise OSError("synthetic second artifact failure for rollback-vs-winner interleaving")
        return real_write_atomic(path, payload)

    monkeypatch.setattr(staged_mod, "_write_atomic_json", _coordinated_write, raising=True)
    try:
        with _stage_case("s2-fm16-rollback-vs-winner", manifest, files) as (_, staging_rel):
            def _run_a() -> None:
                try:
                    run_a_result["value"] = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
                except BaseException as exc:  # pragma: no cover - surfaced in main thread assertions
                    run_a_error["value"] = exc

            thread = threading.Thread(target=_run_a, name="v2s2-run-a")
            thread.start()
            assert run_a_first_artifact_ready.wait(timeout=60), "run A must publish v before run B starts"
            assert lock_path.exists(), "run A must hold the exact on-disk transaction lock while paused"
            names_before_b = sorted(entry.name for entry in leaf.iterdir())
            assert staged_mod.TRANSACTION_LOCK_NAME in names_before_b
            assert any(name.startswith("v-") for name in names_before_b), "run A pause must occur after publishing v"
            assert not any(name.startswith("d-") for name in names_before_b), "run A pause must occur before publishing d"

            run_b_process = _spawn_verify_stage_process(staging_rel)
            wait_probe_deadline = time.monotonic() + 4.0
            observed_waiting = False
            while time.monotonic() < wait_probe_deadline:
                if run_b_process.poll() is not None:
                    run_b_early = _collect_process_result(
                        run_b_process,
                        timeout_seconds=1,
                        description="run B early completion probe",
                    )
                    pytest.fail(
                        "run B must remain waiting while run A owns the exact lock.\n"
                        f"returncode={run_b_early.returncode}\n"
                        f"stdout={run_b_early.stdout!r}\nstderr={run_b_early.stderr!r}"
                    )
                observed_waiting = True
                assert lock_path.exists(), "run A must keep owning the exact lock during the wait probe"
                assert not any(entry.name.startswith("d-") for entry in leaf.iterdir()), (
                    "run B must not publish d while run A still owns the exact lock"
                )
                time.sleep(0.05)
            assert observed_waiting, "wait probe must observe run B as running/waiting"
            assert run_b_process.poll() is None, "run B must remain waiting until run A is released"

            release_run_a.set()
            thread.join(timeout=60)
            assert not thread.is_alive(), "run A must terminate after rollback interleaving release"

            if "value" in run_a_error:
                raise run_a_error["value"]
            run_a_code, run_a_payload = run_a_result["value"]
            run_b = _collect_process_result(run_b_process, timeout_seconds=15, description="run B waiting peer process")
            _assert_one_line_stdout_zero_stderr(run_b)
            assert run_b.returncode == 0
            run_b_payload = _parse_json_stdout(run_b)

        assert run_a_calls["value"] == 2
        assert run_a_code == 7
        assert run_a_payload["run_status"] == "FAILED"
        assert run_a_payload["input_validity"] == "VALID"
        assert _error_code(run_a_payload) == "OUTPUT_WRITE_FAILED"
        _assert_exact_error_from_authority(run_a_payload, expected_code="OUTPUT_WRITE_FAILED", expected_exit=7)
        assert run_a_payload["verification_artifact"] is None
        assert run_a_payload["diff_artifact"] is None

        assert run_b_payload["run_status"] == "COMPLETED"
        assert run_b_payload["input_validity"] == "VALID"
        assert run_b_payload["error"] is None
        winner_v_path, winner_d_path = _assert_output_leaf_has_exact_artifacts(run_b_payload, manifest_hash=manifest_hash)
        assert winner_v_path.exists(), "winner verification artifact path must still exist after loser rollback"
        assert winner_d_path.exists(), "winner diff artifact path must still exist after loser rollback"
        assert sorted(entry.name for entry in leaf.iterdir()) == sorted([winner_v_path.name, winner_d_path.name])
        assert not lock_path.exists(), "exact transaction lock must be removed after both writers finish"
        assert not [entry for entry in leaf.iterdir() if entry.name.startswith(staged_mod.TEMP_ARTIFACT_PREFIX)]
    finally:
        release_run_a.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)
        _cleanup_process(run_b_process)
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac12_fm16_rollback_must_not_delete_other_live_writer_temp(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    _remove_output_leaf(manifest_hash)

    run_a_first_artifact_ready = threading.Event()
    release_run_a = threading.Event()
    run_a_result: dict[str, Any] = {}
    run_a_error: dict[str, BaseException] = {}
    real_write_atomic = staged_mod._write_atomic_json
    run_a_calls = {"value": 0}
    foreign_temp_path: Path | None = None
    foreign_temp_bytes = b"foreign-live-writer-temp-bytes"

    def _coordinated_write(path: Path, payload: dict[str, Any]) -> tuple[str, bool]:
        if threading.current_thread().name == "v2s2-temp-owner-run-a":
            run_a_calls["value"] += 1
            if run_a_calls["value"] == 1:
                outcome = real_write_atomic(path, payload)
                run_a_first_artifact_ready.set()
                if not release_run_a.wait(timeout=60):
                    raise AssertionError("timed out waiting to release run A")
                return outcome
            if run_a_calls["value"] == 2:
                raise OSError("synthetic second artifact failure for temp-ownership probe")
        return real_write_atomic(path, payload)

    monkeypatch.setattr(staged_mod, "_write_atomic_json", _coordinated_write, raising=True)
    try:
        with _stage_case("s2-fm16-temp-ownership", manifest, files) as (_, staging_rel):
            def _run_a() -> None:
                try:
                    run_a_result["value"] = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
                except BaseException as exc:  # pragma: no cover - surfaced in main thread assertions
                    run_a_error["value"] = exc

            thread = threading.Thread(target=_run_a, name="v2s2-temp-owner-run-a")
            thread.start()
            assert run_a_first_artifact_ready.wait(timeout=60), "run A must publish v before foreign temp is created"
            leaf.mkdir(parents=True, exist_ok=True)
            foreign_temp_path = leaf / f"{staged_mod.TEMP_ARTIFACT_PREFIX}foreign-owner-{uuid.uuid4().hex}.json"
            foreign_temp_path.write_bytes(foreign_temp_bytes)
            release_run_a.set()
            thread.join(timeout=60)
            assert not thread.is_alive(), "run A must terminate after rollback release"

            if "value" in run_a_error:
                raise run_a_error["value"]
            run_a_code, run_a_payload = run_a_result["value"]

        assert run_a_calls["value"] == 2
        assert run_a_code == 7
        assert run_a_payload["run_status"] == "FAILED"
        assert run_a_payload["input_validity"] == "VALID"
        assert _error_code(run_a_payload) == "OUTPUT_WRITE_FAILED"
        _assert_exact_error_from_authority(run_a_payload, expected_code="OUTPUT_WRITE_FAILED", expected_exit=7)
        assert run_a_payload["verification_artifact"] is None
        assert run_a_payload["diff_artifact"] is None

        assert foreign_temp_path is not None
        assert foreign_temp_path.exists(), "rollback must not delete a temp file created by another live writer"
        assert foreign_temp_path.read_bytes() == foreign_temp_bytes
        foreign_temp_path.unlink(missing_ok=False)
        if leaf.exists() and leaf.is_dir() and not any(leaf.iterdir()):
            leaf.rmdir()
    finally:
        release_run_a.set()
        if foreign_temp_path is not None:
            foreign_temp_path.unlink(missing_ok=True)
        if leaf.exists() and leaf.is_dir() and not any(leaf.iterdir()):
            leaf.rmdir()
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac12_ac13_fm16_rollback_adoption_race_requires_transactional_leaf_publication() -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    lock_path = leaf / staged_mod.TRANSACTION_LOCK_NAME
    _remove_output_leaf(manifest_hash)

    run_a_process: subprocess.Popen[str] | None = None
    run_b_process: subprocess.Popen[str] | None = None
    sync_dir: Path | None = None
    try:
        with _stage_case("s2-fm16-rollback-adoption-real-procs", manifest, files) as (_, staging_rel):
            sync_dir = STAGING_PARENT / f"s2-process-sync-{uuid.uuid4().hex[:12]}"
            sync_dir.mkdir(parents=True, exist_ok=False)
            run_a_first_ready = sync_dir / "run-a-first-ready.marker"
            release_run_a = sync_dir / "release-run-a.marker"

            run_a_process = _spawn_python_script_process(
                _ROLLBACK_OWNER_PROCESS_SCRIPT,
                CANONICAL_REGISTRY_REL,
                staging_rel,
                str(run_a_first_ready),
                str(release_run_a),
            )
            _wait_for_path(run_a_first_ready, timeout_seconds=10, description="run A first-artifact marker")
            assert lock_path.exists(), "run A must hold the exact on-disk transaction lock while paused"
            names_before_b = sorted(entry.name for entry in leaf.iterdir())
            assert staged_mod.TRANSACTION_LOCK_NAME in names_before_b
            assert any(name.startswith("v-") for name in names_before_b), "run A must publish v before run B starts"
            assert not any(name.startswith("d-") for name in names_before_b), "run A pause must happen before d"

            run_b_process = _spawn_verify_stage_process(staging_rel)
            try:
                run_b_process.communicate(timeout=6)
            except subprocess.TimeoutExpired:
                pass
            else:
                pytest.fail("run B must remain waiting while run A owns the exact lock and has not released yet")

            assert lock_path.exists(), "run A must continue owning the exact lock during the wait probe"
            assert run_b_process.poll() is None, "run B must remain waiting until run A rolls back and releases"
            assert not any(entry.name.startswith("d-") for entry in leaf.iterdir()), (
                "run B must not publish the second final artifact while run A still owns the lock"
            )

            release_run_a.write_text("release", encoding="utf-8")
            run_a = _collect_process_result(run_a_process, timeout_seconds=10, description="run A rollback owner process")
            _assert_one_line_stdout_zero_stderr(run_a)
            run_a_payload = _parse_json_stdout(run_a)
            assert run_a.returncode == 7
            assert run_a_payload["run_status"] == "FAILED"
            assert run_a_payload["input_validity"] == "VALID"
            assert _error_code(run_a_payload) == "OUTPUT_WRITE_FAILED"
            _assert_exact_error_from_authority(run_a_payload, expected_code="OUTPUT_WRITE_FAILED", expected_exit=7)
            assert run_a_payload["verification_artifact"] is None
            assert run_a_payload["diff_artifact"] is None

            run_b = _collect_process_result(run_b_process, timeout_seconds=10, description="run B plain CLI process")
            _assert_one_line_stdout_zero_stderr(run_b)
            run_b_payload = _parse_json_stdout(run_b)
            assert run_b.returncode == 0
            assert run_b_payload["run_status"] == "COMPLETED"
            assert run_b_payload["input_validity"] == "VALID"
            assert run_b_payload["error"] is None
            run_b_v_path, run_b_d_path = _assert_output_leaf_has_exact_artifacts(run_b_payload, manifest_hash=manifest_hash)
            assert sorted(entry.name for entry in leaf.iterdir()) == sorted([run_b_v_path.name, run_b_d_path.name])
            assert not lock_path.exists(), "exact transaction lock must be removed after both processes finish"
            assert not [entry for entry in leaf.iterdir() if entry.name.startswith(staged_mod.TEMP_ARTIFACT_PREFIX)]
    finally:
        _cleanup_process(run_a_process)
        _cleanup_process(run_b_process)
        if sync_dir is not None:
            _remove_path(sync_dir)
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac12_ac13_fm16_live_exact_transaction_lock_blocks_peer_cli_until_release() -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    lock_path = leaf / staged_mod.TRANSACTION_LOCK_NAME
    _remove_output_leaf(manifest_hash)

    run_a_process: subprocess.Popen[str] | None = None
    run_b_process: subprocess.Popen[str] | None = None
    sync_dir: Path | None = None
    try:
        with _stage_case("s2-fm16-live-lock-wait-real-procs", manifest, files) as (_, staging_rel):
            sync_dir = STAGING_PARENT / f"s2-process-sync-{uuid.uuid4().hex[:12]}"
            sync_dir.mkdir(parents=True, exist_ok=False)
            run_a_lock_ready = sync_dir / "run-a-lock-ready.marker"
            release_run_a = sync_dir / "release-run-a.marker"

            run_a_process = _spawn_python_script_process(
                _LOCK_HOLDER_PROCESS_SCRIPT,
                CANONICAL_REGISTRY_REL,
                staging_rel,
                str(run_a_lock_ready),
                str(release_run_a),
            )
            _wait_for_path(run_a_lock_ready, timeout_seconds=10, description="run A exact-lock-ready marker")
            assert lock_path.exists(), "run A must hold the exact lock before run B starts"
            assert sorted(entry.name for entry in leaf.iterdir()) == [staged_mod.TRANSACTION_LOCK_NAME]

            run_b_process = _spawn_verify_stage_process(staging_rel)
            try:
                run_b_process.communicate(timeout=6)
            except subprocess.TimeoutExpired:
                pass
            else:
                pytest.fail("plain CLI run B must remain waiting while run A keeps the exact lock")

            assert lock_path.exists(), "run A must keep owning the exact lock during the wait probe"
            assert run_b_process.poll() is None, "plain CLI run B must wait while run A holds exact lock"
            assert sorted(entry.name for entry in leaf.iterdir()) == [staged_mod.TRANSACTION_LOCK_NAME], (
                "run B must not publish any partial or final artifacts while run A holds the exact lock"
            )

            release_run_a.write_text("release", encoding="utf-8")
            run_a = _collect_process_result(run_a_process, timeout_seconds=10, description="run A lock holder process")
            _assert_one_line_stdout_zero_stderr(run_a)
            run_a_payload = _parse_json_stdout(run_a)
            assert run_a.returncode == 0
            assert run_a_payload["run_status"] == "COMPLETED"
            assert run_a_payload["input_validity"] == "VALID"
            assert run_a_payload["error"] is None

            run_b = _collect_process_result(run_b_process, timeout_seconds=10, description="run B waiting peer process")
            _assert_one_line_stdout_zero_stderr(run_b)
            run_b_payload = _parse_json_stdout(run_b)
            assert run_b.returncode == 0
            assert run_b_payload["run_status"] == "COMPLETED"
            assert run_b_payload["input_validity"] == "VALID"
            assert run_b_payload["error"] is None
            run_b_v_path, run_b_d_path = _assert_output_leaf_has_exact_artifacts(run_b_payload, manifest_hash=manifest_hash)
            assert sorted(entry.name for entry in leaf.iterdir()) == sorted([run_b_v_path.name, run_b_d_path.name])
            assert not lock_path.exists(), "exact lock must not persist after successful publication"
            assert not [entry for entry in leaf.iterdir() if entry.name.startswith(staged_mod.TEMP_ARTIFACT_PREFIX)]
    finally:
        _cleanup_process(run_a_process)
        _cleanup_process(run_b_process)
        if sync_dir is not None:
            _remove_path(sync_dir)
        _remove_output_leaf(manifest_hash)


@pytest.mark.parametrize(
    "case_id,foreign_lock_bytes",
    [
        ("invalid-foreign-bytes", b"\xff\x00foreign-exact-lock-bytes\xfd"),
        ("dead-owner-metadata", b'{"pid":999999,"token":"dead-owner","state":"orphaned"}\n'),
    ],
    ids=["invalid-foreign-bytes", "dead-owner-metadata"],
)
def test_v2s2_ac12_ac13_fm16_exact_transaction_lock_orphan_or_foreign_bytes_fail_closed_and_preserved(
    case_id: str,
    foreign_lock_bytes: bytes,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    lock_path = leaf / staged_mod.TRANSACTION_LOCK_NAME
    _remove_output_leaf(manifest_hash)
    leaf.mkdir(parents=True, exist_ok=False)
    lock_path.write_bytes(foreign_lock_bytes)
    try:
        with _stage_case(f"s2-fm16-exact-lock-{case_id}", manifest, files) as (_, staging_rel):
            result = _run_verify_stage(staging_rel, timeout=12)
        _assert_one_line_stdout_zero_stderr(result)
        report = _parse_json_stdout(result)
        assert result.returncode == 7
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "VALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        code = _error_code(report)
        assert code in {"OUTPUT_COLLISION", "OUTPUT_WRITE_FAILED"}
        assert code != "INTERNAL_ERROR"
        assert isinstance(code, str)
        _assert_exact_error_from_authority(report, expected_code=code, expected_exit=7)
        assert lock_path.exists(), "exact lock must be preserved on fail-closed orphan/foreign probes"
        assert lock_path.read_bytes() == foreign_lock_bytes
        assert sorted(entry.name for entry in leaf.iterdir()) == [staged_mod.TRANSACTION_LOCK_NAME]
        assert not [entry for entry in leaf.iterdir() if entry.name.startswith(staged_mod.TEMP_ARTIFACT_PREFIX)]
    finally:
        _remove_output_leaf(manifest_hash)


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGKILL orphan-lock probe for V2S2-FM16")
def test_v2s2_ac12_ac13_fm16_sigkill_orphan_exact_transaction_lock_fails_closed() -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    lock_path = leaf / staged_mod.TRANSACTION_LOCK_NAME
    _remove_output_leaf(manifest_hash)

    run_a_process: subprocess.Popen[str] | None = None
    orphan_lock_bytes: bytes | None = None
    sync_dir: Path | None = None
    try:
        with _stage_case("s2-fm16-sigkill-orphan-exact-lock", manifest, files) as (_, staging_rel):
            sync_dir = STAGING_PARENT / f"s2-process-sync-{uuid.uuid4().hex[:12]}"
            sync_dir.mkdir(parents=True, exist_ok=False)
            run_a_lock_ready = sync_dir / "run-a-lock-ready.marker"
            run_a_process = _spawn_python_script_process(
                _ORPHAN_LOCK_OWNER_PROCESS_SCRIPT,
                CANONICAL_REGISTRY_REL,
                staging_rel,
                str(run_a_lock_ready),
            )
            _wait_for_path(run_a_lock_ready, timeout_seconds=10, description="run A exact-lock-ready marker before SIGKILL")
            assert lock_path.exists(), "run A must create the exact lock before SIGKILL"
            orphan_lock_bytes = lock_path.read_bytes()

            os.kill(run_a_process.pid, signal.SIGKILL)
            run_a = _collect_process_result(run_a_process, timeout_seconds=5, description="run A SIGKILL orphan owner")
            assert run_a.returncode != 0

            result = _run_verify_stage(staging_rel, timeout=12)

        _assert_one_line_stdout_zero_stderr(result)
        report = _parse_json_stdout(result)
        assert result.returncode == 7
        assert report["run_status"] == "FAILED"
        assert report["input_validity"] == "VALID"
        assert report["verification_artifact"] is None
        assert report["diff_artifact"] is None
        code = _error_code(report)
        assert code in {"OUTPUT_COLLISION", "OUTPUT_WRITE_FAILED"}
        assert code != "INTERNAL_ERROR"
        assert isinstance(code, str)
        _assert_exact_error_from_authority(report, expected_code=code, expected_exit=7)
        assert orphan_lock_bytes is not None
        assert lock_path.exists(), "SIGKILL orphan exact lock must be preserved on bounded fail-closed result"
        assert lock_path.read_bytes() == orphan_lock_bytes
        assert sorted(entry.name for entry in leaf.iterdir()) == [staged_mod.TRANSACTION_LOCK_NAME]
        assert not [entry for entry in leaf.iterdir() if entry.name.startswith(staged_mod.TEMP_ARTIFACT_PREFIX)]
    finally:
        _cleanup_process(run_a_process)
        if sync_dir is not None:
            _remove_path(sync_dir)
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac02_ac06_initial_malformed_registry_yaml_maps_to_baseline_registry_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _temporary_canonical_registry(monkeypatch, staged_mod, raw_bytes=b"schema: [\n") as (temp_rel, _):
            with _stage_case("s2-bl11-initial-registry-malformed", manifest, files) as (_, staging_rel):
                code, payload = staged_mod.verify_stage(temp_rel, staging_rel)
        assert code == 6
        _assert_baseline_registry_invalid_no_artifacts(payload)
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac02_ac06_initial_nonutf8_registry_maps_to_baseline_registry_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _temporary_canonical_registry(monkeypatch, staged_mod, raw_bytes=b"\xff\xfe\x00\xfd") as (temp_rel, _):
            with _stage_case("s2-bl11-initial-registry-nonutf8", manifest, files) as (_, staging_rel):
                code, payload = staged_mod.verify_stage(temp_rel, staging_rel)
        assert code == 6
        _assert_baseline_registry_invalid_no_artifacts(payload)
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac02_ac06_initial_wrong_typed_registry_maps_to_baseline_registry_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _temporary_canonical_registry(monkeypatch, staged_mod, raw_bytes=b"- wrong\n- typed\n- registry\n") as (temp_rel, _):
            with _stage_case("s2-bl11-initial-registry-wrong-typed", manifest, files) as (_, staging_rel):
                code, payload = staged_mod.verify_stage(temp_rel, staging_rel)
        assert code == 6
        _assert_baseline_registry_invalid_no_artifacts(payload)
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac06_ac07_fm10b_mid_run_registry_malformed_yaml_maps_to_baseline_changed_during_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    manifest["source_binding"]["registry_content_hash"] = _load_registry()["registry_content_hash"]
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    mutated = {"value": False}
    try:
        with _temporary_canonical_registry(monkeypatch, staged_mod, raw_bytes=REGISTRY_PATH.read_bytes()) as (temp_rel, temp_path):
            real_build_verification = staged_mod._build_verification_artifact

            def _mutating_build_verification(*args: Any, **kwargs: Any) -> dict[str, Any]:
                if not mutated["value"]:
                    temp_path.write_bytes(b"schema: [\n")
                    mutated["value"] = True
                return real_build_verification(*args, **kwargs)

            monkeypatch.setattr(staged_mod, "_build_verification_artifact", _mutating_build_verification, raising=True)
            with _stage_case("s2-bl11-midrun-registry-malformed", manifest, files) as (_, staging_rel):
                code, payload = staged_mod.verify_stage(temp_rel, staging_rel)
        assert mutated["value"] is True
        assert code == 6
        _assert_baseline_changed_no_artifacts(payload)
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac06_ac07_fm10b_mid_run_registry_nonutf8_maps_to_baseline_changed_during_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest = copy.deepcopy(manifest)
    manifest["source_binding"]["registry_content_hash"] = _load_registry()["registry_content_hash"]
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    mutated = {"value": False}
    try:
        with _temporary_canonical_registry(monkeypatch, staged_mod, raw_bytes=REGISTRY_PATH.read_bytes()) as (temp_rel, temp_path):
            real_build_verification = staged_mod._build_verification_artifact

            def _mutating_build_verification(*args: Any, **kwargs: Any) -> dict[str, Any]:
                if not mutated["value"]:
                    temp_path.write_bytes(b"\xff\xfe\x00\xfd")
                    mutated["value"] = True
                return real_build_verification(*args, **kwargs)

            monkeypatch.setattr(staged_mod, "_build_verification_artifact", _mutating_build_verification, raising=True)
            with _stage_case("s2-bl11-midrun-registry-nonutf8", manifest, files) as (_, staging_rel):
                code, payload = staged_mod.verify_stage(temp_rel, staging_rel)
        assert mutated["value"] is True
        assert code == 6
        _assert_baseline_changed_no_artifacts(payload)
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac06_ac07_bl11_baseline_passes_use_public_load_registry_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    load_calls: list[str] = []
    real_load_registry = staged_mod.load_registry

    def _tracking_load_registry(path: str | os.PathLike[str]) -> Any:
        load_calls.append(str(path))
        return real_load_registry(path)

    monkeypatch.setattr(staged_mod, "load_registry", _tracking_load_registry, raising=True)
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case("s2-bl11-load-registry-two-pass", manifest, files) as (_, staging_rel):
            code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert code == 0
        assert payload["run_status"] == "COMPLETED"
        assert payload["input_validity"] == "VALID"
        assert payload["error"] is None
        assert len(load_calls) >= 2, "both baseline passes must use the public V2-S1 load_registry loader"
        _assert_output_leaf_has_exact_artifacts(payload, manifest_hash=manifest_hash)
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_ac06_bl11_first_pass_public_loader_failure_is_mapped_to_baseline_registry_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib
    from raptor.sourceops.model import RegistrySchemaError

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    snapshot_calls = {"value": 0}
    load_calls = {"value": 0}
    real_snapshot_stage_tree = staged_mod._snapshot_stage_tree

    def _failing_load_registry(_path: str | os.PathLike[str]) -> Any:
        load_calls["value"] += 1
        raise RegistrySchemaError("synthetic malformed registry from public loader")

    def _counting_snapshot(stage_root: Path) -> dict[str, Any]:
        snapshot_calls["value"] += 1
        return real_snapshot_stage_tree(stage_root)

    monkeypatch.setattr(staged_mod, "load_registry", _failing_load_registry, raising=True)
    monkeypatch.setattr(staged_mod, "_snapshot_stage_tree", _counting_snapshot, raising=True)
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case("s2-bl11-first-pass-loader-failure", manifest, files) as (_, staging_rel):
            code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_rel)
        assert load_calls["value"] >= 1
        assert snapshot_calls["value"] == 0, "first-pass baseline loader failure must occur before any staging snapshot"
        assert code == 6
        _assert_baseline_registry_invalid_no_artifacts(payload)
        assert not (OUTPUT_PARENT / manifest_hash).exists()
    finally:
        _remove_output_leaf(manifest_hash)
