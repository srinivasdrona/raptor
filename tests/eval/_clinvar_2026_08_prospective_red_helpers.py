from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import os
import re
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
_DEFAULT_IMPLEMENTATION_FREEZE_MODULES: tuple[str, ...] = ("raptor.eval.prospective_freeze",)
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_WINDOWS_DRIVE_PATH_RE = re.compile(r"^(?P<drive>[A-Za-z]):[\\\\/](?P<tail>.*)$")

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


def _git_blob_sha1(raw: bytes) -> str:
    canonical = canonical_lf_bytes(raw)
    return hashlib.sha1(b"blob " + str(len(canonical)).encode("utf-8") + b"\0" + canonical).hexdigest()


def git_blob_sha1(raw: bytes) -> str:
    return _git_blob_sha1(raw)


def _stderr_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    return text if text else "<empty>"


def _translate_windows_drive_to_wsl(path_text: str) -> str | None:
    match = _WINDOWS_DRIVE_PATH_RE.match(path_text.strip())
    if not match:
        return None
    drive = match.group("drive").lower()
    tail = match.group("tail").replace("\\", "/").lstrip("/")
    if tail:
        return f"/mnt/{drive}/{tail}"
    return f"/mnt/{drive}"


def _parse_linked_worktree_gitdir_pointer(pointer_file: Path) -> str:
    try:
        raw_text = pointer_file.read_text(encoding="utf-8")
    except OSError as exc:
        pytest.fail(f"unable to read linked-worktree git metadata pointer {pointer_file}: {exc}", pytrace=False)
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if len(lines) != 1 or not lines[0].lower().startswith("gitdir:"):
        pytest.fail(
            f"linked-worktree git metadata pointer {pointer_file} must contain exactly one 'gitdir:' line",
            pytrace=False,
        )
    gitdir_raw = lines[0][len("gitdir:") :].strip()
    if not gitdir_raw or "\x00" in gitdir_raw:
        pytest.fail(f"linked-worktree git metadata pointer {pointer_file} has an invalid gitdir value", pytrace=False)
    return gitdir_raw


def _resolve_gitdir_from_pointer(*, repo_root: Path, gitdir_raw: str, pointer_file: Path) -> Path:
    candidates: list[Path] = []
    direct = Path(gitdir_raw)
    candidates.append(direct)
    if not direct.is_absolute():
        candidates.append(repo_root / direct)
    translated = _translate_windows_drive_to_wsl(gitdir_raw)
    if translated:
        candidates.append(Path(translated))

    seen: set[str] = set()
    checked: list[str] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        checked.append(key)
        if candidate.is_dir():
            return candidate
    pytest.fail(
        f"linked-worktree gitdir from {pointer_file} did not resolve to an existing directory; "
        f"raw={gitdir_raw!r}, candidates={checked!r}",
        pytrace=False,
    )


def _resolve_git_metadata() -> tuple[str, str]:
    git_dir = os.environ.get("GIT_DIR")
    git_work_tree = os.environ.get("GIT_WORK_TREE")
    if git_dir and git_work_tree:
        return git_dir, git_work_tree

    dot_git = REPO_ROOT / ".git"
    if dot_git.is_dir():
        return str(dot_git), str(REPO_ROOT)
    if dot_git.is_file():
        gitdir_raw = _parse_linked_worktree_gitdir_pointer(dot_git)
        gitdir = _resolve_gitdir_from_pointer(repo_root=REPO_ROOT, gitdir_raw=gitdir_raw, pointer_file=dot_git)
        return str(gitdir), str(REPO_ROOT)

    pytest.fail(
        f"unable to resolve git metadata: neither env override nor checkout metadata is valid at {dot_git}",
        pytrace=False,
    )


@contextmanager
def _with_resolved_git_env() -> Iterator[None]:
    git_dir = os.environ.get("GIT_DIR")
    git_work_tree = os.environ.get("GIT_WORK_TREE")
    if git_dir and git_work_tree:
        yield
        return

    resolved_git_dir, resolved_work_tree = _resolve_git_metadata()
    prior_git_dir = os.environ.get("GIT_DIR")
    prior_git_work_tree = os.environ.get("GIT_WORK_TREE")
    os.environ["GIT_DIR"] = resolved_git_dir
    os.environ["GIT_WORK_TREE"] = resolved_work_tree
    try:
        yield
    finally:
        if prior_git_dir is None:
            os.environ.pop("GIT_DIR", None)
        else:
            os.environ["GIT_DIR"] = prior_git_dir
        if prior_git_work_tree is None:
            os.environ.pop("GIT_WORK_TREE", None)
        else:
            os.environ["GIT_WORK_TREE"] = prior_git_work_tree


def _run_git_with_worktree(*args: str) -> subprocess.CompletedProcess[bytes]:
    git_dir, git_work_tree = _resolve_git_metadata()
    cmd = ["git", "--no-pager", "--git-dir", git_dir, "--work-tree", git_work_tree, *args]
    try:
        return subprocess.run(
            cmd,
            cwd=git_work_tree,
            check=False,
            capture_output=True,
        )
    except OSError as exc:  # pragma: no cover - platform-specific process launch failure
        pytest.fail(f"git unusable while resolving implementation_freeze: {exc}", pytrace=False)


def _require_git_success(result: subprocess.CompletedProcess[bytes], *, context: str) -> None:
    if result.returncode == 0:
        return
    pytest.fail(
        f"{context}: git command failed with rc={result.returncode}; stderr={_stderr_text(result.stderr)}",
        pytrace=False,
    )


def _module_to_relpath(module_name: str) -> str:
    return (Path("src") / Path(*module_name.split("."))).with_suffix(".py").as_posix()


def _resolve_commit(commitish: str = "HEAD") -> str:
    head = _run_git_with_worktree("rev-parse", "--verify", commitish)
    _require_git_success(head, context=f"resolving implementation_freeze commit {commitish!r}")
    commit = head.stdout.decode("utf-8", errors="replace").strip()
    if not _GIT_COMMIT_RE.fullmatch(commit):
        pytest.fail(f"resolved {commitish!r} is not a lowercase 40-hex SHA: {commit!r}", pytrace=False)
    return commit


def _normalize_module_names(module_names: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    selected = tuple(module_names) if module_names is not None else _DEFAULT_IMPLEMENTATION_FREEZE_MODULES
    if not selected:
        pytest.fail("implementation_freeze module list must be non-empty", pytrace=False)
    normalized: list[str] = []
    for module_name in selected:
        if not isinstance(module_name, str) or not module_name.strip():
            pytest.fail("implementation_freeze module list contains a blank module name", pytrace=False)
        normalized_name = module_name.strip()
        if normalized_name not in normalized:
            normalized.append(normalized_name)
    return tuple(normalized)


def resolve_committed_implementation_freeze(
    commitish: str = "HEAD",
    *,
    module_names: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    commit = _resolve_commit(commitish)
    commit_probe = _run_git_with_worktree("cat-file", "-e", f"{commit}" + "^{commit}")
    _require_git_success(commit_probe, context=f"probing implementation_freeze commit {commit}")

    required_modules = _normalize_module_names(module_names)
    module_hashes: dict[str, str] = {}
    missing_modules: list[str] = []
    missing_errors: list[str] = []
    for module_name in required_modules:
        module_path = _module_to_relpath(module_name)
        shown = _run_git_with_worktree("show", f"{commit}:{module_path}")
        if shown.returncode != 0:
            missing_modules.append(module_name)
            missing_errors.append(f"{module_name}<{module_path}> stderr={_stderr_text(shown.stderr)}")
            continue
        module_hashes[module_name] = sha256_hex(canonical_lf_bytes(shown.stdout))
    if missing_modules:
        pytest.fail(
            "implementation_freeze committed-tree fixture is incomplete for declared modules: "
            f"commit={commit} missing={missing_modules!r}; details={' | '.join(missing_errors)}",
            pytrace=False,
        )
    if not module_hashes:
        pytest.fail(
            "implementation_freeze committed-tree fixture cannot be generated: "
            f"commit {commit} had no resolvable module hashes for declared modules {list(required_modules)!r}",
            pytrace=False,
        )
    return {"commit": commit, "module_hashes": module_hashes}


def draft_placeholder_implementation_freeze(module_names: tuple[str, ...] | list[str] | None = None) -> dict[str, Any]:
    required_modules = _normalize_module_names(module_names)
    return {
        "commit": "NOT_YET_COMMITTED",
        "module_hashes": {module_name: "NOT_YET_COMMITTED" for module_name in required_modules},
    }


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
    resource_manifest_checksums_dir: Path
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


def write_resource_manifest_checksums(directory: Path, *, contents: dict[str, bytes] | None = None) -> Path:
    """Writes the three ADR-0008 pinned resource-manifest checksum files
    (`RESOURCE_MANIFEST_ENTRIES`) into `directory` with deterministic
    fixture bytes, so tests can exercise
    `validate_scoring_stage_approval`'s independent resource-manifest-digest
    RECOMPUTATION without any real x64 Nirvana/BIAS resource bundle.
    Returns `directory`."""
    module = require_module()
    directory.mkdir(parents=True, exist_ok=True)
    for _entry_id, filename in module.RESOURCE_MANIFEST_ENTRIES:
        payload = (contents or {}).get(filename, f"{filename}-fixture-bytes".encode("utf-8"))
        (directory / filename).write_bytes(payload)
    return directory


@contextmanager
def prospective_sandbox(name: str, *, archive_bytes: bytes | None = None) -> Iterator[ProspectiveSandbox]:
    archive = archive_bytes if archive_bytes is not None else default_archive_bytes()
    root = REPO_ROOT / ".raptor" / "pytest-red" / f"{name}-{uuid.uuid4().hex}"
    repo_root = root / "repo"
    external_root = root / "external-content-root"
    spec_path = repo_root / "docs" / "project" / "specs" / SPEC_SOURCE_PATH.name
    base_eval_config_path = repo_root / "configs" / "eval" / "tsc2.yaml"
    resource_manifest_checksums_dir = root / "resource-manifest-checksums"
    root.mkdir(parents=True, exist_ok=False)
    try:
        external_root.mkdir(parents=True, exist_ok=False)
        write_resource_manifest_checksums(resource_manifest_checksums_dir)
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
        spec_path.write_bytes(canonical_lf_bytes(spec_text.encode("utf-8")))
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
            resource_manifest_checksums_dir=resource_manifest_checksums_dir,
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
    implementation_freeze = resolve_committed_implementation_freeze()
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
        "implementation_freeze": implementation_freeze,
        "immutable_inputs_verified": immutable_inputs_verified,
        "protected_tests_verified": protected_tests_verified,
        "scope": scope,
        "pre_data_access_attestation": attestation,
    }


def build_scoring_stage_approval_record(
    sandbox: ProspectiveSandbox,
    *,
    decision: str = "APPROVED_SCORING_STAGE",
    approver: str = "@dronasrinivas",
    approved_at: str = "2026-08-29T10:00:00Z",
    registration_id: str | None = None,
    resource_manifest_checksums_dir: Path | None = None,
    x64_freeze_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Builds a valid `raptor.eval.scoring_stage_approval.v1` record -- the
    SEPARATE, LATER gate for ADR-0020 stage 4 (BIAS/Nirvana execution,
    label-dependent evaluation). Independent of `build_approval_record`
    (`pre_data_approval`, stages 1-2) above.

    By default, `x64_freeze.resource_manifest_sha256` is the REAL digest
    recomputed from `resource_manifest_checksums_dir` (default:
    `sandbox.resource_manifest_checksums_dir`, pre-populated with
    deterministic fixture bytes) -- so this record passes
    `validate_scoring_stage_approval`'s anti-fabrication cross-check by
    construction whenever the caller also passes the matching
    `observed_runtime_identity`/`resource_manifest_checksums_dir` (see
    `validate_scoring_stage_approval` wrapper below). `x64_freeze_overrides`
    lets a caller deliberately fabricate/mismatch a claimed pin for negative
    tests."""
    module = require_module()
    checksums_dir = resource_manifest_checksums_dir or sandbox.resource_manifest_checksums_dir
    x64_freeze = {
        **observed_runtime_identity_ok(),
        "resource_manifest_sha256": module.compute_resource_manifest_sha256(checksums_dir),
    }
    if x64_freeze_overrides:
        x64_freeze = {**x64_freeze, **x64_freeze_overrides}
    return {
        "schema": "raptor.eval.scoring_stage_approval.v1",
        "registration_id": registration_id if registration_id is not None else sandbox.spec["registration"]["id"],
        "decision": decision,
        "approver": approver,
        "approved_at": approved_at,
        "x64_freeze": x64_freeze,
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


def observed_runtime_identity_ok() -> dict[str, Any]:
    """The 4 runtime-identity dimensions a process can OBSERVE directly
    about its own execution (worker designation/arch, BIAS/Nirvana tool
    identity). Deliberately excludes `resource_manifest_sha256`, which
    `validate_scoring_stage_approval` never accepts as an observed claim --
    it is always independently recomputed from the actual manifest files."""
    return {
        "worker_designation": "adr-0008-designated-x64-worker",
        "worker_arch": "x86_64",
        "bias_commit": "ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        "nirvana_banner": "3.18.1-0-g05f88047",
    }


def runtime_identity_ok(resource_manifest_sha256: str = "1" * 64) -> dict[str, Any]:
    """Full 5-key runtime-identity block: `observed_runtime_identity_ok()`
    plus a `resource_manifest_sha256`. The default digest is a fixed
    placeholder suitable only for FORMAT-level checks; pass the real
    recomputed digest (e.g. via
    `require_module().compute_resource_manifest_sha256(...)`) whenever
    asserting an EXACT expected `x64_freeze` value."""
    return {**observed_runtime_identity_ok(), "resource_manifest_sha256": resource_manifest_sha256}


def execute_transport_and_raw_freeze(
    sandbox: ProspectiveSandbox,
    *,
    approval_record: dict[str, Any] | None,
    transport: Any,
    published_archive_date_lookup: Any,
    official_md5_lookup: Any,
    transport_record_path: Path | None = None,
    raw_record_path: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
    env_overrides: dict[str, str] | None = None,
    label_reader: Any = None,
    benchmark_builder: Any = None,
    scoring_runner: Any = None,
    first_archive_get_at: str | None = None,
) -> dict[str, Any]:
    run = require_api("execute_transport_and_raw_freeze")
    with _with_resolved_git_env():
        result = run(
            registration_spec_path=sandbox.spec_path,
            prospective_overlay_path=sandbox.overlay_path,
            approval_record=copy.deepcopy(approval_record) if isinstance(approval_record, dict) else approval_record,
            allowed_repo_root=sandbox.repo_root,
            allowed_external_root=sandbox.external_root,
            transport_freeze_record_path=transport_record_path or sandbox.transport_record_path,
            raw_freeze_record_path=raw_record_path or sandbox.raw_record_path,
            transport=transport,
            published_archive_date_lookup=published_archive_date_lookup,
            official_md5_lookup=official_md5_lookup,
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
    with _with_resolved_git_env():
        out = fn(
            registration_spec_path=sandbox.spec_path,
            prospective_overlay_path=sandbox.overlay_path,
            approval_record=copy.deepcopy(approval_record),
            first_archive_get_at=first_archive_get_at,
        )
    if not isinstance(out, dict):
        pytest.fail("validate_pre_data_approval must return a mapping")
    return out


def validate_scoring_stage_approval(
    sandbox: ProspectiveSandbox,
    *,
    approval_record: dict[str, Any],
    registration_id: str | None = None,
    registration_spec_path: Path | None = None,
    observed_runtime_identity: dict[str, Any] | None = None,
    resource_manifest_checksums_dir: Path | None = None,
    first_scoring_execution_at: str | None = None,
) -> dict[str, Any]:
    """Wraps `raptor.eval.prospective_freeze.validate_scoring_stage_approval`
    -- the SEPARATE, LATER ADR-0020 stage 4 gate (BIAS/Nirvana execution,
    label-dependent evaluation). Independent of `validate_pre_data_approval`
    above. Defaults `observed_runtime_identity` and
    `resource_manifest_checksums_dir` to the sandbox's own known-good
    fixtures (`observed_runtime_identity_ok()` /
    `sandbox.resource_manifest_checksums_dir`) so callers that only want to
    mutate `approval_record` (e.g. `build_scoring_stage_approval_record`'s
    `x64_freeze_overrides`) get the correct anti-fabrication cross-check
    inputs without repeating them at every call site."""
    fn = require_api("validate_scoring_stage_approval")
    out = fn(
        registration_id=registration_id if registration_id is not None else sandbox.spec["registration"]["id"],
        registration_spec_path=registration_spec_path or sandbox.spec_path,
        approval_record=copy.deepcopy(approval_record),
        observed_runtime_identity=(
            dict(observed_runtime_identity) if observed_runtime_identity is not None else observed_runtime_identity_ok()
        ),
        resource_manifest_checksums_dir=resource_manifest_checksums_dir or sandbox.resource_manifest_checksums_dir,
        first_scoring_execution_at=first_scoring_execution_at,
    )
    if not isinstance(out, dict):
        pytest.fail("validate_scoring_stage_approval must return a mapping")
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
