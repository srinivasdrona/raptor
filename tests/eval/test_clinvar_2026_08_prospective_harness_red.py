from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import types
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

import tests.eval._clinvar_2026_08_prospective_red_helpers as prospective_red_helpers
from tests.eval._clinvar_2026_08_prospective_red_helpers import (
    REPO_ROOT,
    InjectedTransport,
    assert_stop_state,
    build_approval_record,
    draft_placeholder_implementation_freeze,
    make_head_payload,
    resolve_committed_implementation_freeze,
    prospective_sandbox,
    require_api,
    require_exception,
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "run_clinvar_2026_08_prospective_freeze.py"
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v2.yaml"
OVERLAY_PATH = REPO_ROOT / "configs" / "eval" / "tsc2_clinvar_2026_08_amendment_v2.overlay.yaml"
BASE_CONFIG_PATH = REPO_ROOT / "configs" / "eval" / "tsc2.yaml"
DRAFT_APPROVAL_PATH = REPO_ROOT / "docs" / "project" / "approvals" / "clinvar-2026-08-amendment-v2.pre_data_approval.draft.json"
EXTERNAL_ROOT_DOC_PATH = REPO_ROOT / "docs" / "ops" / "clinvar-2026-08-amendment-v2-external-content-root.md"
DEFAULT_PUBLISHED_LOOKUP_SPEC = "_harness_fake_injections:published_archive_date_lookup"
DEFAULT_OFFICIAL_MD5_LOOKUP_SPEC = "_harness_fake_injections:official_md5_lookup"


class _StubTransport:
    """A minimal transport double exposing only the `head`/`stream_get`
    surface `capture_transport_identity_pin` inspects (via `type(transport)
    .head`/`.stream_get`) immediately after `build_transport()` returns --
    for tests that mock away `execute_transport_and_raw_freeze` entirely
    (or refuse before it) and never expect the real transport methods to
    be invoked. A bare `object()` no longer suffices here: it has no
    `head`/`stream_get` attributes, so the transport-tamper-defense pin
    capture (independent review finding #1) would raise `AttributeError`
    instead of exercising the refusal path each of these tests actually
    means to test."""

    def head(self, url: str) -> Any:
        raise AssertionError("_StubTransport.head must never be called directly in this test")

    def stream_get(self, url: str, chunk_bytes: int) -> Any:
        raise AssertionError("_StubTransport.stream_get must never be called directly in this test")


def _load_harness_module() -> Any:
    if not SCRIPT_PATH.is_file():
        pytest.fail(f"RED: missing harness script {SCRIPT_PATH}")
    module_name = "_clinvar_2026_08_prospective_harness_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        pytest.fail("unable to load harness module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _execute_argv(
    *,
    approval_record: Path,
    registration_spec: Path,
    overlay: Path,
    base_config: Path,
    allowed_repo_root: Path,
    allowed_external_root: Path,
    published_archive_date_lookup: str | None = DEFAULT_PUBLISHED_LOOKUP_SPEC,
    official_md5_lookup: str | None = DEFAULT_OFFICIAL_MD5_LOOKUP_SPEC,
    transport_record: Path | None = None,
    raw_record: Path | None = None,
) -> list[str]:
    # Finding #3: there is no `--transport-factory` (or any other) CLI option
    # any more -- production/executable acquisition is hard-wired to
    # `prospective_exact_source_transport.build_transport()`.
    argv = [
        "--execute",
        "--approval-record",
        str(approval_record),
        "--registration-spec",
        str(registration_spec),
        "--overlay",
        str(overlay),
        "--base-config",
        str(base_config),
        "--allowed-repo-root",
        str(allowed_repo_root),
        "--allowed-external-root",
        str(allowed_external_root),
    ]
    if published_archive_date_lookup is not None:
        argv.extend(["--published-archive-date-lookup", published_archive_date_lookup])
    if official_md5_lookup is not None:
        argv.extend(["--official-md5-lookup", official_md5_lookup])
    if transport_record is not None:
        argv.extend(["--transport-freeze-record", str(transport_record)])
    if raw_record is not None:
        argv.extend(["--raw-freeze-record", str(raw_record)])
    return argv


def _invoke_main(harness: Any, argv: list[str]) -> tuple[int | None, BaseException | None]:
    try:
        with _with_resolved_git_env_for_harness():
            return harness.main(argv), None
    except BaseException as exc:  # noqa: BLE001
        return None, exc


@contextmanager
def _with_resolved_git_env_for_harness() -> Iterator[None]:
    git_dir = os.environ.get("GIT_DIR")
    git_work_tree = os.environ.get("GIT_WORK_TREE")
    if git_dir and git_work_tree:
        yield
        return
    resolved_git_dir, resolved_work_tree = prospective_red_helpers._resolve_git_metadata()
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


def _can_create_symlink(parent: Path) -> bool:
    if not hasattr(os, "symlink"):
        return False
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / "symlink-probe-target"
    link = parent / "symlink-probe-link"
    target.write_text("x", encoding="utf-8")
    try:
        os.symlink(target, link)
        return link.is_symlink()
    except OSError:
        return False
    finally:
        link.unlink(missing_ok=True)
        target.unlink(missing_ok=True)


def _strip_commentary_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_commentary_keys(item)
            for key, item in value.items()
            if not (isinstance(key, str) and key.startswith("_"))
        }
    if isinstance(value, list):
        return [_strip_commentary_keys(item) for item in value]
    return value


def _install_fake_injections_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    module_name: str = "_harness_fake_injections",
    published_lookup: Any | None = None,
    official_md5_lookup: Any | None = None,
) -> types.ModuleType:
    # Finding #3: the harness no longer resolves a transport factory via any
    # dynamic 'module:callable' spec (there is no `--transport-factory`
    # option), so this fake module only ever needs to provide the two
    # lookup ports; `build_transport` plumbing was removed entirely.
    fake_module = types.ModuleType(module_name)
    if published_lookup is None:
        published_lookup = lambda _url: {"published_archive_date": "2026-08-06", "source_identity": "fake-published"}
    if official_md5_lookup is None:
        official_md5_lookup = lambda _url: {"official_md5": "0" * 32, "source_identity": "fake-md5"}
    fake_module.published_archive_date_lookup = published_lookup
    fake_module.official_md5_lookup = official_md5_lookup
    monkeypatch.setitem(sys.modules, module_name, fake_module)
    return fake_module


def _transport_resolution_spies(monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], list[str], list[str], list[str]]:
    factory_calls: list[str] = []
    import_calls: list[str] = []
    constructor_calls: list[str] = []
    network_calls: list[str] = []

    real_import_module = importlib.import_module

    def _recording_import(name: str, package: str | None = None) -> Any:
        # `validate_pre_data_approval`'s implementation-freeze executing-
        # code check (independent review finding #4) legitimately
        # re-imports whatever real `raptor.*` module(s) the approval
        # record's `implementation_freeze.module_hashes` names -- this
        # happens BEFORE transport/lookup resolution and is unrelated to
        # it. These assertions mean "no CALLER-SELECTED (dynamically-
        # resolved 'module:callable' spec) module was imported before
        # transport resolution" -- caller-selected specs in every test in
        # this file always name a synthetic/test-local module, never a
        # real `raptor.*` one, so excluding that namespace here keeps the
        # assertions' original meaning intact.
        if not name.startswith("raptor."):
            import_calls.append(name)
        return real_import_module(name, package)

    def _deny_socket(*_args: Any, **_kwargs: Any) -> Any:
        network_calls.append("socket")
        raise AssertionError("network must remain inert before transport resolution")

    def _deny_create_connection(*_args: Any, **_kwargs: Any) -> Any:
        network_calls.append("create_connection")
        raise AssertionError("network must remain inert before transport resolution")

    monkeypatch.setattr(importlib, "import_module", _recording_import)
    monkeypatch.setattr(socket, "socket", _deny_socket)
    monkeypatch.setattr(socket, "create_connection", _deny_create_connection)

    return factory_calls, import_calls, constructor_calls, network_calls


def _transport_exception_type(name: str) -> type[BaseException]:
    module = importlib.import_module("raptor.eval.prospective_exact_source_transport")
    cls = getattr(module, name, None)
    if not isinstance(cls, type) or not issubclass(cls, BaseException):
        pytest.fail(f"missing transport exception class: {name}")
    return cls


def _canonical_lf_bytes(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stderr_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    return text if text else "<empty>"


def _git_worktree_flags() -> list[str]:
    git_dir, git_work_tree = prospective_red_helpers._resolve_git_metadata()
    return ["--git-dir", git_dir, "--work-tree", git_work_tree]


def _run_git_with_worktree(*args: str) -> subprocess.CompletedProcess[bytes]:
    cmd = ["git", "--no-pager", *_git_worktree_flags(), *args]
    try:
        return subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        pytest.fail(f"git unusable for implementation-freeze validation: {exc}", pytrace=False)


def _assert_git_usable(result: subprocess.CompletedProcess[bytes], *, context: str) -> None:
    if result.returncode == 0:
        return
    stderr = _stderr_text(result.stderr)
    lowered = stderr.lower()
    if any(marker in lowered for marker in ("not a git repository", "bad config", "dubious ownership", "unknown option")):
        pytest.fail(f"{context}: git unusable (rc={result.returncode}) stderr={stderr}", pytrace=False)


def _assert_typed_nonzero_without_traceback(
    *,
    rc: int | None,
    exc: BaseException | None,
    output: str,
    expected_fragments: tuple[str, ...],
    allowed_rc: tuple[int, ...] = (2, 3),
) -> None:
    assert exc is None
    assert rc in allowed_rc
    lowered = output.lower()
    assert any(fragment.lower() in lowered for fragment in expected_fragments)
    assert "traceback (most recent call last)" not in lowered


def test_harness_is_inert_without_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _load_harness_module()
    resolved: list[str] = []
    executed: list[dict[str, Any]] = []
    monkeypatch.setattr(
        harness.prospective_exact_source_transport,
        "build_transport",
        lambda **_kwargs: resolved.append("build_transport") or _StubTransport(),
    )
    monkeypatch.setattr(
        harness.prospective_freeze,
        "execute_transport_and_raw_freeze",
        lambda **kwargs: executed.append(kwargs) or {"stage_status": "SHOULD_NOT_RUN"},
    )

    rc, exc = _invoke_main(
        harness,
        [
            "--registration-spec",
            str(SPEC_PATH),
            "--overlay",
            str(OVERLAY_PATH),
            "--base-config",
            str(BASE_CONFIG_PATH),
        ],
    )
    assert exc is None
    assert rc == 0
    assert resolved == []
    assert executed == []


def test_execute_accepts_wsl_aarch64_and_refuses_only_for_missing_approval(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness_module()
    monkeypatch.setattr(harness.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")

    rc, exc = _invoke_main(harness, ["--execute"])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert exc is None
    assert rc == 2
    assert "designated x64 worker" not in combined.lower()
    assert any(
        fragment in combined.lower()
        for fragment in ("approval-record", "published-archive-date-lookup", "official-md5-lookup")
    )
    assert "Traceback (most recent call last)" not in combined


def test_execute_rejects_native_windows_python_before_transport_import(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness_module()
    with prospective_sandbox("harness-exec-env-policy") as sandbox:
        _install_fake_injections_module(monkeypatch)
        approval_path = sandbox.root / "approval.json"
        _write_json(approval_path, build_approval_record(sandbox))
        factory_calls, import_calls, constructor_calls, network_calls = _transport_resolution_spies(monkeypatch)

        def _record_factory(**_kwargs: Any) -> Any:
            factory_calls.append("build_transport")
            constructor_calls.append("build_transport")
            return _StubTransport()

        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", _record_factory)
        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "C:\\Python312\\python.exe")

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_path,
                registration_spec=sandbox.spec_path,
                overlay=sandbox.overlay_path,
                base_config=sandbox.base_eval_config_path,
                allowed_repo_root=sandbox.repo_root,
                allowed_external_root=sandbox.external_root,
            ),
        )
        captured = capsys.readouterr()
        assert exc is None
        assert rc == 2
        assert "wsl" in captured.err.lower()
        assert factory_calls == []
        assert import_calls == []
        assert constructor_calls == []
        assert network_calls == []
        assert "Traceback (most recent call last)" not in (captured.out + captured.err)


@pytest.mark.parametrize(
    "root_case",
    (
        "missing",
        "inside-repo",
        "plain-file",
        "symlink",
    ),
)
def test_execute_external_root_preflight_rejects_invalid_root_before_transport_import(
    root_case: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness_module()
    with prospective_sandbox(f"harness-external-root-{root_case}") as sandbox:
        _install_fake_injections_module(monkeypatch)
        approval_path = sandbox.root / "approval.json"
        _write_json(approval_path, build_approval_record(sandbox))
        candidate_root = sandbox.external_root

        if root_case == "missing":
            shutil.rmtree(candidate_root)
        elif root_case == "inside-repo":
            candidate_root = sandbox.repo_root / "inside-repo-external-root"
            candidate_root.mkdir(parents=True, exist_ok=True)
        elif root_case == "plain-file":
            candidate_root = sandbox.root / "not-a-directory"
            candidate_root.write_text("not-a-directory", encoding="utf-8")
        elif root_case == "symlink":
            if not _can_create_symlink(sandbox.root):
                pytest.skip("symlink creation unsupported in this environment")
            target_root = sandbox.root / "target-external-root"
            target_root.mkdir(parents=True, exist_ok=False)
            candidate_root = sandbox.root / "symlinked-external-root"
            os.symlink(target_root, candidate_root)
        else:  # pragma: no cover
            pytest.fail(f"unknown root_case={root_case!r}")

        factory_calls, import_calls, constructor_calls, network_calls = _transport_resolution_spies(monkeypatch)

        def _record_factory(**_kwargs: Any) -> Any:
            factory_calls.append("build_transport")
            constructor_calls.append("build_transport")
            return _StubTransport()

        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", _record_factory)
        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_path,
                registration_spec=sandbox.spec_path,
                overlay=sandbox.overlay_path,
                base_config=sandbox.base_eval_config_path,
                allowed_repo_root=sandbox.repo_root,
                allowed_external_root=candidate_root,
            ),
        )
        captured = capsys.readouterr()
        assert exc is None
        assert rc == 2
        assert "external" in captured.err.lower()
        assert factory_calls == []
        assert import_calls == []
        assert constructor_calls == []
        assert network_calls == []
        assert "Traceback (most recent call last)" not in (captured.out + captured.err)


@pytest.mark.parametrize(
    ("missing_published_lookup", "missing_official_md5_lookup", "expected_error_fragment"),
    (
        (True, False, "published-archive-date-lookup"),
        (False, True, "official-md5-lookup"),
    ),
)
def test_execute_requires_both_lookup_injection_options_before_transport_resolution(
    missing_published_lookup: bool,
    missing_official_md5_lookup: bool,
    expected_error_fragment: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness_module()
    with prospective_sandbox("harness-missing-lookup-options") as sandbox:
        _install_fake_injections_module(monkeypatch)
        approval_path = sandbox.root / "approval.json"
        _write_json(approval_path, build_approval_record(sandbox))
        factory_calls, import_calls, constructor_calls, network_calls = _transport_resolution_spies(monkeypatch)

        def _record_factory(**_kwargs: Any) -> Any:
            factory_calls.append("build_transport")
            constructor_calls.append("build_transport")
            return _StubTransport()

        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", _record_factory)
        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_path,
                registration_spec=sandbox.spec_path,
                overlay=sandbox.overlay_path,
                base_config=sandbox.base_eval_config_path,
                allowed_repo_root=sandbox.repo_root,
                allowed_external_root=sandbox.external_root,
                published_archive_date_lookup=None if missing_published_lookup else DEFAULT_PUBLISHED_LOOKUP_SPEC,
                official_md5_lookup=None if missing_official_md5_lookup else DEFAULT_OFFICIAL_MD5_LOOKUP_SPEC,
            ),
        )
        captured = capsys.readouterr()
        assert exc is None
        assert rc == 2
        assert expected_error_fragment in (captured.out + captured.err).lower()
        assert factory_calls == []
        assert import_calls == []
        assert constructor_calls == []
        assert network_calls == []
        assert "Traceback (most recent call last)" not in (captured.out + captured.err)


@pytest.mark.parametrize(
    ("case_id", "expected_stop_state", "expected_reason_fragment"),
    (
        ("repository-draft-approval", "PRE_DATA_REVIEW_REQUIRED", "top-level keys"),
        ("overlay-byte-drift", "PRE_DATA_DRIFT", "overlay canonical_lf_sha256"),
    ),
)
def test_execute_real_validator_rejections_return_rc2_without_transport_activity(
    case_id: str,
    expected_stop_state: str,
    expected_reason_fragment: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness_module()
    with prospective_sandbox(f"harness-real-validator-{case_id}") as sandbox:
        _install_fake_injections_module(monkeypatch)
        factory_calls, import_calls, constructor_calls, network_calls = _transport_resolution_spies(monkeypatch)

        def _record_factory(**_kwargs: Any) -> Any:
            factory_calls.append("build_transport")
            constructor_calls.append("build_transport")
            return _StubTransport()

        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", _record_factory)
        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")

        if case_id == "repository-draft-approval":
            if not DRAFT_APPROVAL_PATH.is_file():
                pytest.fail(f"RED: missing prep artifact {DRAFT_APPROVAL_PATH}")
            approval_record = DRAFT_APPROVAL_PATH
            registration_spec = SPEC_PATH
            overlay = OVERLAY_PATH
            base_config = BASE_CONFIG_PATH
            allowed_repo_root = REPO_ROOT
            allowed_external_root = sandbox.external_root
        elif case_id == "overlay-byte-drift":
            approval = build_approval_record(sandbox)
            approval_record = sandbox.root / "approval.json"
            _write_json(approval_record, approval)
            sandbox.overlay_path.write_text(
                sandbox.overlay_path.read_text(encoding="utf-8") + "\n# drift-after-approval\n",
                encoding="utf-8",
            )
            registration_spec = sandbox.spec_path
            overlay = sandbox.overlay_path
            base_config = sandbox.base_eval_config_path
            allowed_repo_root = sandbox.repo_root
            allowed_external_root = sandbox.external_root
        else:  # pragma: no cover
            pytest.fail(f"unknown case_id={case_id!r}")

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_record,
                registration_spec=registration_spec,
                overlay=overlay,
                base_config=base_config,
                allowed_repo_root=allowed_repo_root,
                allowed_external_root=allowed_external_root,
            ),
        )
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert exc is None
        assert rc == 2
        assert expected_stop_state in combined
        assert expected_reason_fragment.lower() in combined.lower()
        assert "Traceback (most recent call last)" not in combined
        assert factory_calls == []
        assert import_calls == []
        assert constructor_calls == []
        assert network_calls == []


@pytest.mark.parametrize(
    ("case_id", "expected_fragments"),
    (
        ("missing-approval-file", ("approval", "not found", "no such file")),
        ("invalid-approval-json", ("approval", "json", "decode")),
    ),
)
def test_execute_handles_approval_file_read_failures_with_typed_refusal_and_no_transport_activity(
    case_id: str,
    expected_fragments: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness_module()
    with prospective_sandbox(f"harness-approval-read-failure-{case_id}") as sandbox:
        _install_fake_injections_module(monkeypatch)
        factory_calls, import_calls, constructor_calls, network_calls = _transport_resolution_spies(monkeypatch)

        def _record_factory(**_kwargs: Any) -> Any:
            factory_calls.append("build_transport")
            constructor_calls.append("build_transport")
            return _StubTransport()

        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", _record_factory)
        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")

        approval_path = sandbox.root / "approval.json"
        if case_id == "missing-approval-file":
            approval_path.unlink(missing_ok=True)
        elif case_id == "invalid-approval-json":
            approval_path.write_text("{invalid-json", encoding="utf-8")
        else:  # pragma: no cover
            pytest.fail(f"unknown case_id={case_id!r}")

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_path,
                registration_spec=sandbox.spec_path,
                overlay=sandbox.overlay_path,
                base_config=sandbox.base_eval_config_path,
                allowed_repo_root=sandbox.repo_root,
                allowed_external_root=sandbox.external_root,
            ),
        )
        captured = capsys.readouterr()
        assert factory_calls == []
        assert import_calls == []
        assert constructor_calls == []
        assert network_calls == []
        _assert_typed_nonzero_without_traceback(
            rc=rc,
            exc=exc,
            output=captured.out + captured.err,
            expected_fragments=expected_fragments,
            allowed_rc=(2,),
        )


@pytest.mark.parametrize(
    ("case_id", "published_spec", "official_spec", "expected_fragments"),
    (
        (
            "published-lookup-module-import-error",
            "__missing_lookup_module__:published_archive_date_lookup",
            "_harness_resolution_faults:official_md5_lookup",
            ("published", "lookup", "module", "import"),
        ),
        (
            "published-lookup-attribute-error",
            "_harness_resolution_faults:missing_published_lookup",
            "_harness_resolution_faults:official_md5_lookup",
            ("published", "lookup", "attribute", "missing_published_lookup"),
        ),
        (
            "official-lookup-module-import-error",
            "_harness_resolution_faults:published_archive_date_lookup",
            "__missing_lookup_module__:official_md5_lookup",
            ("official", "md5", "lookup", "module", "import"),
        ),
        (
            "official-lookup-attribute-error",
            "_harness_resolution_faults:published_archive_date_lookup",
            "_harness_resolution_faults:missing_official_md5_lookup",
            ("official", "md5", "lookup", "attribute", "missing_official_md5_lookup"),
        ),
    ),
)
def test_execute_handles_lookup_resolution_errors_with_typed_refusal(
    case_id: str,
    published_spec: str,
    official_spec: str,
    expected_fragments: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Finding #3: transport resolution can no longer fail via any CLI-
    # injected spec at all -- production/executable acquisition is
    # hard-wired to `prospective_exact_source_transport.build_transport()`.
    # Only the two lookup ports remain dynamically resolved via
    # 'module:callable' specs, so this test now exercises only their
    # failure modes.
    harness = _load_harness_module()
    with prospective_sandbox(f"harness-resolution-errors-{case_id}") as sandbox:
        transport_ctor_calls = {"count": 0}

        def _build_transport(**_kwargs: Any) -> Any:
            transport_ctor_calls["count"] += 1
            return _StubTransport()

        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", _build_transport)

        faults = _install_fake_injections_module(
            monkeypatch,
            module_name="_harness_resolution_faults",
            published_lookup=lambda _url: {"published_archive_date": "2026-08-06", "source_identity": "fake-published"},
            official_md5_lookup=lambda _url: {"official_md5": "0" * 32, "source_identity": "fake-md5"},
        )

        approval_path = sandbox.root / "approval.json"
        _write_json(approval_path, build_approval_record(sandbox))

        factory_calls, import_calls, constructor_calls, network_calls = _transport_resolution_spies(monkeypatch)
        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_path,
                registration_spec=sandbox.spec_path,
                overlay=sandbox.overlay_path,
                base_config=sandbox.base_eval_config_path,
                allowed_repo_root=sandbox.repo_root,
                allowed_external_root=sandbox.external_root,
                published_archive_date_lookup=published_spec,
                official_md5_lookup=official_spec,
            ),
        )
        captured = capsys.readouterr()
        assert network_calls == []
        # The hard-wired transport is always constructed before either
        # lookup is resolved (see run_clinvar_2026_08_prospective_freeze.py
        # main()), so it is called exactly once regardless of which lookup
        # fails.
        assert transport_ctor_calls["count"] == 1
        _assert_typed_nonzero_without_traceback(
            rc=rc,
            exc=exc,
            output=captured.out + captured.err,
            expected_fragments=expected_fragments,
            allowed_rc=(2,),
        )
        assert factory_calls == []
        assert constructor_calls == []
        assert "_harness_resolution_faults" in import_calls or "__missing" in published_spec or "__missing" in official_spec


@pytest.mark.parametrize(
    ("case_id", "expected_fragments"),
    (
        ("malformed-overlay-yaml", ("overlay", "yaml", "parse")),
        ("missing-overlay-required-key", ("overlay", "transport_freeze_record", "required key")),
    ),
)
def test_execute_handles_overlay_load_or_shape_errors_with_typed_refusal(
    case_id: str,
    expected_fragments: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness_module()
    with prospective_sandbox(f"harness-overlay-errors-{case_id}") as sandbox:
        _install_fake_injections_module(monkeypatch)
        transport_ctor_calls = {"count": 0}

        def _record_factory(**_kwargs: Any) -> Any:
            transport_ctor_calls["count"] += 1
            return _StubTransport()

        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", _record_factory)
        factory_calls, import_calls, constructor_calls, network_calls = _transport_resolution_spies(monkeypatch)
        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")

        if case_id == "malformed-overlay-yaml":
            sandbox.overlay_path.write_text("schema: [\n", encoding="utf-8")
        elif case_id == "missing-overlay-required-key":
            text = sandbox.overlay_path.read_text(encoding="utf-8")
            needle = 'transport_freeze_record: "data/census/tsc_prospective_validation_2026-08_amendment_v2_transport_freeze.json"\n'
            if needle not in text:
                pytest.fail("expected transport_freeze_record key in overlay fixture")
            sandbox.overlay_path.write_text(text.replace(needle, "", 1), encoding="utf-8")
        else:  # pragma: no cover
            pytest.fail(f"unknown case_id={case_id!r}")

        approval = build_approval_record(sandbox)
        approval_path = sandbox.root / "approval.json"
        _write_json(approval_path, approval)

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_path,
                registration_spec=sandbox.spec_path,
                overlay=sandbox.overlay_path,
                base_config=sandbox.base_eval_config_path,
                allowed_repo_root=sandbox.repo_root,
                allowed_external_root=sandbox.external_root,
            ),
        )
        captured = capsys.readouterr()
        assert network_calls == []
        assert transport_ctor_calls["count"] == 1
        _assert_typed_nonzero_without_traceback(
            rc=rc,
            exc=exc,
            output=captured.out + captured.err,
            expected_fragments=expected_fragments,
            allowed_rc=(2,),
        )
        assert factory_calls == []
        assert constructor_calls == []
        assert import_calls != []


@pytest.mark.parametrize(
    ("case_id", "exception_name", "reason_code", "reason_text", "expected_rc", "allow_transport_record"),
    (
        ("executor-policy-error", "ExactSourceTransportPolicyError", "REDIRECT_NOT_ALLOWED", "redirect refused", 3, False),
        ("executor-get-time-error", "ExactSourceTransportError", None, "GET failed mid-stream", 3, True),
    ),
)
def test_execute_handles_executor_transport_errors_with_typed_output_and_no_raw_record(
    case_id: str,
    exception_name: str,
    reason_code: str | None,
    reason_text: str,
    expected_rc: int,
    allow_transport_record: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness_module()
    with prospective_sandbox(f"harness-executor-transport-errors-{case_id}") as sandbox:
        _install_fake_injections_module(monkeypatch)
        approval = build_approval_record(sandbox)
        approval_path = sandbox.root / "approval.json"
        _write_json(approval_path, approval)

        factory_calls, import_calls, constructor_calls, network_calls = _transport_resolution_spies(monkeypatch)
        transport_ctor_calls = {"count": 0}

        def _record_factory(**_kwargs: Any) -> Any:
            factory_calls.append("build_transport")
            constructor_calls.append("build_transport")
            transport_ctor_calls["count"] += 1
            return _StubTransport()

        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", _record_factory)
        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")

        error_type = _transport_exception_type(exception_name)

        def _raising_execute(**kwargs: Any) -> dict[str, Any]:
            transport_record_path = Path(kwargs["transport_freeze_record_path"])
            raw_record_path = Path(kwargs["raw_freeze_record_path"])
            if allow_transport_record:
                transport_record_path.parent.mkdir(parents=True, exist_ok=True)
                transport_record_path.write_text(
                    json.dumps({"schema": "raptor.eval.prospective_transport_freeze.v1", "status": "TRANSPORT_FROZEN"}) + "\n",
                    encoding="utf-8",
                )
            raw_record_path.unlink(missing_ok=True)
            if reason_code is None:
                raise error_type(reason_text)
            raise error_type(reason_code, reason_text)

        monkeypatch.setattr(harness.prospective_freeze, "execute_transport_and_raw_freeze", _raising_execute)

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_path,
                registration_spec=sandbox.spec_path,
                overlay=sandbox.overlay_path,
                base_config=sandbox.base_eval_config_path,
                allowed_repo_root=sandbox.repo_root,
                allowed_external_root=sandbox.external_root,
                transport_record=sandbox.transport_record_path,
                raw_record=sandbox.raw_record_path,
            ),
        )
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert network_calls == []
        assert factory_calls != []
        assert constructor_calls != []
        assert transport_ctor_calls["count"] == 1
        assert import_calls != []
        if allow_transport_record:
            assert sandbox.transport_record_path.exists()
        assert not sandbox.raw_record_path.exists()
        _assert_typed_nonzero_without_traceback(
            rc=rc,
            exc=exc,
            output=output,
            expected_fragments=(
                exception_name,
                reason_text,
                reason_code or "transport",
            ),
            allowed_rc=(expected_rc,),
        )


def test_execute_success_forwards_registered_paths_and_unset_stage3_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness_module()
    with prospective_sandbox("harness-success-forwarding") as sandbox:
        assert sandbox.external_root.exists()
        assert sandbox.external_root.is_dir()
        assert not sandbox.external_root.is_symlink()
        assert sandbox.external_root.resolve() == sandbox.external_root
        assert sandbox.external_root.resolve() != sandbox.repo_root.resolve()

        approval = build_approval_record(sandbox)
        approval_path = sandbox.root / "approval.json"
        _write_json(approval_path, approval)

        call_order: list[str] = []
        sentinel_transport = _StubTransport()
        published_lookup = lambda _url: {"published_archive_date": "2026-08-06", "source_identity": "fake-published"}
        official_md5_lookup = lambda _url: {"official_md5": "0" * 32, "source_identity": "fake-md5"}

        def _build_transport() -> Any:
            call_order.append("resolve_transport")
            return sentinel_transport

        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", _build_transport)
        _install_fake_injections_module(
            monkeypatch,
            published_lookup=published_lookup,
            official_md5_lookup=official_md5_lookup,
        )

        def _fake_validate(
            *,
            registration_spec_path: Any,
            prospective_overlay_path: Any,
            approval_record: dict[str, Any],
            first_archive_get_at: str | None = None,
        ) -> dict[str, Any]:
            call_order.append("validate")
            assert Path(registration_spec_path) == sandbox.spec_path
            assert Path(prospective_overlay_path) == sandbox.overlay_path
            assert first_archive_get_at is None
            assert approval_record == approval
            return copy.deepcopy(approval)

        def _fake_execute(**kwargs: Any) -> dict[str, Any]:
            call_order.append("execute")
            # Finding #4: acquisition never forwards base_eval_config_path
            # (or any scoring-semantics identity) to execute_transport_and_raw_freeze.
            assert "base_eval_config_path" not in kwargs
            assert Path(kwargs["registration_spec_path"]) == sandbox.spec_path
            assert Path(kwargs["prospective_overlay_path"]) == sandbox.overlay_path
            assert kwargs["approval_record"] == approval
            assert Path(kwargs["allowed_repo_root"]) == sandbox.repo_root
            assert Path(kwargs["allowed_external_root"]) == sandbox.external_root
            expected_transport_record = sandbox.repo_root / str(sandbox.overlay["transport_freeze_record"])
            expected_raw_record = sandbox.repo_root / str(sandbox.overlay["raw_freeze_record"])
            assert Path(kwargs["transport_freeze_record_path"]) == expected_transport_record
            assert Path(kwargs["raw_freeze_record_path"]) == expected_raw_record
            assert kwargs["transport"] is sentinel_transport
            assert kwargs["published_archive_date_lookup"] is published_lookup
            assert kwargs["official_md5_lookup"] is official_md5_lookup
            assert kwargs.get("label_reader") is None
            assert kwargs.get("benchmark_builder") is None
            assert kwargs.get("scoring_runner") is None
            return {
                "stage_status": "TRANSPORT_AND_RAW_FROZEN",
                "terminal_outcome": None,
                "reason_code": None,
            }

        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")
        monkeypatch.setattr(harness.prospective_freeze, "validate_pre_data_approval", _fake_validate)
        monkeypatch.setattr(harness.prospective_freeze, "execute_transport_and_raw_freeze", _fake_execute)

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_path,
                registration_spec=sandbox.spec_path,
                overlay=sandbox.overlay_path,
                base_config=sandbox.base_eval_config_path,
                allowed_repo_root=sandbox.repo_root,
                allowed_external_root=sandbox.external_root,
            ),
        )
        assert exc is None
        assert rc == 0
        assert call_order[0] == "validate"
        assert "resolve_transport" in call_order
        assert call_order[-1] == "execute"


def test_execute_refuses_transport_tampered_by_caller_selected_lookup_module(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Finding #1 (CLI-level regression): `main()` must capture the
    transport identity pin immediately after `build_transport()` returns --
    BEFORE either `--published-archive-date-lookup`/`--official-md5-lookup`
    'module:callable' spec is even imported -- and thread it into
    `execute_transport_and_raw_freeze` (both unmocked here; only
    `build_transport` is replaced, exactly as production would call it, so
    the real transport-tamper re-verification actually runs end to end).
    A caller-selected lookup CALLABLE -- arbitrary code the harness itself
    imports and invokes via the dynamically-resolved 'module:callable'
    spec, running between the real HEAD and the real GET -- that
    monkeypatches `type(transport).stream_get` (e.g. to silently swap the
    downloaded bytes) while still returning well-formed, matching
    metadata must be refused with TRANSPORT_IDENTITY_TAMPERED before any
    real network GET; the real GET must never be reached and no raw
    archive record may be written. This is the CLI's own wiring gap the
    finding identified -- distinct from (and complementary to) the
    freeze-level red tests that exercise `execute_transport_and_raw_freeze`
    directly without going through this script's `main()`."""
    harness = _load_harness_module()
    with prospective_sandbox("harness-transport-tamper-live") as sandbox:
        approval = build_approval_record(sandbox)
        approval_path = sandbox.root / "approval.json"
        _write_json(approval_path, approval)

        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", lambda **_kwargs: transport)
        original_stream_get = type(transport).stream_get

        def _malicious_published_lookup(_url: str) -> dict[str, Any]:
            def _tampered_stream_get(self: Any, url: str, chunk_bytes: int) -> Any:
                raise AssertionError("tampered stream_get must never be invoked")

            # The attack: caller-selected code, resolved and invoked by
            # production itself between the real HEAD and the real GET,
            # monkeypatches the transport CLASS's stream_get -- while still
            # returning well-formed, matching lookup metadata so neither
            # `_verify_published_date` nor the ordinary happy path would
            # otherwise notice anything wrong.
            type(transport).stream_get = _tampered_stream_get
            return {"published_archive_date": "2026-08-06", "source_identity": "fake-published"}

        module_name = "_harness_malicious_lookup_tamper"
        fake_module = types.ModuleType(module_name)
        fake_module.published_archive_date_lookup = _malicious_published_lookup
        fake_module.official_md5_lookup = lambda _url: {"official_md5": "0" * 32, "source_identity": "fake-md5"}
        monkeypatch.setitem(sys.modules, module_name, fake_module)

        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")

        try:
            rc, exc = _invoke_main(
                harness,
                _execute_argv(
                    approval_record=approval_path,
                    registration_spec=sandbox.spec_path,
                    overlay=sandbox.overlay_path,
                    base_config=sandbox.base_eval_config_path,
                    allowed_repo_root=sandbox.repo_root,
                    allowed_external_root=sandbox.external_root,
                    published_archive_date_lookup=f"{module_name}:published_archive_date_lookup",
                    official_md5_lookup=f"{module_name}:official_md5_lookup",
                    transport_record=sandbox.transport_record_path,
                    raw_record=sandbox.raw_record_path,
                ),
            )
            captured = capsys.readouterr()
            output = captured.out + captured.err
            assert exc is None
            assert rc == 3
            assert "TRANSPORT_IDENTITY_TAMPERED" in output
            assert "Traceback (most recent call last)" not in output
            assert transport.get_calls == []
            assert not sandbox.raw_record_path.exists()
        finally:
            type(transport).stream_get = original_stream_get


@pytest.mark.parametrize(
    ("terminal_outcome", "reason_code"),
    (
        ("BLOCKED_DATA", "HEAD_STATUS_MISMATCH"),
        ("INVALID", "DESTINATION_OUTSIDE_ALLOWED_ROOT"),
    ),
)
def test_execute_typed_exit_for_blocked_or_invalid_results_is_nonzero_with_reason(
    terminal_outcome: str,
    reason_code: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness_module()
    with prospective_sandbox(f"harness-exit-{terminal_outcome.lower()}") as sandbox:
        _install_fake_injections_module(monkeypatch)
        approval = build_approval_record(sandbox)
        approval_path = sandbox.root / "approval.json"
        _write_json(approval_path, approval)

        monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(harness.sys, "executable", "/home/sdrona/raptor/bin/python")
        monkeypatch.setattr(
            harness.prospective_freeze,
            "validate_pre_data_approval",
            lambda **_kwargs: copy.deepcopy(approval),
        )
        monkeypatch.setattr(harness.prospective_exact_source_transport, "build_transport", lambda **_kwargs: _StubTransport())
        monkeypatch.setattr(
            harness.prospective_freeze,
            "execute_transport_and_raw_freeze",
            lambda **_kwargs: {
                "stage_status": "BLOCKED",
                "terminal_outcome": terminal_outcome,
                "reason_code": reason_code,
            },
        )

        rc, exc = _invoke_main(
            harness,
            _execute_argv(
                approval_record=approval_path,
                registration_spec=sandbox.spec_path,
                overlay=sandbox.overlay_path,
                base_config=sandbox.base_eval_config_path,
                allowed_repo_root=sandbox.repo_root,
                allowed_external_root=sandbox.external_root,
            ),
        )
        captured = capsys.readouterr()
        assert exc is None
        assert rc is not None and rc != 0
        assert terminal_outcome in (captured.out + captured.err)
        assert reason_code in (captured.out + captured.err)
        assert "Traceback (most recent call last)" not in (captured.out + captured.err)


def test_repository_draft_approval_stays_nonapproved_and_pre_data_attestation_false() -> None:
    if not DRAFT_APPROVAL_PATH.is_file():
        pytest.fail(f"RED: missing prep artifact {DRAFT_APPROVAL_PATH}")
    payload = json.loads(DRAFT_APPROVAL_PATH.read_text(encoding="utf-8"))
    assert payload.get("decision") != "APPROVED_PRE_DATA"
    attestation = payload.get("pre_data_access_attestation")
    assert isinstance(attestation, dict)
    assert set(attestation.keys()) == {
        "archive_get_requested",
        "archive_content_downloaded",
        "archive_bytes_hashed",
        "archive_decompressed",
        "labels_inspected",
        "rows_inspected",
        "benchmark_derived",
        "scoring_performed",
    }
    assert all(value is False for value in attestation.values())


def test_validate_pre_data_approval_rejects_repository_draft_closed_schema() -> None:
    if not DRAFT_APPROVAL_PATH.is_file():
        pytest.fail(f"RED: missing prep artifact {DRAFT_APPROVAL_PATH}")
    validate = require_api("validate_pre_data_approval")
    stop_error = require_exception("ProspectiveStopStateError")
    payload = json.loads(DRAFT_APPROVAL_PATH.read_text(encoding="utf-8"))
    with pytest.raises(stop_error) as exc:
        validate(
            registration_spec_path=SPEC_PATH,
            prospective_overlay_path=OVERLAY_PATH,
            approval_record=payload,
            first_archive_get_at=None,
        )
    assert_stop_state(exc.value, "PRE_DATA_REVIEW_REQUIRED")
    reason = getattr(exc.value, "reason", "")
    assert "top-level keys" in str(reason)


def test_validate_pre_data_approval_rejects_draft_decision_after_commentary_removed() -> None:
    if not DRAFT_APPROVAL_PATH.is_file():
        pytest.fail(f"RED: missing prep artifact {DRAFT_APPROVAL_PATH}")
    payload = json.loads(DRAFT_APPROVAL_PATH.read_text(encoding="utf-8"))
    cleaned = _strip_commentary_keys(payload)
    if not isinstance(cleaned, dict):
        pytest.fail("cleaned draft approval must remain a mapping")

    validate = require_api("validate_pre_data_approval")
    stop_error = require_exception("ProspectiveStopStateError")
    with pytest.raises(stop_error) as exc:
        validate(
            registration_spec_path=SPEC_PATH,
            prospective_overlay_path=OVERLAY_PATH,
            approval_record=cleaned,
            first_archive_get_at=None,
        )
    assert_stop_state(exc.value, "PRE_DATA_REVIEW_REQUIRED")
    reason = getattr(exc.value, "reason", "")
    assert "decision must be APPROVED_PRE_DATA" in str(reason)


def test_draft_implementation_freeze_is_placeholder_or_commit_coherent_tree() -> None:
    if not DRAFT_APPROVAL_PATH.is_file():
        pytest.fail(f"RED: missing prep artifact {DRAFT_APPROVAL_PATH}")
    payload = json.loads(DRAFT_APPROVAL_PATH.read_text(encoding="utf-8"))
    cleaned = _strip_commentary_keys(payload)
    if not isinstance(cleaned, dict):
        pytest.fail("cleaned draft approval must remain a mapping")
    assert cleaned.get("decision") != "APPROVED_PRE_DATA"

    implementation_freeze = cleaned.get("implementation_freeze")
    if not isinstance(implementation_freeze, dict):
        pytest.fail("draft implementation_freeze block must be a mapping")
    commit = implementation_freeze.get("commit")
    module_hashes = implementation_freeze.get("module_hashes")
    if not isinstance(commit, str) or not commit.strip():
        pytest.fail("draft implementation_freeze.commit must be non-blank")
    if not isinstance(module_hashes, dict) or not module_hashes:
        pytest.fail("draft implementation_freeze.module_hashes must be a non-empty mapping")

    if commit == "NOT_YET_COMMITTED":
        assert all(isinstance(v, str) and v for v in module_hashes.values())
        return

    commit_probe = _run_git_with_worktree("cat-file", "-e", f"{commit}" + "^{commit}")
    _assert_git_usable(commit_probe, context="draft implementation_freeze commit probe")
    if commit_probe.returncode != 0:
        pytest.fail(
            f"draft implementation_freeze.commit {commit!r} is not reachable in configured worktree metadata; "
            f"stderr={_stderr_text(commit_probe.stderr)}"
        )

    for module_name, expected_hash in module_hashes.items():
        assert isinstance(module_name, str) and module_name.strip()
        assert isinstance(expected_hash, str) and len(expected_hash) == 64
        module_rel = (Path("src") / Path(*module_name.split("."))).with_suffix(".py")
        shown = _run_git_with_worktree("show", f"{commit}:{module_rel.as_posix()}")
        _assert_git_usable(shown, context=f"draft implementation_freeze module probe {module_name!r}")
        if shown.returncode != 0:
            pytest.fail(
                f"module {module_name!r} not present in committed tree {commit}; "
                f"stderr={_stderr_text(shown.stderr)}"
            )
        assert _sha256_hex(_canonical_lf_bytes(shown.stdout)) == expected_hash


def test_validate_pre_data_approval_rejects_approved_not_yet_committed_implementation_freeze() -> None:
    validate = require_api("validate_pre_data_approval")
    stop_error = require_exception("ProspectiveStopStateError")
    with prospective_sandbox("approval-implementation-freeze-placeholder") as sandbox:
        approval = build_approval_record(sandbox, decision="APPROVED_PRE_DATA")
        approval["implementation_freeze"] = draft_placeholder_implementation_freeze()
        with pytest.raises(stop_error) as exc:
            validate(
                registration_spec_path=sandbox.spec_path,
                prospective_overlay_path=sandbox.overlay_path,
                approval_record=approval,
                first_archive_get_at=None,
            )
        assert_stop_state(exc.value, "PRE_DATA_IMPLEMENTATION_NOT_READY")


def test_validate_pre_data_approval_rejects_approved_reachable_commit_with_stale_module_hashes() -> None:
    stop_error = require_exception("ProspectiveStopStateError")
    stale_commit = "c039383b098cbce89411e10c0b61d9b707c31eb9"
    commit_probe = _run_git_with_worktree("cat-file", "-e", f"{stale_commit}" + "^{commit}")
    _assert_git_usable(commit_probe, context="stale implementation_freeze commit probe")
    if commit_probe.returncode != 0:
        pytest.fail(
            f"fixture commit {stale_commit!r} must be reachable for stale module-hash validation; "
            f"stderr={_stderr_text(commit_probe.stderr)}"
        )

    missing_transport_probe = _run_git_with_worktree(
        "cat-file",
        "-e",
        f"{stale_commit}:src/raptor/eval/prospective_exact_source_transport.py",
    )
    _assert_git_usable(missing_transport_probe, context="stale implementation_freeze transport-module probe")
    if missing_transport_probe.returncode == 0:
        pytest.fail("fixture expectation breached: stale commit unexpectedly contains prospective_exact_source_transport")

    with prospective_sandbox("approval-implementation-freeze-stale-commit") as sandbox:
        approval = build_approval_record(sandbox, decision="APPROVED_PRE_DATA")
        approval["implementation_freeze"] = {
            "commit": stale_commit,
            "module_hashes": {
                "raptor.eval.prospective_freeze": "0" * 64,
                "raptor.eval.prospective_exact_source_transport": "1" * 64,
            },
        }
        with pytest.raises(stop_error) as exc:
            prospective_red_helpers.validate_pre_data_approval(
                sandbox,
                approval_record=approval,
                first_archive_get_at=None,
            )
        assert_stop_state(exc.value, "PRE_DATA_IMPLEMENTATION_NOT_READY")
        reason = str(getattr(exc.value, "reason", ""))
        assert reason
        assert (
            "canonical-lf sha256 does not match commit" in reason.lower()
            or "is not present in the committed tree" in reason.lower()
        )
        assert "not a reachable commit" not in reason.lower()
        assert "could not be verified: git is unavailable" not in reason.lower()


def test_helper_git_metadata_resolution_supports_no_env_checkout_forms_and_strict_declared_modules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)

    linked_git_dir, linked_work_tree = prospective_red_helpers._resolve_git_metadata()
    assert Path(linked_work_tree) == REPO_ROOT
    assert Path(linked_git_dir).is_dir()

    dot_git = REPO_ROOT / ".git"
    if dot_git.is_file():
        gitdir_raw = prospective_red_helpers._parse_linked_worktree_gitdir_pointer(dot_git)
        translated = prospective_red_helpers._translate_windows_drive_to_wsl(gitdir_raw)
        if translated is not None:
            assert Path(translated).is_dir()
    elif dot_git.is_dir():
        assert Path(linked_git_dir) == dot_git
    else:
        pytest.fail(f"unexpected checkout metadata form at {dot_git}")

    synthetic_checkout = tmp_path / "synthetic-standard-checkout"
    synthetic_checkout.mkdir(parents=True, exist_ok=False)
    synthetic_git_dir = synthetic_checkout / ".git"
    synthetic_git_dir.mkdir()
    monkeypatch.setattr(prospective_red_helpers, "REPO_ROOT", synthetic_checkout)
    standard_git_dir, standard_work_tree = prospective_red_helpers._resolve_git_metadata()
    assert Path(standard_git_dir) == synthetic_git_dir
    assert Path(standard_work_tree) == synthetic_checkout

    monkeypatch.setattr(prospective_red_helpers, "REPO_ROOT", REPO_ROOT)
    stale_commit = "c039383b098cbce89411e10c0b61d9b707c31eb9"
    commit_probe = _run_git_with_worktree("cat-file", "-e", f"{stale_commit}" + "^{commit}")
    _assert_git_usable(commit_probe, context="strict implementation_freeze commit probe")
    if commit_probe.returncode != 0:
        pytest.fail(f"fixture commit must be reachable for strict resolver check: {stale_commit}")
    with pytest.raises(pytest.fail.Exception) as exc:
        resolve_committed_implementation_freeze(
            stale_commit,
            module_names=(
                "raptor.eval.prospective_freeze",
                "raptor.eval.prospective_exact_source_transport",
            ),
        )
    assert "incomplete for declared modules" in str(exc.value).lower()


def test_validate_pre_data_approval_rejects_approved_unresolvable_implementation_commit_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_error = require_exception("ProspectiveStopStateError")
    unresolvable_commit = hashlib.sha1(uuid.uuid4().bytes).hexdigest()
    commit_probe = _run_git_with_worktree("cat-file", "-e", f"{unresolvable_commit}" + "^{commit}")
    _assert_git_usable(commit_probe, context="unresolvable implementation_freeze commit probe")
    if commit_probe.returncode == 0:
        pytest.fail(f"fixture generation produced reachable commit unexpectedly: {unresolvable_commit}")

    network_calls: list[str] = []

    def _deny_socket(*_args: Any, **_kwargs: Any) -> Any:
        network_calls.append("socket")
        raise AssertionError("approval validation must not open sockets")

    def _deny_create_connection(*_args: Any, **_kwargs: Any) -> Any:
        network_calls.append("create_connection")
        raise AssertionError("approval validation must not create network connections")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    monkeypatch.setattr(socket, "create_connection", _deny_create_connection)

    with prospective_sandbox("approval-implementation-freeze-unresolvable-commit") as sandbox:
        approval = build_approval_record(sandbox, decision="APPROVED_PRE_DATA")
        approval["implementation_freeze"] = {
            "commit": unresolvable_commit,
            "module_hashes": copy.deepcopy(approval["implementation_freeze"]["module_hashes"]),
        }
        with pytest.raises(stop_error) as exc:
            prospective_red_helpers.validate_pre_data_approval(
                sandbox,
                approval_record=approval,
                first_archive_get_at=None,
            )
        assert_stop_state(exc.value, "PRE_DATA_IMPLEMENTATION_NOT_READY")
        reason = str(getattr(exc.value, "reason", ""))
        assert "not a reachable commit" in reason.lower()
        assert "canonical-lf sha256 does not match commit" not in reason.lower()
        assert "is not present in the committed tree" not in reason.lower()
        assert "could not be verified: git is unavailable" not in reason.lower()
    assert network_calls == []


def test_validate_pre_data_approval_rejects_approved_when_git_metadata_is_unusable_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = require_api("validate_pre_data_approval")
    stop_error = require_exception("ProspectiveStopStateError")
    network_calls: list[str] = []

    def _deny_socket(*_args: Any, **_kwargs: Any) -> Any:
        network_calls.append("socket")
        raise AssertionError("approval validation must not open sockets")

    def _deny_create_connection(*_args: Any, **_kwargs: Any) -> Any:
        network_calls.append("create_connection")
        raise AssertionError("approval validation must not create network connections")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    monkeypatch.setattr(socket, "create_connection", _deny_create_connection)

    with prospective_sandbox("approval-implementation-freeze-git-metadata-unusable") as sandbox:
        approval = build_approval_record(sandbox, decision="APPROVED_PRE_DATA")

        bad_git_dir = sandbox.root / "invalid-git-dir"
        bad_work_tree = sandbox.root / "invalid-work-tree"
        monkeypatch.setenv("GIT_DIR", str(bad_git_dir))
        monkeypatch.setenv("GIT_WORK_TREE", str(bad_work_tree))
        git_probe = subprocess.run(
            [
                "git",
                "--no-pager",
                "--git-dir",
                str(bad_git_dir),
                "--work-tree",
                str(bad_work_tree),
                "rev-parse",
                "--verify",
                "HEAD",
            ],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
        assert git_probe.returncode != 0

        with pytest.raises(stop_error) as exc:
            validate(
                registration_spec_path=sandbox.spec_path,
                prospective_overlay_path=sandbox.overlay_path,
                approval_record=approval,
                first_archive_get_at=None,
            )
        assert_stop_state(exc.value, "PRE_DATA_IMPLEMENTATION_NOT_READY")
    assert network_calls == []


def test_external_root_doc_matches_only_enforced_expectations() -> None:
    if not EXTERNAL_ROOT_DOC_PATH.is_file():
        pytest.fail(f"RED: missing prep artifact {EXTERNAL_ROOT_DOC_PATH}")
    text = EXTERNAL_ROOT_DOC_PATH.read_text(encoding="utf-8")
    normalized = " ".join(text.lower().split())
    assert "must already exist, be a plain directory (not a symlink)" in normalized
    assert "must be empty of any stale prior run content" not in normalized
    assert "must contain no symlinked ancestor at any point in its path" not in normalized
    assert "_validate_destination_boundary rejects both unconditionally" not in normalized
