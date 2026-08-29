from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_SOURCE_PATH = REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v2.yaml"
BASE_CONFIG_SOURCE_PATH = REPO_ROOT / "configs" / "eval" / "tsc2.yaml"
HISTORICAL_BLOCKED_PATH = REPO_ROOT / "data" / "census" / "tsc_prospective_validation_2026-08_blocked_data.json"

try:
    import raptor.eval.prospective_freeze as _prospective_freeze
except ImportError:
    _prospective_freeze = None


def require_module() -> Any:
    if _prospective_freeze is None:
        pytest.fail("RED: missing planned implementation module raptor.eval.prospective_freeze", pytrace=False)
    return _prospective_freeze


def require_api(name: str) -> Any:
    module = require_module()
    if not hasattr(module, name):
        pytest.fail(f"RED: missing planned API raptor.eval.prospective_freeze.{name}", pytrace=False)
    return getattr(module, name)


def require_exception(name: str) -> type[BaseException]:
    cls = require_api(name)
    if not isinstance(cls, type) or not issubclass(cls, BaseException):
        pytest.fail(f"contract breach: {name} must be an exception class")
    return cls


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def md5_hex(raw: bytes) -> str:
    return hashlib.md5(raw).hexdigest()


def canonical_lf_bytes(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def canonical_lf_sha256_path(path: Path) -> str:
    return sha256_hex(canonical_lf_bytes(path.read_bytes()))


def git_blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("utf-8") + b"\0" + raw).hexdigest()


def canonical_json_content_hash(payload: dict[str, Any], *, key: str = "content_hash") -> str:
    basis = copy.deepcopy(payload)
    basis.pop(key, None)
    canonical = json.dumps(
        basis,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256_hex(canonical)


def load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail(f"expected YAML mapping at {path}")
    return loaded


def _replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        pytest.fail(f"expected exactly one replacement for {old!r}, observed {count}")
    return text.replace(old, new, 1)


def default_archive_bytes() -> bytes:
    sink = io.BytesIO()
    with gzip.GzipFile(fileobj=sink, mode="wb") as gz:
        gz.write(b"VariationID\tGeneSymbol\tAssembly\tClinicalSignificance\n")
        gz.write(b"1\tTSC2\tGRCh38\tPathogenic\n")
    return sink.getvalue()


def iso_utc_to_http_date(iso_value: str) -> str:
    dt = datetime.fromisoformat(iso_value.replace("Z", "+00:00")).astimezone(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def projection_sha256_excluding_labels_snapshot(eval_config: dict[str, Any]) -> str:
    basis = copy.deepcopy(eval_config)
    basis.pop("labels_snapshot", None)
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256_hex(canonical)


@dataclass(frozen=True)
class ProspectiveSandbox:
    root: Path
    repo_root: Path
    external_root: Path
    spec_path: Path
    overlay_path: Path
    base_eval_config_path: Path
    transport_record_path: Path
    raw_record_path: Path
    spec: dict[str, Any]
    overlay: dict[str, Any]
    archive_bytes: bytes

    @property
    def exact_url(self) -> str:
        return str(self.spec["dataset_registration"]["exact_url"])

    @property
    def required_final_url(self) -> str:
        return str(self.spec["dataset_registration"]["required_final_url"])


def _overlay_text(required_values: dict[str, Any]) -> str:
    ordered_keys = (
        "schema",
        "registration_id",
        "base_config_path",
        "base_config_canonical_lf_sha256",
        "base_scoring_semantics_projection_sha256",
        "effective_labels_snapshot",
        "exact_archive_url",
        "transport_freeze_record",
        "raw_freeze_record",
    )
    lines = []
    for key in ordered_keys:
        if key not in required_values:
            pytest.fail(f"required overlay key missing from spec: {key}")
        value = required_values[key]
        if isinstance(value, str):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


@contextmanager
def prospective_sandbox(name: str, *, archive_bytes: bytes | None = None) -> Iterator[ProspectiveSandbox]:
    archive = archive_bytes if archive_bytes is not None else default_archive_bytes()
    root = REPO_ROOT / ".raptor" / "pytest-red" / f"{name}-{uuid.uuid4().hex}"
    repo_root = root / "repo"
    external_root = root / "external-content-root"
    spec_path = repo_root / "docs" / "project" / "specs" / SPEC_SOURCE_PATH.name
    base_eval_config_path = repo_root / "configs" / "eval" / "tsc2.yaml"
    root.mkdir(parents=True, exist_ok=False)
    try:
        external_root.mkdir(parents=True, exist_ok=False)
        base_eval_config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BASE_CONFIG_SOURCE_PATH, base_eval_config_path)

        spec_text = SPEC_SOURCE_PATH.read_text(encoding="utf-8")
        spec_text = _replace_once(spec_text, "content_length_bytes: 441792560", f"content_length_bytes: {len(archive)}")
        spec_text = _replace_once(
            spec_text,
            "content_length_bytes_must_equal: 441792560",
            f"content_length_bytes_must_equal: {len(archive)}",
        )
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(spec_text, encoding="utf-8")
        spec = load_yaml(spec_path)

        required_values = spec["prospective_eval_overlay_lifecycle"]["required_values"]
        if not isinstance(required_values, dict):
            pytest.fail("spec prospective_eval_overlay_lifecycle.required_values must be a mapping")
        overlay_rel = Path(str(spec["prospective_eval_overlay_lifecycle"]["required_path"]).replace("\\", "/"))
        overlay_path = repo_root / overlay_rel
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_path.write_text(_overlay_text(required_values), encoding="utf-8")
        overlay = load_yaml(overlay_path)

        transport_record_path = repo_root / Path(str(required_values["transport_freeze_record"]).replace("\\", "/"))
        raw_record_path = repo_root / Path(str(required_values["raw_freeze_record"]).replace("\\", "/"))

        yield ProspectiveSandbox(
            root=root,
            repo_root=repo_root,
            external_root=external_root,
            spec_path=spec_path,
            overlay_path=overlay_path,
            base_eval_config_path=base_eval_config_path,
            transport_record_path=transport_record_path,
            raw_record_path=raw_record_path,
            spec=spec,
            overlay=overlay,
            archive_bytes=archive,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def build_approval_record(
    sandbox: ProspectiveSandbox,
    *,
    decision: str = "APPROVED_PRE_DATA",
    approver: str = "@dronasrinivas",
    approved_at: str = "2026-08-29T10:00:00Z",
    immutable_inputs_verified: bool = True,
    protected_tests_verified: bool = True,
    attestation_overrides: dict[str, bool] | None = None,
    scope_overrides: dict[str, bool] | None = None,
) -> dict[str, Any]:
    spec_raw = sandbox.spec_path.read_bytes()
    attestation = {
        "archive_get_requested": False,
        "archive_content_downloaded": False,
        "archive_bytes_hashed": False,
        "archive_decompressed": False,
        "labels_inspected": False,
        "rows_inspected": False,
        "benchmark_derived": False,
        "scoring_performed": False,
    }
    if attestation_overrides:
        attestation.update(attestation_overrides)
    scope = {
        "allow_transport_freeze": True,
        "allow_exact_registered_archive_get": True,
        "allow_substitute_archive": False,
        "allow_threshold_change": False,
        "allow_label_dependent_implementation_change": False,
        "allow_clinical_use": False,
        "allow_label_inspection": False,
        "allow_scoring": False,
    }
    if scope_overrides:
        scope.update(scope_overrides)
    return {
        "schema": "raptor.eval.pre_data_approval.v1",
        "decision": decision,
        "approver": approver,
        "approved_at": approved_at,
        "registration": {
            "id": sandbox.spec["registration"]["id"],
            "path": str(sandbox.spec_path.relative_to(sandbox.repo_root)).replace("\\", "/"),
            "git_blob_sha1": git_blob_sha1(spec_raw),
            "canonical_lf_sha256": canonical_lf_sha256_path(sandbox.spec_path),
        },
        "adr": {
            "id": "ADR-0020",
            "decision_ref": sandbox.spec["registration"]["decision"],
        },
        "overlay": {
            "path": str(sandbox.overlay_path.relative_to(sandbox.repo_root)).replace("\\", "/"),
            "canonical_lf_sha256": canonical_lf_sha256_path(sandbox.overlay_path),
        },
        "scoring_semantics_projection_sha256": sandbox.spec["authority_partition"]["tsc2_scoring_semantics_projection"]["sha256"],
        "implementation_freeze": {
            "commit": "f" * 40,
            "module_hashes": {"raptor.eval.prospective_freeze": "0" * 64},
        },
        "immutable_inputs_verified": immutable_inputs_verified,
        "protected_tests_verified": protected_tests_verified,
        "x64_freeze": {
            "worker_designation": "adr-0008-designated-x64-worker",
            "worker_arch": "x86_64",
            "bias_commit": "ade13f206f3e2c2efe3ec92715d974645fc8da8f",
            "nirvana_banner": "3.18.1-0-g05f88047",
            "resource_manifest_sha256": "1" * 64,
        },
        "scope": scope,
        "pre_data_access_attestation": attestation,
    }


class InjectedLookup:
    def __init__(self, payload_by_url: dict[str, dict[str, Any] | None]) -> None:
        self._payload_by_url = copy.deepcopy(payload_by_url)
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict[str, Any] | None:
        self.calls.append(url)
        value = self._payload_by_url.get(url)
        return copy.deepcopy(value) if isinstance(value, dict) else value


class InjectedTransport:
    def __init__(
        self,
        *,
        head_by_url: dict[str, dict[str, Any]],
        body_by_url: dict[str, bytes],
        on_get_start: Callable[[], None] | None = None,
    ) -> None:
        self._head_by_url = copy.deepcopy(head_by_url)
        self._body_by_url = dict(body_by_url)
        self._on_get_start = on_get_start
        self._lock = threading.Lock()
        self.head_calls: list[str] = []
        self.get_calls: list[tuple[str, int]] = []

    def head(self, url: str) -> dict[str, Any]:
        with self._lock:
            self.head_calls.append(url)
        if url not in self._head_by_url:
            raise AssertionError(f"unexpected HEAD URL: {url}")
        return copy.deepcopy(self._head_by_url[url])

    def stream_get(self, url: str, chunk_bytes: int) -> Iterator[bytes]:
        with self._lock:
            self.get_calls.append((url, chunk_bytes))
        if url not in self._body_by_url:
            raise AssertionError(f"unexpected GET URL: {url}")
        if self._on_get_start is not None:
            self._on_get_start()
        payload = self._body_by_url[url]
        step = max(1, min(chunk_bytes, 17))
        for idx in range(0, len(payload), step):
            yield payload[idx : idx + step]


def make_head_payload(
    sandbox: ProspectiveSandbox,
    *,
    status_code: int = 200,
    final_url: str | None = None,
    raw_headers: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    stage1 = sandbox.spec["dataset_registration"]["stage_1_head_comparison"]
    if raw_headers is None:
        raw_headers = [
            ("Last-Modified", iso_utc_to_http_date(stage1["last_modified_must_equal"])),
            ("Content-Length", str(stage1["content_length_bytes_must_equal"])),
        ]
    return {
        "status_code": status_code,
        "final_url": final_url or sandbox.required_final_url,
        "raw_headers": list(raw_headers),
    }


def runtime_identity_ok() -> dict[str, Any]:
    return {
        "worker_designation": "adr-0008-designated-x64-worker",
        "worker_arch": "x86_64",
        "bias_commit": "ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        "nirvana_banner": "3.18.1-0-g05f88047",
        "resource_manifest_sha256": "1" * 64,
    }


def execute_transport_and_raw_freeze(
    sandbox: ProspectiveSandbox,
    *,
    approval_record: dict[str, Any] | None,
    transport: Any,
    published_archive_date_lookup: Any,
    official_md5_lookup: Any,
    transport_record_path: Path | None = None,
    raw_record_path: Path | None = None,
    runtime_identity: dict[str, Any] | None = None,
    cli_overrides: dict[str, Any] | None = None,
    env_overrides: dict[str, str] | None = None,
    label_reader: Any = None,
    benchmark_builder: Any = None,
    scoring_runner: Any = None,
    first_archive_get_at: str | None = None,
) -> dict[str, Any]:
    run = require_api("execute_transport_and_raw_freeze")
    default_runtime_identity = runtime_identity
    if default_runtime_identity is None and isinstance(approval_record, dict):
        freeze_block = approval_record.get("x64_freeze")
        if isinstance(freeze_block, dict):
            default_runtime_identity = copy.deepcopy(freeze_block)
    if default_runtime_identity is None:
        default_runtime_identity = runtime_identity_ok()
    result = run(
        registration_spec_path=sandbox.spec_path,
        prospective_overlay_path=sandbox.overlay_path,
        base_eval_config_path=sandbox.base_eval_config_path,
        approval_record=copy.deepcopy(approval_record) if isinstance(approval_record, dict) else approval_record,
        allowed_repo_root=sandbox.repo_root,
        allowed_external_root=sandbox.external_root,
        transport_freeze_record_path=transport_record_path or sandbox.transport_record_path,
        raw_freeze_record_path=raw_record_path or sandbox.raw_record_path,
        transport=transport,
        published_archive_date_lookup=published_archive_date_lookup,
        official_md5_lookup=official_md5_lookup,
        runtime_identity=default_runtime_identity,
        cli_overrides=cli_overrides or {},
        env_overrides=env_overrides or {},
        label_reader=label_reader,
        benchmark_builder=benchmark_builder,
        scoring_runner=scoring_runner,
        first_archive_get_at=first_archive_get_at,
    )
    if not isinstance(result, dict):
        pytest.fail("execute_transport_and_raw_freeze must return a mapping")
    return result


def validate_pre_data_approval(
    sandbox: ProspectiveSandbox,
    *,
    approval_record: dict[str, Any],
    first_archive_get_at: str | None = None,
) -> dict[str, Any]:
    fn = require_api("validate_pre_data_approval")
    out = fn(
        registration_spec_path=sandbox.spec_path,
        prospective_overlay_path=sandbox.overlay_path,
        approval_record=copy.deepcopy(approval_record),
        first_archive_get_at=first_archive_get_at,
    )
    if not isinstance(out, dict):
        pytest.fail("validate_pre_data_approval must return a mapping")
    return out


def merge_overlay(
    sandbox: ProspectiveSandbox,
    *,
    overlay_path: Path | None = None,
    base_eval_config_path: Path | None = None,
) -> dict[str, Any]:
    fn = require_api("merge_prospective_overlay")
    out = fn(
        registration_spec_path=sandbox.spec_path,
        prospective_overlay_path=overlay_path or sandbox.overlay_path,
        base_eval_config_path=base_eval_config_path or sandbox.base_eval_config_path,
    )
    if not isinstance(out, dict):
        pytest.fail("merge_prospective_overlay must return a mapping")
    return out


def parse_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail(f"expected JSON object at {path}")
    return loaded


def assert_record_content_hash(path: Path) -> dict[str, Any]:
    payload = parse_json(path)
    if "content_hash" not in payload:
        pytest.fail(f"missing content_hash field at {path}")
    assert payload["content_hash"] == canonical_json_content_hash(payload)
    return payload


def assert_stop_state(exc: BaseException, expected_code: str) -> None:
    observed_code = getattr(exc, "code", None)
    observed_stop = getattr(exc, "stop_state", None)
    reason = getattr(exc, "reason", None)
    assert observed_code == expected_code
    assert observed_stop == expected_code
    assert isinstance(reason, str) and reason.strip()
