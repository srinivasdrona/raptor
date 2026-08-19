from __future__ import annotations

import copy
import functools
import hashlib
import json
import os
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


def _run_cli_bytes(*args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=False,
        env=env,
    )


def _run_verify_stage(staging_root_rel: str, *, registry_rel: str = CANONICAL_REGISTRY_REL) -> subprocess.CompletedProcess[str]:
    return _run_cli("verify-stage", "--registry", registry_rel, "--staging-root", staging_root_rel)


def _parse_json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if not result.stdout.strip():
        pytest.fail(
            "verify-stage must emit one deterministic JSON object to stdout.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        pytest.fail("stdout payload must be a JSON object")
    return payload


def _assert_one_line_stdout_zero_stderr(result: subprocess.CompletedProcess[str]) -> None:
    assert result.stdout.endswith("\n"), "stdout must end with one LF"
    assert result.stdout.count("\n") == 1, "stdout must contain exactly one JSON object line"
    assert result.stderr == "", f"stderr must be empty, got {result.stderr!r}"


def _error_code(report: dict[str, Any]) -> str | None:
    err = report.get("error")
    if isinstance(err, dict) and isinstance(err.get("code"), str):
        return err["code"]
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
    required = set(_spec()["error_contract"]["error_envelope_required_exact"])
    assert set(error) == required
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
    assert set(report) == set(_spec()["cli_contract"]["stdout"]["top_level_required_exact"])
    assert report["schema"] == _spec()["cli_contract"]["stdout"]["schema_id"]
    assert report["command"] == "verify-stage"
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == expected_input_validity
    assert report["stage_outcome"] is None
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
        pytest.fail("registry source_records must be a list")
    for row in records:
        if isinstance(row, dict) and row.get("source_id") == source_id:
            return copy.deepcopy(row)
    pytest.fail(f"source_id missing from registry: {source_id!r}")


def _base_manifest_and_files() -> tuple[dict[str, Any], dict[str, bytes]]:
    registry = _load_registry()
    source = _source_record(registry, "tsc-ingest-and-reference-declarations")
    decl_bytes = (REPO_ROOT / "configs" / "ingest" / "tsc.yaml").read_bytes()
    candidate = {
        "snapshot_id": "candidate-cli-base-001",
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
    }
    files = [
        {
            "file_id": "decl-tsc-yaml",
            "path": "candidate/ingest/tsc.yaml",
            "role": "CANDIDATE_DECLARATION",
            "media_type": "application/x-yaml",
            "checksum": _canonical_lf_checksum(decl_bytes),
            "component_ids": [],
        }
    ]
    bindings = [
        {
            "binding_id": "bind-declaration",
            "baseline_kind": "DECLARATION_REF",
            "baseline_id": source["declaration_refs"][0]["path"],
            "candidate_file_id": "decl-tsc-yaml",
        }
    ]
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
        "candidate": candidate,
        "files": files,
        "content_bindings": bindings,
        "component_projection": None,
    }
    manifest["manifest_content_hash"] = _canonical_manifest_hash(manifest)
    return manifest, {"candidate/ingest/tsc.yaml": decl_bytes}


@contextmanager
def _stage_case(
    *,
    prefix: str,
    manifest: dict[str, Any],
    files: dict[str, bytes],
) -> Iterator[str]:
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
        yield f".raptor/sourceops/staging/{stage_name}"
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


def test_cleanup_helper_removes_directory_file_and_symlink_leaves_without_touching_target() -> None:
    probe_root = REPO_ROOT / ".raptor" / "sourceops" / f"s2-cleanup-probe-{uuid.uuid4().hex[:10]}"
    probe_root.mkdir(parents=True, exist_ok=False)
    target_dir = probe_root / "target"
    target_dir.mkdir(parents=False, exist_ok=False)
    target_payload = target_dir / "payload.txt"
    target_payload.write_text("preserve", encoding="utf-8")
    dir_leaf = probe_root / "dir-leaf"
    (dir_leaf / "nested").mkdir(parents=True, exist_ok=False)
    (dir_leaf / "nested" / "probe.txt").write_text("probe", encoding="utf-8")
    file_leaf = probe_root / "file-leaf.txt"
    file_leaf.write_text("leaf", encoding="utf-8")
    symlink_leaf = probe_root / "symlink-leaf"
    dangling_leaf = probe_root / "dangling-leaf"
    try:
        symlink_leaf.symlink_to(target_dir, target_is_directory=True)
        dangling_leaf.symlink_to(probe_root / "missing-target", target_is_directory=True)
    except (NotImplementedError, OSError):
        _remove_path(probe_root)
        pytest.skip("symlink creation unavailable for cleanup helper probe")

    try:
        _remove_path(dir_leaf)
        _remove_path(file_leaf)
        _remove_path(symlink_leaf)
        _remove_path(dangling_leaf)

        assert not dir_leaf.exists()
        assert not file_leaf.exists()
        assert not symlink_leaf.exists() and not symlink_leaf.is_symlink()
        assert not dangling_leaf.exists() and not dangling_leaf.is_symlink()
        assert target_dir.exists()
        assert target_payload.read_text(encoding="utf-8") == "preserve"
    finally:
        _remove_path(probe_root)


def test_verify_stage_help_surface_and_validate_status_compatibility_baseline() -> None:
    help_result = _run_cli("--help")
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    assert "verify-stage" in help_text, "verify-stage must be present as the sole new CLI command"
    assert "validate" in help_text and "status" in help_text

    validate = _run_cli("validate", "--registry", CANONICAL_REGISTRY_REL)
    status = _run_cli("status", "--registry", CANONICAL_REGISTRY_REL, "--consumer", "eval-gate")
    assert validate.returncode == 0, validate.stderr or validate.stdout
    assert status.returncode == 0, status.stderr or status.stdout
    assert validate.stderr == ""
    assert status.stderr == ""


@pytest.mark.parametrize(
    "args",
    [
        ("verify-stage",),
        ("verify-stage", "--registry", CANONICAL_REGISTRY_REL),
        ("verify-stage", "--registry", CANONICAL_REGISTRY_REL, "--staging-root", ".raptor/sourceops/staging/demo", "--output", "x"),
        ("verify-stage", "--registry", CANONICAL_REGISTRY_REL, "--staging-root", ".raptor/sourceops/staging/demo", "--consumer", "eval-gate"),
        ("verify-stage", "--registry", CANONICAL_REGISTRY_REL, "--staging-root", ".raptor/sourceops/staging/demo", "--unknown", "x"),
    ],
    ids=[
        "missing-required-args",
        "missing-staging-root",
        "forbidden-output-arg",
        "forbidden-consumer-arg",
        "unknown-arg",
    ],
)
def test_verify_stage_usage_failures_are_closed_json_with_exit_2(args: tuple[str, ...]) -> None:
    result = _run_cli(*args)
    _assert_one_line_stdout_zero_stderr(result)
    assert result.returncode == 2
    report = _parse_json_stdout(result)
    assert report["schema"] == _spec()["cli_contract"]["stdout"]["schema_id"]
    assert report["command"] == "verify-stage"
    assert report["run_status"] == "FAILED"
    assert report["input_validity"] == "NOT_EVALUATED"
    assert report["stage_outcome"] is None
    assert report["verification_artifact"] is None
    assert report["diff_artifact"] is None
    assert _error_code(report) == "CLI_USAGE_ERROR"


@pytest.mark.parametrize("staging_root", ["", " ", "\t"], ids=["empty", "space", "tab"])
def test_v2s2_ac03_ac13_fm01_fm12_staging_root_empty_or_whitespace_emits_catalog_error(staging_root: str) -> None:
    result = _run_cli(
        "verify-stage",
        "--registry",
        CANONICAL_REGISTRY_REL,
        "--staging-root",
        staging_root,
    )
    report = _assert_exact_failure(
        result,
        expected_code="STAGING_ROOT_INVALID",
        expected_exit=2,
        expected_input_validity="INVALID",
    )
    assert report["source_id"] is None
    assert report["registry_content_hash"] is None
    assert report["manifest_content_hash"] is None


def test_verify_stage_exit_partition_unknown_source_vs_hash_vs_binding_mismatch() -> None:
    base_manifest, files = _base_manifest_and_files()

    unknown_source = copy.deepcopy(base_manifest)
    unknown_source["source_binding"]["source_id"] = "source-id-not-present-in-registry"
    unknown_source["manifest_content_hash"] = _canonical_manifest_hash(unknown_source)
    with _stage_case(prefix="s2-cli-unknown-source", manifest=unknown_source, files=files) as staging_root:
        unknown_result = _run_verify_stage(staging_root)
    _assert_one_line_stdout_zero_stderr(unknown_result)
    unknown_report = _parse_json_stdout(unknown_result)
    assert unknown_result.returncode == 4
    assert _error_code(unknown_report) == "UNKNOWN_SOURCE"

    hash_mismatch = copy.deepcopy(base_manifest)
    hash_mismatch["source_binding"]["registry_content_hash"] = "f" * 64
    hash_mismatch["manifest_content_hash"] = _canonical_manifest_hash(hash_mismatch)
    with _stage_case(prefix="s2-cli-hash-mismatch", manifest=hash_mismatch, files=files) as staging_root:
        mismatch_result = _run_verify_stage(staging_root)
    _assert_one_line_stdout_zero_stderr(mismatch_result)
    mismatch_report = _parse_json_stdout(mismatch_result)
    assert mismatch_result.returncode == 5
    assert _error_code(mismatch_report) == "BASELINE_REGISTRY_HASH_MISMATCH"

    binding_mismatch = copy.deepcopy(base_manifest)
    declaration_refs = copy.deepcopy(binding_mismatch["source_binding"]["declaration_refs"])
    declaration_refs[0]["role"] = f"{declaration_refs[0]['role']}-mismatch"
    binding_mismatch["source_binding"]["declaration_refs"] = declaration_refs
    binding_mismatch["manifest_content_hash"] = _canonical_manifest_hash(binding_mismatch)
    with _stage_case(prefix="s2-cli-binding-mismatch", manifest=binding_mismatch, files=files) as staging_root:
        binding_result = _run_verify_stage(staging_root)
    _assert_one_line_stdout_zero_stderr(binding_result)
    binding_report = _parse_json_stdout(binding_result)
    assert binding_result.returncode == 5
    assert _error_code(binding_report) == "BASELINE_DECLARATION_BINDING_MISMATCH"


def test_verify_stage_exit_partition_baseline_path_invalid_input_invalid_and_output_collision() -> None:
    base_manifest, files = _base_manifest_and_files()
    manifest_hash = base_manifest["manifest_content_hash"]
    expected_output_subject = f".raptor/sourceops/generated/staged-snapshots/{manifest_hash}"
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-cli-boundary", manifest=base_manifest, files=files) as staging_root:
            baseline_path_result = _run_verify_stage(staging_root, registry_rel="configs/sourceops/not-canonical.yaml")
            _assert_one_line_stdout_zero_stderr(baseline_path_result)
            baseline_path_report = _parse_json_stdout(baseline_path_result)
            assert baseline_path_result.returncode == 6
            assert _error_code(baseline_path_report) == "BASELINE_REGISTRY_PATH_INVALID"
            assert baseline_path_report["input_validity"] == "NOT_EVALUATED"

            invalid_manifest = copy.deepcopy(base_manifest)
            invalid_manifest["manifest_content_hash"] = "0" * 64
            with _stage_case(prefix="s2-cli-invalid", manifest=invalid_manifest, files=files) as invalid_root:
                invalid_result = _run_verify_stage(invalid_root)
            _assert_one_line_stdout_zero_stderr(invalid_result)
            invalid_report = _parse_json_stdout(invalid_result)
            assert invalid_result.returncode == 2
            assert _error_code(invalid_report) == "STAGING_MANIFEST_HASH_MISMATCH"
            assert invalid_report["input_validity"] == "INVALID"
            assert invalid_report["verification_artifact"] is None
            assert invalid_report["diff_artifact"] is None

            collision_leaf = OUTPUT_PARENT / manifest_hash
            collision_leaf.mkdir(parents=True, exist_ok=True)
            (collision_leaf / "unexpected.txt").write_text("collision", encoding="utf-8")
            collision_result = _run_verify_stage(staging_root)
            _assert_one_line_stdout_zero_stderr(collision_result)
            collision_report = _parse_json_stdout(collision_result)
            assert collision_result.returncode == 7
            assert _error_code(collision_report) == "OUTPUT_COLLISION"
            collision_error = _assert_exact_error_from_authority(
                collision_report,
                expected_code="OUTPUT_COLLISION",
                expected_exit=7,
            )
            _assert_path_subject_forward_slash(collision_error, expected=expected_output_subject)
            _assert_no_backslash_for_path_subject(collision_report)
            assert collision_report["input_validity"] == "VALID"
            assert collision_report["stage_outcome"] in {"OBSERVED_NO_DIFFERENCE", "OBSERVED_DIFFERENCE"}
            assert collision_report["verification_artifact"] is None
            assert collision_report["diff_artifact"] is None

            _remove_path(collision_leaf)
            collision_leaf.write_text("not-a-directory", encoding="utf-8")
            boundary_result = _run_verify_stage(staging_root)
            _assert_one_line_stdout_zero_stderr(boundary_result)
            boundary_report = _parse_json_stdout(boundary_result)
            assert boundary_result.returncode == 7
            assert _error_code(boundary_report) == "OUTPUT_BOUNDARY_INVALID"
            boundary_error = _assert_exact_error_from_authority(
                boundary_report,
                expected_code="OUTPUT_BOUNDARY_INVALID",
                expected_exit=7,
            )
            _assert_path_subject_forward_slash(boundary_error, expected=expected_output_subject)
            _assert_no_backslash_for_path_subject(boundary_report)
            assert boundary_report["input_validity"] == "VALID"
            assert boundary_report["stage_outcome"] in {"OBSERVED_NO_DIFFERENCE", "OBSERVED_DIFFERENCE"}
            assert boundary_report["verification_artifact"] is None
            assert boundary_report["diff_artifact"] is None
    finally:
        _remove_output_leaf(manifest_hash)


def test_verify_stage_success_stdout_schema_and_exit_never_3() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-cli-success", manifest=manifest, files=files) as staging_root:
            success = _run_verify_stage(staging_root)
        _assert_one_line_stdout_zero_stderr(success)
        assert success.returncode == 0
        report = _parse_json_stdout(success)
        assert set(report) == set(_spec()["cli_contract"]["stdout"]["top_level_required_exact"])
        assert report["schema"] == _spec()["cli_contract"]["stdout"]["schema_id"]
        assert report["command"] == "verify-stage"
        assert report["run_status"] == "COMPLETED"
        assert report["input_validity"] == "VALID"
        assert report["stage_outcome"] in {"OBSERVED_NO_DIFFERENCE", "OBSERVED_DIFFERENCE"}
        assert report["error"] is None
        assert success.returncode != 3, "verify-stage must never emit exit 3"
    finally:
        _remove_output_leaf(manifest_hash)


def test_verify_stage_stdout_determinism_and_validate_status_compatibility_after_run() -> None:
    validate_before = _run_cli("validate", "--registry", CANONICAL_REGISTRY_REL)
    status_before = _run_cli("status", "--registry", CANONICAL_REGISTRY_REL, "--consumer", "eval-gate")
    assert validate_before.returncode == 0, validate_before.stderr or validate_before.stdout
    assert status_before.returncode == 0, status_before.stderr or status_before.stdout

    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-cli-repeat", manifest=manifest, files=files) as staging_root:
            first = _run_verify_stage(staging_root)
            second = _run_verify_stage(staging_root)
        _assert_one_line_stdout_zero_stderr(first)
        _assert_one_line_stdout_zero_stderr(second)
        assert first.returncode == 0
        assert second.returncode == 0
        assert first.stdout == second.stdout, "verify-stage identical reruns must have deterministic stdout"
    finally:
        _remove_output_leaf(manifest_hash)

    validate_after = _run_cli("validate", "--registry", CANONICAL_REGISTRY_REL)
    status_after = _run_cli("status", "--registry", CANONICAL_REGISTRY_REL, "--consumer", "eval-gate")
    assert validate_after.returncode == 0, validate_after.stderr or validate_after.stdout
    assert status_after.returncode == 0, status_after.stderr or status_after.stdout
    assert validate_before.stdout == validate_after.stdout, "validate output must remain byte-identical"
    assert status_before.stdout == status_after.stdout, "status output must remain byte-identical"


def test_verify_stage_internal_error_boundary_maps_to_exit_70(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import importlib

    cli_mod = importlib.import_module("raptor.sourceops.cli")
    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("synthetic unhandled verify-stage failure")

    patched = False
    if hasattr(staged_mod, "verify_stage"):
        monkeypatch.setattr(staged_mod, "verify_stage", _boom, raising=True)
        patched = True
    if hasattr(cli_mod, "verify_stage"):
        monkeypatch.setattr(cli_mod, "verify_stage", _boom, raising=True)
        patched = True
    assert patched, "verify_stage public operation must be patchable for INTERNAL_ERROR boundary test"

    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-cli-internal", manifest=manifest, files=files) as staging_root:
            code = cli_mod.main(["verify-stage", "--registry", CANONICAL_REGISTRY_REL, "--staging-root", staging_root])
        out = capsys.readouterr()
        assert out.err == ""
        assert code == 70
        payload = json.loads(out.out)
        assert payload["run_status"] == "FAILED"
        assert payload["input_validity"] == "NOT_EVALUATED"
        assert _error_code(payload) == "INTERNAL_ERROR"
    finally:
        _remove_output_leaf(manifest_hash)


def test_verify_stage_exit_code_partition_never_uses_3() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-cli-exit-partition", manifest=manifest, files=files) as staging_root:
            success = _run_verify_stage(staging_root)
            invalid_manifest = copy.deepcopy(manifest)
            invalid_manifest["manifest_content_hash"] = "0" * 64
            with _stage_case(prefix="s2-cli-exit-invalid", manifest=invalid_manifest, files=files) as invalid_root:
                invalid = _run_verify_stage(invalid_root)
            unknown_source = copy.deepcopy(manifest)
            unknown_source["source_binding"]["source_id"] = "unknown-source-id"
            unknown_source["manifest_content_hash"] = _canonical_manifest_hash(unknown_source)
            with _stage_case(prefix="s2-cli-exit-unknown", manifest=unknown_source, files=files) as unknown_root:
                unknown = _run_verify_stage(unknown_root)
        for result in (success, invalid, unknown):
            assert result.returncode in {0, 2, 4, 5, 6, 7, 70}
            assert result.returncode != 3, "verify-stage must never return exit code 3"
    finally:
        _remove_output_leaf(manifest_hash)


def _assert_stdout_bytes_one_lf_and_empty_stderr(result: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    assert result.stderr == b"", f"stderr must be exactly empty bytes, got: {result.stderr!r}"
    assert result.stdout.endswith(b"\n"), "stdout must end with exactly one LF byte"
    assert not result.stdout.endswith(b"\r\n"), "stdout must not end with CRLF"
    assert result.stdout.count(b"\n") == 1, "stdout must contain exactly one JSON line"
    decoded = result.stdout.decode("utf-8")
    payload = json.loads(decoded)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    assert decoded == canonical, "stdout JSON must already be canonical and single-line"
    assert isinstance(payload, dict)
    return payload


def test_v2s2_ac10_ac11_ac13_fm12_stdout_bytes_contract_holds_on_success_and_failure() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-cli-bytes-success", manifest=manifest, files=files) as staging_root:
            success = _run_cli_bytes("verify-stage", "--registry", CANONICAL_REGISTRY_REL, "--staging-root", staging_root)
        assert success.returncode == 0, success.stdout.decode("utf-8", errors="replace")
        success_payload = _assert_stdout_bytes_one_lf_and_empty_stderr(success)
        assert success_payload["run_status"] == "COMPLETED"
        assert success_payload["error"] is None
    finally:
        _remove_output_leaf(manifest_hash)

    failure = _run_cli_bytes("verify-stage", "--registry", CANONICAL_REGISTRY_REL)
    assert failure.returncode == 2
    failure_payload = _assert_stdout_bytes_one_lf_and_empty_stderr(failure)
    assert failure_payload["run_status"] == "FAILED"
    assert _error_code(failure_payload) == "CLI_USAGE_ERROR"


def test_v2s2_b13_output_failure_payload_retains_known_manifest_and_registry_hashes() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    leaf = OUTPUT_PARENT / manifest_hash
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-cli-hash-fields", manifest=manifest, files=files) as staging_root:
            leaf.mkdir(parents=True, exist_ok=True)
            (leaf / "unexpected.txt").write_text("collision", encoding="utf-8")
            result = _run_verify_stage(staging_root)
        _assert_one_line_stdout_zero_stderr(result)
        report = _parse_json_stdout(result)
        assert result.returncode == 7
        assert _error_code(report) == "OUTPUT_COLLISION"
        assert report["manifest_content_hash"] == manifest_hash
        assert report["registry_content_hash"] == manifest["source_binding"]["registry_content_hash"]
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_fm09_timezone_locale_mtime_and_command_time_do_not_change_stdout_bytes() -> None:
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)
    try:
        with _stage_case(prefix="s2-cli-fm09", manifest=manifest, files=files) as staging_root:
            first = _run_cli_bytes(
                "verify-stage",
                "--registry",
                CANONICAL_REGISTRY_REL,
                "--staging-root",
                staging_root,
                env_overrides={"TZ": "UTC", "LC_ALL": "C"},
            )
            candidate_file = REPO_ROOT / Path(staging_root.replace("/", os.sep)) / "candidate" / "ingest" / "tsc.yaml"
            stat_before = candidate_file.stat()
            os.utime(candidate_file, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns + 5_000_000))
            second = _run_cli_bytes(
                "verify-stage",
                "--registry",
                CANONICAL_REGISTRY_REL,
                "--staging-root",
                staging_root,
                env_overrides={"TZ": "Pacific/Auckland", "LC_ALL": "en_US.UTF-8"},
            )
        assert first.returncode == 0
        assert second.returncode == 0
        _assert_stdout_bytes_one_lf_and_empty_stderr(first)
        _assert_stdout_bytes_one_lf_and_empty_stderr(second)
        assert first.stdout == second.stdout, "stdout bytes must be deterministic across locale/timezone/mtime/command-time perturbations"
    finally:
        _remove_output_leaf(manifest_hash)


def test_v2s2_b13_output_writer_race_maps_to_exit_7_not_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    staged_mod = importlib.import_module("raptor.sourceops.staged_snapshot")
    manifest, files = _base_manifest_and_files()
    manifest_hash = manifest["manifest_content_hash"]
    _remove_output_leaf(manifest_hash)

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("synthetic concurrent writer race")

    monkeypatch.setattr(staged_mod, "_write_atomic_json", _boom, raising=True)
    try:
        with _stage_case(prefix="s2-cli-race", manifest=manifest, files=files) as staging_root:
            code, payload = staged_mod.verify_stage(CANONICAL_REGISTRY_REL, staging_root)
    finally:
        _remove_output_leaf(manifest_hash)
    assert code == 7
    assert payload["run_status"] == "FAILED"
    assert _error_code(payload) == "OUTPUT_WRITE_FAILED"
